"""Domain objects for the OptiFlux crew recovery problem.

Everything the optimiser reasons about is represented here as plain, immutable
dataclasses:

* :class:`Crew` – one Relief or Excess crew member (initial state, base, swing
  calendar, rostered start time, boundary commitments).
* :class:`Duty` – one duty that needs crew (uncovered) or is already staffed
  (existing assignment).
* :class:`TravelLink` – an optional positioning movement between two locations.
* :class:`Instance` – the full problem input.
* :class:`Assignment` / :class:`Solution` – the optimiser's output.

No optimisation logic lives in this module; it only describes data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Mapping, Optional

DATETIME_FORMAT = "%Y-%m-%d %H:%M"
DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"


class CrewType(str, Enum):
    """Crew category from the briefing.

    ``UNSPECIFIED`` exists only so that Version-1 legacy files (which have no
    crew type) can still be loaded; no type-specific rule is applied to it.
    """

    RELIEF = "RELIEF"
    EXCESS = "EXCESS"
    UNSPECIFIED = "UNSPECIFIED"


class ShiftType(str, Enum):
    """Day or night shift. Used to detect day/night transitions (23 h rest)."""

    DAY = "DAY"
    NIGHT = "NIGHT"


@dataclass(frozen=True)
class Crew:
    """A crew member available for recovery work.

    Attributes
    ----------
    crew_id:
        Unique identifier (synthetic in this repository).
    crew_type:
        Relief or Excess. Determines default swing pattern and permitted time
        changes.
    base_location:
        Home location used by return-to-base rules. ``None`` disables base
        rules for this crew member (with a validation warning).
    initial_location:
        Where the crew member is at the start of the horizon (or at the end of
        ``prior_duty_end`` if a prior duty is given).
    rostered_start:
        Time of day of the crew member's rostered shift (e.g. 17:00). Lift-up /
        layback offsets are measured from this time.
    current_start:
        Time in effect at the horizon start if a time change was already made
        earlier in the current swing. ``None`` means "no change yet".
    swing_start:
        Any first working day of a swing; the work/off cycle repeats from it.
        ``None`` means the swing calendar is unknown and is not enforced.
    work_days, off_days:
        Swing pattern; ``None`` falls back to the crew-type default in
        :class:`~railway_rostering.config.ModelConfig`.
    prior_duty_end, prior_shift_type:
        End of the last duty worked before (or overlapping) the horizon start.
        Used for rest at the horizon boundary.
    next_commitment_start, next_commitment_location, next_commitment_shift_type:
        A known commitment after the last recovery duty (e.g. the first rostered
        duty after the horizon). Used for rest and location continuity at the
        end boundary.
    unavailable_dates:
        Dates on which no duty may *start* (leave, training, ...).
    """

    crew_id: str
    crew_type: CrewType
    initial_location: str
    base_location: Optional[str] = None
    rostered_start: Optional[time] = None
    current_start: Optional[time] = None
    swing_start: Optional[date] = None
    work_days: Optional[int] = None
    off_days: Optional[int] = None
    prior_duty_end: Optional[datetime] = None
    prior_shift_type: Optional[ShiftType] = None
    next_commitment_start: Optional[datetime] = None
    next_commitment_location: Optional[str] = None
    next_commitment_shift_type: Optional[ShiftType] = None
    unavailable_dates: frozenset[date] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Duty:
    """A duty requiring ``demand`` crew members.

    ``assigned_crew`` lists crew already rostered on the duty (existing
    assignments). The remaining ``demand - len(assigned_crew)`` units are the
    *open* (uncovered) demand that the optimiser tries to fill.

    ``eligible_crew`` is an optional per-duty list. When an eligibility table
    is also supplied, a crew member must satisfy both (see
    :mod:`railway_rostering.constraints.eligibility`).
    """

    duty_id: str
    activity: str
    start: datetime
    end: datetime
    start_location: str
    end_location: str
    demand: int = 1
    priority: Optional[int] = None
    shift_type: Optional[ShiftType] = None
    eligible_crew: Optional[frozenset[str]] = None
    assigned_crew: tuple[str, ...] = ()
    co_location: Optional[str] = None

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def start_date(self) -> date:
        return self.start.date()

    @property
    def open_demand(self) -> int:
        return max(self.demand - len(self.assigned_crew), 0)


@dataclass(frozen=True)
class TravelLink:
    """A permitted positioning movement (deadhead / passenger travel).

    Only used when positioning is enabled in the model configuration. Travel
    times in this repository are *synthetic* and must not be read as real
    railway journey times.
    """

    from_location: str
    to_location: str
    travel_minutes: int
    cost: float = 1.0


@dataclass
class Instance:
    """A complete problem instance."""

    name: str
    crews: dict[str, Crew]
    duties: list[Duty]
    horizon_start: datetime
    horizon_end: datetime
    # crew_id -> set of activities the crew member is qualified for.
    # ``None`` means no eligibility table was supplied.
    qualifications: Optional[dict[str, frozenset[str]]] = None
    travel: dict[tuple[str, str], TravelLink] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.duties = sorted(self.duties, key=lambda d: (d.start, d.duty_id))
        self._duty_index = {d.duty_id: d for d in self.duties}

    def duty(self, duty_id: str) -> Duty:
        return self._duty_index[duty_id]

    @property
    def duty_ids(self) -> list[str]:
        return [d.duty_id for d in self.duties]

    @property
    def locations(self) -> set[str]:
        locs: set[str] = set()
        for d in self.duties:
            locs.update((d.start_location, d.end_location))
        for c in self.crews.values():
            locs.add(c.initial_location)
            if c.base_location:
                locs.add(c.base_location)
        return locs

    @property
    def total_open_demand(self) -> int:
        return sum(d.open_demand for d in self.duties)


@dataclass(frozen=True)
class Assignment:
    """Crew member ``crew_id`` performs duty ``duty_id``.

    ``existing`` marks assignments that were part of the input roster.
    """

    crew_id: str
    duty_id: str
    existing: bool = False


@dataclass
class Solution:
    """Optimiser output plus solver metadata (filled by :mod:`solve`)."""

    assignments: list[Assignment]
    status: str
    objective_values: dict[str, float] = field(default_factory=dict)
    best_bounds: dict[str, float] = field(default_factory=dict)
    stage_statuses: dict[str, str] = field(default_factory=dict)
    # crew_id -> ordered duty ids as read from the circuit arcs
    routes: dict[str, list[str]] = field(default_factory=dict)
    # (crew_id, from_node, to_node) -> list of positioning legs used on that arc
    positioning: list[dict] = field(default_factory=list)
    wall_time_seconds: float = 0.0
    stats: dict = field(default_factory=dict)

    def assignments_by_crew(self) -> Mapping[str, list[str]]:
        out: dict[str, list[str]] = {}
        for a in self.assignments:
            out.setdefault(a.crew_id, []).append(a.duty_id)
        return out


# --------------------------------------------------------------------------
# Small time helpers shared by loaders and the model (NOT by the validator,
# which re-implements its own arithmetic on purpose).
# --------------------------------------------------------------------------


def minutes_of_day(t: time) -> int:
    return t.hour * 60 + t.minute


def circular_offset_minutes(actual: time, reference: time) -> int:
    """Signed difference ``actual - reference`` on a 24 h clock, in [-720, 720).

    Example: reference 23:30, actual 00:30 -> +60 (a one-hour layback).
    """

    diff = minutes_of_day(actual) - minutes_of_day(reference)
    return (diff + 720) % 1440 - 720
