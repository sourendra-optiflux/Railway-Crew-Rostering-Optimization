# Problem Formulation

This document states the mathematical model that the code solves, and maps
each piece to the function that implements it. The rules marked *(assumption)*
are prototype approximations. Their source status is in
`assumptions_and_open_questions.md`.

## 1. Problem in one sentence

Given Relief and Excess crew members and a set of duties over a multi-day
horizon, choose for each crew member a **chronological sequence of duties**
so that the total covered demand is maximised (then secondary objectives),
while every sequence obeys eligibility, availability, start-time,
rest, location and base-return rules.

## 2. Sets and indices

| Symbol | Meaning | Code |
|---|---|---|
| `C` | crew members | `Instance.crews` |
| `I` | duties | `Instance.duties` |
| `I_c ⊆ I` | **candidate duties** of crew member `c` (passed all node rules, §4.1) | `CandidateSet.crews[c].nodes` |
| `s, t` | depot nodes: `s` = SOURCE (initial state of `c`), `t` = SINK (final state) | `candidate_generation.SOURCE/SINK` |
| `A_c` | **candidate arcs** of `c`: ordered pairs `(u, v)` with `u ∈ {s} ∪ I_c`, `v ∈ I_c ∪ {t}` meaning "`v` directly follows `u`" (passed all pairwise rules, §4.2) | `CandidateSet.crews[c].arcs` |
| `F_c ⊆ I_c` | existing (fixed) assignments of `c` | `Node.fixed` |
| `D` | calendar dates in the horizon | — |

## 3. Parameters (per duty `i` and crew member `c`)

| Symbol | Meaning |
|---|---|
| `S_i, E_i` | start and end times (minutes from horizon start), `E_i > S_i`; may cross midnight |
| `a_i, b_i` | start and end location |
| `σ_i ∈ {DAY, NIGHT}` | shift type: the `shift_type` column if given, else DAY iff start time-of-day ∈ [03:00, 15:00) *(assumption)* |
| `δ_i` | demand (crew members required) |
| `e_i` | number of crew already assigned in the input (`|assigned_crew|`) |
| `o_i = δ_i − e_i` | open demand |
| `p_i` | priority (1 = highest; may be missing) |
| `w_i` | priority weight, `w(p_i)` from `priority_weights` (default 1→3, 2→2, 3→1, missing→1) |
| `d_i` | start date of `i` |
| `R = 11 h`, `R^T = 23 h` | ordinary and transition rest |
| `ℓ⁰_c, base_c` | initial and base location |
| `ρ_c` | rostered start time of day |
| `k_c(d)` | swing index of date `d` for `c`; `work_c(d)` = whether `d` is a working day |
| `τ(x, y), κ(x, y)` | positioning travel time and cost from `x` to `y` (only if positioning is on) |

## 4. Candidate generation (done before the solver)

Every rule that concerns **a single crew–duty pair** or **two consecutive duties
of one crew member** is checked in Python and turned into the *existence* of
nodes and arcs. This is the main design decision of the model; see
`model_architecture.md` §2.

### 4.1 Node rules: is `i ∈ I_c`?

`i ∈ I_c` iff all of the following hold (or `i ∈ F_c`, which bypasses them):

| Rule | Condition | Function |
|---|---|---|
| Eligibility | `activity_i ∈ quals_c` (if a table exists) **and** `c ∈ eligible_i` (if the duty has a list); at least one source must exist | `constraints/eligibility.py::ineligibility_reason` |
| Availability | `d_i ∉ unavailable_c` and `work_c(d_i)` | `constraints/swing_rules.py::availability_reason` |
| Allowed start time | `offset(i) = (tod(S_i) − ρ_c) mod± 24h ∈ Ω_type(c)`; Excess `Ω = {−60, 0, +60}` min, Relief any | `swing_rules.py::time_change_reason` |
| Change already made | if `current_start_c ≠ ρ_c` and `k_c(d_i)` is the current swing, then `tod(S_i) = current_start_c` | same |
| CO hook | allows everything (rules disabled) | `constraints/co_rules.py::candidate_allowed` |
| Has open demand | `o_i > 0` (or reassignable mode) | `candidate_generation.py::generate_candidates` |

### 4.2 Arc rules: is `(u, v) ∈ A_c`?

For duties `u = i`, `v = j` with `S_j > S_i`, the arc exists iff:

1. **Daily cap (cap = 1)** *(assumption)*: `d_i ≠ d_j`.
2. **Time-change persistence** *(persist_after_change policy)*: if
   `k_c(d_i) = k_c(d_j)` and `tod(S_i) ≠ ref_c` then `tod(S_j) = tod(S_i)`.
3. **Base requirement** *(approximation)*: the crew member must pass through
   `base_c` between `i` and `j` if
   `k_c(d_i) ≠ k_c(d_j)` (swing end) or `σ_i ≠ σ_j` (shift transition).
4. **Location**: there is a connection `b_i → a_j` (or `b_i → base_c → a_j`
   if rule 3 applies). Without positioning this means the locations are equal.
   With positioning, each change of location must be a link in `travel.csv`,
   with travel time `τ_ij` (the sum of the legs).
5. **Rest and travel**:

   ```
   S_j ≥ E_i + r_ij + τ_ij            (positioning_counts_as_rest = False)
   S_j ≥ E_i + max(r_ij, τ_ij)        (positioning_counts_as_rest = True)
   r_ij = R^T if transition rest is on and σ_i ≠ σ_j, otherwise R
   ```
6. **CO hook**: allows everything.

**Start arcs** `(s, j)` use the same rules with the virtual predecessor
"initial state": location `ℓ⁰_c`, time `prior_duty_end_c` (rest owed, using
`prior_shift_type_c`) or the horizon start (no rest owed), and swing = the swing
containing the horizon start date.

**End arcs** `(i, t)` use the virtual successor "next commitment" (time,
location and shift of `next_commitment_*`, if given). Otherwise the location
is unconstrained, **except** that the crew member must end at base if the
swing of `i` ends inside the horizon (or always, with
`base_return_at_horizon_end`).

Functions: `candidate_generation.py::_connect` (all arcs),
`constraints/time_rest.py::required_rest_minutes`,
`constraints/location.py::direct_connection/connection_via`,
`constraints/base_return.py::base_required_between/base_required_after_last_duty`,
`constraints/swing_rules.py::persistence_allows`.

**Pruning.** A node that is not on any `s → t` path in `(I_c, A_c)` can never be
assigned. It is removed and counted in the duty diagnostics
(`NO_FEASIBLE_SEQUENCE`). Since all arcs go forward in time the graph is a DAG,
and the forward/backward reachability sweep is exact.

## 5. Decision variables (CP-SAT)

| Variable | Domain | Meaning | Code |
|---|---|---|---|
| `x_ci` | {0,1}, for `i ∈ I_c` | crew member `c` performs duty `i` | `model.py::build_model` (`rm.x`) |
| `y_cuv` | {0,1}, for `(u,v) ∈ A_c` | `v` directly follows `u` in `c`'s sequence | `constraints/sequencing.py` (`rm.arc_lits`) |
| `z_c` | {0,1} | `c` receives no duty | `sequencing.py` (`rm.empty`) |
| `f_i` | {0,1} | duty fully staffed (all-or-nothing mode only) | `constraints/assignment.py` (`rm.full`) |

There are no variables for ineligible pairs or impossible arcs. This fixes
problem P1 of the V1 notebooks (`initial_assessment.md`).

## 6. Hard constraints

### 6.1 Sequencing: one `AddCircuit` per crew member

Number the nodes `0` (depot standing for both `s` and `t`) and `1..|I_c|`. The
arcs of the circuit are:

```
(0, 0)  literal z_c          — empty sequence
(i, i)  literal ¬x_ci        — duty i skipped
(0, j)  literal y_c s j      — j is first
(i, 0)  literal y_c i t      — i is last
(i, j)  literal y_c i j      — j follows i
AddCircuit(all of the above)                           (C1)
```

`AddCircuit` requires the arcs with a true literal to form exactly one
Hamiltonian circuit over the nodes whose self-loop is false. Hence:

* if `c` has no duty, only self-loops are true (`z_c = 1`);
* otherwise the circuit is `0 → i₁ → i₂ → … → i_k → 0`, and these `i` are
  exactly the duties with `x_ci = 1`.

Implemented in `constraints/sequencing.py::add_crew_circuit`. Redundant links
`x_ci ⇒ ¬z_c` and `z_c ∨ ⋁_i x_ci` help propagation.

**Why consecutive checks are enough.** Every arc satisfies
`S_j ≥ E_i + r_ij > S_i`, so along the circuit the start times strictly increase
and the duty nodes contain no cycle without the depot. Let `i` and `k` be any
two assigned duties with `S_i < S_k`, and let `j` be the successor of `i`.
Then `S_k ≥ S_j ≥ E_i + R`, so **no two assigned duties overlap**, and each
duty starts at least `R` after the previous one ends. Location propagates
step by step, so the crew member is always where the next duty starts. The
same argument covers the daily cap of 1: two duties on the same date would
force a consecutive pair on the same date, which has no arc. Persistence is
also consecutive: once the time differs from the reference it must stay
equal, so checking each consecutive pair checks the whole swing.

**Optional redundant flow rows** (`add_flow_linearization`, default on):

```
z_c + Σ_{(s,j)∈A_c} y_csj = 1
Σ_{(u,i)∈A_c} y_cui = x_ci = Σ_{(i,v)∈A_c} y_civ        ∀ i ∈ I_c        (C1')
```

These are implied by (C1). On a DAG they also define the path polytope exactly.
They are what the flow MIP cross-check (`mip_crosscheck.py`) uses *instead*
of the circuit.

### 6.2 Demand and coverage (`constraints/assignment.py::add_demand_constraints`)

```
n_i = Σ_{c : i ∈ I_c} x_ci                                              (crew on duty i)
e_i ≤ n_i ≤ δ_i                                                        (C2)
covered_i = n_i − e_i                                     (partial mode, default)
n_i = e_i + o_i · f_i,  covered_i = o_i · f_i              (all_or_nothing mode)
uncovered_i = δ_i − n_i                                                (reported)
```

Uniqueness of a crew member on a duty is automatic, since there is one
Boolean per pair. Over-staffing is impossible by (C2).

### 6.3 Existing assignments (`assignment.py::add_fixed_assignments`)

```
x_ci = 1   ∀ i ∈ F_c                       (fixed mode)                 (C3)
```

In reassignable mode (C3) is dropped and `n_i ≥ e_i` keeps the coverage.

### 6.4 Daily cap > 1 (`assignment.py::add_daily_cap`)

```
Σ_{i ∈ I_c : d_i = d} x_ci ≤ cap     ∀ c, d                              (C4)
```

(Cap = 1 is enforced by the arcs. The row is also added because it tightens
the LP.)

### 6.5 Redundant cliques (`assignment.py::add_redundant_cliques`)

For each `c` and each candidate start time `S_k`:
`Σ_{i ∈ I_c : S_i ≤ S_k < E_i + R_min} x_ci ≤ 1`. Any two such duties conflict:
neither can follow the other with at least the minimum rest. These rows
remove no feasible solution.

## 7. Objective

Levels in priority order (`ModelConfig.objective_levels`, `objective.py::build_levels`):

| Level | Expression | Sense |
|---|---|---|
| `coverage` | `Σ_i covered_i` | max |
| `priority` | `Σ_i w_i · covered_i` | max |
| `positioning` | `Σ_c Σ_{(u,v)∈A_c} 100·κ_cuv · y_cuv` | min |
| `time_changes` | `Σ_c Σ_{i ∈ I_c∖F_c, tod(S_i) ≠ ρ_c} x_ci` | min |
| `roster_changes` | `Σ_{(c,i) original} (1 − x_ci)` | min |

A level is skipped when it cannot change the ranking of solutions: equal
priority weights, no positioning arcs, no off-roster times, or no
reassignable originals.

**Lexicographic mode** (default, `solve.py::_run_stages`): solve level 1;
add the constraint `level₁ ≥ v₁*` (or `≤` for minimisation); solve level 2
with the previous solution as a hint; and so on. **Weighted mode**: maximise
`Σ_k ±W_k · level_k` with `W_last = 1` and `W_k = W_{k+1} · (UB_{k+1} + 1)`,
where `UB` is an upper bound of a level's value. Each level then outweighs all
later ones combined.

Safety and operating rules are hard constraints (C1–C4 and the arc
rules). They never appear in the objective.

### 7.1 LP-bound cut (`lp_bound.py`)

Before each lexicographic stage the LP relaxation of (C1'), (C2)–(C4), the
cliques and the earlier-stage constraints is solved with GLOP. Every CP-SAT
solution satisfies these rows, so the LP optimum `L` bounds the stage optimum,
and because the objective is integral, `level ≤ ⌊L + 10⁻⁶⌋` is a valid cut.
It is added only if it does not exclude a known feasible solution (the greedy
roster or the previous stage's solution). If a stage ever became INFEASIBLE
after the cut, the whole solve is repeated without cuts. This only helps
CP-SAT *prove* optimality faster (benchmarks: `validation_report.md`). Tests
check that it never changes the optimum.

## 8. Solver status interpretation (`solve.py`)

| Status | Meaning |
|---|---|
| `OPTIMAL` | every objective stage was proven optimal |
| `FEASIBLE` | a solution exists, but at least one stage stopped at the time limit; `best_bounds` gives the proven bound, and `coverage_gap_pct = (bound − found)/bound` |
| `INFEASIBLE` | the hard rules cannot all hold — with fixed existing assignments this means the input roster itself is illegal (see `candidate_issues`) |
| `UNKNOWN` | no solution within the time limit, and no legal greedy roster |
| `HEURISTIC_ONLY` | CP-SAT found nothing within the time limit; the greedy roster (accepted by the independent validator) is returned, with the LP bound as the only quality guarantee |
| `INPUT_ERROR` | input validation failed, no model built |

The independent validator (`solution_validation.py`) re-checks every returned
solution and recomputes coverage. If its number differs from the solver's
objective, it reports `COVERAGE_MISMATCH`.

## 9. Worked example (briefing ABC, `data/sample/briefing_abc`)

ABC (Relief, base Howrah, rostered 17:00, swing from 1 Nov). Duties: D01
1 Nov 17:00 HWH→YAJ (NIGHT), D02 2 Nov 17:00 YAJ→HWH, D03 3 Nov 17:00 HWH→HWH
(CO), D05 5 Nov 05:00 HWH→YAJ (DAY), D06, D07.

* Arc D03 → D05: D03 ends 4 Nov 05:00. The shift changes NIGHT → DAY, so the
  required rest is 23 h. Earliest start is 5 Nov 04:00 ≤ 05:00 ✓. A base
  return is required on a transition: D03 ends at Howrah = base ✓. Persistence:
  D03 is at 17:00 = rostered; D05 at 05:00 is the (one) change ✓. The arc
  exists.
* Add a hypothetical D04 on 4 Nov 05:00 (HWH→YAJ, DAY). It starts 0 h after
  D03 ends, so there is no arc D03 → D04. There *is* an arc D02 → D04: D02
  ends 3 Nov 05:00 at Howrah, and 24 h ≥ 23 h. But D04 ends at Yajpur at
  17:00, so D04 → D05 fails on location and rest, and the best sequence
  through D04 is D01, D02, D04, D06, D07 = 5 duties. The optimum therefore
  keeps the six briefing duties and leaves D04 uncovered
  (`test_briefing_abc_rejects_duty_on_transition_day`).
* The circuit `0 → D01 → D02 → D03 → D05 → D06 → D07 → 0` covers all 6 units.
  The model is OPTIMAL with bound 6.

## 10. Limitations of the formulation

* Rules that are not pairwise along the sequence and not expressible as the
  linear rows above (e.g. "at most N working days in a row", monthly hour
  limits) are not modelled. They would need extra counter variables per crew
  member and day.
* Base return is approximated as *location after the duty*. No deadline is
  enforced.
* Positioning is one link per location change, with no capacity or timetable.
* A duty's date (for swings and the daily cap) is its *start* date.
* The number of arcs grows with the square of a crew member's candidate
  duties. This is fine at ≤ 100 candidates per crew member (see
  benchmarks); highly skewed eligibility would need column generation
  (`model_architecture.md` §6).
