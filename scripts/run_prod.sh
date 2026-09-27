#!/usr/bin/env bash
# Copyright (c) 2026 Filip Marić. See LICENCE.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Production-style defaults for deployment under /matf-app.
# TEACHER_AUTH_MODE controls teacher authentication; STUDENT_AUTH_MODE controls student authentication.
export APP_ENV="${APP_ENV:-production}"
export APPLICATION_ROOT="${APPLICATION_ROOT:-/matf-app}"
export STATIC_URL_PATH="${STATIC_URL_PATH:-/matf-app/static}"
export TEACHER_AUTH_MODE="${TEACHER_AUTH_MODE:-radius}"
export STUDENT_AUTH_MODE="${STUDENT_AUTH_MODE:-radius}"

: "${SECRET_KEY:?Set SECRET_KEY before starting the server}"
: "${BACKEND_SERVICE_BEARER_TOKEN:?Set BACKEND_SERVICE_BEARER_TOKEN before starting the server}"
: "${ATTENDANCE_SECRET:?Set ATTENDANCE_SECRET before starting the server}"
: "${MOBILE_ACTION_OTP_SECRET:?Set MOBILE_ACTION_OTP_SECRET before starting the server}"
: "${TEACHER_RADIUS_SERVER:?Set TEACHER_RADIUS_SERVER before starting the server}"
: "${TEACHER_RADIUS_SECRET:?Set TEACHER_RADIUS_SECRET before starting the server}"
: "${TEACHER_RADIUS_DICTIONARY:?Set TEACHER_RADIUS_DICTIONARY before starting the server}"
: "${STUDENT_RADIUS_SERVER:?Set STUDENT_RADIUS_SERVER before starting the server}"
: "${STUDENT_RADIUS_SECRET:?Set STUDENT_RADIUS_SECRET before starting the server}"
: "${STUDENT_RADIUS_DICTIONARY:?Set STUDENT_RADIUS_DICTIONARY before starting the server}"
: "${FCM_PROJECT_ID:?Set FCM_PROJECT_ID before starting the server}"
: "${FCM_SERVICE_ACCOUNT_FILE:?Set FCM_SERVICE_ACCOUNT_FILE before starting the server}"
: "${GRADES_SOURCE_URL:?Set GRADES_SOURCE_URL before starting the server}"
: "${GRADES_REQUEST_SIGNING_SECRET:?Set GRADES_REQUEST_SIGNING_SECRET before starting the server}"
: "${HYPATIA_EXAM_APPLICATIONS_URL:?Set HYPATIA_EXAM_APPLICATIONS_URL before starting the server}"
: "${HYPATIA_LINK_URL:?Set HYPATIA_LINK_URL before starting the server}"
: "${HYPATIA_REQUEST_SIGNING_SECRET:?Set HYPATIA_REQUEST_SIGNING_SECRET before starting the server}"

exec "$ROOT_DIR/.venv/bin/python" app.py
