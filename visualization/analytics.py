"""Advanced analytics for crew workload/fairness, reassignment chains, depot balance, and individual schedules."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from visualization.data_loader import DashboardDataset
from visualization.metrics import WORK_ASSIGNMENT_TYPES, classify_user


def _parse_dt(date_str: str, time_str: str) -> datetime | None:
    d = (date_str or "").strip()
    t = (time_str or "").strip()
    if not d or not t:
        return None
    try:
        return datetime.fromisoformat(f"{d}T{t}")
    except ValueError:
        return None


def _shift_interval(row: dict[str, str]) -> tuple[datetime, datetime] | None:
    s_dt = _parse_dt(row.get("Start Date", ""), row.get("Shift Start Time", ""))
    if s_dt is None:
        return None
    e_date = row.get("End Date", "").strip() or row.get("Start Date", "").strip()
    e_dt = _parse_dt(e_date, row.get("Shift End Time", ""))
    if e_dt is None:
        e_dt = s_dt + timedelta(hours=12)
    elif e_dt <= s_dt:
        e_dt += timedelta(days=1)
    return s_dt, e_dt


def _is_day_shift(start_dt: datetime, day_from_min: int = 180, day_to_min: int = 900) -> bool:
    minute = start_dt.hour * 60 + start_dt.minute
    return day_from_min <= minute < day_to_min


def _day_window_minutes(dataset: DashboardDataset) -> tuple[int, int]:
    raw = dataset.constraints.get("Day Shift Window", ("03:00-15:00", "Active"))[0]
    try:
        p1, p2 = raw.split("-")
        return int(p1[:2]) * 60 + int(p1[3:5]), int(p2[:2]) * 60 + int(p2[3:5])
    except Exception:
        return 180, 900


def _swing_work_caps(dataset: DashboardDataset) -> tuple[int, int]:
    """Read Residential and FIFO swing work-day caps from constraints_df.csv (default: 6, 14)."""
    def _parse_work_days(key: str, default: int) -> int:
        raw = dataset.constraints.get(key, ("", "Active"))[0].strip()
        if "/" in raw:
            try:
                return max(1, int(raw.split("/")[0]))
            except ValueError:
                pass
        return default

    return (
        _parse_work_days("Residential Work/Off Days", 6),
        _parse_work_days("FIFO Work/Off Days", 14),
    )


def compute_crew_workload_analytics(dataset: DashboardDataset) -> dict[str, object]:
    """Compute per-crew fairness, day/night split, weekend duties, standby conversion, and fatigue indicators."""
    day_from, day_to = _day_window_minutes(dataset)
    res_cap, fifo_cap = _swing_work_caps(dataset)

    # Track standby rows originally belonging to Relief vs final state
    relief_standby_total: dict[str, int] = defaultdict(int)
    relief_converted: dict[str, int] = defaultdict(int)
    reassigned_from_rows = {
        r.get("From Row", "").strip()
        for r in dataset.reassignments
        if r.get("From Row", "").strip()
    }

    per_user_shifts: dict[str, list[dict[str, object]]] = defaultdict(list)
    user_meta: dict[str, dict[str, str]] = {}

    for uid, info in dataset.crew_by_id.items():
        user_meta[uid] = {
            "Classification": info.get("Classification", "").strip() or "Unknown",
            "Home Depot": info.get("Home Depot", "").strip() or "Unknown",
            "Role": info.get("Role", "").strip() or "",
        }

    for r in dataset.roster_rows:
        if r.get("In Horizon", "Yes").strip() not in ("", "Yes", "True", "true"):
            continue
        aid = r.get("Assignment ID", "").strip()
        orig_uid = r.get("User Id", "").strip()
        opt_uid = r.get("Optimised User Id", "").strip()
        atype = r.get("Assignment Type", "").strip()

        if atype == "Relief" and orig_uid:
            relief_standby_total[orig_uid] += 1
            if aid in reassigned_from_rows or (opt_uid and opt_uid != orig_uid):
                relief_converted[orig_uid] += 1

        if atype not in WORK_ASSIGNMENT_TYPES:
            continue
        if not opt_uid:
            continue

        interval = _shift_interval(r)
        if interval is None:
            continue
        s_dt, e_dt = interval
        hours = (e_dt - s_dt).total_seconds() / 3600.0
        is_day = _is_day_shift(s_dt, day_from, day_to)
        is_weekend = s_dt.weekday() >= 5

        if opt_uid not in user_meta:
            user_meta[opt_uid] = {
                "Classification": classify_user(dataset, r, opt_uid),
                "Home Depot": r.get("Start Location", "").strip() or "Unknown",
                "Role": "",
            }

        per_user_shifts[opt_uid].append(
            {
                "start": s_dt,
                "end": e_dt,
                "hours": hours,
                "is_day": is_day,
                "is_weekend": is_weekend,
                "swing": r.get("Swing", "").strip(),
                "assignment_type": atype,
                "activity_head": r.get("Activity Head", "").strip(),
            }
        )

    # Also account for Relief standby rows converted in reassignments where roster row might reflect Demand
    crew_rows: list[dict[str, object]] = []
    total_worked_shifts = 0
    total_day_shifts = 0
    total_night_shifts = 0
    total_weekend_shifts = 0
    fatigue_alerts = 0

    all_uids = sorted(set(user_meta.keys()) | set(per_user_shifts.keys()))
    for uid in all_uids:
        shifts = sorted(per_user_shifts.get(uid, []), key=lambda x: x["start"])
        n_shifts = len(shifts)
        n_hours = round(sum(float(x["hours"]) for x in shifts), 1)
        n_day = sum(1 for x in shifts if x["is_day"])
        n_night = n_shifts - n_day
        n_weekend = sum(1 for x in shifts if x["is_weekend"])

        # Compute max consecutive shifts within a swing (<= 48h rest break)
        max_consec = 0
        cur_consec = 0
        prev_end: datetime | None = None
        for sh in shifts:
            s_dt = sh["start"]
            e_dt = sh["end"]
            if prev_end is None or (s_dt - prev_end) > timedelta(hours=48):
                cur_consec = 1
            else:
                cur_consec += 1
            if cur_consec > max_consec:
                max_consec = cur_consec
            prev_end = e_dt

        meta = user_meta.get(uid, {"Classification": "Unknown", "Home Depot": "Unknown", "Role": ""})
        classification = meta["Classification"]
        swing_cap = res_cap if classification in ("Residential", "Resident") else fifo_cap
        near_fatigue = max_consec >= swing_cap and n_shifts > 0
        if near_fatigue:
            fatigue_alerts += 1

        sb_total = relief_standby_total.get(uid, 0)
        sb_conv = min(sb_total, relief_converted.get(uid, 0))

        total_worked_shifts += n_shifts
        total_day_shifts += n_day
        total_night_shifts += n_night
        total_weekend_shifts += n_weekend

        crew_rows.append(
            {
                "User Id": uid,
                "Classification": classification,
                "Home Depot": meta["Home Depot"],
                "Worked Shifts": n_shifts,
                "Worked Hours": n_hours,
                "Day Shifts": n_day,
                "Night Shifts": n_night,
                "Weekend Shifts": n_weekend,
                "Max Consecutive Shifts": max_consec,
                "Swing Cap": swing_cap,
                "At Swing Cap": near_fatigue,
                "Relief Standby Rows": sb_total,
                "Relief Converted to Fill": sb_conv,
            }
        )

    shift_counts = [int(r["Worked Shifts"]) for r in crew_rows] or [0]
    avg_shifts = round(sum(shift_counts) / len(shift_counts), 2)
    total_sb = sum(relief_standby_total.values())
    total_sb_conv = sum(min(relief_standby_total[u], relief_converted[u]) for u in relief_standby_total)

    return {
        "crew_rows": sorted(crew_rows, key=lambda r: (-int(r["Worked Shifts"]), str(r["User Id"]))),
        "summary": {
            "total_crew": len(crew_rows),
            "total_worked_shifts": total_worked_shifts,
            "total_day_shifts": total_day_shifts,
            "total_night_shifts": total_night_shifts,
            "total_weekend_shifts": total_weekend_shifts,
            "avg_shifts_per_crew": avg_shifts,
            "min_shifts_per_crew": min(shift_counts),
            "max_shifts_per_crew": max(shift_counts),
            "fatigue_alerts": fatigue_alerts,
            "relief_standby_total": total_sb,
            "relief_standby_converted": total_sb_conv,
            "relief_standby_kept": max(0, total_sb - total_sb_conv),
        },
    }


def build_reassignment_chains(dataset: DashboardDataset) -> dict[str, object]:
    """Trace reassignment moves and multi-hop Demand->Demand chains from reassignments.csv."""
    reassignments = dataset.reassignments
    if not reassignments:
        return {
            "moves": [],
            "chains": [],
            "sankey_links": [],
            "summary": {
                "total_moves": 0,
                "direct_gap_fills": 0,
                "chain_moves": 0,
                "max_chain_level": 0,
                "total_cost": 0,
                "by_source": {},
            },
        }

    by_filled_row = {r.get("Filled Row", "").strip(): r for r in reassignments if r.get("Filled Row", "").strip()}
    by_source = Counter(r.get("Source", "").strip() or "Unknown" for r in reassignments)
    max_level = max((int(r.get("Chain Level", "0") or 0) for r in reassignments), default=0)
    total_cost = sum(int(float(r.get("Cost", "0") or 0)) for r in reassignments)

    # Link Sankey flows: Source Type -> Target Activity Name
    flow_counts: Counter[tuple[str, str]] = Counter()
    moves: list[dict[str, object]] = []
    for r in reassignments:
        src = r.get("Source", "").strip() or "Unknown"
        from_act = r.get("From Activity", "").strip() or src
        to_act = r.get("Activity Name", "").strip() or r.get("Activity ID", "").strip()
        flow_counts[(f"{src}: {from_act}", f"Target: {to_act}")] += 1

        moves.append(
            {
                "Date": r.get("Date", ""),
                "Start": r.get("Start", ""),
                "Target Activity": to_act,
                "Filled Row": r.get("Filled Row", ""),
                "Was Gap": r.get("Was Gap", ""),
                "Original User Id": r.get("Original User Id", ""),
                "Optimised User Id": r.get("Optimised User Id", ""),
                "Source Type": src,
                "From Activity": from_act,
                "From Row": r.get("From Row", ""),
                "Offset (min)": int(float(r.get("Offset Minutes", "0") or 0)),
                "Chain Level": int(float(r.get("Chain Level", "0") or 0)),
                "Cost": int(float(r.get("Cost", "0") or 0)),
            }
        )

    # Reconstruct multi-step chains where Filled Row == From Row of another move
    chains: list[dict[str, object]] = []
    for r in reassignments:
        if r.get("Was Gap", "").strip() != "True":
            continue
        steps = [r]
        cur = r
        seen = {r.get("Filled Row", "")}
        # Walk backwards if someone filled the mover's vacated row
        while True:
            from_row = cur.get("From Row", "").strip()
            if not from_row or from_row in seen:
                break
            prev = by_filled_row.get(from_row)
            if prev is None:
                break
            steps.append(prev)
            seen.add(from_row)
            cur = prev

        steps_ordered = list(reversed(steps))
        desc_parts = [
            f"{s.get('Optimised User Id')} ({s.get('Source')}:{s.get('From Activity')}) -> "
            f"{s.get('Activity Name')}@{s.get('Start')}"
            for s in steps_ordered
        ]
        chains.append(
            {
                "Root Gap Row": r.get("Filled Row", ""),
                "Date": r.get("Date", ""),
                "Target Activity": r.get("Activity Name", ""),
                "Target Start": r.get("Start", ""),
                "Hops": len(steps_ordered),
                "Total Chain Cost": sum(int(float(s.get("Cost", "0") or 0)) for s in steps_ordered),
                "Chain Trace": "  ==>  ".join(desc_parts),
            }
        )

    sankey_links = [
        {"source": src_lbl, "target": tgt_lbl, "value": cnt}
        for (src_lbl, tgt_lbl), cnt in sorted(flow_counts.items())
    ]

    return {
        "moves": moves,
        "chains": sorted(chains, key=lambda c: (-int(c["Hops"]), str(c["Date"]), str(c["Target Start"]))),
        "sankey_links": sankey_links,
        "summary": {
            "total_moves": len(reassignments),
            "direct_gap_fills": sum(1 for r in reassignments if r.get("Was Gap") == "True"),
            "chain_moves": sum(1 for r in reassignments if int(float(r.get("Chain Level", "0") or 0)) > 0),
            "max_chain_level": max_level,
            "total_cost": total_cost,
            "by_source": dict(by_source),
        },
    }


def compute_depot_and_travel_analytics(dataset: DashboardDataset) -> dict[str, object]:
    """Compute depot inflow/outflow balance and FIFO deadheading/travel hours."""
    depot_starts: Counter[str] = Counter()
    depot_ends: Counter[str] = Counter()
    daily_depot: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"Starts": 0, "Ends": 0})

    travel_in_count = 0
    travel_out_count = 0
    total_travel_hours = 0.0
    travel_by_user: dict[str, dict[str, object]] = {}

    for r in dataset.roster_rows:
        if r.get("In Horizon", "Yes").strip() not in ("", "Yes", "True", "true"):
            continue
        atype = r.get("Assignment Type", "").strip()
        uid = r.get("Optimised User Id", "").strip() or r.get("User Id", "").strip()
        s_loc = r.get("Start Location", "").strip()
        e_loc = r.get("End Location", "").strip()
        s_date = r.get("Start Date", "").strip()

        if atype in WORK_ASSIGNMENT_TYPES and r.get("Optimised User Id", "").strip():
            if s_loc:
                depot_starts[s_loc] += 1
                if s_date:
                    daily_depot[(s_date, s_loc)]["Starts"] += 1
            if e_loc:
                depot_ends[e_loc] += 1
                if s_date:
                    daily_depot[(s_date, e_loc)]["Ends"] += 1

        if atype in ("Travel In", "Travel Out"):
            interval = _shift_interval(r)
            hrs = round((interval[1] - interval[0]).total_seconds() / 3600.0, 2) if interval else 0.0
            total_travel_hours += hrs
            if atype == "Travel In":
                travel_in_count += 1
            else:
                travel_out_count += 1

            entry = travel_by_user.setdefault(
                uid,
                {
                    "User Id": uid,
                    "Home Depot": classify_user(dataset, r, uid),
                    "Travel In Legs": 0,
                    "Travel Out Legs": 0,
                    "Total Travel Hours": 0.0,
                },
            )
            entry["Home Depot"] = dataset.crew_by_id.get(uid, {}).get("Home Depot", "") or s_loc
            if atype == "Travel In":
                entry["Travel In Legs"] = int(entry["Travel In Legs"]) + 1
            else:
                entry["Travel Out Legs"] = int(entry["Travel Out Legs"]) + 1
            entry["Total Travel Hours"] = round(float(entry["Total Travel Hours"]) + hrs, 2)

    all_depots = sorted(set(depot_starts.keys()) | set(depot_ends.keys()))
    depot_rows = [
        {
            "Depot": d,
            "Shift Starts (Outflow)": depot_starts[d],
            "Shift Ends (Inflow)": depot_ends[d],
            "Net Balance (Ends - Starts)": depot_ends[d] - depot_starts[d],
        }
        for d in all_depots
    ]

    daily_rows = [
        {
            "Date": dt,
            "Depot": dep,
            "Shift Starts": vals["Starts"],
            "Shift Ends": vals["Ends"],
            "Net": vals["Ends"] - vals["Starts"],
        }
        for (dt, dep), vals in sorted(daily_depot.items())
    ]

    return {
        "depot_rows": depot_rows,
        "daily_depot_rows": daily_rows,
        "travel_rows": sorted(travel_by_user.values(), key=lambda x: (-float(x["Total Travel Hours"]), str(x["User Id"]))),
        "summary": {
            "depots_count": len(all_depots),
            "travel_in_legs": travel_in_count,
            "travel_out_legs": travel_out_count,
            "total_travel_legs": travel_in_count + travel_out_count,
            "total_travel_hours": round(total_travel_hours, 1),
        },
    }


def build_individual_crew_schedule(dataset: DashboardDataset, user_id: str) -> list[dict[str, object]]:
    """Return chronological roster timeline (shifts, travel, off, leave) for a specific crew member."""
    entries: list[tuple[datetime, dict[str, object]]] = []

    for r in dataset.roster_rows:
        opt_uid = r.get("Optimised User Id", "").strip()
        orig_uid = r.get("User Id", "").strip()
        is_gap = r.get("Is Gap", "").strip() == "True"
        atype = r.get("Assignment Type", "").strip()

        # Include row if assigned to user_id, or if it's user_id's own leave/off/travel row
        belongs = False
        role_note = ""
        if opt_uid == user_id:
            belongs = True
            role_note = "Assigned" if orig_uid == user_id else f"Reassigned (from {orig_uid or 'gap'})"
        elif orig_uid == user_id and (is_gap or atype in ("Travel In", "Travel Out", "Off")):
            belongs = True
            role_note = f"Leave ({r.get('Leave Type', '')})" if is_gap else atype

        if not belongs:
            continue

        interval = _shift_interval(r)
        s_dt = interval[0] if interval else _parse_dt(r.get("Start Date", ""), "00:00") or datetime.min
        e_dt = interval[1] if interval else s_dt

        entries.append(
            (
                s_dt,
                {
                    "Start Date": r.get("Start Date", ""),
                    "Shift Start": r.get("Shift Start Time", ""),
                    "End Date": r.get("End Date", ""),
                    "Shift End": r.get("Shift End Time", ""),
                    "Swing": r.get("Swing", ""),
                    "Assignment Type": atype,
                    "Activity Head": r.get("Activity Head", ""),
                    "Activity Name": r.get("Activity Name", ""),
                    "Start Location": r.get("Start Location", ""),
                    "End Location": r.get("End Location", ""),
                    "Status": role_note,
                    "Note": r.get("Optimisation Note", ""),
                    "_s": s_dt,
                    "_e": e_dt,
                },
            )
        )

    entries.sort(key=lambda x: x[0])
    schedule: list[dict[str, object]] = []
    prev_work_end: datetime | None = None

    for _, row in entries:
        rest_str = ""
        if row["Assignment Type"] in WORK_ASSIGNMENT_TYPES and row["Status"].startswith(("Assigned", "Reassigned")):
            if prev_work_end is not None:
                rest_hrs = (row["_s"] - prev_work_end).total_seconds() / 3600.0
                rest_str = f"{rest_hrs:.1f}h"
            prev_work_end = row["_e"]
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        clean["Rest Since Prev Shift"] = rest_str
        schedule.append(clean)

    return schedule


def build_executive_insights(dataset: DashboardDataset) -> list[dict[str, str]]:
    """Generate automated, evidence-based operational insights from solver outputs."""
    from visualization.gap_analysis import build_unfilled_gap_records, check_swing_home_depot
    from visualization.metrics import compute_summary_kpis

    kpis = compute_summary_kpis(dataset)
    unfilled = build_unfilled_gap_records(dataset)
    workload = compute_crew_workload_analytics(dataset)
    home_chk = check_swing_home_depot(dataset)

    insights: list[dict[str, str]] = []

    if kpis.unfilled_demand == 0:
        insights.append({
            "Severity": "success",
            "Title": "100% Demand Coverage Achieved",
            "Detail": f"All {kpis.total_demand} demand shifts are covered across the planning horizon.",
        })
    else:
        open_rem = max(0, kpis.unfilled_demand - kpis.locked_gaps)
        insights.append({
            "Severity": "warning" if open_rem > 0 else "info",
            "Title": f"{kpis.unfilled_demand} Unfilled Demand Shift(s) ({kpis.coverage_pct:.2f}% Coverage)",
            "Detail": (
                f"{kpis.locked_gaps} gap(s) are locked before Solver Start Date (Rule G1); "
                f"{open_rem} open gap(s) remain unfilled."
            ),
        })

    if unfilled:
        by_head: Counter[str] = Counter()
        zero_cand = 0
        for u in unfilled:
            by_head[str(u["Activity Head"])] += int(u["Remaining Gap"])
            if "No Legal Layer-1" in str(u.get("Diagnostic Category", "")):
                zero_cand += 1
        top_head, top_cnt = by_head.most_common(1)[0]
        insights.append({
            "Severity": "info",
            "Title": f"Top Unfilled Activity Head: {top_head} ({top_cnt} gaps)",
            "Detail": f"{zero_cand} unfilled slot(s) had zero Layer-1 legal candidate options.",
        })

    if dataset.rejections:
        rej_counts: Counter[str] = Counter()
        for r in dataset.rejections:
            reason = r.get("Reason", "").strip()
            try:
                cnt = int(r.get("Rows Rejected", "0"))
            except ValueError:
                cnt = 0
            if reason:
                rej_counts[reason] += cnt
        if rej_counts:
            top_rej, top_rej_cnt = rej_counts.most_common(1)[0]
            insights.append({
                "Severity": "info",
                "Title": f"Primary Layer-1 Rejection Reason: {top_rej}",
                "Detail": f"Blocked {top_rej_cnt} candidate-slot pairings during option generation.",
            })

    sb_kept = int(workload["summary"]["relief_standby_kept"])
    sb_total = int(workload["summary"]["relief_standby_total"])
    if sb_total > 0:
        insights.append({
            "Severity": "info",
            "Title": f"Relief Standby Utilization: {sb_total - sb_kept} / {sb_total} Deployed",
            "Detail": f"{sb_kept} Relief standby shift(s) remained on standby (not needed or constrained by depot/rest/certification).",
        })

    failed_swings = int(home_chk["failed_swings"])
    if failed_swings == 0 and int(home_chk["total_swings"]) > 0:
        insights.append({
            "Severity": "success",
            "Title": "Home Depot Swing Integrity: 100% PASS",
            "Detail": f"All {home_chk['total_swings']} active crew swings start and end at their Home Depot.",
        })
    elif failed_swings > 0:
        insights.append({
            "Severity": "warning",
            "Title": f"Home Depot Check: {failed_swings} Swing(s) Flagged",
            "Detail": f"{home_chk['passed_swings']} / {home_chk['total_swings']} swings passed start/end Home Depot checks.",
        })

    return insights


def compute_solver_cost_and_offset_analytics(dataset: DashboardDataset) -> dict[str, object]:
    """Break down reassignment costs by source type & activity head, plus F1/F3 start-time offsets."""
    cost_by_source: Counter[str] = Counter()
    count_by_source: Counter[str] = Counter()
    cost_by_head: Counter[str] = Counter()
    offset_counts: Counter[str] = Counter()
    total_cost = 0

    for r in dataset.reassignments:
        src = r.get("Source", "").strip() or "Unknown"
        act = r.get("Activity Name", "").strip() or r.get("Activity ID", "").strip() or "Unknown"
        try:
            c = int(float(r.get("Cost", "0") or 0))
        except ValueError:
            c = 0
        try:
            off = int(float(r.get("Offset Minutes", "0") or 0))
        except ValueError:
            off = 0

        cost_by_source[src] += c
        count_by_source[src] += 1
        cost_by_head[act] += c
        total_cost += c

        if off == 0:
            offset_counts["0 min (Exact)"] += 1
        elif off < 0:
            offset_counts[f"{off} min (Lift-up)"] += 1
        else:
            offset_counts[f"+{off} min (Layback)"] += 1

    source_rows = [
        {
            "Source Type": src,
            "Moves": count_by_source[src],
            "Total Cost": cost_by_source[src],
            "Avg Cost / Move": round(cost_by_source[src] / count_by_source[src], 2) if count_by_source[src] else 0.0,
        }
        for src in sorted(cost_by_source.keys())
    ]
    offset_rows = [
        {"Start Offset": lbl, "Moves": cnt}
        for lbl, cnt in sorted(offset_counts.items())
    ]
    head_cost_rows = [
        {"Activity": act, "Total Cost": cst}
        for act, cst in cost_by_head.most_common()
    ]
    return {
        "total_cost": total_cost,
        "total_moves": len(dataset.reassignments),
        "source_rows": source_rows,
        "offset_rows": offset_rows,
        "head_cost_rows": head_cost_rows,
    }


def compute_skill_and_currency_radar(dataset: DashboardDataset) -> dict[str, object]:
    """Analyze certification supply vs demand, depot x head matrix, and currency expiry risk."""
    # Daily demand per Activity Head
    daily_demand_by_head: Counter[str] = Counter()
    for d in dataset.demand_rows:
        if d.get("Is Active", "Yes").strip() in ("", "Yes", "True", "true"):
            head = d.get("Activity Head", "").strip()
            try:
                qty = int(d.get("Demand", "0"))
            except ValueError:
                qty = 0
            if head:
                daily_demand_by_head[head] += qty

    # Eligibility per Activity Head & Depot x Activity Head matrix
    eligible_users_by_head: dict[str, set[str]] = defaultdict(set)
    for e in dataset.eligibility_rows:
        head = e.get("Activity Head", "").strip()
        raw_users = e.get("Eligible User Ids", "").strip()
        if not head:
            continue
        for uid in raw_users.replace(",", ";").split(";"):
            u = uid.strip()
            if u:
                eligible_users_by_head[head].add(u)

    all_heads = sorted(set(daily_demand_by_head.keys()) | set(eligible_users_by_head.keys()))
    supply_rows: list[dict[str, object]] = []
    depot_head_counts: Counter[tuple[str, str]] = Counter()
    all_depots: set[str] = set()

    for head in all_heads:
        elig_set = eligible_users_by_head.get(head, set())
        elig_cnt = len(elig_set)
        dem_cnt = daily_demand_by_head.get(head, 0)
        ratio = round(elig_cnt / dem_cnt, 2) if dem_cnt > 0 else float(elig_cnt)
        if dem_cnt > 0 and ratio < 2.0:
            risk = "Critical (<2.0x)"
        elif dem_cnt > 0 and ratio < 3.5:
            risk = "Tight (<3.5x)"
        else:
            risk = "Healthy"

        supply_rows.append({
            "Activity Head": head,
            "Priority": dataset.priority_by_head.get(head, 999),
            "Eligible Crew": elig_cnt,
            "Daily Demand (Shifts)": dem_cnt,
            "Supply / Daily Demand Ratio": ratio,
            "Risk Status": risk,
        })

        for uid in elig_set:
            depot = dataset.crew_by_id.get(uid, {}).get("Home Depot", "").strip() or "Unknown"
            all_depots.add(depot)
            depot_head_counts[(depot, head)] += 1

    matrix_rows: list[dict[str, object]] = []
    for dep in sorted(all_depots):
        for head in all_heads:
            matrix_rows.append({
                "Depot": dep,
                "Activity Head": head,
                "Eligible Crew": depot_head_counts.get((dep, head), 0),
            })

    # Currency threshold watchlist
    threshold_by_head: dict[str, int] = {}
    for a in dataset.activities_rows:
        head = a.get("Activity Head", "").strip()
        raw_th = a.get("Currency Threshold", "").strip()
        if head and raw_th:
            try:
                th_val = int(float(raw_th))
                if head not in threshold_by_head or th_val < threshold_by_head[head]:
                    threshold_by_head[head] = th_val
            except ValueError:
                pass

    horizon_start_str = dataset.constraints.get("Planning Horizon Start", ("2026-11-01", "Active"))[0]
    horizon_days_str = dataset.constraints.get("Planning Horizon Days", ("30", "Active"))[0]
    try:
        h_start = datetime.fromisoformat(horizon_start_str).date()
        h_end = h_start + timedelta(days=int(horizon_days_str))
    except Exception:
        h_start = datetime(2026, 11, 1).date()
        h_end = h_start + timedelta(days=30)

    # Track assigned work dates during the horizon so currency refreshes are accounted for
    performed_dates: dict[tuple[str, str], list[datetime.date]] = defaultdict(list)
    for r in dataset.roster_rows:
        if r.get("Assignment Type", "").strip() not in WORK_ASSIGNMENT_TYPES:
            continue
        opt_uid = r.get("Optimised User Id", "").strip()
        head = r.get("Activity Head", "").strip()
        s_date = r.get("Start Date", "").strip()
        if opt_uid and head and s_date:
            try:
                performed_dates[(opt_uid, head)].append(datetime.fromisoformat(s_date).date())
            except ValueError:
                pass
    for key in performed_dates:
        performed_dates[key].sort()

    currency_watchlist: list[dict[str, object]] = []
    for c in dataset.currency_rows:
        uid = c.get("User Id", "").strip()
        head = c.get("Activity Head", "").strip()
        last_str = c.get("Last Performed Date", "").strip()
        th_days = threshold_by_head.get(head)
        if not uid or not head or not last_str or th_days is None:
            continue
        try:
            last_dt = datetime.fromisoformat(last_str).date()
        except ValueError:
            continue
        expiry_dt = last_dt + timedelta(days=th_days)
        for work_dt in performed_dates.get((uid, head), ()):
            if last_dt < work_dt <= expiry_dt:
                last_dt = work_dt
                expiry_dt = last_dt + timedelta(days=th_days)
        if expiry_dt <= h_end:
            status = "Expired Before Horizon" if expiry_dt < h_start else "Expiring In Horizon"
            crew_info = dataset.crew_by_id.get(uid, {})
            currency_watchlist.append({
                "User Id": uid,
                "Home Depot": crew_info.get("Home Depot", "") or crew_info.get("Depot", ""),
                "Activity Head": head,
                "Last Performed": last_dt.isoformat(),
                "Threshold (Days)": th_days,
                "Currency Expires": expiry_dt.isoformat(),
                "Status": status,
            })

    return {
        "supply_rows": sorted(supply_rows, key=lambda r: (int(r["Priority"]), str(r["Activity Head"]))),
        "matrix_rows": matrix_rows,
        "currency_watchlist": sorted(currency_watchlist, key=lambda r: str(r["Currency Expires"])),
    }


def compute_resilience_and_pool_analytics(dataset: DashboardDataset) -> dict[str, object]:
    """Compute rest-hour margins between consecutive work shifts and daily crew pool states."""
    per_user_work: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
    daily_pool: dict[str, Counter[str]] = defaultdict(Counter)

    for r in dataset.roster_rows:
        if r.get("In Horizon", "Yes").strip() not in ("", "Yes", "True", "true"):
            continue
        s_date = r.get("Start Date", "").strip()
        atype = r.get("Assignment Type", "").strip()
        is_gap = r.get("Is Gap", "").strip() == "True"
        opt_uid = r.get("Optimised User Id", "").strip()

        if s_date:
            if is_gap and not opt_uid:
                daily_pool[s_date]["On Leave / Unfilled Gap"] += 1
            elif atype == "Demand" and opt_uid:
                daily_pool[s_date]["Working (Demand)"] += 1
            elif atype == "Excess" and opt_uid:
                daily_pool[s_date]["Working (Excess)"] += 1
            elif atype == "Relief" and opt_uid:
                daily_pool[s_date]["Relief Standby"] += 1
            elif atype in ("Travel In", "Travel Out"):
                daily_pool[s_date]["Traveling"] += 1
            elif atype == "Off":
                daily_pool[s_date]["Off-Swing"] += 1

        if atype in WORK_ASSIGNMENT_TYPES and opt_uid:
            interval = _shift_interval(r)
            if interval:
                per_user_work[opt_uid].append((interval[0], interval[1], r.get("Activity Head", "").strip()))

    rest_margins: list[dict[str, object]] = []
    bucket_counts: Counter[str] = Counter()
    tight_rest_count = 0

    for uid, shifts in sorted(per_user_work.items()):
        shifts.sort(key=lambda x: x[0])
        for i in range(1, len(shifts)):
            prev_s, prev_e, _ = shifts[i - 1]
            cur_s, cur_e, cur_head = shifts[i]
            gap_hrs = (cur_s - prev_e).total_seconds() / 3600.0
            if gap_hrs > 48.0:
                continue  # Swing break, not intra-swing rest
            if gap_hrs < 11.0:
                bucket = "<11h (Violation)"
            elif gap_hrs < 12.5:
                bucket = "11h - 12.5h (Tight)"
                tight_rest_count += 1
            elif gap_hrs < 16.0:
                bucket = "12.5h - 16h (Moderate)"
            elif gap_hrs < 23.0:
                bucket = "16h - 23h (Comfortable)"
            else:
                bucket = "23h+ (Transition / Long)"

            bucket_counts[bucket] += 1
            rest_margins.append({
                "User Id": uid,
                "Shift Start": cur_s.strftime("%Y-%m-%d %H:%M"),
                "Activity Head": cur_head,
                "Rest Hours": round(gap_hrs, 2),
                "Margin Category": bucket,
            })

    bucket_order = [
        "<11h (Violation)",
        "11h - 12.5h (Tight)",
        "12.5h - 16h (Moderate)",
        "16h - 23h (Comfortable)",
        "23h+ (Transition / Long)",
    ]
    rest_buckets = [{"Category": b, "Transitions": bucket_counts.get(b, 0)} for b in bucket_order]

    pool_rows: list[dict[str, object]] = []
    for dt in sorted(daily_pool.keys()):
        c = daily_pool[dt]
        pool_rows.append({
            "Date": dt,
            "Working (Demand)": c.get("Working (Demand)", 0),
            "Working (Excess)": c.get("Working (Excess)", 0),
            "Relief Standby": c.get("Relief Standby", 0),
            "Traveling": c.get("Traveling", 0),
            "On Leave / Unfilled Gap": c.get("On Leave / Unfilled Gap", 0),
            "Off-Swing": c.get("Off-Swing", 0),
        })

    return {
        "rest_margins": sorted(rest_margins, key=lambda x: float(x["Rest Hours"])),
        "rest_buckets": rest_buckets,
        "tight_rest_count": tight_rest_count,
        "daily_pool_rows": pool_rows,
    }


def compute_run_diff(ds_a: DashboardDataset, ds_b: DashboardDataset) -> list[dict[str, object]]:
    """Compare two solver runs row-by-row by Assignment ID and return changed assignments."""
    by_id_a = {r.get("Assignment ID", "").strip(): r for r in ds_a.roster_rows if r.get("Assignment ID", "").strip()}
    by_id_b = {r.get("Assignment ID", "").strip(): r for r in ds_b.roster_rows if r.get("Assignment ID", "").strip()}

    diffs: list[dict[str, object]] = []
    for aid in sorted(set(by_id_a.keys()) & set(by_id_b.keys())):
        ra = by_id_a[aid]
        rb = by_id_b[aid]
        ua = ra.get("Optimised User Id", "").strip()
        ub = rb.get("Optimised User Id", "").strip()
        sa = ra.get("Shift Start Time", "").strip()
        sb = rb.get("Shift Start Time", "").strip()
        ha = ra.get("Activity Head", "").strip()
        hb = rb.get("Activity Head", "").strip()
        if ua != ub or sa != sb or ha != hb:
            diffs.append({
                "Assignment ID": aid,
                "Date": ra.get("Start Date", ""),
                "Activity Head": ha,
                f"{ds_a.name} Crew": ua or "<UNFILLED>",
                f"{ds_b.name} Crew": ub or "<UNFILLED>",
                f"{ds_a.name} Start": sa,
                f"{ds_b.name} Start": sb,
            })
    return diffs


def compute_input_readiness_analytics(dataset: DashboardDataset) -> dict[str, object]:
    """Analyze pre-solver input data: competencies, restrictions, exclusions, onsite checks, and baseline supply."""
    # 1. Competency & Compliance Matrix
    req_by_head: dict[str, set[str]] = defaultdict(set)
    for row in dataset.compliance_rows:
        head = row.get("Activity Head", "").strip()
        code = row.get("Competency LMS Code", "").strip()
        comp = row.get("Competency", "").strip()
        if head and (code or comp):
            req_by_head[head].add(code or comp)

    comp_status_by_user: dict[str, dict[str, str]] = defaultdict(dict)
    invalid_competencies: list[dict[str, str]] = []
    for row in dataset.competency_rows:
        uid = row.get("User Id", "").strip()
        code = row.get("Competency LMS Code", "").strip()
        comp = row.get("Competency", "").strip()
        status = row.get("status", "").strip() or row.get("Status", "").strip()
        expiry = row.get("Expiry Date", "").strip()
        key = code or comp
        if uid and key:
            comp_status_by_user[uid][key] = status or "Unknown"
        if status and status.lower() != "valid":
            crew_meta = dataset.crew_by_id.get(uid, {})
            invalid_competencies.append({
                "User Id": uid,
                "Depot": crew_meta.get("Home Depot", "") or crew_meta.get("Depot", ""),
                "Classification": crew_meta.get("Classification", ""),
                "Competency Code": code,
                "Competency": comp,
                "Expiry Date": expiry,
                "Status": status,
            })

    total_crew = len(dataset.crew_by_id)
    competency_matrix_rows: list[dict[str, object]] = []
    for head in sorted(req_by_head.keys()):
        reqs = sorted(req_by_head[head])
        compliant = 0
        non_compliant = 0
        for uid in dataset.crew_by_id:
            u_comps = comp_status_by_user.get(uid, {})
            if all(u_comps.get(r, "").lower() == "valid" for r in reqs):
                compliant += 1
            else:
                non_compliant += 1
        competency_matrix_rows.append({
            "Activity Head": head,
            "Required Competencies": ", ".join(reqs),
            "Compliant Crew": compliant,
            "Blocked / Missing Crew": non_compliant,
            "Compliance %": round((compliant / total_crew * 100.0), 1) if total_crew else 0.0,
        })

    # 2. Onsite App Cross-Check
    roster_by_user_date: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in dataset.roster_rows:
        uid = r.get("Optimised User Id", "").strip() or r.get("User Id", "").strip()
        dt = r.get("Start Date", "").strip()
        if uid and dt:
            roster_by_user_date[(uid, dt)].append(r)

    onsite_mismatches: list[dict[str, str]] = []
    for o in dataset.onsite_rows:
        uid = o.get("User Id", "").strip()
        dt = o.get("Date", "").strip()
        loc = o.get("Location", "").strip()
        status = o.get("Status", "").strip()
        matched = roster_by_user_date.get((uid, dt), [])
        if not matched and status.lower() in {"onsite", "checked in", "active", "present"}:
            onsite_mismatches.append({
                "User Id": uid,
                "Date": dt,
                "Onsite Location": loc,
                "Onsite Status": status,
                "Roster Status": "No Matching Shift",
            })

    # 3. Pre-Gap Baseline Supply vs Demand by Date
    source_rows = dataset.baseline_roster_rows or dataset.roster_rows
    daily_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"Demand Shifts": 0, "Baseline Assigned": 0, "Relief/Excess Pool": 0})
    for r in source_rows:
        dt = r.get("Start Date", "").strip()
        if not dt:
            continue
        atype = r.get("Assignment Type", "").strip()
        uid = r.get("User Id", "").strip() or r.get("Optimised User Id", "").strip()
        if atype == "Demand":
            daily_counts[dt]["Demand Shifts"] += 1
            if uid:
                daily_counts[dt]["Baseline Assigned"] += 1
        elif atype in {"Relief", "Excess"} and uid:
            daily_counts[dt]["Relief/Excess Pool"] += 1

    daily_supply_rows = [
        {"Date": dt, **daily_counts[dt]}
        for dt in sorted(daily_counts.keys())
    ]

    return {
        "competency_matrix": competency_matrix_rows,
        "invalid_competencies": invalid_competencies,
        "restrictions": dataset.restriction_rows,
        "excluded_activities": dataset.excluded_activity_rows,
        "onsite_mismatches": onsite_mismatches,
        "onsite_total": len(dataset.onsite_rows),
        "daily_supply_rows": daily_supply_rows,
    }


def compute_lifecycle_waterfall(dataset: DashboardDataset) -> dict[str, object]:
    """Compute 3-stage lifecycle metrics: Baseline -> Leave Gaps -> Solver Recovery."""
    demand_rows = [r for r in dataset.roster_rows if r.get("Assignment Type", "").strip() == "Demand"]
    total_demand = len(demand_rows)
    gap_rows = [r for r in demand_rows if r.get("Is Gap", "").strip() == "True"]
    locked_gaps = sum(1 for r in gap_rows if r.get("Is_locked_gap", "").strip() == "True")
    open_gaps = len(gap_rows) - locked_gaps
    filled_gaps = sum(1 for r in gap_rows if r.get("Optimised User Id", "").strip())
    remaining_unfilled = len(gap_rows) - filled_gaps
    undisturbed = total_demand - len(gap_rows)

    # Break down fills into Direct (Level 1 / Relief / Excess) vs Multi-Hop Chain
    chains_data = build_reassignment_chains(dataset)
    chain_moves = int(chains_data["summary"].get("chain_moves", 0))
    direct_fills = max(0, filled_gaps - chain_moves)
    multi_hop_fills = min(filled_gaps, chain_moves)

    leave_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: {"Total": 0, "Locked": 0, "Open": 0, "Filled": 0, "Unfilled": 0})
    for r in gap_rows:
        lt = r.get("Leave Type", "").strip() or "Unspecified"
        is_locked = r.get("Is_locked_gap", "").strip() == "True"
        is_filled = bool(r.get("Optimised User Id", "").strip())
        leave_breakdown[lt]["Total"] += 1
        if is_locked:
            leave_breakdown[lt]["Locked"] += 1
        else:
            leave_breakdown[lt]["Open"] += 1
        if is_filled:
            leave_breakdown[lt]["Filled"] += 1
        else:
            leave_breakdown[lt]["Unfilled"] += 1

    leave_rows = [
        {"Leave Type": lt, **vals}
        for lt, vals in sorted(leave_breakdown.items(), key=lambda x: -x[1]["Total"])
    ]

    return {
        "total_demand": total_demand,
        "undisturbed": undisturbed,
        "total_gaps": len(gap_rows),
        "locked_gaps": locked_gaps,
        "open_gaps": open_gaps,
        "direct_fills": direct_fills,
        "multi_hop_fills": multi_hop_fills,
        "final_covered": undisturbed + filled_gaps,
        "remaining_unfilled": remaining_unfilled,
        "leave_breakdown": leave_rows,
    }


def compute_option_density_vs_fill(dataset: DashboardDataset) -> list[dict[str, object]]:
    """Join seats.csv, gap_options.csv, and roster_rows to inspect option count vs fill outcome."""
    opts_by_seat: dict[str, int] = defaultdict(int)
    for opt in dataset.gap_options:
        sk = opt.get("Seat Key", "").strip()
        if sk:
            opts_by_seat[sk] += 1

    unfilled_aids = {u.get("Assignment ID", "").strip() for u in dataset.unfilled_gaps if u.get("Assignment ID", "").strip()}
    roster_by_aid = {r.get("Assignment ID", "").strip(): r for r in dataset.roster_rows if r.get("Assignment ID", "").strip()}

    rows: list[dict[str, object]] = []
    for seat in dataset.seats:
        sk = seat.get("Seat Key", "").strip()
        aid = seat.get("Assignment ID", "").strip()
        head = seat.get("Activity Head", "").strip() or roster_by_aid.get(aid, {}).get("Activity Head", "")
        dt = seat.get("Start Date", "").strip() or seat.get("Date", "").strip() or roster_by_aid.get(aid, {}).get("Start Date", "")
        shift = seat.get("Shift Start Time", "").strip() or roster_by_aid.get(aid, {}).get("Shift Start Time", "")
        prio = dataset.priority_by_head.get(head, 99)
        r_row = roster_by_aid.get(aid, {})
        is_filled = bool(r_row.get("Optimised User Id", "").strip()) and aid not in unfilled_aids
        rows.append({
            "Seat Key": sk,
            "Assignment ID": aid,
            "Activity Head": head,
            "Date": dt,
            "Shift": shift,
            "Priority": prio,
            "Legal Options (Layer 1)": opts_by_seat.get(sk, 0),
            "Filled": 1 if is_filled else 0,
            "Outcome": "Filled" if is_filled else "Unfilled",
        })
    return rows


def compute_slot_diff_matrix(ds_a: DashboardDataset, ds_b: DashboardDataset) -> list[dict[str, object]]:
    """Compare slot coverage between two runs by (Date, Shift, Activity Head)."""
    from visualization.metrics import build_demand_slot_records

    slots_a = build_demand_slot_records(ds_a)
    slots_b = build_demand_slot_records(ds_b)
    map_a = {(str(s["Date"]), str(s["Shift"]), str(s["Activity Head"])): s for s in slots_a}
    map_b = {(str(s["Date"]), str(s["Shift"]), str(s["Activity Head"])): s for s in slots_b}

    diffs: list[dict[str, object]] = []
    for key in sorted(set(map_a.keys()) | set(map_b.keys())):
        sa = map_a.get(key, {})
        sb = map_b.get(key, {})
        cov_a = int(sa.get("Assigned", 0))
        cov_b = int(sb.get("Assigned", 0))
        delta = cov_b - cov_a
        status = "Improved" if delta > 0 else ("Degraded" if delta < 0 else "Unchanged")
        diffs.append({
            "Date": key[0],
            "Shift": key[1],
            "Activity Head": key[2],
            "Baseline Assigned": cov_a,
            "Comparison Assigned": cov_b,
            "Delta": delta,
            "Change": status,
        })
    return diffs


def parse_solver_log_metrics(log_text: str) -> dict[str, object]:
    """Parse Layer-1 / CP-SAT log text into structured stage summaries, severity counts, and filtered lines."""
    import re

    lines = [ln for ln in log_text.splitlines() if ln.strip()]
    stages: list[dict[str, object]] = []
    cur_stage = "General"
    stage_line_counts: dict[str, int] = defaultdict(int)
    severity_counts = {"INFO": 0, "STAGE": 0, "WARNING": 0, "ERROR": 0}
    parsed_lines: list[dict[str, object]] = []

    stage_re = re.compile(r"^===\s*(.+?)\s*===$")
    time_re = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)\b", re.IGNORECASE)

    for idx, line in enumerate(lines, start=1):
        m_stage = stage_re.match(line.strip())
        if m_stage:
            cur_stage = m_stage.group(1)
            sev = "STAGE"
            stages.append({"Stage": cur_stage, "Start Line": idx, "Duration (s)": 0.0})
        elif any(tok in line.upper() for tok in ("ERROR", "TRACEBACK", "EXCEPTION", "INFEASIBLE", "FAILED")):
            sev = "ERROR"
        elif any(tok in line.upper() for tok in ("WARN", "SKIPPING", "TIMEOUT")):
            sev = "WARNING"
        else:
            sev = "INFO"

        severity_counts[sev] += 1
        stage_line_counts[cur_stage] += 1

        m_time = time_re.search(line)
        if m_time and stages:
            try:
                val = float(m_time.group(1))
                if val > float(stages[-1]["Duration (s)"]) and val < 36000:
                    stages[-1]["Duration (s)"] = val
            except ValueError:
                pass

        parsed_lines.append({
            "Line": idx,
            "Stage": cur_stage,
            "Severity": sev,
            "Message": line,
        })

    for stg in stages:
        stg["Log Lines"] = stage_line_counts.get(str(stg["Stage"]), 0)

    return {
        "total_lines": len(lines),
        "severity_counts": severity_counts,
        "stages": stages,
        "lines": parsed_lines,
    }
