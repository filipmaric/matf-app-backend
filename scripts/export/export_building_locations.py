#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Export building locations to a CSV file."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


def export_building_locations(database_path: Path, output_path: Path) -> int:
    if not database_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT building_name, latitude, longitude, radius_m
            FROM building_locations
            ORDER BY building_name
            """
        ).fetchall()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["building_name", "latitude", "longitude", "radius_m"])
            for row in rows:
                writer.writerow(
                    [
                        row["building_name"],
                        row["latitude"],
                        row["longitude"],
                        row["radius_m"],
                    ]
                )
    finally:
        conn.close()

    print(f"ROWS={len(rows)}")
    print(f"OUTPUT={output_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export building locations to a CSV file.")
    parser.add_argument("--database", required=True, help="SQLite database path")
    parser.add_argument("--output", required=True, help="Path to write the exported CSV")
    args = parser.parse_args(argv)
    return export_building_locations(Path(args.database), Path(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
