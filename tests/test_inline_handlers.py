import pathlib
import re

from tests.conftest import get_csrf

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"

# script-src 'self' (app/__init__.py) silently blocks inline event handlers — an
# onsubmit="return confirm(...)" never runs, so the form submits with no prompt at all.
INLINE_HANDLER = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)


def test_no_template_uses_inline_event_handlers():
    offenders = [
        f"{path.relative_to(TEMPLATES)}:{lineno}"
        for path in TEMPLATES.rglob("*.html")
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if INLINE_HANDLER.search(line)
    ]
    assert offenders == [], f"inline event handlers (blocked by CSP): {offenders}"


def test_confirm_script_loaded_and_destructive_form_marked(logged_in_client, patient_id):
    from tests.test_cases import _create_case

    resp, _ = _create_case(logged_in_client, patient_id)
    body = logged_in_client.get(resp.headers["Location"]).data.decode()
    assert "/static/ui_actions.js" in body
    assert 'data-confirm="Close this case?' in body
    assert "onsubmit=" not in body
