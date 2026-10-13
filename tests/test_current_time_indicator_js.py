# Copyright (c) 2026 Filip Marić. See LICENCE.

from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "js"
    / "main.js"
)
CSS = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "css"
    / "base.css"
)


def test_current_time_indicator_uses_today_and_schedule_bounds():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "updateCurrentTimeIndicators" in source
    assert "const startMinutes = 8 * 60" in source
    assert "const endMinutes = 21 * 60" in source
    assert "date === today" in source
    assert "currentMinutes >= startMinutes && currentMinutes < endMinutes" in source


def test_current_time_indicator_updates_every_minute_and_on_resize():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "60 * 1000" in source
    assert 'window.addEventListener("resize"' in source
    assert 'classList.add("current-time-indicator")' in source


def test_current_time_indicator_does_not_capture_table_interactions():
    source = CSS.read_text(encoding="utf-8")

    assert ".current-time-indicator" in source
    assert "pointer-events: none" in source
