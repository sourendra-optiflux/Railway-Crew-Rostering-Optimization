"""Eligibility rule: which crew members may perform which duties.

Source (briefing §7): eligibility is person-specific and activity-based
("Shrinath is eligible for Howrah Mainline and Nellore Driver"). Whether it
also depends on route, vehicle or crew category is an open question.

Implemented rule (hard constraint)
----------------------------------
A crew member ``c`` is eligible for duty ``i`` iff

1. if an eligibility table (``eligibility.csv``) is supplied, ``activity(i)``
   is in ``c``'s qualified activities, **and**
2. if the duty has a per-duty ``eligible_crew`` list, ``c`` is in it, **and**
3. at least one of the two sources exists for the duty (we never assume
   eligibility when there is no information).

Activities are matched by exact name, so eligibility for "Howrah Mainline"
does *not* imply eligibility for "Howrah Mainline CO" (the briefing leaves that
open; see docs/assumptions_and_open_questions.md).
"""

from __future__ import annotations

from typing import Optional

from ..domain import Crew, Duty, Instance

REASON_NOT_QUALIFIED = "not qualified for activity"
REASON_NOT_LISTED = "not in duty's eligible_crew list"
REASON_NO_INFORMATION = "no eligibility information for duty"


def ineligibility_reason(crew: Crew, duty: Duty, instance: Instance) -> Optional[str]:
    """Return ``None`` if eligible, otherwise a short reason string."""

    if instance.qualifications is None and duty.eligible_crew is None:
        return REASON_NO_INFORMATION
    if instance.qualifications is not None:
        if duty.activity not in instance.qualifications.get(crew.crew_id, frozenset()):
            return REASON_NOT_QUALIFIED
    if duty.eligible_crew is not None and crew.crew_id not in duty.eligible_crew:
        return REASON_NOT_LISTED
    return None


def is_eligible(crew: Crew, duty: Duty, instance: Instance) -> bool:
    return ineligibility_reason(crew, duty, instance) is None
