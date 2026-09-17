from flask import Blueprint, render_template

from app.auth import login_required, role_required

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/")
@login_required
@role_required("admin")
def index():
    return render_template("settings.html")
