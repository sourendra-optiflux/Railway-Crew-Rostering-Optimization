"""Operational rule modules.

Two kinds of code live here:

* **Rule predicates** (pure Python, no solver): ``eligibility``, ``time_rest``,
  ``location``, ``swing_rules``, ``base_return``, ``co_rules``. Candidate
  generation calls them to decide which crew-duty pairs and which consecutive
  arcs exist.
* **CP-SAT constraint adders**: ``sequencing`` (one ``AddCircuit`` per crew
  member) and ``assignment`` (demand, coverage, existing roster, daily cap,
  redundant cliques).

The independent validator (``solution_validation.py``) deliberately does not
import anything from this package.
"""
