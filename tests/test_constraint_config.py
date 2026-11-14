import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CP-SAT"))

from solver import solve  # noqa: E402

from option_generation.data import DEFAULT_DATA_DIR, read_csv  # noqa: E402
from option_generation.options import Costs, Option, try_fill  # noqa: E402
from option_generation.rules import Rules  # noqa: E402


@pytest.mark.parametrize(
    ("disabled", "enabled"),
    [
        ("residential_start_restriction", "relief_only_day_night_transition"),
        ("relief_only_day_night_transition", "residential_start_restriction"),
    ],
)
def test_constraint_switches_load_independently(tmp_path: Path, disabled: str, enabled: str):
    config = tmp_path / "config.yml"
    config.write_text(
        f"constraints:\n  {disabled}: false\n",
        encoding="utf-8",
    )

    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"), config)

    assert getattr(rules, disabled) is False
    assert getattr(rules, enabled) is True


@pytest.mark.parametrize("strategy", ["none", "weighted", "lexicographic"])
def test_priority_strategy_loads_from_optimization_config(tmp_path: Path, strategy: str):
    config = tmp_path / "config.yml"
    config.write_text(
        "constraints:\n"
        "  residential_start_restriction: true\n"
        "  relief_only_day_night_transition: true\n"
        f"optimization:\n  priority_strategy: {strategy}\n",
        encoding="utf-8",
    )

    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"), config)

    assert rules.priority_strategy == strategy


def test_priority_strategy_rejects_unknown_value(tmp_path: Path):
    config = tmp_path / "config.yml"
    config.write_text(
        "constraints:\n"
        "  residential_start_restriction: true\n"
        "  relief_only_day_night_transition: true\n"
        "optimization:\n  priority_strategy: unsupported\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="priority_strategy.*none, weighted, or lexicographic"):
        Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"), config)


def test_option_generation_blocks_new_but_preserves_unchanged_residential_night_assignment():
    rules = replace(
        Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv")),
        residential_start_restriction=True,
    )
    start = datetime(2026, 11, 7, 23)
    data = SimpleNamespace(
        rules=rules,
        activities={
            "target": {
                "Start Depot": "A",
                "End Depot": "A",
                "Roles/Job": "Role",
                "Currency Threshold": "",
            }
        },
        crew={"U1": {"Medical": "Fit", "Role": "Role"}},
        eligible={"target": {"U1"}},
        last_done={},
    )
    swing = SimpleNamespace(user="U1", status="movable", reason="", classification="Residential")
    seat = SimpleNamespace(
        start=start,
        activity_id="target",
        key="target@2026-11-07T23:00",
        demand_id="",
        level=0,
    )
    new_row = {"Assignment Type": "Demand", "_s": start, "Activity ID": "other", "Is Locked": "False"}
    unchanged_row = {"Assignment Type": "Excess", "_s": start, "Activity ID": "target", "Is Locked": "False"}
    swing.rows = [new_row]
    rejected, reason = try_fill(data, swing, 0, seat, Costs())
    assert rejected is None
    assert "22:00 and 02:00" in reason

    swing.rows = [unchanged_row]
    accepted, reason = try_fill(data, swing, 0, seat, Costs())
    assert accepted is not None, reason
    assert accepted.unchanged is True


@pytest.mark.parametrize(
    ("restriction", "unchanged", "expected"),
    [(True, False, "keep"), (False, False, "fill"), (True, True, "fill")],
)
def test_cp_sat_blocks_new_residential_night_start_but_keeps_existing(
    tmp_path: Path, restriction: bool, unchanged: bool, expected: str
):
    config = tmp_path / "config.yml"
    config.write_text(
        "constraints:\n"
        + "\n".join(
            (
                f"  residential_start_restriction: {str(restriction).lower()}",
                "  relief_only_day_night_transition: false",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"), config)
    assert rules.residential_start_restriction is restriction
    rules = replace(
        rules,
        rest=timedelta(hours=8),
        transition_rest=timedelta(hours=8),
        day_from=6 * 60,
        day_to=18 * 60,
    )
    first = Option(
        0, "keep", datetime(2026, 11, 1, 6), datetime(2026, 11, 1, 14), "A", "A", "relief",
        standby=True, source="Relief",
    )
    existing = Option(
        1, "keep", datetime(2026, 11, 2, 23), datetime(2026, 11, 3, 7), "A", "A",
        "target" if unchanged else "existing", source="Excess" if unchanged else "Demand", unchanged=True,
    )
    candidate = Option(
        1, "fill", datetime(2026, 11, 2, 23), datetime(2026, 11, 3, 7), "A", "A", "target",
        seat="target@2026-11-02T23:00", source="Excess" if unchanged else "Demand", unchanged=unchanged,
    )
    swing = SimpleNamespace(
        key="U1|1",
        user="U1",
        home="A",
        classification="Residential",
        earliest_start=None,
        latest_end=None,
        row_ids=["R1", "R2"],
        droppable=[False, False],
        options=[[first], [existing, candidate]],
    )
    seat = SimpleNamespace(capacity=1, priority=1)

    result = solve(rules, {candidate.seat: seat}, [swing], SimpleNamespace(), 2, 1, 0)

    assert result.chosen[swing.key][1].kind == expected


@pytest.mark.parametrize(
    ("enabled", "previous_source", "expected"),
    [(True, "Demand", "keep"), (True, "Relief", "fill"), (False, "Demand", "fill")],
)
def test_cp_sat_enforces_relief_only_day_night_transition(
    tmp_path: Path, enabled: bool, previous_source: str, expected: str
):
    config = tmp_path / "config.yml"
    config.write_text(
        "constraints:\n"
        + "\n".join(
            (
                "  residential_start_restriction: true",
                f"  relief_only_day_night_transition: {str(enabled).lower()}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    loaded_rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"), config)
    assert loaded_rules.residential_start_restriction is True
    rules = replace(
        loaded_rules,
        rest=timedelta(hours=8),
        transition_rest=timedelta(hours=8),
        day_from=6 * 60,
        day_to=18 * 60,
    )
    first = Option(
        0, "keep", datetime(2026, 11, 1, 6), datetime(2026, 11, 1, 14), "A", "A",
        "previous", source=previous_source, standby=previous_source == "Relief",
    )
    existing = Option(
        1, "keep", datetime(2026, 11, 2, 6), datetime(2026, 11, 2, 14), "A", "A", "existing",
        source="Demand", unchanged=True,
    )
    candidate = Option(
        1, "fill", datetime(2026, 11, 2, 22), datetime(2026, 11, 3, 6), "A", "A", "target",
        seat="target@2026-11-02T22:00", source="Demand",
    )
    swing = SimpleNamespace(
        key="U1|transition",
        user="U1",
        home="A",
        classification="FIFO",
        earliest_start=None,
        latest_end=None,
        row_ids=["R1", "R2"],
        droppable=[False, False],
        options=[[first], [existing, candidate]],
    )

    result = solve(rules, {candidate.seat: SimpleNamespace(capacity=1, priority=1)}, [swing], SimpleNamespace(), 2, 1, 0)

    assert result.chosen[swing.key][1].kind == expected
