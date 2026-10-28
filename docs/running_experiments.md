# Running Experiments

Copy-paste commands, run from the repository root. Every command works from a
fresh clone, without installing the package (the `scripts/` wrappers add
`src/` to the path). Expected outputs below were observed in the development
environment (Python 3.13, OR-Tools 9.15, 4 vCPUs).

## 1. Install

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`ortools` is the only runtime dependency. `pytest` is for tests, and `pandas`
and `matplotlib` are for the notebooks. To install the package itself (this
adds the `railway-rostering` command):

```bash
pip install -e ".[dev]"
```

## 2. Run the example

```bash
python scripts/run_example.py
```

This solves `data/sample/briefing_abc` (the briefing's ABC Relief example)
and writes to `outputs/example/`. Expected console output:

```text
Instance        : briefing_abc (1 crew, 6 duties, 6 open demand units)
Status          : OPTIMAL  stages={'coverage': 'OPTIMAL', 'priority': 'OPTIMAL', 'time_changes': 'OPTIMAL'}
Covered units   : 6 / 6 (100.0%)   best bound=6.0
Greedy baseline : 6 units
Validation      : PASSED (0 violations)
...
```

The V1 notebook data, in the legacy CSV format, with explicit file paths:

```bash
python scripts/run_example.py \
  --crew data/sample/v1_toy/crew.csv \
  --duties data/sample/v1_toy/duties.csv \
  --output-dir outputs/v1_toy
```

Expected: `OPTIMAL`, 5 / 5 covered (crew A does G1, G4, G5).

A synthetic instance near the preliminary OptiFlux scale (1,000 crew, 300
duties, 14 days):

```bash
python scripts/run_example.py --instance-dir data/generated/large --output-dir outputs/large --time-limit 60
```

Expected: `OPTIMAL`, 296 / 309 units, about 10 s.

Exit codes: `0` success, `2` input error, `3` the validator found a
violation.

## 3. Generate synthetic datasets

```bash
python scripts/generate_synthetic_instance.py                 # all presets -> data/generated/
python scripts/generate_synthetic_instance.py --preset small  # one preset
python scripts/generate_synthetic_instance.py --preset medium --seed 123 --name medium_seed123
python scripts/generate_synthetic_instance.py --preset large --n-crew 500 --n-duties 200 --name half_crew
```

Each run prints one line per instance, e.g. `wrote data/generated/small (20
crew, 20 duties, 21 open units, seed 11)`. The same preset and seed always
give byte-identical files. The files' design is in `dataset_design.md`.

## 4. Run the tests

```bash
pytest                       # whole suite (~15 s), expected: 171 passed
pytest tests/test_time_rest.py -v
pytest -k brute_force        # CP-SAT vs exhaustive enumeration on 40 random tiny instances
ruff check src tests scripts # lint (as in CI)
```

## 5. Run benchmarks

```bash
python scripts/benchmark.py --presets small medium --time-limit 30
python scripts/benchmark.py --presets small medium tight large xlarge \
  --variants default no_lp_bound relaxed positioning window_only \
  --time-limit 60 --workers 4 --mip-check-max-duties 600
```

Results go to `outputs/benchmarks/results.csv`, `results.json` (with
environment details) and `results.md` (a Markdown table). One progress line is
printed per run:

```text
[medium/default] status=OPTIMAL covered=117/124 bound=117.0 greedy=96 t=4.4s valid=True mip=OPTIMAL:117
```

Variants: `default`; `no_lp_bound` (without the LP cut); `no_cliques`;
`no_hint`; `positioning` (travel allowed, synthetic times); `window_only`
(time changes not persisted); `relaxed` (no transition rest, no base return,
no swing calendar, no time rules — a *rule-impact study only*, not a valid
operating mode). `mip` columns show the SCIP flow-MIP cross-check on the same
candidate arcs.

## 6. Inspect assignments and uncovered duties

```bash
column -s, -t < outputs/example/assignments.csv | less -S
column -s, -t < outputs/large/uncovered_duties.csv | less -S
python -c "import json; s=json.load(open('outputs/large/summary.json')); print(s['status'], s['coverage'], s['best_bounds'])"
python -m json.tool outputs/large/validation_report.json | head -40
```

* `assignments.csv`: one row per (crew, duty) in route order.
  `start_offset_minutes` shows lift-up (−60) and layback (+60).
* `uncovered_duties.csv`: `reason_code` explains each uncovered duty; the
  `n_*` columns show how many crew members survived each filter.
* `crew_routes.csv`: each working crew member's route and whether they end at
  base.

Independently re-validate any assignment file, including one produced by
hand or by another tool:

```bash
python -m railway_rostering validate --instance-dir data/sample/briefing_abc \
  --assignments outputs/example/assignments.csv
```

(Install the package first, or prefix the command with `PYTHONPATH=src`.)
Prints the validation report JSON. The exit code is 3 if any rule is
violated.

The notebooks give a visual view:

```bash
jupyter notebook notebooks/solution_visualization.ipynb
```

## 7. Change the time limit and model settings

```bash
# Solver: seconds per objective stage, threads, seed, search log
python scripts/run_example.py --instance-dir data/generated/tight --time-limit 10 --workers 8 --seed 3 --log

# Rules: any ModelConfig field via --set key=value (value parsed as JSON, else taken as a string)
python scripts/run_example.py --instance-dir data/generated/medium \
  --set 'time_change_policy={"RELIEF":"window_only","EXCESS":"window_only"}'
python scripts/run_example.py --instance-dir data/generated/medium --set max_duties_per_day=null
python scripts/run_example.py --instance-dir data/generated/medium --set transition_rest_enabled=false
python scripts/run_example.py --instance-dir data/generated/medium --positioning
python scripts/run_example.py --instance-dir data/generated/medium --set 'objective_levels=["priority","coverage"]'
python scripts/run_example.py --instance-dir data/generated/medium --set demand_mode=all_or_nothing
python scripts/run_example.py --instance-dir data/generated/medium --set existing_assignment_mode=reassignable
```

Settings can also live in a JSON file:

```json
{
  "model":  {"ordinary_rest_hours": 12, "base_return_on_transition": false},
  "solver": {"time_limit_seconds": 120, "num_workers": 8}
}
```

```bash
python scripts/run_example.py --instance-dir data/generated/large --config my_config.json
```

The full list of fields with their defaults is in
`src/railway_rostering/config.py`. Their meaning and source status are in
`assumptions_and_open_questions.md`.

## 8. From Python

```python
from railway_rostering import load_instance, solve_instance, write_outputs, ModelConfig, SolverConfig

inst = load_instance("data/generated/medium")
result = solve_instance(inst, ModelConfig(positioning_enabled=True), SolverConfig(time_limit_seconds=30))
print(result.solution.status, result.validation.coverage)
write_outputs(result, "outputs/medium_positioning")
```
