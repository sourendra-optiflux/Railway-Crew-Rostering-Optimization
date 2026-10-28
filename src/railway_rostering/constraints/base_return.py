"""Return-to-base rules.

Source (briefing §3): "On the last day of a swing or a transition day, the
person has to return to their base location." The briefing does not define
the deadline, whether ending a duty at base is sufficient, whether
positioning can satisfy it, or how it applies to duties crossing midnight.

Implemented approximation (hard constraint, each part switchable)
-----------------------------------------------------------------
"Being at base" is approximated as "the crew member's location after the
relevant duty is the base", reached either because the duty ends there or -
only when positioning is enabled - by an explicit positioning leg to base.

1. Swing end (``base_return_at_swing_end``): if consecutive duties ``i -> j``
   belong to different swings, the crew member must be at base between them.
   If ``i`` is the last duty and its swing's last working day lies inside the
   horizon, ``i`` must leave the crew member at base.
2. Transition (``base_return_on_transition``): if consecutive duties change
   between DAY and NIGHT shift, the crew member must be at base between them
   (the transition/rest day is spent at base). In the briefing's ABC example
   the duty before the transition is "Howrah Mainline CO, HWH -> HWH", which
   is consistent with this reading.
3. Horizon end (``base_return_at_horizon_end``, off by default): the last duty
   must leave the crew member at base even if the swing continues.

No deadline is enforced beyond the rest/timing rules. Crew without a
``base_location`` are exempt (input validation warns).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from ..config import ModelConfig
from ..domain import Crew, ShiftType
from .swing_rules import swing_last_work_date
from .time_rest import is_transition


def base_required_between(
    crew: Crew,
    prev_shift: Optional[ShiftType],
    prev_swing: Optional[int],
    next_shift: Optional[ShiftType],
    next_swing: Optional[int],
    cfg: ModelConfig,
) -> Optional[str]:
    """Reason string if the crew member must pass through base between two duties."""

    if crew.base_location is None:
        return None
    if cfg.base_return_at_swing_end and prev_swing is not None and next_swing is not None and prev_swing != next_swing:
        return "swing end"
    if cfg.base_return_on_transition and is_transition(prev_shift, next_shift):
        return "shift transition"
    return None


def base_required_after_last_duty(
    crew: Crew, last_swing: Optional[int], horizon_end: datetime, cfg: ModelConfig
) -> Optional[str]:
    """Reason string if the crew member's final location must be base."""

    if crew.base_location is None:
        return None
    if cfg.base_return_at_horizon_end:
        return "horizon end"
    if cfg.base_return_at_swing_end and last_swing is not None:
        last_day = swing_last_work_date(crew, last_swing, cfg)
        if last_day is not None and datetime.combine(last_day + timedelta(days=1), datetime.min.time()) <= horizon_end:
            return "swing end"
    return None
