#!/usr/bin/env bash
# Step 2 of a deploy, run as root: install the bundle from ./deploy/build.sh.
# Idempotent; re-run it after every build to upgrade.
#
#  - creates the unprivileged service user and its data directory (0750)
#  - installs a fresh virtualenv under the root-owned prefix from hash-pinned
#    requirements, then swaps it into place
#  - installs, verifies and (re)starts the systemd units
#  - checks /healthz on the loopback address
set -euo pipefail
umask 022

cd "$(dirname "$0")/.."
bundle=build/deploy

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo: sudo ./deploy/install.sh" >&2
  exit 2
fi
if [ ! -f "$bundle/install.env" ]; then
  echo "no bundle: run ./deploy/build.sh first, as your normal user" >&2
  exit 2
fi
# shellcheck source=/dev/null
. "$bundle/install.env"

if ! id -u "$TRAINER_USER" >/dev/null 2>&1; then
  useradd --system --user-group --no-create-home --home-dir /nonexistent \
    --shell /usr/sbin/nologin "$TRAINER_USER"
  echo "created system user $TRAINER_USER"
fi
install -d -o "$TRAINER_USER" -g "$TRAINER_USER" -m 0750 \
  "$TRAINER_DATA_DIR" "$TRAINER_DATA_DIR/backups"
install -d -o root -g root -m 0755 "$TRAINER_PREFIX"

staging="$TRAINER_PREFIX/venv.new"
rm -rf "$staging"
python3 -m venv "$staging"
"$staging/bin/python" -m pip install --quiet --no-deps --require-hashes \
  -r "$bundle/requirements.txt"
"$staging/bin/python" -m pip install --quiet --no-deps --no-index "$bundle"/*.whl
rm -rf "$TRAINER_PREFIX/venv.old"
if [ -d "$TRAINER_PREFIX/venv" ]; then
  mv "$TRAINER_PREFIX/venv" "$TRAINER_PREFIX/venv.old"
fi
mv "$staging" "$TRAINER_PREFIX/venv"
rm -rf "$TRAINER_PREFIX/venv.old"

units=()
for unit in "$bundle"/systemd/*; do
  install -m 0644 -o root -g root "$unit" /etc/systemd/system/
  units+=("/etc/systemd/system/$(basename "$unit")")
done
systemd-analyze verify "${units[@]}"
systemctl daemon-reload
systemctl enable --now trainer-backup.timer
systemctl enable trainer-api.service
systemctl restart trainer-api.service

for _ in $(seq 1 20); do
  if curl --fail --silent --show-error "http://$TRAINER_UPSTREAM/healthz"; then
    printf '\ninstalled: trainer-api is healthy on %s\n' "$TRAINER_UPSTREAM"
    exit 0
  fi
  sleep 1
done
echo "trainer-api did not become healthy; recent logs:" >&2
journalctl --unit trainer-api.service --lines 40 --no-pager >&2
exit 1
