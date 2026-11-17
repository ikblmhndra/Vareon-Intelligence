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

Image rollback (`make deploy` restores `:prev` on a failed health check; manual rollback uses the `:prev` images).
Before starting the old image, delete the pending tweet jobs so it never runs one as `classify`:
`DATABASE__SYNC_URL=... uv run python tools/ops/requeue_enrich_jobs.py` (report), then `--apply`. The migrations stay
(additive); do not downgrade the database.

### Known risks

- Tweets answered by the gate have no countries.
- Tweet alerts arrive up to a couple of minutes later than before; a long LLM breaker outage delays them further (tweets
  older than 6 hours are stored without a Telegram alert).
- The short prompt must agree with the old one: the dev agreement result is recorded above before release.
