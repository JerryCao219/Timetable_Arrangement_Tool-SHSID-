# SHSID Timetable — HackSHSID 2026 Track 1

A bi-weekly (odd/even week) timetable generator for 600 students (Grades 9-10,  
300 each, as in the name list), with per-student and per-teacher schedules, exported to a pure  
static web app.

## Quick start

```bash
cd scheduler
python gen_data.py     # synthetic students (replace with real files later)
python solver.py       # builds the timetable -> output/timetable.json, web/data.js
python validate.py     # verifies all MUST constraints -> output/report.json
```

Then open `web/index.html` (or serve the folder: `python -m http.server`).

## Model (confirmed with the requirements owner)

- **"credit" = fixed weekly class-hours.** P1/P5 = 1.5 h, P4 = 1 h, others  
  1 h; Friday has no P6/P7. Weekly capacity = 38 h, bi-weekly = 76 h.
- **Odd/even weeks.** The base template (36 h) is identical in both weeks —  
  this minimises week-dependent courses. Odd weeks add the CAS double at  
  Wed P6-P7; even weeks fill the same slots with a double of a rotating  
  "filler" subject, so every subject's bi-weekly hours equal exactly 2x its  
  weekly target.
- **Same-subject doubles are allowed** (two connected periods on one day);  
  more than two periods per subject per day are not.
- **Levels.** Sections never mix levels (Math S/H/AP1/AP2, English S/S+/H/AP,  
  History S/H, sciences S/S+/H, electives S/H/AP per subject); max 25  
  students per section.
- **Choice model.** G10: pick 2 of Phy/Bio/Chem + 1 of 6 electives; G9:  
  Phy+Chem required, pick 1 of CS/Bio/Geography, Art/Music pick 1.
- **PE / CAS / Optional** are taught by dedicated staff (unrestricted, one  
  teacher per section), reflecting reality.
- **Electives are grade-shared blocks**: all bands of a grade have their  
  elective meetings at the same four slots, so sections are formed  
  grade-wide (no fragmented mini-classes).

## Architecture

`config.py` (rules) -> `gen_data.py` (synthetic students) -> `solver.py`  
-> `validate.py` -> `web/` (static front-end reading `data.js`).

Solver pipeline:

1. **Band templates.** Each grade is split into 4 scheduling bands of 75.  
   A randomized backtracking search places 8 x 1.5 h + 20 x 1.0 h meetings  
   into the 28 non-fixed slots (exact packing). Per band 250 candidates are  
   generated; the one minimising the sum of squared per-slot teacher-family  
   loads wins. Bands are staggered to flatten parallel demand.
2. **Sections.** Students are grouped by (band, block, subject, level),  
   chunked to <= 25. Elective sections are formed grade-wide.
3. **Teachers.** The academic pool is sized from *measured* parallel peaks  
   per subject family, then per-family pattern-group assignment (with  
   randomised restarts) allocates sections; if a family proves infeasible,  
   one teacher is added and the family is retried (auto-slack). Daily load  
   variance is the tie-breaker, keeping teacher days balanced.
4. **Rooms.** Random feasible assignment, then a local-search swap  
   optimisation minimising total student travel (same floor = 1, cross  
   floor = 9, lunch crossing P4->P5 free).

## Verified constraints (validate.py, all PASS)

1. Every student: exactly 38 h in odd weeks and 38 h in even weeks.
2. No student slot clashes.
3. No teacher slot clashes. **One teacher teaches exactly one subject.**
4. No room clashes; rooms come from the grade's pool.
5. Section size <= 25, single level per section.
6. Bi-weekly subject hours = 2x weekly target for every student.
7. At most 2 meetings per block per day, connected doubles only.
8. CAS only in odd weeks (Wed P6-P7); even-week filler double per band.
9. PE fixed Mon P5 + Thu P5; no P6/P7 on Friday.
10. Only CAS + filler blocks are week-dependent (bi-weekly courses  
    minimised).

## Results (synthetic data, seed 20261024)

| Metric                                    | Value                                                                             |
| ----------------------------------------- | --------------------------------------------------------------------------------- |
| Sections                                  | 341                                                                               |
| Academic teachers                         | **105** (per-subject pools from measured peaks + auto-slack + load-balancing pad) |
| Dedicated PE/CAS/Optional staff           | 72 (one per section)                                                              |
| Student travel saved by room optimisation | **62.4%** (129,876 -> 48,879)                                                     |
| Avg student travel                        | 40.7 units / week                                                                 |
| Odd/even-only sections                    | 54 (CAS + fillers only — theoretical minimum)                                     |
| Teacher daily-hour spread                 | 2.40 h avg                                                                        |

**One teacher = one subject** (hard rule, verified by `validate.py`).  
Teacher pools are sized per subject from measured parallel peaks; students  
are ability-sorted into scheduling bands so each band hosts a narrow level  
range, which minimises level fragmentation and hence the teacher count.  
The pool is then padded to the 105-teacher target by reinforcing the  
most-loaded subjects, which also improves daily load balance.

## Demo examples

The web app ships **20 featured timetables**: 12 students spanning both  
grades, all 6+3 electives, Art/Music choices and diverse Math/English  
levels, plus 8 teachers of different subjects (English, Math, Chinese,  
Physics, Chemistry, Biology, History, Economy). Any other student or  
teacher is searchable by name.

## AI usage disclosure

The whole project (scheduler design, constraint modelling, code, front-end)  
was developed with an AI pair-programmer (WorkBuddy); requirements were  
clarified interactively, and all constraint checks are machine-verified by  
`validate.py` rather than assumed.

## Replacing synthetic data with real files

**Real teacher roster**: copy `scheduler/data/teachers_real.example.csv` to  
`scheduler/data/teachers_real.csv` and replace its rows with the real  
staff (columns `name,subjects`, subjects separated by `;` — the FIRST  
subject is the one they teach, one subject per teacher). Re-run  
`solver.py`: it detects the file automatically and assigns from the fixed  
roster. If a subject is short-staffed, the solver stops with an exact  
message like `subject 'English' is short-staffed: 13 provided, need at
least 15` — add the missing teachers and re-run. Delete/rename the file to  
return to synthetic mode.

**Real student list**: fill in `scheduler/data/students_real.example.csv`  
(column spec is documented at the top of `import_students.py`), rename it  
to `students_real.csv`, then run `python import_students.py` — it converts  
the CSV into `students_real.json` with per-row error messages. The solver  
detects the JSON automatically; bands may be omitted (auto-assigned by  
level clustering). Delete/rename the JSON to return to synthetic mode.  
Re-run `solver.py` + `validate.py` after any data change.
