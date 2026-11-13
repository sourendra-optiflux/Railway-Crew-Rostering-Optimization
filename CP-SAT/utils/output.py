"""Write the solver's choice into roster_full.csv (`Optimised User Id`) and the report files.

`Optimised User Id` starts as `New User Id` (blank on leave rows) and changes only where the solver moved
someone:
    * the row a person leaves (a Relief standby, an Excess row, or their own Demand seat) becomes blank;
    * the row of the seat they take (a gap row, or a Demand row someone else left) gets their id.
A trip home as Excess has no row of its own yet, so it is added as a new row with a `-R` Assignment ID.
`Optimisation Note` says what happened on every changed row.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from option_generation.data import PERSON, Data, write_csv
from option_generation.options import Option, seat_key

NOTE = "Optimisation Note"
CREW_CLASSIFICATION = "Crew Classification"


def apply(data: Data, swings, chosen: dict[str, list[Option | None]], seats) -> dict:
    roster = [dict(r) for r in data.roster]
    by_id = {r["Assignment ID"]: r for r in roster}
    for r in roster:
        r["Optimised User Id"] = r[PERSON]
        r[NOTE] = ""
    rows_of_seat: dict[str, list[dict]] = defaultdict(list)
    for r in roster:
        if r["Assignment Type"] == "Demand" and data.rules.solvable(r["_s"].date()):
            rows_of_seat[seat_key(r["Activity ID"], r["_s"])].append(r)

    fills, rides, dropped, extra = [], [], [], []
    swing_of = {sw.key: sw for sw in swings}
    for key, per_row in chosen.items():
        sw = swing_of[key]
        for row_id, option in zip(sw.row_ids, per_row):
            row = by_id[row_id]
            if option is not None and option.kind == "keep":
                continue
            row["Optimised User Id"] = ""
            if option is None:
                row[NOTE] = f"{sw.user} stood down to make room"
                dropped.append(row)
            elif option.kind == "fill":
                row[NOTE] = f"{sw.user} moved to {data.activities[option.activity_id]['Activity Name']} " \
                            f"{option.start:%Y-%m-%d %H:%M}"
                fills.append((sw, row, option))
            else:  # ride
                row[NOTE] = f"{sw.user} rides home as Excess"
                rides.append((sw, row, option))
                activity = data.activities[option.activity_id]
                new = {c: "" for c in data.columns}
                new.update({
                    "Assignment ID": f"{row_id}-R", "Optimised User Id": sw.user,
                    "Start Date": option.start.strftime("%Y-%m-%d"), "End Date": option.end.strftime("%Y-%m-%d"),
                    "Shift Start Time": option.start.strftime("%H:%M"), "Shift End Time": option.end.strftime("%H:%M"),
                    "Activity ID": option.activity_id, "Activity Name": activity["Activity Name"],
                    "Is Locked": "False", "Activity Head": activity["Activity Head"],
                    "Activity Type": activity["Activity Type"], "Activity Group": activity["Activity Group"],
                    "Assignment Type": "Excess", "Demand ID": option.demand_id,
                    "Start Location": option.start_loc, "End Location": option.end_loc, "Line ID": row["Line ID"],
                    "Swing": row["Swing"], "In Horizon": "Yes", "Is Gap": "False", NOTE: f"trip home for {sw.user}",
                })  # fmt: skip
                new["_s"], new["_e"] = option.start, option.end
                extra.append(new)

    # Put each filler on an empty row of the seat they take (a gap row or a row its holder left).
    records = []
    waiting: dict[str, list] = defaultdict(list)
    for sw, row, option in fills:
        waiting[option.seat].append((sw, row, option))
    unplaced = []
    for key, items in waiting.items():
        empty = [r for r in rows_of_seat[key] if not r["Optimised User Id"]]
        empty.sort(key=lambda r: (r["Is Gap"] != "True", r["Assignment ID"]))
        for (sw, row, option), target in zip(items, empty):
            target["Optimised User Id"] = sw.user
            target[NOTE] = f"filled by {sw.user} ({row['Assignment Type']}, from {row['Assignment ID']})"
            records.append({
                "Date": option.start.strftime("%Y-%m-%d"), "Start": option.start.strftime("%H:%M"),
                "Activity ID": option.activity_id, "Activity Name": data.activities[option.activity_id]["Activity Name"],
                "Filled Row": target["Assignment ID"], "Was Gap": target["Is Gap"],
                "Original User Id": target["User Id"], "Optimised User Id": sw.user, "Source": row["Assignment Type"],
                "From Row": row["Assignment ID"], "From Activity": row["Activity Name"],
                "From Start": f"{row['Start Date']} {row['Shift Start Time']}", "Offset Minutes": option.offset,
                "Chain Level": option.level, "Cost": option.cost,
            })  # fmt: skip
        unplaced += items[len(empty):]
    if unplaced:
        raise SystemExit(f"error: {len(unplaced)} fills found no empty row on their seat, e.g. {unplaced[0][2].seat}")

    roster += extra
    for row in roster:
        user = row["Optimised User Id"]
        if user and user not in data.crew:
            raise SystemExit(f"error: no crew classification found for assigned user {user!r}")
        row[CREW_CLASSIFICATION] = data.crew[user]["Classification"] if user else ""
    unfilled = [
        {"Assignment ID": r["Assignment ID"], "Date": r["Start Date"], "Start": r["Shift Start Time"],
         "Activity ID": r["Activity ID"], "Activity Name": r["Activity Name"], "Original User Id": r["User Id"],
         "Kind": "gap" if r["Is Gap"] == "True" else "left by a move", "Is_locked_gap": r["Is_locked_gap"],
         "Leave Type": r["Leave Type"]}  # fmt: skip
        for r in roster
        if r["Assignment Type"] == "Demand" and not r["Optimised User Id"]
    ]
    records.sort(key=lambda f: (f["Date"], f["Start"], f["Activity ID"]))
    return {"roster": roster, "fills": records, "rides": rides, "dropped": dropped, "unfilled": unfilled}


def write_outputs(out, data: Data, result: dict) -> None:
    columns = data.columns + [
        column for column in (CREW_CLASSIFICATION, NOTE) if column not in data.columns
    ]
    write_csv(out / "roster_full.csv", columns, result["roster"])
    write_csv(out / "reassignments.csv", list(result["fills"][0]) if result["fills"] else ["Date"], result["fills"])
    unfilled_cols = ["Assignment ID", "Date", "Start", "Activity ID", "Activity Name", "Original User Id", "Kind",
                     "Is_locked_gap", "Leave Type"]  # fmt: skip
    write_csv(out / "unfilled_gaps.csv", unfilled_cols, result["unfilled"])


def write_summary(path, data: Data, seats, solved, result: dict, validation: dict, args) -> None:
    roster = result["roster"]
    gaps = [r for r in roster if r["Is Gap"] == "True"]
    locked = [r for r in gaps if r["Is_locked_gap"] == "True"]
    to_fill = [r for r in gaps if r["Is_locked_gap"] == "False"]
    filled_gaps = [r for r in to_fill if r["Optimised User Id"]]
    opened = [u for u in result["unfilled"] if u["Kind"] == "left by a move"]
    source = Counter(f["Source"] for f in result["fills"])
    moved = {f["Optimised User Id"] for f in result["fills"]}
    chains = Counter(f["Chain Level"] for f in result["fills"])
    lines = [
        "# CP-SAT gap filling result",
        "",
        "Generated by `python CP-SAT/run_gap_filling.py`; do not edit by hand.",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Solver start (rows before it never change) | {data.rules.solver_start} |",
        f"| Residential start restriction | {'on' if data.rules.residential_start_restriction else 'off'} |",
        f"| Relief-only day/night transition | {'on' if data.rules.relief_only_day_night_transition else 'off'} |",
        f"| Activity-head max shifts | {'on' if data.rules.activity_head_max_shifts else 'off'} |",
        f"| Priority strategy | {data.rules.priority_strategy} |",
        f"| Gaps (Demand rows on leave) | {len(gaps)} |",
        f"| Locked gaps (before the solver start) | {len(locked)} |",
        f"| Gaps to fill | {len(to_fill)} |",
        f"| Gaps filled | **{len(filled_gaps)}** ({100 * len(filled_gaps) / max(len(to_fill), 1):.1f}%) |",
        f"| Seats left open by a Demand move | {len(opened)} |",
        *[
            f"| Objective stage: {name.replace('_', ' ')} | {status}"
            + (f" (value {solved.stage_values[name]}, bound {solved.stage_bounds[name]:.0f})"
               if name in solved.stage_values else "")
            + " |"
            for name, status in solved.stage_statuses.items()
        ],
        (f"| Assignment cost | {solved.cost} (lower bound {solved.cost_bound}) |" if solved.cost is not None
         else f"| Assignment cost | not minimized ({solved.cost_status}) |"),
        f"| Seats filled by Excess / Relief / Demand | {source['Excess']} / {source['Relief']} / {source['Demand']} |",
        f"| Fills by chain level (0 = gap seat) | {', '.join(f'{k}: {v}' for k, v in sorted(chains.items()))} |",
        f"| People moved | {len(moved)} |",
        f"| Trips home as Excess | {len(result['rides'])} |",
        f"| Rows stood down | {len(result['dropped'])} |",
        f"| Solve time | {solved.seconds:.1f} s |",
        f"| Rule check | {validation['headline']} |",
        "",
        "## By activity",
        "",
        "| Activity | Gaps to fill | Filled |",
        "|---|---|---|",
    ]
    want = Counter(r["Activity Name"] for r in to_fill)
    got = Counter(r["Activity Name"] for r in filled_gaps)
    lines += [f"| {a} | {n} | {got[a]} |" for a, n in sorted(want.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
