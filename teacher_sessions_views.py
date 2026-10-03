# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Teacher course-session explorer with selectable school year."""

from flask import Blueprint, abort, jsonify, render_template, request

from db import query_db
from semester_utils import academic_year_label, semester_display_name


bp = Blueprint("teacher_sessions_views", __name__)

WEEKDAY_LABELS = (
    "Понедељак",
    "Уторак",
    "Среда",
    "Четвртак",
    "Петак",
    "Субота",
    "Недеља",
)


def available_academic_years():
    """Return school years that exist in the database."""
    rows = query_db(
        """
        SELECT DISTINCT academic_year_start
        FROM semesters
        WHERE academic_year_start IS NOT NULL
        ORDER BY academic_year_start DESC
        """
    )
    return [
        {
            "start_year": int(row["academic_year_start"]),
            "academic_year": academic_year_label(int(row["academic_year_start"])),
        }
        for row in rows
    ]


def resolve_academic_year(requested_academic_year):
    """Resolve a requested school year to its start year and label."""
    years = available_academic_years()
    if not years:
        return None

    if requested_academic_year is None or str(requested_academic_year).strip() == "":
        return years[0]

    normalized = str(requested_academic_year).strip()
    for year in years:
        if normalized in {year["academic_year"], str(year["start_year"])}:
            return year
    abort(404, "Школска година није пронађена.")


def normalize_season_filter(requested_season):
    """Normalize the requested season filter."""
    normalized = " ".join(str(requested_season or "").split()).lower()
    if not normalized or normalized == "both":
        return "both"
    if normalized in {"fall", "autumn"}:
        return "fall"
    if normalized in {"spring"}:
        return "spring"
    if normalized in {"јесењи", "jesenji"}:
        return "fall"
    if normalized in {"пролећни", "prolecni", "prolećni"}:
        return "spring"
        abort(404, "Семестар није пронађен.")


def season_to_semester_label(season_filter):
    """Map the UI season filter to the stored semester season."""
    if season_filter == "fall":
        return "јесењи"
    if season_filter == "spring":
        return "пролећни"
    return None


def available_seasons():
    """Return the available season filter options."""
    return [
        {"value": "both", "label": "оба"},
        {"value": "fall", "label": "јесењи"},
        {"value": "spring", "label": "пролећни"},
    ]


def teachers_for_academic_year(academic_year_start, season_filter):
    """Return teachers that have course sessions in the selected school year."""
    params = [academic_year_start]
    season_clause = ""
    semester_season = season_to_semester_label(season_filter)
    if semester_season is not None:
        season_clause = " AND s.season = ?"
        params.append(semester_season)
    rows = query_db(
        """
        SELECT DISTINCT t.id,
               t.name,
               t.username
        FROM teachers t
        JOIN course_sessions cs ON cs.teacher_id = t.id
        JOIN semesters s ON s.id = cs.semester_id
        WHERE s.academic_year_start = ?
        """ + season_clause + """
        ORDER BY t.name, t.username, t.id
        """,
        tuple(params),
    )
    return [dict(row) for row in rows]


def sessions_for_teacher(teacher_id, academic_year_start, season_filter):
    """Return the teacher's course sessions for the selected school year."""
    semester_season = season_to_semester_label(season_filter)
    season_clause = ""
    params = [teacher_id, academic_year_start]
    if semester_season is not None:
        season_clause = " AND s.season = ?"
        params.append(semester_season)
    rows = query_db(
        """
        SELECT cs.id AS course_session_id,
               cs.type AS course_type,
               c.id AS course_id,
               c.name AS course_name,
               c.code AS course_code,
               s.id AS semester_id,
               s.academic_year_start AS semester_academic_year_start,
               s.season AS semester_season,
               s.start_date AS semester_start_date,
               s.end_date AS semester_end_date,
               COALESCE(GROUP_CONCAT(DISTINCT g.name), '') AS groups
        FROM course_sessions cs
        JOIN courses c ON c.id = cs.course_id
        JOIN semesters s ON s.id = cs.semester_id
        LEFT JOIN session_groups sg ON sg.session_id = cs.id
        LEFT JOIN groups g ON g.id = sg.group_id
        WHERE cs.teacher_id = ?
          AND s.academic_year_start = ?
        """ + season_clause + """
        GROUP BY cs.id,
                 cs.type,
                 c.id,
                 c.name,
                 c.code,
                 s.id,
                 s.academic_year_start,
                 s.season,
                 s.start_date,
                 s.end_date
        ORDER BY s.start_date, s.end_date, c.name, c.code, cs.type, cs.id
        """,
        tuple(params),
    )
    sessions = [dict(row) for row in rows]
    for session in sessions:
        groups = session.pop("groups", "")
        session["groups"] = [group for group in groups.split(",") if group]
        if session.get("semester_academic_year_start") is not None and session.get("semester_season"):
            session["semester_display_name"] = semester_display_name(
                int(session["semester_academic_year_start"]),
                str(session["semester_season"]),
            )
        else:
            session["semester_display_name"] = None
        session.pop("semester_academic_year_start", None)
        session.pop("semester_season", None)
        session["weekly_sessions"] = []
    if not sessions:
        return sessions

    session_ids = [session["course_session_id"] for session in sessions]
    placeholders = ",".join("?" for _ in session_ids)
    weekly_rows = query_db(
        f"""
        SELECT ws.session_id,
               ws.id AS weekly_session_id,
               ws.room_id,
               rm.name AS room_name,
               ws.day_of_week,
               ws.start_slot,
               ws.end_slot
        FROM weekly_sessions ws
        JOIN rooms rm ON rm.id = ws.room_id
        WHERE ws.session_id IN ({placeholders})
        ORDER BY ws.session_id, ws.day_of_week, ws.start_slot, ws.room_id, ws.id
        """,
        tuple(session_ids),
    )

    sessions_by_id = {session["course_session_id"]: session for session in sessions}
    for row in weekly_rows:
        session = sessions_by_id.get(row["session_id"])
        if session is None:
            continue
        session["weekly_sessions"].append(
            {
                "weekly_session_id": row["weekly_session_id"],
                "room_id": row["room_id"],
                "room_name": row["room_name"],
                "day_of_week": row["day_of_week"],
                "day_of_week_label": WEEKDAY_LABELS[row["day_of_week"]]
                if 0 <= row["day_of_week"] < len(WEEKDAY_LABELS)
                else str(row["day_of_week"]),
                "start_slot": row["start_slot"],
                "end_slot": row["end_slot"],
            }
        )

    return sessions


@bp.route("/teacher_sessions")
def teacher_sessions_view():
    """Render the teacher-session explorer page."""
    selected_year = resolve_academic_year(request.args.get("academic_year"))
    selected_season = normalize_season_filter(request.args.get("season"))
    return render_template(
        "teacher_sessions.html",
        academic_years=available_academic_years(),
        selected_academic_year=selected_year["academic_year"] if selected_year else None,
        seasons=available_seasons(),
        selected_season=selected_season,
    )


@bp.route("/teacher_sessions_data")
def teacher_sessions_data():
    """Return teachers and their course sessions for the selected school year."""
    selected_year = resolve_academic_year(request.args.get("academic_year"))
    selected_season = normalize_season_filter(request.args.get("season"))
    if selected_year is None:
        return jsonify(
            {
                "academic_year": None,
                "academic_years": [],
                "season": selected_season,
                "seasons": available_seasons(),
                "teachers": [],
                "selected_teacher": None,
                "sessions": [],
            }
        )

    academic_year_start = selected_year["start_year"]
    teachers = teachers_for_academic_year(academic_year_start, selected_season)
    teacher_id = request.args.get("teacher_id", type=int)
    selected_teacher = None

    if teacher_id is None and teachers:
        selected_teacher = teachers[0]
        teacher_id = int(selected_teacher["id"])
    else:
        selected_teacher = next((teacher for teacher in teachers if teacher["id"] == teacher_id), None)
        if teacher_id is not None and selected_teacher is None:
            abort(404, "Наставник није пронађен.")

    sessions = sessions_for_teacher(teacher_id, academic_year_start, selected_season) if teacher_id is not None else []

    return jsonify(
        {
            "academic_year": selected_year["academic_year"],
            "academic_years": available_academic_years(),
            "season": selected_season,
            "seasons": available_seasons(),
            "teachers": teachers,
            "selected_teacher": selected_teacher,
            "sessions": sessions,
        }
    )
