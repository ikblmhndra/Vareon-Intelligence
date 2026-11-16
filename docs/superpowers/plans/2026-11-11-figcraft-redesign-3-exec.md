# FigCraft redesign 3: Exec Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the full FigCraft Exec mockup (Briefing, Analyst board, brief dialog) with every pre-redesign feature F1-F24 still reachable, the missing data (B1-B3), the brief scope fix (B5) and a stored, platform-wide daily executive brief, inside the 0.8.16 release.

**Architecture:** Backend first: Tasks 1-6 add the dashboard fields, the `exec_briefs` table, the brief service, the endpoints, the hourly catch-up task and the retention purge (spec 4.1-4.8), each with its own pytest cycle; Task 7 regenerates the API contract once, updates `loose-types.ts` and the syrupy snapshot. Then the web: primitives (8), shell (9), Briefing (10-11), brief card and dialog (12-13), Analyst board (14-17), states sweep (18), docs (19) and the final verification (20).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Celery beat + Redis `BeatLock`, pytest + testcontainers + syrupy; Next.js 16 App Router, React 19, TanStack Query, Tailwind v4, shadcn on Base UI (`@base-ui/react`), `openapi-fetch` (`api` from `@/lib/api/client`), Chart.js (`components/dashboard/charts.tsx`), `react-markdown`, `lucide-react`, `sonner`.

**Spec:** `docs/superpowers/specs/2026-11-11-figcraft-redesign-3-exec-design.md` (binding; section numbers below refer to it). The gap inventory (`.superpowers/brainstorm/exec-inventory.md`, F1-F24) is context only; where it differs, the spec wins.

## Global Constraints

- One additive migration: `alembic/versions/c4e8a1f2b9d6_exec_briefs.py`, `down_revision = "b7d41e9a2c63"`, hand-written. `tests/integration/test_migrations_match_models.py` passes after Tasks 2-6. No new `Settings` field (C4: the schedule reuses `WORKER__REPORT_UTC_OFFSET_HOURS`); `.env.example` and `.env.prod.template` unchanged.
- Release stays 0.8.16 (`## [0.8.16] - 2026-11-08`), one PR, no version bump; `uv.lock` stays `revision = 3`.
- The brief is platform-wide (C5): no `client_id` column, and neither generation, the worker nor the read endpoints call `effective_client_id` or read `X-Client-ID`. Router-level `view_intel` stays; `POST /brief` keeps `manage_intel`; the Exec CSV needs `export_data`; IOC verdict buttons need `manage_ioc`. Gate each control on exactly that backend permission (`useCan()`), never a stricter one.
- Comments and docstrings Indonesian, explaining *why*, matching the surrounding file. Docs under `docs/` English; `CHANGELOG.md` and `docs/PROGRESS.md` Indonesian.
- Commits: English conventional (`feat(api): ...`, `feat(web): ...`); the body ends with a blank line + the implementer's own model trailer (`Co-Authored-By: <the model that wrote the commit> <noreply@anthropic.com>`; the session's attribution reminder is authoritative, not a copy of an older trailer). Stage only your own files. Never push, merge or switch branches (`claude/figcraft-design-data`).
- Python checks: `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src packages/cti-scraper/src` (covers the new model and repo). Fast suite: `uv run pytest tests/unit tests/contract packages --deselect tests/contract/test_golden.py::test_golden_trendmicro` (also deselect the two known Mac-only failures). Integration needs Docker, isolated compose project `qacve` only (never `deploy-postgres-1`): `uv run pytest tests/integration -k "<pattern>"`.
- Contract: regenerated ONCE in Task 7. Tasks 1-6 do not run `tools/export_openapi.py` and do not run `test_exec_dashboard_router_snapshot.py`; Task 7 reviews and updates it. `dashboard-v2` stays an untyped `dict`, so its new fields go to `loose-types.ts::ExecDashboardV2` by hand. `ExecBriefResponse` is deleted from `loose-types.ts` and replaced by the generated `ExecBriefOut`.
- openapi-typescript marks defaulted query params required: every web call to `POST /api/exec/brief` sends `days`, `incident_only` and `confirmed_only` explicitly. `GET /api/exec/brief` `date` has no default and is sent only when set.
- Web (`apps/web`): read `apps/web/AGENTS.md` and `apps/web/CLAUDE.md` first. Base UI, not Radix: `render={<X/>}` (never `asChild`), `SelectItem` children a single string, `items` on `Select` for sentinel values. Theme tokens only; text on tints `text-X-text`; heat tints cap alpha; no `backdrop-blur`; minimum text 11 px (`text-2xs`); TTP/CVE ids and IOC values in `font-code`; heat steps and dots legible in dark mode; a `Chip` inside `HeroPanel` uses the hero-safe tokens of the 2b fix `fix(web): ... hero chips`; `table-fixed` always with explicit column widths. Focus ring: `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background` (`ring-offset-hero` inside `HeroPanel`). Two-column rows collapse below 1024 px (`lg:`).
- No interactive element nested inside a clickable row or tile: Exec rows are not clickable; the entity link, the count link and the buttons are siblings. Heat cells are the only buttons in their grid.
- react-query: the brief queries and the dashboard query do not retry 4xx (`retry: (n, e) => n < 2 && !isClientError(e)`, reuse the helper if one exists, else a local one in `lib/exec/query.ts`). Any `useDebounced` input is a memoised object.
- Dates only through `lib/format.ts` (browser time zone): `fmtShortDate`, `fmtDateTime`, `fmtTime`, `fmtCompactAge`, `fmtAgo`, `parseLocalDate`. The brief date is a Jakarta calendar date shown with `parseLocalDate` (no conversion). No `UTC`/`WIB` literal in Exec views; the only fixed zone text is "06:00 Jakarta time".
- Page title: the nested `app/(app)/exec/layout.tsx` exports `metadata.title = { default: "Exec", template: "%s · " + PLATFORM_NAME }` (a bare string would reset the root template); `page.tsx` sets `document.title` per view with the restore-on-unmount pattern of `components/entities/entity-view.tsx`.
- Every pre-redesign feature F1-F24 stays reachable; keep a checklist in the PR (Task 20). No web test runner; do not add one. Web verification per task, from `apps/web` after `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"`: `pnpm lint`, `pnpm exec next typegen && pnpm exec tsc --noEmit`, `pnpm build`, all exit 0, plus the task's checklist in `pnpm dev`.
- No subagent re-delegation inside a task. Do not push.

## Review Focus

1. The hourly task never makes a second LLM call for a date: a present row skips before the lock, a held lock skips, and a manual row inserted between the re-check and the insert survives (Task 5, `test_present_row_makes_no_llm_call`, `test_lock_held_skips`, `test_manual_row_between_recheck_and_insert_survives`).
2. "Today" is one date everywhere: `brief_today` at 16:59 and 17:00 UTC with offset 7 and 0, and the read endpoint's `today` equals the worker's (Task 3, `test_brief_today_*`; Task 4, `test_today_matches_brief_today`).
3. One brief serves every client and generation never touches client data: `X-Client-ID` A and B read identical briefs and dates, and the client-scoped sections are not computed for `role="exec"` (Task 4, `test_two_clients_read_identical_brief`; Task 3, `test_brief_skips_analyst_and_client_sections`).
4. A failed manual or scheduled generation leaves the stored row untouched and writes nothing (Task 4, `test_post_llm_failure_502_keeps_row`; Task 5, `test_failure_writes_no_row_and_next_run_retries`), and a leaderboard actor outside the velocity top 10 still gets its real velocity (Task 1, `test_leaderboard_velocity_for_actor_outside_velocity_top10`).
5. The client parser never loses text: a reply without the five headings falls back to the Markdown, `**Title.**` bullets and plain bullets both split, and the dialog always shows the full Markdown (Task 12 checklist against three stored briefs).

---

### Task 1: Dashboard fields B1-B3 (4.1, 4.2, 4.3)

**Files:**
- Modify: `apps/api/src/cti_api/services/exec_dashboard.py` (`get_exec_dashboard_v2`, `_compute_ta_velocity`), `packages/cti-core/src/cti_core/db/repositories/dashboard.py` (`AsyncDashboardRepo`)
- Test: `tests/integration/test_exec_dashboard_service.py`

**Interfaces:**
- Produces: `dashboard-v2` keys `monthly_totals: list[int]` (aligned with `months`), `ta_leaderboard[*].{velocity_pct: int | None, last_month: int | None, avg_prev: float | None, top_sectors: list[str]}`, `sector_risk_scores[*].top_actor: str | None`.
- Produces: `_velocity_rows(ta_monthly_raw, months, usable) -> dict[str, dict[str, Any]]` (today's per-actor math for every actor; `_compute_ta_velocity` sorts and cuts its output, unchanged); `AsyncDashboardRepo.top_sectors_by_actor(*, actors, limit=2, exclude=(UNSPECIFIED_INDUSTRY,), **filters) -> dict[str, list[str]]` and `AsyncDashboardRepo.top_actor_by_sector(*, sectors, **filters) -> dict[str, str]`, both one grouped query built like `sector_actor_counts` (`mention_rows(SECTOR)` joined to `mention_rows(ACTOR)`, `_apply_article_filters`) with `row_number() OVER (PARTITION BY ... ORDER BY count DESC, name)`.

- [ ] **Step 1: Write failing tests** in `test_exec_dashboard_service.py` (seed with `_seed_incident_article`): `test_monthly_totals_align_with_months` (length equals `len(months)`, sum equals `total_incidents` for the window), `test_leaderboard_velocity_for_actor_outside_velocity_top10` (twelve actors with rising counts push a declining leaderboard actor out of the velocity top 10; its row still has a negative `velocity_pct`, an actor without usable history gets `None` for the three fields), `test_leaderboard_top_sectors` (order by count then name, limit 2, "General" excluded), `test_sector_risk_top_actor` (highest count wins, tie by name, `None` for a sector with no actor mention).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_exec_dashboard_service.py -q -k "monthly_totals or velocity_for_actor or top_sectors or top_actor"` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces and spec 4.1-4.3: `monthly_totals = [month_totals.get(m, 0) for m in months]`; split `_compute_ta_velocity` on top of `_velocity_rows` with identical output; the leaderboard rows (built in `get_exec_dashboard`) are enriched in `get_exec_dashboard_v2` by name lookup; `top_actor` merged into `sector_risk_scores` after `_compute_sector_risk_scores`. No new query for B1; two bounded queries for B2/B3 (≤ 10 actors, ≤ 8 sectors). Indonesian docstring on why velocity is computed for all actors.
- [ ] **Step 4: Run** the Step 2 command plus `uv run pytest tests/integration/test_exec_dashboard_service.py tests/integration/test_exec_cve_kpis.py -q` — Expected: PASS (existing velocity/leaderboard tests unchanged).
- [ ] **Step 5: Commit** `feat(api): monthly totals, leaderboard velocity and top sectors, top actor per sector on the exec dashboard`

### Task 2: `exec_briefs` model, migration and repository (4.5, P1)

**Files:**
- Create: `packages/cti-core/src/cti_core/db/models/exec_brief.py`, `packages/cti-core/src/cti_core/db/repositories/exec_brief.py`, `alembic/versions/c4e8a1f2b9d6_exec_briefs.py`, `tests/integration/test_exec_brief_repo.py`
- Modify: `packages/cti-core/src/cti_core/db/models/__init__.py` (export `ExecBrief`)

**Interfaces:**
- Produces: `ExecBrief` (columns, unique `uq_exec_briefs_brief_date`, no `client_id`, no other index; Indonesian docstring on the daily document and 30-day retention); `AsyncExecBriefRepo(session)` with `get(brief_date) -> ExecBrief | None`, `latest(*, since: date) -> ExecBrief | None`, `list_dates(*, since: date) -> list[date]` (newest first), `upsert(*, brief_date, markdown, filters, generated_by, model, prompt_version, replace: bool) -> ExecBrief | None` (`postgresql.insert(...).returning(ExecBrief)`; `replace` → `on_conflict_do_update(constraint="uq_exec_briefs_brief_date", set_={..., "generated_at": func.now()})`, else `on_conflict_do_nothing()` returning `None` when a row existed), `purge_before(cutoff: date) -> int`.

- [ ] **Step 1: Write failing tests** `tests/integration/test_exec_brief_repo.py`: insert returns the row; `test_upsert_without_replace_keeps_first_and_returns_none`; `test_upsert_replace_overwrites_and_refreshes_generated_at`; `test_latest_and_list_dates_window` (`since` boundary inclusive, newest first); `test_purge_before_boundary` (rows at -31, -30, 0 with cutoff -30 removes only -31); `test_unique_brief_date`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_exec_brief_repo.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the model, the repo (strict typing: `Mapped[...]`, `dict[str, Any]` filters) and the hand-written migration (`op.create_table("exec_briefs", ...)` with `op.f("pk_exec_briefs")`, named unique constraint, `server_default=sa.text("now()")`, `downgrade()` drops the table), column for column as the model.
- [ ] **Step 4: Run** the Step 2 command, `uv run pytest tests/integration/test_migrations_match_models.py -q` and `uv run mypy packages/cti-core/src packages/cti-scraper/src` — Expected: PASS. Then on the isolated database: `alembic upgrade head` prints `c4e8a1f2b9d6`, `alembic downgrade -1` and `upgrade head` again succeed, `alembic heads` prints one head.
- [ ] **Step 5: Commit** `feat(core): exec_briefs table and repository for the daily executive brief`

### Task 3: Brief scope B5 and the generation service (4.4)

**Files:**
- Modify: `apps/api/src/cti_api/services/exec_brief.py`
- Create: `tests/unit/test_exec_brief_dates.py`
- Test: `tests/integration/test_exec_brief_api.py` (first test only here), keep `tests/unit/test_prompt_correctness.py::test_exec_brief_*`, `tests/unit/test_llm_call_sites.py` green

**Interfaces:**
- Produces in `services/exec_brief.py`: `BRIEF_ROLE = "exec"`, `RETENTION_DAYS = 30`; `@dataclass(frozen=True) BriefFilters(days: int, incident_only: bool, confirmed_only: bool)` with `as_json() -> dict[str, object]`; `DEFAULT_FILTERS = BriefFilters(90, True, False)`; `brief_today(now: datetime.datetime | None = None) -> datetime.date` (UTC now + `get_settings().worker.report_utc_offset_hours`); `class BriefGenerationError(Exception)` carrying `error_type: str`; `@dataclass BriefDraft(markdown: str, model: str, prompt_version: str)`; `_call_llm(user_msg) -> tuple[str, str]` (task name `exec_brief` unchanged); `async draft_brief(session, *, filters: BriefFilters) -> BriefDraft` (dashboard with `role=BRIEF_ROLE`, LLM in `asyncio.to_thread`; any LLM exception or stripped-empty answer → `BriefGenerationError(type(exc).__name__ | "empty")`, DB errors propagate); `async store_brief(session, *, brief_date, draft, filters, generated_by, replace) -> ExecBrief | None` (wraps `AsyncExecBriefRepo.upsert`).
- Removes (in Task 4): `generate_exec_brief` (its only caller is the router). `SYSTEM_PROMPT`, `_build_user_message`, `_PROMPT_VERSION` unchanged.

- [ ] **Step 1: Write failing tests.** Unit `test_exec_brief_dates.py`: `test_brief_today_before_boundary` (16:59 UTC, offset 7 → same UTC date), `test_brief_today_at_boundary` (17:00 UTC → next date), `test_brief_today_offset_zero` (monkeypatch settings, clear `get_settings` cache), `test_default_filters_json`. Integration (`test_exec_brief_api.py`, name fixed by spec): `test_brief_skips_analyst_and_client_sections` (monkeypatch `exec_dashboard._get_recent_clusters`, `_get_pending_fp_queue`, `_get_critical_cves` and `_get_source_reliability_spread` to raise, stub `_call_llm`; `draft_brief` succeeds), `test_draft_empty_answer_raises`, `test_draft_llm_error_raises_generation_error`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_exec_brief_dates.py tests/integration/test_exec_brief_api.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces. Indonesian docstring: why the role is `exec` (C5: the brief must not depend on the caller or client), why `brief_today` lives here (API and worker agree on the Jakarta date), and that `_call_llm` returns the model for `exec_briefs.model`.
- [ ] **Step 4: Run** the Step 2 command plus `uv run pytest tests/unit/test_prompt_correctness.py tests/unit/test_llm_call_sites.py -q` — Expected: PASS. `generate_exec_brief` stays in this task as a thin wrapper (`draft_brief` + markdown only) so the router keeps importing; Task 4 deletes it together with its only caller.
- [ ] **Step 5: Commit** `feat(api): shared executive brief drafting without analyst or client sections`

### Task 4: Brief endpoints (4.6, P5, P6)

**Files:**
- Create: `apps/api/src/cti_api/schemas/exec_brief.py`
- Modify: `apps/api/src/cti_api/routers/exec_dashboard.py`, `tests/integration/test_exec_dashboard_router_snapshot.py` (the `POST /brief` test mocks `_call_llm` as a string today: return `("...", "model")`, assert the new shape; snapshot refresh waits for Task 7)
- Test: `tests/integration/test_exec_brief_api.py`, `tests/integration/test_api_permissions.py`

**Interfaces:**
- Produces schemas: `ExecBriefFilters {days, incident_only, confirmed_only}`; `ExecBriefOut {brief_date, markdown, filters, is_default_filters, generated_at, generated_by, model, prompt_version}`; `ExecBriefRead {today: date, brief: ExecBriefOut | None}`; `ExecBriefDates {today, dates: list[date]}`.
- Produces: `GET /api/exec/brief?date=` (today's row, else `latest(since=today-30)`, else null; with `date` only that row; no client, no audit), `GET /api/exec/brief/dates` (`list_dates(since=today-30)`), `POST /api/exec/brief` (`manage_intel`, `days: int = Query(90, ge=7, le=365)`, `incident_only: bool = True`, `confirmed_only: bool = False`): `draft_brief` then `store_brief(brief_date=brief_today(), replace=True, generated_by=user["username"])`, audit `generate_exec_brief` with `{days, incident_only, confirmed_only, brief_date}` + `ip_address`, `commit()`; `BriefGenerationError` → 502 `{"detail": "Brief generation failed. Try again later."}`; `is_default_filters = filters == DEFAULT_FILTERS`. None of the three calls `effective_client_id`.

- [ ] **Step 1: Write failing tests** in `test_exec_brief_api.py` (stub `_call_llm`): `test_get_today`, `test_get_falls_back_to_latest_within_30_days`, `test_get_null_when_none`, `test_get_explicit_date`, `test_two_clients_read_identical_brief` (headers `X-Client-ID` A and B on `/brief` and `/brief/dates`), `test_today_matches_brief_today`, `test_dates_order_and_window` (-31 excluded), `test_post_replaces_scheduler_row_and_sets_generated_by`, `test_post_non_default_filters_flagged`, `test_post_days_bounds` (6 and 366 → 422), `test_post_llm_failure_502_keeps_row`, `test_post_writes_audit`, `test_post_ignores_x_client_id`. `test_api_permissions.py`: keep `("POST", "/api/exec/brief")` in the 403 list and add `("GET", "/api/exec/brief")`, `("GET", "/api/exec/brief/dates")` to `test_analyst_keeps_reading_and_cve_triage` (not 403).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_exec_brief_api.py tests/integration/test_api_permissions.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; delete the Task 3 `generate_exec_brief` wrapper; Indonesian docstring that the response shape changed from `{brief, generated_at}` and why (web is the only consumer, same PR).
- [ ] **Step 4: Run** the Step 2 command and `uv run pytest tests/unit -q -k "exec or llm_call_sites"` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): stored shared executive brief endpoints`

### Task 5: Hourly daily-brief task and schedule (4.7, P2, P3, P3a)

**Files:**
- Modify: `apps/api/src/cti_api/services/exec_brief.py` (`generate_scheduled_brief`), `apps/worker/src/cti_worker/tasks/periodic.py` (new section "Executive brief harian"), `apps/worker/src/cti_worker/beat.py` (`_brief_hours`, `_periodic_schedule`)
- Create: `tests/integration/test_exec_brief_schedule.py`
- Test: `tests/unit/test_beat_schedule.py`

**Interfaces:**
- Produces: `generate_scheduled_brief(session, now) -> str` in `services/exec_brief.py` returning `"present" | "stored" | "raced"`; it re-reads `get(brief_today(now))` and only when missing calls `draft_brief(filters=DEFAULT_FILTERS)` and `store_brief(..., generated_by="scheduler", replace=False)`, then commits; `BriefGenerationError` propagates to the task.
- Produces: `_brief_hours(offset: int) -> str` (`",".join(str(h) for h in sorted({(h - offset) % 24 for h in range(6, 19)}))`, `0,1,...,11,23` at offset 7); beat entry `"exec-brief-daily": {"task": "exec.brief_daily", "schedule": crontab(minute=0, hour=_brief_hours(offset)), "options": {"queue": QUEUE_MAINTENANCE, "expires": 55 * 60}}`.
- Produces: `@app.task(bind=True, name="exec.brief_daily", queue=QUEUE_MAINTENANCE)` `exec_brief_daily`: (1) `_run_async` cheap `get(brief_today())`, a row → `{"status": "present"}` without lock or LLM; (2) `_brief_lock(brief_date)` (`BeatLock`, key `exec_brief:{date}`, TTL 15 min, built like `_sweep_lock`), not acquired → `{"status": "skipped_running"}`; (3) under the lock `generate_scheduled_brief`; (4) `BriefGenerationError` → log `exec_brief_daily_failed` (`brief_date`, `error_type`, local hour), `{"status": "failed"}`, no Celery retry; lock released in `finally`.

- [ ] **Step 1: Write failing tests.** Unit `tests/unit/test_beat_schedule.py::test_exec_brief_entries`: `exec-brief-daily` at minute 0, hours `0-11,23` with offset 7 and `6-18` with offset 0 (monkeypatch `worker.report_utc_offset_hours`), `expires == 3300`, queue `maintenance`. Integration `test_exec_brief_schedule.py` (Redis `redis_client` fixture, LLM stubbed with a call counter, call the task through its `.run()` as `tests/unit/test_recap_task.py` does): `test_missing_stores_scheduler_row_with_default_filters`, `test_present_row_makes_no_llm_call` (scheduler and manual row, lock never taken), `test_lock_held_skips`, `test_failure_writes_no_row_and_next_run_retries`, `test_empty_answer_is_failure`, `test_manual_row_between_recheck_and_insert_survives` (stub `draft_brief` to insert a manual row before returning; the manual row is kept, task returns `raced`/`stored` without error).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_beat_schedule.py tests/integration/test_exec_brief_schedule.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; docstring covers the three no-double-call layers (lock, re-check, `ON CONFLICT DO NOTHING`), why `expires` < the Redis `visibility_timeout` and why `enrich_jobs`/the breaker are not used (spec 4.7).
- [ ] **Step 4: Run** the Step 2 command plus `uv run pytest tests/unit/test_beat_liveness.py -q` — Expected: PASS. Check by hand that `celery -A cti_worker.celery_app inspect registered` code path imports (`uv run python -c "import cti_worker.tasks.periodic"`).
- [ ] **Step 5: Commit** `feat(worker): hourly catch-up task that stores the daily executive brief`

### Task 6: 30-day retention purge (4.8, P4)

**Files:**
- Modify: `apps/api/src/cti_api/services/exec_brief.py` (`purge_old_briefs`), `apps/worker/src/cti_worker/tasks/periodic.py`, `apps/worker/src/cti_worker/beat.py`
- Test: `tests/integration/test_exec_brief_schedule.py`, `tests/unit/test_beat_schedule.py`

**Interfaces:**
- Produces: `purge_old_briefs(session, now) -> int` (`purge_before(brief_today(now) - timedelta(days=RETENTION_DAYS))`, logs `exec_briefs_purged`); task `exec.purge_briefs` (queue `maintenance`); beat entry `"exec-brief-purge": {"task": "exec.purge_briefs", "schedule": crontab(hour=3, minute=45), "options": {"queue": QUEUE_MAINTENANCE}}` (between `llm.purge_calls` 03:40 and `story.purge_empty` 03:50).

- [ ] **Step 1: Write failing tests:** `test_purge_keeps_30_days` (rows at -31, -30, 0 relative to `brief_today`: only -31 removed, count 1); extend `test_exec_brief_entries` with the purge entry (03:45 UTC, `maintenance`).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_beat_schedule.py tests/integration/test_exec_brief_schedule.py -q -k "purge or entries"` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the Step 2 command, then `uv run pytest tests/integration -k "exec or migrations_match or api_permissions" -q` (Docker) — Expected: PASS.
- [ ] **Step 5: Commit** `feat(worker): purge executive briefs older than 30 days`

### Task 7: API contract, loose types and snapshot

**Files:**
- Modify: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts` (generated), `apps/web/src/lib/api/loose-types.ts`, `tests/integration/__snapshots__/test_exec_dashboard_router_snapshot.ambr`

**Interfaces:**
- Produces for the web: `components["schemas"]` gains `ExecBriefFilters`, `ExecBriefOut`, `ExecBriefRead`, `ExecBriefDates`; new paths `/api/exec/brief` (GET, POST) and `/api/exec/brief/dates`.
- Produces in `loose-types.ts`: `ExecDashboardV2.monthly_totals: number[]`; `ta_leaderboard` row type `{ name; count; velocity_pct: number | null; last_month: number | null; avg_prev: number | null; top_sectors: string[] }`; `sector_risk_scores[*].top_actor: string | null`; `ExecBriefResponse` deleted.

- [ ] **Step 1: Regenerate** `uv run python tools/export_openapi.py`, then `cd apps/web && pnpm run gen:api`. Expected: `git diff --stat` shows only those two generated files.
- [ ] **Step 2: Update `loose-types.ts`** per Interfaces (Indonesian comment naming the serialiser each shape comes from: `get_exec_dashboard_v2`).
- [ ] **Step 3: Snapshot.** `uv run pytest tests/integration/test_exec_dashboard_router_snapshot.py -q`; read the diff (only `monthly_totals`, the leaderboard velocity/top-sector fields, `top_actor`), then rerun with `--snapshot-update`.
- [ ] **Step 4: Verify:** ruff check + format check; mypy; fast suite; `uv run pytest tests/integration -k "exec or migrations_match or api_permissions" -q`; web `pnpm exec next typegen && pnpm exec tsc --noEmit` (expected errors only in `app/(app)/exec/page.tsx` for `ExecBriefResponse`; fixed by Task 9, so run `tsc` here only to confirm no other file breaks).
- [ ] **Step 5: Commit** `chore(api): regenerate the API contract for the Exec data and brief endpoints`

### Task 8: Primitives (6.6 #1, #2, #5)

**Files:**
- Create: `apps/web/src/components/ui/sparkline.tsx`, `apps/web/src/components/ui/share-bar.tsx`, `apps/web/src/components/exec/show-all.tsx`
- Modify: `apps/web/src/components/dashboard/stat-box.tsx` (import `Sparkline`), `apps/web/src/components/ui/stat-tile.tsx` (optional `spark?: number[]`)

**Interfaces (Produces):**
- `Sparkline({ data: number[]; className?: string; "aria-hidden"?: boolean })` moved verbatim from `stat-box.tsx` (tone via `currentColor` and a token class, default `text-info`); `StatBox` output unchanged.
- `ShareBar({ items: { label: string; value: number }[]; "aria-label"?: string })`: one 100 % stacked bar, segment colours from the chart-series tokens used by `components/dashboard/charts.tsx`, `role="img"` with an `aria-label` listing "{label} {pct}%"; the caller renders the legend.
- `ShowAll({ total: number; shown: number; expanded: boolean; onToggle: () => void })`: text button "Show all ({total})" / "Show fewer", `aria-expanded`, hidden when `total <= shown` and collapsed.
- `StatTile` renders `Sparkline` bottom-right when `spark` has ≥ 2 points.

- [ ] **Checklist:** Dashboard `StatBox` sparkline looks identical; `ShareBar` has no raw colours and reads in dark mode; `ShowAll` toggles with Enter/Space and announces `aria-expanded`.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): sparkline, share bar and show-all primitives for Exec`

### Task 9: Shell, toolbar, view switch, watchlist and CSV (6.0, D1, D10, D13)

**Files:**
- Create: `apps/web/src/components/exec/exec-page-header.tsx`, `apps/web/src/components/exec/exec-footnote.tsx`, `apps/web/src/lib/exec/query.ts`
- Modify: `apps/web/src/app/(app)/exec/layout.tsx` (metadata only), `apps/web/src/app/(app)/exec/page.tsx` (rewritten shell), `apps/web/src/components/exec/exec-filter-bar.tsx` (rebuilt), `apps/web/src/lib/exec/filters.ts`, `apps/web/src/lib/exec/format.ts` (`buildExecCsv`)

**Interfaces:**
- Produces in `filters.ts`: `ExecView = "briefing" | "board"`; `saveExecWatchlist(filters, view)` stores `view` too; `restoreExecWatchlist()` returns `{days, incidentOnly, confirmedOnly, view?}`; keys unchanged (`cti_exec_idea_watchlist_v1`, `exec_role_preview`); `EXEC_DAY_OPTIONS` becomes `[7, 30, 90, 180, 365]` (unchanged); `execCountNoun(f)` ("threat news articles" | "articles" | "confirmed incidents").
- Produces: `ExecPageHeader({ days; today; data; updatedAt; view; onViewChange })` (kicker "EXECUTIVE", title "Threat posture, last {days} days", the description line of spec 6.0, `SegmentedControl` "Exec view"); `ExecFilterBar` props `{ filters; onChange; isAdmin; viewRole; watchlistSaved; onToggleWatchlist; onExportCsv?; onGenerateBrief?; generating }` (period `SegmentedControl` "Period", two `Checkbox`es, admin-only role-preview `Select` with `items` and "None" sentinel, "Previewing {role}" chip, `StarToggle`-style "Save watchlist", "Export CSV" only when `onExportCsv` is passed, "✦ Generate brief" only when `onGenerateBrief` is passed); `ExecFootnote({ filters })` with the three variants of spec 6.0; `isClientError(e)` helper in `lib/exec/query.ts`.
- `page.tsx`: `useSearchParams` for `?view=` (invalid → `briefing`, `router.replace` on change, explicit `?view=` wins over the saved view), one `useQuery(["exec","dashboard-v2",days,incidentOnly,confirmedOnly,rolePreview])` shared by both views (no retry on 4xx), `useCan()` for `export_data` and `manage_intel`, `document.title` per view ("Exec briefing" / "Analyst board", restore-on-unmount), `StatePanel` loading (skeleton tiles), error with Retry, no access. The views are `BriefingView` (Task 10) and `BoardView` (Task 14); until each exists this task keeps rendering the current sections for that view so the page keeps working, and Tasks 10 and 14 swap them in.
- `buildExecCsv` gains `monthly_totals`, leaderboard `velocity_pct` and `top_sectors`, sector `top_actor` (cells through `lib/csv.ts::csvCell`).

- [ ] **Checklist:** `/exec` and `/exec?view=board` both load; invalid `?view=x` falls back; switching views does not refetch (network tab); the browser tab reads "Exec briefing · Vareon Intelligence" (template kept) and returns to "Exec" on leaving; period/checkbox change updates the header line; the role-preview select appears for admin only and a non-admin browser with a stale stored preview sends no `role`; Save watchlist is `aria-pressed`, restores days, flags and view on reload; Export CSV hidden for a user without `export_data` and the file contains the new columns; footnote text switches with the two checkboxes; keyboard: every toolbar control reachable.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): exec page shell with view switch, rebuilt toolbar and watchlist view`

### Task 10: Briefing, spikes hero and KPI row (6.1, C8, C13, D14)

**Files:**
- Create: `apps/web/src/components/exec/briefing-view.tsx`, `apps/web/src/components/exec/sector-spikes-hero.tsx`, `apps/web/src/components/exec/exec-kpi-row.tsx`
- Modify: `apps/web/src/lib/exec/format.ts` (`execDelta(current, prev, mode)` percent/absolute with red up, green down)
- Delete (after `grep -rn "kpi-strip\|SpikeBanner" apps/web/src` shows no user): `kpi-strip.tsx`; `SpikeBanner` in `tier2-panels.tsx`

**Interfaces:**
- Produces: `BriefingView({ d: ExecDashboardV2; filters: ExecFilters; brief: ReactNode })` (lead row `lg:grid-cols-[2fr_1fr]`, KPI row, then the Task 11 rows); `SectorSpikesHero({ d })` (`HeroPanel`, one row per sector with highest z, `MeterBar variant="baseline"` with white tick, `Chip` hero-safe tokens, link "Open Early warning →" to `/intelligence/early-warning` via `heroLinkClass`, empty line); `ExecKpiRow({ d, filters, tiles: "briefing" | "board" })` (eight tiles with the verbatim labels and subs of 6.1; the four board tiles of 6.2 with `spark={d.monthly_totals}`; "no prior-period data" when `prev_period_reliable` is false; CONFIRMED RATE "—" / "no verified articles yet").

- [ ] **Checklist:** hero rows legible light and dark (name, chip, caption, tick); one row per sector even when a sector has two spike days (highest z kept, date shown); empty hero shows "No sector above baseline in the last 7 days"; deltas red when up and green when down, percent on the article tile and absolute on sectors/actors; tile labels change with Threat news only / Confirmed only; no `UTC`/`WIB` text.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): exec briefing lead row with sector spikes hero and KPI tiles`

### Task 11: Briefing tables and lists (6.1, D7, D9, D12, D16, C15)

**Files:**
- Create: `apps/web/src/components/exec/sector-risk-card.tsx`, `threat-actors-card.tsx`, `cve-exposure-card.tsx`, `top-techniques-card.tsx`
- Modify: `apps/web/src/lib/exec/format.ts` (`RISK_FORMULA_TITLE` moved here, `SECTOR_ABBR`)
- Delete (after grep): `sector-risk.tsx`, `ta-leaderboard.tsx`, `cve-exposure-table.tsx`, `TtpList` in `tier2-panels.tsx`

**Interfaces:**
- Consumes: Task 1 fields (`top_actor`, `top_sectors`, `velocity_pct`), `Sparkline`, `MeterBar`, `ShowAll`, `Chip kind="risk"`, `EntityChip`/entity link helper, `newsroomHref` (`lib/newsroom/links.ts`), `cvssColorClass`, `riskTier`, `sectorPeerBenchmark`.
- Produces: four cards in the two Briefing rows of 6.1. Sector risk: `<table className="table-fixed">` with explicit column widths (sector, risk, articles, trend, share, top TA), all returned rows, "How is risk scored?" `Tooltip`, footnote from `months` with the volume-only sentence. Threat actors: 5 + `ShowAll` (10); "NEW" chip only when `prev_period_reliable` and not in `prev_ta_names`; "most seen in" hidden when empty; count is a sibling link to `newsroomHref({ actor, from })` with the `aria-label` of 6.1 (the row itself is not clickable); velocity red only above +20 (`text-destructive-text`), "—" when null; row `title` "Signal quality {ta_confidence}%". CVE exposure 6 + `ShowAll` (10); Top techniques 6 + `ShowAll` (15).

- [ ] **Checklist:** no interactive element nested in a link or row; table columns do not collapse (explicit widths); NEW chip absent when the previous period is unreliable; velocity 15 % stays neutral and 40 % turns red; Show all expands to 10/10/15 and back; every entity name links to its page and every count to a Newsroom sheet whose number matches; empty copy per card; dark mode risk meters and chips legible.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): exec briefing sector risk, threat actors, CVE exposure and techniques cards`

### Task 12: Brief card, parser and date picker (6.3, P7, P8)

**Files:**
- Create: `apps/web/src/lib/exec/brief.ts`, `apps/web/src/components/exec/brief-card.tsx`, `apps/web/src/lib/exec/use-brief.ts`
- Modify: `apps/web/src/components/exec/briefing-view.tsx` (renders the card in the lead row)

**Interfaces:**
- Produces in `brief.ts`: `parseBrief(markdown: string): ParsedBrief | null` (pure; rules of 6.3: split on `^##\s+`, case-insensitive names, first sentence at the first `. `/`! `/`? ` followed by a capital letter or end, `**Title.**` or first sentence for findings, list markers `-`, `*`, `•`, `1.`, returns `null` without an "Executive Summary" section or with an empty headline), `ParsedBrief = { headline; paragraph; findings: { title; detail }[]; otherSections: string[] }`, `briefFiltersLabel(f: ExecBriefFilters): string` ("Last {days} days · threat news only · confirmed only").
- Produces in `use-brief.ts`: `useBrief(selectedDate: string | null)` (`["exec","brief", selectedDate ?? "default"]`), `useBriefDates()` (`["exec","brief-dates"]`), `useGenerateBrief()` (mutation: `api.POST("/api/exec/brief", { params: { query: { days, incident_only, confirmed_only } } })` with all three sent explicitly; invalidates both keys; 502 detail surfaced as `Error.message`); no retry on 4xx.
- Produces `BriefCard({ filters: ExecFilters; onOpenDialog: () => void; onGenerate: () => void; generating: boolean })` per 6.3: kicker "EXECUTIVE SUMMARY", `Select` "Brief date" (items from `dates`, "Today"/"Yesterday"/`fmtShortDate`), meta "AI brief · generated by {generated_by} · {time}" (`fmtTime` for today else `fmtDateTime`), the non-default filters line, the platform-wide note, headline, paragraph (`react-markdown` in `.prose`), first 3 findings numbered with "+{n} more in the full brief", "Also in the brief: …", "Read full brief →"; fallback of ~600 characters with a fade; states: skeleton, `Notice` "Today's brief is not ready yet. Showing {date}.", `StatePanel` empty ("No brief for this date yet", Generate for `manage_intel` today only, the past-date hint, the 06:00 Jakarta hint without permission), generating `Notice`, error `StatePanel` with Retry.

- [ ] **Checklist (QA against three stored briefs, no unit runner):** (1) normal five-section output; (2) bullets written as `**Title.** detail` and plain `- detail`; (3) a reply without any `##` heading falls back to rendered Markdown. Also: a brief whose Executive Summary has one sentence only (no paragraph) renders without an empty block; picking an older date refetches and hides Generate; a non-default-filter brief shows its filters line; time shows in the browser zone.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): stored executive brief card with parser and date picker`

### Task 13: Brief dialog and generate/replace flow (6.3, 6.4)

**Files:**
- Modify: `apps/web/src/components/exec/brief-modal.tsx` (rebuilt), `apps/web/src/app/(app)/exec/page.tsx`

**Interfaces:**
- Produces: `ExecBriefModal({ open; onOpenChange; brief: ExecBriefOut | null; canRegenerate: boolean; onRegenerate: () => void; regenerating: boolean })`: `DialogTitle` "Executive brief", `DialogDescription` meta of 6.3 (date with year, filters label, generated by, time), close "✕" (`aria-label` "Close"), body `react-markdown` in `.prose` with inner scroll, footer note "AI draft. Review before sharing.", "Download .md" (`Blob`, file `exec-brief-{brief_date}.md`), "Copy" (toast "Copied to clipboard"), "Regenerate" (only with `manage_intel` and `brief_date` equal to `today`).
- Page flow: toolbar "✦ Generate brief" posts the **page** filters; when today already has a brief, `ConfirmDialog` (title "Replace today's brief?", the body and "Generate brief" label of 6.3, `confirmLoading`); success toast "Brief generated" with action "Open"; failure toast with the 502 detail; Regenerate posts the **brief's stored** filters through the same confirm, keeps the dialog open and shows the new content; `selectedDate` resets to `today` after each success.

- [ ] **Checklist:** Generate with no brief today posts straight away; with a brief today the confirm shows generated-by and time; Cancel posts nothing; 502 keeps the old content and shows the toast; Regenerate hidden for a past date and for a user without `manage_intel`; Download file content equals the Markdown; Copy works; focus returns to the trigger on close; dialog readable light and dark; the board view shows the success toast with "Open".
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): rebuilt executive brief dialog with download, copy and confirmed regenerate`

### Task 14: Analyst board, KPIs, heatmap, news types and trends (6.2, D8, D11, C9)

**Files:**
- Create: `apps/web/src/components/exec/board-view.tsx`, `apps/web/src/lib/exec/heat.ts` (`heatInsight(d)`, `heatStep(count, max)`)
- Modify: `apps/web/src/components/exec/sector-heatmap.tsx` (rebuilt on `HeatGrid`/`HeatCell variant="scale"`, drill dialog restyled with "Open in Newsroom →"), `apps/web/src/components/exec/charts-section.tsx` (news types via `ShareBar` and `StackedBarChart`, sector and victim-country trend limited to the top 4)
- Delete (after grep): the doughnut in `charts-section.tsx`

**Interfaces:**
- Produces: `BoardView({ d; filters })` rendering `ExecKpiRow tiles="board"`, the heatmap card (all returned sectors, columns from `months`, a number in every non-empty cell, `useGridRovingKeys`, Enter/click opens the drill dialog, insight sentence only when a sector with ≥ 3 earlier months beats its own earlier maximum), the news-types card (top 5 + "Other" when > 6 types, legend "{type} {n} · {pct}%", kicker "MONTHLY, LAST {months.length} MONTHS"), Sector trend and Victim country trend (`MultiLineChart`, first 4 series); copy built from `months.length`, never "6 months".
- The drill dialog keeps the 20-article call (`GET /api/articles?industry=&posted_on_start=&posted_on_end=`) and adds the footer link `newsroomHref({ industry, from: month start })` with the hint text of 6.4.

- [ ] **Checklist:** heat steps legible in dark mode (lowest step visible against the card, top step readable); keyboard moves across cells and Enter opens the drill; drill title "{sector} · {month year}", article count, "Open in Newsroom →" lands on a sheet whose count matches; insight hidden when nothing qualifies; with 7 d the copy says "last 1 month"; full series still in the CSV.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): exec analyst board with KPI sparkline, sector heatmap, news types and trends`

### Task 15: Actor-sector dots, actor velocity and co-targeted sectors (6.2, C12, D9, C15)

**Files:**
- Create: `apps/web/src/components/exec/actor-sector-dots.tsx`, `apps/web/src/components/exec/actor-velocity-card.tsx`
- Modify: `apps/web/src/components/exec/board-view.tsx`, `apps/web/src/lib/exec/format.ts` (`SECTOR_ABBR` used here)
- Delete (after grep): `sector-actor-matrix.tsx`, `TaVelocity`/`SectorCooccurrence` in `tier2-panels.tsx` (delete `tier2-panels.tsx` when empty)

**Interfaces:**
- Produces: `ActorSectorDots({ matrix: ExecDashboardV2["sector_actor_matrix"] })` (transposed, all returned rows and columns, `<abbr title>` headers, diameter ∝ √(count/max), "·" for 0, `bg-destructive` when count ≥ `ceil(0.75 × max_val)` else `bg-foreground`, dot `title` "{actor} × {sector}: {n} articles", sr-only `<table>`, note with the computed threshold); `ActorVelocityCard({ d })` (7 + `ShowAll` (10); "{last_month} vs {avg_prev} avg"; "NEW" chip when `avg_prev` is 0; red only above +20; co-targeted sectors 3 + `ShowAll` (15)).

- [ ] **Checklist:** matrix with 8 × 8 returned data does not overflow at 1000 px (horizontal scroll inside the card only); threshold in the note equals the smallest red dot; the sr-only table lists every non-zero cell; dots visible against the card in dark mode; velocity colours follow C15; empty cards show their copy.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): exec actor-sector dot matrix and actor velocity card`

### Task 16: Queues row, IOC remove dialog extraction (6.2, F22, C10, C11)

**Files:**
- Create: `apps/web/src/components/intelligence/ioc/ioc-remove-dialog.tsx`
- Modify: `apps/web/src/components/intelligence/ioc/ioc-detail-body.tsx` (use the extracted dialog, behaviour unchanged), `apps/web/src/components/exec/role-gated-panels.tsx` (`FpQueue`, `CriticalCveFeed` restyled, `ClusterList` kept for Task 17), `apps/web/src/components/exec/board-view.tsx`

**Interfaces:**
- Produces: `IocRemoveDialog({ open; onOpenChange; ioc: { id: number; value: string }; onDone: (res: IocFeedbackResponse) => void })` (the `ConfirmDialog` with optional note, title "Remove {value} from feeds?", `POST /api/iocs/{ioc_id}/feedback` with `verdict: "fp"`, error inline); both the IOC detail body and the FP queue use it; the source-FP warning toast stays in the queue.
- Produces the queues row (rendered only when at least one card is visible): IOC false-positive queue (gate `view_config.sections.fp_feedback_queue`; chip "{pending_fp_total} pending"; rows with "confidence {confidence_score} · last seen {fmtCompactAge(last_seen)} ago"; "TP / restore" and "FP: remove" only with `useCan()("manage_ioc")`, read-only text otherwise; 5 + `ShowAll` (20); footer "Showing {n} of {pending_fp_total} pending" linking `/intelligence/iocs`) and Critical CVE feed (gate `critical_cve_feed`; 5 + `ShowAll` (20); empty "No KEV CVE matches this client's tech stack"; "CVE Tracker →").

- [ ] **Checklist:** the 2b IOC detail panel and the entity Indicators tab still open the same Remove dialog with identical copy; FP: remove from the queue refreshes the dashboard query and shows the warning toast when the source warns; analyst without `manage_ioc` sees no buttons; role preview `soc`/`analyst` shows only the matching card; one visible card spans the row.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): exec queues row with shared IOC remove dialog and KEV feed`

### Task 17: More signals row (6.2, D6)

**Files:**
- Create: `apps/web/src/components/exec/more-signals.tsx`
- Modify: `apps/web/src/components/exec/role-gated-panels.tsx` (`ClusterList` restyled), `apps/web/src/components/exec/board-view.tsx`

**Interfaces:**
- Produces: `MoreSignals({ d })` with an `<h2>` "More signals" and a `lg:grid-cols-3` row of: Campaign clusters (`cluster_list`; title link to `/intelligence/campaign-clusters?id={cluster_id}`, size, actor chips, `fmtCompactAge(last_seen)`), Source reliability spread (`source_reliability_spread`; `GradedDoughnutChart` as today), Country trend (all roles; `MultiLineChart` of `country_trend`, every returned series). Rendered only when at least one card is visible.

- [ ] **Checklist:** analyst/admin see all three, exec sees Country trend only; cluster links open the matching campaign; doughnut legible in dark mode; the row collapses to one column below 1024 px.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): exec more-signals row for campaign clusters, source reliability and country trend`

### Task 18: States and permission sweep (6.5, C6, C11)

**Files:**
- Modify: any Exec file from Tasks 9-17 that the greps below flag

- [ ] **Sweep:** `grep -rn "Loading\.\.\.\|Loading…" apps/web/src/components/exec "apps/web/src/app/(app)/exec"` → `StatePanel variant="loading"` or card skeletons; `grep -rn "WIB\|UTC" apps/web/src/components/exec apps/web/src/lib/exec` → none (except the "06:00 Jakarta time" copy); every dialog (`brief-modal`, replace confirm, heat drill, IOC remove) has `DialogDescription`, close "✕", ghost Cancel and a `loading` primary; `grep -rn "asChild" apps/web/src/components/exec` → none; no `backdrop-blur`; the table columns of `table-fixed` tables have widths.
- [ ] **No-access and permissions:** page-level `StatePanel` for missing `view_intel`; Export CSV needs `export_data`; Generate/Regenerate/empty-state Generate need `manage_intel`; TP/FP need `manage_ioc`; role preview only for admin; each hidden control stays reachable for a user who has the permission (try `analyst`, `exec` preview, `admin`). `view_config.exec_brief_button` is not used (C6).
- [ ] **Retry:** a 403/404 on the brief queries shows the error panel once (no retry loop); a 500 retries at most twice.
- [ ] **F1-F24:** walk the inventory list and confirm each feature is reachable; note any re-homed one in the PR checklist.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `fix(web): consistent states, dialog anatomy and permission gates across Exec`

### Task 19: Docs, CHANGELOG and prod-upgrade notes (4.9)

**Files:**
- Modify: `CHANGELOG.md` (extend `## [0.8.16] - 2026-11-08`), `docs/prod-upgrade/0.8.16.md`, `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md`, `docs/ARCHITECTURE.md`, `docs/PROGRESS.md` (Indonesian work-log line)

- [ ] **CHANGELOG (Indonesian):** header paragraph: now two additive migrations (`b7d41e9a2c63`, `c4e8a1f2b9d6`), still no `.env` key. `### Ditambahkan` and `### Diubah` entries exactly as spec 4.9 (brief harian tersimpan satu untuk seluruh platform dan sama untuk semua klien, 06:00 WIB, dicoba lagi tiap jam sampai 18:00 WIB, disimpan 30 hari; `GET /api/exec/brief` dan `/dates`; `monthly_totals`, velocity dan dua sektor teratas per aktor, aktor teratas per sektor; halaman Exec jadi Briefing dan Analyst board `?view=`; `POST /api/exec/brief` kini `days` 7-365, tanpa bagian analis/klien, menggantikan brief bersama hari ini, mengembalikan `ExecBriefOut`, gagal LLM 502; Export CSV butuh `export_data`).
- [ ] **Prod upgrade (both files, English):** *Migrations* `c4e8a1f2b9d6` (`exec_briefs`) on top of `b7d41e9a2c63`, `alembic_version` after deploy; *Settings* none (uses `WORKER__REPORT_UTC_OFFSET_HOURS`, 7 on prod); *Beat restart* (two new entries load only when `beat` starts; `make deploy` recreates it; verify with `celery -A cti_worker.celery_app inspect registered` for `exec.brief_daily`, `exec.purge_briefs` and the beat log line for `exec-brief-daily`); *Daily LLM cost* (one `exec_brief` call per day for the platform, ~1.5-2.5 k tokens, up to 13 catch-up attempts a day during a gateway outage, plus manual generations; the `llm_calls` query of spec 4.9); *After deploy* (the `exec_briefs` check query, `/data-health` LLM task `exec_brief`, log `exec_brief_daily_failed`); *Rollback* (image rollback leaves the table unused; downgrading the migration drops stored briefs).
- [ ] **ARCHITECTURE.md (English):** two rows in the periodic-task table (`exec.brief_daily`, `exec.purge_briefs`) and one row in the table list (`exec_briefs`: writer `exec.brief_daily` and `POST /api/exec/brief`, reader Exec page).
- [ ] **Verify:** `uv run python -c "from cti_api.routers.changelog import _parse; print(_parse()[0]['version'])"` prints `0.8.16`; `uv run ruff format --check .`.
- [ ] Commit `docs(release): note the Exec redesign, the daily brief and its migration in 0.8.16`

### Task 20: Final verification (spec 8)

- [ ] **Backend:** `uv run pytest tests/integration -k "exec or migrations_match or api_permissions" -q` (Docker, `qacve`), then `uv run pytest tests/unit tests/contract packages` with the known deselects. Cross-cutting: two clients read the identical brief and dates; analyst reads (200) but cannot POST (403); the hourly task makes no LLM call for a date with a row or while the lock is held; `tests/unit/test_llm_call_sites.py` and `test_prompt_correctness.py` unchanged and green.
- [ ] **Static:** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src packages/cti-scraper/src`; re-run `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`, then `git diff --exit-code docs/openapi.json apps/web/src/lib/api/schema.d.ts`; `grep -n "^revision" uv.lock` prints `revision = 3`.
- [ ] **Migration:** fresh `alembic upgrade head` → `c4e8a1f2b9d6`; `alembic downgrade -1` and up again on the isolated database; `alembic heads` prints one head.
- [ ] **Web:** `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit`; `pnpm build`, all exit 0. Parser checked against three stored briefs (Task 12).
- [ ] **Visual (controller, local `qacve`, API via uvicorn, web via `pnpm dev`, synthetic data: two clients, briefs on several dates incl. a non-default-filter one and a gap, spikes, a full leaderboard, FP queue, KEV matches, campaigns; LLM stubbed):** run `exec.brief_daily` twice by hand (`celery call`): one row, the second run returns `present` and adds no `llm_calls` row. Screenshots of both views, the brief dialog, the replace confirm and the heat drill at 1440 and 1000 px, light and dark, against frames 40179/42159, 40692/42672, 35068/36123. Keyboard pass (view switch, period, checkboxes, date picker, heat grid, Show all, dialogs); contrast of hero rows, heat cells and dots in both themes; no `UTC` literal; every inventory F1-F24 reachable (checklist in the PR); every Newsroom link filters and its sheet count matches.
- [ ] **Delivery:** report results; commit per backend item and per view happened in earlier tasks; merge into `origin/Dev` under the standing approval. On dev 172.25.1.77 (read-only): `alembic_version`, beat log `exec-brief-daily`, the next morning's row; one manual Generate only with the user's go (one LLM call).
- [ ] No commit unless a fix was needed (then a `fix(...)` commit per fix).

## Spec coverage

| Spec section | Tasks |
|---|---|
| 2 S1-S3 | 9-18 (features kept), 19 |
| 2 D1, D2, D10, D13, D15 | 9 |
| 2 D5, D14 | 1, 10 |
| 2 D6 | 17 |
| 2 D7, D12, D16 | 11, 15, 16 |
| 2 D8, D9, D11 | 14, 15 |
| 2 P1 | 2 |
| 2 P2, P3, P3a | 5 |
| 2 P4 | 6 |
| 2 P5, P6 | 4 |
| 2 P7, P8 | 12, 13 |
| 3 C1-C3 | 9, 12, 13 |
| 3 C4, C5 | 3, 4, 5 |
| 3 C6, C11 | 9, 16, 18 |
| 3 C7, C8, C9 | 10, 12, 14 |
| 3 C10, C12, C13 | 15, 16, 10 |
| 3 C14, C15 | 9, 11, 15 |
| 4.1-4.3 | 1 |
| 4.4 | 3 |
| 4.5 | 2 |
| 4.6 | 4 |
| 4.7 | 5 |
| 4.8 | 6 |
| 4.9 | 19 |
| 5 | Global Constraints, 2, 7, 20 |
| 6.0 | 9 |
| 6.1 | 10, 11 |
| 6.2 | 14, 15, 16, 17 |
| 6.3 | 12, 13 |
| 6.4 | 13, 14, 16 |
| 6.5 | 9, 18 |
| 6.6 | 8, 10, 11, 12, 15 |
| 7 | Global Constraints (excluded items not planned) |
| 8 | 7, 20 |
| 9 | Review Focus, 5 (lock, expiry), 12 (parser), 18 |
