# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Calendar metadata and update endpoints."""

import datetime
import threading
import time

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user

from occupancy import iso_to_weekday
from calendar_common import validate_day_kind

from auth import RATE_LIMITS, check_if_admin, enforce_rate_limit
from db import execute_db, get_db, query_db


bp = Blueprint("calendar_views", __name__)

CALENDAR_HOLIDAYS = ['2026-01-01', '2026-01-07']
_CALENDAR_CACHE_TTL_SECONDS = 3600
_calendar_cache = {}
_calendar_cache_lock = threading.Lock()


def calendar_month_payload(month, year, cache_token=None):
    """Return the read-only calendar payload for one month."""
    cache_key = (year, month, cache_token)
    now = time.monotonic()
    with _calendar_cache_lock:
        cached = _calendar_cache.get(cache_key)
        if cached and now - cached[0] < _CALENDAR_CACHE_TTL_SECONDS:
            return cached[1]

    first_day = datetime.date(year, month, 1)
    last_day = (
        datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        if month < 12
        else datetime.date(year, 12, 31)
    )
    rows = query_db(
        'SELECT date, kind, week_day FROM days WHERE date BETWEEN ? AND ?',
        (first_day.isoformat(), last_day.isoformat()),
    )
    calendar_dict = {
        r['date']: {'kind': r['kind'], 'week_day': r['week_day']}
        for r in rows
    }
    payload = {'calendar': calendar_dict, 'holidays': CALENDAR_HOLIDAYS}
    with _calendar_cache_lock:
        _calendar_cache[cache_key] = (now, payload)
    return payload


def clear_calendar_cache():
    """Invalidate cached calendar payloads after an administrative update."""
    with _calendar_cache_lock:
        _calendar_cache.clear()


def bump_calendar_revisions(dates):
    """Bump each semester whose calendar contains one of ``dates``."""
    semester_ids = set()
    for date_str in dates:
        semester = query_db(
            """
            SELECT id FROM semesters
            WHERE ? BETWEEN start_date AND end_date
            ORDER BY start_date DESC, id DESC
            LIMIT 1
            """,
            (date_str,),
            one=True,
        )
        if semester:
            semester_ids.add(semester["id"])

    for semester_id in semester_ids:
        execute_db(
            "INSERT OR IGNORE INTO calendar_revisions (semester_id) VALUES (?)",
            (semester_id,),
            commit=False,
        )
        execute_db(
            """
            UPDATE calendar_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = ?
            """,
            (semester_id,),
            commit=False,
        )
    if semester_ids:
        get_db().commit()


def _require_admin():
    """Reject requests unless the current user is an administrator."""
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401
    if not check_if_admin(current_user.username):
        return jsonify({"error": "Forbidden"}), 403
    return None


# Calendar read helpers and endpoints.


@bp.route('/calendar_data')
def calendar_data():
    """Return the working-day metadata for one calendar month."""
    limited = enforce_rate_limit(
        "calendar_data",
        *RATE_LIMITS["calendar_data"],
        key=getattr(current_user, "username", None),
    )
    if limited is not None:
        return limited

    denied = _require_admin()
    if denied is not None:
        return denied

    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    if month is None or year is None:
        abort(400, 'month and year are required')
    if month < 1 or month > 12:
        abort(400, 'month must be between 1 and 12')

    return jsonify(calendar_month_payload(month, year))


# Calendar update helpers and endpoints.


@bp.route('/update_calendar', methods=['POST'])
def update_calendar():
    """Update the calendar table for working days and overrides."""
    limited = enforce_rate_limit("calendar", *RATE_LIMITS["calendar"])
    if limited is not None:
        return limited

    denied = _require_admin()
    if denied is not None:
        return denied

    updates = request.get_json(silent=True)

    if not isinstance(updates, list):
        return jsonify({'error': 'expected a list of updates'}), 400

    changed_dates = []
    for index, u in enumerate(updates):
        if not isinstance(u, dict):
            return jsonify({'error': f'update {index} must be an object'}), 400
        date_str = u.get('date')
        if not isinstance(date_str, str):
            return jsonify({'error': f'update {index} has an invalid date'}), 400
        try:
            kind = validate_day_kind(u.get('kind'))
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({'error': str(exc)}), 400
        week_day = u.get('week_day', -1)
        if not isinstance(week_day, int) or not -1 <= week_day <= 6:
            return jsonify({'error': f'update {index} has an invalid week_day'}), 400

        try:
            datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': f'invalid date format for {date_str}, expected YYYY-MM-DD'}), 400

        real_wd = iso_to_weekday(date_str)
        if week_day == real_wd:
            week_day = -1

        existing = query_db(
            'SELECT kind, week_day FROM days WHERE date = ?', (date_str,), one=True
        )
        if kind == 'non_working' and not existing:
            continue

        if existing and existing["kind"] == kind and existing["week_day"] == week_day:
            continue

        execute_db(
            '''
            REPLACE INTO days (date, kind, week_day)
            VALUES (?, ?, ?)
            ''',
            (date_str, kind, week_day)
        )
        changed_dates.append(date_str)
    bump_calendar_revisions(changed_dates)
    clear_calendar_cache()
    return jsonify(success=True)


@bp.route('/calendar')
def calendar_view():
    """Render the calendar page."""
    return render_template(
        'calendar.html',
        calendar_access=current_user.is_authenticated and check_if_admin(current_user.username),
    )
