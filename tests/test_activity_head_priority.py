import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CP-SAT"))

import solver as solver_module  # noqa: E402
from solver import solve  # noqa: E402
from utils.activity_head_priority import (  # noqa: E402
    PRIORITY_WEIGHTS,
    ActivityHeadLimits,
    load_activity_head_limits,
    load_activity_head_priorities,
    load_assignment_type_priorities,
)
from utils.load_options import load_options  # noqa: E402

from option_generation.data import DEFAULT_DATA_DIR, read_csv  # noqa: E402
from option_generation.options import Costs, Option  # noqa: E402
from option_generation.rules import Rules  # noqa: E402


def write_priority_inputs(tmp_path: Path, demand_heads: str, priorities: str) -> tuple[Path, Path]:
    demand = tmp_path / "activity_demand_df.csv"
    priority = tmp_path / "activity_priority.csv"
    demand.write_text(f"Activity Head\n{demand_heads}", encoding="utf-8")
    priority.write_text(f"Activity Head,Priority\n{priorities}", encoding="utf-8")
    return demand, priority


def test_activity_head_priorities_load_for_every_demand_head(tmp_path: Path):
    demand, priority = write_priority_inputs(tmp_path, "High\nLow\n", "High,1\nLow,2\n")

    assert load_activity_head_priorities(demand, priority) == {"High": 1, "Low": 2}


def test_default_priority_config_covers_every_project_demand_head():
    priorities = load_activity_head_priorities(DEFAULT_DATA_DIR / "activity_demand_df.csv")

    assert len(priorities) == 14


def test_priority_weights_are_configured_centrally():
    assert PRIORITY_WEIGHTS == {priority: 15 - priority for priority in range(1, 15)}


def test_load_options_applies_configured_head_priorities(tmp_path: Path):
    (tmp_path / "seats.csv").write_text(
        "Seat Key,Date,Start,Activity ID,Activity Head,Demand,Fixed Occupants,Priority,Chain Level,Gap Assignment IDs\n"
        "high,2026-11-01,06:00,A1,High,1,0,99,0,\n"
        "low,2026-11-01,06:00,A2,Low,1,0,1,0,\n",
        encoding="utf-8",
    )
    (tmp_path / "swings.csv").write_text(
        "Swing Key,User Id,Home Depot,Classification,Earliest Start,Latest End,In Model,Rows,Droppable Rows,Status\n",
        encoding="utf-8",
    )
    (tmp_path / "options.csv").write_text(
        "Swing Key,Row Index,Kind,Start,End,Start Location,End Location,Activity ID,Demand ID,Seat Key,"
        "Excess Seat Key,Standby,Row Type,Offset Minutes,Cost,Chain Level,Unchanged\n",
        encoding="utf-8",
    )

    seats, swings = load_options(tmp_path, {"High": 1, "Low": 2})

    assert seats["high"].priority == 1
    assert seats["low"].priority == 2
    assert swings == []


def test_activity_head_priorities_reject_missing_demand_head(tmp_path: Path):
    demand, priority = write_priority_inputs(tmp_path, "High\nLow\n", "High,1\n")

    with pytest.raises(SystemExit, match="missing priorities for demand activity heads: Low"):
        load_activity_head_priorities(demand, priority)


def test_activity_head_priorities_reject_non_demand_head(tmp_path: Path):
    demand, priority = write_priority_inputs(tmp_path, "High\n", "High,1\nExtra,2\n")

    with pytest.raises(SystemExit, match="priorities configured for non-demand activity heads: Extra"):
        load_activity_head_priorities(demand, priority)


def test_activity_head_priorities_reject_empty_demand_head(tmp_path: Path):
    demand, priority = write_priority_inputs(tmp_path, "High\n \n", "High,1\n")

    with pytest.raises(SystemExit, match="contains a demand row with an empty Activity Head"):
        load_activity_head_priorities(demand, priority)


def test_activity_head_priorities_reject_duplicate_entries(tmp_path: Path):
    demand, priority = write_priority_inputs(tmp_path, "High\n", "High,1\nHigh,2\n")

    with pytest.raises(SystemExit, match="duplicate activity-head priority entries: High"):
        load_activity_head_priorities(demand, priority)


@pytest.mark.parametrize("value", ["0", "-1", "15", "urgent", ""])
def test_activity_head_priorities_reject_values_without_configured_weights(tmp_path: Path, value: str):
    demand, priority = write_priority_inputs(tmp_path, "High\n", f"High,{value}\n")

    with pytest.raises(SystemExit, match="must be integers with configured weights"):
        load_activity_head_priorities(demand, priority)


def test_activity_head_priority_accepts_priority_with_central_weight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    demand, priority = write_priority_inputs(tmp_path, "High\n", "High,21\n")
    monkeypatch.setitem(PRIORITY_WEIGHTS, 21, 3)

    assert load_activity_head_priorities(demand, priority) == {"High": 21}


def test_cp_sat_prefers_higher_priority_head_when_demand_cannot_all_be_filled():
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    rules = replace(
        rules,
        rest=timedelta(hours=8),
        transition_rest=timedelta(hours=8),
        day_from=6 * 60,
        day_to=18 * 60,
    )
    start = datetime(2026, 11, 1, 6)
    high = Option(
        0, "fill", start, start + timedelta(hours=8), "A", "A", "high",
        seat="high-seat",
    )
    low = Option(
        0, "fill", start, start + timedelta(hours=8), "A", "A", "low",
        seat="low-seat",
    )
    swing = SimpleNamespace(
        key="U1|priority",
        user="U1",
        home="A",
        classification="FIFO",
        earliest_start=None,
        latest_end=None,
        row_ids=["R1"],
        droppable=[False],
        options=[[high, low]],
    )
    seats = {
        "high-seat": SimpleNamespace(capacity=1, priority=1),
        "low-seat": SimpleNamespace(capacity=1, priority=2),
    }

    result = solve(rules, seats, [swing], Costs(), 5, 1, 0, priority_strategy="weighted")

    assert result.chosen[swing.key][0] == high
    assert result.places_filled == 1
    assert result.stage_statuses == {
        "coverage": "OPTIMAL",
        "weighted_priority": "OPTIMAL",
        "cost": "OPTIMAL",
    }


def test_priority_strategy_weighted_and_lexicographic_after_total_coverage():
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    rules = replace(
        rules,
        rest=timedelta(0),
        transition_rest=timedelta(0),
        day_from=6 * 60,
        day_to=18 * 60,
        relief_only_day_night_transition=False,
    )
    first_day = datetime(2026, 11, 1, 6)
    second_day = datetime(2026, 11, 2, 6)
    high = Option(0, "fill", first_day, second_day + timedelta(hours=8), "A", "A", "high", seat="high-seat")
    medium_first = Option(
        0, "fill", first_day, first_day + timedelta(hours=8), "A", "A", "medium-first",
        seat="medium-first-seat",
    )
    low_start = second_day + timedelta(hours=12)
    low = Option(1, "fill", low_start, low_start + timedelta(hours=8), "A", "A", "low", seat="low-seat")
    medium_second = Option(
        1, "fill", second_day, second_day + timedelta(hours=8), "A", "A", "medium-second",
        seat="medium-second-seat",
    )
    swing = SimpleNamespace(
        key="U1|priority-strategy",
        user="U1",
        home="A",
        classification="FIFO",
        earliest_start=None,
        latest_end=None,
        row_ids=["R1", "R2"],
        droppable=[False, True],
        options=[[high, medium_first], [low, medium_second]],
    )
    seats = {
        "high-seat": SimpleNamespace(capacity=1, priority=1),
        "medium-first-seat": SimpleNamespace(capacity=1, priority=2),
        "medium-second-seat": SimpleNamespace(capacity=1, priority=2),
        "low-seat": SimpleNamespace(capacity=1, priority=14),
    }

    weighted = solve(rules, seats, [swing], Costs(), 5, 1, 0, priority_strategy="weighted")
    lexicographic = solve(rules, seats, [swing], Costs(), 5, 1, 0, priority_strategy="lexicographic")

    assert weighted.places_filled == lexicographic.places_filled == 2
    assert weighted.chosen[swing.key] == [medium_first, medium_second]
    assert lexicographic.chosen[swing.key] == [high, low]
    assert list(lexicographic.stage_statuses) == ["coverage", "priority_1", "priority_2", "priority_14", "cost"]


def test_none_strategy_uses_cost_without_prioritizing_activity_heads():
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    rules = replace(rules, rest=timedelta(hours=8), transition_rest=timedelta(hours=8))
    start = datetime(2026, 11, 1, 6)
    high = Option(0, "fill", start, start + timedelta(hours=8), "A", "A", "high", seat="high", cost=20)
    low = Option(0, "fill", start, start + timedelta(hours=8), "A", "A", "low", seat="low", cost=1)
    swing = SimpleNamespace(
        key="U1|none",
        user="U1",
        home="A",
        classification="FIFO",
        earliest_start=None,
        latest_end=None,
        row_ids=["R1"],
        droppable=[False],
        options=[[high, low]],
    )
    seats = {
        "high": SimpleNamespace(capacity=1, priority=1),
        "low": SimpleNamespace(capacity=1, priority=14),
    }

    result = solve(rules, seats, [swing], Costs(), 5, 1, 0, priority_strategy="none")

    assert result.places_filled == 1
    assert result.chosen[swing.key] == [low]
    assert list(result.stage_statuses) == ["coverage", "cost"]


@pytest.mark.parametrize(("capacity", "expected_filled"), [(1, 1), (2, 2)])
def test_cp_sat_counts_demand_positions_up_to_seat_capacity(capacity: int, expected_filled: int):
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    rules = replace(
        rules,
        rest=timedelta(hours=8),
        transition_rest=timedelta(hours=8),
        day_from=6 * 60,
        day_to=18 * 60,
    )
    first_start = datetime(2026, 11, 1, 6)
    second_start = datetime(2026, 11, 2, 6)
    first_option = Option(
        0, "fill", first_start, first_start + timedelta(hours=8), "A", "A", "demand",
        seat="shared-seat",
    )
    second_option = Option(
        1, "fill", second_start, second_start + timedelta(hours=8), "A", "A", "demand",
        seat="shared-seat",
    )
    swing = SimpleNamespace(
        key="U1|capacity",
        user="U1",
        home="A",
        classification="FIFO",
        earliest_start=None,
        latest_end=None,
        row_ids=["R1", "R2"],
        droppable=[True, True],
        options=[[first_option], [second_option]],
    )
    seats = {"shared-seat": SimpleNamespace(capacity=capacity, priority=1)}

    result = solve(rules, seats, [swing], Costs(), 5, 1, 0)

    assert result.places_filled == expected_filled
    assert sum(selected is not None for selected in result.chosen[swing.key]) == expected_filled


def test_cp_sat_stage_two_preserves_weighted_coverage_and_minimizes_cost():
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    rules = replace(
        rules,
        rest=timedelta(hours=8),
        transition_rest=timedelta(hours=8),
        day_from=6 * 60,
        day_to=18 * 60,
    )
    start = datetime(2026, 11, 1, 6)
    expensive = Option(
        0, "fill", start, start + timedelta(hours=8), "A", "A", "expensive",
        seat="shared-seat", cost=20,
    )
    cheap = Option(
        0, "fill", start, start + timedelta(hours=8), "A", "A", "cheap",
        seat="shared-seat", cost=1,
    )
    swing = SimpleNamespace(
        key="U1|stage-two",
        user="U1",
        home="A",
        classification="FIFO",
        earliest_start=None,
        latest_end=None,
        row_ids=["R1"],
        droppable=[False],
        options=[[expensive, cheap]],
    )
    seats = {"shared-seat": SimpleNamespace(capacity=1, priority=1)}

    result = solve(rules, seats, [swing], Costs(), 5, 1, 0, priority_strategy="weighted")

    assert result.status == "OPTIMAL"
    assert result.cost_status == "OPTIMAL"
    assert result.places_filled == 1
    assert result.chosen[swing.key] == [cheap]
    assert PRIORITY_WEIGHTS[seats["shared-seat"].priority] * result.places_filled == 14
    assert result.cost == cheap.cost
    assert list(result.stage_statuses) == ["coverage", "weighted_priority", "cost"]


def test_cp_sat_reports_when_stage_two_is_skipped_for_feasible_stage_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    rules = replace(
        rules,
        rest=timedelta(hours=8),
        transition_rest=timedelta(hours=8),
        day_from=6 * 60,
        day_to=18 * 60,
    )
    start = datetime(2026, 11, 1, 6)
    option = Option(
        0, "fill", start, start + timedelta(hours=8), "A", "A", "fill", seat="seat"
    )
    swing = SimpleNamespace(
        key="U1|feasible",
        user="U1",
        home="A",
        classification="FIFO",
        earliest_start=None,
        latest_end=None,
        row_ids=["R1"],
        droppable=[False],
        options=[[option]],
    )
    seats = {"seat": SimpleNamespace(capacity=1, priority=1)}
    original_solver = solver_module.cp_model.CpSolver

    class FeasibleStatusSolver:
        def __init__(self):
            self.solver = original_solver()

        @property
        def parameters(self):
            return self.solver.parameters

        def solve(self, model):
            self.solver.solve(model)
            return solver_module.cp_model.FEASIBLE

        def __getattr__(self, name):
            return getattr(self.solver, name)

    monkeypatch.setattr(solver_module.cp_model, "CpSolver", FeasibleStatusSolver)

    result = solve(rules, seats, [swing], Costs(), 5, 1, 0)

    assert result.cost_status == "SKIPPED (Stage 1 FEASIBLE)"
    assert result.stage_statuses == {
        "coverage": "FEASIBLE",
        "cost": "SKIPPED (Stage 1 FEASIBLE)",
    }
    assert "Stage 2 (SKIPPED): Stage 1 was FEASIBLE, not OPTIMAL" in capsys.readouterr().out


def test_cp_sat_skips_later_stages_when_intermediate_priority_stage_is_feasible(
    monkeypatch: pytest.MonkeyPatch,
):
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    rules = replace(
        rules,
        rest=timedelta(hours=8),
        transition_rest=timedelta(hours=8),
        day_from=6 * 60,
        day_to=18 * 60,
    )
    start = datetime(2026, 11, 1, 6)
    high = Option(0, "fill", start, start + timedelta(hours=8), "A", "A", "high", seat="high", cost=20)
    low = Option(0, "fill", start, start + timedelta(hours=8), "A", "A", "low", seat="low", cost=1)
    swing = SimpleNamespace(
        key="U1|lex-feasible",
        user="U1",
        home="A",
        classification="FIFO",
        earliest_start=None,
        latest_end=None,
        row_ids=["R1"],
        droppable=[False],
        options=[[high, low]],
    )
    seats = {
        "high": SimpleNamespace(capacity=2, priority=1),
        "low": SimpleNamespace(capacity=2, priority=2),
    }
    original_solver = solver_module.cp_model.CpSolver
    calls = 0

    class SecondStageFeasibleSolver:
        def __init__(self):
            self.solver = original_solver()

        @property
        def parameters(self):
            return self.solver.parameters

        def solve(self, model):
            nonlocal calls
            calls += 1
            code = self.solver.solve(model)
            return solver_module.cp_model.FEASIBLE if calls == 2 else code

        def __getattr__(self, name):
            return getattr(self.solver, name)

    monkeypatch.setattr(solver_module.cp_model, "CpSolver", SecondStageFeasibleSolver)

    result = solve(rules, seats, [swing], Costs(), 5, 1, 0, priority_strategy="lexicographic")

    assert result.places_filled == 1
    assert result.bound == 1.0  # solver optimization bound (1.0), not total seat capacity (4)
    assert result.cost is None
    assert result.stage_statuses == {
        "coverage": "OPTIMAL",
        "priority_1": "FEASIBLE",
        "priority_2": "SKIPPED (Stage 2 FEASIBLE)",
        "cost": "SKIPPED (Stage 2 FEASIBLE)",
    }
    assert set(result.stage_values) == {"coverage", "priority_1"}  # skipped stages report no value


def test_lexicographic_priority_level_without_in_model_seats_is_solved_as_zero():
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    rules = replace(rules, rest=timedelta(hours=8), transition_rest=timedelta(hours=8))
    start = datetime(2026, 11, 1, 6)
    option = Option(0, "fill", start, start + timedelta(hours=8), "A", "A", "used", seat="used", cost=3)
    swing = SimpleNamespace(
        key="U1|empty-level", user="U1", home="A", classification="FIFO", earliest_start=None,
        latest_end=None, row_ids=["R1"], droppable=[False], options=[[option]],
    )
    seats = {
        "used": SimpleNamespace(capacity=1, priority=2),
        "unused": SimpleNamespace(capacity=1, priority=1),  # no option points at this seat
    }

    result = solve(rules, seats, [swing], Costs(), 5, 1, 0, priority_strategy="lexicographic")

    assert result.stage_statuses == {
        "coverage": "OPTIMAL", "priority_1": "OPTIMAL", "priority_2": "OPTIMAL", "cost": "OPTIMAL",
    }
    assert result.stage_values == {"coverage": 1, "priority_1": 0, "priority_2": 1, "cost": 3}


def write_limit_inputs(tmp_path: Path, demand_heads: str, rows: str) -> tuple[Path, Path]:
    demand = tmp_path / "activity_demand_df.csv"
    priority = tmp_path / "activity_priority.csv"
    demand.write_text(f"Activity Head\n{demand_heads}", encoding="utf-8")
    priority.write_text(
        f"Priority,Activity Head,Max Resident Shifts,Max FIFO Shifts\n{rows}",
        encoding="utf-8",
    )
    return demand, priority


def _test_rules() -> Rules:
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    return replace(
        rules,
        rest=timedelta(hours=8),
        transition_rest=timedelta(hours=8),
        day_from=6 * 60,
        day_to=18 * 60,
    )


def test_default_activity_head_limits_cover_every_project_demand_head():
    limits = load_activity_head_limits(DEFAULT_DATA_DIR / "activity_demand_df.csv")

    assert len(limits) == 14
    assert all(
        limit == ActivityHeadLimits(max_resident_shifts=6, max_fifo_shifts=14)
        for limit in limits.values()
    )


def test_activity_head_limits_accept_non_negative_integers_including_zero(tmp_path: Path):
    demand, priority = write_limit_inputs(tmp_path, "High\nLow\n", "1,High,0,4\n2,Low,3,0\n")

    assert load_activity_head_limits(demand, priority) == {
        "High": ActivityHeadLimits(max_resident_shifts=0, max_fifo_shifts=4),
        "Low": ActivityHeadLimits(max_resident_shifts=3, max_fifo_shifts=0),
    }


def test_activity_head_limits_reject_missing_columns(tmp_path: Path):
    demand, priority = write_priority_inputs(tmp_path, "High\n", "High,1\n")

    with pytest.raises(SystemExit, match="must contain columns: Activity Head, Max Resident Shifts, Max FIFO Shifts"):
        load_activity_head_limits(demand, priority)


def test_activity_head_limits_reject_missing_demand_head(tmp_path: Path):
    demand, priority = write_limit_inputs(tmp_path, "High\nLow\n", "1,High,2,4\n")

    with pytest.raises(SystemExit, match="missing shift limits for demand activity heads: Low"):
        load_activity_head_limits(demand, priority)


def test_activity_head_limits_reject_unexpected_non_demand_head(tmp_path: Path):
    demand, priority = write_limit_inputs(tmp_path, "High\n", "1,High,2,4\n2,Extra,2,4\n")

    with pytest.raises(SystemExit, match="shift limits configured for non-demand activity heads: Extra"):
        load_activity_head_limits(demand, priority)


def test_activity_head_limits_reject_duplicate_activity_head_entries(tmp_path: Path):
    demand, priority = write_limit_inputs(tmp_path, "High\n", "1,High,2,4\n2,High,3,5\n")

    with pytest.raises(SystemExit, match="duplicate activity-head priority entries: High"):
        load_activity_head_limits(demand, priority)


@pytest.mark.parametrize(
    ("res_val", "fifo_val"),
    [
        ("-1", "4"),
        ("2", "-1"),
        ("", "4"),
        ("2", ""),
        ("abc", "4"),
        ("2", "1.5"),
        ("+2", "4"),
    ],
)
def test_activity_head_limits_reject_invalid_values(tmp_path: Path, res_val: str, fifo_val: str):
    demand, priority = write_limit_inputs(tmp_path, "High\n", f"1,High,{res_val},{fifo_val}\n")

    with pytest.raises(SystemExit, match="Max Resident Shifts and Max FIFO Shifts must be non-negative integers"):
        load_activity_head_limits(demand, priority)


def test_resident_crew_within_max_shift_limit_is_feasible():
    rules = _test_rules()
    d1, d2 = datetime(2026, 11, 1, 6), datetime(2026, 11, 2, 6)
    opt1 = Option(0, "fill", d1, d1 + timedelta(hours=8), "A", "A", "A06", seat="s1", activity_head="Madison Crew")
    opt2 = Option(1, "fill", d2, d2 + timedelta(hours=8), "A", "A", "A06", seat="s2", activity_head="Madison Crew")
    swing = SimpleNamespace(
        key="U_RES|1", user="U_RES", home="A", classification="Residential",
        earliest_start=None, latest_end=None, row_ids=["R1", "R2"], droppable=[False, False],
        options=[[opt1], [opt2]],
    )
    seats = {
        "s1": SimpleNamespace(capacity=1, priority=1, activity_head="Madison Crew"),
        "s2": SimpleNamespace(capacity=1, priority=1, activity_head="Madison Crew"),
    }
    limits = {"Madison Crew": ActivityHeadLimits(max_resident_shifts=2, max_fifo_shifts=1)}

    result = solve(rules, seats, [swing], Costs(), 5, 1, 0, activity_head_limits=limits)

    assert result.status == "OPTIMAL"
    assert result.places_filled == 2


def test_resident_crew_above_max_shift_limit_is_infeasible_or_prevented():
    rules = _test_rules()
    d1, d2 = datetime(2026, 11, 1, 6), datetime(2026, 11, 2, 6)
    opt1 = Option(0, "fill", d1, d1 + timedelta(hours=8), "A", "A", "A06", seat="s1", activity_head="Madison Crew")
    opt2 = Option(1, "fill", d2, d2 + timedelta(hours=8), "A", "A", "A06", seat="s2", activity_head="Madison Crew")
    swing_forced = SimpleNamespace(
        key="U_RES|forced", user="U_RES", home="A", classification="Residential",
        earliest_start=None, latest_end=None, row_ids=["R1", "R2"], droppable=[False, False],
        options=[[opt1], [opt2]],
    )
    seats = {
        "s1": SimpleNamespace(capacity=1, priority=1, activity_head="Madison Crew"),
        "s2": SimpleNamespace(capacity=1, priority=1, activity_head="Madison Crew"),
    }
    limits = {"Madison Crew": ActivityHeadLimits(max_resident_shifts=1, max_fifo_shifts=4)}

    infeasible = solve(rules, seats, [swing_forced], Costs(), 5, 1, 0, activity_head_limits=limits)
    assert infeasible.status == "INFEASIBLE"
    assert infeasible.chosen == {}

    keep2 = Option(1, "keep", d2, d2 + timedelta(hours=8), "A", "A", "A90", standby=True, source="Relief")
    swing_with_standby = replace_swing_options(swing_forced, [[opt1], [keep2, opt2]])
    prevented = solve(rules, seats, [swing_with_standby], Costs(), 5, 1, 0, activity_head_limits=limits)
    assert prevented.status == "OPTIMAL"
    assert prevented.places_filled == 1
    assert prevented.chosen[swing_with_standby.key] == [opt1, keep2]


def replace_swing_options(swing: SimpleNamespace, options: list[list[Option]]) -> SimpleNamespace:
    return SimpleNamespace(**{**swing.__dict__, "options": options})


def test_fifo_crew_within_and_above_max_shift_limit():
    rules = _test_rules()
    d1, d2, d3 = datetime(2026, 11, 1, 6), datetime(2026, 11, 2, 6), datetime(2026, 11, 3, 6)
    o1 = Option(0, "fill", d1, d1 + timedelta(hours=8), "A", "A", "A16", seat="s1", activity_head="NE Crew")
    o2 = Option(1, "fill", d2, d2 + timedelta(hours=8), "A", "A", "A16", seat="s2", activity_head="NE Crew")
    o3 = Option(2, "fill", d3, d3 + timedelta(hours=8), "A", "A", "A16", seat="s3", activity_head="NE Crew")
    swing = SimpleNamespace(
        key="U_FIFO|1", user="U_FIFO", home="A", classification="FIFO",
        earliest_start=None, latest_end=None, row_ids=["R1", "R2", "R3"], droppable=[False, False, False],
        options=[[o1], [o2], [o3]],
    )
    seats = {
        "s1": SimpleNamespace(capacity=1, priority=1, activity_head="NE Crew"),
        "s2": SimpleNamespace(capacity=1, priority=1, activity_head="NE Crew"),
        "s3": SimpleNamespace(capacity=1, priority=1, activity_head="NE Crew"),
    }

    feasible = solve(
        rules, seats, [swing], Costs(), 5, 1, 0,
        activity_head_limits={"NE Crew": ActivityHeadLimits(max_resident_shifts=1, max_fifo_shifts=3)},
    )
    assert feasible.status == "OPTIMAL"
    assert feasible.places_filled == 3

    infeasible = solve(
        rules, seats, [swing], Costs(), 5, 1, 0,
        activity_head_limits={"NE Crew": ActivityHeadLimits(max_resident_shifts=6, max_fifo_shifts=2)},
    )
    assert infeasible.status == "INFEASIBLE"
    assert infeasible.chosen == {}


def test_different_activity_heads_have_independent_limits_and_alternative_options_not_double_counted():
    rules = _test_rules()
    d1, d2, d3 = datetime(2026, 11, 1, 6), datetime(2026, 11, 2, 6), datetime(2026, 11, 3, 6)
    # Row 0 has two alternative options on HeadA (06:00 and 07:00); only one can be selected.
    h1_a = Option(0, "fill", d1, d1 + timedelta(hours=8), "A", "A", "A1", seat="s1a", activity_head="HeadA", cost=5)
    h1_b = Option(
        0, "fill", d1 + timedelta(hours=1), d1 + timedelta(hours=9), "A", "A", "A1",
        seat="s1b", activity_head="HeadA", cost=2,
    )
    # Row 1 can take HeadA or HeadB; since HeadA limit for Residential is 1, Row 1 must take HeadB.
    h2_a = Option(1, "fill", d2, d2 + timedelta(hours=8), "A", "A", "A1", seat="s2a", activity_head="HeadA", cost=1)
    h2_b = Option(1, "fill", d2, d2 + timedelta(hours=8), "A", "A", "B1", seat="s2b", activity_head="HeadB", cost=4)
    # Row 2 takes a second shift on HeadB (HeadB allows up to 2 shifts for Residential).
    h3_b = Option(2, "fill", d3, d3 + timedelta(hours=8), "A", "A", "B1", seat="s3b", activity_head="HeadB", cost=3)

    swing = SimpleNamespace(
        key="U_RES|mix", user="U_RES", home="A", classification="Residential",
        earliest_start=None, latest_end=None, row_ids=["R1", "R2", "R3"], droppable=[False, False, False],
        options=[[h1_a, h1_b], [h2_a, h2_b], [h3_b]],
    )
    seats = {
        "s1a": SimpleNamespace(capacity=1, priority=1, activity_head="HeadA"),
        "s1b": SimpleNamespace(capacity=1, priority=1, activity_head="HeadA"),
        "s2a": SimpleNamespace(capacity=1, priority=1, activity_head="HeadA"),
        "s2b": SimpleNamespace(capacity=1, priority=2, activity_head="HeadB"),
        "s3b": SimpleNamespace(capacity=1, priority=2, activity_head="HeadB"),
    }
    limits = {
        "HeadA": ActivityHeadLimits(max_resident_shifts=1, max_fifo_shifts=5),
        "HeadB": ActivityHeadLimits(max_resident_shifts=2, max_fifo_shifts=5),
    }

    result = solve(rules, seats, [swing], Costs(), 5, 1, 0, activity_head_limits=limits)

    assert result.status == "OPTIMAL"
    assert result.places_filled == 3
    assert result.chosen[swing.key] == [h1_b, h2_b, h3_b]


def test_limits_enforced_independently_across_swings_and_crew_members():
    rules = _test_rules()
    d1, d2 = datetime(2026, 11, 1, 6), datetime(2026, 11, 10, 6)
    s1_opt = Option(0, "fill", d1, d1 + timedelta(hours=8), "A", "A", "A06", seat="seat1", activity_head="Madison Crew")
    s2_opt = Option(0, "fill", d2, d2 + timedelta(hours=8), "A", "A", "A06", seat="seat2", activity_head="Madison Crew")
    other_crew_opt = Option(
        0, "fill", d1, d1 + timedelta(hours=8), "A", "A", "A06", seat="seat3", activity_head="Madison Crew"
    )
    # Same crew member U1 in two separate swings (U1|1 and U1|2), plus a second crew member U2 in U2|1.
    sw1 = SimpleNamespace(
        key="U1|1", user="U1", home="A", classification="Residential",
        earliest_start=None, latest_end=None, row_ids=["R1"], droppable=[False], options=[[s1_opt]],
    )
    sw2 = SimpleNamespace(
        key="U1|2", user="U1", home="A", classification="Residential",
        earliest_start=None, latest_end=None, row_ids=["R2"], droppable=[False], options=[[s2_opt]],
    )
    sw3 = SimpleNamespace(
        key="U2|1", user="U2", home="A", classification="Residential",
        earliest_start=None, latest_end=None, row_ids=["R3"], droppable=[False], options=[[other_crew_opt]],
    )
    seats = {
        "seat1": SimpleNamespace(capacity=1, priority=1, activity_head="Madison Crew"),
        "seat2": SimpleNamespace(capacity=1, priority=1, activity_head="Madison Crew"),
        "seat3": SimpleNamespace(capacity=1, priority=1, activity_head="Madison Crew"),
    }
    limits = {"Madison Crew": ActivityHeadLimits(max_resident_shifts=1, max_fifo_shifts=1)}

    result = solve(rules, seats, [sw1, sw2, sw3], Costs(), 5, 1, 0, activity_head_limits=limits)

    assert result.status == "OPTIMAL"
    assert result.places_filled == 3
    assert result.chosen["U1|1"] == [s1_opt]
    assert result.chosen["U1|2"] == [s2_opt]
    assert result.chosen["U2|1"] == [other_crew_opt]


def test_assignment_type_priorities_load_default_and_validate(tmp_path: Path):
    assert load_assignment_type_priorities() == {"Relief": 1, "Excess": 2, "Demand": 3}

    custom = tmp_path / "assignment_type_priority.csv"
    custom.write_text("Priority,Assignment Type\n1,Excess\n2,Relief\n3,Demand\n", encoding="utf-8")
    assert load_assignment_type_priorities(custom) == {"Excess": 1, "Relief": 2, "Demand": 3}

    bad_missing = tmp_path / "bad_missing.csv"
    bad_missing.write_text("Priority,Assignment Type\n1,Relief\n2,Excess\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="missing assignment-type priorities"):
        load_assignment_type_priorities(bad_missing)

    bad_dup = tmp_path / "bad_dup.csv"
    bad_dup.write_text("Priority,Assignment Type\n1,Relief\n1,Excess\n3,Demand\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="duplicate Priority values"):
        load_assignment_type_priorities(bad_dup)


def test_solver_prefers_relief_over_excess_and_demand_regardless_of_raw_cost():
    rules = _test_rules()
    start = datetime(2026, 11, 1, 6)
    # Excess same-slot has raw cost 0, whereas Relief fill has raw cost 22, and Demand has raw cost 40.
    # Because Relief has priority 1, Excess has priority 2, and Demand has priority 3,
    # the optimizer must choose Relief (1) over Excess (2) and Demand (3).
    relief_opt = Option(
        0, "fill", start, start + timedelta(hours=8), "A", "A", "A06",
        seat="seat1", cost=22, source="Relief",
    )
    excess_opt = Option(
        0, "fill", start, start + timedelta(hours=8), "A", "A", "A06",
        seat="seat1", cost=0, source="Excess",
    )
    demand_opt = Option(
        0, "fill", start, start + timedelta(hours=8), "A", "A", "A06",
        seat="seat1", cost=40, source="Demand",
    )
    sw_rel = SimpleNamespace(
        key="U_REL|1", user="U_REL", home="A", classification="FIFO",
        earliest_start=None, latest_end=None, row_ids=["R_REL"], droppable=[True],
        options=[[Option(0, "keep", start, start + timedelta(hours=8), "A", "A", "REL", source="Relief"), relief_opt]],
    )
    sw_exc = SimpleNamespace(
        key="U_EXC|1", user="U_EXC", home="A", classification="FIFO",
        earliest_start=None, latest_end=None, row_ids=["R_EXC"], droppable=[True],
        options=[[Option(0, "keep", start, start + timedelta(hours=8), "A", "A", "EXC", source="Excess"), excess_opt]],
    )
    sw_dem = SimpleNamespace(
        key="U_DEM|1", user="U_DEM", home="A", classification="FIFO",
        earliest_start=None, latest_end=None, row_ids=["R_DEM"], droppable=[True],
        options=[[Option(0, "keep", start, start + timedelta(hours=8), "A", "A", "DEM", source="Demand"), demand_opt]],
    )
    seats = {"seat1": SimpleNamespace(capacity=1, priority=1, activity_head="Madison Crew")}

    res_default = solve(
        rules, seats, [sw_rel, sw_exc, sw_dem], Costs(), 5, 1, 0,
        assignment_type_priority={"Relief": 1, "Excess": 2, "Demand": 3},
    )
    assert res_default.places_filled == 1
    assert res_default.chosen["U_REL|1"] == [relief_opt]
    assert res_default.cost == 22

    # When only Excess (priority 2) and Demand (priority 3) are available, Excess is chosen over Demand
    res_exc_vs_dem = solve(
        rules, seats, [sw_exc, sw_dem], Costs(), 5, 1, 0,
        assignment_type_priority={"Relief": 1, "Excess": 2, "Demand": 3},
    )
    assert res_exc_vs_dem.places_filled == 1
    assert res_exc_vs_dem.chosen["U_EXC|1"] == [excess_opt]

    # When priority order is inverted so Excess is priority 1 and Relief is priority 2, Excess is chosen
    res_custom = solve(
        rules, seats, [sw_rel, sw_exc, sw_dem], Costs(), 5, 1, 0,
        assignment_type_priority={"Excess": 1, "Relief": 2, "Demand": 3},
    )
    assert res_custom.places_filled == 1
    assert res_custom.chosen["U_EXC|1"] == [excess_opt]
