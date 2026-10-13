# Copyright (c) 2026 Filip Marić. See LICENCE.

import attendance as attendancemod


def login(client, username="alice", password="secret"):
    return client.post(
        "/login",
        json={"username": username, "password": password},
    )


def add_attendance_record(db, kind, event_id, event_date, username="student1"):
    db.execute(
        """
        INSERT INTO attendance_records (event_kind, event_id, event_date, username)
        VALUES (?, ?, ?, ?)
        """,
        (kind, event_id, event_date, username),
    )


def test_reservation_owner_can_view_expired_attendance_roster(client, db, monkeypatch):
    event_date = "2026-03-09"
    room = db.room("R1")
    reservation_id = db.reservation(
        room_id=room,
        date=event_date,
        start=10,
        end=12,
        username="alice",
    )
    add_attendance_record(db, "reservation", reservation_id, event_date)
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: False)
    login(client, "alice")

    response = client.get(f"/attendance/reservation/{reservation_id}/{event_date}/data")

    assert response.status_code == 200
    assert response.get_json()["attendance_open"] is False
    assert response.get_json()["student_count"] == 1


def test_admin_can_view_expired_weekly_attendance_roster(client, db, monkeypatch):
    event_date = "2026-03-09"
    room = db.room("R1")
    teacher = db.teacher("Prof", "prof")
    course = db.course("NumericalMethods")
    semester = db.semester(start="2026-01-01", end="2026-12-31")
    session = db.course_session(course, teacher, semester)
    weekly_id = db.weekly_session(
        session_id=session,
        room_id=room,
        day_of_week=1,
        start_slot=10,
        end_slot=12,
    )
    add_attendance_record(db, "weekly", weekly_id, event_date)
    db.execute("INSERT INTO administrators (username) VALUES (?)", ("alice",))
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: False)
    login(client, "alice")

    response = client.get(f"/attendance/weekly/{weekly_id}/{event_date}/data")

    assert response.status_code == 200
    assert response.get_json()["attendance_open"] is False
    assert response.get_json()["student_count"] == 1


def test_non_owner_cannot_view_expired_attendance_roster(client, db, monkeypatch):
    event_date = "2026-03-09"
    room = db.room("R1")
    reservation_id = db.reservation(
        room_id=room,
        date=event_date,
        start=10,
        end=12,
        username="alice",
    )
    add_attendance_record(db, "reservation", reservation_id, event_date)
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: False)
    login(client, "bob")

    response = client.get(f"/attendance/reservation/{reservation_id}/{event_date}/data")

    assert response.status_code == 403


def test_admin_attendance_page_lists_weekly_and_reservation_events(client, db):
    event_date = "2026-03-09"
    room = db.room("R1")
    teacher = db.teacher("Prof", "prof")
    course = db.course("NumericalMethods")
    semester = db.semester(start="2026-01-01", end="2026-12-31")
    session = db.course_session(course, teacher, semester)
    weekly_id = db.weekly_session(
        session_id=session,
        room_id=room,
        day_of_week=1,
        start_slot=10,
        end_slot=12,
    )
    reservation_id = db.reservation(
        room_id=room,
        date=event_date,
        start=13,
        end=15,
        description="Састанак",
        username="alice",
    )
    add_attendance_record(db, "weekly", weekly_id, event_date)
    add_attendance_record(db, "reservation", reservation_id, event_date, "student2")
    db.execute("INSERT INTO administrators (username) VALUES (?)", ("alice",))
    login(client, "alice")

    response = client.get("/admin/attendance")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "NumericalMethods" in body
    assert "Састанак" in body
    assert f"/attendance/weekly/{weekly_id}/{event_date}" in body
    assert f"/attendance/reservation/{reservation_id}/{event_date}" in body


def test_non_admin_cannot_open_admin_attendance_page(client):
    login(client, "alice")

    response = client.get("/admin/attendance")

    assert response.status_code == 403


def test_anonymous_cannot_open_admin_attendance_page(client):
    response = client.get("/admin/attendance")

    assert response.status_code == 401
