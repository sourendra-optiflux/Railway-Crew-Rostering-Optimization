"""Write a :class:`RunResult` to output files and build the summary.

Files written to the output directory:

``assignments.csv``       one row per (crew, duty) in the solution, in route order.
``uncovered_duties.csv``  one row per duty with uncovered demand, with a reason code.
``crew_routes.csv``       one row per crew member who received work.
``positioning.csv``       positioning legs used (only when positioning is enabled).
``summary.json``          status, objective values, bounds, coverage, timings,
                          model size, greedy baseline, rule status, input issues.
``validation_report.json`` output of the independent validator.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from . import __version__
from .candidate_generation import NOT_SELECTED, REASON_TEXT
from .config import ModelConfig
from .constraints import co_rules
from .constraints.time_rest import shift_type_of
from .domain import DATETIME_FORMAT, circular_offset_minutes
from .solve import RunResult


def rule_status(cfg: ModelConfig) -> dict[str, str]:
    """Which rules are implemented, approximated or disabled in this run."""

    return {
        "eligibility": "implemented (hard): activity table and/or per-duty list, exact activity match",
        "assignment_uniqueness_and_demand": f"implemented (hard), demand_mode={cfg.demand_mode}",
        "overlap": "implemented (hard)",
        "ordinary_rest": f"implemented (hard): {cfg.ordinary_rest_hours} h between consecutive duties",
        "transition_rest": (
            f"implemented (hard): {cfg.transition_rest_hours} h when DAY<->NIGHT changes; "
            f"DAY = start in [{cfg.day_shift_start_from}, {cfg.day_shift_start_until}) (approximation)"
            if cfg.transition_rest_enabled
            else "disabled"
        ),
        "location_continuity": "implemented (hard)"
        + ("; positioning via travel.csv (synthetic times)" if cfg.positioning_enabled else "; no positioning"),
        "swing_work_days": "implemented (hard) by duty start date" if cfg.enforce_swing_work_days else "disabled",
        "time_change_relief": f"{cfg.time_change_policy.get('RELIEF')}, offsets={cfg.allowed_offsets_minutes.get('RELIEF')}",
        "time_change_excess": f"{cfg.time_change_policy.get('EXCESS')}, offsets={cfg.allowed_offsets_minutes.get('EXCESS')}",
        "base_return_swing_end": "approximated (hard): be at base after last duty of a swing"
        if cfg.base_return_at_swing_end
        else "disabled",
        "base_return_transition": "approximated (hard): be at base between DAY<->NIGHT duties"
        if cfg.base_return_on_transition
        else "disabled",
        "base_return_horizon_end": "enabled (assumption)" if cfg.base_return_at_horizon_end else "disabled",
        "daily_cap": f"assumption (hard): max {cfg.max_duties_per_day} duty starts per date"
        if cfg.max_duties_per_day
        else "disabled",
        "existing_assignments": cfg.existing_assignment_mode,
        "co_requirement": co_rules.STATUS["co_requirement"],
        "co_location": co_rules.STATUS["co_location"],
    }


def _fmt(dt) -> str:
    return dt.strftime(DATETIME_FORMAT)


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def build_summary(result: RunResult) -> dict:
    inst, sol, cfg = result.instance, result.solution, result.model_config
    cov = result.validation.coverage if result.validation else {}
    bound = sol.best_bounds.get("coverage")
    found = sol.objective_values.get("coverage")
    gap = None
    if bound is not None and found is not None and bound > 0:
        gap = round(100.0 * (bound - found) / bound, 3)
    return {
        "package_version": __version__,
        "instance": {
            "name": inst.name,
            "synthetic": bool(inst.metadata.get("synthetic", False)),
            "n_crew": len(inst.crews),
            "n_duties": len(inst.duties),
            "open_demand_units": inst.total_open_demand,
            "horizon_start": _fmt(inst.horizon_start),
            "horizon_end": _fmt(inst.horizon_end),
            "seed": inst.metadata.get("seed"),
        },
        "data_preparation": {k: v for k, v in inst.metadata.get("data_preparation", {}).items() if k != "disruptions"},
        "status": sol.status,
        "stage_statuses": sol.stage_statuses,
        "objective_values": sol.objective_values,
        "best_bounds": sol.best_bounds,
        "coverage_gap_pct": gap,
        "coverage": cov,
        "greedy_baseline": result.greedy,
        "validation_passed": result.validation.passed if result.validation else None,
        "n_validation_violations": len(result.validation.violations) if result.validation else None,
        "timings_seconds": {k: round(v, 4) for k, v in result.timings.items()},
        "model_stats": sol.stats,
        "candidate_issues": result.candidates.issues if result.candidates else [],
        "input_issues": {
            "n_errors": sum(1 for i in result.input_issues if i.severity == "ERROR"),
            "n_warnings": sum(1 for i in result.input_issues if i.severity == "WARNING"),
            "items": [i.to_dict() for i in result.input_issues[:200]],
        },
        "rule_status": rule_status(cfg),
        "model_config": cfg.to_dict(),
        "solver_config": result.solver_config.to_dict(),
    }


def assignment_rows(result: RunResult) -> list[dict]:
    inst, sol, cfg = result.instance, result.solution, result.model_config
    rows = []
    existing = {(a.crew_id, a.duty_id): a.existing for a in sol.assignments}
    for cid in sorted(sol.routes):
        crew = inst.crews[cid]
        for k, did in enumerate(sol.routes[cid], start=1):
            d = inst.duty(did)
            off = circular_offset_minutes(d.start.time(), crew.rostered_start) if crew.rostered_start else ""
            rows.append(
                {
                    "crew_id": cid,
                    "crew_type": crew.crew_type.value,
                    "sequence": k,
                    "duty_id": did,
                    "activity": d.activity,
                    "start": _fmt(d.start),
                    "end": _fmt(d.end),
                    "start_location": d.start_location,
                    "end_location": d.end_location,
                    "shift_type": shift_type_of(d, cfg).value,
                    "rostered_start_time": crew.rostered_start.strftime("%H:%M") if crew.rostered_start else "",
                    "start_offset_minutes": off,
                    "assignment_type": "existing" if existing.get((cid, did)) else "new",
                    "base_location": crew.base_location or "",
                }
            )
    return rows


def uncovered_rows(result: RunResult) -> list[dict]:
    inst, sol = result.instance, result.solution
    staffed: dict[str, int] = {}
    for a in sol.assignments:
        staffed[a.duty_id] = staffed.get(a.duty_id, 0) + 1
    rows = []
    for d in inst.duties:
        n = staffed.get(d.duty_id, 0)
        if n >= d.demand:
            continue
        diag = result.candidates.diagnostics.get(d.duty_id) if result.candidates else None
        code = diag.structural_reason() if diag else None
        code = code or NOT_SELECTED
        rows.append(
            {
                "duty_id": d.duty_id,
                "activity": d.activity,
                "start": _fmt(d.start),
                "end": _fmt(d.end),
                "start_location": d.start_location,
                "end_location": d.end_location,
                "priority": "" if d.priority is None else d.priority,
                "demand": d.demand,
                "existing_units": len(d.assigned_crew),
                "assigned_units": n,
                "uncovered_units": d.demand - n,
                "reason_code": code,
                "reason": REASON_TEXT[code],
                "n_considered": diag.n_considered if diag else "",
                "n_eligible": diag.n_eligible if diag else "",
                "n_available": diag.n_available if diag else "",
                "n_time_ok": diag.n_time_ok if diag else "",
                "n_feasible_candidates": diag.n_reachable if diag else "",
            }
        )
    return rows


def route_rows(result: RunResult) -> list[dict]:
    inst, sol = result.instance, result.solution
    rows = []
    for cid in sorted(sol.routes):
        crew = inst.crews[cid]
        route = sol.routes[cid]
        final = inst.duty(route[-1]).end_location if route else crew.initial_location
        rows.append(
            {
                "crew_id": cid,
                "crew_type": crew.crew_type.value,
                "base_location": crew.base_location or "",
                "initial_location": crew.initial_location,
                "n_duties": len(route),
                "route": " > ".join(route),
                "final_location": final,
                "ends_at_base": "" if crew.base_location is None else final == crew.base_location,
            }
        )
    return rows


def write_outputs(result: RunResult, output_dir: str | Path) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}

    a_rows = assignment_rows(result)
    cols = [
        "crew_id", "crew_type", "sequence", "duty_id", "activity", "start", "end", "start_location",
        "end_location", "shift_type", "rostered_start_time", "start_offset_minutes", "assignment_type",
        "base_location",
    ]  # fmt: skip
    paths["assignments"] = out / "assignments.csv"
    _write_csv(paths["assignments"], cols, a_rows)

    u_rows = uncovered_rows(result)
    cols = [
        "duty_id", "activity", "start", "end", "start_location", "end_location", "priority", "demand",
        "existing_units", "assigned_units", "uncovered_units", "reason_code", "reason", "n_considered",
        "n_eligible", "n_available", "n_time_ok", "n_feasible_candidates",
    ]  # fmt: skip
    paths["uncovered_duties"] = out / "uncovered_duties.csv"
    _write_csv(paths["uncovered_duties"], cols, u_rows)

    r_rows = route_rows(result)
    cols = [
        "crew_id",
        "crew_type",
        "base_location",
        "initial_location",
        "n_duties",
        "route",
        "final_location",
        "ends_at_base",
    ]
    paths["crew_routes"] = out / "crew_routes.csv"
    _write_csv(paths["crew_routes"], cols, r_rows)

    if result.model_config.positioning_enabled:
        cols = [
            "crew_id",
            "after",
            "before",
            "from_location",
            "to_location",
            "travel_minutes",
            "cost",
            "base_return_reason",
        ]
        paths["positioning"] = out / "positioning.csv"
        _write_csv(paths["positioning"], cols, result.solution.positioning)

    prep = result.instance.metadata.get("data_preparation")
    if prep is not None:  # instance built from the OptiFlux DB tables
        paths["roster_disruptions"] = out / "roster_disruptions.csv"
        _write_csv(paths["roster_disruptions"], ["assignment_id", "cm_id", "activity", "start", "reason"],
                   prep.get("disruptions", []))  # fmt: skip

    paths["summary"] = out / "summary.json"
    paths["summary"].write_text(json.dumps(build_summary(result), indent=2, default=str) + "\n")
    paths["validation_report"] = out / "validation_report.json"
    report = result.validation.to_dict() if result.validation else {"passed": None, "reason": "no solution to validate"}
    paths["validation_report"].write_text(json.dumps(report, indent=2, default=str) + "\n")
    return paths


def console_summary(result: RunResult) -> str:
    s = build_summary(result)
    cov = s["coverage"] or {}
    prep = s.get("data_preparation") or {}
    lines = []
    if prep:
        lines.append(
            f"DB tables       : {prep['demand_units_total']} demand units in {prep['horizon_days']} days, "
            f"{prep['units_covered_by_regular_crew']} covered by regular crew, "
            f"{prep['regular_rows_disrupted']} roster rows disrupted, "
            f"{prep['released_unlocked_assignments']} unlocked Relief/Excess rows released"
        )
    lines += [
        f"Instance        : {s['instance']['name']} ({s['instance']['n_crew']} crew, "
        f"{s['instance']['n_duties']} duties, {s['instance']['open_demand_units']} open demand units)",
        f"Status          : {s['status']}  stages={s['stage_statuses']}",
        f"Covered units   : {cov.get('covered_units', '-')} / {cov.get('open_units', '-')} "
        f"({cov.get('coverage_pct', '-')}%)   best bound={s['best_bounds'].get('coverage', '-')}",
        f"Greedy baseline : {s['greedy_baseline'].get('covered_units', '-')} units",
        f"Validation      : {'PASSED' if s['validation_passed'] else 'FAILED' if s['validation_passed'] is False else '-'}"
        f" ({s['n_validation_violations']} violations)",
        f"Runtime         : {s['timings_seconds'].get('total', 0):.2f} s total, "
        f"{s['timings_seconds'].get('solve', 0):.2f} s in CP-SAT",
        f"Model size      : {s['model_stats'].get('n_x_vars', 0)} assignment vars, "
        f"{s['model_stats'].get('n_arc_vars', 0)} arc vars, {s['model_stats'].get('n_circuits', 0)} circuits",
    ]
    if s["input_issues"]["n_errors"]:
        lines.append(f"Input errors    : {s['input_issues']['n_errors']} (see summary.json)")
    if s["candidate_issues"]:
        lines.append(f"Candidate issues: {len(s['candidate_issues'])} (see summary.json)")
    return "\n".join(lines)
