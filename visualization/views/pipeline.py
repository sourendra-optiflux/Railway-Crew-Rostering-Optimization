"""Pipeline runner, pytest runner, edge-case demo, and export center views."""

from __future__ import annotations

import sys

import streamlit as st

from visualization.analytics import (
    compute_crew_workload_analytics,
    compute_depot_and_travel_analytics,
    compute_solver_cost_and_offset_analytics,
)
from visualization.data_loader import ROOT, DashboardDataset
from visualization.export_utils import datasets_to_excel_bytes, rows_to_csv_bytes
from visualization.gap_analysis import build_unfilled_gap_records
from visualization.metrics import (
    aggregate_by_activity_head,
    compute_summary_kpis,
)
from visualization.run_history import record_run
from visualization.scenario_runner import stream_command
from visualization.views.solver_log_viewer import render_solver_log_visualizer


def render_pipeline_and_exports(
    dataset: DashboardDataset,
    all_slots: list[dict[str, object]],
    preset: str,
) -> None:
    """Render Section 10: Pipeline, Test Suite, Edge-Case Demo & Export Center."""
    st.subheader("Run Pipeline, Test Suite & Download Center")
    st.markdown(
        "Execute the complete end-to-end rostering workflow, run automated tests, "
        "or export complete roster and diagnostic reports to CSV / Excel."
    )

    tab_pipeline, tab_tests, tab_edge_demo, tab_exports = st.tabs([
        "Full Rostering Pipeline",
        "Pytest Suite & Rule Checks",
        "Edge-Case Multi-Run Demo",
        "Download & Export Center",
    ])

    with tab_pipeline:
        st.markdown("### End-to-End Gap Filling Pipeline")
        st.info(
            "Steps executed in sequence:\n"
            "1. `scripts/build_optiflux_v2_data.py` (Base data & constraints)\n"
            "2. `scripts/roster_making.py` (Initial roster & crew master data)\n"
            "3. `gap_generation/make_gaps.py` (Generate leave gaps)\n"
            "4. `option_generation/generate_options.py` (Generate candidate move options)\n"
            "5. `CP-SAT/run_gap_filling.py` (Run CP-SAT solver to fill gaps)"
        )

        col1, col2 = st.columns(2)
        with col1:
            run_data_gen = st.checkbox(
                "Include Step 1 & 2 (Rebuild base data & initial roster)",
                value=False,
                help="Unchecked by default so custom edits to data/optiflux_v2/*.csv are preserved.",
            )
        with col2:
            time_limit = st.number_input("CP-SAT Time Limit per stage (seconds)", min_value=10, max_value=600, value=60, step=10)

        if st.button("Run Full Planner Pipeline", type="primary"):
            steps: list[tuple[str, list[str]]] = []
            if run_data_gen:
                steps.append(("1. Building OptiFlux v2 Data", [sys.executable, "scripts/build_optiflux_v2_data.py"]))
                steps.append(("2. Building Initial Roster", [sys.executable, "scripts/roster_making.py"]))
            steps.append(("3. Generating Leave Gaps", [sys.executable, "gap_generation/make_gaps.py"]))
            steps.append(("4. Generating Move Options", [sys.executable, "option_generation/generate_options.py", "--config", "config.yml"]))
            steps.append((
                "5. Running CP-SAT Solver",
                [sys.executable, "CP-SAT/run_gap_filling.py", "--config", "config.yml", "--time-limit", str(time_limit)],
            ))

            prog_bar = st.progress(0)
            status_box = st.empty()
            live_log_box = st.empty()
            full_lines: list[str] = []
            all_ok = True

            def _append_log(line: str) -> None:
                full_lines.append(line)
                live_log_box.code("\n".join(full_lines[-80:]))

            for idx, (label, cmd) in enumerate(steps):
                status_box.info(f"Executing: **{label}**...")
                prog_bar.progress(int((idx / len(steps)) * 100))
                _append_log(f"=== {label} ===")
                try:
                    rc, _ = stream_command(cmd, cwd=ROOT, log_callback=_append_log)
                    if rc != 0:
                        all_ok = False
                        status_box.error(f"Step failed: **{label}** (Exit code {rc})")
                        break
                except Exception as exc:
                    all_ok = False
                    status_box.error(f"Execution error in **{label}**: {exc}")
                    break

            if all_ok:
                prog_bar.progress(100)
                status_box.success("Pipeline completed successfully! Refreshing cached data...")
                st.cache_data.clear()
                kpis = compute_summary_kpis(dataset)
                cost_data = compute_solver_cost_and_offset_analytics(dataset)
                record_run(
                    run_type="Pipeline",
                    preset=preset,
                    strategy=str(dataset.config_flags.get("priority_strategy", "none")),
                    rule_toggles={
                        "run_data_gen": run_data_gen,
                        "time_limit": int(time_limit),
                    },
                    total_demand=kpis.total_demand,
                    assigned_demand=kpis.assigned_demand,
                    unfilled_demand=kpis.unfilled_demand,
                    coverage_pct=kpis.coverage_pct,
                    total_cost=float(cost_data["total_cost"]),
                )

            full_log_text = "\n".join(full_lines)
            st.session_state["last_solver_log"] = full_log_text
            try:
                (dataset.cpsat_dir / "solver.log").write_text(full_log_text, encoding="utf-8")
            except OSError:
                pass
            render_solver_log_visualizer(full_log_text, title="Pipeline Solver Log Visualizer", key_prefix="pipe_log")

    with tab_tests:
        st.markdown("### Automated Pytest Suite & Roster Rule Validator")
        c_test1, c_test2 = st.columns([2, 1])
        with c_test1:
            test_target = st.selectbox(
                "Test Target",
                options=[
                    "All Tests (pytest -q)",
                    "Dashboard Tests (tests/test_dashboard_visualization.py)",
                    "Dashboard UI Smoke Tests (tests/test_dashboard_ui.py)",
                    "Constraint Config Tests (tests/test_constraint_config.py)",
                    "Priority Tests (tests/test_activity_head_priority.py)",
                    "Data & Roster Tests (tests/test_optiflux_v2_data.py)",
                    "Initial Roster Rule Checks (scripts/check_roster.py)",
                ],
            )
        with c_test2:
            st.write("")
            st.write("")
            run_test_btn = st.button("Execute Tests", type="primary")

        if run_test_btn:
            if test_target == "Initial Roster Rule Checks (scripts/check_roster.py)":
                cmd = [sys.executable, "scripts/check_roster.py", "--write-report"]
            elif "UI Smoke Tests" in test_target:
                cmd = [sys.executable, "-m", "pytest", "tests/test_dashboard_ui.py", "-q"]
            elif "Dashboard Tests" in test_target:
                cmd = [sys.executable, "-m", "pytest", "tests/test_dashboard_visualization.py", "-q"]
            elif "Constraint Config" in test_target:
                cmd = [sys.executable, "-m", "pytest", "tests/test_constraint_config.py", "-q"]
            elif "Priority Tests" in test_target:
                cmd = [sys.executable, "-m", "pytest", "tests/test_activity_head_priority.py", "-q"]
            elif "Data & Roster" in test_target:
                cmd = [sys.executable, "-m", "pytest", "tests/test_optiflux_v2_data.py", "-q"]
            else:
                cmd = [sys.executable, "-m", "pytest", "-q"]

            st.info(f"Running: `{' '.join(cmd)}`...")
            live_test_box = st.empty()
            test_lines: list[str] = []

            def _append_test_line(line: str) -> None:
                test_lines.append(line)
                live_test_box.code("\n".join(test_lines[-80:]))

            rc, output = stream_command(cmd, cwd=ROOT, log_callback=_append_test_line)
            if rc == 0:
                st.success("All checks / tests passed!")
            else:
                st.error(f"Tests failed with exit code {rc}")
            with st.expander("Full Test Output", expanded=False):
                st.code(output)

    with tab_edge_demo:
        st.markdown("### Edge-Case Multi-Run Generator (`scripts/edge_case_demo.py`)")
        st.markdown(
            "Runs all 7 edge-case solver passes across strategy combinations, tight shift limits, "
            "residential restrictions, and relief transitions."
        )
        if st.button("Run Edge-Case Demo Suite", type="secondary"):
            live_demo_box = st.empty()
            demo_lines: list[str] = []

            def _append_demo_line(line: str) -> None:
                demo_lines.append(line)
                live_demo_box.code("\n".join(demo_lines[-80:]))

            rc, out_txt = stream_command([sys.executable, "scripts/edge_case_demo.py"], cwd=ROOT, log_callback=_append_demo_line)
            if rc == 0:
                st.success("Edge-case runs completed successfully!")
                st.cache_data.clear()
            else:
                st.error(f"Edge-case demo failed with exit code {rc}")
            with st.expander("Full Edge-Case Demo Output", expanded=False):
                st.code(out_txt)

    with tab_exports:
        st.markdown("### Download & Export Center")
        st.markdown("Export full solver outputs, analytics, and reports in CSV or multi-sheet Excel (`.xlsx`) format.")

        export_unfilled = build_unfilled_gap_records(dataset)
        export_workload = compute_crew_workload_analytics(dataset)["crew_rows"]
        export_depot = compute_depot_and_travel_analytics(dataset)["depot_rows"]
        export_head_agg = aggregate_by_activity_head(all_slots)

        e1, e2, e3, e4 = st.columns(4)
        with e1:
            st.download_button(
                "Optimized Roster (CSV)",
                data=rows_to_csv_bytes(dataset.roster_rows),
                file_name="optimized_roster_full.csv",
                mime="text/csv",
            )
        with e2:
            st.download_button(
                "Unfilled Gaps (CSV)",
                data=rows_to_csv_bytes(export_unfilled),
                file_name="unfilled_gaps_analysis.csv",
                mime="text/csv",
            )
        with e3:
            st.download_button(
                "Reassignments Log (CSV)",
                data=rows_to_csv_bytes(dataset.reassignments),
                file_name="reassignments_log.csv",
                mime="text/csv",
            )
        with e4:
            st.download_button(
                "Crew Workload & Fairness (CSV)",
                data=rows_to_csv_bytes(export_workload),
                file_name="crew_workload_fairness.csv",
                mime="text/csv",
            )

        st.markdown("---")
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                "Download Complete Multi-Sheet Excel Report (.xlsx)",
                data=datasets_to_excel_bytes({
                    "Activity Head Summary": export_head_agg,
                    "Unfilled Gaps": export_unfilled,
                    "Reassignments": dataset.reassignments,
                    "Crew Workload": export_workload,
                    "Depot Balance": export_depot,
                    "Optimized Roster": dataset.roster_rows,
                }),
                file_name="optiflux_rostering_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        with dl_col2:
            solver_xlsx = dataset.cpsat_dir / "optiflux_all_tables.xlsx"
            if solver_xlsx.exists():
                st.download_button(
                    "Download Solver Native Workbook (optiflux_all_tables.xlsx)",
                    data=solver_xlsx.read_bytes(),
                    file_name="optiflux_all_tables.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
