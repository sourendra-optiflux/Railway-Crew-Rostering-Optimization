"""The gap-filling pipeline: gap_generation -> option_generation -> CP-SAT (gap_filling_rules.md)."""

import csv
import importlib.util
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "optiflux_v2"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CP-SAT"))


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("pipeline")
    gaps, opts, final = out / "gaps", out / "options", out / "final"
    _module(ROOT / "gap_generation" / "make_gaps.py", "make_gaps").main(["--output-dir", str(gaps)])
    gen = _module(ROOT / "option_generation" / "generate_options.py", "generate_options")
    gen.main(["--roster-full", str(gaps / "roster_full.csv"), "--output-dir", str(opts)])
    cp = _module(ROOT / "CP-SAT" / "run_gap_filling.py", "run_gap_filling")
    code = cp.main(["--roster-full", str(gaps / "roster_full.csv"), "--options-dir", str(opts),
                    "--output-dir", str(final), "--time-limit", "120", "--workers", "8"])  # fmt: skip
    return {"gaps": gaps, "options": opts, "final": final, "code": code}


# ---- base data (R1, R4, R5) -------------------------------------------------------------------------------


def test_off_rows_only_on_off_blocks():
    roster = _rows(DATA / "roster_df.csv")
    offs = [r for r in roster if r["Assignment Type"] == "Off"]
    assert offs and all(r["Activity Name"] == "Off" and r["Activity Head"] == "RR" for r in offs)
    # U100001 (Residential, 6/6): 6 shifts, then 6 Off days, then the next swing.
    mine = [r for r in roster if r["User Id"] == "U100001" and r["In Horizon"] == "Yes"]
    kinds = "".join("O" if r["Assignment Type"] == "Off" else "W" for r in mine[:18])
    assert kinds == "WWWWWWOOOOOOWWWWWW"


def test_nothing_is_locked():
    assert {r["Is Locked"] for r in _rows(DATA / "roster_df.csv")} == {"False"}


def test_eligibility_matrix_matches_the_roster():
    eligible = {m["Activity ID"]: set(m["Eligible User Ids"].split(";")) for m in _rows(DATA / "eligibility_matrix.csv")}
    for r in _rows(DATA / "roster_df.csv"):
        if r["Assignment Type"] in ("Demand", "Excess"):
            assert r["User Id"] in eligible[r["Activity ID"]], r["Assignment ID"]


# ---- layer 0: gap generation (G1-G4) -----------------------------------------------------------------------


def test_leave_mix_and_columns(run):
    plan = _rows(run["gaps"] / "leave_plan.csv")
    assert Counter(p["Leave Type"] for p in plan) == {"Full Swing": 35, "Day Shifts": 14, "Night Shifts": 21, "Random": 35}
    assert len({p["User Id"] for p in plan}) == 105  # 15% of 700, one leave each
    header = next(csv.reader((run["gaps"] / "roster_full.csv").open()))
    assert header[1:4] == ["User Id", "New User Id", "Optimised User Id"]
    rows = _rows(run["gaps"] / "roster_full.csv")
    assert all(r["Optimised User Id"] == "" for r in rows)  # G4: empty until CP-SAT has run
    for r in rows:
        if r["Leave Type"]:
            assert r["New User Id"] == ""
        if r["Is Gap"] == "True":
            assert r["Is_locked_gap"] == str(date.fromisoformat(r["Start Date"]) < date(2026, 11, 6))
    days = {p["Leave Type"]: p for p in plan}
    assert days["Day Shifts"]["Shifts On Leave"] == days["Night Shifts"]["Shifts On Leave"] == "3"


# ---- layer 1: option generation (F1, F4) -------------------------------------------------------------------


def test_options_respect_the_rules(run):
    swings = {s["Swing Key"]: s for s in _rows(run["options"] / "swings.csv")}
    eligible = {m["Activity ID"]: set(m["Eligible User Ids"].split(";")) for m in _rows(DATA / "eligibility_matrix.csv")}
    fills = [o for o in _rows(run["options"] / "options.csv") if o["Kind"] == "fill"]
    assert fills
    for o in fills:
        assert datetime.fromisoformat(o["Start"]).date() >= date(2026, 11, 6)
        assert o["User Id"] in eligible[o["Activity ID"]]
        if o["Row Type"] == "Demand":
            assert int(o["Offset Minutes"]) in (-60, 0, 60)
        if swings[o["Swing Key"]]["Status"] == "frozen":  # F4: only an Excess person on the very same seat
            assert o["Row Type"] == "Excess" and o["Offset Minutes"] == "0"


# ---- layer 2: CP-SAT ---------------------------------------------------------------------------------------


def test_cp_sat_fills_gaps_without_breaking_rules(run):
    assert run["code"] == 0  # 0 = no unexpected rule failure (validation.md)
    rows = _rows(run["final"] / "roster_full.csv")
    to_fill = [r for r in rows if r["Is Gap"] == "True" and r["Is_locked_gap"] == "False"]
    filled = [r for r in to_fill if r["Optimised User Id"]]
    assert len(filled) >= 0.8 * len(to_fill)
    assert all(not r["Optimised User Id"] for r in rows if r["Is_locked_gap"] == "True")
    early = [r for r in rows if r["Start Date"] < "2026-11-06" and r["Optimised User Id"] != r["New User Id"]]
    assert not early
