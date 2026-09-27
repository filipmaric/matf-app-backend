# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import importlib
from pathlib import Path

import app as myapp

from scripts.export.export_exam_applications import export_exam_applications

import_exam_applications_main = importlib.import_module(
    "scripts.import.import_exam_applications"
).main


def test_export_exam_applications_round_trip(tmp_path, db):
    db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "125/1997", "Maric", "Filip")
    db.student("student2", "126/1997", "Petrovic", "Mila")
    db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Linear Algebra", "M1.01"),
    )
    db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Programming", "M2.02"),
    )
    db.building_location("A", 10.0, 20.0, radius_m=100)
    subject_is = db.subject("M1.01", "Linear Algebra", "IS", "I")
    subject_it = db.subject("M1.01", "Linear Algebra", "IT", "I")
    subject_prog = db.subject("M2.02", "Programming", "2014", "I")
    db.course_subject("M1.01", subject_is)
    db.course_subject("M1.01", subject_it)
    db.course_subject("M2.02", subject_prog)

    db.execute(
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
        ("2026.06", "M1.01", "Linear Algebra", "2026-07-03", 9, "A"),
    )
    db.execute(
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
        ("2026.06", "M2.02", "Programming", "2026-07-04", 11, "A"),
    )
    db.execute(
        "INSERT INTO exam_applications (term_code, subject_id, student_username) VALUES (?, ?, ?)",
        ("2026.06", subject_is, "student1"),
    )
    db.execute(
        "INSERT INTO exam_applications (term_code, subject_id, student_username) VALUES (?, ?, ?)",
        ("2026.06", subject_it, "student2"),
    )
    db.execute(
        "INSERT INTO exam_applications (term_code, subject_id, student_username) VALUES (?, ?, ?)",
        ("2026.06", subject_prog, "student1"),
    )

    output_path = tmp_path / "exam_applications.csv"
    assert export_exam_applications(Path(myapp.DATABASE), output_path, "2026.06") == 0

    with output_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows == [
        {
            "Шифра курса": "M1.01",
            "Акредитација": "IS",
            "Модул": "I",
            "Корисничко име": "student1",
        },
        {
            "Шифра курса": "M1.01",
            "Акредитација": "IT",
            "Модул": "I",
            "Корисничко име": "student2",
        },
        {
            "Шифра курса": "M2.02",
            "Акредитација": "2014",
            "Модул": "I",
            "Корисничко име": "student1",
        },
    ]

    # Round-trip through the importer to confirm the contract matches.
    db.execute("DELETE FROM exam_applications")
    assert import_exam_applications_main([Path(myapp.DATABASE).as_posix(), "2026.06", str(output_path)]) == 0

    stored = myapp.query_db(
        """
        SELECT a.term_code, s.code, s.accreditation, s.module, a.student_username
        FROM exam_applications a
        JOIN subjects s ON s.id = a.subject_id
        ORDER BY s.code, s.accreditation, s.module, a.student_username
        """
    )
    assert [(row["term_code"], row["code"], row["accreditation"], row["module"], row["student_username"]) for row in stored] == [
        ("2026.06", "M1.01", "IS", "I", "student1"),
        ("2026.06", "M1.01", "IT", "I", "student2"),
        ("2026.06", "M2.02", 2014, "I", "student1"),
    ]
