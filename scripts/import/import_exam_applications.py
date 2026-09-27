#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Import exam applications from a CSV file."""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import db as mydb


def _normalize(value):
    return (value or "").strip()


def _resolve_student_username(cur, raw_value):
    value = _normalize(raw_value)
    if not value:
        return None
    if value in {"-", "?"}:
        return None
    row = cur.execute(
        "SELECT username FROM students WHERE username = ?",
        (value,),
    ).fetchone()
    if row is not None:
        return row[0]
    row = cur.execute(
        "SELECT username FROM students WHERE student_index = ?",
        (value,),
    ).fetchone()
    if row is not None:
        return row[0]
    return None


def _normalize_exam_value(value):
    return re.sub(r"[^0-9A-Za-zА-Яа-яЉЊЋЂŽžčćšđ]+", "", _normalize(value).lower())


def _load_exam_rows(cur, term_code):
    rows = cur.execute(
        """
        SELECT e.id,
               e.term_code,
               e.course_code,
               e.course_name
        FROM exam_schedule e
        WHERE e.term_code = ?
        ORDER BY e.exam_date, e.exam_hour, e.id
        """,
        (term_code,),
    ).fetchall()
    return [dict(row) for row in rows]


def _match_exam(exam_rows, row):
    exam_code = _normalize_exam_value(row.get("Шифра курса"))
    if not exam_code:
        raise ValueError("Exam application row is missing Шифра курса")

    candidates = []
    for exam in exam_rows:
        if exam_code == _normalize_exam_value(exam["course_code"]):
            candidates.append(exam)

    if not candidates:
        raise ValueError(
            "Cannot match exam row: "
            f"code={exam_code or '-'}"
        )
    if len(candidates) > 1:
        raise ValueError(
            "Ambiguous exam match for "
            f"code={exam_code or '-'}"
        )
    return candidates[0]


def _record_skip(row_number, reason):
    print(f"SKIP\trow={row_number}\treason={reason}", file=sys.stderr)


def _resolve_subject_id(cur, course_code, accreditation, module):
    rows = cur.execute(
        """
        SELECT s.id
        FROM course_subjects cs
        JOIN subjects s ON s.id = cs.subject_id
        WHERE cs.course_code = ?
          AND lower(trim(CAST(s.accreditation AS TEXT))) = lower(trim(COALESCE(?, '')))
          AND lower(trim(s.module)) = lower(trim(COALESCE(?, '')))
        ORDER BY s.id
        """,
        (course_code, accreditation, module),
    ).fetchall()
    subject_ids = [row[0] for row in rows]
    if not subject_ids:
        raise ValueError(
            f"Cannot resolve subject for course {course_code!r} accreditation {accreditation!r} module {module!r}"
        )
    if len(subject_ids) > 1:
        raise ValueError(
            f"Ambiguous subject mapping for course {course_code!r} accreditation {accreditation!r} module {module!r}"
        )
    return subject_ids[0]


def _resolve_row(cur, exam_rows, row):
    username_value = _normalize(row.get("Корисничко име"))
    if not username_value:
        raise ValueError("Корисничко име is required")

    exam = _match_exam(exam_rows, row)
    subject_accreditation = _normalize(row.get("Акредитација"))
    if not subject_accreditation:
        raise ValueError("Акредитација is required")
    subject_module = _normalize(row.get("Модул"))
    if not subject_module:
        raise ValueError("Модул is required")
    subject_id = _resolve_subject_id(
        cur,
        exam["course_code"],
        subject_accreditation,
        subject_module,
    )
    username = _resolve_student_username(cur, username_value)
    if username is None:
        raise ValueError(f"unknown student {username_value}")
    return subject_id, username


def _collect_desired_row(cur, exam_rows, row):
    try:
        return _resolve_row(cur, exam_rows, row), None
    except ValueError as exc:
        return None, str(exc)


def _load_existing_applications(cur, term_code):
    rows = cur.execute(
        """
        SELECT id, subject_id, student_username
        FROM exam_applications
        WHERE term_code = ?
        ORDER BY id
        """,
        (term_code,),
    ).fetchall()
    return {(
        int(row["subject_id"]),
        str(row["student_username"]),
    ): int(row["id"]) for row in rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import exam application CSV files.")
    parser.add_argument("database", help="SQLite database path")
    parser.add_argument("term_code", help="Exam term code like 2026.07")
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
            mydb.ensure_exam_schedule_schema(conn)
            mydb.ensure_exam_application_schema(conn)
            cur = conn.cursor()

            desired_rows = []
            skipped_rows = 0
            exam_rows = _load_exam_rows(cur, args.term_code)
            if not exam_rows:
                raise ValueError(f"No exam schedule rows exist for term {args.term_code}")
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                required_headers = {"Шифра курса", "Акредитација", "Модул", "Корисничко име"}
                fieldnames = {str(name).strip() for name in (reader.fieldnames or [])}
                missing = sorted(required_headers - fieldnames)
                if missing:
                    raise ValueError(
                        f"{csv_path.name} is missing required columns: {', '.join(missing)}"
                    )
                for row_number, row in enumerate(reader, start=2):
                    normalized = {str(key).strip(): value for key, value in row.items() if key is not None}
                    desired_row, skip_reason = _collect_desired_row(cur, exam_rows, normalized)
                    if skip_reason is not None:
                        _record_skip(row_number, skip_reason)
                        skipped_rows += 1
                    else:
                        desired_rows.append(desired_row)

            desired_keys = list(dict.fromkeys(desired_rows))
            desired_key_set = set(desired_keys)
            existing_rows = _load_existing_applications(cur, args.term_code)
            existing_key_set = set(existing_rows.keys())
            unchanged_rows = sum(1 for key in desired_keys if key in existing_key_set)

            inserted_rows = 0
            deleted_rows = 0
            for key, existing_id in existing_rows.items():
                if key not in desired_key_set:
                    cur.execute("DELETE FROM exam_applications WHERE id = ?", (existing_id,))
                    deleted_rows += 1

            for subject_id, username in desired_keys:
                if (subject_id, username) not in existing_key_set:
                    cur.execute(
                        """
                        INSERT INTO exam_applications
                            (term_code, subject_id, student_username)
                        VALUES (?, ?, ?)
                        """,
                        (args.term_code, subject_id, username),
                    )
                    inserted_rows += 1

        print(
            f"Synced exam applications for term {args.term_code}: "
            f"{inserted_rows} inserted, {deleted_rows} deleted, "
            f"{unchanged_rows} unchanged, {skipped_rows} skipped from {csv_path}."
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
