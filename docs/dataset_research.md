# Dataset Research

**Question.** Is there a legally usable public dataset that represents the
OptiFlux crew recovery problem well enough to validate or benchmark the
prototype? The problem needs individual crew members (Relief/Excess),
activity-based eligibility, swing work/off patterns, 11 h and 23 h rest,
locations and bases, and a multi-day set of uncovered duties.

**Answer.** No. Several public resources cover *parts* of the problem, but none
contains crew-level recovery data with Relief/Excess pools and swing
patterns, and none covers Indian Railways crews. The prototype therefore uses
**synthetic data** (see `dataset_design.md`). No external dataset is copied
into this repository.

Research date: 2026-10-28.

## 1. How the search was done, and its limits

The search used about 30 web-search queries (listed in §6) and direct
inspection of repositories. **The network policy of the build environment
allowed downloads only from GitHub** (`github.com`, `raw.githubusercontent.com`).
Requests to the following hosts were refused, so their files could not be
downloaded or inspected: people.brunel.ac.uk (OR-Library),
schedulingbenchmarks.org, data.gov.in, kaggle.com, dbai.tuwien.ac.at,
gerad.ca, mobiz.vives.be, zenodo.org, data.mendeley.com, arxiv.org, doi.org,
mobilitydatabase.org.

Each finding therefore carries one of three evidence levels:

| Level | Meaning |
|---|---|
| **Verified (downloaded)** | Files were downloaded from GitHub and their contents and licence file inspected. |
| **Verified (search only)** | The landing page exists and the search engine's extract describes its contents. The files themselves were *not* opened. |
| **Unverified** | Mentioned in papers or search results; existence or availability not confirmed. |

The repository existence and licence files of the three GitHub datasets in
§2.1, §2.2 and §2.5 were re-checked independently (`git ls-remote` and the
raw `LICENSE` / `README.md` files) before this document was written.

## 2. Verified datasets (downloaded and inspected)

### 2.1 ROMSOC "Benchmarks for MIP rail scheduling" (DB Cargo Polska)

| Item | Finding |
|---|---|
| Source | ROMSOC (EU H2020 project) — https://github.com/ROMSOC/benchmarks-mip-rail-scheduling (README cites Zenodo DOI 10.5281/zenodo.5171817) |
| Contents | 10 instances (1 week to 1 month). `trains.csv` (e.g. 2,551 trains in the 1-month instance: stations, times, route, locomotive type), `drivers.csv` (217 drivers, per-route and per-locomotive qualification columns, `12h_break_required` flag, initial location), region mappings, distance matrix. |
| Licence | MIT (`LICENSE` file). The README adds a civil-use-only disclaimer that must be kept on redistribution. Based on real Feb-2020 freight data. |
| Downloadable | Yes (verified). |
| OptiFlux aspects represented | **Eligibility by qualification** (closest public match), driver initial location, multi-day horizon, a location network. |
| Missing | Relief/Excess pools, swing patterns, 11 h / 23 h rules, day/night transitions, base return, any recovery/uncovered-duty scenario. It is an integrated locomotive and driver *planning* problem for freight. |
| Transformations needed | Trains → duties; route qualifications → activity eligibility; regions → bases; remove assigned drivers to create uncovered duties; add swing and rest rules synthetically. |
| Verdict | **Partial benchmark / inspiration.** Useful for a later realism test of the eligibility layer. Not used now, because the remaining OptiFlux rules would all have to be invented on top of it. |

### 2.2 RCSP benchmark — railway crew scheduling (van Rossum)

| Item | Finding |
|---|---|
| Source | https://github.com/BartvanRossum/rcsp-benchmark (README links an arXiv paper, arXiv:2606.10081, which could not be opened here) |
| Contents | 100 synthetic single-day instances (90–3,016 tasks): tasks with times and stations, feasible connection arcs, crew bases, best-known solutions, a Java feasibility checker. |
| Licence | MIT (`LICENSE` file; README: "The instances are released under the MIT License"). |
| Downloadable | Yes (verified). |
| Represents | Timetable-derived railway tasks, stations, crew bases, **duties that must start and end at the base**, arc-based connection structure (similar to our candidate arcs). |
| Missing | Individual crew members, eligibility, multi-day horizon, rest between duties, swing patterns, Relief/Excess. It is a duty-*generation* problem, which comes before rostering. |
| Verdict | **Inspiration only.** Its connection-arc files and independent checker match the design used here (arc set plus separate validator). |

### 2.3 INRC-II nurse rostering instances (via a GitHub mirror)

| Item | Finding |
|---|---|
| Source | Second International Nurse Rostering Competition (Ceschia et al., 2015). Official site unreachable; files inspected in the MIT-licensed mirror https://github.com/wssuite/NurseScheduler (`datasets/INRC2/`). |
| Contents | 23 scenario families (5–120 nurses, 4–8 weeks): skills, shift types, forbidden shift successions, min/max consecutive working days and days off, weekly demand, history files. |
| Licence | Mirror code is MIT. **Licence of the instances themselves is unverified.** |
| Represents | Skill-based eligibility, forbidden successions (structurally equivalent to "11 h ordinary / 23 h after a day–night change"), consecutive work/off limits (analogous to swings), rolling history. |
| Missing | Locations, travel, base return, timed 12 h shifts, Relief/Excess. Not railway data. |
| Verdict | **Possible benchmark for the rest/pattern rule engine (structural analogue).** Not used. |

### 2.4 Curtois & Qu shift scheduling benchmark (NRP Instance1–24)

| Item | Finding |
|---|---|
| Source | https://schedulingbenchmarks.org/nrp/ (blocked here; existence confirmed by search). Files inspected in the same wssuite mirror (`datasets/nrp/`). |
| Contents | Horizon (Instance1 = 14 days), shifts with lengths and forbidden successors, staff limits on consecutive shifts and days off, fixed days off, cover requirements. |
| Licence | **None found.** Treat as "research use, cite the source" until clarified. |
| Represents | 14-day horizon, rest-type succession rules, work/off limits, pre-assigned days off. |
| Missing | Locations, activity eligibility, Relief/Excess, base return. |
| Verdict | **Possible validation of a rule checker.** Not used, because the licence is unclear. |

### 2.5 DataMeet Indian Railways data

| Item | Finding |
|---|---|
| Source | https://github.com/datameet/railways (2016 snapshot) |
| Contents | `stations.json` (≈9,000 stations), `trains.json` (≈5,200 trains), `schedules.json` (≈417,000 stop rows). |
| Licence | README states **CC0**. The data were collected from Indian Railways sources, and Indian Railways has asserted copyright over timetables, so the CC0 declaration is the uploader's. Use with care. |
| Downloadable | Yes (verified). |
| Represents | Real station geography and train timings. Howrah (HWH) and Nellore (NLR) are present. The research agent noted that Jajpur Keonjhar Road (JJKR) lies on the Howrah–Chennai line between them. |
| Missing | **Any crew data** (crews, duties, rosters, eligibility, rest). Outdated timetables. |
| Verdict | **Inspiration only.** A public timetable is not a crew dataset. **Not used**, partly because the mapping "Yajpur = Jajpur" is *our guess, not confirmed by OptiFlux* (see open question Q-LOC-3). |

## 3. Confirmed by search only (files not inspected)

| Dataset | URL / reference | Content (from search extracts) | Licence | Fit for OptiFlux | Verdict |
|---|---|---|---|---|---|
| OR-Library crew scheduling `csp50`–`csp500` (Beasley & Cao 1996, EJOR 94) | people.brunel.ac.uk/~mastjjb/jeb/orlib/cspinfo.html | Randomly generated fixed-time tasks, transition arcs with costs, working-time limit | Not found (OR-Library is traditionally free for research) | Generic task chaining only: no locations, eligibility, rest or patterns | Generic kernel benchmark only |
| OR-Library set covering `rail507` … `rail4872` (Italian railways; Ceria/Nobili/Sassano; Caprara/Fischetti/Toth) | people.brunel.ac.uk/~mastjjb/jeb/orlib/scpinfo.html; MIPLIB `rail507` | Set covering matrices (rows = trips, columns = duties, costs 1 or 2), no times or stations | Not found | The pairing layer only; anonymised | Not useful for the assignment/recovery layer |
| Rotating workforce scheduling (Musliu et al., TU Wien) | dbai.tuwien.ac.at/proj/Rota/ | Cyclic work/off block patterns, forbidden sequences | Unverified | Closest analogue to 14/14 and 6/6 swings | Pattern-logic validation, if the host is allowed |
| Airline crew data, Kasirzadeh, Saddoune & Soumis (2017), EURO J. Transp. Logist. 6(2), DOI 10.1007/s13676-015-0080-x | gerad.ca/en/papers/G-2014-22 (lists `G1422-DataSets.zip`) | 7 instances from a North American carrier: flights, bases | Unverified | Multi-day, bases, rest; airline only | Inspiration |
| data.gov.in "Indian Railways Train Time Table" | data.gov.in catalog | Train-wise station arrival/departure | GODL-India is used on the portal; not verified for this catalog | Timetable only, no crew | Inspiration only |
| Kaggle IRCTC-scraped schedules | kaggle.com | Scraped schedules and availability | None found | Timetable only | Avoid (licence unclear) |
| Beijing–Shanghai HSR crew-segment data (Mendeley, DOI 10.17632/k2xhxrj9v7.1) | data.mendeley.com | Crew operation segments with times | Not visible | Duty segments, no rostering | Inspiration, after a licence check |
| Unofficial Indian Railways GTFS (Mobility Database `mdb-2867`) | mobilitydatabase.org | Trips and stop times | Unverified | Timetable only | Not used |

## 4. Papers whose data is not public

| Reference | Data status |
|---|---|
| Yu, Häll, Peterson, Schmidt (2025), *Late Train-Crew Rescheduling* (in `Papers/`) | Mälartåg operator data; no public release found. A related paper reportedly used ROMSOC data (§2.1). |
| Huisman (2007); Potthoff, Huisman & Desaulniers (2010); Veelenturf et al. (2012, 2016); Verhaegh et al. (2017) — NS crew (re)scheduling | The Erasmus ECOPT page (search-verified) says the NS datasets are "available upon request for scientific research". **Not public.** |
| Chinese high-speed rail crew scheduling and replanning papers | No public instances found, apart from the Mendeley set above. |

## 5. Decision

1. **No public dataset is adopted as the primary data.** None represents
   Relief/Excess crew, swing patterns, OptiFlux's activity set or the
   recovery setting. Forcing a timetable or a nurse-rostering instance into
   the OptiFlux shape would mean inventing most of the rules on top of it,
   which would *redefine* the problem rather than support it.
2. **A deterministic synthetic generator is used** (`src/railway_rostering/synthetic.py`),
   together with hand-written, hand-checkable instances (`data/sample/`). Every
   synthetic file is marked `"synthetic": true` with a disclaimer, and the
   travel times are labelled as placeholders.
3. **Research-derived ideas taken from these sources** (no data copied):
   * pre-computed connection arcs plus an independent feasibility checker
     (RCSP benchmark, Yu et al.);
   * qualification matrices per crew member (ROMSOC) → `eligibility.csv`;
   * rest rules expressed as rules about which shift may follow which
     (INRC-II / Curtois) → arc filtering in candidate generation.
4. **Possible future steps**, once the network hosts are allowed and licences
   checked: (a) map ROMSOC qualifications onto the eligibility layer for a
   realism benchmark; (b) use INRC-II or Curtois succession rules to
   cross-test the rest engine; (c) derive duty start-time distributions for
   the corridor from a timetable source, but **only after OptiFlux confirms
   which real stations "Yajpur" and the activities refer to.**
5. Real OptiFlux crew data, when available, must stay out of Git
   (`.gitignore` already excludes `data/private/` and `data/real/`).

## 6. Search queries run

1. OR-Library Beasley crew scheduling csp50 csp150 instances
2. OR-Library set covering rail507 rail516 rail582 rail2536 rail4284 Italian railways scpinfo
3. schedulingbenchmarks.org shift scheduling benchmark instances Curtois Qu license
4. Second International Nurse Rostering Competition INRC-II instances download
5. rotating workforce scheduling benchmark instances Musliu TU Wien DBAI download
6. Kasirzadeh Saddoune Soumis airline crew scheduling models algorithms and data sets GERAD instances
7. data.gov.in Indian Railways trains time table dataset Government Open Data License India
8. Kaggle Indian railways train timetable dataset license
9. datameet railways github trains stations schedules json license
10. github csp50.txt csp100 OR-Library crew scheduling Beasley Cao data files
11. github rail507.txt rail516 rail582 set covering instances repository
12. github schedulingbenchmarks Instance1.txt shift scheduling benchmark Curtois instances 1-24
13. github rotating workforce scheduling instances Example1.txt Musliu benchmark 50 instances
14. "orlib" github mirror Beasley OR-Library data files scp41 rail507 csp
15. OR-Library Beasley "OR-Library" terms of use copyright data files freely available
16. Kasirzadeh airline crew scheduling data sets publicly available download pairings instances 1 7 GERAD
17. "Kasirzadeh" crew scheduling dataset "flight legs" US carrier instances benchmark download link
18. railway crew rescheduling benchmark instances publicly available data Huisman Potthoff Veelenturf NS
19. Late train-crew rescheduling Mälartåg 2025 data availability
20. high-speed railway crew scheduling instances dataset github China crew rostering open data
21. ROMSOC project railway crew scheduling open source data set github
22. Erasmus Center for Optimization in Public Transport data sets source codes crew
23. Mendeley Data k2xhxrj9v7 high-speed railway crew duty scheduling license CC BY
24. dbai.tuwien.ac.at staff musliu benchmarks rotating workforce scheduling instances format
25. data.gov.in "Trains available for reservation" Indian Railways dataset fields
26. "Government Open Data License - India" GODL terms attribution permitted use data.gov.in
27. arXiv 2501.08098 late train-crew rescheduling tabu search restricted DFS Mälartåg dataset code
28. INRC-II competition instances license terms mobiz.vives.be inrc2 datasets
29. kaggle "indian railways dataset" stations trains schedules datameet CC0
30. Indian Railways GTFS feed Mobility Database rail India open GTFS
