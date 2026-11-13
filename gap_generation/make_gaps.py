#!/usr/bin/env python3
"""Put crew on leave and write roster_full.csv, the roster with its gaps (gap_filling_rules.md G1-G4).

Layer 0 of the pipeline (then option_generation/, then CP-SAT/). The input tables are only read.

Leave mix (shares of the crew, from constraints_df.csv; 15% in total, one leave per person):
    Full swing   5%   every shift of one swing (6 days Residential, 14 days FIFO)
    Day shifts   2%   the 3 day shifts of one 6-day Residential swing
    Night shifts 3%   the 3 night shifts of one 6-day Residential swing
    Random       5%   a run of 1 or more consecutive shifts inside one swing

A row on leave keeps its original `User Id`, but `New User Id` is blank. If it is a Demand row it is a
gap (`Is Gap` = True). `Is_locked_gap` is True for gaps before the solver start date (6 Nov): those days
have already happened and are never filled. `Optimised User Id` stays blank here; only CP-SAT fills it.

    python gap_generation/make_gaps.py
    python gap_generation/make_gaps.py --seed 7 --output-dir gap_generation/output_seed7
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from option_generation.data import (  # noqa: E402
    DEFAULT_DATA_DIR as DEFAULT_DATA,
    TRAVEL_TYPES as TRAVEL,
    WORK_TYPES as WORK,
    read_csv,
    write_csv,
)

DEFAULT_OUTPUT = HERE / "output"
FULL, DAY, NIGHT, RANDOM = "Full Swing", "Day Shifts", "Night Shifts", "Random"
LEAVE_SETTINGS = {
    FULL: "Leave Full Swing Fraction",
    DAY: "Leave Day Shifts Fraction",
    NIGHT: "Leave Night Shifts Fraction",
    RANDOM: "Leave Random Fraction",
}
# Columns added to roster_df.csv. The three user columns go right after `User Id`, so the original, after-leave
# and optimised person sit side by side; the gap flags go at the end.
USER_COLUMNS = ["New User Id", "Optimised User Id"]
FLAG_COLUMNS = ["Leave Type", "Is Gap", "Is_locked_gap"]
LEAVE_PLAN_HEADER = ["Leave ID", "User Id", "Classification", "Depot", "Leave Type", "Swing", "First Date",
                     "Last Date", "Shifts On Leave", "Gaps", "Locked Gaps"]  # fmt: skip


def is_day(row: dict[str, str], day_from: int, day_to: int) -> bool:
    minutes = int(row["Shift Start Time"][:2]) * 60 + int(row["Shift Start Time"][3:])
    return day_from <= minutes < day_to


def full_header(roster_columns: list[str]) -> list[str]:
    i = roster_columns.index("User Id") + 1
    return roster_columns[:i] + USER_COLUMNS + roster_columns[i:] + FLAG_COLUMNS


def make_leave(data_dir: Path, seed: int) -> dict:
    cons = {r["Constraint"]: r["Value"] for r in read_csv(data_dir / "constraints_df.csv") if r["Status"] == "Active"}
    crew = {c["User Id"]: c for c in read_csv(data_dir / "crew_master_data_df.csv")}
    roster = read_csv(data_dir / "roster_df.csv")
    cutoff = date.fromisoformat(cons["Solver Start Date"])
    day_from, day_to = (int(t[:2]) * 60 + int(t[3:]) for t in cons["Day Shift Window"].split("-"))
    rng = random.Random(seed)

    # Swings that lie wholly inside the horizon: (user, swing) -> its work rows, in order.
    swings: dict[tuple[str, str], list[dict]] = defaultdict(list)
    outside: set[tuple[str, str]] = set()
    for r in roster:
        if r["Assignment Type"] in WORK:
            key = (r["User Id"], r["Swing"])
            swings[key].append(r)
            if r["In Horizon"] != "Yes":
                outside.add(key)
    for key in outside:
        del swings[key]
    of_user: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in sorted(swings):
        of_user[key[0]].append(key)

    def split_6day(rows: list[dict]) -> tuple[list[dict], list[dict]] | None:
        """Day and night halves of a 3 + 3 Residential swing, or None for any other shape."""
        days = [r for r in rows if is_day(r, day_from, day_to)]
        nights = [r for r in rows if not is_day(r, day_from, day_to)]
        return (days, nights) if len(days) == 3 and len(nights) == 3 else None

    # One leave per person: people in a seeded random order, the leave types handed out in turn.
    wanted = {t: round(len(crew) * float(cons[s])) for t, s in LEAVE_SETTINGS.items()}
    people = sorted(u for u in crew if of_user[u])
    rng.shuffle(people)
    plan: list[dict] = []
    taken: set[str] = set()
    for leave_type in (DAY, NIGHT, FULL, RANDOM):  # the picky types first, so they find their swings
        for uid in people:
            if sum(p["Leave Type"] == leave_type for p in plan) == wanted[leave_type]:
                break
            if uid in taken:
                continue
            options = of_user[uid]
            if leave_type in (DAY, NIGHT):
                options = [k for k in options if crew[uid]["Classification"] == "Residential" and split_6day(swings[k])]
            if not options:
                continue
            key = rng.choice(options)
            rows = swings[key]
            if leave_type == FULL:
                chosen = rows
            elif leave_type == DAY:
                chosen = split_6day(rows)[0]
            elif leave_type == NIGHT:
                chosen = split_6day(rows)[1]
            else:
                length = rng.randint(1, len(rows))
                first = rng.randint(0, len(rows) - length)
                chosen = rows[first : first + length]
            taken.add(uid)
            plan.append({"User Id": uid, "Leave Type": leave_type, "Swing": key[1], "rows": chosen})
    short = {t: wanted[t] - sum(p["Leave Type"] == t for p in plan) for t in wanted}
    if any(short.values()):
        raise SystemExit(f"could not place every leave: {short}")

    # A full-swing FIFO leave also cancels that swing's travel: the person does not come to site.
    travel_of = defaultdict(list)
    for r in roster:
        if r["Assignment Type"] in TRAVEL:
            travel_of[(r["User Id"], r["Swing"])].append(r)

    on_leave: dict[str, str] = {}  # Assignment ID -> leave type
    for p in plan:
        for r in p["rows"]:
            on_leave[r["Assignment ID"]] = p["Leave Type"]
        if p["Leave Type"] == FULL:
            for r in travel_of[(p["User Id"], p["Swing"])]:
                on_leave[r["Assignment ID"]] = FULL

    full = []
    for r in roster:
        leave = on_leave.get(r["Assignment ID"], "")
        gap = bool(leave) and r["Assignment Type"] == "Demand"
        row = dict(r)
        row.update({
            "New User Id": "" if leave else r["User Id"],
            "Optimised User Id": "",  # G4: filled only by CP-SAT, after the whole pipeline has run
            "Leave Type": leave,
            "Is Gap": "True" if gap else "False",
            "Is_locked_gap": ("True" if date.fromisoformat(r["Start Date"]) < cutoff else "False") if gap else "",
        })  # fmt: skip
        full.append(row)

    by_id = {r["Assignment ID"]: r for r in full}
    leave_rows = []
    for i, p in enumerate(sorted(plan, key=lambda p: (p["rows"][0]["Start Date"], p["User Id"])), start=1):
        rows = [by_id[r["Assignment ID"]] for r in p["rows"]]
        c = crew[p["User Id"]]
        leave_rows.append({
            "Leave ID": f"LV{i:04d}", "User Id": p["User Id"], "Classification": c["Classification"],
            "Depot": c["Depot"], "Leave Type": p["Leave Type"], "Swing": p["Swing"],
            "First Date": rows[0]["Start Date"], "Last Date": rows[-1]["Start Date"], "Shifts On Leave": str(len(rows)),
            "Gaps": str(sum(r["Is Gap"] == "True" for r in rows)),
            "Locked Gaps": str(sum(r["Is_locked_gap"] == "True" for r in rows)),
        })  # fmt: skip
    return {"roster": full, "columns": full_header(list(roster[0])), "plan": leave_rows, "cutoff": cutoff,
            "crew": crew}  # fmt: skip


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA, help="optiflux_v2 tables (default: %(default)s)")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="where to write (default: %(default)s)")
    p.add_argument("--seed", type=int, default=2026, help="random seed (default: %(default)s)")
    args = p.parse_args(argv)
    if args.output_dir.resolve() == args.data_dir.resolve():
        raise SystemExit("error: --output-dir must differ from --data-dir (the input tables are never changed)")
    result = make_leave(args.data_dir, args.seed)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    roster = result["roster"]
    write_csv(out / "roster_full.csv", result["columns"], roster)
    write_csv(out / "leave_plan.csv", LEAVE_PLAN_HEADER, result["plan"])

    gaps = [r for r in roster if r["Is Gap"] == "True"]
    locked = sum(r["Is_locked_gap"] == "True" for r in gaps)
    types = Counter(p["Leave Type"] for p in result["plan"])
    rows_off = Counter(r["Assignment Type"] for r in roster if r["Leave Type"])
    print(f"Leave: {len(result['plan'])} of {len(result['crew'])} crew "
          f"({', '.join(f'{t} {n}' for t, n in types.items())})")  # fmt: skip
    print(f"Rows on leave: {sum(rows_off.values())} ({', '.join(f'{t} {n}' for t, n in sorted(rows_off.items()))})")
    print(f"Gaps (Demand rows on leave): {len(gaps)}; locked (before {result['cutoff']}): {locked}; "
          f"to fill: {len(gaps) - locked}")  # fmt: skip
    print(f"Wrote {out / 'roster_full.csv'} and {out / 'leave_plan.csv'}")


if __name__ == "__main__":
    main()
