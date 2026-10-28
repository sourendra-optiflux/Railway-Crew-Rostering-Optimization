"""Objective levels and how they are combined.

Levels (``ModelConfig.objective_levels``, in priority order):

``coverage``        maximise new covered demand units (default first level).
``priority``        maximise ``sum_i w(priority_i) * covered_i``; with only
                    coverage above it this acts as a tie-breaker that prefers
                    high-priority duties (Howrah Mainline is Priority 1 in the
                    briefing). Put it first to make priority strictly dominant.
``positioning``     minimise total positioning cost (only if positioning is on).
``time_changes``    minimise the number of duties worked at a non-rostered time.
``roster_changes``  minimise original (crew, duty) pairs that were moved
                    (``existing_assignment_mode = "reassignable"`` only).

Mandatory rules are never part of the objective; they are hard constraints.

``objective_mode = "lexicographic"`` solves one stage per non-trivial level,
fixing each earlier level at the value found before optimising the next.
``"weighted"`` builds one weighted sum whose weights make each level dominate
all later ones (weight_k > max possible value of all later levels combined).
Positioning costs are scaled by 100 and rounded because CP-SAT needs integer
coefficients.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import RosteringModel

MAXIMISE = {"coverage": True, "priority": True, "positioning": False, "time_changes": False, "roster_changes": False}
COST_SCALE = 100


@dataclass
class LevelExpr:
    name: str
    maximise: bool
    terms: list[tuple[int, object]]  # (coefficient, literal or expression)
    constant: int = 0
    upper_bound: int = 0  # max absolute value the level can take
    trivial: bool = False  # level cannot change the solution ranking

    def expr(self):
        return sum(c * v for c, v in self.terms) + self.constant


def priority_weight(priority, cfg) -> int:
    if priority is None:
        return cfg.default_priority_weight
    return cfg.priority_weights.get(str(priority), cfg.default_priority_weight)


def build_levels(rm: RosteringModel) -> list[LevelExpr]:
    cfg = rm.config
    inst = rm.instance
    levels: list[LevelExpr] = []
    x_by_duty: dict[str, list] = {}
    for (cid, did), var in rm.x.items():
        x_by_duty.setdefault(did, []).append((cid, var))

    for name in cfg.objective_levels:
        if name == "coverage":
            terms, const, ub = [], 0, 0
            for d in inst.duties:
                if d.duty_id in rm.full:
                    terms.append((d.open_demand, rm.full[d.duty_id]))
                else:
                    terms += [(1, v) for _, v in x_by_duty.get(d.duty_id, [])]
                    const -= len(d.assigned_crew)
                ub += d.open_demand
            levels.append(LevelExpr(name, True, terms, const, ub, trivial=False))
        elif name == "priority":
            terms, const, ub, weights = [], 0, 0, set()
            for d in inst.duties:
                if d.open_demand == 0 and cfg.existing_assignment_mode == "fixed":
                    continue
                w = priority_weight(d.priority, cfg)
                weights.add(w)
                if d.duty_id in rm.full:
                    terms.append((w * d.open_demand, rm.full[d.duty_id]))
                else:
                    terms += [(w, v) for _, v in x_by_duty.get(d.duty_id, [])]
                    const -= w * len(d.assigned_crew)
                ub += w * d.open_demand
            # Equal weights everywhere: priority is just a multiple of coverage.
            levels.append(LevelExpr(name, True, terms, const, ub, trivial=len(weights) <= 1))
        elif name == "positioning":
            terms = []
            for (cid, tail, head), lit in rm.arc_lits.items():
                arc = _arc_lookup(rm, cid, tail, head)
                if arc.legs:
                    terms.append((round(arc.cost * COST_SCALE), lit))
            ub = sum(c for c, _ in terms)
            levels.append(LevelExpr(name, False, terms, 0, ub, trivial=not terms))
        elif name == "time_changes":
            terms = []
            for cid, cc in rm.cands.crews.items():
                for n in cc.nodes.values():
                    if n.time_changed and not n.fixed:
                        terms.append((1, rm.x[(cid, n.duty_id)]))
            levels.append(LevelExpr(name, False, terms, 0, len(terms), trivial=not terms))
        elif name == "roster_changes":
            terms, const = [], 0
            if cfg.existing_assignment_mode == "reassignable":
                for d in inst.duties:
                    for cid in d.assigned_crew:
                        const += 1
                        if (cid, d.duty_id) in rm.x:
                            terms.append((-1, rm.x[(cid, d.duty_id)]))
            levels.append(LevelExpr(name, False, terms, const, const, trivial=not terms and const == 0))
    return levels


_ARC_CACHE_ATTR = "_arc_index"


def _arc_lookup(rm: RosteringModel, cid, tail, head):
    index = getattr(rm, _ARC_CACHE_ATTR, None)
    if index is None:
        index = {(c, a.tail, a.head): a for c, cc in rm.cands.crews.items() for a in cc.arcs}
        setattr(rm, _ARC_CACHE_ATTR, index)
    return index[(cid, tail, head)]


def weighted_objective(levels: list[LevelExpr]):
    """Single maximisation objective that respects the level order."""

    active = [lvl for lvl in levels if not lvl.trivial]
    weight = 1
    weighted_terms = []
    for lvl in reversed(active):
        sign = 1 if lvl.maximise else -1
        weighted_terms.append((sign * weight, lvl))
        weight = weight * (lvl.upper_bound + 1) if lvl.upper_bound > 0 else weight
    return sum(w * lvl.expr() for w, lvl in weighted_terms)
