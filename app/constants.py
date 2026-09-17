SEX_OPTIONS = ["Male", "Female"]

# Representative list for a dental clinic — not specified in the spec, easy to extend.
# medical_conditions_other / allergies_other on the patient record cover anything missing.
MEDICAL_CONDITIONS = [
    "Diabetes",
    "Hypertension",
    "Cardiac Condition",
    "Asthma",
    "Bleeding Disorder",
    "Thyroid Disorder",
    "Epilepsy",
    "Hepatitis / Liver Disease",
]

ALLERGY_DRUGS = [
    "Penicillin",
    "Local Anesthetic",
    "Latex",
    "Aspirin / NSAIDs",
    "Sulfa Drugs",
]

ATTACHMENT_TYPES = ["X-ray", "Clinical Photo", "Lab Report", "Other"]

LAB_REQ_STATUSES = ["Sent", "Received", "Delayed"]

APPOINTMENT_STATUSES = ["Scheduled", "Completed", "Cancelled", "No-show"]

# Recurring appointments (§14 item). Schema direction is fixed (is_recurring/recur_interval/
# recur_until columns), but the interaction design was explicitly left open (§15) — a bounded
# set of real appointment rows is generated up front, each tagged with the same series_id, so
# exceptions/no-shows/conflict-detection all fall out of the existing per-appointment machinery
# for free instead of needing a separate virtual-recurrence engine.
RECURRENCE_INTERVALS = ["Weekly", "Biweekly", "Monthly"]
MAX_RECURRING_OCCURRENCES = 52

# Bulk patient import (§2/§3 excel_import.py — "Bulk 8,000-row xlsx import").
MAX_IMPORT_ROWS = 8000

# Admin: full access. Doctor: full clinical + financial access. Receptionist:
# zero access to financial data (payments, costs/balances) — enforced server-side,
# see app/auth.py:financial_access_required.
ROLES = ["admin", "doctor", "receptionist"]
NON_FINANCIAL_ROLES = ["receptionist"]

# DPDP Phase 2 (feast9_v2_agents.md §5.11) — data-rights requests.
DATA_REQUEST_TYPES = ["Access", "Correction", "Erasure", "Withdraw Consent"]
DATA_REQUEST_STATUSES = ["Pending", "In Progress", "Completed", "Rejected"]
DATA_REQUEST_DEADLINE_DAYS = 90

# Dental charting (§14 item) — FDI/ISO 3950 notation. Permanent: quadrants 1-4 (11-48).
# Primary/deciduous: quadrants 5-8 (51-85). Ordered left-to-right as conventionally drawn
# ("as if facing the patient" — the patient's right side appears on the left of the chart).
PERMANENT_TEETH_UPPER = ["18", "17", "16", "15", "14", "13", "12", "11",
                          "21", "22", "23", "24", "25", "26", "27", "28"]
PERMANENT_TEETH_LOWER = ["48", "47", "46", "45", "44", "43", "42", "41",
                          "31", "32", "33", "34", "35", "36", "37", "38"]
PRIMARY_TEETH_UPPER = ["55", "54", "53", "52", "51", "61", "62", "63", "64", "65"]
PRIMARY_TEETH_LOWER = ["85", "84", "83", "82", "81", "71", "72", "73", "74", "75"]
ALL_TEETH = PERMANENT_TEETH_UPPER + PERMANENT_TEETH_LOWER + PRIMARY_TEETH_UPPER + PRIMARY_TEETH_LOWER

TOOTH_SURFACES = ["Whole Tooth", "Mesial", "Distal", "Buccal/Facial", "Lingual/Palatal", "Occlusal/Incisal"]

# Findings that describe the whole tooth, never a single surface — the route forces
# surface="Whole Tooth" for these regardless of what was submitted.
WHOLE_TOOTH_FINDINGS = {"Missing/Extracted", "Crown", "Root Canal", "Implant"}
CHART_FINDINGS = ["Sound", "Caries", "Restoration", "Crown", "Root Canal", "Implant",
                   "Missing/Extracted", "Fracture", "Other"]
CHART_STATUSES = ["Existing", "Planned", "Completed"]

# Login screen customisation (§5.12) — fallbacks used until an admin sets a custom
# value in Settings > Login Screen. login_image_filename has no text default; its
# fallback is the bundled static/img/saint_apollonia.png file instead.
DEFAULT_LOGIN_HEADING = "Feast9"
DEFAULT_LOGIN_TAGLINE = "Patient & case management — please log in."

# Presentation only (SVG is a presentation layer, never the source of truth — feast9_v2_agents.md §14).
CHART_FINDING_COLORS = {
    "Sound": "#e9f7ef",
    "Caries": "#e74c3c",
    "Restoration": "#3498db",
    "Crown": "#f1c40f",
    "Root Canal": "#9b59b6",
    "Implant": "#1abc9c",
    "Missing/Extracted": "#95a5a6",
    "Fracture": "#e67e22",
    "Other": "#bdc3c7",
}
