"""Import adapters.

An adapter reads one external source's export and returns this app's shape:
entrants tagged with an `external_ref`, rounds numbered with an integer, pods
with seats, and a typed result per pod. Nothing here touches the database and
nothing here knows what a tournament code is — translation only, so the core
that writes the rows (`apply_import` in tournaments.py) is written once and
never grows a branch per source. If adding a second source would mean editing
that core, the boundary here is in the wrong place.

**Imports are one-way, and that is structural.** The interface has exactly one
method, `read`, and deliberately no `write`, `push` or `sync` counterpart:
TopDeck's API cannot accept results, so pairings can flow in and our results
stay local. An organizer told nothing would assume a sync that does not exist,
so `GET /api/tournament/import/sources` says it in words and every import
response repeats it.

The mappings themselves are §9 of the API contract, which exists precisely so
this file is a field rename rather than a translation layer:

    winner_id            -> places[] (typed, ordered, multi-place)
    winner_id: "Draw"    -> kind "draw"        (no magic string in an id)
    table: "Byes"        -> kind "bye"         (one pod of one, per player)
    round: "Top 8"       -> number 6 + kind "elimination"   (no union type)
    winner (a name)      -> discarded          (names are not identity)
"""

import re
from dataclasses import dataclass

class ImportProblem(Exception):
    """A payload this adapter will not guess at.

    Raised instead of dropping or inventing a row: an import that silently
    skipped half a round would be discovered by an organizer reading standings
    that are quietly wrong, which is the worst moment to find out.
    """


@dataclass(frozen=True)
class ImportedSeat:
    #: the entrant's `external_ref` ("source:id"), never their display name
    ref: str
    #: 1 = won the pod. None when the source recorded no result for the table.
    place: int | None = None


@dataclass(frozen=True)
class ImportedPod:
    seats: tuple[ImportedSeat, ...]
    #: placement | draw | bye | unfinished, or None when the source has no
    #: decision yet. The core owns that vocabulary and checks an adapter's
    #: reading against it (`RESULT_KINDS`), which is what keeps a source's own
    #: word for something out of the database. An imported table with no winner
    #: stays awaiting a ruling rather than being recorded as something nobody
    #: ruled.
    kind: str | None = None
    #: the source's table number, when it published one people could read out
    number: int | None = None
    #: the source's name for the table, when it is not just a number
    label: str | None = None


@dataclass(frozen=True)
class ImportedRound:
    #: always an integer. A source that labels a round "Top 8" gets its position
    #: in the event, because a round number that is sometimes a string forces
    #: every client to parse it.
    number: int
    kind: str = "swiss"
    pods: tuple[ImportedPod, ...] = ()
    #: how many players the cut was to, when the label said ("Top 8" -> 8).
    #: Advisory: it is the source's word for the size, not a seeding.
    cut_to: int | None = None


@dataclass(frozen=True)
class ImportedEntrant:
    ref: str
    name: str


@dataclass(frozen=True)
class ImportedEvent:
    source: str
    name: str | None = None
    entrants: tuple[ImportedEntrant, ...] = ()
    rounds: tuple[ImportedRound, ...] = ()


class ImportAdapter:
    """One external source, read-only.

    Subclass, set `key` and `name`, implement `read`. There is intentionally no
    counterpart that sends anything back: the direction is a property of the
    interface, not a policy an adapter could opt out of.
    """

    key: str = ""
    name: str = ""
    #: where an organizer gets the file this adapter reads, so the UI can say so
    docs: str = ""

    def read(self, payload: dict) -> ImportedEvent:
        raise NotImplementedError


# "Top 8", "Top 4" — the size is in the label. The named rounds below have no
# number in them at all, so they carry the field size they imply; "Finals" is
# two players whatever the game calls them.
_TOP_N = re.compile(r"^top\s*(\d+)$", re.I)
_NAMED_CUT_ROUNDS = {
    "finals": 2,
    "final": 2,
    "semifinals": 4,
    "semis": 4,
    "quarterfinals": 8,
    "quarters": 8,
}

#: their id field's value when a table was drawn. §9: a magic string in an id
#: field forces every client to special-case it, so it dies at this boundary.
_DRAW = "draw"
#: their table field's value for the row listing everyone who got a bye
_BYES = ("byes", "bye")


def round_from_label(label, previous: int) -> tuple[int, str, int | None]:
    """`(number, kind, cut_to)` for one of their round labels.

    A plain number is the round number. A named cut takes the next number in the
    event — the integer half of the mapping — and says so in `kind`, which is
    the cut flag the rest of the app already runs on (`trounds.kind`,
    single-elimination pairing, no-draw adjudication). Nothing else is guessed:
    an unrecognised label raises, because a mislabelled bracket round imported
    as Swiss is invisible afterwards and pairs the next round from standings.
    """
    text = "" if label is None else str(label).strip()
    if isinstance(label, bool):        # bool is an int; a round is not a flag
        raise ImportProblem(f"round label {label!r} is not a round")
    if not text:
        raise ImportProblem("a round with no label — a round is a number, or a named cut")
    if isinstance(label, int) or re.fullmatch(r"\d+", text):
        return int(text), "swiss", None
    top = _TOP_N.match(text)
    if top:
        return previous + 1, "elimination", int(top.group(1))
    named = _NAMED_CUT_ROUNDS.get(text.lower())
    if named:
        return previous + 1, "elimination", named
    raise ImportProblem(
        f"unrecognised round label {text!r} — a round is a number, "
        "or a named cut like 'Top 8'"
    )


class TopDeckAdapter(ImportAdapter):
    """TopDeck Tournaments V2.

    Their export is close to ours by design (§9), so this is mostly renaming.
    The four places it is not are the four places their model cannot say what
    ours does: one winner per table instead of an ordering, a draw written into
    the winner's id, byes collected into a pseudo-table, and a round number that
    is sometimes a phrase.
    """

    key = "topdeck"
    name = "TopDeck Tournaments V2"
    docs = "https://topdeck.gg/docs/tournaments-v2"

    def read(self, payload: dict) -> ImportedEvent:
        if not isinstance(payload, dict):
            raise ImportProblem("expected the tournament object from their API")

        # Their roster lives under `standings` (or `players` on older exports),
        # but a player only ever seated at a table has to become an entrant too
        # — otherwise a round would reference somebody the event has never
        # heard of. Collected in first-seen order so a re-import is stable.
        entrants: dict[str, str] = {}

        def remember(person) -> str:
            ref = self._ref(person)
            name = str((person or {}).get("name") or "").strip()
            # An upstream rename follows the ref, and the last spelling wins;
            # the entrant upsert applies the same rule for the same reason.
            if name:
                entrants[ref] = name
            else:
                entrants.setdefault(ref, ref)
            return ref

        for person in payload.get("standings") or payload.get("players") or []:
            remember(person)

        rounds, previous = [], 0
        for raw in payload.get("rounds") or []:
            if not isinstance(raw, dict):
                raise ImportProblem("each round must be an object")
            number, kind, cut_to = round_from_label(raw.get("round"), previous)
            previous = max(previous, number)
            pods = []
            for table in raw.get("tables") or []:
                if not isinstance(table, dict):
                    raise ImportProblem(f"round {number}: each table must be an object")
                pods.extend(self._pods_from_table(table, remember, number))
            rounds.append(
                ImportedRound(number=number, kind=kind, pods=tuple(pods), cut_to=cut_to)
            )

        return ImportedEvent(
            source=self.key,
            name=(payload.get("tournamentName") or payload.get("name") or None),
            entrants=tuple(ImportedEntrant(ref=r, name=n) for r, n in entrants.items()),
            rounds=tuple(rounds),
        )

    def _ref(self, person) -> str:
        """`"topdeck:<their id>"`. An id is required, on purpose.

        Their payload carries a display name beside every id, and matching on
        it would make names identity — the one flaw in their shape §9 names
        outright. A player with no id cannot be re-imported without duplicating
        them, so the import stops instead of creating a person it cannot find
        again.
        """
        if not isinstance(person, dict):
            raise ImportProblem("expected a player object")
        pid = str(person.get("id") or person.get("playerId") or "").strip()
        if not pid:
            who = str(person.get("name") or "").strip() or "a player"
            raise ImportProblem(
                f"{who} has no id — an import needs a stable id per person, never a name"
            )
        return f"{self.key}:{pid}"

    def _pods_from_table(self, table: dict, remember, round_number: int) -> list[ImportedPod]:
        label = table.get("table")
        text = str(label).strip() if label is not None else ""

        # "Byes" is not a table: it is a list of people who sat out, folded into
        # one row because their model has nowhere else to put them. Ours does —
        # a bye is a pod of one, scored by `byeScoring` — so the row expands
        # into one pod per player rather than seating them together.
        if text.lower() in _BYES:
            return [
                ImportedPod(
                    seats=(ImportedSeat(ref=remember(p), place=1),),
                    kind="bye",
                    label=None,
                )
                for p in table.get("players") or []
            ]

        seats_in = table.get("players") or []
        refs = [remember(p) for p in seats_in]
        if not refs:
            raise ImportProblem(f"round {round_number}: table {text or '?'} seats nobody")

        winner = table.get("winner_id")
        winner_text = str(winner).strip() if winner is not None else ""
        number = int(text) if re.fullmatch(r"\d+", text) else None
        # their table name when it is a name; a number is not a label
        name = text if (text and number is None) else None

        if not winner_text:
            # No decision at the source. `winner` (the display name) is
            # deliberately not consulted as a fallback: §9 says discard it, and
            # a table ruled from a name is a table ruled from something that
            # changes. The pod is imported awaiting a result.
            return [ImportedPod(seats=tuple(ImportedSeat(ref=r) for r in refs),
                                kind=None, number=number, label=name)]

        if winner_text.lower() == _DRAW:
            # every seat shares first, which is what a draw is in our scoring
            return [ImportedPod(
                seats=tuple(ImportedSeat(ref=r, place=1) for r in refs),
                kind="draw", number=number, label=name)]

        won = f"{self.key}:{winner_text}"
        if won not in refs:
            raise ImportProblem(
                f"round {round_number}: table {text or '?'} names a winner "
                "who is not seated at it"
            )
        # Their model records one winner and cannot express the rest of the
        # order, so everybody else is jointly second. Spreading them 2..N would
        # invent an ordering the source never recorded, and it would score
        # differently under placement points.
        return [ImportedPod(
            seats=tuple(ImportedSeat(ref=r, place=1 if r == won else 2) for r in refs),
            kind="placement", number=number, label=name)]


_ADAPTERS: dict[str, ImportAdapter] = {a.key: a for a in (TopDeckAdapter(),)}


def adapter_for(key: str | None) -> ImportAdapter | None:
    """The adapter for a source key, or None. Never falls back to a default —
    importing an event through the wrong reader is worse than not importing."""
    return _ADAPTERS.get(key or "")


def known_sources() -> list[dict]:
    """What this server can import from. One entry today; the shape is the point.

    `oneWay` is on every row rather than stated once, so a client that renders
    this list cannot show an import without the sentence that goes with it.
    """
    return [
        {
            "key": a.key,
            "name": a.name,
            "docs": a.docs,
            "oneWay": True,
            "acceptsResults": False,
        }
        for a in _ADAPTERS.values()
    ]
