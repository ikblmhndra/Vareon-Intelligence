# The current CVE Tracker flow (as-is)

A record of the CVE Tracker's **actual state** as of 2026-10-07, written before designing the tech catalog + CVE
mirror (`docs/ROADMAP.md` #19) so the new design does not break what already works. Everything here was
read from the code, not from memory; what **could not** be verified is in section 10. If the code
changes, update this file (not the other way round).

Related documents: `docs/CVE_TECH_MATCHING.md` (why the Tech column mismatched, the 0.2.1 fix),
`docs/ROADMAP.md` #13-#19, `docs/SCRAPER_MAINTENANCE.md` 4.G-4.H (ops tools).

## 1. One-page overview

```
beat (hourly)                                           analyst (UI /cve)
  └─ scrape.run new_cve  ──► NVD keywordSearch ┐          ├─ CVEs tab: filters, KEV/EPSS/Exploit-DB lookup, Excel export
       (queue scrape.api)    Tenable (XPath)   ├─ candidates ├─ detail modal: Ticket tab (acknowledge, fill in the ticket)
                             MITRE per candidate┘          ├─ Dashboard sub-view (MTTD/MTTA/MTTR), Ticketing
                                  │ relevance gate (tech name ~ CNA vendor/product)
                                  ▼                       └─ Tech Stack sub-view (add/remove/exposure/hosting)
                    CveItem(client_id, tech, ...) ──► sink ──► cve_tracker  (+ references, affected)
                                                                  ▲   ▲   ▲
   cve.enrichment_sweep (every 3 h, maintenance) ── KEV/EPSS/Exploit-DB ┘   │   │
   github_poc_monitor (scraper) ── CvePocItem ── cve_pocs + poc_available ───┘   │
   ticket/ack/false-positive (API) ── cve_tickets, cve_false_positives ──────────┘
```

The gist: **`techstack_entries` (per client) decides which CVEs enter `cve_tracker`**, through a single
scraper (`new_cve`). Everything else (enrichment, tickets, dashboard, export) works on top of the tracker rows.

## 2. Ingest: the `new_cve` scraper

`scrapers/src/cti_scrapers/feeds/new_cve.py`. `meta`: `id="new_cve"`, schedule `spread("0 * * * *")` (hourly,
minute shifted), `rate_limit="60/minute"`, `max_items=300`, `credential="nvd"` (so it goes to the `scrape.api` queue),
`reference_data=("techstack", "techstack_by_client")`, `dedup_key()` = `None`
(**always re-upserts**, because MITRE can update scores).

The steps of one run (`NewCve.fetch`):
1. Read `ctx.reference`: the list of tech names (distinct across clients) and `{client_id: [tech names]}`.
2. **Find candidates** per tech name: (a) NVD `keywordSearch=<name>` with `pubStartDate`..`pubEndDate` =
   **the last 8 days** (by publish date), (b) Tenable `cve/search` (hardcoded XPath, only the first 6
   rows; results are dropped if their summary does not mention the tech name). 2 requests per tech;
   34 techs = 68 requests/hour, paced by `get_waiting` (limit 60/minute).
3. **One CVE = one candidate** (grouped by `cve_id`, carrying every tech that surfaced it).
4. **Detail from MITRE** (`cveawg.mitre.org/api/cve/<id>`), one call per candidate: vendor, product,
   `affected` + version ranges (as text), references, solution, CVSS (from the CNA only), modification date.
5. **Relevance gate** (`relevant_techs`, 0.2.1): a candidate is used only if the tech name appears in the
   CNA's vendor/product/packageName/CPE; if the CNA did not fill in a product (or a placeholder `n/a`...)
   it falls back to the summary. Rejections are logged as `cve_candidate_tech_not_affected`.
6. **Projection to clients**: for each client that has one of the affected techs, one `CveItem`. If
   a client has several affected techs, the **alphabetically first** one is used. Stops at
   `max_items` (300).
7. `CveItem` (`cti_scraper/items.py`) → sink (`cti_scraper/sinks.py::_cve_sink`) → `CveTrackerRepo.upsert`.

Important `upsert` behaviour (`cti_core/db/repositories/cve.py`):
- Key `(cve_id, client_id)`. New row: `INSERT`. Existing row: **every field sent is overwritten** (including
  `tech`, `summary`, scores); `references` and `affected` are **replaced whole** (not merged).
- `detected_on` is set by `server_default now()` only on INSERT, so = when the scraper first found it
  (the basis of MTTD/MTTA/MTTR); updates do not change it.
- `published_at` (MITRE's publish time) is only included when MITRE provides it, so it does not overwrite a
  backfilled value with `NULL`.
- The scraper does **not** check false positives: rows marked FP are still upserted, only hidden
  in queries (section 5).
- Old rows that are later rejected by the gate are **never deleted** automatically (the scraper only upserts); manual
  cleaners: `tools/ops/reconcile_cve_tech.py` and `POST /api/cve/purge-orphaned` (**admin/superadmin only**,
  including the dry run; dry run by default). Neither **ever deletes rows that have a ticket/ACK**; in
  `purge-orphaned` those rows are reported in `protected`/`protected_cve_ids`.
- The initial data before cutover came from the Mongo dump via `tools/seed/fase10_cve_migrate.py` (one time).

## 3. Data model (`cti_core/db/models/cve.py`, `techstack.py`)

| Table | Key | Contents / writer |
|---|---|---|
| `techstack_entries` | `(name, client_id)` unique | `name` free text (**both the label and the join key**), `exposure` (`public`/`internal`/`both`), `hosting_type` (`on_prem`/`cloud`/`saas`), `source`, `added_date`. Written by the UI/API (`routers/techstack.py`). No active flag: present = monitored. |
| `cve_tracker` | `(cve_id, client_id)` unique | CVE metadata (written by `new_cve`), `tech` (a single text value), `cisa_kev`/`active_exploitation` (machine bools), `epss_*`, `cisa_kev_detail`/`exploit_db_hits` (JSONB), `poc_available`, `detected_on`, `registered_date`. |
| `cve_references`, `cve_affected` | `cve_tracker_id` | children, replaced whole on every upsert. `affected` = **one string per row** (e.g. `Zabbix: < 7.0`), not structured data. Its shape is `product: constraint`; constraint = `< X` (`lessThan`), `<= X` (`lessThanOrEqual` or a plain version), or the CNA's free text as-is (`>= 3.3.0, < 3.5.4`; it used to be prefixed with `<=` too, giving `<= >= 3.3.0, < 3.5.4`). |
| `cve_pocs` | `cve_tracker_id` | written by `github_poc_monitor` (and the exploit-db lookup). |
| `cve_threat_actors`, `cve_ttps`, `cve_newsletter_mentions` | `cve_tracker_id` | other children (actors/TTPs via cross-reference, mentions via the newsletter). |
| `cve_false_positives` | `(cve_id, client_id)` unique | marked by analysts. **Keyed by `cve_id`, not the tracker id.** |
| `cve_tickets` | `(cve_id, client_id)` unique | one ticket per (CVE, client), `ticket_id` globally unique (`CTI-2026-09-001`, sequential per **WIB** month, **across clients**; numbering is serialised by `pg_advisory_xact_lock` on the path that saves the ticket directly). Created on acknowledge or manual edit. Also **keyed by `cve_id`, not the tracker id**. |

`CveItem` stores affected versions only as text in `cve_affected.affected`; tickets have
analyst-filled `affected_version`/`fixed_version`. **There is no structured version-range storage**, and that is a
deliberate decision (user 2026-10-07: versions stay as they are).

Important relationships:
- `cve_tracker.tech` ↔ `techstack_entries.name` are **compared as lower-case text** (`get_risk_context`
  maps `name.lower()`), not a foreign key. Renaming an entry breaks the join.
- Deleting a `cve_tracker` row → its children go too (cascade). Tickets and FPs do **not** (they have no FK to the tracker):
  `purge_orphaned` deletes the FPs of the rows it drops, not their tickets, because rows with a ticket are
  never dropped (this path does not create orphan tickets).
- Deleting a techstack entry does **not** delete its CVEs (the router deliberately does not cascade); the tracker rows stay
  but are hidden from the CVEs tab until `purge-orphaned` is run (section 5).

## 4. Enrichment after ingest

**`cve.enrichment_sweep`** (`apps/worker/.../tasks/periodic.py`), beat every 3 hours, `maintenance` queue.
Three steps, each in its own try/except (one failing does not stop the others), using
the same functions as the manual buttons in the UI (`cti_api/services/cve_lookup.py`):
- **CISA KEV**: download the whole catalog, match it against all CVEs → `cisa_kev=True`,
  `active_exploitation=True`, `cisa_kev_detail`.
- **Exploit-DB**: site scraping (no API), batches of 5 + a 1-second pause, **per CVE**, writes `exploit_db_hits`
  and adds `cve_pocs`.
- **EPSS** (FIRST.org): batches of 100 → `epss_score`, `epss_percentile`, `epss_date`.

Properties worth knowing (not bugs I wrote, just how it is):
- The CVE set = `cve_id`s that are still **true positive for at least one client**: there is a tracker row that is
  NOT marked FP by its own client (`list_true_positive_cve_ids()`; FP is judged per `(cve_id, client_id)`).
  It used to count only the `"default"` client's FPs (changed in PR #14). The result is written to **every row
  (across clients)** for that `cve_id`.
- **There is no freshness filter**: everything is re-checked every 3 hours. The cost grows linearly with the
  tracker's size (Exploit-DB is the heaviest: ≥1 second per 5 CVEs + an HTTP call per CVE).
- The "KEV/EPSS/Exploit-DB" buttons on the CVEs tab run the same lookup (not client-scoped).

**`github_poc_monitor`** (scraper, `CvePocItem` → `cve_pocs`, sets `poc_available`): two strategies
(broad: `cve-<year>-*` repos filtered through MITRE vendor/product against the techstack; targeted: each
true-positive CVE). The Telegram alert on the `github_poc` topic comes only from the broad strategy.

Related: `trending_cve` (scraper) collects CVE mentions from tweets into `cve_mentions` (not `cve_tracker`).

## 5. CVEs tab scope, statistics, dashboard, export

`routers/cve.py`. **"Only CVEs for monitored techs" is in fact already the case**, through two layers:
1. `cve_tracker` rows are only created for (client, tech) pairs that matched at ingest.
2. The list/stats/dashboard queries use `effective_tech = tech (param) or the names of all of the client's techstack`
   (`_active_tech_names`). Since slice 5 (#19) "all techstack" = **active** entries (`techstack_entries.active`;
   inactive = hidden, the rows are not deleted). **A client with NO entries at all: `effective_tech = None` =
   no tech filter** (all rows shown, the old behaviour). **A client that has entries but all of them inactive:
   `[]` = an empty tab** (not "no filter"; otherwise "hidden" would mean the opposite). `purge_orphaned` uses
   ALL names (active + inactive): hidden rows are not orphans.

Other filters: `search` (cve_id/summary/tech, ILIKE), `severity`, date range (`date_basis`: `published` = default,
or `detected` = the WIB calendar day on which the CVE was first detected), `ack_filter`
(`acked`/`unacked` via `cve_tickets.acknowledged_by`), FPs hidden unless `include_fp`. Sorting:
`published`/`tech`/`severity`/`epss`. Serialisation (`_serialize`) adds `adjusted_risk_score` =
`cve_score × EXPOSURE_MULTIPLIER × HOSTING_MULTIPLIER` (from `techstack_entries` via the lower-case name), the count and list
of articles that mention the CVE in their title (`get_article_mentions`: ILIKE is only a rough filter, followed by an exact match with a number
boundary, so `CVE-2026-1234` is not `CVE-2026-12345`), and the FP status.
- `GET /stats`, `GET /dashboard?year=` (MTTD/MTTA/MTTR, `services/cve_dashboard.py`), `GET /export` (Excel
  from the `CVE_Tracker_template.xlsx` template, `services/cve_export.py`) use **the same scope** (client,
  active techstack, no FPs), so their numbers are consistent with the CVEs tab. (Correction: before slice 5 `/export`
  did NOT filter by techstack at all, only by the `tech` query param; now it is `tech or active entries`, so orphan
  rows and rows of inactive entries are not exported.)
- `GET /stats` has an `unrated` bucket (CVSS score 0/NULL: the CNA did not fill in CVSS) so that critical + high + medium +
  low + unrated = total. `date_basis` is also on `/stats` and `/export`. API defaults: `published` for list/stats,
  `detected` for export (the monthly report); the UI sends the same basis to all three (default Published).
- `GET /tech-list`: the distinct techs in the client's tracker that CAN show up on the CVEs tab (for the filter dropdown): active
  entries only. Orphan rows (their techstack entry was deleted) and rows of inactive entries are not offered; a client
  with no entries at all = no filter (every tech in the tracker), same as the tab.
- **`GET /freshness`** ("updated as of when", `services/cve_check.py`): when the tracker was last checked, per the path
  currently filling it. Path = the `new_cve` scraper (time from `scraper_runs`) or the CVE List V5 mirror (`polled_at` in
  `job_state` `cve_mirror.state`) when promotion is `live`; both when `KEEP_LEGACY_NEW_CVE` (the same rule as
  `cti_scraper.supersede`, locked by a test). `last_checked_at` = the last **successful** run (`ok`/`empty`/`partial`);
  a failed last attempt (`rate_limited`, etc.) is reported separately (`last_run_status`) so it does not look
  like the data was just refreshed. A `running` run older than 30 minutes is treated as stuck (worker dead), not
  in progress. Also `newest_detected_at` and, when `new_since` (ISO) is given, `new_since` = the number of new CVEs
  recorded (`detected_on`) since then, in the same scope as the CVEs tab (active client, monitored techs, no FPs).
- **`POST /check-new`** (the manual check button; **admin**, audit `check_new_cves`): sends the routine check task to
  the active path: `scrape.run(new_cve, trigger=manual)` to the scraper queue or `cve.mirror_sync` to `maintenance`
  (the API only sends by name, the `services/monitor.py` pattern). Rejected with **409** while a run is still in progress or the scraper
  is disabled in the control plane, **429** during the 120 s cooldown (`Retry-After` = the time left; a 409 rejection does not
  use the cooldown), **503** when the broker is down (the cooldown is released). Note: the `new_cve` check processes **all clients**
  at once (one global run); only the "new CVEs" count is per client. This is NOT "Populate now" (ROADMAP #3,
  history backfill): it only runs the routine check right now.
- `GET /prioritize`: priority score (`services/cve_priority.py`): CVSS 30%, KEV 20%, exploited 20%, PoC
  10%, `in_tech_stack` 20% → a label and `patch_urgency`. If a CVE has rows for several clients, the calling
  client's row is used (other clients' rows are only a fallback when the CVE is not yet tracked by that client).
- Multi-tenant: `X-Client-ID` → `effective_client_id`.

## 6. Tickets, acknowledge, false positive

- **Acknowledge** (`POST /{cve_id}/acknowledge`, `bulk-acknowledge` max 100): no analyst name in the body;
  `acknowledged_by` = **the logged-in username** (same as FP `marked_by` and the audit log). `analyst_name` in the
  body used to be mandatory and stored as-is (a legacy of the old UI: a shared password + a typed name), so anyone
  logged in could act in another analyst's name; old clients that still send it are accepted, the field is ignored.
  Creates/touches `cve_tickets` (sets `acknowledged_by`, `acknowledge_time`, `ticket_id` if not set yet).
- **Ticket** (`PUT /{cve_id}/ticket`): `affected_asset`/`affected_version`/`fixed_version`, `asset_owner`,
  `owner_email`/`owner_team`, `active_exploitation` (analyst input, distinct from the machine bool),
  `remediation_status`/`remediation_date_plan`/`actual_remediation_date`, `escalation_required`, `comments`,
  `risk_acceptance`, `closure_date`. Status values are a "soft enum" **without validation** (ROADMAP #18).
- **False positive** (`POST/DELETE /{cve_id}/false-positive`, `bulk-false-positive` max 100): per
  `(cve_id, client_id)`, recorded in the audit log. A tracker row is only treated as FP if **the client that owns the row**
  marked it (`is_false_positive_row`); marks by other clients, including clients that do not track that CVE,
  do not count. This rule is used everywhere that is not scoped to a single client: enrichment and the newsletter
  (`list_true_positive_cve_ids`), the `recap` digest, the CVE exposure table in `exec_dashboard`, `crossref`, and the CVE list
  for the GitHub PoC monitor (`reference_data`). A CVE only disappears from those once **every** one of its rows has been FP'd by
  its own owner. They used to use the FP set of any client, so one client marking an FP
  hid that CVE from the other clients.
- **Writes only for CVEs in the calling client's tracker**: `POST /{cve_id}/false-positive`,
  `bulk-false-positive`, `PUT /{cve_id}/ticket`, `POST /{cve_id}/acknowledge`, and `bulk-acknowledge` answer **404**
  (`CVE not tracked by this client: ...`) if the CVE has no `cve_tracker` row for the active client; one unknown id
  fails the whole bulk list and nothing is written. Exception for tickets and acks: a CVE
  that ALREADY has a ticket (e.g. orphaned after a purge) can still be changed. `DELETE /{cve_id}/false-positive`
  (clearing an old mark) and `GET /{cve_id}/ticket` (`{}`) are not checked. The check lives in the router
  (`_require_tracked`), not in the repo, so tools and tests that call the repo directly are unaffected.
- Write actions that are read back (false-positive, ticket, bulk-acknowledge, purge) call
  `AsyncAuditLogRepo.write` then `commit`.
- **The `cve_id` in requests is normalised and validated** (`schemas/cve.py::CveId`): the `/{cve_id}/...` path (FP, ticket,
  acknowledge, exploit-lookup) and `cve_ids` in the body of `bulk-false-positive`, `bulk-acknowledge`, `draft-email`.
  Upper case, surrounding spaces stripped, format `CVE-YYYY-NNNN` (4-11 ASCII digits); anything else is **422** and nothing
  is written (one bad id fails the whole bulk list). `cve_id` matching in the DB is exact, so without
  this `cve-2026-1234` would become its own FP/ticket row. Duplicate ids in a bulk list are counted once.
  **No existence check yet**: FPs/tickets can still be created for a CVE that client does not track
  (a product decision, see the note in the PR).
- **Ticketing view** = `GET /tickets` (ticket + CVE summary: severity, score, tech, `detected_on`, `false_positive`).
  Tickets of FP CVEs are hidden unless `include_fp=true` (the UI requires Acknowledge before Mark FP, so every FP CVE
  has a ticket).
- **Draft email** (`POST /draft-email`): 3 LLM calls + the `cve_notification_email.html` template, creating a
  draft via Microsoft Graph. **Manual**, triggered by an analyst. Only tracker rows of the active client (`X-Client-ID`) are
  used. Tracking ID = the existing ticket numbers for the CVE (comma-separated); the next "peek" number (not
  saved) is only used when there is no ticket at all.

## 7. Notifications: what EXISTS

**New CVEs in `cve_tracker` -> a Telegram summary (new on 2026-10-07, on the `nameless/roadmap-runners` branch, not yet
on `main`).** Before that there was **no** automatic notification per new CVE: `_cve_sink` only upserted, and
`legacy_label="NEW CVE"` was just a health compatibility label. (A correction to an earlier verbal assumption.) Now:
- `_cve_sink` uses `CveTrackerRepo.upsert_with_status`; when a row is **created** (INSERT, not update) it records
  `(cve_id, client_id)` in `Session.info["cve_new_rows"]`.
- `Runner.execute()` calls `sinks.finish_run(session)` **after** the run is recorded as finished ->
  `cti_scraper.cve_alert.notify_new_cves`: re-reads those rows from the DB, filters them, sends **one message per client
  per run** to the Telegram `cve_new` topic (`TELEGRAM__THREAD_IDS`).
- Filter: only `published` within the **last 3 days** (a new tech/backfill/new DB does not flood the channel;
  no publish date = not sent), and not a false positive of that client. "Monitored tech" needs no
  filter of its own: tracker rows are only created for (client, tech) pairs in `techstack_entries`.
- Format: title + client name + count; at most 10 CVEs (most severe first), the rest as "and N more";
  always < 4096 characters (rows are dropped until it fits); all external text is `html.escape`d.
- **A send failure does not fail the run and is not retried** (`cve_new_alert_failed` in the log): because the sink
  has already committed, the next run sees those rows as updates. If the `cve_new` topic is not in the prod `.env` yet =
  the alert is not sent, ingest keeps running.
- **Deploy**: add `"cve_new": <thread id>` to `TELEGRAM__THREAD_IDS` in the host `.env` (value `0` = the main
  chat without a thread). `.env.example` and `.env.prod.template` already contain it.
- If the pipeline is replaced by mirror -> promotion (#19), the call point is the same: "a new `cve_tracker` row was created".
  That is already the case in the code (slice 4, `CVE_MIRROR__PROMOTE=live`; when `live` the `new_cve` scraper is suspended, slice 7,
  `docs/CVE_CATALOG_CUTOVER.md`): `cve_promotion` fills
  `Session.info["cve_new_rows"]` and the `cve.mirror_sync` task calls `finish_run` after commit. Default
  `off`: the flow above is unchanged.

Other CVE-related items (unchanged):

| What | Trigger | Destination | Uses the techstack? |
|---|---|---|---|
| Article alert (`cti_enrich` routing) | every enriched article; `related_tech_status` (the title names a tech) or `related_tech_cve_status` (a CVE vendor in the title matches) | `tech_stack` topic | yes, **a distinct list of names across clients** (`score()`) |
| Weekly top CVE (`report.weekly_top_cve`, Sunday 07:01) | beat | `tech_stack` | yes (`techstack_names`, **across clients**) + `applicable_to_stack` |
| Trending CVE (`report.trending_cve`, certain hours at minute 5) | beat | `tech_stack` when it matches, otherwise `tech_stack_unrelated` + `vendor_report` | yes, same |
| GitHub PoC alert (`github_poc_monitor`) | a new repo <= 3 days old from the broad search | `github_poc` | yes (via MITRE vendor/product) |
| CVE draft email | an analyst presses the button | Graph (draft) | no |

The digests and the article/report alerts use the techstack names **combined across all clients**, not per client; the
new-CVE summary above is the only per-client one.

The newsletter (`services/newsletter._enrich_articles`, global, not per client) also correlates articles with the
tracker: articles whose title/body mention a CVE that is still **true positive for at least one client**
(`list_true_positive_cve_ids()`; FP judged per client row, not just `"default"`, changed in PR #14) get
`cve_mentions` and `possibly_exploited_wild`. The mention is written to `cve_newsletter_mentions` on **one**
tracker row (any client, DB order), and that table is not read by anything yet.

## 8. UI map (`apps/web/src/app/(app)/cve/page.tsx`)

Two views: **CVEs** and **Package Vulnerabilities** (`pkgvuln/`, not studied here). Inside CVEs there are
four sub-views: **CVEs** (`cve-core-view`: the filter bar, an "Updated ... + Check for new CVEs" row (`cve-check-new`:
the last check time, an admin button that polls until the check finishes and then reports the number of new CVEs), the KEV/EPSS/Exploit-DB lookup toolbar + Excel Export,
the list, `cve-detail-modal` with the Ticket tab), **Dashboard** (`cve-dashboard-view`), **Ticketing**
(`cve-ticketing-view`), **Tech Stack** (`techstack-panel`: add, delete, change exposure/hosting; a text input
"Tech name..." without validation). The browser does not call the API directly; it goes through `/api/proxy/[...path]`.

## 9. Tech name matchers (seven, not six)

`docs/CVE_TECH_MATCHING.md` 2.4 lists six. There are actually **seven**; the seventh was not recorded and
**is not touched by phase 1**:

| # | Where | Rule on `main` |
|---|---|---|
| 1 | `new_cve._nvd_candidates` | NVD `keywordSearch` (a candidate finder, not a matcher) |
| 2 | `new_cve._tenable_candidates` | word by word (`_mentions`) |
| 3 | `new_cve` gate (`relevant_techs`) | whole word + attached version number |
| 4 | `score.py` `related_tech_status` | `\b{tech}\b` **without `re.escape`** |
| 5 | `score.py` `check_tech_stack` | substring without word boundaries |
| 6 | `cve_priority.in_tech_stack` | substring in both directions |
| **7** | **`reports/cve_record.py::applicable_to_stack`** | **`re.escape(tech)` substring against the vendor, without word boundaries** (label "Might Applicable to Organization!") |

The `nameless/roadmap-runners` branch (not yet on `main`) unifies 2-6 into `cti_core.tech_match`; **#7 is a deliberate
exception (user decision 2026-10-08)**: `test_cve_record.py` locks `c++` ~ `c++ inc`, which contradicts
the rule "terms < 2 characters never match"; the Top CVE report does not follow the catalog path and its behaviour
is not changed.

## 10. What must be preserved when changing the design (invariant checklist)

1. `cve_tracker.tech` is **text that matches the lower-cased `techstack_entries.name`**; `get_risk_context`,
   the `tech` filter, `purge_orphaned`, and the dashboard depend on it. If the catalog replaces names, the display
   label must still be `name` (or the join must be replaced in all those places at once).
2. **Tickets and FPs are keyed by `(cve_id, client_id)` with no FK to the tracker**: safe from cascades, but it means
   that if a tracker row is dropped (retention) its ticket is orphaned. `purge-orphaned` and `reconcile_cve_tech` already
   protect rows that have a ticket/ACK; promotion into `cve_tracker` and any other dropping path must preserve that.
3. One tracker row = **one tech** per (CVE, client); `upsert` overwrites `tech` on every run.
4. **An empty techstack = the CVEs tab without a tech filter** (but `purge_orphaned` treats everything as orphaned, except rows with a ticket). **Decided in
   slice 5**: no entries at all stays unfiltered (no behaviour change); entries that are all
   inactive = empty. Confirmed by the user 2026-10-08 (`docs/CVE_CATALOG_DESIGN.md` 9.5).
5. The enrichment sweep works **across clients** and without a freshness filter; scaling "always enriched" to
   many techs needs `*_checked_at` as a filter.
6. `detected_on` is set on the first INSERT; it is the basis of the dashboard KPIs. CVEs promoted from the mirror must
   set `detected_on` deliberately (the time the system found it, not the publish date) so MTTD stays
   meaningful.
7. New-CVE notifications depend on **the INSERT of a tracker row** (section 7): any path that creates rows
   (promotion from the mirror) must go through `upsert_with_status` + `finish_run`, not a direct insert.
8. Export, `/stats`, and the dashboard must keep using **the same scope** as the CVEs tab.
9. **The first ack wins**: `acknowledge` (single) and `bulk_acknowledge` do not change a ticket that is already acked
   (name, `acknowledge_time`, `ticket_id`); a repeated ack still returns `200` with no effect. `acknowledge_time` is the basis of MTTA on
   the dashboard. Both take the numbering lock BEFORE reading the ticket, so two simultaneous acks are serialised (the
   second sees the first ack). The single ack used to overwrite all three.
10. **FP, ticket, and ack only for tracked CVEs**: all three are keyed by `(cve_id, client_id)` with no FK to the tracker,
    so the existence of a tracker row is checked in the router (`_require_tracked`); without it any valid id would create an orphan
    ticket or an FP mark for a CVE that was never tracked.

## 11. Not yet verified (honestly)

Not read in full: `pkgvuln` (the Package Vulnerabilities view), the contents of `cve_export.py`, `cve_email.py`,
`campaign_analysis`/`crossref` (their contents; one thing was confirmed by grepping `apps`, `packages`, `scrapers`,
`tools`: **no code writes `cve_threat_actors`/`cve_ttps`**, only `crossref` reads them, so
its TA/TTP branches have no data unless a writer exists outside this repo),
the UI details of `cve-detail-modal`/`cve-ticket-tab`, `tools/seed/fase10_cve_migrate.py`, the `scrape.run` task
(the manual trigger `POST /api/scraper/{id}/trigger`). `new_cve`'s behaviour in production (how many candidates per run,
how many pass the gate) is only known from the 2026-10-07 `reconcile_cve_tech` report in
`docs/CVE_TECH_MATCHING.md`.
