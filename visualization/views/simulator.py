"""Rules, Constraints & Objectives Control Center, What-If Simulator, Disruption Simulator, and Run History."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import plotly.express as px
import streamlit as st

from visualization.analytics import (
    compute_slot_diff_matrix,
    compute_solver_cost_and_offset_analytics,
)
from visualization.charts import create_slot_diff_heatmap
from visualization.data_loader import DashboardDataset
from visualization.gap_analysis import build_unfilled_gap_records
from visualization.metrics import compute_summary_kpis
from visualization.run_history import clear_runs, list_runs, record_run
from visualization.scenario_runner import (
    run_disruption_simulation,
    run_what_if_scenario,
    save_active_config_and_constraints,
)
from visualization.views.solver_log_viewer import render_solver_log_visualizer


def _read_csv_dict_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _parse_int(value: str, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def render_simulator(
    dataset: DashboardDataset,
    config_path: Path,
    base_roster_input: Path,
    preset: str,
) -> None:
    """Render Section 9: Rules/Constraints/Objectives Control Center, What-If, Disruption & Run History."""
    st.subheader("Rules, Constraints & Objectives Control Center | What-If & Disruption Simulator")
    tab_whatif, tab_disrupt, tab_history = st.tabs([
        "Rules & What-If Scenario Builder",
        "Leave Impact & Disruption Simulator",
        "Run History & Trend",
    ])

    baseline_kpis = compute_summary_kpis(dataset)

    with tab_whatif:
        st.markdown(
            "Activate or deactivate solver rules, constraints, and objectives, tune rest/offset parameters "
            "or activity priorities, and run an **isolated What-If solve** without modifying project files "
            "(unless you explicitly click **Apply to Active Config**)."
        )

        # --- Group 1: Active / Inactive Rule & Constraint Toggles ---
        st.markdown("#### 1. Active / Inactive Rule & Constraint Switches")
        wc1, wc2, wc3 = st.columns(3)
        with wc1:
            wi_res = st.checkbox(
                "Residential Start Restriction (22:00-02:00)",
                value=bool(dataset.config_flags.get("residential_start_restriction", True)),
                help="config.yml: constraints.residential_start_restriction",
            )
            wi_rel = st.checkbox(
                "Relief-Only Day/Night Transition",
                value=bool(dataset.config_flags.get("relief_only_day_night_transition", True)),
                help="config.yml: constraints.relief_only_day_night_transition",
            )
        with wc2:
            wi_atp = st.checkbox(
                "Assignment Type Priority (Relief > Excess > Demand)",
                value=dataset.constraints.get("Assignment Type Priority", ("1000", "Active"))[1] == "Active",
                help="constraints_df.csv: Assignment Type Priority (Active/Inactive)",
            )
            wi_max_sh = st.checkbox(
                "Activity Head Max Shifts Limit",
                value=dataset.constraints.get("Activity Head Max Shifts", ("", "Active"))[1] == "Active",
                help="constraints_df.csv: Activity Head Max Shifts (Active/Inactive)",
            )
        with wc3:
            cur_offsets = dataset.constraints.get("Demand Allowed Start Offsets", ("-60;0;60", "Active"))[0]
            wi_offsets = st.checkbox(
                "Start-Time Offset Flexibility (-60 / 0 / +60 min)",
                value=("-60" in cur_offsets or "60" in cur_offsets),
                help="When unchecked, sets Excess & Demand Allowed Start Offsets to 0 (no shift sliding).",
            )
            cur_strat = str(dataset.config_flags.get("priority_strategy", "none"))
            strat_opts = ["none", "weighted", "lexicographic"]
            wi_strat = st.selectbox(
                "Objective Priority Strategy",
                options=strat_opts,
                index=strat_opts.index(cur_strat) if cur_strat in strat_opts else 0,
                help="config.yml: optimization.priority_strategy",
            )

        # --- Group 2: Numeric Constraint & Objective Parameters ---
        st.markdown("#### 2. Constraint Thresholds & Objective Penalties")
        p1, p2, p3, p4, p5 = st.columns(5)
        with p1:
            cur_ord = _parse_float(dataset.constraints.get("Ordinary Rest Hours", ("11", "Active"))[0], 11.0)
            wi_ord_rest = st.slider("Ordinary Rest (h)", min_value=8.0, max_value=14.0, value=cur_ord, step=0.5)
        with p2:
            cur_trans = _parse_float(dataset.constraints.get("Transition Rest Hours", ("23", "Active"))[0], 23.0)
            wi_trans_rest = st.slider("Transition Rest (h)", min_value=16.0, max_value=26.0, value=cur_trans, step=1.0)
        with p3:
            cur_tier_pen = _parse_int(dataset.constraints.get("Assignment Type Priority", ("1000", "Active"))[0], 1000)
            wi_tier_pen = st.number_input("Assignment Type Tier Penalty", min_value=0, max_value=10000, value=cur_tier_pen, step=100)
        with p4:
            cur_max_chg = _parse_int(dataset.constraints.get("Max Start Changes Per Block", ("1", "Active"))[0], 1)
            wi_max_chg = st.number_input("Max Start Changes / Block", min_value=0, max_value=10, value=cur_max_chg, step=1)
        with p5:
            cur_chg_min = _parse_int(dataset.constraints.get("Max Start Change Minutes", ("60", "Active"))[0], 60)
            wi_chg_min = st.number_input("Max Start Change (min)", min_value=0, max_value=180, value=cur_chg_min, step=15)

        cur_start_date = dataset.constraints.get("Solver Start Date", ("", "Active"))[0]
        sc_col1, sc_col2 = st.columns([2, 1])
        with sc_col1:
            wi_start_date = st.text_input("Solver Start Date (YYYY-MM-DD)", value=cur_start_date)
        with sc_col2:
            wi_time = st.number_input("Solver Time Limit (s)", min_value=5, max_value=180, value=30, step=5, key="wi_time")

        # --- Group 3: Assignment Type & Activity Head Priority Overrides ---
        edited_at_map: dict[str, int] | None = None
        edited_ap_rows: list[dict[str, str]] | None = None
        with st.expander("3. Assignment Type Priority & Activity Head Priorities / Max Shift Limits", expanded=False):
            at_rows = _read_csv_dict_rows(dataset.data_dir / "assignment_type_priority.csv")
            if at_rows:
                st.markdown("**Assignment Type Priority Ranks (Lower = Higher Priority)**")
                at_edited = st.data_editor(at_rows, use_container_width=True, hide_index=True, key="at_prio_editor")
                edited_at_map = {
                    str(r.get("Assignment Type", "")): _parse_int(str(r.get("Priority", 1)), 1)
                    for r in at_edited
                    if r.get("Assignment Type")
                }

            ap_rows = _read_csv_dict_rows(dataset.data_dir / "activity_priority.csv")
            if ap_rows:
                st.markdown("**Activity Head Priorities & Max Resident/FIFO Shift Limits**")
                edited_ap_rows = st.data_editor(ap_rows, use_container_width=True, hide_index=True, key="ap_prio_editor")

        btn_col1, btn_col2 = st.columns([2, 1])
        with btn_col1:
            run_wi_btn = st.button("Solve What-If Scenario (Isolated Temp Run)", type="primary")
        with btn_col2:
            apply_cfg_btn = st.button("Apply to Active Config & Constraints", type="secondary")

        if apply_cfg_btn:
            save_active_config_and_constraints(
                data_dir=dataset.data_dir,
                config_path=config_path,
                residential_start_restriction=wi_res,
                relief_only_day_night_transition=wi_rel,
                priority_strategy=wi_strat,
                assignment_type_priority_enabled=wi_atp,
                assignment_type_tier_penalty=int(wi_tier_pen),
                activity_head_max_shifts_enabled=wi_max_sh,
                ordinary_rest_hours=float(wi_ord_rest),
                transition_rest_hours=float(wi_trans_rest),
                max_start_changes_per_block=int(wi_max_chg),
                max_start_change_minutes=int(wi_chg_min),
                allow_start_time_offsets=wi_offsets,
                solver_start_date=wi_start_date.strip() or None,
                assignment_type_priority_map=edited_at_map,
                activity_priority_overrides=edited_ap_rows,
            )
            st.cache_data.clear()
            st.success(f"Saved rule & constraint settings to `{config_path.name}` and `{dataset.data_dir.name}/`!")

        if run_wi_btn:
            live_wi_box = st.empty()
            wi_lines: list[str] = []

            def _append_wi_line(line: str) -> None:
                wi_lines.append(line)
                live_wi_box.code("\n".join(wi_lines[-50:]))

            sc_ds, sc_logs = run_what_if_scenario(
                base_data_dir=dataset.data_dir,
                base_roster_full=base_roster_input,
                residential_start_restriction=wi_res,
                relief_only_day_night_transition=wi_rel,
                priority_strategy=wi_strat,
                assignment_type_priority_enabled=wi_atp,
                assignment_type_tier_penalty=int(wi_tier_pen),
                activity_head_max_shifts_enabled=wi_max_sh,
                ordinary_rest_hours=float(wi_ord_rest),
                transition_rest_hours=float(wi_trans_rest),
                max_start_changes_per_block=int(wi_max_chg),
                max_start_change_minutes=int(wi_chg_min),
                allow_start_time_offsets=wi_offsets,
                solver_start_date=wi_start_date.strip() or None,
                assignment_type_priority_map=edited_at_map,
                activity_priority_overrides=edited_ap_rows,
                time_limit=int(wi_time),
                log_callback=_append_wi_line,
            )
            if sc_ds is None:
                st.error("Scenario solve failed.")
            else:
                sc_kpis = compute_summary_kpis(sc_ds)
                sc_cost = compute_solver_cost_and_offset_analytics(sc_ds)
                record_run(
                    run_type="What-If",
                    preset=preset,
                    strategy=wi_strat,
                    rule_toggles={
                        "residential_start_restriction": wi_res,
                        "relief_only_day_night_transition": wi_rel,
                        "assignment_type_priority": wi_atp,
                        "assignment_type_tier_penalty": int(wi_tier_pen),
                        "activity_head_max_shifts": wi_max_sh,
                        "allow_start_time_offsets": wi_offsets,
                        "ordinary_rest_hours": float(wi_ord_rest),
                        "transition_rest_hours": float(wi_trans_rest),
                        "max_start_changes_per_block": int(wi_max_chg),
                        "max_start_change_minutes": int(wi_chg_min),
                    },
                    total_demand=sc_kpis.total_demand,
                    assigned_demand=sc_kpis.assigned_demand,
                    unfilled_demand=sc_kpis.unfilled_demand,
                    coverage_pct=sc_kpis.coverage_pct,
                    total_cost=float(sc_cost["total_cost"]),
                )
                st.success("Scenario solved! Before vs After Comparison:")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Assigned Demand", sc_kpis.assigned_demand, delta=sc_kpis.assigned_demand - baseline_kpis.assigned_demand)
                m2.metric("Unfilled Demand", sc_kpis.unfilled_demand, delta=sc_kpis.unfilled_demand - baseline_kpis.unfilled_demand, delta_color="inverse")
                m3.metric("Coverage %", f"{sc_kpis.coverage_pct:.2f}%", delta=f"{sc_kpis.coverage_pct - baseline_kpis.coverage_pct:+.2f}%")
                m4.metric("Gaps Filled", sc_kpis.filled_open_gaps, delta=sc_kpis.filled_open_gaps - baseline_kpis.filled_open_gaps)
                st.plotly_chart(create_slot_diff_heatmap(compute_slot_diff_matrix(dataset, sc_ds)), use_container_width=True)
            st.session_state["last_solver_log"] = sc_logs
            render_solver_log_visualizer(sc_logs, title="What-If Solver Log Visualizer", key_prefix="wi_log")

    with tab_disrupt:
        st.markdown(
            "Simulate an unexpected absence (e.g., crew calling in sick) on active shifts to test whether "
            "the Relief & Excess pool can absorb the disruption."
        )
        active_demand_rows = [
            r for r in dataset.roster_rows
            if r.get("Assignment Type", "").strip() == "Demand"
            and r.get("Is Gap", "").strip() != "True"
            and r.get("Optimised User Id", "").strip()
        ]
        row_labels = {
            f"{r['Assignment ID']} | {r['Start Date']} {r['Shift Start Time']} | {r['Activity Head']} | Crew {r['Optimised User Id']}": r["Assignment ID"]
            for r in active_demand_rows[:500]
        }
        selected_labels_disrupt = st.multiselect(
            "Select Active Shift(s) to Mark Unavailable (Simulated Sick)",
            options=list(row_labels.keys()),
            max_selections=10,
        )
        dis_time = st.number_input("Disruption Solver Time Limit (s)", min_value=5, max_value=120, value=20, step=5, key="dis_time")

        if st.button("Simulate Disruption & Re-Solve", type="primary"):
            target_ids = [row_labels[lbl] for lbl in selected_labels_disrupt]
            if not target_ids:
                st.warning("Select at least one active shift above.")
            else:
                live_dis_box = st.empty()
                dis_lines: list[str] = []

                def _append_dis_line(line: str) -> None:
                    dis_lines.append(line)
                    live_dis_box.code("\n".join(dis_lines[-50:]))

                dis_ds, dis_logs = run_disruption_simulation(
                    base_data_dir=dataset.data_dir,
                    base_roster_full=dataset.cpsat_dir / "roster_full.csv",
                    base_config_path=config_path,
                    disrupted_assignment_ids=target_ids,
                    time_limit=int(dis_time),
                    log_callback=_append_dis_line,
                )
                if dis_ds is None:
                    st.error("Disruption simulation failed.")
                else:
                    dis_kpis = compute_summary_kpis(dis_ds)
                    dis_cost = compute_solver_cost_and_offset_analytics(dis_ds)
                    record_run(
                        run_type="Disruption",
                        preset=preset,
                        strategy=str(dis_ds.config_flags.get("priority_strategy", "none")),
                        rule_toggles={"disrupted_assignment_ids": target_ids},
                        total_demand=dis_kpis.total_demand,
                        assigned_demand=dis_kpis.assigned_demand,
                        unfilled_demand=dis_kpis.unfilled_demand,
                        coverage_pct=dis_kpis.coverage_pct,
                        total_cost=float(dis_cost["total_cost"]),
                    )
                    st.success("Disruption recovery solved!")
                    dm1, dm2, dm3 = st.columns(3)
                    dm1.metric("Coverage %", f"{dis_kpis.coverage_pct:.2f}%", delta=f"{dis_kpis.coverage_pct - baseline_kpis.coverage_pct:+.2f}%")
                    dm2.metric("Unfilled Demand", dis_kpis.unfilled_demand, delta=dis_kpis.unfilled_demand - baseline_kpis.unfilled_demand, delta_color="inverse")
                    dm3.metric("Reassignments Made", len(dis_ds.reassignments))
                    dis_unfilled = build_unfilled_gap_records(dis_ds)
                    if dis_unfilled:
                        st.markdown("#### Resulting Unfilled Gaps After Disruption")
                        st.dataframe(dis_unfilled, use_container_width=True, hide_index=True)
                st.session_state["last_solver_log"] = dis_logs
                render_solver_log_visualizer(dis_logs, title="Disruption Solver Log Visualizer", key_prefix="dis_log")

    with tab_history:
        st.markdown("#### Saved What-If, Disruption & Pipeline Runs (SQLite History)")
        runs = list_runs(limit=100)
        if not runs:
            st.info("No runs recorded yet. Execute a What-If Scenario, Disruption Simulation, or Pipeline run to track KPI trends.")
        else:
            display_rows: list[dict[str, Any]] = [
                {
                    "ID": r["id"],
                    "Timestamp": r["timestamp"],
                    "Type": r["run_type"],
                    "Preset": r["preset"],
                    "Strategy": r["strategy"],
                    "Demand": r["total_demand"],
                    "Assigned": r["assigned_demand"],
                    "Unfilled": r["unfilled_demand"],
                    "Coverage %": r["coverage_pct"],
                    "Total Cost": r["total_cost"],
                    "Rule Toggles": r["rule_toggles_json"],
                }
                for r in runs
            ]
            st.dataframe(display_rows, use_container_width=True, hide_index=True)

            if len(runs) >= 2:
                ordered = list(reversed(runs))
                fig_trend = px.line(
                    ordered,
                    x="id",
                    y="coverage_pct",
                    color="run_type",
                    markers=True,
                    title="Coverage % Trend Across Recorded Runs",
                    labels={"id": "Run ID", "coverage_pct": "Coverage %", "run_type": "Run Type"},
                )
                st.plotly_chart(fig_trend, use_container_width=True)

                base_run = ordered[0]
                sensitivity_rows = [
                    {
                        "Run ID": r["id"],
                        "Type": r["run_type"],
                        "Strategy": r["strategy"],
                        "Coverage %": r["coverage_pct"],
                        "Coverage Delta vs First": round(float(r["coverage_pct"]) - float(base_run["coverage_pct"]), 2),
                        "Cost Delta vs First": round(float(r["total_cost"]) - float(base_run["total_cost"]), 2),
                        "Rule Toggles": r["rule_toggles_json"],
                    }
                    for r in ordered
                ]
                st.markdown("#### Marginal Rule Impact Sensitivity (vs Earliest Recorded Run)")
                st.dataframe(sensitivity_rows, use_container_width=True, hide_index=True)

            if st.button("Clear Run History", type="secondary"):
                clear_runs()
                st.success("Run history cleared.")
