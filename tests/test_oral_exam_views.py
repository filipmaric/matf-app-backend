# Copyright (c) 2026 Filip Marić. See LICENCE.

from db import query_db

def login(client, username="alice", password="secret"):
    return client.post("/login", json={"username": username, "password": password})


def make_teacher_course_and_groups(db):
    semester_id = db.semester()
    teacher_id = db.teacher("Prof", "alice")
    course_id = db.course("Анализа 1")
    db.execute("UPDATE courses SET code = ? WHERE id = ?", ("an1", course_id))
    session_id = db.course_session(course_id, teacher_id, semester_id)
    first_group_id = db.execute("INSERT INTO groups (name) VALUES (?)", ("1i1a",))
    second_group_id = db.execute("INSERT INTO groups (name) VALUES (?)", ("1i1b",))
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
        (session_id, first_group_id),
    )
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
        (session_id, second_group_id),
    )
    db.execute(
        """INSERT INTO exam_terms
           (term_code, start_date, end_date, semester_id)
           VALUES (?, ?, ?, ?)""",
        ("2026.10", "2026-10-05", "2026-10-16", semester_id),
    )
    return course_id


def test_oral_exam_selection_defaults_to_current_term_and_lists_teacher_courses(client, db):
    course_id = make_teacher_course_and_groups(db)
    login(client)

    response = client.get("/oral_exams_data")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["selected_term"]["term_code"] == "2026.10"
    assert payload["terms"][0]["label"] == "2026.10"
    assert [session["course_id"] for session in payload["sessions"]] == [course_id]
    assert payload["groups"] == []
    assert payload["written_exams"] == []


def test_oral_exam_selection_lists_groups_for_selected_teacher_course(client, db):
    course_id = make_teacher_course_and_groups(db)
    login(client)

    with client.application.app_context():
        session_id = query_db("SELECT id FROM course_sessions LIMIT 1", one=True)["id"]
    response = client.get(f"/oral_exams_data?session_id={session_id}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["selected_session"]["course_id"] == course_id
    assert [group["name"] for group in payload["groups"]] == ["1i1a", "1i1b"]


def test_oral_exam_selection_lists_written_exam_for_selected_course_and_term(client, db):
    course_id = make_teacher_course_and_groups(db)
    db.execute("UPDATE courses SET code = ? WHERE id = ?", ("an1", course_id))
    with client.application.app_context():
        session_id = query_db("SELECT id FROM course_sessions LIMIT 1", one=True)["id"]
    with client.application.app_context():
        semester_id = query_db("SELECT id FROM semesters LIMIT 1", one=True)["id"]
    db.student("student1", "1/2024", "Student", "One")
    own_subject_id = db.subject("AN1", "Анализа 1", 2024, "И", 1)
    exam_subject_id = db.subject("ALG1", "Алгоритми 1", 2024, "И", 1)
    db.course_subject("an1", own_subject_id)
    db.execute(
        "INSERT INTO exam_applications (term_code, subject_id, student_username) VALUES (?, ?, ?), (?, ?, ?)",
        ("2026.10", own_subject_id, "student1", "2026.10", exam_subject_id, "student1"),
    )
    with client.application.app_context():
        group_id = query_db("SELECT id FROM groups ORDER BY id LIMIT 1", one=True)["id"]
    db.execute(
        "INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id) VALUES (?, ?, ?, ?)",
        ("student1", semester_id, own_subject_id, group_id),
    )
    # Exam applicants are restricted to the groups that actually take the
    # written exam, so the fixture must record the corresponding enrollment.
    db.execute(
        "INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id) VALUES (?, ?, ?, ?)",
        ("student1", semester_id, exam_subject_id, group_id),
    )
    other_course_id = db.course("Алгоритми 1")
    db.execute("UPDATE courses SET code = ? WHERE id = ?", ("alg1", other_course_id))
    db.course_subject("alg1", exam_subject_id)
    other_session_id = db.course_session(other_course_id, db.teacher("Other", "other"), semester_id)
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) SELECT ?, id FROM groups",
        (other_session_id,),
    )
    db.execute(
        """INSERT INTO exam_schedule
           (term_code, course_code, course_name, exam_date, exam_hour, location)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("2026.10", "an1", "Анализа 1", "2026-10-10", 9, None),
    )
    db.execute(
        """INSERT INTO exam_schedule
           (term_code, course_code, course_name, exam_date, exam_hour, location)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("2026.10", "alg1", "Алгоритми 1", "2026-10-12", 11, None),
    )
    db.execute(
        """INSERT INTO oral_exam_schedule
           (term_code, course_session_id, exam_date, start_hour, end_hour, teacher_username)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("2026.10", other_session_id, "2026-10-13", 9, 12, "other"),
    )
    login(client)

    response = client.get(f"/oral_exams_data?session_id={session_id}&term_code=2026.10")

    assert response.status_code == 200
    assert response.get_json()["written_exams"] == [
        {
            "course_code": "an1",
            "course_name": "Анализа 1",
            "exam_date": "2026-10-10",
            "exam_hour": 9,
            "location": None,
                "group_names": "1i1a,1i1b",
                "my_student_count": 1,
                "my_student_total": 1,
                "overlap_percentage": 100.0,
        },
        {
            "course_code": "alg1",
            "course_name": "Алгоритми 1",
            "exam_date": "2026-10-12",
            "exam_hour": 11,
            "location": None,
                "group_names": "1i1a,1i1b",
                "my_student_count": 1,
                "my_student_total": 1,
                "overlap_percentage": 100.0,
        },
    ]
    assert response.get_json()["oral_exams"][0]["course_code"] == "alg1"
    assert response.get_json()["oral_exams"][0]["group_names"] == "1i1a,1i1b"


def test_written_exam_requires_applications_in_selected_term(client, db):
    course_id = make_teacher_course_and_groups(db)
    db.execute("UPDATE courses SET code = ? WHERE id = ?", ("an1", course_id))
    with client.application.app_context():
        session_id = query_db("SELECT id FROM course_sessions LIMIT 1", one=True)["id"]
        semester_id = query_db("SELECT id FROM semesters LIMIT 1", one=True)["id"]
    subject_id = db.execute(
        """
        INSERT INTO subjects (code, name, accreditation, module, year)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("AN1", "Анализа 1", 2024, "И", 1),
    )
    db.execute(
        "INSERT INTO course_subjects (course_code, subject_id) VALUES (?, ?)",
        ("an1", subject_id),
    )
    db.execute(
        """
        INSERT INTO exam_schedule
            (term_code, course_code, course_name, exam_date, exam_hour, location)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("2026.10", "an1", "Анализа 1", "2026-10-10", 9, None),
    )
    login(client)

    response = client.get(f"/oral_exams_data?session_id={session_id}")

    assert response.status_code == 200
    assert response.get_json()["written_exams"] == []


def test_written_exam_count_uses_exact_applicant_intersection(client, db):
    semester_id = db.semester()
    teacher_id = db.teacher("Prof", "alice")
    own_course_id = db.course("Лексичка анализа")
    db.execute("UPDATE courses SET code = ? WHERE id = ?", ("lex", own_course_id))
    own_session_id = db.course_session(own_course_id, teacher_id, semester_id)
    group_r = db.execute("INSERT INTO groups (name) VALUES (?)", ("3r",))
    group_r15 = db.execute("INSERT INTO groups (name) VALUES (?)", ("3r15",))
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?), (?, ?)",
        (own_session_id, group_r, own_session_id, group_r15),
    )
    db.execute(
        """INSERT INTO exam_terms
           (term_code, start_date, end_date, semester_id)
           VALUES (?, ?, ?, ?)""",
        ("2026.10", "2026-10-05", "2026-10-16", semester_id),
    )

    exam_course_id = db.course("Геометрија 4")
    db.execute("UPDATE courses SET code = ? WHERE id = ?", ("geo", exam_course_id))
    exam_session_id = db.course_session(
        exam_course_id, db.teacher("Other", "other"), semester_id
    )
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?), (?, ?)",
        (exam_session_id, group_r, exam_session_id, group_r15),
    )

    subjects = [
        ("LEX", "Лексичка анализа", 2022, "МР", 3, 16, "lex"),
        ("LEX", "Лексичка анализа", 2015, "МР", 3, 10, "lex"),
        ("GEO", "Геометрија 4", 2022, "МР", 3, 8, "geo"),
        ("GEO", "Геометрија 4", 2015, "МР", 3, 4, "geo"),
    ]
    subject_ids = {}
    for code, name, accreditation, module, year, count, course_code in subjects:
        subject_id = db.execute(
            """
            INSERT INTO subjects (code, name, accreditation, module, year)
            VALUES (?, ?, ?, ?, ?)
            """,
            (code, name, accreditation, module, year),
        )
        db.execute(
            "INSERT INTO course_subjects (course_code, subject_id) VALUES (?, ?)",
            (course_code, subject_id),
        )
        subject_ids[(course_code, accreditation)] = subject_id
    for index in range(1, 6):
        db.student(f"student{index}", f"{index}/2024", "Student", str(index))
    db.execute(
        """
        INSERT INTO exam_applications (term_code, subject_id, student_username)
        VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?), (?, ?, ?)
        """,
        (
            "2026.10", subject_ids[("lex", 2022)], "student1",
            "2026.10", subject_ids[("lex", 2022)], "student2",
            "2026.10", subject_ids[("lex", 2022)], "student3",
            "2026.10", subject_ids[("lex", 2022)], "student4",
        ),
    )
    for index in range(1, 5):
        db.execute(
            "INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id) VALUES (?, ?, ?, ?)",
            (
                f"student{index}",
                semester_id,
                subject_ids[("lex", 2022)],
                group_r if index <= 2 else group_r15,
            ),
        )
    # This teacher's selected session handles only 3r; 3r15 belongs to another session.
    db.execute(
        "DELETE FROM session_groups WHERE session_id = ? AND group_id = ?",
        (own_session_id, group_r15),
    )
    db.execute(
        """
        INSERT INTO exam_applications (term_code, subject_id, student_username)
        VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?)
        """,
        (
            "2026.10", subject_ids[("geo", 2022)], "student2",
            "2026.10", subject_ids[("geo", 2022)], "student3",
            "2026.10", subject_ids[("geo", 2022)], "student5",
        ),
    )
    # The written exam is offered to both groups, but only student2 belongs
    # to the selected teacher's group (3r).  The other applicants belong to
    # 3r15 and must not contribute to this overlap.
    db.execute(
        """
        INSERT INTO student_enrollments (student_username, semester_id, subject_id, group_id)
        VALUES (?, ?, ?, ?), (?, ?, ?, ?), (?, ?, ?, ?)
        """,
        (
            "student2", semester_id, subject_ids[("geo", 2022)], group_r,
            "student3", semester_id, subject_ids[("geo", 2022)], group_r15,
            "student5", semester_id, subject_ids[("geo", 2022)], group_r15,
        ),
    )
    db.execute(
        """
        INSERT INTO exam_schedule
            (term_code, course_code, course_name, exam_date, exam_hour, location)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("2026.10", "geo", "Геометрија 4", "2026-10-10", 9, None),
    )
    login(client)

    response = client.get(f"/oral_exams_data?session_id={own_session_id}")

    assert response.status_code == 200
    exam = response.get_json()["written_exams"][0]
    assert exam["my_student_count"] == 1
    assert exam["my_student_total"] == 2
    assert exam["overlap_percentage"] == 50.0


def test_oral_exam_selection_does_not_expose_another_teachers_course(client, db):
    make_teacher_course_and_groups(db)
    other_teacher_id = db.teacher("Other", "other.teacher")
    other_course_id = db.course("Други курс")
    db.execute("UPDATE courses SET code = ? WHERE id = ?", ("other", other_course_id))
    db.course_session(other_course_id, other_teacher_id, db.semester(
        name="2026/27. пролећни", start="2026-11-01", end="2027-02-01"
    ))
    login(client)

    response = client.get("/oral_exams_data")

    assert response.status_code == 200
    assert all(session["course_id"] != other_course_id for session in response.get_json()["sessions"])


def test_teacher_can_schedule_one_oral_exam_for_one_group(client, db):
    course_id = make_teacher_course_and_groups(db)
    db.execute("UPDATE courses SET code = ? WHERE id = ?", ("an1", course_id))
    with client.application.app_context():
        session_id = query_db("SELECT id FROM course_sessions LIMIT 1", one=True)["id"]
        group_id = query_db("SELECT id FROM groups ORDER BY id LIMIT 1", one=True)["id"]
    login(client)

    response = client.post(
        "/oral_exams_schedule",
        json={
            "term_code": "2026.10",
            "session_id": session_id,
            "exam_date": "2026-10-20",
            "start_hour": 9,
            "end_hour": 12,
        },
    )

    assert response.status_code == 201
    with client.application.app_context():
        row = query_db(
            "SELECT course_session_id, exam_date, start_hour, end_hour, reservation_id FROM oral_exam_schedule",
            one=True,
        )
    assert dict(row) == {
        "course_session_id": session_id,
        "exam_date": "2026-10-20",
        "start_hour": 9,
        "end_hour": 12,
        "reservation_id": None,
    }

    second_response = client.post(
        "/oral_exams_schedule",
        json={
            "term_code": "2026.10",
            "session_id": session_id,
            "exam_date": "2026-10-21",
            "start_hour": 13,
            "end_hour": 14,
        },
    )
    assert second_response.status_code == 201

    with client.application.app_context():
        schedule_ids = [
            row["id"] for row in query_db(
                "SELECT id FROM oral_exam_schedule ORDER BY id"
            )
        ]

    unauthorized_client = client
    login(unauthorized_client, "other")
    forbidden = unauthorized_client.delete(f"/oral_exams_schedule/{schedule_ids[0]}")
    assert forbidden.status_code == 403

    login(client, "alice")
    deleted = client.delete(f"/oral_exams_schedule/{schedule_ids[0]}")
    assert deleted.status_code == 200
    assert deleted.get_json() == {"success": True}


def test_teacher_can_reserve_a_room_for_an_existing_oral_exam(client, db):
    course_id = make_teacher_course_and_groups(db)
    db.execute("UPDATE courses SET code = ? WHERE id = ?", ("an1", course_id))
    with client.application.app_context():
        session_id = query_db("SELECT id FROM course_sessions LIMIT 1", one=True)["id"]
    room_id = db.room("821")
    login(client)

    oral = client.post(
        "/oral_exams_schedule",
        json={
            "term_code": "2026.10",
            "session_id": session_id,
            "exam_date": "2026-10-20",
            "start_hour": 9,
            "end_hour": 12,
        },
    )
    assert oral.status_code == 201
    with client.application.app_context():
        row = query_db(
            "SELECT reservation_id FROM oral_exam_schedule WHERE id = ?",
            (oral.get_json()["id"],),
            one=True,
        )
    assert row["reservation_id"] is None

    available = client.get(
        f"/oral_exams_schedule/{oral.get_json()['id']}/available_rooms"
    )
    assert available.status_code == 200
    assert {room["id"] for room in available.get_json()["rooms"]} == {room_id}

    reserve_response = client.post(
        f"/oral_exams_schedule/{oral.get_json()['id']}/reserve_room",
        json={"room_id": room_id},
    )
    assert reserve_response.status_code == 200
    with client.application.app_context():
        row = query_db(
            "SELECT reservation_id FROM oral_exam_schedule WHERE id = ?",
            (oral.get_json()["id"],),
            one=True,
        )
    assert row["reservation_id"] == reserve_response.get_json()["reservation_id"]

    cancelled = client.delete(
        f"/reservation/{reserve_response.get_json()['reservation_id']}"
    )
    assert cancelled.status_code == 200
    with client.application.app_context():
        row = query_db(
            "SELECT reservation_id FROM oral_exam_schedule WHERE id = ?",
            (oral.get_json()["id"],),
            one=True,
        )
    assert row["reservation_id"] is None

    with_reservation = client.post(
        "/oral_exams_schedule",
        json={
            "term_code": "2026.10",
            "session_id": session_id,
            "exam_date": "2026-10-21",
            "start_hour": 9,
            "end_hour": 12,
        },
    )
    assert with_reservation.status_code == 201
