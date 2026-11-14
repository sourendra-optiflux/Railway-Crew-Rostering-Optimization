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
from utils.load_options import load_options  # noqa: E402

from option_generation.data import DEFAULT_DATA_DIR, read_csv  # noqa: E402
from option_generation.options import Costs, Option  # noqa: E402
from option_generation.priority import load_activity_head_priorities, priority_weights_for  # noqa: E402
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


def test_priority_weights_are_derived_from_data():
    assert priority_weights_for([1, 2, 15]) == {1: 15, 2: 14, 15: 1}


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


@pytest.mark.parametrize("value", ["0", "-1", "urgent", ""])
def test_activity_head_priorities_reject_non_positive_values(tmp_path: Path, value: str):
    demand, priority = write_priority_inputs(tmp_path, "High\n", f"High,{value}\n")

    with pytest.raises(SystemExit, match="must be positive integers"):
        load_activity_head_priorities(demand, priority)


def test_activity_head_priority_accepts_priorities_above_14(tmp_path: Path):
    demand, priority = write_priority_inputs(tmp_path, "High\n", "High,15\n")
    assert load_activity_head_priorities(demand, priority) == {"High": 15}

    demand2, priority2 = write_priority_inputs(tmp_path, "High\n", "High,21\n")
    assert load_activity_head_priorities(demand2, priority2) == {"High": 21}


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
    assert result.stage_values["weighted_priority"] == 1
    assert result.cost == cheap.cost
    assert list(result.stage_statuses) == ["coverage", "weighted_priority", "cost"]


def test_cp_sat_runs_stage_two_after_feasible_stage_one(
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

    assert result.cost_status == "FEASIBLE"
    assert result.stage_statuses == {
        "coverage": "FEASIBLE",
        "cost": "FEASIBLE",
    }
    assert result.cost is not None


def test_cp_sat_continues_later_stages_when_intermediate_priority_stage_is_feasible(
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
    assert result.cost == 20
    assert result.stage_statuses == {
        "coverage": "OPTIMAL",
        "priority_1": "FEASIBLE",
        "priority_2": "OPTIMAL",
        "cost": "OPTIMAL",
    }
    assert set(result.stage_values) == {"coverage", "priority_1", "priority_2", "cost"}


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
