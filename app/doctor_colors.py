"""Calendar colours for doctors. Appointments are told apart only by the doctor's colour dot,
so two doctors with near-identical colours make the calendar hard to read. A new doctor is
offered the palette colour least like the existing doctors', and saving a colour too close
to another active doctor's gives a warning (it is still saved — the admin decides)."""

# Distinct on a white page and on the calendar's status badges.
PALETTE = [
    "#1c7ed6",  # blue
    "#2f9e44",  # green
    "#e8590c",  # orange
    "#ae3ec9",  # purple
    "#c92a2a",  # red
    "#0c8599",  # teal
    "#f08c00",  # amber
    "#5f3dc4",  # indigo
    "#d6336c",  # pink
    "#5c940d",  # olive
    "#8d5524",  # brown
    "#495057",  # dark grey
]

# Below this, two colours read as "the same" at dot size: the old default blue #2b6cb0 and
# #1c7ed6 are 77 apart; the closest pair in PALETTE (red / pink) is 102.
TOO_SIMILAR = 90


def _rgb(color):
    color = (color or "").lstrip("#")
    if len(color) != 6:
        return None
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def distance(a, b):
    """Perceptual-ish distance between two #rrggbb colours ("redmean" weighted RGB); None if
    either isn't a valid colour."""
    ca, cb = _rgb(a), _rgb(b)
    if ca is None or cb is None:
        return None
    mean_r = (ca[0] + cb[0]) / 2
    dr, dg, db_ = ca[0] - cb[0], ca[1] - cb[1], ca[2] - cb[2]
    return ((2 + mean_r / 256) * dr * dr + 4 * dg * dg + (2 + (255 - mean_r) / 256) * db_ * db_) ** 0.5


def suggest(doctors):
    """The palette colour furthest from every listed doctor's colour (the first unused one
    when there's room)."""
    taken = [d["color"] for d in doctors if _rgb(d.get("color"))]
    if not taken:
        return PALETTE[0]
    return max(PALETTE, key=lambda c: min(distance(c, t) for t in taken))


def similar_to(color, doctors, exclude_id=None):
    """Names of the listed doctors whose colour is too close to `color`."""
    return [
        d["name"] for d in doctors
        if d["id"] != exclude_id and (dist := distance(color, d.get("color"))) is not None and dist < TOO_SIMILAR
    ]
