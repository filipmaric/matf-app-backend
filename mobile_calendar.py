# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Read-only calendar endpoint for the Android application."""

import hashlib
import json
import datetime

from flask import Blueprint, jsonify, request, make_response

from calendar_views import calendar_month_payload
from mobile_auth import mobile_session_rate_limit, require_mobile_session
from db import query_db


bp = Blueprint("mobile_calendar", __name__)


@bp.route("/mobile/calendar", methods=["GET"])
@require_mobile_session
def calendar():
    """Return one calendar month with HTTP caching support."""
    limited = mobile_session_rate_limit("mobile_calendar")
    if limited is not None:
        return limited

    month = request.args.get("month", type=int)
    year = request.args.get("year", type=int)
    if month is None or year is None or not 1 <= month <= 12 or not 2000 <= year <= 2100:
        return jsonify({"error": "month and year are required"}), 400

    first_day = datetime.date(year, month, 1)
    last_day = (
        datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        if month < 12
        else datetime.date(year, 12, 31)
    )
    semesters = query_db(
        """
        SELECT s.id, COALESCE(cr.revision, 0) AS revision
        FROM semesters s
        LEFT JOIN calendar_revisions cr ON cr.semester_id = s.id
        WHERE s.start_date <= ? AND s.end_date >= ?
        ORDER BY s.start_date, s.id
        """,
        (last_day.isoformat(), first_day.isoformat()),
    )
    today = datetime.date.today().isoformat()
    semester = query_db(
        """
        SELECT start_date
        FROM semesters
        WHERE ? BETWEEN start_date AND end_date
        ORDER BY start_date DESC, id DESC
        LIMIT 1
        """,
        (today,),
        one=True,
    )
    current_semester_start = semester["start_date"] if semester else None
    revision_token = "|".join(
        f"{row['id']}:{row['revision']}" for row in semesters
    ) or "none"
    etag = hashlib.sha256(
        json.dumps(
            {
                "month": month,
                "year": year,
                "calendar_revisions": revision_token,
                "current_semester_start": current_semester_start,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if request.headers.get("If-None-Match") == etag:
        response = make_response("", 304)
    else:
        payload = dict(calendar_month_payload(month, year, revision_token))
        payload["current_semester_start"] = current_semester_start
        response = make_response(jsonify(payload))
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=3600, must-revalidate"
    return response
