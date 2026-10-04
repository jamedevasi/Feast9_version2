# Feast9 — Deployment & Support Manual (cloud hosting)

For the IT firm that hosts and supports Feast9 for a clinic on a cloud server. It covers what
to provision, how to install and run Feast9, how to secure it, and how to back up, restore,
upgrade and troubleshoot it.

Related documents in this repository:

| Document | Use it for |
|---|---|
| `README.md` | Local / developer setup (not production) |
| `BACKUP.md` | Backup design, off-site copies, **restore testing** |
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
| Database | SQLite 3: a single file, WAL mode, no database server |
| App server | **Gunicorn** (Linux) |
| HTTPS | **Not built in.** Provided by a reverse proxy, Caddy (section 5) |
| PDF / Excel | ReportLab, openpyxl (pure Python) |
| External services | **None required.** Optional: Google sign-in. Off-site backups go to object storage you choose |

There is no Node.js, no separate database server, no message queue and no third-party
service at runtime. Chart.js and the Inter font are bundled with the app.

**Design limits that decide the hosting choice:**
- **One server, one running copy.** SQLite is a single file on a local disk. Do not use
  platforms that run several copies of the app or wipe the disk on restart (Cloud Run, App
  Engine, Heroku, Azure App Service, AWS Lambda/Fargate without a persistent volume, Vercel).
  Do not put `DATA_DIR` on a network file system (EFS, Azure Files, NFS, SMB).
- Sized for one clinic's staff (tens of concurrent users), not for multi-branch scale.

---

## 2. Recommended cloud setup

```
 Clinic devices (browsers)
        │  HTTPS 443, from allowed addresses only (section 3.4)
        ▼
 ┌─────────────────────── Cloud VM (India region) ───────────────────────┐
 │  Caddy :443 ── Let's Encrypt certificate, HSTS                        │
 │     │                                                                 │
 │     ▼                                                                 │
 │  Gunicorn 127.0.0.1:8000 ── Feast9 (2 workers, systemd)               │
 │     │                                                                 │
 │     ▼                                                                 │
 │  /var/lib/feast9  (separate encrypted data disk)                      │
 │     feast9.db, clinical_uploads/, backups/                            │
 └──────────────────────────────┬────────────────────────────────────────┘
                                │ nightly encrypted backup (rclone)
                                ▼
                 Object storage bucket, other India region
                 (versioning / object lock, no delete from the VM)
```

### 2.1 Where

Host in an **Indian region**. Patient health records are sensitive personal data under the
DPDP Act. Keeping them in India avoids cross-border transfer questions and keeps latency low.

| Provider | VM region | Second region for backups |
|---|---|---|
| AWS (EC2 or Lightsail) | ap-south-1 Mumbai | ap-south-2 Hyderabad |
| Microsoft Azure | Central India (Pune) | South India (Chennai) |
| Google Cloud (Compute Engine) | asia-south1 Mumbai | asia-south2 Delhi |
| DigitalOcean | BLR1 Bangalore | (use another provider's Indian region) |

### 2.2 Server

| Item | Requirement |
|---|---|
| Type | One ordinary virtual machine (not a container platform or serverless service) |
| OS | Ubuntu 24.04 LTS (Python 3.12 included) |
| CPU / RAM | 2 vCPU, 2–4 GB RAM (the app uses well under 500 MB) |
| OS disk | 20 GB |
| Data disk | A **separate** block-storage volume mounted at `/var/lib/feast9`, SSD. Start at 50 GB. Growth comes from uploaded X-rays/photos (≤ 15 MB each) and from local backups. Each backup is a full copy of database + uploads (see section 8.3 on keep count). |
| Disk encryption | **Required** on both disks. Azure managed disks, Lightsail, GCP and DigitalOcean volumes are encrypted at rest by default. On **AWS EC2, turn on "EBS encryption by default" for the region before creating the disks.** Confirm it in writing to the clinic. |
| Static address | A static / elastic public IP |
| Domain | A DNS name for Feast9, e.g. `feast9.<clinic-domain>.in`, pointing at that IP |
| Time zone | **Asia/Kolkata**. Cloud VMs default to UTC, which is wrong for Feast9 (section 3.3) |

### 2.3 Who owns what

The **clinic should own the cloud account** and pay for it, because it is the data
fiduciary. The support firm works through its own named user with only the permissions it
needs. Turn on multi-factor sign-in for every console user, and do not use the account's root
or owner login for daily work.

---

## 3. Provisioning the server

### 3.1 Create the VM and data disk

1. Create the VM (Ubuntu 24.04, India region, static IP) with SSH **key** authentication only.
2. Create a separate encrypted volume, attach it, format it and mount it at `/var/lib/feast9`
   with an `/etc/fstab` entry (use the UUID and the `nofail` option).
3. Point the domain's DNS `A` record at the static IP.

### 3.2 Base hardening

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y unattended-upgrades python3.12-venv git rclone
sudo dpkg-reconfigure -plow unattended-upgrades       # automatic security updates
```

- SSH: keys only, `PermitRootLogin no`, `PasswordAuthentication no` in `/etc/ssh/sshd_config`.
- One named Linux account per support engineer. No shared logins.

### 3.3 Time zone (do not skip)

Feast9 takes every date and time from the server's local clock: "today" on the
dashboard, follow-up due dates, today's appointments, report periods, lockout times and the
daily backup time. On a UTC server, "today" stays as yesterday until 05:30 in India and
the 21:00 backup runs at 02:30.

```bash
sudo timedatectl set-timezone Asia/Kolkata
timedatectl                       # should show "Asia/Kolkata (IST, +0530)" and "NTP service: active"
```

The service file in section 4.2 also sets `TZ=Asia/Kolkata`, so a later OS change can't move it.

### 3.4 Firewall: who can reach Feast9

Feast9 limits failed sign-ins per account and per address, but it has no protection against
attacks from the whole internet beyond that. Restrict access at the **cloud firewall**
(security group / network security group / VPC firewall), and also with `ufw` on the VM.

| Port | Allow from | Why |
|---|---|---|
| 22/TCP | The support firm's fixed IPs only | SSH |
| 80/TCP | Anywhere | Caddy uses it only to obtain/renew the certificate and to redirect to HTTPS. It serves no Feast9 pages. |
| 443/TCP | See the options below | Feast9 |
| 8000 | **Nobody** | Gunicorn listens on `127.0.0.1` only |

Choose one option for port 443, in this order of preference:

1. **The clinic's fixed public IP only.** This is the simplest and strongest option if the
   clinic's internet connection has a static IP (ask its ISP). Staff can't use Feast9 from
   home unless they also use option 2.
2. **A VPN** (WireGuard or Tailscale) on the VM and on each device. Then port 443 needs no
   public exposure at all. In this case, issue the certificate through a DNS challenge, since
   Let's Encrypt can't reach the server.
3. **Open to the internet.** Only acceptable with two-step sign-in required for **everyone**
   (Settings → Sign-in Security, both boxes ticked) and an administrator checking failed
   sign-ins in the Audit Log weekly.

```bash
sudo ufw default deny incoming
sudo ufw allow from <support-firm-ip> to any port 22 proto tcp
sudo ufw allow 80/tcp
sudo ufw allow from <clinic-ip> to any port 443 proto tcp     # option 1
sudo ufw enable
```

---

## 4. Installation

### 4.1 Code, packages and directories

```bash
sudo useradd --system --home /opt/feast9 --shell /usr/sbin/nologin feast9
sudo git clone https://github.com/jamedevasi/Feast9_version2.git /opt/feast9/app
cd /opt/feast9/app
sudo python3.12 -m venv venv
sudo venv/bin/pip install --upgrade pip
sudo venv/bin/pip install -r requirements.txt

sudo mkdir -p /etc/feast9                 # backup key + rclone config, outside DATA_DIR
sudo chown -R feast9:feast9 /opt/feast9 /var/lib/feast9 /etc/feast9
sudo chmod 700 /var/lib/feast9 /etc/feast9
```

### 4.2 Environment file and service

`/etc/feast9.env` (owned by root, `chmod 600`: systemd reads it, the app account doesn't need to):

```ini
DATA_DIR=/var/lib/feast9
TZ=Asia/Kolkata
SESSION_COOKIE_SECURE=1
TRUSTED_PROXY_COUNT=1
FLASK_DEBUG=0
BACKUP_KEY_FILE=/etc/feast9/backup.key
BACKUP_OFFSITE_COMMAND='rclone copy "{file}" offsite:feast9-backups/ --config /etc/feast9/rclone.conf'
```

`/etc/systemd/system/feast9.service`:

```ini
[Unit]
Description=Feast9
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/var/lib/feast9

[Service]
User=feast9
Group=feast9
WorkingDirectory=/opt/feast9/app
EnvironmentFile=/etc/feast9.env
ExecStart=/opt/feast9/app/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 --timeout 120 wsgi:app
Restart=on-failure
UMask=0077

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now feast9
sudo journalctl -u feast9 -f                          # logs
curl -sI http://127.0.0.1:8000/login | head -1        # expect HTTP/1.1 200
sudo -u feast9 /opt/feast9/app/venv/bin/python -c "import datetime; print(datetime.datetime.now())"
                                                      # must print India time
```

Two workers is the tested configuration (SQLite WAL and the busy timeout handle the
concurrency). More workers don't help with a single SQLite file. Each worker starts the
in-app backup scheduler, and the database ensures only one of them runs a given backup.

Do not use `run.py` or `start.bat` on the server. They start Flask's development server.

### 4.3 Environment variables

| Variable | Required | Value / purpose |
|---|---|---|
| `DATA_DIR` | **Yes** | `/var/lib/feast9`, the data disk (section 7). Never rely on the `./data` default. |
| `TZ` | **Yes** | `Asia/Kolkata` (section 3.3). |
| `SESSION_COOKIE_SECURE` | **Yes** | `1`, so the login cookie is only sent over HTTPS. |
| `TRUSTED_PROXY_COUNT` | **Yes** | `1` with Caddy in front (section 5.2). |
| `FLASK_DEBUG` | Yes | `0` (or unset). Never `1` in production. |
| `SECRET_KEY` | No | Leave unset. Feast9 generates a random key on first start in `DATA_DIR/secret_key`. If you manage it yourself, use 32+ random bytes. Changing it logs everyone out. |
| `BACKUP_KEY_FILE` | **Yes** | `/etc/feast9/backup.key`. **Set Up Backups** writes the key here, outside `DATA_DIR`. |
| `BACKUP_ENCRYPTION_KEY` | No | Alternative to the key file (takes precedence). See `BACKUP.md`. |
| `BACKUP_OFFSITE_COMMAND` | **Yes** | Uploads each finished backup off the VM; `{file}` is replaced with the backup's path (section 8.1). Only used while the **copy folder** in the app is blank. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | No | Enables optional Google sign-in. Leave unset to keep it fully disabled (section 5.3). |

---

## 5. HTTPS and the reverse proxy

### 5.1 Caddy

Install Caddy from its official apt repository (see caddyserver.com/docs/install), then set
`/etc/caddy/Caddyfile`:

```
feast9.<clinic-domain>.in {
    reverse_proxy 127.0.0.1:8000
    request_body {
        max_size 16MB
    }
    header Strict-Transport-Security "max-age=31536000"
}
```

```bash
sudo systemctl reload caddy
```

- Caddy obtains and renews a Let's Encrypt certificate automatically (port 80 must stay open,
  section 3.4). With the VPN option, use a DNS-challenge certificate instead.
- Uploads are capped at 15 MB by Feast9, so the proxy limit must be at least that.
- Feast9 doesn't send an HSTS header itself, so it is set here.

nginx works the same way: terminate TLS, forward to `127.0.0.1:8000`, allow 16 MB request
bodies, add HSTS and the forwarding headers listed in 5.2.

### 5.2 Telling Feast9 about the proxy: `TRUSTED_PROXY_COUNT=1`

Behind a proxy, every connection reaches Feast9 from the proxy itself (`127.0.0.1`). With
`TRUSTED_PROXY_COUNT=1`, Feast9 uses the `X-Forwarded-For`, `-Proto` and `-Host` headers that
the proxy adds instead, so that:

- the **per-IP** sign-in limit counts each device separately (otherwise a few failed
  sign-ins by anyone briefly block sign-in for the whole clinic);
- the **audit log** records each user's real address;
- links that Feast9 builds, such as the Google sign-in return address, use `https://` and
  the clinic's host name.

Caddy sends these headers by default. nginx needs `proxy_set_header` lines for
`X-Forwarded-For` (`$proxy_add_x_forwarded_for`), `X-Forwarded-Proto` and `X-Forwarded-Host`.

Set the value to the number of proxies in the chain. If a CDN or tunnel (e.g. Cloudflare)
also sits in front of Caddy, the chain has two proxies: set `2`, and configure Caddy to trust
the CDN's addresses (`trusted_proxies`) so it passes their header on. **Check it:** sign in,
then open Settings → Audit Log. The address shown must be the clinic's public IP, not
`127.0.0.1` or a CDN address.

Only set the variable while **every** connection goes through the proxy (Gunicorn bound to
`127.0.0.1`). If Feast9 were reachable directly, anyone could send these headers and pose
as another address.

### 5.3 Google sign-in (optional)

Only enable it if the clinic wants it. It needs `TRUSTED_PROXY_COUNT` (section 5.2), and the
clinic's Google Cloud OAuth client must list
`https://<feast9-host>/login/google/callback` as an authorised redirect URI.

---

## 6. First-run setup (with the clinic)

1. Browse to `https://<feast9-host>`. The **Setup** page creates the first administrator
   account. Use a named account for the clinic's administrator, not a shared or vendor
   account. Do this immediately after installation: until Setup is done, anyone who can
   reach the page could complete it.
2. **Settings → Clinic Details**: name, address, phone and email (they appear on every printout).
3. **Settings → Doctors**: each doctor, with qualifications and registration number
   (printed on prescriptions).
4. **Settings → Users**: one account per staff member, with the right role
   (Administrator, Doctor, Guest doctor, Receptionist).
5. **Settings → Sign-in Security**: require two-step sign-in. For a cloud server, tick
   **both** boxes (everyone, receptionists included). **Settings → Automatic Logout**: idle
   timeout (default 30 minutes).
6. **Settings → Backup & Data → Set Up Backups**: creates the backup key and the first
   backup. **Store the key off the server** (the clinic owner's password manager, or printed
   and locked away). Leave the **copy folder blank**: off-site copies go through
   `BACKUP_OFFSITE_COMMAND` (section 8.1), and a copy folder on the same VM would replace
   them. Confirm automatic daily backups are on, and check that the first backup shows
   "Sent" for the off-site copy.
7. Optional: import patients from the earlier Feast9 version with **Import from Excel** on
   the same page (template provided there).

For a trial only, `python seed_demo_data.py` loads demo data. Never run it, or
`dev_bootstrap.py`, against a clinic's live data directory.

---

## 7. Data directory

Everything the clinic owns lives under `DATA_DIR` (`/var/lib/feast9`, on the data disk):

| Path | Contents |
|---|---|
| `feast9.db` (+ `-wal`, `-shm`) | The database. Never copy the `.db` file alone while Feast9 runs; use a Feast9 backup. |
| `clinical_uploads/` | X-rays, photos, lab reports (UUID file names) |
| `uploads/` | Older on-screen consent signatures |
| `branding/` | Clinic logo / login image |
| `backups/` | Encrypted backups (`feast9-backup-*.tar.enc`) |
| `secret_key` | Session-signing key. Keep it private. Not included in backups. |

The backup key (`/etc/feast9/backup.key`) is deliberately **outside** `DATA_DIR`.

Only the `feast9` account (and administrators via `sudo`) may read these files. Don't leave
stray copies of patient data on the VM or on engineers' laptops (old `*.db` copies,
downloaded backups, test folders). They sit outside the backup rotation and outside anyone's
oversight.

---

## 8. Backups and restore

Full details are in `BACKUP.md`. The essentials for a cloud install:

### 8.1 Off-site copy to object storage

A backup that only exists on the VM is lost with the VM, the disk or the cloud account.
Every backup must also go to object storage **in a different region**:

1. Create a bucket (S3 / Azure Blob / GCS / Backblaze B2) in the second region from
   section 2.1. Turn on **versioning**, plus **object lock** or an immutability policy if
   offered, with a retention of at least 90 days.
2. Create an access key that can **list and upload to that bucket only, with no delete
   permission**. If the VM is ever compromised, the attacker can't then destroy the off-site
   history.
3. Add a lifecycle rule that removes copies older than the clinic's chosen retention (for
   example, 1 year). Feast9 does not prune the bucket; its keep count applies only to
   local files.
4. Configure rclone as the app account and test it:
   ```bash
   sudo -u feast9 rclone config --config /etc/feast9/rclone.conf     # create a remote named "offsite"
   sudo chmod 600 /etc/feast9/rclone.conf
   sudo -u feast9 rclone lsd offsite: --config /etc/feast9/rclone.conf
   ```
5. In Feast9, **Back Up Now**. The new history row must show the off-site copy as **Sent**.
   If it says "Not sent", hover over the badge for the error.

Backups are encrypted by Feast9 before upload, so the bucket never holds readable patient data.

### 8.2 The backup key

Without the key, no backup can be restored, not even by the support firm. With the key and
a backup, anyone can read every record.

- The clinic owner holds the key off the server (Settings → Backup & Data → **Show backup
  key**, re-authentication required, audited).
- The support firm holds a sealed copy only if the clinic agrees in writing.
- Never store the key in the same bucket or cloud account as the backups.

### 8.3 Keep count and disk space

Each local backup is a full copy of the database **and** all uploads. Once uploads reach a
few GB, the default 30 local copies fill the data disk. The bucket holds the long history,
so a **local keep count of 7** is enough on a cloud install (Backup & Data → Backup
settings). Watch free space on `/var/lib/feast9`.

### 8.4 Monitoring

The Dashboard shows administrators a warning when the last backup failed or is older than
26 hours, and the Backup & Data tiles show the same. Feast9 makes a backup every day at the
configured time, plus a catch-up after any downtime.

### 8.5 Provider snapshots

Daily snapshots of the data disk (AWS Data Lifecycle Manager, Azure Backup, GCP snapshot
schedules) are a useful extra layer for a fast rebuild. They **do not replace** Feast9
backups: they live in the same cloud account, and a disk snapshot taken mid-write isn't
guaranteed to be consistent. Snapshots must be encrypted and are subject to the same
retention decisions.

### 8.6 Restore

Restore is a command-line action only (`restore_backup.py`), never done from the web page:

```bash
sudo systemctl stop feast9
sudo -u feast9 rclone copy offsite:feast9-backups/<file>.tar.enc /tmp/ --config /etc/feast9/rclone.conf
cd /opt/feast9/app
sudo -u feast9 env DATA_DIR=/var/lib/feast9 BACKUP_KEY_FILE=/etc/feast9/backup.key TZ=Asia/Kolkata \
    venv/bin/python restore_backup.py /tmp/<file>.tar.enc --force
sudo systemctl start feast9
sudo shred -u /tmp/<file>.tar.enc
```

The script makes a safety copy of the current database first, and needs `--force` to
overwrite it.

**Restore testing is part of the support contract.** At least quarterly, create a temporary
VM, install Feast9 (section 4) with an empty `DATA_DIR`, restore the latest **bucket** copy
with the clinic's key, sign in, and open a few patients and an attachment. Record the
result, then delete the test VM **and its disks**.

---

## 9. When the clinic's internet is down

With Feast9 in the cloud, an outage at the clinic means nobody there can open it, even
though Feast9 itself is fine.

- **A second connection:** a mobile hotspot or a second ISP at the front desk. If port 443
  is allow-listed by IP (section 3.4), the backup connection's address won't be on the list.
  Use the VPN option, or agree a procedure to add the address temporarily.
- **Plan B Excel copy:** an administrator downloads **Excel Copy** (Backup & Data) weekly,
  and before planned outages, to one clinic PC. It contains every patient, case, upcoming
  appointment, payment and note in readable form and is **not encrypted**, so keep it only
  on a PC with BitLocker turned on, and delete older copies.
- Work done on paper during the outage is entered afterwards. A payment taken during the
  outage can also be brought in through **Import from Excel** (see the user manual).

---

## 10. Security hardening checklist

- [ ] VM in an Indian region. Clinic owns the cloud account. MFA on every console user.
- [ ] Both disks encrypted at rest (section 2.2), confirmed in writing.
- [ ] Time zone `Asia/Kolkata` on the OS and in the service (section 3.3).
- [ ] Cloud firewall + `ufw`: 22 from the support firm only, 443 restricted (section 3.4),
      8000 closed.
- [ ] SSH keys only, no root login, automatic security updates on.
- [ ] HTTPS via Caddy; HSTS; `SESSION_COOKIE_SECURE=1`; `TRUSTED_PROXY_COUNT=1` verified in
      the Audit Log (section 5.2).
- [ ] `FLASK_DEBUG` off; service runs as the unprivileged `feast9` account.
- [ ] Setup completed immediately after installation (section 6).
- [ ] Two-step sign-in required, for everyone if 443 is open to the internet.
- [ ] Off-site backups to a versioned bucket in a second region, with a no-delete key; first
      backup shows "Sent".
- [ ] Backup key held by the clinic off the server; never in the backup bucket or account.
- [ ] Quarterly restore test from the bucket, recorded.
- [ ] One named Feast9 account per person; no shared logins; leavers deactivated the same day.
- [ ] Shared front-desk PCs: separate Windows user, screen lock, browser not saving passwords.
- [ ] No stray patient-data copies on the VM or engineers' machines (section 7).

Feast9 already provides: hashed passwords with strength rules, per-account lockout (5
failures → 15 minutes), idle and 12-hour session expiry, step-up re-authentication for
sensitive actions, CSRF protection, a strict Content-Security-Policy, `no-store` caching for
patient pages, server-side role enforcement, and an audit log of sign-ins, record views and
changes. See `THREAT_MODEL.md` for residual risks.

---

## 11. Upgrading to a new release

1. Agree a short downtime with the clinic (outside clinic hours).
2. **Back Up Now** (Backup & Data) and confirm it completed and shows "Sent".
3. Optional but recommended: take a provider snapshot of the data disk.
4. `sudo systemctl stop feast9`
5. `cd /opt/feast9/app && sudo -u feast9 git pull` (never touch `/var/lib/feast9`).
6. `sudo -u feast9 venv/bin/pip install -r requirements.txt`
7. `sudo systemctl start feast9`. Database changes are applied automatically at start-up and
   are additive only (columns/tables are added, never dropped or renamed).
8. Sign in and check the Dashboard, a patient, a case and the Backup & Data tiles.

Rollback: stop the service, `git checkout` the previous release, restore the pre-upgrade
backup with `restore_backup.py --force` (section 8.6), start.

Optionally run the test suite on a staging VM before upgrading production:
`pip install -r requirements-dev.txt`, then `pytest` (about 20–30 minutes).

---

## 12. Operations and support runbook

### Logs

- Application: `journalctl -u feast9`. Proxy: `journalctl -u caddy`.
- Business-level events (sign-ins, failed sign-ins, lockouts, record views, changes,
  exports, backups) are in **Settings → Audit Log**, visible to administrators.

### Health checks

- `curl -sI http://127.0.0.1:8000/login` on the VM returns 200 when the app is up. An
  external uptime monitor can check `https://<feast9-host>/login` if its addresses are
  allowed through the firewall.
- Backup freshness and off-site status: the Backup & Data tiles and history.
- Free space on `/var/lib/feast9`. Certificate renewal: Caddy logs.

### Common requests

| Request | Action |
|---|---|
| User forgot password | Administrator: **Users → Set Password**. Users with two-step sign-in can self-reset from the sign-in page. |
| The only administrator forgot their password | On the VM, in `/opt/feast9/app`: `sudo -u feast9 env DATA_DIR=/var/lib/feast9 TZ=Asia/Kolkata venv/bin/python reset_admin_password.py` (audited; ends that account's sessions). |
| Account locked | Wait 15 minutes, or administrator: **Users → Unlock**. |
| Lost phone (two-step sign-in) | Administrator: **Users → Reset 2FA**; the user sets it up again. |
| Staff member leaves | Administrator: **Users → Deactivate** (ends their sessions immediately). |
| "Everyone was logged out" | Expected after `SECRET_KEY` / `secret_key` changes. |
| Sign-ins blocked for everyone for a few minutes | `TRUSTED_PROXY_COUNT` is not set or is wrong (section 5.2). |
| Clinic can't reach Feast9, app is up | Clinic's public IP changed or its internet is down (sections 3.4, 9). |
| Dates or "today" off by a day early in the morning | Time zone is not `Asia/Kolkata` (section 3.3). |
| "Database is locked" errors | Make sure only one Feast9 service uses the `DATA_DIR`, and that it isn't on a network file system. |
| Backup tile red / off-site "Not sent" | Check the key file is present, disk space, and the rclone remote (`rclone lsd`); then **Back Up Now**. |
| VM lost | New VM (sections 3–5) → copy the latest backup from the bucket → place the clinic's backup key at `/etc/feast9/backup.key` → restore (8.6) → start → point DNS at the new IP if it changed. |

### Things that must not be done

- Editing `feast9.db` by hand or with a SQL tool on the live system.
- Copying the live `feast9.db` as a "backup". Use Feast9 backups.
- Running `seed_demo_data.py` or `dev_bootstrap.py` against live data.
- Enabling `FLASK_DEBUG=1`, binding Gunicorn to `0.0.0.0`, or opening port 8000.
- Running a second copy of Feast9 (another VM, more containers, a scale-out setting)
  against the same data.
- Deleting old backups, bucket versions or the backup key without the clinic's written
  approval.

---

## 13. Responsibilities (suggested split)

| Area | Support firm | Clinic administrator |
|---|---|---|
| Cloud account ownership, billing | named user with limited rights | ✔ owns it |
| VM, OS, disk encryption, firewall, DNS, proxy, certificates | ✔ | |
| Feast9 installation, upgrades, service health, logs | ✔ | |
| Off-site bucket, backup monitoring, quarterly restore test | ✔ | informed |
| Backup key safekeeping | holds a sealed copy if agreed | ✔ holds the key |
| Plan B Excel copy at the clinic | | ✔ |
| User accounts, roles, clinic settings | on request | ✔ |
| Privacy requests and patient data decisions | | ✔ (doctor/administrator) |
| Incident / suspected breach | technical investigation | decisions and notifications under the DPDP Act |

Support staff should not hold a Feast9 user account with access to patient data unless the
clinic grants one for a specific task, and it should be deactivated afterwards.

---

## Appendix A. Moving an existing Feast9 installation onto the cloud server

If the clinic has already been using this version of Feast9 on a local PC:

1. On the old PC: **Back Up Now**, then note the backup key (**Show backup key**).
2. Stop Feast9 on the old PC so no more work is entered there.
3. Copy the backup file (it's encrypted) to the new VM, place the key at
   `/etc/feast9/backup.key` (owner `feast9`, `chmod 600`), and restore it (section 8.6).
   Skip the Setup page; the accounts come with the backup.
4. Sign in on the cloud server and check patients, cases, attachments and the Audit Log.
5. **Set Up Backups is already done** (the key came across). The backup settings came across
   too: if the old PC had a **copy folder** set (e.g. `D:\...`), clear it, or it will replace
   the off-site upload and fail. Then
   check the off-site copy shows "Sent", and set the keep count (section 8.3).
6. Once the clinic confirms everything is there, remove the old PC's `DATA_DIR`, backups,
   Excel copies and any stray `*.db` copies. They are unencrypted patient data unless that
   PC has BitLocker turned on.

If the clinic is coming from the **earlier** Feast9 version instead, install fresh and use
**Import from Excel** (section 6, step 7).

## Appendix B. Windows Server VM

Linux is the supported cloud setup. If a Windows Server VM is required: Python 3.14 with
`requirements-win-py314.txt`, Waitress behind Caddy or IIS (URL Rewrite + ARR), run as a
service with NSSM under a dedicated non-admin account, set the time zone with
`tzutil /s "India Standard Time"`, and set the same environment variables as section 4.3
(via `nssm set Feast9 AppEnvironmentExtra ...`). For example:

```powershell
nssm install Feast9 C:\Feast9\venv\Scripts\waitress-serve.exe "--host=127.0.0.1 --port=8000 --threads=8 wsgi:app"
nssm set Feast9 AppDirectory C:\Feast9
nssm set Feast9 AppEnvironmentExtra DATA_DIR=D:\Feast9Data SESSION_COOKIE_SECURE=1 TRUSTED_PROXY_COUNT=1 FLASK_DEBUG=0 BACKUP_KEY_FILE=C:\Feast9Keys\backup.key
nssm set Feast9 ObjectName .\feast9svc <password>
nssm start Feast9
```

Everything else in this manual (firewall, backups, first-run setup, checklist) applies unchanged.
