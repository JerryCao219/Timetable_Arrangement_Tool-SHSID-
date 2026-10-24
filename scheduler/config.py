"""Shared configuration parsed from classes.xlsx / classrooms.xlsx and the
requirements document, refined by user-confirmed course-selection rules.

Bi-weekly model (confirmed with user):
- "credit" = class-hours per week. The two-week cycle must deliver 2x hours.
- CAS is a connected double class in ODD weeks only (Wed P6+P7). In EVEN
  weeks the same Wed P6/P7 slots are filled by other subjects (e.g. Chinese),
  so bi-weekly totals stay exactly as specified.
- Both grades total exactly 76 class-hours per 2 weeks = full capacity.

Grade-10 menu: Chinese 3/wk, English 5.5, Math 5.5, pick 2 of Phy/Bio/Chem
(4 each), 1 elective of Economy/Art/Music/Geography/CS/WesternActing (4),
History 4, PBL 2 (double), PE 3, CAS 1, Language 1, Optional 1.
Grade-9 menu: Chinese 3, English 5.5, Math 5.5, Phy 4 + Chem 4 (required),
1 elective of CS/Bio/Geography (4), History 4, Art/Music pick 1 (2),
PE 3, CAS 1, Language 1, Optional 1.
"""

# ---------------------------------------------------------------- time grid
PERIOD_HOURS = {1: 1.5, 2: 1.0, 3: 1.0, 4: 1.0, 5: 1.5, 6: 1.0, 7: 1.0}
PERIOD_TIMES = {1: "08:30-09:30", 2: "09:40-10:20", 3: "10:30-11:10",
                4: "11:20-12:05", 5: "13:15-14:10", 6: "14:20-15:00",
                7: "15:10-15:50"}
DAYS = [1, 2, 3, 4, 5]
DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri"}
FRIDAY_MAX_PERIOD = 5
MAX_CLASS_SIZE = 25
DOUBLE_PAIRS = [(1, 2), (2, 3), (3, 4), (5, 6), (6, 7)]   # P4->P5 is lunch

# School-wide fixed meetings: block -> [(day, period, parity)]
# parity: "both" = every week, "odd" = odd weeks only.
FIXED = {
    "PE":  [(1, 5, "both"), (4, 5, "both")],
    "CAS": [(3, 6, "odd"), (3, 7, "odd")],
    "Opt": [(3, 4, "both")],
}

# ------------------------------------------------------------------- blocks
# Block catalogue per grade. hours2w = class-hours per 2 weeks.
# G10 science blocks SciX/SciY and elective block Elec host different actual
# subjects per student (choice model).
BLOCKS = {
    10: {"En": 11, "Ma": 11, "Ch": 6, "SciX": 8, "SciY": 8, "Elec": 8,
         "Hist": 8, "PBL": 4, "Lang": 2, "PE": 6, "CAS": 2, "Opt": 2},
    9:  {"En": 11, "Ma": 11, "Ch": 6, "Phy": 8, "Chem": 8, "Elec": 8,
         "Hist": 8, "ArtMus": 4, "Lang": 2, "PE": 6, "CAS": 2, "Opt": 2},
}

# Actual subjects behind each block (for teacher qualification / display)
BLOCK_SUBJECTS = {
    10: {"En": ["English"], "Ma": ["Math"], "Ch": ["Chinese"],
         "SciX": ["Phy", "Bio", "Chem"], "SciY": ["Phy", "Bio", "Chem"],
         "Elec": ["Economy", "Art", "Music", "Geography", "Computer Science",
                  "Western Acting"],
         "Hist": ["History"], "PBL": ["PBL"], "Lang": ["Language"],
         "PE": ["PE"], "CAS": ["CAS"], "Opt": ["Optional"]},
    9:  {"En": ["English"], "Ma": ["Math"], "Ch": ["Chinese"],
         "Phy": ["Phy"], "Chem": ["Chem"],
         "Elec": ["Computer Science", "Bio", "Geography"],
         "Hist": ["History"], "ArtMus": ["Art", "Music"], "Lang": ["Language"],
         "PE": ["PE"], "CAS": ["CAS"], "Opt": ["Optional"]},
}

# Levels per actual subject per grade (user-confirmed).
SUBJECT_LEVELS = {
    10: {"Chinese": ["S", "H"], "English": ["S", "S+", "H", "AP"],
         "Math": ["S", "H", "AP1", "AP2"], "Phy": ["S", "H"], "Bio": ["S", "H"],
         "Chem": ["S", "H"], "History": ["S", "H"],
         "Computer Science": ["S", "H", "AP"], "Economy": ["S", "H", "AP"],
         "Art": ["S", "H", "AP"], "Music": ["S", "H", "AP"],
         "Geography": ["S", "H"], "Western Acting": ["S", "H"]},
    9:  {"Chinese": ["S", "H"], "English": ["S", "H"], "Math": ["S", "H"],
         "Phy": ["S", "S+", "H"], "Chem": ["S", "S+", "H"],
         "History": ["S", "H"],
         "Computer Science": ["S", "H"], "Bio": ["S", "H"],
         "Geography": ["S", "H"]},
}

G10_ELECTIVES = ["Computer Science", "Economy", "Art", "Music", "Geography",
                 "Western Acting"]
G9_ELECTIVES = ["Computer Science", "Bio", "Geography"]
G10_SCIENCES = ["Phy", "Bio", "Chem"]

# ---------------------------------------------------------------- classrooms
CLASSROOMS = {
    9:  [311, 312, 313, 314, 315, 316, 317, 318, 319,
         401, 402, 403, 404, 405, 408, 409, 410, 411, 412, 413, 414, 415,
         416, 417, 306, 307, 308, 309],
    10: [306, 307, 308, 309, 304, 303, 302, 301,
         201, 202, 203, 204, 206, 207, 208, 209, 211, 212, 213, 214, 215,
         216, 217, 219],
}
FLOOR_PENALTY = 8


def floor_of(room):
    return room // 100


def travel(a, b):
    """0 same room, 1 same floor, 1+8=9 across floors."""
    if a == b:
        return 0
    return 1 if floor_of(a) == floor_of(b) else 1 + FLOOR_PENALTY


def periods_of_day(day):
    return list(range(1, FRIDAY_MAX_PERIOD + 1)) if day == 5 else list(range(1, 8))


def slot_hours(day, period):
    return PERIOD_HOURS[period]
