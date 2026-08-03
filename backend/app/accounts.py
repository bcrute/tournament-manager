"""Optional accounts.

Deliberately minimal on personal data: a username and a password are the only
required fields. Email is optional and used for nothing but recovery, which
also works without it via one-time recovery codes issued at signup.

An address only counts once it has been **confirmed**. Before 2026-08-02 one
was typed into a box, stored, never checked and never used — so `hasEmail` was
a claim about a text field rather than about a mailbox anyone could reach, and
hosting a tournament (which exists to stop an organizer being locked out
mid-event) rested on it. `hasEmail` now means the owner clicked a link sent to
that address. Every address already on file became unverified in the same
change: they were never checked, and grandfathering them in would have kept
making exactly the claim this stopped making.

Passwords use scrypt from the standard library — memory-hard, no extra
dependency to audit or keep patched.
"""

import base64
import hashlib
import hmac
import re
import secrets
import time

from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .audit import AUTH_FAIL, AUTH_UNKNOWN_USER, security_event
from .db import q
from .mail import MailNotConfigured, Message, get_mailer, mail_configured, public_base_url

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
# The table caps a display name at 24 characters (`table.py`'s join bodies), and
# a default that the table would reject is worse than no default at all.
DISPLAY_NAME_MAX = 24

# How long a link in an email is good for. A verification link is a
# convenience and gets a generous day — the worst case for a stale one is
# clicking it and being told to ask for another. A reset link is a password, so
# it gets an hour: long enough to walk to a computer, short enough that an
# address compromised tomorrow is not an account compromised tomorrow.
VERIFY_TTL = 24 * 3600
RESET_TTL = 3600

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
    """Username and password. Nothing else.

    A recovery email used to be offered here. It is account state with security
    consequences — it is the address a reset would be sent to — and collecting
    it at the one moment nobody can yet prove they own it meant an unverified
    string was doing a credential's job. Enrolling one is its own workflow now,
    behind the account's password.

    Deliberately no `email` field: a stale client still sending one is ignored
    by Pydantic rather than quietly storing it.
    """


class EmailBody(BaseModel):
    """Setting or clearing the recovery address.

    The password is required for both. A session cookie proves this browser was
    signed in once; the recovery address is the thing that can hand the account
    to whoever holds it, so pointing it somewhere else — or removing it so the
    owner cannot use it — is a takeover step, not a preference. Same reasoning
    as the username change above.
    """

    email: str | None = Field(default=None, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class VerifyEmailBody(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ForgotBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class ResetBody(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class UsernameChange(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    #: renaming is confirmed with the password, not just the session — see the
    #: handler for why a cookie alone is not enough here
    password: str = Field(min_length=1, max_length=200)


class DisplayNameBody(BaseModel):
    #: empty or absent clears it, which puts the device's own last name back in
    #: charge rather than leaving the field stuck on an old value
    displayName: str | None = Field(default=None, max_length=DISPLAY_NAME_MAX)


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


def _reload(account_id: int):
    """Re-read after a write, so a response never describes the row as it was."""
    return q("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()


def _public(acct) -> dict:
    return {
        "username": acct["username"],
        # the name this account brings to a table; null means the device decides
        "displayName": acct["display_name"],
        # `hasEmail` means confirmed, and nothing else reads as confirmed.
        # Anything gating on a recovery address gates on this one field, so
        # there is no second place to forget the distinction.
        "hasEmail": bool(acct["email"] and acct["email_verified_at"]),
        # Whether a confirmation is outstanding — but never the address itself.
        # `TestRecoveryEmailIsWriteOnly` pins that no endpoint returns it, and
        # that survives this feature: the address is a takeover target in its
        # own right and a stolen session cookie should not yield it. The client
        # already knows the address it just submitted, so the one screen that
        # wants to echo it can, without the server ever saying it back.
        "emailPending": bool(acct["email"] and not acct["email_verified_at"]),
        "createdAt": acct["created_at"],
        # so the UI can say *why* the address cannot be confirmed rather than
        # showing a form that will 503
        "mailConfigured": mail_configured(),
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
    # No email column in this INSERT, on purpose. A brand-new account has no
    # recovery address at all until one is enrolled and confirmed; the recovery
    # codes below are what stands between the owner and a lost password until
    # then, which is why they are still issued and still shown once.
    cur = q(
        "INSERT INTO accounts (username, pw_hash) VALUES (?, ?)",
        (username, hash_password(body.password)),
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


# ---- recovery email ----


def _valid_email(value: str) -> bool:
    """Deliberately loose. The only check that means anything is whether a
    message sent to the address arrives and gets clicked, and that check is the
    whole flow below — a stricter regex here would reject valid addresses in
    exchange for nothing, since an invalid one simply never confirms."""
    if len(value) < 5 or len(value) > 200 or value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    return bool(local) and "." in domain and not domain.startswith(".") and " " not in value


def _mint_verification(account_id: int, email: str) -> str:
    """One live verification link per account. Asking for a new one retires the
    old, so a link forwarded or left in an old inbox stops working the moment
    the owner asks again."""
    q("DELETE FROM email_verifications WHERE account_id = ?", (account_id,))
    token = secrets.token_urlsafe(32)
    q(
        "INSERT INTO email_verifications (token_hash, account_id, email, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (_token_hash(token), account_id, email, int(time.time()) + VERIFY_TTL),
    )
    return token


def _mint_reset(account_id: int) -> str:
    q("DELETE FROM password_resets WHERE account_id = ?", (account_id,))
    token = secrets.token_urlsafe(32)
    q(
        "INSERT INTO password_resets (token_hash, account_id, expires_at) VALUES (?, ?, ?)",
        (_token_hash(token), account_id, int(time.time()) + RESET_TTL),
    )
    return token


def _link(path: str, token: str) -> str:
    """Links put the token in a **fragment**, for the same reason a room
    invitation does: a fragment is never transmitted to a server, so the
    credential in an emailed link cannot reach an access log — not ours, and
    not a corporate mail gateway's link-rewriter either."""
    return f"{public_base_url()}{path}#{token}"


def _send(background: BackgroundTasks, message: Message) -> None:
    """Queued rather than awaited, and that is a security property as much as a
    latency one: `/forgot` must take the same time whether or not the username
    exists, and an SMTP round trip on one branch only would enumerate accounts
    by stopwatch however carefully the response bodies match."""

    def deliver():
        try:
            get_mailer().send(message)
        except Exception:  # noqa: BLE001 - a dead SMTP host must not raise here
            # Deliberately swallowed. By the time this runs the response has
            # been sent, so there is nobody to raise to; and the failure a user
            # experiences (no email arrives) is the same one they would
            # experience from a full mailbox, which is what the "send it again"
            # button is for. `/email` checks the transport is configured *before*
            # responding, which is the failure worth reporting synchronously.
            pass

    background.add_task(deliver)


def _require_mail() -> None:
    if not mail_configured():
        raise HTTPException(
            503,
            "this deployment cannot send email yet, so a recovery address "
            "cannot be confirmed — your recovery codes still work",
        )


@router.post("/email")
def set_email(body: EmailBody, request: Request, background: BackgroundTasks):
    """Enrol, replace, or remove the recovery address.

    Enrolling never trusts the address: it is stored unconfirmed and a link is
    sent to it. Until that link is clicked the account has no recovery address
    as far as anything that matters is concerned — `hasEmail` is false and
    hosting is refused.
    """
    acct = require_account(request)
    if not verify_password(body.password, acct["pw_hash"]):
        security_event(AUTH_FAIL, acct["username"], "email-change")
        raise HTTPException(403, "your password is wrong")

    email = (body.email or "").strip() or None
    if email is None:
        q(
            "UPDATE accounts SET email = NULL, email_verified_at = NULL WHERE id = ?",
            (acct["id"],),
        )
        q("DELETE FROM email_verifications WHERE account_id = ?", (acct["id"],))
        # Any live reset link went to the address just removed, so it dies with
        # it — otherwise removing a compromised address would leave the way in
        # that made it worth removing.
        q("DELETE FROM password_resets WHERE account_id = ?", (acct["id"],))
        return {"ok": True, **_public(_reload(acct["id"]))}

    if not _valid_email(email):
        raise HTTPException(400, "that doesn't look like an email address")
    _require_mail()

    q(
        "UPDATE accounts SET email = ?, email_verified_at = NULL WHERE id = ?",
        (email, acct["id"]),
    )
    q("DELETE FROM password_resets WHERE account_id = ?", (acct["id"],))
    token = _mint_verification(acct["id"], email)
    _send(
        background,
        Message(
            to=email,
            subject="Confirm your recovery address",
            body=(
                f"Someone added this address to the account \"{acct['username']}\".\n\n"
                f"Confirm it:\n{_link('/account/verify', token)}\n\n"
                "The link is good for 24 hours. If this wasn't you, ignore this "
                "message — nothing changes until the link is used."
            ),
        ),
    )
    return {"ok": True, "sent": True, **_public(_reload(acct["id"]))}


@router.post("/email/resend")
def resend_verification(request: Request, background: BackgroundTasks):
    """Send the confirmation again. No password: the address is already on file
    and it cost a password to put there, so this can only re-send to somewhere
    the owner already chose."""
    acct = require_account(request)
    if not acct["email"]:
        raise HTTPException(400, "there is no address to confirm")
    if acct["email_verified_at"]:
        return {"ok": True, "sent": False, **_public(acct)}
    _require_mail()
    token = _mint_verification(acct["id"], acct["email"])
    _send(
        background,
        Message(
            to=acct["email"],
            subject="Confirm your recovery address",
            body=(
                f"Confirming the recovery address for \"{acct['username']}\":\n"
                f"{_link('/account/verify', token)}\n\n"
                "The link is good for 24 hours."
            ),
        ),
    )
    return {"ok": True, "sent": True, **_public(acct)}


@router.post("/email/verify")
def verify_email(body: VerifyEmailBody):
    """Confirm an address.

    No session required, deliberately: the link is opened from an inbox, which
    is routinely a different browser or a different device from the one that
    asked. The token is the authorization, which is why it is 256 bits, stored
    only as a hash, single-use, and expires.
    """
    row = q(
        "SELECT * FROM email_verifications WHERE token_hash = ?",
        (_token_hash(body.token),),
    ).fetchone()
    now = int(time.time())
    if not row or row["used_at"] or row["expires_at"] < now:
        # One message for all three cases. Distinguishing "expired" from "never
        # existed" tells someone holding a stolen token which of their guesses
        # was once real.
        raise HTTPException(400, "that link is no longer valid — ask for a new one")
    acct = q("SELECT * FROM accounts WHERE id = ?", (row["account_id"],)).fetchone()
    if not acct or (acct["email"] or "").lower() != row["email"].lower():
        # The address changed after the link was sent, so this token confirms
        # an address the account no longer claims.
        raise HTTPException(400, "that link is no longer valid — ask for a new one")
    q("UPDATE email_verifications SET used_at = ? WHERE token_hash = ?", (now, row["token_hash"]))
    q("UPDATE accounts SET email_verified_at = ? WHERE id = ?", (now, acct["id"]))
    return {"ok": True, **_public(_reload(acct["id"]))}


@router.post("/forgot")
def forgot_password(body: ForgotBody, background: BackgroundTasks):
    """Start a password reset.

    Always the same answer. Whether the username exists, whether it has an
    address, and whether that address is confirmed are all things this endpoint
    must not reveal — `/login` goes to real trouble (a throwaway scrypt
    verification) to avoid leaking the first of those, and an honest
    "no account by that name" here would hand it over for free.
    """
    username = body.username.strip()
    acct = q("SELECT * FROM accounts WHERE username = ?", (username,)).fetchone()
    if acct and acct["email"] and acct["email_verified_at"] and mail_configured():
        token = _mint_reset(acct["id"])
        _send(
            background,
            Message(
                to=acct["email"],
                subject="Reset your password",
                body=(
                    f"A password reset was requested for \"{acct['username']}\".\n\n"
                    f"Choose a new password:\n{_link('/account/reset', token)}\n\n"
                    "The link is good for one hour and can be used once. If this "
                    "wasn't you, ignore this message — your password has not changed."
                ),
            ),
        )
    else:
        # Logged, because a run of these against names that don't exist is the
        # same enumeration signal `/login` records, and the response above is
        # deliberately blind to it.
        security_event(
            AUTH_UNKNOWN_USER,
            "<email-shaped>" if "@" in username else username[:64],
            "forgot-password",
        )
    return {
        "ok": True,
        "message": "If that account exists and has a confirmed recovery address, "
        "a reset link is on its way.",
    }


@router.post("/reset")
def reset_password(body: ResetBody, response: Response):
    """Finish a password reset.

    Ends every session, like `/password` does, because the reason someone is
    here is usually that somebody else might be signed in.
    """
    row = q(
        "SELECT * FROM password_resets WHERE token_hash = ?", (_token_hash(body.token),)
    ).fetchone()
    now = int(time.time())
    if not row or row["used_at"] or row["expires_at"] < now:
        raise HTTPException(400, "that link is no longer valid — ask for a new one")
    acct = q("SELECT * FROM accounts WHERE id = ?", (row["account_id"],)).fetchone()
    if not acct:
        raise HTTPException(400, "that link is no longer valid — ask for a new one")
    q("UPDATE password_resets SET used_at = ? WHERE token_hash = ?", (now, row["token_hash"]))
    q("UPDATE accounts SET pw_hash = ? WHERE id = ?", (hash_password(body.password), acct["id"]))
    q("DELETE FROM sessions WHERE account_id = ?", (acct["id"],))
    # Signed straight in: they have just proved control of the recovery address
    # and chosen a password, and making them type it again immediately proves
    # nothing. Matches what `/recover` does with a recovery code.
    _set_cookie(response, _new_session(acct["id"]))
    return {"account": _public(_reload(acct["id"]))}


@router.post("/username")
def change_username(body: UsernameChange, request: Request):
    """Rename the account.

    The password is required as well as the session. A session cookie proves
    "this browser was signed in at some point"; changing the name someone signs
    in with is the first move in taking an account over, and it is the one
    change the real owner cannot undo by themselves — they'd no longer know
    what to type. Everywhere else a stolen cookie can only read.

    Sessions survive: the account is the same account, and logging the owner
    out of their other devices for choosing a new name would punish the
    ordinary case to no benefit.
    """
    acct = require_account(request)
    if not verify_password(body.password, acct["pw_hash"]):
        security_event(AUTH_FAIL, acct["username"], "username-change")
        raise HTTPException(403, "your password is wrong")
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            400, "usernames are 3-64 characters: letters, numbers, and . _ - + @"
        )
    # unchanged-but-for-case is a rename to yourself; the UNIQUE index is
    # NOCASE, so without this exemption "ada" -> "Ada" would collide with itself
    clash = q(
        "SELECT 1 FROM accounts WHERE username = ? AND id != ?", (username, acct["id"])
    ).fetchone()
    if clash:
        raise HTTPException(409, "that username is taken")
    q("UPDATE accounts SET username = ? WHERE id = ?", (username, acct["id"]))
    return {"account": _public(q("SELECT * FROM accounts WHERE id = ?", (acct["id"],)).fetchone())}


@router.post("/display-name")
def set_display_name(body: DisplayNameBody, request: Request):
    """The name pre-filled when this account sits down at a table.

    Cosmetic and public by nature — the other players read it off the table —
    so unlike the username it needs no password and has no uniqueness rule. Two
    people called Grumpy Platypus 42 is a joke, not a collision: seats are
    identified by token, never by name.
    """
    acct = require_account(request)
    name = (body.displayName or "").strip()
    if len(name) > DISPLAY_NAME_MAX:
        raise HTTPException(400, f"table names are at most {DISPLAY_NAME_MAX} characters")
    q("UPDATE accounts SET display_name = ? WHERE id = ?", (name or None, acct["id"]))
    return {"ok": True, "displayName": name or None}


@router.post("/password")
def change_password(body: PasswordChange, request: Request):
    """Change the password and end **every** session, this one included.

    Note what that means: the caller is signed out by their own successful
    request, and their next call returns 401. That is deliberate and pinned by
    `test_changing_password_logs_other_devices_out` — but the neighbouring
    comment used to read "every other device", which is not what the code does,
    and `/recover` takes the opposite line (it drops every session and then
    issues a fresh one for the caller). The two are worth reconciling; until
    someone does, this is the behaviour, and the settings screen tells the user
    they will have to sign in again rather than discovering it on the next
    request.
    """
    acct = require_account(request)
    if not verify_password(body.current, acct["pw_hash"]):
        raise HTTPException(403, "current password is wrong")
    q("UPDATE accounts SET pw_hash = ? WHERE id = ?", (hash_password(body.new), acct["id"]))
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


@router.get("/stats")
def stats(request: Request):
    """Totals across everything this account has played.

    Counted over the whole history rather than the page `/history` returns, so
    the numbers don't quietly shrink to the size of a list.

    A "game" here is one seat at one room, exactly as in `/history` — a room can
    run several games from one seat, so this counts times you sat down, which is
    the number the seat rows can actually support. Nothing here is a win rate:
    the life counter records who was eliminated, not who won, and inferring one
    from the other would be a statistic the data doesn't hold.
    """
    acct = require_account(request)
    row = q(
        "SELECT COUNT(*) AS games, COUNT(DISTINCT p.room_code) AS tables, "
        "       MIN(p.joined_at) AS first_at, MAX(p.joined_at) AS last_at, "
        "       SUM(p.eliminated) AS eliminated "
        "FROM players p WHERE p.account_id = ? AND p.is_display = 0",
        (acct["id"],),
    ).fetchone()
    modes = q(
        "SELECT r.mode, COUNT(*) AS n FROM players p JOIN rooms r ON r.code = p.room_code "
        "WHERE p.account_id = ? AND p.is_display = 0 GROUP BY r.mode",
        (acct["id"],),
    ).fetchall()
    notes = q(
        "SELECT COUNT(*) AS n FROM notes WHERE account_id = ?", (acct["id"],)
    ).fetchone()
    return {
        "games": row["games"] or 0,
        "tables": row["tables"] or 0,
        "eliminated": row["eliminated"] or 0,
        "notes": notes["n"] or 0,
        "firstAt": row["first_at"],
        "lastAt": row["last_at"],
        "byMode": {m["mode"]: m["n"] for m in modes},
        "memberSince": acct["created_at"],
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
