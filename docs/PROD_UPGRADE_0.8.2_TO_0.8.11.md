# Prod upgrade runbook: 0.8.2 → 0.8.11

Prod (`privy-admin@10.8.20.78`, compose project `niskala-intelligence`, repo `/home/privy-admin/Niskala-Intelligence`) runs
**0.8.2**. One `make deploy` takes it to 0.8.11: it backs up Postgres, runs every migration below in order (`migrate` runs
first), then waits for health. The Deploy workflow is off, so this is a manual run by the user.

The per-release sections below are kept in `docs/prod-upgrade/<version>.md` and concatenated here. Read-only SQL runs in a
read-only session (`PGOPTIONS=-c default_transaction_read_only=on`); anything marked **WRITE** needs the user's approval.
Compose commands differ slightly between sections: use the same compose invocation as `make deploy` on the prod host.

## Order of operations

1. **Before deploy (all read-only):** run every "Before deploy" block below (0.8.4 custom roles, 0.8.5 migration head and
   replay backlog, 0.8.6 baselines and overrides count, 0.8.7 article counts, 0.8.8 ATT&CK dictionary counts, 0.8.9 model
   download reachability, `.env` keys and disk space, 0.8.10 confidence baseline, 0.8.11 IOC baseline and role check, P7g parked-backlog count; P7b only needs a stack-env and consumer-planning check, see its read-only bullet;
   P7c link-table baseline, whitelist review and PIR counts). Write the results down: several
   "After deploy" checks compare against them. These run on 0.8.2, where the IOC tables are still `iocs` and `ioc_sources`;
   after the deploy the same data lives in `indicators` and `indicator_sources` (0.8.11), so the After-deploy queries use
   the new names.
2. **`.env`:** no new required key in any of these releases (0.8.11 adds four optional `INDICATOR__TTL_*_DAYS` keys and the optional `ENTITY__ALIAS_SYNC_ENABLED`, all with defaults; leave them unset). Do **not** copy dev's `RELEVANCE__GATE_MIN_AGREEMENT=0.94` or
   `STORY__EMBEDDING_SIMILARITY=0.8`; leave `RELEVANCE__*` and `STORY__*` unset for the first deploy (see 0.8.7 and 0.8.9).
3. **Make sure the prod LLM gateway works** (model name and credits). Dev's OpenRouter free quota ran out; with a dead
   gateway the 0.8.11 (P7g) breaker keeps the model on one canary per cooldown and the jobs wait (nothing is lost; the
   0.8.5 auto-replay no longer exists in this jump), and 0.8.9's first model may be rejected.
4. **`make deploy`.** The `worker-nlp` build downloads the MiniLM model (~88 MB) from Hugging Face (0.8.9); if that fails
   the deploy aborts before any container changes.
5. **After deploy:** run the "After deploy" blocks in release order. Admin task from 0.8.4: add `manage_cve`/`view_ops` to
   custom roles. Remedy from 0.8.6 (only now, never before): clear machine-written `overrides.confidence_score` if the
   before-count was > 0. For its follow-up recompute, the 0.8.10 section recommends the Celery enqueue over the inline
   `POST /api/articles/confidence/recompute`, which can hit the proxy timeout.
6. **One-off WRITE commands, in this order, after the deploy is healthy (each needs approval, dry-run first):**
   1. 0.8.7 story backfill (`cti_enrich.story_backfill`), bounded with `--since`.
   2. 0.8.8 Tier 1 backfill (`cti_enrich.backfill_tier1`, ~3 s/article; never during a deploy).
   3. 0.8.11 (P7c) ATT&CK sync from the ATT&CK DB page ("Sync All Domains"; brings campaigns and current ATT&CK
      aliases into the entities).
   4. 0.8.11 (P7c) Galaxy alias merge: `python -m cti_core.entity.cli merge-aliases --dry-run > /tmp/galaxy.csv`, the
      user reviews the CSV, then `--apply` (one transaction; on a DB error nothing is written, re-run it). The weekly
      `entity.alias_sync` applies Galaxy merges only after this first `--apply` (code gate); until then it only stores
      snapshots.

   The 0.8.8 actor-name canonicalisation (`cti_enrich.canonicalise_actors`) is **superseded** by the 0.8.11 `entity_model`
   migration and step 4: skip it (on 0.8.11 it prints that and writes nothing).

   P7g needs nothing either: the migration turns the parked `[enrichment_failed]` rows into `enrich_jobs` and
   `enrich.llm_dispatch` drains them once the gateway is healthy (the 0.8.5 steps about replaying them, including
   `make replay-failed-enrichment` and the Newsroom Replay button, do not apply from 0.8.11).

   0.8.9 needs nothing: the first model trains itself within an hour. 0.8.11 P7a and P7b need nothing either (P7b: only the After-deploy token round trip and the nginx check): the first API start
   enqueues `indicator.reconcile_validity` once (backfills `valid_until`; check `job_state['indicator.ttl_fingerprint']`).
   0.8.10 needs nothing either: each API process enqueues
   `confidence.recompute_all` once at start (one or two runs with `WEB_CONCURRENCY=2`; idempotent; P6 scoring for every
   article, overrides kept); check that `credibility is null` reaches 0.
7. **Later, separately:** turn on `STORY__EMBEDDING_SIMILARITY=0.8` only after story dedup is checked on prod (0.8.9).

## Migration chain

| Release | Revision | Down revision | Reversible |
|---|---|---|---|
| 0.8.2 (prod now) | `b7e4c1a9d256` | | |
| 0.8.3, 0.8.4 | none | | |
| 0.8.5 | `c4e7a2b9d1f0` llm_calls + auto-replay columns | `b7e4c1a9d256` | yes |
| 0.8.6 | `d1a5c8e3f2b7` article_cves | `c4e7a2b9d1f0` | table only; deleted CVE IOCs are not restored |
| 0.8.6 | `e7b2d4a9c6f1` canonical IOCs + allowlist seed | `d1a5c8e3f2b7` | **no** (IOC merge) |
| 0.8.6 | `f3c9e1b5a7d2` source_reliability.origin | `e7b2d4a9c6f1` | yes |
| 0.8.7 | `a7d3f1c9e5b2` stories | `f3c9e1b5a7d2` | yes (story data lost) |
| 0.8.8 | `b8e2c4a6d1f3` Tier 1 sources + article_malware | `a7d3f1c9e5b2` | yes (source labels lost) |
| 0.8.9 | `c4f1a9d27e6b` relevance_models | `b8e2c4a6d1f3` | yes |
| 0.8.10 | `d7a3e1b94c52` article assessment columns + source content_kind | `c4f1a9d27e6b` | yes (computed scores lost; old confidence values only from the backup) |
| 0.8.11 | `a9e4c7b1d3f6` `iocs` → `indicators` (+ child tables), lifecycle/marking columns, compatibility views | `d7a3e1b94c52` | yes (views, new columns dropped; tables renamed back; revocations and TLP/PAP lost) |
| 0.8.11 (P7b) | `c4f1a8d27b93` machine_api: `api_tokens`, `indicators.feed_changed_at` + `stix_id`, two feed-clock triggers | `a9e4c7b1d3f6` | yes (tokens lost) |
| 0.8.11 (P7c) | `1387fae00908` entity_model: entities, aliases, relationships, mentions, watches, profiles, reference snapshots; old link/TA tables renamed `_legacy_*` behind writable compatibility views; feed clocks for entities, relationships and stories (4.35 s on a dev copy) | `c4f1a8d27b93` | yes (`_legacy_*` renamed back; everything written after the upgrade lost) |
| 0.8.11 (P7g) | `7a3e91c5d2b4` enrich_jobs + `articles.llm_ttp_status`; parked `rejected_articles` rows move into the queue | `1387fae00908` | yes (schema only; moved rows are not put back: run `tools/ops/requeue_enrich_jobs.py --apply` first) |

Expected `alembic_version` after the deploy: **`7a3e91c5d2b4`**. The only way back past `e7b2d4a9c6f1` is the Postgres
backup `make deploy` writes before migrating.

---

## 0.8.3 — Dashboard, Exec, CVE, Recap and Newsroom numbers match their data

### What changes in prod
- Fixes from the UI-vs-data audit (`docs/UI_DATA_AUDIT.md`): "Incidents only" toggle renamed "Threat news only", open-critical CVE and KEV counts use the CVE backlog definition, MTTA rating "Backlog", trend widgets ignore an unreliable baseline.
- RSS scrapers take the date from the feed (`pubDate`, Atom `published`/`updated`, `dc:date`) instead of the scrape time.
- Names that ATT&CK lists as software (e.g. Cobalt Strike) are no longer stored as threat actors; titles are HTML-entity decoded at ingest.
- An empty recap reply from the model is rejected (HTTP 502) instead of stored.
- Images changed: `api`, `web`, workers.

### Migrations
None.

### Settings / .env
None.

### Before deploy
Nothing specific to this release.

### After deploy
- Dashboard shows the toggle as "Threat news only"; the brief and the KPI cards agree on the incident count.
- New RSS articles carry the feed's publication date: `SELECT source, posted_on, created_at FROM articles ORDER BY created_at DESC LIMIT 10;` (`posted_on` should no longer equal the scrape day for older posts).

### One-off commands
None. Existing articles are **not** corrected: they keep their scrape-time date, any "Cobalt strike" actor tag and their old title.

### Rollback / if it goes wrong
Image rollback only (no schema change).

### Known risks and follow-ups
- Historical rows stay as they are (see above).

---

## 0.8.4 — Permissions enforced per endpoint, no cross-client leaks

### What changes in prod
- Every `/api` endpoint now requires a permission. Endpoints that any logged-in user could call before now answer `403 Missing permission: ...` when the role lacks it.
- New permissions: `manage_cve` (ack, ticket, CVE FP, monitored tech, packages) and `view_ops` (Scrapers, Data health).
- `X-Client-ID` for a client the user does not belong to is rejected with `403` (before: silently replaced by the user's first client).
- PIR/CVE lists in crossref, STIX `pirs` and PIR mindmaps are scoped to the user's client.
- `GET /api/auth/me` returns `permissions`; the web hides buttons the role cannot use.
- Images changed: `api`, `web`.

### Migrations
None. System roles (`superadmin`, `admin`, `analyst`) are updated automatically when `api` starts.

### Settings / .env
None.

### Before deploy
1. List custom roles and their permissions; any role whose users must still ack/ticket CVEs or open Scrapers/Data health needs `manage_cve` / `view_ops` added after deploy:
   ```sql
   SELECT name, permissions FROM roles WHERE NOT is_system ORDER BY name;
   ```
2. List who has which role, to know who will lose access:
   ```sql
   SELECT role_name, count(*) FROM users GROUP BY 1 ORDER BY 2 DESC;
   ```

### After deploy
- Admin → Roles: add `manage_cve` and `view_ops` to the custom roles identified above (write, through the UI).
- `analyst` can no longer send newsletters/CVE emails, generate recap/exec brief/TA profile, edit TA groups/whitelist, sync ATT&CK or edit source reliability. Confirm that matches how prod analysts work; otherwise give those users `admin`.
- Log in as a non-admin user and open Dashboard, Exec, CVE: no unexpected 403 banners.

### One-off commands
None.

### Rollback / if it goes wrong
Image rollback restores open endpoints. Role changes made in Admin stay (harmless on 0.8.3).

### Known risks and follow-ups
- Remaining cross-client reads not fixed in this release: TA profile CVE list, `cve_priority`, `campaign_analysis`, CVE mindmaps.

---

## 0.8.5 — LLM call log, self-healing enrichment, prompt fixes (P0 + P1)

> **In a jump to 0.8.11 the replay half of this section is superseded (P7g).** The auto-replay described here is removed
> in 0.8.11: the migration `7a3e91c5d2b4` turns the parked `[enrichment_failed]` rows into `enrich_jobs`, and
> `enrich.llm_dispatch` drains them automatically behind a circuit breaker. `make replay-failed-enrichment`, `enrich.auto_replay`
> and the Newsroom Replay button no longer exist. Read the steps below as the 0.8.5 history; follow the 0.8.11 P7g bullets.

### What changes in prod
- Every LLM call is logged in `llm_calls` (task, model, prompt version, tokens, latency, status); rows older than 90 days are purged daily.
- Articles parked as `[enrichment_failed]` are replayed automatically every 10 minutes: one canary while the model status is unknown, a batch of up to 20 when healthy, at most 3 attempts with backoff; Telegram alert only for articles posted in the last 24 h.
- Gateway configuration errors (400/401/403/404) park an article at once as `failure_kind='config'` (no 30-minute retry).
- Data health gains an LLM section (status, parked articles, token usage per task).
- Prompt fixes (classify, TTP evidence verified in full text, newsletter metadata, TA profile from ATT&CK, exec brief labels, CVE email computed fields, JSON mode on six calls).
- `ttp` input tokens rise about 3x (TTP reads up to 6,000 characters of text instead of a 2,000-character summary).

### Migrations
- `c4e7a2b9d1f0` (revises `b7e4c1a9d256`, prod's head on 0.8.2): creates `llm_calls`, adds `auto_replay_count` and `last_auto_replay_at` to `rejected_articles`, and backfills old `permanent` rows from BadRequest/NotFound/Authentication/PermissionDenied to `config`. Reversible (downgrade drops the table and columns, sets `config` back to `permanent`). Seconds on dev.

### Settings / .env
None. Two new beat entries (`enrich-auto-replay` every 10 min, `llm-purge-calls` 03:40) — `beat` is restarted by `make deploy`.

### Before deploy
1. Confirm prod's migration head:
   ```sql
   SELECT version_num FROM alembic_version;   -- expect b7e4c1a9d256
   ```
2. Size of the replay backlog that will start replaying after deploy:
   ```sql
   SELECT coalesce(failure_kind,'(rejected)'), count(*) FROM rejected_articles GROUP BY 1 ORDER BY 2 DESC;
   ```
3. Confirm prod's LLM gateway works (model name, quota/credits). On dev the OpenRouter free quota ran out and every call returned 503; auto-replay then stays on one canary per 10 minutes, which is safe but slow.

### After deploy
- `SELECT task, status, count(*) FROM llm_calls WHERE at > now() - interval '1 hour' GROUP BY 1,2;` — rows appear for `classify`/`ttp`; mostly `ok`.
- Worker log shows `auto_replayed ... healthy=False sent=1` on the first run, then `healthy=True sent=<n>` once a call succeeds.
- Data health → LLM section: status OK, parked count falling.
- Parked rows go down over the next hours: rerun Before-deploy query 2.

### One-off commands
None (replay is automatic). Manual Replay in Newsroom → Filtered Articles still works for rows past 3 automatic attempts.

### Rollback / if it goes wrong
Image rollback + `alembic downgrade b7e4c1a9d256` is possible. To stop replays without rolling back, stop `beat` briefly (replays only run from beat).

### Known risks and follow-ups
- If the prod gateway is misconfigured, every enrichment parks as `config`; fix the model/credentials and the replay recovers them.
- Higher `ttp` token use (see above).

---

## 0.8.6 — Structured sources skip the LLM, canonical IOCs, article_cves, deterministic confidence (P2)

### What changes in prod
- `cisa_kev`, `exploitdb`, `cis` (`default_relevance="always"`) skip LLM classify and TTP; their articles are accepted even when the LLM is down.
- IOC values are stored canonical (refanged, lowercase; URL path/query kept); the web shows them defanged.
- The allowlist flags matching IOCs (`auto_suppressed`, reason `allowlist:<type>:<entry> (infrastructure-abuse)`) instead of dropping them; curated seed of 124 domains. Suppressed IOCs leave STIX export, stats, campaigns, recap counts and the FP queue.
- CVEs move from `iocs` (type `cve`) to the new `article_cves` table.
- Article confidence = source Admiralty grade + TTP/actor bonus (no longer the LLM self-rating). Every scraper source gets a `default` grade per `content_kind`; existing grades become `analyst`. Web chip "B2 · 72". **In a jump to 0.8.10 this formula never runs:** 0.8.10 (P6) replaces it, see that section.

### Migrations
- `d1a5c8e3f2b7`: creates `article_cves`, copies every article↔CVE link from `ioc_sources`, deletes `type='cve'` IOCs. Downgrade only drops the table (CVE IOCs are not restored).
- `e7b2d4a9c6f1`: rewrites IOC values to canonical form and **merges duplicates (irreversible)**, canonicalises `threat_feed_entries`, inserts the 124 seed allowlist rows, flags matching IOCs. Downgrade is a no-op.
- `f3c9e1b5a7d2`: `source_reliability_entries.origin` (`default`/`analyst`, CHECK constraint). Reversible.
- All three ran in seconds on dev (~7,500 IOCs, 3,061 CVE IOCs → 4,473 `article_cves` rows, 1,955 defanged values, 73 defang twins merged).
- `make deploy` takes a Postgres backup first; for `e7b2d4a9c6f1` that backup is the only way back.

### Settings / .env
None.

### Before deploy
1. Baseline to compare after deploy (run on 0.8.2, where the tables are still `iocs` and `ioc_sources`):
   ```sql
   SELECT count(distinct (s.article_id, upper(i.value))) FROM iocs i JOIN ioc_sources s ON s.ioc_id=i.id
    WHERE i.type='cve' AND s.article_id IS NOT NULL;                          -- = article_cves rows after deploy
   SELECT type, count(*) FROM iocs GROUP BY 1 ORDER BY 1;
   ```
2. Nested defang values make `canonical()` need several passes (handled, up to 5); expect 0 (on 0.8.2):
   ```sql
   SELECT count(*) FROM iocs WHERE value ~ '\[\[|\(\(|\{\{|\]\]|\)\)';
   ```
3. Confidence overrides (record the number; the fix runs **after** deploy):
   ```sql
   SELECT count(*) FROM articles WHERE overrides ? 'confidence_score';
   ```
4. Source names that differ only in case (the grade lookup picks the analyst row first, but check):
   ```sql
   SELECT lower(source_name), count(*) FROM source_reliability_entries GROUP BY 1 HAVING count(*) > 1;
   ```

### After deploy
- `SELECT version_num FROM alembic_version;` shows the final head of the deploy (0.8.11 chain; `iocs` is now `indicators`, so these queries use the new name), and these return:
  ```sql
  SELECT count(*) FROM indicators WHERE type='cve';                -- 0 (else: DELETE FROM indicators WHERE type = 'cve';)
  SELECT count(*) FROM article_cves;                               -- = Before-deploy query 1
  SELECT count(*) FROM indicators WHERE value ~* '\[\.\]|\(\.\)|\[dot\]|^hxxp|\[@\]|\[:\]';   -- 0
  SELECT count(*) FROM ioc_allowlist_entries WHERE added_by='seed';                    -- 124
  SELECT origin, count(*) FROM source_reliability_entries GROUP BY 1;                  -- ~100 default + existing analyst
  ```
- Worker log has `confidence_recompute_all updated=<n>` once after the first API start (with 0.8.10 the same task runs the P6 scoring, and with `WEB_CONCURRENCY=2` it may appear twice); if not, run `POST /api/articles/confidence/recompute` (admin).
- If Before-deploy query 3 was > 0, only now (0.8.6+ live): `UPDATE articles SET overrides = overrides - 'confidence_score' WHERE overrides ? 'confidence_score';` then `POST /api/articles/confidence/recompute`. On 0.8.5 or older that POST writes an override for every article, so never run it before the upgrade.
- UI: IOC Management shows defanged values and the "Include suppressed" toggle; searching `gofile[.]io` finds `gofile.io` (flagged Suppressed). Dashboard "Perlu dibaca" shows chips like `A1 · 100` / `B2 · 86` (with 0.8.10: `C1 · P131`, see that section). Source reliability lists all sources with `default` labels.
- New `cisa_kev`/`exploitdb`/`cis` articles have `raw_enrichment->'classify'->>'skipped' = 'default_relevance=always'`.

### One-off commands
None beyond the remedy above (needs the user's approval; it is a write).

### Rollback / if it goes wrong
Restore the pre-deploy Postgres backup (the IOC merge and CVE IOC deletion cannot be undone by `alembic downgrade`).

### Known risks and follow-ups
- One legacy `url_with_path` IOC row may stay as that type (seen on dev).
- Suppressed IOCs still get an actionability label.
- Confidence saturates near 100 for B2 sources with a few TTPs; P6 (0.8.10) reworks scoring.
- Campaign CVE lists are capped at 20 per campaign; the visible 20 are now sorted, so a campaign with more CVEs may show a different subset than before.

---

## 0.8.7 — Story dedup at ingest (P3)

### What changes in prod

- New articles are grouped into **stories** at ingest. Keys: CVE IDs (an article with more than 5 CVEs is a roundup and gives no key; ≥ 50% overlap; tie-break = more members, then lowest id), then exact title, then TF-IDF title similarity ≥ 0.5 from a **different** source, with year/month/"report"-style words ignored and a CVE veto on the title rules. A story is matched only if it was last seen ≤ 72 h ago and is ≤ 7 days old.
- Pipeline order changes when `STORY__ENABLED=true` (the default): `fetch_text` now runs **before** classify, so articles that classify rejects are also fetched. Resolve runs in its own short DB session under an advisory lock.
- A follow-up of a story whose `classify` is set **inherits** the lead's classification and **skips both LLM calls** (classify and TTP). It is still a full `articles` row with its own IOCs, CVEs, routing and Telegram alert (alerts stay per article). Tier 0 sources (`cisa_kev`, `exploitdb`, `cis`) never inherit and never fill a story's classify.
- A rejected or parked lead keeps its (empty) story; the new daily beat task `story.purge_empty` (03:50) deletes stories that stay empty for 7 days.
- API: `ArticleOut.story = {id, article_count, source_count}` and `ArticleOut.classify_inherited_from`; `GET /api/articles?story_id=`; Data health LLM section gains "Stories, last 24 hours / 7 days". Web: "+N sumber" badge in the Newsroom front section, story sheet, "Klasifikasi diwarisi dari artikel lead" line in the article modal.

### Migrations (revision ids, reversible or not, rough duration/row counts seen on dev)

- `a7d3f1c9e5b2_stories` (down_revision `f3c9e1b5a7d2`, the 0.8.6 head): creates `stories` (GIN index on `cve_ids`, btree on `last_seen_at`), adds `articles.story_id` (FK `ON DELETE SET NULL`, indexed) and `articles.story_match` (varchar 20). No data copy.
- Dev: ran inside the normal `migrate` step; not timed separately, the whole deploy (build + migrate + health) took about 3 minutes with ~1,470 articles. Expect seconds on prod (DDL plus one index on `articles`).
- Reversible: downgrade drops the two columns and the table (story data is lost). **Chain:** 0.8.8's migration `b8e2c4a6d1f3` has `down_revision = "a7d3f1c9e5b2"`, so in the 0.8.2 → 0.8.10 jump this one must run after 0.8.6's `f3c9e1b5a7d2` and before 0.8.8; downgrading it requires downgrading 0.8.8 first. Do not downgrade; use the setting below.

### Settings / .env (new keys, recommended PROD values, defaults)

All optional; no required key is added. Leave them unset in prod (defaults are what was tested on dev).

| Key | Default | Prod |
|-----|---------|------|
| `STORY__ENABLED` | `true` | unset (on). Kill switch: `false` |
| `STORY__WINDOW_HOURS` | `72` | unset |
| `STORY__MAX_AGE_DAYS` | `7` | unset |
| `STORY__MAX_KEY_CVES` | `5` | unset |
| `STORY__CVE_OVERLAP` | `0.5` | unset |
| `STORY__TITLE_SIMILARITY` | `0.5` | unset |

0.8.9 (P5) adds `STORY__EMBEDDING_SIMILARITY` (default `0.0` = off) to this same block; see the 0.8.9 section. The P3 offline experiment found it safe only at ≥ 0.8.

### Before deploy (read-only checks with expected results)

```bash
ssh -o BatchMode=yes privy-admin@10.8.20.78
Q() { docker exec -e "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=30000" niskala-intelligence-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -A -F " | " -c "$0"' "$1"; }
Q "select to_regclass('stories')"                                  # expect empty (table does not exist yet)
Q "select count(*), min(first_seen_at)::date from articles"        # note the size: sizes the backfill below
Q "select count(*) from articles where first_seen_at > now() - interval '14 days'"
```

### After deploy (checks with expected results: SQL, logs, UI pages)

```bash
docker exec niskala-intelligence-api-1 python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/healthz').read())"   # version of the release you deployed (>= 0.8.7)
docker exec niskala-intelligence-api-1 alembic current               # head of the chain; a7d3f1c9e5b2 must be an ancestor
Q "select count(*) from stories"                                     # grows as new articles arrive
Q "select story_match, count(*) from articles where created_at > now() - interval '6 hours' group by 1"   # new rows have lead/cve/title/title_exact, none NULL
docker compose -p niskala-intelligence exec -T beat python -c "from cti_worker.beat import build_beat_schedule as b; print('story-purge-empty' in b())"   # True
docker compose -p niskala-intelligence logs --since 1h worker-nlp 2>&1 | grep -iE "story|Traceback" | grep -viE "APIStatusError|RateLimit" | tail   # no story errors
```

Inheritance (not proven on dev, whose LLM quota was exhausted; check after the first multi-source wave):

```bash
Q "select count(*) filter (where raw_enrichment->'classify' ? 'inherited_from_story') inherited, count(*) filter (where story_match in ('cve','title','title_exact')) followups from articles where created_at > now() - interval '24 hours'"   # inherited > 0 once LLM works
Q "select a.story_id, count(*) articles, count(*) filter (where not (a.raw_enrichment->'classify' ? 'inherited_from_story') and not (a.raw_enrichment->'classify' ? 'skipped')) llm_classified from articles a where a.created_at > now() - interval '24 hours' and a.story_id is not null group by 1 having count(*) > 2 order by 2 desc limit 10"   # target: llm_classified <= 2 per story
```

UI: Newsroom shows "+N sumber" on a multi-source story and the sheet lists its articles; Data health → LLM shows "Stories, last 24 hours: N new · N follow-ups · N inherited · N LLM calls avoided" (`LLM calls avoided` = inherited × 2).

### One-off commands (backfills etc.: exact command, `--dry-run` first, expected numbers from dev, how long; mark each as needing the user's approval)

**Story backfill — WRITE, needs the user's approval.** Groups articles stored before the deploy; no LLM call, no alert, leaves `stories.classify` NULL (old articles never become inheritance sources). Idempotent (skips articles that already have `story_id`). Needs 0.8.6's `article_cves` (populated by its migration in the same deploy).

```bash
docker compose -p niskala-intelligence exec -T worker-nlp python -m cti_enrich.story_backfill --dry-run --since 2026-09-01   # prints story count, follow-ups, top 10; rolls back
docker compose -p niskala-intelligence exec -T worker-nlp python -m cti_enrich.story_backfill --since 2026-09-01             # the real run
```

- Dev (1,469 articles, all history): 1,295 stories, 174 follow-ups (122 cve, 45 title, 7 title_exact); biggest story 26 articles / 22 sources (PHP2Shell). Dry-run and real run each returned in well under 5 minutes (not timed precisely).
- Prod has more history. The backfill keeps every story in memory and is roughly quadratic; time the `--dry-run` first and use `--since` to bound it. Only the last 7 days matter for live matching; older stories only group the Newsroom/API view.

### Rollback / if it goes wrong

- Behaviour problem (wrong merges, wrong inheritance): set `STORY__ENABLED=false` in prod `.env`, then `docker compose -p niskala-intelligence up -d worker-nlp` (restart). The pipeline returns to the 0.8.6 order; existing `stories` and `story_id` stay but stop growing. API/UI keep working.
- Bad backfill: there is no targeted undo (backfilled and live stories look the same, both can have `classify` NULL). Grouping only affects the Newsroom/API view and live matching for 7 days; if it must go, restore the pre-deploy backup that `make deploy` wrote to `/var/backups/cti` — **WRITE, needs approval** — or accept it and let stories age out.
- `make deploy` auto-rollback restores images only, never the DB; the new columns are nullable and unused by 0.8.2 code, so 0.8.2 images run on the migrated schema.

### Known risks and follow-ups

- **Inheritance precision is unmeasured on live data.** An article that classify would reject can inherit `related_cyber=True` when its title (≥ 0.5, other source) or CVEs match a cyber story, and is then accepted and alerted without an LLM call. Sample `story_match in ('title','title_exact')` inherited follow-ups in the first week; if many are wrong, restrict inheritance to `cve`/`title_exact`.
- Extra fetches: rejected articles are now fetched too (~17% of intake on dev). Sources that block fetches (Bleeping Computer returned 403 to dev) get CVE keys from the title only.
- One extra DB connection per enrich task (the resolve session).
- A follow-up of a story whose lead was Tier 0, or whose lead is still enriching, gets full LLM enrichment (no saving) and then fills the story's classify.
- Depends on 0.8.6 (P2): `article_cves` for the backfill, `ScraperMeta.default_relevance` for the Tier 0 rule. 0.8.9 (P5) changes the resolver (optional embedding rule, off by default) — read its section before turning that on.

---

## 0.8.8 — P4 deterministic Tier 1 extractors (+ historical actor-name canonicalisation)

### What changes in prod

- Every accepted article now runs a deterministic **Tier 1** step (no LLM) after `extract_iocs`, before LLM TTP extraction. LLM classify and LLM TTP still run; Tier 1 complements them.
  - Actors and malware/tools from the **full text** via one dictionary: ATT&CK groups/software + `threat_actor_groups`, minus `ta_whitelist`. Aliases map to the ATT&CK canonical name (stored through `capitalize()`, e.g. "Cozy Bear" -> "Apt29").
  - ATT&CK techniques: explicit `T####` IDs (validated against the catalog) and a keyword map (~60 techniques). Merge per ID: `explicit > llm > keyword`.
  - Industry from a keyword taxonomy, only when the LLM gave nothing but "General".
  - Confirmed-incident rule is recorded in `articles.raw_enrichment['tier1']`; in 0.8.8 alone `confirmed_incident` stays the LLM value. **With 0.8.9 (P5)** the rule becomes live for articles the relevance gate accepts without LLM classify (`incident_source="rule"`, victim from the rule).
- New provenance columns: `article_ttps.source` (+ `evidence`), `article_threat_actors.source`, `article_industries.source`; new table `article_malware`.
- API: `TTP.source/evidence`, `ArticleOut.malware/industry_source`, new `GET /api/articles/{id}/inferred-ttps` (computed on read, nothing stored), `ttp_source` filter on `GET /api/articles` and `GET /api/mitre/heatmap`.
- Web: article modal shows TTP source (ID/KW/LLM), "Malware / Tools", a KW marker on keyword industries and a lazy "Known TTPs of related entities" section.
- Behaviour operators will notice on NEW articles:
  - more articles get actors (full text instead of the sumy summary): some move from "Global Article" to "TA Group Article", and Telegram alerts gain a "Related Threat Actor" line;
  - keyword TTPs appear in the alert TTP line; keyword industries can raise the OT marker;
  - `confidence_score` rises more often (actor bonus; explicit TTPs count; keyword TTPs give no bonus, and recompute uses the same rule);
  - single-token names known only from `threat_actor_groups` need a context word (APT, group, hackers, ransomware, ...): a title "ShinyHunters members ..." alone no longer tags an actor. Common-word names (Castle, Royal, Tor, Equation, ...) also need one. ATT&CK Windows utilities (at, cmd, net, reg, ...) match only as `<name>.exe`;
  - best-practice articles get malware + industry from Tier 1, never actors or TTPs;
  - `threat_actor_groups` / `ta_whitelist` edits reach new articles within 1 hour per worker process (dictionary cache).
- Unchanged: X Intel tweet tagging (`monitor_x`, `tweet_alerts`).
- Existing articles are not touched until the one-off backfill runs (see below).

### Migrations (revision ids, reversible or not, rough duration/row counts seen on dev)

- `b8e2c4a6d1f3_tier1_sources_article_malware`, `down_revision = a7d3f1c9e5b2` (0.8.7 / P3 `stories`). Next in chain: `c4f1a9d27e6b` (0.8.9 / P5 `relevance_models`), then `d7a3e1b94c52` (0.8.10 / P6). In a 0.8.2 -> 0.8.10 jump all of them run in order in one `migrate`.
- Adds `source varchar(10) NOT NULL DEFAULT` to `article_ttps` (`'llm'`), `article_threat_actors` (`'dictionary'`), `article_industries` (`'llm'`); `evidence text NULL` to `article_ttps`; table `article_malware` (FK `articles.id ON DELETE CASCADE`, unique `(article_id, name)`, index on `name`).
- Postgres 16 (`postgres:16-alpine`): `ADD COLUMN ... DEFAULT <constant>` is metadata-only (no table rewrite); brief ACCESS EXCLUSIVE lock per table.
- Dev: ~1,470 articles, ~2,300 TTP rows; the step was not measurable inside the ~2 min deploy (seconds).
- Reversible: `downgrade()` drops the index, `article_malware`, then the columns. Downgrading loses all `source`/`evidence` values and malware rows (Tier 1 TTP/actor/industry rows stay, unlabelled).

### Settings / .env (new keys, recommended PROD values, defaults)

- None. No new `Settings` field, no `.env` change.

### Before deploy (read-only checks with expected results)

Run read-only (`set default_transaction_read_only = on;`):

```sql
-- Tier 1 dictionary inputs. Expect attack_groups > 0 and attack_software > 0 (dev: 197 / 975 / ta_names 3995 / suppressed 2).
-- If they are 0, ATT&CK was never synced on prod: Tier 1 then uses threat_actor_groups only and drops explicit T-IDs. Sync ATT&CK first.
select (select count(*) from attack_groups) groups, (select count(*) from attack_software) software,
       (select count(*) from attack_techniques) techniques, (select count(*) from threat_actor_groups) ta_names,
       (select count(*) from ta_whitelist) suppressed;

-- Baseline for the "after" comparison.
select (select count(*) from articles) articles, (select count(*) from article_ttps) ttps,
       (select count(distinct article_id) from article_threat_actors) arts_with_actor;

-- Alias-form actor names that canonicalise_actors would rewrite (measured 2026-10-25: 7 rows, 6 names). (informational only now: superseded in 0.8.11)
select threat_actor, count(*) from article_threat_actors group by 1 order by 2 desc limit 30;
```

- Chain dependency: 0.8.7 (`a7d3f1c9e5b2`) must be applied before `b8e2c4a6d1f3`; one `make deploy` from 0.8.2 does this in order.

### After deploy (checks with expected results: SQL, logs, UI pages)

```sql
-- Objects exist (alembic head will be the 0.8.11 revision, so check objects, not alembic_version).
select table_name, column_name, column_default from information_schema.columns
 where table_name in ('article_ttps','article_threat_actors','article_industries') and column_name in ('source','evidence');
-- expect 4 rows; defaults 'llm', 'dictionary', 'llm'; evidence has none
select to_regclass('public.article_malware');            -- expect article_malware

-- Existing rows got the server default.
select source, count(*) from article_ttps group by 1;   -- expect only 'llm' until new articles / the backfill arrive

-- New articles get Tier 1 (after a few enrich runs).
select count(*) from articles where raw_enrichment ? 'tier1' and first_seen_at > now() - interval '2 hours';  -- expect > 0
select t.source, count(*) from article_ttps t join articles a on a.id = t.article_id
 where a.first_seen_at > now() - interval '2 hours' group by 1;  -- expect explicit/keyword rows next to llm
```

- Logs: `docker compose logs --since 1h worker-nlp | grep -c tier1_failed` -> expect 0; `tier1_catalog_load_failed` -> expect none.
- UI: Newsroom -> open an article with TTPs: "Source" column with ID/KW/LLM badges, D3FEND column visible, "Malware / Tools" row when present, "Known TTPs of related entities" expands. Check light and dark. (Dev checked at desktop and ~567 px; 375 px not tested.)
- API smoke: `GET /api/articles/{id}/inferred-ttps` -> 200 (list, may be empty); `GET /api/mitre/heatmap?ttp_source=keyword` -> 200.

### One-off commands (backfills etc.: exact command, `--dry-run` first, expected numbers from dev, how long; mark each as needing the user's approval)

Run AFTER the full 0.8.11 deploy is healthy, never during a deploy (a deploy restarts `worker-browser` and kills the run; re-running is safe). Use `worker-browser` for the backfill (Chromium for the `fetch_text` fallback).

1. **Tier 1 backfill — WRITE, needs the user's approval.** Add-only: adds explicit/keyword TTPs whose ID is missing, actors/malware not yet present (skips an actor whose alias form already exists), and keyword industries only when the article's sole industry is "General" (0.8.11 code: only when the article has no sector mention, since "General" is gone). Never touches LLM rows, overrides, `news_type`, confidence or alerts. No LLM calls.

   ```bash
   # dry-run on a small slice first (rolls back)
   docker compose --env-file docker/stack.env --profile app exec -T worker-browser \
     python -m cti_enrich.backfill_tier1 --dry-run --limit 20
   # real run, detached (approval required)
   setsid nohup docker compose --env-file docker/stack.env --profile app exec -T worker-browser \
     python -m cti_enrich.backfill_tier1 --sleep 1 </dev/null > /tmp/backfill_tier1.log 2>&1 &
   tail -9 /tmp/backfill_tier1.log   # summary is printed at the end
   ```

   Dev: dry-run 20 -> +40 TTP, +19 actors, +6 malware. Full run (after a partial first run cut by a redeploy): 1,537 articles scanned, 1,194 texts fetched, 343 failed/empty, 0 errors; +744 TTP, +254 actors, +209 malware/tool, 2 industries replaced; **~1 h 20 min** at `--sleep 1` (~3 s/article). Dev totals afterwards: `article_ttps` explicit 798 / keyword 698 / llm 2,363; `article_malware` 515 rows on 285 articles. Optional `--since YYYY-MM-DD` / `--limit N`.

2. **Actor-name canonicalisation — superseded in 0.8.11 (P7c), skip it.** In 0.8.8 it rewrote pre-0.8.8 alias-form names to the canonical stored form in `article_threat_actors`, `ta_watchlist`, `ta_profiles` and PIR criteria. Since the 0.8.11 migration `entity_model` every alias form resolves to one entity, and `cti-entity merge-aliases` (0.8.11 One-off commands) folds the remaining Galaxy duplicates. On 0.8.11 `python -m cti_enrich.canonicalise_actors [--apply]` only prints that it is superseded, writes nothing and exits 0. Measured in 0.8.8, for reference: dev 4 renamed + 1 merged article rows, 1 watchlist, 1 TA profile ("apt36" -> "Transparent tribe"); prod read-only on 2026-10-25: 7 article rows (6 names) + 1 TA profile.

### Rollback / if it goes wrong

- Code: `deploy.sh` rolls images back to `:prev` when health fails (it never downgrades the DB). The 0.8.8 schema is additive, so older code runs against it.
- A Tier 1 failure never drops an article: `run_tier1` catches everything, logs `tier1_failed` and persists without Tier 1. Persistent `tier1_failed` -> check reads of `attack_*` / `threat_actor_groups`, then redeploy the previous image if needed.
- Bad backfill rows (WRITE, approval required): `delete from article_ttps where source in ('explicit','keyword');` and `delete from article_malware;` remove Tier 1 TTPs/malware only; LLM rows stay. On the 0.8.11 schema both names are compatibility views whose `INSTEAD OF DELETE` trigger removes the matching `entity_mentions` rows. Tier 1 actor rows carry `source='dictionary'` like pre-0.8.8 rows, so they cannot be separated by `source`; use the Postgres backup made by `make deploy` for a full revert.
- Canonicalisation (0.8.8 only) has no undo command: restore from the deploy backup, or reverse it from its printed `old -> new` list. On 0.8.11 it writes nothing.
- Schema: `alembic downgrade a7d3f1c9e5b2` only together with 0.8.7 code and only after downgrading 0.8.9 (`c4f1a9d27e6b` depends on `b8e2c4a6d1f3`).

### Known risks and follow-ups

- Precision (silver standard: 2 LLM labellers, 92% agreement, no human labels): actor dictionary 71% vs LLM-era 70%; TTP explicit 99%, keyword 70% vs LLM 35%; industry keyword 5/5 vs LLM 39%; malware/tool 47% (weakest: generic OS tools, incidental mentions). Expect some "mentioned but not involved" actor/malware tags.
- Leaderboards/PIR/watchlist showed a split actor series until `canonicalise_actors --apply` ran (0.8.8-0.8.10). From 0.8.11 alias forms resolve to one entity, PIR criteria and the watchlist match through aliases, and `cti-entity merge-aliases` folds Galaxy synonyms.
- Fetch failures (~22% on dev, mostly 403/bot-blocked sites): those articles get Tier 1 on title/summary only.
- Interactions in the 0.8.2 -> 0.8.11 chain: 0.8.6 (P2) confidence recompute now counts only `explicit` + `llm` TTPs (in 0.8.10 they count as priority points, and explicit TTPs as an artefact for credibility); 0.8.7 (P3) story follow-ups skip LLM TTP but still get Tier 1; 0.8.9 (P5) depends on Tier 1: for gate-accepted articles (LLM classify skipped, `industries_impacted=[]`) industries come only from the Tier 1 keyword taxonomy and `confirmed_incident`/victim only from the Tier 1 incident rule, whose precision was measured on few cases (rule 2/2 vs LLM 9/24 on dev); expect fewer industries and confirmed incidents on gated articles.
- Article modal at a true 375 px viewport is untested.

---

## 0.8.9 — P5 local relevance model (classify gate) + optional embedding story rule

Release: tag `0.8.9` / Release `v0.8.9`, merge commit `3cedd1a` (PR #78). Spec:
`docs/superpowers/specs/2026-10-25-p5-relevance-model-design.md`. Dev evidence: `docs/LLM_ASSIST_REDESIGN.md`
("P5 evaluation", "P5 on dev").

### What changes in prod

- A local model scores every title (TF-IDF + MiniLM embedding + logistic regression). It has three classes:
  `reject` / `best_practice` / `threat_news`. It runs on the enrichment path, but only where the LLM classify ran
  before: Tier 0 (P2) and story follow-ups (P3) do not call it.
- **Shadow first.** Each decision is written to `raw_enrichment.relevance` on `articles` and `rejected_articles`. The
  LLM classify is still called for every title until the gate opens.
- **Gate (only after it opens).** Titles with `p(threat_news) >= 0.85` skip the LLM classify. Their incident fields
  come from the P4 incident rule (0.8.8). 20% of those titles (chosen deterministically by URL hash) still go to the LLM
  as an audit sample. The LLM TTP extraction still runs on every article.
- **New Celery tasks**, both on the `enrich` queue (worker-nlp):
  - `relevance.evaluate`: hourly, at minute 7.
  - `relevance.train`: weekly, Sunday 02:00 WIB.
- **New table** `relevance_models`, which stores the model artifact and the shared gate state.
- **Optional embedding title rule** for the P3 story resolver, off by default.
- **Data health** gets a new "Relevance model" section, and the stories line gains a "by embedding" count.
- **Telegram ops alerts** (topic `scraper_health`) fire on a gate change, a rejected training run, or a model that
  fails to load.
- **Image change.** `worker-nlp` now bakes the MiniLM model in at build time (see Known risks). The new wheels in the
  `nlp` extra are `fastembed` 0.15 MB, `onnxruntime` 23.8 MB and `tokenizers` 3.4 MB.

### Migrations (revision ids, reversible or not, rough duration/row counts seen on dev)

| Revision | Down revision | What | Reversible | Dev |
|---|---|---|---|---|
| `c4f1a9d27e6b` | `b8e2c4a6d1f3` (0.8.8 head) | `CREATE TABLE relevance_models` + partial unique index `uq_relevance_models_active` (`WHERE status='active'`) | yes (`downgrade` drops index + table; loses trained models only, which retrain) | new empty table, under 1 s; `migrate` exited 0 |

This must be the last revision in the chain. After the deploy, `alembic_version` should read `c4f1a9d27e6b`.

### Settings / .env (new keys, recommended PROD values, defaults)

There are **no new required keys**: every `RELEVANCE__*` key has a default, so a prod `.env` without them still starts.
Values are read at process start, so after changing them restart `worker-nlp` and `beat`.

| Key | Default | Recommended PROD | Note |
|---|---|---|---|
| `RELEVANCE__MODE` | `auto` | **`auto`** (or `shadow` to keep a human switch) | `auto` already starts in shadow and opens the gate only after the criteria below are measured. `shadow` = measure only, never gate. `off` = the model is not called. |
| `RELEVANCE__GATE_MIN_AGREEMENT` | `0.95` | **leave unset (0.95)** | **Dev runs 0.94; that is DEV-ONLY, do not copy it.** It is also the activation threshold for a newly trained model. |
| `RELEVANCE__ACCEPT_THRESHOLD` | `0.85` | leave unset | band = `p(threat_news) >= 0.85` |
| `RELEVANCE__AUDIT_RATE` | `0.2` | leave unset | |
| `RELEVANCE__GATE_MIN_TITLES` / `__GATE_WINDOW_DAYS` | `200` / `14` | leave unset | |
| `RELEVANCE__REVERT_SAMPLES` / `__REVERT_MIN_AGREEMENT` | `50` / `0.92` | leave unset | |
| `RELEVANCE__TRAIN_MIN_EXAMPLES` / `__TRAIN_MIN_PER_CLASS` / `__HOLDOUT_DAYS` / `__MIN_BAND_SHARE` | `1000` / `100` / `14` / `0.2` | leave unset | |
| `STORY__EMBEDDING_SIMILARITY` | `0` (off) | **`0` at first deploy**; `0.8` after P3 story dedup has been checked on prod | Dev runs `0.8`; 1 of its 4 embedding merges so far was a topic-level false merge. Never set it below 0.8. |
| `STORY__ENABLED` | `true` (0.8.7) | `true` | The embedding rule only acts when P3 is on. |

Dev `.env` for reference (backup `~/Vareon-Intelligence/.env.bak-sebelum-0.8.9`): `RELEVANCE__MODE=auto`,
`STORY__ENABLED=true`, `STORY__EMBEDDING_SIMILARITY=0.8`, `RELEVANCE__GATE_MIN_AGREEMENT=0.94` (dev-only).

### Before deploy (read-only checks with expected results)

1. **The prod host can reach the model files, which the build downloads.** Checked OK on 2026-10-26.

   ```bash
   ssh privy-admin@10.8.20.78 'curl -sIL --max-time 20 https://huggingface.co/Qdrant/all-MiniLM-L6-v2-onnx/resolve/d13954661f83248295ba75c1ed411eef3b7b936e/model.onnx | grep -iE "^HTTP|^content-length"'
   ```

   Expected: `HTTP/2 302`, then `HTTP/2 200` with `content-length: 90387630`. If this fails, do not deploy: the
   `worker-nlp` image build will fail.

2. **No stray relevance keys in prod `.env`**, and in particular no `0.94` copied from dev.

   ```bash
   ssh privy-admin@10.8.20.78 'cd /home/privy-admin/Niskala-Intelligence && grep -nE "^(RELEVANCE__|STORY__)" .env || echo none'
   ```

   Expected: `none`, or only the values you chose from the table above.

3. **Enough labels for a first model.** Read-only; run it inside a read-only `psql` session on the prod host:

   ```bash
   ssh privy-admin@10.8.20.78
   docker exec -it -e "PGOPTIONS=-c default_transaction_read_only=on" niskala-intelligence-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
   ```

   ```sql
   select (select count(*) from articles) accepted,
          (select count(*) from articles where news_type = 'Security Technology & Best Practices') best_practice,
          (select count(*) from rejected_articles where coalesce(reason,'') not like '[enrichment_failed]%') llm_rejects;
   ```

   Expected: at least 1,000 in total and at least 100 per class. On 2026-10-25 prod had 1,760 accepted (247 best
   practice) and 370 LLM rejects.

4. **Disk space for the new images.** The `worker-nlp` image grows by the model (about 88 MB) plus `onnxruntime`.

   ```bash
   ssh privy-admin@10.8.20.78 'df -h / /var/lib/docker 2>/dev/null'
   ```

   Expected: a few GB free.

### After deploy (checks with expected results: SQL, logs, UI pages)

Run SQL in the read-only `psql` session shown above.

1. **Version and migration head.**
   - `GET /healthz` returns `"version": "0.8.9"`.
   - `select version_num from alembic_version;` returns `c4f1a9d27e6b`.
2. **First training.** It runs automatically within about an hour (see One-off commands).

   ```sql
   select id, status, gate_state, n_examples, metrics->>'agreement' agr, metrics->>'band_share' band, reason, created_at from relevance_models order by id;
   ```

   - Expected: one row with `status=active` and `gate_state=shadow`.
   - Dev for comparison: 1,799 examples, holdout agreement 0.9489, band share 0.5081. That was rejected at 0.95, and
     activated at the dev-only 0.94.
   - Prod's own labels evaluated offline on 2026-10-26: 14-day holdout band 54.5% with agreement 98.1%; 5-fold CV band
     52.2% with agreement 97.6%. A prod model is expected to activate at 0.95.
   - If the row is `rejected`, its `reason` column gives the cause (see Known risks).
3. **Worker logs.**

   ```bash
   cd /home/privy-admin/Niskala-Intelligence && docker compose -p niskala-intelligence logs worker-nlp --since 2h | grep -E "relevance\.(evaluate|train)\[.*succeeded|relevance_trained|relevance_failed|relevance_model_stale|story_embedding|relevance_alert_failed"
   ```

   Expected:
   - First run: `relevance.evaluate ... {'action': 'retrain', 'reason': 'needs_retrain', 'train_triggered': True}`,
     then `relevance_trained model_id=1 status=active`.
   - Every later hour: `{'action': 'none', ..., 'state': 'shadow', 'band_n': N, 'band_agree': M}`.
   - No `relevance_failed`, `relevance_model_stale` or `relevance_alert_failed` lines.
4. **Decisions are being recorded.**

   ```sql
   select raw_enrichment->'relevance'->>'decision' d, raw_enrichment->'relevance'->>'in_band' b, count(*) from articles where created_at > now() - interval '6 hours' group by 1,2;
   ```

   Expected: rows with decision `shadow`. The only articles without a `relevance` key should be Tier 0
   (`raw_enrichment->'classify' ? 'skipped'`) or story follow-ups (`? 'inherited_from_story'`). Dev after 2 days: 87
   shadow decisions, 34 in band, 34/34 agreeing with the LLM, 0 missing.
5. **UI.** Open Data health and check the "Relevance model" card.
   - It shows the mode, gate state `shadow`, the model's training date, holdout numbers, band titles over 14 days and
     agreement.
   - It has not been checked visually yet: check it in light and dark mode and at 375 px.
6. **Telegram.** A "model rejected" alert means the first model failed its holdout. The absence of an alert says
   nothing; read the `relevance_models` table instead.

### One-off commands (training, backfills etc.: exact command, `--dry-run` first if any, expected numbers from dev, how long; mark each as needing the user's approval)

No backfill is needed: old articles are not scored.

**First training: nothing to run.**
- `relevance.evaluate` (minute 7 of every hour) sees that no model is active and triggers `relevance.train` once.
- A Redis key `relevance:train_trigger` limits this to once per 24 h. So if the first attempt is `skipped` or
  `rejected`, the automatic retry comes up to 24 h later, or at the next Sunday 02:00 WIB run.
- Dev: the train task took 8 s for 1,799 titles. Prod has about 2,100 titles, so expect around 10 s.

**Manual training (NEEDS USER APPROVAL; it writes a `relevance_models` row).** Use this only if the automatic run was
skipped or rejected and you want to retry now.

```bash
cd /home/privy-admin/Niskala-Intelligence
# read-only first: computes everything, writes nothing
docker compose -p niskala-intelligence exec -T worker-nlp python -m cti_enrich.relevance.train --dry-run
# then the real run (write)
docker compose -p niskala-intelligence exec -T worker-nlp python -m cti_enrich.relevance.train
```

Both commands print the outcome as JSON, with the status, holdout `agreement`, `band_share`, confusion matrix and
reason. Dev: `"status": "active"` once run with the dev-only 0.94.

**Switching from shadow to the gate.**
- With `RELEVANCE__MODE=auto` nothing needs to be done. The gate opens by itself when, over the last 14 days, at least
  200 in-band titles have an LLM verdict and exact agreement is at least 95%.
- At prod volume (about 60 accepted articles a day, roughly half in band) expect about 7 days. Dev is at 34 in-band
  titles after 2 days.
- With `RELEVANCE__MODE=shadow`, switching is manual (NEEDS USER APPROVAL):
  1. Confirm on Data health that band titles over 14 days are at least 200 and agreement is at least 95%.
  2. Set `RELEVANCE__MODE=auto` in `.env`.
  3. Restart the workers: `docker compose -p niskala-intelligence --env-file docker/stack.env --profile app up -d worker-nlp beat`.
     Use the same compose invocation that `make deploy` uses.
  4. The next hourly evaluate then opens the gate.

**Turning the embedding story rule on later (NEEDS USER APPROVAL).**
1. Set `STORY__EMBEDDING_SIMILARITY=0.8`.
2. Restart `worker-nlp`.
3. Check the matches:

   ```sql
   select story_match, count(*) from articles where created_at > now() - interval '7 days' group by 1;
   ```

   On dev, 4 matches in 2 days were `title_embedding`, and one of them was wrong.

### Rollback / if it goes wrong

- **Model misbehaves.** Set `RELEVANCE__MODE=off` (the model is not called) or `shadow` (the gate is forced shut; the
  next evaluate writes `gate_state=shadow` and alerts), then restart `worker-nlp` and `beat`. Every article then goes
  through the LLM classify exactly as in 0.8.8.
- **Embedding false merges.** Set `STORY__EMBEDDING_SIMILARITY=0` and restart `worker-nlp`. Articles already merged
  stay merged: they keep `story_match='title_embedding'` and their inherited classify.
- **Code rollback.** `deploy.sh` restores the `:prev` images on failure. 0.8.8 code ignores `relevance_models`, so
  **no DB downgrade is needed**. If you insist on one: `alembic downgrade b8e2c4a6d1f3` (WRITE, needs approval) drops the
  table, which only loses trained models.
- **Failsafe built in.** If the model is missing, stale or fails to load, the code falls back to the LLM classify, and a
  DB error is contained in a savepoint. A failed relevance step never fails an article.

### Known risks and follow-ups

- **Build-time dependency on huggingface.co.**
  - The `worker-nlp` build downloads `Qdrant/all-MiniLM-L6-v2-onnx` at pinned revision
    `d13954661f83248295ba75c1ed411eef3b7b936e` (90,387,630-byte `model.onnx` plus tokenizer and config files) into
    `/opt/fastembed` inside the image. It is about 88 MB on disk and `FASTEMBED_CACHE_PATH=/opt/fastembed`.
  - At runtime `HF_HUB_OFFLINE=1` is set and the model is loaded with `local_files_only`, so nothing is downloaded.
  - If Hugging Face is down or rate-limits the request during `make deploy`, the build fails and the deploy aborts
    before the containers change. Retry later.
- **The first prod model may be rejected.**
  - On dev it scored 94.89%, against a 95% bar. Prod labels are cleaner (mostly `gpt-4o`) and passed offline at 98%.
  - However, prod has also used `openrouter/free` since 2026-10-21, and noisier recent labels pull the 14-day holdout
    down.
  - A rejected model means no model is active, so there are no shadow decisions at all and everything goes to the LLM.
    That is safe, but there is nothing to measure.
  - Do not lower `RELEVANCE__GATE_MIN_AGREEMENT` in prod without an explicit decision; it is also the gate's opening
    threshold.
- **Dependencies on earlier releases in the chain.**
  - Gated articles take `confirmed_incident` and `victim_name` from the 0.8.8 (P4) incident rule and industries from
    P4 `merge_industries`.
  - The embedding rule extends the 0.8.7 (P3) story resolver.
  - Labels exclude failed rows through 0.8.5's `failure_kind` and through the `[enrichment_failed]` reason prefix, which
    covers rows written before 0.8.5.
  - Migration `c4f1a9d27e6b` sits on top of 0.8.8's `b8e2c4a6d1f3`.
  - Nothing in 0.8.9 conflicts with earlier releases.
- **CPU load.** Training runs on the `enrich` queue, about 10 s per week. Each scored title costs about 3 ms of
  embedding on CPU.
- **Follow-ups.**
  - Check the Data health card visually.
  - Watch the first Sunday training.
  - Review dev's 0.94 after a week of shadow data.
  - Watch embedding false merges if the rule is enabled.
  - About 20 deferred minor review findings are listed in `p5-sdd-ledger.md` in the side-session notes folder; none
    blocks the upgrade.

---

## 0.8.10 — P6 Admiralty confidence and priority per article

Release: not yet tagged (branch `claude/p6-admiralty-confidence-9bbec2`, PR to `main` pending). Spec:
`docs/superpowers/specs/2026-10-26-p6-admiralty-confidence-design.md`. Dev evidence: `docs/LLM_ASSIST_REDESIGN.md`
("Built for 0.8.10").

**Not yet run on dev.** P6 has not been deployed to the dev instance, so there are no dev runtime numbers (migration
time, recompute time, live distributions). The numbers below come from the dev snapshot replay
(`tests/fixtures/confidence_replay/dev_2026-10.csv`, 1,546 dev articles, exported 2026-10-26). Anything else is marked
**projection**.

### What changes in prod

- **Article confidence becomes pure Admiralty**, computed per article by `cti_core.confidence.assess`:
  - Reliability A-F is the source grade (`F` if the source has no `source_reliability_entries` row).
  - Credibility 1-6 comes from story corroboration, primary vs aggregator source (`content_kind`) and artefacts (CVE,
    non-suppressed IOC, explicit TTP).
  - `confidence_score` uses the STIX 2.1 Admiralty scale averaged over both halves, so it is always **10-90**. Before:
    the LLM self-rating on 0.8.2, the source grade + bonus on 0.8.6-0.8.9 (many at 100).
- **New stored `priority_score`** (confidence + incident/KEV/PoC/TTP/actor/corroboration points, uncapped) drives
  `sort=priority`. The dashboard "Perlu dibaca" and the Newsroom front section show **one article per story**.
- **Interaction with 0.8.6 in the 0.8.2 jump.** The 0.8.6 source-grade + bonus formula never runs on prod. Each API process
  enqueues `confidence.recompute_all` once at start (condition: new default grades inserted **or** any article with
  `credibility IS NULL`), and that task now runs `assess`. `lifespan` runs in every uvicorn process and the API image
  sets `WEB_CONCURRENCY=2`, so a normal deploy may enqueue it twice. The task is idempotent: the second pass is extra load,
  not a fault.
- **Overrides.** An article whose `overrides` has `confidence_score` keeps that confidence, and its credibility and
  priority are still computed. `overrides.credibility` is new (`PUT /api/articles/{id}/credibility`, `manage_intel`).
- **New beat entries**, both on the `maintenance` queue (`worker`); beat restarts on deploy:
  - `confidence-refresh-stories`: every 10 minutes.
  - `confidence-recompute-all`: daily 03:20.
- **New API:** `GET /api/sr/review`, `POST /api/sr/entries/{id}/confirm` (`manage_sources`). `ArticleOut.admiralty_code`
  is now the article's code, plus `reliability_grade`, `credibility`, `priority_score` and `score_reasons`.
- **Web:** chip `C1 · P131` on the dashboard, the Newsroom front section and list, and the article modal ("Why this
  grade", credibility override). Source reliability gets a "Needs review" tab.

### Migrations (revision ids, reversible or not, rough duration/row counts seen on dev)

| Revision | Down revision | What | Reversible | Dev |
|---|---|---|---|---|
| `d7a3e1b94c52` | `c4f1a9d27e6b` (0.8.9 head) | `articles`: nullable `reliability_grade varchar(1)`, `credibility smallint`, `priority_score smallint`; `score_reasons jsonb NOT NULL DEFAULT '{}'`; check `ck_articles_credibility_range` (1-6); index `ix_articles_priority_score (priority_score DESC NULLS LAST)`. `source_reliability_entries.content_kind varchar(20)` nullable. No data backfill. | yes (`downgrade` drops all of it; computed scores are lost and recomputed on the next upgrade) | not run yet. **Projection:** seconds; nullable `ADD COLUMN` and a constant-default jsonb column are metadata-only, the index and the check constraint scan `articles` once |

This must be the last revision in the chain. After the deploy, `alembic_version` should read `d7a3e1b94c52`.

### Settings / .env (new keys, recommended PROD values, defaults)

None. `git diff origin/main -- .env.example .env.prod.template packages/cti-core/src/cti_core/config.py` is empty for
this release. Nothing to set on the prod host.

### Before deploy (read-only checks with expected results)

Open the read-only session:

```bash
ssh privy-admin@10.8.20.78
docker exec -it -e "PGOPTIONS=-c default_transaction_read_only=on" niskala-intelligence-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

1. **P6 columns do not exist yet.** Expected: 0 rows.

   ```sql
   select column_name from information_schema.columns
   where table_name = 'articles'
     and column_name in ('reliability_grade', 'credibility', 'priority_score', 'score_reasons');
   ```

2. **Baseline** (write the numbers down; After deploy compares against them).

   ```sql
   select count(*) articles,
          count(*) filter (where confidence_score = 100) at_100,
          count(*) filter (where overrides ? 'confidence_score') analyst_confidence
   from articles;
   ```

   `analyst_confidence` is the number of articles that keep their confidence after the recompute (it equals 0.8.6's
   Before-deploy query 3). If the 0.8.6 remedy clears those overrides after deploy, its follow-up recompute gives them
   the computed confidence too. For reference, pre-P6 dev had 245 articles at exactly 100.

### After deploy (checks with expected results: SQL, logs, UI pages)

Run SQL in the read-only `psql` session shown above.

1. **Version and migration head.**
   - `GET /healthz` returns `"version": "0.8.10"`.
   - `select version_num from alembic_version;` returns `d7a3e1b94c52`.
2. **The bootstrap enqueued the recompute and a worker ran it.**

   ```bash
   cd /home/privy-admin/Niskala-Intelligence && docker compose -p niskala-intelligence logs api --since 30m | grep -E "recompute_all_enqueue_failed|api_startup_done"
   cd /home/privy-admin/Niskala-Intelligence && docker compose -p niskala-intelligence logs worker --since 30m | grep -E "confidence_recompute_all|confidence\.recompute_all"
   ```

   Expected: `api_startup_done` (one per API process) and **no** `recompute_all_enqueue_failed`; one or two
   `confidence_recompute_all` lines in the worker log (one enqueue per API process, `WEB_CONCURRENCY=2`) once the tasks
   finish. Two lines are normal: the task is idempotent.
3. **Every article assessed.** Expected: `unassessed = 0` once the task finished.

   ```sql
   select count(*) filter (where credibility is null) unassessed, count(*) total from articles;
   ```

4. **Code distribution.** Expected (**projection** from the dev replay): several codes (11 on dev), none dominant. `F6`
   appears only for sources with no grade row.

   ```sql
   select reliability_grade || credibility code, count(*) from articles group by 1 order by 2 desc;
   ```

5. **Priority spread and confidence range.** Expected (**projection** from the dev replay): the most common
   `priority_score` holds at most ~20% of articles (16.9% on dev); without an analyst override, confidence is between
   10 and 90 and nothing is at 100.

   ```sql
   select priority_score, count(*), round(100.0 * count(*) / sum(count(*)) over (), 1) pct
   from articles group by 1 order by 2 desc limit 5;

   select min(confidence_score), max(confidence_score),
          count(*) filter (where confidence_score = 100) at_100
   from articles where not overrides ? 'confidence_score';
   ```

6. **`content_kind` filled from the scraper registry.** Expected: most rows non-NULL; NULL only for non-scraper sources
   (for example CYFIRMA).

   ```sql
   select content_kind, count(*) from source_reliability_entries group by 1 order by 2 desc;
   ```

7. **Story refresh is running** (after 10+ minutes). Expected: a `confidence_refresh_stories` line every 10 minutes, no
   errors.

   ```bash
   cd /home/privy-admin/Niskala-Intelligence && docker compose -p niskala-intelligence logs worker --since 30m | grep -i refresh_stories
   ```

8. **UI** (light and dark):
   - Dashboard "Perlu dibaca": one article per story, chips like `C1 · P131`, reasons in the tooltip.
   - Newsroom front section and list rows: same chip.
   - Article modal: "Why this grade" section; credibility override select for `manage_intel` users.
   - Intelligence > Source reliability > "Needs review" (`manage_sources`): default grades with 30-day statistics and a
     suggested grade.

### One-off commands (recompute/backfills: exact command, `--dry-run` first, expected numbers from dev, how long; mark each as needing the user's approval)

Normally **nothing to run**: the API start enqueues `confidence.recompute_all` by itself. Run the command below only if
After deploy check 2 shows `recompute_all_enqueue_failed` or check 3 stays above 0.

There is **no `--dry-run`** for the recompute (it is idempotent and respects analyst overrides). Read-only preview: After
deploy check 3.

**Manual recompute (NEEDS USER APPROVAL; WRITE: rewrites confidence/credibility/priority on every article).** It
enqueues the same task the bootstrap sends; a `worker` runs it, committing per batch of 500.

```bash
cd /home/privy-admin/Niskala-Intelligence
docker compose -p niskala-intelligence exec -T api python -c "from cti_core.celery_client import send_recompute_all; send_recompute_all()"
```

Alternative: `POST /api/articles/confidence/recompute` as a `manage_intel` user (audit-logged). It runs **inside the API
request**, so on a large table it can hit the proxy timeout; prefer the task.

Expected: `unassessed` goes to 0. Duration: not measured on dev. **Projection:** a few minutes for a few thousand
articles (pages of 500, one facts query per page).

### Rollback / if it goes wrong

- **Code rollback.** `deploy.sh` restores the `:prev` images on failure and never downgrades the DB. 0.8.9 code ignores
  the new columns (nullable or defaulted), so **no DB downgrade is needed**.
- **DB downgrade** (WRITE, needs approval, only after the app is back on 0.8.9): `alembic downgrade c4f1a9d27e6b`. It
  drops the P6 columns, the index and `content_kind`.
- **Old confidence values are not restored** by any rollback: the recompute rewrote them. If needed, take them from the
  Postgres backup `make deploy` writes before migrating.
- **Recompute stuck or failing:** check the `worker` log for `confidence`; re-run the manual recompute once the cause is
  fixed (idempotent).

### Known risks and follow-ups

- **Priority query cost.** `sort=priority` collapses per story with `row_number()` over the filtered set. It was not
  measured on prod-sized data; if "Perlu dibaca" feels slow, run `EXPLAIN (ANALYZE, BUFFERS)` on the dashboard query in
  the read-only session.
- **Refresh watermark edge.** `confidence.refresh_stories` advances its Redis watermark
  (`cti:confidence:refresh_stories:watermark`) only after a successful run, using the timestamp taken before the query. A
  story commit in flight across that boundary can be missed; the daily `recompute_all` (03:20) catches it. Older story
  members can be up to 10 minutes stale.
- **API start scan.** Every API start runs `exists (... credibility is null)` on `articles`. It is cheap once every row
  is assessed (the first match ends it), but scans the table while rows stay NULL.
- **Lower confidence downstream.** Values drop to 10-90. The newsletter ranking awards confidence points only above 50
  (fewer articles get them, intended), and Splunk/STIX consumers see lower `confidence` values. Tell consumers before
  the deploy.
- **Follow-ups:** record the live distribution (After deploy checks 4-5) in `docs/LLM_ASSIST_REDESIGN.md`; review the
  "Needs review" suggestions with an analyst.

---

## 0.8.11 — P7a indicator lifecycle and TLP/PAP (`iocs` becomes `indicators`), P7b machine API, P7c-1 entity model, P7c-2 entity web, P7f PIR and own-asset relevance, P7g persist-first enrichment

Release: not yet tagged (branch `nameless/p7-cti-model-165075`, merge to `origin/Dev` for the dev test, then PR to `main`).
Spec: `docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md`. Progress record:
`docs/LLM_ASSIST_REDESIGN.md` ("Built for 0.8.11").

**Dev result (2026-10-29, `origin/Dev` `27fe2a8`, deploy from 0.8.10).** `make deploy` finished all seven steps and every
container came up healthy; `/healthz` reports 0.8.11 and `alembic_version` is `a9e4c7b1d3f6` (P7b was not part of that test). Before deploy (on 0.8.10):
5,469 IOCs, 29 allowlisted, 6,334 source rows, 0 feedback rows; role `analyst` (2 users) had no `manage_ioc` (granted by a follow-up commit on the same branch). After deploy,
read-only: `indicators` 5,469 = `iocs` view 5,469; `indicator_sources` 6,334; state 5,283 active / 157 expired /
29 allowlisted / 0 revoked; 0 non-hash rows with `valid_until` NULL (1,727 hashes NULL by design); `valid_until -
last_seen_at` is exactly 30 days for `ip` and 90 days for `domain`, `url`, `url_with_path`, `email`; the fingerprint is in
`job_state`; every row `tlp = pap = clear`. The API start enqueued the reconcile twice (two uvicorn processes): the first
run filled 3,742 rows in 0.1 s, the second reported `skipped`. The UI was checked on a local stack (light/dark, 375 px,
analyst vs superadmin), not on dev (the dev certificate is not trusted by the checking browser). Remaining
**projections** below are prod-specific.

### What changes in prod

- **Table rename (instant, ids and rows kept).** `iocs` → `indicators`; `ioc_sources`, `ioc_tags`, `ioc_threat_actors`,
  `ioc_feedback` → `indicator_sources`, `indicator_tags`, `indicator_threat_actors`, `indicator_feedback`; their `ioc_id`
  column → `indicator_id`. Sequences, constraints and indexes are renamed with them. `ioc_allowlist_entries` keeps its name.
  The `/api/iocs` routes do not change.
- **Compatibility views.** The migration creates five views with the old names (`iocs`, `ioc_sources`, `ioc_tags`,
  `ioc_threat_actors`, `ioc_feedback`; `indicator_id AS ioc_id`) so old SQL keeps working. They are **deprecated compatibility views (writable; do not use in new code)**: old code
  writes through them. A later release drops them; do not point new queries at them.
- **Lifecycle columns on `indicators`.** `valid_from` (NOT NULL, backfilled from `first_seen_at`, server default `now()`),
  `valid_until`, `revoked_at`, `revoked_by`, `tlp`, `pap` (both with CHECK constraints), plus an index on `valid_until`.
  **State is computed, never stored**: revoked (`revoked_at` set), allowlisted (`auto_suppressed`), expired
  (`valid_until` in the past) or active.
- **Expiry by type.** IP 30 days, domain 90, URL 90, email 90, hashes never expire. Set on ingest; existing rows get their
  `valid_until` from the reconcile task (next bullet), so right after the migration non-hash indicators read as
  non-expiring until it has run.
- **Reconcile task.** New Celery task `indicator.reconcile_validity` (`maintenance` queue, picked up by `worker`) and beat
  entry `indicator-reconcile-validity` (daily 04:15; beat restarts on deploy). The API `lifespan` enqueues it only when
  `job_state['indicator.ttl_fingerprint']` is missing or differs from the current TTL settings, so it runs **once right
  after the first 0.8.11 start** (which backfills `valid_until`) and again whenever a TTL setting changes. It is
  idempotent; with `WEB_CONCURRENCY=2` it can be enqueued twice and the second run is a no-op.
- **Behaviour users will notice.**
  - `POST /api/iocs/{id}/feedback` now needs `manage_ioc`. The built-in `analyst` role gains `manage_ioc` in this
    release, so `analyst`, `admin` and `superadmin` keep TP/FP; analysts can now also delete IOCs and edit the allowlist,
    tags and threat-actor links. Custom roles without `manage_ioc` lose the buttons (hidden through `useCan("manage_ioc")`).
  - **FP revokes** the indicator: it leaves the STIX export, IOC stats, dashboard counts, campaigns, recap counts and the
    provider-enrichment queue, and it no longer counts as IOC/artefact evidence in the P6 assessment credibility and the
    source review (the P6 effect lands on the next recompute of the affected articles). **TP restores** it.
  - New `PATCH /api/iocs/{id}/marking` sets TLP/PAP.
  - The IOC page shows the indicator state and TLP/PAP.
  - The STIX IOC export carries `valid_until` and TLP 2.0 marking definitions, and leaves revoked indicators out.
- **Backups.** `tools/ops/pg_backup.py` verifies `KEY_TABLES` containing both `iocs` and `indicators`; a table that does
  not exist yet is skipped, so the pre-migration backup (taken by `make deploy`) checks `iocs` and later ones check
  `indicators`.

- **P7b machine API (0.8.11, second part).** Read-only, token-only access for SIEM/TIP clients, vendor-neutral
  (no Splunk-specific connector):
  - **API tokens.** New table `api_tokens` (hashed, shown once at creation, optional expiry, `max_tlp`, scope
    `indicators:read`). Admins manage them in the *API tokens* section of the Admin page (`/admin/users`), permission
    `manage_api_tokens`; the admin routes are `/api/api-tokens` and stay behind the web proxy.
  - **REST feed** `GET /api/v2/indicators` (cursor on a feed clock, filters, TLP capped per token).
  - **TAXII 2.1 server** at `/taxii2/` (API root `/taxii2/api/`, one collection
    `6f0e1a52-6a43-4f0b-9b8e-2a7c1d9e4b10`). Basic auth with any user name and the token as password, or Bearer. Malformed
    parameters return 400. Revoked and allowlisted indicators stay in the feed with `revoked: true`.
  - **Feed clock.** `indicators.feed_changed_at` (default `clock_timestamp()`, indexed with `id`) is maintained by two Postgres
    triggers (`trg_indicators_feed_bump`, `trg_indicator_tags_feed_bump`), not by application code, so every write path
    (including old code through the `iocs` compatibility view) moves it. Confidence, actionability, enrichment and
    `updated_at` do not.
  - **STIX ids.** `indicators.stix_id` (uuid, unique) stores `uuid5(NAMESPACE_DNS, "<type>:<value>")` with no
    lowercasing. The snapshot export (`/api/stix/iocs`) and the threat-actor bundles now use the same ids, so the
    `indicator--...` id **changes once** for values with uppercase letters or surrounding whitespace. `created` and
    `modified` are now stable (row `created_at` / `feed_changed_at`, millisecond precision). No TAXII subscriber exists
    yet, so nothing downstream sees the one-time change.
  - **nginx.** The edge now forwards `/taxii2/` and `/api/v2/` to `api:8000` (the only two paths that skip `web`); every
    other API path is still unreachable from outside. The image `cti-nginx:1` is built from
    `docker/nginx.Dockerfile` with the template baked in, so a template change needs the image rebuilt: `make deploy`
    does this (`dc build` then `dc up -d` recreates `nginx` because its image changed). If the deploy is run with a
    stale image or nginx was not recreated, the paths answer from `web` (a 404 page), not from the API: see
    After deploy check P7b-1.

- **P7c-1 entity model (0.8.11, third part; backend only, the web pages follow in P7c-2).** One id per actor, malware,
  tool, technique, CVE, campaign, sector, country and ransomware victim. Spec:
  `docs/superpowers/specs/2026-10-29-p7c-entity-model-design.md`.
  - **New tables.** `entities` (STIX types `intrusion-set`, `malware`, `tool`, `attack-pattern`, `vulnerability`,
    `campaign`, `identity` (sectors with `identity_class = 'class'`, ransomware victims `organization`) and `location`;
    `merged_into_id` marks a merged tombstone, `suppressed` replaces the TA whitelist), `entity_aliases` (unique per type
    and normalised alias), `relationships` (STIX SROs with `provenance` `attack`/`analyst`/`ransomware`, `confidence`,
    `revoked_at`), `entity_mentions` (one table for every article, indicator and CVE link, with `method`,
    `matched_alias`, `role`, `evidence`), `entity_watches` (per client), `entity_profiles` (LLM actor profile) and
    `reference_snapshots` (stored Galaxy copies). `stories` gains `feed_changed_at` and `stix_id`.
  - **Old link tables become compatibility views.** `article_threat_actors`, `article_malware`, `article_ttps`,
    `article_cves`, `article_countries`, `article_industries`, `indicator_threat_actors`, `cve_threat_actors`, `cve_ttps`,
    `ta_watchlist`, `ta_profiles` and `ta_whitelist` are renamed `_legacy_<name>` (kept for audit and a manual undo until
    the release after 0.8.11) and replaced by views with the old columns. The views old code writes have `INSTEAD OF`
    triggers that resolve names through the SQL function `entity_resolve` (same rules as the Python resolver), so
    0.8.2 and 0.8.10 code write the same rows as new code. The P7a view `ioc_threat_actors` now reads mentions too. They
    are **deprecated compatibility views (writable; do not use in new code)**, dropped in the first release after 0.8.11.
  - **Writers.** Enrichment persist, the Tier 1 dictionary (built from the aliases of live entities plus the
    `threat_actor_groups` names that are not aliases yet), ATT&CK sync (upserts entities, aliases and relationships,
    including **campaigns**), the ransomware sink (victims plus `targets`/`located-at` relationships) and IOC
    threat-actor tags all write entities and mentions.
  - **Readers.** Every v1 endpoint reads mentions. Response shapes do not change; names are entity names.
  - **Entity API** `/api/entities` and `/api/relationships` (web JWT, behind the web proxy). New permission
    `manage_entities` for `admin` and `analyst` (granted when `api` starts); reads need `view_ta`, watch `manage_pir`,
    profiles `manage_intel`. Merge, split, suppress and analyst relationships are audit-logged. The web pages that use it arrive in
    P7c-2 (below).
  - **Machine API.** New token scope `intel:read`; `GET /api/v2/entities`, `GET /api/v2/relationships` and a second
    TAXII collection `intel` (`c0b7e3d4-2f5a-4e91-8a6d-5b3c9f1e7a20`, entities, relationships, one `report` per story,
    indicators). Existing tokens keep `indicators:read` only. The Admin scope selector arrives in P7c-2 (below).
  - **Weekly Galaxy sync.** Task `entity.alias_sync` (`maintenance` queue, Sunday 05:00 UTC; beat restarts on deploy)
    fetches the three MISP Galaxy files, rejects a broken file or one that shrank by more than 20 %, stores the copy in
    `reference_snapshots` and runs the Galaxy merge in apply mode. **Gate:** it applies merges only after a manual
    `cti-entity merge-aliases --apply` has run once (an `entity_merge` audit row by `system:galaxy` exists); until then
    it only stores the snapshots and logs `galaxy_merge_gate_closed`, so the first Sunday after the deploy cannot merge
    before the dry-run CSV is reviewed (One-off command 3).
  - **Behaviour users will notice (deliberate, spec R4).**
    - Aliases of one actor or malware count as one: dashboards, leaderboards, PIR results, recaps, newsletter and the
      weekly TA trend report. Watchlist rows "apt36" and "Transparent tribe" become one watched entity.
    - `industry_unspecified` (`GET /api/articles/dashboard`) now counts articles **with no sector mention**; before it counted articles
      labelled "General". The "General" label is dropped by the migration, so the number rises.
    - Industry values are sector display names: "Financial Services" for "Finance & Insurance"; "Cloud Services" and
      "Information Technology & Software" both show "Technology".
    - Suppressed (whitelisted) actors are hidden everywhere.
    - Whitelisting a name (TA Room "delete group" or a seed whitelist row) suppresses the **whole entity**: every alias
      and every past mention is hidden (kept, so unsuppress restores them).
    - PIR actor criteria are still stored as names but match through aliases ("apt36" matches "Transparent Tribe").
    - `python -m cti_enrich.canonicalise_actors` (0.8.8 one-off) is superseded: it prints that and writes nothing.

- **P7c-2 entity web (0.8.11, fourth part; web plus small API additions, no migration, no new `.env` key).** The entity
  pages replace TA Room and ATT&CK DB. Spec addendum: `docs/superpowers/specs/2026-11-01-p7c2-entity-web-design.md`.
  - **New pages.** `/intelligence/entities` (tabs per type, alias search, Watched, suppressed, mention trend, New entity,
    Navigator layer, and the ATT&CK sync card on the Techniques tab) and `/intelligence/entities/[id]` (hero with KPIs;
    Overview with the LLM profile, a relationships preview and "Often mentioned together"; Relationships with Make
    relationship and Revoke; Stories, Indicators, CVEs, Timeline and ATT&CK tabs; actions Edit, Aliases, Merge with
    preview, Split with Undo merge, and Suppress). An id that was merged redirects to the surviving entity.
  - **Retired pages (permanent redirects).** `/intelligence/threat-actor-room` goes to the Entities Actors tab and
    `/intelligence/attack-db` to the Techniques tab. Bookmarks keep working.
  - **Removed endpoints (nothing in the web or the tests calls them any more).** `GET/POST /api/ta/groups`,
    `DELETE /api/ta/groups/{group_id}`, `GET /api/ta/whitelist`, `DELETE /api/ta/whitelist/{name}`,
    `GET/POST /api/ta/watchlist`, `DELETE /api/ta/watchlist/{name}`, `GET /api/ta/{actor}/timeline`,
    `GET /api/ta/profile/{name}`, `POST /api/ta/profile/generate`, and `GET /api/attack/techniques`, `/techniques/{attack_id}`,
    `/tactics`, `/tactics/distinct`, `/mitigations`, `/groups`, `/groups/{group_id}`, `/software`, `/software/{software_id}`.
    Kept: `/api/ta/stats`, `/api/ta/watchlist-names`, `/api/ta/watchlist/navigator-layer`, `/api/attack/status`,
    `/api/attack/sync`, `/api/attack/sync/{domain_key}`, `/api/attack/navigator-layer`. Check that no external script
    still calls a removed route (they now return 404/405); use `/api/entities` instead.
  - **API additions.** `GET /api/entities/resolve` (alias, then external id, then a name fallback; follows merges).
    `GET /api/entities` accepts a comma-separated `type` and `identity_class`; `EntityDetail` has `merged_from`. Entity ids
    were added to `ArticleOut.entities`, inferred TTPs, trending and spikes (`entity_id`), and the MITRE heatmap
    (`row_ids`, `ttps[].entity_id`). Existing fields are unchanged.
  - **Entity chips.** Every actor, malware, tool, technique, CVE, sector and country name in the web (Newsroom,
    dashboard, Exec, risk matrix, early warning, MITRE, IOC, CVE, recap, newsletter, campaign clusters, diamond model,
    kill chain, geopolitical, PIR list) is a chip that opens the entity page. Two behaviours differ from before: the Exec
    "Critical CVE" feed links the CVE to its entity page instead of `/cve`; on the dashboard CVE card and the TA
    leaderboard the chip opens the entity page while the bar or row keeps its old navigation.
  - **PIR `malware` criterion.** New criterion that matches malware and tool entities anywhere in the article's mentions
    (not only the title). The PIR form uses entity autocomplete (the matched alias is shown; free text is still allowed;
    country criteria are stored as ISO codes). PIR cross-reference (`crossref`) still matches PIRs by actor only.
  - **Admin > API tokens.** Scope checkboxes `indicators:read` and `intel:read` (the console workaround of P7c-7 is no
    longer needed).

- **P7g: persist-first enrichment (the LLM leaves the critical path).** Spec
  `docs/superpowers/specs/2026-11-02-p7g-persist-first-design.md`.
  - **New table `enrich_jobs`** holds only LLM work in flight (`kind` `classify` = a title that needs the model's relevance
    verdict, `ttp` = LLM TTP extraction for an article that is already stored; `state` `pending` or `failed`). A row is deleted
    when its work is done; call history stays in `llm_calls`. New column `articles.llm_ttp_status` (`pending`, `done`,
    `skipped`, `failed`; NULL for articles stored before 0.8.11).
  - **Articles whose relevance is known without the LLM** (Tier 0 sources, story inheritance, relevance gate) are stored and
    alerted at once; only their LLM TTPs arrive later (a `ttp` job). A title that needs the classify verdict waits as a
    `classify` job with no attempt cap, and an analyst can decide it by hand.
  - **New tasks:** `enrich.llm` (queue `enrich`, runs one job) and `enrich.llm_dispatch` (queue `maintenance`, every minute:
    sends due jobs, up to 20 per round and no more than the free room in the `enrich` queue, `classify` before `ttp`, 15
    minute lease). **Removed:** `enrich.auto_replay` (its beat entry), `cti_core.enrich_replay`,
    `tools/ops/replay_failed_enrichment.py` with `make replay-failed-enrichment`, the `send_enrich_task` helper,
    `POST /api/filtered-articles/{id}/replay` and `kind=failed`. `enrich.article` keeps Celery retries only for DB and
    network errors.
  - **Circuit breaker** (`cti_core.llm.breaker`, computed from `llm_calls` for tasks `classify`/`ttp`; no Redis state, no
    setting): opens after 3 consecutive failures, cooldown `min(30 min, 2 min * 2^(n-3))`, then half-open lets exactly one
    canary job through. During an outage the model sees a few canaries instead of every arrival plus every retry.
  - **Failure handling in `enrich.llm`:** gateway errors (5xx, timeout, 429, empty reply, 400/401/403/404) and DB/network
    errors reschedule the job with backoff `min(60 min, 2^attempts min)`, no cap. Broken JSON three times or any other
    exception turns the job `failed` (waits for an analyst); a `ttp` job that fails ends with `llm_ttp_status='failed'` and
    the article keeps its Tier 1 TTPs. A `ttp` job never rewrites analyst or legacy TTP mentions.
  - **Alerts** reuse `WORKER__ENRICH_FAILURE_ALERT_COOLDOWN_MIN`: "LLM gateway down, N waiting" fires only while jobs are
    waiting, plus one alert when a job turns `failed` (permanent `enrich.article` failures included).
  - **API:** `GET /api/enrich-jobs` (list; `kind`, `state`, `search`), `POST /api/enrich-jobs/{id}/accept` and `/reject`
    (`manage_sources`), `POST /api/enrich-jobs/{id}/retry` (`manage_scraper`); `ArticleOut.llm_ttp_status`. Data health: the
    LLM `parked` block became `queue` (breaker state, retry time, pending per kind, failed, oldest pending); the failure
    figures are now a snapshot of failed jobs by job creation time. The daily report's "scraped" total no longer includes
    failed items; pending and failed are separate snapshot lines.
  - **Web:** the Newsroom pill "Failed enrichment" is now "Enrichment queue" (Accept, Reject, Retry); the article modal shows
    "LLM TTPs pending"; Data health shows the breaker and the queue.
  - **Existing parked rows become jobs.** On prod (0.8.2 onward) the `[enrichment_failed]` rows in `rejected_articles` are moved
    into `enrich_jobs` by the migration and drain by themselves once the gateway is healthy: no Replay, no
    `make replay-failed-enrichment`. The 0.8.5 auto-replay steps above are history for the jump: from 0.8.11 they no longer
    apply.
- **P7f: PIR and own-asset relevance in the priority score.** `articles.priority_score` gains two signals computed by the
  same P6 path (`confidence.assess`) at persist, story refresh, the daily recompute and the manual recompute.
  `pir_match`: the article matches an active PIR (same filters and date window as the PIR page); points by the best
  matching PIR only, P1 20, P2 15, P3 10, P4 5 (unknown priority counts as P4), never summed. `own_asset` (flat 15): the
  article title mentions an active techstack name (whole word) or the article mentions a CVE with a non-false-positive
  `cve_tracker` row whose `tech` matches an active techstack name of the same client. Body text is not searched. A PIR with
  malformed criteria, or with no criteria list at all, is ignored (this also applies to the PIR Telegram alert and the
  `.docx` export, where a PIR with only malformed criteria now counts as "no criteria").
  - **Global score, per-client explanation (D1).** `priority_score` stays one global number: a match against any client's
    PIR or techstack raises it. `score_reasons` stores `pir` (`id`, `title`, `priority`, `client_id`) and `own_asset`
    (`name`, `client_id`, at most 5), and the API returns only the entries of the requesting client (client id removed).
    The article list, detail and credibility endpoints now read `X-Client-ID` (an unassigned client id gets 403, as the
    dashboard endpoints already do; the web proxy sends it). The `priority` list (points) is not filtered, so another
    client can see "PIR match +15" without the PIR behind it.
  - **Recompute on edit.** Creating, updating or deleting a PIR, and creating, updating or deleting a techstack entry,
    adding or removing a target, or toggling `active`, enqueues `confidence.recompute_all` after commit (a failed enqueue
    is logged as `recompute_all_enqueue_failed` and the request still succeeds). Exposure and hosting edits do not.
  - **UI.** The grade tooltip ("Why this grade") shows "PIR match" and "own asset" points, the matched PIR titles with
    priority, and the matched tech names.

### Migrations (revision ids, reversible or not, rough duration/row counts seen on dev)

| Revision | Down revision | What | Reversible | Dev |
|---|---|---|---|---|
| `a9e4c7b1d3f6` (`iocs_to_indicators`) | `d7a3e1b94c52` (0.8.10 head) | Renames the five tables, `ioc_id` → `indicator_id`, sequences, constraints and indexes; adds `valid_from` (NOT NULL, backfilled from `first_seen_at`, default `now()`), `valid_until`, `revoked_at`, `revoked_by`, `tlp`, `pap` (CHECKs `ck_indicators_tlp`, `ck_indicators_pap`) and index `ix_indicators_valid_until`; creates the five compatibility views | yes: `downgrade` drops the views, drops the new columns, then reverses the renames. The migration up/down tests cover it (ids and child rows identical; `iocs` is a table again) | not run on dev yet. On a fresh DB the full chain to `a9e4c7b1d3f6` ran locally. **Projection:** seconds; renames are metadata-only, the `valid_from` backfill and the new index scan `indicators` once (about 5,500 rows on dev) |

`a9e4c7b1d3f6` is the P7a step; the final head is the P7b revision below. The P7a revision is no longer the last in the chain. The prod jump
is 0.8.2 → 0.8.11 in one `make deploy`, so this runs right after `d7a3e1b94c52` in the same `migrate` step.

**P7b:** `c4f1a8d27b93` (`machine_api`), down revision `a9e4c7b1d3f6`. It creates `api_tokens` (unique `token_hash`,
CHECK on `max_tlp`), adds `indicators.feed_changed_at` (backfilled from `greatest(created_at, revoked_at)`) and
`indicators.stix_id` (backfilled in Python in batches of 1,000, then made unique), the index
`ix_indicators_feed_changed_at_id`, and the two trigger functions (created after the backfill so it does not move the
clock). Reversible: `downgrade` drops the triggers, functions, index, columns and table. Not run on prod yet.
**Projection:** seconds (one pass over `indicators`, about 5,500 rows on dev). It is the P7b step; the last revision in
the chain is the P7c revision below.

**P7c:** `1387fae00908` (`entity_model`), down revision `c4f1a8d27b93`. It sets `lock_timeout = '10s'` first (a stuck
lock fails the `migrate` step fast instead of hanging the deploy) and locks the twelve old link/TA tables in `EXCLUSIVE`
mode (reads go on; writes by the still-running 0.8.2 workers wait until the migration commits instead of landing in a
table that was already copied), then, in pure set-based SQL with no network: creates
the seven tables, the SQL resolver functions (`entity_resolve` and helpers), backfills entities, aliases, relationships
and mentions from the ATT&CK tables (`attack_*`), `threat_actor_groups`, the sector vocabulary (34 sectors), the ISO
country list (249), CVEs, ransomware groups and victims, every old link table and the TA watchlist, profiles and
whitelist; then renames the old tables to `_legacy_*`, creates the compatibility views and the feed-clock triggers,
and runs `ANALYZE` on the new tables.
**This is the last revision in the chain: after the deploy `alembic_version` should read `1387fae00908`.**

Reversible: `downgrade` drops the triggers, views, functions and new tables and renames `_legacy_*` back. Rows written
after the upgrade (through the views or the new tables: new mentions, entities, merges, watches, profiles) are lost; the
old tables come back as they were at upgrade time.

**Measured on a copy of dev (2026-11-01).** Read-only `pg_dump --no-owner -Fc` of dev (`c4f1a8d27b93`, database
745 MB, 1,797 articles, 1,626 stories) restored into the local `qacve` Postgres 16, then `time alembic upgrade head`:
**4.35 s wall** for the whole revision, no error, no lock wait. **Projection for prod:** seconds; the SQL is set-based and
scales with the link-table rows, which prod's Before-deploy check P7c-1 counts. Counts before (old tables) and after:

| Old table (before) | Rows | After |
|---|---|---|
| `article_threat_actors` | 772 (316 distinct names) | 772 `intrusion-set` mentions on 316 entities |
| `article_malware` | 558 (155 names) | 358 `malware` + 200 `tool` mentions |
| `article_ttps` | 4,096 (456 ids) | 4,096 `attack-pattern` mentions |
| `article_cves` | 4,887 (3,298 CVEs) | 4,887 `vulnerability` mentions |
| `article_countries` | 965 | 965 `location` mentions |
| `article_industries` | 2,551 (1,005 of them "General") | 1,541 sector mentions (General dropped; 5 pairs of labels on one article collapsed into one sector) |
| `ta_watchlist` | 6 | 5 `entity_watches` ("apt36" and "Transparent tribe" are one entity) |
| `ta_profiles` / `ta_whitelist` | 6 / 2 | 6 `entity_profiles` / 2 suppressed entities |
| `indicator_threat_actors`, `cve_threat_actors`, `cve_ttps` | 0 | 0 |

Entities after the migration: `attack-pattern` 961, `intrusion-set` 515 (197 ATT&CK, 318 legacy, 2 suppressed),
`malware` 877, `tool` 97, `vulnerability` 3,802, `identity` 1,498 (34 sectors, 6 legacy sector labels, 1,458 ransomware
victims), `location` 249, `campaign` 0 (campaigns come from the next ATT&CK sync). Aliases 8,452 (2,559 `attack`,
5,893 `legacy`). Relationships 22,556 (`attack` `uses` 19,295 and `subtechnique-of` 553, `ransomware` `targets` 1,461 and
`located-at` 1,247). Mentions 12,819, **0 orphans**; every compatibility view returns the same count as its legacy
table except `article_industries` (General dropped) and `ta_watchlist` (collapse).

- **P7g: `7a3e91c5d2b4`** `enrich_jobs` (revises `1387fae00908`): creates `enrich_jobs` (unique `(kind, url_hash)`, CHECKs on
  `kind` and `state`, index `(state, kind, next_attempt_at)`) and `articles.llm_ttp_status` (CHECK), then moves every
  `rejected_articles` row with `failure_kind IS NOT NULL` into `enrich_jobs` as `classify` with `input_text` NULL
  (`transient`, `config`, `json` become `pending`; `permanent` becomes `failed` with the reason in `last_error`) and deletes
  those rows. `failure_kind`, `auto_replay_count` and `last_auto_replay_at` stay in place, unused. Downgrade drops the table
  and column; moved rows are **not** put back by the downgrade: use `tools/ops/requeue_enrich_jobs.py` first (see Rollback).
  Expected `alembic_version` after the P7g deploy: **`7a3e91c5d2b4`**.

**P7f adds no migration.** `score_reasons` is JSONB; the new keys `pir` and `own_asset` need no schema change.

### Settings / .env (new keys, recommended PROD values, defaults)

Four **optional** keys. All have defaults, so **prod needs no `.env` change** and the app starts without them:

| Key | Default | Meaning |
|---|---|---|
| `INDICATOR__TTL_IP_DAYS` | `30` | IP indicator lifetime |
| `INDICATOR__TTL_DOMAIN_DAYS` | `90` | Domain lifetime |
| `INDICATOR__TTL_URL_DAYS` | `90` | URL lifetime |
| `INDICATOR__TTL_EMAIL_DAYS` | `90` | Email lifetime |

Leave them unset for the first deploy. Changing one later takes effect after the API restarts (the fingerprint changes,
which enqueues the reconcile task) and needs the worker restarted too, since settings are read at start.
`.env.example` and `.env.prod.template` already list the keys.

**P7b adds no `.env` key.** The token hash needs no secret; nothing to set on the prod host before merging.

**P7c adds no required `.env` key.** One optional key with a default: `ENTITY__ALIAS_SYNC_ENABLED` (default `true`;
`false` stops the weekly Galaxy sync). Leave it unset. `.env.example` and `.env.prod.template` list it commented out.

P7g adds **no `.env` key and no setting** (breaker constants and the dispatcher batch are module constants; the alert reuses
`WORKER__ENRICH_FAILURE_ALERT_COOLDOWN_MIN`). Beat gains `enrich-llm-dispatch` (every minute) and loses `enrich-auto-replay`;
`make deploy` restarts `beat`. No version bump: 0.8.11 already exists.

**P7f adds no `.env` key.** Nothing to set on the prod host before merging.

### Before deploy (read-only checks with expected results)

Open the read-only session:

```bash
ssh privy-admin@10.8.20.78
docker exec -it -e "PGOPTIONS=-c default_transaction_read_only=on" niskala-intelligence-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

1. **Baseline of the IOC table (on 0.8.2: the table is still `iocs`).** Write the numbers down; After deploy compares
   against them. The prod baseline is **unknown**: read it now.

   ```sql
   SELECT count(*) AS iocs_total,
          count(*) FILTER (WHERE auto_suppressed) AS allowlisted
   FROM iocs;
   ```

   After deploy, `indicators` must have the same total, and `allowlisted` must match.
   For reference, dev (0.8.9/0.8.10 data, read-only, 2026-10-28): 5,281 active / 157 expired / 29 allowlisted / 0 revoked
   (plus IOCs added since). "Expired" there is a projection of the TTL rule on `last_seen_at`; prod will show 0 expired
   until the reconcile task has run.

2. **Who loses the TP/FP buttons.** Only custom roles: the built-in `analyst` role gains `manage_ioc` when `api` starts,
   and `admin`/`superadmin` already have it. Roles are stored in `roles.permissions` (JSONB list), so list the roles that
   can see IOCs but not manage them, and the users on them (on 0.8.2 the built-in `analyst` still shows here; ignore it):

   ```sql
   SELECT r.name, r.is_system, count(u.id) AS users
   FROM roles r LEFT JOIN users u ON u.role_name = r.name
   WHERE r.permissions ? 'view_ioc' AND NOT r.permissions ? 'manage_ioc'
   GROUP BY 1, 2 ORDER BY 1;
   ```

3. **External readers of `iocs`.** Anything outside the app that names `iocs` (hand-run SQL, a BI dashboard, a Splunk DB
   Connect input) keeps working through the compatibility views but should be moved to `indicators` before the views are
   dropped. List them now.

**P7b (read-only):** nothing to run against the database beyond P7a check 1. Confirm the stack env is the prod one
(`docker/stack.env`, `NGINX_HTTPS_PORT`): the machine API is reachable on the same HTTPS port as the UI. Decide who will
consume the feed (host, TLS trust of the self-signed certificate, TLP ceiling) before creating tokens.

**P7c (read-only, on 0.8.2; `article_malware` and `article_cves` do not exist there yet, 0.8.6/0.8.8 create them).**

- **P7c-1. Link-table baseline.** Write the numbers down; After deploy check P7c-2 compares against them.

  ```sql
  SELECT 'article_threat_actors' AS t, count(*), count(DISTINCT lower(threat_actor)) AS distinct_names FROM article_threat_actors
  UNION ALL SELECT 'article_ttps', count(*), count(DISTINCT ttp_id) FROM article_ttps
  UNION ALL SELECT 'article_countries', count(*), count(DISTINCT country_code) FROM article_countries
  UNION ALL SELECT 'article_industries', count(*), count(*) FILTER (WHERE industry = 'General') FROM article_industries
  UNION ALL SELECT 'ta_watchlist', count(*), count(DISTINCT lower(name)) FROM ta_watchlist
  UNION ALL SELECT 'ta_profiles', count(*), 0 FROM ta_profiles
  UNION ALL SELECT 'ta_whitelist', count(*), 0 FROM ta_whitelist;
  ```

  For `article_industries` the third column is the number of "General" rows (they are dropped by the migration).
  Dev copy for reference (`count` / third column): `article_threat_actors` 772 / 316 distinct names, `article_ttps`
  4,096 / 456 distinct ids, `article_countries` 965 rows / 86 distinct codes, `article_industries` 2,551 / 1,005
  "General", `ta_watchlist` 6 / 6 distinct names, `ta_profiles` 6 / 0, `ta_whitelist` 2 / 0.
- **P7c-2. Whitelisted names.** After the deploy a whitelist row suppresses the **whole entity** it resolves to,
  aliases included. Read the list and look for a real actor name or an alias of one (for example a common word that is
  also an ATT&CK alias); such a row would hide that actor everywhere.

  ```sql
  SELECT name, added_date FROM ta_whitelist ORDER BY name;
  ```

  Dev has 2 rows. If a row looks wrong, note it; after the deploy an analyst restores it with Unsuppress on the entity page (Entities > suppressed) or sends `PATCH /api/entities/{id}` with `{"suppressed": false}` (WRITE, needs approval), rather than
  editing SQL.
- **P7c-3. PIR baseline (UI).** Open the PIR page and note the result counts of the PIRs that have actor criteria; After
  deploy check P7c-6 compares them (they may rise: aliases now match).

- **P7g-1. Size of the parked backlog** (read-only, on 0.8.2/0.8.10). These rows become jobs after the deploy:
  ```sql
  SELECT coalesce(failure_kind,'(rejected)') AS kind, count(*) FROM rejected_articles GROUP BY 1 ORDER BY 2 DESC;
  ```
  Write the numbers down: After deploy P7g-2 compares them. Expected `jobs pending` = `transient` + `config` + `json`, `jobs failed`
  = `permanent`; `(rejected)` rows stay where they are.
- **P7g-2. The gateway must work before the deploy.** The backlog starts draining on the first healthy call. With a dead
  gateway nothing is lost: the breaker stays on one canary per cooldown and the jobs wait.
- **P7f-1. How much data the new signals can use** (read-only, expected: a handful of rows; dev has 1 client, 1 active PIR
  and 35 active techstack entries). If a client has no active PIR and no active techstack, P7f changes nothing for it.

  ```sql
  SELECT client_id, priority, count(*) FROM pir_requirements WHERE status = 'active' GROUP BY 1, 2 ORDER BY 1, 2;
  SELECT client_id, count(*) FROM techstack_entries WHERE active GROUP BY 1 ORDER BY 1;
  ```

  Note the numbers; After deploy check P7f-1 compares against them. More than one client with its own PIRs means the
  global score (D1) will mix their priorities, see Known risks P7f-R1.

### After deploy (checks with expected results: SQL, logs, UI pages)

Run SQL in the read-only `psql` session shown above.

1. **Version and migration head.**
   - `GET /healthz` returns `"version": "0.8.11"`.
   - `select version_num from alembic_version;` returns `1387fae00908` (P7c head; `a9e4c7b1d3f6` and `c4f1a8d27b93` are
     the P7a and P7b steps).
2. **The reconcile task ran.**

   ```bash
   cd /home/privy-admin/Niskala-Intelligence && docker compose -p niskala-intelligence logs api --since 30m | grep -E "reconcile_validity_enqueue_failed|api_startup_done"
   cd /home/privy-admin/Niskala-Intelligence && docker compose -p niskala-intelligence logs worker --since 30m | grep -E "indicator_validity_reconciled|indicator\.reconcile_validity"
   ```

   Expected: `api_startup_done` and **no** `reconcile_validity_enqueue_failed`; one `indicator_validity_reconciled` line
   in the worker log (a second, from the second API process, is normal).
3. **The TTL fingerprint is stored.** Expected: one non-empty row.

   ```sql
   SELECT value FROM job_state WHERE key = 'indicator.ttl_fingerprint';
   ```

4. **State distribution.** Expected: totals equal Before deploy check 1; `revoked` is 0; `allowlisted` equals the
   Before-deploy `allowlisted` count; `expired` is above 0 only after the reconcile task finished (**projection**: the
   share of IP indicators not seen for 30 days and domains/URLs/emails not seen for 90 days, similar to dev's 157 of
   about 5,500).

   ```sql
   SELECT CASE WHEN revoked_at IS NOT NULL THEN 'revoked'
               WHEN auto_suppressed THEN 'allowlisted'
               WHEN valid_until < now() THEN 'expired'
               ELSE 'active' END AS state,
          count(*)
   FROM indicators GROUP BY 1;
   ```

5. **Compatibility view works and equals the table.** Expected: both numbers equal.

   ```sql
   SELECT count(*) FROM iocs;
   SELECT count(*) FROM indicators;
   SELECT count(*) FROM ioc_sources;   -- equals indicator_sources
   SELECT count(*) FROM indicator_sources;
   ```

6. **Every row has a start, and non-hash rows an end.** Expected: `no_valid_from = 0`; `no_valid_until` is 0 for IP,
   domain, URL and email after the reconcile task, and nonzero only for hashes.

   ```sql
   SELECT count(*) FILTER (WHERE valid_from IS NULL) AS no_valid_from,
          count(*) FILTER (WHERE valid_until IS NULL AND type IN ('ip', 'domain', 'url', 'email')) AS no_valid_until
   FROM indicators;
   ```

7. **IOC page smoke check** (light and dark):
   - IOC Management loads, rows show a state badge and TLP/PAP.
   - Open an indicator: TLP/PAP can be changed by a `manage_ioc` user (`PATCH /api/iocs/{id}/marking`).
   - As `admin`/`superadmin`, the TP and FP buttons are visible; as `analyst`, they are not.
   - Marking a test indicator FP revokes it (state `revoked`: it stays in the IOC list, dimmed, and leaves the stats and dashboard counts); TP restores it. Use a
     throwaway indicator and restore it, since this writes.
   - `GET /api/stix/iocs` contains `valid_until` and a TLP marking-definition reference, and no revoked indicator.
8. **Nothing else broke.** The Data health page and the `ioc.enrich_pending` log (every 15 minutes) show no
   `relation "iocs" does not exist` or `column "ioc_id"` errors:

   ```bash
   cd /home/privy-admin/Niskala-Intelligence && docker compose -p niskala-intelligence logs api worker --since 30m | grep -Ei 'relation "iocs|ioc_id|UndefinedTable'
   ```

   Expected: no output.

**P7b checks.**

- **P7b-1. nginx was recreated with the new template.** Expected: `2` (one match per location) and an `Up` nginx.

  ```bash
  cd /home/privy-admin/Niskala-Intelligence
  docker compose --env-file docker/stack.env --profile app exec -T nginx grep -c 'proxy_pass \$cti_api' /etc/nginx/conf.d/cti.conf
  ```

  If it prints `0` or errors, nginx kept the old image. Recreate only the edge (NEEDS USER APPROVAL; brief edge blip):
  `docker compose --env-file docker/stack.env --profile app up -d --build nginx`. App rollbacks do not touch nginx.
- **P7b-2. Migration and shape.** `alembic_version` is `1387fae00908` (P7c; P7b's `c4f1a8d27b93` is the step before). Expected: `count` equals `count(stix_id)`
  (the migration backfills every existing row) and `min(feed_changed_at)` is not in the future.

  ```sql
  SELECT count(*), count(stix_id), min(feed_changed_at) FROM indicators;
  SELECT tgname FROM pg_trigger WHERE tgname LIKE 'trg\_indicator%' AND NOT tgisinternal ORDER BY 1;
  ```

  The second query returns `trg_indicator_tags_feed_bump` and `trg_indicators_feed_bump`.
- **P7b-3. Token round trip** (**WRITE**: creates and revokes a throwaway token; needs the user's approval). In the web UI,
  Admin > API tokens, create `smoke-test` (scope `indicators:read`, TLP `clear`, expiry 1 day). Copy the token once, then
  from a machine outside the host:

  ```bash
  curl -ks -u x:<token> -H 'Accept: application/taxii+json;version=2.1' https://<host>/taxii2/ -o /dev/null -w '%{http_code}\n'
  curl -ks -u x:<token> -H 'Accept: application/taxii+json;version=2.1' \
    'https://<host>/taxii2/api/collections/6f0e1a52-6a43-4f0b-9b8e-2a7c1d9e4b10/objects/?limit=5' | head -c 600
  curl -ks -u x:<token> 'https://<host>/api/v2/indicators?limit=3' | head -c 600
  ```

  Expected: `200`, a STIX envelope with up to 5 `indicator` objects and a `more` flag, and a JSON page. The discovery
  response lists absolute `https://<host>/taxii2/api/` URLs (checks `Host`/`X-Forwarded-*`). Then read
  `SELECT name, last_used_at FROM api_tokens;` (read-only): `last_used_at` is set. Finally revoke the token in the UI and
  repeat the first `curl`: **401**. Without a token the same URLs also answer 401, and `https://<host>/api/api-tokens`
  must not answer from the API (it goes to `web`).

**P7c checks** (read-only unless marked).

- **P7c-1. Head and objects.** `alembic_version` is `1387fae00908`, and the seven tables, twelve `_legacy_*` tables and
  the views exist:

  ```sql
  SELECT count(*) FILTER (WHERE table_name LIKE '\_legacy\_%') AS legacy,
         count(*) FILTER (WHERE table_name IN ('entities','entity_aliases','relationships','entity_mentions',
                                               'entity_watches','entity_profiles','reference_snapshots')) AS new_tables
  FROM information_schema.tables WHERE table_schema = 'public';
  SELECT count(*) AS views FROM information_schema.views WHERE table_schema = 'public'
    AND table_name IN ('article_threat_actors','article_malware','article_ttps','article_cves','article_countries',
                       'article_industries','indicator_threat_actors','cve_threat_actors','cve_ttps',
                       'ta_watchlist','ta_profiles','ta_whitelist');
  ```

  Expected: `legacy = 12`, `new_tables = 7`, `views = 12`.
- **P7c-2. Every old row is reachable.** Each view equals its legacy table, except `article_industries` (legacy minus the
  "General" rows minus labels that map to the same sector on one article) and `ta_watchlist` (alias collapse). No mention
  points to a missing entity.

  ```sql
  SELECT 'threat_actors' t, (SELECT count(*) FROM article_threat_actors) v, (SELECT count(*) FROM _legacy_article_threat_actors) l
  UNION ALL SELECT 'malware', (SELECT count(*) FROM article_malware), (SELECT count(*) FROM _legacy_article_malware)
  UNION ALL SELECT 'ttps', (SELECT count(*) FROM article_ttps), (SELECT count(*) FROM _legacy_article_ttps)
  UNION ALL SELECT 'cves', (SELECT count(*) FROM article_cves), (SELECT count(*) FROM _legacy_article_cves)
  UNION ALL SELECT 'countries', (SELECT count(*) FROM article_countries), (SELECT count(*) FROM _legacy_article_countries)
  UNION ALL SELECT 'industries', (SELECT count(*) FROM article_industries),
                   (SELECT count(*) FROM _legacy_article_industries WHERE industry <> 'General')
  UNION ALL SELECT 'watchlist', (SELECT count(*) FROM ta_watchlist), (SELECT count(*) FROM _legacy_ta_watchlist)
  UNION ALL SELECT 'profiles', (SELECT count(*) FROM ta_profiles), (SELECT count(*) FROM _legacy_ta_profiles)
  UNION ALL SELECT 'whitelist', (SELECT count(*) FROM ta_whitelist), (SELECT count(*) FROM _legacy_ta_whitelist);
  SELECT count(*) AS orphans FROM entity_mentions m LEFT JOIN entities e ON e.id = m.entity_id WHERE e.id IS NULL;
  ```

  Expected: `v = l` on every row except `industries` (`v <= l`, dev 1,541 vs 1,546) and `watchlist` (`v <= l`, dev 5 vs
  6); the legacy counts equal Before deploy check P7c-1 plus what 0.8.3-0.8.10 added; `orphans = 0`.
- **P7c-3. Entities per type** (write the numbers down for the PR / the user; dev copy in the Migrations section):

  ```sql
  SELECT type, coalesce(identity_class, '') AS class, source, count(*) FROM entities GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
  SELECT count(DISTINCT m.entity_id) AS actors_mentioned FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
  WHERE e.type = 'intrusion-set' AND m.article_id IS NOT NULL;
  ```

  `actors_mentioned` equals the distinct actor names of check P7c-1 before Galaxy (dev 316) and drops after
  `cti-entity merge-aliases --apply` (dev copy: 282).
- **P7c-4. No errors from the new write paths.**

  ```bash
  cd /home/privy-admin/Niskala-Intelligence && docker compose -p niskala-intelligence logs api worker worker-nlp --since 30m | grep -Ei 'entity_resolve|entity_mentions|UndefinedTable|deadlock'
  ```

  Expected: no output. One new article enriched after the deploy has mentions:
  `SELECT a.id, count(m.id) FROM articles a JOIN entity_mentions m ON m.article_id = a.id GROUP BY 1 ORDER BY 1 DESC LIMIT 1;`.
- **P7c-5. Entity API through the web.** Logged in as an analyst, open
  `https://<host>/api/proxy/entities?q=apt36` in the browser: one `intrusion-set` (Transparent Tribe, if ATT&CK is
  synced on prod) with its aliases. The Newsroom actor/industry columns and the dashboard still load (light and
  dark). The entity pages themselves are P7c-2 (check P7c-8).
- **P7c-6. PIR results.** The PIRs with actor criteria from Before deploy check P7c-3 return the same or more results
  (aliases now match).
- **P7c-7. TAXII `intel` pull** (**WRITE**: creates and revokes a throwaway token; needs the user's approval). The
  Admin > API tokens page has scope checkboxes since P7c-2; the console call below does the same:

  ```js
  await (await fetch('/api/proxy/api-tokens', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: 'smoke-intel', scopes: ['intel:read'], max_tlp: 'clear', expires_in_days: 1})})).json()
  ```

  Then from a machine outside the host:

  ```bash
  curl -ks -u x:<token> -H 'Accept: application/taxii+json;version=2.1' https://<host>/taxii2/api/collections/ | head -c 600
  curl -ks -u x:<token> -H 'Accept: application/taxii+json;version=2.1' \
    'https://<host>/taxii2/api/collections/c0b7e3d4-2f5a-4e91-8a6d-5b3c9f1e7a20/objects/?limit=20' | head -c 1500
  curl -ks -u x:<token> 'https://<host>/api/v2/entities?limit=3' | head -c 600
  ```

  Expected: the collection list shows only `intel` (the token lacks `indicators:read`); the objects page holds STIX
  objects of several types and a `more` flag; the REST page is JSON. Revoke the token in Admin > API tokens afterwards.
  On the dev copy a full `intel` pull through the service took 4.0 s for 38,258 objects (39 pages of 1,000, worst page
  0.30 s).
- **P7c-8. Entity web** (read-only except the optional token). Logged in as an analyst: (a) open
  `/intelligence/entities`, pick an actor and confirm the hero KPIs and the Overview, Relationships, Stories and
  Indicators tabs load (light and dark); (b) click an actor or malware chip in Newsroom and land on its entity page;
  (c) `/intelligence/threat-actor-room` lands on the Actors tab and `/intelligence/attack-db` on the Techniques tab;
  (d) create a PIR with a `malware` criterion (pick a malware from the autocomplete) and confirm it lists matching
  articles; (e) **WRITE**, needs approval: in Admin > API tokens create a throwaway token with `intel:read`, then revoke it.
  Expected: no console errors and no 5xx in `docker compose -p niskala-intelligence logs api --since 10m`.

- **P7g-1. Head and queue.** `SELECT version_num FROM alembic_version;` returns `7a3e91c5d2b4`.
  `SELECT kind, state, count(*) FROM enrich_jobs GROUP BY 1,2;` shows the migrated rows (compare with Before deploy P7g-1,
  allowing for arrivals since). `SELECT count(*) FROM rejected_articles WHERE failure_kind IS NOT NULL;` returns 0 (classifier
  rejects, `failure_kind IS NULL`, are untouched).
- **P7g-2. The dispatcher runs.** `docker compose -p niskala-intelligence logs worker --since 5m | grep llm_dispatched`
  prints one line per minute (`breaker=closed ... sent=<n> waiting=<n>`); there is no `auto_replayed` line any more, and
  `docker compose -p niskala-intelligence logs beat` lists no `enrich-auto-replay`.
- **P7g-3. It drains.** Re-run the `enrich_jobs` count after 15 to 60 minutes with a healthy gateway: `pending` falls toward 0;
  `llm_calls` shows `classify` rows with `ok`. In a hard outage `llm_calls` errors are mostly canaries (one or two per hour);
  when the gateway flaps, a canary that succeeds closes the breaker and the next batch of up to 20 jobs can fail together
  (dev 2026-11-04: bursts of 35-51 classify errors in such hours, 293 for the day against about 600 a day before P7g).
- **P7g-4. UI.** Data health shows the breaker (`closed` when healthy, otherwise the retry time) and the pending/failed
  counts. Newsroom > Filtered > "Enrichment queue" lists the jobs; a `failed` row can be retried (**WRITE**, needs approval)
  and a pending `classify` row accepted or rejected (**WRITE**). An article stored by the new code shows "LLM TTPs pending" in
  its modal until the `ttp` job finishes.
- **P7f-1. Signals present** (read-only, after the One-off recompute below, or after the daily run). Expected: `pir` rows
  roughly equal the articles that the PIR page lists for each active PIR; `own_asset` rows well above 0 (on dev the title
  path alone matched 80 of 1,331 articles in 30 days).

  ```sql
  SELECT count(*) FROM articles WHERE score_reasons ? 'pir';
  SELECT count(*) FROM articles WHERE score_reasons ? 'own_asset';
  ```

  Dev (2026-11-05, after the recompute, 2,057 articles): `pir` 55, exactly the 55 articles the PIR page lists for PIR #5
  (P2, Shinyhunters); `own_asset` 133 (93 in the last 30 days; top names Linux 42, gitlab 26, fortinet 20, microsoft 365
  12, jira 11). `priority_score` median 70, p90 104, p99 133 (before: 70, 101, 126); 9 of the top 10 by priority in 30
  days carry `own_asset`. The tooltip was checked in light and dark mode; a narrow width was not (the browser window does
  not go below about 600 px).
- **P7f-2. Grade tooltip** (UI, read-only). Open the Newsroom, hover the grade chip of an article returned by the checks
  above: "Why this grade" lists "PIR match" and "own asset" with the PIR title and priority or the tech name. Open the
  PIR page for that PIR and confirm the article is in its list. Check light and dark mode and a narrow width.

### One-off commands (recompute/backfills: exact command, `--dry-run` first, expected numbers from dev, how long; mark each as needing the user's approval)

Normally **nothing to run**: the first API start enqueues `indicator.reconcile_validity` by itself. Run the command below
only if After deploy check 2 shows `reconcile_validity_enqueue_failed` or check 3 returns no row.

There is **no `--dry-run`** (the task is idempotent and only fills `valid_until`; it never touches revoked rows). Read-only
preview: After deploy check 6.

**Manual reconcile (NEEDS USER APPROVAL; WRITE: sets `valid_until` on non-hash indicators).** It enqueues the same task
the bootstrap sends; the `worker` runs it.

```bash
cd /home/privy-admin/Niskala-Intelligence
docker compose -p niskala-intelligence exec -T api python -c "from cti_core.celery_client import send_reconcile_validity; send_reconcile_validity()"
```

Expected: `indicator_validity_reconciled` in the `worker` log and check 6 clean. Duration: not measured on dev.
**Projection:** seconds for about 5,500 rows.

**P7b:** nothing to run. The migration backfills `stix_id` and `feed_changed_at` itself. Rows written by old code during a
rollback window get their `stix_id` from the next `indicator.reconcile_validity` run (the manual command above).

**P7c: three steps, in this order, after the deploy is healthy and After deploy checks P7c-1 to P7c-4 are clean.** They
replace the 0.8.8 `canonicalise_actors` step (now a no-op).

1. **ATT&CK sync (NEEDS USER APPROVAL; WRITE: downloads the MITRE bundles from GitHub and upserts ATT&CK data,
   entities, aliases, relationships and campaigns).** The migration has no network, so `campaign` entities and anything
   newer than prod's last ATT&CK sync only arrive with a sync. In the UI as a `manage_intel` user: Entities > Techniques tab, ATT&CK
   sync card, "Sync All Domains". Wait until every domain card shows done (no `error`); a failed entity upsert marks the domain sync
   as error on that card. Then, read-only: `SELECT count(*) FROM entities WHERE type = 'campaign';` is above 0.
   Duration: not measured (network bound). Running it first matters: the Galaxy merge anchors on ATT&CK entities and
   aliases.
2. **Galaxy merge, dry-run (read-only: plans, writes nothing).** The CSV goes to stdout, the summary line to stderr:

   ```bash
   cd /home/privy-admin/Niskala-Intelligence
   docker compose --env-file docker/stack.env --profile app exec -T worker \
     python -m cti_core.entity.cli merge-aliases --dry-run > /tmp/galaxy.csv
   ```

   Columns: `action,cluster,source_entity,target_entity,alias,reason`. `merge` rows fold `source_entity` into
   `target_entity` (the ATT&CK entity when the cluster has exactly one, else the one with the most mentions); `alias`
   rows add a Galaxy synonym to an existing entity; `skip` rows carry the reason (`ambiguous`: a common word or Tier 1
   ambiguous name, never merged; `owned`: the alias belongs to another entity and is not moved; `two_attack`: the
   cluster touches two ATT&CK entities). **Share the CSV with the user and review every `merge` row before step 3**
   (dev-copy targets worth a look: `Red menshen -> Earth bluecrow`, `Predatory sparrow -> Gonjeshke darande`, where the
   target is the spelling with most mentions, not the cluster name).

   Dev copy (2026-11-01, without a fresh ATT&CK sync): 6,976 clusters; **35 merges, 812 new aliases, 339 skips**
   (197 `ambiguous`, 85 `owned`, 57 `two_attack`); 1.1 s.
3. **Galaxy merge, apply (NEEDS USER APPROVAL after the CSV review; WRITE).**

   ```bash
   docker compose --env-file docker/stack.env --profile app exec -T worker \
     python -m cti_core.entity.cli merge-aliases --apply > /tmp/galaxy-applied.csv
   ```

   The whole run is **one transaction**: a DB error other than a planned skip rolls everything back, so just re-run it
   (each merge has its own savepoint; a deadlock with a concurrent enrichment is retried once, a second deadlock aborts
   the run; a merge the merge code refuses, for example one touching a suppressed entity, becomes an `error` row and the
   run goes on). Every merge is audit-logged with actor `system:galaxy` and can be undone exactly with
   Split (entity API, P7c-2 dialog); an undone merge is never redone by later runs. Dev copy: **2.5 s, 35 merges, 812
   aliases, 0 errors**; actors with article mentions 316 -> 282; a second dry-run plans 0 merges and 0 aliases (the
   339 skips stay listed). From then on the weekly `entity.alias_sync` repeats this on fresh Galaxy data: its merge gate
   opens on the first `entity_merge` audit row by `system:galaxy`, which this step writes. If this step merges nothing
   (0 `merge` rows), the gate stays closed and the weekly task keeps storing snapshots only; that is intended, re-run
   steps 2-3 after a later dry-run shows merges.

P7g needs **nothing**: the migration moves the parked rows and the dispatcher drains them. `make replay-failed-enrichment`
no longer exists. The only P7g command is the rollback helper (below), used **only** if the code is rolled back.

- **P7f recompute (needs the user's approval, WRITE).** Existing articles carry no `pir`/`own_asset` points until their
  score is recomputed; the daily `confidence.recompute_all` and any PIR or techstack edit do it too, so this is only to
  avoid waiting. `POST /api/articles/confidence/recompute` (needs the `manage_intel` permission) runs synchronously inside the API
  request (commit per batch), holds the connection for the whole run so proxy/nginx timeouts apply, and returns the counts.
  The alternative is to wait for the daily `confidence.recompute_all` beat task. There is no `--dry-run`. The run is
  idempotent and rewrites only score columns. Dev duration: 2,057 articles in 5.9 s (run inside the worker container).

### Rollback / if it goes wrong

- **Code rollback.** `deploy.sh` restores the `:prev` images on failure and never downgrades the DB. Prod runs 0.8.2, so
  the auto-rollback target is **0.8.2 images on the 0.8.11 schema**, not 0.8.10. The P7a schema change was verified safe
  for both: on 2026-10-29 the real 0.8.10 code and the real 0.8.2 code were each run against a database migrated to
  `a9e4c7b1d3f6` (`IOCRepo.upsert` twice, child source rows and `add_feedback` all worked through the compatibility
  views; base defaults for `valid_from`, `tlp` and `pap` applied; `valid_until` stayed NULL). Compatibility of 0.8.2 code
  with the schema changes of the other releases in the chain (0.8.3 to 0.8.10) is covered by those releases' own
  sections; the `deploy.sh` backup is the fallback. Caveats: old code does not see or honour revocations and TLP/PAP set
  after the upgrade, and rows it inserts get `valid_until` NULL until the daily `indicator.reconcile_validity` run (04:15)
  of 0.8.11 fills them (or the manual reconcile; an API restart enqueues it only when the TTL settings changed). If only the 0.8.11 *deploy* failed before `migrate` ran, nothing needs undoing.
- **DB downgrade (OPTIONAL, manual)** (WRITE, needs approval, only after the app is stopped, and only when returning to 0.8.10): `alembic downgrade d7a3e1b94c52`.
  It drops the five views, drops the new columns and index, then renames the tables back, so `iocs` is a table again with
  the same ids. Revocations (`revoked_at`) and TLP/PAP set in 0.8.11 are lost; `valid_until` is recomputed after the next
  upgrade. Going back to 0.8.2 is a backup restore, not a P7a downgrade.
- **Reconcile stuck or failing:** check the `worker` log for `indicator`; fix the cause and re-run the manual reconcile
  above (idempotent).
- **A hand-run query fails with `relation "iocs" does not exist`:** before the 0.8.11 migration `iocs` is a table and after it a view, so this error means the session is on the
  wrong database or `search_path` (or the views were dropped by hand). Use `indicators` (the table) in new queries.

- **P7b rollback.** Safe without a DB downgrade. 0.8.2 and 0.8.10 code ignore the `api_tokens` table and the two new
  `indicators` columns; the triggers only maintain `feed_changed_at`, a column that code never reads, so they are harmless
  and stay (this also covers prod's auto-rollback: `:prev` images, no DB downgrade). The `iocs` compatibility view keeps
  `SELECT *` as of the P7a migration, so old INSERTs use the table defaults for the new columns. The API paths
  `/taxii2/` and `/api/v2/` disappear with the code (nginx then answers 502 or 404 for them); consumers see errors until
  the next deploy. nginx is not rolled back by `rollback.py` (own image tag); the extra locations are harmless without
  the routes. An optional `alembic downgrade a9e4c7b1d3f6` (WRITE, app stopped, needs approval) drops the tokens table,
  triggers and columns; tokens are lost.

- **P7c rollback: old code works through the views (verified with the real 0.8.2 and 0.8.10 code, 2026-11-01).** No DB
  downgrade is needed for `deploy.sh`'s auto-rollback. Check run: local `qacve` Postgres migrated to `1387fae00908` from
  this branch; the branch's own `persist` wrote a reference article (actor "Volt Typhoon", tool "Cobalt Strike", T1566,
  country ID/CN, industry "Finance & Insurance", CVE-2026-1111) and merged an analyst entity "Bronze Silhouette" into
  Volt Typhoon. Then from detached worktrees at tags `0.8.10` and `0.8.2`, each with its own `uv sync --locked`
  environment, one script (`uv run --no-sync python -I rollback_check.py <label> <0810|082>`, with
  `DATABASE__URL`/`DATABASE__SYNC_URL` pointing at `qacve`) ran:
  - the tag's real `cti_enrich.stages.persist.persist` for a new article with actors "Volt typhoon",
    "BRONZE SILHOUETTE" and a name only that tag knows, two TTPs, malware (0.8.10 via `Tier1Result`), two industries,
    two countries and two CVEs; the same call again (replay); then once more with a smaller set (old ORM delete-orphan
    through the views);
  - `AsyncTARepo.add_to_watchlist` ("bronze silhouette", then "Volt Typhoon"), `remove_from_watchlist`
    ("bronze silhouette"), `add_to_watchlist` of a new name;
  - `AsyncTAProfileRepo.save_profile("Volt typhoon", ...)` twice (insert, then the old update path);
  - `AsyncTARepo.delete_group` (whitelist add), `list_whitelist`, `remove_from_whitelist`, `delete_group` again;
  - and, from 0.8.2, `remove_from_watchlist("volt typhoon")`.

  Result: **no error in either version.** Every row resolved to the same entities as the new code: actor mentions of
  all three articles point to entity "Volt Typhoon" (both alias spellings collapse into one mention per article), T1566
  to one `attack-pattern`, "Finance & Insurance" to the sector "Financial Services", ID/CN to the `location` entities,
  CVE-2026-1111 to one `vulnerability`, "Cobalt Strike" to one `tool`; the shrink replay removed the dropped mentions;
  the profile landed on Volt Typhoon's `entity_profiles` row; names only old code knew became `legacy` entities; old
  whitelist rows became suppressed `legacy` entities. Differences that are expected, not failures:
  - SQLAlchemy prints `SAWarning: DELETE statement on table 'article_threat_actors' expected to delete 2 row(s); 1 were
    matched` on the replay, because two spellings of one actor are one mention now. A warning, not an error.
  - Mentions written by old code carry `method = 'legacy'` for countries (new code: `llm`).
  - 0.8.2 has no `article_malware`/`article_cves` writers (malware arrived in 0.8.8; 0.8.2 still stores CVEs as `cve`
    indicators); 0.8.10's `ArticleCveRepo.add_many` only adds, as it always did.
  - **Old watchlist removal by an alias spelling misses:** `remove_from_watchlist("bronze silhouette")` returns `False`
    because the view shows the entity name ("Volt Typhoon"); removal by the entity name works. The same applies to the
    old whitelist removal.
- **P7c DB downgrade (OPTIONAL, manual; WRITE, app stopped, needs approval):** `alembic downgrade c4f1a8d27b93` drops
  the triggers, views, functions and new tables and renames the twelve `_legacy_*` tables back. Everything written after
  the upgrade through the views or the new tables (mentions of new articles, merges, aliases, watches, profiles,
  whitelist rows) is lost. Not needed for a code rollback.
- **A wrong Galaxy or analyst merge:** undo it with Split (`POST /api/entities/{id}/split`; the P7c-2 dialog), which
  restores the aliases and mentions exactly and revives the tombstone. Watches, profile and relationships stay on the
  target and are listed for the analyst. A merge undone this way is never redone by the weekly sync.
- **`cti-entity merge-aliases --apply` failed with a DB error:** nothing was written (one transaction). Re-run it.
- **`migrate` failed with `canceling statement due to lock timeout` or `deadlock detected`:** a long transaction held one of the old link/TA
  tables (or another table the migration touches) for more than 10 s. The migration rolled back completely and
  `deploy.sh` restored the `:prev` images; re-run `make deploy` (preferably outside an enrichment burst).

- **P7g: rolling the images back past 0.8.11.** The old code has no `enrich_jobs`, so the waiting work must go back
  into `rejected_articles`. Run this **after** the image rollback (the old workers and beat are up, the 0.8.11 `worker`,
  `worker-nlp`, `beat` and `api` are gone, so nothing creates new jobs behind the tool): report first, then `--apply`. If it
  must run before the rollback, stop `worker`, `worker-nlp`, `beat` and `api` first. From the host checkout (which stays on
  the new commit), with the app `.env` supplying `DATABASE__SYNC_URL` (the tool prints the host and database it connects to,
  never the password; check it is the right environment):
  ```bash
  uv run python tools/ops/requeue_enrich_jobs.py            # report: counts per kind and state, writes nothing
  uv run python tools/ops/requeue_enrich_jobs.py --apply    # WRITE, needs approval
  ```
  `--apply` moves every `classify` job back into `rejected_articles` as `failure_kind='transient'`, `auto_replay_count=0`,
  reason `[enrichment_failed] requeued after rollback`, and deletes the `ttp` jobs (those articles keep their Tier 1 TTPs;
  the LLM TTPs are lost). One transaction; a second run moves nothing; the script uses only the database. What happens next
  depends on the image you rolled back to:
  - **0.8.5 to 0.8.10 images:** the old `enrich.auto_replay` (beat, every 10 min) drains the requeued rows by itself once the
    LLM is healthy.
  - **0.8.2 images (prod's auto-rollback target):** there is no `enrich.auto_replay` (it arrived in 0.8.5), so the rows stay
    parked as `[enrichment_failed]` rows. Once the LLM is healthy an admin replays them by hand with the old Replay button
    (Newsroom > Filtered > Failed enrichment, `POST /api/filtered-articles/{id}/replay`; both exist in the 0.8.2 tag,
    admin only), row by row. `tools/ops/replay_failed_enrichment.py` is not in these images either: do not look for it.
- **Gateway down for hours:** not a rollback case. Jobs wait, the breaker holds the model to one canary per cooldown, and the
  Telegram alert says how many are waiting. Do not restart workers to "push" the queue.
- **P7f.** No schema change, so a code rollback needs no DB step. The 0.8.10 and older code ignores the unknown
  `score_reasons` keys `pir` and `own_asset` (pydantic default) and serves the same rows; the P7f points stay in
  `priority_score` until the old code's next recompute removes them. Nothing to undo by hand.

### Known risks and follow-ups

- **R1: SQL outside the app that names `iocs`.** Covered by the compatibility views and by rewriting this runbook's
  post-0.8.11 queries to `indicators`; queries that run before the deploy (on 0.8.2) keep `iocs`. The views are
  **deprecated and will be dropped in a later release**; that release's runbook must say so and list the external readers
  found in Before deploy check 3. `test_migrations_match_models` stays green with the views present.
- **R2: `pg_backup.py` verification.** `KEY_TABLES` lists both names and skips the one that does not exist. A backup taken
  after the migration verifies `indicators`; if someone later removes `iocs` from the list, keep `indicators`.
- **R3: merge conflicts with unmerged IOC branches** (`feat/ioc-enrichment-abuseipdb`,
  `feat/ioc-enrichment-virustotal-otx`, `claude/react-retheme-ui-ux-pro-max-00bc1b`). The rename is the first commit and
  purely mechanical, so a rebase conflict is a name substitution. Ask whether those branches are still to land.
- **R4: `valid_until` is NULL between the migration and the first reconcile run.** Non-hash indicators read as
  non-expiring for the minutes between `migrate` and the first API start. No feed exists before P7b, so nothing downstream
  consumes expiry yet. After deploy checks 3 and 6 prove the backfill.
- **R5: `manage_ioc` is now required for TP/FP.** The built-in `analyst` role is granted `manage_ioc` in 0.8.11 (user
  decision 2026-10-29), so analysts keep TP/FP; the system role is updated automatically when `api` starts. The grant is
  broad: analysts can now also delete IOCs (single and bulk), edit the allowlist, tags and threat-actor links. Only custom
  roles with `view_ioc` and without `manage_ioc` lose the buttons (Before deploy check 2 lists them). The FP queue panel
  on the Exec dashboard follows the same rule, and FP there now revokes the indicator.
- **R6: downgrade and the compatibility views.** The views occupy the old table names, so the downgrade drops them first.
  This is covered by the migration up/down test.
- **P6 recompute after FP.** A revoked indicator stops counting as IOC/artefact evidence only when the article is next
  assessed (`confidence.refresh_stories`, the daily `confidence.recompute_all` at 03:20, or a manual recompute).
- **Follow-ups:** fill the dev result (state distribution, reconcile duration) after the dev test; record the prod baseline
  and After-deploy numbers; drop the compatibility views in a later release; P7b (scoped API tokens, `/api/v2/indicators`,
  TAXII 2.1) builds on this release.

- **P7b R1: TLP raised after publication.** A consumer below the new level stops receiving the indicator and never gets
  a deletion (a tombstone would leak the value). Markings only rise through an analyst PATCH and everything is `clear`
  today. Revisit when a non-public source exists.
- **P7b R2: strict clients and `marking-definition` objects.** Interop was tested with `taxii2-client` (a dev-only
  dependency used by tests). If a consumer needs the definitions inside the collection, add them with a fixed
  `date_added` before all indicators.
- **P7b R3: `/taxii2/` and `/api/v2/` are exposed on 443.** Token required on every route, read-only, one scope, hashed
  tokens, revocation takes effect on the next request. No per-token rate limit yet (follow-up).
- **P7b R4: discovery URLs behind the proxy.** Correct because nginx passes `Host`/`X-Forwarded-*` and uvicorn runs with
  `--proxy-headers`; verified by After deploy check P7b-3 from outside the host.
- **P7b R5: settle lag.** The feed clock is `clock_timestamp()` (the statement time of the write, not the transaction
  start, which can be minutes old in the enrich pipeline). The 60 s settle lag only has to cover write -> commit
  (persist is the last step before commit); a write that commits later than that can still be skipped by a client already
  past that point, and the next change to the row (any re-sighting) re-sends it.
- **P7b R6: triggers are invisible to the drift test.** Dedicated trigger tests cover them; the docstring of
  `feed_changed_at` names the triggers and the migration.
- **P7b R7: hard delete is not a retraction.** `DELETE /api/iocs/{id}` and the bulk delete remove an indicator from
  the feed without a revocation; subscribers keep it until its `valid_until`. To retract a published indicator, mark it
  FP (revoke) instead of deleting it.
- **P7b R8: un-revoking re-publishes the same id.** A TP after an FP, or removing an allowlist entry, publishes the same
  `indicator--` id without `revoked`. STIX 2.1 treats revocation as permanent, so strict consumers may keep it deleted.
- **P7b R9: expiry does not move the feed clock.** Expiry is time-based, so consumers must evaluate `valid_until`
  themselves; the REST `state` field is a snapshot at the time of the request.
- **P7b follow-ups:** per-token rate limiting; sightings (P7d, deferred); entities and relationships (P7c).

- **P7c R1: a wrong automatic merge from Galaxy** (over-wide clusters, common-word synonyms). Guards: a cluster touching
  two ATT&CK entities is skipped, ambiguous synonyms never merge, ATT&CK and analyst aliases never move, undone merges are
  never redone. In prod the dry-run CSV is reviewed before `--apply`; every merge is audit-logged and Split undoes it.
  The weekly `entity.alias_sync` applies without review (same guards), but only after the first manual `--apply`
  (code gate on the `system:galaxy` audit row); switch it off with `ENTITY__ALIAS_SYNC_ENABLED=false` if it misbehaves.
- **P7c R4: users see changed numbers.** Deliberate. Dev copy: actors with article mentions 316 -> 316 after the
  migration (no two stored article names are aliases of one ATT&CK group) -> 282 after the Galaxy apply; watchlist 6 -> 5;
  `article_industries` 2,551 rows -> 1,541 sector mentions ("General" dropped); `industry_unspecified` rises because it
  now counts every article without a sector mention. The spec's "106 actor strings" estimate counted ATT&CK and Galaxy
  aliases together; the measured Galaxy collapse on the dev copy is 35 merges. Some industry labels map to a neighbouring
  sector (for example "Cloud Services" -> "Technology", "Legal & Professional Services" -> "Commercial"); analysts can fix that by merging.
- **P7c R5: TLP raised after publication cannot reach lower-TLP consumers.** As P7b R1, now for entities and
  relationships: a consumer below the new level stops receiving the object and never gets a deletion (TAXII has none).
  Everything is `clear` today; markings only rise through an analyst action.
- **P7c R6: indicator TLP or state changes do not re-send the reports and relationships that reference the indicator.**
  The indicator itself is re-sent (P7b clock); a consumer keeps the older report until the story changes again.
- **P7c R7: residual deadlock between re-enrichment and a merge.** Re-enriching an article that already has mentions
  while a merge, split or suppress touches one of its entities can still deadlock (mention row locks against the story
  lock). Postgres aborts one side with `40P01`. The enrichment side raises `sqlalchemy.exc.OperationalError`, which the
  `enrich.article` failure policy treats as transient (retry after 30 s backoff, which repeats the article's LLM calls);
  Galaxy apply retries the merge once; an analyst merge through the API fails and can simply be repeated. The common
  case (new article vs analyst operation) is a wait, not a deadlock (merge takes `FOR NO KEY UPDATE`; first/last_seen
  updates skip locked rows, so they may lag by one article).
- **P7c R8: rolled-back 0.8.10 `add_tier1` adds no keyword industries.** In 0.8.10 that branch fires only when the
  article's sole industry is "General", which no longer exists after the migration; a 0.8.10 `backfill_tier1` run during
  a rollback window therefore adds no keyword industries (0.8.11 adds them when the article has no sector mention).
- **P7c R9: old watchlist and whitelist removal by an alias spelling misses** during a rollback window (the views show
  the entity name). Remove by the shown name.
- **P7c R10: Tier 1 dictionary scope.** The dictionary takes aliases from ATT&CK, Galaxy and analysts, plus
  `threat_actor_groups` names. Names known only from legacy data or ransomware groups are entities but are not matched
  in article text: on dev (2026-11-01) the ransomware group "Payload" matched the common word "payload" in a malware
  article before this rule. A ransomware group missing from `threat_actor_groups` is therefore not tagged in news until
  an analyst adds an alias or the group gets a Galaxy alias. Single-token non-ATT&CK names still need a context word.
- **P7c R11: ATT&CK adoption changes a stix_id, and it recurs.** When ATT&CK sync meets a non-ATT&CK entity with the same
  name it adopts it (ATT&CK id, aliases, relationships), so that entity's `intrusion-set--` (or `malware--`/`tool--`) id
  changes. This is not a one-off: it happens again whenever a new ATT&CK release adds a group or software that news
  already mentioned. The swap bumps the entity's feed clock and those of the relationships and reports that reference
  it, so `intel` consumers receive the entity, relationships and reports under the new id. The old id is **not
  revoked**: a consumer keeps the old object as a stale duplicate until it deletes it by hand. No `intel` consumer exists
  before 0.8.11 ships; revisit (publish a revoked copy of the old id) once one does.
- **P7c R12: `_legacy_*` tables and compatibility views** stay until the first release after 0.8.11, which drops them;
  that runbook must say so. Hand-run SQL should move to `entity_mentions` join `entities`.
- **P7c R13: ATT&CK sync overwrites analyst edits** to the name and description of `source = 'attack'` entities at the next sync (Ruling 27).
- **P7c R14: Galaxy clusters that match no existing entity create nothing**, so an actor first seen under a Galaxy-only synonym stays a separate entity until the next weekly `entity.alias_sync` merges it (Ruling 19).
- **P7c R15: a ransomware victim named like a sector is skipped** (log `ransomware_victim_is_sector`) instead of being linked to the sector (Ruling 10; 0 of 1,342 dev victims collided on 2026-10-30).
- **P7c R16: REST v2 shows a few relationships TAXII does not:** relationships whose source is an indicator without a STIX pattern (for example a `cve` indicator) are in `GET /api/v2/relationships` but not in the TAXII `intel` collection.
- **P7c R17: enrichment throughput.** Each mention insert updates its story's `feed_changed_at` row by row, which can serialise the enrichment of articles of the same story; watch enrichment duration and queue depth on dev after the deploy (Task 5).
- **P7c R18: intel visibility queries.** EXPLAIN ANALYZE (auto_explain) of two 1,000-object `intel` pages on a fresh dev copy (2026-11-01, after the Galaxy apply): 20 statements, slowest 27 ms (the story visibility `EXISTS`, hashed subplans with sequential scans of `entities` ~8,000, `entity_mentions` ~12,800 and `articles` 1,797 rows), page 0.16-0.24 s; the feed-clock scans use the `ix_*_feed_changed_at_id` indexes. Fine at dev size; the sequential scans grow linearly, so re-check after the data grows.
- **P7c R19: a mention can land on a merged entity.** An enrichment that runs while a merge (analyst or Galaxy) touches
  one of its entities can write its mention to the tombstone: the mention's foreign-key check does not conflict with the
  merge's row lock (R7), and the merge's repoint cannot see the uncommitted insert. Such a mention is hidden from
  readers (tombstones are not live). `repair_tombstone_mentions` moves these mentions to the live end of the merge chain
  (dropping duplicates) at the start of every Galaxy apply and in the weekly `entity.alias_sync` (log
  `tombstone_mentions_repaired`), so with `ENTITY__ALIAS_SYNC_ENABLED` on they stay hidden for at most a week; with it off,
  only a manual `cti-entity merge-aliases --apply` repairs them. Split stays exact (it moves mentions by
  `matched_alias`). Read-only check, normally 0: `SELECT count(*) FROM entity_mentions m JOIN entities e
  ON e.id = m.entity_id WHERE e.merged_into_id IS NOT NULL;`
- **P7c R20: long transactions can outrun the 60 s settle lag.** `cti-entity merge-aliases --apply`, the weekly
  `entity.alias_sync` and the ATT&CK entity upsert each run as one transaction and can take longer than 60 s on a large
  database. Rows they bump carry the statement time, so an incremental `intel` consumer that polled while the
  transaction was open may move its cursor past them and skip those changes. After a large merge run, ask consumers to
  re-pull from a cursor older than the run (or from the start); the next change to a row re-sends it anyway.
- **P7c R21: reports can disappear without a revocation.** A story whose referenced objects all become invisible
  (suppressed, above the token's TLP, or merged away), a purged story, or a deleted article drops the `report` from the
  `intel` collection with no `revoked: true` copy; a consumer keeps the last report it saw.
- **P7c R22: ransomware victims written by 0.8.2 code during the migrate or rollback window get no entities.** The
  0.8.2 ransomware sink writes only `ransomware_victims` (that table is not a view), so victims it inserts after the
  migration and before 0.8.11 code runs again have no victim/group entities and no `targets`/`located-at`
  relationships; a later 0.8.11 upsert of the same `offset_key` would link them, but scraper dedup normally prevents
  that. Known gap, small (at most one monthly snapshot). Optional manual re-link (WRITE, needs approval; idempotent, the
  relationship upsert only widens the seen range), with the migration time in UTC:

  ```bash
  docker compose --env-file docker/stack.env --profile app exec -T worker python - <<'PY'
  import sqlalchemy as sa
  from cti_core.db.engine import sync_session
  from cti_core.db.models.ransomware import RansomwareVictim
  from cti_core.db.repositories.ransomware import RansomwareVictimRepo
  with sync_session() as s:
      repo = RansomwareVictimRepo(s)
      since = "<migration time, UTC>"
      for v in s.scalars(sa.select(RansomwareVictim).where(RansomwareVictim.created_at >= since)):
          repo._link_entities(v)
      s.commit()
  PY
  ```
- **P7c follow-ups:** the dev data check of spec section 8 after merging to `origin/Dev` (CSV review, 10 sampled merges, PIR
  counts, `feed_changed_at` untouched by the 04:00 decay sweep, TAXII `intel` pull from outside the host); prod numbers
  for After deploy checks P7c-1 to P7c-8.

- **P7g R1: a title waits as long as the gateway is down.** The Enrichment queue page and the Telegram alert make it
  visible; an analyst can accept or reject. Follow-ups of a story whose lead waits also wait (they inherit once the lead is
  decided).
- **P7g R2: storage.** `input_text` is kept per pending job (tens of KB each); rows are deleted on completion.
- **P7g R3: the breaker looks only at `classify`/`ttp` calls.** Failures of recap or TA profile calls do not open it.
- **P7g R4: after a rollback pending `ttp` jobs are dropped** (Tier 1 TTPs remain).
- **P7g R5: a persistent DB bug loops with backoff** (visible in `attempts` and `last_error`) instead of failing fast, by
  design: the goal is zero jobs waiting for a human after transient DB trouble.
- **P7g R6: a permanently rejected request retries forever.** An article whose LLM request always returns 400/401/403/404
  retries with backoff (up to hourly, no cap) and can be the half-open canary, keeping the breaker open for the whole
  queue. Watch `last_error` in the Enrichment queue, and reject the article or fix the gateway config.
- **P7g R7: leftover `enrich.auto_replay` messages.** Messages already queued at deploy time are logged once as
  "unregistered task" by the new worker and discarded. This is harmless.
- **P7g follow-ups:** the dev check of spec section 6 after merging to `origin/Dev` (one outage night: classify `error` calls
  per day drop from hundreds to tens, pending jobs rise then drain, the migrated rows drain, no new `[enrichment_failed]`
  rows); dropping the unused `failure_kind`, `auto_replay_count`, `last_auto_replay_at` columns is a later cleanup.
- **P7f-R1: the score is global (D1).** One `priority_score` for all clients, so a match against client A's PIR raises the
  article for client B too. B sees "PIR match +15" in the grade tooltip but never A's PIR title or tech names. Fine with
  one client (today); revisit before a second client with its own PIRs goes live.
- **P7f-R2: PIR and techstack edits trigger a full recompute** (no debounce; 5 batches of 500 on dev). Many quick edits
  queue many runs; they are idempotent.
- **P7f-R3: relevance is "as of now".** A recompute applies today's PIRs and techstack to old articles, and a PIR whose
  date window opens or closes changes scores at the next daily run.
- **P7f-R4: direct DB edits.** A PIR that expires or is edited directly in the DB keeps or loses its points only at the next recompute (daily, or on an API edit).
- **P7f follow-ups:** PIR matches unlocking Tier 3 LLM, the weekly PIR coverage report and the dashboard "Tech stack"
  badge reading `score_reasons.own_asset` are out of scope.
