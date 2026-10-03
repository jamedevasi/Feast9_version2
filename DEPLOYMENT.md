# Feast9 — Deployment & Support Manual

For the IT firm that installs, hosts and supports Feast9 for a clinic. It covers what to
provision, how to install and run it as a service, how to secure it, and how to upgrade,
back up, restore and troubleshoot it.

Related documents in this repository:

| Document | Use it for |
|---|---|
| `README.md` | Local / developer setup (not production) |
| `BACKUP.md` | Backup design, scheduling, off-site copies, **restore testing** |
| `THREAT_MODEL.md` | Security assumptions and known residual risks |
| `docs/Feast9_User_Manual.pdf` | End-user manual for clinic staff |
| `CLAUDE.md` | Architecture and implementation notes (for developers) |

---

## 1. What Feast9 is

A web application for a single dental clinic: patients, treatment cases, clinical notes,
prescriptions, dental chart, appointments, lab work, billing, reports, privacy (DPDP Act
2023) requests and backups. Staff use it through a web browser.

| Component | Technology |
|---|---|
| Application | Python 3, Flask 3 (server-rendered pages, no JavaScript build step) |
| Database | SQLite 3 — a single file, WAL mode, no database server |
| App server | **Waitress** (Windows) or **Gunicorn** (Linux) |
| HTTPS | **Not built in** — provided by a reverse proxy you install (section 5) |
| PDF / Excel | ReportLab, openpyxl (pure Python) |
| External services | **None required.** Optional: Google sign-in, an off-site backup target |

There is no Node.js, no separate database server, no message queue and no internet
dependency at runtime. Chart.js and the Inter font are bundled with the app.

**Design limits to plan around:**
- One clinic per installation, one server. SQLite is a single file on local disk — do not
  put `DATA_DIR` on a network share, and do not run two servers against the same data.
- Sized for a clinic's staff (tens of concurrent users), not for multi-branch scale.

---

## 2. Choosing a topology

| | A. Single PC | B. Clinic network (recommended for 2+ PCs) | C. Hosted VM |
|---|---|---|---|
| Who connects | Only the PC Feast9 runs on | Several PCs/tablets on the clinic LAN | Clinic over the internet |
| Feast9 listens on | `127.0.0.1` | `127.0.0.1`, behind the proxy | `127.0.0.1`, behind the proxy |
| HTTPS | Not needed (traffic never leaves the PC) | **Required** | **Required** |
| Extra exposure | None | LAN only | Public internet — needs firewalling, VPN or IP allow-list |

**Recommendation:** B, on a dedicated always-on machine in the clinic. Only choose C with a
VPN or IP allow-list in front; Feast9 has no built-in protection against internet-wide attacks
beyond per-account and per-IP sign-in limits.

Never expose the Waitress/Gunicorn port directly to the network — it speaks plain HTTP.

---

## 3. Infrastructure requirements

### Server (recommended minimum)

| Item | Requirement |
|---|---|
| OS | Windows 10/11 Pro or Windows Server 2019+; **or** Ubuntu 22.04/24.04 LTS (or similar Linux) |
| CPU / RAM | 2 cores, 4 GB RAM (the app itself uses well under 500 MB) |
| Disk | SSD. 20 GB free to start. Growth is driven by uploaded X-rays/photos (≤ 15 MB each) and by backups — each backup is a full encrypted copy, and 30 are kept by default. Size accordingly. |
| Disk encryption | **Required:** BitLocker (Windows) or LUKS (Linux). The database and uploads are not encrypted by the app itself. |
| Power | UPS recommended — an abrupt power cut during a write is the main corruption risk for any local database. |
| Clock | Correct time zone and NTP sync (dates, follow-ups and audit times depend on it). |

### Software

| Item | Version |
|---|---|
| Python | **Windows: 3.14** (`requirements-win-py314.txt`). **Linux: 3.11 or 3.12** (`requirements.txt`). |
| Git | To fetch releases (or deliver the code as an archive). |
| Reverse proxy | Topologies B/C: **Caddy** (simplest), nginx, or IIS with URL Rewrite + ARR. |
| Service wrapper | Windows: **NSSM** or WinSW. Linux: systemd. |

Python packages are pinned in the requirements files; no compiler is needed on Windows or
mainstream Linux (wheels are available).

### Client devices

Any current browser: Chrome, Edge, Firefox or Safari. Screens from a phone up to desktop are
supported. Staff using two-step sign-in need an authenticator app on their phone.

### Network

| From | To | Port | Purpose |
|---|---|---|---|
| Clinic devices | Server | 443/TCP | Feast9 over HTTPS (topology B/C) |
| Server | Internet | 443/TCP | Only if Google sign-in or a cloud off-site backup is used |

---

## 4. Installation

Use a dedicated, non-administrator service account (Windows) or system user (Linux) to run
Feast9. The data directory must be writable by that account and by nobody else.

### 4.1 Windows

```powershell
# 1. Code
cd C:\
git clone https://github.com/jamedevasi/Feast9_version2.git Feast9
cd C:\Feast9

# 2. Virtual environment + packages
py -3.14 -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\pip install -r requirements-win-py314.txt

# 3. Data directory (outside the code folder; restrict its permissions to the service account)
mkdir D:\Feast9Data

# 4. Smoke test (Ctrl+C to stop)
$env:DATA_DIR = "D:\Feast9Data"
venv\Scripts\waitress-serve --host=127.0.0.1 --port=8000 wsgi:app
```

Open `http://127.0.0.1:8000` on the server: the first visit shows **Setup** (section 6).

**Run as a Windows service with NSSM** (starts at boot, restarts on failure):

```powershell
nssm install Feast9 C:\Feast9\venv\Scripts\waitress-serve.exe "--host=127.0.0.1 --port=8000 --threads=8 wsgi:app"
nssm set Feast9 AppDirectory C:\Feast9
nssm set Feast9 AppEnvironmentExtra DATA_DIR=D:\Feast9Data SESSION_COOKIE_SECURE=1 TRUSTED_PROXY_COUNT=1 FLASK_DEBUG=0 BACKUP_KEY_FILE=D:\Feast9Keys\backup.key
nssm set Feast9 ObjectName .\feast9svc <password>
nssm set Feast9 AppStdout D:\Feast9Logs\feast9.log
nssm set Feast9 AppStderr D:\Feast9Logs\feast9.log
nssm set Feast9 AppRotateFiles 1
nssm set Feast9 AppRotateBytes 10485760
nssm start Feast9
```

Do not use `run.py` or `start.bat` for a deployment — they start Flask's development server.

### 4.2 Linux

```bash
sudo useradd --system --home /opt/feast9 --shell /usr/sbin/nologin feast9
sudo git clone https://github.com/jamedevasi/Feast9_version2.git /opt/feast9/app
cd /opt/feast9/app
sudo python3.12 -m venv venv
sudo venv/bin/pip install -r requirements.txt
sudo mkdir -p /var/lib/feast9 /etc/feast9
sudo chown -R feast9:feast9 /opt/feast9 /var/lib/feast9
sudo chmod 700 /var/lib/feast9
```

`/etc/systemd/system/feast9.service`:

```ini
[Unit]
Description=Feast9
After=network.target

[Service]
User=feast9
Group=feast9
WorkingDirectory=/opt/feast9/app
Environment=DATA_DIR=/var/lib/feast9
Environment=SESSION_COOKIE_SECURE=1
Environment=TRUSTED_PROXY_COUNT=1
Environment=FLASK_DEBUG=0
Environment=BACKUP_KEY_FILE=/etc/feast9/backup.key
ExecStart=/opt/feast9/app/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 --timeout 120 wsgi:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now feast9
sudo journalctl -u feast9 -f      # logs
```

Two workers is the tested configuration (SQLite WAL + busy timeout handle the concurrency).
Don't go much higher; more workers do not help with a single SQLite file.

### 4.3 Environment variables

| Variable | Required | Value / purpose |
|---|---|---|
| `DATA_DIR` | **Yes** | Absolute path of the data directory (section 7). Defaults to `./data` — never rely on the default in production. |
| `SESSION_COOKIE_SECURE` | **Yes** behind HTTPS | `1` — the login cookie is only sent over HTTPS. Leave unset only for topology A. |
| `TRUSTED_PROXY_COUNT` | **Yes** behind a proxy | `1` when one reverse proxy (Caddy/nginx/IIS) sits in front, so Feast9 takes the user's real address and `https` from the proxy's `X-Forwarded-*` headers (section 5.2). Leave unset for topology A — never set it when Feast9 is reachable without the proxy. |
| `FLASK_DEBUG` | Yes | `0` (or unset). Never `1` in production. |
| `SECRET_KEY` | No | Leave unset. Feast9 generates a random key on first start in `DATA_DIR/secret_key`. If you manage it yourself, use 32+ random bytes; changing it logs everyone out. |
| `BACKUP_KEY_FILE` | Recommended | Where the backup encryption key is written by **Set Up Backups**. Default is `~/.feast9/backup.key` *of the account running Feast9* — for a service account set it explicitly, outside `DATA_DIR`. |
| `BACKUP_ENCRYPTION_KEY` | No | Alternative to the key file (takes precedence). See `BACKUP.md`. |
| `BACKUP_OFFSITE_COMMAND` | No | Shell command run after each backup with `{file}` substituted (e.g. an `rclone copy`). Used when no copy folder is set in the app. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | No | Enables optional Google sign-in. Leave unset to keep it fully disabled. See section 5.3 before enabling. |

---

## 5. HTTPS and the reverse proxy (topologies B and C)

### 5.1 Caddy (recommended)

`Caddyfile` for a LAN install with an internal certificate:

```
feast9.clinic.lan {
    tls internal
    reverse_proxy 127.0.0.1:8000
    request_body {
        max_size 16MB
    }
    header Strict-Transport-Security "max-age=31536000"
}
```

- `tls internal` makes Caddy its own certificate authority: install Caddy's root certificate
  on each clinic device once, so browsers trust it. With a public domain and DNS, use a normal
  Let's Encrypt certificate instead.
- Give the server a fixed IP and a DNS name (router DNS, or a hosts-file entry per device).
- Uploads are capped at 15 MB by Feast9; the proxy limit must be at least that.
- Feast9 does not send an HSTS header itself — set it at the proxy as above.

nginx/IIS equivalents work the same way: terminate TLS, forward to `127.0.0.1:8000`, allow
16 MB request bodies, add HSTS.

### 5.2 Telling Feast9 about the proxy: `TRUSTED_PROXY_COUNT=1`

Behind a proxy every connection reaches Feast9 from the proxy itself (`127.0.0.1`). With
`TRUSTED_PROXY_COUNT=1`, Feast9 uses the `X-Forwarded-For`, `-Proto` and `-Host` headers the
proxy adds instead, so that:

- the **per-IP** sign-in limit counts each device separately (otherwise a few failed
  sign-ins by anyone briefly block sign-in for the whole clinic);
- the **audit log** records each user's device address;
- links Feast9 builds, such as the Google sign-in return address, use `https://` and the
  clinic's host name.

Caddy sends these headers by default; nginx needs `proxy_set_header` lines for
`X-Forwarded-For` (`$proxy_add_x_forwarded_for`), `X-Forwarded-Proto` and `X-Forwarded-Host`;
IIS ARR sends `X-Forwarded-For` and needs the other two added. Set the value to the number of
proxies in the chain — normally 1.

Only set it when **every** connection goes through the proxy (Feast9 bound to `127.0.0.1`).
If Feast9 were reachable directly, anyone could send these headers and pose as another
address. Without the variable the headers are ignored.

### 5.3 Google sign-in (optional)

Only enable if the clinic wants it. It requires `TRUSTED_PROXY_COUNT` (section 5.2) so the
return address is built as `https://…`, and the clinic's Google Cloud OAuth client must list
`https://<feast9-host>/login/google/callback` as an authorised redirect URI.

---

## 6. First-run setup (with the clinic)

1. Browse to Feast9. The **Setup** page creates the first administrator account. Use a
   named account for the clinic's administrator — not a shared or vendor account.
2. **Settings → Clinic Details**: name, address, phone, email (they appear on every printout).
3. **Settings → Doctors**: each doctor with qualifications and registration number
   (printed on prescriptions).
4. **Settings → Users**: one account per staff member with the right role
   (Administrator, Doctor, Guest doctor, Receptionist).
5. **Settings → Sign-in Security**: require two-step sign-in (at least for doctors and
   administrators). **Settings → Automatic Logout**: idle timeout (default 30 minutes).
6. **Settings → Backup & Data → Set Up Backups**: creates the backup key and the first
   backup. Store the key **off the server** (password manager or printed and locked away),
   set a **copy folder** on a different disk or machine, and confirm automatic daily
   backups are on (section 8).
7. Optional: import patients from the earlier Feast9 version with **Import from Excel**
   on the same page (template provided there).

Optional for a trial only: `python seed_demo_data.py` loads demo data. Never run it, or
`dev_bootstrap.py`, against a clinic's live data directory.

---

## 7. Data directory

Everything the clinic owns lives under `DATA_DIR`:

| Path | Contents |
|---|---|
| `feast9.db` (+ `-wal`, `-shm`) | The database. Never copy the `.db` file alone while Feast9 runs — use a Feast9 backup. |
| `clinical_uploads/` | X-rays, photos, lab reports (UUID file names) |
| `uploads/` | Older on-screen consent signatures |
| `branding/` | Clinic logo / login image |
| `backups/` | Encrypted backups (`feast9-backup-*.tar.enc`) |
| `secret_key` | Session-signing key — keep private; not included in backups |

The backup key (`BACKUP_KEY_FILE`) is deliberately **outside** `DATA_DIR`.

Permissions: readable/writable only by the service account and administrators. Exclude
`DATA_DIR` from antivirus real-time scanning of `.db`/`-wal` files if the AV causes locking.

Remove stray copies of patient data from the server (old `*.db` copies, test folders) — they
are unencrypted outside BitLocker and outside the backup rotation.

---

## 8. Backups and restore

Full details are in `BACKUP.md`. The essentials for the support firm:

- **Automatic:** once **Set Up Backups** is done, Feast9 makes an encrypted backup every day
  at the configured time while it is running, plus a catch-up after downtime. Optionally also
  schedule `venv\Scripts\python run_backup.py` (Task Scheduler / cron) with the same
  environment variables.
- **Off-site:** set the **copy folder** in the app (USB/NAS/synced cloud folder) or
  `BACKUP_OFFSITE_COMMAND` (e.g. rclone). Without one, a disk failure loses the backups too.
- **Plan B:** the **Excel Copy** on Backup & Data is a readable spreadsheet of all records for
  use if Feast9 itself is down. It is not encrypted — store it accordingly.
- **Monitoring:** the Dashboard shows administrators a warning when the last backup failed or
  is older than 26 hours. The Backup & Data tiles show the same.
- **Restore** is a command-line action only (`restore_backup.py`), never from the web page:
  stop the service, run the script with the backup file (it makes a safety copy of the current
  database first and needs `--force` to overwrite), start the service.
- **Restore testing is part of the support contract:** at least quarterly, restore the latest
  backup into an empty test `DATA_DIR` on a non-production machine, start Feast9 against it,
  sign in, open a few patients and an attachment. Record the result.

---

## 9. Security hardening checklist

- [ ] Disk encryption (BitLocker/LUKS) on the server and on any machine/drive holding backups
      or Excel copies.
- [ ] HTTPS via the reverse proxy; `SESSION_COOKIE_SECURE=1`; `TRUSTED_PROXY_COUNT=1`; HSTS at the proxy.
- [ ] Feast9 bound to `127.0.0.1` only; firewall allows only 443 from the clinic LAN (and
      nothing from the internet unless topology C with VPN/allow-list).
- [ ] `FLASK_DEBUG` off; service runs as a dedicated non-admin account.
- [ ] `DATA_DIR` and the backup key file permission-restricted; backup key also stored off
      the server.
- [ ] Two-step sign-in required for administrators and doctors.
- [ ] One named account per person; no shared logins; leavers deactivated the same day.
- [ ] OS security updates applied monthly; Python packages updated with each Feast9 release.
- [ ] Shared front-desk PCs: separate Windows user, screen lock, browser not saving passwords.
- [ ] Stray data copies removed from the server (section 7).

Feast9 already provides: hashed passwords with strength rules, per-account lockout (5
failures → 15 minutes), idle and 12-hour session expiry, step-up re-authentication for
sensitive actions, CSRF protection, a strict Content-Security-Policy, `no-store` caching for
patient pages, server-side role enforcement and an audit log of sign-ins, record views and
changes. See `THREAT_MODEL.md` for residual risks.

---

## 10. Upgrading to a new release

1. Announce a short downtime to the clinic.
2. **Back Up Now** (Backup & Data) — or `run_backup.py` — and confirm it completed.
3. Stop the service.
4. Update the code (`git pull`, or replace the code folder — never touch `DATA_DIR`).
5. `venv\Scripts\pip install -r requirements-win-py314.txt` (Linux: `requirements.txt`).
6. Start the service. Database changes are applied automatically at start-up and are
   additive only (columns/tables are added, never dropped or renamed).
7. Sign in and check the Dashboard, a patient, a case and the Backup & Data tiles.

Rollback: stop the service, restore the previous code, restore the pre-upgrade backup with
`restore_backup.py --force`, start.

Optionally run the test suite on a staging copy before upgrading production:
`pip install -r requirements-dev.txt` then `pytest` (about 20–30 minutes).

---

## 11. Operations and support runbook

### Logs

- Windows/NSSM: the file set in `AppStdout` (e.g. `D:\Feast9Logs\feast9.log`).
- Linux: `journalctl -u feast9`.
- Business-level events (sign-ins, failed sign-ins, lockouts, record views, changes,
  exports, backups) are in **Settings → Audit Log**, visible to administrators.

### Health checks

- `GET /login` returns 200 when the app is up.
- Backup freshness: Backup & Data tiles, or the most recent row there.
- Disk space on the `DATA_DIR` volume (backups grow it steadily).

### Common requests

| Request | Action |
|---|---|
| User forgot password | Administrator: **Users → Set Password**. Users with two-step sign-in can self-reset from the sign-in page. |
| The only administrator forgot their password | On the server, with the same `DATA_DIR`: `venv\Scripts\python reset_admin_password.py` (audited; ends that account's sessions). |
| Account locked | Wait 15 minutes, or administrator: **Users → Unlock**. |
| Lost phone (two-step sign-in) | Administrator: **Users → Reset 2FA**; the user sets it up again. |
| Staff member leaves | Administrator: **Users → Deactivate** (ends their sessions immediately). |
| "Everyone was logged out" | Expected after `SECRET_KEY` / `secret_key` changes, or after the service restarts with a different key. |
| Sign-ins blocked for everyone for a few minutes | `TRUSTED_PROXY_COUNT` is not set behind the proxy (section 5.2). |
| "Database is locked" errors | Check antivirus/backup software holding `feast9.db`; make sure only one Feast9 service uses the `DATA_DIR`. |
| Backup tile red | Check the key file is present (`BACKUP_KEY_FILE`), disk space, and the copy folder path; then **Back Up Now**. |
| Server lost | New server → install (section 4) → restore latest backup → place the backup key → start. |

### Things that must not be done

- Editing `feast9.db` by hand or with a SQL tool on the live system.
- Copying the live `feast9.db` as a "backup" — use Feast9 backups.
- Running `seed_demo_data.py` or `dev_bootstrap.py` against live data.
- Enabling `FLASK_DEBUG=1` or exposing port 8000 to the network.
- Deleting old backups or the backup key without the clinic's written approval.

---

## 12. Responsibilities (suggested split)

| Area | Support firm | Clinic administrator |
|---|---|---|
| Server, OS, disk encryption, UPS, network, proxy, certificates | ✔ | |
| Feast9 installation, upgrades, service health, logs | ✔ | |
| Backup monitoring, off-site copy, quarterly restore test | ✔ | informed |
| Backup key safekeeping | holds a sealed copy if agreed | ✔ holds the key |
| User accounts, roles, clinic settings | on request | ✔ |
| Privacy requests and patient data decisions | | ✔ (doctor/administrator) |
| Incident / suspected breach | technical investigation | decisions and notifications under the DPDP Act |

Support staff should not hold a Feast9 user account with access to patient data unless the
clinic grants one for a specific task, and it should be deactivated afterwards.
