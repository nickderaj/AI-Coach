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

Last updated: 2026-10-01.

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
| Phase 2c — offline write queue, service worker, installable app | #13 | Deployed 2026-09-30. |
| Phase 2b-2 — logging screens: start/resume, set table, rest timer, picker, one-off sets | #14 | Deployed 2026-09-30. **Phase 2 built.** |
| Fixes from the first sessions: shorthand, body weight in volume, RPE, rest timer, common exercises | #15 | Deployed 2026-09-30. |
| A share of body weight per bodyweight exercise; "no equipment" merged into bodyweight; schema v4 | #16 | Deployed 2026-10-01 (backup first; no rows needed converting). |
| Phase 3a — pinned Hermes gateway, profile, root-only secrets, private memory repo | #17 | Deploy on 2026-10-01 stopped at the gateway; fixed by #18. |
| Coach unit renamed `trainer-coach`; Hermes run as a module | #18 | Deployed 2026-10-01; the coach answers through the provider. |
| Phase 3b — `trainer.mcp`, the coach's read-only tools; the API holds the log open | #19 | Deployed 2026-10-01; the live coach answers from the owner's log. |
| Phase 3c — Coach endpoints on one durable Hermes session; schema v5 | #20 | Deployed 2026-10-01. |
| Phase 3d — Coach tab in the web app | #21 | Deployed 2026-10-01. **Phase 3 built.** |

## Phase 2 — logging: built, awaiting its exit criterion

Everything in phase 2 is merged and deployed. The phase closes when the owner
stops logging in the v1 bot. Until then, fixes from real use come first.

**2b-2: logging screens (done, #14).** Every write goes through the outbox, so
logging works without signal.
- **Home.** "Start workout" creates the workout on the phone, queues its `PUT`
  and opens the picker. A workout in progress shows as "Resume". A workout the
  server has as unfinished, started on another device or with the phone's copy
  lost, can be picked back up.
- **Workout (`#/log`).** The workout in progress is kept in `localStorage`
  (`web/src/log/`), so iOS closing the app loses nothing. Each exercise has a
  Strong-style table (set | previous | kg | reps or secs | ✓). Rows are
  prefilled from last time's matching set, else from the row above.
  - Ticking a set queues its `PUT` and starts a 90 s rest timer (±15 s, skip).
  - A correction to a logged set is queued as it is typed; the outbox keeps
    only the latest. An edit left incomplete goes back to the last sent values
    when you leave the field, or when the app next opens. Unticking a set
    queues a `DELETE`.
  - Every change re-reads the latest saved copy, and other tabs' changes show
    as they happen, so two tabs keep working on the same workout.
  - You can add or remove sets and remove an exercise with nothing logged.
  - Finish refuses an empty workout. Discard asks first.
- **Picker (`#/log/add`).** Most recently done exercises first, with search.
  "New exercise" posts to the server, which is the one online-only step. It
  handles the near-duplicate answer: use the existing exercise, or add it
  anyway.
- **One-off set.** "Log one set" on an exercise's page saves a workout of its
  own that starts and ends when it is logged.

**2c: offline and install (done, #13).**
- `web/src/outbox/`: writes are saved in IndexedDB first, then replayed in
  order. Only one write per path is kept: a `PUT` replaces the queued one in
  place, so it keeps its turn; a `DELETE` drops it and goes to the back.
- Network errors, 408, 429 and 5xx retry with backoff (2 s doubling to 60 s),
  and again when the phone comes back online or the app is reopened. Any other
  4xx is kept as "refused" and shown in a banner until dismissed.
- Only one copy of the app delivers at a time (a Web Lock shared by Safari tabs
  and the installed app). Each attempt gives up after 20 s and counts as
  retryable.
- `web/src/sw/`: a service worker, built to `/sw.js`. Hashed `/assets/` are
  served cache-first. Everything else is network-first, falling back to the
  cached copy when offline, on a 5xx, or after 3 s.
- A manifest, icons and iOS meta tags, so the app installs to the home screen.

**Fixes from the first real sessions (done, #15).**
- **Shorthand.** The near-duplicate rule spells out gym shorthand before
  comparing names (`ABBREVIATIONS` in `trainer.domain.exercises`: DB, BB, KB,
  BW, OHP, RDL), so "Incline DB Press" is caught as "Incline Dumbbell Press".
- **Body weight in volume.** Schema v3 adds a one-row `profile` table
  (`GET`/`PUT /api/profile`), set from a new Settings screen (⚙ on Home).
  - Bodyweight exercises count reps × (their share of body weight + added
    load); see the next PR for the shares.
  - The server sends that carried weight as `carried_kg` on workout blocks and
    exercise histories, so the charts, records and totals all agree.
  - It uses the current body weight, so past sessions are recalculated when it
    changes.
- **RPE.** The workout table has an optional RPE column, a whole number from
  1 to 10, sent with the set and corrected as it is typed. Drafts saved before
  it existed load with it blank. History shows an RPE column only for an
  exercise where some set has one.
- **Rest timer.** It floats above the tabs, with its space always reserved.
  Ticking a set no longer shifts the screen.
- **Common exercises.** 90 common exercises ship in
  `src/trainer/data/common_exercises.csv`, added by
  `python -m trainer.manage seed-exercises` (see DEPLOY.md). It uses a
  stricter "already there" rule than the near-duplicate prompt (`is_catalogued`).
- **Data fix, outside git.** The owner's late-logged workout #23 was moved to
  Sat 26 Sept, 11:45–12:15 BST. A backup was taken first.

**A share of body weight, and one "bodyweight" (done, #16).**
- **Share of body weight.** 300 bodyweight squats are not 300 squats at body
  weight. Each bodyweight exercise now carries the share of body weight one rep
  lifts, as Alpha Progression does (Hevy counts 100% for pull-ups and dips and
  nothing for the rest). `BODYWEIGHT_SHARES` in `trainer.domain.records` holds
  them: pull-up, chin-up, dip and dead hang 93%, push-up 64% (knee 49%, incline
  55%, decline 70%), squat 77%, split squat and lunge 74%, step-up and pistol
  squat 80%, leg and knee raises 33%, from ExRx's segment data and Ebben et al.
  2011. The inverted row (60%), sit-up (50%), glute bridge (50%), crunch (30%)
  and mountain climber (25%) have no published figure and are estimates. A name
  matches the entry with the most of its words ("Weighted Pull-up" is a
  pull-up), and anything unlisted counts 65%, about a push-up. `carried_kg` is
  that share of the profile's body weight, to 0.1 kg.
- **One "bodyweight".** The new-exercise form offered "None" beside
  "bodyweight". Equipment is now required (the API refuses a missing one), and
  schema v4 sets any exercise without equipment to bodyweight. The v1 importer
  does the same. The live database had none to change.

**Follow-up.** The shares cannot be edited yet; a custom exercise gets the
closest listed one or 65%.

**Follow-up.** An unfinished workout lists in History like a finished one. It
could show an "in progress" mark.

**Next: phase 3, Hermes** (below).

## Phase 3 — Hermes: in progress

**Provider check (2026-10-01): passed.** Hermes v0.21.5 (`v2026.9.24`) uses the
model provider (D13) as a custom OpenAI-compatible provider: a `providers:`
entry with `key_env`, and `model.provider` pointing at it. On the host, with the
production model, it:
- answered over the gateway's Sessions API;
- called its memory tool;
- recalled the fact after a gateway restart, in the same session and in a new
  one.

The same run, as the built bundle, worked under the unit's sandbox. Findings
that shaped the build:
- **Toolsets.** The API server enables terminal, file, browser, code execution
  and more unless `platform_toolsets.api_server` lists the allowed toolsets.
  `agent.disabled_toolsets` removes the rest too.
- **Tool search.** It adds a search-and-call bridge; it is turned off.
- **Packaging.** Hermes refuses to build wheels outside Nix unless
  `HERMES_NIX_BUILD=1` is set. Its API server needs `aiohttp`, which comes from
  the `sms` extra.
- **Runtime installs.** Hermes pip-installs optional providers on first use
  unless lazy installs are off.
- **Syscalls.** Hermes chowns the files it rewrites, so the gateway's syscall
  filter allows `@chown`.

| Step | Scope | PR |
| --- | --- | --- |
| 3a | Pinned Hermes in its own venv; `trainer-coach` unit; `hermes/` profile (config, SOUL); root-only secrets; private memory repo with a nightly commit | #17, #18 |
| 3b | `trainer.mcp`: read-only training-history tools (recent workouts, a workout, the catalogue, an exercise's history, body weight), run by Hermes over stdio | #19 |
| 3c | Coach endpoints in the API: one durable Hermes session, its id in SQLite; send a message, read the conversation | #20 |
| 3d | Coach tab in the web app (needs a connection; shows the conversation) | #21 |
| 3e | On the host, not in git: seed the owner's stated preferences into the coach's memory, then check the exit criterion over several days | seeded 2026-10-01; checking |

**Where the private memory lives.** The coach's home is `<data dir>/hermes`.
Hermes writes what it learns to `memories/` and `skills/` there.
`trainer-memory.timer` commits those two directories nightly to
`<data dir>/hermes-memory.git`, a bare repository on the host with no remote.
The job has no network and refuses a repository that has one.

**3a (done, #17).**
- `build.sh` checks out Hermes at a pinned tag and commit (which must match),
  builds its wheel and exports its hash-pinned requirements (extras `mcp`,
  `sms`).
- `install.sh` installs them into `<prefix>/hermes`, installs the profile into
  the coach's home, creates the memory repository, and enables
  `trainer-coach`. It starts the gateway only once both secrets exist.
- `deploy/hermes-secrets.sh` reads the provider key from the terminal and
  generates the gateway's API key. Both go in root-only files under
  `/etc/hermes-trainer`, which systemd hands to the gateway.
- New `deploy/local.env` keys: `TRAINER_HERMES_PORT`, `TRAINER_MODEL_URL`,
  `TRAINER_MODEL`.
- `python -m trainer.deploy memory-commit` does the nightly commit, without
  user or system git config or hooks.

**Fixes from deploying 3a (done, #18).** The API and the secrets
were installed, but the gateway did not start, for two reasons.
- **Unit name.** The coach's unit was `hermes-gateway.service`. That is the name
  Hermes gives its own gateway, and the v1 bot's Hermes install on the host had
  already used it, with a drop-in of its own (another user, home and env file).
  The installer overwrote v1's unit file under that name (v1's gateway was not
  enabled and nothing ran), and v1's drop-in then applied to the coach. The
  coach's unit is now `trainer-coach.service`. `install.sh` removes the old
  `hermes-gateway.service` only if its description is the coach's, and leaves
  v1's drop-in alone.
- **Launcher.** `ExecStart` ran the venv's `hermes` script, whose `#!` names
  the staging directory the venv was built in, which no longer exists after the
  swap. The unit now runs `python -m hermes_cli.main gateway run`. A test checks
  that every unit starts a venv's `python`, not a console script.

**3b: the trainer's tools (done, #19).**
- `python -m trainer.mcp` is an MCP server over stdio. It handles `initialize`
  (the handshake revisions 2024-11-05 to 2025-11-25), `ping`, `tools/list`
  and `tools/call`; other methods are refused and notifications ignored.
- It is written here, not with the MCP SDK. The SDK (2.2.0) would add about 15
  runtime dependencies to the trainer (cryptography, OpenTelemetry, an
  HTTP/SSE server) for four methods. Hermes's client (mcp 2.0.0) uses the
  `initialize` handshake.
- Five tools, each with a pydantic argument model that also gives the input
  schema: `recent_workouts`, `get_workout`, `list_exercises`,
  `exercise_history`, `body_weight`. They use the storage functions the API
  uses, on a `mode=ro` connection, and return JSON text. Bad arguments, unknown
  ids and an unreadable log come back as tool errors the model can read.
- **Read-only from a read-only mount.** In the coach's sandbox the data
  directory is read-only, and SQLite cannot open a WAL database there unless
  its `-wal` and `-shm` files already exist (checked on the host). The API now
  holds one idle connection for its lifetime, which keeps them, and
  `trainer-coach` starts after `trainer-api`. The coach never gets write access
  near the database.
- `hermes/config.yaml` adds the server as `mcp_servers.trainer` and its
  toolset, `mcp-trainer`, to the allowed toolsets. Hermes passes a stdio server
  only its configured `env` (`TRAINER_DATA_DIR`) plus a safe baseline, so the
  coach's secrets never reach it.
- Checked end to end with the pinned Hermes and a copy of the owner's log: the
  coach answered "what was my last workout, and my last pull-ups?" by calling
  `recent_workouts`, `list_exercises` and `exercise_history`.

**3c: the Coach endpoints (done, #20).**
- `POST /api/coach/messages` with `{"text"}` (1–4000 characters, trimmed)
  runs one turn and returns the reply, `{"role", "text", "at"}`.
  `GET /api/coach/messages` returns the last 100 messages, oldest first: what
  was said, without tool calls or tool results. Both are owner-only.
- **One durable session.** Schema v5 adds a one-row `coach` table with the
  Hermes session id. The first message creates the session, titled "Coach". If
  Hermes no longer has it (`session_not_found`), the next message starts a new
  one. Memory and skills carry over; only the transcript starts again.
- **One turn at a time.** A second message while the coach is answering gets
  409. If the gateway is unreachable or refuses, the endpoints answer 503 and
  log a warning. Without the coach's secrets they answer 503 "the coach is not
  set up".
- `trainer.services.hermes` is a small client for the gateway's Sessions API.
  It uses the standard library (`urllib`), with proxies off so the key only goes
  to the gateway, and a 240 s turn timeout. Tests drive it through a fake
  urllib handler, with no sockets.
- Deploy: `trainer-api` gets `TRAINER_HERMES_URL`, and the gateway key from
  `/etc/hermes-trainer/gateway.env` (optional, so the API starts without it).
  `hermes-secrets.sh` restarts the API as well as the coach.
- Checked end to end: this branch's API, a copy of the log, and the live coach.
  "How many sets of pull-ups did I do last time?" was answered from the log in
  about 10 s (12 sets, 26 September), and the history showed both messages.

**3d: the Coach tab (done, #21).**
- A fourth tab, **Coach** (`#/coach`). It shows the conversation from
  `GET /api/coach/messages`: your messages on the right, the coach's on the
  left. Text is shown as written, never as HTML.
- A composer at the bottom stays above the tab bar. Sending shows your message
  at once and "Thinking…" until the reply arrives; the view scrolls to the
  newest message. Only one message is in flight at a time, and blank messages
  are not sent. The field takes up to 4000 characters, the server's limit.
- If a message cannot be sent, it goes back into the box with the reason. If
  a new message was started in the box meanwhile, that is kept, and the unsent
  one is shown under the reason instead. The reasons:
  - no connection: "Talking to the coach needs a connection.";
  - 409: the coach is still answering;
  - 503: the server's reason, such as "The coach is not set up.".

  Like adding an exercise, the coach needs a connection; nothing is queued
  offline.
- `hermes/SOUL.md`: the coach writes plain text, because the tab shows replies
  exactly as written.

**3e: seeding the coach's memory (2026-10-01, on the host).** The v1 bot's
stated preferences were told to the coach in a throwaway session (deleted
afterwards), and it saved them as three entries in its private memory:
warm-up, split, and progression. v1's "Telegram formatting" preference was
dropped. The entries were committed to the private repository. Their content
is personal and lives only there.

**Exit criterion: the coach remembers across turns and days.** Across turns
was checked in 3a, and through the API in 3c. Across days is being checked: on
a later day, ask in the Coach tab something that needs the seeded preferences
(say "Plan Monday's session"), and check the answer uses the warm-up, split
and progression without being reminded. Phase 3 closes when it does.

**In this PR: keep Hermes's own files out of the memory repository.** The first
memory commit on the host recorded `skills/.curator_state`, Hermes's curator
bookkeeping, beside the owner's memory. Hidden files at the top of `skills/`
(`.curator_state`, `.bundled_manifest`) are now excluded. Each commit re-indexes
the tracked directories from scratch (`git rm -r --cached`, then `git add`),
so a file recorded before an exclude covered it leaves the repository but
stays on disk. Checked on a copy of the host's repository: the file left the
repository, and the next run had nothing to commit.

## Remaining phases

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 2 — Logging | 2a write API, 2b-1 visual design, 2c offline queue and PWA install, 2b-2 logging screens (all done) | Owner stops logging in v1 |
| 3 — Hermes | `trainer-coach` unit, `hermes/` profile templates (SOUL, config), MCP tool server, Coach tab on one durable session, **private local git repo** for memory/skills with a nightly commit (never this repo) | Coach remembers across turns and days |
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
