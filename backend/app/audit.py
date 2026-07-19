"""Audit trails, kept apart by purpose.

Three logs, because they answer three different questions, have different
readers, and different retention:

- **`events`** (in `table.py`) — *what happened in this game?* Read by players,
  scoped to a room, dies with it.
- **`admin_log`** — *what did an operator do?* Read when something looks wrong
  or after an incident. Every entry is a deliberate privileged action.
- **`security_log`** — *is someone attacking us?* Read when investigating. Full
  of failures by nature, most of them noise.

Combining them would ruin all three. A security log full of ordinary gameplay
stops being read; an admin log full of rejected probes hides the one real
action; a player's game history should never carry either.

**Nothing here ever records a secret.** No tokens, passwords, recovery codes,
or raw IP addresses — clients are identified by the same salted hash the rate
limiter uses, which is pseudonymous, not anonymous.
"""

import time

from .db import q

#: security events are noise-heavy and lose value fast
SECURITY_RETENTION_DAYS = 30
#: admin actions are rare and worth keeping
ADMIN_RETENTION_DAYS = 365


def admin_action(actor: str, action: str, target: str | None = None, reason: str | None = None):
    """A privileged action an operator took. Only ever called after the action
    succeeded — a log full of attempts hides the one that mattered."""
    q(
        "INSERT INTO admin_log (actor, action, target, detail) VALUES (?, ?, ?, ?)",
        (actor, action, target, reason),
    )


def security_event(kind: str, subject: str | None = None, detail: str | None = None):
    """Something that might be an attack, or might be someone fat-fingering a
    password. Both are recorded; telling them apart is the reader's job.

    `subject` MUST already be a salted client id (see `limits.client_id`) or an
    account username — never an address.
    """
    q(
        "INSERT INTO security_log (kind, subject, detail) VALUES (?, ?, ?)",
        (kind, subject, detail),
    )


# Kinds, kept as constants so a typo doesn't silently create a new category
# that nobody queries for.
AUTH_FAIL = "auth.fail"                 # wrong password, bad recovery code
AUTH_UNKNOWN_USER = "auth.unknown"      # login for an account that isn't there
AUTHZ_DENY = "authz.deny"               # authenticated, not permitted
ADMIN_DENY = "admin.deny"               # someone found the unlisted surface
RATELIMIT_TRIP = "ratelimit.trip"
BAN_ISSUED = "ban.issued"


def prune(now: float | None = None):
    """Drop entries past their retention. Called from the same hourly sweep the
    rate limiter uses, so there is no extra background work."""
    now = now if now is not None else time.time()
    q(
        "DELETE FROM security_log WHERE at < ?",
        (int(now - SECURITY_RETENTION_DAYS * 86400),),
    )
    q(
        "DELETE FROM admin_log WHERE at < ?",
        (int(now - ADMIN_RETENTION_DAYS * 86400),),
    )
