#!/usr/bin/env bash
# Install the pinned, checksum-verified standalone binaries the gate uses.
# Installs into ${TOOLS_DIR:-$HOME/.local/bin}; nothing here needs root.
set -euo pipefail

tools_dir=${TOOLS_DIR:-$HOME/.local/bin}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

case "$(uname -m)" in
  x86_64) gitleaks_arch=x64 actionlint_arch=amd64 ;;
  aarch64 | arm64) gitleaks_arch=arm64 actionlint_arch=arm64 ;;
  *) echo "unsupported architecture $(uname -m)" >&2; exit 2 ;;
esac

declare -A sha256=(
  [gitleaks_8.30.1_linux_x64.tar.gz]=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
  [gitleaks_8.30.1_linux_arm64.tar.gz]=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080
  [actionlint_1.7.12_linux_amd64.tar.gz]=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
  [actionlint_1.7.12_linux_arm64.tar.gz]=325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6
)

fetch() {
  local url=$1 file=$2 binary=$3
  curl --fail --silent --show-error --location --output "$work/$file" "$url"
  echo "${sha256[$file]}  $work/$file" | sha256sum --check --quiet -
  tar -xzf "$work/$file" -C "$work" "$binary"
  install -D -m 0755 "$work/$binary" "$tools_dir/$binary"
}

fetch "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_${gitleaks_arch}.tar.gz" \
  "gitleaks_8.30.1_linux_${gitleaks_arch}.tar.gz" gitleaks
fetch "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_${actionlint_arch}.tar.gz" \
  "actionlint_1.7.12_linux_${actionlint_arch}.tar.gz" actionlint

echo "installed gitleaks and actionlint into $tools_dir"
