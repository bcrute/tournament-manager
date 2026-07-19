"""Optional accounts.

Deliberately minimal on personal data: a username and a password are the only
required fields. Email is optional and used for nothing but recovery, which
also works without it via one-time recovery codes issued at signup.

Passwords use scrypt from the standard library — memory-hard, no extra
dependency to audit or keep patched.
"""

import base64
import hashlib
import hmac
import re
import secrets
import time

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .audit import AUTH_FAIL, AUTH_UNKNOWN_USER, security_event
from .db import q

router = APIRouter()

SESSION_COOKIE = "table_session"
SESSION_DAYS = 90
# A session unused for this long is dead even if its absolute expiry is far off,
# so a stolen cookie has a bounded life rather than the full 90 days.
SESSION_IDLE_DAYS = 30
RECOVERY_CODE_COUNT = 8
# `@` and `+` are permitted so an email address can be used as a username. We
# discourage it — see the note in signup — but the choice is the user's, and a
# regex that silently refuses is a worse experience than a clear warning.
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.+@-]{3,64}$")

# scrypt parameters: ~64 MB of memory per hash, which is the point.
_SCRYPT = {"n": 2**16, "r": 8, "p": 1, "maxmem": 96 * 1024 * 1024}


# ---- password and code hashing ----


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${}${}".format(
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode()
    )


# A hash of a value nobody knows, used to spend the same scrypt time when no
# account matches. Without it, "no such user" returns in microseconds while a
# real username costs ~100ms of KDF — which enumerates accounts by stopwatch,
# whatever the response body says.
_ABSENT_ACCOUNT_HASH: str | None = None


def _absent_account_hash() -> str:
    global _ABSENT_ACCOUNT_HASH
    if _ABSENT_ACCOUNT_HASH is None:
        _ABSENT_ACCOUNT_HASH = hash_password(secrets.token_urlsafe(32))
    return _ABSENT_ACCOUNT_HASH


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    dk = hashlib.scrypt(password.encode(), salt=salt, dklen=len(expected), **_SCRYPT)
    return hmac.compare_digest(dk, expected)


def _token_hash(token: str) -> str:
    """Sessions and recovery codes are stored hashed, so a database copy alone
    doesn't let anyone log in."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---- sessions ----


def _new_session(account_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + SESSION_DAYS * 86400
    q(
        "INSERT INTO sessions (token_hash, account_id, last_seen, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), account_id, int(time.time()), expires),
    )
    return token


def _set_cookie(response: Response, token: str):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,  # unreachable from JavaScript
        secure=True,
        samesite="lax",
        path="/",
    )


def account_for_session(token: str | None):
    """Account row for a session cookie, or None. Never raises — anonymous use
    is a first-class path through the whole app."""
    if not token:
        return None
    row = q(
        "SELECT a.*, s.expires_at, s.last_seen AS session_last_seen "
        "FROM sessions s JOIN accounts a ON a.id = s.account_id "
        "WHERE s.token_hash = ?",
        (_token_hash(token),),
    ).fetchone()
    if not row:
        return None
    now = time.time()
    # note: a.* also carries accounts.last_seen, so the session's is aliased
    if row["session_last_seen"] and now - row["session_last_seen"] > SESSION_IDLE_DAYS * 86400:
        q("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        return None
    # cheap enough at this scale, and without it last_seen is written once at
    # creation and never again, which makes idle expiry meaningless
    q("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (int(now), _token_hash(token)))
    if row["expires_at"] <= now:
        q("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        return None
    return row


def current_account(request: Request):
    """Optional account for any request. Room endpoints use this to link a seat
    to an account when someone happens to be signed in."""
    return account_for_session(request.cookies.get(SESSION_COOKIE))


def require_account(request: Request):
    acct = current_account(request)
    if acct is None:
        raise HTTPException(401, "sign in first")
    return acct


# ---- request bodies ----


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=200)


class SignupBody(Credentials):
    #: optional at signup, exactly as it is afterwards. Recovery codes are the
    #: working recovery path either way — see the note in the signup handler.
    email: str | None = None


class EmailBody(BaseModel):
    email: str | None = Field(default=None, max_length=200)


class PasswordChange(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=8, max_length=200)


class RecoverBody(BaseModel):
    username: str
    code: str
    new_password: str = Field(min_length=8, max_length=200)


class NoteBody(BaseModel):
    text: str = Field(max_length=10_000)


class DeleteBody(BaseModel):
    confirm: str


# ---- account lifecycle ----


def _issue_recovery_codes(account_id: int) -> list[str]:
    q("DELETE FROM recovery_codes WHERE account_id = ?", (account_id,))
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        code = "-".join(secrets.token_hex(2) for _ in range(3))
        codes.append(code)
        q(
            "INSERT INTO recovery_codes (account_id, code_hash) VALUES (?, ?)",
            (account_id, _token_hash(code)),
        )
    return codes


def _public(acct) -> dict:
    return {
        "username": acct["username"],
        "hasEmail": bool(acct["email"]),
        "createdAt": acct["created_at"],
    }


@router.post("/signup")
def signup(body: SignupBody, response: Response):
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            400, "usernames are 3-64 characters: letters, numbers, and . _ - + @"
        )
    if q("SELECT 1 FROM accounts WHERE username = ?", (username,)).fetchone():
        raise HTTPException(409, "that username is taken")
    email = (body.email or "").strip() or None
    if email and ("@" not in email or len(email) < 5):
        raise HTTPException(400, "that doesn't look like an email address")
    cur = q(
        "INSERT INTO accounts (username, pw_hash, email) VALUES (?, ?, ?)",
        (username, hash_password(body.password), email),
    )
    account_id = cur.lastrowid
    codes = _issue_recovery_codes(account_id)
    _set_cookie(response, _new_session(account_id))
    acct = q("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    # the only time these are ever shown
    return {"account": _public(acct), "recoveryCodes": codes}


@router.post("/login")
def login(body: Credentials, response: Response):
    acct = q("SELECT * FROM accounts WHERE username = ?", (body.username.strip(),)).fetchone()
    # Same error *and* the same work either way: verifying against a throwaway
    # hash when the account is absent keeps the timing indistinguishable.
    if not acct:
        verify_password(body.password, _absent_account_hash())
        # separate kind: a burst against names that don't exist is enumeration,
        # a burst against one that does is a brute-force. Same response, and
        # the log is where the difference lives.
        # Record that an unknown name was tried, but not the name itself when
        # it looks like an address — someone using their email as a username
        # would otherwise have it written to the security log on every typo.
        attempted = body.username.strip()
        security_event(
            AUTH_UNKNOWN_USER,
            "<email-shaped>" if "@" in attempted else attempted[:64],
        )
        raise HTTPException(401, "wrong username or password")
    if not verify_password(body.password, acct["pw_hash"]):
        security_event(AUTH_FAIL, acct["username"], "password")
        raise HTTPException(401, "wrong username or password")
    q("UPDATE accounts SET last_seen = unixepoch() WHERE id = ?", (acct["id"],))
    _set_cookie(response, _new_session(acct["id"]))
    return {"account": _public(acct)}


@router.post("/logout")
def logout(response: Response, table_session: str | None = Cookie(default=None)):
    if table_session:
        q("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(table_session),))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    acct = current_account(request)
    return {"account": _public(acct) if acct else None}


@router.post("/email")
def set_email(body: EmailBody, request: Request):
    """Optional. Stored only so an account can be recovered."""
    acct = require_account(request)
    email = (body.email or "").strip() or None
    if email and ("@" not in email or len(email) < 5):
        raise HTTPException(400, "that doesn't look like an email address")
    q("UPDATE accounts SET email = ? WHERE id = ?", (email, acct["id"]))
    return {"ok": True, "hasEmail": bool(email)}


@router.post("/password")
def change_password(body: PasswordChange, request: Request):
    acct = require_account(request)
    if not verify_password(body.current, acct["pw_hash"]):
        raise HTTPException(403, "current password is wrong")
    q("UPDATE accounts SET pw_hash = ? WHERE id = ?", (hash_password(body.new), acct["id"]))
    # every other device is logged out
    q("DELETE FROM sessions WHERE account_id = ?", (acct["id"],))
    return {"ok": True}


@router.post("/recovery-codes")
def regenerate_codes(request: Request):
    acct = require_account(request)
    return {"recoveryCodes": _issue_recovery_codes(acct["id"])}


@router.post("/recover")
def recover(body: RecoverBody, response: Response):
    """Recover using a one-time code — no email needed."""
    acct = q("SELECT * FROM accounts WHERE username = ?", (body.username.strip(),)).fetchone()
    if not acct:
        raise HTTPException(401, "wrong username or code")
    row = q(
        "SELECT * FROM recovery_codes WHERE account_id = ? AND code_hash = ? AND used_at IS NULL",
        (acct["id"], _token_hash(body.code.strip())),
    ).fetchone()
    if not row:
        raise HTTPException(401, "wrong username or code")
    q(
        "UPDATE recovery_codes SET used_at = unixepoch() WHERE account_id = ? AND code_hash = ?",
        (acct["id"], _token_hash(body.code.strip())),
    )
    q("UPDATE accounts SET pw_hash = ? WHERE id = ?", (hash_password(body.new_password), acct["id"]))
    q("DELETE FROM sessions WHERE account_id = ?", (acct["id"],))
    _set_cookie(response, _new_session(acct["id"]))
    return {"account": _public(acct)}


@router.post("/delete")
def delete_account(body: DeleteBody, request: Request, response: Response):
    """Erase the account. Typing the username is required so this can't happen
    by accident.

    What goes: the account, its sessions, recovery codes and private notes.
    What stays: the games themselves, unlinked. Other players at those tables
    have their own record of what happened, and the seat only ever held a
    display name — after unlinking, nothing ties it to a person.
    """
    acct = require_account(request)
    if body.confirm.strip().lower() != acct["username"].lower():
        raise HTTPException(400, "type your username exactly to confirm")

    # keep shared game history intact, but strip the link to this person
    q("UPDATE players SET account_id = NULL WHERE account_id = ?", (acct["id"],))
    # notes, sessions and recovery codes go with the account (ON DELETE CASCADE)
    q("DELETE FROM accounts WHERE id = ?", (acct["id"],))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


# ---- history and notes ----


@router.get("/history")
def history(request: Request, limit: int = 50):
    """Games this account sat in, newest first."""
    acct = require_account(request)
    rows = q(
        "SELECT p.room_code, p.name, p.life, p.eliminated, p.joined_at, "
        "       r.mode, r.status, r.game_no, "
        "       (SELECT text FROM notes n WHERE n.account_id = p.account_id "
        "          AND n.room_code = p.room_code AND n.game_no = r.game_no) AS note "
        "FROM players p JOIN rooms r ON r.code = p.room_code "
        "WHERE p.account_id = ? AND p.is_display = 0 "
        "ORDER BY p.joined_at DESC LIMIT ?",
        (acct["id"], max(1, min(limit, 200))),
    ).fetchall()
    return {
        "games": [
            {
                "roomCode": r["room_code"],
                "playedAs": r["name"],
                "mode": r["mode"],
                "status": r["status"],
                "gameNo": r["game_no"],
                "life": r["life"],
                "eliminated": bool(r["eliminated"]),
                "at": r["joined_at"],
                "note": r["note"],
            }
            for r in rows
        ]
    }


@router.get("/notes")
def list_notes(request: Request):
    acct = require_account(request)
    rows = q(
        "SELECT room_code, game_no, text, updated_at FROM notes WHERE account_id = ? "
        "ORDER BY updated_at DESC",
        (acct["id"],),
    ).fetchall()
    return {
        "notes": [
            {
                "roomCode": r["room_code"],
                "gameNo": r["game_no"],
                "text": r["text"],
                "updatedAt": r["updated_at"],
            }
            for r in rows
        ]
    }


@router.get("/notes/{code}/{game_no}")
def get_note(code: str, game_no: int, request: Request):
    acct = require_account(request)
    row = q(
        "SELECT text, updated_at FROM notes WHERE account_id = ? AND room_code = ? AND game_no = ?",
        (acct["id"], code.upper(), game_no),
    ).fetchone()
    return {"text": row["text"] if row else "", "updatedAt": row["updated_at"] if row else None}


@router.put("/notes/{code}/{game_no}")
def save_note(code: str, game_no: int, body: NoteBody, request: Request):
    acct = require_account(request)
    text = body.text.strip()
    if not text:
        q(
            "DELETE FROM notes WHERE account_id = ? AND room_code = ? AND game_no = ?",
            (acct["id"], code.upper(), game_no),
        )
        return {"ok": True, "deleted": True}
    q(
        "INSERT INTO notes (account_id, room_code, game_no, text) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(account_id, room_code, game_no) DO UPDATE SET "
        "text = excluded.text, updated_at = unixepoch()",
        (acct["id"], code.upper(), game_no, text),
    )
    return {"ok": True}
