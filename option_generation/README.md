# option_generation: layer 1, list who may legally fill each seat

This layer removes every (person, seat) pair that can never be legal, so CP-SAT only chooses from
options that could work. It reads `gap_generation/output/roster_full.csv` and the tables in
`data/optiflux_v2`, and writes plain CSV files. **CP-SAT reads only these files.** It does not build
options of its own. The rules are in `data/optiflux_v2/source/rules/gap_filling_rules.md`.

```bash
python option_generation/generate_options.py               # after gap_generation/make_gaps.py
python option_generation/generate_options.py --max-chain 1 # at most one Demand move per chain
python option_generation/generate_options.py --config config.yml
```

| Option | Default | Meaning |
|---|---|---|
| `--max-chain` | 2 | Max Demand moves that can follow each other (F2) |
| `--allow-stand-down` | off | Let Excess or Relief rows be dropped to make room |
| `--no-return-rides` | off | No trips across the line as Excess |
| `--config` | `config.yml` | Switches for the configurable constraints, shared with CP-SAT |

`config.yml` controls the two rule switches in both layers. Set either value to `false` to disable that
constraint for option generation and CP-SAT; use the same file when running both commands.

| Switch | Default | Effect when enabled |
|---|---:|---|
| `constraints.residential_start_restriction` | `true` | Residential fill/ride starts are disallowed from 22:00 to 02:00; the separate first-shift-must-be-day rule remains enabled |
| `constraints.relief_only_day_night_transition` | `true` | Only a Relief assignment may precede a day/night switch; transition rest still applies |

## What is rejected, and why

A row of a person is a candidate for a seat only if all of these hold:

| Check | Rule |
|---|---|
| The row is on or after the solver start (6 Nov), inside the horizon, and not locked | G1, R4 |
| The person's swing did not start before 6 Nov and is not partly on leave. The one exception: an Excess person on the very same seat may take it, because nothing in their day changes | F4 |
| **Relief:** the same date, any start time. **Excess:** a start change of -60, 0 or +60 min. **Demand:** a start change of -60, 0 or +60 min, onto a different seat | F1 |
| The person is in `eligibility_matrix.csv` for the activity, medically Fit, in an allowed role, and current | R5 |
| The option sits on a complete legal path through the swing: 11 h rest, 23 h on a day/night switch, one shift a day, location, home base, first shift a day shift (Residential), travel times, and no start jump of more than 1 h inside a block | F3 and the base rules |

## Chains of moves (F2)

- **Level 0:** the gap seats.
- **Next level:** if a Demand person has a legal option on a level-0 seat, their own seat could open up, so it becomes a level-1 seat. Its candidates are found the same way, and so on.
- **Limit:** a Demand person only gets a fill option if their own seat can still be refilled, so the deepest level is filled by Excess and Relief only. With `--max-chain 2`, a gap can be filled by Demand → Demand → Excess/Relief.

## Output (`option_generation/output/`)

| File | Content |
|---|---|
| `gap_options.csv` | The readable list: for each seat (gaps first), every legal candidate, their source (Excess, Relief or Demand), start change and cost |
| `rejections.csv` | For each gap seat, how many same-day rows each check rejected |
| `options.csv` | Input to CP-SAT: every option (keep, fill, ride) of every row of every swing in the model |
| `swings.csv` | Every swing: movable or frozen (and why), time window, in the model or not |
| `seats.csv` | Every seat from 6 Nov: demand, people on it, people fixed outside the model, open places, chain level |
| `summary.md` | Headline numbers and the rejection reasons |

Run with seed 2026: 252 gap seats (258 places), 11 of them with no legal candidate, and 365 chain seats.
309 of 1,481 swings are in the model, with 16,971 options. Most gap candidates are rejected because the
start change is more than 1 h, they are not certified, or their swing started before 6 Nov.

## Files

| File | Purpose |
|---|---|
| `generate_options.py` | Command line entry point, writes the files |
| `options.py` | Swings, seats, candidate checks, chain levels, path pruning, `Costs` |
| `rules.py` | Settings from `constraints_df.csv` and the check between two consecutive shifts. CP-SAT uses it too |
| `data.py` | Loads `roster_full.csv`, the eligibility matrix and the other tables |
