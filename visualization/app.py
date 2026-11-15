"""Streamlit entry point for the Railway Crew Rostering & Gap-Filling Dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from visualization.analytics import (  # noqa: E402
    compute_crew_workload_analytics,
    compute_resilience_and_pool_analytics,
    compute_skill_and_currency_radar,
)
from visualization.data_loader import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    DEFAULT_CPSAT_DIR,
    DEFAULT_DATA_DIR,
    DEFAULT_OPTIONS_DIR,
    DashboardDataset,
    load_dashboard_dataset,
)
from visualization.gap_analysis import parse_summary_and_validation  # noqa: E402
from visualization.metrics import build_demand_slot_records  # noqa: E402
from visualization.views.diagnostics import (  # noqa: E402
    render_constraint_diagnostics,
    render_skill_currency_radar,
    render_strategy_comparison,
    render_workload_chains_depots,
)
from visualization.views.input_readiness import render_input_readiness  # noqa: E402
from visualization.views.overview import (  # noqa: E402
    render_crew_assignment,
    render_demand_coverage,
    render_gap_analysis,
    render_overview,
)
from visualization.views.pipeline import render_pipeline_and_exports  # noqa: E402
from visualization.views.simulator import render_simulator  # noqa: E402
from visualization.views.solver_log_viewer import render_solver_log_visualizer  # noqa: E402

PRESET_OPTIONS = [
    "Full v2 Roster (CP-SAT/outputs/roster_full)",
    "Edge-Case Demo: Strategy None",
    "Edge-Case Demo: Strategy Weighted",
    "Edge-Case Demo: Strategy Lexicographic",
    "Edge-Case Demo: Residential Start Restriction Off",
    "Edge-Case Demo: Relief Transition Off",
    "Edge-Case Demo: Tight Shift Limits (Active)",
    "Edge-Case Demo: Tight Shift Limits (Inactive)",
    "Custom Paths",
]


def resolve_preset_paths(preset: str) -> tuple[Path, Path, Path, Path, Path]:
    """Return (data_dir, cpsat_dir, options_dir, config_path, base_roster_input) for a preset."""
    demo_root = ROOT / "CP-SAT" / "outputs" / "edge_case_demo"
    demo_roster = demo_root / "roster_full_gaps.csv"
    v2_roster = ROOT / "gap_generation" / "output" / "roster_full.csv"

    mapping = {
        "Full v2 Roster (CP-SAT/outputs/roster_full)": (
            DEFAULT_DATA_DIR,
            DEFAULT_CPSAT_DIR,
            DEFAULT_OPTIONS_DIR,
            DEFAULT_CONFIG_PATH,
            v2_roster if v2_roster.exists() else DEFAULT_CPSAT_DIR / "roster_full.csv",
        ),
        "Edge-Case Demo: Strategy None": (
            demo_root / "data",
            demo_root / "run_1_strategy_none" / "cpsat",
            demo_root / "run_1_strategy_none" / "options",
            demo_root / "run_1_strategy_none" / "config.yml",
            demo_roster,
        ),
        "Edge-Case Demo: Strategy Weighted": (
            demo_root / "data",
            demo_root / "run_2_strategy_weighted" / "cpsat",
            demo_root / "run_2_strategy_weighted" / "options",
            demo_root / "run_2_strategy_weighted" / "config.yml",
            demo_roster,
        ),
        "Edge-Case Demo: Strategy Lexicographic": (
            demo_root / "data",
            demo_root / "run_3_strategy_lexicographic" / "cpsat",
            demo_root / "run_3_strategy_lexicographic" / "options",
            demo_root / "run_3_strategy_lexicographic" / "config.yml",
            demo_roster,
        ),
        "Edge-Case Demo: Residential Start Restriction Off": (
            demo_root / "data",
            demo_root / "run_4_residential_start_off" / "cpsat",
            demo_root / "run_4_residential_start_off" / "options",
            demo_root / "run_4_residential_start_off" / "config.yml",
            demo_roster,
        ),
        "Edge-Case Demo: Relief Transition Off": (
            demo_root / "data",
            demo_root / "run_5_relief_transition_off" / "cpsat",
            demo_root / "run_5_relief_transition_off" / "options",
            demo_root / "run_5_relief_transition_off" / "config.yml",
            demo_roster,
        ),
        "Edge-Case Demo: Tight Shift Limits (Active)": (
            demo_root / "run_6_shift_limits_tight_on" / "data",
            demo_root / "run_6_shift_limits_tight_on" / "cpsat",
            demo_root / "run_6_shift_limits_tight_on" / "options",
            demo_root / "run_6_shift_limits_tight_on" / "config.yml",
            demo_roster,
        ),
        "Edge-Case Demo: Tight Shift Limits (Inactive)": (
            demo_root / "run_7_shift_limits_tight_off" / "data",
            demo_root / "run_7_shift_limits_tight_off" / "cpsat",
            demo_root / "run_7_shift_limits_tight_off" / "options",
            demo_root / "run_7_shift_limits_tight_off" / "config.yml",
            demo_roster,
        ),
    }
    return mapping[preset]


def _dataset_mtime_signature(
    data_dir: Path,
    cpsat_dir: Path,
    options_dir: Path,
    config_path: Path,
) -> tuple[tuple[str, float], ...]:
    files = [
        cpsat_dir / "roster_full.csv",
        cpsat_dir / "reassignments.csv",
        cpsat_dir / "unfilled_gaps.csv",
        cpsat_dir / "summary.md",
        cpsat_dir / "validation.md",
        cpsat_dir / "solver.log",
        data_dir / "constraints_df.csv",
        data_dir / "activity_priority.csv",
        data_dir / "assignment_type_priority.csv",
        data_dir / "compliance_matrix_df.csv",
        data_dir / "crew_competencies_df.csv",
        data_dir / "crew_restrictions.csv",
        data_dir / "excluded_activities.csv",
        data_dir / "Crew_Onsite_App.csv",
        data_dir / "roster_df.csv",
        data_dir / "roster_checks.md",
        options_dir / "gap_options.csv",
        config_path,
    ]
    sig: list[tuple[str, float]] = []
    for p in files:
        try:
            sig.append((str(p), p.stat().st_mtime))
        except OSError:
            sig.append((str(p), -1.0))
    return tuple(sig)


@st.cache_data(show_spinner=False)
def _cached_load_dataset(
    data_dir_str: str,
    cpsat_dir_str: str,
    options_dir_str: str,
    config_path_str: str,
    name: str,
    _mtime_sig: tuple[tuple[str, float], ...],
) -> DashboardDataset:
    return load_dashboard_dataset(
        data_dir=Path(data_dir_str),
        cpsat_dir=Path(cpsat_dir_str),
        options_dir=Path(options_dir_str),
        config_path=Path(config_path_str),
        name=name,
    )


@st.cache_data(show_spinner=False)
def _cached_demand_slots(
    _dataset: DashboardDataset,
    _mtime_sig: tuple[tuple[str, float], ...],
) -> list[dict[str, object]]:
    return build_demand_slot_records(_dataset)


@st.cache_data(show_spinner=False)
def _cached_workload(
    _dataset: DashboardDataset,
    _mtime_sig: tuple[tuple[str, float], ...],
) -> dict[str, object]:
    return compute_crew_workload_analytics(_dataset)


@st.cache_data(show_spinner=False)
def _cached_resilience(
    _dataset: DashboardDataset,
    _mtime_sig: tuple[tuple[str, float], ...],
) -> dict[str, object]:
    return compute_resilience_and_pool_analytics(_dataset)


@st.cache_data(show_spinner=False)
def _cached_radar(
    _dataset: DashboardDataset,
    _mtime_sig: tuple[tuple[str, float], ...],
) -> dict[str, object]:
    return compute_skill_and_currency_radar(_dataset)


def main() -> None:
    st.set_page_config(
        page_title="OptiFlux Crew Rostering & Gap-Filling Dashboard",
        layout="wide",
    )
    st.markdown(
        """
        <style>
        .main-hero {
            padding: 14px 20px;
            border-radius: 12px;
            background: linear-gradient(135deg, #1e3a8a 0%, #0f766e 55%, #059669 100%);
            color: #ffffff;
            margin-bottom: 12px;
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.12);
        }
        .main-hero h1 {
            margin: 0;
            font-size: 1.65rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            color: #ffffff;
        }
        .main-hero p {
            margin: 4px 0 0 0;
            font-size: 0.9rem;
            color: rgba(255, 255, 255, 0.88);
        }
        div[data-testid="stMetric"] {
            background: #ffffff !important;
            background-color: #ffffff !important;
            border: 1px solid #cbd5e1 !important;
            border-left: 4px solid #2563eb !important;
            border-radius: 10px !important;
            padding: 12px 15px !important;
            box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08) !important;
        }
        div[data-testid="stMetric"] *,
        div[data-testid="stMetricLabel"] *,
        div[data-testid="stMetricValue"] *,
        div[data-testid="stMetricDelta"] * {
            color: #0f172a !important;
            opacity: 1 !important;
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: unset !important;
        }
        div[data-testid="stMetricLabel"] p,
        div[data-testid="stMetricLabel"] label {
            color: #334155 !important;
            font-weight: 600 !important;
        }
        div[data-testid="stMetricValue"] {
            color: #0f172a !important;
            font-weight: 700 !important;
        }
        div[data-testid="stMetricDelta"] {
            color: #1e293b !important;
            font-weight: 600 !important;
        }
        div[data-testid="stMetric"] svg {
            color: #475569 !important;
            fill: #475569 !important;
        }
        .exec-banner {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
            padding: 10px 14px;
            border-radius: 10px;
            background: linear-gradient(90deg, rgba(37,99,235,0.08), rgba(16,185,129,0.08));
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-left: 4px solid #2563eb;
            margin-bottom: 16px;
            font-size: 0.88rem;
        }
        .status-pill {
            display: inline-block;
            padding: 2px 9px;
            border-radius: 999px;
            font-weight: 600;
            font-size: 0.8rem;
        }
        .pill-blue { background: rgba(37, 99, 235, 0.14); color: #1d4ed8; }
        .pill-green { background: rgba(16, 185, 129, 0.16); color: #047857; }
        .pill-amber { background: rgba(245, 158, 11, 0.18); color: #b45309; }
        .pill-purple { background: rgba(139, 92, 246, 0.15); color: #6d28d9; }
        button[data-baseweb="tab"] {
            font-weight: 600;
            border-radius: 8px 8px 0 0;
        }
        </style>
        <div class="main-hero">
            <h1>OptiFlux Railway Crew Rostering &amp; Gap-Filling Dashboard</h1>
            <p>End-to-End Workforce Readiness, CP-SAT Optimization Analytics, What-If Simulation &amp; Live Solver Diagnostics</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.header("Data Source & Controls")
    preset = st.sidebar.selectbox("Dataset Preset", options=PRESET_OPTIONS)

    if preset == "Custom Paths":
        data_dir = Path(st.sidebar.text_input("Data Directory", str(DEFAULT_DATA_DIR)))
        cpsat_dir = Path(st.sidebar.text_input("CP-SAT Output Directory", str(DEFAULT_CPSAT_DIR)))
        options_dir = Path(st.sidebar.text_input("Option Generation Directory", str(DEFAULT_OPTIONS_DIR)))
        config_path = Path(st.sidebar.text_input("Config File Path", str(DEFAULT_CONFIG_PATH)))
        v2_roster = ROOT / "gap_generation" / "output" / "roster_full.csv"
        base_roster_input = v2_roster if v2_roster.exists() else cpsat_dir / "roster_full.csv"
    else:
        data_dir, cpsat_dir, options_dir, config_path, base_roster_input = resolve_preset_paths(preset)

    if not base_roster_input.exists():
        base_roster_input = cpsat_dir / "roster_full.csv"

    if st.sidebar.button("Refresh Solver Outputs"):
        st.cache_data.clear()

    mtime_sig = _dataset_mtime_signature(data_dir, cpsat_dir, options_dir, config_path)
    try:
        dataset = _cached_load_dataset(
            str(data_dir),
            str(cpsat_dir),
            str(options_dir),
            str(config_path),
            preset,
            mtime_sig,
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
            "0. Input Data & Readiness",
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
            "11. Solver Log Explorer",
        ],
        index=1,
    )

    all_slots = _cached_demand_slots(dataset, mtime_sig)
    all_heads = sorted({str(s["Activity Head"]) for s in all_slots})
    all_swings = sorted(
        {r.get("Swing", "").strip() for r in dataset.roster_rows if r.get("Swing", "").strip()},
        key=lambda x: (0, int(x)) if x.isdecimal() else (1, x),
    )
    all_dates = sorted({str(s["Date"]) for s in all_slots})
    all_shifts = sorted({str(s["Shift"]) for s in all_slots})
    parsed_meta = parse_summary_and_validation(dataset)

    strat_lbl = str(dataset.config_flags.get("priority_strategy", "none"))
    res_lbl = "ON" if dataset.config_flags.get("residential_start_restriction", True) else "OFF"
    rel_lbl = "ON" if dataset.config_flags.get("relief_only_day_night_transition", True) else "OFF"
    atp_lbl = dataset.constraints.get("Assignment Type Priority", ("", "Active"))[1]
    val_lbl = parsed_meta.get("validation_headline") or "N/A"
    res_cls = "pill-green" if res_lbl == "ON" else "pill-amber"
    rel_cls = "pill-green" if rel_lbl == "ON" else "pill-amber"
    atp_cls = "pill-green" if atp_lbl == "Active" else "pill-amber"
    st.markdown(
        f"<div class='exec-banner'>"
        f"<span class='status-pill pill-blue'>Dataset: {preset}</span>"
        f"<span class='status-pill pill-purple'>Strategy: {strat_lbl}</span>"
        f"<span class='status-pill {res_cls}'>Res Start: {res_lbl}</span>"
        f"<span class='status-pill {rel_cls}'>Relief D/N: {rel_lbl}</span>"
        f"<span class='status-pill {atp_cls}'>Type Priority: {atp_lbl}</span>"
        f"<span class='status-pill pill-blue'>Validation: {val_lbl}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if section == "0. Input Data & Readiness":
        render_input_readiness(dataset)
    elif section == "1. Overview":
        render_overview(dataset, all_slots, parsed_meta)
    elif section == "2. Demand vs Coverage":
        render_demand_coverage(dataset, all_heads, all_swings, all_dates, all_shifts)
    elif section == "3. Crew Assignment":
        render_crew_assignment(dataset, all_heads, all_swings)

    # =========================================================================
    # SECTION 4: GAP-FILLING ANALYSIS
    # =========================================================================
    elif section == "4. Gap Analysis":
        render_gap_analysis(dataset, all_heads, all_swings)
    elif section == "5. Constraint Diagnostics":
        render_constraint_diagnostics(dataset, parsed_meta)
    elif section == "6. Strategy Comparison":
        render_strategy_comparison(ROOT)
    elif section == "7. Workload, Chains & Depots":
        render_workload_chains_depots(
            dataset,
            parsed_meta,
            workload_fn=lambda ds: _cached_workload(ds, mtime_sig),
            resilience_fn=lambda ds: _cached_resilience(ds, mtime_sig),
        )
    elif section == "8. Skill & Currency Radar":
        render_skill_currency_radar(
            dataset,
            radar_fn=lambda ds: _cached_radar(ds, mtime_sig),
        )
    elif section == "9. What-If & Disruption Simulator":
        render_simulator(dataset, config_path, base_roster_input, preset)
    elif section == "10. Pipeline, Tests & Exports":
        render_pipeline_and_exports(dataset, all_slots, preset)
    elif section == "11. Solver Log Explorer":
        st.subheader("Solver Execution Log Explorer")
        active_log = st.session_state.get("last_solver_log") or dataset.solver_log_text
        render_solver_log_visualizer(active_log, title="Captured Solver & Pipeline Log Analysis", key_prefix="nav_log")


if __name__ == "__main__":
    main()
