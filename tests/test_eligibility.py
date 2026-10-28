"""Eligibility by activity table and per-duty lists."""

from helpers import covered, crew, duty, make_instance, pairs, solve


def test_activity_qualification_is_exact():
    # Eligible for Howrah Mainline does NOT imply Howrah Mainline CO.
    inst = make_instance(
        [crew("A")],
        [duty("D1", "2026-11-01 05:00", "Howrah", "Howrah", "Howrah Mainline CO")],
        quals={"A": {"Howrah Mainline"}},
    )
    r = solve(inst)
    assert covered(r) == 0
    assert r.candidates.diagnostics["D1"].structural_reason() == "NO_ELIGIBLE_CREW"


def test_table_and_list_must_both_allow():
    duties = [duty("D1", "2026-11-01 05:00", eligible=["B"])]
    inst = make_instance([crew("A"), crew("B")], duties, quals={"A": {"Howrah Mainline"}, "B": {"Howrah Mainline"}})
    assert pairs(solve(inst)) == {("B", "D1")}
    inst2 = make_instance([crew("A"), crew("B")], duties, quals={"A": {"Howrah Mainline"}})
    assert covered(solve(inst2)) == 0


def test_briefing_shrinath_sourendra_example():
    crews = [crew("Shrinath", "Howrah"), crew("Sourendra", "Howrah")]
    quals = {"Shrinath": {"Howrah Mainline", "Nellore Driver"}, "Sourendra": {"Nellore Driver"}}
    inst = make_instance(crews, [duty("HM", "2026-11-01 05:00", "Howrah", "Yajpur", "Howrah Mainline")], quals=quals)
    assert pairs(solve(inst)) == {("Shrinath", "HM")}


def test_ineligible_crew_never_assigned_even_if_only_option():
    inst = make_instance([crew("A")], [duty("D1", "2026-11-01 05:00", eligible=[])])
    assert covered(solve(inst)) == 0
