# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SCRIPT = REPO_ROOT / "scripts" / "import" / "import_subject_sessions.py"


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            with open(REPO_ROOT / "schema.sql", encoding="utf-8") as handle:
                conn.executescript(handle.read())
            conn.executemany(
                """
                INSERT INTO semesters (id, academic_year_start, season, start_date, end_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (3, 2025, "јесењи", "2025-10-01", "2026-02-28"),
                    (4, 2025, "пролећни", "2026-03-01", "2026-09-30"),
                ],
            )
    finally:
        conn.close()


def write_flat_csv(path):
    rows = [
        ["Ознака курса", "Назив курса", "Активност", "Наставник", "Ознака групе", "Број полазника"],
        ["15-А1.01", "Општа астрономија 1", "Предавања", "Бојан Новаковић", "1аф", "1"],
        ["15-А1.01", "Општа астрономија 1", "Вежбе", "Ђорђе Мијовић", "1аф-в", "1"],
        ["15-А2.06", "Физички принципи структуре звезда", "Предавања", "Бојан Арбутина", "4аф", "4"],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", quotechar='"', quoting=csv.QUOTE_ALL)
        writer.writerows(rows)


def run_script(args):
    return subprocess.run(
        [PYTHON, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def fetch_all(db_path, query):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def test_import_subject_sessions_imports_flat_rows(tmp_path):
    db_path = tmp_path / "allocations.db"
    csv_path = tmp_path / "grupe.csv"
    init_db(db_path)
    write_flat_csv(csv_path)

    result = run_script(
        [
            "scripts/import/import_subject_sessions.py",
            str(db_path),
            str(csv_path),
            "--year",
            "2025",
            "--semester",
            "1",
            "--schema",
            str(REPO_ROOT / "schema.sql"),
        ]
    )

    courses = [dict(row) for row in fetch_all(db_path, "SELECT code, name, semester FROM courses ORDER BY code")]
    teachers = [dict(row) for row in fetch_all(db_path, "SELECT name, username FROM teachers ORDER BY name")]
    groups = [dict(row) for row in fetch_all(db_path, "SELECT name FROM groups ORDER BY name")]
    sessions = [dict(row) for row in fetch_all(
        db_path,
        """
        SELECT c.code AS course_code, t.name AS teacher_name, cs.type, g.name AS group_name
        FROM course_sessions cs
        JOIN courses c ON c.id = cs.course_id
        JOIN teachers t ON t.id = cs.teacher_id
        JOIN session_groups sg ON sg.session_id = cs.id
        JOIN groups g ON g.id = sg.group_id
        ORDER BY cs.id
        """,
    )]

    assert courses == [
        {"code": "15-А1.01", "name": "Општа астрономија 1", "semester": 3},
        {"code": "15-А2.06", "name": "Физички принципи структуре звезда", "semester": 3},
    ]
    assert {row["name"] for row in teachers} == {"Бојан Арбутина", "Бојан Новаковић", "Ђорђе Мијовић"}
    assert [row["name"] for row in groups] == ["1аф", "1аф-в", "4аф"]
    assert sessions == [
        {"course_code": "15-А1.01", "teacher_name": "Бојан Новаковић", "type": "Предавања", "group_name": "1аф"},
        {"course_code": "15-А1.01", "teacher_name": "Ђорђе Мијовић", "type": "Вежбе", "group_name": "1аф-в"},
        {"course_code": "15-А2.06", "teacher_name": "Бојан Арбутина", "type": "Предавања", "group_name": "4аф"},
    ]
    assert "COURSES_INSERTED=2" in result.stdout
    assert "SESSIONS_INSERTED=3" in result.stdout
    assert "SESSION_GROUP_LINKS=3" in result.stdout


def test_import_subject_sessions_round_trips_exported_rows(tmp_path):
    source_db = tmp_path / "source.db"
    export_path = tmp_path / "exported.csv"
    roundtrip_db = tmp_path / "roundtrip.db"
    init_db(source_db)
    init_db(roundtrip_db)
    write_flat_csv(tmp_path / "input.csv")

    run_script(
        [
            "scripts/import/import_subject_sessions.py",
            str(source_db),
            str(tmp_path / "input.csv"),
            "--year",
            "2025",
            "--semester",
            "1",
            "--schema",
            str(REPO_ROOT / "schema.sql"),
        ]
    )
    run_script(
        [
            "scripts/export/export_subject_sessions.py",
            "--database",
            str(source_db),
            "--output",
            str(export_path),
            "--year",
            "2025",
            "--semester",
            "1",
        ]
    )
    run_script(
        [
            "scripts/import/import_subject_sessions.py",
            str(roundtrip_db),
            str(export_path),
            "--year",
            "2025",
            "--semester",
            "1",
            "--schema",
            str(REPO_ROOT / "schema.sql"),
        ]
    )

    assert fetch_all(source_db, "SELECT code, name, semester FROM courses ORDER BY code") == fetch_all(
        roundtrip_db, "SELECT code, name, semester FROM courses ORDER BY code"
    )
    assert fetch_all(source_db, "SELECT name, username FROM teachers ORDER BY name") == fetch_all(
        roundtrip_db, "SELECT name, username FROM teachers ORDER BY name"
    )
    assert fetch_all(source_db, "SELECT name FROM groups ORDER BY name") == fetch_all(
        roundtrip_db, "SELECT name FROM groups ORDER BY name"
    )
