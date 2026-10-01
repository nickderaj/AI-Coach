#!/usr/bin/env bash
# Step 2 of a deploy, run as root: install the bundle from ./deploy/build.sh.
# Idempotent; re-run it after every build to upgrade.
#
#  - refuses to proceed if the host is unsafe (python -m trainer.deploy preflight)
#  - creates the unprivileged service user and its data directory (0750)
#  - installs a fresh virtualenv under the root-owned prefix from hash-pinned
#    requirements, and the built web app, then swaps each into place
#  - installs the pinned Hermes in its own virtualenv, and the coach's profile
#    (config.yaml, SOUL.md) into its home in the data directory
#  - creates the private, local-only memory repository (nightly commits)
#  - installs, verifies and (re)starts the systemd units; the coach's gateway
#    starts only once its secrets exist (deploy/hermes-secrets.sh)
#  - checks /healthz and the gateway's /health on loopback
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

# Nothing is changed until the host passes the preflight checks. It runs from the
# bundled wheel with the system Python (the wheel is pure Python and the deploy
# code needs only the standard library).
wheels=("$bundle"/*.whl)
PYTHONPATH="${wheels[0]}" python3 -m trainer.deploy preflight \
  --env "$bundle/config.env" --admin-uid "${SUDO_UID:-0}"

if ! id -u "$TRAINER_USER" >/dev/null 2>&1; then
  useradd --system --user-group --no-create-home --home-dir /nonexistent \
    --shell /usr/sbin/nologin "$TRAINER_USER"
  echo "created system user $TRAINER_USER"
fi
install -d -o "$TRAINER_USER" -g "$TRAINER_USER" -m 0750 \
  "$TRAINER_DATA_DIR" "$TRAINER_DATA_DIR/backups"
install -d -o root -g root -m 0755 "$TRAINER_PREFIX"
touch "$TRAINER_PREFIX/.hermes-trainer"  # marks the prefix as ours for later preflights

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

rm -rf "$TRAINER_PREFIX/web.new" "$TRAINER_PREFIX/web.old"
cp -r "$bundle/web" "$TRAINER_PREFIX/web.new"
chown -R root:root "$TRAINER_PREFIX/web.new"
chmod -R u=rwX,go=rX "$TRAINER_PREFIX/web.new"
if [ -d "$TRAINER_PREFIX/web" ]; then
  mv "$TRAINER_PREFIX/web" "$TRAINER_PREFIX/web.old"
fi
mv "$TRAINER_PREFIX/web.new" "$TRAINER_PREFIX/web"
rm -rf "$TRAINER_PREFIX/web.old"

# Hermes, in its own virtualenv: dependencies from its hash-pinned lock, then the
# wheel built from the pinned commit.
staging="$TRAINER_PREFIX/hermes.new"
rm -rf "$staging"
python3 -m venv "$staging"
"$staging/bin/python" -m pip install --quiet --no-deps --require-hashes \
  -r "$bundle/hermes/requirements.txt"
hermes_wheels=("$bundle"/hermes/*.whl)
"$staging/bin/python" -m pip install --quiet --no-deps --no-index "${hermes_wheels[0]}"
rm -rf "$TRAINER_PREFIX/hermes.old"
if [ -d "$TRAINER_PREFIX/hermes" ]; then
  mv "$TRAINER_PREFIX/hermes" "$TRAINER_PREFIX/hermes.old"
fi
mv "$staging" "$TRAINER_PREFIX/hermes"
rm -rf "$TRAINER_PREFIX/hermes.old"

# The coach's home holds its sessions, memory and skills: the service user's only.
# The profile comes from this repository on every install; the bundled skill
# catalogue is opted out, so skills/ holds only what the coach learns.
install -d -o "$TRAINER_USER" -g "$TRAINER_USER" -m 0700 \
  "$TRAINER_HERMES_HOME" "$TRAINER_MEMORY_REPO"
for file in config.yaml SOUL.md; do
  install -o "$TRAINER_USER" -g "$TRAINER_USER" -m 0600 "$bundle/hermes/$file" \
    "$TRAINER_HERMES_HOME/$file"
done
install -o "$TRAINER_USER" -g "$TRAINER_USER" -m 0600 /dev/null \
  "$TRAINER_HERMES_HOME/.no-bundled-skills"

# Before it was renamed trainer-coach, the coach's unit was hermes-gateway.service,
# the name Hermes gives its own gateway: remove that file only if it is ours.
legacy=/etc/systemd/system/hermes-gateway.service
if [ -f "$legacy" ] && grep -q '^Description=hermes-trainer coach' "$legacy"; then
  systemctl disable --now hermes-gateway.service 2>/dev/null || true
  rm -f "$legacy"
  echo "removed the coach's old unit, hermes-gateway.service"
fi

units=()
for unit in "$bundle"/systemd/*; do
  install -m 0644 -o root -g root "$unit" /etc/systemd/system/
  units+=("/etc/systemd/system/$(basename "$unit")")
done
systemd-analyze verify "${units[@]}"
systemctl daemon-reload
systemctl enable --now trainer-backup.timer trainer-memory.timer
systemctl enable trainer-api.service trainer-coach.service
systemctl restart trainer-api.service

# wait_healthy <unit> <url> <seconds>: wait for a service to answer, else show its logs.
wait_healthy() {
  for _ in $(seq 1 "$3"); do
    if curl --fail --silent --show-error --output /dev/null "$2"; then
      echo "installed: $1 is healthy"
      return 0
    fi
    sleep 1
  done
  echo "$1 did not become healthy; recent logs:" >&2
  journalctl --unit "$1" --lines 40 --no-pager >&2
  return 1
}

wait_healthy trainer-api.service "http://$TRAINER_UPSTREAM/healthz" 20
if [ -f "$TRAINER_SECRETS_DIR/model.env" ] && [ -f "$TRAINER_SECRETS_DIR/gateway.env" ]; then
  systemctl restart trainer-coach.service
  wait_healthy trainer-coach.service "http://$TRAINER_HERMES_UPSTREAM/health" 60
else
  echo "trainer-coach not started: run sudo ./deploy/hermes-secrets.sh first" >&2
fi
