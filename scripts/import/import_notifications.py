#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Import notifications from CSV and dispatch mobile pushes."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import fcntl
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import db as mydb
from mobile_push import _send_one_push
from semester_utils import parse_semester_display_name

IMPORT_STATE_NAME = "notifications_last_sync"


def _utcnow_iso():
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    text = _normalize(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso_datetime(dt):
    """Format one UTC datetime as a canonical ISO-8601 timestamp."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize(value):
    """Trim a CSV value and turn missing cells into an empty string."""
    return (value or "").strip()


def _split_group_names(value):
    """Split a group list separated by semicolons, commas, or pipes."""
    if not value:
        return []
    return [item.strip() for item in re.split(r"[;,|]", value) if item.strip()]


def _lookup_id(cur, table, column, value, label):
    """Return the primary key for one row or raise a helpful error."""
    row = cur.execute(
        f"SELECT id FROM {table} WHERE {column} = ?",
        (value,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown {label}: {value}")
    return row[0]


def _read_import_state(cur, name):
    """Return the stored watermark for one import stream, if any."""
    row = cur.execute(
        "SELECT value FROM import_state WHERE name = ?",
        (name,),
    ).fetchone()
    return row[0] if row is not None else None


def _write_import_state(cur, name, value):
    """Store the latest successful watermark for one import stream."""
    cur.execute(
        """
        INSERT INTO import_state (name, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (name, value, _utcnow_iso()),
    )


def _resolve_semester_id(cur, raw_value):
    """Resolve the semester id, defaulting to the active semester."""
    value = _normalize(raw_value)
    if value:
        if value.isdigit():
            row = cur.execute(
                "SELECT id FROM semesters WHERE id = ?",
                (int(value),),
            ).fetchone()
        else:
            parsed = parse_semester_display_name(value)
            if parsed is not None:
                academic_year_start, season = parsed
                row = cur.execute(
                    """
                    SELECT id
                    FROM semesters
                    WHERE academic_year_start = ? AND season = ?
                    """,
                    (academic_year_start, season),
                ).fetchone()
            else:
                row = None
        if row is None:
            raise ValueError(f"Unknown semester: {value}")
        return row[0]

    row = cur.execute(
        """
        SELECT id
        FROM semesters
        WHERE date('now') BETWEEN start_date AND end_date
        ORDER BY start_date DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is not None:
        return row[0]

    row = cur.execute(
        "SELECT id FROM semesters ORDER BY start_date DESC, id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("No semesters exist in the database")
    return row[0]


def _load_rows(csv_path, encoding="utf-8-sig"):
    """Load and validate the notification CSV file."""
    with open(csv_path, "r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "source_id",
            "course_code",
            "teacher_username",
            "group_names",
            "title",
            "body",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing columns in CSV: {', '.join(sorted(missing))}")
        return list(reader)


def _watermark_for_rows(rows):
    """Return the newest published_at value present in the imported batch."""
    newest = None
    for row in rows:
        dt = _parse_iso_datetime(row.get("published_at"))
        if dt is None:
            continue
        if newest is None or dt > newest:
            newest = dt
    return _format_iso_datetime(newest) if newest is not None else None


def _acquire_import_lock():
    """Prevent overlapping cron imports."""
    lock_path = Path("/tmp") / "notification_import.lock"
    handle = open(lock_path, "a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _import_row(cur, row, row_number):
    """Insert one CSV row and return the stored notification details, or None if skipped."""
    source_id = _normalize(row.get("source_id"))
    course_code = _normalize(row.get("course_code"))
    teacher_username = _normalize(row.get("teacher_username"))
    title = _normalize(row.get("title"))
    body = _normalize(row.get("body"))
    group_names = _split_group_names(_normalize(row.get("group_names")))
    published_at = _normalize(row.get("published_at")) or _utcnow_iso()

    if not source_id:
        raise ValueError(f"Row {row_number}: source_id is required")
    if not course_code:
        raise ValueError(f"Row {row_number}: course_code is required")
    if not teacher_username:
        raise ValueError(f"Row {row_number}: teacher_username is required")
    if not group_names:
        raise ValueError(f"Row {row_number}: group_names is required")
    if not title:
        raise ValueError(f"Row {row_number}: title is required")
    if not body:
        raise ValueError(f"Row {row_number}: body is required")

    existing = cur.execute(
        "SELECT id FROM notifications WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    if existing is not None:
        return None

    semester_id = _resolve_semester_id(cur, row.get("semester_id"))
    course_id = _lookup_id(cur, "courses", "code", course_code, "course")
    _lookup_id(cur, "teachers", "username", teacher_username, "teacher")

    group_ids = []
    for group_name in group_names:
        group_id = _lookup_id(cur, "groups", "name", group_name, "group")
        if group_id not in group_ids:
            group_ids.append(group_id)

    cur.execute(
        """
        INSERT INTO notifications (
            source_id, semester_id, course_id, teacher_username,
            title, body, published_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            semester_id,
            course_id,
            teacher_username,
            title,
            body,
            published_at,
            _utcnow_iso(),
        ),
    )
    notification_id = cur.lastrowid

    for group_id in group_ids:
        cur.execute(
            """
            INSERT INTO notification_targets (notification_id, group_id)
            VALUES (?, ?)
            """,
            (notification_id, group_id),
        )

    placeholders = ",".join("?" for _ in group_ids)
    cur.execute(
        f"""
        INSERT OR IGNORE INTO notification_recipients (notification_id, student_username)
        SELECT ?, se.student_username
        FROM student_enrollments se
        WHERE se.semester_id = ?
          AND se.group_id IN ({placeholders})
        """,
        (notification_id, semester_id, *group_ids),
    )

    recipient_rows = cur.execute(
        """
        SELECT student_username
        FROM notification_recipients
        WHERE notification_id = ?
        ORDER BY student_username
        """,
        (notification_id,),
    ).fetchall()

    metadata_row = cur.execute(
        """
        SELECT c.code AS course_code,
               c.name AS course_name,
               t.name AS teacher_name
        FROM notifications n
        LEFT JOIN courses c ON c.id = n.course_id
        LEFT JOIN teachers t ON t.username = n.teacher_username
        WHERE n.id = ?
        """,
        (notification_id,),
    ).fetchone()
    group_rows = cur.execute(
        """
        SELECT g.name
        FROM notification_targets nt
        JOIN groups g ON g.id = nt.group_id
        WHERE nt.notification_id = ?
        ORDER BY g.name
        """,
        (notification_id,),
    ).fetchall()

    return {
        "notification_id": notification_id,
        "course_code": metadata_row["course_code"] if metadata_row else course_code,
        "course_name": metadata_row["course_name"] if metadata_row else None,
        "teacher_username": teacher_username,
        "teacher_name": metadata_row["teacher_name"] if metadata_row else None,
        "title": title,
        "body": body,
        "published_at": published_at,
        "group_names": [row[0] for row in group_rows],
        "student_usernames": [row[0] for row in recipient_rows],
    }


def _summary_push_content(notifications):
    """Build one summary push for a student over multiple imported notifications."""
    if len(notifications) == 1:
        notification = notifications[0]
        return notification["title"], notification["body"]

    title = f"{len(notifications)} novih obaveštenja"
    titles = [notification["title"] for notification in notifications[:3]]
    body = "; ".join(titles)
    if len(notifications) > 3:
        body = f"{body}; ..."
    return title, body


def _notification_push_data(notification, open_mode):
    """Build FCM data payload fields for one notification push."""
    return {
        "open_mode": open_mode,
        "notification_id": str(notification["notification_id"]),
        "title": notification["title"],
        "body": notification["body"],
        "course_label": notification["course_name"] or notification["course_code"] or "",
        "teacher_label": notification["teacher_name"] or notification["teacher_username"] or "",
        "groups_label": ", ".join(notification["group_names"]),
        "published_at": notification["published_at"],
    }


def _send_summary_pushes(conn, imported_notifications):
    """Send one push per student for the whole import batch."""
    notifications_by_student = defaultdict(list)
    for notification in imported_notifications:
        for student_username in notification["student_usernames"]:
            notifications_by_student[student_username].append(notification)

    push_results = []
    for student_username in sorted(notifications_by_student):
        student_notifications = sorted(
            notifications_by_student[student_username],
            key=lambda item: item["notification_id"],
        )
        title, body = _summary_push_content(student_notifications)
        open_mode = "detail" if len(student_notifications) == 1 else "inbox"
        push_data = _notification_push_data(
            student_notifications[-1],
            open_mode=open_mode,
        )
        if len(student_notifications) > 1:
            push_data["summary_count"] = str(len(student_notifications))
            push_data["summary_titles"] = "; ".join(
                notification["title"] for notification in student_notifications[:3]
            )
        device_rows = conn.execute(
            """
        SELECT installation_id
        FROM mobile_devices
        WHERE student_username = ?
          AND enabled = 1
        ORDER BY updated_at DESC, device_id
        """,
        (student_username,),
    ).fetchall()
        installation_ids = [row["installation_id"] for row in device_rows if row["installation_id"]]
        if not installation_ids:
            push_results.append(
                {
                    "student_username": student_username,
                    "targeted": 0,
                    "delivered": 0,
                    "skipped": True,
                }
            )
            continue

        delivered = 0
        skipped = 0
        for installation_id in installation_ids:
            result = _send_one_push(
                installation_id,
                title,
                body,
                notification_id=student_notifications[-1]["notification_id"],
                extra_data=push_data,
            )
            if isinstance(result, dict) and result.get("skipped"):
                skipped += 1
            else:
                delivered += 1
        push_results.append(
            {
                "student_username": student_username,
                "targeted": len(installation_ids),
                "delivered": delivered,
                "skipped": skipped == len(installation_ids),
            }
        )
    return push_results


def main(argv=None):
    """Import notifications from CSV and dispatch one summary push per student."""
    parser = argparse.ArgumentParser(
        description="Import notifications from CSV and dispatch mobile pushes."
    )
    parser.add_argument("database", help="SQLite database path")
    parser.add_argument("csv_file", help="Path to the notification CSV file")
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV file encoding (defaults to utf-8-sig)",
    )
    args = parser.parse_args(argv)

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}", file=sys.stderr)
        return 2

    try:
        rows = _load_rows(csv_path, encoding=args.encoding)
    except Exception as exc:
        print(f"Failed to read CSV: {exc}", file=sys.stderr)
        return 1

    lock_handle = _acquire_import_lock()
    if lock_handle is None:
        print("Another notification import is already running; skipping this run.")
        return 0

    conn = sqlite3.connect(args.database, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        mydb.init_db(conn)
        mydb.ensure_notification_schema(conn)

        current_watermark = None
        imported_notifications = []
        skipped = 0
        with conn:
            cur = conn.cursor()
            current_watermark = _read_import_state(cur, IMPORT_STATE_NAME)
            for row_number, row in enumerate(rows, start=2):
                notification = _import_row(cur, row, row_number)
                if notification is None:
                    skipped += 1
                else:
                    imported_notifications.append(notification)

            batch_watermark = _watermark_for_rows(rows)
            if batch_watermark is not None:
                if current_watermark is None:
                    _write_import_state(cur, IMPORT_STATE_NAME, batch_watermark)
                else:
                    current_dt = _parse_iso_datetime(current_watermark)
                    batch_dt = _parse_iso_datetime(batch_watermark)
                    if current_dt is None or (batch_dt is not None and batch_dt > current_dt):
                        _write_import_state(cur, IMPORT_STATE_NAME, batch_watermark)

        push_results = _send_summary_pushes(conn, imported_notifications)

        print(
            f"Imported {len(imported_notifications)} notifications "
            f"({skipped} skipped) into {args.database}"
        )
        if current_watermark is not None:
            print(f"PREVIOUS_WATERMARK={current_watermark}")
        stored_watermark = _read_import_state(conn.cursor(), IMPORT_STATE_NAME)
        if stored_watermark is not None:
            print(f"CURRENT_WATERMARK={stored_watermark}")
        for item in push_results:
            if item.get("skipped"):
                print(
                    f"Student {item['student_username']}: "
                    f"targeted {item['targeted']} device(s), delivered 0"
                )
            else:
                print(
                    f"Student {item['student_username']}: "
                    f"targeted {item['targeted']} device(s), delivered {item['delivered']}"
                )
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
