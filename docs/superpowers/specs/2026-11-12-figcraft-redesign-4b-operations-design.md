# FigCraft redesign, sub-project 4b: Operations (Scrapers, Data Health)

Date: 2026-11-12. Status: draft for review. Branch: `claude/figcraft-design-data`. Same one-PR release 0.8.16
(the CHANGELOG entry and the 0.8.16 runbooks are extended, no extra version bump).

## 1. Context and goal

Sub-projects 1, 2a, 2b, 3 and 4a delivered the shell and the shared primitives in `apps/web/src/components/ui/`
(`MasterDetail`, `StatTile` with `onSelect`, `Chip`, `StatePanel`, `Notice`, `SegmentedControl`, `FilterSelect`,
`SearchInput`, `Disclosure` with `printOpen`, `Sheet`, `MeterBar`, `BarSeries`, `LegendRow`, `ConfirmDialog`,
`PageHeader` with `kicker`), the browser-timezone formatters in `apps/web/src/lib/format.ts` (`fmtTime`, `fmtDateTime`,
`fmtShortDate`, `fmtAgo`, `fmtCompactAge`, `browserZoneName`), `lib/use-page-title.ts::usePageTitle` and
`lib/exec/query.ts::isClientError`. This spec is **4b: the two operations pages, Scrapers and Data Health**.
Sub-project 4 is split into 4a (Content, done), 4b (this spec) and 4c (Login, Admin, session-expired dialog).

FigCraft frames (light; dark variant in brackets): Scrapers / List 28315 (29465), Scrapers / Dialogs 34979 (36034,
Disable dialog only), Data Health / D1 3258 (3819). There is no states frame for either page, no frame for the
config editor, the reset confirms, run history, the enable / run-now / dry-run feedback, or the Data Health
sections the mockup leaves out (CVE ingest, Sigma rules, Enrichment detail).

Today both pages are pre-redesign. Scrapers is a status line, a pill bar, an eight-column table with a row menu and a
424-line detail dialog. Data Health is one 400-line `DataHealthView` that stacks `Section` cards of label / value
rows with tone pills. The mockup turns Scrapers into tiles, a table and a side panel, and Data Health into a
tile row, a pipeline flow, a calls-per-hour chart and compact cards.

Goal: deliver the **full mockup, keep every existing feature reachable** (S1-S17, DH1-DH12 in the gap inventory),
and add the data the Data Health mockup needs (B-DH1, B-DH2, B-DH3). Scrapers needs no backend change. Backend lands
first, the contract is regenerated once, then the pages are built on real data. The inventory behind this spec
(`.superpowers/brainstorm/sp4-inventory.md`, not committed) lists every frame element and its source; where they
differ, this spec wins.

## 2. Decisions (binding, from the user)

Scope
- **S1** 4b covers `/scrapers` and `/data-health` only. Login, Admin and the session-expired dialog are 4c.
- **S2** Full mockup; every pre-redesign feature stays reachable, re-homed where the mockup has no place (maps in
  6.1 and 6.2).
- **S3** Release stays 0.8.16, one PR; `CHANGELOG.md` (Indonesian), `docs/prod-upgrade/0.8.16.md` and
  `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` are extended. No migration, no `.env` key.
- **S4** The inventory defaults that shape 4b are accepted:

| Id | Decision |
|---|---|
| D7 | UI copy in English (the two Indonesian confirm texts in the scraper detail are rewritten). |
| D16 | Data Health kicker is "OPERATIONS"; "ADMIN ONLY" is dropped. |
| D17 | Build B-DH1, B-DH2 and B-DH3; no breaker open / close caption under the chart. |
| D18 | CVE ingest, Sigma rules and Enrichment detail move to a "More checks" row; the usage table gets a 24 h / 7 d switch. |
| D19 | Freshness thresholds stay the code's: articles 6 / 24 h, tweets and IOC 24 / 72 h, CVE check 6 / 24 h; the "watch after" captions print them. |
| D20 | Six health tiles for the real statuses; PARTIAL is dropped (B-S2 declined). |
| D21 | RUNTIME column = queue suffix; filters Status / Runtime / Queue; schedule humanized with the raw cron in a tooltip; NEXT as local clock time; no beat-lock line (B-S1 declined). |
| D22 | A `MasterDetail` side panel replaces the detail dialog; Edit config, Reset config, Reset dedup, the options select, Recent Runs paging and Recent Items stay one click away. |
| D32 | Browser time zone everywhere, with `browserZoneName()` where a zone is printed. |
| D34 | One contract regen for 4b (B-DH1 to B-DH3 together). |

Choices this spec makes that the user did not spell out (each is flagged for review):
- **P1** `cve` is included in the queue depths, so the block lists seven queues, not the mockup's six (C7).
- **P2** The flow's "· 10 s each" is dropped (C6).
- **P3** The chart has two series, ok and failed (failed = `error` + `empty`), not the mockup's three (C9).
- **P4** The Scrapers selection lives in the URL as `?scraper={id}`; with no parameter nothing is selected.
- **P5** Write controls are hidden without `manage_scraper` (today the detail dialog shows them disabled).
- **P6** The FRESHNESS tile shows the worst of the five freshness rows, not always the tweet row (C11).
- **P7** "More checks" is collapsed by default and opens by itself when CVE ingest or Sigma is not OK.
- **P8** The health tiles are clickable and set the Status filter.

## 3. Conflicts between inputs, and how they are resolved

- **C1 Who sees Data Health.** Mockup kicker "OPERATIONS · ADMIN ONLY"; both routers depend on
  `require_permission("view_ops")`, which the analyst role has (`services/roles.py`). Kicker "OPERATIONS" (D16).
- **C2 Time zone.** Mockup "Generated 14:32 UTC" and "since 14:26 UTC"; convention is the browser zone (D32):
  "Generated {fmtTime} {browserZoneName()}". The current page uses `lib/cve/freshness.ts::formatWib` and Scrapers
  prints raw UTC strings; both stop.
- **C3 Scraper statuses.** PARTIAL is a run status, not one of the six `HealthStatus` values, and the frames
  disagree on counts (OK 84 vs 88). Six tiles (D20); the legend keeps its "Partial" entry so the word in LAST RUN
  stays explained.
- **C4 Runtime column vs Runtime filter.** Mockup RUNTIME cells read rss / api / browser (the queue suffix) while
  the code's `runtime` is `light | browser` and `queue` is `scrape.rss | scrape.api | scrape.browser`. Resolved
  (D21): the column prints the queue suffix with `title` "runtime {runtime} · queue {queue}"; the **Runtime** filter
  keeps the real `runtime` values (S5 unchanged); the **Queue** filter is new and uses the full queue names.
- **C5 Beat lock holder.** "beat lock held by worker-2" is not exposed by any endpoint. The line is dropped.
- **C6 Pipeline flow is not a funnel.** `scraper_runs.items_found` / `items_new` count every item type (articles,
  IOCs, CVEs, tweets), while only articles pass through `enrich`; steps 3 and 4 are live values, not window totals.
  The card says so in a caption (6.2). "· 10 s each" is an estimate the page cannot measure and the LLM is no longer
  on that path (P7g), so it is dropped (P2).
- **C7 Queues.** The mockup lists six queues. `cti_worker/queues.py` and `cti_scraper/queues.py` define seven:
  `scrape.rss`, `scrape.api`, `scrape.browser`, `enrich`, `notify`, `maintenance`, `cve`. `cve` has its own worker
  with concurrency 1, which is where a backlog is most likely, and it costs one more `LLEN`; it is included (P1).
  The heading "CELERY QUEUES, DEPTH NOW" names no number, so the copy is unchanged.
- **C8 "articles published".** The inventory says "count by `created_at`"; `articles` has no such column. The
  count uses `Article.first_seen_at`, the column `processed_since` and `newest_article_at` already use.
- **C9 Chart legend.** Mockup legend "ok / error / empty". The approved field is `{hour, ok, failed}`. `llm_calls.status`
  is `ok | empty | error`; failed = `error` + `empty`, the same rule as `LlmTaskUsageOut.errors`. Legend: "ok",
  "failed (error or empty reply)". An hour without calls has both values 0 and draws no bar.
- **C10 Chart caption.** "breaker opened 23:10, closed 01:40" would need a replay of the breaker; skipped (D17).
  The live breaker state is the chip above the chart.
- **C11 Freshness numbers.** Mockup captions "watch after 1 h" (tweets), "runs daily" (CVE check), "runs weekly"
  (ATT&CK) contradict the code. Captions print the code thresholds (6.2). The FRESHNESS tile in the mockup always
  shows the tweet age; a tile that reads OK while articles are a day old would mislead, so it shows the worst row
  (P6).
- **C12 "no data lost".** The status block ("4 scrapers need attention · no data lost") and the legend ("WATCH:
  slower than usual, no data lost") claim something the payload cannot prove. Both phrases are removed (6.2).
- **C13 Prompt version.** Mockup "v7", "v4"; `prompt_version` is the first 8 hex of the prompt's sha256 or null.
  The PROMPT column prints it in `font-code`, "–" when null.
- **C14 Failed jobs fact.** Mockup "3 (0.4% of 7 d)" has no single reading. It becomes "{failed_24h} · 7 d: {failed_7d}
  of {processed_7d} processed ({pct})", the figures the page shows today.
- **C15 PIPELINE tile denominator.** "88 / 96": 96 is the whole fleet including disabled. Kept as `counts.ok` /
  sum of `counts`, so the tile and the fleet footer agree.
- **C16 Stories card.** "24 H | 7 D" in the frame are two table columns, not a switch. Rendered as a two-column
  table.
- **C17 Rate limit copy.** Mockup "1 req / 2 s" is sample text; the panel prints the API string as it is
  (`config.rate_limit ?? default_rate_limit`).
- **C18 Disable in the panel.** Today the detail dialog disables immediately with the "Paused reason" field as the
  reason, while the row menu opens the reason dialog. Both now open the one Disable dialog.
- **C19 Page headers.** Both headers carry live content in `actions` (scheduler chip, status block) and the Data
  Health subtitle carries "Generated", so the views render `PageHeader`; the layouts keep only `metadata`.

## 4. Backend

Conventions. Only `GET /api/data-health` changes; `routers/scraper.py` is untouched. Router
`routers/data_health.py` keeps `require_permission("view_ops")` + `require_auth`. Comments and docstrings in
Indonesian, matching the files. All three items are additive response fields inside the existing 60 s per-process
cache (`_CACHE_TTL`), so each query below runs at most once per minute per uvicorn process. New fields change
`docs/openapi.json` → `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`, once, after all
three items.

### 4.1 B-DH1 `pipeline`: items fetched, new and published per window
- **Contract.** `DataHealthOut.pipeline: PipelineHealthOut`; `PipelineHealthOut { last_24h: PipelineWindowOut,
  last_7d: PipelineWindowOut }`; `PipelineWindowOut { items_found: int, items_new: int, articles_published: int }`.
  All ints, 0 when there is no row.
- **Logic.** `AsyncDataHealthRepo.pipeline_totals(now) -> PipelineTotals` (frozen dataclass holding the two
  windows), two statements:
  1. `scraper_runs`: `select coalesce(sum(items_found) filter (where started_at >= now - 24h), 0),
     coalesce(sum(items_new) filter (...24h), 0), coalesce(sum(items_found), 0), coalesce(sum(items_new), 0)
     where started_at >= now - 7d`. Every run status counts, including `running` (its counters are whatever is
     stored) and manual triggers; dry runs write no row and are therefore excluded.
  2. `articles`: `select count(*) filter (where first_seen_at >= now - 24h), count(*) where first_seen_at >=
     now - 7d` (C8). Rejected articles are not counted: "published" means the row is in `articles`.
  `_build` calls it once and maps to the schema. Windows are rolling from `now`, the same `now` as the rest of
  the payload.
- **Performance.** Neither `scraper_runs.started_at` nor `articles.first_seen_at` is indexed, so both are
  sequential scans. `scraper_runs` is bounded by retention (`scraper_run_retention_days` 90, about 1-2 thousand
  rows a day, so under 200 thousand narrow rows); `articles` is already scanned twice per build by
  `processed_since` and `newest_article_at`. No index is added (no migration in 4b). See Risks.
- **Tests.** `tests/integration/test_data_health_api.py::test_data_health_pipeline_windows`: runs at 1 h, 30 h and
  8 d old with distinct counters, one `running` run, articles at 1 h, 3 d and 8 d, one rejected article → asserts
  both windows. `::test_data_health_pipeline_empty` → all six values 0.

### 4.2 B-DH2 `queues.depths`: depth of every Celery queue
- **Contract.** `QueueHealthOut.depths: dict[str, int] | None`. Keys, always all seven when not null:
  `scrape.rss`, `scrape.api`, `scrape.browser`, `enrich`, `notify`, `maintenance`, `cve`. `None` when Redis cannot
  be read. `enrich_depth` and `enrich_max_depth` stay (the X Intel chip and existing tests read them);
  `enrich_depth == depths["enrich"]`, and both are null together.
- **Logic.** `services/data_health.py`: `_QUEUES = (*ALL_SCRAPE_QUEUES, "enrich", "notify", "maintenance", "cve")`
  with `ALL_SCRAPE_QUEUES` imported from `cti_scraper.queues` (already an API dependency) and the other four as
  literals, because `cti_api` must not import `cti_worker`. `_enrich_depth` is replaced by
  `_queue_depths(redis) -> dict[str, int] | None`: one `try` around sequential `await redis.llen(name)` calls;
  any exception returns `None` for the whole block (the page still renders, as today). `LLEN` on a key that does
  not exist returns 0, which is correct: Redis deletes an empty list, so an idle queue has no key. `_build` calls it
  once and derives `enrich_depth` from the result.
- **Meaning.** The value is messages waiting in the broker list. Messages a worker has reserved but not yet
  acknowledged (`acks_late`, prefetch) are not in the list, so "0" means nothing is waiting, not nothing is
  running. The UI caption says "waiting" (6.2).
- **Tests.** `test_data_health_api.py::test_data_health_queue_depths` (push to `enrich` and `cve` in `fake_redis`,
  the other five read 0, `enrich_depth` equals `depths["enrich"]`);
  `::test_data_health_survives_a_redis_outage` extended to assert `depths is None`.
  `tests/unit/test_queue_names.py::test_data_health_queue_names_match_worker`: `set(_QUEUES)` equals the scrape
  queues plus `cti_worker.queues.QUEUE_ENRICH / QUEUE_NOTIFY / QUEUE_MAINTENANCE / QUEUE_CVE`, so a renamed or new
  queue fails a test instead of silently reading 0.

### 4.3 B-DH3 `llm.calls_per_hour`: 24 hourly buckets
- **Contract.** `LlmHealthOut.calls_per_hour: list[LlmHourOut]`, `LlmHourOut { hour: str, ok: int, failed: int }`.
  Always exactly 24 entries, oldest first. `hour` is the ISO 8601 UTC start of the bucket (`…T14:00:00+00:00`). The
  last entry is the current, still running hour; the first starts 23 hours before it.
- **Logic.** `AsyncLlmCallRepo.calls_per_hour(since) -> dict[datetime, tuple[int, int]]`: `select
  date_trunc('hour', timezone('UTC', at)), count(*) filter (where status = 'ok'), count(*) filter (where status in
  ('error', 'empty')) from llm_calls where at >= :since group by 1`. `timezone('UTC', at)` makes the truncation
  independent of the session `TimeZone`. All tasks are counted (the chart is gateway traffic, not only
  classify / ttp). The service computes `start = now.replace(minute=0, second=0, microsecond=0) - 23 h`, calls
  the repo with `since=start`, and zero-fills the 24 buckets in Python; a status outside the three known values
  counts in neither series.
- **Performance.** Range scan on `ix_llm_calls_at` over 24 hours of rows.
- **Tests.** `test_data_health_api.py::test_data_health_llm_calls_per_hour`: no rows → 24 entries of zeros, ordered,
  last `hour` = the current UTC hour; rows `ok`, `error` and `empty` in the same hour → `ok 1, failed 2`; a row
  exactly at `start` is in the first bucket; a row one second before `start` is absent; rows of two different tasks
  add up.

### 4.4 Documentation touched
- `CHANGELOG.md`, 0.8.16 entry (Indonesian). *Ditambahkan:* Data health: alur pipeline 24 jam / 7 hari (item
  diambil, item baru, artikel terbit), kedalaman tujuh antrean Celery, grafik panggilan LLM per jam; halaman
  Scrapers dan Data health didesain ulang (panel samping pengganti dialog detail, tile status, "More checks").
  *Diubah:* waktu di kedua halaman memakai zona browser; label nada menjadi OK / WATCH / ACTION; tombol tulis
  scraper disembunyikan tanpa `manage_scraper`. A "Catatan 0.8.16 (Operations)" line: tanpa migrasi, tanpa key
  `.env` baru.
- `docs/prod-upgrade/0.8.16.md` and `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` (English). *Migrations:* none from
  4b. *Settings:* none. *Contract:* three additive fields on `GET /api/data-health` (`pipeline`, `queues.depths`,
  `llm.calls_per_hour`). *Post-deploy check:* open `/data-health`, confirm the seven queue depths show numbers and
  the chart has 24 slots. *Rollback:* image rollback only; no data change.
- `docs/ARCHITECTURE.md` is not changed (no new data flow).

## 5. Migration summary

None. 4b adds no table, no column, no index and no `Settings` field, so `.env.example` and `.env.prod.template` are
unchanged and the Alembic head stays `c4e8a1f2b9d6`. No syrupy snapshot covers `/api/data-health`. Contract files
to regenerate and commit: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`.

## 6. UI

Global rules (as 2b, 3 and 4a). Desktop 1440 first (content width 1328). Multi-column rows collapse to one column
below 1024 px (`lg:`). No `backdrop-blur`. Colours only through tokens; text on tints uses `text-X-text`. Focus
ring `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background`.
Minimum text 11 px (`text-2xs`). Base UI, not Radix. Scraper ids, cron strings, queue names, task names, prompt
versions and counters in `font-code` (`font-mono` is not monospace here; the current `font-mono` uses on both
pages are replaced). The mockup's wide separators are rendered " · ". Fixed copy below is verbatim from the frames
unless a C-rule says otherwise. All times are browser zone through `lib/format.ts`; the local helpers
`relativeTime`, `untilTime`, `formatAge`, `when` and the raw `…replace("T", " ") UTC` strings are removed.

Tone vocabulary (both pages). The existing `Tone` type `ok | warn | bad | unknown` is kept; its labels change from
OK / Check / Problem / Unknown to **OK / WATCH / ACTION / UNKNOWN** (mockup legend). They render through the
existing `Chip`: ok → `kind="status" value="ok"`, warn → `value="watch"`, bad → `value="action"`, unknown (and
"OFF") → `kind="flag"` (neutral tint). Severity order for roll-ups: bad > warn > unknown > ok. Scraper health
statuses use the same chip with the status word as its text: `ok` → ok; `degraded`, `stale`, `zero_yield` → watch;
`dead` → action; `disabled`, unknown → neutral flag. `StatTile` tones follow the same mapping (success, warning,
destructive, neutral).

Constraints carried over from earlier sub-projects (each is a review checklist item):
1. A nested layout with a string `metadata.title` resets the root title template. Both layouts use
   `{ default, template: "%s · ${PLATFORM_NAME}" }` (as `app/(app)/exec/layout.tsx`) and stop rendering
   `PageHeader`; the views call `usePageTitle`.
2. Check `response.ok`, not just `if (error)`: every query and mutation on both pages (`lib/scrapers/health.ts`,
   list, detail, runs, items, trigger, dry-run, enable, disable, config, reset-config, reset-dedup,
   `/api/data-health`, `/api/cve/freshness`, `/api/attack/status`, `/api/dashboard`) destructures `response` and
   throws `new Error(detail ?? fallback, { cause: response.status })` when `!response.ok` or data is missing. An
   empty-body 502 must not read as success.
3. Do not retry 4xx: every query uses `retry: (n, e) => n < 2 && !isClientError(e)`. `useScraperHealth` is shared
   with X Intel; the change applies there too.
4. No interactive element nested inside another. Table rows have no `onClick`; the SOURCE cell holds a real
   `<button>` and the Disable / Enable button is a sibling cell. Needs-attention rows are one `<Link>` with only
   text and chips inside. Tiles are `StatTile onSelect` (a `<button aria-pressed>`), with no link inside.
5. A `table-fixed` table needs explicit column widths (Sources, usage, Stories, run history).
6. `SelectItem` children are a single string and every `Select` with a sentinel default passes `items`
   (`FilterSelect` already does; the options select in the config dialog must).
7. Gate on the real backend permission, never a stricter one: both pages and every read need `view_ops`; trigger,
   dry-run, enable, disable, save config, reset config and reset dedup need `manage_scraper` (`useCan`). The
   "Open Scrapers" links on Data Health need no extra gate (same permission). The Coverage card reads
   `/api/dashboard`, which has its own permission: a 403 there shows "unknown" in that card only.
8. Legend colours equal the data colours: the chart legend swatches use the same two tokens as the bars, the
   freshness and tile chips use the tone vocabulary above, and the scraper status chips use one mapping for
   tiles, table, panel and Needs attention.
9. A `Chip` inside `HeroPanel` needs hero-safe tokens. 4b uses no `HeroPanel`.
10. A closed `Disclosure` is hidden in print unless `printOpen` is set: "More checks", "How to read this page" and
    "What the statuses mean" set it.
11. Memoise what feeds hooks: the "now" used for ages is read inside `queryFn` / `select` (returned with the
    data), never `Date.now()` in render keys.
12. Every pre-redesign feature stays reachable; the PR carries a checklist S1-S17 and DH1-DH12 (tables in 6.1, 6.2).

### 6.1 Scrapers (frames 28315, 34979)

- **Routing and state.** `app/(app)/scrapers/page.tsx` renders `ScrapersView`, which reads `?scraper={id}`
  (`useSearchParams`); selecting a row calls `router.replace` with the parameter, closing the panel removes it (P4).
  An id that is not in the list shows the panel's "Unknown scraper" state. Search and the three filters are
  component state, not URL state. Queries keep their keys (`["scrapers","list"]`, `["scrapers","health"]`,
  `["scrapers",id,"detail"]`, `["scrapers",id,"runs",…]`, `["scrapers",id,"items",…]`) and the 60 s
  `refetchInterval` on list and health; every mutation still invalidates `["scrapers"]`.
- **Header.** `PageHeader` kicker "OPERATIONS", h1 "Scrapers", description "Every source the platform reads, its
  schedule and how its last run went". `actions` = the scheduler chip (`scheduler-status.tsx`, rewritten):
  state `ok` → success `Chip` "Scheduler alive · tick {n} s ago" (`age_s` rounded; from 90 s "{n} min ago", from
  120 min "{h} h {m} min ago"), `title` "Up since {fmtDateTime(started_at)}"; `stale` → destructive chip "Scheduler
  down · last tick {age} ago"; `unknown` → destructive chip "Scheduler heartbeat missing". No beat-lock line (C5).
  For `stale` / `unknown` a `Notice tone="destructive"` (`role="alert"`) sits under the header: title "Scheduler
  (beat) is down or stuck" / "Scheduler (beat) heartbeat missing", body "Scheduled scraper runs and periodic
  reports are not firing. Last heartbeat: {fmtDateTime(last_tick_at)} ({age} ago) / never recorded; threshold
  {stale_after_s} s. NEXT below is the cron schedule, not a guarantee. Manual runs still work." (S1).
- **Tiles** (`health-summary-bar.tsx`, rewritten; `lg:grid-cols-6`, three per row below). Six `StatTile`s in the
  mockup order with PARTIAL removed: "OK" (`ok`), "DEGRADED" (`degraded`), "STALE" (`stale`), "ZERO YIELD"
  (`zero_yield`), "DEAD" (`dead`), "DISABLED" (`disabled`), toned per the mapping above.
  Value = `counts[status] ?? 0` in `font-code`. Each tile is `onSelect` and toggles the Status filter to that status
  (`selected` when it is the active filter; a second click returns to "all") (P8). Under the row, `text-2xs` muted:
  "Health as of {fmtTime(generated_at)} {browserZoneName()} · refreshes every minute" (S2). Health loading: six
  skeleton tiles. Health failed: values "–" and a `Notice tone="warning"` "Scraper health could not be loaded" /
  "Enabled scrapers show UNKNOWN instead of a status." with a "Retry" action (S17).
- **Toolbar** (one row, wraps): `SearchInput` "Search source or id" (`aria-label` the same; matches `id` and
  `source`, case-insensitive, no debounce: the list is in memory); `FilterSelect` "Status" (all, ok, degraded,
  stale, zero yield, dead, disabled, plus "unknown" only while health failed); `FilterSelect` "Runtime" (all,
  light, browser); `FilterSelect` "Queue" (all, scrape.rss, scrape.api, scrape.browser); right-aligned link "What
  the statuses mean →" (`href="#status-legend"`, opens and scrolls to the legend disclosure).
- **Sources card** (left part of `MasterDetail`). Header "Sources" with the count "{total} scrapers", or
  "{filtered} of {total} scrapers" while any filter or search is active (S7). `Table framed`, `table-fixed`, widths
  SOURCE 28% | RUNTIME 9% | SCHEDULE 13% | LAST RUN 18% | STATUS 14% | NEXT 8% | (action) 10%:
  - SOURCE: a `<button type="button">` (full cell width, left-aligned) with the source name and, under it, the id
    in `font-code text-2xs` muted; selects the row. The selected `<tr>` has `aria-current="true"` and the selected
    tint. The id column of today is this second line.
  - RUNTIME: queue suffix "rss" / "api" / "browser" (`queue.replace("scrape.", "")`), `title` per C4; when
    `has_override`, a primary dot with `aria-label` and `title` "config override active" (S8).
  - SCHEDULE: `humanizeCron(schedule)` (6.4), `title` = the raw cron; a cron the humanizer does not know prints raw
    in `font-code`.
  - LAST RUN: "{time} · {outcome}", `title` = `fmtDateTime(last_started_at)`. `time` = `fmtTime` when the run
    started less than 24 h ago, else `fmtAgo`. `outcome` by `last_status`: `ok` → "{last_items_new} new"; `empty` →
    "0 items"; any other status → the status with underscores as spaces ("partial", "fetch error", "rate
    limited", "backpressure", "running", …), coloured by the existing run-status map moved to `text-X-text`
    tokens. No run: "never".
  - STATUS: `Chip` from `statusFor(id, enabled)` (unchanged logic: `disabled` when not enabled, skeleton while
    health loads, UNKNOWN when health failed, else the problem status or `ok`); for a disabled scraper the
    existing `DisabledReason` line under it ("Turned off by an admin: {reason}" / "Off by default in code" /
    "Replaced by the CVE mirror") (S8).
  - NEXT: `fmtTime(next_run_at)` when it is within 24 h, else `fmtShortDate`; "–" when null (`title` "disabled" or
    "invalid cron"). When the scheduler state is not `ok`: `line-through text-destructive-text` and `title`
    "{fmtDateTime} · scheduler down, will not fire" (S8).
  - Action (only with `manage_scraper`): text button "Disable" (opens the dialog) or "Enable" (posts at once,
    toast "{id} enabled"). Without the permission the column is empty.
  Empty filter result: `StatePanel empty` "No scraper matches these filters" with "Clear filters".
- **Side panel** (`scraper-panel.tsx`, right part of `MasterDetail`, sticky on desktop; below 1024 px it stacks
  under the table and selecting a row scrolls it into view). Nothing selected: `StatePanel empty` "Select a
  scraper" / "Its recent runs, config and actions appear here." Selected:
  - Header: `<h2>` source name, close button "✕" (`aria-label` "Close panel"), sub line "{id} · queue {queue} ·
    {humanizeCron(schedule)}" (id and queue in `font-code`).
  - Status `Chip` and one sentence composed in `lib/scrapers/reason.ts::statusSentence(entry, item)`: for a
    problem status "{reason}" + " Failing {consecutive_failing} of the last 3 runs." (only when > 0) + " Last
    success {fmtAgo(last_success_at)}." or " No successful run on record."; `ok` → "The latest run finished without
    errors."; `disabled` → the `DisabledReason` text; unknown → "Health could not be loaded."
  - "RECENT RUNS": `GET /api/scraper/{id}/runs?page=1&page_size=4` (60 s refetch): rows "{fmtTime or
    fmtShortDate}" + "{items_found} found · {items_new} new", or "{items_found} found · {errors[0].message}"
    (one line, truncated, full text in `title`) when the run has errors; run status coloured as in the table.
    Empty: "No runs yet". Link button "All runs and items" opens the **Run history** `Sheet` (title "Run history ·
    {source}") holding the existing `ScraperRunsPanel` (paged, S14) and `ScraperItemsPanel` (paged, accepted
    filter, S15), restyled.
  - "CONFIG": rows Schedule (effective cron, `font-code`), Max items (`config.max_items ?? default_max_items`),
    Rate limit (`config.rate_limit ?? default_rate_limit`, C17), one row per declared option ("{label}: {effective
    choice label}", S13 read side), Override ("none", or the overridden field names joined with ", " followed by
    "· {updated_by} · {fmtDateTime(updated_at)}"). A `Disclosure` "Defaults and metadata" holds what the old
    dialog header showed: runtime, default schedule, default rate limit, default max items, credential name,
    tags.
  - Actions (only with `manage_scraper`, P5), primary row: "Run now" (trigger; toast "Run queued for {id} · task
    {first 8 chars}"), "Dry run", "Disable" / "Enable". Secondary row: "Edit config…", "Reset dedup…".
  - **Dry-run slot** (inline, under the actions, kept until the selection changes): while pending `Notice busy`
    "Dry run in progress" / "This reads the real source and writes nothing."; success `Notice` "Dry run: {status} ·
    {items_found} items found · {duration_ms} ms" with each `errors[].message` as a line (tone warning when there
    are errors); failure `Notice tone="destructive"` with the `detail`.
- **Edit config dialog** (`scraper-config-dialog.tsx`, the form lifted out of `scraper-detail-dialog.tsx`
  unchanged in logic, mounted only when open so state initialises from loaded data): fields "Schedule (cron)",
  "Rate limit", "Max items" (placeholders = the defaults), one `Select` per declared option (`items` prop,
  description under it), "Paused reason"; every input has a real `<label htmlFor>`. Footer: "Reset to defaults"
  (outline, opens the confirm), "Cancel", "Save config". Note under the schedule field: "A schedule change takes
  effect after beat restarts." Save sends the same body as today (blank = null = code default; only options that
  differ from their default) (S12, S13).
- **Confirms** (`ConfirmDialog`, English, D7). Reset config: "Reset config to defaults?" / "All overrides for {id}
  (schedule, rate limit, max items, paused reason{, options}) are removed and the code defaults apply again."
  Reset dedup (tone destructive): "Reset dedup state?" / "All dedup history for {id} is deleted. The next run is a
  cold start: only its newest items are processed and the rest are marked seen." Success toasts as today ("Config
  reset to defaults", "Dedup reset · {deleted} entries cleared") (S11, S12).
- **Disable dialog** (`disable-scraper-dialog.tsx`, 480 wide, frame 34979; opened from the row and from the
  panel, C18): title "Disable {source}?"; `DialogDescription` "Beat stops scheduling it after the next restart; a
  run already queued is skipped. Seen items are kept, so enabling it later does not re-alert."; `Textarea` with
  `<label htmlFor>` "Reason (optional)" and help text "Shown on the Scrapers page next to the disabled status.";
  footer "Cancel" and "Disable scraper" (destructive, `disabled` while pending). Success: toast "{id} disabled",
  dialog closes, reason cleared; failure: toast with the `detail`, dialog stays open (S10).
- **Legend** (`id="status-legend"`): `Disclosure printOpen` "What the statuses mean" with the eight existing
  entries (OK, Disabled, Stale, Dead, Degraded, Zero yield, Partial, Unknown) unchanged, "Last Run and the Runs
  tab" reworded to "LAST RUN and Run history" (S16).
- **Feature map.**

| # | Pre-redesign feature | New home |
|---|---|---|
| S1 | Scheduler alive line / red banner | Header chip (with "Up since" in its title); `Notice` when stale or unknown |
| S2 | Fleet-health pills, total, "as of" | Six tiles; total in the Sources card header; "Health as of" line |
| S3 | Needs-attention chips opening the detail | Tile click filters the table to that status; the row opens the panel; Data Health rows deep-link `?scraper=` |
| S4 | Search id / source | Toolbar search |
| S5 | Runtime filter | Toolbar "Runtime" |
| S6 | Status filter incl. unknown / loading | Toolbar "Status"; skeleton chip while loading |
| S7 | "N / total scraper" count | Sources card header |
| S8 | Columns, override dot, disabled-by reason, raw cron, last run, Next Run strike-through | Table (id under the source name, raw cron in the tooltip) |
| S9 | Row menu: View Detail, Trigger, Dry-run, Disable / Enable | Row button selects; inline Disable / Enable; Run now and Dry run in the panel |
| S10 | Disable dialog with optional reason | Disable dialog (row and panel) |
| S11 | Reset dedup | Panel "Reset dedup…" + confirm |
| S12 | Config editor + Reset config | Panel "Edit config…" dialog; "Reset to defaults" + confirm |
| S13 | Declared options select | Edit config dialog; effective value in CONFIG |
| S14 | Recent Runs (paged) | Panel RECENT RUNS (4) + Run history sheet |
| S15 | Recent Items (paged, accepted filter) | Run history sheet |
| S16 | Statuses legend | Legend disclosure, linked from the toolbar |
| S17 | Health-failed fallback (UNKNOWN) | `Notice`, "–" tiles, UNKNOWN chips |

### 6.2 Data Health (frame 3258)

- **Data.** `DataHealthView` keeps its four queries and keys (`["data-health"]` with `refetchInterval: 60_000`,
  `["scrapers","health"]` via `useScraperHealth`, `["cve","freshness",null]`, `["intelligence","attack-status"]`,
  `["data-health","coverage"]`), with constraints 2 and 3 applied. `refetchIntervalInBackground` stays off, so a
  hidden tab does not poll. The file is split: `data-health-view.tsx` (queries, tone computation, layout) and
  `components/data-health/{pipeline-card,llm-card,relevance-card,freshness-card,more-checks}.tsx`; the tone rules
  move to `lib/data-health/tones.ts` as pure functions.
- **Tone rules** (unchanged logic, one place):

| Area | ACTION (bad) | WATCH (warn) | UNKNOWN |
|---|---|---|---|
| Pipeline | scheduler state not `ok` | at least one entry in `scrapers.problems` | – |
| Enrich queue | `enrich_depth >= enrich_max_depth` | `enrich_depth >= enrich_max_depth / 2` | `enrich_depth` null |
| LLM jobs | `llm.status == "failing"` or breaker `open` | breaker `half_open`, or `pending_classify > 0`, or `queue.failed > 0` | `llm.status == "unknown"` and none of the above |
| Freshness row | age above the second threshold | age above the first threshold | timestamp missing, or its query loading / failed |
| Relevance | – | – | `mode == "off"` or `gate_state` null |
| Failed jobs | `failed_7d / processed_7d >= 0.10` or `failed_24h >= 5` | `pending_replay > 0` | – |
| CVE ingest | `status == "red"` | `status == "amber"` | `status == "off"` |
| Sigma | `status == "red"` | `status == "amber"` | – |

  Freshness thresholds (hours, D19): article 6 / 24, tweet 24 / 72, IOC 24 / 72, CVE check 6 / 24; ATT&CK: ACTION when
  a domain's status is `error`, WATCH when a domain's last sync is older than 30 days, UNKNOWN when the list is
  empty or failed.
- **Header.** `PageHeader` kicker "OPERATIONS" (C1), h1 "Data health", description "Generated
  {fmtTime(generated_at)} {browserZoneName()} · numbers cached for up to 60 s · is the pipeline feeding the
  newsroom?" (DH11; before the first load: "Is the pipeline feeding the newsroom?"). `actions`: link "How to read
  this page →" (`href="#how-to-read"`, opens the disclosure) and the **status block**: the areas are the eight rows
  of the tone table, with Freshness counted once as the worst of its five rows. Chip = ACTION when any area is bad,
  else WATCH when any is warn, else OK; UNKNOWN only when every area is unknown. Title: "{b} areas need action"
  when b > 0 (bad count), else "{w} areas to watch" when w > 0, else "All areas OK" ("1 area needs action" / "1
  area to watch" for one). Sub line: "{p} scrapers need attention" (p = `scrapers.problems.length`; "No scraper
  needs attention" for 0; "1 scraper needs attention" for 1), then " · {w} to watch" when both b and w are above
  0, then " · {u} unknown" when u > 0. No "no data lost" (C12).
- **Tiles** (six `StatTile`s, `lg:grid-cols-6`, each with its tone chip in the corner; not clickable):

| Label | Value | Sub | Tone |
|---|---|---|---|
| PIPELINE | "{counts.ok} / {fleet total}" (C15) | "scrapers healthy, beat alive" / "scrapers healthy, beat stale" / "scrapers healthy, beat heartbeat missing" | Pipeline |
| ENRICH QUEUE | `enrich_depth`, "–" when null | "of {enrich_max_depth} before backpressure" / "Redis not reachable" | Enrich queue |
| LLM JOBS | `pending_classify + pending_ttp` | "pending, oldest {fmtCompactAge} ago" / "none pending" | LLM jobs |
| FRESHNESS | compact age of the worst freshness row (ties and all-OK: the first in card order) | "since the newest article" / "since the newest X Intel tweet" / "since the newest IOC" / "since the last CVE check" / "since the last ATT&CK sync" | that row's tone (P6) |
| RELEVANCE | `holdout_agreement` as "96.4%" (one decimal); "–" without a model; "Off" when `mode == "off"` | "holdout agreement, gate on" / "holdout agreement, gate off (shadow)" / "no active model yet" / "relevance model is off" | Relevance (chip "OFF" for mode off) |
| FAILED JOBS | `failed_24h` | "created in 24 h, {pending_replay} waiting" | Failed jobs |

- **Pipeline card** (`lg:col-span-2` of a three-column row; the Needs attention card takes the third). Title
  "Pipeline", subtitle "From scraper to newsroom, left to right", `SegmentedControl` "24h | 7d" (`aria-label`
  "Pipeline window", default 24h; selects `pipeline.last_24h` / `last_7d`, no refetch). Flow, five steps joined by
  "→" (an `<ol>`; the arrows are `aria-hidden`):
  1. "SCRAPERS" / "{items_found} items fetched"
  2. "DEDUP" / "{items_new} new after seen-check"
  3. "ENRICH" / "{enrich_depth} in queue now" ("–" when null)
  4. "LLM JOBS" / "{pending} pending now" with "classify {pending_classify} · TTP {pending_ttp}"
  5. "NEWSROOM" / "{articles_published} articles published"
  Caption (`text-2xs` muted, C6): "Fetched and new count every item type (articles, IOCs, CVEs, posts) in the
  selected window; only articles pass through enrich. Queue and job figures are live."
  Below: `MeterBar` "Enrich queue depth {depth} / {max} · backpressure at {max}" (tone from the Enrich queue rule;
  replaced by the text "Enrich queue depth unknown (Redis not reachable)" when null). Facts (`<dl>`): "Scheduler
  (beat)" → "alive · tick {age} ago" / "{STATE} · last tick {age} ago" / "heartbeat missing"; "Failed jobs 24 h" →
  per C14; "Waiting for retry" → `pending_replay`. Then "CELERY QUEUES, DEPTH NOW": the seven queues in the order
  of 4.2, name in `font-code`, value "{n}" ("–" for all when `depths` is null, with the line "Redis not reachable"),
  and the caption "Messages waiting in the broker; tasks a worker already picked up are not counted."
- **Needs attention card.** Title "Needs attention", subtitle "Scrapers not ok and not disabled", count chip
  `problems.length`. Rows sorted by `byProblemSeverity`, the first 8: each row is one `<Link
  href="/scrapers?scraper={id}">` containing the status `Chip`, the id (`font-code`), "failing
  {consecutive_failing}/3" (omitted when 0) and the one-line `reason` (truncated, full text in `title`). More than
  8: a last line link "and {n} more on Scrapers" → `/scrapers`. None: "Every enabled scraper is OK." Footer
  "Fleet: {total} scrapers · {ok} ok · {disabled} disabled" and the link "Open Scrapers" (DH2).
- **LLM gateway card** (full width). Title "LLM gateway", subtitle "Persist first: articles land without the
  model, jobs wait here". Chips: "BREAKER CLOSED" (ok) / "BREAKER HALF-OPEN" (warn) / "BREAKER OPEN" (bad, followed
  by text "retry at {fmtTime(retry_at)}" when set); "STATUS OK" / "STATUS FAILING" / "STATUS UNKNOWN". Four stats:
  "Pending classify", "Pending TTP", "Failed", "Oldest pending" ("{fmtCompactAge}" with sub "since
  {fmtTime(oldest_pending_at)} {zone}", or "none"). Status line under the stats (DH6): failing → destructive text
  "Last error: {http_status} {error_type} · {task} · {fmtAgo(at)}" (`title` `fmtDateTime`; "latest call returned
  no choices" when `last_error` is null); ok → "Last successful call {fmtAgo(last_ok_at)}", plus, when `last_error`
  is not null, muted "Last error: … {fmtAgo}"; unknown → "No calls recorded yet". Link "Review jobs in Newsroom ›
  Filtered Articles › Enrichment queue" → `/newsroom`.
  - **Chart** "Calls per hour, last 24 h": `BarSeries` with `stackValues` (6.4): labels `fmtTime(hour)`, base series
    `ok`, stacked series `failed`; x-axis ticks every 6th label and "now" for the last; tooltip and the hidden
    data table read "{hour}: {ok} ok, {failed} failed". `LegendRow` "ok" / "failed (error or empty reply)" with the
    same two tokens as the bars (constraint 8). Caption `text-2xs`: "Hours are UTC clock hours shown in
    {browserZoneName()}; the last bar is the current hour so far." All 24 values zero: the chart is replaced by
    "No LLM calls in the last 24 hours." No breaker caption (C10).
  - **Usage table** with `SegmentedControl` "24 h | 7 d" (`aria-label` "Usage window", default 24 h) choosing
    `usage_24h` / `usage_7d`; rows = the union of tasks in both lists, sorted, so a task keeps its row when the
    window changes, with "–" for a missing value (DH7). `table-fixed` widths TASK 22% | CALLS 12% | ERRORS 12% |
    PROMPT TOK 15% | COMPLETION TOK 15% | P50 LATENCY 12% | PROMPT 12%; the first header cell reads "TASK, 24 H" /
    "TASK, 7 D"; latency "{n} ms"; PROMPT per C13. Empty: "No LLM calls recorded in the last 7 days."
- **Relevance model card.** Title "Relevance model", subtitle "Local model decides before the LLM does", chip
  "AUTO" / "SHADOW" / "OFF" (`mode`). Variants (DH8):
  - `mode == "off"`: `Notice` "The relevance model is off" / "Every title goes to the LLM classify call." and only
    the "Classify calls avoided" row.
  - `gate_state` null (mode shadow or auto): `Notice` "No active model yet" / "Until a model is trained and
    activated, every title goes to the LLM classify call." and only the "Classify calls avoided" row.
  - Otherwise: gauge = `MeterBar` 0-100 with the big figure "{holdout_agreement}%" and "holdout agreement" ("–"
    when null). Rows: "Gate" → "on since {fmtShortDate(gate_changed_at)}" / "off (shadow) since {date}"; "Model
    trained" → "{fmtShortDate(model_trained_at)} · {n_examples} examples"; "Holdout band share" →
    "{holdout_band_share}%"; "Band agreement 14 d" → "{band_agreement_14d}% of {band_titles_14d}" / "no in-band
    titles with an LLM verdict yet"; "Middle band 14 d" → "{middle_band_14d} → LLM"; "Audit samples" →
    "{audit_samples} · {audit_agreement}%" / "none yet"; "Classify calls avoided" → "{a} / 24 h · {b} / 7 d". With
    `mode == "shadow"`, or `mode == "auto"` and `gate_state == "shadow"`, a `Notice` above the rows: "Shadow: the
    model only measures agreement with the LLM; no classify call is skipped." / "Gate is off: agreement is being
    measured, or the gate turned itself off after audit agreement dropped."
- **Row of three cards.**
  - "Source freshness": five rows, each value = compact age with `title` `fmtDateTime`, a caption and a tone chip
    (DH4): "Newest article" / "watch after 6 h · action after 24 h"; "Newest tweet (X Intel)" / "watch after 24 h ·
    action after 72 h", plus "monitor_x {status}: {reason}" when `useScraperHealth` lists it as a problem; "Newest
    IOC" / "watch after 24 h · action after 72 h"; "CVE check" / "watch after 6 h · action after 24 h"; "ATT&CK
    sync" (newest domain sync) / "watch when a domain is over 30 days old · action when a sync failed". Missing
    timestamp: "never"; query failed: "unknown (failed to load)"; loading: skeleton.
  - "Coverage" (DH5): "Articles with a country", "Articles with a threat actor", "Articles with an ATT&CK
    technique", each "{n} · {pct}%" of `total_articles`; "unknown (failed to load)" when `/api/dashboard` fails.
    Sub-heading "IOC REPUTATION CHECKS": one row per `ioc_enrichment` type (`font-code`), "{enriched} / {total}" with
    a `MeterBar`; empty "No IOCs yet."
  - "Stories" (C16): `table-fixed` (label 52% | 24 H 24% | 7 D 24%) with rows "New stories", "Follow-ups",
    "Inherited classify", "Matched by embedding", "LLM calls avoided" from `stories_24h` / `stories_7d`; footnote
    "Inherited follow-ups skip both classify and TTP extraction (2 calls each)."
- **More checks** (D18): `Disclosure printOpen` whose header is `<h2>` "More checks" followed by three small tone
  chips "CVE INGEST {tone}", "SIGMA {tone}", "ENRICHMENT {tone}" (the CVE ingest, Sigma and Failed jobs tones) so a closed section still shows a problem;
  `defaultOpen` when the CVE ingest or Sigma tone is warn or bad at first render (P7). Three cards in
  `lg:grid-cols-3`:
  - "CVE ingest" (DH9): mirror off → "Off (CVE_MIRROR__ENABLED is false)"; else rows Promote mode, Last sync,
    Pending items, Last reconcile, Reconcile result ("{fixed} fixed · {missing} missing · {outdated} outdated ·
    {failed} failed" or "error · {error}"), as today.
  - "Sigma rules" (DH10): Release ("none loaded"), Rules, Fetched, Last error (when set).
  - "Enrichment detail" (DH3): "Failed jobs created, last 24 hours"; "Failed jobs created, last 7 days" →
    "{failed_7d} of {processed_7d} processed ({pct}) · snapshot of jobs still failed"; "Failed jobs waiting for a
    retry"; "Newest failed job created"; "Enrich queue" → "{depth} waiting · backpressure at {max}"; the Newsroom
    link.
- **Legend and thresholds** (`id="how-to-read"`, DH1). A strip: "HOW TO READ THIS PAGE · OK: nothing to do ·
  WATCH: slower than usual or waiting for a retry · ACTION: a source or job is failing" (C12), each word with its
  chip colour. Under it `Disclosure printOpen` "Thresholds for every area" with the nine existing paragraphs
  (Pipeline, Enrichment, Enrich queue, Freshness, Coverage, LLM, Relevance model, CVE ingest, Sigma rules), the
  words Check / Problem replaced by WATCH / ACTION, and three additions: Pipeline card ("Fetched and new are sums
  over scraper runs started in the window; published counts articles first seen in the window"), Celery queues
  ("messages waiting in each broker queue; tasks already picked up by a worker are not counted"), Calls per hour
  ("failed = calls that ended in an error or an empty reply").
- **Feature map.**

| # | Pre-redesign feature | New home |
|---|---|---|
| DH1 | Tone pill per section + "How to read" thresholds | Tile and card chips, status block, legend strip + thresholds disclosure |
| DH2 | Pipeline: scheduler, fleet counts, problems, Open Scrapers | PIPELINE tile, Pipeline card facts, Needs attention card + footer |
| DH3 | Enrichment: failed 24 h / 7 d, pending replay, newest failure, queue | FAILED JOBS and ENRICH QUEUE tiles, Pipeline card facts and bar, More checks › Enrichment detail |
| DH4 | Source freshness (5 rows, monitor_x) | Source freshness card, FRESHNESS tile |
| DH5 | Coverage + IOC reputation | Coverage card |
| DH6 | LLM status, last error, breaker, pending, stories | LLM gateway chips, stats and status line; Stories card |
| DH7 | Usage table 24 h / 7 d pairs | Usage table with the 24 h / 7 d switch |
| DH8 | Relevance model | Relevance card with off / no-model / shadow variants, RELEVANCE tile |
| DH9 | CVE ingest | More checks |
| DH10 | Sigma rules | More checks |
| DH11 | 60 s polling + "cached up to 60 s" | Unchanged polling; header subtitle |
| DH12 | Loading skeleton, load error | 6.3 |

### 6.3 States
- **Scrapers.** List loading: skeleton tiles and a skeleton table; list error: `StatePanel error` "Failed to load
  scrapers" with "Retry" (`role="alert"`); 403: `StatePanel no-access` "You need the view_ops permission to see
  scrapers" (the nav item is already hidden). Health loading / failed: 6.1. Panel: detail loading skeleton, detail
  error with "Retry", unknown id "Unknown scraper" / "{id} is not in the registry." with "Close". Mutations: buttons
  show a pending label and are disabled while pending; errors are toasts with the API `detail`; a 403 on a write
  toasts "You need the manage_scraper permission".
- **Data Health.** Loading: six skeleton tiles and four skeleton cards (`aria-hidden`, with one `role="status"`
  "Loading data health"); error: `StatePanel error` "Failed to load data health" with "Retry" (DH12); 403:
  `StatePanel no-access`. A failed refetch keeps the last good data on screen and shows `Notice tone="warning"`
  "Could not refresh · showing numbers from {fmtTime(generated_at)}". The three side queries fail independently:
  their rows read "unknown (failed to load)" and their tone is UNKNOWN; nothing else is blocked.

### 6.4 New primitives and domain pieces (existing ones reused as they are)
1. **`BarSeries` gains `stackValues?: number[]` and `stackLabel?: string`** (`components/ui/bar-series.tsx`): a
   second dataset stacked on the first in the destructive token, a second column in the hidden data table, and
   `formatValue` applied to both. Existing callers pass neither and are unchanged.
2. **`lib/scrapers/cron.ts::humanizeCron(expr)`** (pure): `*/N * * * *` → "*/N min"; `M * * * *` → "hourly";
   `M */N * * *` → "*/N h"; `M H * * *` → "daily"; `M H * * D` → "weekly"; anything else → the expression unchanged.
   M, H, D are single integers; lists and ranges fall through to raw.
3. **`lib/scrapers/reason.ts::statusSentence`**, **`lib/data-health/tones.ts`** (the tone table as pure functions
   plus `TONE_LABEL` / `TONE_STYLE`), and the scraper status → `Chip` mapping shared by both pages
   (`components/scrapers/status-badge.tsx::StatusBadge` rewritten to return the `Chip` described under Tone
   vocabulary; `RunStatusText` keeps its map with `text-X-text` tokens).
4. Domain components: `components/scrapers/{scraper-panel,scraper-config-dialog}.tsx`;
   `components/data-health/{pipeline-card,llm-card,relevance-card,freshness-card,more-checks}.tsx`.
5. Reused: `MasterDetail`, `StatTile`, `Chip`, `StatePanel`, `Notice`, `SegmentedControl`, `FilterSelect`,
   `SearchInput`, `Disclosure`, `Sheet`, `MeterBar`, `LegendRow`, `ConfirmDialog`, `Table framed`, `usePageTitle`.

Replaced or removed: `scraper-detail-dialog.tsx` (its header and action bar become the panel, its form the config
dialog), the row `DropdownMenu` in `scrapers-table.tsx`, the pill bar and "Needs attention" chips in
`health-summary-bar.tsx`, the `Section` / `Row` / `TonePill` / `MoreLink` / `HowToRead` helpers in
`data-health-view.tsx`, `formatWib` / `relativeTime` imports on these pages. `scraper-runs-panel.tsx` and
`scraper-items-panel.tsx` stay and move into the sheet.

## 7. Out of scope
- Scrapers: the beat lock holder (B-S1), a `partial` health status (B-S2), filters in the URL, bulk actions,
  sorting columns, changing `cti_scraper.health` rules or the Telegram digest, live progress of a triggered run.
- Data Health: breaker open / close history, a "data lost" indicator, new indexes, per-task chart series, a
  configurable chart range, history of queue depths, moving CVE or ATT&CK freshness into the payload, changing
  any threshold.
- 4c pages (Login, Admin, session-expired dialog); mobile layouts beyond the 1024 px collapse.

## 8. Verification
- **Backend tests.** `uv run pytest tests/integration -k "data_health or scraper"` (Docker), then `uv run pytest
  tests/unit tests/contract packages` (deselect the two known Mac-only failures). Named tests: 4.1, 4.2, 4.3.
- **Static.** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src
  packages/cti-scraper/src` (covers the two repository methods).
- **Contract.** `uv run python tools/export_openapi.py`; `cd apps/web && pnpm run gen:api`; commit both.
- **Web.** `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit`; `pnpm build`. The pure helpers
  (`humanizeCron`, `statusSentence`, the tone functions) have no unit runner: check `humanizeCron` in QA against
  every distinct schedule in the registry (`cti-scraper list`) and confirm unknown shapes print raw.
- **Visual (local).** Isolated compose project `qacve`, API via uvicorn, web via `pnpm dev`, synthetic data:
  scrapers in all six statuses plus one with an override, one disabled by an admin with a reason, one disabled by
  code; runs with errors and a partial run; scheduler heartbeat ok, stale and missing; `llm_calls` spread over 30
  hours with ok / error / empty rows and an empty stretch; pending and failed `enrich_jobs`; queue lists pushed to
  `enrich` and `cve`; Redis stopped for the null case; relevance mode off, shadow, auto without a model and auto
  with the gate on; CVE mirror off and amber; Sigma with a last error. Screenshots at 1440 and 1000 px, light and
  dark, against 28315 / 29465, 34979 / 36034 and 3258 / 3819. Checks: keyboard pass (tiles, filters, row button,
  inline action, panel actions, config dialog, confirms, sheet, both segmented controls, disclosures); no nested
  interactive element (a11y tree of a table row and a Needs-attention row); `?scraper=` deep link from Data Health
  selects the row; chart legend and bar colours match in both themes; chip contrast; the tab title keeps the
  "· {PLATFORM_NAME}" suffix on both pages; a 403 and a 404 are not retried; an empty-body 502 shows the error
  state; a user with `view_ops` but not `manage_scraper` sees no write control; every S and DH feature reachable
  (checklist in the PR); print preview shows the three disclosures open; with the browser zone set to
  Asia/Kolkata the chart labels read ":30" and the caption explains it.
- **Delivery.** Commit per backend item and per page; merge into `origin/Dev` (standing approval). On dev
  172.25.1.77 (read-only checks): both pages with real data, queue depths against `redis-cli LLEN`, the pipeline
  24h figures against a manual sum. No Run now, Dry run, Disable, config save or reset on dev without the user's
  go.

## 9. Risks
- **Aggregate cost on `scraper_runs`.** No index on `started_at`: one sequential scan per cache miss over at most
  90 days of runs. Fine at the current size; if `/data-health` build time grows, the fix is an index on
  `scraper_runs (started_at)` in a later release (a migration, so not here).
- **Aggregate cost on `articles`.** `first_seen_at` is not indexed either; the new count is a third scan next to
  the two that exist. Same trigger and same later fix.
- **`llm_calls` per hour.** Uses `ix_llm_calls_at`; the risk is semantic, not cost: buckets are grouped in UTC
  explicitly, and a test pins the boundary so a session `TimeZone` change cannot shift them.
- **Empty hours.** The SQL returns no row for an hour without calls; the zero-fill is in Python and tested. A
  client that assumed "missing = no data" would be wrong, hence the fixed length of 24.
- **Browser zone vs UTC hour buckets.** Buckets are UTC clock hours. In zones offset by 30 or 45 minutes the
  labels read ":30" / ":45"; the chart caption says the hours are UTC clock hours. The last bucket is partial
  and always looks low.
- **Redis `LLEN` on missing keys.** A missing key reads 0, which is right for an empty queue but also what a
  misspelled or renamed queue would return; the parity unit test in 4.2 is the guard. If Celery priorities are ever
  enabled on the Redis broker, messages move to suffixed keys and these depths under-report (the existing
  backpressure check in `cti_scraper.sinks` has the same limit). Reserved, unacknowledged tasks are not counted;
  the caption says so.
- **Redis round trips.** Seven sequential `LLEN`s instead of one, inside the 60 s cache; one failure nulls the
  whole block rather than showing a half-filled list.
- **Polling cost.** Each open tab polls `/api/data-health` and `/api/scraper/health` every 60 s; the server cache
  is per uvicorn process, so N processes can each rebuild once a minute. 4b adds four queries per rebuild (two
  aggregates, one hourly group, and the `LLEN`s). Hidden tabs do not poll. The side panel adds one runs query per
  minute while a scraper is selected.
- **Pipeline flow reads as a funnel** although steps 1-2 count all item types and steps 3-4 are live (C6); the
  caption and the thresholds text carry the explanation. If it still misleads, the fix is a per-item-type
  breakdown, which needs new data.
- **`running` runs in the sums.** A run still in progress contributes whatever its counters hold, so the 24h
  figures can rise slightly on the next refresh without a new run starting.
- **Largest regression surface: the detail dialog split.** The config form's lazy state initialisation depends on
  mounting only when data is ready; the config dialog keeps that rule. The checklist S9-S15 covers each action.
- **Hidden instead of disabled write controls** (P5) changes what a read-only user sees; CONFIG in the panel still
  shows every value they could read before.
- **Selection in the URL** (P4): a stale deep link to a removed scraper lands on "Unknown scraper", not an error.
- **Seven queues vs the mockup's six** (P1) and the two-series chart (P3) are deliberate deviations from the
  frame; both are listed for the reviewer.
- **Contract drift.** Forgetting the regen fails the CI drift check; it is in the verification list.
