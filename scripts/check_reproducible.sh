#!/usr/bin/env bash
# Build the Python distributions and the web bundle twice from clean state and
# require byte-identical output.
set -euo pipefail

cd "$(dirname "$0")/.."
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

build() {
  local out=$1
  rm -rf dist web/dist
  uv build --quiet --out-dir "$out/python"
  (cd web && npm run -s build >/dev/null)
  cp -r web/dist "$out/web"
  (cd "$out" && find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$out.sha256"
}

build "$work/first"
build "$work/second"
if ! diff -u "$work/first.sha256" "$work/second.sha256"; then
  echo "reproducibility: builds differ" >&2
  exit 1
fi
echo "reproducibility: ok ($(wc -l < "$work/first.sha256") identical files)"
