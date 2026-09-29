#!/usr/bin/env bash
# The full pull-request gate, locally. CI runs the same commands split into
# parallel jobs; a change that passes here passes there.
set -euo pipefail

cd "$(dirname "$0")/.."

require() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required tool $1; see docs/DEVELOPMENT.md" >&2
    exit 2
  fi
}
for tool in uv node pnpm git gitleaks actionlint; do require "$tool"; done

step() { printf '\n==> %s\n' "$*"; }

step policy
uv run --locked python scripts/policy_check.py
actionlint -color
uv run --locked zizmor --quiet --persona auditor .github
gitleaks git --redact --no-banner .

step python
uv sync --locked --quiet
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run lint-imports
uv run deptry src
uv run pytest --cov --cov-report=json:coverage.json --cov-report=xml:coverage.xml
uv run python scripts/check_coverage.py coverage.json
if git rev-parse --verify --quiet origin/main >/dev/null; then
  uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=95
fi

step mutation
rm -rf mutants
uv run mutmut run > mutmut.log 2>&1 || { tail -40 mutmut.log; exit 1; }
rm -f mutmut.log
uv run mutmut results --all true | uv run python scripts/check_mutation.py

step python-dependencies
uv export --locked --no-dev --no-emit-project --format requirements-txt > requirements.audit.txt
trap 'rm -f requirements.audit.txt' EXIT
uv run pip-audit --strict --disable-pip --require-hashes -r requirements.audit.txt
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements-txt \
  | uv run python scripts/check_licenses.py

step web
(
  cd web
  pnpm install --frozen-lockfile --silent
  pnpm --silent format:check
  pnpm --silent lint
  pnpm --silent typecheck
  pnpm --silent coverage
  pnpm --silent knip
  pnpm --silent build
)

step web-dependencies
(
  cd web
  pnpm audit --audit-level low
  pnpm licenses list --prod --json | uv run python ../scripts/check_licenses.py --pnpm
)

step reproducibility
./scripts/check_reproducible.sh

printf '\nci: all gates passed\n'
