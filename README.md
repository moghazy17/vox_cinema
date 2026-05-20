# VOX Cinemas Showtime Notifier

Polls [VOX Cinemas Egypt](https://egy.voxcinemas.com/) every 20 minutes via GitHub Actions and sends you a Telegram message the moment showtimes go live for a specific movie at a specific cinema on the next occurrence of a target weekday (e.g. next Friday). One notification per target date — no spam.

## How it works

1. A scheduled workflow runs `check_showtimes.py` every 20 minutes.
2. The script computes the next target weekday in `Africa/Cairo` (or whatever timezone you set).
3. It fetches `https://egy.voxcinemas.com/showtimes?c=<cinema>&m=<movie>&d=<YYYYMMDD>` and looks for `<a class="action showtime">` entries.
4. If any are found and `state.json` shows it has not already notified for this date, it posts a Telegram message and writes the date back to `state.json`. The workflow then commits the updated `state.json` to the repo.

## One-time setup

### 1. Create a Telegram bot

- Open Telegram and message [`@BotFather`](https://t.me/BotFather).
- Send `/newbot`, follow the prompts, and copy the **bot token** it gives you.

### 2. Find your chat ID

- Send any message to your new bot (open its chat first via the link BotFather provided).
- In a browser, visit `https://api.telegram.org/bot<TOKEN>/getUpdates`.
- Look for `"chat":{"id":<number>,…}`. That number is your **chat ID**.

### 3. Configure the repo

Push this repo to GitHub, then go to **Settings → Secrets and variables → Actions**:

**Secrets:**

| Name | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | The token from BotFather |
| `TELEGRAM_CHAT_ID`   | Your chat ID |

**Variables:**

| Name | Example |
| --- | --- |
| `CINEMA_SLUG`    | `city-centre-almaza` |
| `MOVIE_SLUG`     | `the-devil-wears-prada-2` |
| `TARGET_WEEKDAY` | `friday` (any lowercase weekday name) |
| `TIMEZONE`       | `Africa/Cairo` |

You can find the slugs by browsing voxcinemas.com — they appear in the URL when you select a cinema or open a movie page.

### 4. Enable Actions

**Settings → Actions → General →** allow all actions, and make sure **Workflow permissions** is set to **Read and write permissions** so the workflow can commit `state.json` back.

### 5. Test it

**Actions tab → "Check Showtimes" → Run workflow.** The first successful run with showtimes available will Telegram you; subsequent runs for the same date will log `Already notified for ...` and exit.

## Changing what's monitored

Update the repo variables (`CINEMA_SLUG`, `MOVIE_SLUG`, `TARGET_WEEKDAY`, `TIMEZONE`). No code change required.

## State file

`state.json` stores `{"notified_for": "YYYYMMDD"}` after a notification, or `{"notified_for": null}` when fresh. To force a re-notification, edit it back to `null` and commit, or delete the file — the script will recreate it.

## Local dev

```
pip install -r requirements.txt pytest
pytest -q
```

To dry-run the script locally, export the env vars from the table above and run `python check_showtimes.py`. The script logs everything it does at INFO level.

## Notes

- GitHub free-tier scheduled workflows can drift 5–15 minutes during peak load. That's expected.
- The page HTML is server-rendered — no headless browser needed. If VOX ever changes the structure, the script logs a warning and exits cleanly instead of crashing.
