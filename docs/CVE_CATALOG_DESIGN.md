# Design: CVE mirror, tech catalog, and Monitor (ROADMAP #19)

Status: **slices 1 (resolver), 2 (schema, models, repositories), 3 (ingest), 4 (promotion + shadow
mode), 5 (API), 6 (UI), and 7 (cutover switch + mapping tools + runbook) are DONE on the branch; what remains
is operational (manual mapping of the 34 entries, shadow mode, cutover) and follows `docs/CVE_CATALOG_CUTOVER.md`** (2026-10-07). Derived from the user's decisions, the spike results on the full
data (`docs/spikes/2026-10-07_cve_catalog_report_v2.md`, interpreted in `docs/CVE_TECH_MATCHING.md` 7.1.3), and
the current CVE Tracker flow (`docs/CVE_TRACKER_FLOW.md`; **read its section 10**, those are the invariants that
must be preserved). Unverified items are marked **[assumption]**; verified ones are marked **[checked]**.

## 1. Decisions already made (user, 2026-10-07)

1. Every CVE published >= 2025 is stored in our own DB (the **mirror**). **Calendar-year retention**: keep the current year
   and the previous one; on 1 January 2027 CVEs published in 2025 are dropped.
2. The tech catalog (vendor, product) is derived from the CVE data. Products that do not exist yet may be added as
   **custom** (flagged as unverified).
3. The techstack menu has an **All Tech** tab (the catalog) and a **Monitored Tech** tab (per client). The **CVEs** tab only
   shows CVEs for monitored techs. A new **CVE DB** tab (read-only) browses the whole mirror.
4. **The Monitor unit has two levels: vendor and product family.**
5. Techs that are not monitored are **hidden** (an active flag), not deleted; tickets are never lost.
6. Enrichment for monitored techs = what already exists today (score/risk, KEV, EPSS, ticket).
7. Affected versions: follow what exists (text in Affected + ticket fields). No structured ranges.
8. New-CVE notifications: **already built** (`cti_scraper.cve_alert`), using the "a new tracker row was
   created" marker; this design must keep calling the same point.
9. Automatic normalisation first; product merging by admins later. Tested on the **dev server** first, **shadow
   mode** before replacing `new_cve`.

## 2. Facts from the data that shape the design

| Fact (117,220 CVEs, 2025-01-01 to 2026-10-07) | Consequence for the design |
|---|---|
| Volume: 2025 ~43.8 thousand; Sep 2026 14.9 thousand (3.9x Sep 2025); yesterday 1,010 new + 929 updated | Ingest must handle hundreds to thousands of changes/day; filter per run, not per candidate |
| 93.8% of CVEs have an identity; ADP rescues 42; CPE only 7.5% | Identity from CNA input; **ignore ADP**; do not depend on CPE/NVD |
| 15,290 vendors, **79% with a single product**; 41,507 identities; **62.9% with only 1 CVE**; 5,546 (13.4%) >= 5 CVEs | Search-first picker; initial view >= 5 CVEs; the catalog is mostly tail |
| Automatically merged spellings only 242 (0.6%) | Automatic normalisation is enough for v1; admin merging can come later |
| **Only 562 families with > 1 variant** (1,915 identities, 4.6%): automatic version folding changes almost nothing outside Windows/devices | "Family" is practically = product, with version folding for Windows/Dell/D-Link/Siemens; **vendor level is the safety net** when family folding is wrong |
| Vendors without a usable name: `unknown` 1,236, `n/a` 520, empty 211 identities (4.7%) | Placeholder vendors are collapsed into "(tanpa vendor)" (no vendor), which cannot be monitored at vendor level |
| The same vendor spelled differently: `Palo Alto Networks`/`paloaltonetworks`, `n8n io`/`n8n`, `graylog2`/`graylog`, `nagios`/`nagios enterprises llc` | Vendor key = the compact form; the rest needs manual aliases/merges |
| Old tech labels often cover **several** families (`junos` = junos os + evolved + space; `jira`; `nginx` = open source + plus) or several vendors (`graylog`, `nagios`) | **One Monitor entry must be able to have many targets** (see 3.4) |
| **CVE List V5 delta feed [checked]**: `cves/delta.json` (4 KB) only holds the last fetch window; median fetch interval 18 minutes, max 62; `deltaLog.json` 24 MB keeps 30 days | Hourly polling loses data; see 5 |

## 3. Data model

Different lifetimes, do not conflate them:

| Layer | Tables | Life cycle |
|---|---|---|
| Mirror | `cve_records`, `cve_record_products` | dropped by retention |
| Catalog | `catalog_vendors`, `catalog_families`, `catalog_family_aliases` | **permanent**; rows referenced by Monitor are never deleted |
| Monitor | `techstack_entries` (+columns), `techstack_targets` | permanent, per client |
| Results | `cve_tracker` etc. (already exist) | permanent, no FK to the mirror |

### 3.1 Mirror

`cve_records`: `cve_id` PK; `published_date` (indexed; the retention basis), `published_at`, `modified_at`;
`summary`, `cvss_score`, `cvss_severity`, `cvss_vector`, `link`, `solutions`; `references` JSONB (a list of URLs);
`affected_lines` JSONB (a list of strings in **exactly the format `new_cve` writes today**, e.g. `Zabbix: < 7.0`);
`ingested_at`, `source_updated_at`. That is everything needed to copy into `cve_tracker` (the equivalent of
`CveItem`), so **no raw JSON is stored**.

`cve_record_products`: `cve_id` FK (`ON DELETE CASCADE`), `family_id` FK (nullable when unidentified),
`vendor_id` FK, `vendor_raw`, `product_raw`, `has_cpe`. Indexes `(family_id, cve_id)` and `(vendor_id, cve_id)`.
The raw strings are stored so that re-mapping (when family rules are fixed) can be recomputed for data
still within retention.

### 3.2 Catalog

- `catalog_vendors`: `id`, unique `key` (**compact form**: `palo alto networks` = `paloaltonetworks`),
  `display_name` (the most frequent raw spelling), `monitorable` (false for "(tanpa vendor)"), `first_seen`,
  `last_cve_at`, `cve_seen_total` (incremented on every ingest; **does not drop on retention**, so the popularity
  order stays stable).
- `catalog_families`: `id`, `vendor_id` FK, `key` (unique together with `vendor_id`), `display_name`, `source`
  (`auto` | `manual` | `custom`), the same statistics. `custom` = added by a user, not yet verified.
- `catalog_family_aliases`: unique `alias_key` -> `family_id`. Filled automatically for every folded variant
  (`windows 10 version 1507` -> family `windows`) and, later, by admin merges. The resolver looks here
  first, so manual corrections are not lost on the next ingest.

There is no separate products table: variants are folded into families at resolution time; the raw names live in
`cve_record_products` (while in retention).

### 3.3 Identity resolver (`cti_core.catalog_resolve`, **already exists**, 58 tests)

`resolve(vendor_raw, product_raw, cpes) -> (vendor_key, vendor_display, family_key, family_display) | None`.
Rules = the spike's results, rewritten as a module with tests (the spike stays a local copy without dependencies):
1. Use CPE when present and not a wildcard; otherwise the CNA input (`product`, then `packageName`).
2. Unicode-aware normalisation (lower case, punctuation to spaces, CJK names kept whole).
3. **Junk** products -> `None`: placeholders (`n/a`, `unknown`, ...), generic (`software`, `firmware`, ...),
   version-like, digits-only, URLs. **Not junk** (still an identity): `owner/repo`, long titles, names containing
   `and`/`&`.
4. A placeholder/empty vendor -> the vendor "(tanpa vendor)" (`monitorable=false`).
5. Family = the product with trailing version tokens dropped (`version`, `22h2`, digits, `edition`, `x64`, ...),
   checked against `catalog_family_aliases` first. The noise suffix `server core installation` is dropped too
   (a slice 1 decision; without it every Windows Server version becomes two families). Safeguard: a folded
   family equal to its vendor is not used (`Microsoft 365` must not become `microsoft`).
6. Vendor key = the compact form **without legal suffixes** (`inc`, `corporation`, `ltd`, `llc`, `gmbh`, ...):
   on the real catalog this merges 127 additional vendor groups, all correctly (Microsoft/Microsoft Inc,
   Oracle/Oracle Corporation, D-Link/D-Link Corporation). Single-letter suffixes are deliberately not used (they would merge
   `n` with `n a`).

**Resolver results on the whole spike catalog (41,507 identities, 0.5 seconds)**: **39,896** (vendor,
family) pairs and **14,911** vendors (out of 15,290); 810 families fold > 1 identity (2,421 identities); 1,971
identities without a vendor (4.7%). Every mapping target in the table in 8 exists: `fortinet/fortios`, `junos os`/`junos os
evolved`/`junos space`, `f5/nginx open source` + `nginx plus`, `mikrotik/routeros`, the Fortinet vendor (51
families), Palo Alto Networks (32, both vendor spellings unified), Splunk (31). **Still separate, needing a manual
alias**: `n8nio` vs `n8n` (175 vs 22), `graylog2` vs `graylog`, `nagios` vs `nagios enterprises llc`.

### 3.4 Monitor: one entry, many targets

`techstack_entries` stays: `name` (the label **and the join key** to `cve_tracker.tech`, unchanged),
`exposure`, `hosting_type`, `source`, `added_date`; **add** `active` (default true).

`techstack_targets` (new): `entry_id` FK (`ON DELETE CASCADE`), `vendor_id` FK **or** `family_id` FK
(`CHECK` exactly one is set). Examples: `junos` -> {family `junos os`, `junos os evolved`, `junos space`};
`fortinet` -> {vendor `fortinet`}; `nginx` -> {family `nginx open source`, `nginx plus`}.

An entry **without targets** = an old/custom entry, still matched by text as today (the `new_cve` gate),
so nothing stops working before it is mapped.

The **Monitor** button in All Tech creates an entry (label = the display name, `exposure`/`hosting` defaults
as today) with **one** target; adding a target to an existing entry is a separate step (simple UI
first).

## 4. Matching and promotion into `cve_tracker`

For each new/changed mirror record:
1. Resolve its products -> a set of `(vendor_id, family_id)`.
2. Active entries per client that have a matching target (a vendor target matches when `vendor_id` is in the set;
   a family target when `family_id` is) **OR** entries without targets that pass the old text gate
   (`relevant_techs` on the vendor/product strings, with the summary as a fallback).
3. One row per `(cve_id, client_id)` (invariant: one tech per row). When several entries match, pick
   **the most specific** (a matching family target > vendor only > text), then the alphabetically first
   (today's rule), so it is deterministic.
4. `CveTrackerRepo.upsert_with_status` with the fields copied from `cve_records`; **`detected_on` is set
   on INSERT** (the time the system found it, not the publish date; the MTTD basis) and **never overwritten**. Created rows
   are recorded in `Session.info["cve_new_rows"]` so the existing Telegram summary works unchanged.
5. False positives are not checked at ingest (same as today; they are hidden in queries).

Another trigger: an entry **newly Monitored** -> run once against the whole mirror (history is filled immediately;
the "Populate now" button #3 is not needed). The Telegram summary does not announce that history because of
the 3-day age limit in `cve_alert`.

## 5. Ingest from CVE List V5

**[checked]** `https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/delta.json` contains
`fetchTime`, `numberOfChanges`, `new[]`, `updated[]`, `error[]`; each element has `cveId`, `githubLink`
(the raw file URL), `dateUpdated`. Only the last fetch window; `deltaLog.json` (24 MB, 30 days) keeps the
history.

- Task `cve.mirror_sync` (queue `maintenance`) **every 5 minutes**: fetch `delta.json`, compare
  `fetchTime` with the cursor (stored in the DB), process only what is new, download each `githubLink` file, parse
  it with the existing MITRE parser logic, store it in the mirror, resolve, promote. **[checked on 2 real
  records]** CVE List V5 records have everything the parser reads (`metrics` with `cvssV3_1`/`format`/`scenarios`,
  `affected[].versions` with `lessThan`/`lessThanOrEqual`/`status`, `references`, `solutions`, dates)
  as well as `descriptions[lang=en]`. **But that parser could not be reused yet**: it was fused into
  `NewCve._mitre_detail` (not a pure function), and `summary` and `link` came from the NVD/Tenable candidate,
  not from the MITRE record. It needed a **refactor**: extract a pure `parse_cve_record(data, *, link, summary)`,
  used by `new_cve` (behaviour unchanged, the existing tests as a safety net) and by mirror ingest
  (`summary` = `descriptions[en]`, `link` = `https://nvd.nist.gov/vuln/detail/<id>`; NVD and CNA text are
  usually the same, but the difference needs measuring in shadow mode).
- **Gap**: if the worker is down longer than the fetch interval (max 62 minutes observed), `delta.json` has already overwritten
  the missed window. Detection: the new `fetchTime` is too far from the cursor -> **catch up through `deltaLog.json`**
  (24 MB, rare), or through a clone/git pull. Without this, data is lost silently.
- **Initial backfill**: a one-off ops script using the source iterator from `spike_cve_catalog.py` (clone or
  zip), with the same parser and resolver.
- Limits: `raw.githubusercontent.com` is reachable from this environment **[checked]**; hundreds to ~2,000
  files per day. Respect `User-Agent`/pauses; one file failing does not stop the batch (it is logged and
  retried in the next cycle).

## 6. Retention

A daily task (queue `maintenance`): `DELETE FROM cve_records WHERE published_date < make_date(
extract(year FROM now())::int - 1, 1, 1)` (cascading to `cve_record_products`). Log the count; **does not
touch** `cve_tracker`, tickets, or the catalog. Test: after retention, tracker rows that came from dropped CVEs
stay intact. Catalog statistics do not drop (the `*_seen_total` columns).

## 7. API and UI

- Catalog: `GET /api/catalog/vendors?q=&show_all=` , `GET /api/catalog/vendors/{id}/families?show_all=`,
  `GET /api/catalog/families?q=` (search across families, results include the vendor). **User decision
  2026-10-07: the browse view hides families that have only 1 CVE** (`show_all=true` to
  show everything). Exceptions: **search (`q`) hides nothing** (a new product
  with its first CVE must still be findable and monitorable), and families/vendors already referenced by
  Monitor are always shown. On the real data this hides 24,562 of the 39,896 families (61.6%): 15,334
  families across 5,815 vendors are shown. The "CVEs per family" count is **unique CVEs per family** (one CVE that
  lists three Windows variants is counted once; the entry counts in the spike CSV double-count). Pagination
  is mandatory.
- Monitor: `POST /api/techstack` accepts `{vendor_id | family_id | custom_name}`; `POST/DELETE
  /api/techstack/{id}/targets`; `PATCH /api/techstack/{id}` for `active`. Contract changes ->
  regenerate `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts` (CI checks for drift).
- CVE DB: `GET /api/cve-db?q=&vendor=&family=&severity=&date_start=`, read-only over the mirror; from a CVE,
  every affected product has a Monitor action.
- UI: the Tech Stack sub-view is split into **All Tech** (a vendor -> family tree, search-first) and **Monitored
  Tech** (today's list + targets + an active toggle). Follows `apps/web/CLAUDE.md` (Base UI, not Radix).
- Scope of the CVEs tab/stats/dashboard/export: add an `active` filter on the techstack. **Decide the behaviour of an
  empty techstack** (today = no tech filter; see `docs/CVE_TRACKER_FLOW.md` 10.4).

## 8. Migration and cutover

1. The new schema is added **without changing behaviour**: old entries without targets, `new_cve` keeps running.
2. Backfill the mirror + catalog from a clone (ops script) on dev; verify the counts against the spike numbers.
3. **Mapping the 34 old entries to targets is reviewed by a human** (proposal table below), based on the spike results:

   | Old label | Proposed target | Note from the spike |
   |---|---|---|
   | fortinet | vendor Fortinet | 51 families, 311 CVEs |
   | fortigate | family fortinet/fortios | the CNA writes `FortiOS`, the label differs from the product |
   | juniper | vendor Juniper Networks | 168 CVEs |
   | junos | families junos os, junos os evolved, junos space | needs several targets |
   | palo alto | vendor Palo Alto Networks | the vendor is spelled two ways (the compact form unifies them) |
   | splunk, okta, proofpoint, crowdstrike | their respective vendors | one vendor, many products |
   | nginx | families f5/nginx open source + nginx plus | NOT the vendor/free name: `nginx ui`, `ingress-nginx` would come along |
   | jira | families atlassian/jira software/service management (+align?) | a human decision |
   | graylog, nagios | two vendors spelled differently | needs a vendor alias |
   | microsoft 365, outlook | families Microsoft 365 Apps / Outlook | the Office hierarchy |
   | harmony sase + perimeter81 | one product (Check Point) | two entries point to the same product |
   | gitlab, n8n, wazuh, suricata, mikrotik, anydesk, ejbca, burp suite | clean families | n8n: vendors `n8n io` and `n8n` |
   | grafana | **vendor Grafana (vendor level; DECIDED by the user 2026-10-08)** | catches Grafana OSS/Enterprise, `mcp-k6`, k6, etc.; risk: unused Grafana products come along |
   | new relic, maxscale, extrahop, thales, esxi, mariadb, proxmox | **reviewed one by one** | no CVEs in the window, or ambiguous |

4. **Shadow mode** on dev for a few days: the new pipeline writes to `cve_tracker` only when the flag is on;
   before that it writes to a comparison table. Result: the CVEs found by only one side, with an explanation.
5. Switch over; the old `new_cve` stays available as a fallback (flag) for a few releases.
6. **Rollback**: turn the flag off -> the old `new_cve` comes back; the new schema does not need to be downgraded.

## 9. Breakdown of the work (one PR per slice, each slice mergeable on its own)

1. **Pure resolver + tests** from the spike data (real fixtures), no DB. Includes the decision on the `server core
   installation` suffix.
2. **Migration + models** for mirror/catalog/targets + repositories. Migration test (`test_migrations_match_models`).
   **DONE**: revision `b7e3d9a1c5f2`; `cti_core.db.repositories.catalog` (`CatalogRepo`, `CveMirrorRepo`,
   `retention_cutoff`); `tests/integration/test_catalog_mirror.py` (21 tests). The `cve_seen_total` statistic
   increments once per CVE per family/vendor (idempotent, order-independent, does not drop on retention); records
   with an older `modified_at` are rejected; old techstack entries stay `active` without targets and are still
   matched by text. No code USES these tables yet (no behaviour change).
3. **Ingest**: refactor `_mitre_detail` into a pure function (without changing `new_cve`'s behaviour), the
   `cve.mirror_sync` task, the cursor, catch-up, retention. Tests with a fake delta + real fixtures.
   **DONE** (behind the `CVE_MIRROR__ENABLED` flag, OFF by default):
   - `cti_core.cve_record.parse_cve_record` (the pure parser; `new_cve` uses it, 71 existing tests as the
     safety net), `cti_core.cve_mirror_sync` (`sync_once`, `purge_expired`), the tasks `cve.mirror_sync`
     (every 5 minutes) and `cve.mirror_purge` (03:30 UTC) on the `maintenance` queue, the script
     `tools/ops/backfill_cve_mirror.py` (`make backfill-cve-mirror`).
   - Decisions beyond the original design: cursor + retry queue in `job_state`
     (`cve_mirror.state`, no migration); **catch-up is triggered by two things**: the last successful poll > 12 minutes ago
     (we ourselves are late) or `fetchTime` jumping > 90 minutes (the observed fetch interval is at most 62
     minutes, so a lost window would go undetected by looking at `fetchTime` alone); a Postgres advisory
     lock (one cycle at a time, also used by the backfill); only links under
     `raw.githubusercontent.com/CVEProject/cvelistV5/` are downloaded; REJECTED records are dropped from the
     mirror; records without a date or outside retention are not stored; overflow above
     `max_files_per_run` is carried to the next cycle (the cursor still advances).
   - Tests: `tests/unit/test_cve_mirror_sync.py`, `test_cve_mirror_task.py`,
     `tests/integration/test_cve_mirror_sync.py`, `test_backfill_cve_mirror.py`.
   - **Not yet**: promotion into `cve_tracker` (slice 4), so the mirror fills up but changes nothing the
     user sees. Table size and retention/backfill time have not been measured on the full data (do it on dev
     before turning the flag on in prod).
4. **Promotion + matching** into `cve_tracker` (flag, shadow mode), using `upsert_with_status`.
   **DONE** (flag `CVE_MIRROR__PROMOTE=off|shadow|live`, default `off`, only effective when
   `CVE_MIRROR__ENABLED`):
   - `cti_core.cve_promotion`: `choose` (pure: family target > vendor target > text, then alphabetical
     name, then `entry_id`; entries with targets are NOT matched by text; entries without targets use the old text
     gate `tech_match.relevant_techs`, now moved to `cti_core.tech_match`), `promote_record`,
     `promote_all`. `live` writes `cve_tracker` through `upsert_with_status` (the same row shape as
     `_cve_sink`: score 0.0 and vector "" when there are no metrics; `detected_on` set by the server on INSERT; enrichment,
     tickets, FPs are not touched; tracker rows are never deleted) and fills
     `Session.info["cve_new_rows"]`, so the existing Telegram summary works through `finish_run` (called by the
     `cve.mirror_sync` task after commit). `shadow` writes a new table `cve_promotion_shadow`
     (revision `e5b2d8f4a7c1`) and does not touch the tracker; the shadow is dropped by retention too.
   - Promoting one record runs in the same savepoint as the mirror upsert (failure = the record is retried).
   - `reference_data` (`techstack`, `techstack_by_client`) now only contains `active` entries.
   - Tools: `tools/ops/promote_cve_mirror.py` (`make promote-cve-mirror`; the whole mirror; report =
     rollback; the "newly Monitored entry" path via `--entry`) and `tools/ops/compare_promotion_shadow.py`
     (`make compare-promotion-shadow`; categories same / different tech / shadow only / tracker only +
     reason).
   - **Not yet / deliberately deferred**: switching off `new_cve` (slice 7; while `live` and `new_cve` run
     together, both upsert the same rows and `tech` can flip back and forth, no data is lost);
     a CVEs tab/dashboard that hides inactive entries (slice 5, an API change); the automatic
     "newly Monitored entry" trigger from the UI (slice 5, currently through the tool). The text gate uses the
     resolver's vendor/product (`vendor_raw`/`product_raw`/`product_norm`), not the raw `packageName`/CPE as
     `new_cve` does: the difference will show up in the shadow comparison.
5. **Catalog/CVE DB/Monitor API** + contract.
   **DONE** (`docs/openapi.json` and `schema.d.ts` regenerated, additions only; 8 new operations, 2 schemas
   added/changed):
   - Catalog (read-only, global, Monitor status per client): `GET /api/catalog/vendors`,
     `GET /api/catalog/vendors/{id}/families`, `GET /api/catalog/families?q=` (min 2 letters). Browsing
     hides families with `cve_seen_total < 2` and vendors whose families are all like that (`hidden` in the response
     = how many); `q` and `show_all=true` hide nothing; anything already referenced by Monitor is always shown. The
     `q` input is treated literally (not as a LIKE pattern). `page_size` max 100. The "(tanpa vendor)" vendor appears with
     `monitorable=false`.
   - CVE DB: `GET /api/cve-db?q=&vendor=&family=&severity=&date_start=&date_end=` and `GET /api/cve-db/{cve_id}`;
     each product carries `monitored`/`monitor_entry_id` (directly or through a vendor target). The summary in the list
     is cut at 400 characters, the detail is complete.
   - Monitor: `POST /api/techstack` now accepts just `name` (a **custom** entry, the old contract), or
     `vendor_id` / `family_id` (a **catalog** entry, `name` optionally overrides the default label; the label must be unique per
     client, `duplicate` on a clash). `POST /{id}/targets`, `DELETE /{id}/targets/{target_id}` (404/409/422
     via the HTTP status; **the last target cannot be removed**, because an entry without targets goes back to being matched
     by text), `PATCH /{id}` `{active}`, and `GET /api/techstack?active=`. `TechStackOut` gains
     `active`, `kind` (`catalog`/`custom`), `targets`.
   - Promotion trigger: add/activate/new target -> the API sends a `cve.promote_entry` task (after commit,
     best effort, only when `CVE_MIRROR__ENABLED` and `CVE_MIRROR__PROMOTE` != off) that fills that entry's
     history from the mirror (candidates = records whose products match a target; custom entries scan the whole mirror).
   - Scope of the CVEs tab/stats/dashboard/export/`tech-list`/`purge-orphaned`: see 9.5.
   - Tests: `tests/integration/test_catalog_api.py` (23), `test_cve_promotion.py` (+5 `promote_entry`),
     `tests/unit/test_monitor_trigger.py`.
6. **UI** All Tech / Monitored Tech / CVE DB.
   **DONE** (`apps/web`, the CVE Tracker page; the old "Tech Stack" sub-view replaced by three sub-views):
   - **Monitored Tech** (`monitored-tech-panel.tsx`, replacing `techstack-panel.tsx`): a list of entries with
     targets, Active/Paused status, exposure/hosting, a status filter. Old entries are marked **"Unmapped · name text"**
     with a **"Map to catalog"** button; catalog entries have **"Targets"**. "Pause"/"Resume" = inactive/active.
     "Remove" explains that its CVEs become orphans and offers Pause. "Add custom (unmapped)" remains.
   - **Map to catalog / Targets** (`map-tech-dialog.tsx`): a target editor for one entry. The catalog search is prefilled with the
     entry's name; results are split into **Products** (most precise) and **Vendors** (every product of the vendor); the dialog stays
     open so several targets can be added in a row (e.g. `junos` -> three products); the last target cannot
     be removed (the button is disabled, and the backend refuses too). An empty result shows a hint that the catalog uses
     the names CNAs publish (FortiGate = FortiOS), because entry labels often differ from product names.
   - **All Tech** (`all-tech-view.tsx`): a vendor -> product tree, search-first. Browsing hides products
     with 1 CVE (showing an "N hidden" note; a "Show all" checkbox); search shows everything, split into
     Vendors and Products. Monitor vendor / Monitor product buttons.
   - **CVE DB** (`cve-db-view.tsx`): a list of mirror CVEs (search, severity, date, product filter) and a detail dialog
     with Monitor actions per product/vendor and "Filter DB".
   - Shared: `src/lib/cve/catalog.ts` (`useMonitorActions`, `useDebounced`, types).
   - Verification: `eslint`, `tsc`, `next build` clean, AND run as a real E2E (real API + Postgres + Chromium):
     login, map `fortigate`, three targets for `junos`, the last target cannot be removed, Pause/Resume, All
     Tech (browse, open a vendor, search for a 1-CVE product, Monitor), CVE DB (list, detail, Monitor a product),
     the new entry appears in Monitored Tech; zero 4xx/5xx responses from the new tabs. The E2E script is not committed (the repo has
     no web test runner).
7. Mapping the 34 entries + cutover.
   **DONE on the code side** (the human steps are in `docs/CVE_CATALOG_CUTOVER.md`):
   - **Switch**: `CVE_MIRROR__PROMOTE=live` suspends `new_cve` (`cti_scraper.supersede`): beat does not schedule it,
     `Runner` refuses it (status `disabled`), health = `disabled` (does not pollute the digest), the scraper list shows it
     inactive. `CVE_MIRROR__KEEP_LEGACY_NEW_CVE=true` lets it run side by side (overlap /
     fallback). **Rollback = change the flag + restart, no migration**; the control plane still wins.
   - **Mapping across environments** (`tools/ops/catalog_mapping.py`, `make catalog-mapping`): `export` from dev
     to JSON with stable catalog keys (not IDs), `import` into prod (report first; idempotent; keys that do not yet
     exist in the catalog are reported, not created; the active status is not copied unless `--with-active`), `suggest`
     (catalog candidates for unmapped entries).
   - **`--since`** on `promote_cve_mirror` / `promote_all` / `promote_entry`: limits the history that goes live
     to CVEs published since that date. Without it, old history enters the tracker with `detected_on` = now and
     ruins the dashboard MTTD.
   - Tests: `tests/unit/test_supersede.py`, `tests/integration/test_supersede_runner.py`,
     `test_catalog_mapping.py`, and the `--since` additions in `test_promotion_tools.py`.

### 9.5 Slice 5 decisions (CONFIRMED by the user 2026-10-08)

- **Inactive** (`active=false`) = stops being monitored and is hidden, NOT deleted: tracker rows, tickets,
  ACKs, and false positives stay; reactivating brings them back (and fills its history from the mirror).
  Different from deleting an entry, which orphans its rows so `purge-orphaned` can drop them.
- **Empty techstack**: a client with no entries at all = the CVEs tab without a tech filter (unchanged); a client
  that has entries but all inactive = an empty tab. Alternative: always empty when there are no active entries.
- **Excel export** only the monitored CVEs, same as the tab (user decision: "export hanya cve yang
  termonitor", i.e. export only monitored CVEs). Before, it did not filter by techstack at all;
  orphan rows (tech already deleted) are no longer exported.
- **`score.py`/`reference_data`** only use active entries (articles and scrapers no longer search/match
  deactivated techs).
- **Catalog entry label** = the catalog display name (e.g. "FortiOS"), must be unique per client; on a clash -> give it
  another `name`. The label stays the join key to `cve_tracker.tech`.

## 10. Risks and open items

- **Quality of automatic families**: version folding is only effective in 810 families; elsewhere identity = product. Safe
  because vendor-level Monitor exists. Long pickers (Microsoft 425 families, Siemens 1,053) are **decided**:
  1-CVE families are hidden in the browse view (section 7), search still shows everything.
- **Volume** keeps rising (Sep 2026 14.9 thousand/month). The mirror at the end of 2026 > 130 thousand CVEs; 2027 roughly projected
  bigger. Measure table size and retention time on dev before prod.
- **The delta feed** is not an official stable contract **[assumption]**; keep a fallback (clone/`git pull`) and an alarm when
  `fetchTime` stops advancing.
- **Pipeline recall vs history not yet separated**: the spike was run with `--since 2025-01-01`. Re-run it
  with `--since` = the date `new_cve` started running (and `tracker.csv` from the same DB) before making any
  claim about "missed by keyword search".
- **Identities without a vendor** (4.7%) and CVEs without a usable product (6.2%): only reachable through text;
  the old text path is kept for entries without targets, but CVEs without an identity cannot be matched to
  catalog targets at all.
- **The CVEs tab for an empty techstack** and **which year is kept when an old CVE changes** (KEV) are not yet
  decided (see `docs/ROADMAP.md` #19 "Open").
