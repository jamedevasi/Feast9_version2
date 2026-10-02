import io

from pypdf import PdfReader

from app import db
from tests.conftest import get_csrf, register_patient
from tests.test_cases import _create_case


def _case(client, patient_id):
    resp, doctor_id = _create_case(client, patient_id)
    case_url = resp.headers["Location"]
    return int(case_url.rstrip("/").rsplit("/", 1)[-1]), case_url, doctor_id


def rx_form_data(doctor_id, **overrides):
    """A valid one-medicine New Prescription POST (without the CSRF token)."""
    data = {
        "prescribed_date": "2026-01-20", "prescriber_id": str(doctor_id),
        "diagnosis": "Acute periapical abscess",
        "med_generic": ["Amoxicillin"], "med_brand": ["Mox"], "med_strength": ["500 mg"],
        "med_dose": ["1 capsule"], "med_frequency": ["Three times a day"], "med_route": ["Oral"],
        "med_duration": ["5 days"], "med_instructions": ["After food"],
        "advice": "Warm saline rinses",
    }
    data.update(overrides)
    return data


def _post_rx(client, case_id, case_url, doctor_id, **overrides):
    data = rx_form_data(doctor_id, **overrides)
    data["csrf_token"] = get_csrf(client, case_url)
    return client.post(f"/cases/{case_id}/prescriptions", data=data)


def _pdf_text(resp):
    assert resp.status_code == 200 and resp.data[:4] == b"%PDF"
    # whitespace-normalised, so a phrase wrapped inside a table column still matches
    return " ".join(" ".join(page.extract_text() for page in PdfReader(io.BytesIO(resp.data)).pages).split())


def test_allergy_banner_shown_for_allergic_patient(logged_in_client):
    patient_id = register_patient(logged_in_client, name="Allergic Patient", allergies="Penicillin")

    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    detail_resp = logged_in_client.get(case_url)
    assert b"Allergy alert" in detail_resp.data
    assert b"Penicillin" in detail_resp.data


def test_no_allergy_banner_for_patient_without_allergies(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    detail_resp = logged_in_client.get(case_url)
    assert b"Allergy alert" not in detail_resp.data


def test_add_prescription(logged_in_client, patient_id):
    case_id, case_url, doctor_id = _case(logged_in_client, patient_id)
    assert _post_rx(logged_in_client, case_id, case_url, doctor_id).status_code == 302

    rx = db.list_prescriptions_for_case(case_id)[0]
    assert rx["diagnosis"] == "Acute periapical abscess" and rx["doctor_id"] == doctor_id
    assert rx["medications"] == [{
        "generic": "Amoxicillin", "brand": "Mox", "strength": "500 mg", "dose": "1 capsule",
        "frequency": "Three times a day", "route": "Oral", "duration": "5 days", "instructions": "After food",
    }]
    # the plain-text copy other screens/exports read carries the same content
    assert "AMOXICILLIN (Mox) 500 mg, 1 capsule, Three times a day, Oral, for 5 days" in rx["rx_details"]
    assert "Diagnosis: Acute periapical abscess" in rx["rx_details"] and "Warm saline rinses" in rx["rx_details"]

    body = logged_in_client.get(case_url).data.decode()
    assert "Acute periapical abscess" in body and "AMOXICILLIN" in body and "Warm saline rinses" in body


def test_prescription_needs_doctor_diagnosis_and_a_complete_medicine(logged_in_client, patient_id):
    case_id, case_url, doctor_id = _case(logged_in_client, patient_id)
    for overrides, message in [
        ({"diagnosis": ""}, "Enter the diagnosis"),
        ({"prescriber_id": ""}, "Choose the prescribing doctor"),
        ({"med_generic": [""], "med_brand": [""], "med_strength": [""], "med_dose": [""],
          "med_frequency": [""], "med_duration": [""], "med_instructions": [""]}, "Enter at least one medicine"),
        ({"med_strength": [""], "med_frequency": [""]}, "Medicine 1: enter the strength, frequency."),
        ({"med_generic": [""]}, "Medicine 1: enter the generic name."),  # a brand name alone isn't enough
        ({"med_route": ["Telepathy"]}, "Medicine 1: enter the route."),
    ]:
        resp = _post_rx(logged_in_client, case_id, case_url, doctor_id, **overrides)
        assert resp.status_code == 302
        assert message in logged_in_client.get(case_url).data.decode(), message
    assert db.list_prescriptions_for_case(case_id) == []


def test_rejected_prescription_keeps_what_was_typed(logged_in_client, patient_id):
    case_id, case_url, doctor_id = _case(logged_in_client, patient_id)
    _post_rx(logged_in_client, case_id, case_url, doctor_id, diagnosis="", advice="Soft diet for two days")
    body = logged_in_client.get(case_url).data.decode()
    assert 'value="Amoxicillin"' in body and "Soft diet for two days" in body
    # shown once only
    assert 'value="Amoxicillin"' not in logged_in_client.get(case_url).data.decode()


def test_blank_medicine_rows_are_dropped_and_several_are_kept_in_order(logged_in_client, patient_id):
    case_id, case_url, doctor_id = _case(logged_in_client, patient_id)
    _post_rx(
        logged_in_client, case_id, case_url, doctor_id,
        med_generic=["Amoxicillin", "", "Ibuprofen"], med_brand=["", "", ""],
        med_strength=["500 mg", "", "400 mg"], med_dose=["1 capsule", "", "1 tablet"],
        med_frequency=["Three times a day", "", "When needed (SOS)"], med_route=["Oral", "Oral", "Oral"],
        med_duration=["5 days", "", ""], med_instructions=["", "", ""],
    )
    meds = db.list_prescriptions_for_case(case_id)[0]["medications"]
    assert [m["generic"] for m in meds] == ["Amoxicillin", "Ibuprofen"]


def test_prescription_audit_never_holds_clinical_text(logged_in_client, patient_id):
    case_id, case_url, doctor_id = _case(logged_in_client, patient_id)
    _post_rx(logged_in_client, case_id, case_url, doctor_id)
    conn = db.get_db()
    row = conn.execute("SELECT after_summary FROM audit_log WHERE action = 'prescription_added'").fetchone()
    conn.close()
    assert "1 medicines" in row["after_summary"]
    assert "Amoxicillin" not in row["after_summary"] and "abscess" not in row["after_summary"]


def test_printed_prescription_carries_the_required_particulars(logged_in_client):
    patient_id = register_patient(logged_in_client, name="Print Patient")
    case_id, case_url, doctor_id = _case(logged_in_client, patient_id)
    db.update_doctor(doctor_id, {
        "name": "Dr. Test Doctor", "color": "#000000", "qualifications": "BDS, MDS",
        "registration_number": "A-12345", "registration_council": "Kerala Dental Council",
    })
    db.set_setting("clinic_name", "Smile Clinic")
    db.set_setting("clinic_address", "12 MG Road, Kochi")
    db.set_setting("clinic_phone", "0484-1234567")
    _post_rx(logged_in_client, case_id, case_url, doctor_id)
    rx_id = db.list_prescriptions_for_case(case_id)[0]["id"]

    text = _pdf_text(logged_in_client.get(f"/cases/{case_id}/prescriptions/{rx_id}.pdf"))
    patient = db.get_patient(patient_id)
    for expected in [
        "Smile Clinic", "12 MG Road, Kochi", "0484-1234567",                      # clinic contact details
        "Dr. Test Doctor", "BDS, MDS", "A-12345", "Kerala Dental Council",       # doctor
        "Print Patient", f"Sex: {patient['sex']}",                                # patient
        "Date of issue: 2026-01-20",
        "Acute periapical abscess",                                               # diagnosis
        "AMOXICILLIN", "(Mox)", "500 mg", "1 capsule", "Three times a day", "Oral", "5 days",
        "Warm saline rinses",
    ]:
        assert expected in text, expected
    assert "Age:" in text or "DOB:" in text


def test_prescription_from_before_the_structured_form_still_prints(logged_in_client, patient_id):
    case_id, _case_url, _doctor_id = _case(logged_in_client, patient_id)
    db.add_prescription(case_id, patient_id, "Amoxicillin 500mg TID x5d", "2026-01-20")
    rx_id = db.list_prescriptions_for_case(case_id)[0]["id"]
    assert b"Amoxicillin 500mg TID x5d" in logged_in_client.get(f"/cases/{case_id}").data
    text = _pdf_text(logged_in_client.get(f"/cases/{case_id}/prescriptions/{rx_id}.pdf"))
    assert "Amoxicillin 500mg TID x5d" in text and "Dr. Test Doctor" in text  # falls back to the case's doctor


def test_case_page_says_what_a_printed_prescription_is_missing(logged_in_client, patient_id):
    case_id, case_url, doctor_id = _case(logged_in_client, patient_id)
    body = logged_in_client.get(case_url).data.decode()
    assert "registration number" in body and "address and phone number" in body

    db.update_doctor(doctor_id, {
        "name": "Dr. Test Doctor", "color": "#000000", "qualifications": "BDS",
        "registration_number": "A-1", "registration_council": "",
    })
    db.set_setting("clinic_address", "12 MG Road")
    db.set_setting("clinic_phone", "12345")
    assert "not filled in yet" not in logged_in_client.get(case_url).data.decode()


def test_prescription_is_not_shown_on_patient_page(logged_in_client, patient_id):
    """Prescriptions are recorded and viewed on the case itself, never on the patient page."""
    case_id, case_url, doctor_id = _case(logged_in_client, patient_id)
    _post_rx(logged_in_client, case_id, case_url, doctor_id)

    patient_resp = logged_in_client.get(f"/patients/{patient_id}")
    assert b"Prescription History" not in patient_resp.data
    assert b"AMOXICILLIN" not in patient_resp.data and b"Amoxicillin" not in patient_resp.data
