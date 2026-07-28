# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-purpose scraper + notifier: a GitHub Actions cron job runs `check_showtimes.py`, which
checks whether a cinema has published showtimes for a given movie on a given date, and Telegrams
once per watch when they go live. There is no server, no package, no build — the repo root *is* the
deployable unit. The one exception is `scheduler/`, an independently deployed Cloudflare Worker that
does nothing but trigger the workflow on time (see below); it contains no scraping logic.

The directory is still named `vox_cinema` for historical reasons; it now watches both VOX Cinemas
Egypt and Scene Cinemas District 5.

## Commands

```bash
pip install -r requirements.txt pytest   # deps; python-dotenv optional, only for the helper scripts
pytest -q                                # full suite (tests/test_check_showtimes.py)
pytest -q -k vox                         # single test / group by name substring
python check_showtimes.py                # live run of every watch; WILL send Telegram + write state.json
WATCHES_FILE=/tmp/scratch.json python check_showtimes.py   # dry-run against a scratch watch config
python send_test_message.py              # one sample alert per watch (real wording), TEST-bannered
python send_test_message.py <watch-id>   # ...or just one watch
python get_chat_id.py                    # print chat IDs from getUpdates (message the bot first)
```

Credentials live in GitHub secrets (`gh secret set`); **what** to watch lives in `watches.json` in
the repo. Verify end-to-end with `gh workflow run test-telegram.yml` (delivery only) or
`gh workflow run check-showtimes.yml` (full scrape + parse + notify).

Env vars: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are required. `TIMEZONE` (default
`Africa/Cairo`) is the fallback for watches that don't set their own. `WATCHES_FILE` overrides the
`watches.json` path — the safe way to test config changes. A local `.env` is gitignored and read
only by `get_chat_id.py` / `send_test_message.py`.

## Architecture

`check_showtimes.py` is the whole program. `main()` loads `watches.json`, then calls `check_watch`
per watch inside a try/except so one failing site can't sink the others; the run exits 1 if any
watch failed, after all of them have been attempted.

Per-watch flow: `resolve_target_date` → `site.build_url` → `fetch_page` → `site.parse` →
`should_notify` → state dedupe → `format_message` → `send_telegram`.

Site differences are isolated in the `SITES` dict of `Site` adapters (`build_url`, `parse`,
`display_names`, `headers`, `empty_is_expected`, `soldout_label`). **Add a site by adding an
adapter, not by branching inside the pipeline.**

Load-bearing details that aren't obvious from the code:

- **Absence of showtimes is the signal.** Both sites publish only a rolling window of dates, so
  "parsed nothing" means "not published yet" and exits 0 quietly. The two sites express it
  differently: Scene returns an **empty body**; VOX returns a **full page** with a "No showtimes
  could be found" notice. That's why each adapter carries `empty_is_expected` — for VOX, no
  showtimes *and* no notice means the markup moved and we log a warning instead of silently never
  notifying. If alerts stop, suspect the parser before the schedule.
- **"Published" and "bookable" are different events, and watches choose.** Both sites list a
  date's showtimes before opening sales, so `Watch.notify_on` selects the trigger via
  `should_notify`: `published` (default) fires on any showtime; `bookable` waits for a non-sold-out
  one. When a `bookable` watch is holding off, **state is deliberately not written** — that's what
  lets it keep checking and fire later when sales open. Don't "fix" that by recording it.
- **VOX's "unavailable" is not "sold out".** VOX uses one state for both sold-out and
  not-yet-on-sale, and times routinely flip to bookable (observed live within the hour). Hence
  `Site.soldout_label`: Scene says `sold out` (it has a real `showtime_soldout` class), VOX says
  `not bookable`. Don't collapse these back into one word.
- **VOX renders non-bookable times as `<span>`, not `<a>`.** `span.action.showtime.unavailable`
  entries are real published showtimes that just aren't on sale; the original selector was
  `a.action.showtime`, which silently dropped entire experience groups (GOLD, 4DX). Both element
  types are parsed and spans map to `Showtime.soldout`.
- **`curl_cffi`, not `requests`, for scraping.** Both sites' WAFs reject plain `requests`/`urllib3`
  TLS handshakes with 403; `fetch_page` uses `impersonate="chrome124"`. WebFetch and plain
  `requests` will fail against these hosts — don't "simplify" it back. `requests` is still used for
  the Telegram API, which has no such gate.
- **Scene fetches as XHR, VOX as a navigation.** Hence `SCENE_HEADERS` (`X-Requested-With`,
  `Sec-Fetch-Dest: empty`) vs `VOX_HEADERS` (`Sec-Fetch-Dest: document`). Headers come from the
  adapter, not a global.
- **Three date formats, deliberately.** `business_day=DD-MM-YYYY` (Scene wire), `d=YYYYMMDD` (VOX
  wire), and `YYYYMMDD` as the `state.json` dedupe key. Don't unify them.
- **`vox_display_names` is scoped on purpose.** It reads `article.movie-compare h2`, not the first
  `<h2>` — the page footer has `<h2>Stay in touch</h2>`, which a bare `find("h2")` returns whenever
  the movie block is absent.
- **Cloudflare owns the clock, Actions owns the run.** GitHub's `schedule` trigger is
  deprioritized: it drifts 10-60 minutes and drops firings rather than backfilling them, so `*/10`
  degraded to roughly hourly. API-dispatched runs don't queue that way, so `scheduler/` (a Worker on
  a `*/15` cron) POSTs to the `workflow_dispatch` endpoint and the workflow's own `schedule` block
  is now just a fallback at off-peak offsets. **Don't port the scraper into the Worker** — `fetch()`
  there can't do `curl_cffi`'s TLS impersonation, so it would be back to 403s with no workaround.
  The Worker needs a fine-grained PAT with **Actions: write** on this repo only, stored via
  `wrangler secret put`. Expect duplicate runs occasionally (Worker + fallback); `state.json`
  dedupes them.
- **State is committed back to the repo.** `state.json` maps `{watch_id: "YYYYMMDD"}`; the workflow
  commits it after a notification. That's the dedupe mechanism. `load_state` migrates the legacy
  flat-string form onto the first watch. A watch's `id` *is* its dedupe key — renaming an id
  re-arms that watch. Expect `main` to receive bot commits, so pull before pushing.
- **Scene parsing keys off `ex_*` classes.** Experience groups are `<span class="ex_imax|ex_vip|
  ex_stand">` labels; `ex_*_content` wrappers are excluded so only label spans match. Sold out =
  `showtime_soldout` class or a `javascript:` href.

## Tests

`tests/` covers the pure functions: date resolution (frozen clocks, never `datetime.now`), both
parsers against saved HTML in `tests/fixtures/`, URL building, `watches.json` validation, and state
migration. Network, Telegram, and state writes are untested by design.
`test_repo_watches_file_is_valid` asserts the committed `watches.json` actually loads and still
contains the Odyssey watch — it guards production config, so don't relax it.

When a site's markup changes, capture a fresh page into `tests/fixtures/` and fix the parser against
it rather than testing live.

## Gotchas

- `TELEGRAM_CHAT_ID` points at a shared group. If Telegram promotes that group to a supergroup its
  ID changes to a `-100…` form and sends fail silently — re-fetch via `get_chat_id.py` and update
  the secret.
- Fixed-date watches go dormant once the date passes (logged, not an error). Remove them from
  `watches.json` when they're done.
- The workflow needs **Read and write** workflow permissions to push `state.json`.
