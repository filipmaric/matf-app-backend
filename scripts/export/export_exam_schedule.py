#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Export exam schedule rows at the course level."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


DEFAULT_TERM_CODE = "2026.07"


def _canonical_course_name(cur: sqlite3.Cursor, course_code: str, fallback: str) -> str:
    rows = cur.execute(
        """
        SELECT DISTINCT s.name, s.accreditation, s.id
        FROM course_subjects cs
        JOIN subjects s ON s.id = cs.subject_id
        WHERE cs.course_code = ?
        ORDER BY s.accreditation DESC, s.name ASC, s.id ASC
        """,
        (course_code,),
    ).fetchall()
    names = []
    for row in rows:
        name = " ".join(str(row[0] or "").split())
        if name and name not in names:
            names.append(name)
    return " / ".join(names) if names else fallback


def _fetch_course_rows(cur: sqlite3.Cursor, term_code: str) -> list[sqlite3.Row]:
    return cur.execute(
        """
        SELECT
            e.term_code,
            e.exam_date,
            e.exam_hour,
            e.course_code,
            e.course_name,
            COALESCE(c.requires_computers, 0) AS requires_computers,
            e.location
        FROM exam_schedule e
        LEFT JOIN courses c
          ON c.code = e.course_code
        WHERE e.term_code = ?
        ORDER BY e.course_code, e.exam_date, e.exam_hour, e.id
        """,
        (term_code,),
    ).fetchall()


def export_exam_schedule(
    database_path: Path,
    output_path: Path,
    term_code: str = DEFAULT_TERM_CODE,
) -> int:
    if not database_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    exported_rows = 0

    try:
        cur = conn.cursor()
        course_rows_data = _fetch_course_rows(cur, term_code)
        course_count = cur.execute(
            "SELECT COUNT(*) FROM exam_schedule WHERE term_code = ?",
            (term_code,),
        ).fetchone()[0]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
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
            for course_row in course_rows_data:
                writer.writerow(
                    [
                        course_row["course_code"],
                        _canonical_course_name(
                            cur,
                            course_row["course_code"],
                            course_row["course_name"],
                        ),
                        course_row["exam_date"],
                        course_row["exam_hour"],
                        course_row["requires_computers"] if course_row["requires_computers"] is not None else 0,
                        course_row["location"] or "",
                    ]
                )
                exported_rows += 1
    finally:
        conn.close()

    print(f"COURSES={course_count}")
    print(f"ROWS={exported_rows}")
    print(f"OUTPUT={output_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export exam schedule rows at the course level."
    )
    parser.add_argument(
        "--database",
        required=True,
        help="SQLite database path",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write the exported CSV",
    )
    parser.add_argument(
        "--term-code",
        required=True,
        help="Exam term code to export",
    )
    args = parser.parse_args(argv)
    return export_exam_schedule(
        Path(args.database),
        Path(args.output),
        args.term_code,
    )


if __name__ == "__main__":
    raise SystemExit(main())
