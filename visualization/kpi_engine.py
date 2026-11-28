"""Pure, unit-testable KPI engine, depot/priority aggregations, operational brief, and cross-run deltas."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from visualization.data_loader import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_OPTIONS_DIR,
    ROOT,
    DashboardDataset,
)
from visualization.gap_analysis import parse_summary_and_validation
from visualization.metrics import (
    WORK_ASSIGNMENT_TYPES,
    build_demand_slot_records,
    classify_user,
    compute_summary_kpis,
)


def discover_solver_runs(base_root: Path = ROOT) -> dict[str, dict[str, Path]]:
    """Discover available solver output directories under `CP-SAT/outputs/`."""
    outputs_root = base_root / "CP-SAT" / "outputs"
    runs: dict[str, dict[str, Path]] = {}

    v2_data = base_root / "data" / "optiflux_v2"
    v1_data = base_root / "data" / "optiflux_v1_data_08_05_2026"
    data_dir = v2_data if v2_data.exists() else DEFAULT_DATA_DIR
    options_dir = base_root / "option_generation" / "output"
    config_path = base_root / "config.yml" if (base_root / "config.yml").exists() else DEFAULT_CONFIG_PATH

    if outputs_root.exists():
        candidates = sorted(
            [p for p in outputs_root.iterdir() if p.is_dir() and (p / "roster_full.csv").exists()],
            key=lambda p: (0 if p.name == "roster_full" else 1, -p.stat().st_mtime, p.name),
        )
        for folder in candidates:
            label = (
                "OptiFlux v2 (roster_full)"
                if folder.name == "roster_full"
                else f"Run: {folder.name}"
            )
            runs[label] = {
                "data_dir": data_dir,
                "cpsat_dir": folder,
                "options_dir": options_dir if options_dir.exists() else DEFAULT_OPTIONS_DIR,
                "config_path": config_path,
            }
        whatif_root = outputs_root / "whatif"
        if whatif_root.exists():
            whatif_candidates = sorted(
                [p for p in whatif_root.iterdir() if p.is_dir() and (p / "roster_full.csv").exists()],
                key=lambda p: (-p.stat().st_mtime, p.name),
            )
            for folder in whatif_candidates:
                runs[f"What-If: {folder.name}"] = {
                    "data_dir": data_dir,
                    "cpsat_dir": folder,
                    "options_dir": options_dir if options_dir.exists() else DEFAULT_OPTIONS_DIR,
                    "config_path": config_path,
                }

    if v1_data.exists() and (outputs_root / "roster_full" / "roster_full.csv").exists():
        runs["OptiFlux v1 (08_05_2026)"] = {
            "data_dir": v1_data,
            "cpsat_dir": outputs_root / "roster_full",
            "options_dir": options_dir if options_dir.exists() else DEFAULT_OPTIONS_DIR,
            "config_path": config_path,
        }

    return runs


def _extract_runtime_seconds(summary_items: dict[str, str]) -> float | None:
    raw = summary_items.get("Solve time", "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", raw)
    return float(match.group(1)) if match else None


def _extract_cost(stages: list[dict[str, str]]) -> int | None:
    for stg in stages:
        details = stg.get("Details", "")
        m = re.search(r"cost\s+(\d+)", details, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _build_activity_depot_map(dataset: DashboardDataset) -> dict[str, str]:
    """Map `Activity ID` to its canonical `Start Location` (Depot) from activities, seats, demand, or roster."""
    activity_depot: dict[str, str] = {}
    for source in (dataset.activities_rows, dataset.seats, dataset.demand_rows, dataset.roster_rows):
        for r in source:
            aid = r.get("Activity ID", "").strip()
            loc = (r.get("Start Location", "") or r.get("Location", "")).strip()
            if aid and loc and aid not in activity_depot:
                activity_depot[aid] = loc
    return activity_depot


def compute_extended_kpis(
    dataset: DashboardDataset,
    swing_filter: set[str] | None = None,
    head_filter: set[str] | None = None,
    crew_type_filter: set[str] | None = None,
    date_filter: set[str] | None = None,
    shift_filter: set[str] | None = None,
    depot_filter: set[str] | None = None,
    priority_filter: set[int] | None = None,
) -> dict[str, Any]:
    """Compute comprehensive Page 1 KPIs with exact source reconciliation."""
    base_kpis = compute_summary_kpis(
        dataset,
        swing_filter=swing_filter,
        head_filter=head_filter,
        crew_type_filter=crew_type_filter,
        date_filter=date_filter,
        shift_filter=shift_filter,
    )
    slots = build_demand_slot_records(
        dataset,
        swing_filter=swing_filter,
        head_filter=head_filter,
        crew_type_filter=crew_type_filter,
        date_filter=date_filter,
        shift_filter=shift_filter,
    )

    activity_depot = _build_activity_depot_map(dataset)

    if depot_filter or priority_filter:
        filtered_slots = []
        for s in slots:
            aid = str(s.get("Activity ID", ""))
            depot = activity_depot.get(aid, "Unknown")
            prio = int(s.get("Priority", 999))
            if depot_filter and depot not in depot_filter:
                continue
            if priority_filter and prio not in priority_filter:
                continue
            filtered_slots.append(s)
        slots = filtered_slots

    total_demand = sum(int(s["Total Demand"]) for s in slots)
    assigned_demand = sum(int(s["Assigned Demand"]) for s in slots)
    unfilled_demand = sum(int(s["Remaining Gap"]) for s in slots)
    coverage_pct = round((assigned_demand / total_demand * 100.0) if total_demand > 0 else 0.0, 2)

    demand_assignments = 0
    relief_assignments = 0
    excess_assignments = 0
    resident_work = 0
    fifo_work = 0
    unique_crews: set[str] = set()
    reassigned_crews: set[str] = set()
    reassigned_rows = 0

    for r in dataset.roster_rows:
        in_horizon = r.get("In Horizon", "Yes").strip()
        if in_horizon and in_horizon != "Yes":
            continue
        sw = r.get("Swing", "").strip()
        head = r.get("Activity Head", "").strip()
        day = r.get("Start Date", "").strip()
        shift = r.get("Shift Start Time", "").strip()
        depot = r.get("Start Location", "").strip()
        prio = dataset.priority_by_head.get(head, 999)

        if swing_filter and sw not in swing_filter:
            continue
        if head_filter and head not in head_filter:
            continue
        if date_filter and day not in date_filter:
            continue
        if shift_filter and shift not in shift_filter:
            continue
        if depot_filter and depot not in depot_filter:
            continue
        if priority_filter and prio not in priority_filter:
            continue

        uid = r.get("Optimised User Id", "").strip()
        new_uid = r.get("New User Id", "").strip()
        orig_uid = r.get("User Id", "").strip()
        cls = classify_user(dataset, r, uid) or classify_user(dataset, r, orig_uid)
        if crew_type_filter and cls not in crew_type_filter:
            continue

        atype = r.get("Assignment Type", "").strip()
        if atype in WORK_ASSIGNMENT_TYPES and uid:
            unique_crews.add(uid)
            if atype == "Demand":
                demand_assignments += 1
            elif atype == "Relief":
                relief_assignments += 1
            elif atype == "Excess":
                excess_assignments += 1

            u_cls = classify_user(dataset, r, uid)
            if u_cls == "Residential":
                resident_work += 1
            elif u_cls == "FIFO":
                fifo_work += 1

        if uid != new_uid:
            reassigned_rows += 1
            if uid:
                reassigned_crews.add(uid)
            if new_uid:
                reassigned_crews.add(new_uid)

    for ra in dataset.reassignments:
        u = ra.get("User Id", "").strip()
        if u:
            reassigned_crews.add(u)

    parsed_meta = parse_summary_and_validation(dataset)
    stages = parsed_meta.get("stages", [])
    statuses = [str(s.get("Status", "")) for s in stages if s.get("Status")]
    if statuses and all(st == "OPTIMAL" for st in statuses):
        solver_status = "OPTIMAL"
    elif any(st == "FEASIBLE" for st in statuses):
        solver_status = "FEASIBLE"
    elif statuses:
        solver_status = statuses[-1]
    else:
        solver_status = "COMPLETED"

    runtime_sec = _extract_runtime_seconds(parsed_meta.get("summary_items", {}))
    solver_cost = _extract_cost(stages)

    return {
        "total_demand": total_demand,
        "assigned_demand": assigned_demand,
        "unfilled_demand": unfilled_demand,
        "coverage_pct": coverage_pct,
        "total_gaps": base_kpis.total_gaps,
        "locked_gaps": base_kpis.locked_gaps,
        "open_gaps_to_fill": base_kpis.open_gaps_to_fill,
        "gaps_filled": base_kpis.gaps_filled,
        "gap_fill_pct": base_kpis.gap_fill_pct,
        "total_selected_work_assignments": demand_assignments + relief_assignments + excess_assignments,
        "demand_assignments": demand_assignments,
        "relief_assignments": relief_assignments,
        "excess_assignments": excess_assignments,
        "resident_demand_assignments": sum(int(s["Resident Assigned"]) for s in slots),
        "fifo_demand_assignments": sum(int(s["FIFO Assigned"]) for s in slots),
        "resident_work_assignments": resident_work,
        "fifo_work_assignments": fifo_work,
        "unique_assigned_crews": len(unique_crews),
        "reassigned_crew_count": len(reassigned_crews),
        "reassigned_row_count": len(dataset.reassignments) or reassigned_rows,
        "solver_status": solver_status,
        "solver_runtime_sec": runtime_sec,
        "solver_cost": solver_cost,
    }


def generate_operational_brief(
    dataset: DashboardDataset,
    slot_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate a data-driven Executive Operational Brief synthesizing Priority 1 coverage and top bottlenecks."""
    slots = slot_records if slot_records is not None else build_demand_slot_records(dataset)
    activity_depot = _build_activity_depot_map(dataset)

    p1_slots = [s for s in slots if int(s.get("Priority", 999)) == 1]
    p1_demand = sum(int(s["Total Demand"]) for s in p1_slots)
    p1_assigned = sum(int(s["Assigned Demand"]) for s in p1_slots)
    p1_cov_pct = round((p1_assigned / p1_demand * 100.0) if p1_demand > 0 else 100.0, 2)

    total_demand = sum(int(s["Total Demand"]) for s in slots)
    total_assigned = sum(int(s["Assigned Demand"]) for s in slots)
    total_unfilled = sum(int(s["Remaining Gap"]) for s in slots)
    overall_cov_pct = round((total_assigned / total_demand * 100.0) if total_demand > 0 else 0.0, 2)

    gap_by_depot: dict[str, int] = defaultdict(int)
    gap_by_shift: dict[str, int] = defaultdict(int)
    gap_by_head: dict[str, int] = defaultdict(int)

    for s in slots:
        rem = int(s["Remaining Gap"])
        if rem <= 0:
            continue
        aid = str(s.get("Activity ID", ""))
        depot = activity_depot.get(aid, "Unknown")
        shift = str(s.get("Shift", "Unknown"))
        head = str(s.get("Activity Head", "Unknown"))
        gap_by_depot[depot] += rem
        gap_by_shift[shift] += rem
        gap_by_head[head] += rem

    top_depot = max(gap_by_depot.items(), key=lambda x: (x[1], x[0]))[0] if gap_by_depot else "None"
    top_depot_gaps = gap_by_depot.get(top_depot, 0)
    top_shift = max(gap_by_shift.items(), key=lambda x: (x[1], x[0]))[0] if gap_by_shift else "None"
    top_shift_gaps = gap_by_shift.get(top_shift, 0)
    top_head = max(gap_by_head.items(), key=lambda x: (x[1], x[0]))[0] if gap_by_head else "None"
    top_head_gaps = gap_by_head.get(top_head, 0)

    if total_unfilled == 0:
        narrative = (
            f"Full Coverage Achieved: 100.0% of demand ({total_assigned:,}/{total_demand:,} crew-shifts) "
            f"and {p1_cov_pct:.1f}% of Priority 1 demand are met with zero remaining unfilled gaps."
        )
    else:
        narrative = (
            f"Coverage Alert: {overall_cov_pct:.2f}% of total demand is met ({p1_cov_pct:.1f}% of Priority 1 demand). "
            f"Remaining unfilled gaps ({total_unfilled:,} crew-shifts) are concentrated in Depot **{top_depot}** "
            f"({top_depot_gaps} gaps), during the **{top_shift}** shift ({top_shift_gaps} gaps), "
            f"led by Activity Head **{top_head}** ({top_head_gaps} gaps)."
        )

    return {
        "narrative": narrative,
        "overall_coverage_pct": overall_cov_pct,
        "p1_coverage_pct": p1_cov_pct,
        "total_unfilled": total_unfilled,
        "top_depot": top_depot,
        "top_depot_gaps": top_depot_gaps,
        "top_shift": top_shift,
        "top_shift_gaps": top_shift_gaps,
        "top_head": top_head,
        "top_head_gaps": top_head_gaps,
    }


def aggregate_by_depot(
    dataset: DashboardDataset,
    slot_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate Demand, Assigned, Remaining Gap, Coverage %, and Resident/FIFO by Start Depot."""
    slots = slot_records if slot_records is not None else build_demand_slot_records(dataset)
    activity_depot = _build_activity_depot_map(dataset)

    by_depot: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "Total Demand": 0,
            "Assigned Demand": 0,
            "Remaining Gap": 0,
            "Resident Assigned": 0,
            "FIFO Assigned": 0,
        }
    )
    for s in slots:
        aid = str(s.get("Activity ID", ""))
        depot = activity_depot.get(aid, "Unknown")
        item = by_depot[depot]
        item["Total Demand"] += int(s["Total Demand"])
        item["Assigned Demand"] += int(s["Assigned Demand"])
        item["Remaining Gap"] += int(s["Remaining Gap"])
        item["Resident Assigned"] += int(s["Resident Assigned"])
        item["FIFO Assigned"] += int(s["FIFO Assigned"])

    rows: list[dict[str, Any]] = []
    for depot, vals in sorted(by_depot.items()):
        td = vals["Total Demand"]
        ad = vals["Assigned Demand"]
        rows.append(
            {
                "Depot": depot,
                "Total Demand": td,
                "Assigned Demand": ad,
                "Remaining Gap": vals["Remaining Gap"],
                "Coverage %": round((ad / td * 100.0) if td > 0 else 0.0, 2),
                "Resident Assigned": vals["Resident Assigned"],
                "FIFO Assigned": vals["FIFO Assigned"],
            }
        )
    return rows


def aggregate_by_depot_and_head(
    dataset: DashboardDataset,
    slot_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate Demand, Assigned, Remaining Gap, and Coverage % across `Activity Head x Depot`."""
    slots = slot_records if slot_records is not None else build_demand_slot_records(dataset)
    activity_depot = _build_activity_depot_map(dataset)

    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"Total Demand": 0, "Assigned Demand": 0, "Remaining Gap": 0, "Priority": 999}
    )
    for s in slots:
        aid = str(s.get("Activity ID", ""))
        depot = activity_depot.get(aid, "Unknown")
        head = str(s.get("Activity Head", ""))
        item = grouped[(head, depot)]
        item["Total Demand"] += int(s["Total Demand"])
        item["Assigned Demand"] += int(s["Assigned Demand"])
        item["Remaining Gap"] += int(s["Remaining Gap"])
        item["Priority"] = int(s.get("Priority", 999))

    rows: list[dict[str, Any]] = []
    for (head, depot), vals in sorted(grouped.items(), key=lambda x: (x[1]["Priority"], x[0][0], x[0][1])):
        td = vals["Total Demand"]
        ad = vals["Assigned Demand"]
        rows.append(
            {
                "Activity Head": head,
                "Depot": depot,
                "Priority": vals["Priority"],
                "Total Demand": td,
                "Assigned Demand": ad,
                "Remaining Gap": vals["Remaining Gap"],
                "Coverage %": round((ad / td * 100.0) if td > 0 else 0.0, 2),
            }
        )
    return rows


def aggregate_by_priority_tier(slot_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate Demand, Filled, Unfilled, Fill Rate %, and Cumulative Coverage % ordered by Priority tier."""
    by_prio: dict[int, dict[str, Any]] = {}
    for s in slot_records:
        p = int(s["Priority"])
        head = str(s["Activity Head"])
        entry = by_prio.setdefault(
            p,
            {
                "Priority": p,
                "Activity Heads": set(),
                "Total Demand": 0,
                "Assigned Demand": 0,
                "Remaining Gap": 0,
                "Resident Assigned": 0,
                "FIFO Assigned": 0,
            },
        )
        entry["Activity Heads"].add(head)
        entry["Total Demand"] = int(entry["Total Demand"]) + int(s["Total Demand"])
        entry["Assigned Demand"] = int(entry["Assigned Demand"]) + int(s["Assigned Demand"])
        entry["Remaining Gap"] = int(entry["Remaining Gap"]) + int(s["Remaining Gap"])
        entry["Resident Assigned"] = int(entry["Resident Assigned"]) + int(s["Resident Assigned"])
        entry["FIFO Assigned"] = int(entry["FIFO Assigned"]) + int(s["FIFO Assigned"])

    rows: list[dict[str, Any]] = []
    cum_demand = 0
    cum_assigned = 0
    for p in sorted(by_prio):
        entry = by_prio[p]
        td = int(entry["Total Demand"])
        ad = int(entry["Assigned Demand"])
        cum_demand += td
        cum_assigned += ad
        rows.append(
            {
                "Priority": p,
                "Activity Heads": ", ".join(sorted(entry["Activity Heads"])),
                "Total Demand": td,
                "Assigned Demand": ad,
                "Remaining Gap": int(entry["Remaining Gap"]),
                "Coverage %": round((ad / td * 100.0) if td > 0 else 0.0, 2),
                "Cumulative Coverage %": round((cum_assigned / cum_demand * 100.0) if cum_demand > 0 else 0.0, 2),
                "Resident Assigned": int(entry["Resident Assigned"]),
                "FIFO Assigned": int(entry["FIFO Assigned"]),
            }
        )
    return rows


def compute_cross_run_deltas(
    active_ds: DashboardDataset,
    baseline_ds: DashboardDataset,
) -> dict[str, Any]:
    """Compute delta metrics between `active_ds` and `baseline_ds`."""
    active_kpis = compute_extended_kpis(active_ds)
    base_kpis = compute_extended_kpis(baseline_ds)

    active_cost = active_kpis["solver_cost"]
    base_cost = base_kpis["solver_cost"]
    delta_cost = (int(active_cost) - int(base_cost)) if (active_cost is not None and base_cost is not None) else None

    return {
        "active_name": active_ds.name,
        "baseline_name": baseline_ds.name,
        "active": active_kpis,
        "baseline": base_kpis,
        "delta_coverage_pct": round(float(active_kpis["coverage_pct"]) - float(base_kpis["coverage_pct"]), 2),
        "delta_gap_fill_pct": round(float(active_kpis["gap_fill_pct"]) - float(base_kpis["gap_fill_pct"]), 2),
        "delta_gaps_filled": int(active_kpis["gaps_filled"]) - int(base_kpis["gaps_filled"]),
        "delta_unfilled_demand": int(active_kpis["unfilled_demand"]) - int(base_kpis["unfilled_demand"]),
        "delta_reassigned_crews": int(active_kpis["reassigned_crew_count"]) - int(base_kpis["reassigned_crew_count"]),
        "delta_cost": delta_cost,
    }
