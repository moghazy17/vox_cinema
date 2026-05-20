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
    assert parse_showtimes(_read("no_showtimes.html")) == {}


def test_parse_single_screen():
    groups = parse_showtimes(_read("with_showtimes.html"))
    assert list(groups.keys()) == ["Standard"]
    times = [s.time for s in groups["Standard"]]
    assert times == ["12:00pm", "3:00pm", "6:00pm", "9:00pm"]
    assert groups["Standard"][0].href == "https://egy.voxcinemas.com/booking/0047-257273"


def test_parse_multi_screen_groups():
    groups = parse_showtimes(_read("multi_screen_showtimes.html"))
    assert list(groups.keys()) == ["Standard", "IMAX"]
    assert len(groups["Standard"]) == 4
    assert len(groups["IMAX"]) == 2
    assert [s.time for s in groups["IMAX"]] == ["2:00pm", "8:00pm"]
    assert groups["IMAX"][1].href == "https://egy.voxcinemas.com/booking/0047-257301"
