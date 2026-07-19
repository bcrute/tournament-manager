import asyncio
import json
import os
import random
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .db import q

router = APIRouter()

_here = Path(__file__).resolve()
CARDS_PATH = next(
    p for p in (_here.parents[1] / "data", _here.parents[2] / "data")
    if (p / "treachery-cards.json").exists()
) / "treachery-cards.json"

RARITIES = ["U", "R", "M", "S"]
MODES = ["life", "treachery"]
IDLE_TIMEOUT = int(os.environ.get("TABLE_IDLE_TIMEOUT", 3 * 60 * 60))  # 3h of no activity
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L

_cards_by_id = {}
_cards_by_role = {"Leader": [], "Guardian": [], "Assassin": [], "Traitor": []}
for _c in json.loads(CARDS_PATH.read_text())["cards"]:
    _cards_by_id[_c["id"]] = _c
    _cards_by_role[_c["types"]["subtype"]].append(_c)


async def check_last_standing(room):
    """One player left in a live game means it's over — end it so every client
    can show the result and return to the room together."""
    if norm_status(room["status"]) != "playing":
        return
    alive = q(
        "SELECT name FROM players WHERE room_code = ? AND is_display = 0 "
        "AND left_game = 0 AND eliminated = 0",
        (room["code"],),
    ).fetchall()
    if len(alive) > 1:
        return
    q("UPDATE rooms SET status = 'ended' WHERE code = ?", (room["code"],))
    if len(alive) == 1:
        log_event(room["code"], f"{alive[0]['name']} is the last player standing — game over")
    else:
        log_event(room["code"], "no players left — game over")
    if room["mode"] == "treachery":
        for p in q(
            "SELECT * FROM players WHERE room_code = ? AND is_display = 0 ORDER BY joined_at, id",
            (room["code"],),
        ).fetchall():
            if p["card_id"]:
                q("UPDATE players SET revealed = 1 WHERE id = ?", (p["id"],))
                card = _cards_by_id[p["card_id"]]
                log_event(
                    room["code"],
                    f"final identity: {p['name']} — {card['name']} ({card['types']['subtype']})",
                )
    report_tournament_result(room)


def report_tournament_result(room):
    """If this room backs a tournament pod, record the result automatically.

    Placement comes from elimination order: last standing is 1st, and the rest
    place in reverse order of when they went out. An organizer's ruling always
    wins — this never overwrites one.
    """
    seats = q(
        "SELECT s.entrant_id, s.room_token FROM pod_seats s JOIN pods p ON p.id = s.pod_id "
        "WHERE p.room_code = ?",
        (room["code"],),
    ).fetchall()
    if not seats:
        return  # an ordinary room, nothing to report
    by_token = {s["room_token"]: s["entrant_id"] for s in seats if s["room_token"]}
    players = q(
        "SELECT token, eliminated, left_game, eliminated_at FROM players "
        "WHERE room_code = ? AND is_display = 0",
        (room["code"],),
    ).fetchall()
    alive, out = [], []
    for p in players:
        eid = by_token.get(p["token"])
        if eid is None:
            continue
        if p["eliminated"] or p["left_game"]:
            out.append((p["eliminated_at"] or 0, eid))
        else:
            alive.append(eid)
    # survivors first, then the eliminated in reverse order of going out
    order = alive + [eid for _, eid in sorted(out, key=lambda x: -x[0])]
    if not order:
        return
    from .tournaments import record_room_result

    record_room_result(room["code"], room["game_no"], order)


def log_event(code: str, text: str):
    """Events double as the permanent game history: stamped with the room's game
    number, never deleted, and carrying no identifiers beyond player names/ids."""
    row = q("SELECT game_no FROM rooms WHERE code = ?", (code,)).fetchone()
    q(
        "INSERT INTO events (room_code, text, game_no) VALUES (?, ?, ?)",
        (code, text, row["game_no"] if row else 0),
    )


def distribution(n: int):
    """Role counts (leader, traitor, assassin, guardian) per Treachery CR 907.3c."""
    table = {
        4: (1, 1, 2, 0),
        5: (1, 1, 2, 1),
        6: (1, 1, 3, 1),
        7: (1, 1, 3, 2),
        8: (1, 2, 3, 2),
    }
    if n in table:
        return table[n]
    if n <= 1:
        return (1, 0, 0, 0)
    if n == 2:
        return (1, 0, 1, 0)
    if n == 3:
        return (1, 1, 1, 0)
    a = n // 2
    t = 2
    return (1, t, a, n - 1 - t - a)


def card_public(card):
    return {
        "id": card["id"],
        "name": card["name"],
        "role": card["types"]["subtype"],
        "rarity": card["rarity"],
        "text": card["text"],
        "uri": card["uri"],
        "artist": card.get("artist") or "",  # the illustrators own this art — credit it
        "rulings": card.get("rulings") or [],
        "image": f"/cards/trd/{card['id']:03d}.jpg",
    }


def expire_idle_rooms():
    """Close rooms nobody has touched in IDLE_TIMEOUT. History is kept — only the
    room stops accepting play, so an abandoned code can't be rejoined forever."""
    q(
        "UPDATE rooms SET status = 'closed' WHERE status != 'closed' "
        "AND COALESCE(last_active, created_at) < unixepoch() - ?",
        (IDLE_TIMEOUT,),
    )


def touch(code: str):
    q("UPDATE rooms SET last_active = unixepoch() WHERE code = ?", (code,))


def _is_tournament_room(code: str) -> bool:
    return bool(q("SELECT 1 FROM pods WHERE room_code = ? LIMIT 1", (code,)).fetchone())


def get_room(code: str, allow_closed: bool = False):
    row = q("SELECT * FROM rooms WHERE code = ?", (code.upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "room not found")
    # check just this room's idle clock (primary-key read); the bulk sweep runs on create
    if row["status"] != "closed" and not _is_tournament_room(row["code"]):
        cutoff = q("SELECT unixepoch() - ? AS c", (IDLE_TIMEOUT,)).fetchone()["c"]
        if (row["last_active"] or row["created_at"]) < cutoff:
            q("UPDATE rooms SET status = 'closed' WHERE code = ?", (row["code"],))
            row = q("SELECT * FROM rooms WHERE code = ?", (row["code"],)).fetchone()
    if row["status"] == "closed" and not allow_closed:
        raise HTTPException(410, "this room has closed")
    return row


def get_player(code: str, token: str | None):
    if not token:
        raise HTTPException(401, "missing player token")
    row = q(
        "SELECT * FROM players WHERE room_code = ? AND token = ?",
        (code.upper(), token),
    ).fetchone()
    if not row:
        raise HTTPException(403, "not a player in this room")
    return row


def account_id_of(request) -> int | None:
    """Signed-in account for this request, if any. Accounts are optional, so a
    missing or invalid session is simply anonymous play. Imported lazily to keep
    the room module free of an accounts dependency at import time."""
    from .accounts import current_account

    acct = current_account(request)
    return acct["id"] if acct else None


def norm_status(raw: str) -> str:
    return "playing" if raw in ("dealt", "playing") else raw


def active_players(code: str):
    """Seated (non-display, still-in) players."""
    return q(
        "SELECT * FROM players WHERE room_code = ? AND left_game = 0 AND is_display = 0 ORDER BY joined_at, id",
        (code,),
    ).fetchall()


def cmd_matrix(code: str):
    """defender_id -> {attacker_pid(str): amount} — pid-keyed so duplicate names can't collide."""
    out: dict[int, dict[str, int]] = {}
    for r in q("SELECT * FROM cmd_damage WHERE room_code = ?", (code,)).fetchall():
        if r["amount"] > 0:
            out.setdefault(r["defender_id"], {})[str(r["attacker_id"])] = r["amount"]
    return out


def tournament_context(room_code: str):
    """Round clock and extra-turn count for a room that backs a tournament pod.

    Players routed into a pod otherwise have no idea how long is left — the
    timer lives on the tournament, and the room is what they're actually
    looking at. One query, and None for an ordinary room.
    """
    row = q(
        "SELECT p.id AS pod_id, p.number AS table_no, p.turns_remaining, p.extension_seconds, "
        "r.number AS round_no, r.status AS round_status, r.ends_at, r.paused_at, "
        "t.code AS tournament_code, t.name AS tournament_name "
        "FROM pods p JOIN trounds r ON r.id = p.round_id "
        "JOIN tournaments t ON t.code = r.tournament_code "
        "WHERE p.room_code = ? ORDER BY p.id DESC LIMIT 1",
        (room_code,),
    ).fetchone()
    if not row:
        return None
    ends_at = row["ends_at"]
    if ends_at is not None and row["extension_seconds"]:
        ends_at += row["extension_seconds"]   # a judge extended this table only
    return {
        "code": row["tournament_code"],
        "name": row["tournament_name"],
        "podId": row["pod_id"],
        "table": row["table_no"],
        "round": row["round_no"],
        "roundStatus": row["round_status"],
        "endsAt": ends_at,
        "pausedAt": row["paused_at"],
        "turnsRemaining": row["turns_remaining"],
        "now": int(time.time()),   # clients derive an offset; never trust local clocks
    }


def room_snapshot(code: str):
    """Everything a room's state depends on, fetched once. Personalizing it per
    client is then pure CPU with no further queries — which is what makes
    pushing state over the WebSocket cheaper than N clients each refetching."""
    room = get_room(code)
    # seats keep the order the table arranged them in; unplaced players sit at the end
    players = q(
        "SELECT * FROM players WHERE room_code = ? "
        "ORDER BY is_display, COALESCE(seat_order, 1000000), joined_at, id",
        (room["code"],),
    ).fetchall()
    events = q(
        "SELECT at, text FROM events WHERE room_code = ? ORDER BY id DESC LIMIT 60",
        (room["code"],),
    ).fetchall()
    return {
        "room": room,
        "players": players,
        "cmd": cmd_matrix(room["code"]),
        "events": events,
        "tournament": tournament_context(room["code"]),
        "by_token": {p["token"]: p for p in players},
    }


def room_state(code: str, token: str | None):
    snap = room_snapshot(code)
    if not token:
        raise HTTPException(401, "missing player token")
    me = snap["by_token"].get(token)
    if me is None:
        raise HTTPException(403, "not a player in this room")
    return personalize(snap, me)


def personalize(snap, me):
    """Build one client's view of a snapshot. No database access."""
    room = snap["room"]
    players = snap["players"]
    status = norm_status(room["status"])
    treachery = room["mode"] == "treachery"
    ended = status == "ended"
    n_active = len([p for p in players if not p["left_game"] and not p["is_display"]])
    ldr, trt, ass, gdn = distribution(n_active) if treachery else (0, 0, 0, 0)
    cmd = snap["cmd"]
    out_players = []
    for p in players:
        if p["is_display"]:
            continue
        visible = treachery and (ended or p["revealed"] or p["left_game"])
        out_players.append(
            {
                "pid": p["id"],
                "name": p["name"],
                "isHost": bool(p["is_host"]),
                "revealed": bool(p["revealed"]),
                "left": bool(p["left_game"]),
                "eliminated": bool(p["eliminated"]),
                "isMe": p["id"] == me["id"],
                "life": p["life"],
                "cmdDamage": cmd.get(p["id"], {}),
                "card": card_public(_cards_by_id[p["card_id"]])
                if visible and p["card_id"]
                else None,
            }
        )
    first_pid = room["first_pid"]
    first_name = next((p["name"] for p in players if p["id"] == first_pid), None)
    return {
        "log": [{"at": e["at"], "text": e["text"]} for e in snap["events"]],
        # None for an ordinary room; the round clock for a tournament pod
        "tournament": snap.get("tournament"),
        "room": {
            "code": room["code"],
            "status": status,
            "mode": room["mode"],
            "startingLife": room["starting_life"],
            "gameNo": room["game_no"],
            "firstPid": first_pid,
            "firstPlayer": first_name,
            "options": json.loads(room["options"]),
            "displays": len([p for p in players if p["is_display"] and not p["left_game"]]),
            "distribution": {"Leader": ldr, "Traitor": trt, "Assassin": ass, "Guardian": gdn},
        },
        "players": out_players,
        "me": {
            "pid": me["id"],
            "name": me["name"],
            "isHost": bool(me["is_host"]),
            "isDisplay": bool(me["is_display"]),
            "revealed": bool(me["revealed"]),
            "eliminated": bool(me["eliminated"]),
            "life": me["life"],
            "cmdDamage": cmd.get(me["id"], {}),
            "card": card_public(_cards_by_id[me["card_id"]]) if me["card_id"] else None,
        },
    }


# ---- websocket fanout ----

# socket -> player token (None until the client authenticates). Tokens arrive in
# a message rather than the URL so they never reach access logs.
_ws_rooms: dict[str, dict] = {}
_ws_lock = asyncio.Lock()


async def broadcast(code: str):
    """Push the new state to every client, personalized, from a single snapshot.
    Clients that haven't sent a token (older bundles) get a nudge to refetch."""
    code = code.upper()
    async with _ws_lock:
        sockets = list(_ws_rooms.get(code, {}).items())
    if not sockets:
        return
    try:
        snap = room_snapshot(code)
    except HTTPException:
        snap = None
    for ws, token in sockets:
        try:
            me = snap["by_token"].get(token) if (snap and token) else None
            if me is not None:
                await ws.send_json({"type": "state", "state": personalize(snap, me)})
            else:
                # unauthenticated socket, or a token that no longer holds a seat
                await ws.send_json({"type": "update"})
        except Exception:
            pass


@router.websocket("/ws/{code}")
async def ws_room(ws: WebSocket, code: str):
    code = code.upper()
    # HTTP middleware doesn't see websockets, so limit connections here
    from .limits import client_id, client_ip  # imported late to avoid a cycle

    limiter = getattr(ws.app.state, "limiter", None)
    if limiter is not None:
        allowed, _ = limiter.check(client_id(client_ip(ws)), "socket")
        if not allowed:
            await ws.close(code=1013)  # try again later
            return
    await ws.accept()
    async with _ws_lock:
        _ws_rooms.setdefault(code, {})[ws] = None
    try:
        while True:
            raw = await ws.receive_text()
            # {"token": "..."} authenticates this socket for pushed state;
            # anything else (keepalive pings) is ignored
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            token = msg.get("token") if isinstance(msg, dict) else None
            if not token:
                continue
            async with _ws_lock:
                if ws in _ws_rooms.get(code, {}):
                    _ws_rooms[code][ws] = token
            try:
                await ws.send_json({"type": "state", "state": room_state(code, token)})
            except HTTPException:
                await ws.send_json({"type": "update"})
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_lock:
            _ws_rooms.get(code, {}).pop(ws, None)
            if not _ws_rooms.get(code):
                _ws_rooms.pop(code, None)


# ---- endpoints ----


class CreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    mode: str = Field(default="life")


class JoinBody(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    display: bool = False


class OptionsBody(BaseModel):
    rarities: list[str] | None = None
    startingLife: int | None = Field(default=None, ge=1, le=999)
    mode: str | None = None


class LifeBody(BaseModel):
    delta: int = Field(ge=-999, le=999)
    playerPid: int | None = None  # display corrections target another player


class CmdDamageBody(BaseModel):
    attackerPid: int
    delta: int = Field(ge=-99, le=99)


class EliminateBody(BaseModel):
    undo: bool = False


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=24)


class DisplayBody(BaseModel):
    display: bool = True


class OrderBody(BaseModel):
    pids: list[int]


class ReclaimBody(BaseModel):
    pid: int
    force: bool = False


@router.post("/rooms")
def create_room(body: CreateBody, request: Request):
    if body.mode not in MODES:
        raise HTTPException(400, "unknown mode")
    expire_idle_rooms()  # cheap hygiene sweep, off the hot path
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
    token = secrets.token_urlsafe(24)
    starting = 40 if body.mode == "treachery" else 20
    q(
        "INSERT INTO rooms (code, mode, starting_life) VALUES (?, ?, ?)",
        (code, body.mode, starting),
    )
    q(
        "INSERT INTO players (room_code, token, name, is_host, account_id) VALUES (?, ?, ?, 1, ?)",
        (code, token, body.name.strip(), account_id_of(request)),
    )
    log_event(code, f"{body.name.strip()} created the room ({body.mode} mode)")
    touch(code)
    return {"code": code, "playerToken": token}


@router.post("/rooms/{code}/join")
async def join_room(code: str, body: JoinBody, request: Request):
    room = get_room(code)
    name = body.name.strip()
    if body.display:
        token = secrets.token_urlsafe(24)
        q(
            "INSERT INTO players (room_code, token, name, is_display) VALUES (?, ?, ?, 1)",
            (room["code"], token, name or "Table display"),
        )
        log_event(room["code"], "a table display connected")
        await broadcast(room["code"])
        return {"code": room["code"], "playerToken": token}
    if norm_status(room["status"]) != "lobby":
        raise HTTPException(409, "game already started — ask the host to reopen the lobby")
    token = secrets.token_urlsafe(24)
    q(
        "INSERT INTO players (room_code, token, name, account_id) VALUES (?, ?, ?, ?)",
        (room["code"], token, name, account_id_of(request)),
    )
    log_event(room["code"], f"{name} joined")
    touch(room["code"])
    await broadcast(room["code"])
    return {"code": room["code"], "playerToken": token}


@router.get("/rooms/{code}/seats")
def seats(code: str):
    """Seats in a room, so someone who dropped out can find their way back in.
    Knowing the room code is the credential here, same as joining."""
    room = get_room(code)
    rows = q(
        "SELECT id, name, left_game, eliminated FROM players WHERE room_code = ? AND is_display = 0 "
        "ORDER BY COALESCE(seat_order, 1000000), joined_at, id",
        (room["code"],),
    ).fetchall()
    return {
        "status": norm_status(room["status"]),
        "mode": room["mode"],
        "seats": [
            {
                "pid": r["id"],
                "name": r["name"],
                "vacant": bool(r["left_game"]),
                "eliminated": bool(r["eliminated"]),
            }
            for r in rows
        ],
    }


@router.post("/rooms/{code}/reclaim")
async def reclaim(code: str, body: ReclaimBody):
    """Take back a seat after leaving or losing a session. The seat keeps its
    life, commander damage and identity — only the device token changes."""
    room = get_room(code)
    if norm_status(room["status"]) == "ended":
        raise HTTPException(409, "that game has ended")
    row = q(
        "SELECT * FROM players WHERE room_code = ? AND id = ? AND is_display = 0",
        (room["code"], body.pid),
    ).fetchone()
    if not row:
        raise HTTPException(404, "seat not found")
    if not row["left_game"] and not body.force:
        raise HTTPException(409, "that seat is still in use")
    token = secrets.token_urlsafe(24)  # the old device's token stops working
    q("UPDATE players SET token = ?, left_game = 0 WHERE id = ?", (token, row["id"]))
    log_event(room["code"], f"{row['name']} rejoined")
    touch(room["code"])
    await broadcast(room["code"])
    return {"code": room["code"], "playerToken": token}


@router.get("/rooms/{code}/me")
def me(code: str, x_player_token: str | None = Header(default=None)):
    player = get_player(code, x_player_token)
    if player["left_game"]:
        # a leaver's token must not let them back into the room
        raise HTTPException(403, "you have left this room")
    return room_state(code, x_player_token)


@router.post("/rooms/{code}/options")
async def set_options(code: str, body: OptionsBody, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if not player["is_host"]:
        raise HTTPException(403, "host only")
    if body.mode is not None and body.mode != room["mode"]:
        if body.mode not in MODES:
            raise HTTPException(400, "unknown mode")
        if norm_status(room["status"]) != "lobby":
            raise HTTPException(409, "can only change the mode in the lobby")
        # each mode carries its own starting life (commander pairs with treachery)
        life = 40 if body.mode == "treachery" else 20
        q(
            "UPDATE rooms SET mode = ?, starting_life = ? WHERE code = ?",
            (body.mode, life, room["code"]),
        )
        label = "Treachery" if body.mode == "treachery" else "life counter"
        log_event(room["code"], f"{player['name']} switched the game to {label} (starting life {life})")
    if body.rarities is not None:
        rarities = [r for r in body.rarities if r in RARITIES] or RARITIES
        opts = json.loads(room["options"])
        opts["rarities"] = rarities
        q("UPDATE rooms SET options = ? WHERE code = ?", (json.dumps(opts), room["code"]))
    if body.startingLife is not None:
        if norm_status(room["status"]) != "lobby":
            raise HTTPException(409, "can only change starting life in the lobby")
        q("UPDATE rooms SET starting_life = ? WHERE code = ?", (body.startingLife, room["code"]))
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/start")
async def start_game(code: str, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if not player["is_host"]:
        raise HTTPException(403, "host only")
    if norm_status(room["status"]) != "lobby":
        raise HTTPException(409, "already started")
    players = active_players(room["code"])
    n = len(players)
    if n < 1:
        raise HTTPException(400, "no players")

    # a new game begins: bump the history segment counter before logging deal events
    q("UPDATE rooms SET game_no = game_no + 1 WHERE code = ?", (room["code"],))

    first_row = None
    if room["mode"] == "treachery":
        ldr, trt, ass, gdn = distribution(n)
        need = {"Leader": ldr, "Traitor": trt, "Assassin": ass, "Guardian": gdn}
        # one random rarity tier for the whole table (rarity ≈ power level, keeps it fair)
        eligible = [
            r for r in RARITIES
            if all(
                len([c for c in _cards_by_role[role] if c["rarity"] == r]) >= cnt
                for role, cnt in need.items()
            )
        ]
        tier = random.choice(eligible) if eligible else None
        tier_label = {"U": "Uncommon", "R": "Rare", "M": "Mythic", "S": "Special"}.get(tier or "", "mixed")
        picked = []
        for role, count in need.items():
            pool = (
                [c for c in _cards_by_role[role] if c["rarity"] == tier]
                if tier
                else _cards_by_role[role]
            )
            picked.extend(random.sample(pool, count))
        random.shuffle(picked)
        for p, card in zip(players, picked):
            face_up = 1 if "Unveil" not in card["text"] else 0
            q(
                "UPDATE players SET card_id = ?, revealed = ? WHERE id = ?",
                (card["id"], face_up, p["id"]),
            )
            if card["types"]["subtype"] == "Leader":
                first_row = p
        mix = " / ".join(
            f"{c} {r}{'s' if c > 1 else ''}"
            for r, c in (("Leader", ldr), ("Traitor", trt), ("Assassin", ass), ("Guardian", gdn))
            if c
        )
        log_event(
            room["code"],
            f"{player['name']} dealt identities to {n} players ({mix}) — {tier_label} tier",
        )
        log_event(room["code"], f"{first_row['name']} is the Leader and goes first")
    else:
        first_row = random.choice(players)
        log_event(room["code"], f"rolled for first turn — {first_row['name']} goes first")

    q(
        "UPDATE players SET life = ?, eliminated = 0 WHERE room_code = ? AND is_display = 0",
        (room["starting_life"], room["code"]),
    )
    q(
        "UPDATE rooms SET status = 'playing', first_pid = ? WHERE code = ?",
        (first_row["id"], room["code"]),
    )
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/life")
async def adjust_life(code: str, body: LifeBody, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if norm_status(room["status"]) != "playing":
        raise HTTPException(409, "no game in progress")
    if body.delta == 0:
        return {"ok": True}
    if body.playerPid is not None and body.playerPid != player["id"]:
        if not player["is_display"]:
            raise HTTPException(403, "only the table display can adjust other players")
        target = q(
            "SELECT * FROM players WHERE room_code = ? AND id = ? AND is_display = 0 AND left_game = 0",
            (room["code"], body.playerPid),
        ).fetchone()
        if not target:
            raise HTTPException(404, "player not found")
        who = "table display"
    else:
        if player["is_display"]:
            raise HTTPException(409, "the display has no life total — pass a player")
        target = player
        who = target["name"]
    old = target["life"] if target["life"] is not None else room["starting_life"]
    new = old + body.delta
    q("UPDATE players SET life = ? WHERE id = ?", (new, target["id"]))
    sign = "+" if body.delta > 0 else ""
    suffix = f" (by {who})" if who == "table display" else ""
    log_event(room["code"], f"{target['name']}: {sign}{body.delta} life, {old} → {new}{suffix}")
    await broadcast(room["code"])
    return {"ok": True, "life": new}


@router.post("/rooms/{code}/cmddmg")
async def commander_damage(code: str, body: CmdDamageBody, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if norm_status(room["status"]) != "playing":
        raise HTTPException(409, "no game in progress")
    if player["is_display"]:
        raise HTTPException(409, "displays don't take damage")
    attacker = q(
        "SELECT * FROM players WHERE room_code = ? AND id = ? AND is_display = 0",
        (room["code"], body.attackerPid),
    ).fetchone()
    # self is a legal attacker: your own commander can be turned against you
    if not attacker:
        raise HTTPException(400, "invalid attacker")
    row = q(
        "SELECT amount FROM cmd_damage WHERE room_code = ? AND defender_id = ? AND attacker_id = ?",
        (room["code"], player["id"], attacker["id"]),
    ).fetchone()
    old_amt = row["amount"] if row else 0
    delta = max(body.delta, -old_amt)  # can't undo below 0
    if delta == 0:
        return {"ok": True}
    new_amt = old_amt + delta
    q(
        "INSERT INTO cmd_damage (room_code, defender_id, attacker_id, amount) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(room_code, defender_id, attacker_id) DO UPDATE SET amount = ?",
        (room["code"], player["id"], attacker["id"], new_amt, new_amt),
    )
    old_life = player["life"] if player["life"] is not None else room["starting_life"]
    new_life = old_life - delta  # commander damage is also real damage
    q("UPDATE players SET life = ? WHERE id = ?", (new_life, player["id"]))
    log_event(
        room["code"],
        f"{player['name']} took {delta} commander damage from {attacker['name']} "
        f"(total {new_amt}, life {old_life} → {new_life})"
        if delta > 0
        else f"{player['name']} undid {-delta} commander damage from {attacker['name']} "
        f"(total {new_amt}, life {old_life} → {new_life})",
    )
    lethal = new_amt >= 21
    await broadcast(room["code"])
    return {"ok": True, "total": new_amt, "life": new_life, "lethal": lethal}


@router.post("/rooms/{code}/eliminate")
async def eliminate(code: str, body: EliminateBody, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if norm_status(room["status"]) != "playing":
        raise HTTPException(409, "no game in progress")
    if player["is_display"]:
        raise HTTPException(409, "displays can't be eliminated")
    if body.undo:
        q("UPDATE players SET eliminated = 0, eliminated_at = NULL WHERE id = ?", (player["id"],))
        log_event(room["code"], f"{player['name']} is back in the game")
    else:
        q(
            "UPDATE players SET eliminated = 1, eliminated_at = unixepoch() WHERE id = ?",
            (player["id"],),
        )
        if room["mode"] == "treachery" and player["card_id"] and not player["revealed"]:
            # CR 907.13: losing the game reveals your identity
            q("UPDATE players SET revealed = 1 WHERE id = ?", (player["id"],))
            card = _cards_by_id[player["card_id"]]
            log_event(
                room["code"],
                f"{player['name']} was eliminated — revealed as {card['name']} ({card['types']['subtype']})",
            )
        else:
            log_event(room["code"], f"{player['name']} was eliminated")
        await check_last_standing(get_room(code))
    touch(room["code"])
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/rename")
async def rename(code: str, body: RenameBody, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if player["left_game"]:
        raise HTTPException(403, "you have left this room")
    new = body.name.strip()
    if new == player["name"]:
        return {"ok": True}
    q("UPDATE players SET name = ? WHERE id = ?", (new, player["id"]))
    if not player["is_display"]:
        log_event(room["code"], f"{player['name']} is now known as {new}")
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/display")
async def set_display(code: str, body: DisplayBody, x_player_token: str | None = Header(default=None)):
    """Turn this device into the shared table display (or back into a player).
    Reachable from inside the room, since a QR scan auto-joins as a player."""
    room = get_room(code)
    player = get_player(code, x_player_token)
    if player["left_game"]:
        raise HTTPException(403, "you have left this room")
    if bool(player["is_display"]) == body.display:
        return {"ok": True}
    if not body.display and norm_status(room["status"]) != "lobby":
        raise HTTPException(409, "can only take a seat from the lobby")
    if body.display:
        # a display holds no game state; give up the seat and the host role
        q(
            "UPDATE players SET is_display = 1, card_id = NULL, revealed = 0, "
            "life = NULL, eliminated = 0, is_host = 0 WHERE id = ?",
            (player["id"],),
        )
        q("DELETE FROM cmd_damage WHERE room_code = ? AND (defender_id = ? OR attacker_id = ?)",
          (room["code"], player["id"], player["id"]))
        if player["is_host"]:
            nxt = q(
                "SELECT id FROM players WHERE room_code = ? AND left_game = 0 AND is_display = 0 "
                "ORDER BY joined_at, id LIMIT 1",
                (room["code"],),
            ).fetchone()
            if nxt:
                q("UPDATE players SET is_host = 1 WHERE id = ?", (nxt["id"],))
        log_event(room["code"], f"{player['name']} is now the table display")
    else:
        q("UPDATE players SET is_display = 0 WHERE id = ?", (player["id"],))
        log_event(room["code"], f"{player['name']} took a seat")
    touch(room["code"])
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/order")
async def set_order(code: str, body: OrderBody, x_player_token: str | None = Header(default=None)):
    """Rearrange the seats — dragged on the table display, mirrored to every device."""
    room = get_room(code)
    player = get_player(code, x_player_token)
    if not (player["is_display"] or player["is_host"]):
        raise HTTPException(403, "only the table display or host can rearrange seats")
    seated = {
        r["id"]
        for r in q(
            "SELECT id FROM players WHERE room_code = ? AND is_display = 0", (room["code"],)
        ).fetchall()
    }
    for i, pid in enumerate(p for p in body.pids if p in seated):
        q("UPDATE players SET seat_order = ? WHERE id = ?", (i, pid))
    touch(room["code"])
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/unveil")
async def unveil(code: str, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if norm_status(room["status"]) != "playing":
        raise HTTPException(409, "no game in progress")
    if not player["card_id"]:
        raise HTTPException(409, "you have no identity card")
    q("UPDATE players SET revealed = 1 WHERE id = ?", (player["id"],))
    card = _cards_by_id[player["card_id"]]
    log_event(room["code"], f"{player['name']} unveiled as {card['name']} ({card['types']['subtype']})")
    touch(room["code"])
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/end")
async def end_game(code: str, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if not player["is_host"]:
        raise HTTPException(403, "host only")
    q("UPDATE rooms SET status = 'ended' WHERE code = ?", (room["code"],))
    log_event(
        room["code"],
        f"{player['name']} ended the game"
        + (" — all identities revealed" if room["mode"] == "treachery" else ""),
    )
    if room["mode"] == "treachery":
        # preserve the final reveal in the history/log (clients return to the lobby right away)
        for p in q(
            "SELECT * FROM players WHERE room_code = ? AND is_display = 0 AND left_game = 0 ORDER BY joined_at, id",
            (room["code"],),
        ).fetchall():
            if p["card_id"]:
                card = _cards_by_id[p["card_id"]]
                log_event(
                    room["code"],
                    f"final identity: {p['name']} — {card['name']} ({card['types']['subtype']})",
                )
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/reopen")
async def reopen(code: str, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if not player["is_host"]:
        raise HTTPException(403, "host only")
    q(
        "UPDATE players SET card_id = NULL, revealed = 0, life = NULL, eliminated = 0 WHERE room_code = ?",
        (room["code"],),
    )
    q("DELETE FROM players WHERE room_code = ? AND left_game = 1", (room["code"],))
    q("DELETE FROM cmd_damage WHERE room_code = ?", (room["code"],))
    q("UPDATE rooms SET status = 'lobby', first_pid = NULL WHERE code = ?", (room["code"],))
    log_event(room["code"], f"{player['name']} reopened the lobby for a new game")
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/leave")
async def leave(code: str, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if player["is_display"]:
        q("DELETE FROM players WHERE id = ?", (player["id"],))
        log_event(room["code"], "a table display disconnected")
        await broadcast(room["code"])
        return {"ok": True}
    if norm_status(room["status"]) == "lobby":
        q("DELETE FROM players WHERE id = ?", (player["id"],))
        log_event(room["code"], f"{player['name']} left")
    else:
        # Treachery CR 907.13: a leaving player's face-down identity is revealed
        q("UPDATE players SET left_game = 1, revealed = 1 WHERE id = ?", (player["id"],))
        card = _cards_by_id[player["card_id"]] if player["card_id"] else None
        log_event(
            room["code"],
            f"{player['name']} left the game"
            + (f" — revealed as {card['name']} ({card['types']['subtype']})" if card else ""),
        )
    if player["is_host"]:
        nxt = q(
            "SELECT id FROM players WHERE room_code = ? AND left_game = 0 AND is_display = 0 ORDER BY joined_at, id LIMIT 1",
            (room["code"],),
        ).fetchone()
        if nxt:
            q("UPDATE players SET is_host = 1 WHERE id = ?", (nxt["id"],))
    await check_last_standing(get_room(code))
    touch(room["code"])
    await broadcast(room["code"])
    return {"ok": True}
