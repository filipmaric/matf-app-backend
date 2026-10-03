# Copyright (c) 2026 Filip Marić. See LICENCE.

from group_metadata import infer_group_metadata
from db import _ensure_group_metadata_schema
import sqlite3


def test_m_groups_use_module_and_default_accreditation():
    assert infer_group_metadata("2r") == ("M", "R", 2022, 2)
    assert infer_group_metadata("3ra") == ("M", "R", 2022, 3)
    assert infer_group_metadata("5m") == ("M", "M", 2022, 5)


def test_old_accreditation_is_read_from_15_suffix():
    assert infer_group_metadata("2m15") == ("M", "M", 2015, 2)
    assert infer_group_metadata("3af15") == ("A", "F", 2015, 3)
    assert infer_group_metadata("1i15") == ("I", None, 2015, 1)


def test_program_a_defaults_to_module_f():
    assert infer_group_metadata("1a") == ("A", "F", 2022, 1)
    assert infer_group_metadata("2af") == ("A", "F", 2022, 2)
    assert infer_group_metadata("2ai") == ("A", "I", 2022, 2)


def test_program_i_accreditations_and_special_first_year_m_groups():
    assert infer_group_metadata("2i171a") == ("I", None, 2017, 2)
    assert infer_group_metadata("3i172b") == ("I", None, 2017, 3)
    assert infer_group_metadata("4i1a") == ("I", None, 2017, 4)
    assert infer_group_metadata("4i2b") == ("I", None, 2017, 4)
    assert infer_group_metadata("5i") == ("I", None, 2019, 5)
    assert infer_group_metadata("5i1") == ("I", None, 2019, 5)
    assert infer_group_metadata("1o3") == ("M", None, 2022, 1)


def test_cyrillic_names_are_supported_and_special_groups_are_unknown():
    assert infer_group_metadata("2аф") == ("A", "F", 2022, 2)
    assert infer_group_metadata("semto") == (None, None, None, None)
    assert infer_group_metadata("bio") == (None, None, None, None)


def test_group_schema_migration_adds_and_populates_columns():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE groups (id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
    connection.executemany(
        "INSERT INTO groups (name) VALUES (?)",
        [("2i171a",), ("1o1",), ("semto",)],
    )

    _ensure_group_metadata_schema(connection)

    rows = connection.execute(
        "SELECT name, study_program, module, accreditation, study_year FROM groups ORDER BY id"
    ).fetchall()
    assert rows == [
        ("2i171a", "I", None, 2017, 2),
        ("1o1", "M", None, 2022, 1),
        ("semto", None, None, None, None),
    ]
