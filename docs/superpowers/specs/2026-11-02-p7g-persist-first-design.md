# P7g: persist-first enrichment (design)

Status: approved in brainstorming 2026-11-01 (design sections 1-4), written 2026-11-02 after P7c
merged (`main` 0b26f7c, migration head `1387fae00908`). Part of release **0.8.11** (no version
bump; see the P7 decomposition in `docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md`
section 0).

## 1. Goal

Take the LLM off the critical path of article enrichment. A gateway outage must mean "fields
arrive later", never "article parked until someone replays it" (`docs/LLM_ASSIST_REDESIGN.md`
section 2, Tier 3 guard rails; `docs/TARGET_ARCHITECTURE.md` section 2 "Persist first, enrich in
steps").

Success criteria:

- After an outage like the ones on dev, **0 articles are left waiting** once the gateway is
  healthy, without anyone pressing Replay.
- During an outage, LLM calls drop to a few canaries instead of every arrival plus every retry.
- An article whose relevance is known without the LLM (Tier 0, story inheritance, relevance gate)
  is stored and alerted immediately; only its LLM TTPs come later.
- A title that genuinely needs the LLM classify waits in an orderly, visible state with no attempt
  cap; an analyst can decide it by hand.

## 2. Evidence (dev 172.25.1.77, read-only, 7 days to 2026-10-31)

| # | Finding |
|---|---------|
| G1 | The free OpenRouter models fail every day about 17:00-24:00 UTC (quota reset at 00 UTC). `llm_calls`: classify 631 `ok` / 4,202 `error` (503) / 39 `empty`; ttp 386 `ok` / 208 `error`. |
| G2 | 99 `rejected_articles` rows with `failure_kind='transient'`, **all** with `auto_replay_count >= 3`: stuck for good. Celery retries (~30 min) plus auto-replay backoff (30/60/120 min) all land inside the same 7-hour outage, so P1 cannot recover this pattern. 29, 35 and 35 rows from the weeks of 12, 19 and 26 Oct. |
| G3 | A TTP failure fails the whole article: `_extract_ttps_or_empty` only swallows `JSONDecodeError`, so a 503 re-runs the task from the start, including fetch and the classify LLM call that already succeeded. |
| G4 | The URL advisory lock (`_known_article`) and the session transaction stay open across the LLM calls (classify latency up to 144 s). |
| G5 | The P5 relevance gate is still in shadow on dev (180 shadow decisions, 0 gated), so every non-Tier-0, non-inherited title needs the LLM there. |

## 3. Decisions (user, 2026-11-01)

| # | Question | Decision |
|---|----------|----------|
| D1 | Alert for an accepted article whose LLM TTPs are pending | Send now with Tier 1 TTPs (explicit/keyword). LLM TTPs reach DB/UI later; no second Telegram message. |
| D2 | Title that needs the LLM classify during an outage | Wait with no attempt cap; re-sent when the breaker allows; visible in the UI with the local model probability; analyst can accept or reject. A late decision alerts only if the article is still fresh (`is_fresh`, P1 rule: posted today or yesterday). |
| D3 | Approach | New work table `enrich_jobs` plus `articles.llm_ttp_status`; readers of `articles` unchanged (approach 1 of 3; "articles-first with a visibility state" and "keep parking, fix recovery" rejected). |
| D4 | Rollback lever | No mode flag, one code path. Rollback = previous image + one-off `python -m cti_enrich.requeue_jobs`. |
| D5 | UI | The Newsroom > Filtered tab "Failed enrichment" is renamed **"Enrichment queue"** and shows `enrich_jobs`; no new tab. |
| D6 | Scope | Token budget, prompt cache and story-level LLM summaries are out of scope. |

## 4. Design

### 4.1 Data model (one additive migration after `1387fae00908`)

`enrich_jobs` holds only LLM work in flight; a row is deleted when its work is done (history lives
in `llm_calls`).

| Column | Type | Meaning |
|--------|------|---------|
| `id` | bigint PK | |
| `kind` | varchar(10), check `classify`/`ttp` | |
| `url`, `url_hash` | text, varchar(64) | unique `(kind, url_hash)` |
| `title`, `source`, `scraper_id`, `posted_on` | as in `rejected_articles` | |
| `article_id` | bigint FK `articles.id` ON DELETE CASCADE, null | set for `ttp` |
| `input_text` | text, null | classify: fetched text, so the pipeline resumes without a second fetch; ttp: the exact text sent to the model (`_ttp_input`), used for the evidence check. `NULL` = run the front of the pipeline first (migrated rows, non-LLM failures). |
| `context` | jsonb not null default `{}` | story link (`story_id`, `rule`, `lead_article_id`, `cve_ids`), relevance result, `content_kind`, `tlp`, `pap` |
| `state` | varchar(10), check `pending`/`failed` | `failed` waits for an analyst |
| `attempts` | int not null default 0 | gateway attempts |
| `json_failures` | smallint not null default 0 | |
| `next_attempt_at` | timestamptz not null default now() | due time and dispatch lease |
| `last_error` | text, null | scrubbed of secrets (`_scrub_secrets`), cut to 300 chars |
| `created_at` | timestamptz not null default now() | |

Index `(state, kind, next_attempt_at)`.

`articles.llm_ttp_status` varchar(10) null, check `pending`/`done`/`skipped`/`failed`. `NULL` for
articles stored before 0.8.11; paths that never call the TTP LLM (Tier 0, inherited, best
practice, empty TTP input) write `skipped`.

### 4.2 Pipeline split (`cti_enrich.pipeline`)

`run_pipeline` becomes two functions that `enrich.article` and `enrich.llm` share:

- `prepare(...) -> Prepared | Duplicate`: normalise title, `_known_article` (URL lock), **also stop
  when a `classify` job exists for the URL**, fetch text, resolve story, then decide relevance
  without the LLM: Tier 0 (`default_relevance="always"`), story inheritance, relevance gate
  (`gated`). `Prepared.classify_result` is `None` when the LLM is needed.
- `complete(prepared, classify_result, *, alert)`: summarise, IOCs, Tier 1, score, routing,
  `persist` or `persist_rejected`, commit, then alert. When the TTP LLM applies (not Tier 0, not
  inherited, not best practice, non-empty TTP input), `persist` is called with
  `llm_ttp_status='pending'` and a `ttp` job is created in the same transaction; otherwise
  `skipped`.

No LLM call happens inside either function. `enrich.article` = `prepare`, then `complete` when the
relevance is known, otherwise insert a `classify` job (text + context) and commit. Shadow and audit
decisions of the relevance gate (P5) still need the LLM verdict, so they become `classify` jobs too.

### 4.3 `enrich.llm(job_id, decision=None)` (queue `enrich`)

1. Load the job; stop if it is gone. Call the LLM **outside any transaction**.
2. `classify`:
   - Re-read `stories.classify` for `context.story_id` first: if the lead was classified meanwhile,
     inherit (`classify_from_story`) without an LLM call.
   - Otherwise `classify(title)` (or the gated/shadow path as today, keeping the relevance audit).
   - `input_text IS NULL`: run `prepare` first (migrated and failed rows).
   - Then open a session, take the URL lock, re-check `_known_article`, and run `complete` with the
     stored text, `alert=is_fresh(posted_on)`. Delete the job in the same transaction.
   - `decision="accept"` (analyst): classify result `related_cyber=True`, audit
     `{"skipped": "analyst"}`, incident verdict and victim from the Tier 1 rule (as for gated
     articles). `decision="reject"`: `persist_rejected` with reason `analyst`. Both feed P5 labels as
     analyst decisions.
3. `ttp`:
   - `extract_ttps(input_text)`, `normalize_ttp_result`, `verify_evidence(input_text)`.
   - Read the article's current `attack-pattern` mentions; keep `analyst` mentions untouched, merge
     the rest with the LLM result by the existing `merge_ttps` rule (explicit > llm > keyword), write
     with `apply_ttps` (P7c), `touch_entity_seen`, then `apply_assessments` (P6 priority counts LLM
     TTPs).
   - `llm_ttp_status='done'`, delete the job. No alert.
4. Failure handling (no Celery retry in `enrich.llm`):
   - Gateway errors (`openai` 5xx, timeout, 429, `EmptyLLMResponse`, 400/401/403/404):
     `attempts+1`, `next_attempt_at = now + min(60 min, 2^attempts min)`, `last_error`. No cap.
   - `JSONDecodeError`: `json_failures+1`; at 3 the job becomes `failed` (a `ttp` job instead
     ends with `llm_ttp_status='failed'` and is deleted: the article keeps its Tier 1 TTPs).
   - Any other exception: `state='failed'`, `last_error`, so bugs do not loop silently.

`enrich.article` keeps Celery retries only for DB and network errors
(`sqlalchemy.exc.OperationalError`/`InterfaceError`, `httpx.TransportError`). Its `on_failure`
records a `failed` `classify` job with `input_text=NULL` instead of a `[enrichment_failed]` row in
`rejected_articles`.

### 4.4 Circuit breaker (pure function, `cti_core.llm.breaker`)

Computed from the latest `llm_calls` rows for tasks `classify` and `ttp`; `error` and `empty`
count as failures. No Redis state and no new setting (module constants, like P1).

- **Closed**: the latest call is `ok`, or fewer than 3 consecutive failures.
- **Open**: n >= 3 consecutive failures and `now < last_failure_at + cooldown`, with
  `cooldown = min(30 min, 2 min * 2^(n-3))`.
- **Half-open**: cooldown elapsed; exactly one job is sent as the canary, and its outcome
  (logged in `llm_calls`) decides the next round.

On a 7-hour dev outage this gives about 15 canary calls instead of the 600-1,500 failed calls a
day seen in G1.

### 4.5 Dispatcher `enrich.llm_dispatch` (beat every minute, queue `maintenance`)

Replaces `enrich.auto_replay` (beat entry removed).

- Pick `pending` jobs with `next_attempt_at <= now`, `classify` before `ttp`, oldest first.
- Closed: up to 20 and at most the remaining room in the `enrich` queue
  (`scraper.enrich_queue_max_depth`, same rule as backpressure). Half-open: 1. Open: 0.
- Claim, commit, then send (P1 pattern): `next_attempt_at = now + 15 min` as a lease, so a crash
  between commit and send cannot cause endless re-sends.
- A newly created job is sent at once when the breaker is closed (normal latency stays seconds).
- Alert (best effort, Redis dedupe, existing `WORKER__ENRICH_FAILURE_ALERT_COOLDOWN_MIN`): "LLM
  gateway down, N articles waiting" when the breaker is open, and one alert when a job turns
  `failed`. Replaces `_alert_enrichment_failure`.

### 4.6 Migration of existing rows

The migration moves every `rejected_articles` row with `failure_kind IS NOT NULL` into
`enrich_jobs` as `kind='classify'`, `input_text=NULL`: `transient`/`config`/`json` as `pending`,
`permanent` as `failed` (reason kept in `last_error`), then deletes those rows. Afterwards
`rejected_articles` holds classification rejects only. `failure_kind`, `auto_replay_count` and
`last_auto_replay_at` become unused (left in place, removal is a later cleanup).
`cti_core.enrich_replay` and `enrich.auto_replay` are removed.

### 4.7 API

- `GET /api/enrich-jobs?kind=classify|ttp&state=pending|failed&page&page_size&search`: title,
  source, posted_on, age, attempts, `last_error`, state, relevance probability from `context`.
- `POST /api/enrich-jobs/{id}/accept` and `/reject` (`manage_sources`, audit log): send
  `enrich.llm(job_id, decision=...)`; `409` for a `ttp` job.
- `POST /api/enrich-jobs/{id}/retry` (`manage_scraper`, audit log): `failed` -> `pending`, due now,
  `json_failures=0`.
- `ArticleOut.llm_ttp_status`.
- `/api/filtered-articles`: `kind=failed` and `POST /{id}/replay` are removed; `kind=unrelated`
  stays. `openapi.json` and `schema.d.ts` regenerated; route permission test updated.
- Data health LLM section: breaker state and until when, pending jobs per kind, failed jobs, oldest
  pending age (replaces `parked`).

### 4.8 Web

- Newsroom > Filtered: the "Failed enrichment" pill becomes **"Enrichment queue"**, backed by
  `/api/enrich-jobs?kind=classify`; rows show state, attempts, age, last error and model
  probability; actions Accept/Reject (`manage_sources`) and Retry for `failed` (`manage_scraper`).
- Article modal: a "LLM TTPs pending" note when `llm_ttp_status='pending'`.
- Data health: breaker and queue figures instead of parked articles.

### 4.9 Rollback (`python -m cti_enrich.requeue_jobs`)

With the previous image running on the new schema (the migration is additive except for the moved
rows): sends every `classify` job to the old `enrich.article` and deletes it; drops `ttp` jobs
(articles keep their Tier 1 TTPs). `--dry-run` prints counts. Documented in the runbook.

## 5. Interaction with other phases

- **P7c** (merged): TTPs are `attack-pattern` mentions; the TTP job writes through
  `apply_ttps`/`touch_entity_seen` exactly like `persist`.
- **P3 stories**: a lead that waits for the LLM leaves `stories.classify` empty, so its follow-ups
  also wait; each follow-up re-checks the story when its job runs and inherits once the lead is
  decided.
- **P5 relevance**: unchanged decisions; LLM verdicts from jobs land in `raw_enrichment` as before,
  so training labels are unaffected. Analyst accept/reject count as analyst decisions.
- **P6**: `apply_assessments` runs at persist and again after the TTP job.

## 6. Testing

- Unit: breaker states and cooldowns; dispatch plan (closed/half-open/open, queue room); each
  `enrich.article` branch with a fake LLM (503 -> classify job, no `rejected_articles` row; accepted
  -> article stored + `ttp` job + alert; Tier 0/inherited -> `skipped`); failure accounting in
  `enrich.llm`.
- Integration (testcontainers): migration moves the four `failure_kind` values; classify job
  accept/reject/late inheritance; TTP job merge keeps analyst and explicit mentions and updates
  priority; duplicate arrival while a job is pending; analyst endpoints; requeue command;
  `test_migrations_match_models`.
- Outage simulation: 30 arrivals with the LLM down produce only canary calls; after recovery all
  jobs drain with no manual action.
- Dev (via `origin/Dev`, one nightly outage): classify `error` calls per day drop from hundreds to
  tens; pending jobs rise and drain after 00 UTC; the 99 migrated rows drain; no new
  `[enrichment_failed]` rows.

## 7. Release (0.8.11)

- `CHANGELOG.md` `## [0.8.11]` entry (Indonesian), `docs/prod-upgrade/0.8.11.md` (eight headings),
  0.8.11 part of `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`, progress blocks in
  `docs/LLM_ASSIST_REDESIGN.md` and `docs/TARGET_ARCHITECTURE.md` (step 1 remaining, step 4).
- No new `.env` keys. Prod runs 0.8.2 and jumps in one deploy: the migration chains after the P7c
  head; parked prod rows (`[enrichment_failed]`) become jobs and drain automatically.

## 8. Known risks

- A title waits for as long as the gateway is down (D2). The Enrichment queue page and the Telegram
  alert make that visible; an analyst can accept or reject.
- `input_text` is stored per pending job (tens of KB each); rows are deleted on completion.
- The breaker looks only at `classify`/`ttp` calls; recap or TA profile failures do not open it.
- After a rollback, pending `ttp` jobs are dropped (Tier 1 TTPs remain).
