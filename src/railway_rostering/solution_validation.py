"""Independent solution validator.

Checks a list of (crew, duty) assignments against the *input data* and the
*enabled hard rules* of a :class:`ModelConfig`, and recomputes coverage.

Independence: this module does **not** import candidate generation, the
constraint modules, the model or the objective. It re-derives shift types,
swing days, rest requirements, connections and base-return obligations with
its own code, directly from the rules as written in the documentation. A bug
in the model's rule encoding therefore shows up as a validation failure
instead of being silently repeated. (It shares only the data classes and the
config object.)

Every check is applied to each crew member's assignments sorted by start time:
the validator does not trust the solver's route order.

Existing assignments in ``fixed`` mode are input facts: node-level rules
(eligibility, off days, start-time window) are not re-checked for them, but
they take part in every sequence rule (overlap, rest, location, base return).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from .config import ModelConfig
from .domain import Assignment, Crew, CrewType, Duty, Instance, ShiftType

UNKNOWN_ID = "UNKNOWN_ID"
DUPLICATE_ASSIGNMENT = "DUPLICATE_ASSIGNMENT"
DEMAND_EXCEEDED = "DEMAND_EXCEEDED"
PARTIAL_STAFFING = "PARTIAL_STAFFING"
EXISTING_DROPPED = "EXISTING_ASSIGNMENT_DROPPED"
EXISTING_COVERAGE_LOST = "EXISTING_COVERAGE_LOST"
INELIGIBLE = "INELIGIBLE"
UNAVAILABLE = "UNAVAILABLE_DATE"
OFF_DAY = "OFF_DAY"
TIME_NOT_ALLOWED = "START_TIME_NOT_ALLOWED"
TIME_PERSISTENCE = "TIME_CHANGE_NOT_PERSISTED"
OVERLAP = "OVERLAP"
INSUFFICIENT_REST = "INSUFFICIENT_REST"
LOCATION = "LOCATION_DISCONTINUITY"
BASE_RETURN = "BASE_RETURN"
DAILY_CAP = "DAILY_CAP"
NEXT_COMMITMENT = "NEXT_COMMITMENT"
COVERAGE_MISMATCH = "COVERAGE_MISMATCH"


@dataclass
class Violation:
    rule: str
    message: str
    crew_id: Optional[str] = None
    duty_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {"rule": self.rule, "crew_id": self.crew_id, "duty_id": self.duty_id, "message": self.message}


@dataclass
class ValidationReport:
    passed: bool
    violations: list[Violation]
    rules_checked: dict[str, str]
    coverage: dict
    claimed: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        counts = Counter(v.rule for v in self.violations)
        return {
            "passed": self.passed,
            "n_violations": len(self.violations),
            "violations_by_rule": dict(sorted(counts.items())),
            "violations": [v.to_dict() for v in self.violations],
            "rules_checked": self.rules_checked,
            "recomputed_coverage": self.coverage,
            "claimed_coverage": self.claimed,
        }


# ---------------------------------------------------------------------------
# Independent re-implementations of the rule semantics
# ---------------------------------------------------------------------------


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _shift(duty: Duty, cfg: ModelConfig) -> ShiftType:
    if duty.shift_type is not None:
        return duty.shift_type
    t = duty.start.time()
    lo, hi = _hhmm(cfg.day_shift_start_from), _hhmm(cfg.day_shift_start_until)
    day = (lo <= t < hi) if lo <= hi else (t >= lo or t < hi)
    return ShiftType.DAY if day else ShiftType.NIGHT


def _pattern(crew: Crew, cfg: ModelConfig) -> Optional[tuple[int, int]]:
    if crew.swing_start is None:
        return None
    dflt = cfg.default_work_off_days.get(crew.crew_type.value, [None, None])
    w = crew.work_days if crew.work_days is not None else dflt[0]
    o = crew.off_days if crew.off_days is not None else dflt[1]
    if w is None or o is None:
        return None
    return int(w), int(o)


def _swing(crew: Crew, d: date, cfg: ModelConfig) -> tuple[bool, Optional[int]]:
    """(is_working_day, swing_number)."""

    p = _pattern(crew, cfg)
    if p is None:
        return True, None
    days = (d - crew.swing_start).days
    cycle = p[0] + p[1]
    k = days // cycle
    return (days - k * cycle) < p[0], k


def _swing_end_inside_horizon(crew: Crew, k: int, instance: Instance, cfg: ModelConfig) -> bool:
    w, o = _pattern(crew, cfg)
    last_working = crew.swing_start + timedelta(days=k * (w + o) + (w - 1))
    day_after = datetime(last_working.year, last_working.month, last_working.day) + timedelta(days=1)
    return day_after <= instance.horizon_end


def _signed_offset(t: time, ref: time) -> int:
    d = (t.hour * 60 + t.minute) - (ref.hour * 60 + ref.minute)
    while d >= 720:
        d -= 1440
    while d < -720:
        d += 1440
    return d


def _rest_needed(prev: Optional[ShiftType], nxt: Optional[ShiftType], cfg: ModelConfig) -> timedelta:
    if cfg.transition_rest_enabled and prev is not None and nxt is not None and prev != nxt:
        return timedelta(hours=cfg.transition_rest_hours)
    return timedelta(hours=cfg.ordinary_rest_hours)


def _travel(instance: Instance, cfg: ModelConfig, a: str, b: Optional[str]) -> Optional[timedelta]:
    """Travel time for a single leg, ``None`` if not possible."""

    if b is None or a == b:
        return timedelta(0)
    if not cfg.positioning_enabled:
        return None
    link = instance.travel.get((a, b))
    return None if link is None else timedelta(minutes=link.travel_minutes)


def _path_time(instance, cfg, a: str, b: Optional[str], via: Optional[str]) -> Optional[timedelta]:
    if via is None:
        return _travel(instance, cfg, a, b)
    t1 = _travel(instance, cfg, a, via)
    t2 = _travel(instance, cfg, via, b)
    if t1 is None or t2 is None:
        return None
    return t1 + t2


def _base_needed(crew, cfg, prev_shift, prev_swing, next_shift, next_swing) -> Optional[str]:
    if crew.base_location is None:
        return None
    if cfg.base_return_at_swing_end and prev_swing is not None and next_swing is not None and prev_swing != next_swing:
        return "swing end"
    if cfg.base_return_on_transition and prev_shift is not None and next_shift is not None and prev_shift != next_shift:
        return "shift transition"
    return None


def _eligible(crew: Crew, duty: Duty, instance: Instance) -> bool:
    if instance.qualifications is None and duty.eligible_crew is None:
        return False
    if instance.qualifications is not None and duty.activity not in instance.qualifications.get(crew.crew_id, ()):
        return False
    if duty.eligible_crew is not None and crew.crew_id not in duty.eligible_crew:
        return False
    return True


def _policy(crew: Crew, cfg: ModelConfig) -> str:
    if crew.crew_type == CrewType.UNSPECIFIED or crew.rostered_start is None:
        return "disabled"
    return cfg.time_change_policy.get(crew.crew_type.value, "disabled")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def validate_solution(
    instance: Instance,
    cfg: ModelConfig,
    assignments: Iterable[Assignment | tuple[str, str]],
    claimed_covered_units: Optional[int] = None,
) -> ValidationReport:
    pairs = [(a.crew_id, a.duty_id) if isinstance(a, Assignment) else tuple(a) for a in assignments]
    v: list[Violation] = []
    duties = {d.duty_id: d for d in instance.duties}
    fixed_mode = cfg.existing_assignment_mode == "fixed"

    # --- identities and duplicates -----------------------------------------
    clean: list[tuple[str, str]] = []
    for cid, did in pairs:
        if cid not in instance.crews or did not in duties:
            v.append(Violation(UNKNOWN_ID, f"unknown crew or duty in assignment ({cid}, {did})", cid, did))
            continue
        clean.append((cid, did))
    for (cid, did), k in Counter(clean).items():
        if k > 1:
            v.append(Violation(DUPLICATE_ASSIGNMENT, f"{cid} assigned {k} times to {did}", cid, did))
    unique = sorted(set(clean))
    pair_set = set(unique)

    # --- demand, existing roster, coverage ----------------------------------
    staff = Counter(did for _, did in unique)
    covered_units = 0
    fully_covered = 0
    for d in instance.duties:
        n = staff.get(d.duty_id, 0)
        e = len(d.assigned_crew)
        if n > d.demand:
            v.append(Violation(DEMAND_EXCEEDED, f"{n} crew on duty with demand {d.demand}", None, d.duty_id))
        if fixed_mode:
            for cid in d.assigned_crew:
                if (cid, d.duty_id) not in pair_set:
                    v.append(Violation(EXISTING_DROPPED, "existing assignment missing from solution", cid, d.duty_id))
        elif n < e:
            v.append(Violation(EXISTING_COVERAGE_LOST, f"{n} crew but {e} were already assigned", None, d.duty_id))
        new = max(min(n, d.demand) - e, 0)
        if cfg.demand_mode == "all_or_nothing":
            if d.open_demand > 0 and 0 < new < d.open_demand:
                v.append(Violation(PARTIAL_STAFFING, f"{n}/{d.demand} crew in all_or_nothing mode", None, d.duty_id))
            if d.open_demand > 0 and new == d.open_demand:
                covered_units += new
        else:
            covered_units += new
        if d.open_demand > 0 and n >= d.demand:
            fully_covered += 1

    # --- per crew sequence checks --------------------------------------------
    by_crew: dict[str, list[Duty]] = defaultdict(list)
    for cid, did in unique:
        by_crew[cid].append(duties[did])

    for cid, ds in by_crew.items():
        crew = instance.crews[cid]
        ds.sort(key=lambda d: (d.start, d.duty_id))
        policy = _policy(crew, cfg)
        allowed = cfg.allowed_offsets_minutes.get(crew.crew_type.value)
        h_work, h_swing = _swing(crew, instance.horizon_start.date(), cfg)
        current_swing = h_swing if h_work else None

        # node-level rules
        for d in ds:
            if fixed_mode and cid in d.assigned_crew:
                continue  # existing assignment: an input fact
            if not _eligible(crew, d, instance):
                v.append(Violation(INELIGIBLE, f"not eligible for {d.activity}", cid, d.duty_id))
            if d.start.date() in crew.unavailable_dates:
                v.append(Violation(UNAVAILABLE, "duty starts on an unavailable date", cid, d.duty_id))
            working, _ = _swing(crew, d.start.date(), cfg)
            if cfg.enforce_swing_work_days and not working:
                v.append(Violation(OFF_DAY, "duty starts on an off day of the swing", cid, d.duty_id))
            if policy != "disabled" and allowed is not None:
                off = _signed_offset(d.start.time(), crew.rostered_start)
                if off not in allowed:
                    v.append(Violation(TIME_NOT_ALLOWED, f"start offset {off} min not in {allowed}", cid, d.duty_id))

        # time-change persistence per swing
        if policy == "persist_after_change":
            groups: dict[Optional[int], list[Duty]] = defaultdict(list)
            for d in ds:
                groups[_swing(crew, d.start.date(), cfg)[1]].append(d)
            for k, group in groups.items():
                in_current = crew.current_start is not None and (k is None or k == current_swing)
                locked: Optional[time] = None
                if in_current and crew.current_start != crew.rostered_start:
                    locked = crew.current_start
                ref = crew.current_start if in_current else crew.rostered_start
                for d in group:
                    t = d.start.time()
                    if locked is not None and t != locked:
                        v.append(
                            Violation(TIME_PERSISTENCE, f"start {t} but time was changed to {locked}", cid, d.duty_id)
                        )
                    elif locked is None and t != ref:
                        locked = t

        # overlap (all pairs)
        for a_i in range(len(ds)):
            for b_i in range(a_i + 1, len(ds)):
                a, b = ds[a_i], ds[b_i]
                if b.start < a.end:
                    v.append(Violation(OVERLAP, f"overlaps {a.duty_id}", cid, b.duty_id))

        # daily cap
        if cfg.max_duties_per_day is not None:
            for day, k in Counter(d.start.date() for d in ds).items():
                if k > cfg.max_duties_per_day:
                    v.append(Violation(DAILY_CAP, f"{k} duties start on {day}", cid, None))

        # consecutive transitions, starting from the initial state
        # Without a prior duty the crew member is free from the horizon start
        # (no rest owed, but any positioning travel still takes time).
        prev_end = crew.prior_duty_end if crew.prior_duty_end is not None else instance.horizon_start
        rest_owed = crew.prior_duty_end is not None
        prev_loc = crew.initial_location
        prev_shift = crew.prior_shift_type
        prev_swing = current_swing
        for d in ds:
            sh = _shift(d, cfg)
            sw = _swing(crew, d.start.date(), cfg)[1]
            via = _base_needed(crew, cfg, prev_shift, prev_swing, sh, sw)
            via_loc = crew.base_location if via else None
            travel = _path_time(instance, cfg, prev_loc, d.start_location, via_loc)
            if travel is None:
                rule = BASE_RETURN if via else LOCATION
                why = f" (must pass base {crew.base_location}: {via})" if via else ""
                v.append(Violation(rule, f"cannot get from {prev_loc} to {d.start_location}{why}", cid, d.duty_id))
                travel = timedelta(0)
            rest = _rest_needed(prev_shift, sh, cfg) if rest_owed else timedelta(0)
            need = max(rest, travel) if cfg.positioning_counts_as_rest else rest + travel
            gap = d.start - prev_end
            if gap < need:
                v.append(
                    Violation(
                        INSUFFICIENT_REST,
                        f"gap {gap} after previous duty < required {need}",
                        cid,
                        d.duty_id,
                    )
                )
            prev_end, prev_loc, prev_shift, prev_swing = d.end, d.end_location, sh, sw
            rest_owed = True

        # end of route
        if ds:
            last = ds[-1]
            if crew.next_commitment_start is not None:
                nsh = crew.next_commitment_shift_type
                nsw = _swing(crew, crew.next_commitment_start.date(), cfg)[1]
                via = _base_needed(crew, cfg, prev_shift, prev_swing, nsh, nsw)
                travel = _path_time(
                    instance, cfg, prev_loc, crew.next_commitment_location, crew.base_location if via else None
                )
                if travel is None:
                    rule = BASE_RETURN if via else NEXT_COMMITMENT
                    v.append(
                        Violation(
                            rule, f"cannot reach next commitment at {crew.next_commitment_location}", cid, last.duty_id
                        )
                    )
                    travel = timedelta(0)
                rest = _rest_needed(prev_shift, nsh, cfg)
                need = max(rest, travel) if cfg.positioning_counts_as_rest else rest + travel
                if crew.next_commitment_start - prev_end < need:
                    v.append(Violation(NEXT_COMMITMENT, "insufficient rest before next commitment", cid, last.duty_id))
            elif crew.base_location is not None:
                must = cfg.base_return_at_horizon_end or (
                    cfg.base_return_at_swing_end
                    and prev_swing is not None
                    and _swing_end_inside_horizon(crew, prev_swing, instance, cfg)
                )
                if must and _travel(instance, cfg, prev_loc, crew.base_location) is None:
                    v.append(
                        Violation(BASE_RETURN, f"ends at {prev_loc}, base is {crew.base_location}", cid, last.duty_id)
                    )

    claimed = {}
    if claimed_covered_units is not None:
        claimed = {"covered_units": claimed_covered_units}
        if claimed_covered_units != covered_units:
            v.append(Violation(COVERAGE_MISMATCH, f"solver claims {claimed_covered_units}, recomputed {covered_units}"))

    rules = {
        "eligibility": "enforced",
        "demand_and_uniqueness": "enforced",
        "existing_assignments": cfg.existing_assignment_mode,
        "overlap": "enforced",
        "ordinary_rest": f"{cfg.ordinary_rest_hours} h",
        "transition_rest": f"{cfg.transition_rest_hours} h" if cfg.transition_rest_enabled else "disabled",
        "location_continuity": "enforced" + (" (positioning allowed)" if cfg.positioning_enabled else ""),
        "swing_work_days": "enforced" if cfg.enforce_swing_work_days else "disabled",
        "time_change_policy": str(cfg.time_change_policy),
        "base_return_at_swing_end": str(cfg.base_return_at_swing_end),
        "base_return_on_transition": str(cfg.base_return_on_transition),
        "base_return_at_horizon_end": str(cfg.base_return_at_horizon_end),
        "daily_cap": str(cfg.max_duties_per_day),
        "co_rules": "not validated (disabled in model)",
    }
    coverage = {
        "covered_units": covered_units,
        "open_units": instance.total_open_demand,
        "coverage_pct": round(100.0 * covered_units / instance.total_open_demand, 2)
        if instance.total_open_demand
        else 100.0,
        "fully_covered_duties": fully_covered,
        "duties_with_open_demand": sum(1 for d in instance.duties if d.open_demand > 0),
        "n_assignments": len(unique),
    }
    return ValidationReport(not v, v, rules, coverage, claimed)
