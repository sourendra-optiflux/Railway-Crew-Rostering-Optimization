"""Input files -> CLI -> output files, plus generator and greedy checks."""

import csv
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from helpers import solve

from railway_rostering import ModelConfig
from railway_rostering.candidate_generation import generate_candidates
from railway_rostering.cli import main
from railway_rostering.db_schema import DB_TABLES, write_tables
from railway_rostering.heuristics import greedy_routes
from railway_rostering.mip_crosscheck import solve_flow_mip
from railway_rostering.solution_validation import validate_solution
from railway_rostering.synthetic import SyntheticConfig, generate_instance
from railway_rostering.synthetic_db import DB_PRESETS, DBSyntheticConfig, generate_db_instance, generate_tables

ROOT = Path(__file__).resolve().parents[1]


def read_csv(p):
    with open(p, newline="") as fh:
        return list(csv.DictReader(fh))


def test_cli_solve_writes_all_outputs(tmp_path):
    out = tmp_path / "abc"
    code = main(["solve", "--instance-dir", str(ROOT / "data/sample/briefing_abc"), "--output-dir", str(out),
                 "--time-limit", "10", "--workers", "1"])  # fmt: skip
    assert code == 0
    for name in [
        "assignments.csv",
        "uncovered_duties.csv",
        "crew_routes.csv",
        "summary.json",
        "validation_report.json",
    ]:
        assert (out / name).exists(), name
    rows = read_csv(out / "assignments.csv")
    assert [r["duty_id"] for r in rows] == ["DM02-20261101", "DM04-20261102", "DM06-20261103", "DM01-20261105", "DM03-20261106", "DM05-20261107"]
    assert [r["shift_type"] for r in rows] == ["NIGHT"] * 3 + ["DAY"] * 3
    assert read_csv(out / "uncovered_duties.csv") == []
    summary = json.loads((out / "summary.json").read_text())
    assert summary["status"] == "OPTIMAL" and summary["validation_passed"] is True
    assert summary["coverage"]["covered_units"] == 6
    assert json.loads((out / "validation_report.json").read_text())["passed"] is True


def test_cli_validate_accepts_and_rejects(tmp_path):
    out = tmp_path / "abc"
    inst_dir = str(ROOT / "data/sample/briefing_abc")
    main(["solve", "--instance-dir", inst_dir, "--output-dir", str(out), "--workers", "1"])
    assert main(["validate", "--instance-dir", inst_dir, "--assignments", str(out / "assignments.csv")]) == 0
    bad = tmp_path / "bad.csv"
    bad.write_text("crew_id,duty_id\nABC,DM02-20261101\nABC,DM01-20261105\nABC,DM06-20261103\n")
    # DM01-20261105 (Howrah Mainline) would need ABC in Howrah after DM02-20261101 ends in Yajpur
    assert main(["validate", "--instance-dir", inst_dir, "--assignments", str(bad)]) == 3


def test_cli_with_explicit_legacy_files_and_overrides(tmp_path):
    out = tmp_path / "toy"
    code = main([
        "solve", "--crew", str(ROOT / "tests/fixtures/v1_toy/crew.csv"), "--duties", str(ROOT / "tests/fixtures/v1_toy/duties.csv"),
        "--output-dir", str(out), "--set", "max_duties_per_day=null", "--workers", "1",
    ])  # fmt: skip
    assert code == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["coverage"]["covered_units"] == 5
    assert summary["model_config"]["max_duties_per_day"] is None


def test_cli_reports_uncovered_reasons(tmp_path):
    out = tmp_path / "small"
    main(["solve", "--instance-dir", str(ROOT / "data/generated/small"), "--output-dir", str(out), "--workers", "2"])
    rows = read_csv(out / "uncovered_duties.csv")
    assert rows, "small preset is expected to leave some duties uncovered"
    known = {"NO_ELIGIBLE_CREW", "NO_AVAILABLE_CREW", "NO_TIME_COMPATIBLE_CREW", "NO_FEASIBLE_SEQUENCE",
             "INSUFFICIENT_CANDIDATES", "NOT_SELECTED"}  # fmt: skip
    assert {r["reason_code"] for r in rows} <= known
    summary = json.loads((out / "summary.json").read_text())
    # Every open demand unit is either newly covered or listed as uncovered.
    uncovered = sum(int(r["uncovered_units"]) for r in rows)
    assert summary["coverage"]["covered_units"] + uncovered == summary["instance"]["open_demand_units"]


def test_run_example_script_from_fresh_checkout(tmp_path):
    proc = subprocess.run(
        [sys.executable, "scripts/run_example.py", "--output-dir", str(tmp_path / "ex"), "--workers", "1"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert "Status          : OPTIMAL" in proc.stdout
    assert (tmp_path / "ex" / "summary.json").exists()


def test_db_generator_is_deterministic(tmp_path):
    cfg = DBSyntheticConfig(name="det", seed=5, n_relief_excess=30, existing_fraction=0.1)
    a = write_tables(generate_tables(cfg)[0], tmp_path / "a")
    b = write_tables(generate_tables(cfg)[0], tmp_path / "b")
    for name in DB_TABLES:
        assert (a / f"{name}.csv").read_text() == (b / f"{name}.csv").read_text(), name
    other = write_tables(generate_tables(replace(cfg, seed=6))[0], tmp_path / "c")
    assert (other / "roster_df.csv").read_text() != (a / "roster_df.csv").read_text()


def test_committed_generated_data_matches_generator(tmp_path):
    for name in ["small", "medium"]:
        tables, _ = generate_tables(DB_PRESETS[name])
        fresh = write_tables(tables, tmp_path / name)
        for table in DB_TABLES:
            f = f"{table}.csv"
            assert (fresh / f).read_text() == (ROOT / "data/generated" / name / f).read_text(), f"{name}/{f}"


def test_committed_data_uses_only_db_schema_tables():
    allowed = {f"{t}.csv" for t in DB_TABLES} | {"instance.json"}
    for d in [*(ROOT / "data/generated").iterdir(), *(ROOT / "data/sample").iterdir()]:
        assert {p.name for p in d.iterdir()} == allowed, d


def test_generator_marks_data_as_synthetic():
    inst = generate_db_instance(DB_PRESETS["small"])
    assert inst.metadata["synthetic"] is True and "not OptiFlux operational data" in inst.metadata["disclaimer"]


def test_db_generated_existing_assignments_are_legal():
    inst = generate_db_instance(DBSyntheticConfig(seed=9, n_relief_excess=60, existing_fraction=0.2))
    existing = [(c, d.duty_id) for d in inst.duties for c in d.assigned_crew]
    assert existing
    rep = validate_solution(inst, replace(ModelConfig(), existing_assignment_mode="reassignable"), existing)
    assert rep.passed, rep.to_dict()["violations"][:5]


@pytest.mark.parametrize("seed", [61, 62])
def test_flow_mip_agrees_with_cp_sat_on_db_instances(seed):
    inst = generate_db_instance(DBSyntheticConfig(seed=seed, n_relief_excess=40, demand_scale=2, vacancy_fraction=0.15))
    r = solve(inst)
    mip = solve_flow_mip(r.candidates, "SCIP", 60)
    assert r.solution.stage_statuses["coverage"] == "OPTIMAL" and mip["status"] == "OPTIMAL"
    assert mip["covered_units"] == r.solution.objective_values["coverage"]
    assert r.validation.passed


def test_generated_existing_assignments_are_legal():
    inst = generate_instance(SyntheticConfig(seed=9, n_crew=60, n_duties=80, existing_assignment_fraction=0.2))
    existing = [(c, d.duty_id) for d in inst.duties for c in d.assigned_crew]
    assert existing
    # Reassignable mode re-checks node-level rules (eligibility, off days, times) too.
    rep = validate_solution(inst, ModelConfig(existing_assignment_mode="reassignable"), existing)
    assert rep.passed, rep.to_dict()["violations"][:5]


@pytest.mark.parametrize("seed", [21, 22, 23, 24])
def test_greedy_routes_are_legal(seed):
    inst = generate_instance(SyntheticConfig(seed=seed, n_crew=50, n_duties=70, existing_assignment_fraction=0.1))
    cfg = ModelConfig()
    routes = greedy_routes(generate_candidates(inst, cfg))
    rep = validate_solution(inst, cfg, [(c, d) for c, r in routes.items() for d in r])
    assert rep.passed, rep.to_dict()["violations"][:5]


@pytest.mark.parametrize("seed", [31, 32, 33])
def test_flow_mip_agrees_with_cp_sat(seed):
    inst = generate_instance(SyntheticConfig(seed=seed, n_crew=60, n_duties=80, existing_assignment_fraction=0.05))
    r = solve(inst)
    mip = solve_flow_mip(r.candidates, "SCIP", 60)
    assert r.solution.stage_statuses["coverage"] == "OPTIMAL" and mip["status"] == "OPTIMAL"
    assert mip["covered_units"] == r.solution.objective_values["coverage"]
    rep = validate_solution(inst, ModelConfig(), mip["assignments"])
    assert rep.passed and rep.coverage["covered_units"] == mip["covered_units"]


def test_greedy_fallback_when_cp_sat_finds_nothing(monkeypatch):
    from ortools.sat.python import cp_model

    inst = generate_instance(SyntheticConfig(seed=41, n_crew=40, n_duties=50))
    monkeypatch.setattr(cp_model.CpSolver, "solve", lambda self, model, *a, **k: cp_model.UNKNOWN)
    r = solve(inst)
    assert r.solution.status == "HEURISTIC_ONLY"
    assert r.validation.passed
    assert r.validation.coverage["covered_units"] == r.greedy["covered_units"] > 0
    assert r.solution.best_bounds["coverage"] >= r.greedy["covered_units"]
    assert any("greedy roster" in n for n in r.solution.stats["notes"])
