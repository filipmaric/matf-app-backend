# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Mobile API endpoint for student grade history."""

import csv
import io
import os
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from flask import Blueprint, current_app, g, jsonify

from db import mobile_auth_get_two_factor_settings, student_identity_for_username
from hypatia_request import add_query_params
from hypatia_request import signed_request_headers
from mobile_auth import (
    _two_factor_grace_active,
    _two_factor_requirement_disabled,
    mobile_auth_data_username,
    require_mobile_session,
)


bp = Blueprint("mobile_grades", __name__)


def _grades_request_signing_secret():
    """Return the shared secret used to sign upstream grades requests."""
    secret = os.getenv("GRADES_REQUEST_SIGNING_SECRET", "").strip()
    if secret:
        return secret
    if getattr(current_app, "testing", False):
        return "test-grades-request-signing-secret"
    raise RuntimeError("grades_request_signing_secret_missing")


def _grades_source_text(data_username):
    """Return the CSV text from the upstream server."""
    source_url = os.getenv("GRADES_SOURCE_URL", "").strip()
    if source_url:
        try:
            request_url = add_query_params(source_url, student_username=data_username)
            request_headers = signed_request_headers(
                _grades_request_signing_secret(),
                "GET",
                request_url,
                [f"student_username={data_username}"],
            )
            request = Request(request_url, headers=request_headers)
            with urlopen(request, timeout=10) as response:
                return response.read().decode("utf-8-sig")
        except (OSError, URLError, ValueError) as exc:
            current_app.logger.warning("Failed to fetch grades CSV from %s: %s", source_url, exc)
            raise RuntimeError("grades_source_unavailable") from exc

    raise RuntimeError("grades_source_url_missing")


def _field(row, *names):
    for name in names:
        value = str(row.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _parse_grade_value(raw_value):
    try:
        return int(str(raw_value).strip())
    except (TypeError, ValueError):
        return None


def _parse_bool(raw_value):
    value = str(raw_value).strip().lower()
    if value in {"1", "true", "yes", "y", "da", "да", "zakljucena", "zakljucen", "zakljuceno", "закључена", "закључен", "закључено", "locked"}:
        return True
    if value in {"0", "false", "no", "n", "ne", "не", "otkljucena", "otkljucen", "otkljuceno", "откључана", "откључан", "откључано", "unlocked"}:
        return False
    return False


def _parse_grades_for_student(data_username):
    text = _grades_source_text(data_username).strip()
    if not text:
        return []

    reader = csv.DictReader(io.StringIO(text))
    grades = []
    for row in reader:
        row_username = _field(row, "student_username", "username", "radius_username")
        if row_username and row_username != data_username:
            continue

        subject_code = _field(row, "subject_code", "code")
        accreditation_raw = _field(row, "accreditation")
        semester = _field(row, "semester")
        ects_raw = _field(row, "ects", "espb")
        grade_raw = _field(row, "grade")
        grade_date = _field(row, "date", "grade_date")
        school_year = _field(row, "school_year")
        subject_name = _field(row, "subject_name", "name") or subject_code
        confirmed_raw = _field(row, "confirmed", "is_confirmed", "locked")

        if not subject_code or not accreditation_raw or not semester or not ects_raw or not grade_raw or not grade_date or not school_year:
            continue

        try:
            accreditation = int(accreditation_raw)
        except ValueError:
            continue

        try:
            ects = int(ects_raw)
        except ValueError:
            continue

        grade_value = _parse_grade_value(grade_raw)
        if grade_value is None:
            continue

        grades.append(
            {
                "subject_code": subject_code,
                "subject_name": subject_name,
                "accreditation": accreditation,
                "semester": semester,
                "ects": ects,
                "grade": grade_value,
                "date": grade_date,
                "school_year": school_year,
                "confirmed": _parse_bool(confirmed_raw),
            }
        )
    return grades


@bp.route("/mobile/grades", methods=["GET"])
@require_mobile_session
def grades():
    """Return the authenticated student's grade history."""
    session = g.mobile_auth_session
    user = mobile_auth_get_two_factor_settings(session["user_id"])
    if not _two_factor_requirement_disabled(user) and not _two_factor_grace_active(user):
        return jsonify({"error_code": "two_factor_required", "error": "2FA confirmation is required."}), 401

    data_username = mobile_auth_data_username(user["radius_username"])
    student = student_identity_for_username(data_username)
    try:
        grades = _parse_grades_for_student(data_username)
    except RuntimeError as error:
        if str(error) in {
            "grades_source_unavailable",
            "grades_source_url_missing",
            "grades_request_signing_secret_missing",
        }:
            return jsonify({"error_code": str(error), "error": "Grades are temporarily unavailable."}), 503
        raise
    return jsonify(
        {
            "student": student,
            "grades": grades,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
