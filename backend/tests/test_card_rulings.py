"""Finding a ruling, which is a thing four people do mid-argument.

The feature is "make it easy", so the tests are mostly about the ways it could
be *un*easy: a search that does not find the card someone half-remembers, an
autocomplete that waits on somebody else's server, and — most of all — a dead
end when Scryfall is unreachable. A rulings page that sometimes shows nothing
is worse than a link, because the player has already spent the taps.

Nothing here touches the network. `FakeUpstream` is a real implementation of
the same seam `HttpUpstream` implements, so the routes take the production path
up to the last inch, and the failure branches are reachable on purpose rather
than by unplugging something.
"""

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import cards as cards_mod
from app.cards import _fold, refresh_names, router as cards_router, suggest
from app.db import q
from app.scryfall import FakeUpstream, UpstreamUnavailable, set_upstream

BOLT = {
    "id": "bolt-id",
    "name": "Lightning Bolt",
    "type_line": "Instant",
    "mana_cost": "{R}",
    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
    "set_name": "Limited Edition Alpha",
    "scryfall_uri": "https://scryfall.com/card/lea/161/lightning-bolt",
}
BOLT_RULINGS = [
    {
        "published_at": "2021-03-19",
        "comment": "Any target means any creature, player, or planeswalker.",
        "source": "wotc",
    }
]

CATALOGUE = [
    "Lightning Bolt",
    "Lightning Helix",
    "Jace, the Mind Sculptor",
    "Sword of Feast and Famine",
    "Gaea's Cradle",
    "Lim-Dûl the Necromancer",
    "Aetherflux Reservoir",
    "_Weird Name 50%",
]


def fresh_upstream(**kwargs) -> FakeUpstream:
    up = FakeUpstream(
        names=list(CATALOGUE),
        cards={"lightning bolt": BOLT},
        card_rulings={"bolt-id": list(BOLT_RULINGS)},
        **kwargs,
    )
    set_upstream(up)
    return up


def wipe_cache():
    q("DELETE FROM card_names")
    q("DELETE FROM card_rulings")
    q("DELETE FROM card_index")
    cards_mod._last_failure = 0.0


@pytest.fixture
def upstream():
    wipe_cache()
    up = fresh_upstream()
    yield up
    set_upstream(None)
    wipe_cache()


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(cards_router, prefix="/api/cards")
    with TestClient(app) as c:
        yield c


class TestFolding:
    """What someone types is never what is printed on the card."""

    def test_case_and_punctuation_go(self):
        assert _fold("Jace, the Mind Sculptor") == "jace the mind sculptor"
        assert _fold("Gaea's Cradle") == "gaeas cradle"

    def test_accents_go(self):
        assert _fold("Lim-Dûl the Necromancer") == "limdul the necromancer"
        assert _fold("Æther Vial") == "aether vial"

    def test_spaces_are_kept_because_words_are_the_unit(self):
        assert " " in _fold("Sword of Feast and Famine")

    def test_it_is_stable_on_what_it_already_produced(self):
        once = _fold("Lim-Dûl the Necromancer")
        assert _fold(once) == once


class TestSuggesting:
    def test_a_prefix_finds_the_obvious_cards(self, upstream):
        refresh_names(force=True)
        assert suggest("lightn") == ["Lightning Bolt", "Lightning Helix"]

    def test_a_word_from_the_middle_finds_it(self, upstream):
        """Nobody hunting Feast and Famine types "Sword of" first."""
        refresh_names(force=True)
        assert suggest("feast") == ["Sword of Feast and Famine"]

    def test_words_in_the_wrong_order_still_find_it(self, upstream):
        """Which is how people actually remember card names."""
        refresh_names(force=True)
        assert suggest("famine sword") == ["Sword of Feast and Famine"]
        assert suggest("sculptor jace") == ["Jace, the Mind Sculptor"]

    def test_punctuation_the_player_cannot_type_is_not_required(self, upstream):
        refresh_names(force=True)
        assert suggest("gaeas cradle") == ["Gaea's Cradle"]
        # the hyphen folds away, so the typed space has to survive as a word
        # boundary or this finds nothing at all
        assert suggest("lim dul") == ["Lim-Dûl the Necromancer"]

    def test_prefix_matches_sort_above_mere_containment(self, upstream):
        refresh_names(force=True)
        q("INSERT INTO card_names (name, fold) VALUES (?, ?)",
          ("Notorious Lightning Thief", "notorious lightning thief"))
        assert suggest("lightning")[0].startswith("Lightning")

    def test_nothing_typed_suggests_nothing(self, upstream):
        refresh_names(force=True)
        assert suggest("") == []
        assert suggest("   ") == []
        assert suggest("!!!") == []

    def test_like_wildcards_in_the_query_are_escaped(self, upstream):
        """`%` un-escaped would match every card in the game, which is both
        wrong and the slowest possible query."""
        refresh_names(force=True)
        assert suggest("%") == []
        assert suggest("100% of it") == []

    def test_like_metacharacters_never_reach_the_query_at_all(self, upstream):
        """Two layers, and the first one is why the second rarely matters.

        Folding keeps only `[a-z0-9 ]`, so `%` and `_` are gone before any SQL
        is built — `_ightning` searches for "ightning" and finds the Lightning
        cards, which is the friendly answer rather than an error. `_escape_like`
        is the belt to that pair of braces, for anything that ever reaches it.
        """
        refresh_names(force=True)
        assert _fold("_ightning") == "ightning"
        assert suggest("_ightning") == ["Lightning Bolt", "Lightning Helix"]

        from app.cards import _escape_like

        assert _escape_like("50%") == "50\\%"
        assert _escape_like("a_b") == "a\\_b"

    def test_a_name_containing_a_wildcard_is_still_findable(self, upstream):
        """`_Weird Name 50%` is in the catalogue precisely so a stored name
        with LIKE metacharacters in it gets exercised."""
        refresh_names(force=True)
        assert suggest("weird name") == ["_Weird Name 50%"]

    def test_the_list_is_capped(self, upstream):
        refresh_names(force=True)
        q("DELETE FROM card_names")
        from app.db import qmany

        qmany(
            "INSERT INTO card_names (name, fold) VALUES (?, ?)",
            ((f"Test Card {i}", f"test card {i}") for i in range(50)),
        )
        assert len(suggest("test")) == cards_mod.SUGGESTION_LIMIT


class TestTheIndex:
    def test_it_is_fetched_once_and_then_reused(self, upstream):
        """The point of holding the catalogue: a keystroke costs a local query
        and no request to anybody."""
        refresh_names(force=True)
        upstream.calls.clear()
        for _ in range(20):
            suggest("light")
        refresh_names()
        assert upstream.calls == [], "typing must not reach upstream"

    def test_a_stale_index_is_refetched(self, upstream):
        refresh_names(force=True)
        q("UPDATE card_index SET fetched_at = ?",
          (int(time.time()) - cards_mod.NAMES_TTL - 1,))
        upstream.calls.clear()
        refresh_names()
        assert upstream.calls == ["card_names"]

    def test_a_rebuild_replaces_rather_than_accumulates(self, upstream):
        refresh_names(force=True)
        before = q("SELECT COUNT(*) AS n FROM card_names").fetchone()["n"]
        refresh_names(force=True)
        assert q("SELECT COUNT(*) AS n FROM card_names").fetchone()["n"] == before

    def test_a_card_that_left_the_catalogue_leaves_the_index(self, upstream):
        refresh_names(force=True)
        upstream.names = [n for n in CATALOGUE if n != "Lightning Helix"]
        refresh_names(force=True)
        assert suggest("lightning") == ["Lightning Bolt"]

    def test_an_upstream_failure_leaves_the_old_index_working(self, upstream):
        """An outage must not empty the search box."""
        refresh_names(force=True)
        upstream.fail_with = UpstreamUnavailable("down")
        assert refresh_names(force=True) > 0
        assert suggest("lightn") == ["Lightning Bolt", "Lightning Helix"]

    def test_an_empty_catalogue_is_refused_rather_than_stored(self, upstream):
        """A successful response that happens to be empty would wipe the index
        and break search with no error anywhere."""
        refresh_names(force=True)
        from app.scryfall import HttpUpstream

        empty = HttpUpstream()
        empty._get = lambda *a, **k: {"data": []}  # type: ignore[method-assign]
        set_upstream(empty)
        assert refresh_names(force=True) > 0

    def test_failure_backs_off_instead_of_retrying_every_keystroke(self, upstream):
        """Eight-second timeouts, one per character typed, is the difference
        between a degraded feature and an unusable page."""
        wipe_cache()
        upstream.fail_with = UpstreamUnavailable("down")
        refresh_names()
        upstream.calls.clear()
        for _ in range(5):
            refresh_names()
        assert upstream.calls == []


class TestRulings:
    def test_it_returns_the_card_and_its_rulings(self, upstream, client):
        r = client.get("/api/cards/rulings", params={"name": "Lightning Bolt"})
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Lightning Bolt"
        assert body["typeLine"] == "Instant"
        assert body["rulings"][0]["text"].startswith("Any target")
        assert body["rulings"][0]["source"] == "wotc"

    def test_the_scryfall_link_is_always_there(self, upstream, client):
        """The feature is 'make it easy to find rulings'. Everything else on
        the page is a convenience over this link."""
        body = client.get("/api/cards/rulings", params={"name": "Lightning Bolt"}).json()
        assert body["scryfallUrl"].startswith("https://scryfall.com/")

    def test_a_second_lookup_is_free(self, upstream, client):
        client.get("/api/cards/rulings", params={"name": "Lightning Bolt"})
        upstream.calls.clear()
        client.get("/api/cards/rulings", params={"name": "Lightning Bolt"})
        assert upstream.calls == []

    def test_an_unknown_card_is_a_404_not_an_error(self, upstream, client):
        r = client.get("/api/cards/rulings", params={"name": "Not A Real Card"})
        assert r.status_code == 404

    def test_a_card_with_no_rulings_is_a_normal_answer(self, upstream, client):
        upstream.cards["vanilla bear"] = {
            "id": "bear-id",
            "name": "Vanilla Bear",
            "scryfall_uri": "https://scryfall.com/card/x/1/vanilla-bear",
        }
        body = client.get("/api/cards/rulings", params={"name": "Vanilla Bear"}).json()
        assert body["rulings"] == []
        assert body["scryfallUrl"], "still somewhere to go and check"

    def test_a_ruling_with_no_text_is_dropped(self, upstream, client):
        upstream.card_rulings["bolt-id"] = [{"published_at": "2021-01-01", "comment": ""}]
        body = client.get("/api/cards/rulings", params={"name": "Lightning Bolt"}).json()
        assert body["rulings"] == []


class TestWhenScryfallIsDown:
    def test_a_cached_card_is_still_served(self, upstream, client):
        """Stale rulings beat none: a ruling from last month is still the
        ruling."""
        client.get("/api/cards/rulings", params={"name": "Lightning Bolt"})
        upstream.fail_with = UpstreamUnavailable("down")
        q("UPDATE card_rulings SET fetched_at = ? WHERE name = 'Lightning Bolt'",
          (int(time.time()) - cards_mod.RULINGS_TTL - 1,))

        r = client.get("/api/cards/rulings", params={"name": "Lightning Bolt"})
        assert r.status_code == 200
        assert r.json()["rulings"][0]["text"].startswith("Any target")

    def test_an_uncached_card_says_so_and_does_not_pretend(self, upstream, client):
        upstream.fail_with = UpstreamUnavailable("down")
        r = client.get("/api/cards/rulings", params={"name": "Lightning Bolt"})
        assert r.status_code == 503
        assert "link" in r.json()["detail"], "the page still has somewhere to send them"

    def test_search_keeps_working_from_the_cached_index(self, upstream, client):
        refresh_names(force=True)
        upstream.fail_with = UpstreamUnavailable("down")
        body = client.get("/api/cards/suggest", params={"q": "lightn"}).json()
        assert body["ready"] is True
        assert body["suggestions"] == ["Lightning Bolt", "Lightning Helix"]


class TestTheEndpoints:
    def test_suggest_needs_no_account_and_no_room(self, upstream, client):
        """It is a play aid. Requiring anything to use it would defeat it."""
        r = client.get("/api/cards/suggest", params={"q": "light"})
        assert r.status_code == 200
        assert r.json()["suggestions"]

    def test_suggest_reports_an_index_that_is_not_built_yet(self, upstream, client):
        """"Still loading the card list" and "no such card" are different
        problems, and only one of them is the player's fault."""
        wipe_cache()
        upstream.fail_with = UpstreamUnavailable("down")
        body = client.get("/api/cards/suggest", params={"q": "light"}).json()
        assert body["ready"] is False
        assert body["suggestions"] == []

    def test_an_absurd_query_is_refused_by_the_schema(self, upstream, client):
        assert client.get("/api/cards/suggest", params={"q": "x" * 500}).status_code == 422

    def test_rulings_requires_a_name(self, upstream, client):
        assert client.get("/api/cards/rulings").status_code == 422


class TestTheBrowserNeverTalksToScryfall:
    """The privacy posture this app claims, applied to the one feature that
    has an outbound dependency.

    `frontend/e2e/privacy.spec.ts` asserts no page makes a third-party request
    and the CSP is `default-src 'self'`, so fetching from the browser was never
    an option. Worth stating as a test rather than a comment: the payload the
    client receives must contain everything it needs, so nobody is tempted to
    'just fetch the image from Scryfall' later.
    """

    def test_only_one_module_reaches_the_network(self):
        import pathlib

        app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
        reaching = [
            p.name
            for p in app_dir.glob("*.py")
            if "urllib.request" in p.read_text() or "http.client" in p.read_text()
        ]
        assert reaching == ["scryfall.py"], reaching

    def test_the_payload_carries_no_scryfall_asset_urls(self, upstream, client):
        """A link the player chooses to follow is fine. An image the page loads
        without asking is a third-party request, and would fail the CSP."""
        upstream.cards["lightning bolt"] = {
            **BOLT,
            "image_uris": {"normal": "https://cards.scryfall.io/normal/bolt.jpg"},
        }
        body = client.get("/api/cards/rulings", params={"name": "Lightning Bolt"}).json()
        assert "cards.scryfall.io" not in json.dumps(body)
