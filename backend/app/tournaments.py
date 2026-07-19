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
from .db import q
from .pairing import Entrant as PairEntrant
from .pairing import pair_round, seat_pods

router = APIRouter()

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
IDLE_TIMEOUT = 12 * 60 * 60  # a tournament day, not a room's 3h

DEFAULT_SETTINGS = {
    "scoring": "win_draw_loss",      # win_draw_loss | placement
    "winPoints": 3,
    "drawPoints": 1,
    "lossPoints": 0,
    "placementPoints": [4, 3, 2, 1],
    "byeScoring": "win",
    "podSize": 4,
    "seatAssignment": "random",       # random | by_standings | manual
    "roundMinutes": 60,
    "timeCalledPolicy": "draw_all",   # draw_all | draw_survivors | highest_life | organizer_decides
    "startingLife": 40,
    "allowOfficialCalls": True,
    "collectWizardsEmail": "off",     # off | optional | required
}


# ---- helpers ----


def settings_of(row) -> dict:
    return {**DEFAULT_SETTINGS, **json.loads(row["settings"] or "{}")}


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

    points: dict[int, int] = {e["id"]: 0 for e in entrants}
    played: dict[int, int] = {e["id"]: 0 for e in entrants}
    pod_members: dict[int, list[int]] = {}
    for s in seats:
        pod_members.setdefault(s["pod_id"], []).append(s["entrant_id"])
        if s["points"] is not None:
            points[s["entrant_id"]] = points.get(s["entrant_id"], 0) + s["points"]
            played[s["entrant_id"]] = played.get(s["entrant_id"], 0) + 1

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
                "entrantId": e["id"],
                "name": e["name"],
                "points": points.get(e["id"], 0),
                "opponentPoints": opp,
                "podsPlayed": played.get(e["id"], 0),
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
                f"SELECT s.*, e.name FROM pod_seats s JOIN entrants e ON e.id = s.entrant_id "
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
            "roomCode": p["room_code"],
            "extensionSeconds": p["extension_seconds"],
            "seats": [
                {"seat": s["seat"], "entrantId": s["entrant_id"], "name": s["name"],
                 "place": s["place"], "points": s["points"]}
                for s in members
            ],
        }
        pod_views.append(view)
        mine = next((s for s in members if s["entrant_id"] == viewer_entrant["id"]), None) if viewer_entrant else None
        if mine:
            # the room token is the viewer's own seat only — it never reaches
            # the pod list everyone else sees
            my_pod = {**view, "roomToken": mine["room_token"], "mySeat": mine["seat"]}

    calls = []
    if organizer:
        calls = [
            {"id": c["id"], "podId": c["pod_id"], "status": c["status"],
             "category": c["category"], "note": c["note"], "createdAt": c["created_at"]}
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
            {"entrantId": viewer_entrant["id"], "name": viewer_entrant["name"]}
            if viewer_entrant
            else None
        ),
        "standings": standings_rows(t["code"]),
        "calls": calls,
        "isOrganizer": organizer,
    }


# ---- request bodies ----


class CreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    mode: str = Field(default="life")
    settings: dict = Field(default_factory=dict)


class EntrantsBody(BaseModel):
    names: list[str] = Field(default_factory=list)


class ClaimBody(BaseModel):
    entrantId: int


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


# ---- lifecycle ----


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
    if body.mode not in ("life", "treachery"):
        raise HTTPException(400, "unknown mode")
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
    cfg = {k: v for k, v in body.settings.items() if k in DEFAULT_SETTINGS}
    q(
        "INSERT INTO tournaments (code, name, organizer_account_id, mode, settings, last_active) "
        "VALUES (?, ?, ?, ?, ?, unixepoch())",
        (code, body.name.strip(), acct["id"], body.mode, json.dumps(cfg)),
    )
    return {"code": code}


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
    added = []
    for name in body.names:
        name = name.strip()
        if not name:
            continue
        cur = q(
            "INSERT INTO entrants (tournament_code, name) VALUES (?, ?)", (t["code"], name)
        )
        added.append({"entrantId": cur.lastrowid, "name": name})
    touch(t["code"])
    return {"added": added}


@router.get("/{code}/roster")
def roster(code: str):
    """Public by design: a player scans the code and picks their name."""
    t = get_tournament(code)
    rows = q(
        "SELECT id, name, token IS NOT NULL AS claimed, dropped_at FROM entrants "
        "WHERE tournament_code = ? ORDER BY name COLLATE NOCASE",
        (t["code"],),
    ).fetchall()
    return {
        "name": t["name"],
        "status": t["status"],
        "entrants": [
            {"entrantId": r["id"], "name": r["name"], "claimed": bool(r["claimed"]),
             "dropped": r["dropped_at"] is not None}
            for r in rows
        ],
    }


@router.post("/{code}/claim")
def claim(code: str, body: ClaimBody):
    """Claim a seat by id — names may repeat, ids don't. First claim wins; the
    organizer can release one if somebody taps the wrong name."""
    t = get_tournament(code)
    row = q(
        "SELECT * FROM entrants WHERE id = ? AND tournament_code = ?",
        (body.entrantId, t["code"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, "not on this roster")
    if row["token"]:
        raise HTTPException(409, "that name is already claimed — ask the organizer to release it")
    token = secrets.token_urlsafe(24)
    q("UPDATE entrants SET token = ? WHERE id = ?", (token, row["id"]))
    touch(t["code"])
    return {"entrantToken": token, "entrantId": row["id"], "name": row["name"]}


@router.post("/{code}/entrants/{entrant_id}/release")
def release_claim(code: str, entrant_id: int, request: Request):
    t, _ = require_organizer(code, request)
    q(
        "UPDATE entrants SET token = NULL WHERE id = ? AND tournament_code = ?",
        (entrant_id, t["code"]),
    )
    return {"ok": True}


@router.post("/{code}/entrants/{entrant_id}/drop")
def drop_entrant(code: str, entrant_id: int, request: Request):
    t, _ = require_organizer(code, request)
    q(
        "UPDATE entrants SET dropped_at = unixepoch() WHERE id = ? AND tournament_code = ?",
        (entrant_id, t["code"]),
    )
    return {"ok": True}


# ---- rounds ----


def _make_room_for_pod(t, cfg, pod_id: int, seats: list[tuple[int, str]]) -> str:
    """Back a pod with an ordinary room so the whole table app just works."""
    from . import table as table_mod

    room_code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
    q(
        "INSERT INTO rooms (code, mode, starting_life, status, last_active) "
        "VALUES (?, ?, ?, 'lobby', unixepoch())",
        (room_code, t["mode"], cfg["startingLife"]),
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
    size = q("SELECT COUNT(*) c FROM pod_seats WHERE pod_id = ?", (pod["id"],)).fetchone()["c"]
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
    pod = q("SELECT * FROM pods WHERE id = ?", (pod_id,)).fetchone()
    if not pod:
        raise HTTPException(404, "pod not found")
    current = q(
        "SELECT COALESCE(MAX(version), 0) AS v FROM pod_results WHERE pod_id = ?", (pod_id,)
    ).fetchone()["v"]
    if body.expectedVersion is not None and body.expectedVersion != current:
        raise HTTPException(409, "someone else recorded a result — reload before overriding")
    version = _write_result(t, pod, body.kind, body.places, "organizer", body.note)
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


# ---- timer ----


@router.post("/{code}/timer")
def timer(code: str, body: TimerBody, request: Request):
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
            q(
                "UPDATE pods SET extension_seconds = extension_seconds + ? WHERE id = ?",
                (mins * 60, body.podId),
            )
        else:
            q("UPDATE trounds SET ends_at = ends_at + ? WHERE id = ?", (mins * 60, rnd["id"]))
    else:
        raise HTTPException(400, "unknown timer action")
    touch(t["code"])
    return {"ok": True}


# ---- official calls ----


@router.post("/{code}/pods/{pod_id}/call")
def call_official(code: str, pod_id: int, body: CallBody, token: str | None = None):
    t = get_tournament(code)
    if not settings_of(t)["allowOfficialCalls"]:
        raise HTTPException(409, "official calls are disabled for this tournament")
    entrant = entrant_from_token(t["code"], token)
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


@router.post("/{code}/calls/{call_id}/resolve")
def resolve_call(code: str, call_id: int, body: CallBody, request: Request):
    t, _ = require_organizer(code, request)
    q(
        "UPDATE official_calls SET status = 'resolved', resolved_at = unixepoch(), resolution = ? "
        "WHERE id = ? AND tournament_code = ?",
        (body.note, call_id, t["code"]),
    )
    return {"ok": True}
