"""Swing calendar and shift-time-change rules for Relief and Excess crew.

Source (briefing §4)
--------------------
* Relief ("FIFO"): usually 14 working days then 14 off. "The time can be
  changed to another time if other constraints are satisfied. Once changed,
  the person must follow the new time for the remaining days in that swing."
* Excess ("Residential"): usually 6 working days then 6 off. Rostered time
  cannot change except lift-up (-1 h) or layback (+1 h). "Once changed, the
  selected time must be followed for the remaining days in that swing."
* The briefing's EFG example lists patterns such as ``4 PM, 5 PM, 4 PM, 5 PM``
  that contain several changes, which conflicts with the "once changed" text.

Implemented rules
-----------------
Swing calendar (hard, if ``enforce_swing_work_days``):
    working(c, d)  <=>  (d - swing_start(c)) mod (work + off) < work
    swing_index(c, d) = floor((d - swing_start(c)) / (work + off))
    A duty may only start on a working date (by its *start* date).

Allowed start times (hard, unless policy is "disabled"):
    offset(i) = circular difference between the duty's start time-of-day and
    the crew member's rostered time; it must be in ``allowed_offsets_minutes``
    for the crew type (Excess default {-60, 0, +60}; Relief default: any).

Persistence ("persist_after_change", the default for both types):
    Within one swing, once a duty is worked at a time other than the reference
    time, every later duty in that swing must start at that same time of day.
    Encoded on consecutive arcs ``i -> j`` in the same swing:
        tod(i) != ref  =>  tod(j) == tod(i)
    The time reverts to the rostered time in a new swing (assumption).
    If ``current_start`` is given and differs from the rostered time, the
    change already happened before the horizon: all duties in the *current*
    swing must start at ``current_start``.

"window_only" applies only the allowed-offset check (this accepts every
pattern listed in the EFG example). The default is the stricter
"persist_after_change" because any roster feasible under it is also feasible
under "window_only" - it is the conservative choice until operations confirm.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from ..config import ModelConfig
from ..domain import Crew, CrewType, Duty, circular_offset_minutes, minutes_of_day

REASON_UNAVAILABLE = "unavailable on date"
REASON_OFF_DAY = "off day in swing"
REASON_TIME_NOT_ALLOWED = "start time not an allowed offset from rostered time"
REASON_TIME_ALREADY_CHANGED = "must keep time already changed in current swing"


def work_pattern(crew: Crew, cfg: ModelConfig) -> Optional[tuple[int, int]]:
    """(work_days, off_days) or ``None`` when the swing calendar is unknown."""

    if crew.swing_start is None:
        return None
    default = cfg.default_work_off_days.get(crew.crew_type.value)
    work = crew.work_days if crew.work_days is not None else (default[0] if default else None)
    off = crew.off_days if crew.off_days is not None else (default[1] if default else None)
    if work is None or off is None:
        return None
    return work, off


@dataclass(frozen=True)
class SwingDay:
    working: bool
    swing_index: Optional[int]  # None when the calendar is unknown


def swing_day(crew: Crew, d: date, cfg: ModelConfig) -> SwingDay:
    pattern = work_pattern(crew, cfg)
    if pattern is None:
        return SwingDay(True, None)
    work, off = pattern
    delta = (d - crew.swing_start).days
    period = work + off
    return SwingDay(delta % period < work, delta // period)


def swing_last_work_date(crew: Crew, swing_index: int, cfg: ModelConfig) -> Optional[date]:
    pattern = work_pattern(crew, cfg)
    if pattern is None:
        return None
    work, off = pattern
    return crew.swing_start + timedelta(days=swing_index * (work + off) + work - 1)


def current_swing_index(crew: Crew, horizon_start: datetime, cfg: ModelConfig) -> Optional[int]:
    """Swing containing the horizon start date, if that date is a working day."""

    sd = swing_day(crew, horizon_start.date(), cfg)
    return sd.swing_index if sd.working else None


def policy_for(crew: Crew, cfg: ModelConfig) -> str:
    if crew.crew_type == CrewType.UNSPECIFIED or crew.rostered_start is None:
        return "disabled"
    return cfg.time_change_policy.get(crew.crew_type.value, "disabled")


def reference_time(crew: Crew, swing_index: Optional[int], current_swing: Optional[int]) -> Optional[time]:
    """Time the crew member is 'on' at the beginning of a swing."""

    if crew.current_start is not None and swing_index is not None and swing_index == current_swing:
        return crew.current_start
    if crew.current_start is not None and swing_index is None:
        # Unknown calendar: treat the whole horizon as the current swing.
        return crew.current_start
    return crew.rostered_start


def availability_reason(crew: Crew, duty: Duty, cfg: ModelConfig) -> Optional[str]:
    if duty.start_date in crew.unavailable_dates:
        return REASON_UNAVAILABLE
    if cfg.enforce_swing_work_days and not swing_day(crew, duty.start_date, cfg).working:
        return REASON_OFF_DAY
    return None


def time_change_reason(
    crew: Crew, duty: Duty, swing_index: Optional[int], current_swing: Optional[int], cfg: ModelConfig
) -> Optional[str]:
    """Node-level time rule: allowed offsets and already-made changes."""

    policy = policy_for(crew, cfg)
    if policy == "disabled":
        return None
    allowed = cfg.allowed_offsets_minutes.get(crew.crew_type.value)
    if allowed is not None:
        if circular_offset_minutes(duty.start.time(), crew.rostered_start) not in set(allowed):
            return REASON_TIME_NOT_ALLOWED
    if policy == "persist_after_change":
        ref = reference_time(crew, swing_index, current_swing)
        if ref is not None and ref != crew.rostered_start and duty.start.time() != ref:
            return REASON_TIME_ALREADY_CHANGED
    return None


def persistence_allows(
    crew: Crew,
    prev_tod: time,
    prev_swing: Optional[int],
    next_tod: time,
    next_swing: Optional[int],
    current_swing: Optional[int],
    cfg: ModelConfig,
) -> bool:
    """Arc-level persistence rule for consecutive duties of one crew member."""

    if policy_for(crew, cfg) != "persist_after_change":
        return True
    if prev_swing != next_swing:
        return True  # new swing: time resets (assumption)
    ref = reference_time(crew, prev_swing, current_swing)
    if minutes_of_day(prev_tod) == minutes_of_day(ref):
        return True
    return minutes_of_day(next_tod) == minutes_of_day(prev_tod)
