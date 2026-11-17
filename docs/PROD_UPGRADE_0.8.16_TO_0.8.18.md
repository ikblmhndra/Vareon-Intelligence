# Prod upgrade 0.8.16 → 0.8.18

Prod runs 0.8.16 since 2026-11-16. Per-release details: `docs/prod-upgrade/0.8.17.md` (IOC enrichment fix, branch
`fix/ioc-enrich-invalid-url`, present only once that release is merged) and `docs/prod-upgrade/0.8.18.md` (Ticketing
pagination, CVE list sort).

## Steps

1. Run the 0.8.17 "Before deploy" baseline queries if 0.8.17 is part of this upgrade.
2. `make deploy`. No migration and no new `.env` keys in either release (`alembic_version` stays `d9f2b6a4c1e7`).
3. Run the "After deploy" checks of each release in order: 0.8.17 (no `InvalidURL` from `ioc.enrich_pending`), then
   0.8.18 (CVE list sort, Ticketing pager, health reports `0.8.18`).

## Rollback

`make deploy` restores `:prev` images on a failed health check. Neither release changes the database.
