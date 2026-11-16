"""Streamlit UI smoke tests using streamlit.testing.v1.AppTest."""

from __future__ import annotations

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = st_testing.AppTest

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = str(ROOT / "visualization" / "app.py")


def test_dashboard_app_boots_and_navigates_without_exception():
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.run()
    assert not at.exception

    # Navigate across all pages to verify view modules render cleanly
    nav_radios = [r for r in at.radio if r.label == "Navigation"]
    assert len(nav_radios) == 1
    for target in [
        "2. Demand & Coverage Analysis",
        "3. Crew Allocation & Roster Gantt",
        "4. Unfilled Gap & Bottleneck Forensics",
        "5. Priority, Stages & Telemetry",
        "6. Validation & Solution Diagnostics",
        "7. What-If Simulator & Pipeline Ops",
        "1. Executive Overview & Brief",
    ]:
        nav_radio = [r for r in at.radio if r.label == "Navigation"][0]
        nav_radio.set_value(target).run()
        assert not at.exception, f"Exception on page {target}: {at.exception}"
