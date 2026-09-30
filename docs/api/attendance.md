<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# `attendance`

This module owns the attendance subsystem for both teachers and students.

It covers:

- QR entry tokens that rotate quickly
- the student attendance attempt cookie
- the logged-in Android bearer-token flow
- the rotating challenge number shown on the teacher page
- the student check-in POST flow
- the teacher current attendance list JSON

Main routes:

- `GET /attendance/<kind>/<id>/<date>`
- `GET /attendance/<kind>/<id>/<date>/join/<token>`
- `GET /attendance/<kind>/<id>/<date>/join`
- `GET /attendance/<kind>/<id>/<date>/challenge`
- `GET /attendance/<kind>/<id>/<date>/data`
- `GET /attendance/<kind>/<id>/<date>/data?summary=1`
- `GET /attendance/<kind>/<id>/<date>/data?include_challenge=0`
- `POST /attendance/<kind>/<id>/<date>/session`
- `DELETE /attendance/<kind>/<id>/<date>/student/<record_id>`
- `GET /attendance/weekly/<id>/summary?date=...&date=...`
- `POST /attendance/<kind>/<id>/<date>/join`

## Access Notes

- The teacher page and teacher data endpoint require the logged-in teacher who owns the class, or an administrator.
- The teacher must explicitly start the attendance session before a QR token or challenge is issued.
- The student QR join URL is a short-lived tokenized link.
- The student challenge and submission endpoints require the attendance attempt cookie created by scanning the QR code.
- The Android client can call the same challenge and submission endpoints with `Authorization: Bearer <token>`
  plus the scanned `join_token`.

## Examples

Teacher attendance data:

```bash
curl -i -b cookies.txt \
  http://127.0.0.1:5000/attendance/weekly/51/2026-06-01/data
```

Attendance count only:

```bash
curl -i -b cookies.txt \
  "http://127.0.0.1:5000/attendance/weekly/51/2026-06-01/data?summary=1"
```

The `summary=1` variant performs the same access checks but returns
`student_count` and an empty `students` array. The normal endpoint returns the
full student list.

The `include_challenge=0` variant returns the attendance list without creating
or returning a new QR join token and challenge payload. The teacher web page
uses it after two minutes, when QR generation is paused until the teacher
explicitly extends the attendance session.

Start attendance explicitly:

```http
POST /attendance/<kind>/<event_id>/<event_date>/session
Content-Type: application/json

{"active": true}
```

The teacher may temporarily stop the session with the same endpoint:

```http
POST /attendance/<kind>/<event_id>/<event_date>/session
Content-Type: application/json

{"active": false}
```

An active session expires on the server after `ATTENDANCE_SESSION_TTL`
seconds (120 by default). Closing and reopening the page does not reset this
timer. After expiry the page shows `Продужи пријављивање`; only that explicit
teacher action starts a new two-minute interval.

The weekly summary endpoint performs the aggregation on the server and returns
one attendance total per student across the supplied dates. It is used by the
lazy course-attendance summary, while the full roster remains available for
each individual date.

Student challenge payload:

```bash
curl -i -b cookies.txt \
  http://127.0.0.1:5000/attendance/weekly/51/2026-06-01/challenge
```

Student check-in submission:

```bash
curl -i -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"student1","password":"secret","selected_code":1234}' \
  http://127.0.0.1:5000/attendance/weekly/51/2026-06-01/join
```

Android attendance submission:

```bash
curl -i \
  -H "Authorization: Bearer <android-token>" \
  -H "Content-Type: application/json" \
  -d '{"join_token":"<scanned-qr-token>","attendance_attempt_token":"<attempt-token>","selected_code":1234}' \
  http://127.0.0.1:5000/attendance/weekly/51/2026-06-01/join
```

Typical responses:

- `{"event": {...}, "challenge": {...}}`
- `{"students": [...], "join_token": "..."}`

## Optional username-only registration

The teacher may explicitly enable username-only registration for one weekly
session or reservation occurrence. It is disabled by default and is not an
alternative mobile-authentication flow.

```http
POST /attendance/<kind>/<event_id>/<event_date>/guest-registration
Content-Type: application/json

{"enabled": true}
```

Only the teacher who owns the event or an administrator may change this
setting. The teacher UI displays a warning before enabling it because the QR
code holder can submit any existing student username; the backend therefore
checks that the username exists but does not verify that the person owns it.

When enabled, the web challenge response contains
`attendance_guest_registration_enabled: true` and the student submits only a
username and challenge code. Unknown usernames are rejected with
`error_code: attendance_unknown_username`. Android bearer-authenticated
requests continue to use the existing authenticated flow.
- `{"success": true, "username": "student1"}`

## Security notes

Teacher-side roster, summary, settings, spot-check, and delete endpoints are
restricted to the event owner or an administrator. Browser state-changing
requests additionally require the session CSRF token. Android submissions
require a valid mobile bearer session and a signed, short-lived attendance
attempt token; stopping the teacher session immediately invalidates further
joins even if an older QR or attempt token is still available.

The username-only mode is intentionally weaker and must remain an explicit
teacher choice. It checks only that the submitted username exists. It disables
the geofence for that event because this mode does not authenticate the device.

The `REVIEW_MODE`/`review` event is a deliberate public demo exception used by
the Play review flow. It must be disabled (`REVIEW_MODE=0`) on the production
instance that contains real attendance data. Production deployments must also
set all secret environment variables; the application refuses to start in
production when required secrets are absent.

::: attendance
