"""Consent is collected on paper, once per case: the case page prints a consent form to sign,
and staff then mark it recorded. The on-screen signature pad was removed (2026-10-03); a
signature captured with it before then must still show and print."""
import io
import pathlib

from PIL import Image
from pypdf import PdfReader

from app import config as app_config
from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def _case_for(client, patient_id, **overrides):
    resp, _ = _create_case(client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    return int(case_url.rstrip("/").rsplit("/", 1)[-1]), case_url


def _pdf_text(data):
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def test_case_page_offers_the_printable_form_and_no_signature_pad(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    page = logged_in_client.get(case_url).data
    assert f"/cases/{case_id}/consent.pdf".encode() in page
    assert b"signature-pad" not in page
    assert b"signature_pad.js" not in page


def test_unsigned_consent_form_prints_statement_and_signature_lines(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id)
    resp = logged_in_client.get(f"/cases/{case_id}/consent.pdf")
    text = _pdf_text(resp.data)
    assert "CONSENT FOR DENTAL TREATMENT" in text
    assert f"Case reference: #{case_id}" in text and f"Patient ID: {patient_id}" in text
    assert "What the treatment involves" in text and "initial each line" in text
    for column in ("Patient", "Guardian (if under 18)", "Doctor", "Witness", "Relationship:"):
        assert column in text, column
    assert "Office use" in text
    assert "Recorded in Feast9" not in text
    assert len(PdfReader(io.BytesIO(resp.data)).pages) == 1


def test_consent_form_stays_on_one_sheet_with_long_details(logged_in_client, patient_id):
    db.update_patient(patient_id, {"name": "Long Name " * 8})
    db.set_setting("clinic_name", "A Very Long Clinic Name Dental Care and Implant Centre")
    db.set_setting("clinic_address", "Building 12, Second Floor, Long Street Name, Some Nagar, Kochi, Kerala 682001")
    db.set_setting("clinic_phone", "0484-1234567")
    case_id, _ = _case_for(logged_in_client, patient_id, title="Full mouth rehabilitation " * 4,
                           custom_procedure="Custom procedure with a long description " * 4)
    db.record_case_consent(case_id, "Signed form filed in the blue folder, drawer 3 " * 3)
    page = PdfReader(io.BytesIO(logged_in_client.get(f"/cases/{case_id}/consent.pdf").data)).pages
    assert len(page) == 1


def test_consent_form_never_shows_the_cost(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id, total_cost="45678")
    text = _pdf_text(logged_in_client.get(f"/cases/{case_id}/consent.pdf").data)
    assert "45678" not in text and "45,678" not in text
    assert "Estimated cost" in text


def test_each_case_has_its_own_consent(logged_in_client, patient_id):
    first, first_url = _case_for(logged_in_client, patient_id, title="Root Canal")
    second, _ = _case_for(logged_in_client, patient_id, title="Crown")
    token = get_csrf(logged_in_client, first_url)
    logged_in_client.post(f"/cases/{first}/consent", data={"consent_notes": "", "csrf_token": token})
    assert db.get_case(first)["consent_recorded"] == 1
    assert db.get_case(second)["consent_recorded"] == 0


def test_recording_consent_defaults_to_paper_note_and_ignores_signature_data(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/consent",
        data={"consent_notes": "", "signature_data": "data:image/png;base64,AAAA", "csrf_token": token},
    )
    assert resp.status_code == 302
    case = db.get_case(case_id)
    assert case["consent_recorded"] == 1
    assert case["consent_notes"] == "Paper consent on file"
    assert case["consent_signature_filename"] == ""
    entry = next(e for e in db.list_audit_log() if e["action"] == "consent_recorded")
    assert "signature=no" in entry["after_summary"]

    text = _pdf_text(logged_in_client.get(f"/cases/{case_id}/consent.pdf").data)
    assert "Recorded in Feast9 on" in text
    assert "Paper consent on file" in text


def test_signature_captured_before_the_pad_was_removed_still_shows(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    buf = io.BytesIO()
    Image.new("RGB", (400, 150), "white").save(buf, format="PNG")
    uploads = pathlib.Path(app_config.uploads_dir())
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "old-signature.png").write_bytes(buf.getvalue())
    db.record_case_consent(case_id, "", signature_filename="old-signature.png")

    assert b"consent-signature-preview" in logged_in_client.get(case_url).data
    sig = logged_in_client.get(f"/cases/{case_id}/consent-signature")
    assert sig.status_code == 200 and sig.data[:8] == b"\x89PNG\r\n\x1a\n"
    pdf = logged_in_client.get(f"/cases/{case_id}/consent.pdf")
    assert "Signature captured on screen" in _pdf_text(pdf.data)


def test_consent_signature_route_404_when_none_recorded(logged_in_client, patient_id):
    case_id, _ = _case_for(logged_in_client, patient_id)
    assert logged_in_client.get(f"/cases/{case_id}/consent-signature").status_code == 404
