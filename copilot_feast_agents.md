# Feast9 v3 Fresh-Build Scope and Recommendations

## Planning Basis

This plan uses `feast9_v2_agents.md` as the functional baseline, but does not reproduce its single-admin security model. Every item listed under **Pending for v3** is included in the fresh-build scope:

- Multi-user roles
- Audit log
- TOTP 2FA
- Recurring appointments
- Dental charting
- Patient portal
- Automated off-site backup
- Prescription history
- DPDP Phase 3: breach logging, retention policy, and automated retention sweep

The receptionist must not have access to financial information.

## Recommended Roles

The original document proposes admin and receptionist. A safer model uses three roles:

| Capability | Admin | Doctor | Receptionist |
|---|---:|---:|---:|
| Patient registration and contact details | Yes | Yes | Yes |
| Appointments and reminders | Yes | Yes | Yes |
| Medical alerts needed for safe scheduling | Yes | Yes | Limited |
| Clinical cases, notes, prescriptions, attachments | Yes | Yes | No |
| Dental charting | Yes | Yes | No |
| Payments, costs, balances, revenue | Yes | Yes | **No** |
| Reports and analytics | Yes | Yes | **No** |
| DPDP access/correction requests | Yes | Yes | Create/request only |
| DPDP erasure and consent withdrawal processing | Yes | Yes, optionally | **No** |
| User management, settings, backups | Yes | No | No |
| Audit log viewing | Yes | Limited/read-only | No |
| Patient portal administration | Yes | No | No |

The doctor role reflects the single-practitioner workflow and avoids giving the receptionist clinical or financial authority.

## Financial Access Boundary

Financial access must be treated as a data-classification rule, not just a navigation rule. Financial information includes:

- Payment logs
- Treatment costs and cost history
- Outstanding balances
- Revenue reports and analytics
- Financial fields in case summaries and patient exports
- Financial PDFs and Excel exports
- Backup and export operations that could expose financial data

Enforcement requirements:

- Backend authorization on every financial route.
- Unauthorized requests return `403`.
- Receptionist-facing responses omit financial fields entirely.
- Receptionists cannot create, edit, delete, refund, or export payments.
- Receptionists cannot access financial PDFs, reports, analytics, backups, or bulk exports.
- Automated tests cover every financial endpoint and export path.

## Fresh-Build Scope

### 1. Architecture and Foundation

- Flask 3.x, raw `sqlite3`, Jinja2, and vanilla JavaScript.
- No frontend build step.
- One persistent `DATA_DIR`.
- Application factory and separate blueprints.
- Additive migrations and startup schema validation.
- Central authorization policy layer.
- Transaction helpers so business changes and audit entries commit together.
- Consistent validation and error handling.
- Automated tests from the start.

The two-worker SQLite approach requires care: enable WAL mode, configure a busy timeout, keep write transactions short, and review the PostgreSQL migration path if usage expands.

### 2. Authentication and Account Security

Add a `users` table containing:

- Username
- Password hash
- Role
- Active/disabled state
- Failed-login counters
- TOTP secret and enrollment state
- Last login
- Password-change timestamp

Include:

- Named user accounts; no shared accounts.
- Admin-created users.
- TOTP setup, QR provisioning, recovery codes, and reset flow.
- Login rate limiting and CSRF protection.
- Session invalidation after disablement or credential changes.
- Reauthentication for erasure, user management, backup/export, TOTP reset, and bulk import.

Use Werkzeug's current password-hashing defaults rather than permanently locking the new system to an older PBKDF2 configuration.

### 3. Audit Log

Create an audit log containing:

- Actor user ID and role
- UTC timestamp
- Action
- Entity and entity ID
- Request correlation ID
- Source IP and user-agent where appropriate
- Redacted before/after summaries
- Success or failure
- Reason for sensitive actions

Audit at minimum:

- Patient creation, edits, anonymisation, and exports
- Consent changes
- Case creation, status changes, and deletion attempts
- Clinical note and prescription changes
- Attachment uploads and downloads
- Payments and cost changes
- DPDP requests and resolutions
- User, role, password, and TOTP changes
- Backup and restore operations

Do not store unrestricted clinical or financial payloads in every audit row. Use redacted or field-level summaries and restrict audit-log access.

### 4. Patient and Clinical Management

Retain the v2 workflow and ordering:

- Patient registration
- DPDP notice and communications consent
- Guardian information for minors
- Treatment cases
- Visit notes
- Prescriptions
- Clinical attachments
- Lab requisitions
- Referrals
- Follow-up reminders
- Appointment conversion
- No-show follow-up

Add:

- Prescription history across all patient cases.
- A clinical history timeline.
- A clear distinction between operational receptionist notes and protected clinical notes.
- Record-level authorization checks on patient and case routes.

The v2 restriction of sex to only Male/Female should be reviewed with a clinician and legal/privacy advisor. If retained, document its clinical purpose; otherwise use a broader, clinically appropriate model.

### 5. Dental Charting

Dental charting must be structured clinical data, not merely an SVG saved per case.

Store:

- Tooth or region identifier
- Dentition type
- Surface or finding
- Condition/status
- Procedure association
- Notes
- Recorded-by user
- Recorded timestamp
- Correction/version history

The SVG is a presentation layer. Structured data allows searching, reporting, exporting, and history preservation.

Initial charting scope should define support for:

- Adult and primary dentition
- Missing/extracted teeth
- Caries
- Restorations
- Crowns
- Root canals
- Implants
- Planned versus completed treatment
- Tooth-level notes and attachments

### 6. Appointments

Implement recurring appointments using the existing schema direction, with explicit behavior for:

- Recurrence pattern
- End date or occurrence count
- Exception dates
- Editing one occurrence versus the series
- Cancellation behavior
- Conflict detection
- Closed days and holidays
- No-show handling per occurrence

Generate a bounded set of occurrences rather than unlimited appointments. Each occurrence should reference its recurrence series.

### 7. Patient Portal

First-release portal scope:

- Patient identity verification
- Access-request submission
- Consent and communication preference management
- Appointment request or confirmation workflow
- Download of an approved, filtered patient record

The portal must not expose unrestricted internal notes, staff notes, audit logs, or financial data. Define identity verification before implementing the portal UI; password-only access is insufficient.

### 8. DPDP Phase 3

Include:

- Breach incident log
- Configurable data-retention policy
- Automated retention sweep
- Legal hold to prevent deletion
- Dry-run retention reports
- Admin approval for irreversible actions
- Soft anonymisation where records must remain
- Evidence of what was anonymised and why

The existing assumption that clinical and financial records are always preserved during erasure requires legal review. The fresh build should support configurable policy rather than hard-code a legal conclusion.

### 9. Backups and Recovery

Include:

- Daily local SQLite backup
- Encrypted off-site backup to one supported provider
- Retention schedule
- Backup status and failure alerts
- Manual backup
- Restore into a separate validation directory
- Integrity checks
- Documented restore procedure
- Audit entries for backup, download, and restore operations

Receptionists must not trigger, download, or restore backups.

Recovery is an acceptance criterion: a backup is not considered valid until it has been restored successfully in a clean environment.

### 10. Reports and Analytics

Preserve the v2 distinction:

- Reports: operational and financial reporting for authorized roles.
- Analytics: charts and trends for authorized roles.

Review the use of Chart.js through a CDN. For a healthcare application, pin and serve the dependency locally to avoid external runtime dependence and support a stricter content-security policy.

## Delivery Phases

### Phase 1: Security Foundation

- App factory, schema, migrations
- Users and roles
- Authorization policies
- CSRF and session controls
- Audit framework
- Authentication and TOTP

### Phase 2: Core Workflows

- Patient registration
- DPDP Phase 1
- Patients and cases
- Appointments
- Follow-ups
- No-show handling

### Phase 3: Clinical Workspace

- Notes
- Prescriptions
- Prescription history
- Attachments
- Labs
- Referrals
- Consent records

### Phase 4: Financial Workspace

- Costs
- Payments
- Balances
- Reports
- Analytics
- Exports

Before release, add explicit tests proving that receptionists cannot access financial information through routes, downloads, PDFs, APIs, or exports.

### Phase 5: Dental Charting

- Structured tooth data
- Chart UI
- Chart history
- Case association
- Exports

### Phase 6: DPDP and Governance

- Data rights
- Patient portal
- Breach log
- Retention rules
- Anonymisation workflow

### Phase 7: Operations and Resilience

- Recurring appointments
- Off-site backups
- Restore verification
- Branding and settings
- Deployment documentation

### Phase 8: Hardening and Acceptance

- Role-matrix tests
- Audit completeness tests
- Security review
- Backup restore drill
- Deployment verification
- Regression coverage for all v2 invariants

## Critical Recommendations

1. Replace the single-admin assumption with named users immediately.
2. Add a dedicated doctor role.
3. Enforce financial access at the data and route layers, not only in the UI.
4. Build authorization tests before feature tests.
5. Commit audit entries in the same transaction as the audited action.
6. Model dental charting as structured data; use SVG only for display.
7. Define patient-portal identity verification before building portal screens.
8. Encrypt backups and test restoration regularly.
9. Use UTC internally and display clinic-local time.
10. Add soft-delete or versioning for clinical and financial records instead of destructive edits.
11. Review DPDP and clinical-record assumptions with qualified legal and clinical advisors.
12. Add a threat model covering receptionist misuse, exports, shared devices, stolen sessions, backups, and uploaded files.

## Production Success Criteria

The system is ready for production only when:

- A receptionist cannot access financial data through any route, export, PDF, API response, or backup.
- Every sensitive mutation has an attributable audit entry.
- TOTP enrollment, login, recovery, and reset are tested.
- Dental chart data remains historically traceable after edits.
- Recurring appointments handle exceptions without duplicate or unexpected bookings.
- Patients can submit and track permitted DPDP requests.
- Retention and breach workflows are documented and auditable.
- An off-site backup can be restored successfully in a clean environment.
- v2 workflow invariants remain covered by automated tests, including follow-up versus appointment behavior, case closure, report date filtering, consent enforcement, and protected attachments.
