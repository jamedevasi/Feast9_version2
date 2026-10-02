# Feast9 — Local Deployment Guide

Feast9 is a single-practitioner dental clinic management system: patients, cases,
appointments, billing, dental charting, reports, and more. It's a no-build-step
Flask + raw-SQLite app — no Node, no frontend framework, no separate build step.

This document covers running it **locally** (your own machine, for development or a
single-clinic on-premise install). For the full feature set and architecture, see
`CLAUDE.md` and `feast9_v2_agents.md`. For automated off-server backups, see `BACKUP.md`.

## Prerequisites

- **Python 3.11 or 3.12** (Linux/Mac), or **Python 3.14** (Windows — see the
  Windows-specific requirements file below).
- No database server, no Node/npm, nothing else to install system-wide.

## 1. Get the code and create a virtual environment

```powershell
git clone https://github.com/jamedevasi/Feast9_version2.git
cd Feast9_version2
python -m venv venv
```

## 2. Activate the virtual environment and install dependencies

**Windows (PowerShell):**
```powershell
venv\Scripts\activate
pip install -r requirements-win-py314.txt -r requirements-dev.txt
```

**Linux / Mac:**
```bash
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

`requirements-dev.txt` adds `pytest`, needed only to run the test suite. Windows uses
Waitress instead of Gunicorn as the production WSGI server, since Gunicorn doesn't run
on Windows.

## 3. Set required environment variables

Two environment variables matter for local use:

| Variable | Required | Purpose |
|---|---|---|
| `DATA_DIR` | No (defaults to `./data`) | Where the SQLite database, clinical uploads, backups, and branding images live. Point it anywhere writable. |
| `SECRET_KEY` | No | Signs session cookies. Leave it unset: on first start the app generates a random key and keeps it in `DATA_DIR/secret_key`. Only set it if you manage secrets yourself — then use a long random value. Publicly known values (like the old `local-dev-key` from earlier docs) are ignored with a warning, because anyone who knows the key can forge a login. |

**Windows (PowerShell):**
```powershell
$env:DATA_DIR = "C:\path\to\data"
```

**Linux / Mac:**
```bash
export DATA_DIR="$HOME/feast9-data"
```

A ready-made `start.bat` in the repo root does the Windows activate + env-var + run
steps in one go — edit its `DATA_DIR` line if you want a fixed local setup you can
just double-click.

## 4. Run the app

```powershell
python run.py
```

This starts Flask's development server at **http://127.0.0.1:5000**. The database
schema (and any additive migrations) are created automatically on first run — nothing
to run by hand.

First visit will redirect you to `/setup` to create the initial admin account
(username, password, a security question for self-service password reset). After
that, log in at `/login`.

> The dev server does **not** hot-reload Python code or (with `FLASK_DEBUG` unset)
> cached templates. After pulling new code or editing templates/routes, stop the
> server (Ctrl+C) and run `python run.py` again to pick up the changes.

## 5. (Optional) Seed demo data

To explore the app with realistic sample doctors, case types, patients, and cases
instead of a blank install:

```powershell
python seed_demo_data.py
```

Safe to re-run — it's idempotent and won't duplicate existing rows.

### Faster one-command setup

`dev_bootstrap.py` combines steps 4's `/setup` and this seeding step into one command —
useful for a throwaway local instance where clicking through `/setup` by hand isn't worth it:

```powershell
python dev_bootstrap.py
```

It creates a bootstrap admin account (default username `admin`, password
`DevPassword123!` — override with `--username`/`--password`) only if one doesn't already
exist, then seeds demo data the same as `seed_demo_data.py` (pass `--no-seed` to skip
that part). It prints the login credentials to use at `/login`. Like `seed_demo_data.py`,
it's safe to re-run — it never touches an existing admin account.

## 6. Running the test suite

```powershell
pytest                          # full suite
pytest tests/test_cases.py      # one file
pytest tests/test_cases.py::test_closed_at_only_set_on_explicit_close   # one test
```

Always use the venv's own Python/pytest (`venv\Scripts\pytest` or an activated venv) —
a bare system Python may be missing packages the venv has installed.

## Production-style local run (optional)

To run behind a real WSGI server instead of Flask's dev server (still entirely local):

**Windows:**
```powershell
waitress-serve --host=127.0.0.1 --port=5000 wsgi:app
```

**Linux / Mac:**
```bash
gunicorn wsgi:app
```

For an actual production deployment (not just local), also set
`SESSION_COOKIE_SECURE=1` and `FLASK_DEBUG=0`, and put a real TLS-terminating reverse
proxy in front — this app itself doesn't handle HTTPS.

## Troubleshooting

- **"Address already in use" on port 5000** — another instance is already running
  (check with `netstat -ano | grep :5000` on Windows or `lsof -i :5000` on Linux/Mac)
  and stop it, or run on a different port: edit `run.py`'s `port=5000`, or use
  `waitress-serve --port=5050 ...` / `gunicorn -b 127.0.0.1:5050 wsgi:app`.
- **Forgot a password** — an account with two-step sign-in can reset its own from the
  login page (security answer + a code). Any other account gets a new password from an
  admin (Users > Set Password). For the only admin, run `python reset_admin_password.py`
  (with `DATA_DIR` set the same way as when running the app): an emergency CLI reset that
  doesn't require logging in first, is written to the audit log and signs that account out
  everywhere.
- **Changes not showing up** — see the hot-reload note in step 4; restart the server.
- **`SECRET_KEY is set to a publicly known value` warning** — you set `SECRET_KEY` to a
  value from these docs (e.g. `local-dev-key`). The app ignores it and uses its generated
  key; remove the variable to silence the warning.
- **Everyone was logged out after an update** — expected once, when the app switched from
  a fixed session key to its generated one.

## Related documentation

- `CLAUDE.md` — architecture, conventions, and what's been built so far.
- `feast9_v2_agents.md` — the authoritative product/feature spec.
- `BACKUP.md` — automated off-server encrypted backups (not required for local use).
- `THREAT_MODEL.md` — security assumptions and residual risks.
