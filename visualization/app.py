#!/usr/bin/env python3
"""Streamlit dashboard for Railway Crew Rostering & Gap-Filling Optimization.

Launch with:
    streamlit run visualization/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from visualization.charts import (  # noqa: E402
    create_crew_gantt_chart,
    create_demand_coverage_heatmap,
    create_gap_summary_charts,
    create_shift_limit_utilization_chart,
    create_strategy_comparison_charts,
)
from visualization.data_loader import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    DEFAULT_CPSAT_DIR,
    DEFAULT_DATA_DIR,
    DEFAULT_OPTIONS_DIR,
    discover_strategy_datasets,
    load_dashboard_dataset,
)
from visualization.gap_analysis import (  # noqa: E402
    build_constraint_diagnostics,
    build_unfilled_gap_records,
    check_swing_home_depot,
    inspect_seat_candidates,
    parse_summary_and_validation,
    summarize_gaps,
)
from visualization.metrics import (  # noqa: E402
    aggregate_by_activity_head,
    aggregate_by_swing,
    build_crew_timeline_records,
    build_demand_slot_records,
    compare_strategy_datasets,
    compute_summary_kpis,
)


def _select_set(values: list[str]) -> set[str] | None:
    return set(values) if values else None


def main() -> None:
    st.set_page_config(
        page_title="OptiFlux Crew Rostering & Gap-Filling Dashboard",
        layout="wide",
    )
    st.title("OptiFlux Railway Crew Rostering & Gap-Filling Dashboard")

    # ---- Sidebar: Data paths, Refresh, and Navigation ----
    st.sidebar.header("Data Source & Controls")

    preset = st.sidebar.selectbox(
        "Dataset Preset",
        options=[
            "Full v2 Roster (CP-SAT/outputs/roster_full)",
            "Edge-Case Demo: Strategy None",
            "Edge-Case Demo: Strategy Weighted",
            "Edge-Case Demo: Strategy Lexicographic",
            "Edge-Case Demo: Tight Shift Limits (Active)",
            "Edge-Case Demo: Tight Shift Limits (Inactive)",
            "Custom Paths",
        ],
    )

    demo_root = ROOT / "CP-SAT" / "outputs" / "edge_case_demo"
    if preset == "Full v2 Roster (CP-SAT/outputs/roster_full)":
        data_dir = DEFAULT_DATA_DIR
        cpsat_dir = DEFAULT_CPSAT_DIR
        options_dir = DEFAULT_OPTIONS_DIR
        config_path = DEFAULT_CONFIG_PATH
    elif preset == "Edge-Case Demo: Strategy None":
        data_dir = demo_root / "data"
        cpsat_dir = demo_root / "run_1_strategy_none" / "cpsat"
        options_dir = demo_root / "run_1_strategy_none" / "options"
        config_path = demo_root / "run_1_strategy_none" / "config.yml"
    elif preset == "Edge-Case Demo: Strategy Weighted":
        data_dir = demo_root / "data"
        cpsat_dir = demo_root / "run_2_strategy_weighted" / "cpsat"
        options_dir = demo_root / "run_2_strategy_weighted" / "options"
        config_path = demo_root / "run_2_strategy_weighted" / "config.yml"
    elif preset == "Edge-Case Demo: Strategy Lexicographic":
        data_dir = demo_root / "data"
        cpsat_dir = demo_root / "run_3_strategy_lexicographic" / "cpsat"
        options_dir = demo_root / "run_3_strategy_lexicographic" / "options"
        config_path = demo_root / "run_3_strategy_lexicographic" / "config.yml"
    elif preset == "Edge-Case Demo: Tight Shift Limits (Active)":
        data_dir = demo_root / "run_6_shift_limits_tight_on" / "data"
        cpsat_dir = demo_root / "run_6_shift_limits_tight_on" / "cpsat"
        options_dir = demo_root / "run_6_shift_limits_tight_on" / "options"
        config_path = demo_root / "run_6_shift_limits_tight_on" / "config.yml"
    elif preset == "Edge-Case Demo: Tight Shift Limits (Inactive)":
        data_dir = demo_root / "run_7_shift_limits_tight_off" / "data"
        cpsat_dir = demo_root / "run_7_shift_limits_tight_off" / "cpsat"
        options_dir = demo_root / "run_7_shift_limits_tight_off" / "options"
        config_path = demo_root / "run_7_shift_limits_tight_off" / "config.yml"
    else:
        data_dir = Path(st.sidebar.text_input("Data Directory", str(DEFAULT_DATA_DIR)))
        cpsat_dir = Path(st.sidebar.text_input("CP-SAT Output Directory", str(DEFAULT_CPSAT_DIR)))
        options_dir = Path(st.sidebar.text_input("Option Generation Directory", str(DEFAULT_OPTIONS_DIR)))
        config_path = Path(st.sidebar.text_input("Config File Path", str(DEFAULT_CONFIG_PATH)))

    if st.sidebar.button("Refresh Solver Outputs"):
        st.cache_data.clear()

    try:
        dataset = load_dashboard_dataset(
            data_dir=data_dir,
            cpsat_dir=cpsat_dir,
            options_dir=options_dir,
            config_path=config_path,
            name=preset,
        )
    except ValueError as exc:
        st.error(f"Data Validation Error: {exc}")
        return

    if dataset.warnings:
        with st.sidebar.expander(f"Data Warnings ({len(dataset.warnings)})", expanded=False):
            for w in dataset.warnings:
                st.caption(f"• {w}")

    if not dataset.roster_rows:
        st.warning(
            f"No solver roster rows found in `{cpsat_dir / 'roster_full.csv'}`. "
            "Run `python CP-SAT/run_gap_filling.py` first, then click **Refresh Solver Outputs**."
        )
        return

    section = st.sidebar.radio(
        "Navigation",
        options=[
            "1. Overview",
            "2. Demand vs Coverage",
            "3. Crew Assignment",
            "4. Gap Analysis",
            "5. Constraint Diagnostics",
            "6. Strategy Comparison",
        ],
    )

    # Global filter options derived from dataset
    all_slots = build_demand_slot_records(dataset)
    all_heads = sorted({str(s["Activity Head"]) for s in all_slots})
    all_swings = sorted(
        {r.get("Swing", "").strip() for r in dataset.roster_rows if r.get("Swing", "").strip()},
        key=lambda x: (0, int(x)) if x.isdecimal() else (1, x),
    )
    all_dates = sorted({str(s["Date"]) for s in all_slots})
    all_shifts = sorted({str(s["Shift"]) for s in all_slots})
    parsed_meta = parse_summary_and_validation(dataset)

    # =========================================================================
    # SECTION 1: OVERVIEW
    # =========================================================================
    if section == "1. Overview":
        st.subheader("Overall Summary KPIs")
        kpis = compute_summary_kpis(dataset)

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total Crew Demand", f"{kpis.total_demand:,}")
        c2.metric("Assigned Demand Shifts", f"{kpis.assigned_demand:,}")
        c3.metric("Unfilled Demand Shifts", f"{kpis.unfilled_demand:,}")
        c4.metric("Demand Coverage %", f"{kpis.coverage_pct:.2f}%")
        c5.metric(
            "Resident Assignments",
            f"{kpis.resident_demand_assignments:,}",
            help=f"Demand shifts: {kpis.resident_demand_assignments:,} | All work shifts (incl. Excess/Relief): {kpis.resident_work_assignments:,}",
        )
        c6.metric(
            "FIFO Assignments",
            f"{kpis.fifo_demand_assignments:,}",
            help=f"Demand shifts: {kpis.fifo_demand_assignments:,} | All work shifts (incl. Excess/Relief): {kpis.fifo_work_assignments:,}",
        )

        g1, g2, g3, g4, g5 = st.columns(5)
        depot_chk = check_swing_home_depot(dataset)
        g1.metric("Total Leave Gaps", f"{kpis.total_gaps:,}")
        g2.metric("Open Gaps (On/After Solver Start)", f"{kpis.open_gaps_to_fill:,}")
        g3.metric("Open Gaps Filled by CP-SAT", f"{kpis.gaps_filled:,} ({kpis.gap_fill_pct:.1f}%)")
        g4.metric("Locked Gaps (Before Solver Start)", f"{kpis.locked_gaps:,}")
        g5.metric(
            "Swings Starting & Ending at Home Depot",
            f"{depot_chk['passed_swings']:,} / {depot_chk['total_swings']:,} ({depot_chk['pass_pct']:.1f}%)",
            f"{depot_chk['solver_modified_failed_swings']} solver-modified failures",
        )

        # Improvement 5: Solver Objective Stage & Validation Status Banner
        if parsed_meta["stages"] or parsed_meta["validation_headline"]:
            st.markdown("#### Solver Objective Stages & Rule Validation Status")
            b_cols = st.columns(max(1, len(parsed_meta["stages"]) + 1))
            for idx, stg in enumerate(parsed_meta["stages"]):
                b_cols[idx].metric(
                    f"Stage {idx + 1}: {stg['Stage'].title()}",
                    stg["Status"],
                    stg["Details"].replace(stg["Status"], "").strip(" ()"),
                )
            if parsed_meta["validation_headline"]:
                b_cols[-1].metric(
                    "Validation Check",
                    "0 Unexpected Failures" if "0 unexpected failure" in parsed_meta["validation_headline"] else "Check Failures",
                    parsed_meta["validation_headline"],
                )

        st.markdown("---")
        col_left, col_right = st.columns(2)
        head_agg = aggregate_by_activity_head(all_slots)
        swing_agg = aggregate_by_swing(dataset)

        with col_left:
            st.markdown("#### Activity Head-wise Coverage Summary")
            st.dataframe(head_agg, use_container_width=True, hide_index=True)

        with col_right:
            st.markdown("#### Swing-wise Coverage Summary")
            st.dataframe(swing_agg, use_container_width=True, hide_index=True)

        gap_summaries = summarize_gaps(build_unfilled_gap_records(dataset))
        summary_figs = create_gap_summary_charts(gap_summaries, head_agg)
        st.plotly_chart(summary_figs["resident_vs_fifo"], use_container_width=True)

    # =========================================================================
    # SECTION 2: DEMAND VS COVERAGE HEATMAP
    # =========================================================================
    elif section == "2. Demand vs Coverage":
        st.subheader("Demand vs Coverage Heatmap")
        f1, f2, f3, f4, f5 = st.columns(5)
        with f1:
            sel_heads = st.multiselect("Filter by Activity Head", all_heads)
        with f2:
            sel_swings = st.multiselect("Filter by Swing", all_swings)
        with f3:
            sel_crew_types = st.multiselect("Filter by Crew Type", ["Residential", "FIFO"])
        with f4:
            sel_dates = st.multiselect("Filter by Date", all_dates)
        with f5:
            sel_shifts = st.multiselect("Filter by Shift", all_shifts)

        opt_col1, opt_col2 = st.columns([2, 2])
        with opt_col1:
            col_mode = st.radio(
                "Heatmap X-Axis",
                options=["Date", "Shift", "Date_Shift"],
                horizontal=True,
                format_func=lambda x: {"Date": "Date", "Shift": "Shift Start Time", "Date_Shift": "Date + Shift Slot"}[x],
            )
        with opt_col2:
            # Improvement 1: Show Only Leave-Disrupted Slots Toggle
            only_disrupted = st.checkbox(
                "Show Only Leave-Disrupted / Gap Slots (Focus on Recovery)",
                value=False,
                help="Filters out undisturbed baseline shifts so you can inspect only slots that had a leave gap (Green = recovered by solver, Yellow = partially recovered, Red = unfilled).",
            )

        filtered_slots = build_demand_slot_records(
            dataset,
            swing_filter=_select_set(sel_swings),
            head_filter=_select_set(sel_heads),
            crew_type_filter=_select_set(sel_crew_types),
            date_filter=_select_set(sel_dates),
            shift_filter=_select_set(sel_shifts),
            only_disrupted_gaps=only_disrupted,
        )
        filtered_kpis = compute_summary_kpis(
            dataset,
            swing_filter=_select_set(sel_swings),
            head_filter=_select_set(sel_heads),
            crew_type_filter=_select_set(sel_crew_types),
            date_filter=_select_set(sel_dates),
            shift_filter=_select_set(sel_shifts),
            only_disrupted_gaps=only_disrupted,
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Filtered Demand", f"{filtered_kpis.total_demand:,}")
        m2.metric("Filtered Assigned", f"{filtered_kpis.assigned_demand:,}")
        m3.metric("Filtered Gap", f"{filtered_kpis.unfilled_demand:,}")
        m4.metric("Filtered Coverage %", f"{filtered_kpis.coverage_pct:.2f}%")

        fig_heatmap = create_demand_coverage_heatmap(filtered_slots, column_mode=col_mode)
        st.plotly_chart(fig_heatmap, use_container_width=True)

        st.markdown("#### Detailed Slot Coverage Table")
        st.dataframe(filtered_slots, use_container_width=True, hide_index=True)

    # =========================================================================
    # SECTION 3: CREW ASSIGNMENT GANTT CHART
    # =========================================================================
    elif section == "3. Crew Assignment":
        st.subheader("Crew Assignment Gantt Chart (Actual Selected Solver Assignments)")
        all_users = sorted(dataset.crew_by_id.keys())

        f1, f2, f3, f4 = st.columns(4)
        with f1:
            sel_crew_types = st.multiselect("Crew Classification", ["Residential", "FIFO"])
        with f2:
            sel_swings = st.multiselect("Swing", all_swings)
        with f3:
            sel_heads = st.multiselect("Activity Head", all_heads)
        with f4:
            sel_users = st.multiselect("Crew Member (User Id)", all_users)

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            color_by = st.selectbox(
                "Color Bars By",
                options=["Activity Head", "Changed", "Assignment Type", "Crew Classification", "State"],
            )
        with c2:
            max_crew = st.slider("Max Crew Members Displayed", min_value=5, max_value=150, value=35, step=5)
        with c3:
            # Improvement 2: Changed Crew Only Filter
            only_changed = st.checkbox(
                "Show Only Reassigned / Moved Crew",
                value=True,
                help="Filters the timeline to crew members who were moved or reassigned by CP-SAT.",
            )
        with c4:
            inc_off = st.checkbox("Include Off & Travel Rows", value=False)
        with c5:
            inc_leave = st.checkbox("Show Unassigned / On-Leave Periods", value=True)

        timeline_records = build_crew_timeline_records(
            dataset,
            swing_filter=_select_set(sel_swings),
            crew_filter=_select_set(sel_users),
            head_filter=_select_set(sel_heads),
            crew_type_filter=_select_set(sel_crew_types),
            include_off_and_travel=inc_off,
            include_unassigned_leave=inc_leave,
            only_changed_crew=only_changed,
        )
        fig_gantt = create_crew_gantt_chart(timeline_records, color_by=color_by, max_crew=max_crew)
        st.plotly_chart(fig_gantt, use_container_width=True)

        st.markdown("#### Selected Crew Assignment Records")
        st.dataframe(timeline_records, use_container_width=True, hide_index=True)

    # =========================================================================
    # SECTION 4: GAP-FILLING ANALYSIS
    # =========================================================================
    elif section == "4. Gap Analysis":
        st.subheader("Gap-Filling Analysis (Unfilled Demand)")
        f1, f2 = st.columns(2)
        with f1:
            sel_head = st.multiselect("Inspect Activity Head(s)", all_heads)
        with f2:
            sel_swing = st.multiselect("Filter by Swing", all_swings)

        unfilled_records = build_unfilled_gap_records(
            dataset,
            head_filter=_select_set(sel_head),
            swing_filter=_select_set(sel_swing),
        )
        gap_summaries = summarize_gaps(unfilled_records)
        head_agg = aggregate_by_activity_head(
            build_demand_slot_records(
                dataset,
                head_filter=_select_set(sel_head),
                swing_filter=_select_set(sel_swing),
            )
        )
        charts = create_gap_summary_charts(gap_summaries, head_agg)

        r1c1, r1c2 = st.columns(2)
        with r1c1:
            st.plotly_chart(charts["by_head"], use_container_width=True)
        with r1c2:
            st.plotly_chart(charts["by_priority"], use_container_width=True)

        r2c1, r2c2 = st.columns(2)
        with r2c1:
            st.plotly_chart(charts["by_shift"], use_container_width=True)
        with r2c2:
            st.plotly_chart(charts["resident_vs_fifo"], use_container_width=True)

        st.markdown("#### Unfilled Demand Slots Table")
        st.dataframe(unfilled_records, use_container_width=True, hide_index=True)

        # Improvement 3: Factual "Where Did the Candidates Go?" Seat Inspector
        if unfilled_records:
            st.markdown("---")
            st.markdown("#### Inspect Unfilled Slot: Where Did the Layer-1 Candidates Go?")
            seat_options = [
                f"{r['Seat Key']} | {r['Activity Head']} ({r['Date']} {r['Shift']}) - Gap: {r['Remaining Gap']} [{r['Diagnostic Category']}]"
                for r in unfilled_records
            ]
            chosen_label = st.selectbox("Select an Unfilled Demand Slot to Trace Candidates & Rejections", seat_options)
            chosen_seat_key = chosen_label.split(" | ", 1)[0]
            trace = inspect_seat_candidates(dataset, chosen_seat_key)

            tc1, tc2 = st.columns(2)
            with tc1:
                st.markdown(f"**Layer-1 Candidate Options (`gap_options.csv`) for `{chosen_seat_key}` ({len(trace['candidates'])}):**")
                if trace["candidates"]:
                    st.dataframe(trace["candidates"], use_container_width=True, hide_index=True)
                else:
                    st.caption("No legal candidate options existed in `gap_options.csv` for this seat.")
            with tc2:
                st.markdown(f"**Layer-1 Rejection Breakdown (`rejections.csv`) for `{chosen_seat_key}`:**")
                if trace["rejections"]:
                    st.dataframe(trace["rejections"], use_container_width=True, hide_index=True)
                else:
                    st.caption("No Layer-1 rejection entries recorded for this seat (or locked before Solver Start Date).")

        if dataset.reassignments:
            with st.expander(f"View All Filled Reassignments ({len(dataset.reassignments)} fills)", expanded=False):
                st.dataframe(dataset.reassignments, use_container_width=True, hide_index=True)

    # =========================================================================
    # SECTION 5: CONSTRAINT & DIAGNOSTIC ANALYSIS
    # =========================================================================
    elif section == "5. Constraint Diagnostics":
        st.subheader("Constraint & Diagnostic Analysis")
        st.info(
            "**Evidence Policy:** Diagnostics below report only explicit evidence exported by the pipeline "
            "(`Is_locked_gap` in `roster_full.csv`, candidate counts in `gap_options.csv`, and Layer-1 rejection "
            "counts in `rejections.csv`). When candidates existed in Layer 1 but were not chosen by CP-SAT, "
            "the dashboard traces what those candidates actually did in `roster_full.csv` without guessing a solver conflict cause."
        )

        diag = build_constraint_diagnostics(dataset)
        depot_chk = diag["home_depot_check"]

        st.markdown("#### 1. Home Depot Swing Start & End Check (Every Crew Swing)")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Total Crew Swings Checked", f"{depot_chk['total_swings']:,}")
        d2.metric(
            "Swings Starting & Ending at Home Depot",
            f"{depot_chk['passed_swings']:,} ({depot_chk['pass_pct']:.2f}%)",
        )
        d3.metric(
            "Failed Swings (Start or End != Home Depot)",
            f"{depot_chk['failed_swings']:,}",
            help=f"Start mismatch: {depot_chk['failed_start_count']} | End mismatch: {depot_chk['failed_end_count']}",
        )
        d4.metric(
            "Solver-Modified Failed Swings",
            f"{depot_chk['solver_modified_failed_swings']:,}",
            help="Number of swings modified by CP-SAT that failed the Home Depot start/end check.",
        )

        depot_filter = st.radio(
            "Filter Home Depot Swing Check Table",
            options=["All Swings", "FAIL Only", "Modified by Solver Only"],
            horizontal=True,
        )
        depot_rows = depot_chk["swing_rows"]
        if depot_filter == "FAIL Only":
            depot_rows = [r for r in depot_rows if r["Status"] == "FAIL"]
        elif depot_filter == "Modified by Solver Only":
            depot_rows = [r for r in depot_rows if r["Swing Context"] == "Modified by Solver"]
        st.dataframe(depot_rows, use_container_width=True, hide_index=True)

        st.markdown("#### 2. Active Constraint Switches & Assignment Type Priority (`Relief > Excess > Demand`)")
        ac1, ac2 = st.columns([2, 1])
        with ac1:
            st.dataframe(diag["constraint_overview"], use_container_width=True, hide_index=True)
        with ac2:
            st.dataframe(diag["assignment_type_priority_table"], use_container_width=True, hide_index=True)

        # Improvement 4: Visual Per-Swing Shift-Limit Utilization Chart
        st.markdown("#### 3. Per-Activity-Head Max Resident / FIFO Shifts vs Observed Utilization")
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
                st.dataframe(diag["rejection_summary"], use_container_width=True, hide_index=True)
            else:
                st.caption("`rejections.csv` not available in the selected options directory.")

        # Improvement 5: Interactive 44-Rule Validation Check Explorer
        if parsed_meta["validation_rules"]:
            st.markdown(f"#### 5. Roster Validation Rule Checks ({parsed_meta['validation_headline']})")
            res_filter = st.multiselect(
                "Filter Rule Checks by Result",
                options=["PASS", "fails after leave too", "FAIL"],
                default=["PASS", "fails after leave too", "FAIL"],
            )
            filtered_rules = [
                r for r in parsed_meta["validation_rules"] if r["Result"] in set(res_filter)
            ]
            st.dataframe(filtered_rules, use_container_width=True, hide_index=True)

        with st.expander("View Per-Crew Per-Swing Activity-Head Shift Counts", expanded=False):
            only_at_cap = st.checkbox("Show Only Swings Reaching Configured Shift Limit", value=False)
            util_rows = diag["limit_utilization_rows"]
            if only_at_cap:
                util_rows = [r for r in util_rows if r.get("At / Above Limit")]
            st.dataframe(util_rows, use_container_width=True, hide_index=True)

    # =========================================================================
    # SECTION 6: OPTIMIZATION STRATEGY COMPARISON
    # =========================================================================
    elif section == "6. Strategy Comparison":
        st.subheader("Optimization Strategy Comparison (None vs Weighted vs Lexicographic)")
        discovered = discover_strategy_datasets(ROOT)

        if len(discovered) < 2:
            st.warning(
                "Fewer than two strategy output datasets were found automatically. "
                "You can generate comparable runs with `python scripts/edge_case_demo.py` or by running "
                "`CP-SAT/run_gap_filling.py` with `priority_strategy` set to `none`, `weighted`, and `lexicographic`."
            )

        available_labels = list(discovered.keys())
        default_sel = [
            lbl for lbl in available_labels if "Demo" in lbl
        ] or available_labels
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


if __name__ == "__main__":
    main()
