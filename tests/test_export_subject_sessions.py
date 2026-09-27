# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import sqlite3
from pathlib import Path

from scripts.export.export_subject_sessions import export_subject_sessions


def _init_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            with open(Path(__file__).resolve().parents[1] / "schema.sql", encoding="utf-8") as handle:
                conn.executescript(handle.read())
            conn.executemany(
                """
                INSERT INTO semesters (id, academic_year_start, season, start_date, end_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (3, 2025, "јесењи", "2025-10-01", "2026-02-28"),
                    (4, 2025, "пролећни", "2026-03-01", "2026-09-30"),
                ],
            )
    finally:
        conn.close()


def _fetch_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle, delimiter="\t", quotechar='"'))


def test_export_subject_sessions_exports_grupe_format(tmp_path):
    db_path = tmp_path / "allocations.db"
    output_path = tmp_path / "grupe.csv"
    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.execute("INSERT INTO teachers (name, username) VALUES (?, ?)", ("Бојан Новаковић", "bojan.novakovic"))
            conn.execute("INSERT INTO teachers (name, username) VALUES (?, ?)", ("Ђорђе Мијовић", "djordje.mijovic"))
            conn.execute("INSERT INTO courses (name, code, semester) VALUES (?, ?, ?)", ("Општа астрономија 1", "15-А1.01", 3))
            conn.execute("INSERT INTO courses (name, code, semester) VALUES (?, ?, ?)", ("Физички принципи структуре звезда", "15-А2.06", 3))
            conn.execute("INSERT INTO groups (name) VALUES (?)", ("1аф",))
            conn.execute("INSERT INTO groups (name) VALUES (?)", ("1аф-в",))
            conn.execute("INSERT INTO groups (name) VALUES (?)", ("4аф",))
            s1 = conn.execute(
                "INSERT INTO course_sessions (course_id, teacher_id, semester_id, type) VALUES ((SELECT id FROM courses WHERE code = ?), (SELECT id FROM teachers WHERE name = ?), ?, ?)",
                ("15-А1.01", "Бојан Новаковић", 3, "Предавања"),
            ).lastrowid
            conn.execute("INSERT INTO session_groups (session_id, group_id) VALUES (?, (SELECT id FROM groups WHERE name = ?))", (s1, "1аф"))
            s2 = conn.execute(
                "INSERT INTO course_sessions (course_id, teacher_id, semester_id, type) VALUES ((SELECT id FROM courses WHERE code = ?), (SELECT id FROM teachers WHERE name = ?), ?, ?)",
                ("15-А1.01", "Ђорђе Мијовић", 3, "Вежбе"),
            ).lastrowid
            conn.execute("INSERT INTO session_groups (session_id, group_id) VALUES (?, (SELECT id FROM groups WHERE name = ?))", (s2, "1аф-в"))
            s3 = conn.execute(
                "INSERT INTO course_sessions (course_id, teacher_id, semester_id, type) VALUES ((SELECT id FROM courses WHERE code = ?), (SELECT id FROM teachers WHERE name = ?), ?, ?)",
                ("15-А2.06", "Бојан Новаковић", 3, "Предавања"),
            ).lastrowid
            conn.execute("INSERT INTO session_groups (session_id, group_id) VALUES (?, (SELECT id FROM groups WHERE name = ?))", (s3, "4аф"))
            conn.executemany(
                "INSERT INTO students (username, student_index, surname, given_name) VALUES (?, ?, ?, ?)",
                [
                    ("s1", "1", "A", "A"),
                    ("s2", "2", "B", "B"),
                    ("s3", "3", "C", "C"),
                ],
            )
            conn.executemany(
                """
                INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id)
                VALUES (?, ?, NULL, (SELECT id FROM groups WHERE name = ?))
                """,
                [
                    ("s1", 3, "1аф"),
                    ("s2", 3, "1аф"),
                    ("s3", 3, "4аф"),
                ],
            )
    finally:
        conn.close()

    assert export_subject_sessions(db_path, output_path, "2025", "1") == 0

    rows = _fetch_rows(output_path)
    assert rows[0] == ["Групе у 1. семестру 2025/2026. године"]
    assert rows[1] == ["Ознака курса", "Назив курса", "Активност", "Наставник", "Ознака групе", "Број полазника"]
    assert rows[2][0:5] == ["15-А1.01", "Општа астрономија 1", "Предавања", "Бојан Новаковић", "1аф"]
    assert rows[2][5] == "2"
    assert rows[4][0:5] == ["15-А2.06", "Физички принципи структуре звезда", "Предавања", "Бојан Новаковић", "4аф"]
    assert rows[4][5] == "1"
