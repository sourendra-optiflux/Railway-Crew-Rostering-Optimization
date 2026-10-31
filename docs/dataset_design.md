# Dataset Design

> **Every data file in this repository is synthetic or hand-constructed.**
> None of it is OptiFlux operational data. Crew identifiers (`C0001`, `ABC`,
> `Shrinath`, ...) are placeholders. Travel times are placeholders, not real
> journey times.

> **Data format update.** All data in `data/` now uses the **OptiFlux database
> schema** (12 tables such as `roster_df`, `activities_df`,
> `activity_demand_df`). That schema, its conversion and the synthetic
> generator that writes it are described in **[`db_schema.md`](db_schema.md)**.
>
> This document describes the solver's **internal** format (`crew.csv`,
> `duties.csv`, ...). The DB tables are converted into it in memory. It is
> still accepted on input (`--crew/--duties`, or a directory without
> `roster_df.csv`), is used by the unit tests, and is the format of the legacy
> V1 fixture `tests/fixtures/v1_toy`. §3 describes `synthetic.py`, which
> builds random internal-format instances for the tests. The on-disk presets
> come from `synthetic_db.py` instead.

This document describes (1) the internal CSV schema, (2) the hand-checkable
sample instances, and (3) the internal-format random instance generator used
by the tests. The decision to use synthetic data is explained in
`dataset_research.md`.

## 1. Input schema

An instance is a directory. `crew.csv` and `duties.csv` are required; the
other files are optional. Times use `YYYY-MM-DD HH:MM`, dates `YYYY-MM-DD`,
times of day `HH:MM`, and lists are separated by `;`.

### 1.1 `crew.csv`

| Column | Required | Meaning | If blank |
|---|---|---|---|
| `crew_id` | yes | Unique id (V1 alias `person_id`) | — |
| `initial_location` | yes | Location at horizon start (or where the prior duty ended) | — |
| `crew_type` | no | `RELIEF` or `EXCESS` | `UNSPECIFIED`: no type-specific rules |
| `base_location` | no | Home base for base-return rules | Base rules off for this crew member (warning) |
| `rostered_start_time` | no | Rostered shift start, e.g. `17:00` | Time-change rules off (warning) |
| `current_start_time` | no | Time already changed to earlier in the current swing | No change made yet |
| `swing_start_date` | no | Any first working day of a swing; the pattern repeats from it | Every day is a working day (warning) |
| `work_days`, `off_days` | no | Swing pattern | Type default: Relief 14/14, Excess 6/6 |
| `prior_duty_end` | no | End of the last duty before (or overlapping) the horizon start | No rest owed at the start |
| `prior_shift_type` | no | `DAY`/`NIGHT` of that duty (for the 23 h rule) | Ordinary rest |
| `next_commitment_start` | no | Start of a known commitment after the recovery duties | No end-boundary rule |
| `next_commitment_location` | no | Where that commitment starts | Any location |
| `next_commitment_shift_type` | no | `DAY`/`NIGHT` | Ordinary rest |
| `unavailable_dates` | no | Dates on which no duty may start (leave) | None |

### 1.2 `duties.csv`

| Column | Required | Meaning | If blank |
|---|---|---|---|
| `duty_id` | yes | Unique id (V1 alias `id`) | — |
| `activity` | yes | Activity name, matched exactly against `eligibility.csv` | — |
| `start` | yes | Start timestamp | — |
| `end` | no | End timestamp (may be the next day) | `start + duration_hours`, else `start + 12 h` |
| `duration_hours` | no | Alternative to `end` | 12 h (`default_duty_hours`) |
| `start_location`, `end_location` | yes | Where the duty starts and ends | — |
| `demand` | no | Crew members required | 1 |
| `priority` | no | 1 = highest | No priority (default weight) |
| `shift_type` | no | `DAY`/`NIGHT`, overrides the time-window classification | Classified from the start time |
| `eligible_crew` | no | Per-duty eligible list (V1 alias `eligible`) | No per-duty restriction |
| `assigned_crew` | no | Crew already rostered on the duty (existing assignments) | Fully open (uncovered) |
| `co_location` | no | CO location (parsed and reported only) | — |

Open demand of a duty = `demand − |assigned_crew|`.

### 1.3 `eligibility.csv`

Long format, one row per qualification: `crew_id,activity`. A crew member is
eligible for a duty only if the activity is listed for them **and** (if the
duty has an `eligible_crew` list) they are on that list. With neither source,
nobody is eligible (the solver never assumes eligibility).

### 1.4 `travel.csv` (only used with `positioning_enabled`)

`from_location,to_location,travel_minutes,cost`. Directed links. Each link is
a single positioning leg; multi-hop journeys must be listed as one link.

### 1.5 `instance.json`

`name`, `horizon_start`, `horizon_end` (exclusive) and metadata. If the
horizon is absent it is inferred from the duty start dates (00:00 of the
first date to 00:00 after the last). Synthetic instances store `synthetic:
true`, a disclaimer, the seed, the full generator configuration, the activity
catalogue and summary characteristics.

## 2. Hand-checkable sample instances (`data/sample/`)

| Instance | Content | Known answer | Used by |
|---|---|---|---|
| `tests/fixtures/v1_toy/` | The 3-crew / 5-duty data of `rostering_v1_sheets.ipynb`, in the **legacy V1 CSV format** (a test fixture, not part of `data/`) | 5 of 5 covered (A: G1, G4, G5) | `test_known_optimal.py`, `test_data_loader.py`, CI smoke test |
| `data/sample/briefing_abc/` | The ABC Relief example from the briefing (§10), **in the OptiFlux DB schema**: 5 PM shifts on 1–3 Nov, a rest/transition day on 4 Nov, 5 AM shifts on 5–7 Nov. Permanent crew staff every other slot | All 6 duties covered by ABC in the stated order | `test_known_optimal.py`, `test_end_to_end.py`, `test_db_schema.py`, default example |

In `briefing_abc` the 2 Nov "Yajpur CLO (YAJ → YAJ)" entry is **omitted**
because the briefing gives no time for it. The same instance with
`railway_crew_v1.ipynb`'s data (crew A starting in Yajpur) gives 4 of 5. That
variant is built inside the test rather than stored as a file.

Many more tiny instances with hand-derived answers are built in code in
`tests/` (rest boundaries at exactly 11 h and 23 h, EFG time-change patterns,
swing boundaries and so on; see `validation_report.md`).

## 3. Synthetic generator

Code: `src/railway_rostering/synthetic.py`. CLI:
`python scripts/generate_synthetic_instance.py [--preset NAME] [--seed N]`.

### 3.1 OptiFlux elements and how they are represented

| OptiFlux element | Source status | Synthetic representation |
|---|---|---|
| Locations Howrah, Yajpur, Nellore | specified | Exactly these three location names |
| Routes Howrah ↔ Yajpur, Howrah ↔ Nellore | specified | Mainline duties on HWH↔YAJ; positioning links on both routes (synthetic times) |
| Howrah Mainline HWH→YAJ, Priority 1 | specified | `Howrah Mainline`, Howrah→Yajpur, priority 1 |
| Yajpur Mainline YAJ→HWH, "(2)" | route specified, "(2)" unclear | `Yajpur Mainline`, Yajpur→Howrah, **no priority** (we do not interpret "(2)") |
| Howrah Mainline CO HWH→HWH | from the briefing example | `Howrah Mainline CO`, Howrah→Howrah |
| Yajpur Mainline CO | named only | Yajpur→Yajpur — **synthetic assumption** |
| YAJ CLO / Yajpur CLO YAJ→YAJ | from the briefing example | `YAJ CLO`, Yajpur→Yajpur |
| Yajpur Crew "(0, 2, 4, 6 … even)" | unclear | Local Yajpur duty; the even pattern is **not modelled** |
| NP Crew "demand 2 at each hour" | unclear | Nellore local duty with **demand 2** (an interpretation) |
| NP Shed "Nellore and Nellore" | stated | Nellore→Nellore |
| Nellore Driver | name only | Nellore→Nellore — **synthetic assumption** |
| 12-hour duties | specified ("300 uncovered 12-hour duties") | All synthetic duties last 12 h |
| 05:00 / 17:00 shifts | from the examples | 60 % of duty starts at 05:00/17:00, 25 % at ±1 h, 15 % at any hour |
| Relief 14/14, Excess 6/6 | "usually" | Relief 14 on/14 off; Excess 6 on/6 off; random swing phase |
| Excess rostered time, lift-up/layback | specified | Excess rostered at 05:00/17:00 (mostly) or 04/06/16/18; 5 % already changed by ±1 h |
| Eligibility by activity | specified | Base-dependent qualification profiles (below) |
| Up to ~50 eligible per duty | preliminary estimate | Per-duty list sampled from qualified crew, capped at `max_eligible_per_duty` |
| Initial location / base | needed data | Mostly at base; 15 % start at a neighbouring location |
| Horizon boundary duties | needed data | 30 % have a prior duty ending between −12 h and +4 h of the horizon start; 20 % have a commitment within 24 h after the horizon end |

The activity catalogue, with the source note of each entry, is
`ACTIVITY_CATALOG` in the code and is copied into each `instance.json`.

### 3.2 Qualification profiles (synthetic)

Each crew member gets each activity of their base's profile independently
with the probability shown (at least one is guaranteed):

| Base | Activity: probability |
|---|---|
| Howrah | Howrah Mainline 0.85, Yajpur Mainline 0.85, Howrah Mainline CO 0.7, Yajpur Mainline CO 0.2, YAJ CLO 0.2, Nellore Driver 0.05 |
| Yajpur | Yajpur Mainline 0.85, Howrah Mainline 0.8, YAJ CLO 0.7, Yajpur Crew 0.7, Yajpur Mainline CO 0.6, Howrah Mainline CO 0.25 |
| Nellore | Nellore Driver 0.85, NP Shed 0.75, NP Crew 0.75, Howrah Mainline 0.1 |

The small Nellore → Howrah Mainline cross-qualification mimics the briefing's
"Shrinath is eligible for Howrah Mainline and Nellore Driver". Mainline
qualification does *not* imply CO qualification.

### 3.3 Algorithm

1. `rng = random.Random(seed)`. Every random draw comes from this generator,
   and lists are iterated in a fixed order, so the output does not depend on
   Python's hash seed. This was checked by generating twice with different
   `PYTHONHASHSEED` values and diffing the files.
2. **Crew** (for `k = 1..n_crew`): base (weights Howrah 0.45, Yajpur 0.35,
   Nellore 0.20) → type (Relief with `relief_fraction` = 0.4) → swing pattern
   and `swing_start = start_date − U{0, period−1}` → rostered time →
   qualifications → initial location → optional prior duty, next commitment
   and leave day.
3. **Duties** (for `k = 1..n_duties`): activity (catalogue weights) → date
   uniform over the horizon → start hour from the mixture in §3.1 → 12 h →
   demand and priority from the activity → eligible list = a random sample of
   at most `max_eligible_per_duty` qualified crew members.
4. **Deliberately uncoverable duties** (`infeasible_duty_fraction`): the
   eligible list is drawn only from crew members *not* qualified for the
   activity, imitating a data inconsistency. The solver must report these as
   `NO_ELIGIBLE_CREW`. Their ids are recorded under
   `characteristics.designed_uncoverable_duties`.
5. **Existing assignments** (`existing_assignment_fraction`): random demand-1
   duties are pre-assigned to an eligible crew member. An assignment is kept
   only if the independent validator says that crew member's existing roster
   stays legal under the default rules.
6. **Travel**: four synthetic links (HWH↔YAJ 360 min, cost 1; HWH↔NLR 900 min,
   cost 2). They are used only if positioning is switched on.

### 3.4 Presets

The presets committed under `data/generated/` are now produced by
`synthetic_db.py` in the OptiFlux DB schema (see `db_schema.md` §5).
`synthetic.py` keeps its own `PRESETS` dict (same names) for building
internal-format instances in tests and experiments from Python.

### 3.5 Known design characteristics and limitations

* Duties are independent draws, so the synthetic data has no timetable
  structure (no train-by-train pattern repeating each day). Real uncovered
  duties are likely to cluster around particular trains and absences.
* "Demand at each hour" is not modelled as an hourly cover requirement. Each
  duty is a discrete 12 h job.
* All duties last 12 h. CLO, shed and CO durations are unknown.
* Excess crew outnumber Relief roughly 3:2. The real mix is unknown.
* The off-day share is high because swing phases are uniform: about half of
  the Relief crew and about half of the Excess crew are off on any given day.
  This is the main reason coverage on `small` is low (see
  `validation_report.md`, "relaxed" variant).
* Crew ids and travel times are placeholders.

### 3.6 Generating your own instance

For DB-schema instances, see `db_schema.md` §5:

```bash
python scripts/generate_synthetic_instance.py --preset medium --seed 123 --name medium_seed123
```

An internal-format random instance can be built from Python:

```python
from railway_rostering.synthetic import SyntheticConfig, generate_instance
from railway_rostering import write_instance
inst = generate_instance(SyntheticConfig(name="mine", seed=1, n_crew=300, n_duties=150, horizon_days=10,
                                         relief_fraction=0.6, infeasible_duty_fraction=0.05))
write_instance(inst, "data/generated/mine")
```
