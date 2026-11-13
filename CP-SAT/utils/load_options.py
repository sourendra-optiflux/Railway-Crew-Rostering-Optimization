"""Read what option_generation/ wrote: the seats, the swings in the model, and their options.

CP-SAT never builds options itself. Everything it may choose comes from these files (layer 1).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from option_generation.data import read_csv
from option_generation.options import Option


@dataclass
class SeatInfo:
    key: str
    activity_id: str
    start: datetime
    demand: int
    fixed: int  # occupants whose rows are not in the model
    priority: int
    level: int  # -1 = not a target seat
    gap_rows: list[str]

    @property
    def capacity(self) -> int:
        """Places the model may fill with in-model people (their keep options included)."""
        return max(0, self.demand - self.fixed)


@dataclass
class ModelSwing:
    key: str
    user: str
    home: str
    classification: str
    earliest_start: datetime | None
    latest_end: datetime | None
    row_ids: list[str]
    droppable: list[bool]
    options: list[list[Option]] = field(default_factory=list)


def _dt(text: str) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def load_options(folder: Path) -> tuple[dict[str, SeatInfo], list[ModelSwing]]:
    for name in ("seats.csv", "swings.csv", "options.csv"):
        if not (folder / name).exists():
            raise SystemExit(f"error: {folder / name} not found; run option_generation/generate_options.py first")
    seats = {
        s["Seat Key"]: SeatInfo(
            s["Seat Key"], s["Activity ID"], datetime.fromisoformat(f"{s['Date']}T{s['Start']}"), int(s["Demand"]),
            int(s["Fixed Occupants"]), int(s["Priority"] or 99), int(s["Chain Level"]) if s["Chain Level"] else -1,
            [g for g in s["Gap Assignment IDs"].split(";") if g],
        )  # fmt: skip
        for s in read_csv(folder / "seats.csv")
    }
    swings: dict[str, ModelSwing] = {}
    for s in read_csv(folder / "swings.csv"):
        if s["In Model"] != "True":
            continue
        rows = s["Rows"].split(";")
        drop = set(s["Droppable Rows"].split(";")) - {""}
        swings[s["Swing Key"]] = ModelSwing(
            s["Swing Key"], s["User Id"], s["Home Depot"], s["Classification"], _dt(s["Earliest Start"]),
            _dt(s["Latest End"]), rows, [r in drop for r in rows], [[] for _ in rows],
        )  # fmt: skip
    by_swing: dict[str, list[dict]] = defaultdict(list)
    for o in read_csv(folder / "options.csv"):
        by_swing[o["Swing Key"]].append(o)
    for key, rows in by_swing.items():
        sw = swings[key]
        for o in rows:
            sw.options[int(o["Row Index"])].append(
                Option(
                    int(o["Row Index"]), o["Kind"], datetime.fromisoformat(o["Start"]),
                    datetime.fromisoformat(o["End"]), o["Start Location"], o["End Location"], o["Activity ID"],
                    o["Demand ID"], o["Seat Key"], o["Excess Seat Key"], o["Standby"] == "True", o["Row Type"],
                    int(o["Offset Minutes"]), int(o["Cost"]), int(o["Chain Level"]) if o["Chain Level"] else -1,
                    o.get("Unchanged", "False") == "True",
                )  # fmt: skip
            )
    return seats, list(swings.values())
