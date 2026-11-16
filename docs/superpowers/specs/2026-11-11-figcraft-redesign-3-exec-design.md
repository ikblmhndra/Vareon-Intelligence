# FigCraft redesign, sub-project 3: Exec (Briefing and Analyst board)

Date: 2026-11-11. Status: draft for review. Branch: `claude/figcraft-design-data`. Same one-PR release 0.8.16
(the CHANGELOG entry and the 0.8.16 runbooks are extended, no extra version bump).

## 1. Context and goal

Sub-projects 1 (foundation), 2a (CVE Tracker) and 2b (Intelligence) delivered the shell, the shared primitives in
`apps/web/src/components/ui/` (`HeroPanel`, `MeterBar`, `BarSeries`, `HeatGrid`/`HeatCell`, `LegendRow`, `StatTile`,
`StarToggle`, `PresetControl`, `SegmentedControl`, `StatePanel`, `Notice`, `ConfirmDialog` with note and tone), the
browser-timezone formatters in `apps/web/src/lib/format.ts`, `lib/csv.ts` and `lib/newsroom/links.ts::newsroomHref`.
This spec is **3: the Exec page, its two views (Briefing and Analyst board) and the brief dialog**, plus a stored,
daily executive brief.

FigCraft frames (light; dark variant in brackets): Exec / View: Briefing 40179 (42159), Exec / View: Analyst board 40692
(42672), Exec / Dialogs 35068 (36123, brief dialog only). There is no Exec states frame.

Today `/exec` is one long stack of sections under a fixed `<PageHeader title="Exec">` (`app/(app)/exec/layout.tsx`),
filters live in React state and localStorage, and the brief is generated on demand, shown once in a modal and lost on
reload. The mockup splits the page into a leadership Briefing and an Analyst board, leads the Briefing with the brief,
and shows three data points the API does not return yet.

Goal: deliver the **full mockup, keep every existing feature reachable** (inventory F1-F24), add the missing data
(B1-B3), fix the brief scope (B5), and make the brief a **stored, platform-wide daily document** that every client's
Exec audience reads. Backend lands first, the contract is regenerated once, then the views are built on real data. The gap
inventory behind this spec (`.superpowers/brainstorm/exec-inventory.md`, not committed) lists every frame element and
its source; where they differ, this spec wins.

## 2. Decisions (binding, from the user)

Scope
- **S1** Full mockup; every pre-redesign feature (F1-F24) stays reachable, re-homed where the mockup has no place.
- **S2** Release stays 0.8.16, one PR; `CHANGELOG.md` (Indonesian), `docs/prod-upgrade/0.8.16.md` and
  `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` are extended.
- **S3** All 16 recommended defaults D1-D16 of the inventory are accepted; D3 (session-only brief) and B4 (optional
  Redis cache or prompt change) are **replaced** by P1-P8 below.

Shell and views (inventory D1, D2, D10, D13-D15)
- **D1** One route `/exec`, `?view=briefing|board` (default `briefing`), a `SegmentedControl` in the header; the saved
  watchlist also stores the view.
- **D2** Default period stays **90 days** (mockup 180 is illustrative).
- **D10** CSV export stays client-side, gains the B1-B3 fields, and the button is **hidden without `export_data`**.
- **D13** States without a mockup frame: `StatePanel` for page error and no access, skeleton tiles while loading,
  per-card empty lines.
- **D14** KPI deltas: % for the article count, absolute for sectors and actors; red up, green down; the "no
  prior-period data" fallback stays.
- **D15** The toggle label stays **"Threat news only"** (C1).

Data and cards (inventory D5-D9, D11, D12, D16)
- **D5** Backend B1 (monthly totals), B2 (leaderboard velocity and top sectors), B3 (top actor per sector) and B5
  (brief scope) are built.
- **D6** An Analyst-board row **"More signals"** re-homes Campaign clusters, Source reliability spread and Country
  trend (R1-R3), with today's role gates.
- **D7** Leaderboard: "NEW" chip when the previous period is reliable; signal quality in the row tooltip.
- **D8** Heatmap insight sentence is a deterministic client rule, hidden when nothing qualifies.
- **D9** Matrix red threshold = `ceil(0.75 × max)`, legend computed; dot `title` and an sr-only table carry numbers.
- **D11** Heatmap prints a number in every non-empty cell and keeps the drill dialog (restyled, plus "Open in
  Newsroom").
- **D12** Names stay links to entity pages; actor rows also link to Newsroom; "Open Early warning" and "All →" link to
  Intelligence.
- **D16** Mockup row counts with a "Show all" expander where the API returns more (techniques 6/15, velocity 7/10,
  co-targeted 3/15, CVE exposure 6/10).

Brief persistence (replaces D3 and B4)
- **P1** New table `exec_briefs`: **one shared, platform-wide brief per date**, unique `brief_date`, no `client_id`;
  columns for the Markdown, the filters used (JSONB), `generated_at`, `generated_by` (`"scheduler"` or a username),
  model and prompt version. Hand-written migration revising `b7d41e9a2c63`.
- **P2** Beat task from **06:00 Asia/Jakarta**: today's brief with the default filters (90 days, threat news only, not
  confirmed only). **One LLM call per day** for all clients, through the instrumented path (`llm_calls`,
  `prompt_version`).
- **P3** On LLM failure or outage the date stays empty and the failure is logged: no retry storm, no parked rows.
- **P3a** **Hourly catch-up** 06:00-18:00 Asia/Jakarta (same offset setting): when today's brief is missing, one
  attempt per hour at most. A manual brief for today counts as present.
- **P4** Retention 30 days: a daily `maintenance` task purges older rows.
- **P5** Manual `POST /api/exec/brief` (`manage_intel`) generates and replaces **that day's shared brief**, recording
  `generated_by` and the filters used, with the B5 fixes (`days` 7-365, `role="exec"`, no analyst or client-scoped
  sections). The brief input never depends on `X-Client-ID`.
- **P6** Read endpoints under the Exec page permission (`view_intel`): the brief for a date (default today, else the
  latest available) and the dates available in the last 30 days. Every client reads the same brief for a date.
- **P7** Briefing lead card shows the brief of the selected date with a picker over the available dates and
  "generated by {scheduler | username} · {time}" in the browser time zone; empty state "No brief for this date yet"
  with Generate for `manage_intel`. The brief dialog gets Download .md, Copy and Regenerate (Regenerate only with
  `manage_intel`).
- **P8** Card layout uses the D4 client parser with a Markdown fallback; no prompt change.

## 3. Conflicts between inputs, and how they are resolved

- **C1 Toggle label.** Mockup "Incidents only" (and "incidents only" in the dialog meta); the code says "Threat news
  only" because `incident_only` only excludes the non-incident news types. D15 wins in the toolbar, the meta lines and
  the CSV.
- **C2 "Not saved".** Mockup meta "AI brief · generated 14:20 UTC · not saved" and the designer note "Nothing is
  saved" contradict P1. The meta becomes "AI brief · generated by {who} · {time}"; "not saved" is dropped everywhere.
- **C3 Time zone.** Mockup "14:20 UTC"; repo convention is the browser time zone (`fmtTime`, `fmtDateTime`). The brief
  **date**, however, is a calendar date in Asia/Jakarta (P2), shown as a plain date (`parseLocalDate`, no conversion).
- **C4 "Asia/Jakarta" without a new setting.** The repo already has `WorkerSettings.report_utc_offset_hours` (default
  7 = WIB, `WORKER__REPORT_UTC_OFFSET_HOURS=7` in `.env.prod.template`) for every local-time report. The hourly
  06:00-18:00 cron and the brief date both use it (local hours 6-18 → UTC hours 23 and 0-11 at offset 7). **No new
  `Settings` field**; `.env.example` and `.env.prod.template` are unchanged. If an operator ever changes the offset,
  the brief moves with the other local reports, which is the intended coupling.
- **C5 The brief is platform-wide.** Every field the prompt reads (`services/exec_brief.py::_build_user_message`:
  sector risk, spikes, velocity, leaderboard, CVE exposure, TTPs) comes from global articles or from the cross-client
  `cve_tech_severity_breakdown` / `cve_kpi_counts`; with `role="exec"` (B5) the client-scoped sections (critical CVE
  feed, campaign clusters) are not computed. So one brief per date serves every client, the table has no
  `client_id`, and neither the generation nor the read endpoints call `effective_client_id` or read `X-Client-ID`.
  The card says so (6.3).
- **C6 Brief permission.** UI and API gate generation on `manage_intel` (admin/superadmin among system roles);
  `view_config.exec_brief_button` (exec + admin) stays unused. Readers need only `view_intel`.
- **C7 Brief shape.** Mockup: headline sentence + paragraph + numbered findings with title and detail; the prompt
  returns five `##` sections with plain bullets. Resolved by the parser (P8, 6.3); the dialog renders the Markdown.
- **C8 Spike window.** `get_spikes(lookback_days=max(days, 30))` flags the last 7 days against the baseline, not the
  selected period. Hero subtitle: "Sectors whose daily reporting is above baseline (z ≥ 1.5), last 7 days".
- **C9 Fixed month copy.** "last 6 months", "MONTHLY, LAST 6 MONTHS" and "Trend covers Jun – Nov" come from
  `months` (7 d → 1 month, 365 d → 13), not fixed text.
- **C10 IOC confidence.** Mockup "confidence 0.31"; `confidence_score` is 0-100 → "confidence 31" (as 2b C4).
- **C11 Role chips.** Mockup "Analyst only" / "SOC only"; admin sees both and `soc` is not a system role. Copy:
  "Analyst view" / "SOC view", shown from `view_config.sections`.
- **C12 Matrix orientation and size.** Mockup rows = 6 actors, columns = 7 sectors; API returns sectors × actors (≤ 8
  × 8). The UI transposes and shows **all** returned rows and columns (no loss); the mockup size is sample data.
- **C13 Delta format across views.** Mockup "+5 vs prev" (Briefing) and "+9 vs prev 180 d" (board) for the same metric
  are sample inconsistencies; both views read the same field, compact copy on Briefing, long copy on the board.
- **C14 Page h1.** The layout renders one fixed `<PageHeader title="Exec">`; the mockup h1 depends on the period. The
  page renders its own header (6.0); the layout keeps only `metadata`.
- **C15 Velocity colour.** Mockup "Red = more than 20% above its usual monthly pace"; the code colours any rise red
  and shows "NEW" when `avg_prev` is 0 (no NEW in the mockup). Red only above +20 %; "NEW" stays.

## 4. Backend

Conventions. The brief endpoints are platform-wide (C5): no client filter. Router `routers/exec_dashboard.py` keeps the
router-level `require_permission("view_intel")`; `POST /brief` keeps `manage_intel`. Comments and docstrings in
Indonesian, matching the files. New typed responses (4.6) → `uv run python tools/export_openapi.py` and `cd apps/web &&
pnpm run gen:api`; `dashboard-v2` stays an untyped `dict`, so B1-B3 are added to
`apps/web/src/lib/api/loose-types.ts::ExecDashboardV2`, and `ExecBriefResponse` is removed from `loose-types.ts`
(replaced by the generated `ExecBriefOut`).

### 4.1 B1 `monthly_totals`
- **Contract.** `GET /api/exec/dashboard-v2` gains `monthly_totals: list[int]`, aligned with `months`.
- **Logic.** In `services/exec_dashboard.py::get_exec_dashboard_v2`, `[month_totals.get(m, 0) for m in months]` from
  the existing `month_totals` dict (built from `newstype_monthly_raw`, all news types, same filters).
- **Performance.** Zero new queries.
- **Tests.** `tests/integration/test_exec_dashboard_service.py::test_monthly_totals_align_with_months` (length equals
  `months`, sum equals `total_incidents` for the window).

### 4.2 B2 leaderboard enrichment
- **Contract.** Each `ta_leaderboard` row gains `velocity_pct: int | None`, `last_month: int | None`, `avg_prev: float |
  None` and `top_sectors: list[str]` (at most 2, never "General").
- **Logic.** `_compute_ta_velocity` is split: new `_velocity_rows(ta_monthly_raw, months, usable) -> dict[str,
  dict]` returns the row for **every** actor (today's per-actor math unchanged); `_compute_ta_velocity` keeps its
  output (sort by `velocity_pct`, top 10) on top of it. Leaderboard rows look their actor up by name; an actor without
  enough usable history gets `null` for the three velocity fields. `top_sectors`: new
  `AsyncDashboardRepo.top_sectors_by_actor(*, actors, limit=2, exclude=(UNSPECIFIED_INDUSTRY,), **filters) ->
  dict[str, list[str]]`: one grouped query (sector × actor mention join, as `sector_actor_counts`) with
  `row_number() OVER (PARTITION BY actor ORDER BY count DESC, sector)` ≤ `limit`, for the ≤ 10 leaderboard actors.
- **Performance.** `ta_monthly_raw` is already fetched for all actors; one new query bounded by the period and 10
  actors.
- **Tests.** `test_exec_dashboard_service.py::test_leaderboard_velocity_for_actor_outside_velocity_top10` (a declining
  actor not in the velocity top 10 still gets a negative `velocity_pct`), `::test_leaderboard_top_sectors` (order,
  limit 2, "General" excluded, ties by name).

### 4.3 B3 top actor per sector
- **Contract.** Each `sector_risk_scores` row gains `top_actor: str | None`.
- **Logic.** New `AsyncDashboardRepo.top_actor_by_sector(*, sectors, **filters) -> dict[str, str]`: one grouped
  query with `row_number() OVER (PARTITION BY sector ORDER BY count DESC, actor)` = 1, for the sectors in
  `sector_risk_scores` (≤ 8).
- **Tests.** `test_exec_dashboard_service.py::test_sector_risk_top_actor` (highest count wins, tie by name, `null` for
  a sector without actor mentions).

### 4.4 B5 brief scope and the generation service
- **Logic** (`services/exec_brief.py`). `SYSTEM_PROMPT`, `_build_user_message` and therefore `_PROMPT_VERSION` are
  unchanged. Changes:
  - `BRIEF_ROLE = "exec"`: `build_view_config("exec")` turns off `cluster_list`, `fp_feedback_queue`,
    `source_reliability_spread` and `critical_cve_feed`, so the campaign pipeline, the FP queue and the CVE feed are no
    longer computed for a brief. No new flag on `get_exec_dashboard_v2`.
  - `DEFAULT_FILTERS = BriefFilters(days=90, incident_only=True, confirmed_only=False)` (a frozen dataclass with
    `as_json()`), `RETENTION_DAYS = 30`.
  - `brief_today(now: datetime.datetime | None = None) -> datetime.date`: the date at UTC +
    `get_settings().worker.report_utc_offset_hours` (C4). Used by the API and the worker, so both agree on "today".
  - `_call_llm(user_msg) -> tuple[str, str]` returns `(markdown, model)` from `get_llm_client(task="exec_brief")`
    (task name unchanged, so `tests/unit/test_llm_call_sites.py` stays green and `llm_calls` keeps one row per call).
  - `async def draft_brief(session, *, filters) -> BriefDraft(markdown, model, prompt_version)`: calls
    `get_exec_dashboard_v2(session, days=…, incident_only=…, confirmed_only=…, role=BRIEF_ROLE)` (the `client_id`
    default is unused for this role, C5), then the LLM in `asyncio.to_thread`. Any exception from the LLM call, or a stripped-empty answer, raises
    `BriefGenerationError(error_type)`; DB errors propagate unchanged.
  - `async def store_brief(session, *, brief_date, draft, filters, generated_by, replace: bool) -> ExecBrief | None`
    (4.5 repo upsert).
  - `generate_exec_brief(session, days, incident_only, confirmed_only)` is removed (its only caller is the router).
- **Tests.** `tests/unit/test_exec_brief_dates.py` (`brief_today` at 16:59 and 17:00 UTC with offset 7, and with
  offset 0); `tests/integration/test_exec_brief_api.py::test_brief_skips_analyst_and_client_sections`
  (`_get_recent_clusters`, `_get_pending_fp_queue` and `_get_critical_cves` monkeypatched to raise, LLM stubbed). Existing
  `tests/unit/test_prompt_correctness.py::test_exec_brief_*` stay green.

### 4.5 `exec_briefs` table and repository (P1)
- **Model.** New `packages/cti-core/src/cti_core/db/models/exec_brief.py::ExecBrief` (exported from
  `cti_core.db.models`), Indonesian docstring explaining the daily document and the 30-day retention:

  | Column | Type | Notes |
  |---|---|---|
  | `id` | `BigInteger` PK, autoincrement | |
  | `brief_date` | `Date`, not null, unique | Asia/Jakarta date (C4); no `client_id` (C5) |
  | `markdown` | `Text`, not null | the model answer as returned |
  | `filters` | `JSONB`, not null | `{"days": int, "incident_only": bool, "confirmed_only": bool}` |
  | `generated_at` | `DateTime(timezone=True)`, not null, `server_default=func.now()` | set again on replace |
  | `generated_by` | `String(200)`, not null | `"scheduler"` or `users.username` |
  | `model` | `String(120)`, not null | as `llm_calls.model` |
  | `prompt_version` | `String(16)`, nullable | as `llm_calls.prompt_version` |

  `__table_args__ = (UniqueConstraint("brief_date", name="uq_exec_briefs_brief_date"),)`. No other index: the table
  holds at most 31 rows, and the unique index serves every lookup.
- **Migration.** `alembic/versions/c4e8a1f2b9d6_exec_briefs.py`, hand-written, `down_revision = "b7d41e9a2c63"`,
  `op.create_table("exec_briefs", …)` with `op.f("pk_exec_briefs")` and the named unique constraint (no foreign
  key), matching the model column for column (`server_default=sa.text("now()")`);
  `downgrade()` drops the table. Additive: old containers ignore it.
- **Repository.** New `packages/cti-core/src/cti_core/db/repositories/exec_brief.py::AsyncExecBriefRepo`:
  - `get(brief_date) -> ExecBrief | None`;
  - `latest(*, since: date) -> ExecBrief | None` (`brief_date >= since`, newest first);
  - `list_dates(*, since: date) -> list[date]` (newest first);
  - `upsert(*, brief_date, markdown, filters, generated_by, model, prompt_version, replace: bool) ->
    ExecBrief | None`: `postgresql.insert(...)` with `on_conflict_do_update(constraint="uq_exec_briefs_brief_date",
    set_={… , "generated_at": func.now()})` when `replace`, else `on_conflict_do_nothing()` (returns `None` when a row
    already existed); `RETURNING` the row;
  - `purge_before(cutoff: date) -> int`.
  Typed for mypy strict (the package is in the CI mypy scope).
- **Tests.** `tests/integration/test_exec_brief_repo.py` (insert, `replace=False` keeps the first row and returns
  `None`, `replace=True` overwrites and refreshes `generated_at`, `latest`/`list_dates` window, `purge_before` boundary); `tests/integration/test_migrations_match_models.py` must pass.

### 4.6 Brief endpoints (P5, P6)
All in `routers/exec_dashboard.py`; schemas in new `apps/api/src/cti_api/schemas/exec_brief.py`.

- **Schemas.** `ExecBriefFilters {days: int, incident_only: bool, confirmed_only: bool}`; `ExecBriefOut {brief_date:
  date, markdown: str, filters: ExecBriefFilters, is_default_filters: bool, generated_at: datetime, generated_by: str,
  model: str, prompt_version: str | None}`; `ExecBriefRead {today: date, brief: ExecBriefOut | None}`;
  `ExecBriefDates {today: date, dates: list[date]}`. `today` is `brief_today()`, so the UI never derives the Jakarta
  date from the browser clock.
- **`GET /api/exec/brief`** (`view_intel`), query `date: datetime.date | None = None` → `ExecBriefRead`.
  - With `date`: that date's row, else `brief: null`.
  - Without `date`: today's row, else `latest(since=today − 30 days)`, else `null`.
  - The same answer for every client (C5).
  - No audit row (a read).
- **`GET /api/exec/brief/dates`** (`view_intel`) → `ExecBriefDates`: `list_dates(since=today − 30 days)`, newest
  first.
- **`POST /api/exec/brief`** (`manage_intel`), query `days: int = Query(90, ge=7, le=365)`, `incident_only: bool =
  True`, `confirmed_only: bool = False` → `ExecBriefOut` (200).
  - `draft_brief(session, filters=…)`, then `store_brief(..., brief_date=brief_today(), replace=True,
    generated_by=user["username"])`: the shared brief for today is replaced for every client.
  - Audit `generate_exec_brief`, detail `{days, incident_only, confirmed_only, brief_date}` +
    `ip_address`, then `session.commit()`.
  - `BriefGenerationError` → **502** `{"detail": "Brief generation failed. Try again later."}`; nothing is written and
    an existing row for today stays.
  - **Breaking for the web only:** the response was `{brief, generated_at}`; the web is the sole consumer and changes
    in the same PR.
- **Filters other than the defaults (decision).** The manual brief uses the filters the user has on the page, stores
  them in `filters`, and returns `is_default_filters = filters == DEFAULT_FILTERS`. The card and the dialog always
  show the brief's own filters (6.3), so a 30-day or confirmed-only brief is never mistaken for the standard one.
  The hourly check never overwrites it (it skips dates that already have a row, 4.7); the next morning is standard
  again.
- **Tests.** `tests/integration/test_exec_brief_api.py`: GET today, fallback to latest within 30 days, `null` when
  none, explicit date, two clients (`X-Client-ID` A and B) get the identical brief; `dates`
  order and window; POST 403 for analyst (keep the row in `test_api_permissions.py`), `days=6` and `days=366` → 422,
  POST replaces the scheduler row and sets `generated_by`, stores non-default filters with `is_default_filters=false`,
  LLM failure → 502 and the existing row unchanged, audit row written. Add `("GET", "/api/exec/brief")` to
  `tests/integration/test_api_permissions.py::test_analyst_keeps_reading_and_cve_triage` (200 for analyst).

### 4.7 Daily brief and hourly catch-up (P2, P3, P3a)
- **Design (decision): one task, run hourly.** The 06:00 run and the catch-up are the same task `exec.brief_daily`;
  the 06:00 tick is simply the first of the day. Beat entry in `apps/worker/src/cti_worker/beat.py::
  _periodic_schedule()` (the existing static dict; no `Settings` field):
  `"exec-brief-daily": {"task": "exec.brief_daily", "schedule": crontab(minute=0, hour=_brief_hours(offset)),
  "options": {"queue": QUEUE_MAINTENANCE, "expires": 55 * 60}}`, where `_brief_hours(offset)` returns the UTC hours
  of local 06:00-18:00 as a cron list (the `trending_hours` pattern in `_report_schedule`: `",".join(str(h) for h in
  sorted({(h - offset) % 24 for h in range(6, 19)}))`, i.e. `0,1,…,11,23` at offset 7). Maintenance, like
  `recap.generate_weekly` and `newsletter.prepare_monthly`, which also call the LLM.
- **Task** in `apps/worker/src/cti_worker/tasks/periodic.py` (new section "Executive brief harian"):
  `@app.task(bind=True, name="exec.brief_daily", queue=QUEUE_MAINTENANCE)`:
  1. Cheap check first: `_run_async(...)` reads `get(brief_today())`; a row (scheduler or manual) → return
     `{"status": "present"}` with no lock and no LLM call.
  2. Take a Redis lock `exec_brief:{brief_date}` with the existing `cti_worker.beat_lock.BeatLock` (the `_sweep_lock`
     pattern of `cve.enrichment_sweep`), TTL 15 minutes (well above one dashboard build plus `LLM__TIMEOUT_S` ×
     (1 + `LLM__MAX_RETRIES`)). Not acquired → `{"status": "skipped_running"}`.
  3. Under the lock: `generate_scheduled_brief(session, now)` re-reads the row, and only when still missing calls
     `draft_brief(filters=DEFAULT_FILTERS)` and `store_brief(..., generated_by="scheduler", replace=False)` (`INSERT …
     ON CONFLICT DO NOTHING`), then commits. Release the lock in `finally`.
  4. `BriefGenerationError`: log `exec_brief_daily_failed` (structlog: `brief_date`, `error_type`, local hour), return
     `{"status": "failed"}`. No Celery retry, no row, no job; the next hourly tick is the next attempt.
- **No double LLM call.** Three layers: (a) the lock serialises concurrent ticks (a slow 06:00 run and the 07:00 tick,
  or a manual `celery call`); (b) the row re-check under the lock makes the second holder a no-op once the first has
  stored; (c) `ON CONFLICT DO NOTHING` means a race with a manual `POST` (which replaces and takes no lock) can never
  overwrite the manual brief with the scheduler's. **Beat redelivery:** `expires` (55 min) is below the Redis
  `visibility_timeout` (60 min), so a message redelivered after a worker death has expired and is discarded on
  receipt; a worker that dies mid-call leaves the lock to expire, and the next hourly tick (≥ 45 min later) is the
  only new attempt. At most one attempt per hour, at most 13 per day.
- **Why not `enrich_jobs` and the circuit breaker (decision).** `enrich_jobs` is keyed by article URL, its `kind` has a
  CHECK for `classify`/`ttp`, and `enrich.llm_dispatch` hands jobs to the article pipeline: a brief job would need a
  schema change and a second dispatcher, i.e. exactly the parked-row-and-retry machinery P3 rules out. The breaker in
  `cti_core/llm/breaker.py` is computed only from `classify`/`ttp` calls; adding `exec_brief` to `BREAKER_TASKS` would
  let a brief call change article dispatch. The hourly cadence is already a fixed, bounded backoff: one failed call
  (plus the SDK's own `LLM__MAX_RETRIES`) per hour during an outage, visible in `llm_calls` (task `exec_brief`) and
  on the `/data-health` LLM card.
- **Missed ticks.** `CtiScheduler` does not replay missed ticks, but the next hourly tick covers them; only a beat or
  LLM outage across the whole 06:00-18:00 window leaves the date empty (manual Generate still works).
- **Tests.** `tests/unit/test_beat_schedule.py::test_exec_brief_entries` (`exec-brief-daily` at minute 0, hours
  `0-11,23` UTC with offset 7 and `6-18` with offset 0, `expires` 3300, `exec-brief-purge` at 03:45, both on
  `maintenance`); `tests/integration/test_exec_brief_schedule.py` (LLM stubbed: missing → one row with
  `generated_by="scheduler"` and default filters; present (scheduler or manual) → no lock, no LLM call; lock held →
  `skipped_running`, no call; failure → no row, next run tries again; empty answer = failure; a manual row inserted
  between the re-check and the insert survives (`ON CONFLICT DO NOTHING`)). Lock tests use the Redis testcontainer.

### 4.8 Retention purge (P4)
- **Beat entry** `"exec-brief-purge": {"task": "exec.purge_briefs", "schedule": crontab(hour=3, minute=45),
  "options": {"queue": QUEUE_MAINTENANCE}}` (03:45 UTC is free between `llm.purge_calls` 03:40 and
  `story.purge_empty` 03:50).
- **Task/service.** `exec.purge_briefs` in `tasks/periodic.py` → `services/exec_brief.py::purge_old_briefs(session,
  now)`: `purge_before(brief_today(now) − RETENTION_DAYS)`, logs `exec_briefs_purged` with the count. Kept dates are
  `today − 30 … today`, the same window the read endpoints use.
- **Tests.** In `tests/integration/test_exec_brief_schedule.py::test_purge_keeps_30_days` (rows at −31, −30, 0: only
  −31 removed).

### 4.9 Documentation touched
- `CHANGELOG.md`, 0.8.16 entry (Indonesian). *Ditambahkan:* brief eksekutif harian tersimpan, satu untuk seluruh
  platform dan sama untuk semua klien (tabel `exec_briefs`, dibuat otomatis mulai 06:00 WIB dengan filter default
  90 hari, dicoba lagi tiap jam sampai 18:00 WIB kalau belum ada, disimpan 30 hari);
  `GET /api/exec/brief` dan `GET /api/exec/brief/dates`; dashboard eksekutif: `monthly_totals`, velocity dan dua sektor
  teratas per aktor di leaderboard, aktor teratas per sektor; halaman Exec dipecah jadi Briefing dan Analyst board
  (`?view=`). *Diubah:* `POST /api/exec/brief` kini membatasi `days` 7-365, tidak menghitung bagian khusus analis
  atau per klien, menyimpan hasil sebagai brief bersama hari ini (menggantikan brief scheduler untuk semua klien) dan
  mengembalikan `ExecBriefOut`; gagal LLM → 502; tombol Export CSV butuh `export_data`. Header line: one more additive
  migration (`c4e8a1f2b9d6`), still no `.env` key.
- `docs/prod-upgrade/0.8.16.md` and `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md`:
  - *Migrations:* revision `c4e8a1f2b9d6` (table `exec_briefs`) on top of `b7d41e9a2c63`; after deploy
    `alembic_version` is `c4e8a1f2b9d6`.
  - *Settings:* none; the schedule uses `WORKER__REPORT_UTC_OFFSET_HOURS` (7 on prod).
  - *Beat restart:* the two new entries load only when `beat` starts; `make deploy` recreates it, a manual
    `docker compose ... up -d` of other services does not. Check with `celery -A cti_worker.celery_app inspect
    registered` (tasks `exec.brief_daily`, `exec.purge_briefs`) and the beat log line for `exec-brief-daily`.
  - *Daily LLM cost:* about **one `exec_brief` call per day** for the whole platform (~1.5-2.5 k tokens: prompt ~1 k,
    answer ~0.6-1 k), plus one catch-up attempt per hour while the gateway fails (at most 13 a day), plus manual
    generations. Measure with `SELECT date(at), status, count(*), sum(prompt_tokens), sum(completion_tokens) FROM
    llm_calls WHERE task = 'exec_brief' GROUP BY 1, 2`.
  - *After deploy:* next morning, one row for today (`SELECT brief_date, generated_by, generated_at FROM exec_briefs
    ORDER BY brief_date DESC LIMIT 3`), or generate one by hand from Exec → Briefing; failures show in
    `/data-health` (LLM, task `exec_brief`) and the worker log `exec_brief_daily_failed` (the next hour retries).
  - *Rollback:* image rollback leaves the table unused (additive); downgrading the migration drops stored briefs.
- `docs/ARCHITECTURE.md`: two rows in the periodic-task table (`exec.brief_daily`, `exec.purge_briefs`) and one row in
  the table list (`exec_briefs`: writer `exec.brief_daily` and `POST /api/exec/brief`, reader Exec page).

## 5. Migration summary

One additive migration, `alembic/versions/c4e8a1f2b9d6_exec_briefs.py` (revises `b7d41e9a2c63`, the current head):
creates `exec_briefs` (4.5). Hand-written; `tests/integration/test_migrations_match_models.py` must pass with the new
model. No backfill. No new `Settings` field (C4), so `.env.example` and `.env.prod.template` are unchanged. Syrupy
snapshot to update after review: `tests/integration/test_exec_dashboard_router_snapshot.py` (`--snapshot-update`, B1-B3
fields). Contract files to regenerate and commit: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`.

## 6. UI

Global rules (as 2b). Desktop 1440 first (content width 1328). Two-column rows collapse to one column below 1024 px
(`lg:`). No `backdrop-blur`. Colours only through tokens; text on tints uses `text-X-text`; heat tints cap alpha.
Focus ring `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2
focus-visible:ring-offset-background` (`ring-offset-hero` inside `HeroPanel`). Minimum text 11 px (`text-2xs`). Base
UI, not Radix (`render={<X/>}`, `SelectItem` children a single string, `Select items` for sentinel values). TTP and
CVE ids, IOC values in `font-code`. All times through `lib/format.ts` (browser time zone); no `UTC`/`WIB` literal in
Exec views except the schedule hint "06:00 Jakarta time" (a fixed fact, not a converted time). The mockup's wide
separators ("  ·  ") are visual spacing, rendered " · ". Fixed copy below is verbatim from the frames unless a C-rule
says otherwise.

### 6.0 Page shell (both views)
- **Routing.** `app/(app)/exec/layout.tsx` keeps `metadata.title = "Exec"` and stops rendering `PageHeader` (C14).
  `page.tsx` reads `?view=briefing|board` (`useSearchParams`, invalid → `briefing`; `router.replace` on change) and
  sets `document.title` to "Exec briefing · {PLATFORM_NAME}" / "Analyst board · {PLATFORM_NAME}" (the root
  template's suffix) with the restore-on-unmount pattern of `components/entities/entity-view.tsx`.
- **Header** (`components/exec/exec-page-header.tsx`): `PageHeader kicker="EXECUTIVE" title="Threat posture, last
  {days} days"` and description "{fmtShortDate(today − days)} – {fmtShortDate(today, with year)} · {total_incidents}
  {threat news articles | articles | confirmed incidents} · {unique_ta_count} threat actors · updated
  {fmtAgo(dataUpdatedAt)}" (count noun from `execCountLabel`, lower case); `actions` = view `SegmentedControl`
  "Briefing" | "Analyst board" (`aria-label` "Exec view").
- **Toolbar** (`exec-filter-bar.tsx`, rebuilt), left: period `SegmentedControl` "7d | 30d | 90d | 180d | 365d"
  (default 90, D2; `aria-label` "Period"); `Checkbox` "Threat news only" (C1) and "Confirmed only"; for admin and
  superadmin only, `Select` "Role preview: {value}" with items "None", "analyst", "soc", "exec", "admin" (`items`
  prop; "None" = no `role` param), and when a preview is active a neutral `Chip` "Previewing {role}" (replaces the
  "View: ROLE" badge, F4-F5). Right: `StarToggle`-style button "☆ Save watchlist" / "★ Watchlist saved"
  (`aria-pressed`; on = filters + view saved to localStorage, off = cleared, F6); "Export CSV" outline (only with
  `export_data`, D10); "✦ Generate brief" primary (only with `manage_intel`, C6; `loading` "Generating…").
- **Watchlist.** `lib/exec/filters.ts`: `saveExecWatchlist` also stores `view`; `restoreExecWatchlist` returns it; on
  load an explicit `?view=` wins over the saved view. Keys unchanged (`cti_exec_idea_watchlist_v1`,
  `exec_role_preview`), so existing saved views still restore.
- **Footnote** (bottom of both views, `text-2xs` muted), by filter:
  - default: "Counts are threat news articles, not confirmed incidents; only Confirmed rate uses LLM-verified
    incidents. CVE figures cover all tracked CVEs and ignore the period filter."
  - "Threat news only" off: "Counts are all articles, not confirmed incidents; only Confirmed rate uses LLM-verified
    incidents. CVE figures cover all tracked CVEs and ignore the period filter."
  - "Confirmed only" on: "Counts are LLM-confirmed incidents. CVE figures cover all tracked CVEs and ignore the period
    filter."
- **Data.** One `useQuery(["exec","dashboard-v2",days,incidentOnly,confirmedOnly,rolePreview])` for both views (as
  today); switching views does not refetch. Client switching reloads the page (`client-switcher.tsx`), so no client
  key is needed.

### 6.1 Briefing view (frame 40179)
- **Lead row** (`lg:grid-cols-[2fr_1fr]`): Brief card (6.3) and Sector spikes.
- **Sector spikes** (`HeroPanel`): kicker "SECTOR SPIKES" + count `Chip` (rows after dedupe); subtitle "Sectors whose
  daily reporting is above baseline (z ≥ 1.5), last 7 days" (C8). Rows from `industry_spikes`, one per sector (highest
  z, keeps its date): sector name (link to the entity page, `EntityChip` text style), severity `Chip` HIGH/MEDIUM, "z
  {z_score}", `MeterBar variant="baseline"` (fill = `count` vs max count in the list, tick = `baseline_mean`, white tick
  on hero), caption "{count} vs {baseline_mean} avg · {fmtShortDate(date)}" (date kept, R7). Note "Bar = articles on
  the spike day; white tick = baseline mean." Link "Open Early warning →" (`/intelligence/early-warning`). Empty: "No
  sector above baseline in the last 7 days".
- **KPI row**: eight `StatTile`s, labels verbatim: "THREAT NEWS" (label follows `execCountLabel`: THREAT NEWS /
  ARTICLES / CONFIRMED INCIDENTS), "ACTIVE SECTORS", "UNIQUE TAs", "CRITICAL CVEs", "KEV CVEs", "TOP RISK SECTOR",
  "ACTIVE SPIKES", "CONFIRMED RATE". Subs: "{±n}% vs prev {days} d" (percent, D14), "{±n} vs prev" for sectors and actors
  (absolute), "all tracked", "CISA KEV · all tracked", "risk {score} / 100", "sectors, z ≥ 1.5", "verified by LLM".
  Delta text `text-destructive-text` when up, `text-success-text` when down; "no prior-period data" when
  `prev_period_reliable` is false; CONFIRMED RATE "—" with "no verified articles yet" when `null`.
- **Sector risk** (left, `lg:col-span-3` of 5): "Sector risk" / "Risk = volume (0–50) + trend (0–20) + spike (0–30),
  from monthly articles"; link "How is risk scored?" opens a `Tooltip`/popover with today's `RISK_FORMULA_TITLE` text
  (moved to `lib/exec/format.ts`). Table SECTOR (entity link) | RISK (`MeterBar` 0-100 + score + `Chip kind="risk"`
  HIGH/MED/LOW via `riskTier`) | ARTICLES (sum of `sector_trend[].data`) | MONTHLY TREND (`Sparkline`) | VS AVG SHARE
  (`sectorPeerBenchmark`, "+14.2%") | TOP TA (`top_actor`, B3, entity link; "—" when `null`). All returned rows (≤ 8).
  Footnote "Trend covers {first month} – {last month}. Articles tagged “General” ({sector_unspecified}) have no sector
  and are left out." (C9), plus " Not enough monthly history yet, so risk uses volume only." when
  `risk_volume_only` (R9).
- **Threat actors** (right): "Threat actors" / "By article count; velocity = last month vs prior average"; link "All
  →" (`/intelligence/entities?tab=actors`). Rows `ta_leaderboard`, 5 + "Show all" (10): rank "01", name (entity link)
  + "NEW" chip when `prev_period_reliable` and the actor is not in `prev_ta_names` (D7), "most seen in {top_sectors
  joined " · "}" (B2, hidden when empty), count (large; link to `newsroomHref({actor, from: today − days})` with
  `aria-label` "{count} articles about {actor} in Newsroom", D12), velocity "{+n}%" (`text-destructive-text` when > 20,
  "—" when `null`, C15). Row `title`: "Signal quality {ta_confidence}%" (D7).
- **CVE exposure by technology** (left): "CVE exposure by technology" / "Tracked CVEs per tech, top 10, false
  positives excluded"; link "CVE Tracker →" (`/cve`). Table TECHNOLOGY | CVEs | CRITICAL (`MeterBar` + n) | HIGH |
  MEDIUM | MAX CVSS (`cvssColorClass`) | POC ("{n} PoC" chip or "–"); 6 rows + "Show all" (10).
- **Top techniques** (right): "Top techniques" / "ATT&CK techniques by article count, {days} d"; rows TTP id
  (`font-code`, entity link), name, count, full-width `MeterBar`; 6 + "Show all" (15).

### 6.2 Analyst board (frame 40692)
- **KPI row**: four large `StatTile`s:
  1. THREAT NEWS (per `execCountLabel`), "{±n}% vs prev {days} d", `Sparkline` of `monthly_totals` (B1).
  2. "UNIQUE THREAT ACTORS", "{±n} vs prev {days} d", "top: {ta_leaderboard[0].name} · {count}".
  3. "CRITICAL CVEs · {cve_kpis.kev} KEV", value `cve_kpis.critical`, "all tracked, no period filter", "{tech} {n} ·
     {tech} {n}" (top 2 `cve_exposure_v2` by `critical`, names as returned).
  4. "CONFIRMED RATE", "verified by LLM", "of threat news" (`null` as 6.1).
- **Sector heatmap** (left): "Sector heatmap" / "Articles per sector per month, last {months.length} months" (C9);
  `LegendRow` "fewer" … "more" (5 swatches). `HeatGrid` of `HeatCell variant="scale"` (`count / heatmap_max`), rows =
  `sector_heatmap` sectors (all returned), columns = short month names; a number in every non-empty cell (D11);
  keyboard via `useGridRovingKeys`; Enter/click opens the drill dialog (6.4). Insight (D8, `text-xs` muted, hidden
  when nothing qualifies): among sectors with ≥ 3 earlier months, those whose last month exceeds their own earlier
  maximum; the largest gain wins: "{sector} reached its highest month in {month name} ({n} articles)."
- **News types** (right): "News types" / "Share of {total_incidents} {count noun}"; `ShareBar` (6.6) of
  `news_type_breakdown`, top 5 + "Other" when there are more than 6 types; legend rows "{type} {n} · {pct}%"; kicker
  "MONTHLY, LAST {months.length} MONTHS"; `StackedBarChart` of `newstype_trend`.
- **Sector trend** / **Victim country trend**: "Sector trend" / "Monthly articles, top 4 sectors" (`MultiLineChart`,
  `sector_trend` first 4); "Victim country trend" / "Monthly articles naming a victim country"
  (`victim_country_trend` first 4, country labels as `charts-section.tsx` today). Full series stay in the CSV.
- **Who targets which sector** (left): "Who targets which sector" / "Articles linking each actor to a victim sector".
  `components/exec/actor-sector-dots.tsx`: rows = `sector_actor_matrix.actors`, columns = `sectors` (transposed, all
  returned, C12), header abbreviations from `SECTOR_ABBR` (FINANCE, GOV, HEALTH, TELECOM, MANUF., RETAIL, ENERGY, …;
  fallback: first 7 letters upper-case) with the full name in `<abbr title>`. Dot diameter ∝ √(count / max); "·" for
  0; `bg-destructive` when count ≥ `ceil(0.75 × max_val)`, else `bg-foreground`. Each dot `title` "{actor} ×
  {sector}: {n} articles"; an sr-only `<table>` holds the numbers. Note "Dot size = article count. Red = {threshold}
  or more." (D9).
- **Actor velocity** (right): "Actor velocity" / "Last month vs the average of earlier months"; rows `ta_velocity`, 7 +
  "Show all" (10): actor (entity link), "{last_month} vs {avg_prev} avg", "{+n}%" (`text-destructive-text` when > 20,
  C15; "NEW" chip instead when `avg_prev` is 0). Note "Red = more than 20% above its usual monthly pace." Kicker
  "CO-TARGETED SECTORS": `sector_cooccurrence` rows "{a} · {b}" + "{count} articles", 3 + "Show all" (15).
- **Queues row** (rendered only when at least one card is visible; one card spans the row):
  - **IOC false-positive queue** (`view_config.sections.fp_feedback_queue`): "IOC false-positive queue" / "Analyst view ·
    IOCs waiting for a verdict, top 20" (C11); `Chip` "{pending_fp_total} pending"; rows value (`font-code`,
    truncated with `title`), type chip, "confidence {confidence_score} · last seen {fmtCompactAge(last_seen)} ago"
    (C10), buttons "TP / restore" and "FP: remove" (`manage_ioc`; read-only text otherwise). "FP: remove" opens the
    2b Remove dialog, extracted from `ioc-detail-body.tsx` into `components/intelligence/ioc/ioc-remove-dialog.tsx`
    and used by both; the source-FP warning toast stays (F22). 5 rows + "Show all" (20); footer "Showing {n} of
    {pending_fp_total} pending" with a link to `/intelligence/iocs`.
  - **Critical CVE feed** (`critical_cve_feed`): "Critical CVE feed" / "KEV CVEs matched to this client's tech stack ·
    SOC view" (C11); link "CVE Tracker →"; rows CVSS (`cvssColorClass`), CVE id (`font-code`, entity link), tech,
    "KEV" chip, severity chip ("critical"); 5 + "Show all" (20). Empty: "No KEV CVE matches this client's tech
    stack".
- **More signals** (D6): `<h2>` "More signals", three cards in one `lg:grid-cols-3` row, each only when its gate holds:
  "Campaign clusters" (`cluster_list`: rows title → `/intelligence/campaign-clusters?id={cluster_id}`, size, actor
  chips, `fmtCompactAge(last_seen)`), "Source reliability spread" (`source_reliability_spread`: `GradedDoughnutChart`
  as today), "Country trend" (all roles: `MultiLineChart` of `country_trend`, all returned series).

### 6.3 Brief card and dialog (P7, P8)
- **Queries.** `useQuery(["exec","brief",selectedDate ?? "default"])` → `GET /api/exec/brief[?date=]`;
  `useQuery(["exec","brief-dates"])` → `GET /api/exec/brief/dates`. `selectedDate` starts `null` (server default:
  today, else latest); after load the picker shows the returned `brief_date`. Every successful POST invalidates both
  keys and sets `selectedDate` to `today`.
- **Card** (`components/exec/brief-card.tsx`, `bg-surface` tile, the mockup's warm tint mapped to the existing token):
  header kicker "EXECUTIVE SUMMARY"; right: `Select` "Brief date" (`aria-label`; items from `dates`, labels "Today",
  "Yesterday", else `fmtShortDate`, via `items`) and meta "AI brief · generated by {generated_by} · {time}" (`time` =
  `fmtTime(generated_at)` when `brief_date` is today, else `fmtDateTime`). When `is_default_filters` is false, a
  neutral line "Filters: last {days} days · {threat news only | all articles}{ · confirmed only}". Under the meta a
  `text-2xs` muted note "Platform-wide brief, the same for every client." (C5).
- **Parsed body** (`lib/exec/brief.ts::parseBrief(markdown) -> ParsedBrief | null`, pure):
  - split on `^##\s+` headings; names matched case-insensitively;
  - "Executive Summary": first sentence (split at the first `. `, `! ` or `? ` followed by a capital letter or end) =
    **headline** (inline Markdown stripped), the rest = **paragraph** (rendered with `react-markdown` in `.prose`);
  - "Key Findings & Recommendations": list items (`-`, `*`, `•`, `1.`); a leading `**Title.**` is the title, else the
    first sentence; the rest = detail (may be empty); the card shows the first 3 as a numbered list (bold title + one
    detail line, mockup) and "+{n} more in the full brief" when longer;
  - every other non-empty section name, in order → "Also in the brief: {names joined " · "}";
  - returns `null` when there is no "Executive Summary" section or its headline is empty.
  Card footer: "Also in the brief: …" and link "Read full brief →" (opens the dialog). **Fallback** (`null`): the first
  ~600 characters of the Markdown rendered in `.prose` with a fade, plus "Read full brief →".
- **States.**
  - Loading: skeleton (headline bar, three lines, three list rows).
  - Default load returned an older date: `Notice` "Today's brief is not ready yet. Showing {fmtShortDate(brief_date)}."
  - No brief for the selected date (or none at all): `StatePanel` empty "No brief for this date yet"; with
    `manage_intel` a "Generate brief" button (today only; for a past date the hint "Briefs can only be generated for
    today."); without it "Briefs are generated every morning from 06:00 Jakarta time, retried hourly until 18:00."
  - Generating: the card keeps its content and shows `Notice` "Generating a new brief. This can take up to a minute."
  - POST 502: toast error "Brief generation failed. Try again later." (the `detail`), content unchanged.
  - Error on GET: `StatePanel` error with Retry.
- **Generate and replace.** Toolbar "✦ Generate brief" posts the **page** filters. When today already has a brief, a
  `ConfirmDialog` first: title "Replace today's brief?", body "Everyone who opens Exec, for every client, sees the new
  brief. The current one ({generated_by}, {time}) is overwritten. Generating takes up to a minute and is one LLM
  call.", confirm "Generate brief" (`confirmLoading`). Success toast "Brief generated" with action "Open" (opens the
  dialog); on the board the toast is the only feedback.
- **Brief dialog** (`brief-modal.tsx`, rebuilt): `DialogTitle` "Executive brief"; `DialogDescription` meta "{brief date
  with year} · Last {days} days · {threat news only | all articles}{ · confirmed only} · generated by {generated_by} ·
  {time}" (C1, C2, C3); close "✕" (`aria-label` "Close"). Body: the full Markdown via `react-markdown` in `.prose`
  (`max-h` with inner scroll). Footer: "AI draft. Review before sharing." (muted, left); "Download .md" (outline: a
  `Blob` of the Markdown as is, filename `exec-brief-{brief_date}.md`), "Copy" (outline, toast "Copied to
  clipboard"), "Regenerate" (only with `manage_intel` and when `brief_date` is today; same confirm, posts the
  **brief's stored** filters so the same kind of brief comes back; `loading` "Regenerating…"; the dialog stays open
  and shows the new content).

### 6.4 Other dialogs
- **Sector heatmap drill** (`sector-heatmap.tsx` drill, restyled, F16): title "{sector} · {month name year}",
  description "{n} articles"; the existing 20-article list (`GET /api/articles?industry=&posted_on_start=&
  posted_on_end=`: title link, "{source} · {date}", actor chips); footer link "Open in Newsroom →"
  (`newsroomHref({industry, from: month start})`) with the hint "Newsroom shows articles from {month start} onward."
- **Replace brief** (6.3) and **Remove IOC** (6.2, the 2b dialog). All dialogs: `Dialog` + `DialogDescription`,
  Cancel ghost, primary `loading`, API errors inline or toast, focus returns to the trigger.

### 6.5 States
Page: `StatePanel` loading (skeleton tiles and cards), error with Retry, no access (`view_intel` missing; the route
guard already hides the nav item). Cards: per-card empty copy ("No sector above baseline in the last 7 days", "No
threat actor in this period", "No CVE exposure tracked", "No technique in this period", "No pending IOC", "No campaign
in the last 30 days"). Write actions hidden without permission (Generate, Regenerate, TP/FP, Export CSV). Role preview
changes what the board shows exactly as today.

### 6.6 New primitives and domain pieces (existing ones reused as they are)
1. **`Sparkline`** moved from `components/dashboard/stat-box.tsx` to `components/ui/sparkline.tsx` (exported,
   `aria-hidden`, tone tokens); `StatBox` imports it; `StatTile` gains an optional `spark?: number[]`.
2. **`ShareBar`** (`components/ui/share-bar.tsx`): one 100 % stacked bar from `{label, value}[]`, chart-series tokens,
   `role="img"` with an `aria-label` listing shares, legend rows rendered by the caller.
3. **`ActorSectorDots`** (`components/exec/actor-sector-dots.tsx`, 6.2).
4. **`BriefCard`**, **`ExecPageHeader`**, `lib/exec/brief.ts` (`parseBrief`, `briefFiltersLabel`), `SECTOR_ABBR` and
   `RISK_FORMULA_TITLE` in `lib/exec/format.ts`; `buildExecCsv` gains `monthly_totals`, leaderboard `velocity_pct` /
   `top_sectors`, and sector `top_actor`.
5. **`ShowAll`** expander: a text button "Show all ({n})" / "Show fewer" with `aria-expanded`, used by the D16 lists
   (`components/exec/show-all.tsx`; promoted to `ui/` only if a second page needs it).
6. Reused: `HeroPanel`, `MeterBar` (`baseline`), `HeatGrid`/`HeatCell` (`scale`), `LegendRow`, `StatTile`,
   `StarToggle`, `SegmentedControl`, `Chip` (`risk`, `severity`), `StatePanel`, `Notice`, `ConfirmDialog`, `Tooltip`,
   `EntityChip`, Chart.js wrappers in `components/dashboard/charts.tsx`.

Replaced or removed: `kpi-strip.tsx` (→ `StatTile` rows), `tier2-panels.tsx` (`SpikeBanner` → hero; `TtpList`,
`TaVelocity`, `SectorCooccurrence` → board/Briefing cards), `sector-actor-matrix.tsx` (→ dots), the doughnut in
`charts-section.tsx` (→ `ShareBar`, R11). `role-gated-panels.tsx` keeps `ClusterList`, `FpQueue`, `CriticalCveFeed`,
restyled.

## 7. Out of scope
- A prompt change or structured (JSON) brief output (P8 uses the parser); brief history beyond 30 days; per-client
  brief schedules or time zones; client-specific briefs (C5).
- Notifying (Telegram, mail) when the daily brief is ready or fails.
- Server-side CSV export or an audit row for the Exec CSV (D10).
- Changing the risk, spike or velocity algorithms; the `dashboard-v2` response stays an untyped dict.
- A system `soc` or `exec` role (C11); `view_config.exec_brief_button` gating (C6).
- Mobile layouts beyond the 1024 px collapse; `GET /api/exec/dashboard` (v1) stays as is.

## 8. Verification
- **Backend tests.** `uv run pytest tests/integration -k "exec or migrations_match or api_permissions"` (Docker),
  then `uv run pytest tests/unit tests/contract packages` (deselect the two known Mac-only failures). Named tests:
  4.1-4.8. Cross-cutting: two clients read the identical brief and dates; analyst reads (200) but cannot POST (403);
  the hourly task makes no LLM call for a date that already has a row or while the lock is held; `test_llm_call_sites.py` and
  `test_prompt_correctness.py` unchanged and green.
- **Static.** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src
  packages/cti-scraper/src` (covers the new model and repository).
- **Contract.** `uv run python tools/export_openapi.py`; `cd apps/web && pnpm run gen:api`; commit both; update
  `loose-types.ts` (`ExecDashboardV2` B1-B3, drop `ExecBriefResponse`); review and `--snapshot-update`
  `test_exec_dashboard_router_snapshot.py`.
- **Migration.** Fresh `alembic upgrade head` → `c4e8a1f2b9d6`; `alembic downgrade -1` and up again on the isolated
  database.
- **Web.** `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit`; `pnpm build`. The parser has no unit
  runner: check it in QA against three stored briefs (normal output, `**Title.**` bullets, a reply without headings →
  fallback).
- **Visual (local).** Isolated compose project `qacve`, API via uvicorn, web via `pnpm dev`, synthetic data (two
  clients, briefs on several dates incl. a non-default-filter one and a gap, spikes, a full leaderboard, FP queue,
  KEV matches, campaigns), LLM stubbed. Run `exec.brief_daily` twice by hand (`celery call`): one row, and the
  second run returns `present` with no new `llm_calls` row. Screenshots of both views, the brief dialog, the replace confirm and the drill
  dialog at 1440 and 1000 px, light and dark, against 40179/42159, 40692/42672 and 35068/36123. Checks: keyboard pass
  (view switch, period, checkboxes, date picker, heat grid, Show all, dialogs), contrast of the hero rows and dots in
  both themes, no `UTC` literal, every inventory F1-F24 feature reachable (checklist in the PR), every Newsroom link
  filters.
- **Delivery.** Commit per backend item and per view; merge into `origin/Dev` (standing approval). On dev
  172.25.1.77 (read-only checks): `alembic_version`, beat log shows `exec-brief-daily`, the next morning's row, and
  one manual Generate only with the user's go (one LLM call).

## 9. Risks
- **Whole-day outage.** The date stays empty only if the LLM gateway (or beat) is down for the whole 06:00-18:00
  Jakarta window; the card then shows yesterday with the "not ready yet" notice, and `manage_intel` can still
  generate by hand.
- **Maintenance slot.** One run (~10 s of queries + up to a minute of LLM) holds one child of the worker shared with
  `scrape.rss`/`scrape.api`/`notify` (concurrency 4), once a day, or once an hour during an outage.
- **Data window.** `get_exec_dashboard_v2` uses the server (UTC) date, so the 06:00 WIB run covers articles through
  the previous UTC day (later catch-up runs include part of the current UTC day); this matches a morning brief but
  differs from the Jakarta `brief_date` by up to 7 hours.
- **Manual overwrite.** A manual brief replaces the scheduler's for every client, possibly with custom
  filters; the confirm dialog and the filters line make that visible, and the next morning is standard again.
- **Parser fragility.** Model output can drift from the five headings; the fallback renders the Markdown, and the
  dialog always shows the full text.
- **POST response shape changes** (`{brief, generated_at}` → `ExecBriefOut`); only the web consumes it, changed in the
  same PR. Machine clients (API tokens) did not use it.
- **Beat restart** is required for the two new entries; a partial restart leaves the schedule without them (runbook).
- **Dense board** in dark mode (heat cells, dots, hero meter ticks): verified per `apps/web/CLAUDE.md` in both themes.
