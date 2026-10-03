# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Teacher selection page for oral-exam planning."""

import datetime
import sqlite3

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required
from werkzeug.exceptions import HTTPException

from calendar_common import is_schedule_day
from db import execute_db, query_db
from occupancy import check_day
from reservations import _create_single_reservation
from semester import current_semester_id, semester_by_id
from semester_utils import semester_display_name


bp = Blueprint("oral_exam_views", __name__)


def current_school_year_start():
    """Return the school year containing the current semester."""
    semester = semester_by_id(current_semester_id())
    return int(semester["academic_year_start"]) if semester and semester.get("academic_year_start") else None


def teacher_id_for_current_user():
    row = query_db(
        "SELECT id FROM teachers WHERE username = ?",
        (current_user.username,),
        one=True,
    )
    return int(row["id"]) if row else None


def exam_terms_for_school_year(academic_year_start):
    rows = query_db(
        """
        SELECT et.term_code,
               et.start_date,
               et.end_date,
               et.semester_id,
               s.season
        FROM exam_terms et
        JOIN semesters s ON s.id = et.semester_id
        WHERE s.academic_year_start = ?
        ORDER BY et.start_date, et.end_date, et.term_code
        """,
        (academic_year_start,),
    )
    today = datetime.date.today().isoformat()
    terms = []
    for row in rows:
        term = dict(row)
        term["label"] = term["term_code"]
        term["semester_display_name"] = semester_display_name(
            int(academic_year_start), str(term["season"])
        )
        terms.append(term)

    active = [term for term in terms if term["start_date"] <= today <= term["end_date"]]
    if active:
        selected = active[0]
    else:
        upcoming = [term for term in terms if term["start_date"] > today]
        selected = upcoming[0] if upcoming else (terms[-1] if terms else None)
    return terms, selected


def teacher_sessions_for_school_year(teacher_id, academic_year_start):
    rows = query_db(
        """
        SELECT cs.id,
               c.id AS course_id,
               c.name,
               c.code,
               s.season,
               GROUP_CONCAT(DISTINCT g.name) AS group_names
        FROM course_sessions cs
        JOIN courses c ON c.id = cs.course_id
        JOIN semesters s ON s.id = cs.semester_id
        LEFT JOIN session_groups sg ON sg.session_id = cs.id
        LEFT JOIN groups g ON g.id = sg.group_id
        WHERE cs.teacher_id = ?
          AND s.academic_year_start = ?
        GROUP BY cs.id, c.id, c.name, c.code, s.season
        ORDER BY c.name, c.code, cs.id
        """,
        (teacher_id, academic_year_start),
    )
    return [dict(row) for row in rows]


def groups_for_session(session_id):
    rows = query_db(
        """
        SELECT DISTINCT g.id, g.name, g.description, cs.semester_id,
               g.study_program, g.module, g.accreditation, g.study_year
        FROM course_sessions cs
        JOIN session_groups sg ON sg.session_id = cs.id
        JOIN groups g ON g.id = sg.group_id
        JOIN courses c ON c.id = cs.course_id
        WHERE cs.id = ?
        ORDER BY g.name, g.id
        """,
        (session_id,),
    )
    return [dict(row) for row in rows]


def _application_usernames_for_session(session_id, term_code, group_ids=None):
    """Return applicants belonging to a course session, optionally by group."""
    group_filter = ""
    group_params = []
    if group_ids:
        placeholders = ",".join("?" for _ in group_ids)
        group_filter = f"AND sg.group_id IN ({placeholders})"
        group_params.extend(group_ids)
    rows = query_db(
        f"""
        SELECT DISTINCT a.student_username
        FROM course_sessions cs
        JOIN courses c ON c.id = cs.course_id
        JOIN session_groups sg ON sg.session_id = cs.id
        JOIN student_enrollments se
          ON se.group_id = sg.group_id
         AND se.semester_id = cs.semester_id
        JOIN course_subjects enrolled_csu
          ON enrolled_csu.subject_id = se.subject_id
         AND enrolled_csu.course_code = c.code
        JOIN exam_applications a
          ON a.student_username = se.student_username
         AND a.term_code = ?
        JOIN course_subjects applied_csu
          ON applied_csu.subject_id = a.subject_id
         AND applied_csu.course_code = c.code
        WHERE cs.id = ?
          {group_filter}
        """,
        (term_code, session_id, *group_params),
    )
    return {str(row["student_username"]) for row in rows}


def _application_counts_for_session_groups(session_id, term_code):
    rows = query_db(
        """
        SELECT sg.group_id, COUNT(DISTINCT a.student_username) AS application_count
        FROM course_sessions cs
        JOIN courses c ON c.id = cs.course_id
        JOIN session_groups sg ON sg.session_id = cs.id
        JOIN student_enrollments se
          ON se.group_id = sg.group_id
         AND se.semester_id = cs.semester_id
        JOIN course_subjects enrolled_csu
          ON enrolled_csu.subject_id = se.subject_id
         AND enrolled_csu.course_code = c.code
        JOIN exam_applications a
          ON a.student_username = se.student_username
         AND a.term_code = ?
        JOIN course_subjects applied_csu
          ON applied_csu.subject_id = a.subject_id
         AND applied_csu.course_code = c.code
        WHERE cs.id = ?
        GROUP BY sg.group_id
        """,
        (term_code, session_id),
    )
    return {int(row["group_id"]): int(row["application_count"]) for row in rows}


def _application_usernames_for_course(course_code, term_code, group_ids=None):
    """Return course applicants, optionally restricted to specific groups."""
    group_join = ""
    group_filter = ""
    group_params = []
    if group_ids:
        placeholders = ",".join("?" for _ in group_ids)
        group_join = "JOIN student_enrollments se ON se.student_username = a.student_username AND se.subject_id = a.subject_id"
        group_filter = f"AND se.group_id IN ({placeholders})"
        group_params.extend(group_ids)
    rows = query_db(
        f"""
        SELECT DISTINCT a.student_username
        FROM exam_applications a
        JOIN course_subjects cs ON cs.subject_id = a.subject_id
        {group_join}
        WHERE a.term_code = ?
          AND cs.course_code = ?
          {group_filter}
        """,
        (term_code, course_code, *group_params),
    )
    return {str(row["student_username"]) for row in rows}


def _exam_overlap_count(exam, own_session_id, term_code):
    """Return the exact applicant intersection for one written exam."""
    selected_group_ids = [
        int(value)
        for value in str(exam.get("selected_group_ids") or "").split(",")
        if value
    ]
    if not selected_group_ids:
        return 0, []

    own_group_applicants = _application_usernames_for_session(
        own_session_id,
        term_code,
        selected_group_ids,
    )
    exam_applicants = _application_usernames_for_course(
        exam["course_code"],
        term_code,
        selected_group_ids,
    )
    group_names = {
        int(row["id"]): row["name"]
        for row in query_db(
            "SELECT id, name FROM groups WHERE id IN ({})".format(
                ",".join("?" for _ in selected_group_ids)
            ),
            tuple(selected_group_ids),
        )
    }
    overlap = own_group_applicants & exam_applicants
    return len(overlap), [group_names[group_id] for group_id in selected_group_ids if group_id in group_names]


def written_exams_for_session(
    session_id,
    academic_year_start,
    term_code,
    group_ids=None,
    own_groups=None,
    own_course_code=None,
):
    """Return written exams with exact applicant overlap for the selected term."""
    if group_ids is not None and not group_ids:
        return []

    group_filter = ""
    group_params = []
    if group_ids is not None:
        placeholders = ",".join("?" for _ in group_ids)
        group_filter = f" AND sg.group_id IN ({placeholders})"
        group_params.extend(group_ids)

    rows = query_db(
        f"""
        WITH selected_groups AS (
            SELECT DISTINCT sg.group_id
            FROM course_sessions cs
            JOIN semesters s ON s.id = cs.semester_id
            JOIN session_groups sg ON sg.session_id = cs.id
            WHERE cs.id = ?
              AND s.academic_year_start = ?
              {group_filter}
        ), group_courses AS (
            SELECT DISTINCT cs.course_id, c.code
            FROM course_sessions cs
            JOIN semesters s ON s.id = cs.semester_id
            JOIN session_groups sg ON sg.session_id = cs.id
            JOIN selected_groups selected ON selected.group_id = sg.group_id
            JOIN courses c ON c.id = cs.course_id
            WHERE s.academic_year_start = ?
              AND c.code IS NOT NULL
        )
        SELECT e.course_code,
               e.course_name,
               e.exam_date,
               e.exam_hour,
               e.location,
               GROUP_CONCAT(DISTINCT g.name) AS group_names,
               GROUP_CONCAT(DISTINCT selected.group_id) AS selected_group_ids
        FROM exam_schedule e
        JOIN group_courses gc ON gc.code = e.course_code
        JOIN course_sessions cs ON cs.course_id = gc.course_id
        JOIN semesters s ON s.id = cs.semester_id
        JOIN session_groups sg ON sg.session_id = cs.id
        JOIN selected_groups selected ON selected.group_id = sg.group_id
        JOIN groups g ON g.id = selected.group_id
        WHERE s.academic_year_start = ?
          AND e.term_code = ?
        GROUP BY e.id, e.course_code, e.course_name, e.exam_date, e.exam_hour, e.location
        ORDER BY e.exam_date, e.exam_hour, e.course_name, e.course_code
        """,
        (session_id, academic_year_start, *group_params,
         academic_year_start, academic_year_start, term_code),
    )
    if own_course_code is None:
        return [dict(row) for row in rows]

    own_applicants = _application_usernames_for_session(session_id, term_code)
    if not own_applicants:
        return []
    result = []
    own_student_total = len(own_applicants)
    for row in rows:
        exam = dict(row)
        count, group_names = _exam_overlap_count(
            exam,
            session_id,
            term_code,
        )
        if count == 0:
            continue
        exam["my_student_count"] = count
        exam["my_student_total"] = own_student_total
        exam["overlap_percentage"] = (
            round(100 * count / own_student_total, 2)
            if count is not None and own_student_total
            else None
        )
        exam["group_names"] = ",".join(group_names)
        exam.pop("selected_group_ids", None)
        result.append(exam)
    return result


def oral_exams_for_session(session_id, academic_year_start, term_code):
    rows = query_db(
        """
        WITH selected_groups AS (
            SELECT DISTINCT sg.group_id
            FROM course_sessions cs
            JOIN semesters s ON s.id = cs.semester_id
            JOIN session_groups sg ON sg.session_id = cs.id
            WHERE cs.id = ?
              AND s.academic_year_start = ?
        ), group_sessions AS (
            SELECT DISTINCT cs.id
            FROM course_sessions cs
            JOIN semesters s ON s.id = cs.semester_id
            JOIN session_groups sg ON sg.session_id = cs.id
            JOIN selected_groups selected ON selected.group_id = sg.group_id
            WHERE s.academic_year_start = ?
        )
        SELECT oes.id,
               oes.course_session_id,
               c.code AS course_code,
               c.name AS course_name,
               GROUP_CONCAT(DISTINCT g.name) AS group_names,
               oes.exam_date,
               oes.start_hour,
               oes.end_hour,
               oes.reservation_id,
               r.name AS room_name,
               CASE WHEN oes.teacher_username = ? THEN 1 ELSE 0 END AS can_delete
        FROM oral_exam_schedule oes
        JOIN group_sessions gs ON gs.id = oes.course_session_id
        JOIN course_sessions cs ON cs.id = oes.course_session_id
        JOIN courses c ON c.id = cs.course_id
        JOIN session_groups sg ON sg.session_id = cs.id
        JOIN selected_groups selected ON selected.group_id = sg.group_id
        JOIN groups g ON g.id = sg.group_id
        LEFT JOIN reservations res ON res.id = oes.reservation_id
        LEFT JOIN rooms r ON r.id = res.room_id
        WHERE oes.term_code = ?
        GROUP BY oes.id, oes.course_session_id, c.code, c.name, oes.exam_date,
                 oes.start_hour, oes.end_hour, oes.reservation_id, r.name,
                 oes.teacher_username
        ORDER BY oes.exam_date, oes.start_hour, c.name, oes.id
        """,
        (session_id, academic_year_start, academic_year_start, current_user.username, term_code),
    )
    own_applicants = _application_usernames_for_session(session_id, term_code)
    own_student_total = len(own_applicants)
    result = []
    for row in rows:
        exam = dict(row)
        oral_applicants = _application_usernames_for_session(
            exam["course_session_id"],
            term_code,
        )
        overlap_count = len(own_applicants & oral_applicants)
        exam["my_student_count"] = overlap_count
        exam["my_student_total"] = own_student_total
        exam["overlap_percentage"] = (
            round(100 * overlap_count / own_student_total, 2)
            if own_student_total
            else None
        )
        result.append(exam)
    return result


def room_options():
    return [dict(row) for row in query_db("SELECT id, name FROM rooms ORDER BY name")]


def selection_data():
    teacher_id = teacher_id_for_current_user()
    academic_year_start = current_school_year_start()
    if teacher_id is None or academic_year_start is None:
        return {
            "academic_year_start": academic_year_start,
            "terms": [],
            "selected_term": None,
            "sessions": [],
            "selected_session": None,
            "groups": [],
            "written_exams": [],
            "oral_exams": [],
            "rooms": room_options(),
        }

    terms, default_term = exam_terms_for_school_year(academic_year_start)
    requested_term = request.args.get("term_code")
    if requested_term:
        selected_term = next(
            (term for term in terms if term["term_code"] == requested_term),
            None,
        )
        if selected_term is None:
            abort(404, "Испитни рок није пронађен.")
    else:
        selected_term = default_term

    sessions = teacher_sessions_for_school_year(teacher_id, academic_year_start)
    requested_session_id = request.args.get("session_id", type=int)
    selected_session = next(
        (session for session in sessions if session["id"] == requested_session_id),
        None,
    )
    if requested_session_id is not None and selected_session is None:
        abort(404, "Термин наставе није пронађен.")

    groups = (
        groups_for_session(selected_session["id"])
        if selected_session
        else []
    )
    if selected_session and selected_term:
        application_counts = _application_counts_for_session_groups(
            selected_session["id"], selected_term["term_code"]
        )
        for group in groups:
            group["application_count"] = application_counts.get(group["id"], 0)
    written_exams = (
        written_exams_for_session(
            selected_session["id"],
            academic_year_start,
            selected_term["term_code"],
            [group["id"] for group in groups],
            groups,
            selected_session["code"],
        )
        if selected_term and selected_session
        else []
    )
    oral_exams = (
        oral_exams_for_session(
            selected_session["id"],
            academic_year_start,
            selected_term["term_code"],
        )
        if selected_term and selected_session
        else []
    )
    return {
        "academic_year_start": academic_year_start,
        "terms": terms,
        "selected_term": selected_term,
        "sessions": sessions,
        "selected_session": selected_session,
        "groups": groups,
        "written_exams": written_exams,
        "oral_exams": oral_exams,
        "rooms": room_options(),
    }


@bp.route("/oral_exams")
@login_required
def oral_exams_view():
    return render_template("oral_exams.html")


@bp.route("/oral_exams_data")
@login_required
def oral_exams_data():
    return jsonify(selection_data())


@bp.route("/oral_exams_schedule", methods=["POST"])
@login_required
def create_oral_exam():
    payload = request.get_json(silent=True) or {}
    term_code = str(payload.get("term_code") or "").strip()
    exam_date = str(payload.get("exam_date") or "").strip()
    try:
        session_id = int(payload.get("session_id"))
        start_hour = int(payload.get("start_hour"))
        end_hour = int(payload.get("end_hour"))
    except (TypeError, ValueError):
        return jsonify({"error": "Термин наставе и време су обавезни."}), 400
    try:
        parsed_date = datetime.date.fromisoformat(exam_date)
    except ValueError:
        return jsonify({"error": "Датум није исправан."}), 400
    if not 0 <= start_hour < end_hour <= 24:
        return jsonify({"error": "Почетак и крај морају бити између 00 и 24 часа, при чему крај мора бити после почетка."}), 400

    teacher_id = teacher_id_for_current_user()
    academic_year_start = current_school_year_start()
    allowed = query_db(
        """
        SELECT c.code
        FROM course_sessions cs
        JOIN courses c ON c.id = cs.course_id
        JOIN semesters s ON s.id = cs.semester_id
        WHERE cs.teacher_id = ?
          AND cs.id = ?
          AND s.academic_year_start = ?
        LIMIT 1
        """,
        (teacher_id, session_id, academic_year_start),
        one=True,
    )
    term = query_db(
        """
        SELECT et.term_code
        FROM exam_terms et
        JOIN semesters s ON s.id = et.semester_id
        WHERE et.term_code = ? AND s.academic_year_start = ?
        """,
        (term_code, academic_year_start),
        one=True,
    )
    if allowed is None:
        return jsonify({"error": "Термин наставе није у власништву наставника."}), 403
    if term is None:
        return jsonify({"error": "Испитни рок није пронађен."}), 404
    try:
        schedule_id = execute_db(
            """
            INSERT INTO oral_exam_schedule
                (term_code, course_session_id, exam_date, start_hour, end_hour, teacher_username)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (term_code, session_id, parsed_date.isoformat(), start_hour,
             end_hour, current_user.username),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "Усмени испит није могуће сачувати."}), 409
    return jsonify({"id": schedule_id}), 201


def _teacher_oral_exam(schedule_id):
    return query_db(
        """
        SELECT oes.id, oes.exam_date, oes.start_hour, oes.end_hour,
               oes.reservation_id, res.room_id, oes.course_session_id,
               c.name AS course_name
        FROM oral_exam_schedule oes
        JOIN course_sessions cs ON cs.id = oes.course_session_id
        JOIN courses c ON c.id = cs.course_id
        LEFT JOIN reservations res ON res.id = oes.reservation_id
        WHERE oes.id = ? AND oes.teacher_username = ?
        """,
        (schedule_id, current_user.username),
        one=True,
    )


def _available_rooms_for_interval(exam_date, start_hour, end_hour):
    kind, _week_day, day_of_week = check_day(exam_date)
    schedule_conflict_sql = ""
    schedule_params = []
    if is_schedule_day(kind):
        schedule_conflict_sql = """
            AND NOT EXISTS (
                SELECT 1
                FROM weekly_sessions ws
                JOIN course_sessions cs ON cs.id = ws.session_id
                JOIN semesters s ON s.id = cs.semester_id
                LEFT JOIN weekly_cancellations wxc
                       ON wxc.weekly_session_id = ws.id
                      AND wxc.date = ?
                WHERE ws.room_id = r.id
                  AND ws.day_of_week = ?
                  AND ? BETWEEN s.start_date AND s.end_date
                  AND ws.start_slot < ?
                  AND ? < ws.end_slot
                  AND wxc.id IS NULL
            )
        """
        schedule_params.extend([exam_date, day_of_week, exam_date, end_hour, start_hour])

    rows = query_db(
        f"""
        SELECT r.id, r.name, r.building_name
        FROM rooms r
        WHERE (r.type IS NULL OR r.type != 'teacher_office')
          AND NOT EXISTS (
              SELECT 1
              FROM reservations res
              WHERE res.room_id = r.id
                AND res.date = ?
                AND res.start_slot < ?
                AND ? < res.end_slot
          )
          {schedule_conflict_sql}
        ORDER BY r.name
        """,
        [exam_date, end_hour, start_hour, *schedule_params],
    )
    return [dict(row) for row in rows]


@bp.route("/oral_exams_schedule/<int:schedule_id>/available_rooms")
@login_required
def oral_exam_available_rooms(schedule_id):
    exam = _teacher_oral_exam(schedule_id)
    if exam is None:
        return jsonify({"error": "Усмени испит није пронађен."}), 404
    if exam["reservation_id"] is not None:
        return jsonify({"rooms": []})
    return jsonify({
        "rooms": _available_rooms_for_interval(
            exam["exam_date"], exam["start_hour"], exam["end_hour"]
        )
    })


@bp.route("/oral_exams_schedule/<int:schedule_id>/reserve_room", methods=["POST"])
@login_required
def reserve_room_for_oral_exam(schedule_id):
    exam = _teacher_oral_exam(schedule_id)
    if exam is None:
        return jsonify({"error": "Усмени испит није пронађен."}), 404
    if exam["room_id"] is not None:
        return jsonify({"error": "Усмени испит већ има резервисану салу."}), 409

    payload = request.get_json(silent=True) or {}
    try:
        room_id = int(payload.get("room_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Сала није исправно изабрана."}), 400

    available_ids = {
        room["id"]
        for room in _available_rooms_for_interval(
            exam["exam_date"], exam["start_hour"], exam["end_hour"]
        )
    }
    if room_id not in available_ids:
        return jsonify({"error": "Изабрана сала више није слободна."}), 409

    try:
        reservation_id = _create_single_reservation(
            {
                "room_id": room_id,
                "date": exam["exam_date"],
                "start_slot": exam["start_hour"],
                "end_slot": exam["end_hour"],
                "description": f"Усмени испит: {exam['course_name']}",
            },
            current_user.username,
            is_service=False,
        )
    except HTTPException as exc:
        return jsonify({"error": exc.description}), exc.code or 400

    execute_db(
        "UPDATE oral_exam_schedule SET reservation_id = ? WHERE id = ? AND reservation_id IS NULL",
        (reservation_id, schedule_id),
    )
    return jsonify({"success": True, "reservation_id": reservation_id}), 200


@bp.route("/oral_exams_schedule/<int:schedule_id>", methods=["DELETE"])
@login_required
def delete_oral_exam(schedule_id):
    """Delete an oral-exam term owned by the logged-in teacher."""
    schedule = query_db(
        "SELECT id, teacher_username FROM oral_exam_schedule WHERE id = ?",
        (schedule_id,),
        one=True,
    )
    if schedule is None:
        return jsonify({"error": "Усмени испит није пронађен."}), 404
    if schedule["teacher_username"] != current_user.username:
        return jsonify({"error": "Немате дозволу да откажете овај усмени испит."}), 403

    execute_db("DELETE FROM oral_exam_schedule WHERE id = ?", (schedule_id,))
    return jsonify({"success": True}), 200
