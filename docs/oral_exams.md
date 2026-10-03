<!-- Copyright (c) 2026 Filip Marić. See LICENCE. -->
# Oral-exam scheduling

The `/oral_exams` page lets a logged-in teacher plan oral-exam terms for the
course sessions they teach in the current academic year.

## Selection flow

The page first loads the exam terms belonging to the current school year. The
default term is the term that contains today; if there is no active term, it is
the first future term, or the last available term when the school year has
already ended.

The teacher then selects one of their `course_sessions`, rather than only a
course. This is important because different sessions of the same course may
belong to different groups and may receive different oral-exam times. After a
session is selected, the page displays:

- the groups attached to that session;
- the number of exam applications for each group in the selected term;
- written exams relevant to those groups;
- oral exams for the selected groups, including terms scheduled by other
  teachers.

The calendar is shown one week at a time. Navigation is available before,
during, and after the selected exam term because oral exams are often held in
the week following written exams.

## Creating and deleting terms

The teacher creates an oral exam by dragging across the date and hour cells.
The selected interval becomes the exam's `exam_date`, `start_hour`, and
`end_hour`; oral exams therefore do not have a fixed duration. A teacher may
create more than one term for the same course session.

Creating an oral exam does not reserve a room. A newly created term has no
`reservation_id` and is displayed with a `Резервиши салу` link. Only the owner
of the term can delete it or add/remove its room reservation. Other teachers'
oral exams remain visible for planning but do not expose owner-only actions.

## Room reservations

Selecting `Резервиши салу` opens a dialog containing only rooms that are free
for the complete oral-exam interval. Teacher offices are excluded. Conflicts
with ordinary reservations and, on schedule days, with non-cancelled weekly
classes are checked again when the room is submitted, so a room becoming
occupied between the availability request and the submission is rejected.

Rooms in the dialog are grouped by building. After a room is reserved, the
oral-exam schedule stores the resulting reservation ID and the same calendar
controls as ordinary reservations are shown:

- an action to open that day's reservations in a new browser tab;
- an action to cancel the room reservation.

The foreign key is `oral_exam_schedule.reservation_id` with `ON DELETE SET
NULL`. Consequently, deleting a reservation cannot leave a dangling reference:
the oral exam remains scheduled without a room and can be assigned another
room later.

Oral exams may overlap written exams. This is intentional: the oral exam is a
separate scheduling layer and has its own room-reservation checks.

## Student overlap information

For the selected teacher session, the backend obtains the set of students who
have applied for that session's subject in the selected exam term. For each
written or oral exam shown in the calendar, it obtains the corresponding
applicant set and calculates the intersection.

The response exposes:

- `my_student_count`: students common to the selected teacher session and the
  displayed exam;
- `my_student_total`: students who applied for the selected teacher session;
- `overlap_percentage`: the common count as a percentage of
  `my_student_total`.

Exams with no applicable students from the selected groups are omitted. The UI
uses the percentage to make potentially conflicting exams more or less opaque.
The selected teacher's own oral exams remain fully opaque and have a stronger
border; other teachers' oral exams do not have owner controls or a border.

## Data model

The schedule is stored in `oral_exam_schedule`:

| Column | Meaning |
| --- | --- |
| `id` | Oral-exam term identifier |
| `term_code` | Exam term, referencing `exam_terms` |
| `course_session_id` | The specific course session being examined |
| `exam_date` | Calendar date of the oral exam |
| `start_hour`, `end_hour` | Half-open hour interval, `start_hour < end_hour` |
| `reservation_id` | Optional room reservation; null means no room assigned |
| `teacher_username` | Teacher who created and owns the term |

There is deliberately no uniqueness constraint on a course session and exam
term: one session can have multiple oral-exam terms.

## Web API

- `GET /oral_exams` — HTML page; requires web login.
- `GET /oral_exams_data` — terms, teacher sessions, groups, written exams,
  oral exams, and room data. Optional query parameters are `term_code` and
  `session_id`.
- `POST /oral_exams_schedule` — creates a term for an owned course session.
- `DELETE /oral_exams_schedule/<id>` — deletes an owned term.
- `GET /oral_exams_schedule/<id>/available_rooms` — lists currently available
  rooms for an owned term.
- `POST /oral_exams_schedule/<id>/reserve_room` — creates a normal reservation
  and attaches its ID to the oral-exam term.

All write operations require a logged-in teacher and CSRF protection. The
server checks ownership, school-year membership, exam-term membership, valid
dates and hour ranges, and room availability; the browser is not trusted for
these decisions.

## Android integration

The mobile exam-schedule response includes oral exams relevant to the
authenticated student's selected mode and exam term. These entries are read
only on Android and include the oral-exam date, time, course, group, and room
when one has been assigned. Scheduling and room management remain web-only.

## Tests

Backend coverage is primarily in `tests/test_oral_exam_views.py`, including
teacher/session selection, group counts, written-exam filtering, overlap
counts, ownership checks, multiple terms, room availability, reservation
creation, and room cancellation. Mobile serialization and filtering are
covered in `tests/test_mobile_auth.py`.
