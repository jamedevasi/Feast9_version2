"""Writing user-typed text into Excel files safely.

openpyxl stores any string that starts with "=" as a live formula, so a patient name, case
title or note typed as =HYPERLINK(...) or =cmd|... would run when someone opens the export
in Excel (formula / CSV injection). Every workbook the app builds from database text goes
through append_row(), which keeps text cells as plain text.
"""


def append_row(ws, values):
    """ws.append(values), with every text cell stored as text — never as a formula."""
    ws.append(values)
    for cell in ws[ws.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = "s"
