# Copyright (c) 2026 Filip Marić. See LICENCE.
import importlib
from pathlib import Path

import app as myapp

sync_notifications = importlib.import_module("scripts.import.sync_notifications")


def test_sync_notifications_uses_watermark_and_calls_importer(tmp_path, db, monkeypatch):
    db.execute(
        """
        INSERT INTO import_state (name, value)
        VALUES (?, ?)
        """,
        ("notifications_last_sync", "2026-08-13T10:00:00Z"),
    )

    fetched = {}

    def fake_get(url, params=None, timeout=None):
        fetched["url"] = url
        fetched["params"] = params
        fetched["timeout"] = timeout

        class Response:
            status_code = 200
            text = (
                "source_id,semester_id,course_code,teacher_username,group_names,title,body,published_at\n"
                "central-010,,MAT1,prof.mat,1o1,New notice,Fresh notice text,2026-08-13T10:30:00+00:00\n"
            )

            def raise_for_status(self):
                return None

        return Response()

    imported = {}

    def fake_main(argv):
        imported["argv"] = argv
        return 0

    monkeypatch.setattr(sync_notifications.requests, "get", fake_get)
    monkeypatch.setattr(sync_notifications.import_notifications, "main", fake_main)

    exit_code = sync_notifications.main(
        [myapp.DATABASE, "https://example.invalid/notifications.csv"]
    )

    assert exit_code == 0
    assert fetched["url"] == "https://example.invalid/notifications.csv"
    assert fetched["params"] == {"since": "2026-08-13T10:00:00Z"}
    assert fetched["timeout"] == 30
    assert imported["argv"][0] == myapp.DATABASE
    assert Path(imported["argv"][1]).exists() is False


def test_sync_notifications_handles_empty_response(tmp_path, db, monkeypatch):
    db.execute(
        """
        INSERT INTO import_state (name, value)
        VALUES (?, ?)
        """,
        ("notifications_last_sync", "2026-08-13T10:00:00Z"),
    )

    def fake_get(url, params=None, timeout=None):
        class Response:
            status_code = 204
            text = ""

            def raise_for_status(self):
                return None

        return Response()

    monkeypatch.setattr(sync_notifications.requests, "get", fake_get)

    exit_code = sync_notifications.main(
        [myapp.DATABASE, "https://example.invalid/notifications.csv"]
    )

    assert exit_code == 0
    state = myapp.query_db(
        "SELECT value FROM import_state WHERE name = ?",
        ("notifications_last_sync",),
        one=True,
    )
    assert state["value"] == "2026-08-13T10:00:00Z"
