"""OptiFlux DB schema -> Instance conversion: one test per business rule.

Every test starts from the hand-checkable ``data/sample/briefing_abc`` tables
(Relief crew ABC plus permanent crew P01-P06 staffing every other slot) and
changes one table.
"""

import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from helpers import solve

from railway_rostering import load_instance
from railway_rostering.cli import main
from railway_rostering.db_schema import (
    DB_TABLES,
    DBDataError,
    build_instance,
    model_config_from_constraints,
    read_tables,
    write_tables,
)

ROOT = Path(__file__).resolve().parents[1]
ABC_DIR = ROOT / "data/sample/briefing_abc"
TABLES = read_tables(ABC_DIR)
GAPS = ["DM02-20261101", "DM04-20261102", "DM06-20261103", "DM01-20261105", "DM03-20261106", "DM05-20261107"]


def tables():
    return copy.deepcopy(TABLES)


def build(t):
    return build_instance(t, "abc_test")


def prep(inst):
    return inst.metadata["data_preparation"]


def set_constraint(t, name, value="", status="Active"):
    rows = [r for r in t["constraints_df"] if r["Constraint"] != name]
    rows.append({"Constraint": name, "Value": value, "Status": status})
    t["constraints_df"] = rows


def activity(t, aid):
    return next(r for r in t["activities_df"] if r["Activity ID"] == aid)


def test_sample_counts():
    inst = build(tables())
    p = prep(inst)
    assert p["demand_units_total"] == 42  # 3 activities x 2 shifts x 7 days
    assert p["units_covered_by_regular_crew"] == 36
    assert p["open_demand_units"] == 6 and [d.duty_id for d in inst.duties] == GAPS
    assert p["n_crew_optimised"] == 1 and p["n_crew_regular"] == 6


def test_every_table_has_exact_schema_columns(tmp_path):
    out = write_tables(tables(), tmp_path / "x")
    for name, cols in DB_TABLES.items():
        header = (out / f"{name}.csv").read_text().splitlines()[0]
        assert header == ",".join(cols), name


def test_missing_column_is_reported(tmp_path):
    out = write_tables(tables(), tmp_path / "x")
    p = out / "crew_master_data_df.csv"
    p.write_text(p.read_text().replace("Classification", "Class"))
    with pytest.raises(DBDataError, match="missing columns"):
        read_tables(out)


def test_regular_crew_leave_opens_their_slot():
    t = tables()
    # P01 works Howrah Mainline 05:00-17:00 (slot DM01).
    t["crew_restrictions"].append({"Restriction ID": "R1", "CM Id": "P01", "Restriction Type": "No Duty",
                                   "Activity Head": "", "Effective From": "2026-11-02", "Effective To": "2026-11-03",
                                   "Reason": "Annual Leave"})  # fmt: skip
    inst = build(t)
    ids = {d.duty_id for d in inst.duties}
    assert {"DM01-20261102", "DM01-20261103"} <= ids
    assert prep(inst)["disruptions_by_reason"] == {"UNAVAILABLE": 2}


def test_medically_unfit_regular_crew_loses_every_row():
    t = tables()
    next(r for r in t["crew_master_data_df"] if r["CM Id"] == "P02")["Medical"] = "Unfit"
    p = prep(build(t))
    assert p["disruptions_by_reason"] == {"MEDICAL_UNFIT": 6}  # P02 covered DM02 on 6 of 7 days
    assert p["open_demand_units"] == 12


def test_competency_expiry_is_date_dependent():
    t = tables()
    for r in t["crew_competencies_df"]:
        if r["CM Id"] == "ABC" and r["Competency LMS Code"] == "RK-HY":
            r["Expiry Date"] = "2026-11-04"
    inst = build(t)
    elig = {d.duty_id: d.eligible_crew for d in inst.duties}
    # DM06-20261103 ends on 4 Nov (still valid), later duties are not.
    assert elig["DM06-20261103"] == {"ABC"} and elig["DM01-20261105"] == frozenset()


def test_suspended_competency_blocks_eligibility():
    t = tables()
    for r in t["crew_competencies_df"]:
        if r["CM Id"] == "ABC" and r["Competency LMS Code"] == "SAFE-01":
            r["status"] = "Suspended"
    assert all(not d.eligible_crew for d in build(t).duties)


def test_currency_threshold():
    t = tables()
    activity(t, "A01")["Currency Threshold"] = "30"  # Howrah Mainline
    inst = build(t)
    assert inst.duty("DM02-20261101").eligible_crew == frozenset()  # no currency record
    assert inst.duty("DM04-20261102").eligible_crew == {"ABC"}  # Yajpur Mainline: no threshold
    t["crew_currency_df"].append({"Currency ID": "CU1", "CM Id": "ABC", "Activity Head": "Howrah Mainline",
                                  "Last Performed Date": "2026-10-05", "Last CRT Activity ID": "CRT-0001"})  # fmt: skip
    inst = build(t)
    assert inst.duty("DM02-20261101").eligible_crew == {"ABC"}  # 27 days ago
    assert inst.duty("DM01-20261105").eligible_crew == frozenset()  # 31 days ago: lapsed


def test_role_and_mentor_rules():
    t = tables()
    activity(t, "A02")["Roles/Job"] = "Conductor"
    activity(t, "A03")["Mentor Required"] = "Yes"
    inst = build(t)
    assert inst.duty("DM04-20261102").eligible_crew == frozenset()  # ABC is a Driver
    assert inst.duty("DM06-20261103").eligible_crew == {"ABC"}  # not a trainee
    next(r for r in t["crew_master_data_df"] if r["CM Id"] == "ABC")["Mentor Id"] = "P01"
    assert build(t).duty("DM06-20261103").eligible_crew == frozenset()


def test_night_and_activity_restrictions():
    t = tables()
    t["crew_restrictions"] += [
        {"Restriction ID": "R1", "CM Id": "ABC", "Restriction Type": "No Night Shift", "Activity Head": "",
         "Effective From": "2026-11-01", "Effective To": "2026-11-02", "Reason": "Fatigue"},
        {"Restriction ID": "R2", "CM Id": "ABC", "Restriction Type": "Activity Restriction",
         "Activity Head": "Yajpur Mainline", "Effective From": "2026-11-06", "Effective To": "", "Reason": "Review"},
    ]  # fmt: skip
    elig = {d.duty_id: bool(d.eligible_crew) for d in build(t).duties}
    assert elig == {"DM02-20261101": False, "DM04-20261102": False, "DM06-20261103": True,
                    "DM01-20261105": True, "DM03-20261106": False, "DM05-20261107": True}  # fmt: skip


def test_excluded_and_inactive_demand():
    t = tables()
    t["excluded_activities"].append({"Activity ID": "A02", "Activity Name": "Yajpur Mainline"})
    next(r for r in t["activity_demand_df"] if r["Demand ID"] == "DM05")["Is Active"] = "No"
    inst = build(t)
    assert [d.duty_id for d in inst.duties] == ["DM02-20261101", "DM06-20261103", "DM01-20261105"]
    assert prep(inst)["demand_rows_excluded"] == 2 and prep(inst)["demand_rows_inactive"] == 1


def _abc_row(start, end, crt, name, locked):
    return {"Assignment ID": "AS9999", "User Id": "U-ABC", "Start Date": start[:10], "End Date": end[:10],
            "Shift Start Time": start[11:], "Shift End Time": end[11:], "CRT Activity ID": crt, "Activity Name": name,
            "Is Locked": locked, "Activity Head": "Howrah Mainline", "Activity Type": "Driving",
            "Activity Group": "Mainline"}  # fmt: skip


def test_locked_relief_assignment_is_fixed_and_unlocked_is_released():
    t = tables()
    t["roster_df"].append(_abc_row("2026-11-01 17:00", "2026-11-02 05:00", "CRT-0001", "Howrah Mainline", "Yes"))
    inst = build(t)
    d = inst.duty("DM02-20261101")
    assert d.assigned_crew == ("ABC",) and d.open_demand == 0
    r = solve(inst)
    assert r.validation.passed and r.solution.routes["ABC"] == GAPS

    t["roster_df"][-1]["Is Locked"] = "No"
    inst = build(t)
    assert inst.duty("DM02-20261101").assigned_crew == () and prep(inst)["released_unlocked_assignments"] == 1

    activity(t, "A01")["Can Be Moved"] = "No"  # an unmovable activity keeps the crew even if unlocked
    assert build(t).duty("DM02-20261101").assigned_crew == ("ABC",)


def test_prior_duty_sets_location_rest_and_time_change():
    t = tables()
    # ABC worked Howrah Mainline the night before at 16:00 (a change from 17:00) and is now in Yajpur.
    t["roster_df"].append(_abc_row("2026-10-31 16:00", "2026-11-01 04:00", "CRT-0001", "Howrah Mainline", "Yes"))
    t["roster_df"].append({**t["roster_df"][-1], "Assignment ID": "AS9998", "Activity Type": "Standby",
                           "CRT Activity ID": "CRT-9001", "Activity Name": "Relief Standby", "Activity Head": "Relief",
                           "Start Date": "2026-10-31", "End Date": "2026-11-01", "Shift Start Time": "17:00",
                           "Shift End Time": "05:00"})  # fmt: skip
    t["Crew_Onsite_App"] = []
    abc = build(t).crews["ABC"]
    assert abc.prior_duty_end == datetime(2026, 11, 1, 4, 0) and abc.initial_location == "Yajpur"
    assert abc.current_start.strftime("%H:%M") == "16:00" and abc.swing_start == date(2026, 10, 31)


def test_onsite_app_location_and_absence():
    t = tables()
    t["Crew_Onsite_App"] = [
        {"Record ID": "1", "CM Id": "ABC", "Date": "2026-11-01", "Location": "Yajpur", "Status": "Away"},
        {"Record ID": "2", "CM Id": "ABC", "Date": "2026-11-06", "Location": "Howrah", "Status": "Absent"},
    ]
    abc = build(t).crews["ABC"]
    assert abc.initial_location == "Yajpur" and date(2026, 11, 6) in abc.unavailable_dates


def test_standby_days_define_working_days():
    t = tables()
    t["roster_df"] = [r for r in t["roster_df"] if not (r["User Id"] == "U-ABC" and r["Start Date"] == "2026-11-03")]
    abc = build(t).crews["ABC"]
    assert abc.swing_start == date(2026, 11, 1) and abc.work_days == 2 and abc.off_days == 1
    assert date(2026, 11, 3) in abc.unavailable_dates
    r = solve(build(t))
    assert "DM06-20261103" not in r.solution.routes.get("ABC", [])


def test_priority_from_activity_priority_table():
    t = tables()
    t["activity_priority"] = [{"Priority": "1", "Activity Head": "Yajpur Mainline"},
                              {"Priority": "2", "Activity Head": "Howrah Mainline"}]  # fmt: skip
    inst = build(t)
    cfg = inst.metadata["model_config"]
    assert cfg["priority_weights"] == {"1": 2, "2": 1} and cfg["default_priority_weight"] == 0
    assert inst.duty("DM04-20261102").priority == 1 and inst.duty("DM02-20261101").priority == 2


def test_constraints_table_maps_to_model_config():
    t = tables()
    set_constraint(t, "Transition Rest Hours", "23", "Inactive")
    set_constraint(t, "Max Duties Per Day", "1", "Inactive")
    set_constraint(t, "Excess Allowed Start Offsets", "-30;30")
    set_constraint(t, "Ordinary Rest Hours", "12")
    set_constraint(t, "Something New", "1")
    cfg = build(t).metadata["model_config"]
    assert cfg["transition_rest_enabled"] is False and cfg["max_duties_per_day"] is None
    assert cfg["allowed_offsets_minutes"]["EXCESS"] == [-30, 0, 30] and cfg["ordinary_rest_hours"] == 12
    assert any("Something New" in w for w in prep(build(t))["constraint_warnings"])
    mc = model_config_from_constraints(t["constraints_df"])
    assert mc.ordinary_rest_hours == 12


@pytest.mark.parametrize(
    "name,value,status,msg",
    [("Planning Horizon Days", "", "Inactive", "Planning Horizon"), ("Positioning", "", "Active", "travel"),
     ("Demand Mode", "sometimes", "Active", "demand_mode")],
)  # fmt: skip
def test_bad_constraints_are_errors(name, value, status, msg):
    t = tables()
    if name == "Planning Horizon Days":
        t["constraints_df"] = [r for r in t["constraints_df"] if r["Constraint"] != name]
    else:
        set_constraint(t, name, value, status)
    with pytest.raises(DBDataError, match=msg):
        build(t)


def test_constraints_rule_changes_the_solution():
    # ABC's night duty ends 4 Nov 05:00 and the next day duty starts 5 Nov 05:00: 24 h of rest.
    t = tables()
    assert len(solve(build(t)).solution.routes["ABC"]) == 6
    set_constraint(t, "Transition Rest Hours", "25")
    r = solve(build(t))
    assert len(r.solution.routes["ABC"]) == 5 and r.validation.passed


def test_cli_set_overrides_db_constraints(tmp_path):
    out = tmp_path / "o"
    assert main(["solve", "--instance-dir", str(ABC_DIR), "--output-dir", str(out), "--workers", "1",
                 "--set", "ordinary_rest_hours=12"]) == 0  # fmt: skip
    summary = json.loads((out / "summary.json").read_text())
    assert summary["model_config"]["ordinary_rest_hours"] == 12
    assert summary["model_config"]["priority_weights"] == {"1": 1}  # still from activity_priority
    assert summary["data_preparation"]["open_demand_units"] == 6


def test_load_instance_detects_db_directory():
    inst = load_instance(ABC_DIR)
    assert inst.metadata["data_preparation"]["source_format"] == "optiflux_db_schema"
    assert inst.metadata["expected"]["routes"]["ABC"] == GAPS
