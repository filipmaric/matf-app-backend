<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# Attendance

The attendance flow works like this:

1. A teacher opens the attendance page for one lecture or reservation.
2. The page shows a QR code that rotates every 8 seconds by default. The
   teacher may disable this before starting the session, in which case the
   QR join link remains unchanged for that session.
3. A student scans the QR code and gets a 90-second attendance session.
4. The student picks a challenge number that rotates every 10 seconds.
5. The server validates the student credentials and check-in choice.

The teacher page also shows the current attendance list for that lecture
occurrence. The same page can be opened for a personal room reservation.

When the attendance window has ended, the responsible teacher or reservation
owner can still open the page to view the historical roster. Administrators can
open historical rosters for any weekly term or personal reservation with
recorded attendance. In historical mode, QR/session controls and polling are
disabled; the roster remains available, including its CSV export.

The occupancy page displays a QR action for an event while attendance is open,
and keeps it available after the window when students have registered. Active
overlapping events are marked visually as conflicts. Canceled weekly classes
are not treated as conflicts.

## Endpoint Flow

Teacher page:

```bash
GET /attendance/<kind>/<event_id>/<event_date>/data
```

`kind` is either `weekly` or `reservation`. The data endpoint returns the
roster to an authorized teacher, reservation owner, or administrator even when
`attendance_open` is `false`; student registration endpoints continue to reject
requests outside the attendance window.

Student QR entry:

```bash
GET /attendance/<kind>/<event_id>/<event_date>/join/<token>
```

Student page challenge payload:

```bash
GET /attendance/<kind>/<event_id>/<event_date>/challenge
```

Student check-in submission:

```bash
POST /attendance/<kind>/<event_id>/<event_date>/join
```

The student submission sends:

- `username`
- `password`
- `selected_code`

The QR rotation preference is sent when starting a session:

```http
POST /attendance/<kind>/<event_id>/<event_date>/session
Content-Type: application/json

{"active": true, "qr_rotation_enabled": false}
```

`qr_rotation_enabled` defaults to `true`. This affects only the QR join link;
the student challenge number continues to rotate independently. The setting
and session activation are saved together.
