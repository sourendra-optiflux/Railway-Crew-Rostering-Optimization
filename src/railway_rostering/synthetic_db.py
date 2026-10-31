"""Synthetic data generator for the OptiFlux database schema (all 12 tables).

**Everything produced here is synthetic.** Names, IDs, e-mail addresses,
depots, competencies and timings are invented placeholders. Only the table
*structure* follows the OptiFlux database (:data:`railway_rostering.db_schema.DB_TABLES`).
Activity heads are the ones in the supplied ``activity_priority`` list.
Depots, routes, competencies and demand per shift are synthetic assumptions,
recorded in :data:`ACTIVITY_CATALOG`.

How an instance is built (``docs/db_schema.md`` §5):

1. **Activities.** One activities_df row per catalogue entry, plus two Standby
   activities (Relief / Excess availability) and one excluded training
   activity. compliance_matrix_df lists each activity's competencies, and
   activity_demand_df lists crew required per shift (scaled by ``demand_scale``).
2. **Regular (Permanent) crew** staff every demand unit. Each unit has a pool of
   two crew members working alternating 7-day blocks. A ``vacancy_fraction`` of
   slot-days is left unrostered. A ``disruption_fraction`` of permanent crew get
   a disruption (leave, medical, expiring competency, lapsed currency, onsite
   absence, activity restriction), so some of their roster rows become invalid.
   These two mechanisms create the gaps the optimiser has to fill.
3. **Relief / Excess crew** get a depot, a role, a swing calendar written as
   Standby roster rows, a rostered time, qualifications (competencies +
   currency), and some realistic complications: prior duties ending around the
   horizon start, commitments after it, time changes already made, leave,
   onsite location away from their depot, trainees with a mentor, night
   restrictions.
4. **Existing Relief/Excess assignments.** Some open duties are given to an
   eligible Relief/Excess crew member as a roster row. A row is accepted only
   if the independent validator says that crew member's fixed roster stays
   legal. Most are ``Is Locked = Yes``, and a few are unlocked (released at
   load time).

The same configuration and seed always give byte-identical files.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Optional

from .db_schema import Tables, build_instance, model_config_from_constraints, slot_datetimes
from .domain import Instance
from .solution_validation import validate_solution

HASKETT, YARMOUTH, MADISON, NELAWAY, BETHWAY = "Haskett", "Yarmouth", "Madison", "Nelaway", "Bethway"
DEPOTS = [HASKETT, YARMOUTH, MADISON, NELAWAY, BETHWAY]

# The activity_priority list supplied with the schema (row 1 = highest).
ACTIVITY_PRIORITY = [
    "Madison Crew", "NE Task", "Fuel Return", "Bethway Join/FI Crew", "Nelaway Shuttle Driver", "NE Ship",
    "Nelaway Driver", "Fuel Train", "Haskett Mainline", "CAM LOT", "Madison Yard", "Work Train",
    "Yarmouth Mainline", "BY Shed",
]  # fmt: skip

COMPETENCIES = {
    "SAFE-01": "Safeworking Rules",
    "RK-HY": "Route Knowledge Haskett-Yarmouth",
    "RK-MB": "Route Knowledge Madison-Bethway",
    "TR-ML": "Mainline Traction",
    "DG-01": "Dangerous Goods Handling",
    "YD-01": "Yard Operations",
    "SH-01": "Shed Operations",
    "NL-01": "Nelaway Local Operations",
    "WT-01": "Track Work Protection",
}


@dataclass(frozen=True)
class ActivitySpec:
    activity_id: str
    crt_id: str
    name: str
    head: str
    group: str
    type: str
    start_depot: str
    end_depot: str
    roles: tuple[str, ...]
    competencies: tuple[str, ...]
    shifts: tuple[tuple[str, int], ...]  # (shift "HH:MM-HH:MM", base demand)
    mentor_required: bool = False
    currency_days: Optional[int] = None
    can_be_moved: bool = True
    tea_required: bool = False


D, C, S = "Driver", "Conductor", "Shunter"
DAY, NIGHT = "05:00-17:00", "17:00-05:00"
ACTIVITY_CATALOG: list[ActivitySpec] = [
    ActivitySpec("A01", "CRT-1001", "Haskett Mainline", "Haskett Mainline", "Mainline", "Driving", HASKETT, YARMOUTH,
                 (D,), ("SAFE-01", "RK-HY", "TR-ML"), ((DAY, 1), (NIGHT, 1)), currency_days=90, tea_required=True),
    ActivitySpec("A02", "CRT-1002", "Haskett Mainline CO", "Haskett Mainline", "Mainline", "Crew On", HASKETT, HASKETT,
                 (D, C), ("SAFE-01", "RK-HY"), ((NIGHT, 1),)),
    ActivitySpec("A03", "CRT-1003", "Yarmouth Mainline", "Yarmouth Mainline", "Mainline", "Driving", YARMOUTH, HASKETT,
                 (D,), ("SAFE-01", "RK-HY", "TR-ML"), ((DAY, 1), (NIGHT, 1)), currency_days=90, tea_required=True),
    ActivitySpec("A04", "CRT-1004", "Yarmouth Mainline CO", "Yarmouth Mainline", "Mainline", "Crew On", YARMOUTH,
                 YARMOUTH, (D, C), ("SAFE-01", "RK-HY"), ((DAY, 1), (NIGHT, 1))),
    ActivitySpec("A05", "CRT-1005", "CAM LOT", "CAM LOT", "Yard", "Yard", YARMOUTH, YARMOUTH,
                 (D, S), ("SAFE-01", "YD-01"), ((DAY, 1), (NIGHT, 1))),
    ActivitySpec("A06", "CRT-1006", "Madison Crew", "Madison Crew", "Local", "Crew", MADISON, MADISON,
                 (D, C), ("SAFE-01", "YD-01"), ((DAY, 2), (NIGHT, 1))),
    ActivitySpec("A07", "CRT-1007", "Madison Yard", "Madison Yard", "Yard", "Yard", MADISON, MADISON,
                 (S, D), ("SAFE-01", "YD-01"), (("06:00-18:00", 2), ("18:00-06:00", 1))),
    ActivitySpec("A08", "CRT-1008", "Work Train", "Work Train", "Infrastructure", "Driving", MADISON, MADISON,
                 (D,), ("SAFE-01", "TR-ML", "WT-01"), (("07:00-19:00", 1),), mentor_required=True),
    ActivitySpec("A09", "CRT-1009", "Fuel Train", "Fuel Train", "Freight", "Driving", MADISON, BETHWAY,
                 (D,), ("SAFE-01", "TR-ML", "RK-MB", "DG-01"), ((NIGHT, 1),), currency_days=60, tea_required=True),
    ActivitySpec("A10", "CRT-1010", "Fuel Return", "Fuel Return", "Freight", "Driving", BETHWAY, MADISON,
                 (D,), ("SAFE-01", "TR-ML", "RK-MB", "DG-01"), ((DAY, 1),), currency_days=60, tea_required=True),
    ActivitySpec("A11", "CRT-1011", "Bethway Join/FI Crew", "Bethway Join/FI Crew", "Local", "Crew", BETHWAY,
                 BETHWAY, (D, C, S), ("SAFE-01", "YD-01"), ((DAY, 1), (NIGHT, 1))),
    ActivitySpec("A12", "CRT-1012", "BY Shed", "BY Shed", "Shed", "Shed", BETHWAY, BETHWAY,
                 (S, D), ("SAFE-01", "SH-01"), ((DAY, 1),), can_be_moved=False),
    ActivitySpec("A13", "CRT-1013", "Nelaway Driver", "Nelaway Driver", "Local", "Driving", NELAWAY, NELAWAY,
                 (D,), ("SAFE-01", "NL-01"), ((DAY, 1), (NIGHT, 1))),
    ActivitySpec("A14", "CRT-1014", "Nelaway Shuttle Driver", "Nelaway Shuttle Driver", "Local", "Driving", NELAWAY,
                 NELAWAY, (D,), ("SAFE-01", "NL-01"), ((DAY, 1),)),
    ActivitySpec("A15", "CRT-1015", "NE Ship", "NE Ship", "Shed", "Shed", NELAWAY, NELAWAY,
                 (S, D), ("SAFE-01", "SH-01", "NL-01"), ((DAY, 1),)),
    ActivitySpec("A16", "CRT-1016", "NE Task", "NE Task", "Local", "Crew", NELAWAY, NELAWAY,
                 (D, C, S), ("SAFE-01", "NL-01"), ((DAY, 1), (NIGHT, 1))),
]  # fmt: skip
# Every activity also needs its own sign-off competency (code AC-<Activity ID>),
# so sharing a generic competency (e.g. Yard Operations) does not make a crew
# member eligible for every activity that uses it.
ACTIVITY_CATALOG = [replace(a, competencies=a.competencies + (f"AC-{a.activity_id}",)) for a in ACTIVITY_CATALOG]
COMPETENCIES.update({f"AC-{a.activity_id}": f"{a.name} Sign-off" for a in ACTIVITY_CATALOG})

# Not demanded / not optimised.
STANDBY_ACTIVITIES = [
    ("A90", "CRT-9001", "Relief Standby", "Relief"),
    ("A91", "CRT-9002", "Excess Standby", "Excess"),
]
EXCLUDED_ACTIVITY = ActivitySpec("A17", "CRT-1017", "Route Learning", "Haskett Mainline", "Training", "Training",
                                 HASKETT, YARMOUTH, (D,), ("SAFE-01",), ((DAY, 1),))  # fmt: skip

# Depot-dependent probability that a Relief/Excess crew member is qualified for an activity.
QUALIFICATION_PROFILES: dict[str, dict[str, float]] = {
    HASKETT: {"A01": 0.85, "A02": 0.7, "A03": 0.8, "A04": 0.3, "A05": 0.15},
    YARMOUTH: {"A03": 0.85, "A01": 0.75, "A04": 0.7, "A05": 0.65, "A02": 0.25},
    MADISON: {"A06": 0.8, "A07": 0.75, "A08": 0.4, "A09": 0.5, "A10": 0.5, "A11": 0.15},
    BETHWAY: {"A11": 0.8, "A12": 0.7, "A10": 0.5, "A09": 0.4, "A06": 0.15},
    NELAWAY: {"A13": 0.85, "A14": 0.75, "A15": 0.6, "A16": 0.8},
}
ROLE_WEIGHTS = {D: 0.55, C: 0.2, S: 0.25}


@dataclass
class DBSyntheticConfig:
    name: str = "db_synthetic"
    seed: int = 0
    n_relief_excess: int = 20
    horizon_days: int = 7
    start_date: str = "2026-11-01"
    demand_scale: float = 1.0
    base_weights: dict[str, float] = field(
        default_factory=lambda: {HASKETT: 0.28, YARMOUTH: 0.22, MADISON: 0.2, BETHWAY: 0.12, NELAWAY: 0.18}
    )
    relief_fraction: float = 0.4
    vacancy_fraction: float = 0.06
    disruption_fraction: float = 0.08
    existing_fraction: float = 0.03  # of Relief/Excess crew given an existing assignment
    unlocked_share: float = 0.25  # share of those existing assignments that are unlocked
    prior_duty_fraction: float = 0.3
    next_commitment_fraction: float = 0.2
    changed_time_fraction: float = 0.05
    leave_fraction: float = 0.05
    away_fraction: float = 0.1
    competency_gap_fraction: float = 0.05
    currency_lapsed_fraction: float = 0.05
    trainee_fraction: float = 0.08
    mentor_fraction: float = 0.15
    medical_unfit_fraction: float = 0.01
    night_restriction_fraction: float = 0.02
    # Multiplies QUALIFICATION_PROFILES. The briefing expects up to ~50 eligible
    # crew per duty, so the 1,000-crew presets scale qualifications down.
    qualification_scale: float = 1.0


DB_PRESETS: dict[str, DBSyntheticConfig] = {
    "small": DBSyntheticConfig(name="small", seed=11, n_relief_excess=20, horizon_days=5, vacancy_fraction=0.12),
    "medium": DBSyntheticConfig(name="medium", seed=22, n_relief_excess=150, horizon_days=7, demand_scale=3,
                                vacancy_fraction=0.18),
    "tight": DBSyntheticConfig(name="tight", seed=44, n_relief_excess=60, horizon_days=7, demand_scale=3,
                               vacancy_fraction=0.33),
    "large": DBSyntheticConfig(name="large", seed=33, n_relief_excess=1000, horizon_days=14, demand_scale=5,
                               vacancy_fraction=0.15, disruption_fraction=0.05, qualification_scale=0.2),
    "xlarge": DBSyntheticConfig(name="xlarge", seed=55, n_relief_excess=1000, horizon_days=14, demand_scale=10,
                                vacancy_fraction=0.15, disruption_fraction=0.05, qualification_scale=0.6),
}  # fmt: skip


def _d(x: date) -> str:
    return x.strftime("%Y-%m-%d")


def _t(x: time) -> str:
    return x.strftime("%H:%M")


def _yn(b: bool) -> str:
    return "Yes" if b else "No"


def default_constraints(start: date, days: int) -> list[dict[str, str]]:
    rows = [
        ("Planning Horizon Start", _d(start), "Active"),
        ("Planning Horizon Days", str(days), "Active"),
        ("Ordinary Rest Hours", "11", "Active"),
        ("Transition Rest Hours", "23", "Active"),
        ("Day Shift Window", "03:00-15:00", "Active"),
        ("Max Duties Per Day", "1", "Active"),
        ("Relief Work/Off Days", "14/14", "Active"),
        ("Excess Work/Off Days", "6/6", "Active"),
        ("Relief Allowed Start Offsets", "ANY", "Active"),
        ("Excess Allowed Start Offsets", "-60;0;60", "Active"),
        ("Relief Time Change Policy", "persist_after_change", "Active"),
        ("Excess Time Change Policy", "persist_after_change", "Active"),
        ("Enforce Swing Work Days", "", "Active"),
        ("Base Return At Swing End", "", "Active"),
        ("Base Return On Transition", "", "Active"),
        ("Base Return At Horizon End", "", "Inactive"),
        ("Demand Mode", "partial", "Active"),
        ("Objective Order", "coverage;priority;time_changes", "Active"),
        ("Positioning", "", "Inactive"),
    ]
    return [{"Constraint": a, "Value": b, "Status": c} for a, b, c in rows]


def activity_rows() -> list[dict[str, str]]:
    rows = []
    for a in ACTIVITY_CATALOG + [EXCLUDED_ACTIVITY]:
        rows.append({
            "Activity ID": a.activity_id, "CRT Activity ID": a.crt_id, "Activity Name": a.name,
            "Activity Group": a.group, "Activity Head": a.head, "Activity Type": a.type,
            "TEA Required": _yn(a.tea_required), "Can Be Moved": _yn(a.can_be_moved), "Start Depot": a.start_depot,
            "End Depot": a.end_depot, "Location": a.start_depot, "Mentor Required": _yn(a.mentor_required),
            "Roles/Job": ";".join(a.roles), "Currency Threshold": "" if a.currency_days is None else str(a.currency_days),
        })  # fmt: skip
    for aid, crt, name, head in STANDBY_ACTIVITIES:
        rows.append({
            "Activity ID": aid, "CRT Activity ID": crt, "Activity Name": name, "Activity Group": "Reserve",
            "Activity Head": head, "Activity Type": "Standby", "TEA Required": "No", "Can Be Moved": "Yes",
            "Start Depot": "", "End Depot": "", "Location": "", "Mentor Required": "No", "Roles/Job": "",
            "Currency Threshold": "",
        })  # fmt: skip
    return rows


def compliance_rows() -> list[dict[str, str]]:
    return [
        {"Activity ID": a.activity_id, "Activity Name": a.name, "Competency LMS Code": code,
         "Competency": COMPETENCIES[code], "Activity Head": a.head}
        for a in ACTIVITY_CATALOG + [EXCLUDED_ACTIVITY] for code in a.competencies
    ]  # fmt: skip


class _Builder:
    def __init__(self, cfg: DBSyntheticConfig):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.d0 = date.fromisoformat(cfg.start_date)
        self.days = [self.d0 + timedelta(days=k) for k in range(cfg.horizon_days)]
        self.t: Tables = {k: [] for k in (
            "roster_df", "crew_restrictions", "crew_competencies_df", "crew_master_data_df", "Crew_Onsite_App",
            "crew_currency_df")}  # fmt: skip
        self.n_crew = 0
        self.n_roster = 0
        self.n_restr = 0
        self.n_onsite = 0
        self.n_cur = 0
        self.by_id = {a.activity_id: a for a in ACTIVITY_CATALOG}
        self.mentors: dict[str, list[str]] = {d: [] for d in DEPOTS}

    # -- rows -----------------------------------------------------------------
    def crew(self, classification: str, depot: str, role: str, medical: str = "Fit", mentor_id: str = "",
             is_mentor: bool = False) -> tuple[str, str]:  # fmt: skip
        self.n_crew += 1
        k = self.n_crew
        cm, user = f"CM{k:05d}", f"U{100000 + k}"
        self.t["crew_master_data_df"].append({
            "CM Id": cm, "User Id": user, "Email": f"crew{k:05d}@example.invalid", "First Name": f"First{k:05d}",
            "Last Name": f"Last{k:05d}", "Mentor Id": mentor_id, "Classification": classification, "Depot": depot,
            "Role": role, "Is Mentor": _yn(is_mentor), "Medical": medical,
            "Position": {"Relief": "FIFO", "Excess": "Residential"}.get(classification, "Line"),
        })  # fmt: skip
        if is_mentor:
            self.mentors[depot].append(cm)
        return cm, user

    def roster(self, user: str, start: datetime, end: datetime, crt: str, name: str, head: str, atype: str,
               group: str, locked: bool) -> None:  # fmt: skip
        self.n_roster += 1
        self.t["roster_df"].append({
            "Assignment ID": f"AS{self.n_roster:07d}", "User Id": user, "Start Date": _d(start.date()),
            "End Date": _d(end.date()), "Shift Start Time": _t(start.time()), "Shift End Time": _t(end.time()),
            "CRT Activity ID": crt, "Activity Name": name, "Is Locked": _yn(locked), "Activity Head": head,
            "Activity Type": atype, "Activity Group": group,
        })  # fmt: skip

    def roster_activity(self, user: str, a: ActivitySpec, start: datetime, end: datetime, locked: bool) -> None:
        self.roster(user, start, end, a.crt_id, a.name, a.head, a.type, a.group, locked)

    def restriction(self, cm: str, rtype: str, lo: date, hi: date, reason: str, head: str = "") -> None:
        self.n_restr += 1
        self.t["crew_restrictions"].append({
            "Restriction ID": f"RS{self.n_restr:05d}", "CM Id": cm, "Restriction Type": rtype,
            "Activity Head": head, "Effective From": _d(lo), "Effective To": _d(hi), "Reason": reason,
        })  # fmt: skip

    def onsite(self, cm: str, day: date, location: str, status: str) -> None:
        self.n_onsite += 1
        self.t["Crew_Onsite_App"].append(
            {"Record ID": f"OS{self.n_onsite:06d}", "CM Id": cm, "Date": _d(day), "Location": location,
             "Status": status}  # fmt: skip
        )

    def competency(self, cm: str, code: str, expiry: date, status: str = "Valid") -> None:
        self.t["crew_competencies_df"].append({
            "CM Id": cm, "Competency": COMPETENCIES[code], "Competency LMS Code": code, "Expiry Date": _d(expiry),
            "status": status,
        })  # fmt: skip

    def currency(self, cm: str, a: ActivitySpec, last: date) -> None:
        self.n_cur += 1
        self.t["crew_currency_df"].append({
            "Currency ID": f"CU{self.n_cur:06d}", "CM Id": cm, "Activity Head": a.head,
            "Last Performed Date": _d(last), "Last CRT Activity ID": a.crt_id,
        })  # fmt: skip

    def qualify(self, cm: str, acts: list[ActivitySpec], gap: bool, lapsed: bool) -> None:
        rng = self.rng
        codes = sorted({c for a in acts for c in a.competencies})
        broken = rng.choice(codes) if gap and codes else None
        for code in codes:
            expiry = self.d0 + timedelta(days=rng.randint(120, 900))
            status = "Valid"
            if code == broken:
                if rng.random() < 0.5:
                    expiry = self.d0 + timedelta(days=rng.randrange(max(1, self.cfg.horizon_days)))
                else:
                    status = rng.choice(["Expired", "Suspended"])
            self.competency(cm, code, expiry, status)
        heads_done = set()
        for a in acts:
            if a.currency_days is None or a.head in heads_done:
                continue
            heads_done.add(a.head)
            if lapsed:
                last = self.d0 - timedelta(days=a.currency_days - rng.randint(0, self.cfg.horizon_days))
            else:
                last = self.d0 - timedelta(days=rng.randint(1, max(1, a.currency_days - self.cfg.horizon_days - 1)))
            self.currency(cm, a, last)

    # -- regular crew ------------------------------------------------------------
    def regular_crew(self) -> None:
        cfg, rng = self.cfg, self.rng
        for a in ACTIVITY_CATALOG:
            for shift, base in a.shifts:
                units = max(1, round(base * cfg.demand_scale))
                s_txt, e_txt = shift.split("-")
                s_t, e_t = time.fromisoformat(s_txt), time.fromisoformat(e_txt)
                for _ in range(units):
                    pool = []
                    for _p in range(2):
                        role = a.roles[0]
                        cm, user = self.crew("Permanent", a.start_depot, role, is_mentor=rng.random() < 0.2)
                        self.qualify(cm, [a], gap=False, lapsed=False)
                        pool.append((cm, user))
                    for k, day in enumerate(self.days):
                        cm, user = pool[(k // 7) % 2]
                        if rng.random() < cfg.vacancy_fraction:
                            continue
                        s, e = slot_datetimes(day, s_t, e_t)
                        self.roster_activity(user, a, s, e, locked=rng.random() < 0.5)
                    for cm, _user in pool:
                        if rng.random() < cfg.disruption_fraction:
                            self.disrupt(cm, a)

    def disrupt(self, cm: str, a: ActivitySpec) -> None:
        rng, days = self.rng, self.days
        kind = rng.choice(["leave", "leave", "medical", "competency", "currency", "onsite", "restriction"])
        lo = rng.choice(days)
        hi = min(days[-1], lo + timedelta(days=rng.randint(0, 3)))
        if kind == "leave":
            self.restriction(cm, "No Duty", lo, hi, rng.choice(["Annual Leave", "Sick Leave", "Training Course"]))
        elif kind == "medical":
            row = next(r for r in self.t["crew_master_data_df"] if r["CM Id"] == cm)
            row["Medical"] = "Unfit"
        elif kind == "competency":
            for r in self.t["crew_competencies_df"]:
                if r["CM Id"] == cm and r["Competency LMS Code"] == a.competencies[-1]:
                    r["Expiry Date"] = _d(lo)
        elif kind == "currency" and a.currency_days:
            for r in self.t["crew_currency_df"]:
                if r["CM Id"] == cm:
                    r["Last Performed Date"] = _d(lo - timedelta(days=a.currency_days + 1))
        elif kind == "onsite":
            self.onsite(cm, lo, a.start_depot, "Absent")
        else:
            self.restriction(cm, "Activity Restriction", lo, hi, "Pending incident review", head=a.head)

    # -- relief / excess crew -------------------------------------------------------
    def relief_excess_crew(self) -> None:
        cfg, rng = self.cfg, self.rng
        d0, d_end = self.d0, self.days[-1]
        for _ in range(cfg.n_relief_excess):
            depot = rng.choices(list(cfg.base_weights), weights=list(cfg.base_weights.values()), k=1)[0]
            relief = rng.random() < cfg.relief_fraction
            classification = "Relief" if relief else "Excess"
            role = rng.choices(list(ROLE_WEIGHTS), weights=list(ROLE_WEIGHTS.values()), k=1)[0]
            mentor_id = ""
            if rng.random() < cfg.trainee_fraction and self.mentors[depot]:
                mentor_id = rng.choice(self.mentors[depot])
            medical = "Unfit" if rng.random() < cfg.medical_unfit_fraction else "Fit"
            cm, user = self.crew(classification, depot, role, medical, mentor_id,
                                 is_mentor=not mentor_id and rng.random() < cfg.mentor_fraction)  # fmt: skip
            profile = QUALIFICATION_PROFILES[depot]
            acts = [self.by_id[aid] for aid, p in profile.items()
                    if rng.random() < p * cfg.qualification_scale and role in self.by_id[aid].roles]
            if not acts:
                options = [self.by_id[aid] for aid in profile if role in self.by_id[aid].roles]
                acts = [rng.choice(options)] if options else []
            self.qualify(cm, acts, rng.random() < cfg.competency_gap_fraction,
                         rng.random() < cfg.currency_lapsed_fraction)  # fmt: skip

            # Swing calendar -> Standby rows over every run that touches the horizon.
            work, off = (14, 14) if relief else (6, 6)
            swing_start = d0 - timedelta(days=rng.randrange(work + off))
            cycle = work + off
            work_days: list[date] = []
            day = d0 - timedelta(days=cycle)
            while day <= d_end + timedelta(days=cycle):
                if (day - swing_start).days % cycle < work:
                    work_days.append(day)
                day += timedelta(days=1)
            runs: list[list[date]] = []
            for wd in work_days:
                if runs and (wd - runs[-1][-1]).days == 1:
                    runs[-1].append(wd)
                else:
                    runs.append([wd])
            keep = [r for r in runs if r[-1] >= d0 - timedelta(days=1) and r[0] <= d_end]
            if relief:
                hour = rng.choice([5, 17])
            else:
                hour = rng.choice([5, 17, 5, 17, 4, 6, 16, 18, 7])
            rostered = time(hour, 0)
            standby = STANDBY_ACTIVITIES[0] if relief else STANDBY_ACTIVITIES[1]
            on_days = sorted({d for r in keep for d in r})
            for wd in on_days:
                s = datetime.combine(wd, rostered)
                self.roster(user, s, s + timedelta(hours=12), standby[1], standby[2], standby[3], "Standby",
                            "Reserve", False)  # fmt: skip
            on = set(on_days)

            location = depot
            # Prior duty on the day before the horizon (if that was a working day).
            local = [a for a in acts if a.start_depot == depot]
            if (d0 - timedelta(days=1)) in on and local and rng.random() < cfg.prior_duty_fraction:
                a = rng.choice(local)
                start_t = rostered
                if rng.random() < cfg.changed_time_fraction:
                    start_t = time((hour + rng.choice([-1, 1])) % 24, 0)
                s = datetime.combine(d0 - timedelta(days=1), start_t)
                self.roster_activity(user, a, s, s + timedelta(hours=12), locked=True)
                location = a.end_depot
            # Commitment on the first day after the horizon.
            d_after = d_end + timedelta(days=1)
            if d_after in on and local and rng.random() < cfg.next_commitment_fraction:
                a = rng.choice(local)
                s = datetime.combine(d_after, rostered)
                self.roster_activity(user, a, s, s + timedelta(hours=12), locked=True)
            if rng.random() < cfg.away_fraction:
                location = rng.choice([d for d in DEPOTS if d != depot])
            self.onsite(cm, d0, location, "On Site" if location == depot else "Away")
            if rng.random() < cfg.leave_fraction:
                lo = rng.choice(self.days)
                if rng.random() < 0.5:
                    self.restriction(cm, "No Duty", lo, lo, "Annual Leave")
                else:
                    self.onsite(cm, lo, depot, "Absent")
            if rng.random() < cfg.night_restriction_fraction:
                self.restriction(cm, "No Night Shift", d0, d_end, "Fatigue management plan")

    # -- assemble -----------------------------------------------------------------
    def tables(self) -> Tables:
        cfg = self.cfg
        t = dict(self.t)
        t["activities_df"] = activity_rows()
        t["compliance_matrix_df"] = compliance_rows()
        demand = []
        n = 0
        for a in ACTIVITY_CATALOG + [EXCLUDED_ACTIVITY]:
            for shift, base in a.shifts:
                n += 1
                demand.append({
                    "Demand ID": f"DM{n:03d}", "Shift": shift, "Demand": str(max(1, round(base * cfg.demand_scale))),
                    "Is Active": "Yes", "Activity ID": a.activity_id, "Activity Name": a.name, "Activity Head": a.head,
                })  # fmt: skip
        # One inactive demand row (seasonal), so the Is Active flag is exercised.
        n += 1
        demand.append({"Demand ID": f"DM{n:03d}", "Shift": "17:00-05:00", "Demand": "1", "Is Active": "No",
                       "Activity ID": "A12", "Activity Name": "BY Shed", "Activity Head": "BY Shed"})  # fmt: skip
        t["activity_demand_df"] = demand
        t["constraints_df"] = default_constraints(self.d0, cfg.horizon_days)
        t["excluded_activities"] = [{"Activity ID": EXCLUDED_ACTIVITY.activity_id,
                                     "Activity Name": EXCLUDED_ACTIVITY.name}]  # fmt: skip
        t["activity_priority"] = [{"Priority": str(k), "Activity Head": h} for k, h in enumerate(ACTIVITY_PRIORITY, 1)]
        return t


def metadata_for(cfg: DBSyntheticConfig) -> dict:
    return {
        "name": cfg.name,
        "synthetic": True,
        "disclaimer": "SYNTHETIC DATA generated by railway_rostering.synthetic_db - not OptiFlux operational data.",
        "seed": cfg.seed,
        "generator_config": asdict(cfg),
    }


def generate_tables(cfg: DBSyntheticConfig) -> tuple[Tables, dict]:
    """Return ``(tables, metadata)`` for ``cfg``. Deterministic in ``cfg``."""

    b = _Builder(cfg)
    b.regular_crew()
    b.relief_excess_crew()
    tables = b.tables()
    meta = metadata_for(cfg)

    # Existing Relief/Excess assignments, accepted only if the validator agrees.
    if cfg.existing_fraction > 0:
        inst = build_instance(tables, cfg.name, dict(meta))
        mcfg = model_config_from_constraints(tables["constraints_df"])
        check_cfg = replace(mcfg, existing_assignment_mode="fixed")
        target = round(cfg.existing_fraction * cfg.n_relief_excess)
        users = {r["CM Id"]: r["User Id"] for r in tables["crew_master_data_df"]}
        acts = {a.name: a for a in ACTIVITY_CATALOG}
        chosen: dict[str, list[tuple[str, str]]] = {}
        duties = [d for d in inst.duties if d.open_demand > 0 and d.eligible_crew]
        b.rng.shuffle(duties)
        n_done = 0
        for d in duties:
            if n_done >= target:
                break
            options = sorted(d.eligible_crew - set(chosen))
            b.rng.shuffle(options)
            for cm in options[:8]:
                if validate_solution(inst, check_cfg, [(cm, d.duty_id)]).passed:
                    chosen[cm] = [(cm, d.duty_id)]
                    a = acts[d.activity]
                    b.roster_activity(users[cm], a, d.start, d.end, locked=b.rng.random() >= cfg.unlocked_share)
                    n_done += 1
                    break
        tables["roster_df"] = b.t["roster_df"]
    return tables, meta


def generate_db_instance(cfg: DBSyntheticConfig) -> Instance:
    tables, meta = generate_tables(cfg)
    return build_instance(tables, cfg.name, meta)
