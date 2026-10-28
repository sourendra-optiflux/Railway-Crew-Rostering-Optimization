"""Input validation: semantic checks on a loaded :class:`Instance`.

Parsing errors (bad timestamps, missing columns, duplicate ids) are raised by
:mod:`data_loader`. This module checks consistency *between* records and
flags data that the model can technically run on but that probably indicates
a mistake or an unimplemented rule.

``ERROR``   the run should not proceed (e.g. an eligible list names an unknown
            crew member, an existing assignment references an unknown crew).
``WARNING`` the run proceeds, but a rule is skipped or an assumption is made
            (e.g. a crew member has no base, so base-return rules are off for
            them).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import ModelConfig
from .domain import CrewType, Instance

ERROR = "ERROR"
WARNING = "WARNING"


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def validate_instance(instance: Instance, cfg: ModelConfig) -> list[Issue]:
    issues: list[Issue] = []

    def err(code, msg):
        issues.append(Issue(ERROR, code, msg))

    def warn(code, msg):
        issues.append(Issue(WARNING, code, msg))

    crew_ids = set(instance.crews)
    if not instance.crews:
        err("NO_CREW", "instance has no crew members")
    if not instance.duties:
        warn("NO_DUTIES", "instance has no duties")
    if instance.horizon_end <= instance.horizon_start:
        err("BAD_HORIZON", "horizon_end must be after horizon_start")

    # --- duties ----------------------------------------------------------
    activities = {d.activity for d in instance.duties}
    for d in instance.duties:
        if d.eligible_crew is not None:
            unknown = sorted(d.eligible_crew - crew_ids)
            if unknown:
                err("UNKNOWN_ELIGIBLE_CREW", f"duty {d.duty_id} lists unknown crew {unknown}")
        unknown_assigned = sorted(set(d.assigned_crew) - crew_ids)
        if unknown_assigned:
            err("UNKNOWN_ASSIGNED_CREW", f"duty {d.duty_id} assigned to unknown crew {unknown_assigned}")
        if instance.qualifications is None and d.eligible_crew is None:
            warn(
                "NO_ELIGIBILITY_INFO",
                f"duty {d.duty_id} has no eligible list and there is no eligibility table: nobody can cover it",
            )
        if not (instance.horizon_start <= d.start < instance.horizon_end):
            warn("DUTY_OUTSIDE_HORIZON", f"duty {d.duty_id} starts outside the planning horizon")
        if d.duration.total_seconds() > 24 * 3600:
            warn("LONG_DUTY", f"duty {d.duty_id} lasts {d.duration}")
        if d.co_location is not None and d.co_location not in instance.locations:
            warn("UNKNOWN_CO_LOCATION", f"duty {d.duty_id} co_location {d.co_location!r} is not a known location")

    # --- eligibility table ------------------------------------------------
    if instance.qualifications is not None:
        unknown = sorted(set(instance.qualifications) - crew_ids)
        if unknown:
            warn("ELIGIBILITY_UNKNOWN_CREW", f"eligibility.csv mentions unknown crew {unknown[:10]}")
        never = sorted({a for q in instance.qualifications.values() for a in q} - activities)
        if never:
            warn("ELIGIBILITY_UNUSED_ACTIVITY", f"activities with qualifications but no duties: {never}")

    # --- crew ------------------------------------------------------------
    for c in instance.crews.values():
        if c.crew_type == CrewType.UNSPECIFIED:
            warn("NO_CREW_TYPE", f"crew {c.crew_id}: no crew_type, Relief/Excess rules not applied")
        if c.base_location is None:
            warn("NO_BASE", f"crew {c.crew_id}: no base_location, base-return rules not applied")
        if c.crew_type != CrewType.UNSPECIFIED and c.rostered_start is None:
            warn("NO_ROSTERED_TIME", f"crew {c.crew_id}: no rostered_start_time, time-change rules not applied")
        if c.crew_type != CrewType.UNSPECIFIED and c.swing_start is None and cfg.enforce_swing_work_days:
            warn("NO_SWING", f"crew {c.crew_id}: no swing_start_date, every day treated as a working day")
        if c.prior_shift_type is not None and c.prior_duty_end is None:
            warn("PRIOR_SHIFT_WITHOUT_END", f"crew {c.crew_id}: prior_shift_type given without prior_duty_end")
        if c.prior_duty_end is not None and c.prior_duty_end > instance.horizon_end:
            err("PRIOR_DUTY_AFTER_HORIZON", f"crew {c.crew_id}: prior_duty_end after horizon end")
        if c.next_commitment_start is not None and c.next_commitment_start < instance.horizon_start:
            err("NEXT_COMMITMENT_BEFORE_HORIZON", f"crew {c.crew_id}: next_commitment_start before horizon start")

    # --- existing assignments: same crew twice at overlapping times ----------
    per_crew: dict[str, list] = {}
    for d in instance.duties:
        for cid in d.assigned_crew:
            per_crew.setdefault(cid, []).append(d)
    for cid, ds in per_crew.items():
        ds.sort(key=lambda d: d.start)
        for a, b in zip(ds, ds[1:]):
            if b.start < a.end:
                err("EXISTING_OVERLAP", f"crew {cid}: existing duties {a.duty_id} and {b.duty_id} overlap")

    # --- travel ------------------------------------------------------------
    if cfg.positioning_enabled and not instance.travel:
        warn("NO_TRAVEL_LINKS", "positioning enabled but travel.csv is empty / missing")
    for a, b in instance.travel:
        if a == b:
            warn("SELF_TRAVEL", f"travel link {a}->{b} is a self-loop")
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == ERROR for i in issues)
