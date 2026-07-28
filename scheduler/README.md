# Scheduler (Cloudflare Worker)

A ~30-line Worker whose only job is to press "run" on the `Check Showtimes` workflow every 15
minutes, on time.

**Why this exists:** GitHub's `schedule` trigger is best-effort. It runs on a deprioritized queue,
drifts 10-60 minutes when Actions is busy, and silently drops firings instead of backfilling them —
so `*/10` in practice becomes "roughly hourly, sometimes". Runs started through the API don't have
that problem: they queue like a push and start within seconds. Cloudflare's cron fires punctually,
so it keeps the clock and Actions keeps doing the work.

**Why the scraper stayed in Python:** `check_showtimes.py` needs `curl_cffi`'s Chrome TLS
impersonation to get past both cinemas' WAFs (see `CLAUDE.md`). Workers' `fetch()` can't forge a TLS
fingerprint, so a port would very likely just collect 403s. Nothing about the Python side changes.

Free on both sides: 96 Worker invocations/day against a 100,000/day free-plan budget, and Actions
minutes are unlimited on a public repo.

---

## Setup (once)

**You'll need:** a free [Cloudflare account](https://dash.cloudflare.com/sign-up), and
[Node.js](https://nodejs.org) installed locally so you can run `npx`. No credit card, no paid plan.
Nothing here is installed into the repo — `wrangler` runs straight from `npx`.

### Step 1 — Create a fine-grained PAT

**GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate
new token.**

| Field | Value |
| --- | --- |
| Repository access | **Only select repositories** → `vox_cinema` |
| Permissions → Repository → **Actions** | **Read and write** |
| Expiration | your call — put a reminder in your calendar |

That is the *only* permission it needs. It can't read your other repos, can't push code, can't touch
secrets.

### Step 2 — Deploy

```bash
cd scheduler
npx wrangler login
npx wrangler deploy                    # creates the Worker + registers the cron
npx wrangler secret put GITHUB_TOKEN   # paste the PAT when prompted
```

Deploy first, then set the secret — `wrangler secret put` wants the Worker to already exist. The
secret takes effect immediately; no redeploy needed.

If you forked this repo, change `GITHUB_REPO` in `wrangler.jsonc` to your own `owner/repo`.

### Step 3 — Confirm it fired

Wait for the next quarter hour, then check **Actions** — you should see a `Check Showtimes` run
whose trigger is `workflow_dispatch`, starting within seconds of `:00 / :15 / :30 / :45`.

Worker-side logs live in **Cloudflare dashboard → Workers & Pages → vox-cinema-scheduler → Logs**,
or:

```bash
npx wrangler tail
```

---

## Testing without waiting

```bash
npx wrangler dev --test-scheduled
# then, in another terminal:
curl "http://localhost:8787/__scheduled?cron=*/15+*+*+*+*"
```

Local dev doesn't see deployed secrets — put the token in `scheduler/.dev.vars` (gitignored):

```
GITHUB_TOKEN=github_pat_...
```

⚠️ This dispatches a **real** workflow run, which really scrapes and really sends Telegram messages
if showtimes are up.

---

## Changing the interval

Edit `triggers.crons` in `wrangler.jsonc` and redeploy. Going faster is free within the request
budget, but be neighbourly to the cinemas' servers — 15 minutes is already ~100 hits/day per watch.

---

## Troubleshooting

**Runs stopped appearing in Actions.** Check `wrangler tail`. A `401`/`404` from the dispatch call
almost always means the PAT expired or lost its **Actions: write** permission — GitHub returns `404`
rather than `403` when a token lacks access, so don't read it as "wrong workflow filename".

**Both a `workflow_dispatch` and a `schedule` run show up.** Expected. The workflow keeps a
`schedule` trigger at an off-peak offset as a fallback for if the Worker dies; a duplicate run is
harmless because `state.json` dedupes notifications.

**Uninstalling.** `npx wrangler delete` removes the Worker and its cron. The `schedule` fallback in
the workflow keeps things running (late, as before).
