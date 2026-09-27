# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import datetime as dt
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def init_timetable_db(db_path, target_day=None):
    if target_day is None:
        target_day = dt.date(2026, 3, 10)

    conn = sqlite3.connect(db_path)
    with conn:
        with open(REPO_ROOT / "schema.sql", encoding="utf-8") as f:
            conn.executescript(f.read())

        conn.execute(
            """
            INSERT INTO rooms (name, capacity, type, building_name, code, priority)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Room 406", 50, "lecture", "A", "406", 1),
        )
        conn.execute(
            """
            INSERT INTO rooms (name, capacity, type, building_name, code, priority)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Room 407", 50, "lecture", "A", "407", 2),
        )
        conn.execute(
            """
            INSERT INTO semesters (academic_year_start, season, start_date, end_date)
            VALUES (?, ?, ?, ?)
            """,
            (2025, "пролећни", "2026-03-23", "2026-09-30"),
        )
        conn.execute(
            """
            INSERT INTO days (date, kind, week_day)
            VALUES (?, ?, ?)
            """,
            (target_day.isoformat(), "teaching", target_day.weekday()),
        )
    conn.close()


def seed_timetable_entities(db_path, teachers=(), courses=(), groups=()):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for username, name in teachers:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO teachers (username, name)
                    VALUES (?, ?)
                    """,
                    (username, name),
                )
            for code, name, semester in courses:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO courses (code, name, semester)
                    VALUES (?, ?, ?)
                    """,
                    (code, name, semester),
                )
            for group_name in groups:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO groups (name)
                    VALUES (?)
                    """,
                    (group_name,),
                )
    finally:
        conn.close()


def seed_timetable_sessions(db_path, sessions=()):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for teacher_username, course_code, semester_id, session_type, group_names in sessions:
                teacher_id = conn.execute(
                    "SELECT id FROM teachers WHERE username = ?",
                    (teacher_username,),
                ).fetchone()[0]
                course_id = conn.execute(
                    "SELECT id FROM courses WHERE code = ?",
                    (course_code,),
                ).fetchone()[0]
                session_id = conn.execute(
                    """
                    INSERT INTO course_sessions (course_id, teacher_id, semester_id, type)
                    VALUES (?, ?, ?, ?)
                    """,
                    (course_id, teacher_id, semester_id, session_type),
                ).lastrowid
                for group_name in group_names:
                    group_id = conn.execute(
                        "SELECT id FROM groups WHERE name = ?",
                        (group_name,),
                    ).fetchone()[0]
                    conn.execute(
                        """
                        INSERT INTO session_groups (session_id, group_id)
                        VALUES (?, ?)
                        """,
                        (session_id, group_id),
                    )
    finally:
        conn.close()


def run_script(args, input_text=None):
    return subprocess.run(
        [PYTHON, *args],
        cwd=REPO_ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
    )


def fetch_one(db_path, query):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query).fetchone()
    finally:
        conn.close()


def fetch_all(db_path, query):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def write_timetable(path, text):
    path.write_text(text, encoding="utf-8")


def test_import_timetable_replaces_existing_schedule(tmp_path):
    db_path = tmp_path / "timetable.db"
    timetable = tmp_path / "timetable.txt"

    init_timetable_db(db_path)
    seed_timetable_entities(
        db_path,
        teachers=[("profuser", "Prof Full Name")],
        courses=[("MAT1", "Mathematics 1", 1), ("ALG1", "Algebra 1", 1)],
        groups=["3A"],
    )
    seed_timetable_sessions(
        db_path,
        sessions=[
            ("profuser", "MAT1", 1, "p", ["3A"]),
            ("profuser", "ALG1", 1, "p", ["3A"]),
        ],
    )

    write_timetable(timetable, "profuser_3A_MAT1.p_pon_8_9_406\n")
    run_script(["scripts/import/import_timetable.py", str(db_path), str(timetable)])

    row = fetch_one(
        db_path,
        """
        SELECT c.code, ws.day_of_week, ws.start_slot, ws.end_slot, r.code AS room_code
        FROM weekly_sessions ws
        JOIN course_sessions cs ON cs.id = ws.session_id
        JOIN courses c ON c.id = cs.course_id
        JOIN rooms r ON r.id = ws.room_id
        """,
    )
    assert row["code"] == "MAT1"
    assert row["day_of_week"] == 0
    assert row["start_slot"] == 8
    assert row["end_slot"] == 9
    assert row["room_code"] == "406"

    write_timetable(timetable, "profuser_3A_ALG1.p_uto_10_11_407\n")
    run_script(["scripts/import/import_timetable.py", str(db_path), str(timetable)])

    weekly_sessions = fetch_all(db_path, "SELECT * FROM weekly_sessions")
    course_sessions = fetch_all(db_path, "SELECT * FROM course_sessions")

    assert len(weekly_sessions) == 1
    assert len(course_sessions) == 2

    row = fetch_one(
        db_path,
        """
        SELECT c.code, ws.day_of_week, ws.start_slot, ws.end_slot, r.code AS room_code
        FROM weekly_sessions ws
        JOIN course_sessions cs ON cs.id = ws.session_id
        JOIN courses c ON c.id = cs.course_id
        JOIN rooms r ON r.id = ws.room_id
        """,
    )
    assert row["code"] == "ALG1"
    assert row["day_of_week"] == 1
    assert row["start_slot"] == 10
    assert row["end_slot"] == 11
    assert row["room_code"] == "407"


def test_import_timetable_accepts_teacher_office_room(tmp_path):
    db_path = tmp_path / "timetable.db"
    timetable = tmp_path / "timetable.txt"

    init_timetable_db(db_path)
    seed_timetable_entities(
        db_path,
        teachers=[("profuser", "Prof Full Name")],
        courses=[("MAT1", "Mathematics 1", 1)],
        groups=["3A"],
    )
    seed_timetable_sessions(
        db_path,
        sessions=[("profuser", "MAT1", 1, "p", ["3A"])],
    )

    write_timetable(timetable, "profuser_3A_MAT1.p_pon_8_9_kab\n")
    run_script(["scripts/import/import_timetable.py", str(db_path), str(timetable)])

    row = fetch_one(
        db_path,
        """
        SELECT r.code, r.type
        FROM weekly_sessions ws
        JOIN rooms r ON r.id = ws.room_id
        """,
    )
    assert row["code"] == "kab"
    assert row["type"] == "teacher_office"


def test_import_timetable_normalizes_latin_course_type_to_database_type(tmp_path):
    db_path = tmp_path / "timetable.db"
    timetable = tmp_path / "timetable.txt"

    init_timetable_db(db_path)
    seed_timetable_entities(
        db_path,
        teachers=[("profuser", "Prof Full Name")],
        courses=[("М5.01", "Probability", 1)],
        groups=["3A"],
    )
    seed_timetable_sessions(
        db_path,
        sessions=[("profuser", "М5.01", 1, "п", ["3A"])],
    )
    write_timetable(timetable, "profuser_3A_М5.01.p_pon_8_9_406\n")

    result = run_script(["scripts/import/import_timetable.py", str(db_path), str(timetable)])

    assert "(1 rows imported, 0 rows skipped)" in result.stdout


def test_import_timetable_can_create_missing_session(tmp_path):
    db_path = tmp_path / "timetable.db"
    timetable = tmp_path / "timetable.txt"

    init_timetable_db(db_path)
    seed_timetable_entities(
        db_path,
        teachers=[("assistant", "Assistant")],
        courses=[("MAT1", "Mathematics 1", 1)],
        groups=["3A"],
    )
    write_timetable(timetable, "assistant_3A_MAT1.p_pon_8_9_406\n")

    result = run_script(
        [
            "scripts/import/import_timetable.py",
            str(db_path),
            str(timetable),
            "--create-missing-sessions",
        ]
    )

    assert "(1 rows imported, 0 rows skipped)" in result.stdout
    row = fetch_one(
        db_path,
        """
        SELECT cs.type, cs.weekly_lessons, g.name
        FROM course_sessions cs
        JOIN session_groups sg ON sg.session_id = cs.id
        JOIN groups g ON g.id = sg.group_id
        """,
    )
    assert (row["type"], row["weekly_lessons"], row["name"]) == ("п", 1, "3A")


def test_import_timetable_matches_session_with_extra_groups(tmp_path):
    db_path = tmp_path / "timetable.db"
    timetable = tmp_path / "timetable.txt"

    init_timetable_db(db_path)
    seed_timetable_entities(
        db_path,
        teachers=[("profuser", "Prof Full Name")],
        courses=[("MAT1", "Mathematics 1", 1)],
        groups=["3A", "3B"],
    )
    seed_timetable_sessions(
        db_path,
        sessions=[("profuser", "MAT1", 1, "p", ["3A", "3B"])],
    )
    write_timetable(timetable, "profuser_3A_MAT1.p_pon_8_9_406\n")

    result = run_script(["scripts/import/import_timetable.py", str(db_path), str(timetable)])

    assert "(1 rows imported, 0 rows skipped)" in result.stdout


def test_import_timetable_supports_other_session_type(tmp_path):
    db_path = tmp_path / "timetable.db"
    timetable = tmp_path / "timetable.txt"

    init_timetable_db(db_path)
    seed_timetable_entities(
        db_path,
        teachers=[("seminar.t", "Seminar")],
        courses=[("sem1", "Seminar 1", 2)],
        groups=["sem1"],
    )
    write_timetable(timetable, "seminar.t_sem1_sem1.o_pon_8_9_kab\n")

    result = run_script(
        [
            "scripts/import/import_timetable.py",
            str(db_path),
            str(timetable),
            "--create-missing-sessions",
        ]
    )

    assert "(1 rows imported, 0 rows skipped)" in result.stdout
    row = fetch_one(db_path, "SELECT type FROM course_sessions")
    assert row["type"] == "o"


def test_import_timetable_numbers_multiple_weekly_sessions(tmp_path):
    db_path = tmp_path / "timetable.db"
    timetable = tmp_path / "timetable.txt"

    init_timetable_db(db_path)
    seed_timetable_entities(
        db_path,
        teachers=[("profuser", "Prof Full Name")],
        courses=[("MAT1", "Mathematics 1", 1)],
        groups=["3A"],
    )
    seed_timetable_sessions(
        db_path,
        sessions=[("profuser", "MAT1", 1, "p", ["3A"])],
    )

    write_timetable(
        timetable,
        "\n".join(
            [
                "profuser_3A_MAT1.p_pon_8_9_406",
                "profuser_3A_MAT1.p_uto_10_11_407",
            ]
        )
        + "\n",
    )

    run_script(["scripts/import/import_timetable.py", str(db_path), str(timetable)])

    rows = fetch_all(
        db_path,
        """
        SELECT meeting_no, day_of_week, start_slot, end_slot, r.code AS room_code
        FROM weekly_sessions ws
        JOIN rooms r ON r.id = ws.room_id
        ORDER BY meeting_no
        """,
    )
    assert [
        (row["meeting_no"], row["day_of_week"], row["start_slot"], row["end_slot"], row["room_code"])
        for row in rows
    ] == [
        (1, 0, 8, 9, "406"),
        (2, 1, 10, 11, "407"),
    ]


def test_import_timetable_targets_requested_semester(tmp_path):
    db_path = tmp_path / "timetable.db"
    timetable = tmp_path / "timetable.txt"

    init_timetable_db(db_path)
    seed_timetable_entities(
        db_path,
        teachers=[("profuser", "Prof Full Name"), ("existing.teacher", "Existing Teacher")],
        courses=[("MAT1", "Mathematics 1", 1), ("OLD1", "Existing Course", 3)],
        groups=["3A"],
    )

    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO semesters (academic_year_start, season, start_date, end_date)
            VALUES (?, ?, ?, ?)
            """,
            (2026, "јесењи", "2026-10-01", "2027-02-28"),
        )
        fall_semester_id = conn.execute(
            """
            SELECT id
            FROM semesters
            WHERE academic_year_start = ? AND season = ?
            """,
            (2026, "јесењи"),
        ).fetchone()[0]
        teacher_id = conn.execute(
            "SELECT id FROM teachers WHERE username = ?",
            ("existing.teacher",),
        ).fetchone()[0]
        course_id = conn.execute(
            "SELECT id FROM courses WHERE code = ?",
            ("OLD1",),
        ).fetchone()[0]
        session_id = conn.execute(
            """
            INSERT INTO course_sessions (course_id, teacher_id, semester_id, type)
            VALUES (?, ?, ?, ?)
            """,
            (course_id, teacher_id, fall_semester_id, "п"),
        ).lastrowid
        room_id = conn.execute("SELECT id FROM rooms WHERE code = ?", ("407",)).fetchone()[0]
        conn.execute(
            """
            INSERT INTO weekly_sessions (session_id, room_id, day_of_week, start_slot, end_slot)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, room_id, 2, 12, 14),
        )
    conn.close()
    seed_timetable_sessions(
        db_path,
        sessions=[
            ("profuser", "MAT1", 1, "p", ["3A"]),
        ],
    )

    write_timetable(timetable, "profuser_3A_MAT1.p_pon_8_9_406\n")
    run_script(
        [
            "scripts/import/import_timetable.py",
            str(db_path),
            str(timetable),
            "--semester",
            "2025/26. пролећни",
        ]
    )

    rows = fetch_all(
        db_path,
        """
        SELECT s.academic_year_start, s.season, c.code, ws.day_of_week, ws.start_slot, ws.end_slot, r.code AS room_code
        FROM weekly_sessions ws
        JOIN course_sessions cs ON cs.id = ws.session_id
        JOIN courses c ON c.id = cs.course_id
        JOIN semesters s ON s.id = cs.semester_id
        JOIN rooms r ON r.id = ws.room_id
        ORDER BY s.academic_year_start, s.season, c.code
        """,
    )

    assert [
        (row["academic_year_start"], row["season"], row["code"], row["day_of_week"], row["start_slot"], row["end_slot"], row["room_code"])
        for row in rows
    ] == [
        (2025, "пролећни", "MAT1", 0, 8, 9, "406"),
        (2026, "јесењи", "OLD1", 2, 12, 14, "407"),
    ]


def test_import_timetable_skips_unknown_rows(tmp_path):
    db_path = tmp_path / "timetable.db"
    timetable = tmp_path / "timetable.txt"

    init_timetable_db(db_path)
    seed_timetable_entities(
        db_path,
        teachers=[("profuser", "Prof Full Name")],
        courses=[("MAT1", "Mathematics 1", 1)],
        groups=["3A"],
    )
    seed_timetable_sessions(
        db_path,
        sessions=[("profuser", "MAT1", 1, "p", ["3A"])],
    )

    write_timetable(
        timetable,
        "\n".join(
            [
                "profuser_3A_MAT1.p_pon_8_9_406",
                "badline",
                "ghost_3A_MAT1.p_pon_8_9_406",
                "profuser_ghost_MAT1.p_pon_8_9_406",
                "profuser_3A_UNKNOWN.p_pon_8_9_406",
                "profuser_3A_MAT1.p_pon_8_9_999",
                "profuser_3A_MAT1.p_pon_8_9_406",
            ]
        )
        + "\n",
    )

    result = run_script([
        "scripts/import/import_timetable.py",
        str(db_path),
        str(timetable),
    ])

    assert "SKIP\trow=2\treason=Invalid format: badline" in result.stdout
    assert "SKIP\trow=3\treason=unknown session: ghost MAT1 (3A)" in result.stdout
    assert "SKIP\trow=4\treason=unknown session: profuser MAT1 (ghost)" in result.stdout
    assert "SKIP\trow=5\treason=unknown session: profuser UNKNOWN (3A)" in result.stdout
    assert "SKIP\trow=6\treason=Room not found: 999" in result.stdout
    assert "SKIP\trow=7\treason=duplicate timetable row" in result.stdout
    assert "Synchronized timetable for semester (latest) (1 rows imported, 6 rows skipped)" in result.stdout

    rows = fetch_all(
        db_path,
        """
        SELECT c.code, ws.day_of_week, ws.start_slot, ws.end_slot, r.code AS room_code
        FROM weekly_sessions ws
        JOIN course_sessions cs ON cs.id = ws.session_id
        JOIN courses c ON c.id = cs.course_id
        JOIN rooms r ON r.id = ws.room_id
        """,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "MAT1"
    assert row["day_of_week"] == 0
    assert row["start_slot"] == 8
    assert row["end_slot"] == 9
    assert row["room_code"] == "406"


def test_import_students_populates_directory(tmp_path):
    db_path = tmp_path / "students.db"
    csv_path = tmp_path / "students.csv"

    with csv_path.open("w", encoding="utf-16", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Индекс", "Презиме", "Име", "Кориснички налог"])
        writer.writerow(["1140/2025", "Agildere", "Fritz Ali", "em251140"])
        writer.writerow(["2020/2022", "Elmarghani", "Rowaida", "pd222020"])

    result = run_script(
        [
            "scripts/import/import_students.py",
            str(db_path),
            "--csv-file",
            str(csv_path),
        ]
    )
    assert "Imported 2 students" in result.stdout

    rows = fetch_all(
        db_path,
        """
        SELECT username, student_index, surname, given_name
        FROM students
        ORDER BY username
        """,
    )
    assert len(rows) == 2
    assert rows[0]["username"] == "em251140"
    assert rows[0]["student_index"] == "1140/2025"
    assert rows[0]["surname"] == "Agildere"
    assert rows[0]["given_name"] == "Fritz Ali"
