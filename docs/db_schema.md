# OptiFlux Database Schema — Input Data

All input data in this repository uses the 12 tables of the OptiFlux database,
one CSV file per table. This guide covers each table, how the optimiser reads
it, and which parts of the schema had to be assumed.

Code: `src/railway_rostering/db_schema.py` (schema, reader, conversion) and
`src/railway_rostering/synthetic_db.py` (synthetic data in this schema).
Tests: `tests/test_db_schema.py` (one test per conversion rule).

> **All data in `data/` is synthetic.** Names, IDs, e-mail addresses
> (`@example.invalid`), depots, competencies and timings are invented.

## 1. Directory layout

An instance is a directory holding one CSV per table, named after the table.
The header is the exact database column names, in schema order:

```text
data/generated/medium/
  roster_df.csv            activities_df.csv        activity_demand_df.csv
  crew_restrictions.csv    crew_competencies_df.csv compliance_matrix_df.csv
  crew_master_data_df.csv  Crew_Onsite_App.csv      crew_currency_df.csv
  constraints_df.csv       excluded_activities.csv  activity_priority.csv
  instance.json            (optional: name, seed, generator settings — not a DB table)
```

`load_instance(dir)` and every command-line `--instance-dir` recognise this
layout (by `roster_df.csv`) and convert it automatically.

**Excel alternative.** A workbook with one sheet per table can be loaded the
same way: the sheet names are the table names and the headers are the same
columns. `real_data/optiflux_db_template.xlsx` is the blank template (see
`real_data/README.md`). Pass the `.xlsx` path to `load_instance` or
`--instance-dir`. `python scripts/make_excel_template.py --from-dir DIR`
writes any CSV instance as a filled workbook.

* **Required tables:** `roster_df`, `activities_df`, `activity_demand_df`,
  `crew_master_data_df` and `constraints_df`.
* **Optional tables:** the other seven. A missing optional table is treated as
  empty.

## 2. The tables

Formats:
* Dates are `YYYY-MM-DD` and times are `HH:MM`.
* Flags accept `Yes/No` (also `Y/N`, `True/False`, `1/0`).
* Lists are separated by `;`.

### 2.1 `roster_df` — every rostered assignment
| # | Column | Use |
|---|---|---|
| 1 | Assignment ID | identifier, used in `roster_disruptions.csv` |
| 2 | User Id | crew member (→ `crew_master_data_df.User Id`) |
| 3 | Start Date | date the shift starts |
| 4 | End Date | date the shift ends (the next day for a night shift) |
| 5 | Shift Start Time | start time |
| 6 | Shift End Time | end time |
| 7 | CRT Activity ID | activity (→ `activities_df.CRT Activity ID`) |
| 8 | Activity Name | fallback key if the CRT ID is unknown |
| 9 | Is Locked | Relief/Excess rows: `Yes` = must be kept, `No` = may be re-planned |
| 10 | Activity Head | informational (taken from the activity) |
| 11 | Activity Type | `Standby` = availability row for Relief/Excess crew |
| 12 | Activity Group | informational |

One row is one shift. Rows before and after the horizon are used too: they set
rest and location at the horizon start and commitments after its end.

### 2.2 `activities_df` — activity catalogue
| # | Column | Use |
|---|---|---|
| 1 | Activity ID | key used by demand, compliance and exclusions |
| 2 | CRT Activity ID | key used by the roster |
| 3 | Activity Name | duty activity name in the outputs |
| 4 | Activity Group | informational |
| 5 | Activity Head | key for priority, currency and activity restrictions |
| 6 | Activity Type | `Standby` marks the availability activities |
| 7 | TEA Required | **read but not modelled** (meaning not specified) |
| 8 | Can Be Moved | `No` → Relief/Excess assignments on it are kept even if unlocked |
| 9 | Start Depot | duty start location |
| 10 | End Depot | duty end location (location continuity, base return) |
| 11 | Location | fallback for Start/End Depot |
| 12 | Mentor Required | `Yes` → trainees (crew with a `Mentor Id`) may not work it alone |
| 13 | Roles/Job | allowed crew `Role`s (blank = any) |
| 14 | Currency Threshold | days: crew must have worked this Activity Head within this many days (blank = no rule) |

### 2.3 `activity_demand_df` — crew required per shift
| # | Column | Use |
|---|---|---|
| 1 | Demand ID | prefix of the duty IDs (`DM014-20261103`) |
| 2 | Shift | `HH:MM-HH:MM`; an end at or before the start crosses midnight |
| 3 | Demand | crew required on that shift |
| 4 | Is Active | `No` → ignored |
| 5 | Activity ID | the activity |
| 6 | Activity Name | fallback key |
| 7 | Activity Head | informational |

A row applies to **every day** of the planning horizon.

### 2.4 `crew_restrictions` — restrictions by date
| # | Column | Use |
|---|---|---|
| 1 | Restriction ID ⚠ | identifier |
| 2 | CM Id ⚠ | crew member |
| 3 | Restriction Type ⚠ | `No Duty`, `Activity Restriction` or `No Night Shift` |
| 4 | Activity Head ⚠ | for `Activity Restriction` (blank = all activities) |
| 5 | Effective From | first day (blank = open) |
| 6 | Effective To | last day (blank = open) |
| 7 | Reason | informational |

### 2.5 `crew_competencies_df` — competencies held
| # | Column | Use |
|---|---|---|
| 1 | CM Id | crew member |
| 2 | Competency | name (fallback key) |
| 3 | Competency LMS Code | key matched against the compliance matrix |
| 4 | Expiry Date | must not be before the duty's end date (blank = no expiry) |
| 5 | status | must be `Valid` (or `Active`/`Current`) |

### 2.6 `compliance_matrix_df` — competencies each activity requires
| # | Column | Use |
|---|---|---|
| 1 | Activity ID | the activity |
| 2 | Activity Name | informational |
| 3 | Competency LMS Code | a required competency |
| 4 | Competency | informational |
| 5 | Activity Head | informational |

### 2.7 `crew_master_data_df` — crew
| # | Column | Use |
|---|---|---|
| 1 | CM Id | crew ID used in all outputs |
| 2 | User Id | link to the roster |
| 3–5 | Email, First Name, Last Name | identity only; not used |
| 6 | Mentor Id | non-blank → trainee (see Mentor Required) |
| 7 | Classification | `Relief` / `Excess` → optimised; anything else (e.g. `Permanent`) → regular crew |
| 8 | Depot | base location (return-to-base rules) |
| 9 | Role | matched against `Roles/Job` |
| 10 | Is Mentor | informational |
| 11 | Medical | `Unfit` / `Expired` / `Suspended` → may not work |
| 12 | Position | informational (synthetic data: FIFO / Residential / Line) |

### 2.8 `Crew_Onsite_App` ⚠ — onsite check-ins
| # | Column | Use |
|---|---|---|
| 1 | Record ID | identifier |
| 2 | CM Id | crew member |
| 3 | Date | day of the record |
| 4 | Location | where the crew member is (the record on the horizon start day, or the day before, sets the initial location) |
| 5 | Status | `Absent` / `Sick` → unavailable that day |

### 2.9 `crew_currency_df` ⚠ — last time each activity head was worked
| # | Column | Use |
|---|---|---|
| 1 | Currency ID ⚠ | identifier |
| 2 | CM Id ⚠ | crew member |
| 3 | Activity Head | the activity head |
| 4 | Last Performed Date | used with `Currency Threshold` |
| 5 | Last CRT Activity ID | informational |

### 2.10 `constraints_df` — rule settings
`Constraint`, `Value`, `Status` (`Active` / `Inactive`). Recognised names (case-insensitive):

| Constraint | Value | Effect |
|---|---|---|
| Planning Horizon Start | `2026-11-01` | **required** |
| Planning Horizon Days | `14` | **required** |
| Ordinary Rest Hours | `11` | minimum rest; Inactive → 0 |
| Transition Rest Hours | `23` | rest on a DAY↔NIGHT change; Inactive → rule off |
| Day Shift Window | `03:00-15:00` | start times counted as DAY shifts |
| Max Duties Per Day | `1` | Inactive → no cap |
| Relief Work/Off Days | `14/14` | default swing if the roster shows no next swing |
| Excess Work/Off Days | `6/6` | idem |
| Relief Allowed Start Offsets | `ANY` | minutes from the rostered time |
| Excess Allowed Start Offsets | `-60;0;60` | lift-up / layback |
| Relief Time Change Policy | `persist_after_change` | or `window_only` / `disabled` |
| Excess Time Change Policy | `persist_after_change` | idem |
| Enforce Swing Work Days | — | Status only |
| Base Return At Swing End | — | Status only |
| Base Return On Transition | — | Status only |
| Base Return At Horizon End | — | Status only |
| Demand Mode | `partial` | or `all_or_nothing` |
| Objective Order | `coverage;priority;time_changes` | lexicographic levels |
| Positioning | — | must be Inactive (the schema has no travel times) |

A row whose name is exactly a `ModelConfig` field (e.g. `add_redundant_cliques`)
sets that field. Any other name gives a warning and is ignored. Command-line
`--config` / `--set` options override this table.

### 2.11 `excluded_activities` ⚠
`Activity ID`, `Activity Name`. Demand for these activities is not covered by the optimiser.

### 2.12 `activity_priority` ⚠
`Priority`, `Activity Head`. Rank 1 is the highest priority. The priority
objective weight of rank *r* out of *N* is `N + 1 − r`, and an unranked head
gets weight 0. The supplied order is used in the synthetic data:

1 Madison Crew · 2 NE Task · 3 Fuel Return · 4 Bethway Join/FI Crew ·
5 Nelaway Shuttle Driver · 6 NE Ship · 7 Nelaway Driver · 8 Fuel Train ·
9 Haskett Mainline · 10 CAM LOT · 11 Madison Yard · 12 Work Train ·
13 Yarmouth Mainline · 14 BY Shed

⚠ = column(s) not readable in the schema screenshots (see §6).

## 3. From tables to an optimisation instance

`build_instance(tables)` runs these steps. The counts from each step are in
`summary.json → data_preparation` and on the first console line.

1. **Rules and horizon** come from `constraints_df`, and priority weights from
   `activity_priority`. The result is stored as the instance's `ModelConfig`.
2. **Demand slots.** Each active, non-excluded `activity_demand_df` row
   creates one slot per horizon day: (activity, date, shift) needing `Demand`
   crew.
3. **Regular crew roster rows** (Classification not Relief/Excess) cover a slot
   when activity and start date-time match. A row counts only if that crew
   member can still legally work it (rule check in step 6). Otherwise it is a
   **disruption**, listed with its reason in `roster_disruptions.csv`, and
   the slot opens up again.
4. **Relief/Excess roster rows inside the horizon:**
   * `Is Locked = Yes`, or an activity with `Can Be Moved = No`, → **fixed
     assignment** (if still legal; otherwise it is a disruption too).
   * Unlocked → **released**: the crew member is free and the slot is open,
     so the optimiser may re-cover it with anyone.
   * A locked row with no matching demand slot is still kept as a fixed duty
     (`R-<Assignment ID>`) so that the crew member's time stays blocked.
5. **Relief/Excess crew state:**
   * *Working days.* The days of all their roster rows (Standby or real).
     The consecutive run that reaches the horizon start is the current swing
     (`swing_start`, `work_days`). The gap to the next run gives `off_days`;
     if there is no next run, the constraints_df default applies. With
     *Enforce Swing Work Days* on, horizon days without a roster row are days
     off.
   * *Rostered start time.* The most common Standby `Shift Start Time`.
   * *Prior duty.* The last real row before the horizon. It gives rest at the
     horizon start (`prior_duty_end`, shift type) and location (End Depot).
     If it started at a non-rostered time within the current swing, that time
     is the time already in effect (persistence rule).
   * *Next commitment.* The first real row after the horizon end.
   * *Initial location.* The onsite record for the start day (or the day
     before), else the prior duty's End Depot, else the Depot.
   * *Unavailable days.* `No Duty` restrictions, onsite `Absent`/`Sick`, and
     days off.
   * *Excluded entirely.* Medically unfit crew, and crew with no roster row in
     the horizon.
6. **Rule check** for crew *c*, activity *a*, shift from *s* to *e* (used for
   regular-crew validity, locked rows and Relief/Excess eligibility). All of
   these must hold:
   * medical fit;
   * not unavailable on the start date;
   * `Role ∈ Roles/Job`;
   * not a trainee on a `Mentor Required` activity;
   * every competency the compliance matrix lists for *a* is held, with
     status Valid and expiry ≥ the end date;
   * currency: `start date − Last Performed Date ≤ Currency Threshold`;
   * no `Activity Restriction` on that head that day;
   * no `No Night Shift` restriction that day if the shift is a night shift.
7. **Duties.** Each slot with uncovered crew becomes a duty
   `<Demand ID>-<YYYYMMDD>`:
   * *demand* = slot demand − valid regular-crew rows;
   * *assigned crew* = the fixed Relief/Excess rows;
   * *eligible crew* = every Relief/Excess crew member passing step 6 for
     that date.

   Eligibility is date-dependent, which is why it is stored per duty
   rather than as a crew × activity table.

The optimiser then runs unchanged, with all its sequencing rules (rest, 23 h
transitions, location continuity, swing, lift-up/layback, persistence, base
return). Each solution is still re-checked by the independent validator.

## 4. Outputs added for DB instances

* `roster_disruptions.csv`: one row per regular-crew (or locked) roster row
  that could not be worked, with its reason code: `MEDICAL_UNFIT`,
  `UNAVAILABLE`, `ROLE_NOT_PERMITTED`, `COMPETENCY_MISSING_OR_EXPIRED`,
  `CURRENCY_LAPSED`, `MENTOR_REQUIRED`, `ACTIVITY_RESTRICTED` or
  `NIGHT_RESTRICTED`.
* `summary.json → data_preparation`: demand units, coverage by regular crew,
  disruptions by reason, released rows, crew optimised / excluded, eligible
  list sizes, constraint warnings and the columns that are not modelled.

## 5. Synthetic data (`synthetic_db.py`)

| Element | Synthetic choice |
|---|---|
| Depots | Haskett, Yarmouth, Madison, Nelaway, Bethway (placeholders consistent with the activity heads) |
| Activities | 16 demanded activities under the 14 supplied activity heads (e.g. *Haskett Mainline* Haskett→Yarmouth and *Haskett Mainline CO* Haskett→Haskett), 2 Standby activities, 1 excluded *Route Learning* activity |
| Shifts | mostly 05:00-17:00 / 17:00-05:00; Madison Yard 06:00-18:00 / 18:00-06:00; Work Train 07:00-19:00 |
| Competencies | Safeworking, route knowledge, traction, dangerous goods, yard, shed, local, track protection, plus one activity sign-off (`AC-<Activity ID>`) per activity |
| Currency | 90 days on mainlines, 60 days on fuel trains |
| Regular crew | 2 Permanent crew per demand unit, alternating 7-day blocks |
| Gaps | unstaffed slot-days (`vacancy_fraction`), plus disruptions of a fraction of Permanent crew: leave, medical, expiring competency, lapsed currency, onsite absence, activity restriction |
| Relief / Excess | 14/14 and 6/6 swings written as Standby rows; rostered 05:00/17:00 (Excess also 04/06/07/16/18); prior duties, commitments after the horizon, time changes already made, leave, away-from-depot, trainees, night restrictions, expiring or suspended competencies, lapsed currency |
| Existing work | some open slots given to an eligible Relief/Excess crew member. Accepted only if the validator says that crew member's roster stays legal; 25% of them unlocked |

Presets (in `data/generated/`, rebuilt by
`python scripts/generate_synthetic_instance.py`; the same seed gives
byte-identical files):

| Preset | Relief/Excess crew (optimised) | Regular crew | Days | Duties | Open units | Eligible per duty (mean / max) |
|---|---|---|---|---|---|---|
| small | 18 | 54 | 5 | 21 | 21 | 2.4 / 6 |
| medium | 130 | 162 | 7 | 100 | 138 | 18 / 36 |
| tight | 54 | 162 | 7 | 134 | 212 | 7.9 / 14 |
| large | 974 | 270 | 14 | 211 | 293 | 66 / 172 |
| xlarge | 973 | 540 | 14 | 299 | 598 | 97 / 173 |

`data/sample/briefing_abc` is the briefing's ABC example in this schema.
Relief crew ABC and six permanent crew staff every slot except the six gaps
ABC covers in the briefing. The known optimum is all six covered, in the
briefing's order.

## 6. Assumptions about the schema (to confirm with OptiFlux)

These parts of the schema were not readable in the supplied screenshots. Each
one is a single entry in `DB_TABLES` / `ASSUMED_COLUMNS` and can be renamed
there.

| Table | What was assumed |
|---|---|
| `crew_restrictions` | columns 1–4 (`Restriction ID`, `CM Id`, `Restriction Type`, `Activity Head`) and the three restriction types |
| `Crew_Onsite_App` | all columns (`Record ID`, `CM Id`, `Date`, `Location`, `Status`) and the status values |
| table 9 | its name (`crew_currency_df`) and columns 1–2 (`Currency ID`, `CM Id`); columns 3–5 were visible |
| `excluded_activities` | columns `Activity ID`, `Activity Name` |
| `activity_priority` | header `Priority`, `Activity Head` (only the ordered values were visible) |

Business-rule interpretations that are also assumptions:

* `activity_demand_df.Shift` is a `HH:MM-HH:MM` time window, and its demand
  applies every day.
* Relief/Excess availability is given by `Activity Type = Standby` roster rows.
* `Is Locked = No` means a Relief/Excess assignment may be re-planned.
  Regular-crew rows are never re-planned.
* `Mentor Required` means trainees may not cover the activity (pairing a
  trainee with their mentor is not modelled).
* Currency is not renewed by duties worked inside the horizon (conservative).
* `TEA Required`, activity `Location` (when Start/End Depot are given),
  `Position`, `Is Mentor` and identity fields are read but not used.
* Positioning is impossible because the schema has no travel times.
* CO / CO-location rules stay disabled. They are not defined in the briefing
  or in the schema.
