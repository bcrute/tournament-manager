"""Rate limiting and banning.

Clients are identified by a *salted hash* of their IP, never the IP itself:
bans work, but the stored value can't be correlated back to a person or reused
as tracking data. Counters live in memory (single worker); bans are persisted so
a restart doesn't wipe them.
"""

import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from hashlib import sha256

# Requests allowed per window, by route class.
DEFAULT_RULES = {
    # room/account creation and seat claiming — the abusable ones
    "sensitive": (20, 600),  # 20 per 10 minutes
    # ordinary gameplay: life taps, state reads, everything else
    "normal": (900, 60),  # 900 per minute
    "socket": (60, 60),  # websocket connections per minute
}

# Consecutive-ban durations. Repeat offenders climb this ladder.
BAN_STEPS = (3600, 6 * 3600, 24 * 3600, 7 * 24 * 3600)
STRIKES_BEFORE_BAN = 5
STRIKE_WINDOW = 900  # strikes older than this are forgotten

# Retention: a lapsed ban is kept only long enough to make a returning abuser's
# next ban longer. After this it is deleted — there is no reason to hold an
# identifier (even a hashed one) for someone who stopped months ago.
BAN_RETENTION = 30 * 24 * 3600


def _salt() -> bytes:
    """Stable per-deployment salt. Set TABLE_IP_SALT to keep bans across
    redeploys; otherwise one is generated per process (bans still work, they
    just don't survive a restart)."""
    env = os.environ.get("TABLE_IP_SALT")
    return env.encode() if env else _EPHEMERAL_SALT


_EPHEMERAL_SALT = secrets.token_bytes(32)


def client_id(ip: str) -> str:
    """One-way, salted identifier for a client. Not reversible to an IP."""
    return hmac.new(_salt(), ip.encode(), sha256).hexdigest()[:32]


def client_ip(request) -> str:
    """Real client IP. Caddy sits in front and sets X-Forwarded-For; only the
    proxy can reach this app (docker network), so the header is trustworthy."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self, rules=None, db=None, clock=time.time):
        self.rules = dict(rules or DEFAULT_RULES)
        self.clock = clock
        self.db = db  # callable(sql, params) -> cursor, for persisted bans
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._strikes: dict[str, deque] = defaultdict(deque)
        self._bans: dict[str, float] = {}
        self._ban_count: dict[str, int] = {}  # escalation history when there's no db

    # ---- bans ----

    def ban_until(self, cid: str) -> float | None:
        now = self.clock()
        until = self._bans.get(cid)
        if until is None and self.db:
            row = self.db("SELECT until FROM bans WHERE subject = ?", (cid,)).fetchone()
            if row:
                until = row["until"]
                self._bans[cid] = until
        if until is None:
            return None
        if until <= now:
            # the ban lapsed, but keep the record: the strike count is what makes
            # a repeat offender's next ban longer than their last
            self._bans.pop(cid, None)
            return None
        return until

    def clear(self, cid: str):
        """Explicit unban — forgets the history too."""
        self._bans.pop(cid, None)
        self._strikes.pop(cid, None)
        self._ban_count.pop(cid, None)
        if self.db:
            self.db("DELETE FROM bans WHERE subject = ?", (cid,))

    def _strike(self, cid: str) -> float | None:
        """Record a limit violation; ban once they pile up. Returns ban expiry."""
        now = self.clock()
        marks = self._strikes[cid]
        marks.append(now)
        while marks and marks[0] < now - STRIKE_WINDOW:
            marks.popleft()
        if len(marks) < STRIKES_BEFORE_BAN:
            return None
        prior = self._ban_count.get(cid, 0)
        if self.db:
            row = self.db("SELECT strikes FROM bans WHERE subject = ?", (cid,)).fetchone()
            prior = max(prior, row["strikes"] if row else 0)
        step = BAN_STEPS[min(prior, len(BAN_STEPS) - 1)]
        until = now + step
        self._bans[cid] = until
        self._ban_count[cid] = prior + 1
        marks.clear()
        if self.db:
            self.db(
                "INSERT INTO bans (subject, until, strikes, last_strike) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(subject) DO UPDATE SET until = ?, strikes = strikes + 1, last_strike = ?",
                (cid, until, 1, now, until, now),
            )
        return until

    # ---- limiting ----

    def check(self, cid: str, route_class: str) -> tuple[bool, int]:
        """(allowed, retry_after_seconds). Banned or over-limit clients are
        refused; repeated refusals escalate into a ban."""
        now = self.clock()
        banned = self.ban_until(cid)
        if banned:
            return False, max(1, int(banned - now))

        limit, window = self.rules.get(route_class, self.rules["normal"])
        hits = self._hits[(cid, route_class)]
        while hits and hits[0] < now - window:
            hits.popleft()
        if len(hits) >= limit:
            until = self._strike(cid)
            if until:
                return False, max(1, int(until - now))
            return False, max(1, int(hits[0] + window - now))
        hits.append(now)
        return True, 0

    def prune(self, older_than: int = 3600):
        """Drop idle counters so memory doesn't grow with unique visitors, and
        delete ban records past their retention window."""
        now = self.clock()
        cutoff = now - older_than
        for key in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
            self._hits.pop(key, None)
        for key in [k for k, v in self._strikes.items() if not v or v[-1] < cutoff]:
            self._strikes.pop(key, None)
        if self.db:
            self.db("DELETE FROM bans WHERE until < ?", (now - BAN_RETENTION,))
        for cid, until in [(c, u) for c, u in self._bans.items() if u < now - BAN_RETENTION]:
            self._bans.pop(cid, None)
            self._ban_count.pop(cid, None)


# Route classification. Anything that creates state or claims a seat is
# "sensitive"; gameplay traffic is "normal".
SENSITIVE_SUFFIXES = (
    "/rooms",
    "/join",
    "/reclaim",
    # claiming hands out an entrant token, and the roster is public to anyone
    # with the tournament code — at the normal limit a script could claim every
    # seat in an event in seconds
    "/claim",
    "/lift",       # admin: privileged, and a prober shouldn't get free retries
    "/entrants",
    "/turn",
    "/display",
    "/rename",
    "/start",
    # account endpoints: credential stuffing and signup spam land here
    "/signup",
    "/login",
    "/recover",
    "/password",
    "/recovery-codes",
)


def classify(path: str, method: str) -> str:
    if method == "GET":
        return "normal"
    if any(path.endswith(s) for s in SENSITIVE_SUFFIXES):
        return "sensitive"
    return "normal"
