<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# `mobile_auth`

This module exposes the Android login backend:

- `POST /mobile/login`
- `GET /mobile/me`
- `POST /mobile/logout`
- `GET /mobile/sessions`
- `GET /mobile/timetable`
- `GET /mobile/exam_schedule`

It reuses the student RADIUS settings from `config.py`, stores opaque bearer tokens in SQLite,
and blocks a different username from logging in on the same device during the same UTC day.
`POST /mobile/login` is rate limited per username when a username is supplied, with an IP
fallback for malformed requests.
The bearer-token endpoints are also rate limited per authenticated mobile user.
The attendance challenge response includes the geofence for the room where the scanned class
is held.
The attendance history summary used by mobile clients lives in
[mobile_attendance](mobile_attendance.md).
The personalized timetable endpoint returns the authenticated student's semester enrollments
and flat weekly timetable events. The client groups events however it wants.
The personalized exam schedule endpoint returns the authenticated student's exam entries from
the imported `exam_schedule.csv` files together with the imported
`terms/<term>/exam_applications.csv` application
rows. Import matching uses `course_code + accreditation` as the exam key. The response exposes
the public subject display name as `subject_name`, while `course_code` keeps the course
code used to match the imported schedule rows. The backend returns the available exam
terms for the current semester, defaults to the newest term, and accepts `term_code` to switch
to another term. It also accepts `mode=applied` for the default view or `mode=all_subjects`
to show all exams for subjects the student is enrolled in for that semester. The
`available_terms` payload is a structured list with `term_code`, `start_date`, `end_date`,
and `semester_id`.
The `/mobile/me` payload also includes the current 2FA state and the current-semester unread
notification count so the app can render its header without extra startup requests.

## Typical Flow

1. The app posts `username`, `password`, `device_id`, and `device_name` to `/mobile/login`.
2. The backend returns an opaque bearer token.
3. The app sends `Authorization: Bearer <token>` to `/mobile/me` or `/mobile/logout`.
4. The app fetches `/mobile/timetable` after login to render the personalized schedule.
5. The app fetches `/mobile/exam_schedule` to render the exam schedule on a separate screen.
6. The app passes `term_code` when the user switches to another exam term.

If `REVIEW_MODE=1` is configured, the backend also enables the review login path and the mapped
student data flow.

::: mobile_auth
