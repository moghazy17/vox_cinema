"""Unit tests for check_showtimes."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_showtimes import (  # noqa: E402
    SITES,
    Showtime,
    Watch,
    format_message,
    load_state,
    load_watches,
    next_target_date,
    parse_showtimes_scene,
    parse_showtimes_vox,
    resolve_target_date,
    scene_url,
    should_notify,
    vox_display_names,
    vox_empty_is_expected,
    vox_url,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ target dates


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


def test_resolve_target_date_fixed_date_ignores_clock():
    watch = Watch(id="w", site="vox", movie_slug="m", timezone="Africa/Cairo",
                  cinema_slug="c", target_date=date(2026, 8, 6))
    now = datetime(2026, 7, 27, 10, 0, tzinfo=ZoneInfo("Africa/Cairo"))
    assert resolve_target_date(watch, now=now) == date(2026, 8, 6)


def test_resolve_target_date_weekday_follows_clock():
    watch = Watch(id="w", site="scene", movie_slug="m", timezone="Africa/Cairo",
                  target_weekday="friday")
    now = datetime(2026, 7, 27, 10, 0, tzinfo=ZoneInfo("Africa/Cairo"))  # Monday
    assert resolve_target_date(watch, now=now) == date(2026, 7, 31)


# ------------------------------------------------------------------- scene parse


def test_parse_scene_no_showtimes_returns_empty():
    # An empty AJAX fragment means the date has no showtimes scheduled yet.
    assert parse_showtimes_scene(_read("scene_no_showtimes.html")) == {}
    assert parse_showtimes_scene("   \n  ") == {}


def test_parse_scene_groups_by_experience():
    groups = parse_showtimes_scene(_read("scene_with_showtimes.html"))
    assert list(groups.keys()) == ["IMAX", "Premiere", "Standard & Deluxe"]
    assert [s.time for s in groups["IMAX"]] == ["04:00 PM", "08:00 PM", "12:00 AM"]
    assert [s.time for s in groups["Standard & Deluxe"]] == ["04:00 PM"]


def test_parse_scene_marks_soldout_and_bookable():
    groups = parse_showtimes_scene(_read("scene_with_showtimes.html"))
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


# --------------------------------------------------------------------- vox parse


def test_parse_vox_no_showtimes_returns_empty():
    # VOX serves a full page with a notice rather than an empty body.
    html = _read("vox_no_showtimes.html")
    assert parse_showtimes_vox(html) == {}
    assert vox_empty_is_expected(html) is True


def test_vox_empty_is_expected_flags_unexpected_page():
    # No showtimes AND no notice → the page structure changed and we should warn.
    assert vox_empty_is_expected("<html><body><p>Something else entirely</p></body></html>") is False


def test_parse_vox_groups_by_screen_type():
    groups = parse_showtimes_vox(_read("vox_with_showtimes.html"))
    assert list(groups.keys()) == ["GOLD", "4DX", "Standard"]
    assert [s.time for s in groups["Standard"]] == ["1:45pm", "5:00pm", "8:15pm", "11:30pm"]


def test_parse_vox_treats_unavailable_spans_as_soldout():
    groups = parse_showtimes_vox(_read("vox_with_showtimes.html"))
    # GOLD/4DX are <span class="... unavailable"> — published but not bookable.
    assert all(s.soldout for s in groups["GOLD"])
    assert all(s.href == "" for s in groups["GOLD"])
    assert all(s.soldout for s in groups["4DX"])
    # Standard entries are real links.
    standard = groups["Standard"]
    assert all(not s.soldout for s in standard)
    assert standard[0].href == "https://egy.voxcinemas.com/booking/0047-266952"


def test_vox_display_names_from_page():
    watch = Watch(id="w", site="vox", movie_slug="spider-man-brand-new-day",
                  timezone="Africa/Cairo", cinema_slug="city-centre-almaza")
    movie, cinema = vox_display_names(_read("vox_with_showtimes.html"), watch)
    assert movie == "Spider-Man: Brand New Day"
    # Must be the cinema heading, not the "other movies you might like" h3.
    assert cinema == "City Centre Almaza"


def test_vox_display_names_ignore_footer_headings():
    """The footer's <h2>Stay in touch</h2> must never be mistaken for the movie title."""
    watch = Watch(id="w", site="vox", movie_slug="spider-man-brand-new-day",
                  timezone="Africa/Cairo", cinema_slug="city-centre-almaza")
    movie, _ = vox_display_names(_read("vox_no_showtimes.html"), watch)
    assert movie == "Spider Man Brand New Day"


def test_vox_display_names_fall_back_to_slugs():
    watch = Watch(id="w", site="vox", movie_slug="spider-man-brand-new-day",
                  timezone="Africa/Cairo", cinema_slug="city-centre-almaza")
    movie, cinema = vox_display_names("<html><body></body></html>", watch)
    assert movie == "Spider Man Brand New Day"
    assert cinema == "City Centre Almaza"


# ----------------------------------------------------------------------- url building


def test_url_builders_use_each_sites_date_format():
    scene = Watch(id="s", site="scene", movie_slug="the-odyssey", timezone="Africa/Cairo",
                  base_url="https://district5.scenecinemas.com/movie-details/the-odyssey.html",
                  target_weekday="friday")
    assert scene_url(scene, date(2026, 7, 31)) == (
        "https://district5.scenecinemas.com/movie-details/the-odyssey.html"
        "?business_day=31-07-2026&ajax=1"
    )

    vox = Watch(id="v", site="vox", movie_slug="spider-man-brand-new-day",
                timezone="Africa/Cairo", cinema_slug="city-centre-almaza",
                target_date=date(2026, 8, 6))
    assert vox_url(vox, date(2026, 8, 6)) == (
        "https://egy.voxcinemas.com/showtimes"
        "?c=city-centre-almaza&m=spider-man-brand-new-day&d=20260806"
    )


# -------------------------------------------------------------------------- watches


def _write_watches(tmp_path: Path, watches: list) -> Path:
    p = tmp_path / "watches.json"
    p.write_text(json.dumps({"watches": watches}), encoding="utf-8")
    return p


def test_load_watches_parses_both_target_kinds(tmp_path):
    path = _write_watches(tmp_path, [
        {"id": "a", "site": "scene", "movie_slug": "the-odyssey",
         "target": {"weekday": "friday"}},
        {"id": "b", "site": "vox", "movie_slug": "spider-man-brand-new-day",
         "cinema_slug": "city-centre-almaza", "target": {"date": "2026-08-06"}},
    ])
    a, b = load_watches(path, "Africa/Cairo")
    assert a.target_weekday == "friday" and a.target_date is None
    # scene base_url defaults and gets the movie slug substituted in.
    assert a.base_url.endswith("/movie-details/the-odyssey.html")
    assert b.target_date == date(2026, 8, 6) and b.target_weekday == ""
    assert b.timezone == "Africa/Cairo"


@pytest.mark.parametrize("entry,message", [
    ({"site": "scene", "movie_slug": "m", "target": {"weekday": "friday"}}, "missing 'id'"),
    ({"id": "a", "site": "netflix", "movie_slug": "m", "target": {"weekday": "friday"}}, "site must be"),
    ({"id": "a", "site": "vox", "movie_slug": "m", "target": {"weekday": "friday"}}, "requires 'cinema_slug'"),
    ({"id": "a", "site": "scene", "movie_slug": "m", "target": {}}, "exactly one of"),
    ({"id": "a", "site": "scene", "movie_slug": "m",
      "target": {"weekday": "friday", "date": "2026-08-06"}}, "exactly one of"),
    ({"id": "a", "site": "scene", "movie_slug": "m", "target": {"weekday": "funday"}}, "weekday must be"),
    ({"id": "a", "site": "scene", "movie_slug": "m", "target": {"date": "06-08-2026"}}, "must be YYYY-MM-DD"),
])
def test_load_watches_rejects_bad_config(tmp_path, entry, message):
    path = _write_watches(tmp_path, [entry])
    with pytest.raises(RuntimeError, match=message):
        load_watches(path, "Africa/Cairo")


def test_load_watches_rejects_duplicate_ids(tmp_path):
    path = _write_watches(tmp_path, [
        {"id": "dup", "site": "scene", "movie_slug": "m", "target": {"weekday": "friday"}},
        {"id": "dup", "site": "scene", "movie_slug": "n", "target": {"weekday": "friday"}},
    ])
    with pytest.raises(RuntimeError, match="duplicate id"):
        load_watches(path, "Africa/Cairo")


def test_repo_watches_file_is_valid():
    """The committed watches.json must actually load — it's what production runs on."""
    watches = load_watches(REPO_ROOT / "watches.json", "Africa/Cairo")
    by_id = {w.id: w for w in watches}
    assert "odyssey-d5-friday" in by_id, "the original Odyssey watch must stay configured"
    odyssey = by_id["odyssey-d5-friday"]
    assert odyssey.target_weekday == "friday"
    assert odyssey.site == "scene"
    assert odyssey.notify_on == "published", "Odyssey's original trigger must not change"

    # The VOX watches are fixed-date and get retired once their date passes, so
    # assert their shape rather than any one date — pinning a specific date here
    # fails the suite the moment a spent watch is cleaned out of watches.json.
    vox = [w for w in watches if w.site == "vox"]
    assert vox, "at least one VOX watch must stay configured"
    for w in vox:
        assert w.cinema_slug, f"{w.id}: VOX watches require a cinema_slug"
        assert w.notify_on == "bookable", f"{w.id}: VOX watches alert on bookable"


# ------------------------------------------------------------------ notify triggers


@pytest.mark.parametrize("total,bookable,expected", [
    (0, 0, False),   # nothing published yet
    (5, 0, True),    # published but not on sale — "published" doesn't care
    (5, 2, True),
])
def test_should_notify_published_fires_as_soon_as_anything_is_listed(total, bookable, expected):
    assert should_notify("published", total, bookable) is expected


@pytest.mark.parametrize("total,bookable,expected", [
    (0, 0, False),   # nothing published yet
    (5, 0, False),   # published but sales not open — keep waiting
    (5, 1, True),    # one bookable seat is enough
])
def test_should_notify_bookable_waits_for_sales_to_open(total, bookable, expected):
    assert should_notify("bookable", total, bookable) is expected


def test_bookable_watch_holds_off_on_an_all_unavailable_vox_page():
    """The real scenario: VOX lists the date but nothing is on sale yet."""
    groups = parse_showtimes_vox(_read("vox_with_showtimes.html"))
    # Drop the bookable Standard group — leaves only `unavailable` spans.
    listed_only = {k: v for k, v in groups.items() if k != "Standard"}
    total = sum(len(v) for v in listed_only.values())
    bookable = sum(1 for v in listed_only.values() for s in v if not s.soldout)
    assert total > 0 and bookable == 0
    assert should_notify("bookable", total, bookable) is False
    # ...and fires once anything opens up.
    assert should_notify("bookable", total + 1, 1) is True


def test_load_watches_defaults_notify_on_to_published(tmp_path):
    path = _write_watches(tmp_path, [
        {"id": "a", "site": "scene", "movie_slug": "m", "target": {"weekday": "friday"}},
    ])
    assert load_watches(path, "Africa/Cairo")[0].notify_on == "published"


def test_load_watches_rejects_bad_notify_on(tmp_path):
    path = _write_watches(tmp_path, [
        {"id": "a", "site": "scene", "movie_slug": "m", "target": {"weekday": "friday"},
         "notify_on": "whenever"},
    ])
    with pytest.raises(RuntimeError, match="notify_on must be"):
        load_watches(path, "Africa/Cairo")


# --------------------------------------------------------------------- message text


def test_message_uses_per_site_soldout_wording():
    """VOX's 'unavailable' covers not-yet-on-sale too, so it must not claim 'sold out'."""
    groups = {"GOLD": [Showtime(time="1:30pm", href="", soldout=True)]}
    vox_text = format_message("M", "C", date(2026, 8, 6), groups,
                              soldout_label=SITES["vox"].soldout_label)
    assert "(not bookable)" in vox_text and "sold out" not in vox_text

    scene_text = format_message("M", "C", date(2026, 8, 6), groups,
                                soldout_label=SITES["scene"].soldout_label)
    assert "(sold out)" in scene_text


def test_message_headline_defaults_are_backwards_compatible():
    """format_message must stay callable without the label/headline args."""
    groups = {"Standard": [Showtime(time="9:00pm", href="https://x/1")]}
    assert "showtimes are live!" in format_message("M", "C", date(2026, 8, 6), groups)


# ---------------------------------------------------------------------------- state


def test_load_state_migrates_legacy_flat_key(tmp_path):
    """Old state was a bare string for the single watch that existed then."""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"notified_for": "20260724"}), encoding="utf-8")
    watches = [
        Watch(id="odyssey-d5-friday", site="scene", movie_slug="m", timezone="Africa/Cairo",
              target_weekday="friday"),
        Watch(id="other", site="vox", movie_slug="m", timezone="Africa/Cairo", cinema_slug="c",
              target_date=date(2026, 8, 6)),
    ]
    assert load_state(p, watches) == {"notified_for": {"odyssey-d5-friday": "20260724"}}


def test_load_state_reads_per_watch_map(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"notified_for": {"a": "20260731", "b": None}}), encoding="utf-8")
    assert load_state(p, []) == {"notified_for": {"a": "20260731", "b": None}}


def test_load_state_missing_file_is_empty(tmp_path):
    assert load_state(tmp_path / "nope.json", []) == {"notified_for": {}}
