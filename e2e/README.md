# Attendance browser E2E tests

These tests exercise the teacher attendance page in a real Chromium browser.
They use the review demo, so they do not require RADIUS credentials or a
production database.

The suite also starts an isolated SQLite database, logs in with a local mock
teacher account, and verifies starting and stopping a real weekly attendance
session.

The room-reservation test also uses the isolated database. It creates a
cancelled weekly class and verifies that its time slots are exposed as
reservation sensors and can be reserved by dragging across them.

From this directory:

```sh
npm install
npx playwright install chromium
npm test
```

The test server runs with `REVIEW_MODE=1` and is stopped by Playwright after
the test run.
