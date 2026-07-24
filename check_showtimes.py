"""Poll Scene Cinemas (District 5) for showtimes on a target weekday and notify via Telegram.

Scene Cinemas exposes a rolling window of dates on the movie-details page. Each date's
showtimes are loaded via an AJAX fragment:

    https://district5.scenecinemas.com/movie-details/<movie>.html?business_day=DD-MM-YYYY&ajax=1

A date that has no showtimes yet (e.g. a future date beyond the published window) returns
an empty body. So "the target Friday is available" == "the fragment for that date contains
showtimes". We fetch the fragment for the next target weekday, parse it, and notify once.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

# {base} is the movie-details URL; {date} is DD-MM-YYYY.
SHOWTIMES_URL = "{base}?business_day={date}&ajax=1"
DEFAULT_MOVIE_BASE = "https://district5.scenecinemas.com/movie-details/{movie}.html"
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}
DEFAULT_STATE_PATH = Path(__file__).parent / "state.json"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

log = logging.getLogger("scene_notifier")


@dataclass(frozen=True)
class Config:
    """Runtime configuration loaded from environment variables."""
    movie_slug: str
    movie_base: str
    target_weekday: str
    timezone: str
    telegram_token: str
    telegram_chat_id: str


@dataclass(frozen=True)
class Showtime:
    """A single showtime entry parsed from the page."""
    time: str
    href: str
    soldout: bool = False


def load_config() -> Config:
    """Read and validate required env vars; raise on missing required ones."""
    required = {
        "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    weekday = (os.environ.get("TARGET_WEEKDAY") or "friday").strip().lower()
    if weekday not in WEEKDAYS:
        raise RuntimeError(f"TARGET_WEEKDAY must be one of {WEEKDAYS}, got {weekday!r}")

    movie_slug = (os.environ.get("MOVIE_SLUG") or "the-odyssey").strip()
    movie_base = (os.environ.get("MOVIE_BASE_URL") or DEFAULT_MOVIE_BASE).strip()
    if "{movie}" in movie_base:
        movie_base = movie_base.format(movie=movie_slug)

    return Config(
        movie_slug=movie_slug,
        movie_base=movie_base,
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
    """GET `url` impersonating Chrome's TLS fingerprint; retry on network errors and 5xx.

    The site's WAF rejects plain `requests`/`urllib3` TLS handshakes, so we use curl_cffi.
    """
    last_err: Optional[Exception] = None
    for i in range(attempts):
        try:
            r = cffi_requests.get(
                url, headers=BROWSER_HEADERS, timeout=timeout, impersonate="chrome124"
            )
            if 500 <= r.status_code < 600:
                raise RuntimeError(f"server error {r.status_code}")
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
            return r.text
        except Exception as e:  # noqa: BLE001 — curl_cffi raises its own errors
            last_err = e
            backoff = 2 ** i
            log.warning("fetch attempt %d/%d failed: %s (sleeping %ds)", i + 1, attempts, e, backoff)
            if i < attempts - 1:
                time.sleep(backoff)
    raise RuntimeError(f"failed to fetch {url} after {attempts} attempts: {last_err}")


def parse_showtimes(html: str) -> "dict[str, list[Showtime]]":
    """Parse the Scene Cinemas AJAX fragment, returning {screen_type: [Showtime, ...]}.

    Showtimes are grouped by an experience label span (e.g. `IMAX`, `Premiere`,
    `Standard & Deluxe`) whose class starts with `ex_`. Sold-out entries carry the
    `showtime_soldout` class and a `javascript:void(0)` href. Returns an empty dict when
    the fragment is empty (no showtimes scheduled yet for that date).
    """
    text = html.strip()
    if not text:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    groups: dict[str, list[Showtime]] = {}

    # Each experience label is a <span class="ex_imax|ex_vip|ex_stand|...">. The content
    # wrapper divs are `ex_*_content`, so exclude those to keep only label spans.
    label_spans = soup.find_all(
        "span", class_=lambda c: bool(c) and any(
            cls.startswith("ex_") and not cls.endswith("_content") for cls in c.split()
        )
    )
    for span in label_spans:
        label = span.get_text(strip=True)
        if not label:
            continue
        container = span.find_parent("div")
        if container is None:
            continue
        for a in container.select("ul li a"):
            time_text = a.get_text(strip=True)
            if not time_text:
                continue
            classes = a.get("class") or []
            href = (a.get("href") or "").strip()
            soldout = "showtime_soldout" in classes or href.lower().startswith("javascript:")
            groups.setdefault(label, []).append(
                Showtime(time=time_text, href=href, soldout=soldout)
            )
    return groups


def extract_display_names(html: str, movie_slug: str) -> "tuple[str, str]":
    """Return (movie_title, cinema_name); cinema comes from the fragment's branch label."""
    movie = _title_from_slug(movie_slug)

    cinema = "Scene Cinemas — District 5"
    soup = BeautifulSoup(html, "html.parser")
    branch = soup.find(class_="branch")
    if branch and branch.get_text(strip=True):
        cinema = re.sub(r"\s+", " ", branch.get_text(strip=True)).strip()

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
            if st.soldout:
                lines.append(f"• <s>{st.time}</s> (sold out)")
            elif st.href:
                lines.append(f"• <a href=\"{st.href}\">{st.time}</a>")
            else:
                lines.append(f"• {st.time}")
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
    business_day = target.strftime("%d-%m-%Y")   # Scene Cinemas date format
    dedupe_key = target.strftime("%Y%m%d")       # internal, sortable state key
    url = SHOWTIMES_URL.format(base=cfg.movie_base, date=business_day)
    log.info("checking %s for %s on %s", cfg.movie_slug, cfg.target_weekday, business_day)
    log.info("URL: %s", url)

    html = fetch_page(url)
    groups = parse_showtimes(html)
    total = sum(len(v) for v in groups.values())

    if total == 0:
        log.info("No showtimes yet for %s", business_day)
        return 0

    bookable = sum(1 for v in groups.values() for s in v if not s.soldout)
    log.info("Found %d showtimes (%d bookable) across %d screen types: %s",
             total, bookable, len(groups), ", ".join(groups.keys()))

    state = load_state(DEFAULT_STATE_PATH)
    if state.get("notified_for") == dedupe_key:
        log.info("Already notified for %s", dedupe_key)
        return 0

    movie, cinema = extract_display_names(html, cfg.movie_slug)
    text = format_message(movie, cinema, target, groups)
    send_telegram(cfg.telegram_token, cfg.telegram_chat_id, text)
    log.info("Telegram notification sent for %s", dedupe_key)

    save_state(DEFAULT_STATE_PATH, {"notified_for": dedupe_key})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        log.error("fatal: %s", e)
        sys.exit(1)
