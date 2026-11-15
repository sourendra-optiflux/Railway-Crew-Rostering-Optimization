"""Constraint diagnostics, strategy comparison, workload/chains/depots, and skill radar views."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import streamlit as st

from visualization.analytics import (
    build_reassignment_chains,
    compute_depot_and_travel_analytics,
    compute_run_diff,
    compute_slot_diff_matrix,
    compute_solver_cost_and_offset_analytics,
)
from visualization.charts import (
    create_cost_and_offset_charts,
    create_daily_pool_area_chart,
    create_depot_balance_chart,
    create_depot_head_eligibility_heatmap,
    create_priority_adherence_waterfall_chart,
    create_reassignment_sankey_chart,
    create_rejection_pareto_chart,
    create_rest_margin_histogram,
    create_shift_limit_utilization_chart,
    create_skill_supply_chart,
    create_slot_diff_heatmap,
    create_strategy_comparison_charts,
    create_workload_distribution_chart,
)
from visualization.data_loader import ROOT, DashboardDataset, discover_strategy_datasets
from visualization.export_utils import rows_to_csv_bytes
from visualization.gap_analysis import build_constraint_diagnostics
from visualization.kpi_engine import aggregate_by_priority_tier, compute_extended_kpis
from visualization.metrics import compare_strategy_datasets
from visualization.validators import run_post_solve_qa_suite


def render_priority_and_telemetry(
    dataset: DashboardDataset,
    all_slots: list[dict[str, object]],
    parsed_meta: dict[str, object],
    base_root: Path = ROOT,
) -> None:
    """Render Page 5: Priority Hierarchy, Multi-Stage Telemetry & Cross-Run Comparison."""
    st.subheader("Priority Adherence, Multi-Stage Objectives & Solver Telemetry")

    st.markdown("#### Conceptual Separation of Priority & Crew Dimensions")
    ext = compute_extended_kpis(dataset)
    d1, d2, d3 = st.columns(3)
    with d1:
        st.info(
            "**1. Activity Head Priority (Task Criticality)**\n\n"
            f"Configured in `activity_priority.csv` (`1 = Highest` .. `{max(dataset.priority_by_head.values(), default=14)}`). "
            f"Active `priority_strategy`: **`{dataset.config_flags.get('priority_strategy', 'none')}`**."
        )
    with d2:
        atp_status = dataset.constraints.get("Assignment Type Priority", ("Demand > Relief > Excess", "Active"))[1]
        st.info(
            "**2. Assignment Type Priority (Source Tier)**\n\n"
            f"Status: **`{atp_status}`** (`constraints_df.csv`). "
            f"Selected Work Shifts — Demand: **{ext['demand_assignments']:,}**, "
            f"Relief: **{ext['relief_assignments']:,}**, Excess: **{ext['excess_assignments']:,}**."
        )
    with d3:
        st.info(
            "**3. Crew Classification (Operational Rules)**\n\n"
            "Separates **Residential** vs **FIFO** crew rules (Residential night-start restriction & per-swing "
            f"Max Resident / FIFO Shifts). Demand filled — Resident: **{ext['resident_demand_assignments']:,}**, "
            f"FIFO: **{ext['fifo_demand_assignments']:,}**."
        )

    prio_rows = aggregate_by_priority_tier(all_slots)
    st.plotly_chart(
        create_priority_adherence_waterfall_chart(prio_rows),
        use_container_width=True,
        key="prio_waterfall_chart",
    )
    st.markdown("#### Priority Tier Coverage & Cumulative Adherence Table")
    st.dataframe(
        prio_rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Coverage %": st.column_config.ProgressColumn(
                "Coverage %", format="%.2f%%", min_value=0, max_value=100
            ),
            "Cumulative Coverage %": st.column_config.ProgressColumn(
                "Cumulative Coverage %", format="%.2f%%", min_value=0, max_value=100
            ),
        },
    )

    stages = parsed_meta.get("stages", [])
    summary_items = parsed_meta.get("summary_items", {})
    st.markdown("#### Solver Stage Telemetry (`summary.md`)")
    if stages:
        st.dataframe(stages, use_container_width=True, hide_index=True)
    else:
        st.caption("No explicit stage breakdown rows found in `summary.md`.")
    if summary_items:
        with st.expander("View All Raw Solver Telemetry Items (`summary.md`)", expanded=False):
            st.dataframe(
                [{"Metric": k, "Value": v} for k, v in summary_items.items()],
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("---")
    render_strategy_comparison(base_root)


def render_constraint_diagnostics(
    dataset: DashboardDataset,
    parsed_meta: dict[str, object],
) -> None:
    """Render Page 6: Automated Post-Solve QA Engine & Constraint Diagnostics."""
    st.subheader("Automated Post-Solve QA Scorecard & Constraint Diagnostics")
    qa = run_post_solve_qa_suite(dataset)

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Total Validation Checks", f"{qa['total_checks']}")
    q2.metric("Passed Checks", f"{qa['passed']}")
    q3.metric("Failed (Critical)", f"{qa['failed_critical']}")
    q4.metric("Warnings", f"{qa['warnings']}")

    st.markdown("#### Post-Solve QA Check Suite")
    st.dataframe(qa["checks"], use_container_width=True, hide_index=True)

    if qa["offending_rows"]:
        with st.expander(f"Inspect QA Diagnostic Log Rows ({len(qa['offending_rows'])} item(s))", expanded=False):
            st.dataframe(qa["offending_rows"], use_container_width=True, hide_index=True)
            st.download_button(
                "Download QA Diagnostic Log (CSV)",
                data=rows_to_csv_bytes(qa["offending_rows"]),
                file_name="qa_diagnostic_log.csv",
                mime="text/csv",
            )

    st.info(
        "**Evidence Policy:** Diagnostics below report only explicit evidence exported by the pipeline "
        "(`Is_locked_gap` in `roster_full.csv`, candidate counts in `gap_options.csv`, and Layer-1 rejection "
        "counts in `rejections.csv`). When candidates existed in Layer 1 but were not chosen by CP-SAT, "
        "the dashboard traces what those candidates actually did in `roster_full.csv` without guessing a solver conflict cause."
    )

    diag = build_constraint_diagnostics(dataset)

    st.markdown("#### 1. Active Constraint Switches & Rule Parameters")
    st.dataframe(diag["constraint_overview"], use_container_width=True, hide_index=True)

    st.markdown("#### 2. Per-Activity-Head Max Resident / FIFO Shifts vs Observed Utilization")
    fig_limits = create_shift_limit_utilization_chart(diag["head_limits_table"])
    st.plotly_chart(fig_limits, use_container_width=True)
    st.dataframe(diag["head_limits_table"], use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 3. Crew Swing Availability (`swings.csv`)")
        if diag["swing_availability"]:
            st.dataframe(diag["swing_availability"], use_container_width=True, hide_index=True)
        else:
            st.caption("`swings.csv` not available in the selected options directory.")
    with c2:
        st.markdown("#### 4. Layer-1 Option Rejection Counts (`rejections.csv`)")
        if diag["rejection_summary"]:
            st.plotly_chart(create_rejection_pareto_chart(diag["rejection_summary"]), use_container_width=True)
            st.dataframe(diag["rejection_summary"], use_container_width=True, hide_index=True)
        else:
            st.caption("`rejections.csv` not available in the selected options directory.")

    if dataset.baseline_checks_markdown:
        with st.expander("Baseline Input Roster Checks (`roster_checks.md`) vs Post-Solver Validation", expanded=False):
            st.markdown(dataset.baseline_checks_markdown[:4000])

    validation_rules = parsed_meta.get("validation_rules", [])
    val_headline = str(parsed_meta.get("validation_headline", ""))
    if validation_rules:
        st.markdown(f"#### 5. Roster Validation Rule Checks ({val_headline})")
        res_filter = st.multiselect(
            "Filter Rule Checks by Result",
            options=["PASS", "fails after leave too", "FAIL"],
            default=["PASS", "fails after leave too", "FAIL"],
        )
        filtered_rules = [r for r in validation_rules if r["Result"] in set(res_filter)]
        st.dataframe(filtered_rules, use_container_width=True, hide_index=True)

    with st.expander("View Per-Crew Per-Swing Activity-Head Shift Counts", expanded=False):
        only_at_cap = st.checkbox("Show Only Swings Reaching Configured Shift Limit", value=False)
        util_rows = diag["limit_utilization_rows"]
        if only_at_cap:
            util_rows = [r for r in util_rows if r.get("At / Above Limit")]
        st.dataframe(util_rows, use_container_width=True, hide_index=True)


def render_strategy_comparison(base_root: Path = ROOT) -> None:
    """Render Section 6: Optimization Strategy Comparison."""
    st.subheader("Optimization Strategy Comparison (None vs Weighted vs Lexicographic)")
    discovered = discover_strategy_datasets(base_root)

    if len(discovered) < 2:
        st.warning(
            "Fewer than two strategy output datasets were found automatically. "
            "You can generate comparable runs with `python scripts/edge_case_demo.py` or by running "
            "`CP-SAT/run_gap_filling.py` with `priority_strategy` set to `none`, `weighted`, and `lexicographic`."
        )

    available_labels = list(discovered.keys())
    default_sel = [lbl for lbl in available_labels if "Demo" in lbl] or available_labels
    selected_labels = st.multiselect(
        "Select Strategy Runs to Compare",
        options=available_labels,
        default=default_sel,
    )

    selected_datasets = {lbl: discovered[lbl] for lbl in selected_labels if lbl in discovered}
    if selected_datasets:
        comp = compare_strategy_datasets(selected_datasets)
        st.markdown("#### Overall Strategy KPI Comparison")
        st.dataframe(comp["overall"], use_container_width=True, hide_index=True)

        comp_charts = create_strategy_comparison_charts(comp)
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(comp_charts["by_head"], use_container_width=True)
        with c2:
            st.plotly_chart(comp_charts["by_priority"], use_container_width=True)

        st.markdown("#### Priority-wise Coverage Breakdown")
        st.dataframe(comp["by_priority"], use_container_width=True, hide_index=True)

        st.markdown("#### Activity Head-wise Coverage Breakdown")
        st.dataframe(comp["by_head"], use_container_width=True, hide_index=True)

        if len(available_labels) >= 2:
            st.markdown("#### Side-by-Side Run Diff Viewer (Exact Shifted Assignments)")
            dc1, dc2 = st.columns(2)
            with dc1:
                run_a = st.selectbox("Baseline Run (A)", options=available_labels, index=0, key="diff_a")
            with dc2:
                run_b = st.selectbox(
                    "Comparison Run (B)",
                    options=available_labels,
                    index=min(1, len(available_labels) - 1),
                    key="diff_b",
                )
            if run_a != run_b:
                slot_diffs = compute_slot_diff_matrix(discovered[run_a], discovered[run_b])
                st.plotly_chart(create_slot_diff_heatmap(slot_diffs), use_container_width=True)
                diffs = compute_run_diff(discovered[run_a], discovered[run_b])
                st.info(f"Found **{len(diffs)}** assignment difference(s) between **{run_a}** and **{run_b}**.")
                if diffs:
                    st.dataframe(diffs, use_container_width=True, hide_index=True)
            else:
                st.caption("Select two different runs to compare assignment-level differences.")


def render_workload_chains_depots(
    dataset: DashboardDataset,
    parsed_meta: dict[str, object],
    *,
    workload_fn: Callable[[DashboardDataset], dict[str, object]],
    resilience_fn: Callable[[DashboardDataset], dict[str, object]],
) -> None:
    """Render Section 7: Crew Fairness, Reassignment Chains, Rest Margins & Depot Balance."""
    st.subheader("Crew Fairness, Reassignment Chains, Rest Margins & Depot Balance")
    tab_work, tab_chains, tab_depots, tab_resilience, tab_cost = st.tabs([
        "Crew Fairness & Fatigue",
        "Reassignment Move Tracer",
        "Depot Balance & Travel",
        "Rest Margins & Daily Pool",
        "Cost & Offset Flexibility (F1/F3)",
    ])

    with tab_work:
        workload = workload_fn(dataset)
        ws = workload["summary"]
        w1, w2, w3, w4, w5 = st.columns(5)
        w1.metric("Total Crew", ws["total_crew"])
        w2.metric("Avg Shifts / Crew", ws["avg_shifts_per_crew"], delta=f"Min {ws['min_shifts_per_crew']} / Max {ws['max_shifts_per_crew']}")
        w3.metric("Day vs Night Shifts", f"{ws['total_day_shifts']} / {ws['total_night_shifts']}")
        w4.metric("Relief Standby Converted", f"{ws['relief_standby_converted']} / {ws['relief_standby_total']}")
        w5.metric("Crew at Swing Cap", ws["fatigue_alerts"])

        top_n = st.slider("Top Crew Displayed in Chart", min_value=10, max_value=100, value=30, step=5)
        st.plotly_chart(create_workload_distribution_chart(workload["crew_rows"], top_n=top_n), use_container_width=True)

        only_fatigue = st.checkbox("Show Only Crew Reaching Swing Shift Cap", value=False)
        w_rows = workload["crew_rows"]
        if only_fatigue:
            w_rows = [r for r in w_rows if r.get("At Swing Cap")]
        st.dataframe(w_rows, use_container_width=True, hide_index=True)

    with tab_chains:
        chains_data = build_reassignment_chains(dataset)
        cs = chains_data["summary"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Reassignment Moves", cs["total_moves"])
        c2.metric("Direct Gap Fills", cs["direct_gap_fills"])
        c3.metric("Multi-Hop Chain Moves", cs["chain_moves"], delta=f"Max Level {cs['max_chain_level']}")
        c4.metric("Total Move Cost", cs["total_cost"])

        st.plotly_chart(create_reassignment_sankey_chart(chains_data["sankey_links"]), use_container_width=True)
        st.markdown("#### Reconstructed Gap-Fill Chains")
        st.dataframe(chains_data["chains"], use_container_width=True, hide_index=True)
        with st.expander("All Individual Reassignment Moves", expanded=False):
            st.dataframe(chains_data["moves"], use_container_width=True, hide_index=True)

    with tab_depots:
        depot_data = compute_depot_and_travel_analytics(dataset)
        ds_sum = depot_data["summary"]
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Active Depots", ds_sum["depots_count"])
        d2.metric("Travel In Legs", ds_sum["travel_in_legs"])
        d3.metric("Travel Out Legs", ds_sum["travel_out_legs"])
        d4.metric("Total Travel Hours", f"{ds_sum['total_travel_hours']} h")

        st.plotly_chart(create_depot_balance_chart(depot_data["depot_rows"]), use_container_width=True)
        st.markdown("#### Depot Inflow vs Outflow Table")
        st.dataframe(depot_data["depot_rows"], use_container_width=True, hide_index=True)
        st.markdown("#### Per-Crew FIFO Travel / Deadheading Summary")
        st.dataframe(depot_data["travel_rows"], use_container_width=True, hide_index=True)

    with tab_resilience:
        res_data = resilience_fn(dataset)
        st.metric("Tight Rest Transitions (11h - 12.5h)", res_data["tight_rest_count"])
        st.plotly_chart(create_rest_margin_histogram(res_data["rest_buckets"]), use_container_width=True)
        st.plotly_chart(create_daily_pool_area_chart(res_data["daily_pool_rows"]), use_container_width=True)
        with st.expander("Tightest Intra-Swing Rest Transitions Table", expanded=False):
            st.dataframe(res_data["rest_margins"][:200], use_container_width=True, hide_index=True)

    with tab_cost:
        cost_data = compute_solver_cost_and_offset_analytics(dataset)
        c1, c2 = st.columns(2)
        c1.metric("Total Reassignment Cost", cost_data["total_cost"])
        c2.metric("Total Gap-Fill Moves", cost_data["total_moves"])
        cost_figs = create_cost_and_offset_charts(cost_data)
        cc1, cc2 = st.columns(2)
        with cc1:
            st.plotly_chart(cost_figs["cost_by_source"], use_container_width=True)
        with cc2:
            st.plotly_chart(cost_figs["offsets"], use_container_width=True)
        st.markdown("#### Cost Breakdown by Source Type")
        st.dataframe(cost_data["source_rows"], use_container_width=True, hide_index=True)
        stages = parsed_meta.get("stages", [])
        if stages:
            st.markdown("#### Solver Stage-by-Stage Convergence")
            st.dataframe(stages, use_container_width=True, hide_index=True)


def render_skill_currency_radar(
    dataset: DashboardDataset,
    *,
    radar_fn: Callable[[DashboardDataset], dict[str, object]],
) -> None:
    """Render Section 8: Skill & Currency Radar."""
    st.subheader("Certification Supply, Depot Readiness & Currency Expiry Radar")
    radar = radar_fn(dataset)

    st.plotly_chart(create_skill_supply_chart(radar["supply_rows"]), use_container_width=True)
    st.markdown("#### Activity Head Skill Supply vs Daily Demand")
    st.dataframe(radar["supply_rows"], use_container_width=True, hide_index=True)

    st.plotly_chart(create_depot_head_eligibility_heatmap(radar["matrix_rows"]), use_container_width=True)

    st.markdown("#### Currency Expiry Watchlist (Within Planning Horizon)")
    if radar["currency_watchlist"]:
        st.warning(f"{len(radar['currency_watchlist'])} crew-activity currency record(s) expire before or during the horizon.")
        st.dataframe(radar["currency_watchlist"], use_container_width=True, hide_index=True)
    else:
        st.success("All tracked crew currency records remain valid throughout the planning horizon.")
