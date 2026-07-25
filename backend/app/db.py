"""Shared SQLite connection and schema.

Lives apart from the feature modules so rooms, accounts and rate limiting can
all reach the same database without importing each other.
"""

import os
import secrets
import sqlite3
import threading

DB_PATH = os.environ.get("TREACHERY_DB", "treachery.db")

_db_lock = threading.Lock()
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.row_factory = sqlite3.Row
# WAL: readers don't block the writer and commits stop rewriting a rollback
# journal every time. synchronous=NORMAL is the documented safe pairing —
# durable against process crashes, and a lost game state on host power-loss is
# not worth an fsync per write here.
_db.execute("PRAGMA journal_mode=WAL")
_db.execute("PRAGMA synchronous=NORMAL")
_db.execute("PRAGMA busy_timeout=5000")
_db.execute("PRAGMA foreign_keys=ON")

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
    CREATE TABLE IF NOT EXISTS bans (
        subject TEXT PRIMARY KEY,   -- salted hash of a client IP, never the IP
        until INTEGER NOT NULL,
        strikes INTEGER NOT NULL DEFAULT 0,
        last_strike INTEGER
    );

    -- Accounts are optional. The only required field is a username; email is
    -- there purely so someone can recover an account, and may stay NULL.
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        pw_hash TEXT NOT NULL,
        email TEXT,
        created_at INTEGER NOT NULL DEFAULT (unixepoch()),
        last_seen INTEGER
    );
    -- One-time codes so an account can be recovered without an email address.
    CREATE TABLE IF NOT EXISTS recovery_codes (
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        code_hash TEXT NOT NULL,
        used_at INTEGER,
        PRIMARY KEY (account_id, code_hash)
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL DEFAULT (unixepoch()),
        last_seen INTEGER,
        expires_at INTEGER NOT NULL
    );
    -- Private per-game notes, written during or after a game.
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        room_code TEXT NOT NULL,
        game_no INTEGER NOT NULL,
        text TEXT NOT NULL,
        updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
        UNIQUE (account_id, room_code, game_no)
    );
    """
)


_db.executescript(
    """
    -- Tournaments. An organizer runs one; entrants are tournament-scoped and
    -- need no account, so a player only ever provides a display name.
    CREATE TABLE IF NOT EXISTS tournaments (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        organizer_account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        mode TEXT NOT NULL DEFAULT 'life',
        settings TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'setup',   -- setup | running | ended | expired
                                                -- 'ended' is the organizer's call, 'expired' the
                                                -- idle sweep's; only the first freezes standings
        created_at INTEGER NOT NULL DEFAULT (unixepoch()),
        last_active INTEGER
    );
    CREATE TABLE IF NOT EXISTS entrants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_code TEXT NOT NULL REFERENCES tournaments(code) ON DELETE CASCADE,
        name TEXT NOT NULL,
        token TEXT UNIQUE,          -- null until someone claims the seat
        account_id INTEGER,
        -- the sanctioning id (whatever the game's profile calls it), stored
        -- only when the organizer enables collection. The column keeps its
        -- MTG-era name while the setting and the wire field are already
        -- generic; it is internal and never served, and the rename waits
        -- because a test reads it by this name.
        wizards_email TEXT,
        dropped_at INTEGER,
        created_at INTEGER NOT NULL DEFAULT (unixepoch())
    );
    CREATE TABLE IF NOT EXISTS trounds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_code TEXT NOT NULL REFERENCES tournaments(code) ON DELETE CASCADE,
        number INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',  -- pending | active | closed
        seed INTEGER NOT NULL DEFAULT 0,
        started_at INTEGER,
        ends_at INTEGER,
        paused_at INTEGER,
        UNIQUE (tournament_code, number)
    );
    CREATE TABLE IF NOT EXISTS pods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        round_id INTEGER NOT NULL REFERENCES trounds(id) ON DELETE CASCADE,
        number INTEGER NOT NULL,
        room_code TEXT,
        game_no INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',  -- pending|active|awaiting_result|complete
        extension_seconds INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS pod_seats (
        pod_id INTEGER NOT NULL REFERENCES pods(id) ON DELETE CASCADE,
        entrant_id INTEGER NOT NULL,
        seat INTEGER NOT NULL,       -- 1-based; seat order is turn order
        place INTEGER,               -- 1 = won the pod
        points INTEGER,
        PRIMARY KEY (pod_id, entrant_id)
    );
    -- Results are versioned rather than mutated: an override keeps its history.
    CREATE TABLE IF NOT EXISTS pod_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pod_id INTEGER NOT NULL REFERENCES pods(id) ON DELETE CASCADE,
        version INTEGER NOT NULL,
        kind TEXT NOT NULL,          -- placement | draw | bye | unfinished
        source TEXT NOT NULL,        -- auto | organizer
        note TEXT,
        decided_at INTEGER NOT NULL DEFAULT (unixepoch())
    );
    CREATE TABLE IF NOT EXISTS official_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_code TEXT NOT NULL REFERENCES tournaments(code) ON DELETE CASCADE,
        pod_id INTEGER,
        entrant_id INTEGER,
        category TEXT,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'open',   -- open | acknowledged | resolved
        created_at INTEGER NOT NULL DEFAULT (unixepoch()),
        acknowledged_at INTEGER,
        resolved_at INTEGER,
        resolution TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_entrants_tournament ON entrants(tournament_code);
    CREATE INDEX IF NOT EXISTS idx_pods_round ON pods(round_id);
    CREATE INDEX IF NOT EXISTS idx_pods_room ON pods(room_code, game_no);
    CREATE INDEX IF NOT EXISTS idx_calls_tournament ON official_calls(tournament_code, status);
    """
)


_db.executescript(
    """
    -- Every privileged action taken through the admin surface. This is the one
    -- part of the app with a real audit requirement: admin actions affect other
    -- people's games and are invisible to them.
    CREATE TABLE IF NOT EXISTS admin_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at INTEGER NOT NULL DEFAULT (unixepoch()),
        actor TEXT NOT NULL,        -- admin username
        action TEXT NOT NULL,
        target TEXT,
        detail TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_admin_log_at ON admin_log(at DESC);

    -- Kept apart from admin_log on purpose: this one is noise-heavy and mostly
    -- failures, and mixing the two would bury the rare deliberate action among
    -- thousands of rejected probes. Different question, different reader,
    -- different retention.
    CREATE TABLE IF NOT EXISTS security_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at INTEGER NOT NULL DEFAULT (unixepoch()),
        kind TEXT NOT NULL,
        subject TEXT,               -- salted client hash or username, never an IP
        detail TEXT                 -- never a token, password, or recovery code
    );
    CREATE INDEX IF NOT EXISTS idx_security_log_at ON security_log(at DESC);
    CREATE INDEX IF NOT EXISTS idx_security_log_kind ON security_log(kind, at DESC);
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
_ensure_column("rooms", "last_active", "INTEGER")
_ensure_column("events", "game_no", "INTEGER")
_ensure_column("players", "is_display", "INTEGER NOT NULL DEFAULT 0")
_ensure_column("players", "life", "INTEGER")
_ensure_column("players", "eliminated", "INTEGER NOT NULL DEFAULT 0")
_ensure_column("players", "seat_order", "INTEGER")
_ensure_column("players", "account_id", "INTEGER")  # optional link to an account
_ensure_column("pod_seats", "room_token", "TEXT")   # this entrant's token in the pod's room
# "source:id" (e.g. "topdeck:9f3c") so a re-run of an import matches the same
# person instead of duplicating them. Matching on display name would make names
# identity — the exact flaw we rejected in TopDeck's shape.
_ensure_column("entrants", "external_ref", "TEXT")
# which game profile this event runs; MTG is one surface over a generic core
_ensure_column("tournaments", "game", "TEXT NOT NULL DEFAULT 'mtg'")
# extra turns left after time was called; NULL means time hasn't been called
_ensure_column("pods", "turns_remaining", "INTEGER")
# An organizer's name for the table ("Feature", "Bar side"). NULL means the pod
# is known by its number, which stays its identity either way — a name is a
# label people call across a hall, never a key anything looks up.
_ensure_column("pods", "label", "TEXT")
# The id shown to clients. The integer primary key stays internal: it is
# sequential, and the roster is public to anyone holding a tournament code, so
# exposing it would disclose roughly how many entrants have ever been created.
_ensure_column("entrants", "public_id", "TEXT")
for _row in _db.execute("SELECT id FROM entrants WHERE public_id IS NULL").fetchall():
    _db.execute(
        "UPDATE entrants SET public_id = ? WHERE id = ?",
        (secrets.token_urlsafe(8), _row[0]),
    )
_db.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_entrants_public ON entrants(public_id) "
    "WHERE public_id IS NOT NULL"
)
_ensure_column("players", "eliminated_at", "INTEGER")
# A seated player showing the table view on their own phone. Unlike is_display
# this changes no game state: they keep their seat, life, card and host role.
# It only grants the one capability the display has — adjusting other players.
_ensure_column("players", "is_tracker", "INTEGER NOT NULL DEFAULT 0")
# "I can't lose": Platinum Angel, Phyrexian Unlife, Gideon of the Trials and
# friends. Zero life and 21 commander damage stop meaning anything for this
# player, so the app stops flagging them — only an explicit "I'm dead" ends it.
_ensure_column("players", "cant_lose", "INTEGER NOT NULL DEFAULT 0")
# The id that appears in the address bar. The five-character code has to be
# readable aloud across a table, which means it is short enough to guess; this
# is 128 random bits, so a room URL can be shared, screenshotted or left in
# history without handing over something joinable.
_ensure_column("rooms", "url_id", "TEXT")
for _r in _db.execute("SELECT code FROM rooms WHERE url_id IS NULL").fetchall():
    _db.execute("UPDATE rooms SET url_id = ? WHERE code = ?", (secrets.token_urlsafe(16), _r[0]))
_db.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_rooms_url_id ON rooms(url_id) "
    "WHERE url_id IS NOT NULL"
)  # ordering for tournament placement
# indexes on migrated columns must come after the columns exist
_db.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_entrants_external ON entrants(tournament_code, external_ref) "
    "WHERE external_ref IS NOT NULL"
)
_db.execute(
    "CREATE INDEX IF NOT EXISTS idx_players_account ON players(account_id) "
    "WHERE account_id IS NOT NULL"
)
_db.commit()


def q(sql, params=()):
    with _db_lock:
        cur = _db.execute(sql, params)
        # only writes need a commit; committing after every SELECT was pure cost
        head = sql.lstrip()[:6].upper()
        if head not in ("SELECT", "PRAGMA"):
            _db.commit()
        return cur
