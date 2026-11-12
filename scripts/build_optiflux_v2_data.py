#!/usr/bin/env python3
"""Build the fixed OptiFlux v2 tables (everything except the roster and the per-person tables).

Step 1 of 2. Step 2 is ``scripts/roster_making.py``, which builds the roster and,
from it, the crew list and the per-person tables.

Inputs (kept unchanged, for traceability):
    data/optiflux_v2/source/*.csv                      the four tables as uploaded
    data/optiflux_v2/source/rules/*.txt                the rule notes as supplied
    data/optiflux_v2/source/from_generated_small/*.csv compliance matrix and priority list of the old data

Outputs (overwritten):
    activities_df.csv, activity_demand_df.csv, activity_priority.csv, excluded_activities.csv,
    compliance_matrix_df.csv, constraints_df.csv,
    crew_restrictions.csv, Crew_Onsite_App.csv            (header only: no leave, no check-ins yet)

Every change is explained in Progress/real_data_understanding/03_data_changes.md.
The script uses only the standard library and is deterministic.

    python scripts/build_optiflux_v2_data.py
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "optiflux_v2"

# ---------------------------------------------------------------------------
# Rules: activities_df
# ---------------------------------------------------------------------------

# Renames from demand_changes.txt: "NE task = replace by NE Crew", "replace By Shed with By Ship".
RENAMES = {
    "A12": {"Activity Name": "BY Ship", "Activity Head": "BY Ship"},
    "A16": {"Activity Name": "NE Crew", "Activity Head": "NE Crew"},
}
OLD_NAMES = {"BY Shed": "BY Ship", "NE Task": "NE Crew"}

# The upload has two rows with Activity ID A08 (Work Train, Work Train CO).
# Activity ID is a key, so Work Train CO gets the next free ID.
DUPLICATE_ID_FIX = {("A08", "Work Train CO"): "A17"}


def _non_work(aid: str, name: str, group: str, head: str, typ: str) -> dict[str, str]:
    return {
        "Activity ID": aid, "Activity Name": name, "Activity Group": group, "Activity Head": head,
        "Activity Type": typ, "TEA Required": "", "Can Be Moved": "", "Start Depot": "", "End Depot": "",
        "Mentor Required": "No", "Roles/Job": "", "Currency Threshold": "",
    }  # fmt: skip


EXTRA_ACTIVITIES = [
    # general_rules_assignment.txt: "relief: ... activity name and head would be both relief,
    # not assigned to any activity, just kept as extras".
    _non_work("A90", "Relief", "Reserve", "Relief", "Relief"),
    # general_rules_assignment.txt: FIFO "travel_in and travel_out ... when exactly they are coming and leaving".
    _non_work("A91", "Travel In", "Travel", "Travel", "Travel"),
    _non_work("A92", "Travel Out", "Travel", "Travel", "Travel"),
    # gap_filling_rules.md R1: the off-block between two swings gets rows with Activity Name Off, Head RR.
    _non_work("A93", "Off", "Rest", "RR", "Off"),
]

# ---------------------------------------------------------------------------
# Rules: activity_demand_df  (demand_changes.txt)
# ---------------------------------------------------------------------------


def every(step_h: int, first_h: int) -> list[int]:
    """Start hours every ``step_h`` hours over a day, beginning at ``first_h``."""
    return sorted((first_h + k * step_h) % 24 for k in range(24 // step_h))


HOURLY = every(1, 0)

# Activity ID -> list of (start hour, people). One row per start time.
DEMAND_RULES: dict[str, list[tuple[int, int]]] = {
    "A01": [(h, 1) for h in HOURLY],  # Haskett Mainline: 1 person per hour
    "A03": [(h, 1) for h in HOURLY],  # Yarmouth Mainline: 1 person per hour
    "A05": [(h, 1) for h in every(3, 0)],  # CAM LOT: 1 per 3 h from 00:00
    "A06": [(h, 1) for h in HOURLY],  # Madison Crew: 1 person per hour
    "A07": [(h, 1) for h in every(3, 1)],  # Madison Yard: 1 per 3 h from 01:00
    "A08": [(22, 2)],  # Work Train: 2 people at 22:00
    "A09": [(10, 1)],  # Fuel Train: 1 person at 10:00
    "A10": [(10, 1)],  # Fuel Return: 1 person at 10:00
    "A11": [(h, 1) for h in every(3, 4)],  # Bethway Join/FI Crew: 1 per 3 h from 04:00
    "A12": [(h, 1) for h in (4, 9, 16, 21)],  # BY Ship: "similar to NE Ship"
    "A13": [(h, 1) for h in HOURLY],  # Nelaway Driver: 1 person per hour
    "A14": [(h, 1) for h in every(3, 1)],  # Nelaway Shuttle Driver: 1 per 3 h from 01:00
    "A15": [(h, 1) for h in (4, 9, 16, 21)],  # NE Ship: 04:00, 09:00, 16:00, 21:00, 1 each
    # NE Crew: 4 people at 04, 07, 09, 16, 19, 21; 2 people at 00 and 12.
    "A16": sorted([(h, 4) for h in (4, 7, 9, 16, 19, 21)] + [(h, 2) for h in (0, 12)]),
    # Not in the new rules: kept from the uploaded demand table, start time only (open question Q1).
    "A02": [(17, 1)],  # Haskett Mainline CO
    "A04": [(5, 1), (17, 1)],  # Yarmouth Mainline CO
}

# ---------------------------------------------------------------------------
# Rules: constraints_df  (settings read by scripts/roster_making.py)
# ---------------------------------------------------------------------------

CONSTRAINTS = [
    # Planning horizon of the initial roster (open question Q11): one full FIFO cycle.
    ("Planning Horizon Start", "2026-11-01", "Active"),
    # gap_filling_rules.md R3: the full month of November.
    ("Planning Horizon Days", "30", "Active"),
    # gap_filling_rules.md G1: the roster ran from the 1st; the solver may only change rows from this date on.
    ("Solver Start Date", "2026-11-06", "Active"),
    # demand_changes.txt: "end time = 12 hrs".
    ("Shift Length Hours", "12", "Active"),
    # Carried over from the previous model (briefing section 9).
    ("Ordinary Rest Hours", "11", "Active"),
    ("Transition Rest Hours", "23", "Active"),
    ("Day Shift Window", "03:00-15:00", "Active"),
    ("Max Duties Per Day", "1", "Active"),
    # Swing patterns from the briefing (FIFO "swing 14 days", Residential "swing 6 days"); open question Q3.
    ("FIFO Work/Off Days", "14/14", "Active"),
    ("Residential Work/Off Days", "6/6", "Active"),
    # general_rules_assignment.txt: "for residential: first shift should be day shift".
    ("Residential First Shift Day", "", "Active"),
    # general_rules_assignment.txt: FIFO travel_in before the first shift, travel_out after the last; random for now.
    ("FIFO Travel", "", "Active"),
    ("Travel Gap Hours", "1-4", "Active"),
    ("Travel Duration Hours", "2-6", "Active"),
    ("Base Return At Swing End", "", "Active"),
    # general_rules_assignment.txt: "initial roster (without any leaves)".
    ("Leave In Initial Roster", "", "Inactive"),
    # general_rules_assignment.txt: "add rows of no activity ... overtime {not considered for now}".
    ("No Activity Rows", "", "Inactive"),
    # Share of each activity's shift lines given an extra Excess line (see 05_roster_generation.md).
    ("Excess Line Fraction", "0.10", "Active"),
    # gap_filling_rules.md G2: leave per type, as a share of the crew (15% in total).
    ("Leave Full Swing Fraction", "0.05", "Active"),
    ("Leave Day Shifts Fraction", "0.02", "Active"),
    ("Leave Night Shifts Fraction", "0.03", "Active"),
    ("Leave Random Fraction", "0.05", "Active"),
    # Previous model, for the recovery step: Relief may start at any time, Excess may move by 1 h.
    ("Relief Allowed Start Offsets", "ANY", "Active"),
    ("Excess Allowed Start Offsets", "-60;0;60", "Active"),
    # gap_filling_rules.md F1/F3: Demand crew may move to another seat by lift-up/layback of at most 1 h, and a
    # block (the day or night half of a swing) may change its start time at most once, by at most 60 minutes.
    ("Demand Allowed Start Offsets", "-60;0;60", "Active"),
    ("Max Start Changes Per Block", "1", "Active"),
    ("Max Start Change Minutes", "60", "Active"),
    # Per-swing activity-head shift limits from activity_priority.csv (Max Resident Shifts / Max FIFO Shifts).
    ("Activity Head Max Shifts", "", "Active"),
    # gap_filling_rules.md R4: every row is unlocked; locking is a later application feature.
    ("Default Is Locked", "False", "Active"),
    ("Random Seed", "2026", "Active"),
]

# ---------------------------------------------------------------------------


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_activities(source: Path) -> tuple[list[str], list[dict[str, str]]]:
    header, rows = read_csv(source / "activities_df.csv")
    out = []
    for r in rows:
        r = dict(r)
        new_id = DUPLICATE_ID_FIX.get((r["Activity ID"], r["Activity Name"]))
        if new_id:
            r["Activity ID"] = new_id
        r.update(RENAMES.get(r["Activity ID"], {}))
        out.append(r)
    out.extend(dict(a) for a in EXTRA_ACTIVITIES)
    dupes = [i for i, n in Counter(r["Activity ID"] for r in out).items() if n > 1]
    if dupes:
        raise SystemExit(f"duplicate Activity ID after fixes: {dupes}")
    return header, out


def build_demand(activities: list[dict[str, str]]) -> tuple[list[str], list[dict[str, str]]]:
    by_id = {a["Activity ID"]: a for a in activities}
    missing = sorted(set(DEMAND_RULES) - set(by_id))
    if missing:
        raise SystemExit(f"demand rules refer to unknown activities: {missing}")
    header = ["Demand ID", "Shift", "Demand", "Is Active", "Activity ID", "Activity Name", "Activity Head"]
    rows = []
    for aid in sorted(DEMAND_RULES):
        for hour, people in sorted(DEMAND_RULES[aid]):
            a = by_id[aid]
            rows.append(
                {
                    "Demand ID": f"DM{len(rows) + 1:03d}",
                    "Shift": f"{hour:02d}:00",
                    "Demand": str(people),
                    "Is Active": "Yes",
                    "Activity ID": aid,
                    "Activity Name": a["Activity Name"],
                    "Activity Head": a["Activity Head"],
                }
            )
    return header, rows


def build_priority(old: Path, activities: list[dict[str, str]]) -> tuple[list[str], list[dict[str, str]]]:
    """Old priority order with the renames; every work head must appear exactly once.

    `Max Resident Shifts` (6) and `Max FIFO Shifts` (14) default to the full swing work-day lengths
    from constraints_df.csv (`Residential Work/Off Days = 6/6`, `FIFO Work/Off Days = 14/14`).
    """
    _, rows = read_csv(old / "activity_priority.csv")
    heads = [
        OLD_NAMES.get(r["Activity Head"], r["Activity Head"]) for r in sorted(rows, key=lambda r: int(r["Priority"]))
    ]
    work_heads = {a["Activity Head"] for a in activities if a["Activity Type"] not in ("Relief", "Travel", "Off")}
    missing = sorted(work_heads - set(heads))
    unknown = sorted(set(heads) - work_heads)
    if missing or unknown:
        raise SystemExit(f"priority list: missing heads {missing}, unknown heads {unknown}")
    header = ["Priority", "Activity Head", "Max Resident Shifts", "Max FIFO Shifts"]
    return header, [
        {"Priority": str(i), "Activity Head": h, "Max Resident Shifts": "6", "Max FIFO Shifts": "14"}
        for i, h in enumerate(heads, start=1)
    ]


def build_assignment_type_priority() -> tuple[list[str], list[dict[str, str]]]:
    """Assignment-type fill priority order: Relief (1) > Excess (2) > Demand (3)."""
    header = ["Priority", "Assignment Type"]
    rows = [
        {"Priority": "1", "Assignment Type": "Relief"},
        {"Priority": "2", "Assignment Type": "Excess"},
        {"Priority": "3", "Assignment Type": "Demand"},
    ]
    return header, rows


def build_compliance(old: Path, activities: list[dict[str, str]]) -> tuple[list[str], list[dict[str, str]]]:
    """Old compliance matrix with the renames; old A17 (Route Learning) dropped; Work Train CO copies Work Train."""
    header, rows = read_csv(old / "compliance_matrix_df.csv")
    by_id = {a["Activity ID"]: a for a in activities}
    out = []
    for r in rows:
        if r["Activity ID"] == "A17":  # old A17 = Route Learning, removed from the activities
            continue
        a = by_id[r["Activity ID"]]
        row = dict(r, **{"Activity Name": a["Activity Name"], "Activity Head": a["Activity Head"]})
        for old_name, new_name in OLD_NAMES.items():
            row["Competency"] = row["Competency"].replace(old_name, new_name)
        out.append(row)
        if r["Activity ID"] == "A08":  # Work Train CO needs what Work Train needs
            co = by_id["A17"]
            copy = dict(row, **{"Activity ID": "A17", "Activity Name": co["Activity Name"]})
            if copy["Competency LMS Code"] == "AC-A08":
                copy.update({"Competency LMS Code": "AC-A17", "Competency": "Work Train CO Sign-off"})
            out.append(copy)
    out.sort(key=lambda r: r["Activity ID"])
    work_ids = {a["Activity ID"] for a in activities if a["Activity Type"] not in ("Relief", "Travel", "Off")}
    missing = sorted(work_ids - {r["Activity ID"] for r in out})
    if missing:
        raise SystemExit(f"compliance matrix has no rows for {missing}")
    return header, out


def summarise(activities, demand) -> str:
    depot_of = {a["Activity ID"]: a["Start Depot"] for a in activities}
    per_act: dict[str, int] = defaultdict(int)
    per_depot: dict[str, int] = defaultdict(int)
    for d in demand:
        per_act[f"{d['Activity ID']} {d['Activity Name']}"] += int(d["Demand"])
        per_depot[depot_of[d["Activity ID"]]] += int(d["Demand"])
    lines = [f"activities: {len(activities)} rows"]
    lines.append(f"demand: {len(demand)} rows, {sum(per_act.values())} crew-shifts per day")
    lines += [f"  {k:32s} {v:3d}" for k, v in per_act.items()]
    lines.append("demand per day by start depot: " + ", ".join(f"{k}={v}" for k, v in sorted(per_depot.items())))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DIR, help="folder holding source/ (default: %(default)s)")
    args = p.parse_args(argv)
    out = args.data_dir
    source = out / "source"
    old = source / "from_generated_small"

    act_header, activities = build_activities(source)
    dem_header, demand = build_demand(activities)
    write_csv(out / "activities_df.csv", act_header, activities)
    write_csv(out / "activity_demand_df.csv", dem_header, demand)
    write_csv(out / "activity_priority.csv", *build_priority(old, activities))
    write_csv(out / "assignment_type_priority.csv", *build_assignment_type_priority())
    write_csv(out / "compliance_matrix_df.csv", *build_compliance(old, activities))
    write_csv(out / "excluded_activities.csv", ["Activity ID", "Activity Name"], [])
    write_csv(
        out / "constraints_df.csv",
        ["Constraint", "Value", "Status"],
        [{"Constraint": c, "Value": v, "Status": s} for c, v, s in CONSTRAINTS],
    )
    # Per-person tables that stay empty for the initial roster. Keyed by User Id (CM Id is not used).
    write_csv(
        out / "crew_restrictions.csv",
        ["Restriction ID", "User Id", "Restriction Type", "Activity Head", "Effective From", "Effective To", "Reason"],
        [],
    )
    write_csv(out / "Crew_Onsite_App.csv", ["Record ID", "User Id", "Date", "Location", "Status"], [])
    print(summarise(activities, demand))


if __name__ == "__main__":
    main()
