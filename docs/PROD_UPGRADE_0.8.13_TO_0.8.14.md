# Prod upgrade runbook: 0.8.13 → 0.8.14

Prod (`privy-admin@10.8.20.78`, compose project `niskala-intelligence`, repo `/home/privy-admin/Niskala-Intelligence`) runs
**0.8.13** (deployed 2026-11-06). One `make deploy` takes it to 0.8.14: backup, `migrate` (no new revision), rebuild,
health wait. The checkout is owned by root, so the user runs it with `sudo`. Older steps stay in
`docs/PROD_UPGRADE_0.8.11_TO_0.8.13.md` and `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`.

The per-release section below is kept in `docs/prod-upgrade/<version>.md` and copied here.

## Order of operations

1. **Before deploy (read-only):** the 0.8.14 check that no sweep is mid-run.
2. **`.env`:** no new key.
3. **`make deploy`.**
4. **After deploy:** the 0.8.14 checks at the next sweep (minute 0 of an hour divisible by 3, UTC). The 0.8.13 7-day
   watch continues unchanged.

Expected `alembic_version` after the deploy: **`7e3b9c1d5a42`** (unchanged).

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
