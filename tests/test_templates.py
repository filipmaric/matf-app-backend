# Copyright (c) 2026 Filip Marić. See LICENCE.
from datetime import datetime, timedelta

import attendance as attendancemod


def login(client, username="alice", password="secret"):
    return client.post(
        "/login",
        json={"username": username, "password": password},
    )


def test_index_template(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Резервације учионица" in r.get_data(as_text=True)
    assert "Моје резервације" in r.get_data(as_text=True)


def test_healthz_route(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}


def test_calendar_template(client):
    r = client.get("/calendar")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Да бисте видели и мењали календар" in body
    assert "Пријавите се овде" in body


def test_my_reservations_template(client):
    r = client.get("/my_reservations")
    assert r.status_code == 200
    assert "Моје резервације" in r.get_data(as_text=True)


def test_attendance_templates(client, db):
    login(client, "alice")

    now = datetime.now()
    event_date = now.date().isoformat()
    start_slot = max(0, now.hour - 1)
    end_slot = min(23, start_slot + 2)

    semester = db.semester(
        name="Current 2026",
        start=event_date,
        end=(now + timedelta(days=1)).date().isoformat(),
    )
    room = db.room("R1")
    teacher = db.teacher("Prof", "alice")
    course = db.course("NumericalMethods")
    session = db.course_session(course, teacher, semester)
    weekly_session_id = db.weekly_session(
        session_id=session,
        room_id=room,
        day_of_week=now.weekday(),
        start_slot=start_slot,
        end_slot=end_slot,
    )

    roster = client.get(f"/attendance/weekly/{weekly_session_id}/{event_date}/data")
    assert roster.status_code == 200
    token = roster.get_json()["join_token"]

    r = client.get(f"/attendance/weekly/1/{event_date}")
    assert r.status_code == 200
    assert "Присуство на часу" in r.get_data(as_text=True)

    r = client.get(
        f"/attendance/weekly/{weekly_session_id}/{event_date}/join/{token}",
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Пријава присуства" in r.get_data(as_text=True)


def test_review_demo_uses_student_flow(client, monkeypatch):
    monkeypatch.setattr(attendancemod, "REVIEW_MODE", True)

    fixed_now = datetime(2026, 8, 14, 10, 0, 0)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now
            return fixed_now.replace(tzinfo=tz)

    monkeypatch.setattr(attendancemod.datetime, "datetime", FrozenDatetime)

    r = client.get("/attendance/review-demo")
    assert r.status_code == 200

    body = r.get_data(as_text=True)
    assert 'id="attendance-root"' in body
    assert "attendanceTeacher.js" in body
    assert "Присуство на часу" in body
    assert 'id="attendance-join-root"' not in body

    review_date = fixed_now.date().isoformat()
    data = client.get(f"/attendance/review/0/{review_date}/data")
    assert data.status_code == 200
    payload = data.get_json()
    assert isinstance(payload["challenge"]["current_code"], int)
    assert len(payload["challenge"]["options"]) == 4
    assert payload["join_token"]
