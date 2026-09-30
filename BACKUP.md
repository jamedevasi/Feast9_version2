# Feast9 Backup & Restore

Implements `feast9_v2_agents.md` §14 "Automated off-server backup." The off-site *destination*
(S3 vs Backblaze B2 vs a second server) is an intentionally deferred operational/cost decision
per §15 — this document shows how to point the app at whichever one you pick, without the
app itself depending on any particular provider's SDK or credentials.

## What a backup contains

A single encrypted file, `feast9-backup-<timestamp>.tar.enc`, containing:
- A consistent snapshot of `feast9.db` (taken via SQLite's own backup API, safe to run while
  the app is live under WAL — see `app/backup.py:_snapshot_db`).
- The entire `clinical_uploads/` directory (X-rays, photos, lab reports).

It does **not** contain `SECRET_KEY`, `BACKUP_ENCRYPTION_KEY`, or anything else from the
environment — back those up separately, by a different, out-of-band means (a password
manager, not a file next to the backups).

## Setup from the app (the normal way)

Everything a clinic needs is on **Settings → Backup & Data** (admin-only, password re-entry
required):

- **Set Up Backups** creates the key, writes it to `BACKUP_KEY_FILE` (default
  `~/.feast9/backup.key` — deliberately *outside* `DATA_DIR`), makes the first backup, and
  shows the key once so it can be stored in a password manager or printed. It refuses to run
  if a key already exists, so it can never orphan existing backups. **Show backup key**
  displays it again later (audited `backup_key_viewed`).
- **Backup settings** (stored in the `settings` table): automatic daily backup on/off and its
  time (default 21:00), an optional **copy folder** (USB drive, network share, or a
  OneDrive/Google Drive folder — each backup is copied there), and how many backups to keep
  (default 30 — older files are deleted locally and in the copy folder, their history rows
  marked `removed`).
- **Automatic backups run inside the app**: `run.py` and `wsgi.py` start a timer thread
  (`app.backup.start_backup_scheduler`) that checks once a minute. A backup is due when no
  backup (manual or automatic) has started since the most recent scheduled time — so a missed
  run (computer off at 9 PM) happens as soon as Feast9 next starts. With several worker
  processes, `db.claim_backup_run` lets only one of them run it. Feast9 must be running for
  this; for a server that's always up that's automatic, and the Task Scheduler/cron approach
  below still works as an alternative or in addition.

The environment variables below still work and take precedence: `BACKUP_ENCRYPTION_KEY` over
the key file, and `BACKUP_OFFSITE_COMMAND` is used when no copy folder is set (a shell command
is never settable from the web page).

## Setup by environment variable (alternative)

1. **Generate an encryption key**, independent of `SECRET_KEY` — losing or rotating one must
   never compromise the other:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. **Set it as an environment variable** wherever the app and the backup script run:
   ```powershell
   $env:BACKUP_ENCRYPTION_KEY = "the-key-you-generated"
   ```
   Store this key somewhere durable and separate from `DATA_DIR` — if you lose it, every
   existing backup becomes permanently unreadable. There is no recovery path for a lost key;
   that's the point of encryption.
3. **Run a backup manually once** to confirm it works:
   ```powershell
   venv\Scripts\python run_backup.py
   ```
   This writes to `DATA_DIR/backups/` and records a row in the `backup_log` table, visible at
   `/backup` (admin-only) in the app.

## Scheduling (nightly)

The app does not schedule its own backups — `run_backup.py` is a plain script, meant to be
invoked by whatever the OS already provides for cron-like jobs.

**Windows (Task Scheduler):**
```
Program:   C:\path\to\venv\Scripts\python.exe
Arguments: C:\path\to\run_backup.py
Trigger:   Daily, e.g. 02:00
```
Make sure `DATA_DIR`, `SECRET_KEY`, and `BACKUP_ENCRYPTION_KEY` are set for the account the
task runs as (Task Scheduler actions don't inherit your interactive shell's env vars — set
them via "Add" under the action's environment, or wrap the call in a `.bat` that sets them
first).

**Linux/Mac (cron):**
```cron
0 2 * * * DATA_DIR=/path/to/data SECRET_KEY=... BACKUP_ENCRYPTION_KEY=... /path/to/venv/bin/python /path/to/run_backup.py >> /var/log/feast9-backup.log 2>&1
```

## Off-site destination (your choice — S3, Backblaze B2, or a second server)

Set `BACKUP_OFFSITE_COMMAND` to a shell command that uploads the finished file; `{file}` is
replaced with its local path. [rclone](https://rclone.org/) speaks all three backends behind
the same CLI, so the app never needs provider-specific credentials or an SDK:

```bash
# S3 (after `rclone config` sets up a remote named "s3remote")
BACKUP_OFFSITE_COMMAND='rclone copy "{file}" s3remote:feast9-backups/'

# Backblaze B2 (remote named "b2remote")
BACKUP_OFFSITE_COMMAND='rclone copy "{file}" b2remote:feast9-backups/'

# A second server over SSH
BACKUP_OFFSITE_COMMAND='rsync -avz "{file}" backupuser@second-server:/backups/feast9/'
```

Leave it unset to keep backups local-only (not recommended for production — "automated
off-*server*" is the point). Every run's off-site push result (`success` / `failed: ...` /
`not_configured`) is recorded alongside that run in `backup_log` and shown at `/backup`.

## If a backup fails

- The Backup & Data page shows the status at the top — not set up, last attempt failed, never
  a successful one, or last success more than 26 hours old
  (`app/routes/backup_routes.py:BACKUP_STALE_HOURS`) — with what to do next. Technical error
  detail is in the server log and in the history row's hover text.
- `/backup` (admin-only) shows the full history with error messages.
- Every backup run and every download is written to the audit log (`backup_created`,
  `backup_downloaded`).

## Restoring — and why it's a CLI script, not a web button

Restoring overwrites the live database. That is exactly the kind of action this app avoids
putting behind a web form — `restore_backup.py` is a deliberately separate, local-only script:

```powershell
venv\Scripts\python restore_backup.py path\to\feast9-backup-20260101-020000.tar.enc --force
```

- Requires `BACKUP_ENCRYPTION_KEY` to be set (same key the backup was made with).
- Makes a timestamped safety copy of the current `feast9.db` before overwriting it, whenever
  one exists.
- Refuses to overwrite an existing database unless `--force` is passed — the default run
  against an empty `DATA_DIR` (a clean/staging restore test) doesn't need it.

### Restore-testing is the acceptance bar, not optional

Per §11/§14: **a backup that has never been restore-tested is not considered valid.**
Periodically (e.g. monthly, or after any schema change):

1. Point `DATA_DIR` at a throwaway directory (`$env:DATA_DIR = "C:\temp\feast9-restore-test"`).
2. Run `restore_backup.py` against your most recent backup, with no `--force` needed since
   the directory is empty.
3. Start the app against that `DATA_DIR` and confirm: you can log in, patient/case data is
   present and correct, and clinical attachments open.
4. Delete the throwaway directory.

If any of that fails, today's backups are not actually protecting you — fix it before the next
real incident does the testing for you.
