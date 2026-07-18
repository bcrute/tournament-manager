import asyncio
import json
import os
import random
import secrets
import sqlite3
import threading
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

router = APIRouter()

DB_PATH = os.environ.get("TREACHERY_DB", "treachery.db")
# container: /app/app/treachery.py with data at /app/data; repo: backend/app/ with data at repo root
_here = Path(__file__).resolve()
CARDS_PATH = next(
    p for p in (_here.parents[1] / "data", _here.parents[2] / "data")
    if (p / "treachery-cards.json").exists()
) / "treachery-cards.json"

RARITIES = ["U", "R", "M", "S"]
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L

_db_lock = threading.Lock()
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.executescript(
    """
    CREATE TABLE IF NOT EXISTS rooms (
        code TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'lobby',
        options TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL DEFAULT (unixepoch())
    );
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_code TEXT NOT NULL REFERENCES rooms(code),
        token TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        is_host INTEGER NOT NULL DEFAULT 0,
        card_id INTEGER,
        revealed INTEGER NOT NULL DEFAULT 0,
        left_game INTEGER NOT NULL DEFAULT 0,
        joined_at INTEGER NOT NULL DEFAULT (unixepoch())
    );
    """
)
_db.commit()

_cards_by_id = {}
_cards_by_role = {"Leader": [], "Guardian": [], "Assassin": [], "Traitor": []}
for _c in json.loads(CARDS_PATH.read_text())["cards"]:
    _cards_by_id[_c["id"]] = _c
    _cards_by_role[_c["types"]["subtype"]].append(_c)


def q(sql, params=()):
    with _db_lock:
        cur = _db.execute(sql, params)
        _db.commit()
        return cur


def distribution(n: int):
    """Role counts (leader, traitor, assassin, guardian) per CR 907.3c."""
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
    # 9+: 907.3b — one Leader, assassins = n//2, rest split traitor/guardian
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
        "image": f"/cards/trd/{card['id']:03d}.jpg",
    }


def get_room(code: str):
    row = q("SELECT * FROM rooms WHERE code = ?", (code.upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "room not found")
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


def room_state(code: str, token: str):
    room = get_room(code)
    me = get_player(code, token)
    players = q(
        "SELECT * FROM players WHERE room_code = ? ORDER BY joined_at, id",
        (room["code"],),
    ).fetchall()
    ended = room["status"] == "ended"
    ldr, trt, ass, gdn = distribution(len([p for p in players if not p["left_game"]]))
    out_players = []
    for p in players:
        visible = ended or p["revealed"] or p["left_game"]
        out_players.append(
            {
                "name": p["name"],
                "isHost": bool(p["is_host"]),
                "revealed": bool(p["revealed"]),
                "left": bool(p["left_game"]),
                "isMe": p["id"] == me["id"],
                "card": card_public(_cards_by_id[p["card_id"]])
                if visible and p["card_id"]
                else None,
            }
        )
    return {
        "room": {
            "code": room["code"],
            "status": room["status"],
            "options": json.loads(room["options"]),
            "distribution": {"Leader": ldr, "Traitor": trt, "Assassin": ass, "Guardian": gdn},
        },
        "players": out_players,
        "me": {
            "name": me["name"],
            "isHost": bool(me["is_host"]),
            "revealed": bool(me["revealed"]),
            "card": card_public(_cards_by_id[me["card_id"]]) if me["card_id"] else None,
        },
    }


# ---- websocket fanout ----

_ws_rooms: dict[str, set] = {}
_ws_lock = asyncio.Lock()


async def broadcast(code: str):
    async with _ws_lock:
        sockets = list(_ws_rooms.get(code.upper(), ()))
    for ws in sockets:
        try:
            await ws.send_json({"type": "update"})
        except Exception:
            pass


@router.websocket("/ws/{code}")
async def ws_room(ws: WebSocket, code: str):
    code = code.upper()
    await ws.accept()
    async with _ws_lock:
        _ws_rooms.setdefault(code, set()).add(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive pings from client
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_lock:
            _ws_rooms.get(code, set()).discard(ws)


# ---- endpoints ----


class CreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=24)


class JoinBody(CreateBody):
    pass


class OptionsBody(BaseModel):
    rarities: list[str] = Field(default=RARITIES)


@router.post("/rooms")
def create_room(body: CreateBody):
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
    token = secrets.token_urlsafe(24)
    q("INSERT INTO rooms (code) VALUES (?)", (code,))
    q(
        "INSERT INTO players (room_code, token, name, is_host) VALUES (?, ?, ?, 1)",
        (code, token, body.name.strip()),
    )
    return {"code": code, "playerToken": token}


@router.post("/rooms/{code}/join")
async def join_room(code: str, body: JoinBody):
    room = get_room(code)
    if room["status"] != "lobby":
        raise HTTPException(409, "game already dealt — ask the host to deal again")
    token = secrets.token_urlsafe(24)
    q(
        "INSERT INTO players (room_code, token, name) VALUES (?, ?, ?)",
        (room["code"], token, body.name.strip()),
    )
    await broadcast(room["code"])
    return {"code": room["code"], "playerToken": token}


@router.get("/rooms/{code}/me")
def me(code: str, x_player_token: str | None = Header(default=None)):
    return room_state(code, x_player_token)


@router.post("/rooms/{code}/options")
async def set_options(code: str, body: OptionsBody, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if not player["is_host"]:
        raise HTTPException(403, "host only")
    rarities = [r for r in body.rarities if r in RARITIES] or RARITIES
    q("UPDATE rooms SET options = ? WHERE code = ?", (json.dumps({"rarities": rarities}), room["code"]))
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/deal")
async def deal(code: str, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if not player["is_host"]:
        raise HTTPException(403, "host only")
    players = q(
        "SELECT * FROM players WHERE room_code = ? AND left_game = 0", (room["code"],)
    ).fetchall()
    n = len(players)
    if n < 1:
        raise HTTPException(400, "no players")
    rarities = json.loads(room["options"]).get("rarities", RARITIES)
    ldr, trt, ass, gdn = distribution(n)
    roles = ["Leader"] * ldr + ["Traitor"] * trt + ["Assassin"] * ass + ["Guardian"] * gdn
    picked = []
    for role, count in (("Leader", ldr), ("Traitor", trt), ("Assassin", ass), ("Guardian", gdn)):
        pool = [c for c in _cards_by_role[role] if c["rarity"] in rarities]
        if len(pool) < count:  # rarity filter too narrow for this role
            pool = _cards_by_role[role]
        picked.extend((role, c) for c in random.sample(pool, count))
    random.shuffle(picked)
    for p, (role, card) in zip(players, picked):
        # Leaders have no unveil ability, so they enter face up (CR 907.4a)
        face_up = 1 if "Unveil" not in card["text"] else 0
        q(
            "UPDATE players SET card_id = ?, revealed = ? WHERE id = ?",
            (card["id"], face_up, p["id"]),
        )
    q("UPDATE rooms SET status = 'dealt' WHERE code = ?", (room["code"],))
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/unveil")
async def unveil(code: str, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if room["status"] != "dealt":
        raise HTTPException(409, "no game in progress")
    if not player["card_id"]:
        raise HTTPException(409, "you have no identity card")
    q("UPDATE players SET revealed = 1 WHERE id = ?", (player["id"],))
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/end")
async def end_game(code: str, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if not player["is_host"]:
        raise HTTPException(403, "host only")
    q("UPDATE rooms SET status = 'ended' WHERE code = ?", (room["code"],))
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/reopen")
async def reopen(code: str, x_player_token: str | None = Header(default=None)):
    """Back to lobby for a re-deal with the same group."""
    room = get_room(code)
    player = get_player(code, x_player_token)
    if not player["is_host"]:
        raise HTTPException(403, "host only")
    q(
        "UPDATE players SET card_id = NULL, revealed = 0 WHERE room_code = ?",
        (room["code"],),
    )
    q("DELETE FROM players WHERE room_code = ? AND left_game = 1", (room["code"],))
    q("UPDATE rooms SET status = 'lobby' WHERE code = ?", (room["code"],))
    await broadcast(room["code"])
    return {"ok": True}


@router.post("/rooms/{code}/leave")
async def leave(code: str, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if room["status"] == "lobby":
        q("DELETE FROM players WHERE id = ?", (player["id"],))
    else:
        # CR 907.13: a leaving player's face-down identity is revealed
        q("UPDATE players SET left_game = 1, revealed = 1 WHERE id = ?", (player["id"],))
    if player["is_host"]:
        nxt = q(
            "SELECT id FROM players WHERE room_code = ? AND left_game = 0 ORDER BY joined_at, id LIMIT 1",
            (room["code"],),
        ).fetchone()
        if nxt:
            q("UPDATE players SET is_host = 1 WHERE id = ?", (nxt["id"],))
    await broadcast(room["code"])
    return {"ok": True}
