# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Mobile notification inbox endpoints."""

from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from db import (
    mobile_auth_get_user_by_id,
    student_identity_for_username,
    student_notification_delete,
    student_notifications_mark_all_read,
    student_notification_mark_read,
    student_notifications_for_student,
    student_notifications_unread_count,
)
from mobile_auth import mobile_auth_data_username, require_mobile_session
from semester import current_semester_id, semester_by_id


bp = Blueprint("mobile_notifications", __name__)


def _utcnow():
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def _notification_payload(row):
    target_group_names = sorted(
        [
        name.strip()
        for name in str(row["target_group_names"] or "").split(",")
        if name.strip()
        ]
    )
    return {
        "notification_id": row["notification_id"],
        "source_id": row["source_id"],
        "semester_id": row["semester_id"],
        "course_id": row["course_id"],
        "course_code": row["course_code"],
        "course_name": row["course_name"],
        "teacher_username": row["teacher_username"],
        "teacher_name": row["teacher_name"],
        "title": row["title"],
        "body": row["body"],
        "published_at": row["published_at"],
        "updated_at": row["updated_at"],
        "delivered_at": row["delivered_at"],
        "read_at": row["read_at"],
        "is_read": row["read_at"] is not None,
        "target_groups": target_group_names,
    }


@bp.route("/mobile/notifications", methods=["GET"])
@require_mobile_session
def notifications():
    """Return the authenticated student's inbox."""
    semester_id = request.args.get("semester_id", type=int)
    resolved_semester_id = semester_id if semester_id is not None else current_semester_id()
    semester = semester_by_id(resolved_semester_id) if resolved_semester_id is not None else None
    if semester_id is not None and semester is None:
        return jsonify({"error": "semester_not_found"}), 404
    if resolved_semester_id is None:
        return jsonify(
            {
                "student": None,
                "semester": None,
                "unread_count": 0,
                "notifications": [],
                "generated_at": _utcnow().isoformat(),
            }
        )

    session = g.mobile_auth_session
    user = mobile_auth_get_user_by_id(session["user_id"])
    data_username = mobile_auth_data_username(user["radius_username"])
    student = student_identity_for_username(data_username)
    if student["student_name"] is None and student["student_index"] is None:
        return jsonify({"error": "student_not_found"}), 404

    limit = request.args.get("limit", default=50, type=int)
    offset = request.args.get("offset", default=0, type=int)
    rows = student_notifications_for_student(
        data_username,
        resolved_semester_id,
        limit=limit,
        offset=offset,
    )
    return jsonify(
        {
            "student": student,
            "semester": semester,
            "unread_count": student_notifications_unread_count(
                data_username, resolved_semester_id
            ),
            "notifications": [_notification_payload(row) for row in rows],
            "generated_at": _utcnow().isoformat(),
        }
    )


@bp.route("/mobile/notifications/unread_count", methods=["GET"])
@require_mobile_session
def unread_count():
    """Return the unread notification count for the authenticated student."""
    semester_id = request.args.get("semester_id", type=int)
    resolved_semester_id = semester_id if semester_id is not None else current_semester_id()
    semester = semester_by_id(resolved_semester_id) if resolved_semester_id is not None else None
    if semester_id is not None and semester is None:
        return jsonify({"error": "semester_not_found"}), 404
    if resolved_semester_id is None:
        return jsonify({"semester": None, "unread_count": 0})

    session = g.mobile_auth_session
    user = mobile_auth_get_user_by_id(session["user_id"])
    data_username = mobile_auth_data_username(user["radius_username"])
    student = student_identity_for_username(data_username)
    if student["student_name"] is None and student["student_index"] is None:
        return jsonify({"error": "student_not_found"}), 404

    return jsonify(
        {
            "semester": semester,
            "unread_count": student_notifications_unread_count(
                data_username, resolved_semester_id
            ),
        }
    )


@bp.route("/mobile/notifications/<int:notification_id>/read", methods=["POST"])
@require_mobile_session
def mark_read(notification_id):
    """Mark one inbox item as read for the authenticated student."""
    session = g.mobile_auth_session
    user = mobile_auth_get_user_by_id(session["user_id"])
    data_username = mobile_auth_data_username(user["radius_username"])
    student = student_identity_for_username(data_username)
    if student["student_name"] is None and student["student_index"] is None:
        return jsonify({"error": "student_not_found"}), 404

    row = student_notification_mark_read(data_username, notification_id)
    if row is None:
        return jsonify({"error": "notification_not_found"}), 404
    return jsonify({"ok": True, "read_at": row["read_at"]})


@bp.route("/mobile/notifications/<int:notification_id>", methods=["DELETE"])
@require_mobile_session
def delete_notification(notification_id):
    """Delete one inbox item for the authenticated student."""
    session = g.mobile_auth_session
    user = mobile_auth_get_user_by_id(session["user_id"])
    data_username = mobile_auth_data_username(user["radius_username"])
    student = student_identity_for_username(data_username)
    if student["student_name"] is None and student["student_index"] is None:
        return jsonify({"error": "student_not_found"}), 404

    row = student_notification_delete(data_username, notification_id)
    if row is None:
        return jsonify({"error": "notification_not_found"}), 404

    semester_id = request.args.get("semester_id", type=int)
    resolved_semester_id = semester_id if semester_id is not None else current_semester_id()
    unread_count = 0 if resolved_semester_id is None else student_notifications_unread_count(
        data_username,
        resolved_semester_id,
    )
    return jsonify({"ok": True, "unread_count": unread_count})


@bp.route("/mobile/notifications/mark_all_read", methods=["POST"])
@require_mobile_session
def mark_all_read():
    """Mark all unread notifications as read for the authenticated student."""
    semester_id = request.args.get("semester_id", type=int)
    if semester_id is None:
        payload = request.get_json(silent=True) or {}
        semester_id = payload.get("semester_id")
        if semester_id is not None:
            try:
                semester_id = int(semester_id)
            except (TypeError, ValueError):
                semester_id = None
    resolved_semester_id = semester_id if semester_id is not None else current_semester_id()
    semester = semester_by_id(resolved_semester_id) if resolved_semester_id is not None else None
    if semester_id is not None and semester is None:
        return jsonify({"error": "semester_not_found"}), 404
    if resolved_semester_id is None:
        return jsonify({"ok": True, "updated_count": 0, "unread_count": 0})
    session = g.mobile_auth_session
    user = mobile_auth_get_user_by_id(session["user_id"])
    data_username = mobile_auth_data_username(user["radius_username"])
    student = student_identity_for_username(data_username)
    if student["student_name"] is None and student["student_index"] is None:
        return jsonify({"error": "student_not_found"}), 404

    updated_count = student_notifications_mark_all_read(data_username, resolved_semester_id)
    unread_count = student_notifications_unread_count(data_username, resolved_semester_id)
    return jsonify({"ok": True, "updated_count": updated_count, "unread_count": unread_count})
