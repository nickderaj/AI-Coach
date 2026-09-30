#!/usr/bin/env bash
# Publish the API on this machine's tailnet HTTPS name (port 443), tailnet only.
# Run as root after ./deploy/install.sh. Idempotent: re-running replaces the
# mapping. Never use `tailscale funnel`, which would expose it to the internet.
set -euo pipefail

cd "$(dirname "$0")/.."
bundle=build/deploy

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo: sudo ./deploy/tailscale-serve.sh" >&2
  exit 2
fi
if [ ! -f "$bundle/install.env" ]; then
  echo "no bundle: run ./deploy/build.sh first, as your normal user" >&2
  exit 2
fi
# shellcheck source=/dev/null
. "$bundle/install.env"

tailscale serve --bg --https=443 "http://$TRAINER_UPSTREAM"
tailscale serve status
