# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Run an isolated local server for attendance browser E2E tests."""

import datetime
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("TEACHER_AUTH_MODE", "mock")
os.environ.setdefault("DATABASE", "/tmp/matf-app-attendance-e2e.db")

database_path = Path(os.environ["DATABASE"])
database_path.unlink(missing_ok=True)

from flask import jsonify  # noqa: E402

from app import app  # noqa: E402
from db import execute_db, init_db  # noqa: E402


init_db()
now = datetime.datetime.now()
event_date = now.date().isoformat()
start_slot = max(0, now.hour - 1)
end_slot = min(23, start_slot + 2)
day_of_week = now.isoweekday() % 7
execute_db(
    "INSERT INTO days (date, kind, week_day) VALUES (?, ?, ?)",
    (event_date, "teaching", day_of_week),
)

semester_id = execute_db(
    """INSERT INTO semesters (academic_year_start, season, start_date, end_date)
       VALUES (?, ?, ?, ?)""",
    (now.year, "јесењи", event_date, (now.date() + datetime.timedelta(days=1)).isoformat()),
)
teacher_id = execute_db(
    "INSERT INTO teachers (name, username) VALUES (?, ?)",
    ("E2E наставник", "e2e-teacher"),
)
course_id = execute_db("INSERT INTO courses (name, code) VALUES (?, ?)", ("E2E предмет", "e2e"))
room_id = execute_db(
    "INSERT INTO rooms (name, capacity, type, building_name) VALUES (?, ?, ?, ?)",
    ("E2E сала", 30, "lecture", "E2E зграда"),
)
reservation_room_id = execute_db(
    "INSERT INTO rooms (name, capacity, type, building_name) VALUES (?, ?, ?, ?)",
    ("E2E сала за резервације", 30, "lecture", "E2E зграда"),
)
session_id = execute_db(
    """INSERT INTO course_sessions (course_id, teacher_id, semester_id, type)
       VALUES (?, ?, ?, ?)""",
    (course_id, teacher_id, semester_id, "p"),
)
event_id = execute_db(
    """INSERT INTO weekly_sessions
       (session_id, room_id, day_of_week, start_slot, end_slot)
       VALUES (?, ?, ?, ?, ?)""",
    (session_id, room_id, day_of_week, start_slot, end_slot),
)
reservation_course_id = execute_db("INSERT INTO courses (name, code) VALUES (?, ?)", ("E2E резервације", "e2e-res"))
reservation_session_id = execute_db(
    "INSERT INTO course_sessions (course_id, teacher_id, semester_id, type) VALUES (?, ?, ?, ?)",
    (reservation_course_id, teacher_id, semester_id, "p"),
)
reservation_start_slot = 10
reservation_end_slot = 12
reservation_event_id = execute_db(
    """INSERT INTO weekly_sessions
       (session_id, room_id, day_of_week, start_slot, end_slot)
       VALUES (?, ?, ?, ?, ?)""",
    (reservation_session_id, reservation_room_id, day_of_week,
     reservation_start_slot, reservation_end_slot),
)
execute_db(
    """INSERT INTO weekly_cancellations (weekly_session_id, date, username)
       VALUES (?, ?, ?)""",
    (reservation_event_id, event_date, "e2e-teacher"),
)


@app.get("/__e2e__/attendance-target")
def attendance_target():
    return jsonify({"event_id": event_id, "event_date": event_date})


@app.get("/__e2e__/reservation-target")
def reservation_target():
    return jsonify({
        "room_id": reservation_room_id,
        "date": event_date,
        "start_slot": reservation_start_slot,
        "end_slot": reservation_end_slot,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5173, debug=False)
