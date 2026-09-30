#!/usr/bin/env bash
# Import (or re-import) history from the v1 gym bot. Run as root after
# ./deploy/install.sh:
#
#   sudo ./deploy/import-v1.sh <path to the v1 gym.db>
#
# The v1 database is only read: an online SQLite backup of it is taken into a
# private temporary directory, and the importer runs as the service user against
# that copy. Re-running replaces everything previously imported from v1.
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."
bundle=build/deploy

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo: sudo ./deploy/import-v1.sh <v1 gym.db>" >&2
  exit 2
fi
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "usage: sudo ./deploy/import-v1.sh <path to an existing v1 gym.db>" >&2
  exit 2
fi
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
sqlite3 "$1" ".backup '$work/v1.db'"
chown -R "$TRAINER_USER:$TRAINER_USER" "$work"

runuser -u "$TRAINER_USER" -- "$TRAINER_PREFIX/venv/bin/python" -m trainer.manage import-v1 \
  --source "$work/v1.db" --database "$TRAINER_DATA_DIR/trainer.db"
