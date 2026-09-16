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
- Pillow is optional — app boots and works without it

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
| Excel | openpyxl | Reports + Plan B backup |
| Images | Pillow ≥ 10.0.0 | Optional — wrapped in try/except everywhere |
| Frontend | Jinja2 + vanilla JS | No React, no Vue, no build step |
| Charts | Chart.js 4.x, vendored locally in `static/` | Analytics tab only — not loaded from CDN, keeps CSP `script-src` self-only |

### requirements.txt (Linux / Mac / Python 3.11 or 3.12)
```
Flask==3.1.3
Werkzeug==3.1.7
openpyxl==3.1.5
reportlab==4.4.10
gunicorn==23.0.0
Pillow>=10.0.0
```

### requirements-win-py314.txt (Windows + Python 3.14)
```
Flask==3.1.3
Werkzeug==3.1.7
openpyxl==3.1.5
reportlab==4.4.10
waitress>=3.0.0
Pillow>=11.1.0
```

Two files exist because: gunicorn does not run on Windows (use waitress), and Pillow 3.14 needs a newer version. Always use requirements.txt on Linux/Mac servers.

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
guardian_mobile TEXT DEFAULT ''
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
closed_at TEXT DEFAULT ''                   -- set ONLY when doctor explicitly marks Closed; uses now_iso()
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
is_recurring INTEGER NOT NULL DEFAULT 0,   -- schema ready; UI not built
recur_interval TEXT NOT NULL DEFAULT '',
recur_until TEXT NOT NULL DEFAULT ''
```

**Note on arrived_at / seen_at:** These columns exist in the database from an earlier feature (wait time tracking) that was removed. Keep them — removing columns from SQLite is disruptive and the data is harmless. Do not build any UI on top of them.

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
login_heading          -- caption below login screen image; blank = "St Apollonia — pray for us."
login_tagline          -- subtitle under clinic name on login; blank = default text
login_image_filename   -- filename in DATA_DIR/branding/; blank = use saint_apollonia.png
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

---

## 5. Features

### 5.1 Authentication
- Single admin account, PBKDF2 password hash (Werkzeug)
- Security question for self-service password reset — no email needed
- `reset_admin_password.py` for emergency CLI recovery
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
| `login_heading` | "St Apollonia — pray for us." | Caption below login image |
| `login_tagline` | "Patient & case management — please log in." | Subtitle under clinic name |
| `login_image_filename` | (uses `static/img/saint_apollonia.png`) | Custom image filename in DATA_DIR/branding/ |

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
  "I will restore you to health and heal your wounds."
  <span class="verse-ref">— Jeremiah 30:17</span>
</div>
```

### 5.13 Settings Navigation

**Top nav:** Dashboard | Patients | Appointments | Reports | Analytics | Data Rights | Settings

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

# settings_routes.py — this import is REQUIRED at module level:
from app.config import DATA_DIR
# Missing this causes NameError → 500 on any image upload operation.

# login_image route must NOT have @login_required
# Use pathlib for cross-platform paths:
import pathlib
path = pathlib.Path(DATA_DIR) / "branding" / filename
return send_file(str(path), mimetype=mt)
```

**Environment variables:**

| Variable | Required | Notes |
|---|---|---|
| SECRET_KEY | Yes | 32+ byte random hex. App warns on startup if using default. |
| DATA_DIR | Yes | Persistent directory for DB, uploads, branding, backups |
| SESSION_COOKIE_SECURE | Production only | Set to `1` when HTTPS is active |
| FLASK_DEBUG | Must be `0` | Never `1` in production |

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

**Backup validity:** A backup is only trusted once it has been restored successfully into a separate, clean environment. v2 does not yet automate this (see §14, Automated off-server backup) — until then, treat a periodic manual restore test as a required checklist item, not optional.

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
21. Bible verse (Jeremiah 30:17) always present on login page
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

These are not a deferred "v3" — they are part of this build's scope and belong in the overall plan alongside Appointments/Dashboard/Reports/Analytics/DPDP Phase 2/Branding/PDFs. "v3" language elsewhere in this doc is historical from earlier drafts; treat every row below as work still to be sequenced into the build, not work to skip.

| Feature | Notes |
|---|---|
| Multi-user roles | Three roles: Admin, Doctor, Receptionist. **Requirement, not optional:** the receptionist has zero access to financial data — payments, costs/balances, revenue reports, financial PDFs, exports, backups — enforced server-side on every route/response, never hidden by navigation alone. Requires `role` column in `users`, role checks in `@login_required` plus record-level checks, automated tests proving a receptionist session gets `403` on every financial route/export/PDF/backup path. |
| Audit log | Table: `audit_log(id, actor_user_id, role, ts_utc, action, entity, entity_id, correlation_id, before_summary, after_summary, ip, user_agent, outcome)`. Use redacted/field-level before/after summaries — never dump full clinical notes into a row. Commit the audit entry in the **same transaction** as the action it records. Log at minimum: patient edits/anonymisation/exports, consent changes, case status changes, clinical note/prescription changes, attachment upload/download, payments/cost changes, DPDP requests, user/role/password/TOTP changes, backup/restore operations. |
| TOTP 2FA | `pyotp` library, `users.totp_secret` column, QR setup page, one-time recovery codes, admin-controlled reset. Require re-authentication (not just an active session) before high-risk actions: user management, backup download/restore, bulk import/export, TOTP reset, erasure. |
| Google sign-in (optional, secondary) | Already-decided design, not an open question: OpenID Connect for identity only (`openid`, `email`, `profile` scopes — never Gmail/Drive/Calendar/contacts). Must link to an existing admin-approved local user via verified email + explicit first-time link step. Must never be the *only* path in — local password + TOTP + recovery codes remain the required baseline and break-glass path. Admin can unlink/disable/revoke sessions. Validate issuer, audience, signature, expiry, nonce, state, redirect URI server-side. Log link/unlink/sign-in events. |
| Recurring appointments | Schema columns ready (is_recurring, recur_interval, recur_until). Needs: recurrence pattern, end date/occurrence count, exception dates, edit-one-vs-edit-series, cancellation behaviour, conflict detection, closed-days/holidays, per-occurrence no-show handling. Generate a bounded set of occurrences (each referencing its series) — not unlimited appointments. |
| Dental charting | Not just an SVG per case — biggest clinical gap in the system. Model as structured data: tooth/region identifier, dentition type, surface/finding, condition/status, procedure association, notes, recorded-by, recorded-at, correction/version history. SVG is a presentation layer over that data, not the source of truth. Initial scope: adult + primary dentition, missing/extracted teeth, caries, restorations, crowns, root canals, implants, planned-vs-completed treatment. |
| Patient portal | Self-service data access + DPDP request submission. **Identity verification must be designed before any portal UI is built** — password-only access to a health record portal is insufficient. Must not expose internal/staff notes, audit logs, or financial data. |
| Automated off-server backup | Nightly rclone/rsync to S3, Backblaze B2, or a second server, encrypted. Retain backup status/failures, alert admin on failure. Restore-tested in a clean environment is the acceptance bar (see §11, Backup validity) — a backup that has never been restore-tested is not considered valid. |
| Prescription history | All prescriptions across all cases shown on patient detail tab. |
| DPDP Phase 3 | Breach incident log, configurable (not hard-coded) data-retention policy, legal hold to block deletion, automated retention sweep with dry-run reports and admin approval before irreversible actions, soft anonymisation with evidence of what was anonymised and why. |
| Threat model | Not yet written — needed once the receptionist role exists. Cover: receptionist misuse of scheduling-only access, export/PDF paths, shared front-desk devices, stolen sessions, backup file exposure, uploaded clinical files. |

---

## 15. Decisions Intentionally Deferred

These are genuinely open — don't treat them as settled just because they're absent from the anti-patterns list:

- Off-site backup provider (S3 vs Backblaze B2 vs a second server) — operational/cost decision, not architectural.
- Approved communication channel for appointment reminders (WhatsApp Business API vs SMS gateway vs manual copy-paste, which is what's built today) — may be automated later; not required.
- Payment gateway integration, if any — payments are treated as manually logged records, not processed transactions, throughout this build. Adding a live gateway is a separate decision with its own PCI/compliance surface.
- Exact recurring-appointment UI/UX (calendar view of a series vs list) — schema direction is set (§14), interaction design is not.
- Build sequencing of §14 items relative to the rest of the roadmap (Appointments/Dashboard/Reports/Analytics/Branding/PDFs) — all are in scope; order is a standing decision to revisit each time a new phase starts.

Settled and **not** open for re-litigation, despite appearing in earlier drafts of related planning docs:
- Sex field is Male/Female only (§5.2) — clinic requirement, not pending review.
- Receptionist has no financial access whatsoever (§14, Multi-user roles) — clinic requirement, not a configurable option.
- DPDP Phase 1/2 rules as documented in §5.11 do not require external counsel review before proceeding.

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
9. Login screen: inputs INSIDE form tag, `DATA_DIR` imported in settings_routes
10. Referral notes: `<details>` element, collapsed by default, localStorage per case
11. Dashboard appointments: status badges from `appointment.status` only
12. Patient retention: always render, never hide on 0 lapsed
13. Once roles exist (§14): financial access is enforced server-side on every route/export/PDF/backup, never by hiding UI elements — receptionist must get `403`, not a filtered view

### Anti-patterns — never do these
- Do not use flask_sqlalchemy or any ORM
- Do not add a build step (webpack, npm, etc.)
- Do not hardcode DATA_DIR — always `from app.config import DATA_DIR`
- Do not omit `from app.config import DATA_DIR` in settings_routes.py
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
| login_heading | Caption below login screen image — configurable in Settings |
| login_tagline | Subtitle under clinic name on login page — configurable in Settings |
| Bible verse | Jeremiah 30:17 — always in login.html, never in Settings UI |
| Referral (collapsed) | Referral Notes hidden by default via HTML `<details>` element |
| arrived_at | DB column retained from removed wait time feature — ignore in new code |
| seen_at | DB column retained from removed wait time feature — ignore in new code |
| start.bat | Windows one-click startup script |
| _handle_noshow_followup | Helper function that sets tomorrow's follow-up on patient's active case |

---

*Feast9 — September 2026.*
*One continuous build against this document — "v2"/"v3" labels elsewhere are historical from earlier planning drafts, not two separate projects. §14 (roles, audit log, TOTP, dental charting, etc.) is in scope alongside Appointments/Dashboard/Reports/Analytics/Branding/PDFs; see §15 for the standing note on how each phase's sequencing is decided.*
