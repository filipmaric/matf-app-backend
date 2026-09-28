# Copyright (c) 2026 Filip Marić. See LICENCE.

from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "js"
    / "myReservations.js"
)
API_SCRIPT = SCRIPT.with_name("api.js")


def script_text():
    return SCRIPT.read_text(encoding="utf-8")


def api_script_text():
    return API_SCRIPT.read_text(encoding="utf-8")


def function_body(source, function_name):
    marker = f"function {function_name}("
    start = source.index(marker)
    next_function = source.find("\nfunction ", start + len(marker))
    if next_function == -1:
        return source[start:]
    return source[start:next_function]


def test_reservations_page_defers_attendance_loading():
    source = script_text()
    load_reservations = function_body(source, "loadReservations")

    assert "createLazyPersonalAttendanceSummary" in load_reservations
    assert "renderCourseOverview" in load_reservations
    assert "await renderPersonalAttendanceSummary" not in load_reservations
    assert "await renderCourseSessions" not in load_reservations
    assert "getAttendanceRoster" not in load_reservations


def test_lazy_loader_requires_explicit_click_and_loads_once():
    source = script_text()
    loader = function_body(source, "createLazyAttendanceLoader")

    assert "document.createElement('details')" in loader
    assert "shell.className = 'attendance-collapsible attendance-summary'" in loader
    assert "document.createElement('summary')" in loader
    assert "shell.addEventListener('toggle'" in loader
    assert "if (!shell.open || loaded) return" in loader
    assert "loaded = true" in loader
    assert "await loadContent()" in loader
    assert "content.textContent = 'Учитавање...'" in loader


def test_attendance_dialog_uses_icon_only_close_button():
    source = script_text()
    assert "closeButton.textContent = '×';" in source
    assert "closeButton.setAttribute('aria-label', 'Затвори');" in source
    assert "content.id = 'attendance-dialog-content';" in source
    assert "body.appendChild(downloadButton);" in source
    assert "dialog.querySelector('#attendance-dialog-content')" in source
    assert "const downloadButton = document.createElement('a');" in source
    assert "downloadButton.href = '#';" in source
    assert "downloadButton.style.display = summaryEntries.length ? 'block' : 'none';" in source


def test_personal_attendance_loads_counts_before_term_details():
    source = script_text()
    lazy_personal_loader = function_body(source, "createLazyPersonalAttendanceSummary")
    personal_loader = function_body(source, "renderPersonalAttendanceByTerm")

    assert "API.getMyReservationsAttendance(semesterId)" in lazy_personal_loader
    assert "attendance_count: counts.get(reservation.id) || 0" in lazy_personal_loader
    assert "reservation.date" in personal_loader
    assert "reservation.attendance_count" in personal_loader
    assert "' · '" in personal_loader
    assert "'(' + reservation.attendance_count" in personal_loader
    assert "summary=1" not in personal_loader
    assert "API.getAttendanceRoster" in personal_loader
    assert "if (!details.open || loaded) return" in personal_loader
    assert "createAttendanceListItem(student)" in personal_loader


def test_course_sessions_are_loaded_by_expanding_the_lazy_section():
    source = script_text()
    course_loader = function_body(source, "createLazyCourseSessions")

    assert "Прикажи термине и присуство" in course_loader
    assert "await renderCourseSessions(content, courses)" in course_loader


def test_course_list_is_rendered_before_attendance_is_loaded():
    source = script_text()
    overview = function_body(source, "renderCourseOverview")

    assert "course.course_name" in overview
    assert "course.sessions.forEach" in overview
    assert "API.getMyCourseAttendance(semesterId, course.course_id)" in overview
    assert "createLazyAttendanceLoader('Присутност по термину'" in overview


def test_course_attendance_api_accepts_a_course_id():
    source = api_script_text()
    assert "async getMyCourseAttendance(semesterId, courseId)" in source
    assert "params.set('course_id', courseId)" in source


def test_attendance_summary_uses_one_server_aggregate_request():
    source = script_text()
    attendance = function_body(source, "renderCourseAttendance")

    assert "API.getAttendanceSummary(" in attendance
    assert "session.weekly_session_id" in attendance
    assert "session.instances || []" in attendance
    assert "Promise.all" not in attendance


def test_weekly_attendance_loads_roster_only_for_expanded_term():
    source = script_text()
    term_loader = function_body(source, "createLazyAttendanceTerm")

    assert "if (!details.open || loaded) return" in term_loader
    assert "API.getAttendanceRoster(kind, eventId, date)" in term_loader
    assert "studentCount" in term_loader


def test_attendance_download_is_added_only_after_students_are_loaded():
    source = script_text()

    assert "function createAttendanceDownloadButton(date, students)" in source
    assert "createAttendanceDownloadButton(reservation.date, data.students)" in source
    assert "createAttendanceDownloadButton(date, data.students)" in source
    assert "Преузми CSV" in source
    assert "link.href = '#'" in source
    assert "event.preventDefault()" in source


def test_course_attendance_summary_uses_a_link():
    source = script_text()
    attendance = function_body(source, "renderCourseAttendance")

    assert "const summaryLink = document.createElement('a')" in attendance
    assert "summaryLink.href = '#'" in attendance
    assert "summaryLink.dataset.loading" in attendance


def test_course_attendance_keeps_scheduled_sessions_without_held_dates():
    source = script_text()
    attendance = function_body(source, "renderCourseAttendance")

    assert "course.sessions.forEach" in attendance
    assert "session.instances || []" in attendance
    assert "Нема одржаних термина у изабраном семестру." not in attendance
