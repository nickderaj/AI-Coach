#!/usr/bin/env bash
# Make the server's VAPID key pair for Web Push, where only root can read it;
# systemd hands the private key to trainer-push and the public key to
# trainer-api. Run as root after ./deploy/install.sh (it uses the installed
# virtualenv to make the key).
# Idempotent: an existing key pair is kept. --rotate makes a new one, and then
# every browser has to turn notifications on again.
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
# write_secret <file> <line>: replace a secrets file atomically, root-only.
write_secret() {
  tmp=$(mktemp "$TRAINER_SECRETS_DIR/.secret.XXXXXX")
  printf '%s\n' "$2" > "$tmp"
  chmod 0600 "$tmp"
  mv "$tmp" "$TRAINER_SECRETS_DIR/$1"
}

if [ "$rotate" = yes ] || [ ! -f "$TRAINER_SECRETS_DIR/push.env" ] \
  || [ ! -f "$TRAINER_SECRETS_DIR/push-public.env" ]; then
  # The key never appears in an argument list: it goes from the generator's
  # output, through shell builtins, into the files.
  pair=$("$python" -m trainer.push new-key)
  private="" public=""
  while IFS= read -r line; do
    case "$line" in
      TRAINER_VAPID_PRIVATE_KEY=*) private=$line ;;
      TRAINER_VAPID_PUBLIC_KEY=*) public=$line ;;
    esac
  done <<< "$pair"
  if [ -z "$private" ] || [ -z "$public" ]; then
    echo "the key generator gave no key pair; nothing written" >&2
    exit 1
  fi
  write_secret push.env "$private"
  write_secret push-public.env "$public"
  echo "made a new VAPID key pair"
else
  echo "kept the existing VAPID key pair"
fi
echo "secrets stored in $TRAINER_SECRETS_DIR"

# The API serves the public key; the sender signs with the private one.
for unit in trainer-api.service trainer-push.service; do
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    systemctl restart "$unit"
    echo "restarted $unit"
  fi
done
