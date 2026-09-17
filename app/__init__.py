import os

from flask import Flask, render_template

from app import config as app_config
from app import db as db_module
from app.csrf import generate_csrf_token


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = app_config.SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

    if app_config.SECRET_KEY == app_config.DEFAULT_SECRET_KEY:
        app.logger.warning(
            "SECRET_KEY is using the insecure default — set the SECRET_KEY "
            "environment variable before deploying."
        )

    db_module.init_db()

    app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB — clinical attachments are small files

    from app.routes.analytics_routes import bp as analytics_bp
    from app.routes.appointment_routes import bp as appointment_bp
    from app.routes.audit_routes import bp as audit_bp
    from app.routes.auth_routes import bp as auth_bp
    from app.routes.backup_routes import bp as backup_bp
    from app.routes.case_routes import bp as case_bp
    from app.routes.clinical_routes import bp as clinical_bp
    from app.routes.dashboard_routes import bp as dashboard_bp
    from app.routes.dental_routes import bp as dental_bp
    from app.routes.doctor_routes import bp as doctor_bp
    from app.routes.dpdp_routes import bp as dpdp_bp
    from app.routes.import_routes import bp as import_bp
    from app.routes.patient_routes import bp as patient_bp
    from app.routes.procedure_type_routes import bp as procedure_type_bp
    from app.routes.reports_routes import bp as reports_bp
    from app.routes.settings_routes import bp as settings_bp
    from app.routes.totp_routes import bp as totp_bp
    from app.routes.user_routes import bp as user_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(case_bp)
    app.register_blueprint(clinical_bp)
    app.register_blueprint(appointment_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(totp_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(dpdp_bp)
    app.register_blueprint(dental_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(procedure_type_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(import_bp)

    app.jinja_env.globals["csrf_token"] = generate_csrf_token

    _register_context_processors(app)
    _register_error_handlers(app)
    _register_security_headers(app)

    return app


def _register_context_processors(app):
    @app.context_processor
    def inject_current_year():
        from datetime import date
        return {"current_year": date.today().year}

    @app.context_processor
    def inject_clinic_name():
        from app.constants import DEFAULT_CLINIC_NAME
        return {"clinic_name_nav": db_module.get_setting("clinic_name", "") or DEFAULT_CLINIC_NAME}

    @app.context_processor
    def inject_pending_data_requests():
        # feast9_v2_agents.md §5.11: "count_pending_data_requests() injected into every page"
        from flask import session

        from app.auth import can_view_financial_data
        if not session.get("admin_id"):
            return {}
        return {
            "pending_data_requests_count": db_module.count_pending_data_requests(),
            "can_view_financial_nav": can_view_financial_data(),
        }


def _register_security_headers(app):
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'"
        )
        return response


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(_e):
        return render_template(
            "error.html", error_code=404, error_title="Page Not Found",
            error_message="The page you're looking for doesn't exist.",
        ), 404

    @app.errorhandler(500)
    def server_error(_e):
        return render_template(
            "error.html", error_code=500, error_title="Something Went Wrong",
            error_message="An unexpected error occurred. Please try again.",
        ), 500

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template(
            "error.html", error_code=403, error_title="Access Denied",
            error_message="You don't have permission to view this page.",
        ), 403
