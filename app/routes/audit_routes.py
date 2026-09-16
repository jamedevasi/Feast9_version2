from flask import Blueprint, render_template

from app import db
from app.auth import login_required, role_required

bp = Blueprint("audit", __name__, url_prefix="/audit-log")


@bp.route("/")
@login_required
@role_required("admin")
def list_view():
    return render_template("audit_log.html", entries=db.list_audit_log())
