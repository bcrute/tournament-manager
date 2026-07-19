"""Shared SQLite connection and schema.

Lives apart from the feature modules so rooms, accounts and rate limiting can
all reach the same database without importing each other.
"""

import os
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
# indexes on migrated columns must come after the columns exist
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
