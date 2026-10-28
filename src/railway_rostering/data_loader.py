"""Read and write problem instances as CSV files.

An instance directory contains:

``crew.csv`` (required)
    One row per crew member. Columns are described in ``docs/dataset_design.md``.
``duties.csv`` (required)
    One row per duty (uncovered or already staffed).
``eligibility.csv`` (optional)
    Long table ``crew_id,activity`` of activity qualifications.
``travel.csv`` (optional)
    Positioning links ``from_location,to_location,travel_minutes,cost``.
``instance.json`` (optional)
    ``name``, ``horizon_start``, ``horizon_end`` and free-form metadata
    (e.g. the synthetic generator configuration and seed).

The Version-1 notebook format (``person_id,initial_location`` and
``id,start,start_location,end_location,activity,eligible``) is also accepted;
see :func:`load_instance`.

Parsing problems are collected and raised together as :class:`DataError` so a
user sees every bad row at once.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional

from .domain import (
    DATE_FORMAT,
    DATETIME_FORMAT,
    TIME_FORMAT,
    Crew,
    CrewType,
    Duty,
    Instance,
    ShiftType,
    TravelLink,
)

LEGACY_CREW_ALIASES = {"person_id": "crew_id"}
LEGACY_DUTY_ALIASES = {"id": "duty_id", "eligible": "eligible_crew"}

CREW_COLUMNS = [
    "crew_id",
    "crew_type",
    "base_location",
    "initial_location",
    "rostered_start_time",
    "current_start_time",
    "swing_start_date",
    "work_days",
    "off_days",
    "prior_duty_end",
    "prior_shift_type",
    "next_commitment_start",
    "next_commitment_location",
    "next_commitment_shift_type",
    "unavailable_dates",
]
DUTY_COLUMNS = [
    "duty_id",
    "activity",
    "start",
    "end",
    "duration_hours",
    "start_location",
    "end_location",
    "demand",
    "priority",
    "shift_type",
    "eligible_crew",
    "assigned_crew",
    "co_location",
]
REQUIRED_CREW_COLUMNS = {"crew_id", "initial_location"}
REQUIRED_DUTY_COLUMNS = {"duty_id", "activity", "start", "start_location", "end_location"}


class DataError(ValueError):
    """Raised when input files cannot be parsed. ``errors`` lists every problem."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        preview = "\n  - ".join(errors[:20])
        more = f"\n  ... and {len(errors) - 20} more" if len(errors) > 20 else ""
        super().__init__(f"{len(errors)} input error(s):\n  - {preview}{more}")


# --------------------------------------------------------------------------
# Field parsers
# --------------------------------------------------------------------------


def _blank(value: Optional[str]) -> bool:
    return value is None or value.strip() == ""


def _parse_datetime(value: str) -> datetime:
    return datetime.strptime(value.strip(), DATETIME_FORMAT)


def _parse_date(value: str) -> date:
    return datetime.strptime(value.strip(), DATE_FORMAT).date()


def _parse_time(value: str) -> time:
    return datetime.strptime(value.strip(), TIME_FORMAT).time()


def _parse_list(value: Optional[str]) -> list[str]:
    if _blank(value):
        return []
    return [p.strip() for p in value.split(";") if p.strip()]


def _parse_shift(value: Optional[str]) -> Optional[ShiftType]:
    if _blank(value):
        return None
    return ShiftType(value.strip().upper())


class _Table:
    """Header-normalised CSV contents."""

    def __init__(self, columns: list[str], rows: list[dict[str, str]]):
        self.columns = set(columns)
        self.rows = rows


def _read_csv(path: Path, aliases: dict[str, str]) -> _Table:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            return _Table([], [])
        # Strip header whitespace *before* checking columns (V1 notebook bug P9).
        names = [aliases.get(h.strip(), h.strip()) for h in header]
        rows = []
        for values in reader:
            if not any(v.strip() for v in values):
                continue  # skip blank lines
            rows.append({name: (values[i].strip() if i < len(values) else "") for i, name in enumerate(names)})
        return _Table(names, rows)


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------


def parse_crew_rows(table: _Table, errors: list[str]) -> dict[str, Crew]:
    missing = REQUIRED_CREW_COLUMNS - table.columns
    if missing:
        errors.append(f"crew.csv: missing required columns {sorted(missing)}")
        return {}
    crews: dict[str, Crew] = {}
    for n, row in enumerate(table.rows, start=2):
        where = f"crew.csv line {n}"
        try:
            crew_id = row.get("crew_id") or ""
            if crew_id == "":
                raise ValueError("blank crew_id")
            if crew_id in crews:
                raise ValueError(f"duplicate crew_id {crew_id}")
            if _blank(row.get("initial_location")):
                raise ValueError("blank initial_location")
            crew_type = CrewType(row["crew_type"].upper()) if not _blank(row.get("crew_type")) else CrewType.UNSPECIFIED
            crews[crew_id] = Crew(
                crew_id=crew_id,
                crew_type=crew_type,
                initial_location=row["initial_location"],
                base_location=None if _blank(row.get("base_location")) else row["base_location"],
                rostered_start=None
                if _blank(row.get("rostered_start_time"))
                else _parse_time(row["rostered_start_time"]),
                current_start=None if _blank(row.get("current_start_time")) else _parse_time(row["current_start_time"]),
                swing_start=None if _blank(row.get("swing_start_date")) else _parse_date(row["swing_start_date"]),
                work_days=None if _blank(row.get("work_days")) else int(row["work_days"]),
                off_days=None if _blank(row.get("off_days")) else int(row["off_days"]),
                prior_duty_end=None if _blank(row.get("prior_duty_end")) else _parse_datetime(row["prior_duty_end"]),
                prior_shift_type=_parse_shift(row.get("prior_shift_type")),
                next_commitment_start=None
                if _blank(row.get("next_commitment_start"))
                else _parse_datetime(row["next_commitment_start"]),
                next_commitment_location=None
                if _blank(row.get("next_commitment_location"))
                else row["next_commitment_location"],
                next_commitment_shift_type=_parse_shift(row.get("next_commitment_shift_type")),
                unavailable_dates=frozenset(_parse_date(d) for d in _parse_list(row.get("unavailable_dates"))),
            )
        except (ValueError, KeyError) as exc:
            errors.append(f"{where}: {exc}")
    return crews


def parse_duty_rows(table: _Table, default_duty_hours: float, errors: list[str]) -> list[Duty]:
    missing = REQUIRED_DUTY_COLUMNS - table.columns
    if missing:
        errors.append(f"duties.csv: missing required columns {sorted(missing)}")
        return []
    duties: list[Duty] = []
    seen: set[str] = set()
    for n, row in enumerate(table.rows, start=2):
        where = f"duties.csv line {n}"
        try:
            duty_id = row.get("duty_id") or ""
            if duty_id == "":
                raise ValueError("blank duty_id")
            if duty_id in seen:
                raise ValueError(f"duplicate duty_id {duty_id}")
            seen.add(duty_id)
            for col in ("activity", "start_location", "end_location"):
                if _blank(row.get(col)):
                    raise ValueError(f"blank {col}")
            try:
                start = _parse_datetime(row["start"])
            except ValueError:
                raise ValueError(f"invalid start {row.get('start')!r}; use YYYY-MM-DD HH:MM") from None
            if not _blank(row.get("end")):
                end = _parse_datetime(row["end"])
            elif not _blank(row.get("duration_hours")):
                end = start + timedelta(hours=float(row["duration_hours"]))
            else:
                end = start + timedelta(hours=default_duty_hours)
            if end <= start:
                raise ValueError(f"end {end} is not after start {start}")
            demand = 1 if _blank(row.get("demand")) else int(row["demand"])
            if demand < 1:
                raise ValueError("demand must be >= 1")
            assigned = tuple(_parse_list(row.get("assigned_crew")))
            if len(set(assigned)) != len(assigned):
                raise ValueError("assigned_crew contains duplicates")
            if len(assigned) > demand:
                raise ValueError(f"{len(assigned)} assigned crew exceed demand {demand}")
            # Blank / missing list = no per-duty restriction (eligibility is then
            # decided by eligibility.csv alone; see constraints/eligibility.py).
            eligible: Optional[frozenset[str]] = None
            if not _blank(row.get("eligible_crew")):
                eligible = frozenset(_parse_list(row["eligible_crew"]))
            duties.append(
                Duty(
                    duty_id=duty_id,
                    activity=row["activity"],
                    start=start,
                    end=end,
                    start_location=row["start_location"],
                    end_location=row["end_location"],
                    demand=demand,
                    priority=None if _blank(row.get("priority")) else int(row["priority"]),
                    shift_type=_parse_shift(row.get("shift_type")),
                    eligible_crew=eligible,
                    assigned_crew=assigned,
                    co_location=None if _blank(row.get("co_location")) else row["co_location"],
                )
            )
        except (ValueError, KeyError) as exc:
            errors.append(f"{where}: {exc}")
    return duties


def parse_eligibility_rows(table: _Table, errors: list[str]) -> dict[str, frozenset[str]]:
    missing = {"crew_id", "activity"} - table.columns
    if missing:
        errors.append(f"eligibility.csv: missing required columns {sorted(missing)}")
        return {}
    quals: dict[str, set[str]] = {}
    for n, row in enumerate(table.rows, start=2):
        if _blank(row.get("crew_id")) or _blank(row.get("activity")):
            errors.append(f"eligibility.csv line {n}: blank crew_id or activity")
            continue
        quals.setdefault(row["crew_id"], set()).add(row["activity"])
    return {k: frozenset(v) for k, v in quals.items()}


def parse_travel_rows(table: _Table, errors: list[str]) -> dict[tuple[str, str], TravelLink]:
    missing = {"from_location", "to_location", "travel_minutes"} - table.columns
    if missing:
        errors.append(f"travel.csv: missing required columns {sorted(missing)}")
        return {}
    links: dict[tuple[str, str], TravelLink] = {}
    for n, row in enumerate(table.rows, start=2):
        try:
            minutes = int(row["travel_minutes"])
            if minutes < 0:
                raise ValueError("travel_minutes must be >= 0")
            link = TravelLink(
                from_location=row["from_location"],
                to_location=row["to_location"],
                travel_minutes=minutes,
                cost=1.0 if _blank(row.get("cost")) else float(row["cost"]),
            )
            links[(link.from_location, link.to_location)] = link
        except (ValueError, KeyError) as exc:
            errors.append(f"travel.csv line {n}: {exc}")
    return links


def load_instance(
    directory: str | Path | None = None,
    *,
    crew_path: str | Path | None = None,
    duties_path: str | Path | None = None,
    eligibility_path: str | Path | None = None,
    travel_path: str | Path | None = None,
    metadata_path: str | Path | None = None,
    default_duty_hours: float = 12.0,
) -> Instance:
    """Load an instance from a directory or from explicit file paths.

    Explicit paths override files found in ``directory``.
    """

    base = Path(directory) if directory is not None else None

    def pick(explicit, name: str) -> Optional[Path]:
        if explicit is not None:
            return Path(explicit)
        if base is not None and (base / name).exists():
            return base / name
        return None

    crew_p = pick(crew_path, "crew.csv")
    duties_p = pick(duties_path, "duties.csv")
    elig_p = pick(eligibility_path, "eligibility.csv")
    travel_p = pick(travel_path, "travel.csv")
    meta_p = pick(metadata_path, "instance.json")

    errors: list[str] = []
    if crew_p is None or not crew_p.exists():
        errors.append(f"crew file not found: {crew_p or (base / 'crew.csv' if base else 'crew.csv')}")
    if duties_p is None or not duties_p.exists():
        errors.append(f"duties file not found: {duties_p or (base / 'duties.csv' if base else 'duties.csv')}")
    if errors:
        raise DataError(errors)

    metadata: dict = {}
    if meta_p is not None and meta_p.exists():
        metadata = json.loads(meta_p.read_text())

    crews = parse_crew_rows(_read_csv(crew_p, LEGACY_CREW_ALIASES), errors)
    duties = parse_duty_rows(_read_csv(duties_p, LEGACY_DUTY_ALIASES), default_duty_hours, errors)
    quals = parse_eligibility_rows(_read_csv(elig_p, {}), errors) if elig_p is not None else None
    travel = parse_travel_rows(_read_csv(travel_p, {}), errors) if travel_p is not None else {}
    if errors:
        raise DataError(errors)

    if "horizon_start" in metadata:
        h_start = _parse_datetime(metadata["horizon_start"])
    elif duties:
        h_start = datetime.combine(min(d.start for d in duties).date(), time(0, 0))
    else:
        raise DataError(["cannot infer horizon: no duties and no horizon_start in instance.json"])
    if "horizon_end" in metadata:
        h_end = _parse_datetime(metadata["horizon_end"])
    else:
        h_end = datetime.combine(max(d.start for d in duties).date() + timedelta(days=1), time(0, 0))

    name = metadata.get("name") or (base.name if base is not None else duties_p.stem)
    return Instance(
        name=name,
        crews=crews,
        duties=duties,
        horizon_start=h_start,
        horizon_end=h_end,
        qualifications=quals,
        travel=travel,
        metadata=metadata,
    )


# --------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------


def _fmt_dt(v: Optional[datetime]) -> str:
    return "" if v is None else v.strftime(DATETIME_FORMAT)


def _fmt_t(v: Optional[time]) -> str:
    return "" if v is None else v.strftime(TIME_FORMAT)


def _fmt_d(v: Optional[date]) -> str:
    return "" if v is None else v.strftime(DATE_FORMAT)


def _write_rows(path: Path, columns: list[str], rows: Iterable[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def crew_to_row(c: Crew) -> dict:
    return {
        "crew_id": c.crew_id,
        "crew_type": c.crew_type.value,
        "base_location": c.base_location or "",
        "initial_location": c.initial_location,
        "rostered_start_time": _fmt_t(c.rostered_start),
        "current_start_time": _fmt_t(c.current_start),
        "swing_start_date": _fmt_d(c.swing_start),
        "work_days": "" if c.work_days is None else c.work_days,
        "off_days": "" if c.off_days is None else c.off_days,
        "prior_duty_end": _fmt_dt(c.prior_duty_end),
        "prior_shift_type": c.prior_shift_type.value if c.prior_shift_type else "",
        "next_commitment_start": _fmt_dt(c.next_commitment_start),
        "next_commitment_location": c.next_commitment_location or "",
        "next_commitment_shift_type": c.next_commitment_shift_type.value if c.next_commitment_shift_type else "",
        "unavailable_dates": ";".join(_fmt_d(d) for d in sorted(c.unavailable_dates)),
    }


def duty_to_row(d: Duty) -> dict:
    return {
        "duty_id": d.duty_id,
        "activity": d.activity,
        "start": _fmt_dt(d.start),
        "end": _fmt_dt(d.end),
        "duration_hours": "",
        "start_location": d.start_location,
        "end_location": d.end_location,
        "demand": d.demand,
        "priority": "" if d.priority is None else d.priority,
        "shift_type": d.shift_type.value if d.shift_type else "",
        "eligible_crew": "" if d.eligible_crew is None else ";".join(sorted(d.eligible_crew)),
        "assigned_crew": ";".join(d.assigned_crew),
        "co_location": d.co_location or "",
    }


def write_instance(instance: Instance, directory: str | Path) -> Path:
    """Write ``instance`` to ``directory`` in the canonical CSV schema."""

    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    _write_rows(out / "crew.csv", CREW_COLUMNS, (crew_to_row(c) for c in instance.crews.values()))
    duty_cols = DUTY_COLUMNS
    if all(d.eligible_crew is None for d in instance.duties):
        duty_cols = [c for c in DUTY_COLUMNS if c != "eligible_crew"]
    rows = []
    for d in instance.duties:
        r = duty_to_row(d)
        rows.append({k: r[k] for k in duty_cols})
    _write_rows(out / "duties.csv", duty_cols, rows)
    if instance.qualifications is not None:
        _write_rows(
            out / "eligibility.csv",
            ["crew_id", "activity"],
            (
                {"crew_id": cid, "activity": act}
                for cid in instance.crews
                for act in sorted(instance.qualifications.get(cid, ()))
            ),
        )
    if instance.travel:
        _write_rows(
            out / "travel.csv",
            ["from_location", "to_location", "travel_minutes", "cost"],
            (
                {
                    "from_location": t.from_location,
                    "to_location": t.to_location,
                    "travel_minutes": t.travel_minutes,
                    "cost": t.cost,
                }
                for t in instance.travel.values()
            ),
        )
    meta = dict(instance.metadata)
    meta.update(
        name=instance.name,
        horizon_start=_fmt_dt(instance.horizon_start),
        horizon_end=_fmt_dt(instance.horizon_end),
    )
    (out / "instance.json").write_text(json.dumps(meta, indent=2, sort_keys=True, default=str) + "\n")
    return out
