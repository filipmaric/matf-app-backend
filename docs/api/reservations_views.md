<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# `reservations_views`

This module serves the "My Reservations" page and the semester-scoped JSON model behind it.

It is read-only and focuses on:

- the semester list
- the selected semester
- the current user's personal reservations
- the current user's weekly course sessions
- the held instances of those weekly sessions inside the semester

It depends on the shared semester lookup helpers in `semester.py`.

The browser page uses layered lazy attendance loading. Opening the page fetches
only the reservation and weekly-session model, and the course list is displayed
immediately. Personal-reservation records intentionally contain no attendance
data. Opening the personal-attendance section calls
`GET /my_reservations_attendance_data` once and adds the attendance counts to
the displayed reservations. Opening a course's attendance section calls
`GET /my_course_attendance_data?course_id=...`; that response contains only
the selected course's held dates and `attendance_counts` keyed by date.
The detailed student list for one reservation or one weekly term is fetched
only when that specific row is expanded. The optional summary action requests
a server-side aggregate and does not download the full roster for every date.

## Access Notes

- `GET /my_reservations` shows the HTML page to a logged-in user.
- `GET /my_reservations_data` requires a logged-in user session.
- `GET /my_reservations_data` is rate limited per authenticated user.

Main routes:

- `GET /my_reservations`
- `GET /my_reservations_data`
- `GET /my_reservations_attendance_data`
- `GET /my_course_attendance_data?semester_id=...&course_id=...`

## Examples

Fetch the current semester-scoped reservation model:

```bash
curl -i -b cookies.txt \
  "http://127.0.0.1:5000/my_reservations_data?semester_id=3"
```

Fetch the page HTML:

```bash
  curl -i -b cookies.txt http://127.0.0.1:5000/my_reservations
```

Typical response:

- a JSON object with `semesters`, `current_semester_id`, `selected_semester`, `personal_reservations`, and `courses`

::: reservations_views
