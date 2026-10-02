#!/usr/bin/env bash
# Import (or re-import) history from the v1 gym bot. Run as root after
# ./deploy/install.sh:
#
#   sudo ./deploy/import-v1.sh [--dry-run] <path to the v1 gym.db>
#
# The v1 database is only read: an online SQLite backup of it is taken, through
# a read-only connection made as the database's own owner (so any file SQLite
# keeps beside it stays theirs), into a private temporary directory. The
# importer runs as the service user against that copy. Re-running replaces
# everything previously imported from v1. --dry-run shows what would change
# against the last import and writes nothing.
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."
bundle=build/deploy

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo: sudo ./deploy/import-v1.sh <v1 gym.db>" >&2
  exit 2
fi
dry_run=()
if [ "${1:-}" = --dry-run ]; then
  dry_run=(--dry-run)
  shift
fi
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "usage: sudo ./deploy/import-v1.sh [--dry-run] <path to an existing v1 gym.db>" >&2
  exit 2
fi
source_db=$(realpath "$1")
# The path goes into an SQLite URI and a quoted dot-command: keep it plain.
case "$source_db" in
  *[\?#%\'\"]*) echo "the v1 database's path has characters this script will not quote" >&2; exit 2 ;;
esac
if [ ! -f "$bundle/install.env" ]; then
  echo "no bundle: run ./deploy/build.sh and sudo ./deploy/install.sh first" >&2
  exit 2
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required to snapshot the v1 database" >&2
  exit 2
fi
# shellcheck source=/dev/null
. "$bundle/install.env"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
owner=$(stat -c %U "$source_db")
chown "$owner" "$work"
runuser -u "$owner" -- sqlite3 "file:$source_db?mode=ro" ".backup '$work/v1.db'"
chown -R "$TRAINER_USER:$TRAINER_USER" "$work"

runuser -u "$TRAINER_USER" -- "$TRAINER_PREFIX/venv/bin/python" -m trainer.manage import-v1 \
  "${dry_run[@]}" --source "$work/v1.db" --database "$TRAINER_DATA_DIR/trainer.db"
