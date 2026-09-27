# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import sqlite3
from pathlib import Path

from scripts.export.export_building_locations import export_building_locations


def _init_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with open(Path(__file__).resolve().parents[1] / "schema.sql", encoding="utf-8") as handle:
            conn.executescript(handle.read())
        conn.commit()
    finally:
        conn.close()


def _fetch_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_building_locations_exports_rows_in_name_order(tmp_path):
    db_path = tmp_path / "building_locations.db"
    output_path = tmp_path / "building_locations.csv"
    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.execute(
                "INSERT INTO building_locations (building_name, latitude, longitude, radius_m) VALUES (?, ?, ?, ?)",
                ("B", 11.0, 21.0, 120.0),
            )
            conn.execute(
                "INSERT INTO building_locations (building_name, latitude, longitude, radius_m) VALUES (?, ?, ?, ?)",
                ("A", 10.0, 20.0, 100.0),
            )
    finally:
        conn.close()

    assert export_building_locations(db_path, output_path) == 0

    rows = _fetch_rows(output_path)
    assert rows == [
        {
            "building_name": "A",
            "latitude": "10.0",
            "longitude": "20.0",
            "radius_m": "100.0",
        },
        {
            "building_name": "B",
            "latitude": "11.0",
            "longitude": "21.0",
            "radius_m": "120.0",
        },
    ]
