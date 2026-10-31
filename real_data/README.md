# real_data — template for loading real OptiFlux data

`optiflux_db_template.xlsx` is a **blank** workbook with one sheet per
OptiFlux database table. Each sheet has the exact column headers that the
synthetic CSV files in `data/` use. Fill it in, and the solver reads it
directly.

| Sheet | Content |
|---|---|
| `roster_df` | every rostered shift (regular crew and Relief/Excess, incl. `Standby` availability rows) |
| `activities_df` | activity catalogue (depots, roles, mentor, currency threshold, Can Be Moved) |
| `activity_demand_df` | crew required per activity and shift (applies every day of the horizon) |
| `crew_restrictions` | leave / activity / night restrictions by date |
| `crew_competencies_df` | competencies held, with expiry and status |
| `compliance_matrix_df` | competencies each activity requires |
| `crew_master_data_df` | crew (Classification Relief/Excess = optimised, Depot = base, Role, Medical, Mentor Id) |
| `Crew_Onsite_App` | onsite check-ins (location, Absent/Sick) |
| `crew_currency_df` | last date each crew member worked each activity head |
| `constraints_df` | rules and planning horizon (`Planning Horizon Start` and `Planning Horizon Days` are required) |
| `excluded_activities` | activities not to be covered |
| `activity_priority` | activity heads in priority order (1 = highest) |

## How to fill it

* **Headers.** Keep the header row and the sheet names as they are. Extra
  columns are ignored.
* **Header colours.** Dark-blue headers come from the supplied schema.
  **Orange headers are assumed names**: they were not visible in the schema
  screenshots. Rename them in `src/railway_rostering/db_schema.py`
  (`DB_TABLES`) if the real names differ.
* **Header comments.** Hover over a header to see how the column is used.
  Full reference: `docs/db_schema.md`.
* **Formats.** Dates are `YYYY-MM-DD`, times `HH:MM`, shifts `HH:MM-HH:MM`,
  flags `Yes`/`No`, and lists are separated by `;`. The first 1,000 rows are
  formatted as text so IDs keep leading zeros. Real Excel date/time cells are
  also understood.
* **Required sheets.** `roster_df`, `activities_df`, `activity_demand_df`,
  `crew_master_data_df` and `constraints_df` must have rows. The other sheets
  may stay empty.
* **A worked example.** To see a filled-in workbook, run:

  ```bash
  python scripts/make_excel_template.py --from-dir data/generated/medium --output real_data/example_medium.xlsx
  ```

## How to run on it

Save your filled copy under a new name (e.g. `real_data/nov_2026.xlsx`), then:

```bash
python scripts/run_example.py --instance-dir real_data/nov_2026.xlsx --output-dir outputs/nov_2026
```

From Python:

```python
from railway_rostering import load_instance, solve_instance
result = solve_instance(load_instance("real_data/nov_2026.xlsx"))
```

## Privacy

Only the blank template and this README are tracked by git (see
`.gitignore`). Any other file you put in `real_data/` stays on your machine.
**Do not commit real crew data.** To regenerate the blank template, run:

```bash
python scripts/make_excel_template.py
```
