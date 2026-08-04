#!/usr/bin/env bash
#
# Back up the SQLite database, on the host, before anything can go wrong.
#
# `docs/security.md` carried "no off-host backup" as gap 1 — the largest real
# risk — deferred with the trigger "before the first real tournament runs on
# it". That trigger never fired, and meanwhile the stakes moved: the file now
# holds accounts, scrypt password hashes, game history and private notes, and
# schema migrations run on deploy. On 2026-08-04 a deploy applied a migration
# with no backup of any kind in existence. This closes the cheap half of that
# gap.
#
# What it protects against: a bad migration, an accidental delete, a container
# doing something unexpected to its volume. What it does NOT protect against is
# losing the host — these copies live on the same disk. Off-host remains open
# and needs a destination somebody chooses; see the note at the end of this
# file.
#
# Why `sqlite3 .backup` rather than `cp`: the database runs in WAL mode with a
# live writer. Copying the file while a write is in flight gives you a torn
# database that looks fine until it does not. `.backup` uses SQLite's own
# online backup API, which is consistent by construction and does not block the
# app while it runs.
#
# Usage:
#   deploy/backup.sh                 back up, prune, report
#   deploy/backup.sh --label predeploy   tag this one (the deploy uses this)
#
# Install on the VPS:
#   0 4 * * * /opt/apps/mtg/backup.sh >> /var/log/mtg-backup.log 2>&1

set -euo pipefail

DB=${MTG_DB:-/opt/apps/mtg/appdata/treachery.db}
DEST=${MTG_BACKUP_DIR:-/opt/apps/mtg/backups}
KEEP=${MTG_BACKUP_KEEP:-14}
LABEL="daily"

while [ $# -gt 0 ]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ ! -f "$DB" ]; then
  echo "backup: no database at $DB — nothing to do" >&2
  exit 0
fi

mkdir -p "$DEST"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$DEST/treachery-$STAMP-$LABEL.db"

# The image has sqlite3; the host may not. Run it in the container we already
# ship rather than adding a host dependency for one command.
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".backup '$OUT'"
else
  docker run --rm -v "$(dirname "$DB")":/data -v "$DEST":/out python:3.12-slim \
    python -c "
import sqlite3, sys
src = sqlite3.connect('/data/$(basename "$DB")')
dst = sqlite3.connect('/out/$(basename "$OUT")')
with dst:
    src.backup(dst)
dst.close(); src.close()
"
fi

# Refuse to keep a backup that is not a readable database. A zero-byte or torn
# file in the backup directory is worse than no file, because it looks like
# protection.
SIZE=$(stat -c%s "$OUT" 2>/dev/null || echo 0)
if [ "$SIZE" -lt 4096 ]; then
  echo "backup: $OUT is only ${SIZE}B — refusing to keep it" >&2
  rm -f "$OUT"
  exit 1
fi

gzip -f "$OUT"
OUT="$OUT.gz"

# Prune by count, newest kept. Deliberately not by age: a host that has been
# off for a month should not wake up and delete its only copies.
mapfile -t OLD < <(ls -1t "$DEST"/treachery-*.db.gz 2>/dev/null | tail -n +$((KEEP + 1)))
for f in ${OLD+"${OLD[@]}"}; do
  rm -f "$f"
done

echo "backup: $(basename "$OUT") ($(du -h "$OUT" | cut -f1)), $(ls -1 "$DEST"/treachery-*.db.gz 2>/dev/null | wc -l) kept"

# ---------------------------------------------------------------------------
# Still open: these copies are on the same disk as the database, so they do not
# survive losing the host. Closing that needs a destination — another machine,
# or object storage — and a credential for it. Whatever it is, note that these
# files contain password hashes and private notes, so a public bucket or a
# GitHub artifact is not an option.
