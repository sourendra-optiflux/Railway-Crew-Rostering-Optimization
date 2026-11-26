"""Layer 2: the CP-SAT model. It chooses one option per row from what option_generation/ allowed.

Each swing in the model gets one AddCircuit. A path through the circuit is the sequence of shifts the
person really works, so rest, day/night switches, location, the first-shift rule and return to base are
enforced on consecutive shifts.

Seats: every seat has room for `Demand - Fixed Occupants` in-model people. A Demand person's `keep` uses a
place on their own seat; a `fill` uses a place on the new seat. When a Demand person moves (F2), their own
seat loses its keep and has room for someone else, which is how the chain of moves works.

Start-time pattern (F3): for each swing and each block (its day shifts, its night shifts) the model has a
base start B and a changed start N, at most `Max Start Change Minutes` apart, and a switch point. Every
worked shift before the switch starts at B, every one after it at N. So the start changes at most once.
Relief standby rows have no fixed start and are not part of the pattern.

Stage 1 maximises total demand coverage. Depending on `priority_strategy` (`none`, `weighted`, or
`lexicographic`), optional intermediate stages maximise weighted or per-priority activity-head
coverage after fixing each preceding proven optimum. The final stage fixes all preceding optimal
objectives and minimises assignment cost (from `option_generation.options.Costs`).

CO pairing (soft): every Change Over should happen together with the CO on the reverse lane at the same start
time. For each pair of CO seats that start together, `mismatch = |filled(a) - filled(b)|` is penalised by
`rules.co_pairing_penalty` in the final stage. Violations are allowed, but they cost, so the solver keeps them
as few as it can once coverage is fixed. A CO seat with no reverse-lane seat at its start time has nothing to
pair with and is not penalised.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model
from utils.load_options import ModelSwing, SeatInfo

from option_generation.options import Costs, Option, can_close, can_open, skippable
from option_generation.priority import ActivityHeadLimits, priority_weights_for
from option_generation.rules import Rules


@dataclass
class Result:
    status: str
    cost_status: str
    places_filled: int  # in-model places taken, keeps included
    bound: float
    cost: int | None
    cost_bound: float | None  # CP-SAT bound of the cost stage objective: assignment cost + CO pairing penalty
    seconds: float
    chosen: dict[str, list[Option | None]] = field(default_factory=dict)  # swing key -> option per row (None = dropped)
    stage_statuses: dict[str, str] = field(default_factory=dict)
    stage_values: dict[str, int] = field(default_factory=dict)  # objective value of each stage that ran
    stage_bounds: dict[str, float] = field(default_factory=dict)  # CP-SAT best objective bound of each stage
    co_violations: int | None = None  # unmatched CO seats over all reverse-lane pairs; None = pairing not modelled


def _validate_head_limits(activity_head_limits: dict[str, ActivityHeadLimits]) -> None:
    if not isinstance(activity_head_limits, dict) or any(
        not isinstance(limit, ActivityHeadLimits) for limit in activity_head_limits.values()
    ):
        raise TypeError("activity_head_limits must be a dict[str, ActivityHeadLimits]")


def _option_activity_head(o: Option, seats: dict[str, SeatInfo], head_by_activity: dict[str, str]) -> str:
    if o.activity_head:
        return o.activity_head
    if o.seat and o.seat in seats and getattr(seats[o.seat], "activity_head", ""):
        return seats[o.seat].activity_head
    if o.excess_seat and o.excess_seat in seats and getattr(seats[o.excess_seat], "activity_head", ""):
        return seats[o.excess_seat].activity_head
    if o.activity_id in head_by_activity:
        return head_by_activity[o.activity_id]
    return o.activity_id


def solve(rules: Rules, seats: dict[str, SeatInfo], swings: list[ModelSwing], costs: Costs, time_limit: float,
          workers: int, seed: int, log: bool = False, priority_strategy: str | None = None,
          activity_head_limits: dict[str, ActivityHeadLimits] | None = None,
          co_pairs: list[tuple[str, str]] | None = None) -> Result:  # fmt: skip
    if rules.max_changes not in (0, 1):
        raise SystemExit("error: the model supports Max Start Changes Per Block of 0 or 1")
    priority_strategy = rules.priority_strategy if priority_strategy is None else priority_strategy
    if not isinstance(priority_strategy, str) or priority_strategy not in ("none", "weighted", "lexicographic"):
        raise ValueError("priority_strategy must be one of: none, weighted, lexicographic")
    if activity_head_limits is not None:
        _validate_head_limits(activity_head_limits)
    head_by_activity = {
        s.activity_id: s.activity_head
        for s in seats.values()
        if getattr(s, "activity_id", "") and getattr(s, "activity_head", "")
    }
    model = cp_model.CpModel()
    tracked: list = []
    picks: list[tuple[ModelSwing, list[tuple[Option, object]], list[object | None]]] = []
    at_seat: dict[str, list] = defaultdict(list)
    excess_on: list[tuple[str, object]] = []
    spend: list[tuple[int, object]] = []

    def new_bool(name: str):
        var = model.new_bool_var(name)
        tracked.append(var)
        return var

    for n, sw in enumerate(swings):
        nodes: list[tuple[Option, object]] = []
        arcs: list[tuple[int, int, object]] = []
        dropped: list[object | None] = []
        for i, opts in enumerate(sw.options):
            lits = []
            for o in opts:
                if (rules.residential_start_restriction and sw.classification == "Residential"
                        and not o.unchanged
                        and not rules.residential_start_allowed(o.start)):
                    continue
                lit = new_bool(f"w{n}_r{i}_{o.kind}{len(nodes)}")
                nodes.append((o, lit))
                lits.append(lit)
                arcs.append((len(nodes), len(nodes), lit.Not()))
                spend.append((o.cost, lit))
                if o.seat:
                    at_seat[o.seat].append(lit)
                if o.excess_seat:
                    excess_on.append((o.excess_seat, lit))
            if sw.droppable[i]:
                d = new_bool(f"w{n}_r{i}_drop")
                model.add_exactly_one(lits + [d])
                standby = any(o.standby for o in opts if o.kind == "keep")
                spend.append((costs.drop_relief if standby else costs.drop_excess, d))
                dropped.append(d)
            else:
                model.add_exactly_one(lits)
                dropped.append(None)

        last = len(sw.options)
        for a, (first, _) in enumerate(nodes, start=1):
            if skippable(sw, -1, first.row_index) and can_open(rules, sw, first):
                arcs.append((0, a, new_bool(f"w{n}_open{a}")))
            if skippable(sw, first.row_index, last) and can_close(sw, first):
                arcs.append((a, 0, new_bool(f"w{n}_close{a}")))
            for b, (second, _) in enumerate(nodes, start=1):
                if (first.row_index < second.row_index and skippable(sw, first.row_index, second.row_index)
                        and rules.can_follow(first, second)):  # fmt: skip
                    arcs.append((a, b, new_bool(f"w{n}_{a}_{b}")))
        model.add_circuit(arcs)

        # F3: one start-time change per block, by at most max_change_minutes.
        for is_day in (True, False):
            worked = [(o, lit) for o, lit in nodes if not o.standby and rules.is_day(o.start) == is_day]
            if not worked:
                continue
            minutes = {rules.block_minute(o.start) for o, _ in worked}
            if len(minutes) == 1:
                continue  # every option starts at the same time: nothing can change
            lo, hi = min(minutes), max(minutes)
            base = model.new_int_var(lo, hi, f"w{n}_{is_day}_B")
            new = model.new_int_var(lo, hi, f"w{n}_{is_day}_N")
            tracked += [base, new]
            model.add(new - base <= rules.max_change_minutes)
            model.add(base - new <= rules.max_change_minutes)
            if rules.max_changes == 0:
                model.add(new == base)
            after = [new_bool(f"w{n}_{is_day}_p{i}") for i in range(last)]
            for p, q in zip(after, after[1:]):
                model.add_implication(p, q)  # once switched, stays switched
            for o, lit in worked:
                m = rules.block_minute(o.start)
                model.add(base == m).only_enforce_if([lit, after[o.row_index].Not()])
                model.add(new == m).only_enforce_if([lit, after[o.row_index]])
        if rules.activity_head_max_shifts and activity_head_limits is not None:
            by_head: dict[str, list] = defaultdict(list)
            for o, lit in nodes:
                if o.standby:
                    continue
                head = _option_activity_head(o, seats, head_by_activity)
                if head not in activity_head_limits:
                    raise ValueError(f"missing activity-head shift limits for {head or '<empty>'!r}")
                by_head[head].append(lit)
            for head, head_lits in by_head.items():
                model.add(sum(head_lits) <= activity_head_limits[head].limit_for(sw.classification))
        picks.append((sw, nodes, dropped))

    # Seat capacity bounds the number of demand positions credited to the objective.
    for key, lits in at_seat.items():
        seat = seats[key]
        model.add(sum(lits) <= seat.capacity)
    # G5: an Excess row (or a trip as Excess) may only sit on a seat that is fully covered.
    for key, lit in excess_on:
        seat = seats.get(key)
        if seat is None or seat.capacity == 0:
            continue
        model.add(sum(at_seat.get(key, [])) >= seat.capacity).only_enforce_if(lit)

    # Soft CO pairing: mismatch between the two reverse-lane CO seats that start at the same time.
    co_mismatch: list = []
    if co_pairs and rules.co_pairing_penalty > 0:
        starts: dict[str, dict] = defaultdict(dict)  # Activity ID -> {start: seat key}
        for key, seat in seats.items():
            starts[seat.activity_id][seat.start] = key
        for a, b in co_pairs:
            for start in sorted(starts[a].keys() & starts[b].keys()):
                seat_a, seat_b = seats[starts[a][start]], seats[starts[b][start]]
                filled_a = seat_a.fixed + sum(at_seat.get(seat_a.key, []))
                filled_b = seat_b.fixed + sum(at_seat.get(seat_b.key, []))
                mismatch = model.new_int_var(0, max(seat_a.demand, seat_b.demand), f"co_mismatch_{a}_{b}_{start:%d%H%M}")
                tracked.append(mismatch)
                model.add(mismatch >= filled_a - filled_b)
                model.add(mismatch >= filled_b - filled_a)
                co_mismatch.append(mismatch)

    def run(limit: float):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = limit
        solver.parameters.num_workers = workers
        solver.parameters.random_seed = seed
        solver.parameters.log_search_progress = log
        return solver, solver.solve(model)

    print(f"Model: {len(picks)} swings, {len(tracked)} variables, {len(at_seat)} seats")
    coverage = [lit for lits in at_seat.values() for lit in lits]
    priority_weights = priority_weights_for(seat.priority for seat in seats.values())
    weighted_coverage = sum(
        priority_weights[seats[key].priority] * sum(lits)
        for key, lits in at_seat.items()
    )
    stages: list[tuple[str, object, bool, str]] = [
        ("coverage", sum(coverage), True, "total demand fulfilment"),
    ]
    if priority_strategy == "weighted":
        stages.append(("weighted_priority", weighted_coverage, True, "weighted activity-head priority"))
    elif priority_strategy == "lexicographic":
        for priority in sorted({seat.priority for seat in seats.values()}):
            objective = sum(
                lit
                for key, lits_for_seat in at_seat.items()
                if seats[key].priority == priority
                for lit in lits_for_seat
            )
            stages.append((f"priority_{priority}", objective, True, f"priority {priority} demand fulfilment"))
    assignment_cost = sum(c * v for c, v in spend)
    co_cost = rules.co_pairing_penalty * sum(co_mismatch) if co_mismatch else 0
    stages.append(("cost", assignment_cost + co_cost, False,
                   "assignment cost + CO pairing penalty" if co_mismatch else "assignment cost"))

    stage_statuses = {}
    stage_values = {}
    stage_bounds = {}
    stage_solvers = {}
    total_seconds = 0.0
    final = None
    blocked_stage = None
    for index, (name, objective, maximize, description) in enumerate(stages, start=1):
        if blocked_stage is not None:
            blocked_name, blocked_status, blocked_index = blocked_stage
            status = f"SKIPPED (Stage {blocked_index} {blocked_status})"
            stage_statuses[name] = status
            print(f"Stage {index} (SKIPPED): Stage {blocked_index} was {blocked_status}, not OPTIMAL; "
                  f"{description} was not optimized")
            continue

        model.clear_objective()
        model.maximize(objective) if maximize else model.minimize(objective)
        solver, code = run(time_limit)
        total_seconds += solver.wall_time
        status = solver.status_name(code)
        stage_statuses[name] = status
        print(f"Stage {index} ({status}): {description}", end="")
        if code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            value = solver.value(objective)
            print(f" {value} (bound {solver.best_objective_bound:.0f}), {solver.wall_time:.1f}s")
            stage_values[name] = value
            stage_bounds[name] = solver.best_objective_bound
            final = solver
            stage_solvers[name] = solver
            if index < len(stages):
                if code == cp_model.OPTIMAL:
                    model.add(objective == value)
                else:
                    model.add(objective >= value if maximize else objective <= value)
                model.clear_hints()
                for var in tracked:
                    model.add_hint(var, solver.value(var))
        else:
            print(f", {solver.wall_time:.1f}s")
            blocked_stage = (name, status, index)

    first_solver = stage_solvers.get("coverage")
    if first_solver is None:
        first_status = stage_statuses["coverage"]
        return Result(
            status=first_status,
            cost_status=stage_statuses.get("cost", "NOT RUN"),
            places_filled=0,
            bound=0,
            cost=None,
            cost_bound=None,
            seconds=total_seconds,
            stage_statuses=stage_statuses,
            stage_values=stage_values,
            stage_bounds=stage_bounds,
        )

    best = sum(first_solver.value(lit) for lit in coverage)
    best_bound = first_solver.best_objective_bound
    cost_solver = stage_solvers.get("cost")
    # The reported cost is the assignment cost alone; the CO penalty is reported through `co_violations`.
    penalty = rules.co_pairing_penalty if co_mismatch else 0
    cost_value = round(cost_solver.objective_value - penalty * sum(cost_solver.value(m) for m in co_mismatch)) \
        if cost_solver else None
    cost_bound = cost_solver.best_objective_bound if cost_solver else None
    co_violations = sum(final.value(m) for m in co_mismatch) if co_mismatch else None

    chosen = {}
    for sw, nodes, _dropped in picks:
        per_row: list[Option | None] = [None] * len(sw.options)
        for o, lit in nodes:
            if final.value(lit):
                per_row[o.row_index] = o
        chosen[sw.key] = per_row
    return Result(
        status=stage_statuses["coverage"],
        cost_status=stage_statuses["cost"],
        places_filled=best,
        bound=best_bound,
        cost=cost_value,
        cost_bound=cost_bound,
        chosen=chosen,
        seconds=total_seconds,
        stage_statuses=stage_statuses,
        stage_values=stage_values,
        stage_bounds=stage_bounds,
        co_violations=co_violations,
    )
