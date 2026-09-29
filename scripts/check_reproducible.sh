#!/usr/bin/env bash
# Build the Python distributions and the web bundle twice from clean state and
# require byte-identical output. Portable to Linux and macOS.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
. scripts/lib.sh
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

build() {
  local out=$1
  rm -rf dist web/dist
  uv build --quiet --out-dir "$out/python"
  (cd web && pnpm --silent build >/dev/null)
  cp -r web/dist "$out/web"
  (
    cd "$out"
    find . -type f | LC_ALL=C sort | while IFS= read -r file; do
      printf '%s  %s\n' "$(sha256 "$file")" "$file"
    done
  ) > "$out.sha256"
}

build "$work/first"
build "$work/second"
if ! diff -u "$work/first.sha256" "$work/second.sha256"; then
  echo "reproducibility: builds differ" >&2
  exit 1
fi
count=$(wc -l < "$work/first.sha256" | tr -d ' ')  # BSD wc pads with spaces
echo "reproducibility: ok (${count} identical files)"
