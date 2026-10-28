"""OptiFlux railway crew recovery and rostering prototype.

Typical use::

    from railway_rostering import load_instance, solve_instance, write_outputs
    inst = load_instance("data/sample/briefing_abc")
    result = solve_instance(inst)
    write_outputs(result, "outputs/briefing_abc")

See docs/codebase_guide.md for the architecture.
"""

__version__ = "0.2.0"

from .config import ModelConfig, SolverConfig, load_configs  # noqa: E402
from .data_loader import DataError, load_instance, write_instance  # noqa: E402
from .domain import Assignment, Crew, CrewType, Duty, Instance, ShiftType, TravelLink  # noqa: E402
from .reporting import write_outputs  # noqa: E402
from .solution_validation import validate_solution  # noqa: E402
from .solve import RunResult, solve_instance  # noqa: E402

__all__ = [
    "Assignment",
    "Crew",
    "CrewType",
    "DataError",
    "Duty",
    "Instance",
    "ModelConfig",
    "RunResult",
    "ShiftType",
    "SolverConfig",
    "TravelLink",
    "load_configs",
    "load_instance",
    "solve_instance",
    "validate_solution",
    "write_instance",
    "write_outputs",
]
