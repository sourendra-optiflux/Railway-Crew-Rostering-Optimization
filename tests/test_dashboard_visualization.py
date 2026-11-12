from __future__ import annotations

from pathlib import Path

import pytest

from visualization.charts import (
    create_crew_gantt_chart,
    create_demand_coverage_heatmap,
    create_gap_summary_charts,
    create_shift_limit_utilization_chart,
    create_strategy_comparison_charts,
)
from visualization.data_loader import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_CPSAT_DIR,
    DEFAULT_DATA_DIR,
    DEFAULT_OPTIONS_DIR,
    discover_strategy_datasets,
    load_dashboard_dataset,
    read_csv_safe,
)
from visualization.gap_analysis import (
    build_constraint_diagnostics,
    build_unfilled_gap_records,
    inspect_seat_candidates,
    parse_summary_and_validation,
    summarize_gaps,
)
from visualization.metrics import (
    aggregate_by_activity_head,
    aggregate_by_swing,
    build_crew_timeline_records,
    build_demand_slot_records,
    compare_strategy_datasets,
    compute_summary_kpis,
)


def _write_controlled_dataset(tmp_path: Path, duplicate_roster_row: bool = False) -> tuple[Path, Path, Path, Path]:
    """Create a small, controlled dataset covering full, partial, and unfilled demand slots."""
    data_dir = tmp_path / "data"
    cpsat_dir = tmp_path / "cpsat"
    opts_dir = tmp_path / "options"
    cfg_path = tmp_path / "config.yml"
    data_dir.mkdir(parents=True, exist_ok=True)
    cpsat_dir.mkdir(parents=True, exist_ok=True)
    opts_dir.mkdir(parents=True, exist_ok=True)

    cfg_path.write_text(
        "constraints:\n"
        "  residential_start_restriction: true\n"
        "  relief_only_day_night_transition: true\n\n"
        "optimization:\n"
        "  priority_strategy: weighted\n",
        encoding="utf-8",
    )

    (data_dir / "activity_demand_df.csv").write_text(
        "Demand ID,Shift,Demand,Is Active,Activity ID,Activity Name,Activity Head\n"
        "DM001,06:00,2,Yes,A06,Madison Crew,Madison Crew\n"
        "DM002,08:00,1,Yes,A16,NE Crew,NE Crew\n"
        "DM003,10:00,1,Yes,A12,BY Ship,BY Ship\n",
        encoding="utf-8",
    )
    (data_dir / "activity_priority.csv").write_text(
        "Priority,Activity Head,Max Resident Shifts,Max FIFO Shifts\n"
        "1,Madison Crew,2,4\n"
        "2,NE Crew,3,5\n"
        "3,BY Ship,2,4\n",
        encoding="utf-8",
    )
    (data_dir / "crew_master_data_df.csv").write_text(
        "User Id,Classification,Eligibility,Depot,Role,Is Mentor,Medical,Position\n"
        "U_RES_1,Residential,A06;A16;A12,Haskett,Driver,No,Fit,L1\n"
        "U_FIFO_1,FIFO,A06;A16;A12,Haskett,Driver,No,Fit,L2\n"
        "U_RES_LEAVE,Residential,A06;A16;A12,Haskett,Driver,No,Fit,L3\n",
        encoding="utf-8",
    )
    (data_dir / "constraints_df.csv").write_text(
        "Constraint,Value,Status\n"
        "Solver Start Date,2026-11-06,Active\n"
        "Ordinary Rest Hours,11,Active\n"
        "Transition Rest Hours,23,Active\n"
        "Max Start Changes Per Block,1,Active\n"
        "Max Start Change Minutes,60,Active\n"
        "Activity Head Max Shifts,,Active\n",
        encoding="utf-8",
    )

    roster_lines = [
        "Assignment ID,User Id,New User Id,Optimised User Id,Start Date,End Date,Shift Start Time,Shift End Time,"
        "Activity ID,Activity Name,Is Locked,Activity Head,Activity Type,Activity Group,Assignment Type,Demand ID,"
        "Start Location,End Location,Line ID,Swing,In Horizon,Leave Type,Is Gap,Is_locked_gap,Crew Classification,Optimisation Note",
        # Slot 1: DM001 on 2026-11-07 06:00 (Demand = 2): 1 filled by Residential, 1 unfilled gap -> Partially Covered!
        "AS1,U_RES_1,U_RES_1,U_RES_1,2026-11-07,2026-11-07,06:00,18:00,A06,Madison Crew,False,Madison Crew,Crew,Yard,"
        "Demand,DM001,Haskett,Haskett,L1,1,Yes,,False,False,Residential,",
        "AS2,U_RES_LEAVE,,,2026-11-07,2026-11-07,06:00,18:00,A06,Madison Crew,False,Madison Crew,Crew,Yard,"
        "Demand,DM001,Haskett,Haskett,L3,1,Yes,Random,True,False,,",
        # Slot 2: DM002 on 2026-11-07 08:00 (Demand = 1): 1 filled by FIFO -> Fully Covered!
        "AS3,U_RES_LEAVE,,U_FIFO_1,2026-11-07,2026-11-07,08:00,20:00,A16,NE Crew,False,NE Crew,Crew,Yard,"
        "Demand,DM002,Haskett,Haskett,L2,2,Yes,Random,True,False,FIFO,filled by U_FIFO_1",
        # Slot 3: DM003 on 2026-11-04 10:00 (Demand = 1): 1 locked gap before Solver Start Date -> Completely Unfilled!
        "AS4,U_RES_LEAVE,,,2026-11-04,2026-11-04,10:00,22:00,A12,BY Ship,False,BY Ship,Shed,Yard,"
        "Demand,DM003,Haskett,Haskett,L3,1,Yes,Full Swing,True,True,,",
    ]
    if duplicate_roster_row:
        roster_lines.append(roster_lines[1])  # duplicate AS1 row

    (cpsat_dir / "roster_full.csv").write_text("\n".join(roster_lines) + "\n", encoding="utf-8")
    (cpsat_dir / "unfilled_gaps.csv").write_text(
        "Assignment ID,Date,Start,Activity ID,Activity Name,Original User Id,Kind,Is_locked_gap,Leave Type\n"
        "AS2,2026-11-07,06:00,A06,Madison Crew,U_RES_LEAVE,gap,False,Random\n"
        "AS4,2026-11-04,10:00,A12,BY Ship,U_RES_LEAVE,gap,True,Full Swing\n",
        encoding="utf-8",
    )
    (opts_dir / "gap_options.csv").write_text(
        "Seat Key,Chain Level,Date,Start,Activity Name,Open Seats,Gap Assignment IDs,Candidate User Id,Source,Candidate Row,Candidate Row Start,Offset Minutes,Cost\n",
        encoding="utf-8",
    )
    (opts_dir / "rejections.csv").write_text(
        "Seat Key,Reason,Rows Rejected\n"
        "A06@2026-11-07T06:00,not certified (eligibility matrix),4\n",
        encoding="utf-8",
    )
    (opts_dir / "swings.csv").write_text(
        "Swing Key,User Id,Swing,Classification,Home Depot,Status,Reason,Earliest Start,Latest End,In Model,Rows,Droppable Rows\n"
        "U_RES_1|1,U_RES_1,1,Residential,Haskett,movable,,2026-11-07T06:00,2026-11-07T18:00,True,AS1,\n"
        "U_RES_LEAVE|1,U_RES_LEAVE,1,Residential,Haskett,frozen,swing partly on leave,2026-11-04T10:00,2026-11-07T18:00,False,AS4;AS2,\n",
        encoding="utf-8",
    )
    return data_dir, cpsat_dir, opts_dir, cfg_path


def test_demand_assigned_gap_coverage_and_resident_fifo_breakdown(tmp_path: Path):
    data_dir, cpsat_dir, opts_dir, cfg_path = _write_controlled_dataset(tmp_path)
    ds = load_dashboard_dataset(data_dir, cpsat_dir, opts_dir, cfg_path)
    kpis = compute_summary_kpis(ds)

    # Total demand = 2 (DM001) + 1 (DM002) + 1 (DM003) = 4
    # Assigned = 1 (AS1 Residential) + 1 (AS3 FIFO) = 2
    # Unfilled = 1 (AS2 open gap) + 1 (AS4 locked gap) = 2
    # Coverage % = (2 / 4) * 100 = 50.0%
    assert kpis.total_demand == 4
    assert kpis.assigned_demand == 2
    assert kpis.unfilled_demand == 2
    assert kpis.coverage_pct == 50.0
    assert kpis.resident_demand_assignments == 1
    assert kpis.fifo_demand_assignments == 1
    assert kpis.fully_covered_slots == 1
    assert kpis.partially_covered_slots == 1
    assert kpis.unfilled_slots == 1
    assert kpis.total_gaps == 3
    assert kpis.locked_gaps == 1
    assert kpis.open_gaps_to_fill == 2
    assert kpis.gaps_filled == 1
    assert kpis.gap_fill_pct == 50.0


def test_duplicate_assignment_records_are_deduplicated(tmp_path: Path):
    data_dir, cpsat_dir, opts_dir, cfg_path = _write_controlled_dataset(tmp_path, duplicate_roster_row=True)
    ds = load_dashboard_dataset(data_dir, cpsat_dir, opts_dir, cfg_path)
    kpis = compute_summary_kpis(ds)

    assert len(ds.roster_rows) == 4
    assert any("Deduplicated 1 duplicate record" in w for w in ds.warnings)
    assert kpis.total_demand == 4
    assert kpis.assigned_demand == 2
    assert kpis.resident_demand_assignments == 1


def test_activity_head_and_swing_wise_aggregations(tmp_path: Path):
    data_dir, cpsat_dir, opts_dir, cfg_path = _write_controlled_dataset(tmp_path)
    ds = load_dashboard_dataset(data_dir, cpsat_dir, opts_dir, cfg_path)

    slots = build_demand_slot_records(ds)
    by_head = {r["Activity Head"]: r for r in aggregate_by_activity_head(slots)}
    assert by_head["Madison Crew"]["Total Demand"] == 2
    assert by_head["Madison Crew"]["Assigned Demand"] == 1
    assert by_head["Madison Crew"]["Remaining Gap"] == 1
    assert by_head["Madison Crew"]["Coverage %"] == 50.0
    assert by_head["Madison Crew"]["Partially Covered Slots"] == 1

    assert by_head["NE Crew"]["Total Demand"] == 1
    assert by_head["NE Crew"]["Assigned Demand"] == 1
    assert by_head["NE Crew"]["Remaining Gap"] == 0
    assert by_head["NE Crew"]["Coverage %"] == 100.0
    assert by_head["NE Crew"]["FIFO Assigned"] == 1

    assert by_head["BY Ship"]["Total Demand"] == 1
    assert by_head["BY Ship"]["Assigned Demand"] == 0
    assert by_head["BY Ship"]["Remaining Gap"] == 1
    assert by_head["BY Ship"]["Coverage %"] == 0.0
    assert by_head["BY Ship"]["Unfilled Slots"] == 1

    by_swing = {r["Swing"]: r for r in aggregate_by_swing(ds)}
    assert by_swing["1"]["Total Demand"] == 3
    assert by_swing["1"]["Assigned Demand"] == 1
    assert by_swing["1"]["Remaining Gap"] == 2
    assert by_swing["1"]["Resident Assigned"] == 1
    assert by_swing["2"]["Total Demand"] == 1
    assert by_swing["2"]["Assigned Demand"] == 1
    assert by_swing["2"]["FIFO Assigned"] == 1


def test_missing_and_empty_outputs_handled_gracefully(tmp_path: Path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    ds = load_dashboard_dataset(
        data_dir=empty_dir,
        cpsat_dir=empty_dir,
        options_dir=empty_dir,
        config_path=empty_dir / "missing.yml",
    )
    kpis = compute_summary_kpis(ds)
    assert kpis.total_demand == 0
    assert kpis.assigned_demand == 0
    assert kpis.unfilled_demand == 0
    assert kpis.coverage_pct == 0.0
    assert ds.warnings

    # Missing required columns raises a clear ValueError
    bad_csv = empty_dir / "bad.csv"
    bad_csv.write_text("WrongCol1,WrongCol2\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required column"):
        read_csv_safe(bad_csv, required_columns={"Assignment ID", "User Id"})


def test_gap_diagnostics_use_explicit_evidence_without_guessing(tmp_path: Path):
    data_dir, cpsat_dir, opts_dir, cfg_path = _write_controlled_dataset(tmp_path)
    ds = load_dashboard_dataset(data_dir, cpsat_dir, opts_dir, cfg_path)
    unfilled = {r["Seat Key"]: r for r in build_unfilled_gap_records(ds)}

    # AS4 is before solver_start -> explicitly marked locked
    assert unfilled["A12@2026-11-04T10:00"]["Diagnostic Category"] == "Locked Gap (Before Solver Start)"
    assert "Is_locked_gap=True" in str(unfilled["A12@2026-11-04T10:00"]["Diagnostic Evidence"])

    # AS2 has 0 candidates in gap_options.csv and an explicit rejection in rejections.csv
    assert unfilled["A06@2026-11-07T06:00"]["Diagnostic Category"] == "No Legal Layer-1 Candidate Options"
    assert "not certified (eligibility matrix) (4)" in str(unfilled["A06@2026-11-07T06:00"]["Diagnostic Evidence"])

    # When options_dir is omitted, diagnostic reason explicitly states "Reason Not Available"
    ds_no_opts = load_dashboard_dataset(data_dir, cpsat_dir, options_dir=None, config_path=cfg_path)
    unfilled_no_opts = {r["Seat Key"]: r for r in build_unfilled_gap_records(ds_no_opts)}
    assert unfilled_no_opts["A06@2026-11-07T06:00"]["Diagnostic Category"] == "Reason Not Available"


def test_charts_and_real_solver_outputs_load_cleanly():
    ds = load_dashboard_dataset(
        data_dir=DEFAULT_DATA_DIR,
        cpsat_dir=DEFAULT_CPSAT_DIR,
        options_dir=DEFAULT_OPTIONS_DIR,
        config_path=DEFAULT_CONFIG_PATH,
    )
    kpis = compute_summary_kpis(ds)
    assert kpis.total_demand == 5130  # 171 crew-shifts/day * 30 days
    assert kpis.assigned_demand + kpis.unfilled_demand == kpis.total_demand
    assert kpis.resident_demand_assignments + kpis.fifo_demand_assignments == kpis.assigned_demand

    slots = build_demand_slot_records(ds)
    head_agg = aggregate_by_activity_head(slots)
    unfilled = build_unfilled_gap_records(ds)
    gap_summaries = summarize_gaps(unfilled)
    timeline = build_crew_timeline_records(ds, include_off_and_travel=False)
    diag = build_constraint_diagnostics(ds)

    assert len(head_agg) == 14
    assert diag["head_limits_table"]
    assert create_demand_coverage_heatmap(slots, "Date") is not None
    assert create_crew_gantt_chart(timeline, max_crew=10) is not None
    assert create_gap_summary_charts(gap_summaries, head_agg)["by_head"] is not None
    assert create_shift_limit_utilization_chart(diag["head_limits_table"]) is not None

    # Disrupted-only slots filter
    disrupted_slots = build_demand_slot_records(ds, only_disrupted_gaps=True)
    assert 0 < len(disrupted_slots) < len(slots)

    # Changed-crew-only timeline filter
    changed_timeline = build_crew_timeline_records(ds, include_off_and_travel=False, only_changed_crew=True)
    assert 0 < len(changed_timeline) < len(timeline)

    # Candidate inspector & summary/validation parser
    if unfilled:
        trace = inspect_seat_candidates(ds, str(unfilled[0]["Seat Key"]))
        assert "candidates" in trace and "rejections" in trace
    parsed_meta = parse_summary_and_validation(ds)
    assert parsed_meta["stages"]
    assert parsed_meta["validation_rules"]

    discovered = discover_strategy_datasets()
    if discovered:
        comp = compare_strategy_datasets(discovered)
        assert comp["overall"]
        assert create_strategy_comparison_charts(comp)["by_head"] is not None
