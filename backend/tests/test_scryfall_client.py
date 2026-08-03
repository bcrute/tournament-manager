"""The HTTP client itself — the app's only outbound call.

`test_card_rulings.py` covers what the routes do with card data, using
`FakeUpstream`. This covers the layer underneath it: the request that actually
goes out, and the mapping from "what a remote server did" to "what this app
does about it".

That mapping is the whole value. A 404 means a card nobody has heard of, which
is a normal answer and must reach the user as a 404. Anything else — a 500, a
timeout, DNS failure, TLS failure, a body that is not JSON — means *we* cannot
answer, which is a different outcome with different handling (cache fallback,
backoff, a link). Getting those two confused is how a typo starts reporting an
outage, or an outage starts telling people their card does not exist.

Nothing here opens a socket. `urlopen` is replaced, so the failure modes are
reachable on purpose rather than by pulling a cable.
"""

import io
import json
import urllib.error

import pytest

from app import scryfall
from app.scryfall import (
    USER_AGENT,
    FileUpstream,
    HttpUpstream,
    UpstreamUnavailable,
    build_upstream,
)


class Response(io.BytesIO):
    """Enough of an HTTP response for `with urlopen(...) as r: r.read()`."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def serving(monkeypatch, payload, capture=None):
    """Replace `urlopen` with something that returns `payload`."""

    def fake_urlopen(request, timeout=None):
        if capture is not None:
            capture["request"] = request
            capture["timeout"] = timeout
        body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
        return Response(body.encode() if isinstance(body, str) else body)

    monkeypatch.setattr(scryfall.urllib.request, "urlopen", fake_urlopen)


def failing(monkeypatch, error):
    def fake_urlopen(request, timeout=None):
        raise error

    monkeypatch.setattr(scryfall.urllib.request, "urlopen", fake_urlopen)


def http_error(code):
    return urllib.error.HTTPError(
        url="https://api.scryfall.com/x", code=code, msg="nope", hdrs=None, fp=None
    )


class TestTheRequestItself:
    def test_it_identifies_this_app(self, monkeypatch):
        """Scryfall asks for a descriptive User-Agent so they can contact
        whoever is misbehaving. Taking their bandwidth anonymously would be
        rude, and they are within their rights to block it."""
        seen = {}
        serving(monkeypatch, {"data": ["Sol Ring"]}, seen)
        HttpUpstream().card_names()

        request = seen["request"]
        assert request.get_header("User-agent") == USER_AGENT
        assert "mtg.skadoosh.dev" in USER_AGENT, "contactable, not just distinctive"
        assert request.get_header("Accept") == "application/json"

    def test_it_does_not_wait_forever(self, monkeypatch):
        """No timeout means a hung upstream hangs a worker thread, and enough
        of those is the whole app."""
        seen = {}
        serving(monkeypatch, {"data": ["Sol Ring"]}, seen)
        HttpUpstream().card_names()
        assert seen["timeout"] == scryfall.TIMEOUT
        assert 0 < scryfall.TIMEOUT <= 15

    def test_a_card_name_is_encoded_into_the_query(self, monkeypatch):
        """Card names contain commas, apostrophes, spaces and the occasional
        ampersand. Pasted into a URL raw, some of them silently become a
        different request."""
        seen = {}
        serving(monkeypatch, {"id": "x"}, seen)
        HttpUpstream().named("Jace, the Mind Sculptor")
        url = seen["request"].full_url
        assert " " not in url
        assert "exact=Jace%2C+the+Mind+Sculptor" in url

    def test_it_calls_the_documented_endpoints(self, monkeypatch):
        seen = {}
        serving(monkeypatch, {"data": []}, seen)
        HttpUpstream().rulings("abc-123")
        assert seen["request"].full_url == "https://api.scryfall.com/cards/abc-123/rulings"

    def test_the_base_url_is_overridable_without_touching_the_code(self, monkeypatch):
        seen = {}
        serving(monkeypatch, {"data": ["x"]}, seen)
        HttpUpstream(base="https://mirror.example").card_names()
        assert seen["request"].full_url.startswith("https://mirror.example/")


class TestWhatAFailureMeans:
    """404 is an answer. Everything else is an outage, and they are handled
    completely differently upstream of here."""

    def test_a_404_is_a_missing_card_not_an_outage(self, monkeypatch):
        failing(monkeypatch, http_error(404))
        with pytest.raises(LookupError):
            HttpUpstream().named("Definitely Not A Card")

    def test_a_500_is_an_outage(self, monkeypatch):
        failing(monkeypatch, http_error(500))
        with pytest.raises(UpstreamUnavailable):
            HttpUpstream().named("Sol Ring")

    def test_being_rate_limited_is_an_outage_not_a_missing_card(self, monkeypatch):
        """429 is the one this app could plausibly earn by asking too often,
        and reporting it as "no such card" would send everybody hunting a
        spelling mistake."""
        failing(monkeypatch, http_error(429))
        with pytest.raises(UpstreamUnavailable):
            HttpUpstream().named("Sol Ring")

    def test_a_timeout_is_an_outage(self, monkeypatch):
        failing(monkeypatch, TimeoutError("timed out"))
        with pytest.raises(UpstreamUnavailable):
            HttpUpstream().card_names()

    def test_dns_and_tls_failures_are_outages(self, monkeypatch):
        for error in (urllib.error.URLError("no route"), OSError("tls handshake")):
            failing(monkeypatch, error)
            with pytest.raises(UpstreamUnavailable):
                HttpUpstream().card_names()

    def test_a_body_that_is_not_json_is_an_outage(self, monkeypatch):
        """A captive portal or a proxy error page answers 200 with HTML. That
        is not a card, and it must not crash on the way to saying so."""
        serving(monkeypatch, "<html>proxy error</html>")
        with pytest.raises(UpstreamUnavailable):
            HttpUpstream().card_names()

    def test_the_message_says_what_happened(self, monkeypatch):
        failing(monkeypatch, http_error(503))
        with pytest.raises(UpstreamUnavailable, match="503"):
            HttpUpstream().named("Sol Ring")


class TestTheCatalogue:
    def test_it_returns_the_names(self, monkeypatch):
        serving(monkeypatch, {"data": ["Sol Ring", "Lightning Bolt"]})
        assert HttpUpstream().card_names() == ["Sol Ring", "Lightning Bolt"]

    def test_an_empty_catalogue_is_refused(self, monkeypatch):
        """A 200 carrying nothing would otherwise wipe the local index and
        break search with no error anywhere — the worst shape of failure,
        because it looks like the feature simply stopped finding things."""
        serving(monkeypatch, {"data": []})
        with pytest.raises(UpstreamUnavailable):
            HttpUpstream().card_names()

    def test_a_malformed_catalogue_is_refused(self, monkeypatch):
        for payload in ({"data": "not a list"}, {}, {"data": None}):
            serving(monkeypatch, payload)
            with pytest.raises(UpstreamUnavailable):
                HttpUpstream().card_names()

    def test_non_string_entries_are_dropped_rather_than_stored(self, monkeypatch):
        serving(monkeypatch, {"data": ["Sol Ring", None, 42, "Lightning Bolt"]})
        assert HttpUpstream().card_names() == ["Sol Ring", "Lightning Bolt"]


class TestRulingsShape:
    def test_it_unwraps_the_data_list(self, monkeypatch):
        serving(monkeypatch, {"data": [{"comment": "a ruling"}]})
        assert HttpUpstream().rulings("x") == [{"comment": "a ruling"}]

    def test_a_card_with_no_rulings_is_an_empty_list_not_an_error(self, monkeypatch):
        """Which is the common case — Lightning Bolt has none."""
        serving(monkeypatch, {"data": []})
        assert HttpUpstream().rulings("x") == []

    def test_a_missing_or_malformed_data_key_is_still_an_empty_list(self, monkeypatch):
        """Rulings are the least important half of the answer: the card and its
        link are still worth showing, so a surprise here degrades rather than
        fails."""
        for payload in ({}, {"data": None}, {"data": "nope"}):
            serving(monkeypatch, payload)
            assert HttpUpstream().rulings("x") == []


class TestTheFixtureTransport:
    """What the browser suite actually runs on.

    It had no test of its own, which is the wrong way round: a break here fails
    ten browser tests confusingly instead of one unit test clearly.
    """

    def fixture(self, tmp_path, payload):
        path = tmp_path / "cards.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return FileUpstream(str(path))

    def test_it_serves_names_cards_and_rulings(self, tmp_path):
        up = self.fixture(
            tmp_path,
            {
                "names": ["Sol Ring"],
                "cards": {"sol ring": {"id": "ring-id", "name": "Sol Ring"}},
                "rulings": {"ring-id": [{"comment": "a ruling"}]},
            },
        )
        assert up.card_names() == ["Sol Ring"]
        assert up.named("Sol Ring")["id"] == "ring-id"
        assert up.rulings("ring-id") == [{"comment": "a ruling"}]

    def test_lookup_is_case_insensitive_like_the_real_one(self, tmp_path):
        up = self.fixture(tmp_path, {"cards": {"sol ring": {"id": "ring-id"}}})
        assert up.named("SOL RING")["id"] == "ring-id"

    def test_an_unknown_card_raises_the_same_error_the_real_one_does(self, tmp_path):
        """Same exception type, so the routes cannot behave differently under
        test than they do in production."""
        up = self.fixture(tmp_path, {"cards": {}})
        with pytest.raises(LookupError):
            up.named("Sol Ring")

    def test_missing_sections_are_empty_rather_than_explosive(self, tmp_path):
        up = self.fixture(tmp_path, {})
        assert up.card_names() == []
        assert up.rulings("anything") == []

    def test_an_unreadable_fixture_is_an_outage(self, tmp_path):
        """Which is the honest mapping: the transport cannot answer. A missing
        fixture path is a misconfigured test environment, and it should look
        like an outage rather than like an empty card catalogue."""
        up = FileUpstream(str(tmp_path / "does-not-exist.json"))
        with pytest.raises(UpstreamUnavailable):
            up.card_names()

    def test_malformed_json_is_an_outage(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(UpstreamUnavailable):
            FileUpstream(str(path)).card_names()


class TestSelection:
    def test_nothing_configured_means_the_real_thing(self):
        assert isinstance(build_upstream({}), HttpUpstream)

    def test_a_fixture_path_selects_the_file_transport(self):
        up = build_upstream({"TABLE_SCRYFALL_FIXTURE": "/tmp/cards.json"})
        assert isinstance(up, FileUpstream)
        assert up.path == "/tmp/cards.json"

    def test_an_empty_value_is_not_a_path(self):
        assert isinstance(build_upstream({"TABLE_SCRYFALL_FIXTURE": "   "}), HttpUpstream)
