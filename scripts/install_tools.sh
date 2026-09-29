#!/usr/bin/env bash
# Install the pinned, checksum-verified standalone binaries the gate uses.
# Installs into ${TOOLS_DIR:-$HOME/.local/bin}; nothing here needs root.
# Portable to Linux and macOS (including macOS's stock bash 3.2 and BSD tools).
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck source=scripts/lib.sh
. ./lib.sh

tools_dir=${TOOLS_DIR:-$HOME/.local/bin}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) echo "unsupported OS $(uname -s)" >&2; exit 2 ;;
esac
case "$(uname -m)" in
  x86_64) gitleaks_arch=x64 actionlint_arch=amd64 ;;
  aarch64 | arm64) gitleaks_arch=arm64 actionlint_arch=arm64 ;;
  *) echo "unsupported architecture $(uname -m)" >&2; exit 2 ;;
esac

expected_sha256() {
  case "$1" in
    gitleaks_8.30.1_linux_x64.tar.gz) echo 551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb ;;
    gitleaks_8.30.1_linux_arm64.tar.gz) echo e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080 ;;
    gitleaks_8.30.1_darwin_x64.tar.gz) echo dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709 ;;
    gitleaks_8.30.1_darwin_arm64.tar.gz) echo b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5 ;;
    actionlint_1.7.12_linux_amd64.tar.gz) echo 8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 ;;
    actionlint_1.7.12_linux_arm64.tar.gz) echo 325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6 ;;
    actionlint_1.7.12_darwin_amd64.tar.gz) echo 5b44c3bc2255115c9b69e30efc0fecdf498fdb63c5d58e17084fd5f16324c644 ;;
    actionlint_1.7.12_darwin_arm64.tar.gz) echo aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f ;;
    *) echo "no pinned checksum for $1" >&2; return 1 ;;
  esac
}

fetch() {
  local url=$1 file=$2 binary=$3 expected actual
  expected=$(expected_sha256 "$file")
  curl --fail --silent --show-error --location --output "$work/$file" "$url"
  actual=$(sha256 "$work/$file")
  if [ "$actual" != "$expected" ]; then
    echo "checksum mismatch for $file: expected $expected, got $actual" >&2
    exit 1
  fi
  tar -xzf "$work/$file" -C "$work" "$binary"
  mkdir -p "$tools_dir"
  cp "$work/$binary" "$tools_dir/$binary"
  chmod 0755 "$tools_dir/$binary"
}

gitleaks_file="gitleaks_8.30.1_${os}_${gitleaks_arch}.tar.gz"
actionlint_file="actionlint_1.7.12_${os}_${actionlint_arch}.tar.gz"
fetch "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/${gitleaks_file}" \
  "$gitleaks_file" gitleaks
fetch "https://github.com/rhysd/actionlint/releases/download/v1.7.12/${actionlint_file}" \
  "$actionlint_file" actionlint

echo "installed gitleaks and actionlint into $tools_dir"
