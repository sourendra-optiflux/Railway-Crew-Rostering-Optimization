#!/usr/bin/env python3
"""Layer 1 of gap filling: list the legal options for every open seat. See option_generation/README.md.

    python option_generation/generate_options.py
    python option_generation/generate_options.py --max-chain 1 --output-dir option_generation/output_chain1
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from option_generation.data import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT,
    DEFAULT_ROSTER_FULL,
    Data,
    load,
    write_csv,
)  # fmt: skip
from option_generation.options import Costs, Generated, generate  # noqa: E402

SEAT_HEADER = ["Seat Key", "Date", "Start", "Activity ID", "Activity Name", "Activity Head", "Priority", "Demand ID",
               "Demand", "Occupants", "Fixed Occupants", "Open Seats", "Gap Assignment IDs", "Chain Level"]  # fmt: skip
SWING_HEADER = ["Swing Key", "User Id", "Swing", "Classification", "Home Depot", "Status", "Reason", "Earliest Start",
                "Latest End", "In Model", "Rows", "Droppable Rows"]  # fmt: skip
OPTION_HEADER = ["Option ID", "Swing Key", "User Id", "Row Index", "Assignment ID", "Row Type", "Kind", "Activity ID",
                 "Start", "End", "Start Location", "End Location", "Demand ID", "Seat Key", "Excess Seat Key",
                 "Standby", "Offset Minutes", "Cost", "Chain Level", "Unchanged"]  # fmt: skip
CANDIDATE_HEADER = ["Seat Key", "Chain Level", "Date", "Start", "Activity Name", "Open Seats", "Gap Assignment IDs",
                    "Candidate User Id", "Source", "Candidate Row", "Candidate Row Start", "Offset Minutes", "Cost"]  # fmt: skip
REJECTION_HEADER = ["Seat Key", "Reason", "Rows Rejected"]
TIME = "%Y-%m-%dT%H:%M"


def fmt(t) -> str:
    return t.strftime(TIME) if t else ""


def write_outputs(data: Data, gen: Generated, out: Path, args) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    model_swings = [sw for sw in gen.swings if sw.in_model]
    in_model_rows = {r["Assignment ID"] for sw in model_swings for r in sw.rows}

    seat_rows = []
    for s in sorted(gen.seats.values(), key=lambda s: (s.start, s.activity_id)):
        activity = data.activities[s.activity_id]
        fixed = sum(aid not in in_model_rows for aid, _ in s.occupants)
        seat_rows.append({
            "Seat Key": s.key, "Date": s.start.date().isoformat(), "Start": s.start.strftime("%H:%M"),
            "Activity ID": s.activity_id, "Activity Name": activity["Activity Name"],
            "Activity Head": activity["Activity Head"], "Priority": data.priority.get(activity["Activity Head"], ""),
            "Demand ID": s.demand_id, "Demand": s.demand, "Occupants": len(s.occupants), "Fixed Occupants": fixed,
            "Open Seats": max(0, s.open), "Gap Assignment IDs": ";".join(s.gap_rows),
            "Chain Level": s.level if s.level >= 0 else "",
        })  # fmt: skip
    write_csv(out / "seats.csv", SEAT_HEADER, seat_rows)

    swing_rows, option_rows, candidates = [], [], []
    for sw in gen.swings:
        swing_rows.append({
            "Swing Key": sw.key, "User Id": sw.user, "Swing": sw.number, "Classification": sw.classification,
            "Home Depot": sw.home, "Status": sw.status, "Reason": sw.reason, "Earliest Start": fmt(sw.earliest_start),
            "Latest End": fmt(sw.latest_end), "In Model": str(sw.in_model),
            "Rows": ";".join(r["Assignment ID"] for r in sw.rows),
            "Droppable Rows": ";".join(r["Assignment ID"] for r, d in zip(sw.rows, sw.droppable) if d),
        })  # fmt: skip
        if not sw.in_model:
            continue
        for i, opts in enumerate(sw.options):
            row = sw.rows[i]
            for o in opts:
                option_rows.append({
                    "Option ID": f"OP{len(option_rows) + 1:07d}", "Swing Key": sw.key, "User Id": sw.user,
                    "Row Index": i, "Assignment ID": row["Assignment ID"], "Row Type": row["Assignment Type"],
                    "Kind": o.kind, "Activity ID": o.activity_id, "Start": fmt(o.start), "End": fmt(o.end),
                    "Start Location": o.start_loc, "End Location": o.end_loc, "Demand ID": o.demand_id,
                    "Seat Key": o.seat, "Excess Seat Key": o.excess_seat, "Standby": str(o.standby),
                    "Offset Minutes": o.offset, "Cost": o.cost, "Chain Level": o.level if o.kind == "fill" else "",
                    "Unchanged": str(o.unchanged),
                })  # fmt: skip
                if o.kind == "fill":
                    s = gen.seats[o.seat]
                    candidates.append({
                        "Seat Key": s.key, "Chain Level": s.level, "Date": s.start.date().isoformat(),
                        "Start": s.start.strftime("%H:%M"),
                        "Activity Name": data.activities[s.activity_id]["Activity Name"],
                        "Open Seats": max(0, s.open), "Gap Assignment IDs": ";".join(s.gap_rows),
                        "Candidate User Id": sw.user, "Source": o.source, "Candidate Row": row["Assignment ID"],
                        "Candidate Row Start": fmt(row["_s"]), "Offset Minutes": o.offset, "Cost": o.cost,
                    })  # fmt: skip
    write_csv(out / "swings.csv", SWING_HEADER, swing_rows)
    write_csv(out / "options.csv", OPTION_HEADER, option_rows)
    candidates.sort(key=lambda c: (c["Chain Level"], c["Date"], c["Start"], c["Seat Key"], c["Cost"]))
    write_csv(out / "gap_options.csv", CANDIDATE_HEADER, candidates)
    rejections = [{"Seat Key": k, "Reason": r, "Rows Rejected": n} for (k, r), n in sorted(gen.rejections.items())]
    rejections += [{"Seat Key": k, "Reason": "no legal sequence in the swing (rest, location, pattern)",
                    "Rows Rejected": n} for k, n in sorted(gen.pruned.items()) if gen.seats[k].level == 0]  # fmt: skip
    write_csv(out / "rejections.csv", REJECTION_HEADER, rejections)

    gap_seats = [s for s in gen.seats.values() if s.level == 0]
    cand_per_gap = Counter(c["Seat Key"] for c in candidates if c["Chain Level"] == 0)
    stats = {
        "gap seats": len(gap_seats),
        "open gap places": sum(s.open for s in gap_seats),
        "gap seats with no candidate": sum(cand_per_gap[s.key] == 0 for s in gap_seats),
        "chain seats": sum(s.level > 0 for s in gen.seats.values()),
        "swings": len(gen.swings),
        "swings frozen": sum(sw.status == "frozen" for sw in gen.swings),
        "swings in model": len(model_swings),
        "options": len(option_rows),
        "fill options": sum(r["Kind"] == "fill" for r in option_rows),
        "ride options": sum(r["Kind"] == "ride" for r in option_rows),
        "fill options by source": Counter(c["Source"] for c in candidates),
        "rejected": Counter(r for (_, r), n in gen.rejections.items() for _ in range(n)),
        "pruned": sum(n for k, n in gen.pruned.items()),
        "residential start restriction": data.rules.residential_start_restriction,
        "relief-only day/night transition": data.rules.relief_only_day_night_transition,
    }
    write_summary(out / "summary.md", stats, args)
    return stats


def write_summary(path: Path, stats: dict, args) -> None:
    lines = [
        "# Option generation result",
        "",
        "Generated by `python option_generation/generate_options.py`; do not edit by hand.",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Roster with gaps | `{args.roster_full}` |",
        f"| Max Demand moves in a chain | {args.max_chain} |",
        f"| Residential start restriction | {'on' if stats['residential start restriction'] else 'off'} |",
        f"| Relief-only day/night transition | {'on' if stats['relief-only day/night transition'] else 'off'} |",
        f"| Gap seats (open, from the solver start) | {stats['gap seats']} seats, {stats['open gap places']} places |",
        f"| Gap seats with no legal candidate | {stats['gap seats with no candidate']} |",
        f"| Seats opened by Demand moves (chain levels 1+) | {stats['chain seats']} |",
        f"| Swings: total / frozen / in the CP-SAT model | {stats['swings']} / {stats['swings frozen']} / {stats['swings in model']} |",
        f"| Options passed to CP-SAT | {stats['options']} ({stats['fill options']} fill, {stats['ride options']} ride, rest keep) |",
        f"| Fill options by source | {', '.join(f'{k} {v}' for k, v in sorted(stats['fill options by source'].items()))} |",
        f"| Fill options removed by sequence pruning | {stats['pruned']} |",
        "",
        "## Why rows were rejected for gap seats (same-day rows only)",
        "",
        "| Reason | Rows |",
        "|---|---|",
    ]
    lines += [f"| {r} | {n:,} |" for r, n in stats["rejected"].most_common()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--roster-full", type=Path, default=DEFAULT_ROSTER_FULL, help="output of gap_generation")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="YAML constraint switches (default: config.yml)")
    p.add_argument("--max-chain", type=int, default=2, help="max Demand moves in one chain (F2), default 2")
    p.add_argument("--allow-stand-down", action="store_true", help="let rows of Excess/Relief be dropped")
    p.add_argument("--no-return-rides", action="store_true", help="no trips across the line as Excess")
    args = p.parse_args(argv)
    data = load(args.data_dir, args.roster_full, args.config)
    gen = generate(data, Costs(), args.max_chain, args.allow_stand_down, not args.no_return_rides)
    stats = write_outputs(data, gen, args.output_dir, args)
    print(f"Gap seats {stats['gap seats']} ({stats['open gap places']} places), "
          f"{stats['gap seats with no candidate']} with no candidate; chain seats {stats['chain seats']}")  # fmt: skip
    print(f"Swings {stats['swings']}: {stats['swings frozen']} frozen, {stats['swings in model']} in the model")
    print(f"Options {stats['options']} ({stats['fill options']} fill: "
          f"{dict(stats['fill options by source'])}; {stats['ride options']} ride)")  # fmt: skip
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
