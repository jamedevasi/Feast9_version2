import base64
import io

from PIL import Image, ImageDraw

from app import db
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def _case_for(client, patient_id, **overrides):
    resp, _ = _create_case(client, patient_id, **overrides)
    case_url = resp.headers["Location"]
    case_id = int(case_url.rstrip("/").rsplit("/", 1)[-1])
    return case_id, case_url


def _signature_data_url():
    img = Image.new("RGB", (400, 150), "white")
    draw = ImageDraw.Draw(img)
    draw.line([(20, 100), (100, 40), (180, 110), (260, 30), (340, 90)], fill="black", width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _garbage_data_url():
    """Valid PNG magic bytes, but not a real decodable image."""
    garbage = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    return "data:image/png;base64," + base64.b64encode(garbage).decode()


def test_record_consent_with_signature(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/consent",
        data={"consent_notes": "", "signature_data": _signature_data_url(), "csrf_token": token},
    )
    assert resp.status_code == 302

    case = db.get_case(case_id)
    assert case["consent_recorded"] == 1
    assert case["consent_signature_filename"]
    # A real signature was captured -> don't fall back to the "Paper consent on file" text.
    assert case["consent_notes"] == ""

    detail = logged_in_client.get(case_url)
    assert b"consent-signature-preview" in detail.data

    sig_resp = logged_in_client.get(f"/cases/{case_id}/consent-signature")
    assert sig_resp.status_code == 200
    assert sig_resp.headers["Content-Type"] == "image/png"
    assert sig_resp.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_record_consent_without_signature_falls_back_to_paper_text(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/consent",
        data={"consent_notes": "", "signature_data": "", "csrf_token": token},
    )
    assert resp.status_code == 302

    case = db.get_case(case_id)
    assert case["consent_notes"] == "Paper consent on file"
    assert case["consent_signature_filename"] == ""


def test_record_consent_with_signature_and_explicit_notes_keeps_both(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/consent",
        data={
            "consent_notes": "Witnessed by front desk", "signature_data": _signature_data_url(),
            "csrf_token": token,
        },
    )
    case = db.get_case(case_id)
    assert case["consent_notes"] == "Witnessed by front desk"
    assert case["consent_signature_filename"]


def test_corrupt_signature_data_rejected_gracefully(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    resp = logged_in_client.post(
        f"/cases/{case_id}/consent",
        data={"consent_notes": "", "signature_data": _garbage_data_url(), "csrf_token": token},
    )
    assert resp.status_code == 302

    case = db.get_case(case_id)
    assert case["consent_signature_filename"] == ""
    # No signature actually saved -> falls back to the paper-consent default, same as no signature at all.
    assert case["consent_notes"] == "Paper consent on file"


def test_consent_signature_route_404_when_none_recorded(logged_in_client, patient_id):
    case_id, _case_url = _case_for(logged_in_client, patient_id)
    resp = logged_in_client.get(f"/cases/{case_id}/consent-signature")
    assert resp.status_code == 404


def test_consent_pdf_embeds_signature(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/consent",
        data={"consent_notes": "", "signature_data": _signature_data_url(), "csrf_token": token},
    )

    without_signature_size_resp = logged_in_client.get(f"/cases/{case_id}/consent.pdf")
    assert without_signature_size_resp.status_code == 200
    assert without_signature_size_resp.data[:4] == b"%PDF"

    # A case with no signature produces a visibly smaller PDF (text-only) — sanity check
    # that the embedded image actually made it into the document rather than being dropped.
    case_id2, case_url2 = _case_for(logged_in_client, patient_id, title="No Signature Case")
    token2 = get_csrf(logged_in_client, case_url2)
    logged_in_client.post(
        f"/cases/{case_id2}/consent",
        data={"consent_notes": "", "signature_data": "", "csrf_token": token2},
    )
    no_sig_resp = logged_in_client.get(f"/cases/{case_id2}/consent.pdf")
    assert len(without_signature_size_resp.data) > len(no_sig_resp.data)


def test_consent_recording_is_audited_with_signature_flag(logged_in_client, patient_id):
    case_id, case_url = _case_for(logged_in_client, patient_id)
    token = get_csrf(logged_in_client, case_url)
    logged_in_client.post(
        f"/cases/{case_id}/consent",
        data={"consent_notes": "", "signature_data": _signature_data_url(), "csrf_token": token},
    )
    entry = next(e for e in db.list_audit_log() if e["action"] == "consent_recorded")
    assert "signature=yes" in entry["after_summary"]
