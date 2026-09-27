# Copyright (c) 2026 Filip Marić. See LICENCE.
from collections import Counter


def seed_teacher_sessions(db):
    legacy_fall = db.semester("2025/26. јесењи", "2025-10-01", "2026-02-28")
    fall = db.semester("2026/27. јесењи", "2026-10-01", "2027-02-28")
    spring = db.semester("2026/27. пролећни", "2027-03-01", "2027-09-30")

    db.execute(
        "INSERT INTO groups (name, description) VALUES (?, NULL)",
        ("g1",),
    )
    db.execute(
        "INSERT INTO groups (name, description) VALUES (?, NULL)",
        ("g2",),
    )

    teacher_a = db.teacher("Prof A", "prof.a")
    teacher_b = db.teacher("Prof B", "prof.b")
    course_a = db.course("Algebra")
    course_b = db.course("Programming")
    room = db.room("R1")

    session_a1 = db.course_session(course_a, teacher_a, fall, "p")
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, (SELECT id FROM groups WHERE name = ?))",
        (session_a1, "g1"),
    )
    db.weekly_session(session_a1, room, 0, 8, 10)

    session_a2 = db.course_session(course_b, teacher_a, spring, "v")
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, (SELECT id FROM groups WHERE name = ?))",
        (session_a2, "g2"),
    )
    db.weekly_session(session_a2, room, 2, 12, 14)

    session_legacy = db.course_session(course_b, teacher_b, legacy_fall, "l")
    db.weekly_session(session_legacy, room, 4, 10, 12)

    db.course_session(course_b, teacher_b, fall, "l")

    return teacher_a, teacher_b


def test_teacher_sessions_page_and_data(client, db):
    teacher_a, teacher_b = seed_teacher_sessions(db)

    page = client.get("/teacher_sessions?academic_year=2026/27&season=both")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Наставнички часови" in body
    assert "academic-year-select" in body
    assert "season-select" in body
    assert "teacher-select" in body

    data = client.get("/teacher_sessions_data?academic_year=2026/27&season=both")
    assert data.status_code == 200
    payload = data.get_json()
    assert payload["academic_year"] == "2026/27"
    assert payload["season"] == "both"
    assert [item["academic_year"] for item in payload["academic_years"]] == ["2026/27", "2025/26"]
    assert len(payload["teachers"]) == 2
    assert payload["selected_teacher"]["id"] == teacher_a
    assert len(payload["sessions"]) == 2
    assert Counter(session["semester_display_name"] for session in payload["sessions"]) == {
        "2026/27. јесењи": 1,
        "2026/27. пролећни": 1,
    }
    assert payload["sessions"][0]["weekly_sessions"]

    filtered = client.get(f"/teacher_sessions_data?academic_year=2026/27&season=fall&teacher_id={teacher_b}")
    assert filtered.status_code == 200
    filtered_payload = filtered.get_json()
    assert filtered_payload["season"] == "fall"
    assert filtered_payload["selected_teacher"]["id"] == teacher_b
    assert len(filtered_payload["sessions"]) == 1

    spring = client.get("/teacher_sessions_data?academic_year=2026/27&season=spring")
    assert spring.status_code == 200
    spring_payload = spring.get_json()
    assert spring_payload["season"] == "spring"
    assert len(spring_payload["teachers"]) == 1
    assert spring_payload["selected_teacher"]["id"] == teacher_a
    assert len(spring_payload["sessions"]) == 1

    legacy = client.get("/teacher_sessions_data?academic_year=2025/26&season=both")
    assert legacy.status_code == 200
    legacy_payload = legacy.get_json()
    assert legacy_payload["academic_year"] == "2025/26"
    assert legacy_payload["season"] == "both"
    assert legacy_payload["selected_teacher"]["id"] == teacher_b
    assert len(legacy_payload["teachers"]) == 1
    assert len(legacy_payload["sessions"]) == 1
