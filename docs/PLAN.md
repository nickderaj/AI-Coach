# hermes-trainer — build plan

A single-user strength-training app: multi-week programs, a phone-first logging
UI, and a Hermes coach with persistent memory. It replaces the `gym` Telegram bot
from the retired `ultron` monorepo.

Progress and the next step are tracked in [STATUS.md](STATUS.md). Every change
lands through the quality gate in [DEVELOPMENT.md](DEVELOPMENT.md).

## 1. Why a rebuild

The v1 bot had four structural problems, confirmed against its live database:

| Problem | Evidence in v1 |
| --- | --- |
| A plan was one workout for one date | `workout_plans.plan_json` held a flat `items[]` list with a `for_date`; nothing could express "Upper A / Lower A / Upper B / Lower B for six weeks". |
| Supersets only existed as prose | No grouping in the plan schema or the log; pairings lived in `notes`. |
| Exercise names drifted | 54 strength `movements` for ~35 real exercises. The model wrote free-text names each time, `/gym` accepted anything, and `movements.name` was the only dedup key. |
| Weights were parsed into names | `/gym incline bench 20kg 1x12` stored an exercise called `incline bench 20kg` with no weight — 21 sets lost their load this way. |
| One workout was ~15 sessions | Every logged exercise created its own `sessions` row. |
| Hermes memory was inert | `memory`, `session_search`, `skills` were enabled but every message ran a cold `hermes -z` one-shot, so nothing persisted between turns. |

The v1 database was cleaned in place on 2026-09-29 (54 → 35 movements, 194 → 22
sessions, weights recovered from names) and is the import source for this app.

## 2. Decisions

| # | Decision |
| --- | --- |
| D1 | **No Telegram bot.** A React web app is the only interface. Notifications use Web Push to the home-screen app. |
| D2 | **Private to the tailnet.** Served with `tailscale serve` (HTTPS, tailnet-only). The `Tailscale-User-Login` identity header is the login: the API answers only the configured owner; nothing is exposed to the internet. |
| D3 | **Stack:** Python 3.13 + FastAPI + SQLite on the server; React + Vite + TypeScript PWA on the client. |
| D4 | **Programs** are fixed blocks: **6 training weeks + 1 deload week**, typically a 3–4 day split. |
| D5 | **Progression is rule-based double progression**, computed when a day is opened — never pre-computed. If every working set of an exercise reached the top of its rep range at the current load, the next session's load rises by the exercise's increment **and the rep target resets to the bottom of the range** (owner's stated rule: 12 × 10 kg → next time 12.5 kg for 8–10). If the sets fell short of the bottom of the range (a failed session), the load drops one increment and is worked back up. Otherwise load and target repeat. |
| D6 | **Deload week:** same exercises, ~60% of the sets, ~90% of the last working load. After it the app offers a new program. |
| D7 | **Supersets are structure**: a program day is an ordered list of *blocks*; a block with more than one exercise is a superset (A1/A2). |
| D8 | **Exercises are chosen, never typed.** A searchable catalogue backs every screen, including ad-hoc logging (e.g. 100 push-ups mid-day). New exercises are built from structured fields (equipment + movement) with a near-duplicate check. |
| D9 | **Equipment is part of an exercise's identity** (dumbbell vs cable overhead tricep extension are different exercises). Bench-type moves under 30 kg are dumbbells, weight per hand. |
| D10 | **Hermes owns coaching, SQLite owns facts.** Hermes memory/skills/session search hold soft knowledge (injuries, preferences, style); sets, programs and the catalogue live in SQLite and reach Hermes only through MCP tools. |
| D11 | **Hermes learning is on from day one**, writes land immediately, and the profile's memory and skills directory is **committed nightly to a private, local-only git repository on the host** so every learned fact is a reviewable, revertible diff. It is personal data and never enters this (public) repository. |
| D12 | **Program generation goes through Hermes** (`propose_program` MCP tool, exercise ids only), so it benefits from memory. Progression itself never calls a model. |
| D13 | **Model provider: Surplus**, via Hermes's OpenAI-compatible custom endpoint. Endpoint, model id and key are deployment configuration. |
| D14 | **Runtime:** a dedicated unprivileged system user; code root-owned and read-only; one writable data directory. User, paths and bind address are deployment configuration (`deploy/local.env`, git-ignored), never committed. |
| D15 | **Strict gate from the first commit.** Every change after bootstrap lands by pull request through required checks and owner review (see DEVELOPMENT.md). |

## 3. Architecture

```
iPhone (home-screen PWA, offline queue)
   │  HTTPS, tailnet only
   ▼
tailscale serve ──▶ trainer-api (FastAPI, 127.0.0.1)
                      ├─ REST API for the web app
                      ├─ Web Push sender
                      ├─ SQLite  $TRAINER_DATA_DIR/trainer.db
                      └─ Coach proxy ──▶ trainer-coach (127.0.0.1, session API)
                                           home: $TRAINER_DATA_DIR/hermes (profile from hermes/)
                                           memory · skills · session_search · todo · clarify
                                           └─ MCP (stdio) ──▶ python -m trainer.mcp (reads, read-only)
```

Processes (systemd, all as the service user, loopback-only):

1. **trainer-api** — serves the built web app and the JSON API.
2. **trainer-coach** — one long-lived Hermes gateway, pinned to a Hermes
   release, with the profile in `hermes/` installed into its home,
   addressed through its authenticated HTTP session API. The web app's Coach tab
   maps to one durable Hermes session, so turns keep context and a warm prompt
   cache.
3. **The tool server** (`python -m trainer.mcp`) — started by the gateway as a
   child process and spoken to over stdin and stdout, so it shares the coach's
   sandbox and has no unit of its own. It reads the training log through the
   same storage functions as the API, on a read-only connection; the API holds
   one connection open so SQLite's WAL files exist for it. Writing (programs,
   phase 4) will go through services.

Repository layout:

```
src/trainer/
  domain/     pure models and rules (progression, deload, catalogue matching) — no I/O
  storage/    SQLite schema, migrations, repositories
  services/   use cases composed from domain + storage
  api/        FastAPI routers and app factory
  mcp/        Hermes tool surface
web/          React + Vite PWA
hermes/       trainer profile templates: config.yaml, SOUL.md, reviewed skills
              (memory lives in a private store on the host, not here)
deploy/       systemd units, tailscale serve config, backup + nightly memory commit
docs/         this plan, DEVELOPMENT.md, DATA_MODEL.md
```

Layering is enforced by `import-linter`: `api`/`mcp` → `services` → `storage` →
`domain`; `domain` may not import any I/O or web framework.

## 4. Data model (initial)

```
exercises          id, name, display_name, equipment, movement, muscle_groups,
                   measure (reps|seconds|distance), load_increment_kg?
exercise_aliases   alias, exercise_id              -- every historical v1 name
programs           id, name, notes, training_weeks(6), status (proposed|active|archived),
                   created_at, started_at     -- deload week = training_weeks + 1
program_days       id, program_id, position, name ("Upper A")
program_blocks     id, day_id, position, rest_s    -- >1 exercise = superset
block_exercises    id, block_id, position, exercise_id, sets, rep_min, rep_max,
                   start_load_kg, notes
workouts           id, started_at, ended_at, program_day_id?, program_week?, notes, client_id
workout_sets       id, workout_id, exercise_position, exercise_id, set_number,
                   reps, load_kg, duration_s, rpe, notes, client_id (idempotency),
                   block_exercise_id?
body_metrics       id, measured_at, metric, value, unit, source
cardio_sessions    id, started_at, activity, duration_s, distance_m, notes   -- logged in the app
push_subscriptions id, endpoint, keys, created_at
coach              session_id                      -- the Coach tab's one Hermes session
```

Program position is sequence-based, not calendar-based: "today" is the day after
the last completed program day, so a missed session never desynchronises the week.
`workout_sets.client_id` makes offline replays idempotent.

## 5. Web app

- **Today** — the next program day, grouped by block (supersets side-by-side),
  each set row prefilled with the computed target and "last time". Tick a set to
  save it; a rest timer starts per block. Finish closes the workout.
- **Log** — ad-hoc logging from the catalogue picker (recents first, search,
  structured "add exercise" with near-duplicate warning).
- **Program** — the whole block, current week, deload marker; generate / refine
  through the coach.
- **History** — per-exercise trend and PRs; per-workout detail.
- **Coach** — Hermes chat on one durable session.
- **Offline-first** — sets are written to IndexedDB and synced with idempotent
  `client_id`s; the gym's patchy signal never loses a set.

## 6. Migration from v1

A one-off, re-runnable importer reads the cleaned v1 `gym.db` (read-only) and
writes:

- the 35 movements → `exercises`, with every historical v1 name seeded as an alias;
- 22 strength sessions → `workouts` + `workout_sets` (dead hang as seconds);
- body metrics (2 rows) and the single manual cardio session;
- the owner's stated v1 preferences → Hermes seed memory in the private store
  (personal data; not reproduced in this repository).

Cut-over: once logging works (phase 2), stop logging in v1; after phase 5,
retire the v1 service.

**Apple Health is out of scope.** v1's sync never worked (no import was ever
recorded) and only produced a daily "not imported for five days" nag. v2 has no
Health endpoint and no staleness nudge; cardio is logged in the app.

## 7. Phases

Each phase is one or more gated pull requests.

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 0a | **Quality gate** — pinned toolchains, policy checker, lint/type/test/coverage/mutation/dependency/reproducibility gates, CI workflows, CODEOWNERS, branch-protection script | All required checks green on the bootstrap PR; branch protection applied |
| 0b | **Runtime skeleton** — service user, data directory, systemd units, `tailscale serve` HTTPS, deploy + backup scripts, all driven by `deploy/local.env` | A health page loads on the phone over the tailnet |
| 1 | **Data** — schema, migrations, catalogue + aliases, v1 importer, read-only history API and screens | Imported history visible on the phone |
| 2 | **Logging** — exercise picker, ad-hoc logging, offline queue, workouts | Old bot no longer needed for logging |
| 3 | **Hermes** — gateway + `trainer` profile, MCP tools, Coach tab, nightly memory commit to the private store | Coach remembers across turns and days |
| 4 | **Programs** — `propose_program`, Today screen, supersets, rest timer, progression + deload engine | A full week trained from the app |
| 5 | **Cut-over** — Web Push, retire v1 | `gym.service` stopped |

## 8. Owner actions required

- Apply branch protection with `scripts/configure_repository.sh` (needs repo
  admin; private-repo branch protection needs GitHub Pro or higher).
- Enable **HTTPS certificates** in the Tailscale admin console (DNS page).
- Reconnect Tailscale on the phone.
- Revoke the unused Telegram bot token that was shared in chat (BotFather `/revoke`).
