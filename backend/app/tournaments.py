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

import json
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .accounts import require_account
from .audit import AUTHZ_DENY, security_event
from .db import q
from .games import known_games, profile_for, structure_for
from .pairing import Entrant as PairEntrant
from .pairing import pair_round, seat_pods

router = APIRouter()

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
IDLE_TIMEOUT = 12 * 60 * 60  # a tournament day, not a room's 3h

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
    "collectWizardsEmail": "off",     # off | optional | required (publisher account)
    # measure the disruption a judge call caused and give that table the time
    # back automatically. The judge can still override or decline per call.
    "autoExtendOnCall": True,
    "structure": None,                # a game profile's structure key; None = first
}


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


def touch(code: str):
    q("UPDATE tournaments SET last_active = unixepoch() WHERE code = ?", (code,))


def get_tournament(code: str):
    row = q("SELECT * FROM tournaments WHERE code = ?", (code.upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "tournament not found")
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


def tournament_state(code: str, viewer_entrant=None, organizer: bool = False):
    """One snapshot for every client. Single query set, personalized in memory."""
    t = get_tournament(code)
    cfg = settings_of(t)
    rounds = q(
        "SELECT * FROM trounds WHERE tournament_code = ? ORDER BY number", (t["code"],)
    ).fetchall()
    latest = rounds[-1] if rounds else None
    pods, seats = [], []
    if latest:
        pods = q("SELECT * FROM pods WHERE round_id = ? ORDER BY number", (latest["id"],)).fetchall()
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
    for p in pods:
        members = by_pod.get(p["id"], [])
        view = {
            "podId": p["id"],
            "table": p["number"],
            "status": p["status"],
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
        "standings": [
            {**{k: v for k, v in row.items() if k != "publicId"},
             "entrantId": row["publicId"]}
            for row in standings_rows(t["code"])
        ],
        "calls": calls,
        "isOrganizer": organizer,
    }


# ---- request bodies ----


class CreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    game: str = Field(default="mtg")
    mode: str = Field(default="life")
    settings: dict = Field(default_factory=dict)


class EntrantsBody(BaseModel):
    names: list[str] = Field(default_factory=list)
    # imports send [{name, externalRef}] instead; externalRef is "source:id"
    entrants: list[dict] = Field(default_factory=list)


class ClaimBody(BaseModel):
    entrantId: str
    wizardsEmail: str | None = None


class RoundBody(BaseModel):
    reroll: bool = False


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
    known = {g["key"] for g in known_games()}
    if body.game not in known:
        raise HTTPException(400, f"unknown game — this server runs {', '.join(sorted(known))}")
    profile = profile_for(body.game)
    if profile.modes and body.mode not in profile.modes:
        raise HTTPException(400, f"{profile.name} has no '{body.mode}' mode")

    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
    allowed = defaults_for(body.game)
    cfg = {k: v for k, v in body.settings.items() if k in allowed}
    if "timeCalledPolicy" in cfg and cfg["timeCalledPolicy"] not in profile.time_called_policies:
        raise HTTPException(400, f"{profile.name} does not offer that time-called policy")
    q(
        "INSERT INTO tournaments (code, name, organizer_account_id, game, mode, settings, last_active) "
        "VALUES (?, ?, ?, ?, ?, ?, unixepoch())",
        (code, body.name.strip(), acct["id"], body.game, body.mode, json.dumps(cfg)),
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


@router.get("/{code}")
def get_state(code: str, request: Request, token: str | None = None):
    t = get_tournament(code)
    acct = None
    try:
        from .accounts import current_account

        acct = current_account(request)
    except Exception:
        acct = None
    organizer = bool(acct and acct["id"] == t["organizer_account_id"])
    return tournament_state(t["code"], entrant_from_token(t["code"], token), organizer)


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
    return {
        "name": t["name"],
        "status": t["status"],
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
    # has to report to Wizards. Never collected by default, never shown to other
    # players, and never used for anything else.
    cfg = settings_of(t)
    wiz = (body.wizardsEmail or "").strip() or None
    if cfg["collectWizardsEmail"] == "off":
        wiz = None
    elif cfg["collectWizardsEmail"] == "required" and not wiz:
        raise HTTPException(
            422, "this event reports to Wizards, so it needs the email on your Wizards account"
        )

    token = secrets.token_urlsafe(24)
    q(
        "UPDATE entrants SET token = ?, wizards_email = COALESCE(?, wizards_email) WHERE id = ?",
        (token, wiz, row["id"]),
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
    return {"ok": True, "standings": standings_rows(t["code"])}


@router.delete("/{code}")
def delete_tournament(code: str, request: Request):
    """Remove an event and everything under it.

    Organizers accumulate abandoned events — a test run, a night that never
    happened — and until now the only way to tidy them was to leave them in the
    list forever. Deleting is the organizer's own data and nobody else's: the
    row cascades to entrants, rounds, pods, results and calls.

    An active round blocks it, exactly as ending does. People are sitting at
    tables during a round, and pulling the event out from under them is not
    something a stray tap should be able to do.

    Pod rooms are closed rather than deleted. They hold their own players and
    game log, they expire on the normal idle sweep, and a room outliving its
    event by an hour is a much smaller problem than a delete that has to reason
    about who is still seated in one.
    """
    t, _ = require_organizer(code, request)
    open_round = q(
        "SELECT id FROM trounds WHERE tournament_code = ? AND status = 'active'", (t["code"],)
    ).fetchone()
    if open_round:
        raise HTTPException(409, "close the current round before deleting the tournament")
    q(
        "UPDATE rooms SET status = 'closed' WHERE code IN ("
        "  SELECT p.room_code FROM pods p JOIN trounds r ON p.round_id = r.id"
        "  WHERE r.tournament_code = ? AND p.room_code IS NOT NULL"
        ")",
        (t["code"],),
    )
    q("DELETE FROM tournaments WHERE code = ?", (t["code"],))
    return {"ok": True}


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


@router.post("/{code}/rounds")
def open_round(code: str, body: RoundBody, request: Request):
    """Pair, seat, and create a room per pod. Pairing is computed and persisted
    before anything is announced, so the round opening is a broadcast of settled
    state rather than work done under load."""
    t, _ = require_organizer(code, request)
    cfg = settings_of(t)
    if t["status"] == "ended":
        raise HTTPException(409, "this tournament has ended")

    active = q(
        "SELECT * FROM trounds WHERE tournament_code = ? AND status = 'active'", (t["code"],)
    ).fetchone()
    if active and not body.reroll:
        raise HTTPException(409, "close the current round first")

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

    for i, pod in enumerate(pods, 1):
        cur = q("INSERT INTO pods (round_id, number, status) VALUES (?, ?, 'active')", (round_id, i))
        pod_id = cur.lastrowid
        for seat_no, entrant_id in enumerate(pod.seats, 1):
            q(
                "INSERT INTO pod_seats (pod_id, entrant_id, seat) VALUES (?, ?, ?)",
                (pod_id, entrant_id, seat_no),
            )
        room = _make_room_for_pod(t, cfg, pod_id, [(eid, names[eid]) for eid in pod.seats])
        q("UPDATE pods SET room_code = ?, game_no = 0 WHERE id = ?", (room, pod_id))

    q("UPDATE tournaments SET status = 'running' WHERE code = ?", (t["code"],))
    touch(t["code"])
    return {"round": number, "pods": len(pods)}


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


def resolve_pod_at_time(t, cfg, pod):
    """Decide one unfinished pod when time is called.

    MTR 2.4: a match that goes to time is a draw — life totals do *not* rank it,
    outside single elimination. That is the default. The other policies are
    house rules that leagues genuinely run, so they are opt-in and named
    honestly rather than presented as official.
    """
    policy = cfg["timeCalledPolicy"]
    if policy == "organizer_decides":
        q("UPDATE pods SET status = 'awaiting_result' WHERE id = ?", (pod["id"],))
        return None

    seats = q(
        "SELECT entrant_id, room_token FROM pod_seats WHERE pod_id = ? ORDER BY seat",
        (pod["id"],),
    ).fetchall()
    if policy == "draw_all" or not pod["room_code"]:
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

    if policy == "highest_life":
        alive.sort(key=lambda x: -x[0])
        ordered = [eid for _, eid in alive]
        places = [{"entrantId": eid, "place": i} for i, eid in enumerate(ordered, 1)]
        # a tie on life is a genuine tie, not an arbitrary ordering
        for i in range(1, len(alive)):
            if alive[i][0] == alive[i - 1][0]:
                places[i]["place"] = places[i - 1]["place"]
        start = (places[-1]["place"] + 1) if places else 1
        places += [{"entrantId": eid, "place": start + i} for i, eid in enumerate(tail)]
        return _write_result(t, pod, "placement", places, "auto", "time called — ranked on life")

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
            "turns": extra, "policy": cfg["timeCalledPolicy"]}


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
