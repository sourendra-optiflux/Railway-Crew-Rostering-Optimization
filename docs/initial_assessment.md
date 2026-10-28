# Initial Assessment of the Repository

*Written at the start of the implementation work, before any new code was
added. It records what existed, what was wrong or missing, and the plan that
the rest of the work followed.*

## 1. What the repository contained

| Path | Type | Content |
|---|---|---|
| `README.md` | Markdown | Describes "Version 1", a simplified Colab proof of concept: input CSV format, model scope, limitations, next steps. |
| `Optiflux_crew_rostering_problem.md` | Markdown | The OptiFlux problem specification: routes (Howrah–Yajpur, Howrah–Nellore), activities, Relief/Excess crew, swing patterns, 11 h / 23 h rest, CO, base return, examples, open questions and a roadmap. **This is the primary source of operational requirements.** |
| `railway_crew_v1.ipynb` | Colab notebook | Hard-coded 3-crew / 5-duty toy instance, CP-SAT model, printed solution, in-notebook validation. Output: `OPTIMAL`, 4 of 5 duties covered. |
| `rostering_v1_sheets.ipynb` | Colab notebook | Same model, but reads `crew.csv` / `duties.csv` from Google Drive and exports result CSVs. Output: `OPTIMAL`, 5 of 5 covered (crew A starts at Howrah in this data). |
| `Papers/tabu_search_approach.pdf` | Paper | Yu, Häll, Peterson, Schmidt (2025), *Late Train-Crew Rescheduling — a Model and a Heuristic Approach*, Transportation Research Procedia 86, 337–344. MILP + Tabu Search for one-day driver rescheduling with standby drivers. |
| `Progress/CP_SAT_vs_MIP_Solvers.pdf` | Internal note | "Why CP-SAT for OptiFlux Crew Recovery" — argues for CP-SAT (conflict learning, native `only_enforce_if`, global constraints), estimates model size (~200k Booleans at 300 duties × 50 eligible), recommends a greedy hint, MIP cross-check on small instances, and tiny hand-checkable tests. |

There was no Python package, no tests, no dependency file, no `.gitignore`, no
sample data in the repository (the Drive notebook reads files that are not in
Git), and no CI.

## 2. The V1 formulation, reviewed

Both notebooks build the same CP-SAT model:

* `x[p, i]` — Boolean, person `p` covers duty `i`; forced to 0 when `p` is not
  in the duty's `eligible` list.
* `Σ_p x[p, i] ≤ 1` — at most one person per duty.
* `Σ_{i on day d} x[p, i] ≤ 1` — at most one duty *starting* per calendar day.
* One `AddCircuit` per person over nodes `{0} ∪ {1..N}`:
  * `0 → 0` self-loop literal `empty_route` (person does nothing);
  * `i → i` self-loop literal `¬x[p, i]` (duty skipped);
  * `0 → i` only if the duty starts at the person's initial location;
  * `i → 0` always allowed;
  * `i → j` only if `start_j ≥ end_i + 11 h` **and** `end_location_i = start_location_j`.
* Objective: maximise `Σ x`.

### 2.1 Is the circuit formulation correct?

Yes, for the rules it encodes. The reasoning (which the new implementation
keeps and documents in `docs/problem_formulation.md`):

1. `AddCircuit` requires every node whose self-loop is false to lie on a single
   Hamiltonian circuit through the selected arcs. Node `i`'s self-loop is
   `¬x[p, i]`, so exactly the assigned duties (plus the depot 0) form one cycle.
2. Every duty→duty arc goes strictly forward in time (`start_j ≥ end_i + 11 h >
   start_i`), so the cycle is `0 → i₁ → i₂ → … → i_k → 0` with increasing start
   times: it is the person's duty sequence in chronological order.
3. Rest and location are checked only between *consecutive* duties. That is
   enough: if every consecutive pair has `start_{next} ≥ end_{prev} + 11 h`, no
   two assigned duties can overlap, and location is propagated duty by duty.

This argument was verified empirically in the new code (CP-SAT vs. a brute-force
enumerator and vs. an independent flow MIP; see `docs/validation_report.md`).

### 2.2 Problems found

| # | Problem | Impact |
|---|---|---|
| P1 | **Dense variables.** `x[p, i]` and all arc literals are created for *every* person–duty pair, including ineligible ones (then fixed to 0). Arc count is `O(P · N²)`. At the scoping estimate (1,000 crew, 300 duties) that is up to ~90 million arc literals. | Will not build at OptiFlux scale. Candidates must be generated only for eligible, time-compatible pairs (≈15,000 at 50 eligible/duty). |
| P2 | Fixed 12 h duration derived from `start`; no `end` column. | Cannot represent shorter CLO/CO/shed duties if they exist (open question). |
| P3 | No 23 h transition rest, no shift type. | Required by the briefing; missing. |
| P4 | No Relief/Excess distinction, swing calendar, rostered time, lift-up/layback, time-change persistence. | Core OptiFlux rules missing. |
| P5 | No base-return rule, no CO handling. | Specified rule families missing. |
| P6 | No horizon-boundary handling: rest after a duty that ended just before the horizon, or before a commitment just after it, is ignored. | Can produce rosters that violate rest at the boundaries. |
| P7 | Demand fixed at 1; NP Crew is described with "demand 2". | Multi-crew duties not representable. |
| P8 | Daily cap counts duties by *start date*. With 12 h duties and 11 h rest the cap only bites in a corner case (00:00 start and 23:00 start on the same date), so it is mostly redundant; the briefing's 2 Nov example lists *two* activities on one day (Yajpur Mainline then Yajpur CLO), which the cap would forbid. | The cap is an unverified assumption; kept as a configurable rule. |
| P9 | `rostering_v1_sheets.ipynb` strips column names *after* asserting they exist, so a header such as `" id"` fails the assertion instead of being cleaned. The file listing in its saved output shows `crew.gsheet` / `duties.csv.gsheet` while the code reads `crew.csv` / `duties.csv`, so the saved outputs cannot be reproduced from what the listing shows. | Minor robustness/reproducibility issues. |
| P10 | Model code duplicated across two notebooks; Colab/Drive-only paths. | Hard to test and maintain. |
| P11 | The in-notebook validator re-reads the solver's `x` values but re-checks the same rules with closely related code, and there are no negative tests. | Correctness not demonstrated beyond the single example. |
| P12 | Status handling prints `objective_value` but not the best bound, so FEASIBLE vs OPTIMAL quality is not reported. | Needed for honest reporting at scale. |
| P13 | No explanation of *why* a duty is uncovered. | Listed in the spec as an open need ("How should the system explain an uncovered duty?"). |

Reusable ideas kept: the circuit-per-crew sequencing model, depot node 0,
self-loop = skip encoding, consecutive-pair arc filtering, and the notebook's
validator idea (generalised into an independent module).

## 3. Research already in the repository

* **Yu et al. (2025)** — useful ideas: a *shadow driver* for unassigned tasks
  (we use explicit uncovered-demand accounting instead), pairwise compatibility
  parameters `q_{g,g'}` / `p_{g,g'}` (equivalent to our precomputed arc set),
  first/last task depot restrictions (our start/end arcs), and the observation
  that a compact MILP with big-M runs out of memory quickly (12–35 GB for 18–22
  tasks), motivating pre-filtered arcs and CP-SAT. Their data (Mälartåg) is not
  public.
* **CP-SAT vs MIP note** — adopted recommendations: CP-SAT as the primary
  solver, `only_enforce_if`-style conditional rules (here mostly pre-computed
  into arc filters), greedy roster as a hint and baseline, tiny hand-checkable
  instances (including its 3-duty example, now a test), recording status /
  bound / gap / runtime, and a MIP cross-check on small instances.

## 4. Implementation plan (as executed)

1. Package `src/railway_rostering/` with domain objects, CSV loaders (new schema
   + V1 legacy schema), and input validation.
2. Rule predicates in `constraints/` (eligibility, time/rest, location,
   swing/time-change, base return, CO interface).
3. **Candidate generation**: only feasible crew–duty pairs and feasible
   consecutive arcs, plus reachability pruning and per-duty diagnostics.
4. CP-SAT model: `x[c,i]`, one `AddCircuit` per crew over its own candidates,
   demand/coverage, fixed existing assignments, daily cap, redundant cliques.
5. Lexicographic objective: coverage → priority → positioning cost → time
   changes → roster changes (configurable).
6. Greedy baseline used as a solver hint.
7. Independent solution validator (does not import the constraint modules).
8. Brute-force and flow-MIP cross-checks.
9. Synthetic generator with seeds and presets; hand-written sample instances
   including the V1 toy data and the briefing's ABC example.
10. CLI, output files, notebooks that call the package, tests, CI, benchmarks,
    documentation.

Existing files (`Optiflux_crew_rostering_problem.md`, both notebooks, both PDFs)
are preserved unchanged. The V1 notebooks remain at the repository root because
their "Open in Colab" badges link to those paths.
