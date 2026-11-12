"""Plotly chart builders for the Crew Rostering & Gap-Filling Dashboard."""

from __future__ import annotations

from collections import defaultdict

import plotly.express as px
import plotly.graph_objects as go


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


def create_crew_gantt_chart(
    timeline_records: list[dict[str, str]],
    color_by: str = "Activity Head",
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

    color_field = (
        color_by
        if color_by in ("Activity Head", "Assignment Type", "Crew Classification", "State", "Changed")
        else "Activity Head"
    )

    fig = px.timeline(
        filtered,
        x_start="Start",
        x_end="End",
        y="Crew Label",
        color=color_field,
        hover_name="Activity Name",
        hover_data={
            "Assignment ID": True,
            "User Id": True,
            "Crew Classification": True,
            "Swing": True,
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
