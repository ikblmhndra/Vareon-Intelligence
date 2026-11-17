# Prod upgrade runbook: 0.8.18 → 0.8.19

Prod (`privy-admin@10.8.20.78`, compose project `niskala-intelligence`, repo `/home/privy-admin/Niskala-Intelligence`)
should run **0.8.16** or later per the older runbooks. **Confirm the running version first** with `GET /api/health`
(field `version`). 0.8.17 and 0.8.18 come first when prod is older: follow their `docs/prod-upgrade/<version>.md` in
order, then this one. Earlier steps stay in `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` and the older runbooks.

One `make deploy` takes prod to 0.8.19: backup, `migrate` (three additive revisions), rebuild, health wait. The checkout
is owned by root, so the user runs it with `sudo`. Read-only SQL runs in a read-only session
(`PGOPTIONS=-c default_transaction_read_only=on`); anything that writes needs the user's approval.

The per-release section below is kept in `docs/prod-upgrade/0.8.19.md` and copied here.

## Order of operations

0. **Confirm the running version** (`GET /api/health`).
1. **Before deploy:** record the `classify_tweet` baseline (query in "Before deploy" below).
2. **`.env`:** no new key.
3. **`make deploy`.**
4. **After deploy:** the 0.8.19 checks below.

Expected `alembic_version` after the deploy: **`a7d3e1b5c9f2`**.

---

## 0.8.19 — tweet classification moves to the enrich queue (short prompt + local gate)

Release: not yet tagged (branch `feat/tweet-llm-cost`; merge to `origin/Dev` for the dev test and the prompt eval,
then PR to `main`). Comes after 0.8.17 and 0.8.18, which are on other branches.

### What changes in prod

- `tweet_alerts_1h`, `tweet_alerts_30m` and `monitor_x` no longer call the LLM in `fetch()`. They store each tweet as
  an `enrich_jobs` row of kind `tweet` (`TweetJobItem`); `enrich.llm` in `worker-nlp` classifies it, stores it in
  `tweets`, records the verdict in `tweet_verdicts` and sends the Telegram alert per topic.
- Tweet alerts now go out from the enrich worker about 2 minutes after the scrape (`enrich.llm_dispatch` runs every
  minute), not inside the scraper.
- `classify_tweet` uses a short dedicated prompt (`TWEET_PROMPT_VERSION`).
- A local relevance gate (kind `tweet`) answers without the LLM once it has a model. It only activates after
  `tweet_verdicts` reaches the training minimums (1,000 examples, 100 per class) and a tweet model is trained.

Why: on prod, 7 days: 1,674 `classify_tweet` calls for 978 stored tweets, about 4,144 prompt tokens per call, about
75 % of all LLM tokens.

### Migrations

Three, all additive, run by the compose `migrate` service: `e3b7c5a9d1f4` (`enrich_jobs` kind `tweet`),
`f4c8a2d6b9e1` (`tweet_verdicts`), `a7d3e1b5c9f2` (`relevance_models.kind`). Expected `alembic_version` after the
deploy: **`a7d3e1b5c9f2`**.

### Settings / .env

None.

### Before deploy

Baseline, read-only:
`SELECT date(at), count(*), round(avg(prompt_tokens)) FROM llm_calls WHERE task='classify_tweet' AND at > now()-interval '3 days' GROUP BY 1 ORDER BY 1;`
Write the numbers down for the after-deploy comparison.

### After deploy

1. `enrich_jobs` of kind `tweet` drain (rows appear and disappear, none pile up):
   `SELECT kind, count(*) FROM enrich_jobs GROUP BY 1;`
2. `classify_tweet` calls per day are about the number of distinct new tweets, and prompt tokens per call are at most
   about 1,000 (was about 4,144):
   `SELECT date(at), count(*), round(avg(prompt_tokens)) FROM llm_calls WHERE task='classify_tweet' AND at > now()-interval '3 days' GROUP BY 1 ORDER BY 1;`
3. `tweet_verdicts` grows:
   `SELECT source, related_cyber, count(*) FROM tweet_verdicts GROUP BY 1,2;`
4. The Telegram tweet topics still receive alerts (about 2 minutes after the tweet).
5. Data health shows the tweet jobs and the "Tweets relevance" block.

### One-off commands

None. Training the tweet relevance model is the usual weekly training once `tweet_verdicts` has enough rows.

Prompt eval on dev: <to be filled after the dev run>

### Rollback

Image rollback: `make deploy` restores the `:prev` images by itself when the health check fails; a manual rollback
starts the `:prev` images. The migrations stay (additive); do not downgrade the database.

Images 0.8.11 to 0.8.18 already have `enrich_jobs`, but they run every job that is not `ttp` as `classify`: a pending
`tweet` job would have its tweet URL fetched and stored as an article. Their `RelevanceModelRepo.get_active` also reads
the one row with `status='active'` without looking at `kind`, so it raises once a tweet model is active next to the
article model. Right after any rollback to an image >= 0.8.11, **including right after an automatic `deploy.sh`
rollback**, run (writes; needs the user's approval):

```sql
DELETE FROM enrich_jobs WHERE kind = 'tweet';
UPDATE relevance_models SET status = 'retired' WHERE kind = 'tweet' AND status = 'active';
```

The deleted tweets are lost (their `scraper_seen` dedup key is already written); that is the accepted cost.
`tools/ops/requeue_enrich_jobs.py` is **not** the tool here: it moves `classify` jobs back to `rejected_articles` and
is only for a rollback to an image without `enrich_jobs` (0.8.10 or older).

### Known risks

- Tweets answered by the gate have no countries.
- Tweet alerts arrive up to a couple of minutes later than before; a long LLM breaker outage delays them further (tweets
  older than 6 hours are stored without a Telegram alert).
- Tweet jobs run as `enrich.llm` on the same `enrich` Celery queue as `enrich.article`, so an article backlog delays
  tweet alerts too. A job not finished within the 15-minute lease is sent again by the dispatcher: the second run costs
  a second LLM call, but the job row lock means only one of them stores the tweet and alerts. Past 6 hours after the
  tweet was posted the alert is dropped (the tweet is still stored).
- `classify_tweet` failures count toward the shared circuit breaker: three consecutive failed tweet calls hold back
  article and TTP jobs too. Data health now includes `classify_tweet` in the LLM status.
- One-off re-alerts at deploy: the new scrapers dedup on the tweet id alone. A tweet the old scrapers rejected (never
  marked seen) or alerted without storing (empty author; seen only per topic) before the deploy, and still inside the
  1 to 2 hour search window, is queued once more: a rejected one is classified again by the short prompt and alerted
  if it now passes, an empty-author one is alerted a second time.
- During `up -d` there is a short window where a new scraper container has written a `tweet` job while the old
  `worker-nlp` (or the old dispatcher) is still running; the old worker would run it as `classify` and store the tweet
  as an article. If that happens, delete those rows by hand (articles whose URL is an `x.com`/`twitter.com` status URL
  created during the deploy minute).
- The short prompt must agree with the old one: the dev agreement result is recorded above before release.
