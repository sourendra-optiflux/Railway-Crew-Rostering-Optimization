"""Return-to-base at swing end and on day/night transitions."""

import pytest
from helpers import covered, crew, duty, make_instance, solve


def excess_day():
    return crew("E", "Howrah", "EXCESS", base="Howrah", rostered="05:00", swing_start="2026-11-01", work=6, off=6)


def test_last_swing_day_must_end_at_base():
    # Swing 1-6 Nov lies inside a 7-day horizon; a duty on 6 Nov ending at Yajpur strands E.
    inst = make_instance([excess_day()], [duty("D6", "2026-11-06 05:00", "Howrah", "Yajpur", eligible=["E"])])
    r = solve(inst)
    assert covered(r) == 0
    assert r.candidates.diagnostics["D6"].structural_reason() == "NO_FEASIBLE_SEQUENCE"
    assert covered(solve(inst, base_return_at_swing_end=False)) == 1


def test_returning_to_base_by_duty_satisfies_rule():
    inst = make_instance(
        [excess_day()],
        [
            duty("D5", "2026-11-05 05:00", "Howrah", "Yajpur", eligible=["E"]),
            duty("D6", "2026-11-06 05:00", "Yajpur", "Howrah", "Yajpur Mainline", eligible=["E"]),
        ],
    )
    assert covered(solve(inst)) == 2


def test_swing_continuing_beyond_horizon_has_no_end_requirement():
    inst = make_instance([excess_day()], [duty("D5", "2026-11-05 05:00", "Howrah", "Yajpur", eligible=["E"])], days=5)
    assert covered(solve(inst)) == 1
    assert covered(solve(inst, base_return_at_horizon_end=True)) == 0


def test_base_return_between_swings():
    # D6 ends at Yajpur on the last day of swing 0; D13 (next swing) starts at Yajpur.
    inst = make_instance(
        [excess_day()],
        [
            duty("D6", "2026-11-06 05:00", "Howrah", "Yajpur", eligible=["E"]),
            duty("D13", "2026-11-13 05:00", "Yajpur", "Howrah", "Yajpur Mainline", eligible=["E"]),
        ],
        days=13,
    )
    # D6 cannot end the swing away from base, and D13 cannot be reached without D6.
    assert covered(solve(inst)) == 0
    assert covered(solve(inst, base_return_at_swing_end=False)) == 2


def relief_night():
    return crew("R", "Howrah", "RELIEF", base="Howrah", rostered="17:00", swing_start="2026-11-01", work=14, off=14)


@pytest.mark.parametrize("day_start", ["2026-11-03 05:00", "2026-11-04 05:00"])
def test_transition_requires_base(day_start):
    duties = [
        duty("N1", "2026-11-01 17:00", "Howrah", "Yajpur", eligible=["R"]),  # ends Yajpur
        duty("D2", day_start, "Yajpur", "Howrah", "Yajpur Mainline", eligible=["R"]),  # DAY: transition
    ]
    inst = make_instance([relief_night()], duties, travel=[("Yajpur", "Howrah", 360), ("Howrah", "Yajpur", 360)])
    assert covered(solve(inst)) == 1
    assert covered(solve(inst, base_return_on_transition=False)) == 2
    # With positioning the crew can go home and come back: needs 23 h + 2 x 6 h.
    r = solve(inst, positioning_enabled=True)
    expected = 2 if day_start == "2026-11-04 05:00" else 1
    assert covered(r) == expected
    if expected == 2:
        assert [p["base_return_reason"] for p in r.solution.positioning] == ["shift transition"] * 2


def test_briefing_transition_sequence_returns_to_base():
    # ABC: night duties end with Howrah Mainline CO (HWH->HWH), then day duties.
    duties = [
        duty("N3", "2026-11-03 17:00", "Howrah", "Howrah", "Howrah Mainline CO", eligible=["R"]),
        duty("D5", "2026-11-05 05:00", "Howrah", "Yajpur", eligible=["R"]),
    ]
    assert covered(solve(make_instance([relief_night()], duties))) == 2
