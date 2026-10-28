# OptiFlux Railway Crew Rostering and Recovery — Problem Specification

## 1. Purpose and source

This document describes the full crew rostering/recovery problem being explored for OptiFlux: operational context, routes, crew categories, activities, time/location rules, examples, optimization requirements, missing data, and implementation roadmap. It does not include the separate Tabu Search research notes.

The operational facts below are based on the supplied three-page **Crew Rostering Problem.pdf** and project context discussed during implementation planning.

- **Specified in briefing** means explicitly stated in the source.
- **Modeling implication** means a possible way to encode a stated rule, to be confirmed.
- **Needs clarification** means the source does not define the rule sufficiently.

The briefing contains examples that are incomplete or potentially inconsistent. They are preserved as examples rather than silently reconciled into new rules.

## 2. Problem overview

The goal is to use available **Excess and Relief crew** to cover uncovered railway duties while respecting roster patterns and operating constraints. The full problem is not just matching a person to a gap: assignments must be compatible with the person's availability, eligibility, time, location, shift pattern, rest requirements, CO rules, and base-return obligations.

A duty that is feasible in isolation may make later duties infeasible. The model therefore needs to reason about each crew member's sequence of duties over the planning horizon.

Approximate scale discussed during initial scoping—not yet validated dataset statistics:
- Around **300 uncovered 12-hour duties**.
- Around **1,000 available crew members**.
- Up to around **50 eligible crew members** for one uncovered duty.
- A planning horizon potentially up to **14 days**.

## 3. Routes and locations

The supplied briefing identifies these routes:
- Howrah ↔ Yajpur
- Howrah ↔ Nellore

Abbreviations:
- **HWH** — Howrah
- **YAJ** — Yajpur

Explicit route/activity descriptions:
- **Howrah Mainline:** HWH → YAJ
- **Yajpur Mainline:** YAJ → HWH

Other activities are associated with Yajpur and Nellore locations, including crew, shed, and CLO-related activities.

### Location continuity
Location is an explicit constraint. A natural modeling implication is that after a crew member performs a duty from A to B, they finish at B. Their next duty must start at their current location unless a permitted positioning/travel movement connects them to another location. The briefing does not fully define such movements; do not assume independent travel is allowed without confirmation.

### Return to base
The briefing states that on the **last day of a swing or a transition day, the person has to return to their base location**.

Needs clarification: how base is recorded; whether return must occur by a deadline; whether ending a duty at base is sufficient; whether positioning can satisfy the rule; and how the rule applies to duties crossing midnight.

## 4. Crew categories and work patterns

The briefing describes:

| Group | Typical work/off pattern | Associated category |
|---|---|---|
| FIFO | Usually 14 days working followed by 14 days off; “swing 14 days” | Relief |
| Residential | Usually 6 days working followed by 6 days off; “swing 6 days” | Excess |

The briefing describes these as usual patterns. Confirm whether these are strict rules or common patterns, and whether FIFO/Residential and Relief/Excess are equivalent categories or distinct concepts.

### Relief crew
Specified in the briefing:
- Relief crew have an initially rostered work time.
- The time can be changed to another time if other constraints are satisfied.
- Once changed, the person must follow the new time for the remaining days in that swing.
- An example says a Relief person rostered at 5 PM can cover gaps throughout the day.

Example listed for “ABD (relief) → 5PM”:

```text
10 AM, 10 AM, 11 AM, 11 AM
```

The source does not fully explain the meaning or date sequence of this example. Confirm it before treating it as a general rule.

### Excess crew
Specified in the briefing:
- Excess crew are rostered at a specific time that generally cannot change except for **lift-up** and **layback**.
- Lift-up = one hour earlier (`-1 hour`).
- Layback = one hour later (`+1 hour`).
- Once changed, the selected time must be followed for the remaining days in that swing.

For a person EFG rostered at 5 PM from 1 November to 6 November, the briefing lists these feasible patterns:

```text
All days 5 PM
All days 4 PM
All days 6 PM
5 PM, 6 PM, 6 PM, 6 PM, 6 PM, 6 PM
5 PM, 4 PM, ...
4 PM, 4 PM, 5 PM, ...
4 PM, 5 PM, 6 PM, 6 PM, ...
4 PM, 5 PM, 4 PM, 5 PM, ...
```

These examples suggest timing choices persist through the swing, but the precise allowed state transitions are not fully specified. Some examples appear to contain more than one time change. Confirm the exact rule rather than inferring it.

### Swing and off-day questions
The source does not fully define swing start/end dates, how off days are represented, whether recovery work can be assigned on off days, how a swing crosses the planning horizon, or how a change persists into the next swing. These need operational clarification.

## 5. Shift timing and transitions

A **transition** is described as a change from day shift to night shift or night shift to day shift.

The briefing gives this pattern:
- 5 PM shifts for three days.
- Then 5 AM shifts for the next three days.
- Each shift lasts 12 hours.
- Ordinary rest between shifts must be at least **11 hours**.
- During a shift transition, rest must be **23 hours**.

The example says:
- 1 November to 3 November: 5 PM shifts.
- A shift ends at 5 AM on 4 November; rest runs from 4 November to 5 November at 5 AM.
- 5 November to 7 November: 5 AM shifts.

The example does not list a duty on 4 November, which appears to be a transition/rest day. Confirm date counting and whether “three days” means duty start dates or shift-end dates.

A full model may need to track shift type, rostered start time, consecutive days in a pattern, transition status, which rest rule applies, and work/off days. The 11-hour and 23-hour rules must be distinct. Exact triggers for the 23-hour rule need confirmation.

## 6. Activities and demand

The source lists eight activities. Ambiguous notation is retained rather than interpreted as fact.

| Activity | Detail stated in briefing | Needs clarification |
|---|---|---|
| Howrah Mainline | Priority 1; demand 1 at each hour; mentions Howrah and Yajpur | Exact meaning of demand, time slots, and whether it applies at both locations |
| Yajpur Mainline | Listed with `(2)` | Does 2 mean priority, demand, or something else? |
| NP Crew | Demand 2 at each hour | Meaning of NP and relevant locations |
| NP Shed | “Nellore and Nellore” | Confirm whether this is a typo or specific location description |
| Yajpur Crew | `(0, 2, 4, 6, … even)` | Exact meaning of the even-number sequence |
| Nellore Driver | Activity name only | Timing, locations, demand and qualifications |
| Nellore Shed | Activity name only | Timing, location and demand |
| YAJ CLO | Activity name only | Meaning of CLO, duration and location rules |

Howrah Mainline is explicitly called Priority 1. The source does not define a complete priority scale for all other activities. Do not assume `(2)` after Yajpur Mainline means priority 2 without confirmation.

The production data needs a demand table specifying required crew by activity, location and time. “Demand 1 at each hour” must be clarified: it could mean a duty starts each hour, a crew member must be present in each hour, or another operational requirement.

## 7. Eligibility

Eligibility is person-specific. The source gives this example:
- Shrinath is eligible for Howrah Mainline and Nellore Driver.
- Sourendra is eligible for Nellore only.
- The example states Shrinath is assigned to Nellore Driver and Sourendra is Excess/Relief.

The model must explicitly restrict each person to eligible activities. Clarify whether eligibility depends only on activity or also on route, location, vehicle, shift, or crew category; whether qualifications vary over time; and whether eligibility for a mainline activity implies eligibility for its CO duty.

## 8. Crew-on (CO) and CO location

The briefing lists separate **CO constraint** and **CO Location constraint** categories and mentions:
- Howrah Mainline CO
- Yajpur Mainline CO

Its example sequence includes Howrah Mainline (HWH → YAJ), Yajpur Mainline (YAJ → HWH), Yajpur CLO (YAJ → YAJ), and Howrah Mainline CO (HWH → HWH).

The briefing does not formally define “CO.” Do not assume its expansion or semantics. Operations must specify what CO means, when it is required, which crew/activity sequences need it, valid locations, duration, whether it is a duty or status, and how it interacts with mainline duties and eligibility. CO location should be treated as its own rule family, not automatically covered by ordinary location continuity.

## 9. Rest, overlap and midnight

The source states a minimum of 11 hours of rest in ordinary cases and 23 hours for a shift transition. A 12-hour duty starting at 5 PM ends at 5 AM the following day. The next duty's start must leave the appropriate rest interval.

A correct model must distinguish overlapping duties, insufficient rest, ordinary consecutive duties, transition duties, duties crossing midnight, and duties just outside the planning horizon. The exact trigger for 23-hour rest and treatment of boundary duties require confirmation.

## 10. Example sequence from the briefing

The source provides this example for ABC, described as Relief, from 1 November to 7 November, with 5 PM shifts for the first three days and 5 AM shifts for the next three days.

| Date | Activity in source | Route/location | Time |
|---|---|---|---|
| 1 Nov | Howrah Mainline | HWH → YAJ | 5 PM–5 AM |
| 2 Nov | Yajpur Mainline, then Yajpur CLO | Mainline YAJ → HWH; CLO listed YAJ → YAJ | Mainline shown as 5 PM–5 AM; CLO timing not separately specified |
| 3 Nov | Howrah Mainline CO | HWH → HWH | 5 PM–5 AM |
| 4 Nov | No duty listed | Appears to be transition/rest day | Confirm |
| 5 Nov | Howrah Mainline | HWH → YAJ | 5 AM–5 PM |
| 6 Nov | Yajpur Mainline | YAJ → HWH | 5 AM–5 PM |
| 7 Nov | Howrah Mainline CO | HWH → HWH | 5 AM–5 PM |

The source also says “Howrah mainline → Gap” and “Nellore Driver → No Gap.” Their exact meaning is not explained; do not treat them as general rules without clarification. The example is suitable as a test case only after the missing details are confirmed.

## 11. Optimization problem

The optimizer must choose a set of assignments that obey all hard rules and best meets the agreed coverage objective. Some duties may remain uncovered if no feasible crew assignment exists.

Potential decisions, depending on final scope:
- Which crew member covers each uncovered duty.
- Which permitted shift-time pattern is selected for a Relief or Excess crew member.
- Which duties remain uncovered.
- Whether positioning duties are needed/permitted.
- Whether existing assignments can be changed.
- How duties are sequenced over the planning horizon.

### Objective
The supplied briefing does not fully specify the production objective. The current toy model maximizes the number of covered duties, but the final objective should be approved by operations.

Possible components to discuss:
1. Maximize covered duties / minimize uncovered demand.
2. Give priority to high-priority activities, including the stated Priority 1 for Howrah Mainline.
3. Minimize changes to existing assignments, if changes are permitted.
4. Minimize overtime or positioning cost, if relevant.
5. Minimize violations of soft preferences.

These are candidate objectives, not confirmed requirements. Safety and mandatory operating rules should be hard constraints, not penalties that the optimizer may choose to violate.

## 12. Data required for a complete model

### Crew data
- Unique crew ID.
- Crew category and relevant work pattern.
- Base location and current location at horizon start.
- Eligibility/qualifications by activity, route, vehicle or other applicable dimensions.
- Rostered shift start time.
- Swing start/end and work/off pattern.
- Permitted time changes and changes already applied in the current swing.
- Existing assignments before, within and after the horizon as needed for rest/base-return checks.
- Availability and leave/unavailability.

### Duty and demand data
- Unique duty ID.
- Activity.
- Start/end timestamp or a defined duration rule.
- Start/end location.
- Required crew count or demand.
- Priority.
- Eligibility requirements.
- Assigned/uncovered status.
- CO and CO-location requirements.
- Route/positioning and predecessor/successor relationships where relevant.

### Rule/configuration data
- Ordinary minimum rest and transition rest trigger.
- Swing and work/off rules.
- Allowed start times and time-change patterns per crew category.
- Lift-up/layback rules.
- Base-return requirement and deadline.
- CO rules and valid CO locations.
- Permitted positioning movements.
- Objective priorities and weights.
- Planning horizon and treatment of duties crossing its boundaries.

## 13. Current simplified prototype — Version 1

A toy model was planned to validate the data pipeline and basic assignment/sequencing before implementing the complete rule set.

### Included
- Fixed 12-hour duties.
- Initial location per crew member.
- Start/end locations for duties.
- Person-specific eligibility.
- At most one assigned duty per crew member per calendar start day.
- At most one crew member per duty.
- At least 11 hours between consecutive duties.
- Location continuity between consecutive duties.
- No independent travel/positioning; movement only through assigned duties.
- Objective: maximize covered duties.
- OR-Tools CP-SAT solver.

Input CSVs:
- `crew.csv`: `person_id`, `initial_location`
- `duties.csv`: `id`, `start`, `start_location`, `end_location`, `activity`, `eligible`

The `start` format is `YYYY-MM-DD HH:MM`; `eligible` contains semicolon-separated crew IDs. End time is calculated as start plus 12 hours.

### Excluded from Version 1
- Relief/Excess distinction and swing rules.
- Rostered shift-time patterns.
- 23-hour transition rest.
- CO and CO-location rules.
- Positioning duties and independent movement.
- Return-to-base rules.
- Existing rostered duties outside the supplied uncovered-duty list.
- Activity priorities and a multi-component objective.
- Complete operational rule coverage.

The “one duty per calendar start day” rule is a simplifying assumption and may not match real rules for overnight duties.

### Validation needed
1. Build tiny synthetic cases with known expected solutions.
2. Test eligibility, initial location, location continuity, rest, daily cap and coverage independently.
3. Include cases where no feasible assignment exists.
4. Verify every returned assignment against every encoded rule.
5. Add new rules one at a time with positive and negative test cases.
6. Scale only after the small formulation is validated.

## 14. Open questions that block a reliable full model

### Crew and swing
- Are FIFO/Residential and Relief/Excess equivalent categories or separate dimensions?
- How are swing dates and work/off days defined?
- Can work be assigned on off days?
- What exact sequences of 5 PM, 4 PM and 6 PM starts are allowed for Excess?
- Does a time change persist through all remaining workdays?
- Can a time be changed more than once during a swing?

### Duties and demand
- What do NP, CLO and CO mean?
- What does `(2)` after Yajpur Mainline mean?
- What does the even-number pattern for Yajpur Crew represent?
- Are all activities 12 hours, including shed, CLO and CO?
- What exactly does “demand 1 at each hour” mean?
- Are demands required simultaneously at both named locations?

### Time and rest
- When exactly does the 23-hour rule trigger?
- How are start dates and end dates counted around midnight?
- Is the example's transition day mandatory?
- How are duties outside the planning horizon included in rest calculations?

### Location and base
- Which positioning movements are allowed, and how long do they take?
- How and by when must a person return to base?
- How do the Nellore routes connect to other locations?

### CO and eligibility
- What is the operational definition of CO?
- Which sequences require it and where?
- Is CO a duty, status, or separate obligation?
- How do eligibility rules apply to CO and related activities?

### Objective and use
- Does coverage count suffice, or must high-priority demand be strictly prioritized?
- May existing assignments be changed?
- What costs/penalties apply to overtime, positioning and schedule changes?
- Which rules are hard constraints versus soft preferences?
- How should the system explain an uncovered duty?

## 15. Recommended roadmap

### Phase A — Formalize the rulebook
- Define activity codes and abbreviations.
- Confirm crew categories and their relation to work patterns.
- Turn examples into unambiguous date-by-date test cases.
- Classify rules as hard constraints or soft preferences.
- Confirm coverage objective and priority policy.

### Phase B — Validate the toy model
- Use synthetic cases with known answers.
- Test eligibility, location, time, rest and coverage.
- Review the sequence formulation and edge cases.
- Report solver status, coverage, objective and runtime.

### Phase C — Add constraints incrementally
Suggested order, subject to dependencies:
1. Existing rostered duties and horizon boundaries.
2. Crew categories and swing/work-off patterns.
3. Shift timing and time-change rules.
4. Day/night transitions and 23-hour rest.
5. CO and CO-location requirements.
6. Positioning duties and permitted movement.
7. Return-to-base rules.
8. Demand priorities and approved objective.

### Phase D — Scale and assess
- Test larger synthetic instances.
- Track runtime, coverage and solver status.
- Check behavior when full coverage is impossible.
- Revisit the formulation if it becomes too large.
- Compare against historical anonymized cases with operational review.

### Phase E — Operational readiness
- Compare recommendations with human-created recovery plans.
- Explain why duties remain uncovered or assignments are infeasible.
- Protect sensitive crew and timetable data.
- Do not use the prototype for live operational decisions until rules and outputs are validated and approved.

## 16. Summary

The OptiFlux problem is a multi-day railway crew recovery/rostering problem in which Excess and Relief crew must cover uncovered duties while satisfying eligibility, shift timing, location, rest, CO, CO-location and return-to-base requirements. The briefing identifies routes between Howrah, Yajpur and Nellore, several activities, different crew work patterns, and 11-hour ordinary and 23-hour transition rest requirements. It also indicates that permitted time changes depend on crew category and persist through the remainder of a swing.

The current CP-SAT prototype deliberately simplifies the problem to fixed 12-hour duties, eligibility, initial locations, location continuity, 11-hour rest, and maximizing coverage. It is a development baseline, not a complete representation of railway operations. The next priority is to clarify ambiguous rules and validate the toy model with test cases before implementing the full constraint set.
