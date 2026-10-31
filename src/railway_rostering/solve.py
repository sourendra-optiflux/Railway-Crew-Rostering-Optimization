"""End-to-end solve pipeline.

``solve_instance`` runs, in order:

1. input validation (:mod:`validation`) - stop on errors;
2. candidate generation (:mod:`candidate_generation`);
3. model construction (:mod:`model`);
4. greedy baseline (:mod:`heuristics`) used as a CP-SAT hint;
5. objective stages (:mod:`objective`) - lexicographic or weighted;
6. solution extraction (assignments, routes read from the circuit arcs,
   positioning legs);
7. independent validation (:mod:`solution_validation`) of both the CP-SAT
   solution and the greedy baseline.

Solver status semantics
-----------------------
``OPTIMAL``     every objective stage was proven optimal.
``FEASIBLE``    a solution was found but at least one stage hit the time limit
                before optimality was proven (the reported bound tells how far
                it can be from optimal).
``INFEASIBLE``  the hard constraints cannot all hold (with fixed existing
                assignments this usually means the input roster itself is
                inconsistent - see ``candidate_issues``).
``UNKNOWN``     no solution found within the time limit (and no legal greedy roster).
``HEURISTIC_ONLY`` CP-SAT found nothing within the time limit; the greedy roster,
                which the independent validator accepted, is returned instead.
                Its quality is not proven (``best_bounds`` may still hold an
                LP bound).
``INPUT_ERROR`` input validation failed; no model was built.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Optional

from ortools.sat.python import cp_model

from .candidate_generation import SINK, SOURCE, CandidateSet, generate_candidates
from .config import ModelConfig, SolverConfig, model_config_from_dict
from .domain import Assignment, Instance, Solution
from .heuristics import greedy_routes
from .lp_bound import LPRelaxation, integral_cut_value
from .model import RosteringModel, build_model
from .objective import build_levels, weighted_objective
from .solution_validation import ValidationReport, validate_solution
from .validation import Issue, has_errors, validate_instance


@dataclass
class RunResult:
    instance: Instance
    model_config: ModelConfig
    solver_config: SolverConfig
    input_issues: list[Issue]
    solution: Solution
    candidates: Optional[CandidateSet] = None
    validation: Optional[ValidationReport] = None
    greedy: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)


def _status_name(code: int) -> str:
    return {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }[code]


def _value(solver: cp_model.CpSolver, expr) -> int:
    if isinstance(expr, (int, float)):
        return int(expr)
    return int(round(solver.value(expr)))


def _apply_hint_from_routes(rm: RosteringModel, routes: dict[str, list[str]]) -> None:
    m = rm.model
    m.clear_hints()
    for (cid, did), var in rm.x.items():
        m.add_hint(var, did in routes.get(cid, ()))
    used = set()
    for cid, route in routes.items():
        seq = [SOURCE] + route + [SINK]
        used.update((cid, a, b) for a, b in zip(seq, seq[1:]))
    for key, lit in rm.arc_lits.items():
        m.add_hint(lit, key in used)
    for cid, lit in rm.empty.items():
        m.add_hint(lit, not routes.get(cid))


def _apply_hint_from_solver(rm: RosteringModel, solver: cp_model.CpSolver) -> None:
    m = rm.model
    m.clear_hints()
    for var in list(rm.x.values()) + list(rm.arc_lits.values()) + list(rm.empty.values()) + list(rm.full.values()):
        m.add_hint(var, solver.boolean_value(var))


def _extract(rm: RosteringModel, solver: cp_model.CpSolver) -> tuple[list[Assignment], dict, list[dict]]:
    assignments: list[Assignment] = []
    for (cid, did), var in sorted(rm.x.items()):
        if solver.boolean_value(var):
            existing = cid in rm.instance.duty(did).assigned_crew
            assignments.append(Assignment(cid, did, existing))
    succ: dict[str, dict[str, str]] = {}
    for (cid, tail, head), lit in rm.arc_lits.items():
        if solver.boolean_value(lit):
            if tail in succ.setdefault(cid, {}):
                raise RuntimeError(f"two successors for {cid}:{tail}")
            succ[cid][tail] = head
    arc_index = {(cid, a.tail, a.head): a for cid, cc in rm.cands.crews.items() for a in cc.arcs}
    routes: dict[str, list[str]] = {}
    positioning: list[dict] = []
    for cid, nxt in succ.items():
        route, node = [], SOURCE
        while True:
            head = nxt[node]
            arc = arc_index[(cid, node, head)]
            for leg in arc.legs:
                positioning.append(
                    {
                        "crew_id": cid,
                        "after": "" if node == SOURCE else node,
                        "before": "" if head == SINK else head,
                        "from_location": leg.from_location,
                        "to_location": leg.to_location,
                        "travel_minutes": leg.travel_minutes,
                        "cost": leg.cost,
                        "base_return_reason": arc.base_reason or "",
                    }
                )
            if head == SINK:
                break
            route.append(head)
            node = head
        routes[cid] = route
    # Consistency check between x and the circuit (guards against encoding bugs).
    from_x: dict[str, set] = {}
    for a in assignments:
        from_x.setdefault(a.crew_id, set()).add(a.duty_id)
    for cid in set(from_x) | set(routes):
        if set(routes.get(cid, [])) != from_x.get(cid, set()):
            raise RuntimeError(f"route/x mismatch for crew {cid}")
    return assignments, routes, positioning


@dataclass
class _Staged:
    rm: RosteringModel
    levels: list
    stages: list
    status: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    bounds: dict = field(default_factory=dict)
    times: dict = field(default_factory=dict)
    lp_bounds: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    last_good: Optional[cp_model.CpSolver] = None
    overall: str = "UNKNOWN"
    cut_suspect: bool = False


def _run_stages(cands: CandidateSet, scfg: SolverConfig, g_routes, use_lp: bool, timings: dict) -> _Staged:
    t = _time.perf_counter()
    rm = build_model(cands)
    levels = build_levels(rm)
    timings["model_build"] = _time.perf_counter() - t
    if scfg.use_greedy_hint:
        _apply_hint_from_routes(rm, g_routes)
    active = [lvl for lvl in levels if not lvl.trivial]
    if cands.config.objective_mode == "weighted":
        stages = [("weighted", True, weighted_objective(levels), None)]
    else:
        stages = [(lvl.name, lvl.maximise, lvl.expr(), lvl) for lvl in active]
    out = _Staged(rm, levels, [s[0] for s in stages])

    lp = None
    if use_lp:
        t = _time.perf_counter()
        lp = LPRelaxation(rm)
        timings["lp_build"] = _time.perf_counter() - t

    for k, (name, maximise, expr, lvl) in enumerate(stages):
        cut_added = False
        if lp is not None and lvl is not None:
            b = lp.bound(lvl.terms, lvl.constant, maximise)
            if b is not None:
                cut = integral_cut_value(b, maximise)
                out.lp_bounds[name] = round(b, 6)
                # Sanity check: the cut must not exclude a known feasible solution
                # (the greedy roster for stage 1, the previous stage's solution after).
                if out.last_good is not None:
                    known = _value(out.last_good, expr)
                else:
                    known = _expr_value_from_routes(rm, lvl, g_routes)
                if known <= cut if maximise else known >= cut:
                    rm.model.add(expr <= cut if maximise else expr >= cut)
                    cut_added = True
                else:
                    out.notes.append(f"LP bound for {name} rejected (excludes a known feasible value)")
        if maximise:
            rm.model.maximize(expr)
        else:
            rm.model.minimize(expr)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = scfg.time_limit_seconds
        solver.parameters.num_workers = scfg.num_workers
        solver.parameters.random_seed = scfg.random_seed
        solver.parameters.log_search_progress = scfg.log_search_progress
        ts = _time.perf_counter()
        code = solver.solve(rm.model)
        out.times[name] = round(_time.perf_counter() - ts, 4)
        status = _status_name(code)
        out.status[name] = status
        if code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            val = _value(solver, expr)
            out.values[name] = val
            # Report the tighter of CP-SAT's own bound and the LP bound.
            bound = solver.best_objective_bound
            if name in out.lp_bounds:
                lpb = integral_cut_value(out.lp_bounds[name], maximise)
                bound = min(bound, lpb) if maximise else max(bound, lpb)
            out.bounds[name] = bound
            if code == cp_model.FEASIBLE and name in out.lp_bounds and round(bound) == val:
                # Incumbent equals a valid upper (lower) bound: optimality proven.
                out.status[name] = "OPTIMAL"
                out.notes.append(f"{name}: optimality proven by the LP bound (CP-SAT stopped at the time limit)")
            out.last_good = solver
            if k + 1 < len(stages):
                # Fix this level at the value found before optimising the next.
                rm.model.add(expr >= val if maximise else expr <= val)
                if lp is not None and lvl is not None:
                    lp.add_level_constraint(lvl.terms, lvl.constant, maximise, val)
                _apply_hint_from_solver(rm, solver)
        else:
            if code == cp_model.INFEASIBLE and cut_added:
                out.cut_suspect = True
            if k == 0:
                out.overall = status
            break
    return out


def _expr_value_from_routes(rm: RosteringModel, lvl, routes) -> int:
    on = set()
    for cid, route in routes.items():
        on.update((cid, d) for d in route)
    on_index = {rm.x[k].Index() for k in on if k in rm.x}
    seq_arcs = set()
    for cid, route in routes.items():
        seq = [SOURCE] + route + [SINK]
        seq_arcs.update((cid, a, b) for a, b in zip(seq, seq[1:]))
    on_index |= {rm.arc_lits[k].Index() for k in seq_arcs if k in rm.arc_lits}
    if rm.full:
        staffed: dict[str, int] = {}
        for _, d in on:
            staffed[d] = staffed.get(d, 0) + 1
        for did, f in rm.full.items():
            if staffed.get(did, 0) >= rm.instance.duty(did).demand:
                on_index.add(f.Index())
    return lvl.constant + sum(c for c, v in lvl.terms if v.Index() in on_index)


def _routes_to_solution(cands: CandidateSet, routes: dict[str, list[str]]):
    """Assignments, routes and positioning legs for a roster given as routes."""

    assignments, positioning = [], []
    for cid, route in sorted(routes.items()):
        arcs = {(a.tail, a.head): a for a in cands.crews[cid].arcs}
        seq = [SOURCE] + route + [SINK]
        for tail, head in zip(seq, seq[1:]):
            for leg in arcs[(tail, head)].legs:
                positioning.append(
                    {
                        "crew_id": cid,
                        "after": "" if tail == SOURCE else tail,
                        "before": "" if head == SINK else head,
                        "from_location": leg.from_location,
                        "to_location": leg.to_location,
                        "travel_minutes": leg.travel_minutes,
                        "cost": leg.cost,
                        "base_return_reason": arcs[(tail, head)].base_reason or "",
                    }
                )
        for did in route:
            assignments.append(Assignment(cid, did, cid in cands.instance.duty(did).assigned_crew))
    return assignments, {c: list(r) for c, r in routes.items()}, positioning


def solve_instance(
    instance: Instance,
    model_config: Optional[ModelConfig] = None,
    solver_config: Optional[SolverConfig] = None,
) -> RunResult:
    if model_config is None and "model_config" in instance.metadata:
        # Rules derived from the instance's own data (constraints_df).
        model_config = model_config_from_dict(dict(instance.metadata["model_config"]))
    mcfg = model_config or ModelConfig()
    scfg = solver_config or SolverConfig()
    mcfg.validate()
    t0 = _time.perf_counter()
    timings: dict[str, float] = {}

    issues = validate_instance(instance, mcfg)
    if has_errors(issues):
        sol = Solution([], "INPUT_ERROR")
        return RunResult(instance, mcfg, scfg, issues, sol, timings={"total": _time.perf_counter() - t0})

    t = _time.perf_counter()
    cands = generate_candidates(instance, mcfg)
    timings["candidate_generation"] = _time.perf_counter() - t

    t = _time.perf_counter()
    g_routes = greedy_routes(cands)
    g_pairs = [(cid, did) for cid, r in g_routes.items() for did in r]
    g_report = validate_solution(instance, mcfg, g_pairs)
    timings["greedy"] = _time.perf_counter() - t
    greedy = {
        "covered_units": g_report.coverage["covered_units"],
        "coverage_pct": g_report.coverage["coverage_pct"],
        "validation_passed": g_report.passed,
        "n_violations": len(g_report.violations),
    }

    use_lp = scfg.use_lp_bound and mcfg.objective_mode == "lexicographic"
    t_solve = _time.perf_counter()
    staged = _run_stages(cands, scfg, g_routes, use_lp, timings)
    if staged.cut_suspect:
        # An LP cut can only make the model infeasible through numerical error;
        # never trust it in that case: rebuild and solve without cuts.
        staged = _run_stages(cands, scfg, g_routes, False, timings)
        staged.notes.append("LP-bound cut made a stage infeasible; re-solved without LP cuts")
    timings["solve"] = _time.perf_counter() - t_solve
    rm, levels, last_good = staged.rm, staged.levels, staged.last_good
    stage_status, best_bounds = staged.status, staged.bounds
    # Values at the end of each stage. A later stage can still *improve* an
    # earlier level that was not proven optimal (it is only constrained to stay
    # >= the value found), so the reported objective values are recomputed from
    # the final solution below.
    stage_values = dict(staged.values)
    objective_values: dict[str, float] = {}
    stages = staged.stages
    overall = staged.overall

    if last_good is not None:
        statuses = set(stage_status.values())
        overall = "OPTIMAL" if statuses == {"OPTIMAL"} else "FEASIBLE"
        assignments, routes, positioning = _extract(rm, last_good)
        for lvl in levels:  # every level's value in the final solution, trivial ones included
            objective_values[lvl.name] = _value(last_good, lvl.expr())
    elif g_report.passed and g_routes and overall == "UNKNOWN":
        # CP-SAT found nothing within the time limit, but the greedy roster is
        # legal (checked by the independent validator): return it, clearly
        # labelled, rather than an empty answer.
        overall = "HEURISTIC_ONLY"
        assignments, routes, positioning = _routes_to_solution(cands, g_routes)
        objective_values["coverage"] = g_report.coverage["covered_units"]
        if "coverage" in staged.lp_bounds:
            best_bounds["coverage"] = integral_cut_value(staged.lp_bounds["coverage"], True)
        staged.notes.append("CP-SAT found no solution in the time limit; returning the validated greedy roster")
    else:
        assignments, routes, positioning = [], {}, []

    stats = dict(cands.stats)
    stats.update(rm.stats)
    stats["stage_seconds"] = staged.times
    stats["lp_bounds"] = staged.lp_bounds
    stats["stage_objective_values"] = stage_values
    stats["notes"] = staged.notes
    stats["active_objective_levels"] = list(stages)
    stats["skipped_objective_levels"] = [lvl.name for lvl in levels if lvl.trivial]
    solution = Solution(
        assignments=assignments,
        status=overall,
        objective_values=objective_values,
        best_bounds=best_bounds,
        stage_statuses=stage_status,
        routes=routes,
        positioning=positioning,
        stats=stats,
    )
    t = _time.perf_counter()
    have_solution = last_good is not None or overall == "HEURISTIC_ONLY"
    claimed = objective_values.get("coverage") if have_solution else None
    report = validate_solution(instance, mcfg, assignments, claimed_covered_units=claimed) if have_solution else None
    timings["validation"] = _time.perf_counter() - t
    timings["total"] = _time.perf_counter() - t0
    solution.wall_time_seconds = timings["total"]
    return RunResult(instance, mcfg, scfg, issues, solution, cands, report, greedy, timings)
