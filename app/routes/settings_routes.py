import pathlib
import uuid

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import config as app_config
from app import db
from app.auth import current_actor, login_required, role_required
from app.constants import DEFAULT_LOGIN_HEADING, DEFAULT_LOGIN_TAGLINE
from app.csrf import validate_csrf
from app.validators import detect_image_upload_type

# feast9_v2_agents.md §5.12 rule #1 says "from app.config import DATA_DIR must be at the
# top of settings_routes.py" — a flat top-level constant import instead reads app_config.DATA_DIR
# once at import time and goes stale for every test that monkeypatches it afterward (the same
# footgun app/backup.py's backups_dir()/branding_dir() were written to avoid). We import the
# module and read app_config.branding_dir() fresh inside each view instead, which avoids that
# while still satisfying the rule's actual intent (DATA_DIR must be reachable here, not missing
# -> NameError). The public /login-image route itself lives in auth_routes.py, not here — this
# blueprint has url_prefix="/settings", and the login page needs that path unprefixed.

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET", "POST"])
@login_required
@role_required("admin")
def index():
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        form = request.form.get("form")
        if form == "clinic_details":
            _save_clinic_details()
        elif form == "clinic_logo":
            _save_clinic_logo()
        elif form == "login_screen":
            _save_login_screen()
        return redirect(url_for("settings.index"))

    return render_template(
        "settings.html",
        clinic_name=db.get_setting("clinic_name", ""),
        clinic_address=db.get_setting("clinic_address", ""),
        clinic_phone=db.get_setting("clinic_phone", ""),
        clinic_email=db.get_setting("clinic_email", ""),
        login_heading=db.get_setting("login_heading", DEFAULT_LOGIN_HEADING),
        login_tagline=db.get_setting("login_tagline", DEFAULT_LOGIN_TAGLINE),
    )


def _save_clinic_details():
    actor = current_actor()
    db.set_setting("clinic_name", request.form.get("clinic_name", "").strip(), actor=actor)
    db.set_setting("clinic_address", request.form.get("clinic_address", "").strip(), actor=actor)
    db.set_setting("clinic_phone", request.form.get("clinic_phone", "").strip(), actor=actor)
    db.set_setting("clinic_email", request.form.get("clinic_email", "").strip(), actor=actor)
    flash("Clinic details updated.", "success")


def _save_clinic_logo():
    upload = request.files.get("clinic_logo")
    if not upload or not upload.filename:
        flash("Choose an image to upload.", "warning")
        return

    content = upload.read()
    detected = detect_image_upload_type(content[:16])
    if detected is None:
        flash("Unsupported or corrupted image — only JPG, PNG, GIF, and WEBP are accepted.", "warning")
        return

    _mimetype, ext = detected
    filename = f"{uuid.uuid4().hex}.{ext}"
    branding_dir = pathlib.Path(app_config.branding_dir())
    branding_dir.mkdir(parents=True, exist_ok=True)
    (branding_dir / filename).write_bytes(content)
    db.set_setting("login_image_filename", filename, actor=current_actor())
    flash("Clinic logo updated — used on the login page and in the navigation bar.", "success")


def _save_login_screen():
    actor = current_actor()
    db.set_setting("login_heading", request.form.get("login_heading", "").strip(), actor=actor)
    db.set_setting("login_tagline", request.form.get("login_tagline", "").strip(), actor=actor)
    flash("Login screen updated.", "success")
