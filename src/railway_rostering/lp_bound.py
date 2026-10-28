"""LP-relaxation bound used to help CP-SAT *prove* optimality.

Observation from the benchmarks (docs/validation_report.md): on the large
synthetic instance CP-SAT finds the optimal coverage in ~1.5 s but needs ~40 s
to close its own bound, while the LP relaxation of the equivalent path-flow
formulation already equals the optimum. This module solves that LP with GLOP
and returns its value, which :mod:`solve` adds to the CP-SAT model as a cut::

    maximise stage:  objective <= floor(LP bound)
    minimise stage:  objective >= ceil(LP bound)

Why this is sound: every solution of the CP-SAT model satisfies the flow rows
below (they are implied by ``AddCircuit``: each assigned duty has exactly one
predecessor and one successor arc, every skipped duty has none, the depot has
either its self-loop or one outgoing arc), and every other row is copied from
the CP-SAT model. So the LP feasible set contains the CP-SAT feasible set,
the LP optimum bounds the CP-SAT optimum, and the cut removes no feasible
solution that could be better. Because the objective is integral, rounding the
bound down (up) is also valid. A small tolerance guards against floating
point noise, and :mod:`solve` re-solves a stage without the cut if it ever
becomes INFEASIBLE.

LP rows (all variables continuous in [0, 1]):

* ``empty[c] + sum_{SOURCE->j} arc = 1`` and ``in(i) = x[c,i] = out(i)``;
* fixed existing assignments ``x = 1``;
* demand ``E_i <= sum_c x[c,i] <= D_i`` (and ``= E_i + open_i * full_i`` in
  all-or-nothing mode);
* daily cap and redundant cliques (same rows as the CP-SAT model);
* constraints fixing earlier lexicographic stages.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from ortools.linear_solver import pywraplp

from .candidate_generation import SINK, SOURCE
from .constraints.time_rest import minimum_possible_rest_minutes
from .model import RosteringModel

TOLERANCE = 1e-6


class LPRelaxation:
    def __init__(self, rm: RosteringModel):
        self.rm = rm
        self.solver = pywraplp.Solver.CreateSolver("GLOP")
        if self.solver is None:  # pragma: no cover - GLOP ships with OR-Tools
            raise RuntimeError("GLOP not available")
        s = self.solver
        self.var_of: dict[int, pywraplp.Variable] = {}

        def lp_var(cp_var, name):
            v = s.NumVar(0.0, 1.0, name)
            self.var_of[cp_var.Index()] = v
            return v

        x = {k: lp_var(v, f"x{k}") for k, v in rm.x.items()}
        arcs = {k: lp_var(v, f"a{k}") for k, v in rm.arc_lits.items()}
        empty = {k: lp_var(v, f"e{k}") for k, v in rm.empty.items()}
        full = {k: lp_var(v, f"f{k}") for k, v in rm.full.items()}

        into: dict[tuple, list] = defaultdict(list)
        out: dict[tuple, list] = defaultdict(list)
        for (cid, tail, head), v in arcs.items():
            out[(cid, tail)].append(v)
            if head != SINK:
                into[(cid, head)].append(v)
        cands = rm.cands
        for cid, cc in cands.crews.items():
            s.Add(empty[cid] + sum(out[(cid, SOURCE)]) == 1)
            for did, node in cc.nodes.items():
                s.Add(sum(into[(cid, did)]) == x[(cid, did)])
                s.Add(sum(out[(cid, did)]) == x[(cid, did)])
                if node.fixed:
                    s.Add(x[(cid, did)] == 1)
            cap = cands.config.max_duties_per_day
            if cap is not None:
                per_day = defaultdict(list)
                for did, node in cc.nodes.items():
                    per_day[node.start_date].append(x[(cid, did)])
                for vs in per_day.values():
                    if len(vs) > cap:
                        s.Add(sum(vs) <= cap)
            if cands.config.add_redundant_cliques:
                min_rest = minimum_possible_rest_minutes(cands.config)
                nodes = list(cc.nodes.values())
                for n in nodes:
                    clique = [m.duty_id for m in nodes if m.start <= n.start < m.end + min_rest]
                    if len(clique) >= 2:
                        s.Add(sum(x[(cid, d)] for d in clique) <= 1)
        by_duty: dict[str, list] = defaultdict(list)
        for (_cid, did), v in x.items():
            by_duty[did].append(v)
        for d in cands.instance.duties:
            vs = by_duty.get(d.duty_id)
            if not vs:
                continue
            n = sum(vs)
            s.Add(n <= d.demand)
            if d.assigned_crew:
                s.Add(n >= len(d.assigned_crew))
            if d.duty_id in full:
                s.Add(n == len(d.assigned_crew) + d.open_demand * full[d.duty_id])

    def _linear(self, terms, constant):
        expr = constant
        for coef, cp_var in terms:
            expr = expr + coef * self.var_of[cp_var.Index()]
        return expr

    def add_level_constraint(self, terms, constant, maximise: bool, value: float) -> None:
        e = self._linear(terms, constant)
        self.solver.Add(e >= value if maximise else e <= value)

    def bound(self, terms, constant, maximise: bool) -> Optional[float]:
        if not terms:
            return float(constant)
        e = self._linear(terms, constant)
        if maximise:
            self.solver.Maximize(e)
        else:
            self.solver.Minimize(e)
        status = self.solver.Solve()
        if status != pywraplp.Solver.OPTIMAL:
            return None
        return self.solver.Objective().Value()


def integral_cut_value(bound: float, maximise: bool) -> int:
    """Round an LP bound to the strongest valid integer bound."""

    return math.floor(bound + TOLERANCE) if maximise else math.ceil(bound - TOLERANCE)
