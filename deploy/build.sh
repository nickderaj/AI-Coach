#!/usr/bin/env bash
# Step 1 of a deploy, run as your normal user (no root): build the wheel and the
# web app, export the hash-pinned runtime requirements, build the pinned Hermes
# release, and render the systemd units and installer variables from
# deploy/local.env into build/deploy/.
set -euo pipefail

cd "$(dirname "$0")/.."
env_file=${1:-deploy/local.env}
out=build/deploy

# The coach runs this Hermes release, checked out by tag and verified by commit.
# Bumping it is a reviewed change: read the release notes, then update both.
hermes_repo=https://github.com/NousResearch/hermes-agent
hermes_tag=v2026.9.24
hermes_commit=f97608f178d1ffeca59860195ab7da295f7c8e5f
# Hermes's build backend pins setuptools but not wheel.
hermes_build_constraints='setuptools==83.0.0
wheel==0.48.0'

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

# Hermes: a wheel built from the pinned commit, and its runtime requirements with
# hashes from Hermes's own lock. Extras: "mcp" for the trainer's tool server and
# "sms", which adds only aiohttp, for the gateway's API server. Hermes refuses to
# build wheels outside its Nix packaging unless HERMES_NIX_BUILD is set.
hermes_src=build/hermes-src
rm -rf "$hermes_src"
git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$hermes_tag" "$hermes_repo" "$hermes_src"
if [ "$(git -C "$hermes_src" rev-parse HEAD)" != "$hermes_commit" ]; then
  echo "hermes $hermes_tag is not commit $hermes_commit; refusing to build it" >&2
  exit 1
fi
mkdir -p "$out/hermes"
printf '%s\n' "$hermes_build_constraints" > build/hermes-build-constraints.txt
(cd "$hermes_src" && uv export --quiet --locked --python 3.13 --no-dev --extra mcp --extra sms \
  --no-emit-project --format requirements-txt) > "$out/hermes/requirements.txt"
HERMES_NIX_BUILD=1 uv build --quiet --wheel --python 3.13 \
  --build-constraint build/hermes-build-constraints.txt --out-dir "$out/hermes" "$hermes_src"
cp hermes/config.yaml hermes/SOUL.md "$out/hermes/"
echo "bundle ready in $out; next: sudo ./deploy/install.sh"
