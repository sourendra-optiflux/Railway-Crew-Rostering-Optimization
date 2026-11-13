import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CP-SAT"))

from utils.validate import recovery_checks  # noqa: E402

from option_generation.data import DEFAULT_DATA_DIR, read_csv  # noqa: E402
from option_generation.rules import DEFAULT_CONFIG, Rules  # noqa: E402


def make_rules(**overrides):
    rules = Rules.from_table(read_csv(DEFAULT_DATA_DIR / "constraints_df.csv"), DEFAULT_CONFIG)
    return replace(
        rules,
        rest=timedelta(hours=8),
        transition_rest=timedelta(hours=8),
        day_from=6 * 60,
        day_to=18 * 60,
        **overrides,
    )


def row(assignment_id, assignment_type, start, end, new_user, optimized_user, note=""):
    return {
        "Assignment ID": assignment_id,
        "Assignment Type": assignment_type,
        "Start Date": start.date().isoformat(),
        "Shift Start Time": start.strftime("%H:%M"),
        "Shift End Time": end.strftime("%H:%M"),
        "New User Id": new_user,
        "Optimised User Id": optimized_user,
        "User Id": new_user or optimized_user,
        "Swing": "1",
        "Activity ID": assignment_id,
        "Start Location": "A",
        "End Location": "A",
        "Is Gap": "False",
        "Is_locked_gap": "False",
        "Leave Type": "",
        "Optimisation Note": note,
        "_s": start,
        "_e": end,
    }


def check(data_rules, roster):
    activities = {r["Activity ID"]: {"Roles/Job": "Role", "Currency Threshold": ""} for r in roster}
    data = SimpleNamespace(
        rules=data_rules,
        crew={"U1": {"Classification": "Residential", "Role": "Role", "Medical": "Fit"}},
        demand={},
        activities=activities,
        eligible={activity_id: {"U1"} for activity_id in activities},
        last_done={},
    )
    return recovery_checks(data, roster, set())


def check_failures(checks, rule_id):
    return next(failures for code, _, failures in checks if code == rule_id)


@pytest.mark.parametrize(
    ("start", "forbidden"),
    [
        ("2026-11-07T21:59", False),
        ("2026-11-07T22:00", True),
        ("2026-11-08T00:00", True),
        ("2026-11-08T01:59", True),
        ("2026-11-08T02:00", False),
    ],
)
def test_validator_detects_only_new_residential_starts_in_restricted_window(start, forbidden):
    rules = make_rules()
    start_dt = datetime.fromisoformat(start)
    changed = row("NEW", "Demand", start_dt, start_dt + timedelta(hours=8), "", "U1")

    failures = check_failures(check(rules, [changed]), "V7")

    assert bool(failures) is forbidden


def test_validator_preserves_unchanged_residential_night_assignment():
    rules = make_rules()
    unchanged_start = datetime(2026, 11, 7, 23)
    unchanged = row("OLD", "Demand", unchanged_start, unchanged_start + timedelta(hours=8), "U1", "U1")
    changed_start = datetime(2026, 11, 9, 6)
    changed = row("NEW", "Demand", changed_start, changed_start + timedelta(hours=8), "", "U1")

    assert check_failures(check(rules, [unchanged, changed]), "V7") == []


def test_validator_honors_disabled_residential_start_restriction():
    rules = make_rules(residential_start_restriction=False)
    start = datetime(2026, 11, 7, 23)
    changed = row("NEW", "Demand", start, start + timedelta(hours=8), "", "U1")

    assert check_failures(check(rules, [changed]), "V7") == []


def test_recovery_sequence_does_not_duplicate_a_changed_work_assignment():
    rules = make_rules()
    start = datetime(2026, 11, 7, 6)
    changed = row("CHANGED", "Demand", start, start + timedelta(hours=8), "U2", "U1")

    assert check_failures(check(rules, [changed]), "V6") == []


def test_validator_detects_restricted_start_when_user_id_is_unchanged():
    rules = make_rules()
    source_start = datetime(2026, 11, 7, 6)
    source = row("SOURCE", "Demand", source_start, source_start + timedelta(hours=8), "U1", "")
    source["Optimisation Note"] = "U1 moved to target"
    changed_start = datetime(2026, 11, 8, 23)
    changed = row(
        "TARGET",
        "Demand",
        changed_start,
        changed_start + timedelta(hours=8),
        "U1",
        "U1",
        "filled by U1 (Demand, from SOURCE)",
    )

    assert check_failures(check(rules, [source, changed]), "V7") == [
        "U1 TARGET starts at 23:00"
    ]


@pytest.mark.parametrize(
    ("enabled", "previous_type", "previous_source", "violation"),
    [
        (True, "Demand", "Demand", True),
        (True, "Demand", "Relief", False),
        (False, "Demand", "Demand", False),
    ],
)
def test_validator_checks_relief_only_day_night_transition(enabled, previous_type, previous_source, violation):
    rules = make_rules(relief_only_day_night_transition=enabled)
    previous_start = datetime(2026, 11, 1, 19)
    previous_note = ""
    roster = []
    if previous_source != previous_type:
        roster.append(row("SOURCE", previous_source, previous_start, previous_start + timedelta(hours=8), "U1", ""))
        previous_note = "filled by U1 (Relief, from SOURCE)"
    previous = row(
        "PREV", previous_type, previous_start, previous_start + timedelta(hours=8), "U1", "U1", previous_note
    )
    next_start = datetime(2026, 11, 3, 6)
    next_assignment = row("NEXT", "Demand", next_start, next_start + timedelta(hours=8), "", "U1")
    roster.extend([previous, next_assignment])

    failures = check_failures(check(rules, roster), "V6")

    assert any("day/night change follows" in failure for failure in failures) is violation
