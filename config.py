# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Central application configuration and environment-backed constants."""

import json
import os


# Absolute path to the application directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Shared workspace data directory used by import/export tools and the app database.
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, os.pardir, "data"))
# SQLite database file used by the application.
DATABASE = os.path.join(DATA_DIR, "app.db")
# SQL schema file used when creating the database from scratch.
SCHEMA_FILE = os.path.join(BASE_DIR, "schema.sql")
# Current runtime mode: development, prod, or production.
APP_ENV = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).lower()
# True when the application should enforce production-only checks.
IS_PRODUCTION = APP_ENV in {"production", "prod"}


def load_secret_env(name, dev_default):
    """Read a secret from the environment and require it in production."""
    value = os.getenv(name)
    if value:
        return value
    if IS_PRODUCTION:
        raise RuntimeError(f"{name} must be set when APP_ENV=production")
    return dev_default


def load_env(name, dev_default):
    """Read a non-secret configuration value from the environment."""
    value = os.getenv(name)
    if value:
        return value
    if IS_PRODUCTION:
        raise RuntimeError(f"{name} must be set when APP_ENV=production")
    return dev_default


def load_json_env(name, dev_default):
    """Read a JSON configuration value from the environment."""
    value = os.getenv(name)
    if not value:
        if IS_PRODUCTION:
            raise RuntimeError(f"{name} must be set when APP_ENV=production")
        return dev_default

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must contain valid JSON") from exc

    if not isinstance(parsed, list):
        raise RuntimeError(f"{name} must contain a JSON list")

    normalized = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise RuntimeError(f"{name}[{index}] must be a JSON object")

        try:
            latitude = float(item["latitude"])
            longitude = float(item["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"{name}[{index}] must define latitude and longitude") from exc

        radius_value = item.get("radius_m", item.get("radius", 100))
        try:
            radius_m = float(radius_value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{name}[{index}].radius_m must be numeric") from exc
        if radius_m <= 0:
            raise RuntimeError(f"{name}[{index}].radius_m must be positive")

        label = str(item.get("name", "")).strip() or f"Lokacija {index + 1}"
        normalized.append(
            {
                "name": label,
                "latitude": latitude,
                "longitude": longitude,
                "radius_m": radius_m,
            }
        )

    return normalized


def load_bool_env(name, dev_default=False):
    """Read a boolean configuration value from the environment."""
    value = os.getenv(name)
    if not value:
        return bool(dev_default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


# URL prefix where the app is mounted. In production it is /matf-app.
STATIC_URL_PATH = os.getenv("STATIC_URL_PATH", "/static")
# Base URL path used when Flask builds links for this app.
APPLICATION_ROOT = os.getenv("APPLICATION_ROOT", "/")
# Path to the application log file.
LOG_FILE = os.getenv("APP_LOG_FILE", os.path.join(BASE_DIR, "app.log"))
# Secret used to sign attendance QR/attempt tokens.
ATTENDANCE_SECRET = load_secret_env("ATTENDANCE_SECRET", "attendance-secret")
# Secret used to sign mobile action setup codes.
MOBILE_ACTION_OTP_SECRET = load_secret_env("MOBILE_ACTION_OTP_SECRET", "mobile-action-otp-secret")
# How many seconds one QR token stays valid before it rotates.
ATTENDANCE_JOIN_TOKEN_TTL = int(os.getenv("ATTENDANCE_JOIN_TOKEN_TTL", "8"))
# How many seconds one challenge number stays visible before it changes.
ATTENDANCE_CHALLENGE_TTL = int(os.getenv("ATTENDANCE_CHALLENGE_TTL", "10"))
# How many seconds the student attendance attempt stays valid after scanning the QR code.
ATTENDANCE_ATTEMPT_TTL = int(os.getenv("ATTENDANCE_ATTEMPT_TTL", "90"))
# How many seconds a mobile action OTP setup code remains valid.
MOBILE_ACTION_OTP_TTL = int(os.getenv("MOBILE_ACTION_OTP_TTL", "180"))
# How many days a successful 2FA verification stays trusted for sensitive actions.
MOBILE_TWO_FACTOR_GRACE_DAYS = int(os.getenv("MOBILE_TWO_FACTOR_GRACE_DAYS", "7"))
# How many older attendance challenge rounds are still accepted as a grace window.
ATTENDANCE_PREVIOUS_CHALLENGE_ROUNDS = int(os.getenv("ATTENDANCE_PREVIOUS_CHALLENGE_ROUNDS", "2"))
# How many minutes before and after class attendance is allowed.
ATTENDANCE_CLASS_GRACE_MINUTES = int(os.getenv("ATTENDANCE_CLASS_GRACE_MINUTES", "150"))
# How many days an Android app session remains valid.
MOBILE_AUTH_SESSION_DAYS = int(os.getenv("MOBILE_AUTH_SESSION_DAYS", "30"))
# Whether review-only access paths are enabled.
REVIEW_MODE = load_bool_env("REVIEW_MODE", False)
# Teacher login mode: "mock" for local development or "radius" in production.
TEACHER_AUTH_MODE = os.getenv("TEACHER_AUTH_MODE", "mock").lower()
# Address of the teacher RADIUS server.
TEACHER_RADIUS_SERVER = load_env("TEACHER_RADIUS_SERVER", "147.91.66.2")
# Shared secret used when talking to the teacher RADIUS server.
TEACHER_RADIUS_SECRET = load_secret_env("TEACHER_RADIUS_SECRET", "raspored2mainWebsite").encode()
# Dictionary file that tells the RADIUS client which attribute names to use.
TEACHER_RADIUS_DICTIONARY = load_env("TEACHER_RADIUS_DICTIONARY", "/var/www/matf-app/radius/dictionary")
# Student login mode: "mock" for local development or "radius" in production.
STUDENT_AUTH_MODE = os.getenv("STUDENT_AUTH_MODE", "mock").lower()
# Address of the student RADIUS server.
STUDENT_RADIUS_SERVER = load_env("STUDENT_RADIUS_SERVER", "147.91.66.2")
# Shared secret used when talking to the student RADIUS server.
STUDENT_RADIUS_SECRET = load_secret_env("STUDENT_RADIUS_SECRET", "raspored2mainWebsite").encode()
# Dictionary file that tells the RADIUS client which attribute names to use.
STUDENT_RADIUS_DICTIONARY = load_env("STUDENT_RADIUS_DICTIONARY", "/var/www/matf-app/radius/dictionary")
# Review login credentials used for Play reviewer access.
MOBILE_AUTH_REVIEW_USERNAME = "google"
MOBILE_AUTH_REVIEW_PASSWORD = "review"
# Student username whose data the review account should display.
MOBILE_AUTH_REVIEW_DATA_USERNAME = "mr97125"
# Secret key used to protect backend service-only bearer requests.
BACKEND_SERVICE_BEARER_TOKEN = load_secret_env("BACKEND_SERVICE_BEARER_TOKEN", "dev-service-bearer-token")
# URL of the Hypatia exam-application authorization endpoint.
HYPATIA_EXAM_APPLICATIONS_URL = load_env("HYPATIA_EXAM_APPLICATIONS_URL", "")
# URL of the Hypatia 2FA link-confirmation page.
HYPATIA_LINK_URL = load_env("HYPATIA_LINK_URL", "")
# Shared secret used to sign backend-to-Hypatia exam-application requests.
HYPATIA_REQUEST_SIGNING_SECRET = load_secret_env(
    "HYPATIA_REQUEST_SIGNING_SECRET",
    "hypatia-request-signing-secret",
)
# Firebase Cloud Messaging HTTP v1 service account key file.
FCM_SERVICE_ACCOUNT_FILE = os.getenv(
    "FCM_SERVICE_ACCOUNT_FILE",
    os.path.join(BASE_DIR, "firebase-service-account.json"),
).strip()
# Firebase Cloud Messaging HTTP v1 service account JSON payload.
FCM_SERVICE_ACCOUNT_JSON = os.getenv("FCM_SERVICE_ACCOUNT_JSON", "").strip()
# Firebase Cloud Messaging project id.
FCM_PROJECT_ID = os.getenv("FCM_PROJECT_ID", "").strip()
# Flask session secret used for signed cookies and CSRF protection.
SECRET_KEY = load_secret_env("SECRET_KEY", "classroommatfreservations")
