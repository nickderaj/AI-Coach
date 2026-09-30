#!/usr/bin/env bash
# Step 1 of a deploy, run as your normal user (no root): build the wheel and the
# web app, export the hash-pinned runtime requirements, and render the systemd
# units and installer variables from deploy/local.env into build/deploy/.
set -euo pipefail

cd "$(dirname "$0")/.."
env_file=${1:-deploy/local.env}
out=build/deploy

if [ ! -f "$env_file" ]; then
  echo "missing $env_file: copy deploy/local.env.example to it and fill in your values" >&2
  exit 2
fi

rm -rf "$out"
mkdir -p "$out"
uv build --quiet --wheel --out-dir "$out"
uv export --locked --no-dev --no-emit-project --format requirements-txt > "$out/requirements.txt"
uv run --locked python -m trainer.deploy render --env "$env_file" --out "$out"
(cd web && pnpm install --frozen-lockfile --silent && pnpm --silent build)
cp -r web/dist "$out/web"
echo "bundle ready in $out; next: sudo ./deploy/install.sh"
