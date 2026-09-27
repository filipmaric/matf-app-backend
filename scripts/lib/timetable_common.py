# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import datetime as dt
import re
import unicodedata
from collections import defaultdict

from calendar_common import is_schedule_day
from room_common import TEACHER_OFFICE_ROOM_TYPE


DAY_MAP = {
    "pon": 0,
    "uto": 1,
    "sre": 2,
    "cet": 3,
    "pet": 4,
    "sub": 5,
    "ned": 6,
}

REVERSE_DAY_MAP = {v: k for k, v in DAY_MAP.items()}

CYRILLIC_TO_LATIN = str.maketrans(
    {
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "G",
        "Д": "D",
        "Ђ": "Dj",
        "Е": "E",
        "Ж": "Z",
        "З": "Z",
        "И": "I",
        "Ј": "J",
        "К": "K",
        "Л": "L",
        "Љ": "Lj",
        "М": "M",
        "Н": "N",
        "Њ": "Nj",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "Ћ": "C",
        "У": "U",
        "Ф": "F",
        "Х": "H",
        "Ц": "C",
        "Ч": "C",
        "Џ": "Dz",
        "Ш": "S",
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "ђ": "dj",
        "е": "e",
        "ж": "z",
        "з": "z",
        "и": "i",
        "ј": "j",
        "к": "k",
        "л": "l",
        "љ": "lj",
        "м": "m",
        "н": "n",
        "њ": "nj",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "ћ": "c",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "c",
        "џ": "dz",
        "ш": "s",
    }
)


def normalize_group_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or "").strip().translate(CYRILLIC_TO_LATIN))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", "", text)
    return text.lower()


def load_metadata(filename):
    mapping = {}

    with open(filename, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) >= 2:
                mapping[row[0].strip()] = row[1].strip()

    return mapping


def parse_line(line):
    parts = line.strip().split("_")

    if len(parts) != 7:
        raise ValueError(f"Invalid format: {line}")

    teacher = parts[0]
    groups = [g.strip() for g in re.split(r"[.,;|]+", parts[1]) if g.strip()]
    course_token = parts[2]
    day_str = parts[3]
    start_slot = int(parts[4])
    end_slot = int(parts[5])
    room_code = parts[6]

    course_parts = course_token.rsplit(".", 1)
    if len(course_parts) == 2 and course_parts[1] in {"p", "v", "k", "o"}:
        course_code, course_type = course_parts
    else:
        # Some course codes contain a dot, but have no explicit session type.
        course_code = course_token
        course_type = None

    if day_str not in DAY_MAP:
        raise ValueError(f"Invalid day: {day_str}")

    return (
        teacher,
        groups,
        course_code,
        course_type,
        DAY_MAP[day_str],
        start_slot,
        end_slot,
        room_code,
    )


def clear_schedule(cur):
    """Delete all timetable-related data."""
    cur.execute("PRAGMA foreign_keys = ON;")
    cur.execute("DELETE FROM weekly_sessions;")
    cur.execute("DELETE FROM session_groups;")
    cur.execute("DELETE FROM course_sessions;")


def get_or_create_teacher(cur, username, full_name):
    cur.execute(
        """
        INSERT OR IGNORE INTO teachers(username, name)
        VALUES (?, ?)
        """,
        (username, full_name),
    )
    cur.execute("SELECT id FROM teachers WHERE username = ?", (username,))
    return cur.fetchone()[0]


def get_or_create_course(cur, code, name):
    cur.execute(
        """
        INSERT OR IGNORE INTO courses(name, code)
        VALUES (?, ?)
        """,
        (name, code),
    )
    cur.execute("SELECT id FROM courses WHERE code = ?", (code,))
    return cur.fetchone()[0]


def get_or_create_group(cur, name):
    cur.execute(
        """
        INSERT OR IGNORE INTO groups(name)
        VALUES (?)
        """,
        (name,),
    )
    cur.execute("SELECT id FROM groups WHERE name = ?", (name,))
    return cur.fetchone()[0]


def get_latest_semester_id(cur):
    cur.execute(
        """
        SELECT id FROM semesters
        ORDER BY start_date DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        raise ValueError("No semester found")
    return row[0]


def get_room_id(cur, code):
    lookup_code = str(code).strip()
    if lookup_code.lower() == "kab":
        lookup_code = "kab"
        cur.execute(
            """
            INSERT OR IGNORE INTO rooms
                (name, capacity, type, building_name, code, priority)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "Кабинет наставника",
                0,
                TEACHER_OFFICE_ROOM_TYPE,
                "Кабинет наставника",
                "kab",
                1000,
            ),
        )
        cur.execute(
            "UPDATE rooms SET type = ? WHERE code = ?",
            (TEACHER_OFFICE_ROOM_TYPE, "kab"),
        )
    cur.execute("SELECT id FROM rooms WHERE code = ?", (lookup_code,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Room not found: {code}")
    return row[0]


def find_session_ids(cur, teacher_username, course_code, course_type, groups, semester_id=None):
    query = [
        """
        SELECT cs.id
        FROM course_sessions cs
        JOIN teachers t ON cs.teacher_id = t.id
        JOIN courses c ON cs.course_id = c.id
        WHERE t.username = ? AND c.code = ?
        """
    ]
    params = [teacher_username, course_code]
    if course_type is not None:
        query[0] += " AND cs.type = ?"
        params.append(course_type)
    if semester_id is not None:
        query.append(" AND cs.semester_id = ?")
        params.append(semester_id)

    cur.execute("".join(query), params)

    potential_sessions = cur.fetchall()
    exact_ids = []
    superset_ids = []
    wanted_groups = set(groups)
    for (session_id,) in potential_sessions:
        cur.execute(
            """
            SELECT g.name
            FROM groups g
            JOIN session_groups sg ON g.id = sg.group_id
            WHERE sg.session_id = ?
            """,
            (session_id,),
        )
        existing_groups = {row[0] for row in cur.fetchall()}
        if existing_groups == wanted_groups:
            exact_ids.append(session_id)
        elif wanted_groups < existing_groups:
            superset_ids.append(session_id)

    return exact_ids or superset_ids


def slot_datetime(day, slot):
    return dt.datetime.combine(day, dt.time(hour=slot, minute=0))


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def load_days(conn, start_date):
    rows = conn.execute(
        """
        SELECT date, kind, week_day
        FROM days
        WHERE date >= ?
        ORDER BY date
        """,
        (start_date.isoformat(),),
    ).fetchall()
    days = {}
    for row in rows:
        day = dt.date.fromisoformat(row["date"])
        week_day = row["week_day"]
        if week_day == -1:
            week_day = day.weekday()
        days[day] = {
            "kind": row["kind"],
            "week_day": week_day,
        }
    return days


def load_future_reservations(conn, now):
    rows = conn.execute(
        """
        SELECT r.id, r.room_id, ro.name AS room_name, ro.code AS room_code,
               r.date, r.start_slot, r.end_slot, r.description, r.username
        FROM reservations r
        JOIN rooms ro ON ro.id = r.room_id
        ORDER BY r.date, r.start_slot, r.id
        """
    ).fetchall()

    events = []
    for row in rows:
        day = dt.date.fromisoformat(row["date"])
        start_dt = slot_datetime(day, row["start_slot"])
        end_dt = slot_datetime(day, row["end_slot"])
        if start_dt < now:
            continue
        events.append(
            {
                "kind": "reservation",
                "source_id": row["id"],
                "room_id": row["room_id"],
                "room_name": row["room_name"],
                "room_code": row["room_code"],
                "date": day,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "start_slot": row["start_slot"],
                "end_slot": row["end_slot"],
                "username": row["username"],
                "description": row["description"] or "",
            }
        )
    return events


def load_future_weekly_occurrences(conn, now):
    rows = conn.execute(
        """
        SELECT ws.id AS weekly_session_id,
               ws.room_id,
               ro.name AS room_name,
               ro.code AS room_code,
               ws.day_of_week,
               ws.start_slot,
               ws.end_slot,
               c.name AS course_name,
               c.code AS course_code,
               cs.type AS course_type,
               t.name AS teacher_name,
               t.username AS teacher_username,
               s.start_date AS semester_start,
               s.end_date AS semester_end
        FROM weekly_sessions ws
        JOIN rooms ro ON ro.id = ws.room_id
        JOIN course_sessions cs ON cs.id = ws.session_id
        JOIN courses c ON c.id = cs.course_id
        JOIN teachers t ON t.id = cs.teacher_id
        JOIN semesters s ON s.id = cs.semester_id
        WHERE ro.type IS NULL OR ro.type != ?
        ORDER BY ws.id
        """,
        (TEACHER_OFFICE_ROOM_TYPE,),
    ).fetchall()

    days = load_days(conn, now.date())
    canceled = conn.execute(
        """
        SELECT weekly_session_id, date
        FROM weekly_cancellations
        WHERE date >= ?
        """,
        (now.date().isoformat(),),
    ).fetchall()
    canceled_dates = {
        (row["weekly_session_id"], dt.date.fromisoformat(row["date"]))
        for row in canceled
    }

    events = []
    for row in rows:
        semester_start = dt.date.fromisoformat(row["semester_start"])
        semester_end = dt.date.fromisoformat(row["semester_end"])
        start_date = max(now.date(), semester_start)
        current = start_date

        while current <= semester_end:
            day_info = days.get(current)
            if not day_info or not is_schedule_day(day_info["kind"]):
                current += dt.timedelta(days=1)
                continue

            if day_info["week_day"] != row["day_of_week"]:
                current += dt.timedelta(days=1)
                continue

            if (row["weekly_session_id"], current) in canceled_dates:
                current += dt.timedelta(days=1)
                continue

            start_dt = slot_datetime(current, row["start_slot"])
            end_dt = slot_datetime(current, row["end_slot"])
            if start_dt >= now:
                events.append(
                    {
                        "kind": "weekly",
                        "source_id": row["weekly_session_id"],
                        "room_id": row["room_id"],
                        "room_name": row["room_name"],
                        "room_code": row["room_code"],
                        "date": current,
                        "start_dt": start_dt,
                        "end_dt": end_dt,
                        "start_slot": row["start_slot"],
                        "end_slot": row["end_slot"],
                        "course_name": row["course_name"],
                        "course_code": row["course_code"],
                        "course_type": row["course_type"],
                        "teacher_name": row["teacher_name"],
                        "teacher_username": row["teacher_username"],
                    }
                )

            current += dt.timedelta(days=1)

    return events


def find_conflicts(events):
    grouped = defaultdict(list)
    for event in events:
        grouped[(event["room_id"], event["date"])].append(event)

    conflicts = []
    seen = set()
    for (room_id, day), day_events in grouped.items():
        day_events.sort(
            key=lambda item: (
                item["start_dt"],
                item["end_dt"],
                item["kind"],
                item["source_id"],
            )
        )
        for i, left in enumerate(day_events):
            for right in day_events[i + 1 :]:
                if right["start_dt"] >= left["end_dt"]:
                    break
                if not overlaps(
                    left["start_dt"], left["end_dt"], right["start_dt"], right["end_dt"]
                ):
                    continue

                key = (
                    room_id,
                    day,
                    tuple(
                        sorted(
                            [
                                (left["kind"], left["source_id"]),
                                (right["kind"], right["source_id"]),
                            ]
                        )
                    ),
                )
                if key in seen:
                    continue
                seen.add(key)
                conflicts.append((room_id, day, left, right))

    return conflicts


def collect_future_conflicts(conn, now, focus_weekly_session_ids=None):
    events = load_future_reservations(conn, now) + load_future_weekly_occurrences(conn, now)
    conflicts = find_conflicts(events)
    if focus_weekly_session_ids is None:
        return conflicts

    focus = set(focus_weekly_session_ids)
    filtered = []
    for conflict in conflicts:
        left = conflict[2]
        right = conflict[3]
        if left["kind"] == "weekly" and left["source_id"] in focus:
            filtered.append(conflict)
        elif right["kind"] == "weekly" and right["source_id"] in focus:
            filtered.append(conflict)
    return filtered


def event_label(event):
    if event["kind"] == "reservation":
        desc = f" {event['description']}" if event["description"] else ""
        return (
            f"reservation #{event['source_id']} by {event['username']!r}"
            f"{desc}"
        )

    return (
        f"weekly session #{event['source_id']} "
        f"{event['course_name']} ({event['teacher_name']})"
    )


def format_conflict(conflict):
    room_id, day, left, right = conflict
    room = left["room_code"] or left["room_name"] or str(room_id)
    return (
        f"- {day.isoformat()} room {room} "
        f"{left['start_dt'].strftime('%H:%M')}-{left['end_dt'].strftime('%H:%M')}: "
        f"{event_label(left)} overlaps with {event_label(right)}"
    )
