"""Isolated What-If Scenario Builder and Disruption Simulator runners for the dashboard."""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from visualization.data_loader import ROOT, DashboardDataset, load_dashboard_dataset


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _run_layer1_and_layer2(
    data_dir: Path,
    roster_full_path: Path,
    config_path: Path,
    opts_dir: Path,
    out_dir: Path,
    time_limit: int = 30,
) -> tuple[bool, str]:
    logs: list[str] = []

    res1 = subprocess.run(
        [
            sys.executable,
            "option_generation/generate_options.py",
            "--data-dir", str(data_dir),
            "--roster-full", str(roster_full_path),
            "--output-dir", str(opts_dir),
            "--config", str(config_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    logs.append("=== Layer 1: Option Generation ===\n" + (res1.stdout or "") + (res1.stderr or ""))
    if res1.returncode != 0:
        return False, "\n".join(logs)

    res2 = subprocess.run(
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
        capture_output=True,
        text=True,
        check=False,
    )
    logs.append("=== Layer 2: CP-SAT Solver ===\n" + (res2.stdout or "") + (res2.stderr or ""))
    ok = (out_dir / "roster_full.csv").exists()
    return ok, "\n".join(logs)


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
    time_limit: int = 30,
) -> tuple[DashboardDataset | None, str]:
    """Run an isolated What-If scenario with custom rule/strategy settings in a temp workspace."""
    with tempfile.TemporaryDirectory(prefix="rostering_whatif_") as tmp:
        tmp_path = Path(tmp)
        data_dir = tmp_path / "data"
        opts_dir = tmp_path / "options"
        out_dir = tmp_path / "cpsat"
        cfg_path = tmp_path / "config.yml"
        roster_in = tmp_path / "roster_full_input.csv"

        shutil.copytree(base_data_dir, data_dir)
        shutil.copy2(base_roster_full, roster_in)

        # Apply constraints_df.csv overrides
        cons_path = data_dir / "constraints_df.csv"
        fieldnames, cons_rows = _read_csv_rows(cons_path)
        seen_names: set[str] = set()
        for row in cons_rows:
            name = row.get("Constraint", "")
            seen_names.add(name)
            if name == "Assignment Type Priority":
                row["Status"] = "Active" if assignment_type_priority_enabled else "Inactive"
            elif name == "Activity Head Max Shifts":
                row["Status"] = "Active" if activity_head_max_shifts_enabled else "Inactive"
            elif name == "Ordinary Rest Hours":
                row["Value"] = str(int(ordinary_rest_hours) if float(ordinary_rest_hours).is_integer() else ordinary_rest_hours)
            elif name == "Transition Rest Hours":
                row["Value"] = str(int(transition_rest_hours) if float(transition_rest_hours).is_integer() else transition_rest_hours)

        if "Assignment Type Priority" not in seen_names:
            cons_rows.append({
                "Constraint": "Assignment Type Priority",
                "Value": "",
                "Status": "Active" if assignment_type_priority_enabled else "Inactive",
            })
        if "Activity Head Max Shifts" not in seen_names:
            cons_rows.append({
                "Constraint": "Activity Head Max Shifts",
                "Value": "",
                "Status": "Active" if activity_head_max_shifts_enabled else "Inactive",
            })
        _write_csv_rows(cons_path, fieldnames or ["Constraint", "Value", "Status"], cons_rows)

        cfg_path.write_text(
            "constraints:\n"
            f"  residential_start_restriction: {str(residential_start_restriction).lower()}\n"
            f"  relief_only_day_night_transition: {str(relief_only_day_night_transition).lower()}\n\n"
            "optimization:\n"
            f"  priority_strategy: {priority_strategy}\n",
            encoding="utf-8",
        )

        ok, logs = _run_layer1_and_layer2(data_dir, roster_in, cfg_path, opts_dir, out_dir, time_limit=time_limit)
        if not ok:
            return None, logs

        ds = load_dashboard_dataset(
            data_dir=data_dir,
            cpsat_dir=out_dir,
            options_dir=opts_dir,
            config_path=cfg_path,
            name="What-If Scenario",
        )
        return ds, logs


def run_disruption_simulation(
    base_data_dir: Path,
    base_roster_full: Path,
    base_config_path: Path,
    disrupted_assignment_ids: list[str],
    leave_label: str = "Simulated Sick",
    time_limit: int = 30,
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
        # Keep only gap_generation columns + reset Optimised User Id to New User Id for non-gap rows
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
                # Preserve existing assignment as input to solver
                if r.get("Is Gap", "").strip() != "True":
                    uid = r.get("Optimised User Id", "").strip() or r.get("User Id", "").strip()
                    r["New User Id"] = uid
                    r["Optimised User Id"] = uid

        _write_csv_rows(roster_in, fieldnames, rows)
        if modified_count == 0:
            return None, "Selected Assignment IDs were not found in roster_full.csv."

        ok, logs = _run_layer1_and_layer2(data_dir, roster_in, cfg_path, opts_dir, out_dir, time_limit=time_limit)
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
