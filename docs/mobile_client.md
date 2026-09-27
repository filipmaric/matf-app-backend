<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# Mobile Client Contract

This page collects the backend endpoints and payloads that a native iOS client needs in order
to reproduce the current Android attendance app behavior without changing the backend.

## Scope

The mobile client currently needs:

- authentication against the student RADIUS backend
- a persisted bearer token
- the current-semester attendance summary
- the personalized semester timetable
- QR attendance check-in
- rotating challenge numbers
- optional geofence enforcement

The backend does not need any iOS-specific changes for this flow. The iOS app should speak the
same JSON contract that the Android app already uses.

## Base URL

The app may be deployed under a path prefix such as `/matf-app`, so the mobile client should
not hard-code the host or path. Treat the deployment base URL as configurable.

All examples below use plain root-relative paths.

## Authentication

### `POST /mobile/login`

Request JSON:

```json
{
  "username": "student1",
  "password": "secret",
  "device_id": "device-1",
  "device_name": "iPhone"
}
```

Response JSON on success:

```json
{
  "token": "<opaque-bearer-token>",
  "token_type": "Bearer",
  "expires_at": "2026-06-21T12:00:00+00:00",
  "user": {
    "id": 1,
    "radius_username": "student1"
  },
  "session": {
    "id": 12,
    "device_id": "device-1",
    "device_name": "iPhone",
    "expires_at": "2026-06-21T12:00:00+00:00"
  }
}
```

Important behavior:

- the token is opaque; do not inspect it client-side
- store it securely in Keychain
- use the same `device_id` for that installation
- the backend blocks a different username on the same device during the same UTC day

### `GET /mobile/me`

Headers:

```http
Authorization: Bearer <token>
```

Response:

```json
{
  "user": {
    "id": 1,
    "radius_username": "student1"
  },
  "session": {
    "id": 12,
    "device_id": "device-1",
    "device_name": "iPhone",
    "expires_at": "2026-06-21T12:00:00+00:00",
    "last_seen_at": "2026-06-21T11:15:00+00:00"
  },
  "two_factor": {
    "enabled": true,
    "setup_pending": false,
    "disabled": false,
    "grace_active": true
  },
  "unread_count": 3
}
```

Use this to restore a session after app restart.

### `POST /mobile/logout`

Headers:

```http
Authorization: Bearer <token>
```

Response:

```json
{"ok": true}
```

### `GET /mobile/sessions`

Headers:

```http
Authorization: Bearer <token>
```

Response:

```json
{
  "user": {
    "id": 1,
    "radius_username": "student1"
  },
  "current_session_id": 12
}
```

## Attendance History

### `GET /mobile/attendance/history`

Headers:

```http
Authorization: Bearer <token>
```

Response:

```json
{
  "current_semester": {
    "id": 1,
    "name": "Summer 2026",
    "start_date": "2026-03-01",
    "end_date": "2026-06-30"
  },
  "summaries": [
    {
      "course_id": 10,
      "course_name": "Algorithms",
      "course_code": "ALG",
      "attended_lessons": 9,
      "total_lessons_with_recorded_attendance": 12
    }
  ]
}
```

Only courses with at least one recorded attendance appear.

## Personalized Timetable

### `GET /mobile/timetable`

Headers:

```http
Authorization: Bearer <token>
```

Optional query parameters:

- `semester_id`

Response:

```json
{
  "student": {
    "username": "student1",
    "student_index": "125/1997",
    "student_name": "Filip Maric",
    "student_label": "Filip Maric (125/1997)"
  },
  "semester": {
    "id": 2,
    "name": "2026/27. prolećni",
    "start_date": "2026-03-23",
    "end_date": "2026-09-30"
  },
  "enrollments": [
    {
      "course_id": 10,
      "course_code": "an1",
      "course_name": "Analiza 1",
      "group_id": 4,
      "group_name": "1o1",
      "semester_id": 2
    }
  ],
  "events": [
    {
      "course_id": 10,
      "course_code": "an1",
      "course_name": "Analiza 1",
      "course_type": "p",
      "group_id": 4,
      "group_name": "1o1",
      "teacher_username": "predrag.janicic",
      "teacher_name": "Predrag Janičić",
      "room_id": 12,
      "room_name": "406",
      "room_code": "406",
      "day_of_week": 1,
      "start_slot": 10,
      "end_slot": 12,
      "weekly_session_id": 1234,
      "course_session_id": 4321,
      "semester_id": 2
    }
  ],
  "generated_at": "2026-08-12T12:00:00+00:00"
}
```

The `events` array is flat; the client can group it by day or render it as an agenda.

## Attendance Scan Flow

### 1. Open the short-lived QR link

The QR code points to:

```text
/attendance/<kind>/<event_id>/<event_date>/join/<join_token>
```

For mobile clients, the QR token should still be used. It creates a longer-lived attendance
attempt token that the client reuses for the rest of the flow.

### 2. Fetch the challenge payload

### `GET /attendance/<kind>/<event_id>/<event_date>/challenge`

Headers:

```http
Authorization: Bearer <token>
```

Query parameters:

- `join_token=<qr-token>` for the first request after scanning
- `attendance_attempt_token=<attempt-token>` for subsequent refreshes

The mobile response includes:

- `event`
- `challenge`
- `attendance_attempt_token`
- `attendance_geofence_available`
- `attendance_geofence_enabled`
- `attendance_geofence_warning`
- `attendance_locations` when the client is mobile-authenticated

The `challenge` object currently contains:

- `bucket`
- `current_code`
- `options`
- `expires_in`

Example:

```json
{
  "event": {
    "course_name": "Algorithms",
    "room_name": "A1",
    "teacher_name": "Prof. Example",
    "start_slot": 10,
    "end_slot": 12
  },
  "challenge": {
    "bucket": 123456,
    "current_code": 4321,
    "options": [4321, 1111, 2222, 3333],
    "expires_in": 7
  },
  "attendance_attempt_token": "<attempt-token>",
  "attendance_geofence_available": true,
  "attendance_geofence_enabled": true,
  "attendance_geofence_warning": null,
  "attendance_locations": [
    {
      "building_name": "Studentski trg",
      "name": "Studentski trg",
      "latitude": 44.8200177330261,
      "longitude": 20.45871822883615,
      "radius_m": 100
    }
  ]
}
```

Important behavior:

- `expires_in` is the remaining seconds in the current challenge bucket
- the client should refresh the challenge using the attendance attempt token
- if geofencing is enabled and the client has location data, the app must submit latitude/longitude

### 3. Submit attendance

### `POST /attendance/<kind>/<event_id>/<event_date>/join`

Headers:

```http
Authorization: Bearer <token>
Content-Type: application/json
```

Request JSON for mobile:

```json
{
  "attendance_attempt_token": "<attempt-token>",
  "selected_code": 4321,
  "latitude": 44.8200,
  "longitude": 20.4587
}
```

Response JSON on success:

```json
{
  "success": true,
  "username": "student1"
}
```

If geofencing is enabled and the location is outside the allowed buildings, the backend returns
`403` with a detailed payload including:

- `error_code`
- `error`
- `current_location`
- `closest_location`

If the chosen number is wrong, the backend returns:

- `409`
- `{"error_code": "attendance_wrong_code", ...}`

If the attendance attempt token is blocked or expired, the backend returns:

- `403`
- `{"error_code": "attendance_attempt_blocked", ...}`
  or
- `{"error_code": "attendance_attempt_expired", ...}`

## Recommended iOS client state

Keep the same conceptual split as the Android app:

- auth/session state
- QR scanner state
- geofence state
- challenge state
- attendance history state

That makes it easier to map the existing backend behavior onto SwiftUI or UIKit without changing
the backend contract.
