"""Location continuity, initial location and optional positioning."""

import pytest
from helpers import covered, crew, duty, make_instance, pairs, solve


def test_no_teleporting_between_duties():
    inst = make_instance(
        [crew("A", "Howrah")],
        [
            duty("D1", "2026-11-01 05:00", "Howrah", "Yajpur", eligible=["A"]),
            duty("D2", "2026-11-02 05:00", "Howrah", "Yajpur", eligible=["A"]),
        ],
    )
    assert covered(solve(inst)) == 1


def test_duty_moves_crew_to_end_location():
    inst = make_instance(
        [crew("A", "Howrah")],
        [
            duty("D1", "2026-11-01 05:00", "Howrah", "Yajpur", eligible=["A"]),
            duty("D2", "2026-11-02 05:00", "Yajpur", "Howrah", "Yajpur Mainline", eligible=["A"]),
        ],
    )
    r = solve(inst)
    assert covered(r) == 2 and r.solution.routes["A"] == ["D1", "D2"]


def test_initial_location_must_match_first_duty():
    inst = make_instance([crew("A", "Yajpur")], [duty("D1", "2026-11-01 05:00", "Howrah", "Yajpur", eligible=["A"])])
    r = solve(inst)
    assert covered(r) == 0
    assert r.candidates.diagnostics["D1"].structural_reason() == "NO_FEASIBLE_SEQUENCE"


@pytest.mark.parametrize("start, expected", [("2026-11-01 06:00", 1), ("2026-11-01 05:59", 0)])
def test_positioning_from_initial_location_takes_travel_time(start, expected):
    inst = make_instance(
        [crew("A", "Yajpur")],
        [duty("D1", start, "Howrah", "Howrah", "Howrah Mainline CO", eligible=["A"])],
        travel=[("Yajpur", "Howrah", 360)],
    )
    assert covered(solve(inst)) == 0  # positioning disabled by default
    r = solve(inst, positioning_enabled=True)
    assert covered(r) == expected
    if expected:
        assert len(r.solution.positioning) == 1 and r.solution.positioning[0]["from_location"] == "Yajpur"


@pytest.mark.parametrize(
    "start, counts_as_rest, expected",
    [
        ("2026-11-02 10:00", False, 2),  # 17:00 + 11 h rest + 6 h travel
        ("2026-11-02 09:59", False, 1),
        ("2026-11-02 04:00", True, 2),  # max(11 h, 6 h) after 17:00
        ("2026-11-02 03:59", True, 1),
    ],
)
def test_positioning_between_duties_rest_plus_travel(start, counts_as_rest, expected):
    inst = make_instance(
        [crew("A", "Howrah")],
        [
            duty("D1", "2026-11-01 05:00", "Howrah", "Yajpur", eligible=["A"]),
            duty("D2", start, "Howrah", "Howrah", "Howrah Mainline CO", eligible=["A"], shift="DAY"),
        ],
        travel=[("Yajpur", "Howrah", 360)],
    )
    r = solve(inst, positioning_enabled=True, positioning_counts_as_rest=counts_as_rest)
    assert covered(r) == expected


def test_positioning_cost_is_minimised_after_coverage():
    inst = make_instance(
        [crew("A", "Howrah"), crew("B", "Yajpur")],
        [duty("D1", "2026-11-01 12:00", "Howrah", "Howrah", "Howrah Mainline CO", eligible=["A", "B"])],
        travel=[("Yajpur", "Howrah", 360)],
    )
    r = solve(inst, positioning_enabled=True)
    assert pairs(r) == {("A", "D1")}
    assert r.solution.positioning == []
