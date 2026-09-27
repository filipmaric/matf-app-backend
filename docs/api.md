<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# API Reference

The route overview in `app.py` gives a quick map of the application.

This section groups the route modules under the same three high-level sections used in the
route overview: Mobile, Web, and Other.

Several read endpoints are also rate limited in-app to reduce scraping and query bursts:
`/rooms`, `/occupancy`, `/calendar_data`, `/mobile/calendar`, `/my_reservations_data`, and
`/mobile/attendance/history`.
Mobile bearer-session endpoints are also rate limited per authenticated user.

## Mobile

Modules behind the Android API:

- `mobile_auth.py` for Android bearer-token auth
- `mobile_attendance.py` for the current-semester attendance summary used by mobile clients

### Authentication and session state

- `mobile_auth.py` for login, logout, session state, and device-scoped bearer tokens

### 2FA

- `mobile_auth.py` for 2FA state, setup, confirmation, clearing, disabling, and link completion

### Attendance history

- `mobile_attendance.py` for attendance history summaries

### Push token

- `mobile_auth.py` for push token storage and clearing

### Schedule, grades, and exam applications

- `mobile_auth.py` for buildings, timetable, grades, and exam application data

### Notifications

- `mobile_notifications.py` for notification lists, counts, reads, and deletes

## Web

Modules behind browser-facing pages and web JSON feeds:

- `auth.py` for login, logout, CSRF, and rate limiting
- `attendance.py` for QR attendance and check-in flows
- `occupancy.py` for room list and occupancy reads
- `calendar_views.py` for calendar metadata and updates
- `semester.py` for shared semester lookup helpers
- `reservations.py` for reservation writes and cancellations
- `reservations_views.py` for the My Reservations page
- `main.py` for the homepage blueprint

## Other

Supporting modules and service helpers:

- `db.py` for SQLite helpers
- `config.py` for environment-backed settings
- `factory.py` for app creation

Operational endpoints:

- `GET /healthz` for the health check

## Quick Route Examples

```bash
curl -i http://127.0.0.1:5000/
curl -i "http://127.0.0.1:5000/occupancy?date=2026-03-09"
curl -i -H "Content-Type: application/json" \
  -d '{"username":"teacher","password":"secret"}' \
  http://127.0.0.1:5000/login
curl -i -H "Content-Type: application/json" \
  -d '{"username":"student","password":"secret","device_id":"phone-1","device_name":"Android"}' \
  http://127.0.0.1:5000/auth/login
curl -i -H "Authorization: Bearer <token>" \
  http://127.0.0.1:5000/mobile/attendance/history
curl -i "http://127.0.0.1:5000/my_reservations_data"
curl -i -b cookies.txt "http://127.0.0.1:5000/calendar_data?month=3&year=2026"
```

For attendance, the teacher page first fetches:

- `GET /attendance/<kind>/<event_id>/<event_date>/data`

The student page uses:

- `GET /attendance/<kind>/<event_id>/<event_date>/challenge`
- `POST /attendance/<kind>/<event_id>/<event_date>/join`

For a client-facing mobile contract with exact request/response examples, see
[Mobile Client Contract](mobile_client.md).
