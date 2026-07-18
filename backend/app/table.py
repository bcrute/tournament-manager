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
_here = Path(__file__).resolve()
CARDS_PATH = next(
    p for p in (_here.parents[1] / "data", _here.parents[2] / "data")
    if (p / "treachery-cards.json").exists()
) / "treachery-cards.json"

RARITIES = ["U", "R", "M", "S"]
MODES = ["life", "treachery"]
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
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_code TEXT NOT NULL,
        at INTEGER NOT NULL DEFAULT (unixepoch()),
        text TEXT NOT NULL
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
    CREATE TABLE IF NOT EXISTS cmd_damage (
        room_code TEXT NOT NULL,
        defender_id INTEGER NOT NULL,
        attacker_id INTEGER NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (room_code, defender_id, attacker_id)
    );
    """
)


def _ensure_column(table: str, col: str, decl: str):
    cols = [r[1] for r in _db.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        _db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


_ensure_column("rooms", "mode", "TEXT NOT NULL DEFAULT 'treachery'")
_ensure_column("rooms", "starting_life", "INTEGER NOT NULL DEFAULT 40")
_ensure_column("rooms", "first_player", "TEXT")  # legacy, superseded by first_pid
_ensure_column("rooms", "first_pid", "INTEGER")
_ensure_column("rooms", "game_no", "INTEGER NOT NULL DEFAULT 0")
_ensure_column("events", "game_no", "INTEGER")
_ensure_column("players", "is_display", "INTEGER NOT NULL DEFAULT 0")
_ensure_column("players", "life", "INTEGER")
_ensure_column("players", "eliminated", "INTEGER NOT NULL DEFAULT 0")
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


def room_state(code: str, token: str):
    room = get_room(code)
    me = get_player(code, token)
    status = norm_status(room["status"])
    treachery = room["mode"] == "treachery"
    players = q(
        "SELECT * FROM players WHERE room_code = ? ORDER BY is_display, joined_at, id",
        (room["code"],),
    ).fetchall()
    ended = status == "ended"
    n_active = len([p for p in players if not p["left_game"] and not p["is_display"]])
    ldr, trt, ass, gdn = distribution(n_active) if treachery else (0, 0, 0, 0)
    cmd = cmd_matrix(room["code"])
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
    events = q(
        "SELECT at, text FROM events WHERE room_code = ? ORDER BY id DESC LIMIT 60",
        (room["code"],),
    ).fetchall()
    first_pid = room["first_pid"]
    first_name = next((p["name"] for p in players if p["id"] == first_pid), None)
    return {
        "log": [{"at": e["at"], "text": e["text"]} for e in events],
        "room": {
            "code": room["code"],
            "status": status,
            "mode": room["mode"],
            "startingLife": room["starting_life"],
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
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_lock:
            _ws_rooms.get(code, set()).discard(ws)


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


@router.post("/rooms")
def create_room(body: CreateBody):
    if body.mode not in MODES:
        raise HTTPException(400, "unknown mode")
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
    token = secrets.token_urlsafe(24)
    starting = 40 if body.mode == "treachery" else 20
    q(
        "INSERT INTO rooms (code, mode, starting_life) VALUES (?, ?, ?)",
        (code, body.mode, starting),
    )
    q(
        "INSERT INTO players (room_code, token, name, is_host) VALUES (?, ?, ?, 1)",
        (code, token, body.name.strip()),
    )
    log_event(code, f"{body.name.strip()} created the room ({body.mode} mode)")
    return {"code": code, "playerToken": token}


@router.post("/rooms/{code}/join")
async def join_room(code: str, body: JoinBody):
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
        "INSERT INTO players (room_code, token, name) VALUES (?, ?, ?)",
        (room["code"], token, name),
    )
    log_event(room["code"], f"{name} joined")
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
    if not attacker or attacker["id"] == player["id"]:
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
        q("UPDATE players SET eliminated = 0 WHERE id = ?", (player["id"],))
        log_event(room["code"], f"{player['name']} is back in the game")
    else:
        q("UPDATE players SET eliminated = 1 WHERE id = ?", (player["id"],))
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
    await broadcast(room["code"])
    return {"ok": True}
