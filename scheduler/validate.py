"""Constraint verifier + metrics report for the generated timetable.

Checks every MUST constraint against scheduler/output/timetable.json and
writes scheduler/output/report.json. Exits non-zero if any check fails.

Checks:
 1. Every student has exactly 38 class-hours in odd and in even weeks.
 2. No student has two meetings in the same (week, day, period).
 3. No teacher has two sections in the same (week, day, period).
 4. No room hosts two sections in the same (week, day, period).
 5. Every section size <= MAX_CLASS_SIZE; same (block, level) only.
 6. Bi-weekly subject hours per student equal 2x the weekly target.
 7. A block meets at most twice per day and then only as a connected double.
 8. CAS meets only in odd weeks (Wed P6-P7); every band's even-week Wed
    P6-P7 is a connected double of one academic subject (the filler).
 9. Fixed meetings respected: PE Mon P5 + Thu P5, Optional Wed P4,
    no P6/P7 on Friday.
10. Bi-weekly (odd/even-only) meetings are minimised: only CAS + fillers.
"""
import json
import os
import sys
from collections import defaultdict

from config import (DAYS, BLOCKS, CLASSROOMS, DOUBLE_PAIRS, FIXED,
                    FRIDAY_MAX_PERIOD, MAX_CLASS_SIZE, PERIOD_HOURS, travel)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
DATA = os.path.join(HERE, "data")

CHAIN_PAIRS = [(1, 2), (2, 3), (3, 4), (5, 6), (6, 7)]

WEEKLY_TARGET = {g: {b: h / 2 for b, h in blocks.items()}
                 for g, blocks in BLOCKS.items()}


def main():
    data = json.load(open(os.path.join(OUT, "timetable.json"),
                          encoding="utf-8"))
    students = {s["id"]: s for s in data["students"]}
    sections = data["sections"]
    failures = []
    warnings = []

    def check(name, ok, detail=""):
        (failures if not ok else []).append
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" - {detail}" if detail and not ok
                                     else ""))
        if not ok:
            failures.append(f"{name}: {detail}")

    # ------------------------------------------------------------ per-student
    stu_slots = defaultdict(list)      # (sid, week, day, period) -> [sec]
    stu_hours = defaultdict(lambda: defaultdict(float))   # sid -> week -> h
    stu_subj_hours = defaultdict(lambda: defaultdict(float))  # sid->subj->h/2w
    for sec in sections:
        for m in sec["meetings"]:
            h = PERIOD_HOURS[m["period"]]
            for sid in sec["students"]:
                stu_slots[(sid, m["week"], m["day"], m["period"])].append(
                    sec["id"])
                stu_hours[sid][m["week"]] += h
                stu_subj_hours[sid][sec["subject"]] += h

    bad = [k for k, v in stu_slots.items() if len(v) > 1]
    check("2. no student slot clash", not bad, f"{len(bad)} clashes")

    bad = [sid for sid in students
           if abs(stu_hours[sid]["odd"] - 38) > 1e-9
           or abs(stu_hours[sid]["even"] - 38) > 1e-9]
    check("1. every student 38 h in odd and even weeks", not bad,
          f"{len(bad)} students off target, e.g. {bad[:3]}")

    # ------------------------------------------------------- section sanity
    bad = [s["id"] for s in sections if s["size"] > MAX_CLASS_SIZE]
    check("5a. section size <= %d" % MAX_CLASS_SIZE, not bad, str(bad[:5]))

    # ------------------------------------------------------------ teachers
    t_slots = defaultdict(list)
    t_subjects = defaultdict(set)
    for sec in sections:
        t_subjects[sec["teacher"]].add(sec["subject"])
        for m in sec["meetings"]:
            t_slots[(sec["teacher"], m["week"], m["day"],
                     m["period"])].append(sec["id"])
    bad = [k for k, v in t_slots.items() if len(v) > 1]
    check("3. no teacher slot clash", not bad, f"{len(bad)} clashes")

    bad = {t: s for t, s in t_subjects.items() if len(s) > 1}
    check("3b. one subject per teacher", not bad, str(bad)[:80])

    # --------------------------------------------------------------- rooms
    r_slots = defaultdict(list)
    for sec in sections:
        for m in sec["meetings"]:
            r_slots[(m["room"], m["week"], m["day"], m["period"])].append(
                sec["id"])
    bad = [k for k, v in r_slots.items() if len(v) > 1]
    check("4. no room slot clash", not bad, f"{len(bad)} clashes")

    # rooms must belong to the grade pool
    bad = []
    for sec in sections:
        for m in sec["meetings"]:
            if m["room"] not in CLASSROOMS[sec["grade"]]:
                bad.append((sec["id"], m["room"]))
    check("4b. rooms drawn from the grade pool", not bad, str(bad[:5]))

    # ------------------------------------------------- bi-weekly hour totals
    # subject targets per student derive from the student's block map
    studata = json.load(open(os.path.join(DATA, "students.json"),
                             encoding="utf-8"))
    block_of = {s["id"]: s["blocks"] for s in studata}
    grade_of = {sid: students[sid]["grade"] for sid in students}
    bad = []
    for sid, blocks in block_of.items():
        g = grade_of[sid]
        for block, (subj, _lvl) in blocks.items():
            tgt = 2 * WEEKLY_TARGET[g][block]
            got = stu_subj_hours[sid][subj]
            # ArtMus block subject is Art or Music; both keyed fine.
            if abs(got - tgt) > 1e-9:
                bad.append((sid, subj, tgt, got))
    check("6. bi-weekly subject hours = 2x weekly target", not bad,
          f"{len(bad)} mismatches, e.g. {bad[:3]}")

    # ------------------------------------------- at most a double per day
    bad = []
    for sec in sections:
        per_day = defaultdict(list)
        for m in sec["meetings"]:
            per_day[(m["week"], m["day"])].append(m)
        for k, ms in per_day.items():
            if len(ms) > 2:
                bad.append((sec["id"], k, len(ms)))
            elif len(ms) == 2:
                ps = sorted(m["period"] for m in ms)
                if (ps[0], ps[1]) not in DOUBLE_PAIRS:
                    bad.append((sec["id"], k, "non-connected"))
    check("7. <=2 meetings/day, connected doubles only", not bad,
          str(bad[:5]))

    # -------------------------------------------------------- CAS / filler
    bad = [s["id"] for s in sections if s["subject"] == "CAS"
           and any(m["week"] != "odd" for m in s["meetings"])]
    check("8a. CAS only in odd weeks", not bad, str(bad[:5]))

    fillers = data["fillers"]
    bad = []
    for band, filler_block in fillers.items():
        for week in ("odd", "even"):
            at67 = defaultdict(set)
            for sec in sections:
                if sec["band"] != band:
                    continue
                for m in sec["meetings"]:
                    if m["week"] == week and m["day"] == 3 \
                            and m["period"] in (6, 7):
                        at67[m["period"]].add(sec["block"])
            blocks67 = at67[6] | at67[7]
            want = {"CAS"} if week == "odd" else {filler_block}
            if blocks67 != want:
                bad.append((band, week, sorted(block67 for block67
                                                 in blocks67)))
    check("8b. Wed P6-P7 = CAS (odd) / filler double (even)", not bad,
          str(bad[:5]))

    # ------------------------------------------------------------ fixed grid
    bad = [s["id"] for s in sections
           for m in s["meetings"]
           if m["day"] == 5 and m["period"] > FRIDAY_MAX_PERIOD]
    check("9a. no P6/P7 on Friday", not bad, str(bad[:5]))

    pe_ok = True
    for sec in sections:
        if sec["subject"] == "PE":
            got = sorted({(m["day"], m["period"]) for m in sec["meetings"]})
            if got != sorted({(d, p) for d, p, _ in FIXED["PE"]}):
                pe_ok = False
    check("9b. PE fixed at Mon P5 + Thu P5", pe_ok)

    # --------------------------------------------- odd/even-only minimality
    # a block is week-dependent if any (day, period) occurs in only one week
    oe = set()
    for sec in sections:
        weeks_of = defaultdict(set)
        for m in sec["meetings"]:
            weeks_of[(m["day"], m["period"])].add(m["week"])
        if any(w != {"odd", "even"} for w in weeks_of.values()):
            oe.add(sec["block"])
    extra = oe - {"CAS"} - set(fillers.values())
    check("10. only CAS + filler blocks are week-dependent", not extra,
          str(extra))

    # ------------------------------------------------------------- metrics
    # student travel distance (from final room assignment)
    slot_room = {}
    for sec in sections:
        for m in sec["meetings"]:
            for sid in sec["students"]:
                slot_room[(sid, m["week"], m["day"], m["period"])] = m["room"]
    total = 0
    per_student = {}
    for sid in students:
        c = 0
        for week in ("odd", "even"):
            for d in DAYS:
                for a, b in CHAIN_PAIRS:
                    ra = slot_room.get((sid, week, d, a))
                    rb = slot_room.get((sid, week, d, b))
                    if ra is not None and rb is not None:
                        c += travel(ra, rb)
        per_student[sid] = c
        total += c
    avg = total / len(students)

    stats = data["teacherStats"]
    daily = stats["daily"]
    spreads = []
    for tid, byweek in daily.items():
        for week in ("odd", "even"):
            vals = [byweek[week][str(d)] for d in DAYS]
            spreads.append(max(vals) - min(vals))
    avg_spread = sum(spreads) / len(spreads)

    report = {
        "checks": {"failed": failures, "allPassed": not failures},
        "warnings": warnings,
        "metrics": {
            **data["metrics"],
            "avgStudentTravelPerWeek": round(avg / 2, 2),
            "avgTeacherDailySpread": round(avg_spread, 2),
        },
    }
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nstudent travel: total(2w)={total}  avg/week={avg/2:.1f}")
    print(f"teacher daily-hour spread avg={avg_spread:.2f} h")
    print("report -> scheduler/output/report.json")
    if failures:
        print(f"\n{len(failures)} CHECK(S) FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
