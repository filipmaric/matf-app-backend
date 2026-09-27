#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Generate the people section of a timetable file from course sessions."""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(BACKEND_DIR))
from semester_utils import semester_id_for_academic_year_and_season
from lib.timetable_common import CYRILLIC_TO_LATIN, normalize_group_name


TYPE_SUFFIXES = {"п": "p", "p": "p", "в": "v", "v": "v", "к": "k", "k": "k"}
DEFAULT_ALIASES_PATH = Path("data/2026-27/course_code_aliases.csv")


def transliterate(value: str) -> str:
    return str(value or "").translate(CYRILLIC_TO_LATIN).lower()


def normalize_course_code(code: str) -> str:
    return re.sub(r"[^a-z0-9]", "", transliterate(code))


def course_name_base(name: str, code: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", transliterate(name))
    initials = "".join(token if token.isdigit() else token[0] for token in tokens)
    base = re.sub(r"[^a-z0-9]", "", initials)[:5]
    return base or normalize_course_code(code)[:5] or "course"


def read_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            row["original_code"]: row["timetable_code"]
            for row in csv.DictReader(handle)
            if row.get("original_code") and row.get("timetable_code")
        }


def write_aliases(path: Path, courses: list[tuple[str, str]], aliases: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["original_code", "course_name", "timetable_code"])
        for code, name in courses:
            writer.writerow([code, name, aliases[code]])


def build_aliases(conn: sqlite3.Connection, path: Path) -> dict[str, str]:
    courses = conn.execute(
        "SELECT code, name FROM courses WHERE code IS NOT NULL ORDER BY code"
    ).fetchall()
    course_items = [(str(row["code"]), str(row["name"] or "")) for row in courses]
    aliases = read_aliases(path)
    used = set()
    for code, alias in aliases.items():
        if code not in {item[0] for item in course_items}:
            continue
        if len(alias) > 5 or not re.fullmatch(r"[a-z0-9]{1,5}", alias) or alias in used:
            raise ValueError(f"Invalid or duplicate alias for course {code}: {alias!r}")
        used.add(alias)

    for code, name in course_items:
        if code in aliases:
            continue
        base = course_name_base(name, code)
        candidates = [base]
        code_slug = normalize_course_code(code)
        candidates.extend(
            f"{base[:max(1, 5 - len(suffix))]}{suffix}"
            for suffix in code_slug
        )
        candidates.extend(
            f"{base[:4]}{number:x}" for number in range(36)
        )
        alias = next((candidate for candidate in candidates if candidate not in used), None)
        if alias is None:
            raise ValueError(f"Unable to generate unique alias for course {code}")
        aliases[code] = alias
        used.add(alias)

    write_aliases(path, course_items, aliases)
    return aliases


def format_weekly_lessons(value) -> str:
    number = float(value or 0)
    if number == 4:
        return "2+2"
    return str(int(number)) if number.is_integer() else str(number)


def people_rows(database_path: Path, semester_label: str, aliases_path: Path) -> list[str]:
    if "." not in semester_label:
        raise ValueError(f"Invalid semester label: {semester_label!r}")
    academic_year, season = (part.strip() for part in semester_label.split(".", 1))
    if season not in {"јесењи", "пролећни"}:
        raise ValueError(f"Invalid semester season: {season!r}")

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        aliases = build_aliases(conn, aliases_path)
        semester_id = semester_id_for_academic_year_and_season(conn, academic_year, season)
        if semester_id is None:
            raise ValueError(f"Semester not found: {semester_label}")
        rows = conn.execute(
            """
            SELECT c.code, cs.type, cs.weekly_lessons, t.username,
                   GROUP_CONCAT(g.name) AS group_names
            FROM course_sessions cs
            JOIN courses c ON c.id = cs.course_id
            JOIN teachers t ON t.id = cs.teacher_id
            JOIN semesters s ON s.id = cs.semester_id
            JOIN session_groups sg ON sg.session_id = cs.id
            JOIN groups g ON g.id = sg.group_id
            WHERE s.id = ?
            GROUP BY cs.id, c.code, cs.type, cs.weekly_lessons, t.username
            ORDER BY c.code, cs.type, t.username, cs.id
            """,
            (semester_id,),
        ).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        suffix = TYPE_SUFFIXES.get(str(row["type"]).strip().lower())
        if suffix is None:
            raise ValueError(f"Unsupported course-session type: {row['type']!r}")
        groups = sorted(
            {
                normalized_group
                for group in str(row["group_names"] or "").split(",")
                if (normalized_group := normalize_group_name(group))
                and not re.match(r"^[1-5]a", normalized_group)
            }
        )
        if not groups:
            continue
        course_code = aliases[row["code"]]
        result.append(
            "\t".join(
                (
                    ",".join(groups),
                    str(row["username"]).strip().lower(),
                    f"{course_code}.{suffix}",
                    format_weekly_lessons(row["weekly_lessons"]),
                )
            )
        )
    return result


def replace_people_section(timetable_path: Path, rows: list[str]) -> None:
    lines = timetable_path.read_text(encoding="utf-8").splitlines()
    try:
        people_index = lines.index("people")
    except ValueError as exc:
        raise ValueError(f"People section not found: {timetable_path}") from exc

    end_index = len(lines)
    for index in range(people_index + 1, len(lines)):
        if lines[index] and "\t" not in lines[index]:
            end_index = index
            break
    updated_lines = lines[: people_index + 1] + rows + lines[end_index:]
    timetable_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--timetable", required=True)
    parser.add_argument("--semester", required=True)
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES_PATH)
    args = parser.parse_args(argv)

    rows = people_rows(Path(args.database), args.semester, args.aliases)
    replace_people_section(Path(args.timetable), rows)
    print(f"Generated people section: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
