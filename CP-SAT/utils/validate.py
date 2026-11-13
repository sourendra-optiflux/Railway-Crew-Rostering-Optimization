"""Check the optimised roster with scripts/check_roster.py, which shares no code with the solver.

Leave on its own already breaks some roster rules: open seats (G1), Excess on a seat that is now short
(G5), a Residential swing whose day shifts are on leave starting on a night shift (R1), a swing cut in two
by leave (off time, travel). So the checker runs twice: on the roster after leave (`New User Id`) and on
the optimised roster (`Optimised User Id`). A check that fails only after optimisation is a real failure.

Recovery checks V1-V6 are added on top. They look at every person whose rows changed.
"""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from option_generation.data import ROOT, WORK_TYPES, Data, why_not_eligible, write_csv
from option_generation.rules import SWING_BREAK

COPIED_TABLES = (
    "activities_df.csv", "activity_demand_df.csv", "activity_priority.csv", "compliance_matrix_df.csv",
    "constraints_df.csv", "crew_competencies_df.csv", "crew_currency_df.csv", "crew_restrictions.csv",
    "Crew_Onsite_App.csv", "excluded_activities.csv", "crew_master_data_df.csv", "eligibility_matrix.csv",
)  # fmt: skip


def load_checker():
    spec = importlib.util.spec_from_file_location("check_roster", ROOT / "scripts" / "check_roster.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def as_roster(data: Data, roster: list[dict], person: str) -> list[dict]:
    """roster_df-shaped rows, with `User Id` taken from the given person column; rows with no one are left out."""
    out = []
    for r in roster:
        if r.get(person):
            row = {c: r.get(c, "") for c in data.columns if c not in ("New User Id", "Optimised User Id")}
            row["User Id"] = r[person]
            out.append(row)
    return out


def run_checker(checker, data_dir: Path, data: Data, rows: list[dict]):
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp)
        for table in COPIED_TABLES:
            shutil.copy(data_dir / table, staged / table)
        columns = [c for c in data.columns if c not in ("New User Id", "Optimised User Id")]
        write_csv(staged / "roster_df.csv", columns, rows)
        return checker.run(staged).results


def recovery_checks(data: Data, roster: list[dict], frozen_keys: set[tuple[str, str]]) -> list[tuple]:
    rules = data.rules
    by_id = {r["Assignment ID"]: r for r in roster}

    def source_assignment(row: dict) -> dict | None:
        note = row.get("Optimisation Note", "")
        if note.startswith("filled by ") and note.endswith(")") and ", from " in note:
            source_id = note.rsplit(", from ", 1)[1][:-1]
            return by_id.get(source_id)
        return None

    def is_changed_assignment(row: dict) -> bool:
        if row.get("Optimisation Note", "").startswith("filled by "):
            source = source_assignment(row)
            return (
                source is None
                or source["New User Id"] != row["Optimised User Id"]
                or source["_s"] != row["_s"]
                or source["Activity ID"] != row["Activity ID"]
            )
        return row["Optimised User Id"] != row["New User Id"]

    changed_people = {
        r["Optimised User Id"]
        for r in roster
        if r["Optimised User Id"] and (r["Optimised User Id"] != r["New User Id"] or is_changed_assignment(r))
    }
    before_start = [r["Assignment ID"] for r in roster if r["_s"].date() < rules.solver_start
                    and r["Optimised User Id"] != r["New User Id"]]  # fmt: skip
    per_seat = Counter((r["Activity ID"], r["_s"]) for r in roster
                       if r["Assignment Type"] == "Demand" and r["Optimised User Id"])  # fmt: skip
    demand = {(a, s): int(d["Demand"]) for (a, s), d in data.demand.items()}
    over = [f"{a} {s}" for (a, s), n in per_seat.items() if n > demand.get((a, s.strftime("%H:%M")), 0)]

    unfit, from_frozen = [], []
    for r in roster:
        user = r["Optimised User Id"]
        if not user or user == r["New User Id"] or r["Assignment Type"] != "Demand":
            continue
        reason = why_not_eligible(data, user, r["Activity ID"], r["_s"].date())
        if reason:
            unfit.append(f"{user} {r['Assignment ID']} ({reason})")
    # V5: a frozen swing may only lose a row to its own Excess person taking the very same seat.
    on_seat = {(r["Optimised User Id"], r["Activity ID"], r["_s"]) for r in roster if r["Assignment Type"] == "Demand"}
    for r in roster:
        if r["New User Id"] and not r["Optimised User Id"] and (r["New User Id"], r["Swing"]) in frozen_keys:
            same = r["Assignment Type"] == "Excess" and (r["New User Id"], r["Activity ID"], r["_s"]) in on_seat
            if not same:
                from_frozen.append(f"{r['New User Id']} {r['Assignment ID']} ({r.get('Optimisation Note', '')})")

    # V6: every changed person's work, in order: rest, day/night rest, one shift a day, location, pattern.
    seq: dict[str, list[dict]] = defaultdict(list)
    residential_start_violations = []
    for r in roster:
        user = r["Optimised User Id"]
        if user not in changed_people:
            continue
        if r["Assignment Type"] in WORK_TYPES:
            seq[user].append(r)
            if (rules.residential_start_restriction
                    and data.crew[user]["Classification"] == "Residential"
                    and is_changed_assignment(r)
                    and not rules.residential_start_allowed(r["_s"])):
                residential_start_violations.append(f"{user} {r['Assignment ID']} starts at {r['_s']:%H:%M}")

    def source_type(row: dict) -> str:
        source = source_assignment(row)
        if source is not None:
            return source["Assignment Type"]
        return row["Assignment Type"]

    bad = []
    for user, rows in seq.items():
        rows.sort(key=lambda r: r["_s"])
        changes = 0
        for a, b in zip(rows, rows[1:]):
            gap = b["_s"] - a["_e"]
            if gap > SWING_BREAK:
                changes = 0
                continue
            if a["_s"].date() == b["_s"].date() or gap < rules.rest:
                bad.append(f"{user} {b['Assignment ID']} rest {gap}")
            same_block = rules.is_day(a["_s"]) == rules.is_day(b["_s"])
            if not same_block:
                changes = 0
                if rules.relief_only_day_night_transition and source_type(a) != "Relief":
                    bad.append(f"{user} {b['Assignment ID']} day/night change follows {source_type(a)}")
                if gap < rules.transition_rest:
                    bad.append(f"{user} {b['Assignment ID']} day/night rest {gap}")
            if a["End Location"] != b["Start Location"]:
                bad.append(f"{user} {b['Assignment ID']} starts at {b['Start Location']}, was at {a['End Location']}")
        worked = [r for r in rows if r["Assignment Type"] != "Relief"]
        changes = 0
        for a, b in zip(worked, worked[1:]):
            if b["_s"] - a["_e"] > SWING_BREAK or rules.is_day(a["_s"]) != rules.is_day(b["_s"]):
                changes = 0
                continue
            step = abs(rules.block_minute(a["_s"]) - rules.block_minute(b["_s"]))
            if step:
                changes += 1
                if step > rules.max_change_minutes or changes > rules.max_changes:
                    bad.append(f"{user} {b['Assignment ID']} start {a['Shift Start Time']}->{b['Shift Start Time']}")
    return [
        ("V1", "Rows before the solver start are unchanged (G1)", before_start),
        ("V2", "No seat has more people than its demand", over),
        ("V3", "Everyone placed on a new seat is certified (matrix), fit, in role and current", unfit),
        ("V5", "Swings that started before the solver start or are on leave lose no rows (F4)", from_frozen),
        ("V6", "Changed people: rest, Relief-only day/night transition, one shift a day, location, one start change per block", bad),
        ("V7", "Changed Residential assignments do not start from 22:00 to 02:00", residential_start_violations),
    ]


def validate(data: Data, data_dir: Path, roster: list[dict], frozen_keys: set[tuple[str, str]], out: Path) -> dict:
    checker = load_checker()
    plain = [r for r in roster if not r["Assignment ID"].endswith("-R")]
    before = {(r[0], r[1]): r[2] for r in run_checker(checker, data_dir, data, as_roster(data, plain, "New User Id"))}
    after = run_checker(checker, data_dir, data, as_roster(data, roster, "Optimised User Id"))
    extra = recovery_checks(data, roster, frozen_keys)
    results = []
    for rule, text, ok, detail in after:
        state = "PASS" if ok else ("fails after leave too" if not before.get((rule, text), True) else "FAIL")
        results.append((rule, text, state, detail))
    for rule, text, fails in extra:
        detail = "; ".join(fails[:3]) + (f" (+{len(fails) - 3} more)" if len(fails) > 3 else "")
        results.append((rule, text, "PASS" if not fails else "FAIL", detail))
    unexpected = [r for r in results if r[2] == "FAIL"]
    lines = [
        "# Rule check of the optimised roster",
        "",
        "`scripts/check_roster.py` on the optimised roster, compared with the roster after leave, plus recovery",
        "checks V1-V6. `fails after leave too` means leave alone already breaks that rule (for example open seats).",
        "",
        f"**{sum(r[2] == 'PASS' for r in results)} of {len(results)} pass; {len(unexpected)} unexpected failure(s).**",
        "",
        "| Rule | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    lines += [f"| {r} | {t} | {s} | {d.replace('|', '/')} |" for r, t, s, d in results]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    headline = f"{sum(r[2] == 'PASS' for r in results)}/{len(results)} pass, {len(unexpected)} unexpected failure(s)"
    return {"headline": headline, "unexpected": unexpected}
