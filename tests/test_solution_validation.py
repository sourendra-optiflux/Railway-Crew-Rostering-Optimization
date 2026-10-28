"""Independent validator: a correct roster passes, every injected violation is caught."""

from datetime import date

import pytest
from helpers import crew, duty, make_instance

from railway_rostering import ModelConfig, ShiftType
from railway_rostering import solution_validation as sv
from railway_rostering.solution_validation import validate_solution

ALL = ["Howrah Mainline", "Yajpur Mainline", "Howrah Mainline CO"]


def build():
    crews = [
        crew("E", "Howrah", "EXCESS", base="Howrah", rostered="17:00", swing_start="2026-11-01", work=6, off=6),
        crew("U", "Howrah"),
        crew("L", "Howrah", unavailable_dates=frozenset({date(2026, 11, 2)})),
        crew("N", "Howrah", next_commitment_start="2026-11-02 12:00", next_commitment_location="Howrah"),
    ]
    duties = [
        duty("N1", "2026-11-01 17:00", "Howrah", "Yajpur"),
        duty("N2", "2026-11-02 17:00", "Yajpur", "Howrah", "Yajpur Mainline"),
        duty("X1", "2026-11-01 20:00", "Howrah", "Howrah", "Howrah Mainline CO"),  # overlaps N1
        duty("R1", "2026-11-02 15:00", "Yajpur", "Yajpur", "Yajpur Mainline", shift="NIGHT"),  # 10 h after N1
        duty("T1", "2026-11-02 16:00", "Yajpur", "Yajpur", "Yajpur Mainline", shift="DAY"),  # transition after N1
        duty("L1", "2026-11-03 17:00", "Yajpur", "Yajpur", "Yajpur Mainline"),  # after N2 crew is in Howrah
        duty("O1", "2026-11-07 17:00", "Howrah", "Howrah", "Howrah Mainline CO"),  # E's off day
        duty("W1", "2026-11-03 15:00", "Howrah", "Howrah", "Howrah Mainline CO"),  # E offset -120
        duty("P1", "2026-11-03 18:00", "Howrah", "Howrah", "Howrah Mainline CO"),
        duty("P2", "2026-11-04 17:00", "Howrah", "Howrah", "Howrah Mainline CO"),  # back to 17:00
        duty("B1", "2026-11-06 17:00", "Howrah", "Yajpur"),  # E's last swing day, ends away
        duty("Q1", "2026-11-03 05:00", "Howrah", "Howrah", "Nellore Driver"),  # nobody qualified
        duty("F1", "2026-11-04 05:00", "Howrah", "Howrah", "Howrah Mainline CO", assigned_crew=("U",)),
        duty("C1", "2026-11-05 00:00", "Howrah", "Howrah", "Howrah Mainline CO"),
        duty("C2", "2026-11-05 23:00", "Howrah", "Howrah", "Howrah Mainline CO"),  # same date as C1
    ]
    quals = {c.crew_id: set(ALL) for c in crews}
    return make_instance(crews, duties, quals=quals, days=7)


CFG = ModelConfig()
VALID = [("E", "N1"), ("E", "N2"), ("U", "X1"), ("U", "F1")]


def rules(assignments, cfg=CFG, **kw):
    return {v.rule for v in validate_solution(build(), cfg, assignments, **kw).violations}


def test_valid_roster_passes():
    rep = validate_solution(build(), CFG, VALID)
    assert rep.passed, rep.to_dict()["violations"]
    assert rep.coverage["covered_units"] == 3  # F1 is existing, not new coverage


@pytest.mark.parametrize(
    "extra, expected",
    [
        ([("E", "X1")], sv.OVERLAP),
        ([("U", "N1"), ("U", "R1")], sv.INSUFFICIENT_REST),
        ([("U", "N1"), ("U", "T1")], sv.INSUFFICIENT_REST),
        ([("U", "L1")], sv.LOCATION),
        ([("E", "O1")], sv.OFF_DAY),
        ([("E", "W1")], sv.TIME_NOT_ALLOWED),
        ([("E", "P1"), ("E", "P2")], sv.TIME_PERSISTENCE),
        ([("E", "B1")], sv.BASE_RETURN),
        ([("U", "Q1")], sv.INELIGIBLE),
        ([("U", "N1"), ("E", "N1")], sv.DEMAND_EXCEEDED),
        ([("U", "C1"), ("U", "C2")], sv.DAILY_CAP),
        ([("L", "R1")], sv.UNAVAILABLE),
        ([("N", "X1")], sv.NEXT_COMMITMENT),
        ([("ZZZ", "N1")], sv.UNKNOWN_ID),
        ([("U", "X1")], sv.DUPLICATE_ASSIGNMENT),
    ],
)
def test_injected_violation_detected(extra, expected):
    base = (
        [p for p in VALID if not any(p[0] == e[0] and p[1] == e[1] for e in extra)]
        if expected != sv.DUPLICATE_ASSIGNMENT
        else VALID
    )
    found = rules(base + extra)
    assert expected in found, found


def test_dropping_existing_assignment_detected():
    assert sv.EXISTING_DROPPED in rules([("E", "N1"), ("E", "N2"), ("U", "X1")])


def test_transition_rest_violation_disappears_when_rule_disabled():
    roster = [("U", "N1"), ("U", "T1"), ("U", "F1")]  # 11 h NIGHT -> DAY gap
    assert sv.INSUFFICIENT_REST in rules(roster)
    cfg = ModelConfig(transition_rest_enabled=False, base_return_on_transition=False)
    # Only the (genuine) Yajpur -> Howrah discontinuity before F1 remains.
    assert rules(roster, cfg) == {sv.LOCATION}


def test_coverage_mismatch_detected():
    assert sv.COVERAGE_MISMATCH in rules(VALID, claimed_covered_units=4)
    assert sv.COVERAGE_MISMATCH not in rules(VALID, claimed_covered_units=3)


def test_prior_duty_rest_checked():
    inst = make_instance(
        [crew("A", prior_duty_end="2026-11-01 02:00", prior_shift_type=ShiftType.NIGHT)],
        [duty("D", "2026-11-01 12:00", "Howrah", "Howrah", eligible=["A"], shift="NIGHT")],
    )
    rep = validate_solution(inst, CFG, [("A", "D")])
    assert {v.rule for v in rep.violations} == {sv.INSUFFICIENT_REST}


def test_partial_staffing_in_all_or_nothing_mode():
    inst = make_instance([crew("A")], [duty("D", "2026-11-01 05:00", eligible=["A"], demand=2)])
    rep = validate_solution(inst, ModelConfig(demand_mode="all_or_nothing"), [("A", "D")])
    assert sv.PARTIAL_STAFFING in {v.rule for v in rep.violations}


def test_validator_does_not_import_model_code():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(sv))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    forbidden = {"candidate_generation", "model", "objective", "solve", "heuristics", "constraints"}
    assert not any(m.split(".")[-1] in forbidden or "constraints" in m for m in imported), imported
