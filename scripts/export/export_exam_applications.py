#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Export exam applications for one exam term to a CSV file."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import OrderedDict
from pathlib import Path


def _fetch_application_rows(cur: sqlite3.Cursor, term_code: str) -> list[sqlite3.Row]:
    return cur.execute(
        """
        SELECT
            a.id AS application_id,
            a.term_code,
            a.student_username,
            s.accreditation,
            s.module,
            e.course_code
        FROM exam_applications a
        JOIN subjects s
          ON s.id = a.subject_id
        LEFT JOIN course_subjects cs
          ON cs.subject_id = s.id
        LEFT JOIN exam_schedule e
          ON e.term_code = a.term_code
         AND e.course_code = cs.course_code
        WHERE a.term_code = ?
        ORDER BY a.id, e.course_code
        """,
        (term_code,),
    ).fetchall()


def export_exam_applications(
    database_path: Path,
    output_path: Path,
    term_code: str,
) -> int:
    if not database_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    exported_rows = 0
    applications: "OrderedDict[int, dict[str, object]]" = OrderedDict()

    try:
        cur = conn.cursor()
        rows = _fetch_application_rows(cur, term_code)
        if not rows:
            print(f"TERM={term_code}")
            print("ROWS=0")
            print(f"OUTPUT={output_path}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "Шифра курса",
                        "Акредитација",
                        "Модул",
                        "Корисничко име",
                    ]
                )
            return 0

        for row in rows:
            application_id = int(row["application_id"])
            app = applications.setdefault(
                application_id,
                {
                    "term_code": row["term_code"],
                    "student_username": row["student_username"],
                    "accreditation": row["accreditation"],
                    "module": row["module"],
                    "course_codes": [],
                },
            )
            course_code = row["course_code"]
            if course_code is None:
                continue
            course_code = str(course_code).strip()
            if course_code and course_code not in app["course_codes"]:
                app["course_codes"].append(course_code)

        output_rows: list[tuple[str, str, str, str]] = []
        for application_id, app in applications.items():
            course_codes = app["course_codes"]
            if not course_codes:
                raise ValueError(
                    f"Cannot determine course code for exam application {application_id}"
                )
            if len(course_codes) > 1:
                raise ValueError(
                    "Ambiguous course code for exam application "
                    f"{application_id}: {', '.join(course_codes)}"
                )
            output_rows.append(
                (
                    course_codes[0],
                    str(app["accreditation"]),
                    str(app["module"]),
                    str(app["student_username"]),
                )
            )

        output_rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "Шифра курса",
                    "Акредитација",
                    "Модул",
                    "Корисничко име",
                ]
            )
            for row in output_rows:
                writer.writerow(row)
                exported_rows += 1
    finally:
        conn.close()

    print(f"TERM={term_code}")
    print(f"ROWS={exported_rows}")
    print(f"OUTPUT={output_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export exam applications to a CSV file.")
    parser.add_argument("database", help="SQLite database path")
    parser.add_argument("term_code", help="Exam term code to export")
    parser.add_argument("csv_file", help="CSV file path to write")
    args = parser.parse_args(argv)
    return export_exam_applications(Path(args.database), Path(args.csv_file), args.term_code)


if __name__ == "__main__":
    raise SystemExit(main())
