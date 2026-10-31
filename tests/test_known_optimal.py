"""Hand-checkable instances with known optimal coverage, and brute-force cross-checks.

The brute-force check enumerates *every* possible assignment of a tiny random
instance, keeps those the independent validator accepts, and compares the best
coverage with CP-SAT's proven optimum. CP-SAT (circuit + candidate arcs) and
the validator are separate implementations of the rules, so agreement over
many random instances and rule configurations is evidence that the
sequencing formulation is correct - not just that the solver returned
something.
"""

import random
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from helpers import H0, brute_force_max_coverage, covered, crew, duty, make_instance, pairs, solve

from railway_rostering import ModelConfig, load_instance
from railway_rostering.domain import ShiftType

ROOT = Path(__file__).resolve().parents[1]


def test_v1_sheets_notebook_instance_covers_all_five():
    r = solve(load_instance(ROOT / "tests/fixtures/v1_toy"))
    assert r.solution.status == "OPTIMAL" and covered(r) == 5 and r.validation.passed


def test_v1_colab_notebook_instance_covers_four():
    inst = load_instance(ROOT / "tests/fixtures/v1_toy")
    inst.crews["A"] = replace(inst.crews["A"], initial_location="Yajpur")  # railway_crew_v1.ipynb data
    r = solve(inst)
    assert covered(r) == 4
    # G1 starts at Howrah but both eligible crew (A, B) start in Yajpur.
    assert "G1" not in {d for _, d in pairs(r)}
    assert r.candidates.diagnostics["G1"].structural_reason() == "NO_FEASIBLE_SEQUENCE"


def test_briefing_abc_sequence_is_reproduced():
    r = solve(load_instance(ROOT / "data/sample/briefing_abc"))
    assert r.solution.status == "OPTIMAL"
    assert r.solution.routes == {"ABC": ["DM02-20261101", "DM04-20261102", "DM06-20261103", "DM01-20261105", "DM03-20261106", "DM05-20261107"]}
    assert r.validation.passed


def test_briefing_abc_rejects_duty_on_transition_day():
    inst = load_instance(ROOT / "data/sample/briefing_abc")
    extra = duty("D04", "2026-11-04 05:00", "Howrah", "Yajpur", "Howrah Mainline", eligible=["ABC"])
    inst = make_instance(list(inst.crews.values()), inst.duties + [extra])
    r = solve(inst)
    assert covered(r) == 6 and "D04" not in r.solution.routes["ABC"]


def test_cp_sat_note_three_duty_example():
    # From Progress/CP_SAT_vs_MIP_Solvers.pdf: every pair conflicts -> optimum 1.
    inst = make_instance(
        [crew("A", "Howrah")],
        [
            duty("D1", "2026-01-01 05:00", eligible=["A"]),
            duty("D2", "2026-01-01 17:00", eligible=["A"]),
            duty("D3", "2026-01-02 05:00", eligible=["A"]),
        ],
        start=H0.replace(year=2026, month=1, day=1),
    )
    r = solve(inst)
    assert r.solution.status == "OPTIMAL" and covered(r) == 1


# ---------------------------------------------------------------------------
# Brute force on random tiny instances
# ---------------------------------------------------------------------------

LOCS = ["Howrah", "Yajpur"]


def random_tiny(seed: int):
    rng = random.Random(seed)
    crews = []
    for k in range(3):
        ctype = rng.choice(["RELIEF", "EXCESS", "UNSPECIFIED"])
        kw = {}
        if rng.random() < 0.3:
            kw["prior_duty_end"] = (H0 + timedelta(hours=rng.randint(-10, 3))).strftime("%Y-%m-%d %H:%M")
            kw["prior_shift_type"] = rng.choice([ShiftType.DAY, ShiftType.NIGHT])
        if rng.random() < 0.2:
            kw["next_commitment_start"] = (H0 + timedelta(days=3, hours=rng.randint(0, 20))).strftime("%Y-%m-%d %H:%M")
            kw["next_commitment_location"] = rng.choice(LOCS)
        crews.append(
            crew(
                f"C{k}",
                rng.choice(LOCS),
                ctype,
                base=rng.choice(LOCS + [None]),
                rostered=rng.choice(["05:00", "17:00"]) if ctype != "UNSPECIFIED" else None,
                swing_start=(date(2026, 11, 1) - timedelta(days=rng.randrange(5))).isoformat()
                if ctype != "UNSPECIFIED"
                else None,
                work=3,
                off=2,
                **kw,
            )
        )
    duties = []
    for k in range(5):
        day = rng.randrange(3)
        hour = rng.choice([4, 5, 6, 16, 17, 18, rng.randrange(24)])
        s, e = rng.choice(LOCS), rng.choice(LOCS)
        eligible = [c.crew_id for c in crews if rng.random() < 0.75]
        duties.append(
            duty(
                f"D{k}",
                (H0 + timedelta(days=day, hours=hour)).strftime("%Y-%m-%d %H:%M"),
                s,
                e,
                eligible=eligible,
                demand=2 if rng.random() < 0.15 else 1,
                hours=rng.choice([12, 12, 12, 8]),
            )
        )
    cfg = ModelConfig(
        transition_rest_enabled=rng.random() < 0.7,
        base_return_at_swing_end=rng.random() < 0.6,
        base_return_on_transition=rng.random() < 0.6,
        positioning_enabled=rng.random() < 0.3,
        positioning_counts_as_rest=rng.random() < 0.5,
        max_duties_per_day=rng.choice([1, None, 2]),
        enforce_swing_work_days=rng.random() < 0.8,
        time_change_policy={
            "RELIEF": rng.choice(["persist_after_change", "window_only", "disabled"]),
            "EXCESS": rng.choice(["persist_after_change", "window_only", "disabled"]),
        },
        demand_mode=rng.choice(["partial", "partial", "all_or_nothing"]),
    )
    travel = [("Howrah", "Yajpur", 240), ("Yajpur", "Howrah", 240)]
    return make_instance(crews, duties, days=4, travel=travel), cfg


@pytest.mark.parametrize("seed", range(40))
def test_cp_sat_matches_brute_force(seed):
    inst, cfg = random_tiny(seed)
    expected = brute_force_max_coverage(inst, cfg)
    r = solve(inst, **{k: v for k, v in cfg.to_dict().items()})
    assert r.solution.status == "OPTIMAL"
    assert covered(r) == expected, f"seed {seed}: CP-SAT {covered(r)} vs brute force {expected}"
    assert r.validation.passed, r.validation.to_dict()["violations"]
