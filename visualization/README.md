# OptiFlux Crew Rostering & Gap-Filling Visualization Dashboard

Interactive Streamlit dashboard for visualizing and diagnosing Railway Crew Rostering & Gap-Filling solver outputs.

## What the Dashboard Does

The dashboard reads the input dataset (`data/optiflux_v2/`), Layer 1 option generation outputs (`option_generation/output/`), and Layer 2 CP-SAT solver outputs (`CP-SAT/outputs/roster_full/`) to provide six views:

1. **Overview:**
   - KPI cards for **Total Crew Demand**, **Assigned Demand Shifts**, **Unfilled Demand Shifts**, **Overall Demand Coverage (%)**, **Resident Crew Assignments**, and **FIFO Crew Assignments**, plus Gap-Filling Recovery KPIs (total leave gaps, open gaps, filled gaps, and locked gaps).
   - **Solver Stage & Rule Validation Banner** showing each CP-SAT objective stage (`OPTIMAL` / `FEASIBLE`) and the 44 rule validation status headline (`0 unexpected failure(s)`).
   - Activity Head-wise and Swing-wise coverage summary tables and Resident vs FIFO contribution bar chart.
2. **Demand vs Coverage Heatmap:**
   - Interactive Plotly heatmap (`Activity Head` rows ordered by priority vs `Date`, `Shift`, or `Date + Shift` columns).
   - Color-coded cells: **Green** (Fully covered), **Yellow** (Partially covered), **Red** (Completely unfilled), displaying `Demand / Assigned / Gap` on each cell and full details on hover.
   - Includes a **"Show Only Leave-Disrupted / Gap Slots"** toggle to focus strictly on leave recovery slots (`296` leave gaps) rather than scanning across all `5,130` horizon shifts.
   - Filters for Activity Head, Swing, Crew Classification, Date, and Shift.
3. **Crew Assignment Gantt Chart:**
   - Interactive timeline of **actual selected solver assignments** from `roster_full.csv` (never unselected options from `options.csv`).
   - Includes a **"Show Only Reassigned / Moved Crew"** toggle and a `"Changed"` color mode (`Reassigned / Moved` vs `Unchanged`) with full before/after `Reassignment Detail` in the tooltip.
   - Differentiates `Residential` and `FIFO` crew and optionally shows `Off` / `Travel` rows and unassigned on-leave periods.
4. **Gap-Filling Analysis:**
   - Detailed table of unfilled demand slots (`Activity Head`, `Priority`, `Swing`, `Date`, `Shift`, `Total Demand`, `Assigned Demand`, `Remaining Gap`, `Resident/FIFO Assigned`, `Locked Gaps`, and `Diagnostic Category`).
   - Interactive **"Where Did the Layer-1 Candidates Go?" Seat Inspector**: select any unfilled `Seat Key` to see what every Layer-1 candidate from `gap_options.csv` actually did in the final `roster_full.csv` / `reassignments.csv` solution alongside the exact `rejections.csv` breakdown for that seat.
   - Summary charts for Remaining Gaps by Activity Head, by Shift, by Priority, and Resident vs FIFO contribution.
5. **Constraint & Diagnostic Analysis:**
   - Displays active rule and constraint settings (`Max Resident Shifts` / `Max FIFO Shifts` from `activity_priority.csv` and `Activity Head Max Shifts` status in `constraints_df.csv`, `Residential Start Restriction`, `Relief Only Day/Night Transition`, rest hours, and F3 start-time change limits).
   - Interactive **Per-Swing Activity-Head Shift Utilization vs Configured Limits Bar Chart** and a filterable table for swings reaching their shift limit.
   - Summarizes `swings.csv` availability (`movable` vs `frozen`), `rejections.csv` Layer-1 rejection counts, and the **44 Roster Validation Rule Checks** (`PASS` / `fails after leave too` / `FAIL`).
6. **Optimization Strategy Comparison:**
   - Compares `None`, `Weighted`, and `Lexicographic` strategy runs across total assigned demand, remaining gaps, coverage %, Activity Head-wise coverage, and Priority-wise coverage.

---

## Required Input & Output Files

| Layer | Default Location | Files Consumed |
|---|---|---|
| Base Data | `data/optiflux_v2/` | `activity_demand_df.csv`, `activity_priority.csv`, `crew_master_data_df.csv`, `constraints_df.csv` |
| Config | `config.yml` | `residential_start_restriction`, `relief_only_day_night_transition`, `priority_strategy` |
| Layer 1 (Option Generation, optional for diagnostics) | `option_generation/output/` | `seats.csv`, `swings.csv`, `gap_options.csv`, `rejections.csv` |
| Layer 2 (CP-SAT Solver Output) | `CP-SAT/outputs/roster_full/` | `roster_full.csv`, `reassignments.csv`, `unfilled_gaps.csv`, `summary.md`, `validation.md` |

---

## Dependencies & Installation

Install the project with the `dashboard` extra (or install `streamlit` and `plotly` into the virtual environment):

```powershell
.\.venv\Scripts\pip.exe install -e ".[dashboard]"
```

---

## How to Run the Solver & Launch the Dashboard

### 1. Run the Optimization Pipeline

```powershell
# Generate leave gaps, candidate options, and solve with CP-SAT:
.\.venv\Scripts\python.exe gap_generation/make_gaps.py
.\.venv\Scripts\python.exe option_generation/generate_options.py --config config.yml
.\.venv\Scripts\python.exe CP-SAT/run_gap_filling.py --config config.yml

# (Optional) Generate multi-strategy and edge-case comparison runs:
.\.venv\Scripts\python.exe scripts/edge_case_demo.py
```

### 2. Launch the Dashboard

```powershell
.\.venv\Scripts\streamlit.exe run visualization/app.py
```

---

## Current Limitations Regarding Constraint Diagnostics

- **No Speculative Attribution:** The dashboard strictly reports only explicit evidence exported by the pipeline:
  1. **Locked Gaps (`Is_locked_gap = True`):** Explicitly identified from `roster_full.csv` / `unfilled_gaps.csv` for shifts before `Solver Start Date` (`G1`).
  2. **Zero Layer-1 Candidates:** When `gap_options.csv` has `0` candidate options for an open seat, the dashboard displays the exact Layer-1 rejection counts recorded in `rejections.csv` for that `Seat Key` (e.g., `not certified (eligibility matrix)`, `start change beyond +-1 h (F1)`, `Residential crew cannot start between 22:00 and 02:00`, `no legal sequence in the swing`).
  3. **Unselected Layer-1 Candidates in CP-SAT:** When `gap_options.csv` contains one or more legal candidate options for a seat, but that seat remains unfilled after the global CP-SAT solve (for instance, because candidate crew were used on other seats or constrained by swing-level limits), CP-SAT does not export a per-seat conflict proof. In those cases, the dashboard explicitly states that candidate options existed in Layer 1 and that the exact global solver conflict reason is not exported.
