# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Main page blueprint for the classroom reservation app."""

from flask import Blueprint, jsonify, render_template


bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    """Render the main timetable page."""
    return render_template("index.html")


@bp.route("/current-occupancy")
def current_occupancy():
    """Render the live, one-building-at-a-time occupancy display."""
    return render_template("current_occupancy.html")


@bp.route("/healthz")
def healthz():
    """Expose a lightweight health check for the web frontend."""
    return jsonify({"ok": True})
