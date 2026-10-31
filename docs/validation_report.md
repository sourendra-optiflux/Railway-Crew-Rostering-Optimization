# Validation Report

Test and benchmark results for v0.3, where all data uses the OptiFlux database
schema. Environment: Python 3.13, OR-Tools 9.15, 4 vCPUs, 4 CP-SAT workers.
All data is synthetic (`data/generated`, `data/sample`).

## 1. Test suite

```bash
pytest          # 199 passed in ~15 s
ruff check src tests scripts
```

| Area | Tests |
|---|---|
| DB schema conversion (`test_db_schema.py`) | exact columns; missing column error; demand minus regular roster; leave / medical / competency expiry / suspension / currency / role / mentor / night and activity restrictions; excluded and inactive demand; locked vs unlocked vs Can Be Moved; prior duty → location, rest, time already changed; onsite location and absence; Standby rows → swing and days off; priority weights; constraints_df → ModelConfig, bad constraints, a rule change altering the optimum; CLI overrides |
| Known optima | briefing ABC (DB schema) reproduced in order; 23 h transition day rejected; V1 notebook data 5/5 and 4/5 |
| Brute force | CP-SAT = exhaustive enumeration on random tiny instances under several rule settings |
| Cross-checks | CP-SAT = SCIP flow MIP on random internal-format and DB-schema instances; greedy rosters always legal; greedy fallback when CP-SAT finds nothing |
| Rules | eligibility, demand, rest/overlap, location, swing, lift-up/layback and persistence, base return, objective levels, validator |
| Generators | DB generator deterministic; committed `small`/`medium` match it byte for byte; `data/` holds only DB-schema tables; generated existing assignments legal |
| End to end | CLI solve / validate / benchmark, output files, uncovered reasons account for every open unit, `run_example.py` from a fresh checkout |

The two notebooks also execute from start to finish (`nbclient`).

## 2. Benchmarks

```bash
python scripts/benchmark.py --presets small medium tight large \
  --variants default no_lp_bound no_cliques no_hint window_only relaxed \
  --time-limit 60 --workers 4 --mip-check-max-duties 600
python scripts/benchmark.py --presets xlarge --time-limit 120 --workers 4 --mip-check-max-duties 600
```

`covered` = new demand units covered by Relief/Excess crew. `bound` = proven
upper bound. `greedy` = the constructive baseline. `MIP` = SCIP flow MIP on
the same candidate arcs. Runtimes are totals over all lexicographic stages.

| Preset | Variant | Crew | Duties | Open | Status | Covered | Bound | Greedy | Runtime (s) | Valid | MIP |
|---|---|---|---|---|---|---|---|---|---|---|---|
| small | default | 18 | 21 | 21 | OPTIMAL | 12 | 12 | 10 | 0.03 | ✓ | 12 |
| small | relaxed | 18 | 21 | 21 | OPTIMAL | 14 | 14 | 14 | 0.07 | ✓ | 14 |
| medium | default | 130 | 100 | 138 | OPTIMAL | 120 | 120 | 117 | 1.8 | ✓ | 120 |
| medium | no_lp_bound | 130 | 100 | 138 | OPTIMAL | 120 | 120 | 117 | 2.0 | ✓ | 120 |
| medium | no_cliques | 130 | 100 | 138 | OPTIMAL | 120 | 120 | 117 | 1.5 | ✓ | 120 |
| medium | no_hint | 130 | 100 | 138 | OPTIMAL | 120 | 120 | 117 | 1.8 | ✓ | 120 |
| medium | window_only | 130 | 100 | 138 | OPTIMAL | 122 | 122 | 119 | 2.0 | ✓ | 122 |
| medium | relaxed | 130 | 100 | 138 | OPTIMAL | 136 | 136 | 135 | 3.9 | ✓ | 136 |
| tight | default | 54 | 134 | 212 | OPTIMAL | 96 | 96 | 85 | 1.1 | ✓ | 96 |
| tight | window_only | 54 | 134 | 212 | OPTIMAL | 99 | 99 | 90 | 1.0 | ✓ | 99 |
| tight | relaxed | 54 | 134 | 212 | OPTIMAL | 114 | 114 | 109 | 1.5 | ✓ | 114 |
| large | default | 974 | 211 | 293 | OPTIMAL | 256 | 256 | 244 | 15.0 | ✓ | 256 |
| large | no_lp_bound | 974 | 211 | 293 | OPTIMAL | 256 | 256 | 244 | 18.4 | ✓ | 256 |
| large | no_cliques | 974 | 211 | 293 | OPTIMAL | 256 | 256 | 244 | 16.5 | ✓ | 256 |
| large | no_hint | 974 | 211 | 293 | OPTIMAL | 256 | 256 | 244 | 18.4 | ✓ | 256 |
| large | window_only | 974 | 211 | 293 | OPTIMAL | 256 | 256 | 244 | 16.3 | ✓ | 256 |
| large | relaxed | 974 | 211 | 293 | OPTIMAL | 292 | 292 | 291 | 34.3 | ✓ | 292 |
| xlarge | default | 973 | 299 | 598 | OPTIMAL | 564 | 564 | 546 | 128.9 | ✓ | 564 |

(The small and tight variants not shown give the same result as `default`.)
Full rows, including model size, are in `outputs/benchmarks/results.csv`.

Model size (default variant):

| Preset | Candidate (crew, duty) pairs | Arcs |
|---|---|---|
| small | 15 | 34 |
| medium | 432 | 1,770 |
| tight | 237 | 1,145 |
| large | 2,306 | 10,729 |
| xlarge | 5,353 | 33,431 |

## 3. Observations

* **Every run is OPTIMAL, accepted by the independent validator, and equal
  to the SCIP flow MIP.**
* **CP-SAT beats greedy where it matters.** CP-SAT covers 3–18 more units
  than the greedy roster on medium, tight, large and xlarge. The difference comes
  from sequencing: a feasible duty taken greedily blocks later ones.
* **Rule impact (`relaxed`).** Dropping transition rest, base return, the
  swing calendar and the time rules raises coverage on `large` from 256 to
  292 of 293. These rules cost about 12% of the coverage. This is a study
  only, not a valid operating mode.
* **Structural gaps.** Some open units cannot be covered by anyone: no
  eligible, available or time-compatible crew member
  (`uncovered_structural` = 9, 3, 17, 5, 5 duties for small, medium, tight,
  large and xlarge). `uncovered_duties.csv` explains each one, and
  `roster_disruptions.csv` explains why the slot was open in the first place.
* **Speed-ups have little effect at this size.** The LP bound, clique rows
  and greedy hint make little difference here. All variants on
  small to large prove optimality within seconds. `xlarge` (33k arcs) takes about
  two minutes over the three stages.
