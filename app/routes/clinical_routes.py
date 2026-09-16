"""Clinical Attachments, Lab Requisitions, Referral Notes — grouped as in feast9_v2_agents.md §3."""
import os
import uuid

from flask import Blueprint, abort, flash, redirect, request, send_file, url_for
from werkzeug.utils import secure_filename

from app import config as app_config
from app import db
from app.auth import login_required
from app.constants import ATTACHMENT_TYPES, LAB_REQ_STATUSES
from app.csrf import validate_csrf
from app.validators import detect_upload_type, normalize_date, today_iso

bp = Blueprint("clinical", __name__)

_EXT_TO_MIMETYPE = {"jpg": "image/jpeg", "png": "image/png", "pdf": "application/pdf"}


def _get_case_or_404(case_id):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    return case


def _uploads_dir():
    path = os.path.join(app_config.DATA_DIR, "clinical_uploads")
    os.makedirs(path, exist_ok=True)
    return path


@bp.route("/cases/<int:case_id>/attachments", methods=["POST"])
@login_required
def upload_attachment(case_id):
    validate_csrf(request.form.get("csrf_token"))
    _get_case_or_404(case_id)

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        flash("Choose a file to upload.", "warning")
        return redirect(url_for("cases.detail", case_id=case_id))

    content = upload.read()
    detected = detect_upload_type(content[:16])
    if detected is None:
        flash("Unsupported or corrupted file — only JPG, PNG, and PDF are accepted.", "warning")
        return redirect(url_for("cases.detail", case_id=case_id))

    _mimetype, ext = detected
    filename = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(_uploads_dir(), filename), "wb") as f:
        f.write(content)

    file_type = request.form.get("file_type", "Other")
    if file_type not in ATTACHMENT_TYPES:
        file_type = "Other"
    description = request.form.get("description", "").strip()
    original_name = secure_filename(upload.filename) or "upload"

    db.add_attachment(case_id, filename, original_name, file_type, description)
    flash("Attachment uploaded.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/attachments/<int:attachment_id>/file")
@login_required
def serve_attachment(attachment_id):
    attachment = db.get_attachment(attachment_id)
    if not attachment:
        abort(404)
    path = os.path.join(_uploads_dir(), attachment["filename"])
    if not os.path.exists(path):
        abort(404)
    ext = attachment["filename"].rsplit(".", 1)[-1].lower()
    mimetype = _EXT_TO_MIMETYPE.get(ext, "application/octet-stream")
    return send_file(path, mimetype=mimetype)


@bp.route("/attachments/<int:attachment_id>/delete", methods=["POST"])
@login_required
def delete_attachment(attachment_id):
    validate_csrf(request.form.get("csrf_token"))
    attachment = db.get_attachment(attachment_id)
    if not attachment:
        abort(404)
    case_id = attachment["case_id"]
    filename = db.delete_attachment(attachment_id)
    if filename:
        try:
            os.remove(os.path.join(_uploads_dir(), filename))
        except FileNotFoundError:
            pass
    flash("Attachment deleted.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/cases/<int:case_id>/lab-reqs", methods=["POST"])
@login_required
def add_lab_req(case_id):
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)

    work_description = request.form.get("work_description", "").strip()
    if not work_description:
        flash("Work description is required for a lab requisition.", "warning")
        return redirect(url_for("cases.detail", case_id=case_id))

    lab_name = request.form.get("lab_name", "").strip()
    sent_date = normalize_date(request.form.get("sent_date", "")) or today_iso()
    expected_return = normalize_date(request.form.get("expected_return", ""))
    notes = request.form.get("notes", "").strip()

    db.add_lab_req(case_id, case["patient_id"], lab_name, work_description, sent_date, expected_return, notes)
    flash("Lab requisition added.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/lab-reqs/<int:req_id>/update", methods=["POST"])
@login_required
def update_lab_req(req_id):
    validate_csrf(request.form.get("csrf_token"))
    lab_req = db.get_lab_req(req_id)
    if not lab_req:
        abort(404)

    status = request.form.get("status", "Sent")
    if status not in LAB_REQ_STATUSES:
        status = "Sent"
    received_date = normalize_date(request.form.get("received_date", ""))
    notes = request.form.get("notes", "").strip()

    db.update_lab_req(req_id, status, received_date, notes)
    flash("Lab requisition updated.", "success")
    return redirect(url_for("cases.detail", case_id=lab_req["case_id"]))


@bp.route("/lab-reqs/<int:req_id>/delete", methods=["POST"])
@login_required
def delete_lab_req(req_id):
    validate_csrf(request.form.get("csrf_token"))
    lab_req = db.get_lab_req(req_id)
    if not lab_req:
        abort(404)
    db.delete_lab_req(req_id)
    flash("Lab requisition deleted.", "success")
    return redirect(url_for("cases.detail", case_id=lab_req["case_id"]))


@bp.route("/cases/<int:case_id>/referrals", methods=["POST"])
@login_required
def add_referral(case_id):
    validate_csrf(request.form.get("csrf_token"))
    case = _get_case_or_404(case_id)

    referred_to = request.form.get("referred_to", "").strip()
    reason = request.form.get("reason", "").strip()
    if not referred_to or not reason:
        flash("Referred To and Reason are required for a referral.", "warning")
        return redirect(url_for("cases.detail", case_id=case_id))

    referral_date = normalize_date(request.form.get("referral_date", "")) or today_iso()
    speciality = request.form.get("speciality", "").strip()
    notes = request.form.get("notes", "").strip()

    db.add_referral(case_id, case["patient_id"], referral_date, referred_to, speciality, reason, notes)
    flash("Referral added.", "success")
    return redirect(url_for("cases.detail", case_id=case_id))


@bp.route("/referrals/<int:ref_id>/delete", methods=["POST"])
@login_required
def delete_referral(ref_id):
    validate_csrf(request.form.get("csrf_token"))
    referral = db.get_referral(ref_id)
    if not referral:
        abort(404)
    db.delete_referral(ref_id)
    flash("Referral deleted.", "success")
    return redirect(url_for("cases.detail", case_id=referral["case_id"]))
