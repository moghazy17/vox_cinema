"""Unit tests for check_showtimes."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_showtimes import next_target_date, parse_showtimes  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_next_target_date_when_today_is_target():
    # 2026-05-22 is a Friday in Africa/Cairo.
    now = datetime(2026, 5, 22, 10, 0, tzinfo=ZoneInfo("Africa/Cairo"))
    assert next_target_date("friday", "Africa/Cairo", now=now).isoformat() == "2026-05-22"


def test_next_target_date_when_target_is_future():
    # 2026-05-20 is a Wednesday → next Friday is 2026-05-22.
    now = datetime(2026, 5, 20, 10, 0, tzinfo=ZoneInfo("Africa/Cairo"))
    assert next_target_date("friday", "Africa/Cairo", now=now).isoformat() == "2026-05-22"
    # Saturday from Wednesday → 2026-05-23.
    assert next_target_date("saturday", "Africa/Cairo", now=now).isoformat() == "2026-05-23"


def test_parse_no_showtimes_returns_empty():
    # An empty AJAX fragment means the date has no showtimes scheduled yet.
    assert parse_showtimes(_read("scene_no_showtimes.html")) == {}
    assert parse_showtimes("   \n  ") == {}


def test_parse_groups_by_experience():
    groups = parse_showtimes(_read("scene_with_showtimes.html"))
    assert list(groups.keys()) == ["IMAX", "Premiere", "Standard & Deluxe"]
    assert [s.time for s in groups["IMAX"]] == ["04:00 PM", "08:00 PM", "12:00 AM"]
    assert [s.time for s in groups["Standard & Deluxe"]] == ["04:00 PM"]


def test_parse_marks_soldout_and_bookable():
    groups = parse_showtimes(_read("scene_with_showtimes.html"))
    imax = {s.time: s for s in groups["IMAX"]}
    # 08:00 PM has a real booking link; the others are struck-through / void hrefs.
    assert imax["08:00 PM"].soldout is False
    assert imax["08:00 PM"].href.startswith("https://district5.scenecinemas.com/showtime-")
    assert imax["04:00 PM"].soldout is True
    assert imax["12:00 AM"].soldout is True
    # Premiere is entirely sold out.
    assert all(s.soldout for s in groups["Premiere"])
    # Standard & Deluxe 04:00 PM is bookable.
    assert groups["Standard & Deluxe"][0].soldout is False
