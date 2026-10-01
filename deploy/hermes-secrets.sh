#!/usr/bin/env bash
# Store the coach's secrets where only root can read them; systemd hands them to
# trainer-coach as environment variables. Run as root after ./deploy/build.sh.
# Idempotent: re-run to replace the model provider's API key.
#
#  - model.env:   TRAINER_MODEL_API_KEY, read from stdin (never an argument, so it
#                 stays out of shell history and the process list)
#  - gateway.env: API_SERVER_KEY, the key the gateway's API server checks;
#                 generated once and kept (pass --rotate-gateway-key to replace it)
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."
bundle=build/deploy

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo: sudo ./deploy/hermes-secrets.sh" >&2
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
  --rotate-gateway-key) rotate=yes ;;
  *) echo "usage: sudo ./deploy/hermes-secrets.sh [--rotate-gateway-key]" >&2; exit 2 ;;
esac

if [ -t 0 ]; then
  read -rsp "Model provider API key: " key
  echo
else
  IFS= read -r key || true
fi
if ! [[ $key =~ ^[A-Za-z0-9._~+/=-]{16,512}$ ]]; then
  echo "that does not look like an API key; nothing written" >&2
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

write_secret model.env "TRAINER_MODEL_API_KEY=$key"
if [ "$rotate" = yes ] || [ ! -f "$TRAINER_SECRETS_DIR/gateway.env" ]; then
  write_secret gateway.env "API_SERVER_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  echo "generated a new gateway key"
fi
echo "secrets stored in $TRAINER_SECRETS_DIR"

if systemctl is-enabled --quiet trainer-coach.service 2>/dev/null; then
  systemctl restart trainer-coach.service
  echo "restarted trainer-coach"
fi
