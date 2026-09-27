#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Import student enrollments from a CSV file."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import db as mydb
from semester_utils import parse_semester_display_name


REQUIRED_HEADERS = {
    "student_username",
    "semester_name",
    "subject_code",
    "subject_name",
    "subject_accreditation",
    "subject_module",
    "subject_year",
    "group_name",
}


def _normalize(value):
    return (value or "").strip()


def _record_skip(row_number, reason):
    print(f"SKIP\trow={row_number}\treason={reason}", file=sys.stderr)


def _resolve_student_username(cur, raw_value):
    value = _normalize(raw_value)
    if not value:
        raise ValueError("student_username is required")
    row = cur.execute(
        "SELECT username FROM students WHERE username = ?",
        (value,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown student {value}")
    return row[0]


def _resolve_semester_id(cur, raw_value):
    value = _normalize(raw_value)
    if not value:
        raise ValueError("semester_name is required")
    if value.isdigit():
        row = cur.execute(
            "SELECT id FROM semesters WHERE id = ?",
            (int(value),),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown semester id {value}")
        return int(row[0])
    parsed = parse_semester_display_name(value)
    if parsed is None:
        raise ValueError(f"unknown semester label: {value}")
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
        raise ValueError(f"unknown semester label: {value}")
    return int(row[0])


def _resolve_subject_id(cur, code, accreditation, module):
    code_value = _normalize(code)
    accreditation_value = _normalize(accreditation)
    module_value = _normalize(module)
    if not code_value:
        raise ValueError("subject_code is required")
    if not accreditation_value:
        raise ValueError("subject_accreditation is required")
    if not module_value:
        raise ValueError("subject_module is required")

    rows = cur.execute(
        """
        SELECT id
        FROM subjects
        WHERE code = ?
          AND lower(trim(CAST(accreditation AS TEXT))) = lower(trim(?))
          AND lower(trim(module)) = lower(trim(?))
        ORDER BY id
        """,
        (code_value, accreditation_value, module_value),
    ).fetchall()
    subject_ids = [int(row[0]) for row in rows]
    if not subject_ids:
        raise ValueError(
            f"unknown subject: code={code_value} accreditation={accreditation_value} module={module_value}"
        )
    if len(subject_ids) > 1:
        raise ValueError(
            f"ambiguous subject: code={code_value} accreditation={accreditation_value} module={module_value}"
        )
    return subject_ids[0]


def _resolve_group_id(cur, raw_value):
    value = _normalize(raw_value)
    if not value:
        raise ValueError("group_name is required")
    row = cur.execute(
        "SELECT id FROM groups WHERE name = ?",
        (value,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown group {value}")
    return int(row[0])


def _load_desired_rows(csv_path):
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = {str(name).strip() for name in (reader.fieldnames or [])}
        missing = sorted(REQUIRED_HEADERS - fieldnames)
        if missing:
            raise ValueError(
                f"{csv_path.name} is missing required columns: {', '.join(missing)}"
            )
        return list(reader)


def _collect_desired_rows(cur, rows):
    desired_rows = []
    skipped_rows = 0
    for row_number, row in enumerate(rows, start=2):
        normalized = {
            str(key).strip(): value
            for key, value in row.items()
            if key is not None
        }
        try:
            student_username = _resolve_student_username(
                cur, normalized.get("student_username")
            )
            semester_id = _resolve_semester_id(cur, normalized.get("semester_name"))
            subject_id = _resolve_subject_id(
                cur,
                normalized.get("subject_code"),
                normalized.get("subject_accreditation"),
                normalized.get("subject_module"),
            )
            group_id = _resolve_group_id(cur, normalized.get("group_name"))
            desired_rows.append(
                (
                    student_username,
                    semester_id,
                    subject_id,
                    group_id,
                )
            )
        except ValueError as exc:
            _record_skip(row_number, str(exc))
            skipped_rows += 1
    return desired_rows, skipped_rows


def _load_existing_rows(cur):
    rows = cur.execute(
        """
        SELECT id, student_username, semester_id, subject_id, group_id
        FROM student_enrollments
        ORDER BY id
        """
    ).fetchall()
    return {
        (str(row["student_username"]), int(row["semester_id"]), int(row["subject_id"])): (
            int(row["id"]),
            int(row["group_id"]),
        )
        for row in rows
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import student enrollments from CSV.")
    parser.add_argument("database", help="SQLite database path")
    parser.add_argument("csv_file", help="CSV file to import")
    args = parser.parse_args(argv)

    csv_path = Path(args.csv_file).expanduser()
    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}")
        return 1

    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            mydb.ensure_student_enrollment_schema(conn)
            mydb.ensure_timetable_revision_schema(conn)
            cur = conn.cursor()

            raw_rows = _load_desired_rows(csv_path)
            desired_rows, skipped_rows = _collect_desired_rows(cur, raw_rows)
            desired_keys = list(dict.fromkeys(desired_rows))
            desired_key_set = set(desired_keys)
            existing_rows = _load_existing_rows(cur)
            existing_key_set = set(existing_rows.keys())

            inserted_rows = 0
            updated_rows = 0
            deleted_rows = 0
            unchanged_rows = 0

            for key, (existing_id, existing_group_id) in existing_rows.items():
                if key not in desired_key_set:
                    cur.execute(
                        "DELETE FROM student_enrollments WHERE id = ?",
                        (existing_id,),
                    )
                    deleted_rows += 1

            for student_username, semester_id, subject_id, group_id in desired_keys:
                existing_entry = existing_rows.get((student_username, semester_id, subject_id))
                if existing_entry is None:
                    cur.execute(
                        """
                        INSERT INTO student_enrollments (
                            student_username, semester_id, subject_id, group_id
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (student_username, semester_id, subject_id, group_id),
                    )
                    inserted_rows += 1
                    continue

                existing_id, existing_group_id = existing_entry
                if existing_group_id != group_id:
                    cur.execute(
                        """
                        UPDATE student_enrollments
                        SET group_id = ?, updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (group_id, existing_id),
                    )
                    updated_rows += 1
                else:
                    unchanged_rows += 1

        print(
            "Synced student enrollments: "
            f"{inserted_rows} inserted, {updated_rows} updated, "
            f"{deleted_rows} deleted, {unchanged_rows} unchanged, "
            f"{skipped_rows} skipped from {csv_path}."
        )
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
