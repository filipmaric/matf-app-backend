# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import sqlite3
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SHEETS = ("predmeti1sem", "predmeti2sem")
FULLY_ELECTIVE_STATUS = "потпуно изборни"


def write_courses_workbook(path):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in SHEETS:
        workbook.create_sheet(sheet_name)

    def block(code, name, module="М", accreditation="2022", year="1"):
        return "\n".join(
            (
                f"Шифра: {code}",
                f"Назив: {name}",
                f"Модул: {module}",
                f"Акредитација: {accreditation}",
                f"Година: {year}",
            )
        )

    fall = workbook["predmeti1sem"]
    fall.cell(row=3, column=2, value="П099")
    fall.cell(row=3, column=21, value=block("S099", "Fall Subject"))
    fall.cell(row=4, column=2, value="П100")
    fall.cell(row=4, column=21, value=block("S100", "Another Fall Subject"))

    spring = workbook["predmeti2sem"]
    spring.cell(row=3, column=2, value="П101")
    spring.cell(row=3, column=21, value=block("S101", "Увод у алгоритме"))
    spring.cell(row=3, column=22, value=block("S102", "Програмирање 2"))
    spring.cell(row=4, column=2, value="Р274")
    spring.cell(row=4, column=21, value=block("S101", "Увод у алгоритме"))

    workbook.save(path)


def parse_block(cell):
    parsed = {}
    for raw_line in str(cell).splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def is_fully_elective_block(parsed):
    return str(parsed.get("Статус") or "").strip().casefold() == FULLY_ELECTIVE_STATUS.casefold()


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        with open(REPO_ROOT / "schema.sql", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.executemany(
            """
            INSERT INTO semesters (id, academic_year_start, season, start_date, end_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (3, 2026, "јесењи", "2026-10-01", "2027-02-28"),
                (4, 2026, "пролећни", "2027-03-01", "2027-09-30"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def run_script(args):
    return subprocess.run(
        [PYTHON, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def fetch_all(db_path, query):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def count_distinct_group_codes(workbook_path):
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    codes = set()
    for sheet_name in SHEETS:
        ws = workbook[sheet_name]
        for row in ws.iter_rows(min_row=3, values_only=True):
            if len(row) <= 1:
                continue
            code = str(row[1] or "").strip()
            if not code:
                continue
            if any(
                cell not in (None, "") and not is_fully_elective_block(parse_block(cell))
                for cell in row[20:]
            ):
                codes.add(code)
    return len(codes)


def count_distinct_memberships(workbook_path):
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    memberships = set()
    for sheet_name in SHEETS:
        ws = workbook[sheet_name]
        for row in ws.iter_rows(min_row=3, values_only=True):
            if len(row) <= 1:
                continue
            group_code = str(row[1] or "").strip()
            if not group_code:
                continue
            for cell in row[20:]:
                if cell in (None, ""):
                    continue
                parsed = parse_block(cell)
                if is_fully_elective_block(parsed):
                    continue
                subject_code = str(parsed.get("Шифра") or "").strip()
                module = str(parsed.get("Модул") or "").strip()
                accreditation = str(parsed.get("Акредитација") or "").strip()
                if subject_code and module and accreditation.isdigit():
                    memberships.add((subject_code, module, int(accreditation)))
    return len(memberships)


def count_distinct_subjects(workbook_path):
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    subjects = set()
    for sheet_name in SHEETS:
        ws = workbook[sheet_name]
        for row in ws.iter_rows(min_row=3, values_only=True):
            for cell in row[20:]:
                if cell in (None, ""):
                    continue
                parsed = parse_block(cell)
                if is_fully_elective_block(parsed):
                    continue
                subject_code = str(parsed.get("Шифра") or "").strip()
                module = str(parsed.get("Модул") or "").strip()
                accreditation = str(parsed.get("Акредитација") or "").strip()
                year = str(parsed.get("Година") or "").strip()
                subject_name = str(parsed.get("Назив") or "").strip()
                if subject_code and module and accreditation.isdigit() and subject_name:
                    year_value = 0
                    if year.isdigit() and 1 <= int(year) <= 5:
                        year_value = int(year)
                    subjects.add(
                        (
                            subject_code,
                            subject_name,
                            int(accreditation),
                            module,
                            year_value,
                        )
                    )
    return len(subjects)


def count_duplicate_memberships(workbook_path):
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    seen = set()
    duplicates = 0
    for sheet_name in SHEETS:
        ws = workbook[sheet_name]
        for row in ws.iter_rows(min_row=3, values_only=True):
            if len(row) <= 1:
                continue
            group_code = str(row[1] or "").strip()
            if not group_code:
                continue
            for cell in row[20:]:
                if cell in (None, ""):
                    continue
                parsed = parse_block(cell)
                if is_fully_elective_block(parsed):
                    continue
                subject_code = str(parsed.get("Шифра") or "").strip()
                module = str(parsed.get("Модул") or "").strip()
                accreditation = str(parsed.get("Акредитација") or "").strip()
                if subject_code and module and accreditation.isdigit():
                    key = (subject_code, module, int(accreditation))
                    if key in seen:
                        duplicates += 1
                    else:
                        seen.add(key)
    return duplicates


def count_duplicate_membership_pairs(workbook_path):
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    seen = set()
    duplicate_pairs = set()
    for sheet_name in SHEETS:
        ws = workbook[sheet_name]
        for row in ws.iter_rows(min_row=3, values_only=True):
            if len(row) <= 1:
                continue
            group_code = str(row[1] or "").strip()
            if not group_code:
                continue
            for cell in row[20:]:
                if cell in (None, ""):
                    continue
                parsed = parse_block(cell)
                if is_fully_elective_block(parsed):
                    continue
                subject_code = str(parsed.get("Шифра") or "").strip()
                module = str(parsed.get("Модул") or "").strip()
                accreditation = str(parsed.get("Акредитација") or "").strip()
                if subject_code and module and accreditation.isdigit():
                    key = (subject_code, module, int(accreditation))
                    if key in seen:
                        duplicate_pairs.add(key)
                    else:
                        seen.add(key)
    return len(duplicate_pairs)


def read_csv_rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_exported_courses_csv(path):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "course_code",
                "course_name",
                "course_semester",
                "requires_computers",
                "subject_code",
                "subject_name",
                "subject_accreditation",
                "subject_module",
                "subject_year",
            ]
        )
        writer.writerow(["C1", "Course One", "јесењи", 1, "S1", "Subject One", 2015, "М", 2])
        writer.writerow(["C1", "Course One", "јесењи", 1, "S2", "Subject Two", 2022, "М", 3])
        writer.writerow(["C2", "Course Two", "пролећни", 0, "", "", "", "", ""])


def write_exported_courses_csv_with_course_only_row(path):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "course_code",
                "course_name",
                "course_semester",
                "requires_computers",
                "subject_code",
                "subject_name",
                "subject_accreditation",
                "subject_module",
                "subject_year",
            ]
        )
        writer.writerow(["C1", "Course One", "јесењи", 1, "S1", "Subject One", 2015, "М", 2])
        writer.writerow(["C2", "Course Two", "пролећни", 0, "", "", "", "", ""])


def test_import_course_groups_populates_courses_table(tmp_path):
    db_path = tmp_path / "courses.db"
    csv_path = tmp_path / "course_groups.csv"
    workbook_path = tmp_path / "courses.xlsx"
    write_courses_workbook(workbook_path)

    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO courses (name, code, semester) VALUES (?, ?, ?)",
                ("Stale Fall Course", "STALE-SEM3", 3),
            )
            conn.execute(
                "INSERT INTO courses (name, code, semester) VALUES (?, ?, ?)",
                ("Stale Spring Course", "STALE-SEM4", 4),
            )
            conn.execute(
                "INSERT INTO courses (name, code, semester) VALUES (?, ?, ?)",
                ("Keep Course", "KEEP-SEM1", 1),
            )
    finally:
        conn.close()

    result = run_script(
        [
            "scripts/import/import_courses.py",
            "--year",
            "2026",
            "--input",
            str(workbook_path),
            "--database",
            str(db_path),
            "--schema",
            str(REPO_ROOT / "schema.sql"),
            "--csv-output",
            str(csv_path),
        ]
    )

    rows = fetch_all(db_path, "SELECT code, name FROM courses ORDER BY code")
    semester_rows = fetch_all(
        db_path,
        "SELECT code, semester FROM courses ORDER BY code",
    )
    subject_rows = fetch_all(
        db_path,
        "SELECT code, name, accreditation, module, year FROM subjects ORDER BY code, accreditation, module, year",
    )
    course_subject_rows = fetch_all(
        db_path,
        """
        SELECT course_code, subject_id
        FROM course_subjects
        ORDER BY course_code, subject_id
        """,
    )
    csv_rows = read_csv_rows(csv_path)
    assert len(rows) == count_distinct_group_codes(workbook_path) + 1
    assert len(csv_rows) == count_distinct_group_codes(workbook_path)
    assert len(rows) == len({row["code"] for row in rows})
    assert len(subject_rows) == count_distinct_subjects(workbook_path)
    assert len(course_subject_rows) == count_distinct_memberships(workbook_path)
    assert f"DUPLICATE_PAIRS={count_duplicate_membership_pairs(workbook_path)}" in result.stderr
    assert f"DUPLICATE_OCCURRENCES={count_duplicate_memberships(workbook_path)}" in result.stderr
    assert "YEAR=2026" in result.stdout
    assert "ACADEMIC_YEAR=2026/27" in result.stdout
    assert "SEMESTER=2026/27. јесењи" in result.stdout
    assert "SEMESTER=2026/27. пролећни" in result.stdout
    assert "CLEARED_COURSES=2" in result.stdout
    assert "PRUNED_SUBJECTS=" in result.stdout
    assert not any(
        row["code"] == "2А1.03"
        and row["name"] == "Међузвездана материја"
        and row["accreditation"] == 2015
        and row["module"] == "ААФ"
        and row["year"] == 0
        for row in subject_rows
    )

    assert next(row for row in semester_rows if row["code"] == "KEEP-SEM1")["semester"] == 1
    p101 = next(row for row in rows if row["code"] == "П101")
    assert p101["name"] == "Увод у алгоритме / Програмирање 2"
    assert next(row for row in semester_rows if row["code"] == "П099")["semester"] == 3
    assert next(row for row in semester_rows if row["code"] == "П101")["semester"] == 4
    assert next(row for row in semester_rows if row["code"] == "Р274")["semester"] == 4
    assert "STALE-SEM3" not in {row["code"] for row in rows}
    assert "STALE-SEM4" not in {row["code"] for row in rows}

    csv_p101 = next(row for row in csv_rows if row["code"] == "П101")
    assert csv_p101["name"] == "Увод у алгоритме / Програмирање 2"



def test_import_course_groups_accepts_exported_csv(tmp_path):
    db_path = tmp_path / "courses.db"
    csv_path = tmp_path / "courses.csv"

    init_db(db_path)
    write_exported_courses_csv(csv_path)

    run_script(
        [
            "scripts/import/import_courses.py",
            "--year",
            "2026",
            "--input",
            str(csv_path),
            "--database",
            str(db_path),
            "--schema",
            str(REPO_ROOT / "schema.sql"),
        ]
    )

    rows = [
        dict(row)
        for row in fetch_all(
            db_path,
            "SELECT code, name, semester, requires_computers FROM courses ORDER BY code",
        )
    ]
    subject_rows = [dict(row) for row in fetch_all(
        db_path,
        "SELECT code, name, accreditation, module, year FROM subjects ORDER BY code, accreditation, module",
    )]
    course_subject_rows = fetch_all(
        db_path,
        """
        SELECT course_code, subject_id
        FROM course_subjects
        ORDER BY course_code, subject_id
        """,
    )
    assert rows == [
        {"code": "C1", "name": "Course One", "semester": 3, "requires_computers": 1},
        {"code": "C2", "name": "Course Two", "semester": 4, "requires_computers": 0},
    ]
    assert subject_rows == [
        {"code": "S1", "name": "Subject One", "accreditation": 2015, "module": "М", "year": 2},
        {"code": "S2", "name": "Subject Two", "accreditation": 2022, "module": "М", "year": 3},
    ]
    assert len(course_subject_rows) == 2


def test_import_course_groups_skips_csv_rows_without_module(tmp_path):
    db_path = tmp_path / "courses.db"
    csv_path = tmp_path / "courses.csv"

    init_db(db_path)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "course_code",
                "course_name",
                "course_semester",
                "requires_computers",
                "subject_code",
                "subject_name",
                "subject_accreditation",
                "subject_module",
                "subject_year",
            ]
        )
        writer.writerow(["C1", "Course One", "јесењи", 1, "S1", "Subject One", 2015, "М", 2])
        writer.writerow(["C2", "Course Two", "пролећни", 0, "S2", "Subject Two", 2022, "М", 3])

    run_script(
        [
            "scripts/import/import_courses.py",
            "--year",
            "2026",
            "--input",
            str(csv_path),
            "--database",
            str(db_path),
            "--schema",
            str(REPO_ROOT / "schema.sql"),
        ]
    )

    rows = [
        dict(row)
        for row in fetch_all(
            db_path,
            "SELECT code, name, semester, requires_computers FROM courses ORDER BY code",
        )
    ]
    subject_rows = [
        dict(row)
        for row in fetch_all(
            db_path,
            "SELECT code, name, accreditation, module, year FROM subjects ORDER BY code, accreditation, module",
        )
    ]
    course_subject_rows = fetch_all(
        db_path,
        """
        SELECT course_code, subject_id
        FROM course_subjects
        ORDER BY course_code, subject_id
        """,
    )

    assert rows == [
        {"code": "C1", "name": "Course One", "semester": 3, "requires_computers": 1},
        {"code": "C2", "name": "Course Two", "semester": 4, "requires_computers": 0},
    ]
    assert subject_rows == [
        {"code": "S1", "name": "Subject One", "accreditation": 2015, "module": "М", "year": 2},
        {"code": "S2", "name": "Subject Two", "accreditation": 2022, "module": "М", "year": 3},
    ]
    assert len(course_subject_rows) == 2


def test_import_course_groups_keeps_course_without_subject_data(tmp_path):
    db_path = tmp_path / "courses.db"
    csv_path = tmp_path / "courses.csv"

    init_db(db_path)
    write_exported_courses_csv_with_course_only_row(csv_path)

    run_script(
        [
            "scripts/import/import_courses.py",
            "--year",
            "2026",
            "--input",
            str(csv_path),
            "--database",
            str(db_path),
            "--schema",
            str(REPO_ROOT / "schema.sql"),
        ]
    )

    rows = [
        dict(row)
        for row in fetch_all(
            db_path,
            "SELECT code, name, semester, requires_computers FROM courses ORDER BY code",
        )
    ]
    assert rows == [
        {"code": "C1", "name": "Course One", "semester": 3, "requires_computers": 1},
        {"code": "C2", "name": "Course Two", "semester": 4, "requires_computers": 0},
    ]


def test_import_course_groups_merges_requires_computers_from_duplicate_csv_rows(tmp_path):
    db_path = tmp_path / "courses.db"
    csv_path = tmp_path / "courses.csv"

    init_db(db_path)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "course_code",
                "course_name",
                "course_semester",
                "requires_computers",
                "subject_code",
                "subject_name",
                "subject_accreditation",
                "subject_module",
                "subject_year",
            ]
        )
        writer.writerow(["C1", "Course One", "јесењи", 0, "S1", "Subject One", 2015, "М", 2])
        writer.writerow(["C1", "Course One", "јесењи", 1, "S1", "Subject One", 2015, "М", 2])

    run_script(
        [
            "scripts/import/import_courses.py",
            "--year",
            "2026",
            "--input",
            str(csv_path),
            "--database",
            str(db_path),
            "--schema",
            str(REPO_ROOT / "schema.sql"),
        ]
    )

    rows = [
        dict(row)
        for row in fetch_all(
            db_path,
            "SELECT code, name, semester, requires_computers FROM courses ORDER BY code",
        )
    ]
    assert rows == [
        {"code": "C1", "name": "Course One", "semester": 3, "requires_computers": 1},
    ]
