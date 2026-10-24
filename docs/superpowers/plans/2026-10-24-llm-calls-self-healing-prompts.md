# LLM Call Log, Self-Healing Enrichment and Prompt Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every LLM call in `llm_calls`, replay parked `[enrichment_failed]` articles automatically once the model works again, show both on Data health, and fix the 13 prompts' accuracy problems found in review.

**Architecture:** `get_llm_client(task=...)` returns an OpenAI client whose `chat.completions.create` is wrapped to write one `llm_calls` row per call through its own short sync session. A beat task reads the latest enrichment call to decide between a one-article canary replay and a batch replay of parked rows. `/api/data-health` gains an `llm` block rendered as a new section. Prompt fixes are local to each service and each gets a new prompt version.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic (hand-written), Celery beat, FastAPI + Pydantic, OpenAI SDK, Next.js 16 / React 19 (TanStack Query), pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-10-24-llm-calls-self-healing-prompts-design.md`

## Global Constraints

- Branch `claude/llm-calls-self-healing`; one PR; release **0.8.5**; merge to `origin/Dev` and test on the dev instance before the PR to `main`.
- Commit messages in English, conventional (`feat(...)`, `fix(...)`), ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Code comments and docstrings match the surrounding language (mostly Indonesian); docs English; `CHANGELOG.md` Indonesian.
- Ruff line length 100; `uv run mypy packages/cti-core/src packages/cti-scraper/src` stays clean.
- No new `.env` keys. Module constants: replay interval **10 min**, batch **20**, attempt cap **3**, backoff `30 min * 2 ** auto_replay_count`, alert window **24 h**, `llm_calls` retention **90 days**, TTP text cap **6,000** characters.
- Task names (exact): `classify`, `classify_tweet`, `ttp`, `recap_daily`, `recap_weekly`, `newsletter_article`, `newsletter_metadata`, `newsletter_summary`, `cve_email_validate`, `cve_email_mitigation`, `cve_email_risk`, `ta_profile`, `exec_brief`, `news_of_the_day`.
- `llm_calls.status` values: `ok`, `empty`, `error`. `failure_kind = 'config'` for `BadRequestError`, `AuthenticationError`, `PermissionDeniedError`, `NotFoundError`.
- Prompt version = `hashlib.sha256(prompt.encode()).hexdigest()[:8]`.
- After any API schema change: `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api` (node via fnm: `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"`).
- Known local failures to deselect: `tests/contract/test_golden.py::test_golden_trendmicro`, `tests/integration/test_backfill_cve_mirror.py::test_zip_source_and_limit`.

## Review Focus

- Gateway returns no `usage` at all: rows store null tokens, and the usage table sums only known tokens (shows `—` when none), never 0 invented. Test in Task 6.
- Parked article with `posted_on` null: auto-replay treats it as not fresh (no Telegram alert). Test in Task 5.
- Enrich queue depth unknown (Redis unreachable): auto-replay sends at most the canary, never a batch. Test in Task 5.
- TTP evidence quoted with curly quotes, ellipsis or different spacing from the source text: still matches after normalisation (casefold, collapse whitespace, map `“”‘’` to straight quotes); a quote absent from the text still drops the technique. Test in Task 9.
- CVE without a CVSS vector or severity: computed `attack_complexity` is `"Unknown"` and `recommended_timeline` falls back to the MEDIUM rule, no exception. Test in Task 8.

---

### Task 1: `llm_calls` table, `rejected_articles` columns, migration and repositories

**Files:**
- Create: `packages/cti-core/src/cti_core/db/models/llm_call.py`
- Modify: `packages/cti-core/src/cti_core/db/models/__init__.py` (export `LlmCall`)
- Modify: `packages/cti-core/src/cti_core/db/models/article.py` (`RejectedArticle`)
- Create: `alembic/versions/c4e7a2b9d1f0_llm_calls_and_auto_replay.py` (revises `b7e4c1a9d256`)
- Create: `packages/cti-core/src/cti_core/db/repositories/llm_call.py`
- Test: `tests/integration/test_llm_calls_repo.py`

**Interfaces:**
- Produces: model `LlmCall` (columns per spec 2.1); `RejectedArticle.auto_replay_count: int` (default 0), `RejectedArticle.last_auto_replay_at: datetime | None`.
- Produces (sync, `LlmCallRepo(session)`): `add(*, task: str, model: str, prompt_version: str | None, status: str, error_type: str | None, http_status: int | None, prompt_tokens: int | None, completion_tokens: int | None, latency_ms: int) -> None`; `purge_older_than(cutoff: datetime) -> int`; `latest_for_tasks(tasks: Sequence[str]) -> LlmCall | None`.
- Produces (async, `AsyncLlmCallRepo(session)`): `latest_for_tasks(tasks) -> LlmCall | None`; `latest_ok_at(tasks) -> datetime | None`; `latest_error() -> LlmCall | None`; `usage_by_task(since: datetime) -> list[TaskUsage]` where `TaskUsage` is a frozen dataclass `(task: str, calls: int, errors: int, prompt_tokens: int | None, completion_tokens: int | None, median_latency_ms: int | None, prompt_version: str | None)`.

- [ ] **Step 1: Write failing integration tests** in `tests/integration/test_llm_calls_repo.py`:
  - `test_add_and_latest_for_tasks`: add `classify` ok then `ttp` error; `latest_for_tasks(["classify","ttp"]).status == "error"`.
  - `test_usage_by_task_sums_known_tokens_only`: two `classify` rows with tokens (10/2, 20/3) and one with null tokens and `status="error"` → `calls == 3`, `errors == 1`, `prompt_tokens == 30`, `completion_tokens == 5`; a task whose rows all have null tokens → `prompt_tokens is None`.
  - `test_purge_older_than_90_days`: rows at now-91d and now-1d → `purge_older_than(now - 90d) == 1`.
  - `test_rejected_upsert_keeps_auto_replay_fields`: create a rejected row, set `auto_replay_count=2`, `last_auto_replay_at=X`, call `RejectedArticleRepo.upsert(...)` again for the same url → fields unchanged.
  - `test_migration_backfills_config`: covered by Step 4's migration check below.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_llm_calls_repo.py -q` — expect FAIL (import errors).
- [ ] **Step 3: Implement** the model (indexes `ix_llm_calls_at`, `ix_llm_calls_task_at`), the two columns on `RejectedArticle` (`server_default="0"` for the count), and both repos (`usage_by_task` via one `GROUP BY task` query; median through `percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)`; `prompt_version` = version of the newest row per task).
- [ ] **Step 4: Write the migration** following `b7e4c1a9d256_rejected_articles_failure_kind.py`: create table + indexes, add columns, then
  `UPDATE rejected_articles SET failure_kind = 'config' WHERE failure_kind = 'permanent' AND (reason LIKE '[enrichment_failed] BadRequestError%' OR reason LIKE '[enrichment_failed] NotFoundError%' OR reason LIKE '[enrichment_failed] AuthenticationError%' OR reason LIKE '[enrichment_failed] PermissionDeniedError%')`. Downgrade drops table/columns and sets `config` back to `permanent`. Add a test `test_migration_backfill_config` in the same file that inserts a `permanent` BadRequestError row via SQL, runs the backfill SQL from the migration module (import its constant) and asserts `config`.
- [ ] **Step 5: Run** `uv run pytest tests/integration/test_llm_calls_repo.py tests/integration/test_migrations_match_models.py -q` — expect PASS.
- [ ] **Step 6: Commit** `feat(core): llm_calls table and auto-replay fields on rejected_articles`.

### Task 2: Instrumented LLM client

**Files:**
- Create: `packages/cti-core/src/cti_core/llm/usage.py`
- Modify: `packages/cti-core/src/cti_core/llm/client.py` (`get_llm_client`)
- Test: `tests/unit/test_llm_client_instrumentation.py`

**Interfaces:**
- Consumes: `LlmCallRepo.add` (Task 1), `cti_core.db.engine.sync_session`, `usage_from`.
- Produces: `get_llm_client(*, task: str, settings: LlmSettings | None = None) -> tuple[OpenAI, str]`; `cti_core.llm.usage.record_call(**fields) -> None` (best-effort); `cti_core.llm.usage.prompt_version(prompt: str) -> str`. The wrapped `create` accepts and strips `prompt_version: str | None = None`.

- [ ] **Step 1: Write failing unit tests** (patch `cti_core.llm.usage.record_call` with a recorder; patch the underlying `Completions.create` with fakes):
  - `test_ok_call_records_tokens_and_latency`: fake returns choices + usage 12/3 → one record with `status="ok"`, `prompt_tokens=12`, `completion_tokens=3`, `task="classify"`, `model` = resolved model, `latency_ms >= 0`; the SDK fake did not receive `prompt_version`.
  - `test_empty_choices_recorded_as_empty`: choices `[]` → `status="empty"`, result returned unchanged.
  - `test_error_recorded_and_reraised`: fake raises `openai.BadRequestError` (status 400) → record `status="error"`, `error_type="BadRequestError"`, `http_status=400`; the same exception object propagates.
  - `test_recording_failure_never_breaks_the_call`: `record_call` patched to raise → `create` still returns the fake result.
  - `test_task_is_required`: `get_llm_client()` without `task` raises `TypeError`.
  - `test_prompt_version_is_8_hex`: `prompt_version("x") == hashlib.sha256(b"x").hexdigest()[:8]`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_llm_client_instrumentation.py -q` — expect FAIL.
- [ ] **Step 3: Implement**: wrap by replacing `client.chat.completions.create` on the instance with a closure (task, model captured); `record_call` opens `sync_session()`, calls `LlmCallRepo(session).add(...)`, catches every exception and logs `llm_call_record_failed`. The `usage.py` docstring records the accepted exception from spec 3.2 (scraper `fetch()` in `monitor_x`/`tweet_alerts` reaches the DB only through this best-effort log).
- [ ] **Step 4: Run** the test file — expect PASS; run `uv run mypy packages/cti-core/src` — clean.
- [ ] **Step 5: Commit** `feat(core): record every LLM call through an instrumented client`.

### Task 3: Every call site names its task

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/stages/classify.py` (`classify(title: str, *, task: str = "classify")`)
- Modify: `packages/cti-enrich/src/cti_enrich/stages/extract_ttps.py`
- Modify: `scrapers/src/cti_scrapers/feeds/monitor_x.py:270`, `scrapers/src/cti_scrapers/collectors/tweet_alerts.py:238` (`task="classify_tweet"`)
- Modify: `apps/api/src/cti_api/services/{recap,newsletter,newsletter_summary,cve_email,ta_profile,exec_brief}.py`, `apps/worker/src/cti_worker/reports/news_of_the_day.py`
- Test: `tests/unit/test_llm_call_sites.py`; update tests that call `get_llm_client()` without `task`

**Interfaces:**
- Consumes: `get_llm_client(task=...)`, `prompt_version(...)` (Task 2).
- Produces: each module exposes `PROMPT_VERSION`-style constants passed as `prompt_version=` (recap daily/weekly use their respective system prompt; newsletter uses the rendered template per language at call time).

- [ ] **Step 1: Write the failing test** `test_every_get_llm_client_call_names_a_task`: walk `apps/`, `packages/`, `scrapers/` `*.py` (excluding tests), regex `get_llm_client\(` and assert each match is followed by `task=` before the closing parenthesis; also assert the set of task literals equals the Global Constraints list.
- [ ] **Step 2: Run** it — expect FAIL listing the 13 call sites.
- [ ] **Step 3: Update** each call site with its task name from Global Constraints and `prompt_version=`; recap `_call_llm` takes a `task` argument (`recap_daily` / `recap_weekly`).
- [ ] **Step 4: Run** `uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro` — expect PASS (fix any test patching `get_llm_client` with a lambda that rejects keywords: make fakes accept `**_`).
- [ ] **Step 5: Commit** `feat: name every LLM call site's task`.

### Task 4: `config` failures and an alert override for replays

**Files:**
- Modify: `apps/worker/src/cti_worker/tasks/enrich.py` (`_failure_kind`, task signature, retry policy)
- Modify: `packages/cti-core/src/cti_core/celery_client.py` (`send_enrich_task`)
- Modify: `packages/cti-enrich/src/cti_enrich/pipeline.py` only if the `alert` flag needs threading (it already accepts `alert`)
- Test: `tests/unit/test_enrich_failure_policy.py` (extend the existing enrich task tests if present; otherwise new)

**Interfaces:**
- Produces: `send_enrich_task(*, title, url, posted_on, source, scraper_id, replay: bool = False, alert: bool | None = None) -> None` (sends `alert` only when not None); `enrich.article` accepts `alert: bool | None = None` and uses `alert if alert is not None else not replay`.

- [ ] **Step 1: Write failing tests**:
  - `test_config_errors_are_config`: `_failure_kind(openai.BadRequestError) == "config"`, same for `AuthenticationError`, `PermissionDeniedError`, `NotFoundError`; `InternalServerError` stays `transient`; `JSONDecodeError` stays `json`.
  - `test_config_error_is_not_retried`: run the task body with a pipeline that raises `BadRequestError` → no `self.retry` call, failure recorded with `failure_kind="config"`.
  - `test_alert_override`: `replay=True, alert=True` → pipeline called with `alert=True`; `replay=True` alone → `alert=False`; `send_enrich_task(..., alert=None)` does not put `alert` in kwargs.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** the classification and the override; update the module docstring's failure policy (Indonesian) with the `config` path.
- [ ] **Step 4: Run** the tests — expect PASS.
- [ ] **Step 5: Commit** `fix(worker): park gateway config errors at once and let replays choose alerts`.

### Task 5: `enrich.auto_replay` and `llm.purge_calls`

**Files:**
- Create: `packages/cti-core/src/cti_core/enrich_replay.py` (pure decision)
- Modify: `packages/cti-core/src/cti_core/db/repositories/article.py` (`RejectedArticleRepo.auto_replay_candidates`, `mark_auto_replayed`)
- Create: `apps/worker/src/cti_worker/tasks/llm_maintenance.py`
- Modify: `apps/worker/src/cti_worker/celery_app.py` (import), `apps/worker/src/cti_worker/beat.py` (two entries, queue `QUEUE_MAINTENANCE`)
- Test: `tests/unit/test_enrich_replay_plan.py`, `tests/integration/test_auto_replay_task.py`; extend the beat schedule test if one lists entries

**Interfaces:**
- Consumes: `LlmCallRepo.latest_for_tasks`, `LlmCallRepo.purge_older_than` (Task 1); `send_enrich_task(..., replay=True, alert=...)` (Task 4); `cti_scraper.sinks` queue-depth helper (currently `_broker_redis().llen(...)`; expose it as `enrich_queue_depth() -> int | None` returning None on Redis errors).
- Produces: `plan_auto_replay(candidates: Sequence[ReplayCandidate], *, last_status: str | None, queue_depth: int | None, max_depth: int, now: datetime) -> list[ReplayCandidate]`; `ReplayCandidate` frozen dataclass `(id: int, url: str, title: str, source: str, scraper_id: str | None, posted_on: date | None, auto_replay_count: int, last_auto_replay_at: datetime | None)`; `is_fresh(posted_on: date | None, now: datetime) -> bool` (24 h window, None → False). Constants `BATCH = 20`, `MAX_ATTEMPTS = 3`, `BACKOFF_BASE = timedelta(minutes=30)`.
- Repo: `auto_replay_candidates(now: datetime, limit: int) -> list[ReplayCandidate]` (kinds `transient`, `config`, `json`; count < 3; backoff elapsed; oldest `rejected_at` first); `mark_auto_replayed(ids: Sequence[int], now: datetime) -> None`.

- [ ] **Step 1: Write failing unit tests** for `plan_auto_replay`:
  - healthy (`last_status="ok"`), depth 0, 25 candidates → 20 returned, oldest first.
  - unknown (`"error"`, `"empty"`, None) → exactly 1 (canary).
  - healthy but `queue_depth` near max (`max_depth - 5`) → 5.
  - `queue_depth=None` with healthy status → 1 (canary only).
  - no candidates → [].
  - `is_fresh`: posted today → True; posted 2 days ago → False; None → False.
- [ ] **Step 2: Write failing integration test** `test_auto_replay_sends_and_marks`: seed 3 parked rows (`transient`, `config`, `permanent`) and one `llm_calls` ok row; run the task function with `send_enrich_task` patched → 2 sends (not `permanent`), both rows `auto_replay_count == 1`; alert True only for the row posted today. `test_purge_calls_task` deletes a 91-day-old row.
- [ ] **Step 3: Run** both files — expect FAIL.
- [ ] **Step 4: Implement** the pure module, the repo methods, the tasks (`enrich.auto_replay`: gather inputs, plan, mark, commit, send; `llm.purge_calls`: cutoff now-90d) and the beat entries (`"enrich-auto-replay": crontab(minute="*/10")`, `"llm-purge-calls": crontab(hour=3, minute=40)`).
- [ ] **Step 5: Run** the tests — expect PASS.
- [ ] **Step 6: Commit** `feat(worker): replay parked articles automatically once the model works`.

### Task 6: `llm` block in `/api/data-health`

**Files:**
- Modify: `apps/api/src/cti_api/schemas/data_health.py` (add `LlmHealthOut`, `LlmErrorOut`, `LlmParkedOut`, `LlmTaskUsageOut`; field `llm` on `DataHealthOut`)
- Modify: `apps/api/src/cti_api/services/data_health.py` (`_build`)
- Modify: `packages/cti-core/src/cti_core/db/repositories/data_health.py` (parked counts) or reuse Task 1/5 repos
- Modify: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts` (regenerated)
- Test: `tests/integration/test_data_health_api.py` (extend)

**Interfaces:**
- Consumes: `AsyncLlmCallRepo` (Task 1).
- Produces (JSON): `llm: {status: "ok"|"failing"|"unknown", last_call_at, last_ok_at, last_error: {at, task, error_type, http_status} | null, parked: {total, auto_eligible, auto_replays_24h}, usage_24h: [TaskUsage], usage_7d: [TaskUsage]}` where each usage item is `{task, calls, errors, prompt_tokens, completion_tokens, median_latency_ms, prompt_version}`.

- [ ] **Step 1: Write failing tests**: seed `llm_calls` (classify ok 2 h ago, ttp error 1 h ago with 400) and parked rows → `status == "failing"`, `last_error.http_status == 400`, `parked.total`, `auto_eligible` (excludes `permanent` and rows at the 3-attempt cap), `usage_24h` contains both tasks; a seeded task with null tokens has `prompt_tokens is None`; no calls at all → `status == "unknown"`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** using the status rule from spec 4.2 step 2.
- [ ] **Step 4: Run** the tests, `uv run python tools/export_openapi.py`, `pnpm run gen:api` — expect PASS and regenerated files.
- [ ] **Step 5: Commit** `feat(api): LLM status, parked articles and usage on data health`.

### Task 7: LLM section on the Data health page

**Files:**
- Modify: `apps/web/src/components/data-health/data-health-view.tsx`

**Interfaces:**
- Consumes: `DataHealthOut.llm` (Task 6) through the existing `["data-health"]` query.

- [ ] **Step 1: Add the section "LLM"** using the page's existing `Section`, `Row` and tone helpers: status row (`ok` → OK, `failing` → Problem with `"<http_status> <error_type> · <task> · <relative time>"`, `unknown` → Unknown), parked row (`"<total> parked · <auto_eligible> eligible for auto-replay · <auto_replays_24h> auto-replays in 24 h"` with the existing Newsroom link), and a framed table (task, calls, errors, prompt/completion tokens 24 h and 7 d, median latency; `—` for null). Add one paragraph to "How to read this page".
- [ ] **Step 2: Verify** `./node_modules/.bin/next typegen && ./node_modules/.bin/tsc --noEmit && ./node_modules/.bin/eslint src` in `apps/web` — clean.
- [ ] **Step 3: Commit** `feat(web): LLM section on data health`.

### Task 8: Correctness fixes in four prompts

**Files:**
- Modify: `apps/api/src/cti_api/services/newsletter.py` (`_PROMPT_FROM_METADATA`)
- Modify: `apps/api/src/cti_api/services/ta_profile.py` (context block, prompt rules, overwrites)
- Modify: `apps/api/src/cti_api/services/exec_brief.py` (`_build_user_message`, `SYSTEM_PROMPT`)
- Modify: `apps/api/src/cti_api/services/cve_email.py` (computed fields, JSON input, mitigation wording)
- Test: `tests/unit/test_prompt_correctness.py`, `tests/integration/test_ta_profile_context.py`

**Interfaces:**
- Consumes: `AsyncAttackQueryRepo.get_group_by_name_or_alias_ci(name)` and `get_group(group_id)` (existing) for the TA context.
- Produces: `cve_email.computed_fields(cve_data: dict) -> dict[str, str]` returning `attack_complexity`, `recommended_timeline`, `affected_version`, `analysis_timestamp`; `ta_profile.apply_overrides(profile: dict, mitre_group_id: str | None, now: datetime) -> dict`.

- [ ] **Step 1: Write failing tests**:
  - `test_metadata_prompt_forbids_invention`: `_PROMPT_FROM_METADATA` contains no `"plausible"` and no `"Do not mention that the article was paywalled"`, and contains "only" plus "do not add" wording.
  - `test_exec_brief_labels`: `_build_user_message(90, {"total_incidents": 992, "confirmed_incident_rate": 37, ...})` contains `"Threat news articles: 992"` and `"Confirmed incidents: 367"` (rounded 992*0.37) and no `"Total incidents tracked"`.
  - `test_cve_computed_fields`: vector `AV:N/AC:L/...` → `"Low"`; `AC:H` → `"High"`; no vector → `"Unknown"`; severity CRITICAL → `"CRITICAL (24-48h)"`, HIGH → `"HIGH (7 days)"`, MEDIUM → `"MEDIUM (30 days)"`, LOW → `"LOW (90 days)"`, missing → MEDIUM rule; `analysis_timestamp` is ISO 8601 UTC; model output for those keys is overwritten.
  - `test_cve_input_is_json_capped`: the user message is valid JSON and at most 6,000 characters.
  - `test_mitigation_prompt_not_exactly_7`: prompt contains "5 to 7" and no "EXACTLY 7".
  - `test_ta_prompt_requires_context_only`: `_SYSTEM_PROMPT` states that `known_malware`, `exploited_vulnerabilities`, `attack_techniques` and `known_iocs` come only from the provided context and are empty otherwise.
  - `test_ta_overrides`: `apply_overrides` sets `profile_metadata.generated_at`, `tlp_marking == "TLP:CLEAR"`, `identity.tracking_ids.mitre_group_id` (or None).
  - Integration `test_ta_profile_context_from_attack`: seed an `attack_groups` row with alias and a related software/technique; the built user message contains the MITRE ID, the software name and the technique ID; a name with no group yields a context block that says no ATT&CK match.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** per spec 6.1 items 1-4.
- [ ] **Step 4: Run** the tests plus existing `tests/integration/*newsletter*`, `*ta_profile*`, `*exec*`, `*cve_email*` — expect PASS (update snapshots only where the prompt text is snapshotted, and say so in the commit body).
- [ ] **Step 5: Commit** `fix(api): stop four prompts from stating things the data does not say`.

### Task 9: TTP prompt, full-text input and evidence verification

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/stages/extract_ttps.py` (prompt; `verify_evidence(result: TtpResult, text: str) -> TtpResult`)
- Modify: `packages/cti-enrich/src/cti_enrich/pipeline.py` (`_extract_ttps_or_empty(url, text, summary)`)
- Test: `tests/unit/test_ttp_evidence.py`; update existing TTP tests

**Interfaces:**
- Produces: `extract_ttps(source_text: str) -> TtpResult` (input is the capped text); `verify_evidence(result, text) -> TtpResult`; constant `TTP_TEXT_CAP = 6000`.

- [ ] **Step 1: Write failing tests**:
  - `test_prompt_allows_none`: prompt contains "up to 5" and "has_techniques": false instruction; no "top 5".
  - `test_evidence_must_be_in_text`: technique with evidence present (different case and spacing) kept; evidence absent dropped; curly vs straight quotes match; empty evidence dropped.
  - `test_pipeline_uses_text_then_summary`: with text → `extract_ttps` gets `text[:6000]`; with empty text → gets the summary.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement**; call `verify_evidence` after `normalize_ttp_result` in `pipeline.py`, using the same string sent to the model.
- [ ] **Step 4: Run** the tests and `uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro` — expect PASS.
- [ ] **Step 5: Commit** `fix(enrich): TTPs only with evidence found in the article text`.

### Task 10: Classify prompt cleanup and boundary examples

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/stages/classify.py` (`_PROMPT`)
- Test: `tests/unit/test_classify_prompt.py`

- [ ] **Step 1: Write failing tests**: no line of `_PROMPT` starts with 8 spaces; the JSON format block has no `"title"` key; the prompt contains the six boundary examples (product launch, certification, vendor award, regulation explainer → false; vulnerability disclosure/exploit, campaign/data leak → true); `confidence` still requested; `PROMPT_VERSION` changed from its old value.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Rewrite** `_PROMPT` (use `textwrap.dedent` or a flush-left literal; keep every existing rule and field except `title`).
- [ ] **Step 4: Run** the tests and existing classify tests — expect PASS.
- [ ] **Step 5: Commit** `fix(enrich): tighter, cheaper classify prompt with boundary examples`.

### Task 11: JSON mode where JSON is parsed

**Files:**
- Modify: `apps/api/src/cti_api/services/recap.py` (`_call_llm`), `newsletter.py` (both summarizers), `newsletter_summary.py` (`_call_llm`), `cve_email.py` (validator, mitigation dedup)
- Test: `tests/unit/test_json_mode.py`

- [ ] **Step 1: Write the failing test** `test_json_mode_on_json_tasks`: patch `get_llm_client` with a fake capturing `create` kwargs; call each of the six functions → `response_format == {"type": "json_object"}`; `exec_brief._call_llm` and `cve_email._dedup_risk_context` → no `response_format`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Add** `response_format={"type": "json_object"}` to the six calls.
- [ ] **Step 4: Run** the test and the recap/newsletter integration tests — expect PASS.
- [ ] **Step 5: Commit** `fix(api): JSON mode for every LLM call whose reply is parsed as JSON`.

### Task 12: Release 0.8.5, full verification, Dev

**Files:**
- Modify: version strings (root and package `pyproject.toml`, each `__version__`, `apps/web/package.json` line 3), `uv.lock` (keep `revision = 3`), `docs/openapi.json`, `tests/integration/__snapshots__/test_health_router_snapshot.ambr`, `CHANGELOG.md`
- Modify: `docs/LLM_ASSIST_REDESIGN.md` and `docs/TARGET_ARCHITECTURE.md` progress sections

- [ ] **Step 1: Bump** to 0.8.5 and add a `## [0.8.5] - <date>` CHANGELOG entry (Indonesian): upgrade notes say migration + two beat entries, `beat` restarts with `make deploy`, no new `.env` keys, and parked `config` rows will start replaying automatically.
- [ ] **Step 2: Verify** (superpowers:verification-before-completion): `uv run ruff check . && uv run ruff format --check .`; mypy; `uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro`; `uv run pytest tests/integration -q --deselect tests/integration/test_backfill_cve_mirror.py::test_zip_source_and_limit`; web `tsc`, `eslint .`, `next build`; `export_openapi.py` produces no diff.
- [ ] **Step 3: Update** the progress tables in both design docs (P0 and P1 done in 0.8.5; prompt fixes listed).
- [ ] **Step 4: Commit** `chore(release): 0.8.5 - LLM call log, self-healing enrichment, prompt fixes`; push the branch; merge into `origin/Dev` through a temporary worktree.
- [ ] **Step 5: Deploy to dev only after the user approves it explicitly**, then check the four success criteria from spec section 1 and record the results in the PR body; open the PR to `main`.
