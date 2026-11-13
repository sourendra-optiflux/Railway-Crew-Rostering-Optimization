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

Stage 1 fills as many seats as possible (ties broken by activity priority). Stage 2 holds that and makes
the cheapest change to the roster (costs from option_generation.options.Costs).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model
from utils.load_options import ModelSwing, SeatInfo

from option_generation.options import Costs, Option
from option_generation.rules import Rules

SEAT_VALUE = 10_000  # one seat always beats any priority tie-break
LOWEST_PRIORITY = 15


@dataclass
class Result:
    status: str
    cost_status: str
    places_filled: int  # in-model places taken, keeps included
    bound: float
    cost: int | None
    cost_bound: float | None
    seconds: float
    chosen: dict[str, list[Option | None]] = field(default_factory=dict)  # swing key -> option per row (None = dropped)


def _can_open(rules: Rules, sw: ModelSwing, o: Option) -> bool:
    if o.start_loc != sw.home or (sw.earliest_start and o.start < sw.earliest_start):
        return False
    return sw.classification != "Residential" or rules.is_day(o.start)


def _can_close(sw: ModelSwing, o: Option) -> bool:
    return o.end_loc == sw.home and not (sw.latest_end and o.end > sw.latest_end)


def _skippable(sw: ModelSwing, first: int, last: int) -> bool:
    return all(sw.droppable[i] for i in range(first + 1, last))


def solve(rules: Rules, seats: dict[str, SeatInfo], swings: list[ModelSwing], costs: Costs, time_limit: float,
          workers: int, seed: int, log: bool = False) -> Result:  # fmt: skip
    if rules.max_changes not in (0, 1):
        raise SystemExit("error: the model supports Max Start Changes Per Block of 0 or 1")
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
                        and not o.unchanged and o.kind != "keep"
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
            if _skippable(sw, -1, first.row_index) and _can_open(rules, sw, first):
                arcs.append((0, a, new_bool(f"w{n}_open{a}")))
            if _skippable(sw, first.row_index, last) and _can_close(sw, first):
                arcs.append((a, 0, new_bool(f"w{n}_close{a}")))
            for b, (second, _) in enumerate(nodes, start=1):
                if (first.row_index < second.row_index and _skippable(sw, first.row_index, second.row_index)
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
        picks.append((sw, nodes, dropped))

    # Seat room, and coverage weighted by priority (1 = highest).
    coverage_terms = []
    for key, lits in at_seat.items():
        seat = seats[key]
        model.add(sum(lits) <= seat.capacity)
        weight = SEAT_VALUE + LOWEST_PRIORITY - min(seat.priority, LOWEST_PRIORITY)
        coverage_terms += [(weight, lit) for lit in lits]
    # G5: an Excess row (or a trip as Excess) may only sit on a seat that is fully covered.
    for key, lit in excess_on:
        seat = seats.get(key)
        if seat is None or seat.capacity == 0:
            continue
        model.add(sum(at_seat.get(key, [])) >= seat.capacity).only_enforce_if(lit)

    def run(limit: float):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = limit
        solver.parameters.num_workers = workers
        solver.parameters.random_seed = seed
        solver.parameters.log_search_progress = log
        return solver, solver.solve(model)

    print(f"Model: {len(picks)} swings, {len(tracked)} variables, {len(at_seat)} seats")
    coverage = sum(w * t for w, t in coverage_terms)
    model.maximize(coverage)
    s1, st1 = run(time_limit)
    if st1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Result(s1.status_name(st1), "NOT RUN", 0, 0, None, None, s1.wall_time)
    best = round(s1.objective_value)
    print(f"Stage 1 ({s1.status_name(st1)}): {best // SEAT_VALUE} places, {s1.wall_time:.1f}s")

    model.clear_objective()
    model.clear_hints()
    for var in tracked:
        model.add_hint(var, s1.value(var))
    model.add(coverage >= best)
    model.minimize(sum(c * v for c, v in spend))
    s2, st2 = run(time_limit)
    final = s2 if st2 in (cp_model.OPTIMAL, cp_model.FEASIBLE) else s1
    if final is s2:
        print(f"Stage 2 ({s2.status_name(st2)}): cost {s2.objective_value:.0f} "
              f"(bound {s2.best_objective_bound:.0f}), {s2.wall_time:.1f}s")  # fmt: skip
    else:
        print(f"Stage 2 ({s2.status_name(st2)}): no better roster found, keeping stage 1, {s2.wall_time:.1f}s")

    chosen = {}
    for sw, nodes, dropped in picks:
        per_row: list[Option | None] = [None] * len(sw.options)
        for o, lit in nodes:
            if final.value(lit):
                per_row[o.row_index] = o
        chosen[sw.key] = per_row
    return Result(
        status=s1.status_name(st1),
        cost_status=s2.status_name(st2),
        places_filled=best // SEAT_VALUE,
        bound=s1.best_objective_bound / SEAT_VALUE,
        cost=round(s2.objective_value) if final is s2 else None,
        cost_bound=s2.best_objective_bound if final is s2 else None,
        seconds=s1.wall_time + s2.wall_time,
        chosen=chosen,
    )
