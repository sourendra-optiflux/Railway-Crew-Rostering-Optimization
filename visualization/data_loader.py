"""Data loading and validation layer for the Crew Rostering & Gap-Filling Dashboard.

Reads actual solver input and output files without modifying any source CSVs or duplicating solver logic.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data" / "optiflux_v2"
DEFAULT_CPSAT_DIR = ROOT / "CP-SAT" / "outputs" / "roster_full"
DEFAULT_OPTIONS_DIR = ROOT / "option_generation" / "output"
DEFAULT_CONFIG_PATH = ROOT / "config.yml"

REQUIRED_ROSTER_COLUMNS = {
    "Assignment ID",
    "User Id",
    "Optimised User Id",
    "Start Date",
    "End Date",
    "Shift Start Time",
    "Shift End Time",
    "Activity ID",
    "Activity Name",
    "Activity Head",
    "Assignment Type",
    "Swing",
}

REQUIRED_DEMAND_COLUMNS = {
    "Demand ID",
    "Shift",
    "Demand",
    "Is Active",
    "Activity ID",
    "Activity Name",
    "Activity Head",
}

REQUIRED_CREW_COLUMNS = {
    "User Id",
    "Classification",
}

REQUIRED_PRIORITY_COLUMNS = {
    "Priority",
    "Activity Head",
}


@dataclass
class DashboardDataset:
    """Container for validated inputs and solver outputs for a single run."""

    name: str
    data_dir: Path
    cpsat_dir: Path
    options_dir: Path | None = None
    roster_rows: list[dict[str, str]] = field(default_factory=list)
    demand_rows: list[dict[str, str]] = field(default_factory=list)
    crew_by_id: dict[str, dict[str, str]] = field(default_factory=dict)
    priority_by_head: dict[str, int] = field(default_factory=dict)
    limits_by_head: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)
    constraints: dict[str, tuple[str, str]] = field(default_factory=dict)
    config_flags: dict[str, object] = field(default_factory=dict)
    reassignments: list[dict[str, str]] = field(default_factory=list)
    unfilled_gaps: list[dict[str, str]] = field(default_factory=list)
    seats: list[dict[str, str]] = field(default_factory=list)
    swings: list[dict[str, str]] = field(default_factory=list)
    gap_options: list[dict[str, str]] = field(default_factory=list)
    rejections: list[dict[str, str]] = field(default_factory=list)
    summary_markdown: str = ""
    validation_markdown: str = ""
    warnings: list[str] = field(default_factory=list)


def read_csv_safe(
    path: Path | None,
    required_columns: set[str] | None = None,
    dedupe_key: str | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Read a CSV file safely, validating required columns and deduplicating records if requested."""
    warnings: list[str] = []
    if path is None or not path.exists() or not path.is_file():
        if path is not None:
            warnings.append(f"Missing file: {path}")
        return [], warnings

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        warnings.append(f"Cannot read {path}: {exc}")
        return [], warnings

    if not text.strip():
        warnings.append(f"Empty file: {path}")
        return [], warnings

    reader = csv.DictReader(text.splitlines())
    fieldnames = set(reader.fieldnames or [])
    if required_columns:
        missing = sorted(required_columns - fieldnames)
        if missing:
            raise ValueError(
                f"File {path} is missing required column(s): {', '.join(missing)}"
            )

    rows: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    duplicates = 0
    for raw in reader:
        if raw is None:
            continue
        row = {
            str(k).strip(): (str(v).strip() if v is not None else "")
            for k, v in raw.items()
            if k is not None
        }
        if dedupe_key and dedupe_key in row:
            key_val = row[dedupe_key]
            if key_val:
                if key_val in seen_keys:
                    duplicates += 1
                    continue
                seen_keys.add(key_val)
        rows.append(row)

    if duplicates:
        warnings.append(
            f"Deduplicated {duplicates} duplicate record(s) by '{dedupe_key}' in {path.name}"
        )
    return rows, warnings


def _load_config_flags(config_path: Path | None) -> tuple[dict[str, object], list[str]]:
    warnings: list[str] = []
    flags: dict[str, object] = {
        "residential_start_restriction": True,
        "relief_only_day_night_transition": True,
        "priority_strategy": "none",
    }
    if config_path is None or not config_path.exists():
        return flags, warnings
    try:
        import yaml

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            cons = raw.get("constraints")
            if isinstance(cons, dict):
                for key in ("residential_start_restriction", "relief_only_day_night_transition"):
                    if key in cons and isinstance(cons[key], bool):
                        flags[key] = cons[key]
            opt = raw.get("optimization")
            if isinstance(opt, dict) and isinstance(opt.get("priority_strategy"), str):
                flags["priority_strategy"] = opt["priority_strategy"]
    except Exception as exc:  # pragma: no cover - defensive fallback
        warnings.append(f"Could not parse {config_path}: {exc}")
    return flags, warnings


def load_dashboard_dataset(
    data_dir: Path = DEFAULT_DATA_DIR,
    cpsat_dir: Path = DEFAULT_CPSAT_DIR,
    options_dir: Path | None = DEFAULT_OPTIONS_DIR,
    config_path: Path | None = DEFAULT_CONFIG_PATH,
    name: str = "Current Run",
) -> DashboardDataset:
    """Load and validate all input and output tables for the dashboard."""
    warnings: list[str] = []

    roster_rows, w = read_csv_safe(
        cpsat_dir / "roster_full.csv",
        required_columns=REQUIRED_ROSTER_COLUMNS,
        dedupe_key="Assignment ID",
    )
    warnings.extend(w)

    demand_rows, w = read_csv_safe(
        data_dir / "activity_demand_df.csv",
        required_columns=REQUIRED_DEMAND_COLUMNS,
        dedupe_key="Demand ID",
    )
    warnings.extend(w)

    crew_rows, w = read_csv_safe(
        data_dir / "crew_master_data_df.csv",
        required_columns=REQUIRED_CREW_COLUMNS,
        dedupe_key="User Id",
    )
    warnings.extend(w)
    crew_by_id = {r["User Id"]: r for r in crew_rows if r.get("User Id")}

    priority_rows, w = read_csv_safe(
        data_dir / "activity_priority.csv",
        required_columns=REQUIRED_PRIORITY_COLUMNS,
        dedupe_key="Activity Head",
    )
    warnings.extend(w)

    priority_by_head: dict[str, int] = {}
    limits_by_head: dict[str, tuple[int | None, int | None]] = {}
    for row in priority_rows:
        head = row.get("Activity Head", "")
        if not head:
            continue
        try:
            priority_by_head[head] = int(row["Priority"])
        except (KeyError, ValueError):
            pass
        res_lim = row.get("Max Resident Shifts", "")
        fifo_lim = row.get("Max FIFO Shifts", "")
        res_val = int(res_lim) if res_lim.isdecimal() else None
        fifo_val = int(fifo_lim) if fifo_lim.isdecimal() else None
        limits_by_head[head] = (res_val, fifo_val)

    constraint_rows, w = read_csv_safe(
        data_dir / "constraints_df.csv",
        required_columns={"Constraint", "Value", "Status"},
        dedupe_key="Constraint",
    )
    warnings.extend(w)
    constraints = {
        r["Constraint"]: (r["Value"], r["Status"])
        for r in constraint_rows
        if r.get("Constraint")
    }

    config_flags, w = _load_config_flags(config_path)
    warnings.extend(w)

    reassignments, w = read_csv_safe(cpsat_dir / "reassignments.csv")
    warnings.extend(w)
    unfilled_gaps, w = read_csv_safe(cpsat_dir / "unfilled_gaps.csv", dedupe_key="Assignment ID")
    warnings.extend(w)

    seats: list[dict[str, str]] = []
    swings: list[dict[str, str]] = []
    gap_options: list[dict[str, str]] = []
    rejections: list[dict[str, str]] = []
    if options_dir is not None and options_dir.exists():
        seats, _ = read_csv_safe(options_dir / "seats.csv", dedupe_key="Seat Key")
        swings, _ = read_csv_safe(options_dir / "swings.csv", dedupe_key="Swing Key")
        gap_options, _ = read_csv_safe(options_dir / "gap_options.csv")
        rejections, _ = read_csv_safe(options_dir / "rejections.csv")

    summary_md = ""
    summary_path = cpsat_dir / "summary.md"
    if summary_path.exists():
        summary_md = summary_path.read_text(encoding="utf-8")

    validation_md = ""
    validation_path = cpsat_dir / "validation.md"
    if validation_path.exists():
        validation_md = validation_path.read_text(encoding="utf-8")

    # Backfill Crew Classification on roster rows if missing
    for r in roster_rows:
        uid = r.get("Optimised User Id", "") or r.get("New User Id", "")
        if not r.get("Crew Classification") and uid and uid in crew_by_id:
            r["Crew Classification"] = crew_by_id[uid].get("Classification", "")

    return DashboardDataset(
        name=name,
        data_dir=data_dir,
        cpsat_dir=cpsat_dir,
        options_dir=options_dir,
        roster_rows=roster_rows,
        demand_rows=demand_rows,
        crew_by_id=crew_by_id,
        priority_by_head=priority_by_head,
        limits_by_head=limits_by_head,
        constraints=constraints,
        config_flags=config_flags,
        reassignments=reassignments,
        unfilled_gaps=unfilled_gaps,
        seats=seats,
        swings=swings,
        gap_options=gap_options,
        rejections=rejections,
        summary_markdown=summary_md,
        validation_markdown=validation_md,
        warnings=warnings,
    )


def discover_strategy_datasets(base_root: Path = ROOT) -> dict[str, DashboardDataset]:
    """Discover available strategy outputs (None, Weighted, Lexicographic) for comparison."""
    discovered: dict[str, DashboardDataset] = {}

    # 1. Check standard strategy output folders under CP-SAT/outputs/
    outputs_root = base_root / "CP-SAT" / "outputs"
    standard_candidates = [
        ("None", DEFAULT_DATA_DIR, outputs_root / "roster_full_none", DEFAULT_OPTIONS_DIR, DEFAULT_CONFIG_PATH),
        ("Weighted", DEFAULT_DATA_DIR, outputs_root / "roster_full_weighted", DEFAULT_OPTIONS_DIR, DEFAULT_CONFIG_PATH),
        ("Lexicographic", DEFAULT_DATA_DIR, outputs_root / "roster_full_lexicographic", DEFAULT_OPTIONS_DIR, DEFAULT_CONFIG_PATH),
    ]
    for label, d_dir, c_dir, o_dir, cfg in standard_candidates:
        if (c_dir / "roster_full.csv").exists():
            discovered[label] = load_dashboard_dataset(d_dir, c_dir, o_dir, cfg, name=label)

    # 2. Also check edge_case_demo strategy runs if present
    demo_root = outputs_root / "edge_case_demo"
    demo_candidates = [
        ("None (Demo)", "run_1_strategy_none"),
        ("Weighted (Demo)", "run_2_strategy_weighted"),
        ("Lexicographic (Demo)", "run_3_strategy_lexicographic"),
    ]
    for label, folder in demo_candidates:
        run_dir = demo_root / folder
        c_dir = run_dir / "cpsat"
        d_dir = demo_root / "data"
        o_dir = run_dir / "options"
        cfg = run_dir / "config.yml"
        if (c_dir / "roster_full.csv").exists() and d_dir.exists():
            discovered[label] = load_dashboard_dataset(d_dir, c_dir, o_dir, cfg, name=label)

    return discovered
