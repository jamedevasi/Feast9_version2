"""The only module that touches sqlite3 directly. All schema and CRUD live here."""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta

from app import config as app_config
from app.constants import MAX_RECURRING_OCCURRENCES
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


def _migrate_patients_dpdp(conn):
    """Additive migration for DPDP Phase 2 erasure support."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(patients)")}
    if "is_anonymized" not in columns:
        conn.execute("ALTER TABLE patients ADD COLUMN is_anonymized INTEGER NOT NULL DEFAULT 0")
    if "anonymized_at" not in columns:
        conn.execute("ALTER TABLE patients ADD COLUMN anonymized_at TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _migrate_appointments_recurring(conn):
    """Additive migration: groups a recurring series' generated rows together."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(appointments)")}
    if "series_id" not in columns:
        conn.execute("ALTER TABLE appointments ADD COLUMN series_id INTEGER REFERENCES appointments(id)")
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

        CREATE TABLE IF NOT EXISTS backup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running',
            file_path TEXT NOT NULL DEFAULT '',
            file_size INTEGER NOT NULL DEFAULT 0,
            offsite_status TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS data_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            request_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            description TEXT NOT NULL DEFAULT '',
            resolution_note TEXT NOT NULL DEFAULT '',
            requested_at TEXT NOT NULL,
            deadline_at TEXT NOT NULL,
            resolved_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dental_chart_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            case_id INTEGER REFERENCES cases(id),
            tooth_id TEXT NOT NULL,
            dentition TEXT NOT NULL,
            surface TEXT NOT NULL DEFAULT 'Whole Tooth',
            finding TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Existing',
            notes TEXT NOT NULL DEFAULT '',
            recorded_by INTEGER,
            recorded_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TEXT
        );
        """
    )
    conn.commit()
    _migrate_admin_roles(conn)
    _migrate_patients_dpdp(conn)
    _migrate_appointments_recurring(conn)
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


# ── Settings (key/value store — §5.12 Login Screen Customisation) ─────────

def get_setting(key, default=""):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value, actor=None):
    conn = get_db()
    conn.execute(
        """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (key, value, now_iso()),
    )
    _write_audit(conn, actor, "setting_changed", "setting", None, after_summary=f"key={key}")
    conn.commit()
    conn.close()


# ── Backup log ───────────────────────────────────────────────────────────

def start_backup_log():
    conn = get_db()
    cur = conn.execute("INSERT INTO backup_log (started_at, status) VALUES (?, 'running')", (now_iso(),))
    conn.commit()
    backup_id = cur.lastrowid
    conn.close()
    return backup_id


def finish_backup_log(backup_id, status, file_path="", file_size=0, offsite_status="", error_message=""):
    conn = get_db()
    conn.execute(
        """UPDATE backup_log SET finished_at = ?, status = ?, file_path = ?, file_size = ?,
           offsite_status = ?, error_message = ? WHERE id = ?""",
        (now_iso(), status, file_path, file_size, offsite_status, error_message, backup_id),
    )
    conn.commit()
    conn.close()


def list_backup_log(limit=100):
    conn = get_db()
    rows = conn.execute("SELECT * FROM backup_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_backup_log(backup_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM backup_log WHERE id = ?", (backup_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def latest_backup_log():
    conn = get_db()
    row = conn.execute("SELECT * FROM backup_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


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


# ── Doctors / Procedure Types (lookup data — admin CRUD UI, §5.13) ─────────
# Deactivating either never deletes the row — cases already reference doctor_id, and
# procedures_json already stores procedure-type *names* by value, so history is
# unaffected either way; list_doctors()/list_procedure_types() default to active_only,
# so a deactivated one simply stops being offered on new cases.

def add_doctor(name, color="", actor=None):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO doctors (name, color, is_active, created_at) VALUES (?, ?, 1, ?)",
        (name, color, now_iso()),
    )
    _write_audit(conn, actor, "doctor_created", "doctor", cur.lastrowid, after_summary=f"name={name}")
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


def set_doctor_active(doctor_id, is_active, actor=None):
    conn = get_db()
    conn.execute("UPDATE doctors SET is_active = ? WHERE id = ?", (1 if is_active else 0, doctor_id))
    _write_audit(conn, actor, "doctor_activated" if is_active else "doctor_deactivated", "doctor", doctor_id)
    conn.commit()
    conn.close()


def add_procedure_type(name, actor=None):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO procedure_types (name, is_active, created_at) VALUES (?, 1, ?)",
        (name, now_iso()),
    )
    _write_audit(
        conn, actor, "procedure_type_created", "procedure_type", cur.lastrowid, after_summary=f"name={name}"
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


def get_procedure_type(procedure_type_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM procedure_types WHERE id = ?", (procedure_type_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_procedure_type_active(procedure_type_id, is_active, actor=None):
    conn = get_db()
    conn.execute(
        "UPDATE procedure_types SET is_active = ? WHERE id = ?", (1 if is_active else 0, procedure_type_id)
    )
    _write_audit(
        conn, actor, "procedure_type_activated" if is_active else "procedure_type_deactivated",
        "procedure_type", procedure_type_id,
    )
    conn.commit()
    conn.close()


# ── Patients ─────────────────────────────────────────────────────────────

def _insert_patient_row(conn, data, is_historic_import, now):
    row = {col: data.get(col, _PATIENT_DEFAULTS.get(col)) for col in _PATIENT_COLUMNS}
    for col in _PATIENT_BOOL_COLUMNS:
        row[col] = int(bool(row[col]))
    row["created_at"] = now
    row["updated_at"] = now
    row["is_historic_import"] = 1 if is_historic_import else 0

    columns = ", ".join(row.keys())
    placeholders = ", ".join(f":{k}" for k in row.keys())
    cur = conn.execute(f"INSERT INTO patients ({columns}) VALUES ({placeholders})", row)
    return cur.lastrowid


def add_patient(data):
    conn = get_db()
    patient_id = _insert_patient_row(conn, data, is_historic_import=False, now=now_iso())
    conn.commit()
    conn.close()
    return patient_id


def bulk_add_patients(rows, actor=None):
    """Insert many validated patient dicts in a single transaction — the Excel bulk
    import (up to MAX_IMPORT_ROWS per row, feast9_v2_agents.md's 'Bulk 8,000-row xlsx
    import'), where one connect/commit per row would be needlessly slow for a batch
    this size. Every row is marked is_historic_import=1."""
    conn = get_db()
    now = now_iso()
    ids = [_insert_patient_row(conn, data, is_historic_import=True, now=now) for data in rows]
    _write_audit(
        conn, actor, "patients_bulk_imported", "patient", None,
        after_summary=f"{len(ids)} patients imported",
    )
    conn.commit()
    conn.close()
    return ids


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


def list_visit_notes_for_patient(patient_id):
    """All visit notes across every case for a patient — used by the DPDP right-to-access
    export (feast9_v2_agents.md §10 generate_data_access_pdf), which must hand the patient
    their own clinical text in full, unlike the audit log's field-level redaction."""
    conn = get_db()
    rows = conn.execute(
        """SELECT vn.*, c.title AS case_title FROM case_visit_notes vn
           JOIN cases c ON c.id = vn.case_id
           WHERE vn.patient_id = ? ORDER BY vn.visit_date DESC, vn.id DESC""",
        (patient_id,),
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


def get_prescription(rx_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM prescriptions WHERE id = ?", (rx_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_prescriptions_for_patient(patient_id):
    """All prescriptions across every case for a patient — feast9_v2_agents.md §14 'Prescription history'."""
    conn = get_db()
    rows = conn.execute(
        """SELECT rx.*, c.title AS case_title FROM prescriptions rx
           JOIN cases c ON c.id = rx.case_id
           WHERE rx.patient_id = ? ORDER BY rx.prescribed_date DESC, rx.id DESC""",
        (patient_id,),
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


def delete_attachment(attachment_id, actor=None, reason=""):
    """Deletes the DB row and returns the on-disk filename so the caller can remove the file."""
    conn = get_db()
    row = conn.execute(
        "SELECT filename, case_id, file_type FROM case_attachments WHERE id = ?", (attachment_id,)
    ).fetchone()
    conn.execute("DELETE FROM case_attachments WHERE id = ?", (attachment_id,))
    if row:
        summary = f"file_type={row['file_type']}"
        if reason:
            summary += f", reason={reason}"
        _write_audit(conn, actor, "attachment_deleted", "case_attachment", attachment_id, before_summary=summary)
    conn.commit()
    conn.close()
    return row["filename"] if row else None


def clear_case_clinical_documents(case_id, reason, actor=None):
    """Deletes every attachment for a case in one go (the practitioner's retention/erasure
    choice per case — e.g. some cases must keep lab reports/X-rays after closing, others
    don't). Returns the on-disk filenames removed so the caller can delete the files."""
    conn = get_db()
    rows = conn.execute(
        "SELECT filename, file_type FROM case_attachments WHERE case_id = ?", (case_id,)
    ).fetchall()
    conn.execute("DELETE FROM case_attachments WHERE case_id = ?", (case_id,))
    type_counts = {}
    for r in rows:
        type_counts[r["file_type"]] = type_counts.get(r["file_type"], 0) + 1
    counts_summary = ", ".join(f"{t}:{c}" for t, c in sorted(type_counts.items()))
    _write_audit(
        conn, actor, "clinical_documents_cleared", "case", case_id,
        before_summary=f"{len(rows)} document(s) ({counts_summary})" if rows else "0 documents",
        after_summary=f"reason={reason}",
    )
    conn.commit()
    conn.close()
    return [r["filename"] for r in rows]


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


# New requirement, added by the user 2026-09-17 — not in feast9_v2_agents.md's original
# §5.5: a lab requisition still "open" (not yet Received) is worth flagging if its
# patient is due back soon, so results (or their absence) aren't a surprise at the visit.

def get_next_scheduled_appointment_within(patient_id, days=3):
    """Earliest Scheduled appointment date for this patient in the next `days` days,
    or '' if none — used to highlight open lab requisitions on a single case page."""
    conn = get_db()
    today = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=days)).isoformat()
    row = conn.execute(
        """SELECT MIN(appt_date) AS d FROM appointments
           WHERE patient_id = ? AND status = 'Scheduled' AND appt_date BETWEEN ? AND ?""",
        (patient_id, today, cutoff),
    ).fetchone()
    conn.close()
    return row["d"] or ""


def get_open_lab_reqs_for_upcoming_appointments(days=3):
    """Open (Sent/Delayed) lab requisitions whose patient has a Scheduled appointment
    in the next `days` days — the dashboard-wide version of the same check, across
    every patient rather than one case."""
    conn = get_db()
    today = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT lr.id AS lab_req_id, lr.case_id, lr.patient_id, lr.lab_name,
                  lr.work_description, lr.status, lr.sent_date, lr.expected_return,
                  p.name AS patient_name, MIN(a.appt_date) AS next_appt_date
           FROM lab_requisitions lr
           JOIN patients p ON p.id = lr.patient_id
           JOIN appointments a ON a.patient_id = lr.patient_id
           WHERE lr.status != 'Received'
             AND a.status = 'Scheduled'
             AND a.appt_date BETWEEN ? AND ?
           GROUP BY lr.id
           ORDER BY next_appt_date, lr.sent_date""",
        (today, cutoff),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


# ── DPDP Phase 2 — data-rights requests (feast9_v2_agents.md §5.11) ────────
# Four types: Access | Correction | Erasure | Withdraw Consent. Erasure soft-anonymises
# PII on the patient row and preserves every clinical/financial record attached to it —
# it is never a hard delete of the patient or their cases.

_ANONYMIZE_FIELDS = {
    "mobile": "", "email": "", "address": "", "date_of_birth": "",
    "emergency_contact_name": "", "emergency_contact_relation": "", "emergency_contact_number": "",
    "guardian_name": "", "guardian_relation": "", "guardian_mobile": "",
}


def create_data_request(patient_id, request_type, description, actor=None):
    now = now_iso()
    deadline = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO data_requests
           (patient_id, request_type, status, description, requested_at, deadline_at, created_at)
           VALUES (?, ?, 'Pending', ?, ?, ?, ?)""",
        (patient_id, request_type, description, now, deadline, now),
    )
    request_id = cur.lastrowid
    _write_audit(
        conn, actor, "dpdp_request_created", "data_request", request_id,
        after_summary=f"type={request_type}",
    )
    conn.commit()
    conn.close()
    return request_id


def get_data_request(request_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM data_requests WHERE id = ?", (request_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_data_requests(status=None):
    conn = get_db()
    query = "SELECT dr.*, p.name AS patient_name FROM data_requests dr JOIN patients p ON p.id = dr.patient_id"
    if status:
        rows = conn.execute(f"{query} WHERE dr.status = ? ORDER BY dr.deadline_at", (status,)).fetchall()
    else:
        rows = conn.execute(f"{query} ORDER BY dr.deadline_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_data_requests_for_patient(patient_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM data_requests WHERE patient_id = ? ORDER BY requested_at DESC", (patient_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_pending_data_requests():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM data_requests WHERE status = 'Pending'").fetchone()
    conn.close()
    return row["c"]


def resolve_data_request(request_id, new_status, resolution_note, confirm_name="", actor=None):
    """Updates a request's status and, when completing it, applies the request type's
    real-world effect in the SAME transaction: Erasure soft-anonymises the patient (requires
    confirm_name to exactly match the patient's current name — the spec's confirmation
    safeguard for an irreversible action); Withdraw Consent clears comms consent. Raises
    ValueError (no writes made) if an Erasure completion's confirm_name doesn't match."""
    conn = get_db()
    request = conn.execute("SELECT * FROM data_requests WHERE id = ?", (request_id,)).fetchone()
    if not request:
        conn.close()
        raise ValueError("No such data request.")

    if new_status == "Completed" and request["request_type"] == "Erasure":
        patient = conn.execute("SELECT name FROM patients WHERE id = ?", (request["patient_id"],)).fetchone()
        if not patient or confirm_name.strip() != patient["name"]:
            conn.close()
            raise ValueError("Typed name does not match the patient's name — erasure not performed.")

    now = now_iso()
    resolved_at = now if new_status in ("Completed", "Rejected") else ""
    conn.execute(
        "UPDATE data_requests SET status = ?, resolution_note = ?, resolved_at = ? WHERE id = ?",
        (new_status, resolution_note, resolved_at, request_id),
    )
    _write_audit(
        conn, actor, "dpdp_request_status_changed", "data_request", request_id,
        before_summary=f"status={request['status']}", after_summary=f"status={new_status}",
    )

    if new_status == "Completed":
        if request["request_type"] == "Erasure":
            set_clause = ", ".join(f"{k} = ?" for k in _ANONYMIZE_FIELDS)
            conn.execute(
                f"""UPDATE patients SET {set_clause}, name = ?, is_anonymized = 1,
                    anonymized_at = ?, comms_consent = 0, updated_at = ? WHERE id = ?""",
                (*_ANONYMIZE_FIELDS.values(), f"Erased Patient #{request['patient_id']}", now, now, request["patient_id"]),
            )
            _write_audit(conn, actor, "patient_anonymized", "patient", request["patient_id"])
        elif request["request_type"] == "Withdraw Consent":
            conn.execute(
                "UPDATE patients SET comms_consent = 0, comms_consent_at = '', updated_at = ? WHERE id = ?",
                (now, request["patient_id"]),
            )
            _write_audit(conn, actor, "comms_consent_withdrawn", "patient", request["patient_id"])

    conn.commit()
    conn.close()


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


# ── Recurring appointments (§14 item) ───────────────────────────────────────
# A bounded set of real appointment rows is generated up front — not a virtual/computed
# series — so per-occurrence no-show handling, editing one occurrence, and "exceptions"
# (delete or edit a single generated row) all fall out of the normal appointment machinery.

def _add_months(d, n):
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def _step_date(d, interval):
    if interval == "Weekly":
        return d + timedelta(days=7)
    if interval == "Biweekly":
        return d + timedelta(days=14)
    return _add_months(d, 1)  # Monthly


def _times_overlap(start_a, end_a, start_b, end_b):
    end_a = end_a or start_a
    end_b = end_b or start_b
    return start_a < end_b and start_b < end_a


def _find_conflicts(conn, doctor_id, appt_date, start_time, end_time):
    rows = conn.execute(
        """SELECT id, start_time, end_time FROM appointments
           WHERE doctor_id = ? AND appt_date = ? AND status != 'Cancelled'""",
        (doctor_id, appt_date),
    ).fetchall()
    return [r["id"] for r in rows if _times_overlap(start_time, end_time, r["start_time"], r["end_time"])]


def add_recurring_appointments(patient_id, case_id, doctor_id, start_date, start_time, end_time,
                                title, notes, status, interval, until_date, skip_sundays=True):
    """Generates occurrences from start_date through until_date (inclusive), stepping by
    interval, capped at MAX_RECURRING_OCCURRENCES. Returns (created_ids, conflict_warnings) —
    conflict_warnings lists dates where another appointment already exists for that doctor at
    an overlapping time; the occurrence is still created (a warning, not a hard block)."""
    dates = []
    d = date.fromisoformat(start_date)
    until = date.fromisoformat(until_date)
    while d <= until and len(dates) < MAX_RECURRING_OCCURRENCES:
        if not (skip_sundays and d.weekday() == 6):
            dates.append(d)
        d = _step_date(d, interval)

    conn = get_db()
    now = now_iso()
    created_ids = []
    conflict_warnings = []
    series_id = None
    for occurrence_date in dates:
        iso_date = occurrence_date.isoformat()
        conflicts = _find_conflicts(conn, doctor_id, iso_date, start_time, end_time)
        if conflicts:
            conflict_warnings.append(f"{iso_date} {start_time} already has another appointment for this doctor")

        cur = conn.execute(
            """INSERT INTO appointments
                   (patient_id, case_id, doctor_id, appt_date, start_time, end_time, title, notes, status,
                    created_at, updated_at, is_recurring, recur_interval, recur_until, series_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (patient_id, case_id, doctor_id, iso_date, start_time, end_time, title, notes, status,
             now, now, interval, until_date, series_id),
        )
        new_id = cur.lastrowid
        created_ids.append(new_id)
        if series_id is None:
            series_id = new_id
            conn.execute("UPDATE appointments SET series_id = ? WHERE id = ?", (series_id, new_id))

    conn.commit()
    conn.close()
    return created_ids, conflict_warnings


def list_appointments_for_series(series_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM appointments WHERE series_id = ? ORDER BY appt_date, start_time", (series_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_appointment_series(series_id, doctor_id, start_time, end_time, title, notes):
    """Applies shared fields to every not-yet-resolved occurrence in a series — deliberately
    excludes appt_date and status, which stay per-occurrence."""
    conn = get_db()
    conn.execute(
        """UPDATE appointments SET doctor_id = ?, start_time = ?, end_time = ?, title = ?, notes = ?,
           updated_at = ? WHERE series_id = ? AND status = 'Scheduled'""",
        (doctor_id, start_time, end_time, title, notes, now_iso(), series_id),
    )
    conn.commit()
    conn.close()


def cancel_appointment_series(series_id):
    """Cancels every not-yet-resolved occurrence in a series — leaves Completed/No-show/
    already-Cancelled history untouched."""
    conn = get_db()
    conn.execute(
        "UPDATE appointments SET status = 'Cancelled', updated_at = ? WHERE series_id = ? AND status = 'Scheduled'",
        (now_iso(), series_id),
    )
    conn.commit()
    conn.close()


# ── Dashboard widgets ────────────────────────────────────────────────────────

def get_followup_alerts():
    """Merged follow-up table for the dashboard — (overdue_list, upcoming_list).
    overdue:  follow_up_date < today
    upcoming: today <= follow_up_date <= today + 3 days
    Only cases still Active are surfaced — a closed case's stale follow-up date
    (left over from before it was closed) shouldn't nag the dashboard."""
    conn = get_db()
    rows = conn.execute(
        """SELECT c.id AS case_id, c.patient_id, c.title AS case_title,
                  c.follow_up_date, c.next_action_note, p.name AS patient_name
           FROM cases c JOIN patients p ON p.id = c.patient_id
           WHERE c.follow_up_date != '' AND c.status = 'Active'
           ORDER BY c.follow_up_date""",
    ).fetchall()
    conn.close()
    today_str = date.today().isoformat()
    upcoming_cutoff = (date.today() + timedelta(days=3)).isoformat()
    overdue, upcoming = [], []
    for r in rows:
        row = dict(r)
        if row["follow_up_date"] < today_str:
            overdue.append(row)
        elif row["follow_up_date"] <= upcoming_cutoff:
            upcoming.append(row)
    return overdue, upcoming


def get_active_cases_count():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS n FROM cases WHERE status = 'Active'").fetchone()
    conn.close()
    return row["n"]


def get_outstanding_balance():
    """Total_cost minus payments, summed across every case — financial data, redact
    entirely (not just hide) from receptionist sessions at the route level."""
    conn = get_db()
    row = conn.execute(
        """SELECT COALESCE(SUM(c.total_cost), 0) AS total_cost,
                  COALESCE((SELECT SUM(amount) FROM payments), 0) AS total_paid
           FROM cases c"""
    ).fetchone()
    conn.close()
    return row["total_cost"] - row["total_paid"]


def get_todays_appointments():
    """Today's Appointments widget — status badges must key off appointment.status
    only (never arrived_at/seen_at, which are unused leftovers)."""
    conn = get_db()
    today_str = date.today().isoformat()
    rows = conn.execute(
        """SELECT a.*, p.name AS patient_name, d.name AS doctor_name, d.color AS doctor_color
           FROM appointments a
           JOIN patients p ON p.id = a.patient_id
           LEFT JOIN doctors d ON d.id = a.doctor_id
           WHERE a.appt_date = ?
           ORDER BY a.start_time""",
        (today_str,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Reports (§5.9) ───────────────────────────────────────────────────────────
# created_at/closed_at are "YYYY-MM-DD HH:MM:SS" — every filter here wraps them in
# DATE() so a record on the end date isn't excluded by a plain string comparison.
# payment_date is stored date-only, so it compares fine without DATE().

def get_new_cases_count(start, end):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cases WHERE DATE(created_at) BETWEEN ? AND ?", (start, end)
    ).fetchone()
    conn.close()
    return row["n"]


def get_new_patients_count(start, end):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM patients WHERE DATE(created_at) BETWEEN ? AND ?", (start, end)
    ).fetchone()
    conn.close()
    return row["n"]


def get_cases_closed_count(start, end):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cases WHERE closed_at != '' AND DATE(closed_at) BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    conn.close()
    return row["n"]


def get_cases_closed_in_range(start, end):
    conn = get_db()
    rows = conn.execute(
        """SELECT c.*, p.name AS patient_name
           FROM cases c JOIN patients p ON p.id = c.patient_id
           WHERE c.closed_at != '' AND DATE(c.closed_at) BETWEEN ? AND ?
           ORDER BY c.closed_at DESC""",
        (start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_revenue_collected(start, end):
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE payment_date BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    conn.close()
    return row["total"]


def get_payments_in_range(start, end):
    conn = get_db()
    rows = conn.execute(
        """SELECT pay.*, p.name AS patient_name, c.title AS case_title
           FROM payments pay
           JOIN cases c ON c.id = pay.case_id
           JOIN patients p ON p.id = pay.patient_id
           WHERE pay.payment_date BETWEEN ? AND ?
           ORDER BY pay.payment_date DESC, pay.id DESC""",
        (start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_revenue_overview():
    """All-time billed vs. collected vs. outstanding — computed live, never stored,
    same principle as get_case_balance."""
    conn = get_db()
    row = conn.execute(
        """SELECT COALESCE(SUM(total_cost), 0) AS billed,
                  COALESCE((SELECT SUM(amount) FROM payments), 0) AS collected
           FROM cases"""
    ).fetchone()
    conn.close()
    billed, collected = row["billed"], row["collected"]
    return {"billed": billed, "collected": collected, "outstanding": billed - collected}


def get_pending_payments():
    """Every case with a live-computed outstanding balance > 0, for the 'Pending Payments
    by Patient & Case' report section and its Excel export — not period-filtered, since a
    balance owed doesn't stop being owed once the period ends."""
    conn = get_db()
    rows = conn.execute(
        """SELECT c.id AS case_id, c.title AS case_title, c.status, c.total_cost,
                  p.id AS patient_id, p.name AS patient_name, p.mobile,
                  COALESCE((SELECT SUM(amount) FROM payments WHERE case_id = c.id), 0) AS paid
           FROM cases c JOIN patients p ON p.id = c.patient_id"""
    ).fetchall()
    conn.close()
    pending = []
    for r in rows:
        row = dict(r)
        row["balance"] = row["total_cost"] - row["paid"]
        if row["balance"] > 0:
            pending.append(row)
    pending.sort(key=lambda r: r["balance"], reverse=True)
    return pending


def get_doctor_revenue_by_period(start, end):
    """Billed = total_cost of cases opened in the period; collected = payments against
    those same cases (a subquery, not a join, so a case with several payments doesn't
    fan out and inflate the billed sum). collection_rate feeds the progress bars."""
    conn = get_db()
    rows = conn.execute(
        """SELECT d.id AS doctor_id, d.name AS doctor_name, d.color AS doctor_color,
                  COALESCE(SUM(c.total_cost), 0) AS billed,
                  COALESCE((SELECT SUM(pay.amount) FROM payments pay
                            WHERE pay.case_id IN (
                                SELECT id FROM cases
                                WHERE doctor_id = d.id AND DATE(created_at) BETWEEN ? AND ?
                            )), 0) AS collected
           FROM doctors d
           LEFT JOIN cases c ON c.doctor_id = d.id AND DATE(c.created_at) BETWEEN ? AND ?
           GROUP BY d.id
           ORDER BY d.name""",
        (start, end, start, end),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        row = dict(r)
        row["collection_rate"] = (row["collected"] / row["billed"] * 100) if row["billed"] else 0
        result.append(row)
    return result


def get_patient_retention(months=6):
    """Lapsed = no logged visit within the threshold window. 'Visit' is
    case_visit_notes.visit_date — the actual clinical-visit record — falling back to the
    patient's registration date for a patient who has never had one logged yet. Anonymised
    (erased) patients are excluded — they're no longer a retention target."""
    conn = get_db()
    cutoff = _add_months(date.today(), -months).isoformat()
    rows = conn.execute(
        """SELECT p.id, p.name, p.mobile,
                  COALESCE((SELECT MAX(visit_date) FROM case_visit_notes WHERE patient_id = p.id),
                           DATE(p.created_at)) AS last_activity
           FROM patients p
           WHERE p.is_anonymized = 0"""
    ).fetchall()
    conn.close()
    total_patients = len(rows)
    lapsed = [dict(r) for r in rows if (r["last_activity"] or "") < cutoff]
    lapsed.sort(key=lambda r: r["last_activity"] or "")
    return {
        "lapsed": lapsed,
        "total_patients": total_patients,
        "threshold_months": months,
        "cutoff_date": cutoff,
    }


# ── Analytics (§5.10) — separate tab from Reports; the monthly revenue chart lives
# here, not in Reports, per the spec's explicit instruction. Everything is scoped to a
# single selected year, unlike Reports' free date range.

def get_analytics_years():
    """Years with any recorded activity, for the year selector — always includes the
    current year even before anything has happened in it yet."""
    conn = get_db()
    rows = conn.execute(
        """SELECT DISTINCT substr(created_at, 1, 4) AS y FROM cases WHERE created_at != ''
           UNION SELECT DISTINCT substr(created_at, 1, 4) FROM patients WHERE created_at != ''
           UNION SELECT DISTINCT substr(appt_date, 1, 4) FROM appointments WHERE appt_date != ''"""
    ).fetchall()
    conn.close()
    years = {int(r["y"]) for r in rows if r["y"] and r["y"].isdigit()}
    years.add(date.today().year)
    return sorted(years, reverse=True)


def get_analytics_kpis(year):
    start, end = f"{year}-01-01", f"{year}-12-31"
    conn = get_db()
    revenue = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS n FROM payments WHERE payment_date BETWEEN ? AND ?", (start, end)
    ).fetchone()["n"]
    new_patients = conn.execute(
        "SELECT COUNT(*) AS n FROM patients WHERE DATE(created_at) BETWEEN ? AND ?", (start, end)
    ).fetchone()["n"]
    case_stats = conn.execute(
        """SELECT COUNT(*) AS n, COALESCE(AVG(total_cost), 0) AS avg_cost
           FROM cases WHERE DATE(created_at) BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()
    closed = conn.execute(
        "SELECT COUNT(*) AS n FROM cases WHERE closed_at != '' AND DATE(closed_at) BETWEEN ? AND ?",
        (start, end),
    ).fetchone()["n"]
    appt_stats = conn.execute(
        """SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'No-show' THEN 1 ELSE 0 END) AS no_shows
           FROM appointments WHERE appt_date BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()
    conn.close()
    total_appts = appt_stats["total"] or 0
    no_shows = appt_stats["no_shows"] or 0
    return {
        "revenue_collected": revenue,
        "new_patients": new_patients,
        "new_cases": case_stats["n"],
        "cases_closed": closed,
        "avg_case_value": case_stats["avg_cost"],
        "no_show_rate": (no_shows / total_appts * 100) if total_appts else 0,
    }


def get_monthly_revenue(year):
    """12 values, Jan..Dec — THE monthly revenue chart (belongs in Analytics, never
    Reports, per §5.10's explicit instruction)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT CAST(substr(payment_date, 6, 2) AS INTEGER) AS m, COALESCE(SUM(amount), 0) AS total
           FROM payments WHERE substr(payment_date, 1, 4) = ? GROUP BY m""",
        (str(year),),
    ).fetchall()
    conn.close()
    by_month = {r["m"]: r["total"] for r in rows}
    return [by_month.get(m, 0) for m in range(1, 13)]


def get_monthly_new_patients(year):
    conn = get_db()
    rows = conn.execute(
        """SELECT CAST(substr(created_at, 6, 2) AS INTEGER) AS m, COUNT(*) AS n
           FROM patients WHERE substr(created_at, 1, 4) = ? GROUP BY m""",
        (str(year),),
    ).fetchall()
    conn.close()
    by_month = {r["m"]: r["n"] for r in rows}
    return [by_month.get(m, 0) for m in range(1, 13)]


def get_monthly_new_cases(year):
    conn = get_db()
    rows = conn.execute(
        """SELECT CAST(substr(created_at, 6, 2) AS INTEGER) AS m, COUNT(*) AS n
           FROM cases WHERE substr(created_at, 1, 4) = ? GROUP BY m""",
        (str(year),),
    ).fetchall()
    conn.close()
    by_month = {r["m"]: r["n"] for r in rows}
    return [by_month.get(m, 0) for m in range(1, 13)]


def get_monthly_appointments(year):
    conn = get_db()
    rows = conn.execute(
        """SELECT CAST(substr(appt_date, 6, 2) AS INTEGER) AS m, COUNT(*) AS n
           FROM appointments WHERE substr(appt_date, 1, 4) = ? GROUP BY m""",
        (str(year),),
    ).fetchall()
    conn.close()
    by_month = {r["m"]: r["n"] for r in rows}
    return [by_month.get(m, 0) for m in range(1, 13)]


def get_case_status_breakdown(year):
    """Active vs. Closed among cases opened in the selected year."""
    conn = get_db()
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM cases WHERE substr(created_at, 1, 4) = ? GROUP BY status",
        (str(year),),
    ).fetchall()
    conn.close()
    counts = {r["status"]: r["n"] for r in rows}
    return {"Active": counts.get("Active", 0), "Closed": counts.get("Closed", 0)}


def get_appointment_status_breakdown(year):
    conn = get_db()
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM appointments WHERE substr(appt_date, 1, 4) = ? GROUP BY status",
        (str(year),),
    ).fetchall()
    conn.close()
    counts = {r["status"]: r["n"] for r in rows}
    return {s: counts.get(s, 0) for s in ("Scheduled", "Completed", "Cancelled", "No-show")}


def get_doctor_revenue_share(year):
    """Collected (not billed) per doctor, for cases opened in the year — a doctor
    with nothing collected that year is left out rather than padding the chart with
    zero-width bars."""
    conn = get_db()
    rows = conn.execute(
        """SELECT d.id AS doctor_id, d.name AS doctor_name, d.color AS doctor_color,
                  COALESCE((SELECT SUM(pay.amount) FROM payments pay
                            WHERE pay.case_id IN (
                                SELECT id FROM cases WHERE doctor_id = d.id AND substr(created_at, 1, 4) = ?
                            )), 0) AS collected
           FROM doctors d
           ORDER BY d.name""",
        (str(year),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows if r["collected"] > 0]


def get_procedure_popularity(year, limit=8):
    """Tally of procedures across cases opened in the year. procedures_json is a
    JSON array of procedure-type names (see _collect_case_form) — parsed in Python,
    not SQL, same as the dental-chart entries."""
    conn = get_db()
    rows = conn.execute(
        "SELECT procedures_json, custom_procedure FROM cases WHERE substr(created_at, 1, 4) = ?",
        (str(year),),
    ).fetchall()
    conn.close()
    counts = {}
    for r in rows:
        try:
            procedures = json.loads(r["procedures_json"] or "[]")
        except ValueError:
            procedures = []
        for p in procedures:
            counts[p] = counts.get(p, 0) + 1
        if r["custom_procedure"]:
            counts[r["custom_procedure"]] = counts.get(r["custom_procedure"], 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"name": name, "count": n} for name, n in ranked]


# ── Dental charting (§14 item) ──────────────────────────────────────────────
# Append-only, like visit notes/prescriptions — a correction is a new entry, never an edit of
# an old one; "current state" is derived (latest entry per tooth+surface), and the append-only
# log itself IS the correction/version history the spec asks for. SVG is a presentation layer
# built from this data in the route/template — never the source of truth.

def _dentition_for_tooth(tooth_id):
    return "Primary" if tooth_id[0] in "5678" else "Permanent"


def add_dental_chart_entry(patient_id, case_id, tooth_id, surface, finding, status, notes, actor=None):
    dentition = _dentition_for_tooth(tooth_id)
    now = now_iso()
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO dental_chart_entries
               (patient_id, case_id, tooth_id, dentition, surface, finding, status, notes,
                recorded_by, recorded_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (patient_id, case_id, tooth_id, dentition, surface, finding, status, notes,
         actor.get("user_id") if actor else None, now, now),
    )
    entry_id = cur.lastrowid
    _write_audit(
        conn, actor, "dental_chart_entry_added", "patient", patient_id,
        after_summary=f"tooth={tooth_id}, surface={surface}, finding={finding}, status={status}",
    )
    conn.commit()
    conn.close()
    return entry_id


def list_dental_chart_entries(patient_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM dental_chart_entries WHERE patient_id = ? ORDER BY id DESC", (patient_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_current_dental_chart(patient_id):
    """Returns {tooth_id: [current entries]} — the latest entry per surface for that tooth,
    except a tooth whose overall latest entry is Missing/Extracted shows only that (it
    supersedes any older surface-specific findings, which no longer apply to an absent tooth)."""
    conn = get_db()
    latest_per_surface = conn.execute(
        """SELECT * FROM dental_chart_entries WHERE id IN (
               SELECT MAX(id) FROM dental_chart_entries WHERE patient_id = ? GROUP BY tooth_id, surface
           )""",
        (patient_id,),
    ).fetchall()
    latest_overall = conn.execute(
        """SELECT * FROM dental_chart_entries WHERE id IN (
               SELECT MAX(id) FROM dental_chart_entries WHERE patient_id = ? GROUP BY tooth_id
           )""",
        (patient_id,),
    ).fetchall()
    conn.close()

    by_tooth = {}
    for row in latest_per_surface:
        by_tooth.setdefault(row["tooth_id"], []).append(dict(row))

    for row in latest_overall:
        if row["finding"] == "Missing/Extracted":
            by_tooth[row["tooth_id"]] = [dict(row)]

    return by_tooth
