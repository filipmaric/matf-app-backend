# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Shared helpers for semester naming and school-year parsing."""

from __future__ import annotations

import re

SEMESTER_SEASONS = ("јесењи", "пролећни")
ACADEMIC_YEAR_RE = re.compile(r"^\s*(\d{4})\s*/\s*(\d{2}|\d{4})\s*$")
SEMESTER_NAME_RE = re.compile(
    r"^\s*(\d{4})\s*/\s*(\d{2}|\d{4})\.\s*(јесењи|пролећни)\s*$",
    re.IGNORECASE,
)


def normalize_text(value) -> str:
    return " ".join(str(value or "").split())


def academic_year_label(start_year: int) -> str:
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def semester_display_name(start_year: int, season: str) -> str:
    return f"{academic_year_label(start_year)}. {season}"


def parse_academic_year_label(academic_year: str) -> int | None:
    normalized = normalize_text(academic_year)
    match = ACADEMIC_YEAR_RE.fullmatch(normalized)
    if match is None:
        return None

    start_year = int(match.group(1))
    expected_end_year = start_year + 1
    end_token = match.group(2)
    if len(end_token) == 2:
        if int(end_token) != expected_end_year % 100:
            return None
    elif int(end_token) != expected_end_year:
        return None
    return start_year


def parse_school_year_start_year(year: str) -> int | None:
    normalized = normalize_text(year)
    if not re.fullmatch(r"\d{4}", normalized):
        return None
    return int(normalized)


def parse_semester_display_name(name: str) -> tuple[int, str] | None:
    normalized = normalize_text(name)
    match = SEMESTER_NAME_RE.fullmatch(normalized)
    if match is None:
        return None

    start_year = int(match.group(1))
    expected_end_year = start_year + 1
    end_token = match.group(2)
    if len(end_token) == 2:
        if int(end_token) != expected_end_year % 100:
            return None
    elif int(end_token) != expected_end_year:
        return None
    season = match.group(3)
    return start_year, season


def semester_id_for_academic_year_and_season(cur, academic_year: str, season: str) -> int | None:
    start_year = parse_school_year_start_year(academic_year)
    if start_year is None:
        start_year = parse_academic_year_label(academic_year)
    if start_year is None:
        return None
    row = cur.execute(
        """
        SELECT id
        FROM semesters
        WHERE academic_year_start = ? AND season = ?
        """,
        (start_year, season),
    ).fetchone()
    return int(row[0]) if row is not None else None


def school_year_semester_ids(cur, academic_year: str) -> tuple[int | None, int | None]:
    return (
        semester_id_for_academic_year_and_season(cur, academic_year, "јесењи"),
        semester_id_for_academic_year_and_season(cur, academic_year, "пролећни"),
    )
