import json

from app.allergy_check import conflicts


def _patient(ticked=(), other=""):
    return {"allergies_json": json.dumps(list(ticked)), "allergies_other": other}


def _meds(*names):
    return [{"generic": g, "brand": b} for g, b in (n if isinstance(n, tuple) else (n, "") for n in names)]


def test_ticked_allergies_match_their_whole_family():
    assert conflicts(_patient(["Penicillin"]), _meds("Amoxicillin", "Metronidazole")) == [(1, "Amoxicillin", "Penicillin")]
    assert conflicts(_patient(["Penicillin"]), _meds(("Amoxicillin + Clavulanic acid", "Augmentin")))
    assert conflicts(_patient(["Local Anesthetic"]), _meds("Lignocaine with adrenaline", "Articaine"))[1][1] == "Articaine"
    nsaids = conflicts(_patient(["Aspirin / NSAIDs"]), _meds("Paracetamol", "Ibuprofen", "Aceclofenac", "Etoricoxib"))
    assert [n for n, _name, _a in nsaids] == [2, 3, 4]  # paracetamol is not an NSAID
    assert conflicts(_patient(["Sulfa Drugs"]), _meds("Co-trimoxazole"))
    assert conflicts(_patient(["Latex"]), _meds("Amoxicillin")) == []


def test_brand_name_is_checked_too():
    assert conflicts(_patient(["Penicillin"]), _meds(("", "Augmentin 625")))


def test_free_text_allergies_match_by_name_and_by_family():
    found = conflicts(_patient(other="Penicillins, metronidazole"), _meds("Amoxicillin", "Metronidazole", "Paracetamol"))
    assert found == [(1, "Amoxicillin", "Penicillins"), (2, "Metronidazole", "metronidazole")]
    assert conflicts(_patient(other="Local anaesthetic"), _meds("Articaine"))
    assert conflicts(_patient(other="lignocaine"), _meds("Lidocaine"))  # same family
    assert conflicts(_patient(other="NSAIDs"), _meds("Diclofenac"))


def test_free_text_that_is_not_an_allergy_matches_nothing():
    assert conflicts(_patient(other="None"), _meds("Nonacog")) == []
    assert conflicts(_patient(other="nil; NKDA"), _meds("Amoxicillin")) == []
    assert conflicts(_patient(other="some drugs"), _meds("Co-trimoxazole")) == []


def test_on_screen_row_numbers_are_used():
    assert conflicts(_patient(["Penicillin"]), _meds("Amoxicillin"), numbers=[3]) == [(3, "Amoxicillin", "Penicillin")]
