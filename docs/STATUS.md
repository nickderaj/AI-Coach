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

Last updated: 2026-09-30.

## Done

| Step | PR | Notes |
| --- | --- | --- |
| Bootstrap: plan on `main` | direct push `0df8e38` | The only commit that bypassed review. |
| Phase 0a — quality gate | #1 | Seven required checks; branch protection and squash-only merges applied by the owner. |
| Gate fix — Dependabot titles, `@types/node` major pinned to Node 24 | #3 | #2 (Dependabot) closed because of it. |
| npm → pnpm; Apple Health dropped from scope; this status file | #4 | Single-document pnpm lockfile so GitHub's dependency graph and Dependabot can read it. |
| Phase 0b — serve, deploy config, units, backups, scripts; fail-closed preflight | #6 | Deployed 2026-09-30; `/healthz` verified on the phone over the tailnet. |
| Phase 1a — SQLite schema, migrations, re-runnable v1 import (read-only source) | #8 | Deployed and imported 2026-09-30: 35 exercises, 22 aliases, 22 workouts, 361 sets. |
| Phase 1b — owner-only history API and screens; knip production entry (#10) | #9 | Deployed 2026-09-30; history visible on the phone. **Phase 1 complete.** |
| Dependabot: minor/patch only for Python and web | #7 | Majors are planned upgrades (Node 26 LTS from 2026-10-28; TypeScript 7 once typescript-eslint supports it). |
| Phase 2a — idempotent write API; schema v2 | #11 | Deployed 2026-09-30. |
| Phase 2b-1 — Catppuccin Latte redesign: dashboard, history cards, exercise charts and records | #12 | Deployed 2026-09-30. |

## In progress: phase 2 — logging (2c in this PR, before 2b-2)

2c comes before the logging screens so that every write they make goes through
the offline queue from the start, instead of being rewritten later.

**2c: offline and install (this PR).**
- `web/src/outbox/`: writes are saved in IndexedDB first, then replayed in
  order. Only one write per path is kept: a `PUT` replaces the queued one in
  place, so it keeps its turn; a `DELETE` drops it and goes to the back.
- Network errors, 408, 429 and 5xx retry with backoff (2 s doubling to 60 s),
  and again when the phone comes back online or the app is reopened. Any
  other 4xx is kept as "refused" and shown in a banner until dismissed.
- A banner shows what is still waiting to sync.
- `web/src/sw/`: a service worker, built to `/sw.js`. Hashed `/assets/` are
  served cache-first. Everything else is network-first, falling back to the
  cached copy when offline, on a 5xx, or after 3 s. It precaches the app shell
  on install.
- A manifest, icons and iOS meta tags, so the app installs to the home screen.

**Next, 2b-2: logging screens, all writing through the outbox.**
- Start or resume a workout from Home.
- A Strong-style set table (previous | kg | reps | ✓), prefilled from last
  time.
- An exercise picker: recent first, search, and add-exercise with the
  near-duplicate prompt. Adding an exercise needs a connection, because the
  server decides what counts as a duplicate.
- Edit or delete sets, a rest timer, and finishing the workout.
- One-off logging: a single set outside a planned workout.

## Remaining phases

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 2 — Logging | 2a write API (done); 2b-1 visual design (done); 2c offline queue and PWA install (in progress); 2b-2 logging screens | Owner stops logging in v1 |
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
