"""Gap-filling analysis and evidence-based constraint diagnostics."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from visualization.data_loader import DashboardDataset
from visualization.metrics import (
    WORK_ASSIGNMENT_TYPES,
    build_demand_slot_records,
    classify_user,
)

SWING_BREAK = timedelta(hours=48)


def _parse_shift_interval(row: dict[str, str]) -> tuple[datetime, datetime] | None:
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


def check_swing_home_depot(dataset: DashboardDataset) -> dict[str, object]:
    """Check whether every crew member's assigned swing starts and ends at their Home Depot.

    Follows the exact swing segmentation rule in `scripts/check_roster.py`:
    - Collects all active work shifts (`Demand`, `Excess`, `Relief`) assigned to each crew member
      (`Optimised User Id`, or `User Id` when `Optimised User Id` is absent).
    - Orders shifts chronologically and splits into a new swing whenever the rest gap between
      consecutive work shifts exceeds 48 hours (`SWING_BREAK`).
    - Verifies `first_shift["Start Location"] == Home Depot` and `last_shift["End Location"] == Home Depot`.
    """
    per_user_work: dict[str, list[tuple[datetime, datetime, dict[str, str]]]] = defaultdict(list)
    leave_dates_by_user: dict[str, set[str]] = defaultdict(set)
    modified_users: set[str] = set()

    for r in dataset.roster_rows:
        in_horizon = r.get("In Horizon", "Yes").strip()
        if in_horizon and in_horizon != "Yes":
            continue
        orig_uid = r.get("User Id", "").strip()
        opt_uid = r.get("Optimised User Id", "").strip()
        if r.get("Leave Type", "").strip() and orig_uid:
            leave_dates_by_user[orig_uid].add(r.get("Start Date", "").strip())
        if orig_uid != opt_uid:
            if orig_uid:
                modified_users.add(orig_uid)
            if opt_uid:
                modified_users.add(opt_uid)

        atype = r.get("Assignment Type", "").strip()
        if atype not in WORK_ASSIGNMENT_TYPES or not opt_uid:
            continue
        interval = _parse_shift_interval(r)
        if interval is None:
            continue
        per_user_work[opt_uid].append((interval[0], interval[1], r))

    swing_rows: list[dict[str, object]] = []
    total_swings = 0
    passed_swings = 0
    failed_swings = 0
    failed_start_count = 0
    failed_end_count = 0
    solver_modified_failed_swings = 0

    for uid in sorted(per_user_work.keys()):
        crew_info = dataset.crew_by_id.get(uid, {})
        home_depot = crew_info.get("Depot", "").strip()
        if not home_depot:
            # Fallback to first row's Crew Home Depot if present
            home_depot = per_user_work[uid][0][2].get("Crew Home Depot", "").strip()
        if not home_depot:
            continue

        cls = crew_info.get("Classification", "").strip() or classify_user(
            dataset, per_user_work[uid][0][2], uid
        )

        ordered = sorted(per_user_work[uid], key=lambda item: (item[0], item[1]))
        swings: list[list[tuple[datetime, datetime, dict[str, str]]]] = [[ordered[0]]]
        for prev, cur in zip(ordered, ordered[1:]):
            gap = cur[0] - prev[1]
            if gap > SWING_BREAK:
                swings.append([cur])
            else:
                swings[-1].append(cur)

        for idx, sw in enumerate(swings, start=1):
            first_s, _, first_r = sw[0]
            _, last_e, last_r = sw[-1]
            start_loc = first_r.get("Start Location", "").strip()
            end_loc = last_r.get("End Location", "").strip()
            swing_label = first_r.get("Swing", "").strip() or str(idx)

            starts_at_depot = start_loc == home_depot
            ends_at_depot = end_loc == home_depot
            passed = starts_at_depot and ends_at_depot

            swing_modified = any(
                item[2].get("User Id", "").strip() != item[2].get("Optimised User Id", "").strip()
                for item in sw
            )
            has_user_leave = bool(leave_dates_by_user.get(uid))
            if swing_modified:
                context = "Modified by Solver"
            elif has_user_leave:
                context = "Unchanged (Leave-Disrupted)"
            else:
                context = "Unchanged Baseline"

            total_swings += 1
            if passed:
                passed_swings += 1
            else:
                failed_swings += 1
                if not starts_at_depot:
                    failed_start_count += 1
                if not ends_at_depot:
                    failed_end_count += 1
                if swing_modified:
                    solver_modified_failed_swings += 1

            swing_rows.append(
                {
                    "User Id": uid,
                    "Crew Classification": cls,
                    "Home Depot": home_depot,
                    "Swing": swing_label,
                    "Shifts in Swing": len(sw),
                    "First Shift Start": f"{first_r.get('Start Date', '')} {first_r.get('Shift Start Time', '')}",
                    "Start Location": start_loc,
                    "Starts at Home Depot": starts_at_depot,
                    "Last Shift End": f"{last_r.get('End Date', '') or last_r.get('Start Date', '')} {last_r.get('Shift End Time', '')}",
                    "End Location": end_loc,
                    "Ends at Home Depot": ends_at_depot,
                    "Status": "PASS" if passed else "FAIL",
                    "Swing Context": context,
                }
            )

    pass_pct = round((passed_swings / total_swings) * 100.0, 2) if total_swings > 0 else 100.0
    return {
        "total_swings": total_swings,
        "passed_swings": passed_swings,
        "failed_swings": failed_swings,
        "failed_start_count": failed_start_count,
        "failed_end_count": failed_end_count,
        "solver_modified_failed_swings": solver_modified_failed_swings,
        "pass_pct": pass_pct,
        "swing_rows": swing_rows,
    }


def build_unfilled_gap_records(
    dataset: DashboardDataset,
    head_filter: set[str] | None = None,
    swing_filter: set[str] | None = None,
) -> list[dict[str, object]]:
    """Build detailed records for every demand slot that has `Remaining Gap > 0`."""
    slots = build_demand_slot_records(
        dataset,
        swing_filter=swing_filter,
        head_filter=head_filter,
    )

    # Index candidate options and rejections by Seat Key from Layer 1 if available
    cand_count_by_seat: Counter[str] = Counter()
    for c in dataset.gap_options:
        sk = c.get("Seat Key", "").strip()
        if sk:
            cand_count_by_seat[sk] += 1

    rejections_by_seat: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for rej in dataset.rejections:
        sk = rej.get("Seat Key", "").strip()
        reason = rej.get("Reason", "").strip()
        try:
            count = int(rej.get("Rows Rejected", "0"))
        except ValueError:
            count = 0
        if sk and reason:
            rejections_by_seat[sk].append((reason, count))

    unfilled_kind_by_seat: dict[str, set[str]] = defaultdict(set)
    leave_types_by_seat: dict[str, set[str]] = defaultdict(set)
    for u in dataset.unfilled_gaps:
        sk = f"{u.get('Activity ID', '').strip()}@{u.get('Date', '').strip()}T{u.get('Start', '').strip()}"
        if u.get("Kind"):
            unfilled_kind_by_seat[sk].add(u["Kind"])
        if u.get("Leave Type"):
            leave_types_by_seat[sk].add(u["Leave Type"])

    has_layer1_diagnostics = bool(dataset.gap_options or dataset.rejections or dataset.seats)
    solver_start = dataset.constraints.get("Solver Start Date", ("2026-11-06", "Active"))[0]

    unfilled_records: list[dict[str, object]] = []
    for s in slots:
        rem_gap = int(s["Remaining Gap"])
        if rem_gap <= 0:
            continue

        seat_key = str(s["Seat Key"])
        locked = int(s["Locked Gaps"])
        cand_count = cand_count_by_seat.get(seat_key, 0)
        seat_rejs = rejections_by_seat.get(seat_key, [])
        rej_summary = "; ".join(f"{r} ({n})" for r, n in seat_rejs) if seat_rejs else ""

        # Determine evidence-based diagnostic status without guessing
        if locked > 0 and locked >= rem_gap:
            diag_status = "Locked Gap (Before Solver Start)"
            diag_evidence = (
                f"Explicitly marked Is_locked_gap=True in roster_full.csv "
                f"(date {s['Date']} is before Solver Start Date {solver_start}; rule G1)."
            )
        elif has_layer1_diagnostics:
            if cand_count == 0:
                diag_status = "No Legal Layer-1 Candidate Options"
                if rej_summary:
                    diag_evidence = f"0 candidate options in gap_options.csv. Layer-1 rejections: {rej_summary}"
                else:
                    diag_evidence = "0 candidate options in gap_options.csv (no eligible/available crew row matched)."
            else:
                diag_status = "Candidates Existed; Unselected in CP-SAT Global Solve"
                diag_evidence = (
                    f"{cand_count} candidate option(s) existed in gap_options.csv, but CP-SAT did not assign them "
                    "(e.g., candidates assigned elsewhere or constrained globally). "
                    "Exact solver conflict reason is not exported by CP-SAT."
                )
        else:
            diag_status = "Reason Not Available"
            diag_evidence = "Diagnostic reason not available (Layer-1 option/rejection files not loaded or not exported)."

        kinds = sorted(unfilled_kind_by_seat.get(seat_key, set()))
        leaves = sorted(leave_types_by_seat.get(seat_key, set()))

        unfilled_records.append(
            {
                "Seat Key": seat_key,
                "Activity Head": s["Activity Head"],
                "Activity Name": s["Activity Name"],
                "Priority": s["Priority"],
                "Swing": s["Swings"],
                "Date": s["Date"],
                "Shift": s["Shift"],
                "Date_Shift": s["Date_Shift"],
                "Total Demand": s["Total Demand"],
                "Assigned Demand": s["Assigned Demand"],
                "Remaining Gap": rem_gap,
                "Resident Assigned": s["Resident Assigned"],
                "FIFO Assigned": s["FIFO Assigned"],
                "Locked Gaps": locked,
                "Gap Kind": ", ".join(kinds) if kinds else ("locked gap" if locked else "gap"),
                "Leave Type": ", ".join(leaves),
                "Layer-1 Candidates": cand_count if has_layer1_diagnostics else None,
                "Diagnostic Category": diag_status,
                "Diagnostic Evidence": diag_evidence,
            }
        )

    unfilled_records.sort(key=lambda r: (int(r["Priority"]), str(r["Date"]), str(r["Shift"]), str(r["Activity Head"])))
    return unfilled_records


def summarize_gaps(unfilled_records: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Summarize remaining gaps by Activity Head, by Shift, and by Priority."""
    by_head: dict[str, dict[str, object]] = {}
    by_shift: dict[str, int] = defaultdict(int)
    by_date: dict[str, int] = defaultdict(int)
    by_priority: dict[int, int] = defaultdict(int)

    for r in unfilled_records:
        head = str(r["Activity Head"])
        prio = int(r["Priority"])
        shift = str(r["Shift"])
        day = str(r["Date"])
        gap = int(r["Remaining Gap"])

        h_entry = by_head.setdefault(
            head,
            {
                "Activity Head": head,
                "Priority": prio,
                "Remaining Gaps": 0,
                "Unfilled Slots": 0,
                "Locked Gaps": 0,
                "Open Unfilled Gaps": 0,
            },
        )
        h_entry["Remaining Gaps"] = int(h_entry["Remaining Gaps"]) + gap
        h_entry["Unfilled Slots"] = int(h_entry["Unfilled Slots"]) + 1
        locked = min(gap, int(r["Locked Gaps"]))
        h_entry["Locked Gaps"] = int(h_entry["Locked Gaps"]) + locked
        h_entry["Open Unfilled Gaps"] = int(h_entry["Open Unfilled Gaps"]) + max(0, gap - locked)

        by_shift[shift] += gap
        by_date[day] += gap
        by_priority[prio] += gap

    return {
        "by_head": sorted(by_head.values(), key=lambda x: (-int(x["Remaining Gaps"]), int(x["Priority"]))),
        "by_shift": [{"Shift": k, "Remaining Gaps": v} for k, v in sorted(by_shift.items())],
        "by_date": [{"Date": k, "Remaining Gaps": v} for k, v in sorted(by_date.items())],
        "by_priority": [{"Priority": k, "Remaining Gaps": v} for k, v in sorted(by_priority.items())],
    }


def build_constraint_diagnostics(dataset: DashboardDataset) -> dict[str, object]:
    """Compile evidence-based diagnostics for constraints, swing availability, and per-swing shift limits."""
    # 1. Configured constraint switches & rule parameters
    max_shifts_status = dataset.constraints.get("Activity Head Max Shifts", ("", "Active"))[1]
    assign_prio_val, assign_prio_status = dataset.constraints.get("Assignment Type Priority", ("1000", "Active"))
    tier_pen_str = assign_prio_val or "1000"
    res_restrict = bool(dataset.config_flags.get("residential_start_restriction", True))
    relief_trans = bool(dataset.config_flags.get("relief_only_day_night_transition", True))
    prio_strategy = str(dataset.config_flags.get("priority_strategy", "none"))
    type_prio_str = ", ".join(
        f"{atype}: {p}"
        for atype, p in sorted(dataset.assignment_type_priority.items(), key=lambda x: (x[1], x[0]))
    )

    constraint_overview = [
        {
            "Constraint / Setting": "Assignment Type Priority (Gap-Fill Source Preference)",
            "Source": "constraints_df.csv + assignment_type_priority.csv",
            "Status": assign_prio_status,
            "Configured Value": f"{type_prio_str} (Tier Penalty: {tier_pen_str})",
        },
        {
            "Constraint / Setting": "Activity Head Max Shifts (Max Resident / Max FIFO Shifts)",
            "Source": "constraints_df.csv + activity_priority.csv",
            "Status": max_shifts_status,
            "Configured Value": "Per Activity Head (see limits table below)",
        },
        {
            "Constraint / Setting": "Residential Start Restriction (22:00 - 02:00)",
            "Source": "config.yml",
            "Status": "Active" if res_restrict else "Inactive",
            "Configured Value": "Residential crew cannot start new shifts in [22:00, 02:00)",
        },
        {
            "Constraint / Setting": "Relief Only Day/Night Transition",
            "Source": "config.yml",
            "Status": "Active" if relief_trans else "Inactive",
            "Configured Value": "Only Relief standby rows may transition Day <-> Night (with 23h rest)",
        },
        {
            "Constraint / Setting": "Optimization Priority Strategy",
            "Source": "config.yml",
            "Status": "Active",
            "Configured Value": prio_strategy,
        },
        {
            "Constraint / Setting": "Solver Start Date (G1)",
            "Source": "constraints_df.csv",
            "Status": dataset.constraints.get("Solver Start Date", ("2026-11-06", "Active"))[1],
            "Configured Value": dataset.constraints.get("Solver Start Date", ("2026-11-06", "Active"))[0],
        },
        {
            "Constraint / Setting": "Ordinary / Transition Rest Hours",
            "Source": "constraints_df.csv",
            "Status": "Active",
            "Configured Value": (
                f"{dataset.constraints.get('Ordinary Rest Hours', ('11', 'Active'))[0]}h ordinary / "
                f"{dataset.constraints.get('Transition Rest Hours', ('23', 'Active'))[0]}h transition"
            ),
        },
        {
            "Constraint / Setting": "Start-Time Pattern per Block (F3)",
            "Source": "constraints_df.csv",
            "Status": "Active",
            "Configured Value": (
                f"Max {dataset.constraints.get('Max Start Changes Per Block', ('1', 'Active'))[0]} change(s) "
                f"of <= {dataset.constraints.get('Max Start Change Minutes', ('60', 'Active'))[0]} min"
            ),
        },
    ]

    # 2. Layer-1 Rejection Reasons aggregated from rejections.csv (if present)
    rejection_totals: Counter[str] = Counter()
    seats_affected: dict[str, set[str]] = defaultdict(set)
    for r in dataset.rejections:
        reason = r.get("Reason", "").strip()
        sk = r.get("Seat Key", "").strip()
        try:
            n = int(r.get("Rows Rejected", "0"))
        except ValueError:
            n = 0
        if reason:
            rejection_totals[reason] += n
            if sk:
                seats_affected[reason].add(sk)

    rejection_summary = [
        {
            "Layer-1 Rejection Reason (rejections.csv)": reason,
            "Candidate Crew-Rows Rejected": count,
            "Distinct Open Seats Affected": len(seats_affected[reason]),
        }
        for reason, count in rejection_totals.most_common()
    ]

    # 3. Swing availability diagnostics from swings.csv (if present)
    swing_status_counts: Counter[tuple[str, str]] = Counter()
    for sw in dataset.swings:
        status = sw.get("Status", "unknown").strip()
        reason = sw.get("Reason", "").strip() or "Available in CP-SAT model"
        swing_status_counts[(status, reason)] += 1

    swing_availability = [
        {
            "Swing Status": status,
            "Reason": reason,
            "Swing Count": count,
        }
        for (status, reason), count in sorted(swing_status_counts.items())
    ]

    # 4. Per-Swing Activity-Head Shift Limit Utilization (computed from actual selected assignments)
    # Group selected non-Relief work shifts by (User Id, Classification, Swing, Activity Head)
    per_swing_head_counts: Counter[tuple[str, str, str, str]] = Counter()
    for r in dataset.roster_rows:
        in_horizon = r.get("In Horizon", "Yes").strip()
        if in_horizon and in_horizon != "Yes":
            continue
        assign_type = r.get("Assignment Type", "").strip()
        if assign_type not in WORK_ASSIGNMENT_TYPES or assign_type == "Relief":
            continue
        uid = r.get("Optimised User Id", "").strip()
        if not uid:
            continue
        cls = classify_user(dataset, r, uid)
        sw = r.get("Swing", "").strip()
        head = r.get("Activity Head", "").strip()
        if head in dataset.limits_by_head:
            per_swing_head_counts[(uid, cls, sw, head)] += 1

    limit_utilization_rows: list[dict[str, object]] = []
    max_observed_by_head: dict[str, dict[str, int]] = defaultdict(lambda: {"Residential": 0, "FIFO": 0})
    at_limit_by_head: dict[str, dict[str, int]] = defaultdict(lambda: {"Residential": 0, "FIFO": 0})

    for (uid, cls, sw, head), count in sorted(per_swing_head_counts.items()):
        res_lim, fifo_lim = dataset.limits_by_head.get(head, (None, None))
        applicable_limit = res_lim if cls == "Residential" else (fifo_lim if cls == "FIFO" else None)
        if cls in ("Residential", "FIFO"):
            if count > max_observed_by_head[head][cls]:
                max_observed_by_head[head][cls] = count
            if applicable_limit is not None and count >= applicable_limit:
                at_limit_by_head[head][cls] += 1
        limit_utilization_rows.append(
            {
                "User Id": uid,
                "Crew Classification": cls,
                "Swing": sw,
                "Activity Head": head,
                "Assigned Shifts in Swing": count,
                "Configured Limit": applicable_limit,
                "At / Above Limit": bool(applicable_limit is not None and count >= applicable_limit),
                "Exceeded Limit": bool(applicable_limit is not None and count > applicable_limit),
            }
        )

    head_limits_table: list[dict[str, object]] = []
    for head, prio in sorted(dataset.priority_by_head.items(), key=lambda x: (x[1], x[0])):
        res_lim, fifo_lim = dataset.limits_by_head.get(head, (None, None))
        head_limits_table.append(
            {
                "Priority": prio,
                "Activity Head": head,
                "Max Resident Shifts (Config)": res_lim,
                "Max Observed Resident Shifts / Swing": max_observed_by_head[head]["Residential"],
                "Resident Swings Reaching Limit": at_limit_by_head[head]["Residential"],
                "Max FIFO Shifts (Config)": fifo_lim,
                "Max Observed FIFO Shifts / Swing": max_observed_by_head[head]["FIFO"],
                "FIFO Swings Reaching Limit": at_limit_by_head[head]["FIFO"],
            }
        )

    # 5. Assignment Type Priority & Fills by Source Type
    fills_by_source: Counter[str] = Counter()
    candidates_by_source: Counter[str] = Counter()
    for r in dataset.reassignments:
        src = r.get("Source", "").strip()
        if src:
            fills_by_source[src] += 1
    for c in dataset.gap_options:
        src = c.get("Source", "").strip()
        if src:
            candidates_by_source[src] += 1

    assignment_type_priority_table = [
        {
            "Priority": prio,
            "Assignment Type": atype,
            "Layer-1 Candidate Options": candidates_by_source.get(atype, 0),
            "Selected Gap Fills (reassignments.csv)": fills_by_source.get(atype, 0),
        }
        for atype, prio in sorted(dataset.assignment_type_priority.items(), key=lambda x: (x[1], x[0]))
    ]

    # 6. Home Depot Swing Start & End Check
    home_depot_check = check_swing_home_depot(dataset)

    return {
        "constraint_overview": constraint_overview,
        "assignment_type_priority_table": assignment_type_priority_table,
        "home_depot_check": home_depot_check,
        "rejection_summary": rejection_summary,
        "swing_availability": swing_availability,
        "head_limits_table": head_limits_table,
        "limit_utilization_rows": limit_utilization_rows,
    }


def inspect_seat_candidates(dataset: DashboardDataset, seat_key: str) -> dict[str, list[dict[str, object]]]:
    """Trace what happened in the final solver output to every Layer-1 candidate for a given Seat Key.

    Uses only factual records from `gap_options.csv`, `rejections.csv`, `reassignments.csv`, and `roster_full.csv`.
    """
    roster_by_id = {
        r.get("Assignment ID", "").strip(): r
        for r in dataset.roster_rows
        if r.get("Assignment ID", "").strip()
    }
    reass_by_from_row = {
        r.get("From Row", "").strip(): r
        for r in dataset.reassignments
        if r.get("From Row", "").strip()
    }

    # Precompute per-swing assigned shift counts by (User Id, Swing, Activity Head)
    swing_head_counts: Counter[tuple[str, str, str]] = Counter()
    for r in dataset.roster_rows:
        if r.get("In Horizon", "Yes").strip() not in ("Yes", ""):
            continue
        atype = r.get("Assignment Type", "").strip()
        if atype not in WORK_ASSIGNMENT_TYPES or atype == "Relief":
            continue
        uid = r.get("Optimised User Id", "").strip()
        sw = r.get("Swing", "").strip()
        head = r.get("Activity Head", "").strip()
        if uid and sw and head:
            swing_head_counts[(uid, sw, head)] += 1

    # Find target Activity Head for the inspected seat
    target_head = ""
    for s in dataset.seats:
        if s.get("Seat Key", "").strip() == seat_key:
            target_head = s.get("Activity Head", "").strip()
            break
    if not target_head and "@" in seat_key:
        aid = seat_key.split("@", 1)[0]
        for d in dataset.demand_rows:
            if d.get("Activity ID", "").strip() == aid:
                target_head = d.get("Activity Head", "").strip()
                break

    candidate_rows: list[dict[str, object]] = []
    for c in dataset.gap_options:
        if c.get("Seat Key", "").strip() != seat_key:
            continue
        uid = c.get("Candidate User Id", "").strip()
        cand_row_id = c.get("Candidate Row", "").strip()
        source_row = roster_by_id.get(cand_row_id, {})
        sw = source_row.get("Swing", "").strip()
        cls = classify_user(dataset, source_row, uid)

        reass = reass_by_from_row.get(cand_row_id)
        if reass:
            filled_act = reass.get("Activity Name", "")
            filled_dt = f"{reass.get('Date', '')} {reass.get('Start', '')}".strip()
            outcome = (
                f"Moved to fill {filled_act} @ {filled_dt} "
                f"(Row {reass.get('Filled Row', '')}, Cost {reass.get('Cost', '')})"
            )
        elif source_row:
            opt_u = source_row.get("Optimised User Id", "").strip()
            note = source_row.get("Optimisation Note", "").strip()
            if opt_u == uid:
                outcome = (
                    f"Kept original {source_row.get('Assignment Type', '')} row "
                    f"({source_row.get('Activity Name', '')} @ {source_row.get('Start Date', '')} {source_row.get('Shift Start Time', '')})"
                )
            elif not opt_u and note:
                outcome = note
            else:
                outcome = f"Source row assigned to {opt_u or 'unassigned'}"
        else:
            outcome = "Source row not found in roster_full.csv"

        head_to_check = target_head or c.get("Activity Name", "").strip()
        res_lim, fifo_lim = dataset.limits_by_head.get(head_to_check, (None, None))
        lim = res_lim if cls == "Residential" else (fifo_lim if cls == "FIFO" else None)
        used = swing_head_counts.get((uid, sw, head_to_check), 0) if sw else 0
        limit_str = f"{used}/{lim}" if lim is not None else f"{used}"

        candidate_rows.append(
            {
                "Candidate User Id": uid,
                "Classification": cls,
                "Swing": sw,
                "Source Type": c.get("Source", ""),
                "Candidate Row": cand_row_id,
                "Candidate Row Start": c.get("Candidate Row Start", ""),
                "Offset Minutes": c.get("Offset Minutes", ""),
                "Option Cost": c.get("Cost", ""),
                "Actual Solver Outcome for Candidate Row": outcome,
                f"Swing Shifts on {head_to_check or 'Head'} (Used/Limit)": limit_str,
            }
        )

    rejection_rows: list[dict[str, object]] = []
    for r in dataset.rejections:
        if r.get("Seat Key", "").strip() == seat_key:
            rejection_rows.append(
                {
                    "Seat Key": seat_key,
                    "Layer-1 Rejection Reason": r.get("Reason", ""),
                    "Rows Rejected": r.get("Rows Rejected", "0"),
                }
            )

    return {
        "candidates": candidate_rows,
        "rejections": rejection_rows,
    }


def parse_summary_and_validation(dataset: DashboardDataset) -> dict[str, object]:
    """Parse CP-SAT objective stage statuses from `summary.md` and rule checks from `validation.md`."""
    stages: list[dict[str, str]] = []
    summary_items: dict[str, str] = {}

    for line in dataset.summary_markdown.splitlines():
        text = line.strip()
        if not text.startswith("|") or text.startswith("|---") or text.startswith("| Item "):
            continue
        parts = [p.strip() for p in text.strip("|").split("|")]
        if len(parts) == 2:
            key, val = parts
            summary_items[key] = val
            if key.startswith("Objective stage:"):
                stage_name = key.replace("Objective stage:", "").strip()
                status_badge = "OPTIMAL" if val.startswith("OPTIMAL") else (
                    "FEASIBLE" if val.startswith("FEASIBLE") else "OTHER"
                )
                stages.append(
                    {
                        "Stage": stage_name,
                        "Status": status_badge,
                        "Details": val,
                    }
                )

    validation_headline = ""
    validation_rules: list[dict[str, str]] = []
    for line in dataset.validation_markdown.splitlines():
        text = line.strip()
        if text.startswith("**") and "unexpected failure" in text:
            validation_headline = text.strip("*")
        elif text.startswith("|") and not text.startswith("|---") and not text.startswith("| Rule "):
            parts = [p.strip() for p in text.strip("|").split("|")]
            if len(parts) >= 4:
                validation_rules.append(
                    {
                        "Rule": parts[0],
                        "Check": parts[1],
                        "Result": parts[2],
                        "Detail": parts[3],
                    }
                )

    return {
        "stages": stages,
        "summary_items": summary_items,
        "validation_headline": validation_headline,
        "validation_rules": validation_rules,
    }
