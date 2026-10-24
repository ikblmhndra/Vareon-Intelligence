# LLM call log, self-healing enrichment and prompt fixes

Date: 2026-10-24. Status: design approved in chat, awaiting review of this written spec.
Scope: phases P0 and P1 of `docs/LLM_ASSIST_REDESIGN.md` plus the prompt review done during
brainstorming. One PR, release 0.8.5.

## 1. Intent

What the user asked for, in their words: articles must not stay stuck when the LLM gateway
fails, the cost of every LLM call must be visible, a misconfigured model must show up
immediately, and the prompts must be checked "biar lebih akurat" (so the output is more
accurate).

What we found while designing:

- Failed articles are not lost. `apps/worker/src/cti_worker/tasks/enrich.py` retries transient
  errors 6 times over ~30 minutes, then parks the article in `rejected_articles` as
  `[enrichment_failed]`, alerts on Telegram and waits for a manual Replay. A gateway 400/404
  (wrong model name) is treated as permanent and never retried. On dev 218 articles were parked,
  128 of them from `400 Unsupported model mimo-auto`.
- Token usage is recorded only by recap and newsletter. Classify, TTP extraction and tweet
  classification, the bulk of the calls, record nothing.
- Three prompts make the platform state things that are not true (newsletter metadata summaries,
  TA profiles, exec brief), and others are inaccurate or wasteful (TTP, CVE email, classify,
  missing JSON mode).

Success criteria (checked on the dev instance after deploy):

1. Within an hour, `llm_calls` holds rows for `classify` and `ttp`, and the new LLM section on
   Data health shows model status and tokens per task.
2. Parked `[enrichment_failed]` articles decrease without anyone pressing Replay, including the
   128 `mimo-auto` rows, provided the configured model on dev works at that time (if it does not,
   the canary keeps failing and the LLM section shows why, which is also a pass).
3. New articles carry no ATT&CK technique without a verifiable evidence quote; the E8 examples
   do not recur.
4. Newsletter summaries written from metadata contain no facts that are not in the metadata.

Decisions taken in chat: no scheduled probe call (status comes from the call log); replayed
articles alert on Telegram only when `posted_on` is within 24 hours; the usage view lives on
Data health; the call log is captured by instrumenting the LLM client; all prompt fixes ship in
this spec.

## 2. Data model

### 2.1 New table `llm_calls`

One row per `chat.completions.create` call.

| Column | Type | Notes |
|--------|------|-------|
| `id` | bigint identity | PK |
| `at` | timestamptz, default `now()` | |
| `task` | varchar(40), not null | see 3.1 for the list |
| `model` | varchar(120), not null | resolved model name |
| `prompt_version` | varchar(16), null | 8-char hash of the system prompt in use |
| `status` | varchar(10), not null | `ok`, `empty` (200 without choices), `error` |
| `error_type` | varchar(80), null | exception class name |
| `http_status` | smallint, null | from `openai.APIStatusError.status_code` |
| `prompt_tokens` | integer, null | from `usage`; null when the gateway sends none |
| `completion_tokens` | integer, null | same |
| `latency_ms` | integer, not null | |

Indexes: `(at)`, `(task, at)`. No prompt or completion text is stored (size, third-party text).
No `client_id`: every current call is platform work.

Retention: 90 days, deleted by a daily beat task `llm.purge_calls` on the `maintenance` queue,
following the `scraper.purge_*` pattern.

### 2.2 `rejected_articles`

- New columns `auto_replay_count integer not null default 0` and `last_auto_replay_at
  timestamptz null`.
- New `failure_kind` value `config` for gateway 400, 401, 403 and 404 (wrong model, key or
  endpoint). Existing values stay: `transient`, `json`, `permanent`, null (rejected by
  classification).
- `RejectedArticleRepo.upsert` keeps both new columns untouched when it updates a row, so a
  replay that fails again does not reset the count.

### 2.3 Migration

One hand-written Alembic revision: create `llm_calls`, add the two columns, and backfill
`failure_kind = 'config'` for rows with `failure_kind = 'permanent'` whose `reason` starts with
`[enrichment_failed] BadRequestError`, `[enrichment_failed] NotFoundError`,
`[enrichment_failed] AuthenticationError` or `[enrichment_failed] PermissionDeniedError`.
Models are updated in the same commit so `tests/integration/test_migrations_match_models.py`
passes.

## 3. LLM client instrumentation

### 3.1 API

`cti_core.llm.client.get_llm_client(*, task: str, settings=None) -> tuple[OpenAI, str]`. `task`
is required. The returned client's `chat.completions.create` is wrapped; nothing else about the
client changes.

Task names: `classify`, `classify_tweet`, `ttp`, `recap_daily`, `recap_weekly`,
`newsletter_article`, `newsletter_metadata`, `newsletter_summary`, `cve_email_validate`,
`cve_email_mitigation`, `cve_email_risk`, `ta_profile`, `exec_brief`, `news_of_the_day`.

`classify(title, *, task="classify")`; `scrapers/.../monitor_x.py` and
`collectors/tweet_alerts.py` pass `task="classify_tweet"`.

Each call site passes its prompt version through a keyword the wrapper strips before calling the
SDK (`prompt_version=...`), computed once per module as
`hashlib.sha256(PROMPT.encode()).hexdigest()[:8]` (the existing `classify.PROMPT_VERSION`
pattern).

### 3.2 Wrapper behaviour

1. Start a monotonic timer, call the original `create`.
2. On return: `status = "empty"` when `choices` is empty or None, else `ok`; tokens from the
   existing `usage_from()`.
3. On exception: `status = "error"`, `error_type = type(exc).__name__`, `http_status =
   getattr(exc, "status_code", None)`; re-raise the original exception unchanged, so the retry
   policy in `tasks/enrich.py` behaves exactly as today.
4. Write the row through `cti_core.llm.usage.record_call()`, which opens its own short sync
   session (`cti_core.db.engine.sync_session`) and commits it. The caller's session and
   transaction are never used, so a row survives a caller rollback and async API callers need no
   change. Best-effort: any failure is logged as `llm_call_record_failed` and swallowed.

Exception to a framework rule, recorded here on purpose: `monitor_x` and `tweet_alerts` call
`classify()` inside a scraper `fetch()`, which must not touch the DB. The write happens in
`cti_core` infrastructure, not scraper logic, and contract tests fake the LLM, so no DB is used
in tests.

Out of scope: per-task token ceilings and reading `llm.rate_limit` (the wrapper is where they go
later).

## 4. Self-healing enrichment

### 4.1 Failure classification (`tasks/enrich.py`)

`_failure_kind` returns `config` for `openai.BadRequestError`, `AuthenticationError`,
`PermissionDeniedError` and `NotFoundError`. These are not retried by Celery (they will not heal
within 30 minutes); the article is parked at once and the existing Telegram failure alert fires.

### 4.2 Beat task `enrich.auto_replay`

Every 10 minutes on `maintenance`. The decision logic is a pure function so it can be unit
tested; the task only gathers inputs and sends.

1. Candidates: `rejected_articles` with `failure_kind in ('transient', 'config', 'json')`,
   `auto_replay_count < 3`, and `last_auto_replay_at` null or older than
   `30 min * 2 ** auto_replay_count`. Oldest `rejected_at` first.
2. Model status: the latest `llm_calls` row with `task in ('classify', 'ttp')`. `ok` means
   healthy; `error`, `empty` or no row means unknown.
3. Unknown: replay one candidate (canary). Healthy: replay up to 20 candidates, stopping early
   when the `enrich` queue depth reaches `scraper.enrich_queue_max_depth`.
4. For each replayed article: increment `auto_replay_count`, set `last_auto_replay_at`, commit,
   then `send_enrich_task(..., replay=True, alert=<posted_on within the last 24 hours>)`.
   `send_enrich_task` and the `enrich.article` task gain an optional `alert` argument that
   overrides the current `alert=not replay` rule only when given; the manual Replay sends no
   `alert`, so it keeps today's behaviour (no Telegram).
5. When nothing is parked the task makes no LLM call and sends nothing.

After 3 automatic attempts an article stays parked for the manual Replay, which is unchanged.

## 5. Data health: LLM section

### 5.1 API

`GET /api/data-health` (already `view_ops`, cached 60 s) gains an `llm` block:

- `status`: `ok` | `failing` | `unknown` (rule of 4.2 step 2), `last_call_at`, `last_ok_at`,
  `last_error` (`at`, `task`, `error_type`, `http_status`) or null.
- `parked`: `total` (`failure_kind` not null), `auto_eligible` (candidates of 4.2 step 1 without
  the time condition), `auto_replays_24h` (rows with `last_auto_replay_at` in the last 24 hours).
- `usage_24h` and `usage_7d`: one entry per task with `calls`, `errors` (`error` + `empty`),
  `prompt_tokens`, `completion_tokens` (null when no row of that task reported tokens),
  `median_latency_ms` and the latest `prompt_version`.

Typed response models; `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts` regenerated.

### 5.2 Web

A new "LLM" section on the Data health page, same rows and OK/Check/Problem tones as the others:

- Model status row (Problem when the latest call failed, with error type, HTTP status, task and
  age).
- Parked articles row with auto-replay count and the existing link to Newsroom > Failed
  enrichment.
- A small table: task, calls, errors, prompt/completion tokens (24 h and 7 d), median latency.
- "How to read this page" gains a paragraph for the section.

## 6. Prompt fixes

Every changed prompt gets a new `prompt_version`, so before/after can be compared per task in
`llm_calls`.

### 6.1 Correctness

1. **Newsletter metadata summary** (`services/newsletter.py`, `_PROMPT_FROM_METADATA`): remove
   "generate plausible key points" and "Do not mention that the article was paywalled". The
   prompt summarises only the metadata given (title, source, date, feed description), may return
   fewer than 3 key points, and must not add facts. The composer's existing "Summary from
   metadata only" warning stays as it is.
2. **TA profile** (`services/ta_profile.py`):
   - Before the call, build a context block from the DB: the ATT&CK group matched by name or
     alias (`attack_groups`: MITRE ID, aliases) and, through `attack_relationships`, its
     software and techniques; plus the article titles sent today.
   - The prompt requires `known_malware`, `exploited_vulnerabilities`,
     `capability_assessment.attack_techniques` and `infrastructure.known_iocs` to come only from
     that context, empty otherwise.
   - After parsing, code overwrites `profile_metadata.generated_at` (now, UTC),
     `profile_metadata.tlp_marking` (`TLP:CLEAR`) and `identity.tracking_ids.mitre_group_id`
     (from the matched group, or null). The JSON schema and the UI are unchanged.
3. **Exec brief** (`services/exec_brief.py`): the data sent to the model labels the main count
   "threat news articles" and sends confirmed incidents separately; the prompt says to use
   "incident" only for the confirmed count.
4. **CVE email** (`services/cve_email.py`):
   - Code computes `attack_complexity` (from `AC:` in the CVSS vector), `recommended_timeline`
     (from severity: CRITICAL 24-48h, HIGH 7 days, MEDIUM 30 days, LOW 90 days),
     `affected_version` (from the affected data) and `analysis_timestamp` (now); these overwrite
     whatever the model returns, and the prompt stops asking for them.
   - The model receives a JSON object of the relevant fields with a length cap instead of
     `str(cve_data)`.
   - The mitigation dedup asks for 5 to 7 genuinely distinct controls instead of "EXACTLY 7".

### 6.2 Accuracy and cost

5. **TTP extraction** (`stages/extract_ttps.py`, `pipeline.py`):
   - "Identify the top 5" becomes "up to 5 techniques directly supported by the text; return
     `has_techniques: false` and an empty list when none".
   - Input is the article text from `fetch_text`, capped at 6,000 characters, instead of the LSA
     summary cut to 2,000; the summary is used only when there is no text.
   - After normalisation to the ATT&CK catalog, techniques whose `evidence` is not found in the
     input (case-insensitive, whitespace collapsed) are dropped.
   - Expected effect: about 3x the input tokens for `ttp`, visible in `llm_calls`.
6. **Classify** (`stages/classify.py`):
   - Remove the 8-space indentation and the echoed `"title"` output field (unused by code).
   - Add six short boundary examples for `related_cyber`: product launch, certification, vendor
     award and regulation explainer without a threat are `false`; vulnerability disclosure,
     exploit, campaign and data leak are `true`.
   - Keep `confidence` (the UI uses it) and title-only input.
7. **JSON mode**: add `response_format={"type": "json_object"}` to the daily and weekly recap,
   both newsletter article summaries, the newsletter executive summary, and the CVE email
   validator and mitigation dedup. Exec brief (Markdown) and risk context (HTML) are unchanged.

## 7. Testing

Unit:

- Wrapper: records `ok`, `empty` and `error`; re-raises the original exception; the LLM call
  still succeeds when recording fails; `prompt_version` is not passed to the SDK.
- `_failure_kind` returns `config` for 400/401/403/404.
- `auto_replay` decision function: candidate filter, backoff, canary versus batch, 3-attempt cap,
  queue-depth stop, 24-hour alert rule.
- TTP evidence verification; CVE email computed fields; TA profile field overwrites and context
  block; exec brief labels; classify prompt no longer asks for `title`.
- A test that fails when any `get_llm_client(` call in `apps/`, `packages/` or `scrapers/` omits
  `task=`.

Integration (testcontainers):

- Migration creates `llm_calls` and the columns, and backfills `config`; models match.
- `RejectedArticleRepo.upsert` keeps `auto_replay_count`.
- `GET /api/data-health` returns the `llm` block with counts from seeded rows.
- `enrich.auto_replay` end to end with a fake `send_task`.
- `llm.purge_calls` deletes rows older than 90 days.

Existing tests that patch `get_llm_client` keep working; those that call it without `task` are
updated.

## 8. Rollout

- One PR, release 0.8.5 (version strings, `uv.lock`, `docs/openapi.json`, health snapshot,
  `CHANGELOG.md`).
- Migration and two new beat entries (`enrich.auto_replay`, `llm.purge_calls`): `beat` restarts,
  which `make deploy` already does. No new `.env` keys: interval (10 min), batch (20), attempt cap
  (3), backoff base (30 min) and retention (90 days) are module constants.
- Merged to `Dev`, deployed to the dev instance, checked against the success criteria in section
  1, then PR to `main`.

## 9. Out of scope

- Classify from title plus lead paragraph (needs text fetched before classify; changes flow and
  cost).
- Per-task token ceilings and `llm.rate_limit`.
- Persist-first with a `documents` table (step 4 of `docs/TARGET_ARCHITECTURE.md`).
- A local relevance model (P5) and Admiralty confidence (P6).
