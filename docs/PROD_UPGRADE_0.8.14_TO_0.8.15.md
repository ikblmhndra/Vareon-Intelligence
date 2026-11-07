# Prod upgrade runbook: 0.8.14 → 0.8.15

Prod (`privy-admin@10.8.20.78`, compose project `niskala-intelligence`, repo `/home/privy-admin/Niskala-Intelligence`) runs
**0.8.14** (deployed 2026-11-07). One `make deploy` takes it to 0.8.15: backup, `migrate` (no new revision), rebuild,
health wait. The checkout is owned by root, so the user runs it with `sudo`. Older steps stay in
`docs/PROD_UPGRADE_0.8.13_TO_0.8.14.md`, `docs/PROD_UPGRADE_0.8.11_TO_0.8.13.md` and
`docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`.

The per-release section below is kept in `docs/prod-upgrade/<version>.md` and copied here.

## Order of operations

1. **Before deploy:** nothing to check.
2. **`.env`:** no new key.
3. **`make deploy`.**
4. **After deploy:** the 0.8.15 checks on the next `github_poc_monitor` runs. The 0.8.13 7-day watch (until about
   2026-11-13) continues unchanged.

Expected `alembic_version` after the deploy: **`7e3b9c1d5a42`** (unchanged).

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
