"""Central registry of discovered file paths, CSV schemas, semantic color palettes, and domain constants.

All column names and file paths in this module are discovered directly from the repository's
`data/optiflux_v2/`, `gap_generation/output/`, `option_generation/output/`, and `CP-SAT/outputs/` schemas.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "optiflux_v2"
DEFAULT_CPSAT_DIR = ROOT / "CP-SAT" / "outputs" / "roster_full"
DEFAULT_OPTIONS_DIR = ROOT / "option_generation" / "output"
DEFAULT_GAP_ROSTER_PATH = ROOT / "gap_generation" / "output" / "roster_full.csv"
DEFAULT_CONFIG_PATH = ROOT / "config.yml"

# Discovered CSV schemas
ROSTER_COLUMNS = (
    "Assignment ID",
    "Demand ID",
    "User Id",
    "Start Date",
    "End Date",
    "Shift Start Time",
    "Shift End Time",
    "Activity ID",
    "Activity Name",
    "Start Location",
    "End Location",
    "Assignment Type",
    "Leave Type",
    "In Horizon",
    "Swing",
    "Is Gap",
    "Is_locked_gap",
    "New User Id",
    "Activity Head",
    "Optimised User Id",
    "Crew Classification",
)

DEMAND_COLUMNS = (
    "Demand ID",
    "Shift",
    "Demand",
    "Start Date",
    "End Date",
    "Rotation Days",
    "Is Active",
    "Activity ID",
    "Activity Name",
    "Activity Head",
    "Start Location",
    "End Location",
)

CREW_MASTER_COLUMNS = (
    "User Id",
    "Home Location",
    "Accommodation Type",
    "Classification",
)

PRIORITY_COLUMNS = (
    "Priority",
    "Activity Head",
    "Max Resident Shifts",
    "Max FIFO Shifts",
)

SEATS_COLUMNS = (
    "Seat Key",
    "Activity ID",
    "Activity Head",
    "Date",
    "Start",
    "End",
    "Start Location",
    "End Location",
    "Demand",
    "Fixed Occupants",
    "Priority",
    "Chain Level",
    "Gap Assignment IDs",
)

SWINGS_COLUMNS = (
    "Swing Key",
    "User Id",
    "Swing",
    "Classification",
    "Home Depot",
    "Status",
    "In Model",
    "Rows",
    "Droppable Rows",
    "Earliest Start",
    "Latest End",
)

OPTIONS_COLUMNS = (
    "Swing Key",
    "User Id",
    "Swing",
    "Row Index",
    "Assignment ID",
    "Source Type",
    "Kind",
    "Seat Key",
    "Excess On Seat",
    "Activity ID",
    "Activity Head",
    "Start",
    "End",
    "Start Location",
    "End Location",
    "Is Day",
    "Standby",
    "Chain Level",
    "Priority",
    "Cost",
)

REJECTIONS_COLUMNS = (
    "Seat Key",
    "Chain Level",
    "Swing Key",
    "Assignment ID",
    "Rule",
    "Detail",
)

UNFILLED_GAPS_COLUMNS = (
    "Seat Key",
    "Chain Level",
    "Activity ID",
    "Activity Head",
    "Priority",
    "Date",
    "Start",
    "End",
    "Demand",
    "Filled",
    "Unfilled",
    "Gap Assignment IDs",
    "Option Count",
)

REASSIGNMENTS_COLUMNS = (
    "Assignment ID",
    "User Id",
    "Swing",
    "Date",
    "Source Type",
    "Change",
    "From Activity",
    "From Start",
    "From End",
    "To Activity",
    "To Start",
    "To End",
    "Seat Key",
    "Chain Level",
)

# Domain constants
WORK_ASSIGNMENT_TYPES = ("Demand", "Excess", "Relief")
NON_WORK_ASSIGNMENT_TYPES = ("Off", "Travel In", "Travel Out")
CREW_CLASSIFICATIONS = ("Residential", "FIFO")

# Accessible semantic color tokens
SEMANTIC_COLORS = {
    "filled": "#10B981",       # Emerald
    "passed": "#10B981",       # Emerald
    "unfilled": "#EF4444",     # Crimson
    "failed": "#EF4444",       # Crimson
    "partial": "#F59E0B",      # Amber
    "warning": "#F59E0B",      # Amber
    "relief": "#F59E0B",       # Amber
    "demand": "#2563EB",       # Royal Blue
    "excess": "#8B5CF6",       # Violet
    "residential": "#2563EB",  # Royal Blue
    "fifo": "#0D9488",         # Teal
    "baseline": "#64748B",     # Slate
}
