# Feast9 Threat Model

Written per `feast9_v2_agents.md` §14 ("Threat model — not yet written, needed once the
receptionist role exists"). The receptionist role now exists (Phase 4a), so this document
covers the six areas §14 calls out by name, plus the assets/actors/trust-boundary context
needed to make sense of them. It reflects the codebase as of the TOTP 2FA commit (Phase 4c)
and should be revisited whenever a new role, external integration, or data-export path is added
— PDF generation, Excel import, Google sign-in, and the patient portal are the most likely
future triggers for a revision.

## 1. Assets

| Asset | Sensitivity | Where it lives |
|---|---|---|
| Patient PII/PHI (name, DOB, contact, medical conditions, allergies, consent records) | High — DPDP-regulated health data | `patients`, `cases` tables |
| Clinical notes, prescriptions, lab requisitions, referrals | High — clinical content | `case_visit_notes`, `prescriptions`, `lab_requisitions`, `referral_notes` |
| Clinical attachments (X-rays, photos, lab reports) | High — clinical content, largest single files | `DATA_DIR/clinical_uploads/`, UUID-named |
| Financial data (payments, cost revisions, balances) | Medium-high — financial + receptionist-excluded | `payments`, `cost_revisions`, `cases.total_cost` |
| Credentials (password hashes, TOTP secrets, recovery-code hashes) | Critical | `admin` table |
| Audit log | Medium — itself a record of who touched what | `audit_log` table |
| Session cookies | High — bearer of an authenticated identity | Client-side, signed by `SECRET_KEY` |
| Backups (once built — see the accompanying `BACKUP.md`) | Critical — a single file containing everything above | `DATA_DIR/backups/` (local), optional off-site destination |

## 2. Actors and trust levels

- **Admin** — full access: all clinical/financial data, user management, audit log, TOTP resets.
- **Doctor** — full clinical + financial access, no user management.
- **Receptionist** — clinical/scheduling access only. **Zero access to financial data**,
  enforced server-side (`app.auth.financial_access_required`, `can_view_financial_data`) —
  not a UI-only restriction. See §3 below.
- **Unauthenticated attacker** — no valid session; the only reachable surface is `/`,
  `/setup` (only before the first account exists), `/login`, `/login/totp`.
- **A former/deactivated user** — `is_active = 0` rows are excluded from
  `db.get_user_by_username`, so a deactivated account cannot start a new session, but any
  session it already held before deactivation is not proactively revoked (see §3, "stolen
  sessions").

There is currently exactly one tenant (one clinic, one `DATA_DIR`) — there is no cross-tenant
boundary to reason about.

## 3. The six areas (feast9_v2_agents.md §14)

### 3.1 Receptionist misuse of scheduling-only access

**Threat:** a receptionist account (or a compromised receptionist session) is used to view or
tamper with financial data it should never see, or to inflate/deflate a case's cost.

**Current mitigations:**
- `case_routes.detail()` never places `total_cost`/`payments`/`balance`/`cost_revisions` into
  the render context for a receptionist session — the data does not reach the browser, it
  isn't just hidden with CSS (`app/routes/case_routes.py`).
- `add_payment` and `revise_cost` are decorated with `@financial_access_required`, which
  `abort(403)`s before any write happens (`app/auth.py`).
- Case creation silently zeroes any `total_cost` a receptionist session posts, regardless of
  what the client sends — defends against a receptionist hand-crafting the POST body.
- All of the above is exercised by `tests/test_roles.py`.

**Residual risk:** a receptionist can still see non-financial clinical detail (visit notes,
attachments, prescriptions) for any patient — by design, since §14 only requires financial
lockout, not a narrower clinical scope. If clinic policy later wants receptionists restricted
to scheduling only (no clinical note content), that is a new, larger scope decision, not a bug
in the current build.

### 3.2 Export/PDF paths

**Threat:** a bulk export or generated PDF becomes a way to exfiltrate financial or clinical
data that the UI would otherwise gate by role, or to leak more than the requester needed.

**Current mitigations:** none needed yet — **no export or PDF generation exists in the
codebase.** This is the one area where "current mitigations" is genuinely "not applicable."

**Recommendation for when it's built:** every export/PDF route must re-run the same
`financial_access_required`/`can_view_financial_data` checks used in `case_routes.py` — a
receptionist must not be able to get financial figures through a PDF that the HTML page
already denies them. Treat export/PDF as a first-class route requiring the same role check as
its data source, not a separate code path that's easy to forget to gate.

### 3.3 Shared front-desk devices

**Threat:** a clinic PC used by multiple staff over a shift is left logged in, letting the next
person at the desk act as the previous session's user.

**Current mitigations:**
- Explicit logout (`auth.logout`) clears the session.
- `role_required`/`financial_access_required` still apply per-request regardless of who's
  physically at the keyboard, limiting blast radius to what that logged-in role can do.
- `reauth_required` forces a fresh password (+ TOTP code if enabled) before user management or
  a TOTP reset even within an active session — so a walk-up user can't silently create new
  accounts on someone else's forgotten-but-still-open session without knowing that user's
  password.

**Residual risk — no idle/absolute session timeout.** Flask's session cookie here is a
non-permanent cookie (`session.permanent` is never set, `PERMANENT_SESSION_LIFETIME` is never
configured in `app/__init__.py`); it is deleted by the *browser* on close, but the signed
cookie value itself carries no server-enforced expiry. A session left open on a shared device
(browser not closed, or closed-and-reopened by a browser that restores tabs) remains valid
indefinitely for anything short of the `reauth_required`-gated actions. **Recommendation:** add
an idle timeout (e.g. `PERMANENT_SESSION_LIFETIME` + `session.permanent = True` +
`SESSION_REFRESH_EACH_REQUEST`) — a small, well-scoped follow-up, not done as part of this
document.

### 3.4 Stolen sessions

**Threat:** a session cookie is captured (network interception, malware, physical access to an
unlocked device) and reused by an attacker.

**Current mitigations:**
- `SESSION_COOKIE_HTTPONLY = True` — not readable from JavaScript, so a same-origin XSS bug
  (none known — CSP is `script-src 'self'` with no inline scripts anywhere) can't read it via
  `document.cookie` even if one existed.
- `SESSION_COOKIE_SAMESITE = "Lax"` — blocks the cookie being sent on most cross-site requests.
- `SESSION_COOKIE_SECURE` — enforced in production via the `SESSION_COOKIE_SECURE=1` env var
  (per `CLAUDE.md`'s deployment notes), so the cookie isn't sent over plain HTTP.
- CSRF tokens (`app/csrf.py`) prevent a *different* site from forging state-changing requests
  even if it could guess the session existed — the token itself lives in the same session, so
  this doesn't help against a fully stolen cookie, but it does close the more common CSRF
  vector.
- `reauth_required` limits what a stolen-but-still-valid session can do unattended: even with
  the cookie, an attacker cannot create/deactivate users or reset TOTP without the account's
  actual password (+ TOTP code, if the victim enabled it) within the last `REAUTH_WINDOW_MINUTES`.

**Residual risk:** as in §3.3, there's no session revocation mechanism — deactivating a user
(`set_user_active`) or resetting their TOTP doesn't invalidate a session that account already
holds; it only blocks *new* logins. A stolen session for a currently-active account remains
usable for non-`reauth_required` actions until it's abandoned or the browser session ends.
**Recommendation:** track a per-session or per-user "session version"/token in the DB and check
it on every `login_required` request, bumped on deactivation/password change/TOTP reset, so
those actions actually kill existing sessions. Not implemented — flagged for a future pass.

### 3.5 Backup file exposure

**Threat:** a backup — by construction, a single file containing the *entire* patient
database — is read by someone who shouldn't have it, whether at rest, in transit to an
off-site destination, or via the app's own download path.

**Current mitigations:** backups do not exist yet in this codebase as of this document; see
the accompanying `BACKUP.md` for the design being built immediately after this document,
which addresses this threat directly: encryption at rest with a key independent of `SECRET_KEY`,
admin-only + `reauth_required` download, and audit logging of every backup run and download.

**Recommendation carried into that design:** never serve a backup file to anyone but an
authenticated admin who has just stepped up via `reauth_required`; never log backup contents,
only metadata (size, timestamp, status); treat the encryption key as at least as sensitive as
`SECRET_KEY` and never commit it to the repo.

### 3.6 Uploaded clinical files

**Threat:** an uploaded "X-ray" is actually something else (a script, an executable, a
polyglot file) — either to attack the server directly, or to attack a browser that later opens
it — or an attacker guesses/enumerates a filename to view another patient's file without
authorization.

**Current mitigations:**
- Content is validated by **magic bytes only** — `app.validators.detect_upload_type` checks
  the first bytes against known JPEG/PNG/PDF signatures and rejects anything else, regardless
  of the client-supplied filename or `Content-Type` header (`app/routes/clinical_routes.py`).
- Files are stored outside the web root, under `DATA_DIR/clinical_uploads/`, renamed to a
  random UUID (`uuid.uuid4().hex`) — the original filename is kept only as a display label in
  the DB (`original_name`), never used as a path component, which also rules out path
  traversal via a crafted filename.
- Files are served only through `clinical.serve_attachment`, which is `@login_required` (any
  authenticated role — not further scoped, since attachments aren't in the financial-lockout
  list) and looks the file up by an opaque integer `attachment_id`, not by filename — an
  attacker without a valid session cannot reach a file at all, and a valid session can only
  reach files whose IDs it can enumerate (small integers, so *not* effectively unguessable —
  see residual risk below).
- Every upload and download is now audit-logged (`attachment_uploaded` / `attachment_downloaded`
  in `db.py`, exercised by `tests/test_audit_log.py`), so unauthorized access by a legitimate-but-
  misbehaving account is at least detectable after the fact.
- `MAX_CONTENT_LENGTH = 15 MB` bounds upload size, limiting resource-exhaustion risk.

**Residual risk:** `attachment_id` is a small sequential integer, so any logged-in user
(any role) can enumerate `/attachments/<id>/file` and view attachments belonging to any
patient's case, not just ones they've navigated to — there is no per-attachment ownership
check tying the request back to a case the user has actually opened. This is a real gap: it
relies entirely on "every logged-in role is trusted with all clinical attachments," which
matches §14's scope (financial lockout only) but is worth stating explicitly rather than
leaving implicit. **Recommendation:** low priority given the single-clinic, three-role trust
model, but if the patient portal (§14, future) is ever built, this must change — an external
patient session must never be able to enumerate another patient's attachment IDs.

## 4. Explicitly out of scope for this document

- Multi-tenancy / cross-clinic isolation — not applicable, single `DATA_DIR` per deployment.
- Google sign-in's own threat surface (token validation, issuer/audience/nonce checks) — deferred
  along with the feature itself; §14 already specifies the required checks in detail when it's
  built, and it explicitly cannot replace the local-password/TOTP baseline this document assumes.
- Physical security of the server / hosting provider's own security posture.
- Denial-of-service beyond the basic `MAX_CONTENT_LENGTH` bound and IP-based login rate limiting.

## 5. Summary of open recommendations

1. Idle/absolute session timeout (§3.3).
2. Session revocation on deactivation/password-change/TOTP-reset (§3.4).
3. Re-run financial role checks on any future export/PDF route (§3.2) — process note for
   whoever builds it, not code to write now.
4. Per-attachment ownership check, if/when an external (patient-facing) role is introduced (§3.6).

None of these block shipping the app to a single trusted clinic staff; they're ordered here by
where they'd matter most first (a shared front-desk PC is a near-term reality; an external
patient-facing role is not yet built).
