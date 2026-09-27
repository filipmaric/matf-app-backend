# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import importlib
from pathlib import Path

import app as myapp

import_notifications = importlib.import_module("scripts.import.import_notifications")


def _make_notification_csv(path):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "source_id",
                "semester_id",
                "course_code",
                "teacher_username",
                "group_names",
                "title",
                "body",
                "published_at",
            ]
        )
        writer.writerow(
            [
                "central-001",
                "",
                "MAT1",
                "prof.mat",
                "1o1;1o2",
                "Exercise canceled",
                "Today's exercise is canceled.",
                "2026-08-13T10:00:00+00:00",
            ]
        )
        writer.writerow(
            [
                "central-002",
                "",
                "MAT1",
                "prof.mat",
                "1o1",
                "Second notice",
                "A second notification for the same batch.",
                "2026-08-13T10:05:00+00:00",
            ]
        )


def test_import_notifications_from_csv_creates_rows_and_pushes(tmp_path, db, monkeypatch):
    semester_id = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "1/2026", "Petrovic", "Mina")
    db.teacher("Prof Math", "prof.mat")
    course_id = db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Mathematics", "MAT1"),
    )
    subject_id = db.subject("MAT1", "Mathematics", 2026, "I")
    db.course_subject("MAT1", subject_id)
    db.execute(
        """
        INSERT INTO mobile_devices (
            device_id, student_username, device_name, platform, installation_id, enabled
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("device-student1", "student1", "Phone", "android", "installation-id-student1", 1),
    )
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    group_1o2 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o2",))
    db.execute(
        """
        INSERT INTO student_enrollments (
            student_username, semester_id, subject_id, group_id
        ) VALUES (?, ?, ?, ?)
        """,
        ("student1", semester_id, subject_id, group_1o1),
    )

    csv_path = tmp_path / "notifications.csv"
    _make_notification_csv(csv_path)

    dispatched = []

    def fake_send_one_push(installation_id, title, body, notification_id, extra_data=None):
        dispatched.append((installation_id, title, body, notification_id, extra_data))
        return {"ok": True, "message_id": "test-message"}

    monkeypatch.setattr(import_notifications, "_send_one_push", fake_send_one_push)

    exit_code = import_notifications.main([myapp.DATABASE, str(csv_path)])
    assert exit_code == 0
    assert len(dispatched) == 1
    assert dispatched[0][0] == "installation-id-student1"
    assert dispatched[0][1] == "2 novih obaveštenja"
    assert dispatched[0][2] == "Exercise canceled; Second notice"
    assert dispatched[0][4]["open_mode"] == "inbox"
    assert dispatched[0][4]["summary_count"] == "2"
    state = myapp.query_db(
        """
        SELECT value
        FROM import_state
        WHERE name = ?
        """,
        ("notifications_last_sync",),
        one=True,
    )
    assert state["value"] == "2026-08-13T10:05:00Z"


def test_single_notification_import_sends_detail_push(tmp_path, db, monkeypatch):
    semester_id = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "1/2026", "Petrovic", "Mina")
    db.teacher("Prof Math", "prof.mat")
    course_id = db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Mathematics", "MAT1"),
    )
    subject_id = db.subject("MAT1", "Mathematics", 2026, "I")
    db.course_subject("MAT1", subject_id)
    db.execute(
        """
        INSERT INTO mobile_devices (
            device_id, student_username, device_name, platform, installation_id, enabled
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("device-student1", "student1", "Phone", "android", "installation-id-student1", 1),
    )
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    db.execute(
        """
        INSERT INTO student_enrollments (
            student_username, semester_id, subject_id, group_id
        ) VALUES (?, ?, ?, ?)
        """,
        ("student1", semester_id, subject_id, group_1o1),
    )

    csv_path = tmp_path / "single-notification.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "source_id",
                "semester_id",
                "course_code",
                "teacher_username",
                "group_names",
                "title",
                "body",
                "published_at",
            ]
        )
        writer.writerow(
            [
                "central-001",
                "",
                "MAT1",
                "prof.mat",
                "1o1",
                "Single notice",
                "One notification only.",
                "2026-08-13T10:00:00+00:00",
            ]
        )

    dispatched = []

    def fake_send_one_push(installation_id, title, body, notification_id, extra_data=None):
        dispatched.append((installation_id, title, body, notification_id, extra_data))
        return {"ok": True, "message_id": "test-message"}

    monkeypatch.setattr(import_notifications, "_send_one_push", fake_send_one_push)

    exit_code = import_notifications.main([myapp.DATABASE, str(csv_path)])
    assert exit_code == 0
    assert len(dispatched) == 1
    assert dispatched[0][1] == "Single notice"
    assert dispatched[0][2] == "One notification only."
    assert dispatched[0][4]["open_mode"] == "detail"
    assert dispatched[0][4]["course_label"] == "Mathematics"
    assert dispatched[0][4]["teacher_label"] == "Prof Math"
    assert dispatched[0][4]["groups_label"] == "1o1"

    notification = myapp.query_db(
        """
        SELECT source_id, semester_id, course_id, teacher_username, title, body, published_at
        FROM notifications
        WHERE source_id = ?
        """,
        ("central-001",),
        one=True,
    )
    assert notification is not None
    assert notification["semester_id"] == semester_id
    assert notification["course_id"] == course_id
    assert notification["teacher_username"] == "prof.mat"
    assert notification["title"] == "Single notice"

    targets = myapp.query_db(
        """
        SELECT g.name
        FROM notification_targets nt
        JOIN groups g ON g.id = nt.group_id
        JOIN notifications n ON n.id = nt.notification_id
        WHERE n.source_id = ?
        ORDER BY g.name
        """,
        ("central-001",),
    )
    assert [row["name"] for row in targets] == ["1o1"]

    recipients = myapp.query_db(
        """
        SELECT student_username
        FROM notification_recipients r
        JOIN notifications n ON n.id = r.notification_id
        WHERE n.source_id = ?
        ORDER BY student_username
        """,
        ("central-001",),
    )
    assert [row["student_username"] for row in recipients] == ["student1"]

    exit_code = import_notifications.main([myapp.DATABASE, str(csv_path)])
    assert exit_code == 0
    assert len(dispatched) == 1
