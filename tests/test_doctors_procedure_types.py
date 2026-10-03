from app import db
from tests.conftest import get_csrf
from tests.test_roles import _create_user, _login, _logout


def _add_doctor(client, name="Dr. New Hire", color="#123456"):
    token = get_csrf(client, "/doctors/")
    return client.post("/doctors/new", data={"name": name, "color": color, "csrf_token": token})


def _add_procedure_type(client, name="Whitening"):
    token = get_csrf(client, "/procedure-types/")
    return client.post("/procedure-types/new", data={"name": name, "csrf_token": token})


def test_admin_can_add_and_list_doctor(logged_in_client):
    resp = _add_doctor(logged_in_client, "Dr. Anjali Rao", "#2f9e44")
    assert resp.status_code == 302

    doctors = db.list_doctors(active_only=False)
    assert any(d["name"] == "Dr. Anjali Rao" and d["color"] == "#2f9e44" for d in doctors)

    list_resp = logged_in_client.get("/doctors/")
    assert b"Dr. Anjali Rao" in list_resp.data


def test_doctor_name_required(logged_in_client):
    resp = _add_doctor(logged_in_client, name="")
    assert resp.status_code == 302
    assert db.list_doctors(active_only=False) == []


def test_deactivate_and_reactivate_doctor(logged_in_client):
    _add_doctor(logged_in_client, "Dr. Temp")
    doctor = next(d for d in db.list_doctors(active_only=False) if d["name"] == "Dr. Temp")

    token = get_csrf(logged_in_client, "/doctors/")
    logged_in_client.post(f"/doctors/{doctor['id']}/deactivate", data={"csrf_token": token})
    assert db.get_doctor(doctor["id"])["is_active"] == 0
    assert doctor["id"] not in [d["id"] for d in db.list_doctors()]

    token = get_csrf(logged_in_client, "/doctors/")
    logged_in_client.post(f"/doctors/{doctor['id']}/activate", data={"csrf_token": token})
    assert db.get_doctor(doctor["id"])["is_active"] == 1


def test_deactivated_doctor_hidden_from_new_case_form(logged_in_client, patient_id):
    _add_doctor(logged_in_client, "Dr. Hideaway")
    doctor = next(d for d in db.list_doctors(active_only=False) if d["name"] == "Dr. Hideaway")

    resp = logged_in_client.get(f"/patients/{patient_id}/cases/new")
    assert b"Dr. Hideaway" in resp.data

    token = get_csrf(logged_in_client, "/doctors/")
    logged_in_client.post(f"/doctors/{doctor['id']}/deactivate", data={"csrf_token": token})
    logged_in_client.get("/dashboard")  # consume the flash message before re-checking the form

    resp2 = logged_in_client.get(f"/patients/{patient_id}/cases/new")
    assert b"Dr. Hideaway" not in resp2.data


def _deactivated_doctor_with_records(client, patient_id):
    """A doctor with one case and one appointment, then deactivated. Returns (doctor, active, case_id, appt_id)."""
    doctor_id = db.add_doctor("Dr. Retired", "#aa3355")
    active_id = db.add_doctor("Dr. Current", "#3355aa")
    case_id = db.add_case({"patient_id": patient_id, "title": "Old RCT", "doctor_id": doctor_id, "total_cost": 0})
    appt_id = db.add_appointment(patient_id, None, doctor_id, "2026-09-10", "10:00", "10:30", "Check", "", "Scheduled")
    db.set_doctor_active(doctor_id, False)
    return doctor_id, active_id, case_id, appt_id


def test_editing_a_deactivated_doctors_case_keeps_them(logged_in_client, patient_id):
    doctor_id, active_id, case_id, _ = _deactivated_doctor_with_records(logged_in_client, patient_id)

    form = logged_in_client.get(f"/cases/{case_id}/edit").data.decode()
    assert f'<option value="{doctor_id}" selected>Dr. Retired (inactive)</option>' in form
    assert f'<option value="{active_id}" >Dr. Current</option>' in form

    # A title fix saves without reassigning the case.
    token = get_csrf(logged_in_client, f"/cases/{case_id}/edit")
    resp = logged_in_client.post(f"/cases/{case_id}/edit",
                                 data={"title": "Old RCT 36", "doctor_id": doctor_id, "csrf_token": token})
    assert resp.status_code == 302
    case = db.get_case(case_id)
    assert (case["title"], case["doctor_id"]) == ("Old RCT 36", doctor_id)


def test_deactivated_doctor_cannot_be_given_new_work(logged_in_client, patient_id):
    doctor_id, active_id, case_id, appt_id = _deactivated_doctor_with_records(logged_in_client, patient_id)
    other_case = db.add_case({"patient_id": patient_id, "title": "Other", "doctor_id": active_id, "total_cost": 0})

    # New case, and an existing case that isn't theirs: the inactive doctor is refused server-side.
    token = get_csrf(logged_in_client, f"/patients/{patient_id}/cases/new")
    body = logged_in_client.post(f"/patients/{patient_id}/cases/new",
                                 data={"title": "New", "doctor_id": doctor_id, "csrf_token": token}).data.decode()
    assert "Choose a doctor from the list" in body
    token = get_csrf(logged_in_client, f"/cases/{other_case}/edit")
    body = logged_in_client.post(f"/cases/{other_case}/edit",
                                 data={"title": "Other", "doctor_id": doctor_id, "csrf_token": token}).data.decode()
    assert "Choose a doctor from the list" in body
    assert db.get_case(other_case)["doctor_id"] == active_id

    # New appointment: refused too.
    token = get_csrf(logged_in_client, "/appointments/new")
    body = logged_in_client.post("/appointments/new", data={
        "patient_id": patient_id, "doctor_id": doctor_id, "appt_date": "2026-10-01", "start_time": "09:00",
        "status": "Scheduled", "csrf_token": token,
    }).data.decode()
    assert "Choose a doctor from the list" in body


def test_editing_a_deactivated_doctors_appointment_keeps_them(logged_in_client, patient_id):
    doctor_id, _, _, appt_id = _deactivated_doctor_with_records(logged_in_client, patient_id)

    form = logged_in_client.get(f"/appointments/{appt_id}/edit").data.decode()
    assert f'<option value="{doctor_id}" selected>Dr. Retired (inactive)</option>' in form

    token = get_csrf(logged_in_client, f"/appointments/{appt_id}/edit")
    resp = logged_in_client.post(f"/appointments/{appt_id}/edit", data={
        "doctor_id": doctor_id, "appt_date": "2026-09-10", "start_time": "10:00", "end_time": "10:30",
        "title": "Check", "status": "Completed", "csrf_token": token,
    })
    assert resp.status_code == 302
    appt = db.get_appointment(appt_id)
    assert (appt["status"], appt["doctor_id"]) == ("Completed", doctor_id)


def test_calendar_legend_explains_deactivated_doctors_dots(logged_in_client, patient_id):
    _deactivated_doctor_with_records(logged_in_client, patient_id)
    assert "Dr. Retired (inactive)" in logged_in_client.get("/appointments/2026/9").data.decode()
    assert "Dr. Retired" not in logged_in_client.get("/appointments/2026/10").data.decode()  # no appointments then


def test_admin_can_add_and_list_procedure_type(logged_in_client):
    resp = _add_procedure_type(logged_in_client, "Whitening")
    assert resp.status_code == 302
    assert any(p["name"] == "Whitening" for p in db.list_procedure_types(active_only=False))

    list_resp = logged_in_client.get("/procedure-types/")
    assert b"Whitening" in list_resp.data


def test_procedure_type_name_required(logged_in_client):
    before = len(db.list_procedure_types(active_only=False))
    resp = _add_procedure_type(logged_in_client, name="")
    assert resp.status_code == 302
    assert len(db.list_procedure_types(active_only=False)) == before


def test_standard_case_types_shipped_and_idempotent(logged_in_client):
    from app.constants import STANDARD_PROCEDURE_TYPES

    names = [p["name"] for p in db.list_procedure_types(active_only=False)]
    assert set(STANDARD_PROCEDURE_TYPES) <= set(names)
    db.init_db()  # every startup re-runs the seed — it must not duplicate anything
    assert len(db.list_procedure_types(active_only=False)) == len(names)


def test_deactivated_standard_case_type_stays_deactivated(logged_in_client):
    pt = next(p for p in db.list_procedure_types() if p["name"] == "Biopsy")
    db.set_procedure_type_active(pt["id"], False)
    db.init_db()
    assert db.get_procedure_type(pt["id"])["is_active"] == 0
    assert "Biopsy" not in [p["name"] for p in db.list_procedure_types()]


def test_deactivate_and_reactivate_procedure_type(logged_in_client):
    _add_procedure_type(logged_in_client, "Temp Procedure")
    pt = next(p for p in db.list_procedure_types(active_only=False) if p["name"] == "Temp Procedure")

    token = get_csrf(logged_in_client, "/procedure-types/")
    logged_in_client.post(f"/procedure-types/{pt['id']}/deactivate", data={"csrf_token": token})
    assert db.get_procedure_type(pt["id"])["is_active"] == 0
    assert pt["id"] not in [p["id"] for p in db.list_procedure_types()]

    token = get_csrf(logged_in_client, "/procedure-types/")
    logged_in_client.post(f"/procedure-types/{pt['id']}/activate", data={"csrf_token": token})
    assert db.get_procedure_type(pt["id"])["is_active"] == 1


def test_doctor_and_procedure_type_changes_are_audited(logged_in_client):
    _add_doctor(logged_in_client, "Dr. Audit Test")
    doctor = next(d for d in db.list_doctors(active_only=False) if d["name"] == "Dr. Audit Test")
    token = get_csrf(logged_in_client, "/doctors/")
    logged_in_client.post(f"/doctors/{doctor['id']}/deactivate", data={"csrf_token": token})

    _add_procedure_type(logged_in_client, "Audit Procedure")

    actions = [e["action"] for e in db.list_audit_log()]
    assert "doctor_created" in actions
    assert "doctor_deactivated" in actions
    assert "procedure_type_created" in actions


def test_settings_hub_links_to_doctors_and_case_types(logged_in_client):
    resp = logged_in_client.get("/settings/")
    assert resp.status_code == 200
    assert b'href="/doctors/"' in resp.data
    assert b'href="/procedure-types/"' in resp.data


def test_non_admin_blocked_from_doctor_and_settings_management(logged_in_client, patient_id):
    _create_user(logged_in_client, "docrole", "doctor")
    _logout(logged_in_client)
    _login(logged_in_client, "docrole")

    assert logged_in_client.get("/settings/").status_code == 403
    assert logged_in_client.get("/doctors/").status_code == 403
    assert logged_in_client.get("/procedure-types/").status_code == 403

    dash = logged_in_client.get("/dashboard")
    assert b'href="/settings/"' not in dash.data


def test_doctor_credentials_can_be_added_and_edited(logged_in_client):
    token = get_csrf(logged_in_client, "/doctors/")
    logged_in_client.post("/doctors/new", data={
        "name": "Dr. Creds", "color": "#123456", "qualifications": "BDS",
        "registration_number": "K-100", "registration_council": "Kerala Dental Council", "csrf_token": token,
    })
    doctor = next(d for d in db.list_doctors() if d["name"] == "Dr. Creds")
    assert (doctor["qualifications"], doctor["registration_number"]) == ("BDS", "K-100")

    edit_url = f"/doctors/{doctor['id']}/edit"
    assert b"K-100" in logged_in_client.get(edit_url).data
    token = get_csrf(logged_in_client, edit_url)
    resp = logged_in_client.post(edit_url, data={
        "name": "Dr. Creds", "color": "#123456", "qualifications": "BDS, MDS",
        "registration_number": "K-100", "registration_council": "Kerala Dental Council", "csrf_token": token,
    })
    assert resp.status_code == 302
    assert db.get_doctor(doctor["id"])["qualifications"] == "BDS, MDS"

    conn = db.get_db()
    row = conn.execute("SELECT after_summary FROM audit_log WHERE action = 'doctor_updated'").fetchone()
    conn.close()
    assert row["after_summary"] == "changed: qualifications"


def test_doctors_list_flags_missing_credentials(logged_in_client):
    _add_doctor(logged_in_client, "Dr. Bare")
    assert b"Missing" in logged_in_client.get("/doctors/").data


def test_doctor_edit_is_admin_only(logged_in_client):
    doctor_id = db.add_doctor("Dr. Locked")
    _create_user(logged_in_client, "recep_doc_edit", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recep_doc_edit")
    assert logged_in_client.get(f"/doctors/{doctor_id}/edit").status_code == 403


# ── Renaming a case type also renames it on existing cases ──────────────────

def _type_id(name):
    return next(p["id"] for p in db.list_procedure_types(active_only=False) if p["name"] == name)


def _rename(client, type_id, new_name):
    url = f"/procedure-types/{type_id}/edit"
    return client.post(url, data={"name": new_name, "csrf_token": get_csrf(client, url)}, follow_redirects=True)


def _case_with(client, patient_id, procedures):
    import json
    from tests.test_cases import _create_case
    resp, _ = _create_case(client, patient_id, procedures=procedures)
    case_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    return case_id, lambda: json.loads(db.get_case(case_id)["procedures_json"])


def test_renaming_a_case_type_updates_existing_cases(logged_in_client, patient_id):
    case_id, procedures = _case_with(logged_in_client, patient_id, ["Scaling", "Crown"])
    _other_id, other = _case_with(logged_in_client, patient_id, ["Crown"])
    updated_before = db.get_case(case_id)["updated_at"]

    type_id = _type_id("Scaling")
    assert b"1 existing case uses" in logged_in_client.get(f"/procedure-types/{type_id}/edit").data
    resp = _rename(logged_in_client, type_id, "Scaling & Polishing")
    assert b"also updated on 1 existing case." in resp.data

    assert procedures() == ["Scaling & Polishing", "Crown"]
    assert other() == ["Crown"]
    assert db.get_case(case_id)["updated_at"] == updated_before  # a label fix, not case activity
    names = [p["name"] for p in db.list_procedure_types(active_only=False)]
    assert "Scaling & Polishing" in names and "Scaling" not in names

    conn = db.get_db()
    row = conn.execute("SELECT before_summary, after_summary FROM audit_log WHERE action = 'procedure_type_renamed'").fetchone()
    conn.close()
    assert row["before_summary"] == "name=Scaling"
    assert row["after_summary"] == "name=Scaling & Polishing, cases_updated=1"


def test_renamed_standard_case_type_is_not_seeded_back(logged_in_client, app):
    _rename(logged_in_client, _type_id("Scaling"), "Scaling & Polishing")
    with app.app_context():
        db.init_db()  # what every startup runs
    names = [p["name"] for p in db.list_procedure_types(active_only=False)]
    assert "Scaling" not in names and names.count("Scaling & Polishing") == 1
    # ...and still not after a second rename
    _rename(logged_in_client, _type_id("Scaling & Polishing"), "Oral Prophylaxis")
    with app.app_context():
        db.init_db()
    assert "Scaling" not in [p["name"] for p in db.list_procedure_types(active_only=False)]


def test_case_type_cannot_be_renamed_to_an_existing_or_blank_name(logged_in_client, patient_id):
    _case_id, procedures = _case_with(logged_in_client, patient_id, ["Scaling"])
    type_id = _type_id("Scaling")
    assert b"already a case type called" in _rename(logged_in_client, type_id, "crown").data
    _rename(logged_in_client, type_id, "   ")
    assert db.get_procedure_type(type_id)["name"] == "Scaling" and procedures() == ["Scaling"]


def test_case_type_rename_is_admin_only(logged_in_client):
    type_id = _type_id("Scaling")
    _create_user(logged_in_client, "recep_type_edit", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "recep_type_edit")
    assert logged_in_client.get(f"/procedure-types/{type_id}/edit").status_code == 403
    assert db.get_procedure_type(type_id)["name"] == "Scaling"


def test_add_doctor_form_offers_a_colour_unlike_the_existing_doctors(logged_in_client):
    db.add_doctor("Dr. Blue", "#1c7ed6")
    db.add_doctor("Dr. Green", "#2f9e44")
    body = logged_in_client.get("/doctors/").data.decode()
    offered = body.split('name="color" value="')[1].split('"')[0]
    assert offered not in ("#1c7ed6", "#2f9e44", "#2b6cb0")
    from app.doctor_colors import TOO_SIMILAR, distance
    assert min(distance(offered, "#1c7ed6"), distance(offered, "#2f9e44")) >= TOO_SIMILAR


def test_saving_a_colour_close_to_another_doctors_warns_but_still_saves(logged_in_client):
    db.add_doctor("Dr. Vivek Menon", "#1c7ed6")
    _add_doctor(logged_in_client, "Dr. Look Alike", "#2b6cb0")
    assert any(d["name"] == "Dr. Look Alike" for d in db.list_doctors())
    body = logged_in_client.get("/doctors/").data.decode()
    assert "Dr. Look Alike&#39;s calendar colour looks very like Dr. Vivek Menon&#39;s" in body

    # Editing a doctor and keeping their own colour doesn't compare them with themselves.
    doctor_id = next(d["id"] for d in db.list_doctors() if d["name"] == "Dr. Vivek Menon")
    token = get_csrf(logged_in_client, f"/doctors/{doctor_id}/edit")
    logged_in_client.post(f"/doctors/{doctor_id}/edit", data={
        "name": "Dr. Vivek Menon", "color": "#1c7ed6", "csrf_token": token})
    assert "looks very like Dr. Vivek Menon" not in logged_in_client.get("/doctors/").data.decode()


def test_a_distinct_colour_gives_no_warning(logged_in_client):
    db.add_doctor("Dr. Vivek Menon", "#1c7ed6")
    _add_doctor(logged_in_client, "Dr. Orange", "#e8590c")
    assert "looks very like" not in logged_in_client.get("/doctors/").data.decode()
