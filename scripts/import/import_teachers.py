#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Import teachers from a CSV file into the SQLite database."""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path


EMAIL_RE = re.compile(r"^(?P<username>[a-z]+(?:\.[a-z]+){1,2})@matf\.bg\.ac\.rs$")


def normalize_text(value) -> str:
    return " ".join(str(value or "").split())


def normalize_header(value) -> str:
    return normalize_text(value).casefold()


def ensure_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'teachers'"
    ).fetchone()
    if table_exists:
        return
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    conn.executescript(schema_path.read_text(encoding="utf-8"))


def resolve_username(email: str) -> str | None:
    normalized = normalize_text(email).casefold()
    if not normalized:
        return None
    match = EMAIL_RE.match(normalized)
    if not match:
        return None
    return match.group("username")


def load_source_rows(csv_path: Path) -> tuple[list[dict[str, str]], list[str], int]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", quotechar='"')
        rows = [
            [normalize_text(cell) for cell in row]
            for row in reader
            if any(normalize_text(cell) for cell in row)
        ]

    header_index = None
    headers: list[str] = []
    for index, row in enumerate(rows):
        normalized = [normalize_header(cell) for cell in row]
        if {"презиме", "име", "адреса е-поште"}.issubset(set(normalized)):
            header_index = index
            headers = normalized
            break

    if header_index is None:
        raise ValueError(f"Could not find header row in {csv_path}")

    index_by_header = {header: idx for idx, header in enumerate(headers)}
    required_headers = {"презиме", "име", "адреса е-поште"}
    missing_headers = [header for header in required_headers if header not in index_by_header]
    if missing_headers:
        raise ValueError(
            f"Missing required columns in {csv_path}: {', '.join(sorted(missing_headers))}"
        )

    records: list[dict[str, str]] = []
    for row in rows[header_index + 1 :]:
        records.append(
            {
                "last_name": row[index_by_header["презиме"]] if len(row) > index_by_header["презиме"] else "",
                "first_name": row[index_by_header["име"]] if len(row) > index_by_header["име"] else "",
                "email": row[index_by_header["адреса е-поште"]]
                if len(row) > index_by_header["адреса е-поште"]
                else "",
            }
        )

    return records, headers, header_index + 2


def plan_import(
    records: list[dict[str, str]],
    existing: dict[str, str],
) -> tuple[list[tuple[str, str]], list[tuple[int, str, str]], list[tuple[int, str, str, str]]]:
    planned: list[tuple[str, str]] = []
    skipped: list[tuple[int, str, str]] = []
    duplicates: list[tuple[int, str, str, str]] = []
    seen_usernames: set[str] = set()

    for row_number, record in enumerate(records, start=1):
        first_name = normalize_text(record.get("first_name"))
        last_name = normalize_text(record.get("last_name"))
        email = normalize_text(record.get("email"))

        if not first_name or not last_name:
            skipped.append((row_number, email, "missing first name or last name"))
            continue

        username = resolve_username(email)
        if username is None:
            skipped.append((row_number, email or f"{first_name} {last_name}", "unsupported email format"))
            continue

        display_name = f"{first_name} {last_name}"
        if username in seen_usernames:
            duplicates.append((row_number, username, display_name, "duplicate username in CSV"))
            continue
        seen_usernames.add(username)

        current_name = existing.get(username)
        if current_name is None:
            planned.append((display_name, username))
            existing[username] = display_name
            continue

        skipped.append((row_number, username, "teacher already exists"))

    return planned, skipped, duplicates


def load_existing_teachers(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        normalize_text(row[0]).casefold(): normalize_text(row[1])
        for row in conn.execute(
            """
            SELECT username, name
            FROM teachers
            WHERE username IS NOT NULL AND username <> ''
            """
        )
        if row[0] not in (None, "")
    }


def insert_teachers(conn: sqlite3.Connection, planned: list[tuple[str, str]]) -> int:
    inserted = 0
    with conn:
        for name, username in planned:
            conn.execute(
                """
                INSERT INTO teachers (name, username)
                VALUES (?, ?)
                """,
                (name, username),
            )
            inserted += 1
    return inserted


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import teachers from ../data/<school_year>/teachers.csv into the SQLite database."
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to teachers.csv in the shared data tree",
    )
    parser.add_argument(
        "--database",
        required=True,
        help="SQLite database path",
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="Path to backend/schema.sql used when the database is empty",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing to the database",
    )
    args = parser.parse_args(argv)

    csv_path = Path(args.csv)
    database_path = Path(args.database)
    schema_path = Path(args.schema)

    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}", file=sys.stderr)
        return 2

    records, _headers, first_data_row_number = load_source_rows(csv_path)

    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    try:
        ensure_schema(conn, schema_path)
        existing = load_existing_teachers(conn)
        planned, skipped, duplicates = plan_import(records, existing)

        if first_data_row_number != 1:
            skipped = [(row_number + first_data_row_number - 1, value, reason) for row_number, value, reason in skipped]
            duplicates = [
                (row_number + first_data_row_number - 1, username, name, reason)
                for row_number, username, name, reason in duplicates
            ]

        if args.dry_run:
            for name, username in planned:
                print(f"{username}\t{name}")
            for row_number, value, reason in skipped:
                print(f"SKIP\trow={row_number}\tvalue={value}\treason={reason}")
            for row_number, username, name, reason in duplicates:
                print(f"SKIP\trow={row_number}\tusername={username}\tname={name}\treason={reason}")
            print(f"COUNT={len(planned)}")
            print(f"SKIPPED={len(skipped) + len(duplicates)}")
            return 0

        inserted = insert_teachers(conn, planned)
        print(f"Imported {inserted} teachers into {database_path}")
        total_skipped = len(skipped) + len(duplicates)
        if total_skipped:
            print(f"Skipped {total_skipped} rows:")
            for row_number, value, reason in skipped:
                print(f"- row={row_number}\tvalue={value}\t{reason}")
            for row_number, username, name, reason in duplicates:
                print(f"- row={row_number}\tusername={username}\tname={name}\t{reason}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
