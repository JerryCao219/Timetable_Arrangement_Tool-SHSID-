"""Timetable solver: band templates -> sections -> teachers -> rooms.

Model (confirmed with user):
- One base weekly template per band (36 class-hours), identical in odd and
  even weeks - this keeps odd/even (bi-weekly) classes to the minimum.
- Odd weeks add the fixed CAS double at Wed P6-P7 (38 h total).
- Even weeks fill Wed P6-P7 with a "filler" double of another subject
  (38 h total), so every subject's bi-weekly hours equal 2x its weekly
  target (e.g. Chinese: 2 h in odd weeks, 4 h in even weeks -> avg 3 h).
  The filler subject rotates across bands to keep teacher peaks low; a
  band's filler subject never meets on Wednesday in its base template.
- PE (Mon P5 + Thu P5), Optional (Wed P4) are school-wide fixed; PE/CAS/
  Optional are taught by dedicated staff (unrestricted, user decision).
- Elective blocks are grade-shared (sections formed grade-wide).
- Teacher pool for academic subjects is sized from measured parallel peaks.
- Room assignment minimises student travel (local-search swaps).

Outputs scheduler/output/timetable.json and web/data.js.
"""
import csv
import json
import math
import os
import random
from collections import defaultdict

from config import (DAYS, PERIOD_HOURS, PERIOD_TIMES, DAY_NAMES, FIXED,
                    BLOCKS, BLOCK_SUBJECTS, CLASSROOMS, DOUBLE_PAIRS,
                    MAX_CLASS_SIZE, FRIDAY_MAX_PERIOD, periods_of_day,
                    slot_hours, travel)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "output")
WEB = os.path.join(os.path.dirname(HERE), "web")

SEED = 20261024
TEMPLATE_CANDIDATES = 800
ROOM_OPT_ITERS = 40000

# ---------------------------------------------------------------------------
# 1. meeting specs (base week). Hours per block = weekly target, except the
#    band's filler block which is reduced by 1 h (the missing 2 h per 2
#    weeks are delivered as the even-week Wed P6-P7 double).
#    Every variant uses exactly 8 x 1.5h meetings + 20 x 1.0h slot-meetings
#    (28 non-fixed base slots: Wed P6/P7 are reserved for CAS/filler).
# ---------------------------------------------------------------------------
BASE_SPECS_FULL = {
    10: {"En": [1.5, 1, 1, 1, 1], "Ma": [1.5, 1, 1, 1, 1], "Ch": [1.5, 1.5],
         "SciX": [1.5, 1.5, 1], "SciY": [1.5, 1.5, 1], "Elec": [1, 1, 1, 1],
         "Hist": [1, 1, 1, 1], "PBL": ["D"], "Lang": [1]},
    9:  {"En": [1.5, 1, 1, 1, 1], "Ma": [1.5, 1, 1, 1, 1], "Ch": [1.5, 1.5],
         "Phy": [1.5, 1.5, 1], "Chem": [1.5, 1.5, 1], "Elec": [1, 1, 1, 1],
         "Hist": [1, 1, 1, 1], "ArtMus": [1, 1], "Lang": [1]},
}
# filler block -> reduced spec (1 h less); variants keep the 8/20 slot math
FILLER_REDUCED = {
    "Ch": [1, 1], "SciX": [1.5, 1.5], "SciY": [1.5, 1.5], "Phy": [1.5, 1.5],
    "Chem": [1.5, 1.5], "Elec": [1, 1, 1], "Hist": [1, 1, 1],
    "ArtMus": [1],
}
# when Ch is the filler, Hist moves to [1.5,1.5,1] to keep 8 x 1.5 meetings
# (Elec is always a full [1,1,1,1] grade-shared preset, so it must not take
# part in filler variants)
FILLER_CH_BOOST = {"Hist": [1.5, 1.5, 1]}
FILLER_ROTATION = {10: ["Ch", "Hist", "SciX", "SciY"],
                   9:  ["Ch", "Hist", "Phy", "Chem"]}

FAMILY = {"English": "En", "Math": "Ma", "Chinese": "ChLang",
          "Language": "ChLang", "Phy": "Sci", "Chem": "Sci", "Bio": "Sci",
          "History": "Hum", "Geography": "Hum", "Economy": "Hum",
          "Western Acting": "Hum", "PBL": "Hum", "Art": "Arts",
          "Music": "Arts", "Computer Science": "CS"}

# pooling families: teachers are qualified for their whole department
POOL_FAMILY = {"En": ["English"], "Ma": ["Math"],
               "ChLang": ["Chinese", "Language"],
               "Sci": ["Phy", "Chem", "Bio"],
               "Hum": ["History", "Geography", "Economy", "Western Acting",
                       "PBL"],
               "Arts": ["Art", "Music"], "CS": ["Computer Science"]}

# PE/CAS/Optional: dedicated staff, one per section (user: unrestricted)
DEDICATED = {"PE": "PE Coach", "CAS": "CAS Advisor", "Optional": "Mentor"}

RESERVED = {(3, 6), (3, 7)}   # Wed P6-P7: CAS (odd) / filler double (even)


def fixed_slots():
    occ = {}
    for block, meets in FIXED.items():
        for d, p, _par in meets:
            occ[(d, p)] = block
    for rp in RESERVED:
        occ[rp] = "CAS/filler"
    return occ


def avail_slots(size):
    occ = fixed_slots()
    out = []
    for d in DAYS:
        for p in periods_of_day(d):
            if (d, p) in occ:
                continue
            if size == 1.5 and PERIOD_HOURS[p] != 1.5:
                continue
            if size == 1 and PERIOD_HOURS[p] != 1.0:
                continue
            out.append((d, p))
    return out


def spec_for(grade, filler):
    spec = {b: list(s) for b, s in BASE_SPECS_FULL[grade].items()}
    spec[filler] = list(FILLER_REDUCED[filler])
    if filler == "Ch":
        spec.update({k: list(v) for k, v in FILLER_CH_BOOST.items()})
    return spec


def place_template(grade, filler, rng, preset=None):
    """Randomized backtracking: assign every meeting unit to a free slot.
    Rules: a block meets at most twice per day and only as a connected
    double; the filler block never meets on Wednesday; preset slots
    (grade-shared Elec) are pre-placed."""
    raw = spec_for(grade, filler)
    units = []
    for block, sizes in raw.items():
        if preset and block in preset.values():
            continue
        for s in sizes:
            units.append((block, s))
    units.sort(key=lambda u: (0 if u[1] == 1.5 else 1 if u[1] == "D" else 2,
                              rng.random()))

    grid = dict(preset or {})
    result = defaultdict(list)
    fixed = fixed_slots()
    nodes = [0]
    NODE_CAP = 20_000

    def block_periods_on(block, d):
        return [p for (dd, p), b in grid.items() if b == block and dd == d]

    def can_single(block, d, p):
        if (d, p) in grid:
            return False
        if block == filler and d == 3:
            return False
        eps = block_periods_on(block, d)
        if not eps:
            return True
        if len(eps) >= 2:
            return False
        return any((min(p, q), max(p, q)) in DOUBLE_PAIRS for q in eps)

    def bt(i):
        nodes[0] += 1
        if nodes[0] > NODE_CAP:
            return False
        if i == len(units):
            return True
        block, size = units[i]
        if size == "D":
            days = list(DAYS)
            rng.shuffle(days)
            pairs = list(DOUBLE_PAIRS)
            rng.shuffle(pairs)
            for d in days:
                if block_periods_on(block, d):
                    continue
                if block == filler and d == 3:
                    continue
                for p1, p2 in pairs:
                    if d == 5 and p2 > FRIDAY_MAX_PERIOD:
                        continue
                    if (d, p1) in grid or (d, p2) in grid:
                        continue
                    if (d, p1) in fixed or (d, p2) in fixed:
                        continue
                    if PERIOD_HOURS[p1] != 1.0 or PERIOD_HOURS[p2] != 1.0:
                        continue
                    grid[(d, p1)] = grid[(d, p2)] = block
                    result[block].append((d, p1, 1.0, True))
                    result[block].append((d, p2, 1.0, True))
                    if bt(i + 1):
                        return True
                    del grid[(d, p1)]; del grid[(d, p2)]
                    result[block] = result[block][:-2]
            return False
        cands = avail_slots(size)
        rng.shuffle(cands)
        for d, p in cands:
            if not can_single(block, d, p):
                continue
            grid[(d, p)] = block
            result[block].append((d, p, size, False))
            if bt(i + 1):
                return True
            del grid[(d, p)]
            result[block].pop()
        return False

    if not bt(0):
        return None
    out = {}
    for block, meets in result.items():
        by_day = defaultdict(list)
        for d, p, h, dbl in meets:
            by_day[d].append([d, p, h, dbl])
        final = []
        for d, lst in by_day.items():
            if len(lst) == 2:
                ps = sorted(x[1] for x in lst)
                if (ps[0], ps[1]) in DOUBLE_PAIRS:
                    for x in lst:
                        x[3] = True
            final.extend(lst)
        out[block] = [tuple(x) for x in final]
    return out


def gen_elec_slots(grade, rng, occupied=None):
    """Grade-shared elective block slots (identical for all bands of the
    grade); occupied: (day, period) slots to avoid (other grade's Elec)."""
    occupied = occupied or set()
    for _ in range(500):
        grid = {}
        used_days = set()
        placed = []
        ok = True
        units = list(BASE_SPECS_FULL[grade]["Elec"])   # full 4 h; filler
        # reduction for Elec is handled inside band templates instead
        for size in units:
            cands = [(d, p) for d, p in avail_slots(size)
                     if (d, p) not in occupied]
            rng.shuffle(cands)
            for d, p in cands:
                if (d, p) in grid or d in used_days:
                    continue
                grid[(d, p)] = "Elec"
                used_days.add(d)
                placed.append((d, p, size, False))
                break
            else:
                ok = False
                break
        if ok:
            return placed
    raise RuntimeError("cannot place grade-shared Elec slots")


# ---------------------------------------------------------------------------
# 2. section counts + load measurement + template selection
# ---------------------------------------------------------------------------
def band_grade(band):
    return 10 if str(band).startswith("10") else 9


def expected_section_counts(students):
    by_band = defaultdict(list)
    for st in students:
        by_band[st["band"]].append(st)
    counts = {}
    for band, studs in by_band.items():
        per_block = defaultdict(lambda: defaultdict(int))
        for st in studs:
            for block, (subj, lvl) in st["blocks"].items():
                if block == "Elec":
                    continue
                per_block[block][(subj, lvl)] += 1
        counts[band] = {b: {k: math.ceil(n / MAX_CLASS_SIZE)
                            for k, n in d.items()}
                        for b, d in per_block.items()}
    for grade in (9, 10):
        per = defaultdict(int)
        for st in students:
            if st["grade"] == grade:
                subj, lvl = st["blocks"]["Elec"]
                per[(subj, lvl)] += 1
        counts[f"G{grade}"] = {"Elec": {k: math.ceil(n / MAX_CLASS_SIZE)
                                        for k, n in per.items()}}
    return counts


def slot_loads(templates, counts):
    """{(day, period): (subject->n, grade->n)} for base-week meetings.
    Subject-level (not family) loads: one teacher teaches exactly one
    subject, so the per-subject parallel peak is what sizes the pools.
    templates may include key ("Elec", grade) -> meetings."""
    loads = defaultdict(lambda: (defaultdict(int), defaultdict(int)))

    def add(grade, subs, n, d, p):
        sub, gr = loads[(d, p)]
        for s, c in subs.items():
            sub[s] += c
        gr[grade] += n

    for band, block_counts in counts.items():
        if str(band).startswith("G"):
            continue
        grade = band_grade(band)
        for block, meets in FIXED.items():
            n = sum(block_counts.get(block, {}).values())
            subs = {s: n for s in BLOCK_SUBJECTS[grade][block]
                    if s not in DEDICATED}
            for d, p, _par in meets:
                add(grade, subs, n, d, p)
    for band, tpl in templates.items():
        if isinstance(band, tuple):
            grade = band[1]
            gcounts = counts[f"G{grade}"]["Elec"]
            n = sum(gcounts.values())
            subs = defaultdict(int)
            for (subj, _lvl), c in gcounts.items():
                subs[subj] += c
            for d, p, *_ in tpl:
                add(grade, subs, n, d, p)
            continue
        grade = band_grade(band)
        band_counts = counts.get(band, {})
        for block, meets in tpl.items():
            n = sum(band_counts.get(block, {}).values())
            subs = defaultdict(int)
            for (subj, _lvl), c in band_counts.get(block, {}).items():
                subs[subj] += c
            for d, p, *_ in meets:
                add(grade, subs, n, d, p)
    return loads


def template_valid(band, tpl, chosen, counts, elec):
    """Hard check: room-pool capacity per grade per slot."""
    combo = {**chosen, band: tpl}
    for g, em in elec.items():
        combo[("Elec", g)] = em
    loads = slot_loads(combo, counts)
    for (_d, _p), (_fam, gr) in loads.items():
        for g, n in gr.items():
            if n > len(CLASSROOMS[g]):
                return False
    return True


def template_score(band, tpl, chosen, counts, elec):
    """Minimise per-subject parallel peaks: squared subject loads plus a
    heavy penalty on the worst slot (the peak directly sets how many
    teachers a subject needs)."""
    combo = {**chosen, band: tpl}
    for g, em in elec.items():
        combo[("Elec", g)] = em
    loads = slot_loads(combo, counts)
    per_subject = defaultdict(int)
    sumsq = 0
    for subs, _gr in loads.values():
        for s, n in subs.items():
            sumsq += n * n
            per_subject[s] = max(per_subject[s], n)
    peak_term = sum(n * n for n in per_subject.values())
    return 4 * peak_term + sumsq


def band_load_delta(band, tpl, counts):
    """{(day,period): {subject: n}} contributed by one band template."""
    grade = band_grade(band)
    band_counts = counts.get(band, {})
    delta = defaultdict(lambda: defaultdict(int))
    for block, meets in tpl.items():
        for (subj, _lvl), c in band_counts.get(block, {}).items():
            for d, p, *_ in meets:
                delta[(d, p)][subj] += c
    return delta


def gen_templates(bands, fillers, rng, counts, elec,
                  restarts=10, keep=30, rounds=60):
    """Multi-restart greedy seed + coordinate descent over per-band template
    candidates. Objective: sum of per-subject parallel peaks (= academic
    teacher count), then squared loads. Loads are computed incrementally:
    base (FIXED + grade-shared Elec) once, each candidate's delta once."""
    # ---- base loads: school-wide FIXED + grade-shared Elec
    base_subj = defaultdict(lambda: defaultdict(int))
    base_grade = defaultdict(lambda: defaultdict(int))
    for band, block_counts in counts.items():
        if str(band).startswith("G"):
            continue
        grade = band_grade(band)
        for block, meets in FIXED.items():
            n = sum(block_counts.get(block, {}).values())
            for s in BLOCK_SUBJECTS[grade][block]:
                if s in DEDICATED:
                    continue
                for d, p, _par in meets:
                    base_subj[(d, p)][s] += n
                    base_grade[(d, p)][grade] += n
    for g, em in elec.items():
        for (subj, _lvl), c in counts[f"G{g}"]["Elec"].items():
            for d, p, *_ in em:
                base_subj[(d, p)][subj] += c
                base_grade[(d, p)][g] += c

    # ---- candidate pools (deduped), each with its load delta
    cands = {}
    for band in bands:
        grade = band_grade(band)
        filler = fillers[band]
        preset = {(d, p): "Elec" for d, p, *_ in elec[grade]}
        pool, seen = [], set()
        for _ in range(TEMPLATE_CANDIDATES):
            t = place_template(grade, filler, rng, preset)
            if t is None:
                continue
            t["Elec"] = list(elec[grade])
            key = tuple(sorted(
                (b, tuple(sorted((m[0], m[1]) for m in ms)))
                for b, ms in t.items()))
            if key in seen:
                continue
            seen.add(key)
            pool.append((t, band_load_delta(band, t, counts)))
        if not pool:
            raise RuntimeError(f"no template for band {band}")
        cands[band] = pool

    def combine(chosen):
        """chosen: band -> delta. Returns (score, peak_sum, ok_rooms)."""
        subj = defaultdict(lambda: defaultdict(int))
        gr = defaultdict(lambda: defaultdict(int))
        for slot, d in base_subj.items():
            subj[slot] = dict(d)
        for slot, d in base_grade.items():
            gr[slot] = dict(d)
        for band, val in chosen.items():
            delta = val[1] if isinstance(val, tuple) else val
            grade = band_grade(band)
            for slot, subs in delta.items():
                for s, n in subs.items():
                    subj[slot][s] = subj[slot].get(s, 0) + n
                gr[slot][grade] = gr[slot].get(grade, 0) \
                    + sum(subs.values())
        for slot, gs in gr.items():
            for g, n in gs.items():
                if n > len(CLASSROOMS[g]):
                    return None, math.inf, False
        per_subject = defaultdict(int)
        sumsq = 0
        for subs in subj.values():
            for s, n in subs.items():
                sumsq += n * n
                if n > per_subject[s]:
                    per_subject[s] = n
        peak_sum = sum(per_subject.values())
        return (1000 * peak_sum
                + 4 * sum(n * n for n in per_subject.values())
                + sumsq), peak_sum, True

    best_overall, best_peak = None, math.inf
    for restart in range(restarts):
        order = list(bands)
        rng.shuffle(order)
        chosen = {}
        for band in order:          # greedy seed in random band order
            best_c, best_sc = None, math.inf
            for t, delta in cands[band]:
                sc, _pk, ok = combine({**chosen, band: delta})
                if ok and sc < best_sc:
                    best_c, best_sc = (t, delta), sc
            if best_c is None:
                best_c = cands[band][0]
            chosen[band] = best_c
        cur, peak, _ok = combine(chosen)
        for _ in range(rounds):     # coordinate descent
            improved = False
            for band in order:
                best_c, best_sc = chosen[band], cur
                others = {k: v for k, v in chosen.items() if k != band}
                for t, delta in cands[band][:keep]:
                    if delta is best_c[1]:
                        continue
                    sc, _pk, ok = combine({**others, band: delta})
                    if ok and sc < best_sc:
                        best_c, best_sc = (t, delta), sc
                if best_c is not chosen[band]:
                    chosen[band] = best_c
                    cur = best_sc
                    improved = True
            if not improved:
                break
        _sc, peak, _ok = combine(chosen)
        print(f"  restart {restart}: teacher lower bound {peak}")
        if peak < best_peak:
            best_peak = peak
            best_overall = {b: t for b, (t, _d) in chosen.items()}
    print(f"  best teacher lower bound: {best_peak}")
    return best_overall


# ---------------------------------------------------------------------------
# 3. sections
# ---------------------------------------------------------------------------
def chunk(students):
    n = len(students)
    k = math.ceil(n / MAX_CLASS_SIZE)
    base, extra = divmod(n, k)
    out, i = [], 0
    for j in range(k):
        size = base + (1 if j < extra else 0)
        out.append(students[i:i + size])
        i += size
    return out


def build_sections(students, templates, elec, fillers):
    sections = []
    by_band = defaultdict(list)
    for st in students:
        by_band[st["band"]].append(st)
    sec_no = 0

    def add(band, grade, block, subj, lvl, ids, meetings):
        nonlocal sec_no
        for part in chunk(sorted(ids)):
            sec_no += 1
            sections.append({
                "id": f"S{sec_no:03d}", "band": band, "grade": grade,
                "block": block, "subject": subj, "level": lvl,
                "students": part, "size": len(part), "meetings": meetings,
            })

    for band, studs in sorted(by_band.items()):
        grade = band_grade(band)
        filler = fillers[band]
        for block in BLOCKS[grade]:
            if block == "Elec":
                continue
            groups = defaultdict(list)
            for st in studs:
                subj, lvl = st["blocks"][block]
                groups[(subj, lvl)].append(st["id"])
            for (subj, lvl), ids in sorted(groups.items()):
                if block == "CAS":
                    meets = [{"day": d, "period": p,
                              "hours": slot_hours(d, p), "parity": par,
                              "double": True}
                             for d, p, par in FIXED["CAS"]]
                elif block in FIXED:
                    meets = [{"day": d, "period": p,
                              "hours": slot_hours(d, p), "parity": "both",
                              "double": False}
                             for d, p, _ in FIXED[block]]
                else:
                    meets = [{"day": d, "period": p, "hours": h,
                              "parity": "both", "double": dbl}
                             for d, p, h, dbl in templates[band][block]]
                    if block == filler:
                        meets += [{"day": 3, "period": 6, "hours": 1.0,
                                   "parity": "even", "double": True},
                                  {"day": 3, "period": 7, "hours": 1.0,
                                   "parity": "even", "double": True}]
                add(band, grade, block, subj, lvl, ids, meets)

    for grade in (9, 10):
        groups = defaultdict(list)
        for st in students:
            if st["grade"] == grade:
                subj, lvl = st["blocks"]["Elec"]
                groups[(subj, lvl)].append(st["id"])
        meets = [{"day": d, "period": p, "hours": h, "parity": "both",
                  "double": dbl} for d, p, h, dbl in elec[grade]]
        for (subj, lvl), ids in sorted(groups.items()):
            add(f"G{grade}", grade, "Elec", subj, lvl, ids, meets)
    return sections


# ---------------------------------------------------------------------------
# 4b. real-data mode: if data/students_real.json / data/teachers_real.csv
#     exist they replace the synthetic inputs. Teachers CSV layout matches
#     data/teachers.csv: columns "name,subjects" with subjects separated by
#     ";". One teacher still teaches exactly ONE subject: the first listed
#     subject is their main (and only) assignment pool.
# ---------------------------------------------------------------------------
REAL_STUDENTS = os.path.join(DATA, "students_real.json")
REAL_TEACHERS = os.path.join(DATA, "teachers_real.csv")

LEVEL_RANK = {"S": 0.0, "S+": 0.5, "H": 1.0, "AP": 2.0, "AP1": 1.5,
              "AP2": 2.0}


def load_real_students():
    """Load students_real.json; auto-assign ability-sorted bands if the
    band field is missing."""
    students = json.load(open(REAL_STUDENTS, encoding="utf-8"))
    if all(st.get("band") for st in students):
        return students
    per_grade = defaultdict(list)
    for st in students:
        per_grade[st["grade"]].append(st)
    for g, studs in per_grade.items():
        def ability(st):
            vals = [LEVEL_RANK.get(l, 0.5) for _s, l in
                    st["blocks"].values() if l]
            return sum(vals) / max(len(vals), 1)
        studs.sort(key=lambda s: (-ability(s), s.get("id", "")))
        n = len(studs)
        size = max(n // 4, 1)
        for i, st in enumerate(studs):
            st["band"] = f"{g}{'ABCD'[min(i // size, 3)]}"
    return students


def load_real_teachers():
    teachers = []
    with open(REAL_TEACHERS, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            subs = [s.strip() for s in row["subjects"].split(";")
                    if s.strip()]
            if not subs:
                continue
            teachers.append({"id": f"T{i:03d}", "name": row["name"].strip(),
                             "main": subs[0], "subjects": [subs[0]]})
    return teachers


def assign_fixed_teachers(sections, teachers, rng):
    """Assign from a FIXED real roster: per subject, no auto-slack. If a
    subject is short-staffed, report exactly how many more are needed."""
    by_subj = defaultdict(list)
    for sec in sections:
        by_subj[sec["subject"]].append(sec)
    daily_all, total_all = {}, {}
    for subj in sorted(by_subj):
        if subj in DEDICATED:
            continue                       # dedicated staff handled later
        pool = [t for t in teachers if t["main"] == subj]
        extra = 0
        while True:
            ghosts = pool + [{"id": f"GHOST{i}", "name": f"extra {i}",
                              "main": subj, "subjects": [subj]}
                             for i in range(extra)]
            try:
                daily, total = _assign_family(subj, by_subj[subj], ghosts,
                                              random.Random(rng.random()))
                if extra:
                    raise RuntimeError(
                        f"subject '{subj}' is short-staffed: {len(pool)} "
                        f"teacher(s) provided, but the schedule needs at "
                        f"least {len(pool) + extra}. Add {extra} more "
                        f"'{subj}' teacher(s) to teachers_real.csv and "
                        f"re-run.")
                daily_all.update(daily)
                total_all.update(total)
                break
            except RuntimeError as e:
                if "short-staffed" in str(e):
                    raise
                extra += 1
                if extra > 30:
                    raise RuntimeError(
                        f"subject '{subj}' cannot be staffed even with 30 "
                        f"extra teachers - check course rules.")
    return {"weeklyHours": {tid: round(t / 2, 2)
                            for tid, t in total_all.items()},
            "daily": {tid: {pp: {str(d): daily_all[tid][pp].get(d, 0)
                                 for d in DAYS}
                            for pp in ("odd", "even")}
                      for tid in daily_all}}


def _subject_peak(secs):
    at = defaultdict(int)
    for sec in secs:
        for m in sec["meetings"]:
            pars = ("odd", "even") if m["parity"] == "both" \
                else (m["parity"],)
            for pp in pars:
                at[(pp, m["day"], m["period"])] += 1
    return max(at.values()) if at else 0

# ---------------------------------------------------------------------------
# 4. teachers: ONE subject per teacher (hard rule). Per-subject pools sized
#    from measured parallel peaks; dedicated PE/CAS/Optional staff on top.
# ---------------------------------------------------------------------------
TARGET_ACADEMIC_TEACHERS = 105


def make_teachers(sections, rng):
    from gen_data import FIRST, LAST
    sat = defaultdict(lambda: defaultdict(int))
    for sec in sections:
        if sec["subject"] in DEDICATED:
            continue
        for m in sec["meetings"]:
            pars = ("odd", "even") if m["parity"] == "both" \
                else (m["parity"],)
            for pp in pars:
                sat[(pp, m["day"], m["period"])][sec["subject"]] += 1
    peak = defaultdict(int)
    for subs in sat.values():
        for s, n in subs.items():
            peak[s] = max(peak[s], n)

    teachers = []
    used = set()
    i = 0
    for s in sorted(peak):
        for _ in range(peak[s]):
            i += 1
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if name in used:
                name = f"{name} {i}"
            used.add(name)
            teachers.append({"id": f"T{i:03d}", "name": name,
                             "main": s, "subjects": [s]})
    return teachers, dict(peak)


def add_teacher(teachers, subject, rng):
    """Append one teacher who teaches exactly `subject`."""
    from gen_data import FIRST, LAST
    used = {t["name"] for t in teachers}
    n = max(int(t["id"][1:]) for t in teachers) + 1
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    while name in used:
        n += 1
        name = f"{name} {n}"
    used.add(name)
    teachers.append({"id": f"T{n:03d}", "name": name,
                     "main": subject, "subjects": [subject]})


def make_dedicated_teachers(sections, start_idx):
    teachers = []
    i = start_idx
    counters = defaultdict(int)
    for sec in sections:
        subj = sec["subject"]
        if subj not in DEDICATED:
            continue
        counters[subj] += 1
        i += 1
        t = {"id": f"T{i:03d}", "name": f"{DEDICATED[subj]} {counters[subj]}",
             "main": subj, "subjects": [subj]}
        teachers.append(t)
        sec["teacher"] = t["id"]
    return teachers


def _meetings_of(sec):
    for m in sec["meetings"]:
        pars = ("odd", "even") if m["parity"] == "both" else (m["parity"],)
        for pp in pars:
            yield pp, m["day"], m["period"], m["hours"]


def _assign_family(fam, fam_secs, pool, rng, attempts=12):
    """Pattern-group assignment of one subject's sections to its own teacher
    pool (one subject per teacher). Sections sharing an identical meeting
    pattern must receive distinct teachers; a teacher may serve several
    groups only if their slot sets are disjoint. Group-level backtracking
    with randomised restarts; returns (daily, total) keyed by teacher id."""
    from itertools import combinations
    by_pattern = defaultdict(list)
    for sec in fam_secs:
        key = frozenset((pp, d, p) for pp, d, p, _h in _meetings_of(sec))
        by_pattern[key].append(sec)
    groups = [(slots, secs) for slots, secs in by_pattern.items()]
    hours_of = {}
    for slots, secs in groups:
        hours = defaultdict(float)
        for m in secs[0]["meetings"]:
            pars = ("odd", "even") if m["parity"] == "both" \
                else (m["parity"],)
            for pp in pars:
                hours[(pp, m["day"])] += m["hours"]
        hours_of[slots] = hours

    for _ in range(attempts):
        busy = {t["id"]: set() for t in pool}
        daily = {t["id"]: {"odd": defaultdict(float),
                           "even": defaultdict(float)} for t in pool}
        total = {t["id"]: 0.0 for t in pool}
        nodes = [0]

        def bal(tid, hours):
            tmp = {pp: dict(daily[tid][pp]) for pp in ("odd", "even")}
            for (pp, d), h in hours.items():
                tmp[pp][d] = tmp[pp].get(d, 0) + h
            var = 0.0
            for pp in ("odd", "even"):
                vals = [tmp[pp].get(d, 0) for d in DAYS]
                mean = sum(vals) / 5
                var += sum((v - mean) ** 2 for v in vals)
            return (round(var, 3), total[tid])

        def bt(gi):
            nodes[0] += 1
            if nodes[0] > 40_000:
                return False
            if gi == len(groups):
                return True
            # MRV over remaining groups: fewest free teachers first
            best_j, best_free = None, None
            for j in range(gi, len(groups)):
                slots, secs = groups[j]
                free = [t for t in pool if not (slots & busy[t["id"]])]
                if best_free is None or len(free) < len(best_free):
                    best_j, best_free = j, free
                    if len(free) < len(secs):
                        break
            groups[gi], groups[best_j] = groups[best_j], groups[gi]
            slots, secs = groups[gi]
            k = len(secs)
            hours = hours_of[slots]
            free = sorted(best_free, key=lambda t: bal(t["id"], hours))
            shortlist = free[:min(len(free), k + 3)]
            combos = list(combinations(shortlist, k))
            combos.sort(key=lambda cb: sum(total[t["id"]] for t in cb)
                        + rng.random())
            for cb in combos[:12]:
                for t, sec in zip(cb, secs):
                    busy[t["id"]] |= slots
                    for (pp, d), h in hours.items():
                        daily[t["id"]][pp][d] += h
                        total[t["id"]] += h
                    sec["teacher"] = t["id"]
                if bt(gi + 1):
                    return True
                for t, sec in zip(cb, secs):
                    busy[t["id"]] -= slots
                    for (pp, d), h in hours.items():
                        daily[t["id"]][pp][d] -= h
                        total[t["id"]] -= h
                    del sec["teacher"]
            groups[gi], groups[best_j] = groups[best_j], groups[gi]
            return False

        if bt(0):
            return daily, total
        for sec in fam_secs:
            sec.pop("teacher", None)
    raise RuntimeError(f"no teacher assignment for subject {fam}")


def assign_with_autoslack(sections, teachers, rng, max_extra=30,
                          pad_to=TARGET_ACADEMIC_TEACHERS):
    """Assign academic teachers subject by subject (one subject per
    teacher); when a subject pool proves infeasible, add one teacher to
    that subject and retry. Afterwards the pool is padded up to
    TARGET_ACADEMIC_TEACHERS by repeatedly adding a teacher to the most
    loaded subject and re-balancing it."""
    by_subj = defaultdict(list)
    for sec in sections:
        if sec["subject"] not in DEDICATED:
            by_subj[sec["subject"]].append(sec)
    daily_all, total_all = {}, {}

    def assign_subject(subj):
        pool = [t for t in teachers if t["main"] == subj]
        for t in pool:                     # drop stale stats on re-run
            daily_all.pop(t["id"], None)
            total_all.pop(t["id"], None)
        daily, total = _assign_family(subj, by_subj[subj], pool,
                                      random.Random(rng.random()))
        daily_all.update(daily)
        total_all.update(total)

    for subj in sorted(by_subj):
        extra = 0
        while True:
            try:
                assign_subject(subj)
                break
            except RuntimeError:
                extra += 1
                if extra > max_extra:
                    raise RuntimeError(f"subject {subj} infeasible")
                add_teacher(teachers, subj, rng)
                print(f"  +1 teacher for {subj}")

    # pad up to the target staff size: most-loaded subject first
    while len(teachers) < pad_to:
        loads = defaultdict(list)
        for t in teachers:
            if t["main"] in by_subj:
                loads[t["main"]].append(total_all.get(t["id"], 0))
        subj = max(loads, key=lambda s: sum(loads[s]) / len(loads[s]))
        add_teacher(teachers, subj, rng)
        assign_subject(subj)
        print(f"  +1 teacher for {subj} (padding to target)")

    return {"weeklyHours": {tid: round(t / 2, 2)
                            for tid, t in total_all.items()},
            "daily": {tid: {pp: {str(d): daily_all[tid][pp].get(d, 0)
                                 for d in DAYS}
                            for pp in ("odd", "even")}
                      for tid in daily_all}}


# ---------------------------------------------------------------------------
# 5. rooms + distance optimisation
# ---------------------------------------------------------------------------
CHAIN_PAIRS = [(1, 2), (2, 3), (3, 4), (5, 6), (6, 7)]  # P4->P5 lunch excluded


def build_student_slot_map(sections, room_of):
    slot_room = {}
    for sec in sections:
        for m in sec["meetings"]:
            pars = ("odd", "even") if m["parity"] == "both" else (m["parity"],)
            for pp in pars:
                room = room_of[(sec["id"], pp, m["day"], m["period"])]
                for sid in sec["students"]:
                    slot_room[(sid, pp, m["day"], m["period"])] = room
    return slot_room


def student_total_cost(slot_room, sid):
    cost = 0
    for pp in ("odd", "even"):
        for d in DAYS:
            for a, b in CHAIN_PAIRS:
                ra = slot_room.get((sid, pp, d, a))
                rb = slot_room.get((sid, pp, d, b))
                if ra is not None and rb is not None:
                    cost += travel(ra, rb)
    return cost


def assign_rooms(sections, rng):
    at = defaultdict(list)
    sec_by_id = {s["id"]: s for s in sections}
    for sec in sections:
        for m in sec["meetings"]:
            pars = ("odd", "even") if m["parity"] == "both" else (m["parity"],)
            for pp in pars:
                at[(pp, m["day"], m["period"])].append(sec["id"])
    room_of = {}
    for (pp, d, p), sec_ids in at.items():
        used = set()
        for sec_id in sec_ids:
            pool = [r for r in CLASSROOMS[sec_by_id[sec_id]["grade"]]
                    if r not in used]
            if not pool:
                raise RuntimeError(f"room shortage at {pp} d{d} p{p}")
            room = rng.choice(pool)
            used.add(room)
            room_of[(sec_id, pp, d, p)] = room
    return room_of, at


def optimize_rooms(sections, students, room_of, at, rng,
                   iters=ROOM_OPT_ITERS):
    sec_by_id = {s["id"]: s for s in sections}
    slot_room = build_student_slot_map(sections, room_of)
    student_cost = {st["id"]: student_total_cost(slot_room, st["id"])
                    for st in students}
    cur = sum(student_cost.values())
    baseline = cur

    def delta_for(sid, pp, d, p, new_room):
        old_room = slot_room[(sid, pp, d, p)]
        if old_room == new_room:
            return 0
        delta = 0
        for q in (p - 1, p + 1):
            if (min(p, q), max(p, q)) not in CHAIN_PAIRS:
                continue
            rq = slot_room.get((sid, pp, d, q))
            if rq is None:
                continue
            delta += travel(new_room, rq) - travel(old_room, rq)
        return delta

    keys = [k for k, v in at.items() if len(v) >= 2]
    for _ in range(iters):
        pp, d, p = keys[rng.randrange(len(keys))]
        sa, sb = rng.sample(at[(pp, d, p)], 2)
        if sec_by_id[sa]["grade"] != sec_by_id[sb]["grade"]:
            continue
        ra = room_of[(sa, pp, d, p)]
        rb = room_of[(sb, pp, d, p)]
        if ra == rb:
            continue
        delta = 0
        for sid in sec_by_id[sa]["students"]:
            delta += delta_for(sid, pp, d, p, rb)
        for sid in sec_by_id[sb]["students"]:
            delta += delta_for(sid, pp, d, p, ra)
        if delta <= 0:
            room_of[(sa, pp, d, p)], room_of[(sb, pp, d, p)] = rb, ra
            for sid in sec_by_id[sa]["students"]:
                slot_room[(sid, pp, d, p)] = rb
            for sid in sec_by_id[sb]["students"]:
                slot_room[(sid, pp, d, p)] = ra
            cur += delta
    return room_of, baseline, cur


# ---------------------------------------------------------------------------
# 6. export
# ---------------------------------------------------------------------------
def pick_examples(students, teachers, teacher_stats):
    """20 featured timetables for the demo: 12 students spanning both
    grades, every elective, science pair and a spread of levels; 8 teachers
    spanning distinct subject families."""
    full = {s["id"]: s for s in
            json.load(open(os.path.join(DATA, "students.json"),
                           encoding="utf-8"))}
    examples = []
    seen = set()

    def add_student(st, why):
        if st["id"] in seen:
            return
        seen.add(st["id"])
        blocks = full[st["id"]]["blocks"]
        elec, elvl = blocks["Elec"]
        _ma, mlvl = blocks["Ma"]
        _en, enlvl = blocks["En"]
        examples.append({
            "kind": "student", "id": st["id"], "name": st["name"],
            "label": f"G{st['grade']} · {elec} {elvl} · "
                     f"Math {mlvl} · English {enlvl}",
            "why": why})

    # G10: one student per elective, diverse levels/science pairs
    for elec in ["Computer Science", "Economy", "Art", "Music",
                 "Geography", "Western Acting"]:
        cands = [s for s in students
                 if s["grade"] == 10
                 and full[s["id"]]["blocks"]["Elec"][0] == elec]
        cands.sort(key=lambda s: (full[s["id"]]["blocks"]["Ma"][1],
                                  full[s["id"]]["blocks"].get("SciX",
                                                              ("",))[0],
                                  s["id"]))
        if cands:
            add_student(cands[0], f"Grade 10 · {elec} elective")
    # G9: one student per elective x art/music, diverse levels
    for elec in ["Computer Science", "Bio", "Geography"]:
        for am in ["Art", "Music"]:
            cands = [s for s in students
                     if s["grade"] == 9
                     and full[s["id"]]["blocks"]["Elec"][0] == elec
                     and full[s["id"]]["blocks"]["ArtMus"][0] == am]
            cands.sort(key=lambda s: (full[s["id"]]["blocks"]["Ma"][1],
                                      s["id"]))
            if cands:
                add_student(cands[0], f"Grade 9 · {elec} + {am}")

    wanted_mains = ["English", "Math", "Chinese", "Phy", "Chem", "Bio",
                    "History", "Economy", "Computer Science", "Art"]
    for main in wanted_mains:
        cands = [t for t in teachers if t["main"] == main]
        if not cands:
            continue
        cands.sort(key=lambda t: -teacher_stats["weeklyHours"].get(t["id"],
                                                                   0))
        t = cands[0]
        examples.append({
            "kind": "teacher", "id": t["id"], "name": t["name"],
            "label": f"{main} · "
                     f"{teacher_stats['weeklyHours'].get(t['id'], 0)} h/wk",
            "why": f"{main} teacher"})
        if len(examples) >= 20:
            break
    return examples[:20]


def export(sections, students, teachers, room_of, teacher_stats, metrics,
           fillers):
    sec_out = []
    for sec in sections:
        meets = []
        for m in sec["meetings"]:
            pars = ("odd", "even") if m["parity"] == "both" \
                else (m["parity"],)
            for pp in pars:
                meets.append({"week": pp, "day": m["day"],
                              "period": m["period"],
                              "room": room_of[(sec["id"], pp, m["day"],
                                               m["period"])],
                              "double": m["double"]})
        sec_out.append({"id": sec["id"], "band": sec["band"],
                        "grade": sec["grade"], "block": sec["block"],
                        "subject": sec["subject"], "level": sec["level"],
                        "teacher": sec["teacher"], "size": sec["size"],
                        "students": sec["students"], "meetings": meets})
    data = {
        "meta": {"students": len(students), "teachers": len(teachers),
                 "sections": len(sections),
                 "generated": "HackSHSID 2026 Track 1"},
        "periodTimes": {str(k): v for k, v in PERIOD_TIMES.items()},
        "periodHours": {str(k): v for k, v in PERIOD_HOURS.items()},
        "dayNames": {str(k): v for k, v in DAY_NAMES.items()},
        "fillers": fillers,
        "students": [{"id": s["id"], "name": s["name"], "grade": s["grade"],
                      "band": s["band"]} for s in students],
        "teachers": teachers,
        "sections": sec_out,
        "teacherStats": teacher_stats,
        "metrics": metrics,
        "examples": pick_examples(students, teachers, teacher_stats),
    }
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(WEB, exist_ok=True)
    with open(os.path.join(OUT, "timetable.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    with open(os.path.join(WEB, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.DATA = ")
        json.dump(data, f, ensure_ascii=False)
        f.write(";\n")


# ---------------------------------------------------------------------------
def solve():
    rng = random.Random(SEED)
    if os.path.exists(REAL_STUDENTS):
        print("REAL student list detected:", REAL_STUDENTS)
        students = load_real_students()
    else:
        students = json.load(open(os.path.join(DATA, "students.json"),
                                  encoding="utf-8"))
    bands = sorted({s["band"] for s in students})
    fillers = {}
    for band in bands:
        g = band_grade(band)
        idx = "ABCDEF".index(band[-1]) % len(FILLER_ROTATION[g])
        fillers[band] = FILLER_ROTATION[g][idx]
    print("bands:", bands, "fillers:", fillers)
    counts = expected_section_counts(students)

    print("generating grade-shared elective slots ...")
    elec = {10: gen_elec_slots(10, rng)}
    elec[9] = gen_elec_slots(9, rng, occupied={(d, p) for d, p, *_ in elec[10]})

    print("generating templates ...")
    templates = gen_templates(bands, fillers, rng, counts, elec)

    print("building sections ...")
    sections = build_sections(students, templates, elec, fillers)
    print(f"sections: {len(sections)}")

    real_mode = os.path.exists(REAL_TEACHERS)
    if real_mode:
        print("REAL teacher roster detected:", REAL_TEACHERS)
        teachers = load_real_teachers()
        print(f"real roster: {len(teachers)} academic teachers")
        tstats = assign_fixed_teachers(sections, teachers, rng)
    else:
        print("sizing teacher pool from measured peaks ...")
        teachers, peaks = make_teachers(sections, rng)
        print(f"initial academic pool: {len(teachers)}; peaks: {peaks}")
        print("assigning teachers (auto-slack on infeasible subjects) ...")
        # padding to 105 only makes sense for the full synthetic cohort
        pad_to = 0 if os.path.exists(REAL_STUDENTS) \
            else TARGET_ACADEMIC_TEACHERS
        tstats = assign_with_autoslack(sections, teachers, rng,
                                       pad_to=pad_to)
    n_academic = len(teachers)
    max_id = max(int(t["id"][1:]) for t in teachers)
    teachers += make_dedicated_teachers(sections, max_id)
    print(f"teachers: {n_academic} academic + "
          f"{len(teachers) - n_academic} dedicated (PE/CAS/Optional)")
    with open(os.path.join(DATA, "teachers.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "subjects"])
        for t in teachers:
            w.writerow([t["name"], ";".join(t["subjects"])])

    print("assigning rooms ...")
    room_of, at = assign_rooms(sections, rng)

    print("optimising room assignment for travel distance ...")
    room_of, baseline, optimised = optimize_rooms(sections, students,
                                                  room_of, at, rng)
    odd_even = sum(1 for s in sections
                   if any(m["parity"] != "both" for m in s["meetings"]))
    metrics = {"travelBaseline": baseline, "travelOptimised": optimised,
               "travelSaved": baseline - optimised,
               "travelSavingPct": round(100 * (baseline - optimised)
                                        / max(baseline, 1), 1),
               "oddEvenSections": odd_even,
               "academicTeachers": n_academic,
               "dedicatedTeachers": len(teachers) - n_academic,
               "teacherPeaks": peaks if not real_mode else "real roster"}
    print("metrics:", metrics)

    export(sections, students, teachers, room_of, tstats, metrics, fillers)
    print("exported scheduler/output/timetable.json and web/data.js")


if __name__ == "__main__":
    solve()
