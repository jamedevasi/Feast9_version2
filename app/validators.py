import re
from datetime import date, datetime

from app.constants import CHART_PROBLEM_FINDINGS

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
    Content is validated by magic bytes, never by the client-supplied filename/extension.
    Scoped to clinical attachments (JPG/PNG/PDF only) — see detect_image_upload_type for the
    broader image set (adds GIF/WEBP) used by login-screen branding uploads."""
    for signature, result in _MAGIC_BYTES.items():
        if header_bytes.startswith(signature):
            return result
    return None


_IMAGE_MAGIC_BYTES = {
    b"\xff\xd8": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"GIF87a": ("image/gif", "gif"),
    b"GIF89a": ("image/gif", "gif"),
}


def detect_image_upload_type(header_bytes):
    """Same magic-bytes principle as detect_upload_type, but for plain image uploads
    (JPG/PNG/GIF/WEBP) — used by login-screen branding, not clinical attachments."""
    for signature, result in _IMAGE_MAGIC_BYTES.items():
        if header_bytes.startswith(signature):
            return result
    # WEBP's signature straddles a variable-length size field (RIFF + 4-byte size + "WEBP"),
    # so it can't be a fixed-prefix dict entry like the others.
    if header_bytes[:4] == b"RIFF" and header_bytes[8:12] == b"WEBP":
        return ("image/webp", "webp")
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


def chart_entry_severity(finding, status, planned_date=""):
    """Derives a dental chart entry's severity from its finding + status (+ an optional
    "Planned By" target date), for colour-coding the chart history — see
    app/constants.py:CHART_PROBLEM_FINDINGS for why this is severity-based rather than a
    flat per-status colour.

    - stable: treatment is Completed (any finding), or it's an Existing, non-problem finding
      (a healthy tooth, or dental work already done — possibly at another clinic, before this
      one started charting) — nothing to act on.
    - attention: a problem finding (Caries/Fracture/Other) that isn't Completed yet — whether
      it's Existing, Planned or Ongoing, it still represents untreated disease — OR a Planned
      entry whose target date has passed without being marked Ongoing/Completed.
    - scheduled: anything else — a non-problem finding that's Planned or Ongoing (e.g. an
      elective crown, or a multi-visit treatment in progress that will end in Completed).
    """
    if status == "Completed":
        return "stable"
    if status == "Planned" and planned_date and planned_date < today_iso():
        return "attention"
    if finding in CHART_PROBLEM_FINDINGS:
        return "attention"
    return "stable" if status == "Existing" else "scheduled"
