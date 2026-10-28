"""Shift classification, day/night transitions and minimum rest.

Source (briefing §5, §9): "Ordinary rest between shifts must be at least
11 hours. During a shift transition, rest must be 23 hours." A transition is
"a change from day shift to night shift or night shift to day shift".

Implemented rule (hard constraint)
----------------------------------
For two *consecutive* duties ``i -> j`` of the same crew member::

    start(j) >= end(i) + rest(i, j)
    rest(i, j) = 23 h  if transition rest is enabled and shift(i) != shift(j)
               = 11 h  otherwise

Shift type is the duty's explicit ``shift_type`` column if given, otherwise
DAY when the start time-of-day lies in ``[day_shift_start_from,
day_shift_start_until)`` (default 03:00-15:00) and NIGHT otherwise. This
classification window is an assumption: the briefing only says 5 AM shifts are
day and 5 PM shifts are night.

Because every arc goes forward in time, enforcing rest between consecutive
duties also rules out any overlap between non-consecutive duties (see
docs/problem_formulation.md, "Why consecutive checks are enough").

The 23 h rule is *not* applied after every duty: only when the shift type
changes between consecutive duties (including the prior duty before the
horizon and the next commitment after it, when their shift types are known).
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from ..config import ModelConfig
from ..domain import Duty, ShiftType


def parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def classify_start(start: datetime | time, cfg: ModelConfig) -> ShiftType:
    t = start.time() if isinstance(start, datetime) else start
    lo = parse_hhmm(cfg.day_shift_start_from)
    hi = parse_hhmm(cfg.day_shift_start_until)
    if lo <= hi:
        is_day = lo <= t < hi
    else:  # window wraps midnight
        is_day = t >= lo or t < hi
    return ShiftType.DAY if is_day else ShiftType.NIGHT


def shift_type_of(duty: Duty, cfg: ModelConfig) -> ShiftType:
    return duty.shift_type if duty.shift_type is not None else classify_start(duty.start, cfg)


def is_transition(prev: Optional[ShiftType], nxt: Optional[ShiftType]) -> bool:
    """A day<->night change between consecutive duties. Unknown -> no transition."""

    return prev is not None and nxt is not None and prev != nxt


def required_rest_minutes(prev: Optional[ShiftType], nxt: Optional[ShiftType], cfg: ModelConfig) -> int:
    if cfg.transition_rest_enabled and is_transition(prev, nxt):
        return round(cfg.transition_rest_hours * 60)
    return round(cfg.ordinary_rest_hours * 60)


def minimum_possible_rest_minutes(cfg: ModelConfig) -> int:
    """Smallest rest any consecutive pair can need (used for redundant cliques)."""

    rest = cfg.ordinary_rest_hours
    if cfg.transition_rest_enabled:
        rest = min(rest, cfg.transition_rest_hours)
    return round(rest * 60)
