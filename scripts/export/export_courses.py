#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Export courses for one school year together with their subjects."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from semester_utils import academic_year_label, parse_school_year_start_year, school_year_semester_ids


def normalize_text(value) -> str:
    return " ".join(str(value or "").split())


def fetch_course_rows(cur: sqlite3.Cursor, academic_year: str) -> list[sqlite3.Row]:
    start_year = parse_school_year_start_year(academic_year)
    if start_year is None:
        raise ValueError(f"Invalid academic year: {academic_year!r}")
    fall_semester_id, spring_semester_id = school_year_semester_ids(cur, academic_year)
    if fall_semester_id is None or spring_semester_id is None:
        raise ValueError(f"Missing semesters for academic year: {academic_year!r}")
    return cur.execute(
        """
        SELECT
            c.code AS course_code,
            c.name AS course_name,
            s_course.season AS course_semester_season,
            c.requires_computers AS requires_computers,
            s.code AS subject_code,
            s.name AS subject_name,
            s.accreditation AS subject_accreditation,
            s.module AS subject_module,
            s.year AS subject_year
        FROM courses c
        JOIN semesters s_course
          ON s_course.id = c.semester
        LEFT JOIN course_subjects cs
          ON cs.course_code = c.code
        LEFT JOIN subjects s
          ON s.id = cs.subject_id
        WHERE s_course.id IN (?, ?)
        ORDER BY s_course.id, c.code, s.accreditation, s.module, s.code, s.id
        """,
        (fall_semester_id, spring_semester_id),
    ).fetchall()


def export_courses(
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
        rows = fetch_course_rows(cur, academic_year)
        course_count = cur.execute(
            """
            SELECT COUNT(DISTINCT c.code)
            FROM courses c
            JOIN semesters s_course
              ON s_course.id = c.semester
            WHERE s_course.id IN (?, ?)
            """,
            school_year_semester_ids(cur, academic_year),
        ).fetchone()[0]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "course_code",
                    "course_name",
                    "course_semester",
                    "requires_computers",
                    "subject_code",
                    "subject_name",
                    "subject_accreditation",
                    "subject_module",
                    "subject_year",
                ]
            )
            for row in rows:
                writer.writerow(
                    [
                        row["course_code"],
                        row["course_name"],
                        row["course_semester_season"],
                        row["requires_computers"] if row["requires_computers"] is not None else 0,
                        row["subject_code"] or "",
                        row["subject_name"] or "",
                        row["subject_accreditation"] if row["subject_accreditation"] is not None else "",
                        row["subject_module"] or "",
                        row["subject_year"] if row["subject_year"] is not None else "",
                    ]
                )
    finally:
        conn.close()

    start_year = parse_school_year_start_year(academic_year)
    if start_year is None:
        raise ValueError(f"Invalid academic year: {academic_year!r}")
    print(f"YEAR={start_year}")
    print(f"ACADEMIC_YEAR={academic_year_label(start_year)}")
    print(f"COURSES={course_count}")
    print(f"ROWS={len(rows)}")
    print(f"OUTPUT={output_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export courses for a school year together with linked subjects."
    )
    parser.add_argument("--database", required=True, help="SQLite database path")
    parser.add_argument("--output", required=True, help="Path to write the exported CSV")
    parser.add_argument(
        "--year",
        required=True,
        help="School year start year like 2026",
    )
    args = parser.parse_args(argv)
    return export_courses(Path(args.database), Path(args.output), args.year)


if __name__ == "__main__":
    raise SystemExit(main())
