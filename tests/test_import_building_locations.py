# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _init_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with open(REPO_ROOT / "schema.sql", encoding="utf-8") as handle:
            conn.executescript(handle.read())
        conn.commit()
    finally:
        conn.close()


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["building_name", "latitude", "longitude", "radius_m"])
        writer.writerows(rows)


def _fetch_locations(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT building_name, latitude, longitude, radius_m
                FROM building_locations
                ORDER BY building_name
                """
            ).fetchall()
        ]
    finally:
        conn.close()


def run_script(args):
    return subprocess.run(
        [PYTHON, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def test_import_building_locations_syncs_rows_and_preserves_referenced_buildings(tmp_path):
    db_path = tmp_path / "building_locations.db"
    csv_path = tmp_path / "building_locations.csv"
    _init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.execute(
                "INSERT INTO building_locations (building_name, latitude, longitude, radius_m) VALUES (?, ?, ?, ?)",
                ("Old", 1.0, 2.0, 50.0),
            )
            conn.execute(
                "INSERT INTO building_locations (building_name, latitude, longitude, radius_m) VALUES (?, ?, ?, ?)",
                ("Keep", 3.0, 4.0, 60.0),
            )
            conn.execute(
                "INSERT INTO exam_schedule (term_code, course_code, course_name, exam_date, exam_hour, location) VALUES (?, ?, ?, ?, ?, ?)",
                ("2026.07", "C1", "Course", "2026-07-01", 9, "Keep"),
            )
    finally:
        conn.close()

    _write_csv(
        csv_path,
        [
            ["Keep", 3.5, 4.5, 70.0],
            ["New", 5.0, 6.0, 80.0],
        ],
    )

    result = run_script(
        [
            "scripts/import/import_building_locations.py",
            str(db_path),
            str(csv_path),
        ]
    )

    assert _fetch_locations(db_path) == [
        {"building_name": "Keep", "latitude": 3.5, "longitude": 4.5, "radius_m": 70.0},
        {"building_name": "New", "latitude": 5.0, "longitude": 6.0, "radius_m": 80.0},
    ]
    assert "IMPORTED=2" in result.stdout
    assert "INSERTED=1" in result.stdout
    assert "UPDATED=1" in result.stdout
    assert "DELETED=1" in result.stdout
