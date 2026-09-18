import re

from app import db
from app.constants import DEFAULT_THEME_BACKGROUND_COLOR, DEFAULT_THEME_PRIMARY_COLOR

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_valid_hex_color(value):
    return bool(value and HEX_COLOR_RE.match(value))


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _mix(color_a, color_b, weight_b):
    """Blend color_a with color_b, weighting color_b by weight_b (0..1)."""
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    return _rgb_to_hex(a[i] * (1 - weight_b) + b[i] * weight_b for i in range(3))


def resolve_theme():
    """Reads the admin-customizable primary/background colors (Settings > Theme) and derives
    the remaining tokens from them, so a custom theme always stays internally consistent —
    there's no separate accent/border setting that could fall out of sync with it."""
    primary = db.get_setting("theme_primary_color", DEFAULT_THEME_PRIMARY_COLOR)
    background = db.get_setting("theme_background_color", DEFAULT_THEME_BACKGROUND_COLOR)
    if not is_valid_hex_color(primary):
        primary = DEFAULT_THEME_PRIMARY_COLOR
    if not is_valid_hex_color(background):
        background = DEFAULT_THEME_BACKGROUND_COLOR

    return {
        "primary": primary,
        "background": background,
        "accent": _mix(primary, "#ffffff", 0.88),
        "border": _mix(background, "#1f2933", 0.12),
    }


def render_theme_css(theme):
    return (
        ":root {\n"
        f"  --brand: {theme['primary']};\n"
        f"  --bg: {theme['background']};\n"
        f"  --accent: {theme['accent']};\n"
        f"  --border: {theme['border']};\n"
        "}\n"
    )
