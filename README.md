<p align="center">
  <img src="web/public/icon-192.png" width="112" alt="Coach logo">
</p>

<h1 align="center">Coach</h1>

<p align="center">
  A private, phone-first strength-training app with structured programs, offline logging and a coach that remembers.
</p>

## How it works

Coach keeps the training record in SQLite and uses clear progression rules to
choose the next session, target reps and load. Workouts can be logged without a
connection and sync when the phone is back online. Hermes handles conversation,
program changes and long-term coaching context.

## Screens

| Home | Today's workout |
| :---: | :---: |
| <img src="docs/screenshots/home.png" width="300" alt="Coach home screen"> | <img src="docs/screenshots/today.png" width="300" alt="Today's planned workout"> |
| Program | Coach |
| <img src="docs/screenshots/program.png" width="300" alt="Training program"> | <img src="docs/screenshots/coach.png" width="300" alt="Coach conversation"> |

## Running it

The React PWA and FastAPI service run on a private host and are served to the
owner over Tailscale. See [deployment](docs/DEPLOY.md) for installation and
[development](docs/DEVELOPMENT.md) for the toolchain and quality checks.
