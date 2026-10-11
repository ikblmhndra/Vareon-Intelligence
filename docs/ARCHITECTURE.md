# Architecture

How Vareon Intelligence moves data from ~95 sources to the analyst's screen and to Telegram. It covers the
runtime topology, the three main data flows, who reads and writes which store, the code path to read for each
flow, and the design decisions and open risks a reviewer should know about.

Everything here was read from the code at `e44d4bc` (2026-10-10). Code references name the file and the
symbol, not line numbers, so they survive edits. When the code changes, update this file.

Related: `CLAUDE.md` (commands and conventions), `docs/CVE_TRACKER_FLOW.md` (CVE Tracker in depth),
`docs/ADDING_A_SCRAPER.md`, `docs/CI_CD.md`.

## 1. Overview

The system is a one-way pipeline glued together by **Celery on Redis**, with **Postgres** as the only durable
store.

1. **Ingest.** Scrapers (RSS, HTML, APIs, X/Twitter, GitHub) run on a cron schedule and yield typed items.
2. **Enrich.** Articles go through an NLP + LLM pipeline: classification, full text, summary, IOCs, MITRE
   ATT&CK TTPs, threat actor / country / industry scoring.
3. **Serve and alert.** FastAPI serves the data to a Next.js UI. Telegram receives routed alerts, and
   Microsoft Graph sends mail (newsletter, CVE).

Ingest is fast (seconds per run). Enrichment is slow (~10-13 s plus LLM time per article). The two halves
therefore run on different queues and worker images, with backpressure between them (section 3.1).

## 2. Components and runtime topology

### Workspace packages

| Package | Path | Role |
|---|---|---|
| `cti-core` | `packages/cti-core` | Settings, SQLAlchemy models and repositories, LLM client, IOC extractor, CVE mirror and promotion. Every other package depends on it. |
| `cti-scraper` | `packages/cti-scraper` | Scraper framework: `BaseScraper`, `ScraperMeta`, registry, `Runner`, dedup, sinks, rate limiting, CLI. |
| `cti-scrapers` | `scrapers/` | The scraper plugins: `feeds/` (one file per source) and `collectors/` (bespoke). Auto-discovered. |
| `cti-enrich` | `packages/cti-enrich` | Enrichment pipeline and its stages. The `nlp` extra (spaCy, sumy) is installed only in the `worker-nlp` image. |
| `cti-alerts` | `packages/cti-alerts` | Telegram and Microsoft Graph mail. |
| `cti-api` | `apps/api` | FastAPI: thin `routers/` → `services/` → `cti_core` repositories. |
| `cti-worker` | `apps/worker` | Celery app, tasks, beat. **Depends on `cti-api`** (section 7, note 6). |
| web | `apps/web` | Next.js 16 App Router UI. Never calls `cti-api` from the browser directly. |

### Compose services

| Service | Command / queues | Notes |
|---|---|---|
| `postgres`, `redis` | | Redis runs with AOF (`--appendonly yes`). |
| `migrate` | `alembic upgrade head` | The only process that migrates. API and workers never do. |
| `api` | uvicorn, several processes | `lifespan` bootstraps reference rows under a Postgres advisory lock. |
| `worker` | `-Q scrape.rss,scrape.api,notify,maintenance` | Light scrapers, notifications, periodic maintenance. |
| `worker-browser` | `-Q scrape.browser` | Scrapers with `runtime="browser"` (Playwright/Chromium). |
| `worker-nlp` | `-Q enrich` | Enrichment. Image includes spaCy and sumy. |
| `beat` | `python -m cti_worker.beat_main` | Singleton: holds a Redis lock (`cti:beat:lock`) and renews it. |
| `web`, `nginx` | | Next.js server and the TLS reverse proxy. |

One Celery app (`cti_worker.celery_app`) serves every worker. The `-Q` flag picks the role. Tasks use
`acks_late`.

## 3. Data flows

### 3.1 Scrape → enrich → alert

```mermaid
flowchart LR
  beat["beat<br/>build_beat_schedule"] -->|"cron tick<br/>expires after 1 interval"| q["scrape.rss / scrape.api / scrape.browser<br/>queue_for(meta)"]
  q --> run["scrape.run → Runner.execute<br/>scraper_runs row"]
  run -->|per yielded item| dedup{"scraper_seen<br/>reserve lease"}
  dedup -->|duplicate / lease held| drop((drop))
  dedup -->|reserved| sink{"sink by item type"}
  sink -->|non-article items| direct["direct-write sinks<br/>ransomware, CVE, PoC, IOC feed,<br/>tweets, notices"]
  sink -->|ArticleItem| bp{"LLEN enrich<br/>≥ max depth?"}
  bp -->|full: release lease,<br/>run = backpressure| run
  bp -->|send_task| enrich["enrich.article<br/>(worker-nlp)"]
  enrich --> cls{"classify (LLM)<br/>related_cyber?"}
  cls -->|no| rej[("rejected_articles")]
  cls -->|yes| stages["fetch text → summarize → IOCs<br/>→ TTPs → score → route"]
  stages --> persist[("articles + IOCs<br/>commit")]
  persist -->|after commit| tg(("Telegram topics"))
```

**Scheduling.** `cti_worker.beat.build_beat_schedule` runs once, at import. It reads the scraper registry and
the `scraper_config` rows, skips scrapers that are disabled or superseded (`cti_scraper.supersede.
effective_enabled`), and adds one `scrape.run` entry per scraper. The queue comes from
`cti_scraper.queues.queue_for`: `scrape.browser` for `runtime="browser"`, `scrape.api` for scrapers with a
`credential`, `scrape.rss` otherwise. Each tick expires after one schedule interval (`_tick_expiry_s`).

**A run.** `scrape.run` (`apps/worker/src/cti_worker/tasks/scrape.py`) builds a `Runner` and calls
`execute()`. The runner re-reads `scraper_config` (so disabling takes effect at once), writes a
`scraper_runs` row, resolves credentials and `reference_data`, and iterates over `scraper.fetch(ctx)`. A scraper
with no `scraper_seen` rows is "cold": only its newest `scraper.cold_start_max_items` (5) items are
dispatched and the rest are marked seen.

**Per item** (`Runner._handle_item`):

1. `DedupStore.reserve` inserts or steals a `scraper_seen` lease (`in_flight`, 15 minutes). A row that is
   `done`, or `in_flight` with a live lease, means drop.
2. `sinks.dispatch` picks the sink registered with `@sink_for(<ItemType>)`.
3. The session commits, then `DedupStore.commit` marks the key `done` with `dedup_ttl_days`, and commits again.
4. On a sink error the lease is released, so the next run retries the item.

**Article sink.** `_article_sink` does not touch Postgres. It checks `ensure_enrich_capacity` (Redis `LLEN
enrich` against `scraper.enrich_queue_max_depth`) and then `send_task("enrich.article")`. When the queue is
full it raises `BackpressureError`: the runner releases the lease and stops the run with status
`backpressure`.

**Other sinks** (ransomware victims, CVEs, PoCs, malware trends, IOC feeds, tweets, CVE mentions, notices)
write Postgres directly from the scrape worker.

**Enrichment** (`cti_enrich.pipeline.run_pipeline`):

1. `classify(title)`. If `related_cyber` is false, write a light `rejected_articles` row and return.
2. `fetch_text` → `summarize` → `extract_iocs` and the C2 check.
3. If `security_tech_best_practice`, skip TTPs and scoring: persist and alert on the `best_practice` topic.
4. Otherwise `extract_ttps` (normalised against the ATT&CK catalog), `score`, `routing.route`.
5. `persist` upserts `articles` by `url_hash` and writes countries, industries, threat actors, TTPs and IOCs.
   It also deletes any `rejected_articles` row for the same URL.
6. **Commit**, track CVE mentions (new articles only), then `route_alerts` sends one Telegram message per
   topic.

**Failure policy** (`apps/worker/src/cti_worker/tasks/enrich.py`). Transient errors (LLM connection, 5xx,
429 that is not quota, network, DB connection) retry up to 6 times with 30 s → 10 min backoff and jitter.
Broken JSON retries twice. On the final failure `on_failure` writes `rejected_articles` with reason
`[enrichment_failed] ...` (secrets scrubbed), unless the article was already persisted.

### 3.2 Read path: UI → API → Postgres

```mermaid
sequenceDiagram
  participant B as Browser
  participant G as Next proxy.ts
  participant R as Route Handler /api/proxy
  participant A as FastAPI deps
  participant X as Redis
  participant D as Repo (asyncpg)
  B->>G: page navigation
  G-->>B: no session cookie → redirect /login (no JWT check)
  B->>R: fetch /api/proxy/api/... + X-Client-ID
  R->>A: forward with Authorization: Bearer <httpOnly cookie>
  A->>X: decode JWT, MGET revoked_user:<sub>, revoked_jti:<jti>
  X-->>A: revoked → 401
  A->>D: router → service → repository
  D-->>B: JSON, or raw bytes for xlsx/docx exports, relayed as-is
```

- `apps/web/src/proxy.ts` is an **optimistic** guard: it only checks that the `cti_session` cookie exists.
- `apps/web/src/app/api/proxy/[...path]/route.ts` is the only way client components reach the API. It reads
  the httpOnly cookie server-side, adds `Authorization: Bearer`, forwards `X-Client-ID` and the client IP
  headers, and relays the body as raw bytes.
- `cti_api.deps.get_current_user` does the real enforcement: JWT decode, Redis revocation check
  (`token_revocation.is_revoked`), and the force-password-change gate.
- **Tenancy.** `deps.effective_client_id` picks the active client from `X-Client-ID` (any value for
  superadmin; otherwise only one of the user's `client_ids`). `deps.ensure_client_access` answers 404, not
  403, for another client's object. Only routers that call these are tenant-scoped (section 7, note 4).
- Roles: `require_auth`, `require_admin` (admin or superadmin), `require_superadmin`.

### 3.3 CVE Tracker ingest

`techstack_entries` (per client) decides which CVEs reach `cve_tracker`. Two ingest paths exist:

```mermaid
flowchart LR
  tech[("techstack_entries<br/>per client")]
  tech -->|reference_data| newcve["new_cve scraper<br/>hourly, scrape.api"]
  newcve --> sup{"superseded<br/>by mirror?"}
  sup -->|no| cvesink["_cve_sink<br/>upsert (cve_id, client_id)"]
  cvesink --> tracker[("cve_tracker<br/>+ references, affected")]
  mirror["cve.mirror_sync<br/>every 5 min, maintenance"] --> apply["apply_record<br/>cve_records + catalog resolve"]
  apply -->|created / updated| mode{"CVE_MIRROR__PROMOTE"}
  tech -.->|load_entries| mode
  mode -->|shadow| shadow[("cve_promotion_shadow")]
  mode -->|live| live["_promote_live"]
  live --> tracker
  tracker -->|rows created this run| notify(("new-CVE<br/>Telegram summary"))
  sweep["cve.enrichment_sweep<br/>every 3 h: KEV, Exploit-DB, EPSS"] -.-> tracker
  monitor["cve.promote_entry<br/>enqueued by API on Monitor"] -.-> live
```

- **Legacy path.** `new_cve` (`scrapers/src/cti_scrapers/feeds/new_cve.py`) searches NVD and Tenable per tech
  name, fetches MITRE detail per candidate, applies a relevance gate, and yields one `CveItem` per affected
  client. `_cve_sink` upserts on `(cve_id, client_id)` and collects newly created rows. `finish_run` sends one
  summary at the end of the run.
- **Mirror path.** `cve.mirror_sync` (`cti_core.cve_mirror_sync.sync_once`) takes a session-level Postgres
  advisory lock, reads the cvelistV5 delta log, keeps a cursor and a retry queue in `job_state`, and applies
  each record to `cve_records` with catalog resolution. Promotion runs in the same savepoint.
- **Modes.** `off`: mirror only. `shadow`: write `cve_promotion_shadow` to compare against `new_cve`. `live`:
  upsert `cve_tracker` and suspend `new_cve` (`supersede.superseded_by_mirror`). Rollback is the flag. Runbook:
  `docs/CVE_CATALOG_CUTOVER.md`.
- **Enrichment.** `cve.enrichment_sweep` calls `cti_api.services.cve_lookup` (CISA KEV, Exploit-DB, EPSS) and
  writes the result to every client's row for that `cve_id`.

Full detail, including ticketing and the tech matchers: `docs/CVE_TRACKER_FLOW.md`.

### 3.4 Periodic jobs

Beat also schedules non-scraper tasks (`cti_worker.beat._periodic_schedule`, `_report_schedule`):

| Task | Queue | Does |
|---|---|---|
| `scraper.purge_expired_items`, `scraper.purge_expired_seen` | maintenance | Delete expired `scraper_items` and `scraper_seen` rows. |
| `scraper.health_digest` | notify | One Telegram message summarising unhealthy scrapers; silent when all are fine. |
| `pir.check_p1_alerts`, `pir.check_all_alerts` | notify | Match new articles against PIRs and alert. |
| `attack.sync_check`, `ioc.decay_sweep` | maintenance | Re-sync the ATT&CK catalog when older than `worker.attack_sync_interval_days`, IOC confidence decay. |
| `recap.generate_weekly` | maintenance | Monday 00:15 UTC (07:15 WIB): the weekly recap for the Monday-Sunday week (UTC dates) that ended the day before, one LLM call from aggregates, none for a week without articles, tweets or CVEs. There is no scheduled daily recap; a single day is still generated by hand with `POST /api/recap/generate?kind=daily`. |
| `cve.enrichment_sweep`, `cve.mirror_sync`, `cve.mirror_purge` | maintenance | Section 3.3. |
| `report.*` (daily counters, news of the day, logbook, weekly top CVE, trending CVE, threat actor trend) | notify | Scheduled Telegram reports. |

Tasks that need business logic call the async `cti_api.services.*` functions through
`cti_worker.tasks.periodic._run_async`, which wraps `asyncio.run` and resets the async engine afterwards.

## 4. Data stores and access patterns

Postgres is reached through two drivers: **sync psycopg** in Celery and the CLI (`cti_core.db.engine.
sync_session`), and **async asyncpg** in FastAPI (`deps.get_db`). The schema has about 70 tables; the hot ones:

| Table | Key | Written by | Read by |
|---|---|---|---|
| `scraper_config` | `scraper_id` | API (control plane) | beat (once, at import), `Runner` (every run), API |
| `scraper_runs` | `run_id` | `Runner.execute` (start, finish) | API (`/scrapers`), `scraper.health_digest` |
| `scraper_seen` | `dedup_key` = sha256(`scraper_id`, raw key) | `Runner` via `DedupStore` (reserve, commit, release) | `Runner` |
| `articles` (+ `article_countries`, `_industries`, `_threat_actors`, `_ttps`) | `url_hash` (unique) | `enrich.article` (`ArticleRepo.upsert`) | API, reports, PIR alerts |
| `rejected_articles` | `url_hash` | `enrich.article` (not cyber, or final failure) | API (Filtered Articles; restore) |
| `iocs` (+ sources, tags, actors, feedback) | `(type, value)` | `enrich.article`, IOC feed sink | API, `ioc.decay_sweep` |
| `techstack_entries` | `(name, client_id)` | API (techstack, catalog) | `new_cve` (`reference_data`), promotion, API |
| `cve_tracker` (+ `cve_references`, `cve_affected`, ...) | `(cve_id, client_id)` | `_cve_sink`, `_promote_live`, `cve.enrichment_sweep` | API (CVE tab, dashboards, export) |
| `cve_records` (+ `cve_record_products`) | `cve_id` | `cve.mirror_sync` | promotion, API (CVE DB) |
| `job_state` | key | `cve.mirror_sync` (cursor, pending retries) | `cve.mirror_sync` |

Redis plays four roles at once:

| Key | Role | Written by | Read by |
|---|---|---|---|
| lists `scrape.*`, `enrich`, `notify`, `maintenance` | Celery broker | beat, API (manual trigger, promote entry), `_article_sink` | workers; `_article_sink` (`LLEN enrich`) |
| `revoked_user:<sub>`, `revoked_jti:<jti>` | JWT revocation | API (logout, password/role/client change) | API, on every authenticated request |
| `cti:ratelimit:<domain>` | per-domain token bucket | `ScraperHttpClient` via `TokenBucket` | same |
| `cti:beat:lock` | beat singleton | `beat_main` (acquire, renew) | `beat_main` |

## 5. Code paths to read

Read these in order. Each starts at a real entry point.

**1. Beat tick → one scraper run**

1. `apps/worker/src/cti_worker/beat.py`: `build_beat_schedule`
2. `apps/worker/src/cti_worker/tasks/scrape.py`: `run_scraper` (task `scrape.run`), via the `scrape.*` queue
3. `packages/cti-scraper/src/cti_scraper/runner.py`: `Runner.execute` → `_run_body` → `_handle_item`
4. `packages/cti-scraper/src/cti_scraper/sinks.py`: `dispatch` → `_article_sink` / other sinks

**2. `enrich.article` → stored article and alerts**

1. `apps/worker/src/cti_worker/tasks/enrich.py`: `enrich_article`, `_EnrichTask.on_failure`
2. `packages/cti-enrich/src/cti_enrich/pipeline.py`: `run_pipeline`
3. `packages/cti-enrich/src/cti_enrich/stages/`: `classify`, `fetch_text`, `summarize`, `extract_iocs`,
   `extract_ttps`, `score`
4. `packages/cti-enrich/src/cti_enrich/routing.py`: `route`
5. `packages/cti-enrich/src/cti_enrich/stages/persist.py`: `persist` → `ArticleRepo.upsert`
6. `packages/cti-enrich/src/cti_enrich/stages/alert.py`: `route_alerts` → `cti_alerts.telegram.send_alert`

**3. Analyst opens a page → API → Postgres**

1. `apps/web/src/proxy.ts`: route guard
2. `apps/web/src/app/api/proxy/[...path]/route.ts`: cookie → Bearer
3. `apps/api/src/cti_api/deps.py`: `get_current_user`, `effective_client_id`, `ensure_client_access`
4. A router, e.g. `apps/api/src/cti_api/routers/articles.py`: `list_articles`
5. A repository, e.g. `packages/cti-core/src/cti_core/db/repositories/article.py`:
   `AsyncArticleRepo.list_filtered`

**4. CVE mirror sync**

1. `apps/worker/src/cti_worker/tasks/cve_mirror.py`: `cve_mirror_sync`
2. `packages/cti-core/src/cti_core/cve_mirror_sync.py`: `sync_once` → `_sync_locked` → `_process` →
   `apply_record`
3. `packages/cti-core/src/cti_core/cve_promotion.py`: `promote_record` → `_promote_live` / `_promote_shadow`

## 6. Design decisions

- **Lease-based dedup, marked after success.** `scraper_seen` rows start `in_flight` with a lease and become
  `done` only after the sink commits. A worker that crashes mid-item leaves an expired lease, and the next
  run takes the item again. The old system marked items before processing and lost them on failure.
- **Retry the whole run, not each request.** `ScraperHttpClient` does not retry. `Runner` turns
  `TransientFetchError` and `RateLimited` into a run status, and `scrape.run` retries the run with
  60 s → 600 s backoff (never shorter than `retry_after`). Retried runs are recorded as `beat_retry` /
  `manual_retry`. `ParseError` (the site changed) is never retried.
- **Stale ticks expire.** A scrape tick that waited longer than one schedule interval is dropped. This stops
  a thundering herd (and source bans) when a worker comes back after an outage. Other periodic tasks do not
  expire: late is better than lost.
- **Backpressure between ingest and enrichment.** Scrapers stop sending articles once the `enrich` queue is
  at `scraper.enrich_queue_max_depth`, instead of letting Redis grow without bound.
- **Commit before alerting.** The pipeline commits the article before calling `route_alerts`, so a Telegram
  failure cannot roll back stored intelligence.
- **Nothing that passed dedup is lost silently.** Rejected and failed articles land in `rejected_articles`,
  where analysts can review and restore them.
- **Sink chosen by item type.** Scrapers only yield typed items; `@sink_for` in one file decides where each
  type is stored. `fetch()` has no DB access, so scrapers stay testable with recorded HTTP fixtures.
- **One business-logic implementation.** Periodic tasks call the same `cti_api.services` functions as the API
  buttons, instead of duplicating them in the worker.
- **Strict configuration.** `Settings` uses `extra="forbid"` at every level: an unknown or misspelled key
  stops the process at start-up.

## 7. Known risks and open questions

1. **Cross-source repeats pay for full enrichment and re-alert.** Dedup keys are namespaced per scraper
   (`dedup.compute_dedup_key`), so the same URL from two feeds runs the whole LLM pipeline twice.
   `ArticleRepo.upsert` only increments `seen_count`, and `route_alerts` runs regardless of `seen_count`
   (only CVE-mention tracking checks it). Decide whether the second Telegram post is intended.
2. **An alert that fails after commit is dropped, not retried.** `send_alert` lets
   `telegram.error.NetworkError` propagate. That class derives from `TelegramError`, not
   `httpx.TransportError`, so it is not in `_TRANSIENT_ERRORS`. The task fails, `on_failure` sees the article
   already exists, and only a log line (`enrich_failed_after_persist`) remains. With several topics, the ones
   sent before the failure went out and the rest are lost. The article itself is safe.
3. **Backpressure counts queued messages only.** `LLEN enrich` excludes messages that workers have prefetched
   but not yet acknowledged. The default limit (2000) is described in the code as a first guess.
4. **Tenancy is per router, not per table.** Articles, IOCs and the article dashboard (`/api/dashboard`) are
   global. Only routers that call `effective_client_id` are scoped: cve, techstack, pir, rfi, pkg_vuln,
   ta_groups, catalog, cve_db, exec_dashboard, intelligence. Confirm that shared news and IOCs are meant to
   be visible to every tenant.
5. **Redis is on both the auth path and the ingest path.** Every authenticated request does a revocation
   `MGET`, and the same Redis is the broker, the rate limiter and the beat lock. A Redis outage takes down
   the UI and scraping together.
6. **The worker depends on the API package.** Periodic tasks import `cti_api.services` and run them with
   `asyncio.run`, which needs an engine reset after each call to avoid asyncpg pools bound to a closed loop
   (`_run_async`). The worker image ships the API code.
7. **The schedule is static.** Schedule and `enabled` overrides apply only after beat restarts.
   `Runner` re-checks `enabled` at run time, so disabling takes effect immediately; enabling a scraper or
   changing its schedule does not. The `/scrapers` page needs an API restart for new scrapers.
8. **CVE enrichment cost grows linearly.** `cve.enrichment_sweep` re-checks every true-positive CVE every
   3 hours with no freshness filter (Exploit-DB is the heaviest: per-CVE HTTP in batches of 5).
9. **Two CVE ingest paths coexist** with different matchers until cutover. Shadow mode exists to compare
   them; see `docs/CVE_CATALOG_CUTOVER.md`.
