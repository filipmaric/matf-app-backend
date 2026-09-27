#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Import building locations from a CSV file."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


REQUIRED_HEADERS = {"building_name", "latitude", "longitude", "radius_m"}


def _normalize(value) -> str:
    return " ".join(str(value or "").split())


def _ensure_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'building_locations'"
    ).fetchone()
    if table_exists:
        return
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    conn.executescript(schema_path.read_text(encoding="utf-8"))


def _load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = {str(name).strip() for name in (reader.fieldnames or [])}
        missing = sorted(REQUIRED_HEADERS - fieldnames)
        if missing:
            raise ValueError(
                f"{csv_path.name} is missing required columns: {', '.join(missing)}"
            )
        return list(reader)


def _parse_float(value, field_name: str, row_number: int) -> float:
    text = _normalize(value)
    if not text:
        raise ValueError(f"row {row_number}: {field_name} is required")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"row {row_number}: invalid {field_name}: {value!r}") from exc


def _parse_row(row: dict[str, str], row_number: int) -> tuple[str, float, float, float]:
    building_name = _normalize(row.get("building_name"))
    if not building_name:
        raise ValueError(f"row {row_number}: building_name is required")
    latitude = _parse_float(row.get("latitude"), "latitude", row_number)
    longitude = _parse_float(row.get("longitude"), "longitude", row_number)
    radius_m = _parse_float(row.get("radius_m"), "radius_m", row_number)
    if radius_m <= 0:
        raise ValueError(f"row {row_number}: radius_m must be greater than 0")
    return building_name, latitude, longitude, radius_m


def import_building_locations(database_path: Path, csv_path: Path, schema_path: Path) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    rows = _load_rows(csv_path)
    parsed_rows = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        parsed = _parse_row(row, row_number)
        if parsed[0] in seen:
            raise ValueError(f"row {row_number}: duplicate building_name {parsed[0]!r}")
        seen.add(parsed[0])
        parsed_rows.append(parsed)

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            _ensure_schema(conn, schema_path)
            existing_rows = {
                row["building_name"]: row
                for row in conn.execute(
                    """
                    SELECT building_name, latitude, longitude, radius_m
                    FROM building_locations
                    """
                ).fetchall()
            }

            inserted = 0
            updated = 0
            unchanged = 0
            imported_names = {building_name for building_name, *_ in parsed_rows}

            for building_name, latitude, longitude, radius_m in parsed_rows:
                existing = existing_rows.get(building_name)
                if existing is None:
                    inserted += 1
                elif (
                    float(existing["latitude"]) == latitude
                    and float(existing["longitude"]) == longitude
                    and float(existing["radius_m"]) == radius_m
                ):
                    unchanged += 1
                else:
                    updated += 1
                conn.execute(
                    """
                    INSERT INTO building_locations (building_name, latitude, longitude, radius_m)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(building_name) DO UPDATE SET
                        latitude = excluded.latitude,
                        longitude = excluded.longitude,
                        radius_m = excluded.radius_m
                    """,
                    (building_name, latitude, longitude, radius_m),
                )

            referenced_names = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT DISTINCT location
                    FROM exam_schedule
                    WHERE location IS NOT NULL AND location <> ''
                    """
                ).fetchall()
            }
            deletable_names = [
                row[0]
                for row in conn.execute(
                    """
                    SELECT building_name
                    FROM building_locations
                    WHERE building_name NOT IN ({placeholders})
                    """.format(
                        placeholders=",".join("?" for _ in imported_names) if imported_names else "''"
                    ),
                    tuple(imported_names),
                ).fetchall()
                if row[0] not in referenced_names
            ]
            deleted = 0
            if deletable_names:
                conn.executemany(
                    "DELETE FROM building_locations WHERE building_name = ?",
                    [(name,) for name in deletable_names],
                )
                deleted = len(deletable_names)
    finally:
        conn.close()

    print(f"IMPORTED={len(parsed_rows)}")
    print(f"INSERTED={inserted}")
    print(f"UPDATED={updated}")
    print(f"UNCHANGED={unchanged}")
    print(f"DELETED={deleted}")
    print(f"CSV={csv_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import building locations from a CSV file.")
    parser.add_argument("database", help="SQLite database path")
    parser.add_argument("csv_file", help="CSV file to import")
    parser.add_argument(
        "--schema",
        required=False,
        default=Path(__file__).resolve().parents[2] / "schema.sql",
        help="Path to schema.sql used when the database is empty",
    )
    args = parser.parse_args(argv)
    return import_building_locations(
        Path(args.database),
        Path(args.csv_file).expanduser(),
        Path(args.schema),
    )


if __name__ == "__main__":
    raise SystemExit(main())
