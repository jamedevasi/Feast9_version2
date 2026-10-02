"""Dental charting (§14 item) — structured data is the source of truth; the chart below is
just a presentation layer built from it. Append-only, like visit notes/prescriptions: a
correction is a new entry, never an edit of an old one."""
from collections import defaultdict

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import db
from app.auth import current_actor, login_required, logs_view
from app.constants import (
    ALL_TEETH,
    CHART_FINDINGS,
    CHART_SEVERITIES,
    CHART_SEVERITY_LABELS,
    CHART_STATUSES,
    PERMANENT_TEETH_LOWER,
    PERMANENT_TEETH_UPPER,
    PRIMARY_TEETH_LOWER,
    PRIMARY_TEETH_UPPER,
    TOOTH_SURFACES,
    WHOLE_TOOTH_FINDINGS,
)
from app.csrf import validate_csrf
from app.validators import chart_entry_severity, normalize_date, today_iso

bp = Blueprint("dental", __name__)


def _get_patient_or_404(patient_id):
    patient = db.get_patient(patient_id)
    if not patient:
        abort(404)
    return patient


@bp.route("/patients/<int:patient_id>/dental-chart", methods=["GET", "POST"])
@login_required
@logs_view("dental_chart_viewed", "patient", "patient_id")
def chart(patient_id):
    patient = _get_patient_or_404(patient_id)
    errors = []

    current_chart = db.get_current_dental_chart(patient_id)
    primary_teeth = set(PRIMARY_TEETH_UPPER + PRIMARY_TEETH_LOWER)
    has_primary_entries = any(tooth_id in primary_teeth for tooth_id in current_chart)
    age = patient.get("computed_age")
    # Defaults to the view that matches the patient — a child (or anyone with primary-tooth
    # entries already on file) starts on Mixed/Paediatric; everyone else starts on Adult. It's
    # just a display filter (both dentitions are always chartable either way, per
    # feast9_v2_agents.md §14) — the viewer can switch it any time via the on-page toggle, and
    # a request can carry its own choice either as ?dentition= (GET, e.g. the toggle links) or
    # a posted dentition_view field (so it survives the redirect after adding an entry).
    default_dentition_view = "mixed" if (has_primary_entries or (age is not None and age < 13)) else "adult"
    requested_view = request.form.get("dentition_view") or request.args.get("dentition", "")
    dentition_view = requested_view if requested_view in ("adult", "mixed") else default_dentition_view

    form_state = {
        "tooth_id": request.args.get("tooth", ""), "surface": "Whole Tooth",
        "finding": "", "status": "Existing", "notes": "", "case_id": "",
        "planned_date": "", "set_as_followup": False,
    }

    if request.method == "POST":
        validate_csrf(request.form.get("csrf_token"))
        tooth_id = request.form.get("tooth_id", "")
        surface = request.form.get("surface", "Whole Tooth")
        finding = request.form.get("finding", "")
        status = request.form.get("status", "Existing")
        notes = request.form.get("notes", "").strip()
        case_id_raw = request.form.get("case_id", "")
        case_id = int(case_id_raw) if case_id_raw.isdigit() else None
        planned_date = normalize_date(request.form.get("planned_date", ""))
        set_as_followup = request.form.get("set_as_followup") == "on"
        form_state = {
            "tooth_id": tooth_id, "surface": surface, "finding": finding,
            "status": status, "notes": notes, "case_id": case_id_raw,
            "planned_date": planned_date, "set_as_followup": set_as_followup,
        }

        if tooth_id not in ALL_TEETH:
            errors.append("Select a valid tooth.")
        if finding not in CHART_FINDINGS:
            errors.append("Select a valid finding.")
        if status not in CHART_STATUSES:
            errors.append("Select a valid status.")
        if surface not in TOOTH_SURFACES:
            errors.append("Select a valid surface.")
        if set_as_followup and not case_id:
            errors.append("Select a Related Case to link this entry to its follow-up.")
        if set_as_followup and not planned_date:
            errors.append("Set a Planned By date to link this entry to a follow-up.")

        if not errors:
            if finding in WHOLE_TOOTH_FINDINGS:
                surface = "Whole Tooth"
            db.add_dental_chart_entry(
                patient_id, case_id, tooth_id, surface, finding, status, notes,
                planned_date=planned_date, actor=current_actor(),
            )
            flash_msg = f"Chart entry added for tooth {tooth_id}."
            if set_as_followup:
                # A hand-set follow-up always replaces whatever the case already had — same
                # rule as every other way of setting one (see db.update_case_followup).
                db.update_case_followup(
                    case_id, planned_date, f"Planned dental treatment — Tooth {tooth_id}: {finding}"
                )
                flash_msg += f" Follow-up set on the linked case for {planned_date}."
            flash(flash_msg, "success")
            return redirect(url_for("dental.chart", patient_id=patient_id, dentition=dentition_view))

    # A practitioner-facing summary, tallied from the tooth's *current* state (one line per
    # tooth/surface, not every historical entry — so a tooth corrected three times over still
    # counts once) rather than the full append-only history. Each entry's severity is also
    # attached here so the selected-tooth panel (dental_chart.html) can colour it the same way.
    severity_counts = {s: 0 for s in CHART_SEVERITIES}
    current_entry_ids = set()
    for entries in current_chart.values():
        for entry in entries:
            entry["severity"] = chart_entry_severity(entry["finding"], entry["status"], entry["planned_date"])
            severity_counts[entry["severity"]] += 1
            current_entry_ids.add(entry["id"])

    # A tooth's square in the SVG takes its most severe current entry's colour — a tooth with
    # caries on one surface and a sound other surface still needs attention.
    tooth_severity = {
        tooth_id: min((e["severity"] for e in entries), key=CHART_SEVERITIES.index)
        for tooth_id, entries in current_chart.items() if entries
    }

    # Only a tooth/surface's *current* entry gets a severity colour in Chart History — an
    # older entry a later correction has superseded no longer describes the tooth's present
    # state, so colouring it too would make the log show far more red/blue/green than the
    # summary counts above, which only tally current state (this was reported as the colours
    # "not correlating" with the summary — an entry from months ago showing green even though
    # nothing about the tooth is currently "stable" is exactly that mismatch).
    history = db.list_dental_chart_entries(patient_id)
    for entry in history:
        entry["is_current"] = entry["id"] in current_entry_ids
        entry["severity"] = (
            chart_entry_severity(entry["finding"], entry["status"], entry["planned_date"])
            if entry["is_current"] else None
        )

    # Grouped by tooth (in the same left-to-right order the chart itself is drawn in) rather
    # than one long chronological list — entries within a tooth's group stay newest-first.
    entries_by_tooth = defaultdict(list)
    for entry in history:
        entries_by_tooth[entry["tooth_id"]].append(entry)
    history_by_tooth = [
        {"tooth_id": t, "dentition": entries_by_tooth[t][0]["dentition"], "entries": entries_by_tooth[t]}
        for t in ALL_TEETH if t in entries_by_tooth
    ]

    return render_template(
        "dental_chart.html",
        patient=patient,
        errors=errors,
        form_state=form_state,
        current_chart=current_chart,
        history=history,
        history_by_tooth=history_by_tooth,
        cases=db.list_cases_for_patient(patient_id),
        teeth_upper_permanent=PERMANENT_TEETH_UPPER,
        teeth_lower_permanent=PERMANENT_TEETH_LOWER,
        teeth_upper_primary=PRIMARY_TEETH_UPPER,
        teeth_lower_primary=PRIMARY_TEETH_LOWER,
        surfaces=TOOTH_SURFACES,
        findings=CHART_FINDINGS,
        statuses=CHART_STATUSES,
        tooth_severity=tooth_severity,
        dentition_view=dentition_view,
        severity_counts=severity_counts,
        severity_labels=CHART_SEVERITY_LABELS,
        today=today_iso(),
    )
