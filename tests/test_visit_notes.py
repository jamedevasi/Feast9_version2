from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def test_add_visit_note(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])

    token = get_csrf(logged_in_client, case_url)
    add_resp = logged_in_client.post(
        f"/cases/{case_id}/visit-notes",
        data={"note": "Patient tolerated procedure well.", "visit_date": "2026-01-15", "csrf_token": token},
    )
    assert add_resp.status_code == 302

    detail_resp = logged_in_client.get(case_url)
    assert b"Patient tolerated procedure well." in detail_resp.data
    assert b"2026-01-15" in detail_resp.data


def test_blank_visit_note_not_saved(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])

    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/visit-notes",
        data={"note": "  ", "visit_date": "2026-01-15", "csrf_token": token},
    )
    assert db.list_visit_notes_for_case(case_id) == []


def test_visit_notes_newest_first(logged_in_client, patient_id):
    resp, _ = _create_case(logged_in_client, patient_id)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])

    for date_, text in [("2026-01-01", "First visit"), ("2026-02-01", "Second visit")]:
        token = get_csrf(logged_in_client, case_url)
        logged_in_client.post(
            f"/cases/{case_id}/visit-notes",
            data={"note": text, "visit_date": date_, "csrf_token": token},
        )

    notes = db.list_visit_notes_for_case(case_id)
    assert [n["note"] for n in notes] == ["Second visit", "First visit"]
