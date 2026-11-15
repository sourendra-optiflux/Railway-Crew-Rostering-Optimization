"""Streamlit UI smoke tests using streamlit.testing.v1.AppTest."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = str(ROOT / "visualization" / "app.py")


def test_dashboard_app_boots_and_navigates_without_exception():
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.run()
    assert not at.exception

    # Navigate across key sections to verify view modules render cleanly
    nav_radios = [r for r in at.radio if r.label == "Navigation"]
    assert len(nav_radios) == 1
    for target in [
        "0. Input Data & Readiness",
        "2. Demand vs Coverage",
        "3. Crew Assignment",
        "4. Gap Analysis",
        "5. Constraint Diagnostics",
        "6. Strategy Comparison",
        "7. Workload, Chains & Depots",
        "8. Skill & Currency Radar",
        "9. What-If & Disruption Simulator",
        "10. Pipeline, Tests & Exports",
        "11. Solver Log Explorer",
    ]:
        nav_radios[0].set_value(target).run()
        assert not at.exception, f"Exception on section {target}: {at.exception}"
