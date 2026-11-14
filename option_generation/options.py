"""Layer 1: for every open seat, reject the people who cannot fill it; keep the legal options.

Terms
    seat    one activity at one start time on one day (activity_demand_df), with room for `Demand` people.
    swing   one person's run of shifts between two off-blocks (the roster's `Swing` number).
    option  what one row of a swing could become: `keep` it, `fill` a seat, or `ride` home as Excess.

Gap filling rules (data/optiflux_v2/source/rules/gap_filling_rules.md):
    G1  only rows from the solver start date on may change; earlier gaps are locked.
    F1  Excess, Relief and Demand crew of other seats may fill; Demand crew move by at most +-1 h.
    F2  a Demand person who moves leaves their own seat open: it becomes a seat to fill at the next
        chain level. `max_chain` limits how many Demand moves can follow each other.
    F3  start-time pattern: checked between consecutive shifts here (`Rules.can_follow`), and over the
        whole block in the CP-SAT model.
    F4  swings that started before the solver start date, or that are partly on leave, keep their rows.
        (The one exception is an Excess person already on the same seat at the same time: taking the
        seat changes nothing in their day.)

An option survives only if it lies on some complete legal path through its swing (`prune`), so the
CP-SAT model never sees an option that cannot be used.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from .data import PERSON, TRAVEL_TYPES, WORK_TYPES, Data, why_not_eligible

if TYPE_CHECKING:
    from .rules import Rules

FREE_TYPES = ("Excess", "Relief")
RETURN_RIDES = (("A03", "22:00"),)  # the Work Train return seat: Excess on Yarmouth Mainline 22:00


@dataclass(frozen=True)
class Costs:
    """Penalty for each kind of change. Lower is preferred. CP-SAT minimises their sum in stage 2."""

    excess_same_slot: int = 0  # an Excess person already on this seat takes it
    relief_fill: int = 10  # plus 1 per hour between the standby time and the duty
    excess_moved: int = 20  # plus 1 per hour of start change
    demand_moved: int = 40  # plus 1 per hour; a Demand move also opens a seat, so it costs most
    ride: int = 30
    drop_relief: int = 15  # a standby row removed to make room
    drop_excess: int = 25


def seat_key(activity_id: str, start: datetime) -> str:
    return f"{activity_id}@{start:%Y-%m-%dT%H:%M}"


@dataclass(frozen=True)
class Option:
    row_index: int
    kind: str  # keep | fill | ride
    start: datetime
    end: datetime
    start_loc: str
    end_loc: str
    activity_id: str
    demand_id: str = ""
    seat: str = ""  # the seat this option occupies (fill, or keep of a Demand row)
    excess_seat: str = ""  # keep of an Excess row: the seat it is surplus on (rule G5)
    standby: bool = False  # keep of a Relief row: no real duty, no fixed start
    source: str = ""  # Assignment Type of the row
    offset: int = 0  # start change in minutes
    cost: int = 0
    level: int = -1  # chain level of the seat (fill only)
    unchanged: bool = False  # same existing assignment, even when represented as a fill option

    def __post_init__(self) -> None:
        if self.kind == "keep" and not self.unchanged:
            object.__setattr__(self, "unchanged", True)


@dataclass
class Seat:
    key: str
    activity_id: str
    start: datetime
    demand: int
    demand_id: str
    occupants: list[tuple[str, str]] = field(default_factory=list)  # (Assignment ID, user) of Demand rows
    gap_rows: list[str] = field(default_factory=list)  # Assignment IDs of open gap rows
    level: int = -1  # 0 = gap seat; 1, 2, ... = opened by a Demand move; -1 = not a target

    @property
    def open(self) -> int:
        return self.demand - len(self.occupants)


@dataclass
class Swing:
    key: str  # "User|Swing"
    user: str
    number: str
    home: str
    classification: str
    rows: list[dict]
    status: str  # movable | frozen
    reason: str = ""
    earliest_start: datetime | None = None
    latest_end: datetime | None = None
    raw: list[list[Option]] = field(default_factory=list)  # every option, one list per row
    options: list[list[Option]] = field(default_factory=list)  # after pruning
    droppable: list[bool] = field(default_factory=list)

    @property
    def in_model(self) -> bool:
        return any(o.kind != "keep" for opts in self.options for o in opts)


# ---------------------------------------------------------------------------
# Swings and seats
# ---------------------------------------------------------------------------


def build_swings(data: Data, allow_drop: bool) -> list[Swing]:
    rules = data.rules
    work: dict[tuple[str, str], list[dict]] = defaultdict(list)
    travel: dict[str, list[dict]] = defaultdict(list)
    on_leave: set[tuple[str, str]] = set()
    for row in sorted(data.roster, key=lambda r: r["_s"]):
        if row["Assignment Type"] in WORK_TYPES:
            if row[PERSON]:
                work[(row[PERSON], row["Swing"])].append(row)
            else:
                on_leave.add((row["User Id"], row["Swing"]))
        elif row["Assignment Type"] in TRAVEL_TYPES and row[PERSON]:
            travel[row[PERSON]].append(row)

    by_user: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in sorted(work, key=lambda k: work[k][0]["_s"]):
        by_user[key[0]].append(key)

    swings = []
    for user, keys in by_user.items():
        person = data.crew[user]
        off = timedelta(days=rules.off_days[person["Classification"]])
        arrivals = [t["_e"] for t in travel[user] if t["Assignment Type"] == "Travel In"]
        departures = [t["_s"] for t in travel[user] if t["Assignment Type"] == "Travel Out"]
        for i, key in enumerate(keys):
            rows = work[key]
            earliest = [work[keys[i - 1]][-1]["_e"] + off] if i else []
            latest = [work[keys[i + 1]][0]["_s"] - off] if i + 1 < len(keys) else []
            earliest += [t for t in arrivals if t <= rows[0]["_s"]][-1:]
            latest += [t for t in departures if t >= rows[-1]["_e"]][:1]
            if rows[0]["_s"].date() < rules.solver_start:
                status, reason = "frozen", f"swing started before {rules.solver_start} (F4)"
            elif key in on_leave:
                status, reason = "frozen", "swing partly on leave"
            elif any(r["Is Locked"] == "True" for r in rows):
                status, reason = "frozen", "swing has locked rows"
            else:
                status, reason = "movable", ""
            sw = Swing(f"{user}|{key[1]}", user, key[1], person["Depot"], person["Classification"], rows, status,
                       reason, max(earliest, default=None), min(latest, default=None))  # fmt: skip
            sw.droppable = [allow_drop and status == "movable" and changeable(data, r)
                            and r["Assignment Type"] in FREE_TYPES for r in rows]  # fmt: skip
            sw.raw = [[keep_option(data, i, r)] for i, r in enumerate(rows)]
            swings.append(sw)
    return swings


def changeable(data: Data, row: dict) -> bool:
    """G1 + R4: the row is on or after the solver start, inside the horizon, and not locked."""
    return data.rules.solvable(row["_s"].date()) and row["Is Locked"] != "True"


def keep_option(data: Data, index: int, row: dict) -> Option:
    typ = row["Assignment Type"]
    key = seat_key(row["Activity ID"], row["_s"])
    return Option(index, "keep", row["_s"], row["_e"], row["Start Location"], row["End Location"],
                  row["Activity ID"], row["Demand ID"], seat=key if typ == "Demand" else "",
                  excess_seat=key if typ == "Excess" else "", standby=typ == "Relief", source=typ,
                  unchanged=True)  # fmt: skip


def build_seats(data: Data) -> dict[str, Seat]:
    """Every seat from the solver start to the end of the horizon, with who is on it after leave."""
    rules = data.rules
    seats: dict[str, Seat] = {}
    day = rules.solver_start
    while day < rules.horizon_end:
        for (activity_id, shift), d in data.demand.items():
            start = datetime.fromisoformat(f"{day.isoformat()}T{shift}")
            key = seat_key(activity_id, start)
            seats[key] = Seat(key, activity_id, start, int(d["Demand"]), d["Demand ID"])
        day += timedelta(days=1)
    for row in data.roster:
        if row["Assignment Type"] != "Demand":
            continue
        seat = seats.get(seat_key(row["Activity ID"], row["_s"]))
        if seat is None:
            continue
        if row[PERSON]:
            seat.occupants.append((row["Assignment ID"], row[PERSON]))
        elif row["Is Gap"] == "True" and row["Is_locked_gap"] == "False":
            seat.gap_rows.append(row["Assignment ID"])
    return seats


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def clock_hours_apart(a: datetime, b: datetime) -> int:
    minutes = abs((a.hour * 60 + a.minute) - (b.hour * 60 + b.minute))
    return round(min(minutes, 1440 - minutes) / 60)


def try_fill(data: Data, swing: Swing, index: int, seat: Seat, costs: Costs) -> tuple[Option | None, str]:
    """The option for row `index` of `swing` to take `seat`, or (None, reason it is rejected)."""
    row = swing.rows[index]
    typ = row["Assignment Type"]
    offset = int((seat.start - row["_s"]).total_seconds() // 60)
    same_seat = typ == "Excess" and offset == 0 and row["Activity ID"] == seat.activity_id
    if not changeable(data, row):
        return None, "row before the solver start or locked (G1)"
    if swing.status != "movable" and not same_seat:
        return None, swing.reason
    if (data.rules.residential_start_restriction
        and swing.classification == "Residential"
        and not same_seat
        and not data.rules.residential_start_allowed(seat.start)):
        return None, "Residential crew cannot start a shift between 22:00 and 02:00"
    if typ == "Relief":
        if row["_s"].date() != seat.start.date():
            return None, "different day"
        cost = costs.relief_fill + clock_hours_apart(row["_s"], seat.start)
    elif typ == "Excess":
        if offset not in data.rules.excess_offsets:
            return None, "start change beyond the allowed offsets"
        cost = costs.excess_same_slot if same_seat else costs.excess_moved + abs(offset) // 60
    else:  # Demand
        if seat_key(row["Activity ID"], row["_s"]) == seat.key:
            return None, "already on this seat"
        if offset not in data.rules.demand_offsets:
            return None, "start change beyond +-1 h (F1)"
        cost = costs.demand_moved + abs(offset) // 60
    reason = why_not_eligible(data, swing.user, seat.activity_id, seat.start.date())
    if reason:
        return None, reason
    activity = data.activities[seat.activity_id]
    end = seat.start + timedelta(hours=data.rules.shift_hours)
    return Option(index, "fill", seat.start, end, activity["Start Depot"], activity["End Depot"], seat.activity_id,
                  seat.demand_id, seat=seat.key, source=typ, offset=offset, cost=cost,
                  level=seat.level, unchanged=same_seat), ""  # fmt: skip


def ride_options(data: Data, swing: Swing, index: int, target_keys: set[str], costs: Costs) -> list[Option]:
    """A trip across the line as Excess on a seat that is already covered, to get home or into position."""
    row = swing.rows[index]
    rides = []
    for activity_id, shift in RETURN_RIDES:
        start = datetime.fromisoformat(f"{row['_s'].date().isoformat()}T{shift}")
        key = seat_key(activity_id, start)
        if (data.rules.residential_start_restriction and swing.classification == "Residential"
                and not data.rules.residential_start_allowed(start)):
            continue
        if key in target_keys or why_not_eligible(data, swing.user, activity_id, start.date()):
            continue
        activity = data.activities[activity_id]
        rides.append(Option(index, "ride", start, start + timedelta(hours=data.rules.shift_hours),
                            activity["Start Depot"], activity["End Depot"], activity_id,
                            data.demand[(activity_id, shift)]["Demand ID"], excess_seat=key,
                            source=row["Assignment Type"], cost=costs.ride))  # fmt: skip
    return rides


# ---------------------------------------------------------------------------
# Pruning: keep options that sit on a complete legal path through the swing
# ---------------------------------------------------------------------------


def can_open(rules: Rules, swing, option: Option) -> bool:
    if option.start_loc != swing.home or (swing.earliest_start and option.start < swing.earliest_start):
        return False
    return swing.classification != "Residential" or rules.is_day(option.start)


def can_close(swing, option: Option) -> bool:
    return option.end_loc == swing.home and not (swing.latest_end and option.end > swing.latest_end)


def skippable(swing, first: int, last: int) -> bool:
    """True if every row strictly between positions `first` and `last` may be dropped."""
    return all(swing.droppable[i] for i in range(first + 1, last))


def prune(data: Data, swing: Swing) -> None:
    rules, count = data.rules, len(swing.raw)
    reach_start: set[Option] = set()
    for i, options in enumerate(swing.raw):
        for option in options:
            if skippable(swing, -1, i) and can_open(rules, swing, option):
                reach_start.add(option)
                continue
            for j in range(i):
                if skippable(swing, j, i) and any(p in reach_start and rules.can_follow(p, option) for p in swing.raw[j]):
                    reach_start.add(option)
                    break
    reach_end: set[Option] = set()
    for i in range(count - 1, -1, -1):
        for option in swing.raw[i]:
            if skippable(swing, i, count) and can_close(swing, option):
                reach_end.add(option)
                continue
            for j in range(i + 1, count):
                if skippable(swing, i, j) and any(n in reach_end and rules.can_follow(option, n) for n in swing.raw[j]):
                    reach_end.add(option)
                    break
    swing.options = [[o for o in options if o in reach_start and o in reach_end] for options in swing.raw]


# ---------------------------------------------------------------------------
# The whole layer
# ---------------------------------------------------------------------------


@dataclass
class Generated:
    swings: list[Swing]
    seats: dict[str, Seat]
    rejections: Counter  # (seat key, reason) -> rows rejected, for gap seats
    pruned: Counter  # seat key -> fill options removed by pruning
    levels: int  # chain levels actually used


def generate(data: Data, costs: Costs, max_chain: int, allow_drop: bool, allow_rides: bool) -> Generated:
    swings = build_swings(data, allow_drop)
    seats = build_seats(data)
    rows_by_day: dict[date, list[tuple[Swing, int]]] = defaultdict(list)
    for sw in swings:
        for i, row in enumerate(sw.rows):
            rows_by_day[row["_s"].date()].append((sw, i))
    rejections: Counter = Counter()
    pruned: Counter = Counter()

    frontier = [s for s in seats.values() if s.gap_rows and s.open > 0]
    for s in frontier:
        s.level = 0
    level = 0
    while frontier:
        touched: set[int] = set()
        for seat in frontier:
            day = seat.start.date()
            near = rows_by_day[day] + rows_by_day[day - timedelta(days=1)] + rows_by_day[day + timedelta(days=1)]
            for sw, i in near:
                row = sw.rows[i]
                if row["Assignment Type"] == "Demand" and level >= max_chain:
                    continue  # F2: a Demand move needs its own seat refilled, one level deeper
                option, reason = try_fill(data, sw, i, seat, costs)
                if option is None:
                    if seat.level == 0 and row["_s"].date() == day:
                        rejections[(seat.key, reason)] += 1
                    continue
                sw.raw[i].append(option)
                touched.add(id(sw))
        for sw in swings:
            if id(sw) in touched:
                prune(data, sw)
        # F2: seats left by Demand crew who now have a fill option become the next level's targets.
        nxt = []
        for sw in swings:
            if id(sw) not in touched:
                continue
            for i, opts in enumerate(sw.options):
                if sw.rows[i]["Assignment Type"] == "Demand" and any(o.kind == "fill" for o in opts):
                    own = seats.get(seat_key(sw.rows[i]["Activity ID"], sw.rows[i]["_s"]))
                    if own is not None and own.level < 0:
                        own.level = level + 1
                        nxt.append(own)
        frontier = nxt
        level += 1

    target_keys = {k for k, s in seats.items() if s.level >= 0}
    for sw in swings:
        if allow_rides and sw.status == "movable" and any(o.kind == "fill" for opts in sw.raw for o in opts):
            for i, row in enumerate(sw.rows):
                if changeable(data, row) and row["Assignment Type"] in FREE_TYPES:
                    sw.raw[i] += ride_options(data, sw, i, target_keys, costs)
        prune(data, sw)
        for raw, kept in zip(sw.raw, sw.options):
            for o in set(raw) - set(kept):
                if o.kind == "fill":
                    pruned[o.seat] += 1
    return Generated(swings, seats, rejections, pruned, level)
