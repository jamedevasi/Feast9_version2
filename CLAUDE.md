# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

The app is under active, phased construction, built directly against `feast9_v2_agents.md`. It is not a git repository. Built so far:

- **Phase 1 — Foundation + Patients**: app factory, auth (setup/login/logout, PBKDF2, CSRF, DB-backed rate limiting, security headers), patient registration/search/detail.
- **Phase 2 — Cases**: full 9-section case detail (Consent Forms, Visit Notes, Prescriptions, Clinical Attachments, Lab Requisitions, Referral Notes, Payment Log, Follow-up & Next Action, Cost History & Revisions), wired into the patient detail page.
- **Phase 3 — Appointments**: `appointment_routes.py` (calendar month view, new/edit/delete), doctor-colour-coded month grid, patient-detail Appointments section, "📅 Book Appointment" link on a case's Follow-up section (`clear_followup` flow — clears the case's follow-up once the appointment is booked), no-show → next-day follow-up logic in `_save_appointment`'s edit path (not a separate status route), click-to-copy WhatsApp/SMS reminder text on the edit page. Recurring-appointment columns exist on the schema but have no UI yet (§14 item).

Not yet built — all part of the same build, not a separate later project: dashboard widgets, reports/analytics, DPDP Phase 2 (data-rights requests), login-screen branding/settings, backups, PDF generation, Excel import, doctors/procedure-types admin UI (they exist as seeded lookup data only), **plus** multi-user roles (admin/doctor/receptionist with server-side financial lockout), audit log, TOTP 2FA, Google sign-in, recurring appointments, structured dental charting, patient portal, automated off-site backup, DPDP Phase 3 (breach log/retention sweep) — see `feast9_v2_agents.md` §14 for full detail on this last group. None of §14 is deferred or optional; it's unsequenced, not out of scope.

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

`feast9_v2_agents.md` §4 never defined DDL for `admin`/`login_attempts` (auth), `case_visit_notes`, `prescriptions`, `payments`, or `cost_revisions`, despite requiring the features that need them. These were designed during the build (see `app/db.py`) following the spec's own conventions (additive, `CREATE TABLE IF NOT EXISTS`, explicit timestamps). The `cases` table also has three columns beyond the spec's literal DDL — `consent_recorded`, `consent_recorded_at`, `consent_notes` — needed for the "red border if no consent" rule; signature capture and the consent PDF remain out of scope until PDF generation is built.
