# Build status and handoff

The single source of truth for **where the build is and what comes next**.
Read this first in any new session, then [PLAN.md](PLAN.md) (design) and
[DEVELOPMENT.md](DEVELOPMENT.md) (the gate). Update this file in the same PR
that completes or changes a step.

**This repository is public.** Nothing specific to the owner's machine, network
or accounts belongs here: no hostnames, tailnet names, IP addresses, ports in
use, emails, filesystem paths on the host, service accounts or personal data.
Those live in the owner's private notes on the build host (outside git) and in
a git-ignored `deploy/local.env`; ask the owner if they are missing. The policy
checker rejects the most common leaks (emails, `*.ts.net` names, Tailscale IPs).

Last updated: 2026-09-29.

## Done

| Step | PR | Notes |
| --- | --- | --- |
| Bootstrap: plan on `main` | direct push `0df8e38` | The only commit that bypassed review. |
| Phase 0a — quality gate | #1 | Seven required checks; branch protection and squash-only merges applied by the owner. |
| Gate fix — Dependabot titles, `@types/node` major pinned to Node 24 | #3 | #2 (Dependabot) closed because of it. |
| npm → pnpm; Apple Health dropped from scope; this status file | #4 | Single-document pnpm lockfile so GitHub's dependency graph and Dependabot can read it. |
| Phase 0b repository side — serve, deploy config, units, backups, scripts | this PR | Owner host steps pending (see In progress). |

## In progress: phase 0b — runtime skeleton (repository side done)

The repository side is complete: `python -m trainer.api` serves the app with
uvicorn; `trainer.deploy` validates `deploy/local.env`, renders hardened systemd
units (API on loopback; nightly SQLite backup with rotation and no network) and
shell-quoted installer variables; `deploy/build.sh` (unprivileged),
`deploy/install.sh` and `deploy/tailscale-serve.sh` (root, idempotent) do the
rest. The installer refuses to run on unsafe host state (`trainer.deploy
preflight`: existing accounts must be dedicated system accounts; data and code
directories and their ancestors must have safe owners and permissions). See [DEPLOY.md](DEPLOY.md). Rehearsed without root: the wheel installs from
the hash-pinned requirements, `/healthz` answers, `systemd-analyze verify` passes.

Exit criterion still open: the owner runs the root steps and opens the served
URL on the phone. `shellcheck` for `deploy/*.sh` is not in the gate yet (a
separate `ci:` PR); the scripts are syntax-checked by the test suite.

## Next: phase 1 — data

One or more PRs:

- `trainer.storage`: SQLite connection factory (WAL, foreign keys on) at
  `$TRAINER_DATA_DIR/trainer.db`, migration runner on `PRAGMA user_version`, the
  PLAN §4 schema for exercises, aliases, workouts and sets.
- `trainer.domain`: exercise identity and alias normalisation (pure).
- v1 importer as a one-off command reading the v1 database read-only (path
  passed on the command line, never committed), seeding every historical name
  listed below as an alias.
- Read-only history API and a History screen in the web app.

## Remaining phases

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 1 — Data | SQLite schema + migration runner (`PRAGMA user_version`), exercise catalogue + aliases, **v1 importer** (read-only on the v1 database, path from config), read-only history API, History screen | Imported history visible on the phone |
| 2 — Logging | Exercise picker (recents, search, structured "add exercise" with near-duplicate warning), ad-hoc logging, workouts, offline IndexedDB queue with idempotent `client_id`s, PWA manifest + service worker | Owner stops logging in v1 |
| 3 — Hermes | `hermes-gateway` unit, `hermes/` profile templates (SOUL, config), MCP tool server, Coach tab on one durable session, **private local git repo** for memory/skills with a nightly commit (never this repo) | Coach remembers across turns and days |
| 4 — Programs | Domain engine (`# coverage-critical`): double progression per D5, deload per D6, sequence-based "next day"; `propose_program` via Hermes; Today screen with blocks/supersets, targets, "last time", rest timer | A full week trained from the app |
| 5 — Cut-over | Web Push + in-app inbox, retire the v1 bot | v1 retired |

## Facts a new session needs

**Runtime.** Python 3.13 managed by uv 0.11.27; Node 24.21.0 and pnpm 12.8.1
(Corepack) for the web app; `gitleaks` and `actionlint` from
`scripts/install_tools.sh`. The target host is a single aarch64 Linux machine
on the owner's tailnet; the app binds to loopback and is published only with
`tailscale serve` (never Funnel). The tailnet ACL allows only the owner's own
devices to reach the served port.

**v1 data (import source).** The retiring v1 gym bot's SQLite database was
cleaned on 2026-09-29: 35 strength movements with display name, equipment and
muscle groups; 22 strength sessions (one per training day, one item per
exercise, one `efforts` row per set); dead hang stored as `duration_s`; two
body-metric rows; one manually logged cardio session. Its location and read
access are in the owner's private notes.

**v1 names the importer must seed as aliases** (old name → v2 exercise):
`bench`, `bench press` → Barbell Bench Press · `pull down`, `pulldown machine`
(+ `40kg`/`45kg`/`50kg` variants) → Lat Pulldown · `tricep ohp`,
`tricep overhead press` (+ `16kg`) → Dumbbell Overhead Tricep Extension ·
`tricep cable overhead press` → Cable Overhead Tricep Extension ·
`tricep press` → Cable Tricep Pushdown · `bulgarian` → Bulgarian Split Squat ·
`romanian` → Barbell Romanian Deadlift · `romanian bosu` → Single-Leg Bosu
Romanian Deadlift · `shoulder press` (+ `20kg`) → Dumbbell Shoulder Press ·
`incline dumbbell bench`, `dumbbell incline press`, `incline bench`
(+ `20kg`/`22.5kg`/`25kg`) → Incline Dumbbell Press · `barbell row`
(+ `20kg`/`40kg`/`50kg`) → Barbell Row · `kettlebell swing` (+ `16kg`/`20kg`/`24kg`)
→ Kettlebell Swing · `standing calf raise`, `calf raise` → Calf Raise ·
`hang` → Dead Hang · `kettlebell twist` → Kettlebell Russian Twist ·
`deadlift` → Barbell Deadlift · `decline bench` → Decline Barbell Bench Press ·
`dumbbell clean press` / `kettlebell clean press` → the matching Clean & Press.

**Personal data.** The owner's stated coaching preferences seed Hermes's memory
in phase 3. They are personal data: they go into the private memory store,
never into this repository.

**Hermes.** v2 runs its own Hermes install. Before phase 3, verify that Hermes
accepts the chosen model provider (D13) as an OpenAI-compatible custom
provider; endpoint and key are configuration, never committed.

**GitHub.** The repository is public. Agents push as a collaborator with write
access (not admin) and cannot approve or merge; the owner reviews every PR.
Squash merges only; PR titles are policy-checked.

## Working rules for every session

1. Start from an up-to-date `main`; one branch and one PR per step.
2. Run `./scripts/ci.sh` before pushing; PRs must be green.
3. Gate changes (thresholds, rules, required checks) only in dedicated `ci:` PRs.
4. Update this file in the PR that completes or changes a step.
5. Anything needing root on the host goes in an idempotent script that the owner runs.
6. Nothing environment-specific or personal is committed (see the top of this file).
