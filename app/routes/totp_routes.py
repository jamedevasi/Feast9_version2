import io

import qrcode
import qrcode.image.svg

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import db
from app.auth import (
    current_actor,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    login_required,
    reauth_required,
    totp_provisioning_uri,
    verify_totp_code,
)
from app.csrf import validate_csrf

bp = Blueprint("totp", __name__, url_prefix="/totp")


def _qr_svg(uri):
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


@bp.route("/setup", methods=["GET", "POST"])
@login_required
def setup():
    user = db.get_user_by_id(session["admin_id"])
    if user["totp_enabled"]:
        flash("Two-factor authentication is already enabled on your account.", "warning")
        return redirect(url_for("dashboard.index"))

    secret = user["totp_secret"] or generate_totp_secret()
    if not user["totp_secret"]:
        db.set_pending_totp_secret(user["id"], secret)

    errors = []
    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        code = request.form.get("code", "").strip()
        if verify_totp_code(secret, code):
            codes = generate_recovery_codes()
            db.enable_totp(user["id"], [hash_recovery_code(c) for c in codes], actor=current_actor())
            session["recovery_codes_to_show"] = codes
            return redirect(url_for("totp.recovery_codes"))
        errors.append("That code didn't match. Check your app's time sync and try again.")

    uri = totp_provisioning_uri(secret, user["username"])
    return render_template("totp_setup.html", errors=errors, secret=secret, qr_svg=_qr_svg(uri))


@bp.route("/recovery-codes")
@login_required
def recovery_codes():
    codes = session.pop("recovery_codes_to_show", None)
    if not codes:
        return redirect(url_for("dashboard.index"))
    return render_template("totp_recovery_codes.html", codes=codes)


@bp.route("/disable", methods=["POST"])
@login_required
@reauth_required
def disable():
    validate_csrf(request.form.get("csrf_token"))
    db.reset_totp(session["admin_id"], actor=current_actor())
    flash("Two-factor authentication disabled on your account.", "success")
    return redirect(url_for("dashboard.index"))
