"""Greedy constructive heuristic.

Used for two things (as recommended in ``Progress/CP_SAT_vs_MIP_Solvers.pdf``):

1. a **baseline** to compare CP-SAT against in benchmarks, and
2. a **solution hint** passed to CP-SAT (``model.add_hint``).

Algorithm: walk through duties in start-time order. Each crew member keeps a
partial route ending at its last chosen node (initially SOURCE). For each open
demand unit of a duty, pick among crew members that

* have the duty as a candidate,
* have a candidate arc ``last -> duty``,
* would still be able to finish legally (an arc ``duty -> SINK`` exists, or an
  arc ``duty -> next fixed duty`` when the crew member still has fixed duties),
* respect the daily cap,

the one with the *fewest* remaining candidate duties (keep flexible crew for
later); in reassignable mode the originally rostered crew member goes first.
Fixed (existing) duties are appended to their crew member's route when
reached. The greedy uses exactly the arcs of candidate generation, so its
routes satisfy every pairwise rule; it gives no optimality guarantee.
"""

from __future__ import annotations

from collections import defaultdict

from .candidate_generation import SINK, SOURCE, CandidateSet


def greedy_routes(cands: CandidateSet) -> dict[str, list[str]]:
    arcset: dict[str, set[tuple[str, str]]] = {
        cid: {(a.tail, a.head) for a in cc.arcs} for cid, cc in cands.crews.items()
    }
    last: dict[str, str] = {cid: SOURCE for cid in cands.crews}
    routes: dict[str, list[str]] = {cid: [] for cid in cands.crews}
    per_day: dict[tuple[str, object], int] = defaultdict(int)
    cap = cands.config.max_duties_per_day

    fixed_left: dict[str, list[str]] = {}
    for cid, cc in cands.crews.items():
        fixed_left[cid] = sorted(cc.fixed_nodes, key=lambda d: cc.nodes[d].start)
    remaining_options: dict[str, int] = {cid: len(cc.nodes) for cid, cc in cands.crews.items()}

    def closable(cid: str, did: str) -> bool:
        pending = [f for f in fixed_left[cid] if f != did]
        target = pending[0] if pending else SINK
        return (did, target) in arcset[cid]

    for duty in cands.instance.duties:
        did = duty.duty_id
        crews_here = cands.candidates_for_duty(did)
        for cid in crews_here:
            remaining_options[cid] -= 1
        # 1) fixed crew first
        assigned = 0
        for cid in [c for c in cands.crews if did in cands.crews[c].fixed_nodes]:
            if (last[cid], did) in arcset[cid]:
                routes[cid].append(did)
                last[cid] = did
                per_day[(cid, duty.start_date)] += 1
            fixed_left[cid].remove(did)
            assigned += 1
        # 2) open units
        open_units = cands.diagnostics[did].assignable_demand - (
            assigned if cands.config.existing_assignment_mode == "reassignable" else 0
        )
        options = []
        for cid in crews_here:
            node = cands.crews[cid].nodes[did]
            if node.fixed or did in routes[cid]:
                continue
            if (last[cid], did) not in arcset[cid] or not closable(cid, did):
                continue
            if cap is not None and per_day[(cid, duty.start_date)] >= cap:
                continue
            options.append((0 if node.original else 1, remaining_options[cid], cid))
        options.sort()
        for _, _, cid in options[: max(open_units, 0)]:
            routes[cid].append(did)
            last[cid] = did
            per_day[(cid, duty.start_date)] += 1

    # Drop routes whose end is not closable (can only happen with broken fixed data).
    for cid, route in routes.items():
        if route and (route[-1], SINK) not in arcset[cid]:
            while route and (route[-1], SINK) not in arcset[cid] and not cands.crews[cid].nodes[route[-1]].fixed:
                route.pop()
    return {cid: r for cid, r in routes.items() if r}
