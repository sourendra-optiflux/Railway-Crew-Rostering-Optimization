"""Benchmark runner: solve synthetic presets under several rule variants.

Each run records instance size, seed, enabled rules (variant), time limit,
solver status per stage, coverage, best bound, gap, greedy baseline, runtime,
independent-validation result and (for small enough instances) the flow-MIP
cross-check. Results go to ``results.csv``, ``results.json`` and a Markdown
table ``results.md`` in the output directory.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import time
from dataclasses import replace
from pathlib import Path

import ortools

from .config import ModelConfig, SolverConfig, model_config_from_dict
from .mip_crosscheck import solve_flow_mip
from .solve import solve_instance
from .synthetic_db import DB_PRESETS, generate_db_instance


def variant_configs(
    name: str, base_solver: SolverConfig, base_model: ModelConfig | None = None
) -> tuple[ModelConfig, SolverConfig]:
    """Variant of the instance's own rules (``base_model``, from constraints_df) and the solver settings."""

    m = replace(base_model) if base_model is not None else ModelConfig()
    s = replace(base_solver)
    if name == "default":
        pass
    elif name == "no_cliques":
        m.add_redundant_cliques = False
    elif name == "no_hint":
        s.use_greedy_hint = False
    elif name == "no_lp_bound":
        s.use_lp_bound = False
    elif name == "window_only":
        m.time_change_policy = {"RELIEF": "window_only", "EXCESS": "window_only"}
    elif name == "relaxed":
        # Rule-impact study only: drops transition rest, base return and swing calendar.
        m.transition_rest_enabled = False
        m.base_return_at_swing_end = False
        m.base_return_on_transition = False
        m.enforce_swing_work_days = False
        m.time_change_policy = {"RELIEF": "disabled", "EXCESS": "disabled"}
    else:
        raise ValueError(f"unknown variant {name}")
    return m, s


COLUMNS = [
    "preset", "variant", "seed", "n_crew", "n_duties", "horizon_days", "open_units", "n_candidate_pairs",
    "n_arcs", "time_limit_s", "status", "stage_statuses", "covered_units", "coverage_pct", "best_bound",
    "gap_pct", "greedy_units", "uncovered_structural", "runtime_total_s", "runtime_solve_s",
    "validation_passed", "mip_status", "mip_covered_units", "mip_runtime_s", "mip_agrees",
]  # fmt: skip


def run_benchmarks(
    presets: list[str],
    output_dir: Path,
    time_limit: float = 60.0,
    workers: int = 8,
    variants: list[str] | None = None,
    mip_check_max_duties: int = 150,
) -> list[dict]:
    variants = variants or ["default"]
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    base_solver = SolverConfig(time_limit_seconds=time_limit, num_workers=workers)
    for preset in presets:
        gcfg = DB_PRESETS[preset]
        inst = generate_db_instance(gcfg)
        base_model = model_config_from_dict(dict(inst.metadata["model_config"]))
        for variant in variants:
            mcfg, scfg = variant_configs(variant, base_solver, base_model)
            res = solve_instance(inst, mcfg, scfg)
            sol = res.solution
            cov = res.validation.coverage if res.validation else {}
            bound = sol.best_bounds.get("coverage")
            found = sol.objective_values.get("coverage")
            row = {
                "preset": preset,
                "variant": variant,
                "seed": gcfg.seed,
                "n_crew": len(inst.crews),
                "n_duties": len(inst.duties),
                "horizon_days": gcfg.horizon_days,
                "open_units": inst.total_open_demand,
                "n_candidate_pairs": sol.stats.get("n_candidate_pairs"),
                "n_arcs": sol.stats.get("n_arcs"),
                "time_limit_s": time_limit,
                "status": sol.status,
                "stage_statuses": ";".join(f"{k}={v}" for k, v in sol.stage_statuses.items()),
                "covered_units": cov.get("covered_units"),
                "coverage_pct": cov.get("coverage_pct"),
                "best_bound": bound,
                "gap_pct": round(100 * (bound - found) / bound, 3) if bound else None,
                "greedy_units": res.greedy.get("covered_units"),
                "uncovered_structural": sol.stats.get("n_duties_structurally_uncoverable"),
                "runtime_total_s": round(res.timings.get("total", 0), 3),
                "runtime_solve_s": round(res.timings.get("solve", 0), 3),
                "validation_passed": res.validation.passed if res.validation else None,
                "mip_status": "",
                "mip_covered_units": "",
                "mip_runtime_s": "",
                "mip_agrees": "",
            }
            if len(inst.duties) <= mip_check_max_duties and res.candidates is not None:
                t = time.perf_counter()
                mip = solve_flow_mip(res.candidates, "SCIP", time_limit_s=max(time_limit, 60))
                row["mip_runtime_s"] = round(time.perf_counter() - t, 3)
                row["mip_status"] = mip["status"]
                row["mip_covered_units"] = mip.get("covered_units", "")
                if mip["status"] == "OPTIMAL" and sol.stage_statuses.get("coverage") == "OPTIMAL":
                    row["mip_agrees"] = mip.get("covered_units") == found
            rows.append(row)
            print(
                f"[{preset}/{variant}] status={row['status']} covered={row['covered_units']}/{row['open_units']} "
                f"bound={row['best_bound']} greedy={row['greedy_units']} t={row['runtime_total_s']}s "
                f"valid={row['validation_passed']} mip={row['mip_status']}:{row['mip_covered_units']}",
                flush=True,
            )

    env = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "ortools": ortools.__version__,
        "cpu_count": os.cpu_count(),
        "workers": workers,
        "time_limit_per_stage_s": time_limit,
    }
    with (output_dir / "results.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    (output_dir / "results.json").write_text(json.dumps({"environment": env, "runs": rows}, indent=2, default=str))
    md_cols = ["preset", "variant", "n_crew", "n_duties", "open_units", "status", "covered_units", "best_bound",
               "coverage_pct", "greedy_units", "runtime_total_s", "validation_passed", "mip_covered_units"]  # fmt: skip
    lines = ["| " + " | ".join(md_cols) + " |", "|" + "---|" * len(md_cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r[c]) for c in md_cols) + " |")
    lines.append("")
    lines.append("Environment: " + ", ".join(f"{k}={v}" for k, v in env.items()))
    (output_dir / "results.md").write_text("\n".join(lines) + "\n")
    return rows
