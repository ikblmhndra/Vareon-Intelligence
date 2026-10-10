# Adding a New Scraper (step by step)

A guide to adding **one new scraper** from scratch until it runs in production. How to
maintain scrapers that are already running (broken, empty, dead) is in
[`SCRAPER_MAINTENANCE.md`](SCRAPER_MAINTENANCE.md).

The principle: **one scraper = one file** in `scrapers/src/cti_scrapers/feeds/`.
No registry to edit, no central schedule, no `pyproject.toml`
entry. Drop the file in and the framework finds it on its own (auto-discovery,
`cti_scraper.registry`). There are currently ~95 registered scrapers.

> Last verified against the code and the prod containers: 2026-10-05
> (`cti-scraper list`, `cti-scraper dry-run bitdefender` run in the `worker` container).

---

## 0. Quick map: what happens to a scraper

```
beat (cron schedule)  ->  Celery task scrape.run  ->  Runner  ->  the scraper's fetch()
                                                        |
                                dedup (reserve) <-------+------->  sink (by item type)
                                                                      |
                                                    ArticleItem -> enrich task (LLM, score, IOC) -> articles table
```

All you write is `fetch()` (or, for simple RSS/XPath/API, just the class
attributes). **Dedup, retries, rate limiting, heartbeat, logging, storage, and
alerts are handled by the framework** -- do not rewrite them in the scraper file.

See `docs/ARCHITECTURE.md` section 3.1 for the full flow.

---

## 1. Pick the scraper type

| Source | Family | `meta.runtime` | Example |
|---|---|---|---|
| RSS / Atom | `RSSScraper` | `light` | `feeds/bitdefender.py` |
| Static HTML page | `XPathScraper` | `light` | `feeds/cyfirma.py` |
| HTML page that needs JavaScript | `XPathScraper` | `browser` | `feeds/abnormalsecurity.py` |
| Simple JSON API (a list of items) | `ApiScraper` | `light` | `families/api.py` |
| Anything else (state, auth, its own document type) | a direct `BaseScraper` subclass | as needed | `collectors/ransomware_live.py` |

Order to try: **RSS first** (most stable, cheapest), then API, then `light` XPath,
and `browser` only when really required (Chromium is heavy and runs in a
separate worker with low concurrency).

Check the source before writing anything:

```bash
curl -sI https://example.com/feed | head -5          # status + content-type
curl -s  https://example.com/feed | head -40         # RSS? Atom? what is in it?
curl -s  https://example.com/robots.txt              # is crawling disallowed?
```

If there is an RSS/Atom feed, always use it instead of scraping the HTML. If the site
disallows crawling or needs a login/captcha, **stop and decide first**
(never bypass a captcha or create an account on the source).

---

## 2. Set up the dev environment

```bash
git checkout -b feat/scraper-<name>
uv sync --extra dev                                  # from the repo root
uv run cti-scraper list | head                       # must show the list of scrapers
```

`runtime="browser"` scrapers need Playwright: `uv sync --extra browser` in
`packages/cti-scraper`, then `playwright install chromium`.

---

## 3. Create the scraper file

**There is no scaffold command** (`cti-scraper new` does *not* exist): copy a similar
reference scraper and change it.

```bash
cp scrapers/src/cti_scrapers/feeds/bitdefender.py scrapers/src/cti_scrapers/feeds/<slug>.py
```

### 3a. RSS (the most common case)

```python
"""Source Name -- what is monitored, and why."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class SourceName(RSSScraper):
    meta = ScraperMeta(
        id="source_name",  # slug, lower case. NEVER change it after deploy
        source="Source Name",  # display label, must be UNIQUE and meaningful
        schedule=spread("*/30 * * * *", "source_name"),
        tags=("vendor",),
        legacy_script="source_name",  # used as the fixture folder name (see step 5)
    )
    feeds = ("https://example.com/feed.xml",)
```

RSS attributes that often need changing (all `ClassVar`, see
`packages/cti-scraper/src/cti_scraper/families/rss.py`):

| Attribute | Default | When to change |
|---|---|---|
| `item_path` | `.//item` | Atom: `.//{http://www.w3.org/2005/Atom}entry` |
| `link_path` / `link_attr` | `link` / `None` | Atom: `link_attr = "href"` |
| `date_path` | `pubDate` | `None` if the feed has no dates (the scrape time is used) |
| `base_url` | `""` | relative links in the feed |
| `xml_fixups` / `html_unescape` | empty / `False` | feeds with broken entities (rarely needed) |
| `_include_item(node)` | everything passes | a per-item filter, e.g. certain categories only |

### 3b. XPath

```python
class SourceName(XPathScraper):
    meta = ScraperMeta(
        id="source_name",
        source="Source Name",
        schedule=spread("0 */2 * * *", "source_name"),
        runtime="light",
    )
    url = "https://example.com/blog"
    title_xpath = "(//article//h2)[{i}]"  # {i} is filled with 1..max_items when indexed=True
    link_xpath = "(//article//h2/a/@href)[{i}]"
    base_url = "https://example.com"
```

`indexed = False` uses one XPath for all cards (titles and links are paired
in order). If `title_xpath` matches nothing at all, the framework raises
`ParseError` (meaning: the site changed). For pages that need JavaScript:
`runtime="browser"` plus `wait_for = "<css selector>"`.

### 3c. JSON API

Fill in `url`, `root_path` (the key pointing at the list), and `field_map`
(`{"title": "<json key>", "url": "<json key>"}`). If the mapping is not that
simple, subclass `BaseScraper` directly and write your own `fetch()`.

### 3d. Writing your own `fetch()` (bespoke)

```python
def fetch(self, ctx):
    resp = ctx.http.get("https://api.example.com/items")  # shared client: UA, timeout, rate limit
    for row in resp.json()["items"]:
        yield ArticleItem(title=row["title"], url=row["url"], posted_on=ctx.now.date())
```

`fetch()` rules:
- HTTP **only** through `ctx.http`; the browser through `ctx.page()`. Do not create your own `httpx.Client`/`requests`.
- Time **only** through `ctx.now` (not `datetime.now()`), so tests are deterministic.
- No access to the DB, Telegram, or raw tokens. Need internal data? Declare `meta.reference_data`; need an API key? Declare `meta.credential`.
- No `try/except` that swallows errors. Raise `TransientFetchError` for what is worth retrying (5xx, timeouts) and `ParseError` when the document was read but its structure changed.
- Yielding zero items is legitimate (recorded as `empty`). Do not `yield` garbage to "look like it works".
- Other item types (`NoticeItem`, `CveItem`, `RansomwareVictimItem`, ...) choose their destination through a *sink*; see `cti_scraper/items.py` and `sinks.py`.

### 3e. Fill in `ScraperMeta` correctly

| Field | Notes |
|---|---|
| `id` | **Permanent.** It is the dedup namespace and the control plane key. Changing it = resetting dedup, so the scraper re-yields every item. |
| `source` | Shown on articles, in Telegram, and in the UI. Must be unique (case-insensitive) and not a placeholder ("Name", "Source", ...), enforced by `tests/contract/test_scraper_labels.py`. |
| `schedule` | 5-field cron. Use `spread("*/N * * * *", id)` so dozens of scrapers do not fire on the same minute. For vendor RSS, 15-60 minutes is enough. |
| `runtime` | `light` (httpx) or `browser` (Playwright). Decides the Celery queue: `browser` -> `scrape.browser`, has a `credential` -> `scrape.api`, the rest -> `scrape.rss`. |
| `rate_limit` | Default `20/minute`, **per domain** (two scrapers on the same host share the budget). Lower it for sensitive sites. |
| `max_items` | A hard cap per run (max 1000). A fence in case the parser suddenly explodes. |
| `tags` | Free-form, used for filtering (`cti-scraper list --tag vendor`). |
| `legacy_script` / `legacy_label` | For a new scraper, setting `legacy_script` to the same value as `id` is enough (used as the fixture folder name). Must be unique. |
| `enabled` | Default `True`. See step 8 before deploying. |

---

## 4. Dry-run (real, writes nothing)

```bash
uv run cti-scraper dry-run source_name
# status=ok items_found=15 duration_ms=147
```

Fetches from the real source **without** touching the DB, dedup, or alerts. The output is
just a summary (status, item count, errors), **not the list of items**. To see the
actual items (title/URL/date), use this snippet:

```bash
uv run python - <<'PY'
from datetime import UTC, datetime
import structlog
from cti_scraper import registry
from cti_scraper.base import ScrapeContext
from cti_scraper.http import ScraperHttpClient

cls = registry.get("source_name")
m = cls.meta
ctx = ScrapeContext(
    meta=m, run_id="dev", log=structlog.get_logger(),
    http=ScraperHttpClient(timeout_s=m.timeout_s, rate_limit=m.rate_limit),
    now=datetime.now(UTC).replace(tzinfo=None),
)
for it in cls().fetch(ctx):
    print(it.title, it.url, it.posted_on)
PY
```

(Only for `runtime="light"`; for `browser` scrapers checking with `dry-run` and `verify` is enough.)
Check: the item count makes sense, titles and URLs are right, dates are filled in, and there is no
`ERROR [...]` in the `dry-run` output.

Possible statuses: `ok`, `empty` (zero items), `parse_error` (structure changed),
`fetch_error`, `rate_limited`, `backpressure`.

Dry-run can also be run in the prod container (read-only with respect to data):

```bash
docker compose exec worker cti-scraper dry-run source_name
```

---

## 5. Fixture + verify (regression baseline)

Fixture = recorded HTTP bytes, so tests do not depend on the internet.

```bash
uv run cti-scraper verify source_name --record     # record a baseline from the real source
uv run cti-scraper verify source_name              # re-run against the fixture, must be "OK"
```

- The recording lives in `tests/fixtures/<legacy_script>/` (`<date>.input.xml|html|json`
  and `expected_items.json`). **Commit this folder.**
- `--record` needs `meta.legacy_script`. `runtime="browser"` scrapers cannot be
  recorded through this CLI (use `tools/salvage/record_fixtures.py`).
- `verify` only runs in the **dev repo** (the prod container does not ship `tests/fixtures`).
- After recording, **open `expected_items.json`** and make sure its content really is correct;
  never store a wrong baseline.

---

## 6. Tests and lint

```bash
uv run pytest tests/contract -k source_name -q     # contract: id matches, valid cron, fetch is a generator, max_items, runtime
uv run pytest tests/contract/test_scraper_labels.py -q   # unique labels, not placeholders
uv run ruff check scrapers && uv run ruff format --check scrapers
```

The contract tests run automatically for every registered scraper. If they fail,
**fix the framework or the meta**, do not work around it in `fetch()`.

---

## 7. Commit and review

```bash
git add scrapers/src/cti_scrapers/feeds/<slug>.py tests/fixtures/<slug>
git commit -m "feat(scraper): add <Source Name>"
```

Only two things change: the scraper file and the fixture folder. If you feel you
need to edit another file, ask why first (it is usually a sign of a problem in the
framework).

---

## 8. Deploying to production

Scraper code ships in the **image** (`COPY scrapers scrapers`), and the registry is only read
when a process starts. So a new scraper needs an **image rebuild and a restart of the processes**
that read the registry:

```bash
git pull
docker compose --profile app up -d --build worker worker-browser beat api
```

| Service | Why it is rebuilt |
|---|---|
| `worker` | runs the `scrape.rss` and `scrape.api` scrapers |
| `worker-browser` | runs the `runtime="browser"` scrapers (rebuild it even for a `light` scraper; it is the same image) |
| `beat` | **builds the schedule at start-up**; without a restart the new scraper is never scheduled |
| `api` | the scraper list on the `/scrapers` page and the dry-run/trigger endpoints are read from the registry |

> The schedule is NOT hot-reloaded. An older document said "beat re-reads every 60 seconds":
> that is **not true** for the current code. `ScraperConfig.schedule`/`enabled` changed
> through the control plane are only used by beat after a restart (see the docstring of
> `cti_worker.beat.build_beat_schedule`).

### The first run of a new scraper (cold start)

A scraper with no dedup history yet (zero `scraper_seen` rows) hits the
**cold-start cap**: only the `Settings.scraper.cold_start_max_items` (default **5**)
**newest** items are processed (enrichment, LLM, Telegram); the rest are immediately marked
"already seen" without being processed (`Runner._cold_start_cap`). So a feed with hundreds of
old items does not flood the queue, but **the 5 newest items still come in** as articles.

If you want **zero** items from the first run (e.g. a new feed whose content before today is not
relevant):

```bash
docker compose exec worker cti-scraper run source_name --prime
```

`--prime` marks every item it finds as seen without storing or
sending anything; the next scheduled run only processes what is genuinely new.

To test in prod first without scheduling it: deploy with `enabled=False`
in `meta`, check it with `dry-run` in the container, then enable it (`cti-scraper enable
source_name` or the button on `/scrapers`) and **restart `beat`**.

---

## 9. Verification after deploy

1. `/scrapers` in the UI: the scraper appears, its status is not `stale`/`dead`.
2. After one tick of its schedule: open the scraper detail -> **Runs**: `status=ok`, `items_found>0`.
3. **Items** tab: items appear; check one article in the Newsroom (title, URL, source correct).
4. If the status is `empty`, `parse_error`, or `fetch_error`, follow
   [`SCRAPER_MAINTENANCE.md`](SCRAPER_MAINTENANCE.md).

The UI (admin) also offers a manual **Dry-run** and **Trigger** per scraper; trigger
sends the task to the right queue according to `meta.runtime`/`credential`.

---

## Special cases

**API keys / credentials** -- set `meta.credential = "github" | "nvd" | "twitter" | ...`
(see `cti_scraper/credentials.py`). `Runner` puts the auth headers on `ctx.http`
before `fetch()`; scraper code never holds the token. An empty secret in env
makes the run fail with `fetch_error` (stage `config`), not a crash. Scrapers
with a credential go to the `scrape.api` queue.

**Internal data (techstack, etc.)** -- `meta.reference_data = ("techstack",)`;
`Runner` reads it from Postgres and puts it in `ctx.reference["techstack"]`.
`dry-run` still needs a DB connection for this.

**Two ways to fetch data, which an admin can switch without a deploy** -- declare a
`ScraperOption` in `meta.options` (a closed choice, validated by the API). Read it through
`ctx.options["key"]`. Try it without changing the configuration:
`cti-scraper dry-run <id> --option provider=x_official`. If one of the choices is
pay-per-use, write a cost warning in `description` and do not make it the default.
The contract is enforced by `tests/contract/test_scraper_options.py`.

**Its own document shape** (ransomware, CVE) -- just `yield` the matching item type;
the sink is chosen by item type. Need a new destination: register `@sink_for(MyItem)` in
the same file.

**Browser** -- `runtime="browser"`, use `with ctx.page() as page:`. Calling
`ctx.page()` with `runtime="light"` raises `ConfigError` (on purpose, so it is
caught during dev). Browser worker concurrency is deliberately low (`BROWSER_WORKER_CONCURRENCY`, default 2).

---

## Why `fetch()` must not access the DB/Telegram directly

This is a safety fence, not style. While recording fixtures from the old scrapers, some
created a `MongoClient` directly from config and some held a hardcoded Telegram token:
a scraper that was "just being tested" could write to the production database or
send messages to the real channel. `fetch()` is only given `ctx.http`, `ctx.page()`,
`ctx.now`, `ctx.options`, `ctx.reference`. So that class of bug cannot happen again.

---

## Done checklist

- [ ] `cti-scraper dry-run <id>` produces the right items
- [ ] Fixture recorded, `expected_items.json` checked by hand, `cti-scraper verify <id>` = OK
- [ ] `pytest tests/contract -k <id>` and `test_scraper_labels.py` pass; `ruff` is clean
- [ ] `id` is final (will not be changed), `source` is unique and meaningful
- [ ] `schedule` uses `spread()`, `runtime` matches how it fetches, `rate_limit` is sensible
- [ ] No `try/except` that swallows errors, no leftover debug `print`
- [ ] Only the scraper file + the fixture folder changed
- [ ] After deploy: the first run is `ok`, items appear (remember cold start: the 5 newest items; use `--prime` if you do not want them)

## Common problems when adding

The quoted messages are the framework's literal (Indonesian) error text.

| Symptom | Cause | Fix |
|---|---|---|
| `scraper '<id>' gak kedaftar` (not registered) | the file is outside `cti_scrapers/`, the class is not a `BaseScraper` subclass, or `meta.id` differs | check the file location and `meta.id` |
| `ConfigError ... gak nulis meta sendiri` (does not define its own meta) | a concrete subclass without `meta` | add `meta = ScraperMeta(...)` |
| `DuplicateScraperId` | the `id` is already used by another file | change the slug |
| `parse_error ... gak ada node di item_path` (no nodes at item_path) | an Atom feed but `item_path` is the RSS default | set `item_path`/`link_attr` for Atom |
| `parse_error ... XML gak valid` (invalid XML) | a broken/blocked feed, sometimes a challenge page | `curl` the URL and check its content; it may need `xml_fixups`, or the site blocks bots |
| `fetch_error` 403/429 | the site blocks the UA/rate | lower `rate_limit`, check whether it needs `browser` |
| always `empty` | wrong selector, or the source really is quiet | compare with the page content from `curl` |
| The new scraper never runs | `beat` has not been restarted | `docker compose up -d --build beat` |
| The `/scrapers` UI does not show the new scraper | `api` has not been rebuilt | rebuild `api` |
| The first run produced 5 articles that were not wanted | the cold-start cap (normal) | use `--prime` before it is scheduled |
