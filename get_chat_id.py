"""Print candidate chat IDs from Telegram's getUpdates so you can pick your personal one.

Usage: ensure TELEGRAM_BOT_TOKEN is set (e.g. in .env), then `python get_chat_id.py`.
Send your bot any message FIRST — getUpdates only shows recent activity.
"""
from __future__ import annotations

import os
import sys

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN first.", file=sys.stderr)
        return 1

    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
    r.raise_for_status()
    data = r.json()

    if not data.get("ok"):
        print(f"Telegram API not-ok: {data}", file=sys.stderr)
        return 1

    updates = data.get("result", [])
    if not updates:
        print("No updates yet. Open your bot's chat in Telegram and send it any message, then re-run this.")
        return 0

    seen = {}
    for u in updates:
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None or cid in seen:
            continue
        seen[cid] = chat
        kind = chat.get("type", "?")
        who = chat.get("username") or chat.get("first_name") or chat.get("title") or "?"
        print(f"chat_id={cid:<15} type={kind:<8} who={who}")
    if seen:
        print("\nUse the chat_id where type=private and who=your name.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
