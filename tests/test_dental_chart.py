from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def _add_entry(client, patient_id, **overrides):
    token = get_csrf(client, f"/patients/{patient_id}/dental-chart")
    data = {
        "tooth_id": "11", "surface": "Mesial", "finding": "Caries",
        "status": "Existing", "notes": "", "case_id": "", "csrf_token": token,
    }
    data.update(overrides)
    return client.post(f"/patients/{patient_id}/dental-chart", data=data)


def test_add_entry_appears_in_current_chart(logged_in_client, patient_id):
    resp = _add_entry(logged_in_client, patient_id)
    assert resp.status_code == 302

    chart = db.get_current_dental_chart(patient_id)
    assert "11" in chart
    assert chart["11"][0]["finding"] == "Caries"
    assert chart["11"][0]["dentition"] == "Permanent"


def test_primary_tooth_dentition_computed_correctly(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="55", surface="Whole Tooth", finding="Sound")
    chart = db.get_current_dental_chart(patient_id)
    assert chart["55"][0]["dentition"] == "Primary"


def test_whole_tooth_finding_forces_surface_regardless_of_submission(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="26", surface="Mesial", finding="Crown", status="Completed")
    chart = db.get_current_dental_chart(patient_id)
    assert chart["26"][0]["surface"] == "Whole Tooth"


def test_missing_tooth_supersedes_older_surface_findings(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="36", surface="Mesial", finding="Caries")
    _add_entry(logged_in_client, patient_id, tooth_id="36", surface="Distal", finding="Restoration")
    _add_entry(logged_in_client, patient_id, tooth_id="36", surface="Whole Tooth", finding="Missing/Extracted", status="Completed")

    chart = db.get_current_dental_chart(patient_id)
    assert len(chart["36"]) == 1
    assert chart["36"][0]["finding"] == "Missing/Extracted"

    # The append-only history still has all three — nothing was overwritten or deleted.
    history = db.list_dental_chart_entries(patient_id)
    assert len(history) == 3


def test_new_entry_for_same_tooth_and_surface_supersedes_without_deleting_history(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="14", surface="Occlusal/Incisal", finding="Caries", status="Existing")
    _add_entry(logged_in_client, patient_id, tooth_id="14", surface="Occlusal/Incisal", finding="Restoration", status="Completed")

    chart = db.get_current_dental_chart(patient_id)
    assert chart["14"][0]["finding"] == "Restoration"

    history = [e for e in db.list_dental_chart_entries(patient_id) if e["tooth_id"] == "14"]
    assert len(history) == 2
    findings = {e["finding"] for e in history}
    assert findings == {"Caries", "Restoration"}


def test_invalid_tooth_rejected(logged_in_client, patient_id):
    resp = _add_entry(logged_in_client, patient_id, tooth_id="99")
    assert resp.status_code == 200
    assert b"Select a valid tooth" in resp.data
    assert db.list_dental_chart_entries(patient_id) == []


def test_entry_can_be_linked_to_a_case(logged_in_client, patient_id):
    case_resp, _ = _create_case(logged_in_client, patient_id)
    case_id = int(case_resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    _add_entry(logged_in_client, patient_id, tooth_id="46", case_id=str(case_id))
    entry = db.list_dental_chart_entries(patient_id)[0]
    assert entry["case_id"] == case_id


def test_audit_entry_logs_structured_fields_not_notes_content(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="21", notes="Highly sensitive detail")
    entries = [e for e in db.list_audit_log() if e["action"] == "dental_chart_entry_added"]
    assert len(entries) == 1
    assert "tooth=21" in entries[0]["after_summary"]
    assert "Highly sensitive detail" not in entries[0]["after_summary"]


def test_dental_chart_page_requires_login(app, patient_id):
    unauth_client = app.test_client()
    resp = unauth_client.get(f"/patients/{patient_id}/dental-chart")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_dental_chart_link_on_patient_page(logged_in_client, patient_id):
    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert b"Dental Chart" in resp.data


def test_chart_history_shows_entries_newest_first(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="11", finding="Caries")
    _add_entry(logged_in_client, patient_id, tooth_id="12", finding="Fracture")

    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    body = resp.data.decode()
    assert body.index("Tooth 12") < body.index("Tooth 11")
