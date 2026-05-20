"""Poll VOX Cinemas Egypt for showtimes on a target weekday and notify via Telegram."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SHOWTIMES_URL = "https://egy.voxcinemas.com/showtimes?c={cinema}&m={movie}&d={date}"
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_STATE_PATH = Path(__file__).parent / "state.json"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

log = logging.getLogger("vox_notifier")


@dataclass(frozen=True)
class Config:
    """Runtime configuration loaded from environment variables."""
    cinema_slug: str
    movie_slug: str
    target_weekday: str
    timezone: str
    telegram_token: str
    telegram_chat_id: str


@dataclass(frozen=True)
class Showtime:
    """A single showtime entry parsed from the page."""
    time: str
    href: str


def load_config() -> Config:
    """Read and validate required env vars; raise on missing required ones."""
    required = {
        "CINEMA_SLUG": os.environ.get("CINEMA_SLUG"),
        "MOVIE_SLUG": os.environ.get("MOVIE_SLUG"),
        "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    weekday = (os.environ.get("TARGET_WEEKDAY") or "friday").strip().lower()
    if weekday not in WEEKDAYS:
        raise RuntimeError(f"TARGET_WEEKDAY must be one of {WEEKDAYS}, got {weekday!r}")

    return Config(
        cinema_slug=required["CINEMA_SLUG"],
        movie_slug=required["MOVIE_SLUG"],
        target_weekday=weekday,
        timezone=(os.environ.get("TIMEZONE") or "Africa/Cairo").strip(),
        telegram_token=required["TELEGRAM_BOT_TOKEN"],
        telegram_chat_id=required["TELEGRAM_CHAT_ID"],
    )


def next_target_date(weekday: str, tz: str, now: Optional[datetime] = None) -> date:
    """Return the next occurrence of `weekday` in `tz`; today if today already matches."""
    if now is None:
        now = datetime.now(ZoneInfo(tz))
    target_idx = WEEKDAYS.index(weekday.lower())
    today_idx = now.weekday()
    delta = (target_idx - today_idx) % 7
    return (now.date() + timedelta(days=delta))


def fetch_page(url: str, attempts: int = 3, timeout: int = 20) -> str:
    """GET `url` with a browser UA, retrying on network errors and 5xx."""
    last_err: Optional[Exception] = None
    for i in range(attempts):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if 500 <= r.status_code < 600:
                raise requests.HTTPError(f"server error {r.status_code}")
            r.raise_for_status()
            return r.text
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last_err = e
            backoff = 2 ** i
            log.warning("fetch attempt %d/%d failed: %s (sleeping %ds)", i + 1, attempts, e, backoff)
            if i < attempts - 1:
                time.sleep(backoff)
    raise RuntimeError(f"failed to fetch {url} after {attempts} attempts: {last_err}")


def parse_showtimes(html: str) -> "dict[str, list[Showtime]]":
    """Parse the showtimes page, returning {screen_type: [Showtime, ...]} preserving order.

    Returns an empty dict if no showtimes are present. If the expected container is
    missing entirely, logs a warning and returns an empty dict (treated as 'not yet').
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("ol", class_="showtimes")
    if container is None:
        log.warning("showtimes container not found — page structure may have changed")
        return {}

    groups: dict[str, list[Showtime]] = {}
    for group_li in container.find_all("li", recursive=False):
        label_el = group_li.find("strong")
        if not label_el:
            continue
        screen_type = label_el.get_text(strip=True)
        times: list[Showtime] = []
        for a in group_li.find_all("a", class_="action showtime"):
            text = a.get_text(strip=True)
            href = a.get("href", "").strip()
            if text and href:
                times.append(Showtime(time=text, href=href))
        if times:
            groups[screen_type] = times
    return groups


def extract_display_names(html: str, cinema_slug: str, movie_slug: str) -> "tuple[str, str]":
    """Pull movie title and cinema name from page meta/headings, with slug fallbacks."""
    soup = BeautifulSoup(html, "html.parser")

    movie = _title_from_slug(movie_slug)
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        movie = og["content"].strip()
    else:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            movie = h1.get_text(strip=True)

    cinema = _title_from_slug(cinema_slug)
    breadcrumb = soup.find(class_="cinema-name") or soup.find("h2")
    if breadcrumb and breadcrumb.get_text(strip=True):
        cinema = breadcrumb.get_text(strip=True)

    return movie, cinema


def _title_from_slug(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("_", "-").split("-"))


def format_message(movie: str, cinema: str, target_date: date,
                   groups: "dict[str, list[Showtime]]") -> str:
    """Format the HTML-mode Telegram message body."""
    date_str = f"{target_date:%A, %B} {target_date.day}, {target_date:%Y}"
    lines = [
        f"🎬 <b>{movie}</b> showtimes are live!",
        f"📍 {cinema}",
        f"📅 {date_str}",
    ]
    for screen_type, times in groups.items():
        lines.append("")
        lines.append(f"<b>{screen_type}</b>")
        for st in times:
            lines.append(f"• <a href=\"{st.href}\">{st.time}</a>")
    return "\n".join(lines)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    """POST a message to the Telegram Bot API; raise on failure."""
    r = requests.post(
        TELEGRAM_URL.format(token=token),
        json={
            "chat_id": chat_id,
            "parse_mode": "HTML",
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    if not r.ok:
        raise RuntimeError(f"Telegram API error {r.status_code}: {r.text}")
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API returned not-ok: {body}")


def load_state(path: Path) -> dict:
    """Read state.json, or return a fresh default if missing."""
    if not path.exists():
        return {"notified_for": None}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    """Persist state.json with a trailing newline."""
    path.write_text(json.dumps(state) + "\n", encoding="utf-8")


def main() -> int:
    """Orchestrate: load config → compute date → fetch → parse → dedupe → notify."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cfg = load_config()
    target = next_target_date(cfg.target_weekday, cfg.timezone)
    date_str = target.strftime("%Y%m%d")
    url = SHOWTIMES_URL.format(cinema=cfg.cinema_slug, movie=cfg.movie_slug, date=date_str)
    log.info("checking %s for %s at %s on %s", cfg.movie_slug, cfg.target_weekday, cfg.cinema_slug, date_str)
    log.info("URL: %s", url)

    html = fetch_page(url)
    groups = parse_showtimes(html)
    total = sum(len(v) for v in groups.values())

    if total == 0:
        log.info("No showtimes yet for %s", date_str)
        return 0

    log.info("Found %d showtimes across %d screen types: %s",
             total, len(groups), ", ".join(groups.keys()))

    state = load_state(DEFAULT_STATE_PATH)
    if state.get("notified_for") == date_str:
        log.info("Already notified for %s", date_str)
        return 0

    movie, cinema = extract_display_names(html, cfg.cinema_slug, cfg.movie_slug)
    text = format_message(movie, cinema, target, groups)
    send_telegram(cfg.telegram_token, cfg.telegram_chat_id, text)
    log.info("Telegram notification sent for %s", date_str)

    save_state(DEFAULT_STATE_PATH, {"notified_for": date_str})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        log.error("fatal: %s", e)
        sys.exit(1)
