"""Random instances in the solver's *internal* format (used by the tests).

The data committed under ``data/`` uses the OptiFlux database schema and is
produced by :mod:`railway_rostering.synthetic_db`. This module builds
:class:`Instance` objects directly (crews, duties, eligibility), which is
convenient for randomised tests such as the CP-SAT vs. MIP and greedy-legality
checks.

**All data produced here is synthetic.** It imitates the *structure* described
in the OptiFlux briefing (locations, activities, Relief/Excess crew, swing
patterns, 05:00 / 17:00 shifts, lift-up/layback times, eligibility by
activity) but no value is operational data. Where the briefing does not give
a value (e.g. the location of "Nellore Driver" duties, travel times), the
generator uses a clearly labelled synthetic assumption, recorded in
:data:`ACTIVITY_CATALOG` and in each instance's ``instance.json``.

Generation algorithm (see docs/dataset_design.md for details):

1. Crew: base location -> crew type -> swing pattern and phase -> rostered
   time -> activity qualifications (base-dependent profile) -> initial state
   (mostly at base; some away; some with a prior duty overlapping the horizon
   start; some with a commitment after the horizon; occasional leave day).
2. Duties: activity (weighted) -> date (uniform over the horizon) -> start hour
   (mostly 05:00 / 17:00, some +/-1 h, some arbitrary) -> 12 h duration ->
   demand and priority from the activity -> per-duty eligible list sampled
   from qualified crew (capped at ``max_eligible_per_duty``).
3. Difficulty knobs: ``infeasible_duty_fraction`` gives some duties an
   eligible list containing only *unqualified* crew (a deliberately
   uncoverable duty, like a data inconsistency); the crew/duty ratio controls
   tightness.
4. Existing assignments: a fraction of duties is pre-assigned to an eligible
   crew member, accepted only if the independent validator says that crew
   member's existing roster stays legal.

Same configuration + same seed => byte-identical files.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Optional

from .config import ModelConfig
from .domain import Crew, CrewType, Duty, Instance, ShiftType, TravelLink
from .solution_validation import validate_solution

HOWRAH, YAJPUR, NELLORE = "Howrah", "Yajpur", "Nellore"


@dataclass(frozen=True)
class ActivitySpec:
    name: str
    start_location: str
    end_location: str
    priority: Optional[int]
    demand: int
    weight: float
    source: str


ACTIVITY_CATALOG: list[ActivitySpec] = [
    ActivitySpec("Howrah Mainline", HOWRAH, YAJPUR, 1, 1, 0.24,
                 "specified: HWH->YAJ; Priority 1 specified"),
    ActivitySpec("Yajpur Mainline", YAJPUR, HOWRAH, None, 1, 0.24,
                 "specified: YAJ->HWH; '(2)' in briefing not interpreted, so no priority"),
    ActivitySpec("Howrah Mainline CO", HOWRAH, HOWRAH, None, 1, 0.07,
                 "HWH->HWH from the briefing's ABC example"),
    ActivitySpec("Yajpur Mainline CO", YAJPUR, YAJPUR, None, 1, 0.04,
                 "SYNTHETIC ASSUMPTION: YAJ->YAJ by analogy with Howrah Mainline CO"),
    ActivitySpec("YAJ CLO", YAJPUR, YAJPUR, None, 1, 0.07,
                 "YAJ->YAJ from the briefing example ('Yajpur CLO')"),
    ActivitySpec("Yajpur Crew", YAJPUR, YAJPUR, None, 1, 0.07,
                 "SYNTHETIC ASSUMPTION: local Yajpur duty; '(0, 2, 4, 6, ... even)' not modelled"),
    ActivitySpec("NP Crew", NELLORE, NELLORE, None, 2, 0.08,
                 "SYNTHETIC ASSUMPTION: Nellore location; demand 2 is an interpretation of 'demand 2 at each hour'"),
    ActivitySpec("NP Shed", NELLORE, NELLORE, None, 1, 0.07,
                 "'Nellore and Nellore' in the briefing"),
    ActivitySpec("Nellore Driver", NELLORE, NELLORE, None, 1, 0.12,
                 "SYNTHETIC ASSUMPTION: local Nellore duty"),
]  # fmt: skip

# Base-dependent qualification profiles: activity -> probability.
QUALIFICATION_PROFILES: dict[str, dict[str, float]] = {
    HOWRAH: {
        "Howrah Mainline": 0.85, "Yajpur Mainline": 0.85, "Howrah Mainline CO": 0.7,
        "Yajpur Mainline CO": 0.2, "YAJ CLO": 0.2, "Nellore Driver": 0.05,
    },
    YAJPUR: {
        "Yajpur Mainline": 0.85, "Howrah Mainline": 0.8, "YAJ CLO": 0.7, "Yajpur Crew": 0.7,
        "Yajpur Mainline CO": 0.6, "Howrah Mainline CO": 0.25,
    },
    NELLORE: {
        "Nellore Driver": 0.85, "NP Shed": 0.75, "NP Crew": 0.75, "Howrah Mainline": 0.1,
    },
}  # fmt: skip

# Where an "away" crew member may start (neighbours on the briefing's routes).
NEIGHBOURS = {HOWRAH: [YAJPUR, NELLORE], YAJPUR: [HOWRAH], NELLORE: [HOWRAH]}

# SYNTHETIC positioning links. These are NOT real journey times.
SYNTHETIC_TRAVEL = [
    (HOWRAH, YAJPUR, 360, 1.0),
    (YAJPUR, HOWRAH, 360, 1.0),
    (HOWRAH, NELLORE, 900, 2.0),
    (NELLORE, HOWRAH, 900, 2.0),
]


@dataclass
class SyntheticConfig:
    name: str = "synthetic"
    seed: int = 0
    n_crew: int = 20
    n_duties: int = 30
    horizon_days: int = 7
    start_date: str = "2026-11-01"
    base_weights: dict[str, float] = field(default_factory=lambda: {HOWRAH: 0.45, YAJPUR: 0.35, NELLORE: 0.20})
    relief_fraction: float = 0.4
    max_eligible_per_duty: int = 50
    away_fraction: float = 0.15
    prior_duty_fraction: float = 0.3
    next_commitment_fraction: float = 0.2
    leave_fraction: float = 0.05
    changed_time_fraction: float = 0.05
    existing_assignment_fraction: float = 0.0
    infeasible_duty_fraction: float = 0.0
    # (hours, probability) for the start-hour mixture
    main_start_hours: list[int] = field(default_factory=lambda: [5, 17])
    adjacent_start_hours: list[int] = field(default_factory=lambda: [4, 6, 16, 18])
    p_main_hour: float = 0.6
    p_adjacent_hour: float = 0.25
    duty_hours: float = 12.0


PRESETS: dict[str, SyntheticConfig] = {
    "small": SyntheticConfig(name="small", seed=11, n_crew=20, n_duties=20, horizon_days=5),
    "medium": SyntheticConfig(
        name="medium", seed=22, n_crew=150, n_duties=120, horizon_days=7, existing_assignment_fraction=0.05,
        infeasible_duty_fraction=0.02,
    ),
    "large": SyntheticConfig(
        name="large", seed=33, n_crew=1000, n_duties=300, horizon_days=14, max_eligible_per_duty=50,
        existing_assignment_fraction=0.05, infeasible_duty_fraction=0.02,
    ),
    "tight": SyntheticConfig(
        name="tight", seed=44, n_crew=60, n_duties=200, horizon_days=7, infeasible_duty_fraction=0.05,
    ),
    "xlarge": SyntheticConfig(
        name="xlarge", seed=55, n_crew=1000, n_duties=600, horizon_days=14, max_eligible_per_duty=100,
        existing_assignment_fraction=0.05,
    ),
}  # fmt: skip


def _weighted_choice(rng: random.Random, items: dict[str, float] | list, weights=None):
    if isinstance(items, dict):
        keys = list(items)
        return rng.choices(keys, weights=[items[k] for k in keys], k=1)[0]
    return rng.choices(items, weights=weights, k=1)[0]


def _shift_of_hour(hour: int) -> ShiftType:
    return ShiftType.DAY if 3 <= hour < 15 else ShiftType.NIGHT


def generate_instance(cfg: SyntheticConfig) -> Instance:
    rng = random.Random(cfg.seed)
    d0 = date.fromisoformat(cfg.start_date)
    h_start = datetime.combine(d0, time(0, 0))
    h_end = h_start + timedelta(days=cfg.horizon_days)

    # ---------------- crew ----------------
    crews: dict[str, Crew] = {}
    quals: dict[str, frozenset[str]] = {}
    width = max(4, len(str(cfg.n_crew)))
    for k in range(cfg.n_crew):
        cid = f"C{k + 1:0{width}d}"
        base = _weighted_choice(rng, cfg.base_weights)
        ctype = CrewType.RELIEF if rng.random() < cfg.relief_fraction else CrewType.EXCESS
        work, off = (14, 14) if ctype == CrewType.RELIEF else (6, 6)
        swing_start = d0 - timedelta(days=rng.randrange(work + off))
        if ctype == CrewType.RELIEF:
            rostered_hour = rng.choice(cfg.main_start_hours)
        else:
            rostered_hour = rng.choice(cfg.main_start_hours * 3 + cfg.adjacent_start_hours)
        rostered = time(rostered_hour, 0)
        current = None
        if ctype == CrewType.EXCESS and rng.random() < cfg.changed_time_fraction:
            current = time((rostered_hour + rng.choice([-1, 1])) % 24, 0)
        profile = QUALIFICATION_PROFILES[base]
        q = {act for act, p in profile.items() if rng.random() < p}
        if not q:
            q = {max(profile, key=profile.get)}
        quals[cid] = frozenset(q)
        initial = base
        if rng.random() < cfg.away_fraction:
            initial = rng.choice(NEIGHBOURS[base])
        prior_end = prior_shift = None
        if rng.random() < cfg.prior_duty_fraction:
            prior_end = h_start + timedelta(hours=rng.randint(-12, 4))
            prior_shift = _shift_of_hour((prior_end - timedelta(hours=cfg.duty_hours)).hour)
        nxt = nxt_loc = nxt_shift = None
        if rng.random() < cfg.next_commitment_fraction:
            nxt = h_end + timedelta(hours=rng.randint(0, 24))
            nxt_loc = base
            nxt_shift = _shift_of_hour(nxt.hour)
        leave = frozenset()
        if rng.random() < cfg.leave_fraction:
            leave = frozenset({d0 + timedelta(days=rng.randrange(cfg.horizon_days))})
        crews[cid] = Crew(
            crew_id=cid,
            crew_type=ctype,
            initial_location=initial,
            base_location=base,
            rostered_start=rostered,
            current_start=current,
            swing_start=swing_start,
            work_days=work,
            off_days=off,
            prior_duty_end=prior_end,
            prior_shift_type=prior_shift,
            next_commitment_start=nxt,
            next_commitment_location=nxt_loc,
            next_commitment_shift_type=nxt_shift,
            unavailable_dates=leave,
        )

    qualified_by_activity: dict[str, list[str]] = {a.name: [] for a in ACTIVITY_CATALOG}
    for cid, q in quals.items():
        for act in q:
            qualified_by_activity[act].append(cid)

    # ---------------- duties ----------------
    duties: list[Duty] = []
    weights = [a.weight for a in ACTIVITY_CATALOG]
    width = max(4, len(str(cfg.n_duties)))
    designed_infeasible: list[str] = []
    for k in range(cfg.n_duties):
        did = f"D{k + 1:0{width}d}"
        spec = rng.choices(ACTIVITY_CATALOG, weights=weights, k=1)[0]
        day = d0 + timedelta(days=rng.randrange(cfg.horizon_days))
        u = rng.random()
        if u < cfg.p_main_hour:
            hour = rng.choice(cfg.main_start_hours)
        elif u < cfg.p_main_hour + cfg.p_adjacent_hour:
            hour = rng.choice(cfg.adjacent_start_hours)
        else:
            hour = rng.randrange(24)
        start = datetime.combine(day, time(hour, 0))
        end = start + timedelta(hours=cfg.duty_hours)
        qualified = qualified_by_activity[spec.name]
        if rng.random() < cfg.infeasible_duty_fraction:
            pool = [c for c in crews if c not in set(qualified)]
            eligible = rng.sample(pool, min(len(pool), 5))
            designed_infeasible.append(did)
        else:
            eligible = rng.sample(qualified, min(len(qualified), cfg.max_eligible_per_duty))
        duties.append(
            Duty(
                duty_id=did,
                activity=spec.name,
                start=start,
                end=end,
                start_location=spec.start_location,
                end_location=spec.end_location,
                demand=spec.demand,
                priority=spec.priority,
                eligible_crew=frozenset(eligible),
            )
        )

    travel = {(a, b): TravelLink(a, b, m, c) for a, b, m, c in SYNTHETIC_TRAVEL}
    inst = Instance(cfg.name, crews, duties, h_start, h_end, quals, travel, {})

    # ---------------- existing assignments ----------------
    n_existing = 0
    if cfg.existing_assignment_fraction > 0:
        check_cfg = ModelConfig()
        existing: dict[str, list[tuple[str, str]]] = {}
        chosen = [d for d in inst.duties if d.demand == 1 and d.duty_id not in designed_infeasible]
        rng.shuffle(chosen)
        target = round(cfg.existing_assignment_fraction * cfg.n_duties)
        updated: dict[str, Duty] = {}
        for d in chosen:
            if n_existing >= target:
                break
            options = sorted(d.eligible_crew)
            rng.shuffle(options)
            for cid in options[:10]:
                trial = existing.get(cid, []) + [(cid, d.duty_id)]
                if validate_solution(inst, check_cfg, trial).passed:
                    existing[cid] = trial
                    updated[d.duty_id] = replace(d, assigned_crew=(cid,))
                    n_existing += 1
                    break
        inst = Instance(
            cfg.name, crews, [updated.get(d.duty_id, d) for d in inst.duties], h_start, h_end, quals, travel, {}
        )

    elig_sizes = [len(d.eligible_crew) for d in inst.duties]
    inst.metadata = {
        "synthetic": True,
        "disclaimer": "SYNTHETIC DATA generated by railway_rostering.synthetic - not OptiFlux operational data.",
        "seed": cfg.seed,
        "generator_config": asdict(cfg),
        "activity_catalog": [asdict(a) for a in ACTIVITY_CATALOG],
        "synthetic_travel_note": "travel.csv times are synthetic placeholders, not real journey times",
        "characteristics": {
            "n_crew": cfg.n_crew,
            "n_relief": sum(1 for c in crews.values() if c.crew_type == CrewType.RELIEF),
            "n_excess": sum(1 for c in crews.values() if c.crew_type == CrewType.EXCESS),
            "crew_by_base": {b: sum(1 for c in crews.values() if c.base_location == b) for b in cfg.base_weights},
            "n_crew_away_from_base": sum(1 for c in crews.values() if c.initial_location != c.base_location),
            "n_crew_with_prior_duty": sum(1 for c in crews.values() if c.prior_duty_end is not None),
            "n_crew_with_next_commitment": sum(1 for c in crews.values() if c.next_commitment_start is not None),
            "n_duties": cfg.n_duties,
            "duties_by_activity": {
                a.name: sum(1 for d in inst.duties if d.activity == a.name) for a in ACTIVITY_CATALOG
            },
            "total_demand_units": sum(d.demand for d in inst.duties),
            "open_demand_units": inst.total_open_demand,
            "n_existing_assignments": n_existing,
            "eligible_list_size": {
                "min": min(elig_sizes, default=0),
                "mean": round(sum(elig_sizes) / len(elig_sizes), 2) if elig_sizes else 0,
                "max": max(elig_sizes, default=0),
            },
            "designed_uncoverable_duties": designed_infeasible,
        },
    }
    return inst
