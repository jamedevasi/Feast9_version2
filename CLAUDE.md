# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

The app is under active, phased construction, built directly against `feast9_v2_agents.md`. It is now a git repository (`origin` = https://github.com/jamedevasi/Feast9_version2.git). Built so far:

- **Phase 1 — Foundation + Patients**: app factory, auth (setup/login/logout, PBKDF2, CSRF, DB-backed rate limiting, security headers), patient registration/search/detail.
- **Phase 2 — Cases**: full 9-section case detail (Consent Forms, Visit Notes, Prescriptions, Clinical Attachments, Lab Requisitions, Referral Notes, Payment Log, Follow-up & Next Action, Cost History & Revisions), wired into the patient detail page.
- **Phase 3 — Appointments**: `appointment_routes.py` (calendar month view, new/edit/delete), doctor-colour-coded month grid, patient-detail Appointments section, "📅 Book Appointment" link on a case's Follow-up section (`clear_followup` flow — clears the case's follow-up once the appointment is booked), no-show → next-day follow-up logic in `_save_appointment`'s edit path (not a separate status route), click-to-copy WhatsApp/SMS reminder text on the edit page. Recurring-appointment columns exist on the schema but have no UI yet (§14 item).
- **Phase 4a — Multi-user roles (§14 item)**: `admin` table extended (additive `role`/`is_active` columns via `_migrate_admin_roles`) to hold every account, not just the bootstrap admin. Three roles: `admin`, `doctor`, `receptionist`. `app/routes/user_routes.py` (admin-only `/users` list/create/deactivate/reactivate, blocked from deactivating the last active admin). `app.auth.role_required(*roles)` and `financial_access_required` (blocks `receptionist`) enforce access server-side — applied to `add_payment`/`revise_cost` in `case_routes.py`. Case detail's `detail()` route redacts `total_cost`/`payments`/`balance`/`cost_revisions` entirely out of the render context for receptionist sessions (never sent to the client, not just CSS-hidden); `case_sections/payments.html` and `cost_history.html` show a "Restricted" notice in that case, preserving the fixed section order. Case creation silently zeroes any `total_cost` a receptionist session posts, regardless of what's in the form. See `tests/test_roles.py` for the enforcement tests (403s on every financial route/record for receptionist, admin/doctor unaffected).
- **Phase 4b — Audit log (§14 item)**: additive `audit_log` table (`actor_user_id, role, ts_utc, action, entity, entity_id, correlation_id, before_summary, after_summary, ip, user_agent, outcome`). `db._write_audit(conn, ...)` takes the caller's already-open connection and does **not** commit/close — every instrumented db.py write function (`update_patient`, `close_case`, `record_case_consent`, `add_visit_note`, `add_prescription`, `add_payment`, `update_case_cost`, `add_attachment`, `create_user`, `set_user_active`) inserts its audit row in the same transaction as the action it records. `db.write_audit_now()` is the one exception — a standalone commit for attachment *downloads* (`clinical.serve_attachment`), which has no other write to piggyback on. Summaries are field-level/redacted by construction: patient edits log changed field *names* only (never values — allergies/medical conditions are sensitive), visit notes/prescriptions log a length + date (never the clinical text), consent logs the fact only. Financial actions (payments, cost revisions) do log amounts — that's the point of a financial audit trail, not a redaction gap. Admin-only viewer at `/audit-log` (`app/routes/audit_routes.py`). See `tests/test_audit_log.py`, including the check that sensitive field values never appear in a logged row.
- **Phase 4c — TOTP 2FA (§14 item)**: `pyotp` (codes) + `qrcode` (SVG QR, no Pillow dependency — `qrcode.image.svg.SvgPathImage`). Additive `admin` columns `totp_secret`, `totp_enabled`, `totp_recovery_codes_json`. Self-service enrollment at `/totp/setup` (`app/routes/totp_routes.py`) — scan QR or enter the key manually, confirm with a live code, then one-time recovery codes are shown exactly once (`/totp/recovery-codes`, session-only, hashed at rest same as passwords). Login becomes two-step when `totp_enabled`: password success stores `totp_pending_user_id`/`totp_pending_next` in session and redirects to `/login/totp` (code or a recovery code — recovery codes are consumed on use, `db.consume_recovery_code`) rather than completing the session; `admin_id` is only set after the second factor passes. **Step-up re-authentication** (§14: "not just an active session") is `app.auth.reauth_required` — a session's `reauth_at` is stamped fresh at every successful login (password-only or TOTP-completed) and must be within `REAUTH_WINDOW_MINUTES` (10) or the decorator redirects to `/reauth` (password, +code if enabled) before continuing; applied to `/users/new`, `/users/<id>/deactivate`, `/users/<id>/activate`, `/users/<id>/reset-totp`, and `/totp/disable` — the "user management" and "TOTP reset" items from §14's high-risk-action list (backup/restore and bulk import/export aren't built yet, so not wired up). Admin can force-reset another user's TOTP from `/users` (audited as `totp_reset`). See `tests/test_totp.py`, including a test that manipulates `session_transaction()` to prove a stale (10+ minute) session is rejected until it steps up.

- **Threat model (§14 item)**: `THREAT_MODEL.md` covers the six areas §14 names by name (receptionist misuse of scheduling-only access, export/PDF paths, shared front-desk devices, stolen sessions, backup file exposure, uploaded clinical files) — assets, actors, current mitigations with file references, and residual risks. Flags two real gaps as follow-up recommendations rather than fixing them inline: no idle/absolute session timeout, and no session revocation on deactivation/TOTP-reset. Revisit it when PDF generation, Excel import, Google sign-in, or the patient portal are built — each is called out in the doc as a likely trigger.
- **Automated off-server backup (§14 item)**: `app/backup.py` — `create_backup()`/`restore_backup()`. A consistent DB snapshot via SQLite's own backup API (safe under WAL) + `clinical_uploads/` are tarred and encrypted with Fernet (`cryptography`, key in `BACKUP_ENCRYPTION_KEY`, deliberately independent of `SECRET_KEY`); refuses to run at all if the key isn't set rather than ever writing an unencrypted backup. Off-site push is a pluggable shell command (`BACKUP_OFFSITE_COMMAND`, `{file}` placeholder) — provider choice (S3/B2/second server, via rclone/rsync) stays a deferred operational decision per §15, not hardcoded. `run_backup.py` (schedule nightly via cron/Task Scheduler) and `restore_backup.py` (CLI-only, never a web route — makes a safety copy of the current DB, refuses to overwrite without `--force`) at the repo root; full setup/scheduling/restore-testing instructions in `BACKUP.md`. Admin-only `/backup` (`app/routes/backup_routes.py`) lists history and lets an admin run one on demand or download a past one — both `reauth_required`, both audited (`backup_created`, `backup_downloaded`). Dashboard shows a warning banner to admins if the last backup failed, never ran, or is more than 26h stale. See `tests/test_backup.py`.

Not yet built — all part of the same build, not a separate later project: dashboard widgets, reports/analytics, DPDP Phase 2 (data-rights requests), login-screen branding/settings, PDF generation, Excel import, doctors/procedure-types admin UI (they exist as seeded lookup data only), **plus** Google sign-in (explicitly optional/secondary per §14 itself — local password+TOTP remains the required baseline regardless), recurring appointments, structured dental charting, patient portal, prescription history (cross-case view), DPDP Phase 3 (breach log/retention sweep) — see `feast9_v2_agents.md` §14 for full detail on this last group. None of §14 is deferred or optional (Google sign-in aside, which the spec itself marks optional); it's unsequenced, not out of scope.

**Commands:**
```powershell
# Setup (Windows, Python 3.14 — see requirements-win-py314.txt / requirements.txt for Linux/Mac)
python -m venv venv
venv\Scripts\activate
pip install -r requirements-win-py314.txt -r requirements-dev.txt

# Run locally
$env:DATA_DIR = "C:\path\to\data"; $env:SECRET_KEY = "local-dev-key"; python run.py

# Tests (run after every change — the whole suite, not just the touched area)
pytest                          # full suite
pytest tests/test_cases.py      # one file
pytest tests/test_cases.py::test_closed_at_only_set_on_explicit_close   # one test

# Seed demo data (idempotent) against a running DATA_DIR
python seed_demo_data.py
```

## The three documents

| File | Role |
|---|---|
| `feast9_v2_agents.md` | **Single source of truth.** The authoritative spec for Feast9, a dental clinic practice management system. Contains the full schema, route patterns, UX rules, security rules, and known-gotcha fixes. Any future build must follow this file exactly. |
| `codex_feast_agents.md` | Secondary planning input — an abstract requirements doc exploring a multi-role, TOTP, Google-sign-in version of the system. Superseded where it conflicts with `feast9_v2_agents.md`. |
| `copilot_feast_agents.md` | Secondary planning input — a phased v3 fresh-build plan (roles, audit log, dental charting, etc.) written on top of v2. Superseded where it conflicts with `feast9_v2_agents.md`. |

`feast9_v2_agents.md` has already absorbed the parts of the other two documents worth keeping (see its §14 "Remaining Build Scope" and §15 "Decisions Intentionally Deferred"). When asked to extend or rebuild the app, work from `feast9_v2_agents.md` alone unless told otherwise — it is the merged, corrected version. "v2"/"v3" naming in these docs is historical — there is one build, one roadmap; §14's roles/audit/TOTP/etc. are in scope, just not yet sequenced.

## Non-negotiable requirements (do not "fix" or soften these)

These are stated as settled in `feast9_v2_agents.md` and must not be treated as open questions, regardless of what the secondary planning docs suggest:

- Sex field is `Male` / `Female` only — no other options.
- A receptionist role (once built) must have **zero** access to financial data (payments, costs, balances, revenue reports/exports/PDFs, backups), enforced server-side on every route — never UI-only.
- DPDP Act 2023 compliance (data notice, consent, data-rights requests) must never be diluted; the documented DPDP rules do not require external legal review before implementation.
- Follow-up (a dashboard reminder on a case) and Appointment (a confirmed calendar booking) are distinct concepts and must never be conflated in UI or logic.
- Additive-only DB migrations — never drop or rename columns (`arrived_at`/`seen_at` are deliberately retained, unused columns from a removed feature).

## Architecture (as built)

A **no-build-step Flask + raw-SQLite** system — no ORM, no frontend framework:

- `app/db.py` is the only file that touches SQLite directly; all other modules go through it. It uses an explicit column-whitelist pattern for every insert/update (see `add_patient`/`update_patient`, `add_case`/`update_case`) — never build SQL column lists from raw request-derived dict keys.
- Routes are split into per-domain blueprints under `app/routes/`, each registered in `app/__init__.py`: `auth_routes.py`, `patient_routes.py`, `case_routes.py` (case core + visit notes + prescriptions + payments + cost revisions + follow-up + consent), `clinical_routes.py` (attachments + lab requisitions + referral notes — grouped per feast9_v2_agents.md's own file layout), `dashboard_routes.py`.
- The case detail page (`templates/case_detail.html`) composes its 9 fixed-order sections via `{% include %}` of `templates/case_sections/*.html` partials — add new case sub-features as a new partial + route, not by growing case_detail.html directly.
- Clinical file uploads are stored outside the web root (`DATA_DIR/clinical_uploads/`), UUID-named, validated by magic bytes only (`app/validators.py:detect_upload_type` — never trust the client-supplied extension), served only through an authenticated route (`clinical.serve_attachment`).
- CSRF validation (`app/csrf.py`) is required on every POST. Every page with a logged-in nav (`base.html`) renders a second hidden CSRF input in the logout form — when scripting against the app (curl, tests), take the *first* `csrf_token` match on a page, not the count.
- Case detail and patient detail each have a fixed, non-negotiable section order — see §5.2/§5.3/§8 of `feast9_v2_agents.md` before touching those templates. Section-order regressions are caught by `test_patient_detail_section_order` / `test_case_detail_section_order`.
- Visit notes, prescriptions, and payments/cost-revisions are **append-only** (no edit/delete routes) — intentional, matches the "controlled correction process, not silent destructive editing" principle for clinical/financial records.
- `total_cost` on a case only ever changes via `db.update_case_cost()`, which inserts a `cost_revisions` row automatically when the value actually changes. Never `UPDATE cases SET total_cost` directly.
- CSP is `script-src 'self'` with no inline scripts anywhere — any new client-side behavior goes in a static `.js` file (see `patient_form.js`, `referrals.js`), not an inline `<script>` block.
- Not yet in scope: reports queries needing `DATE()` wrapping on timestamp columns, and the no-show → follow-up appointment logic — both apply once Appointments/Reports are built (see §5.9/§5.7 of the spec).

## Planned stack & setup (from feast9_v2_agents.md §2)

- Python 3.11/3.12 (3.14 supported via `requirements-win-py314.txt`), Flask 3.x, SQLite 3 (WAL mode + busy timeout — 2 gunicorn workers share one DB file), ReportLab, openpyxl, optional Pillow, Jinja2 + vanilla JS, Chart.js (vendored locally, not CDN).
- Gunicorn on Linux/Mac, Waitress on Windows.
- Required env vars: `SECRET_KEY`, `DATA_DIR`; production also needs `SESSION_COOKIE_SECURE=1` and `FLASK_DEBUG=0`.
- Local dev entry point: `python run.py`. Production: `gunicorn wsgi:app` (Linux/Mac) or Waitress (Windows).

Consult `feast9_v2_agents.md` directly for exact schema DDL, route code patterns, the 27-point test checklist, and the full glossary before implementing any feature — it is far more detailed than this summary.

## Tables not in the original spec

`feast9_v2_agents.md` §4 never defined DDL for `admin`/`login_attempts` (auth), `case_visit_notes`, `prescriptions`, `payments`, or `cost_revisions`, despite requiring the features that need them. These were designed during the build (see `app/db.py`) following the spec's own conventions (additive, `CREATE TABLE IF NOT EXISTS`, explicit timestamps). The `cases` table also has three columns beyond the spec's literal DDL — `consent_recorded`, `consent_recorded_at`, `consent_notes` — needed for the "red border if no consent" rule; signature capture and the consent PDF remain out of scope until PDF generation is built. The `admin` table gained `role`/`is_active` columns (Phase 4, additive `ALTER TABLE` in `_migrate_admin_roles`) — it holds every user account (admin/doctor/receptionist), not just the bootstrap admin; the table name was kept as-is to avoid a pointless rename.
