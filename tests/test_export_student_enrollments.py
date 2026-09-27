# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
from pathlib import Path

import app as myapp
from scripts.export.export_student_enrollments import export_student_enrollments


def test_export_student_enrollments_exports_readable_rows_and_filters(db, tmp_path):
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

    output_path = tmp_path / "enrollments.csv"
    assert export_student_enrollments(Path(myapp.DATABASE), output_path) == 0

    with output_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows == [
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

    filtered_path = tmp_path / "filtered.csv"
    assert export_student_enrollments(
        Path(myapp.DATABASE),
        filtered_path,
        student_username="student1",
        semester_filter="2026/27. јесењи",
    ) == 0
    with filtered_path.open(encoding="utf-8-sig", newline="") as handle:
        filtered_rows = list(csv.DictReader(handle))
    assert filtered_rows == [
        {
            "student_username": "student1",
            "semester_name": "2026/27. јесењи",
            "subject_code": "M1.01",
            "subject_name": "Analiza 1",
            "subject_accreditation": "IS",
            "subject_module": "I",
            "subject_year": "1",
            "group_name": "1o1",
        }
    ]
