# Maintaining Scrapers

An operational guide for scrapers that are **already running**: how to tell something is broken,
what each status means, and the steps to fix it. How to add a new scraper is in
[`ADDING_A_SCRAPER.md`](ADDING_A_SCRAPER.md).

> Verified against the code (`health.py`, `runner.py`, `beat.py`, `routers/scraper.py`) and the
> prod containers, 2026-10-05. Container names on prod still start with `niskala-intelligence-`
> (following the folder name), so use `docker compose exec <service>` from the project folder
> to avoid depending on that name.

---

## 1. How to tell something is broken

| Source | Contents | When to look |
|---|---|---|
| The **/scrapers** page (UI, admin) | each scraper's health status, a summary at the top, **Runs** and **Items** tabs per scraper | routinely, and when someone reports missing articles |
| The **Telegram digest** `scraper_health` | one message listing the non-`ok` scrapers, sent every `scraper_health_sweep_interval_min` (default **30 minutes**). **Sends nothing when everything is `ok`/`disabled`**: silence = healthy | automatic |
| `GET /api/scraper/health` | the same data as the UI | integrations/scripts |
| Worker logs | one `run_finished` line per run with the status and item counts | investigation |

Note: the `scraper_health` topic must be in `TELEGRAM__THREAD_IDS`, otherwise
the digest has nowhere to go.

```bash
# logs for one scraper (last hour)
docker compose logs --since 1h worker worker-browser | grep "scraper_id=<id>"
```

---

## 2. What the health statuses mean

Computed by `cti_scraper.health.compute_health` from the latest runs (newest first):

| Status | Meaning | Usually | Action |
|---|---|---|---|
| `ok` | healthy | | |
| `disabled` | switched off on purpose (config or `meta.enabled=False`) | | no action needed |
| `stale` | has never run at all | a new scraper not yet scheduled | check that `beat` was restarted (section 5) |
| `dead` | the last run is older than **3x its schedule interval** | `beat`/`worker` down, queue stuck | section 4.A |
| `degraded` | the last run failed (`fetch_error`, `parse_error`, `rate_limited`, `timeout`, `backpressure`) | the site changed or is blocking | sections 4.B-D |
| `zero_yield` | the **last 3 runs in a row** were `empty` | broken selector **or** the source is genuinely quiet | section 4.C |

Status per **run** (Runs column): `ok`, `empty` (ran, zero items), `parse_error`,
`fetch_error`, `rate_limited`, `backpressure`, `disabled` (skipped because the config is off).

---

## 3. Tools

```bash
# in the container (prod) -- no repo needed
docker compose exec worker cti-scraper list                 # all scrapers + on/off + schedule
docker compose exec worker cti-scraper list --tag vendor
docker compose exec worker cti-scraper dry-run <id>         # fetch from the real source, writes NOTHING
docker compose exec worker cti-scraper run <id>             # real run (writes to the DB, dedup active)
docker compose exec worker cti-scraper run <id> --prime     # mark every item as seen, without storing
docker compose exec worker cti-scraper disable <id> --reason "site changed"
docker compose exec worker cti-scraper enable <id>
```

In the **/scrapers UI** (admin): Dry-run, Trigger (run once via Celery on the right queue),
Enable/Disable, edit Config, Reset config, Reset dedup.

| Action | Effect | Restart needed? |
|---|---|---|
| Disable (UI/CLI) | the next run immediately has status `disabled` and makes no HTTP call | **No** (Runner checks the config every run) |
| Enable a scraper that was not scheduled | it starts being scheduled | **Yes, restart `beat`** (beat builds the schedule at start-up and skips disabled ones) |
| Change `schedule` | new schedule | **Yes, restart `beat`** |
| Change `rate_limit` / `max_items` / options | used by the next run | No |
| Reset config | removes every override, back to the code defaults | beat, if a `schedule` changed |
| Reset dedup | the next run treats EVERY item as new (still subject to the cold-start cap of 5 items) | No |

Restarting beat: `docker compose restart beat`.

`dry-run` and `trigger` in the UI use the admin's stored choices; `cti-scraper dry-run`
in the CLI uses the code defaults unless given `--option key=value`.

---

## 4. Playbook per problem

### A. `dead` / the scraper never runs

1. `docker compose ps`: `beat`, `worker`, `worker-browser`, `redis`, `postgres` must be `Up (healthy)`.
2. `docker compose logs --since 30m beat | tail`: beat refuses to start if the registry is empty (`registry scraper KOSONG`).
3. When was the last run? Runs tab. If every scraper is `dead` at once, it is an infrastructure problem (beat/redis/worker), not one scraper.
4. Only one scraper is `dead` while beat runs: check its schedule (`cti-scraper list`) and whether it is `enabled`. Ticks expire after one schedule interval (`expires`), so a worker that was down for a long time does not cause a flood when it recovers.
5. Only `browser` scrapers: check `worker-browser` (memory/`shm_size`, Chromium crashes).

### B. `parse_error` (the site changed)

It means the document was read but its structure does not match; it is **not** a network problem, and
the framework deliberately does **not** retry.

1. Look at the error message in Runs (`ParseError: ...`): "gak ada node di item_path" (no nodes at item_path), "XML gak valid" (invalid XML), or "title_xpath ... gak match" (title_xpath does not match).
2. Look at what the source actually returns now:
   ```bash
   curl -sL -A "Mozilla/5.0" "<feed/page url>" | head -60
   ```
   - Does the page contain a challenge/captcha/block (Cloudflare, "Access denied")? That is blocking, not a structural change: go to section D.
   - Did the RSS move (redirect, `/feed` -> `/rss.xml`)? Change `feeds`.
   - Did the HTML structure change? Fix the XPath.
3. Fix it in the dev repo, then:
   ```bash
   uv run cti-scraper dry-run <id>
   uv run cti-scraper verify <id> --record     # record a NEW baseline once the fix is proven correct
   uv run cti-scraper verify <id>              # must be OK
   ```
   Check `tests/fixtures/<legacy_script>/expected_items.json` by hand before committing.
4. Deploy (`worker worker-browser beat api`, see ADDING section 8), wait one tick, check Runs.
5. If the parser produced garbage (wrong titles/URLs) into dedup/articles: after the fix,
   **Reset dedup** so the right items are processed again. Garbage articles that were already stored are not
   deleted automatically (there is no dedicated tool yet; clean them up via SQL carefully,
   checking first with a `select` by `source` and time range).

### C. `zero_yield` / `empty` all the time

Tell "the source is quiet" apart from "the selector is broken":

```bash
docker compose exec worker cti-scraper dry-run <id>      # status=empty?
curl -sL "<url>" | grep -c "<item\|<article"             # does the source have items?
```

- The source has items but the scraper is empty -> broken selector/`item_path`, fix it as in section B.
- The source really publishes rarely (a monthly blog) -> expected. Loosen the schedule (e.g. daily) so it is not flagged all the time; do not disable it just because it is quiet.
- The `_include_item` filter is too strict (e.g. a category the source removed) -> check the filter.

### D. `fetch_error` / `rate_limited`

| Message | Cause | Action |
|---|---|---|
| 403 / 429 / challenge page | the site blocks bots or the rate is too high | increase the `schedule` interval, lower `rate_limit`; if it persists, consider `runtime="browser"` or another source. **Never** bypass a captcha. |
| timeout / connection reset | slow source or network | transient, retried automatically (`max_retries`); if permanent, raise `timeout_s` |
| `ConfigError` stage `config` | an empty secret/credential in env (e.g. `NVD__API_KEY`) | set the secret in `stack.env`, restart the service |
| persistent 5xx | the source is down | wait; `disable --reason` if it lasts for days |

`rate_limit` is counted **per domain**: two scrapers hitting the same host share one budget,
so adding a new scraper for a domain already in use can trigger `rate_limited` on
the existing one.

### E. `backpressure`

The `enrich` queue went over `Settings.scraper.enrich_queue_max_depth` (default **2000**), so
the sink deliberately refuses to dispatch. Items are **not** marked seen (they are retried on the next run
once the queue drains). What to check is the enrichment side, not the scraper: is `worker-nlp`
alive, is the LLM gateway healthy (see the `classify_json_failed` log), and is there a burst of
articles from one scraper (Runs -> a large `items_new`).

### F. A scraper produces too many items / garbage

- `max_items` caps each run. If it suddenly hits the cap, the parser is probably catching the wrong elements (menus, ads).
- Look at the **Items** tab, find title/URL patterns that make no sense, fix the selector, then Reset dedup.

### G. CVE Tracker: the Tech column does not match Affected

Symptom: a CVE is recorded under a tech that is not its affected product (Tech `mariadb`, Affected
"Zabbix"). The cause is NVD `keywordSearch`, which matches words anywhere in the description; since 0.2.1
`new_cve` only accepts a CVE if the tech name appears in the vendor/product/CPE of the MITRE record. A healthy
run does NOT clean up old rows -- a CVE that is now rejected is never fetched again.
Background, matching rules, and limitations: `docs/CVE_TECH_MATCHING.md`.

Run it from the repo folder on the server (the one containing `docker-compose.yml`). `compose run` joins the
application's network and env automatically, so neither `--network` nor `--env-file` is needed:

```bash
# 1) report only (default) -- writes nothing
docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \
  -v "$PWD/tools:/tools:ro" --entrypoint python worker /tools/ops/reconcile_cve_tech.py

# 2) a single client only: append to the same command, e.g.  --client acme
# 3) once the report has been read and makes sense: append to the same command  --apply
```

Use `docker compose run`, not `docker run --env-file .env`: the latter does not strip inline
comments in `.env` (see `tools/ops/deploy.sh`, same pattern).

Each row is re-evaluated with the same rules as the scraper: `RETAG` (another tech of the same client
that matches), `DELETE` (nothing matches), `REVIEW` (no match but it already has a
ticket/ACK -- **never deleted automatically**, decide by hand). CVEs whose MITRE record is
unreachable or has no data are skipped and counted as "tak terverifikasi" (unverified). Needs access to
`cveawg.mitre.org`, ~1 request/second per unique CVE. Idempotent, safe to repeat.

### H. Excel export: "CVE Reported Date" shows a date only (no time)

Symptom: in the CVE Tracker export the **CVE Reported Date** column contains `31-08-2026`, not
`20:53 31-08-2026`. That column reads `cve_tracker.published_at` (the publish time from MITRE, written by
`new_cve`); CVEs that arrived before that column existed, or whose MITRE record gives no time, have it empty and
fall back to the `published` date. (**Reported by System** is not affected: that is `detected_on`, when the
scraper first got the CVE.)

```bash
# on the production host (repo checkout, stack running). Report only (default) -- writes nothing
make backfill-published-at                      # or ARGS='--client <client_id>' for a single client
# once the report has been read and makes sense:
make backfill-published-at ARGS='--apply'
```

The `make` target runs the tool in the existing `worker` container (image, `.env`, and network follow
that service; `tools/` is mounted read-only; postgres/redis/migrate are not touched). Without a repo checkout, use
the `docker run` form as in 4.G with `/tools/ops/backfill_cve_published_at.py`.

Only rows with a NULL `published_at` are touched, and filled ones are never overwritten.
Rows whose MITRE date differs from the stored `published` are reported as `MISMATCH` and **not
written**; CVEs whose MITRE record is unreachable or has no time are skipped ("tak terverifikasi", unverified). Needs
access to `cveawg.mitre.org`, ~1 request/second per unique CVE. Idempotent, safe to repeat.

---

## 5. Changes that need a deploy

| Change | Rebuild | Restart |
|---|---|---|
| New/changed scraper file | `worker worker-browser beat api` | automatic via `up -d --build` |
| Config via the UI only (rate_limit, max_items, options, enable/disable) | no | no (except a schedule change or enabling a scraper that was not scheduled: `beat`) |
| Env variables (secrets/credentials) | no | the services that use them |

```bash
docker compose --profile app up -d --build worker worker-browser beat api
```

Why `api` is included: it reads the registry for the `/scrapers` list, dry-run, and trigger.

---

## 6. Rules not to break

- **Never change the `meta.id`** of a scraper that is already running. `id` = the dedup namespace + the control plane key; changing it resets dedup. Want to change the display name? Change `source` (note: the label on old articles does not change). Really want to move to a new id? Create a new scraper, `--prime` it, disable the old one.
- **Never delete a scraper file** to "switch it off". Use `disable --reason "..."` (the reason is kept in the config) or `meta.enabled=False`. Deleting the file orphans its run history and config, and the effect on the UI is untested.
- **Never swallow errors in `fetch()`**. A broken scraper that looks healthy is more dangerous than one that looks broken.
- **Never raise the frequency without a reason**. 15-60 minutes is enough for vendor blogs; most sources do not publish every minute, and it only adds the risk of being blocked.
- A selector fix **must** come with a new, hand-checked fixture, so the next regression is caught.

---

## 7. Periodic routine

**Weekly (~10 minutes)**
- Open `/scrapers`: sort by status. Handle `parse_error` and `dead` first.
- `zero_yield`: tell quiet from broken (section 4.C). Do not let them pile up without a decision; if left on purpose, record it in `docs/KNOWN_BROKEN.md` or disable with `--reason`.
- Check the Telegram digest: the same scraper appearing again and again = an unresolved problem.

**Monthly**
- Review sources that are permanently dead (site closed, RSS discontinued): `disable --reason` or remove via a PR.
- Review quality, not just whether it runs: which scrapers have the most rejected articles
  (`rejected_articles`, grouped by `source`)? A source that is almost entirely rejected
  wastes LLM quota; consider disabling it or filtering via `_include_item`.
- Update dependencies (`uv lock --upgrade-package ...`), especially `playwright` (the Chromium image) and
  `lxml`/`httpx`; run `pytest tests/contract tests/unit`.
- Refresh the fixtures of scrapers that changed a lot (`verify --record`, check the result).

**When adding a scraper for a domain already in use**
- Remember the rate-limit budget is shared per domain (section 4.D).

---

## 8. Summary: "scraper X is broken, what now?"

```
UI /scrapers or Telegram digest -> status?
  dead        -> infra: beat/worker/redis/queue              (4.A)
  parse_error -> site changed: curl, fix, verify             (4.B)
  zero_yield  -> quiet or broken? compare with curl          (4.C)
  fetch_error -> blocking/credential/timeout                 (4.D)
  backpressure-> check enrichment, not the scraper           (4.E)
  CVE: Tech does not match Affected -> reconcile_cve_tech    (4.G)
  CVE export: Reported Date without time -> backfill_cve_published_at (4.H)
Fixed? -> deploy (section 5) -> wait one tick -> check Runs -> (if needed) Reset dedup
```
