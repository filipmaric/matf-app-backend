<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# Attendance stress test

`scripts/load/attendance_stress_test.py` emulates the HTTP protocol used by
the Android attendance flow. It is intended for dedicated test accounts and a
dedicated weekly attendance event, not for real students or a real lecture.

The complete flow for each account is:

1. `POST /mobile/login`
2. `GET /attendance/weekly/<event_id>/<date>/challenge?join_token=...`
3. `POST /attendance/weekly/<event_id>/<date>/join`

The script reads a private CSV with these columns:

```csv
username,password,device_id,device_name
load.student.001,secret-1,load-device-001,Load test device 001
```

Do not commit this file. It contains credentials and should be stored outside
the repository with restrictive permissions.

## Dry run

Validate the input and schedule 300 clients without contacting a server:

```bash
python scripts/load/attendance_stress_test.py \
  --base-url http://127.0.0.1:5000 \
  --accounts-file /secure/load-accounts.csv \
  --event-id 108 \
  --event-date 2026-05-15 \
  --join-token test-token \
  --clients 300 \
  --duration 60 \
  --dry-run
```

## Local run

Start the backend from the `backend` directory with mock student
authentication and a long-lived QR token. The longer token lifetime is needed
because this test uses one captured QR token while it spreads 300 flows over a
minute; do not use these values in production.

Terminal 1:

```bash
cd backend
export APP_ENV=development
export STUDENT_AUTH_MODE=mock
export ATTENDANCE_SECRET=local-attendance-stress-secret
export ATTENDANCE_JOIN_TOKEN_TTL=3600
export ATTENDANCE_CLASS_GRACE_MINUTES=1000000
.venv/bin/python app.py
```

Create a private account file. Mock authentication accepts any non-empty
password, but the usernames must be unique:

```bash
{ echo 'username,password,device_id,device_name'; \
  for i in $(seq -w 1 300); do \
    echo "load.student.$i,local-password-$i,load-device-$i,Local load device $i"; \
  done; \
} > /tmp/attendance-load-accounts.csv
chmod 600 /tmp/attendance-load-accounts.csv
```

Generate the QR token with the same local secret in Terminal 2:

```bash
cd backend
JOIN_TOKEN=$(ATTENDANCE_SECRET=local-attendance-stress-secret \
  ATTENDANCE_JOIN_TOKEN_TTL=3600 \
  .venv/bin/python -c \
  "from attendance import attendance_join_token; print(attendance_join_token('weekly', 108, '2026-05-15'))")
```

First run a five-client smoke test, then run the full local test:

```bash
.venv/bin/python scripts/load/attendance_stress_test.py \
  --base-url http://127.0.0.1:5000 \
  --accounts-file /tmp/attendance-load-accounts.csv \
  --event-id 108 \
  --event-date 2026-05-15 \
  --join-token "$JOIN_TOKEN" \
  --latitude 44.8200177330261 \
  --longitude 20.4587182288362 \
  --clients 5 \
  --duration 5 \
  --report /tmp/attendance-smoke.json

.venv/bin/python scripts/load/attendance_stress_test.py \
  --base-url http://127.0.0.1:5000 \
  --accounts-file /tmp/attendance-load-accounts.csv \
  --event-id 108 \
  --event-date 2026-05-15 \
  --join-token "$JOIN_TOKEN" \
  --latitude 44.8200177330261 \
  --longitude 20.4587182288362 \
  --clients 300 \
  --duration 60 \
  --report /tmp/attendance-stress-local.json \
  --cleanup-sql /tmp/attendance-cleanup.sql
```

The script returns a non-zero exit status only for argument/validation
errors; inspect the JSON report for flow failures and phase latency. Review
the generated cleanup SQL, then remove only the test attendance records with:

```bash
sqlite3 ../data/app.db < /tmp/attendance-cleanup.sql
```

## Load run

The default schedule starts clients evenly over 60 seconds. Each client gets
its own bearer session and device ID. The QR join token and event must be valid
at the time of the test; the challenge response supplies the current code and
the attendance attempt token used by the final POST.

```bash
python scripts/load/attendance_stress_test.py \
  --base-url https://staging.example.edu/matf-app \
  --accounts-file /secure/load-accounts.csv \
  --event-id 108 \
  --event-date 2026-05-15 \
  --join-token '<token-from-test-qr>' \
  --environment staging \
  --allow-remote \
  --latitude 44.8200 \
  --longitude 20.4587 \
  --clients 300 \
  --duration 60 \
  --report attendance-stress.json \
  --cleanup-sql attendance-cleanup.sql
```

Remote runs require `--allow-remote`, and production runs additionally require
`--environment production --allow-production`. These flags are deliberately
separate so that a staging test does not accidentally look like a production
authorization, and a typo cannot silently generate traffic against a remote
server.

The script stops starting new flows when the observed error rate exceeds 10%
after at least 20 completed flows. It does not retry the login or attendance
POST, because retrying a write would distort the test. It records status codes,
success counts, errors, and latency percentiles without recording passwords.

Supply latitude and longitude when the test event has geofencing enabled.

## Cleanup

Review the generated cleanup SQL before executing it on the server:

```bash
sqlite3 /var/www/matf-app/data/app.db < attendance-cleanup.sql
```

Alternatively, run the explicit cleanup mode on the server:

```bash
python scripts/load/attendance_stress_test.py \
  --cleanup \
  --confirm-cleanup \
  --database data/app.db \
  --usernames-file /secure/load-usernames.txt \
  --event-id 108 \
  --event-date 2026-05-15
```

Cleanup removes only `weekly` attendance rows for the selected event, date,
and usernames. It does not remove student accounts, mobile sessions, or the
test event itself.

## Metrics and server observation

The JSON report contains per-flow status, HTTP status codes, total elapsed
time, and min/p50/p95/p99/max latency for the complete flow and each phase
(login, challenge, and submit). During the run also observe Gunicorn
workers, CPU, memory, SQLite lock/busy errors, RADIUS latency, and the final
number of `attendance_records` for the test event.
