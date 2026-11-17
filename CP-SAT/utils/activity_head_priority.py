"""Backward-compatible re-export of activity-head priority and shift-limit helpers from Layer 1."""

from __future__ import annotations

from option_generation.priority import (
    DEFAULT_ACTIVITY_HEAD_PRIORITY,
    MAX_FIFO_SHIFTS_COL,
    MAX_RESIDENT_SHIFTS_COL,
    ActivityHeadLimits,
    load_activity_head_limits,
    load_activity_head_priorities,
    priority_weights_for,
)

__all__ = [
    "ActivityHeadLimits",
    "DEFAULT_ACTIVITY_HEAD_PRIORITY",
    "MAX_FIFO_SHIFTS_COL",
    "MAX_RESIDENT_SHIFTS_COL",
    "load_activity_head_limits",
    "load_activity_head_priorities",
    "priority_weights_for",
]
