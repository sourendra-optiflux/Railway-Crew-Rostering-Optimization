"""Load roster_full.csv (the roster with its gaps) and the tables the rules need."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .rules import DEFAULT_CONFIG, Rules

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "optiflux_v2"
DEFAULT_ROSTER_FULL = ROOT / "gap_generation" / "output" / "roster_full.csv"
DEFAULT_OUTPUT = ROOT / "option_generation" / "output"

WORK_TYPES = ("Demand", "Excess", "Relief")
TRAVEL_TYPES = ("Travel In", "Travel Out")
PERSON = "New User Id"  # who works the row after leave; blank on leave rows


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_dt(day: str, time: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{time}")


@dataclass
class Data:
    rules: Rules
    activities: dict[str, dict[str, str]]
    demand: dict[tuple[str, str], dict[str, str]]  # (Activity ID, "HH:MM") -> demand row
    crew: dict[str, dict[str, str]]
    roster: list[dict]  # roster_full rows, with parsed _s / _e
    columns: list[str]
    eligible: dict[str, set[str]]  # Activity ID -> User Ids (eligibility_matrix.csv, R5)
    last_done: dict[tuple[str, str], date]  # (User Id, Activity Head) -> last performed
    priority: dict[str, int]  # Activity Head -> priority, 1 = highest
    max_shifts: dict = field(default_factory=dict)  # Activity Head -> ActivityHeadLimits


def load(data_dir: Path, roster_full: Path, config_path: Path = DEFAULT_CONFIG) -> Data:
    for table in ("crew_restrictions.csv", "Crew_Onsite_App.csv", "excluded_activities.csv"):
        if read_csv(data_dir / table):
            raise SystemExit(f"error: {table} has rows, but this run does not model them yet")
    if not roster_full.exists():
        raise SystemExit(f"error: {roster_full} not found; run gap_generation/make_gaps.py first")
    roster = read_csv(roster_full)
    for row in roster:
        row["_s"] = parse_dt(row["Start Date"], row["Shift Start Time"])
        row["_e"] = parse_dt(row["End Date"], row["Shift End Time"])
    # gap_filling_rules.md R5: the eligibility matrix replaces crew_competencies_df + compliance_matrix_df.
    eligible = {
        m["Activity ID"]: {u for u in m["Eligible User Ids"].split(";") if u}
        for m in read_csv(data_dir / "eligibility_matrix.csv")
    }
    import sys

    if str(ROOT / "CP-SAT") not in sys.path:
        sys.path.insert(0, str(ROOT / "CP-SAT"))
    from utils.activity_head_priority import (
        load_activity_head_limits,
        load_activity_head_priorities,
    )

    demand_path = data_dir / "activity_demand_df.csv"
    priority_path = data_dir / "activity_priority.csv"
    return Data(
        rules=Rules.from_table(read_csv(data_dir / "constraints_df.csv"), config_path),
        activities={a["Activity ID"]: a for a in read_csv(data_dir / "activities_df.csv")},
        demand={
            (d["Activity ID"], d["Shift"]): d
            for d in read_csv(demand_path)
            if d["Is Active"] == "Yes"
        },
        crew={c["User Id"]: c for c in read_csv(data_dir / "crew_master_data_df.csv")},
        roster=roster,
        columns=[c for c in roster[0] if not c.startswith("_")],
        eligible=eligible,
        last_done={
            (r["User Id"], r["Activity Head"]): date.fromisoformat(r["Last Performed Date"])
            for r in read_csv(data_dir / "crew_currency_df.csv")
        },
        priority=load_activity_head_priorities(demand_path, priority_path),
        max_shifts=load_activity_head_limits(demand_path, priority_path),
    )


def why_not_eligible(data: Data, user: str, activity_id: str, day: date) -> str:
    """Empty string if the person may do this duty on this day, else the first reason they may not."""
    person, activity = data.crew[user], data.activities[activity_id]
    if user not in data.eligible.get(activity_id, ()):
        return "not certified (eligibility matrix)"
    if person["Medical"] != "Fit":
        return "medical"
    if person["Role"] not in [r.strip() for r in activity["Roles/Job"].split(";")]:
        return "role"
    if activity["Currency Threshold"]:
        last = data.last_done.get((user, activity["Activity Head"]))
        if last is None or (day - last).days > int(activity["Currency Threshold"]):
            return "currency"
    return ""
