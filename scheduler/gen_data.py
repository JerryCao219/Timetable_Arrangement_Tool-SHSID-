"""Synthetic data generator (seeded, reproducible).

Scale (confirmed): 300 students per grade (600 total), 105 academic
teachers (one subject each) + dedicated PE/CAS/Optional staff.
Students have individual course choices (no fixed administrative class);
they are ability-sorted into scheduling bands (75/band, 4 bands per grade)
so each band hosts a narrow level range (fewer parallel sections).

Outputs: data/students.csv, data/teachers.csv (requirement-doc layout) and
JSON sidecars consumed by the solver.
"""
import csv
import json
import os
import random
from collections import defaultdict

from config import (SUBJECT_LEVELS, G10_ELECTIVES, G9_ELECTIVES, G10_SCIENCES)

SEED = 20261024
STUDENTS_PER_GRADE = 300
BANDS_PER_GRADE = 4

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

FIRST = ["Alex", "Brian", "Cindy", "David", "Emma", "Frank", "Grace", "Henry",
         "Ivy", "Jack", "Karen", "Leo", "Mia", "Nick", "Olivia", "Peter",
         "Queenie", "Ryan", "Sophia", "Tom", "Uma", "Victor", "Wendy",
         "Xander", "Yuki", "Zoe", "Aaron", "Bella", "Chris", "Dora", "Ethan",
         "Fiona", "George", "Hannah", "Ivan", "Julia", "Kevin", "Lily"]
LAST = ["Wang", "Li", "Zhang", "Chen", "Liu", "Yang", "Huang", "Zhao", "Wu",
        "Zhou", "Xu", "Sun", "Ma", "Zhu", "Hu", "Guo", "Lin", "He", "Gao", "Luo"]

# popularity weights
ELEC10_W = [("Computer Science", .25), ("Economy", .20), ("Art", .15),
            ("Geography", .15), ("Western Acting", .15), ("Music", .10)]
ELEC9_W = [("Computer Science", .40), ("Bio", .35), ("Geography", .25)]
ARTMUS_W = [("Art", .55), ("Music", .45)]

# teacher main subjects (60 total); secondary qualifications added later.
TEACHER_MAINS = (["English"] * 8 + ["Math"] * 8 + ["Chinese"] * 4
                 + ["Phy"] * 4 + ["Chem"] * 3 + ["Bio"] * 3
                 + ["History"] * 4 + ["Geography"] * 3 + ["Economy"] * 2
                 + ["Western Acting"] * 1 + ["Art"] * 4 + ["Music"] * 3
                 + ["Computer Science"] * 5 + ["Language"] * 2 + ["PBL"] * 2
                 + ["PE"] * 4)
# cross-qualification groups (realistic department sharing)
SCIENCES = {"Phy", "Chem", "Bio"}
HUMANITIES = {"History", "Geography", "Economy", "Western Acting"}
ARTS = {"Art", "Music"}
PE_EXTRA = 20          # extra teachers dual-qualified for PE (fixed parallel)
OPTIONAL_POOL = 30     # teachers qualified for the Wed P4 Optional slot


def wpick(rng, pairs):
    r, acc = rng.random(), 0.0
    for v, w in pairs:
        acc += w
        if r <= acc:
            return v
    return pairs[-1][0]


def level_weights(subject, grade):
    n = len(SUBJECT_LEVELS[grade][subject])
    if n == 2:
        return [(SUBJECT_LEVELS[grade][subject][0], .6),
                (SUBJECT_LEVELS[grade][subject][1], .4)]
    if n == 3:
        return [(SUBJECT_LEVELS[grade][subject][0], .5),
                (SUBJECT_LEVELS[grade][subject][1], .3),
                (SUBJECT_LEVELS[grade][subject][2], .2)]
    return [(lv, .4 if i == 0 else .25 if i == 1 else .2 if i == 2 else .15)
            for i, lv in enumerate(SUBJECT_LEVELS[grade][subject])]


def make_name(rng, used):
    for _ in range(80):
        n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if n not in used:
            used.add(n)
            return n
    i = 2
    while f"{n} {i}" in used:
        i += 1
    n = f"{n} {i}"
    used.add(n)
    return n


def gen_student(rng, used, grade, idx):
    st = {"id": f"G{grade}-{idx + 1:03d}", "name": make_name(rng, used),
          "grade": grade, "band": None, "levels": {}}
    # ability drives level placement in every subject (correlated, like a
    # real school); bands are then formed by sorting on ability so each
    # band hosts a narrow level range -> fewer parallel sections
    ability = rng.random()
    st["ability"] = ability

    def lv(subject):
        levels = SUBJECT_LEVELS[grade][subject]
        n = len(levels)
        i = int(ability * n + rng.uniform(-0.3, 0.3))
        i = max(0, min(n - 1, i))
        l = levels[i]
        st["levels"][subject] = l
        return l

    lv("Chinese"); lv("English"); lv("Math"); lv("History")
    if grade == 10:
        pair = tuple(sorted(rng.sample(G10_SCIENCES, 2)))
        st["science_pair"] = pair          # e.g. ("Bio","Phy")
        for s in pair:
            lv(s)
        e = wpick(rng, ELEC10_W)
        st["elective"] = e
        lv(e)
    else:
        lv("Phy"); lv("Chem")
        e = wpick(rng, ELEC9_W)
        st["elective"] = e
        lv(e)
        st["artmusic"] = wpick(rng, ARTMUS_W)
    return st


def block_map(st):
    """Map block name -> (subject, level) for this student."""
    g = st["grade"]
    lv = st["levels"]
    m = {"En": ("English", lv["English"]), "Ma": ("Math", lv["Math"]),
         "Ch": ("Chinese", lv["Chinese"]), "Hist": ("History", lv["History"]),
         "Lang": ("Language", None), "PBL": ("PBL", None), "PE": ("PE", None),
         "CAS": ("CAS", None), "Opt": ("Optional", None)}
    if g == 10:
        a, b = st["science_pair"]          # alphabetical, a < b
        # canonical split keeps both blocks balanced (300/block/grade)
        first = {"Bio": "SciX", "Chem": "SciY", "Phy": "SciX"}
        m[first[a]] = (a, lv[a])
        m["SciY" if first[a] == "SciX" else "SciX"] = (b, lv[b])
        m["Elec"] = (st["elective"], lv[st["elective"]])
    else:
        m["Phy"] = ("Phy", lv["Phy"])
        m["Chem"] = ("Chem", lv["Chem"])
        m["Elec"] = (st["elective"], lv[st["elective"]])
        m["ArtMus"] = (st["artmusic"], None)
        m.pop("PBL")                       # grade 9 has no PBL
    return m


def generate():
    rng = random.Random(SEED)
    os.makedirs(DATA, exist_ok=True)
    used = set()

    students = [gen_student(rng, used, g, i)
                for g in (9, 10) for i in range(STUDENTS_PER_GRADE)]
    # bands: sort by ability within the grade, then chunk -> level-homogeneous
    # scheduling groups (fewer distinct levels per band -> fewer sections)
    per_grade = defaultdict(list)
    for st in students:
        per_grade[st["grade"]].append(st)
    for g, studs in per_grade.items():
        studs.sort(key=lambda s: (-s["ability"], s["id"]))
        for i, st in enumerate(studs):
            st["band"] = f"{g}{'ABCDEF'[i // (len(studs) // BANDS_PER_GRADE)]}"
            del st["ability"]
    for st in students:
        st["blocks"] = {k: list(v) for k, v in block_map(st).items()}

    # ------------------------------------------------------------- output
    with open(os.path.join(DATA, "students.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["grade_band", "name", "subjects"])
        for st in students:
            parts = [f"{s}_{l}" if l else s for s, l in
                     (st["blocks"][b] for b in sorted(st["blocks"]))]
            w.writerow([st["band"], st["name"], ";".join(sorted(parts))])

    with open(os.path.join(DATA, "students.json"), "w", encoding="utf-8") as f:
        json.dump(students, f, ensure_ascii=False)

    print(f"students={len(students)} (teachers are generated by solver.py "
          f"from measured scheduling peaks)")


if __name__ == "__main__":
    generate()
