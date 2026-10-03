# Copyright (c) 2026 Filip Marić. See LICENCE.
"""SQLite database helpers for the classroom reservation app."""

import hashlib
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from flask import g, has_app_context

import config
def _app_module():
    """Return the loaded app module when available."""
    return sys.modules.get("app") or sys.modules.get("__main__")


def _database_path():
    """Resolve the active database path from the app module or config defaults."""
    core = _app_module()
    if core is not None and hasattr(core, "DATABASE"):
        return core.DATABASE
    return config.DATABASE


def _schema_path():
    """Resolve the active schema path from the app module or config defaults."""
    core = _app_module()
    if core is not None and hasattr(core, "SCHEMA_FILE"):
        return core.SCHEMA_FILE
    return config.SCHEMA_FILE


def _database_has_schema(conn):
    """Check whether the main application schema is already present."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rooms'"
    ).fetchone()
    return bool(row)


def _table_exists(conn, table_name):
    """Check whether a table already exists in the current database."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def _ensure_attendance_schema(conn):
    """Create the attendance tables if they are missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY,
            event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
            event_id INTEGER NOT NULL,
            event_date TEXT NOT NULL,
            username TEXT NOT NULL,
            registration_source TEXT NOT NULL DEFAULT 'web' CHECK(registration_source IN ('web', 'android')),
            client_ip TEXT,
            geofence_checked INTEGER NOT NULL DEFAULT 0 CHECK(geofence_checked IN (0,1)),
            failed_attempts_before_success INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(event_kind, event_id, event_date, username)
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_records_event
            ON attendance_records(event_kind, event_id, event_date);
        CREATE INDEX IF NOT EXISTS idx_attendance_records_username_event
            ON attendance_records(username, event_kind, event_id, event_date);

        CREATE TABLE IF NOT EXISTS attendance_attempt_geofence_settings (
            event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
            event_id INTEGER NOT NULL,
            event_date TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
            PRIMARY KEY(event_kind, event_id, event_date)
        );

        CREATE TABLE IF NOT EXISTS attendance_guest_registration_settings (
            event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
            event_id INTEGER NOT NULL,
            event_date TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
            PRIMARY KEY(event_kind, event_id, event_date)
        );

        CREATE TABLE IF NOT EXISTS attendance_guest_devices (
            device_token_hash TEXT NOT NULL,
            event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
            event_id INTEGER NOT NULL,
            event_date TEXT NOT NULL,
            username TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(device_token_hash, event_kind, event_id, event_date)
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_guest_devices_event
            ON attendance_guest_devices(event_kind, event_id, event_date);

        CREATE TABLE IF NOT EXISTS attendance_session_settings (
            event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
            event_id INTEGER NOT NULL,
            event_date TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(event_kind, event_id, event_date)
        );

        CREATE TABLE IF NOT EXISTS attendance_attempt_failures (
            attempt_token TEXT PRIMARY KEY,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS attendance_spot_check_flags (
            attendance_record_id INTEGER PRIMARY KEY,
            teacher_username TEXT NOT NULL,
            flagged_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(attendance_record_id) REFERENCES attendance_records(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_weekly_sessions_day_room_start
            ON weekly_sessions(day_of_week, room_id, start_slot);
        """
    )
    conn.commit()


def _ensure_mobile_auth_schema(conn):
    """Create the Android auth tables if they are missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mobile_auth_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            radius_username TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            two_factor_enabled INTEGER NOT NULL DEFAULT 0 CHECK(two_factor_enabled IN (0, 1)),
            two_factor_setup_code TEXT,
            two_factor_setup_expires_at TEXT,
            two_factor_link_ticket TEXT,
            two_factor_link_ticket_expires_at TEXT,
            two_factor_link_action TEXT,
            two_factor_created_at TEXT,
            two_factor_confirmed_at TEXT,
            two_factor_last_verified_at TEXT
        );

        CREATE TABLE IF NOT EXISTS mobile_auth_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            device_name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_seen_ip TEXT,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            revoked_reason TEXT,
            FOREIGN KEY(user_id) REFERENCES mobile_auth_users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_mobile_auth_sessions_user_id
            ON mobile_auth_sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_mobile_auth_sessions_token_hash
            ON mobile_auth_sessions(token_hash);

        CREATE TABLE IF NOT EXISTS mobile_auth_device_login_policies (
            device_id TEXT PRIMARY KEY,
            last_username TEXT NOT NULL,
            last_login_date TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_mobile_auth_device_login_policies_login_date
            ON mobile_auth_device_login_policies(last_login_date);
        """
    )
    conn.commit()


def _ensure_mobile_device_schema(conn):
    """Create the mobile device registration table if it is missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mobile_devices (
            device_id TEXT PRIMARY KEY,
            student_username TEXT NOT NULL,
            device_name TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'android',
            installation_id TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
            last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_mobile_devices_student_enabled
            ON mobile_devices(student_username, enabled);
        """
    )
    conn.commit()


def _ensure_student_directory_schema(conn):
    """Create the student directory table if it is missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS students (
            username TEXT PRIMARY KEY,
            student_index TEXT NOT NULL,
            surname TEXT NOT NULL,
            given_name TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_students_student_index
            ON students(student_index);
        """
    )
    conn.commit()


def _ensure_subject_schema(conn):
    """Create the subject master table if it is missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            accreditation INTEGER NOT NULL,
            module TEXT NOT NULL,
            year INTEGER NOT NULL DEFAULT 1,
            UNIQUE(code, accreditation, module)
        );
        CREATE INDEX IF NOT EXISTS idx_subjects_code_accreditation_module
            ON subjects(code, accreditation, module);
        """
    )
    conn.commit()


def _ensure_semester_schema(conn):
    """Create the semester table if it is missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS semesters (
            id INTEGER PRIMARY KEY,
            academic_year_start INTEGER,
            season TEXT CHECK(season IN ('јесењи', 'пролећни')),
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            CHECK (end_date > start_date),
            UNIQUE(academic_year_start, season)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_semesters_academic_year_season
            ON semesters(academic_year_start, season);
        """
    )
    conn.commit()


def _ensure_course_subject_schema(conn):
    """Create the grouped-course to subject relation table if it is missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS course_subjects (
            course_code TEXT NOT NULL,
            subject_id INTEGER NOT NULL,
            PRIMARY KEY (course_code, subject_id),
            FOREIGN KEY (course_code) REFERENCES courses(code) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_course_subjects_course
            ON course_subjects(course_code);
        CREATE INDEX IF NOT EXISTS idx_course_subjects_subject
            ON course_subjects(subject_id);
        """
    )
    conn.commit()


def _ensure_subject_student_counts_schema(conn):
    """Create imported aggregate student counts for subjects."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS subject_student_counts (
            subject_id INTEGER NOT NULL,
            semester_id INTEGER NOT NULL,
            student_count INTEGER,
            PRIMARY KEY (subject_id, semester_id),
            CHECK (student_count IS NULL OR student_count >= 0),
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
            FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_subject_student_counts_semester
            ON subject_student_counts(semester_id, subject_id);
        """
    )
    conn.commit()


def _ensure_weekly_session_schema(conn):
    """Create the current weekly-session table and indexes if missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS weekly_sessions (
            id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL,
            meeting_no INTEGER NOT NULL DEFAULT 1,
            room_id INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
            start_slot INTEGER NOT NULL,
            end_slot INTEGER NOT NULL,
            FOREIGN KEY(session_id) REFERENCES course_sessions(id),
            FOREIGN KEY(room_id) REFERENCES rooms(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly_sessions_session_meeting
            ON weekly_sessions(session_id, meeting_no);
        CREATE INDEX IF NOT EXISTS idx_weekly_sessions_day_room_start
            ON weekly_sessions(day_of_week, room_id, start_slot);
        """
    )
    conn.commit()


def _ensure_student_enrollment_schema(conn):
    """Create the semester-scoped student enrollment table if it is missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS student_enrollments (
            id INTEGER PRIMARY KEY,
            student_username TEXT NOT NULL,
            semester_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(student_username, semester_id, subject_id),
            FOREIGN KEY(student_username) REFERENCES students(username) ON DELETE CASCADE,
            FOREIGN KEY(semester_id) REFERENCES semesters(id) ON DELETE CASCADE,
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_student_enrollments_student_semester
            ON student_enrollments(student_username, semester_id);
        CREATE INDEX IF NOT EXISTS idx_student_enrollments_semester_subject
            ON student_enrollments(semester_id, subject_id);
        """
    )
    conn.commit()


def _ensure_timetable_revision_schema(conn):
    """Create independent revisions for timetable and student enrollments."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS timetable_revisions (
            semester_id INTEGER PRIMARY KEY,
            revision INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(semester_id) REFERENCES semesters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS student_enrollment_revisions (
            student_username TEXT NOT NULL,
            semester_id INTEGER NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(student_username, semester_id),
            FOREIGN KEY(student_username) REFERENCES students(username) ON DELETE CASCADE,
            FOREIGN KEY(semester_id) REFERENCES semesters(id) ON DELETE CASCADE
        );

        CREATE TRIGGER IF NOT EXISTS trg_timetable_revision_course_session_insert
        AFTER INSERT ON course_sessions
        BEGIN
            INSERT OR IGNORE INTO timetable_revisions (semester_id) VALUES (NEW.semester_id);
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = NEW.semester_id;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_timetable_revision_course_session_update
        AFTER UPDATE ON course_sessions
        BEGIN
            INSERT OR IGNORE INTO timetable_revisions (semester_id) VALUES (OLD.semester_id);
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = OLD.semester_id;
            INSERT OR IGNORE INTO timetable_revisions (semester_id) VALUES (NEW.semester_id);
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = NEW.semester_id;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_timetable_revision_course_session_delete
        AFTER DELETE ON course_sessions
        BEGIN
            INSERT OR IGNORE INTO timetable_revisions (semester_id) VALUES (OLD.semester_id);
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = OLD.semester_id;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_timetable_revision_weekly_session_insert
        AFTER INSERT ON weekly_sessions
        BEGIN
            INSERT OR IGNORE INTO timetable_revisions (semester_id)
            SELECT semester_id FROM course_sessions WHERE id = NEW.session_id;
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = (
                SELECT semester_id FROM course_sessions WHERE id = NEW.session_id
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_timetable_revision_weekly_session_update
        AFTER UPDATE ON weekly_sessions
        BEGIN
            INSERT OR IGNORE INTO timetable_revisions (semester_id)
            SELECT semester_id FROM course_sessions WHERE id = OLD.session_id;
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = (
                SELECT semester_id FROM course_sessions WHERE id = OLD.session_id
            );
            INSERT OR IGNORE INTO timetable_revisions (semester_id)
            SELECT semester_id FROM course_sessions WHERE id = NEW.session_id;
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = (
                SELECT semester_id FROM course_sessions WHERE id = NEW.session_id
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_timetable_revision_weekly_session_delete
        AFTER DELETE ON weekly_sessions
        BEGIN
            INSERT OR IGNORE INTO timetable_revisions (semester_id)
            SELECT semester_id FROM course_sessions WHERE id = OLD.session_id;
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = (
                SELECT semester_id FROM course_sessions WHERE id = OLD.session_id
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_timetable_revision_session_group_insert
        AFTER INSERT ON session_groups
        BEGIN
            INSERT OR IGNORE INTO timetable_revisions (semester_id)
            SELECT semester_id FROM course_sessions WHERE id = NEW.session_id;
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = (
                SELECT semester_id FROM course_sessions WHERE id = NEW.session_id
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_timetable_revision_session_group_update
        AFTER UPDATE ON session_groups
        BEGIN
            INSERT OR IGNORE INTO timetable_revisions (semester_id)
            SELECT semester_id FROM course_sessions WHERE id = OLD.session_id;
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = (
                SELECT semester_id FROM course_sessions WHERE id = OLD.session_id
            );
            INSERT OR IGNORE INTO timetable_revisions (semester_id)
            SELECT semester_id FROM course_sessions WHERE id = NEW.session_id;
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = (
                SELECT semester_id FROM course_sessions WHERE id = NEW.session_id
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_timetable_revision_session_group_delete
        AFTER DELETE ON session_groups
        BEGIN
            INSERT OR IGNORE INTO timetable_revisions (semester_id)
            SELECT semester_id FROM course_sessions WHERE id = OLD.session_id;
            UPDATE timetable_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE semester_id = (
                SELECT semester_id FROM course_sessions WHERE id = OLD.session_id
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_student_enrollment_revision_insert
        AFTER INSERT ON student_enrollments
        BEGIN
            INSERT OR IGNORE INTO student_enrollment_revisions
                (student_username, semester_id)
            VALUES (NEW.student_username, NEW.semester_id);
            UPDATE student_enrollment_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE student_username = NEW.student_username
              AND semester_id = NEW.semester_id;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_student_enrollment_revision_update
        AFTER UPDATE ON student_enrollments
        BEGIN
            INSERT OR IGNORE INTO student_enrollment_revisions
                (student_username, semester_id)
            VALUES (OLD.student_username, OLD.semester_id);
            UPDATE student_enrollment_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE student_username = OLD.student_username
              AND semester_id = OLD.semester_id;
            INSERT OR IGNORE INTO student_enrollment_revisions
                (student_username, semester_id)
            VALUES (NEW.student_username, NEW.semester_id);
            UPDATE student_enrollment_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE student_username = NEW.student_username
              AND semester_id = NEW.semester_id;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_student_enrollment_revision_delete
        AFTER DELETE ON student_enrollments
        BEGIN
            INSERT OR IGNORE INTO student_enrollment_revisions
                (student_username, semester_id)
            VALUES (OLD.student_username, OLD.semester_id);
            UPDATE student_enrollment_revisions
            SET revision = revision + 1, updated_at = datetime('now')
            WHERE student_username = OLD.student_username
              AND semester_id = OLD.semester_id;
        END;
        """
    )
    # These tables contain values embedded in the timetable response.  Their
    # changes are uncommon and can affect more than one semester, so invalidate
    # every known semester rather than maintaining a more fragile dependency map.
    for table_name in (
        "courses",
        "course_subjects",
        "subjects",
        "teachers",
        "groups",
        "rooms",
        "building_locations",
    ):
        for event in ("INSERT", "UPDATE", "DELETE"):
            trigger_name = f"trg_timetable_revision_{table_name}_{event.lower()}"
            conn.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {trigger_name}
                AFTER {event} ON {table_name}
                BEGIN
                    INSERT OR IGNORE INTO timetable_revisions (semester_id)
                    SELECT id FROM semesters;
                    UPDATE timetable_revisions
                    SET revision = revision + 1, updated_at = datetime('now');
                END
                """
            )
    conn.commit()


def _ensure_calendar_revision_schema(conn):
    """Create per-semester revisions used for cheap calendar cache validation."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS calendar_revisions (
            semester_id INTEGER PRIMARY KEY,
            revision INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(semester_id) REFERENCES semesters(id) ON DELETE CASCADE
        );
        INSERT OR IGNORE INTO calendar_revisions (semester_id)
        SELECT id FROM semesters;
        """
    )
    conn.commit()


def _ensure_exam_schedule_schema(conn):
    """Create the imported exam schedule table if it is missing."""
    _ensure_building_locations_schema(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS exam_schedule (
            id INTEGER PRIMARY KEY,
            term_code TEXT NOT NULL,
            course_code TEXT NOT NULL,
            course_name TEXT NOT NULL,
            exam_date TEXT NOT NULL,
            exam_hour INTEGER NOT NULL,
            location TEXT,
            imported_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_exam_schedule_term_date_hour
            ON exam_schedule(term_code, exam_date, exam_hour);
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_exam_schedule_location_insert
        BEFORE INSERT ON exam_schedule
        WHEN NEW.location IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1
                 FROM building_locations
                 WHERE building_name = NEW.location
             )
        BEGIN
            SELECT RAISE(ABORT, 'exam_schedule.location must reference an existing building');
        END;
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_exam_schedule_location_update
        BEFORE UPDATE OF location ON exam_schedule
        WHEN NEW.location IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1
                 FROM building_locations
                 WHERE building_name = NEW.location
             )
        BEGIN
            SELECT RAISE(ABORT, 'exam_schedule.location must reference an existing building');
        END;
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_exam_schedule_term_course_code_accreditation
            ON exam_schedule(term_code, course_code)
        """
    )
    conn.commit()


def _ensure_exam_term_schema(conn):
    """Create the imported exam terms table if it is missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS exam_terms (
            term_code TEXT PRIMARY KEY,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            semester_id INTEGER NOT NULL,
            imported_at TEXT NOT NULL DEFAULT (datetime('now')),
            CHECK (end_date >= start_date),
            FOREIGN KEY(semester_id) REFERENCES semesters(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_exam_terms_semester_end_date
            ON exam_terms(semester_id, end_date DESC, term_code DESC);
        CREATE INDEX IF NOT EXISTS idx_exam_terms_end_date
            ON exam_terms(end_date DESC, term_code DESC);
        """
    )

    conn.commit()


def _ensure_oral_exam_schema(conn):
    """Create the teacher-managed oral-exam schedule table."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS oral_exam_schedule (
            id INTEGER PRIMARY KEY,
            term_code TEXT NOT NULL,
            course_session_id INTEGER NOT NULL,
            exam_date TEXT NOT NULL,
            start_hour INTEGER NOT NULL,
            end_hour INTEGER NOT NULL,
            reservation_id INTEGER,
            teacher_username TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            CHECK (start_hour >= 0 AND end_hour <= 24 AND end_hour > start_hour),
            FOREIGN KEY(term_code) REFERENCES exam_terms(term_code) ON DELETE CASCADE,
            FOREIGN KEY(course_session_id) REFERENCES course_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(reservation_id) REFERENCES reservations(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_oral_exam_schedule_term_date_hour
            ON oral_exam_schedule(term_code, exam_date, start_hour);
        CREATE INDEX IF NOT EXISTS idx_oral_exam_schedule_group
            ON oral_exam_schedule(course_session_id, term_code);
        """
    )
    conn.commit()


def _ensure_exam_application_schema(conn):
    """Create the imported exam application table if it is missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS exam_applications (
            id INTEGER PRIMARY KEY,
            term_code TEXT NOT NULL,
            subject_id INTEGER NOT NULL,
            student_username TEXT NOT NULL,
            imported_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(term_code, subject_id, student_username),
            FOREIGN KEY(student_username) REFERENCES students(username) ON DELETE CASCADE,
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_exam_applications_term_student
            ON exam_applications(term_code, student_username);
        CREATE INDEX IF NOT EXISTS idx_exam_applications_subject
            ON exam_applications(subject_id, term_code);
        """
    )
    conn.commit()


def _ensure_notification_schema(conn):
    """Create the notification tables if they are missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            source_id TEXT NOT NULL UNIQUE,
            semester_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            teacher_username TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            published_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(semester_id) REFERENCES semesters(id) ON DELETE CASCADE,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE,
            FOREIGN KEY(teacher_username) REFERENCES teachers(username) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_notifications_semester_course_published
            ON notifications(semester_id, course_id, published_at DESC);

        CREATE TABLE IF NOT EXISTS notification_targets (
            notification_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            PRIMARY KEY(notification_id, group_id),
            FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_notification_targets_group_notification
            ON notification_targets(group_id, notification_id);

        CREATE TABLE IF NOT EXISTS notification_recipients (
            notification_id INTEGER NOT NULL,
            student_username TEXT NOT NULL,
            delivered_at TEXT NOT NULL DEFAULT (datetime('now')),
            read_at TEXT,
            PRIMARY KEY(notification_id, student_username),
            FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
            FOREIGN KEY(student_username) REFERENCES students(username) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_notification_recipients_student_read
            ON notification_recipients(student_username, read_at, notification_id);

        CREATE TABLE IF NOT EXISTS import_state (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()


def _ensure_building_locations_schema(conn):
    """Create the building locations table."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS building_locations (
            building_name TEXT PRIMARY KEY,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            radius_m REAL NOT NULL CHECK(radius_m > 0)
        );
        """
    )
    conn.commit()


def _ensure_reservation_overlap_schema(conn):
    """Prevent overlapping reservations for the same room and date."""
    conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS trg_reservations_no_overlap_insert
        BEFORE INSERT ON reservations
        WHEN EXISTS (
            SELECT 1
            FROM reservations
            WHERE room_id = NEW.room_id
              AND date = NEW.date
              AND start_slot < NEW.end_slot
              AND NEW.start_slot < end_slot
        )
        BEGIN
            SELECT RAISE(ABORT, 'reservation_overlap');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_reservations_no_overlap_update
        BEFORE UPDATE OF room_id, date, start_slot, end_slot ON reservations
        WHEN EXISTS (
            SELECT 1
            FROM reservations
            WHERE id <> NEW.id
              AND room_id = NEW.room_id
              AND date = NEW.date
              AND start_slot < NEW.end_slot
              AND NEW.start_slot < end_slot
        )
        BEGIN
            SELECT RAISE(ABORT, 'reservation_overlap');
        END;
        """
    )
    conn.commit()


def _ensure_extra_schemas(conn):
    """Create the add-on tables used by attendance and Android auth."""
    _ensure_semester_schema(conn)
    _ensure_calendar_revision_schema(conn)
    _ensure_subject_schema(conn)
    _ensure_course_subject_schema(conn)
    _ensure_subject_student_counts_schema(conn)
    _ensure_weekly_session_schema(conn)
    _ensure_attendance_schema(conn)
    _ensure_mobile_auth_schema(conn)
    _ensure_mobile_device_schema(conn)
    _ensure_student_directory_schema(conn)
    _ensure_student_enrollment_schema(conn)
    _ensure_timetable_revision_schema(conn)
    _ensure_exam_schedule_schema(conn)
    _ensure_exam_term_schema(conn)
    _ensure_oral_exam_schema(conn)
    _ensure_exam_application_schema(conn)
    _ensure_notification_schema(conn)
    _ensure_building_locations_schema(conn)
    _ensure_reservation_overlap_schema(conn)


def ensure_student_directory_schema(conn):
    """Public helper used by import scripts to ensure the student directory exists."""
    _ensure_student_directory_schema(conn)


def ensure_calendar_revision_schema(conn):
    """Public helper used by standalone calendar import scripts."""
    _ensure_semester_schema(conn)
    _ensure_calendar_revision_schema(conn)


def ensure_student_enrollment_schema(conn):
    """Public helper used by import scripts to ensure student enrollments exist."""
    _ensure_student_enrollment_schema(conn)


def ensure_timetable_revision_schema(conn):
    """Public helper used by standalone import scripts."""
    _ensure_timetable_revision_schema(conn)


def ensure_exam_schedule_schema(conn):
    """Public helper used by import scripts to ensure exam schedules exist."""
    _ensure_exam_schedule_schema(conn)


def ensure_exam_term_schema(conn):
    """Public helper used by import scripts to ensure exam terms exist."""
    _ensure_exam_term_schema(conn)


def ensure_exam_application_schema(conn):
    """Public helper used by import scripts to ensure exam applications exist."""
    _ensure_exam_application_schema(conn)


def ensure_notification_schema(conn):
    """Public helper used by import scripts to ensure notifications exist."""
    _ensure_notification_schema(conn)


def ensure_mobile_device_schema(conn):
    """Public helper used by push-registration scripts."""
    _ensure_mobile_device_schema(conn)


def building_locations_for_room_building_name(building_name):
    """Return building geofences for one room location label."""
    normalized = str(building_name or "").strip()
    if not normalized:
        return []
    return [
        dict(row)
        for row in query_db(
            """
            SELECT building_name,
                   building_name AS name,
                   latitude,
                   longitude,
                   radius_m
            FROM building_locations
            WHERE building_name = ?
            ORDER BY building_name
            """,
            (normalized,),
        )
    ]


def building_locations_all():
    """Return all configured building geofences."""
    return [
        dict(row)
        for row in query_db(
            """
            SELECT building_name,
                   building_name AS name,
                   latitude,
                   longitude,
                   radius_m
            FROM building_locations
            ORDER BY building_name
            """
        )
    ]


def resolve_exam_location_to_building(cur, raw_location):
    """Resolve an imported exam location to an existing building name."""
    normalized = str(raw_location or "").strip()
    unknown_values = {
        "",
        "-",
        "?",
        "unknown",
        "n/a",
        "na",
        "n/p",
        "np",
        "tbd",
        "nepoznat",
        "nepoznata",
        "nepoznato",
        "непознат",
        "непозната",
        "непознато",
    }
    if normalized.lower() in unknown_values:
        return None

    row = cur.execute(
        """
        SELECT building_name
        FROM building_locations
        WHERE building_name = ?
        """,
        (normalized,),
    ).fetchone()
    if row is not None:
        return row[0]

    row = cur.execute(
        """
        SELECT building_name
        FROM rooms
        WHERE name = ?
           OR code = ?
           OR building_name = ?
        ORDER BY id
        LIMIT 1
        """,
        (normalized, normalized, normalized),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"Unknown exam location {normalized!r}; expected an existing building or room"
        )

    building_name = str(row[0] or "").strip()
    if not building_name:
        raise ValueError(
            f"Room {normalized!r} does not have a building name for exam location mapping"
        )

    building_row = cur.execute(
        """
        SELECT building_name
        FROM building_locations
        WHERE building_name = ?
        """,
        (building_name,),
    ).fetchone()
    if building_row is None:
        raise ValueError(
            f"Room {normalized!r} maps to building {building_name!r}, but that building is not configured"
        )
    return building_name


def _utcnow():
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def _isoformat(dt):
    """Render a UTC timestamp in ISO 8601 format."""
    return dt.astimezone(timezone.utc).isoformat()


def hash_token(token):
    """Hash an opaque bearer token before storing it in SQLite."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def init_app(app):
    """Register database teardown hooks on the Flask application."""
    app.teardown_appcontext(close_connection)


def init_db(conn=None):
    """Initialize the database from schema.sql and add attendance tables."""
    close_conn = False
    if conn is None:
        os.makedirs(os.path.dirname(_database_path()), exist_ok=True)
        conn = sqlite3.connect(_database_path(), detect_types=sqlite3.PARSE_DECLTYPES)
        close_conn = True

    try:
        if _database_has_schema(conn):
            _ensure_semester_schema(conn)
            _ensure_weekly_session_schema(conn)
            _ensure_extra_schemas(conn)
            return False

        schema_path = _schema_path()
        if not os.path.exists(schema_path):
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(schema_path, encoding="utf-8") as f:
            conn.executescript(f.read())
        _ensure_weekly_session_schema(conn)
        _ensure_extra_schemas(conn)
        conn.commit()
        return True
    finally:
        if close_conn:
            conn.close()


def get_db():
    """Return the current SQLite connection, creating one for this request if needed."""
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = _open_db_connection()
    return db


def _open_db_connection():
    """Open a SQLite connection and ensure the current schema exists."""
    db = sqlite3.connect(_database_path(), detect_types=sqlite3.PARSE_DECLTYPES)
    db.row_factory = sqlite3.Row
    # enable WAL mode for concurrent access (Gunicorn)
    db.execute("PRAGMA journal_mode=WAL;")
    # ensure foreign keys are enforced
    db.execute("PRAGMA foreign_keys = ON;")
    init_db(db)
    _ensure_extra_schemas(db)
    return db


def close_connection(exception):
    """Close the request-scoped SQLite connection at teardown."""
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    """Run a SELECT query and return either one row or all rows."""
    if has_app_context():
        cur = get_db().execute(query, args)
        rv = cur.fetchall()
        cur.close()
        return (rv[0] if rv else None) if one else rv

    conn = _open_db_connection()
    try:
        cur = conn.execute(query, args)
        rv = cur.fetchall()
        cur.close()
        return (rv[0] if rv else None) if one else rv
    finally:
        conn.close()


def execute_db(query, args=(), commit=True):
    """Run a write query and optionally commit it immediately."""
    if has_app_context():
        conn = get_db()
        cur = conn.execute(query, args)
        if commit:
            conn.commit()
        return cur.lastrowid

    conn = _open_db_connection()
    try:
        cur = conn.execute(query, args)
        if commit:
            conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def mobile_auth_get_or_create_user(radius_username):
    """Return the Android-auth user row for a RADIUS username."""
    now = _isoformat(_utcnow())
    conn = get_db()
    row = conn.execute(
        "SELECT id, radius_username FROM mobile_auth_users WHERE radius_username = ?",
        (radius_username,),
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO mobile_auth_users (radius_username, created_at) VALUES (?, ?)",
            (radius_username, now),
        )
        conn.commit()
        user_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT id, radius_username FROM mobile_auth_users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return row


def mobile_auth_get_user_by_id(user_id):
    """Return a mobile-auth user row by id."""
    return query_db(
        "SELECT id, radius_username, two_factor_enabled, two_factor_setup_code, two_factor_setup_expires_at, two_factor_link_ticket, two_factor_link_ticket_expires_at, two_factor_link_action, two_factor_last_verified_at FROM mobile_auth_users WHERE id = ?",
        (user_id,),
        one=True,
    )


def mobile_auth_get_two_factor_settings(user_id):
    """Return the stored 2FA state for one mobile-auth user."""
    return query_db(
        """
        SELECT id,
               radius_username,
               two_factor_enabled,
               two_factor_setup_code,
               two_factor_setup_expires_at,
               two_factor_link_ticket,
               two_factor_link_ticket_expires_at,
               two_factor_link_action,
               two_factor_created_at,
               two_factor_confirmed_at,
               two_factor_last_verified_at
        FROM mobile_auth_users
        WHERE id = ?
        """,
        (user_id,),
        one=True,
    )


def mobile_auth_begin_two_factor_setup(user_id, setup_code, setup_expires_at, enabled=False):
    """Store a fresh unconfirmed 2FA setup code for a mobile-auth user."""
    now = _isoformat(_utcnow())
    conn = get_db()
    conn.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_enabled = ?,
            two_factor_setup_code = ?,
            two_factor_setup_expires_at = ?,
            two_factor_link_ticket = NULL,
            two_factor_link_ticket_expires_at = NULL,
            two_factor_link_action = NULL,
            two_factor_created_at = ?,
            two_factor_confirmed_at = NULL,
            two_factor_last_verified_at = NULL
        WHERE id = ?
        """,
        (1 if enabled else 0, setup_code, setup_expires_at, now, user_id),
    )
    conn.commit()


def mobile_auth_confirm_two_factor(user_id):
    """Mark a stored 2FA setup code as active after a successful verification."""
    now = _isoformat(_utcnow())
    conn = get_db()
    conn.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_enabled = 1,
            two_factor_confirmed_at = ?,
            two_factor_last_verified_at = ?,
            two_factor_setup_code = NULL,
            two_factor_setup_expires_at = NULL,
            two_factor_link_ticket = NULL,
            two_factor_link_ticket_expires_at = NULL,
            two_factor_link_action = NULL
        WHERE id = ?
        """,
        (now, now, user_id),
    )
    conn.commit()


def mobile_auth_mark_two_factor_verified(user_id):
    """Record the latest successful 2FA verification timestamp for a user."""
    now = _isoformat(_utcnow())
    conn = get_db()
    conn.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_last_verified_at = ?
        WHERE id = ?
        """,
        (now, user_id),
    )
    conn.commit()


def mobile_auth_clear_two_factor_verification(user_id):
    """Clear the current 2FA trust window for one mobile-auth user."""
    conn = get_db()
    conn.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_last_verified_at = NULL
        WHERE id = ?
        """,
        (user_id,),
    )
    conn.commit()


def mobile_auth_disable_two_factor(user_id):
    """Disable 2FA requirements for one mobile-auth user."""
    conn = get_db()
    conn.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_enabled = 0,
            two_factor_last_verified_at = NULL,
            two_factor_setup_code = NULL,
            two_factor_setup_expires_at = NULL,
            two_factor_link_ticket = NULL,
            two_factor_link_ticket_expires_at = NULL,
            two_factor_link_action = NULL
        WHERE id = ?
        """,
        (user_id,),
    )
    conn.commit()


def mobile_auth_clear_two_factor_setup(user_id):
    """Clear any stored 2FA setup for one mobile-auth user."""
    conn = get_db()
    conn.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_enabled = 0,
            two_factor_setup_code = NULL,
            two_factor_setup_expires_at = NULL,
            two_factor_link_ticket = NULL,
            two_factor_link_ticket_expires_at = NULL,
            two_factor_link_action = NULL,
            two_factor_confirmed_at = NULL,
            two_factor_last_verified_at = NULL
        WHERE id = ?
        """,
        (user_id,),
    )
    conn.commit()


def mobile_auth_set_two_factor_link_ticket(user_id, link_ticket, link_ticket_expires_at, link_action):
    """Persist the current link-based 2FA ticket for a user."""
    conn = get_db()
    conn.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_link_ticket = ?,
            two_factor_link_ticket_expires_at = ?,
            two_factor_link_action = ?
        WHERE id = ?
        """,
        (link_ticket, link_ticket_expires_at, link_action, user_id),
    )
    conn.commit()


def mobile_auth_clear_two_factor_link_ticket(user_id):
    """Clear any stored link-based 2FA ticket for one user."""
    conn = get_db()
    conn.execute(
        """
        UPDATE mobile_auth_users
        SET two_factor_link_ticket = NULL,
            two_factor_link_ticket_expires_at = NULL,
            two_factor_link_action = NULL
        WHERE id = ?
        """,
        (user_id,),
    )
    conn.commit()


def mobile_auth_get_user_by_two_factor_link_ticket(link_ticket):
    """Return the mobile-auth user row for one active link ticket."""
    return query_db(
        """
        SELECT id,
               radius_username,
               two_factor_enabled,
               two_factor_setup_code,
               two_factor_setup_expires_at,
               two_factor_link_ticket,
               two_factor_link_ticket_expires_at,
               two_factor_link_action,
               two_factor_created_at,
               two_factor_confirmed_at,
               two_factor_last_verified_at
        FROM mobile_auth_users
        WHERE two_factor_link_ticket = ?
        """,
        (link_ticket,),
        one=True,
    )


def mobile_auth_get_device_login_policy(device_id):
    """Return the latest username recorded for a device."""
    return query_db(
        """
        SELECT device_id, last_username, last_login_date, updated_at
        FROM mobile_auth_device_login_policies
        WHERE device_id = ?
        """,
        (device_id,),
        one=True,
    )


def mobile_auth_assert_device_login_allowed(device_id, username):
    """Reject a different username on the same device within one UTC day."""
    policy = mobile_auth_get_device_login_policy(device_id)
    if policy is None:
        return

    current_day = _utcnow().date().isoformat()
    if policy["last_login_date"] == current_day and policy["last_username"] != username.strip():
        raise RuntimeError(
            f'This phone is already used by "{policy["last_username"]}" today. Try again tomorrow.'
        )


def mobile_auth_record_device_login(device_id, username):
    """Persist the username that last logged in from a device."""
    now = _isoformat(_utcnow())
    current_day = _utcnow().date().isoformat()
    conn = get_db()
    conn.execute(
        """
        INSERT INTO mobile_auth_device_login_policies (
            device_id, last_username, last_login_date, updated_at
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            last_username = excluded.last_username,
            last_login_date = excluded.last_login_date,
            updated_at = excluded.updated_at
        """,
        (device_id, username.strip(), current_day, now),
    )
    conn.commit()
    return mobile_auth_get_device_login_policy(device_id)


def mobile_auth_revoke_active_sessions(user_id, reason, exclude_session_id=None):
    """Revoke all active Android sessions for a user."""
    now = _isoformat(_utcnow())
    sql = """
        UPDATE mobile_auth_sessions
        SET revoked_at = ?, revoked_reason = ?
        WHERE user_id = ?
          AND revoked_at IS NULL
          AND expires_at > ?
    """
    params = [now, reason, user_id, now]
    if exclude_session_id is not None:
        sql += " AND id != ?"
        params.append(exclude_session_id)
    conn = get_db()
    cur = conn.execute(sql, params)
    conn.commit()
    return int(cur.rowcount)


def mobile_auth_create_session(user_id, device_id, device_name, token_hash, session_days):
    """Create a new Android session and return the stored row."""
    now = _utcnow()
    created_at = _isoformat(now)
    expires_at = _isoformat(now + timedelta(days=session_days))
    conn = get_db()
    cur = conn.execute(
        """
        INSERT INTO mobile_auth_sessions (
            user_id, device_id, device_name, token_hash,
            created_at, last_seen_at, last_seen_ip, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, device_id, device_name, token_hash, created_at, created_at, None, expires_at),
    )
    conn.commit()
    return mobile_auth_get_session_by_id(int(cur.lastrowid))


def mobile_auth_touch_session(session_id, last_seen_ip=None):
    """Refresh the last-seen timestamp for an Android session."""
    conn = get_db()
    conn.execute(
        "UPDATE mobile_auth_sessions SET last_seen_at = ?, last_seen_ip = ? WHERE id = ?",
        (_isoformat(_utcnow()), last_seen_ip, session_id),
    )
    conn.commit()
    return mobile_auth_get_session_by_id(session_id)


def mobile_auth_revoke_session(session_id, reason):
    """Mark an Android session as revoked."""
    conn = get_db()
    conn.execute(
        "UPDATE mobile_auth_sessions SET revoked_at = ?, revoked_reason = ? WHERE id = ?",
        (_isoformat(_utcnow()), reason, session_id),
    )
    conn.commit()


def mobile_auth_get_session_by_token(token):
    """Find an Android session by its raw bearer token."""
    token_hash = hash_token(token)
    return query_db(
        "SELECT * FROM mobile_auth_sessions WHERE token_hash = ?",
        (token_hash,),
        one=True,
    )


def mobile_auth_get_session_by_id(session_id):
    """Find an Android session by id."""
    return query_db(
        "SELECT * FROM mobile_auth_sessions WHERE id = ?",
        (session_id,),
        one=True,
    )


def mobile_device_upsert(student_username, device_id, device_name, installation_id, platform="android"):
    """Store or update one mobile registration id for a student device."""
    now = _isoformat(_utcnow())
    conn = get_db()
    conn.execute(
        "DELETE FROM mobile_devices WHERE installation_id = ? AND device_id != ?",
        (installation_id, device_id),
    )
    conn.execute(
        """
        INSERT INTO mobile_devices (
            device_id, student_username, device_name, platform, installation_id,
            enabled, last_seen_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            student_username = excluded.student_username,
            device_name = excluded.device_name,
            platform = excluded.platform,
            installation_id = excluded.installation_id,
            enabled = 1,
            last_seen_at = excluded.last_seen_at,
            updated_at = excluded.updated_at
        """,
        (device_id, student_username, device_name, platform, installation_id, now, now),
    )
    conn.commit()
    return query_db(
        """
        SELECT device_id,
               student_username,
               device_name,
               platform,
               installation_id,
               enabled,
               last_seen_at,
               updated_at
        FROM mobile_devices
        WHERE device_id = ?
        """,
        (device_id,),
        one=True,
    )


def mobile_device_delete(device_id):
    """Remove the stored mobile registration for one device."""
    conn = get_db()
    conn.execute("DELETE FROM mobile_devices WHERE device_id = ?", (device_id,))
    conn.commit()


def mobile_device_by_device_id(device_id):
    """Return one stored mobile registration row by device id."""
    return query_db(
        """
        SELECT device_id,
               student_username,
               device_name,
               platform,
               installation_id,
               enabled,
               last_seen_at,
               updated_at
        FROM mobile_devices
        WHERE device_id = ?
        """,
        (device_id,),
        one=True,
    )


def mobile_device_tokens_for_student(student_username):
    """Return enabled registrations for one student."""
    return query_db(
        """
        SELECT device_id,
               student_username,
               device_name,
               platform,
               installation_id,
               last_seen_at,
               updated_at
        FROM mobile_devices
        WHERE student_username = ?
          AND enabled = 1
        ORDER BY updated_at DESC, device_id
        """,
        (student_username,),
    )


def mobile_device_tokens_for_students(student_usernames):
    """Return enabled registrations for multiple students."""
    usernames = [str(username).strip() for username in student_usernames if str(username).strip()]
    if not usernames:
        return []
    placeholders = ", ".join("?" for _ in usernames)
    return query_db(
        f"""
        SELECT device_id,
               student_username,
               device_name,
               platform,
               installation_id,
               last_seen_at,
               updated_at
        FROM mobile_devices
        WHERE student_username IN ({placeholders})
          AND enabled = 1
        ORDER BY updated_at DESC, device_id
        """,
        tuple(usernames),
    )


def student_identity_for_username(username):
    """Return the stored student identity for one username or a fallback label."""
    row = query_db(
        """
        SELECT username, student_index, surname, given_name
        FROM students
        WHERE username = ?
        """,
        (username,),
        one=True,
    )
    if not row:
        return {
            "username": username,
            "student_index": None,
            "student_name": None,
            "student_label": "Непознато",
        }

    given_name = (row["given_name"] or "").strip()
    surname = (row["surname"] or "").strip()
    full_name = " ".join(part for part in (given_name, surname) if part).strip()
    student_index = (row["student_index"] or "").strip()
    student_label = "Непознато"
    if full_name and student_index:
        student_label = f"{full_name} ({student_index})"
    elif full_name:
        student_label = full_name
    elif student_index:
        student_label = student_index

    return {
        "username": row["username"],
        "student_index": student_index or None,
        "student_name": full_name or None,
        "student_label": student_label,
    }


def student_enrollment_upsert(student_username, semester_id, subject_id, group_id):
    """Store one semester-scoped course enrollment for a student."""
    now = _isoformat(_utcnow())
    conn = get_db()
    conn.execute(
        """
        INSERT INTO student_enrollments (
            student_username, semester_id, subject_id, group_id, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(student_username, semester_id, subject_id) DO UPDATE SET
            group_id = excluded.group_id,
            updated_at = excluded.updated_at
        """,
        (student_username, semester_id, subject_id, group_id, now),
    )
    conn.commit()


def student_enrollments_for_student(student_username, semester_id=None):
    """Return the enrollments stored for one student, optionally filtered by semester."""
    if semester_id is None:
        return query_db(
            """
            SELECT se.id,
                   se.student_username,
                   se.semester_id,
                   c.id AS course_id,
                   se.subject_id,
                   se.group_id,
                   se.updated_at,
                   s.name AS course_name,
                   c.code AS course_code,
                   g.name AS group_name
            FROM student_enrollments se
            JOIN subjects s ON s.id = se.subject_id
            LEFT JOIN course_subjects csub ON csub.subject_id = s.id
            LEFT JOIN courses c ON c.code = csub.course_code
            JOIN groups g ON g.id = se.group_id
            WHERE se.student_username = ?
            ORDER BY se.semester_id, c.code, se.id
            """,
            (student_username,),
        )

    return query_db(
        """
        SELECT se.id,
               se.student_username,
               se.semester_id,
               c.id AS course_id,
               se.subject_id,
               se.group_id,
               se.updated_at,
               s.name AS course_name,
               c.code AS course_code,
               g.name AS group_name
        FROM student_enrollments se
        JOIN subjects s ON s.id = se.subject_id
        LEFT JOIN course_subjects csub ON csub.subject_id = s.id
        LEFT JOIN courses c ON c.code = csub.course_code
        JOIN groups g ON g.id = se.group_id
        WHERE se.student_username = ? AND se.semester_id = ?
        ORDER BY c.code, se.id
        """,
        (student_username, semester_id),
    )


def timetable_revision_for_semester(semester_id):
    """Return the cheap revision number for one semester's timetable."""
    row = query_db(
        "SELECT revision FROM timetable_revisions WHERE semester_id = ?",
        (semester_id,),
        one=True,
    )
    return int(row["revision"]) if row else 0


def student_enrollment_revision(student_username, semester_id):
    """Return the revision number for one student's semester enrollments."""
    row = query_db(
        """
        SELECT revision
        FROM student_enrollment_revisions
        WHERE student_username = ? AND semester_id = ?
        """,
        (student_username, semester_id),
        one=True,
    )
    return int(row["revision"]) if row else 0


def student_timetable_events_for_student(student_username, semester_id):
    """Return weekly timetable events for one student in one semester."""
    return query_db(
        """
        SELECT DISTINCT se.student_username,
               se.semester_id,
               c.id AS course_id,
               c.code AS course_code,
               s.name AS course_name,
               se.subject_id,
               se.group_id,
               g.name AS group_name,
               cs.id AS course_session_id,
               cs.type AS course_type,
               t.username AS teacher_username,
               t.name AS teacher_name,
               ws.id AS weekly_session_id,
               ws.room_id,
               r.name AS room_name,
               r.code AS room_code,
               r.building_name AS room_building_name,
               bl.latitude AS room_latitude,
               bl.longitude AS room_longitude,
               ws.day_of_week,
               ws.start_slot,
               ws.end_slot
        FROM student_enrollments se
        JOIN subjects s ON s.id = se.subject_id
        JOIN course_subjects csub ON csub.subject_id = s.id
        JOIN courses c ON c.code = csub.course_code
        JOIN groups g ON g.id = se.group_id
        JOIN course_sessions cs
          ON cs.course_id = c.id
         AND cs.semester_id = se.semester_id
        JOIN session_groups sg
          ON sg.session_id = cs.id
         AND sg.group_id = se.group_id
        JOIN teachers t ON t.id = cs.teacher_id
        JOIN weekly_sessions ws ON ws.session_id = cs.id
        JOIN rooms r ON r.id = ws.room_id
        LEFT JOIN building_locations bl ON bl.building_name = r.building_name
        WHERE se.student_username = ?
          AND se.semester_id = ?
        ORDER BY c.code, cs.type, ws.day_of_week, ws.start_slot, ws.id
        """,
        (student_username, semester_id),
    )


def _normalize_exam_match_value(value):
    """Normalize exam schedule values for tolerant matching."""
    normalized = re.sub(r"[^0-9A-Za-zА-Яа-яЉЊЋЂŽžčćšđ]+", "", str(value or "").strip().lower())
    return normalized


def student_exam_schedule_for_student(student_username, term_code=None, mode="applied"):
    """Return exam schedule entries relevant for one student."""
    params = []
    if mode == "all_subjects":
        where_clause = "WHERE se.student_username = ?"
        params.append(student_username)
        if term_code is not None:
            where_clause += " AND e.term_code = ?"
            params.append(term_code)
        rows = query_db(
            f"""
            SELECT DISTINCT e.term_code,
                   e.course_code AS course_code,
                   s.id AS subject_id,
                   s.name AS subject_name,
                   e.exam_date,
                   e.exam_hour,
                   CASE
                       WHEN EXISTS (
                           SELECT 1
                           FROM exam_applications a
                           WHERE a.student_username = se.student_username
                             AND a.term_code = e.term_code
                             AND a.subject_id = se.subject_id
                       ) THEN 1
                       ELSE 0
                   END AS is_applied,
                   COALESCE(bl_room.building_name, bl_direct.building_name, r.building_name, e.location) AS location,
                   COALESCE(bl_room.latitude, bl_direct.latitude) AS location_latitude,
                   COALESCE(bl_room.longitude, bl_direct.longitude) AS location_longitude,
                   CASE
                       WHEN bl_room.building_name IS NOT NULL OR bl_direct.building_name IS NOT NULL THEN 1
                       ELSE 0
                   END AS location_is_building
            FROM student_enrollments se
            JOIN exam_terms et
              ON et.semester_id = se.semester_id
            JOIN course_subjects csub
              ON csub.subject_id = se.subject_id
            JOIN subjects s
              ON s.id = se.subject_id
            JOIN courses c
              ON c.code = csub.course_code
            JOIN exam_schedule e
              ON e.term_code = et.term_code
             AND e.course_code = c.code
            LEFT JOIN rooms r
              ON r.name = e.location OR r.code = e.location
            LEFT JOIN building_locations bl_room
              ON bl_room.building_name = r.building_name
            LEFT JOIN building_locations bl_direct
              ON bl_direct.building_name = e.location
            {where_clause}
            ORDER BY e.exam_date, e.exam_hour, e.term_code, e.course_code, e.id
            """,
            params,
        )
    else:
        where_clause = "WHERE a.student_username = ?"
        params.append(student_username)
        if term_code is not None:
            where_clause += " AND a.term_code = ?"
            params.append(term_code)

        rows = query_db(
            f"""
            SELECT DISTINCT e.term_code,
                   e.course_code AS course_code,
                   s.id AS subject_id,
                   s.name AS subject_name,
                   e.exam_date,
                   e.exam_hour,
                   1 AS is_applied,
                   COALESCE(bl_room.building_name, bl_direct.building_name, r.building_name, e.location) AS location,
                   COALESCE(bl_room.latitude, bl_direct.latitude) AS location_latitude,
                   COALESCE(bl_room.longitude, bl_direct.longitude) AS location_longitude,
                   CASE
                       WHEN bl_room.building_name IS NOT NULL OR bl_direct.building_name IS NOT NULL THEN 1
                       ELSE 0
                   END AS location_is_building
            FROM exam_applications a
            JOIN exam_schedule e
              ON e.term_code = a.term_code
            JOIN subjects s
              ON s.id = a.subject_id
            LEFT JOIN rooms r
              ON r.name = e.location OR r.code = e.location
            LEFT JOIN building_locations bl_room
              ON bl_room.building_name = r.building_name
            LEFT JOIN building_locations bl_direct
              ON bl_direct.building_name = e.location
            {where_clause}
              AND EXISTS (
                  SELECT 1
                  FROM student_enrollments se
                  JOIN course_subjects csub ON csub.subject_id = s.id
                  JOIN courses c ON c.code = csub.course_code
                  JOIN exam_terms et ON et.term_code = a.term_code
                  WHERE se.student_username = a.student_username
                    AND se.semester_id = et.semester_id
                    AND se.subject_id = a.subject_id
                    AND c.code = e.course_code
              )
            ORDER BY e.exam_date, e.exam_hour, e.term_code, e.course_code, e.id
            """,
            params,
        )

    matches = []
    for row in rows:
        matches.append(dict(row))

    return matches


def student_oral_exam_schedule_for_student(student_username, term_code=None, mode="applied"):
    """Return oral exams scheduled for course sessions attended by a student."""
    params = [student_username]
    term_clause = ""
    if term_code is not None:
        term_clause = " AND oes.term_code = ?"
        params.append(term_code)
    application_clause = ""
    if mode == "applied":
        application_clause = """
          AND EXISTS (
              SELECT 1
              FROM exam_applications ea
              WHERE ea.student_username = se.student_username
                AND ea.term_code = oes.term_code
                AND ea.subject_id = se.subject_id
          )
        """

    rows = query_db(
        f"""
        SELECT DISTINCT oes.id AS oral_exam_id,
               oes.term_code,
               c.code AS course_code,
               c.name AS course_name,
               oes.exam_date,
               oes.start_hour,
               oes.end_hour,
               r.name AS location,
               r.building_name AS location_building_name
        FROM oral_exam_schedule oes
        JOIN exam_terms et
          ON et.term_code = oes.term_code
        JOIN course_sessions cs
          ON cs.id = oes.course_session_id
         AND cs.semester_id = et.semester_id
        JOIN courses c
          ON c.id = cs.course_id
        JOIN session_groups sg
          ON sg.session_id = cs.id
        JOIN student_enrollments se
          ON se.group_id = sg.group_id
         AND se.semester_id = cs.semester_id
         AND se.student_username = ?
        JOIN course_subjects csub
          ON csub.course_code = c.code
         AND csub.subject_id = se.subject_id
        LEFT JOIN reservations res
          ON res.id = oes.reservation_id
        LEFT JOIN rooms r
          ON r.id = res.room_id
        WHERE 1 = 1
        {term_clause}
        {application_clause}
        ORDER BY oes.exam_date, oes.start_hour, c.name, oes.id
        """,
        params,
    )
    return [dict(row) for row in rows]


def exam_terms_all(semester_id=None):
    """Return available exam terms sorted newest first."""
    params = []
    semester_clause = ""
    if semester_id is not None:
        semester_clause = "WHERE semester_id = ?"
        params.append(semester_id)
    return [
        dict(row)
        for row in query_db(
            """
            SELECT term_code, start_date, end_date, semester_id, imported_at
            FROM exam_terms
            {semester_clause}
            ORDER BY end_date DESC, term_code DESC
            """.format(semester_clause=semester_clause),
            params,
        )
    ]


def student_notifications_for_student(student_username, semester_id=None, limit=50, offset=0):
    """Return notifications for one student, optionally filtered by semester."""
    limit = max(1, min(int(limit or 50), 100))
    offset = max(0, int(offset or 0))
    params = [student_username]
    semester_clause = ""
    if semester_id is not None:
        semester_clause = " AND n.semester_id = ?"
        params.append(semester_id)
    params.extend([limit, offset])
    return query_db(
        f"""
        SELECT n.id AS notification_id,
               n.source_id,
               n.semester_id,
               n.course_id,
               c.code AS course_code,
               c.name AS course_name,
               n.teacher_username,
               t.name AS teacher_name,
               n.title,
               n.body,
               n.published_at,
               n.updated_at,
               r.delivered_at,
               r.read_at,
               group_concat(DISTINCT g.name) AS target_group_names
        FROM notification_recipients r
        JOIN notifications n ON n.id = r.notification_id
        LEFT JOIN courses c ON c.id = n.course_id
        LEFT JOIN teachers t ON t.username = n.teacher_username
        LEFT JOIN notification_targets nt ON nt.notification_id = n.id
        LEFT JOIN groups g ON g.id = nt.group_id
        WHERE r.student_username = ?{semester_clause}
        GROUP BY n.id
        ORDER BY n.published_at DESC, n.id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )


def student_notifications_unread_count(student_username, semester_id=None):
    """Return the unread notification count for one student."""
    params = [student_username]
    semester_clause = ""
    if semester_id is not None:
        semester_clause = " AND n.semester_id = ?"
        params.append(semester_id)
    row = query_db(
        f"""
        SELECT COUNT(*) AS unread_count
        FROM notification_recipients r
        JOIN notifications n ON n.id = r.notification_id
        WHERE r.student_username = ?
          AND r.read_at IS NULL{semester_clause}
        """,
        tuple(params),
        one=True,
    )
    return int(row["unread_count"]) if row else 0


def student_notification_mark_read(student_username, notification_id):
    """Mark one notification as read for one student and return the stored row."""
    now = _isoformat(_utcnow())
    conn = get_db()
    conn.execute(
        """
        UPDATE notification_recipients
        SET read_at = COALESCE(read_at, ?)
        WHERE student_username = ? AND notification_id = ?
        """,
        (now, student_username, notification_id),
    )
    conn.commit()
    return query_db(
        """
        SELECT notification_id, student_username, delivered_at, read_at
        FROM notification_recipients
        WHERE student_username = ? AND notification_id = ?
        """,
        (student_username, notification_id),
        one=True,
    )


def student_notification_delete(student_username, notification_id):
    """Delete one notification from one student's inbox."""
    conn = get_db()
    row = conn.execute(
        """
        SELECT 1
        FROM notification_recipients
        WHERE student_username = ? AND notification_id = ?
        """,
        (student_username, notification_id),
    ).fetchone()
    if row is None:
        return None

    conn.execute(
        """
        DELETE FROM notification_recipients
        WHERE student_username = ? AND notification_id = ?
        """,
        (student_username, notification_id),
    )
    conn.commit()
    return {"notification_id": notification_id, "student_username": student_username}


def student_notifications_mark_all_read(student_username, semester_id=None):
    """Mark all unread notifications for one student as read."""
    now = _isoformat(_utcnow())
    conn = get_db()
    if semester_id is None:
        cur = conn.execute(
            """
            UPDATE notification_recipients
            SET read_at = COALESCE(read_at, ?)
            WHERE student_username = ?
              AND read_at IS NULL
            """,
            (now, student_username),
        )
    else:
        cur = conn.execute(
            """
            UPDATE notification_recipients
            SET read_at = COALESCE(read_at, ?)
            WHERE student_username = ?
              AND read_at IS NULL
              AND notification_id IN (
                  SELECT id
                  FROM notifications
                  WHERE semester_id = ?
              )
            """,
            (now, student_username, semester_id),
        )
    conn.commit()
    return cur.rowcount
