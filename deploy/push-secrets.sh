#!/usr/bin/env bash
# Make the server's VAPID key pair for Web Push, where only root can read it;
# systemd hands the private key to trainer-push and the public key to
# trainer-api. Run as root after ./deploy/install.sh (it uses the installed
# virtualenv).
# Idempotent: an existing pair is kept, and its public file is checked against
# the private key and written again if it does not match (so a run cut short
# is put right by the next). --rotate makes a new pair; the sender then forgets
# every subscription made with the old key, and each phone has to turn
# notifications on again.
#
#  - push.env:        TRAINER_VAPID_PRIVATE_KEY, which signs every push
#  - push-public.env: TRAINER_VAPID_PUBLIC_KEY, which browsers subscribe with
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."
bundle=build/deploy

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo: sudo ./deploy/push-secrets.sh" >&2
  exit 2
fi
if [ ! -f "$bundle/install.env" ]; then
  echo "no bundle: run ./deploy/build.sh first, as your normal user" >&2
  exit 2
fi
# shellcheck source=/dev/null
. "$bundle/install.env"

rotate=no
case "${1:-}" in
  "") ;;
  --rotate) rotate=yes ;;
  *) echo "usage: sudo ./deploy/push-secrets.sh [--rotate]" >&2; exit 2 ;;
esac

python="$TRAINER_PREFIX/venv/bin/python"
if [ ! -x "$python" ]; then
  echo "not installed: run sudo ./deploy/install.sh first" >&2
  exit 2
fi

install -d -o root -g root -m 0700 "$TRAINER_SECRETS_DIR"
# The keys go from the generator straight into the files: never an argument.
args=(--dir "$TRAINER_SECRETS_DIR")
if [ "$rotate" = yes ]; then
  args+=(--rotate)
fi
"$python" -m trainer.push write-keys "${args[@]}"
echo "secrets stored in $TRAINER_SECRETS_DIR"

# The API serves the public key; the sender signs with the private one.
for unit in trainer-api.service trainer-push.service; do
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    systemctl restart "$unit"
    echo "restarted $unit"
  fi
done
