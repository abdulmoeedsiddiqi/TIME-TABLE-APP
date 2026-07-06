"""
Constraint-based timetable generator for the GIKI Automated Timetable System.

Hard Constraints (strictly enforced):
  HC1: A teacher cannot teach two classes at the same time.
  HC2: A room cannot host two classes at the same time.
  HC3: A student section cannot attend two classes at the same time.
  HC4: Every offering is scheduled for the required number of weekly sessions.

Soft constraints (optimized via candidate scoring):
  - Spread classes across Monday-Friday
  - Minimize section gaps
  - Avoid long consecutive section lectures
  - Prefer capacity-fit rooms
  - Balance teacher workload across days
  - Avoid placing electives in very early slots
"""

from __future__ import annotations
import random, time, copy
from collections import defaultdict
from typing import Dict, Iterable, Optional, Set, Tuple, List

DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _day_index(day: str) -> int:
    return DAY_ORDER.index(day) if day in DAY_ORDER else len(DAY_ORDER)


def _normalize_room_type(raw_type: str) -> str:
    return "lab" if str(raw_type or "").lower() == "lab" else "lecture"


def _max_consecutive_streak(periods: Iterable[int]) -> int:
    ordered = sorted(set(periods))
    if not ordered:
        return 0
    best = current = 1
    for idx in range(1, len(ordered)):
        if ordered[idx] == ordered[idx - 1] + 1:
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best


def _build_time_slot_maps(time_slots):
    filtered_slots = [ts for ts in time_slots if ts.get("day") in DAY_ORDER]
    slot_by_id = {ts["id"]: ts for ts in filtered_slots}
    ordered_slots = sorted(filtered_slots, key=lambda ts: (_day_index(ts["day"]), int(ts.get("period_number", 0) or 0)))
    day_period_to_slot: Dict[str, Dict[int, dict]] = defaultdict(dict)
    for ts in ordered_slots:
        day_period_to_slot[ts["day"]][int(ts["period_number"])] = ts
    return slot_by_id, ordered_slots, day_period_to_slot


def _build_blocks(day_period_to_slot, duration):
    blocks = []
    for day in DAY_ORDER:
        period_map = day_period_to_slot.get(day, {})
        if not period_map:
            continue
        max_period = max(period_map.keys())
        for start in range(1, max_period - duration + 2):
            block = []
            for period in range(start, start + duration):
                slot = period_map.get(period)
                if slot is None:
                    block = []
                    break
                block.append(slot["id"])
            if block:
                blocks.append(tuple(block))
    return blocks


def _build_session_tasks(offerings, config):
    lab_duration = int(config.get("LAB_SESSION_DURATION", 3))
    tasks = []
    expected = {}
    for offering in offerings:
        weekly = int(offering.get("sessions_per_week", 0) or 0)
        if weekly <= 0:
            continue
        ctype = "lab" if offering.get("course_type") == "lab" else "theory"
        ch = int(offering.get("credit_hours", 3) or 3)
        duration = (1 if ch <= 1 else lab_duration) if ctype == "lab" else 1
        expected[offering["id"]] = weekly
        for si in range(weekly):
            tasks.append({
                "task_id": f"{offering['id']}#{si+1}", "session_index": si+1,
                "offering_id": offering["id"], "course_code": offering.get("course_code", ""),
                "teacher_id": offering.get("teacher_id"), "section_id": offering["section_id"],
                "program_code": offering.get("program_code"), "year": offering.get("year"),
                "course_type": ctype, "is_elective": bool(offering.get("is_elective")),
                "student_count": int(offering.get("student_count", 0) or 0),
                "duration": duration, "sessions_per_week": weekly,
            })
    tload = defaultdict(int)
    sload = defaultdict(int)
    for t in tasks:
        if t.get("teacher_id"): tload[t["teacher_id"]] += 1
        sload[t["section_id"]] += 1
    tasks.sort(key=lambda t: (t["duration"], t["student_count"], tload.get(t.get("teacher_id"), 0), sload.get(t["section_id"], 0), t["course_code"]), reverse=True)
    return tasks, expected


def _build_domains(tasks, rooms, ordered_slots, lab_blocks):
    rtype = {r["id"]: _normalize_room_type(r.get("room_type")) for r in rooms}
    lec_ids = [rid for rid, t in rtype.items() if t == "lecture"]
    lab_ids = [rid for rid, t in rtype.items() if t == "lab"]
    domains = {}
    for task in tasks:
        cands = lab_ids if task["course_type"] == "lab" else lec_ids
        candidates = []
        if task["duration"] == 1:
            for slot in ordered_slots:
                for rid in cands:
                    candidates.append((rid, (slot["id"],)))
            if task["course_type"] == "lab":
                for slot in ordered_slots:
                    for rid in lec_ids:
                        candidates.append((rid, (slot["id"],)))
        else:
            for block in lab_blocks:
                for rid in cands:
                    candidates.append((rid, block))
        domains[task["task_id"]] = candidates
    return domains

# ---------------------------------------------------------------------------
# Busy-set helpers
# ---------------------------------------------------------------------------

def _is_busy(eid, slot_ids, busy):
    if not eid:
        return False
    return any((eid, sid) in busy for sid in slot_ids)


def _candidate_penalty(task, room_id, slot_ids, slot_by_id, room_capacity, section_day_periods, section_day_load, teacher_day_load, global_day_load):
    first_slot = slot_by_id[slot_ids[0]]
    day = first_slot["day"]
    periods = [slot_by_id[sid]["period_number"] for sid in slot_ids]
    sid = task["section_id"]
    tid = task.get("teacher_id")
    dur = len(slot_ids)
    p = 0.0
    cs = int(task.get("student_count", 0) or 0)
    cap = int(room_capacity.get(room_id, 0) or 0)
    if cap and cap < cs: p += (cs - cap) * 8.0
    elif cap: p += (cap - cs) * 0.04
    sl = section_day_load.get(sid, {})
    bdl = sl.get(day, 0)
    ta = sum(sl.values()) + dur
    p += abs((bdl + dur) - ta / len(DAY_ORDER)) * 2.5
    p += bdl * 1.2
    gb = global_day_load.get(day, 0)
    gt = sum(global_day_load.values()) + dur
    p += abs((gb + dur) - gt / len(DAY_ORDER)) * 0.08
    ep = set(section_day_periods.get(sid, {}).get(day, set()))
    sim = set(ep).union(periods)
    if len(sim) > 1:
        o = sorted(sim)
        p += ((o[-1] - o[0] + 1) - len(o)) * 1.1
    s = _max_consecutive_streak(sim)
    if s > 3: p += (s - 3) * 4.0
    if tid:
        tl = teacher_day_load.get(tid, {})
        tb = tl.get(day, 0)
        tt = sum(tl.values()) + dur
        p += abs((tb + dur) - tt / len(DAY_ORDER)) * 1.6
        p += tb * 0.8
    if task.get("is_elective") and first_slot["period_number"] <= 2: p += 2.0
    p += ((_day_index(day) - (sid % len(DAY_ORDER))) % len(DAY_ORDER)) * 0.03
    p += first_slot["period_number"] * 0.01
    return p


def _place_task(task, domains, teacher_busy, room_busy, section_busy, slot_by_id, room_capacity, section_day_periods, section_day_load, teacher_day_load, global_day_load):
    """Try to place a single task. Returns (room_id, slot_ids) or None."""
    feasible = []
    for room_id, slot_ids in domains[task["task_id"]]:
        if _is_busy(task.get("teacher_id"), slot_ids, teacher_busy): continue
        if _is_busy(room_id, slot_ids, room_busy): continue
        if _is_busy(task["section_id"], slot_ids, section_busy): continue
        penalty = _candidate_penalty(task, room_id, slot_ids, slot_by_id, room_capacity, section_day_periods, section_day_load, teacher_day_load, global_day_load)
        feasible.append((penalty, room_id, slot_ids))
    if not feasible:
        return None
    feasible.sort(key=lambda x: x[0])
    return (feasible[0][1], feasible[0][2])


def _commit(task, room_id, slot_ids, slot_by_id, teacher_busy, room_busy, section_busy, section_day_load, section_day_periods, teacher_day_load, global_day_load):
    """Commit an assignment into the busy sets."""
    for sid in slot_ids:
        if task.get("teacher_id"):
            teacher_busy.add((task["teacher_id"], sid))
            teacher_day_load[task["teacher_id"]][slot_by_id[sid]["day"]] += 1
        room_busy.add((room_id, sid))
        section_busy.add((task["section_id"], sid))
        section_day_load[task["section_id"]][slot_by_id[sid]["day"]] += 1
        section_day_periods[task["section_id"]][slot_by_id[sid]["day"]].add(slot_by_id[sid]["period_number"])
        global_day_load[slot_by_id[sid]["day"]] += 1


def _uncommit(task, room_id, slot_ids, slot_by_id, teacher_busy, room_busy, section_busy, section_day_load, section_day_periods, teacher_day_load, global_day_load):
    """Remove an assignment from the busy sets."""
    for sid in slot_ids:
        if task.get("teacher_id"):
            teacher_busy.discard((task["teacher_id"], sid))
            teacher_day_load[task["teacher_id"]][slot_by_id[sid]["day"]] -= 1
        room_busy.discard((room_id, sid))
        section_busy.discard((task["section_id"], sid))
        section_day_load[task["section_id"]][slot_by_id[sid]["day"]] -= 1
        section_day_periods[task["section_id"]][slot_by_id[sid]["day"]].discard(slot_by_id[sid]["period_number"])
        global_day_load[slot_by_id[sid]["day"]] -= 1

# ---------------------------------------------------------------------------
# Hard-constraint validator  (post-generation integrity check)
# ---------------------------------------------------------------------------

def _validate_hard_constraints(assignments, expected, offerings, slot_by_id):
    """Verify all 4 hard constraints. Returns dict with status and violations."""
    violations = {"HC1_teacher": [], "HC2_room": [], "HC3_section": [], "HC4_sessions": []}
    off_map = {o["id"]: o for o in offerings}
    teacher_slots = defaultdict(set)
    room_slots = defaultdict(set)
    section_slots = defaultdict(set)
    for a in assignments:
        off = off_map.get(a["offering_id"], {})
        rid = a["room_id"]
        sids = tuple(a.get("time_slot_ids") or [a["time_slot_id"]])
        for sid in sids:
            # HC1
            tid = off.get("teacher_id")
            if tid:
                if sid in teacher_slots[tid]:
                    violations["HC1_teacher"].append(f"Teacher {tid} double-booked at slot {sid}")
                teacher_slots[tid].add(sid)
            # HC2
            if sid in room_slots[rid]:
                violations["HC2_room"].append(f"Room {rid} double-booked at slot {sid}")
            room_slots[rid].add(sid)
            # HC3
            sec = off.get("section_id")
            if sec:
                if sid in section_slots[sec]:
                    violations["HC3_section"].append(f"Section {sec} double-booked at slot {sid}")
                section_slots[sec].add(sid)
    # HC4
    counts = defaultdict(int)
    for a in assignments:
        counts[a["offering_id"]] += 1
    for oid, exp in expected.items():
        got = counts.get(oid, 0)
        if got != exp:
            off = off_map.get(oid, {})
            violations["HC4_sessions"].append(f"{off.get('course_code','?')} (section {off.get('section_id','?')}) expected {exp} sessions, got {got}")
    total = sum(len(v) for v in violations.values())
    return {"satisfied": total == 0, "total_violations": total, "violations": violations}

# ---------------------------------------------------------------------------
# Single-attempt solver (greedy + retry + swap repair)
# ---------------------------------------------------------------------------

def _solve_once(tasks, domains, slot_by_id, room_capacity, task_by_id, started, max_time, shuffle_seed=None):
    """Run one complete attempt. Returns (assignments, assigned_task_ids, unplaced)."""
    teacher_busy: Set[Tuple] = set()
    room_busy: Set[Tuple] = set()
    section_busy: Set[Tuple] = set()
    teacher_day_load = defaultdict(lambda: defaultdict(int))
    section_day_load = defaultdict(lambda: defaultdict(int))
    section_day_periods = defaultdict(lambda: defaultdict(set))
    global_day_load = defaultdict(int)

    assignments: List[dict] = []
    assigned_task_ids: Set[str] = set()

    def _try_place(task):
        result = _place_task(task, domains, teacher_busy, room_busy, section_busy, slot_by_id, room_capacity, section_day_periods, section_day_load, teacher_day_load, global_day_load)
        if result is None:
            return False
        rid, sids = result
        _commit(task, rid, sids, slot_by_id, teacher_busy, room_busy, section_busy, section_day_load, section_day_periods, teacher_day_load, global_day_load)
        row = {"offering_id": task["offering_id"], "room_id": rid, "task_id": task["task_id"]}
        if len(sids) == 1:
            row["time_slot_id"] = sids[0]
        else:
            row["time_slot_ids"] = list(sids)
        assignments.append(row)
        assigned_task_ids.add(task["task_id"])
        return True

    # Optionally shuffle task order for diversity across restarts
    ordered_tasks = list(tasks)
    if shuffle_seed is not None:
        rng = random.Random(shuffle_seed)
        rng.shuffle(ordered_tasks)

    # === PASS 1: Greedy forward pass ===
    unplaced = []
    for task in ordered_tasks:
        if time.time() - started > max_time * 0.6:
            unplaced.append(task)
            continue
        if not _try_place(task):
            unplaced.append(task)

    # === PASS 2: Retry unplaced with shuffled order ===
    if unplaced and time.time() - started < max_time * 0.8:
        still_unplaced = []
        random.shuffle(unplaced)
        for task in unplaced:
            if time.time() - started > max_time * 0.8:
                still_unplaced.append(task)
                continue
            if not _try_place(task):
                still_unplaced.append(task)
        unplaced = still_unplaced

    # === PASS 3: Swap repair — try displacing up to 2 blockers ===
    if unplaced and time.time() - started < max_time:
        still_unplaced = []
        for task in unplaced:
            if time.time() - started > max_time:
                still_unplaced.append(task)
                continue
            placed = False
            for room_id, slot_ids in domains[task["task_id"]]:
                if time.time() - started > max_time:
                    break
                t_block = _is_busy(task.get("teacher_id"), slot_ids, teacher_busy)
                r_block = _is_busy(room_id, slot_ids, room_busy)
                s_block = _is_busy(task["section_id"], slot_ids, section_busy)
                if s_block and t_block:
                    continue
                if s_block:
                    continue
                # Collect all blockers for this candidate
                blockers = []
                for sid in slot_ids:
                    if t_block and task.get("teacher_id") and (task["teacher_id"], sid) in teacher_busy:
                        for a in assignments:
                            at = task_by_id.get(a.get("task_id"))
                            if at and at.get("teacher_id") == task["teacher_id"]:
                                a_sids = tuple(a.get("time_slot_ids") or [a["time_slot_id"]])
                                if sid in a_sids:
                                    blockers.append(a)
                    if r_block and (room_id, sid) in room_busy:
                        for a in assignments:
                            if a["room_id"] == room_id:
                                a_sids = tuple(a.get("time_slot_ids") or [a["time_slot_id"]])
                                if sid in a_sids:
                                    blockers.append(a)
                seen = set()
                unique_blockers = []
                for b in blockers:
                    if b["task_id"] not in seen:
                        seen.add(b["task_id"])
                        unique_blockers.append(b)
                # Allow up to 2 blockers to be swapped
                if len(unique_blockers) < 1 or len(unique_blockers) > 2:
                    continue
                # Save blocker state and remove them
                blocker_snapshots = []
                for blocker in unique_blockers:
                    bt = task_by_id.get(blocker["task_id"])
                    if not bt:
                        break
                    b_rid = blocker["room_id"]
                    b_sids = tuple(blocker.get("time_slot_ids") or [blocker["time_slot_id"]])
                    blocker_snapshots.append((bt, b_rid, b_sids, blocker))
                if len(blocker_snapshots) != len(unique_blockers):
                    continue
                # Remove all blockers
                for bt, b_rid, b_sids, blocker in blocker_snapshots:
                    _uncommit(bt, b_rid, b_sids, slot_by_id, teacher_busy, room_busy, section_busy, section_day_load, section_day_periods, teacher_day_load, global_day_load)
                    assignments.remove(blocker)
                    assigned_task_ids.discard(blocker["task_id"])
                # Try to place our task
                if _try_place(task):
                    # Try to re-place all blockers
                    all_replaced = True
                    replaced_blockers = []
                    for bt, _, _, _ in blocker_snapshots:
                        if _try_place(bt):
                            replaced_blockers.append(bt)
                        else:
                            all_replaced = False
                            break
                    if all_replaced:
                        placed = True
                        break
                    else:
                        # Undo everything: remove our task and any replaced blockers
                        our_a = [a for a in assignments if a["task_id"] == task["task_id"]]
                        if our_a:
                            a = our_a[0]
                            a_sids = tuple(a.get("time_slot_ids") or [a["time_slot_id"]])
                            _uncommit(task, a["room_id"], a_sids, slot_by_id, teacher_busy, room_busy, section_busy, section_day_load, section_day_periods, teacher_day_load, global_day_load)
                            assignments.remove(a)
                            assigned_task_ids.discard(task["task_id"])
                        for bt in replaced_blockers:
                            rb_a = [a for a in assignments if a["task_id"] == bt["task_id"]]
                            if rb_a:
                                a = rb_a[0]
                                a_sids = tuple(a.get("time_slot_ids") or [a["time_slot_id"]])
                                _uncommit(bt, a["room_id"], a_sids, slot_by_id, teacher_busy, room_busy, section_busy, section_day_load, section_day_periods, teacher_day_load, global_day_load)
                                assignments.remove(a)
                                assigned_task_ids.discard(bt["task_id"])
                        # Restore original blockers
                        for bt, b_rid, b_sids, blocker in blocker_snapshots:
                            _commit(bt, b_rid, b_sids, slot_by_id, teacher_busy, room_busy, section_busy, section_day_load, section_day_periods, teacher_day_load, global_day_load)
                            row = {"offering_id": bt["offering_id"], "room_id": b_rid, "task_id": blocker["task_id"]}
                            if len(b_sids) == 1: row["time_slot_id"] = b_sids[0]
                            else: row["time_slot_ids"] = list(b_sids)
                            assignments.append(row)
                            assigned_task_ids.add(blocker["task_id"])
                else:
                    # Restore blockers
                    for bt, b_rid, b_sids, blocker in blocker_snapshots:
                        _commit(bt, b_rid, b_sids, slot_by_id, teacher_busy, room_busy, section_busy, section_day_load, section_day_periods, teacher_day_load, global_day_load)
                        row = {"offering_id": bt["offering_id"], "room_id": b_rid, "task_id": blocker["task_id"]}
                        if len(b_sids) == 1: row["time_slot_id"] = b_sids[0]
                        else: row["time_slot_ids"] = list(b_sids)
                        assignments.append(row)
                        assigned_task_ids.add(blocker["task_id"])
            if not placed:
                still_unplaced.append(task)
        unplaced = still_unplaced

    return assignments, assigned_task_ids, unplaced

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate(offerings, rooms, time_slots, config):
    """Generate a Mon-Fri timetable enforcing all 4 hard constraints."""
    started = time.time()
    max_time = float(config.get("MAX_GENERATION_TIME_SEC", 90))
    if not offerings:
        return {"status": "success", "assignments": [], "soft_score": 100.0, "generation_time_ms": 0,
                "hard_constraints": {"satisfied": True, "total_violations": 0, "violations": {}}}

    slot_by_id, ordered_slots, day_period_to_slot = _build_time_slot_maps(time_slots)
    if not ordered_slots:
        return {"status": "infeasible", "conflicts": ["No Monday-Friday time slots available."]}

    lab_duration = int(config.get("LAB_SESSION_DURATION", 3))
    lab_blocks = _build_blocks(day_period_to_slot, lab_duration)
    tasks, expected = _build_session_tasks(offerings, config)
    domains = _build_domains(tasks, rooms, ordered_slots, lab_blocks)
    room_capacity = {r["id"]: int(r.get("capacity", 0) or 0) for r in rooms}
    task_by_id = {t["task_id"]: t for t in tasks}

    impossible = [t for t in tasks if not domains.get(t["task_id"])]
    if impossible:
        return {"status": "infeasible", "conflicts": [
            f"No room/time domain for {impossible[0]['course_code']} ({impossible[0]['course_type']})",
            "Check that rooms, labs, and Mon-Fri time slots are loaded."]}

    # === Multi-restart: try up to MAX_RESTARTS orderings, keep best ===
    MAX_RESTARTS = 5
    best_assignments = None
    best_unplaced_count = len(tasks) + 1

    for attempt in range(MAX_RESTARTS):
        if time.time() - started > max_time * 0.95:
            break
        per_attempt_budget = max_time / MAX_RESTARTS
        attempt_start = time.time()
        seed = None if attempt == 0 else random.randint(0, 2**31)
        assignments, assigned_ids, unplaced = _solve_once(
            tasks, domains, slot_by_id, room_capacity, task_by_id,
            started=attempt_start,
            max_time=per_attempt_budget,
            shuffle_seed=seed,
        )
        if len(unplaced) < best_unplaced_count:
            best_unplaced_count = len(unplaced)
            best_assignments = assignments
        if best_unplaced_count == 0:
            break  # Perfect — all tasks placed

    assignments = best_assignments or []

    # === Final hard-constraint validation ===
    hc = _validate_hard_constraints(assignments, expected, offerings, slot_by_id)
    elapsed = int((time.time() - started) * 1000)

    # Strip internal task_id from output
    for a in assignments:
        a.pop("task_id", None)

    if not assignments:
        return {"status": "infeasible", "conflicts": ["Could not place any sessions."],
                "generation_time_ms": elapsed, "hard_constraints": hc}

    # Compute soft score
    soft_score = _compute_soft_score(assignments, offerings, rooms, ordered_slots)

    return {
        "status": "success" if hc["satisfied"] else "partial",
        "assignments": assignments,
        "soft_score": soft_score,
        "generation_time_ms": elapsed,
        "hard_constraints": hc,
        "total_tasks": len(tasks),
        "placed_tasks": len(assignments),
    }


def _compute_soft_score(assignments, offerings, rooms, time_slots):
    off_by_id = {o["id"]: o for o in offerings}
    slot_by_id = {s["id"]: s for s in time_slots if s.get("day") in DAY_ORDER}
    rcap = {r["id"]: int(r.get("capacity", 0) or 0) for r in rooms}
    sdp = defaultdict(lambda: defaultdict(set))
    tdl = defaultdict(lambda: defaultdict(int))
    sdl = defaultdict(lambda: defaultdict(int))
    p = 0.0
    for a in assignments:
        off = off_by_id.get(a["offering_id"], {})
        sids = tuple(a.get("time_slot_ids") or [a["time_slot_id"]])
        rid = a["room_id"]
        cap = rcap.get(rid, 0)
        sz = int(off.get("student_count", 0) or 0)
        if cap and cap < sz: p += (sz - cap) * 8.0
        elif cap: p += (cap - sz) * 0.04
        for sid in sids:
            sl = slot_by_id.get(sid)
            if not sl: continue
            d = sl["day"]
            sdp[off.get("section_id")][d].add(sl["period_number"])
            sdl[off.get("section_id")][d] += 1
            if off.get("teacher_id"): tdl[off["teacher_id"]][d] += 1
    for dm in sdp.values():
        for pds in dm.values():
            o = sorted(pds)
            if len(o) > 1: p += ((o[-1] - o[0] + 1) - len(o)) * 1.1
            s = _max_consecutive_streak(o)
            if s > 3: p += (s - 3) * 4.0
    for dm in tdl.values():
        vals = [dm.get(d, 0) for d in DAY_ORDER]
        avg = sum(vals) / len(DAY_ORDER)
        p += sum(abs(v - avg) for v in vals) * 0.5
    for dm in sdl.values():
        vals = [dm.get(d, 0) for d in DAY_ORDER]
        avg = sum(vals) / len(DAY_ORDER)
        p += sum(abs(v - avg) for v in vals) * 0.8
    return round(max(0.0, 100.0 - p), 2)
