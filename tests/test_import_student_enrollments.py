# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import importlib
from pathlib import Path

import app as myapp

from scripts.export.export_student_enrollments import export_student_enrollments

import_student_enrollments_main = importlib.import_module(
    "scripts.import.import_student_enrollments"
).main


def test_import_student_enrollments_round_trip(tmp_path, db):
    sem_fall = db.semester(name="2026/27. јесењи", start="2026-10-01", end="2027-02-28")
    sem_spring = db.semester(name="2026/27. пролећни", start="2027-03-01", end="2027-09-30")
    db.student("student1", "125/1997", "Maric", "Filip")
    db.student("student2", "126/1997", "Petrovic", "Mila")
    subject_a = db.subject("M1.01", "Analiza 1", "IS", "I", year=1)
    subject_b = db.subject("M2.02", "Programiranje", "2014", "I", year=2)
    group_1o1 = db.execute(
        "INSERT INTO groups (name, description) VALUES (?, ?)",
        ("1o1", None),
    )
    group_2o1 = db.execute(
        "INSERT INTO groups (name, description) VALUES (?, ?)",
        ("2o1", None),
    )
    db.execute(
        """
        INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id)
        VALUES (?, ?, ?, ?)
        """,
        ("student1", sem_fall, subject_a, group_1o1),
    )
    db.execute(
        """
        INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id)
        VALUES (?, ?, ?, ?)
        """,
        ("student1", sem_spring, subject_b, group_2o1),
    )
    db.execute(
        """
        INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id)
        VALUES (?, ?, ?, ?)
        """,
        ("student2", sem_fall, subject_a, group_1o1),
    )

    exported_path = tmp_path / "enrollments.csv"
    assert export_student_enrollments(Path(myapp.DATABASE), exported_path) == 0
    with exported_path.open(encoding="utf-8-sig", newline="") as handle:
        exported_rows = list(csv.DictReader(handle))
    assert exported_rows == [
        {
            "student_username": "student1",
            "semester_name": "2026/27. јесењи",
            "subject_code": "M1.01",
            "subject_name": "Analiza 1",
            "subject_accreditation": "IS",
            "subject_module": "I",
            "subject_year": "1",
            "group_name": "1o1",
        },
        {
            "student_username": "student1",
            "semester_name": "2026/27. пролећни",
            "subject_code": "M2.02",
            "subject_name": "Programiranje",
            "subject_accreditation": "2014",
            "subject_module": "I",
            "subject_year": "2",
            "group_name": "2o1",
        },
        {
            "student_username": "student2",
            "semester_name": "2026/27. јесењи",
            "subject_code": "M1.01",
            "subject_name": "Analiza 1",
            "subject_accreditation": "IS",
            "subject_module": "I",
            "subject_year": "1",
            "group_name": "1o1",
        },
    ]

    db.execute("DELETE FROM student_enrollments")
    assert import_student_enrollments_main([Path(myapp.DATABASE).as_posix(), str(exported_path)]) == 0

    stored = myapp.query_db(
        """
        SELECT se.student_username,
               ssem.academic_year_start,
               ssem.season,
               s.code AS subject_code,
               s.name AS subject_name,
               s.accreditation AS subject_accreditation,
               s.module AS subject_module,
               s.year AS subject_year,
               g.name AS group_name
        FROM student_enrollments se
        JOIN semesters ssem ON ssem.id = se.semester_id
        JOIN subjects s ON s.id = se.subject_id
        JOIN groups g ON g.id = se.group_id
        ORDER BY se.student_username,
                 ssem.academic_year_start,
                 CASE ssem.season
                     WHEN 'јесењи' THEN 0
                     WHEN 'пролећни' THEN 1
                     ELSE 2
                 END,
                 s.code,
                 g.name
        """
    )
    assert [
        {
            "student_username": row["student_username"],
            "semester_name": f"{row['academic_year_start']}/{(int(row['academic_year_start']) + 1) % 100:02d}. {row['season']}",
            "subject_code": row["subject_code"],
            "subject_name": row["subject_name"],
            "subject_accreditation": str(row["subject_accreditation"]),
            "subject_module": row["subject_module"],
            "subject_year": str(row["subject_year"]),
            "group_name": row["group_name"],
        }
        for row in stored
    ] == exported_rows
