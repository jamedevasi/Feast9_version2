"""Patients page: by default only patients with an active case (or, for roles allowed to see
money, an outstanding balance); ?view=all shows everyone."""
from datetime import date

from app import db
from tests.conftest import get_csrf, register_patient
from tests.test_cases import _create_case
from tests.test_roles import _create_user, _login, _logout


def _patient(client, name, mobile):
    return register_patient(client, name=name, mobile=mobile)


def _case(client, patient_id, title, total_cost="4000"):
    resp, _doctor_id = _create_case(client, patient_id, title=title, total_cost=total_cost)
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _close(client, case_id):
    token = get_csrf(client, f"/cases/{case_id}")
    client.post(f"/cases/{case_id}/close", data={"csrf_token": token})


def _pay(client, case_id, amount):
    token = get_csrf(client, f"/cases/{case_id}")
    client.post(
        f"/cases/{case_id}/payments",
        data={"payment_date": date.today().isoformat(), "amount": str(amount), "method": "Cash",
              "reference": "", "notes": "", "csrf_token": token},
    )


def _names_on(client, url):
    body = client.get(url).data.decode()
    return {n for n in ("Alpha Active", "Bravo NoCase", "Charlie Settled", "Delta Owing") if n in body}


def _setup_four(client):
    alpha = _patient(client, "Alpha Active", "9876500001")          # active case
    _patient(client, "Bravo NoCase", "9876500002")                   # registered, no case yet
    charlie = _patient(client, "Charlie Settled", "9876500003")      # closed case, paid in full
    delta = _patient(client, "Delta Owing", "9876500004")            # closed case, still owes money
    _case(client, alpha, "Alpha case")
    c_case = _case(client, charlie, "Charlie case")
    _pay(client, c_case, 4000)
    _close(client, c_case)
    d_case = _case(client, delta, "Delta case")
    _pay(client, d_case, 1000)
    _close(client, d_case)


def test_default_list_shows_active_cases_and_pending_payments_only(logged_in_client):
    _setup_four(logged_in_client)
    assert _names_on(logged_in_client, "/patients/") == {"Alpha Active", "Delta Owing"}


def test_show_all_lists_everyone(logged_in_client):
    _setup_four(logged_in_client)
    assert _names_on(logged_in_client, "/patients/?view=all") == {
        "Alpha Active", "Bravo NoCase", "Charlie Settled", "Delta Owing",
    }


def test_closed_case_with_balance_is_included_but_settled_one_is_not(logged_in_client):
    _setup_four(logged_in_client)
    body = logged_in_client.get("/patients/").data.decode()
    assert "Delta Owing" in body and "3000.00" in body      # 4000 billed - 1000 paid
    assert "Charlie Settled" not in body


def test_overpaid_case_does_not_offset_another_cases_debt(logged_in_client):
    pid = _patient(logged_in_client, "Delta Owing", "9876500004")
    owed = _case(logged_in_client, pid, "Owes", total_cost="5000")
    over = _case(logged_in_client, pid, "Overpaid", total_cost="1000")
    _pay(logged_in_client, over, 3000)
    _close(logged_in_client, owed)
    _close(logged_in_client, over)
    body = logged_in_client.get("/patients/").data.decode()
    assert "Delta Owing" in body and "5000.00" in body


def test_active_case_count_column(logged_in_client):
    pid = _patient(logged_in_client, "Alpha Active", "9876500001")
    _case(logged_in_client, pid, "One")
    _case(logged_in_client, pid, "Two")
    row = logged_in_client.get("/patients/").data.decode()
    assert "Active Cases" in row
    assert "<td>2</td>" in row


def test_search_works_within_each_view(logged_in_client):
    _setup_four(logged_in_client)
    # Bravo has no case: invisible in the default view even when searched for by name...
    default = logged_in_client.get("/patients/?q=Bravo").data.decode()
    assert "Bravo NoCase" not in default
    assert "Show all patients" in default and "view=all" in default
    # ...and found once the full view is on
    assert "Bravo NoCase" in logged_in_client.get("/patients/?view=all&q=Bravo").data.decode()


def test_toggle_links_keep_the_search_text(logged_in_client):
    _setup_four(logged_in_client)
    body = logged_in_client.get("/patients/?q=Alpha").data.decode()
    assert "view=all" in body and "q=Alpha" in body
    all_body = logged_in_client.get("/patients/?view=all&q=Alpha").data.decode()
    assert 'name="view" value="all"' in all_body      # the search box stays in the full view


def test_default_view_with_nobody_active_explains_itself(logged_in_client):
    _patient(logged_in_client, "Bravo NoCase", "9876500002")
    body = logged_in_client.get("/patients/").data.decode()
    assert "No patients with an active case or an outstanding balance right now" in body
    assert "Show all patients" in body


def test_receptionist_default_list_ignores_payments_and_shows_no_money(logged_in_client):
    _setup_four(logged_in_client)
    _create_user(logged_in_client, "frontdesk", "receptionist")
    _logout(logged_in_client)
    _login(logged_in_client, "frontdesk")

    body = logged_in_client.get("/patients/").data.decode()
    # only the active-case patient: Delta (closed, owes money) must NOT appear, or the list itself
    # would reveal who owes money
    assert "Alpha Active" in body and "Delta Owing" not in body and "Charlie Settled" not in body
    assert "Balance Due" not in body and "3000" not in body and "₹" not in body
    assert "outstanding balance" not in body
    # the full list is still available to them, still without any amounts
    everyone = logged_in_client.get("/patients/?view=all").data.decode()
    assert "Delta Owing" in everyone and "Bravo NoCase" in everyone
    assert "Balance Due" not in everyone and "₹" not in everyone


def test_patient_directory_query_omits_balance_when_not_asked(logged_in_client):
    from app import db
    _setup_four(logged_in_client)
    rows = db.list_patients_directory(only_active=True, include_balance=False)
    assert {r["name"] for r in rows} == {"Alpha Active"}
    assert all("balance_due" not in r for r in rows)


def test_dashboard_quick_links_are_styled_buttons(logged_in_client):
    body = logged_in_client.get("/dashboard").data.decode()
    assert 'class="quick-links"' in body
    assert body.count("button button-outline") == 2
    assert "Go to Patients" in body and "Go to Appointments" in body


# ── Imported patients: age without a date of birth, "Last Visited" without visit notes ──

def _imported_patient(name="Imported Person", age=34, last_visited="2026-09-25", created_at=None):
    from datetime import date
    conn = db.get_db()
    now = created_at or f"{date.today().isoformat()} 09:00:00"
    cur = conn.execute(
        """INSERT INTO patients (name, date_of_birth, age, sex, mobile, last_visited_date,
                                 created_at, updated_at, is_historic_import)
           VALUES (?, '', ?, 'Male', '9000000055', ?, ?, ?, 1)""",
        (name, age, last_visited, now, now),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def test_patient_without_dob_shows_the_recorded_age_and_imported_last_visit(logged_in_client):
    pid = _imported_patient()
    row = next(r for r in db.list_patients_directory() if r["id"] == pid)
    assert row["computed_age"] == 34 and row["last_visit_date"] == "2026-09-25"
    body = logged_in_client.get("/patients/?view=all").data.decode()
    assert "2026-09-25 (0)" in body and "Never (0)" not in body
    assert "(Age 34)" in logged_in_client.get(f"/patients/{pid}").data.decode()


def test_recorded_age_moves_forward_with_the_years_since_registration():
    from datetime import date
    from app.validators import patient_age
    three_years_ago = date.today().replace(year=date.today().year - 3, day=1).isoformat()
    assert patient_age({"date_of_birth": "", "age": 34, "created_at": f"{three_years_ago} 09:00:00"}) == 37
    assert patient_age({"date_of_birth": "", "age": None, "created_at": "2026-01-01 00:00:00"}) is None
    assert patient_age({"date_of_birth": "2000-01-01", "age": 99, "created_at": "2026-01-01 00:00:00"}) < 99  # DOB wins


def test_a_newer_visit_note_overrides_the_imported_last_visit(logged_in_client, app):
    pid = _imported_patient(last_visited="2026-01-10")
    conn = db.get_db()
    cur = conn.execute(
        "INSERT INTO cases (patient_id, title, status, created_at, updated_at) VALUES (?, 'C', 'Active', '2026-02-01 00:00:00', '2026-02-01 00:00:00')",
        (pid,),
    )
    conn.execute(
        "INSERT INTO case_visit_notes (case_id, patient_id, note, visit_date, created_at) VALUES (?, ?, 'x', '2026-03-05', '2026-03-05 00:00:00')",
        (cur.lastrowid, pid),
    )
    conn.commit()
    conn.close()
    row = next(r for r in db.list_patients_directory() if r["id"] == pid)
    assert row["last_visit_date"] == "2026-03-05"


def test_retention_counts_the_imported_last_visit(logged_in_client):
    from datetime import date, timedelta
    recent = (date.today() - timedelta(days=20)).isoformat()
    old_registration = "2020-01-01 00:00:00"
    seen_recently = _imported_patient("Seen Recently", last_visited=recent, created_at=old_registration)
    long_gone = _imported_patient("Long Gone", last_visited="2021-05-01", created_at=old_registration)
    lapsed = {r["id"]: r for r in db.get_patient_retention()["lapsed"]}
    assert seen_recently not in lapsed
    assert lapsed[long_gone]["last_activity"] == "2021-05-01"


def test_import_reads_an_age_written_with_a_unit():
    from app.excel_import import _parse_patient
    def row(age):
        cells = {"Patient Name": "A", "Age": age, "Sex": "Male", "Privacy Notice Accepted": "Yes"}
        return _parse_patient(lambda key: cells.get(key, ""))
    for text, expected in [("34", 34), ("34 Y", 34), ("34yrs", 34), ("34.5", 34), ("", None), ("adult", None)]:
        parsed = row(text)
        data = parsed[0] if isinstance(parsed, tuple) else parsed
        assert data["age"] == expected, text
