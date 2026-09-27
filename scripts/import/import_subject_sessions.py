#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Import flat subject session CSV files in the `subject_sessions_*.csv` format."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semester_utils import academic_year_label, semester_id_for_academic_year_and_season
from lib.timetable_common import get_or_create_group


HEADER = [
    "Ознака курса",
    "Назив курса",
    "Активност",
    "Наставник",
    "Ознака групе",
    "Број полазника",
]
VALID_ACTIVITIES = {"Предавања", "Вежбе", "Практикум", "СИ"}


def normalize_text(value) -> str:
    return " ".join(str(value or "").split())


def ensure_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    has_courses = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'courses'"
    ).fetchone()
    if has_courses:
        return
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    conn.executescript(schema_path.read_text(encoding="utf-8"))


def resolve_season(value: str) -> str:
    normalized = normalize_text(value).casefold()
    if normalized in {"1", "јесењи", "jesenji", "fall", "autumn"}:
        return "јесењи"
    if normalized in {"2", "пролећни", "prolecni", "spring"}:
        return "пролећни"
    raise ValueError(f"Invalid semester value: {value!r}")


def load_rows(csv_path: Path) -> list[list[str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", quotechar='"')
        rows = [
            [normalize_text(cell) for cell in row]
            for row in reader
            if any(normalize_text(cell) for cell in row)
        ]

    if not rows:
        raise ValueError(f"{csv_path}: missing header row")

    if rows[0] == HEADER:
        return rows[1:]

    if len(rows) >= 2 and rows[1] == HEADER:
        return rows[2:]

    raise ValueError(f"{csv_path}: unexpected header row: {rows[0]!r}")


def resolve_teacher_id(cur: sqlite3.Cursor, teacher_name: str) -> int:
    normalized = normalize_text(teacher_name)
    if not normalized:
        raise ValueError("teacher name is required")
    row = cur.execute(
        """
        SELECT id
        FROM teachers
        WHERE trim(name) = ?
        ORDER BY username IS NULL, id
        LIMIT 1
        """,
        (normalized,),
    ).fetchone()
    if row is not None:
        return int(row[0])
    cur.execute(
        "INSERT INTO teachers (name, username) VALUES (?, NULL)",
        (normalized,),
    )
    return int(cur.lastrowid)


def upsert_course(cur: sqlite3.Cursor, course_code: str, course_name: str, semester_id: int) -> int:
    code = normalize_text(course_code)
    name = normalize_text(course_name)
    if not code:
        raise ValueError("course code is required")
    if not name:
        raise ValueError("course name is required")

    row = cur.execute(
        "SELECT id, name, semester FROM courses WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO courses (name, code, semester) VALUES (?, ?, ?)",
            (name, code, semester_id),
        )
        return int(cur.lastrowid)

    course_id = int(row[0])
    updates = []
    params: list[object] = []
    if normalize_text(row[1]) != name:
        updates.append("name = ?")
        params.append(name)
    if int(row[2]) != semester_id:
        updates.append("semester = ?")
        params.append(semester_id)
    if updates:
        params.append(course_id)
        cur.execute(
            f"UPDATE courses SET {', '.join(updates)} WHERE id = ?",
            params,
        )
    return course_id


def import_subject_sessions(
    database_path: Path,
    csv_path: Path,
    schema_path: Path,
    academic_year: str,
    semester: str,
) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    rows = load_rows(csv_path)
    start_year = int(academic_year)
    season = resolve_season(semester)

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn, schema_path)
        semester_id = semester_id_for_academic_year_and_season(
            conn.cursor(),
            str(start_year),
            season,
        )
        if semester_id is None:
            raise ValueError(
                f"Missing semester for {academic_year_label(start_year)}. {season}"
            )

        inserted_courses = 0
        updated_courses = 0
        inserted_sessions = 0
        inserted_links = 0
        skipped_rows = 0
        seen_rows: set[tuple[str, str, str, str]] = set()

        with conn:
            cur = conn.cursor()
            for row_number, row in enumerate(rows, start=3):
                if len(row) < len(HEADER):
                    print(
                        f"SKIP\trow={row_number}\treason=missing columns",
                        file=sys.stderr,
                    )
                    skipped_rows += 1
                    continue

                course_code = normalize_text(row[0])
                course_name = normalize_text(row[1])
                activity = normalize_text(row[2])
                teacher_name = normalize_text(row[3])
                group_name = normalize_text(row[4])

                if not course_code or not course_name or not activity or not teacher_name or not group_name:
                    print(
                        f"SKIP\trow={row_number}\treason=missing required value",
                        file=sys.stderr,
                    )
                    skipped_rows += 1
                    continue
                if activity not in VALID_ACTIVITIES:
                    print(
                        f"SKIP\trow={row_number}\treason=invalid activity: {activity}",
                        file=sys.stderr,
                    )
                    skipped_rows += 1
                    continue

                row_key = (course_code, activity, teacher_name, group_name)
                if row_key in seen_rows:
                    print(
                        f"SKIP\trow={row_number}\treason=duplicate row",
                        file=sys.stderr,
                    )
                    skipped_rows += 1
                    continue
                seen_rows.add(row_key)

                course_row = cur.execute(
                    "SELECT id, name, semester FROM courses WHERE code = ?",
                    (course_code,),
                ).fetchone()
                if course_row is None:
                    inserted_courses += 1
                else:
                    if normalize_text(course_row["name"]) != course_name or int(course_row["semester"]) != semester_id:
                        updated_courses += 1

                course_id = upsert_course(cur, course_code, course_name, semester_id)
                teacher_id = resolve_teacher_id(cur, teacher_name)
                group_id = get_or_create_group(cur, group_name)

                existing_session = cur.execute(
                    """
                    SELECT cs.id
                    FROM course_sessions cs
                    JOIN session_groups sg ON sg.session_id = cs.id
                    WHERE cs.course_id = ?
                      AND cs.teacher_id = ?
                      AND cs.semester_id = ?
                      AND cs.type = ?
                      AND sg.group_id = ?
                    """,
                    (course_id, teacher_id, semester_id, activity, group_id),
                ).fetchone()
                if existing_session is not None:
                    continue

                cur.execute(
                    """
                    INSERT INTO course_sessions (course_id, teacher_id, semester_id, type)
                    VALUES (?, ?, ?, ?)
                    """,
                    (course_id, teacher_id, semester_id, activity),
                )
                session_id = int(cur.lastrowid)
                inserted_sessions += 1
                cur.execute(
                    "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
                    (session_id, group_id),
                )
                inserted_links += 1
    finally:
        conn.close()

    print(f"YEAR={start_year}")
    print(f"ACADEMIC_YEAR={academic_year_label(start_year)}")
    print(f"SEMESTER={season}")
    print(f"COURSES_INSERTED={inserted_courses}")
    print(f"COURSES_UPDATED={updated_courses}")
    print(f"SESSIONS_INSERTED={inserted_sessions}")
    print(f"SESSION_GROUP_LINKS={inserted_links}")
    print(f"SKIPPED={skipped_rows}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import flat subject sessions from a subject_sessions_*.csv file."
    )
    parser.add_argument("database", help="SQLite database path")
    parser.add_argument("csv_file", help="Flat subject_sessions_*.csv file to import")
    parser.add_argument(
        "--year",
        required=True,
        help="School year start year like 2025",
    )
    parser.add_argument(
        "--semester",
        required=True,
        help="Semester selector: 1, 2, јесењи, or пролећни",
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="Path to backend/schema.sql used when the database is empty",
    )
    args = parser.parse_args(argv)

    try:
        return import_subject_sessions(
            Path(args.database),
            Path(args.csv_file).expanduser(),
            Path(args.schema),
            args.year,
            args.semester,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
