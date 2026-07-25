"""Tournament management.

An organizer (an account, with a recovery email on file) hosts a tournament.
Entrants need no account at all — they scan a code and claim a name, so a player
still hands over nothing but a display name.

Each pod is backed by an ordinary room, so the whole table app — life, commander
damage, seating, Treachery, the display — works unchanged inside a tournament.
Results come from the room automatically when a game ends, and the organizer can
override.

Resource notes: pairing is pure and in-memory, every read is a single snapshot
query set (no N+1), pods reuse the room machinery rather than duplicating it, and
the only background work is a lazy sweep on read.
"""

import csv
import io
import json
import re
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .accounts import require_account
from .audit import AUTHZ_DENY, security_event
from .db import q
from .games import canonical_policy, known_games, profile_for, structure_for
from .pairing import Entrant as PairEntrant
from .pairing import bracket_pods, pair_round, seat_pods

router = APIRouter()

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
IDLE_TIMEOUT = 12 * 60 * 60  # a tournament day, not a room's 3h

#: A tournament nobody has ended and nobody has touched inside IDLE_TIMEOUT.
#: Written once and asked from two places — the tournament sweep below and the
#: room sweep in table.py — because the pod-room exemption and tournament
#: expiry have to agree. If they can disagree, expiring an event strands its
#: pod rooms open forever: exempt from the 3h room sweep by a tournament that
#: is no longer live. Takes IDLE_TIMEOUT as its one parameter.
LIVE_TOURNAMENT = (
    "t.status NOT IN ('ended', 'expired') "
    "AND COALESCE(t.last_active, t.created_at) >= unixepoch() - ?"
)

#: Rooms that a live tournament is holding open, for the room sweep to skip.
LIVE_TOURNAMENT_ROOMS = (
    "SELECT p.room_code FROM pods p "
    "JOIN trounds r ON r.id = p.round_id "
    "JOIN tournaments t ON t.code = r.tournament_code "
    "WHERE p.room_code IS NOT NULL AND " + LIVE_TOURNAMENT
)


def expire_idle_tournaments():
    """Retire tournaments nobody has touched in IDLE_TIMEOUT.

    The room sweep's shape, one tier up: a bulk UPDATE, run lazily off the hot
    path rather than on a scheduler. 'expired' is deliberately not 'ended' —
    ending is an organizer's decision that freezes final standings, expiring is
    the server admitting an event was abandoned. Standings and history stay
    readable either way; what stops is the event, and the exemption its pod
    rooms were enjoying.
    """
    q(
        "UPDATE tournaments SET status = 'expired' "
        "WHERE status NOT IN ('ended', 'expired') "
        "AND COALESCE(last_active, created_at) < unixepoch() - ?",
        (IDLE_TIMEOUT,),
    )

# Game-independent defaults. Anything that varies by game comes from the game
# profile instead — see games.py. Keep this list free of MTG assumptions.
GENERIC_SETTINGS = {
    "scoring": "win_draw_loss",      # win_draw_loss | placement
    "winPoints": 3,
    "drawPoints": 1,
    "lossPoints": 0,
    "placementPoints": [4, 3, 2, 1],
    "byeScoring": "win",
    "seatAssignment": "random",       # random | by_standings | manual
    "allowOfficialCalls": True,
    # off | optional | required. *What* is collected is the game's business:
    # the profile's `sanctioning_account` is the label, and a game with no
    # sanctioning body (None) cannot turn this on at all — see create.
    "collectSanctioningId": "off",
    # measure the disruption a judge call caused and give that table the time
    # back automatically. The judge can still override or decline per call.
    "autoExtendOnCall": True,
    "structure": None,                # a game profile's structure key; None = first
}

SANCTIONING_MODES = ("off", "optional", "required")

# What seat_pods() actually implements. Validated on create because seat 1 takes
# the first turn: a misspelled value silently falls through to "random", which
# is a different fairness decision from the one the organizer asked for and is
# invisible afterwards.
SEAT_MODES = ("random", "by_standings", "manual")

# Settings keys renamed after clients had already shipped. The old name is
# accepted on create and rewritten to the new one, so a build of the app that
# is already in someone's pocket keeps working; nothing is stored under the
# old key, so there is only ever one name in the database.
DEPRECATED_SETTING_KEYS = {"collectWizardsEmail": "collectSanctioningId"}


def defaults_for(game: str | None) -> dict:
    """Generic defaults plus whatever this game says about tables and resources."""
    p = profile_for(game)
    return {
        **GENERIC_SETTINGS,
        "podSize": p.default_pod_size,
        "roundMinutes": p.default_round_minutes,
        "timeCalledPolicy": p.time_called_policies[0],
        # wire name kept as startingLife: the room API already speaks it, and
        # renaming a live settings key buys nothing. It is the profile's
        # resource start, whatever that resource is called.
        "startingLife": p.resource_start,
        "extraTurns": p.extra_turns_at_time,
    }


# Back-compat alias: the shape of an MTG tournament's settings.
DEFAULT_SETTINGS = defaults_for("mtg")


# ---- helpers ----


def new_public_id() -> str:
    """Client-facing entrant id. Random, so it carries no ordering and leaks no
    count — the roster is readable by anyone holding the tournament code."""
    return secrets.token_urlsafe(8)


def resolve_entrant(code: str, public_id) -> "object | None":
    """Public id to row. Everything internal keys on the integer primary key;
    only the boundary speaks public ids."""
    if public_id is None:
        return None
    return q(
        "SELECT * FROM entrants WHERE tournament_code = ? AND public_id = ?",
        (code, str(public_id)),
    ).fetchone()


def pod_in(code: str, pod_id: int):
    """Resolve a pod *through its tournament*.

    A pod id is a global integer. Treating it as self-authorizing let an
    organizer of one event write results into another's, and let anonymous
    callers act on pods they had nothing to do with. Every pod lookup goes
    through here.
    """
    pod = q(
        "SELECT p.* FROM pods p JOIN trounds r ON r.id = p.round_id "
        "WHERE p.id = ? AND r.tournament_code = ?",
        (pod_id, code),
    ).fetchone()
    if not pod:
        raise HTTPException(404, "pod not found")
    return pod


def seat_in_pod(pod_id: int, entrant_id: int) -> bool:
    return bool(
        q(
            "SELECT 1 FROM pod_seats WHERE pod_id = ? AND entrant_id = ?",
            (pod_id, entrant_id),
        ).fetchone()
    )


def public_ids(code: str) -> dict:
    """Internal id to public id for one tournament, in a single query."""
    return {
        r["id"]: r["public_id"]
        for r in q(
            "SELECT id, public_id FROM entrants WHERE tournament_code = ?", (code,)
        ).fetchall()
    }


def settings_of(row) -> dict:
    game = row["game"] if "game" in row.keys() else None
    return {**defaults_for(game), **json.loads(row["settings"] or "{}")}


def sanctioning_label(row) -> str | None:
    """What this event's game calls the id it collects, or None if it has none.

    Every word the server says about the collected id comes from here. Hardcoding
    "Wizards" made the message a lie for any second game, and made it impossible
    to tell a game that has no sanctioning concept from one that does.
    """
    game = row["game"] if "game" in row.keys() else None
    return profile_for(game).sanctioning_account


def touch(code: str):
    q("UPDATE tournaments SET last_active = unixepoch() WHERE code = ?", (code,))


def get_tournament(code: str):
    row = q("SELECT * FROM tournaments WHERE code = ?", (code.upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "tournament not found")
    # check just this tournament's idle clock (primary-key read); the bulk sweep
    # runs on create. Unlike a closed room this is not a 410: an expired event's
    # standings are still worth reading, it just can't be run any more.
    if row["status"] not in ("ended", "expired"):
        cutoff = q("SELECT unixepoch() - ? AS c", (IDLE_TIMEOUT,)).fetchone()["c"]
        if (row["last_active"] or row["created_at"]) < cutoff:
            q("UPDATE tournaments SET status = 'expired' WHERE code = ?", (row["code"],))
            row = q("SELECT * FROM tournaments WHERE code = ?", (row["code"],)).fetchone()
    return row


def require_organizer(code: str, request: Request):
    acct = require_account(request)
    row = get_tournament(code)
    if row["organizer_account_id"] != acct["id"]:
        # This is the whole tournament layer's authorization chokepoint — every
        # organizer action routes through here. It is also the class the
        # 2026-07-19 audit found five defects in, all from treating a client id
        # as self-authorizing. An authenticated account reaching for a
        # tournament it does not own is exactly the probe worth a trace; the
        # subject is a username, never a secret.
        security_event(AUTHZ_DENY, acct["username"], str(request.url.path))
        raise HTTPException(403, "only the organizer can do that")
    return row, acct


def entrant_from_token(code: str, token: str | None):
    if not token:
        return None
    return q(
        "SELECT * FROM entrants WHERE tournament_code = ? AND token = ?",
        (code.upper(), token),
    ).fetchone()


def standings_rows(code: str):
    """Points and tiebreakers in one pass — no per-entrant queries."""
    entrants = q(
        "SELECT * FROM entrants WHERE tournament_code = ? ORDER BY id", (code,)
    ).fetchall()
    seats = q(
        "SELECT s.entrant_id, s.points, s.place, p.id AS pod_id FROM pod_seats s "
        "JOIN pods p ON p.id = s.pod_id JOIN trounds r ON r.id = p.round_id "
        "WHERE r.tournament_code = ?",
        (code,),
    ).fetchall()
    # A draw awards every seat place 1, so "place == 1" alone would report a
    # drawn pod as a win for everyone. The pod's result kind is what separates
    # them; take the latest version, since an override appends rather than
    # mutates.
    kinds = {
        r["pod_id"]: r["kind"]
        for r in q(
            "SELECT pr.pod_id, pr.kind FROM pod_results pr "
            "JOIN pods p ON p.id = pr.pod_id JOIN trounds r ON r.id = p.round_id "
            "WHERE r.tournament_code = ? "
            "AND pr.version = (SELECT MAX(v2.version) FROM pod_results v2 "
            "                  WHERE v2.pod_id = pr.pod_id)",
            (code,),
        ).fetchall()
    }

    points: dict[int, int] = {e["id"]: 0 for e in entrants}
    played: dict[int, int] = {e["id"]: 0 for e in entrants}
    wins: dict[int, int] = {e["id"]: 0 for e in entrants}
    draws: dict[int, int] = {e["id"]: 0 for e in entrants}
    pod_members: dict[int, list[int]] = {}
    for s in seats:
        pod_members.setdefault(s["pod_id"], []).append(s["entrant_id"])
        if s["points"] is not None:
            points[s["entrant_id"]] = points.get(s["entrant_id"], 0) + s["points"]
            played[s["entrant_id"]] = played.get(s["entrant_id"], 0) + 1
            kind = kinds.get(s["pod_id"])
            if kind == "draw":
                draws[s["entrant_id"]] = draws.get(s["entrant_id"], 0) + 1
            elif s["place"] == 1:
                wins[s["entrant_id"]] = wins.get(s["entrant_id"], 0) + 1

    # opponents' points: the standard Swiss tiebreaker, computed from the same rows
    opponents: dict[int, set[int]] = {e["id"]: set() for e in entrants}
    for members in pod_members.values():
        for eid in members:
            opponents.setdefault(eid, set()).update(m for m in members if m != eid)

    out = []
    for e in entrants:
        opp = sum(points.get(o, 0) for o in opponents.get(e["id"], ()))
        out.append(
            {
                "entrantId": e["id"],          # internal; translated at the boundary
                "publicId": e["public_id"],
                "name": e["name"],
                "points": points.get(e["id"], 0),
                "opponentPoints": opp,
                "podsPlayed": played.get(e["id"], 0),
                "wins": wins.get(e["id"], 0),
                "draws": draws.get(e["id"], 0),
                # everything decided that wasn't a win or a draw
                "losses": max(
                    0,
                    played.get(e["id"], 0) - wins.get(e["id"], 0) - draws.get(e["id"], 0),
                ),
                "claimed": e["token"] is not None,
                "dropped": e["dropped_at"] is not None,
            }
        )
    out.sort(key=lambda r: (-r["points"], -r["opponentPoints"], r["name"].lower()))
    for i, row in enumerate(out, 1):
        row["rank"] = i
    return out


def public_standings(code: str):
    """standings_rows() translated for the wire.

    standings_rows carries the internal id because pairing and scoring key on
    it; no response may. Every endpoint that serves standings goes through
    here, so there is one place to get the translation right rather than one
    per caller — POST /end used to serve the raw rows and leaked the integer
    primary key for exactly that reason.
    """
    return [
        {**{k: v for k, v in row.items() if k != "publicId"}, "entrantId": row["publicId"]}
        for row in standings_rows(code)
    ]


def results_rows(code: str) -> list[dict]:
    """Every seat of every pod of every round, with the pod's decision.

    One row per seat rather than per pod: a pod result is an ordering over
    players, and a flat row per player is the shape a spreadsheet, a scorekeeper
    and a rules-committee query all want. Two queries, no N+1, same pattern as
    `standings_rows`.
    """
    seats = q(
        "SELECT r.number AS round_number, p.number AS table_number, p.id AS pod_id, "
        "p.status AS pod_status, s.seat, s.place, s.points, e.public_id, e.name "
        "FROM trounds r JOIN pods p ON p.round_id = r.id "
        "JOIN pod_seats s ON s.pod_id = p.id JOIN entrants e ON e.id = s.entrant_id "
        "WHERE r.tournament_code = ? ORDER BY r.number, p.number, s.seat",
        (code,),
    ).fetchall()
    # An override appends a version rather than mutating, so the export must
    # report the latest one — the same rule standings_rows follows.
    decisions = {
        r["pod_id"]: r
        for r in q(
            "SELECT pr.pod_id, pr.kind, pr.source, pr.note, pr.version FROM pod_results pr "
            "JOIN pods p ON p.id = pr.pod_id JOIN trounds r ON r.id = p.round_id "
            "WHERE r.tournament_code = ? "
            "AND pr.version = (SELECT MAX(v2.version) FROM pod_results v2 "
            "                  WHERE v2.pod_id = pr.pod_id)",
            (code,),
        ).fetchall()
    }
    out = []
    for s in seats:
        d = decisions.get(s["pod_id"])
        out.append(
            {
                "round": s["round_number"],
                "table": s["table_number"],
                "podId": s["pod_id"],
                "podStatus": s["pod_status"],
                "seat": s["seat"],
                "entrantId": s["public_id"],   # public id only; the PK stays here
                "name": s["name"],
                "place": s["place"],
                "points": s["points"],
                "kind": d["kind"] if d else None,
                "source": d["source"] if d else None,
                "version": d["version"] if d else None,
                "note": d["note"] if d else None,
            }
        )
    return out


#: A leading =, +, -, @ or a control character makes Excel and Sheets treat a
#: cell as a formula. Entrant names and result notes are free text typed by
#: whoever ran the event, so a name like `=HYPERLINK(...)` would execute on the
#: organizer's machine when they open the file. Prefix a quote: the value still
#: reads correctly to a human and to any CSV parser, and no spreadsheet
#: evaluates it. Applied to text cells only — never to the numeric columns,
#: where a leading `-` is a real minus sign.
_FORMULA_START = re.compile(r"^[=+\-@\t\r]")


def csv_text(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if _FORMULA_START.match(text) else text


def as_csv(header: list[str], rows: list[dict], text_columns: set[str]) -> str:
    """Rows to CSV via the stdlib writer — entrant names contain commas, quotes
    and the occasional newline, and hand-rolled joining gets that wrong."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for row in rows:
        w.writerow(
            [csv_text(row.get(k)) if k in text_columns else row.get(k, "") for k in header]
        )
    return buf.getvalue()


def met_history(code: str) -> dict[int, list[int]]:
    """Who has already shared a pod with whom, for repeat avoidance."""
    rows = q(
        "SELECT s.pod_id, s.entrant_id FROM pod_seats s JOIN pods p ON p.id = s.pod_id "
        "JOIN trounds r ON r.id = p.round_id WHERE r.tournament_code = ?",
        (code,),
    ).fetchall()
    by_pod: dict[int, list[int]] = {}
    for r in rows:
        by_pod.setdefault(r["pod_id"], []).append(r["entrant_id"])
    met: dict[int, list[int]] = {}
    for members in by_pod.values():
        for eid in members:
            met.setdefault(eid, []).extend(m for m in members if m != eid)
    return met


# ---- top cut ----
#
# A cut is stored as two facts and nothing else: `entrants.cut_seed` says who
# advanced and in what order, and `trounds.kind` says which rounds are bracket
# rounds. Everything else about the bracket — who is still alive, whose turn it
# is to play whom, whether it is over — is derived from the pod results that
# already exist, so there is no second copy of the standings to fall out of
# step with the first.


def cut_seeds(code: str) -> dict[int, int]:
    """Entrant id to bracket seed. Empty when no cut has been made."""
    return {
        r["id"]: r["cut_seed"]
        for r in q(
            "SELECT id, cut_seed FROM entrants WHERE tournament_code = ? AND cut_seed IS NOT NULL",
            (code,),
        ).fetchall()
    }


def last_bracket_round(code: str, closed_only: bool = False):
    status = " AND status = 'closed'" if closed_only else ""
    return q(
        "SELECT * FROM trounds WHERE tournament_code = ? AND kind = 'elimination'"
        + status
        + " ORDER BY number DESC LIMIT 1",
        (code,),
    ).fetchone()


def _dropped_ids(code: str) -> set:
    return {
        r["id"]
        for r in q(
            "SELECT id FROM entrants WHERE tournament_code = ? AND dropped_at IS NOT NULL",
            (code,),
        ).fetchall()
    }


def bracket_survivors(code: str) -> list[int]:
    """Who is still in the cut, in bracket order.

    Read from the last *closed* bracket round, so this answers the same
    question before and during a round: the players who won their way into the
    round now being played are the players still alive. A dropped entrant is
    out of the bracket whatever their result was — a cut is a commitment to
    keep playing, and their pod-mates advance rather than waiting for someone
    who has gone home.
    """
    seeds = cut_seeds(code)
    if not seeds:
        return []
    dropped = _dropped_ids(code)
    last = last_bracket_round(code, closed_only=True)
    if not last:
        return [e for e in sorted(seeds, key=lambda eid: seeds[eid]) if e not in dropped]
    rows = q(
        "SELECT p.number, s.entrant_id, s.place FROM pods p "
        "JOIN pod_seats s ON s.pod_id = p.id WHERE p.round_id = ? ORDER BY p.number, s.seat",
        (last["id"],),
    ).fetchall()
    return [r["entrant_id"] for r in rows if r["place"] == 1 and r["entrant_id"] not in dropped]


def bracket_blocker(code: str) -> str | None:
    """Why the bracket cannot advance, if it cannot.

    Single elimination has no draw to fall back on: a pod that ends with two
    players sharing first has not produced anyone to advance, and the app will
    not pick between them. The organizer rules and the bracket moves on.
    """
    last = last_bracket_round(code, closed_only=True)
    if not last:
        return None
    rows = q(
        "SELECT p.number, s.place FROM pods p JOIN pod_seats s ON s.pod_id = p.id "
        "WHERE p.round_id = ?",
        (last["id"],),
    ).fetchall()
    winners: dict[int, int] = {}
    for r in rows:
        winners[r["number"]] = winners.get(r["number"], 0) + (1 if r["place"] == 1 else 0)
    bad = sorted(n for n, count in winners.items() if count != 1)
    if bad:
        return (
            f"table {bad[0]} has no single winner — single elimination cannot end in a "
            "draw, so record a result that ranks it"
        )
    return None


def bracket_view(code: str) -> dict | None:
    """The cut as clients see it. None until a cut has been made."""
    seeded = q(
        "SELECT id, public_id, name, cut_seed FROM entrants "
        "WHERE tournament_code = ? AND cut_seed IS NOT NULL ORDER BY cut_seed",
        (code,),
    ).fetchall()
    if not seeded:
        return None
    alive = set(bracket_survivors(code))
    rounds = q(
        "SELECT COUNT(*) c FROM trounds WHERE tournament_code = ? AND kind = 'elimination'",
        (code,),
    ).fetchone()["c"]
    champion = next(
        (r["public_id"] for r in seeded if len(alive) == 1 and r["id"] in alive),
        None,
    )
    return {
        "cutTo": len(seeded),
        "rounds": rounds,
        "seeds": [
            {"entrantId": r["public_id"], "name": r["name"], "seed": r["cut_seed"],
             "alive": r["id"] in alive}
            for r in seeded
        ],
        # only once the final round is closed does one survivor mean a winner
        "champion": champion if last_bracket_round(code, closed_only=True) else None,
    }


def pod_views_for(round_row, viewer_entrant=None, organizer: bool = False):
    """The pods of one round, seen by one viewer: `(pods, myPod)`.

    Every rule about who may see what in a pod lives here and nowhere else, so
    the live snapshot and the historical round view cannot drift apart — the
    room code is a credential, the room token belongs to one seat, and the
    entrant id on the wire is always the public one.
    """
    pods, seats = [], []
    if round_row:
        pods = q(
            "SELECT * FROM pods WHERE round_id = ? ORDER BY number", (round_row["id"],)
        ).fetchall()
        if pods:
            marks = ",".join("?" * len(pods))
            seats = q(
                f"SELECT s.*, e.name, e.public_id FROM pod_seats s JOIN entrants e ON e.id = s.entrant_id "
                f"WHERE s.pod_id IN ({marks}) ORDER BY s.pod_id, s.seat",
                tuple(p["id"] for p in pods),
            ).fetchall()
    by_pod: dict[int, list] = {}
    for s in seats:
        by_pod.setdefault(s["pod_id"], []).append(s)

    my_pod = None
    pod_views = []
    round_ends_at = round_row["ends_at"] if round_row else None
    for p in pods:
        members = by_pod.get(p["id"], [])
        view = {
            "podId": p["id"],
            "table": p["number"],
            # the organizer's label for this table, null when it is just its
            # number — clients show the name and keep the number beside it
            "name": p["label"],
            "status": p["status"],
            # The deadline *this table* is playing to. An extension is added on
            # read, exactly as the room view does it (table.py), so a judge
            # extending one table moves only that table and `round.endsAt`
            # stays the round's own deadline. Clients count down against this,
            # never against round.endsAt + extensionSeconds computed by hand.
            "endsAt": (
                round_ends_at + p["extension_seconds"] if round_ends_at is not None else None
            ),
            # A room code lets its holder take a seat in that room, so it is a
            # credential, not a label. Only the organizer and the players at
            # that table get it; it is added to `my_pod` below.
            "roomCode": p["room_code"] if organizer else None,
            "extensionSeconds": p["extension_seconds"],
            "turnsRemaining": p["turns_remaining"],
            "seats": [
                {"seat": s["seat"], "entrantId": s["public_id"], "name": s["name"],
                 "place": s["place"], "points": s["points"]}
                for s in members
            ],
        }
        pod_views.append(view)
        mine = next((s for s in members if s["entrant_id"] == viewer_entrant["id"]), None) if viewer_entrant else None
        if mine:
            # the room token is the viewer's own seat only — it never reaches
            # the pod list everyone else sees
            my_pod = {
                **view,
                "roomCode": p["room_code"],   # their own table, so they get it
                "roomToken": mine["room_token"],
                "mySeat": mine["seat"],
            }
    return pod_views, my_pod


def tournament_state(code: str, viewer_entrant=None, organizer: bool = False):
    """One snapshot for every client. Single query set, personalized in memory."""
    t = get_tournament(code)
    cfg = settings_of(t)
    rounds = q(
        "SELECT * FROM trounds WHERE tournament_code = ? ORDER BY number", (t["code"],)
    ).fetchall()
    latest = rounds[-1] if rounds else None
    pod_views, my_pod = pod_views_for(latest, viewer_entrant, organizer)

    calls = []
    if organizer:
        calls = [
            {"id": c["id"], "podId": c["pod_id"], "status": c["status"],
             "category": c["category"], "note": c["note"], "createdAt": c["created_at"],
             "openSeconds": max(0, int(time.time()) - c["created_at"]),
             "suggestedMinutes": suggested_extension(max(0, int(time.time()) - c["created_at"]))}
            for c in q(
                "SELECT * FROM official_calls WHERE tournament_code = ? AND status != 'resolved' "
                "ORDER BY created_at",
                (t["code"],),
            ).fetchall()
        ]

    return {
        "tournament": {
            "code": t["code"],
            "name": t["name"],
            "game": t["game"] if "game" in t.keys() else "mtg",
            "mode": t["mode"],
            "status": t["status"],
            "settings": cfg,
            "roundCount": len(rounds),
        },
        "round": (
            {
                "number": latest["number"],
                "status": latest["status"],
                # swiss | elimination: a bracket round is paired and adjudicated
                # differently, and players need to know which one they are in
                "kind": latest["kind"] if "kind" in latest.keys() else "swiss",
                "endsAt": latest["ends_at"],
                "pausedAt": latest["paused_at"],
                "now": int(time.time()),  # clients derive an offset, never trust local clocks
            }
            if latest
            else None
        ),
        "pods": pod_views,
        "myPod": my_pod,
        "me": (
            {"entrantId": viewer_entrant["public_id"], "name": viewer_entrant["name"]}
            if viewer_entrant
            else None
        ),
        # standings carry the internal id for callers like pairing; the wire
        # only ever sees the public one, and not both
        "standings": public_standings(t["code"]),
        # null until a cut has been made; the standings above stay in Swiss
        # order, because points are what they measure and a bracket is not
        # decided on points
        "cut": bracket_view(t["code"]),
        "calls": calls,
        "isOrganizer": organizer,
    }


# ---- request bodies ----


class CreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    game: str = Field(default="mtg")
    #: None means "whatever this game's first mode is". It is not defaulted to
    #: "life" here because a game with no room support has no modes at all, and
    #: an unasked-for default would be indistinguishable from an organizer
    #: naming a mode that game cannot run.
    mode: str | None = None
    settings: dict = Field(default_factory=dict)


class EntrantsBody(BaseModel):
    names: list[str] = Field(default_factory=list)
    # imports send [{name, externalRef}] instead; externalRef is "source:id"
    entrants: list[dict] = Field(default_factory=list)


class RenameBody(BaseModel):
    #: same bound as a tournament name; the roster is free text either way
    name: str = Field(min_length=1, max_length=80)


class ClaimBody(BaseModel):
    entrantId: str
    sanctioningId: str | None = None
    #: deprecated: what `sanctioningId` was called when MTG was the only game.
    #: Clients already in the wild still send it, so it is still read.
    wizardsEmail: str | None = None


class RoundBody(BaseModel):
    reroll: bool = False


class CutBody(BaseModel):
    #: how many advance. None takes the number the structure recommends.
    size: int | None = None


class ResultBody(BaseModel):
    kind: str = "placement"                    # placement | draw | unfinished
    places: list[dict] = Field(default_factory=list)   # [{entrantId, place}]
    note: str | None = None
    expectedVersion: int | None = None


class TimerBody(BaseModel):
    action: str                                # start | pause | resume | extend
    minutes: int | None = None
    podId: int | None = None                   # extensions apply to one table


class CallBody(BaseModel):
    category: str | None = None
    note: str | None = None
    #: minutes to add to this table when resolving. Omitted means none — a
    #: judge grants time, the app never grants it on their behalf.
    extendMinutes: int | None = None


# ---- lifecycle ----


@router.get("/mine")
def my_tournaments(request: Request):
    """Every event this account is running.

    Without this an organizer who closes the tab has no way back to their own
    tournament except the URL — the code is on the projector, not in their
    history. Registered before `/{code}` so it isn't read as a tournament code.
    """
    acct = require_account(request)
    # a list read can't use get_tournament's per-row check, and an organizer's
    # dashboard showing "running" against an abandoned event is the one place
    # that lie would be believed
    expire_idle_tournaments()
    rows = q(
        "SELECT t.code, t.name, t.status, t.game, t.mode, t.created_at, t.last_active, "
        "(SELECT COUNT(*) FROM entrants e WHERE e.tournament_code = t.code "
        " AND e.dropped_at IS NULL) AS entrants, "
        "(SELECT COUNT(*) FROM trounds r WHERE r.tournament_code = t.code) AS rounds, "
        "(SELECT COUNT(*) FROM official_calls c WHERE c.tournament_code = t.code "
        " AND c.status != 'resolved') AS openCalls "
        "FROM tournaments t WHERE t.organizer_account_id = ? "
        "ORDER BY COALESCE(t.last_active, t.created_at) DESC LIMIT 100",
        (acct["id"],),
    ).fetchall()
    return {"tournaments": [dict(r) for r in rows]}


@router.get("/games")
def list_games():
    """What this server can run. One profile today; the registry is the point."""
    return {"games": known_games()}


@router.post("")
def create_tournament(body: CreateBody, request: Request):
    """Hosting requires an account with a recovery email: an organizer locked out
    mid-event strands everyone at the table, which recovery codes alone don't
    reliably solve on a phone in a game store."""
    acct = require_account(request)
    if not acct["email"]:
        raise HTTPException(
            409,
            "add a recovery email to your account before hosting — "
            "an organizer who loses access mid-event strands the whole room",
        )
    expire_idle_tournaments()  # cheap hygiene sweep, off the hot path
    known = {g["key"] for g in known_games()}
    if body.game not in known:
        raise HTTPException(400, f"unknown game — this server runs {', '.join(sorted(known))}")
    profile = profile_for(body.game)
    if profile.modes:
        mode = body.mode or profile.modes[0]
        if mode not in profile.modes:
            raise HTTPException(400, f"{profile.name} has no '{mode}' mode")
    else:
        # A game with no room support has no live table state to name: its pods
        # are seated and reported by hand. Skipping validation here meant any
        # string was accepted and stored against a tournament whose pods never
        # get a room, so the value could only ever mislead. The stored mode for
        # such an event is the empty string.
        if body.mode:
            raise HTTPException(
                400, f"{profile.name} has no room modes — it is scored by hand"
            )
        mode = ""

    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
    allowed = defaults_for(body.game)
    submitted = {DEPRECATED_SETTING_KEYS.get(k, k): v for k, v in body.settings.items()}
    # an explicit new key wins over its deprecated alias, whatever the dict order
    submitted.update({k: v for k, v in body.settings.items() if k in allowed})
    cfg = {k: v for k, v in submitted.items() if k in allowed}
    if "timeCalledPolicy" in cfg:
        # a client on an older build still sends the old spelling; accept it and
        # store the current one so the alias stays a boundary concern
        cfg["timeCalledPolicy"] = canonical_policy(cfg["timeCalledPolicy"])
        if cfg["timeCalledPolicy"] not in profile.time_called_policies:
            raise HTTPException(400, f"{profile.name} does not offer that time-called policy")
    if "collectSanctioningId" in cfg:
        want = cfg["collectSanctioningId"]
        if want not in SANCTIONING_MODES:
            raise HTTPException(
                400, f"collectSanctioningId must be one of {', '.join(SANCTIONING_MODES)}"
            )
        # A game with no sanctioning body has nothing to collect and no word for
        # it. Accepting "required" here produced an event that blocked every
        # claim on an id the player could not possibly hold, behind a prompt
        # with no label — so it is refused at the only place settings are set.
        if want != "off" and not profile.sanctioning_account:
            raise HTTPException(
                400, f"{profile.name} has no sanctioning account, so there is no id to collect"
            )
    if "seatAssignment" in cfg and cfg["seatAssignment"] not in SEAT_MODES:
        raise HTTPException(400, f"seatAssignment must be one of {', '.join(SEAT_MODES)}")
    q(
        "INSERT INTO tournaments (code, name, organizer_account_id, game, mode, settings, last_active) "
        "VALUES (?, ?, ?, ?, ?, ?, unixepoch())",
        (code, body.name.strip(), acct["id"], body.game, mode, json.dumps(cfg)),
    )
    return {"code": code, "game": body.game}


@router.get("/{code}/plan")
def plan(code: str, request: Request, players: int | None = None):
    """What this structure says to run for the current field.

    Advisory only: it recommends rounds and a cut, it does not schedule them.
    `official` says whether a published rules document backs the numbers — a
    house convention must never be shown as if Wizards wrote it.
    """
    t = get_tournament(code)
    cfg = settings_of(t)
    game = t["game"] if "game" in t.keys() else None
    struct = structure_for(game, cfg.get("structure"), cfg.get("podSize"))
    if not struct:
        raise HTTPException(409, "this game has no event structures")
    if players is None:
        players = q(
            "SELECT COUNT(*) c FROM entrants WHERE tournament_code = ? AND dropped_at IS NULL",
            (t["code"],),
        ).fetchone()["c"]
    played = q(
        "SELECT COUNT(*) c FROM trounds WHERE tournament_code = ? AND status = 'closed'",
        (t["code"],),
    ).fetchone()["c"]
    out = struct.plan(players)
    out["name"] = struct.name
    out["notes"] = struct.notes
    out["roundsPlayed"] = played
    out["roundsRemaining"] = max(0, out["swissRounds"] - played)
    return out


def viewing_as_organizer(t, request: Request) -> bool:
    """Is this reader the organizer? A missing or foreign session is not an
    error on a read path — it just means a plainer view, so this never raises.
    """
    try:
        from .accounts import current_account

        acct = current_account(request)
    except Exception:
        acct = None
    return bool(acct and acct["id"] == t["organizer_account_id"])


@router.get("/{code}")
def get_state(code: str, request: Request, token: str | None = None):
    t = get_tournament(code)
    organizer = viewing_as_organizer(t, request)
    return tournament_state(t["code"], entrant_from_token(t["code"], token), organizer)


@router.get("/{code}/rounds/{number}")
def get_round(code: str, number: int, request: Request, token: str | None = None):
    """One round as it was: its pairings, pods, seats and results.

    The live snapshot deliberately carries only the latest round, so a player
    asking "who did I play in round 1, and what did we end up with?" had no
    answer once round 2 opened. Readable by exactly whoever may read
    `GET /{code}` — possession of the code is the gate there and a past round
    exposes nothing the round did not already show while it was live — and it
    reuses the same pod view, so the room code stays organizer-only and a room
    token still reaches one seat and one caller.
    """
    t = get_tournament(code)
    organizer = viewing_as_organizer(t, request)
    viewer = entrant_from_token(t["code"], token)
    rnd = q(
        "SELECT * FROM trounds WHERE tournament_code = ? AND number = ?", (t["code"], number)
    ).fetchone()
    if not rnd:
        raise HTTPException(404, "no such round")

    pod_views, my_pod = pod_views_for(rnd, viewer, organizer)

    # What the pod was ruled, not just the seat placings: a draw awards every
    # seat place 1, so placings alone cannot tell a drawn pod from a four-way
    # tie for the win. An override appends a version rather than mutating, so
    # the latest version is the standing decision. The organizer's note is the
    # one part kept back — it is a ruling written for staff, and the design
    # never showed it to the table.
    results = {}
    if pod_views:
        marks = ",".join("?" * len(pod_views))
        for r in q(
            f"SELECT * FROM pod_results pr WHERE pr.pod_id IN ({marks}) "
            f"AND pr.version = (SELECT MAX(v2.version) FROM pod_results v2 WHERE v2.pod_id = pr.pod_id)",
            tuple(p["podId"] for p in pod_views),
        ).fetchall():
            results[r["pod_id"]] = {
                "kind": r["kind"],
                "source": r["source"],
                "version": r["version"],
                "decidedAt": r["decided_at"],
                **({"note": r["note"]} if organizer else {}),
            }
    for view in pod_views:
        view["result"] = results.get(view["podId"])
    if my_pod:
        my_pod["result"] = results.get(my_pod["podId"])

    return {
        "round": {
            "number": rnd["number"],
            "status": rnd["status"],
            "endsAt": rnd["ends_at"],
            "pausedAt": rnd["paused_at"],
            "now": int(time.time()),  # same contract as the snapshot: never trust a local clock
        },
        "pods": pod_views,
        "myPod": my_pod,
        "me": ({"entrantId": viewer["public_id"], "name": viewer["name"]} if viewer else None),
        "isOrganizer": organizer,
    }


@router.post("/{code}/entrants")
def add_entrants(code: str, body: EntrantsBody, request: Request):
    t, _ = require_organizer(code, request)
    incoming = [{"name": n, "externalRef": None} for n in body.names]
    incoming += [
        {"name": str(e.get("name", "")), "externalRef": e.get("externalRef")}
        for e in body.entrants
    ]

    added, matched = [], []
    for item in incoming:
        name = item["name"].strip()
        ref = (item["externalRef"] or None) and str(item["externalRef"]).strip()
        if not name:
            continue
        if ref:
            # re-running an import must find the same person, not clone them.
            # Matching on name would make display names identity.
            existing = q(
                "SELECT id, public_id, name FROM entrants WHERE tournament_code = ? AND external_ref = ?",
                (t["code"], ref),
            ).fetchone()
            if existing:
                if existing["name"] != name:  # they renamed upstream; follow it
                    q("UPDATE entrants SET name = ? WHERE id = ?", (name, existing["id"]))
                matched.append(
                    {"entrantId": existing["public_id"], "name": name, "externalRef": ref}
                )
                continue
        pub = new_public_id()
        q(
            "INSERT INTO entrants (tournament_code, name, external_ref, public_id) "
            "VALUES (?, ?, ?, ?)",
            (t["code"], name, ref, pub),
        )
        added.append({"entrantId": pub, "name": name, "externalRef": ref})
    touch(t["code"])
    return {"added": added, "matched": matched}


@router.get("/{code}/roster")
def roster(code: str):
    """Public by design: a player scans the code and picks their name."""
    t = get_tournament(code)
    rows = q(
        "SELECT public_id, name, token IS NOT NULL AS claimed, dropped_at FROM entrants "
        "WHERE tournament_code = ? ORDER BY name COLLATE NOCASE",
        (t["code"],),
    ).fetchall()
    # The claim form is drawn from this response — the player has no credential
    # yet, so this is the only place they can learn whether an id is wanted and
    # what to call it. The label is the profile's, never a word from this module.
    cfg = settings_of(t)
    label = sanctioning_label(t)
    collect = cfg["collectSanctioningId"] if label else "off"
    return {
        "name": t["name"],
        "status": t["status"],
        "sanctioning": {"collect": collect, "label": label if collect != "off" else None},
        "entrants": [
            {"entrantId": r["public_id"], "name": r["name"], "claimed": bool(r["claimed"]),
             "dropped": r["dropped_at"] is not None}
            for r in rows
        ],
    }


@router.post("/{code}/claim")
def claim(code: str, body: ClaimBody):
    """Claim a seat by id — names may repeat, ids don't. First claim wins; the
    organizer can release one if somebody taps the wrong name."""
    t = get_tournament(code)
    row = resolve_entrant(t["code"], body.entrantId)
    if not row:
        raise HTTPException(404, "not on this roster")
    if row["token"]:
        raise HTTPException(409, "that name is already claimed — ask the organizer to release it")

    # Only collected when the organizer turns it on, because a sanctioned event
    # has to report the field to whoever sanctions it. Never collected by
    # default, never shown to other players, never used for anything else.
    cfg = settings_of(t)
    label = sanctioning_label(t)
    sid = (body.sanctioningId or body.wizardsEmail or "").strip() or None
    # No label means this game has no sanctioning body. Create refuses to turn
    # collection on for such a game, but a row written before that check existed
    # (or by a build that still knew a game this one doesn't) must not strand a
    # player behind a prompt the server cannot even name.
    if cfg["collectSanctioningId"] == "off" or not label:
        sid = None
    elif cfg["collectSanctioningId"] == "required" and not sid:
        raise HTTPException(422, f"this event is sanctioned, so it needs your {label}")

    token = secrets.token_urlsafe(24)
    q(
        "UPDATE entrants SET token = ?, wizards_email = COALESCE(?, wizards_email) WHERE id = ?",
        (token, sid, row["id"]),
    )
    touch(t["code"])
    return {"entrantToken": token, "entrantId": row["public_id"], "name": row["name"]}


@router.post("/{code}/entrants/{entrant_id}/release")
def release_claim(code: str, entrant_id: str, request: Request):
    t, _ = require_organizer(code, request)
    row = resolve_entrant(t["code"], entrant_id)
    if not row:
        raise HTTPException(404, "no such entrant")
    q(
        "UPDATE entrants SET token = NULL WHERE id = ?", (row["id"],),
    )
    return {"ok": True}


@router.post("/{code}/entrants/{entrant_id}/rename")
def rename_entrant(code: str, entrant_id: str, body: RenameBody, request: Request):
    """Fix a misspelled or mis-heard name on the roster.

    A rename touches `entrants.name` and nothing else. Identity here is the
    public id — the roster, results, standings and pairings all key on it — so
    the token stays valid, the public id is stable, and every recorded place and
    point survives untouched. That is also why a duplicate name is allowed:
    names legitimately repeat (§7), and rejecting one would make the display
    name identity, which is the exact flaw the import path avoids.

    It deliberately does not rewrite the player rows in pods already seated.
    A pod's room is a separate identity — a player renaming themselves inside a
    room does not touch their entrant either — and rewriting a live room's
    seats from the tournament would let an organizer's typo fix relabel a game
    in progress. The new name shows on the roster and standings immediately,
    and on the next round's seats.
    """
    t, _ = require_organizer(code, request)
    row = resolve_entrant(t["code"], entrant_id)
    if not row:
        raise HTTPException(404, "no such entrant")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "a name is required")
    q("UPDATE entrants SET name = ? WHERE id = ?", (name, row["id"]))
    touch(t["code"])
    return {"ok": True, "entrantId": row["public_id"], "name": name}


@router.post("/{code}/entrants/{entrant_id}/undrop")
def undrop_entrant(code: str, entrant_id: str, request: Request):
    """People come back — a drop entered by mistake shouldn't end someone's day."""
    t, _ = require_organizer(code, request)
    row = resolve_entrant(t["code"], entrant_id)
    if not row:
        raise HTTPException(404, "no such entrant")
    q(
        "UPDATE entrants SET dropped_at = NULL WHERE id = ?", (row["id"],),
    )
    touch(t["code"])
    return {"ok": True}


@router.post("/{code}/end")
def end_tournament(code: str, request: Request):
    """Close the event and freeze the final standings."""
    t, _ = require_organizer(code, request)
    open_round = q(
        "SELECT id FROM trounds WHERE tournament_code = ? AND status = 'active'", (t["code"],)
    ).fetchone()
    if open_round:
        raise HTTPException(409, "close the current round before ending the tournament")
    q("UPDATE tournaments SET status = 'ended' WHERE code = ?", (t["code"],))
    touch(t["code"])
    return {"ok": True, "standings": public_standings(t["code"])}


#: Fixed column orders. Written down rather than derived from a dict so that
#: adding a field to the API cannot silently reorder somebody's saved import.
STANDINGS_COLUMNS = [
    "rank", "entrantId", "name", "points", "opponentPoints",
    "podsPlayed", "wins", "draws", "losses", "claimed", "dropped",
]
RESULTS_COLUMNS = [
    "round", "table", "seat", "entrantId", "name", "place", "points",
    "kind", "source", "version", "note",
]


def export_standings(code: str) -> list[dict]:
    """Standings as the wire sees them: the internal id swapped for the public
    one, never both. It is `public_standings()` and nothing else — a file that
    outlives the event is the last place to translate ids a second way, so the
    export shares the single boundary the snapshot and `POST /end` go through.
    """
    return public_standings(code)


@router.get("/{code}/export")
def export(code: str, request: Request, what: str = "standings", format: str = "json"):
    """Take the event's numbers away with you — organizer only.

    An organizer needs the results outside this app: to report a sanctioned
    event upstream, to post a league table, or simply to keep a record once the
    tournament is swept. This is the whole of that path, so it is deliberately
    a download rather than another polling shape.

    **`entrantId` is the public id in every format.** The integer primary key
    never leaves the server (§3), and a file that outlives the event is the
    worst possible place to make an exception: it gets mailed around, pasted
    into spreadsheets and re-imported long after anyone remembers what the
    column meant.

    Organizer-only even though the roster and standings are readable with the
    tournament code alone. A bulk file is not the same disclosure as a screen:
    it hands whoever holds the code the entire history of the event in one
    request, and export is an organizer's action anyway.
    """
    t, _ = require_organizer(code, request)
    if what not in ("standings", "results", "all"):
        raise HTTPException(400, "export 'what' must be standings, results or all")
    if format not in ("json", "csv"):
        raise HTTPException(400, "export 'format' must be json or csv")

    if format == "csv":
        if what == "all":
            # A CSV file is one table. Ask for one of them.
            raise HTTPException(400, "csv exports one table at a time — ask for standings or results")
        if what == "standings":
            rows = [
                {**r, "claimed": str(bool(r["claimed"])).lower(),
                 "dropped": str(bool(r["dropped"])).lower()}
                for r in export_standings(t["code"])
            ]
            body = as_csv(STANDINGS_COLUMNS, rows, {"entrantId", "name"})
        else:
            body = as_csv(RESULTS_COLUMNS, results_rows(t["code"]), {"entrantId", "name", "note"})
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{t["code"]}-{what}.csv"',
            },
        )

    payload = {
        "tournament": {
            "code": t["code"],
            "name": t["name"],
            "game": t["game"] if "game" in t.keys() else "mtg",
            "status": t["status"],
        },
        "exportedAt": int(time.time()),
    }
    if what in ("standings", "all"):
        payload["standings"] = export_standings(t["code"])
    if what in ("results", "all"):
        payload["results"] = results_rows(t["code"])
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="{t["code"]}-{what}.json"',
        },
    )


@router.post("/{code}/entrants/{entrant_id}/drop")
def drop_entrant(code: str, entrant_id: str, request: Request):
    t, _ = require_organizer(code, request)
    row = resolve_entrant(t["code"], entrant_id)
    if not row:
        raise HTTPException(404, "no such entrant")
    q(
        "UPDATE entrants SET dropped_at = unixepoch() WHERE id = ?", (row["id"],),
    )
    return {"ok": True}


# ---- rounds ----


def _make_room_for_pod(t, cfg, pod_id: int, seats: list[tuple[int, str]]) -> str:
    """Back a pod with an ordinary room so the whole table app just works."""
    from . import table as table_mod

    room_code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
    q(
        "INSERT INTO rooms (code, url_id, mode, starting_life, status, last_active) "
        "VALUES (?, ?, ?, ?, 'lobby', unixepoch())",
        (room_code, table_mod.new_url_id(), t["mode"], cfg["startingLife"]),
    )
    for order, (entrant_id, name) in enumerate(seats, 1):
        token = secrets.token_urlsafe(24)
        q(
            "INSERT INTO players (room_code, token, name, is_host, seat_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (room_code, token, name, 1 if order == 1 else 0, order),
        )
        q(
            "UPDATE pod_seats SET room_token = ? WHERE pod_id = ? AND entrant_id = ?",
            (token, pod_id, entrant_id),
        )
    table_mod.log_event(room_code, f"pod {pod_id} seated from tournament {t['code']}")
    return room_code


def _unseat_from_room(pod, room_token: str | None, name: str):
    """Take a moved entrant out of the room behind the table they are leaving.

    Their phone is still holding this room's token, so it has to stop working
    here: otherwise they keep a vote on life totals and eliminations at a table
    they are no longer playing at. This mirrors `leave` in the room module — in
    the lobby the seat simply goes away, and mid-game the row stays (identity
    revealed, Treachery CR 907.13) because the events and commander damage that
    mention it are already history.
    """
    from . import table as table_mod

    if not (pod["room_code"] and room_token):
        return
    player = q(
        "SELECT * FROM players WHERE room_code = ? AND token = ?",
        (pod["room_code"], room_token),
    ).fetchone()
    if not player:
        return
    room = q("SELECT * FROM rooms WHERE code = ?", (pod["room_code"],)).fetchone()
    if room and table_mod.norm_status(room["status"]) == "lobby":
        q("DELETE FROM players WHERE id = ?", (player["id"],))
    else:
        q("UPDATE players SET left_game = 1, revealed = 1 WHERE id = ?", (player["id"],))
    if player["is_host"]:
        # a table left without a host cannot start its game
        nxt = q(
            "SELECT id FROM players WHERE room_code = ? AND left_game = 0 AND is_display = 0 "
            "ORDER BY joined_at, id LIMIT 1",
            (pod["room_code"],),
        ).fetchone()
        if nxt:
            q("UPDATE players SET is_host = 1 WHERE id = ?", (nxt["id"],))
    table_mod.log_event(pod["room_code"], f"{name} was moved to another table by the organizer")


def _seat_in_room(pod, name: str) -> str | None:
    """Seat a moved entrant in their new table's room and hand back their token.

    The token is new rather than carried across: a room token is scoped to one
    room, and the one they were holding has just been retired at the table they
    left. They pick this one up from their own tournament poll — `myPod` carries
    it — so nothing has to be typed at the table.
    """
    from . import table as table_mod

    if not pod["room_code"]:
        return None
    room = q("SELECT * FROM rooms WHERE code = ?", (pod["room_code"],)).fetchone()
    if not room:
        return None
    seat_order = (
        q(
            "SELECT COALESCE(MAX(seat_order), 0) AS m FROM players WHERE room_code = ?",
            (pod["room_code"],),
        ).fetchone()["m"]
        + 1
    )
    hosted = q(
        "SELECT 1 FROM players WHERE room_code = ? AND is_host = 1 AND left_game = 0 LIMIT 1",
        (pod["room_code"],),
    ).fetchone()
    playing = table_mod.norm_status(room["status"]) == "playing"
    token = secrets.token_urlsafe(24)
    q(
        "INSERT INTO players (room_code, token, name, is_host, seat_order, life) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            pod["room_code"],
            token,
            name,
            0 if hosted else 1,
            seat_order,
            # arriving at a game already under way: start them on the room's
            # resource total rather than at null, which renders as no life at all
            room["starting_life"] if playing else None,
        ),
    )
    table_mod.log_event(pod["room_code"], f"{name} was moved to this table by the organizer")
    if playing and room["mode"] == "treachery":
        # nothing deals an identity into a game in progress, so say it at the
        # table instead of leaving somebody silently card-less
        table_mod.log_event(
            pod["room_code"], f"{name} has no identity card — deal one or restart the game"
        )
    return token


def _persist_pods(t, cfg, round_id: int, pods, names: dict) -> int:
    """Write a paired round to the database, one room per pod.

    A pod of one is a bye: it gets no room — there is no game to play — and its
    result is written straight away, so the round can close and, in a bracket,
    the entrant advances without having to be ruled on.

    A game whose profile has no modes has no live table state to keep, so *all*
    of its pods are seated and left roomless: the organizer reports each result
    by hand. Everything that reads a pod already treats a missing `room_code` as
    "no table app here" rather than as an error.
    """
    roomless = not profile_for(t["game"] if "game" in t.keys() else None).modes
    for i, pod in enumerate(pods, 1):
        bye = len(pod.seats) == 1
        cur = q(
            "INSERT INTO pods (round_id, number, status) VALUES (?, ?, ?)",
            (round_id, i, "pending" if bye else "active"),
        )
        pod_id = cur.lastrowid
        for seat_no, entrant_id in enumerate(pod.seats, 1):
            q(
                "INSERT INTO pod_seats (pod_id, entrant_id, seat) VALUES (?, ?, ?)",
                (pod_id, entrant_id, seat_no),
            )
        if bye:
            row = q("SELECT * FROM pods WHERE id = ?", (pod_id,)).fetchone()
            _write_result(t, row, "bye", [{"entrantId": pod.seats[0], "place": 1}], "auto", "bye")
            continue
        if roomless:
            continue
        room = _make_room_for_pod(t, cfg, pod_id, [(eid, names[eid]) for eid in pod.seats])
        q("UPDATE pods SET room_code = ?, game_no = 0 WHERE id = ?", (room, pod_id))
    return len(pods)


def _open_bracket_round(t, cfg, reuse=None) -> dict:
    """Pair the next single-elimination round from the bracket.

    No pairer runs here: a bracket is not a pairing problem, it is an ordering
    one, and the order was fixed by the standings at the cut. Seating inside a
    pod is still the tournament's seating setting — who takes the first turn is
    a fairness question in any round.
    """
    code = t["code"]
    blocker = bracket_blocker(code)
    if blocker:
        raise HTTPException(409, blocker)
    order = bracket_survivors(code)
    if len(order) < 2:
        raise HTTPException(
            409,
            "the top cut is already decided — end the tournament"
            if order
            else "nobody is left in the cut",
        )

    if reuse is not None:
        q("DELETE FROM pods WHERE round_id = ?", (reuse["id"],))
        round_id, number, seed = reuse["id"], reuse["number"], reuse["seed"] + 1
        q(
            "UPDATE trounds SET seed = ?, kind = 'elimination', status = 'active' WHERE id = ?",
            (seed, round_id),
        )
    else:
        prior = q(
            "SELECT COALESCE(MAX(number), 0) AS n, COALESCE(MAX(seed), 0) AS s "
            "FROM trounds WHERE tournament_code = ?",
            (code,),
        ).fetchone()
        number, seed = prior["n"] + 1, prior["s"] + 1
        cur = q(
            "INSERT INTO trounds (tournament_code, number, status, seed, kind) "
            "VALUES (?, ?, 'active', ?, 'elimination')",
            (code, number, seed),
        )
        round_id = cur.lastrowid

    names = {
        r["id"]: r["name"]
        for r in q("SELECT id, name FROM entrants WHERE tournament_code = ?", (code,)).fetchall()
    }
    points = {r["entrantId"]: r["points"] for r in standings_rows(code)}
    seat_input = [PairEntrant(id=eid, points=points.get(eid, 0)) for eid in order]
    pods = bracket_pods(order, pod_size=cfg["podSize"])
    pods = seat_pods(pods, seat_input, mode=cfg["seatAssignment"], seed=seed)
    _persist_pods(t, cfg, round_id, pods, names)

    q("UPDATE tournaments SET status = 'running' WHERE code = ?", (code,))
    touch(code)
    return {
        "round": number,
        "kind": "elimination",
        "pods": len(pods),
        "byes": sum(1 for p in pods if len(p.seats) == 1),
        "remaining": len(order),
    }


@router.post("/{code}/rounds")
def open_round(code: str, body: RoundBody, request: Request):
    """Pair, seat, and — for a game with room support — create a room per pod.
    Pairing is computed and persisted before anything is announced, so the round
    opening is a broadcast of settled state rather than work done under load.

    A game whose profile has no modes has no live table state to keep, so its
    pods are seated and left roomless: the organizer reports each result by
    hand. Everything that reads a pod already treats a missing `room_code` as
    "no table app here" rather than as an error.

    Once a cut has been made this opens the next bracket round instead: after a
    cut there is no Swiss left to pair, and the field is whoever is still in.
    """
    t, _ = require_organizer(code, request)
    cfg = settings_of(t)
    if t["status"] == "ended":
        raise HTTPException(409, "this tournament has ended")
    if t["status"] == "expired":
        # get_tournament already flipped it; pairing a new round here would seat
        # people into rooms the sweep has stopped protecting
        raise HTTPException(409, "this tournament has expired")

    active = q(
        "SELECT * FROM trounds WHERE tournament_code = ? AND status = 'active'", (t["code"],)
    ).fetchone()
    if active and not body.reroll:
        raise HTTPException(409, "close the current round first")

    if cut_seeds(t["code"]):
        if body.reroll:
            # There is nothing to re-roll: the bracket pairing is the seeding,
            # so it would come back identical. Re-cutting is the real remedy.
            raise HTTPException(409, "a bracket is seeded, not paired — it cannot be re-rolled")
        return _open_bracket_round(t, cfg)

    prior = q(
        "SELECT COALESCE(MAX(number), 0) AS n, COALESCE(MAX(seed), 0) AS s "
        "FROM trounds WHERE tournament_code = ?",
        (t["code"],),
    ).fetchone()

    if body.reroll and active:
        # discard the unplayed pairing and roll a genuinely different one
        q("DELETE FROM pods WHERE round_id = ?", (active["id"],))
        number, seed, round_id = active["number"], active["seed"] + 1, active["id"]
        q("UPDATE trounds SET seed = ? WHERE id = ?", (seed, round_id))
    else:
        number, seed = prior["n"] + 1, prior["s"] + 1
        cur = q(
            "INSERT INTO trounds (tournament_code, number, status, seed) VALUES (?, ?, 'active', ?)",
            (t["code"], number, seed),
        )
        round_id = cur.lastrowid

    standings = {r["entrantId"]: r["points"] for r in standings_rows(t["code"])}
    met = met_history(t["code"])
    field = q(
        "SELECT id, name FROM entrants WHERE tournament_code = ? AND dropped_at IS NULL ORDER BY id",
        (t["code"],),
    ).fetchall()
    if not field:
        raise HTTPException(400, "nobody to pair")
    names = {e["id"]: e["name"] for e in field}

    pair_input = [
        PairEntrant(id=e["id"], points=standings.get(e["id"], 0), met=tuple(met.get(e["id"], ())))
        for e in field
    ]
    pods = pair_round(pair_input, preferred_size=cfg["podSize"], seed=seed)
    pods = seat_pods(pods, pair_input, mode=cfg["seatAssignment"], seed=seed)

    _persist_pods(t, cfg, round_id, pods, names)

    q("UPDATE tournaments SET status = 'running' WHERE code = ?", (t["code"],))
    touch(t["code"])
    return {"round": number, "kind": "swiss", "pods": len(pods)}


@router.post("/{code}/cut")
def make_cut(code: str, body: CutBody, request: Request):
    """Cut the field to the top N and open the first single-elimination round.

    Seeding is the Swiss standings as they stand: points, then opponents'
    points, then name — the same order the standings have shown all day, so an
    organizer can read the bracket off the screen everyone was already looking
    at. Nobody is cut *into* a bracket they cannot play, so a dropped entrant
    is skipped and the next player up takes the slot; that is the only place
    the seeding departs from the standings.

    Size comes from the game profile's structure when it is not given, which is
    the same number `GET /{code}/plan` has been recommending. A structure that
    recommends no cut needs an explicit size — running one anyway is a
    legitimate organizer decision, guessing on their behalf is not.
    """
    t, _ = require_organizer(code, request)
    cfg = settings_of(t)
    if t["status"] == "ended":
        raise HTTPException(409, "this tournament has ended")

    # A mis-typed size is worth undoing, a played bracket is not: re-seeding
    # from Swiss standings after a round of the cut has been played would
    # resurrect the people it eliminated.
    existing = last_bracket_round(t["code"])
    if existing:
        drawn = q(
            "SELECT COUNT(*) c FROM trounds WHERE tournament_code = ? AND kind = 'elimination'",
            (t["code"],),
        ).fetchone()["c"]
        # a bye is written the moment the bracket is drawn, so it is not
        # evidence that anybody has played
        played = q(
            "SELECT COUNT(*) c FROM pod_results pr JOIN pods p ON p.id = pr.pod_id "
            "WHERE p.round_id = ? AND pr.kind != 'bye'",
            (existing["id"],),
        ).fetchone()["c"]
        if played or drawn > 1 or existing["status"] != "active":
            raise HTTPException(409, "the cut has already been played — it cannot be re-drawn")

    active = q(
        "SELECT * FROM trounds WHERE tournament_code = ? AND status = 'active'", (t["code"],)
    ).fetchone()
    if active and not (existing and active["id"] == existing["id"]):
        raise HTTPException(409, "close the current round before cutting")
    closed = q(
        "SELECT COUNT(*) c FROM trounds WHERE tournament_code = ? AND status = 'closed'",
        (t["code"],),
    ).fetchone()["c"]
    if not closed:
        raise HTTPException(409, "play a round first — a bracket is seeded from the standings")

    field = [r for r in standings_rows(t["code"]) if not r["dropped"]]
    if len(field) < 2:
        raise HTTPException(409, "not enough entrants left to cut")

    size = body.size
    if size is None:
        game = t["game"] if "game" in t.keys() else None
        struct = structure_for(game, cfg.get("structure"), cfg.get("podSize"))
        size = struct.plan(len(field))["cutTo"] if struct else 0
        if not size:
            raise HTTPException(409, "this structure recommends no cut — name a size to run one")
    if size < 2:
        raise HTTPException(400, "a cut is at least two entrants")
    size = min(size, len(field))

    q("UPDATE entrants SET cut_seed = NULL WHERE tournament_code = ?", (t["code"],))
    seeded = field[:size]
    for seed, row in enumerate(seeded, 1):
        q("UPDATE entrants SET cut_seed = ? WHERE id = ?", (seed, row["entrantId"]))

    opened = _open_bracket_round(t, cfg, reuse=existing)
    return {
        "ok": True,
        "cutTo": size,
        "seeds": [
            {"entrantId": r["publicId"], "name": r["name"], "seed": i, "points": r["points"]}
            for i, r in enumerate(seeded, 1)
        ],
        **opened,
    }


@router.post("/{code}/rounds/close")
def close_round(code: str, request: Request):
    t, _ = require_organizer(code, request)
    rnd = q(
        "SELECT * FROM trounds WHERE tournament_code = ? AND status = 'active'", (t["code"],)
    ).fetchone()
    if not rnd:
        raise HTTPException(409, "no round is open")
    open_calls = q(
        "SELECT COUNT(*) c FROM official_calls WHERE tournament_code = ? AND status != 'resolved'",
        (t["code"],),
    ).fetchone()["c"]
    if open_calls:
        raise HTTPException(409, f"{open_calls} official call(s) still open — resolve or dismiss first")
    unfinished = q(
        "SELECT COUNT(*) c FROM pods WHERE round_id = ? AND status != 'complete'", (rnd["id"],)
    ).fetchone()["c"]
    if unfinished:
        raise HTTPException(409, f"{unfinished} pod(s) have no result yet")
    q("UPDATE trounds SET status = 'closed' WHERE id = ?", (rnd["id"],))
    touch(t["code"])
    return {"ok": True}


# ---- seating overrides ----
#
# The pairer is the only thing that seats anyone, which is right for the first
# minute of a round and wrong for the hour after it: somebody registers late,
# two people were split by a mistake anyone at the table can see, a table is
# being streamed and wants a name rather than a number.
#
# All three overrides stop at the same line — a recorded result. A pod's result
# is a ruling about a specific set of players, and moving someone in or out
# after it would silently rewrite a decided game: their points would follow them
# to a table they never played at, and `met_history` would claim they faced
# people they never sat with. Before a result there is nothing to rewrite, so
# the move is free; after one the organizer's route is to correct the result,
# which is versioned and auditable, rather than to re-pair around it.
#
# `met_history` and `standings` are both derived from `pod_seats` rather than
# stored, so a move that happens before a result needs no repair: whoever is
# sitting at the table when it is decided is who played there.

MIN_POD_SEATS = 3   # pod_sizes() never produces fewer, and an override shouldn't either


class MoveBody(BaseModel):
    entrantId: str


class SeatOrderBody(BaseModel):
    entrantIds: list[str] = Field(default_factory=list)


class PodNameBody(BaseModel):
    #: null or blank clears it and the table goes back to being its number
    name: str | None = Field(default=None, max_length=40)


def active_round(code: str):
    rnd = q(
        "SELECT * FROM trounds WHERE tournament_code = ? AND status = 'active'", (code,)
    ).fetchone()
    if not rnd:
        raise HTTPException(409, "no round is open")
    return rnd


def seat_count(pod_id: int) -> int:
    return q("SELECT COUNT(*) AS c FROM pod_seats WHERE pod_id = ?", (pod_id,)).fetchone()["c"]


def require_rearrangeable(pod, rnd):
    """A pod may only be re-arranged while it is live and undecided."""
    if pod["round_id"] != rnd["id"]:
        raise HTTPException(409, "that table belongs to a round that is no longer open")
    decided = pod["status"] == "complete" or q(
        "SELECT 1 FROM pod_results WHERE pod_id = ? LIMIT 1", (pod["id"],)
    ).fetchone()
    if decided:
        raise HTTPException(
            409,
            f"table {pod['number']} already has a result — moving someone now would "
            "rewrite a decided game; correct the result instead",
        )


@router.post("/{code}/pods/{pod_id}/move")
async def move_entrant(code: str, pod_id: int, body: MoveBody, request: Request):
    """Move an entrant to this table, from wherever the pairer put them.

    The pod in the path is the *destination*: "seat them here" is the action an
    organizer is taking, and the table they came from is derivable. An entrant
    with no seat in the open round — somebody who registered after it was
    paired — is seated rather than moved, which is the same operation with an
    empty source.
    """
    t, _ = require_organizer(code, request)
    cfg = settings_of(t)
    rnd = active_round(t["code"])
    dest = pod_in(t["code"], pod_id)
    require_rearrangeable(dest, rnd)

    entrant = resolve_entrant(t["code"], body.entrantId)
    if not entrant:
        raise HTTPException(404, "no such entrant")
    if entrant["dropped_at"]:
        raise HTTPException(409, f"{entrant['name']} has dropped — undrop them before seating them")

    src = q(
        "SELECT p.*, s.room_token AS seat_token FROM pod_seats s JOIN pods p ON p.id = s.pod_id "
        "WHERE p.round_id = ? AND s.entrant_id = ?",
        (rnd["id"], entrant["id"]),
    ).fetchone()
    if src and src["id"] == dest["id"]:
        # a double-tap, or two organizers doing the same thing; not an error
        return {"ok": True, "moved": False, "from": dest["number"], "to": dest["number"]}
    if src:
        require_rearrangeable(src, rnd)
        left = seat_count(src["id"]) - 1
        if left < MIN_POD_SEATS:
            raise HTTPException(
                409,
                f"that would leave table {src['number']} with {left} — a pod never goes "
                f"below {MIN_POD_SEATS}; move somebody in there first",
            )
    # The pairer's own ceiling: pod_sizes() grows a pod by one to absorb a
    # remainder and never further, so an override that seats a seventh player at
    # a four-player event is doing something the pairer would refuse to do.
    cap = cfg["podSize"] + 1
    if seat_count(dest["id"]) + 1 > cap:
        raise HTTPException(
            409, f"table {dest['number']} already seats {cap} — this event pods {cfg['podSize']}"
        )

    if src:
        q("DELETE FROM pod_seats WHERE pod_id = ? AND entrant_id = ?", (src["id"], entrant["id"]))
        # close the gap they left: seat order is turn order, and a hole in it
        # reads at the table as a player who hasn't arrived yet
        for i, r in enumerate(
            q(
                "SELECT entrant_id FROM pod_seats WHERE pod_id = ? ORDER BY seat", (src["id"],)
            ).fetchall(),
            1,
        ):
            q(
                "UPDATE pod_seats SET seat = ? WHERE pod_id = ? AND entrant_id = ?",
                (i, src["id"], r["entrant_id"]),
            )
        _unseat_from_room(src, src["seat_token"], entrant["name"])

    seat_no = (
        q(
            "SELECT COALESCE(MAX(seat), 0) AS m FROM pod_seats WHERE pod_id = ?", (dest["id"],)
        ).fetchone()["m"]
        + 1
    )
    token = _seat_in_room(dest, entrant["name"])
    q(
        "INSERT INTO pod_seats (pod_id, entrant_id, seat, room_token) VALUES (?, ?, ?, ?)",
        (dest["id"], entrant["id"], seat_no, token),
    )
    touch(t["code"])

    rooms = [p["room_code"] for p in (src, dest) if p and p["room_code"]]
    if src and src["room_code"]:
        # taking a player out can leave one person alone in a live game, which
        # is a finished game — the same call `leave` makes for the same reason
        from . import table as table_mod

        room = q("SELECT * FROM rooms WHERE code = ?", (src["room_code"],)).fetchone()
        if room:
            await table_mod.check_last_standing(room)
    await push_to_pods(room_codes=rooms)
    return {
        "ok": True,
        "moved": True,
        "from": src["number"] if src else None,
        "to": dest["number"],
        "seat": seat_no,
    }


@router.post("/{code}/pods/{pod_id}/seats")
async def set_pod_seat_order(code: str, pod_id: int, body: SeatOrderBody, request: Request):
    """Set turn order at one table.

    Seat 1 takes the first turn, which is a real advantage in multiplayer, so
    this is the arranging half of `seatAssignment: "manual"` — without it that
    mode only ever meant "leave the pairer's order alone".
    """
    t, _ = require_organizer(code, request)
    rnd = active_round(t["code"])
    pod = pod_in(t["code"], pod_id)
    require_rearrangeable(pod, rnd)

    seats = q(
        "SELECT s.entrant_id, s.room_token, e.public_id FROM pod_seats s "
        "JOIN entrants e ON e.id = s.entrant_id WHERE s.pod_id = ? ORDER BY s.seat",
        (pod["id"],),
    ).fetchall()
    by_public = {s["public_id"]: s for s in seats}
    wanted = [str(x) for x in body.entrantIds]
    if sorted(wanted) != sorted(by_public):
        # a partial order would leave duplicate or missing seat numbers, so this
        # takes the whole table or nothing
        raise HTTPException(400, "list every player at this table exactly once")

    for i, pub in enumerate(wanted, 1):
        row = by_public[pub]
        q(
            "UPDATE pod_seats SET seat = ? WHERE pod_id = ? AND entrant_id = ?",
            (i, pod["id"], row["entrant_id"]),
        )
        if row["room_token"]:
            # the room seats the same people; leaving it on the pairer's order
            # would show one table two different turn orders
            q(
                "UPDATE players SET seat_order = ? WHERE room_code = ? AND token = ?",
                (i, pod["room_code"], row["room_token"]),
            )
    touch(t["code"])
    await push_to_pods(room_codes=[pod["room_code"]] if pod["room_code"] else [])
    return {"ok": True, "seats": wanted}


@router.post("/{code}/pods/{pod_id}/name")
async def name_pod(code: str, pod_id: int, body: PodNameBody, request: Request):
    """Name a table.

    Pods are numbered, and a number is the right default, but "Feature" or "Bar
    side" is what actually gets called across a hall. The number stays the pod's
    identity — the name is a label, never something anything looks up by.
    """
    t, _ = require_organizer(code, request)
    pod = pod_in(t["code"], pod_id)
    name = (body.name or "").strip()
    if name:
        clash = q(
            "SELECT number FROM pods WHERE round_id = ? AND id != ? AND label = ? COLLATE NOCASE",
            (pod["round_id"], pod["id"], name),
        ).fetchone()
        if clash:
            # two tables answering to one name in the same round is worse than
            # no name at all — somebody gets sent to the wrong one
            raise HTTPException(409, f"table {clash['number']} in this round is already called that")
    q("UPDATE pods SET label = ? WHERE id = ?", (name or None, pod["id"]))
    touch(t["code"])
    await push_to_pods(room_codes=[pod["room_code"]] if pod["room_code"] else [])
    return {"ok": True, "podId": pod["id"], "table": pod["number"], "name": name or None}


# ---- results ----


def points_for(cfg: dict, place: int, kind: str, pod_size: int) -> int:
    if kind == "draw":
        return cfg["drawPoints"]
    if kind == "bye":
        return cfg["winPoints"] if cfg["byeScoring"] == "win" else cfg["drawPoints"]
    if cfg["scoring"] == "placement":
        table = cfg["placementPoints"]
        return table[place - 1] if 1 <= place <= len(table) else 0
    return cfg["winPoints"] if place == 1 else cfg["lossPoints"]


def _write_result(t, pod, kind: str, places: list[dict], source: str, note: str | None):
    cfg = settings_of(t)
    version = (
        q("SELECT COALESCE(MAX(version), 0) AS v FROM pod_results WHERE pod_id = ?", (pod["id"],))
        .fetchone()["v"]
        + 1
    )
    q(
        "INSERT INTO pod_results (pod_id, version, kind, source, note) VALUES (?, ?, ?, ?, ?)",
        (pod["id"], version, kind, source, note),
    )
    seat_rows = q(
        "SELECT entrant_id FROM pod_seats WHERE pod_id = ? ORDER BY seat", (pod["id"],)
    ).fetchall()
    size = len(seat_rows)

    # A draw or a bye has no ordering to send, so callers reasonably post none —
    # the organizer's "Draw" button did exactly that, and every seat was left
    # with no points at all. Fill it in: everyone shares first.
    if not places and kind in ("draw", "bye"):
        places = [{"entrantId": r["entrant_id"], "place": 1} for r in seat_rows]

    for entry in places:
        place = entry.get("place")
        q(
            "UPDATE pod_seats SET place = ?, points = ? WHERE pod_id = ? AND entrant_id = ?",
            (place, points_for(cfg, place or size, kind, size), pod["id"], entry["entrantId"]),
        )
    q("UPDATE pods SET status = 'complete' WHERE id = ?", (pod["id"],))
    return version


@router.post("/{code}/pods/{pod_id}/result")
def report_result(code: str, pod_id: int, body: ResultBody, request: Request):
    """Organizer override. Auto-detection writes the same rows from the room."""
    t, _ = require_organizer(code, request)
    pod = pod_in(t["code"], pod_id)
    current = q(
        "SELECT COALESCE(MAX(version), 0) AS v FROM pod_results WHERE pod_id = ?", (pod_id,)
    ).fetchone()["v"]
    if body.expectedVersion is not None and body.expectedVersion != current:
        raise HTTPException(409, "someone else recorded a result — reload before overriding")
    # translate the wire's public ids into the internal ones _write_result uses
    places = []
    for entry in body.places:
        row = resolve_entrant(t["code"], entry.get("entrantId"))
        if not row:
            raise HTTPException(400, f"no entrant {entry.get('entrantId')} in this tournament")
        places.append({"entrantId": row["id"], "place": entry.get("place")})
    version = _write_result(t, pod, body.kind, places, "organizer", body.note)
    touch(t["code"])
    return {"ok": True, "version": version}


def record_room_result(room_code: str, game_no: int, order: list[int], kind: str = "placement"):
    """Called from the room when a game ends. `order` is entrant elimination
    order reversed — last standing first. Never overwrites an organizer's ruling.
    """
    pod = q(
        "SELECT p.*, r.tournament_code FROM pods p JOIN trounds r ON r.id = p.round_id "
        "WHERE p.room_code = ? ORDER BY p.id DESC LIMIT 1",
        (room_code,),
    ).fetchone()
    if not pod:
        return
    decided = q(
        "SELECT source FROM pod_results WHERE pod_id = ? ORDER BY version DESC LIMIT 1",
        (pod["id"],),
    ).fetchone()
    if decided and decided["source"] == "organizer":
        return
    t = q("SELECT * FROM tournaments WHERE code = ?", (pod["tournament_code"],)).fetchone()
    if not t:
        return
    places = [{"entrantId": eid, "place": i} for i, eid in enumerate(order, 1)]
    q("UPDATE pods SET game_no = ? WHERE id = ?", (game_no, pod["id"]))
    _write_result(t, pod, kind, places, "auto", None)
    touch(t["code"])


async def push_to_pods(round_id: int | None = None, room_codes=None):
    """Tell the pods' rooms their clock changed.

    The room shows the round timer, but the timer lives on the tournament, so a
    pause or an extension is invisible to players until something pushes it.
    Only organizer actions land here, so this is rare and cheap — far cheaper
    than every phone polling for a number that changes a few times an hour.
    """
    from . import table as table_mod

    codes = list(room_codes or [])
    if round_id is not None:
        codes += [
            r["room_code"]
            for r in q("SELECT room_code FROM pods WHERE round_id = ?", (round_id,)).fetchall()
            if r["room_code"]
        ]
    for code in dict.fromkeys(codes):
        await table_mod.broadcast(code)


def pod_is_elimination(pod) -> bool:
    row = q("SELECT kind FROM trounds WHERE id = ?", (pod["round_id"],)).fetchone()
    return bool(row) and row["kind"] == "elimination"


def resolve_pod_at_time(t, cfg, pod):
    """Decide one unfinished pod when time is called.

    MTR 2.4: a match that goes to time is a draw — life totals do *not* rank it,
    outside single elimination. That is the default. The other policies are
    house rules that leagues genuinely run, so they are opt-in and named
    honestly rather than presented as official.

    Inside the cut the same section says the opposite, and the tournament's
    setting stops applying: a single-elimination match may not end in a draw,
    so the game profile's `elimination_time_policy` decides instead. That is
    not an override of the organizer's choice — `draw_all` simply has no legal
    outcome to produce here. A game that publishes no such rule, and an
    organizer who asked to rule every pod themselves, both land on the same
    honest answer: the pod waits for a person.
    """
    # tournaments settled before the rename still carry `highest_life` in their
    # stored settings; canonicalise on read so a live event keeps resolving
    policy = canonical_policy(cfg["timeCalledPolicy"])
    elimination = pod_is_elimination(pod)
    if elimination and policy != "organizer_decides":
        profile = profile_for(t["game"] if "game" in t.keys() else None)
        policy = canonical_policy(profile.elimination_time_policy) or "organizer_decides"
    if policy == "organizer_decides":
        q("UPDATE pods SET status = 'awaiting_result' WHERE id = ?", (pod["id"],))
        return None

    seats = q(
        "SELECT entrant_id, room_token FROM pod_seats WHERE pod_id = ? ORDER BY seat",
        (pod["id"],),
    ).fetchall()
    if policy == "draw_all" or not pod["room_code"]:
        if elimination:
            # a bracket pod with no live state to read: there is nothing to rank
            # it on and a draw is not available, so it waits for the organizer
            q("UPDATE pods SET status = 'awaiting_result' WHERE id = ?", (pod["id"],))
            return None
        places = [{"entrantId": s["entrant_id"], "place": 1} for s in seats]
        return _write_result(t, pod, "draw", places, "auto", "time called")

    # the remaining policies need live state from the pod's room
    rows = q(
        "SELECT token, life, eliminated, eliminated_at FROM players WHERE room_code = ?",
        (pod["room_code"],),
    ).fetchall()
    by_token = {r["token"]: r for r in rows}

    alive, out = [], []
    for s in seats:
        p = by_token.get(s["room_token"])
        if p and p["eliminated"]:
            out.append((p["eliminated_at"] or 0, s["entrant_id"]))
        else:
            alive.append((p["life"] if p and p["life"] is not None else 0, s["entrant_id"]))

    # everyone eliminated is ranked below survivors, latest death placing higher
    tail = [eid for _, eid in sorted(out, key=lambda x: -x[0])]

    if policy == "highest_resource":
        # which way the resource ranks is the profile's to say, not this
        # function's: MTG life counts down, another game's may count up
        profile = profile_for(t["game"] if "game" in t.keys() else None)
        alive.sort(key=lambda x: profile.resource_rank_key(x[0]))
        ordered = [eid for _, eid in alive]
        places = [{"entrantId": eid, "place": i} for i, eid in enumerate(ordered, 1)]
        # a tie on the resource is a genuine tie, not an arbitrary ordering
        for i in range(1, len(alive)):
            if alive[i][0] == alive[i - 1][0]:
                places[i]["place"] = places[i - 1]["place"]
        start = (places[-1]["place"] + 1) if places else 1
        places += [{"entrantId": eid, "place": start + i} for i, eid in enumerate(tail)]
        if elimination and len(places) > 1 and places[1]["place"] == places[0]["place"]:
            # dead level at the top of a bracket pod. The resource ran out of
            # things to say, and picking between them on seed or seat would be
            # us adjudicating a game we do not adjudicate. A person rules it.
            q("UPDATE pods SET status = 'awaiting_result' WHERE id = ?", (pod["id"],))
            return None
        return _write_result(
            t, pod, "placement", places, "auto", f"time called — ranked on {profile.resource}"
        )

    # draw_survivors: everyone still alive draws; the dead keep their order below
    places = [{"entrantId": eid, "place": 1} for _, eid in alive]
    places += [{"entrantId": eid, "place": 2 + i} for i, eid in enumerate(tail)]
    return _write_result(t, pod, "draw", places, "auto", "time called — survivors drew")


@router.post("/{code}/rounds/time")
async def call_time(code: str, request: Request):
    """Organizer calls time on the round. Every pod without a result is decided
    by the tournament's time-called policy; pods already reported are untouched,
    and an organizer ruling is never overwritten."""
    t, _ = require_organizer(code, request)
    cfg = settings_of(t)
    rnd = q(
        "SELECT * FROM trounds WHERE tournament_code = ? AND status = 'active'", (t["code"],)
    ).fetchone()
    if not rnd:
        raise HTTPException(409, "no round is open")
    pods = q(
        "SELECT * FROM pods WHERE round_id = ? AND status != 'complete'", (rnd["id"],)
    ).fetchall()

    # MTR 2.4: at time the current turn is finished and N additional turns are
    # played — the game is only decided after them. The app can't detect a turn
    # passing, so the pod counts them down itself; players are already doing
    # this by hand at the table.
    extra = cfg["extraTurns"]
    decided, counting = 0, 0
    for pod in pods:
        if extra > 0 and pod["room_code"]:
            q("UPDATE pods SET turns_remaining = ?, status = 'extra_turns' WHERE id = ?",
              (extra, pod["id"]))
            counting += 1
            continue
        # no room to count turns in (or the game doesn't have the procedure):
        # decide immediately rather than stranding the pod
        if resolve_pod_at_time(t, cfg, pod) is not None:
            decided += 1
    q("UPDATE trounds SET ends_at = ? WHERE id = ?", (int(time.time()), rnd["id"]))
    touch(t["code"])
    await push_to_pods(rnd["id"])
    return {"ok": True, "decided": decided, "extraTurns": counting,
            "turns": extra, "policy": canonical_policy(cfg["timeCalledPolicy"])}


class TurnBody(BaseModel):
    delta: int = -1          # -1 counts a turn down; +1 undoes a mis-tap


@router.post("/{code}/pods/{pod_id}/turn")
async def advance_turn(
    code: str, pod_id: int, body: TurnBody, request: Request, token: str | None = None
):
    """Count an additional turn at the table. Any player in the pod may tap it
    — a judge shouldn't have to stand there — and +1 undoes a mis-tap. When the
    count reaches zero the pod is decided by the time-called policy."""
    t = get_tournament(code)
    cfg = settings_of(t)
    pod = pod_in(t["code"], pod_id)

    # Counting a turn ends in a recorded result, so it is a privileged action.
    # Any player *at that table* may do it — a judge shouldn't have to stand
    # there for five turns — but nobody else, and not an anonymous caller who
    # merely knows the tournament code.
    entrant = entrant_from_token(t["code"], token)
    if not (entrant and seat_in_pod(pod["id"], entrant["id"])):
        try:
            require_organizer(code, request)
        except HTTPException:
            raise HTTPException(403, "only a player at this table, or the organizer, may count turns")
    if pod["turns_remaining"] is None:
        raise HTTPException(409, "time has not been called on this pod")
    if pod["status"] == "complete":
        raise HTTPException(409, "this pod already has a result")

    # A tap counts one turn down. Counting *up* is not just undo: MTR 2.6 says
    # certain slow-play penalties add turns rather than time, and those are
    # added to the end-of-match additional turns — so the count must be able to
    # exceed where it started. Bounded only to keep a stuck finger from
    # producing an absurd number.
    step = 1 if body.delta > 0 else -1
    left = min(99, max(0, pod["turns_remaining"] + step))
    q("UPDATE pods SET turns_remaining = ? WHERE id = ?", (left, pod["id"]))
    touch(t["code"])

    if left == 0:
        pod = pod_in(t["code"], pod_id)
        resolve_pod_at_time(t, cfg, pod)
        await push_to_pods(room_codes=[pod["room_code"]] if pod["room_code"] else [])
        return {"ok": True, "turnsRemaining": 0, "decided": True}
    await push_to_pods(room_codes=[pod["room_code"]] if pod["room_code"] else [])
    return {"ok": True, "turnsRemaining": left, "decided": False}


# ---- timer ----


@router.post("/{code}/timer")
async def timer(code: str, body: TimerBody, request: Request):
    t, _ = require_organizer(code, request)
    cfg = settings_of(t)
    rnd = q(
        "SELECT * FROM trounds WHERE tournament_code = ? AND status = 'active'", (t["code"],)
    ).fetchone()
    if not rnd:
        raise HTTPException(409, "no round is open")
    now = int(time.time())
    if body.action == "start":
        mins = body.minutes or cfg["roundMinutes"]
        q(
            "UPDATE trounds SET started_at = ?, ends_at = ?, paused_at = NULL WHERE id = ?",
            (now, now + mins * 60, rnd["id"]),
        )
    elif body.action == "pause":
        q("UPDATE trounds SET paused_at = ? WHERE id = ?", (now, rnd["id"]))
    elif body.action == "resume":
        if rnd["paused_at"]:
            q(
                "UPDATE trounds SET ends_at = ends_at + (? - paused_at), paused_at = NULL WHERE id = ?",
                (now, rnd["id"]),
            )
    elif body.action == "extend":
        mins = body.minutes or 5
        if body.podId:  # a judge extends one table, not the whole round
            target = pod_in(t["code"], body.podId)
            q(
                "UPDATE pods SET extension_seconds = extension_seconds + ? WHERE id = ?",
                (mins * 60, target["id"]),
            )
        else:
            q("UPDATE trounds SET ends_at = ends_at + ? WHERE id = ?", (mins * 60, rnd["id"]))
    else:
        raise HTTPException(400, "unknown timer action")
    touch(t["code"])
    await push_to_pods(rnd["id"])
    return {"ok": True}


# ---- official calls ----


@router.post("/{code}/pods/{pod_id}/call")
def call_official(code: str, pod_id: int, body: CallBody, token: str | None = None):
    t = get_tournament(code)
    if not settings_of(t)["allowOfficialCalls"]:
        raise HTTPException(409, "official calls are disabled for this tournament")
    pod = pod_in(t["code"], pod_id)
    entrant = entrant_from_token(t["code"], token)
    # A call can earn that table a time extension, so it can't be raised by a
    # stranger with the tournament code, nor against someone else's table.
    if not (entrant and seat_in_pod(pod["id"], entrant["id"])):
        raise HTTPException(403, "only a player at this table may call an official")
    existing = q(
        "SELECT id FROM official_calls WHERE pod_id = ? AND status != 'resolved'", (pod_id,)
    ).fetchone()
    if existing:
        return {"ok": True, "callId": existing["id"], "alreadyOpen": True}
    cur = q(
        "INSERT INTO official_calls (tournament_code, pod_id, entrant_id, category, note) "
        "VALUES (?, ?, ?, ?, ?)",
        (t["code"], pod_id, entrant["id"] if entrant else None, body.category, body.note),
    )
    touch(t["code"])
    return {"ok": True, "callId": cur.lastrowid}


@router.post("/{code}/calls/{call_id}/ack")
def ack_call(code: str, call_id: int, request: Request):
    t, _ = require_organizer(code, request)
    q(
        "UPDATE official_calls SET status = 'acknowledged', acknowledged_at = unixepoch() "
        "WHERE id = ? AND tournament_code = ? AND status = 'open'",
        (call_id, t["code"]),
    )
    return {"ok": True}


def suggested_extension(open_seconds: int) -> int:
    """Minutes MTR 2.6 suggests for a pause of this length.

    "If a judge pauses a match for more than one minute while the round clock is
    running, they should extend the match time appropriately." Under a minute,
    nothing. Over it, round up to the minute. This is a *suggestion* the judge
    accepts or overrides — "appropriately" is their call, not ours, and a deck
    check has its own formula (duration plus three minutes) that only they know
    applies.
    """
    if open_seconds <= 60:
        return 0
    return -(-open_seconds // 60)   # ceiling division


@router.post("/{code}/calls/{call_id}/resolve")
async def resolve_call(code: str, call_id: int, body: CallBody, request: Request):
    t, _ = require_organizer(code, request)
    cfg = settings_of(t)
    call = q(
        "SELECT * FROM official_calls WHERE id = ? AND tournament_code = ?",
        (call_id, t["code"]),
    ).fetchone()
    if not call:
        return {"ok": True}   # already gone; a double-tap is not an error

    q(
        "UPDATE official_calls SET status = 'resolved', resolved_at = unixepoch(), resolution = ? "
        "WHERE id = ? AND tournament_code = ?",
        (body.note, call_id, t["code"]),
    )

    # The disruption is the whole time the table sat waiting — from the hand
    # going up to the ruling being done, not just the judge's time at the table.
    open_for = max(0, int(time.time()) - call["created_at"])
    suggested = suggested_extension(open_for)

    if body.extendMinutes is not None:
        granted = max(0, body.extendMinutes)      # the judge decided, including 0
        source = "judge"
    elif cfg["autoExtendOnCall"]:
        granted = suggested                        # measured, and given back
        source = "measured"
    else:
        granted = 0
        source = "off"

    if granted and call["pod_id"]:
        q(
            "UPDATE pods SET extension_seconds = extension_seconds + ? WHERE id = ?",
            (granted * 60, call["pod_id"]),
        )
        room = q("SELECT room_code FROM pods WHERE id = ?", (call["pod_id"],)).fetchone()
        if room and room["room_code"]:
            await push_to_pods(room_codes=[room["room_code"]])
    touch(t["code"])
    return {
        "ok": True,
        "openSeconds": open_for,
        "suggestedMinutes": suggested,
        "grantedMinutes": granted,
        "grantedBy": source,
    }
