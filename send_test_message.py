"""One-shot helper: send a sample Telegram message to verify bot setup.

Usage (PowerShell):
    $env:TELEGRAM_BOT_TOKEN = "..."
    $env:TELEGRAM_CHAT_ID   = "..."
    python send_test_message.py

Exits 0 on success, 1 on any failure.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date

from check_showtimes import Showtime, format_message, send_telegram

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars first.", file=sys.stderr)
        return 1

    sample_groups = {
        "Standard": [
            Showtime(time="12:00pm", href="https://egy.voxcinemas.com/booking/0047-test1"),
            Showtime(time="3:00pm",  href="https://egy.voxcinemas.com/booking/0047-test2"),
            Showtime(time="9:00pm",  href="https://egy.voxcinemas.com/booking/0047-test3"),
        ],
        "IMAX": [
            Showtime(time="6:00pm",  href="https://egy.voxcinemas.com/booking/0047-test4"),
        ],
    }
    text = format_message(
        movie="[TEST] The Devil Wears Prada 2",
        cinema="City Centre Almaza",
        target_date=date(2026, 5, 22),
        groups=sample_groups,
    )

    logging.info("sending test message to chat %s", chat_id)
    send_telegram(token, chat_id, text)
    logging.info("test message sent — check Telegram")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        logging.error("failed: %s", e)
        sys.exit(1)
