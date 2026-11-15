"""Dedicated OR reconciliation, KPI engine, and post-solve QA tests (`tests/test_dashboard_analytics.py`)."""

from __future__ import annotations

from copy import deepcopy

from visualization.charts import (
    create_assignment_type_donut_charts,
    create_depot_coverage_chart,
    create_fill_rate_gauge_chart,
    create_head_depot_coverage_heatmap,
    create_priority_adherence_waterfall_chart,
)
from visualization.data_loader import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_CPSAT_DIR,
    DEFAULT_DATA_DIR,
    DEFAULT_OPTIONS_DIR,
    load_dashboard_dataset,
)
from visualization.kpi_engine import (
    aggregate_by_depot,
    aggregate_by_depot_and_head,
    aggregate_by_priority_tier,
    compute_cross_run_deltas,
    compute_extended_kpis,
    discover_solver_runs,
    generate_operational_brief,
)
from visualization.metrics import (
    aggregate_by_activity_head,
    build_crew_timeline_records,
    build_demand_slot_records,
    compute_summary_kpis,
)
from visualization.schema import (
    DEMAND_COLUMNS,
    PRIORITY_COLUMNS,
    ROSTER_COLUMNS,
    SEMANTIC_COLORS,
    WORK_ASSIGNMENT_TYPES,
)
from visualization.validators import run_post_solve_qa_suite


def _load_real_dataset():
    return load_dashboard_dataset(
        data_dir=DEFAULT_DATA_DIR,
        cpsat_dir=DEFAULT_CPSAT_DIR,
        options_dir=DEFAULT_OPTIONS_DIR,
        config_path=DEFAULT_CONFIG_PATH,
    )


def test_schema_constants_and_run_discovery():
    assert "Optimised User Id" in ROSTER_COLUMNS
    assert "Demand" in DEMAND_COLUMNS
    assert "Priority" in PRIORITY_COLUMNS
    assert set(WORK_ASSIGNMENT_TYPES) == {"Demand", "Excess", "Relief"}
    assert SEMANTIC_COLORS["filled"] == "#10B981"
    assert SEMANTIC_COLORS["unfilled"] == "#EF4444"

    runs = discover_solver_runs()
    assert runs
    assert "OptiFlux v2 (roster_full)" in runs


def test_demand_reconciliation_across_all_dimensions():
    ds = _load_real_dataset()
    kpis = compute_summary_kpis(ds)
    ext = compute_extended_kpis(ds)
    slots = build_demand_slot_records(ds)

    # Overall reconciliation
    assert kpis.assigned_demand + kpis.unfilled_demand == kpis.total_demand
    assert ext["assigned_demand"] + ext["unfilled_demand"] == ext["total_demand"] == kpis.total_demand
    assert ext["resident_demand_assignments"] + ext["fifo_demand_assignments"] == ext["assigned_demand"]

    # Slot-level reconciliation
    for s in slots:
        assert int(s["Assigned Demand"]) + int(s["Remaining Gap"]) == int(s["Total Demand"])

    # Activity Head reconciliation
    head_rows = aggregate_by_activity_head(slots)
    assert sum(int(r["Total Demand"]) for r in head_rows) == kpis.total_demand
    assert sum(int(r["Assigned Demand"]) for r in head_rows) == kpis.assigned_demand
    assert sum(int(r["Remaining Gap"]) for r in head_rows) == kpis.unfilled_demand

    # Depot reconciliation
    depot_rows = aggregate_by_depot(ds, slots)
    assert sum(int(r["Total Demand"]) for r in depot_rows) == kpis.total_demand
    assert sum(int(r["Assigned Demand"]) for r in depot_rows) == kpis.assigned_demand
    assert sum(int(r["Remaining Gap"]) for r in depot_rows) == kpis.unfilled_demand

    # Priority tier reconciliation
    prio_rows = aggregate_by_priority_tier(slots)
    assert sum(int(r["Total Demand"]) for r in prio_rows) == kpis.total_demand
    assert sum(int(r["Assigned Demand"]) for r in prio_rows) == kpis.assigned_demand
    assert sum(int(r["Remaining Gap"]) for r in prio_rows) == kpis.unfilled_demand


def test_zero_unselected_candidate_options_leak_into_active_assignments():
    ds = _load_real_dataset()
    assert len(ds.gap_options) > 0  # Layer-1 candidate options exist

    # Active timeline and KPIs use only roster_full.csv rows, never unselected gap_options
    ds_without_options = deepcopy(ds)
    ds_without_options.gap_options = []

    ext_with = compute_extended_kpis(ds)
    ext_without = compute_extended_kpis(ds_without_options)
    assert ext_with["total_selected_work_assignments"] == ext_without["total_selected_work_assignments"]
    assert ext_with["assigned_demand"] == ext_without["assigned_demand"]

    timeline = build_crew_timeline_records(ds, include_off_and_travel=False, include_unassigned_leave=False)
    roster_aids = {r["Assignment ID"] for r in ds.roster_rows if r.get("Optimised User Id", "").strip()}
    for rec in timeline:
        assert rec["Assignment ID"] in roster_aids


def test_post_solve_qa_suite_passes_clean_roster_and_catches_synthetic_overlap():
    ds = _load_real_dataset()
    qa = run_post_solve_qa_suite(ds)

    assert qa["total_checks"] == 6
    assert qa["failed_critical"] == 0
    by_id = {c["Check ID"]: c for c in qa["checks"]}
    assert by_id["QA1"]["Status"] == "PASS"
    assert by_id["QA2"]["Status"] == "PASS"
    assert by_id["QA3"]["Status"] == "PASS"
    assert by_id["QA5"]["Status"] == "PASS"
    assert by_id["QA6"]["Status"] == "PASS"

    # Inject a synthetic overlapping shift for the same crew member and verify QA2 catches it
    ds_bad = deepcopy(ds)
    work_rows = [
        r for r in ds_bad.roster_rows
        if r.get("Assignment Type") == "Demand" and r.get("Optimised User Id", "").strip()
    ]
    dup_shift = deepcopy(work_rows[0])
    dup_shift["Assignment ID"] = "SYNTHETIC_OVERLAP_999999"
    ds_bad.roster_rows.append(dup_shift)

    qa_bad = run_post_solve_qa_suite(ds_bad)
    by_id_bad = {c["Check ID"]: c for c in qa_bad["checks"]}
    assert by_id_bad["QA2"]["Status"] == "FAIL"
    assert by_id_bad["QA2"]["Violations"] >= 1
    assert qa_bad["failed_critical"] >= 1


def test_extended_kpis_brief_and_new_charts_deterministic():
    ds = _load_real_dataset()
    slots = build_demand_slot_records(ds)
    ext = compute_extended_kpis(ds)
    brief = generate_operational_brief(ds, slots)
    deltas = compute_cross_run_deltas(ds, ds)

    assert ext["total_selected_work_assignments"] == (
        ext["demand_assignments"] + ext["relief_assignments"] + ext["excess_assignments"]
    )
    assert ext["unique_assigned_crews"] > 0
    assert ext["reassigned_crew_count"] > 0
    assert brief["narrative"]
    assert deltas["delta_coverage_pct"] == 0.0
    assert deltas["delta_unfilled_demand"] == 0

    depot_rows = aggregate_by_depot(ds, slots)
    head_depot_rows = aggregate_by_depot_and_head(ds, slots)
    prio_rows = aggregate_by_priority_tier(slots)

    assert create_fill_rate_gauge_chart(float(ext["coverage_pct"]), float(ext["gap_fill_pct"])) is not None
    donuts = create_assignment_type_donut_charts(ext)
    assert "assignment_type" in donuts and "crew_classification" in donuts
    assert create_depot_coverage_chart(depot_rows) is not None
    assert create_head_depot_coverage_heatmap(head_depot_rows) is not None
    assert create_priority_adherence_waterfall_chart(prio_rows) is not None
