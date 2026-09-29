# Working in hermes-trainer

Read [docs/PLAN.md](docs/PLAN.md) for what is being built and why, and
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the gate every change must pass.

- Never push to `main`. Branch, open a PR with a Conventional Commit title, and
  let the owner review it.
- Run `./scripts/ci.sh` before pushing; do not open a PR that fails it.
- Do not weaken the gate (thresholds, rule selections, required checks,
  `scripts/policy_check.py`) inside a feature PR. Gate changes get their own
  `ci:` PR explaining why.
- `trainer.domain` is pure: no I/O, no framework imports. Rules that decide
  training load or program position are marked `# coverage-critical`.
- Tests are hermetic: no network, no real Hermes/model/Tailscale, no production
  database.
- Pin every new dependency exactly and justify it in the PR description.
