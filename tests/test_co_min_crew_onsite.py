"""CO reverse-lane pairing (soft), on-site crew dataframe, minimum crew per activity head."""

import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CP-SAT"))

from solver import solve  # noqa: E402

from option_generation.co_pairs import reverse_co_pairs  # noqa: E402
from option_generation.data import DEFAULT_DATA_DIR, read_csv  # noqa: E402
from option_generation.min_crew import default_min_crew, load_min_crew, total_daily_demand  # noqa: E402
from option_generation.onsite import below_minimum, onsite_crew_df, relief_heads_by_user  # noqa: E402
from option_generation.options import Costs, Option  # noqa: E402
from option_generation.rules import Rules  # noqa: E402

START = datetime(2026, 11, 6, 17)


# --- CO reverse-lane pairing ------------------------------------------------------------------------------


def test_reverse_co_pairs_from_project_data():
    activities = {a["Activity ID"]: a for a in read_csv(DEFAULT_DATA_DIR / "activities_df.csv")}

    assert reverse_co_pairs(activities) == [("A02", "A04")]  # Haskett Mainline CO <-> Yarmouth Mainline CO


def test_reverse_co_pairs_keeps_every_head_sharing_a_lane():
    def act(head, typ, a, b):
        return {"Activity Head": head, "Activity Type": typ, "Start Depot": a, "End Depot": b}

    shared = {
        "M1": act("Main", "Driving", "X", "Y"), "C1": act("Main", "Crew On", "X", "X"),
        "M2": act("Work", "Driving", "X", "Y"), "C2": act("Work", "Crew On", "X", "X"),
        "M3": act("Back", "Driving", "Y", "X"), "C3": act("Back", "Crew On", "Y", "Y"),
    }  # fmt: skip
    assert reverse_co_pairs(shared) == [("C1", "C3"), ("C2", "C3")]


def test_reverse_co_pairs_ignores_lane_without_reverse():
    def act(head, typ, a, b):
        return {"Activity Head": head, "Activity Type": typ, "Start Depot": a, "End Depot": b}

    one_way = {
        "M1": act("Up", "Driving", "X", "Y"), "C1": act("Up", "Crew On", "X", "X"),
        "M2": act("Side", "Driving", "X", "Z"), "C2": act("Side", "Crew On", "X", "X"),
    }  # fmt: skip
    assert reverse_co_pairs(one_way) == []


def _rules(penalty: int) -> Rules:
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"))
    return replace(rules, co_pairing_penalty=penalty)


def _seat(key: str, fixed: int = 0) -> SimpleNamespace:
    return SimpleNamespace(key=key, activity_id=key, start=START, demand=1, fixed=fixed,
                           capacity=max(0, 1 - fixed), priority=1)  # fmt: skip


def _swing(user: str, options: list[Option]) -> SimpleNamespace:
    return SimpleNamespace(key=f"{user}|1", user=user, home="A", classification="FIFO", earliest_start=None,
                           latest_end=None, row_ids=["R"], droppable=[False], options=[options])  # fmt: skip


def _fill(seat: str, cost: int) -> Option:
    return Option(0, "fill", START, START + timedelta(hours=12), "A", "A", seat, seat=seat, cost=cost)


def _solve(penalty: int, seats: dict, swings: list):
    return solve(_rules(penalty), seats, swings, Costs(), 5, 1, 0, co_pairs=[("A", "B")])


def test_pairing_penalty_brings_the_two_cos_together():
    # U1 can cover CO "A" (cost 10) or the plain seat "Y" (cost 0); U3 can only cover CO "B".
    # Both choices cover 2 seats. Cheapest alone: U1 on Y, which leaves B unmatched.
    seats = {"A": _seat("A"), "B": _seat("B"), "Y": _seat("Y")}
    u1, u3 = _fill("A", 10), _fill("Y", 0)
    swings = [_swing("U1", [u1, u3]), _swing("U3", [_fill("B", 0)])]

    unpenalised = _solve(0, seats, swings)
    penalised = _solve(50, seats, swings)

    assert unpenalised.chosen["U1|1"][0].seat == "Y"
    assert unpenalised.co_violations is None  # penalty 0 switches the pairing off
    assert penalised.chosen["U1|1"][0].seat == "A"
    assert penalised.co_violations == 0


def test_pairing_is_soft_so_an_unavoidable_mismatch_is_allowed_and_reported():
    seats = {"A": _seat("A"), "B": _seat("B")}  # nobody can cover B
    result = _solve(50, seats, [_swing("U1", [_fill("A", 10)])])

    assert result.places_filled == 1  # coverage is never traded for pairing
    assert result.co_violations == 1


def test_pairing_counts_occupants_outside_the_model():
    # B is already staffed by someone outside the model (fixed=1). Covering A is the pairing.
    seats = {"A": _seat("A"), "B": _seat("B", fixed=1), "Y": _seat("Y")}
    result = _solve(50, seats, [_swing("U1", [_fill("A", 10), _fill("Y", 0)])])

    assert result.chosen["U1|1"][0].seat == "A"
    assert result.co_violations == 0


def test_a_penalty_below_the_cost_gap_does_not_force_the_pair():
    seats = {"A": _seat("A"), "B": _seat("B"), "Y": _seat("Y")}
    swings = [_swing("U1", [_fill("A", 10), _fill("Y", 0)]), _swing("U3", [_fill("B", 0)])]

    result = _solve(5, seats, swings)  # 5 < the 10 it costs to put U1 on A

    assert result.chosen["U1|1"][0].seat == "Y"
    assert result.co_violations == 1


@pytest.mark.parametrize("value", ["-1", "1.5", "true", "many"])
def test_co_pairing_penalty_config_rejects_bad_values(tmp_path: Path, value: str):
    config = tmp_path / "config.yml"
    config.write_text(f"constraints: {{}}\noptimization:\n  co_pairing_penalty: {value}\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="co_pairing_penalty"):
        Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"), config)


def test_co_pairing_penalty_is_configurable(tmp_path: Path):
    config = tmp_path / "config.yml"
    config.write_text("constraints: {}\noptimization:\n  co_pairing_penalty: 7\n", encoding="utf-8")

    assert Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"), config).co_pairing_penalty == 7
    assert _rules(0).co_pairing_penalty == 0


# --- minimum crew -----------------------------------------------------------------------------------------


def _demand_file(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "activity_demand_df.csv"
    path.write_text("Activity Head,Demand,Is Active\n" + rows, encoding="utf-8")
    return path


def test_min_crew_defaults_to_half_the_daily_demand_rounded_up(tmp_path: Path):
    demand = _demand_file(tmp_path, "Main,10,Yes\nMain,5,Yes\nMain,99,No\nShed,4,Yes\nSolo,1,Yes\n")
    priority = tmp_path / "activity_priority.csv"
    priority.write_text("Activity Head,Priority\nMain,1\nShed,2\nSolo,3\n", encoding="utf-8")

    assert total_daily_demand(demand) == {"Main": 15, "Shed": 4, "Solo": 1}
    assert load_min_crew(demand, priority) == {"Main": 8, "Shed": 2, "Solo": 1}
    assert default_min_crew(25) == 13


def test_min_crew_column_overrides_the_default_when_filled(tmp_path: Path):
    demand = _demand_file(tmp_path, "Main,10,Yes\nShed,4,Yes\n")
    priority = tmp_path / "activity_priority.csv"
    priority.write_text("Activity Head,Priority,Min Crew\nMain,1,3\nShed,2,\n", encoding="utf-8")

    assert load_min_crew(demand, priority) == {"Main": 3, "Shed": 2}


def test_min_crew_override_must_be_a_non_negative_integer(tmp_path: Path):
    demand = _demand_file(tmp_path, "Main,10,Yes\n")
    priority = tmp_path / "activity_priority.csv"
    priority.write_text("Activity Head,Priority,Min Crew\nMain,1,-2\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Min Crew"):
        load_min_crew(demand, priority)


def test_min_crew_covers_every_project_demand_head():
    minimum = load_min_crew(DEFAULT_DATA_DIR / "activity_demand_df.csv")

    assert len(minimum) == 14
    assert minimum["Haskett Mainline"] == 13  # 25 per day (24 mainline + 1 CO) -> ceil(12.5)


# --- on-site crew -----------------------------------------------------------------------------------------


def _row(user: str, start: str, site: str = "Haskett", head: str = "Main", kind: str = "Demand") -> dict:
    day, time = start.split(" ")
    return {"New User Id": user, "Start Date": day, "Shift Start Time": time, "Start Location": site,
            "Activity Head": head, "Assignment Type": kind}  # fmt: skip


def _starts(hours: list[int]) -> dict[str, list[datetime]]:
    return {"Main": [datetime(2026, 11, 6, h) for h in hours]}


def test_crew_starting_at_11_is_available_until_23_exclusive():
    roster = [_row("U1", "2026-11-06 11:00")]

    df = onsite_crew_df(roster, _starts([10, 11, 22, 23]), shift_hours=12)

    got = dict(zip(df["Start Datetime"].dt.hour, df["Crew Available"]))
    assert got == {10: 0, 11: 1, 22: 1, 23: 0}


def test_onsite_counts_per_site_and_assignment_type():
    roster = [
        _row("U1", "2026-11-06 11:00"), _row("U2", "2026-11-06 06:00", kind="Excess"),
        _row("U3", "2026-11-06 11:00", site="Yarmouth", kind="Relief"),
        _row("U1", "2026-11-06 11:00"),  # the same person twice is one person
        _row("", "2026-11-06 11:00"),  # leave row: nobody
    ]  # fmt: skip

    df = onsite_crew_df(roster, _starts([12]), shift_hours=12, min_crew={"Main": 2})
    by_site = df.set_index("Site")

    assert by_site.loc["Haskett", ["Demand Crew", "Excess Crew", "Relief Crew", "Crew Available"]].tolist() == [1, 1, 0, 2]
    assert by_site.loc["Yarmouth", ["Demand Crew", "Excess Crew", "Relief Crew", "Crew Available"]].tolist() == [0, 0, 1, 1]
    assert (df["Min Crew"] == 2).all()


def test_onsite_uses_the_chosen_person_column():
    roster = [{**_row("U1", "2026-11-06 11:00"), "Optimised User Id": ""}]

    after = onsite_crew_df(roster, _starts([12]), 12, person_column="Optimised User Id")
    before = onsite_crew_df(roster, _starts([12]), 12)

    assert after.empty or after["Crew Available"].sum() == 0
    assert before["Crew Available"].sum() == 1


def test_below_minimum_sums_the_sites_of_a_head():
    roster = [_row("U1", "2026-11-06 11:00"), _row("U2", "2026-11-06 11:00", site="Yarmouth")]
    df = onsite_crew_df(roster, _starts([12, 23]), 12, min_crew={"Main": 2})

    short = below_minimum(df)

    assert short["Start Datetime"].dt.hour.tolist() == [23]  # 2 people at 12:00 meet the minimum, 0 at 23:00
    assert short["Shortfall"].tolist() == [2]


def test_standby_relief_crew_counts_under_the_heads_they_are_eligible_for():
    roster = [_row("U1", "2026-11-06 11:00", head="Relief", kind="Relief"),
              _row("U2", "2026-11-06 11:00", head="Relief", kind="Relief")]  # fmt: skip
    eligible = {"A1": {"U1"}, "A2": {"U1", "U2"}}
    activities = {"A1": {"Activity Head": "Main"}, "A2": {"Activity Head": "Shed"}}
    starts = {"Main": [datetime(2026, 11, 6, 12)], "Shed": [datetime(2026, 11, 6, 12)]}

    df = onsite_crew_df(roster, starts, 12, relief_heads=relief_heads_by_user(eligible, activities))
    got = df.set_index("Activity Head")["Relief Crew"].to_dict()

    assert got == {"Main": 1, "Shed": 2}
