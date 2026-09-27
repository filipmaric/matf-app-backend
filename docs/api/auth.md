<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# `auth`

This module owns browser authentication, teacher RADIUS login, student RADIUS authentication,
CSRF protection, and the in-memory rate limiter.

For the Android bearer-token API, see [`mobile_auth`](mobile_auth.md).

It also exposes the small set of auth-related routes:

- `POST /login`
- `POST /logout`
- `GET /me`
- `GET /is_admin/<username>`

## Access Notes

- `POST /login` does not need a prior session.
- `POST /logout` and `GET /me` use the current browser session.
- `GET /is_admin/<username>` is public, but it only reports an admin flag.
- `POST /login` is rate limited per username when a username is supplied, with an IP fallback
  for malformed requests.

## Examples

Log in with teacher credentials:

```bash
curl -i -c cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"teacher","password":"secret"}' \
  http://127.0.0.1:5000/login
```

If `REVIEW_MODE=1` is configured, the backend also accepts the review login path.

Check the current session:

```bash
curl -i -b cookies.txt http://127.0.0.1:5000/me
```

Log out:

```bash
curl -i -b cookies.txt \
  -H "Content-Type: application/json" \
  -X POST http://127.0.0.1:5000/logout
```

Typical success responses:

- `{"success": true, "username": "teacher", "role": "teacher"}`
- `{"logged_in": true, "username": "teacher"}`
- `{"success": true}`

::: auth
