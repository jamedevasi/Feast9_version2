import re
from datetime import date, datetime

_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


def today_iso():
    return date.today().isoformat()


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_date(value):
    """Return a YYYY-MM-DD string, or '' if blank/invalid."""
    if not value:
        return ""
    value = value.strip()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def is_valid_mobile(value):
    """India-format 10-digit mobile number, optionally prefixed with 91."""
    if not value:
        return False
    digits = re.sub(r"\D", "", value)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return bool(_MOBILE_RE.match(digits))


_MAGIC_BYTES = {
    b"\xff\xd8": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"%PDF": ("application/pdf", "pdf"),
}


def detect_upload_type(header_bytes):
    """Return (mimetype, extension) for a recognised file signature, or None if unrecognised.
    Content is validated by magic bytes, never by the client-supplied filename/extension."""
    for signature, result in _MAGIC_BYTES.items():
        if header_bytes.startswith(signature):
            return result
    return None


def compute_age(date_of_birth):
    """Age in whole years as of today, accounting for whether the birthday has passed this year."""
    if not date_of_birth:
        return None
    try:
        born = date.fromisoformat(date_of_birth)
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
