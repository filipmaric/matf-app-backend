# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Minimal Firebase Cloud Messaging helper for mobile notifications."""

from __future__ import annotations

import json
from pathlib import Path

import requests
from functools import wraps

from flask import Blueprint, current_app, g, has_app_context, jsonify, request

from config import FCM_PROJECT_ID, FCM_SERVICE_ACCOUNT_FILE, FCM_SERVICE_ACCOUNT_JSON
from db import mobile_device_by_device_id, mobile_device_tokens_for_students, query_db

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"


bp = Blueprint("mobile_push", __name__)


def _require_service_api_key(fn):
    """Require the backend service bearer token for push test routes."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token = auth.split(" ", 1)[1].strip()
        if token != current_app.config["BACKEND_SERVICE_BEARER_TOKEN"]:
            return jsonify({"error": "Unauthorized"}), 401
        g.service_auth = True
        return fn(*args, **kwargs)

    return wrapper


def notification_student_usernames(notification_id):
    """Return distinct student usernames targeted by one notification."""
    rows = query_db(
        """
        SELECT DISTINCT se.student_username
        FROM notification_targets nt
        JOIN student_enrollments se
          ON se.group_id = nt.group_id
        JOIN notifications n ON n.id = nt.notification_id
        WHERE nt.notification_id = ?
          AND se.semester_id = n.semester_id
          AND se.course_id = n.course_id
        ORDER BY se.student_username
        """,
        (notification_id,),
    )
    return [row["student_username"] for row in rows]


def _load_service_account_info():
    """Load the Firebase service account JSON from env or a file path."""
    if FCM_SERVICE_ACCOUNT_JSON:
        return json.loads(FCM_SERVICE_ACCOUNT_JSON)
    if FCM_SERVICE_ACCOUNT_FILE:
        return json.loads(Path(FCM_SERVICE_ACCOUNT_FILE).read_text(encoding="utf-8"))
    return None


def _load_access_token():
    """Return an OAuth access token for the Firebase HTTP v1 API."""
    service_account_info = _load_service_account_info()
    if not service_account_info or not FCM_PROJECT_ID:
        return None

    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError:
        current_app.logger.warning(
            "Skipping push delivery because google-auth is not installed in the backend environment"
        )
        return None

    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=[FCM_SCOPE],
    )
    credentials.refresh(Request())
    return credentials.token


def _send_one_push(installation_id, title, body, notification_id, extra_data=None):
    """Send one push message to one device registration token."""
    access_token = _load_access_token()
    if not access_token:
        if has_app_context():
            current_app.logger.info(
                "Skipping push delivery for notification %s because FCM credentials are not configured",
                notification_id,
            )
        else:
            print(
                f"Skipping push delivery for notification {notification_id} because FCM credentials are not configured"
            )
        return {"ok": True, "sent": 0, "skipped": True}

    payload = {
        "message": {
            "token": installation_id,
            "data": {
                "notification_id": str(notification_id),
                "title": title,
                "body": body,
            },
            "android": {
                "priority": "HIGH",
            },
        }
    }
    if extra_data:
        for key, value in extra_data.items():
            if value is None:
                continue
            payload["message"]["data"][str(key)] = str(value)
    response = requests.post(
        FCM_ENDPOINT.format(project_id=FCM_PROJECT_ID),
        json=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def send_notification_push(notification_id, title, body):
    """Send one notification to all enabled mobile devices for its students."""
    student_usernames = notification_student_usernames(notification_id)
    device_rows = mobile_device_tokens_for_students(student_usernames)
    installation_ids = [row["installation_id"] for row in device_rows if row["installation_id"]]
    if not installation_ids:
        return {"ok": True, "sent": 0}

    results = []
    for installation_id in installation_ids:
        results.append(_send_one_push(installation_id, title, body, notification_id))
    return {"ok": True, "sent": len(installation_ids), "results": results}


def dispatch_notification_push(notification_id):
    """Look up one notification and send it to the matching student devices."""
    row = query_db(
        "SELECT id, title, body FROM notifications WHERE id = ?",
        (notification_id,),
        one=True,
    )
    if row is None:
        return {"ok": False, "error": "notification_not_found"}
    return send_notification_push(notification_id, row["title"], row["body"])


@bp.route("/service/mobile/push-test", methods=["POST"])
@_require_service_api_key
def push_test():
    """Send one verification push to one stored device token."""
    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id", "")).strip()
    title = str(payload.get("title", "MATF test push")).strip() or "MATF test push"
    body = str(payload.get("body", "Test push from the backend")).strip() or "Test push from the backend"

    if not device_id:
        return jsonify({"error": "device_id_required"}), 400

    device = mobile_device_by_device_id(device_id)
    if device is None:
        return jsonify({"error": "device_not_found"}), 404

    result = _send_one_push(device["installation_id"], title, body, notification_id=0)
    return jsonify(
        {
            "ok": True,
            "device_id": device_id,
            "student_username": device["student_username"],
            "result": result,
        }
    )
