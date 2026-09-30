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
| Phase 0b — serve, deploy config, units, backups, scripts; fail-closed preflight | #6 | Deployed 2026-09-30; `/healthz` verified on the phone over the tailnet. |
| Phase 1a — SQLite schema, migrations, re-runnable v1 import (read-only source) | #8 | Deployed and imported 2026-09-30: 35 exercises, 22 aliases, 22 workouts, 361 sets. |
| Dependabot: minor/patch only for Python and web | #7 | Majors are planned upgrades (Node 26 LTS from 2026-10-28; TypeScript 7 once typescript-eslint supports it). |

## In progress: phase 1 — data (1b in this PR)

**1b: history API and screens.** The API opens and migrates
`$TRAINER_DATA_DIR/trainer.db` at start-up and serves read-only
`/api/workouts`, `/api/workouts/{id}`, `/api/exercises` and
`/api/exercises/{id}/history`, plus the built web app at `/`. Everything except
`/healthz` answers only the `Tailscale-User-Login` configured as
`TRAINER_OWNER_LOGIN`. The web app has History (workouts → workout detail) and
Exercises (searchable catalogue → per-exercise history) on hash routes, with
every response validated by zod. `deploy/build.sh` builds the web app and
`install.sh` installs it next to the virtualenv. Exit criterion: the imported
history is visible on the phone.

## Next: phase 2 — logging

Exercise picker (recents, search, structured "add exercise" with a
near-duplicate warning), ad-hoc logging and workouts, an offline IndexedDB
queue with idempotent `client_id`s, and the PWA manifest and service worker so
the app installs to the home screen.

## Remaining phases

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 1 — Data | 1a storage + v1 import (#8, done); 1b history API + screens (in progress) | Imported history visible on the phone |
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

**v1 names seeded as aliases** live in code:
`trainer.services.import_v1.HISTORICAL_ALIASES` (weight-suffixed junk names from
v1 are deliberately not carried over).

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
