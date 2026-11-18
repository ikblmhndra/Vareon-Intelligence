# Tweet LLM cost: persist-first tweet jobs, a short tweet prompt, a local tweet gate

Status: draft for review (2026-11-16). One spec, one plan, one PR, one release (next patch after 0.8.17).

## Why

Tweets are now the biggest LLM cost. Prod, read-only, 7 days to 2026-11-16:

| | |
|---|---|
| `classify_tweet` calls | 1,674 |
| tweets stored (`tweets`, all `related_cyber=true`) | 978 |
| prompt tokens per call | ~4,144 (min 3,955, max 6,866) |
| completion tokens per call | ~133 |
| tweet tokens | 7.1 M = **75 %** of all LLM tokens |

Three causes, each fixed by one part of this design:

1. **Classify runs before dedup.** `tweet_alerts._items()` calls `classify()` inside `fetch()`, before the framework
   dedups on `tweet_id`. The search window is twice the schedule interval, so most tweets are classified in two runs (the
   module docstring calls this "harga kecil"). The LLM also runs inside a scraper, which the framework rules otherwise
   forbid (`usage.py` documents it as an accepted exception), and an LLM outage drops tweets from `tweet_alerts`.
2. **Tweets use the article prompt.** `classify()` hard-wires `_PROMPT`, ~115 lines written for article titles, with
   few-shot examples and an 11-field schema. 97 % of a tweet call's tokens are this prompt.
3. **Every tweet goes to the LLM.** The article path skips the LLM for confident titles (P5 gate, live on prod since
   2026-11-11, model #3 at 98.5 % agreement). Tweets have no gate, and no stored verdicts to train one.

The goal is the redesign's goal: the LLM is an assistant, not the pipeline. Success, measured on prod:

- `classify_tweet` calls per day ≈ distinct new tweets per day (no repeat classification).
- Prompt tokens per tweet call ≤ ~1,000.
- Once the tweet gate is on: tweet LLM calls drop by at least half.
- Telegram tweet alerts keep their topics and arrive within ~2 minutes of the scrape in normal operation.
- X Intel keeps its fields (incident flag, victim, countries, industries) for LLM-classified tweets.

## Goals, non-goals, anti-goals

Goals:
- (Part A) Tweets follow persist-first like articles: the scraper stores a job, dedup happens before any LLM call, and
  the LLM runs in the worker behind the existing breaker. LLM outages delay tweets instead of dropping them.
- (Part B) A short tweet-only prompt with its own `PROMPT_VERSION`.
- (Part C) A local relevance gate for tweets that reuses the P5 model, gate and evaluate code, with its own model row,
  its own dataset and its own gate state.

Non-goals:
- Changing which accounts are scraped, the search queries, the schedules, or `route_tweet` topic rules.
- Re-classifying tweets already in `tweets`.
- Fixing `monitor_x` (prod: twitterapi.io HTTP 402 since October; a key/provider decision for the user). It moves to the
  new path like `tweet_alerts` so the code has one tweet path, and it keeps working when its key is fixed.
- Batching several tweets in one LLM call; per-account templated parsing.

Anti-goals (a failure even if the token numbers improve):
- A tweet lost because the LLM was down, or a duplicate Telegram notice for the same tweet and topic.
- The gate silently rejecting tweets: the gate may only skip the LLM for confident **accepts**, as in P5.
- An LLM call inside scraper `fetch()` after this change.

## Constraints from the code (found while reading, 2026-11-16)

- `enrich_jobs.kind` is `String(10)` with `CHECK kind IN ('classify','ttp')`, unique `(kind, url_hash)`; `url` and
  `title` are NOT NULL. `has_classify`, `counts()` and `claim_due` ordering are hard-coded to the two kinds.
  `_finish_classify` ends in `pipeline.complete()`, which persists an article.
- `BREAKER_TASKS = ("classify","ttp")`: `classify_tweet` calls neither trip nor close the breaker today.
- `classify(title, *, task)` has no prompt parameter; the user message is tagged `article_title`.
- `tweets` has no verdict column; rejected tweets are never stored; `TweetRepo.insert` is insert-only (first writer owns
  `source`). X Intel filters/sorts on `confirmed_incident`, `incident_confidence`, `victim_name`, and shows
  `victim_countries` and `industries_impacted`.
- `route_tweet` uses only regex scan signals (`ScoreResult`), never the LLM verdict; it needs `msg_data` (the full
  message), `cve_list`, `related_tech_cve_status`, `report_status`, `ot_status`, `databreach_list`, `zero_day_list`.
  `scan_results` stores most of these but not `related_tech_cve_status` or the message text.
- Notices today: one `NoticeItem` per topic, dedup key `"{tweet_id}:{topic}"` per scraper; `_notice_sink` calls
  `send_alert` and does not swallow errors (at-least-once).
- `relevance_models` has one active model in the whole table (partial unique index on `status`), no kind column. The
  model code (`model.py`, `embedder.py`, `gate.decide`, `evaluate.next_state`, `train.split_holdout/band_metrics`) is
  generic over strings; `dataset.load_examples`, `run_training`, `gate_stats` SQL, the stage cache and the two worker
  tasks are article-only. `CLASSES` is the 3-class tuple.
- The relevance model (sklearn, fastembed) is installed only in the `worker-nlp` image (queue `enrich`). Tweet scrapers
  run on `scrape.api` in `worker`. So the gate must run in the job, not in `fetch()`.
- Tier 1 (`run_tier1`) gives actors/malware, industries and an incident verdict from text, but **no countries**.
- `tests/unit/test_llm_call_sites.py` pins the set of LLM task names.

## Approaches considered

1. **Persist-first tweet jobs in `enrich_jobs` (chosen).** New job kind `tweet`; the scraper yields a job item; the
   worker classifies (gate, then short prompt) and then stores the tweet and sends the notices. Reuses the dispatcher,
   breaker, lease, backoff and Data health. Cost: a migration, a new finish path, notices move from the sink to the
   worker.
2. **Keep classify in `fetch()`, add a verdict cache.** Cache verdicts by `tweet_id` (Redis or a table) and add the
   short prompt. Smaller, but keeps the LLM in the scraper, keeps the outage drop, and cannot host the gate (no model in
   the `worker` image).
3. **Separate `tweet_jobs` table and task.** Clean separation, but duplicates the dispatcher, breaker and Data health
   logic that P7g built.

The user asked for all three parts together, ordered 2 → 1 → 3 (structure, prompt, gate), in one spec and one plan.
Approach 1 is the only one that supports all three.

## Design

### Part A: persist-first tweet jobs

**Scraper side.** `tweet_alerts` and `monitor_x` stop calling `classify()`. They keep their cheap filters (reply/RT,
account filter, funding keyword, "Ransomware Alert:") and the regex scan, then yield one new item per tweet,
`TweetJobItem`, carrying:
- the tweet fields `from_tweet` needs today (id, url, text, author fields, `posted_on`, `lang`, `media_urls`);
- `scan_results` (as stored today) plus the routing inputs not in it (`related_tech_cve_status`; the message text is
  rebuilt in the worker with `build_message`, so it need not be stored);
- `notify: bool` (true for `tweet_alerts`, false for `monitor_x`).

`TweetJobItem.dedup_key()` is the `tweet_id`, so the framework dedups before any job exists. `NoticeItem` is no longer
yielded by `tweet_alerts`. Its `max_items` (40) used to cap notices *after* the LLM said "related"; counting unclassified
job items against it would drop real alerts, so `max_items` for both tweet scrapers becomes 200 job items per run (the
`monitor_x` value; a 1–2 h window of ~10 accounts stays well below it). There is no per-run notice cap in the worker.

**Sink.** `@sink_for(TweetJobItem)`:
- skips the tweet if `tweets` already has the `tweet_id` (already classified by any scraper);
- otherwise `EnrichJobRepo.create(kind="tweet", url=tweet url, url_hash=sha256(canonical url), title=text[:300],
  source=scraper id, scraper_id, posted_on=date, input_text=text, context={tweet fields, scan_results, routing, notify})`;
- on a `(kind,url_hash)` conflict, `notify` becomes the OR of both, so a tweet seen by `monitor_x` first still alerts
  when `tweet_alerts` sees it;
- leases and sends `enrich.llm` at once when the breaker is closed (same `_lease_if_closed` pattern as articles);
- does **not** apply `ensure_enrich_capacity()` backpressure: a tweet job is one small row, and refusing it would either
  age it out of the 1–2 h search window or lose it. The dispatcher's `dispatch_limit` already throttles `enrich.llm`.

**Worker.** `jobs.run_job` gains a `tweet` branch:
1. Already in `tweets` → delete the job (`duplicate`).
2. Part C gate (when a tweet model is active and in `gate` state) may return a verdict without the LLM.
3. Otherwise call the tweet classifier (Part B), LLM call outside a DB session as today.
4. Record the decision in `tweet_verdicts` (below), for every tweet including rejects.
5. `related_cyber=false` → delete the job; nothing else stored (as today).
6. `related_cyber=true` → insert the `tweets` row (same fields as `_tweet_sink` today), delete the job, commit; then,
   if `notify` and the tweet is fresh, rebuild the message with `build_message`, run `route_tweet`, and send one Telegram
   notice per topic.

Errors follow the article job semantics (gateway errors → backoff retry; JSON failures cap at 3 → `failed`; other errors
→ `failed` and the existing failure alert).

**Notice delivery.** Commit first, then send (as `pipeline.complete` does for articles): a crash between commit and send
loses that alert rather than duplicating it. A send error is logged per topic and does not undo the stored tweet.

**Freshness.** Alerts are sent only when the tweet was posted at most 6 hours before the job finishes (my call; the
search window is at most 2 hours, so normal operation is well inside it). Older tweets are still stored for X Intel.

**Breaker and dispatcher.** `classify_tweet` joins `BREAKER_TASKS`. `claim_due` orders `classify`, then `tweet`, then
`ttp` (alerts before TTP backfill). `counts()` and Data health show the `tweet` kind.

**Migration.** `enrich_jobs` CHECK becomes `kind IN ('classify','ttp','tweet')` (fits `String(10)`).

### `tweet_verdicts` table (needed by Part C, written from Part A on)

One row per classified tweet, kept 90 days (purged by the existing maintenance pattern): `tweet_id` (unique), `text`,
`related_cyber` (bool), `source` (`llm` | `gate`), `prompt_version`, `relevance` (JSONB, the gate audit as articles store
it in `raw_enrichment['relevance']`), `created_at`. This is the tweet dataset (labels from `source='llm'` rows only, so
the model never learns from its own output) and the source for tweet gate statistics.

### Part B: short tweet prompt

- New prompt constant `_TWEET_PROMPT` with its own `TWEET_PROMPT_VERSION`, used by a new `classify_tweet(text)` in
  `stages/classify.py` (or `classify(..., prompt=, tag=)`; builder's choice). Task name stays `classify_tweet`, user tag
  `tweet`.
- Target ≤ ~800 prompt tokens. It returns the same JSON keys X Intel uses: `related_cyber`, `confidence`,
  `industries_impacted`, `victim_countries`, `actor_countries`, `confirmed_incident`, `incident_confidence`,
  `incident_indicators`, `victim_name` (the same `ClassifyResult`, other fields default). The relevance criteria are
  rewritten for short posts from curated threat-intel accounts (ransomware leak claims, breach/dump notices, CVE/exploit
  news, threat reports), with a short industry list and at most two examples.
- **Check before release:** an eval command runs the old and the new prompt over the same tweets and reports agreement
  on `related_cyber` and `confirmed_incident` and the token counts. Run on dev over ≥ 300 recent tweets (stored tweets
  plus tweets from a dev dry-run so rejects are included). Ship only with `related_cyber` agreement ≥ 95 %.

### Part C: tweet relevance gate

- `relevance_models` gets `kind` (`article` | `tweet`, default `article`); the partial unique index becomes one active
  model **per kind**. Repo methods (`get_active`, `activate`, `lock`, `set_gate_state`, `gate_stats`) take `kind`; the
  stage cache is keyed by kind. Existing rows become `article`; article behaviour is unchanged.
- Dataset for `tweet`: `tweet_verdicts` rows with `source='llm'`; label `threat_news` when `related_cyber`, else
  `reject`. Two classes: the model, `band_metrics` and the minimum-per-class check work on the classes present for the
  kind (builder chooses how; `CLASSES` stays for articles).
- Same `decide()`: only an in-band `threat_news` (≥ `accept_threshold`) outside the audit sample skips the LLM; out of
  band and audit-sample tweets go to the LLM; rejects always go to the LLM. Same `next_state()` rule (≥ 200 in-band tweets
  over 14 days with ≥ 95 % agreement opens the gate; recent audit agreement < 92 % closes it).
- `relevance.train` and `relevance.evaluate` run for each kind. The tweet model trains only when its dataset meets the
  existing minimums (1,000 examples, 100 per class), so it starts in shadow some time after Part A has collected
  verdicts. Estimate: about 1–2 weeks of prod volume, plus the shadow period.
- A gated tweet gets: `related_cyber=true`, `confidence` from the model, industries and incident from Tier 1
  (`run_tier1(title=text, text=text, victim_name=None)`, incident source "rule" as for gated articles), victim and actor
  countries empty (Tier 1 has none). This is an accepted loss: countries are missing only for gated tweets.
- Data health shows the tweet gate next to the article gate.

### Settings

No new required keys. `RELEVANCE__MODE` governs both kinds. A tweet-only switch is not added (my call: one switch keeps
the ops story the same; `RELEVANCE__MODE=shadow` stops both).

### Release and ops

- Migrations (all additive): `enrich_jobs` kind CHECK; `tweet_verdicts`; `relevance_models.kind` and the per-kind index.
- `docs/prod-upgrade/<version>.md` and the consolidated runbook, as for every release. After deploy: tweet jobs appear in
  Data health and drain; `classify_tweet` calls per day fall to about the distinct tweet count; tokens per call fall to the
  new prompt size; Telegram tweet topics keep receiving alerts.
- Rollback: image rollback restores in-scraper classify; pending `tweet` jobs stay in the table harmlessly (or are
  deleted by a documented one-off).

## Left to the builder

- `classify_tweet` as a sibling function or a parameterised `classify`.
- Exact `TweetJobItem` field layout and the `context` JSON shape.
- How the relevance code handles two classes for tweets.
- The wording of the tweet prompt, within the constraints above and the eval threshold.
- Test layout, following the existing unit/integration split.

## Settled after the builder check

- **Cross-scraper alerts.** `tweet_alerts` already writes `tweets` rows today (since 2026-10-16). If `monitor_x`
  (`notify=false`) stores a tweet first and its job is already finished, a later `tweet_alerts` sighting is skipped and
  does not alert. Accepted: `monitor_x` is down on prod and its accounts barely overlap the alert accounts. No
  "notified" column is added.
- **Prompt eval gate.** If the short prompt misses 95 % `related_cyber` agreement, the prompt is revised until it passes;
  the release waits. No switch back to the long prompt is built.
- **Where notices are sent.** In `enrich.llm` on `worker-nlp`, which already sends article alerts from
  `pipeline.complete` and reads the same `.env`. `enrich.llm` has `max_retries=0`, so a send error cannot cause a Celery
  retry; it is logged per topic.
- **Tweet model data.** The reject rate after the cheap filters is unknown (rejects were never stored). The tweet model
  trains automatically once `tweet_verdicts` meets the existing minimums (1,000 examples, 100 per class); if rejects are
  rare that takes longer than 1–2 weeks, and until then tweets simply use the LLM. Tests use synthetic data.
- **`tweet_verdicts` purge.** Rows older than 90 days are deleted regardless of `source` (~13,000 LLM rows at current
  volume remain, far above the training minimum).
- **Downgrade.** The `enrich_jobs` migration's downgrade deletes `kind='tweet'` rows before restoring the old CHECK;
  the other two downgrades drop the new table/column. Prod rollback stays image-only, as documented in the runbook.

## Calls I made (for review)

- Fields kept from the LLM for tweets: everything X Intel uses today; gated tweets get them from Tier 1 and lose countries.
- Commit then send for notices (at-most-once), like articles.
- Alert freshness limit of 6 hours.
- `notify` merged with OR on job conflicts.
- One `RELEVANCE__MODE` for both kinds.
- `monitor_x` moves to the same path.
