# P7g Persist-First Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the LLM off the critical path of article enrichment: articles whose relevance is known
are stored and alerted at once, LLM work (classify for uncertain titles, TTP extraction) runs as
durable `enrich_jobs` that drain automatically behind a circuit breaker.

**Architecture:** `run_pipeline` is split into `prepare` (no LLM) and `complete` (deterministic tail +
persist + alert). `enrich.article` never calls the LLM; it either completes or writes a `classify` job.
`cti_enrich.jobs.run_job` executes one job (LLM outside any transaction); the worker task `enrich.llm`
wraps it. `enrich.llm_dispatch` (every minute) sends due jobs according to a stateless breaker
computed from `llm_calls`.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (sync psycopg in worker, asyncpg in API), Alembic, Celery,
FastAPI, Next.js 16 + TanStack Query, pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-11-02-p7g-persist-first-design.md` (read it first; section
numbers below refer to it).

## Global Constraints

- Release: part of 0.8.11, **no version bump**; add to the existing `## [0.8.11]` CHANGELOG entry
  (Indonesian), `docs/prod-upgrade/0.8.11.md` and the 0.8.11 part of
  `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`.
- **No new `Settings` fields / `.env` keys.** Breaker and dispatch numbers are module constants.
- One migration, `down_revision = "1387fae00908"`; additive except the row move of spec 4.6.
- Constants: breaker opens at 3 consecutive failures; cooldown `min(30 min, 2 min * 2**(n-3))`;
  dispatch batch 20; lease 15 min; gateway backoff `min(60 min, 2**attempts min)`; JSON failures
  cap 3; `last_error` cut to 300 chars after `_scrub_secrets`.
- Breaker counts only `llm_calls.task in ("classify", "ttp")`; `error` and `empty` are failures.
- Late classify alerts only when `cti_core.enrich_replay.is_fresh(posted_on, now)` (move `is_fresh`
  and `ALERT_WINDOW` to `cti_core.llm.breaker` when `enrich_replay` is deleted).
- TTP writes go through P7c's `apply_ttps` / `ArticleRepo.touch_entity_seen`; `analyst` mentions are
  never replaced.
- Code comments/docstrings Indonesian, docs English, commit messages English conventional ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Fast suite: `uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro`.
  mypy strict only on `cti-core` and `cti-scraper`.
- After API changes: `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`
  (node via `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"`).
- Local Docker QA only on an isolated compose project (`POSTGRES_PORT=55433 REDIS_PORT=56379 docker
  compose -p qacve up -d postgres redis`), never `deploy-postgres-1`.

## Review Focus

1. The same URL arrives again (other feed, other title) while its `classify` job is pending: no
   second job, no LLM call, no article; `prepare` returns a duplicate outcome. Test in Task 3.
2. `enrich.llm` runs twice for the same job (dispatch lease expired, or dispatch + immediate send):
   exactly one article and one alert. Test in Task 4.
3. An analyst accepts/rejects a job while its LLM call is in flight, or deletes the article of a
   pending `ttp` job: whichever commits first wins, the other is a no-op without error. Tests in Task 4.
4. A migrated row (`input_text IS NULL`) whose URL already became an article (restored stub) or whose
   `posted_on` is old: job is deleted as duplicate / article stored without alert. Tests in Task 4.
5. Fresh install with no `llm_calls` rows, and a breaker that sees only analyst-triggered task
   failures (recap): breaker closed. Test in Task 2.

---

### Task 1: `enrich_jobs` model, migration and repository

**Files:**
- Create: `packages/cti-core/src/cti_core/db/models/enrich_job.py`, `packages/cti-core/src/cti_core/db/repositories/enrich_job.py`, `alembic/versions/<rev>_enrich_jobs.py`
- Modify: `packages/cti-core/src/cti_core/db/models/__init__.py`, `packages/cti-core/src/cti_core/db/models/article.py` (column `llm_ttp_status`)
- Test: `tests/integration/test_enrich_jobs_repo.py`, `tests/integration/test_enrich_jobs_migration.py`

**Interfaces:**
- Produces: model `EnrichJob` (columns exactly as spec 4.1; `JOB_KINDS = ("classify", "ttp")`,
  `JOB_STATES = ("pending", "failed")`, `LLM_TTP_STATUSES = ("pending", "done", "skipped", "failed")`
  in `cti_core.db.models.enrich_job`).
- Produces `EnrichJobRepo(session)` (sync):
  - `create(*, kind, url, title, source, scraper_id, posted_on, input_text, context, article_id=None, state="pending", last_error=None) -> EnrichJob | None` (`INSERT ... ON CONFLICT (kind, url_hash) DO NOTHING`, `None` on conflict)
  - `has_classify(url_hash: str) -> bool`
  - `get_for_update(job_id: int) -> EnrichJob | None` (`FOR UPDATE SKIP LOCKED`)
  - `claim_due(now, *, limit: int, lease: timedelta) -> list[EnrichJob]` (pending, due, `classify` before `ttp`, oldest `created_at` first, `FOR UPDATE SKIP LOCKED`, sets `next_attempt_at = now + lease`)
  - `record_gateway_failure(job, now, error: str) -> None`, `record_json_failure(job, now, error: str) -> bool` (True when it reached the cap and became `failed`), `mark_failed(job, error: str) -> None`, `delete(job) -> None`, `counts() -> JobCounts(pending_classify, pending_ttp, failed, oldest_pending_at)`
- Produces `AsyncEnrichJobRepo(session)`: `list(kind, state, search, page, page_size) -> tuple[list[EnrichJob], int]`, `get(job_id)`, `retry(job, now)` (state pending, `next_attempt_at=now`, `json_failures=0`), `counts()`.

- [ ] **Step 1: Write failing tests.** `test_create_is_unique_per_kind_and_url` (second `create` for the same url/kind returns `None`, a `ttp` job for the same url is allowed); `test_claim_due_orders_classify_first_and_sets_lease` (3 jobs, `limit=2` returns the two classify ones oldest first, `next_attempt_at == now + 15 min`, a second claim with the same `now` returns only the ttp one); `test_gateway_backoff` (attempts 0→1, `next_attempt_at == now + 2 min`; at attempts 7, `now + 60 min`); `test_json_cap` (third `record_json_failure` returns True and state `failed`); `test_job_deleted_with_article` (FK cascade). Migration test `test_migration_moves_failed_rows` (downgrade to `1387fae00908`, insert `rejected_articles` rows with `failure_kind` `transient`, `config`, `json`, `permanent` and one with `NULL`, upgrade: four `classify` jobs, the first three `pending`, `permanent` `failed` with `last_error` = old reason, `input_text IS NULL`, only the `NULL` row remains in `rejected_articles`).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_enrich_jobs_repo.py tests/integration/test_enrich_jobs_migration.py -q` — FAIL (import error).
- [ ] **Step 3: Implement** model, `articles.llm_ttp_status` (varchar(10) null + check), migration (create table + index `(state, kind, next_attempt_at)` + unique `(kind, url_hash)` + check constraints, add column, `INSERT INTO enrich_jobs ... SELECT ... FROM rejected_articles WHERE failure_kind IS NOT NULL`, then `DELETE`), repositories. Downgrade drops table and column only (moved rows are not restored; say so in its docstring).
- [ ] **Step 4: Run** the two files plus `tests/integration/test_migrations_match_models.py` — PASS.
- [ ] **Step 5: Commit** `feat(db): add enrich_jobs and articles.llm_ttp_status`.

### Task 2: Circuit breaker and dispatch plan (pure)

**Files:**
- Create: `packages/cti-core/src/cti_core/llm/breaker.py`
- Modify: `packages/cti-core/src/cti_core/db/repositories/llm_call.py` (add `recent_for_tasks`)
- Test: `tests/unit/test_llm_breaker.py`, `tests/integration/test_llm_calls_repo.py` (add one test)

**Interfaces:**
- Produces in `cti_core.llm.breaker`: `BREAKER_TASKS = ("classify", "ttp")`, `OPEN_AFTER = 3`,
  `BATCH = 20`, `LEASE = timedelta(minutes=15)`, `ALERT_WINDOW`, `is_fresh(posted_on, now) -> bool`
  (moved verbatim from `cti_core.enrich_replay`, which re-imports it until Task 5 deletes the module), `CallOutcome(status: str, at: datetime)`,
  `Breaker(state: Literal["closed", "open", "half_open"], failures: int, retry_at: datetime | None)`,
  `breaker_state(recent: Sequence[CallOutcome], now) -> Breaker` (`recent` newest first),
  `dispatch_limit(breaker: Breaker, *, queue_depth: int | None, max_depth: int) -> int`.
- Produces `LlmCallRepo.recent_for_tasks(tasks: Sequence[str], limit: int) -> list[CallOutcome]` and the async twin.

- [ ] **Step 1: Write failing tests** (unit): no calls → closed; `[ok]` → closed; `[error, error]` → closed; `[error]*3` with last at `now - 1 min` → open, `retry_at == last + 2 min`; `[error]*5` → cooldown 8 min; `[error]*12` → cooldown capped at 30 min; `[error]*3` with last at `now - 3 min` → half_open; `[empty, error, error]` counts as 3 failures; `dispatch_limit`: closed → `min(20, max_depth - depth)`, closed with `max_depth=0` → 20, closed with `queue_depth=None` → 1, half_open → 1, open → 0; `is_fresh` cases copied from `tests/unit/test_enrich_replay_plan.py`. Integration: `recent_for_tasks` ignores other tasks and returns newest first.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_llm_breaker.py -q` — FAIL.
- [ ] **Step 3: Implement** (scan `recent` from newest until the first non-failure to get `n`).
- [ ] **Step 4: Run** unit file, the integration test, and `uv run mypy packages/cti-core/src packages/cti-scraper/src` — PASS.
- [ ] **Step 5: Commit** `feat(core): add stateless LLM circuit breaker`.

### Task 3: Split the pipeline; `enrich.article` stops calling the LLM

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/pipeline.py`, `stages/persist.py`, `stages/relevance.py` (`RelevanceResult.from_audit`), `story/attach.py` (`StoryLink.to_context`/`from_context`), `apps/worker/src/cti_worker/tasks/enrich.py`
- Test: `tests/unit/test_pipeline_prepare.py` (new); update `tests/unit/test_pipeline_{relevance,story,tier0,tier1}.py`, `tests/unit/test_enrich_failure_kind.py`, `tests/unit/test_enrich_empty_response.py`, `tests/integration/test_enrich_pipeline_resilience.py`, `test_enrich_cross_source_dedup.py`, `test_pipeline_story.py`, `test_pipeline_tier1_db.py`, `test_enrich_task_failures.py`, `test_ttp_normalization.py`, `test_threat_actor_backfill.py`, `test_source_grade_defaults.py`

**Interfaces:**
- Consumes: Task 1 `EnrichJobRepo.create`, `has_classify`.
- Produces in `cti_enrich.pipeline`:
  - `Prepared` dataclass: `title, url, posted_on, source, scraper_id, text, story: StoryLink | None, relevance: RelevanceResult | None, classify_result: ClassifyResult | None, content_kind, default_relevance, tlp, pap`; `to_context() -> dict` / `Prepared.from_job(job: EnrichJob) -> Prepared` (text from `input_text`).
  - `prepare(*, title, url, posted_on, source, scraper_id, session, content_kind=None, default_relevance="classify", tlp="clear", pap="clear") -> Prepared | PipelineOutcome` (a `PipelineOutcome(duplicate=True)` when the URL is an article **or has a classify job**).
  - `complete(prepared: Prepared, classify_result: ClassifyResult, *, session, alert: bool) -> PipelineOutcome` (no LLM; creates the `ttp` job and passes `llm_ttp_status` to `persist`).
  - `run_pipeline(...)` keeps its signature for `enrich.article`: `prepare`, then `complete` when `classify_result` is known, else `EnrichJobRepo.create(kind="classify", ...)`, commit, and return `PipelineOutcome(accepted=False, pending_job_id=<id>)`.
  - `PipelineOutcome.pending_job_id: int | None = None`.
  - `ttp_job_input(text, summary) -> str` (= current `_ttp_input`).
- `persist(..., llm_ttp_status: str | None = None)` writes the column.
- `RelevanceResult.from_audit(d: dict) -> RelevanceResult` (inverse of `to_audit`).
- After this task the gate's `shadow`/`audit`/`llm` decisions produce a `classify` job (the LLM
  verdict comes from the job, Task 4).

- [ ] **Step 1: Write failing tests** in `test_pipeline_prepare.py` (fake session/repos as in the existing `test_pipeline_*` unit tests): `test_uncertain_title_creates_classify_job_without_llm` (classify patched to raise `AssertionError`; outcome `pending_job_id` set, job context round-trips story and relevance); `test_tier0_completes_with_ttp_skipped`; `test_gated_completes_and_creates_ttp_job` (status `pending`, job `input_text == ttp_job_input(text, summary)`); `test_inherited_completes_with_ttp_skipped`; `test_best_practice_writes_skipped`; `test_empty_ttp_input_writes_skipped`; `test_duplicate_when_classify_job_pending` (Review Focus 1: different title, same URL → duplicate, `create` not called); `test_prepared_context_round_trip`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_pipeline_prepare.py -q` — FAIL.
- [ ] **Step 3: Implement** the split (behaviour of the deterministic tail unchanged, including the `relevance_gate` incident rule and story attach). In `enrich.py`: drop the openai errors and `EmptyLLMResponse` from the retried set (keep DB/`httpx` retries); `on_failure` creates a `failed` `classify` job with `input_text=None`, `last_error="<Type>: <scrubbed msg>"[:300]`; remove `_record_enrichment_failure` and `_failure_kind` (alerting moves to Task 5). Update the listed tests: where they relied on an inline LLM classify, assert the `classify` job instead, or run the job through Task 4's `run_job` once it exists (leave such cases `xfail(strict=True, reason="Task 4")` and flip them in Task 4).
- [ ] **Step 4: Run** the fast suite and the touched integration files — PASS.
- [ ] **Step 5: Commit** `refactor(enrich): split pipeline into prepare and complete, defer LLM work to jobs`.

### Task 4: Job runner `run_job` and task `enrich.llm`

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/jobs.py`
- Modify: `apps/worker/src/cti_worker/tasks/enrich.py` (task `enrich.llm`), `packages/cti-core/src/cti_core/celery_client.py` (`send_enrich_llm(job_id: int, decision: str | None = None)`)
- Test: `tests/integration/test_enrich_jobs_runner.py`; flip the Task 3 `xfail`s

**Interfaces:**
- Consumes: Task 1 repo, Task 3 `Prepared`, `prepare`, `complete`, `ttp_job_input`; `classify`, `extract_ttps`, `normalize_ttp_result`, `verify_evidence`, `merge_ttps`, `classify_from_story`, `StoryRepo.get_inherit`, `apply_ttps`, `apply_assessments`, `is_fresh`.
- Produces: `JobOutcome = Literal["done", "duplicate", "gone", "retry", "failed"]`; `run_job(job_id: int, *, decision: Literal["accept", "reject"] | None = None, now: datetime | None = None) -> JobOutcome` (opens its own `sync_session()`s; the LLM call happens with no session open); Celery task `enrich.llm(job_id, decision=None)` on queue `enrich`, no Celery retry, returns the outcome.
- Gateway errors = the tuple currently in `_TRANSIENT_ERRORS` minus DB errors, plus `_CONFIG_ERRORS` (move both tuples to `cti_enrich.jobs` as `GATEWAY_ERRORS`).

- [ ] **Step 1: Write failing tests** (LLM patched at `cti_enrich.jobs.classify` / `.extract_ttps`):
  - `test_classify_job_accepts_and_alerts_if_fresh` (job deleted, article stored, `route_alerts` called once; with `posted_on` 3 days old → not called).
  - `test_classify_job_rejects_to_rejected_articles`.
  - `test_classify_job_inherits_when_lead_classified_meanwhile` (`stories.classify` set after the job was created; classify mock asserts not called; audit `inherited_from_story`).
  - `test_job_without_text_runs_prepare_first` (migrated row; fetch patched).
  - `test_gateway_error_reschedules_without_cap` (`openai.InternalServerError` → `attempts == 1`, still pending; repeat 10× → still pending).
  - `test_json_error_fails_after_three` (classify job `failed`; ttp job deleted and `llm_ttp_status='failed'`).
  - `test_unexpected_error_marks_failed`.
  - `test_ttp_job_merges_and_keeps_analyst` (article with an `analyst` attack-pattern mention T1059 and a `keyword` mention T1566; LLM returns T1566 with evidence present in `input_text` and T1027 with evidence absent → T1566 becomes `llm`, T1027 dropped, T1059 analyst unchanged; `priority_score` recomputed; status `done`; no alert).
  - `test_run_job_twice_creates_one_article` (Review Focus 2).
  - `test_analyst_decision_vs_inflight_llm` (job deleted by a concurrent accept before the LLM result is persisted → outcome `gone`, still one article) and `test_ttp_job_for_deleted_article_is_gone` (Review Focus 3).
  - `test_migrated_row_for_existing_article_is_duplicate` (Review Focus 4).
  - `test_accept_decision_uses_rule_incident` and `test_reject_decision_reason_analyst` (no LLM call).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_enrich_jobs_runner.py -q` — FAIL.
- [ ] **Step 3: Implement** `run_job`: load the job (session 1, closed); classify path = story re-check → decision/LLM (no session) → session 2: `get_for_update` (gone → `"gone"`), `_known_article` (exists → delete job, `"duplicate"`), `complete(..., alert=is_fresh(...))` or `persist_rejected`, delete job, commit. TTP path = LLM → session 2: `get_for_update`, load article (missing → `"gone"`), build current techniques from `article.mentions_of("attack-pattern")` (non-`analyst` → `SourcedTechnique` for `merge_ttps`; `analyst` appended unchanged), `apply_ttps`, `touch_entity_seen`, `apply_assessments`, status `done`, delete job. Failure accounting per spec 4.3 item 4.
- [ ] **Step 4: Run** the new file, the flipped Task 3 tests and the fast suite — PASS.
- [ ] **Step 5: Commit** `feat(enrich): run LLM classify and TTP as durable jobs`.

### Task 5: Dispatcher, alerts, and retiring auto-replay

**Files:**
- Create: `apps/worker/src/cti_worker/tasks/llm_dispatch.py`
- Modify: `apps/worker/src/cti_worker/beat.py` (replace `enrich-auto-replay` with `enrich-llm-dispatch`, `crontab(minute="*")`, queue maintenance), `apps/worker/src/cti_worker/tasks/llm_maintenance.py` (remove `auto_replay`), `apps/worker/src/cti_worker/reports/daily_counters.py` (the "failed" counter reads `EnrichJobRepo.counts()` pending/failed instead of `rejected_articles.failure_kind`), `packages/cti-enrich/src/cti_enrich/pipeline.py` (immediate send after commit when the breaker is closed), `Makefile`
- Delete: `packages/cti-core/src/cti_core/enrich_replay.py`, `tools/ops/replay_failed_enrichment.py`, `tests/unit/test_enrich_replay_plan.py`, `tests/unit/test_replay_failed_enrichment.py`, `tests/integration/test_replay_failed_enrichment.py`, `tests/integration/test_auto_replay_task.py`, the `replay-failed-enrichment` Makefile target and its case in `tests/unit/test_ops_makefile.py`, `RejectedArticleRepo.auto_replay_candidates`/`mark_auto_replayed`
- Test: `tests/integration/test_llm_dispatch_task.py`, `tests/unit/test_enrich_failure_alert.py` (rewrite), `tests/unit/test_beat_schedule*.py` (existing beat test, update)

**Interfaces:**
- Consumes: Task 1 `claim_due`, `counts`; Task 2 `breaker_state`, `dispatch_limit`; Task 4 `send_enrich_llm`; `cti_scraper.sinks.enrich_queue_depth`.
- Produces: task `enrich.llm_dispatch() -> dict[str, int]` (`{"sent", "failed", "limit"}`); `alert_llm_down(waiting: int) -> None` and `alert_job_failed(title: str, error: str) -> None` in `cti_worker.tasks.llm_dispatch` (Redis `SET NX EX` dedupe, key per alert type, cooldown `worker.enrich_failure_alert_cooldown_min`, best effort); `run_job` calls `alert_job_failed` through a hook passed by the worker task (keep `cti_enrich` free of `cti_alerts` imports).

- [ ] **Step 1: Write failing tests:** dispatch with breaker closed sends ≤ 20 and respects queue room; half-open sends exactly 1; open sends 0 and calls `alert_llm_down(n_pending)`; claim is committed before send (send raising leaves jobs leased, not re-sent in the same minute); outage simulation `test_outage_then_recovery_drains_without_manual_action` (30 `run_pipeline` arrivals with classify raising 503 → 30 jobs, `llm_calls` failures recorded only by canaries; then LLM ok → repeated dispatch + `run_job` drain to 0 jobs, 30 articles or rejects); alert dedupe (two calls within cooldown → one `send_alert`); beat schedule has `enrich.llm_dispatch` and no `enrich.auto_replay`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**, delete the retired files, fix imports (`grep -rn "enrich_replay\|auto_replay\|replay_failed_enrichment" apps packages tools tests Makefile` returns only migration/model column names and docs).
- [ ] **Step 4: Run** the fast suite and the touched integration files — PASS.
- [ ] **Step 5: Commit** `feat(worker): dispatch LLM jobs behind the circuit breaker, retire auto-replay`.

### Task 6: API (`/api/enrich-jobs`, ArticleOut, filtered articles, data health)

**Files:**
- Create: `apps/api/src/cti_api/routers/enrich_jobs.py`, `apps/api/src/cti_api/schemas/enrich_job.py`
- Modify: `apps/api/src/cti_api/main.py`, `routers/filtered_articles.py` (drop `replay` and `kind=failed`), `schemas/filtered_article.py`, `schemas/article.py` (`llm_ttp_status: str | None`), article serializers, `schemas/data_health.py` (`LlmParkedOut` → `LlmQueueOut(breaker: Literal["closed","open","half_open"], retry_at: str | None, pending_classify: int, pending_ttp: int, failed: int, oldest_pending_at: str | None)`, field `parked` → `queue`), `services/data_health.py`, `packages/cti-core/src/cti_core/db/repositories/data_health.py` (drop `parked_counts`; `enrichment_failures` reads `enrich_jobs` `failed`), `docs/openapi.json`
- Test: `tests/integration/test_enrich_jobs_api.py`; update `test_filtered_articles_router_snapshot.py` (+ `.ambr`), `test_data_health_api.py`, `test_rejected_article_query.py`, `tests/unit/test_route_permissions.py`

**Interfaces:**
- Consumes: Task 1 `AsyncEnrichJobRepo`, Task 2 breaker, Task 4 `send_enrich_llm`.
- Produces: `GET /api/enrich-jobs` → `EnrichJobListResponse(items: list[EnrichJobOut], total, page, page_size)`, `EnrichJobOut(id, kind, url, title, source, posted_on, state, attempts, last_error, created_at, next_attempt_at, p_threat_news: float | None)`; `POST /api/enrich-jobs/{id}/accept|reject` (`manage_sources`, 404 missing, 409 `ttp`, audit `enrich_job_accept|reject`); `POST /api/enrich-jobs/{id}/retry` (`manage_scraper`, 409 unless `failed`, audit `enrich_job_retry`). The list uses the same read permission as `GET /api/filtered-articles`.

- [ ] **Step 1: Write failing tests** for list filters/pagination/search, each POST (status codes, permission 403, `send_enrich_llm` called with the decision, audit row), `ArticleOut.llm_ttp_status`, data health `queue` block, and that `POST /api/filtered-articles/{id}/replay` is gone (404/405) and `kind=failed` is rejected (422).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**; then `uv run python tools/export_openapi.py` and `uv run pytest tests/integration/test_filtered_articles_router_snapshot.py --snapshot-update`.
- [ ] **Step 4: Run** fast suite + touched integration files — PASS.
- [ ] **Step 5: Commit** `feat(api): expose the enrichment queue and breaker state`.

### Task 7: Web

**Files:**
- Modify: `apps/web/src/components/newsroom/filtered-view.tsx` (pill "Failed enrichment" → "Enrichment queue", backed by `/api/enrich-jobs?kind=classify`; columns state, attempts, age, last error, model p; actions Accept/Reject `manage_sources`, Retry for `failed` `manage_scraper`), `article-modal.tsx` ("LLM TTPs pending" note), `apps/web/src/components/data-health/data-health-view.tsx` (breaker + queue instead of parked), `apps/web/src/lib/api/schema.d.ts` (generated)

- [ ] **Step 1:** `cd apps/web && pnpm run gen:api`; `pnpm exec next typegen && pnpm exec tsc --noEmit` — shows the type errors this task fixes.
- [ ] **Step 2: Implement** following `apps/web/CLAUDE.md` (Base UI, no backdrop-blur, theme tokens).
- [ ] **Step 3: Run** `pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build` — PASS.
- [ ] **Step 4: Browser QA** (controller, isolated `qacve` stack with seeded jobs: one pending, one failed; one article with `llm_ttp_status='pending'`): tab label, actions per role, modal note, data health; light and dark; 375 px width.
- [ ] **Step 5: Commit** `feat(web): show the enrichment queue in Newsroom and Data health`.

### Task 8: Rollback tool and release docs

**Files:**
- Create: `tools/ops/requeue_enrich_jobs.py`
- Modify: `CHANGELOG.md` (`## [0.8.11]`), `docs/prod-upgrade/0.8.11.md`, `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`, `docs/LLM_ASSIST_REDESIGN.md` (progress block, status line), `docs/TARGET_ARCHITECTURE.md` (step 1 remaining, step 4 progress), `docs/ARCHITECTURE.md` (data flow: enrich jobs, dispatcher), `CLAUDE.md` (Data flow paragraph: `enrich.llm`, `enrich.llm_dispatch`)
- Test: `tests/integration/test_requeue_enrich_jobs.py`

**Interfaces:**
- Produces: `requeue_enrich_jobs.py [--apply]`: report by default; `--apply` moves `classify` jobs to `rejected_articles` (`failure_kind='transient'`, `auto_replay_count=0`, reason `[enrichment_failed] requeued after rollback`) and deletes `ttp` jobs, in one transaction; uses `DATABASE__URL` from the environment like other `tools/ops` scripts.

- [ ] **Step 1: Write failing test** (report mode writes nothing; apply moves 2 classify jobs and drops 1 ttp job; rerun is a no-op).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Docs**: runbook headings as in `docs/prod-upgrade/0.8.11.md` (what changes, migration `<rev>`, no `.env`, after deploy: `enrich_jobs` counts and Data health queue, prod parked rows become jobs and drain; rollback: image rollback + `uv run python tools/ops/requeue_enrich_jobs.py --apply` from the host checkout; risks from spec section 8). CHANGELOG in Indonesian.
- [ ] **Step 6:** full fast suite, `uv run pytest tests/integration -q`, ruff, ruff format check, mypy — PASS.
- [ ] **Step 7: Commit** `docs: document P7g persist-first enrichment for 0.8.11`.

### Task 9: Dev verification (needs the user's approval for merge to `origin/Dev` and deploy)

- [ ] **Step 1:** With approval: merge the branch into `origin/Dev`, deploy on dev (`make deploy` on 172.25.1.77), confirm migration and that the 99 moved rows exist as jobs (read-only query).
- [ ] **Step 2:** Over one nightly outage (17:00-24:00 UTC) read: `llm_calls` classify `error` count for the day (target: tens, not hundreds); `enrich_jobs` pending peak and drain to 0 after 00 UTC; no new `rejected_articles` rows with `failure_kind`; articles accepted during the outage visible at once with `llm_ttp_status` moving `pending` → `done`.
- [ ] **Step 3:** Record the numbers in `docs/LLM_ASSIST_REDESIGN.md` and the runbook; commit `docs: record P7g dev measurements`. Then the PR to `main` with the user's approval.
