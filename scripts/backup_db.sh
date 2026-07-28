#!/bin/sh
# Nightly SQLite backup (T-072). Writes a consistent, dated snapshot of app.db to
# a backup folder (iCloud Drive by default). Uses sqlite3 .backup rather than cp
# so a snapshot taken while the app is running is never half-written.
#
#   ./scripts/backup_db.sh [DB_PATH] [DEST_DIR]
#
# Defaults assume the repo lives at ~/Desktop/PROJECTS/case-prep. Override via the
# two positional args (the launchd plist passes them explicitly).
set -e

DB="${1:-$HOME/Desktop/PROJECTS/case-prep/app.db}"
DEST="${2:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/caseprep-backups}"

mkdir -p "$DEST"
STAMP=$(date +%Y-%m-%d)
sqlite3 "$DB" ".backup '$DEST/app-$STAMP.db'"
echo "$(date '+%Y-%m-%d %H:%M:%S') backed up $DB -> $DEST/app-$STAMP.db"
