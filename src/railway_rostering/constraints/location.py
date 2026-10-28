"""Location continuity and optional positioning.

Source (briefing §3): "Location is an explicit constraint ... after a crew
member performs a duty from A to B, they finish at B. Their next duty must
start at their current location unless a permitted positioning/travel movement
connects them to another location. ... do not assume independent travel is
allowed without confirmation."

Implemented rule (hard constraint)
----------------------------------
* Default (``positioning_enabled = False``): the next duty must start exactly
  where the previous duty ended (or at ``initial_location`` for the first
  duty). No teleporting, no travel.
* Optional (``positioning_enabled = True``): a single direct positioning leg
  listed in ``travel.csv`` may connect the two locations. Its travel time is
  added to the required rest unless ``positioning_counts_as_rest`` is True.
  Multi-hop journeys are only possible if ``travel.csv`` lists them as one
  link. All travel times in this repository are synthetic.

When a base-return rule applies between two duties the connection must pass
through the base: ``end(i) -> base -> start(j)`` (see base_return.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import ModelConfig
from ..domain import Instance


@dataclass(frozen=True)
class Leg:
    from_location: str
    to_location: str
    travel_minutes: int
    cost: float


@dataclass(frozen=True)
class Connection:
    """How a crew member gets from one location to the next duty's start."""

    legs: tuple[Leg, ...] = ()

    @property
    def travel_minutes(self) -> int:
        return sum(leg.travel_minutes for leg in self.legs)

    @property
    def cost(self) -> float:
        return sum(leg.cost for leg in self.legs)


def direct_connection(
    from_location: str, to_location: Optional[str], instance: Instance, cfg: ModelConfig
) -> Optional[Connection]:
    """Connection without an intermediate stop. ``to_location=None`` means 'anywhere'."""

    if to_location is None or from_location == to_location:
        return Connection()
    if not cfg.positioning_enabled:
        return None
    link = instance.travel.get((from_location, to_location))
    if link is None:
        return None
    return Connection((Leg(from_location, to_location, link.travel_minutes, link.cost),))


def connection_via(
    from_location: str,
    via: str,
    to_location: Optional[str],
    instance: Instance,
    cfg: ModelConfig,
) -> Optional[Connection]:
    """Connection that must visit ``via`` (the base) on the way."""

    first = direct_connection(from_location, via, instance, cfg)
    if first is None:
        return None
    second = direct_connection(via, to_location, instance, cfg)
    if second is None:
        return None
    return Connection(first.legs + second.legs)
