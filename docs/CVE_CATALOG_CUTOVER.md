# Cutover runbook: tech catalog + CVE mirror (ROADMAP #19, slice 7)

Moves the filling of `cve_tracker` from the `new_cve` scraper (NVD/Tenable keyword search) to the
mirror pipeline: `cve.mirror_sync` -> catalog -> promotion (`docs/CVE_CATALOG_DESIGN.md`). **There is no
staging**: dev first, then prod with the same steps. Every step has a way back; none of them downgrades
the DB schema.

All new features are **off by default** (`CVE_MIRROR__ENABLED=false`, `CVE_MIRROR__PROMOTE=off`).
Deploying the code does NOT change any behaviour.

## State map (one switch: env, then restart)

| `ENABLED` | `PROMOTE` | Mirror filled | Shadow | Tracker filled by | `new_cve` |
|---|---|---|---|---|---|
| false | (any) | no | no | `new_cve` | runs |
| true | off | yes | no | `new_cve` | runs |
| true | shadow | yes | yes (`cve_promotion_shadow`) | `new_cve` | runs |
| true | **live** | yes | no | **mirror** + Telegram summary | **suspended** |
| true | live + `KEEP_LEGACY_NEW_CVE=true` | yes | no | mirror **and** `new_cve` | runs (overlapping) |

Env is read once per process: after changing it, restart `worker`, `beat`, and `api`.
A suspended `new_cve`: beat does not schedule it, `Runner` refuses it (status `disabled`), health
counts it as `disabled` (it does not show up as `stale`/`dead` in the digest), and it shows as inactive on the scrapers page.

## Prerequisites (once, per environment)

1. **Env**: `TELEGRAM__THREAD_IDS` contains `"cve_new": <thread id>` (`0` = main chat). Without it ingest
   still runs, only the new-CVE summary is not sent. The `CVE_MIRROR__*` keys are optional (default off).
2. **Deploy the code** (CD runs the migrations first): revisions `b7e3d9a1c5f2` (catalog/mirror/targets,
   `techstack_entries.active`), `d4a9c7e1b3f6` (`cvss_vector` becomes TEXT: **fixes `new_cve` failing
   on CVSS vectors > 100 characters**), `e5b2d8f4a7c1` (shadow table). All are safe for existing data.
3. **Fill the mirror + catalog** from a clone of CVE List V5 (`git clone` / `git pull` on a machine that can reach
   github.com), ~10 minutes for 114 thousand files:
   `make backfill-cve-mirror SOURCE=cvelistV5/` (report) then `ARGS=--apply`. Safe to repeat.
4. **Turn on ingest**: `CVE_MIRROR__ENABLED=true`, `CVE_MIRROR__PROMOTE=off`, restart `worker`. Wait
   up to 5 minutes (the `cve.mirror_sync` schedule), then watch its log (command below, nothing extra):

   ```bash
   docker compose logs worker | grep cve_mirror_synced | tail -n 3
   ```

   Expected on every line: `status` is `ok` or `noop`, `failed` is `0`, and
   `gap_unrecoverable` is `False`. Re-run the backfill if the clone is older than the moment ingest
   was turned on (it closes the gap in between).

## Stage 1: mapping the 34 entries (human, on dev)

1. UI: CVE Tracker -> **Monitored Tech** -> each "Unmapped" entry -> **Map to catalog**. Draft proposal:
   `docs/CVE_CATALOG_DESIGN.md` 8.3 (e.g. `fortigate` = the FortiOS product, `junos` = three Juniper products).
   Labels often differ from the CNA name (fortigate != FortiOS): the dialog gives hints. Candidate helper:
   `make catalog-mapping CMD=suggest`.
2. The decision per entry: vendor-level (every product of the vendor; a wide net that can pull in
   products that are not used) or product (precise). Entries deliberately left "Unmapped" are still
   matched by text, as before.
3. Export: `make catalog-mapping CMD=export ARGS='--out /work/mapping.json'`.

## Stage 2: shadow mode on dev (a few days)

1. `CVE_MIRROR__PROMOTE=shadow`, restart `worker`.
2. Fill the shadow history: `make promote-cve-mirror MODE=shadow` (report) then `ARGS=--apply`.
3. Compare: `make compare-promotion-shadow SINCE=<date new_cve started running>`.
4. **Go criteria** (all of them). The report labels are quoted as printed by the tool:
   - the shadow has been filled for >= 7 days and the mirror is not stale (no "mirror basi?" (stale mirror?) reason under
     "hanya tracker" (tracker only));
   - every "hanya tracker" row is explained: the reason "entri bertarget tidak cocok CVE" (targeted entry does not match
     the CVE) means a wrong/missing target (fix it in the UI), "gate teks" (text gate) means the text entry's name does not
     appear in the CNA vendor/product;
   - "hanya bayangan" (shadow only) has been reviewed (correct = CVEs that keyword search used to miss; wrong = target
     too wide or text gate too loose, e.g. a third-party plugin that mentions the product name);
   - "tech beda" (different tech) is understood (the shadow picks the most specific entry, `new_cve` picks alphabetically);
   - every entry in use is mapped, or deliberately left as text.

## Stage 3: `live` cutover (dev first, then prod)

1. Prod: import the mapping: `make catalog-mapping CMD=import ARGS='--file /work/mapping.json'` (report; check
   "masalah" (problems) = catalog keys that are not yet in the prod mirror), then `--apply`.
2. Prod: do a short Stage 2 (shadow + compare) if it has never been done on prod.
   **Only for a mirror filled before 0.4.1**: first clean up `affected_lines` text that starts with a doubled `<=`, because promotion
   copies it as-is into the tracker (idempotent; one transaction with a safeguard; a mirror backfilled with code 0.4.1
   or later is already clean):
   `docker compose --env-file docker/stack.env --profile app exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -q' < tools/ops/fix_affected_double_operator.sql`.
3. **Switch**: `CVE_MIRROR__PROMOTE=live`, restart `worker`, `beat`, `api`. `new_cve` stops being scheduled;
   `cve.mirror_sync` starts writing `cve_tracker` and sending a Telegram summary for new CVEs <= 3 days old.
4. Fill the history WITHOUT flooding: `make promote-cve-mirror MODE=live ARGS='--since <shadow start date>'`
   (report first, then `--apply`). **`--since` is mandatory**: newly found old history enters the tracker with
   `detected_on` = now, which ruins the dashboard MTTD. (Entries Monitored through the UI fill their own history
   from the whole mirror, per the "history is filled immediately" decision; their `detected_on` is also = that moment.)
5. Verify (first day): `cve_mirror_synced` log (`promoted_new`), the Telegram summary on the `cve_new` topic
   arrives, the CVEs tab is filled, the dashboard looks sane, the Scrapers page shows `new_cve` as inactive, the health
   digest does not report `new_cve`.

## Rollback (any time, no migration)

- **Back to `new_cve`**: `CVE_MIRROR__PROMOTE=off` (or `shadow`), restart `worker`, `beat`, `api`.
  `new_cve` is scheduled again. Tracker rows already created by the mirror stay (tickets/ACKs are safe); the next
  `new_cve` run upserts the same rows.
- **Overlap / fallback**: `CVE_MIRROR__KEEP_LEGACY_NEW_CVE=true` runs both; only
  `tech` can flip back and forth (the mirror picks the most specific, `new_cve` picks alphabetically), no data is lost.
- **Turn everything off**: `CVE_MIRROR__ENABLED=false`. The mirror and catalog stay in the DB (nothing reads them).

## Operational notes

- **Retention**: `cve.mirror_purge` (03:30 UTC) drops mirror records published before 1 January of the previous year; from
  2027-01-01 CVEs published in 2025 disappear from the mirror. `cve_tracker`, tickets, and the catalog (statistics) are not
  touched.
- **Inactive entries** (Pause) = hidden, not deleted; reactivating one fills its history.
- **Stale mirror**: if `cve_mirror_synced` stops or `gap_unrecoverable=True` (the worker was down longer than
  the 30 days of delta log), run `make backfill-cve-mirror` with a fresh clone.
- **Notifications** only for new CVEs <= 3 days old, per client, one message per ingest cycle.
