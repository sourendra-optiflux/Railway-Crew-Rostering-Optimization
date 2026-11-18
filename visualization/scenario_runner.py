"""Isolated What-If Scenario Builder and Disruption Simulator runners for the dashboard."""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

from visualization.data_loader import ROOT, DashboardDataset, load_dashboard_dataset

WORKING_DATA_DIR = ROOT / "outputs" / "working_data"
WHATIF_OUTPUTS_DIR = ROOT / "CP-SAT" / "outputs" / "whatif"


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def ensure_working_data_dir(
    base_data_dir: Path,
    working_dir: Path = WORKING_DATA_DIR,
    *,
    reset: bool = False,
) -> Path:
    """Create/populate a non-tracked working copy of input CSVs under `outputs/working_data/`."""
    working_dir.mkdir(parents=True, exist_ok=True)
    if base_data_dir.exists():
        for src_csv in sorted(base_data_dir.glob("*.csv")):
            dst_csv = working_dir / src_csv.name
            if reset or not dst_csv.exists():
                shutil.copy2(src_csv, dst_csv)
    base_cfg = ROOT / "config.yml"
    dst_cfg = working_dir / "config.yml"
    if base_cfg.exists() and (reset or not dst_cfg.exists()):
        shutil.copy2(base_cfg, dst_cfg)
    return working_dir


def save_working_csv_with_backup(
    working_csv_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
    *,
    working_root: Path = WORKING_DATA_DIR,
) -> Path:
    """Write a `.bak` copy first and save CSV rows strictly inside the non-tracked working copy directory."""
    resolved_target = working_csv_path.resolve()
    resolved_root = working_root.resolve()
    if resolved_root not in resolved_target.parents:
        raise ValueError(
            f"Refusing to overwrite tracked file '{working_csv_path}'; edits must target '{working_root}'."
        )
    working_csv_path.parent.mkdir(parents=True, exist_ok=True)
    bak_path = working_csv_path.with_suffix(working_csv_path.suffix + ".bak")
    if working_csv_path.exists():
        shutil.copy2(working_csv_path, bak_path)
    _write_csv_rows(working_csv_path, fieldnames, rows)
    return bak_path


def _format_num(value: float) -> str:
    return str(int(value) if float(value).is_integer() else value)


def stream_command(
    cmd: list[str],
    cwd: Path,
    log_callback: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """Run a command and stream stdout+stderr line-by-line to log_callback."""
    lines: list[str] = []
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is not None:
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\r\n")
            lines.append(line)
            if log_callback is not None:
                log_callback(line)
    rc = proc.wait()
    return rc, "\n".join(lines)


def _run_layer1_and_layer2(
    data_dir: Path,
    roster_full_path: Path,
    config_path: Path,
    opts_dir: Path,
    out_dir: Path,
    time_limit: int = 30,
    log_callback: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    logs: list[str] = []

    if log_callback is not None:
        log_callback("=== Layer 1: Option Generation ===")
    rc1, out1 = stream_command(
        [
            sys.executable,
            "option_generation/generate_options.py",
            "--data-dir", str(data_dir),
            "--roster-full", str(roster_full_path),
            "--output-dir", str(opts_dir),
            "--config", str(config_path),
        ],
        cwd=ROOT,
        log_callback=log_callback,
    )
    logs.append("=== Layer 1: Option Generation ===\n" + out1)
    if rc1 != 0:
        return False, "\n".join(logs)

    if log_callback is not None:
        log_callback("=== Layer 2: CP-SAT Solver ===")
    _, out2 = stream_command(
        [
            sys.executable,
            "CP-SAT/run_gap_filling.py",
            "--data-dir", str(data_dir),
            "--roster-full", str(roster_full_path),
            "--options-dir", str(opts_dir),
            "--output-dir", str(out_dir),
            "--config", str(config_path),
            "--time-limit", str(time_limit),
            "--workers", "2",
        ],
        cwd=ROOT,
        log_callback=log_callback,
    )
    logs.append("=== Layer 2: CP-SAT Solver ===\n" + out2)
    ok = (out_dir / "roster_full.csv").exists()
    return ok, "\n".join(logs)


def _apply_rule_overrides_to_dir(
    data_dir: Path,
    config_path: Path,
    *,
    residential_start_restriction: bool,
    relief_only_day_night_transition: bool,
    priority_strategy: str,
    assignment_type_priority_enabled: bool,
    assignment_type_tier_penalty: int,
    activity_head_max_shifts_enabled: bool,
    ordinary_rest_hours: float,
    transition_rest_hours: float,
    max_start_changes_per_block: int,
    max_start_change_minutes: int,
    allow_start_time_offsets: bool,
    solver_start_date: str | None = None,
    assignment_type_priority_map: dict[str, int] | None = None,
    activity_priority_overrides: list[dict[str, str]] | None = None,
    constraints_table_overrides: list[dict[str, str]] | None = None,
) -> None:
    """Apply rule, constraint, and objective overrides to data_dir and config_path."""
    cons_path = data_dir / "constraints_df.csv"
    fieldnames, cons_rows = _read_csv_rows(cons_path)
    if constraints_table_overrides:
        cons_rows = [
            {
                "Constraint": str(r.get("Constraint", "")).strip(),
                "Value": str(r.get("Value", "")).strip(),
                "Status": str(r.get("Status", "Active")).strip() or "Active",
            }
            for r in constraints_table_overrides
            if str(r.get("Constraint", "")).strip()
        ]
    seen_names: set[str] = set()
    offsets_val = "-60;0;60" if allow_start_time_offsets else "0"

    for row in cons_rows:
        name = row.get("Constraint", "")
        seen_names.add(name)
        if name == "Assignment Type Priority":
            row["Value"] = str(int(assignment_type_tier_penalty))
            row["Status"] = "Active" if assignment_type_priority_enabled else "Inactive"
        elif name == "Activity Head Max Shifts":
            row["Status"] = "Active" if activity_head_max_shifts_enabled else "Inactive"
        elif name == "Ordinary Rest Hours":
            row["Value"] = _format_num(ordinary_rest_hours)
        elif name == "Transition Rest Hours":
            row["Value"] = _format_num(transition_rest_hours)
        elif name == "Max Start Changes Per Block":
            row["Value"] = str(int(max_start_changes_per_block))
        elif name == "Max Start Change Minutes":
            row["Value"] = str(int(max_start_change_minutes))
        elif name in {"Excess Allowed Start Offsets", "Demand Allowed Start Offsets"}:
            row["Value"] = offsets_val
        elif name == "Solver Start Date" and solver_start_date:
            row["Value"] = solver_start_date.strip()

    if "Assignment Type Priority" not in seen_names:
        cons_rows.append({
            "Constraint": "Assignment Type Priority",
            "Value": str(int(assignment_type_tier_penalty)),
            "Status": "Active" if assignment_type_priority_enabled else "Inactive",
        })
    if "Activity Head Max Shifts" not in seen_names:
        cons_rows.append({
            "Constraint": "Activity Head Max Shifts",
            "Value": "",
            "Status": "Active" if activity_head_max_shifts_enabled else "Inactive",
        })
    _write_csv_rows(cons_path, fieldnames or ["Constraint", "Value", "Status"], cons_rows)

    if assignment_type_priority_map:
        at_path = data_dir / "assignment_type_priority.csv"
        if at_path.exists():
            at_fields, at_rows = _read_csv_rows(at_path)
            for row in at_rows:
                atype = row.get("Assignment Type", "")
                if atype in assignment_type_priority_map:
                    row["Priority"] = str(int(assignment_type_priority_map[atype]))
            _write_csv_rows(at_path, at_fields, at_rows)

    if activity_priority_overrides:
        ap_path = data_dir / "activity_priority.csv"
        if ap_path.exists():
            ap_fields, _ = _read_csv_rows(ap_path)
            _write_csv_rows(ap_path, ap_fields, activity_priority_overrides)

    config_path.write_text(
        "constraints:\n"
        f"  residential_start_restriction: {str(residential_start_restriction).lower()}\n"
        f"  relief_only_day_night_transition: {str(relief_only_day_night_transition).lower()}\n\n"
        "optimization:\n"
        f"  priority_strategy: {priority_strategy}\n",
        encoding="utf-8",
    )


def save_active_config_and_constraints(
    data_dir: Path,
    config_path: Path,
    *,
    residential_start_restriction: bool,
    relief_only_day_night_transition: bool,
    priority_strategy: str,
    assignment_type_priority_enabled: bool,
    assignment_type_tier_penalty: int = 1000,
    activity_head_max_shifts_enabled: bool = True,
    ordinary_rest_hours: float = 11.0,
    transition_rest_hours: float = 23.0,
    max_start_changes_per_block: int = 1,
    max_start_change_minutes: int = 60,
    allow_start_time_offsets: bool = True,
    solver_start_date: str | None = None,
    assignment_type_priority_map: dict[str, int] | None = None,
    activity_priority_overrides: list[dict[str, str]] | None = None,
    constraints_table_overrides: list[dict[str, str]] | None = None,
) -> None:
    """Persist rule, constraint, and objective overrides to the working copy config/data files."""
    tracked_data_dir = (ROOT / "data" / "optiflux_v2").resolve()
    target_data_dir = data_dir
    target_config_path = config_path
    if data_dir.resolve() == tracked_data_dir:
        target_data_dir = ensure_working_data_dir(data_dir)
        target_config_path = target_data_dir / "config.yml"
    _apply_rule_overrides_to_dir(
        target_data_dir,
        target_config_path,
        residential_start_restriction=residential_start_restriction,
        relief_only_day_night_transition=relief_only_day_night_transition,
        priority_strategy=priority_strategy,
        assignment_type_priority_enabled=assignment_type_priority_enabled,
        assignment_type_tier_penalty=assignment_type_tier_penalty,
        activity_head_max_shifts_enabled=activity_head_max_shifts_enabled,
        ordinary_rest_hours=ordinary_rest_hours,
        transition_rest_hours=transition_rest_hours,
        max_start_changes_per_block=max_start_changes_per_block,
        max_start_change_minutes=max_start_change_minutes,
        allow_start_time_offsets=allow_start_time_offsets,
        solver_start_date=solver_start_date,
        assignment_type_priority_map=assignment_type_priority_map,
        activity_priority_overrides=activity_priority_overrides,
        constraints_table_overrides=constraints_table_overrides,
    )


def run_what_if_scenario(
    base_data_dir: Path,
    base_roster_full: Path,
    *,
    residential_start_restriction: bool,
    relief_only_day_night_transition: bool,
    priority_strategy: str,
    assignment_type_priority_enabled: bool,
    activity_head_max_shifts_enabled: bool,
    ordinary_rest_hours: float,
    transition_rest_hours: float,
    assignment_type_tier_penalty: int = 1000,
    max_start_changes_per_block: int = 1,
    max_start_change_minutes: int = 60,
    allow_start_time_offsets: bool = True,
    solver_start_date: str | None = None,
    assignment_type_priority_map: dict[str, int] | None = None,
    activity_priority_overrides: list[dict[str, str]] | None = None,
    constraints_table_overrides: list[dict[str, str]] | None = None,
    include_gap_generation: bool = False,
    gap_seed: int = 2026,
    persist_output_name: str | None = None,
    time_limit: int = 30,
    log_callback: Callable[[str], None] | None = None,
) -> tuple[DashboardDataset | None, str]:
    """Run an isolated What-If scenario with custom rule/strategy settings in a temp workspace."""
    target_persist_dir: Path | None = None
    if persist_output_name and persist_output_name.strip():
        safe_name = "".join(
            ch if (ch.isalnum() or ch in {"_", "-"}) else "_"
            for ch in persist_output_name.strip()
        ).strip("_-")
        if not safe_name:
            return None, "Invalid scenario output name."
        top_level_collision = ROOT / "CP-SAT" / "outputs" / safe_name
        candidate_persist_dir = WHATIF_OUTPUTS_DIR / safe_name
        if top_level_collision.exists() or candidate_persist_dir.exists():
            return (
                None,
                f"Refusing to overwrite existing output folder '{safe_name}'. "
                "Please choose a new unique scenario name.",
            )
        target_persist_dir = candidate_persist_dir

    with tempfile.TemporaryDirectory(prefix="rostering_whatif_") as tmp:
        tmp_path = Path(tmp)
        data_dir = tmp_path / "data"
        gap_dir = tmp_path / "gaps"
        opts_dir = tmp_path / "options"
        out_dir = tmp_path / "cpsat"
        cfg_path = tmp_path / "config.yml"
        roster_in = tmp_path / "roster_full_input.csv"

        shutil.copytree(base_data_dir, data_dir)
        if WORKING_DATA_DIR.exists() and base_data_dir.resolve() == (ROOT / "data" / "optiflux_v2").resolve():
            for working_csv in sorted(WORKING_DATA_DIR.glob("*.csv")):
                shutil.copy2(working_csv, data_dir / working_csv.name)
        shutil.copy2(base_roster_full, roster_in)

        _apply_rule_overrides_to_dir(
            data_dir,
            cfg_path,
            residential_start_restriction=residential_start_restriction,
            relief_only_day_night_transition=relief_only_day_night_transition,
            priority_strategy=priority_strategy,
            assignment_type_priority_enabled=assignment_type_priority_enabled,
            assignment_type_tier_penalty=assignment_type_tier_penalty,
            activity_head_max_shifts_enabled=activity_head_max_shifts_enabled,
            ordinary_rest_hours=ordinary_rest_hours,
            transition_rest_hours=transition_rest_hours,
            max_start_changes_per_block=max_start_changes_per_block,
            max_start_change_minutes=max_start_change_minutes,
            allow_start_time_offsets=allow_start_time_offsets,
            solver_start_date=solver_start_date,
            assignment_type_priority_map=assignment_type_priority_map,
            activity_priority_overrides=activity_priority_overrides,
            constraints_table_overrides=constraints_table_overrides,
        )

        gap_logs = ""
        if include_gap_generation:
            if log_callback:
                log_callback(f"=== Layer 0: Gap Generation (make_gaps.py, seed={gap_seed}) ===")
            rc0, out0 = stream_command(
                [
                    sys.executable,
                    str(ROOT / "gap_generation" / "make_gaps.py"),
                    "--data-dir",
                    str(data_dir),
                    "--output-dir",
                    str(gap_dir),
                    "--seed",
                    str(int(gap_seed)),
                ],
                cwd=ROOT,
                log_callback=log_callback,
            )
            gap_logs = f"=== Layer 0: Gap Generation (seed={gap_seed}) ===\n{out0}\n"
            if rc0 != 0 or not (gap_dir / "roster_full.csv").exists():
                return None, gap_logs
            roster_in = gap_dir / "roster_full.csv"

        ok, logs = _run_layer1_and_layer2(
            data_dir,
            roster_in,
            cfg_path,
            opts_dir,
            out_dir,
            time_limit=time_limit,
            log_callback=log_callback,
        )
        full_logs = (gap_logs + logs) if gap_logs else logs
        if not ok:
            return None, full_logs

        if target_persist_dir is not None:
            if target_persist_dir.exists():
                return (
                    None,
                    f"Refusing to overwrite existing output folder '{target_persist_dir}'.",
                )
            target_persist_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(out_dir, target_persist_dir)
            (target_persist_dir / "solver.log").write_text(full_logs, encoding="utf-8")

        ds = load_dashboard_dataset(
            data_dir=data_dir,
            cpsat_dir=out_dir,
            options_dir=opts_dir,
            config_path=cfg_path,
            name="What-If Scenario",
        )
        return ds, full_logs


def run_disruption_simulation(
    base_data_dir: Path,
    base_roster_full: Path,
    base_config_path: Path,
    disrupted_assignment_ids: list[str],
    leave_label: str = "Simulated Sick",
    time_limit: int = 30,
    log_callback: Callable[[str], None] | None = None,
) -> tuple[DashboardDataset | None, str]:
    """Simulate unexpected crew absence on selected Assignment IDs and re-solve recovery."""
    target_ids = {aid.strip() for aid in disrupted_assignment_ids if aid.strip()}
    if not target_ids:
        return None, "No Assignment IDs selected for disruption."

    with tempfile.TemporaryDirectory(prefix="rostering_disrupt_") as tmp:
        tmp_path = Path(tmp)
        data_dir = tmp_path / "data"
        opts_dir = tmp_path / "options"
        out_dir = tmp_path / "cpsat"
        cfg_path = tmp_path / "config.yml"
        roster_in = tmp_path / "roster_full_disrupted.csv"

        shutil.copytree(base_data_dir, data_dir)
        shutil.copy2(base_config_path, cfg_path)

        fieldnames, rows = _read_csv_rows(base_roster_full)
        modified_count = 0
        for r in rows:
            if r.get("Assignment ID", "").strip() in target_ids:
                r["New User Id"] = ""
                r["Optimised User Id"] = ""
                r["Leave Type"] = leave_label
                r["Is Gap"] = "True"
                r["Is_locked_gap"] = "False"
                modified_count += 1
            else:
                if r.get("Is Gap", "").strip() != "True":
                    uid = r.get("Optimised User Id", "").strip() or r.get("User Id", "").strip()
                    r["New User Id"] = uid
                    r["Optimised User Id"] = uid

        _write_csv_rows(roster_in, fieldnames, rows)
        if modified_count == 0:
            return None, "Selected Assignment IDs were not found in roster_full.csv."

        ok, logs = _run_layer1_and_layer2(
            data_dir,
            roster_in,
            cfg_path,
            opts_dir,
            out_dir,
            time_limit=time_limit,
            log_callback=log_callback,
        )
        if not ok:
            return None, logs

        ds = load_dashboard_dataset(
            data_dir=data_dir,
            cpsat_dir=out_dir,
            options_dir=opts_dir,
            config_path=cfg_path,
            name="Disruption Simulation",
        )
        return ds, logs
