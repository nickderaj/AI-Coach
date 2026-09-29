# Deploying

The app runs on one Linux host as an unprivileged systemd service bound to
loopback, and is published to the owner's tailnet with `tailscale serve`. Every
host-specific value lives in `deploy/local.env`, which is git-ignored; the
committed `deploy/local.env.example` documents the keys with placeholders.

## Requirements on the host

- systemd, `python3` (3.13) with `venv`, `curl`, `useradd`
- `uv` for the unprivileged build step
- Tailscale with HTTPS certificates enabled for the tailnet, and an ACL that
  lets only the owner's devices reach port 443 on the host

## First install

```console
cp deploy/local.env.example deploy/local.env   # then edit every value
./deploy/build.sh                              # as your user: wheel, locked requirements, units
sudo ./deploy/install.sh                       # user, data dir, venv, units, health check
sudo ./deploy/tailscale-serve.sh               # publish on https://<host>.<tailnet>.ts.net/
```

`build.sh` validates `local.env` (`python -m trainer.deploy render`) and refuses
unsafe values: a non-loopback bind address, relative or unusual paths, invalid
user names, or unknown keys. `install.sh` and `tailscale-serve.sh` only read the
validated, shell-quoted `build/deploy/install.env`.

## Upgrade

Pull, then run `./deploy/build.sh` and `sudo ./deploy/install.sh` again. The
installer builds a fresh virtualenv from the hash-pinned requirements, swaps it
into place, reinstalls the units and restarts the API; it exits non-zero with the
service's recent logs if `/healthz` does not answer within 20 seconds.

## What gets installed

| Unit | Runs | Notes |
| --- | --- | --- |
| `trainer-api.service` | `python -m trainer.api` | Loopback only (`IPAddressAllow=localhost`), read-only system, writable data directory only, no capabilities, `@system-service` syscalls |
| `trainer-backup.timer` → `trainer-backup.service` | `python -m trainer.deploy backup` nightly at 03:30 | SQLite online backup into `<data dir>/backups`, keeps `TRAINER_BACKUP_KEEP`; no network at all |

Code is root-owned under `TRAINER_PREFIX`; the service user can write only
`TRAINER_DATA_DIR`. Inspect the sandbox with
`systemd-analyze security trainer-api.service`.

## Operations

```console
systemctl status trainer-api.service
journalctl -u trainer-api.service -f
systemctl list-timers trainer-backup.timer
sudo systemctl start trainer-backup.service     # back up now
tailscale serve status
```

Never use `tailscale funnel`: it would publish the app to the internet.
