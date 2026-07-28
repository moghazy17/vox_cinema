// A precise clock for the showtime checker.
//
// GitHub's `schedule` trigger is best-effort: it runs on a deprioritized queue,
// drifts 10-60 minutes under load, and drops firings entirely rather than
// backfilling them. Runs started through the API don't — they queue like a push
// and begin within seconds.
//
// So this Worker owns the *timing* and GitHub Actions stays the *runner*. The
// scraping deliberately does not move here: check_showtimes.py depends on
// curl_cffi's Chrome TLS impersonation to get past both cinemas' WAFs, and
// Workers' fetch() has no way to forge a TLS fingerprint.

const WORKFLOW_FILE = "check-showtimes.yml";

export default {
  async scheduled(event, env) {
    const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;

    const response = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        // GitHub rejects API requests that arrive without a User-Agent.
        "User-Agent": "vox-cinema-scheduler",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: env.GITHUB_REF }),
      // Never follow a redirect: fetch would replay the Authorization header at
      // whatever host it pointed to. A real dispatch answers 204 directly, so a
      // 3xx here means something is wrong and should surface as an error below.
      redirect: "manual",
    });

    // A successful workflow_dispatch is 204 with an empty body.
    if (response.status !== 204) {
      // Throwing records the failure in the Workers dashboard and `wrangler
      // tail`. The next tick is 15 minutes out, so a lost dispatch is a gap in
      // coverage, not an outage — the Actions-side `schedule` fallback and the
      // next tick both still fire.
      throw new Error(
        `dispatch failed: ${response.status} ${await response.text()}`,
      );
    }

    console.log(`dispatched ${WORKFLOW_FILE} on ${env.GITHUB_REF}`);
  },
};
