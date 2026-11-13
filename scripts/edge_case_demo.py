#!/usr/bin/env python3
"""Build a self-contained edge-case dataset and run Option Generation + CP-SAT across all rule/strategy modes.

This script creates a small, realistic OptiFlux v2 dataset under `CP-SAT/outputs/edge_case_demo/data/`
and `CP-SAT/outputs/edge_case_demo/roster_full_gaps.csv` that tests every edge case of:

  1. Residential start-time restriction (22:00-02:00):
     - U_RES_2100: Residential Relief filling a 21:00 gap -> ALLOWED (just before 22:00)
     - U_RES_2200: Residential Relief filling a 22:00 gap -> BLOCKED when on, ALLOWED when off
     - U_RES_0100: Residential Relief filling a 01:00 gap -> BLOCKED when on, ALLOWED when off
     - U_RES_0200: Residential Relief filling a 02:00 gap -> ALLOWED (exact 02:00 boundary)
     - U_RES_KEEP: Residential Demand keeping an unchanged 23:00 shift -> KEPT & VALIDATED (exception)
     - U_RES_SAME: Residential Excess taking same-seat 23:00 gap (offset 0) -> ALLOWED at cost 0 (exception)
     - U_FIFO_2300: FIFO Relief filling a 23:00 gap -> ALLOWED (restriction is Residential-only)

  2. Relief-only Day/Night transition (with 23h transition rest):
     - U_REL_D2N:    Relief Day (04:00-16:00) -> Demand Night next day (16:00-04:00, 24h rest) -> ALLOWED
     - U_DEM_D2N:    Demand Day (04:00-16:00) -> Excess Night next day filling 17:00 gap (25h rest)
                     -> BLOCKED when relief_only_day_night_transition=true, ALLOWED when false
     - U_REL_SHORT:  Relief Day (10:00-22:00) -> Demand Night next day (16:00-04:00, 18h rest < 23h)
                     -> BLOCKED in both modes (23h transition rest preserved)

  3. Activity-head priorities & 3 optimization strategies (none / weighted / lexicographic):
     - U_PRIO_DECIDER (FIFO Relief on 2026-11-20 & 2026-11-21, standby 09:00) can fill at most 2 gaps
       across 2 days. Because F3 allows at most 60m start-time change between consecutive Day shifts:
         * Path N (09:00 -> 09:00): fills 2x BY Ship (Priority 14, weight 1+1=2, cost 10+10=20)
           -> Chosen by `none` (minimum cost for max coverage 2)
         * Path W (07:00 -> 07:00): fills 2x NE Crew (Priority 2, weight 13+13=26, cost 12+12=24)
           -> Chosen by `weighted` (maximum weighted priority 26 for max coverage 2)
         * Path L (03:00 -> 04:00): fills 1x Madison Crew (Priority 1) + 1x BY Ship (Priority 14)
           (weight 14+1=15, cost 16+15=31)
           -> Chosen by `lexicographic` (maximizes Priority 1 first, then Priority 14)

Usage:
    python scripts/edge_case_demo.py
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_DATA = ROOT / "data" / "optiflux_v2"
DEMO_ROOT = ROOT / "CP-SAT" / "outputs" / "edge_case_demo"
DEMO_DATA = DEMO_ROOT / "data"
GAPS_CSV = DEMO_ROOT / "roster_full_gaps.csv"

ROSTER_FULL_HEADER = [
    "Assignment ID", "User Id", "New User Id", "Optimised User Id",
    "Start Date", "End Date", "Shift Start Time", "Shift End Time",
    "Activity ID", "Activity Name", "Is Locked", "Activity Head",
    "Activity Type", "Activity Group", "Assignment Type", "Demand ID",
    "Start Location", "End Location", "Line ID", "Swing", "In Horizon",
    "Leave Type", "Is Gap", "Is_locked_gap",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def make_row(
    aid: str,
    user: str,
    new_user: str,
    day: str,
    start_hm: str,
    act_id: str,
    act_name: str,
    act_head: str,
    act_type: str,
    act_group: str,
    assign_type: str,
    demand_id: str = "",
    loc: str = "Haskett",
    line_id: str = "L_DEMO",
    swing: str = "1",
    leave_type: str = "",
    is_gap: str = "False",
    is_locked_gap: str = "",
) -> dict[str, str]:
    start_dt = datetime.fromisoformat(f"{day}T{start_hm}")
    end_dt = start_dt + timedelta(hours=12)
    return {
        "Assignment ID": aid,
        "User Id": user,
        "New User Id": new_user,
        "Optimised User Id": "",
        "Start Date": start_dt.strftime("%Y-%m-%d"),
        "End Date": end_dt.strftime("%Y-%m-%d"),
        "Shift Start Time": start_dt.strftime("%H:%M"),
        "Shift End Time": end_dt.strftime("%H:%M"),
        "Activity ID": act_id,
        "Activity Name": act_name,
        "Is Locked": "False",
        "Activity Head": act_head,
        "Activity Type": act_type,
        "Activity Group": act_group,
        "Assignment Type": assign_type,
        "Demand ID": demand_id,
        "Start Location": loc,
        "End Location": loc,
        "Line ID": line_id,
        "Swing": swing,
        "In Horizon": "Yes",
        "Leave Type": leave_type,
        "Is Gap": is_gap,
        "Is_locked_gap": is_locked_gap,
    }


def build_demo_dataset() -> None:
    if DEMO_ROOT.exists():
        shutil.rmtree(DEMO_ROOT)
    DEMO_DATA.mkdir(parents=True, exist_ok=True)

    # Copy base schema tables from data/optiflux_v2
    for name in (
        "activities_df.csv", "activity_demand_df.csv", "activity_priority.csv",
        "assignment_type_priority.csv", "compliance_matrix_df.csv", "constraints_df.csv",
        "Crew_Onsite_App.csv", "crew_restrictions.csv", "excluded_activities.csv",
        "roster_lines.csv",
    ):
        shutil.copy(BASE_DATA / name, DEMO_DATA / name)

    # Define demo crew members
    crew_specs = [
        # (User Id, Classification, Role, Depot)
        ("U_GAP_OWNER", "FIFO", "Driver", "Haskett"),
        ("U_RES_2100", "Residential", "Driver", "Haskett"),
        ("U_RES_2200", "Residential", "Driver", "Haskett"),
        ("U_RES_0100", "Residential", "Driver", "Haskett"),
        ("U_RES_0200", "Residential", "Driver", "Haskett"),
        ("U_RES_KEEP", "Residential", "Driver", "Haskett"),
        ("U_RES_SAME", "Residential", "Driver", "Haskett"),
        ("U_FIFO_2300", "FIFO", "Driver", "Haskett"),
        ("U_REL_D2N", "Residential", "Driver", "Haskett"),
        ("U_DEM_D2N", "Residential", "Driver", "Haskett"),
        ("U_REL_SHORT", "Residential", "Driver", "Haskett"),
        ("U_PRIO_DECIDER", "FIFO", "Driver", "Haskett"),
        ("U_RES_LIMIT", "Residential", "Driver", "Nelaway"),
        ("U_FIFO_LIMIT", "FIFO", "Driver", "Nelaway"),
    ]
    all_users = [u for u, _, _, _ in crew_specs]
    crew_rows = [
        {
            "User Id": uid,
            "Classification": cls,
            "Eligibility": "A06;A10;A11;A12;A13;A14;A16",
            "Depot": depot,
            "Role": role,
            "Is Mentor": "Yes",
            "Medical": "Fit",
            "Position": "L_DEMO",
        }
        for uid, cls, role, depot in crew_specs
    ]
    write_csv(
        DEMO_DATA / "crew_master_data_df.csv",
        ["User Id", "Classification", "Eligibility", "Depot", "Role", "Is Mentor", "Medical", "Position"],
        crew_rows,
    )

    # Eligibility matrix: certify all demo crew on all activities used
    elig_rows = []
    for row in read_csv(BASE_DATA / "eligibility_matrix.csv"):
        updated = dict(row)
        updated["Eligible Count"] = str(len(all_users))
        updated["Eligible User Ids"] = ";".join(all_users)
        elig_rows.append(updated)
    write_csv(
        DEMO_DATA / "eligibility_matrix.csv",
        ["Activity Head", "Activity ID", "Activity Name", "Eligible Count", "Eligible User Ids"],
        elig_rows,
    )

    # Currency & competencies: valid for all demo crew
    comp_rows = []
    for row in read_csv(BASE_DATA / "compliance_matrix_df.csv"):
        for uid in all_users:
            comp_rows.append({
                "User Id": uid,
                "Competency": row["Competency"],
                "Competency LMS Code": row["Competency LMS Code"],
                "Expiry Date": "2027-12-31",
                "status": "Valid",
            })
    write_csv(
        DEMO_DATA / "crew_competencies_df.csv",
        ["User Id", "Competency", "Competency LMS Code", "Expiry Date", "status"],
        comp_rows,
    )

    curr_rows = []
    cid = 1
    for uid in all_users:
        for head in (
            "Haskett Mainline", "Yarmouth Mainline", "Fuel Train", "Fuel Return",
            "Madison Crew", "NE Crew", "BY Ship", "Bethway Join/FI Crew",
            "Nelaway Driver", "Nelaway Shuttle Driver",
        ):
            curr_rows.append({
                "Currency ID": f"CU{cid:04d}",
                "User Id": uid,
                "Activity Head": head,
                "Last Performed Date": "2026-10-25",
                "Last Activity ID": "A06",
            })
            cid += 1
    write_csv(
        DEMO_DATA / "crew_currency_df.csv",
        ["Currency ID", "User Id", "Activity Head", "Last Performed Date", "Last Activity ID"],
        curr_rows,
    )

    rows: list[dict[str, str]] = []
    seq = 1

    def add_row(**kwargs) -> None:
        nonlocal seq
        rows.append(make_row(aid=f"AS_DEMO_{seq:04d}", **kwargs))
        seq += 1

    def add_gap(day: str, start_hm: str, act_id: str, act_name: str, act_head: str, act_type: str, demand_id: str, swing: str, loc: str = "Haskett") -> None:
        add_row(
            user="U_GAP_OWNER", new_user="", day=day, start_hm=start_hm,
            act_id=act_id, act_name=act_name, act_head=act_head, act_type=act_type,
            act_group="Yard", assign_type="Demand", demand_id=demand_id,
            loc=loc, swing=swing, leave_type="Random", is_gap="True", is_locked_gap="False",
        )

    # -------------------------------------------------------------------------
    # GROUP 1: Residential Start-Time Restriction (22:00 to 02:00)
    # Note: Residential swings must start with a Day shift (R1), so each Residential
    # crew member works a Day shift on Day 1, then transitions via Relief (24h+ rest)
    # to test the target start time on Day 2/3.
    # -------------------------------------------------------------------------

    # 1A. U_RES_2100: Day shift on Nov 6 (06:00), then Relief on Nov 7 that can fill 21:00 gap on Nov 7
    add_row(user="U_RES_2100", new_user="U_RES_2100", day="2026-11-06", start_hm="06:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_row(user="U_RES_2100", new_user="U_RES_2100", day="2026-11-07", start_hm="21:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_gap(day="2026-11-07", start_hm="21:00", act_id="A06", act_name="Madison Crew",
            act_head="Madison Crew", act_type="Crew", demand_id="DM081", swing="10")

    # 1B. U_RES_2200: Day shift on Nov 8 (06:00), then Relief on Nov 9 facing 22:00 gap on Nov 9
    add_row(user="U_RES_2200", new_user="U_RES_2200", day="2026-11-08", start_hm="06:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_row(user="U_RES_2200", new_user="U_RES_2200", day="2026-11-09", start_hm="22:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_gap(day="2026-11-09", start_hm="22:00", act_id="A06", act_name="Madison Crew",
            act_head="Madison Crew", act_type="Crew", demand_id="DM082", swing="11")

    # 1C. U_RES_0100: Day shift on Nov 9 (03:00-15:00), then Relief on Nov 11 facing 01:00 gap on Nov 11
    add_row(user="U_RES_0100", new_user="U_RES_0100", day="2026-11-09", start_hm="03:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_row(user="U_RES_0100", new_user="U_RES_0100", day="2026-11-11", start_hm="01:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_gap(day="2026-11-11", start_hm="01:00", act_id="A06", act_name="Madison Crew",
            act_head="Madison Crew", act_type="Crew", demand_id="DM061", swing="12")

    # 1D. U_RES_0200: Day shift on Nov 10 (03:00-15:00), then Relief on Nov 12 facing 02:00 gap on Nov 12
    add_row(user="U_RES_0200", new_user="U_RES_0200", day="2026-11-10", start_hm="03:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_row(user="U_RES_0200", new_user="U_RES_0200", day="2026-11-12", start_hm="02:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_gap(day="2026-11-12", start_hm="02:00", act_id="A06", act_name="Madison Crew",
            act_head="Madison Crew", act_type="Crew", demand_id="DM062", swing="13")

    # 1E. U_RES_KEEP: Existing Residential Demand shift at 23:00 (unchanged keep exception)
    add_row(user="U_RES_KEEP", new_user="U_RES_KEEP", day="2026-11-06", start_hm="06:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_row(user="U_RES_KEEP", new_user="U_RES_KEEP", day="2026-11-07", start_hm="23:00",
            act_id="A06", act_name="Madison Crew", act_head="Madison Crew", act_type="Crew", act_group="Yard",
            assign_type="Demand", demand_id="DM083", swing="1")

    # 1F. U_RES_SAME: Residential Excess already on A06 @ 23:00 on Nov 13 (same-seat unchanged exception)
    add_row(user="U_RES_SAME", new_user="U_RES_SAME", day="2026-11-12", start_hm="06:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_row(user="U_RES_SAME", new_user="U_RES_SAME", day="2026-11-13", start_hm="23:00",
            act_id="A06", act_name="Madison Crew", act_head="Madison Crew", act_type="Crew", act_group="Yard",
            assign_type="Excess", demand_id="DM083", swing="1")
    add_gap(day="2026-11-13", start_hm="23:00", act_id="A06", act_name="Madison Crew",
            act_head="Madison Crew", act_type="Crew", demand_id="DM083", swing="14")

    # 1G. U_FIFO_2300: FIFO Relief filling 23:00 gap on Nov 14 -> ALLOWED
    add_row(user="U_FIFO_2300", new_user="U_FIFO_2300", day="2026-11-14", start_hm="23:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_gap(day="2026-11-14", start_hm="23:00", act_id="A06", act_name="Madison Crew",
            act_head="Madison Crew", act_type="Crew", demand_id="DM083", swing="15")

    # -------------------------------------------------------------------------
    # GROUP 2: Relief-Only Day/Night Transition & 23h Transition Rest
    # -------------------------------------------------------------------------

    # 2A. U_REL_D2N: Relief Day (Nov 15 04:00-16:00) -> Night gap (Nov 16 16:00-04:00, 24h rest) -> ALLOWED
    add_row(user="U_REL_D2N", new_user="U_REL_D2N", day="2026-11-15", start_hm="04:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_row(user="U_REL_D2N", new_user="U_REL_D2N", day="2026-11-16", start_hm="16:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_gap(day="2026-11-16", start_hm="16:00", act_id="A06", act_name="Madison Crew",
            act_head="Madison Crew", act_type="Crew", demand_id="DM076", swing="16")

    # 2B. U_DEM_D2N: Demand Day (Nov 17 04:00-16:00) -> Relief row on Nov 18 facing Night gap (Nov 18 16:00, 24h rest)
    # Blocked when relief_only_day_night_transition=true because Nov 17 shift is Demand, not Relief!
    add_row(user="U_DEM_D2N", new_user="U_DEM_D2N", day="2026-11-17", start_hm="04:00",
            act_id="A06", act_name="Madison Crew", act_head="Madison Crew", act_type="Crew", act_group="Yard",
            assign_type="Demand", demand_id="DM064", swing="1")
    add_row(user="U_DEM_D2N", new_user="U_DEM_D2N", day="2026-11-18", start_hm="16:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_gap(day="2026-11-18", start_hm="16:00", act_id="A11", act_name="Bethway Join/FI Crew",
            act_head="Bethway Join/FI Crew", act_type="Crew", demand_id="DM100", swing="17")

    # 2C. U_REL_SHORT: Relief Day (Nov 18 10:00-22:00) -> Night gap (Nov 19 16:00, 18h rest < 23h) -> ALWAYS BLOCKED
    add_row(user="U_REL_SHORT", new_user="U_REL_SHORT", day="2026-11-18", start_hm="10:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_row(user="U_REL_SHORT", new_user="U_REL_SHORT", day="2026-11-19", start_hm="16:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_gap(day="2026-11-19", start_hm="16:00", act_id="A11", act_name="Bethway Join/FI Crew",
            act_head="Bethway Join/FI Crew", act_type="Crew", demand_id="DM100", swing="18")

    # -------------------------------------------------------------------------
    # GROUP 3: Priority Strategy Comparison (none vs weighted vs lexicographic)
    # U_PRIO_DECIDER works Nov 20 and Nov 21 (Relief standby at 09:00 on both days).
    # Because F3 restricts consecutive Day-block shifts to <= 60 min start-time change:
    #   - Path N (09:00 -> 09:00): 2x A12 BY Ship (Priority 14, weight 1+1=2, cost 10+10=20)
    #   - Path W (07:00 -> 07:00): 2x A16 NE Crew (Priority 2, weight 13+13=26, cost 12+12=24)
    #   - Path L (03:00 -> 04:00): 1x A06 Madison Crew (Priority 1, weight 14, cost 16)
    #                            + 1x A12 BY Ship (Priority 14, weight 1, cost 15) -> weight 15, cost 31
    # -------------------------------------------------------------------------
    add_row(user="U_PRIO_DECIDER", new_user="U_PRIO_DECIDER", day="2026-11-20", start_hm="09:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")
    add_row(user="U_PRIO_DECIDER", new_user="U_PRIO_DECIDER", day="2026-11-21", start_hm="09:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", swing="1")

    # Path L gaps (03:00 Madison Crew P1 on Nov 20; 04:00 BY Ship P14 on Nov 21)
    add_gap(day="2026-11-20", start_hm="03:00", act_id="A06", act_name="Madison Crew",
            act_head="Madison Crew", act_type="Crew", demand_id="DM063", swing="20")
    add_gap(day="2026-11-21", start_hm="04:00", act_id="A12", act_name="BY Ship",
            act_head="BY Ship", act_type="Shed", demand_id="DM103", swing="21")

    # Path W gaps (07:00 NE Crew P2 on Nov 20 and Nov 21)
    add_gap(day="2026-11-20", start_hm="07:00", act_id="A16", act_name="NE Crew",
            act_head="NE Crew", act_type="Crew", demand_id="DM145", swing="22")
    add_gap(day="2026-11-21", start_hm="07:00", act_id="A16", act_name="NE Crew",
            act_head="NE Crew", act_type="Crew", demand_id="DM145", swing="23")

    # Path N gaps (09:00 BY Ship P14 on Nov 20 and Nov 21)
    add_gap(day="2026-11-20", start_hm="09:00", act_id="A12", act_name="BY Ship",
            act_head="BY Ship", act_type="Shed", demand_id="DM104", swing="24")
    add_gap(day="2026-11-21", start_hm="09:00", act_id="A12", act_name="BY Ship",
            act_head="BY Ship", act_type="Shed", demand_id="DM104", swing="25")

    # -------------------------------------------------------------------------
    # GROUP 4: Per-Swing Activity-Head Shift Limits (Max Resident Shifts / Max FIFO Shifts)
    # Isolated at Nelaway depot using A13 Nelaway Driver and A14 Nelaway Shuttle Driver:
    #   - U_RES_LIMIT (Residential, Nelaway):
    #       * Swing 1 (Nov 6, 7, 8 @ 09:00 Relief): faces 3x Nelaway Driver @ 09:00 (cost 10)
    #         plus 2x Nelaway Shuttle Driver @ 10:00 on Nov 7, 8 (cost 11, <= 60 min jump for F3).
    #       * Swing 2 (Nov 16 @ 10:00 Relief, after 7.5d >= 6d off): faces 1x Nelaway Driver @ 10:00.
    #   - U_FIFO_LIMIT (FIFO, Nelaway):
    #       * Swing 1 (Nov 23, 24, 25 @ 10:00 Relief): faces 3x Nelaway Shuttle Driver @ 10:00.
    # -------------------------------------------------------------------------
    for day in ("2026-11-06", "2026-11-07", "2026-11-08"):
        add_row(user="U_RES_LIMIT", new_user="U_RES_LIMIT", day=day, start_hm="09:00",
                act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
                assign_type="Relief", loc="Nelaway", swing="1")
    add_gap(day="2026-11-06", start_hm="09:00", act_id="A13", act_name="Nelaway Driver",
            act_head="Nelaway Driver", act_type="Driving", demand_id="DM116", swing="30", loc="Nelaway")
    add_gap(day="2026-11-07", start_hm="09:00", act_id="A13", act_name="Nelaway Driver",
            act_head="Nelaway Driver", act_type="Driving", demand_id="DM116", swing="31", loc="Nelaway")
    add_gap(day="2026-11-08", start_hm="09:00", act_id="A13", act_name="Nelaway Driver",
            act_head="Nelaway Driver", act_type="Driving", demand_id="DM116", swing="32", loc="Nelaway")
    add_gap(day="2026-11-07", start_hm="10:00", act_id="A14", act_name="Nelaway Shuttle Driver",
            act_head="Nelaway Shuttle Driver", act_type="Driving", demand_id="DM134", swing="33", loc="Nelaway")
    add_gap(day="2026-11-08", start_hm="10:00", act_id="A14", act_name="Nelaway Shuttle Driver",
            act_head="Nelaway Shuttle Driver", act_type="Driving", demand_id="DM134", swing="34", loc="Nelaway")

    # U_RES_LIMIT Swing 2 (Nov 16 @ 10:00, independent swing)
    add_row(user="U_RES_LIMIT", new_user="U_RES_LIMIT", day="2026-11-16", start_hm="10:00",
            act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
            assign_type="Relief", loc="Nelaway", swing="2")
    add_gap(day="2026-11-16", start_hm="10:00", act_id="A13", act_name="Nelaway Driver",
            act_head="Nelaway Driver", act_type="Driving", demand_id="DM117", swing="35", loc="Nelaway")

    # U_FIFO_LIMIT Swing 1 (Nov 23, 24, 25 @ 10:00)
    for day, sw_gap in (("2026-11-23", "36"), ("2026-11-24", "37"), ("2026-11-25", "38")):
        add_row(user="U_FIFO_LIMIT", new_user="U_FIFO_LIMIT", day=day, start_hm="10:00",
                act_id="A90", act_name="Relief", act_head="Relief", act_type="Relief", act_group="Reserve",
                assign_type="Relief", loc="Nelaway", swing="1")
        add_gap(day=day, start_hm="10:00", act_id="A14", act_name="Nelaway Shuttle Driver",
                act_head="Nelaway Shuttle Driver", act_type="Driving", demand_id="DM134", swing=sw_gap, loc="Nelaway")

    write_csv(GAPS_CSV, ROSTER_FULL_HEADER, rows)
    roster_df_cols = [
        c for c in ROSTER_FULL_HEADER
        if c not in ("New User Id", "Optimised User Id", "Leave Type", "Is Gap", "Is_locked_gap")
    ]
    write_csv(DEMO_DATA / "roster_df.csv", roster_df_cols, rows)


def run_mode(
    name: str,
    res_restrict: bool,
    relief_trans: bool,
    strategy: str,
    limit_overrides: dict[str, tuple[int, int]] | None = None,
    max_shifts_enabled: bool = True,
) -> dict:
    mode_dir = DEMO_ROOT / f"run_{name}"
    opts_dir = mode_dir / "options"
    out_dir = mode_dir / "cpsat"
    cfg_path = mode_dir / "config.yml"
    mode_dir.mkdir(parents=True, exist_ok=True)
    data_dir = DEMO_DATA
    if limit_overrides or not max_shifts_enabled:
        data_dir = mode_dir / "data"
        if data_dir.exists():
            shutil.rmtree(data_dir)
        shutil.copytree(DEMO_DATA, data_dir)
        if limit_overrides:
            prio_rows = read_csv(data_dir / "activity_priority.csv")
            for r in prio_rows:
                if r["Activity Head"] in limit_overrides:
                    res_lim, fifo_lim = limit_overrides[r["Activity Head"]]
                    r["Max Resident Shifts"] = str(res_lim)
                    r["Max FIFO Shifts"] = str(fifo_lim)
            write_csv(
                data_dir / "activity_priority.csv",
                ["Priority", "Activity Head", "Max Resident Shifts", "Max FIFO Shifts"],
                prio_rows,
            )
        cons_rows = read_csv(data_dir / "constraints_df.csv")
        for r in cons_rows:
            if r["Constraint"] == "Activity Head Max Shifts":
                r["Status"] = "Active" if max_shifts_enabled else "Inactive"
        write_csv(
            data_dir / "constraints_df.csv",
            ["Constraint", "Value", "Status"],
            cons_rows,
        )
    cfg_path.write_text(
        "constraints:\n"
        f"  residential_start_restriction: {str(res_restrict).lower()}\n"
        f"  relief_only_day_night_transition: {str(relief_trans).lower()}\n\n"
        "optimization:\n"
        f"  priority_strategy: {strategy}\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable, "option_generation/generate_options.py",
            "--data-dir", str(data_dir),
            "--roster-full", str(GAPS_CSV),
            "--output-dir", str(opts_dir),
            "--config", str(cfg_path),
        ],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        [
            sys.executable, "CP-SAT/run_gap_filling.py",
            "--data-dir", str(data_dir),
            "--roster-full", str(GAPS_CSV),
            "--options-dir", str(opts_dir),
            "--output-dir", str(out_dir),
            "--config", str(cfg_path),
            "--time-limit", "30",
            "--workers", "2",
        ],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    reassignments = {
        r["Optimised User Id"]: r for r in read_csv(out_dir / "reassignments.csv")
    }
    by_user_fills: dict[str, list[dict[str, str]]] = {}
    for r in read_csv(out_dir / "reassignments.csv"):
        by_user_fills.setdefault(r["Optimised User Id"], []).append(r)
    roster_out = read_csv(out_dir / "roster_full.csv")
    return {
        "name": name,
        "reassignments": reassignments,
        "by_user_fills": by_user_fills,
        "roster_out": roster_out,
        "summary": (out_dir / "summary.md").read_text(encoding="utf-8"),
        "validation": (out_dir / "validation.md").read_text(encoding="utf-8"),
    }


def main() -> None:
    print("Building edge-case dataset in:", DEMO_ROOT.relative_to(ROOT))
    build_demo_dataset()

    tight_limits = {
        "Nelaway Driver": (1, 3),          # Max Resident Shifts = 1, Max FIFO Shifts = 3
        "Nelaway Shuttle Driver": (2, 2),  # Max Resident Shifts = 2, Max FIFO Shifts = 2
    }
    modes = [
        ("1_strategy_none", True, True, "none", None, True),
        ("2_strategy_weighted", True, True, "weighted", None, True),
        ("3_strategy_lexicographic", True, True, "lexicographic", None, True),
        ("4_residential_restriction_off", False, True, "none", None, True),
        ("5_relief_transition_off", True, False, "none", None, True),
        ("6_shift_limits_tight_on", True, True, "none", tight_limits, True),
        ("7_shift_limits_tight_off", True, True, "none", tight_limits, False),
    ]
    results = {}
    for name, res, rel, strat, lim_overrides, max_shifts_on in modes:
        results[name] = run_mode(name, res, rel, strat, lim_overrides, max_shifts_on)

    r_none = results["1_strategy_none"]
    r_weighted = results["2_strategy_weighted"]
    r_lex = results["3_strategy_lexicographic"]
    r_res_off = results["4_residential_restriction_off"]
    r_rel_off = results["5_relief_transition_off"]
    r_limits = results["6_shift_limits_tight_on"]
    r_limits_off = results["7_shift_limits_tight_off"]

    def status_of(run: dict, user: str) -> str:
        fills = run["by_user_fills"].get(user, [])
        if not fills:
            return "BLOCKED / UNFILLED"
        return ", ".join(f"FILLED {f['Activity Name']}@{f['Start']} (cost {f['Cost']})" for f in fills)

    print("\n=== 1. RESIDENTIAL START-TIME RESTRICTION (22:00-02:00) EDGE CASES ===")
    for user, label in [
        ("U_RES_2100", "Residential -> 21:00 gap (boundary just before 22:00)"),
        ("U_RES_2200", "Residential -> 22:00 gap (exact start of 22:00 ban)"),
        ("U_RES_0100", "Residential -> 01:00 gap (inside 22:00-02:00 ban)"),
        ("U_RES_0200", "Residential -> 02:00 gap (exact end of 02:00 ban)"),
        ("U_RES_SAME", "Residential Excess -> 23:00 same-seat gap (exception)"),
        ("U_FIFO_2300", "FIFO Relief -> 23:00 gap (FIFO not restricted)"),
    ]:
        print(f"  {user:12s} | {label}")
        print(f"    restriction=ON : {status_of(r_none, user)}")
        print(f"    restriction=OFF: {status_of(r_res_off, user)}")

    keep_rows = [
        r for r in r_none["roster_out"]
        if r["User Id"] == "U_RES_KEEP" and r["Shift Start Time"] == "23:00"
    ]
    print(f"  U_RES_KEEP   | Unchanged Residential Demand @ 23:00 -> Optimised User Id={keep_rows[0]['Optimised User Id']!r}, "
          f"Crew Classification={keep_rows[0]['Crew Classification']!r}")

    print("\n=== 2. RELIEF-ONLY DAY/NIGHT TRANSITION & 23H REST EDGE CASES ===")
    for user, label in [
        ("U_REL_D2N", "Relief Day (04:00-16:00) -> Night (16:00, 24h rest)"),
        ("U_DEM_D2N", "Demand Day (04:00-16:00) -> Night (16:00, 24h rest)"),
        ("U_REL_SHORT", "Relief Day (10:00-22:00) -> Night (16:00, 18h rest < 23h)"),
    ]:
        print(f"  {user:12s} | {label}")
        print(f"    relief_only=ON : {status_of(r_none, user)}")
        print(f"    relief_only=OFF: {status_of(r_rel_off, user)}")

    print("\n=== 3. PRIORITY STRATEGY COMPARISON (U_PRIO_DECIDER) ===")
    for label, run in [
        ("priority_strategy: none         ", r_none),
        ("priority_strategy: weighted     ", r_weighted),
        ("priority_strategy: lexicographic", r_lex),
    ]:
        print(f"  {label} -> {status_of(run, 'U_PRIO_DECIDER')}")

    def swing_status_of(run: dict, user: str, dates: set[str]) -> str:
        fills = [f for f in run["by_user_fills"].get(user, []) if f["Date"] in dates]
        if not fills:
            return "BLOCKED / UNFILLED"
        return ", ".join(f"FILLED {f['Activity Name']}@{f['Date']} {f['Start']} (cost {f['Cost']})" for f in fills)

    print("\n=== 4. PER-SWING ACTIVITY-HEAD SHIFT LIMITS (Max Resident Shifts / Max FIFO Shifts) ===")
    print("  U_RES_LIMIT Swing 1 (Nov 6-8, Residential) | faces 3x Nelaway Driver + 2x Nelaway Shuttle Driver")
    print(f"    default (Res=6, FIFO=14, Status=Active)               : {swing_status_of(r_none, 'U_RES_LIMIT', {'2026-11-06', '2026-11-07', '2026-11-08'})}")
    print(f"    tight   (Driver Res=1, Shuttle Res=2, Status=Active)  : {swing_status_of(r_limits, 'U_RES_LIMIT', {'2026-11-06', '2026-11-07', '2026-11-08'})}")
    print(f"    tight   (Driver Res=1, Shuttle Res=2, Status=Inactive): {swing_status_of(r_limits_off, 'U_RES_LIMIT', {'2026-11-06', '2026-11-07', '2026-11-08'})}")
    print("  U_RES_LIMIT Swing 2 (Nov 16, separate swing) | faces 1x Nelaway Driver (proves per-swing reset)")
    print(f"    default (Res=6, FIFO=14, Status=Active)               : {swing_status_of(r_none, 'U_RES_LIMIT', {'2026-11-16'})}")
    print(f"    tight   (Driver Res=1, Shuttle Res=2, Status=Active)  : {swing_status_of(r_limits, 'U_RES_LIMIT', {'2026-11-16'})}")
    print("  U_FIFO_LIMIT Swing 1 (Nov 23-25, FIFO) | faces 3x Nelaway Shuttle Driver")
    print(f"    default (Res=6, FIFO=14, Status=Active)               : {swing_status_of(r_none, 'U_FIFO_LIMIT', {'2026-11-23', '2026-11-24', '2026-11-25'})}")
    print(f"    tight   (Shuttle FIFO=2, Status=Active)               : {swing_status_of(r_limits, 'U_FIFO_LIMIT', {'2026-11-23', '2026-11-24', '2026-11-25'})}")
    print(f"    tight   (Shuttle FIFO=2, Status=Inactive)             : {swing_status_of(r_limits_off, 'U_FIFO_LIMIT', {'2026-11-23', '2026-11-24', '2026-11-25'})}")

    print("\n=== 5. VALIDATION REPORT SUMMARY ACROSS ALL 7 RUNS ===")
    for name, run in results.items():
        val_lines = [line.strip() for line in run["validation"].splitlines() if "unexpected failure" in line]
        verdict = val_lines[-1] if val_lines else "OK"
        print(f"  {name:30s} -> {verdict}")


if __name__ == "__main__":
    main()
