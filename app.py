# Copyright (c) 2026 Filip Marić. See LICENCE.
"""
Flask app entry point and route registration.

Route overview:
- Health checks:
  - `/healthz`: lightweight health check.
- Mobile:
  - Authentication and session state.
  - `/mobile/login`: logs in a mobile client and issues a bearer token.
  - `/mobile/logout`: revokes the current mobile session.
  - `/mobile/me`: returns the current mobile user and session state.
  - `/mobile/sessions`: lists the current mobile session summary.
  - 2FA.
  - `/mobile/2fa`: returns the current 2FA state.
  - `/mobile/2fa/setup`: starts 2FA setup.
  - `/mobile/2fa/confirm`: confirms 2FA setup with an OTP code.
  - `/mobile/2fa/clear`: clears an active 2FA confirmation.
  - `/mobile/2fa/disable`: disables 2FA.
  - `/mobile/2fa/link/complete`: completes the 2FA link-based confirmation flow.
  - Attendance history.
  - `/mobile/attendance/history`: returns attendance history summaries.
  - Push token.
  - `/mobile/push-token`: stores or clears the push token for the device.
  - Schedule, grades, and exam applications.
  - `/mobile/buildings`: returns building locations.
  - `/mobile/exam_schedule`: returns the exam schedule for the mobile app.
  - `/mobile/grades`: returns the student's grades.
  - `/mobile/exam_applications`: applies for or cancels an exam application.
  - Notifications.
  - `/mobile/notifications`: lists notifications.
  - `/mobile/notifications/unread_count`: returns the unread notification count.
  - `/mobile/notifications/<id>`: deletes one notification.
  - `/mobile/notifications/<id>/read`: marks one notification as read.
  - `/mobile/notifications/mark_all_read`: marks all notifications as read.

  
- Web:
  - browser login/logout endpoints and simple identity checks for the web app.
  - `/login`: web login endpoint.
  - `/logout`: web logout endpoint.
  - `/me`: returns the current web user identity.
  - `/is_admin/<username>`: checks whether one web user is an admin.
  - the main web landing page.
  - `/`: renders the main web landing page.

  - room list and current occupancy views.
  - `/rooms`: lists rooms.
  - `/occupancy`: shows room occupancy.

  - reservation writes that create, update, or cancel reservations.
  - `/reserve`: creates a reservation.
  - `/reserve/bulk`: creates reservations in bulk.
  - `/reservation/<id>`: updates or deletes one reservation.
  - `/weekly_session_cancel`: cancels one weekly session.

  - the personal reservations page and its JSON data feed.
  - `/my_reservations`: renders the personal reservations page.
  - `/my_reservations_data`: returns the personal reservations data feed.

  - the admin-only calendar page and update endpoint, plus the authenticated
    read-only calendar feed for Android.
  - `/calendar`: renders the admin calendar page.
  - `/calendar_data`: returns admin calendar data.
  - `/mobile/calendar`: returns read-only calendar data for Android.
  - `/update_calendar`: updates admin calendar data.

  - teacher-oriented course-session explorer and data feed.
  - `/teacher_sessions`: renders the teacher sessions view.
  - `/teacher_sessions_data`: returns the teacher sessions data feed.

  - group-oriented course-session explorer and data feed.
  - `/group_sessions`: renders the group sessions view.
  - `/group_sessions_data`: returns the group sessions data feed.
  - `/oral_exams`: renders the teacher oral-exam selection page.
  - `/oral_exams_data`: returns the current teacher's exam terms, courses, and groups.
  - `/oral_exams_schedule`: creates, deletes, and assigns room reservations to
    teacher-managed oral-exam terms.
  
  - QR attendance, challenge refresh, check-in submission, review demo, and geofence checks.
  - `/attendance/<kind>/<id>/<date>`: renders the attendance page.
  - `/attendance/<kind>/<id>/<date>/join`: creates or resumes an attendance join session.
  - `/attendance/<kind>/<id>/<date>/join/<token>`: opens a QR join link.
  - `/attendance/<kind>/<id>/<date>/challenge`: returns the current attendance challenge.
  - `/attendance/<kind>/<id>/<date>/data`: returns attendance data for the page.
  - `/attendance/<kind>/<id>/<date>/geofence`: checks geofence access.
  - `/attendance/<kind>/<id>/<date>/spot_check`: opens the spot-check page.
  - `/attendance/<kind>/<id>/<date>/join` (POST): submits an attendance join attempt.
  - `/attendance/<kind>/<id>/<date>/spot_check` (POST): submits a spot-check attempt.
  - `/attendance/review-demo`: renders the review attendance demo page.


- Other:
  - internal helper endpoint for push notification testing.
  - `/service/mobile/push-test`: sends a test push notification.
"""

import argparse

from config import (
    DATABASE,
)
from factory import create_app
from db import execute_db, get_db, init_db, query_db

app = create_app()
import main as main_mod  # noqa: E402,F401 - registers the main page route on import
import auth  # noqa: E402,F401 - registers auth routes and helpers on import
from auth import *  # noqa: F401,F403,E402 - re-export auth helpers and routes
import mobile_auth as mobile_auth_mod  # noqa: E402,F401 - registers mobile API routes on import
import mobile_attendance as mobile_attendance_mod  # noqa: E402,F401 - registers mobile attendance routes on import
import mobile_grades as mobile_grades_mod  # noqa: E402,F401 - registers mobile grades routes on import
import mobile_notifications as mobile_notifications_mod  # noqa: E402,F401 - registers mobile notification routes on import
import mobile_calendar as mobile_calendar_mod  # noqa: E402,F401 - registers mobile calendar routes on import
import mobile_push as mobile_push_mod  # noqa: E402,F401 - registers mobile push routes on import

auth.init_app(app)

import occupancy as occupancy_mod  # noqa: E402,F401 - registers room and occupancy routes on import
from occupancy import *  # noqa: F401,F403,E402 - re-export occupancy helpers for tests and callers
import attendance as attendance_mod  # noqa: E402,F401 - registers attendance routes on import
from attendance import *  # noqa: F401,F403,E402 - re-export attendance helpers for tests and callers

import calendar_views as calendar_views_mod  # noqa: E402,F401 - registers calendar routes on import
from calendar_views import *  # noqa: F401,F403,E402 - re-export calendar helpers for tests and callers

import teacher_sessions_views as teacher_sessions_views_mod  # noqa: E402,F401 - teacher course-session explorer
import group_sessions_views as group_sessions_views_mod  # noqa: E402,F401 - group course-session explorer
import oral_exam_views as oral_exam_views_mod  # noqa: E402,F401 - oral-exam selection

import reservations as reservations_mod  # noqa: E402,F401 - registers reservation routes on import
import semester as semester_mod  # noqa: E402,F401 - shared semester helpers on import
import reservations_views as reservations_views_mod  # noqa: E402,F401 - registers semester/personal-reservation routes on import
from semester import *  # noqa: F401,F403,E402 - re-export semester helpers for tests and callers
from reservations_views import *  # noqa: F401,F403,E402 - re-export semester/personal-reservation helpers for tests and callers

app.register_blueprint(auth.bp)
app.register_blueprint(mobile_auth_mod.bp)
app.register_blueprint(mobile_attendance_mod.bp)
app.register_blueprint(mobile_grades_mod.bp)
app.register_blueprint(mobile_notifications_mod.bp)
app.register_blueprint(mobile_calendar_mod.bp)
app.register_blueprint(mobile_push_mod.bp)
app.register_blueprint(main_mod.bp)
app.register_blueprint(occupancy_mod.bp)
app.register_blueprint(attendance_mod.bp)
app.register_blueprint(calendar_views_mod.bp)
app.register_blueprint(teacher_sessions_views_mod.bp)
app.register_blueprint(group_sessions_views_mod.bp)
app.register_blueprint(oral_exam_views_mod.bp)
app.register_blueprint(reservations_mod.bp)
app.register_blueprint(reservations_views_mod.bp)
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MatF App backend")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "init-db"),
        default="run",
        help="run the web app or initialize the database schema",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    with app.app_context():
        if args.command == "init-db":
            created = init_db()
            if created:
                print(f"Initialized database schema at {DATABASE}")
            else:
                print(f"Database already initialized at {DATABASE}")
        else:
            get_db()
            app.run(host=args.host, port=args.port, debug=False)
