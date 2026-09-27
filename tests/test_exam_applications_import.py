# Copyright (c) 2026 Filip Marić. See LICENCE.
import sqlite3
import importlib
from pathlib import Path

import app as myapp
import db as mydb

import_exam_applications_main = importlib.import_module(
    "scripts.import.import_exam_applications"
).main


def test_import_exam_applications_matches_course_code_and_accreditation(tmp_path, db):
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
    db.building_location("A", 10.0, 20.0, radius_m=100)
    subject_is = db.subject("M1.01", "Linear Algebra", "IS", "I")
    subject_it = db.subject("M1.01", "Linear Algebra", "IT", "I")
    subject_is_other_module = db.subject("M1.01", "Linear Algebra", "IS", "M")
    db.course_subject("M1.01", subject_is)
    db.course_subject("M1.01", subject_it)
    db.course_subject("M1.01", subject_is_other_module)

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
        (
            "2026.06",
            "M1.01",
            "Linear Algebra",
            "2026-07-03",
            9,
            "A",
        ),
    )

    csv_path = tmp_path / "exam_applications.csv"
    csv_path.write_text(
        "Шифра курса,Акредитација,Модул,Корисничко име\n"
        "M1.01,IS,I,student1\n"
        "M1.01,IT,I,student2\n",
        encoding="utf-8",
    )

    database_path = Path(myapp.DATABASE)
    assert import_exam_applications_main([str(database_path), "2026.06", str(csv_path)]) == 0

    initial_rows = mydb.query_db(
        """
        SELECT id, student_username
        FROM exam_applications
        WHERE term_code = ?
        ORDER BY student_username
        """,
        ("2026.06",),
    )
    assert [row["student_username"] for row in initial_rows] == ["student1", "student2"]
    preserved_id = initial_rows[0]["id"]

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
        (
            "2026.07",
            "M1.01",
            "Linear Algebra",
            "2026-07-10",
            9,
            "A",
        ),
    )
    db.execute(
        "INSERT INTO exam_applications (term_code, subject_id, student_username) VALUES (?, ?, ?)",
        ("2026.07", subject_is, "student1"),
    )

    csv_path.write_text(
        "Шифра курса,Акредитација,Модул,Корисничко име\n"
        "M1.01,IS,I,student1\n",
        encoding="utf-8",
    )
    assert import_exam_applications_main([str(database_path), "2026.06", str(csv_path)]) == 0

    synced_rows = mydb.query_db(
        """
        SELECT id, student_username
        FROM exam_applications
        WHERE term_code = ?
        ORDER BY student_username
        """,
        ("2026.06",),
    )
    assert [(row["id"], row["student_username"]) for row in synced_rows] == [
        (preserved_id, "student1"),
    ]
    other_term_rows = mydb.query_db(
        """
        SELECT term_code, student_username
        FROM exam_applications
        WHERE term_code = ?
        """,
        ("2026.07",),
    )
    assert [(row["term_code"], row["student_username"]) for row in other_term_rows] == [
        ("2026.07", "student1"),
    ]

    rows = mydb.query_db(
        """
        SELECT a.student_username, s.code AS subject_code, s.accreditation, s.module
        FROM exam_applications a
        JOIN subjects s
          ON s.id = a.subject_id
        WHERE a.term_code = ?
        ORDER BY a.student_username
        """,
        ("2026.06",),
    )
    assert [row["student_username"] for row in rows] == ["student1"]
    assert [row["accreditation"] for row in rows] == ["IS"]
    assert [row["module"] for row in rows] == ["I"]


def test_import_exam_applications_skips_unmatched_subject_rows(tmp_path, db):
    db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "125/1997", "Maric", "Filip")
    db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Linear Algebra", "M1.01"),
    )
    db.building_location("A", 10.0, 20.0, radius_m=100)
    subject_is = db.subject("M1.01", "Linear Algebra", "IS", "I")
    db.course_subject("M1.01", subject_is)
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

    csv_path = tmp_path / "exam_applications.csv"
    csv_path.write_text(
        "Шифра курса,Акредитација,Модул,Корисничко име\n"
        "M1.01,IS,I,student1\n"
        "M1.01,IS,Z,student1\n",
        encoding="utf-8",
    )

    database_path = Path(myapp.DATABASE)
    assert import_exam_applications_main([str(database_path), "2026.06", str(csv_path)]) == 0

    rows = mydb.query_db(
        """
        SELECT a.student_username, s.module
        FROM exam_applications a
        JOIN subjects s
          ON s.id = a.subject_id
        ORDER BY a.student_username
        """
    )
    assert [row["student_username"] for row in rows] == ["student1"]
    assert [row["module"] for row in rows] == ["I"]
