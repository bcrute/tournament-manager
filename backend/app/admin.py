"""Admin surface.

The third surface of the app, alongside the table and the tournament. It is
unlisted — nothing links to it — but **that is not the control**. Obscurity is
not access control; the control is that every endpoint here requires an account
session whose username appears in `TABLE_ADMINS`.

Two deliberate choices:

- **Admin is configured by environment, not by a database flag.** A flag in the
  accounts table is one bad `UPDATE` (or one signup bug) away from privilege
  escalation. An env var can only be changed by whoever can already restart the
  process, which is the same person who owns the host.
- **Non-admins get 404, not 403.** A 403 confirms the surface exists and that
  the caller found a real endpoint. 404 tells a prober nothing. Admins are
  operating a known URL; nobody else needs a helpful error.

Every action that changes anything is written to `admin_log`. This surface is
the one place in the app with a genuine audit requirement: an admin acts on
other people's games, and those people cannot see it happening.
"""

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .accounts import current_account
from .audit import ADMIN_DENY, admin_action, security_event
from .db import q

router = APIRouter()


def admin_usernames() -> set[str]:
    """Read at call time, not import time, so the tests (and a restart) can
    change it without rebuilding the module graph."""
    raw = os.environ.get("TABLE_ADMINS", "")
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def require_admin(request: Request):
    """404 for everyone who isn't an admin — including signed-out callers.

    Deliberately indistinguishable from a route that doesn't exist.
    """
    allowed = admin_usernames()
    if not allowed:
        raise HTTPException(404, "Not Found")   # admin disabled entirely
    acct = current_account(request)
    if not acct or acct["username"].lower() not in allowed:
        # Someone reached an unlisted surface. Worth knowing about even though
        # the response gives them nothing.
        security_event(ADMIN_DENY, acct["username"] if acct else None, str(request.url.path))
        raise HTTPException(404, "Not Found")
    return acct


record = admin_action   # the writer lives in audit.py; this is the local name


# ---- read ----


@router.get("/overview")
def overview(request: Request):
    """One query set. Counts only — the admin surface deliberately does not
    show game contents or anyone's notes."""
    acct = require_admin(request)
    one = lambda sql, p=(): q(sql, p).fetchone()[0]  # noqa: E731
    return {
        "admin": acct["username"],
        "rooms": {
            "total": one("SELECT COUNT(*) FROM rooms"),
            "active": one("SELECT COUNT(*) FROM rooms WHERE status = 'playing'"),
            "lobby": one("SELECT COUNT(*) FROM rooms WHERE status = 'lobby'"),
        },
        "tournaments": {
            "total": one("SELECT COUNT(*) FROM tournaments"),
            "running": one("SELECT COUNT(*) FROM tournaments WHERE status = 'running'"),
        },
        "accounts": one("SELECT COUNT(*) FROM accounts"),
        "players": one("SELECT COUNT(*) FROM players WHERE left_game = 0"),
        "bans": one("SELECT COUNT(*) FROM bans WHERE until > unixepoch()"),
    }


@router.get("/rooms")
def rooms(request: Request, limit: int = 50):
    require_admin(request)
    rows = q(
        "SELECT r.code, r.status, r.mode, r.game_no, r.created_at, r.last_active, "
        "(SELECT COUNT(*) FROM players p WHERE p.room_code = r.code AND p.left_game = 0) AS players "
        "FROM rooms r ORDER BY COALESCE(r.last_active, r.created_at) DESC LIMIT ?",
        (min(limit, 200),),
    ).fetchall()
    return {"rooms": [dict(r) for r in rows]}


@router.get("/tournaments")
def tournaments(request: Request, limit: int = 50):
    require_admin(request)
    rows = q(
        "SELECT t.code, t.name, t.status, t.game, t.created_at, t.last_active, "
        "(SELECT COUNT(*) FROM entrants e WHERE e.tournament_code = t.code) AS entrants "
        "FROM tournaments t ORDER BY COALESCE(t.last_active, t.created_at) DESC LIMIT ?",
        (min(limit, 200),),
    ).fetchall()
    return {"tournaments": [dict(r) for r in rows]}


@router.get("/bans")
def bans(request: Request):
    require_admin(request)
    rows = q(
        "SELECT subject, until, strikes, last_strike FROM bans ORDER BY until DESC LIMIT 200"
    ).fetchall()
    # `subject` is a salted hash of an IP, never the address itself — there is
    # no way to display the IP here, by design.
    return {"bans": [dict(r) for r in rows]}


@router.get("/log")
def log(request: Request, limit: int = 100):
    """Admin actions only — deliberate, rare, and each one a decision."""
    require_admin(request)
    rows = q(
        "SELECT at, actor, action, target, detail FROM admin_log ORDER BY id DESC LIMIT ?",
        (min(limit, 500),),
    ).fetchall()
    return {"entries": [dict(r) for r in rows]}


@router.get("/security")
def security(request: Request, kind: str | None = None, limit: int = 200):
    """Security events — separate from the admin log because this one is mostly
    failures and would otherwise bury the actions worth reading."""
    require_admin(request)
    if kind:
        rows = q(
            "SELECT at, kind, subject, detail FROM security_log WHERE kind = ? "
            "ORDER BY id DESC LIMIT ?",
            (kind, min(limit, 1000)),
        ).fetchall()
    else:
        rows = q(
            "SELECT at, kind, subject, detail FROM security_log ORDER BY id DESC LIMIT ?",
            (min(limit, 1000),),
        ).fetchall()
    counts = q(
        "SELECT kind, COUNT(*) AS n FROM security_log WHERE at > unixepoch() - 86400 "
        "GROUP BY kind ORDER BY n DESC"
    ).fetchall()
    return {"entries": [dict(r) for r in rows], "last24h": [dict(c) for c in counts]}


# ---- act ----


class ReasonBody(BaseModel):
    reason: str | None = None


@router.post("/bans/{subject}/lift")
def lift_ban(subject: str, body: ReasonBody, request: Request):
    """Clear a ban and its strike history. Expiry alone keeps history so repeat
    offenders escalate; lifting is the explicit 'this was a mistake' path."""
    acct = require_admin(request)
    if not q("SELECT 1 FROM bans WHERE subject = ?", (subject,)).fetchone():
        raise HTTPException(404, "no such ban")
    q("DELETE FROM bans WHERE subject = ?", (subject,))
    record(acct["username"], "ban.lift", subject, body.reason)
    return {"ok": True}


@router.post("/rooms/{code}/close")
def close_room(code: str, body: ReasonBody, request: Request):
    """End a stuck room. Does not delete it — players keep their history, and
    an admin quietly erasing a game is exactly what the log exists to prevent."""
    acct = require_admin(request)
    code = code.upper()
    if not q("SELECT 1 FROM rooms WHERE code = ?", (code,)).fetchone():
        raise HTTPException(404, "no such room")
    q("UPDATE rooms SET status = 'ended' WHERE code = ?", (code,))
    record(acct["username"], "room.close", code, body.reason)
    return {"ok": True}


@router.post("/tournaments/{code}/end")
def end_tournament(code: str, body: ReasonBody, request: Request):
    """End an event an organizer abandoned. Standings are left intact."""
    acct = require_admin(request)
    code = code.upper()
    if not q("SELECT 1 FROM tournaments WHERE code = ?", (code,)).fetchone():
        raise HTTPException(404, "no such tournament")
    q("UPDATE tournaments SET status = 'ended' WHERE code = ?", (code,))
    q(
        "UPDATE trounds SET status = 'closed' WHERE tournament_code = ? AND status = 'active'",
        (code,),
    )
    record(acct["username"], "tournament.end", code, body.reason)
    return {"ok": True}
