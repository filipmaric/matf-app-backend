# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Application factory for the classroom reservation system."""

import logging
import os

from flask import Flask, url_for
from logging.handlers import RotatingFileHandler

from config import (
    APPLICATION_ROOT,
    BACKEND_SERVICE_BEARER_TOKEN,
    IS_PRODUCTION,
    LOG_FILE,
    MOBILE_AUTH_SESSION_DAYS,
    SECRET_KEY,
)
from config import (
    STATIC_URL_PATH,
    STUDENT_AUTH_MODE,
    STUDENT_RADIUS_DICTIONARY,
    STUDENT_RADIUS_SECRET,
    STUDENT_RADIUS_SERVER,
    TEACHER_AUTH_MODE,
    TEACHER_RADIUS_DICTIONARY,
    TEACHER_RADIUS_SECRET,
    TEACHER_RADIUS_SERVER,
)
from db import init_app as init_db_app


def create_app():
    """Create and configure the Flask application instance."""
    app = Flask(__name__, static_url_path=STATIC_URL_PATH)
    app.config["APPLICATION_ROOT"] = APPLICATION_ROOT
    app.config["BACKEND_SERVICE_BEARER_TOKEN"] = BACKEND_SERVICE_BEARER_TOKEN
    app.config["MOBILE_AUTH_SESSION_DAYS"] = MOBILE_AUTH_SESSION_DAYS
    app.secret_key = SECRET_KEY
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    init_db_app(app)

    @app.template_global("app_url_for")
    def app_url_for(endpoint, *args, **kwargs):
        """Build a route URL that remains correct behind a path prefix."""
        path = url_for(endpoint, *args, **kwargs)
        application_root = app.config["APPLICATION_ROOT"].rstrip("/")
        if application_root and not (path == application_root or path.startswith(f"{application_root}/")):
            return application_root + path
        return path

    if IS_PRODUCTION:
        if TEACHER_AUTH_MODE != "radius":
            raise RuntimeError("TEACHER_AUTH_MODE must be radius when APP_ENV=production")
        if STUDENT_AUTH_MODE != "radius":
            raise RuntimeError("STUDENT_AUTH_MODE must be radius when APP_ENV=production")
        for name in (
            "TEACHER_RADIUS_SERVER",
            "TEACHER_RADIUS_SECRET",
            "TEACHER_RADIUS_DICTIONARY",
            "STUDENT_RADIUS_SERVER",
            "STUDENT_RADIUS_SECRET",
            "STUDENT_RADIUS_DICTIONARY",
        ):
            if not os.getenv(name):
                raise RuntimeError(f"{name} must be set when APP_ENV=production")

    try:
        handler = RotatingFileHandler(LOG_FILE, maxBytes=1000000, backupCount=3)
        handler.setLevel(logging.INFO)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
    except OSError:
        # Keep the app usable when the log path is not writable locally.
        pass

    return app
