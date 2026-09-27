# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Shared calendar-day kinds and their timetable semantics."""

DAY_KINDS = frozenset({"teaching", "makeup", "exam", "colloquium", "non_working"})
SCHEDULE_DAY_KINDS = frozenset({"teaching", "makeup"})


def is_schedule_day(kind: str | None) -> bool:
    """Return whether a day participates in the regular weekly timetable."""
    return kind in SCHEDULE_DAY_KINDS


def validate_day_kind(kind: str) -> str:
    """Validate and return a calendar day kind."""
    if kind not in DAY_KINDS:
        allowed = ", ".join(sorted(DAY_KINDS))
        raise ValueError(f"invalid day kind {kind!r}; expected one of: {allowed}")
    return kind
