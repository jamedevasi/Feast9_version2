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

# Standard dental case types shipped with the app (user request 2026-09-23) — added on startup
# by db._seed_standard_procedure_types wherever the name is missing, so a fresh install is
# usable immediately. Admins still manage the list under Settings > Case Types; a type they
# deactivate stays deactivated (it's matched by name, active or not). The first seven match
# the names the demo data and early installs already used, so no case is orphaned.
STANDARD_PROCEDURE_TYPES = [
    "Consultation",
    "Scaling",
    "Filling",
    "Root Canal Treatment",
    "Crown",
    "Extraction",
    "Implant",
    "Dental X-ray (IOPA)",
    "OPG (Full-mouth X-ray)",
    "Deep Cleaning (Root Planing)",
    "Re-Root Canal Treatment",
    "Pulpotomy",
    "Pulpectomy",
    "Post & Core",
    "Bridge",
    "Inlay / Onlay",
    "Veneers",
    "Surgical Extraction",
    "Wisdom Tooth Surgery",
    "Complete Denture",
    "Partial Denture",
    "Orthodontic Treatment (Braces)",
    "Clear Aligners",
    "Retainer",
    "Teeth Whitening",
    "Gum Surgery",
    "Frenectomy",
    "Fluoride Application",
    "Pit & Fissure Sealant",
    "Space Maintainer",
    "Night Guard",
    "Biopsy",
]

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
# Existing = recording a historic finding — e.g. work already done at another clinic, or
# whatever was already there before this system started charting the patient — not something
# being actioned now. Planned = future treatment (optionally given a target "Planned By" date,
# see planned_date below, and linkable to the case's follow-up). Ongoing = an actively
# in-progress multi-visit treatment; a later visit logs a new Completed entry once it's done —
# Ongoing itself never transitions in place, per the append-only design. Completed = done.
# The badge for each is colored via CSS class (badge-status-<status>, app/static/style.css),
# same as every other status badge in the app — not a second Python-side color table.
CHART_STATUSES = ["Existing", "Planned", "Ongoing", "Completed"]

# Findings that represent an active, unresolved clinical problem — as opposed to Sound,
# Restoration, Crown, Root Canal, Implant and Missing/Extracted, which describe either a
# healthy tooth or dental work that's already done. Drives the chart's severity colour-coding
# (app/validators.py:chart_entry_severity) — the *only* colour language on the dental chart:
# the tooth squares, summary tiles and Chart History all use it. The squares used to have a
# separate per-finding colour table too, which the page's 3-colour severity legend didn't
# explain (a Planned Crown showed amber) — dropped in favour of severity alone (user request
# 2026-09-23); a tooth's findings are still in its hover title and the selected-tooth panel.
CHART_PROBLEM_FINDINGS = {"Caries", "Fracture", "Other"}

CHART_SEVERITIES = ["attention", "scheduled", "stable"]
CHART_SEVERITY_LABELS = {
    "attention": "Needs Attention",
    "scheduled": "Scheduled / In Progress",
    "stable": "Stable",
}

# Login screen customisation (§5.12) — fallbacks used until an admin sets a custom
# value in Settings > Login Screen. login_image_filename has no text default; its
# fallback is the bundled static/img/saint_apollonia.png file instead.
DEFAULT_LOGIN_HEADING = "Feast9"
DEFAULT_LOGIN_TAGLINE = "Patient & case management — please log in."

# Clinic Details (§4 "settings (key-value)" schema, §5.13 Settings section) — clinic_name
# falls back to the app name everywhere it's shown (nav bar brand, PDF letterheads);
# address/phone/email have no fallback and are simply omitted when blank.
DEFAULT_CLINIC_NAME = "Feast9"

# Theme (customizable app-wide colour scheme, user request 2026-09-18). Default is a light
# apple-green-and-white combination; an admin can override either value in Settings > Theme.
# Accent/border shades are derived from these two at render time (see app/theme.py) rather
# than stored, so there's no way for them to drift out of sync with a custom primary/background.
DEFAULT_THEME_PRIMARY_COLOR = "#0f766e"
DEFAULT_THEME_BACKGROUND_COLOR = "#f5f7f8"

# Prescriptions: each medicine row states the generic name, strength, dosage, frequency and
# route of administration (the particulars a prescription must legally carry).
MAX_PRESCRIPTION_MEDICINES = 8
PRESCRIPTION_ROUTES = [
    "Oral", "Topical / local application", "Mouth rinse", "Sublingual",
    "Intramuscular (IM)", "Intravenous (IV)", "Subcutaneous", "Inhalation", "Other",
]
# Suggestions only (a datalist) — the frequency field accepts any text.
PRESCRIPTION_FREQUENCIES = [
    "Once a day", "Twice a day", "Three times a day", "Four times a day",
    "Every 6 hours", "Every 8 hours", "At bedtime", "When needed (SOS)", "Single dose",
]
