# Deploying

The app runs on one Linux host as an unprivileged systemd service bound to
loopback, and is published to the owner's tailnet with `tailscale serve`. Every
host-specific value lives in `deploy/local.env`, which is git-ignored; the
committed `deploy/local.env.example` documents the keys with placeholders.

## Requirements on the host

- systemd, `python3` (3.13) with `venv`, `curl`, `git`, `useradd`
- `uv`, `git`, Node (see `web/.nvmrc`) and pnpm (Corepack) for the unprivileged
  build step, which also fetches the pinned Hermes release from GitHub
- an API key for the model provider (an OpenAI-compatible endpoint, D13)
- Tailscale with HTTPS certificates enabled for the tailnet, and an ACL that
  lets only the owner's devices reach port 443 on the host

## First install

```console
cp deploy/local.env.example deploy/local.env   # then edit every value
./deploy/build.sh                              # as your user: wheels, locked requirements, units
sudo ./deploy/install.sh                       # user, data dir, venvs, units, health checks
sudo ./deploy/hermes-secrets.sh                # the model API key (asked for), starts the coach
sudo ./deploy/push-secrets.sh                  # the VAPID key pair for notifications, starts the sender
sudo ./deploy/tailscale-serve.sh               # publish on https://<host>.<tailnet>.ts.net/
```

## Safety checks

Two layers, both failing closed:

1. **Configuration** (`build.sh` → `python -m trainer.deploy render`):
   - the bind address must be loopback;
   - `TRAINER_USER` must be a valid name other than `root` or `nobody`;
   - `TRAINER_DATA_DIR` must be a dedicated directory inside `/srv`, `/var/lib`,
     `/mnt` or `/media`, and `TRAINER_PREFIX` one inside `/opt` or `/usr/local`
     (not the root itself, plain segments only). The two sets of roots are
     disjoint, so the service-writable data can never contain or be the
     root-owned code, and `/home` (hidden by `ProtectHome=yes`) is excluded;
   - unknown or duplicate keys are rejected.
   - `TRAINER_OWNER_LOGIN` must look like a Tailscale login (no spaces or `%`).
   - `TRAINER_HERMES_PORT` must differ from `TRAINER_BIND_PORT` (both bind
     loopback); `TRAINER_MODEL_URL` must be HTTPS with no credentials, query or
     characters systemd or Hermes would expand; `TRAINER_MODEL` must be a plain
     model id.
2. **Host preflight** (`install.sh` → `python -m trainer.deploy preflight`, run
   from the bundled wheel before anything is changed):
   - an existing service account must be a dedicated system account (uid 1–999,
     same-named primary group, home `/nonexistent`, nologin shell); a same-named
     group without that user is refused;
   - an existing data directory must be a real directory already owned by that
     account; its existing ancestors must be real directories owned by root or by
     the admin running `sudo` (a data drive mounted as your own user is fine), and
     writable by nobody else;
   - an existing prefix must be a real, root-owned directory writable by nobody
     else, and either empty or already marked `.hermes-trainer`; its ancestors must
     be root-owned and writable by nobody else.

`install.sh` and `tailscale-serve.sh` only read the validated, shell-quoted
`build/deploy/install.env`.

## Who can use it

`tailscale serve` adds a `Tailscale-User-Login` header to every request from a
user-owned device on the tailnet. The API answers only when that header equals
`TRAINER_OWNER_LOGIN`; everything except `/healthz` returns 403 otherwise,
including requests from tagged devices (they carry no identity). This sits on top
of the tailnet ACL, which already limits who can reach the host at all.

## The coach (Hermes)

The coach is a [Hermes](https://github.com/NousResearch/hermes-agent) gateway,
`trainer-coach.service`, running as the service user. Only the API talks to
it, over loopback (`TRAINER_HERMES_PORT`); it is never published with
`tailscale serve`.

**Install.** `build.sh` checks out the Hermes release pinned in it (tag and
commit, which must match), builds a wheel and exports Hermes's own hash-pinned
requirements. `install.sh` puts them in a separate virtualenv,
`<prefix>/hermes`, then copies the profile from `hermes/` (`config.yaml`,
`SOUL.md`) into the coach's home, `<data dir>/hermes`. Edits made there on the
host are overwritten on the next install. Bundled Hermes skills are opted out,
and runtime package installs are off. To upgrade Hermes, change `hermes_tag`
and `hermes_commit` in `build.sh` in a reviewed PR.

**Model.** `TRAINER_MODEL_URL` (an OpenAI-compatible base URL, HTTPS) and
`TRAINER_MODEL` (the model id) in `deploy/local.env`. The API key is stored
by `sudo ./deploy/hermes-secrets.sh`, which reads it from the terminal (or
stdin) and never takes it as an argument. It writes two root-only files that
systemd hands to the gateway as environment variables:
- `/etc/hermes-trainer/model.env`, the provider key;
- `/etc/hermes-trainer/gateway.env`, the key the gateway's API checks. This one
  is generated once; `--rotate-gateway-key` replaces it.

Run the script again to change the provider key. Until both files exist,
`install.sh` leaves the gateway stopped.

**What it can do.** Memory, skills, session search, a to-do list, clarifying
questions, and the trainer's tools. That's all: no terminal, files, web,
browser or code execution (`hermes/config.yaml` allows these toolsets and
removes the rest).

**The trainer's tools.** The gateway starts `python -m trainer.mcp` from the
trainer's virtualenv and talks MCP to it over stdin and stdout. It reads the
training log read-only, through six tools: `recent_workouts`, `get_workout`,
`list_exercises`, `exercise_history`, `body_weight` and `current_program` (the
program being trained, its next day, and any proposal). It runs in the coach's
sandbox, where the data directory is read-only. SQLite can read a WAL database
from there only while its `-wal` and `-shm` files exist, so the API holds one
connection open for as long as it runs, and `trainer-coach` starts after it.
If the API is down, the tools answer that the log cannot be read.

**Proposing a program.** The seventh tool, `propose_program`, is the coach's
only write. It sends the program to the API at `TRAINER_API_URL` (the API's loopback
address, set by `trainer-coach.service`) with the gateway's key, which the API
accepts on `PUT /api/programs/proposal` and nowhere else. The API saves it as a
proposal; the owner accepts it in the app. `hermes/config.yaml` passes the URL
and the key to the tool server as its only environment besides the data
directory; Hermes keeps the `${API_SERVER_KEY}` name, not the key, in the
config file it may rewrite.

**The Coach tab's endpoints.** The API talks to the gateway at
`TRAINER_HERMES_URL` (the gateway's loopback address), with the key from
`/etc/hermes-trainer/gateway.env`. That file is optional for `trainer-api`, so
the API starts before the coach's secrets exist; until then the Coach
endpoints answer 503. `hermes-secrets.sh` restarts both units. The id of the
tab's one Hermes session is kept in the database (`coach` table).

**Memory.** What the coach learns is written straight to `memories/` and
`skills/` in its home. Every night at 03:15, `trainer-memory.timer` commits
those two directories, and nothing else, to a private git repository,
`<data dir>/hermes-memory.git`. Each learned fact is then a diff you can read
and revert. The repository is local only: the job has no network, and it
refuses to run if the repository has a remote. It is personal data and never
goes in this repository. To read it, run as the service user:

```console
sudo -u <user> git --git-dir=<data dir>/hermes-memory.git log -p
```

To revert a fact, check out the old version of the file into the coach's home
with `--work-tree=<data dir>/hermes`, then restart the gateway.

## Notifications (Web Push)

The app tells the owner when the coach has answered and they were not watching,
through Web Push to the phone, and always in the app's inbox. The design and
what is notified are in [STATUS.md](STATUS.md) (phase 5).

**Keys.** `sudo ./deploy/push-secrets.sh` makes the server's VAPID key pair
(P-256) with the installed virtualenv, once, into two root-only files:
- `/etc/hermes-trainer/push.env`, the private key, which signs every push;
  only `trainer-push.service` gets it;
- `/etc/hermes-trainer/push-public.env`, the public key, which browsers
  subscribe with; `trainer-api.service` serves it.

Running it again keeps the pair, and writes the public file again if it does not
match the private key (the private key decides). `--rotate` makes a new pair:
the sender then forgets every subscription made with the old key, and each
phone has to turn notifications on again in Settings. Until the files exist the app
says notifications are not set up, and `install.sh` leaves the sender stopped.

`TRAINER_PUSH_CONTACT` in `deploy/local.env` (a `mailto:` address or an HTTPS
page) is sent, signed, with every push, so a push service can reach the sender.

**The sender.** `trainer-push.service` runs `python -m trainer.push serve`. Every
2 seconds it pushes the notices that have come due to every subscribed browser:
encrypted for that browser (RFC 8291), signed (RFC 8292), over HTTPS with no
proxy and no redirects, and only to Apple's, Google's, Mozilla's or Microsoft's
push services. A browser whose subscription has ended is forgotten.

**Its network.** The API keeps `IPAddressDeny=any`: it never talks to the
internet. The sender is the one unit of the app's own with a route out, and it
is refused everything nearer than the internet: loopback (so neither the API
nor the coach), link-local, multicast, the private ranges and the tailnet's
range. It still needs DNS, so `install.sh` writes a drop-in,
`/etc/systemd/system/trainer-push.service.d/resolvers.conf`, allowing exactly
the resolvers `/etc/resolv.conf` names. If they change, run `install.sh` again.

## Common exercises

`python -m trainer.manage seed-exercises --database <data dir>/trainer.db` adds
the common exercises in `src/trainer/data/common_exercises.csv` that the
catalogue does not have yet. It can be run again at any time. Add `--dry-run` to list them
first. An exercise counts as already there when a catalogued one with the same
equipment has the same words, not counting equipment words, or a nearly
identical spelling. Your "Dips" keeps "Dip" out, while "Incline Bench Press"
still goes in beside "Barbell Bench Press". Run it as the service user, with
the installed virtualenv.

## On the phone

Open the served address in Safari, tap **Share → Add to Home Screen**. The app
then opens full screen from its own icon, keeps working without signal
(reads come from the last copy, writes wait on the phone and sync later), and
picks up new versions on the next launch with a connection. The Coach tab
needs a connection: a message that cannot be sent goes back into the box.

## Upgrade

Pull, then run `./deploy/build.sh` and `sudo ./deploy/install.sh` again. The
installer:
- builds fresh virtualenvs from the hash-pinned requirements and swaps them into
  place;
- reinstalls the units and restarts the API, then the coach.

It exits non-zero, with the service's recent logs, if the API's `/healthz` does
not answer within 20 seconds, or the gateway's `/health` within 60. New keys in
`deploy/local.env.example` must be added to `deploy/local.env` first; the
build names any that are missing.

## What gets installed

| Unit | Runs | Notes |
| --- | --- | --- |
| `trainer-api.service` | `python -m trainer.api` (JSON API under `/api`, the built web app at `/`) | Loopback only (`IPAddressAllow=localhost`), read-only system, writable data directory only, no capabilities, `@system-service` syscalls |
| `trainer-backup.timer` → `trainer-backup.service` | `python -m trainer.deploy backup` nightly at 03:30 | SQLite online backup into `<data dir>/backups`, keeps `TRAINER_BACKUP_KEEP`; no network at all |
| `trainer-coach.service` | `hermes gateway run` (the coach; its API on loopback) | Writes only `<data dir>/hermes`; secrets from root-only `EnvironmentFile`s; outbound network for the model provider; read-only system, no capabilities, `@system-service` syscalls |
| `trainer-push.service` | `python -m trainer.push serve` (the push sender) | Pushes due notices to subscribed browsers; VAPID key from a root-only `EnvironmentFile`; outbound network to the internet only (loopback, LAN and tailnet denied; the resolvers allowed by a drop-in); writes the data directory only |
| `trainer-memory.timer` → `trainer-memory.service` | `python -m trainer.deploy memory-commit` nightly at 03:15 | Commits `memories/` and `skills/` to `<data dir>/hermes-memory.git`; writes only that repository; no network at all |

Code is root-owned under `TRAINER_PREFIX`; the service user can write only
`TRAINER_DATA_DIR`. Inspect the sandbox with
`systemd-analyze security trainer-api.service`.

## Importing v1 history

After an install, import (or re-import) the v1 gym bot's history:

```console
sudo ./deploy/import-v1.sh --dry-run <path to the v1 gym.db>   # what would change; writes nothing
sudo ./deploy/import-v1.sh <path to the v1 gym.db>
```

The script takes an online SQLite backup of the v1 database into a private
temporary directory, and runs `python -m trainer.manage import-v1` as the
service user against that copy. The backup is read through a read-only
connection (`mode=ro`) made as the v1 database's own owner, so the v1
database is never written and any file SQLite keeps beside it stays that
owner's. Never copy a live SQLite file with `cp`/`cat`: in WAL mode recent
changes live in the `-wal` file, and a raw copy silently misses them.

Re-running replaces everything previously imported from v1 in one
transaction; exercise ids stay stable, but the v1 workouts get new ids.
`--dry-run` re-imports into a copy of the database held in memory and lists
every workout, set, body metric and cardio session that would be added or
removed, and every exercise and alias the import would add or change.

## Operations

```console
systemctl status trainer-api.service
journalctl -u trainer-api.service -f
systemctl list-timers trainer-backup.timer trainer-memory.timer
sudo systemctl start trainer-backup.service     # back up now
systemctl status trainer-coach.service
journalctl -u trainer-coach.service -f
journalctl -u trainer-push.service -f          # pushes sent, failed, subscriptions ended
sudo systemctl start trainer-memory.service     # commit the coach's memory now
tailscale serve status
```

Never use `tailscale funnel`: it would publish the app to the internet.
