"""Interface for CO and CO-location rules - currently disabled.

Source (briefing §8): the briefing lists separate "CO constraint" and "CO
Location constraint" categories and the activities "Howrah Mainline CO" and
"Yajpur Mainline CO", with an example "Howrah Mainline CO (HWH -> HWH)". It
does **not** define what CO means, when it is required, which sequences need
it, valid locations, duration, or whether it is a duty or a status.

What *is* implemented (grounded in the source)
----------------------------------------------
* CO activities are ordinary duties with their own activity name, times and
  locations, so they are covered, sequenced and rest-checked like any duty.
* Eligibility for "X CO" is separate from eligibility for "X" (exact activity
  match in eligibility.py).
* ``duties.csv`` accepts an optional ``co_location`` column; it is parsed,
  carried through to the outputs, and checked by input validation, but it does
  not constrain the solution.

What is *not* implemented
-------------------------
Any rule that links CO duties to other duties or restricts CO locations.
This module gives such a rule a single home: ``candidate_allowed`` and
``arc_allowed`` are called by candidate generation for every crew-duty pair and
every consecutive arc. With ``co_rules_mode = "disabled"`` (the only mode)
they allow everything. A future rule is added by implementing a new mode here,
plus the matching check in solution_validation.py, plus tests.
"""

from __future__ import annotations

from typing import Optional

from ..config import ModelConfig
from ..domain import Crew, Duty

STATUS = {
    "co_requirement": "disabled - semantics of CO not defined in the briefing",
    "co_location": "disabled - column parsed and reported only",
}


def candidate_allowed(crew: Crew, duty: Duty, cfg: ModelConfig) -> Optional[str]:
    """Return a reason string to forbid ``crew`` on ``duty``; ``None`` allows it."""

    if cfg.co_rules_mode == "disabled":
        return None
    raise NotImplementedError(cfg.co_rules_mode)


def arc_allowed(crew: Crew, prev: Optional[Duty], nxt: Optional[Duty], cfg: ModelConfig) -> Optional[str]:
    """Return a reason string to forbid ``prev -> nxt`` for ``crew``; ``None`` allows it."""

    if cfg.co_rules_mode == "disabled":
        return None
    raise NotImplementedError(cfg.co_rules_mode)
