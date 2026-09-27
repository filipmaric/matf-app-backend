# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import importlib
import sqlite3
from collections import OrderedDict
from pathlib import Path

from scripts.export.export_course_sessions import export_course_sessions


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
                (2, 2025, "пролећни", "2026-03-23", "2026-09-30"),
                (3, 2026, "јесењи", "2026-10-01", "2027-02-28"),
                (4, 2026, "пролећни", "2027-03-01", "2027-09-30"),
            ],
        )
        conn.executemany(
            "INSERT INTO teachers (name, username) VALUES (?, ?)",
            [
                ("Teacher A", "teacher.a"),
                ("Teacher B", "teacher.b"),
            ],
        )
        conn.executemany(
            "INSERT INTO courses (name, code, semester) VALUES (?, ?, ?)",
            [
                ("Linear Algebra", "M1.01", 3),
                ("Programming", "M2.02", 4),
                ("Old Course", "OLD1", 2),
            ],
        )
        conn.executemany(
            "INSERT INTO groups (name) VALUES (?)",
            [("1o1",), ("1o2",), ("2o1",)],
        )
        conn.commit()
    finally:
        conn.close()


def _session_snapshot(db_path, semester_names=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        params = []
        semester_clause = ""
        if semester_names is not None:
            semester_clause = "WHERE s.academic_year_start = 2026 AND s.season IN ({})".format(
                ",".join("?" for _ in semester_names)
            )
            params.extend(semester_names)
        rows = conn.execute(
            f"""
            SELECT
                cs.id AS session_id,
                s.academic_year_start AS semester_academic_year_start,
                s.season AS semester_season,
                c.code AS course_code,
                t.username AS teacher_username,
                cs.type AS session_type,
                g.name AS group_name
            FROM course_sessions cs
            JOIN courses c ON c.id = cs.course_id
            JOIN teachers t ON t.id = cs.teacher_id
            JOIN semesters s ON s.id = cs.semester_id
            LEFT JOIN session_groups sg ON sg.session_id = cs.id
            LEFT JOIN groups g ON g.id = sg.group_id
            {semester_clause}
            ORDER BY s.academic_year_start, s.season, c.code, t.username, cs.type, cs.id, g.name
            """,
            params,
        ).fetchall()
        sessions = OrderedDict()
        for row in rows:
            if row["semester_academic_year_start"] is not None and row["semester_season"]:
                semester_name = f"{int(row['semester_academic_year_start'])}/{(int(row['semester_academic_year_start']) + 1) % 100:02d}. {row['semester_season']}"
            else:
                semester_name = None
            session = sessions.setdefault(
                row["session_id"],
                {
                    "semester_name": semester_name,
                    "course_code": row["course_code"],
                    "teacher_username": row["teacher_username"],
                    "session_type": row["session_type"],
                    "group_names": [],
                },
            )
            if row["group_name"]:
                session["group_names"].append(row["group_name"])
        return [
            (
                session["semester_name"],
                session["course_code"],
                session["teacher_username"],
                session["session_type"],
                tuple(session["group_names"]),
            )
            for session in sessions.values()
        ]
    finally:
        conn.close()


def test_export_course_sessions_round_trip_through_csv(tmp_path):
    db_path = tmp_path / "course_sessions.db"
    output_path = tmp_path / "course_sessions.csv"
    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        fall_semester = conn.execute(
            "SELECT id FROM semesters WHERE academic_year_start = ? AND season = ?",
            (2026, "јесењи"),
        ).fetchone()[0]
        spring_semester = conn.execute(
            "SELECT id FROM semesters WHERE academic_year_start = ? AND season = ?",
            (2026, "пролећни"),
        ).fetchone()[0]
        old_semester = conn.execute(
            "SELECT id FROM semesters WHERE academic_year_start = ? AND season = ?",
            (2025, "пролећни"),
        ).fetchone()[0]
        teacher_a = conn.execute(
            "SELECT id FROM teachers WHERE username = ?",
            ("teacher.a",),
        ).fetchone()[0]
        teacher_b = conn.execute(
            "SELECT id FROM teachers WHERE username = ?",
            ("teacher.b",),
        ).fetchone()[0]
        course_a = conn.execute(
            "SELECT id FROM courses WHERE code = ?",
            ("M1.01",),
        ).fetchone()[0]
        course_b = conn.execute(
            "SELECT id FROM courses WHERE code = ?",
            ("M2.02",),
        ).fetchone()[0]
        old_course = conn.execute(
            "SELECT id FROM courses WHERE code = ?",
            ("OLD1",),
        ).fetchone()[0]
        group_1o1 = conn.execute("SELECT id FROM groups WHERE name = ?", ("1o1",)).fetchone()[0]
        group_1o2 = conn.execute("SELECT id FROM groups WHERE name = ?", ("1o2",)).fetchone()[0]
        group_2o1 = conn.execute("SELECT id FROM groups WHERE name = ?", ("2o1",)).fetchone()[0]

        conn.execute(
            "INSERT INTO course_sessions (course_id, teacher_id, semester_id, type) VALUES (?, ?, ?, ?)",
            (course_a, teacher_a, fall_semester, "п"),
        )
        fall_session = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.executemany(
            "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
            [
                (fall_session, group_1o1),
                (fall_session, group_1o2),
            ],
        )

        conn.execute(
            "INSERT INTO course_sessions (course_id, teacher_id, semester_id, type) VALUES (?, ?, ?, ?)",
            (course_b, teacher_b, spring_semester, "в"),
        )
        spring_session = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
            (spring_session, group_2o1),
        )

        conn.execute(
            "INSERT INTO course_sessions (course_id, teacher_id, semester_id, type) VALUES (?, ?, ?, ?)",
            (old_course, teacher_a, old_semester, "п"),
        )
        old_session = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
            (old_session, group_1o1),
        )
        conn.commit()
    finally:
        conn.close()

    original_target_sessions = _session_snapshot(
        db_path,
        ["2026/27. јесењи", "2026/27. пролећни"],
    )
    original_old_sessions = _session_snapshot(db_path, ["2025/26. пролећни"])

    assert export_course_sessions(db_path, output_path, "2026") == 0

    with output_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert "course_semester" not in rows[0]
    assert [row["teacher_username"] for row in rows] == ["teacher.a", "teacher.b"]
    assert [row["semester_name"] for row in rows] == ["2026/27. јесењи", "2026/27. пролећни"]
    assert rows[0]["group_names"] == "1o1, 1o2"
    assert rows[1]["group_names"] == "2o1"

    import_course_sessions_main = importlib.import_module(
        "scripts.import.import_course_sessions"
    ).main

    exit_code = import_course_sessions_main(
        [
            "--year",
            "2026",
            "--source",
            str(output_path),
            "--database",
            str(db_path),
            "--schema",
            str(Path(__file__).resolve().parents[1] / "schema.sql"),
        ]
    )
    assert exit_code == 0

    reimported_target_sessions = _session_snapshot(
        db_path,
        ["2026/27. јесењи", "2026/27. пролећни"],
    )
    reimported_old_sessions = _session_snapshot(db_path, ["2025/26. пролећни"])

    assert reimported_target_sessions == original_target_sessions
    assert reimported_old_sessions == original_old_sessions
