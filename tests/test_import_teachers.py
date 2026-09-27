# Copyright (c) 2026 Filip Marić. See LICENCE.
import csv
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SCRIPT = REPO_ROOT / "scripts" / "import" / "import_teachers.py"


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            with open(REPO_ROOT / "schema.sql", encoding="utf-8") as f:
                conn.executescript(f.read())
            conn.execute(
                "INSERT INTO teachers (name, username) VALUES (?, ?)",
                ("Стара Наставница", "stara.nastavnica"),
            )
    finally:
        conn.close()


def write_sample_csv(csv_path):
    rows = [
        ["Активни наставници"],
        [
            "Бр.",
            "Презиме",
            "Име",
            "Звање",
            "Адреса е-поште",
            "Лична адреса е-поште",
        ],
        [
            "1.",
            "Петровић",
            "Милица",
            "Доцент",
            "milica.petrovic@matf.bg.ac.rs",
            "",
        ],
        [
            "2.",
            "Јовановић",
            "Ана",
            "Асистент",
            "ana.jovanovic.petrovic@matf.bg.ac.rs",
            "",
        ],
        [
            "3.",
            "Илић",
            "Петар",
            "Асистент",
            "petar.ilic@example.com",
            "",
        ],
        [
            "4.",
            "Промењена",
            "Стара",
            "Асистент",
            "stara.nastavnica@matf.bg.ac.rs",
            "",
        ],
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", quotechar='"', quoting=csv.QUOTE_ALL)
        writer.writerows(rows)


def run_script(*args):
    return subprocess.run(
        [PYTHON, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def test_import_teachers_imports_matf_email_rows_and_skips_others(tmp_path):
    db_path = tmp_path / "teachers.db"
    csv_path = tmp_path / "teachers.csv"
    init_db(db_path)
    write_sample_csv(csv_path)

    result = run_script(
        "--csv",
        str(csv_path),
        "--database",
        str(db_path),
        "--schema",
        str(REPO_ROOT / "schema.sql"),
    )

    assert "Imported 2 teachers" in result.stdout
    assert "Skipped 2 rows" in result.stdout

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT name, username FROM teachers ORDER BY username"
        ).fetchall()
    finally:
        conn.close()

    assert [row["username"] for row in rows] == [
        "ana.jovanovic.petrovic",
        "milica.petrovic",
        "stara.nastavnica",
    ]
    assert [row["name"] for row in rows] == [
        "Ана Јовановић",
        "Милица Петровић",
        "Стара Наставница",
    ]
