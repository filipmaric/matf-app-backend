#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Fetch notification CSV data from a server and import it locally."""

from __future__ import annotations

import argparse
import importlib
import sqlite3
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import db as mydb

IMPORT_STATE_NAME = "notifications_last_sync"

import_notifications = importlib.import_module("scripts.import.import_notifications")


def _read_import_state(cur):
    row = cur.execute(
        "SELECT value FROM import_state WHERE name = ?",
        (IMPORT_STATE_NAME,),
    ).fetchone()
    return row[0] if row is not None else None


def _build_fetch_params(watermark):
    params = {}
    if watermark:
        params["since"] = watermark
    return params


def _fetch_csv(url, watermark, timeout=30):
    response = requests.get(url, params=_build_fetch_params(watermark), timeout=timeout)
    response.raise_for_status()
    return response.text


def _write_temp_csv(content):
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False)
    try:
        handle.write(content)
        handle.flush()
        return Path(handle.name)
    finally:
        handle.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch notification CSV data from a server and import it locally."
    )
    parser.add_argument("database", help="SQLite database path")
    parser.add_argument("url", help="Notification CSV URL")
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds",
    )
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row
    try:
        mydb.init_db(conn)
        mydb.ensure_notification_schema(conn)
        watermark = _read_import_state(conn.cursor())
        csv_text = _fetch_csv(args.url, watermark, timeout=args.timeout)
        if not csv_text.strip():
            print("No notification updates returned by the server.")
            if watermark is not None:
                print(f"CURRENT_WATERMARK={watermark}")
            return 0

        temp_path = _write_temp_csv(csv_text)
        try:
            return import_notifications.main([args.database, str(temp_path)])
        finally:
            temp_path.unlink(missing_ok=True)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
