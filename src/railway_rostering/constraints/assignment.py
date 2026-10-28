"""Assignment, demand/coverage, existing-roster and daily-cap constraints.

Coverage accounting (per duty ``i`` with demand ``D_i`` and ``E_i`` crew
already assigned in the input):

* ``n_i = sum_c x[c, i]`` counts every crew member on the duty, existing ones
  included. Uniqueness of a crew member on a duty is automatic (one Boolean
  per pair).
* ``E_i <= n_i <= D_i`` (never over-staff; never drop existing coverage).
* ``covered_i = n_i - E_i`` is the *new* coverage produced by the optimiser.
  With ``demand_mode = "all_or_nothing"`` the stronger
  ``n_i = E_i + (D_i - E_i) * full_i`` is used instead, so a duty counts only
  when fully staffed.
* ``uncovered_i = D_i - n_i`` is reported for every duty.

Existing assignments are hard-fixed (``x = 1``) in ``existing_assignment_mode
= "fixed"``; in ``"reassignable"`` mode only ``n_i >= E_i`` is enforced and the
``roster_changes`` objective level counts how many original pairs were moved.

Daily cap: at most ``max_duties_per_day`` duty starts per crew member per date.
With cap 1 this is already enforced on arcs; it is also added here as a
linear clique because it tightens the LP relaxation.

Redundant cliques: for each crew member and each candidate start time ``t``,
all candidate duties ``j`` with ``start_j <= t < end_j + min_rest`` pairwise
conflict (none can follow another), so ``sum x <= 1``. This does not remove any
legal solution; it only strengthens propagation and the LP bound.
"""

from __future__ import annotations

from collections import defaultdict

from ortools.sat.python import cp_model

from ..candidate_generation import CandidateSet
from .time_rest import minimum_possible_rest_minutes


def add_demand_constraints(
    model: cp_model.CpModel,
    cands: CandidateSet,
    x: dict[tuple[str, str], cp_model.IntVar],
) -> tuple[dict[str, cp_model.LinearExprT], dict[str, cp_model.IntVar]]:
    """Return (covered_units_expr per duty, full-coverage literal per duty)."""

    by_duty: dict[str, list] = defaultdict(list)
    for (_cid, did), var in x.items():
        by_duty[did].append(var)

    covered: dict[str, cp_model.LinearExprT] = {}
    full: dict[str, cp_model.IntVar] = {}
    aon = cands.config.demand_mode == "all_or_nothing"
    for d in cands.instance.duties:
        vars_ = by_duty.get(d.duty_id, [])
        existing = len(d.assigned_crew)
        n_i = sum(vars_) if vars_ else 0
        model.add(n_i <= d.demand)
        if existing:
            model.add(n_i >= existing)
        if aon and d.open_demand > 0:
            f = model.new_bool_var(f"full[{d.duty_id}]")
            model.add(n_i == existing + d.open_demand * f)
            full[d.duty_id] = f
            covered[d.duty_id] = d.open_demand * f
        else:
            covered[d.duty_id] = n_i - existing
    return covered, full


def add_fixed_assignments(model: cp_model.CpModel, cands: CandidateSet, x) -> int:
    count = 0
    for cid, cc in cands.crews.items():
        for did in cc.fixed_nodes:
            model.add(x[(cid, did)] == 1)
            count += 1
    return count


def add_daily_cap(model: cp_model.CpModel, cands: CandidateSet, x) -> int:
    cap = cands.config.max_duties_per_day
    if cap is None:
        return 0
    count = 0
    for cid, cc in cands.crews.items():
        per_day: dict = defaultdict(list)
        for n in cc.nodes.values():
            per_day[n.start_date].append(x[(cid, n.duty_id)])
        for vars_ in per_day.values():
            if len(vars_) > cap:
                model.add(sum(vars_) <= cap)
                count += 1
    return count


def add_redundant_cliques(model: cp_model.CpModel, cands: CandidateSet, x) -> int:
    min_rest = minimum_possible_rest_minutes(cands.config)
    count = 0
    for cid, cc in cands.crews.items():
        nodes = sorted(cc.nodes.values(), key=lambda n: n.start)
        seen: set[frozenset[str]] = set()
        for n in nodes:
            t = n.start
            clique = frozenset(m.duty_id for m in nodes if m.start <= t < m.end + min_rest)
            if len(clique) >= 2 and clique not in seen:
                seen.add(clique)
                model.add(sum(x[(cid, did)] for did in clique) <= 1)
                count += 1
    return count
