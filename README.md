<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# MatF App

[![docs](https://github.com/filipmaric/matf-app-backend/actions/workflows/docs.yml/badge.svg)](https://github.com/filipmaric/matf-app-backend/actions/workflows/docs.yml)
[![tests](https://github.com/filipmaric/matf-app-backend/actions/workflows/tests.yml/badge.svg)](https://github.com/filipmaric/matf-app-backend/actions/workflows/tests.yml)

This repository contains MatF App, a Flask app for timetable, attendance, notifications, and calendar management.

## Documentation Site

The repository includes a MkDocs-based documentation site in `docs/` with:

- setup instructions,
- deployment notes,
- the attendance flow,
- and module-level API docs generated from Python docstrings.

The main entry points are:

- [docs/index.md](docs/index.md) for the docs home page
- [docs/api.md](docs/api.md) for the API index
- [mkdocs.yml](mkdocs.yml) for the docs site configuration

Build it with:

```bash
pip install mkdocs mkdocstrings[python]
mkdocs serve
```

or:

```bash
mkdocs build
```

## Setup After Clone

1. Create and activate a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

This includes the production WSGI server (`gunicorn`) used by the systemd service.

3. Initialize the database schema.

```bash
python app.py init-db
```

This creates `../data/app.db` from `schema.sql` if it does not already exist.

4. Run the app locally.

```bash
python app.py
```

The default local mount point is `/`.

## Production Deployment

In production, the app is started by `systemd` through `gunicorn` and `wsgi:application`.
The real production configuration should be kept in an environment file, for example:

- `/var/www/matf-app/matf.env`

The repository includes [`deploy/matf.env.example`](deploy/matf.env.example) as a template you can copy and fill in.

The service unit should load that file with `EnvironmentFile=...`.

Required variables:

```bash
APP_ENV=production
APPLICATION_ROOT=/matf-app
STATIC_URL_PATH=/matf-app/static
TEACHER_AUTH_MODE=radius
STUDENT_AUTH_MODE=radius
SECRET_KEY=your_flask_session_secret
BACKEND_SERVICE_BEARER_TOKEN=your_backend_service_bearer_token
ATTENDANCE_SECRET=your_attendance_signing_secret
MOBILE_ACTION_OTP_SECRET=your_mobile_action_otp_secret
TEACHER_RADIUS_SERVER=your.teacher.radius.server
TEACHER_RADIUS_SECRET=your_teacher_radius_secret
TEACHER_RADIUS_DICTIONARY=/path/to/teacher/dictionary
STUDENT_RADIUS_SERVER=your.student.radius.server
STUDENT_RADIUS_SECRET=your_student_radius_secret
STUDENT_RADIUS_DICTIONARY=/path/to/student/dictionary
REVIEW_MODE=0
FCM_PROJECT_ID=your_firebase_project_id
FCM_SERVICE_ACCOUNT_FILE=/path/to/firebase-service-account.json
GRADES_SOURCE_URL=https://grades.example.edu/api/grades
GRADES_REQUEST_SIGNING_SECRET=your_grades_request_signing_secret
HYPATIA_EXAM_APPLICATIONS_URL=https://hypatia.example.edu/api/exam-applications
HYPATIA_LINK_URL=https://hypatia.example.edu/2fa/link
HYPATIA_REQUEST_SIGNING_SECRET=your_hypatia_request_signing_secret
```

The backend appends `student_username=...` to the upstream grades request and signs
the canonical request payload with `GRADES_REQUEST_SIGNING_SECRET`. The upstream
server can use the timestamp and nonce headers to reject stale or replayed requests.

`BACKEND_SERVICE_BEARER_TOKEN` is the shared backend-to-backend bearer token used for
service-only routes such as calendar updates, push-test delivery, and Hypatia callbacks.

Exam application toggles use the same request model against Hypatia. The backend
sends the student username, term code, subject id, requested action, timestamp,
nonce, and signature before it mutates local state. If Hypatia rejects the request,
the backend returns Hypatia's message and does not change the local database.

For local testing, run the separate `mock_hypatia_server/` project in this workspace
and point `GRADES_SOURCE_URL`, `HYPATIA_EXAM_APPLICATIONS_URL`, and `HYPATIA_LINK_URL`
to that mock service.

Example service file:

```ini
[Unit]
Description=Gunicorn za MatF App backend
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/matf-app
Environment="PATH=/var/www/matf-app/.venv/bin"
EnvironmentFile=/var/www/matf-app/matf.env
ExecStart=/var/www/matf-app/.venv/bin/gunicorn -b 127.0.0.1:5000 wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart matf-app
```

`scripts/run_prod.sh` is optional. It is a convenience launcher for manual runs and ad-hoc testing; it is not the canonical production startup path.

The helper script refuses to start unless the required variables are set.

## Lecture Attendance

The main occupancy table shows a QR action on lecture entries that the logged-in user can manage. That opens an attendance page with:

- a QR code for students to scan,
- a live list of registered students,
- and a student check-in page that uses a rotating short challenge code.

Operationally, the attendance flow uses:

- a QR link that rotates every 8 seconds,
- a student attendance session that remains valid for 90 seconds after scanning,
- and a separate challenge code that rotates every 10 seconds on the teacher page.

Teacher authentication uses the `TEACHER_AUTH_MODE`/`TEACHER_RADIUS_*` variables above.

Student authentication uses a separate RADIUS server and its own variables:

```bash
export STUDENT_AUTH_MODE=radius
export STUDENT_RADIUS_SERVER=your.radius.server
export STUDENT_RADIUS_SECRET=your_shared_secret
export STUDENT_RADIUS_DICTIONARY=/path/to/dictionary
```

To manually verify a deployed RADIUS configuration, use the diagnostic scripts:

```bash
python scripts/check_teacher_radius.py --env-file /var/www/matf-app/matf.env --username teacher
python scripts/check_student_radius.py --env-file /var/www/matf-app/matf.env --username student
```

Each script prompts for the password, checks the corresponding `*_AUTH_MODE` and
`*_RADIUS_*` settings, and sends one real authentication request. These are
manual deployment checks, not automated tests, and require a reachable RADIUS
server. Avoid passing `--password` when possible so the password is not exposed
in the process command line.

The challenge generator uses `ATTENDANCE_SECRET` if you want to override the default signing secret.
Building geofences are stored in the `building_locations` table and are matched to each room by `rooms.building_name`.
Attendance records also store the best-effort client IP address and the registration source (`web` or `android`).

If you have `students.csv` in the shared `../data/2025-26/` directory and want to load it into the local student directory, run:

```bash
python scripts/import/import_students.py ../data/app.db --csv-file ../data/2025-26/students.csv
```

The importer creates the `students` table automatically if it does not already exist.

### Auxiliary teacher-name import

The authoritative teacher import is [`scripts/import/import_teachers.py`](scripts/import/import_teachers.py),
which reads institutional teacher records from `teachers.csv`. If that source is
unavailable and only `course_sessions.xlsx` is available, the auxiliary
[`scripts/import/import_real_teachers.py`](scripts/import/import_real_teachers.py)
script can be used instead:

```bash
python scripts/import/import_real_teachers.py \
  --workbook ../data/2026-27/course_sessions.xlsx \
  --database ../data/app.db \
  --schema schema.sql
```

This fallback extracts teacher names from the workbook and derives transliterated
usernames. It is intended for one-off or backup-database recovery and should be
used instead of `import_teachers.py`, not as an additional required import step.
Use `--dry-run` to inspect the planned names without modifying the database.

## Notification CSV Import

To import new notifications from a CSV file and immediately dispatch push notifications to the matching students, run:

```bash
python scripts/import/import_notifications.py ../data/app.db ../data/2025-26/notifications.csv
```

The CSV must use headers and UTF-8 encoding. Required columns:

- `source_id`
- `course_code`
- `teacher_username`
- `group_names`
- `title`
- `body`

Optional columns:

- `semester_id` - if empty, the script uses the active semester, or the latest semester if none is active
- `published_at` - if empty, the current UTC timestamp is used

`group_names` may contain one or more group names separated by `;`, `,`, or `|`.

Example:

```csv
source_id,semester_id,course_code,teacher_username,group_names,title,body,published_at
central-001,,MAT1,prof.mat,1o1;1o2,Exercise canceled,Today's exercise is canceled.,2026-08-13T10:00:00+00:00
```

Rows with a `source_id` that already exists in the database are skipped, so the importer is safe to rerun on the same file.

### Server Sync

If the backend should fetch notifications from a server, use the sync helper. It reads `import_state.notifications_last_sync`, requests only newer rows with `since=...`, and then delegates to the importer:

```bash
/var/www/matf-app/.venv/bin/python /var/www/matf-app/scripts/import/sync_notifications.py \
  /var/www/matf-app/data/app.db \
  https://server.example.com/notifications.csv
```

The server should return a CSV file with the same columns as above. The sync helper updates `import_state.notifications_last_sync` only after a successful import.

### Cron Job

If the sync should run periodically, call the sync helper from cron directly:

```bash
/var/www/matf-app/.venv/bin/python /var/www/matf-app/scripts/import/sync_notifications.py \
  /var/www/matf-app/data/app.db \
  https://server.example.com/notifications.csv
```

Example crontab entry that runs every 5 minutes:

```cron
*/5 * * * * /var/www/matf-app/.venv/bin/python /var/www/matf-app/scripts/import/sync_notifications.py /var/www/matf-app/data/app.db https://server.example.com/notifications.csv >> /var/www/matf-app/app.log 2>&1
```

The sync helper can run while the Flask app is serving requests. The importer is idempotent by `source_id`, so repeated runs are safe.
If a previous import is still running, the next cron invocation exits cleanly without starting a second import. The lock file lives in `/tmp/notification_import.lock`.

## Timetable Import Tools

The repository includes a semester-aware timetable synchronizer for the merged underscore-separated format:

- `scripts/import/import_timetable.py` synchronizes timetable entries for a given semester from a text file

Example:

```bash
python scripts/import/import_timetable.py ../data/app.db timetable.txt --semester "2026/27. јесењи"
```

If the timetable is also the source for previously missing assistant or
collaborator sessions, pass `--create-missing-sessions`. This creates only
unambiguous sessions whose teacher, course, type, and groups already exist;
the default import mode never creates course sessions automatically.

The input file is an underscore-separated text file with seven fields:
`teacher_groups_course.type_day_start_slot_end_slot_room`. For example, these
are two entries from `data/2026-27/timetable.txt` for `filip.maric`:

```text
filip.maric_2i171a.2i171b.2i172a.2i172b_15-П103.p_pon_15_18_706
filip.maric_3r.3r15_РМ10.p_pet_9_11_840
```

The fields are the teacher username, one or more groups, the course code and
type (`p`, `v`, `k`, or `o` for other activities), the weekday (`pon`, `uto`, `sre`, `cet`, `pet`, `sub`, or `ned`), the
first and last timetable slots, and the room code.
The special room code `kab` means that the class is held in the teacher's
office. It is imported into the timetable and shown to students, but it is
not available for room reservations or occupancy management.
The timetable synchronizer only attaches weekly slots to course sessions that already exist in the database, so `scripts/import/import_course_sessions.py` must run first.
When a unique existing course session has all timetable groups plus additional
groups with no enrolled students, the timetable row is attached to that
session as well.

## Calendar Import

Import the academic calendar from the Excel workbook. The importer recognizes teaching,
non-working, exam, colloquium, and makeup days. Makeup-day comments in the workbook
specify which weekday's timetable should be used:

```bash
python scripts/import/import_calendar.py \
  ../data/app.db \
  ../data/2026-27/Calendar.xlsx
```

The import replaces calendar rows for the workbook's academic year (1 October through
30 September) and writes semantic `kind` values directly.

Expected line format:

```text
teacher_groups_coursecode_day_start_end_room
```

Example:

```text
profuser_3A.3B_MAT1.p_pon_8_10_406
```

Field values should not contain `_` because `_` is the separator used by the format.

## Conflict Report

To scan the database for future conflicts between reservations and weekly timetable entries, run:

```bash
python scripts/report_conflicts.py ../data/app.db
```

You can also fix the cutoff time for reproducible checks:

```bash
python scripts/report_conflicts.py ../data/app.db --now 2026-03-10T08:00:00
```

The script exits with status `1` if conflicts are found and `0` otherwise.

## Notes

- Use `python app.py init-db` to create a fresh `../data/app.db` from `schema.sql`.
- Local development uses mock teacher authentication unless `TEACHER_AUTH_MODE=radius` is set.
- Run the test suite with:

```bash
pytest -q
```
