"""Google sign-in (§14) — the Authlib OIDC client. Registered unconditionally at app
creation (registration just stores config, it never calls out to Google), but every
route that actually uses it checks app_config.google_signin_enabled() first and 404s
if Google isn't configured — see app/routes/google_auth_routes.py.

Authlib's authorize_redirect()/authorize_access_token() pair handles every validation
step §14 requires without any hand-rolled JWT code: state (CSRF) and nonce (replay) are
auto-generated whenever the scope includes "openid" and round-tripped through the
session; authorize_access_token() then validates the returned ID token's issuer,
audience, signature (via the provider's published JWKS), expiry, and that same nonce
before token["userinfo"] is ever populated.
"""
from authlib.integrations.flask_client import OAuth

from app import config as app_config

oauth = OAuth()


def init_google_oauth(app):
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=app_config.GOOGLE_CLIENT_ID or "unconfigured",
        client_secret=app_config.GOOGLE_CLIENT_SECRET or "unconfigured",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},  # identity only — never Gmail/Drive/Calendar/contacts
    )
