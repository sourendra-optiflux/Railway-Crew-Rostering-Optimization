"""Reusable Solver Log Visualizer component."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from visualization.analytics import parse_solver_log_metrics
from visualization.charts import create_solver_log_timeline_chart


def _style_severity(val: object) -> str:
    s = str(val).upper()
    if s == "ERROR":
        return "background-color: rgba(239, 68, 68, 0.18); color: #b91c1c; font-weight: 700;"
    if s == "WARNING":
        return "background-color: rgba(245, 158, 11, 0.20); color: #b45309; font-weight: 700;"
    if s == "STAGE":
        return "background-color: rgba(37, 99, 235, 0.16); color: #1d4ed8; font-weight: 700;"
    return "color: #334155;"


def render_solver_log_visualizer(
    log_text: str,
    title: str = "Solver Log Visualizer",
    key_prefix: str = "solver_log",
) -> None:
    """Visualize solver execution logs with stage breakdown, severity metrics, and color-coded lines."""
    st.markdown(f"#### {title}")
    if not log_text.strip():
        st.info(
            "No solver log captured yet. Run the **What-If Scenario Builder**, **Disruption Simulator**, "
            "or **Full Rostering Pipeline** to capture and visualize live solver logs."
        )
        return

    parsed = parse_solver_log_metrics(log_text)
    sev = parsed["severity_counts"]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Log Lines", parsed["total_lines"])
    c2.metric("Stages", len(parsed["stages"]))
    c3.metric("Warnings", sev.get("WARNING", 0))
    c4.metric("Errors", sev.get("ERROR", 0))
    with c5:
        st.download_button(
            "Download .log",
            data=log_text.encode("utf-8"),
            file_name="solver_run.log",
            mime="text/plain",
            key=f"{key_prefix}_dl",
        )

    if parsed["stages"]:
        st.plotly_chart(create_solver_log_timeline_chart(parsed), use_container_width=True)
        st.dataframe(parsed["stages"], use_container_width=True, hide_index=True)

    f1, f2 = st.columns([2, 1])
    with f1:
        search_q = st.text_input("Search Log Lines", value="", key=f"{key_prefix}_search")
    with f2:
        sev_filter = st.multiselect(
            "Severity Filter",
            options=["STAGE", "INFO", "WARNING", "ERROR"],
            default=["STAGE", "INFO", "WARNING", "ERROR"],
            key=f"{key_prefix}_sev",
        )

    filtered = [
        ln for ln in parsed["lines"]
        if ln["Severity"] in set(sev_filter)
        and (not search_q.strip() or search_q.strip().lower() in str(ln["Message"]).lower())
    ]
    if filtered:
        df_logs = pd.DataFrame(filtered[:500])
        st.dataframe(
            df_logs.style.map(_style_severity, subset=["Severity"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No log lines match the current filter.")

    with st.expander("Raw Solver Log Output", expanded=False):
        st.code(log_text)
