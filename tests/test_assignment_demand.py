"""Demand, uniqueness, coverage accounting and existing assignments."""

from helpers import covered, crew, duty, make_instance, pairs, solve

from railway_rostering.reporting import uncovered_rows

ABC = [crew("A"), crew("B"), crew("C")]


def test_multi_crew_demand_uses_distinct_crew():
    inst = make_instance(ABC, [duty("D1", "2026-11-01 05:00", eligible=["A", "B", "C"], demand=2)])
    r = solve(inst)
    assert covered(r) == 2
    assert len({c for c, _ in pairs(r)}) == 2


def test_partial_versus_all_or_nothing_demand():
    inst = make_instance(ABC, [duty("D1", "2026-11-01 05:00", eligible=["A"], demand=2)])
    r = solve(inst)
    assert covered(r) == 1
    [row] = uncovered_rows(r)
    assert row["uncovered_units"] == 1 and row["assigned_units"] == 1
    assert row["reason_code"] == "INSUFFICIENT_CANDIDATES"
    r2 = solve(inst, demand_mode="all_or_nothing")
    assert covered(r2) == 0 and pairs(r2) == set()


def test_one_crew_cannot_cover_two_simultaneous_duties():
    duties = [duty("D1", "2026-11-01 05:00", eligible=["A"]), duty("D2", "2026-11-01 05:00", eligible=["A"])]
    r = solve(make_instance([crew("A")], duties))
    assert covered(r) == 1
    [row] = uncovered_rows(r)
    assert row["reason_code"] == "NOT_SELECTED"


def test_existing_assignment_is_kept_and_counted_separately():
    inst = make_instance(ABC, [duty("D1", "2026-11-01 05:00", eligible=["A", "B"], demand=2, assigned_crew=("A",))])
    r = solve(inst)
    assert pairs(r) == {("A", "D1"), ("B", "D1")}
    assert covered(r) == 1  # only the new unit counts
    assert [a.existing for a in r.solution.assignments if a.crew_id == "A"] == [True]


def test_fixed_existing_assignment_blocks_conflicting_duty():
    duties = [
        duty("D1", "2026-11-01 05:00", "Howrah", "Howrah", eligible=["A", "B"], assigned_crew=("A",)),
        duty("D2", "2026-11-01 06:00", "Howrah", "Howrah", eligible=["A"]),
    ]
    r = solve(make_instance(ABC, duties), max_duties_per_day=None)
    assert covered(r) == 0 and ("A", "D1") in pairs(r)
    # Reassignable mode: B takes D1, freeing A for D2 (one roster change).
    r2 = solve(make_instance(ABC, duties), max_duties_per_day=None, existing_assignment_mode="reassignable")
    assert covered(r2) == 1
    assert pairs(r2) == {("B", "D1"), ("A", "D2")}
    assert r2.solution.objective_values["roster_changes"] == 1
    assert r2.validation.passed


def test_reassignable_mode_minimises_changes():
    duties = [duty("D1", "2026-11-01 05:00", eligible=["A", "B"], assigned_crew=("A",))]
    r = solve(make_instance(ABC, duties), existing_assignment_mode="reassignable")
    assert pairs(r) == {("A", "D1")}
    assert r.solution.objective_values["roster_changes"] == 0


def test_inconsistent_existing_roster_reports_infeasible():
    # Existing duty for A starts in Yajpur but A is in Howrah with no way to get there.
    duties = [duty("D1", "2026-11-01 05:00", "Yajpur", "Howrah", eligible=["A"], assigned_crew=("A",))]
    r = solve(make_instance([crew("A", "Howrah")], duties))
    assert r.solution.status == "INFEASIBLE"
    assert r.candidates.issues and "cannot be part of any legal sequence" in r.candidates.issues[0]
