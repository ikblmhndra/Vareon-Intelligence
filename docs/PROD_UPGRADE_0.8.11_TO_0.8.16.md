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

One `make deploy` takes prod from any of these to 0.8.16: it backs up Postgres, runs `migrate` (none of 0.8.12 to
0.8.16 has a migration), creates the new `worker-cve` service when it is missing, rebuilds, then waits for health. The
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
   - 0.8.16: record the Early Warning anomaly counts per group (30d, z 2.0) to compare after deploy.
2. **`.env`:** no new key in any of the five releases.
3. **`make deploy`** (with `sudo`). Beat restarts with it, which the 0.8.13 queue routing needs.
4. **After deploy:**
   - 0.8.12 checks (`github_poc_monitor` run length) are superseded by the 0.8.13 ones: 0.8.13 replaces the 0.8.12 cap of
     600 searches with the 90-day/KEV filter and a cap of 300.
   - 0.8.13 checks (`worker-cve` healthy, queue routing, first reconcile, the 50 missing CVEs, `/data-health`).
   - 0.8.14 checks at the next sweep slot (no long `cve_tracker` transaction, no run of `locked` syncs).
   - 0.8.15 checks: the next hourly `github_poc_monitor` runs finish in under 15 minutes, no `overlap` rows.
   - 0.8.16 checks (health version `0.8.16`, Early Warning spikes, PIR weekly coverage, Navigator export, theme, masthead shell).
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
`main`). Patch on top of 0.8.15 (`github_poc_monitor` cap 250, PR #90). The release entry may grow when the page implementation of the redesign
lands in the same PR.

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

### Migrations

None. `alembic_version` stays at `7e3b9c1d5a42`.

### Settings / .env

None.

### Before deploy

Record the current Early Warning picture for comparison: anomaly count per group (threat actors, industries,
countries, overall) at lookback 30d, z 2.0, from Intelligence > Early Warning or `GET /api/spikes`. Nothing else to
check; all other changes are read-only endpoints and web styling.

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

### One-off commands

None.

### Rollback

`make deploy` restores the `:prev` images on a failed health check. Rolling back to 0.8.15 removes the new endpoint
and the `daily` block; nothing is written to the database, so there is nothing to undo.

### Known risks

- Cached browser bundles may show old colours until a hard refresh after the web image changes.
- Early Warning anomalies change by design (zero-filled baseline). Analysts used to the old list may see entities
  appear or drop out; rollback to 0.8.15 restores the old detection.
- The weekly coverage query scans article rows by week for one PIR; check its latency on prod-sized data on first use.
