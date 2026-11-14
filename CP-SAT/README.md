# CP-SAT: layer 2, choose the options and fill `Optimised User Id`

This layer reads what `option_generation/` wrote (`seats.csv`, `swings.csv`, `options.csv`) and uses
OR-Tools CP-SAT to choose one option per row. It then writes the result into `roster_full.csv`. It never
adds options of its own. The rules are in `data/optiflux_v2/source/rules/gap_filling_rules.md`.

```bash
python gap_generation/make_gaps.py
python option_generation/generate_options.py --config config.yml
python CP-SAT/run_gap_filling.py --config config.yml --time-limit 120
# or all of it, plus the Excel workbook:
python scripts/run_pipeline.py
```

| Option | Default | Meaning |
|---|---|---|
| `--roster-full` | `gap_generation/output/roster_full.csv` | Roster with gaps |
| `--options-dir` | `option_generation/output` | Layer 1 output |
| `--output-dir` | `CP-SAT/outputs/roster_full` | Where results go. A rerun overwrites them |
| `--time-limit` | 120 | Seconds per objective stage |
| `--workers` | 8 | CP-SAT threads |
| `--config` | `config.yml` | Shared constraint switches; use the same file as option generation |

Demand filling priorities are configured in
[`data/optiflux_v2/activity_priority.csv`](../data/optiflux_v2/activity_priority.csv) (or `activity_priority.csv` inside `--data-dir`). It must contain exactly one
priority per demand activity head. Each priority must have a weight in `PRIORITY_WEIGHTS` in
`CP-SAT/utils/activity_head_priority.py`; lower numbers indicate higher priority. Missing, duplicate,
invalid, unweighted, and non-demand activity-head entries are rejected before solving.

`config.yml` selects how those priorities affect optimization:

```yaml
optimization:
  priority_strategy: none  # none / weighted / lexicographic
```

Every strategy first maximizes total demand fulfilment. `none` then minimizes assignment cost;
`weighted` next maximizes weighted activity-head fulfilment; `lexicographic` instead maximizes
fulfilment for each priority in ascending order, one stage at a time. Each stage's optimum is fixed
before the next stage runs, and the next stage is skipped unless the previous stage is proven `OPTIMAL`.

## Output (`CP-SAT/outputs/roster_full/`)

| File | Content |
|---|---|
| `roster_full.csv` | The roster with `User Id`, `New User Id` and **`Optimised User Id`** side by side, plus `Optimisation Note` on every changed row |
| `reassignments.csv` | One row per filled seat: the row, who had it, who has it now, where they came from, the start change and the chain level |
| `unfilled_gaps.csv` | Demand rows still empty: locked gaps, gaps with no legal filler, and seats left by a move (if any) |
| `validation.md` | The rule checks (see below) |
| `summary.md` | The headline numbers |
| `optiflux_all_tables.xlsx` | Written by `scripts/run_pipeline.py`: every CSV of the run (base data, gaps, options, result) as its own sheet |

In `roster_full.csv`, `Optimised User Id` starts as `New User Id` and changes only where someone moved:

- the row they left becomes blank: a standby row, an Excess row, or their own Demand seat;
- the row of the seat they took gets their id: a gap row, or a row its holder left.

## The model

- **Rows.** Each row of a swing in the model gets exactly one of its options (keep, fill, ride), or is
  dropped if layer 1 allowed that.
- **Sequence.** One `AddCircuit` per swing. A path through it is the shifts the person really works,
  so rest, day/night switches, location, home base and the Residential day-first rule hold between
  consecutive shifts.
- **Seats.** A seat has room for `Demand - Fixed Occupants`. A Demand person's `keep` uses a place on
  their own seat. If they move, that place is free for someone else. This is how chains work (F2).
- **Start-time pattern (F3).** Each block (the day shifts or the night shifts of a swing) has a base
  start B, a changed start N at most 60 min away, and one switch point. Worked shifts before the
  switch start at B and those after it at N, so `03 04 04` is allowed but `03 04 03` and `03 05 05`
  are not. Relief standby rows have no fixed start and are left out.
- **Excess (G5).** An Excess row may only stay on a seat that is fully covered.
- **Objective stages** follow `optimization.priority_strategy` as described above. Weighted fulfilment
  uses `PRIORITY_WEIGHTS` in `CP-SAT/utils/activity_head_priority.py`. Each assigned in-model demand
  position contributes its seat's weight, and seat-capacity constraints limit how many positions count.
  The final cost stage uses `Costs` in `option_generation/options.py`. A later stage only runs when the
  preceding stage is `OPTIMAL`; if a stage is only `FEASIBLE`, all remaining stages are skipped.

  | Change | Cost |
  |---|---|
  | Excess already on the seat | 0 |
  | Relief | 10 + 1 per hour between standby time and duty |
  | Excess moved | 20 + 1 per hour |
  | Trip home | 30 |
  | Demand moved | 40 + 1 per hour |

## Validation

`scripts/check_roster.py` runs twice: on the roster after leave and on the optimised roster. Leave on
its own already breaks some rules: open seats (G1), Excess on a short seat (G5), a swing that now starts
on a night shift (R1), and a swing cut in two (off time, travel). Those show as
`fails after leave too`. A check that fails **only** after optimisation is a real failure.

Recovery checks V1–V6 are added on top:

- rows before 6 Nov are unchanged;
- no seat is over its demand;
- every filler is certified, fit, in an allowed role and current;
- frozen swings lose no rows;
- every changed person keeps rest, location and the one-change start pattern.

## Files

| File | Purpose |
|---|---|
| `run_gap_filling.py` | Command line entry point |
| `solver.py` | The CP-SAT model and staged objectives |
| `utils/load_options.py` | Reads the layer 1 files |
| `utils/output.py` | Writes `Optimised User Id`, the reports and the summary |
| `utils/validate.py` | The checker comparison and checks V1–V6 |
