# Copyright (c) 2026 Filip Marić. See LICENCE.
"""Shared room classifications."""

TEACHER_OFFICE_ROOM_TYPE = "teacher_office"


def is_reservable_room(room_type: str | None) -> bool:
    """Return whether a room may be used for room reservations."""
    return room_type != TEACHER_OFFICE_ROOM_TYPE
