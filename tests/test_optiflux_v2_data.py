"""Checks on data/optiflux_v2: the committed tables follow the rules and match the scripts that build them."""

import csv
import importlib.util
import shutil
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "optiflux_v2"
GENERATED = [
    # scripts/build_optiflux_v2_data.py
    "activities_df.csv", "activity_demand_df.csv", "activity_priority.csv", "assignment_type_priority.csv",
    "compliance_matrix_df.csv", "excluded_activities.csv", "constraints_df.csv", "crew_restrictions.csv",
    "Crew_Onsite_App.csv",
    # scripts/roster_making.py
    "roster_df.csv", "crew_master_data_df.csv", "crew_competencies_df.csv", "crew_currency_df.csv",
    "roster_lines.csv", "roster_report.md", "eligibility_matrix.csv",
    # scripts/check_roster.py --write-report
    "roster_checks.md",
]  # fmt: skip


def _rows(name, folder=DATA):
    with (folder / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look the module up by name
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory):
    """Run the whole pipeline from source/ into a fresh folder."""
    out = tmp_path_factory.mktemp("optiflux_v2")
    shutil.copytree(DATA / "source", out / "source")
    _script("build_optiflux_v2_data").main(["--data-dir", str(out)])
    _script("roster_making").main(["--data-dir", str(out)])
    assert _script("check_roster").main(["--data-dir", str(out), "--write-report"]) == 0
    return out


@pytest.mark.parametrize("name", GENERATED)
def test_committed_files_match_the_scripts(rebuilt, name):
    assert (rebuilt / name).read_text() == (DATA / name).read_text(), f"{name} is stale: rerun the v2 scripts"


def test_every_rule_check_passes_on_committed_data():
    ck = _script("check_roster").run(DATA)
    failed = [(rule, text, detail) for rule, text, ok, detail in ck.results if not ok]
    assert not failed
    assert len(ck.results) >= 30


def test_activity_ids_unique_and_renamed():
    acts = _rows("activities_df.csv")
    ids = [a["Activity ID"] for a in acts]
    assert len(ids) == len(set(ids))
    names = {a["Activity Name"] for a in acts}
    assert {"NE Crew", "BY Ship", "Relief", "Travel In", "Travel Out"} <= names
    assert not {"NE Task", "BY Shed"} & names
    relief = next(a for a in acts if a["Activity ID"] == "A90")
    assert relief["Activity Name"] == relief["Activity Head"] == "Relief"


def test_demand_rules():
    demand = _rows("activity_demand_df.csv")

    def starts(name):
        return {d["Shift"]: int(d["Demand"]) for d in demand if d["Activity Name"] == name}

    for name in ("Haskett Mainline", "Yarmouth Mainline", "Madison Crew", "Nelaway Driver"):
        assert starts(name) == {f"{h:02d}:00": 1 for h in range(24)}
    assert starts("CAM LOT") == {f"{h:02d}:00": 1 for h in range(0, 24, 3)}
    assert starts("Madison Yard") == starts("Nelaway Shuttle Driver") == {f"{h:02d}:00": 1 for h in range(1, 24, 3)}
    assert starts("Bethway Join/FI Crew") == {f"{h:02d}:00": 1 for h in (1, 4, 7, 10, 13, 16, 19, 22)}
    assert starts("Work Train") == {"22:00": 2}
    assert starts("Fuel Train") == starts("Fuel Return") == {"10:00": 1}
    assert starts("NE Ship") == starts("BY Ship") == {"04:00": 1, "09:00": 1, "16:00": 1, "21:00": 1}
    assert starts("NE Crew") == {**{f"{h:02d}:00": 4 for h in (4, 7, 9, 16, 19, 21)}, "00:00": 2, "12:00": 2}
    assert sum(int(d["Demand"]) for d in demand) == 171


def test_per_person_tables_use_user_id_not_cm_id():
    for name in (
        "crew_master_data_df",
        "crew_competencies_df",
        "crew_currency_df",
        "crew_restrictions",
        "Crew_Onsite_App",
    ):
        header = (DATA / f"{name}.csv").read_text().splitlines()[0].split(",")
        assert "User Id" in header and "CM Id" not in header, name


@pytest.mark.parametrize(
    "depot, classification, n",
    [("Haskett", "Residential", 210), ("Haskett", "FIFO", 70), ("Yarmouth", "FIFO", 210),
     ("Nelaway", "Residential", 140), ("Nelaway", "FIFO", 70)],  # gap_filling_rules.md R2: 700 crew
)  # fmt: skip
def test_crew_counts(depot, classification, n):
    crew = _rows("crew_master_data_df.csv")
    assert len(crew) == len({c["User Id"] for c in crew}) == 700
    assert Counter((c["Depot"], c["Classification"]) for c in crew)[(depot, classification)] == n


def test_priority_one_pattern_day_and_night_partners():
    """U100001 and U100002 are on the same priority-1 job on day 1: one on the day start, one on the night start."""
    roster = [r for r in _rows("roster_df.csv") if r["Start Date"] == "2026-11-01"]
    first = {r["User Id"]: r for r in roster if r["User Id"] in ("U100001", "U100002")}
    assert first["U100001"]["Activity Name"] == first["U100002"]["Activity Name"] == "Madison Crew"
    assert first["U100001"]["Shift Start Time"] == "03:00"
    assert first["U100002"]["Shift Start Time"] == "15:00"
