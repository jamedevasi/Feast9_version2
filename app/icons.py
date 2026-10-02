"""Inline SVG icons for templates: {{ icon('calendar') }}.

The icons live in app/static/icons/ (see its README) as the inner markup of a 24x24 stroke
icon. They are inlined into the page rather than referenced by URL, so they need no extra
request, inherit the surrounding text colour (stroke="currentColor"), and stay within the
CSP (inline SVG is markup, not script)."""
import pathlib

from markupsafe import Markup

_ICON_DIR = pathlib.Path(__file__).parent / "static" / "icons"
_ICONS = {path.stem: path.read_text(encoding="utf-8").strip() for path in _ICON_DIR.glob("*.svg")}


def icon(name):
    """Decorative (aria-hidden): every icon sits next to the words that say what it means."""
    return Markup(
        f'<svg class="icon icon-{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>'
    )
