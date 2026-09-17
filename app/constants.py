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

# Admin: full access. Doctor: full clinical + financial access. Receptionist:
# zero access to financial data (payments, costs/balances) — enforced server-side,
# see app/auth.py:financial_access_required.
ROLES = ["admin", "doctor", "receptionist"]
NON_FINANCIAL_ROLES = ["receptionist"]

# DPDP Phase 2 (feast9_v2_agents.md §5.11) — data-rights requests.
DATA_REQUEST_TYPES = ["Access", "Correction", "Erasure", "Withdraw Consent"]
DATA_REQUEST_STATUSES = ["Pending", "In Progress", "Completed", "Rejected"]
DATA_REQUEST_DEADLINE_DAYS = 90
