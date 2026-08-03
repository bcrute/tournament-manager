"""The one outbound dependency, behind a seam.

Card rulings are written by Wizards and published by Scryfall, who make them
available freely and ask three things in return: identify yourself, accept
JSON, and do not hammer them. All three are honoured here.

**The browser never talks to Scryfall.** It cannot: the CSP is
`default-src 'self'` and `frontend/e2e/privacy.spec.ts` asserts that no page in
this app makes a third-party request. So this proxies, and that is not a
workaround — it is the better shape. A player looking up a ruling reveals to
Scryfall only that *this server* asked; their own address, their session and
the fact that they are mid-game stay here. Fetching from the browser would have
handed all three to a third party on every keystroke.

The seam exists for the same reason `mail.py` has one: the tests must not
depend on a network, and the failure paths — timeout, 404, garbage, upstream
down — are the interesting half of the behaviour and have to be reachable
deliberately.

No new dependency. `urllib.request` is in the standard library and these
routes are sync `def`, which FastAPI runs in a threadpool, so blocking here
blocks one worker rather than the event loop.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

API = "https://api.scryfall.com"

#: Scryfall asks for a descriptive User-Agent so they can contact whoever is
#: misbehaving. Anonymising it would be taking their bandwidth while hiding.
USER_AGENT = "Lifetap/1.0 (+https://mtg.skadoosh.dev; tabletop life tracker)"

TIMEOUT = 8


class UpstreamUnavailable(RuntimeError):
    """Scryfall could not be reached, or answered with something unusable.

    Never fatal to a request: every caller degrades to cached data and, failing
    that, to a link the player can follow themselves.
    """


class Upstream:
    """Everything this app asks of Scryfall, which is deliberately little."""

    def card_names(self) -> list[str]:  # pragma: no cover - interface
        raise NotImplementedError

    def named(self, name: str) -> dict:  # pragma: no cover - interface
        raise NotImplementedError

    def rulings(self, card_id: str) -> list[dict]:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class HttpUpstream(Upstream):
    base: str = API

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # A card nobody has heard of is a normal answer, not a failure.
                raise LookupError(f"no such card: {path}") from e
            raise UpstreamUnavailable(f"scryfall returned {e.code}") from e
        except Exception as e:  # noqa: BLE001 — timeouts, DNS, TLS, bad JSON
            raise UpstreamUnavailable(str(e)) from e

    def card_names(self) -> list[str]:
        """Every card name in one response — about 35,000 strings.

        Fetched whole and kept, rather than asking Scryfall to autocomplete
        each keystroke. One request a week instead of one per character typed,
        and the suggestions then come off local storage in microseconds, which
        is the answer to whether the hardware can take it.
        """
        payload = self._get("/catalog/card-names")
        names = payload.get("data")
        if not isinstance(names, list) or not names:
            raise UpstreamUnavailable("card-names catalog was empty or malformed")
        return [n for n in names if isinstance(n, str)]

    def named(self, name: str) -> dict:
        return self._get("/cards/named", {"exact": name})

    def rulings(self, card_id: str) -> list[dict]:
        payload = self._get(f"/cards/{card_id}/rulings")
        data = payload.get("data")
        return data if isinstance(data, list) else []


@dataclass
class FakeUpstream(Upstream):
    """Records what was asked and answers from a script. Used by the tests, and
    by nothing else."""

    names: list[str] = field(default_factory=list)
    cards: dict[str, dict] = field(default_factory=dict)
    card_rulings: dict[str, list[dict]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    fail_with: Exception | None = None

    def card_names(self) -> list[str]:
        self.calls.append("card_names")
        if self.fail_with:
            raise self.fail_with
        return list(self.names)

    def named(self, name: str) -> dict:
        self.calls.append(f"named:{name}")
        if self.fail_with:
            raise self.fail_with
        try:
            return self.cards[name.lower()]
        except KeyError:
            raise LookupError(name) from None

    def rulings(self, card_id: str) -> list[dict]:
        self.calls.append(f"rulings:{card_id}")
        if self.fail_with:
            raise self.fail_with
        return list(self.card_rulings.get(card_id, []))


@dataclass
class FileUpstream(Upstream):
    """Reads a JSON fixture instead of the network.

    Selected by `TABLE_SCRYFALL_FIXTURE`. It exists for the browser suite,
    which runs against a real server with no internet and must still be able to
    type a card name and read a ruling — the alternative was e2e tests that
    skip the feature's entire point, or a live dependency on somebody else's
    uptime for our tests to pass.

    A real transport, like `FileMailer`: the routes take the production path.
    """

    path: str

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as e:  # noqa: BLE001
            raise UpstreamUnavailable(f"fixture unreadable: {e}") from e

    def card_names(self) -> list[str]:
        return list(self._load().get("names") or [])

    def named(self, name: str) -> dict:
        cards = self._load().get("cards") or {}
        try:
            return cards[name.lower()]
        except KeyError:
            raise LookupError(name) from None

    def rulings(self, card_id: str) -> list[dict]:
        return list((self._load().get("rulings") or {}).get(card_id) or [])


_upstream: Upstream | None = None


def build_upstream(env: dict[str, str] | None = None) -> Upstream:
    """Pure, so a test can ask what a given configuration would produce."""
    import os

    env = os.environ if env is None else env
    fixture = (env.get("TABLE_SCRYFALL_FIXTURE") or "").strip()
    return FileUpstream(fixture) if fixture else HttpUpstream()


def get_upstream() -> Upstream:
    global _upstream
    if _upstream is None:
        _upstream = build_upstream()
    return _upstream


def set_upstream(upstream: Upstream | None) -> None:
    global _upstream
    _upstream = upstream
