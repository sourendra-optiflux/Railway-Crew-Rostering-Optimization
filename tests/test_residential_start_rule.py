from dataclasses import replace
from datetime import datetime

import pytest

from option_generation.rules import Rules


@pytest.fixture
def rules():
    return Rules(
        horizon_start=datetime(2026, 11, 1).date(),
        horizon_days=30,
        solver_start=datetime(2026, 11, 6).date(),
        shift_hours=8,
        rest=__import__("datetime").timedelta(hours=11),
        transition_rest=__import__("datetime").timedelta(hours=23),
        day_from=6 * 60,
        day_to=18 * 60,
        off_days={"FIFO": 6, "Residential": 6},
        excess_offsets=frozenset({-60, 0, 60}),
        demand_offsets=frozenset({-60, 0, 60}),
        max_changes=1,
        max_change_minutes=60,
    )


@pytest.mark.parametrize(
    "time, expected",
    [
        ("21:59", True),
        ("22:00", False),
        ("23:00", False),
        ("00:00", False),
        ("01:59", False),
        ("02:00", True),
        ("02:01", True),
    ],
)
def test_residential_start_window(rules, time, expected):
    start = datetime.fromisoformat(f"2026-11-07T{time}")
    assert rules.residential_start_allowed(start) is expected


def test_residential_start_window_can_be_disabled(rules):
    unrestricted = replace(rules, residential_start_restriction=False)
    assert unrestricted.residential_start_allowed(datetime(2026, 11, 7, 23)) is True
