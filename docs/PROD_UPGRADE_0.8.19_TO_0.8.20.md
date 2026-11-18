# Prod upgrade runbook: 0.8.19 → 0.8.20

Prod (`privy-admin@10.8.20.78`, compose project `niskala-intelligence`, repo `/home/privy-admin/Niskala-Intelligence`)
should run **0.8.19** before this release. Confirm the running version first (`GET /healthz`); for older versions follow
`docs/PROD_UPGRADE_0.8.18_TO_0.8.19.md` (and the runbooks it points to) before this one.

One `make deploy` (run by the user with `sudo`; the Deploy workflow is off and the checkout is owned by root) takes prod
to 0.8.20. There are no migrations and no new `.env` keys.

Per-release checks: `docs/prod-upgrade/0.8.20.md`. Its content is repeated below.

---

## 0.8.20 — IOC reputation enrichment no longer stalls on malformed IOC values

Release: not yet tagged (branch `fix/ioc-enrich-invalid-url`; merge to `origin/Dev` for the dev test, then PR to
`main`). Patch on top of 0.8.19 (merge after PR #93). Numbered 0.8.17 when written; renumbered because 0.8.18 and 0.8.19 shipped first.

### What changes in prod

- `ioc.enrich_pending` (every 15 min) no longer crashes on an IOC value that httpx cannot send. Values with whitespace or
  non-printable characters are skipped before any lookup (card `unknown`, reason `malformed value (contains whitespace)`),
  and an `httpx.InvalidURL` from a provider lookup becomes an `unknown` card (`rejected: value cannot be sent (InvalidURL)`)
  instead of an unhandled exception.
- The IOC extractor no longer matches across line breaks: spaces around a defang separator are horizontal only, so text
  like `2.34.2.` at the end of a line followed by `16` is no longer stored as the IP `2.34.2.\n16`.

Why: prod read-only check on 2026-11-16 found `ioc.enrich_pending` raising `InvalidURL("Invalid non-printable ASCII
character in URL, '\n' ...")` every 15 minutes. 16 stored IOCs contain a newline (oldest from 2026-09-26). The failing IOC
never got a card, so it stayed at the head of the queue and the provider made no progress; 742 domains, 554 URLs and about
670 hashes were waiting for enrichment (IPs were fine).

### Migrations

None. `alembic_version` stays at `d9f2b6a4c1e7`.

### Settings / .env

None.

### Before deploy

Record the baseline (read-only):

```sql
SELECT count(*) FROM iocs WHERE value ~ E'[\\n\\r]';                       -- 16 on 2026-11-16
SELECT type, count(*) FILTER (WHERE enrichment IS NULL OR enrichment = '{}'::jsonb) pending
FROM iocs WHERE type IN ('domain','url','md5','sha1','sha256') GROUP BY 1 ORDER BY 1;
```

### After deploy

1. No more `InvalidURL` tracebacks from `ioc.enrich_pending` after the next quarter-hour run:
   `docker compose -p niskala-intelligence logs worker --since 30m | grep -c "ioc.enrich_pending.*raised"` returns 0.
2. The newline IOCs carry a skipped card:
   `SELECT id, enrichment->'providers'->0->'raw' FROM iocs WHERE value ~ E'[\\n\\r]' LIMIT 5;`
   shows `{"skipped": "malformed value (contains whitespace)"}`.
3. Within a day the `pending` counts from "Before deploy" fall (each provider still runs within its own rate budget).

### One-off commands

None required. The 16 malformed IOCs stay in `iocs` (now harmless for enrichment). Deleting them is optional, a WRITE,
and needs the user's approval; it is not part of this release.

### Rollback

`make deploy` restores the `:prev` images on a failed health check. Rolling back to 0.8.19 or older brings the crash back.

### Known risks

- The extractor now misses an IOC whose defanged form is genuinely split over two lines (rare in article text). Single-line
  forms, including `1 . 2 . 3 . 4` with spaces, still match.
