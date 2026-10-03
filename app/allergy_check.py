"""Checks a prescription's medicines against the patient's recorded allergies.

A ticked allergy (constants.ALLERGY_DRUGS) matches by its family's name fragments
(constants.ALLERGY_DRUG_MATCHES), so 'Penicillin' catches amoxicillin. The free-text
'other allergies' box is split into its items; each matches a medicine whose name contains
it (or that it contains), and an item naming a family — "penicillins", "NSAIDs" — also
brings in that family's fragments. This is a safety net, not a full drug database: a miss is
possible, so the allergy banner stays on the page either way."""
import json
import re

from app.constants import ALLERGY_DRUG_MATCHES

_MIN_FREE_TEXT = 4  # shorter items ("no", "nil", "dust") would match by accident or not at all
_NO_ALLERGY = {"none", "nil", "nkda", "no known allergies", "no known drug allergies", "not known"}


# Words in the free-text box that name a whole family rather than one medicine.
_FAMILY_WORDS = {
    "Penicillin": ["penicillin"],
    "Local Anesthetic": ["anesthe", "anaesthe"],
    "Aspirin / NSAIDs": ["aspirin", "nsaid"],
    "Sulfa Drugs": ["sulfa", "sulpha"],
}


def _family_for(item):
    """The allergy family a free-text item names, if any (e.g. 'penicillins' -> Penicillin,
    'lignocaine' -> Local Anesthetic)."""
    item = item.lower()
    for family, fragments in ALLERGY_DRUG_MATCHES.items():
        words = _FAMILY_WORDS.get(family, []) + [f for f in fragments if len(f) >= _MIN_FREE_TEXT]
        if any(w in item for w in words):
            return family
    return None


def recorded_allergies(patient):
    """[(label shown to the doctor, [name fragments])] for this patient."""
    rules = []
    try:
        ticked = json.loads(patient.get("allergies_json") or "[]")
    except ValueError:
        ticked = []
    for family in ticked:
        rules.append((family, ALLERGY_DRUG_MATCHES.get(family, [])))
    for item in re.split(r"[,;/\n]| and ", patient.get("allergies_other") or ""):
        item = item.strip()
        if len(item) < _MIN_FREE_TEXT or item.lower() in _NO_ALLERGY:
            continue
        family = _family_for(item)
        fragments = [item.lower()] + (ALLERGY_DRUG_MATCHES[family] if family else [])
        rules.append((item, fragments))
    return rules


def conflicts(patient, medications, numbers=None):
    """[(medicine number, medicine name, allergy label)] — every medicine that may conflict.
    `numbers` are the medicines' on-screen row numbers (default 1, 2, 3...)."""
    rules = recorded_allergies(patient)
    found = []
    for number, med in zip(numbers or range(1, len(medications) + 1), medications):
        names = [n.strip().lower() for n in (med.get("generic", ""), med.get("brand", "")) if n.strip()]
        for label, fragments in rules:
            if any(f in name or (len(name) >= _MIN_FREE_TEXT and name in f)
                   for name in names for f in fragments):
                found.append((number, med.get("generic") or med.get("brand"), label))
                break
    return found
