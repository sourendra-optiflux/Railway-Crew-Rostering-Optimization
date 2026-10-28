"""Candidate generation: the sparse graph the CP-SAT model is built on.

For every crew member ``c`` this module computes

* **nodes** - the duties ``c`` may perform at all (eligible, available on that
  date, allowed start time, CO hook), and
* **arcs** - which ordered pairs ``i -> j`` may be *consecutive* duties of
  ``c`` (rest, transition rest, location continuity / positioning, daily cap,
  time-change persistence, base return, CO hook), plus start arcs
  ``SOURCE -> i`` (first duty, from the initial state) and end arcs
  ``i -> SINK`` (last duty, towards the next commitment / base).

Every *pairwise* hard rule is therefore decided here, in plain Python, before
the solver sees the problem. The CP-SAT model (``model.py``) only has to pick
one path ``SOURCE -> i1 -> ... -> ik -> SINK`` per crew member through these
arcs (via ``AddCircuit``) and enforce the non-pairwise rules (demand, daily
cap > 1, fixed assignments).

Nodes that are not on any ``SOURCE -> SINK`` path are pruned (they could never
be assigned), and per-duty diagnostics record how many crew survive each
filter, which is how uncovered duties are explained in the outputs.

Times are integer minutes relative to ``instance.horizon_start``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional

from .config import ModelConfig
from .constraints import base_return, co_rules, eligibility, location, swing_rules, time_rest
from .constraints.location import Connection, Leg
from .domain import Crew, Instance, ShiftType

SOURCE = "__source__"
SINK = "__sink__"

# Reason codes for duties that can never be (fully) covered.
NO_ELIGIBLE_CREW = "NO_ELIGIBLE_CREW"
NO_AVAILABLE_CREW = "NO_AVAILABLE_CREW"
NO_TIME_COMPATIBLE_CREW = "NO_TIME_COMPATIBLE_CREW"
BLOCKED_BY_CO_RULE = "BLOCKED_BY_CO_RULE"
NO_FEASIBLE_SEQUENCE = "NO_FEASIBLE_SEQUENCE"
NOT_SELECTED = "NOT_SELECTED"
INSUFFICIENT_CANDIDATES = "INSUFFICIENT_CANDIDATES"

REASON_TEXT = {
    NO_ELIGIBLE_CREW: "No crew member is eligible for this duty's activity / eligible list.",
    NO_AVAILABLE_CREW: "Eligible crew exist, but none is on a working (non-off, non-leave) day.",
    NO_TIME_COMPATIBLE_CREW: "Eligible, available crew exist, but none may start at this time "
    "(lift-up/layback or time-change persistence).",
    BLOCKED_BY_CO_RULE: "All remaining candidates are excluded by a CO rule.",
    NO_FEASIBLE_SEQUENCE: "Candidates exist, but none can reach the duty from their initial "
    "state and still finish legally (location, rest, base return or next commitment).",
    INSUFFICIENT_CANDIDATES: "Fewer feasible candidates than open demand units.",
    NOT_SELECTED: "Feasible candidates existed, but covering this duty would have cost "
    "coverage elsewhere (the optimiser used them for other duties).",
}


def to_minutes(dt: datetime, origin: datetime) -> int:
    return int((dt - origin).total_seconds() // 60)


@dataclass(frozen=True)
class Node:
    """Duty ``duty_id`` as a candidate for one particular crew member."""

    duty_id: str
    start: int
    end: int
    start_location: str
    end_location: str
    shift: ShiftType
    start_date: date
    swing: Optional[int]
    tod: time
    fixed: bool = False
    original: bool = False
    time_changed: bool = False


@dataclass(frozen=True)
class Arc:
    """A permitted 'consecutive duties' link for one crew member."""

    tail: str
    head: str
    legs: tuple[Leg, ...] = ()
    base_reason: Optional[str] = None

    @property
    def cost(self) -> float:
        return sum(leg.cost for leg in self.legs)

    @property
    def n_positioning(self) -> int:
        return len(self.legs)


@dataclass
class CrewCandidates:
    crew: Crew
    nodes: dict[str, Node]
    arcs: list[Arc]
    current_swing: Optional[int]

    @property
    def fixed_nodes(self) -> list[str]:
        return [n.duty_id for n in self.nodes.values() if n.fixed]


@dataclass
class DutyDiagnostics:
    duty_id: str
    assignable_demand: int
    n_considered: int = 0
    n_eligible: int = 0
    n_available: int = 0
    n_time_ok: int = 0
    n_co_ok: int = 0
    n_reachable: int = 0
    candidate_crew: list[str] = field(default_factory=list)

    def structural_reason(self) -> Optional[str]:
        """Why this duty cannot be fully covered regardless of other duties."""

        if self.assignable_demand == 0:
            return None
        if self.n_eligible == 0:
            return NO_ELIGIBLE_CREW
        if self.n_available == 0:
            return NO_AVAILABLE_CREW
        if self.n_time_ok == 0:
            return NO_TIME_COMPATIBLE_CREW
        if self.n_co_ok == 0:
            return BLOCKED_BY_CO_RULE
        if self.n_reachable == 0:
            return NO_FEASIBLE_SEQUENCE
        if self.n_reachable < self.assignable_demand:
            return INSUFFICIENT_CANDIDATES
        return None


@dataclass
class CandidateSet:
    instance: Instance
    config: ModelConfig
    crews: dict[str, CrewCandidates]
    diagnostics: dict[str, DutyDiagnostics]
    issues: list[str]
    stats: dict

    def candidates_for_duty(self, duty_id: str) -> list[str]:
        return [cid for cid, cc in self.crews.items() if duty_id in cc.nodes]


# --------------------------------------------------------------------------
# Endpoints: a uniform description of "where/when/what" at both ends of an arc.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Endpoint:
    time: Optional[int]  # tail: release time; head: start time. None = unbounded.
    location: Optional[str]  # None = anywhere
    shift: Optional[ShiftType]
    swing: Optional[int]
    rest_applies: bool  # False for a source with no prior duty
    node: Optional[Node] = None


def _connect(
    crew: Crew,
    tail: _Endpoint,
    head: _Endpoint,
    instance: Instance,
    cfg: ModelConfig,
    current_swing: Optional[int],
    base_reason_override: Optional[str] = None,
) -> Optional[tuple[Connection, Optional[str]]]:
    """Return (connection, base_reason) if ``head`` may directly follow ``tail``."""

    tn, hn = tail.node, head.node

    # Daily cap of one duty per start date (cap > 1 is a model constraint).
    if cfg.max_duties_per_day == 1 and tn is not None and hn is not None and tn.start_date == hn.start_date:
        return None

    # Time-change persistence within a swing.
    if tn is not None and hn is not None:
        if not swing_rules.persistence_allows(crew, tn.tod, tn.swing, hn.tod, hn.swing, current_swing, cfg):
            return None

    # Base return between the two (swing end / transition) or at the very end.
    base_reason = base_reason_override
    if base_reason is None:
        base_reason = base_return.base_required_between(crew, tail.shift, tail.swing, head.shift, head.swing, cfg)
    if base_reason is not None:
        conn = location.connection_via(tail.location, crew.base_location, head.location, instance, cfg)
    else:
        conn = location.direct_connection(tail.location, head.location, instance, cfg)
    if conn is None:
        return None

    # Rest + travel timing.
    if head.time is not None and tail.time is not None:
        rest = time_rest.required_rest_minutes(tail.shift, head.shift, cfg) if tail.rest_applies else 0
        travel = conn.travel_minutes
        needed = max(rest, travel) if cfg.positioning_counts_as_rest else rest + travel
        if head.time < tail.time + needed:
            return None

    # CO hook (allows everything while CO rules are disabled).
    tail_duty = instance.duty(tn.duty_id) if tn is not None else None
    head_duty = instance.duty(hn.duty_id) if hn is not None else None
    if co_rules.arc_allowed(crew, tail_duty, head_duty, cfg) is not None:
        return None
    return conn, base_reason


def _node_endpoint_as_tail(n: Node) -> _Endpoint:
    return _Endpoint(n.end, n.end_location, n.shift, n.swing, True, n)


def _node_endpoint_as_head(n: Node) -> _Endpoint:
    return _Endpoint(n.start, n.start_location, n.shift, n.swing, True, n)


def _source_endpoint(crew: Crew, instance: Instance, current_swing: Optional[int]) -> _Endpoint:
    if crew.prior_duty_end is not None:
        t = to_minutes(crew.prior_duty_end, instance.horizon_start)
        return _Endpoint(t, crew.initial_location, crew.prior_shift_type, current_swing, True)
    return _Endpoint(0, crew.initial_location, crew.prior_shift_type, current_swing, False)


def _sink_endpoint(crew: Crew, instance: Instance, cfg: ModelConfig) -> _Endpoint:
    if crew.next_commitment_start is not None:
        t = to_minutes(crew.next_commitment_start, instance.horizon_start)
        sd = swing_rules.swing_day(crew, crew.next_commitment_start.date(), cfg)
        return _Endpoint(t, crew.next_commitment_location, crew.next_commitment_shift_type, sd.swing_index, True)
    return _Endpoint(None, None, None, None, True)


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------


def generate_candidates(instance: Instance, cfg: ModelConfig) -> CandidateSet:
    reassignable = cfg.existing_assignment_mode == "reassignable"
    diagnostics: dict[str, DutyDiagnostics] = {}
    for d in instance.duties:
        assignable = d.demand if reassignable else d.open_demand
        diagnostics[d.duty_id] = DutyDiagnostics(d.duty_id, assignable)

    crews: dict[str, CrewCandidates] = {}
    issues: list[str] = []
    n_arcs_total = 0

    for crew in instance.crews.values():
        current_swing = swing_rules.current_swing_index(crew, instance.horizon_start, cfg)
        nodes: dict[str, Node] = {}
        for d in instance.duties:
            originally_here = crew.crew_id in d.assigned_crew
            fixed = originally_here and not reassignable
            if not fixed and diagnostics[d.duty_id].assignable_demand == 0:
                continue
            diag = diagnostics[d.duty_id]
            sd = swing_rules.swing_day(crew, d.start_date, cfg)
            if not fixed:
                diag.n_considered += 1
                if eligibility.ineligibility_reason(crew, d, instance) is not None:
                    continue
                diag.n_eligible += 1
                if swing_rules.availability_reason(crew, d, cfg) is not None:
                    continue
                diag.n_available += 1
                if swing_rules.time_change_reason(crew, d, sd.swing_index, current_swing, cfg) is not None:
                    continue
                diag.n_time_ok += 1
                if co_rules.candidate_allowed(crew, d, cfg) is not None:
                    continue
                diag.n_co_ok += 1
            nodes[d.duty_id] = Node(
                duty_id=d.duty_id,
                start=to_minutes(d.start, instance.horizon_start),
                end=to_minutes(d.end, instance.horizon_start),
                start_location=d.start_location,
                end_location=d.end_location,
                shift=time_rest.shift_type_of(d, cfg),
                start_date=d.start_date,
                swing=sd.swing_index,
                tod=d.start.time(),
                fixed=fixed,
                original=originally_here,
                time_changed=crew.rostered_start is not None and d.start.time() != crew.rostered_start,
            )
        if not nodes:
            continue

        ordered = sorted(nodes.values(), key=lambda n: (n.start, n.duty_id))
        src = _source_endpoint(crew, instance, current_swing)
        sink = _sink_endpoint(crew, instance, cfg)
        arcs: list[Arc] = []

        for n in ordered:
            res = _connect(crew, src, _node_endpoint_as_head(n), instance, cfg, current_swing)
            if res is not None:
                arcs.append(Arc(SOURCE, n.duty_id, res[0].legs, res[1]))
        for a_idx, a in enumerate(ordered):
            tail = _node_endpoint_as_tail(a)
            for b in ordered[a_idx + 1 :]:
                if b.start <= a.start:
                    continue
                res = _connect(crew, tail, _node_endpoint_as_head(b), instance, cfg, current_swing)
                if res is not None:
                    arcs.append(Arc(a.duty_id, b.duty_id, res[0].legs, res[1]))
            end_reason = None
            if crew.next_commitment_start is None:
                end_reason = base_return.base_required_after_last_duty(crew, a.swing, instance.horizon_end, cfg)
            res = _connect(crew, tail, sink, instance, cfg, current_swing, base_reason_override=end_reason)
            if res is not None:
                arcs.append(Arc(a.duty_id, SINK, res[0].legs, res[1]))

        # Reachability pruning on the DAG (forward from SOURCE, backward to SINK).
        succ: dict[str, list[str]] = {}
        for arc in arcs:
            succ.setdefault(arc.tail, []).append(arc.head)
        fwd = {SOURCE}
        for n in [SOURCE] + [o.duty_id for o in ordered]:
            if n in fwd:
                fwd.update(h for h in succ.get(n, ()) if h != SINK)
        bwd = {SINK}
        for n in reversed([o.duty_id for o in ordered]):
            if any(h in bwd for h in succ.get(n, ())):
                bwd.add(n)
        keep = {n for n in nodes if n in fwd and n in bwd}
        for n in nodes.values():
            if n.fixed and n.duty_id not in keep:
                issues.append(
                    f"existing assignment {crew.crew_id} -> {n.duty_id} cannot be part of any legal "
                    f"sequence for this crew member (model will be infeasible)"
                )
                keep.add(n.duty_id)
        nodes = {k: v for k, v in nodes.items() if k in keep}
        arcs = [a for a in arcs if (a.tail == SOURCE or a.tail in nodes) and (a.head == SINK or a.head in nodes)]
        for n in nodes.values():
            if not n.fixed:
                diagnostics[n.duty_id].n_reachable += 1
                diagnostics[n.duty_id].candidate_crew.append(crew.crew_id)
        if nodes:
            crews[crew.crew_id] = CrewCandidates(crew, nodes, arcs, current_swing)
            n_arcs_total += len(arcs)

    node_counts = [len(cc.nodes) for cc in crews.values()]
    per_duty = [diag.n_reachable for diag in diagnostics.values() if diag.assignable_demand > 0]
    stats = {
        "n_crew": len(instance.crews),
        "n_duties": len(instance.duties),
        "n_crew_with_candidates": len(crews),
        "n_candidate_pairs": sum(node_counts),
        "n_arcs": n_arcs_total,
        "max_candidates_per_crew": max(node_counts, default=0),
        "mean_candidates_per_duty": round(sum(per_duty) / len(per_duty), 2) if per_duty else 0.0,
        "max_candidates_per_duty": max(per_duty, default=0),
        "n_duties_structurally_uncoverable": sum(
            1 for diag in diagnostics.values() if diag.structural_reason() not in (None, INSUFFICIENT_CANDIDATES)
        ),
    }
    return CandidateSet(instance, cfg, crews, diagnostics, issues, stats)
