#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Synchronize timetable entries for a given semester from a text file."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db as mydb
from semester_utils import parse_semester_display_name
from lib.timetable_common import find_session_ids, get_latest_semester_id, get_room_id, parse_line


COURSE_TYPE_TO_DATABASE = {
    "p": "п",
    "v": "в",
    "k": "к",
}


def normalize_course_type(
    cur: sqlite3.Cursor, course_type: str | None, semester_id: int
) -> str | None:
    """Use the database spelling for a course-session type when available."""
    if course_type is None:
        return None
    normalized = COURSE_TYPE_TO_DATABASE.get(course_type.casefold(), course_type)
    if normalized == course_type:
        return course_type

    # Keep compatibility with older databases that stored the Latin spelling.
    for candidate in (normalized, course_type):
        if cur.execute(
            """
            SELECT 1
            FROM course_sessions
            WHERE semester_id = ? AND type = ?
            LIMIT 1
            """,
            (semester_id, candidate),
        ).fetchone():
            return candidate
    return normalized


def clear_semester_schedule(cur: sqlite3.Cursor, semester_id: int) -> None:
    cur.execute(
        """
        DELETE FROM weekly_sessions
        WHERE session_id IN (
            SELECT id FROM course_sessions WHERE semester_id = ?
        )
        """,
        (semester_id,),
    )


def resolve_semester_id(cur: sqlite3.Cursor, semester_label: str | None) -> int:
    if not semester_label:
        return get_latest_semester_id(cur)

    parsed = parse_semester_display_name(semester_label)
    if parsed is None:
        raise ValueError(f"Invalid semester label: {semester_label!r}")

    academic_year_start, season = parsed
    row = cur.execute(
        """
        SELECT id
        FROM semesters
        WHERE academic_year_start = ? AND season = ?
        """,
        (academic_year_start, season),
    ).fetchone()
    if row is None:
        raise ValueError(f"Semester not found: {semester_label}")
    return int(row[0])


def create_course_session(
    cur: sqlite3.Cursor,
    teacher_username: str,
    course_code: str,
    course_type: str | None,
    groups: list[str],
    semester_id: int,
) -> int:
    if course_type is None:
        raise ValueError(
            f"cannot create session without course type: {teacher_username} "
            f"{course_code} ({'.'.join(groups)})"
        )

    teacher_row = cur.execute(
        "SELECT id FROM teachers WHERE username = ?", (teacher_username,)
    ).fetchone()
    if teacher_row is None:
        raise ValueError(f"unknown teacher: {teacher_username}")

    course_row = cur.execute(
        "SELECT id FROM courses WHERE code = ?", (course_code,)
    ).fetchone()
    if course_row is None:
        raise ValueError(f"unknown course: {course_code}")

    group_ids: list[int] = []
    for group_name in groups:
        group_row = cur.execute(
            "SELECT id FROM groups WHERE name = ?", (group_name,)
        ).fetchone()
        if group_row is None:
            raise ValueError(f"unknown group: {group_name}")
        group_ids.append(int(group_row[0]))

    cur.execute(
        """
        INSERT INTO course_sessions
            (course_id, teacher_id, semester_id, type, weekly_lessons)
        VALUES (?, ?, ?, ?, 0)
        """,
        (course_row[0], teacher_row[0], semester_id, course_type),
    )
    session_id = int(cur.lastrowid)
    cur.executemany(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
        [(session_id, group_id) for group_id in group_ids],
    )
    return session_id


def resolve_session_id(
    cur: sqlite3.Cursor,
    parsed,
    semester_id: int,
    create_missing: bool = False,
) -> tuple[int, bool]:
    (
        teacher_username,
        groups,
        course_code,
        course_type,
        _day_of_week,
        _start_slot,
        _end_slot,
        _room_code,
    ) = parsed

    database_course_type = normalize_course_type(cur, course_type, semester_id)
    if database_course_type == "o" and course_code.startswith("ment"):
        raise ValueError(f"ignored mentoring session: {teacher_username} {course_code}")
    session_ids = find_session_ids(
        cur,
        teacher_username,
        course_code,
        database_course_type,
        groups,
        semester_id=semester_id,
    )
    if not session_ids:
        if create_missing:
            session_id = create_course_session(
                cur,
                teacher_username,
                course_code,
                database_course_type,
                groups,
                semester_id,
            )
            return session_id, True
        raise ValueError(
            f"unknown session: {teacher_username} {course_code} ({'.'.join(groups)})"
        )
    if len(session_ids) > 1:
        raise ValueError(
            f"ambiguous session: {teacher_username} {course_code} ({'.'.join(groups)})"
        )
    return int(session_ids[0]), False


def insert_weekly_session(
    cur: sqlite3.Cursor,
    parsed,
    semester_id: int,
    meeting_no: int,
    create_missing: bool = False,
) -> tuple[int, bool]:
    (
        teacher_username,
        groups,
        course_code,
        course_type,
        day_of_week,
        start_slot,
        end_slot,
        room_code,
    ) = parsed

    room_id = get_room_id(cur, room_code)
    session_id, created = resolve_session_id(
        cur,
        parsed,
        semester_id,
        create_missing=create_missing,
    )

    cur.execute(
        """
        INSERT INTO weekly_sessions
            (session_id, meeting_no, room_id, day_of_week, start_slot, end_slot)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, meeting_no, room_id, day_of_week, start_slot, end_slot),
    )
    if created:
        cur.execute(
            "UPDATE course_sessions SET weekly_lessons = ? WHERE id = ?",
            (meeting_no, session_id),
        )
    return session_id, created


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Synchronize timetable entries for a given semester."
    )
    parser.add_argument("database", help="SQLite database path")
    parser.add_argument("source_file", help="Text file with timetable lines")
    parser.add_argument(
        "--semester",
        help="Semester display name like 2026/27. јесењи. Defaults to the latest semester.",
    )
    parser.add_argument(
        "--create-missing-sessions",
        action="store_true",
        help="Create unambiguous course sessions when the teacher, course, type, and groups exist.",
    )
    args = parser.parse_args(argv)

    source_path = Path(args.source_file)
    if not source_path.exists():
        print(f"ERROR: source file does not exist: {source_path}")
        return 2

    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row

    imported_rows = 0
    skipped_rows = 0
    seen_entries: set[tuple] = set()
    meeting_counts: dict[tuple, int] = {}

    try:
        mydb.ensure_timetable_revision_schema(conn)
        with conn:
            cur = conn.cursor()
            semester_id = resolve_semester_id(cur, args.semester)
            clear_semester_schedule(cur, semester_id)

            with source_path.open("r", encoding="utf-8") as handle:
                for index, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue

                    try:
                        parsed = parse_line(line)
                    except ValueError as exc:
                        skipped_rows += 1
                        print(f"SKIP\trow={index}\treason={exc}")
                        continue

                    seen_key = (
                        parsed[0],
                        tuple(parsed[1]),
                        *parsed[2:],
                    )
                    if seen_key in seen_entries:
                        skipped_rows += 1
                        print(f"SKIP\trow={index}\treason=duplicate timetable row")
                        continue
                    seen_entries.add(seen_key)

                    session_key = (
                        parsed[0],
                        tuple(parsed[1]),
                        parsed[2],
                        parsed[3],
                        semester_id,
                    )
                    meeting_no = meeting_counts.get(session_key, 0) + 1

                    try:
                        _session_id, created = insert_weekly_session(
                            cur,
                            parsed,
                            semester_id,
                            meeting_no,
                            create_missing=args.create_missing_sessions,
                        )
                    except ValueError as exc:
                        skipped_rows += 1
                        print(f"SKIP\trow={index}\treason={exc}")
                        continue

                    meeting_counts[session_key] = meeting_no
                    imported_rows += 1

        print(
            f"Synchronized timetable for semester {args.semester or '(latest)'} "
            f"({imported_rows} rows imported, {skipped_rows} rows skipped)"
        )
        return 0
    except Exception as exc:
        print("ERROR:", exc)
        conn.rollback()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
