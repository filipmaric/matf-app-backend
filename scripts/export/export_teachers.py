#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Export teachers from the SQLite database to a CSV file."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


def export_teachers(database_path: Path, output_path: Path) -> int:
    """Write all teachers, ordered by username, to ``output_path``."""
    if not database_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT username, name
            FROM teachers
            ORDER BY username, id
            """
        ).fetchall()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["username", "name"])
            for row in rows:
                writer.writerow([row["username"] or "", row["name"] or ""])
    finally:
        conn.close()

    print(f"ROWS={len(rows)}")
    print(f"OUTPUT={output_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export teachers from a SQLite database to a CSV file."
    )
    parser.add_argument("--database", required=True, help="SQLite database path")
    parser.add_argument("--output", required=True, help="Path to write the exported CSV")
    args = parser.parse_args(argv)
    return export_teachers(Path(args.database), Path(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
