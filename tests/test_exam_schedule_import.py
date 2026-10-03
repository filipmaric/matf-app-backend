# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import importlib
import sqlite3
from pathlib import Path

import db as mydb

import_exam_schedule_module = importlib.import_module(
    "scripts.import.import_exam_schedule"
)
import_exam_schedule_main = importlib.import_module(
    "scripts.import.import_exam_schedule"
).main


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
        conn.execute(
            "INSERT INTO building_locations (building_name, latitude, longitude, radius_m) VALUES (?, ?, ?, ?)",
            ("A", 10.0, 20.0, 100),
        )
        conn.execute(
            "INSERT INTO building_locations (building_name, latitude, longitude, radius_m) VALUES (?, ?, ?, ?)",
            ("B", 11.0, 21.0, 100),
        )
        conn.commit()
    finally:
        conn.close()


def _write_schedule_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "course_code",
                "course_name",
                "exam_date",
                "exam_hour",
                "requires_computers",
                "location",
            ]
        )
        writer.writerows(rows)


def _fetch_exam_row(db_path, course_code):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        return conn.execute(
            """
            SELECT id,
                   term_code,
                   course_code,
                   course_name,
                   exam_date,
                   exam_hour,
                   location
            FROM exam_schedule
            WHERE term_code = ? AND course_code = ?
            """,
            ("2026.06", course_code),
        ).fetchone()
    finally:
        conn.close()


def _fetch_term_row(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        return conn.execute(
            "SELECT term_code, start_date, end_date, semester_id FROM exam_terms WHERE term_code = ?",
            ("2026.06",),
        ).fetchone()
    finally:
        conn.close()


def _fetch_applications(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        return conn.execute(
            """
            SELECT a.student_username, s.code AS subject_code, s.accreditation
            FROM exam_applications a
            JOIN subjects s
              ON s.id = a.subject_id
            ORDER BY a.student_username
            """
        ).fetchall()
    finally:
        conn.close()


def test_import_exam_schedule_synchronizes_term_and_cascades_removals(tmp_path):
    db_path = tmp_path / "exam_schedule.db"
    csv_path = tmp_path / "exam_schedule.csv"

    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.execute(
                "INSERT INTO courses (name, code) VALUES (?, ?)",
                ("Linear Algebra", "M1.01"),
            )
            conn.execute(
                "INSERT INTO courses (name, code) VALUES (?, ?)",
                ("Programming", "M2.02"),
            )
    finally:
        conn.close()

    _write_schedule_csv(
        csv_path,
        [
            [
                "M1.01",
                "Linear Algebra",
                "03. 07. 2026.",
                "9",
                "1",
                "A",
            ],
            [
                "M2.02",
                "Programming",
                "04. 07. 2026.",
                "11",
                "0",
                "B",
            ],
        ],
    )

    assert import_exam_schedule_main(
        [
            "--database",
            str(db_path),
            "--source",
            str(csv_path),
            "--term-code",
            "2026.06",
        ]
    ) == 0

    first_row = _fetch_exam_row(db_path, "M1.01")
    second_row = _fetch_exam_row(db_path, "M2.02")
    assert first_row is not None
    assert second_row is not None

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        subject = conn.execute(
            "INSERT INTO subjects (code, name, accreditation, module) VALUES (?, ?, ?, ?)",
            ("M1.01", "Linear Algebra", "IS", "I"),
        ).lastrowid
        conn.executemany(
            "INSERT INTO course_subjects (course_code, subject_id) VALUES (?, ?)",
            [("M1.01", subject)],
        )
        conn.execute(
            "INSERT INTO students (username, student_index, surname, given_name) VALUES (?, ?, ?, ?)",
            ("student1", "125/1997", "Maric", "Filip"),
        )
        conn.execute(
            """
            INSERT INTO exam_applications (term_code, subject_id, student_username)
            VALUES (?, ?, ?)
            """,
            ("2026.06", subject, "student1"),
        )
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        subject_it = conn.execute(
            "INSERT INTO subjects (code, name, accreditation, module) VALUES (?, ?, ?, ?)",
            ("M1.01", "Linear Algebra", "IT", "I"),
        ).lastrowid
        conn.executemany(
            "INSERT INTO course_subjects (course_code, subject_id) VALUES (?, ?)",
            [("M1.01", subject_it)],
        )
        conn.executemany(
            "INSERT INTO students (username, student_index, surname, given_name) VALUES (?, ?, ?, ?)",
            [
                ("student2", "126/1997", "Petrovic", "Mila"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO exam_applications
                (term_code, subject_id, student_username)
            VALUES (?, ?, ?)
            """,
            [
                ("2026.06", subject_it, "student2"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    _write_schedule_csv(
        csv_path,
        [
            [
                "M1.01",
                "Linear Algebra",
                "05. 07. 2026.",
                "10",
                "1",
                "A",
            ]
        ],
    )

    assert import_exam_schedule_main(
        [
            "--database",
            str(db_path),
            "--source",
            str(csv_path),
            "--term-code",
            "2026.06",
        ]
    ) == 0

    first_row_after = _fetch_exam_row(db_path, "M1.01")
    second_row_after = _fetch_exam_row(db_path, "M2.02")
    assert first_row_after is not None
    assert second_row_after is None
    assert first_row_after["exam_date"] == "2026-07-05"
    assert first_row_after["exam_hour"] == 10
    assert first_row_after["location"] == "A"

    term_row = _fetch_term_row(db_path)
    assert term_row["start_date"] == "2026-07-05"
    assert term_row["end_date"] == "2026-07-05"
    assert term_row["semester_id"] == 1

    applications = _fetch_applications(db_path)
    assert [(row["student_username"], row["subject_code"]) for row in applications] == [
        ("student1", "M1.01"),
        ("student2", "M1.01"),
    ]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        notification = conn.execute(
            """
            SELECT id, source_id, title, body
            FROM notifications
            WHERE title = ?
            """,
            ("Промена испита: Linear Algebra",),
        ).fetchone()
        assert notification is not None
        recipients = conn.execute(
            """
            SELECT student_username
            FROM notification_recipients
            WHERE notification_id = ?
            ORDER BY student_username
            """,
            (notification["id"],),
        ).fetchall()
        assert [row["student_username"] for row in recipients] == ["student1", "student2"]
    finally:
        conn.close()

def test_exam_schedule_unique_key_is_enforced(tmp_path):
    db_path = tmp_path / "exam_schedule.db"
    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
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
            (
                "2026.06",
                "M1.01",
                "Linear Algebra",
                "2026-07-03",
                9,
                "A",
            ),
        )
        conn.commit()

        try:
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
                (
                    "2026.06",
                    "M1.01",
                    "Linear Algebra",
                    "2026-07-05",
                    10,
                    "A",
                ),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("Expected unique key violation for duplicate exam schedule row")
    finally:
        conn.close()


def test_import_exam_schedule_ignores_duplicate_source_rows(tmp_path, capsys):
    db_path = tmp_path / "exam_schedule.db"
    csv_path = tmp_path / "exam_schedule.csv"

    _init_db(db_path)

    _write_schedule_csv(
        csv_path,
        [
            [
                "M1.01",
                "Linear Algebra",
                "03. 07. 2026.",
                "9",
                "1",
                "A",
            ],
            [
                "M1.01",
                "Linear Algebra Updated",
                "04. 07. 2026.",
                "9",
                "1",
                "A",
            ],
        ],
    )

    assert import_exam_schedule_main(
        [
            "--database",
            str(db_path),
            "--source",
            str(csv_path),
            "--term-code",
            "2026.06",
        ]
    ) == 0
    captured = capsys.readouterr()
    assert "conflicting exam schedule rows" in captured.err

    row = _fetch_exam_row(db_path, "M1.01")
    assert row is not None
    assert row["course_name"] == "Linear Algebra"
    assert row["exam_date"] == "2026-07-03"
    assert row["exam_hour"] == 9
    assert row["location"] == "A"


def test_import_exam_schedule_maps_unknown_location_to_null(tmp_path):
    db_path = tmp_path / "exam_schedule.db"
    csv_path = tmp_path / "exam_schedule.csv"

    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO courses (name, code) VALUES (?, ?)", ("Linear Algebra", "M1.01"))
        conn.commit()
    finally:
        conn.close()

    _write_schedule_csv(
        csv_path,
        [
            [
                "M1.01",
                "Linear Algebra",
                "03. 07. 2026.",
                "9",
                "1",
                "Непознато",
            ]
        ],
    )

    assert import_exam_schedule_main(
        [
            "--database",
            str(db_path),
            "--source",
            str(csv_path),
            "--term-code",
            "2026.06",
        ]
    ) == 0

    row = _fetch_exam_row(db_path, "M1.01")
    assert row is not None
    assert row["location"] is None


def test_import_exam_schedule_uses_all_linked_subject_names_in_accreditation_order(tmp_path):
    db_path = tmp_path / "exam_schedule.db"
    csv_path = tmp_path / "exam_schedule.csv"

    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            course_id = conn.execute(
                "INSERT INTO courses (name, code) VALUES (?, ?)",
                ("Grouped Course", "M1.01"),
            ).lastrowid
            older_subject_id = conn.execute(
                """INSERT INTO subjects (code, name, accreditation, module)
                   VALUES (?, ?, ?, ?)""",
                ("M1.01", "Older name", 2015, "A"),
            ).lastrowid
            newer_subject_id = conn.execute(
                """INSERT INTO subjects (code, name, accreditation, module)
                   VALUES (?, ?, ?, ?)""",
                ("M1.01", "Newer name", 2022, "A"),
            ).lastrowid
            conn.executemany(
                "INSERT INTO course_subjects (course_code, subject_id) VALUES (?, ?)",
                [("M1.01", older_subject_id), ("M1.01", newer_subject_id)],
            )
    finally:
        conn.close()

    _write_schedule_csv(
        csv_path,
        [["M1.01", "Source name", "03. 07. 2026.", "9", "0", "Непознато"]],
    )

    assert import_exam_schedule_main(
        [
            "--database",
            str(db_path),
            "--source",
            str(csv_path),
            "--term-code",
            "2026.06",
        ]
    ) == 0

    row = _fetch_exam_row(db_path, "M1.01")
    assert row["course_name"] == "Newer name / Older name"


def test_import_exam_schedule_ignores_courses_without_scheduled_exam(tmp_path):
    db_path = tmp_path / "exam_schedule.db"
    csv_path = tmp_path / "exam_schedule.csv"

    _init_db(db_path)
    _write_schedule_csv(
        csv_path,
        [
            ["M1.01", "Linear Algebra", "03. 07. 2026.", "9", "0", "Непознато"],
            ["M1.02", "Unscheduled Course", "", "", "0", "Непознато"],
        ],
    )

    assert import_exam_schedule_main(
        [
            "--database",
            str(db_path),
            "--source",
            str(csv_path),
            "--term-code",
            "2026.06",
        ]
    ) == 0

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT course_code FROM exam_schedule WHERE term_code = ? ORDER BY course_code",
            ("2026.06",),
        ).fetchall()
    finally:
        conn.close()

    assert rows == [("M1.01",)]


def test_import_exam_schedule_updates_changed_row_in_place(tmp_path, capsys):
    db_path = tmp_path / "exam_schedule.db"
    csv_path = tmp_path / "exam_schedule.csv"

    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO courses (name, code) VALUES (?, ?)",
            ("Linear Algebra", "M1.01"),
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
            ("2026.06", "M1.01", "Linear Algebra", "2026-07-03", 9, "A"),
        )
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO mobile_devices (device_id, student_username, device_name, platform, installation_id, enabled) VALUES (?, ?, ?, ?, ?, ?)",
            ("device-student1", "student1", "Phone", "android", "installation-id-student1", 1),
        )
        conn.commit()
    finally:
        conn.close()

    _write_schedule_csv(
        csv_path,
        [
            [
                "M1.01",
                "Linear Algebra",
                "04. 07. 2026.",
                "10",
                "0",
                "B",
            ]
        ],
    )

    assert import_exam_schedule_main(
        [
            "--database",
            str(db_path),
            "--source",
            str(csv_path),
            "--term-code",
            "2026.06",
        ]
    ) == 0
    captured = capsys.readouterr()
    assert "UPDATED=1" in captured.out
    assert "INSERTED=0" in captured.out

    row = _fetch_exam_row(db_path, "M1.01")
    assert row is not None
    assert row["exam_date"] == "2026-07-04"
    assert row["exam_hour"] == 10
    assert row["location"] == "B"


def test_import_exam_schedule_sends_push_for_changed_row(tmp_path, monkeypatch):
    db_path = tmp_path / "exam_schedule.db"
    csv_path = tmp_path / "exam_schedule.csv"

    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO courses (name, code) VALUES (?, ?)",
            ("Linear Algebra", "M1.01"),
        )
        conn.execute(
            "INSERT INTO students (username, student_index, surname, given_name) VALUES (?, ?, ?, ?)",
            ("student1", "125/1997", "Maric", "Filip"),
        )
        conn.execute(
            "INSERT INTO mobile_devices (device_id, student_username, device_name, platform, installation_id, enabled) VALUES (?, ?, ?, ?, ?, ?)",
            ("device-student1", "student1", "Phone", "android", "installation-id-student1", 1),
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
            ("2026.06", "M1.01", "Linear Algebra", "2026-07-03", 9, "A"),
        )
        subject = conn.execute(
            "INSERT INTO subjects (code, name, accreditation, module) VALUES (?, ?, ?, ?)",
            ("M1.01", "Linear Algebra", "IS", "I"),
        ).lastrowid
        conn.execute(
            "INSERT INTO course_subjects (course_code, subject_id) VALUES (?, ?)",
            ("M1.01", subject),
        )
        conn.execute(
            "INSERT INTO exam_applications (term_code, subject_id, student_username) VALUES (?, ?, ?)",
            ("2026.06", subject, "student1"),
        )
        conn.commit()
    finally:
        conn.close()

    _write_schedule_csv(
        csv_path,
        [
            [
                "M1.01",
                "Linear Algebra",
                "04. 07. 2026.",
                "10",
                "0",
                "B",
            ]
        ],
    )

    dispatched = []

    def fake_send_one_push(installation_id, title, body, notification_id, extra_data=None):
        dispatched.append((installation_id, title, body, notification_id, extra_data))
        return {"ok": True, "message_id": "test-message"}

    monkeypatch.setattr(import_exam_schedule_module, "_send_one_push", fake_send_one_push)

    assert import_exam_schedule_main(
        [
            "--database",
            str(db_path),
            "--source",
            str(csv_path),
            "--term-code",
            "2026.06",
        ]
    ) == 0

    assert len(dispatched) == 1
    assert dispatched[0][0] == "installation-id-student1"
    assert dispatched[0][1] == "Промена испита: Linear Algebra"
    assert dispatched[0][3] == 0 or dispatched[0][3] is not None
    assert dispatched[0][4]["open_mode"] == "detail"
