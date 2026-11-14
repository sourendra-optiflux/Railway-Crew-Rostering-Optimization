"""Load and validate demand activity-head priorities."""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACTIVITY_HEAD_PRIORITY = ROOT / "data" / "optiflux_v2" / "activity_priority.csv"


def priority_weights_for(priorities: Iterable[int]) -> dict[int, int]:
    """Derive strictly positive descending weights from the observed priority integers."""
    unique = set(priorities)
    if not unique:
        return {}
    max_priority = max(unique)
    return {priority: max_priority + 1 - priority for priority in unique}


def _read_rows(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None or any(column not in reader.fieldnames for column in required):
                raise SystemExit(f"error: {path} must contain columns: {', '.join(required)}")
            return list(reader)
    except FileNotFoundError:
        raise SystemExit(f"error: required priority data file not found: {path}") from None


def load_activity_head_priorities(
    demand_path: Path,
    priority_path: Path = DEFAULT_ACTIVITY_HEAD_PRIORITY,
) -> dict[str, int]:
    """Return one positive integer priority per activity head in the demand data."""
    demand_rows = _read_rows(demand_path, ("Activity Head",))
    demand_heads = {
        head for row in demand_rows if (head := (row.get("Activity Head") or "").strip())
    }
    if any(not (row.get("Activity Head") or "").strip() for row in demand_rows):
        raise SystemExit(f"error: {demand_path} contains a demand row with an empty Activity Head")

    priority_rows = _read_rows(priority_path, ("Activity Head", "Priority"))
    heads = [(row.get("Activity Head") or "").strip() for row in priority_rows]
    duplicates = sorted(head for head, count in Counter(heads).items() if head and count > 1)
    if duplicates:
        raise SystemExit(f"error: duplicate activity-head priority entries: {', '.join(duplicates)}")

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
        if not head or priority < 1:
            invalid.append(f"{head or '<empty>'}={value}")
            continue
        priorities[head] = priority
    if invalid:
        raise SystemExit(
            f"error: activity-head priorities must be positive integers (>= 1): {', '.join(invalid)}"
        )

    missing = sorted(demand_heads - priorities.keys())
    if missing:
        raise SystemExit(f"error: missing priorities for demand activity heads: {', '.join(missing)}")
    unknown = sorted(priorities.keys() - demand_heads)
    if unknown:
        raise SystemExit(f"error: priorities configured for non-demand activity heads: {', '.join(unknown)}")
    return priorities
