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

#: Lethal commander damage from a single source (CR 903.10a).
LETHAL_COMMANDER_DAMAGE = 21
#: Lethal poison counters (CR 104.3c, ten in every format that uses them).
LETHAL_POISON = 10
#: Extra starting life for the Leader in a treachery game. **A house rule, not
#: a format one** — rule 907.6 gives every player the same starting total and
#: says nothing about the Leader. They start face up and get focused for it, so
#: the table gives them a cushion; the rules sheet says as much rather than
#: implying the variant asks for this.
LEADER_BONUS_LIFE = 10
#: How long a player has to say "I'm not dead" when their death would end the
#: game. Only that case waits: they are already looking at the screen when the
#: counter crosses, so this is about the one death nobody can undo afterwards,
#: not about second-guessing every elimination. Deaths that leave the game
#: running stay undoable for as long as it runs, so they need no window.
CONCLUDE_GRACE_SECONDS = 10

_cards_by_id = {}
_cards_by_role = {"Leader": [], "Guardian": [], "Assassin": [], "Traitor": []}
for _c in json.loads(CARDS_PATH.read_text())["cards"]:
    _cards_by_id[_c["id"]] = _c
    _cards_by_role[_c["types"]["subtype"]].append(_c)


def lethal_reason(room, player) -> str | None:
    """Why this player is dead, or None if they aren't.

    Read from stored state rather than passed in, so it gives the same answer
    whoever asks and whatever route changed the number — a player tapping −1,
    the table display adjusting them, or commander damage taking life as a
    side effect.

    **A player who has said they can't lose is never dead by this.** That flag
    exists because the app cannot see the battlefield: Platinum Angel, Solemnity,
    Phyrexian Unlife and a dozen others make a counter stop meaning what it
    normally means, and guessing wrong here would end someone's game for them.
    Deciding they are still alive is the safe direction to be wrong in.
    """
    if player["cant_lose"]:
        return None
    life = player["life"] if player["life"] is not None else room["starting_life"]
    if life <= 0:
        return "life"
    poison = player["poison"] or 0
    if poison >= LETHAL_POISON:
        return "poison"
    worst = q(
        "SELECT a.name AS attacker, d.amount AS amount FROM cmd_damage d "
        "JOIN players a ON a.id = d.attacker_id "
        "WHERE d.room_code = ? AND d.defender_id = ? "
        "ORDER BY d.amount DESC LIMIT 1",
        (room["code"], player["id"]),
    ).fetchone()
    if worst and worst["amount"] >= LETHAL_COMMANDER_DAMAGE:
        return f"commander damage from {worst['attacker']}"
    return None


async def check_auto_death(room, player_id: int):
    """Eliminate a player whose counters have just become lethal.

    Called after anything that moves life, poison or commander damage. Nothing
    here trusts the client: the caller says *what changed*, this decides what
    it means, which is why a rigged request can't kill anyone who isn't dead.

    Death is not final. The player gets an "I'm not dead" button either way —
    this only changes who does the tapping in the ordinary case, where four
    people used to wait for one of them to notice and confirm it.
    """
    if norm_status(room["status"]) != "playing":
        return
    player = q(
        "SELECT * FROM players WHERE id = ? AND is_display = 0 AND left_game = 0 "
        "AND eliminated = 0",
        (player_id,),
    ).fetchone()
    if not player:
        return
    reason = lethal_reason(room, player)
    if not reason:
        return
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
            f"{player['name']} was eliminated by {reason} — revealed as "
            f"{card['name']} ({card['types']['subtype']})",
        )
    else:
        log_event(room["code"], f"{player['name']} was eliminated by {reason}")
    await check_last_standing(get_room(room["code"]), grace=True)


async def revive_if_adjusted_back(room, player_id: int):
    """Touching a dead player's life says they aren't dead.

    Reviving used to be its own deliberate action. But somebody reaching over
    to put life back on an eliminated player has already said what they mean,
    and making them find a menu afterwards to confirm it is ceremony.

    **Only when the counters agree.** Adding life takes them off zero and they
    are back; taking more away leaves them lethal, so they stay out and nothing
    happens. That is not a technicality — an elimination carries the moment it
    happened, `eliminated_at`, and tournament placement is read from the order
    of those. Clearing and re-stamping it on a stray tap would quietly reorder
    a pod's results.
    """
    if norm_status(room["status"]) != "playing":
        return
    player = q(
        "SELECT * FROM players WHERE id = ? AND is_display = 0 AND left_game = 0 "
        "AND eliminated = 1",
        (player_id,),
    ).fetchone()
    if not player:
        return
    if lethal_reason(room, player):
        return  # still dead by the numbers; leave the elimination where it is
    q(
        "UPDATE players SET eliminated = 0, eliminated_at = NULL WHERE id = ?",
        (player["id"],),
    )
    log_event(room["code"], f"{player['name']} is back in the game")
    # they might have been the death that was about to end it
    cancel_pending_conclusion(room["code"])


def cancel_pending_conclusion(code: str):
    """Called whenever someone comes back from the dead."""
    q("UPDATE rooms SET concludes_at = NULL WHERE code = ?", (code,))


async def resolve_pending_conclusion(code: str):
    """End a game whose grace window has run out.

    The window is an absolute timestamp rather than a live timer, so this is
    safe to call from anywhere and any number of times: it ends the game once
    the moment has passed and does nothing before then. A scheduled task fires
    it on time; every state read calls it too, so a restarted process — which
    loses the task — still concludes the game rather than leaving the room
    stuck behind a countdown that already finished.
    """
    room = q("SELECT * FROM rooms WHERE code = ?", (code.upper(),)).fetchone()
    if not room or room["concludes_at"] is None:
        return False
    if norm_status(room["status"]) != "playing":
        cancel_pending_conclusion(room["code"])
        return False
    now = q("SELECT unixepoch() AS n").fetchone()["n"]
    if now < room["concludes_at"]:
        return False
    cancel_pending_conclusion(room["code"])
    await check_last_standing(get_room(room["code"]), grace=False)
    return True


async def _conclude_after_grace(code: str, delay: int):
    """Fire the conclusion on time rather than on the next poll.

    Without this the game would end whenever a client next asked, which is up
    to a poll interval late and looks like the countdown hanging on zero.
    """
    try:
        await asyncio.sleep(delay)
        if await resolve_pending_conclusion(code):
            await broadcast(code)
    except asyncio.CancelledError:  # pragma: no cover - shutdown
        raise
    except Exception:  # pragma: no cover - a failed timer must not kill the loop
        pass


async def check_last_standing(room, grace: bool = False):
    """One player left in a live game means it's over — end it so every client
    can show the result and return to the room together.

    `grace` holds the ending open for `CONCLUDE_GRACE_SECONDS` first. That is
    for automatic deaths only: the counter crossed on its own, and the player
    it killed is the one person who can say the board says otherwise. A player
    who deliberately taps "I lost some other way" has already decided, so their
    game ends immediately — waiting would only make the app feel unsure.
    """
    if norm_status(room["status"]) != "playing":
        return
    alive = q(
        "SELECT name FROM players WHERE room_code = ? AND is_display = 0 "
        "AND left_game = 0 AND eliminated = 0",
        (room["code"],),
    ).fetchall()
    if len(alive) > 1:
        # more than one player left, so nothing is pending any more either —
        # someone came back and the game carried on
        cancel_pending_conclusion(room["code"])
        return
    if grace:
        # already counting down from an earlier death: don't restart the clock
        pending = q(
            "SELECT concludes_at FROM rooms WHERE code = ?", (room["code"],)
        ).fetchone()["concludes_at"]
        if pending is None:
            q(
                "UPDATE rooms SET concludes_at = unixepoch() + ? WHERE code = ?",
                (CONCLUDE_GRACE_SECONDS, room["code"]),
            )
            asyncio.create_task(_conclude_after_grace(room["code"], CONCLUDE_GRACE_SECONDS))
        return
    cancel_pending_conclusion(room["code"])
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
    await report_tournament_result(room)


async def report_tournament_result(room):
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

    # awaited, not fired and forgotten: recording the result also pushes the new
    # standings to everyone watching the tournament
    await record_room_result(room["code"], room["game_no"], order)


def seat_resources(room_code: str) -> list[dict]:
    """Each seat's live state, in the vocabulary the tournament layer speaks.

    The room stores the tracked resource in a column called `life`, because this
    started as a life counter and the schema is older than game profiles. That
    name is the room's business and nobody else's: a tournament ranking an
    unfinished pod asks what each seat *has* and who is out, and the game
    profile says which way those numbers rank. Reading `players.life` from the
    tournament layer put MTG's word for the resource in code that is supposed
    not to know what Magic is.
    """
    return [
        {
            "token": r["token"],
            "resource": r["life"],
            "eliminated": bool(r["eliminated"]),
            "eliminatedAt": r["eliminated_at"] or 0,
        }
        for r in q(
            "SELECT token, life, eliminated, eliminated_at FROM players WHERE room_code = ?",
            (room_code,),
        ).fetchall()
    ]


def note_mid_game_arrival(room, name: str):
    """Say at the table whatever this room's mode makes true of a player seated
    into a game already under way.

    The organizer moving an entrant between pods is a tournament action; what it
    means at the table is the room's business. Treachery deals hidden identities
    once, at the start of a game, and nothing deals one mid-game — so the table
    is told rather than leaving somebody silently card-less. A mode with nothing
    to add says nothing, and a game with no such mode never gets here.
    """
    if room["mode"] == "treachery":
        log_event(room["code"], f"{name} has no identity card — deal one or restart the game")


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
    room stops accepting play, so an abandoned code can't be rejoined forever.

    A pod of a live tournament is exempt: three hours is a room's clock, and a
    field breaking for lunch must not come back to closed tables. The exemption
    lasts exactly as long as the tournament does — see tournaments.LIVE_TOURNAMENT
    — so an ended or expired event's rooms come back under this sweep instead of
    living forever behind a tournament that no longer exists as a live thing.
    """
    from .tournaments import IDLE_TIMEOUT as TOURNAMENT_IDLE_TIMEOUT
    from .tournaments import LIVE_TOURNAMENT_ROOMS

    q(
        "UPDATE rooms SET status = 'closed' WHERE status != 'closed' "
        "AND COALESCE(last_active, created_at) < unixepoch() - ? "
        f"AND code NOT IN ({LIVE_TOURNAMENT_ROOMS})",
        (IDLE_TIMEOUT, TOURNAMENT_IDLE_TIMEOUT),
    )


def touch(code: str):
    q("UPDATE rooms SET last_active = unixepoch() WHERE code = ?", (code,))


def _is_tournament_room(code: str) -> bool:
    """Is a still-live tournament holding this room open? Asking whether a pods
    row merely exists would exempt the pods of events that ended months ago."""
    from .tournaments import IDLE_TIMEOUT as TOURNAMENT_IDLE_TIMEOUT
    from .tournaments import LIVE_TOURNAMENT_ROOMS

    return bool(
        q(
            f"SELECT 1 FROM ({LIVE_TOURNAMENT_ROOMS}) WHERE room_code = ? LIMIT 1",
            (TOURNAMENT_IDLE_TIMEOUT, code),
        ).fetchone()
    )


def note_bad_join(request: Request):
    """Record a join attempt against a room that isn't there.

    Wrong codes happen — someone mistypes, or a room has expired. A client
    producing them repeatedly is doing something else, and the shared limiter
    already knows how to escalate; this just tells it that these attempts count.
    """
    limiter = getattr(request.app.state, "limiter", None)
    if limiter is None:
        return
    from .audit import security_event
    from .limits import client_id, client_ip

    cid = client_id(client_ip(request))
    security_event("join.unknown_room", cid, None)
    limiter.strike(cid)


def new_url_id() -> str:
    """The opaque half of a room's identity.

    The five-character code is what someone reads across a table, so it is
    short by necessity. This is what goes in the address bar: 128 random bits,
    so a link, a screenshot or a browser-history entry doesn't hand over
    something joinable.
    """
    return secrets.token_urlsafe(16)


def get_room(code: str, allow_closed: bool = False):
    row = q("SELECT * FROM rooms WHERE code = ?", (code.upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "room not found")
    # check just this room's idle clock (primary-key read); the bulk sweep runs on create
    if row["status"] != "closed" and not _is_tournament_room(row["code"]):
        cutoff = q("SELECT unixepoch() - ? AS c", (IDLE_TIMEOUT,)).fetchone()["c"]
        # no timestamp means no idle verdict — same as the sweep's COALESCE,
        # where a NULL comparison is false. Seen as a live TypeError once.
        last_seen = row["last_active"] or row["created_at"]
        if last_seen is not None and last_seen < cutoff:
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
        "SELECT p.id AS pod_id, p.number AS table_no, p.label AS table_name, "
        "p.turns_remaining, p.extension_seconds, "
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
        "tableName": row["table_name"],   # null unless the organizer named it
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
                "cantLose": bool(p["cant_lose"]),
                "isMe": p["id"] == me["id"],
                "life": p["life"],
                "poison": p["poison"] or 0,
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
            "urlId": room["url_id"],
            "status": status,
            "mode": room["mode"],
            "startingLife": room["starting_life"],
            "gameNo": room["game_no"],
            "firstPid": first_pid,
            "firstPlayer": first_name,
            "options": json.loads(room["options"]),
            # The moment this game ends unless someone says they're not dead,
            # and the server's own clock to measure it against — a phone whose
            # clock is wrong would otherwise show the wrong countdown, the same
            # correction the round clock makes.
            "concludesAt": room["concludes_at"],
            "now": int(time.time()),
            "displays": len([p for p in players if p["is_display"] and not p["left_game"]]),
            "distribution": {"Leader": ldr, "Traitor": trt, "Assassin": ass, "Guardian": gdn},
        },
        "players": out_players,
        "me": {
            "pid": me["id"],
            "name": me["name"],
            "isHost": bool(me["is_host"]),
            "isDisplay": bool(me["is_display"]),
            "isTracker": bool(me["is_tracker"]),
            "cantLose": bool(me["cant_lose"]),
            "revealed": bool(me["revealed"]),
            "eliminated": bool(me["eliminated"]),
            "life": me["life"],
            "poison": me["poison"] or 0,
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
    #: Open the room as the shared screen rather than as a player. A spare
    #: tablet setting up the table starts here; the first player to join takes
    #: the host's controls, since a display holds no seat.
    display: bool = False


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
    #: whose total to change. Omitted means the caller. Only the table display,
    #: or a player keeping score, may name someone else.
    defenderPid: int | None = None


class PoisonBody(BaseModel):
    delta: int = Field(ge=-99, le=99)
    #: whose counters to change. Omitted means the caller. Same rule as life:
    #: only the table display, or a player keeping score, may name someone else.
    playerPid: int | None = None


class EliminateBody(BaseModel):
    undo: bool = False
    #: whose game to end. Omitted means the caller. Only the table display, or
    #: a player keeping score, may name someone else — for the player whose
    #: phone is across the table or out of battery.
    playerPid: int | None = None


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
        "INSERT INTO rooms (code, url_id, mode, starting_life) VALUES (?, ?, ?, ?)",
        (code, url_id := new_url_id(), body.mode, starting),
    )
    if body.display:
        # a display holds no seat, so it cannot be the host either; whoever
        # joins first gets the controls (see join_room)
        q(
            "INSERT INTO players (room_code, token, name, is_display) VALUES (?, ?, ?, 1)",
            (code, token, body.name.strip() or "Table display"),
        )
        log_event(code, f"a table display opened the room ({body.mode} mode)")
    else:
        q(
            "INSERT INTO players (room_code, token, name, is_host, account_id) VALUES (?, ?, ?, 1, ?)",
            (code, token, body.name.strip(), account_id_of(request)),
        )
        log_event(code, f"{body.name.strip()} created the room ({body.mode} mode)")
    touch(code)
    return {"code": code, "urlId": url_id, "playerToken": token}


@router.post("/rooms/{code}/join")
async def join_room(code: str, body: JoinBody, request: Request):
    # A room code is short enough to read across a table, which means it is
    # short enough to guess. The URL id keeps codes out of links and history,
    # but this is the endpoint an enumerator would actually hammer, so a client
    # that keeps naming rooms that don't exist is treated as one.
    try:
        room = get_room(code)
    except HTTPException:
        note_bad_join(request)
        raise

    name = body.name.strip()
    if body.display:
        token = secrets.token_urlsafe(24)
        q(
            "INSERT INTO players (room_code, token, name, is_display) VALUES (?, ?, ?, 1)",
            (room["code"], token, name or "Table display"),
        )
        log_event(room["code"], "a table display connected")
        await broadcast(room["code"])
        return {"code": room["code"], "urlId": room["url_id"], "playerToken": token}
    if norm_status(room["status"]) != "lobby":
        raise HTTPException(409, "game already started — ask the host to reopen the lobby")
    token = secrets.token_urlsafe(24)
    # A room opened by a table display has no host until someone sits down;
    # without this nobody could ever start the game.
    host = not q(
        "SELECT 1 FROM players WHERE room_code = ? AND is_host = 1 AND is_display = 0 "
        "AND left_game = 0",
        (room["code"],),
    ).fetchone()
    q(
        "INSERT INTO players (room_code, token, name, is_host, account_id) VALUES (?, ?, ?, ?, ?)",
        (room["code"], token, name, 1 if host else 0, account_id_of(request)),
    )
    log_event(room["code"], f"{name} joined")
    touch(room["code"])
    await broadcast(room["code"])
    return {"code": room["code"], "urlId": room["url_id"], "playerToken": token}


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
    return {"code": room["code"], "urlId": room["url_id"], "playerToken": token}


@router.get("/rooms/{code}/me")
async def me(code: str, x_player_token: str | None = Header(default=None)):
    player = get_player(code, x_player_token)
    if player["left_game"]:
        # a leaver's token must not let them back into the room
        raise HTTPException(403, "you have left this room")
    # Backstop for the scheduled task: a process restart loses it, and a room
    # stuck behind a countdown that finished minutes ago is worse than a late
    # ending. Costs nothing when nothing is pending.
    if await resolve_pending_conclusion(code):
        await broadcast(code)
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

    # Poison and "I can't lose" are per-game state, like life: a counter from
    # last game would put someone one tick from dying before a card is drawn,
    # and a flag declared for a Platinum Angel that is no longer on the
    # battlefield would quietly make them unkillable for the rest of the night.
    q(
        "UPDATE players SET life = ?, eliminated = 0, poison = 0, cant_lose = 0 "
        "WHERE room_code = ? AND is_display = 0",
        (room["starting_life"], room["code"]),
    )
    if room["mode"] == "treachery" and first_row is not None:
        # House rule, not a format one: rule 907.6 gives every player the same
        # starting total and says nothing about the Leader. They start face up,
        # known to the table from turn one, and get focused accordingly — this
        # is the table's answer to that, not the variant's. `RulesSheet` says so
        # in the same words, because a summary that implied 907.6 said this
        # would be worse than no summary.
        leader_life = room["starting_life"] + LEADER_BONUS_LIFE
        q("UPDATE players SET life = ? WHERE id = ?", (leader_life, first_row["id"]))
        log_event(
            room["code"],
            f"{first_row['name']} starts on {leader_life} — the Leader carries "
            f"{LEADER_BONUS_LIFE} extra (house rule)",
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
        if not (player["is_display"] or player["is_tracker"]):
            raise HTTPException(
                403, "only the table display, or a player tracking for the table, "
                     "can adjust other players"
            )
        target = q(
            "SELECT * FROM players WHERE room_code = ? AND id = ? AND is_display = 0 AND left_game = 0",
            (room["code"], body.playerPid),
        ).fetchone()
        if not target:
            raise HTTPException(404, "player not found")
        who = "table display" if player["is_display"] else player["name"]
    else:
        if player["is_display"]:
            raise HTTPException(409, "the display has no life total — pass a player")
        target = player
        who = target["name"]
    old = target["life"] if target["life"] is not None else room["starting_life"]
    new = old + body.delta
    q("UPDATE players SET life = ? WHERE id = ?", (new, target["id"]))
    sign = "+" if body.delta > 0 else ""
    suffix = f" (by {who})" if who != target["name"] else ""
    log_event(room["code"], f"{target['name']}: {sign}{body.delta} life, {old} → {new}{suffix}")
    await revive_if_adjusted_back(room, target["id"])
    await check_auto_death(room, target["id"])
    await broadcast(room["code"])
    return {"ok": True, "life": new}


@router.post("/rooms/{code}/cmddmg")
async def commander_damage(code: str, body: CmdDamageBody, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if norm_status(room["status"]) != "playing":
        raise HTTPException(409, "no game in progress")
    # Who is taking the damage. A display holds no life of its own, so it can
    # only ever act on someone else — which is the whole point of the table
    # view being able to record commander damage at all.
    if body.defenderPid is not None and body.defenderPid != player["id"]:
        if not (player["is_display"] or player["is_tracker"]):
            raise HTTPException(
                403, "only the table display, or a player keeping score, "
                     "can record damage for another player"
            )
        defender = q(
            "SELECT * FROM players WHERE room_code = ? AND id = ? AND is_display = 0 "
            "AND left_game = 0",
            (room["code"], body.defenderPid),
        ).fetchone()
        if not defender:
            raise HTTPException(404, "player not found")
    else:
        if player["is_display"]:
            raise HTTPException(409, "displays don't take damage — name a defender")
        defender = player

    attacker = q(
        "SELECT * FROM players WHERE room_code = ? AND id = ? AND is_display = 0",
        (room["code"], body.attackerPid),
    ).fetchone()
    # self is a legal attacker: your own commander can be turned against you
    if not attacker:
        raise HTTPException(400, "invalid attacker")
    row = q(
        "SELECT amount FROM cmd_damage WHERE room_code = ? AND defender_id = ? AND attacker_id = ?",
        (room["code"], defender["id"], attacker["id"]),
    ).fetchone()
    old_amt = row["amount"] if row else 0
    delta = max(body.delta, -old_amt)  # can't undo below 0
    if delta == 0:
        return {"ok": True}
    new_amt = old_amt + delta
    q(
        "INSERT INTO cmd_damage (room_code, defender_id, attacker_id, amount) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(room_code, defender_id, attacker_id) DO UPDATE SET amount = ?",
        (room["code"], defender["id"], attacker["id"], new_amt, new_amt),
    )
    old_life = defender["life"] if defender["life"] is not None else room["starting_life"]
    new_life = old_life - delta  # commander damage is also real damage
    q("UPDATE players SET life = ? WHERE id = ?", (new_life, defender["id"]))
    by = "" if defender["id"] == player["id"] else (
        " (by the table display)" if player["is_display"] else f" (by {player['name']})"
    )
    log_event(
        room["code"],
        f"{defender['name']} took {delta} commander damage from {attacker['name']} "
        f"(total {new_amt}, life {old_life} → {new_life}){by}"
        if delta > 0
        else f"{defender['name']} undid {-delta} commander damage from {attacker['name']} "
        f"(total {new_amt}, life {old_life} → {new_life}){by}",
    )
    lethal_cmd = new_amt >= LETHAL_COMMANDER_DAMAGE
    # one call covers both ways this can kill: 21 from a single commander, and
    # the life the same damage just took
    await check_auto_death(room, defender["id"])
    await broadcast(room["code"])
    return {"ok": True, "total": new_amt, "life": new_life, "lethal": lethal_cmd}


@router.post("/rooms/{code}/poison")
async def adjust_poison(code: str, body: PoisonBody, x_player_token: str | None = Header(default=None)):
    """Poison counters, which only ever count up to ten.

    Kept apart from life rather than folded into it: they are a second, parallel
    clock on the same player, and a deck that wins with them never touches the
    first one.
    """
    room = get_room(code)
    player = get_player(code, x_player_token)
    if norm_status(room["status"]) != "playing":
        raise HTTPException(409, "no game in progress")
    if body.playerPid is not None and body.playerPid != player["id"]:
        if not (player["is_display"] or player["is_tracker"]):
            raise HTTPException(
                403, "only the table display, or a player tracking for the table, "
                     "can adjust other players"
            )
        target = q(
            "SELECT * FROM players WHERE room_code = ? AND id = ? AND is_display = 0 AND left_game = 0",
            (room["code"], body.playerPid),
        ).fetchone()
        if not target:
            raise HTTPException(404, "player not found")
        who = "table display" if player["is_display"] else player["name"]
    else:
        if player["is_display"]:
            raise HTTPException(409, "the display holds no counters — pass a player")
        target = player
        who = target["name"]
    old = target["poison"] or 0
    new = max(0, old + body.delta)  # a counter that goes negative is a bug, not a state
    if new == old:
        return {"ok": True, "poison": old}
    q("UPDATE players SET poison = ? WHERE id = ?", (new, target["id"]))
    suffix = f" (by {who})" if who != target["name"] else ""
    log_event(
        room["code"],
        f"{target['name']}: {old} → {new} poison{suffix}",
    )
    await check_auto_death(room, target["id"])
    await broadcast(room["code"])
    return {"ok": True, "poison": new}


@router.post("/rooms/{code}/eliminate")
async def eliminate(code: str, body: EliminateBody, x_player_token: str | None = Header(default=None)):
    room = get_room(code)
    player = get_player(code, x_player_token)
    if norm_status(room["status"]) != "playing":
        raise HTTPException(409, "no game in progress")
    if body.playerPid is not None and body.playerPid != player["id"]:
        if not (player["is_display"] or player["is_tracker"]):
            raise HTTPException(
                403, "only the table display, or a player keeping score, can do this "
                     "for another player"
            )
        target = q(
            "SELECT * FROM players WHERE room_code = ? AND id = ? AND is_display = 0 "
            "AND left_game = 0",
            (room["code"], body.playerPid),
        ).fetchone()
        if not target:
            raise HTTPException(404, "player not found")
    else:
        if player["is_display"]:
            raise HTTPException(409, "displays can't be eliminated — name a player")
        target = player

    player = target
    if body.undo:
        q("UPDATE players SET eliminated = 0, eliminated_at = NULL WHERE id = ?", (player["id"],))
        # An undo that leaves the counters lethal is not an undo: the next
        # change would kill them again, and the player would be arguing with
        # the app once per turn. So coming back from a death the counters
        # called also stops them calling it — and *only* then. Someone who was
        # decked at twenty life has nothing to suppress, and silently marking
        # them unable to lose would be inventing a board state.
        #
        # The server decides rather than the client asking, because every way
        # back in has the same problem: the player's own "I'm not dead", the
        # table display reviving someone whose phone died, all of them.
        revived = q("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
        if lethal_reason(room, revived):
            q("UPDATE players SET cant_lose = 1 WHERE id = ?", (player["id"],))
            log_event(
                room["code"],
                f"{player['name']} is not dead — the app will stop calling it",
            )
        else:
            log_event(room["code"], f"{player['name']} is back in the game")
        # whatever was counting down, it isn't happening now
        cancel_pending_conclusion(room["code"])
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


class TrackerBody(BaseModel):
    tracking: bool


class CantLoseBody(BaseModel):
    value: bool
    #: the table display, or a player keeping score, may set it for someone else
    playerPid: int | None = None


@router.post("/rooms/{code}/cantlose")
async def set_cant_lose(
    code: str, body: CantLoseBody, x_player_token: str | None = Header(default=None)
):
    """Mark a player as unable to lose, or mortal again.

    Some cards say you don't lose the game at zero life, or from commander
    damage. The app can't know which card is on the battlefield, so it stops
    asserting: the thresholds stop being highlighted for this player and only an
    explicit "I'm dead" ends their game. It is a display decision, not a rules
    engine.
    """
    room = get_room(code)
    player = get_player(code, x_player_token)
    if norm_status(room["status"]) != "playing":
        raise HTTPException(409, "no game in progress")

    if body.playerPid is not None and body.playerPid != player["id"]:
        if not (player["is_display"] or player["is_tracker"]):
            raise HTTPException(
                403, "only the table display, or a player keeping score, can set this "
                     "for another player"
            )
        target = q(
            "SELECT * FROM players WHERE room_code = ? AND id = ? AND is_display = 0 "
            "AND left_game = 0",
            (room["code"], body.playerPid),
        ).fetchone()
        if not target:
            raise HTTPException(404, "player not found")
    else:
        if player["is_display"]:
            raise HTTPException(409, "a display has no life of its own — name a player")
        target = player

    if bool(target["cant_lose"]) == body.value:
        return {"ok": True}
    q("UPDATE players SET cant_lose = ? WHERE id = ?", (1 if body.value else 0, target["id"]))
    log_event(
        room["code"],
        f"{target['name']} can't lose the game"
        if body.value
        else f"{target['name']} can lose the game again",
    )
    touch(room["code"])
    await broadcast(room["code"])
    return {"ok": True, "cantLose": body.value}


@router.post("/rooms/{code}/tracker")
async def set_tracker(code: str, body: TrackerBody, x_player_token: str | None = Header(default=None)):
    """Show the table view on a player's own phone, without giving up the seat.

    Distinct from `/display`, which turns a device into a dedicated display and
    discards its game state. A group with no spare tablet needs one player to
    keep the totals *while still playing*, and to be able to hand that job back
    mid-game — neither of which the display flag allows.

    Logged, because the table should know whose phone is keeping score.
    """
    room = get_room(code)
    player = get_player(code, x_player_token)
    if player["left_game"]:
        raise HTTPException(403, "you have left this room")
    if player["is_display"]:
        raise HTTPException(409, "this device is already the table display")
    if bool(player["is_tracker"]) == body.tracking:
        return {"ok": True}
    q("UPDATE players SET is_tracker = ? WHERE id = ?", (1 if body.tracking else 0, player["id"]))
    log_event(
        room["code"],
        f"{player['name']} is {'now keeping score for the table' if body.tracking else 'no longer keeping score'}",
    )
    touch(room["code"])
    await broadcast(room["code"])
    return {"ok": True, "tracking": body.tracking}


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
    if not (player["is_display"] or player["is_tracker"] or player["is_host"]):
        raise HTTPException(
            403,
            "only the table display, a player keeping score, or the host can "
            "rearrange seats",
        )
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
        "UPDATE players SET card_id = NULL, revealed = 0, life = NULL, eliminated = 0, "
        "poison = 0, cant_lose = 0 WHERE room_code = ?",
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
