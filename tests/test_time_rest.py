"""Overlap, 11 h ordinary rest, 23 h transition rest, midnight and horizon boundaries."""

import pytest
from helpers import covered, crew, duty, make_instance, solve

from railway_rostering import ShiftType

A = [crew("A")]


def local(did, start, **kw):
    """A Howrah -> Howrah duty so location never interferes."""
    return duty(did, start, "Howrah", "Howrah", "Howrah Mainline CO", eligible=["A"], **kw)


def test_overlapping_duties_cannot_both_be_assigned():
    inst = make_instance(A, [local("D1", "2026-11-01 05:00"), local("D2", "2026-11-01 10:00")])
    r = solve(inst, max_duties_per_day=None)
    assert covered(r) == 1


@pytest.mark.parametrize("second_start, expected", [("2026-11-02 16:00", 2), ("2026-11-02 15:59", 1)])
def test_ordinary_rest_exact_boundary(second_start, expected):
    # D1 17:00 -> 05:00 next day; D2 must start >= 05:00 + 11 h = 16:00.
    inst = make_instance(A, [local("D1", "2026-11-01 17:00"), local("D2", second_start, shift="NIGHT")])
    assert covered(solve(inst)) == expected


@pytest.mark.parametrize("second_start, expected", [("2026-11-03 04:00", 2), ("2026-11-03 03:59", 1)])
def test_transition_rest_exact_boundary(second_start, expected):
    # Night duty ends 2 Nov 05:00; a DAY duty needs >= 23 h -> 3 Nov 04:00.
    inst = make_instance(A, [local("D1", "2026-11-01 17:00"), local("D2", second_start)])
    assert covered(solve(inst)) == expected


def test_transition_rest_only_applies_to_transitions():
    # Same 11 h gap: NIGHT -> NIGHT ok, NIGHT -> DAY needs 23 h.
    night_night = make_instance(A, [local("D1", "2026-11-01 17:00"), local("D2", "2026-11-02 16:00", shift="NIGHT")])
    night_day = make_instance(A, [local("D1", "2026-11-01 17:00"), local("D2", "2026-11-02 16:00", shift="DAY")])
    assert covered(solve(night_night)) == 2
    assert covered(solve(night_day)) == 1
    assert covered(solve(night_day, transition_rest_enabled=False)) == 2


def test_shift_classification_window_is_configurable():
    inst = make_instance(A, [local("D1", "2026-11-01 17:00"), local("D2", "2026-11-02 16:00")])
    # Default window [03:00,15:00): 16:00 is NIGHT -> no transition.
    assert covered(solve(inst)) == 2
    # Widen DAY to 03:00-17:00: 16:00 becomes DAY -> transition -> 23 h needed.
    assert covered(solve(inst, day_shift_start_until="17:00")) == 1


@pytest.mark.parametrize(
    "start, shift, expected",
    [
        ("2026-11-01 13:00", "NIGHT", 1),  # 11 h after prior end 02:00
        ("2026-11-01 12:59", "NIGHT", 0),
        ("2026-11-01 13:00", "DAY", 0),  # transition from prior NIGHT needs 23 h
        ("2026-11-02 01:00", "DAY", 1),  # exactly 23 h
    ],
)
def test_rest_after_prior_duty_at_horizon_start(start, shift, expected):
    c = [crew("A", prior_duty_end="2026-11-01 02:00", prior_shift_type=ShiftType.NIGHT)]
    inst = make_instance(c, [local("D1", start, shift=shift)])
    assert covered(solve(inst)) == expected


@pytest.mark.parametrize("commit, expected", [("2026-11-02 16:00", 1), ("2026-11-02 15:59", 0)])
def test_rest_before_next_commitment(commit, expected):
    c = [
        crew(
            "A",
            next_commitment_start=commit,
            next_commitment_location="Howrah",
            next_commitment_shift_type=ShiftType.NIGHT,
        )
    ]
    inst = make_instance(c, [local("D1", "2026-11-01 17:00")])
    assert covered(solve(inst)) == expected


def test_next_commitment_location_continuity():
    c = [crew("A", next_commitment_start="2026-11-05 05:00", next_commitment_location="Howrah")]
    away = make_instance(c, [duty("D1", "2026-11-01 05:00", "Howrah", "Yajpur", eligible=["A"])])
    assert covered(solve(away)) == 0


def test_midnight_crossing_end_and_daily_cap():
    d2 = local("D2", "2026-11-01 23:00")
    assert d2.end.strftime("%Y-%m-%d %H:%M") == "2026-11-02 11:00"
    inst = make_instance(A, [local("D1", "2026-11-01 00:00"), d2])  # 11 h rest between them
    assert covered(solve(inst)) == 1  # default cap: one start per date
    assert covered(solve(inst, max_duties_per_day=None)) == 2
    assert covered(solve(inst, max_duties_per_day=2)) == 2


def test_rest_holds_for_every_consecutive_pair_in_long_sequence():
    duties = [local(f"D{k}", f"2026-11-0{k} 17:00") for k in range(1, 7)]
    r = solve(make_instance(A, duties))
    assert covered(r) == 6
    assert r.solution.routes["A"] == [f"D{k}" for k in range(1, 7)]
    assert r.validation.passed
