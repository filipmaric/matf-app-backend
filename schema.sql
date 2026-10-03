-- Copyright (c) 2026 Filip Marić. See LICENCE.
CREATE TABLE groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    study_program TEXT,
    module TEXT,
    accreditation INTEGER,
    study_year INTEGER
);

CREATE TABLE days (
    date TEXT PRIMARY KEY, -- ISO YYYY-MM-DD
    kind TEXT NOT NULL DEFAULT 'non_working'
        CHECK(kind IN ('teaching', 'makeup', 'exam', 'colloquium', 'non_working')),
    week_day INTEGER NOT NULL DEFAULT -1 -- podrazumevano se gleda stvarni dan, a makeup može zadati drugi raspored
);

CREATE TABLE calendar_revisions (
    semester_id INTEGER PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE CASCADE
);

CREATE TABLE reservations (
    id INTEGER PRIMARY KEY,
    room_id INTEGER NOT NULL,
    username INTEGER,
    date TEXT NOT NULL, -- YYYY-MM-DD
    start_slot INTEGER NOT NULL CHECK(start_slot >= 0),
    end_slot INTEGER NOT NULL CHECK(end_slot > start_slot),
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE RESTRICT
);

CREATE TABLE administrators (
    username TEXT PRIMARY KEY
);

CREATE INDEX idx_reservations_room_date ON reservations(room_id, date, start_slot);
CREATE INDEX idx_reservations_date ON reservations(date);

CREATE TRIGGER trg_reservations_no_overlap_insert
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

CREATE TRIGGER trg_reservations_no_overlap_update
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

CREATE TABLE semesters (
    id INTEGER PRIMARY KEY,
    academic_year_start INTEGER,
    season TEXT CHECK(season IN ('јесењи', 'пролећни')),
    start_date TEXT NOT NULL, -- ISO YYYY-MM-DD
    end_date TEXT NOT NULL,
    CHECK (end_date > start_date),
    UNIQUE(academic_year_start, season)
);

CREATE TABLE teachers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    username TEXT UNIQUE
);

CREATE TABLE courses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT,
    semester INTEGER NOT NULL DEFAULT 2,
    requires_computers INTEGER NOT NULL DEFAULT 0 CHECK(requires_computers IN (0, 1)),
    UNIQUE(name, code),
    UNIQUE(code)
);

CREATE TABLE subjects (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    accreditation INTEGER NOT NULL,
    module TEXT NOT NULL,
    year INTEGER NOT NULL DEFAULT 1,
    UNIQUE(code, accreditation, module)
);

CREATE INDEX idx_subjects_code_accreditation_module
    ON subjects(code, accreditation, module);

CREATE TABLE course_subjects (
    course_code TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    PRIMARY KEY (course_code, subject_id),
    FOREIGN KEY (course_code) REFERENCES courses(code) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE INDEX idx_course_subjects_course
    ON course_subjects(course_code);
CREATE INDEX idx_course_subjects_subject
    ON course_subjects(subject_id);

CREATE TABLE subject_student_counts (
    subject_id INTEGER NOT NULL,
    semester_id INTEGER NOT NULL,
    student_count INTEGER,
    PRIMARY KEY (subject_id, semester_id),
    CHECK (student_count IS NULL OR student_count >= 0),
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE CASCADE
);

CREATE INDEX idx_subject_student_counts_semester
    ON subject_student_counts(semester_id, subject_id);

CREATE TABLE course_sessions (
    id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL,
    teacher_id INTEGER NOT NULL,
    semester_id INTEGER NOT NULL,
    type TEXT NOT NULL, -- p / v / l
    weekly_lessons REAL NOT NULL DEFAULT 0,
    FOREIGN KEY(course_id) REFERENCES courses(id),
    FOREIGN KEY(teacher_id) REFERENCES teachers(id),
    FOREIGN KEY(semester_id) REFERENCES semesters(id)
);

CREATE TABLE session_groups (
    session_id INTEGER,
    group_id INTEGER,
    PRIMARY KEY(session_id, group_id),
    FOREIGN KEY(session_id) REFERENCES course_sessions(id),
    FOREIGN KEY(group_id) REFERENCES groups(id)
);

CREATE TABLE weekly_sessions (
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
CREATE UNIQUE INDEX idx_weekly_sessions_session_meeting
    ON weekly_sessions(session_id, meeting_no);

CREATE TABLE rooms (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    capacity INTEGER DEFAULT 0,
    type TEXT,
    building_name TEXT NOT NULL,
    code TEXT UNIQUE,
    priority INTEGER DEFAULT (100)
);

CREATE TABLE building_locations (
    building_name TEXT PRIMARY KEY,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    radius_m REAL NOT NULL CHECK(radius_m > 0)
);

CREATE TABLE weekly_cancellations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weekly_session_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    username TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(weekly_session_id, date),
    FOREIGN KEY (weekly_session_id) REFERENCES weekly_sessions(id) ON DELETE CASCADE
);

CREATE TABLE attendance_records (
    id INTEGER PRIMARY KEY,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
    event_id INTEGER NOT NULL,
    event_date TEXT NOT NULL,
    username TEXT NOT NULL,
    registration_source TEXT NOT NULL DEFAULT 'web' CHECK(registration_source IN ('web', 'android')),
    client_ip TEXT,
    geofence_checked INTEGER NOT NULL DEFAULT 0 CHECK(geofence_checked IN (0, 1)),
    failed_attempts_before_success INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(event_kind, event_id, event_date, username)
);

CREATE INDEX idx_attendance_records_event ON attendance_records(event_kind, event_id, event_date);
CREATE INDEX idx_attendance_records_username_event ON attendance_records(username, event_kind, event_id, event_date);

CREATE TABLE attendance_attempt_geofence_settings (
    event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
    event_id INTEGER NOT NULL,
    event_date TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    PRIMARY KEY(event_kind, event_id, event_date)
);

CREATE TABLE attendance_guest_registration_settings (
    event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
    event_id INTEGER NOT NULL,
    event_date TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
    PRIMARY KEY(event_kind, event_id, event_date)
);

CREATE TABLE attendance_guest_devices (
    device_token_hash TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
    event_id INTEGER NOT NULL,
    event_date TEXT NOT NULL,
    username TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY(device_token_hash, event_kind, event_id, event_date)
);

CREATE INDEX idx_attendance_guest_devices_event
    ON attendance_guest_devices(event_kind, event_id, event_date);

CREATE TABLE attendance_session_settings (
    event_kind TEXT NOT NULL CHECK(event_kind IN ('weekly', 'reservation')),
    event_id INTEGER NOT NULL,
    event_date TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY(event_kind, event_id, event_date)
);

CREATE TABLE attendance_attempt_failures (
    attempt_token TEXT PRIMARY KEY,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE attendance_spot_check_flags (
    attendance_record_id INTEGER PRIMARY KEY,
    teacher_username TEXT NOT NULL,
    flagged_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(attendance_record_id) REFERENCES attendance_records(id) ON DELETE CASCADE
);

CREATE INDEX idx_weekly_sessions_day_room_start ON weekly_sessions(day_of_week, room_id, start_slot);

CREATE TABLE students (
    username TEXT PRIMARY KEY,
    student_index TEXT NOT NULL,
    surname TEXT NOT NULL,
    given_name TEXT NOT NULL
);

CREATE INDEX idx_students_student_index ON students(student_index);

CREATE TABLE student_enrollments (
    id INTEGER PRIMARY KEY,
    student_username TEXT NOT NULL,
    semester_id INTEGER NOT NULL,
    subject_id INTEGER,
    group_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_username, semester_id, subject_id),
    FOREIGN KEY (student_username) REFERENCES students(username) ON DELETE CASCADE,
    FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
);

CREATE INDEX idx_student_enrollments_student_semester
    ON student_enrollments(student_username, semester_id);
CREATE INDEX idx_student_enrollments_semester_subject
    ON student_enrollments(semester_id, subject_id);

CREATE TABLE exam_schedule (
    id INTEGER PRIMARY KEY,
    term_code TEXT NOT NULL,
    course_code TEXT NOT NULL,
    course_name TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    exam_hour INTEGER NOT NULL,
    location TEXT,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(location) REFERENCES building_locations(building_name)
);
CREATE UNIQUE INDEX idx_exam_schedule_term_course_code_accreditation
    ON exam_schedule(term_code, course_code);
CREATE INDEX idx_exam_schedule_term_date_hour
    ON exam_schedule(term_code, exam_date, exam_hour);

CREATE TABLE exam_terms (
    term_code TEXT PRIMARY KEY,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    semester_id INTEGER NOT NULL,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (end_date >= start_date),
    FOREIGN KEY(semester_id) REFERENCES semesters(id) ON DELETE RESTRICT
);

CREATE INDEX idx_exam_terms_semester_end_date
    ON exam_terms(semester_id, end_date DESC, term_code DESC);
CREATE INDEX idx_exam_terms_end_date
    ON exam_terms(end_date DESC, term_code DESC);

CREATE TABLE oral_exam_schedule (
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
CREATE INDEX idx_oral_exam_schedule_term_date_hour
    ON oral_exam_schedule(term_code, exam_date, start_hour);
CREATE INDEX idx_oral_exam_schedule_group
    ON oral_exam_schedule(course_session_id, term_code);

CREATE TABLE exam_applications (
    id INTEGER PRIMARY KEY,
    term_code TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    student_username TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(term_code, subject_id, student_username),
    FOREIGN KEY(student_username) REFERENCES students(username) ON DELETE CASCADE,
    FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE INDEX idx_exam_applications_term_student
    ON exam_applications(term_code, student_username);
CREATE INDEX idx_exam_applications_subject
    ON exam_applications(subject_id, term_code);

CREATE TABLE notifications (
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
CREATE INDEX idx_notifications_semester_course_published
    ON notifications(semester_id, course_id, published_at DESC);

CREATE TABLE notification_targets (
    notification_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    PRIMARY KEY(notification_id, group_id),
    FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
    FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
);
CREATE INDEX idx_notification_targets_group_notification
    ON notification_targets(group_id, notification_id);

CREATE TABLE notification_recipients (
    notification_id INTEGER NOT NULL,
    student_username TEXT NOT NULL,
    delivered_at TEXT NOT NULL DEFAULT (datetime('now')),
    read_at TEXT,
    PRIMARY KEY(notification_id, student_username),
    FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
    FOREIGN KEY(student_username) REFERENCES students(username) ON DELETE CASCADE
);
CREATE INDEX idx_notification_recipients_student_read
    ON notification_recipients(student_username, read_at, notification_id);

CREATE TABLE import_state (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE mobile_auth_users (
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

CREATE TABLE mobile_auth_sessions (
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

CREATE INDEX idx_mobile_auth_sessions_user_id ON mobile_auth_sessions(user_id);
CREATE INDEX idx_mobile_auth_sessions_token_hash ON mobile_auth_sessions(token_hash);

CREATE TABLE mobile_auth_device_login_policies (
    device_id TEXT PRIMARY KEY,
    last_username TEXT NOT NULL,
    last_login_date TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_mobile_auth_device_login_policies_login_date ON mobile_auth_device_login_policies(last_login_date);

CREATE TABLE mobile_devices (
    device_id TEXT PRIMARY KEY,
    student_username TEXT NOT NULL,
    device_name TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'android',
    installation_id TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_mobile_devices_student_enabled
    ON mobile_devices(student_username, enabled);
