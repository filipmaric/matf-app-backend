# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import sqlite3
from pathlib import Path

from scripts.export.export_courses import export_courses


def _init_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with open(Path(__file__).resolve().parents[1] / "schema.sql", encoding="utf-8") as handle:
            conn.executescript(handle.read())
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


def _fetch_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_courses_exports_school_year_with_subjects(tmp_path):
    db_path = tmp_path / "courses.db"
    output_path = tmp_path / "courses.csv"
    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executemany(
            "INSERT INTO courses (name, code, semester, requires_computers) VALUES (?, ?, ?, ?)",
            [
                ("Linear Algebra", "M1.01", 3, 1),
                ("Programming", "M2.02", 4, 0),
                ("Out of Year", "M9.99", 2, 1),
            ],
        )
        subject_a = conn.execute(
            "INSERT INTO subjects (code, name, accreditation, module, year) VALUES (?, ?, ?, ?, ?)",
            ("M1.01", "Linear Algebra", 2022, "M", 1),
        ).lastrowid
        subject_b = conn.execute(
            "INSERT INTO subjects (code, name, accreditation, module, year) VALUES (?, ?, ?, ?, ?)",
            ("M2.02", "Programming", 2022, "M", 2),
        ).lastrowid
        conn.executemany(
            "INSERT INTO course_subjects (course_code, subject_id) VALUES (?, ?)",
            [
                ("M1.01", subject_a),
                ("M2.02", subject_b),
                ("M2.02", subject_a),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    assert export_courses(db_path, output_path, "2026") == 0

    rows = _fetch_rows(output_path)
    assert len(rows) == 3
    assert [row["course_code"] for row in rows] == ["M1.01", "M2.02", "M2.02"]
    assert [row["subject_code"] for row in rows] == ["M1.01", "M1.01", "M2.02"]
    assert [row["course_semester"] for row in rows] == ["јесењи", "пролећни", "пролећни"]
    assert [row["requires_computers"] for row in rows] == ["1", "0", "0"]
    assert "M9.99" not in {row["course_code"] for row in rows}
