#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Import course-level exam schedule rows from a CSV file."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import db as mydb
from mobile_push import _send_one_push


DEFAULT_TERM_CODE = "2026.07"


def _normalize_text(value) -> str:
    return " ".join(str(value or "").split())


def _parse_exam_date(value: str) -> str:
    value = str(value or "").strip()
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    for pattern in (
        r"^(?P<day>\d{1,2})\.\s*(?P<month>\d{1,2})\.\s*(?P<year>\d{4})\.$",
        r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})\.$",
    ):
        import re

        match = re.match(pattern, value)
        if match:
            return dt.date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            ).isoformat()
    raise ValueError(f"Invalid exam date: {value}")


def _parse_exam_hour(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"Invalid exam hour: {value!r}")


def _parse_location(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    return normalized or None


def _resolve_semester_id_for_term(cur, start_date, end_date, term_code):
    semester_row = cur.execute(
        """
        SELECT id
        FROM semesters
        WHERE start_date <= ? AND end_date >= ?
        ORDER BY start_date DESC, end_date ASC, id DESC
        LIMIT 1
        """,
        (start_date, end_date),
    ).fetchone()
    if semester_row is None:
        raise ValueError(
            "Unable to resolve semester for exam term "
            f"{term_code} ({start_date}..{end_date})"
        )
    return semester_row[0]


def _load_source_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected_columns = {
            "course_code",
            "course_name",
            "exam_date",
            "exam_hour",
            "location",
        }
        if reader.fieldnames is None or not expected_columns.issubset(set(reader.fieldnames)):
            raise ValueError(
                "CSV input does not look like the exported course-level exam schedule file "
                f"({csv_path})"
            )
        return list(reader)


def _group_rows(rows: list[dict[str, str]], term_code: str) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    order: list[str] = []
    for row in rows:
        course_code = _normalize_text(row.get("course_code"))
        if not course_code:
            continue
        if course_code not in grouped:
            grouped[course_code] = []
            order.append(course_code)
        grouped[course_code].append(row)

    records: list[dict[str, object]] = []
    for course_code in order:
        course_rows = grouped[course_code]
        datetimes = {
            (_parse_exam_date(row["exam_date"]), _parse_exam_hour(row["exam_hour"]))
            for row in course_rows
        }
        first = course_rows[0]
        if len(datetimes) != 1:
            print(
                "WARNING: conflicting exam schedule rows for "
                f"term={term_code} course={course_code}; using the first row and ignoring {len(course_rows) - 1} others",
                file=sys.stderr,
            )
        course_name = _normalize_text(first.get("course_name"))
        if not course_name:
            raise ValueError(f"Missing course name for course {course_code}")
        records.append(
            {
                "course_code": course_code,
                "course_name": course_name,
                "exam_date": _parse_exam_date(first["exam_date"]),
                "exam_hour": _parse_exam_hour(first["exam_hour"]),
                "location": _parse_location(first.get("location")),
            }
        )
    return records


def _load_existing_rows(cur: sqlite3.Cursor, term_code: str) -> dict[str, sqlite3.Row]:
    rows = cur.execute(
        """
        SELECT
            id,
            term_code,
            course_code,
            course_name,
            exam_date,
            exam_hour,
            location
        FROM exam_schedule
        WHERE term_code = ?
        ORDER BY course_code, id
        """,
        (term_code,),
    ).fetchall()
    existing: dict[str, sqlite3.Row] = {}
    for row in rows:
        existing[_normalize_text(row[2])] = row
    return existing


def _row_changed(existing: sqlite3.Row, record: dict[str, object]) -> bool:
    return (
        _normalize_text(existing[3]) != _normalize_text(record["course_name"])
        or _normalize_text(existing[4]) != _normalize_text(record["exam_date"])
        or int(existing[5]) != int(record["exam_hour"])
        or _normalize_text(existing[6]) != _normalize_text(record["location"])
    )


def _format_exam_value(exam_date: str, exam_hour: int, location: str | None) -> str:
    location_text = location if location else "непознато"
    return f"{exam_date} у {exam_hour:02d}:00, локација {location_text}"


def _change_source_id(term_code: str, course_code: str, old_row: sqlite3.Row, record: dict[str, object]) -> str:
    payload = "|".join(
        [
            term_code,
            course_code,
            _normalize_text(old_row[3]),
            _normalize_text(old_row[4]),
            str(int(old_row[5])),
            _normalize_text(old_row[6]),
            _normalize_text(record["course_name"]),
            _normalize_text(record["exam_date"]),
            str(int(record["exam_hour"])),
            _normalize_text(record["location"]),
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"exam-schedule-change:{term_code}:{course_code}:{digest}"


def _notify_exam_schedule_change(
    cur: sqlite3.Cursor,
    *,
    term_code: str,
    semester_id: int,
    course_code: str,
    old_row: sqlite3.Row,
    new_record: dict[str, object],
) -> int:
    recipients = [
        row[0]
        for row in cur.execute(
            """
            SELECT DISTINCT a.student_username
            FROM exam_applications a
            JOIN course_subjects cs ON cs.subject_id = a.subject_id
            WHERE a.term_code = ?
              AND cs.course_code = ?
            ORDER BY a.student_username
            """,
            (term_code, course_code),
        ).fetchall()
    ]
    if not recipients:
        return 0

    course_row = cur.execute(
        "SELECT id, name FROM courses WHERE code = ?",
        (course_code,),
    ).fetchone()
    if course_row is None:
        print(
            f"WARNING: could not create change notification for missing course {course_code}",
            file=sys.stderr,
        )
        return 0

    teacher_row = cur.execute(
        "SELECT username FROM teachers WHERE username = ?",
        ("system",),
    ).fetchone()
    if teacher_row is None:
        cur.execute(
            "INSERT INTO teachers (name, username) VALUES (?, ?)",
            ("Систем обавештења", "system"),
        )

    source_id = _change_source_id(term_code, course_code, old_row, new_record)
    title = f"Промена испита: {new_record['course_name']}"
    body = "\n\n".join(
        [
            f"Термин испита за предмет {new_record['course_name']} је промењен.",
            f"Старо: {_format_exam_value(_normalize_text(old_row[4]), int(old_row[5]), old_row[6])}.",
            f"Ново: {_format_exam_value(new_record['exam_date'], int(new_record['exam_hour']), new_record['location'])}.",
        ]
    )

    existing = cur.execute(
        "SELECT id FROM notifications WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    if existing is not None:
        return 0

    cur.execute(
        """
        INSERT INTO notifications (
            source_id, semester_id, course_id, teacher_username,
            title, body, published_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            source_id,
            semester_id,
            course_row[0],
            "system",
            title,
            body,
        ),
    )
    notification_id = cur.lastrowid

    for student_username in recipients:
        cur.execute(
            """
            INSERT OR IGNORE INTO notification_recipients (notification_id, student_username)
            VALUES (?, ?)
            """,
            (notification_id, student_username),
        )
    push_data = {
        "open_mode": "detail",
        "course_label": new_record["course_name"],
        "teacher_label": "Систем обавештења",
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    conn = cur.connection
    device_rows = conn.execute(
        """
        SELECT installation_id
        FROM mobile_devices
        WHERE student_username IN ({})
          AND enabled = 1
        ORDER BY updated_at DESC, device_id
        """.format(",".join("?" for _ in recipients)),
        tuple(recipients),
    ).fetchall()
    delivered = 0
    for row in device_rows:
        installation_id = row[0]
        if not installation_id:
            continue
        result = _send_one_push(
            installation_id,
            title,
            body,
            notification_id=notification_id,
            extra_data=push_data,
        )
        if not (isinstance(result, dict) and result.get("skipped")):
            delivered += 1
    return delivered


def import_rows(database_path: Path, csv_path: Path, term_code: str) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(f"Source CSV not found: {csv_path}")
    if not database_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")

    source_rows = _load_source_rows(csv_path)
    records = _group_rows(source_rows, term_code)

    conn = sqlite3.connect(database_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        mydb.ensure_exam_schedule_schema(conn)
        mydb.ensure_exam_term_schema(conn)
        mydb.ensure_notification_schema(conn)
        cur = conn.cursor()

        for record in records:
            record["location"] = mydb.resolve_exam_location_to_building(
                cur,
                record["location"],
            )

        existing_rows = _load_existing_rows(cur, term_code)
        inserted = 0
        updated = 0
        skipped = 0
        notified_recipients = 0
        kept_course_codes: set[str] = set()

        term_semester_id = None
        start_date = end_date = None
        if records:
            start_date = min(record["exam_date"] for record in records)
            end_date = max(record["exam_date"] for record in records)
            term_semester_id = _resolve_semester_id_for_term(cur, start_date, end_date, term_code)

        with conn:
            for record in records:
                course_code = _normalize_text(record["course_code"])
                kept_course_codes.add(course_code)
                existing = existing_rows.get(course_code)
                if existing is None:
                    cur.execute(
                        """
                        INSERT INTO exam_schedule (
                            term_code,
                            course_code,
                            course_name,
                            exam_date,
                            exam_hour,
                            location
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            term_code,
                            record["course_code"],
                            record["course_name"],
                            record["exam_date"],
                            record["exam_hour"],
                            record["location"],
                        ),
                    )
                    inserted += 1
                    continue

                if _row_changed(existing, record):
                    cur.execute(
                        """
                        UPDATE exam_schedule
                        SET course_name = ?,
                            exam_date = ?,
                            exam_hour = ?,
                            location = ?,
                            imported_at = datetime('now')
                        WHERE id = ?
                        """,
                        (
                            record["course_name"],
                            record["exam_date"],
                            record["exam_hour"],
                            record["location"],
                            existing[0],
                        ),
                    )
                    updated += 1
                    if term_semester_id is not None:
                        notified_recipients += _notify_exam_schedule_change(
                            cur,
                            term_code=term_code,
                            semester_id=term_semester_id,
                            course_code=course_code,
                            old_row=existing,
                            new_record=record,
                        )
                else:
                    skipped += 1

            if kept_course_codes:
                placeholders = ",".join("?" for _ in kept_course_codes)
                deleted = cur.execute(
                    f"""
                    DELETE FROM exam_schedule
                    WHERE term_code = ?
                      AND course_code NOT IN ({placeholders})
                    """,
                    (term_code, *sorted(kept_course_codes)),
                ).rowcount
            else:
                deleted = cur.execute(
                    "DELETE FROM exam_schedule WHERE term_code = ?",
                    (term_code,),
                ).rowcount

            if records and term_semester_id is not None and start_date is not None and end_date is not None:
                cur.execute(
                    """
                    INSERT INTO exam_terms (term_code, start_date, end_date, semester_id)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(term_code) DO UPDATE SET
                        start_date = excluded.start_date,
                        end_date = excluded.end_date,
                        semester_id = excluded.semester_id,
                        imported_at = datetime('now')
                    """,
                    (term_code, start_date, end_date, term_semester_id),
                )
            else:
                cur.execute("DELETE FROM exam_terms WHERE term_code = ?", (term_code,))

        if records:
            print(
                f"TERM={term_code} DELETED={deleted} INSERTED={inserted} UPDATED={updated} "
                f"UNCHANGED={skipped} NOTIFIED={notified_recipients} "
                f"DATE_RANGE={records[0]['exam_date']}..{records[-1]['exam_date']}"
            )
        else:
            print(f"TERM={term_code} DELETED={deleted} INSERTED=0")
        return 0
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import course-level exam schedule rows from a CSV file."
    )
    parser.add_argument("--source", required=True, help="Path to the exported CSV")
    parser.add_argument("--database", required=True, help="SQLite database path")
    parser.add_argument("--term-code", default=DEFAULT_TERM_CODE, help="Exam term code to replace")
    args = parser.parse_args(argv)
    return import_rows(Path(args.database), Path(args.source), args.term_code)


if __name__ == "__main__":
    raise SystemExit(main())
