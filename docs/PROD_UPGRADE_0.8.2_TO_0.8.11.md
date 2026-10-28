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
   download reachability, `.env` keys and disk space, 0.8.10 confidence baseline, 0.8.11 IOC baseline and role check). Write the results down: several
   "After deploy" checks compare against them. These run on 0.8.2, where the IOC tables are still `iocs` and `ioc_sources`;
   after the deploy the same data lives in `indicators` and `indicator_sources` (0.8.11), so the After-deploy queries use
   the new names.
2. **`.env`:** no new required key in any of these releases (0.8.11 adds four optional `INDICATOR__TTL_*_DAYS` keys with defaults; leave them unset). Do **not** copy dev's `RELEVANCE__GATE_MIN_AGREEMENT=0.94` or
   `STORY__EMBEDDING_SIMILARITY=0.8`; leave `RELEVANCE__*` and `STORY__*` unset for the first deploy (see 0.8.7 and 0.8.9).
3. **Make sure the prod LLM gateway works** (model name and credits). Dev's OpenRouter free quota ran out; with a dead
   gateway 0.8.5's auto-replay stays on one canary per 10 minutes and 0.8.9's first model may be rejected.
4. **`make deploy`.** The `worker-nlp` build downloads the MiniLM model (~88 MB) from Hugging Face (0.8.9); if that fails
   the deploy aborts before any container changes.
5. **After deploy:** run the "After deploy" blocks in release order. Admin task from 0.8.4: add `manage_cve`/`view_ops` to
   custom roles. Remedy from 0.8.6 (only now, never before): clear machine-written `overrides.confidence_score` if the
   before-count was > 0. For its follow-up recompute, the 0.8.10 section recommends the Celery enqueue over the inline
   `POST /api/articles/confidence/recompute`, which can hit the proxy timeout.
6. **One-off WRITE commands, in this order, after the deploy is healthy (each needs approval, dry-run first):**
   1. 0.8.7 story backfill (`cti_enrich.story_backfill`), bounded with `--since`.
   2. 0.8.8 Tier 1 backfill (`cti_enrich.backfill_tier1`, ~3 s/article; never during a deploy).
   3. 0.8.8 actor-name canonicalisation (`cti_enrich.canonicalise_actors --apply`).

   0.8.9 needs nothing: the first model trains itself within an hour. 0.8.11 needs nothing either: the first API start
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

Expected `alembic_version` after the deploy: **`a9e4c7b1d3f6`**. The only way back past `e7b2d4a9c6f1` is the Postgres
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

-- Alias-form actor names that canonicalise_actors would rewrite (measured 2026-10-25: 7 rows, 6 names).
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

1. **Tier 1 backfill — WRITE, needs the user's approval.** Add-only: adds explicit/keyword TTPs whose ID is missing, actors/malware not yet present (skips an actor whose alias form already exists), and keyword industries only when the article's sole industry is "General". Never touches LLM rows, overrides, `news_type`, confidence or alerts. No LLM calls.

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

2. **Actor-name canonicalisation — WRITE, needs the user's approval.** Rewrites pre-0.8.8 alias-form names to the canonical stored form in `article_threat_actors`, `ta_watchlist`, `ta_profiles` and PIR criteria; merges duplicates (newest `generated_at` wins for TA profiles; dropped names are printed). One transaction; re-runnable (second run is a no-op). Run after the backfill.

   ```bash
   docker compose --env-file docker/stack.env --profile app exec -T worker python -m cti_enrich.canonicalise_actors          # dry-run, rolls back
   docker compose --env-file docker/stack.env --profile app exec -T worker python -m cti_enrich.canonicalise_actors --apply  # approval required
   ```

   Dev: 4 renamed + 1 merged article rows, 1 watchlist, 1 TA profile ("apt36" -> "Transparent tribe"); second dry-run 0/0. Prod measured read-only on 2026-10-25: 7 article rows (6 names) + 1 TA profile. Takes seconds.

### Rollback / if it goes wrong

- Code: `deploy.sh` rolls images back to `:prev` when health fails (it never downgrades the DB). The 0.8.8 schema is additive, so older code runs against it.
- A Tier 1 failure never drops an article: `run_tier1` catches everything, logs `tier1_failed` and persists without Tier 1. Persistent `tier1_failed` -> check reads of `attack_*` / `threat_actor_groups`, then redeploy the previous image if needed.
- Bad backfill rows (WRITE, approval required): `delete from article_ttps where source in ('explicit','keyword');` and `delete from article_malware;` remove Tier 1 TTPs/malware only; LLM rows stay. Tier 1 actor rows carry `source='dictionary'` like pre-0.8.8 rows, so they cannot be separated by `source`; use the Postgres backup made by `make deploy` for a full revert.
- Canonicalisation has no undo command: restore from the deploy backup, or reverse it from its printed `old -> new` list.
- Schema: `alembic downgrade a7d3f1c9e5b2` only together with 0.8.7 code and only after downgrading 0.8.9 (`c4f1a9d27e6b` depends on `b8e2c4a6d1f3`).

### Known risks and follow-ups

- Precision (silver standard: 2 LLM labellers, 92% agreement, no human labels): actor dictionary 71% vs LLM-era 70%; TTP explicit 99%, keyword 70% vs LLM 35%; industry keyword 5/5 vs LLM 39%; malware/tool 47% (weakest: generic OS tools, incidental mentions). Expect some "mentioned but not involved" actor/malware tags.
- Leaderboards/PIR/watchlist show a split actor series until `canonicalise_actors --apply` runs; watchlist/profiles added later with alias names still will not match canonical article names.
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
- **Code rollback.** `deploy.sh` restores the `:prev` images on failure and never downgrades the DB. **A code-only rollback
  to 0.8.10 needs no DB step**: 0.8.10 code keeps working against the 0.8.11 schema through the compatibility views
  (verified on 2026-10-29 by running 0.8.10 code against a database migrated to `a9e4c7b1d3f6`: `IOCRepo.upsert` twice,
  its child source rows and `add_feedback` all worked; base defaults for `valid_from`, `tlp` and `pap` applied). Caveats:
  0.8.10 does not see or honour revocations and TLP/PAP set after the upgrade, and rows it inserts get `valid_until` NULL
  until 0.8.11 runs again and its reconcile/upsert fills them. If only the 0.8.11 *deploy* failed before `migrate` ran,
  nothing needs undoing.
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

## 0.8.11 — P7a indicator lifecycle and TLP/PAP (`iocs` becomes `indicators`)

Release: not yet tagged (branch `nameless/p7-cti-model-165075`, merge to `origin/Dev` for the dev test, then PR to `main`).
Spec: `docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md`. Progress record:
`docs/LLM_ASSIST_REDESIGN.md` ("Built for 0.8.11").

**Dev verification is pending.** P7a has not been deployed to the dev instance yet, so there are no dev runtime numbers
(migration time, reconcile time, live state distribution). What is verified: the migration chain ran from an empty
database to `a9e4c7b1d3f6` locally, and the migration up/down tests and the full test suite pass. The dev baseline below
(read-only, 2026-10-28, dev on 0.8.9/0.8.10 data) predates this release. The dev result will be filled in after the dev
test. Anything not measured is marked **projection**.

### What changes in prod

- **Table rename (instant, ids and rows kept).** `iocs` → `indicators`; `ioc_sources`, `ioc_tags`, `ioc_threat_actors`,
  `ioc_feedback` → `indicator_sources`, `indicator_tags`, `indicator_threat_actors`, `indicator_feedback`; their `ioc_id`
  column → `indicator_id`. Sequences, constraints and indexes are renamed with them. `ioc_allowlist_entries` keeps its name.
  The `/api/iocs` routes do not change.
- **Compatibility views.** The migration creates five views with the old names (`iocs`, `ioc_sources`, `ioc_tags`,
  `ioc_threat_actors`, `ioc_feedback`; `indicator_id AS ioc_id`) so old read-only SQL keeps working. They are read-only by
  convention and **deprecated since 0.8.11**; a later release drops them. Do not write through them and do not point
  new queries at them.
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
  - `POST /api/iocs/{id}/feedback` now needs `manage_ioc`. The built-in `analyst` role loses the TP/FP buttons; `admin`
    and `superadmin` keep them. The web hides the buttons through `useCan("manage_ioc")`.
  - **FP revokes** the indicator: it leaves the STIX export, IOC stats, dashboard counts, campaigns, recap counts and the
    provider-enrichment queue, and it no longer counts as IOC/artefact evidence in the P6 assessment credibility and the
    source review (the P6 effect lands on the next recompute of the affected articles). **TP restores** it.
  - New `PATCH /api/iocs/{id}/marking` sets TLP/PAP.
  - The IOC page shows the indicator state and TLP/PAP.
  - The STIX IOC export carries `valid_until` and TLP 2.0 marking definitions, and leaves revoked indicators out.
- **Backups.** `tools/ops/pg_backup.py` verifies `KEY_TABLES` containing both `iocs` and `indicators`; a table that does
  not exist yet is skipped, so the pre-migration backup (taken by `make deploy`) checks `iocs` and later ones check
  `indicators`.

### Migrations (revision ids, reversible or not, rough duration/row counts seen on dev)

| Revision | Down revision | What | Reversible | Dev |
|---|---|---|---|---|
| `a9e4c7b1d3f6` (`iocs_to_indicators`) | `d7a3e1b94c52` (0.8.10 head) | Renames the five tables, `ioc_id` → `indicator_id`, sequences, constraints and indexes; adds `valid_from` (NOT NULL, backfilled from `first_seen_at`, default `now()`), `valid_until`, `revoked_at`, `revoked_by`, `tlp`, `pap` (CHECKs `ck_indicators_tlp`, `ck_indicators_pap`) and index `ix_indicators_valid_until`; creates the five compatibility views | yes: `downgrade` drops the views, drops the new columns, then reverses the renames. The migration up/down tests cover it (ids and child rows identical; `iocs` is a table again) | not run on dev yet. On a fresh DB the full chain to `a9e4c7b1d3f6` ran locally. **Projection:** seconds; renames are metadata-only, the `valid_from` backfill and the new index scan `indicators` once (about 5,500 rows on dev) |

This must be the last revision in the chain. After the deploy, `alembic_version` should read `a9e4c7b1d3f6`. The prod jump
is 0.8.2 → 0.8.11 in one `make deploy`, so this runs right after `d7a3e1b94c52` in the same `migrate` step.

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

2. **Who loses the TP/FP buttons.** The built-in `analyst` role loses them; `admin` and `superadmin` keep them. Roles are
   stored in `roles.permissions` (JSONB list), so list the roles that can see IOCs but not manage them, and the users on
   them, so you can tell those users (or grant `manage_ioc` to the role):

   ```sql
   SELECT r.name, r.is_system, count(u.id) AS users
   FROM roles r LEFT JOIN users u ON u.role_name = r.name
   WHERE r.permissions ? 'view_ioc' AND NOT r.permissions ? 'manage_ioc'
   GROUP BY 1, 2 ORDER BY 1;
   ```

3. **External readers of `iocs`.** Anything outside the app that names `iocs` (hand-run SQL, a BI dashboard, a Splunk DB
   Connect input) keeps working through the compatibility views but should be moved to `indicators` before the views are
   dropped. List them now.

### After deploy (checks with expected results: SQL, logs, UI pages)

Run SQL in the read-only `psql` session shown above.

1. **Version and migration head.**
   - `GET /healthz` returns `"version": "0.8.11"`.
   - `select version_num from alembic_version;` returns `a9e4c7b1d3f6`.
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
   - Marking a test indicator FP revokes it (state `revoked`, out of the default list and stats); TP restores it. Use a
     throwaway indicator and restore it, since this writes.
   - `GET /api/stix/iocs` contains `valid_until` and a TLP marking-definition reference, and no revoked indicator.
8. **Nothing else broke.** The Data health page and the `ioc.enrich_pending` log (every 15 minutes) show no
   `relation "iocs" does not exist` or `column "ioc_id"` errors:

   ```bash
   cd /home/privy-admin/Niskala-Intelligence && docker compose -p niskala-intelligence logs api worker --since 30m | grep -Ei 'relation "iocs|ioc_id|UndefinedTable'
   ```

   Expected: no output.

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

### Rollback / if it goes wrong

- **Code rollback.** `deploy.sh` restores the `:prev` images on failure and never downgrades the DB. **0.8.10 code reads the
  old table names, so a code rollback with the migration applied breaks the IOC pages and ingest** (the compatibility
  views are read-only and the old code writes to `iocs`). If the app is rolled back to 0.8.10, also run the DB downgrade
  below. If only the 0.8.11 *deploy* failed before `migrate` ran, nothing needs undoing.
- **DB downgrade (OPTIONAL, manual)** (WRITE, needs approval, only after the app is stopped or back on 0.8.10): `alembic downgrade d7a3e1b94c52`.
  It drops the five views, drops the new columns and index, then renames the tables back, so `iocs` is a table again with
  the same ids. Revocations (`revoked_at`) and TLP/PAP set in 0.8.11 are lost; `valid_until` is recomputed after the next
  upgrade.
- **Reconcile stuck or failing:** check the `worker` log for `indicator`; fix the cause and re-run the manual reconcile
  above (idempotent).
- **A hand-run query fails with `relation "iocs" does not exist`:** the 0.8.11 migration has not run on that database (the
  upgrade creates the compatibility views); after the migration, `iocs` works as a read-only view and `indicators` is the table.

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
- **R5: `manage_ioc` is now required for TP/FP.** A user with only `view_ioc` loses the buttons (the built-in `analyst`
  role). All dev users are superadmin today, so dev will not show it; tell prod analysts before the deploy or grant
  `manage_ioc` to the role.
- **R6: downgrade and the compatibility views.** The views occupy the old table names, so the downgrade drops them first.
  This is covered by the migration up/down test.
- **P6 recompute after FP.** A revoked indicator stops counting as IOC/artefact evidence only when the article is next
  assessed (`confidence.refresh_stories`, the daily `confidence.recompute_all` at 03:20, or a manual recompute).
- **Follow-ups:** fill the dev result (state distribution, reconcile duration) after the dev test; record the prod baseline
  and After-deploy numbers; drop the compatibility views in a later release; P7b (scoped API tokens, `/api/v2/indicators`,
  TAXII 2.1) builds on this release.
