#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Export student enrollments to a CSV file."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from semester_utils import parse_semester_display_name, semester_display_name


def _build_query(
    student_username: str | None,
    semester_filter: str | None,
) -> tuple[str, tuple[object, ...]]:
    where_clauses = ["se.subject_id IS NOT NULL"]
    params: list[object] = []

    if student_username:
        where_clauses.append("se.student_username = ?")
        params.append(student_username)
    if semester_filter:
        parsed = parse_semester_display_name(semester_filter)
        if parsed is not None:
            start_year, season = parsed
            where_clauses.append(
                "ssem.academic_year_start = ? AND ssem.season = ?"
            )
            params.extend([start_year, season])
        elif semester_filter.isdigit():
            where_clauses.append("CAST(se.semester_id AS TEXT) = ?")
            params.append(semester_filter)
        else:
            raise ValueError(
                "Semester filter must be a semester display name like '2026/27. јесењи' "
                "or a semester id"
            )

    where_sql = " AND ".join(where_clauses)
    query = f"""
        SELECT
            se.student_username,
            se.semester_id,
            ssem.academic_year_start,
            ssem.season,
            s.code AS subject_code,
            s.name AS subject_name,
            s.accreditation AS subject_accreditation,
            s.module AS subject_module,
            s.year AS subject_year,
            g.name AS group_name
        FROM student_enrollments se
        JOIN subjects s
          ON s.id = se.subject_id
        JOIN groups g
          ON g.id = se.group_id
        JOIN semesters ssem
          ON ssem.id = se.semester_id
        WHERE {where_sql}
        ORDER BY se.student_username,
                 ssem.academic_year_start,
                 CASE ssem.season
                     WHEN 'јесењи' THEN 0
                     WHEN 'пролећни' THEN 1
                     ELSE 2
                 END,
                 s.code,
                 s.accreditation,
                 s.module,
                 g.name,
                 se.id
    """
    return query, tuple(params)


def export_student_enrollments(
    database_path: Path,
    output_path: Path,
    student_username: str | None = None,
    semester_filter: str | None = None,
) -> int:
    if not database_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        query, params = _build_query(student_username, semester_filter)
        rows = cur.execute(query, params).fetchall()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "student_username",
                    "semester_name",
                    "subject_code",
                    "subject_name",
                    "subject_accreditation",
                    "subject_module",
                    "subject_year",
                    "group_name",
                ]
            )
            for row in rows:
                semester_name = semester_display_name(
                    int(row["academic_year_start"]),
                    str(row["season"]),
                )
                writer.writerow(
                    [
                        row["student_username"],
                        semester_name,
                        row["subject_code"],
                        row["subject_name"],
                        row["subject_accreditation"],
                        row["subject_module"],
                        row["subject_year"],
                        row["group_name"],
                    ]
                )
    finally:
        conn.close()

    print(f"ROWS={len(rows)}")
    print(f"OUTPUT={output_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export student enrollments to a CSV file."
    )
    parser.add_argument("--database", required=True, help="SQLite database path")
    parser.add_argument("--output", required=True, help="Path to write the exported CSV")
    parser.add_argument(
        "--student-username",
        help="Optional student username to export only one student's enrollments",
    )
    parser.add_argument(
        "--semester",
        help="Optional semester filter, either a semester display name or a semester id",
    )
    args = parser.parse_args(argv)
    return export_student_enrollments(
        Path(args.database),
        Path(args.output),
        student_username=args.student_username,
        semester_filter=args.semester,
    )


if __name__ == "__main__":
    raise SystemExit(main())
