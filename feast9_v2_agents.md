# Feast9 v2 — Agent Requirements & Rebuild Document
## Single Source of Truth · September 2026

> Hand this document to any AI agent or developer to rebuild Feast9 v2 from scratch. Every design decision, database field, route pattern, UX rule, known bug fix, and anti-pattern is captured here. Nothing is assumed from prior sessions.

---

## 1. What Feast9 Is

A dental clinic practice management system for a single practitioner and their reception staff. It covers the complete patient journey: registration → treatment cases → clinical files → billing → appointments → reports → DPDP compliance.

**Design principles (non-negotiable):**
- No build step — plain Python, runs with `python run.py` locally or `gunicorn wsgi:app` in production
- One SQLite file, one DATA_DIR — zero external dependencies for data
- DPDP Act 2023 compliance must never be diluted

**Correction (2026-09-17, PDF generation phase):** "Pillow is optional — app boots and works
without it" is no longer true and is removed from this list. `reportlab` (required for §10's
PDF generators, themselves non-optional) lists Pillow as a hard install dependency, so it
became a transitive requirement the moment PDF generation shipped — before any code in this
app touched `PIL` directly. Signature capture (§5.4/§10) and the generated login-screen
placeholder logo later added *direct* `PIL` imports on top of that, but the guarantee was
already gone by then. TOTP's QR codes (§14) deliberately used `qrcode.image.svg.SvgPathImage`
specifically to avoid a Pillow dependency at the time — a correct call in isolation, just one
later overtaken by PDF generation. If a future rebuild needs Pillow to stay optional, PDF
generation would have to be built without `reportlab`'s raster-image support, which isn't
recommended.

---

## 2. Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.11 or 3.12 | 3.14 works with requirements-win-py314.txt |
| Framework | Flask 3.x | No ORM, no build step |
| Database | SQLite 3 | Raw sqlite3 module — Row factory; WAL mode + busy timeout (2 gunicorn workers share one file) |
| WSGI Linux/Mac | Gunicorn 23.x | 2 workers |
| WSGI Windows | Waitress | Use requirements-win-py314.txt |
| PDF | ReportLab | Returns bytes — never writes to disk |
| Excel | openpyxl | Reports + Plan B backup + bulk patient import (§14) |
| Images | Pillow | Transitive via reportlab, not optional — see §1's correction |
| Frontend | Jinja2 + vanilla JS | No React, no Vue, no build step |
| Charts | Chart.js 4.x, vendored locally in `static/` | Analytics tab only — not loaded from CDN, keeps CSP `script-src` self-only |
| TOTP 2FA | `pyotp` + `qrcode` (SVG factory) | §14 — QR codes never touch Pillow even though it's present elsewhere |
| Backup encryption | `cryptography` (Fernet) | §14 — key independent of `SECRET_KEY` |
| Google sign-in | `Authlib` + `requests` | §14 — OIDC client; feature-flagged off when unconfigured |

### requirements.txt (Linux / Mac / Python 3.11 or 3.12) — as actually built
```
Flask==3.1.3
Werkzeug==3.1.7
gunicorn==23.0.0
pyotp==2.10.0
qrcode==8.2
cryptography==50.0.1
openpyxl==3.1.5
reportlab==4.4.4
Authlib==1.6.5
requests==2.32.5
```

### requirements-win-py314.txt (Windows + Python 3.14) — as actually built
```
Flask==3.1.3
Werkzeug==3.1.7
waitress>=3.0.0
pyotp==2.10.0
qrcode==8.2
cryptography==50.0.1
openpyxl==3.1.5
reportlab==4.4.4
Authlib==1.6.5
requests==2.32.5
```

Two files exist because: gunicorn does not run on Windows (use waitress). Always use
requirements.txt on Linux/Mac servers. **Pillow has no explicit pin in either file** — it
arrives transitively via `reportlab`'s own dependency (see §1's correction above); this is
intentional, not an oversight, since pinning it separately would just risk it drifting out of
sync with whatever version `reportlab` actually needs. `pyotp`/`qrcode`/`cryptography` (TOTP +
backup encryption, §14), `Authlib`/`requests` (Google sign-in, §14) were added as those phases
shipped — none were in the original stack table above, which now undercounts the real
dependency list; treat this block, not §2's table, as current.

### Local setup — Windows PowerShell
```powershell
cd C:\Projects\feast9_v2
python -m venv venv
venv\Scripts\activate
pip install -r requirements-win-py314.txt
$env:DATA_DIR = "C:\Projects\feast9_data"
$env:SECRET_KEY = "local-dev-key"
python run.py
```
Open http://127.0.0.1:5000 — first run shows Setup page.

### start.bat (one-click startup)
```bat
@echo off
call venv\Scripts\activate
set DATA_DIR=C:\Projects\feast9_data
set SECRET_KEY=local-dev-key
python run.py
```

---

## 3. Project Structure

```
feast9_v2/
├── app/
│   ├── __init__.py            # App factory, blueprint registration, error handlers
│   ├── db.py                  # All schema + CRUD — the only file that touches SQLite
│   ├── auth.py                # PBKDF2 hashing, login_required, rate limiting
│   ├── csrf.py                # Session-based CSRF token, validate_csrf()
│   ├── backup.py              # Auto daily, on-demand SQLite, Excel Plan B
│   ├── branding.py            # Logo upload/serve — Pillow in try/except
│   ├── config.py              # DATA_DIR, DB_PATH, SECRET_KEY from env
│   ├── constants.py           # SEX_OPTIONS, MEDICAL_CONDITIONS, ALLERGY_DRUGS, etc.
│   ├── validators.py          # normalize_date, is_valid_mobile, today_iso(), now_iso()
│   ├── excel_import.py        # Bulk 8,000-row xlsx import
│   ├── pdf_reports.py         # All PDF generators — return bytes
│   └── routes/
│       ├── auth_routes.py
│       ├── dashboard_routes.py
│       ├── patient_routes.py
│       ├── case_routes.py
│       ├── clinical_routes.py     # Attachments, lab reqs, referrals
│       ├── appointment_routes.py
│       ├── doctor_routes.py
│       ├── procedure_type_routes.py
│       ├── report_routes.py
│       ├── analytics_routes.py
│       ├── settings_routes.py     # Login screen customisation + login_image route
│       ├── import_routes.py
│       ├── branding_routes.py
│       └── data_rights_routes.py
├── app/templates/             # 28 Jinja2 templates
├── app/static/img/            # logo.png, saint_apollonia.png
├── README.md                  # Windows-first local setup guide
├── start.bat                  # One-click Windows startup
├── wsgi.py                    # gunicorn/waitress entry point
├── run.py                     # Flask dev server (local only)
├── seed_demo_data.py          # Creates demo patients, cases, appointments
└── reset_admin_password.py    # Emergency password reset CLI
```

---

## 4. Database Schema

### Core rule
Always use `CREATE TABLE IF NOT EXISTS`. Never DROP or RENAME columns. All migrations are additive. Run `_migrate_*` functions inside `init_db()` on every startup.

**Concurrency:** `init_db()` sets `PRAGMA journal_mode=WAL;` and a `PRAGMA busy_timeout=...;` on connect. Keep write transactions short. Run `PRAGMA integrity_check` periodically (e.g. alongside the daily backup job). This matters because gunicorn runs 2 workers against the same SQLite file.

### patients
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT NOT NULL,
date_of_birth TEXT NOT NULL DEFAULT '',    -- YYYY-MM-DD; computed_age derived in get_patient()
age INTEGER,                                -- kept for manual override / backward compat
sex TEXT,                                   -- 'Male' | 'Female' ONLY — no Other
mobile TEXT, email TEXT, address TEXT, last_visited_date TEXT,
created_at TEXT, updated_at TEXT, is_historic_import INTEGER DEFAULT 0,
medical_conditions_json TEXT DEFAULT '[]',
medical_conditions_other TEXT DEFAULT '',
is_pregnant INTEGER DEFAULT 0,
is_nursing INTEGER DEFAULT 0,
allergies_json TEXT DEFAULT '[]',
allergies_other TEXT DEFAULT '',
emergency_contact_name TEXT DEFAULT '',
emergency_contact_relation TEXT DEFAULT '',
emergency_contact_number TEXT DEFAULT '',
dpdp_notice_accepted INTEGER DEFAULT 0,
dpdp_notice_accepted_at TEXT DEFAULT '',
comms_consent INTEGER DEFAULT 0,
comms_consent_at TEXT DEFAULT '',
guardian_name TEXT DEFAULT '',
guardian_relation TEXT DEFAULT '',
guardian_mobile TEXT DEFAULT '',
is_anonymized INTEGER NOT NULL DEFAULT 0,   -- additive, DPDP Phase 2 (§5.11) — set by an Erasure request
anonymized_at TEXT NOT NULL DEFAULT ''
```

### cases
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
patient_id INTEGER NOT NULL REFERENCES patients(id),
title TEXT NOT NULL,
status TEXT NOT NULL DEFAULT 'Active',      -- 'Active' | 'Closed'
procedures_json TEXT DEFAULT '[]',
custom_procedure TEXT DEFAULT '',
doctor_id INTEGER REFERENCES doctors(id),
total_cost REAL DEFAULT 0,
next_action_note TEXT DEFAULT '',
follow_up_date TEXT DEFAULT '',             -- YYYY-MM-DD; Dashboard reminder ONLY — not a calendar booking
created_at TEXT, updated_at TEXT,
closed_at TEXT DEFAULT '',                  -- set ONLY when doctor explicitly marks Closed; uses now_iso()
consent_recorded INTEGER DEFAULT 0,         -- not in original §4 DDL — needed for the "red border if no consent" rule
consent_recorded_at TEXT DEFAULT '',
consent_notes TEXT DEFAULT '',
consent_signature_filename TEXT NOT NULL DEFAULT ''  -- additive — captured signature PNG, embedded in the consent PDF (§10)
```

### appointments
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
patient_id INTEGER NOT NULL REFERENCES patients(id),
case_id INTEGER REFERENCES cases(id),
doctor_id INTEGER REFERENCES doctors(id),
appt_date TEXT NOT NULL,
start_time TEXT NOT NULL,
end_time TEXT,
title TEXT DEFAULT '',
notes TEXT DEFAULT '',
status TEXT NOT NULL DEFAULT 'Scheduled',  -- Scheduled | Completed | Cancelled | No-show
created_at TEXT, updated_at TEXT,
arrived_at TEXT NOT NULL DEFAULT '',        -- kept in schema; not used in UI (wait time removed)
seen_at TEXT NOT NULL DEFAULT '',           -- kept in schema; not used in UI (wait time removed)
is_recurring INTEGER NOT NULL DEFAULT 0,   -- legacy columns from the original design; superseded — see note below
recur_interval TEXT NOT NULL DEFAULT '',
recur_until TEXT NOT NULL DEFAULT '',
series_id INTEGER REFERENCES appointments(id)  -- additive, self-referential — ties every occurrence (incl. the first) of a recurring series together; §14
```

**Note on is_recurring / recur_interval / recur_until:** the built recurring-appointments feature (§14) does
not use these three columns — it generates a bounded set of real appointment rows up front and ties them
together via `series_id` instead, rather than storing a recurrence rule on one row and computing occurrences
virtually. Kept in the schema, additive-only, harmless; do not build new logic on top of them.

**Note on arrived_at / seen_at:** These columns exist in the database from an earlier feature (wait time tracking) that was removed. Keep them — removing columns from SQLite is disruptive and the data is harmless. Do not build any UI on top of them.

### admin — not in original §4, built during Phase 1 (auth was always required but had no defined schema)
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
username TEXT NOT NULL UNIQUE,
password_hash TEXT NOT NULL,           -- PBKDF2
security_question TEXT NOT NULL,
security_answer_hash TEXT NOT NULL,
created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
role TEXT NOT NULL DEFAULT 'admin',    -- additive, Phase 4a (§14) — 'admin' | 'doctor' | 'receptionist'
is_active INTEGER NOT NULL DEFAULT 1,  -- additive, Phase 4a
totp_secret TEXT NOT NULL DEFAULT '',              -- additive, Phase 4c (§14 TOTP 2FA)
totp_enabled INTEGER NOT NULL DEFAULT 0,
totp_recovery_codes_json TEXT NOT NULL DEFAULT '[]',  -- hashed at rest, same as passwords
google_sub TEXT NOT NULL DEFAULT '',   -- additive — Google sign-in (§14), partial UNIQUE index WHERE google_sub != ''
google_email TEXT NOT NULL DEFAULT '',
google_linked_at TEXT NOT NULL DEFAULT ''
```
Holds every user account (admin/doctor/receptionist), not just the bootstrap admin — table name kept as-is (see CLAUDE.md) to avoid a pointless rename once roles were added.

### login_attempts — not in original §4
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
ip TEXT NOT NULL,
attempted_at TEXT NOT NULL
```
Backs DB-backed rate limiting on `/login` (no in-memory limiter, since gunicorn/waitress may run multiple workers/processes).

### case_visit_notes — not in original §4
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
patient_id INTEGER NOT NULL,
note TEXT NOT NULL,
visit_date TEXT NOT NULL,
created_at TEXT NOT NULL
```
Append-only — no edit/delete route. A correction is a new note, never an edit of an old one.

### prescriptions — not in original §4
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
patient_id INTEGER NOT NULL,
rx_details TEXT NOT NULL,
prescribed_date TEXT NOT NULL,
created_at TEXT NOT NULL
```
Append-only. `db.list_prescriptions_for_patient` (§14 "Prescription history") joins this to `cases` for a cross-case, most-recent-first view, shown as a 5th section on patient detail appended after the 4 order-fixed §5.2/§5.3 sections.

### payments — not in original §4
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
patient_id INTEGER NOT NULL,
payment_date TEXT NOT NULL,
amount REAL NOT NULL,
method TEXT NOT NULL DEFAULT '',
reference TEXT NOT NULL DEFAULT '',
notes TEXT NOT NULL DEFAULT '',
created_at TEXT NOT NULL
```
Append-only, financial — `role_required`/`financial_access_required` blocks the receptionist role on every read and write.

### cost_revisions — not in original §4
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
old_cost REAL NOT NULL,
new_cost REAL NOT NULL,
reason TEXT NOT NULL DEFAULT '',
changed_at TEXT NOT NULL,
created_at TEXT NOT NULL
```
`cases.total_cost` only ever changes via `db.update_case_cost()`, which inserts a row here automatically whenever the value actually changes — never `UPDATE cases SET total_cost` directly.

### audit_log — not in original §4, Phase 4b (§14)
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
actor_user_id INTEGER,
role TEXT NOT NULL DEFAULT '',
ts_utc TEXT NOT NULL,
action TEXT NOT NULL,
entity TEXT NOT NULL,
entity_id INTEGER,
correlation_id TEXT NOT NULL DEFAULT '',
before_summary TEXT NOT NULL DEFAULT '',   -- field-level/redacted by construction — clinical text/values never logged
after_summary TEXT NOT NULL DEFAULT '',
ip TEXT NOT NULL DEFAULT '',
user_agent TEXT NOT NULL DEFAULT '',
outcome TEXT NOT NULL DEFAULT 'success'
```
Written in the same transaction as the action it records (`db._write_audit`, no commit/close) for every instrumented write; `db.write_audit_now()` is the one standalone-commit exception (attachment downloads, which have no other write to piggyback on). Admin-only viewer at `/audit-log`.

### backup_log — not in original §4, automated off-server backup (§14)
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
started_at TEXT NOT NULL,
finished_at TEXT NOT NULL DEFAULT '',
status TEXT NOT NULL DEFAULT 'running',
file_path TEXT NOT NULL DEFAULT '',
file_size INTEGER NOT NULL DEFAULT 0,
offsite_status TEXT NOT NULL DEFAULT '',
error_message TEXT NOT NULL DEFAULT ''
```
Backs the admin-only `/backup` history/on-demand-run/download UI; dashboard shows a warning banner if the last backup failed, never ran, or is >26h stale.

### dental_chart_entries — not in original §4, dental charting (§14, "biggest clinical gap")
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
patient_id INTEGER NOT NULL REFERENCES patients(id),
case_id INTEGER REFERENCES cases(id),
tooth_id TEXT NOT NULL,           -- FDI/ISO 3950 notation, e.g. '11', '85'
dentition TEXT NOT NULL,          -- 'Permanent' | 'Primary' — both always chartable, no per-patient setting
surface TEXT NOT NULL DEFAULT 'Whole Tooth',
finding TEXT NOT NULL,            -- Sound/Caries/Restoration/Crown/Root Canal/Implant/Missing-Extracted/Fracture/Other
status TEXT NOT NULL DEFAULT 'Existing',  -- Existing | Planned | Completed
notes TEXT NOT NULL DEFAULT '',
recorded_by INTEGER,
recorded_at TEXT NOT NULL,
created_at TEXT NOT NULL
```
Append-only, like visit notes/prescriptions — a correction is a new entry, never an edit of an old one; the log itself is the correction/version history. `db.get_current_dental_chart` derives current per-tooth state as the latest entry per (tooth, surface), except a tooth whose overall-latest entry is Missing/Extracted, which shows only that.

### case_attachments
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
filename TEXT NOT NULL,                    -- UUID-based; in DATA_DIR/clinical_uploads/
original_name TEXT NOT NULL,               -- original filename shown to user
file_type TEXT NOT NULL DEFAULT 'Other',   -- X-ray | Clinical Photo | Lab Report | Other
description TEXT NOT NULL DEFAULT '',
uploaded_at TEXT NOT NULL,
created_at TEXT NOT NULL
```

### lab_requisitions
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
patient_id INTEGER NOT NULL,
lab_name TEXT NOT NULL DEFAULT '',
work_description TEXT NOT NULL,
sent_date TEXT NOT NULL,
expected_return TEXT NOT NULL DEFAULT '',
received_date TEXT NOT NULL DEFAULT '',
status TEXT NOT NULL DEFAULT 'Sent',       -- Sent | Received | Delayed
notes TEXT NOT NULL DEFAULT '',
created_at TEXT NOT NULL
```

### referral_notes
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
patient_id INTEGER NOT NULL,
referral_date TEXT NOT NULL,
referred_to TEXT NOT NULL,
speciality TEXT NOT NULL DEFAULT '',
reason TEXT NOT NULL,
notes TEXT NOT NULL DEFAULT '',
created_at TEXT NOT NULL
```

### settings (key-value)
```
clinic_name
clinic_address
clinic_phone
clinic_email
login_heading          -- blank falls back to clinic_name, then DEFAULT_LOGIN_HEADING = "Feast9"
                        -- (no devotional-caption default was ever implemented — see §5.12 correction)
login_tagline          -- subtitle under clinic name on login; blank = DEFAULT_LOGIN_TAGLINE
login_image_filename   -- filename in DATA_DIR/branding/; also reused as "Clinic Logo" (Settings) —
                        -- one key, two Settings entry points, no separate clinic-logo key
```

### data_requests
```sql
id, patient_id,
request_type TEXT,    -- Access | Correction | Erasure | Withdraw Consent
status TEXT,          -- Pending | In Progress | Completed | Rejected
description TEXT, resolution_note TEXT,
requested_at TEXT,
deadline_at TEXT,     -- 90 days from requested_at
resolved_at TEXT, created_at TEXT
```

### doctors
```sql
id, name TEXT, color TEXT, is_active INTEGER DEFAULT 1, created_at TEXT
```

### procedure_types
```sql
id, name TEXT, is_active INTEGER DEFAULT 1, created_at TEXT
```

### case_financial_assessments — not in original §4, Financial Assessment (ad-hoc, §5.15, 2026-09-18)
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
case_id INTEGER NOT NULL UNIQUE REFERENCES cases(id) ON DELETE CASCADE,
lab_amount REAL NOT NULL DEFAULT 0,
consultant_fee REAL NOT NULL DEFAULT 0,
consumables REAL NOT NULL DEFAULT 0,   -- additive, same day, follow-up request
misc_expense REAL NOT NULL DEFAULT 0,
created_at TEXT NOT NULL, updated_at TEXT NOT NULL
```
One row per case, upserted (`db.upsert_case_financial_expenses`) — a plain editable current-state row, not append-only like payments/visit notes, since these are estimates the doctor may revise. Each change is still audited (`case_financial_expenses_updated`, amounts logged).

### monthly_overhead_expenses — not in original §4, Monthly Evaluation (ad-hoc, §5.15, 2026-09-18)
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
month TEXT NOT NULL UNIQUE,     -- 'YYYY-MM'
rent REAL NOT NULL DEFAULT 0,
staff_salary REAL NOT NULL DEFAULT 0,
electricity REAL NOT NULL DEFAULT 0,
emi REAL NOT NULL DEFAULT 0,
cleaning_disposal REAL NOT NULL DEFAULT 0,
other_expense REAL NOT NULL DEFAULT 0,
created_at TEXT NOT NULL, updated_at TEXT NOT NULL
```
One row per calendar month, upserted (`db.upsert_monthly_overhead_expenses`, audited `monthly_overhead_expenses_updated`). Clinic overhead that isn't tied to any one case.

### capital_investments — not in original §4, Capital Investments ledger (ad-hoc, §5.15, 2026-09-18)
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
asset_name TEXT NOT NULL,
purchase_date TEXT NOT NULL,
cost REAL NOT NULL,
useful_life_months INTEGER NOT NULL,
notes TEXT NOT NULL DEFAULT '',
is_active INTEGER NOT NULL DEFAULT 1,
created_at TEXT NOT NULL, updated_at TEXT NOT NULL
```
Soft-deactivate-only (mirrors `doctors`/`procedure_types` — no edit/delete route) so correcting a mis-entered asset never silently rewrites depreciation already reported in past months; a correction is deactivate-the-wrong-one + add-the-right-one. `db.add_capital_investment` audits `capital_investment_added`; `db.set_capital_investment_active` audits `capital_investment_activated`/`_deactivated`.

---

## 5. Features

### 5.1 Authentication
- **Multi-user, role-based** (§14, built) — the `admin` table holds every account, not just the
  bootstrap admin. Three roles: `admin`, `doctor`, `receptionist`. `role_required(*roles)` and
  `financial_access_required` (blocks receptionist) enforce access server-side on every route,
  never UI-only. Admin-only `/users` list/create/deactivate/reactivate; the last active admin
  cannot be deactivated.
- PBKDF2 password hash (Werkzeug)
- Security question for self-service password reset — no email needed. Self-service
  Change Password / Security Question at `/account` (§5.13 correction — open to every role,
  not gated behind the admin-only `/settings`).
- `reset_admin_password.py` for emergency CLI recovery
- **TOTP 2FA** (§14, built) — `pyotp` + `qrcode` (SVG factory, no Pillow dependency). Self-service
  enrollment at `/totp/setup`; one-time recovery codes shown once, hashed at rest. Login becomes
  two-step when enabled (`/login/totp`, code or a recovery code).
- **Step-up re-authentication** (§14, built) — `reauth_required`: a session's `reauth_at` must be
  within 10 minutes or the user is sent to `/reauth` before continuing. Applied to user
  management, TOTP reset, clinical-document deletion, and backup actions.
- **Google sign-in** (§14, built, optional/secondary per spec) — Authlib OIDC. Only *links* to an
  already-authenticated local session (`/account/link-google`); a Google identity that was never
  linked cannot sign in or create an account. Feature-flagged off (routes 404, button hidden)
  when `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` aren't set. Local password (+TOTP) remains the
  required baseline regardless.
- CSRF token on every POST via `validate_csrf(request.form.get('csrf_token'))`
- Rate limiting: 8 failed login attempts per 15 minutes per IP (DB-backed, survives restarts)
- Security headers on every response: X-Frame-Options: DENY, X-Content-Type-Options, CSP, Referrer-Policy

### 5.2 Patients

**Date of Birth + computed age:**
- `date_of_birth` stored as YYYY-MM-DD
- Patient form: JS `computeAge()` runs on DOB input and fills the age field automatically
- `get_patient()` computes `computed_age` server-side — accounts for whether birthday has passed this year
- Patient detail shows both: `1985-06-20 (Age 41)`
- Age field remains manually editable for historic imports without DOB

**Patient list full-text search:**
```sql
SELECT DISTINCT p.* FROM patients p
LEFT JOIN cases c2 ON c2.patient_id = p.id
LEFT JOIN case_visit_notes vn ON vn.case_id = c2.id
LEFT JOIN prescriptions rx ON rx.case_id = c2.id
WHERE p.name LIKE ? OR p.mobile LIKE ? OR p.email LIKE ?
   OR p.address LIKE ? OR vn.note LIKE ? OR rx.rx_details LIKE ?
ORDER BY p.name LIMIT ? OFFSET ?
```

**Follow-up icons on patient list:**
- 🔴 = follow_up_date < today (overdue)
- 🟡 = today ≤ follow_up_date ≤ today + 3 days (upcoming)
- Computed by `get_patients_followup_status(patient_ids)` — returns `{patient_id: "overdue"|"upcoming"}`
- Icons disappear automatically when follow-up is cleared or case is closed

**Patient detail section order (never change):**
1. Medical Alerts
2. Active Treatment Cases
3. Appointments
4. Contact Details + DPDP Status

**Gender:** `SEX_OPTIONS = ["Male", "Female"]` — no Other, no Non-binary. This is for clinical records under the Clinical Establishments Act.

### 5.3 Treatment Cases

**Case detail section order (never change):**
1. Consent Forms (red border if no consent + Active case)
2. Visit Notes
3. Prescriptions (allergy alert auto-shows if any allergy recorded)
4. Clinical Attachments
5. Lab Requisitions
6. Referral Notes — collapsed by default (see below)
7. Payment Log
8. Follow-up & Next Action (editable inline)
9. Cost History & Revisions

**`closed_at` rule:** Set only when doctor explicitly marks status as Closed. Never auto-set. This is the basis for "doctor-marked closures" in Reports.

**Balance:** `total_cost − SUM(payments)` — computed live, never stored.

**Follow-up → Appointment conversion:**
- "📅 Book Appointment" link on case page passes `?clear_followup=case.id` in URL
- Appointment form has `<input type="hidden" name="clear_followup" value="{{ clear_followup }}">`
- After appointment saves successfully: `db.update_case_followup(int(clear_followup_id), "", "")` clears both follow_up_date and next_action_note
- Follow-up icon disappears from patient list; case removed from dashboard alerts

**Referral Notes — collapsed by default:**
Use HTML `<details>` element. Auto-opens if referrals already exist. localStorage remembers state per case (`referrals_open_<case_id>`).
```html
<details id="referrals-details" class="card">
  <summary>Referral Notes ▶ Show</summary>
  <!-- full content here -->
</details>
<script>
(function(){
  var det = document.getElementById('referrals-details');
  var key = 'referrals_open_{{ case.id }}';
  if (localStorage.getItem(key) === 'true' ||
      (localStorage.getItem(key) === null && {{ 'true' if referrals else 'false' }})) {
    det.open = true;
  }
  function updateIcon() {
    det.querySelector('.referral-toggle-icon').textContent = det.open ? '▼ Hide' : '▶ Show';
  }
  updateIcon();
  det.addEventListener('toggle', function() {
    localStorage.setItem(key, det.open);
    updateIcon();
  });
})();
</script>
```

### 5.4 Clinical Attachments
- Stored in `DATA_DIR/clinical_uploads/` — outside web root, never in static/
- Served via authenticated route only (`@login_required`)
- Magic bytes validation on upload:
  - JPG: `data[:2] == b'\xff\xd8'`
  - PNG: `data[:8] == b'\x89PNG\r\n\x1a\n'`
  - PDF: `data[:4] == b'%PDF'`
- Filenames are UUID-based to prevent collisions and path traversal
- `ATTACHMENT_TYPES = ["X-ray", "Clinical Photo", "Lab Report", "Other"]`
- **Retention / deletion (added 2026-09-16, not in original spec — practitioner-only, non-negotiable)**:
  retention needs vary per case — some cases must keep lab reports/X-rays/photos after closing,
  others don't — so purging is a deliberate, per-case choice for the practitioner, never automatic
  and never available to the receptionist role. `clinical.delete_attachment` (single file) is
  `role_required("admin", "doctor")` + `reauth_required`, reason optional, audited
  (`attachment_deleted` — file type + reason, never file content). `clinical.clear_attachments`
  (bulk, `db.clear_case_clinical_documents`) is the same role/reauth gating plus a **required**
  reason, one `clinical_documents_cleared` audit row summarizing count + file types. Both actions
  are hidden from the receptionist role in the template, not just blocked server-side.

### 5.5 Lab Requisitions
- `LAB_REQ_STATUSES = ["Sent", "Received", "Delayed"]`
- Status badge colours: Sent = green, Received = primary-dark, Delayed = red

### 5.6 Referral Notes
- Collapsed by default via `<details>` element (see 5.3)
- Referral letter PDF via `generate_referral_pdf()` in pdf_reports.py
- Print route: `GET /cases/<case_id>/referral/<ref_id>/print`

### 5.7 Appointments

**Statuses:** Scheduled | Completed | Cancelled | No-show

**Appointment form — all render_template calls must pass:**
```python
return render_template(
    "appointment_form.html",
    appt=appt,
    doctors=doctors,
    statuses=db.APPOINTMENT_STATUSES,
    prefill_date=appt["appt_date"],
    prefill_patient=prefill_patient,
    errors=[],
    clear_followup="",     # or the case_id string if coming from follow-up
)
```

**form_state dict (error re-render) must include:**
```python
form_state = {
    "id": appt_id,
    "patient_id": patient_id,
    "doctor_id": int(doctor_id) if doctor_id else None,
    "appt_date": appt_date_raw,
    "start_time": start_time,
    "end_time": end_time,
    "title": title,
    "notes": notes,
    "status": status,
    "arrived_at": "",     # column exists in DB; include in dict to avoid template errors
    "seen_at": "",        # column exists in DB; include in dict to avoid template errors
    "patient_name": patient["name"] if patient else "",
    "doctor_name": "",
}
```

**No-show → automatic follow-up next day:**

This logic lives in `_handle_noshow_followup()` called from `_save_appointment()`. It is NOT in any separate status route.

```python
def _handle_noshow_followup(patient_id, appt_date):
    """Set follow-up reminder for next day on patient's most recent active case."""
    from datetime import date, timedelta
    next_day = (date.today() + timedelta(days=1)).isoformat()
    try:
        cases = db.list_cases_for_patient(patient_id)
        active = sorted(
            [c for c in cases if c.get("status") == "Active"],
            key=lambda c: c.get("updated_at", ""), reverse=True
        )
        if active:
            db.update_case_followup(
                active[0]["id"], next_day,
                f"Patient did not attend appointment on {appt_date} — please reschedule"
            )
            flash(f"Follow-up reminder set for {next_day}.", "warning")
    except Exception:
        pass   # follow-up is best-effort; don't block the save
```

Called from `_save_appointment` when status changes TO No-show:
```python
# In _save_appointment, after db.update_appointment:
if status == "No-show" and prev_status != "No-show":
    _handle_noshow_followup(patient["id"], appt_date)
```

**Appointment delete:** `POST /<appt_id>/delete` — redirects to calendar for the deleted appointment's month/year.

**Reminder text:** Shown on appointment edit page for copy-paste to WhatsApp/SMS. Simple click-to-copy with no JS dependency:
```html
<div onclick="this.nextElementSibling.style.display='block';
              navigator.clipboard&&navigator.clipboard.writeText(this.textContent.trim());
              setTimeout(()=>this.nextElementSibling.style.display='none',2000)">
  Dear [patient], your appointment at [time] on [date] with [doctor] is confirmed...
</div>
<span style="display:none;">✓ Copied</span>
```

### 5.8 Dashboard

**4 stat tiles:** Follow-ups Needing Attention (combined), Total Outstanding Balance, Active Cases, Today's Appointments count.

**Merged follow-up table:**
- 🔴 Red rows = overdue (follow_up_date < today) — shown first
- 🟡 Amber rows = upcoming (within 3 days)
- "No follow-ups requiring attention 🎉" when empty

`get_followup_alerts()` returns `(overdue_list, upcoming_list)`.

**Today's Appointments widget** — Status column shows badges based on `appointment.status` only:
```
Completed → ✓ Completed badge (green), green row background (#F1F8F1)
Cancelled → Cancelled badge (grey)
No-show   → No-show badge (red)
Scheduled → Scheduled badge (blue) — default
```
Do NOT base this on `arrived_at` or `seen_at` columns (wait time feature was removed).

### 5.9 Reports

**Critical: DATE() wrapper for timestamp fields.**
`created_at` and `closed_at` are stored as `YYYY-MM-DD HH:MM:SS`. Without `DATE()`, records on the end date are excluded because `"2026-09-13 14:30:00" > "2026-09-13"`.

```sql
-- Correct for timestamp fields:
WHERE DATE(created_at) BETWEEN ? AND ?
WHERE DATE(closed_at)  BETWEEN ? AND ?
-- Fine without DATE() — payment_date is date-only:
WHERE payment_date BETWEEN ? AND ?
```

**Filter form must have explicit action:**
```html
<form method="get" action="{{ url_for('reports.view_reports') }}">
```

**Sections (all always rendered — never hide on empty data):**
1. Period stat tiles (Revenue Collected, Cases Closed, New Cases, New Patients)
2. Revenue Overview — all time
3. Pending Payments by Patient & Case
4. Doctor-wise Revenue by Period — with collection rate progress bars
5. Patient Retention — **always renders**; green "All clear" state when 0 lapsed
6. Payments Received in Period
7. Cases Closed in Period

Two downloads: 🖨 Print Report (PDF) · 📊 Download Pending (Excel).

### 5.10 Analytics
Separate tab from Reports. 8 Chart.js charts, year selector, 6 KPI tiles. Monthly revenue chart belongs HERE, not in Reports.

### 5.11 DPDP Act 2023 — NEVER DILUTE

**Phase 1 (at registration):**
- Data Processing Notice: scrollable text, mandatory checkbox — form blocked without it
- Communications consent: separate opt-in, default OFF, timestamped
- Guardian section: auto-shows for age < 18, guardian mobile mandatory for minors

**Phase 2 (data rights):**
- Four types: Access | Correction | Erasure | Withdraw Consent
- 90-day deadline auto-set on each request
- Erasure = soft-anonymise PII, preserve clinical/financial records
- Erasure requires typing patient's exact name to confirm
- `count_pending_data_requests()` injected into every page via context processor

### 5.12 Login Screen Customisation

Three configurable settings (stored in `settings` table):

| Key | Default fallback | Description |
|---|---|---|
| `login_heading` | `clinic_name`, then `DEFAULT_LOGIN_HEADING = "Feast9"` | H1 on the login page — no devotional-caption default was ever built (see correction below) |
| `login_tagline` | `DEFAULT_LOGIN_TAGLINE` | Subtitle under clinic name |
| `login_image_filename` | (uses `static/img/saint_apollonia.png`) | Custom image filename in DATA_DIR/branding/; also reused as "Clinic Logo" (§5.13) |

**Correction (2026-09-17, login redesign + Clinic Details phase):** this section's original example table and
code below describe the *first-draft* shape of the feature; the actually-built version differs in three ways,
kept here rather than silently rewritten so the history is legible:
1. `login_heading`'s fallback chain is `clinic_name` → `DEFAULT_LOGIN_HEADING` (`"Feast9"`), not a hardcoded
   devotional caption — setting just the Clinic Name (§5.13) is enough to have it appear on login without
   also filling in `login_heading`; an explicit `login_heading` still wins if both are set.
2. `static/img/saint_apollonia.png` is a **generated placeholder** (a plain "F9" monogram in the app's brand
   blue, made with Pillow), not an actual devotional image — swap it or upload a real clinic logo via
   Settings whenever one is available.
3. The Bible verse was changed from the placeholder Jeremiah 30:17 text to **Exodus 15:26** at the user's
   explicit request (2026-09-17) — see the updated block below. It remains hardcoded, non-configurable, and
   never exposed in the Settings UI, exactly as originally specified.

The login page also gained a visual pass not in the original spec: `body.auth-page` (shared by login/setup/
2FA-verify/forgot-password, via a `body_class` Jinja block in `base.html`) — soft gradient background, card
shadow, rounded logo badge — and a `© {{ current_year }} Feast9` footer. Scope was deliberately kept to the
auth flow, not an app-wide redesign.

**Five critical implementation rules:**

1. **`from app.config import DATA_DIR` must be at the top of settings_routes.py** — missing this causes a 500 error on any image upload
2. **The login_heading and login_tagline inputs must be INSIDE the `<form>` tag** — if they are in a wrapper `<div>` above the form, they are never submitted
3. **The `login_image` route must be public** (no `@login_required`) — the login page loads it before the user authenticates
4. **Use `pathlib.Path` for file paths** — Windows requires forward-slash-safe path handling
5. **Falls back gracefully** — if `login_image_filename` is blank or the file is missing, serve `static/img/saint_apollonia.png`

**Correct settings form structure:**
```html
<form method="post" enctype="multipart/form-data">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <input type="hidden" name="form" value="login_screen">
  <!-- THESE INPUTS MUST BE INSIDE THE FORM -->
  <input type="text" name="login_heading" value="{{ login_heading or '' }}">
  <input type="text" name="login_tagline" value="{{ login_tagline or '' }}">
  <input type="file" name="login_image" accept="image/png,image/jpeg,image/gif,image/webp">
  <button type="submit">Save Login Screen</button>
</form>
```

**login_image route (public):**
```python
@bp.route("/login-image")
def login_image():
    import pathlib
    from flask import current_app
    default = pathlib.Path(current_app.root_path) / "static" / "img" / "saint_apollonia.png"
    filename = db.get_setting("login_image_filename", "")
    if filename:
        custom = pathlib.Path(DATA_DIR) / "branding" / filename
        if custom.exists():
            ext = custom.suffix.lower().lstrip(".")
            mt = {"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png",
                  "gif":"image/gif","webp":"image/webp"}.get(ext, "image/jpeg")
            return send_file(str(custom), mimetype=mt)
    return send_file(str(default), mimetype="image/png")
```

**Bible verse — hardcoded in login.html, never configurable, never in Settings UI:**
```html
<div class="verse-block">
  "...for I am the LORD, who heals you."
  <span class="verse-ref">— Exodus 15:26</span>
</div>
```

### 5.13 Settings Navigation

**Top nav:** Dashboard | Patients | Appointments | Reports | Analytics | Financial Assessment | Data Rights | Settings

**Financial Assessment** (§5.15, added 2026-09-18, not in original spec) sits in the nav
immediately after Analytics, gated by the same `can_view_financial_nav` flag as Reports/
Analytics — hidden from the receptionist role, not just blocked server-side (though it is also
blocked server-side, via `financial_access_required` on every route).

**Settings page — admin cards (NOT in top nav):**
- 👨‍⚕️ Doctors → `/doctors/`
- 🦷 Case Types → `/procedure-types/`
- 📥 Import Data → `/import/`

**Settings page sections:**
Clinic Details | Clinic Logo | Login Screen | Security Question | Change Password | Backups

Backup is in Settings only — not in top nav.

### 5.14 Custom Error Pages
```python
# In create_app(), registered via _register_error_handlers(app):
@app.errorhandler(404)   # Page Not Found
@app.errorhandler(500)   # Something went wrong
@app.errorhandler(403)   # Access Denied
```
All use `error.html` template with error_code, error_title, error_message and navigation links.

### 5.15 Financial Assessment / Monthly Evaluation / Capital Investments (ad-hoc addition, 2026-09-18 — not in original scope)

A doctor-facing per-case and per-month profitability module, added the same day at the user's
request, on top of the existing Reports/Analytics financial pages rather than folded into them.
Gated exactly like Reports/Analytics: `financial_access_required` on every route
(`app/routes/financial_routes.py`, `url_prefix="/financial-assessment"`) — receptionist gets
`403` on every route, and the nav link (top nav, right after Analytics) is hidden for that role
via the same `can_view_financial_nav` flag.

**Per-case table (`/financial-assessment`):**
- Lists every case (any status), most recent first, with live-computed Billed (`total_cost`)/
  Collected (`SUM(payments)`)/Pending, next to the doctor-entered expenses (Lab Amount,
  Consultant Fee, Consumables, Misc Expense — one editable row per case,
  `db.upsert_case_financial_expenses`, one form for the whole table with a single "Save
  Expenses" button, since a `<form>` can't be nested per-row inside a `<table>`).
- **Profit = Billed − (Lab Amount + Consultant Fee + Consumables + Misc Expense)** — the user's
  explicit choice over a collected-based formula, so a paper profit on an uncollected balance
  isn't mistaken for cash in hand. A negative profit (loss) is flagged amber (`.profit-loss`,
  reusing the `.flash-warning` amber palette) both on-screen and in the export.
- Optional `from`/`to` filter on the case's `created_at` (`DATE()`-wrapped, same convention as
  Reports); no filter shows all cases.
- `/financial-assessment/export.xlsx` (openpyxl) mirrors the on-screen columns exactly,
  including Profit; audited `financial_assessment_exported`.
- **Deliberately kept off the Reports page** — Reports only gets a compact "Profitability — All
  Time" card (`db.get_financial_assessment_summary()`, one cheap aggregate query: all-time net
  profit + a loss-case count) with a link to the full table; the editable per-case list never
  renders inside Reports, so the period-filtered report view doesn't get a second, differently
  -scoped (all-time, not period) editable table.

**Monthly Evaluation (`/financial-assessment/monthly`):**
- Extends the same methodology to a whole calendar month. "Billed this month" = every case
  *opened* that month (`strftime('%Y-%m', c.created_at) = ?`) — the same "billed = cases opened
  in the period" convention `get_doctor_revenue_by_period` already uses, so the per-case and
  monthly views never disagree about what counts as a given month's business
  (`db.get_monthly_case_rollup`).
- Clinic overhead not tied to any one case (Rent, Staff Salary, Electricity, EMI,
  Cleaning & Disposal, Other) is entered per month (`db.upsert_monthly_overhead_expenses`, one
  row per `'YYYY-MM'`, `HTML5 <input type="month">`).
- A **Short Term / Long Term** toggle (`?view=short|long`, default short):
  - **Short Term: Net Profit = Billed − Case Expenses − Overhead**
  - **Long Term: Net Profit = Billed − Case Expenses − Overhead − Depreciation** (see Capital
    Investments below), with a per-asset depreciation breakdown shown on the page.
- Same amber-on-loss treatment as the per-case table.

**Capital Investments ledger (`/financial-assessment/capital-investments`):**
- A small asset ledger — asset name, purchase date, cost, useful-life months, notes.
- No edit/delete route, mirroring the `doctors`/`procedure_types` pattern — only soft
  deactivate/reactivate (`db.set_capital_investment_active`), specifically so correcting a
  mis-entered asset never silently rewrites depreciation already reported in past months; a
  correction is deactivate-the-wrong-one + add-the-right-one.
- `db.get_monthly_depreciation(month)` computes **straight-line depreciation** (cost ÷
  useful_life_months) per active asset, contributing only for the months from purchase
  (inclusive) through the end of its useful life (exclusive) — zero before purchase, zero once
  fully depreciated.
- This is a direct, deliberately partial implementation of a capital-investment-ROI question
  raised the same day — true cumulative ROI/payback tracking (cumulative profit vs. cumulative
  capital invested, a "months to payback" projection) was flagged as a separate, larger feature
  and was **not** built; only the depreciation-based Long Term view was. See §15.

---

## 6. Key DB Functions

```python
# ── Patient / DOB ─────────────────────────────────────────────────────
# In get_patient(), compute computed_age from date_of_birth:
from datetime import date
born  = date.fromisoformat(patient["date_of_birth"])
today = date.today()
computed_age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))

# ── Follow-up alerts (Dashboard) ──────────────────────────────────────
get_followup_alerts() -> (overdue_list, upcoming_list)
# overdue:  follow_up_date < today
# upcoming: today <= follow_up_date <= today + 3 days

# ── Follow-up icons (Patient list) ────────────────────────────────────
get_patients_followup_status(patient_ids) -> {patient_id: "overdue"|"upcoming"}

# ── Inline follow-up update ───────────────────────────────────────────
update_case_followup(case_id, follow_up_date, next_action_note)
# Call with ("", "") to clear a follow-up

# ── Reports — always use DATE() for timestamp fields ──────────────────
get_new_cases_count(start, end)       -> WHERE DATE(created_at) BETWEEN ? AND ?
get_new_patients_count(start, end)    -> WHERE DATE(created_at) BETWEEN ? AND ?
get_cases_closed_count(start, end)    -> WHERE DATE(closed_at)  BETWEEN ? AND ?
get_cases_closed_in_range(start, end) -> WHERE DATE(c.closed_at) BETWEEN ? AND ?
get_doctor_revenue_by_period(s, e)    -> WHERE DATE(c.created_at) BETWEEN ? AND ?
get_payments_in_range(start, end)     -> WHERE payment_date BETWEEN ? AND ? (date-only, fine)
get_patient_retention(months=6)       -> {lapsed, total_patients, threshold_months, cutoff_date}

# ── Clinical attachments ──────────────────────────────────────────────
add_attachment(case_id, filename, original_name, file_type, description)
list_attachments_for_case(case_id)
delete_attachment(att_id)           # returns filename for disk deletion

# ── Lab requisitions ──────────────────────────────────────────────────
add_lab_req(case_id, patient_id, lab_name, work_description, sent_date, expected_return, notes)
list_lab_reqs_for_case(case_id)
update_lab_req(req_id, status, received_date, notes)
delete_lab_req(req_id)

# ── Referral notes ────────────────────────────────────────────────────
add_referral(case_id, patient_id, referral_date, referred_to, speciality, reason, notes)
list_referrals_for_case(case_id)
delete_referral(ref_id)
```

---

## 7. Route Architecture

### Blueprint registration (app/__init__.py)
Every blueprint must be registered. Example:
```python
from app.routes.clinical_routes import bp as clinical_bp
app.register_blueprint(clinical_bp)
```

### CSRF on every POST
```python
from app.csrf import validate_csrf
validate_csrf(request.form.get('csrf_token'))
```

### No-show flow (the correct implementation)
```python
# appointment_routes.py

def _handle_noshow_followup(patient_id, appt_date):
    from datetime import date, timedelta
    next_day = (date.today() + timedelta(days=1)).isoformat()
    try:
        cases = db.list_cases_for_patient(patient_id)
        active = sorted([c for c in cases if c.get("status") == "Active"],
                        key=lambda c: c.get("updated_at", ""), reverse=True)
        if active:
            db.update_case_followup(active[0]["id"], next_day,
                f"Patient did not attend appointment on {appt_date} — please reschedule")
            flash(f"Follow-up reminder set for {next_day}.", "warning")
    except Exception:
        pass   # best-effort; don't block save

# Called inside _save_appointment after db.update_appointment:
prev = db.get_appointment(appt_id)
prev_status = prev["status"] if prev else ""
db.update_appointment(...)
if status == "No-show" and prev_status != "No-show":
    _handle_noshow_followup(patient["id"], appt_date)
```

### clear_followup flow (Follow-up → Appointment)
```python
# new_appointment route GET:
clear_followup = request.args.get("clear_followup", "")
# Pass to template as hidden field.

# In _save_appointment after add_appointment:
clear_followup_id = request.form.get("clear_followup", "").strip()
if clear_followup_id:
    db.update_case_followup(int(clear_followup_id), "", "")
```

---

## 8. UX Rules (Non-Negotiable)

**Case detail section order:** Consent → Visit Notes → Prescriptions → Clinical Attachments → Lab Requisitions → Referral Notes (collapsed) → Payment Log → Follow-up & Next Action → Cost History

**Patient detail section order:** Medical Alerts → Active Cases → Appointments → Contact / DPDP

**Follow-up ≠ Appointment:** Always distinguish in UI. Follow-up = Dashboard reminder on a case. Appointment = confirmed calendar booking. Booking clears the follow-up via `clear_followup` param.

**Gender:** Male / Female only. No Other.

**closed_at:** Only set when doctor explicitly closes. Never auto-close.

**Referral Notes:** Always collapsed by default. Uses `<details>` HTML element. localStorage state per case. Auto-opens if referrals already exist for that case.

**Reports date filter:** Always `DATE()` wrapper on `created_at`/`closed_at`. Form has explicit `action` attribute.

**Patient Retention:** Always render the section. Show "All clear" empty state when 0 lapsed. Never hide on empty.

**Dashboard appointments:** Status column badges based on `appointment.status` only — Completed (green), Cancelled, No-show, Scheduled. Do not use `arrived_at`/`seen_at` for dashboard display.

**No-show:** The follow-up logic is in `_save_appointment` → `_handle_noshow_followup()`. There is no separate status-change endpoint. The trigger is the main appointment form save.

---

## 9. Security

```python
# Every POST:
validate_csrf(request.form.get('csrf_token'))

# Clinical file uploads — magic bytes:
data = f.read(16); f.seek(0)
assert data[:2] == b'\xff\xd8'        # JPG
assert data[:8] == b'\x89PNG\r\n\x1a\n'  # PNG
assert data[:4] == b'%PDF'            # PDF

# login_image route must NOT have @login_required
# Use pathlib for cross-platform paths:
import pathlib
path = pathlib.Path(DATA_DIR) / "branding" / filename
return send_file(str(path), mimetype=mt)
```

**Correction (as built):** `from app.config import DATA_DIR` as a flat module-level constant is the pattern to
**avoid**, not follow — `DATA_DIR`-relative storage dirs (`app_config.branding_dir()`, `backups_dir()`,
`uploads_dir()`) are read fresh, as **functions**, inside each view instead, specifically so
`monkeypatch.setattr(app_config, "DATA_DIR", ...)` in tests doesn't go stale against a constant captured at
import time. The same function-not-constant pattern was reused for `google_signin_enabled()`.

**Environment variables:**

| Variable | Required | Notes |
|---|---|---|
| SECRET_KEY | Yes | 32+ byte random hex. App warns on startup if using default. |
| DATA_DIR | Yes | Persistent directory for DB, uploads, branding, backups |
| SESSION_COOKIE_SECURE | Production only | Set to `1` when HTTPS is active |
| FLASK_DEBUG | Must be `0` | Never `1` in production |
| BACKUP_ENCRYPTION_KEY | Required to run backups (§14) | Fernet key, deliberately independent of SECRET_KEY — `create_backup()` refuses to run at all if unset rather than ever writing an unencrypted backup |
| BACKUP_OFFSITE_COMMAND | Optional (§14) | Pluggable shell command, `{file}` placeholder — provider choice (S3/B2/second server) stays a deferred operational decision per §15 |
| GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET | Optional (§14) | Unset means Google sign-in is feature-flagged off — routes 404, no button renders, zero added attack surface |

---

## 10. PDF Generators

All in `pdf_reports.py`. All return `bytes`. Never write to disk. Pattern: `buf = io.BytesIO(); doc.build(story); return buf.getvalue()`.

| Function | Purpose |
|---|---|
| `generate_prescription_pdf` | With allergy alert banner if allergies recorded |
| `generate_case_summary_pdf` | Cost, payments, consent status |
| `generate_patient_summary_pdf` | All cases and history |
| `generate_report_pdf` | Period stats + revenue + pending payments |
| `generate_consent_pdf` | With embedded signature or "Paper consent on file" |
| `generate_data_access_pdf` | DPDP Phase 2 right-to-access export |
| `generate_referral_pdf` | Referral letter to specialist |

---

## 11. Deployment

### Docker + Caddy (recommended for production)
```bash
unzip feast9_v2.zip && cd feast9_v2
cp .env.example .env   # fill SECRET_KEY and DATA_DIR
docker compose --env-file .env up -d --build
```

### Persistent data directory
```
DATA_DIR/
├── feast9.db             ← entire database
├── uploads/              ← consent signatures and uploaded PDFs
├── clinical_uploads/     ← X-rays, clinical photos, lab reports (create on first boot)
├── backups/              ← auto daily + manual snapshots
└── branding/             ← custom logo + custom login image
```

`clinical_uploads/` is created automatically on first file upload. Safe to pre-create: `os.makedirs(os.path.join(DATA_DIR, "clinical_uploads"), exist_ok=True)`.

**Backup validity:** A backup is only trusted once it has been restored successfully into a separate, clean environment. Automated nightly backup + on-demand admin backup are built (§14, Automated off-server backup — `app/backup.py`, `BACKUP.md`), but restore-testing itself is still a manual, periodic checklist item — `restore_backup.py` is CLI-only, never a web route, and there is no automated restore-test job.

### Upgrade from v1 → v2
1. Run `patch_v2_migrate.py` first (creates `.bak` backup, adds columns/tables)
2. Deploy new app files
3. Restart

### Infrastructure changes v1 → v2
- Persistent volume: increase to 50 GB minimum (clinical file storage)
- Nginx: set `client_max_body_size 25m` (default 1 MB blocks file uploads)
- Caddy: no change needed (no default upload limit)

---

## 12. Testing Patterns

```python
from app import create_app, db
import re, json

app = create_app(); app.testing = True
c = app.test_client()

def tok(path):
    r = c.get(path)
    m = re.search(r'name="csrf_token" value="([a-f0-9]+)"', r.data.decode())
    return m.group(1) if m else ''

# Setup + seed
c.post('/setup', data={'username':'admin','password':'test123','confirm':'test123',
    'security_question':'City?','security_question_custom':'','security_answer':'Test',
    'csrf_token':tok('/setup')})
c.post('/login', data={'username':'admin','password':'test123','csrf_token':tok('/login')})
import seed_demo_data; seed_demo_data.run()
```

### What to always test (27-point checklist)

1. All pages return 200 after login
2. DPDP notice enforcement — 400 without tick
3. Case detail section order — find HTML IDs by DOM position
4. Appointment delete removes record, redirects to correct month/year
5. No-show via form save (not a status route) sets follow-up to next day
6. Follow-up appears in dashboard as upcoming (within 3 days)
7. Follow-up icon appears on patient list
8. clear_followup param clears follow-up after booking appointment
9. Lab req add/update/delete on case detail
10. Referral note add/delete, referral PDF returns `%PDF`
11. Referral Notes section uses `<details>` element, closed by default
12. localStorage state remembered for referral panel per case
13. Report filters produce different data for different date ranges
14. DATE() fix: records created on the end date ARE included
15. Report form has explicit `action` attribute
16. Patient retention always renders (green "All clear" on 0 lapsed)
17. Custom 404 page shows "Page Not Found" on unknown URL
18. Login screen: heading and tagline save and appear on login page
19. Login screen heading and tagline inputs are INSIDE the form tag
20. Image upload saves to DATA_DIR/branding/ and filename saved to DB
21. Bible verse (Exodus 15:26) always present on login page
22. DOB field auto-computes age in patient form
23. Patient list full-text search returns match from visit notes
24. Clinical attachment upload validates magic bytes
25. Attachment served only to authenticated users
26. All PDFs return `%PDF` in first 4 bytes
27. Feast9 branding — no "Master Dentizt" anywhere

---

## 13. Seed Data

`seed_demo_data.py` creates on every call (idempotent check by patient name):
- 2 doctors: Dr. Anjali Rao (green), Dr. Vivek Menon (blue)
- 3 patients with medical history, allergies, DPDP notice, emergency contacts
- 5 cases: Active + Closed, with payments, prescription, visit notes, cost revision, signed consent
- 3 appointments: upcoming, colour-coded by doctor

Seed must call `db.add_patient(...)` with `date_of_birth` parameter.

---

## 14. Remaining Build Scope (Security, Governance & Advanced Clinical)

**Status as of 2026-09-18:** every row below has been built except two, which the user explicitly decided
(2026-09-17) to put **out of scope for now** rather than sequence into this build: **Patient portal** and
**DPDP Phase 3**. Everything else in this table is done — see `CLAUDE.md`'s build log for the concrete
implementation of each (files, routes, tests). This is a real change from earlier drafts of this document,
which framed the whole table as "unsequenced, not out of scope" — that framing no longer applies to those
two rows specifically; it still applies to nothing else remaining, since nothing else remains. Financial
Assessment / Monthly Evaluation / Capital Investments (§5.15) is an ad-hoc addition made after this table
was originally drafted — it was never part of `feast9_v2_agents.md`'s original scope at all, so its row
below is not a "built vs. deferred" status the same way the others are; it is simply documented for
completeness.

| Feature | Status |
|---|---|
| Multi-user roles | ✅ Built (Phase 4a). Three roles: Admin, Doctor, Receptionist. `admin.role`/`is_active` columns, `role_required`/`financial_access_required` enforced server-side on every route — receptionist gets `403`, financial data is redacted out of the render context entirely, never CSS-hidden. See `tests/test_roles.py`. |
| Audit log | ✅ Built (Phase 4b). `audit_log` table exactly as specified. `db._write_audit` commits in the same transaction as the action it records; `db.write_audit_now()` is the one standalone-commit exception (attachment downloads). Admin-only viewer at `/audit-log`. See `tests/test_audit_log.py`. |
| TOTP 2FA | ✅ Built (Phase 4c). `pyotp` + `qrcode` (SVG factory), self-service enrollment, one-time recovery codes, admin-controlled reset. `reauth_required` (10-minute step-up window) gates user management, TOTP reset, clinical-document deletion, and backup actions. See `tests/test_totp.py`. |
| Google sign-in (optional, secondary) | ✅ Built. Authlib OIDC, `openid email profile` scope only. Can only *link* an already-authenticated local session — never creates a new account, never signs in an unlinked identity. Feature-flagged off (routes 404, no button) when unconfigured. Local password (+TOTP) remains the required baseline. See `tests/test_google_signin.py`. |
| Recurring appointments | ✅ Built. A bounded set of real appointment rows (capped at `MAX_RECURRING_OCCURRENCES` = 52), tied together by `appointments.series_id`. Edit-one-vs-edit-series (§14's own literal framing), same-doctor/overlap conflicts flagged (not blocked), per-occurrence no-show handling reuses the existing single-appointment machinery. See `tests/test_appointments.py`. |
| Dental charting | ✅ Built. `dental_chart_entries`, append-only, structured data as the source of truth (tooth/dentition/surface/finding/status/case/notes/recorded-by/recorded-at), FDI/ISO 3950 notation, both permanent and primary dentition always chartable. SVG chart is a presentation layer over `db.get_current_dental_chart`, not a separate data source. See `tests/test_dental_chart.py`. |
| **Patient portal** | ❌ **Out of scope (2026-09-17 product decision, deferred indefinitely, not just unsequenced).** Self-service identity verification for a health-record portal was never solved (password-only access is insufficient, and Google sign-in doesn't solve it either — OIDC proves email ownership, not that a claimed identity maps to a specific patient record). Decision: the existing staff-verifies-identity-in-person model plus a **DPDP Access-request PDF export** (`/data-requests/<id>/access.pdf`, §10) is the accepted substitute — DPDP's right-to-access obligation is about the patient receiving their data within statutory timelines, not about the delivery channel being self-service. Revisit only if a real identity-verification design is proposed. |
| Automated off-server backup | ✅ Built. `app/backup.py`, SQLite backup API (WAL-safe) + `clinical_uploads/`, Fernet-encrypted (`BACKUP_ENCRYPTION_KEY`, independent of `SECRET_KEY`, refuses to run unset). Off-site push is a pluggable shell command — provider choice stays deferred per §15. Admin-only `/backup`, both actions `reauth_required` + audited. See `tests/test_backup.py`, `BACKUP.md`. |
| Prescription history | ✅ Built. `db.list_prescriptions_for_patient`, cross-case most-recent-first view, 5th section on patient detail appended after the 4 order-fixed sections. See `tests/test_prescriptions.py`. |
| **DPDP Phase 3** | ❌ **Out of scope (2026-09-17 product decision, deferred indefinitely, alongside Patient portal).** Breach incident log, configurable retention policy, legal hold, automated retention sweep — none needed for the current single-clinic scale and none blocking any other shipped feature. Revisit if regulatory obligations or data volume change. |
| Threat model | ✅ Built. `THREAT_MODEL.md` covers all six named areas with file references; two residual gaps flagged as follow-up recommendations rather than fixed inline (no idle/absolute session timeout, no session revocation on deactivation/TOTP-reset) — revisit if PDF generation, Excel import, Google sign-in, or the patient portal change (first three now shipped; portal is out of scope). |
| Clinical document retention/deletion (added 2026-09-16, not originally in this table) | ✅ Built. Practitioner-only (`role_required("admin","doctor")` + `reauth_required`) single-file delete (reason optional) and bulk clear (reason required), both audited, both hidden from the receptionist role client-side too. See §5.4, `tests/test_attachments.py`. |
| Financial Assessment / Monthly Evaluation / Capital Investments (added 2026-09-18, ad-hoc, not in original scope) | ✅ Built. Per-case profitability table (`/financial-assessment`), Monthly Evaluation with a Short/Long Term (depreciation) toggle (`/financial-assessment/monthly`), and a Capital Investments asset ledger (`/financial-assessment/capital-investments`) — all `financial_access_required`, all audited. Cumulative ROI/payback tracking was explicitly **not** built (flagged as a separate, larger feature — see §15). See §5.15, `tests/test_financial_assessment.py`. |

---

## 15. Decisions Intentionally Deferred

These are genuinely open — don't treat them as settled just because they're absent from the anti-patterns list:

- Off-site backup provider (S3 vs Backblaze B2 vs a second server) — operational/cost decision, not architectural. `BACKUP_OFFSITE_COMMAND` is built to be provider-agnostic (pluggable shell command) precisely so this choice stays deferred.
- Approved communication channel for appointment reminders (WhatsApp Business API vs SMS gateway vs manual copy-paste, which is what's built today) — may be automated later; not required.
- Payment gateway integration, if any — payments are treated as manually logged records, not processed transactions, throughout this build. Adding a live gateway is a separate decision with its own PCI/compliance surface.
- Real identity-verification design for a future patient portal, should the 2026-09-17 out-of-scope decision (§14) ever be revisited.
- Cumulative capital-investment ROI/payback tracking (cumulative profit vs. cumulative capital invested, a "months to payback" projection) — flagged 2026-09-18 as a separate, larger feature on top of §5.15's straight-line depreciation view; not built.

Resolved since earlier drafts (moved out of "genuinely open"):
- Exact recurring-appointment UI/UX — resolved as a bounded set of real appointment rows (`series_id`), not a virtual/computed series; edit-one-vs-edit-series per §14's literal framing. See §14, Recurring appointments.
- Build sequencing of §14 items — resolved: every §14 item is now built except Patient portal and DPDP Phase 3, which are explicitly out of scope (see §14's status note), not merely unsequenced.

Settled and **not** open for re-litigation, despite appearing in earlier drafts of related planning docs:
- Sex field is Male/Female only (§5.2) — clinic requirement, not pending review.
- Receptionist has no financial access whatsoever (§14, Multi-user roles) — clinic requirement, not a configurable option.
- DPDP Phase 1/2 rules as documented in §5.11 do not require external counsel review before proceeding.
- Clinical document deletion/retention is a practitioner-only decision (added 2026-09-16, §5.4) — the receptionist role must never delete a clinical attachment, single or bulk, enforced server-side; there is no automatic purge-on-close.
- Patient portal and DPDP Phase 3 are out of scope for now (2026-09-17 product decision, §14) — not a configurable option, not pending review; revisit only on a fresh, explicit decision to re-open them.

---

## 16. Prompting Guidelines

### Always include this context
1. Stack: Flask + SQLite, raw `sqlite3.Row`, no ORM
2. DPDP compliance — never dilute Phase 1 or Phase 2
3. Case detail 9-section order (exact)
4. Patient detail 4-section order (exact)
5. Follow-up ≠ appointment — always distinguish in UI
6. `closed_at` only set when doctor explicitly closes
7. No-show logic: in `_save_appointment` via `_handle_noshow_followup()` — NOT in any separate status route
8. Reports: `DATE()` wrapper on `created_at`/`closed_at`, explicit form action
9. Login screen: inputs INSIDE form tag; storage dirs read via `app_config.branding_dir()`-style functions, never a flat `DATA_DIR` constant, in settings_routes
10. Referral notes: `<details>` element, collapsed by default, localStorage per case
11. Dashboard appointments: status badges from `appointment.status` only
12. Patient retention: always render, never hide on 0 lapsed
13. Once roles exist (§14): financial access is enforced server-side on every route/export/PDF/backup, never by hiding UI elements — receptionist must get `403`, not a filtered view

### Anti-patterns — never do these
- Do not use flask_sqlalchemy or any ORM
- Do not add a build step (webpack, npm, etc.)
- Do not hardcode DATA_DIR paths as string literals
- Do not read `DATA_DIR` as a flat module-level constant (`from app.config import DATA_DIR` at import time) in
  a file with storage-dir helpers — it goes stale under `monkeypatch.setattr(app_config, "DATA_DIR", ...)` in
  tests; use a function like `app_config.branding_dir()`/`backups_dir()`/`uploads_dir()`, read fresh per call
  (corrects this document's own earlier §9 example — see §9's correction note)
- Do not put login_heading / login_tagline inputs outside the `<form>` tag
- Do not use `BETWEEN start AND end` for timestamp fields without `DATE()` wrapper
- Do not hide patient retention section when lapsed count is 0
- Do not implement a separate status-change route for no-show logic — it belongs in `_save_appointment`
- Do not build UI on top of `arrived_at` / `seen_at` columns (wait time feature was removed)
- Do not put monthly revenue chart in Reports (belongs in Analytics)
- Do not drop or rename DB columns — additive migrations only
- Do not write to disk from PDF generators — always return bytes
- Do not commit an audit-log entry outside the transaction of the action it records (§14) — a failed action must never leave an orphan audit row, and a successful action must never be missing one

---

## 17. Glossary

| Term | Meaning in Feast9 v2 |
|---|---|
| Case | One course of dental treatment (e.g. RCT, Crown, Scaling) |
| Follow-up Date | Dashboard reminder on a case — NOT a calendar appointment |
| Appointment | Confirmed calendar booking with date, time, doctor |
| clear_followup | URL / hidden form param: case_id to clear after booking appointment |
| closed_at | Timestamp set when doctor explicitly marks case Closed |
| now_iso() | `datetime.now().strftime("%Y-%m-%d %H:%M:%S")` — second precision |
| today_iso() | `date.today().isoformat()` — date only (YYYY-MM-DD) |
| DATA_DIR | Single persistent directory: DB + uploads + clinical_uploads + backups + branding |
| DATE() | SQLite function to extract date from timestamp for correct BETWEEN comparisons |
| DPDP Notice | Data Processing Notice — mandatory at registration (Section 5, DPDP Act 2023) |
| Erasure | Soft-anonymise PII; preserve clinical and financial records |
| Plan B Export | Excel spreadsheet of all patient/case data, readable without the app |
| login_heading | H1 on login screen — configurable in Settings; falls back to clinic_name, then "Feast9" |
| login_tagline | Subtitle under clinic name on login page — configurable in Settings |
| Bible verse | Exodus 15:26 — always in login.html, never in Settings UI (changed 2026-09-17 from an earlier Jeremiah 30:17 placeholder) |
| Referral (collapsed) | Referral Notes hidden by default via HTML `<details>` element |
| arrived_at | DB column retained from removed wait time feature — ignore in new code |
| seen_at | DB column retained from removed wait time feature — ignore in new code |
| start.bat | Windows one-click startup script |
| _handle_noshow_followup | Helper function that sets tomorrow's follow-up on patient's active case |
| series_id | Self-referential FK on `appointments` tying every occurrence of a recurring series (incl. the first) together |
| is_historic_import | `patients` column flagging a row created via bulk Excel import rather than the manual registration form |
| consent_signature_filename | `cases` column — filename of an optional captured signature PNG, embedded in the consent PDF when present |
| google_sub | Google's stable per-account identifier on `admin` — used for linking, never the (mutable) email address |
| reauth_required | Decorator gating high-risk actions behind a fresh (≤10 min) re-authentication, not just an active session |
| Financial Assessment | Ad-hoc (2026-09-18) per-case profitability table — Profit = Billed − (Lab + Consultant Fee + Consumables + Misc Expense); not the same page as Reports (§5.15) |
| Monthly Evaluation | Extends Financial Assessment to a calendar month, adding clinic overhead; Short Term excludes depreciation, Long Term includes it (§5.15) |
| Capital Investment | An asset ledger entry (cost, purchase date, useful-life months) depreciated straight-line for Monthly Evaluation's Long Term view; soft-deactivate-only, no edit (§5.15) |

---

*Feast9 — September 2026.*
*One continuous build against this document — "v2"/"v3" labels elsewhere are historical from earlier planning drafts, not two separate projects. As of 2026-09-17, every §14 item is built (roles, audit log, TOTP, Google sign-in, recurring appointments, dental charting, automated backup, prescription history, threat model, clinical-document retention) except **Patient portal** and **DPDP Phase 3**, which are explicitly out of scope for now by product decision — not merely unsequenced. On 2026-09-18, Financial Assessment / Monthly Evaluation / Capital Investments (§5.15) was added as an ad-hoc, same-day build on top of this document's original scope — not a §14 item, not sequenced from an earlier draft. See §14's status note and §15 for what's settled vs. still genuinely open.*
