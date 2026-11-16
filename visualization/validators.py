"""Automated Post-Solve QA & Solution Diagnostics Engine.

Wraps existing project validation results (`validation.md` / `check_swing_home_depot`) and supplements
them with deterministic read-only post-solve checks on the selected roster.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from visualization.data_loader import DashboardDataset
from visualization.gap_analysis import check_swing_home_depot, parse_summary_and_validation
from visualization.metrics import WORK_ASSIGNMENT_TYPES, build_demand_slot_records


def _parse_interval(row: dict[str, str]) -> tuple[datetime, datetime] | None:
    s_date = row.get("Start Date", "").strip()
    e_date = row.get("End Date", "").strip() or s_date
    s_time = row.get("Shift Start Time", "").strip()
    e_time = row.get("Shift End Time", "").strip()
    if not s_date or not s_time or not e_time:
        return None
    try:
        s_dt = datetime.fromisoformat(f"{s_date}T{s_time}")
        e_dt = datetime.fromisoformat(f"{e_date}T{e_time}")
        if e_dt <= s_dt:
            e_dt += timedelta(days=1)
        return s_dt, e_dt
    except ValueError:
        return None


def run_post_solve_qa_suite(dataset: DashboardDataset) -> dict[str, Any]:
    """Run all 6 deterministic post-solve QA checks and combine with `validation.md` rule checks."""
    checks: list[dict[str, Any]] = []
    offending_rows: list[dict[str, Any]] = []

    # 1. Schema & Completeness Check
    schema_errors: list[dict[str, Any]] = []
    work_count = 0
    for r in dataset.roster_rows:
        if r.get("In Horizon", "Yes").strip() not in ("", "Yes", "True", "true"):
            continue
        atype = r.get("Assignment Type", "").strip()
        uid = r.get("Optimised User Id", "").strip()
        if atype not in WORK_ASSIGNMENT_TYPES or not uid:
            continue
        work_count += 1
        aid = r.get("Assignment ID", "").strip()
        head = r.get("Activity Head", "").strip()
        s_loc = r.get("Start Location", "").strip()
        e_loc = r.get("End Location", "").strip()
        interval = _parse_interval(r)
        missing_fields = []
        if atype == "Demand" and not head:
            missing_fields.append("Activity Head")
        if not s_loc or not e_loc:
            missing_fields.append("Start/End Location")
        if interval is None or interval[0] >= interval[1]:
            missing_fields.append("Start < End Timestamp")
        if missing_fields:
            err = {
                "Check ID": "QA1",
                "Rule": "Schema & Completeness",
                "Severity": "CRITICAL",
                "Assignment ID": aid,
                "Crew ID": uid,
                "Activity Head": head,
                "Timestamp": f"{r.get('Start Date', '')} {r.get('Shift Start Time', '')}",
                "Detail": f"Invalid/missing: {', '.join(missing_fields)}",
            }
            schema_errors.append(err)
            offending_rows.append(err)

    checks.append({
        "Check ID": "QA1",
        "Rule": "Schema & Completeness Check",
        "Category": "Data Hygiene",
        "Status": "PASS" if not schema_errors else "FAIL",
        "Severity": "OK" if not schema_errors else "CRITICAL",
        "Checked": work_count,
        "Violations": len(schema_errors),
        "Detail": f"{work_count:,} selected work assignments verified (valid Crew ID, Depot, Start < End)."
        if not schema_errors
        else f"{len(schema_errors)} incomplete/invalid work assignment row(s).",
    })

    # 2. Double-Booking / Overlap Check
    per_user_shifts: dict[str, list[tuple[datetime, datetime, dict[str, str]]]] = defaultdict(list)
    for r in dataset.roster_rows:
        if r.get("In Horizon", "Yes").strip() not in ("", "Yes", "True", "true"):
            continue
        if r.get("Assignment Type", "").strip() not in WORK_ASSIGNMENT_TYPES:
            continue
        uid = r.get("Optimised User Id", "").strip()
        if not uid:
            continue
        interval = _parse_interval(r)
        if interval is not None:
            per_user_shifts[uid].append((interval[0], interval[1], r))

    overlap_errors: list[dict[str, Any]] = []
    for uid, items in sorted(per_user_shifts.items()):
        items.sort(key=lambda x: (x[0], x[1]))
        for (s1, e1, r1), (s2, _e2, r2) in zip(items, items[1:]):
            if s2 < e1:
                err = {
                    "Check ID": "QA2",
                    "Rule": "Double-Booking / Overlap",
                    "Severity": "CRITICAL",
                    "Assignment ID": f"{r1.get('Assignment ID', '')} & {r2.get('Assignment ID', '')}",
                    "Crew ID": uid,
                    "Activity Head": r2.get("Activity Head", ""),
                    "Timestamp": f"{s1.isoformat()} .. {e1.isoformat()} vs {s2.isoformat()}",
                    "Detail": f"Crew {uid} double-booked across overlapping shifts.",
                }
                overlap_errors.append(err)
                offending_rows.append(err)

    checks.append({
        "Check ID": "QA2",
        "Rule": "Double-Booking / Time Overlap Check",
        "Category": "Crew Feasibility",
        "Status": "PASS" if not overlap_errors else "FAIL",
        "Severity": "OK" if not overlap_errors else "CRITICAL",
        "Checked": len(per_user_shifts),
        "Violations": len(overlap_errors),
        "Detail": f"0 overlapping shift intervals across {len(per_user_shifts)} active crew members."
        if not overlap_errors
        else f"{len(overlap_errors)} overlapping crew assignment pair(s) detected.",
    })

    # 3. Duplicate Assignment Check
    seen_assignment_ids: set[str] = set()
    dup_errors: list[dict[str, Any]] = []
    for r in dataset.roster_rows:
        aid = r.get("Assignment ID", "").strip()
        uid = r.get("Optimised User Id", "").strip()
        if not aid:
            continue
        if aid in seen_assignment_ids:
            err = {
                "Check ID": "QA3",
                "Rule": "Duplicate Assignment",
                "Severity": "CRITICAL",
                "Assignment ID": aid,
                "Crew ID": uid,
                "Activity Head": r.get("Activity Head", ""),
                "Timestamp": f"{r.get('Start Date', '')} {r.get('Shift Start Time', '')}",
                "Detail": f"Duplicate Assignment ID {aid} in roster.",
            }
            dup_errors.append(err)
            offending_rows.append(err)
        seen_assignment_ids.add(aid)

    checks.append({
        "Check ID": "QA3",
        "Rule": "Duplicate Assignment Check",
        "Category": "Data Hygiene",
        "Status": "PASS" if not dup_errors else "FAIL",
        "Severity": "OK" if not dup_errors else "CRITICAL",
        "Checked": len(seen_assignment_ids),
        "Violations": len(dup_errors),
        "Detail": f"{len(seen_assignment_ids):,} unique Assignment IDs verified with 0 duplicates."
        if not dup_errors
        else f"{len(dup_errors)} duplicate Assignment ID(s) found.",
    })

    # 4. Home Depot & Swing Continuity Check
    depot_check = check_swing_home_depot(dataset)
    failed_swings = int(depot_check["failed_swings"])
    for sw_row in depot_check["swing_rows"]:
        if sw_row["Status"] != "PASS":
            offending_rows.append({
                "Check ID": "QA4",
                "Rule": "Home Depot Continuity",
                "Severity": "WARNING",
                "Assignment ID": f"Swing {sw_row['Swing']}",
                "Crew ID": sw_row["User Id"],
                "Activity Head": f"Home: {sw_row['Home Depot']}",
                "Timestamp": f"Start: {sw_row['Start Location']} -> End: {sw_row['End Location']}",
                "Detail": "Swing start or end location differs from crew Home Depot.",
            })

    checks.append({
        "Check ID": "QA4",
        "Rule": "Home Depot & Swing Continuity Check",
        "Category": "Operational Rule",
        "Status": "PASS" if failed_swings == 0 else "WARN",
        "Severity": "OK" if failed_swings == 0 else "WARNING",
        "Checked": int(depot_check["total_swings"]),
        "Violations": failed_swings,
        "Detail": f"{depot_check['passed_swings']}/{depot_check['total_swings']} swings start and end at crew Home Depot.",
    })

    # 5. Crew Availability & Eligibility Check
    eligible_map: dict[str, set[str]] = {}
    for row in dataset.eligibility_rows:
        act_id = row.get("Activity ID", "").strip()
        users = {u.strip() for u in row.get("Eligible User Ids", "").split(";") if u.strip()}
        if act_id:
            eligible_map[act_id] = users

    elig_errors: list[dict[str, Any]] = []
    demand_checked = 0
    for r in dataset.roster_rows:
        if r.get("In Horizon", "Yes").strip() not in ("", "Yes", "True", "true"):
            continue
        if r.get("Assignment Type", "").strip() != "Demand":
            continue
        uid = r.get("Optimised User Id", "").strip()
        if not uid:
            continue
        demand_checked += 1
        act_id = r.get("Activity ID", "").strip()
        orig_uid = r.get("User Id", "").strip()
        leave_type = r.get("Leave Type", "").strip()
        is_reassigned = uid != r.get("New User Id", "").strip()
        if is_reassigned and eligible_map and act_id in eligible_map and uid not in eligible_map[act_id]:
            err = {
                "Check ID": "QA5",
                "Rule": "Crew Eligibility (R5)",
                "Severity": "CRITICAL",
                "Assignment ID": r.get("Assignment ID", ""),
                "Crew ID": uid,
                "Activity Head": r.get("Activity Head", ""),
                "Timestamp": f"{r.get('Start Date', '')} {r.get('Shift Start Time', '')}",
                "Detail": f"Crew {uid} assigned to Activity {act_id} but not in eligibility_matrix.csv.",
            }
            elig_errors.append(err)
            offending_rows.append(err)
        if leave_type and uid == orig_uid:
            err = {
                "Check ID": "QA5",
                "Rule": "Crew Availability (Leave)",
                "Severity": "CRITICAL",
                "Assignment ID": r.get("Assignment ID", ""),
                "Crew ID": uid,
                "Activity Head": r.get("Activity Head", ""),
                "Timestamp": f"{r.get('Start Date', '')} {r.get('Shift Start Time', '')}",
                "Detail": f"Crew {uid} assigned to row while on leave ({leave_type}).",
            }
            elig_errors.append(err)
            offending_rows.append(err)

    checks.append({
        "Check ID": "QA5",
        "Rule": "Crew Availability & Eligibility Check",
        "Category": "Crew Feasibility",
        "Status": "PASS" if not elig_errors else "FAIL",
        "Severity": "OK" if not elig_errors else "CRITICAL",
        "Checked": demand_checked,
        "Violations": len(elig_errors),
        "Detail": f"{demand_checked:,} assigned Demand shifts verified against leave & eligibility_matrix.csv."
        if not elig_errors
        else f"{len(elig_errors)} eligibility/availability violation(s) detected.",
    })

    # 6. Demand Reconciliation Check
    slots = build_demand_slot_records(dataset)
    reconcile_errors: list[dict[str, Any]] = []
    for s in slots:
        td = int(s["Total Demand"])
        ad = int(s["Assigned Demand"])
        rg = int(s["Remaining Gap"])
        if ad + rg != td:
            err = {
                "Check ID": "QA6",
                "Rule": "Demand Reconciliation",
                "Severity": "CRITICAL",
                "Assignment ID": str(s["Seat Key"]),
                "Crew ID": "",
                "Activity Head": str(s["Activity Head"]),
                "Timestamp": f"{s['Date']} {s['Shift']}",
                "Detail": f"Assigned ({ad}) + Remaining Gap ({rg}) != Total Demand ({td}).",
            }
            reconcile_errors.append(err)
            offending_rows.append(err)

    checks.append({
        "Check ID": "QA6",
        "Rule": "Demand Reconciliation Check (Filled + Unfilled == Total)",
        "Category": "OR Reconciliation",
        "Status": "PASS" if not reconcile_errors else "FAIL",
        "Severity": "OK" if not reconcile_errors else "CRITICAL",
        "Checked": len(slots),
        "Violations": len(reconcile_errors),
        "Detail": f"All {len(slots):,} demand slots satisfy Filled + Unfilled == Total Demand."
        if not reconcile_errors
        else f"{len(reconcile_errors)} slot reconciliation mismatch(es).",
    })

    # Combine with solver validation.md checks if present
    parsed_meta = parse_summary_and_validation(dataset)
    val_rules = parsed_meta.get("validation_rules", [])

    passed_count = sum(1 for c in checks if c["Status"] == "PASS")
    failed_critical = sum(1 for c in checks if c["Severity"] == "CRITICAL")
    warning_count = sum(1 for c in checks if c["Severity"] == "WARNING")

    return {
        "total_checks": len(checks),
        "passed": passed_count,
        "failed_critical": failed_critical,
        "warnings": warning_count,
        "checks": checks,
        "offending_rows": offending_rows,
        "solver_validation_headline": parsed_meta.get("validation_headline", ""),
        "solver_validation_rules": val_rules,
    }
