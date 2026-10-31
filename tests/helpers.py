"""Builders for tiny hand-checkable instances used across the tests."""

from __future__ import annotations

import itertools
from datetime import date, datetime, time, timedelta

from railway_rostering import ModelConfig, SolverConfig, solve_instance
from railway_rostering.config import model_config_from_dict
from railway_rostering.domain import Crew, CrewType, Duty, Instance, ShiftType, TravelLink
from railway_rostering.solution_validation import validate_solution

H0 = datetime(2026, 11, 1)


def dt(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


def crew(
    cid: str,
    loc: str = "Howrah",
    ctype: str = "UNSPECIFIED",
    base: str | None = None,
    rostered: str | None = None,
    swing_start: str | None = None,
    work: int | None = None,
    off: int | None = None,
    **kw,
) -> Crew:
    if "prior_duty_end" in kw and isinstance(kw["prior_duty_end"], str):
        kw["prior_duty_end"] = dt(kw["prior_duty_end"])
    if "next_commitment_start" in kw and isinstance(kw["next_commitment_start"], str):
        kw["next_commitment_start"] = dt(kw["next_commitment_start"])
    if "current_start" in kw and isinstance(kw["current_start"], str):
        h, m = kw["current_start"].split(":")
        kw["current_start"] = time(int(h), int(m))
    return Crew(
        crew_id=cid,
        crew_type=CrewType(ctype),
        initial_location=loc,
        base_location=base,
        rostered_start=None if rostered is None else time(*map(int, rostered.split(":"))),
        swing_start=None if swing_start is None else date.fromisoformat(swing_start),
        work_days=work,
        off_days=off,
        **kw,
    )


def duty(
    did: str,
    start: str,
    s: str = "Howrah",
    e: str = "Yajpur",
    act: str = "Howrah Mainline",
    hours: float = 12,
    eligible=None,
    shift: str | None = None,
    **kw,
) -> Duty:
    st = dt(start)
    return Duty(
        duty_id=did,
        activity=act,
        start=st,
        end=st + timedelta(hours=hours),
        start_location=s,
        end_location=e,
        eligible_crew=None if eligible is None else frozenset(eligible),
        shift_type=None if shift is None else ShiftType(shift),
        **kw,
    )


def make_instance(crews, duties, quals=None, days: int = 7, travel=None, start: datetime = H0) -> Instance:
    links = {}
    for a, b, minutes, *cost in travel or []:
        links[(a, b)] = TravelLink(a, b, minutes, cost[0] if cost else 1.0)
    q = None if quals is None else {k: frozenset(v) for k, v in quals.items()}
    return Instance(
        "test", {c.crew_id: c for c in crews}, list(duties), start, start + timedelta(days=days), q, links, {}
    )


def solve(inst: Instance, solver: SolverConfig | None = None, **model_overrides):
    # Instances built from DB tables carry their own rules (constraints_df).
    base = dict(inst.metadata.get("model_config") or ModelConfig().to_dict())
    cfg = model_config_from_dict({**base, **model_overrides})
    scfg = solver or SolverConfig(time_limit_seconds=20, num_workers=1, random_seed=1)
    return solve_instance(inst, cfg, scfg)


def covered(result) -> int:
    return result.validation.coverage["covered_units"]


def pairs(result) -> set[tuple[str, str]]:
    return {(a.crew_id, a.duty_id) for a in result.solution.assignments}


def brute_force_max_coverage(inst: Instance, cfg: ModelConfig) -> int:
    """Enumerate every assignment (each duty: a subset of crew of size <= open demand)
    and return the best coverage among those the independent validator accepts."""

    crew_ids = sorted(inst.crews)
    options = []
    for d in inst.duties:
        fixed = list(d.assigned_crew) if cfg.existing_assignment_mode == "fixed" else []
        free = [c for c in crew_ids if c not in fixed]
        opts = []
        for k in range(0, d.open_demand + 1):
            for combo in itertools.combinations(free, k):
                opts.append([(c, d.duty_id) for c in fixed + list(combo)])
        options.append(opts)
    best = -1
    for choice in itertools.product(*options):
        flat = [p for group in choice for p in group]
        rep = validate_solution(inst, cfg, flat)
        if rep.passed:
            best = max(best, rep.coverage["covered_units"])
    return best
