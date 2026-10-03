from app import db
from tests.conftest import get_csrf, register_patient
from tests.test_cases import _create_case
from tests.test_payments import _case_for as _case_with_payment


def _create_request(client, patient_id, request_type="Access", description="Patient wants a copy of their records"):
    token = get_csrf(client, f"/patients/{patient_id}/data-requests/new")
    return client.post(
        f"/patients/{patient_id}/data-requests/new",
        data={"request_type": request_type, "description": description, "csrf_token": token},
    )


def _make_receptionist(admin_client):
    token = get_csrf(admin_client, "/users/new")
    admin_client.post(
        "/users/new",
        data={
            "username": "recep_dpdp", "password": "testpass123", "confirm": "testpass123",
            "role": "receptionist", "security_question": "Q", "security_answer": "A",
            "csrf_token": token,
        },
    )
    token = get_csrf(admin_client, "/dashboard")
    admin_client.post("/logout", data={"csrf_token": token})
    token = get_csrf(admin_client, "/login")
    admin_client.post("/login", data={"username": "recep_dpdp", "password": "testpass123", "csrf_token": token})


def test_create_request_sets_pending_status_and_90_day_deadline(logged_in_client, patient_id):
    resp = _create_request(logged_in_client, patient_id, "Access")
    assert resp.status_code == 302

    requests_ = db.list_data_requests_for_patient(patient_id)
    assert len(requests_) == 1
    entry = requests_[0]
    assert entry["status"] == "Pending"

    requested = entry["requested_at"][:10]
    deadline = entry["deadline_at"][:10]
    from datetime import date
    assert (date.fromisoformat(deadline) - date.fromisoformat(requested)).days == 90


def test_request_appears_on_patient_detail_page(logged_in_client, patient_id):
    _create_request(logged_in_client, patient_id, "Correction", "Please fix my phone number")
    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert b"Correction" in resp.data
    assert b"Pending" in resp.data


def test_pending_count_shown_in_nav(logged_in_client, patient_id):
    _create_request(logged_in_client, patient_id, "Access")
    resp = logged_in_client.get("/dashboard")
    assert b"Privacy Requests (1)" in resp.data


def test_list_filters_by_status(logged_in_client, patient_id):
    _create_request(logged_in_client, patient_id, "Access")
    resp = logged_in_client.get("/data-requests?status=Rejected")
    assert b"No privacy requests" in resp.data
    resp = logged_in_client.get("/data-requests?status=Pending")
    assert b"Access" in resp.data


def test_receptionist_can_create_but_not_resolve(logged_in_client, patient_id):
    _create_request(logged_in_client, patient_id, "Access")
    entry = db.list_data_requests_for_patient(patient_id)[0]

    _make_receptionist(logged_in_client)
    resp = _create_request(logged_in_client, patient_id, "Correction", "Second request by receptionist")
    assert resp.status_code == 302
    assert len(db.list_data_requests_for_patient(patient_id)) == 2

    token = get_csrf(logged_in_client, f"/data-requests/{entry['id']}")
    resp = logged_in_client.post(
        f"/data-requests/{entry['id']}/resolve",
        data={"status": "Rejected", "resolution_note": "n/a", "csrf_token": token},
    )
    assert resp.status_code == 403


def test_resolve_requires_fresh_reauth(logged_in_client, patient_id):
    _create_request(logged_in_client, patient_id, "Access")
    entry = db.list_data_requests_for_patient(patient_id)[0]

    with logged_in_client.session_transaction() as sess:
        sess["reauth_at"] = "2020-01-01T00:00:00"

    token = get_csrf(logged_in_client, f"/data-requests/{entry['id']}")
    resp = logged_in_client.post(
        f"/data-requests/{entry['id']}/resolve",
        data={"status": "Completed", "resolution_note": "sent copy", "csrf_token": token},
    )
    assert resp.status_code == 302
    assert "/reauth" in resp.headers["Location"]
    assert db.get_data_request(entry["id"])["status"] == "Pending"


def test_access_request_completion_has_no_data_side_effect(logged_in_client, patient_id):
    _create_request(logged_in_client, patient_id, "Access")
    entry = db.list_data_requests_for_patient(patient_id)[0]

    token = get_csrf(logged_in_client, f"/data-requests/{entry['id']}")
    logged_in_client.post(
        f"/data-requests/{entry['id']}/resolve",
        data={"status": "Completed", "resolution_note": "Emailed a copy of the record", "csrf_token": token},
    )
    updated = db.get_data_request(entry["id"])
    assert updated["status"] == "Completed"
    assert updated["resolved_at"]
    patient = db.get_patient(patient_id)
    assert patient["is_anonymized"] == 0
    assert patient["name"] == "Case Test Patient"


def test_withdraw_consent_completion_clears_comms_consent(logged_in_client):
    patient_id = register_patient(logged_in_client, comms_consent="on")
    assert db.get_patient(patient_id)["comms_consent"] == 1

    _create_request(logged_in_client, patient_id, "Withdraw Consent", "No more SMS reminders")
    entry = db.list_data_requests_for_patient(patient_id)[0]

    token = get_csrf(logged_in_client, f"/data-requests/{entry['id']}")
    logged_in_client.post(
        f"/data-requests/{entry['id']}/resolve",
        data={"status": "Completed", "resolution_note": "Opted out", "csrf_token": token},
    )
    patient = db.get_patient(patient_id)
    assert patient["comms_consent"] == 0
    assert patient["comms_consent_at"] == ""
    assert patient["is_anonymized"] == 0  # withdraw-consent must not anonymise anything


def test_erasure_with_wrong_name_is_rejected_and_makes_no_changes(logged_in_client, patient_id):
    _create_request(logged_in_client, patient_id, "Erasure", "Patient wants to be forgotten")
    entry = db.list_data_requests_for_patient(patient_id)[0]

    token = get_csrf(logged_in_client, f"/data-requests/{entry['id']}")
    resp = logged_in_client.post(
        f"/data-requests/{entry['id']}/resolve",
        data={
            "status": "Completed", "resolution_note": "erasing",
            "confirm_name": "Wrong Name", "csrf_token": token,
        },
    )
    assert resp.status_code == 302
    updated = db.get_data_request(entry["id"])
    assert updated["status"] == "Pending"  # unchanged — the mismatch aborts before any write
    patient = db.get_patient(patient_id)
    assert patient["is_anonymized"] == 0
    assert patient["name"] == "Case Test Patient"


def test_erasure_with_correct_name_anonymises_but_preserves_clinical_and_financial_records(logged_in_client, patient_id):
    case_id, _ = _case_with_payment(logged_in_client, patient_id, total_cost="5000")
    case_url = f"/cases/{case_id}"
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": "2026-01-10", "amount": "1000", "csrf_token": token},
    )
    # Erasure waits until nothing is owed and treatment is closed.
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": "2026-01-20", "amount": "4000", "csrf_token": token},
    )
    db.close_case(case_id)

    _create_request(logged_in_client, patient_id, "Erasure", "Patient wants to be forgotten")
    entry = db.list_data_requests_for_patient(patient_id)[0]

    token = get_csrf(logged_in_client, f"/data-requests/{entry['id']}")
    resp = logged_in_client.post(
        f"/data-requests/{entry['id']}/resolve",
        data={
            "status": "Completed", "resolution_note": "Erased per request",
            "confirm_name": "Case Test Patient", "csrf_token": token,
        },
    )
    assert resp.status_code == 302

    patient = db.get_patient(patient_id)
    assert patient["is_anonymized"] == 1
    assert patient["anonymized_at"]
    assert patient["name"] == f"Erased Patient #{patient_id}"
    assert patient["mobile"] == ""
    assert patient["email"] == ""
    assert patient["address"] == ""
    assert patient["date_of_birth"] == ""
    assert patient["comms_consent"] == 0

    # Clinical and financial records must survive erasure untouched.
    case = db.get_case(case_id)
    assert case["title"] == "Root Canal — Tooth 36"
    assert case["total_cost"] == 5000
    assert db.get_case_balance(case_id) == 0
    assert len(db.list_payments_for_case(case_id)) == 2

    updated_request = db.get_data_request(entry["id"])
    assert updated_request["status"] == "Completed"


def test_patient_detail_shows_anonymized_banner(logged_in_client, patient_id):
    _create_request(logged_in_client, patient_id, "Erasure", "forget me")
    entry = db.list_data_requests_for_patient(patient_id)[0]
    token = get_csrf(logged_in_client, f"/data-requests/{entry['id']}")
    logged_in_client.post(
        f"/data-requests/{entry['id']}/resolve",
        data={
            "status": "Completed", "resolution_note": "done",
            "confirm_name": "Case Test Patient", "csrf_token": token,
        },
    )
    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert b"contact details were erased" in resp.data


def test_audit_entries_written_for_create_resolve_and_anonymize(logged_in_client, patient_id):
    _create_request(logged_in_client, patient_id, "Erasure", "forget me")
    entry = db.list_data_requests_for_patient(patient_id)[0]
    token = get_csrf(logged_in_client, f"/data-requests/{entry['id']}")
    logged_in_client.post(
        f"/data-requests/{entry['id']}/resolve",
        data={
            "status": "Completed", "resolution_note": "done",
            "confirm_name": "Case Test Patient", "csrf_token": token,
        },
    )
    actions = [e["action"] for e in db.list_audit_log()]
    assert "dpdp_request_created" in actions
    assert "dpdp_request_status_changed" in actions
    assert "patient_anonymized" in actions


def test_erasure_clears_appointment_text_and_privacy_request_descriptions(logged_in_client, patient_id):
    from tests.test_appointments import _book_appointment
    _book_appointment(logged_in_client, patient_id, title="Case Test Patient - crown fit",
                      notes="Call Case Test Patient on 9876543210")
    _create_request(logged_in_client, patient_id, "Access", "Case Test Patient asked for records")
    _create_request(logged_in_client, patient_id, "Erasure", "Case Test Patient wants to be forgotten")
    earlier = [r for r in db.list_data_requests_for_patient(patient_id) if r["request_type"] == "Access"][0]
    db.resolve_data_request(earlier["id"], "Completed", "PDF handed to Case Test Patient")

    erasure_id = [r for r in db.list_data_requests_for_patient(patient_id) if r["request_type"] == "Erasure"][0]["id"]
    entry = db.get_data_request(erasure_id)
    token = get_csrf(logged_in_client, f"/data-requests/{erasure_id}")
    logged_in_client.post(
        f"/data-requests/{erasure_id}/resolve",
        data={"status": "Completed", "resolution_note": "Erased per request",
              "confirm_name": "Case Test Patient", "csrf_token": token},
    )
    assert entry["status"] == "Pending"

    for appt in db.list_appointments_for_patient(patient_id):
        assert appt["title"] == "" and appt["notes"] == ""
        assert appt["appt_date"] == "2026-10-01"  # the booking itself is kept
    requests_ = {r["id"]: r for r in db.list_data_requests_for_patient(patient_id)}
    assert all(r["description"] == "" for r in requests_.values())
    assert requests_[earlier["id"]]["resolution_note"] == ""
    assert requests_[erasure_id]["resolution_note"] == "Erased per request"


def test_reminder_text_only_for_patients_who_agreed_to_reminders(logged_in_client):
    from tests.test_appointments import _book_appointment
    opted_out = register_patient(logged_in_client, name="No Reminders")
    opted_in = register_patient(logged_in_client, name="Wants Reminders", mobile="9876500009", comms_consent="on")
    _book_appointment(logged_in_client, opted_out)
    _book_appointment(logged_in_client, opted_in)

    out_appt = db.list_appointments_for_patient(opted_out)[0]["id"]
    in_appt = db.list_appointments_for_patient(opted_in)[0]["id"]
    out_page = logged_in_client.get(f"/appointments/{out_appt}/edit").data.decode()
    in_page = logged_in_client.get(f"/appointments/{in_appt}/edit").data.decode()

    assert "Dear No Reminders" not in out_page and "reminder-opted-out" in out_page
    assert "Dear Wants Reminders" in in_page and "reminder-opted-out" not in in_page


def test_withdrawing_consent_hides_the_reminder_text(logged_in_client):
    from tests.test_appointments import _book_appointment
    pid = register_patient(logged_in_client, name="Changed Mind", comms_consent="on")
    _book_appointment(logged_in_client, pid)
    _create_request(logged_in_client, pid, "Withdraw Consent", "No more messages")
    entry = db.list_data_requests_for_patient(pid)[0]
    db.resolve_data_request(entry["id"], "Completed", "done")

    appt = db.list_appointments_for_patient(pid)[0]["id"]
    page = logged_in_client.get(f"/appointments/{appt}/edit").data.decode()
    assert "Dear Changed Mind" not in page


def test_patient_form_records_consent_on_the_patients_behalf(logged_in_client):
    page = logged_in_client.get("/patients/new").data.decode()
    assert "Patient (or guardian, if under 18) has received and accepted the privacy notice" in page
    assert "has agreed to receive appointment reminders" in page
    assert "I have read and understood" not in page


def _try_erasure(client, patient_id, name="Case Test Patient"):
    _create_request(client, patient_id, "Erasure", "forget me")
    entry = [r for r in db.list_data_requests_for_patient(patient_id) if r["request_type"] == "Erasure"][0]
    token = get_csrf(client, f"/data-requests/{entry['id']}")
    client.post(f"/data-requests/{entry['id']}/resolve",
                data={"status": "Completed", "resolution_note": "done", "confirm_name": name, "csrf_token": token})
    return entry["id"]


def test_erasure_is_blocked_while_money_is_owed(logged_in_client, patient_id):
    case_id, _ = _case_with_payment(logged_in_client, patient_id, total_cost="5000")
    db.close_case(case_id)  # closed, but Rs. 5000 still unpaid
    request_id = _try_erasure(logged_in_client, patient_id)
    patient = db.get_patient(patient_id)
    assert patient["is_anonymized"] == 0 and patient["name"] == "Case Test Patient"
    assert db.get_data_request(request_id)["status"] == "Pending"
    body = logged_in_client.get(f"/data-requests/{request_id}").data.decode()
    assert "can&#39;t be completed yet: Rs. 5,000.00 is still outstanding" in body


def test_erasure_is_blocked_while_a_case_is_active(logged_in_client, patient_id):
    _create_case(logged_in_client, patient_id, total_cost="0")
    request_id = _try_erasure(logged_in_client, patient_id)
    assert db.get_patient(patient_id)["is_anonymized"] == 0
    assert "1 case is still active" in logged_in_client.get(f"/data-requests/{request_id}").data.decode()


def test_overpaid_case_does_not_hide_another_cases_debt(logged_in_client, patient_id):
    paid_id, _ = _case_with_payment(logged_in_client, patient_id, total_cost="1000")
    owing_id, _ = _case_with_payment(logged_in_client, patient_id, total_cost="2000")
    db.add_payment(paid_id, patient_id, "2026-01-05", 3000, "Cash", "", "")
    for c in (paid_id, owing_id):
        db.close_case(c)
    assert db.erasure_blockers(patient_id) == {"balance": 2000.0, "active_cases": 0}


def test_erasure_blockers_are_not_shown_to_a_receptionist(logged_in_client, patient_id):
    case_id, _ = _case_with_payment(logged_in_client, patient_id, total_cost="5000")
    _create_request(logged_in_client, patient_id, "Erasure", "forget me")
    request_id = db.list_data_requests_for_patient(patient_id)[0]["id"]
    _make_receptionist(logged_in_client)
    body = logged_in_client.get(f"/data-requests/{request_id}").data.decode()
    assert "can&#39;t be completed yet" not in body and "5,000" not in body
