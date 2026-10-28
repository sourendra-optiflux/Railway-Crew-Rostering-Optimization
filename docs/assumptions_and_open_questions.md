# Assumptions and Open Questions

This table separates what the OptiFlux briefing
(`Optiflux_crew_rostering_problem.md`, the primary source) **says**, from what
the prototype **does**. Every behaviour that is not a direct reading of the
source is either an *implementation assumption* (switchable in
`ModelConfig`) or *disabled*. Nothing ambiguous is resolved silently.

Legend for "Status":

* **Hard** — implemented as a hard constraint, as specified.
* **Hard (approx.)** — a hard constraint, but the exact rule is an approximation.
* **Assumption** — not in the source; a prototype choice, switchable.
* **Disabled** — interface exists, but no rule is enforced.
* **Data only** — parsed and reported, never constrains the solution.

Categories, as required by the project brief: **S** = specified requirement,
**A** = implementation assumption, **R** = research-derived idea, **Q** = open
operational question.

## 1. Rule table

| # | Operational rule | What the source says | Current implementation | Status | Why | Information needed to improve |
|---|---|---|---|---|---|---|
| 1 | Eligibility | Person-specific, by activity (§7, Shrinath/Sourendra example) | Activity table and/or per-duty list; exact activity names; no information means not eligible | Hard (S) | Specified | Does eligibility depend on route, vehicle, shift or category? Can qualifications change over time? |
| 2 | Eligibility for CO duties | "Whether eligibility for a mainline activity implies eligibility for its CO duty" is open | Not implied: "Howrah Mainline CO" needs its own row | Hard (A) | Conservative, never assumes eligibility | Q-CO-4 |
| 3 | One crew per single-crew duty; multi-crew demand | "NP Crew: demand 2 at each hour" | `demand` column; `e_i ≤ n_i ≤ δ_i`; partial or all-or-nothing counting | Hard (S, A for counting) | Demand needed for NP Crew | Q-DEM-1, Q-DEM-2: what "demand at each hour" means |
| 4 | Duty duration | "300 uncovered 12-hour duties" | `end` column, or `duration_hours`, else 12 h | Hard (S default) | Allows shorter CLO/CO/shed duties if they exist | Q-DEM-3: are all activities 12 h? |
| 5 | Overlap | Implied (§9) | No two assigned duties of a crew member overlap (follows from rest on consecutive arcs) | Hard (S) | — | — |
| 6 | Ordinary rest | "at least 11 hours" | `S_j ≥ E_i + 11 h` between consecutive duties, including the prior duty and next commitment | Hard (S) | Specified | — |
| 7 | Transition rest | "During a shift transition, rest must be 23 hours" | 23 h when consecutive duties have different shift types (DAY/NIGHT); not applied otherwise | Hard (approx.) | Pairwise reading of "transition" | Q-TIME-1: exact trigger |
| 8 | Day vs night classification | 5 AM shifts = day, 5 PM shifts = night (examples) | DAY iff start ∈ [03:00, 15:00), configurable; a `shift_type` column overrides | Assumption (A) | Only two example times exist | Q-TIME-2: official definition of day/night shifts |
| 9 | Duties crossing midnight | "A 12-hour duty starting at 5 PM ends at 5 AM the following day" | True end timestamps; date of a duty = start date | Hard (S) / date rule (A) | Needed for swing and cap | Q-TIME-3: which date does an overnight duty belong to? |
| 10 | Horizon boundaries | "duties just outside the planning horizon" need treatment | `prior_duty_end`/`prior_shift_type` and `next_commitment_*` per crew member, checked with rest, transition, location and base rules | Hard (A for data format) | Specified need; format invented | Q-TIME-4: what pre/post-horizon data will be available? |
| 11 | Location continuity | "Location is an explicit constraint"; next duty starts where the last ended | Exact location equality between consecutive duties and from the initial location | Hard (S) | Specified | — |
| 12 | Positioning / independent travel | "do not assume independent travel is allowed without confirmation" | **Off by default.** Optional single-leg links from `travel.csv` with **synthetic** times; travel added to rest; cost minimised after coverage | Disabled by default (A) | Not confirmed | Q-LOC-1, Q-LOC-2 |
| 13 | Relief vs Excess | Two categories with different time flexibility (§4) | `crew_type` column; separate policies and offsets per type | Hard (S) | Specified | Q-CREW-1: are FIFO/Residential the same as Relief/Excess? |
| 14 | Swing pattern | Relief "usually" 14 on/14 off, Excess "usually" 6 on/6 off | Per-crew `work_days/off_days`, default by type; cycle anchored at `swing_start_date` | Hard (approx.) | "Usually", so per-crew override | Q-CREW-2: are patterns strict? |
| 15 | Work on off days | Not defined | Not allowed (`enforce_swing_work_days`) | Assumption (A) | Conservative | Q-CREW-3 |
| 16 | Excess time change | Only lift-up (−1 h) or layback (+1 h) | Start time-of-day ∈ rostered + {−60, 0, +60} min (exact, circular clock) | Hard (S) | Specified | Is ±1 h relative to the original roster or to the current time? (we use the original) |
| 17 | Relief time change | "can be changed to another time if other constraints are satisfied"; can "cover gaps throughout the day" | Any time of day (offset set = all), configurable | Hard (S) | Specified | Q-CREW-4: any limits? |
| 18 | Time-change persistence | "Once changed, the person must follow the new time for the remaining days in that swing" — but the EFG and Relief examples contain several changes | Default `persist_after_change`: after the first duty at a non-reference time, later duties in the swing must keep that time. `window_only` accepts all example patterns. Resets at a new swing | Hard (approx.) | Text and examples conflict; the strict reading is the conservative default (its rosters are also legal under the loose reading) | Q-CREW-5, Q-CREW-6 |
| 19 | Changes made before the horizon | Implied by persistence | `current_start_time` locks the current swing to that time | Hard (A for format) | — | Q-TIME-4 |
| 20 | Daily cap | Not in the source (V1 assumption); the briefing's 2 Nov example lists two activities on one day | At most 1 duty *start* per date, configurable or off | Assumption (A) | Kept from V1; mostly redundant with 11 h rest | Q-TIME-5 |
| 21 | Base return at swing end | "On the last day of a swing … has to return to their base" | Location after the last duty of a swing must be base (duty ends there, or positioning if enabled); only if that swing ends inside the horizon | Hard (approx.) | No deadline or mechanism given | Q-BASE-1 … Q-BASE-4 |
| 22 | Base return on transition day | "or a transition day" | Between consecutive DAY↔NIGHT duties, the crew member must pass through base | Hard (approx.) | Consistent with the ABC example (the duty before the transition ends at HWH) | Q-BASE-5 |
| 23 | Base at horizon end | Not stated | Off (`base_return_at_horizon_end`) | Assumption (A) | Not required when the swing continues | Q-BASE-1 |
| 24 | CO requirement | Separate "CO constraint" category; "Howrah/Yajpur Mainline CO" listed; meaning not defined | CO duties are ordinary duties with their own name, eligibility and locations. **No CO rule is enforced.** Interface in `constraints/co_rules.py` | Disabled | Semantics unknown — not invented | Q-CO-1 … Q-CO-4 |
| 25 | CO location | Separate "CO Location constraint" category | `co_location` column parsed, validated and reported | Data only | Semantics unknown | Q-CO-2 |
| 26 | Activity priorities | Howrah Mainline = Priority 1; "(2)" after Yajpur Mainline unexplained | `priority` column; the priority level breaks ties *after* coverage by default; weights configurable; order configurable | Assumption (A) | Only one priority is known; the objective is unapproved | Q-OBJ-1 |
| 27 | Objective | "maximize coverage"; other components are candidates | Lexicographic: coverage → priority → positioning → time changes → roster changes | S (coverage), A (rest) | Safety rules stay hard | Q-OBJ-1 … Q-OBJ-3 |
| 28 | Existing assignments | "Whether existing assignments can be changed" is open | `assigned_crew` column; `fixed` (default) or `reassignable` (keep coverage, minimise moves) | Hard / A | Both modes supported | Q-OBJ-2 |
| 29 | Leave / unavailability | Listed under data needed | `unavailable_dates` per crew member | Hard (A for format) | — | — |
| 30 | Yajpur Crew "(0, 2, 4, 6 … even)" | Unexplained | Not modelled | Disabled | Unknown meaning | Q-DEM-4 |
| 31 | "Howrah mainline → Gap", "Nellore Driver → No Gap" | Unexplained | Not modelled | Disabled | Unknown meaning | Q-DEM-5 |
| 32 | Pairwise duty arcs, independent checker | — | Candidate arcs and a separate validator | R | Yu et al. (2025) parameters `q`, `p`; RCSP benchmark connection files and checker | — |
| 33 | Greedy hint, MIP cross-check, tiny tests | — | `heuristics.py`, `mip_crosscheck.py`, brute-force tests | R | `Progress/CP_SAT_vs_MIP_Solvers.pdf` | — |

## 2. Open operational questions

These need answers from OptiFlux / railway operations before the prototype can
be trusted on real data. The ids are referenced in the table above.

### Crew and swing
* **Q-CREW-1** Are FIFO/Residential and Relief/Excess the same categories or separate dimensions?
* **Q-CREW-2** Are 14/14 and 6/6 strict, or only typical? Where are swing dates recorded?
* **Q-CREW-3** Can recovery work be assigned on off days (e.g. with consent or overtime)?
* **Q-CREW-4** Are there limits on Relief time changes (earliest/latest start, maximum shift)?
* **Q-CREW-5** Exactly which sequences of start times are allowed for Excess? (The EFG list contains `4 PM, 5 PM, 4 PM, 5 PM`, which contradicts "once changed … follow the new time".)
* **Q-CREW-6** Does a time change persist into the next swing?

### Duties and demand
* **Q-DEM-1** What exactly does "demand 1 at each hour" (Howrah Mainline) / "demand 2 at each hour" (NP Crew) mean: a duty starting every hour, or presence in every hour?
* **Q-DEM-2** Are demands required simultaneously at both named locations (Howrah and Yajpur)?
* **Q-DEM-3** Are CLO, shed and CO duties also 12 h?
* **Q-DEM-4** What does the even-number pattern for Yajpur Crew represent?
* **Q-DEM-5** What do "Gap" / "No Gap" mean in "Howrah mainline → Gap" and "Nellore Driver → No Gap"?
* **Q-DEM-6** What do NP, CLO and CO stand for?

### Time and rest
* **Q-TIME-1** When exactly does the 23 h rule trigger? Any DAY↔NIGHT change between consecutive duties (current implementation), or only a change of the *rostered* shift?
* **Q-TIME-2** What are the official day and night shift definitions (time windows)?
* **Q-TIME-3** Which date does an overnight duty belong to, for swings and daily limits?
* **Q-TIME-4** Which pre-horizon and post-horizon data will be supplied (last duty end, current time state, first rostered duty after the horizon)?
* **Q-TIME-5** Is there a daily limit on duties, given that the 2 Nov example lists "Yajpur Mainline, then Yajpur CLO"?
* **Q-TIME-6** Is the transition (rest) day in the ABC example mandatory, and does it have to be a full calendar day?

### Location and base
* **Q-LOC-1** Which positioning movements are allowed (deadheading on trains, road transport)? What are their real durations and costs?
* **Q-LOC-2** Does travel time count as rest?
* **Q-LOC-3** Which real stations do "Yajpur" (YAJ) and the Nellore activities refer to? (Public timetables suggest Jajpur Keonjhar Road on the Howrah–Chennai line, but this has **not** been confirmed and is not used.)
* **Q-LOC-4** How do the Nellore routes connect to Howrah and Yajpur in practice?
* **Q-BASE-1** By when must the crew member be back at base (end of the last swing day, or before the first off day)?
* **Q-BASE-2** Is ending a duty at base sufficient? Can positioning satisfy the rule?
* **Q-BASE-3** How is base recorded, and can it differ from the depot of the rostered duties?
* **Q-BASE-4** How does the rule apply to a night duty that starts on the last swing day and ends on the first off day?
* **Q-BASE-5** On a transition day, must the crew member be at base *during* the rest, or only at some point?

### CO
* **Q-CO-1** What is the operational definition of CO? Is it a duty, a status, or an obligation attached to another duty?
* **Q-CO-2** What does the CO-location constraint require?
* **Q-CO-3** Which duty sequences require a CO duty, and where?
* **Q-CO-4** How does eligibility for a mainline activity relate to eligibility for its CO duty?

### Objective and use
* **Q-OBJ-1** Is coverage count enough, or must Priority-1 demand be covered first (strict priority)? What is the full priority scale?
* **Q-OBJ-2** May existing assignments be changed during recovery? At what cost?
* **Q-OBJ-3** What costs apply to overtime, positioning and time changes? Which rules are hard and which are soft?
* **Q-OBJ-4** How should the system explain an uncovered duty? (The prototype gives a reason code; see `codebase_guide.md` §8.)

## 3. How to change an assumption

All switches are fields of `ModelConfig` (`src/railway_rostering/config.py`).
Override them in a JSON file (`--config my.json`) or on the command line:

```bash
python scripts/run_example.py --instance-dir data/generated/medium \
  --set 'time_change_policy={"RELIEF":"window_only","EXCESS":"window_only"}' \
  --set max_duties_per_day=null --set transition_rest_hours=24
```

The independent validator reads the same `ModelConfig`, so it always checks
the rules that were enabled for the run.
