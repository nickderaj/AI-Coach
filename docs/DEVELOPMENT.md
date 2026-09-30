# Development and the quality gate

Every change reaches `main` through a pull request that passes seven required
checks and the owner's review. There are no exceptions for admins, no force
pushes, and history is linear (squash merges only; the PR title becomes the
commit subject).

## Toolchain

All versions are exact; bumping one is a visible, reviewed change.

| Tool | Version | Pinned in |
| --- | --- | --- |
| Python | 3.13 | `pyproject.toml` (`requires-python`), `.python-version` |
| uv | 0.11.27 | `pyproject.toml` (`tool.uv.required-version`), workflows |
| Node | 24.21.0 | `web/.nvmrc`, `web/package.json` (`engines`, strict) |
| pnpm | 12.8.1 | `web/package.json` (`packageManager`, with hash); installed via Corepack locally, `pnpm/action-setup` in CI |
| Python and web packages | exact `==` / `x.y.z` | `pyproject.toml` + `uv.lock`, `web/package.json` + `pnpm-lock.yaml` |
| gitleaks, actionlint | 8.30.1, 1.7.12 | `scripts/install_tools.sh` (SHA-256 verified) |
| GitHub Actions | full commit SHA | workflows |

Setup (Linux or macOS, Intel or Apple silicon; the scripts avoid GNU-only tools and
run on macOS's stock bash 3.2):

```console
./scripts/install_tools.sh          # gitleaks + actionlint into ~/.local/bin
corepack enable pnpm                # pnpm at the version pinned in web/package.json
uv sync --locked
(cd web && pnpm install --frozen-lockfile)
./scripts/ci.sh                     # the whole PR gate, locally
```

## The gate

`./scripts/ci.sh` runs exactly what CI runs. CI splits it into parallel jobs,
each a required status check:

| Check | What fails it |
| --- | --- |
| **policy** | `scripts/policy_check.py`: a requirement not pinned exactly; an action not pinned to a SHA; a suppression (`noqa`, `type: ignore`, `pragma: no cover/mutate`) without a `# why:` justification; an `eslint-disable` without `-- reason`; `@ts-ignore`/`@ts-nocheck`; a skipped, xfailed or focused test; a breakpoint; a symlink; an owner-specific path; anything shaped like a secret; an email address, tailnet hostname or Tailscale IP (the repository is public); an npm lockfile (the web app uses pnpm only); a PR title that is not a Conventional Commit. Also actionlint, zizmor (workflow security), and gitleaks over the full history. |
| **python** | `ruff format`; `ruff check` with **every** rule enabled (complexity ≤ 8, ≤ 5 args, Google docstrings); `mypy --strict` plus extra error codes (explicit `@override`, exhaustive `match`, unreachable code…); `import-linter` layering (`api`/`mcp` → `services` → `storage` → `domain`; `domain` imports no I/O); `deptry`; `pytest` with warnings as errors, no network, random order, 30 s timeout; coverage ≥ 90% total, ≥ 85% per module, **100% of lines and branches in `# coverage-critical` functions**; **≥ 95% of changed lines** (`diff-cover`). |
| **mutation** | `mutmut` over `src/trainer`: **every** mutant must be killed. An equivalent mutant is removed by simplifying the code, or marked `# pragma: no mutate  # why: ...`. |
| **python-dependencies** | `pip-audit` on the hashed runtime lock (any known advisory fails); runtime licences outside the allow-list (`scripts/check_licenses.py`). |
| **web** | Prettier; ESLint `strictTypeChecked` + `stylisticTypeChecked` + React rules, zero warnings, explicit return types, complexity ≤ 8; `tsc` with `strict`, `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess` and friends; Vitest with ≥ 90% lines/branches/functions/statements; Knip (unused files, exports, dependencies); production build. |
| **web-dependencies** | `pnpm audit` at any severity; production licences (`pnpm licenses`) outside the same allow-list as Python (`scripts/check_licenses.py --pnpm`). |
| **reproducibility** | Two clean builds of the wheel, sdist and web bundle must be byte-identical. |

The nightly workflow re-audits `main`'s Python and web dependencies, because
advisories appear without code changing. Dependabot opens weekly grouped
update PRs (with a seven-day cooldown) for minor and patch versions only; they go
through the same gate. **Major versions are never proposed**: they are planned
upgrades, done deliberately in their own PR together with whatever moves in
lockstep (for example TypeScript with typescript-eslint, `@types/node` with the
Node version in `web/.nvmrc`). GitHub Actions majors are still proposed. pnpm
itself refuses any package version published less than a day ago
(`minimumReleaseAge` in `web/pnpm-workspace.yaml`).

## Rules the tools cannot enforce

- **`# coverage-critical`** goes directly above any function that decides
  training load or program position (progression, deload, "next day"). Those
  must be exhaustively tested.
- **Tests are hermetic.** No network (pytest-socket enforces it), no real
  Hermes, model, Tailscale or production database. Use fakes at the service
  boundary and temporary SQLite files.
- **No suppression without a reason**, and prefer changing the code to
  suppressing a rule.
- **Keep PRs small** and single-purpose; the title is the permanent history.

## Repository settings (owner, once)

`scripts/configure_repository.sh` (needs admin) sets squash-only merges with the
PR title as the subject, auto-delete of merged branches, and applies
`scripts/branch-protection.json` to `main`: the seven checks above, required and
up to date; one approving code-owner review, re-requested after any new push;
resolved conversations; linear history; admins included. Private-repository
branch protection requires GitHub Pro or higher on the owner account.
