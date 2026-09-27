# Copyright (c) 2026 Filip Marić. See LICENCE.
import app as myapp
from datetime import datetime, timezone, timedelta
import hashlib
import hmac


def _otp_token_for_setup_code(setup_code, secret="mobile-action-otp-secret"):
    expected_signature = hmac.new(secret.encode("utf-8"), str(setup_code).encode("utf-8"), hashlib.sha256).hexdigest()
    assert expected_signature
    return f"{int(expected_signature[:12], 16) % 1_000_000:06d}"


def _mobile_login(
    client,
    username="alice",
    password="secret",
    device_id="device-1",
    device_name="Pixel",
    otp_code=None,
):
    payload = {
        "username": username,
        "password": password,
        "device_id": device_id,
        "device_name": device_name,
    }
    if otp_code is not None:
        payload["otp_code"] = otp_code
    return client.post("/mobile/login", json=payload)


def _add_enrollment(db, student_username, semester_id, subject_id, group_id):
    db.execute(
        """
        INSERT INTO student_enrollments
            (student_username, semester_id, subject_id, group_id, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (student_username, semester_id, subject_id, group_id, "2026-08-12T00:00:00+00:00"),
    )


def _add_notification(db, source_id, semester_id, course_id, teacher_username, title, body, published_at):
    return db.execute(
        """
        INSERT INTO notifications
            (source_id, semester_id, course_id, teacher_username, title, body, published_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (source_id, semester_id, course_id, teacher_username, title, body, published_at, published_at),
    )


def _add_notification_target(db, notification_id, group_id):
    db.execute(
        "INSERT INTO notification_targets (notification_id, group_id) VALUES (?, ?)",
        (notification_id, group_id),
    )


def _add_notification_recipient(db, notification_id, student_username, read_at=None):
    db.execute(
        """
        INSERT INTO notification_recipients
            (notification_id, student_username, delivered_at, read_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            notification_id,
            student_username,
            "2026-08-12T00:00:00+00:00",
            read_at,
        ),
    )


def _add_exam_application(db, term_code, subject_id, student_username):
    db.execute(
        """
        INSERT INTO exam_applications
            (term_code, subject_id, student_username)
        VALUES (?, ?, ?)
        """,
        (term_code, subject_id, student_username),
    )


def _add_exam_term(db, semester_id, term_code, start_date, end_date):
    db.execute(
        """
        INSERT INTO exam_terms (term_code, start_date, end_date, semester_id)
        VALUES (?, ?, ?, ?)
        """,
        (term_code, start_date, end_date, semester_id),
    )


def _register_installation_id(client, token, installation_id="installation-id-1"):
    return client.post(
        "/mobile/push-token",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "installation_id": installation_id,
            "platform": "android",
        },
    )


def test_mobile_calendar_supports_read_only_etag_cache(client):
    response = _mobile_login(client)
    assert response.status_code == 200
    token = response.get_json()["token"]

    response = client.get(
        "/mobile/calendar?month=4&year=2027",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "calendar" in response.get_json()
    assert response.headers["Cache-Control"] == "private, max-age=3600, must-revalidate"
    etag = response.headers["ETag"]

    cached = client.get(
        "/mobile/calendar?month=4&year=2027",
        headers={
            "Authorization": f"Bearer {token}",
            "If-None-Match": etag,
        },
    )
    assert cached.status_code == 304


def test_mobile_auth_login_me_and_logout(client, db, monkeypatch):
    import attendance as attendancemod

    response = _mobile_login(client)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["token"]
    assert payload["token_type"] == "Bearer"
    assert payload["user"]["radius_username"] == "alice"
    assert payload["session"]["device_id"] == "device-1"
    assert "attendance_locations" not in payload

    token = payload["token"]

    response = client.get("/mobile/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user"]["radius_username"] == "alice"
    assert payload["session"]["device_name"] == "Pixel"
    assert "last_seen_at" in payload["session"]
    assert "two_factor" in payload
    assert payload["unread_count"] == 0
    assert "attendance_locations" not in payload

    semester = db.semester(name="2026/27. јесењи", start="2026-01-01", end="2026-12-31")
    db.building_location("A", 10.0, 20.0, radius_m=100)
    room = db.room("R1", building_name="A")
    teacher = db.teacher("Prof", "alice")
    course = db.course("NumericalMethods")
    session = db.course_session(course, teacher, semester)
    weekly_session = db.weekly_session(
        session_id=session,
        room_id=room,
        day_of_week=1,
        start_slot=10,
        end_slot=12,
    )
    join_token = myapp.attendance_join_token("weekly", weekly_session, "2026-03-09")

    monkeypatch.setattr(attendancemod, "attendance_is_open_now", lambda row, now=None: True)

    response = client.get(
        f"/attendance/weekly/{weekly_session}/2026-03-09/challenge",
        headers={"Authorization": f"Bearer {token}"},
        query_string={"join_token": join_token},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["attendance_locations"][0]["name"] == "A"

    response = client.get("/mobile/sessions", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["current_session_id"]
    assert "attendance_locations" not in payload

    response = client.post("/mobile/logout", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}

    response = client.get("/mobile/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_mobile_auth_me_rate_limit(client, monkeypatch):
    token = _mobile_login(client, username="alice", device_id="device-me-rate-limit").get_json()["token"]
    monkeypatch.setitem(myapp.RATE_LIMITS, "mobile_me", (1, 60))

    assert client.get("/mobile/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    response = client.get("/mobile/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 429
    assert response.get_json() == {"error": "Too many requests"}


def test_mobile_attendance_history_rate_limit(client, db, monkeypatch):
    semester = db.semester(name="2026/27. јесењи", start="2026-01-01", end="2026-12-31")
    teacher = db.teacher("Prof", "alice")
    course = db.course("NumericalMethods")
    session = db.course_session(course, teacher, semester)
    db.weekly_session(
        session_id=session,
        room_id=db.room("R1"),
        day_of_week=1,
        start_slot=10,
        end_slot=12,
    )
    db.execute(
        """
        INSERT INTO attendance_records
            (event_kind, event_id, event_date, username, registration_source, client_ip, failed_attempts_before_success)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("weekly", session, "2026-03-09", "alice", "android", "198.51.100.10", 1),
    )

    monkeypatch.setitem(myapp.RATE_LIMITS, "mobile_attendance_history", (1, 60))
    token = _mobile_login(client, username="alice", device_id="device-history-rate-limit").get_json()["token"]

    assert client.get("/mobile/attendance/history", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    response = client.get("/mobile/attendance/history", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 429
    assert response.get_json() == {"error": "Too many requests"}


def test_mobile_auth_blocks_second_username_on_same_device_same_day(client):
    assert _mobile_login(client, username="alice", device_id="device-2").status_code == 200

    response = _mobile_login(client, username="bob", device_id="device-2")
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["error"] == "device_username_locked_for_today"


def test_mobile_auth_revokes_previous_session_for_same_user(client):
    first = _mobile_login(client, username="alice", device_id="device-3")
    assert first.status_code == 200
    first_token = first.get_json()["token"]

    second = _mobile_login(client, username="alice", device_id="device-4")
    assert second.status_code == 200
    second_token = second.get_json()["token"]

    response = client.get("/mobile/me", headers={"Authorization": f"Bearer {first_token}"})
    assert response.status_code == 401

    response = client.get("/mobile/me", headers={"Authorization": f"Bearer {second_token}"})
    assert response.status_code == 200


def test_mobile_auth_rejects_invalid_credentials(client, monkeypatch):
    import mobile_auth

    monkeypatch.setattr(
        mobile_auth,
        "student_radius_auth",
        lambda username, password, raise_on_error=False: False,
    )

    response = _mobile_login(client, username="alice", password="wrong")
    assert response.status_code == 401


def test_mobile_auth_login_rate_limit_is_per_username(client, monkeypatch):
    import mobile_auth

    monkeypatch.setattr(
        mobile_auth,
        "student_radius_auth",
        lambda username, password, raise_on_error=False: True,
    )
    monkeypatch.setitem(myapp.RATE_LIMITS, "login", (1, 60))

    assert _mobile_login(client, username="alice", device_id="device-login-a").status_code == 200
    assert _mobile_login(client, username="bob", device_id="device-login-b").status_code == 200

    response = _mobile_login(client, username="alice", device_id="device-login-c")
    assert response.status_code == 429
    assert response.get_json() == {"error": "Too many requests"}


def test_mobile_auth_push_token_rate_limit(client, monkeypatch):
    token = _mobile_login(client, username="alice", device_id="device-push-rate-limit").get_json()["token"]
    monkeypatch.setitem(myapp.RATE_LIMITS, "mobile_push_token", (1, 60))

    assert _register_installation_id(client, token, installation_id="installation-1").status_code == 200

    response = _register_installation_id(client, token, installation_id="installation-2")
    assert response.status_code == 429
    assert response.get_json() == {"error": "Too many requests"}


def test_mobile_auth_optional_two_factor_step_up_flow(client, db, monkeypatch):
    fixed_now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    later_now = fixed_now + timedelta(days=8)

    import mobile_auth

    monkeypatch.setattr(mobile_auth, "_utcnow", lambda: fixed_now)

    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    first_login = _mobile_login(client, username="alice", device_id="device-2fa")
    assert first_login.status_code == 200
    token = first_login.get_json()["token"]

    setup_response = client.post(
        "/mobile/2fa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert setup_response.status_code == 200
    setup_payload = setup_response.get_json()
    setup_code = setup_payload["two_factor"]["setup_code"]
    assert setup_code
    assert len(setup_code) == 6
    assert setup_payload["two_factor"]["setup_pending"] is True
    assert setup_payload["two_factor"]["enabled"] is False
    assert setup_payload["two_factor"]["link_ticket"]
    assert setup_payload["two_factor"]["link_ticket_expires_at"]

    code = _otp_token_for_setup_code(setup_code)
    confirm_response = client.post(
        "/mobile/2fa/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"otp_code": code},
    )
    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.get_json()
    assert confirm_payload["two_factor"]["enabled"] is True
    assert confirm_payload["two_factor"]["setup_pending"] is False


def test_mobile_auth_two_factor_link_complete_uses_signed_service_request(client, db, monkeypatch):
    import hypatia_request
    import mobile_auth

    monkeypatch.setattr(mobile_auth, "HYPATIA_LINK_URL", "https://hypatia.example.edu/2fa/link")
    monkeypatch.setattr(mobile_auth, "HYPATIA_REQUEST_SIGNING_SECRET", "test-hypatia-secret")

    first_login = _mobile_login(client, username="alice", device_id="device-2fa-link")
    assert first_login.status_code == 200
    token = first_login.get_json()["token"]

    setup_response = client.post(
        "/mobile/2fa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert setup_response.status_code == 200
    setup_payload = setup_response.get_json()
    ticket = setup_payload["two_factor"]["link_ticket"]
    assert ticket
    assert setup_payload["two_factor"]["link_url"] == f"https://hypatia.example.edu/2fa/link?ticket={ticket}"

    request_path = f"/mobile/2fa/link/complete?ticket={ticket}"
    headers = hypatia_request.signed_request_headers(
        "test-hypatia-secret",
        "POST",
        request_path,
        [f"ticket={ticket}"],
        timestamp="1725000000",
        nonce="nonce-123",
    )
    headers["Authorization"] = f"Bearer {client.application.config['BACKEND_SERVICE_BEARER_TOKEN']}"

    response = client.post(request_path, headers=headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["return_url"] == "matfapp://two-factor-complete"

    refreshed = client.get("/mobile/2fa", headers={"Authorization": f"Bearer {token}"})
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.get_json()
    assert refreshed_payload["two_factor"]["enabled"] is True
    assert refreshed_payload["two_factor"]["link_ticket"] is None


def test_mobile_auth_two_factor_clear_confirmation_and_reconfirm(client, db, monkeypatch):
    fixed_now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    import mobile_auth

    monkeypatch.setattr(mobile_auth, "_utcnow", lambda: fixed_now)

    first_login = _mobile_login(client, username="alice", device_id="device-2fa-clear-confirm")
    assert first_login.status_code == 200
    token = first_login.get_json()["token"]

    setup_response = client.post(
        "/mobile/2fa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert setup_response.status_code == 200
    setup_payload = setup_response.get_json()
    setup_code = setup_payload["two_factor"]["setup_code"]
    assert setup_payload["two_factor"]["link_ticket"]

    confirm_response = client.post(
        "/mobile/2fa/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"otp_code": _otp_token_for_setup_code(setup_code)},
    )
    assert confirm_response.status_code == 200

    clear_response = client.post(
        "/mobile/2fa/clear",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert clear_response.status_code == 200
    clear_payload = clear_response.get_json()
    assert clear_payload["two_factor"]["enabled"] is True
    assert clear_payload["two_factor"]["grace_active"] is False
    assert clear_payload["two_factor"]["setup_pending"] is False

    reconfirm_setup_response = client.post(
        "/mobile/2fa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reconfirm_setup_response.status_code == 200
    reconfirm_payload = reconfirm_setup_response.get_json()
    reconfirm_code = reconfirm_payload["two_factor"]["setup_code"]
    assert reconfirm_payload["two_factor"]["enabled"] is True
    assert reconfirm_payload["two_factor"]["setup_pending"] is True
    assert len(reconfirm_code) == 6

    reconfirm_response = client.post(
        "/mobile/2fa/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"otp_code": _otp_token_for_setup_code(reconfirm_code)},
    )
    assert reconfirm_response.status_code == 200
    assert reconfirm_response.get_json()["two_factor"]["grace_active"] is True


def test_mobile_auth_two_factor_disable_clears_pending_setup(client, db, monkeypatch):
    fixed_now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    import mobile_auth

    monkeypatch.setattr(mobile_auth, "_utcnow", lambda: fixed_now)

    first_login = _mobile_login(client, username="alice", device_id="device-2fa-clear")
    assert first_login.status_code == 200
    token = first_login.get_json()["token"]

    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("alice", "125/1997", "Maric", "Filip")
    db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Linear Algebra", "M1.01"),
    )
    subject_id = db.subject("M1.01", "Linear Algebra", "A", "I")
    db.course_subject("M1.01", subject_id)
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    _add_enrollment(db, "alice", semester, subject_id, group_1o1)
    db.building_location("A", 10.0, 20.0, radius_m=100)
    db.execute(
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
        ("2026.07", "M1.01", "Linear Algebra", "2026-08-10", 11, "A"),
    )
    _add_exam_term(db, semester, "2026.07", "2026-08-10", "2026-08-10")

    setup_response = client.post(
        "/mobile/2fa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert setup_response.status_code == 200
    setup_payload = setup_response.get_json()
    assert setup_payload["two_factor"]["setup_pending"] is True
    assert setup_payload["two_factor"]["enabled"] is False
    assert setup_payload["two_factor"]["disabled"] is False
    assert len(setup_payload["two_factor"]["setup_code"]) == 6
    assert setup_payload["two_factor"]["link_ticket"]

    clear_response = client.post(
        "/mobile/2fa/disable",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert clear_response.status_code == 200
    clear_payload = clear_response.get_json()
    assert clear_payload["two_factor"]["enabled"] is False
    assert clear_payload["two_factor"]["setup_pending"] is False
    assert clear_payload["two_factor"]["disabled"] is True
    assert clear_payload["two_factor"].get("setup_code") is None

    disable_response = client.post(
        "/mobile/2fa/disable",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert disable_response.status_code == 200
    disable_payload = disable_response.get_json()
    assert disable_payload["two_factor"]["enabled"] is False
    assert disable_payload["two_factor"]["disabled"] is True

    disabled_apply_response = client.post(
        "/mobile/exam_applications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "term_code": "2026.07",
            "subject_id": subject_id,
            "applied": True,
        },
    )
    assert disabled_apply_response.status_code == 200
    disabled_apply_payload = disabled_apply_response.get_json()
    assert disabled_apply_payload["ok"] is True
    assert disabled_apply_payload["applied"] is True


def test_mobile_auth_review_login_bypasses_radius_and_uses_review_data(client, db, monkeypatch):
    import mobile_auth

    semester = db.semester(
        name="Review 2026",
        start="2026-01-01",
        end="2026-12-31",
    )
    room = db.room("R-review")
    teacher = db.teacher("Review Prof", "review-prof")
    course = db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Review Course", "Review Course"),
    )
    subject = db.subject("Review Course", "Review Course", 2026, "I")
    db.course_subject("Review Course", subject)
    group = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    db.student("mr97125", "97125", "Maric", "Filip")
    session = db.course_session(course, teacher, semester)
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
        (session, group),
    )
    db.weekly_session(
        session_id=session,
        room_id=room,
        day_of_week=1,
        start_slot=10,
        end_slot=12,
    )
    db.execute(
        """
        INSERT INTO student_enrollments
            (student_username, semester_id, subject_id, group_id, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("mr97125", semester, subject, group, "2026-08-13T00:00:00+00:00"),
    )

    radius_called = {"value": False}

    def fail_if_called(*args, **kwargs):
        radius_called["value"] = True
        raise AssertionError("RADIUS should not be called for the review account")

    monkeypatch.setattr(mobile_auth, "REVIEW_MODE", True)
    monkeypatch.setattr(mobile_auth, "student_radius_auth", fail_if_called)

    response = _mobile_login(client, username="google", password="review", device_id="review-device")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user"]["radius_username"] == "google"
    assert radius_called["value"] is False

    token = payload["token"]
    response = client.get(
        f"/mobile/timetable?semester_id={semester}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["student"]["username"] == "mr97125"
    assert [item["course_name"] for item in payload["enrollments"]] == ["Review Course"]
    assert [item["course_name"] for item in payload["events"]] == ["Review Course"]


def test_mobile_auth_attendance_history_returns_course_summary_for_current_semester(client, db, monkeypatch):
    import mobile_attendance

    current_semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    past_semester = db.semester(
        name="2025/26. јесењи",
        start="2025-10-01",
        end="2026-02-28",
    )
    room = db.room("R1")
    teacher = db.teacher("Prof", "alice")
    course = db.course("NumericalMethods")
    current_session = db.course_session(course, teacher, current_semester)
    past_session = db.course_session(course, teacher, past_semester)
    db.weekly_session(
        session_id=current_session,
        room_id=room,
        day_of_week=1,
        start_slot=10,
        end_slot=12,
    )
    db.execute(
        "INSERT INTO days (date, kind, week_day) VALUES (?, ?, ?)",
        ("2026-03-16", "teaching", 1),
    )
    db.weekly_session(
        session_id=past_session,
        room_id=room,
        day_of_week=1,
        start_slot=12,
        end_slot=14,
    )
    db.execute(
        """
        INSERT INTO attendance_records
            (event_kind, event_id, event_date, username, registration_source, client_ip, failed_attempts_before_success)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("weekly", current_session, "2026-03-09", "alice", "android", "198.51.100.10", 1),
    )

    token = _mobile_login(client, username="alice", device_id="device-history").get_json()["token"]
    response = client.get(
        "/mobile/attendance/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["current_semester"]["display_name"] == "2026/27. јесењи"
    assert payload["current_semester"]["name"] == "2026/27. јесењи"
    assert [item["course_name"] for item in payload["summaries"]] == ["NumericalMethods"]
    assert payload["summaries"][0]["attended_lessons"] == 1
    assert payload["summaries"][0]["total_lessons_with_recorded_attendance"] == 1


def test_mobile_timetable_returns_personalized_events(client, db):
    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.building_location("A", 10.0, 20.0, radius_m=100)
    room = db.room("R1")
    teacher = db.teacher("Prof A", "alice")
    other_teacher = db.teacher("Prof B", "bob")
    course_an1 = db.execute("INSERT INTO courses (name, code) VALUES (?, ?)", ("Analiza 1", "an1"))
    course_ang = db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Analiticka geometrija", "ang"),
    )
    subject_an1 = db.subject("an1", "Analiza 1", 2026, "I")
    subject_ang = db.subject("ang", "Analiticka geometrija", 2026, "I")
    db.course_subject("an1", subject_an1)
    db.course_subject("ang", subject_ang)
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    group_1o2 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o2",))
    db.student("student1", "125/1997", "Maric", "Filip")

    session_an1 = db.course_session(course_an1, teacher, semester, type="p")
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
        (session_an1, group_1o1),
    )
    db.weekly_session(session_an1, room, day_of_week=1, start_slot=10, end_slot=12)

    session_ang_1o1 = db.course_session(course_ang, other_teacher, semester, type="v")
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
        (session_ang_1o1, group_1o1),
    )
    db.weekly_session(session_ang_1o1, room, day_of_week=2, start_slot=12, end_slot=14)

    session_ang_1o2 = db.course_session(course_ang, other_teacher, semester, type="v")
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
        (session_ang_1o2, group_1o2),
    )
    db.weekly_session(session_ang_1o2, room, day_of_week=3, start_slot=12, end_slot=14)

    _add_enrollment(db, "student1", semester, subject_an1, group_1o1)
    _add_enrollment(db, "student1", semester, subject_ang, group_1o1)

    token = _mobile_login(client, username="student1", device_id="device-timetable").get_json()["token"]
    response = client.get("/mobile/timetable", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["student"]["username"] == "student1"
    assert payload["student"]["student_label"] == "Filip Maric (125/1997)"
    assert payload["semester"]["display_name"] == "2026/27. јесењи"
    assert payload["semester"]["name"] == "2026/27. јесењи"
    assert [item["course_code"] for item in payload["enrollments"]] == ["an1", "ang"]
    assert [item["course_code"] for item in payload["events"]] == ["an1", "ang"]
    assert [item["group_name"] for item in payload["events"]] == ["1o1", "1o1"]
    assert [item["day_of_week"] for item in payload["events"]] == [1, 2]
    assert payload["events"][0]["room_building_name"] == "A"
    assert payload["events"][0]["room_latitude"] == 10.0
    assert payload["events"][0]["room_longitude"] == 20.0
    assert all(item["group_name"] != "1o2" for item in payload["events"])


def test_mobile_exam_schedule_returns_personalized_exams(client, db):
    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "125/1997", "Maric", "Filip")
    course = db.execute("INSERT INTO courses (name, code) VALUES (?, ?)", ("Linear Algebra", "M1.01"))
    subject = db.subject("M1.01", "Linear Algebra", "A", "I")
    db.course_subject("M1.01", subject)
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    _add_enrollment(db, "student1", semester, subject, group_1o1)
    db.building_location("A", 10.0, 20.0, radius_m=100)
    db.building_location("B", 11.0, 21.0, radius_m=100)

    exam_060 = db.execute(
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
            "2026.06",
            "M1.01",
            "Linear Algebra",
            "2026-07-03",
            9,
            "A",
        ),
    )
    _add_exam_term(db, semester, "2026.06", "2026-07-03", "2026-07-03")
    exam_070 = db.execute(
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
            "2026.07",
            "M1.01",
            "Linear Algebra",
            "2026-08-10",
            11,
            "B",
        ),
    )
    _add_exam_term(db, semester, "2026.07", "2026-08-10", "2026-08-10")
    _add_exam_application(db, "2026.06", subject, "student1")
    _add_exam_application(db, "2026.07", subject, "student1")

    token = _mobile_login(client, username="student1", device_id="device-exam").get_json()["token"]
    response = client.get("/mobile/exam_schedule", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["student"]["username"] == "student1"
    assert payload["semester"]["display_name"] == "2026/27. јесењи"
    assert [item["term_code"] for item in payload["available_terms"]] == ["2026.07", "2026.06"]
    assert [item["start_date"] for item in payload["available_terms"]] == ["2026-08-10", "2026-07-03"]
    assert payload["selected_term_code"] == "2026.07"
    assert [item["course_code"] for item in payload["exams"]] == ["M1.01"]
    assert [item["exam_date"] for item in payload["exams"]] == ["2026-08-10"]
    assert [item["subject_name"] for item in payload["exams"]] == ["Linear Algebra"]

    response = client.get(
        "/mobile/exam_schedule",
        headers={"Authorization": f"Bearer {token}"},
        query_string={"term_code": "2026.06"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["selected_term_code"] == "2026.06"
    assert [item["exam_date"] for item in payload["exams"]] == ["2026-07-03"]


def test_mobile_exam_schedule_supports_all_subjects_mode(client, db):
    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "125/1997", "Maric", "Filip")
    course_applied = db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Linear Algebra", "M1.01"),
    )
    course_unapplied = db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Probability", "M1.02"),
    )
    subject_applied = db.subject("M1.01", "Linear Algebra", "A", "I")
    subject_unapplied = db.subject("M1.02", "Probability", "A", "I")
    db.course_subject("M1.01", subject_applied)
    db.course_subject("M1.02", subject_unapplied)
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    db.building_location("A", 10.0, 20.0, radius_m=100)
    db.building_location("B", 11.0, 21.0, radius_m=100)
    _add_enrollment(db, "student1", semester, subject_applied, group_1o1)
    _add_enrollment(db, "student1", semester, subject_unapplied, group_1o1)

    db.execute(
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
        ("2026.07", "M1.01", "Linear Algebra", "2026-08-10", 11, "A"),
    )
    db.execute(
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
        ("2026.07", "M1.02", "Probability", "2026-08-11", 10, "B"),
    )
    _add_exam_term(db, semester, "2026.07", "2026-08-10", "2026-08-11")
    _add_exam_application(db, "2026.07", subject_applied, "student1")

    token = _mobile_login(client, username="student1", device_id="device-exam-all").get_json()["token"]

    response = client.get("/mobile/exam_schedule", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()
    assert [item["course_code"] for item in payload["exams"]] == ["M1.01"]

    response = client.get(
        "/mobile/exam_schedule",
        headers={"Authorization": f"Bearer {token}"},
        query_string={"mode": "all_subjects"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert [item["course_code"] for item in payload["exams"]] == ["M1.01", "M1.02"]
    assert [item["is_applied"] for item in payload["exams"]] == [True, False]


def test_mobile_exam_schedule_ignores_subject_code_exam_rows_in_all_subjects_mode(client, db):
    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "125/1997", "Maric", "Filip")
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))

    db.execute("INSERT INTO courses (name, code) VALUES (?, ?)", ("Linear Algebra", "lalgb"))
    subject_id = db.subject("M1.01", "Linear Algebra", 2022, "МР")
    db.course_subject("lalgb", subject_id)
    _add_enrollment(db, "student1", semester, subject_id, group_1o1)
    db.execute(
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
        ("2026.06", "M1.01", "Linear Algebra", "2026-07-03", 9, None),
    )
    _add_exam_term(db, semester, "2026.06", "2026-06-26", "2026-07-09")
    token = _mobile_login(client, username="student1", device_id="device-exam-all").get_json()["token"]

    response = client.get(
        "/mobile/exam_schedule",
        headers={"Authorization": f"Bearer {token}"},
        query_string={"term_code": "2026.06", "mode": "all_subjects"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["exams"] == []


def test_mobile_exam_application_toggle_apply_and_cancel(client, db, monkeypatch):
    fixed_now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    later_now = fixed_now + timedelta(days=8)
    import mobile_auth

    monkeypatch.setattr(mobile_auth, "_utcnow", lambda: later_now)
    monkeypatch.setattr(mobile_auth, "HYPATIA_EXAM_APPLICATIONS_URL", "https://hypatia.example/api/exam-applications")
    monkeypatch.setattr(mobile_auth, "HYPATIA_REQUEST_SIGNING_SECRET", "test-hypatia-secret")

    captured_requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout=None):
        captured_requests.append(
            {
                "url": request.full_url,
                "headers": {key.lower(): value for key, value in request.header_items()},
                "timeout": timeout,
                "data": request.data.decode("utf-8") if request.data else "",
            }
        )
        return FakeResponse()

    monkeypatch.setattr(mobile_auth, "urlopen", fake_urlopen)

    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "125/1997", "Maric", "Filip")
    db.execute(
        "INSERT INTO courses (name, code) VALUES (?, ?)",
        ("Linear Algebra", "M1.01"),
    )
    subject_id = db.subject("M1.01", "Linear Algebra", "A", "I")
    db.course_subject("M1.01", subject_id)
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    _add_enrollment(db, "student1", semester, subject_id, group_1o1)
    db.building_location("A", 10.0, 20.0, radius_m=100)
    db.execute(
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
        ("2026.07", "M1.01", "Linear Algebra", "2026-08-10", 11, "A"),
    )
    _add_exam_term(db, semester, "2026.07", "2026-08-10", "2026-08-10")

    token = _mobile_login(client, username="student1", device_id="device-toggle").get_json()["token"]

    setup_response = client.post(
        "/mobile/2fa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert setup_response.status_code == 200
    setup_payload = setup_response.get_json()
    setup_code = setup_payload["two_factor"]["setup_code"]
    assert setup_payload["two_factor"]["link_ticket"]
    confirm_response = client.post(
        "/mobile/2fa/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"otp_code": _otp_token_for_setup_code(setup_code)},
    )
    assert confirm_response.status_code == 200
    db.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_last_verified_at = ?
        WHERE radius_username = ?
        """,
        ((fixed_now - timedelta(days=8)).isoformat(), "student1"),
    )

    apply_response = client.post(
        "/mobile/exam_applications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "term_code": "2026.07",
            "subject_id": subject_id,
            "applied": True,
        },
    )
    assert apply_response.status_code == 401
    apply_payload = apply_response.get_json()
    assert apply_payload["error_code"] == "two_factor_required"

    confirm_again = client.post(
        "/mobile/2fa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_again.status_code == 200
    confirm_again_code = confirm_again.get_json()["two_factor"]["setup_code"]
    confirm_again_response = client.post(
        "/mobile/2fa/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"otp_code": _otp_token_for_setup_code(confirm_again_code)},
    )
    assert confirm_again_response.status_code == 200

    apply_response = client.post(
        "/mobile/exam_applications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "term_code": "2026.07",
            "subject_id": subject_id,
            "applied": True,
        },
    )
    assert apply_response.status_code == 200
    payload = apply_response.get_json()
    assert payload["ok"] is True
    assert payload["term_code"] == "2026.07"
    assert payload["subject_id"] == subject_id
    assert payload["applied"] is True

    cancel_response = client.post(
        "/mobile/exam_applications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "term_code": "2026.07",
            "subject_id": subject_id,
            "applied": False,
        },
    )
    assert cancel_response.status_code == 200
    cancel_payload = cancel_response.get_json()
    assert cancel_payload["ok"] is True
    assert cancel_payload["applied"] is False
    assert len(captured_requests) == 2
    assert captured_requests[0]["url"] == "https://hypatia.example/api/exam-applications"
    assert captured_requests[0]["timeout"] == 10
    assert captured_requests[0]["headers"]["x-request-timestamp"].isdigit()
    assert len(captured_requests[0]["headers"]["x-request-nonce"]) > 0
    assert '"student_username":"student1"' in captured_requests[0]["data"]
    assert '"applied":true' in captured_requests[0]["data"]
    assert '"applied":false' in captured_requests[1]["data"]

    with db.app.app_context():
        row = myapp.query_db(
            """
            SELECT term_code, subject_id, student_username
            FROM exam_applications
            WHERE term_code = ? AND subject_id = ? AND student_username = ?
            """,
            ("2026.07", subject_id, "student1"),
            one=True,
        )
    assert row is None


def test_mobile_exam_application_rejected_by_hypatia_does_not_apply(client, db, monkeypatch):
    fixed_now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    import mobile_auth

    monkeypatch.setattr(mobile_auth, "_utcnow", lambda: fixed_now)
    monkeypatch.setattr(mobile_auth, "HYPATIA_EXAM_APPLICATIONS_URL", "https://hypatia.example/api/exam-applications")
    monkeypatch.setattr(mobile_auth, "HYPATIA_REQUEST_SIGNING_SECRET", "test-hypatia-secret")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                '{"ok": false, "error_code": "fee_not_paid", "error": "Student did not yet pay the fee.", "status_code": 403}'
            ).encode("utf-8")

    monkeypatch.setattr(mobile_auth, "urlopen", lambda request, timeout=None: FakeResponse())

    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "125/1997", "Maric", "Filip")
    db.execute("INSERT INTO courses (name, code) VALUES (?, ?)", ("Linear Algebra", "M1.01"))
    subject_id = db.subject("M1.01", "Linear Algebra", "1", "МР")
    db.course_subject("M1.01", subject_id)
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    _add_enrollment(db, "student1", semester, subject_id, group_1o1)
    db.execute(
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
        ("2026.07", "M1.01", "Linear Algebra", "2026-08-10", 11, None),
    )
    _add_exam_term(db, semester, "2026.07", "2026-08-10", "2026-08-10")

    token = _mobile_login(client, username="student1", device_id="device-toggle-denied").get_json()["token"]
    db.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_enabled = 1,
            two_factor_last_verified_at = ?
        WHERE radius_username = ?
        """,
        (fixed_now.isoformat(), "student1"),
    )

    response = client.post(
        "/mobile/exam_applications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "term_code": "2026.07",
            "subject_id": subject_id,
            "applied": True,
        },
    )
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["error_code"] == "fee_not_paid"
    assert payload["error"] == "Student did not yet pay the fee."

    with db.app.app_context():
        row = myapp.query_db(
            """
            SELECT term_code, subject_id, student_username
            FROM exam_applications
            WHERE term_code = ? AND subject_id = ? AND student_username = ?
            """,
            ("2026.07", subject_id, "student1"),
            one=True,
    )
    assert row is None


def test_mobile_exam_application_rejected_by_hypatia_does_not_cancel(client, db, monkeypatch):
    fixed_now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    import mobile_auth

    monkeypatch.setattr(mobile_auth, "_utcnow", lambda: fixed_now)
    monkeypatch.setattr(mobile_auth, "HYPATIA_EXAM_APPLICATIONS_URL", "https://hypatia.example/api/exam-applications")
    monkeypatch.setattr(mobile_auth, "HYPATIA_REQUEST_SIGNING_SECRET", "test-hypatia-secret")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                '{"ok": false, "error_code": "already_paid", "error": "Application cancellation is not allowed right now.", "status_code": 409}'
            ).encode("utf-8")

    monkeypatch.setattr(mobile_auth, "urlopen", lambda request, timeout=None: FakeResponse())

    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student1", "125/1997", "Maric", "Filip")
    db.execute("INSERT INTO courses (name, code) VALUES (?, ?)", ("Linear Algebra", "M1.01"))
    subject_id = db.subject("M1.01", "Linear Algebra", "1", "МР")
    db.course_subject("M1.01", subject_id)
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    _add_enrollment(db, "student1", semester, subject_id, group_1o1)
    db.execute(
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
        ("2026.07", "M1.01", "Linear Algebra", "2026-08-10", 11, None),
    )
    _add_exam_term(db, semester, "2026.07", "2026-08-10", "2026-08-10")
    db.execute(
        "INSERT INTO exam_applications (term_code, subject_id, student_username) VALUES (?, ?, ?)",
        ("2026.07", subject_id, "student1"),
    )

    token = _mobile_login(client, username="student1", device_id="device-toggle-denied-cancel").get_json()["token"]
    db.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_enabled = 1,
            two_factor_last_verified_at = ?
        WHERE radius_username = ?
        """,
        (fixed_now.isoformat(), "student1"),
    )

    response = client.post(
        "/mobile/exam_applications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "term_code": "2026.07",
            "subject_id": subject_id,
            "applied": False,
        },
    )
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["error_code"] == "already_paid"
    assert payload["error"] == "Application cancellation is not allowed right now."

    with db.app.app_context():
        row = myapp.query_db(
            """
            SELECT term_code, subject_id, student_username
            FROM exam_applications
            WHERE term_code = ? AND subject_id = ? AND student_username = ?
            """,
            ("2026.07", subject_id, "student1"),
            one=True,
        )
    assert row is not None


def test_mobile_timetable_returns_empty_lists_for_student_without_enrollments(client, db):
    semester = db.semester(
        name="Current 2026",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student2", "126/1997", "Petrovic", "Mila")
    token = _mobile_login(client, username="student2", device_id="device-empty").get_json()["token"]

    response = client.get("/mobile/timetable", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["semester"]["id"] == semester
    assert payload["enrollments"] == []
    assert payload["events"] == []


def test_mobile_timetable_rejects_invalid_semester(client, db):
    db.student("student3", "127/1997", "Jovanovic", "Lena")
    token = _mobile_login(client, username="student3", device_id="device-invalid-semester").get_json()["token"]

    response = client.get(
        "/mobile/timetable?semester_id=999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.get_json()["error"] == "semester_not_found"


def test_mobile_notifications_inbox_and_mark_read(client, db):
    semester = db.semester(
        name="Current 2026",
        start="2026-01-01",
        end="2026-12-31",
    )
    db.student("student4", "128/1997", "Petrovic", "Mina")
    teacher = db.teacher("Prof C", "prof.c")
    course = db.course("OperatingSystems")
    group_1o1 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))
    group_1o2 = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o2",))

    notification_id = _add_notification(
        db,
        source_id="central-1",
        semester_id=semester,
        course_id=course,
        teacher_username="prof.c",
        title="Laboratory postponed",
        body="Today's lab is moved to next week.",
        published_at="2026-08-12T10:00:00+00:00",
    )
    _add_notification_target(db, notification_id, group_1o1)
    _add_notification_target(db, notification_id, group_1o2)
    _add_notification_recipient(db, notification_id, "student4")

    token = _mobile_login(client, username="student4", device_id="device-notifications").get_json()["token"]

    response = client.get("/mobile/notifications", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["unread_count"] == 1
    assert len(payload["notifications"]) == 1
    assert payload["notifications"][0]["title"] == "Laboratory postponed"
    assert payload["notifications"][0]["target_groups"] == ["1o1", "1o2"]
    assert payload["notifications"][0]["is_read"] is False

    response = client.get("/mobile/notifications/unread_count", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json()["unread_count"] == 1

    response = client.post(
        f"/mobile/notifications/{notification_id}/read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    response = client.get("/mobile/notifications/unread_count", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json()["unread_count"] == 0


def test_mobile_notifications_mark_all_read(client, db):
    semester = db.semester(name="2026/27. јесењи", start="2026-01-01", end="2026-12-31")
    course = db.course("Course A")
    db.teacher("Teacher A", "teacher.a")
    db.student("student4", "128/1997", "Petrovic", "Mina")
    group = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))

    notification_1 = _add_notification(
        db,
        source_id="batch-1",
        semester_id=semester,
        course_id=course,
        teacher_username="teacher.a",
        title="First notice",
        body="First body",
        published_at="2026-08-12T10:00:00+00:00",
    )
    notification_2 = _add_notification(
        db,
        source_id="batch-2",
        semester_id=semester,
        course_id=course,
        teacher_username="teacher.a",
        title="Second notice",
        body="Second body",
        published_at="2026-08-12T11:00:00+00:00",
    )
    _add_notification_target(db, notification_1, group)
    _add_notification_target(db, notification_2, group)
    _add_notification_recipient(db, notification_1, "student4")
    _add_notification_recipient(db, notification_2, "student4")

    token = _mobile_login(client, username="student4", device_id="device-mark-all").get_json()["token"]

    response = client.get("/mobile/notifications", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json()["unread_count"] == 2

    response = client.post("/mobile/notifications/mark_all_read", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["updated_count"] == 2
    assert payload["unread_count"] == 0

    response = client.get("/mobile/notifications", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["unread_count"] == 0
    assert all(item["is_read"] for item in payload["notifications"])


def test_mobile_notifications_delete_removes_only_current_students_copy(client, db):
    semester = db.semester(name="2026/27. јесењи", start="2026-01-01", end="2026-12-31")
    course = db.course("Course A")
    db.teacher("Teacher A", "teacher.a")
    db.student("student4", "128/1997", "Petrovic", "Mina")
    db.student("student5", "129/1997", "Ilic", "Ana")
    group = db.execute("INSERT INTO groups (name) VALUES (?)", ("1o1",))

    notification_id = _add_notification(
        db,
        source_id="delete-1",
        semester_id=semester,
        course_id=course,
        teacher_username="teacher.a",
        title="Delete me",
        body="Delete body",
        published_at="2026-08-12T10:00:00+00:00",
    )
    _add_notification_target(db, notification_id, group)
    _add_notification_recipient(db, notification_id, "student4")
    _add_notification_recipient(db, notification_id, "student5")

    token = _mobile_login(client, username="student4", device_id="device-delete").get_json()["token"]

    response = client.delete(
        f"/mobile/notifications/{notification_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["unread_count"] == 0

    response = client.get("/mobile/notifications", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json()["notifications"] == []

    stored_notification = myapp.query_db(
        "SELECT id FROM notifications WHERE id = ?",
        (notification_id,),
        one=True,
    )
    assert stored_notification is not None

    other_token = _mobile_login(client, username="student5", device_id="device-delete-2").get_json()["token"]
    response = client.get("/mobile/notifications", headers={"Authorization": f"Bearer {other_token}"})
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["notifications"]) == 1
    assert payload["notifications"][0]["title"] == "Delete me"


def test_mobile_installation_id_registration_and_logout_removes_token(client, db):
    db.student("student5", "129/1997", "Ilic", "Ana")
    token = _mobile_login(client, username="student5", device_id="device-push").get_json()["token"]

    response = _register_installation_id(client, token, installation_id="installation-id-student5")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}

    row = myapp.query_db(
        """
        SELECT device_id, student_username, device_name, platform, installation_id, enabled
        FROM mobile_devices
        WHERE device_id = ?
        """,
        ("device-push",),
        one=True,
    )
    assert row is not None

    response = client.post("/mobile/logout", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    row = myapp.query_db(
        "SELECT device_id FROM mobile_devices WHERE device_id = ?",
        ("device-push",),
        one=True,
    )
    assert row is None


def test_mobile_installation_id_registration_requires_installation_id(client, db):
    db.student("student5", "129/1997", "Ilic", "Ana")
    token = _mobile_login(client, username="student5", device_id="device-push").get_json()["token"]

    response = client.post(
        "/mobile/push-token",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "platform": "android",
        },
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "installation_id_required"}


def test_mobile_push_test_endpoint_sends_to_one_device(client, db, monkeypatch):
    import mobile_push

    db.student("student6", "130/1997", "Markovic", "Jelena")
    token = _mobile_login(client, username="student6", device_id="device-push-test").get_json()["token"]
    _register_installation_id(client, token, installation_id="installation-id-student6")

    calls = []

    def fake_send_one_push(installation_id, title, body, notification_id):
        calls.append((installation_id, title, body, notification_id))
        return {"ok": True, "message_id": "test-message"}

    monkeypatch.setattr(mobile_push, "_send_one_push", fake_send_one_push)

    response = client.post(
        "/service/mobile/push-test",
        headers={"Authorization": f"Bearer {myapp.app.config['BACKEND_SERVICE_BEARER_TOKEN']}"},
        json={
            "device_id": "device-push-test",
            "title": "Verification",
            "body": "Hello from backend",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["device_id"] == "device-push-test"
    assert calls == [("installation-id-student6", "Verification", "Hello from backend", 0)]


def test_fcm_payload_is_data_only_and_high_priority(monkeypatch):
    import mobile_push

    sent_requests = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"name": "projects/matf-app/messages/123"}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent_requests.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(mobile_push, "_load_access_token", lambda: "test-access-token")
    monkeypatch.setattr(mobile_push.requests, "post", fake_post)

    result = mobile_push._send_one_push("push-token-xyz", "Title", "Body", notification_id=42)

    assert result == {"name": "projects/matf-app/messages/123"}
    assert len(sent_requests) == 1
    payload = sent_requests[0]["json"]
    assert payload["message"]["token"] == "push-token-xyz"
    assert payload["message"]["data"] == {
        "notification_id": "42",
        "title": "Title",
        "body": "Body",
    }
    assert "notification" not in payload["message"]
    assert payload["message"]["android"] == {"priority": "HIGH"}


def test_mobile_grades_returns_example_csv_rows_for_student(client, db, monkeypatch):
    import mobile_grades

    db.student("mr97125", "97125", "Maric", "Filip")
    token = _mobile_login(client, username="mr97125", device_id="device-grades").get_json()["token"]

    db.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_enabled = 1,
            two_factor_last_verified_at = ?
        WHERE radius_username = ?
        """,
        ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "mr97125"),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                "student_username,subject_code,subject_name,accreditation,semester,ects,grade,date,school_year,confirmed\n"
                "mr97125,M1.01,Linearna algebra,1,I,6,10,2026-06-25,2025/26,1\n"
                "mr97125,PPJ,Programski prevodioci,2,V,6,9,2026-07-02,2025/26,1\n"
                "mr97125,ASP,Algoritmi i strukture podataka,1,III,6,8,2026-07-08,2025/26,0\n"
            ).encode("utf-8")

    monkeypatch.setenv("GRADES_SOURCE_URL", "https://grades.example.edu/api/grades")
    monkeypatch.setenv("GRADES_REQUEST_SIGNING_SECRET", "test-grades-secret")
    monkeypatch.setattr(
        mobile_grades,
        "urlopen",
        lambda request, timeout=None: FakeResponse(),
    )

    response = client.get("/mobile/grades", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["student"]["username"] == "mr97125"
    assert len(payload["grades"]) >= 3
    first = payload["grades"][0]
    assert first["subject_code"]
    assert first["subject_name"]
    assert first["accreditation"]
    assert first["semester"]
    assert first["grade"]
    assert first["date"]
    assert first["school_year"]
    assert first["confirmed"] is True


def test_mobile_grades_signs_upstream_request_with_nonce_and_timestamp(client, db, monkeypatch):
    import mobile_grades

    db.student("mr97125", "97125", "Maric", "Filip")
    token = _mobile_login(client, username="mr97125", device_id="device-grades-signed").get_json()["token"]

    db.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_enabled = 1,
            two_factor_last_verified_at = ?
        WHERE radius_username = ?
        """,
        ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "mr97125"),
    )

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                "student_username,subject_code,accreditation,semester,ects,grade,date,school_year,confirmed\n"
                "mr97125,M1.01,1,I,6,10,2026-07-01,2026/27,1\n"
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("GRADES_SOURCE_URL", "https://grades.example.edu/api/grades")
    monkeypatch.setenv("GRADES_REQUEST_SIGNING_SECRET", "test-grades-secret")
    monkeypatch.setattr(mobile_grades, "urlopen", fake_urlopen)

    response = client.get("/mobile/grades", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["student"]["username"] == "mr97125"
    assert len(payload["grades"]) == 1
    assert captured["url"] == "https://grades.example.edu/api/grades?student_username=mr97125"
    assert captured["timeout"] == 10
    assert captured["headers"]["x-request-timestamp"].isdigit()
    assert len(captured["headers"]["x-request-nonce"]) > 0

    import hypatia_request

    expected_payload = hypatia_request.build_canonical_payload(
        "GET",
        "/api/grades?student_username=mr97125",
        ["student_username=mr97125"],
        captured["headers"]["x-request-timestamp"],
        captured["headers"]["x-request-nonce"],
    )
    expected_signature = hypatia_request.sign_payload("test-grades-secret", expected_payload)
    assert captured["headers"]["x-request-signature"] == expected_signature


def test_mobile_grades_requires_confirmed_two_factor(client, db):
    db.student("mr97125", "97125", "Maric", "Filip")
    login = _mobile_login(client, username="mr97125", device_id="device-grades-2fa")
    assert login.status_code == 200
    token = login.get_json()["token"]

    db.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_enabled = 1,
            two_factor_last_verified_at = '2020-01-01T00:00:00+00:00'
        WHERE radius_username = ?
        """,
        ("mr97125",),
    )

    response = client.get("/mobile/grades", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.get_json()["error_code"] == "two_factor_required"
