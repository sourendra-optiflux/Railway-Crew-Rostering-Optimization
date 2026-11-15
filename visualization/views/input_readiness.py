"""Input Data & Pre-Solver Readiness view."""

from __future__ import annotations

import streamlit as st

from visualization.analytics import compute_input_readiness_analytics
from visualization.charts import (
    create_competency_bottleneck_chart,
    create_daily_supply_vs_demand_chart,
)
from visualization.data_loader import DashboardDataset


def render_input_readiness(dataset: DashboardDataset) -> None:
    """Render Section 0: Input Data Explorer & Pre-Solver Readiness."""
    st.subheader("Input Data Explorer & Pre-Solver Readiness")
    st.markdown(
        "Inspect input tables (`roster_df.csv`, `compliance_matrix_df.csv`, `crew_competencies_df.csv`, "
        "`crew_restrictions.csv`, `excluded_activities.csv`, `Crew_Onsite_App.csv`) to spot structural "
        "bottlenecks before optimization."
    )

    readiness = compute_input_readiness_analytics(dataset)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Crew Master", len(dataset.crew_by_id))
    m2.metric("Invalid / Non-Valid Competencies", len(readiness["invalid_competencies"]))
    m3.metric("Active Crew Restrictions", len(readiness["restrictions"]))
    m4.metric("Onsite Check-In Mismatches", len(readiness["onsite_mismatches"]))

    tab_supply, tab_comp, tab_restrict, tab_onsite = st.tabs([
        "Pre-Gap Supply vs Demand",
        "Competency & Compliance Matrix",
        "Crew Restrictions & Exclusions",
        "Onsite App Cross-Check",
    ])

    with tab_supply:
        st.plotly_chart(
            create_daily_supply_vs_demand_chart(readiness["daily_supply_rows"]),
            use_container_width=True,
        )
        st.dataframe(readiness["daily_supply_rows"], use_container_width=True, hide_index=True)

    with tab_comp:
        st.plotly_chart(
            create_competency_bottleneck_chart(readiness["competency_matrix"]),
            use_container_width=True,
        )
        st.markdown("#### Activity Head Competency Compliance Summary")
        st.dataframe(readiness["competency_matrix"], use_container_width=True, hide_index=True)
        st.markdown("#### Non-Valid / Expiring Crew Competencies")
        if readiness["invalid_competencies"]:
            st.dataframe(readiness["invalid_competencies"], use_container_width=True, hide_index=True)
        else:
            st.success("All tracked crew competency records are marked Valid.")

    with tab_restrict:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Crew Restrictions (`crew_restrictions.csv`)")
            if readiness["restrictions"]:
                st.dataframe(readiness["restrictions"], use_container_width=True, hide_index=True)
            else:
                st.info("No crew restrictions recorded in `crew_restrictions.csv`.")
        with c2:
            st.markdown("#### Excluded Activities (`excluded_activities.csv`)")
            if readiness["excluded_activities"]:
                st.dataframe(readiness["excluded_activities"], use_container_width=True, hide_index=True)
            else:
                st.info("No excluded activities recorded in `excluded_activities.csv`.")

    with tab_onsite:
        st.caption(f"Total records in `Crew_Onsite_App.csv`: {readiness['onsite_total']}")
        if readiness["onsite_mismatches"]:
            st.warning(f"Found {len(readiness['onsite_mismatches'])} onsite check-in record(s) with no matching shift in `roster_full.csv`.")
            st.dataframe(readiness["onsite_mismatches"], use_container_width=True, hide_index=True)
        else:
            st.success("No onsite check-in mismatches detected.")
