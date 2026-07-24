# Scene Cinemas Showtime Notifier

Polls [Scene Cinemas — District 5](https://district5.scenecinemas.com/) every 20 minutes via GitHub Actions and sends you a Telegram message the moment showtimes go live for a specific movie on the next occurrence of a target weekday (e.g. next Friday). One notification per target date — no spam.

## How it works

1. A scheduled workflow runs `check_showtimes.py` every 20 minutes.
2. The script computes the next target weekday in `Africa/Cairo` (or whatever timezone you set).
3. It fetches the movie's AJAX showtimes fragment for that date:
   `https://district5.scenecinemas.com/movie-details/<movie>.html?business_day=<DD-MM-YYYY>&ajax=1`.
   Scene Cinemas only publishes a rolling window of upcoming dates, so a date with no
   showtimes scheduled yet returns an **empty** body — that's how "not available yet" is
   detected. Once the target date goes live, the fragment contains showtimes grouped by
   experience (IMAX, Premiere, Standard & Deluxe), each with a booking link or a
   struck-through "sold out" marker.
4. If showtimes are found and `state.json` shows it has not already notified for this date,
   it posts a Telegram message and writes the date back to `state.json`. The workflow then
   commits the updated `state.json` to the repo.

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

| Name | Example | Notes |
| --- | --- | --- |
| `MOVIE_SLUG`     | `the-odyssey` | From the movie-details URL |
| `TARGET_WEEKDAY` | `friday` | Any lowercase weekday name |
| `TIMEZONE`       | `Africa/Cairo` | |
| `MOVIE_BASE_URL` | _(optional)_ | Override the full movie-details URL; defaults to `https://district5.scenecinemas.com/movie-details/{movie}.html`. Use `{movie}` as a placeholder for `MOVIE_SLUG`, or set a fully-qualified URL for a different branch/movie. |

You can find the movie slug by browsing scenecinemas.com — it appears in the URL when you open a movie page (e.g. `.../movie-details/the-odyssey.html` → `the-odyssey`).

### 4. Enable Actions

**Settings → Actions → General →** allow all actions, and make sure **Workflow permissions** is set to **Read and write permissions** so the workflow can commit `state.json` back.

### 5. Test it

**Actions tab → "Check Showtimes" → Run workflow.** The first successful run with showtimes available will Telegram you; subsequent runs for the same date will log `Already notified for ...` and exit.

## Changing what's monitored

Update the repo variables (`MOVIE_SLUG`, `TARGET_WEEKDAY`, `TIMEZONE`, and optionally `MOVIE_BASE_URL`). No code change required.

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
- Showtimes are fetched from the site's own AJAX endpoint — no headless browser needed. If Scene Cinemas ever changes the fragment structure, `parse_showtimes` returns an empty result and the script exits cleanly (treated as "not yet") instead of crashing.
