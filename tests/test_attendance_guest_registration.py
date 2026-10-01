# Copyright (c) 2026 Filip Marić. See LICENCE.
import attendance as attendancemod
import app as myapp


def login(client, username="alice", password="secret"):
    return client.post("/login", json={"username": username, "password": password})


def make_event(db):
    event_date = "2026-03-09"
    semester = db.semester(name="2026/27. јесењи", start="2026-01-01", end="2026-12-31")
    room = db.room("R1")
    teacher = db.teacher("Prof", "alice")
    course = db.course("NumericalMethods")
    session = db.course_session(course, teacher, semester)
    weekly_session_id = db.weekly_session(
        session_id=session,
        room_id=room,
        day_of_week=0,
        start_slot=10,
        end_slot=12,
    )
    return weekly_session_id, event_date


def open_guest_challenge(client, event_id, event_date):
    started = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/session",
        json={"active": True},
    )
    assert started.status_code == 200
    join_token = myapp.attendance_join_token("weekly", event_id, event_date)
    opened = client.get(
        f"/attendance/weekly/{event_id}/{event_date}/join/{join_token}",
        follow_redirects=True,
    )
    assert opened.status_code == 200
    challenge = client.get(f"/attendance/weekly/{event_id}/{event_date}/challenge")
    assert challenge.status_code == 200
    return challenge.get_json()


def test_guest_registration_is_disabled_by_default(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    db.student("known.student", "2026/0001", "Студент", "Познат")
    login(client)

    challenge = open_guest_challenge(client, event_id, event_date)

    assert challenge["attendance_guest_registration_enabled"] is False
    response = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/join",
        json={"username": "known.student", "selected_code": challenge["challenge"]["current_code"]},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Корисничко име и лозинка су обавезни."


def test_qr_join_redirect_preserves_application_root(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    monkeypatch.setitem(client.application.config, "APPLICATION_ROOT", "/matf-app")
    event_id, event_date = make_event(db)
    login(client)

    started = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/session",
        json={"active": True},
    )
    assert started.status_code == 200
    join_token = myapp.attendance_join_token("weekly", event_id, event_date)

    response = client.get(
        f"/attendance/weekly/{event_id}/{event_date}/join/{join_token}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == (
        f"/matf-app/attendance/weekly/{event_id}/{event_date}/join"
    )


def test_attendance_requires_explicit_teacher_start(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    db.building_location("A", 10.0, 20.0, radius_m=100)
    login(client)

    before_start = client.get(f"/attendance/weekly/{event_id}/{event_date}/data")
    assert before_start.status_code == 200
    assert "no-store" in before_start.headers["Cache-Control"]
    assert before_start.get_json()["attendance_session_active"] is False
    assert "join_token" not in before_start.get_json()

    started = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/session",
        json={"active": True},
    )
    assert started.status_code == 200

    after_start = client.get(f"/attendance/weekly/{event_id}/{event_date}/data")
    assert after_start.get_json()["attendance_session_active"] is True
    assert after_start.get_json()["join_token"]

    stopped = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/session",
        json={"active": False},
    )
    assert stopped.status_code == 200
    after_stop = client.get(f"/attendance/weekly/{event_id}/{event_date}/data")
    assert after_stop.get_json()["attendance_session_active"] is False
    assert "join_token" not in after_stop.get_json()


def test_stopping_session_rejects_an_already_open_attempt(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    login(client)
    challenge = open_guest_challenge(client, event_id, event_date)

    stopped = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/session",
        json={"active": False},
    )
    assert stopped.status_code == 200

    response = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/join",
        json={
            "username": "known.student",
            "password": "secret",
            "selected_code": challenge["challenge"]["current_code"],
        },
    )
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "attendance_not_started"


def test_attendance_session_expires_on_server_and_can_be_extended(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    login(client)

    started = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/session",
        json={"active": True},
    )
    assert started.status_code == 200

    db.execute(
        """
        UPDATE attendance_session_settings
        SET updated_at = datetime('now', '-121 seconds')
        WHERE event_kind = 'weekly' AND event_id = ? AND event_date = ?
        """,
        (event_id, event_date),
    )

    expired = client.get(f"/attendance/weekly/{event_id}/{event_date}/data")
    assert expired.status_code == 200
    assert expired.get_json()["attendance_session_active"] is False
    assert expired.get_json()["attendance_session_expired"] is True
    assert "join_token" not in expired.get_json()

    extended = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/session",
        json={"active": True},
    )
    assert extended.status_code == 200
    assert extended.get_json()["attendance_session_active"] is True

    current = client.get(f"/attendance/weekly/{event_id}/{event_date}/data")
    assert current.get_json()["attendance_session_expired"] is False
    assert current.get_json()["join_token"]


def test_canceled_weekly_event_cannot_start_or_issue_qr(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    db.execute(
        "INSERT INTO weekly_cancellations (weekly_session_id, date, username) VALUES (?, ?, ?)",
        (event_id, event_date, "alice"),
    )
    login(client)

    start = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/session",
        json={"active": True},
    )
    assert start.status_code == 409
    assert start.get_json()["error_code"] == "attendance_canceled"

    data = client.get(f"/attendance/weekly/{event_id}/{event_date}/data")
    assert data.status_code == 200
    assert "join_token" not in data.get_json()


def test_teacher_can_enable_guest_registration_and_known_student_can_join(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    db.building_location("A", 10.0, 20.0, radius_m=100)
    db.student("known.student", "2026/0001", "Студент", "Познат")
    login(client)

    enabled = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/guest-registration",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.get_json()["attendance_guest_registration_enabled"] is True
    assert enabled.get_json()["attendance_geofence_available"] is True
    assert enabled.get_json()["attendance_geofence_enabled"] is False

    challenge = open_guest_challenge(client, event_id, event_date)
    assert challenge["attendance_guest_registration_enabled"] is True
    response = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/join",
        json={"username": "known.student", "selected_code": challenge["challenge"]["current_code"]},
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    record = myapp.query_db(
        "SELECT id, username FROM attendance_records WHERE event_kind = 'weekly' AND event_id = ?",
        (event_id,),
        one=True,
    )
    assert record["username"] == "known.student"

    deleted = client.delete(
        f"/attendance/weekly/{event_id}/{event_date}/student/{record['id']}"
    )
    assert deleted.status_code == 200
    assert myapp.query_db(
        "SELECT 1 FROM attendance_records WHERE id = ?",
        (record["id"],),
        one=True,
    ) is None


def test_guest_registration_rejects_unknown_username(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    login(client)
    client.post(
        f"/attendance/weekly/{event_id}/{event_date}/guest-registration",
        json={"enabled": True},
    )

    challenge = open_guest_challenge(client, event_id, event_date)
    response = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/join",
        json={"username": "does.not.exist", "selected_code": challenge["challenge"]["current_code"]},
    )

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "attendance_unknown_username"
    assert response.get_json()["error"] == "Корисничко име не постоји."


def test_guest_registration_setting_requires_event_owner(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    login(client, username="other.teacher")

    response = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/guest-registration",
        json={"enabled": True},
    )

    assert response.status_code == 403


def test_attendance_rejects_non_boolean_settings(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    db.building_location("A", 10.0, 20.0, radius_m=100)
    login(client)

    for endpoint, field in (
        ("guest-registration", "enabled"),
        ("geofence", "enabled"),
        ("session", "active"),
    ):
        response = client.post(
            f"/attendance/weekly/{event_id}/{event_date}/{endpoint}",
            json={field: "true"},
        )
        assert response.status_code == 400, response.get_json()


def test_attendance_rejects_malformed_join_payload_without_server_error(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    login(client)
    challenge = open_guest_challenge(client, event_id, event_date)
    code = challenge["challenge"]["current_code"]

    non_object = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/join",
        json=["not", "an", "object"],
    )
    assert non_object.status_code == 400

    invalid_username = client.post(
        f"/attendance/weekly/{event_id}/{event_date}/join",
        json={"username": 123, "password": "secret", "selected_code": code},
    )
    assert invalid_username.status_code == 400
    assert "текстуалне" in invalid_username.get_json()["error"]


def test_non_owner_cannot_delete_attendance_record(client, db, monkeypatch):
    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)
    event_id, event_date = make_event(db)
    db.student("known.student", "2026/0001", "Студент", "Познат")
    db.execute(
        """
        INSERT INTO attendance_records
            (event_kind, event_id, event_date, username, registration_source)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("weekly", event_id, event_date, "known.student", "web"),
    )
    record = myapp.query_db(
        "SELECT id FROM attendance_records WHERE event_kind = 'weekly' AND event_id = ?",
        (event_id,),
        one=True,
    )
    login(client, username="other.teacher")

    response = client.delete(
        f"/attendance/weekly/{event_id}/{event_date}/student/{record['id']}"
    )

    assert response.status_code == 403
    assert myapp.query_db(
        "SELECT 1 FROM attendance_records WHERE id = ?",
        (record["id"],),
        one=True,
    ) is not None
