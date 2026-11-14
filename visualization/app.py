#!/usr/bin/env python3
"""Streamlit dashboard for Railway Crew Rostering & Gap-Filling Optimization.

Launch with:
    streamlit run visualization/app.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from visualization.analytics import (  # noqa: E402
    build_executive_insights,
    build_individual_crew_schedule,
    build_reassignment_chains,
    compute_crew_workload_analytics,
    compute_depot_and_travel_analytics,
    compute_resilience_and_pool_analytics,
    compute_run_diff,
    compute_skill_and_currency_radar,
    compute_solver_cost_and_offset_analytics,
)
from visualization.charts import (  # noqa: E402
    create_cost_and_offset_charts,
    create_crew_gantt_chart,
    create_daily_pool_area_chart,
    create_demand_coverage_heatmap,
    create_depot_balance_chart,
    create_depot_head_eligibility_heatmap,
    create_gap_summary_charts,
    create_reassignment_sankey_chart,
    create_rest_margin_histogram,
    create_shift_limit_utilization_chart,
    create_skill_supply_chart,
    create_strategy_comparison_charts,
    create_workload_distribution_chart,
)
from visualization.data_loader import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    DEFAULT_CPSAT_DIR,
    DEFAULT_DATA_DIR,
    DEFAULT_OPTIONS_DIR,
    discover_strategy_datasets,
    load_dashboard_dataset,
)
from visualization.export_utils import (  # noqa: E402
    crew_schedule_to_html,
    datasets_to_excel_bytes,
    rows_to_csv_bytes,
)
from visualization.gap_analysis import (  # noqa: E402
    build_constraint_diagnostics,
    build_unfilled_gap_records,
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
from visualization.scenario_runner import (  # noqa: E402
    run_disruption_simulation,
    run_what_if_scenario,
)


def _select_set(values: list[str]) -> set[str] | None:
    return set(values) if values else None


def main() -> None:
    st.set_page_config(
        page_title="OptiFlux Crew Rostering & Gap-Filling Dashboard",
        layout="wide",
    )
    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] {
            background-color: rgba(248, 250, 252, 0.7);
            border: 1px solid rgba(203, 213, 225, 0.7);
            border-radius: 8px;
            padding: 10px 14px;
        }
        .exec-banner {
            padding: 8px 14px;
            border-radius: 8px;
            background: linear-gradient(90deg, rgba(30,58,138,0.08), rgba(16,185,129,0.06));
            border-left: 4px solid #1e3a8a;
            margin-bottom: 14px;
            font-size: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
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
            "7. Workload, Chains & Depots",
            "8. Skill & Currency Radar",
            "9. What-If & Disruption Simulator",
            "10. Pipeline, Tests & Exports",
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

    # Executive Run Context Banner
    strat_lbl = str(dataset.config_flags.get("priority_strategy", "none"))
    res_lbl = "ON" if dataset.config_flags.get("residential_start_restriction", True) else "OFF"
    rel_lbl = "ON" if dataset.config_flags.get("relief_only_day_night_transition", True) else "OFF"
    atp_lbl = dataset.constraints.get("Assignment Type Priority", ("", "Active"))[1]
    val_lbl = parsed_meta.get("validation_headline") or "N/A"
    st.markdown(
        f"<div class='exec-banner'><strong>Active Dataset:</strong> {preset} &nbsp;|&nbsp; "
        f"<strong>Strategy:</strong> <code>{strat_lbl}</code> &nbsp;|&nbsp; "
        f"<strong>Res Start Restriction:</strong> {res_lbl} &nbsp;|&nbsp; "
        f"<strong>Relief-Only D/N:</strong> {rel_lbl} &nbsp;|&nbsp; "
        f"<strong>Type Priority:</strong> {atp_lbl} &nbsp;|&nbsp; "
        f"<strong>Validation:</strong> {val_lbl}</div>",
        unsafe_allow_html=True,
    )

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

        g1, g2, g3, g4 = st.columns(4)
        g1.metric("Total Leave Gaps", f"{kpis.total_gaps:,}")
        g2.metric("Open Gaps (On/After Solver Start)", f"{kpis.open_gaps_to_fill:,}")
        g3.metric("Open Gaps Filled by CP-SAT", f"{kpis.gaps_filled:,} ({kpis.gap_fill_pct:.1f}%)")
        g4.metric("Locked Gaps (Before Solver Start)", f"{kpis.locked_gaps:,}")

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

        insights = build_executive_insights(dataset)
        if insights:
            st.markdown("#### Executive Bottleneck Digest")
            i_cols = st.columns(min(3, len(insights)))
            for idx, ins in enumerate(insights):
                col = i_cols[idx % len(i_cols)]
                msg = f"**{ins['Title']}**\n\n{ins['Detail']}"
                if ins["Severity"] == "success":
                    col.success(msg)
                elif ins["Severity"] == "warning":
                    col.warning(msg)
                else:
                    col.info(msg)

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

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            color_by = st.selectbox(
                "Color Bars By",
                options=[
                    "Activity Name",
                    "Activity Name Change",
                    "Activity Head",
                    "Changed",
                    "Assignment Type",
                    "Crew Classification",
                    "State",
                ],
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
            only_act_name_changed = st.checkbox(
                "Only Activity Name Changes",
                value=False,
                help="Filter to assignments where Before Activity Name differs from After Activity Name.",
            )
        with c5:
            inc_off = st.checkbox("Include Off & Travel Rows", value=False)
        with c6:
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
        if only_act_name_changed:
            timeline_records = [r for r in timeline_records if r.get("Activity Name Changed") == "Yes"]

        fig_gantt = create_crew_gantt_chart(timeline_records, color_by=color_by, max_crew=max_crew)
        st.plotly_chart(fig_gantt, use_container_width=True)

        before_after_rows = [
            {
                "Assignment ID": r["Assignment ID"],
                "User Id": r["User Id"],
                "Swing": r["Swing"],
                "Activity Name Changed": r["Activity Name Changed"],
                "Before Activity Name": r["Before Activity Name"],
                "After Activity Name": r["After Activity Name"],
                "Before Activity Head": r["Before Activity Head"],
                "After Activity Head": r["After Activity Head"],
                "Before Start Datetime": r["Before Start Datetime"],
                "After Start Datetime": r["After Start Datetime"],
                "Changed": r["Changed"],
                "Reassignment Detail": r["Reassignment Detail"],
            }
            for r in timeline_records
            if r.get("Changed") == "Reassigned / Moved"
        ]
        st.markdown(f"#### Before vs After Reassignment Changes ({len(before_after_rows)} Moved Shift(s))")
        if before_after_rows:
            st.dataframe(before_after_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No reassigned/moved shifts match the current filters.")

        st.markdown("#### Selected Crew Assignment Records")
        st.dataframe(timeline_records, use_container_width=True, hide_index=True)

        st.markdown("#### Individual Crew Journey & Printable Schedule")
        crew_options = sorted(dataset.crew_by_id.keys()) or all_users
        if crew_options:
            sel_individual = st.selectbox("Select Crew Member for Full Schedule", options=crew_options)
            indiv_schedule = build_individual_crew_schedule(dataset, sel_individual)
            crew_meta = dataset.crew_by_id.get(sel_individual, {})
            m1, m2, m3 = st.columns(3)
            m1.metric("Classification", crew_meta.get("Classification", "Unknown"))
            m2.metric("Home Depot", crew_meta.get("Home Depot", "Unknown"))
            m3.metric("Total Timeline Entries", len(indiv_schedule))
            st.dataframe(indiv_schedule, use_container_width=True, hide_index=True)
            dl1, dl2 = st.columns(2)
            with dl1:
                st.download_button(
                    f"Download {sel_individual} Schedule (CSV)",
                    data=rows_to_csv_bytes(indiv_schedule),
                    file_name=f"schedule_{sel_individual}.csv",
                    mime="text/csv",
                )
            with dl2:
                st.download_button(
                    f"Download {sel_individual} Printable Roster (HTML)",
                    data=crew_schedule_to_html(sel_individual, crew_meta, indiv_schedule),
                    file_name=f"schedule_{sel_individual}.html",
                    mime="text/html",
                )

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

        st.markdown("#### 1. Active Constraint Switches & Rule Parameters")
        st.dataframe(diag["constraint_overview"], use_container_width=True, hide_index=True)

        # Improvement 4: Visual Per-Swing Shift-Limit Utilization Chart
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

            if len(available_labels) >= 2:
                st.markdown("#### Side-by-Side Run Diff Viewer (Exact Shifted Assignments)")
                dc1, dc2 = st.columns(2)
                with dc1:
                    run_a = st.selectbox("Baseline Run (A)", options=available_labels, index=0, key="diff_a")
                with dc2:
                    run_b = st.selectbox("Comparison Run (B)", options=available_labels, index=min(1, len(available_labels) - 1), key="diff_b")
                if run_a != run_b:
                    diffs = compute_run_diff(discovered[run_a], discovered[run_b])
                    st.info(f"Found **{len(diffs)}** assignment difference(s) between **{run_a}** and **{run_b}**.")
                    if diffs:
                        st.dataframe(diffs, use_container_width=True, hide_index=True)
                else:
                    st.caption("Select two different runs to compare assignment-level differences.")

    # =========================================================================
    # SECTION 7: WORKLOAD, REASSIGNMENT CHAINS & DEPOT TRACKER
    # =========================================================================
    elif section == "7. Workload, Chains & Depots":
        st.subheader("Crew Fairness, Reassignment Chains, Rest Margins & Depot Balance")
        tab_work, tab_chains, tab_depots, tab_resilience, tab_cost = st.tabs([
            "Crew Fairness & Fatigue",
            "Reassignment Move Tracer",
            "Depot Balance & Travel",
            "Rest Margins & Daily Pool",
            "Cost & Offset Flexibility (F1/F3)",
        ])

        with tab_work:
            workload = compute_crew_workload_analytics(dataset)
            ws = workload["summary"]
            w1, w2, w3, w4, w5 = st.columns(5)
            w1.metric("Total Crew", ws["total_crew"])
            w2.metric("Avg Shifts / Crew", ws["avg_shifts_per_crew"], delta=f"Min {ws['min_shifts_per_crew']} / Max {ws['max_shifts_per_crew']}")
            w3.metric("Day vs Night Shifts", f"{ws['total_day_shifts']} / {ws['total_night_shifts']}")
            w4.metric("Relief Standby Converted", f"{ws['relief_standby_converted']} / {ws['relief_standby_total']}")
            w5.metric("Crew at Swing Cap", ws["fatigue_alerts"])

            top_n = st.slider("Top Crew Displayed in Chart", min_value=10, max_value=100, value=30, step=5)
            st.plotly_chart(create_workload_distribution_chart(workload["crew_rows"], top_n=top_n), use_container_width=True)

            only_fatigue = st.checkbox("Show Only Crew Reaching Swing Shift Cap (6 Res / 14 FIFO)", value=False)
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
            res_data = compute_resilience_and_pool_analytics(dataset)
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
            if parsed_meta["stages"]:
                st.markdown("#### Solver Stage-by-Stage Convergence")
                st.dataframe(parsed_meta["stages"], use_container_width=True, hide_index=True)

    # =========================================================================
    # SECTION 8: SKILL & CURRENCY RADAR
    # =========================================================================
    elif section == "8. Skill & Currency Radar":
        st.subheader("Certification Supply, Depot Readiness & Currency Expiry Radar")
        radar = compute_skill_and_currency_radar(dataset)

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

    # =========================================================================
    # SECTION 9: WHAT-IF & DISRUPTION SIMULATOR
    # =========================================================================
    elif section == "9. What-If & Disruption Simulator":
        st.subheader("Interactive What-If Scenario Builder & Leave Disruption Simulator")
        tab_whatif, tab_disrupt = st.tabs([
            "What-If Scenario Builder",
            "Leave Impact & Disruption Simulator",
        ])

        baseline_kpis = compute_summary_kpis(dataset)
        base_roster_input = ROOT / "gap_generation" / "output" / "roster_full.csv"
        if not base_roster_input.exists():
            base_roster_input = dataset.cpsat_dir / "roster_full.csv"

        with tab_whatif:
            st.markdown(
                "Tune solver constraints and strategy in an isolated temporary workspace without altering project files, "
                "and compare resulting KPIs against the currently loaded baseline."
            )
            wc1, wc2, wc3 = st.columns(3)
            with wc1:
                wi_res = st.checkbox(
                    "Residential Start Restriction (22:00-02:00)",
                    value=bool(dataset.config_flags.get("residential_start_restriction", True)),
                )
                wi_rel = st.checkbox(
                    "Relief-Only Day/Night Transition",
                    value=bool(dataset.config_flags.get("relief_only_day_night_transition", True)),
                )
            with wc2:
                wi_atp = st.checkbox(
                    "Assignment Type Priority (Relief > Excess > Demand)",
                    value=dataset.constraints.get("Assignment Type Priority", ("", "Active"))[1] == "Active",
                )
                wi_max_sh = st.checkbox(
                    "Activity Head Max Shifts Limit",
                    value=dataset.constraints.get("Activity Head Max Shifts", ("", "Active"))[1] == "Active",
                )
            with wc3:
                cur_strat = str(dataset.config_flags.get("priority_strategy", "none"))
                strat_opts = ["none", "weighted", "lexicographic"]
                wi_strat = st.selectbox(
                    "Priority Strategy",
                    options=strat_opts,
                    index=strat_opts.index(cur_strat) if cur_strat in strat_opts else 0,
                )
                wi_time = st.number_input("Solver Time Limit (s)", min_value=5, max_value=180, value=30, step=5, key="wi_time")

            rc1, rc2 = st.columns(2)
            with rc1:
                cur_ord = float(dataset.constraints.get("Ordinary Rest Hours", ("11", "Active"))[0] or 11)
                wi_ord_rest = st.slider("Ordinary Rest Hours", min_value=8.0, max_value=14.0, value=cur_ord, step=0.5)
            with rc2:
                cur_trans = float(dataset.constraints.get("Transition Rest Hours", ("23", "Active"))[0] or 23)
                wi_trans_rest = st.slider("Transition Rest Hours", min_value=16.0, max_value=26.0, value=cur_trans, step=1.0)

            if st.button("Solve What-If Scenario", type="primary"):
                with st.spinner("Running isolated Option Generation + CP-SAT solve..."):
                    sc_ds, sc_logs = run_what_if_scenario(
                        base_data_dir=dataset.data_dir,
                        base_roster_full=base_roster_input,
                        residential_start_restriction=wi_res,
                        relief_only_day_night_transition=wi_rel,
                        priority_strategy=wi_strat,
                        assignment_type_priority_enabled=wi_atp,
                        activity_head_max_shifts_enabled=wi_max_sh,
                        ordinary_rest_hours=wi_ord_rest,
                        transition_rest_hours=wi_trans_rest,
                        time_limit=int(wi_time),
                    )
                if sc_ds is None:
                    st.error("Scenario solve failed.")
                else:
                    sc_kpis = compute_summary_kpis(sc_ds)
                    st.success("Scenario solved! Before vs After Comparison:")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Assigned Demand", sc_kpis.assigned_demand, delta=sc_kpis.assigned_demand - baseline_kpis.assigned_demand)
                    m2.metric("Unfilled Demand", sc_kpis.unfilled_demand, delta=sc_kpis.unfilled_demand - baseline_kpis.unfilled_demand, delta_color="inverse")
                    m3.metric("Coverage %", f"{sc_kpis.coverage_pct:.2f}%", delta=f"{sc_kpis.coverage_pct - baseline_kpis.coverage_pct:+.2f}%")
                    m4.metric("Gaps Filled", sc_kpis.filled_open_gaps, delta=sc_kpis.filled_open_gaps - baseline_kpis.filled_open_gaps)
                with st.expander("Scenario Solver Logs", expanded=False):
                    st.code(sc_logs)

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
                    with st.spinner("Simulating disruption and running recovery solve..."):
                        dis_ds, dis_logs = run_disruption_simulation(
                            base_data_dir=dataset.data_dir,
                            base_roster_full=dataset.cpsat_dir / "roster_full.csv",
                            base_config_path=config_path,
                            disrupted_assignment_ids=target_ids,
                            time_limit=int(dis_time),
                        )
                    if dis_ds is None:
                        st.error("Disruption simulation failed.")
                    else:
                        dis_kpis = compute_summary_kpis(dis_ds)
                        st.success("Disruption recovery solved!")
                        dm1, dm2, dm3 = st.columns(3)
                        dm1.metric("Coverage %", f"{dis_kpis.coverage_pct:.2f}%", delta=f"{dis_kpis.coverage_pct - baseline_kpis.coverage_pct:+.2f}%")
                        dm2.metric("Unfilled Demand", dis_kpis.unfilled_demand, delta=dis_kpis.unfilled_demand - baseline_kpis.unfilled_demand, delta_color="inverse")
                        dm3.metric("Reassignments Made", len(dis_ds.reassignments))
                        dis_unfilled = build_unfilled_gap_records(dis_ds)
                        if dis_unfilled:
                            st.markdown("#### Resulting Unfilled Gaps After Disruption")
                            st.dataframe(dis_unfilled, use_container_width=True, hide_index=True)
                    with st.expander("Disruption Solver Logs", expanded=False):
                        st.code(dis_logs)

    # =========================================================================
    # SECTION 10: PIPELINE, TESTS & EXPORTS
    # =========================================================================
    elif section == "10. Pipeline, Tests & Exports":
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
                run_data_gen = st.checkbox("Include Step 1 & 2 (Rebuild base data & initial roster)", value=True)
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
                logs_expander = st.expander("Pipeline Execution Logs", expanded=True)
                full_log = []
                all_ok = True

                for idx, (label, cmd) in enumerate(steps):
                    status_box.info(f"Executing: **{label}**...")
                    prog_bar.progress(int((idx / len(steps)) * 100))
                    try:
                        res = subprocess.run(
                            cmd,
                            cwd=ROOT,
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        output_text = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
                        full_log.append(f"=== {label} ===\n{output_text}\n")
                        with logs_expander:
                            st.text(f"--- {label} (Exit Code: {res.returncode}) ---")
                            st.code(output_text if output_text.strip() else "[No output produced]")
                        if res.returncode != 0:
                            st.error(f"Failed at {label} with exit code {res.returncode}")
                            all_ok = False
                            break
                    except Exception as exc:
                        st.error(f"Error launching {label}: {exc}")
                        all_ok = False
                        break

                if all_ok:
                    prog_bar.progress(100)
                    status_box.success("Planner pipeline completed successfully! Outputs refreshed.")
                    st.cache_data.clear()

        with tab_tests:
            st.markdown("### Pytest Suite & Initial Roster Rule Checks")
            c_test1, c_test2 = st.columns(2)
            with c_test1:
                test_target = st.selectbox(
                    "Test Target",
                    options=[
                        "All Tests (pytest -q)",
                        "Dashboard Tests (tests/test_dashboard_visualization.py)",
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
                with st.spinner("Executing test suite..."):
                    res = subprocess.run(
                        cmd,
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                output = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
                if res.returncode == 0:
                    st.success("All checks / tests passed!")
                else:
                    st.error(f"Tests failed with exit code {res.returncode}")
                st.code(output)

        with tab_edge_demo:
            st.markdown("### Edge-Case Multi-Run Generator (`scripts/edge_case_demo.py`)")
            st.markdown(
                "Runs all 7 edge-case solver passes across strategy combinations, tight shift limits, "
                "residential restrictions, and relief transitions."
            )
            if st.button("Run Edge-Case Demo Suite", type="secondary"):
                with st.spinner("Running edge_case_demo.py across all modes..."):
                    res = subprocess.run(
                        [sys.executable, "scripts/edge_case_demo.py"],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                out_txt = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
                if res.returncode == 0:
                    st.success("Edge-case runs completed successfully!")
                    st.cache_data.clear()
                else:
                    st.error(f"Edge-case demo failed with exit code {res.returncode}")
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


if __name__ == "__main__":
    main()
