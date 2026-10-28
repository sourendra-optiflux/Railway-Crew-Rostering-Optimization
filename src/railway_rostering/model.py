"""Build the CP-SAT model from a :class:`CandidateSet`.

Decision variables
------------------
``x[c, i]``           Boolean - crew member ``c`` performs duty ``i`` (only for
                      candidate pairs).
``arc[c, u, v]``      Boolean - ``v`` directly follows ``u`` in ``c``'s sequence
                      (``u``/``v`` may be SOURCE/SINK).
``empty[c]``          Boolean - ``c`` receives no recovery duty.
``full[i]``           Boolean - duty fully staffed (``all_or_nothing`` mode).

Constraints are added by the modules in :mod:`railway_rostering.constraints`;
the objective is attached by :mod:`railway_rostering.objective`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .candidate_generation import CandidateSet
from .constraints import assignment, sequencing


@dataclass
class RosteringModel:
    cands: CandidateSet
    model: cp_model.CpModel = field(default_factory=cp_model.CpModel)
    x: dict = field(default_factory=dict)
    arc_lits: dict = field(default_factory=dict)
    empty: dict = field(default_factory=dict)
    covered: dict = field(default_factory=dict)
    full: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    @property
    def instance(self):
        return self.cands.instance

    @property
    def config(self):
        return self.cands.config


def build_model(cands: CandidateSet) -> RosteringModel:
    rm = RosteringModel(cands)
    m = rm.model
    for cid, cc in cands.crews.items():
        for did in sorted(cc.nodes):
            rm.x[(cid, did)] = m.new_bool_var(f"x[{cid},{did}]")
    for cc in cands.crews.values():
        sequencing.add_crew_circuit(m, cc, rm.x, rm.arc_lits, rm.empty, cands.config.add_flow_linearization)
    rm.covered, rm.full = assignment.add_demand_constraints(m, cands, rm.x)
    n_fixed = assignment.add_fixed_assignments(m, cands, rm.x)
    n_cap = assignment.add_daily_cap(m, cands, rm.x)
    n_cliques = assignment.add_redundant_cliques(m, cands, rm.x) if cands.config.add_redundant_cliques else 0
    rm.stats = {
        "n_x_vars": len(rm.x),
        "n_arc_vars": len(rm.arc_lits),
        "n_circuits": len(cands.crews),
        "n_fixed_assignments": n_fixed,
        "n_daily_cap_constraints": n_cap,
        "n_redundant_cliques": n_cliques,
    }
    return rm
