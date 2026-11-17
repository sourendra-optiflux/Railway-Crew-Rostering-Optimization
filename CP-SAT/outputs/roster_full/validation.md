# Rule check of the optimised roster

`scripts/check_roster.py` on the optimised roster, compared with the roster after leave, plus recovery
checks V1-V6. `fails after leave too` means leave alone already breaks that rule (for example open seats).

**38 of 44 pass; 0 unexpected failure(s).**

| Rule | Check | Result | Detail |
|---|---|---|---|
| — | Assignment IDs are unique | PASS |  |
| — | Every row's activity exists; Assignment Type is known | PASS |  |
| — | `In Horizon` matches the start date | PASS |  |
| D1 | Demand `Shift` holds a start time only (HH:MM) | PASS |  |
| D3/D4 | NE Task and BY Shed are renamed (NE Crew, BY Ship) | PASS |  |
| G1 | Every demand slot on every horizon day has exactly its demand (171 crew-shifts/day x 30 days) | fails after leave too | DM004 Haskett Mainline 2026-11-02 03:00: 0/1; DM004 Haskett Mainline 2026-11-04 03:00: 0/1; DM004 Haskett Mainline 2026-11-06 03:00: 0/1 (+68 more) |
| G1 | Demand rows carry the Demand ID of their activity and start time | PASS |  |
| G1 | No slot (in or outside the horizon) has more Demand rows than its demand | PASS |  |
| G5 | Excess rows are on work activities whose slot is already fully covered (surplus) | fails after leave too | AS0001627; AS0001628; AS0001629 (+21 more) |
| G6 | Relief rows: Activity Name = Activity Head = Relief, no Demand ID | PASS |  |
| G6 | Only Relief rows use the Relief activity | PASS |  |
| G9 | Initial roster has no leave (crew_restrictions empty, everyone Fit) | PASS |  |
| G2 | No 'no activity' rows yet (deferred) | PASS |  |
| R4 | Is Locked = False on every row (only a user locks rows, in the application) | PASS |  |
| OFF | Off rows: Activity Name Off, Activity Head RR, inside the horizon, no Demand ID | PASS |  |
| OFF | At most one Off row per person per day, never on a day with a shift | PASS |  |
| D2 | Every work row lasts 12 h | PASS |  |
| M1-M4 | Crew per depot and classification meets the targets (more allowed) | PASS | Haskett/Residential 210, Haskett/FIFO 70, Yarmouth/FIFO 210, Nelaway/Residential 140, Nelaway/FIFO 70 |
| M5 | Classification is Residential or FIFO | PASS |  |
| — | Every roster user is in the crew list, and everyone in the crew list is rostered | PASS |  |
| C1 | No CM Id: per-person tables are keyed by User Id | PASS |  |
| F* | No overlapping shifts | PASS |  |
| F* | At least 11 h rest between shifts | PASS |  |
| F* | At least 23 h rest when switching day <-> night | PASS |  |
| F* | At most one shift starting per person per day | PASS |  |
| F* | Swing length: no more shifts in a swing than its work days (FIFO 14, Residential 6) | PASS |  |
| F* | Off time between swings at least the off days (FIFO 14, Residential 6) | fails after leave too | U100124 before 2026-11-27 (4 days, 0:00:00); U100553 before 2026-11-12 (7 days, 0:00:00); U100273 before 2026-11-11 (10 days, 0:00:00) (+8 more) |
| R1 | Residential: the first shift of every swing is a day shift | fails after leave too | U100124 swing from 2026-11-27 starts 16:00; U100588 swing from 2026-11-15 starts 16:00; U100074 swing from 2026-11-13 starts 19:00 (+18 more) |
| F* | Location continuity: each shift starts where the previous one ended, at the activity's depots | PASS |  |
| F* | Every swing starts and ends at the person's home depot | fails after leave too | U100273 swing from 2026-11-01 |
| F1-F3 | FIFO: one Travel In before the first shift and one Travel Out after the last shift of every swing | fails after leave too | U100553: 3 swings, 2 in, 2 out; U100273: 3 swings, 2 in, 2 out; U100461: 3 swings, 2 in, 2 out (+7 more) |
| F1 | Residential crew have no travel rows | PASS |  |
| F3 | Start time changes at most 1x per day/night block, by at most 60 min | PASS |  |
| — | Work rows only on activities in the person's Eligibility | PASS |  |
| — | The person's Role is allowed by the activity's Roles/Job | PASS |  |
| — | The person holds every competency the activity needs, valid on the duty date | PASS |  |
| — | Currency: the activity head was performed within its threshold before each duty | PASS |  |
| R5 | eligibility_matrix.csv = crew_competencies_df joined with compliance_matrix_df | PASS |  |
| V1 | Rows before the solver start are unchanged (G1) | PASS |  |
| V2 | No seat has more people than its demand | PASS |  |
| V3 | Everyone placed on a new seat is certified (matrix), fit, in role and current | PASS |  |
| V5 | Swings that started before the solver start or are on leave lose no rows (F4) | PASS |  |
| V6 | Changed people: rest, Relief-only day/night transition, one shift a day, location, one start change per block | PASS |  |
| V7 | Changed Residential assignments do not start from 22:00 to 02:00 | PASS |  |
