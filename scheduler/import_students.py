"""Import a real student roster from a simple CSV into students_real.json.

Input:  data/students_real.csv   (Excel -> save as CSV, UTF-8)
Output: data/students_real.json  (consumed automatically by solver.py)

Columns (one row per student):

  name            student name
  grade           9 or 10
  Ch_lv           Chinese level      (S / H)
  En_lv           English level      (G10: S/S+/H/AP;  G9: S/H)
  Ma_lv           Math level         (G10: S/H/AP1/AP2; G9: S/H)
  Hist_lv         History level      (S / H)
  --- grade 10 only ---
  SciA, SciB      the 2 chosen sciences, each one of Phy/Bio/Chem
  SciA_lv, SciB_lv  their levels     (S / H)
  Elec            elective: Economy / Art / Music / Geography /
                  Computer Science / Western Acting
  Elec_lv         elective level     (CS/Economy/Art/Music: S/H/AP;
                                      Geography/Western Acting: S/H)
  --- grade 9 only ---
  Phy_lv          Physics level      (S / S+ / H)
  Chem_lv         Chemistry level    (S / S+ / H)
  Elec            Computer Science / Bio / Geography
  Elec_lv         S / H
  ArtMus          Art / Music

The "band" column is optional; if omitted, bands are auto-assigned by the
solver (students sorted by level so each band stays level-homogeneous).

Run:  python import_students.py  &&  python solver.py  &&  python validate.py
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.join(DATA, "students_real.csv")
DST = os.path.join(DATA, "students_real.json")

G10_ELECTIVES = {"Economy", "Art", "Music", "Geography", "Computer Science",
                 "Western Acting"}
G9_ELECTIVES = {"Computer Science", "Bio", "Geography"}
SCIENCES = {"Phy", "Bio", "Chem"}
ARTMUS = {"Art", "Music"}


def fail(row_no, name, msg):
    print(f"row {row_no} ({name}): {msg}")
    sys.exit(1)


def convert():
    if not os.path.exists(SRC):
        print(f"input not found: {SRC}")
        print("create it first (see the column spec at the top of this file)")
        sys.exit(1)
    students = []
    with open(SRC, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), 2):
            name = (row.get("name") or "").strip()
            g = (row.get("grade") or "").strip()
            if not name or g not in ("9", "10"):
                fail(i, name, "need name and grade (9 or 10)")
            g = int(g)
            lv = {k: (row.get(k) or "").strip() or None
                  for k in ("Ch_lv", "En_lv", "Ma_lv", "Hist_lv")}
            blocks = {"En": ["English", lv["En_lv"]],
                      "Ma": ["Math", lv["Ma_lv"]],
                      "Ch": ["Chinese", lv["Ch_lv"]],
                      "Hist": ["History", lv["Hist_lv"]],
                      "Lang": ["Language", None], "PE": ["PE", None],
                      "CAS": ["CAS", None], "Opt": ["Optional", None]}
            elec = (row.get("Elec") or "").strip()
            elec_lv = (row.get("Elec_lv") or "").strip() or None
            if g == 10:
                sa = (row.get("SciA") or "").strip()
                sb = (row.get("SciB") or "").strip()
                if sa not in SCIENCES or sb not in SCIENCES or sa == sb:
                    fail(i, name, "SciA/SciB must be 2 different of "
                                  "Phy/Bio/Chem")
                if elec not in G10_ELECTIVES:
                    fail(i, name, f"Elec must be one of {G10_ELECTIVES}")
                blocks["SciX"] = [sa, (row.get("SciA_lv") or "").strip()
                                  or None]
                blocks["SciY"] = [sb, (row.get("SciB_lv") or "").strip()
                                  or None]
                blocks["PBL"] = ["PBL", None]
            else:
                if elec not in G9_ELECTIVES:
                    fail(i, name, f"Elec must be one of {G9_ELECTIVES}")
                am = (row.get("ArtMus") or "").strip()
                if am not in ARTMUS:
                    fail(i, name, "ArtMus must be Art or Music")
                blocks["Phy"] = ["Phy", (row.get("Phy_lv") or "").strip()
                                 or None]
                blocks["Chem"] = ["Chem", (row.get("Chem_lv") or "").strip()
                                  or None]
                blocks["ArtMus"] = [am, None]
            blocks["Elec"] = [elec, elec_lv]
            students.append({
                "id": f"G{g}-{len([s for s in students
                                    if s['grade'] == g]) + 1:03d}",
                "name": name, "grade": g,
                "band": (row.get("band") or "").strip() or None,
                "blocks": blocks})
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(students, f, ensure_ascii=False)
    n9 = sum(1 for s in students if s["grade"] == 9)
    n10 = sum(1 for s in students if s["grade"] == 10)
    print(f"imported {len(students)} students (G9={n9}, G10={n10}) "
          f"-> {DST}")
    print("next: python solver.py && python validate.py")


if __name__ == "__main__":
    convert()
