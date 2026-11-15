"""Plotly chart builders for the Crew Rostering & Gap-Filling Dashboard."""

from __future__ import annotations

from collections import defaultdict

import plotly.express as px
import plotly.graph_objects as go

VIBRANT_PALETTE = [
    "#2563eb",  # Royal Blue
    "#10b981",  # Emerald
    "#f59e0b",  # Amber
    "#ef4444",  # Coral Red
    "#8b5cf6",  # Violet
    "#06b6d4",  # Cyan
    "#ec4899",  # Pink
    "#14b8a6",  # Teal
]
px.defaults.color_discrete_sequence = VIBRANT_PALETTE


def _apply_chart_theme(fig: go.Figure) -> go.Figure:
    """Apply consistent typography, gridlines, and high-contrast hover styling."""
    fig.update_layout(
        template="plotly_white",
        font={"family": "Inter, Segoe UI, sans-serif", "size": 12, "color": "#1e293b"},
        title_font={"size": 15, "color": "#0f172a"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248, 250, 252, 0.55)",
        hoverlabel={"bgcolor": "#0f172a", "font_color": "#f8fafc", "font_size": 12},
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(203, 213, 225, 0.45)", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(203, 213, 225, 0.45)", zeroline=False)
    return fig


def create_demand_coverage_heatmap(
    slot_records: list[dict[str, object]],
    column_mode: str = "Date",
) -> go.Figure:
    """Build an interactive Demand vs Coverage Heatmap.

    Rows: Activity Heads (ordered by Priority).
    Columns: `Date`, `Shift`, or `Date_Shift`.
    Colors:
      - Green (1.0): Fully covered (Remaining Gap == 0 and Total Demand > 0)
      - Yellow (0.5): Partially covered (0 < Assigned Demand < Total Demand)
      - Red (0.0): Completely unfilled (Assigned Demand == 0 and Total Demand > 0)
    Cell text displays `Demand / Assigned / Gap` and hover displays full breakdown.
    """
    if not slot_records:
        fig = go.Figure()
        fig.update_layout(title="No demand slot records match the selected filters.")
        return fig

    col_key = column_mode if column_mode in ("Date", "Shift", "Date_Shift") else "Date"

    heads_sorted = [
        h
        for h, _ in sorted(
            {(str(s["Activity Head"]), int(s["Priority"])) for s in slot_records},
            key=lambda x: (x[1], x[0]),
        )
    ]
    cols_sorted = sorted({str(s[col_key]) for s in slot_records})

    agg: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"demand": 0, "assigned": 0, "gap": 0, "res": 0, "fifo": 0}
    )
    for s in slot_records:
        key = (str(s["Activity Head"]), str(s[col_key]))
        agg[key]["demand"] += int(s["Total Demand"])
        agg[key]["assigned"] += int(s["Assigned Demand"])
        agg[key]["gap"] += int(s["Remaining Gap"])
        agg[key]["res"] += int(s["Resident Assigned"])
        agg[key]["fifo"] += int(s["FIFO Assigned"])

    z_matrix: list[list[float | None]] = []
    text_matrix: list[list[str]] = []
    hover_matrix: list[list[str]] = []

    for head in heads_sorted:
        z_row: list[float | None] = []
        t_row: list[str] = []
        h_row: list[str] = []
        for col in cols_sorted:
            cell = agg.get((head, col))
            if not cell or cell["demand"] == 0:
                z_row.append(None)
                t_row.append("")
                h_row.append(f"<b>{head}</b><br>{col_key}: {col}<br>No active demand")
                continue
            d = cell["demand"]
            a = cell["assigned"]
            g = cell["gap"]
            cov = (a / d) * 100.0 if d > 0 else 0.0
            if g == 0:
                score = 1.0
                status = "Fully Covered (Green)"
            elif a > 0:
                score = 0.5
                status = "Partially Covered (Yellow)"
            else:
                score = 0.0
                status = "Completely Unfilled (Red)"
            z_row.append(score)
            t_row.append(f"{d}/{a}/{g}")
            h_row.append(
                f"<b>{head}</b><br>"
                f"{col_key}: {col}<br>"
                f"Status: {status}<br>"
                f"Total Demand: {d}<br>"
                f"Assigned Crew: {a} (Res: {cell['res']}, FIFO: {cell['fifo']})<br>"
                f"Remaining Gap: {g}<br>"
                f"Coverage: {cov:.1f}%"
            )
        z_matrix.append(z_row)
        text_matrix.append(t_row)
        hover_matrix.append(h_row)

    colorscale = [
        [0.0, "#d9534f"],   # Red: Unfilled
        [0.49, "#d9534f"],
        [0.5, "#f0ad4e"],   # Yellow: Partially covered
        [0.99, "#f0ad4e"],
        [1.0, "#2ea043"],   # Green: Fully covered
    ]

    fig = go.Figure(
        data=go.Heatmap(
            z=z_matrix,
            x=cols_sorted,
            y=heads_sorted,
            text=text_matrix,
            texttemplate="%{text}",
            hovertext=hover_matrix,
            hoverinfo="text",
            colorscale=colorscale,
            zmin=0.0,
            zmax=1.0,
            xgap=2,
            ygap=2,
            colorbar={
                "title": "Coverage",
                "tickvals": [0.0, 0.5, 1.0],
                "ticktext": ["Unfilled", "Partial", "Full"],
            },
        )
    )
    fig.update_layout(
        title=f"Demand vs Assigned vs Gap Heatmap (by {col_key}; Cell = Demand/Assigned/Gap)",
        xaxis_title=col_key,
        yaxis_title="Activity Head (Ordered by Priority)",
        yaxis={"autorange": "reversed"},
        height=max(420, 38 * len(heads_sorted) + 140),
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


ACTIVITY_NAME_PALETTE = [
    "#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed",
    "#0891b2", "#db2777", "#65a30d", "#ea580c", "#4f46e5",
    "#0d9488", "#be123c", "#ca8a04", "#0284c7", "#9333ea",
    "#16a34a", "#e11d48", "#0369a1", "#6d28d9", "#b45309",
    "#15803d", "#1d4ed8", "#a21caf", "#c2410c",
]


def build_activity_name_color_map(activity_names: list[str]) -> dict[str, str]:
    """Return a deterministic, distinct hex color mapping for each Activity Name."""
    unique_names = sorted({str(name).strip() for name in activity_names if str(name).strip()})
    color_map: dict[str, str] = {}
    for idx, name in enumerate(unique_names):
        if name.lower().startswith("unassigned") or "leave" in name.lower():
            color_map[name] = "#ef4444"
        elif name.lower() == "off":
            color_map[name] = "#94a3b8"
        elif "travel" in name.lower():
            color_map[name] = "#8b5cf6"
        else:
            color_map[name] = ACTIVITY_NAME_PALETTE[idx % len(ACTIVITY_NAME_PALETTE)]
    return color_map


def create_crew_gantt_chart(
    timeline_records: list[dict[str, str]],
    color_by: str = "Activity Name",
    max_crew: int = 40,
) -> go.Figure:
    """Build an interactive Crew Assignment Gantt chart from actual selected solver assignments."""
    if not timeline_records:
        fig = go.Figure()
        fig.update_layout(title="No crew assignment records match the selected filters.")
        return fig

    unique_users: list[str] = []
    seen: set[str] = set()
    for r in timeline_records:
        u = r["User Id"]
        if u not in seen:
            seen.add(u)
            unique_users.append(u)
    allowed_users = set(unique_users[:max_crew])
    filtered = [r for r in timeline_records if r["User Id"] in allowed_users]

    valid_color_fields = (
        "Activity Name",
        "Activity Name Change",
        "Activity Head",
        "Assignment Type",
        "Crew Classification",
        "State",
        "Changed",
    )
    color_field = color_by if color_by in valid_color_fields else "Activity Name"

    color_discrete_map: dict[str, str] | None = None
    if color_field == "Activity Name":
        color_discrete_map = build_activity_name_color_map(
            [str(r.get("Activity Name", "")) for r in filtered]
        )
    elif color_field == "Activity Name Change":
        color_discrete_map = {
            "Activity Name Changed": "#dc2626",
            "Same Activity (Time/Seat Changed)": "#2563eb",
            "Unchanged": "#94a3b8",
            "Unassigned / On Leave": "#fca5a5",
        }
    elif color_field == "Changed":
        color_discrete_map = {
            "Reassigned / Moved": "#f59e0b",
            "Unchanged": "#64748b",
        }

    fig = px.timeline(
        filtered,
        x_start="Start",
        x_end="End",
        y="Crew Label",
        color=color_field,
        color_discrete_map=color_discrete_map,
        hover_name="Activity Name",
        hover_data={
            "Assignment ID": True,
            "User Id": True,
            "Crew Classification": True,
            "Swing": True,
            "Before Activity Name": True,
            "After Activity Name": True,
            "Before Activity Head": True,
            "After Activity Head": True,
            "Before Start Datetime": True,
            "After Start Datetime": True,
            "Activity Name Changed": True,
            "Assignment Type": True,
            "State": True,
            "Changed": True,
            "Reassignment Detail": True,
            "Start Location": True,
            "End Location": True,
            "Optimisation Note": True,
            "Crew Label": False,
        },
        title=f"Selected Crew Assignments Timeline (Showing {len(allowed_users)} of {len(unique_users)} Crew Members)",
    )
    fig.update_yaxes(autorange="reversed", title="Crew Member (Classification)")
    fig.update_xaxes(title="Shift Timeline")
    fig.update_layout(
        height=max(420, 28 * len(allowed_users) + 140),
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_gap_summary_charts(
    gap_summaries: dict[str, list[dict[str, object]]],
    head_aggregates: list[dict[str, object]],
) -> dict[str, go.Figure]:
    """Build bar charts for Gap-Filling Analysis (by Activity Head, Shift, Priority, and Resident vs FIFO)."""
    by_head = gap_summaries.get("by_head", [])
    by_shift = gap_summaries.get("by_shift", [])
    by_priority = gap_summaries.get("by_priority", [])

    if by_head:
        fig_head = px.bar(
            by_head,
            x="Activity Head",
            y=["Open Unfilled Gaps", "Locked Gaps"],
            title="Remaining Gaps by Activity Head (Open vs Locked)",
            labels={"value": "Remaining Gaps", "variable": "Gap Type"},
            barmode="stack",
        )
    else:
        fig_head = go.Figure()
        fig_head.update_layout(title="No Remaining Gaps by Activity Head")

    if by_shift:
        fig_shift = px.bar(
            by_shift,
            x="Shift",
            y="Remaining Gaps",
            title="Remaining Gaps by Shift Start Time",
            color_discrete_sequence=["#d9534f"],
        )
    else:
        fig_shift = go.Figure()
        fig_shift.update_layout(title="No Remaining Gaps by Shift")

    if by_priority:
        fig_prio = px.bar(
            by_priority,
            x="Priority",
            y="Remaining Gaps",
            title="Remaining Gaps by Activity-Head Priority (1 = Highest Priority)",
            color_discrete_sequence=["#f0ad4e"],
        )
        fig_prio.update_xaxes(type="category")
    else:
        fig_prio = go.Figure()
        fig_prio.update_layout(title="No Remaining Gaps by Priority")

    if head_aggregates:
        fig_contrib = px.bar(
            head_aggregates,
            x="Activity Head",
            y=["Resident Assigned", "FIFO Assigned", "Remaining Gap"],
            title="Resident vs FIFO Assigned Demand & Remaining Gaps by Activity Head",
            labels={"value": "Crew-Shifts", "variable": "Category"},
            barmode="stack",
            color_discrete_map={
                "Resident Assigned": "#1f77b4",
                "FIFO Assigned": "#2ca02c",
                "Remaining Gap": "#d9534f",
            },
        )
    else:
        fig_contrib = go.Figure()
        fig_contrib.update_layout(title="No Activity Head Demand Data")

    return {
        "by_head": fig_head,
        "by_shift": fig_shift,
        "by_priority": fig_prio,
        "resident_vs_fifo": fig_contrib,
    }


def create_strategy_comparison_charts(comparison: dict[str, object]) -> dict[str, go.Figure]:
    """Build grouped bar charts comparing None, Weighted, and Lexicographic strategies."""
    by_head = list(comparison.get("by_head", []))
    by_priority = list(comparison.get("by_priority", []))

    if by_head:
        fig_head = px.bar(
            by_head,
            x="Activity Head",
            y="Coverage %",
            color="Strategy",
            barmode="group",
            hover_data=["Priority", "Total Demand", "Assigned Demand", "Remaining Gap"],
            title="Activity Head-wise Demand Coverage (%) by Strategy",
        )
    else:
        fig_head = go.Figure()
        fig_head.update_layout(title="No Strategy Comparison Data by Activity Head")

    if by_priority:
        fig_prio = px.bar(
            by_priority,
            x="Priority",
            y="Assigned Demand",
            color="Strategy",
            barmode="group",
            hover_data=["Total Demand", "Remaining Gap", "Coverage %"],
            title="Assigned Demand by Priority Level Across Strategies",
        )
        fig_prio.update_xaxes(type="category")
    else:
        fig_prio = go.Figure()
        fig_prio.update_layout(title="No Strategy Comparison Data by Priority")

    return {
        "by_head": fig_head,
        "by_priority": fig_prio,
    }


def create_shift_limit_utilization_chart(head_limits_table: list[dict[str, object]]) -> go.Figure:
    """Build a grouped bar chart comparing Max Observed Shifts/Swing vs Configured Max Resident/FIFO Shifts."""
    if not head_limits_table:
        fig = go.Figure()
        fig.update_layout(title="No Activity-Head Shift Limit Data Available")
        return fig

    heads = [str(r["Activity Head"]) for r in head_limits_table]
    obs_res = [int(r.get("Max Observed Resident Shifts / Swing") or 0) for r in head_limits_table]
    lim_res = [int(r.get("Max Resident Shifts (Config)") or 0) for r in head_limits_table]
    obs_fifo = [int(r.get("Max Observed FIFO Shifts / Swing") or 0) for r in head_limits_table]
    lim_fifo = [int(r.get("Max FIFO Shifts (Config)") or 0) for r in head_limits_table]

    fig = go.Figure(
        data=[
            go.Bar(name="Observed Max Resident / Swing", x=heads, y=obs_res, marker_color="#1f77b4"),
            go.Bar(name="Configured Max Resident Limit", x=heads, y=lim_res, marker_color="#9ecae1"),
            go.Bar(name="Observed Max FIFO / Swing", x=heads, y=obs_fifo, marker_color="#2ca02c"),
            go.Bar(name="Configured Max FIFO Limit", x=heads, y=lim_fifo, marker_color="#a1d99b"),
        ]
    )
    fig.update_layout(
        barmode="group",
        title="Per-Swing Activity-Head Shift Utilization vs Configured Limits (Resident & FIFO)",
        xaxis_title="Activity Head (Ordered by Priority)",
        yaxis_title="Shifts per Swing",
        height=420,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_workload_distribution_chart(crew_rows: list[dict[str, object]], top_n: int = 30) -> go.Figure:
    """Stacked bar chart of Day vs Night shifts for top crew members by total worked shifts."""
    if not crew_rows:
        fig = go.Figure()
        fig.update_layout(title="No Crew Workload Data Available")
        return fig

    subset = crew_rows[:top_n]
    users = [str(r["User Id"]) for r in subset]
    day_shifts = [int(r["Day Shifts"]) for r in subset]
    night_shifts = [int(r["Night Shifts"]) for r in subset]

    fig = go.Figure(
        data=[
            go.Bar(name="Day Shifts", x=users, y=day_shifts, marker_color="#f59e0b"),
            go.Bar(name="Night Shifts", x=users, y=night_shifts, marker_color="#1e3a8a"),
        ]
    )
    fig.update_layout(
        barmode="stack",
        title=f"Crew Workload Distribution (Day vs Night Shifts, Top {len(subset)} Crew)",
        xaxis_title="Crew Member (User Id)",
        yaxis_title="Worked Shifts",
        height=400,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_reassignment_sankey_chart(sankey_links: list[dict[str, object]]) -> go.Figure:
    """Sankey flow diagram showing gap-fill sources flowing into target activities."""
    if not sankey_links:
        fig = go.Figure()
        fig.update_layout(title="No Reassignment Moves to Visualize")
        return fig

    labels: list[str] = []
    idx_by_label: dict[str, int] = {}

    def get_idx(lbl: str) -> int:
        if lbl not in idx_by_label:
            idx_by_label[lbl] = len(labels)
            labels.append(lbl)
        return idx_by_label[lbl]

    sources: list[int] = []
    targets: list[int] = []
    values: list[int] = []
    for link in sankey_links:
        sources.append(get_idx(str(link["source"])))
        targets.append(get_idx(str(link["target"])))
        values.append(int(link["value"]))

    fig = go.Figure(
        data=[
            go.Sankey(
                node={"pad": 15, "thickness": 18, "label": labels},
                link={"source": sources, "target": targets, "value": values},
            )
        ]
    )
    fig.update_layout(
        title="Reassignment Flow: Source Type & Activity -> Target Activity",
        height=460,
        margin={"l": 20, "r": 20, "t": 50, "b": 20},
    )
    return fig


def create_depot_balance_chart(depot_rows: list[dict[str, object]]) -> go.Figure:
    """Grouped bar chart of Shift Starts vs Shift Ends per Depot."""
    if not depot_rows:
        fig = go.Figure()
        fig.update_layout(title="No Depot Balance Data Available")
        return fig

    depots = [str(r["Depot"]) for r in depot_rows]
    starts = [int(r["Shift Starts (Outflow)"]) for r in depot_rows]
    ends = [int(r["Shift Ends (Inflow)"]) for r in depot_rows]

    fig = go.Figure(
        data=[
            go.Bar(name="Shift Starts (Outflow)", x=depots, y=starts, marker_color="#0284c7"),
            go.Bar(name="Shift Ends (Inflow)", x=depots, y=ends, marker_color="#16a34a"),
        ]
    )
    fig.update_layout(
        barmode="group",
        title="Depot Inflow vs Outflow Balance",
        xaxis_title="Depot",
        yaxis_title="Shift Count",
        height=380,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_cost_and_offset_charts(cost_analytics: dict[str, object]) -> dict[str, go.Figure]:
    """Build cost-by-source and start-time offset (F1/F3) distribution charts."""
    source_rows = cost_analytics.get("source_rows", [])
    offset_rows = cost_analytics.get("offset_rows", [])

    if source_rows:
        fig_cost = go.Figure(
            data=[
                go.Bar(
                    x=[str(r["Source Type"]) for r in source_rows],
                    y=[int(r["Total Cost"]) for r in source_rows],
                    text=[f"Cost {r['Total Cost']} ({r['Moves']} moves)" for r in source_rows],
                    textposition="auto",
                    marker_color=["#2ca02c", "#1f77b4", "#ff7f0e"][: len(source_rows)],
                )
            ]
        )
        fig_cost.update_layout(
            title="Reassignment Cost Breakdown by Source Type",
            xaxis_title="Assignment Source Type",
            yaxis_title="Total Solver Cost",
            height=360,
            margin={"l": 20, "r": 20, "t": 50, "b": 40},
        )
    else:
        fig_cost = go.Figure()
        fig_cost.update_layout(title="No Cost Breakdown Data Available")

    if offset_rows:
        fig_off = go.Figure(
            data=[
                go.Bar(
                    x=[str(r["Start Offset"]) for r in offset_rows],
                    y=[int(r["Moves"]) for r in offset_rows],
                    text=[int(r["Moves"]) for r in offset_rows],
                    textposition="auto",
                    marker_color="#6366f1",
                )
            ]
        )
        fig_off.update_layout(
            title="Start-Time Flexibility Usage (F1/F3 Lift-Up / Layback Offsets)",
            xaxis_title="Offset from Original Start Time",
            yaxis_title="Number of Moves",
            height=360,
            margin={"l": 20, "r": 20, "t": 50, "b": 40},
        )
    else:
        fig_off = go.Figure()
        fig_off.update_layout(title="No Start-Time Offset Data Available")

    return {"cost_by_source": fig_cost, "offsets": fig_off}


def create_skill_supply_chart(supply_rows: list[dict[str, object]]) -> go.Figure:
    """Grouped bar chart comparing Eligible Certified Crew vs Daily Demand per Activity Head."""
    if not supply_rows:
        fig = go.Figure()
        fig.update_layout(title="No Eligibility Supply Data Available")
        return fig

    heads = [str(r["Activity Head"]) for r in supply_rows]
    elig = [int(r["Eligible Crew"]) for r in supply_rows]
    dem = [int(r["Daily Demand (Shifts)"]) for r in supply_rows]

    fig = go.Figure(
        data=[
            go.Bar(name="Eligible Certified Crew", x=heads, y=elig, marker_color="#10b981"),
            go.Bar(name="Daily Demand (Shifts/Day)", x=heads, y=dem, marker_color="#ef4444"),
        ]
    )
    fig.update_layout(
        barmode="group",
        title="Certification Supply vs Daily Demand by Activity Head",
        xaxis_title="Activity Head (Ordered by Priority)",
        yaxis_title="Headcount / Daily Shifts",
        height=400,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_depot_head_eligibility_heatmap(matrix_rows: list[dict[str, object]]) -> go.Figure:
    """Heatmap of certified crew count by Home Depot x Activity Head."""
    if not matrix_rows:
        fig = go.Figure()
        fig.update_layout(title="No Depot x Activity Head Eligibility Data Available")
        return fig

    depots = sorted({str(r["Depot"]) for r in matrix_rows})
    heads = sorted({str(r["Activity Head"]) for r in matrix_rows})
    lookup = {(str(r["Depot"]), str(r["Activity Head"])): int(r["Eligible Crew"]) for r in matrix_rows}

    z = [[lookup.get((d, h), 0) for h in heads] for d in depots]
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=heads,
            y=depots,
            colorscale="Blues",
            text=z,
            texttemplate="%{text}",
            colorbar={"title": "Certified Crew"},
        )
    )
    fig.update_layout(
        title="Depot × Activity Head Certified Crew Matrix",
        xaxis_title="Activity Head",
        yaxis_title="Home Depot",
        height=380,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_rest_margin_histogram(rest_buckets: list[dict[str, object]]) -> go.Figure:
    """Bar chart of intra-swing rest-time margin buckets."""
    if not rest_buckets:
        fig = go.Figure()
        fig.update_layout(title="No Rest Margin Data Available")
        return fig

    cats = [str(r["Category"]) for r in rest_buckets]
    vals = [int(r["Transitions"]) for r in rest_buckets]
    colors = ["#dc2626", "#f59e0b", "#3b82f6", "#10b981", "#059669"]

    fig = go.Figure(
        data=[
            go.Bar(
                x=cats,
                y=vals,
                text=vals,
                textposition="auto",
                marker_color=colors[: len(cats)],
            )
        ]
    )
    fig.update_layout(
        title="Intra-Swing Rest Margin Distribution (Resilience Monitor)",
        xaxis_title="Rest Hours Between Consecutive Work Shifts",
        yaxis_title="Shift Transitions",
        height=360,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_daily_pool_area_chart(daily_pool_rows: list[dict[str, object]]) -> go.Figure:
    """Stacked area chart of daily crew pool allocation across the planning horizon."""
    if not daily_pool_rows:
        fig = go.Figure()
        fig.update_layout(title="No Daily Crew Pool Data Available")
        return fig

    dates = [str(r["Date"]) for r in daily_pool_rows]
    series = [
        ("Working (Demand)", "#2563eb"),
        ("Working (Excess)", "#06b6d4"),
        ("Relief Standby", "#10b981"),
        ("Traveling", "#8b5cf6"),
        ("On Leave / Unfilled Gap", "#ef4444"),
        ("Off-Swing", "#9ca3af"),
    ]
    fig = go.Figure()
    for col, color in series:
        fig.add_trace(
            go.Scatter(
                name=col,
                x=dates,
                y=[int(r.get(col, 0)) for r in daily_pool_rows],
                mode="lines",
                stackgroup="one",
                line={"width": 0.5, "color": color},
            )
        )
    fig.update_layout(
        title="Daily Crew Pool Allocation Across Horizon",
        xaxis_title="Date",
        yaxis_title="Roster Rows / Crew",
        height=400,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_lifecycle_waterfall_chart(lifecycle: dict[str, object]) -> go.Figure:
    """3-stage waterfall chart from Baseline Demand through Leave Gaps to Solver Recovery."""
    fig = go.Figure(
        go.Waterfall(
            name="Demand Lifecycle",
            orientation="v",
            measure=["absolute", "relative", "relative", "relative", "total"],
            x=[
                "Baseline Demand",
                "Leave Gaps Injected",
                "Direct Fills",
                "Multi-Hop Chain Fills",
                "Final Covered Demand",
            ],
            y=[
                int(lifecycle.get("total_demand", 0)),
                -int(lifecycle.get("total_gaps", 0)),
                int(lifecycle.get("direct_fills", 0)),
                int(lifecycle.get("multi_hop_fills", 0)),
                0,
            ],
            textposition="outside",
            connector={"line": {"color": "#94a3b8"}},
            increasing={"marker": {"color": "#10b981"}},
            decreasing={"marker": {"color": "#ef4444"}},
            totals={"marker": {"color": "#2563eb"}},
        )
    )
    fig.update_layout(
        title="3-Stage Lifecycle: Baseline Demand -> Leave Gaps -> Solver Recovery",
        yaxis_title="Demand Shifts",
        height=390,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return _apply_chart_theme(fig)


def create_rejection_pareto_chart(rejection_summary: list[dict[str, object]]) -> go.Figure:
    """Pareto bar + cumulative % line chart of Layer-1 rejection reasons."""
    if not rejection_summary:
        fig = go.Figure()
        fig.update_layout(title="No Layer-1 Rejection Data Available")
        return fig

    sorted_rows = sorted(rejection_summary, key=lambda r: -int(r.get("Count", 0)))
    reasons = [str(r.get("Reason", r.get("Rejection Reason", "Unknown"))) for r in sorted_rows]
    counts = [int(r.get("Count", 0)) for r in sorted_rows]
    total = sum(counts) or 1
    cum_pct: list[float] = []
    running = 0
    for c in counts:
        running += c
        cum_pct.append(round(running / total * 100.0, 1))

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Rejections", x=reasons, y=counts, marker_color="#f59e0b", yaxis="y"))
    fig.add_trace(
        go.Scatter(
            name="Cumulative %",
            x=reasons,
            y=cum_pct,
            mode="lines+markers",
            line={"color": "#dc2626", "width": 2},
            yaxis="y2",
        )
    )
    fig.update_layout(
        title="Layer-1 Rejection Pareto (Top Constraint Bottlenecks)",
        xaxis_title="Rejection Reason",
        yaxis={"title": "Rejection Count"},
        yaxis2={"title": "Cumulative %", "overlaying": "y", "side": "right", "range": [0, 105]},
        height=390,
        margin={"l": 20, "r": 30, "t": 50, "b": 70},
        legend={"orientation": "h", "y": 1.12},
    )
    return _apply_chart_theme(fig)


def create_unfilled_treemap_chart(unfilled_records: list[dict[str, object]]) -> go.Figure:
    """Treemap breaking down unfilled demand by Activity Head -> Priority -> Shift."""
    if not unfilled_records:
        fig = go.Figure()
        fig.update_layout(title="No Unfilled Demand Slots")
        return fig

    fig = px.treemap(
        unfilled_records,
        path=["Activity Head", "Priority", "Shift"],
        values="Remaining Gap",
        color="Remaining Gap",
        color_continuous_scale="Reds",
        title="Unfilled Demand Treemap (Activity Head -> Priority -> Shift)",
    )
    fig.update_layout(height=420, margin={"l": 10, "r": 10, "t": 50, "b": 10})
    return fig


def create_option_density_scatter_chart(seat_density_rows: list[dict[str, object]]) -> go.Figure:
    """Scatter plot of Layer-1 legal option count vs fill outcome per open seat."""
    if not seat_density_rows:
        fig = go.Figure()
        fig.update_layout(title="No Seat Option Density Data Available")
        return fig

    fig = px.strip(
        seat_density_rows,
        x="Legal Options (Layer 1)",
        y="Outcome",
        color="Activity Head",
        hover_data=["Seat Key", "Date", "Shift", "Priority"],
        title="Option Density vs Fill Outcome (0 Options = Layer-1 Bottleneck, >0 Unfilled = Layer-2 Conflict)",
    )
    fig.update_layout(height=390, margin={"l": 20, "r": 20, "t": 50, "b": 40})
    return fig


def create_individual_crew_calendar_chart(schedule_rows: list[dict[str, object]], user_id: str) -> go.Figure:
    """Visual timeline/calendar strip for a single crew member across the horizon."""
    plot_rows: list[dict[str, object]] = []
    for r in schedule_rows:
        s_date = str(r.get("Start Date", "")).strip()
        e_date = str(r.get("End Date", "")).strip() or s_date
        s_time = str(r.get("Shift Start", "")).strip() or "00:00"
        e_time = str(r.get("Shift End", "")).strip() or "23:59"
        if not s_date:
            continue
        start_ts = f"{s_date} {s_time}"
        end_ts = f"{e_date} {e_time}"
        if end_ts <= start_ts:
            end_ts = f"{e_date} 23:59"
        plot_rows.append({
            **r,
            "Start": start_ts,
            "End": end_ts,
            "Activity Head": str(r.get("Activity Head", "")).strip() or str(r.get("Assignment Type", "Other")),
        })

    if not plot_rows:
        fig = go.Figure()
        fig.update_layout(title=f"No Schedule Entries for {user_id}")
        return _apply_chart_theme(fig)

    fig = px.timeline(
        plot_rows,
        x_start="Start",
        x_end="End",
        y="Assignment Type",
        color="Activity Head",
        hover_data=[
            "Start Date",
            "Shift Start",
            "End Date",
            "Shift End",
            "Status",
            "Start Location",
            "End Location",
            "Rest Since Prev Shift",
            "Note",
        ],
        title=f"Visual Schedule Strip: {user_id}",
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=320, margin={"l": 20, "r": 20, "t": 50, "b": 30})
    return _apply_chart_theme(fig)


def create_competency_bottleneck_chart(comp_rows: list[dict[str, object]]) -> go.Figure:
    """Horizontal bar chart showing compliant vs blocked crew per Activity Head."""
    if not comp_rows:
        fig = go.Figure()
        fig.update_layout(title="No Competency Compliance Matrix Available")
        return fig

    heads = [str(r["Activity Head"]) for r in comp_rows]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Compliant Crew", y=heads, x=[int(r["Compliant Crew"]) for r in comp_rows], orientation="h", marker_color="#10b981"))
    fig.add_trace(go.Bar(name="Blocked / Missing Crew", y=heads, x=[int(r["Blocked / Missing Crew"]) for r in comp_rows], orientation="h", marker_color="#ef4444"))
    fig.update_layout(
        barmode="stack",
        title="Competency Compliance Readiness by Activity Head",
        xaxis_title="Crew Count",
        height=400,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_daily_supply_vs_demand_chart(daily_supply_rows: list[dict[str, object]]) -> go.Figure:
    """Pre-gap daily demand vs baseline assigned vs relief/excess pool."""
    if not daily_supply_rows:
        fig = go.Figure()
        fig.update_layout(title="No Daily Supply vs Demand Data Available")
        return fig

    dates = [str(r["Date"]) for r in daily_supply_rows]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Baseline Assigned", x=dates, y=[int(r["Baseline Assigned"]) for r in daily_supply_rows], marker_color="#2563eb"))
    fig.add_trace(go.Bar(name="Relief / Excess Pool", x=dates, y=[int(r["Relief/Excess Pool"]) for r in daily_supply_rows], marker_color="#10b981"))
    fig.add_trace(go.Scatter(name="Total Demand Shifts", x=dates, y=[int(r["Demand Shifts"]) for r in daily_supply_rows], mode="lines+markers", line={"color": "#dc2626", "width": 2}))
    fig.update_layout(
        barmode="stack",
        title="Pre-Gap Baseline Supply & Relief Pool vs Daily Demand",
        xaxis_title="Date",
        yaxis_title="Shifts / Crew",
        height=380,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_slot_diff_heatmap(diff_rows: list[dict[str, object]]) -> go.Figure:
    """Heatmap of coverage delta (Comparison - Baseline) across Activity Head x Date."""
    if not diff_rows:
        fig = go.Figure()
        fig.update_layout(title="No Slot Differences Available")
        return fig

    agg: dict[tuple[str, str], int] = {}
    dates: set[str] = set()
    heads: set[str] = set()
    for r in diff_rows:
        d = str(r["Date"])
        h = str(r["Activity Head"])
        dates.add(d)
        heads.add(h)
        agg[(h, d)] = agg.get((h, d), 0) + int(r.get("Delta", 0))

    sorted_dates = sorted(dates)
    sorted_heads = sorted(heads)
    z = [[agg.get((h, d), 0) for d in sorted_dates] for h in sorted_heads]

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=sorted_dates,
            y=sorted_heads,
            colorscale="RdYlGn",
            zmid=0,
            colorbar={"title": "Delta Assigned"},
        )
    )
    fig.update_layout(
        title="Before vs After Slot Coverage Delta (Green = Improved, Red = Degraded)",
        xaxis_title="Date",
        yaxis_title="Activity Head",
        height=420,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return fig


def create_solver_log_timeline_chart(parsed_log: dict[str, object]) -> go.Figure:
    """Bar chart of solver log stage durations / line volume."""
    stages = parsed_log.get("stages", [])
    if not stages:
        fig = go.Figure()
        fig.update_layout(title="No Stage Headers Found in Solver Log")
        return fig

    names = [str(s["Stage"]) for s in stages]
    durations = [float(s.get("Duration (s)", 0.0)) for s in stages]
    lines = [int(s.get("Log Lines", 0)) for s in stages]

    fig = go.Figure()
    if any(d > 0 for d in durations):
        fig.add_trace(go.Bar(name="Reported Duration (s)", x=names, y=durations, marker_color="#2563eb"))
        yaxis_title = "Seconds"
    else:
        fig.add_trace(go.Bar(name="Log Lines", x=names, y=lines, marker_color="#6366f1"))
        yaxis_title = "Log Lines"

    fig.update_layout(
        title="Solver Log Stage Breakdown",
        xaxis_title="Stage",
        yaxis_title=yaxis_title,
        height=320,
        margin={"l": 20, "r": 20, "t": 50, "b": 40},
    )
    return _apply_chart_theme(fig)
