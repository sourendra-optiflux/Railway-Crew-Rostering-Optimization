"""Input Data & Pre-Solver Readiness view."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import streamlit as st

from visualization.analytics import compute_input_readiness_analytics
from visualization.charts import (
    create_competency_bottleneck_chart,
    create_daily_supply_vs_demand_chart,
)
from visualization.data_loader import ROOT, DashboardDataset
from visualization.export_utils import rows_to_csv_bytes


def _discover_stage_files(dataset: DashboardDataset) -> dict[str, dict[str, Path]]:
    """Map every pipeline stage to its readable CSV, Markdown, YAML, and Log files."""
    gap_dir = ROOT / "gap_generation" / "output"
    stage0_files: dict[str, Path] = {}
    if dataset.data_dir.exists():
        for p in sorted(dataset.data_dir.glob("*.csv")):
            stage0_files[f"{p.name} (Input CSV)"] = p
    cfg_file = ROOT / "config.yml"
    if cfg_file.exists():
        stage0_files[f"{cfg_file.name} (Solver Config YAML)"] = cfg_file

    stage1_files: dict[str, Path] = {}
    if gap_dir.exists():
        for p in sorted(gap_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in {".csv", ".md", ".txt", ".log"}:
                stage1_files[f"{p.name} (Gap Gen)"] = p

    stage2_files: dict[str, Path] = {}
    if dataset.options_dir is not None and dataset.options_dir.exists():
        for p in sorted(dataset.options_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in {".csv", ".md", ".txt", ".log"}:
                stage2_files[f"{p.name} (Option Gen)"] = p

    stage3_files: dict[str, Path] = {}
    if dataset.cpsat_dir.exists():
        for p in sorted(dataset.cpsat_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in {".csv", ".md", ".txt", ".log"}:
                stage3_files[f"{p.name} ({dataset.cpsat_dir.name})"] = p

    return {
        "Stage 0: Raw Input Tables & Config (data/optiflux_v2)": stage0_files,
        "Stage 1: Gap Generation Outputs (gap_generation/output)": stage1_files,
        "Stage 2: Option Generation Outputs (option_generation/output)": stage2_files,
        f"Stage 3: CP-SAT Solver Outputs ({dataset.cpsat_dir.name})": stage3_files,
    }


def _read_csv_with_headers(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _write_csv_with_headers(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def render_input_readiness(dataset: DashboardDataset) -> None:
    """Render Section 0: Input Data Explorer & Pre-Solver Readiness."""
    st.subheader("Input Data Explorer & Pre-Solver Readiness")
    st.markdown(
        "Inspect input tables (`roster_df.csv`, `compliance_matrix_df.csv`, `crew_competencies_df.csv`, "
        "`crew_restrictions.csv`, `excluded_activities.csv`, `Crew_Onsite_App.csv`), browse all pipeline stage "
        "artifacts (Stages 0–3), or import/edit input CSV tables directly before running the solver."
    )

    readiness = compute_input_readiness_analytics(dataset)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Crew Master", len(dataset.crew_by_id))
    m2.metric("Invalid / Non-Valid Competencies", len(readiness["invalid_competencies"]))
    m3.metric("Active Crew Restrictions", len(readiness["restrictions"]))
    m4.metric("Onsite Check-In Mismatches", len(readiness["onsite_mismatches"]))

    tab_supply, tab_comp, tab_restrict, tab_onsite, tab_explorer, tab_importer = st.tabs([
        "Pre-Gap Supply vs Demand",
        "Competency & Compliance Matrix",
        "Crew Restrictions & Exclusions",
        "Onsite App Cross-Check",
        "🗂️ Universal File Explorer (Stages 0–3)",
        "📥 CSV Importer & Input Table Editor",
    ])

    with tab_supply:
        st.plotly_chart(
            create_daily_supply_vs_demand_chart(readiness["daily_supply_rows"]),
            use_container_width=True,
            key="ir_daily_supply_chart",
        )
        st.dataframe(readiness["daily_supply_rows"], use_container_width=True, hide_index=True)

    with tab_comp:
        st.plotly_chart(
            create_competency_bottleneck_chart(readiness["competency_matrix"]),
            use_container_width=True,
            key="ir_comp_bottleneck_chart",
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
            st.warning(
                f"Found {len(readiness['onsite_mismatches'])} onsite check-in record(s) with no matching shift in `roster_full.csv`."
            )
            st.dataframe(readiness["onsite_mismatches"], use_container_width=True, hide_index=True)
        else:
            st.success("No onsite check-in mismatches detected.")

    with tab_explorer:
        st.markdown("#### Universal Pipeline Data & Artifact Explorer (Stages 0–3)")
        st.caption(
            "Browse and filter any raw input CSV, intermediate gap/option generation artifact, or CP-SAT solver output table/report."
        )
        stage_map = _discover_stage_files(dataset)
        col_stage, col_file, col_search = st.columns([3, 3, 2])
        with col_stage:
            selected_stage = st.selectbox("1. Select Pipeline Stage", list(stage_map.keys()), key="exp_stage_sel")
        files_in_stage = stage_map.get(selected_stage or "", {})
        with col_file:
            selected_file_label = st.selectbox(
                "2. Select File / Artifact",
                list(files_in_stage.keys()) if files_in_stage else ["No files found"],
                key="exp_file_sel",
            )
        with col_search:
            search_query = st.text_input(
                "3. Filter Rows (Search Text)",
                value="",
                placeholder="Type crew ID, head, date, status...",
                key="exp_search_q",
            )

        target_path = files_in_stage.get(selected_file_label or "")
        if target_path and target_path.exists():
            st.caption(f"**File Path:** `{target_path}` | **Size:** `{target_path.stat().st_size:,} bytes`")
            if target_path.suffix.lower() == ".csv":
                headers, rows = _read_csv_with_headers(target_path)
                filtered_rows = rows
                if search_query.strip():
                    q_low = search_query.strip().lower()
                    filtered_rows = [
                        r for r in rows if any(q_low in str(v).lower() for v in r.values())
                    ]
                f1, f2, f3 = st.columns(3)
                f1.metric("Total Rows", f"{len(rows):,}")
                f2.metric("Matching Filtered Rows", f"{len(filtered_rows):,}")
                f3.metric("Columns", len(headers))
                with st.expander("Column Schema & Sample Values", expanded=False):
                    schema_rows = []
                    sample_row = rows[0] if rows else {}
                    for h in headers:
                        non_empty = sum(1 for r in rows[:500] if str(r.get(h, "")).strip() != "")
                        schema_rows.append({
                            "Column Name": h,
                            "Sample Value (Row 1)": str(sample_row.get(h, "")),
                            "Non-Empty (first 500 rows)": non_empty,
                        })
                    st.dataframe(schema_rows, use_container_width=True, hide_index=True)

                max_rows = st.slider(
                    "Max rows to display in table preview",
                    min_value=100,
                    max_value=max(500, min(10000, len(filtered_rows) or 500)),
                    value=min(1000, max(100, len(filtered_rows) or 100)),
                    step=100,
                    key="exp_max_rows",
                )
                st.dataframe(filtered_rows[:max_rows], use_container_width=True, hide_index=True)
                st.download_button(
                    f"Download {target_path.name} ({len(filtered_rows):,} rows)",
                    data=rows_to_csv_bytes(filtered_rows),
                    file_name=target_path.name,
                    mime="text/csv",
                    key="exp_dl_csv_btn",
                )
            elif target_path.suffix.lower() == ".md":
                md_text = target_path.read_text(encoding="utf-8", errors="replace")
                st.markdown(md_text)
                st.download_button(
                    f"Download {target_path.name}",
                    data=md_text.encode("utf-8"),
                    file_name=target_path.name,
                    mime="text/markdown",
                    key="exp_dl_md_btn",
                )
            else:
                raw_text = target_path.read_text(encoding="utf-8", errors="replace")
                st.code(raw_text)
                st.download_button(
                    f"Download {target_path.name}",
                    data=raw_text.encode("utf-8"),
                    file_name=target_path.name,
                    mime="text/plain",
                    key="exp_dl_txt_btn",
                )

    with tab_importer:
        st.markdown("#### CSV Input Table Importer & In-Place Editor (`data/optiflux_v2/`)")
        st.caption(
            "Edit any pre-solver input table directly in the browser or upload a replacement CSV file before running "
            "Gap Generation, Option Generation, or the CP-SAT Solver."
        )
        input_csvs = sorted(dataset.data_dir.glob("*.csv")) if dataset.data_dir.exists() else []
        csv_map = {p.name: p for p in input_csvs}
        selected_csv_name = st.selectbox(
            "Select Input Table to Edit or Replace",
            list(csv_map.keys()),
            index=list(csv_map.keys()).index("constraints_df.csv") if "constraints_df.csv" in csv_map else 0,
            key="imp_table_select",
        )
        selected_csv_path = csv_map.get(selected_csv_name or "")

        if selected_csv_path and selected_csv_path.exists():
            headers, current_rows = _read_csv_with_headers(selected_csv_path)
            col_up, col_ed = st.columns([1, 2])
            with col_up:
                st.markdown("##### Option A: Upload / Import CSV")
                uploaded = st.file_uploader(
                    f"Upload replacement for `{selected_csv_name}`",
                    type=["csv"],
                    key=f"upload_{selected_csv_name}",
                )
                if uploaded is not None:
                    content = uploaded.getvalue().decode("utf-8-sig", errors="replace")
                    up_reader = csv.DictReader(io.StringIO(content))
                    up_headers = list(up_reader.fieldnames or [])
                    up_rows = list(up_reader)
                    missing_cols = [c for c in headers if c not in up_headers]
                    if missing_cols:
                        st.error(f"Uploaded CSV is missing required columns: {', '.join(missing_cols)}")
                    else:
                        st.success(f"Validated `{uploaded.name}`: {len(up_rows):,} rows, {len(up_headers)} columns.")
                        if st.button(f"Apply Uploaded CSV to `{selected_csv_name}`", type="primary", key="apply_upload_btn"):
                            _write_csv_with_headers(selected_csv_path, up_headers, up_rows)
                            st.cache_data.clear()
                            st.success(f"Saved `{selected_csv_name}` ({len(up_rows):,} rows)!")

            with col_ed:
                st.markdown(f"##### Option B: Interactive Table Editor (`{selected_csv_name}`)")
                if len(current_rows) <= 2000:
                    edited_rows = st.data_editor(
                        current_rows,
                        num_rows="dynamic",
                        use_container_width=True,
                        key=f"editor_{selected_csv_name}",
                    )
                    if st.button(f"Save Edits to `{selected_csv_name}`", type="primary", key=f"save_ed_{selected_csv_name}"):
                        _write_csv_with_headers(selected_csv_path, headers, list(edited_rows))
                        st.cache_data.clear()
                        st.success(f"Saved {len(edited_rows):,} rows to `{selected_csv_path}`.")
                else:
                    st.info(
                        f"`{selected_csv_name}` has {len(current_rows):,} rows. Use Option A (CSV Upload) or the "
                        "Universal File Explorer tab to filter and download large tables."
                    )
                    st.dataframe(current_rows[:500], use_container_width=True, hide_index=True)

