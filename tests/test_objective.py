"""Lexicographic / weighted objective behaviour and the LP-bound cut."""

import pytest
from helpers import crew, duty, make_instance, pairs, solve

from railway_rostering import SolverConfig
from railway_rostering.synthetic import SyntheticConfig, generate_instance


def _priority_instance():
    # A can do HI (05:00-17:00) or LO1 (00:00-12:00) + LO2 (23:00-11:00, 11 h after LO1),
    # but HI conflicts with both: it overlaps LO1 and leaves only 6 h rest before LO2.
    return make_instance(
        [crew("A")],
        [
            duty("HI", "2026-11-01 05:00", "Howrah", "Howrah", priority=1, eligible=["A"]),
            duty("LO1", "2026-11-01 00:00", "Howrah", "Howrah", eligible=["A"]),
            duty("LO2", "2026-11-01 23:00", "Howrah", "Howrah", eligible=["A"]),
        ],
    )


def test_priority_breaks_ties_after_coverage():
    inst = make_instance(
        [crew("A")],
        [
            duty("HI", "2026-11-01 05:00", "Howrah", "Howrah", priority=1, eligible=["A"]),
            duty("LO", "2026-11-01 06:00", "Howrah", "Howrah", eligible=["A"]),
        ],
    )
    assert pairs(solve(inst)) == {("A", "HI")}


def test_coverage_dominates_priority_by_default_and_order_is_configurable():
    inst = _priority_instance()
    assert pairs(solve(inst, max_duties_per_day=None)) == {("A", "LO1"), ("A", "LO2")}
    r = solve(inst, objective_levels=["priority", "coverage"], max_duties_per_day=None)
    assert ("A", "HI") in pairs(r)


@pytest.mark.parametrize("levels", [["coverage", "priority"], ["priority", "coverage"]])
def test_weighted_mode_matches_lexicographic(levels):
    inst = _priority_instance()
    lex = solve(inst, objective_levels=levels, max_duties_per_day=None)
    w = solve(inst, objective_levels=levels, objective_mode="weighted", max_duties_per_day=None)
    assert pairs(lex) == pairs(w)


def test_time_changes_minimised():
    crews = [
        crew("E17", "Howrah", "EXCESS", rostered="17:00"),
        crew("E18", "Howrah", "EXCESS", rostered="18:00"),
    ]
    inst = make_instance(crews, [duty("D", "2026-11-01 18:00", "Howrah", "Howrah", eligible=["E17", "E18"])])
    r = solve(inst)
    assert pairs(r) == {("E18", "D")}
    assert r.solution.objective_values["time_changes"] == 0


def test_trivial_levels_are_skipped():
    inst = make_instance([crew("A")], [duty("D", "2026-11-01 05:00", eligible=["A"])])
    r = solve(inst)
    assert r.solution.stats["active_objective_levels"] == ["coverage"]
    assert set(r.solution.stats["skipped_objective_levels"]) == {
        "priority",
        "positioning",
        "time_changes",
        "roster_changes",
    }


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_lp_cut_never_changes_the_optimum(seed):
    inst = generate_instance(SyntheticConfig(seed=seed, n_crew=40, n_duties=50, horizon_days=6))
    with_cut = solve(inst, SolverConfig(time_limit_seconds=30, num_workers=2, use_lp_bound=True))
    without = solve(inst, SolverConfig(time_limit_seconds=30, num_workers=2, use_lp_bound=False))
    assert with_cut.solution.stage_statuses["coverage"] == "OPTIMAL"
    assert without.solution.stage_statuses["coverage"] == "OPTIMAL"
    assert with_cut.solution.objective_values["coverage"] == without.solution.objective_values["coverage"]
    assert with_cut.solution.stats["lp_bounds"]["coverage"] >= with_cut.solution.objective_values["coverage"] - 1e-6
    assert with_cut.validation.passed and without.validation.passed
