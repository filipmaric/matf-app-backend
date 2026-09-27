#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Export flat subject sessions to the `subject_sessions_*.csv` format."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from semester_utils import academic_year_label, parse_school_year_start_year, semester_id_for_academic_year_and_season


HEADER = [
    "Ознака курса",
    "Назив курса",
    "Активност",
    "Наставник",
    "Ознака групе",
    "Број полазника",
]
SEMESTER_ORDINAL = {"јесењи": 1, "пролећни": 2}
VALID_SEASONS = {"јесењи", "пролећни"}


def normalize_text(value) -> str:
    return " ".join(str(value or "").split())


def resolve_season(value: str) -> str:
    normalized = normalize_text(value).casefold()
    if normalized in {"1", "јесењи", "jesenji", "fall", "autumn"}:
        return "јесењи"
    if normalized in {"2", "пролећни", "prolecni", "spring"}:
        return "пролећни"
    raise ValueError(f"Invalid semester value: {value!r}")


def fetch_rows(cur: sqlite3.Cursor, semester_id: int) -> list[sqlite3.Row]:
    return cur.execute(
        """
        SELECT
            cs.id AS session_id,
            c.code AS course_code,
            c.name AS course_name,
            cs.type AS activity,
            t.name AS teacher_name,
            g.name AS group_name,
            g.id AS group_id
        FROM course_sessions cs
        JOIN courses c ON c.id = cs.course_id
        JOIN teachers t ON t.id = cs.teacher_id
        JOIN session_groups sg ON sg.session_id = cs.id
        JOIN groups g ON g.id = sg.group_id
        WHERE cs.semester_id = ?
        ORDER BY cs.id, g.name
        """,
        (semester_id,),
    ).fetchall()


def export_subject_sessions(
    database_path: Path,
    output_path: Path,
    academic_year: str,
    semester: str,
) -> int:
    if not database_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")

    start_year = parse_school_year_start_year(academic_year)
    if start_year is None:
        raise ValueError(f"Invalid academic year: {academic_year!r}")
    season = resolve_season(semester)

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        semester_id = semester_id_for_academic_year_and_season(cur, str(start_year), season)
        if semester_id is None:
            raise ValueError(f"Missing semester: {academic_year_label(start_year)}. {season}")

        rows = fetch_rows(cur, semester_id)
        counts = {
            int(row[0]): int(row[1])
            for row in cur.execute(
                """
                SELECT group_id, COUNT(*) AS student_count
                FROM student_enrollments
                WHERE semester_id = ?
                GROUP BY group_id
                """,
                (semester_id,),
            ).fetchall()
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", quotechar='"', quoting=csv.QUOTE_ALL)
            title = f"Групе у {SEMESTER_ORDINAL[season]}. семестру {start_year}/{start_year + 1}. године"
            writer.writerow([title])
            writer.writerow(HEADER)
            for row in rows:
                writer.writerow(
                    [
                        row["course_code"],
                        row["course_name"],
                        row["activity"],
                        row["teacher_name"],
                        row["group_name"],
                        counts.get(int(row["group_id"]), 0),
                    ]
                )
    finally:
        conn.close()

    print(f"YEAR={start_year}")
    print(f"ACADEMIC_YEAR={academic_year_label(start_year)}")
    print(f"SEMESTER={season}")
    print(f"ROWS={len(rows)}")
    print(f"OUTPUT={output_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export flat subject sessions to the subject_sessions_*.csv format."
    )
    parser.add_argument("--database", required=True, help="SQLite database path")
    parser.add_argument("--output", required=True, help="Path to write the exported CSV")
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
    args = parser.parse_args(argv)
    return export_subject_sessions(
        Path(args.database),
        Path(args.output),
        args.year,
        args.semester,
    )


if __name__ == "__main__":
    raise SystemExit(main())
