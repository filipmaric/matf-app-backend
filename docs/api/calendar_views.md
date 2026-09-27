<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# `calendar_views`

This module owns the calendar metadata view and the calendar-day update endpoint.

It exposes:

- `GET /calendar`
- `GET /calendar_data`
- `GET /mobile/calendar`
- `POST /update_calendar`

## Access Notes

- `GET /calendar`, `GET /calendar_data`, and `POST /update_calendar` require an administrator session.
- `GET /mobile/calendar` requires an authenticated Android session and is read-only.
- `GET /calendar_data` is rate limited separately from the calendar write endpoint.

## Examples

Fetch month metadata as an administrator:

```bash
curl -i -b cookies.txt "http://127.0.0.1:5000/calendar_data?month=3&year=2026"
```

Update calendar-day kinds as an administrator:

```bash
curl -i -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '[{"date":"2026-03-09","kind":"teaching","week_day":0}]' \
  http://127.0.0.1:5000/update_calendar
```

Open the calendar page as an administrator:

```bash
curl -i -b cookies.txt http://127.0.0.1:5000/calendar
```

Typical response:

- `{"calendar": {...}, "holidays": [...]}` for `GET /calendar_data`

Each calendar entry has a `kind` (`teaching`, `makeup`, `exam`, `colloquium`, or
`non_working`) and an optional `week_day` override. For `makeup` days,
`week_day` selects the regular timetable that should be used.

The mobile endpoint accepts `month` and `year` query parameters and supports
`ETag`/`If-None-Match` caching. Responses may be cached by clients for one hour.
The backend also keeps a one-hour in-process cache per month and invalidates it
after an administrative calendar update.

::: calendar_views
