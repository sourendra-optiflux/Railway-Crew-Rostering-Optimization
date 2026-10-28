"""Swing work/off days and Relief/Excess shift-time changes (lift-up/layback, persistence)."""

import pytest
from helpers import covered, crew, duty, make_instance, pairs, solve


def excess(**kw):
    args = dict(loc="Howrah", ctype="EXCESS", base="Howrah", rostered="17:00", swing_start="2026-11-01", work=6, off=6)
    args.update(kw)
    return crew("E", **args)


def relief(**kw):
    args = dict(
        loc="Howrah", ctype="RELIEF", base="Howrah", rostered="17:00", swing_start="2026-11-01", work=14, off=14
    )
    args.update(kw)
    return crew("R", **args)


def local(did, start, who="E"):
    return duty(did, start, "Howrah", "Howrah", "Howrah Mainline CO", eligible=[who])


@pytest.mark.parametrize(
    "start, expected",
    [("2026-11-06 17:00", 1), ("2026-11-07 17:00", 0), ("2026-11-12 17:00", 0), ("2026-11-13 17:00", 1)],
)
def test_excess_six_on_six_off(start, expected):
    r = solve(make_instance([excess()], [local("D", start)], days=14))
    assert covered(r) == expected
    if not expected:
        assert r.candidates.diagnostics["D"].structural_reason() == "NO_AVAILABLE_CREW"


def test_default_pattern_from_crew_type():
    c = excess(work=None, off=None)  # falls back to ModelConfig default 6/6 for EXCESS
    assert covered(solve(make_instance([c], [local("D", "2026-11-07 17:00")], days=14))) == 0


def test_off_day_rule_can_be_disabled():
    inst = make_instance([excess()], [local("D", "2026-11-07 17:00")], days=14)
    assert covered(solve(inst, enforce_swing_work_days=False)) == 1


@pytest.mark.parametrize(
    "start, expected",
    [("2026-11-02 16:00", 1), ("2026-11-02 17:00", 1), ("2026-11-02 18:00", 1),
     ("2026-11-02 15:00", 0), ("2026-11-02 16:30", 0), ("2026-11-02 19:00", 0)],
)  # fmt: skip
def test_excess_lift_up_and_layback_only(start, expected):
    r = solve(make_instance([excess()], [local("D", start)]))
    assert covered(r) == expected
    if not expected:
        assert r.candidates.diagnostics["D"].structural_reason() == "NO_TIME_COMPATIBLE_CREW"


def _efg(hours):
    return [local(f"D{k}", f"2026-11-0{k} {h:02d}:00") for k, h in enumerate(hours, start=1)]


@pytest.mark.parametrize(
    "hours, persist, window",
    [
        ([17, 17, 17, 17], 4, 4),  # all days 5 PM
        ([16, 16, 16, 16], 4, 4),  # all days 4 PM
        ([17, 18, 18, 18], 4, 4),  # 5 PM then layback persisted
        ([16, 17, 16, 17], 2, 4),  # briefing pattern with several changes
        ([16, 17, 18, 18], 3, 4),  # best: skip day 1, then 5 PM, 6 PM, 6 PM
    ],
)
def test_efg_patterns_under_both_policies(hours, persist, window):
    inst = make_instance([excess()], _efg(hours))
    assert covered(solve(inst)) == persist
    policy = {"RELIEF": "window_only", "EXCESS": "window_only"}
    assert covered(solve(inst, time_change_policy=policy)) == window


def test_time_change_resets_in_new_swing():
    inst = make_instance([excess()], [local("D1", "2026-11-02 18:00"), local("D2", "2026-11-13 17:00")], days=14)
    assert covered(solve(inst)) == 2
    same_swing = make_instance([excess()], [local("D1", "2026-11-02 18:00"), local("D2", "2026-11-05 17:00")], days=14)
    assert covered(solve(same_swing)) == 1


@pytest.mark.parametrize("start, expected", [("2026-11-02 17:00", 0), ("2026-11-02 18:00", 1), ("2026-11-13 17:00", 1)])
def test_change_made_before_horizon_persists_in_current_swing(start, expected):
    inst = make_instance([excess(current_start="18:00")], [local("D", start)], days=14)
    assert covered(solve(inst)) == expected


def test_relief_can_take_any_time_but_change_persists():
    # Briefing Relief example "10 AM, 10 AM, 11 AM, 11 AM" for a 5 PM crew member.
    duties = [local(f"D{k}", f"2026-11-0{k} {h}:00", who="R") for k, h in enumerate([10, 10, 11, 11], start=1)]
    inst = make_instance([relief()], duties)
    assert covered(solve(inst)) == 2
    assert covered(solve(inst, time_change_policy={"RELIEF": "window_only", "EXCESS": "window_only"})) == 4
    assert covered(solve(inst, time_change_policy={"RELIEF": "disabled", "EXCESS": "disabled"})) == 4


def test_relief_offsets_can_be_restricted():
    inst = make_instance([relief()], [local("D", "2026-11-02 10:00", who="R")])
    assert covered(solve(inst)) == 1
    assert covered(solve(inst, allowed_offsets_minutes={"RELIEF": [-60, 0, 60], "EXCESS": [-60, 0, 60]})) == 0


def test_unavailable_date():
    from datetime import date

    c = excess(unavailable_dates=frozenset({date(2026, 11, 2)}))
    inst = make_instance([c], [local("D1", "2026-11-02 17:00"), local("D2", "2026-11-03 17:00")])
    assert pairs(solve(inst)) == {("E", "D2")}
