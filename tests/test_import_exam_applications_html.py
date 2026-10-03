# Copyright (c) 2026 Filip Marić. See LICENCE.

from pathlib import Path
import importlib

import app as myapp
import db as mydb

import_html_main = importlib.import_module(
    "scripts.import.import_exam_applications_html"
).main


def test_html_import_creates_term_and_resolves_students(tmp_path, db):
    semester_id = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "8/2025", "Бабић", "Христина")
    db.student("student2", "228/2022", "Валент", "Мартин")
    db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Аналитичка геометрија", "M3.01"),
    )
    subject_id = db.subject("M3.01", "Аналитичка геометрија", "2022", "М")
    db.course_subject("M3.01", subject_id)
    group_id = db.execute("INSERT INTO groups (name) VALUES (?)", ("1о2",))
    db.execute(
        "INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id) "
        "VALUES (?, ?, ?, ?)",
        ("student1", semester_id, subject_id, group_id),
    )
    db.execute(
        "INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id) "
        "VALUES (?, ?, ?, ?)",
        ("student2", semester_id, subject_id, group_id),
    )

    html_path = tmp_path / "applications.html"
    html_path.write_text(
        """
        <html><body>
        <td id="details">Септембар2 2026<br>
        Математика - Основне академске студије<br>
        проф. др Наставник, Аналитичка геометрија (M3.01), 1о2<br></td>
        <tbody id="students-list">
          <tr><td>1</td><td>8&nbsp;/&nbsp;2025</td><td>Буџ.</td></tr>
          <tr><td>2</td><td>228 / 2022</td><td>Сам.</td></tr>
        </tbody>
        <td id="details">Септембар2 2026<br>
        Математика - Основне академске студије<br>
        проф. др Наставник, Аналитичка геометрија (M3.01), 1о2<br></td>
        <tbody id="students-list">
          <tr><td>1</td><td>8 / 2025</td><td>Буџ.</td></tr>
        </tbody>
        </body></html>
        """,
        encoding="utf-8",
    )

    assert import_html_main(
        [
            str(Path(myapp.DATABASE)),
            str(html_path),
            "--start-date",
            "2026-09-21",
            "--end-date",
            "2026-10-02",
        ]
    ) == 0

    terms = mydb.query_db(
        "SELECT term_code, start_date, end_date, semester_id FROM exam_terms WHERE term_code = ?",
        ("2026.10",),
    )
    assert [(row["term_code"], row["start_date"], row["end_date"], row["semester_id"]) for row in terms] == [
        ("2026.10", "2026-09-21", "2026-10-02", semester_id)
    ]
    rows = mydb.query_db(
        """
        SELECT a.student_username, a.subject_id
        FROM exam_applications a
        WHERE a.term_code = ?
        ORDER BY a.student_username
        """,
        ("2026.10",),
    )
    assert [(row["student_username"], row["subject_id"]) for row in rows] == [
        ("student1", subject_id),
        ("student2", subject_id),
    ]
