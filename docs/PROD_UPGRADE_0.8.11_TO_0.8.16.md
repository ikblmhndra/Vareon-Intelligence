# Prod upgrade runbook: 0.8.11 → 0.8.16

Prod (`privy-admin@10.8.20.78`, compose project `niskala-intelligence`, repo `/home/privy-admin/Niskala-Intelligence`) runs
**0.8.11** per the user. Older runbooks have claimed other starting versions (`docs/PROD_UPGRADE_0.8.13_TO_0.8.14.md` says
0.8.13), so **confirm the running version first** with `GET /api/health` (field `version`) and start at the section
for that version:

| Running version | Follow |
|---|---|
| 0.8.11 | every section below (0.8.12, 0.8.13, 0.8.14, 0.8.15, 0.8.16) |
| 0.8.12 | 0.8.13, 0.8.14, 0.8.15, 0.8.16 |
| 0.8.13 | 0.8.14, 0.8.15, 0.8.16 |
| 0.8.14 | 0.8.15, 0.8.16 |
| 0.8.15 | 0.8.16 |

One `make deploy` takes prod from any of these to 0.8.16: it backs up Postgres, runs `migrate` (only 0.8.16 has migrations: `b7d41e9a2c63` then `c4e8a1f2b9d6`, both additive), creates the new `worker-cve` service when it is missing, rebuilds, then waits for health. The
Deploy workflow is off and the checkout is owned by root, so this is a manual run by the user with `sudo`. Older steps
stay in `docs/PROD_UPGRADE_0.8.13_TO_0.8.14.md`, `docs/PROD_UPGRADE_0.8.14_TO_0.8.15.md`,
`docs/PROD_UPGRADE_0.8.11_TO_0.8.13.md` and `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md` for history.

The per-release sections below are kept in `docs/prod-upgrade/<version>.md` and concatenated here. Read-only SQL runs in a
read-only session (`PGOPTIONS=-c default_transaction_read_only=on`); anything marked **WRITE** needs the user's approval.

## Order of operations

0. **Confirm the running version** (`GET /api/health`) and pick the starting section from the table above.
1. **Before deploy (all read-only), for the sections you follow:**
   - 0.8.12: count of `github_poc_monitor` runs still `running` (informational; the deploy ends them).
   - 0.8.13: the "Before deploy" block (flags, missing-CVE baseline, tracker size, whether `github_poc_monitor` is
     disabled, disk). Write the numbers down for the after-deploy comparison.
   - 0.8.14: **no sweep is running** (both checks: `pg_stat_activity` and the worker log). Sweeps start at 00, 03, 06, ...
     UTC; the safest window is roughly 90 minutes to 3 hours after a slot.
   - 0.8.15: nothing to check (PoC cap, no `.env` key).
   - 0.8.16: record the Early Warning anomaly counts per group (30d, z 2.0) to compare after deploy; optionally count
     tickets with a non-email `owner_email` or a legacy status alias (queries in the 0.8.16 section, informational).
2. **`.env`:** no new key in any of the five releases. 0.8.16 adds one migration (`b7d41e9a2c63`), applied by `make deploy`.
3. **`make deploy`** (with `sudo`). Beat restarts with it, which the 0.8.13 queue routing needs.
4. **After deploy:**
   - 0.8.12 checks (`github_poc_monitor` run length) are superseded by the 0.8.13 ones: 0.8.13 replaces the 0.8.12 cap of
     600 searches with the 90-day/KEV filter and a cap of 300.
   - 0.8.13 checks (`worker-cve` healthy, queue routing, first reconcile, the 50 missing CVEs, `/data-health`).
   - 0.8.14 checks at the next sweep slot (no long `cve_tracker` transaction, no run of `locked` syncs).
   - 0.8.15 checks: the next hourly `github_poc_monitor` runs finish in under 15 minutes, no `overlap` rows.
   - 0.8.16 checks (health version `0.8.16`, Early Warning spikes, PIR weekly coverage, Navigator export, theme, masthead shell, CVE Tracker pages: risk sort, FP tab, ticket save + escalation draft, teams, lookup, lockfile dry run).
5. **One-off WRITE commands:** only the optional manual `cve.mirror_reconcile` run (0.8.13); otherwise the first one
   happens at minute :17.
6. **7-day watch (0.8.13), then the final step:** only when it passes, set `CVE_MIRROR__KEEP_LEGACY_NEW_CVE=false` in
   the prod `.env` and recreate with `docker compose ... up -d worker beat api` (details in the 0.8.13 section below).
   The watch counts from this deploy.

Expected `alembic_version` after the deploy: unchanged from 0.8.11, **`7e3b9c1d5a42`**.

---

## 0.8.12 — `github_poc_monitor` no longer fills the worker

Release: patch on top of 0.8.11 (prod runs 0.8.11 since 2026-11-05).

### What changes in prod

- `github_poc_monitor` runs at most 600 targeted GitHub searches per run (about 20 minutes at the GitHub Search
  limit of 30 per minute). Before, one run searched every non-false-positive CVE in `cve_tracker` (2,469 on prod on
  2026-11-06), took more than 80 minutes on an hourly schedule, and the overlapping runs filled all four `worker`
  slots: on 2026-11-06 RSS ingestion, maintenance tasks and notifications stopped for about five hours (see
  `docs/prod-upgrade/0.8.11.md`, Prod result).
- A larger list is split into `ceil(n / 600)` slices by `crc32(cve_id)`; the run's hour picks the slice. With 2,469
  CVEs there are 5 slices, so each tracked CVE is searched once every 5 hours instead of (in theory) every hour.
  Lists of 600 or fewer are searched in full every run, as before.
- The broad search (`cve-{year}-*` repositories, MITRE vendor lookup, the Telegram PoC alert) is unchanged.

### Migrations

None.

### Settings / .env

None. The limit is a module constant (`_TARGETED_SEARCHES_PER_RUN` in
`scrapers/src/cti_scrapers/feeds/github_poc_monitor.py`).

### Before deploy

Read-only, on the prod host:

```sql
SELECT count(*) FROM scraper_runs WHERE scraper_id = 'github_poc_monitor' AND finished_at IS NULL AND status = 'running';
```

Runs still `running` from 0.8.11 are killed by the deploy (the worker container is recreated); the reaper marks
their rows `timeout`. Nothing to do by hand.

### After deploy

1. Within two hours, the newest `github_poc_monitor` runs finish in about 20 to 30 minutes:

   ```sql
   SELECT started_at, status, round(extract(epoch FROM finished_at - started_at) / 60) AS minutes
   FROM scraper_runs WHERE scraper_id = 'github_poc_monitor' ORDER BY started_at DESC LIMIT 5;
   ```

2. No `github_poc_monitor` task is older than an hour on the worker, and the queues stay near zero:
   `docker exec niskala-intelligence-redis-1 redis-cli llen scrape.rss` (and `maintenance`, `notify`).

### One-off commands

None.

### Rollback

`tools/ops/rollback.py` (the standard `:prev` images). No schema change, so nothing else. On 0.8.11 the stall can
come back; the remedy then is the one recorded in `docs/prod-upgrade/0.8.11.md` (revoke queued runs, kill running
ones).

### Known risks

- **Longer PoC latency for tracked CVEs.** Each tracked CVE is searched every `ceil(n / 600)` hours (5 today). A new
  PoC for a tracked CVE can show up a few hours later than with an hourly search; PoCs for new CVEs found by the
  broad search are not affected.
- **The slice count grows with the tracker.** At about 14,400 CVEs a CVE is searched once a day. If the tracker grows
  past that, prioritising recent CVEs is the next step.

---

## 0.8.13 — CVE single source: hourly mirror reconcile, 30-day creation window, `worker-cve`, overlap guard, bounded `github_poc_monitor`, CVE ingest health

Release: not yet tagged (branch `nameless/cve-tracker-workflow-d01774`, merge to `origin/Dev` for the dev test, then PR to `main`).
Spec: `docs/superpowers/specs/2026-11-06-cve-single-source-design.md`. Map of the pipeline: `docs/CVE_END_TO_END.md`.

Prod facts measured read-only on 2026-11-06: `CVE_MIRROR__PROMOTE=live`, `CVE_MIRROR__KEEP_LEGACY_NEW_CVE=true`;
50 PUBLISHED 2026 CVEs from the last 7 days of `deltaLog.json` are absent from the mirror (mostly one burst,
CVE-2026-95731..95777, 2026-11-03 19:50 UTC; also CVE-2026-74846 and CVE-2026-121577); the `worker` pool was held by
4 concurrent `github_poc_monitor` runs.

### What changes in prod

- **New service `worker-cve`** (`-Q cve -c 1`, same image and env as `worker`). `make deploy` creates it with `up -d` and
  includes it in the wait-healthy and rollback service lists. `cve.mirror_sync`, `cve.mirror_reconcile`,
  `cve.promote_entry` and `cve.mirror_purge` move to the new queue `cve`; `cve.enrichment_sweep` stays on `maintenance`.
  Beat must restart (it does in `make deploy`) or the old routing keeps sending them to `maintenance`.
- **Hourly `cve.mirror_reconcile`** (minute 17). It downloads `deltaLog.json` (~24 MB, ~580 MB/day), compares each CVE's
  `dateUpdated` with `cve_records.modified_at`, and refetches whatever is missing or outdated through the normal
  record pipeline. The first run is expected to fix the ~50 missing CVEs. Records fetched and deliberately not stored
  (not PUBLISHED, outside retention) are remembered in `job_state["cve_mirror.reconcile"]` (`skips`) and not refetched.
- **30-day creation window.** Sync and reconcile create a tracker row only for records published within the last 30
  days. Older matching records still update an existing row but no longer create one (this is what produced the
  786-row Linux flood on 2026-11-05). `cve.promote_entry` and `make promote-cve-mirror --since` keep creating rows for
  history.
- **Overlap guard.** `Runner.execute` refuses to start a scraper while a younger-than-stale `running` run of the same
  scraper exists; the refused run is stored with the new status `overlap` (neutral in health).
- **Bounded `github_poc_monitor`.** Only CVEs published within 90 days or in CISA KEV are searched, and each run takes a
  rotating slice of at most ~300 (stable crc32 of `cve_id` mod `k`, `k = ceil(n/300)`, by hour). Prod: 1,425 of 2,469
  candidates, so every CVE is searched about every 5 h and a run takes ~10 min.
  This replaces the 0.8.12 hotfix (`_TARGETED_SEARCHES_PER_RUN = 600` over every tracked CVE, PR #87): the slice is
  now taken after the 90-day/KEV filter and capped at 300.
- **`/data-health` gets a "CVE ingest" block** with `status` off / red / amber / ok. Red: last sync older than 15 min.
  Amber: no reconcile yet, last reconcile older than 2 h, or its last report has status `error`.
- Existing Path A false-positive or REJECTED tracker rows (e.g. the 10 REJECTED `Linux` rows CVE-2026-99217, -99243,
  -99252, -99262..-99268, and the Snowflake / ingress-nginx text-gate matches) are **not cleaned** by this release.

### Migrations

None. No new revision; `alembic_version` stays at the 0.8.11 head. State lives in `job_state` (key
`cve_mirror.reconcile`), created on first write.

### Settings / .env (recommended PROD values)

- No new key, nothing required before merge.
- Final step after the watch period (below): `CVE_MIRROR__KEEP_LEGACY_NEW_CVE=false` (already supported; it is `true`
  on prod today). `CVE_MIRROR__PROMOTE` stays `live`, `CVE_MIRROR__ENABLED` stays `true`.

### Before deploy

Read-only (`PGOPTIONS=-c default_transaction_read_only=on`). Write the results down for the after-deploy comparison.

1. Which flags are live: `docker compose ... exec api env | grep CVE_MIRROR` shows `PROMOTE=live`,
   `KEEP_LEGACY_NEW_CVE=true`.
2. Missing-CVE baseline (the reconcile should drive this to 0): from the `deltaLog.json` window, the 50 CVEs above are
   absent, for example
   `SELECT cve_id FROM cve_records WHERE cve_id IN ('CVE-2026-95731','CVE-2026-95777','CVE-2026-74846','CVE-2026-121577');`
   returns 0 rows.
3. Tracker size baseline: `SELECT count(*) FROM cve_tracker;` (compare after deploy: growth should stay small, no
   burst of old CVEs).
4. If `github_poc_monitor` was disabled by hand (`cti-scraper disable github_poc_monitor`, rollout step 1), note it:
   it stays disabled until the checks below pass (the disable is a `ScraperConfig` override and survives the deploy).
5. Disk: one more container, no new volume; check free space as for any deploy.

### After deploy

1. `docker compose ps` shows `worker-cve` healthy. `docker compose logs worker-cve | tail` shows it consuming
   `cve.mirror_sync` every 5 min.
2. Beat picked up the routing: the `maintenance` queue no longer collects `cve.mirror_sync`
   (`docker compose -p niskala-intelligence exec redis redis-cli LLEN maintenance` stays low).
3. After the first reconcile (minute :17, or one-off below): the log line `cve_mirror_reconciled` carries `planned`,
   `missing`, `outdated`, `fixed`, `skipped`, `failed`, `queued`, `duration_ms`. The first runs plan a large backlog (old
   CVEs updated in the last 30 days: mostly skipped once, processed 500 per hour, newest first, `queued` is what waits
   for the next run). The ~50 recent missing CVEs are fixed in the first run; `failed` 0. A reconcile run holds the
   mirror lock for its duration, so a sync tick may report `locked` meanwhile.
4. The 50 CVEs are in the mirror (query from Before deploy now returns the rows) and, for those matching a monitored
   tech and published within 30 days, in the tracker.
5. UI: `/data-health` shows the CVE ingest block with status `ok`.
6. `github_poc_monitor`: re-enable it now if it was disabled (`cti-scraper enable github_poc_monitor`, then restart
   `beat`). Its runs should finish in ~10 min.
7. **7-day watch (spec section 4, step 4):** reconcile `fixed` near 0 after the first day and no CVE ingest `red`; no sync gap
   over 15 min (block never red); PoC runs under 15 min; no `overlap` storms in Scrapers > Recent Runs. Only when all
   four hold, do the final step.
8. **Final step, retire `new_cve`:** set `CVE_MIRROR__KEEP_LEGACY_NEW_CVE=false` in the prod `.env`, then recreate with
   `docker compose ... up -d worker beat api` (not `restart`, which keeps the old environment). `new_cve` is then not
   scheduled, the Runner refuses it, and health shows it as disabled.

### One-off commands (dry-run first, need user permission)

- Run a reconcile now instead of waiting for :17 (**WRITE**, user approval): from the `worker-cve` container,
  `python -c "from cti_worker.tasks.cve_mirror import cve_mirror_reconcile; print(cve_mirror_reconcile.run())"` (same code
  as the beat task, under the same advisory lock). On dev, run it once after deploy and read the report before prod.
- Clean old Path A false positives or REJECTED rows: not part of this release. If wanted, it is a separate read-only
  listing first, then a per-row decision by the user.
- A gap older than 30 days (beyond `deltaLog.json`): `make backfill-cve-mirror SOURCE=<clone or zip of cvelistV5>`
  (unchanged, see `docs/CVE_CATALOG_CUTOVER.md`).

### Rollback

- **Code:** `tools/ops/deploy.sh` auto-rolls back to the `:prev` images on a failed health check, including
  `worker-cve`. No migration to undo.
- **Retiring `new_cve`:** set `CVE_MIRROR__KEEP_LEGACY_NEW_CVE=true` and `up -d worker beat api`. The scraper runs again
  on its next hourly slot (overlap-guarded).
- **`github_poc_monitor` too heavy again:** `cti-scraper disable github_poc_monitor`, restart `beat`.
- Rolling the images back to 0.8.12 leaves `worker-cve` without tasks; stop it (`docker compose stop worker-cve`) and
  note that 0.8.12 routes CVE tasks to `maintenance` again. The `job_state` reconcile key is harmless.

### Known risks and follow-ups

- **Download volume:** `deltaLog.json` is fetched once per hour, about 24 MB, so ~580 MB/day outbound from the prod
  host to GitHub. Check that this is acceptable on the host's network.
- **Old CVEs no longer enter on their own.** An old CVE whose CNA adds a monitored product to `affected` months later
  will not appear by itself (same case as the 786-row flood). It stays in the CVE DB tab; an analyst can promote the
  entry history (`cve.promote_entry`, `make promote-cve-mirror --since`).
- **First reconcile precision:** if `cve_records.modified_at` and `dateUpdated` differ in precision, the first run could
  plan thousands of outdated records. The reconcile cap (500 per run, newest first, overflow left for the next run) spreads
  the work across runs; check `outdated` in the first report (expected near 0).
- **Pool pressure was the `worker` pool:** it was saturated by 4 concurrent `github_poc_monitor` runs (oldest 4.9 h, the
  `maintenance` queue 291 deep with 40 `cve.mirror_sync`). The `cve` queue and the overlap guard remove that cause;
  the `github_poc_monitor` long tail (CVEs older than 90 days and not in KEV) is no longer searched for PoCs.
- **`deltaLog.json` lags `delta.json`** on the CDN; reconcile only adds work and never moves the sync cursor, so a lag
  cannot lose data.
- **Path A rows stay:** REJECTED and false-positive rows written by `new_cve` remain until someone removes them.

---

## 0.8.14 — CVE enrichment sweep without hour-long transactions

Release: not yet tagged (branch `nameless/cve-enrichment-sweep-tx`; merge to `origin/Dev` for the dev test, then PR
to `main`). Patch on top of 0.8.13, which prod runs since 2026-11-06.

### What changes in prod

- `cve.enrichment_sweep` (every 3 h at minute 0, queue `maintenance`) runs KEV, Exploit-DB and EPSS each in its own
  database session and commits per step.
- The Exploit-DB step commits after each CVE and writes each CVE in a savepoint. Row locks on `cve_tracker` are held for
  one write, not for the whole sweep. The same applies to the manual "Exploit-DB Lookup" button.
- A Redis lock `cti:cve:enrichment_sweep:lock` (TTL 3 h) allows one sweep at a time. A second one returns
  `{"status": "skipped"}` and logs `cve_enrichment_skipped_running`.

Why: on 2026-11-06 one sweep held a transaction for more than 75 minutes (`idle in transaction`, row locks on
`cve_tracker`). A second sweep and `promote_cve_mirror.py --apply` waited behind it, and because that tool holds the
mirror ingest lock, `cve.mirror_sync` and `cve.mirror_reconcile` returned `locked` for about 35 minutes.

### Migrations

None. `alembic_version` stays at `7e3b9c1d5a42`.

### Settings / .env

None.

### Before deploy

Read-only:

1. No sweep is running, so the deploy does not cut one off mid-way. Both checks, whatever the transaction age (a
   sweep that started a minute ago counts too):
   - `SELECT count(*) FROM pg_stat_activity WHERE query ILIKE '%cve_tracker%' AND state <> 'idle' AND pid <> pg_backend_pid();`
     returns 0;
   - the worker log has no `Task cve.enrichment_sweep[...] received` without a matching `succeeded` since the last
     sweep slot (`docker compose ... logs --since 3h worker | grep 'cve.enrichment_sweep\['`).

   Sweeps start at 00, 03, 06, ... UTC and, on 0.8.13, keep one transaction open for an hour or more, so the safest
   window is roughly 90 minutes to 3 hours after a slot.

### After deploy

1. At the next sweep (minute 0 of an hour divisible by 3, UTC) the worker log shows one
   `Task cve.enrichment_sweep[...] received`, and no `cve_tracker` transaction older than a few seconds:
   `SELECT state, now() - xact_start FROM pg_stat_activity WHERE query ILIKE '%cve_tracker%';`
2. `cve.mirror_sync` keeps returning `ok` or `noop` during the sweep (worker-cve log), never a run of `locked`.
3. `exploit_db_checked_at` advances during the sweep, not only at its end:
   `SELECT max(exploit_db_checked_at) FROM cve_tracker;` run twice a few minutes apart while it runs.

### One-off commands

None.

### Rollback

`make deploy` restores the `:prev` images on a failed health check. Rolling back to 0.8.13 brings back the single
long transaction; no data to undo.

### Known risks

- The Redis lock key survives a worker crash for up to 3 h; during that time scheduled sweeps are skipped (logged).
  Delete the key by hand only if no sweep is running.
- The sweep still re-checks every true-positive CVE each run (no freshness filter), so its duration still grows with
  the tracker; only the locking changed.

---

## 0.8.15 — `github_poc_monitor` targeted searches capped at 250 per run

Release: not yet tagged (branch `nameless/poc-search-cap-250`; merge to `origin/Dev` for the dev test, then PR to
`main`). Patch on top of 0.8.14, which prod runs since 2026-11-07.

### What changes in prod

- `github_poc_monitor` searches at most about 250 tracked CVEs per run (`POC_SEARCH_CAP`, was 300). The candidates are
  unchanged: CVEs published within 90 days or in CISA KEV.
- Prod on 2026-11-07: 1,425 candidates, so the rotation grows from 5 to 6 hourly slices. Each CVE is searched about
  every 6 hours instead of every 5.

Why: after 0.8.13/0.8.14, 14 consecutive prod runs all finished `ok` with no overlap, but averaged 1,076 s
(about 18 min), above the 15 min target. The broad search and MITRE lookups come on top of the targeted searches at
GitHub's 30 searches per minute.

### Migrations

None. `alembic_version` stays at `7e3b9c1d5a42`.

### Settings / .env

None. The cap is a module constant (`POC_SEARCH_CAP` in `scrapers/src/cti_scrapers/feeds/github_poc_monitor.py`).

### Before deploy

Nothing to check.

### After deploy

1. The next hourly `github_poc_monitor` runs finish in under 15 minutes:
   `SELECT status, round(extract(epoch from finished_at - started_at)) FROM scraper_runs WHERE scraper_id = 'github_poc_monitor' ORDER BY started_at DESC LIMIT 6;`
2. No `overlap` rows for `github_poc_monitor` in Scrapers > Recent Runs.

### One-off commands

None.

### Rollback

`make deploy` restores the `:prev` images on a failed health check. Rolling back to 0.8.14 only brings back the cap of
300.

### Known risks

- PoCs for long-tail candidates are found up to about one hour later than with 0.8.14 (6 slices instead of 5). Recent
  and KEV CVEs are all still in the candidate set.

---

## 0.8.16 — FigCraft redesign data: PIR weekly coverage, spike daily series, Navigator layer from the heatmap

Release: not yet tagged (branch `claude/figcraft-design-data`; merge to `origin/Dev` for the dev test, then PR to
`main`). Patch on top of 0.8.15 (`github_poc_monitor` cap 250, PR #90). The release also carries the CVE Tracker redesign (backend additions, UI and one additive migration) and the Exec redesign (daily shared brief, one more additive migration).

### What changes in prod

- New endpoint `GET /api/pir/{pir_id}/coverage/weekly` (`PIRWeeklyCoverage`): weekly article counts per PIR for the PIR
  coverage chart. Read-only query on existing tables.
- `GET /api/spikes` now has a typed response (`SpikesResponse`) with a new `daily` block (daily series per spiking
  entity). Existing keys are unchanged.
- **Spike detection changes:** the baseline mean and standard deviation now count baseline days without articles as 0
  (before, only days with articles counted). `baseline_mean` drops for every entity with empty baseline days; sparse
  entities get higher z-scores, while entities with uneven daily counts can get lower ones (their std rises). The
  number and order of Early Warning anomalies change after deploy in both directions. An entity still needs at least 5 baseline days with
  articles. Exec dashboard industry spikes use the same detector and change the same way.
- MITRE page: "Open in Navigator" now opens ATT&CK Navigator and downloads the layer, with a hint to load it via
  "Open Existing Layer → Upload from local" (the old `#layerURL=` link never worked behind login).
- `GET /api/mitre/navigator-layer` and `/navigator-export` accept the optional `top_rows`, `top_ttps` and `ttp_source`
  parameters, so the exported ATT&CK Navigator layer matches the visible heatmap. Without them the output is unchanged.
- Web: one risk-tier scale (LOW 0-39, MED 40-69, HIGH 70-100) in the risk matrix, ink focus ring, warning colour
  `#A04A07`, breakpoint rule at `lg` (1024px), and a darker `--input` border token (3:1 contrast or better) used by
  Input, Textarea, Select and Checkbox.
- Web: new shell following the FigCraft mockup: a top masthead with a "More" menu replaces the sidebar (a Menu button
  below 1024px), with a utility bar for the client switcher and account menu. Buttons, fields, underline and pill tabs,
  segmented controls, chips, cards (flat, bordered, no shadow), tables and dialogs follow the mockup too.
- CVE Tracker redesign, backend: risk score 0-100 with the `sort_by=risk` option; False positive tab filter with reason and note;
  ticket timestamps and a ticket XLSX export; stricter owner email validation (new or changed values must be a valid
  email, at most 200 characters; an unchanged legacy value can still be saved); the CVE response carries the KEV ruling
  (`kev_date_added`, `kev_due_date`, `kev_required_action`); owner teams and an escalation EMAIL DRAFT to the team lead (Microsoft
  Graph; nothing is sent and there is no Telegram); techstack match counts and coverage; per-client catalog hide; CVE DB
  mirror meta and `covered_by_vendor`; check status `running_since` and per-source retry; live CVE lookup (NVD, CIRCL,
  Exploit-DB, EPSS; cached and rate limited); lockfile dry run with ecosystem and project path, plus `Gemfile.lock`,
  `yarn.lock` and `go.sum` parsers. With ecosystem "Detect from file", a file name the parser does not recognise now
  returns 422 (before, it was silently parsed as `requirements.txt`); an explicit ecosystem still forces that parser. New dependency: `email-validator`.
- CVE Tracker redesign, web: CVEs master-detail with risk sort, Open/Acknowledged/False positive tabs, More actions and
  Select mode; Ticketing master-detail and Teams; Monitored Tech, All Tech, CVE DB, Dashboard and Packages restyled;
  all times render in the browser timezone. The Ticketing tab is hidden for roles without `manage_cve`, and the detail
  modal is replaced by a side panel.
- Intelligence pages (PIR, RFI, Source reliability, IOC, Entities, MITRE) follow the FigCraft mockup. Data changes:
  - `GET /api/pir?include_campaigns=true` runs the uncached campaign pipeline (the PIR page fetches it in the background).
    PIR to campaign links now carry `&days=30`; the Campaign clusters page reads `?days=`.
  - New CSV exports `GET /api/sr/entries/export` and `GET /api/iocs/export`: both need `export_data`, write an audit row
    and guard against CSV formulas. The IOC export is capped at 50 000 rows and sets `X-Export-Truncated` when cut; the
    Source reliability export is capped at 5 000 rows (one row per source) and has no truncation header.
  - Entities list `sort=mentions` orders by the 30-day mention count (descending), ties by name then id; `total` is
    returned on the first page only. Measured about 50 ms per page with 200 000 mentions on a local copy, no new index;
    the 30-day count scans `entity_mentions`, so cost grows with the total number of mentions.
  - `PUT /api/rfi/{id}` and `PUT /api/pir/{id}` accept an explicit `null` to clear nullable fields (RFI `due_date`,
    `linked_pir`; PIR `start_date`, `end_date`). Before, a cleared value was silently ignored; `null` on a required field
    is still ignored.
  - Entity profile AI summaries fill in only after a profile is regenerated. The ATT&CK sync card moved from
    Entities > Techniques to the MITRE heatmap page.
  - No migration (Alembic head stays `b7d41e9a2c63`) and no new env keys for this part.
- Executive dashboard redesign (Exec page), backend:
  - **Shared daily brief.** One stored executive brief per Asia/Jakarta date, platform-wide and identical for every
    client (table `exec_briefs`, no `client_id`). Beat task `exec.brief_daily` (queue `maintenance`) runs hourly from
    06:00 to 18:00 Jakarta time (`WORKER__REPORT_UTC_OFFSET_HOURS`, 7 on prod, so UTC `0-11,23`). A cheap check returns
    `present` without a lock or LLM call when today already has a row; otherwise it takes a Redis lock
    (`exec_brief:<date>`), generates with the default filters (90 days) and inserts with `ON CONFLICT DO NOTHING`. So
    there is at most one LLM call per day plus retries of failed attempts. A failure leaves no row and the next hour
    tries again.
  - Manual `POST /api/exec/brief` (needs `manage_intel`) replaces that day's brief for every client. `days` is now
    bounded to 7-365, the analyst-only and per-client parts are gone, the response is `ExecBriefOut` (it was
    `{brief, generated_at}`; only the web consumed it) and an LLM failure returns 502.
  - New read endpoints `GET /api/exec/brief` and `GET /api/exec/brief/dates` (router-level `view_intel`, window of the
    last 30 days).
  - **Retention.** `exec.purge_briefs` runs daily at 03:45 UTC and keeps 30 days.
  - `GET /api/exec/dashboard-v2` gained `monthly_totals`, leaderboard velocity and top sectors per actor, and the top
    actor per sector. Existing keys are unchanged.
- Executive dashboard redesign, web: `/exec` has a Briefing | Analyst board switch (`?view=`); the Export CSV button
  is shown only with `export_data`; a "More signals" row (campaign clusters, source reliability, country trend); the
  IOC "Remove from feeds" dialog shows errors inline.
- X Intel, Recap and Newsletter redesign (4a), backend and web:
  - **Migrations:** none. **Settings:** none. Image rollback only, no data change.
  - **Contract (additive).** `GET /api/tweets` and `GET /api/tweets/stats` accept two new optional query parameters:
    `has_cve` (bool) and `signal` (`zero_day|databreach|ot|report`). The stats response is untyped and gains keys: six
    period counters (confirmed incidents, APAC, CVE, data breach, zero-day, OT) and `top_victims`. Existing keys are
    unchanged.
  - **Behaviour.** Free-text search now matches handle, victim and CVE (before, fewer fields), and `%` and `_` are
    matched literally. A search can therefore return more rows than before.
  - Web: X Intel filters apply live (the Apply/Reset buttons are gone); Newsletter uses a three-column composer; Recap has a History select, a Generate dialog and exports PDF through the browser print dialog, and newsletter history opens as a side sheet.
- Scrapers and Data health redesign (4b), backend and web:
  - **Migrations:** none. **Settings:** none.
  - **Contract (additive).** `GET /api/data-health` gains three fields: `pipeline` (`last_24h` and `last_7d`, each with
    `items_found`, `items_new`, `articles_published`), `queues.depths` (the depth of the seven Celery queues; `null` when
    Redis is unreadable) and `llm.calls_per_hour` (24 UTC hourly buckets `{hour, ok, failed}`). Existing keys are unchanged.
  - Web: Scrapers uses a side panel (recent runs, config summary, actions, dry-run result) in place of the detail dialog,
    status tiles and a filter toolbar; Data health gets a pipeline flow, queue depths, a stacked calls-per-hour LLM chart,
    status tiles and a "More checks" section. Times use the browser timezone, tone labels read OK / WATCH / ACTION, and
    the scraper write buttons are hidden without `manage_scraper`.
- Access redesign (4c), backend and web:
  - **Migrations:** none. **Settings:** none.
  - **Behaviour change.** An admin password reset now flags the account (`force_pw_change`): the user must choose a new
    password at the next sign-in and gets 403 "Password change required" from every other endpoint until then.
    **Existing users are unaffected**: no row is updated by the deploy, only resets made after it set the flag. Any
    account that a script signs in with (username and password) must not be reset from the Admin page without
    completing the change by hand afterwards.
  - **Contract (additive).** `GET /api/auth/me` adds `signed_in_at`; a login 429 adds `Retry-After` (seconds, clamped
    to 1-60). `docs/openapi.json` is unchanged.
  - **URLs.** `/admin/users` still works; the other Admin sections moved to their own routes (Users, Roles, Password
    policy, Clients, API tokens, Audit log, Third-party keys).
  - Web: the Login page is redesigned in English with no raw API messages, a Retry-After countdown, and a forced
    password change on the login page itself followed by an automatic re-sign-in. A "Your session has ended" dialog
    replaces the silent redirect to `/login`. Admin is split into seven pages with a side nav; Users gets overview
    tiles and the audit log gets a client-side CSV export.

### Migrations

Two additive migrations, applied automatically by `make deploy` (the `migrate` service), in this order: `b7d41e9a2c63`
(CVE Tracker redesign) on top of `7e3b9c1d5a42`, then `c4e8a1f2b9d6` (Exec redesign). The Intelligence part has none.

Revision `b7d41e9a2c63`: It is additive and all new columns are nullable: `cve_false_positives` reason and note,
`cve_tickets.updated_by` and `escalation_notified_at`, new tables `cve_owner_teams` and `catalog_family_hides`, and
`monitored_packages.source_path`. It backfills owner teams from the distinct ticket `owner_team` values and
`cve_tickets.updated_by` from `acknowledged_by`.

Revision `c4e8a1f2b9d6` creates the new table `exec_briefs` (one row per Jakarta `brief_date`, with the generation
metadata and the stored brief; no backfill). It is additive and nothing in the old code reads it. After deploy
`alembic_version` is `c4e8a1f2b9d6`.

### Settings / .env

None. The brief schedule reuses `WORKER__REPORT_UTC_OFFSET_HOURS` (7 on prod); `.env.example` and `.env.prod.template`
are unchanged.

### Beat restart (required for the Exec brief)

The beat schedule is built once at import, so the two new entries (`exec-brief-daily`, `exec-brief-purge`) load only
when `beat` starts. `make deploy` recreates it; a manual `docker compose ... up -d` of other services does not. The
workers pick up the tasks on deploy. Check with `celery -A cti_worker.celery_app inspect registered` (tasks
`exec.brief_daily` and `exec.purge_briefs`) and the beat log line for `exec-brief-daily`.

### Daily LLM cost (Exec brief)

About **one `exec_brief` call per day** for the whole platform (roughly 1.5-2.5 k tokens), plus one catch-up attempt per
hour while the gateway fails (at most 13 a day), plus manual generations. Check after deploy:

```sql
SELECT date(at) AS day, status, count(*), sum(prompt_tokens) AS prompt, sum(completion_tokens) AS completion
FROM llm_calls WHERE task = 'exec_brief' GROUP BY 1, 2 ORDER BY 1 DESC;
```

### Before deploy

Record the current Early Warning picture for comparison: anomaly count per group (threat actors, industries,
countries, overall) at lookback 30d, z 2.0, from Intelligence > Early Warning or `GET /api/spikes`.

Optional, read-only (`PGOPTIONS=-c default_transaction_read_only=on`), informational only: the app handles both cases,
but the numbers tell you what legacy data exists.

```sql
-- tickets whose owner_email is set but does not look like an email (they can still be re-saved unchanged)
SELECT count(*) FROM cve_tickets WHERE coalesce(owner_email, '') <> '' AND owner_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$';
-- tickets with a legacy status alias (shown under the canonical status tabs)
SELECT remediation_status, count(*) FROM cve_tickets
WHERE lower(coalesce(remediation_status, '')) IN ('pending', 'completed', 'not affected', 'not applicable')
   OR remediation_status IN ('open', 'in progress', 'resolved', 'closed', 'risk accepted')
GROUP BY 1;
```

Nothing else to check; all other changes are read-only endpoints and web styling.

### After deploy

1. `GET /api/health` reports version `0.8.16`.
2. Intelligence > Early Warning: the spike view still renders (it reads `/api/spikes`); the response now includes `daily`.
   Compare with the counts recorded before deploy: different anomalies and lower `baseline_mean` values are expected
   (empty baseline days now count as 0); an empty list where there were many anomalies is not.
3. PIR page: `GET /api/pir/<id>/coverage/weekly` returns 200 with a weekly series for an existing PIR.
4. MITRE page: "Open in Navigator" opens ATT&CK Navigator and downloads the layer; uploading it ("Open Existing
   Layer → Upload from local") shows the same techniques as the visible heatmap.
5. Spot-check light and dark theme: field borders, focus ring and the risk matrix colours.
6. Shell: the masthead nav shows on every page (Dashboard, Newsroom, CVE Tracker, Intelligence, Exec, X Intel, Recap,
   Newsletter, More), the active item has the underline, and below 1024px the nav collapses into the Menu button.
   Open one dialog (e.g. Intelligence > PIR > New PIR) in light and dark: field borders visible, footer divider only.
7. CVE Tracker: `alembic_version` is `b7d41e9a2c63`. CVEs tab: sort by risk works, the False positive tab lists
   items with reason and note. Ticketing: save a ticket (the updated timestamp changes); an escalation produces a
   draft in the shared mailbox, once, and not again on re-save (needs the existing Microsoft Graph config and a team
   lead email; nothing is sent). Teams list shows the names backfilled from ticket owner teams. Run one live lookup
   of a known CVE, and a lockfile dry run (e.g. a `yarn.lock`) in Packages. A `cve_reader` user must not see Ticketing.
8. Intelligence > Entities: the Entities page requests `sort=mentions` (the API default sort is `name`). Watch the latency of
   the first pages; expect tens of ms, and investigate if it grows into seconds, since the 30-day count scans `entity_mentions`.
9. PIR page: the campaign matches fill in after the list renders; a PIR campaign link opens Campaign clusters with the
   30-day window. IOC and Source reliability CSV exports download for a role with `export_data`.

10. Exec brief (read-only): `alembic_version` is `c4e8a1f2b9d6`. Today's brief appears after 06:00 Jakarta time (or at
    the first hourly tick after the deploy hour, until 18:00):
    `SELECT brief_date, generated_by, generated_at FROM exec_briefs ORDER BY brief_date DESC LIMIT 3`. The query in
    "Daily LLM cost" shows one `exec_brief` row per day (not one per hour). Failures show in `/data-health` (LLM,
    task `exec_brief`) and the worker log `exec_brief_daily_failed`; the next hour retries. Generating by hand from
    Exec > Briefing (`manage_intel`) is an LLM call; do it only with the operator's go.
11. `exec.purge_briefs` is registered and its log line `exec_briefs_purged` appears after 03:45 UTC (nothing to delete
    in the first 30 days).
12. Exec page: `/exec` loads for an analyst and an exec role, with the Briefing | Analyst board switch. Without
    `export_data` there is no Export CSV button. The More signals row renders, and a failing IOC "Remove from feeds"
    shows its error inside the dialog.

13. X Intel, Recap and Newsletter (read-only): `GET /api/tweets/stats?signal=ot` and `?has_cve=true` return 200 with
    the new counters and `top_victims`; searching a victim name or a CVE id on X Intel finds rows. Recap opens, and
    Export PDF opens the browser print dialog. Newsletter history opens as a side sheet.

14. Scrapers and Data health (read-only): open `/data-health`; the seven queue depths show numbers (not dashes) and the
    LLM chart has 24 hourly slots. `/scrapers` opens a source in the side panel.

15. Access (read-only): sign in, open `/admin/users` and confirm the "Your session" card shows a sign-in time. Reset a
    test account (not one a script uses) and confirm its STATUS reads "Reset pending".

Optional, only with the operator's go: regenerate the profiles of watched actors to fill the new AI summaries (one LLM
call each).

### One-off commands

None.

### Rollback

`make deploy` restores the `:prev` images on a failed health check; it never auto-downgrades the database. Rolling back
to 0.8.15 removes the new endpoints and the `daily` block. The `b7d41e9a2c63` migration is additive (nullable columns
and new tables the old code ignores), so it is safe to leave in place; no manual downgrade is needed. The same holds for
`c4e8a1f2b9d6`: after an image rollback `exec_briefs` is simply unused. Downgrading that migration (`alembic downgrade
-1`, never automatic) drops the stored briefs; they are regenerated from the next 06:00 run. The X Intel, Recap and Newsletter part (4a) has no migration or data change: an image rollback just drops the two optional parameters and the extra stats keys. The Scrapers and Data health part (4b) has no migration or data change: an image rollback only drops the three additive `data-health` fields. The Access part (4c) has no migration: an image rollback only; flags set while 0.8.16 ran stay set and the old forced dialog still handles them.

### Known risks

- Cached browser bundles may show old colours until a hard refresh after the web image changes.
- Early Warning anomalies change by design (zero-filled baseline). Analysts used to the old list may see entities
  appear or drop out; rollback to 0.8.15 restores the old detection.
- The weekly coverage query scans article rows by week for one PIR; check its latency on prod-sized data on first use.
- Entities `sort=mentions` and `include_campaigns=true` cost grows with data (mention rows; uncached campaign pipeline).
  Check latency on prod-sized data after deploy.
- Exec brief: a whole-day LLM or beat outage across 06:00-18:00 Jakarta leaves the date empty (the card shows
  yesterday's brief with a "not ready yet" notice; manual Generate still works). A manual brief replaces the shared
  brief for every client until the next morning. If `beat` is not restarted the brief never runs.
