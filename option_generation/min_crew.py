"""Minimum crew required per activity head.

Default: half of the head's total daily demand, rounded up (a half person cannot be rostered):

    min_crew(head) = ceil(sum of Demand over the head's active shifts / 2)

`activity_demand_df.csv` is a one-day template (one row per activity and shift), so the sum over its
active rows is the head's demand for one day, all its activities (CO included) together.

A head can override the default by filling the optional `Min Crew` column of `activity_priority.csv`
with a non-negative integer. A blank cell keeps the default. The column may be absent.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

from .priority import DEFAULT_ACTIVITY_HEAD_PRIORITY, _read_rows

MIN_CREW_COL = "Min Crew"
DEFAULT_MIN_CREW_DIVISOR = 2


def total_daily_demand(demand_path: Path) -> dict[str, int]:
    """Activity Head -> sum of `Demand` over its active rows of `activity_demand_df.csv`."""
    _, rows = _read_rows(demand_path, ("Activity Head", "Demand", "Is Active"))
    total: dict[str, int] = defaultdict(int)
    for row in rows:
        if (row["Is Active"] or "").strip() == "Yes":
            total[row["Activity Head"].strip()] += int(row["Demand"])
    return dict(total)


def default_min_crew(daily_demand: int, divisor: int = DEFAULT_MIN_CREW_DIVISOR) -> int:
    return math.ceil(daily_demand / divisor)


def load_min_crew(
    demand_path: Path,
    priority_path: Path = DEFAULT_ACTIVITY_HEAD_PRIORITY,
    divisor: int = DEFAULT_MIN_CREW_DIVISOR,
) -> dict[str, int]:
    """Minimum crew per activity head: the `Min Crew` override if given, else ceil(daily demand / divisor)."""
    if divisor < 1:
        raise ValueError("divisor must be >= 1")
    demand = total_daily_demand(demand_path)
    minimum = {head: default_min_crew(total, divisor) for head, total in demand.items()}

    fieldnames, rows = _read_rows(priority_path, ("Activity Head",))
    if MIN_CREW_COL not in fieldnames:
        return minimum
    invalid: list[str] = []
    for row in rows:
        head = (row.get("Activity Head") or "").strip()
        raw = (row.get(MIN_CREW_COL) or "").strip()
        if not raw:
            continue
        if head not in demand:
            invalid.append(f"{head or '<empty>'} (not a demand activity head)")
        elif not raw.isdecimal():
            invalid.append(f"{head}={raw}")
        else:
            minimum[head] = int(raw)
    if invalid:
        raise SystemExit(f"error: {MIN_CREW_COL} must be a non-negative integer for a demand head: {', '.join(invalid)}")
    return minimum


def min_crew_table(demand_path: Path, minimum: dict[str, int]) -> list[dict]:
    """Rows for `min_crew.csv`: head, daily demand, minimum, and whether the default was used."""
    demand = total_daily_demand(demand_path)
    return [
        {
            "Activity Head": head,
            "Total Daily Demand": demand[head],
            "Min Crew": minimum[head],
            "Source": "default" if minimum[head] == default_min_crew(demand[head]) else "override",
        }
        for head in sorted(demand)
    ]
