# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import sqlite3
from pathlib import Path

from scripts.export.export_exam_schedule import export_exam_schedule


def _init_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with open(Path(__file__).resolve().parents[1] / "schema.sql", encoding="utf-8") as handle:
            conn.executescript(handle.read())
        conn.execute(
            "INSERT INTO semesters (academic_year_start, season, start_date, end_date) VALUES (?, ?, ?, ?)",
            (2025, "пролећни", "2026-03-23", "2026-09-30"),
        )
        conn.commit()
    finally:
        conn.close()


def _fetch_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_exam_schedule_exports_one_row_per_course(tmp_path):
    db_path = tmp_path / "exam_schedule.db"
    output_path = tmp_path / "exam_schedule.csv"
    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO courses (name, code, requires_computers) VALUES (?, ?, ?)",
            ("Linear Algebra", "M1.01", 1),
        )
        conn.execute(
            "INSERT INTO courses (name, code, requires_computers) VALUES (?, ?, ?)",
            ("Programming", "M2.02", 0),
        )
        conn.execute(
            "INSERT INTO building_locations (building_name, latitude, longitude, radius_m) VALUES (?, ?, ?, ?)",
            ("A", 10.0, 20.0, 100),
        )
        conn.execute(
            "INSERT INTO building_locations (building_name, latitude, longitude, radius_m) VALUES (?, ?, ?, ?)",
            ("B", 11.0, 21.0, 100),
        )
        subject_a = conn.execute(
            "INSERT INTO subjects (code, name, accreditation, module) VALUES (?, ?, ?, ?)",
            ("M1.01", "Linear Algebra", "IS", "I"),
        ).lastrowid
        subject_b = conn.execute(
            "INSERT INTO subjects (code, name, accreditation, module) VALUES (?, ?, ?, ?)",
            ("M1.01", "Linear Algebra", "IT", "I"),
        ).lastrowid
        subject_c = conn.execute(
            "INSERT INTO subjects (code, name, accreditation, module) VALUES (?, ?, ?, ?)",
            ("M2.02", "Programming", "IS", "I"),
        ).lastrowid
        conn.executemany(
            "INSERT INTO course_subjects (course_code, subject_id) VALUES (?, ?)",
            [("M1.01", subject_a), ("M1.01", subject_b), ("M2.02", subject_c)],
        )
        conn.execute(
            """
            INSERT INTO exam_schedule (
                term_code,
                course_code,
                course_name,
                exam_date,
                exam_hour,
                location
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("2026.07", "M1.01", "Linear Algebra", "2026-07-03", 9, "A"),
        )
        conn.execute(
            """
            INSERT INTO exam_schedule (
                term_code,
                course_code,
                course_name,
                exam_date,
                exam_hour,
                location
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("2026.07", "M2.02", "Programming", "2026-07-04", 10, "B"),
        )
        conn.commit()
    finally:
        conn.close()

    assert export_exam_schedule(db_path, output_path, "2026.07") == 0

    rows = _fetch_rows(output_path)
    assert len(rows) == 2
    assert [row["course_code"] for row in rows] == ["M1.01", "M2.02"]
    assert [row["course_name"] for row in rows] == ["Linear Algebra", "Programming"]
    assert [row["exam_date"] for row in rows] == ["2026-07-03", "2026-07-04"]
    assert [row["requires_computers"] for row in rows] == ["1", "0"]
