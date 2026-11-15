"""Overview, Demand Coverage, Crew Assignment, and Gap Analysis views."""

from __future__ import annotations

import streamlit as st

from visualization.analytics import (
    build_executive_insights,
    build_individual_crew_schedule,
    compute_lifecycle_waterfall,
    compute_option_density_vs_fill,
)
from visualization.charts import (
    create_assignment_type_donut_charts,
    create_crew_gantt_chart,
    create_demand_coverage_heatmap,
    create_depot_coverage_chart,
    create_fill_rate_gauge_chart,
    create_gap_summary_charts,
    create_head_depot_coverage_heatmap,
    create_individual_crew_calendar_chart,
    create_lifecycle_waterfall_chart,
    create_option_density_scatter_chart,
    create_unfilled_treemap_chart,
)
from visualization.data_loader import DashboardDataset
from visualization.export_utils import crew_schedule_to_html, rows_to_csv_bytes
from visualization.gap_analysis import (
    build_unfilled_gap_records,
    inspect_seat_candidates,
    summarize_gaps,
)
from visualization.kpi_engine import (
    aggregate_by_depot,
    aggregate_by_depot_and_head,
    compute_cross_run_deltas,
    compute_extended_kpis,
    generate_operational_brief,
)
from visualization.metrics import (
    aggregate_by_activity_head,
    aggregate_by_swing,
    build_crew_timeline_records,
    build_demand_slot_records,
    compute_summary_kpis,
)


def _select_set(values: list[str]) -> set[str] | None:
    return set(values) if values else None


def render_overview(
    dataset: DashboardDataset,
    all_slots: list[dict[str, object]],
    parsed_meta: dict[str, object],
    baseline_dataset: DashboardDataset | None = None,
) -> None:
    """Render Page 1: Executive Overview, Automated Operational Brief, KPIs & Reconciled Summaries."""
    brief = generate_operational_brief(dataset, all_slots)
    if int(brief["total_unfilled"]) == 0:
        st.success(f"**Automated Executive Operational Brief** — {brief['narrative']}")
    else:
        st.info(f"**Automated Executive Operational Brief** — {brief['narrative']}")

    if baseline_dataset is not None:
        deltas = compute_cross_run_deltas(dataset, baseline_dataset)
        st.markdown(f"#### Cross-Run Delta vs Baseline (`{baseline_dataset.name}`)")
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Active Coverage %", f"{deltas['active']['coverage_pct']:.2f}%", f"{deltas['delta_coverage_pct']:+.2f}%")
        d2.metric("Active Gap Fill %", f"{deltas['active']['gap_fill_pct']:.2f}%", f"{deltas['delta_gap_fill_pct']:+.2f}%")
        d3.metric(
            "Unfilled Demand",
            f"{deltas['active']['unfilled_demand']:,}",
            f"{deltas['delta_unfilled_demand']:+d}",
            delta_color="inverse",
        )
        d4.metric(
            "Reassigned Crews",
            f"{deltas['active']['reassigned_crew_count']:,}",
            f"{deltas['delta_reassigned_crews']:+d}",
            delta_color="inverse",
        )
        cost_val = f"{deltas['active']['solver_cost']:,}" if deltas["active"]["solver_cost"] is not None else "N/A"
        cost_delta = f"{deltas['delta_cost']:+d}" if deltas["delta_cost"] is not None else None
        d5.metric("Assignment Cost", cost_val, cost_delta, delta_color="inverse")

    st.subheader("Executive Summary KPIs (Reconciled Source Metrics)")
    kpis = compute_summary_kpis(dataset)
    ext = compute_extended_kpis(dataset)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Crew Demand", f"{kpis.total_demand:,}", help=f"Exact total demand shifts: {kpis.total_demand}")
    c2.metric("Assigned Demand Shifts", f"{kpis.assigned_demand:,}", help=f"Exact assigned demand shifts: {kpis.assigned_demand}")
    c3.metric("Unfilled Demand Shifts", f"{kpis.unfilled_demand:,}", help=f"Exact unfilled demand shifts: {kpis.unfilled_demand}")
    c4.metric(
        "Demand Coverage %",
        f"{kpis.coverage_pct:.2f}%",
        help=f"Exact coverage: {kpis.coverage_pct:.4f}% ({kpis.assigned_demand:,} / {kpis.total_demand:,})",
    )
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

    g1, g2, g3, g4, g5, g6 = st.columns(6)
    g1.metric("Total Leave Gaps", f"{kpis.total_gaps:,}", help=f"Open: {kpis.open_gaps_to_fill:,} + Locked: {kpis.locked_gaps:,}")
    g2.metric("Open Gaps (On/After Solver Start)", f"{kpis.open_gaps_to_fill:,}")
    g3.metric(
        "Open Gaps Filled by CP-SAT",
        f"{kpis.gaps_filled:,} ({kpis.gap_fill_pct:.1f}%)",
        help=f"Exact fill rate: {kpis.gap_fill_pct:.4f}% ({kpis.gaps_filled:,} / {kpis.open_gaps_to_fill:,})",
    )
    g4.metric(
        "Selected Work Shifts",
        f"{ext['total_selected_work_assignments']:,}",
        help=f"Demand: {ext['demand_assignments']:,} | Relief: {ext['relief_assignments']:,} | Excess: {ext['excess_assignments']:,}",
    )
    g5.metric(
        "Reassigned Crews",
        f"{ext['reassigned_crew_count']:,}",
        help=f"Unique crews moved vs baseline ({ext['reassigned_row_count']:,} reassigned shift rows)",
    )
    rt_str = f"{ext['solver_runtime_sec']:.1f}s" if ext["solver_runtime_sec"] is not None else "N/A"
    g6.metric(
        "Solver Status & Runtime",
        f"{ext['solver_status']} ({rt_str})",
        help=f"Locked gaps before solver start: {kpis.locked_gaps:,}",
    )

    stages = parsed_meta.get("stages", [])
    val_headline = str(parsed_meta.get("validation_headline", ""))
    if stages or val_headline:
        st.markdown("#### Solver Objective Stages & Rule Validation Status")
        b_cols = st.columns(max(1, len(stages) + 1))
        for idx, stg in enumerate(stages):
            detail_txt = stg["Details"].replace(stg["Status"], "").strip(" ()")
            stage_label = stg["Stage"].title()
            if not stage_label.lower().startswith("stage "):
                stage_label = f"Stage {idx + 1}: {stage_label}"
            b_cols[idx].metric(
                stage_label,
                stg["Status"],
                detail_txt,
                delta_color="off",
                help=f"{stage_label}: {stg['Status']} ({detail_txt})",
            )
        if val_headline:
            val_status = "PASS (0 Failures)" if "0 unexpected failure" in val_headline else "Check Failures"
            b_cols[-1].metric(
                "Validation Check",
                val_status,
                val_headline,
                delta_color="off",
                help=val_headline,
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
    g_col1, g_col2, g_col3 = st.columns([4, 3, 3])
    donuts = create_assignment_type_donut_charts(ext)
    with g_col1:
        st.plotly_chart(
            create_fill_rate_gauge_chart(kpis.coverage_pct, kpis.gap_fill_pct),
            use_container_width=True,
            key="ov_gauge",
        )
    with g_col2:
        st.plotly_chart(donuts["assignment_type"], use_container_width=True, key="ov_donut_type")
    with g_col3:
        st.plotly_chart(donuts["crew_classification"], use_container_width=True, key="ov_donut_cls")

    col_left, col_right = st.columns(2)
    head_agg = aggregate_by_activity_head(all_slots)
    swing_agg = aggregate_by_swing(dataset)
    depot_agg = aggregate_by_depot(dataset, all_slots)

    with col_left:
        st.markdown("#### Activity Head-wise Coverage Summary")
        st.dataframe(
            head_agg,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Coverage %": st.column_config.ProgressColumn(
                    "Coverage %", format="%.2f%%", min_value=0, max_value=100
                ),
            },
        )

    with col_right:
        st.markdown("#### Swing-wise Coverage Summary")
        st.dataframe(
            swing_agg,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Coverage %": st.column_config.ProgressColumn(
                    "Coverage %", format="%.2f%%", min_value=0, max_value=100
                ),
            },
        )

    gap_summaries = summarize_gaps(build_unfilled_gap_records(dataset))
    summary_figs = create_gap_summary_charts(gap_summaries, head_agg)
    c_chart1, c_chart2 = st.columns([3, 2])
    with c_chart1:
        st.plotly_chart(summary_figs["resident_vs_fifo"], use_container_width=True, key="ov_res_fifo")
    with c_chart2:
        st.plotly_chart(create_depot_coverage_chart(depot_agg), use_container_width=True, key="ov_depot_cov")

    st.markdown("---")
    st.markdown("#### 3-Stage Demand Lifecycle & Leave Impact Breakdown")
    lifecycle = compute_lifecycle_waterfall(dataset)
    lc1, lc2 = st.columns([3, 2])
    with lc1:
        st.plotly_chart(create_lifecycle_waterfall_chart(lifecycle), use_container_width=True, key="ov_lifecycle")
    with lc2:
        st.markdown("**Leave Type Recovery Breakdown**")
        if lifecycle["leave_breakdown"]:
            st.dataframe(lifecycle["leave_breakdown"], use_container_width=True, hide_index=True)
        else:
            st.info("No leave gaps present in this dataset.")


def render_demand_coverage(
    dataset: DashboardDataset,
    all_heads: list[str],
    all_swings: list[str],
    all_dates: list[str],
    all_shifts: list[str],
    default_heads: list[str] | None = None,
    default_swings: list[str] | None = None,
    default_crew_types: list[str] | None = None,
) -> None:
    """Render Page 2: Demand vs Coverage Analysis & Heatmaps."""
    st.subheader("Demand vs Coverage Analysis & Bottleneck Heatmaps")
    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        sel_heads = st.multiselect(
            "Filter by Activity Head",
            all_heads,
            default=[h for h in (default_heads or []) if h in all_heads],
        )
    with f2:
        sel_swings = st.multiselect(
            "Filter by Swing",
            all_swings,
            default=[s for s in (default_swings or []) if s in all_swings],
        )
    with f3:
        sel_crew_types = st.multiselect(
            "Filter by Crew Type",
            ["Residential", "FIFO"],
            default=[c for c in (default_crew_types or []) if c in ("Residential", "FIFO")],
        )
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
    st.plotly_chart(fig_heatmap, use_container_width=True, key="cov_heatmap_main")

    hd_col1, hd_col2 = st.columns([3, 2])
    head_depot_rows = aggregate_by_depot_and_head(dataset, filtered_slots)
    bottleneck_heads = sorted(
        aggregate_by_activity_head(filtered_slots),
        key=lambda r: (-int(r["Remaining Gap"]), int(r["Priority"]), str(r["Activity Head"])),
    )
    with hd_col1:
        st.plotly_chart(
            create_head_depot_coverage_heatmap(head_depot_rows),
            use_container_width=True,
            key="cov_heatmap_depot",
        )
    with hd_col2:
        st.markdown("#### Ranked Bottleneck Table (By Unfilled Demand & Priority)")
        st.dataframe(
            bottleneck_heads,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Coverage %": st.column_config.ProgressColumn(
                    "Coverage %", format="%.2f%%", min_value=0, max_value=100
                ),
            },
        )

    st.markdown("#### Detailed Slot Coverage Table")
    st.dataframe(
        filtered_slots,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Coverage %": st.column_config.ProgressColumn(
                "Coverage %", format="%.2f%%", min_value=0, max_value=100
            ),
        },
    )


def render_crew_assignment(
    dataset: DashboardDataset,
    all_heads: list[str],
    all_swings: list[str],
    default_heads: list[str] | None = None,
    default_swings: list[str] | None = None,
    default_crew_types: list[str] | None = None,
) -> None:
    """Render Section 3: Crew Assignment Gantt Chart & Individual Schedule."""
    st.subheader("Crew Assignment Gantt Chart (Actual Selected Solver Assignments)")
    all_users = sorted(dataset.crew_by_id.keys())

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        sel_crew_types = st.multiselect(
            "Crew Classification",
            ["Residential", "FIFO"],
            default=[c for c in (default_crew_types or []) if c in ("Residential", "FIFO")],
        )
    with f2:
        sel_swings = st.multiselect(
            "Swing",
            all_swings,
            default=[s for s in (default_swings or []) if s in all_swings],
        )
    with f3:
        sel_heads = st.multiselect(
            "Activity Head",
            all_heads,
            default=[h for h in (default_heads or []) if h in all_heads],
        )
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
        st.download_button(
            "Download Reassignment Diff Table (CSV)",
            data=rows_to_csv_bytes(before_after_rows),
            file_name="reassignment_diff_table.csv",
            mime="text/csv",
        )
    else:
        st.info("No reassigned/moved shifts match the current filters.")

    st.markdown("#### Selected Crew Assignment Records")
    st.dataframe(timeline_records, use_container_width=True, hide_index=True)
    if timeline_records:
        st.download_button(
            "Download Selected Crew Assignments (CSV)",
            data=rows_to_csv_bytes(timeline_records),
            file_name="selected_crew_assignments.csv",
            mime="text/csv",
        )

    st.markdown("#### Individual Crew Journey & Printable Schedule")
    crew_options = sorted(dataset.crew_by_id.keys()) or all_users
    if crew_options:
        sel_individual = st.selectbox("Select Crew Member for Full Schedule", options=crew_options)
        indiv_schedule = build_individual_crew_schedule(dataset, sel_individual)
        crew_meta = dataset.crew_by_id.get(sel_individual, {})
        m1, m2, m3 = st.columns(3)
        m1.metric("Classification", crew_meta.get("Classification", "Unknown"))
        m2.metric("Home Depot", crew_meta.get("Home Depot", "") or crew_meta.get("Depot", "Unknown"))
        m3.metric("Total Timeline Entries", len(indiv_schedule))
        st.plotly_chart(create_individual_crew_calendar_chart(indiv_schedule, sel_individual), use_container_width=True)
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


def render_gap_analysis(
    dataset: DashboardDataset,
    all_heads: list[str],
    all_swings: list[str],
    default_heads: list[str] | None = None,
    default_swings: list[str] | None = None,
) -> None:
    """Render Section 4: Gap-Filling Analysis & Seat Inspector."""
    st.subheader("Gap-Filling Analysis (Unfilled Demand)")
    f1, f2 = st.columns(2)
    with f1:
        sel_head = st.multiselect(
            "Inspect Activity Head(s)",
            all_heads,
            default=[h for h in (default_heads or []) if h in all_heads],
        )
    with f2:
        sel_swing = st.multiselect(
            "Inspect Swing(s)",
            all_swings,
            default=[s for s in (default_swings or []) if s in all_swings],
        )

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
        st.plotly_chart(charts["by_head"], use_container_width=True, key="gap_by_head")
    with r1c2:
        st.plotly_chart(charts["by_priority"], use_container_width=True, key="gap_by_priority")

    r2c1, r2c2 = st.columns(2)
    with r2c1:
        st.plotly_chart(charts["by_shift"], use_container_width=True, key="gap_by_shift")
    with r2c2:
        st.plotly_chart(charts["resident_vs_fifo"], use_container_width=True, key="gap_res_fifo")

    t_col1, t_col2 = st.columns(2)
    with t_col1:
        st.plotly_chart(create_unfilled_treemap_chart(unfilled_records), use_container_width=True, key="gap_treemap")
    with t_col2:
        density_rows = compute_option_density_vs_fill(dataset)
        st.plotly_chart(create_option_density_scatter_chart(density_rows), use_container_width=True, key="gap_density")

    st.markdown("#### Unfilled Demand Slots Table")
    st.dataframe(unfilled_records, use_container_width=True, hide_index=True)
    if unfilled_records:
        st.download_button(
            "Download Filtered Unfilled Gap Report (CSV)",
            data=rows_to_csv_bytes(unfilled_records),
            file_name="unfilled_gap_report.csv",
            mime="text/csv",
        )

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
