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

Last updated: 2026-10-02.

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
| Phase 4a — program engine (progression, deload, next day); schema v6 | #24 | Deployed 2026-10-01 (backup first); schema v6 live, existing workouts untouched. |
| Phase 4b — programs through the API: proposals, the active program, today's day | #25 | Deployed 2026-10-01 (backup first); `/api/programs` and `/api/today` answer the owner, 403 otherwise. |
| Phase 4c — `propose_program`: the coach proposes through the API with the gateway's key | #26 | Deployed 2026-10-01 (backup first). A live turn in a throwaway session proposed through the API (200); session deleted, test proposal turned down, no memory written. |
| Phase 4d — the Program tab: the block, its weeks and next day; accept or turn down a proposal; ask the coach | #27 | Deployed 2026-10-01 (backup first); the live app serves the tab, and decline by id answers 409 for a stale id. |
| `current_program`: the coach reads the program it changes | #29 | Deployed 2026-10-01. A live turn in a throwaway session called `current_program`; session deleted, no memory written. |
| v1's Telegram gym bot (`gym.service`) stopped and disabled, at the owner's request | — | 2026-10-02, on the host: `sudo systemctl disable --now gym.service`. Nothing deleted (its code, database and user stay); roll back with `sudo systemctl enable --now gym.service`. **Phase 2's exit criterion met**; phase 5's "retire v1" step done early. |
| Phase 4e — the Today screen: train the program's next day from the app | #28 | Deployed 2026-10-02 (backup first). Live: `/api/today` answered the owner (null, no program yet); the served bundle has Today, the left-over recovery and the fresh (`no-store`) reads. **Phase 4 built.** |

## Phase 2 — logging: done

Everything in phase 2 is merged and deployed. Its exit criterion, the owner
no longer logging in the v1 bot, was met on 2026-10-02: the owner stopped using
it, and its service was stopped and disabled at their request (see Done).

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

**In this PR: one answer per turn in the Coach tab.** The first real
conversation showed a turn twice. When the coach writes a sentence and calls
tools in the same step ("I'll check your recent upper-body sets…"), Hermes
stores that commentary as an assistant message with tool calls, and the tab
showed it as a reply before the real answer. Assistant messages that call
tools are now left out of the history (`GatewayMessage.calls_tools`, from
Hermes's `tool_calls`). Checked against the live conversation: each turn now
shows once. Also, the hidden "You:"/"Coach:" labels can no longer be selected,
so copying a bubble no longer carries them into a new message.

**Exit criterion, across days:** in that same conversation the coach planned
Friday's session with the seeded 5-minute mobility warm-up, unprompted, and
deferred to the app's progression and deload rules.

## Phase 4 — Programs: built, awaiting its exit criterion

Phase 4 is split into PRs that each stand on their own, in this order. Each one
updates this section.

| Step | Scope | PR |
| --- | --- | --- |
| 4a | Schema v6 (programs, days, blocks, block exercises; program links on workouts and sets; an exercise's own load step) and the pure engine: double progression (D5), deload (D6), next day by sequence | #24 |
| 4b | Programs in storage and services. API: the active and the proposed program, accept a proposal, today's program day with each exercise's target and last time, workouts and sets linked to the program | #25 |
| 4c | `propose_program`, the coach's MCP tool: exercise ids only, validated, written through the API as a proposal (see below); the coach's profile learns to use it | #26 |
| 4d | Web: the Program screen. The whole block, the current week, the deload week marked; a proposal to accept; generate or refine through the coach | #27 |
| 4e | Web: the Today screen. The next program day, supersets side by side, sets prefilled with targets, last time, a rest timer per block | #28 |
| 4f | Exit criterion, by the owner: a full week trained from the app | ready |

**Exit criterion: a full week trained from the app (4f, ready for the owner).**
Everything in phase 4 is merged and deployed. To check it:
1. In the **Program** tab, ask the coach for a program ("Plan one with the
   coach"). Read the proposal, then **Start this program**.
2. Each training day, open **Home → Next in your program**, then **Start
   this workout**. Log the sets (prefilled from the targets) and **Finish**.
3. After the last day of the week, the Program tab shows week 2, and Today
   shows targets worked out from week 1: up a step where every set reached
   the top of its range.

Phase 4 closes when a full week has been trained this way.

**How the coach writes a program (4c).** The tool server runs in the coach's
sandbox, where the data directory is read-only, so it cannot write the
database, and should not: writes go through services. `propose_program`
checks its arguments (shape, and that every exercise id exists, read-only),
then sends the program to the API on loopback. That one endpoint accepts the
gateway's key, which the API and the coach already share, in place of the
owner's login. The API checks the program again and saves it as a *proposal*.
The owner accepts it on the Program screen. The coach never replaces the
active program by itself, and the model never works out loads (D12).

**4a: the engine and schema v6 (done, #24).**
- `trainer.domain.programs` is pure and every rule in it is
  `# coverage-critical`.
- **Next day.** Position is the day after the last completed one
  (`next_position`): day 1 to the last day, then the next week. Weeks 1–6 are
  training weeks, week 7 is the deload week, and after its last day the block
  is done. A missed session is simply the next one.
- **Double progression (D5)**, worked out from the last session of the same
  program exercise:
  - Working sets are the sets at that session's heaviest load, so lighter
    warm-ups do not count.
  - If at least the prescribed number of them all reached the top of the
    range, the load rises one increment and the sets are prefilled with the
    bottom of the range.
  - If every one fell short of the bottom, the load drops one increment (never
    below none) and is worked back up.
  - Otherwise the load repeats, and each set is prefilled with last time's reps
    for that set, kept within the range.
  - A first session uses the program's starting load, or leaves it to the
    owner. Timed exercises do the same with seconds.
  - A bodyweight exercise at the top adds load (a dip belt), from none to one
    increment.
- **Load steps.** Barbell, dumbbell, EZ bar, cable and bodyweight 2.5 kg,
  machine 5 kg, kettlebell 4 kg. Bands and "other" have none, so their load
  never changes by rule. An exercise can have its own step
  (`exercises.load_increment_kg`; no screen sets it yet).
- **Deload (D6).** 60% of the sets, rounded and at least one. The load is 90%
  of the last session's working load, to the nearest increment, a tie going
  lighter: 12.5 kg becomes 10 kg, 60 kg becomes 55 kg. An exercise without an
  increment keeps its load, since 90% may not be a load it has (a band); the
  fewer sets are its deload.
- **Schema v6.** `programs` (name, notes, training weeks, status `proposed`,
  `active` or `archived`; at most one proposed and one active),
  `program_days`, `program_blocks` (rest in seconds), `block_exercises` (sets,
  rep range, starting load, notes). `workouts` gain `program_day_id` and
  `program_week`, both or neither. `workout_sets` gain `block_exercise_id`, so
  the sets of a superset (A1, A2, A1, A2…) still belong to their program
  exercise. A program that has been trained from cannot be deleted. Existing
  rows are untouched.
- **From review:** an exercise without an increment keeps its load in the
  deload week (see above), rather than rounding to an invented step.

**4b: programs through the API (done, #25).** Every endpoint is owner-only.
- **The program's shape** is one pydantic model in `trainer.services.programs`
  (`ProgramIn`), so the API and the coach's tool (4c) check it the same way:
  - 1–7 days, each with 1–12 blocks;
  - a block holds 1 exercise, or 2–3 as a superset, with rest 0–600 s
    (default 90);
  - an exercise has 1–10 sets, a range within 1–600 (reps, or seconds),
    an optional starting load and notes;
  - unknown fields are refused. Exercises are ids from the catalogue; an
    unknown id, or one measured in distance, is refused with the ids named.
- `PUT /api/programs/proposal` saves a program as the proposal, replacing the
  last one. `POST /api/programs/{id}/accept` makes it the active program and
  archives the old one; 409 if it is no longer the proposal. (Turning one down
  is `POST /api/programs/{id}/decline`, from review of 4d.)
- `GET /api/programs`: the active program with its next week and day, and the
  proposal. A program lists its days in order, each with its blocks in order,
  and each exercise with its catalogue name, measure and load step.
- `GET /api/today` (null without an active program) plans the next day:
  - the week, whether it is the deload week, and each block's rest;
  - each exercise's target (decision, load, reps per set) from its last
    finished training-week session;
  - last time: the exercise's most recent session anywhere, outside today's
    workout;
  - the body weight a bodyweight exercise carries.

  An unfinished workout that trains a day of the program makes that day
  today, and its id comes back as `workout_client_id`; it counts neither for
  targets nor as last time. Once the deload week is done, `day` is null.
- **Workouts and sets.** `PUT /api/workouts/{id}` takes an optional
  `program: {day_id, week}`; the day must exist and the week be within the
  program, deload included. `PUT /api/sets/{id}` takes an optional
  `block_exercise_id`, which must be on that workout's day and for the same
  exercise (422 otherwise). A program exercise's sets share one block in the
  log, whatever order a superset is done in; a set outside the program never
  joins it. A workout shows its `program_day_id` and `program_week`, and each
  block its `block_exercise_id`.
- **From review:** once a workout has sets for a day's program exercises, it
  keeps that day. A `PUT` that drops the day or names another is refused
  (422), so a workout's day and its sets' program exercises always agree. A
  later week of the same day, or a new day before any program set is logged,
  is still allowed.

**4c: the coach proposes programs (done, #26).**
- `propose_program` is a sixth tool on `trainer.mcp`, offered only when the
  tool server has `TRAINER_API_URL` and `TRAINER_COACH_KEY`. Its arguments are
  `ProgramIn` (4b), so the coach writes exercise ids, sets, rep ranges, rest
  and starting loads, never later loads. Its JSON schema has the nested models
  written out in place (no `$ref`), which any model provider can read.
- Bad arguments are answered as a tool error naming where each problem is
  (`days.0.blocks.1.exercises.0.rep_max: …`) and never reach the API. The
  API's own refusals (an unknown exercise id) come back as the coach's tool
  error with the API's reason.
- It `PUT`s the program to the API on loopback with
  `Authorization: Bearer <gateway key>`. The API accepts that key (compared in
  constant time) on `PUT /api/programs/proposal` alone; every other route
  still needs the owner's login. Proxies are ignored, as for the Hermes client.
- `trainer-coach.service` sets `TRAINER_API_URL` to the API's address
  (bracketed for IPv6). `hermes/config.yaml` passes it and
  `${API_SERVER_KEY}` to the tool server. Hermes gives a stdio server only its
  configured env and a safe baseline, and keeps the `${...}` names when it
  rewrites the config (checked in the pinned Hermes source), so the key is
  never written to disk by it.
- `hermes/SOUL.md` gains a Programs section: read the log and memory first,
  use catalogue ids, set first-session loads only, and tell the owner the
  proposal waits for them on the Program screen (4d).
- **Checked end to end before review**, with throwaway servers, removed
  afterwards:
  - this branch's API on a copy of the latest backup;
  - a second pinned Hermes gateway with a scratch home, running this branch's
    profile and tool server with the production model.

  Asked for a two-day full-body program, the coach read the log, called
  `propose_program` once (the API logged one `PUT …/proposal` 200), and saved
  a two-day program with a superset each day and starting loads from the
  log; nothing active changed. The provider accepted the nested schema.
  (Hermes also refused to start on a short test key: its API server wants at
  least 16 characters, as the real generated key has.)

**4d: the Program screen (done, #27).** A fifth tab, **Program** (`#/program`),
between Home and History.
- **The block.** The active program's name, when it started, and a strip of
  its weeks: 1–6 and D for the deload week. Weeks done are green, the current
  one is filled, and the deload week is teal.
  - One line says where training is: "Week 3 of 6. Next: Lower.", or "Deload
    week: the same days, fewer sets and lighter. Next: …", or "Block
    complete. Ask the coach for your next program."
  - Then each day in order, the next one outlined and marked "Next".
  - Within a day, blocks are lettered A, B, C. A superset is labelled and its
    exercises are A1, A2 on a shared rail.
  - Each exercise shows sets × range ("3 × 8–12", "2 × 30–45 s"), and each
    block its rest.
- **A proposal** sits on top in its own card ("Proposed by your coach"), with
  the coach's notes and each exercise's starting load.
  - "Start this program" accepts it at once if nothing is active. Otherwise it
    asks first: "It replaces …".
  - "Turn down" always asks first.
  - Both need a connection; a failure says why ("Changing your program needs a
    connection.", or the server's reason) and leaves the buttons ready to try
    again.
- **Asking the coach.** A box under the program: "Plan one with the coach"
  without a program, "Change it with the coach" with one. The text is sent as
  "Plan a program for me: …" or "Change my program: …" in the coach's one
  conversation, so it shows in the Coach tab too.
  - "The coach is working on it…" while it answers. The reply is shown
    there, and the programs load again, so a new proposal appears.
  - On a failure the request stays in the box with the reason.
  - The request and the reply live with the screen, so the reload does not
    lose them.
- **From review:**
  - Turning a proposal down names it: `POST /api/programs/{id}/decline`, 409
    if another has replaced it. The old `DELETE /api/programs/proposal`
    removed whichever was current, which a stale screen could do to one never
    seen.
  - A replaced or declined proposal is now archived, not deleted. Otherwise
    SQLite could give its id to the next program, and a stale screen's accept
    or decline would act on that one.
  - While a change is on its way, every proposal button, confirmations
    included, is disabled, and a second change cannot start.
  - The box to ask the coach appears only once the programs are known.
    While they load or cannot be read, it can't tell "plan one" from "change
    it".
- Checked on a phone-size render (390 px, this branch's API on a copy of
  the latest backup). That caught a clash: a block's rest line used `.rest`,
  the class of the logging screen's floating rest timer, and was drawn as a
  bar over the tabs. It is `.block-rest` now, and a test checks it.

**4e: the Today screen (done, #28).** Training a program day reuses the
logging screens of phase 2, so it works offline and through the outbox like any
workout.
- **Today (`#/today`).** Home shows "Next in your program: Upper A · Week 2"
  while nothing is in progress, and links here.
  - The screen shows the day ("Day 1 of 4"), the week or the deload week, and
    every exercise in order: its letter (A, or B1/B2 in a superset), its
    target ("Target 3 × 8–12 · 62.5 kg") and last time ("Last Thu 24 Sept:
    12 × 60 kg, …"), with each block's rest.
  - **Start this workout** builds the workout from the targets. Each set is
    prefilled with the target load and that set's reps or seconds; kg stays
    empty when there is no load to add.
  - If this phone already has the day in progress, it says **Resume**. Another
    workout in progress is named, with Resume. If the server has the day in
    progress but the phone lost its copy, **Resume this workout** fetches it
    and fills in its logged sets (this needs a connection).
- **Training it** (`#/log`, the phase 2 screen):
  - The heading is the day and week. Each exercise card shows its letter, its
    target and why: "Up: every set reached the top last time", "Same load:
    beat last time", "Lighter: work back up", "First time in this program" or
    "Deload: lighter, fewer sets".
  - A superset's exercises are kept together on one rail: "Superset: one set of
    each in turn, then rest 60 s".
  - The rest timer uses the block's rest. In a superset it starts only after
    the round's last exercise.
  - Exercises added from the picker are logged as before, outside the program.
- **Writes.** The workout's `PUT` names `program: {day_id, week}` at start and
  at finish, and each set its `block_exercise_id`. A workout picked up from the
  server keeps both, so finishing it never drops its day (the server refuses
  that, 4b).
- Drafts saved by the previous version still load: the new fields default to
  nothing.
- **From review**, so a stale screen can never train or change the wrong day:
  - **The API** refuses (409) a workout that newly names a program day another
    workout already trains that week, finished or still in progress (two
    phones, one offline), or a day of a program no longer active. A replay of
    its own start or finish is still accepted.
  - **The service worker** leaves a read made with `cache: "no-store"` to the
    network: such a read gets the server's answer or fails, never a saved copy.
  - **Start** reads Today afresh and starts only if the day and week shown are
    still due and nothing trains them yet. Otherwise the plan reloads, with a
    note. Only a network failure (fetch's TypeError) falls back to the saved
    plan, and not for a day this phone has finished (it remembers the days it
    finishes). A refusal (401, 403, 5xx), an answer that is not JSON (a
    proxy's error page) or not the expected shape is shown, and nothing starts.
  - **Resume** reads the workout in progress afresh. It picks it up only if it
    is the same workout, day and week; otherwise the plan reloads.
  - **Partial pick-up:** logged sets take their places, and the sets still to
    do keep their targets.
  - **Home's Resume** of any workout with a program day goes through Today,
    which checks it afresh and rebuilds the plan around the logged sets. Only
    a workout outside any program is rebuilt from the server's copy.
  - **A program is not replaced mid-workout.** Accepting a proposal is
    refused (409, "finish or discard the workout in progress first") while a
    workout of the active program is unfinished. Otherwise that workout would
    be left without its plan, and Today, which plans the new program, could
    not pick it up.
  - **One program workout at a time.** The API refuses a new program workout
    (409, "finish or discard the workout in progress first") while another
    is unfinished: one on another phone, or one of a program replaced before
    that was refused. In data like that, `/api/today` names the left-over
    workout (`left_over`) in the same answer as the day, so the screen never
    pairs two separately saved reads. Today shows it with **Resume it as
    logged** and holds the day's Start until it is finished or discarded.
    Resuming re-reads `/api/today` afresh and needs the same left-over, and
    the rebuild keeps its program day, so its finish is accepted. Start
    likewise needs no left-over in its fresh read. The day in progress is
    the latest unfinished *program* workout, so a later workout outside the
    program hides nothing.
  - **Superset rest:** a round ends with the last exercise that has that set,
    as the superset stands. With unequal set counts the longer one rests on
    its extra sets, and after removing the rest of a superset every set rests.
- Checked at phone size: this branch's API on a copy of the latest backup,
  with an upper/lower program and week 1 logged through the API, driven by
  Playwright in the headless shell. Today showed week 2 with the engine's
  decisions: incline press up to 25 kg, lat pulldown "beat 10/9/8", lateral
  raise up a step, rear delt fly (11/10/9 against 12–15) down a step.
  Starting it, then ticking set 1, started the block's 150 s rest. The render
  caught two layout bugs before review: a squeezed "Last" column on Today,
  and the block letter pushing the exercise name onto its own row.

**The coach reads the program (done, #29, from review of 4d).** The coach could
propose programs but not read the one being trained, so "Change my program: …"
from the Program tab left it guessing. A read-only `current_program` tool now
returns `GET /api/programs`'s answer through the same service: the active
program with every day, block and exercise, its next week and day, and any
proposal waiting. `hermes/SOUL.md` tells the coach to read it before
proposing.

## Phase 5 — Cut-over: in progress

v1's bot is already stopped (see Done). What is left is how the app reaches
the owner when it is closed (D1), and one last import of anything logged in
v1 since phase 1. Phase 5 is split into PRs that each stand on their own:

| Step | Scope | PR |
| --- | --- | --- |
| 5a | Schema v7 (`push_subscriptions`, `inbox`); what to notify (pure, `trainer.domain.notices`); the inbox, holding and claiming a notice, subscriptions, and pushing through a sender interface | this PR |
| 5b | API: subscribe and unsubscribe, the inbox, a test notice; the coach's answer posts its notice. Web Push itself (RFC 8291 encryption, RFC 8292 VAPID) on `cryptography`; a small sender unit with outbound network, the API kept without; `deploy/push-secrets.sh` for the VAPID keys | |
| 5c | Web: the service worker shows pushes and opens the right screen; a Settings switch and a test; the Inbox screen with unread state | |
| 5d | The last v1 import: a dry run in the PR, then one re-run after deploy, backup first | this PR |
| 5e | Exit criterion, by the owner: push and the inbox working on the phone; v1's history fully imported | |

**What is notified.** As little as possible; v1's daily "not imported" nudge
was dropped on purpose, and nothing here runs on a timer.
- **The coach's answer, when the owner is not watching for it.** A turn can
  take a minute, and the phone may be locked or on another screen by then. The
  answer's notice is *held* for 15 seconds (`HOLD`). If the Coach or Program
  screen is open and visible when the reply arrives, the app tells the server
  it was seen, which *claims* the notice: it is removed and never pushed.
  Otherwise it shows in the inbox and is pushed. Its text is the start of the
  reply, on one line, up to 140 characters.
- **A new program proposal, folded into that answer.** Only the coach proposes,
  and only inside a turn, so a turn that proposed a program sends one notice,
  "Your coach proposed <name>", which opens the Program screen, rather than
  two.
- **Not the program's next day.** A program is a sequence, not a calendar, so a
  daily "next: Upper A" would arrive on rest days too: the nagging v1 dropped.
  Today and Home already show it.
- **A test**, sent from Settings, to check a phone receives pushes.

**5a: the inbox and its storage (this PR).**
- **Schema v7.** `push_subscriptions`: one row per browser, by its push
  service address (`https` only, unique), with its two keys as it gave them.
  `inbox`: a notice's kind (`coach`, `proposal` or `test`), title and text,
  when it was made, when it is due (shown and pushed), when its push was dealt
  with and when it was read.
- **The inbox** (`trainer.services.notices`) shows the 50 newest notices that
  are due, newest first, and counts every unread one. "Seen" claims a notice
  still held, or marks one already due as read; read all marks every due one.
- **Subscriptions** are checked before they are kept: the address must be
  HTTPS on a known push service (Apple, Google, Mozilla or Microsoft, or their
  subdomains) with no user or port, and the keys must be base64url of the
  right size (a 65-byte uncompressed P-256 key, a 16-byte secret).
  Subscribing again with the same address replaces the keys.
- **Pushing** (`deliver`): each notice that has come due is pushed at most
  once to every browser, through a `PushSender` (5b brings the real one; tests
  use a fake). It is claimed in a transaction of its own before anything is
  sent, so a second round running at the same time skips it, and a process
  stopped mid-push does not push it again on restart. The claim also checks,
  under the same write lock, that the notice is still unread, so one read in
  the app after the round picked it up is not pushed (both from review). A failed push is not retried: the notice is in the inbox. A browser
  whose subscription has ended (the push service answers 404 or 410) is
  forgotten. A notice read before its push, or due more than an hour ago (the
  sender was down), is left to the inbox. No transaction is held while a push
  is on its way.
- **Dependencies.** Pushing needs encryption and signatures, so 5b adds
  `cryptography` (Apache-2.0 or BSD-3-Clause), which brings `cffi` and
  `pycparser`. `cffi` 2.1 declares `MIT-0`; the allow-list gains it in its own
  `ci:` PR. `pywebpush` was not used: it would add `requests`, `aiohttp`,
  `http-ece` and `py-vapid`, the last two under MPL-2.0, for about 80 lines
  of code that the RFC's own test vector checks.

**5d: the last v1 import, a dry run first (this PR).**
- `python -m trainer.manage import-v1 --dry-run` (and `import-v1.sh --dry-run`)
  re-imports into an in-memory copy of the database, read through a read-only
  connection, and compares it with what the last import wrote. It lists every
  workout, set, body metric and cardio session that would be added or removed,
  by content rather than id, and the exercises new to the catalogue. Nothing
  is written.
- `import-v1.sh` now snapshots the v1 database through a read-only connection
  (`file:…?mode=ro`) made as that database's owner. Before, it opened the
  source read-write as root. In WAL mode that can checkpoint into the source
  and leave root-owned `-wal`/`-shm` files beside it.
- **Dry run on 2026-10-02**, against a fresh backup of the live database and
  a read-only copy of v1 (v1's bot stopped since that morning): it would
  import 35 exercises, 22 aliases, 22 workouts, 361 sets, 2 body metrics and
  1 cardio session, and **nothing differs** from the phase 1 import. No
  workout, set, metric or cardio session would be added or removed, and no
  exercise is new. v1's last session is 28 September, before phase 1's import.

## Remaining phases

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 2 — Logging | 2a write API, 2b-1 visual design, 2c offline queue and PWA install, 2b-2 logging screens (all done) | Owner stops logging in v1 |
| 3 — Hermes | `trainer-coach` unit, `hermes/` profile templates (SOUL, config), MCP tool server, Coach tab on one durable session, **private local git repo** for memory/skills with a nightly commit (never this repo) | Coach remembers across turns and days |
| 4 — Programs | Domain engine (`# coverage-critical`): double progression per D5, deload per D6, sequence-based "next day"; `propose_program` via Hermes; Today screen with blocks/supersets, targets, "last time", rest timer | A full week trained from the app |
| 5 — Cut-over | Web Push + in-app inbox; a last catch-up import from v1's database (v1's bot is already stopped, 2026-10-02); in progress, above | Push and inbox working; v1's history fully imported |

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
