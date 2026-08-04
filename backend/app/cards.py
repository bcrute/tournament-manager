"""Card ruling lookup.

Rulings are the thing four people argue about at a table with a phone already
in their hand, so the whole design goal is *fewest taps to the answer*: type
three letters, see the card, read the rulings. Nothing here needs an account,
a room, or a tournament.

Three decisions worth keeping:

**Autocomplete is local.** The full list of card names — about 35,000 strings —
is fetched from Scryfall once and kept in SQLite, so a keystroke costs one
indexed query against short text and no network at all. Proxying each keystroke
upstream would have been simpler to write, a request per character in flight,
and dependent on somebody else's uptime for the app to feel responsive.

**Rulings are cached.** They change when a card is printed and then almost
never, so a card looked up once is free for everyone afterwards. The cache is
also what makes an upstream outage a degradation rather than a failure.

**Nothing is ever a dead end.** Upstream down, card not in the cache, rulings
empty because the card genuinely has none — every one of those still ends with
a working Scryfall link the player can follow. The feature is "make it easy to
find rulings", and a link that works beats an inline panel that sometimes
doesn't.

**This module must not be reused in the commercial project.** It is the newest
and most self-contained code here, which makes it the most tempting to lift,
and it is precisely what `docs/commercial-position.md` §3 forbids: a commercial
product may not ship Magic card content, and Scryfall's data comes under the
Wizards Fan Content Policy, which is noncommercial. That rule lives three
documents away, so it is repeated here where somebody about to copy the file
will read it. The account, mail, audit and rate-limiting modules are the ones
that port cleanly.

MTG only, and apart from `games.py`'s profile registry deliberately. This app
is card games and nothing else, so a second game here is a realistic prospect —
but rulings are not a solved shape across card games. Magic has an official
corpus, freely published, behind a good API; Lorcana, the other game in the
registry, has no equivalent. One worked example and one absence is not enough
to design against, so the trigger for generalising is a second card game with a
real rulings source, not a second card game.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .db import q, qmany
from .scryfall import UpstreamUnavailable, get_upstream

router = APIRouter()

#: How long the name index is good for. Card names change only when a set is
#: released, so a week is frequent enough to catch a new set within days and
#: rare enough to be invisible.
NAMES_TTL = 7 * 86400
#: Rulings change when errata land, which is seldom. Thirty days.
RULINGS_TTL = 30 * 86400
#: After an upstream failure, stop trying for a while and serve what is cached.
#: Without this, an outage turns every search into an eight-second timeout.
BACKOFF = 300

SUGGESTION_LIMIT = 10

_last_failure = 0.0


def _fold(text: str) -> str:
    """The form matching runs against.

    Case, punctuation and accents all get in the way of finding a card whose
    name someone half-remembers: nobody types the comma in "Jace, the Mind
    Sculptor", the apostrophe in "Gaea's Cradle", or the accent in "Lim-Dûl".
    """
    lowered = text.lower()
    lowered = (
        lowered.replace("â", "a").replace("á", "a").replace("à", "a")
        .replace("é", "e").replace("è", "e").replace("ê", "e")
        .replace("í", "i").replace("î", "i")
        .replace("ó", "o").replace("ö", "o").replace("ô", "o")
        .replace("ú", "u").replace("û", "u").replace("ü", "u")
        .replace("ñ", "n").replace("æ", "ae")
    )
    return re.sub(r"[^a-z0-9 ]+", "", lowered).strip()


# ---------------------------------------------------------------- name index


def _index_age() -> float | None:
    """When the name index was last rebuilt, or None if it never has been.

    Its own table rather than a sentinel row in `card_rulings`: a fake card
    called something no card is called would work right up until somebody
    wondered why the cache had a row that was not a card.
    """
    row = q("SELECT fetched_at FROM card_index WHERE id = 1").fetchone()
    return row["fetched_at"] if row else None


def _note_index_refreshed() -> None:
    q(
        "INSERT INTO card_index (id, fetched_at) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET fetched_at = excluded.fetched_at",
        (int(time.time()),),
    )


def refresh_names(force: bool = False) -> int:
    """Pull the card-name catalogue if it is stale. Returns how many names are
    indexed afterwards — including when nothing was fetched, because the
    caller's question is "can I autocomplete", not "did you make a request"."""
    global _last_failure

    have = q("SELECT COUNT(*) AS n FROM card_names").fetchone()["n"]
    age = _index_age()
    fresh = age is not None and (time.time() - age) < NAMES_TTL
    if have and fresh and not force:
        return have
    if not force and (time.time() - _last_failure) < BACKOFF:
        return have

    try:
        names = get_upstream().card_names()
    except Exception:  # noqa: BLE001 — an index that cannot refresh is not an outage
        _last_failure = time.time()
        return have

    # Replace wholesale inside one transaction: a half-written index would
    # silently drop cards from search with no symptom other than "it isn't
    # finding it", which is indistinguishable from a typo to the person typing.
    q("DELETE FROM card_names")
    qmany(
        "INSERT OR IGNORE INTO card_names (name, fold) VALUES (?, ?)",
        ((name, _fold(name)) for name in names),
    )
    _note_index_refreshed()
    _last_failure = 0.0
    return q("SELECT COUNT(*) AS n FROM card_names").fetchone()["n"]


def suggest(text: str, limit: int = SUGGESTION_LIMIT) -> list[str]:
    """Names to offer for what has been typed so far.

    Every word typed has to appear somewhere in the name, in any order. That
    one rule covers the three ways people actually search:

      "light"          prefix — the ordinary case
      "feast"          a distinctive word from the middle: nobody types
                       "Sword of…" first when hunting Feast and Famine
      "famine sword"   remembered out of order, which is most of the time

    It also fixes a subtler miss. Punctuation is folded away but spaces are
    kept, so "Lim-Dûl" is stored as "limdul" — and someone typing "lim dul"
    would match nothing at all under a whole-string comparison. As separate
    words, "lim" and "dul" are both substrings of it, and it matches.

    Prefix matches still sort first, because when someone has typed "lightn"
    they mean the obvious card and not a fifteen-letter one that happens to
    contain it.
    """
    folded = _fold(text)
    words = [w for w in folded.split(" ") if w]
    if not words:
        return []

    # One LIKE per word, ANDed. At ten words this is ten substring scans over
    # 35,000 short strings, which is still under a millisecond — and nobody
    # types ten words into an autocomplete box.
    where = " AND ".join(["fold LIKE ? ESCAPE '\\'"] * len(words))
    params: list = [_like_contains(w) for w in words]
    params.insert(0, _like_prefix(folded))  # for the ordering column
    params.append(limit)

    rows = q(
        f"SELECT name, (fold LIKE ? ESCAPE '\\') AS starts FROM card_names "
        f"WHERE {where} "
        "ORDER BY starts DESC, LENGTH(name), name LIMIT ?",
        tuple(params),
    ).fetchall()
    return [r["name"] for r in rows]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_prefix(folded: str) -> str:
    return _escape_like(folded) + "%"


def _like_contains(folded: str) -> str:
    return "%" + _escape_like(folded) + "%"


# ------------------------------------------------------------------- rulings


def _clean_link(uri: str | None, fallback_name: str) -> str:
    """The Scryfall page, without their analytics parameter.

    Their API appends `?utm_source=api` to every `scryfall_uri`. Passing that
    through would mean this app handing a third party a tracking parameter on
    a link a player clicked — in an app whose Referrer-Policy is `no-referrer`
    specifically so that does not happen. Their page, their analytics, their
    call once the player is there; ours is not to tag them on the way out.
    """
    if not uri:
        return f"https://scryfall.com/search?q={urllib.parse.quote(fallback_name)}"
    split = urllib.parse.urlsplit(uri)
    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(split.query)
        if not k.lower().startswith("utm_")
    ]
    return urllib.parse.urlunsplit(
        (split.scheme, split.netloc, split.path, urllib.parse.urlencode(kept), split.fragment)
    )


def _card_payload(name: str) -> dict:
    """The card and its rulings, from cache when possible."""
    row = q("SELECT payload, fetched_at FROM card_rulings WHERE name = ?", (name,)).fetchone()
    if row and (time.time() - row["fetched_at"]) < RULINGS_TTL:
        return json.loads(row["payload"])

    global _last_failure
    if (time.time() - _last_failure) < BACKOFF and row:
        # Upstream is unwell and we have something. Stale rulings beat none —
        # a ruling from last month is still the ruling.
        return json.loads(row["payload"])

    upstream = get_upstream()
    try:
        card = upstream.named(name)
        rulings = upstream.rulings(card.get("id") or "")
    except LookupError:
        raise HTTPException(404, "no card by that name")
    except UpstreamUnavailable:
        _last_failure = time.time()
        if row:
            return json.loads(row["payload"])
        raise HTTPException(
            503, "card rulings are unavailable right now — the link below still works"
        )

    payload = {
        "name": card.get("name") or name,
        "typeLine": card.get("type_line"),
        "manaCost": card.get("mana_cost"),
        "oracleText": card.get("oracle_text"),
        "setName": card.get("set_name"),
        # Where to go for anything this page does not show. Always present,
        # even when the rulings list is empty, because "no rulings" is a real
        # answer that people want to double-check.
        "scryfallUrl": _clean_link(card.get("scryfall_uri"), name),
        "rulings": [
            {
                "at": r.get("published_at"),
                "text": r.get("comment"),
                # Scryfall carries rulings from Wizards and from itself; which
                # one is speaking matters when a table is arguing about it.
                "source": r.get("source"),
            }
            for r in rulings
            if r.get("comment")
        ],
    }
    q(
        "INSERT INTO card_rulings (name, payload, fetched_at) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET payload = excluded.payload, "
        "fetched_at = excluded.fetched_at",
        (payload["name"], json.dumps(payload), int(time.time())),
    )
    _last_failure = 0.0
    return payload


# -------------------------------------------------------------------- routes


class Suggestions(BaseModel):
    suggestions: list[str]
    #: False when the index has never been built — the UI says "still loading
    #: the card list" rather than "no such card", which are different problems
    #: and only one of them is the player's.
    ready: bool


@router.get("/suggest", response_model=Suggestions)
def suggest_cards(q_: str = Query("", alias="q", max_length=100)):
    ready = refresh_names() > 0
    return Suggestions(suggestions=suggest(q_) if ready else [], ready=ready)


@router.get("/rulings")
def card_rulings(name: str = Query(..., min_length=1, max_length=200)):
    """Rulings for one card, by exact name.

    Exact rather than fuzzy on purpose: the client picked this name off the
    suggestion list, so a fuzzy match here could only ever turn a correct
    choice into a different card.
    """
    return _card_payload(name.strip())
