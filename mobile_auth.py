# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Mobile API endpoints backed by student RADIUS sessions."""

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from flask import Blueprint, current_app, g, jsonify, make_response, request

from auth import RATE_LIMITS, enforce_rate_limit, login_rate_limit_key, service_required, student_radius_auth
from config import (
    MOBILE_AUTH_REVIEW_DATA_USERNAME,
    MOBILE_AUTH_REVIEW_PASSWORD,
    MOBILE_AUTH_REVIEW_USERNAME,
    MOBILE_ACTION_OTP_SECRET,
    MOBILE_ACTION_OTP_TTL,
    MOBILE_TWO_FACTOR_GRACE_DAYS,
    HYPATIA_LINK_URL,
    HYPATIA_EXAM_APPLICATIONS_URL,
    HYPATIA_REQUEST_SIGNING_SECRET,
    REVIEW_MODE,
)
from hypatia_request import add_query_params, build_canonical_payload, sign_payload, signed_request_headers
from db import (
    get_db,
    hash_token,
    building_locations_all,
    exam_terms_all,
    mobile_device_delete,
    mobile_device_upsert,
    mobile_auth_assert_device_login_allowed,
    mobile_auth_create_session,
    mobile_auth_get_or_create_user,
    mobile_auth_get_session_by_token,
    mobile_auth_get_user_by_id,
    mobile_auth_get_user_by_two_factor_link_ticket,
    mobile_auth_get_two_factor_settings,
    mobile_auth_begin_two_factor_setup,
    mobile_auth_confirm_two_factor,
    mobile_auth_disable_two_factor,
    mobile_auth_mark_two_factor_verified,
    mobile_auth_clear_two_factor_setup,
    mobile_auth_clear_two_factor_verification,
    mobile_auth_set_two_factor_link_ticket,
    mobile_auth_clear_two_factor_link_ticket,
    mobile_auth_record_device_login,
    mobile_auth_revoke_active_sessions,
    mobile_auth_revoke_session,
    mobile_auth_touch_session,
    student_enrollments_for_student,
    student_enrollment_revision,
    student_identity_for_username,
    student_exam_schedule_for_student,
    student_notifications_unread_count,
    student_timetable_events_for_student,
    timetable_revision_for_semester,
)
from semester import current_semester_id, semester_by_id


bp = Blueprint("mobile_auth", __name__)


def _timetable_response(payload, etag):
    """Return a timetable response using a cheap metadata-based ETag."""
    if request.headers.get("If-None-Match") == etag:
        response = make_response("", 304)
    else:
        response = make_response(jsonify(payload))
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    return response


def _timetable_etag(semester_id, timetable_revision, enrollment_revision):
    """Build an ETag from independent timetable and enrollment revisions."""
    return f'"semester-{semester_id}-timetable-{timetable_revision}-enrollments-{enrollment_revision}"'


class HypatiaExamApplicationError(RuntimeError):
    """Represent one rejected Hypatia exam-application request."""

    def __init__(self, status_code, error_code, message):
        super().__init__(message or error_code or "hypatia_exam_application_error")
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


def _utcnow():
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def _parse_iso(value):
    """Parse an ISO 8601 timestamp stored in SQLite."""
    return datetime.fromisoformat(value)


def _two_factor_grace_expires_at(user_row):
    """Return the end of the current 2FA grace window for one user."""
    last_verified_at = user_row["two_factor_last_verified_at"] if user_row else None
    if not last_verified_at:
        return None
    return _parse_iso(last_verified_at) + timedelta(days=MOBILE_TWO_FACTOR_GRACE_DAYS)


def _two_factor_grace_active(user_row):
    """Return True when recent 2FA verification is still trusted."""
    expires_at = _two_factor_grace_expires_at(user_row)
    return expires_at is not None and expires_at > _utcnow()


def _two_factor_setup_active(user_row):
    """Return True when the user has an active 2FA setup code."""
    if not user_row:
        return False
    setup_code = user_row["two_factor_setup_code"]
    setup_expires_at = user_row["two_factor_setup_expires_at"]
    if not setup_code or not setup_expires_at:
        return False
    return _parse_iso(setup_expires_at) > _utcnow()


def _two_factor_requirement_disabled(user_row):
    """Return True when the user has turned off 2FA requirements."""
    return bool(user_row) and not bool(user_row["two_factor_enabled"]) and not _two_factor_setup_active(user_row)


def _two_factor_link_ticket_active(user_row):
    """Return True when the user has a usable link-based 2FA ticket."""
    if not user_row:
        return False
    link_ticket = user_row["two_factor_link_ticket"]
    link_ticket_expires_at = user_row["two_factor_link_ticket_expires_at"]
    link_action = user_row["two_factor_link_action"]
    if not link_ticket or not link_ticket_expires_at or not link_action:
        return False
    return _parse_iso(link_ticket_expires_at) > _utcnow()


def _ensure_two_factor_link_ticket(user_row):
    """Generate a fresh link ticket for setup or verification flows when needed."""
    if not user_row:
        return user_row

    if _two_factor_setup_active(user_row):
        link_action = "setup"
    elif bool(user_row["two_factor_enabled"]) and not _two_factor_grace_active(user_row) and not _two_factor_requirement_disabled(user_row):
        link_action = "verify"
    else:
        if user_row["two_factor_link_ticket"] or user_row["two_factor_link_ticket_expires_at"] or user_row["two_factor_link_action"]:
            mobile_auth_clear_two_factor_link_ticket(user_row["id"])
            return mobile_auth_get_two_factor_settings(user_row["id"])
        return user_row

    if _two_factor_link_ticket_active(user_row) and user_row["two_factor_link_action"] == link_action:
        return user_row

    link_ticket = secrets.token_urlsafe(24).rstrip("=")
    link_ticket_expires_at = (_utcnow() + timedelta(minutes=10)).isoformat()
    mobile_auth_set_two_factor_link_ticket(user_row["id"], link_ticket, link_ticket_expires_at, link_action)
    return mobile_auth_get_two_factor_settings(user_row["id"])


def _complete_two_factor_link(ticket):
    """Complete one production 2FA link flow for the provided ticket."""
    ticket = str(ticket or "").strip()
    if not ticket:
        return jsonify({"ok": False, "error": "ticket_required", "message": "Недостаје тикет."}), 400

    user_row = mobile_auth_get_user_by_two_factor_link_ticket(ticket)
    if user_row is None:
        return jsonify({"ok": False, "error": "invalid_or_expired_ticket", "message": "Тикет није важећи или је истекао."}), 404

    link_ticket_expires_at = user_row["two_factor_link_ticket_expires_at"]
    if not link_ticket_expires_at or _parse_iso(link_ticket_expires_at) <= _utcnow():
        mobile_auth_clear_two_factor_link_ticket(user_row["id"])
        return jsonify({"ok": False, "error": "invalid_or_expired_ticket", "message": "Тикет није важећи или је истекао."}), 404

    link_action = user_row["two_factor_link_action"]
    if link_action == "setup":
        mobile_auth_confirm_two_factor(user_row["id"])
    elif link_action == "verify":
        mobile_auth_mark_two_factor_verified(user_row["id"])
        mobile_auth_clear_two_factor_link_ticket(user_row["id"])
    else:
        mobile_auth_clear_two_factor_link_ticket(user_row["id"])
        return jsonify({"ok": False, "error": "invalid_link_action", "message": "Непозната акција за тикет."}), 400

    return jsonify({"ok": True, "return_url": "matfapp://two-factor-complete"})


def _session_is_active(session):
    """Return True when the stored bearer session is still valid."""
    if session is None:
        return False
    if session["revoked_at"] is not None:
        return False
    return _parse_iso(session["expires_at"]) > _utcnow()


def _user_payload(user):
    """Serialize a mobile API user row for the JSON API."""
    return {"id": user["id"], "radius_username": user["radius_username"]}


def _student_payload(radius_username):
    """Serialize the student's public identity for the JSON API."""
    data_username = mobile_auth_data_username(radius_username)
    student = student_identity_for_username(data_username)
    return {
        "username": student["username"],
        "student_index": student["student_index"],
        "student_name": student["student_name"],
        "student_label": student["student_label"],
    }


def _session_payload(session, include_last_seen=False):
    """Serialize a mobile API session row for the JSON API."""
    payload = {
        "id": session["id"],
        "device_id": session["device_id"],
        "device_name": session["device_name"],
        "expires_at": session["expires_at"],
    }
    if include_last_seen:
        payload["last_seen_at"] = session["last_seen_at"]
        payload["last_seen_ip"] = session["last_seen_ip"]
    return payload


def _mobile_client_ip():
    """Return the best-effort client IP address for the mobile API."""
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    return client_ip.split(",")[0].strip() or "unknown"


def mobile_auth_data_username(radius_username):
    """Map the review login account to the student data it should display."""
    if REVIEW_MODE and radius_username == MOBILE_AUTH_REVIEW_USERNAME:
        return MOBILE_AUTH_REVIEW_DATA_USERNAME
    return radius_username


def _two_factor_payload(user_row):
    """Serialize the stored 2FA settings for the current user."""
    setup_code = user_row["two_factor_setup_code"]
    setup_expires_at = user_row["two_factor_setup_expires_at"]
    setup_expiry = _parse_iso(setup_expires_at) if setup_expires_at else None
    setup_active = _two_factor_setup_active(user_row)
    disabled = _two_factor_requirement_disabled(user_row)
    grace_active = bool(user_row["two_factor_enabled"]) and not disabled and _two_factor_grace_active(user_row)
    payload = {
        "enabled": bool(user_row["two_factor_enabled"]),
        "setup_pending": setup_active,
        "disabled": disabled,
        "created_at": user_row["two_factor_created_at"],
        "confirmed_at": user_row["two_factor_confirmed_at"],
        "last_verified_at": user_row["two_factor_last_verified_at"],
        "grace_active": grace_active,
        "grace_expires_at": (
            _two_factor_grace_expires_at(user_row).astimezone(timezone.utc).isoformat()
            if grace_active
            and _two_factor_grace_expires_at(user_row) is not None
            else None
        ),
        "link_ticket": user_row["two_factor_link_ticket"] if _two_factor_link_ticket_active(user_row) else None,
        "link_ticket_expires_at": (
            _parse_iso(user_row["two_factor_link_ticket_expires_at"]).astimezone(timezone.utc).isoformat()
            if _two_factor_link_ticket_active(user_row)
            else None
        ),
        "link_action": user_row["two_factor_link_action"] if _two_factor_link_ticket_active(user_row) else None,
        "link_url": (
            add_query_params(HYPATIA_LINK_URL, ticket=user_row["two_factor_link_ticket"])
            if _two_factor_link_ticket_active(user_row) and HYPATIA_LINK_URL
            else None
        ),
    }
    if setup_active:
        payload["setup_code"] = setup_code
        payload["setup_code_expires_at"] = setup_expiry.astimezone(timezone.utc).isoformat()
    return payload


def _mobile_action_expected_otp_token(setup_code):
    """Derive the 6-digit OTP token emitted by the external test server."""
    signature = hmac.new(
        MOBILE_ACTION_OTP_SECRET.encode("utf-8"),
        str(setup_code).strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{int(signature[:12], 16) % 1_000_000:06d}"


def _hypatia_exam_application_request(data_username, term_code, subject_id, applied):
    """Ask Hypatia to authorize one exam application change before local mutation."""
    source_url = HYPATIA_EXAM_APPLICATIONS_URL.strip()
    if not source_url:
        if getattr(current_app, "testing", False):
            return {"ok": True}
        raise RuntimeError("hypatia_exam_application_url_missing")
    if not HYPATIA_REQUEST_SIGNING_SECRET:
        if getattr(current_app, "testing", False):
            return {"ok": True}
        raise RuntimeError("hypatia_request_signing_secret_missing")

    payload = {
        "student_username": data_username,
        "term_code": term_code,
        "subject_id": subject_id,
        "applied": applied,
    }
    request_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = signed_request_headers(
        HYPATIA_REQUEST_SIGNING_SECRET,
        "POST",
        source_url,
        [
            f"student_username={data_username}",
            f"term_code={term_code}",
            f"subject_id={subject_id}",
            f"applied={1 if applied else 0}",
        ],
    )
    request = Request(
        source_url,
        data=request_body,
        headers={
            **headers,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    response_status = 400
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8-sig").strip()
    except HTTPError as exc:
        response_status = exc.code or 400
        response_body = exc.read().decode("utf-8-sig").strip()
        if not response_body:
            current_app.logger.warning(
                "Hypatia rejected exam application request at %s with status %s and empty body",
                source_url,
                response_status,
            )
            raise HypatiaExamApplicationError(response_status, "hypatia_exam_application_rejected", "Hypatia rejected the request.") from exc
    except (OSError, URLError, ValueError) as exc:
        current_app.logger.warning("Failed to authorize exam application with Hypatia at %s: %s", source_url, exc)
        raise RuntimeError("hypatia_exam_application_unavailable") from exc

    if not response_body:
        return {"ok": True}

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        current_app.logger.warning("Invalid Hypatia response from %s: %s", source_url, exc)
        raise RuntimeError("hypatia_exam_application_unavailable") from exc

    if isinstance(parsed, dict) and parsed.get("ok", True):
        return parsed

    error_code = ""
    error_message = ""
    status_code = response_status
    if isinstance(parsed, dict):
        error_code = str(parsed.get("error_code", "") or "").strip()
        error_message = str(parsed.get("error", "") or "").strip()
        status_code = int(parsed.get("status_code", status_code) or status_code)
    raise HypatiaExamApplicationError(status_code, error_code, error_message)


def _parse_exam_application_bool(value):
    """Return a strict boolean from a JSON payload field."""
    if isinstance(value, bool):
        return value
    return None


def _exam_application_two_factor_required(user):
    """Return True when the user must confirm 2FA before a sensitive action."""
    return not _two_factor_requirement_disabled(user) and not _two_factor_grace_active(user)


def _validate_exam_application_context(user, term_code, subject_id):
    """Validate that the student can toggle one exam application."""
    data_username = mobile_auth_data_username(user["radius_username"])

    term_row = get_db().execute(
        """
        SELECT term_code, semester_id
        FROM exam_terms
        WHERE term_code = ?
        """,
        (term_code,),
    ).fetchone()
    if term_row is None:
        return None, (jsonify({"error": "exam_term_not_found"}), 404)

    enrollment_row = get_db().execute(
        """
        SELECT 1
        FROM student_enrollments
        WHERE student_username = ?
          AND semester_id = ?
          AND subject_id = ?
        """,
        (data_username, term_row["semester_id"], subject_id),
    ).fetchone()
    if enrollment_row is None:
        return None, (jsonify({"error": "subject_not_enrolled"}), 404)

    schedule_row = get_db().execute(
        """
        SELECT 1
        FROM course_subjects cs
        JOIN exam_schedule e
          ON e.course_code = cs.course_code
        WHERE cs.subject_id = ?
          AND e.term_code = ?
        LIMIT 1
        """,
        (subject_id, term_code),
    ).fetchone()
    if schedule_row is None:
        return None, (jsonify({"error": "exam_not_found"}), 404)

    return {"term_row": term_row, "data_username": data_username}, None


def require_mobile_session(fn):
    """Require a valid mobile bearer token for the wrapped route."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing_bearer_token"}), 401

        raw_token = auth_header.split(" ", 1)[1].strip()
        session = mobile_auth_get_session_by_token(raw_token)
        if not _session_is_active(session):
            return jsonify({"error": "invalid_or_expired_session"}), 401

        g.mobile_auth_session = mobile_auth_touch_session(session["id"], last_seen_ip=_mobile_client_ip())
        return fn(*args, **kwargs)

    return wrapper


def mobile_session_rate_limit(scope):
    """Apply a per-mobile-user rate limit for authenticated bearer requests."""
    session = getattr(g, "mobile_auth_session", None)
    if session is None:
        return None
    return enforce_rate_limit(scope, *RATE_LIMITS[scope], key=session["user_id"])


@bp.route("/mobile/login", methods=["POST"])
def login():
    """Authenticate a student and create an opaque bearer session."""
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    device_id = str(payload.get("device_id", "")).strip()
    device_name = str(payload.get("device_name", "Mobile device")).strip()

    limited = enforce_rate_limit("login", *RATE_LIMITS["login"], key=login_rate_limit_key(username))
    if limited is not None:
        return limited

    if not username or not password or not device_id:
        return jsonify({"error": "username_password_and_device_id_required"}), 400

    try:
        mobile_auth_assert_device_login_allowed(device_id, username)
    except RuntimeError as exc:
        return jsonify({"error": "device_username_locked_for_today", "detail": str(exc)}), 409

    if REVIEW_MODE and username == MOBILE_AUTH_REVIEW_USERNAME and password == MOBILE_AUTH_REVIEW_PASSWORD:
        ok = True
    else:
        try:
            ok = student_radius_auth(username, password, raise_on_error=True)
        except Exception as exc:
            return jsonify({"error": "radius_unavailable", "detail": str(exc)}), 503

    if not ok:
        return jsonify({"error": "invalid_credentials"}), 401

    user = mobile_auth_get_or_create_user(username)
    mobile_auth_revoke_active_sessions(user["id"], reason="replaced_by_new_login")

    raw_token = secrets.token_urlsafe(32)
    session = mobile_auth_create_session(
        user_id=user["id"],
        device_id=device_id,
        device_name=device_name,
        token_hash=hash_token(raw_token),
        session_days=current_app.config["MOBILE_AUTH_SESSION_DAYS"],
    )
    mobile_auth_record_device_login(device_id, username)

    return jsonify(
        {
            "token": raw_token,
            "token_type": "Bearer",
            "expires_at": session["expires_at"],
            "user": _user_payload(user),
            "student": _student_payload(user["radius_username"]),
            "session": _session_payload(session),
        }
    )


@bp.route("/mobile/2fa", methods=["GET"])
@require_mobile_session
def two_factor_status():
    """Return the current mobile 2FA state for the authenticated user."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_2fa")
    if limited is not None:
        return limited
    user = mobile_auth_get_user_by_id(session["user_id"])
    state = mobile_auth_get_two_factor_settings(user["id"])
    state = _ensure_two_factor_link_ticket(state)
    return jsonify(
        {
            "user": _user_payload(user),
            "two_factor": _two_factor_payload(state),
        }
    )


@bp.route("/mobile/2fa/setup", methods=["POST"])
@require_mobile_session
def two_factor_setup():
    """Create or refresh a 2FA setup code for the current user."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_2fa")
    if limited is not None:
        return limited
    user = mobile_auth_get_user_by_id(session["user_id"])
    state = mobile_auth_get_two_factor_settings(user["id"])
    enabled = bool(state["two_factor_enabled"]) if state is not None else False
    setup_code = f"{secrets.randbelow(1_000_000):06d}"
    setup_code_expires_at = (_utcnow() + timedelta(seconds=MOBILE_ACTION_OTP_TTL)).isoformat()
    mobile_auth_begin_two_factor_setup(user["id"], setup_code, setup_code_expires_at, enabled=enabled)
    updated = mobile_auth_get_two_factor_settings(user["id"])
    updated = _ensure_two_factor_link_ticket(updated)
    return jsonify(
        {
            "user": _user_payload(user),
            "two_factor": _two_factor_payload(updated),
        }
    )


@bp.route("/mobile/2fa/confirm", methods=["POST"])
@require_mobile_session
def two_factor_confirm():
    """Enable 2FA after the user proves access to the setup code."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_2fa")
    if limited is not None:
        return limited
    user = mobile_auth_get_user_by_id(session["user_id"])
    state = mobile_auth_get_two_factor_settings(user["id"])
    if state is None or not state["two_factor_setup_code"]:
        return jsonify({"error": "two_factor_setup_required"}), 409
    setup_expires_at = state["two_factor_setup_expires_at"]
    if not setup_expires_at or _parse_iso(setup_expires_at) <= _utcnow():
        mobile_auth_clear_two_factor_setup(user["id"])
        return jsonify({"error": "two_factor_setup_required"}), 409

    payload = request.get_json(silent=True) or {}
    code = str(payload.get("otp_code", "") or "").strip()
    if not code:
        return jsonify({"error": "otp_code_required"}), 400

    expected_code = _mobile_action_expected_otp_token(state["two_factor_setup_code"])
    if expected_code != code:
        return jsonify({"error": "invalid_two_factor_code"}), 401

    mobile_auth_confirm_two_factor(user["id"])
    updated = mobile_auth_get_two_factor_settings(user["id"])
    return jsonify(
        {
            "user": _user_payload(user),
            "two_factor": _two_factor_payload(updated),
        }
    )


@bp.route("/mobile/2fa/clear", methods=["POST"])
@require_mobile_session
def two_factor_clear():
    """Clear the current 2FA trust window for the authenticated user."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_2fa")
    if limited is not None:
        return limited
    user = mobile_auth_get_user_by_id(session["user_id"])
    state = mobile_auth_get_two_factor_settings(user["id"])
    if state is None or not state["two_factor_enabled"]:
        return jsonify({"error": "two_factor_setup_required"}), 409

    mobile_auth_clear_two_factor_verification(user["id"])
    updated = mobile_auth_get_two_factor_settings(user["id"])
    return jsonify(
        {
            "user": _user_payload(user),
            "two_factor": _two_factor_payload(updated),
        }
    )


@bp.route("/mobile/2fa/disable", methods=["POST"])
@require_mobile_session
def two_factor_disable():
    """Disable 2FA for the authenticated user."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_2fa")
    if limited is not None:
        return limited
    user = mobile_auth_get_user_by_id(session["user_id"])
    state = mobile_auth_get_two_factor_settings(user["id"])
    if (
        state is not None
        and state["two_factor_setup_code"]
        and not state["two_factor_enabled"]
    ):
        mobile_auth_clear_two_factor_setup(user["id"])
    else:
        mobile_auth_disable_two_factor(user["id"])
    updated = mobile_auth_get_two_factor_settings(user["id"])
    return jsonify(
        {
            "user": _user_payload(user),
            "two_factor": _two_factor_payload(updated),
        }
    )


@bp.route("/mobile/2fa/link/complete", methods=["POST"])
@service_required
def two_factor_link_complete():
    """Complete the production 2FA link flow after Hipatia verification."""
    ticket = str(request.args.get("ticket", "")).strip()
    timestamp = str(request.headers.get("X-Request-Timestamp", "")).strip()
    nonce = str(request.headers.get("X-Request-Nonce", "")).strip()
    signature = str(request.headers.get("X-Request-Signature", "")).strip()

    if not ticket:
        return jsonify({"ok": False, "error": "ticket_required", "message": "Недостаје тикет."}), 400
    if not timestamp or not nonce or not signature:
        return jsonify({"ok": False, "error": "signature_required", "message": "Недостаје потпис."}), 400
    if not HYPATIA_REQUEST_SIGNING_SECRET:
        raise RuntimeError("hypatia_request_signing_secret_missing")

    canonical_payload = build_canonical_payload(
        "POST",
        request.full_path.rstrip("?"),
        [f"ticket={ticket}"],
        timestamp,
        nonce,
    )
    expected_signature = sign_payload(HYPATIA_REQUEST_SIGNING_SECRET, canonical_payload)
    if not hmac.compare_digest(signature, expected_signature):
        return jsonify({"ok": False, "error": "invalid_signature", "message": "Потпис није важећи."}), 403

    return _complete_two_factor_link(ticket)


@bp.route("/mobile/me", methods=["GET"])
@require_mobile_session
def me():
    """Return the current authenticated mobile session."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_me")
    if limited is not None:
        return limited
    user = mobile_auth_get_user_by_id(session["user_id"])
    data_username = mobile_auth_data_username(user["radius_username"])
    student = student_identity_for_username(data_username)
    semester_id = current_semester_id()
    unread_count = 0
    if semester_id is not None and (student["student_name"] is not None or student["student_index"] is not None):
        unread_count = student_notifications_unread_count(data_username, semester_id)
    two_factor_state = mobile_auth_get_two_factor_settings(user["id"])
    two_factor_state = _ensure_two_factor_link_ticket(two_factor_state)
    return jsonify(
        {
            "user": _user_payload(user),
            "student": _student_payload(user["radius_username"]),
            "session": _session_payload(session, include_last_seen=True),
            "two_factor": _two_factor_payload(two_factor_state),
            "unread_count": unread_count,
        }
    )


@bp.route("/mobile/logout", methods=["POST"])
@require_mobile_session
def logout():
    """Revoke the current mobile bearer token."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_logout")
    if limited is not None:
        return limited
    mobile_device_delete(session["device_id"])
    mobile_auth_revoke_session(session["id"], reason="logged_out")
    return jsonify({"ok": True})


@bp.route("/mobile/push-token", methods=["POST"])
@require_mobile_session
def register_installation_id():
    """Register or update the current device Firebase installation id."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_push_token")
    if limited is not None:
        return limited
    payload = request.get_json(silent=True) or {}
    installation_id = str(payload.get("installation_id", "")).strip()
    platform = str(payload.get("platform", "android")).strip() or "android"
    device_name = str(payload.get("device_name", session["device_name"])).strip() or session["device_name"]

    if not installation_id:
        return jsonify({"error": "installation_id_required"}), 400

    user = mobile_auth_get_user_by_id(session["user_id"])
    mobile_device_upsert(
        student_username=user["radius_username"],
        device_id=session["device_id"],
        device_name=device_name,
        installation_id=installation_id,
        platform=platform,
    )
    return jsonify({"ok": True})


@bp.route("/mobile/sessions", methods=["GET"])
@require_mobile_session
def sessions():
    """Expose the current session id for clients that need to confirm login state."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_sessions")
    if limited is not None:
        return limited
    user = mobile_auth_get_user_by_id(session["user_id"])
    return jsonify(
        {
            "user": _user_payload(user),
            "current_session_id": session["id"],
        }
    )


@bp.route("/mobile/timetable", methods=["GET"])
@require_mobile_session
def timetable():
    """Return the authenticated student's personalized timetable for one semester."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_timetable")
    if limited is not None:
        return limited
    semester_id = request.args.get("semester_id", type=int)
    resolved_semester_id = semester_id if semester_id is not None else current_semester_id()
    semester = semester_by_id(resolved_semester_id) if resolved_semester_id is not None else None
    if semester_id is not None and semester is None:
        return jsonify({"error": "semester_not_found"}), 404
    if resolved_semester_id is None:
        etag = _timetable_etag("none", 0, 0)
        return _timetable_response(
            {
                "student": None,
                "semester": None,
                "enrollments": [],
                "events": [],
                "generated_at": _utcnow().isoformat(),
            },
            etag,
        )

    user = mobile_auth_get_user_by_id(session["user_id"])
    data_username = mobile_auth_data_username(user["radius_username"])
    student = student_identity_for_username(data_username)
    if student["student_name"] is None and student["student_index"] is None:
        return jsonify({"error": "student_not_found"}), 404

    etag = _timetable_etag(
        resolved_semester_id,
        timetable_revision_for_semester(resolved_semester_id),
        student_enrollment_revision(data_username, resolved_semester_id),
    )
    if request.headers.get("If-None-Match") == etag:
        return _timetable_response({}, etag)

    enrollments = [
        {
            "course_id": row["course_id"],
            "course_code": row["course_code"],
            "course_name": row["course_name"],
            "group_id": row["group_id"],
            "group_name": row["group_name"],
            "semester_id": row["semester_id"],
        }
        for row in student_enrollments_for_student(data_username, resolved_semester_id)
    ]
    events = [
        {
            "course_id": row["course_id"],
            "course_code": row["course_code"],
            "course_name": row["course_name"],
            "course_type": row["course_type"],
            "group_id": row["group_id"],
            "group_name": row["group_name"],
            "teacher_username": row["teacher_username"],
            "teacher_name": row["teacher_name"],
            "room_id": row["room_id"],
            "room_name": row["room_name"],
            "room_code": row["room_code"],
            "room_building_name": row["room_building_name"],
            "room_latitude": row["room_latitude"],
            "room_longitude": row["room_longitude"],
            "day_of_week": row["day_of_week"],
            "start_slot": row["start_slot"],
            "end_slot": row["end_slot"],
            "weekly_session_id": row["weekly_session_id"],
            "course_session_id": row["course_session_id"],
            "semester_id": row["semester_id"],
        }
        for row in student_timetable_events_for_student(data_username, resolved_semester_id)
    ]
    return _timetable_response(
        {
            "student": student,
            "semester": semester,
            "enrollments": enrollments,
            "events": events,
            "generated_at": _utcnow().isoformat(),
        },
        etag,
    )


@bp.route("/mobile/buildings", methods=["GET"])
@require_mobile_session
def buildings():
    """Return all known building locations for the mobile app."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_buildings")
    if limited is not None:
        return limited
    return jsonify(
        {
            "buildings": building_locations_all(),
            "generated_at": _utcnow().isoformat(),
        }
    )


@bp.route("/mobile/exam_schedule", methods=["GET"])
@require_mobile_session
def exam_schedule():
    """Return the authenticated student's personalized exam schedule."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_exam_schedule")
    if limited is not None:
        return limited
    semester_id = request.args.get("semester_id", type=int)
    requested_term_code = request.args.get("term_code", type=str)
    requested_mode = request.args.get("mode", type=str) or "applied"
    if requested_mode not in {"applied", "all_subjects"}:
        return jsonify({"error": "invalid_mode"}), 400
    resolved_semester_id = semester_id if semester_id is not None else current_semester_id()
    semester = semester_by_id(resolved_semester_id) if resolved_semester_id is not None else None
    if semester_id is not None and semester is None:
        return jsonify({"error": "semester_not_found"}), 404
    if resolved_semester_id is None:
        return jsonify(
            {
                "student": None,
                "semester": None,
                "exams": [],
                "available_terms": [],
                "selected_term_code": None,
                "generated_at": _utcnow().isoformat(),
            }
        )

    user = mobile_auth_get_user_by_id(session["user_id"])
    data_username = mobile_auth_data_username(user["radius_username"])
    student = student_identity_for_username(data_username)
    if student["student_name"] is None and student["student_index"] is None:
        return jsonify({"error": "student_not_found"}), 404

    terms_semester_id = current_semester_id() or resolved_semester_id
    available_terms = exam_terms_all(terms_semester_id)
    available_term_codes = {row["term_code"] for row in available_terms}
    if requested_term_code is not None and requested_term_code not in available_term_codes:
        return jsonify({"error": "exam_term_not_found"}), 404
    resolved_term_code = requested_term_code or (available_terms[0]["term_code"] if available_terms else None)

    exams_source = (
        student_exam_schedule_for_student(data_username, mode=requested_mode)
        if resolved_term_code is None
        else student_exam_schedule_for_student(data_username, resolved_term_code, requested_mode)
    )

    def _clean_optional_location(value):
        text = str(value or "").strip()
        if not text or text.lower() == "null" or text == "Непознато":
            return None
        return text

    exams = [
        {
            "term_code": row["term_code"],
            "course_code": row["course_code"],
            "subject_id": row["subject_id"],
            "subject_name": row["subject_name"],
            "exam_date": row["exam_date"],
            "exam_hour": row["exam_hour"],
            "is_applied": bool(row["is_applied"]),
            "location": _clean_optional_location(row["location"]),
            "location_latitude": row["location_latitude"],
            "location_longitude": row["location_longitude"],
            "location_is_building": bool(row["location_is_building"]),
        }
        for row in exams_source
    ]
    return jsonify(
        {
            "student": student,
            "semester": semester,
            "exams": exams,
            "available_terms": available_terms,
            "selected_term_code": resolved_term_code,
            "generated_at": _utcnow().isoformat(),
        }
    )


@bp.route("/mobile/exam_applications", methods=["POST"])
@require_mobile_session
def exam_application_toggle():
    """Set whether the current student is applied for one subject's exam."""
    session = g.mobile_auth_session
    limited = mobile_session_rate_limit("mobile_exam_applications")
    if limited is not None:
        return limited
    payload = request.get_json(silent=True) or {}
    term_code = str(payload.get("term_code", "")).strip()
    subject_id = payload.get("subject_id")
    applied = payload.get("applied")

    if not term_code:
        return jsonify({"error": "term_code_required"}), 400
    if subject_id is None:
        return jsonify({"error": "subject_id_required"}), 400
    try:
        subject_id = int(subject_id)
    except (TypeError, ValueError):
        return jsonify({"error": "subject_id_invalid"}), 400
    applied = _parse_exam_application_bool(applied)
    if applied is None:
        return jsonify({"error": "applied_required"}), 400

    user = mobile_auth_get_user_by_id(session["user_id"])
    context, error = _validate_exam_application_context(
        user,
        term_code,
        subject_id,
    )
    if error is not None:
        return error
    data_username = context["data_username"]

    if _exam_application_two_factor_required(user):
        return jsonify({"error_code": "two_factor_required", "error": "Two-factor confirmation required."}), 401

    try:
        hypatia_response = _hypatia_exam_application_request(
            data_username=data_username,
            term_code=term_code,
            subject_id=subject_id,
            applied=applied,
        )
    except HypatiaExamApplicationError as error:
        return (
            jsonify(
                {
                    "error_code": error.error_code or "hypatia_exam_application_rejected",
                    "error": error.message or "Hypatia rejected the request.",
                }
            ),
            error.status_code,
        )
    except RuntimeError as error:
        if str(error) == "hypatia_exam_application_url_missing":
            return jsonify({"error_code": "hypatia_exam_application_url_missing", "error": "Hypatia is temporarily unavailable."}), 503
        if str(error) == "hypatia_exam_application_unavailable":
            return jsonify({"error_code": "hypatia_exam_application_unavailable", "error": "Hypatia is temporarily unavailable."}), 503
        raise

    if not hypatia_response.get("ok", True):
        return jsonify(
            {
                "error_code": hypatia_response.get("error_code", "hypatia_exam_application_rejected"),
                "error": hypatia_response.get("error", "Hypatia rejected the request."),
            }
        ), int(hypatia_response.get("status_code", 400) or 400)

    conn = get_db()
    with conn:
        if applied:
            cur = conn.execute(
                """
                INSERT INTO exam_applications (term_code, subject_id, student_username)
                VALUES (?, ?, ?)
                ON CONFLICT(term_code, subject_id, student_username) DO NOTHING
                """,
                (term_code, subject_id, data_username),
            )
        else:
            cur = conn.execute(
                """
                DELETE FROM exam_applications
                WHERE term_code = ? AND subject_id = ? AND student_username = ?
                """,
                (term_code, subject_id, data_username),
            )

    applied_row = get_db().execute(
        """
        SELECT 1
        FROM exam_applications
        WHERE term_code = ? AND subject_id = ? AND student_username = ?
        """,
        (term_code, subject_id, data_username),
    ).fetchone()
    applied_now = applied_row is not None

    return jsonify(
        {
            "ok": True,
            "term_code": term_code,
            "subject_id": subject_id,
            "applied": applied_now,
            "changed": bool(cur.rowcount),
        }
    )
