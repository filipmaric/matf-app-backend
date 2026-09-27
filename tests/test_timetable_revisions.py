# Copyright (c) 2026 Filip Marić. See LICENCE.

from db import student_enrollment_revision, timetable_revision_for_semester


def test_timetable_and_student_enrollment_revisions_are_independent(db):
    semester = db.semester(
        name="2026/27. јесењи",
        start="2026-01-01",
        end="2026-12-31",
    )
    student = "student-revisions"
    db.student(student, "130/1997", "Rev", "Student")
    teacher = db.teacher("Revision Teacher", "revision.teacher")
    course = db.course("Revision Course")
    subject = db.subject("rev", "Revision Course", 2026, "I")
    group = db.execute("INSERT INTO groups (name) VALUES (?)", ("1r",))
    room = db.room("Revision Room")

    with db.app.app_context():
        initial_timetable = timetable_revision_for_semester(semester)
        initial_enrollments = student_enrollment_revision(student, semester)

    session = db.course_session(course, teacher, semester)
    db.execute(
        "INSERT INTO session_groups (session_id, group_id) VALUES (?, ?)",
        (session, group),
    )
    db.weekly_session(session, room, day_of_week=1, start_slot=8, end_slot=10)

    with db.app.app_context():
        after_timetable = timetable_revision_for_semester(semester)
        after_schedule_enrollments = student_enrollment_revision(student, semester)

    assert after_timetable > initial_timetable
    assert after_schedule_enrollments == initial_enrollments

    db.execute(
        """
        INSERT INTO student_enrollments
            (student_username, semester_id, subject_id, group_id)
        VALUES (?, ?, ?, ?)
        """,
        (student, semester, subject, group),
    )

    with db.app.app_context():
        after_enrollment = student_enrollment_revision(student, semester)
        after_enrollment_timetable = timetable_revision_for_semester(semester)

    assert after_enrollment > after_schedule_enrollments
    assert after_enrollment_timetable == after_timetable
