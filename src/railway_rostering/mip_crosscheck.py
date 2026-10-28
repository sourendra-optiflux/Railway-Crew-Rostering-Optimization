"""Flow-MIP cross-check of the CP-SAT circuit formulation.

The CP-SAT model expresses each crew member's sequence with ``AddCircuit``.
This module builds the textbook alternative on the *same candidate arcs*: a
unit-capacity path flow per crew member, solved by a MIP solver (SCIP or
HiGHS, both bundled with OR-Tools)::

    sum_{a out of SOURCE} f[c,a]        <= 1
    sum_{a into i} f[c,a] = x[c,i] = sum_{a out of i} f[c,a]
    E_i <= sum_c x[c,i] <= D_i,  fixed x = 1, daily cap
    max  sum_i covered_i

(``all_or_nothing`` demand mode is not supported here.) Because both models
share the candidate arcs, agreement of the optimal coverage checks the
*circuit encoding*; candidate generation itself is checked separately by
the brute-force tests and by the independent validator.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ortools.linear_solver import pywraplp

from .candidate_generation import SOURCE, CandidateSet


def solve_flow_mip(cands: CandidateSet, solver_name: str = "SCIP", time_limit_s: float = 60.0) -> dict:
    if cands.config.demand_mode != "partial":
        raise ValueError("flow MIP cross-check supports demand_mode='partial' only")
    solver = pywraplp.Solver.CreateSolver(solver_name)
    if solver is None:
        raise RuntimeError(f"MIP solver {solver_name} not available")
    solver.SetTimeLimit(int(time_limit_s * 1000))

    x: dict[tuple[str, str], pywraplp.Variable] = {}
    by_duty: dict[str, list] = defaultdict(list)
    for cid, cc in cands.crews.items():
        f = {}
        for a in cc.arcs:
            f[(a.tail, a.head)] = solver.BoolVar(f"f[{cid},{a.tail},{a.head}]")
        solver.Add(sum(v for (t, _), v in f.items() if t == SOURCE) <= 1)
        for did, node in cc.nodes.items():
            xv = solver.BoolVar(f"x[{cid},{did}]")
            x[(cid, did)] = xv
            by_duty[did].append(xv)
            solver.Add(sum(v for (_, h), v in f.items() if h == did) == xv)
            solver.Add(sum(v for (t, _), v in f.items() if t == did) == xv)
            if node.fixed:
                solver.Add(xv == 1)
        cap = cands.config.max_duties_per_day
        if cap is not None:
            per_day = defaultdict(list)
            for did, node in cc.nodes.items():
                per_day[node.start_date].append(x[(cid, did)])
            for vars_ in per_day.values():
                if len(vars_) > cap:
                    solver.Add(sum(vars_) <= cap)

    objective_terms = []
    constant = 0
    for d in cands.instance.duties:
        vars_ = by_duty.get(d.duty_id, [])
        n = sum(vars_) if vars_ else 0
        if vars_:
            solver.Add(n <= d.demand)
            if d.assigned_crew:
                solver.Add(n >= len(d.assigned_crew))
            objective_terms.extend(vars_)
        constant -= len(d.assigned_crew)
    solver.Maximize(sum(objective_terms) + constant if objective_terms else solver.Sum([]))
    status = solver.Solve()
    names = {
        pywraplp.Solver.OPTIMAL: "OPTIMAL",
        pywraplp.Solver.FEASIBLE: "FEASIBLE",
        pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
        pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
        pywraplp.Solver.ABNORMAL: "ABNORMAL",
    }
    result: dict = {"status": names.get(status, str(status)), "solver": solver_name}
    if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        covered: Optional[int] = round(solver.Objective().Value()) if objective_terms else 0
        result["covered_units"] = covered
        result["assignments"] = sorted(k for k, v in x.items() if v.solution_value() > 0.5)
        result["best_bound"] = solver.Objective().BestBound() if objective_terms else 0
    return result
