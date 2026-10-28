"""Model and solver configuration.

Every operational rule that is uncertain in the OptiFlux briefing is controlled
from here, so that an approximation can be switched off or changed without
editing model code. Defaults are documented in
``docs/assumptions_and_open_questions.md``; each field's comment says whether
the default comes from the briefing ("specified") or is a prototype
assumption ("assumption").

Configurations can be loaded from / saved to JSON with
:func:`load_model_config` and :meth:`ModelConfig.to_dict`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

TIME_CHANGE_POLICIES = ("disabled", "window_only", "persist_after_change")
DEMAND_MODES = ("partial", "all_or_nothing")
EXISTING_ASSIGNMENT_MODES = ("fixed", "reassignable")
OBJECTIVE_LEVELS = ("coverage", "priority", "positioning", "time_changes", "roster_changes")
OBJECTIVE_MODES = ("lexicographic", "weighted")
CO_RULE_MODES = ("disabled",)


@dataclass
class ModelConfig:
    """Rules and objective settings for one optimisation run."""

    # --- Duty timing -------------------------------------------------------
    # Used only when a duty row has neither ``end`` nor ``duration_hours``.
    default_duty_hours: float = 12.0  # specified ("12-hour duties")

    # --- Rest ----------------------------------------------------------------
    ordinary_rest_hours: float = 11.0  # specified
    transition_rest_enabled: bool = True
    transition_rest_hours: float = 23.0  # specified ("during a shift transition")
    # A duty is a DAY shift if its start time-of-day is in [day_start_from,
    # day_start_until); otherwise NIGHT. Assumption: the briefing only gives
    # 05:00 (day) and 17:00 (night) as examples. A ``shift_type`` column in
    # duties.csv overrides this.
    day_shift_start_from: str = "03:00"
    day_shift_start_until: str = "15:00"

    # --- Work pattern ----------------------------------------------------------
    # Assumption carried over from V1: at most this many duties may *start* on
    # one calendar date per crew member. ``None`` disables the rule.
    max_duties_per_day: Optional[int] = 1
    # Duties may only start on working days of the crew member's swing.
    enforce_swing_work_days: bool = True  # assumption (off-day work unclear)
    # Default work/off pattern per crew type when crew.csv leaves it blank.
    default_work_off_days: dict[str, list[int]] = field(
        default_factory=lambda: {"RELIEF": [14, 14], "EXCESS": [6, 6]}  # specified ("usually")
    )

    # --- Shift-time changes ----------------------------------------------------
    # "disabled": no rule; "window_only": each duty's start must be an allowed
    # offset from the rostered time; "persist_after_change": additionally, once
    # a duty is worked at a non-rostered time, all later duties in the same
    # swing must be at that same time (briefing text). See
    # constraints/swing_rules.py for the exact semantics.
    time_change_policy: dict[str, str] = field(
        default_factory=lambda: {"RELIEF": "persist_after_change", "EXCESS": "persist_after_change"}
    )
    # Allowed start-time offsets in minutes from the rostered time. ``None``
    # means any time of day (Relief: "can cover gaps throughout the day").
    # Excess: lift-up (-60) and layback (+60) only (specified).
    allowed_offsets_minutes: dict[str, Optional[list[int]]] = field(
        default_factory=lambda: {"RELIEF": None, "EXCESS": [-60, 0, 60]}
    )

    # --- Base return -----------------------------------------------------------
    # "On the last day of a swing or a transition day, the person has to return
    # to their base location" (specified). Approximations: see base_return.py.
    base_return_at_swing_end: bool = True
    base_return_on_transition: bool = True
    # If True, also require being at base after the last duty when the swing
    # continues beyond the horizon (assumption, off by default).
    base_return_at_horizon_end: bool = False

    # --- Positioning -----------------------------------------------------------
    # The briefing does not say positioning is allowed; off by default.
    positioning_enabled: bool = False
    # If False, travel time is added on top of the required rest.
    positioning_counts_as_rest: bool = False

    # --- CO rules ----------------------------------------------------------------
    co_rules_mode: str = "disabled"  # semantics of CO not defined in the briefing

    # --- Demand and existing roster ----------------------------------------------
    # "partial": a demand-2 duty with one crew counts as 1 covered unit.
    # "all_or_nothing": a duty counts only when fully staffed.
    demand_mode: str = "partial"
    # "fixed": existing assignments are hard-fixed. "reassignable": existing
    # units must stay covered, but by anyone eligible; changes are minimised.
    existing_assignment_mode: str = "fixed"

    # --- Objective ---------------------------------------------------------------
    objective_levels: list[str] = field(
        default_factory=lambda: ["coverage", "priority", "positioning", "time_changes", "roster_changes"]
    )
    objective_mode: str = "lexicographic"
    # Weight per covered unit for the "priority" level, keyed by priority value
    # as a string. Priority 1 = highest (only Howrah Mainline is specified as
    # Priority 1). Missing priority -> default_priority_weight.
    priority_weights: dict[str, int] = field(default_factory=lambda: {"1": 3, "2": 2, "3": 1})
    default_priority_weight: int = 1

    # --- Model strengthening -----------------------------------------------------
    add_redundant_cliques: bool = True
    # Redundant linear flow-conservation rows on the circuit arcs (tighter LP).
    add_flow_linearization: bool = True

    # ------------------------------------------------------------------------
    def validate(self) -> None:
        """Raise ``ValueError`` for an internally inconsistent configuration."""

        for crew_type, policy in self.time_change_policy.items():
            if policy not in TIME_CHANGE_POLICIES:
                raise ValueError(f"time_change_policy[{crew_type}]={policy!r} not in {TIME_CHANGE_POLICIES}")
        if self.demand_mode not in DEMAND_MODES:
            raise ValueError(f"demand_mode must be one of {DEMAND_MODES}")
        if self.existing_assignment_mode not in EXISTING_ASSIGNMENT_MODES:
            raise ValueError(f"existing_assignment_mode must be one of {EXISTING_ASSIGNMENT_MODES}")
        if self.objective_mode not in OBJECTIVE_MODES:
            raise ValueError(f"objective_mode must be one of {OBJECTIVE_MODES}")
        if self.co_rules_mode not in CO_RULE_MODES:
            raise ValueError(f"co_rules_mode must be one of {CO_RULE_MODES}")
        unknown = [lvl for lvl in self.objective_levels if lvl not in OBJECTIVE_LEVELS]
        if unknown:
            raise ValueError(f"unknown objective levels {unknown}; allowed {OBJECTIVE_LEVELS}")
        if self.ordinary_rest_hours < 0 or self.transition_rest_hours < 0:
            raise ValueError("rest hours must be non-negative")
        if self.max_duties_per_day is not None and self.max_duties_per_day < 1:
            raise ValueError("max_duties_per_day must be >= 1 or None")
        for crew_type, pattern in self.default_work_off_days.items():
            if len(pattern) != 2 or pattern[0] < 1 or pattern[1] < 0:
                raise ValueError(f"default_work_off_days[{crew_type}] must be [work>=1, off>=0]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SolverConfig:
    """CP-SAT parameters."""

    # Time limit per lexicographic stage (seconds).
    time_limit_seconds: float = 30.0
    num_workers: int = 8
    random_seed: int = 0
    log_search_progress: bool = False
    use_greedy_hint: bool = True
    # Add the LP-relaxation bound of each lexicographic stage as a valid cut
    # (see lp_bound.py). Helps CP-SAT prove optimality; never changes the optimum.
    use_lp_bound: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _from_dict(cls, data: dict[str, Any]):
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} keys: {sorted(unknown)}")
    return cls(**data)


def model_config_from_dict(data: dict[str, Any]) -> ModelConfig:
    cfg = _from_dict(ModelConfig, data)
    cfg.validate()
    return cfg


def solver_config_from_dict(data: dict[str, Any]) -> SolverConfig:
    return _from_dict(SolverConfig, data)


def load_configs(path: str | Path) -> tuple[ModelConfig, SolverConfig]:
    """Load a JSON file of the form ``{"model": {...}, "solver": {...}}``.

    Either section may be omitted; omitted keys keep their defaults.
    """

    raw = json.loads(Path(path).read_text())
    model = model_config_from_dict(raw.get("model", {}))
    solver = solver_config_from_dict(raw.get("solver", {}))
    return model, solver
