# Helpers shared by the gate scripts. Portable to Linux (GNU) and macOS (BSD,
# stock bash 3.2); sourced, not executed.

# Print the SHA-256 hex digest of a file.
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d ' ' -f 1
  else
    shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}
