"""The only module that touches sqlite3 directly. All schema and CRUD live here."""
import json
import os
import sqlite3
from datetime import datetime, timedelta

from app import config as app_config
from app.validators import compute_age, now_iso

_PATIENT_COLUMNS = [
    "name", "date_of_birth", "age", "sex", "mobile", "email", "address",
    "medical_conditions_json", "medical_conditions_other",
    "is_pregnant", "is_nursing",
    "allergies_json", "allergies_other",
    "emergency_contact_name", "emergency_contact_relation", "emergency_contact_number",
    "dpdp_notice_accepted", "dpdp_notice_accepted_at",
    "comms_consent", "comms_consent_at",
    "guardian_name", "guardian_relation", "guardian_mobile",
]

_PATIENT_DEFAULTS = {
    "date_of_birth": "", "mobile": "", "email": "", "address": "",
    "medical_conditions_json": "[]", "medical_conditions_other": "",
    "is_pregnant": 0, "is_nursing": 0,
    "allergies_json": "[]", "allergies_other": "",
    "emergency_contact_name": "", "emergency_contact_relation": "", "emergency_contact_number": "",
    "dpdp_notice_accepted": 0, "dpdp_notice_accepted_at": "",
    "comms_consent": 0, "comms_consent_at": "",
    "guardian_name": "", "guardian_relation": "", "guardian_mobile": "",
}

_PATIENT_BOOL_COLUMNS = ("is_pregnant", "is_nursing", "dpdp_notice_accepted", "comms_consent")


def get_db():
    os.makedirs(os.path.dirname(app_config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(app_config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    # Two WSGI workers share this file in production — WAL + a busy timeout avoid "database is locked".
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _migrate_admin_roles(conn):
    """Additive migration: admin rows predate roles — every existing row is a full Admin."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(admin)")}
    if "role" not in columns:
        conn.execute("ALTER TABLE admin ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
    if "is_active" not in columns:
        conn.execute("ALTER TABLE admin ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "totp_secret" not in columns:
        conn.execute("ALTER TABLE admin ADD COLUMN totp_secret TEXT NOT NULL DEFAULT ''")
    if "totp_enabled" not in columns:
        conn.execute("ALTER TABLE admin ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0")
    if "totp_recovery_codes_json" not in columns:
        conn.execute("ALTER TABLE admin ADD COLUMN totp_recovery_codes_json TEXT NOT NULL DEFAULT '[]'")
    conn.commit()


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            security_question TEXT NOT NULL,
            security_answer_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            attempted_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date_of_birth TEXT NOT NULL DEFAULT '',
            age INTEGER,
            sex TEXT,
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
        );

        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            color TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS procedure_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active',
            procedures_json TEXT DEFAULT '[]',
            custom_procedure TEXT DEFAULT '',
            doctor_id INTEGER REFERENCES doctors(id),
            total_cost REAL DEFAULT 0,
            next_action_note TEXT DEFAULT '',
            follow_up_date TEXT DEFAULT '',
            created_at TEXT, updated_at TEXT,
            closed_at TEXT DEFAULT '',
            consent_recorded INTEGER DEFAULT 0,
            consent_recorded_at TEXT DEFAULT '',
            consent_notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS case_visit_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            patient_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prescriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            patient_id INTEGER NOT NULL,
            rx_details TEXT NOT NULL,
            prescribed_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS case_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_type TEXT NOT NULL DEFAULT 'Other',
            description TEXT NOT NULL DEFAULT '',
            uploaded_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lab_requisitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            patient_id INTEGER NOT NULL,
            lab_name TEXT NOT NULL DEFAULT '',
            work_description TEXT NOT NULL,
            sent_date TEXT NOT NULL,
            expected_return TEXT NOT NULL DEFAULT '',
            received_date TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Sent',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS referral_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            patient_id INTEGER NOT NULL,
            referral_date TEXT NOT NULL,
            referred_to TEXT NOT NULL,
            speciality TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            patient_id INTEGER NOT NULL,
            payment_date TEXT NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL DEFAULT '',
            reference TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cost_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            old_cost REAL NOT NULL,
            new_cost REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            changed_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            case_id INTEGER REFERENCES cases(id),
            doctor_id INTEGER REFERENCES doctors(id),
            appt_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT DEFAULT '',
            title TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Scheduled',
            created_at TEXT, updated_at TEXT,
            arrived_at TEXT NOT NULL DEFAULT '',
            seen_at TEXT NOT NULL DEFAULT '',
            is_recurring INTEGER NOT NULL DEFAULT 0,
            recur_interval TEXT NOT NULL DEFAULT '',
            recur_until TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_user_id INTEGER,
            role TEXT NOT NULL DEFAULT '',
            ts_utc TEXT NOT NULL,
            action TEXT NOT NULL,
            entity TEXT NOT NULL,
            entity_id INTEGER,
            correlation_id TEXT NOT NULL DEFAULT '',
            before_summary TEXT NOT NULL DEFAULT '',
            after_summary TEXT NOT NULL DEFAULT '',
            ip TEXT NOT NULL DEFAULT '',
            user_agent TEXT NOT NULL DEFAULT '',
            outcome TEXT NOT NULL DEFAULT 'success'
        );
        """
    )
    conn.commit()
    _migrate_admin_roles(conn)
    conn.close()


# ── Audit log ────────────────────────────────────────────────────────────
# _write_audit takes an already-open conn and does NOT commit/close — callers
# insert it into their own write's transaction so the audit row and the action
# it records live or die together. before/after summaries are field-level and
# redacted by the caller — never pass raw clinical note/prescription text here.

NO_ACTOR = {"user_id": None, "role": "", "ip": "", "user_agent": ""}


def _write_audit(conn, actor, action, entity, entity_id,
                  before_summary="", after_summary="", correlation_id="", outcome="success"):
    actor = actor or NO_ACTOR
    conn.execute(
        """INSERT INTO audit_log
           (actor_user_id, role, ts_utc, action, entity, entity_id,
            correlation_id, before_summary, after_summary, ip, user_agent, outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            actor.get("user_id"), actor.get("role") or "", now_iso(), action, entity, entity_id,
            correlation_id, before_summary, after_summary,
            actor.get("ip") or "", actor.get("user_agent") or "", outcome,
        ),
    )


def list_audit_log(limit=200):
    conn = get_db()
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def write_audit_now(actor, action, entity, entity_id, before_summary="", after_summary="", outcome="success"):
    """For actions with no other write to share a transaction with (e.g. a file download)."""
    conn = get_db()
    _write_audit(conn, actor, action, entity, entity_id, before_summary, after_summary, outcome=outcome)
    conn.commit()
    conn.close()


# ── Admin ────────────────────────────────────────────────────────────────

def get_admin():
    conn = get_db()
    row = conn.execute("SELECT * FROM admin ORDER BY id LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def create_admin(username, password_hash, security_question, security_answer_hash):
    now = now_iso()
    conn = get_db()
    conn.execute(
        """INSERT INTO admin (username, password_hash, security_question, security_answer_hash, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (username, password_hash, security_question, security_answer_hash, now, now),
    )
    conn.commit()
    conn.close()


def update_admin_password(password_hash):
    conn = get_db()
    admin = conn.execute("SELECT id FROM admin ORDER BY id LIMIT 1").fetchone()
    if admin:
        conn.execute(
            "UPDATE admin SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, now_iso(), admin["id"]),
        )
        conn.commit()
    conn.close()


# ── Multi-user accounts (admin / doctor / receptionist) ────────────────────
# The `admin` table now holds every login, not just the bootstrap admin —
# `role` distinguishes them. Kept the table name to avoid an unnecessary
# rename; every account (any role) lives here.

def get_user_by_username(username):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM admin WHERE username = ? AND is_active = 1", (username,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM admin WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def username_exists(username):
    conn = get_db()
    row = conn.execute("SELECT 1 FROM admin WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row is not None


def list_users():
    conn = get_db()
    rows = conn.execute("SELECT * FROM admin ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(username, password_hash, role, security_question, security_answer_hash, actor=None):
    now = now_iso()
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO admin
           (username, password_hash, security_question, security_answer_hash, role, is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (username, password_hash, security_question, security_answer_hash, role, now, now),
    )
    _write_audit(
        conn, actor, "user_created", "user", cur.lastrowid,
        after_summary=f"username={username}, role={role}",
    )
    conn.commit()
    conn.close()


def count_active_admins():
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM admin WHERE role = 'admin' AND is_active = 1"
    ).fetchone()
    conn.close()
    return row["c"]


def set_user_active(user_id, is_active, actor=None):
    conn = get_db()
    conn.execute(
        "UPDATE admin SET is_active = ?, updated_at = ? WHERE id = ?",
        (1 if is_active else 0, now_iso(), user_id),
    )
    _write_audit(
        conn, actor, "user_activated" if is_active else "user_deactivated", "user", user_id,
    )
    conn.commit()
    conn.close()


# ── TOTP 2FA ─────────────────────────────────────────────────────────────
# totp_secret is set (pending) as soon as setup starts but totp_enabled stays 0
# until the user proves they can generate a valid code with it — see
# app.routes.totp_routes. Recovery codes are stored hashed, never in plaintext.

def set_pending_totp_secret(user_id, secret):
    conn = get_db()
    conn.execute(
        "UPDATE admin SET totp_secret = ?, updated_at = ? WHERE id = ?",
        (secret, now_iso(), user_id),
    )
    conn.commit()
    conn.close()


def enable_totp(user_id, recovery_code_hashes, actor=None):
    conn = get_db()
    conn.execute(
        "UPDATE admin SET totp_enabled = 1, totp_recovery_codes_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(recovery_code_hashes), now_iso(), user_id),
    )
    _write_audit(conn, actor, "totp_enabled", "user", user_id)
    conn.commit()
    conn.close()


def reset_totp(user_id, actor=None):
    """Admin-controlled reset, or self-service disable — clears secret/codes, turns 2FA off."""
    conn = get_db()
    conn.execute(
        "UPDATE admin SET totp_secret = '', totp_enabled = 0, totp_recovery_codes_json = '[]', updated_at = ? WHERE id = ?",
        (now_iso(), user_id),
    )
    _write_audit(conn, actor, "totp_reset", "user", user_id)
    conn.commit()
    conn.close()


def consume_recovery_code(user_id, code_hash_matcher):
    """code_hash_matcher(stored_hash) -> bool. Removes the matched hash (one-time use). Returns True if consumed."""
    conn = get_db()
    row = conn.execute("SELECT totp_recovery_codes_json FROM admin WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return False
    hashes = json.loads(row["totp_recovery_codes_json"] or "[]")
    for h in hashes:
        if code_hash_matcher(h):
            hashes.remove(h)
            conn.execute(
                "UPDATE admin SET totp_recovery_codes_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(hashes), now_iso(), user_id),
            )
            conn.commit()
            conn.close()
            return True
    conn.close()
    return False


# ── Login rate limiting (DB-backed, survives restarts) ─────────────────────

def record_failed_login(ip):
    conn = get_db()
    conn.execute("INSERT INTO login_attempts (ip, attempted_at) VALUES (?, ?)", (ip, now_iso()))
    conn.commit()
    conn.close()


def count_recent_failed_logins(ip, minutes=15):
    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM login_attempts WHERE ip = ? AND attempted_at >= ?",
        (ip, cutoff),
    ).fetchone()
    conn.close()
    return row["c"]


def clear_failed_logins(ip):
    conn = get_db()
    conn.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
    conn.commit()
    conn.close()


# ── Doctors / Procedure Types (lookup data — admin CRUD UI is a later phase) ──

def add_doctor(name, color=""):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO doctors (name, color, is_active, created_at) VALUES (?, ?, 1, ?)",
        (name, color, now_iso()),
    )
    conn.commit()
    doctor_id = cur.lastrowid
    conn.close()
    return doctor_id


def list_doctors(active_only=True):
    conn = get_db()
    query = "SELECT * FROM doctors"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY name"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_doctor(doctor_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_procedure_type(name):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO procedure_types (name, is_active, created_at) VALUES (?, 1, ?)",
        (name, now_iso()),
    )
    conn.commit()
    procedure_type_id = cur.lastrowid
    conn.close()
    return procedure_type_id


def list_procedure_types(active_only=True):
    conn = get_db()
    query = "SELECT * FROM procedure_types"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY name"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Patients ─────────────────────────────────────────────────────────────

def add_patient(data):
    row = {col: data.get(col, _PATIENT_DEFAULTS.get(col)) for col in _PATIENT_COLUMNS}
    for col in _PATIENT_BOOL_COLUMNS:
        row[col] = int(bool(row[col]))
    now = now_iso()
    row["created_at"] = now
    row["updated_at"] = now
    row["is_historic_import"] = 0

    columns = ", ".join(row.keys())
    placeholders = ", ".join(f":{k}" for k in row.keys())
    conn = get_db()
    cur = conn.execute(f"INSERT INTO patients ({columns}) VALUES ({placeholders})", row)
    conn.commit()
    patient_id = cur.lastrowid
    conn.close()
    return patient_id


def update_patient(patient_id, data, actor=None):
    row = {col: data[col] for col in _PATIENT_COLUMNS if col in data}
    for col in _PATIENT_BOOL_COLUMNS:
        if col in row:
            row[col] = int(bool(row[col]))
    changed_fields = sorted(row.keys())
    row["updated_at"] = now_iso()
    row["id"] = patient_id

    set_clause = ", ".join(f"{k} = :{k}" for k in row if k != "id")
    conn = get_db()
    conn.execute(f"UPDATE patients SET {set_clause} WHERE id = :id", row)
    _write_audit(
        conn, actor, "patient_updated", "patient", patient_id,
        after_summary=f"fields changed: {', '.join(changed_fields)}",
    )
    conn.commit()
    conn.close()


def get_patient(patient_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    conn.close()
    if not row:
        return None
    patient = dict(row)
    patient["computed_age"] = compute_age(patient.get("date_of_birth"))
    return patient


def add_case(data):
    row = {col: data.get(col, _CASE_DEFAULTS.get(col)) for col in _CASE_CREATE_COLUMNS}
    row["patient_id"] = data["patient_id"]
    row["status"] = "Active"
    now = now_iso()
    row["created_at"] = now
    row["updated_at"] = now
    row["closed_at"] = ""
    row["next_action_note"] = ""
    row["follow_up_date"] = ""
    row["consent_recorded"] = 0
    row["consent_recorded_at"] = ""
    row["consent_notes"] = ""

    columns = ", ".join(row.keys())
    placeholders = ", ".join(f":{k}" for k in row.keys())
    conn = get_db()
    cur = conn.execute(f"INSERT INTO cases ({columns}) VALUES ({placeholders})", row)
    conn.commit()
    case_id = cur.lastrowid
    conn.close()
    return case_id


def update_case(case_id, data):
    row = {col: data[col] for col in _CASE_EDIT_COLUMNS if col in data}
    row["updated_at"] = now_iso()
    row["id"] = case_id

    set_clause = ", ".join(f"{k} = :{k}" for k in row if k != "id")
    conn = get_db()
    conn.execute(f"UPDATE cases SET {set_clause} WHERE id = :id", row)
    conn.commit()
    conn.close()


def close_case(case_id, actor=None):
    now = now_iso()
    conn = get_db()
    conn.execute(
        "UPDATE cases SET status = 'Closed', closed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, case_id),
    )
    _write_audit(
        conn, actor, "case_status_changed", "case", case_id,
        before_summary="status=Active", after_summary="status=Closed",
    )
    conn.commit()
    conn.close()


def get_case(case_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_cases_for_patient(patient_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM cases WHERE patient_id = ?
           ORDER BY CASE WHEN status = 'Active' THEN 0 ELSE 1 END, updated_at DESC""",
        (patient_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


_CASE_CREATE_COLUMNS = ["title", "procedures_json", "custom_procedure", "doctor_id", "total_cost"]
_CASE_EDIT_COLUMNS = ["title", "procedures_json", "custom_procedure", "doctor_id"]
_CASE_DEFAULTS = {"procedures_json": "[]", "custom_procedure": "", "doctor_id": None, "total_cost": 0}


# ── Visit Notes (append-only clinical record — no edit/delete) ─────────────

def add_visit_note(case_id, patient_id, note, visit_date, actor=None):
    conn = get_db()
    conn.execute(
        """INSERT INTO case_visit_notes (case_id, patient_id, note, visit_date, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (case_id, patient_id, note, visit_date, now_iso()),
    )
    _write_audit(
        conn, actor, "visit_note_added", "case", case_id,
        after_summary=f"visit note added ({len(note)} chars), visit_date={visit_date}",
    )
    conn.commit()
    conn.close()


def list_visit_notes_for_case(case_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM case_visit_notes WHERE case_id = ? ORDER BY visit_date DESC, id DESC",
        (case_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Prescriptions (append-only clinical record — no edit/delete) ───────────

def add_prescription(case_id, patient_id, rx_details, prescribed_date, actor=None):
    conn = get_db()
    conn.execute(
        """INSERT INTO prescriptions (case_id, patient_id, rx_details, prescribed_date, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (case_id, patient_id, rx_details, prescribed_date, now_iso()),
    )
    _write_audit(
        conn, actor, "prescription_added", "case", case_id,
        after_summary=f"prescription added ({len(rx_details)} chars), prescribed_date={prescribed_date}",
    )
    conn.commit()
    conn.close()


def list_prescriptions_for_case(case_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM prescriptions WHERE case_id = ? ORDER BY prescribed_date DESC, id DESC",
        (case_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Clinical Attachments ────────────────────────────────────────────────

def add_attachment(case_id, filename, original_name, file_type, description, actor=None):
    now = now_iso()
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO case_attachments
               (case_id, filename, original_name, file_type, description, uploaded_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (case_id, filename, original_name, file_type, description, now, now),
    )
    attachment_id = cur.lastrowid
    _write_audit(
        conn, actor, "attachment_uploaded", "case_attachment", attachment_id,
        after_summary=f"file_type={file_type}",
    )
    conn.commit()
    conn.close()
    return attachment_id


def list_attachments_for_case(case_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM case_attachments WHERE case_id = ? ORDER BY uploaded_at DESC, id DESC",
        (case_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_attachment(attachment_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM case_attachments WHERE id = ?", (attachment_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_attachment(attachment_id):
    """Deletes the DB row and returns the on-disk filename so the caller can remove the file."""
    conn = get_db()
    row = conn.execute("SELECT filename FROM case_attachments WHERE id = ?", (attachment_id,)).fetchone()
    conn.execute("DELETE FROM case_attachments WHERE id = ?", (attachment_id,))
    conn.commit()
    conn.close()
    return row["filename"] if row else None


# ── Lab Requisitions ─────────────────────────────────────────────────────

def add_lab_req(case_id, patient_id, lab_name, work_description, sent_date, expected_return, notes):
    conn = get_db()
    conn.execute(
        """INSERT INTO lab_requisitions
               (case_id, patient_id, lab_name, work_description, sent_date, expected_return,
                received_date, status, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, '', 'Sent', ?, ?)""",
        (case_id, patient_id, lab_name, work_description, sent_date, expected_return, notes, now_iso()),
    )
    conn.commit()
    conn.close()


def list_lab_reqs_for_case(case_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM lab_requisitions WHERE case_id = ? ORDER BY sent_date DESC, id DESC",
        (case_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lab_req(req_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM lab_requisitions WHERE id = ?", (req_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_lab_req(req_id, status, received_date, notes):
    conn = get_db()
    conn.execute(
        "UPDATE lab_requisitions SET status = ?, received_date = ?, notes = ? WHERE id = ?",
        (status, received_date, notes, req_id),
    )
    conn.commit()
    conn.close()


def delete_lab_req(req_id):
    conn = get_db()
    conn.execute("DELETE FROM lab_requisitions WHERE id = ?", (req_id,))
    conn.commit()
    conn.close()


# ── Referral Notes ───────────────────────────────────────────────────────

def add_referral(case_id, patient_id, referral_date, referred_to, speciality, reason, notes):
    conn = get_db()
    conn.execute(
        """INSERT INTO referral_notes
               (case_id, patient_id, referral_date, referred_to, speciality, reason, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (case_id, patient_id, referral_date, referred_to, speciality, reason, notes, now_iso()),
    )
    conn.commit()
    conn.close()


def list_referrals_for_case(case_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM referral_notes WHERE case_id = ? ORDER BY referral_date DESC, id DESC",
        (case_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_referral(ref_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM referral_notes WHERE id = ?", (ref_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_referral(ref_id):
    conn = get_db()
    conn.execute("DELETE FROM referral_notes WHERE id = ?", (ref_id,))
    conn.commit()
    conn.close()


# ── Payments (append-only financial ledger — no edit/delete) ───────────────

def add_payment(case_id, patient_id, payment_date, amount, method, reference, notes, actor=None):
    conn = get_db()
    conn.execute(
        """INSERT INTO payments (case_id, patient_id, payment_date, amount, method, reference, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (case_id, patient_id, payment_date, amount, method, reference, notes, now_iso()),
    )
    _write_audit(
        conn, actor, "payment_added", "case", case_id,
        after_summary=f"amount={amount}, method={method or '—'}",
    )
    conn.commit()
    conn.close()


def list_payments_for_case(case_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM payments WHERE case_id = ? ORDER BY payment_date DESC, id DESC",
        (case_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_case_balance(case_id):
    """total_cost - SUM(payments) — computed live, never stored."""
    conn = get_db()
    case_row = conn.execute("SELECT total_cost FROM cases WHERE id = ?", (case_id,)).fetchone()
    paid_row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS paid FROM payments WHERE case_id = ?", (case_id,)
    ).fetchone()
    conn.close()
    if not case_row:
        return None
    return case_row["total_cost"] - paid_row["paid"]


# ── Cost Revisions (append-only — total_cost only ever changes via this) ───

def update_case_cost(case_id, new_cost, reason, actor=None):
    conn = get_db()
    case_row = conn.execute("SELECT total_cost FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case_row:
        conn.close()
        return
    old_cost = case_row["total_cost"]
    now = now_iso()
    if old_cost != new_cost:
        conn.execute(
            """INSERT INTO cost_revisions (case_id, old_cost, new_cost, reason, changed_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (case_id, old_cost, new_cost, reason, now, now),
        )
        _write_audit(
            conn, actor, "cost_revised", "case", case_id,
            before_summary=f"total_cost={old_cost}", after_summary=f"total_cost={new_cost}, reason={reason}",
        )
    conn.execute("UPDATE cases SET total_cost = ?, updated_at = ? WHERE id = ?", (new_cost, now, case_id))
    conn.commit()
    conn.close()


def list_cost_revisions_for_case(case_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM cost_revisions WHERE case_id = ? ORDER BY changed_at DESC, id DESC",
        (case_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Follow-up & Consent (both live directly on the case row) ───────────────

def update_case_followup(case_id, follow_up_date, next_action_note):
    """Call with ("", "") to clear a follow-up."""
    conn = get_db()
    conn.execute(
        "UPDATE cases SET follow_up_date = ?, next_action_note = ?, updated_at = ? WHERE id = ?",
        (follow_up_date, next_action_note, now_iso(), case_id),
    )
    conn.commit()
    conn.close()


def record_case_consent(case_id, notes, actor=None):
    conn = get_db()
    conn.execute(
        """UPDATE cases SET consent_recorded = 1, consent_recorded_at = ?, consent_notes = ?, updated_at = ?
           WHERE id = ?""",
        (now_iso(), notes, now_iso(), case_id),
    )
    _write_audit(conn, actor, "consent_recorded", "case", case_id, after_summary="consent_recorded=1")
    conn.commit()
    conn.close()


def list_patients(search="", limit=200):
    conn = get_db()
    if search:
        like = f"%{search}%"
        rows = conn.execute(
            """SELECT * FROM patients
               WHERE name LIKE ? OR mobile LIKE ? OR email LIKE ? OR address LIKE ?
               ORDER BY name LIMIT ?""",
            (like, like, like, like, limit),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM patients ORDER BY name LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Appointments ─────────────────────────────────────────────────────────

def add_appointment(patient_id, case_id, doctor_id, appt_date, start_time, end_time, title, notes, status):
    conn = get_db()
    now = now_iso()
    cur = conn.execute(
        """INSERT INTO appointments
               (patient_id, case_id, doctor_id, appt_date, start_time, end_time, title, notes, status,
                created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, case_id, doctor_id, appt_date, start_time, end_time, title, notes, status, now, now),
    )
    conn.commit()
    appt_id = cur.lastrowid
    conn.close()
    return appt_id


def update_appointment(appt_id, patient_id, case_id, doctor_id, appt_date, start_time, end_time, title, notes, status):
    conn = get_db()
    conn.execute(
        """UPDATE appointments
           SET patient_id = ?, case_id = ?, doctor_id = ?, appt_date = ?, start_time = ?, end_time = ?,
               title = ?, notes = ?, status = ?, updated_at = ?
           WHERE id = ?""",
        (patient_id, case_id, doctor_id, appt_date, start_time, end_time, title, notes, status, now_iso(), appt_id),
    )
    conn.commit()
    conn.close()


def get_appointment(appt_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_appointment(appt_id):
    conn = get_db()
    conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
    conn.commit()
    conn.close()


def list_appointments_for_patient(patient_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT a.*, d.name AS doctor_name, d.color AS doctor_color
           FROM appointments a LEFT JOIN doctors d ON d.id = a.doctor_id
           WHERE a.patient_id = ?
           ORDER BY a.appt_date DESC, a.start_time DESC""",
        (patient_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_appointments_for_month(year, month):
    conn = get_db()
    month_str = f"{year:04d}-{month:02d}"
    rows = conn.execute(
        """SELECT a.*, p.name AS patient_name, d.name AS doctor_name, d.color AS doctor_color
           FROM appointments a
           JOIN patients p ON p.id = a.patient_id
           LEFT JOIN doctors d ON d.id = a.doctor_id
           WHERE substr(a.appt_date, 1, 7) = ?
           ORDER BY a.appt_date, a.start_time""",
        (month_str,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
