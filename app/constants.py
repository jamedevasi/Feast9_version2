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

# Admin: full access. Doctor: full clinical + financial access. Receptionist:
# zero access to financial data (payments, costs/balances) — enforced server-side,
# see app/auth.py:financial_access_required.
ROLES = ["admin", "doctor", "receptionist"]
NON_FINANCIAL_ROLES = ["receptionist"]
