from datetime import date, timedelta

from app import db
from app.validators import chart_entry_severity
from tests.conftest import get_csrf
from tests.test_cases import _create_case


def _add_entry(client, patient_id, **overrides):
    token = get_csrf(client, f"/patients/{patient_id}/dental-chart")
    data = {
        "tooth_id": "11", "surface": "Mesial", "finding": "Caries",
        "status": "Ongoing", "notes": "", "case_id": "", "csrf_token": token,
    }
    data.update(overrides)
    return client.post(f"/patients/{patient_id}/dental-chart", data=data)


def test_add_entry_appears_in_current_chart(logged_in_client, patient_id):
    resp = _add_entry(logged_in_client, patient_id)
    assert resp.status_code == 302

    chart = db.get_current_dental_chart(patient_id)
    assert "11" in chart
    assert chart["11"][0]["finding"] == "Caries"
    assert chart["11"][0]["dentition"] == "Permanent"


def test_primary_tooth_dentition_computed_correctly(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="55", surface="Whole Tooth", finding="Sound")
    chart = db.get_current_dental_chart(patient_id)
    assert chart["55"][0]["dentition"] == "Primary"


def test_whole_tooth_finding_forces_surface_regardless_of_submission(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="26", surface="Mesial", finding="Crown", status="Completed")
    chart = db.get_current_dental_chart(patient_id)
    assert chart["26"][0]["surface"] == "Whole Tooth"


def test_missing_tooth_supersedes_older_surface_findings(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="36", surface="Mesial", finding="Caries")
    _add_entry(logged_in_client, patient_id, tooth_id="36", surface="Distal", finding="Restoration")
    _add_entry(logged_in_client, patient_id, tooth_id="36", surface="Whole Tooth", finding="Missing/Extracted", status="Completed")

    chart = db.get_current_dental_chart(patient_id)
    assert len(chart["36"]) == 1
    assert chart["36"][0]["finding"] == "Missing/Extracted"

    # The append-only history still has all three — nothing was overwritten or deleted.
    history = db.list_dental_chart_entries(patient_id)
    assert len(history) == 3


def test_new_entry_for_same_tooth_and_surface_supersedes_without_deleting_history(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="14", surface="Occlusal/Incisal", finding="Caries", status="Ongoing")
    _add_entry(logged_in_client, patient_id, tooth_id="14", surface="Occlusal/Incisal", finding="Restoration", status="Completed")

    chart = db.get_current_dental_chart(patient_id)
    assert chart["14"][0]["finding"] == "Restoration"

    history = [e for e in db.list_dental_chart_entries(patient_id) if e["tooth_id"] == "14"]
    assert len(history) == 2
    findings = {e["finding"] for e in history}
    assert findings == {"Caries", "Restoration"}


def test_invalid_tooth_rejected(logged_in_client, patient_id):
    resp = _add_entry(logged_in_client, patient_id, tooth_id="99")
    assert resp.status_code == 200
    assert b"Select a valid tooth" in resp.data
    assert db.list_dental_chart_entries(patient_id) == []


def test_entry_can_be_linked_to_a_case(logged_in_client, patient_id):
    case_resp, _ = _create_case(logged_in_client, patient_id)
    case_id = int(case_resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    _add_entry(logged_in_client, patient_id, tooth_id="46", case_id=str(case_id))
    entry = db.list_dental_chart_entries(patient_id)[0]
    assert entry["case_id"] == case_id


def test_audit_entry_logs_structured_fields_not_notes_content(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="21", notes="Highly sensitive detail")
    entries = [e for e in db.list_audit_log() if e["action"] == "dental_chart_entry_added"]
    assert len(entries) == 1
    assert "tooth=21" in entries[0]["after_summary"]
    assert "Highly sensitive detail" not in entries[0]["after_summary"]


def test_dental_chart_page_requires_login(app, patient_id):
    unauth_client = app.test_client()
    resp = unauth_client.get(f"/patients/{patient_id}/dental-chart")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_dental_chart_link_on_patient_page(logged_in_client, patient_id):
    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert b"Dental Chart" in resp.data


def _history_section(body):
    """The Chart History section only — the SVG chart above it has its own per-tooth <title>
    tooltips ("Tooth 24 · Mesial: Caries ...") that would otherwise collide with these
    assertions, since they mention the same tooth numbers and finding text. Anchored on the
    literal <summary> tag, not just the words "Chart History", since the severity hint above
    also mentions "Chart History" in prose."""
    return body[body.index("<summary>Chart History"):]


def test_chart_history_is_grouped_by_tooth_in_chart_order(logged_in_client, patient_id):
    """Groups follow the same left-to-right order the chart itself is drawn in (PERMANENT_TEETH_UPPER
    lists 12 before 11), not registration order — added 11 first, but 12's group comes first."""
    _add_entry(logged_in_client, patient_id, tooth_id="11", finding="Caries")
    _add_entry(logged_in_client, patient_id, tooth_id="12", finding="Fracture")

    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    history = _history_section(resp.data.decode())
    assert "<h4>Tooth 11 (Permanent)</h4>" in history
    assert "<h4>Tooth 12 (Permanent)</h4>" in history
    assert history.index("<h4>Tooth 12 (Permanent)</h4>") < history.index("<h4>Tooth 11 (Permanent)</h4>")


def test_chart_history_groups_keep_entries_newest_first_within_a_tooth(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="24", surface="Mesial", finding="Caries", status="Existing")
    _add_entry(logged_in_client, patient_id, tooth_id="24", surface="Distal", finding="Restoration", status="Completed")

    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    history = _history_section(resp.data.decode())
    assert history.index("Distal: Restoration") < history.index("Mesial: Caries")


def test_chart_history_does_not_repeat_the_tooth_number_on_every_row(logged_in_client, patient_id):
    """The tooth number/dentition is shown once as the group heading, not on every entry line."""
    _add_entry(logged_in_client, patient_id, tooth_id="24", surface="Mesial", finding="Caries")
    _add_entry(logged_in_client, patient_id, tooth_id="24", surface="Distal", finding="Restoration")

    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    history = _history_section(resp.data.decode())
    assert history.count("Tooth 24") == 1


def test_superseded_entry_is_muted_not_severity_coloured(logged_in_client, patient_id):
    """A later correction for the same tooth+surface supersedes the older entry — the older
    one no longer describes the tooth's current state, so it shouldn't get a severity colour
    (only the summary-counted *current* entry should) — this was the actual bug behind
    "the legend doesn't correlate with the summary" (an old Caries entry stayed red forever,
    even after a newer entry marked that same spot Completed)."""
    _add_entry(logged_in_client, patient_id, tooth_id="24", surface="Mesial", finding="Caries", status="Existing")
    _add_entry(logged_in_client, patient_id, tooth_id="24", surface="Mesial", finding="Restoration", status="Completed")

    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    history = _history_section(resp.data.decode())
    rows = [row for row in history.split("<li") if "Mesial:" in row]
    assert len(rows) == 2
    newest_row, oldest_row = rows  # newest-first within the group
    assert "Restoration" in newest_row and "dental-severity-stable" in newest_row
    assert "Caries" in oldest_row and "dental-history-superseded" in oldest_row
    assert "Superseded" in oldest_row


def test_severity_summary_counts_only_current_entries(logged_in_client, patient_id):
    """Two entries for the same tooth+surface (one superseding the other) must only ever
    contribute one count to the summary — the newer one's severity, not both."""
    _add_entry(logged_in_client, patient_id, tooth_id="24", surface="Mesial", finding="Caries", status="Existing")
    _add_entry(logged_in_client, patient_id, tooth_id="24", surface="Mesial", finding="Restoration", status="Completed")

    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    body = resp.data.decode()
    assert "1 Stable" in body
    assert "0 Needs Attention" in body


def test_existing_status_is_accepted(logged_in_client, patient_id):
    resp = _add_entry(logged_in_client, patient_id, tooth_id="17", finding="Sound", status="Existing")
    assert resp.status_code == 302
    chart = db.get_current_dental_chart(patient_id)
    assert chart["17"][0]["status"] == "Existing"


# Severity is derived from finding + status (app/validators.py:chart_entry_severity), not a
# flat per-status colour — see app/constants.py:CHART_PROBLEM_FINDINGS for why.
def test_severity_completed_is_always_stable_regardless_of_finding():
    assert chart_entry_severity("Caries", "Completed") == "stable"
    assert chart_entry_severity("Sound", "Completed") == "stable"


def test_severity_untreated_problem_finding_needs_attention():
    for status in ("Existing", "Planned", "Ongoing"):
        assert chart_entry_severity("Caries", status) == "attention"
        assert chart_entry_severity("Fracture", status) == "attention"


def test_severity_non_problem_finding_existing_is_stable():
    assert chart_entry_severity("Sound", "Existing") == "stable"
    assert chart_entry_severity("Crown", "Existing") == "stable"


def test_severity_non_problem_finding_planned_or_ongoing_is_scheduled():
    assert chart_entry_severity("Crown", "Planned") == "scheduled"
    assert chart_entry_severity("Implant", "Ongoing") == "scheduled"


def test_dental_chart_page_shows_severity_summary_and_legend(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="11", finding="Caries", status="Existing")
    _add_entry(logged_in_client, patient_id, tooth_id="12", finding="Crown", status="Planned")
    _add_entry(logged_in_client, patient_id, tooth_id="13", finding="Restoration", status="Completed")

    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    body = resp.data.decode()
    assert "1 Needs Attention" in body
    assert "1 Scheduled / In Progress" in body
    assert "1 Stable" in body
    assert "dental-severity-attention" in body
    assert "dental-severity-scheduled" in body
    assert "dental-severity-stable" in body


def test_severity_overdue_planned_entry_needs_attention():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert chart_entry_severity("Crown", "Planned", yesterday) == "attention"
    assert chart_entry_severity("Crown", "Planned", tomorrow) == "scheduled"
    # Only a still-Planned entry can be "overdue" — once it's Ongoing/Completed the date is moot.
    assert chart_entry_severity("Crown", "Ongoing", yesterday) == "scheduled"
    assert chart_entry_severity("Crown", "Completed", yesterday) == "stable"


def test_planned_date_is_stored(logged_in_client, patient_id):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    _add_entry(logged_in_client, patient_id, tooth_id="24", status="Planned", planned_date=tomorrow)
    entry = db.list_dental_chart_entries(patient_id)[0]
    assert entry["planned_date"] == tomorrow


def test_set_as_followup_requires_case_and_planned_date(logged_in_client, patient_id):
    resp = _add_entry(logged_in_client, patient_id, tooth_id="24", status="Planned", set_as_followup="on")
    assert resp.status_code == 200
    assert b"Select a Related Case" in resp.data
    assert b"Set a Planned By date" in resp.data
    assert db.list_dental_chart_entries(patient_id) == []


def test_set_as_followup_updates_the_linked_case(logged_in_client, patient_id):
    case_resp, _ = _create_case(logged_in_client, patient_id)
    case_id = int(case_resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    target_date = (date.today() + timedelta(days=5)).isoformat()

    resp = _add_entry(
        logged_in_client, patient_id, tooth_id="24", finding="Crown", status="Planned",
        case_id=str(case_id), planned_date=target_date, set_as_followup="on",
    )
    assert resp.status_code == 302

    case = db.get_case(case_id)
    assert case["follow_up_date"] == target_date
    assert "Tooth 24" in case["next_action_note"]


def test_overdue_planned_entry_shown_in_chart_history(logged_in_client, patient_id):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _add_entry(logged_in_client, patient_id, tooth_id="24", status="Planned", planned_date=yesterday)

    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    body = resp.data.decode()
    assert "Overdue since" in body
    assert "dental-severity-attention" in body


def test_selecting_a_tooth_shows_its_current_entries_panel(logged_in_client, patient_id):
    _add_entry(logged_in_client, patient_id, tooth_id="24", surface="Mesial", finding="Caries", status="Existing")

    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart?tooth=24")
    body = resp.data.decode()
    assert "Tooth 24 — current entries" in body
    assert "Mesial: Caries" in body
    assert "dental-severity-attention" in body


def test_selecting_a_tooth_with_no_entries_says_so(logged_in_client, patient_id):
    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart?tooth=24")
    body = resp.data.decode()
    assert "Tooth 24 — current entries" in body
    assert "No entries yet for this tooth." in body


def test_selecting_a_tooth_highlights_it_in_the_svg(logged_in_client, patient_id):
    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart?tooth=24")
    body = resp.data.decode()
    assert 'stroke="#111" stroke-width="3"' in body


def _tooth_rect(body, tooth_id):
    anchor = body.index(f"?tooth={tooth_id}&")
    return body[anchor:body.index("</rect>", anchor)]


def test_tooth_square_coloured_by_severity_not_finding(logged_in_client, patient_id):
    """A Planned Crown is 'scheduled' severity — the square must use the legend's severity
    colour, not a separate per-finding colour the legend doesn't explain."""
    db.add_dental_chart_entry(patient_id, None, "24", "Whole Tooth", "Crown", "Planned", "")
    body = logged_in_client.get(f"/patients/{patient_id}/dental-chart").data.decode()
    rect = _tooth_rect(body, "24")
    assert 'class="tooth-severity-scheduled"' in rect
    assert "#f1c40f" not in body
    assert "class=" not in _tooth_rect(body, "25")  # no entries -> plain white


def test_tooth_square_takes_most_severe_surface(logged_in_client, patient_id):
    db.add_dental_chart_entry(patient_id, None, "36", "Mesial", "Restoration", "Existing", "")
    db.add_dental_chart_entry(patient_id, None, "36", "Occlusal/Incisal", "Caries", "Existing", "")
    body = logged_in_client.get(f"/patients/{patient_id}/dental-chart").data.decode()
    assert 'class="tooth-severity-attention"' in _tooth_rect(body, "36")


def test_no_tooth_selected_shows_no_selected_tooth_panel(logged_in_client, patient_id):
    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    assert b"current entries" not in resp.data


def test_dental_chart_finding_legend_removed(logged_in_client, patient_id):
    resp = logged_in_client.get(f"/patients/{patient_id}/dental-chart")
    assert b"chart-legend" not in resp.data
