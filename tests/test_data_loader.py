"""Parsing, legacy V1 format, round trips and input validation."""

from datetime import datetime
from pathlib import Path

import pytest

from railway_rostering import DataError, ModelConfig, load_instance, solve_instance, write_instance
from railway_rostering.domain import CrewType
from railway_rostering.validation import ERROR, validate_instance

ROOT = Path(__file__).resolve().parents[1]


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_load_canonical_sample():
    inst = load_instance(ROOT / "data/sample/briefing_abc")
    assert list(inst.crews) == ["ABC"]
    abc = inst.crews["ABC"]
    assert abc.crew_type == CrewType.RELIEF and abc.base_location == "Howrah" and abc.work_days == 14
    assert inst.qualifications["ABC"] == {"Howrah Mainline", "Yajpur Mainline", "Howrah Mainline CO"}
    d1 = inst.duty("D01")
    assert d1.end == datetime(2026, 11, 2, 5, 0)  # crosses midnight
    assert inst.horizon_end == datetime(2026, 11, 8)


def test_legacy_v1_format_and_default_duration():
    inst = load_instance(ROOT / "data/sample/v1_toy")
    assert set(inst.crews) == {"A", "B", "C"}
    assert inst.crews["A"].crew_type == CrewType.UNSPECIFIED
    g1 = inst.duty("G1")
    assert g1.eligible_crew == {"A", "B"}
    assert (g1.end - g1.start).total_seconds() == 12 * 3600
    assert inst.qualifications is None


def test_header_whitespace_is_stripped(tmp_path):
    write(tmp_path, "crew.csv", " person_id , initial_location \nA,Howrah\n")
    write(
        tmp_path,
        "duties.csv",
        " id,start,start_location,end_location,activity,eligible\nG1,2026-11-01 17:00,Howrah,Yajpur,HM,A\n",
    )
    inst = load_instance(tmp_path)
    assert inst.duty("G1").eligible_crew == {"A"}


def test_all_parse_errors_reported_together(tmp_path):
    write(tmp_path, "crew.csv", "crew_id,initial_location\nA,Howrah\nA,Yajpur\n")
    write(
        tmp_path,
        "duties.csv",
        "duty_id,activity,start,end,start_location,end_location,demand\n"
        "D1,HM,01/11/2026 17:00,,Howrah,Yajpur,1\n"
        "D2,HM,2026-11-01 17:00,2026-11-01 16:00,Howrah,Yajpur,1\n"
        "D3,HM,2026-11-01 17:00,,Howrah,Yajpur,0\n"
        "D3,HM,2026-11-01 17:00,,Howrah,Yajpur,1\n",
    )
    with pytest.raises(DataError) as exc:
        load_instance(tmp_path)
    msgs = "\n".join(exc.value.errors)
    assert len(exc.value.errors) == 5
    for fragment in [
        "duplicate crew_id A",
        "invalid start",
        "is not after start",
        "demand must be >= 1",
        "duplicate duty_id D3",
    ]:
        assert fragment in msgs


def test_missing_required_columns(tmp_path):
    write(tmp_path, "crew.csv", "crew_id\nA\n")
    write(tmp_path, "duties.csv", "duty_id,start\nD1,2026-11-01 05:00\n")
    with pytest.raises(DataError) as exc:
        load_instance(tmp_path)
    assert any("missing required columns" in e for e in exc.value.errors)


def test_missing_files(tmp_path):
    with pytest.raises(DataError):
        load_instance(tmp_path)


def test_write_then_load_round_trip(tmp_path):
    inst = load_instance(ROOT / "data/generated/small")
    write_instance(inst, tmp_path / "copy")
    again = load_instance(tmp_path / "copy")
    assert again.crews == inst.crews
    assert again.duties == inst.duties
    assert again.qualifications == inst.qualifications
    assert again.travel == inst.travel
    assert (again.horizon_start, again.horizon_end) == (inst.horizon_start, inst.horizon_end)


def test_unknown_crew_in_eligible_list_is_an_error(tmp_path):
    write(tmp_path, "crew.csv", "crew_id,initial_location\nA,Howrah\n")
    write(
        tmp_path,
        "duties.csv",
        "duty_id,activity,start,start_location,end_location,eligible_crew\nD1,HM,2026-11-01 05:00,Howrah,Yajpur,A;Z\n",
    )
    inst = load_instance(tmp_path)
    issues = validate_instance(inst, ModelConfig())
    assert any(i.severity == ERROR and i.code == "UNKNOWN_ELIGIBLE_CREW" for i in issues)
    result = solve_instance(inst)
    assert result.solution.status == "INPUT_ERROR" and result.validation is None


def test_missing_eligibility_information_warns(tmp_path):
    write(tmp_path, "crew.csv", "crew_id,initial_location\nA,Howrah\n")
    write(
        tmp_path,
        "duties.csv",
        "duty_id,activity,start,start_location,end_location\nD1,HM,2026-11-01 05:00,Howrah,Yajpur\n",
    )
    inst = load_instance(tmp_path)
    codes = {i.code for i in validate_instance(inst, ModelConfig())}
    assert "NO_ELIGIBILITY_INFO" in codes
    r = solve_instance(inst)
    assert r.validation.coverage["covered_units"] == 0
    assert r.candidates.diagnostics["D1"].structural_reason() == "NO_ELIGIBLE_CREW"


def test_existing_overlap_is_an_error(tmp_path):
    write(tmp_path, "crew.csv", "crew_id,initial_location\nA,Howrah\n")
    write(
        tmp_path,
        "duties.csv",
        "duty_id,activity,start,start_location,end_location,eligible_crew,assigned_crew\n"
        "D1,HM,2026-11-01 05:00,Howrah,Howrah,A,A\nD2,HM,2026-11-01 06:00,Howrah,Howrah,A,A\n",
    )
    codes = {i.code for i in validate_instance(load_instance(tmp_path), ModelConfig())}
    assert "EXISTING_OVERLAP" in codes


def test_config_validation_rejects_unknown_values():
    with pytest.raises(ValueError):
        ModelConfig(demand_mode="most").validate()
    with pytest.raises(ValueError):
        ModelConfig(objective_levels=["coverage", "happiness"]).validate()
    with pytest.raises(ValueError):
        ModelConfig(time_change_policy={"RELIEF": "sometimes", "EXCESS": "disabled"}).validate()
