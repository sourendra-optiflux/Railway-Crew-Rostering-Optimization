"""Reverse-lane pairing of Change Over (CO) activities.

A lane is a mainline direction: "Haskett Mainline" runs Haskett -> Yarmouth, "Yarmouth Mainline" runs
Yarmouth -> Haskett. Each lane has a CO activity ("Crew On", at the lane's start depot). Two lanes are
reverses of each other when their depots are swapped. Every CO should ideally happen together with the CO on
the reverse lane at the same start time.

`reverse_co_pairs` derives the pairs from `activities_df.csv`; nothing is hard-coded to these names.
CP-SAT treats a mismatch as a soft violation (see CP-SAT/solver.py).
"""

from __future__ import annotations

from collections import defaultdict

CO_TYPE = "Crew On"


def reverse_co_pairs(activities: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """Return (Activity ID, Activity ID) pairs of CO activities on reverse lanes, each pair once, sorted."""
    lane_of_head: dict[str, tuple[str, str]] = {}
    co_of_head: dict[str, list[str]] = defaultdict(list)
    for aid, a in sorted(activities.items()):
        head = a["Activity Head"]
        if a["Activity Type"] == CO_TYPE:
            co_of_head[head].append(aid)
        elif a["Start Depot"] and a["End Depot"] and a["Start Depot"] != a["End Depot"]:
            lane_of_head.setdefault(head, (a["Start Depot"], a["End Depot"]))
    heads_of_lane: dict[tuple[str, str], list[str]] = defaultdict(list)
    for head, lane in lane_of_head.items():
        heads_of_lane[lane].append(head)  # several heads can share one depot lane

    pairs: set[tuple[str, str]] = set()
    for head, cos in co_of_head.items():
        lane = lane_of_head.get(head)
        if lane is None:
            continue
        for reverse in heads_of_lane.get((lane[1], lane[0]), []):
            if reverse == head:
                continue
            for a in cos:
                for b in co_of_head.get(reverse, []):
                    pairs.add(tuple(sorted((a, b))))
    return sorted(pairs)
