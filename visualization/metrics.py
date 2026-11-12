"""KPI calculations, slot-level demand reconciliation, and aggregations for the dashboard."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from visualization.data_loader import DashboardDataset

WORK_ASSIGNMENT_TYPES = {"Demand", "Excess", "Relief"}


@dataclass(frozen=True)
class SummaryKPIs:
    """Overall summary KPIs derived from actual solver outputs."""

    total_demand: int
    assigned_demand: int
    unfilled_demand: int
    coverage_pct: float
    resident_demand_assignments: int
    fifo_demand_assignments: int
    resident_work_assignments: int
    fifo_work_assignments: int
    total_gaps: int
    locked_gaps: int
    open_gaps_to_fill: int
    gaps_filled: int
    gap_fill_pct: float
    fully_covered_slots: int
    partially_covered_slots: int
    unfilled_slots: int


def classify_user(dataset: DashboardDataset, row: dict[str, str], user_id: str) -> str:
    """Return crew classification ('Residential' or 'FIFO') for a user from row or crew master table."""
    if not user_id:
        return ""
    row_cls = row.get("Crew Classification", "").strip()
    if row_cls in ("Residential", "FIFO"):
        return row_cls
    crew_info = dataset.crew_by_id.get(user_id, {})
    return crew_info.get("Classification", "").strip()


def _in_horizon_demand_rows(dataset: DashboardDataset) -> list[dict[str, str]]:
    """Return in-horizon Demand rows from roster_full.csv."""
    rows: list[dict[str, str]] = []
    for r in dataset.roster_rows:
        if r.get("Assignment Type") != "Demand":
            continue
        in_horizon = r.get("In Horizon", "Yes").strip()
        if in_horizon and in_horizon != "Yes":
            continue
        rows.append(r)
    return rows


def build_demand_slot_records(
    dataset: DashboardDataset,
    swing_filter: set[str] | None = None,
    head_filter: set[str] | None = None,
    crew_type_filter: set[str] | None = None,
    date_filter: set[str] | None = None,
    shift_filter: set[str] | None = None,
    only_disrupted_gaps: bool = False,
) -> list[dict[str, object]]:
    """Reconcile demand slots with assigned crew in roster_full.csv.

    Each slot corresponds to `(Activity ID, Start Date, Shift Start Time)` (or per Swing when filtered by Swing).
    Handles multi-capacity slots (`Demand > 1`) and partially covered slots accurately.
    """
    demand_lookup: dict[tuple[str, str], dict[str, str]] = {}
    demand_by_id: dict[str, dict[str, str]] = {}
    for d in dataset.demand_rows:
        if d.get("Is Active", "Yes").strip() not in ("Yes", "True", "1", ""):
            continue
        aid = d.get("Activity ID", "").strip()
        shift = d.get("Shift", "").strip()
        did = d.get("Demand ID", "").strip()
        if aid and shift:
            demand_lookup[(aid, shift)] = d
        if did:
            demand_by_id[did] = d

    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for r in _in_horizon_demand_rows(dataset):
        aid = r.get("Activity ID", "").strip()
        day = r.get("Start Date", "").strip()
        shift = r.get("Shift Start Time", "").strip()
        sw = r.get("Swing", "").strip()
        head = r.get("Activity Head", "").strip()
        if not head and (aid, shift) in demand_lookup:
            head = demand_lookup[(aid, shift)].get("Activity Head", "").strip()

        if swing_filter and sw not in swing_filter:
            continue
        if head_filter and head not in head_filter:
            continue
        if date_filter and day not in date_filter:
            continue
        if shift_filter and shift not in shift_filter:
            continue

        if crew_type_filter:
            assigned_uid = r.get("Optimised User Id", "").strip()
            orig_uid = r.get("User Id", "").strip()
            cls = classify_user(dataset, r, assigned_uid) or classify_user(dataset, r, orig_uid)
            if cls not in crew_type_filter:
                continue

        grouped[(aid, day, shift)].append(r)

    slot_records: list[dict[str, object]] = []
    for (aid, day, shift), rows in sorted(grouped.items(), key=lambda x: (x[0][1], x[0][2], x[0][0])):
        first = rows[0]
        did = first.get("Demand ID", "").strip()
        d_meta = demand_by_id.get(did) or demand_lookup.get((aid, shift), {})
        head = first.get("Activity Head", "").strip() or d_meta.get("Activity Head", "").strip() or aid
        act_name = first.get("Activity Name", "").strip() or d_meta.get("Activity Name", "").strip() or aid
        priority = dataset.priority_by_head.get(head, 999)

        # If unfiltered by Swing/Crew Type and demand_meta has an explicit Demand count, reconcile with rows count.
        row_count = len(rows)
        configured_demand = row_count
        if not swing_filter and not crew_type_filter and d_meta.get("Demand", "").isdecimal():
            configured_demand = max(int(d_meta["Demand"]), row_count)
        total_demand = configured_demand

        # Count unique assigned rows / users (preventing duplicate assignment counting)
        assigned_users: list[str] = []
        resident_assigned = 0
        fifo_assigned = 0
        locked_gaps = 0
        open_gaps = 0
        recovered_gaps = 0
        swings_in_slot = sorted({r.get("Swing", "").strip() for r in rows if r.get("Swing", "").strip()})
        assignment_ids = [r.get("Assignment ID", "").strip() for r in rows if r.get("Assignment ID", "").strip()]

        for r in rows:
            uid = r.get("Optimised User Id", "").strip()
            is_gap = r.get("Is Gap", "").strip() == "True"
            is_locked = r.get("Is_locked_gap", "").strip() == "True"
            if is_gap and is_locked:
                locked_gaps += 1
            elif is_gap:
                open_gaps += 1
                if uid:
                    recovered_gaps += 1

            if uid:
                assigned_users.append(uid)
                cls = classify_user(dataset, r, uid)
                if cls == "Residential":
                    resident_assigned += 1
                elif cls == "FIFO":
                    fifo_assigned += 1

        assigned_demand = min(len(assigned_users), total_demand)
        remaining_gap = max(0, total_demand - assigned_demand)
        if only_disrupted_gaps and (locked_gaps + open_gaps == 0) and remaining_gap == 0:
            continue
        coverage_pct = (assigned_demand / total_demand * 100.0) if total_demand > 0 else 0.0

        if remaining_gap == 0 and total_demand > 0:
            status = "Fully Covered"
        elif assigned_demand > 0:
            status = "Partially Covered"
        else:
            status = "Unfilled"

        slot_records.append(
            {
                "Seat Key": f"{aid}@{day}T{shift}",
                "Demand ID": did or d_meta.get("Demand ID", ""),
                "Activity ID": aid,
                "Activity Name": act_name,
                "Activity Head": head,
                "Priority": priority,
                "Date": day,
                "Shift": shift,
                "Date_Shift": f"{day} {shift}",
                "Swings": ", ".join(swings_in_slot),
                "Swing List": swings_in_slot,
                "Total Demand": total_demand,
                "Assigned Demand": assigned_demand,
                "Remaining Gap": remaining_gap,
                "Coverage %": round(coverage_pct, 2),
                "Resident Assigned": resident_assigned,
                "FIFO Assigned": fifo_assigned,
                "Locked Gaps": locked_gaps,
                "Open Gaps": open_gaps,
                "Recovered Gaps": recovered_gaps,
                "Status": status,
                "Assignment IDs": ", ".join(assignment_ids),
            }
        )

    return slot_records


def compute_summary_kpis(
    dataset: DashboardDataset,
    swing_filter: set[str] | None = None,
    head_filter: set[str] | None = None,
    crew_type_filter: set[str] | None = None,
    date_filter: set[str] | None = None,
    shift_filter: set[str] | None = None,
    only_disrupted_gaps: bool = False,
) -> SummaryKPIs:
    """Compute overall KPIs from reconciled demand slots and selected work assignments."""
    slots = build_demand_slot_records(
        dataset,
        swing_filter=swing_filter,
        head_filter=head_filter,
        crew_type_filter=crew_type_filter,
        date_filter=date_filter,
        shift_filter=shift_filter,
        only_disrupted_gaps=only_disrupted_gaps,
    )

    total_demand = sum(int(s["Total Demand"]) for s in slots)
    assigned_demand = sum(int(s["Assigned Demand"]) for s in slots)
    unfilled_demand = sum(int(s["Remaining Gap"]) for s in slots)
    coverage_pct = (assigned_demand / total_demand * 100.0) if total_demand > 0 else 0.0

    resident_demand = sum(int(s["Resident Assigned"]) for s in slots)
    fifo_demand = sum(int(s["FIFO Assigned"]) for s in slots)

    fully_covered = sum(1 for s in slots if s["Status"] == "Fully Covered")
    partially_covered = sum(1 for s in slots if s["Status"] == "Partially Covered")
    unfilled_slots = sum(1 for s in slots if s["Status"] == "Unfilled")

    # Count all active selected work shifts (Demand, Excess, Relief) in horizon
    resident_work = 0
    fifo_work = 0
    total_gaps = 0
    locked_gaps = 0
    open_gaps = 0
    gaps_filled = 0

    for r in dataset.roster_rows:
        in_horizon = r.get("In Horizon", "Yes").strip()
        if in_horizon and in_horizon != "Yes":
            continue
        sw = r.get("Swing", "").strip()
        head = r.get("Activity Head", "").strip()
        day = r.get("Start Date", "").strip()
        shift = r.get("Shift Start Time", "").strip()
        if swing_filter and sw not in swing_filter:
            continue
        if head_filter and head not in head_filter:
            continue
        if date_filter and day not in date_filter:
            continue
        if shift_filter and shift not in shift_filter:
            continue

        uid = r.get("Optimised User Id", "").strip()
        orig_uid = r.get("User Id", "").strip()
        cls = classify_user(dataset, r, uid) or classify_user(dataset, r, orig_uid)
        if crew_type_filter and cls not in crew_type_filter:
            continue

        if r.get("Assignment Type") in WORK_ASSIGNMENT_TYPES and uid:
            u_cls = classify_user(dataset, r, uid)
            if u_cls == "Residential":
                resident_work += 1
            elif u_cls == "FIFO":
                fifo_work += 1

        if r.get("Assignment Type") == "Demand" and r.get("Is Gap", "").strip() == "True":
            total_gaps += 1
            if r.get("Is_locked_gap", "").strip() == "True":
                locked_gaps += 1
            else:
                open_gaps += 1
                if uid:
                    gaps_filled += 1

    gap_fill_pct = (gaps_filled / open_gaps * 100.0) if open_gaps > 0 else 0.0

    return SummaryKPIs(
        total_demand=total_demand,
        assigned_demand=assigned_demand,
        unfilled_demand=unfilled_demand,
        coverage_pct=round(coverage_pct, 2),
        resident_demand_assignments=resident_demand,
        fifo_demand_assignments=fifo_demand,
        resident_work_assignments=resident_work,
        fifo_work_assignments=fifo_work,
        total_gaps=total_gaps,
        locked_gaps=locked_gaps,
        open_gaps_to_fill=open_gaps,
        gaps_filled=gaps_filled,
        gap_fill_pct=round(gap_fill_pct, 2),
        fully_covered_slots=fully_covered,
        partially_covered_slots=partially_covered,
        unfilled_slots=unfilled_slots,
    )


def aggregate_by_activity_head(slot_records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Aggregate demand, assigned, remaining gap, and Resident/FIFO breakdown by Activity Head."""
    by_head: dict[str, dict[str, object]] = {}
    for s in slot_records:
        head = str(s["Activity Head"])
        entry = by_head.setdefault(
            head,
            {
                "Activity Head": head,
                "Priority": int(s["Priority"]),
                "Total Demand": 0,
                "Assigned Demand": 0,
                "Remaining Gap": 0,
                "Resident Assigned": 0,
                "FIFO Assigned": 0,
                "Fully Covered Slots": 0,
                "Partially Covered Slots": 0,
                "Unfilled Slots": 0,
            },
        )
        entry["Total Demand"] = int(entry["Total Demand"]) + int(s["Total Demand"])
        entry["Assigned Demand"] = int(entry["Assigned Demand"]) + int(s["Assigned Demand"])
        entry["Remaining Gap"] = int(entry["Remaining Gap"]) + int(s["Remaining Gap"])
        entry["Resident Assigned"] = int(entry["Resident Assigned"]) + int(s["Resident Assigned"])
        entry["FIFO Assigned"] = int(entry["FIFO Assigned"]) + int(s["FIFO Assigned"])
        if s["Status"] == "Fully Covered":
            entry["Fully Covered Slots"] = int(entry["Fully Covered Slots"]) + 1
        elif s["Status"] == "Partially Covered":
            entry["Partially Covered Slots"] = int(entry["Partially Covered Slots"]) + 1
        else:
            entry["Unfilled Slots"] = int(entry["Unfilled Slots"]) + 1

    result: list[dict[str, object]] = []
    for entry in by_head.values():
        td = int(entry["Total Demand"])
        ad = int(entry["Assigned Demand"])
        entry["Coverage %"] = round((ad / td * 100.0) if td > 0 else 0.0, 2)
        result.append(entry)

    result.sort(key=lambda r: (int(r["Priority"]), str(r["Activity Head"])))
    return result


def aggregate_by_swing(dataset: DashboardDataset) -> list[dict[str, object]]:
    """Aggregate Demand, Assigned, Remaining Gap, and Resident/FIFO breakdown by Swing number."""
    by_swing: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "Total Demand": 0,
            "Assigned Demand": 0,
            "Remaining Gap": 0,
            "Resident Assigned": 0,
            "FIFO Assigned": 0,
        }
    )
    for r in _in_horizon_demand_rows(dataset):
        sw = r.get("Swing", "").strip() or "Unassigned"
        uid = r.get("Optimised User Id", "").strip()
        item = by_swing[sw]
        item["Total Demand"] += 1
        if uid:
            item["Assigned Demand"] += 1
            cls = classify_user(dataset, r, uid)
            if cls == "Residential":
                item["Resident Assigned"] += 1
            elif cls == "FIFO":
                item["FIFO Assigned"] += 1
        else:
            item["Remaining Gap"] += 1

    def _swing_sort_key(sw_key: str) -> tuple[int, int | str]:
        return (0, int(sw_key)) if sw_key.isdecimal() else (1, sw_key)

    result: list[dict[str, object]] = []
    for sw in sorted(by_swing, key=_swing_sort_key):
        vals = by_swing[sw]
        td = vals["Total Demand"]
        ad = vals["Assigned Demand"]
        result.append(
            {
                "Swing": sw,
                "Total Demand": td,
                "Assigned Demand": ad,
                "Remaining Gap": vals["Remaining Gap"],
                "Coverage %": round((ad / td * 100.0) if td > 0 else 0.0, 2),
                "Resident Assigned": vals["Resident Assigned"],
                "FIFO Assigned": vals["FIFO Assigned"],
            }
        )
    return result


def build_crew_timeline_records(
    dataset: DashboardDataset,
    swing_filter: set[str] | None = None,
    crew_filter: set[str] | None = None,
    head_filter: set[str] | None = None,
    crew_type_filter: set[str] | None = None,
    include_off_and_travel: bool = True,
    include_unassigned_leave: bool = True,
    only_changed_crew: bool = False,
) -> list[dict[str, str]]:
    """Extract actual selected solver assignments per crew member for the Gantt chart.

    Reflects only selected assignments from `roster_full.csv` (never unselected candidate options).
    """
    reassignment_by_filled_row: dict[str, dict[str, str]] = {}
    moved_users: set[str] = set()
    for reass in dataset.reassignments:
        filled_row = reass.get("Filled Row", "").strip()
        opt_u = reass.get("Optimised User Id", "").strip()
        if filled_row:
            reassignment_by_filled_row[filled_row] = reass
        if opt_u:
            moved_users.add(opt_u)

    for r in dataset.roster_rows:
        opt_u = r.get("Optimised User Id", "").strip()
        new_u = r.get("New User Id", "").strip()
        note = r.get("Optimisation Note", "").strip()
        if (opt_u and opt_u != new_u) or (note and opt_u):
            moved_users.add(opt_u)

    records: list[dict[str, str]] = []
    for r in dataset.roster_rows:
        in_horizon = r.get("In Horizon", "Yes").strip()
        if in_horizon and in_horizon != "Yes":
            continue

        assign_type = r.get("Assignment Type", "").strip()
        if not include_off_and_travel and assign_type not in WORK_ASSIGNMENT_TYPES:
            continue

        opt_user = r.get("Optimised User Id", "").strip()
        orig_user = r.get("User Id", "").strip()
        new_user = r.get("New User Id", "").strip()
        leave_type = r.get("Leave Type", "").strip()

        if opt_user:
            person = opt_user
            state = "Assigned"
        elif include_unassigned_leave and orig_user and leave_type:
            person = orig_user
            state = f"Unassigned / On Leave ({leave_type})"
        else:
            continue

        if only_changed_crew and person not in moved_users:
            continue

        cls = classify_user(dataset, r, person)
        sw = r.get("Swing", "").strip()
        head = r.get("Activity Head", "").strip() or r.get("Activity Name", "").strip()

        if swing_filter and sw not in swing_filter:
            continue
        if crew_filter and person not in crew_filter:
            continue
        if head_filter and head not in head_filter:
            continue
        if crew_type_filter and cls not in crew_type_filter:
            continue

        aid_row = r.get("Assignment ID", "").strip()
        reass = reassignment_by_filled_row.get(aid_row)
        is_row_changed = bool(reass or (opt_user and opt_user != new_user) or r.get("Optimisation Note", "").strip())
        changed_status = "Reassigned / Moved" if is_row_changed else "Unchanged"
        if reass:
            reass_detail = (
                f"From {reass.get('Source', '')} ({reass.get('From Activity', '')} @ {reass.get('From Start', '')}) "
                f"-> {reass.get('Activity Name', '')} (Offset {reass.get('Offset Minutes', '0')}m, Cost {reass.get('Cost', '')})"
            )
        else:
            reass_detail = r.get("Optimisation Note", "").strip() or "Unchanged original assignment"

        start_dt = f"{r.get('Start Date', '').strip()}T{r.get('Shift Start Time', '00:00').strip()}"
        end_dt = f"{r.get('End Date', '').strip()}T{r.get('Shift End Time', '00:00').strip()}"

        records.append(
            {
                "Assignment ID": aid_row,
                "User Id": person,
                "Crew Label": f"{person} ({cls or 'Unknown'})",
                "Crew Classification": cls or "Unknown",
                "Swing": sw,
                "Activity ID": r.get("Activity ID", ""),
                "Activity Name": r.get("Activity Name", ""),
                "Activity Head": head if state == "Assigned" else f"Unassigned ({head})",
                "Raw Activity Head": head,
                "Assignment Type": assign_type,
                "State": state,
                "Changed": changed_status,
                "Reassignment Detail": reass_detail,
                "Start": start_dt,
                "End": end_dt,
                "Start Date": r.get("Start Date", ""),
                "Shift Start Time": r.get("Shift Start Time", ""),
                "Shift End Time": r.get("Shift End Time", ""),
                "Start Location": r.get("Start Location", ""),
                "End Location": r.get("End Location", ""),
                "Optimisation Note": r.get("Optimisation Note", ""),
            }
        )

    records.sort(key=lambda x: (x["Crew Classification"], x["User Id"], x["Start"]))
    return records


def compare_strategy_datasets(datasets: dict[str, DashboardDataset]) -> dict[str, object]:
    """Compare KPIs, Activity Head coverage, and Priority coverage across multiple strategy runs."""
    overall_rows: list[dict[str, object]] = []
    by_head_rows: list[dict[str, object]] = []
    by_priority_rows: list[dict[str, object]] = []

    for label, ds in datasets.items():
        kpis = compute_summary_kpis(ds)
        slots = build_demand_slot_records(ds)
        head_agg = aggregate_by_activity_head(slots)

        overall_rows.append(
            {
                "Strategy": label,
                "Configured Strategy": str(ds.config_flags.get("priority_strategy", "none")),
                "Total Demand": kpis.total_demand,
                "Assigned Demand": kpis.assigned_demand,
                "Remaining Gaps": kpis.unfilled_demand,
                "Coverage %": kpis.coverage_pct,
                "Open Gaps Filled": f"{kpis.gaps_filled}/{kpis.open_gaps_to_fill}",
                "Gap Recovery %": kpis.gap_fill_pct,
                "Resident Assignments": kpis.resident_demand_assignments,
                "FIFO Assignments": kpis.fifo_demand_assignments,
            }
        )

        prio_totals: dict[int, dict[str, int]] = defaultdict(
            lambda: {"Total Demand": 0, "Assigned Demand": 0, "Remaining Gap": 0}
        )
        for h in head_agg:
            by_head_rows.append(
                {
                    "Strategy": label,
                    "Activity Head": h["Activity Head"],
                    "Priority": h["Priority"],
                    "Total Demand": h["Total Demand"],
                    "Assigned Demand": h["Assigned Demand"],
                    "Remaining Gap": h["Remaining Gap"],
                    "Coverage %": h["Coverage %"],
                }
            )
            p = int(h["Priority"])
            prio_totals[p]["Total Demand"] += int(h["Total Demand"])
            prio_totals[p]["Assigned Demand"] += int(h["Assigned Demand"])
            prio_totals[p]["Remaining Gap"] += int(h["Remaining Gap"])

        for p, p_vals in sorted(prio_totals.items()):
            td = p_vals["Total Demand"]
            ad = p_vals["Assigned Demand"]
            by_priority_rows.append(
                {
                    "Strategy": label,
                    "Priority": p,
                    "Total Demand": td,
                    "Assigned Demand": ad,
                    "Remaining Gap": p_vals["Remaining Gap"],
                    "Coverage %": round((ad / td * 100.0) if td > 0 else 0.0, 2),
                }
            )

    return {
        "overall": overall_rows,
        "by_head": by_head_rows,
        "by_priority": by_priority_rows,
    }
