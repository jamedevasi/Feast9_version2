from flask import Blueprint, render_template, request

from app import db
from app.auth import login_required, role_required

bp = Blueprint("audit", __name__, url_prefix="/audit-log")

# (query value, label) — "" is everything.
CATEGORIES = [("", "All"), ("changes", "Changes"), ("views", "Records opened"), ("signins", "Sign-ins")]


@bp.route("/")
@login_required
@role_required("admin")
def list_view():
    category = request.args.get("show", "")
    if category not in {value for value, _label in CATEGORIES}:
        category = ""
    return render_template(
        "audit_log.html", entries=db.list_audit_log(category=category or None),
        categories=CATEGORIES, current_category=category,
    )
