# Copyright (c) 2026 Filip Marić. See LICENCE.

import csv
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from scripts.load.attendance_stress_test import (
    Account,
    build_parser,
    cleanup_attendance,
    load_accounts,
    load_usernames,
    percentile_report,
    run_flow,
    validate_args,
    write_cleanup_sql,
)


def write_accounts(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["username", "password", "device_id"])
        writer.writeheader()
        writer.writerows(rows)


def test_load_accounts_requires_unique_complete_rows(tmp_path):
    path = tmp_path / "accounts.csv"
    write_accounts(path, [{"username": "s1", "password": "secret", "device_id": "d1"}])

    assert load_accounts(path) == [Account("s1", "secret", "d1")]

    write_accounts(
        path,
        [
            {"username": "s1", "password": "secret", "device_id": "d1"},
            {"username": "s1", "password": "secret2", "device_id": "d2"},
        ],
    )
    with pytest.raises(ValueError, match="duplicate username"):
        load_accounts(path)


def test_percentile_report_is_deterministic():
    assert percentile_report([10, 20, 30, 40, 50]) == {
        "min": 10,
        "p50": 30,
        "p95": 50,
        "p99": 50,
        "max": 50,
    }


def test_cleanup_only_removes_selected_event_and_accounts(tmp_path):
    database = tmp_path / "test.db"
    import sqlite3

    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE attendance_records (event_kind TEXT, event_id INTEGER, event_date TEXT, username TEXT)"
        )
        connection.executemany(
            "INSERT INTO attendance_records VALUES (?, ?, ?, ?)",
            [
                ("weekly", 10, "2026-01-01", "s1"),
                ("weekly", 10, "2026-01-01", "other"),
                ("weekly", 11, "2026-01-01", "s1"),
            ],
        )

    assert cleanup_attendance(database, 10, "2026-01-01", ["s1"]) == 1
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT * FROM attendance_records ORDER BY event_id, username").fetchall()
    assert rows == [
        ("weekly", 10, "2026-01-01", "other"),
        ("weekly", 11, "2026-01-01", "s1"),
    ]


def test_cleanup_sql_is_reviewable(tmp_path):
    output = tmp_path / "cleanup.sql"
    write_cleanup_sql(output, 10, "2026-01-01", ["s1", "s2"])
    text = output.read_text(encoding="utf-8")
    assert "event_id = 10" in text
    assert "'s1', 's2'" in text


def test_load_usernames_ignores_comments_and_blank_lines(tmp_path):
    path = tmp_path / "usernames.txt"
    path.write_text("# test accounts\n\ns1\ns2\n", encoding="utf-8")
    assert load_usernames(path) == ["s1", "s2"]


def test_remote_run_requires_explicit_production_flag(tmp_path):
    path = tmp_path / "accounts.csv"
    write_accounts(path, [{"username": "s1", "password": "secret", "device_id": "d1"}])
    args = build_parser().parse_args(
        [
            "--base-url", "https://mia.example.test/matf-app",
            "--accounts-file", str(path),
            "--event-id", "10",
            "--event-date", "2026-01-01",
            "--join-token", "token",
            "--clients", "1",
        ]
    )
    with pytest.raises(ValueError, match="--allow-remote"):
        validate_args(args, load_accounts(path))


def test_run_flow_reproduces_login_challenge_and_submit(monkeypatch):
    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.ok = 200 <= status_code < 400

        def json(self):
            return self._payload

    class Session:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append(("POST", url, kwargs))
            if url.endswith("/mobile/login"):
                return Response(200, {"token": "bearer-token"})
            return Response(200, {"success": True})

        def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            return Response(
                200,
                {
                    "challenge": {"current_code": 1234},
                    "attendance_attempt_token": "attempt-token",
                },
            )

        def close(self):
            pass

    session = Session()
    monkeypatch.setattr(
        "scripts.load.attendance_stress_test.requests.Session",
        lambda: session,
    )
    args = SimpleNamespace(
        base_url="http://127.0.0.1:5000",
        timeout=1,
        latitude=44.82,
        longitude=20.45,
    )

    result = run_flow(
        Account("s1", "secret", "device-1"),
        args,
        event_id=10,
        event_date="2026-01-01",
        join_token="qr-token",
        scheduled_at=time.monotonic(),
        stop_event=threading.Event(),
    )

    assert result.status == "success"
    assert result.login_ms is not None
    assert result.challenge_ms is not None
    assert result.submit_ms is not None
    assert [call[0] for call in session.calls] == ["POST", "GET", "POST"]
    assert session.calls[1][2]["params"] == {"join_token": "qr-token"}
    assert session.calls[2][2]["json"] == {
        "attendance_attempt_token": "attempt-token",
        "selected_code": 1234,
        "latitude": 44.82,
        "longitude": 20.45,
    }
