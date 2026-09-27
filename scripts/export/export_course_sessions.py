#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Export course sessions for one academic year to a CSV file."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import OrderedDict
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from semester_utils import academic_year_label, parse_school_year_start_year, semester_display_name, school_year_semester_ids


def normalize_text(value) -> str:
    return " ".join(str(value or "").split())


def fetch_course_session_rows(cur: sqlite3.Cursor, academic_year: str) -> list[sqlite3.Row]:
    start_year = parse_school_year_start_year(academic_year)
    if start_year is None:
        raise ValueError(f"Invalid academic year: {academic_year!r}")
    fall_semester_id, spring_semester_id = school_year_semester_ids(cur, academic_year)
    if fall_semester_id is None or spring_semester_id is None:
        raise ValueError(f"Missing semesters for academic year: {academic_year!r}")
    return cur.execute(
        """
        SELECT
            cs.id AS session_id,
            s.academic_year_start AS academic_year_start,
            s.season AS season,
            NULL AS semester_name,
            c.code AS course_code,
            c.name AS course_name,
            t.username AS teacher_username,
            cs.type AS session_type,
            cs.weekly_lessons,
            g.name AS group_name
        FROM course_sessions cs
        JOIN courses c ON c.id = cs.course_id
        JOIN teachers t ON t.id = cs.teacher_id
        JOIN semesters s ON s.id = cs.semester_id
        LEFT JOIN session_groups sg ON sg.session_id = cs.id
        LEFT JOIN groups g ON g.id = sg.group_id
        WHERE s.id IN (?, ?)
        ORDER BY CASE s.id
                     WHEN ? THEN 0
                     WHEN ? THEN 1
                     ELSE 2
                 END,
                 c.code, t.username, cs.type, cs.id, g.name
        """,
        (
            fall_semester_id,
            spring_semester_id,
            fall_semester_id,
            spring_semester_id,
        ),
    ).fetchall()


def export_course_sessions(
    database_path: Path,
    output_path: Path,
    academic_year: str,
) -> int:
    if not database_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        raw_rows = fetch_course_session_rows(cur, academic_year)

        sessions: "OrderedDict[int, dict[str, object]]" = OrderedDict()
        for row in raw_rows:
            session_id = int(row["session_id"])
            session = sessions.setdefault(
                session_id,
                {
                    "semester_name": row["semester_name"],
                    "academic_year_start": row["academic_year_start"],
                    "season": row["season"],
                    "course_code": row["course_code"],
                    "course_name": row["course_name"],
                    "teacher_username": row["teacher_username"],
                    "session_type": row["session_type"],
                    "weekly_lessons": row["weekly_lessons"],
                    "group_names": [],
                },
            )
            if session["semester_name"] is None and row["academic_year_start"] is not None and row["season"]:
                session["semester_name"] = semester_display_name(
                    int(row["academic_year_start"]),
                    str(row["season"]),
                )
            group_name = normalize_text(row["group_name"])
            if group_name and group_name not in session["group_names"]:
                session["group_names"].append(group_name)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "teacher_username",
                    "course_code",
                    "course_name",
                    "semester_name",
                    "type",
                    "weekly_lessons",
                    "group_names",
                ]
            )
            for session in sessions.values():
                semester_name = session["semester_name"]
                if session["academic_year_start"] is not None and session["season"]:
                    semester_name = semester_display_name(
                        int(session["academic_year_start"]),
                        str(session["season"]),
                    )
                writer.writerow(
                    [
                        session["teacher_username"],
                        session["course_code"],
                        session["course_name"],
                        semester_name,
                        session["session_type"],
                        session["weekly_lessons"],
                        ", ".join(session["group_names"]),
                    ]
                )
    finally:
        conn.close()

    start_year = parse_school_year_start_year(academic_year)
    if start_year is None:
        raise ValueError(f"Invalid academic year: {academic_year!r}")
    print(f"YEAR={start_year}")
    print(f"ACADEMIC_YEAR={academic_year_label(start_year)}")
    print(f"SESSIONS={len(sessions)}")
    print(f"OUTPUT={output_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export course sessions for one academic year to a CSV file."
    )
    parser.add_argument("--database", required=True, help="SQLite database path")
    parser.add_argument("--output", required=True, help="Path to write the exported CSV")
    parser.add_argument(
        "--year",
        required=True,
        help="School year start year like 2026",
    )
    args = parser.parse_args(argv)
    return export_course_sessions(Path(args.database), Path(args.output), args.year)


if __name__ == "__main__":
    raise SystemExit(main())
