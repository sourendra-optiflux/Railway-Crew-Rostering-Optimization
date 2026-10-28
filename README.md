# OptiFlux Railway Crew Recovery and Rostering

A working prototype that assigns available **Relief and Excess** railway crew
to **uncovered duties** over a multi-day horizon (Howrah, Yajpur and Nellore;
Howrah Mainline, Yajpur Mainline, NP Crew, NP Shed, Yajpur Crew, Nellore
Driver, YAJ CLO and CO activities). It maximises covered demand while
respecting crew eligibility, swing work/off patterns, shift-time rules
(lift-up / layback), 11 h ordinary and 23 h transition rest, location
continuity and return-to-base rules.

It is built on Google OR-Tools **CP-SAT**: one `AddCircuit` per crew member
over a sparse, pre-filtered graph of legal duty sequences. Every solution is
re-checked by an **independent validator**.

> **Status:** research prototype (v0.2). All data in this repository is
> **synthetic or hand-constructed**. Several operating rules in the briefing
> are ambiguous and are implemented as documented, switchable
> approximations. Do not use the results for live operational decisions.

The problem specification is
[`Optiflux_crew_rostering_problem.md`](Optiflux_crew_rostering_problem.md).

## Quick start

```bash
pip install -r requirements.txt
python scripts/run_example.py                      # briefing ABC example -> outputs/example/
pytest                                             # 171 tests
```

```bash
python scripts/generate_synthetic_instance.py      # regenerate data/generated/*
python scripts/run_example.py --instance-dir data/generated/large --output-dir outputs/large
python scripts/run_example.py --crew data/sample/v1_toy/crew.csv --duties data/sample/v1_toy/duties.csv
python scripts/benchmark.py --presets small medium --time-limit 30
```

More commands, including changing rules and time limits:
[`docs/running_experiments.md`](docs/running_experiments.md).

## What is modelled

| Rule | Status |
|---|---|
| Eligibility by activity (table and/or per-duty list) | hard |
| Demand per duty (multi-crew), uniqueness, coverage accounting | hard |
| Overlap, 11 h ordinary rest | hard |
| 23 h rest on DAY↔NIGHT transitions (only on transitions) | hard; day window 03:00–15:00 is an assumption |
| Duties crossing midnight; prior duty and next commitment at the horizon edges | hard |
| Location continuity from the initial location; no teleporting | hard |
| Positioning (travel) | off by default; optional, synthetic travel times |
| Relief / Excess swing calendars (14/14, 6/6 defaults) | hard (approximation) |
| Excess lift-up / layback (±1 h); Relief any time; persistence of a change within the swing | hard; persistence policy configurable |
| Return to base at swing end and on transition days | hard (approximation) |
| Existing assignments | fixed (default) or reassignable |
| CO and CO-location rules | **disabled**: semantics not defined in the briefing |
| Objective | lexicographic: coverage → priority → positioning → time changes → roster changes |

Details, with the source text for each rule:
[`docs/assumptions_and_open_questions.md`](docs/assumptions_and_open_questions.md).

## Outputs

`assignments.csv`, `uncovered_duties.csv` (with a reason code per duty),
`crew_routes.csv`, `summary.json` (status per stage, objective, bound, gap,
coverage, runtime, model size, rule-status table) and `validation_report.json`.
See [`docs/codebase_guide.md`](docs/codebase_guide.md) §11.

## Results at a glance

Measured in this repository's environment (4 vCPUs). Synthetic data; see
[`docs/validation_report.md`](docs/validation_report.md) for every run.

| Instance | Crew | Duties | Status | Covered / open | Runtime |
|---|---|---|---|---|---|
| `briefing_abc` | 1 | 6 | OPTIMAL | 6 / 6 | < 0.1 s |
| `medium` | 150 | 120 | OPTIMAL | 117 / 124 | ≈ 4 s |
| `large` (≈ preliminary OptiFlux scale) | 1,000 | 300 | OPTIMAL | 296 / 309 | ≈ 10 s |

The formulation was checked against exhaustive enumeration on 300 random tiny
instances and against an independent flow MIP (SCIP): every comparison agreed.

## Documentation

| Guide | Content |
|---|---|
| [`initial_assessment.md`](docs/initial_assessment.md) | Audit of the V1 notebooks and plan |
| [`dataset_research.md`](docs/dataset_research.md) | Public datasets investigated, licences, decision |
| [`dataset_design.md`](docs/dataset_design.md) | Input schema, sample instances, synthetic generator |
| [`problem_formulation.md`](docs/problem_formulation.md) | Sets, variables, constraints, objective → code |
| [`assumptions_and_open_questions.md`](docs/assumptions_and_open_questions.md) | Source vs implementation, open questions |
| [`model_architecture.md`](docs/model_architecture.md) | Design decisions, alternatives, performance |
| [`codebase_guide.md`](docs/codebase_guide.md) | Top-down tour of the code |
| [`running_experiments.md`](docs/running_experiments.md) | Commands |
| [`validation_report.md`](docs/validation_report.md) | Test and benchmark results |
| [`mentor_presentation_guide.md`](docs/mentor_presentation_guide.md) | How to present the work |
| [`file_change_log.md`](docs/file_change_log.md) | What changed, file by file |

## Repository layout

```text
src/railway_rostering/   package (model, constraints, validator, generator, CLI)
scripts/                 run_example.py, generate_synthetic_instance.py, benchmark.py
data/sample/             hand-checkable instances (V1 toy, briefing ABC)
data/generated/          synthetic presets small / medium / tight / large / xlarge
notebooks/               exploratory_analysis.ipynb, solution_visualization.ipynb
tests/                   pytest suite
docs/                    guides listed above
railway_crew_v1.ipynb, rostering_v1_sheets.ipynb   original V1 Colab notebooks (kept unchanged)
Papers/, Progress/       research material
```

## History

Version 1 was a pair of Colab notebooks with fixed 12 h duties, 11 h rest,
location continuity and a daily cap. Its circuit-per-person idea is kept;
its dense variables, missing rules and lack of tests were addressed (see
[`docs/initial_assessment.md`](docs/initial_assessment.md)). The V1 data
still runs unchanged: `data/sample/v1_toy` gives the same answer as the
notebook (5 of 5).

## Data privacy

Do not commit confidential crew identities, schedules or operational railway
data. `.gitignore` excludes `data/private/`, `data/real/` and `outputs/`.
Clear notebook outputs before publishing if they contain real information.

## Disclaimer

This is a learning and prototyping project. Its rules are approximations of
an incompletely specified briefing and must be confirmed by OptiFlux
operations before any real-world use.
