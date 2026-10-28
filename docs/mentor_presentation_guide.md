# Mentor Presentation Guide

How to explain this project accurately, based on what is actually committed.
Numbers are taken from `validation_report.md`, which records the commands and
environment.

## 1. The original OptiFlux problem

OptiFlux has **uncovered railway duties**: around 300 twelve-hour duties
(a preliminary estimate) over a horizon of up to 14 days, on the Howrah–Yajpur
and Howrah–Nellore routes. It also has a pool of **Relief** and **Excess** crew,
around 1,000 people, with up to about 50 eligible per duty. Each crew member has
qualifications (activities such as Howrah Mainline, Yajpur Mainline, NP Crew,
NP Shed, Yajpur Crew, Nellore Driver, YAJ CLO, CO duties), a location, a base,
a swing pattern (Relief usually 14 on / 14 off, Excess 6 on / 6 off) and a
rostered start time. Excess crew may move their start time only by one hour
(lift-up or layback). Relief crew may change it more freely, and a change
must then be kept for the rest of the swing. Rest is at least 11 h, or 23 h
when a crew member switches between day and night shifts. On the last swing
day or a transition day the person must return to base. The task: **cover as
much demand as possible without breaking any of these rules.**

## 2. Why this is an optimisation problem, not a simple assignment

A simple assignment (bipartite matching) treats each duty independently. Here,
**taking one duty changes what the same person can do next**: they end up
somewhere else, they need 11 or 23 h of rest, their start time may become
locked for the swing, and they may have to be back at base. A duty that is
feasible on its own can therefore block two later duties. Example from the
data: on the `medium` instance the greedy heuristic, which takes each duty in
time order, covers 96 units, while the optimiser covers 117. The difference
comes entirely from choosing sequences instead of single assignments.

## 3. The formulation selected

For each crew member we build a small **time-ordered graph** of the duties they
could do. An arc `i → j` exists only if `j` may *directly follow* `i`: enough
rest (11 h, or 23 h on a day/night change), the right location (or a permitted
positioning trip), the time-change rule, the daily cap, and passing through
base when a swing ends or the shift type changes. CP-SAT then chooses for each
crew member **one path** through their graph (`AddCircuit`), subject to
per-duty demand. It maximises covered demand first, then priority, then
smaller tie-breakers (positioning cost, time changes, roster changes), solved
lexicographically.

## 4. Why OR-Tools CP-SAT

* Native `AddCircuit` encodes "these duties form one ordered chain" exactly.
* Conditional rules are natural in CP-SAT (the repository's
  `Progress/CP_SAT_vs_MIP_Solvers.pdf` gives the reasoning). Most of them are
  in fact pre-computed into the arc set.
* It returns good solutions early (the greedy hint is accepted as complete)
  and reports a bound, so we can say OPTIMAL versus FEASIBLE honestly.
* It is free and pip-installable.

Caveat found during the work: CP-SAT found the optimum quickly but was slow to
*prove* it (about 40 s on `large`). The LP relaxation of the equivalent flow
model was already tight, so I added a **mathematically valid LP-bound cut**
(GLOP). All stages on `large` are now proven optimal in about 10 s. A flow MIP
in SCIP is used as a cross-check, and on most instances it agrees and is fast.
It is not always fast, though: on the `tight` instance with rules relaxed it
did not finish in 60 s.

## 5. Role of the variables and constraints

| Element | Role |
|---|---|
| `x[c,i]` | crew member `c` does duty `i` (only for candidate pairs) |
| `arc[c,u,v]` | `v` directly follows `u` in `c`'s sequence |
| `empty[c]` | `c` gets no duty |
| `AddCircuit` per crew | the chosen `x` form one chronological path through legal arcs |
| demand rows | `existing ≤ crew on duty ≤ demand` |
| fixed rows | existing roster kept (or reassignable mode) |
| cliques, flow rows, LP cut | strengthening only; they never remove a legal roster |

**Hard constraints are never in the objective.** Coverage cannot be bought by
breaking rest.

## 6. How the solver handles a crew member's sequence

Node 0 stands for "start" and "end". Each candidate duty has a self-loop that
is true when the duty is skipped. `AddCircuit` forces the remaining nodes into
one cycle `0 → i₁ → … → i_k → 0`. Arcs only go forward in time, so the cycle
is the crew member's chronological sequence. Because every consecutive pair
satisfies rest, no two duties overlap, and because location carries from duty
to duty, nobody teleports. That is why checking *consecutive* pairs is
enough (proof in `problem_formulation.md` §6.1).

## 7. Dataset strategy

I searched for public data: OR-Library crew and rail set-covering instances,
nurse-rostering benchmarks, an airline crew dataset, the ROMSOC DB Cargo data,
the RCSP railway crew-scheduling benchmark, Indian Railways timetables, and NS
datasets. **None contains crew-level recovery data with Relief/Excess pools and
swing patterns**, and timetables contain no crew at all. Several hosts were
blocked in my environment, and `dataset_research.md` says which sources were
verified and how. So I built a **seeded synthetic generator** that keeps the
OptiFlux structure (the three locations, all eight activities, Relief/Excess,
swings, 05:00/17:00 shifts, ±1 h starts, boundary duties, existing
assignments, deliberately uncoverable duties). Every file is labelled
synthetic. I also added two hand-checkable instances: the V1 notebook data,
and the briefing's ABC example.

## 8. Most important implementation decisions

1. Pairwise rules are evaluated in Python as arcs; CP-SAT only chooses paths.
2. Ambiguous rules are configurable, with conservative defaults (strict
   time-change persistence, base return, no positioning, no off-day work),
   and each is documented in `assumptions_and_open_questions.md`.
3. CO rules are **not invented**. CO duties are covered like other duties, and
   the CO rule hook is disabled.
4. An independent validator re-checks every solution with separate code.
5. Uncovered duties get a reason code: no eligible crew, nobody available,
   wrong start time, no legal sequence, or used elsewhere.
6. Lexicographic objective: coverage first, never traded against safety.

## 9. What the tests demonstrate

* **171 automated tests pass.** They cover the exact 11 h / 23 h boundaries,
  overlap, midnight crossing, prior and next commitments, location and
  positioning timing, the swing calendar, every EFG example pattern under both
  time-change policies, base-return cases, demand and existing assignments,
  objective ordering, CLI outputs, and generator determinism.
* **Formulation correctness is evidenced, not assumed.** On 300 random tiny
  instances with randomly switched rules, CP-SAT's proven optimum equals an
  exhaustive enumeration checked by the independent validator, in every case
  (40 of these run in CI). On synthetic instances up to 1,000 crew, a
  separate flow MIP (SCIP) on the same arcs gives the same optimum.
* **17 kinds of injected violations** are each caught by the validator.
* Every benchmark solution passes the independent validator.

## 10. Current limitations and open questions

* All data is synthetic. Performance on real data is unknown.
* Base return is approximated as "be at base after the relevant duty", with no
  deadline. The day/night window (03:00–15:00) is an assumption. The
  time-change persistence semantics are uncertain, because the briefing's
  examples contradict its text.
* CO, the "(2)" after Yajpur Mainline, Yajpur Crew's even-number pattern,
  "Gap / No Gap" and "demand at each hour" are not modelled; their meaning is
  unknown.
* No positioning by default. When enabled, travel times are placeholders.
* Non-pairwise limits (e.g. maximum consecutive working days, hours per
  swing) are not modelled.
* The time limit applies per lexicographic stage.
* The full list of questions for operations is in
  `assumptions_and_open_questions.md` §2.

## 11. Next steps

1. Get answers to the open questions, especially CO, the 23 h trigger,
   time-change persistence, base-return timing and positioning.
2. Obtain an anonymised real extract (crew, eligibility, uncovered duties,
   pre-horizon state) and compare the results with planners' manual recovery
   plans.
3. Add the CO rule family once it is defined (the hook is ready).
4. Add non-pairwise rules if operations has them (counter variables).
5. Calibrate the generator to real distributions.
6. If real instances are much larger or eligibility is skewed, move to column
   generation using the same arc rules as the pricing graph.

## 12. Two-minute verbal explanation

> "OptiFlux needs to cover uncovered railway duties with spare Relief and
> Excess crew over up to two weeks. It isn't a simple matching problem,
> because each duty moves a person, starts an 11- or 23-hour rest clock, can
> lock their start time for the swing, and can oblige them to get back to
> base. So one assignment changes what is possible later.
>
> I model each crew member as a path through a time-ordered graph of the
> duties they could do. All the pairwise rules (rest, transition rest,
> location, start-time changes, base return) are checked in Python and
> decide which arcs exist. Then OR-Tools CP-SAT picks one path per person with
> a circuit constraint and maximises covered demand. After that, it breaks
> ties by priority and keeps changes small. Safety rules are hard
> constraints, never penalties.
>
> I couldn't find a public dataset with this kind of crew data, so I wrote a
> seeded generator that keeps the OptiFlux structure, plus hand-checkable
> cases from the briefing. To show the model is correct I compared it against
> brute force on 300 random small cases and against a separate MIP, and every
> solution is re-checked by an independent validator. At roughly the
> estimated real scale — 1,000 crew and 300 duties — it proves the optimum in
> about ten seconds.
>
> What remains is mostly operational definitions: CO rules, the exact
> transition and time-change rules, and base-return timing. I've listed them
> as open questions instead of guessing."

## 13. Likely mentor questions and honest answers

**Q: How do you know the model is correct, and not just producing output?**
A: Three independent checks. (1) Brute force: for 300 random tiny instances,
exhaustive enumeration of all assignments, filtered by the independent
validator, gives the same optimum as CP-SAT. (2) A flow MIP on the same arcs,
solved by SCIP, agrees on synthetic instances up to 1,000 crew. (3) Every solution is
re-validated by code that doesn't import the model. Plus boundary tests at
exactly 11 h, 23 h, ±60 min, and so on. A limitation: (2) shares the arc set
with CP-SAT, so it checks the encoding, not the rules themselves. (1) and (3)
check the rules.

**Q: Why not a MIP with Gurobi?**
A: MIP is valid, and I use a flow MIP as a cross-check. CP-SAT was chosen
because it is free, has a native circuit constraint, handles conditional rules
naturally and returns early feasible solutions. In practice the LP relaxation
here is strong. That is why the LP cut helps CP-SAT, and also why a MIP could
be competitive at larger scale. I have not benchmarked Gurobi.

**Q: Isn't adding an LP bound cheating?**
A: No. The LP's feasible region contains every CP-SAT solution: its flow rows
are implied by the circuit, and the other rows are copied from the model. So
its optimum is a valid upper bound. The cut is only added if it doesn't
exclude a known feasible roster, and tests show the optimum is unchanged with
and without it.

**Q: Why are only 117 of 124 units covered on `medium`, or 12 of 21 on `small`?**
A: The rules are strict, and roughly half of the crew are on off days on any
day, by construction of the random swing phases. The uncovered-duty report
gives the reasons. The `relaxed` benchmark variant, which drops swing,
transition, base and time rules, covers 124/124 and 18/21. That quantifies
what the rules cost. These are synthetic numbers, not a statement about real
operations.

**Q: What does the 23-hour rule trigger on?**
A: Any DAY↔NIGHT change between *consecutive* duties of a person, including
the prior duty before the horizon and the next commitment after it. DAY means
a start between 03:00 and 15:00 unless the data says otherwise. It is not
applied after every duty. The exact trigger is an open question (Q-TIME-1).

**Q: How did you handle the conflicting time-change examples?**
A: I implemented both readings. `persist_after_change` (default) follows the
text: after the first change, later duties in the swing keep that time.
`window_only` follows the examples: any ±1 h each day. The default is the
stricter one, because any roster it allows is also allowed by the looser
reading. The tests encode every EFG example under both.

**Q: What about CO?**
A: CO duties (e.g. Howrah Mainline CO, HWH→HWH) are covered like other
duties, with their own eligibility. The CO and CO-location *rules* are not
defined in the briefing, so they are disabled behind an interface rather than
invented.

**Q: Can crew travel without working (positioning)?**
A: Not by default, because the briefing says not to assume it. It can be
switched on with a travel table. The travel times in the repo are
placeholders. Travel is added to rest unless configured otherwise.

**Q: Will it scale?**
A: At the preliminary scale (1,000 crew, 300 duties, 14 days, 50 eligible per
duty) it proves optimality in about 10 s. A stress test with twice the duties
and 100 eligible per duty is in `validation_report.md`. Arcs grow with the
square of each person's candidate count, so very skewed eligibility could be
a problem; column generation is the fallback.

**Q: What would you need from OptiFlux to make this operational?**
A: The answers in `assumptions_and_open_questions.md` §2, an anonymised data
extract, and a review of results against planners' decisions. The
prototype must not be used for live decisions before that.
