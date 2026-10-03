#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Create deterministic, evenly distributed student-group assignments for testing."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from group_metadata import infer_group_metadata


SUBJECT_GROUP_MODULES = {
    "И": ("I", None),
    "АФ": ("A", "F"),
    "АИ": ("A", "I"),
    "ММ": ("M", "M"),
    "МР": ("M", "R"),
    "МС": ("M", "S"),
    "МП": ("M", "P"),
    "МЛ": ("M", "L"),
}


def _compatible_group(subject, group):
    program, module, accreditation, study_year = infer_group_metadata(group["name"])
    expected_program, expected_module = SUBJECT_GROUP_MODULES.get(
        str(subject["module"] or "").strip(), (None, None)
    )
    if expected_program is not None and program != expected_program:
        return False
    if expected_module != module:
        return False
    return (
        str(subject["accreditation"] or "").strip()
        == str(accreditation or "").strip()
        and int(subject["year"]) == int(study_year)
    )


def synthesize(database, term_code, replace=False):
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        term = conn.execute(
            "SELECT semester_id FROM exam_terms WHERE term_code = ?",
            (term_code,),
        ).fetchone()
        if term is None:
            raise ValueError(f"Unknown exam term: {term_code}")
        semester_id = int(term["semester_id"])

        subject_rows = conn.execute(
            """
            SELECT DISTINCT a.subject_id,
                            s.accreditation,
                            s.module,
                            s.year
            FROM exam_applications a
            JOIN subjects s ON s.id = a.subject_id
            WHERE a.term_code = ?
            ORDER BY a.subject_id
            """,
            (term_code,),
        ).fetchall()
        if replace and subject_rows:
            placeholders = ",".join("?" for _ in subject_rows)
            conn.execute(
                f"DELETE FROM student_enrollments WHERE subject_id IN ({placeholders})",
                tuple(int(row["subject_id"]) for row in subject_rows),
            )
        inserted = 0
        unchanged = 0
        skipped = 0
        with conn:
            for subject_row in subject_rows:
                subject_id = int(subject_row["subject_id"])
                course_rows = conn.execute(
                    """
                    SELECT cs.course_code,
                           sessions.semester_id,
                           COUNT(DISTINCT sg.group_id) AS group_count
                    FROM course_subjects cs
                    JOIN course_sessions sessions ON sessions.course_id = (
                        SELECT id FROM courses WHERE code = cs.course_code
                    )
                    JOIN session_groups sg ON sg.session_id = sessions.id
                    WHERE cs.subject_id = ?
                    GROUP BY cs.course_code, sessions.semester_id
                    ORDER BY
                        CASE WHEN sessions.semester_id = ? THEN 0 ELSE 1 END,
                        group_count DESC,
                        cs.course_code,
                        sessions.semester_id
                    """,
                    (subject_id, semester_id),
                ).fetchall()
                if not course_rows:
                    skipped += 1
                    continue
                course_code = course_rows[0]["course_code"]
                assignment_semester_id = int(course_rows[0]["semester_id"])
                group_rows = conn.execute(
                    """
                    SELECT DISTINCT sg.group_id, g.name
                    FROM course_subjects cs
                    JOIN courses c ON c.code = cs.course_code
                    JOIN course_sessions sessions ON sessions.course_id = c.id
                    JOIN session_groups sg ON sg.session_id = sessions.id
                    JOIN groups g ON g.id = sg.group_id
                    WHERE cs.subject_id = ?
                      AND cs.course_code = ?
                      AND sessions.semester_id = ?
                    ORDER BY g.name, sg.group_id
                    """,
                    (subject_id, course_code, assignment_semester_id),
                ).fetchall()
                subject = subject_row
                group_rows = [row for row in group_rows if _compatible_group(subject, row)]
                students = conn.execute(
                    """
                    SELECT DISTINCT student_username
                    FROM exam_applications
                    WHERE term_code = ? AND subject_id = ?
                    ORDER BY student_username
                    """,
                    (term_code, subject_id),
                ).fetchall()
                if not group_rows or not students:
                    skipped += 1
                    continue
                for index, student_row in enumerate(students):
                    username = student_row["student_username"]
                    group_id = int(group_rows[index % len(group_rows)]["group_id"])
                    existing = conn.execute(
                        """
                        SELECT 1 FROM student_enrollments
                        WHERE student_username = ?
                          AND semester_id = ?
                          AND subject_id = ?
                        """,
                        (username, assignment_semester_id, subject_id),
                    ).fetchone()
                    if existing is not None:
                        unchanged += 1
                        continue
                    conn.execute(
                        """
                        INSERT INTO student_enrollments
                            (student_username, semester_id, subject_id, group_id)
                        VALUES (?, ?, ?, ?)
                        """,
                        (username, assignment_semester_id, subject_id, group_id),
                    )
                    inserted += 1
        return inserted, unchanged, skipped
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Synthesize evenly distributed student enrollments from exam applications."
    )
    parser.add_argument("database")
    parser.add_argument("term_code")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing enrollments for subjects in this term before regenerating them",
    )
    args = parser.parse_args(argv)
    try:
        inserted, unchanged, skipped = synthesize(
            args.database, args.term_code, replace=args.replace
        )
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(
        f"Synthesized enrollments for {args.term_code}: "
        f"{inserted} inserted, {unchanged} unchanged, {skipped} subjects skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
