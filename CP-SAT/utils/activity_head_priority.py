"""Load and validate demand activity-head priorities and per-swing shift limits."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from option_generation.data import DEFAULT_DATA_DIR

DEFAULT_ACTIVITY_HEAD_PRIORITY = DEFAULT_DATA_DIR / "activity_priority.csv"
PRIORITY_WEIGHTS = {
    1: 14,
    2: 13,
    3: 12,
    4: 11,
    5: 10,
    6: 9,
    7: 8,
    8: 7,
    9: 6,
    10: 5,
    11: 4,
    12: 3,
    13: 2,
    14: 1,
}
MAX_RESIDENT_SHIFTS_COL = "Max Resident Shifts"
MAX_FIFO_SHIFTS_COL = "Max FIFO Shifts"


@dataclass(frozen=True)
class ActivityHeadLimits:
    max_resident_shifts: int
    max_fifo_shifts: int

    def limit_for(self, classification: str) -> int:
        if classification in ("Residential", "Resident"):
            return self.max_resident_shifts
        if classification == "FIFO":
            return self.max_fifo_shifts
        raise ValueError(f"unknown crew classification: {classification!r}")


def _read_rows(path: Path, required: tuple[str, ...]) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None or any(column not in reader.fieldnames for column in required):
                raise SystemExit(f"error: {path} must contain columns: {', '.join(required)}")
            return list(reader.fieldnames), list(reader)
    except FileNotFoundError:
        raise SystemExit(f"error: required priority data file not found: {path}") from None


def _load_demand_heads(demand_path: Path) -> set[str]:
    _, demand_rows = _read_rows(demand_path, ("Activity Head",))
    if any(not (row.get("Activity Head") or "").strip() for row in demand_rows):
        raise SystemExit(f"error: {demand_path} contains a demand row with an empty Activity Head")
    return {head for row in demand_rows if (head := (row.get("Activity Head") or "").strip())}


def _check_unique_heads(rows: list[dict[str, str]]) -> None:
    heads = [(row.get("Activity Head") or "").strip() for row in rows]
    duplicates = sorted(head for head, count in Counter(heads).items() if head and count > 1)
    if duplicates:
        raise SystemExit(f"error: duplicate activity-head priority entries: {', '.join(duplicates)}")


def _parse_non_negative_int(raw: str | None) -> int | None:
    text = (raw or "").strip()
    return int(text) if text.isdecimal() else None


def load_activity_head_priorities(
    demand_path: Path, priority_path: Path = DEFAULT_ACTIVITY_HEAD_PRIORITY
) -> dict[str, int]:
    """Return one positive integer priority per activity head in the demand data."""
    demand_heads = _load_demand_heads(demand_path)
    fieldnames, priority_rows = _read_rows(priority_path, ("Activity Head", "Priority"))
    _check_unique_heads(priority_rows)

    priorities: dict[str, int] = {}
    invalid: list[str] = []
    for row in priority_rows:
        head = (row.get("Activity Head") or "").strip()
        value = (row.get("Priority") or "").strip()
        try:
            priority = int(value)
        except ValueError:
            invalid.append(f"{head or '<empty>'}={value or '<empty>'}")
            continue
        if not head or priority not in PRIORITY_WEIGHTS:
            invalid.append(f"{head or '<empty>'}={value}")
            continue
        priorities[head] = priority
    if invalid:
        raise SystemExit(
            "error: activity-head priorities must be integers with configured weights in "
            f"PRIORITY_WEIGHTS: {', '.join(invalid)}"
        )

    missing = sorted(demand_heads - priorities.keys())
    if missing:
        raise SystemExit(f"error: missing priorities for demand activity heads: {', '.join(missing)}")
    unknown = sorted(priorities.keys() - demand_heads)
    if unknown:
        raise SystemExit(f"error: priorities configured for non-demand activity heads: {', '.join(unknown)}")

    if MAX_RESIDENT_SHIFTS_COL in fieldnames or MAX_FIFO_SHIFTS_COL in fieldnames:
        load_activity_head_limits(demand_path, priority_path)
    return priorities


def load_activity_head_limits(
    demand_path: Path, priority_path: Path = DEFAULT_ACTIVITY_HEAD_PRIORITY
) -> dict[str, ActivityHeadLimits]:
    """Return validated (Max Resident Shifts, Max FIFO Shifts) limits for every demand activity head."""
    demand_heads = _load_demand_heads(demand_path)
    _, rows = _read_rows(priority_path, ("Activity Head", MAX_RESIDENT_SHIFTS_COL, MAX_FIFO_SHIFTS_COL))
    _check_unique_heads(rows)

    limits: dict[str, ActivityHeadLimits] = {}
    invalid: list[str] = []
    for row in rows:
        head = (row.get("Activity Head") or "").strip()
        raw_res = row.get(MAX_RESIDENT_SHIFTS_COL)
        raw_fifo = row.get(MAX_FIFO_SHIFTS_COL)
        res_limit = _parse_non_negative_int(raw_res)
        fifo_limit = _parse_non_negative_int(raw_fifo)
        if not head or res_limit is None or fifo_limit is None:
            invalid.append(
                f"{head or '<empty>'}(Max Resident Shifts={(raw_res or '').strip() or '<empty>'}, "
                f"Max FIFO Shifts={(raw_fifo or '').strip() or '<empty>'})"
            )
            continue
        limits[head] = ActivityHeadLimits(max_resident_shifts=res_limit, max_fifo_shifts=fifo_limit)

    if invalid:
        raise SystemExit(
            "error: Max Resident Shifts and Max FIFO Shifts must be non-negative integers: "
            f"{', '.join(invalid)}"
        )

    missing = sorted(demand_heads - limits.keys())
    if missing:
        raise SystemExit(f"error: missing shift limits for demand activity heads: {', '.join(missing)}")
    unknown = sorted(limits.keys() - demand_heads)
    if unknown:
        raise SystemExit(f"error: shift limits configured for non-demand activity heads: {', '.join(unknown)}")
    return limits
