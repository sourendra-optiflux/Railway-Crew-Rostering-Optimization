"""Rule settings from constraints_df.csv, and the checks between two consecutive shifts of one person."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

SWING_BREAK = timedelta(hours=48)  # a longer gap starts a new swing (same as scripts/check_roster.py)
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config.yml"


@dataclass(frozen=True)
class Rules:
    horizon_start: date
    horizon_days: int
    solver_start: date  # gap_filling_rules.md G1: nothing before this date changes
    shift_hours: int
    rest: timedelta
    transition_rest: timedelta
    day_from: int  # minutes after midnight
    day_to: int
    off_days: dict[str, int]  # Classification -> days off between swings
    excess_offsets: frozenset[int]  # allowed start changes for Excess, in minutes
    demand_offsets: frozenset[int]  # allowed start changes for Demand crew moving seat (F1: lift-up / layback)
    max_changes: int  # F3: start-time changes allowed per day/night block
    max_change_minutes: int  # F3: size of one change
    residential_start_restriction: bool = True
    relief_only_day_night_transition: bool = True
    activity_head_max_shifts: bool = True
    priority_strategy: str = "none"

    @classmethod
    def from_table(cls, rows: list[dict[str, str]], config_path: Path = DEFAULT_CONFIG) -> "Rules":
        status_by_name = {r["Constraint"]: r["Status"] for r in rows}
        max_shifts_status = status_by_name.get("Activity Head Max Shifts", "Active")
        if max_shifts_status not in ("Active", "Inactive"):
            raise SystemExit(
                f"error: Activity Head Max Shifts Status in constraints_df.csv must be Active or Inactive, "
                f"got {max_shifts_status!r}"
            )
        activity_head_max_shifts = max_shifts_status == "Active"
        value = {r["Constraint"]: r["Value"] for r in rows if r["Status"] == "Active"}
        day_from, day_to = (int(t[:2]) * 60 + int(t[3:]) for t in value["Day Shift Window"].split("-"))
        if value["Relief Allowed Start Offsets"] != "ANY":
            raise SystemExit("error: only 'ANY' is supported for Relief Allowed Start Offsets")

        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise SystemExit("error: loading config.yml requires PyYAML; install the project dependencies") from exc

        try:
            with config_path.open(encoding="utf-8") as stream:
                config = yaml.safe_load(stream)
        except OSError as exc:
            raise SystemExit(f"error: cannot read constraint config {config_path}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise SystemExit(f"error: invalid YAML in constraint config {config_path}: {exc}") from exc

        constraints = config.get("constraints") if isinstance(config, dict) else None
        if not isinstance(constraints, dict):
            raise SystemExit(f"error: {config_path} must contain a 'constraints' mapping")
        optimization = config.get("optimization", {}) if isinstance(config, dict) else {}
        if not isinstance(optimization, dict):
            raise SystemExit(f"error: optimization in {config_path} must be a mapping")
        unknown_optimization = set(optimization) - {"priority_strategy"}
        if unknown_optimization:
            raise SystemExit(
                f"error: unknown optimization settings in {config_path}: {', '.join(sorted(unknown_optimization))}"
            )
        priority_strategy = optimization.get("priority_strategy", "none")
        if not isinstance(priority_strategy, str) or priority_strategy not in ("none", "weighted", "lexicographic"):
            raise SystemExit(
                f"error: optimization.priority_strategy in {config_path} must be none, weighted, or lexicographic"
            )
        allowed = {"residential_start_restriction", "relief_only_day_night_transition"}
        unknown = set(constraints) - allowed
        if unknown:
            raise SystemExit(f"error: unknown constraint switches in {config_path}: {', '.join(sorted(unknown))}")
        defaults = {
            "residential_start_restriction": True,
            "relief_only_day_night_transition": True,
        }
        for name, enabled in constraints.items():
            if type(enabled) is not bool:
                raise SystemExit(f"error: constraints.{name} in {config_path} must be true or false")
            defaults[name] = enabled

        def offsets(name: str) -> frozenset[int]:
            return frozenset(int(x) for x in value[name].split(";"))

        return cls(
            horizon_start=date.fromisoformat(value["Planning Horizon Start"]),
            horizon_days=int(value["Planning Horizon Days"]),
            solver_start=date.fromisoformat(value["Solver Start Date"]),
            shift_hours=int(value["Shift Length Hours"]),
            rest=timedelta(hours=float(value["Ordinary Rest Hours"])),
            transition_rest=timedelta(hours=float(value["Transition Rest Hours"])),
            day_from=day_from,
            day_to=day_to,
            off_days={c: int(value[f"{c} Work/Off Days"].split("/")[1]) for c in ("FIFO", "Residential")},
            excess_offsets=offsets("Excess Allowed Start Offsets"),
            demand_offsets=offsets("Demand Allowed Start Offsets"),
            max_changes=int(value["Max Start Changes Per Block"]),
            max_change_minutes=int(value["Max Start Change Minutes"]),
            **defaults,
            activity_head_max_shifts=activity_head_max_shifts,
            priority_strategy=priority_strategy,
        )

    @property
    def horizon_end(self) -> date:
        """First day after the horizon."""
        return self.horizon_start + timedelta(days=self.horizon_days)

    def is_day(self, start: datetime) -> bool:
        return self.day_from <= start.hour * 60 + start.minute < self.day_to

    def residential_start_allowed(self, start: datetime) -> bool:
        """Residential crew cannot start a shift from 22:00 up to (but not including) 02:00."""
        if not self.residential_start_restriction:
            return True
        minute = start.hour * 60 + start.minute
        return not (minute >= 22 * 60 or minute < 2 * 60)

    def in_horizon(self, day: date) -> bool:
        return self.horizon_start <= day < self.horizon_end

    def solvable(self, day: date) -> bool:
        """May a row on this day change? From the solver start to the end of the horizon."""
        return self.solver_start <= day < self.horizon_end

    def block_minute(self, start: datetime) -> int:
        """Minutes since the start of its own window (day or night), so a night block never wraps midnight."""
        m = start.hour * 60 + start.minute
        return (m - (self.day_from if self.is_day(start) else self.day_to)) % 1440

    def can_follow(self, first, second) -> bool:
        """True if `second` may be the next shift after `first` in the same swing.

        Rest, day/night transition rest, one shift a day, location continuity, and (F3) no jump of more than
        the allowed change between two worked shifts of the same block. Relief standby rows (`standby`) have
        no real start time, so the F3 jump check skips them.
        """
        gap = second.start - first.end
        if gap < self.rest or gap > SWING_BREAK:
            return False
        if first.start.date() == second.start.date() or first.end_loc != second.start_loc:
            return False
        same_block = self.is_day(first.start) == self.is_day(second.start)
        if not same_block:
            if self.relief_only_day_night_transition and first.source != "Relief":
                return False

            if gap < self.transition_rest:
                return False
        if same_block and not (first.standby or second.standby):
            step = abs(self.block_minute(first.start) - self.block_minute(second.start))
            if step > self.max_change_minutes:
                return False
        return True
