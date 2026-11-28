"""Export helpers for CSV, multi-sheet Excel workbooks, and printable crew schedules."""

from __future__ import annotations

import csv
import html
import io
from typing import Any


def rows_to_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    """Serialize a list of row dicts to UTF-8 CSV bytes."""
    if not rows:
        return b""
    buf = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def datasets_to_excel_bytes(sheets: dict[str, list[dict[str, Any]]]) -> bytes:
    """Build a multi-sheet Excel (.xlsx) workbook from {sheet_name: rows}."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    first = True
    for raw_name, rows in sheets.items():
        sheet_name = raw_name[:31]  # Excel 31-char sheet title limit
        ws = wb.active if first else wb.create_sheet(title=sheet_name)
        ws.title = sheet_name
        first = False

        if not rows:
            ws.append(["No data available"])
            continue

        headers = list(rows[0].keys())
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append([row.get(h, "") for h in headers])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def crew_schedule_to_html(
    user_id: str,
    crew_info: dict[str, str],
    schedule_rows: list[dict[str, Any]],
) -> bytes:
    """Generate a clean, printable HTML roster card for an individual crew member."""
    classification = html.escape(crew_info.get("Classification", "Unknown"))
    home_depot = html.escape(crew_info.get("Home Depot", "Unknown"))
    role = html.escape(crew_info.get("Role", ""))

    if schedule_rows:
        cols = list(schedule_rows[0].keys())
        th = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
        trs = []
        for r in schedule_rows:
            tds = "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols)
            trs.append(f"<tr>{tds}</tr>")
        table_html = f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"
    else:
        table_html = "<p>No scheduled entries found for this crew member.</p>"

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Crew Schedule - {html.escape(user_id)}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }}
  h1 {{ margin-bottom: 4px; }}
  .meta {{ color: #4b5563; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; }}
  th {{ background: #f3f4f6; }}
  tr:nth-child(even) {{ background: #f9fafb; }}
  @media print {{ body {{ margin: 8px; }} }}
</style>
</head>
<body>
  <h1>Crew Roster Schedule: {html.escape(user_id)}</h1>
  <div class="meta">
    <strong>Classification:</strong> {classification} &nbsp;|&nbsp;
    <strong>Home Depot:</strong> {home_depot} &nbsp;|&nbsp;
    <strong>Role:</strong> {role}
  </div>
  {table_html}
</body>
</html>
"""
    return doc.encode("utf-8")
