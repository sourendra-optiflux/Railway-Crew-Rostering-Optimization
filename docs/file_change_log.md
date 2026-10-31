# File Change Log

Record of every file created or modified on branch `claude/youthful-davinci-ix84gg`
relative to the starting commit `ac0ed62` ("Add crew rostering problem
specification"). **No file was deleted or moved.** The original problem
document, both V1 notebooks and both PDFs are unchanged.

## Unchanged (preserved)

| File | Note |
|---|---|
| `Optiflux_crew_rostering_problem.md` | Primary source of requirements |
| `railway_crew_v1.ipynb`, `rostering_v1_sheets.ipynb` | Kept at the root because their Colab badges link to these paths. Their model and data are reproduced by `data/sample/v1_toy` and `tests/test_known_optimal.py` |
| `Papers/tabu_search_approach.pdf`, `Progress/CP_SAT_vs_MIP_Solvers.pdf` | Research material, summarised in `initial_assessment.md` §3 |

## Modified

| File | Why | What changed |
|---|---|---|
| `README.md` | It described only the V1 notebook | Now the entry point: what the project is, quick start, supported rules, outputs, results summary, links to every guide. Kept the V1 history, privacy note and disclaimer. |

## Created — package `src/railway_rostering/`

| File | Purpose / responsibilities | Interacts with | Verified by | Limitations / follow-up |
|---|---|---|---|---|
| `__init__.py`, `__main__.py` | Public API (`load_instance`, `solve_instance`, `write_outputs`, ...), `python -m railway_rostering` | all | every test imports it | — |
| `domain.py` | Dataclasses `Crew`, `Duty`, `TravelLink`, `Instance`, `Assignment`, `Solution`; enums; clock helpers | everything | `test_data_loader.py` | — |
| `config.py` | `ModelConfig` (every rule switch, with source status) and `SolverConfig`; JSON loading; `validate()` | all modules | `test_data_loader.py::test_config_validation_rejects_unknown_values` and every rule test | Defaults reflect assumptions listed in `assumptions_and_open_questions.md` |
| `data_loader.py` | Parse/write the CSV schema and the legacy V1 format; collects all errors | `domain`, CLI, generator | `test_data_loader.py` | CSV only (no Excel); timestamps without time zones |
| `validation.py` | Input consistency: errors stop the run, warnings list skipped rules | `solve` | `test_data_loader.py` | — |
| `constraints/__init__.py` | Explains the two kinds of constraint code | — | — | — |
| `constraints/eligibility.py` | Activity table ∩ per-duty list; exact activity match | `candidate_generation` | `test_eligibility.py` | No route/vehicle dimensions (none in the data) |
| `constraints/time_rest.py` | DAY/NIGHT classification, transitions, 11 h / 23 h rest | `candidate_generation`, `assignment` | `test_time_rest.py` | Day window is an assumption |
| `constraints/location.py` | Continuity, single-leg positioning, via-base connections | `candidate_generation` | `test_location.py`, `test_base_return.py` | No multi-hop routing, no capacity |
| `constraints/swing_rules.py` | Swing calendar, leave, lift-up/layback, persistence policies | `candidate_generation` | `test_swing_rules.py` | Persistence semantics unconfirmed (Q-CREW-5) |
| `constraints/base_return.py` | When the crew member must pass through base | `candidate_generation` | `test_base_return.py` | Approximation; no deadline |
| `constraints/co_rules.py` | CO hook points, disabled | `candidate_generation`, `reporting` | (no rule to test) | Needs the CO definition (Q-CO-1 … 4) |
| `constraints/sequencing.py` | `AddCircuit` per crew member, redundant flow rows | `model` | `test_known_optimal.py` (brute force), `test_end_to_end.py` (MIP agreement) | — |
| `constraints/assignment.py` | Demand/coverage, fixed assignments, daily cap, redundant cliques | `model`, `lp_bound` | `test_assignment_demand.py` | — |
| `candidate_generation.py` | Nodes, arcs, pruning, per-duty diagnostics and reason codes | constraints, `model`, `heuristics`, `lp_bound`, `reporting` | all rule tests | Quadratic arcs per crew member |
| `model.py` | Builds the CP-SAT model | `sequencing`, `assignment` | all solve tests | — |
| `objective.py` | Objective levels, trivial-level detection, weighted mode | `solve`, `lp_bound` | `test_objective.py` | Priority weights are assumptions |
| `lp_bound.py` | GLOP relaxation → valid integer bound cut per stage | `solve` | `test_objective.py::test_lp_cut_never_changes_the_optimum` | Helps only when the LP is tight (see `tight` preset) |
| `heuristics.py` | Greedy roster, used as baseline and hint | `solve` | `test_end_to_end.py::test_greedy_routes_are_legal` | No quality guarantee |
| `solve.py` | Pipeline, lexicographic stages, LP cuts, extraction, status logic | everything | `test_end_to_end.py` and all solve tests | Time limit applies per stage |
| `solution_validation.py` | **Independent** validator (imports only `domain`, `config`) | `solve`, CLI `validate`, generator, tests | `test_solution_validation.py` (positive and 17 negative cases, plus the import-independence check) | CO rules not validated (none enforced) |
| `reporting.py` | Output CSV/JSON, rule-status table, console summary | `solve`, CLI | `test_end_to_end.py` | — |
| `mip_crosscheck.py` | Flow MIP on the same arcs (SCIP/HiGHS) | tests, `benchmark` | `test_end_to_end.py::test_flow_mip_agrees_with_cp_sat` | Partial-demand mode only |
| `synthetic.py` | Reproducible generator, activity catalogue, presets | CLI, `benchmark`, tests | `test_end_to_end.py` (determinism, committed data, legality of existing assignments, synthetic flag) | No timetable structure |
| `benchmark.py` | Runs presets × variants, writes results tables | CLI | run manually (`validation_report.md`) | — |
| `cli.py` | `generate`, `solve`, `validate`, `benchmark` | everything | `test_end_to_end.py` | — |

## Created — scripts, data, notebooks

| File | Purpose |
|---|---|
| `scripts/_bootstrap.py` | Puts `src/` on `sys.path` so the scripts run without installation |
| `scripts/run_example.py` | `solve` wrapper; defaults to `data/sample/briefing_abc` → `outputs/example` |
| `scripts/generate_synthetic_instance.py` | `generate` wrapper; defaults to all presets |
| `scripts/benchmark.py` | `benchmark` wrapper |
| `data/sample/v1_toy/{crew,duties}.csv`, `instance.json` | V1 notebook data in the legacy format (known answer 5/5) |
| `data/sample/briefing_abc/{crew,duties,eligibility}.csv`, `instance.json` | Briefing ABC example (known answer 6/6) |
| `data/generated/{small,medium,tight,large,xlarge}/` | Synthetic presets (`crew.csv`, `duties.csv`, `eligibility.csv`, `travel.csv`, `instance.json`), regenerable byte-for-byte |
| `notebooks/exploratory_analysis.ipynb` | Instance statistics and the candidate-filter funnel; calls the package |
| `notebooks/solution_visualization.ipynb` | Solves and draws Gantt charts, uncovered reasons, offsets; calls the package |

## Created — tests (`tests/`, 171 tests)

| File | Covers |
|---|---|
| `conftest.py`, `helpers.py` | Path setup; tiny-instance builders; brute-force enumerator |
| `test_data_loader.py` | Parsing, legacy format, header stripping, error collection, round trip, input-validation errors and warnings, config validation |
| `test_eligibility.py` | Exact activity match, table ∩ list, no-information case, briefing example |
| `test_assignment_demand.py` | Multi-crew demand, partial vs all-or-nothing, uniqueness, existing assignments (fixed / reassignable), infeasible input roster |
| `test_time_rest.py` | Overlap; 11 h and 23 h exact boundaries; transition only when the shift changes; classification window; prior duty and next commitment boundaries; midnight crossing; daily cap |
| `test_location.py` | No teleporting; continuity; initial location; positioning timing boundaries; positioning cost |
| `test_swing_rules.py` | 6/6 calendar; type defaults; offsets ±60 only; the EFG patterns under both policies; reset in a new swing; pre-horizon change; Relief example; leave |
| `test_base_return.py` | Swing-end base, swing beyond the horizon, between swings, transition with and without positioning, ABC sequence |
| `test_known_optimal.py` | V1 instances (5 and 4), briefing ABC (6, plus the transition-day duty rejected), CP-SAT note 3-duty example (1), **40 random brute-force comparisons** |
| `test_solution_validation.py` | A valid roster passes; 17 injected violation types are each detected; validator independence |
| `test_objective.py` | Priority tie-break and order, weighted = lexicographic, time-change minimisation, trivial-level skipping, LP cut invariance |
| `test_end_to_end.py` | CLI solve/validate/legacy files/overrides; outputs; reason codes; script from a fresh checkout; generator determinism; committed data matches the generator; greedy legality; flow MIP agreement |

## Created — repository infrastructure and docs

| File | Purpose |
|---|---|
| `pyproject.toml` | Package metadata, `railway-rostering` entry point, pytest and ruff settings |
| `requirements.txt` | `ortools`, `pytest`, optional `pandas`/`matplotlib` |
| `.gitignore` | Python caches, `outputs/`, `data/private/`, `data/real/` (keeps real data out of Git) |
| `.github/workflows/tests.yml` | CI on Python 3.10 and 3.12: ruff, pytest, CLI smoke tests |
| `docs/initial_assessment.md` | Audit of the starting repository and plan |
| `docs/dataset_research.md` | Public dataset search, evidence levels, licences, decision |
| `docs/dataset_design.md` | Input schema, sample instances, generator design and presets |
| `docs/problem_formulation.md` | Mathematical model mapped to code |
| `docs/assumptions_and_open_questions.md` | Rule-by-rule source vs implementation table; open questions |
| `docs/model_architecture.md` | Design decisions, alternatives, performance investigation |
| `docs/codebase_guide.md` | Top-down tour of the code |
| `docs/running_experiments.md` | Copy-paste commands |
| `docs/validation_report.md` | Actual test and benchmark results |
| `docs/mentor_presentation_guide.md` | How to explain the project |
| `docs/file_change_log.md` | This file |

## v0.3 — OptiFlux database schema (branch `claude/stoic-cannon-07j4z7`)

All data now uses the 12 OptiFlux DB tables. The optimisation model is
unchanged.

| File | Change |
|---|---|
| `src/railway_rostering/db_schema.py` | **New.** Exact table schemas, CSV reader/writer, `constraints_df` → `ModelConfig`, conversion of the tables into an `Instance` (open demand, disruptions, locked/released assignments, crew state, per-duty eligibility) |
| `src/railway_rostering/synthetic_db.py` | **New.** Synthetic generator for all 12 tables; presets small / medium / tight / large / xlarge |
| `src/railway_rostering/data_loader.py` | `load_instance` dispatches directories with `roster_df.csv` to `db_schema` |
| `src/railway_rostering/solve.py` | Uses the instance's own `ModelConfig` (from `constraints_df`) when none is passed |
| `src/railway_rostering/cli.py` | `generate` writes DB tables (`--n-crew`, `--demand-scale`); config precedence defaults < constraints_df < `--config` < `--set` |
| `src/railway_rostering/benchmark.py` | DB presets; variants start from the instance's rules; `positioning` variant removed (no travel table) |
| `src/railway_rostering/reporting.py` | `roster_disruptions.csv`; `data_preparation` in `summary.json` and the console |
| `src/railway_rostering/synthetic.py` | Docstring: now the internal-format test generator |
| `data/generated/*` | **Replaced** by DB-schema tables |
| `data/sample/briefing_abc` | **Converted** to the DB schema (same known optimum) |
| `data/sample/v1_toy` | **Moved** to `tests/fixtures/v1_toy` (legacy internal format, test fixture only) |
| `tests/test_db_schema.py` | **New.** One test per conversion rule |
| `tests/*` | Updated duty IDs / paths; generator tests use the DB generator; CP-SAT vs MIP on DB instances |
| `notebooks/exploratory_analysis.ipynb` | Uses the instance's `ModelConfig`; shows `data_preparation` |
| `.github/workflows/tests.yml` | v1_toy smoke test path |
| `docs/db_schema.md` | **New.** Table reference, conversion rules, synthetic data, schema assumptions |
| `docs/validation_report.md` | **New.** Test and benchmark results on the DB-schema data |
| `README.md`, `docs/running_experiments.md`, `docs/dataset_design.md`, `docs/codebase_guide.md`, `docs/assumptions_and_open_questions.md` | Updated for the DB schema |
