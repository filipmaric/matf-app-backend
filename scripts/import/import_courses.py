#!/usr/bin/env python3
# Copyright (c) 2026 Filip Marić. See LICENCE.

"""Import courses, subjects, and course-group memberships.

Each distinct group code from column B becomes one row in `courses`.
The `code` column is the group code itself.
The `name` column is derived from all distinct subject names attached to
that group in columns U onward.
The importer accepts the courses.xlsx workbook and the CSV
export produced by backend/scripts/export/export_courses.py.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from semester_utils import academic_year_label, parse_school_year_start_year, semester_id_for_academic_year_and_season

SHEETS = ("predmeti1sem", "predmeti2sem")
GROUP_CODE_COLUMN = 2  # B
SUBJECT_START_COLUMN = 21  # U
FULLY_ELECTIVE_STATUS = "потпуно изборни"


def normalize_text(value) -> str:
    return " ".join(str(value or "").split())


def parse_key_value_block(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def pick_first(parsed: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = normalize_text(parsed.get(key))
        if value:
            return value
    return None


def is_fully_elective_block(parsed: dict[str, str]) -> bool:
    return normalize_text(parsed.get("Статус")).casefold() == FULLY_ELECTIVE_STATUS.casefold()


def parse_subject_year(raw_year: str | None) -> int:
    """Parse the subject year encoded in a workbook block or CSV row."""
    normalized = normalize_text(raw_year)
    if not normalized:
        return 0

    if not normalized.isdigit():
        raise ValueError(f"Invalid subject year in subject block: {raw_year!r}")

    year = int(normalized)
    if year < 0 or year > 5:
        raise ValueError(f"Invalid subject year in subject block: {raw_year!r}")
    return year


def parse_student_count(raw_count: str | None) -> int | None:
    """Parse an aggregate student count from a subject block or CSV row."""
    normalized = normalize_text(raw_count)
    if not normalized or normalized.startswith("???") or normalized == "-":
        return None
    if not normalized.isdigit():
        raise ValueError(f"Invalid student count in subject block: {raw_count!r}")
    return int(normalized)


def parse_requires_computers(raw_value: str | None) -> int | None:
    normalized = normalize_text(raw_value)
    if not normalized:
        return None
    if normalized not in {"0", "1"}:
        raise ValueError(f"Invalid requires_computers value: {raw_value!r}")
    return int(normalized)


def parse_course_semester_label(label: str, semester_ids: tuple[int, int]) -> int:
    normalized = normalize_text(label).lower()
    if "јесењ" in normalized:
        return semester_ids[0]
    if "пролећ" in normalized:
        return semester_ids[1]
    raise ValueError(f"Invalid course semester label: {label!r}")


def ensure_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    has_courses = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'courses'"
    ).fetchone()
    if has_courses:
        return
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    conn.executescript(schema_path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class CourseGroupRecord:
    code: str
    name: str
    semester: int
    requires_computers: int | None
    subject_names: tuple[str, ...]
    source_locations: tuple[str, ...]
    subject_counts: tuple["SubjectStudentCount", ...] = ()


@dataclass(frozen=True)
class SubjectStudentCount:
    subject_code: str
    module: str
    accreditation: int
    semester: int
    student_count: int | None


def make_course_bucket(semester: int) -> dict[str, object]:
    return {
        "names": [],
        "seen": set(),
        "sources": [],
        "semester": semester,
        "course_name": None,
        "requires_computers": None,
        "subject_counts": {},
    }


def finalize_course_records(
    grouped: "OrderedDict[str, dict[str, object]]",
) -> list[CourseGroupRecord]:
    records: list[CourseGroupRecord] = []
    for code, bucket in grouped.items():
        names = [str(name) for name in bucket["names"]]
        explicit_course_name = normalize_text(bucket["course_name"])
        if explicit_course_name:
            course_name = explicit_course_name
        elif not names:
            course_name = code
        elif len(names) == 1:
            course_name = names[0]
        else:
            course_name = " / ".join(names)
        records.append(
            CourseGroupRecord(
                code=code,
                name=course_name,
                semester=int(bucket["semester"]),
                requires_computers=(
                    None
                    if bucket["requires_computers"] is None
                    else int(bucket["requires_computers"])
                ),
                subject_names=tuple(names),
                source_locations=tuple(str(source) for source in bucket["sources"]),
                subject_counts=tuple(bucket["subject_counts"].values()),
            )
        )
    return records


def register_course_item(
    grouped: "OrderedDict[str, dict[str, object]]",
    *,
    course_code: str,
    semester: int,
    source_location: str,
    subject_name: str | None = None,
    explicit_course_name: str | None = None,
    requires_computers: int | None = None,
) -> None:
    bucket = grouped.setdefault(course_code, make_course_bucket(semester))
    if int(bucket["semester"]) != semester:
        raise ValueError(
            f"Conflicting semester for course {course_code}: "
            f"{bucket['semester']} vs {semester}"
        )

    if explicit_course_name:
        normalized_course_name = normalize_text(explicit_course_name)
        if normalized_course_name:
            existing_course_name = normalize_text(bucket["course_name"])
            if existing_course_name and existing_course_name != normalized_course_name:
                raise ValueError(
                    f"Conflicting course name for course {course_code}: "
                    f"{existing_course_name!r} vs {normalized_course_name!r}"
                )
            bucket["course_name"] = normalized_course_name

    if requires_computers is not None:
        existing_requires = bucket["requires_computers"]
        if existing_requires is None:
            bucket["requires_computers"] = requires_computers
        else:
            bucket["requires_computers"] = int(existing_requires) or requires_computers

    if subject_name:
        names: list[str] = bucket["names"]  # type: ignore[assignment]
        seen: set[str] = bucket["seen"]  # type: ignore[assignment]
        normalized_subject_name = normalize_text(subject_name)
        if normalized_subject_name in seen:
            return
        seen.add(normalized_subject_name)
        names.append(normalized_subject_name)
        bucket["sources"].append(source_location)


def register_subject_student_count(
    grouped: "OrderedDict[str, dict[str, object]]",
    *,
    course_code: str,
    subject_code: str,
    module: str,
    accreditation: int,
    semester: int,
    student_count: int | None,
) -> None:
    """Remember one aggregate count for a subject-semester pair."""
    counts = grouped[course_code]["subject_counts"]
    key = (subject_code, module, accreditation)
    existing = counts.get(key)
    if existing is None or existing.student_count is None:
        counts[key] = SubjectStudentCount(
            subject_code=subject_code,
            module=module,
            accreditation=accreditation,
            semester=semester,
            student_count=student_count,
        )


def register_subject_and_membership(
    subjects: dict[tuple[str, int, str], SubjectRecord],
    memberships: dict[tuple[str, str, int], CourseGroupMembership],
    membership_locations: dict[tuple[str, str, int], str],
    duplicate_counts: dict[tuple[str, str, int], int],
    duplicate_groups: dict[tuple[str, str, int], set[str]],
    *,
    course_code: str,
    subject_code: str,
    module: str,
    accreditation: int,
    subject_name: str,
    subject_year: int,
    source_location: str,
) -> None:
    subject_key = (subject_code, accreditation, module)
    existing_subject = subjects.get(subject_key)
    if existing_subject is None or (existing_subject.year == 0 and subject_year != 0):
        subjects[subject_key] = SubjectRecord(
            code=subject_code,
            name=subject_name,
            accreditation=accreditation,
            module=module,
            year=subject_year,
        )
    membership_key = (subject_code, module, accreditation)
    if membership_key in membership_locations:
        duplicate_counts[membership_key] = duplicate_counts.get(membership_key, 0) + 1
        duplicate_groups.setdefault(membership_key, set()).add(course_code)
        return
    memberships[membership_key] = CourseGroupMembership(
        group_code=course_code,
        subject_code=subject_code,
        module=module,
        accreditation=accreditation,
    )
    membership_locations[membership_key] = source_location


def finalize_import_result(
    grouped: "OrderedDict[str, dict[str, object]]",
    subjects: dict[tuple[str, int, str], SubjectRecord],
    memberships: dict[tuple[str, str, int], CourseGroupMembership],
    membership_locations: dict[tuple[str, str, int], str],
    duplicate_counts: dict[tuple[str, str, int], int],
    duplicate_groups: dict[tuple[str, str, int], set[str]],
) -> tuple[
    list[CourseGroupRecord],
    list[SubjectRecord],
    list[CourseGroupMembership],
    list[DuplicateMembershipSummary],
]:
    records = finalize_course_records(grouped)
    duplicate_summaries = [
        DuplicateMembershipSummary(
            course_code=course_code,
            module=module,
            accreditation=accreditation,
            first_group_code=memberships[(course_code, module, accreditation)].group_code,
            first_location=membership_locations[(course_code, module, accreditation)],
            duplicate_count=duplicate_counts[(course_code, module, accreditation)],
            duplicate_group_codes=tuple(sorted(duplicate_groups[(course_code, module, accreditation)])),
        )
        for course_code, module, accreditation in sorted(duplicate_counts)
    ]
    return records, list(subjects.values()), list(memberships.values()), duplicate_summaries


@dataclass(frozen=True)
class SubjectRecord:
    code: str
    name: str
    accreditation: int
    module: str
    year: int


@dataclass(frozen=True)
class CourseGroupMembership:
    group_code: str
    subject_code: str
    module: str
    accreditation: int


@dataclass(frozen=True)
class DuplicateMembershipSummary:
    course_code: str
    module: str
    accreditation: int
    first_group_code: str
    first_location: str
    duplicate_count: int
    duplicate_group_codes: tuple[str, ...]


def build_course_groups_from_workbook(
    workbook_path: Path,
    academic_year: str,
    semester_ids: tuple[int, int],
) -> tuple[
    list[CourseGroupRecord],
    list[SubjectRecord],
    list[CourseGroupMembership],
    list[DuplicateMembershipSummary],
]:
    workbook = load_workbook(workbook_path, data_only=True, read_only=True)
    grouped: "OrderedDict[str, dict[str, object]]" = OrderedDict()
    subjects: dict[tuple[str, int, str], SubjectRecord] = {}
    memberships: dict[tuple[str, str, int], CourseGroupMembership] = {}
    membership_locations: dict[tuple[str, str, int], str] = {}
    duplicate_counts: dict[tuple[str, str, int], int] = {}
    duplicate_groups: dict[tuple[str, str, int], set[str]] = {}
    sheet_semesters = {
        "predmeti1sem": semester_ids[0],
        "predmeti2sem": semester_ids[1],
    }

    for sheet_name in SHEETS:
        ws = workbook[sheet_name]
        semester = sheet_semesters[sheet_name]
        for row_number, row in enumerate(ws.iter_rows(min_row=3, values_only=True), start=3):
            if len(row) < SUBJECT_START_COLUMN:
                continue
            group_code = normalize_text(row[GROUP_CODE_COLUMN - 1])
            for column in range(SUBJECT_START_COLUMN, len(row) + 1):
                raw_text = row[column - 1]
                if raw_text in (None, ""):
                    continue
                parsed = parse_key_value_block(raw_text)
                if is_fully_elective_block(parsed):
                    continue
                subject_name = pick_first(parsed, "Назив")
                subject_code = pick_first(parsed, "Шифра")
                module = pick_first(parsed, "Модул")
                accreditation = pick_first(parsed, "Акредитација")
                subject_year = pick_first(parsed, "Година")
                student_count = parse_student_count(pick_first(parsed, "Студената"))
                if subject_name is None:
                    continue
                year = parse_subject_year(subject_year)
                if not group_code or not subject_code or not module or not accreditation:
                    continue
                if not accreditation.isdigit():
                    continue
                accreditation_year = int(accreditation)
                location = f"{sheet_name}:{row_number}:{get_column_letter(column)}"
                register_course_item(
                    grouped,
                    course_code=group_code,
                    semester=semester,
                    source_location=location,
                    subject_name=subject_name,
                )
                register_subject_student_count(
                    grouped,
                    course_code=group_code,
                    subject_code=subject_code,
                    module=module,
                    accreditation=accreditation_year,
                    semester=semester,
                    student_count=student_count,
                )
                register_subject_and_membership(
                    subjects,
                    memberships,
                    membership_locations,
                    duplicate_counts,
                    duplicate_groups,
                    course_code=group_code,
                    subject_code=subject_code,
                    module=module,
                    accreditation=accreditation_year,
                    subject_name=subject_name,
                    subject_year=year,
                    source_location=location,
                )

    return finalize_import_result(
        grouped,
        subjects,
        memberships,
        membership_locations,
        duplicate_counts,
        duplicate_groups,
    )


def build_course_groups_from_csv(
    csv_path: Path,
    academic_year: str,
    semester_ids: tuple[int, int],
) -> tuple[
    list[CourseGroupRecord],
    list[SubjectRecord],
    list[CourseGroupMembership],
    list[DuplicateMembershipSummary],
]:
    grouped: "OrderedDict[str, dict[str, object]]" = OrderedDict()
    subjects: dict[tuple[str, int, str], SubjectRecord] = {}
    memberships: dict[tuple[str, str, int], CourseGroupMembership] = {}
    membership_locations: dict[tuple[str, str, int], str] = {}
    duplicate_counts: dict[tuple[str, str, int], int] = {}
    duplicate_groups: dict[tuple[str, str, int], set[str]] = {}

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        expected_columns = {
            "course_code",
            "course_name",
            "course_semester",
            "subject_code",
            "subject_name",
            "subject_accreditation",
            "subject_module",
            "subject_year",
        }
        if reader.fieldnames is None or not expected_columns.issubset(set(reader.fieldnames)):
            raise ValueError(
                "CSV input does not look like the exported courses file "
                f"({csv_path})"
            )
        for line_number, row in enumerate(reader, start=2):
            course_code = normalize_text(row.get("course_code"))
            course_name = normalize_text(row.get("course_name"))
            course_semester = row.get("course_semester", "")
            requires_computers = parse_requires_computers(row.get("requires_computers"))
            if not course_code:
                continue
            semester = parse_course_semester_label(course_semester, semester_ids)
            source_location = f"{csv_path.name}:{line_number}"
            register_course_item(
                grouped,
                course_code=course_code,
                semester=semester,
                source_location=source_location,
                explicit_course_name=course_name,
                requires_computers=requires_computers,
            )
            subject_code = normalize_text(row.get("subject_code"))
            subject_name = normalize_text(row.get("subject_name"))
            module = normalize_text(row.get("subject_module"))
            accreditation = normalize_text(row.get("subject_accreditation"))
            subject_year = row.get("subject_year")
            student_count = parse_student_count(row.get("student_count"))
            if not subject_code or not subject_name or not accreditation:
                continue
            if not accreditation.isdigit():
                continue
            register_subject_student_count(
                grouped,
                course_code=course_code,
                subject_code=subject_code,
                module=module,
                accreditation=int(accreditation),
                semester=semester,
                student_count=student_count,
            )
            register_subject_and_membership(
                subjects,
                memberships,
                membership_locations,
                duplicate_counts,
                duplicate_groups,
                course_code=course_code,
                subject_code=subject_code,
                module=module,
                accreditation=int(accreditation),
                subject_name=subject_name,
                subject_year=parse_subject_year(subject_year),
                source_location=source_location,
            )

    return finalize_import_result(
        grouped,
        subjects,
        memberships,
        membership_locations,
        duplicate_counts,
        duplicate_groups,
    )


def prune_unreferenced_subjects(conn: sqlite3.Connection) -> int:
    with conn:
        cur = conn.cursor()
        subject_ids = [
            row[0]
            for row in cur.execute(
                """
                SELECT id
                FROM subjects
                WHERE id NOT IN (
                    SELECT DISTINCT subject_id
                    FROM course_subjects
                    WHERE subject_id IS NOT NULL
                )
                """
            ).fetchall()
        ]
        if not subject_ids:
            return 0
        placeholders = ",".join("?" for _ in subject_ids)
        cur.execute(
            f"DELETE FROM subjects WHERE id IN ({placeholders})",
            tuple(subject_ids),
        )
        return cur.rowcount


def build_course_groups(
    input_path: Path,
    academic_year: str,
    semester_ids: tuple[int, int],
) -> tuple[
    list[CourseGroupRecord],
    list[SubjectRecord],
    list[CourseGroupMembership],
    list[DuplicateMembershipSummary],
]:
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        return build_course_groups_from_csv(input_path, academic_year, semester_ids)
    if suffix in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return build_course_groups_from_workbook(input_path, academic_year, semester_ids)
    raise ValueError(f"Unsupported input format: {input_path}")


def upsert_courses(
    conn: sqlite3.Connection,
    records: list[CourseGroupRecord],
) -> tuple[int, int, int]:
    inserted = 0
    updated = 0
    unchanged = 0
    with conn:
        cur = conn.cursor()
        for record in records:
            rows = cur.execute(
                "SELECT id, name, semester, requires_computers FROM courses WHERE code = ? ORDER BY id",
                (record.code,),
            ).fetchall()
            if len(rows) > 1:
                raise ValueError(f"Multiple existing course rows found for code {record.code}")
            if not rows:
                requires_computers = 0 if record.requires_computers is None else int(record.requires_computers)
                cur.execute(
                    "INSERT INTO courses (name, code, semester, requires_computers) VALUES (?, ?, ?, ?)",
                    (record.name, record.code, record.semester, requires_computers),
                )
                inserted += 1
                continue
            course_id, existing_name, existing_semester, existing_requires = rows[0]
            updates = []
            params = []
            if existing_name != record.name:
                updates.append("name = ?")
                params.append(record.name)
            if int(existing_semester) != record.semester:
                updates.append("semester = ?")
                params.append(record.semester)
            if record.requires_computers is not None and int(existing_requires) != record.requires_computers:
                updates.append("requires_computers = ?")
                params.append(record.requires_computers)
            if not updates:
                unchanged += 1
                continue
            params.append(course_id)
            cur.execute(
                f"UPDATE courses SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            updated += 1
    return inserted, updated, unchanged


def upsert_subjects(
    conn: sqlite3.Connection,
    subjects: list[SubjectRecord],
) -> dict[tuple[str, int, str], int]:
    ids: dict[tuple[str, int, str], int] = {}
    with conn:
        cur = conn.cursor()
        for subject in subjects:
            row = cur.execute(
                """
                SELECT id, name, year
                FROM subjects
                WHERE code = ? AND accreditation = ? AND module = ?
                """,
                (subject.code, subject.accreditation, subject.module),
            ).fetchone()
            if row is None:
                cur.execute(
                    """
                    INSERT INTO subjects (code, name, accreditation, module, year)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        subject.code,
                        subject.name,
                        subject.accreditation,
                        subject.module,
                        subject.year,
                    ),
                )
                ids[(subject.code, subject.accreditation, subject.module)] = int(cur.lastrowid)
                continue
            subject_id, existing_name, existing_year = row
            ids[(subject.code, subject.accreditation, subject.module)] = int(subject_id)
            if existing_name != subject.name or int(existing_year) != subject.year:
                cur.execute(
                    "UPDATE subjects SET name = ?, year = ? WHERE id = ?",
                    (subject.name, subject.year, subject_id),
                )
    return ids


def sync_course_subjects(
    conn: sqlite3.Connection,
    records: list[CourseGroupRecord],
    memberships: list[CourseGroupMembership],
    subject_ids: dict[tuple[str, int, str], int],
) -> int:
    inserted = 0
    course_codes = {record.code for record in records}
    with conn:
        cur = conn.cursor()
        if course_codes:
            placeholders = ",".join("?" for _ in course_codes)
            cur.execute(
                f"DELETE FROM course_subjects WHERE course_code IN ({placeholders})",
                tuple(sorted(course_codes)),
            )
        for membership in memberships:
            if membership.group_code not in course_codes:
                continue
            subject_id = subject_ids.get(
                (membership.subject_code, membership.accreditation, membership.module)
            )
            if subject_id is None:
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO course_subjects (course_code, subject_id)
                VALUES (?, ?)
                """,
                (membership.group_code, subject_id),
            )
            inserted += cur.rowcount
    return inserted


def sync_subject_student_counts(
    conn: sqlite3.Connection,
    records: list[CourseGroupRecord],
    subject_ids: dict[tuple[str, int, str], int],
) -> int:
    """Replace imported aggregate counts for the subjects in this workbook."""
    count_rows = [count for record in records for count in record.subject_counts]
    target_semesters = sorted({record.semester for record in records})
    with conn:
        cur = conn.cursor()
        if target_semesters:
            semester_placeholders = ",".join("?" for _ in target_semesters)
            cur.execute(
                f"""
                DELETE FROM subject_student_counts
                WHERE semester_id IN ({semester_placeholders})
                """,
                tuple(target_semesters),
            )
        values = {}
        for count in count_rows:
            subject_id = subject_ids.get(
                (count.subject_code, count.accreditation, count.module)
            )
            if subject_id is None:
                continue
            key = (subject_id, count.semester)
            if key not in values or values[key] is None:
                values[key] = count.student_count
        inserted = 0
        for (subject_id, semester_id), student_count in values.items():
            cur.execute(
                """
                INSERT INTO subject_student_counts
                    (subject_id, semester_id, student_count)
                VALUES (?, ?, ?)
                """,
                (subject_id, semester_id, student_count),
            )
            inserted += cur.rowcount
    return inserted


def clear_missing_course_semesters(
    conn: sqlite3.Connection,
    records: list[CourseGroupRecord],
) -> int:
    target_codes = sorted({record.code for record in records if record.code})
    target_semesters = sorted({record.semester for record in records})
    if not target_codes or not target_semesters:
        return 0

    semester_placeholders = ",".join("?" for _ in target_semesters)
    code_placeholders = ",".join("?" for _ in target_codes)
    with conn:
        cur = conn.cursor()
        course_ids = [
            row[0]
            for row in cur.execute(
                f"""
                SELECT id
                FROM courses
                WHERE semester IN ({semester_placeholders})
                  AND (code IS NULL OR code NOT IN ({code_placeholders}))
                """,
                (*target_semesters, *target_codes),
            ).fetchall()
        ]
        if course_ids:
            course_id_placeholders = ",".join("?" for _ in course_ids)
            cur.execute(
                f"""
                DELETE FROM weekly_sessions
                WHERE session_id IN (
                    SELECT id FROM course_sessions
                    WHERE course_id IN ({course_id_placeholders})
                )
                """,
                tuple(course_ids),
            )
            cur.execute(
                f"""
                DELETE FROM session_groups
                WHERE session_id IN (
                    SELECT id FROM course_sessions
                    WHERE course_id IN ({course_id_placeholders})
                )
                """,
                tuple(course_ids),
            )
            cur.execute(
                f"DELETE FROM course_sessions WHERE course_id IN ({course_id_placeholders})",
                tuple(course_ids),
            )
        deleted_courses = 0
        if course_ids:
            cur.execute(
                f"DELETE FROM courses WHERE id IN ({','.join('?' for _ in course_ids)})",
                tuple(course_ids),
            )
            deleted_courses = cur.rowcount
    return deleted_courses


def write_csv(path: Path, records: list[CourseGroupRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "name", "subject_names", "source_locations"])
        for record in records:
            writer.writerow(
                [
                    record.code,
                    record.name,
                    " / ".join(record.subject_names),
                    " | ".join(record.source_locations),
                ]
            )


def report_duplicates(duplicates: list[DuplicateMembershipSummary]) -> None:
    if not duplicates:
        return
    total_extra_occurrences = sum(duplicate.duplicate_count for duplicate in duplicates)
    print(f"DUPLICATE_PAIRS={len(duplicates)}", file=sys.stderr)
    print(f"DUPLICATE_OCCURRENCES={total_extra_occurrences}", file=sys.stderr)
    for duplicate in duplicates:
        print(
            "DUPLICATE\t"
            f"course_code={duplicate.course_code}\t"
            f"module={duplicate.module}\t"
            f"accreditation={duplicate.accreditation}\t"
            f"first_group={duplicate.first_group_code}\t"
            f"first_location={duplicate.first_location}\t"
            f"duplicate_count={duplicate.duplicate_count}\t"
            f"duplicate_groups={','.join(duplicate.duplicate_group_codes)}",
            file=sys.stderr,
        )


def ensure_required_tables(conn: sqlite3.Connection, schema_path: Path) -> None:
    ensure_schema(conn, schema_path)
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_code_unique
            ON courses(code);
        """
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS subject_student_counts (
            subject_id INTEGER NOT NULL,
            semester_id INTEGER NOT NULL,
            student_count INTEGER,
            PRIMARY KEY (subject_id, semester_id),
            CHECK (student_count IS NULL OR student_count >= 0),
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
            FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_subject_student_counts_semester
            ON subject_student_counts(semester_id, subject_id);
        """
    )
    conn.commit()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import subjects, courses, and course groups from courses.xlsx or the exported CSV."
    )
    parser.add_argument(
        "--input",
        "--workbook",
        dest="input",
        required=True,
        help="Path to courses.xlsx or exported courses CSV",
    )
    parser.add_argument(
        "--year",
        required=True,
        help="School year start year like 2026",
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
        "--csv-output",
        help="Optional CSV output path for reviewing the derived course groups",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Derive the rows but do not write to the database",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    database_path = Path(args.database)
    schema_path = Path(args.schema)

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    start_year = parse_school_year_start_year(args.year)
    if start_year is None:
        print(f"Invalid year: {args.year!r}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(database_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        ensure_required_tables(conn, schema_path)
        cur = conn.cursor()
        fall_semester_id = semester_id_for_academic_year_and_season(cur, start_year, "јесењи")
        spring_semester_id = semester_id_for_academic_year_and_season(cur, start_year, "пролећни")
        if fall_semester_id is None or spring_semester_id is None:
            raise ValueError(f"Missing semesters for academic year: {academic_year_label(start_year)!r}")
        semester_ids = (fall_semester_id, spring_semester_id)
        records, subjects, memberships, duplicates = build_course_groups(
            input_path,
            start_year,
            semester_ids,
        )
        if not records:
            print("No course groups found.", file=sys.stderr)
            return 1

        if args.csv_output:
            write_csv(Path(args.csv_output), records)

        if args.dry_run:
            report_duplicates(duplicates)
            for record in records:
                print(f"{record.code}\t{record.name}")
            print(f"ROWS={len(records)}")
            return 0

        cleared_courses = clear_missing_course_semesters(conn, records)
        subject_ids = upsert_subjects(conn, subjects)
        inserted, updated, unchanged = upsert_courses(conn, records)
        normalized_rows = sync_course_subjects(conn, records, memberships, subject_ids)
        subject_student_count_rows = sync_subject_student_counts(conn, records, subject_ids)
        pruned_subjects = prune_unreferenced_subjects(conn)
    finally:
        conn.close()

    report_duplicates(duplicates)
    print(f"YEAR={start_year}")
    print(f"ACADEMIC_YEAR={academic_year_label(start_year)}")
    print(f"SEMESTER={academic_year_label(start_year)}. јесењи")
    print(f"SEMESTER={academic_year_label(start_year)}. пролећни")
    print(f"ROWS={len(records)}")
    print(f"SUBJECTS={len(subjects)}")
    print(f"MEMBERSHIPS={len(memberships)}")
    print(f"CLEARED_COURSES={cleared_courses}")
    print(f"PRUNED_SUBJECTS={pruned_subjects}")
    print(f"INSERTED={inserted}")
    print(f"UPDATED={updated}")
    print(f"UNCHANGED={unchanged}")
    print(f"COURSE_SUBJECTS_INSERTED={normalized_rows}")
    print(f"SUBJECT_STUDENT_COUNTS_INSERTED={subject_student_count_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
