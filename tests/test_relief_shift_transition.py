from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from option_generation.rules import Rules

rules = Rules(
    horizon_start=date(2026, 11, 1),
    horizon_days=30,
    solver_start=date(2026, 11, 1),
    shift_hours=8,
    rest=timedelta(hours=8),
    transition_rest=timedelta(hours=12),
    day_from=6 * 60,
    day_to=18 * 60,
    off_days={"FIFO": 2, "Residential": 2},
    excess_offsets=frozenset({0}),
    demand_offsets=frozenset({0}),
    max_changes=3,
    max_change_minutes=120,
)


def make_shift(day, start_hour, source):
    start = datetime(2026, 11, day, start_hour)
    end = start + timedelta(hours=8)

    return SimpleNamespace(
        start=start,
        end=end,
        start_loc="A",
        end_loc="A",
        source=source,
        standby=False,
    )


def test_relief_day_to_night():
    first = make_shift(1, 6, "Relief")
    second = make_shift(2, 22, "Demand")
    assert rules.can_follow(first, second)


def test_relief_night_to_day():
    first = make_shift(1, 22, "Relief")
    second = make_shift(3, 6, "Demand")
    assert rules.can_follow(first, second)


def test_demand_cannot_change_day_to_night():
    first = make_shift(1, 6, "Demand")
    second = make_shift(2, 22, "Relief")
    assert not rules.can_follow(first, second)


def test_excess_cannot_change_night_to_day():
    first = make_shift(1, 22, "Excess")
    second = make_shift(2, 6, "Demand")
    assert not rules.can_follow(first, second)


def test_non_relief_can_change_blocks_when_restriction_is_disabled():
    first = make_shift(1, 6, "Demand")
    second = make_shift(2, 22, "Demand")
    unrestricted = replace(rules, relief_only_day_night_transition=False)
    assert unrestricted.can_follow(first, second)


def test_demand_can_continue_same_shift():
    first = make_shift(1, 6, "Demand")
    second = make_shift(2, 6, "Excess")
    assert rules.can_follow(first, second)


def test_excess_can_continue_same_shift():
    first = make_shift(1, 22, "Excess")
    second = make_shift(2, 22, "Demand")
    assert rules.can_follow(first, second)
