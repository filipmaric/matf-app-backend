# Copyright (c) 2026 Filip Marić. See LICENCE.

from pathlib import Path


CELL_RENDERERS = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "js"
    / "cellRenderers.js"
)
MAIN_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "js"
    / "main.js"
)


def test_attendance_button_remains_for_events_with_registered_students():
    source = CELL_RENDERERS.read_text(encoding="utf-8")

    assert "appendAttendanceBtn(" in source
    assert "attendance-qr-icon" in source
    assert "Погледај пријављене студенте" in source


def test_occupancy_conflicts_are_visually_marked():
    source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "js"
        / "cellRenderers.js"
    ).read_text(encoding="utf-8")
    css_source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "css"
        / "base.css"
    ).read_text(encoding="utf-8")

    assert "occupancy-conflict" in source
    assert "occupancy-conflict-indicator" in source
    assert "table.occupancy-table td.occupancy-conflict" in css_source


def test_admin_can_open_weekly_attendance_roster():
    source = CELL_RENDERERS.read_text(encoding="utf-8")
    teacher_source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "js"
        / "attendanceTeacher.js"
    ).read_text(encoding="utf-8")
    assert "allowAdmin = false" in source
    assert "allowAdmin && ctx.isAdmin" in source
    assert "function appendAttendanceBtn" in source
    assert "attendanceCount > 0" in source
    assert '"weekly",\n            cellData.weekly_session_id,' in source
    assert "const historyView = Boolean(data.can_view && !data.attendance_open);" in teacher_source
    assert "renderRoster(" in teacher_source
    assert '"reservation",\n            cellData.id,' in source


def test_expired_attendance_links_to_my_reservations():
    source = MAIN_SCRIPT.read_text(encoding="utf-8")

    assert "onOpenAttendanceList" in source
    assert "attendance_kind: kind" in source
    assert "attendance_id: String(eventId)" in source
    assert "attendance_date: date" in source
    assert "${basePath}/my_reservations?${params.toString()}" in source


def test_main_page_shows_admin_attendance_navigation_for_admins():
    source = MAIN_SCRIPT.read_text(encoding="utf-8")
    header_source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "js"
        / "siteHeader.js"
    ).read_text(encoding="utf-8")

    assert "initializeSiteHeader" in source
    assert "onLogin: () => this.refresh()" in source
    assert "adminAttendance" in header_source
    assert "isAdmin ? 'block' : 'none'" in header_source


def test_teacher_attendance_polling_only_runs_for_active_sessions():
    source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "js"
        / "attendanceTeacher.js"
    ).read_text(encoding="utf-8")

    assert "function startAttendancePolling(root)" in source
    assert "if (!data.attendance_session_active)" in source
    assert "stopAttendancePolling();" in source
    assert "startAttendancePolling(root);" in source


def test_teacher_added_students_use_teacher_source_label():
    attendance_source = (
        Path(__file__).resolve().parents[1] / "attendance.py"
    ).read_text(encoding="utf-8")
    teacher_source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "js"
        / "attendanceTeacher.js"
    ).read_text(encoding="utf-8")
    reservations_source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "js"
        / "myReservations.js"
    ).read_text(encoding="utf-8")

    assert "registration_source='teacher'" in attendance_source
    assert "source === 'android' || source === 'teacher'" in teacher_source
    assert "['android', 'teacher'].includes(rawSource)" in reservations_source


def test_attendance_option_panels_share_a_wrapping_layout():
    teacher_source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "js"
        / "attendanceTeacher.js"
    ).read_text(encoding="utf-8")
    css_source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "css"
        / "base.css"
    ).read_text(encoding="utf-8")

    assert teacher_source.count('attendance-option-panel') == 3
    assert ".attendance-option-panel" in css_source
    assert "flex-direction: column" in css_source
    assert "overflow-wrap: anywhere" in css_source


def test_teacher_roster_has_a_csv_export_control():
    source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "js"
        / "attendanceTeacher.js"
    ).read_text(encoding="utf-8")
    css_source = (
        Path(__file__).resolve().parents[1]
        / "static"
        / "css"
        / "base.css"
    ).read_text(encoding="utf-8")

    assert "function attendanceRosterCsv(students)" in source
    assert "downloadTextFile('prijavljeni-studenti.csv'" in source
    assert "csvLink.textContent = 'CSV'" in source
    assert "csvLink.disabled = !students.length" in source
    assert ".attendance-csv-link" in css_source
