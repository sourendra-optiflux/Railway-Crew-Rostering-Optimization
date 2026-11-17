"""On-site crew: how many people are available at each site, per activity head and start datetime.

A person is counted at a site for the whole shift window, starting at the shift start. With 12 h shifts a
crew member who starts at 11:00 is available from 11:00 until 23:00 (the end is exclusive, so they are no
longer counted at 23:00).

    site     the `Start Location` of the person's roster row (the depot they start the shift at)
    head     the `Activity Head` of that row
    T        every start datetime in the demand template (one per active shift of the head, every day of the
             horizon), so the table answers "who could cover the seat that starts at T?"

Counted rows are Demand, Excess and Relief rows with a person. Leave rows (no person) are not counted.
`person_column` picks whose roster to use: `New User Id` (after leave, before gap filling) or
`Optimised User Id` (after gap filling).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

from .data import PERSON, WORK_TYPES

COLUMNS = [
    "Site", "Activity Head", "Start Datetime", "Demand Crew", "Excess Crew", "Relief Crew", "Crew Available",
    "Min Crew",
]  # fmt: skip


def seat_start_times(demand: dict[tuple[str, str], dict[str, str]], activities: dict[str, dict[str, str]],
                     horizon_start, horizon_days: int) -> dict[str, list[datetime]]:  # fmt: skip
    """Activity Head -> sorted start datetimes of its demand over the horizon."""
    times: dict[str, set[datetime]] = defaultdict(set)
    for activity_id, shift in demand:
        head = activities[activity_id]["Activity Head"]
        hour, minute = int(shift[:2]), int(shift[3:])
        for day in range(horizon_days):
            d = horizon_start + timedelta(days=day)
            times[head].add(datetime(d.year, d.month, d.day, hour, minute))
    return {head: sorted(ts) for head, ts in times.items()}


def onsite_crew_df(roster: list[dict], starts: dict[str, list[datetime]], shift_hours: int,
                   min_crew: dict[str, int] | None = None, person_column: str = PERSON) -> pd.DataFrame:  # fmt: skip
    """One row per (Site, Activity Head, Start Datetime) with the people on site, split by assignment type."""
    window = timedelta(hours=shift_hours)
    people: dict[tuple[str, str, datetime], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    sites: set[str] = set()
    for r in roster:
        user = r.get(person_column)
        if not user or r["Assignment Type"] not in WORK_TYPES:
            continue
        head, site = r["Activity Head"], r["Start Location"]
        if head not in starts or not site:
            continue
        sites.add(site)
        begin = datetime.fromisoformat(f"{r['Start Date']}T{r['Shift Start Time']}")
        for t in starts[head]:
            if begin <= t < begin + window:
                people[(site, head, t)][r["Assignment Type"]].add(user)

    rows = []
    for head in sorted(starts):
        for site in sorted(sites):
            for t in starts[head]:
                by_type = people.get((site, head, t), {})
                n = {kind: len(by_type.get(kind, ())) for kind in WORK_TYPES}
                everyone = set().union(*by_type.values()) if by_type else set()
                rows.append({
                    "Site": site, "Activity Head": head, "Start Datetime": t,
                    "Demand Crew": n["Demand"], "Excess Crew": n["Excess"], "Relief Crew": n["Relief"],
                    "Crew Available": len(everyone),
                    "Min Crew": (min_crew or {}).get(head),
                })  # fmt: skip
    return pd.DataFrame(rows, columns=COLUMNS)


def below_minimum(df: pd.DataFrame) -> pd.DataFrame:
    """Start datetimes where the head's crew over all sites is under its `Min Crew`.

    Sites are summed because the minimum is per activity head. A person has one roster row at a time (one
    shift a day), so the sum does not count anyone twice.
    """
    if df.empty or df["Min Crew"].isna().all():
        return df.iloc[0:0].drop(columns=["Site"])
    total = df.groupby(["Activity Head", "Start Datetime"], as_index=False).agg(
        **{"Crew Available": ("Crew Available", "sum"), "Min Crew": ("Min Crew", "first")}
    )
    short = total[total["Crew Available"] < total["Min Crew"]].copy()
    short["Shortfall"] = short["Min Crew"] - short["Crew Available"]
    return short.reset_index(drop=True)
