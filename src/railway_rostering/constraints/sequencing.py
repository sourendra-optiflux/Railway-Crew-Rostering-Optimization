"""Per-crew duty sequencing with CP-SAT ``AddCircuit``.

For one crew member with candidate duties ``1..k`` (node 0 is a depot standing
for both the initial state SOURCE and the final state SINK) we add one
``AddCircuit`` over the arcs

=================  =========================  =================================
arc                literal                    meaning
=================  =========================  =================================
``0 -> 0``         ``empty[c]``               crew member gets no recovery duty
``i -> i``         ``NOT x[c, i]``            duty ``i`` skipped by this crew
``0 -> i``         start arc literal          ``i`` is the first duty
``i -> 0``         end arc literal            ``i`` is the last duty
``i -> j``         arc literal                ``j`` directly follows ``i``
=================  =========================  =================================

Only arcs produced by candidate generation exist, so every legal circuit is
``0 -> i1 -> ... -> ik -> 0`` where each step satisfies every pairwise rule.
Because candidate arcs always go forward in time, the duty nodes cannot form a
cycle without the depot, so the circuit is exactly one chronological path.

Optional redundant flow linearisation (``add_flow_linearization``)::

    sum_{arcs into i} arc = x[c, i] = sum_{arcs out of i} arc
    empty[c] + sum_{arcs out of SOURCE} arc = 1

These rows are implied by ``AddCircuit`` but, as linear constraints, they
give CP-SAT's LP relaxation the (integral) path polytope of each crew
member's DAG, which tightens the coverage bound considerably.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from ..candidate_generation import SINK, SOURCE, CrewCandidates


def add_crew_circuit(
    model: cp_model.CpModel,
    cc: CrewCandidates,
    x: dict[tuple[str, str], cp_model.IntVar],
    arc_lits: dict[tuple[str, str, str], cp_model.IntVar],
    empty: dict[str, cp_model.IntVar],
    add_flow_linearization: bool = True,
) -> None:
    cid = cc.crew.crew_id
    order = sorted(cc.nodes.values(), key=lambda n: (n.start, n.duty_id))
    index = {n.duty_id: k + 1 for k, n in enumerate(order)}

    empty_lit = model.new_bool_var(f"empty[{cid}]")
    empty[cid] = empty_lit
    circuit = [(0, 0, empty_lit)]
    xs = []
    for n in order:
        xv = x[(cid, n.duty_id)]
        xs.append(xv)
        circuit.append((index[n.duty_id], index[n.duty_id], xv.Not()))
        # Redundant links between 'empty' and x (help propagation; V1 had the same).
        model.add_implication(xv, empty_lit.Not())
    model.add_bool_or(xs + [empty_lit])

    for arc in cc.arcs:
        lit = model.new_bool_var(f"arc[{cid},{arc.tail}->{arc.head}]")
        arc_lits[(cid, arc.tail, arc.head)] = lit
        u = 0 if arc.tail == SOURCE else index[arc.tail]
        v = 0 if arc.head == SINK else index[arc.head]
        circuit.append((u, v, lit))
    model.add_circuit(circuit)

    if add_flow_linearization:
        into: dict[str, list] = {n.duty_id: [] for n in order}
        out: dict[str, list] = {n.duty_id: [] for n in order}
        from_source = []
        for arc in cc.arcs:
            lit = arc_lits[(cid, arc.tail, arc.head)]
            if arc.tail == SOURCE:
                from_source.append(lit)
            else:
                out[arc.tail].append(lit)
            if arc.head != SINK:
                into[arc.head].append(lit)
        model.add(empty_lit + sum(from_source) == 1)
        for n in order:
            xv = x[(cid, n.duty_id)]
            model.add(sum(into[n.duty_id]) == xv)
            model.add(sum(out[n.duty_id]) == xv)
