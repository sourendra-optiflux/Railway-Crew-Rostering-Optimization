# OptiFlux Crew Rostering

A prototype for railway crew recovery and rostering, built to explore
how uncovered duties can be assigned to available crew members while
respecting basic operational constraints.

> **Status:** Version 1 --- simplified proof of concept. This is not a
> production rostering system.

## Objective

The initial model aims to maximize the number of uncovered duties
assigned to eligible crew members.

It is intentionally small in scope so that the data pipeline and
optimization model can be tested before adding more detailed railway
operating rules.

## Current model scope

The prototype models:

-   Crew members and their initial locations.
-   Duties with a start time, start location, end location, activity,
    and eligible crew list.
-   A fixed duration of 12 hours per duty.
-   At most one assigned duty per crew member per calendar start day.
-   Eligibility restrictions for each duty.
-   At least 11 hours of rest between consecutive duties.
-   Location continuity: a crew member must be at a duty's start
    location to perform it.
-   Location changes only through an assigned duty; no independent
    travel or positioning is allowed.
-   Maximization of the total number of covered duties.

For a duty starting at time `start`, its end time is calculated as
`start + 12 hours`.

## Repository structure

A suggested layout is:

``` text
OptiFlux-Crew-Rostering/
├── notebooks/
│   └── crew_recovery_v1.ipynb
├── data/
│   ├── crew_sample.csv
│   └── duties_sample.csv
├── README.md
└── .gitignore
```

Use synthetic or anonymized sample data in the repository. Keep actual
operational data out of Git.

## Requirements

The notebook is designed to run in Google Colab and uses:

-   Python
-   pandas
-   OR-Tools CP-SAT

Install the solver in a Colab cell:

``` python
%pip install -q ortools
```

## Input data

The prototype expects two CSV files.

### `crew.csv`

  -----------------------------------------------------------------------
  Column                              Description
  ----------------------------------- -----------------------------------
  `person_id`                         Unique crew identifier

  `initial_location`                  Crew member's location at the start
                                      of the planning horizon
  -----------------------------------------------------------------------

Example:

``` csv
person_id,initial_location
CREW_001,Howrah
CREW_002,Yajpur
```

### `duties.csv`

  Column             Description
  ------------------ ---------------------------------------------------------
  `id`               Unique duty identifier
  `start`            Start date and time in `YYYY-MM-DD HH:MM` format
  `start_location`   Location where the duty begins
  `end_location`     Location where the duty ends
  `activity`         Duty or activity name
  `eligible`         Semicolon-separated list of eligible `person_id` values

Example:

``` csv
id,start,start_location,end_location,activity,eligible
DUTY_001,2026-01-01 05:00,Howrah,Yajpur,Howrah Mainline,CREW_001;CREW_002
DUTY_002,2026-01-01 17:00,Yajpur,Howrah,Yajpur Mainline,CREW_002
```

The examples above are illustrative only. Ensure that every crew ID in
`eligible` exists in `crew.csv`.

## Run in Google Colab

1.  Open `notebooks/crew_recovery_v1.ipynb` in Google Colab.

2.  Put `crew.csv` and `duties.csv` in your Google Drive project folder,
    for example `MyDrive/Optiflux_Crew_Rostering/`.

3.  Mount Google Drive:

    ``` python
    from google.colab import drive
    drive.mount('/content/drive')
    ```

4.  Set the project directory in the notebook to match your Drive
    folder.

5.  Run the notebook cells in order: install/import dependencies, load
    and validate data, build the model, solve, inspect results, and
    export outputs.

The notebook exports the assignment and uncovered-duty results as CSV
files when a feasible or optimal solution is found.

## Outputs

The prototype produces:

-   **Assignments output:** duties assigned to crew, including start/end
    times, activity, and locations.
-   **Uncovered output:** duties that were not assigned to any crew
    member.

A duty is counted as covered only when it is assigned to a crew member
by the solver.

## Important limitations

This version does **not** yet model:

-   Relief and Excess crew distinctions.
-   Swing schedules or rostered work/off patterns.
-   Existing rostered duties outside the uncovered-duty input.
-   Positioning duties or independent crew movement.
-   Crew-on (CO) rules or CO location requirements.
-   Special 23-hour rest requirements for day/night shift transitions.
-   The requirement to return to base on the last day of a swing or
    transition day.
-   Activity-specific or priority-weighted objectives.
-   Full operational validation of every railway rule.

The current "one duty per calendar start day" rule is a simplifying
assumption and should be reviewed against the actual operating
requirements. The output should be treated as an experimental solution,
not as an operational roster.

## Next steps

Potential extensions:

1.  Validate the simplified model against hand-worked toy examples.
2.  Add explicit test cases for location continuity, eligibility, rest,
    and uncovered duties.
3.  Introduce crew types and swing rules.
4.  Add existing roster duties and positioning duties.
5.  Implement CO, base-return, and shift-transition rules.
6.  Add duty priorities and evaluate trade-offs between coverage and
    operational preferences.
7.  Test on anonymized data before any operational use.

## Data privacy

Do not commit confidential crew identities, schedules, or operational
railway data to a public repository. Use synthetic data in examples and
notebooks, and clear notebook outputs before publishing if they contain
real operational information.

## Disclaimer

This repository is a learning and prototyping project. Its model
assumptions are deliberately simplified and must be checked against the
applicable operating rules before any real-world use.
