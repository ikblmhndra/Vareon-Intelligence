# Tweet LLM Cost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut tweet LLM tokens by classifying each tweet once, in the worker, with a short prompt, and by skipping the
LLM for confident tweets once a local tweet model is trusted.

**Architecture:** Tweet scrapers stop calling the LLM and yield a `TweetJobItem`; its sink writes an `enrich_jobs` row of
kind `tweet`. `cti_enrich.jobs.run_job` gets a tweet branch: optional tweet gate, else `classify_tweet()` with a short
prompt, then `tweet_verdicts` + `tweets` rows and Telegram notices. `relevance_models` gains a `kind` so a second model
(`tweet`) trains from `tweet_verdicts` with the existing P5 code.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (sync + async), Alembic (hand-written), Celery, pytest + testcontainers,
scikit-learn + fastembed (worker-nlp only).

**Spec:** `docs/superpowers/specs/2026-11-16-tweet-llm-cost-design.md` (read it first; "Settled after the builder
check" and "Calls I made" are binding).

## Global Constraints

- Comments and docstrings in Indonesian, identifiers English, docs under `docs/` in English, `CHANGELOG.md` Indonesian.
- Commit messages: English conventional commits, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Ruff (line length 100), `uv run mypy packages/cti-core/src packages/cti-scraper/src` strict, both clean after every task.
- Every new column/table exists in both a migration and the model (`tests/integration/test_migrations_match_models.py`).
- Migrations chain from the current head `d9f2b6a4c1e7`, additive, each with a working downgrade.
- No LLM call may remain in any scraper `fetch()`.
- Job kind name: `tweet`. LLM task name: `classify_tweet` (unchanged). User-message tag: `tweet`.
- Alert freshness: notices only when `now - posted_at <= 6 hours`.
- Tweet scrapers `max_items = 200`.
- Prompt ship gate: `related_cyber` agreement old vs new ≥ 95 % on ≥ 300 dev tweets.
- `tweet_verdicts` retention: 90 days, all sources.
- Gate: only in-band `threat_news` skips the LLM; rejects always go to the LLM; `RELEVANCE__MODE` governs both kinds.
- Release: next patch version after main's current one (0.8.18 if 0.8.17 is merged first), version bumped in every file a
  release touches (see CLAUDE.md "Releases"), plus `docs/prod-upgrade/<version>.md` and `docs/PROD_UPGRADE_<prev>_TO_<version>.md`.
- After any API schema change: `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`.

## Review Focus

1. A tweet already in `tweets` (stored earlier by any scraper) is seen again → no job is created, no LLM call, no
   notice. Test in Task 5.
2. The same tweet arrives from `monitor_x` (`notify=false`) and then `tweet_alerts` (`notify=true`) while the first job is
   pending → one job, `context.notify` is true. Test in Task 5.
3. The LLM gateway is down when the job runs → the job is rescheduled, nothing is stored, no notice; it succeeds on the
   next run. Test in Task 7.
4. Telegram fails for one topic of a tweet with two topics → the tweet row exists, the other topic is still sent, the job
   is gone. Test in Task 7.
5. Articles after `relevance_models.kind` exists → the article model is still found, trained and evaluated exactly as
   before (no tweet row interferes). Test in Task 3.

---

### Task 1: `enrich_jobs` accepts kind `tweet`

**Files:**
- Create: `alembic/versions/<rev>_enrich_jobs_tweet_kind.py` (down_revision `d9f2b6a4c1e7`)
- Modify: `packages/cti-core/src/cti_core/db/models/enrich_job.py` (`JOB_KINDS`, CHECK)
- Modify: `packages/cti-core/src/cti_core/db/repositories/enrich_job.py` (`JobCounts`, `_counts_query`, `claim_due`)
- Modify: `apps/api/src/cti_api/services/data_health.py`, its schema, `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`
- Test: `tests/integration/test_enrich_jobs_repo.py`, `tests/integration/test_enrich_jobs_migration.py`

**Interfaces:**
- Produces: `JOB_KINDS = ("classify", "ttp", "tweet")`; `JobCounts.pending_tweet: int`; `claim_due` orders kinds
  `classify`, `tweet`, `ttp`.

- [ ] **Step 1: Failing tests**
  - `test_create_accepts_tweet_kind`: `EnrichJobRepo.create(kind="tweet", ...)` returns a row.
  - `test_counts_include_pending_tweet`: one pending of each kind → `counts().pending_tweet == 1`.
  - `test_claim_due_orders_classify_tweet_ttp`: three due jobs → claimed kinds in that order.
  - `test_downgrade_deletes_tweet_jobs_then_restores_check` (migration test pattern of the file).
- [ ] **Step 2:** run `uv run pytest tests/integration/test_enrich_jobs_repo.py tests/integration/test_enrich_jobs_migration.py -q` → FAIL.
- [ ] **Step 3:** implement migration (drop/recreate `kind_valid`; downgrade `DELETE FROM enrich_jobs WHERE kind='tweet'`
  first), model, repo; add `pending_tweet` to the Data health jobs block (API schema + web type only, no UI work).
- [ ] **Step 4:** tests PASS; regenerate `docs/openapi.json` and `schema.d.ts`; `tests/integration/test_migrations_match_models.py` PASS.
- [ ] **Step 5:** commit `feat(enrich): add the tweet job kind to enrich_jobs`.

### Task 2: `tweet_verdicts` table and repo

**Files:**
- Create: `alembic/versions/<rev>_tweet_verdicts.py`, `packages/cti-core/src/cti_core/db/models/tweet_verdict.py`
- Modify: `packages/cti-core/src/cti_core/db/repositories/tweet.py` (add `TweetVerdictRepo`), models `__init__`
- Modify: the existing 90-day maintenance purge task that calls `RelevanceModelRepo.purge` (add the verdict purge next to it)
- Test: `tests/integration/test_tweet_verdicts_repo.py`

**Interfaces:**
- Produces: model `TweetVerdict` (`id`, `tweet_id` unique String(50), `text` Text, `related_cyber` Bool, `source`
  String(10) CHECK in (`llm`,`gate`), `prompt_version` String(16) nullable, `relevance` JSONB nullable, `created_at`).
- Produces: `TweetVerdictRepo(session).record(*, tweet_id, text, related_cyber, source, prompt_version, relevance) -> None`
  (insert; on `tweet_id` conflict do nothing), `.purge(older_than: datetime) -> int`,
  `.llm_rows(since: datetime | None = None) -> list[TweetVerdict]` (only `source='llm'`, newest first).

- [ ] **Step 1: Failing tests** `test_record_is_idempotent_per_tweet`, `test_llm_rows_exclude_gate_rows`,
  `test_purge_deletes_rows_older_than_cutoff_regardless_of_source`.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement. **Step 4:** PASS + migrations-match test PASS.
- [ ] **Step 5:** commit `feat(core): store every tweet classification in tweet_verdicts`.

### Task 3: `relevance_models.kind`

**Files:**
- Create: `alembic/versions/<rev>_relevance_models_kind.py`
- Modify: `packages/cti-core/src/cti_core/db/models/relevance.py`, `packages/cti-core/src/cti_core/db/repositories/relevance.py`
- Modify: `packages/cti-enrich/src/cti_enrich/stages/relevance.py` (cache keyed by kind), `relevance/train.py`,
  `apps/worker/src/cti_worker/tasks/relevance.py` (pass `kind="article"` for now)
- Test: `tests/integration/test_relevance_repo.py`, `tests/unit/test_relevance_stage.py`

**Interfaces:**
- Produces: column `kind` String(10) NOT NULL default `'article'`, CHECK in (`article`,`tweet`); partial unique index
  `uq_relevance_models_active` on `(kind)` WHERE `status='active'`.
- Produces: `RelevanceModelRepo.get_active(kind: str = "article")`, `activate(..., kind: str = "article")`,
  `lock(kind: str = "article")` (advisory lock key derived from kind), `set_gate_state` unchanged (acts on the row),
  `gate_stats(..., kind: str = "article")`; async repo likewise. `run_training(..., kind: str = "article")`.
  `stages.relevance._active(session, kind="article")`.

- [ ] **Step 1: Failing tests**
  - `test_one_active_model_per_kind`: activating a tweet model keeps the article model active.
  - `test_get_active_defaults_to_article` (Review Focus 5): with an active tweet model present, `get_active()` returns
    the article row and article `gate_stats` are unchanged.
  - `test_stage_cache_is_per_kind` (unit, fakes in `tests/unit/relevance_fakes.py`).
- [ ] **Step 2:** FAIL. **Step 3:** implement; existing article call sites keep working through the defaults.
- [ ] **Step 4:** PASS, plus the whole relevance suite: `uv run pytest tests/unit -k relevance tests/integration -k relevance -q`.
- [ ] **Step 5:** commit `feat(relevance): one active relevance model per kind`.

### Task 4: short tweet prompt and eval command (Part B)

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/stages/classify.py`
- Create: `packages/cti-enrich/src/cti_enrich/tweet_prompt_eval.py`
- Modify: `tests/unit/test_llm_call_sites.py` if the call-site scan needs the new function
- Test: `tests/unit/test_classify_tweet.py`

**Interfaces:**
- Produces: `_TWEET_PROMPT: str`, `TWEET_PROMPT_VERSION: str` (sha256[:8]), and
  `classify_tweet(text: str) -> ClassifyResult` (task `classify_tweet`, tag `tweet`, same JSON parsing, retries and
  `OpenAIQuotaExhausted` behaviour as `classify`; `audit["prompt_version"] == TWEET_PROMPT_VERSION`).
- Produces: `python -m cti_enrich.tweet_prompt_eval --limit N [--file tweets.jsonl]` printing, for old (`classify`) vs
  new (`classify_tweet`): agreement on `related_cyber`, agreement on `confirmed_incident`, mean prompt tokens of each.
  Input: recent `tweets` rows plus optional JSONL of `{"text": ...}` (to include rejects from a dev dry-run).

- [ ] **Step 1: Failing tests** (fake LLM client as in existing classify tests):
  - `test_classify_tweet_uses_the_tweet_prompt_and_task`: the system message is `_TWEET_PROMPT`, `task="classify_tweet"`.
  - `test_tweet_prompt_is_short`: `len(_TWEET_PROMPT) <= 3200` characters (≈ 800 tokens).
  - `test_tweet_prompt_asks_for_every_x_intel_field`: each of `related_cyber, confidence, industries_impacted,
    victim_countries, actor_countries, confirmed_incident, incident_confidence, incident_indicators, victim_name`
    appears in `_TWEET_PROMPT`.
  - `test_eval_reports_agreement` with stub classifiers: 3 of 4 agree → `0.75`.
- [ ] **Step 2:** FAIL. **Step 3:** implement (prompt written for short posts from curated threat-intel accounts, at most
  two examples, compact industry list; see spec Part B).
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** commit `feat(enrich): short dedicated prompt for tweet classification`.

### Task 5: `TweetJobItem` and its sink

**Files:**
- Modify: `packages/cti-scraper/src/cti_scraper/items.py` (add `TweetJobItem`)
- Modify: `packages/cti-scraper/src/cti_scraper/sinks.py` (add `@sink_for(TweetJobItem)`)
- Modify: `packages/cti-core/src/cti_core/db/repositories/enrich_job.py` (`create_tweet` with notify-OR upsert)
- Test: `tests/integration/test_tweet_job_sink.py`

**Interfaces:**
- Produces: `TweetJobItem(Item)` fields: `tweet_id: str`, `url: str`, `text: str`, `author_username: str`,
  `author_name: str | None`, `author_avatar: str | None`, `author_followers: int | None`, `posted_on: datetime | None`,
  `lang: str | None`, `media_urls: list[str]`, `scan_results: dict`, `routing: dict` (the `TweetRoutingInput` fields
  except `msg_data`), `notify: bool`; `dedup_key() -> tweet_id`.
- Produces: `EnrichJobRepo.create_tweet(*, url, title, source, scraper_id, posted_on, input_text, context) -> EnrichJob | None`:
  `INSERT ... ON CONFLICT (kind,url_hash) DO UPDATE SET context = jsonb_set(context,'{notify}',
  to_jsonb((enrich_jobs.context->>'notify')::bool OR (EXCLUDED.context->>'notify')::bool))`, returns the row it inserted
  or `None` on conflict.
- Context JSON (consumed by Task 7): `{"tweet": {<tweet fields>}, "scan_results": {...}, "routing": {...}, "notify": bool}`.

- [ ] **Step 1: Failing tests**
  - `test_sink_creates_one_tweet_job` (title = text[:300], input_text = text).
  - `test_sink_skips_tweet_already_stored` (Review Focus 1): a `tweets` row exists → no job.
  - `test_notify_is_ored_on_conflict` (Review Focus 2): notify=false then notify=true → one job, `context.notify` true.
  - `test_sink_ignores_enrich_backpressure`: queue depth above the max → job still created.
  - `test_sink_sends_enrich_llm_when_breaker_closed` (reuse the article `_lease_if_closed` helper; monkeypatch `_send`).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat(scraper): persist tweets as enrich jobs before any LLM call`.

### Task 6: tweet scrapers yield jobs, no LLM

**Files:**
- Modify: `scrapers/src/cti_scrapers/collectors/tweet_alerts.py`, `scrapers/src/cti_scrapers/feeds/monitor_x.py`,
  `scrapers/src/cti_scrapers/collectors/_tweet_item.py`
- Modify: `packages/cti-core/src/cti_core/llm/usage.py` docstring (the scraper exception is gone)
- Test: `tests/unit/test_tweet_alerts.py`, `tests/unit/test_monitor_x_official.py` (and other monitor_x tests that
  assert on classify), `tests/unit/test_llm_call_sites.py`

**Interfaces:**
- Consumes: `TweetJobItem` (Task 5).
- Produces: `tweet_job_item(tweet, scan, *, notify: bool) -> TweetJobItem` in `_tweet_item.py`; both scrapers have
  `max_items = 200`; `tweet_alerts` yields no `NoticeItem`; neither module imports `cti_enrich.stages.classify`.

- [ ] **Step 1: Failing tests**
  - `test_tweet_alerts_yields_one_job_item_per_kept_tweet_with_notify` (replies, RT, funding, "Ransomware Alert:" still
    filtered; `routing["related_tech_status"]` set from the scan).
  - `test_monitor_x_yields_job_items_with_notify_false`.
  - `test_no_scraper_imports_classify` (`ast` scan of `scrapers/src`).
- [ ] **Step 2:** FAIL. **Step 3:** implement; update module docstrings (the flow description and "diklasifikasi ulang").
- [ ] **Step 4:** PASS, plus `uv run pytest tests/unit -k "tweet or monitor_x or twitter" tests/contract -q`.
- [ ] **Step 5:** commit `refactor(scrapers): tweet scrapers hand tweets to the enrich queue`.

### Task 7: worker classifies tweets and sends notices

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/tweet_job.py` (tweet finish path)
- Modify: `packages/cti-enrich/src/cti_enrich/jobs.py` (dispatch on `job.kind == "tweet"`)
- Modify: `packages/cti-core/src/cti_core/llm/breaker.py` (`BREAKER_TASKS` adds `classify_tweet`)
- Test: `tests/integration/test_tweet_jobs.py`, `tests/unit/test_llm_breaker.py`

**Interfaces:**
- Consumes: `classify_tweet` (Task 4), `TweetVerdictRepo.record` (Task 2), context shape (Task 5),
  `TweetRepo.insert`, `llm_fields`/`scan_results` mapping (`_tweet_item.py`), `build_message`, `route_tweet`,
  `cti_alerts` `send_alert(topic, text)`.
- Produces: `run_tweet_job(job_id: int, now: datetime, *, verdict_for: Callable[[Session, EnrichJob], tuple[ClassifyResult, str, dict | None]] | None = None) -> JobOutcome`
  where the callable returns `(result, source, relevance_audit)`; default = LLM only (Task 8 plugs in the gate).
  `TWEET_ALERT_MAX_AGE = timedelta(hours=6)`.

Order inside `run_tweet_job` (spec Part A, Worker): already stored → delete job, `duplicate`; verdict (LLM outside any
session); session 2: lock job, record verdict, if related insert `tweets` row, delete job, commit; then notices if
`context.notify` and fresh.

- [ ] **Step 1: Failing tests** (fake classifier and fake `send_alert`):
  - `test_related_tweet_is_stored_and_notified_per_topic`.
  - `test_unrelated_tweet_is_recorded_but_not_stored`.
  - `test_stale_tweet_is_stored_without_notice` (posted 7 h before `now`).
  - `test_notify_false_stores_without_notice`.
  - `test_gateway_error_reschedules_and_stores_nothing` (Review Focus 3): first call raises a gateway error → outcome
    `retry`, no `tweets`/`tweet_verdicts` row, job pending with a later `next_attempt_at`; second run → `done`.
  - `test_one_failing_topic_does_not_stop_the_others` (Review Focus 4).
  - `test_breaker_counts_classify_tweet` (unit).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS, plus `uv run pytest tests/integration -k "enrich_job or llm_dispatch" -q`.
- [ ] **Step 5:** commit `feat(enrich): classify tweets in the enrich worker and send their alerts`.

### Task 8: tweet relevance model and gate (Part C)

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/relevance/dataset.py` (add `load_tweet_examples`)
- Modify: `packages/cti-enrich/src/cti_enrich/relevance/model.py`, `train.py` (classes per kind)
- Modify: `packages/cti-core/src/cti_core/db/repositories/relevance.py` (tweet `gate_stats` SQL over `tweet_verdicts.relevance`)
- Modify: `apps/worker/src/cti_worker/tasks/relevance.py` (train/evaluate loop over `("article","tweet")`)
- Modify: `packages/cti-enrich/src/cti_enrich/tweet_job.py` (default `verdict_for` uses the gate)
- Test: `tests/unit/test_relevance_dataset.py`, `tests/unit/test_relevance_train.py`, `tests/integration/test_tweet_gate.py`

**Interfaces:**
- Produces: `KIND_CLASSES = {"article": ("reject","best_practice","threat_news"), "tweet": ("reject","threat_news")}`;
  `fit(examples, embedder, classes=...)`; `load_tweet_examples(session) -> list[Example]` (from
  `TweetVerdictRepo.llm_rows`, label `threat_news` if `related_cyber` else `reject`, deduped by normalised text).
- Produces: `run_relevance(session, *, title, url, cfg, kind="article")`; the tweet job calls it with `kind="tweet"`,
  `title=text`, `url=tweet url`. A `gated` decision → `ClassifyResult(related_cyber=True, confidence=probs.threat_news,
  industries_impacted=tier1.industries, confirmed_incident=tier1.incident.confirmed, victim_countries=[], actor_countries=[],
  audit={"skipped": "relevance_gate", ...})` with Tier 1 from `run_tier1(session=..., title=text, text=text, victim_name=None)`;
  verdict `source="gate"`; `relevance` audit stored on the verdict row.

- [ ] **Step 1: Failing tests**
  - `test_tweet_examples_use_llm_rows_only` and `test_tweet_labels_are_binary`.
  - `test_training_tweet_kind_with_two_classes` (synthetic: 600 reject + 600 threat_news, minimums satisfied).
  - `test_tweet_training_skips_below_minimum_per_class` (50 rejects → skipped, reason names the class).
  - `test_gated_tweet_skips_llm_and_fills_tier1_fields` (active tweet model in `gate`, in-band, outside audit sample →
    classifier never called, verdict `source='gate'`).
  - `test_shadow_tweet_model_still_calls_llm_and_records_relevance`.
  - `test_evaluate_moves_tweet_gate_independently_of_article_gate`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS, plus the full relevance suite.
- [ ] **Step 5:** commit `feat(relevance): local relevance gate for tweets`.

### Task 9: Data health shows the tweet gate

**Files:**
- Modify: `apps/api/src/cti_api/services/data_health.py` and schema (relevance block per kind), the Data health web
  component that renders the relevance block, `docs/openapi.json`, `schema.d.ts`
- Test: `tests/integration/test_data_health_relevance.py`

**Interfaces:**
- Produces: Data health `relevance` becomes `{"article": <existing block>, "tweet": <same shape>}`; the web page renders
  both with the labels "Articles" and "Tweets".

- [ ] **Step 1: Failing test** `test_data_health_reports_relevance_per_kind` (tweet block null-safe with no tweet model).
- [ ] **Step 2:** FAIL. **Step 3:** implement; regenerate the API contract. **Step 4:** PASS; web
  `pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit` clean (node via fnm, see local tooling note).
- [ ] **Step 5:** commit `feat(api): show the tweet relevance gate in Data health`.

### Task 10: release, runbook and prompt eval on dev

**Files:**
- Modify: version files (CLAUDE.md "Releases" list), `uv.lock`, `CHANGELOG.md`, health snapshot
- Create: `docs/prod-upgrade/<version>.md`, `docs/PROD_UPGRADE_<prev>_TO_<version>.md`; update `docs/CI_CD.md` link,
  `docs/ARCHITECTURE.md` (tweet flow), `CLAUDE.md` data-flow paragraph (tweets join persist-first)

- [ ] **Step 1:** bump the version, write the CHANGELOG entry and runbooks (migrations: three; no `.env` keys; after-deploy
  checks: `enrich_jobs` kind `tweet` drains, `classify_tweet` calls/day ≈ distinct tweets, prompt tokens/call ≤ ~1,000,
  Telegram tweet topics still receive alerts, `tweet_verdicts` grows; rollback image-only).
- [ ] **Step 2:** full verification: `uv run pytest tests/unit tests/contract packages -q`, `uv run pytest tests/integration -q`,
  ruff, mypy, web lint/typecheck/build.
- [ ] **Step 3 (needs the user's approval, dev is shared):** merge to `origin/Dev`, deploy dev, run
  `python -m cti_enrich.tweet_prompt_eval --limit 300` (plus a dry-run JSONL for rejects) in `worker-nlp`; record the
  agreement in the runbook. Below 95 % → revise `_TWEET_PROMPT` (Task 4) and repeat.
- [ ] **Step 4:** commit `chore(release): <version>`; PR to `main` only with the user's approval.
