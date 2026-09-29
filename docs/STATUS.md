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

## Next: phase 0b — runtime skeleton

Goal: the API's `/healthz` answers over HTTPS on the owner's phone, through
`tailscale serve`, with nothing exposed beyond the tailnet. One PR
(`feat(deploy): ...`), plus owner-run host steps.

Every host-specific value is **configuration, not code**: the deploy scripts
read `deploy/local.env` (git-ignored; a committed `deploy/local.env.example`
documents each key with placeholder values). At minimum:
`TRAINER_USER`, `TRAINER_DATA_DIR`, `TRAINER_PREFIX`, `TRAINER_BIND`
(loopback `host:port`), `TRAINER_BACKUP_KEEP`.

Repository work (all gated):

- `deploy/systemd/trainer-api.service` template: runs `uvicorn` (add as an
  exact-pinned runtime dependency) on the `create_app` factory as the
  configured user, bound to the configured loopback address, hardened
  (`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp`,
  `ReadWritePaths=` the data directory only, `RestrictAddressFamilies=AF_INET
  AF_INET6 AF_UNIX`, empty `CapabilityBoundingSet=`).
- `deploy/install.sh`: idempotent; creates the system user
  (`--system --no-create-home --shell /usr/sbin/nologin`), the data directory
  (0750, owned by that user) and the install prefix (root-owned, read-only to the
  service), builds the wheel into a venv there with `uv`, renders and installs
  the units, enables them. Code is root-owned; only data is writable.
- `deploy/tailscale-serve.sh`: `tailscale serve --bg --https=443 http://$TRAINER_BIND`.
- `deploy/backup.sh` + timer: nightly `sqlite3 .backup` of the database into
  `$TRAINER_DATA_DIR/backups`, keeping `$TRAINER_BACKUP_KEEP`.
- Tests that render and validate the unit templates from the example env (no
  host access in tests), and `shellcheck` for `deploy/*.sh` if it can join the
  gate cleanly (separate `ci:` PR if it changes the gate).

Owner/host steps (need root; by rule the owner runs them, not an agent):
fill in `deploy/local.env`, then `sudo ./deploy/install.sh` and
`sudo ./deploy/tailscale-serve.sh`, then open the URL on the phone.

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
