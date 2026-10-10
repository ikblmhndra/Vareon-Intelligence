# Post-cutover roadmap

A record of requests, written on 2026-09-26 (user requests, order = the order of work) and updated as they are
delivered; **status as of 2026-10-10 is in "Delivered so far" right after the index**. Not a schedule commitment: each
open item only needs the input/decision written under it.
What is **already** running and not roadmap is in `docs/PROGRESS.md`; the cutover gate is in
`docs/CUTOVER_RUNBOOK.md`.

Each item contains: **what** was asked, **the current state** (facts from the repo/staging, not guesses),
**touch points** (files), **what is needed** before starting, and **how to prove it is done**.

| # | Item | Needs from the user | Depends on |
|---|---|---|---|
| 21 | **PRIORITY (team feedback 2026-10-10)** -- **Improve the Recap feature**: weekly instead of daily (a manual daily trigger stays), fewer/cheaper LLM calls, week-over-week comparison, grounding check, forecast scorecard -- **scope decided 2026-10-10, not built** | the week boundary and generation time (WIB); recap language | -- |
| 22 | **PRIORITY (team feedback 2026-10-10)** -- **Newsletter**: biweekly (Fridays, WIB), Indonesian content, redesigned template (mockup drawn, `docs/mockups/newsletter-redesign.html`), recommended articles in the composer, executive summary reused from the weekly recap, per-article summary cache and one history row per send -- **scope decided 2026-10-10, not built** | the first edition date; confirm the preparation time of the suggested draft (assumed Friday 09:00 WIB) | #21 (the executive summary reuses the weekly recap; shared LLM usage logging) |
| 1 | Rebranding the platform name + UI (colour palette, typography, animation) -- **DONE 2026-10-02, the SVG logo remains** | brand assets | -- |
| 2 | Rebranding the `newsletter_email` and `cve_notification_email` templates -- **code done 2026-10-02, email client verification not yet** | (the same assets as #1) | #1 |
| 3 | (probably superseded by #19) A "Populate now" button in the CVE Tracker (all / only newly added) | a small decision (see the item) | -- |
| 4 | IOC enrichment + reputation (VirusTotal, AbuseIPDB, urlscan, Shodan/GreyNoise) | an API key per service, quotas | -- |
| 5 | Outbound IOC/CVE feeds (TAXII 2.1 and/or CSV/JSON) + integration API keys | target tooling (Wazuh/Splunk/Fortinet?) | #4 |
| 6 | IOC lifecycle: first/last seen, sightings, expiry/decay | an IOC age decision | #4 |
| 7 | Relevance to our own assets: threats x techstack, alerts for actors targeting our stack | tidy asset data | -- |
| 8 | MISP/OpenCTI connector (import + export) | a target instance | #5 |
| 9 | Dark web monitoring through aggregator sources (breaches, ransomware leak sites, Telegram) -- not crawling onions ourselves | budget, a list of executive domains/emails, internal approval | -- |
| 10 | Case/RFI workflow (assignment, SLA, status, audit) linked to CVE tickets | the team's workflow | -- |
| 11 | Consistent TLP/PAP on every object + MFA/SSO | a TLP policy | #5 |
| 12 | Improving the article classification prompt based on the audit trail (false accept / false reject) | examples of misclassified articles | the `raw_enrichment` audit trail (running since 2026-10-05) |
| 13 | **CI on `main` is red** (3 jobs), so the Deploy job has never run (5 runs, all `skipped`) -- **green CI on `main` proven 2026-10-07 (run #23); Deploy has run 3 times (#8-#10, 2026-10-07/08) and all 3 were `cancelled`, none has passed, cause unknown** | -- | -- |
| 14 | Logo missing from the CVE Tracker Excel export (Pillow is not yet a dependency) -- **done 2026-10-07 (PR #9); the API image build with pillow is green in CI (PR #12)** | -- | -- |
| 15 | Use `published_at` in the UI/API/dashboard + align the export date formats | a decision on the format of the Acknowledged column | the `published_at` backfill in production |
| 16 | CVE dashboard: SLA per severity (replacing fixed-threshold ratings) | ack/remediation SLA targets per severity | -- |
| 17 | CVE dashboard: backlog/aging panels, KEV/EPSS, most frequently affected products | a choice of panels | -- |
| 18 | CVE ticket field validation + a ticket model decision (1 ticket per CVE vs one ticket for many CVEs) | a list of standard values, the model decision | -- |
| 19 | **Tech catalog from the CVE mirror + Monitor** (new direction 2026-10-07, replacing the alias/phase 2-3 plan; the `aliases` column is dropped): mirror every CVE (calendar-year retention) -> a vendor+product catalog -> All Tech / Monitored Tech tabs -> the CVEs tab only for monitored techs. **Code done (slices 1-7), merged to `main` 2026-10-08 (PR #12, release 0.3.0)**; what remains is operational: mapping the 34 entries on dev, shadow mode, cutover (`docs/CVE_CATALOG_CUTOVER.md`); design `docs/CVE_CATALOG_DESIGN.md` | manual mapping + shadow on dev | test on the dev server first, then prod |
| 20 | **Known follow-ups from releases 0.4.0 / 0.4.1** (found while reviewing the CVE Tracker; none is blocking) | product decisions on the points marked (D) | -- |

---

## Priority queue (team feedback 2026-10-10)

The team asked for two items to be treated as priorities; they go before everything that is still open. Order:
**#21 Recap first** (it introduces LLM usage logging and the weekly content that #22 reuses), then **#22 Newsletter**.
Scope was decided with the user on 2026-10-10 (which proposed additions were approved and which were left out are
listed in each item); both are written out at the end of this file. Nothing is built yet. The questions that still block
work are under **Needed** in each item.

---

## Delivered so far (as of 2026-10-10)

PRs #2-#31 are all merged into `main` (release tags in `CHANGELOG.md`: 0.2.0, 0.2.1, 0.3.0, 0.4.0, 0.4.1).

**Roadmap items by status**

| # | Status | Delivered by | What is left |
|---|---|---|---|
| 1 | Done | PRs #3, #4 (+ the rename to Vareon Intelligence, 2026-10-05) | the SVG logo |
| 2 | Code done | PR #3 | verification in real email clients |
| 3 | Superseded by #19 | PR #12 | nothing, do not work on it |
| 13 | Partly done | PR #11 (CI green on `main`, run #23) | one Deploy that passes: runs #8-#10 were all `cancelled`; check the prod host state |
| 14 | Done | PR #9 (pillow), CI image build green in PR #12 | nothing |
| 19 | Code done, merged | PR #12 (release 0.3.0), PR #27 (cutover runbook fix) | operational only: map 34 entries on dev, shadow mode, cutover dev then prod |
| 21, 22 | Open, **priority** | -- | scoped 2026-10-10, waiting on the answers listed in each item |
| 4-12, 15-18 | Open | -- | not started; only prerequisites exist (e.g. the `raw_enrichment` audit trail for #12, the `published_at` column for #15). See each item |

**Merged PRs by release**

| Release | PRs | What they delivered |
|---|---|---|
| before 0.2.0 | #2, #3, #4 | date-independent TA timeline test; rebrand (themes, font, emails, #1/#2); UI redesign (sidebar, world map, cards) |
| 0.2.0 (2026-10-05) | #5, #6, #7 | end-to-end QA fixes (API security, session/JWT, CVE data bugs, UI); CD that deploys to prod after green CI on `main` (see #13); release |
| 0.2.1 (2026-10-06) | #8 | CVE Tracker Tech must match the affected product (`reconcile_cve_tech` tool) |
| 0.2.1 -> 0.3.0 (2026-10-07) | #9, #10, #11 | CVE Dashboard (MTTD/MTTA/MTTR) + backfill tooling, Excel logo (#14); docs fix for the `reconcile_cve_tech` server command; CI green on `main` (#13) |
| 0.3.0 (2026-10-08) | #12, #13 | **#19 tech catalog + CVE mirror + Monitor** (slices 1-7), new-CVE Telegram summary, one shared tech matcher, Chromium in CI; release |
| 0.4.0 (2026-10-09) | #14-#23 | CVE Tracker logic review: NVD window offset, client scope, article mentions, ticket numbers, stats; CVE id validation; FP per client; `acknowledged_by` from the login, first ack wins; purge/write protections; "last updated" line + manual **Check for new CVEs**; release |
| 0.4.1 (2026-10-09) | #24-#28 | `affected` text no longer starts with `<=` twice (+ `tools/ops/fix_affected_double_operator.sql`), Exec "Critical CVEs" caption, Dashboard "unrated" tile, runbook fix; release |
| after 0.4.1 | #29, #30, #31 | Exec KPI cards: Critical CVEs and KEV CVEs separate with full totals (2026-10-09); `docs/ARCHITECTURE.md` + all docs in English (2026-10-10); a URL that is already an article is not re-enriched or re-alerted (2026-10-10) |

Not yet released as a version: #29-#31 are on `main` after 0.4.1. Follow-ups found while delivering 0.4.x are
collected in #20 below.

---

## 1. Rebranding the platform name and UI

> **Status 2026-10-02 -- done** (PRs #3 and #4). Display name **Vareon Intelligence** (one constant
> `apps/web/src/lib/brand.ts` + the `platform_name` setting in `cti_core.config`); light and dark themes
> (`globals.css`, separate severity tokens, contrast checked to AA); the Google Sans Flex font; `prefers-reduced-motion`;
> the sidebar, dashboard + world map, every tab and the main dialogs checked on staging. Technical identifiers (`cti-platform`,
> `cti_*`, images) deliberately stay. **Remaining**: the SVG logo (the header is still the letter "N" + text), and a `grep` for the old name in
> LLM prompts ("Cyber Threat Intelligence" as a generic term) is deliberately left alone.

**Asked**: change the platform name and the UI look -- *colour palette*, *typography*, *animation* -- according to
assets the user will provide.

**Current state**
- The name "CTI PLATFORM" is written directly in 9 files, not from a single source:
  `apps/web/src/app/layout.tsx` (page title), `apps/web/src/app/login/page.tsx`,
  `apps/web/src/components/app-header.tsx`, `apps/api/src/cti_api/main.py`,
  `apps/api/src/cti_api/services/stix.py`, `apps/api/src/cti_api/templates/newsletter_email.html`,
  `packages/cti-core/src/cti_core/db/repositories/{attack,mitre}.py`, `tools/codemod/run_migration.py`
  (the last one is a migration tool -- ignore it). Telegram message titles and Excel headers also need checking
  (not grepped yet).
- Colours: `oklch(...)` tokens in `apps/web/src/app/globals.css` (`--background`, `--foreground`, `--primary`,
  `--accent`, `--radius`, ...). The current theme is dark with blue/cyan accents.
- Fonts: three Google fonts via `next/font` in `apps/web/src/app/layout.tsx` -- Rajdhani (body),
  Share Tech Mono (headings/numbers), IBM Plex Mono (data); mapped to `--font-sans/--font-heading/--font-mono`.
- Animation: not inventoried yet (the first step of this item).

**Needed from the user**: the final name; a logo (SVG); a colour palette (light and/or dark) including the
severity colours (critical/high/medium/low -- semantic, they must not change by accident); fonts + their licences;
animation guidelines (and the stance on `prefers-reduced-motion`).

**Design proposal (to decide together)**
- Change the **display name** only (UI, email, Telegram, STIX producer). Technical identifiers (`cti-platform`,
  `cti-*` images, `cti_*` package names, env vars) **stay**: changing those = a lot of churn with no value for
  users, and it breaks the tags/volumes/rollbacks that have already been drilled.
- One source for the name (a `platform_name` setting in `cti_core.config` for the backend; one constant for the web)
  so the next rebrand is in one place.
- Severity colours separated from brand colours in `globals.css`.

**Done when**: every tab + the login page + email + Telegram messages use the new name/colours/fonts; text-background
contrast meets WCAG AA in the themes used; a screenshot of each tab is attached; a `grep` for the old name = empty
(except the technical identifiers that deliberately stay).

---

## 2. Rebranding the email templates

> **Status 2026-10-02 -- code done, verification not yet**: `templates/_base_email.html` (Jinja `extends`) is used by
> both emails; brand palette, hex only, a fallback font stack, `platform_name` from the setting. **Not yet**: sent through
> Graph to a test account and checked in Outlook desktop/web, Gmail, mobile (the "Done when" criteria below). Note:
> the newsletter preview on staging still fails with `500: Expecting value` on the server side (suspected LLM configuration
> in `.env`), separate from this template.

**Asked**: the `newsletter_email` and `cve_notification_email` templates follow the outcome of item 1.

**Current state**
- Files: `apps/api/src/cti_api/templates/newsletter_email.html` (240 lines) and
  `apps/api/src/cti_api/templates/cve_notification_email.html` (268 lines).
- Colours are written **inline** and duplicated in both files (e.g. `#1976d2`, `#0d1b2a`, `#00e5ff`, `#d32f2f`,
  `#e8ecf0`), not using the web tokens -- so a web rebrand does not change the emails automatically.
- The name is written directly in the newsletter header/footer ("Cyber Threat Intelligence", "CTI Platform").
- There is a test that touches sending (`tests/unit/test_mailer.py`); brand string assertions (if any)
  need updating too.

**Email client limitations** (do not break these when restyling):
- Inline CSS; no web fonts in many clients (Outlook desktop) -> define a fallback *font stack*.
- No `oklch()`/CSS variables -> use hex/rgb.
- No animation support -> the "animation" part of #1 does not apply to email.
- Severity colours must stay readable (red/yellow/green) in the client's light and dark modes.

**Proposal**: one Jinja *base layout* (`{% extends %}`) for both templates, so the next rebrand is in
one place (today the CSS is duplicated).

**Depends on**: #1 (the final palette + name).

**Done when**: both emails are sent through Graph to a test account and look right in Outlook desktop, Outlook
web, Gmail, and mobile; the render tests pass.

---

## 3. A "Populate now" button in the CVE Tracker

> **Superseded by #19 (code done 2026-10-08, on `main` since PR #12 / release 0.3.0).** A Monitored tech (the Monitor button,
> "Map to catalog", Resume, or a new target) immediately has its history filled from the mirror through the
> `cve.promote_entry` task (only when `CVE_MIRROR__ENABLED` and `CVE_MIRROR__PROMOTE` are on), so this button,
> the 8-day window, the 180-day backfill, and the MITRE pacing problem below are no longer relevant IF the cutover
> happens. **Do not work on it**; the section below records the state before the cutover.

**Asked**: a **Populate now** button to fill in CVEs, with a choice of **populate all** or **only
newly added techstack/packages**. It replaces the old hint text on the empty tab.

> **Update 2026-09-30**: the "CVE history empty on day one" part for OLD data (already
> tracked before the cutover) is ALREADY SOLVED by `tools/seed/fase10_cve_migrate.py` (migration from the Mongo dump,
> step 8 in `docs/CUTOVER_RUNBOOK.md`) -- see `docs/PROGRESS.md`. What REMAINS in this item is purely about
> techstack/packages added AFTER the cutover (not in the old dump), plus the desired UI button.

**Current state** (all measured on staging 2026-09-26, except where marked as updated above)
- CVEs are only filled by the `new_cve` scraper (hourly, bespoke, `scrapers/src/cti_scrapers/feeds/new_cve.py`):
  per techstack it queries NVD (`keywordSearch`) + Tenable, then fetches details from MITRE. Its search window is
  **only the last 8 days**.
- Consequence: a **new** techstack (added after the cutover, so not in the migration dump) only gets CVEs
  published in the 8 days before it was added -- **the history before that is never filled** unless
  triggered manually.
- **Legacy had this and it was deliberately not ported yet**: `POST /api/techstack/backfill-cves` (every techstack of one
  client), `POST /api/techstack/{id}/backfill-historical` (NVD **180 days** for one tech), and when adding a
  techstack legacy copied the existing CVEs + triggered a 180-day backfill. Recorded in the docstrings of
  `apps/api/src/cti_api/routers/techstack.py` and `apps/web/src/components/cve/techstack-panel.tsx`.
- Packages: `POST /api/pkg-vuln/packages/{id}/scan` (one) and `POST /api/pkg-vuln/scan` (all) already exist.
  Package scanning is **not scheduled** (nor was it in legacy: there is no Rundeck job for it); so on the package side a
  button action is enough, not a scraper.

**Foundations that already exist**
- The manual trigger `POST /api/scraper/{id}/trigger` (admin + audit log). The Celery task `scrape.run` currently
  **only** accepts `scraper_id` and `trigger`, and does **not yet** pass options through.
- The per-scraper options framework (`ScraperOption`, `Runner(options=...)`, `--option key=value`) can already
  override one run's behaviour **without writing to the DB** -- a fit for `scope`/`window_days`.
- `techstack_entries.added_date` and `created_at` = the basis for "newly added".

**What needs building**
1. `new_cve`: options `scope` (`all` | `recent`) and `window_days` (default 8; a longer backfill). For
   `recent`: only techstacks with `added_date` since a given date.
   NVD limits one request to **120 days** (the documented NVD API 2.0 limit) -> a 180-day window must be split.
2. **MITRE pacing**: the token bucket currently *does not wait* -- once 60/minute is used up, `RateLimited` and the run
   stops. A large backfill (hundreds of CVEs) will certainly hit it. It needs to wait for tokens / work in batches / continue
   in the next run. This is also a risk for normal runs when candidates > 60 in one go.
3. **Dedup**: `new_cve` deliberately has no dedup (MITRE can update scores), so every run calls MITRE again
   for every candidate. For a backfill, skip CVEs that already exist and whose `cve_modified_date` has not changed.
4. The `scrape.run` task + the trigger endpoint accept `options` (validated by `validate_options`, 422 if wrong,
   like PUT config). A dedicated endpoint, e.g. `POST /api/cve/populate {scope, since}` (admin, audit log),
   that returns the run id.
5. UI: a button on the CVE Tracker tab -> a dialog with two choices ("All techstacks" / "Only those newly added
   since ...") + the run status (a link to `/scrapers`); for packages, the existing scan action.
6. Tests: unit (options + window), integration (trigger with options), e2e on staging with a new techstack.

**Decisions needed from the user**
- How many days of history for a new techstack? (legacy: 180.)
- "Newly added" = since when? (e.g. the last 7 days, or since the last populate.)
- Who may press the button? (proposal: admins only, same as the scraper trigger.)
- Scan packages automatically when a package is added, or keep it manual?

**Done when**: adding a new techstack and then pressing "only new" fills its history without touching
other techstacks; "populate all" on a large techstack finishes without `rate_limited`; the empty tab shows this button
instead of the hint.

> Done in the same session and **not** part of this roadmap: the old empty-state text ("Run newCveThreat.py")
> was replaced; the bug where techstacks with multi-word names (`palo alto`, `microsoft 365`, `new relic`, `harmony sase`)
> had their CVEs silently dropped is fixed -- see `docs/PROGRESS.md`.

---

# Feature gaps towards a full Threat Intelligence Platform (proposal 2026-10-05)

Items 4-11 below are **proposals** (from the 2026-10-05 feature audit), not yet formally requested: order = the suggested
priority, feel free to change it. The gap pattern: the platform is already strong at **collecting and reading**
intel (scrapers, article enrichment, CVEs, ATT&CK, newsletter, exec dashboard), but weak at **acting and
connecting** to other tooling. `git grep` results in `apps packages scrapers`: zero hits for `taxii`, `misp`,
`opencti`, `virustotal`, `sighting`, `yara|sigma`, `siem|wazuh|splunk`, `api_key`, `sso|oidc|saml|mfa`;
`tlp` only in `services/stix.py` and `services/ta_profile.py`; `webhook` in 1 file. Existing touch points:
`routers/iocs.py`, `routers/stix.py`, `routers/techstack.py`, `routers/rfi.py`/`pir.py`,
`packages/cti-alerts` (Telegram + email), `db/models/ioc_reference.py` (`IocAllowlistEntry`).

## 4. IOC enrichment + reputation

**Asked (proposal)**: every IOC is enriched automatically (VirusTotal, AbuseIPDB, urlscan, Shodan/GreyNoise)
with its score/verdict and its source stored.
**Current state**: IOCs are extracted from articles (`cti-enrich`); there is no external enrichment yet.
**Needed**: an API key + quota per service (stored through the same secret mechanism as
`docs/SECRETS_ROTATION.md`), a decision on which IOCs are enriched (all vs only those linked to priority CVEs/actors)
so quotas do not run out.
**Done when**: the IOC detail shows the verdict + a source link, results are cached, rate limits are respected,
and one service failing does not fail the others.

## 5. Outbound feeds + integration API keys

**Asked (proposal)**: a TAXII 2.1 and/or CSV/JSON endpoint with TLP, confidence, and IOC age filters,
accessed with a per-service API key (not a UI login), so Wazuh/Splunk/Fortinet pull IOCs + CVEs automatically.
**Current state**: `services/stix.py` already builds STIX bundles; there is no TAXII yet and no API key
(auth is user JWT only).
**Needed**: the target tooling + the requested format, a TLP policy (#11), a decision on key scope
(per client).
**Done when**: one real tool pulls the feed with a key, the key can be revoked, every pull
is recorded in the audit log, and the result is scoped to `client_id`.

## 6. IOC lifecycle

**Asked (proposal)**: first/last seen, sighting counts, expiry or decay, and false positive/allowlist.
**Current state**: the allowlist already exists (`IocAllowlistEntry`); whether first/last seen, sightings, and expiry
exist **has not been checked yet** -- the first step of this item proves it against the `iocs` schema.
**Needed**: a decision on IOC age per type (IP vs hash vs domain).
**Done when**: expired IOCs automatically drop out of the feed (#5) without being deleted from history.

## 7. Relevance to our own assets

**Asked (proposal)**: link the techstack to threats -- an "actor X targets technology we use" alert,
exposure-based CVE priority, a "what is relevant to us" summary on the dashboard.
**Current state**: the techstack, the risk exposure/hosting multipliers in the CVE score (`routers/cve.py`), and
threat actor profiles already exist, but there is no actor -> techstack link and no alert for it yet.
**Needed**: a tidy and complete techstack (matching quality follows the quality of this data).
**Done when**: adding a techstack surfaces related actors/campaigns, and Telegram/email alerts are
only sent for those that match the client's stack.

## 8. MISP / OpenCTI connector

**Asked (proposal)**: two-way import and export.
**Current state**: none. Depends on #5 (an outbound format already tested).
**Needed**: a target MISP/OpenCTI instance, or confirmation that it is not needed.

## 9. Dark web monitoring (through aggregator sources)

**Asked (proposal)**: dark web monitoring with four goals: (1) **breach monitoring** of domains and executive
emails, (2) material for the **Executive Summary**, (3) **enriching the newsroom**, (4) **TA monitoring**. It also covers
this item's old intent (typosquat/brand, mentions in pastes) as a later phase.
**Design decision (from the 2026-10-05 discussion)**: **no onion crawler of our own**. Onion URLs change quickly,
so URL lists, captchas, and forum logins become a constant maintenance burden; it needs isolated
Tor infrastructure with security/legal risks (illegal content, malware); forums need accounts that will not be
created, or captchas that will not be bypassed. Take it from sources that already aggregate, so changing URLs are
their problem.
**Current state**: the `ransomware_victims` table + `routers/ransomware.py` + the ransomware panel in the newsroom
already exist (written by a scraper). Telegram is only **outbound** (`packages/cti-alerts/telegram.py` sends alerts);
**inbound** Telegram channel monitoring does not exist (not found in `scrapers/`). Breaches/leaked credentials:
zero hits in the code.

**Phases**
1. **Breaches + ransomware leak sites**: HIBP (domain search) or Intelligence X for domains and executive
   emails; additional ransomware leak-site sources (e.g. the ransomware.live API) into the existing table.
   Covers goal 1 and most of 4.
2. **Actor Telegram channels** (inbound) + link to the Executive Summary (2) and the newsroom (3): widgets
   "new victims in our sector", "leaked credentials in 30 days", "active actors"; articles linked to the victims/actors
   that appear on leak sites.
3. **(optional, if there is budget)** a commercial dark web service (e.g. Flare, SpyCloud) instead of
   crawling ourselves; paste monitoring and typosquat domains.

**Needed**: budget (deciding between HIBP only, which is cheap and covers breaches only, or a service that also
covers forums); the list of monitored domains and executive emails; a legal/policy decision on
storing leaked credential data (hash only or plaintext; who may see it); internal approval.
**Done when**: a monitored domain raises an alert when it appears in a new breach/leak (without duplicates),
the data is scoped to `client_id`, one source failing does not stop the others, and the Executive Summary
shows a summary of this data.

## 10. Case/RFI workflow

**Asked (proposal)**: assignment, SLA, status, and an audit trail on PIRs/RFIs, linked to CVE tickets
(the Ticketing sub-view).
**Current state**: `routers/pir.py` and `routers/rfi.py` exist; CVE tickets exist (`cve_tickets`); they are not
linked to each other.
**Needed**: the team's workflow (who receives RFIs, SLA targets).

## 11. Consistent TLP/PAP + MFA/SSO

**Asked (proposal)**: TLP/PAP labels on every object, enforced at distribution (#5); MFA/TOTP and SSO
(OIDC) if used across teams.
**Current state**: TLP only in STIX and actor profiles; no MFA/SSO.
**Needed**: the internal TLP policy, the IdP in use.

## 12. Improving the classification prompt based on the audit trail

**Asked**: the classification prompt needs improving, because some articles that should be valid become
invalid (rejected) and vice versa.
**Current state**: the `_PROMPT` in `packages/cti-enrich/src/cti_enrich/stages/classify.py` (copied
verbatim from the old system, judging **from the title only**). Since 2026-10-05 the raw LLM response, model, and
`prompt_version` are stored in `raw_enrichment["classify"]` (for accepted and rejected articles), so wrong cases
can be analysed and results across prompt revisions compared. Only articles processed after the deploy
have this data. The current error rate **has not been measured yet**.
**Touch points**: `classify.py` (`_PROMPT`, `ClassifyResult`), `routers/filtered_articles.py` (the rejected
list), `tests/unit/test_llm_json_retry.py`.
**Needed**: real examples of mistakes in both directions (rejected although relevant, accepted although not);
a decision on whether classification stays title-only or also reads the summary/body (more accurate, but
every article then needs a text fetch before classification, which reorders the stages in `pipeline.py`).
**Steps**: (1) collect 30-50 labelled examples from `rejected_articles` and `articles`; (2) measure the
current prompt's precision/recall as a baseline; (3) revise the prompt, re-measure on the same set; (4) release
with a new `prompt_version` and watch the daily rejection ratio.
**Done when**: a labelled example set is stored in the repo (tests/fixtures), the before and after metrics are
recorded, and the false reject/false accept ratios drop without increasing JSON failures.

---

# CVE Tracker and CI follow-ups (findings 2026-10-06)

Items 13-18 come from an audit of the `CVE_Tracker_Dashboard.xlsx` Excel workbook, the work on the CVE Tracker
Dashboard, the change to the Excel export columns, and reading the CI results on GitHub on the same day. 13-14 are
real defects with evidence; 15-18 are proposals (not yet formally requested), order = the suggested priority.
**Deliberately left out**: importing the 2026 Excel history (811 CVEs) into the platform, decided against on
2026-10-06 (the dashboard only reads platform data).

## 13. CI on `main` is red, automatic CD cannot be triggered

**Asked (proposal)**: make CI green again so `deploy.yml` (which only runs when CI succeeds for a push to
`main`) really gets triggered.
**Current state**: CI runs #11 to #16 (2026-10-05 to 10-06, including `main` @ `d3f2a04`) were all
`failure`. Three red jobs, three different causes (read from the GitHub Actions log, run #16):
1. `lint`: `ruff format --check .` rejects 2 files, `docs/ADDING_A_SCRAPER.md` and
   `tests/unit/test_rss_illegal_xml_chars.py` (reproduced locally; `ruff format` fixes them).
2. `compose`: `env file .../.env not found`. `docker-compose.yml` contains `env_file: ${CTI_ENV_FILE:-.env}`,
   while the job only has `docker/stack.env.example` (`.env` is not in git).
3. `test`: 2 tests failed, 2150 passed, 3 skipped. (a) `tests/contract/test_golden.py::test_golden_trendmicro`: Playwright's
   Chromium is not installed on the runner. (b) `tests/integration/test_articles_router_snapshot.py::
   test_article_dedup_groups`: the seed uses a hardcoded `_TODAY = datetime.date(2026, 9, 24)`, while
   `services/dedup.py::get_dedup_groups` uses a 7-day window from `date.today()`, so this test has been dead
   since 2026-10-01 (a time bomb, not a code regression).
As a result all five Deploy runs (#1-#5) are `skipped` (their condition is CI `success`): the deploy job has never
run even once. The other jobs (typecheck, web, api-contract, 4 image builds, gitleaks) are green. The codecov upload also fails
("Token required") but has `continue-on-error`, so it does not turn the job red.
**Touch points**: `.github/workflows/ci.yml` (`compose`, `test`), `tests/integration/
test_articles_router_snapshot.py` (`_TODAY`), the 2 files mentioned above.
**Needed**: no decisions; for (3a) choose between installing Chromium in the `test` job
(`playwright install --with-deps chromium`, adding a few minutes) or skipping tests with the
`playwright` marker when the browser is missing (like the Docker tests that are already skipped automatically).
**Done when**: CI is green on `main`, and Deploy is triggered once (automatically or via `workflow_dispatch`) and
passes `deploy.sh` with its health check. Until then, production can only be updated manually (`make deploy`, or Actions > Deploy > Run workflow).
**Status 2026-10-07**: all four causes are fixed, each reproduced and then proven locally:
1. `lint`: `ruff format` on the 2 files (`ruff format --check .` clean, 574 files).
2. `compose`: the step sets `CTI_ENV_FILE: .env.example` (the mechanism already documented at the top of
   `docker-compose.yml`); `docker compose config -q` passes for the default and `app` profiles.
3a. `test`: a `uv run playwright install --with-deps chromium` step before pytest, through the playwright in the venv
   so the Chromium revision matches `uv.lock` (1.63.0 wants revision 1243; it failed locally for exactly the same
   reason as CI because only revision 1194 was present). The test content is proven to pass with real Chromium.
3b. `test_article_dedup_groups` seeds with `date.today()`; the old version fails and the new one passes on
   a local Postgres 16 (8/8 snapshots pass). The pinned `_TODAY` is deliberately kept for the tests whose snapshots
   contain `week`/`month`.
**Not yet proven**: a fully green CI (only available once a PR is opened; CI only runs on `pull_request` and pushes to
`main`), and the first triggered Deploy on the prod runner. The `playwright install --with-deps` step has not
run on a GitHub runner yet (the development sandbox may not install browsers); `docker/api.Dockerfile` and
`docker/worker.Dockerfile` use the same command through `uv tool run`.
**Result after PR #11 was merged (2026-10-07)**: CI on `main` @ `35e6def` is green (run #23, all jobs). Deploy
**was triggered for the first time** (run #8, `workflow_run` from that CI) and ran on the self-hosted runner, but ended
`cancelled` after 10m25s. Not a timeout (`timeout-minutes: 45`) and not superseded by another run
(`cancel-in-progress: false`); the job log is a 404 from the GitHub API, so the cause cannot be read from here
(possibly cancelled manually or the runner disconnected -- not confirmed). What remains of "Done when":
one Deploy that passes `deploy.sh` with its health check. **After an interrupted deploy, check the state of the prod
host**: `docker compose ps`, the `:prev` vs latest image tags, and `alembic current` (whether `migrate` got to run).
**Found when PR #11 ran in CI (2026-10-07), fixed in the same PR because it blocked "green CI"**:
`tests/unit/test_ioc_extractor.py::test_domain_defanged_regex_does_not_catastrophically_backtrack` was red on the
GitHub runner (the only failure out of 2240 tests; the two tests fixed above passed, so the
`playwright install` step is proven to work). Cause: an alarm threshold of 5 seconds for 2000 repetitions, while
`_RE_DOMAIN_DEFANGED` (`{0,10}`) has a large LINEAR cost (~0.45 ms per character; 1.3 s / 2.7 s / 5.4 s for
500 / 1000 / 2000 repetitions on the dev machine, ~5 s on the runner), so pass/fail followed the runner's speed, not
ReDoS (run #16 passed narrowly). The threshold was raised to 60 seconds; an unbounded regex (`*`) grows exponentially (x16
per +4 repetitions) so it is still caught (simulated: it fails exactly at the 60th second). No change
to the production regex.
**Update 2026-10-10**: Deploy has run three times and all three ended `cancelled`: #8 (2026-10-07, after PR #11), #9 and
#10 (2026-10-08, after PRs #12 and #13), each after 10-23 minutes; the Actions list shows no Deploy run after 2026-10-08
and none has passed. The cause is still unknown (the logs are not readable from the development session), so
"Done when" is not met. Check on the prod host what the interrupted runs left behind (`docker compose ps`, `:prev` tags,
`alembic current`: whether `migrate` got to run).
**Finding NOT yet worked on**: that ~0.45 ms per character cost is itself real in production -- `extract_iocs()`
on one ~12KB article takes ~5 seconds of synchronous CPU in the enrichment stage. Not ReDoS and not part of #13; if
it is to be optimised, the spot is `_RE_DOMAIN_DEFANGED` (e.g. a pre-filter before running the regex), with the
`tests/unit/test_ioc_extractor.py` corpus as a byte-identical safety net.

## 14. Logo missing from the CVE Tracker Excel export

**Asked (proposal)**: the file produced by `GET /api/cve/export` carries the logo at the top left like the template.
**Current state**: the template `apps/api/src/cti_api/templates/CVE_Tracker_template.xlsx` contains the logo
(`xl/media/image1.png`), but the export does not: openpyxl drops images when Pillow is not installed,
and `pillow` is not in `uv.lock` (so not in the API image either). Reproduction: loading and then saving
the original template with openpyxl in the project venv produces a zip without `xl/media/*`. It was already like this before
the 2026-10-06 export column change.
**Touch points**: `apps/api/pyproject.toml` (+ `uv.lock`), `services/cve_export.py`,
`tests/integration/test_cve_export_service.py`.
**Needed**: nothing.
**Done when**: `pillow` is a `cti-api` dependency, the API image still passes the CI smoke, and one test
ensures the exported workbook contains 1 image.
**Status 2026-10-07**: `pillow>=10.0` added (`uv.lock`: pillow 12.3.0, manylinux wheels only),
`test_export_keeps_template_logo` added (fails without pillow, passes with it). Not yet
proven: the CI `docker` job building the API image. `uv sync --frozen --no-dev --no-editable --package cti-api`
(the builder stage step) was checked separately and installs pillow, but a full `docker build` has not run
because the `ghcr.io` registry is unreachable from the development session.
**Merged 2026-10-07 (PR #9); the `docker (api ...)` CI job that builds the image with pillow was green in the CI run of
PR #12 (2026-10-08).** Item closed.

## 15. Use `published_at` in the UI/API/dashboard + align the date formats

**Asked (proposal)**: MITRE's publish time (`cve_tracker.published_at`, added 2026-10-06 for the export)
is used elsewhere too, and the export date formats are uniform.
**Current state**: `CveOut` (`schemas/cve.py`) does not expose `published_at` yet; the Ticket tab
(`cve-ticket-tab.tsx`, `reportedDateVal = fmtDt(cve.published)`) shows "CVE Reported Date" without a
time; the dashboard MTTD is computed in **days** (`detected_on` - `published`) because `published` has no time
(`services/cve_dashboard.py`). In the export, the "Date Acknowledged by CTI Team" column is still
`YYYY-MM-DD HH:MM:SS`, unlike the two columns next to it (`HH:MM DD-MM-YYYY`).
**Touch points**: `schemas/cve.py`, `routers/cve.py` (`_serialize`), `cve-ticket-tab.tsx`,
`services/cve_dashboard.py`, `cve-dashboard-view.tsx` (the MTTD definition text), `services/cve_export.py`.
**Needed**: `tools/ops/backfill_cve_published_at.py --apply` has been run in production
(without it old CVEs have no time); a decision on whether the Acknowledged column follows `HH:MM DD-MM-YYYY`.
**Done when**: the Ticket tab shows the publish time, MTTD is shown in hours for CVEs that have
`published_at` (and falls back to days for those that do not, with a separate `n` so the coverage is visible),
the API contract is regenerated (`export_openapi` + `gen:api`), and the export column formats are consistent.

## 16. CVE dashboard: SLA per severity

**Asked (proposal)**: dashboard ratings based on SLA targets per severity, not fixed thresholds.
**Current state**: the rating (Excellent/Good/Fair/Needs improvement) uses the thresholds from the old Excel sheet
for the average MTTA (<=1 / <=7 / <=14 days), the same for every severity
(`apps/web/src/lib/cve/dashboard.ts::ratingForMtta`): a CRITICAL with an MTTA of 10 days and a LOW with 10 days
are rated the same ("Fair"). The average is also easily pulled by outliers; the median and p90 are already computed but not
used for the rating.
**Touch points**: `dashboard.ts`, `cve-dashboard-view.tsx`, `services/cve_dashboard.py` (compute violations
on the server, not in the browser).
**Needed**: targets per severity for acknowledge and remediation (calendar days or working days,
per client or global), and the metric to rate (mean, median, or the percentage of CVEs within SLA).
**Done when**: the dashboard shows the number/percentage of CVEs violating the SLA per severity and a list of CVEs
currently over the limit, with the targets stored as configuration (not constants in code).

## 17. CVE dashboard: additional panels

**Asked (proposal)**: panels that were not in the old Excel but whose data already exists in the platform.
**Current state** (numbers from the 2026 Excel workbook, 811 CVEs, not from the platform DB): 511 CVEs were already
acknowledged but their remediation status is empty and 147 are not acknowledged (a backlog that today is only
visible as the "Awaiting status" and "Unacknowledged" buckets); the most frequent products are n8n 62,
Splunk Enterprise 60, wazuh 43, suricata 42. The platform stores `cisa_kev`, `epss_score`, and
`active_exploitation` per CVE (`db/models/cve.py`), which are not used on the dashboard yet.
**Proposed panels**: (a) backlog aging (CVEs without a status for > N days, grouped by severity); (b) CVEs
with high KEV/EPSS that are not yet remediated; (c) the most frequently affected products/techs.
**Touch points**: `services/cve_dashboard.py` (`DashRow` needs extra columns),
`repositories/cve.py::list_dashboard_rows`, `cve-dashboard-view.tsx`.
**Needed**: a choice of useful panels and a "too long" threshold for aging.
**Done when**: each panel has a test in `tests/unit/test_cve_dashboard.py` and one integration test that
locks the client/techstack scope like the existing panels.

## 18. CVE ticket field validation + the ticket model

**Asked (proposal)**: ticket values are restricted to a standard list, and a decision on whether one ticket may
cover many CVEs.
**Current state**: `remediation_status`, `risk_acceptance`, and `active_exploitation` are "soft
enums" without a CHECK or API validation (`CveTicketBody` is all `str`); the UI dropdown uses
Open/In Progress/Resolved/Risk Accepted/Closed. The dashboard absorbs the Excel legend vocabulary through
`_STATUS_ALIASES` (`services/cve_dashboard.py`) so legacy values do not silently land in the wrong bucket. In the
Excel workbook the root cause is visible: the status dropdown only covers some rows (its list contains
"Not Applicable" twice and no "Completed"), there are 4 rows with the status "Closed" outside the legend, and 657 of
811 statuses are empty. Model: Excel uses 600 tickets for 811 CVEs (up to 32 CVEs in one ticket, e.g. one
Splunk patch), the platform has one `CveTicket` per `(cve_id, client_id)` (the `CveTicket` docstring).
**Touch points**: `schemas/cve.py::CveTicketBody`, `routers/cve.py` (`PUT /{cve_id}/ticket`),
`cve-ticket-tab.tsx`, `cve-ticketing-view.tsx`, `db/models/cve.py::CveTicket`.
**Needed**: the list of standard values (including whether "Not Applicable" and "Completed" are in), and the
model decision: keep 1 ticket per CVE, or allow a ticket to cover many CVEs (a schema change +
export + dashboard).
**Done when**: `PUT /ticket` rejects values outside the list with 422 (old values migrated or
mapped), the UI and the dashboard use one shared list, and the ticket model decision is written in the
`CveTicket` docstring.

## 19. Tech catalog from the CVE mirror + Monitor

> **The direction changed on 2026-10-07 (a discussion with the user).** The old plan (an `aliases` column + a
> hand-curated catalog + CPE queries) is not continued as the main path: manual per-tech aliases do not scale, and the
> root problem (free names matched as text) remains. The design below replaces phases 2 and 3 in
> `docs/CVE_TECH_MATCHING.md` 7.1. **The code already exists** (slices 1-7, see "Phases" and "Technical design"
> below); "Current state" records the state BEFORE the catalog.

**Asked (2026-10-07)**: the Tech column in the CVE Tracker must not mismatch any more, and the techstack list
stops being "type the name by hand". Background, root cause, and the 0.2.1 solution:
`docs/CVE_TECH_MATCHING.md`.

**Current state** (the full CVE Tracker flow: `docs/CVE_TRACKER_FLOW.md`; facts from the repo/production, not
guesses): `techstack_entries.name` is free text, the UI input
"Tech name..." has no validation, and that name is also the **join key** to `cve_tracker.tech` (`get_risk_context`).
Seven matchers with different rules use it (NVD `keywordSearch`; Tenable; the `new_cve` gate;
`score.py` `related_tech_status`; `score.py` `check_tech_stack`; `cve_priority.in_tech_stack`; the Top CVE report's
`applicable_to_stack`). In production, 55
of the 118 verifiable tracker rows were wrong. `new_cve` searches per tech name every hour (34 requests to
NVD, searching words in the description), an 8-day window, and one MITRE call per candidate (limit 60/minute).
**What exists (merged to `main` in PR #12, 2026-10-08)**: `cti_core.tech_match` (one
definition of "matches": whole word, attached version digits accepted, attached letters rejected, terms < 2 characters never
match) used by matchers 2-6 and by the `reconcile_cve_tech` assessor. **The `techstack_entries.aliases` column,
the migration, the seed, and the `techstack_aliases` reference data are dropped (user decision 2026-10-07)**; there is no new
migration. The visible effect in production once deployed: `tech_stack` alerts and the `in_tech_stack` flag no longer
match by substring (`go` ~ `google`).

### Design (agreed 2026-10-07)

**Flow**: pull every CVE (2025 to now) into our own DB -> from that data comes a **tech catalog**
(vendor + product) -> the techstack menu has two tabs, **All Tech** (the catalog; search and click **Monitor**) and
**Monitored Tech** (per client) -> new CVEs are matched through **the product identity from the CVE data**, not
through name text -> the **CVEs** tab only shows CVEs for monitored techs.

**Data layers (different lifetimes, this is the core of the design)**

| Layer | Contents | Life cycle |
|---|---|---|
| CVE mirror (new) | every CVE: id, publish/modify dates, summary, CVSS, affected products (text, like the Affected column today) | **dropped by retention** |
| Tech catalog (new) | normalised vendor + product, display name, `first_seen`, `last_cve_at`, CVE count | **permanent**; monitored rows are never deleted |
| Monitored tech (`techstack_entries`) | per client; points into the catalog (a nullable column for "custom"); `exposure`, `hosting_type`, an active flag | permanent |
| `cve_tracker` (already exists) | CVEs per client for monitored techs, plus tickets/ACKs | **permanent**, no FK cascade to the mirror |

- **CVEs matching a monitored tech are promoted into `cve_tracker` at ingest** (copied, not
  joined at query time), so tickets, the Excel export, and the CVE dashboard are not affected by retention.
- **The catalog is not a transient derivative of the mirror**: otherwise a product whose CVEs only exist in 2025 would disappear from
  the catalog in 2027 while still being monitored.
- `name` stays the display label and the join key (`cve_tracker.tech`), so tickets and history do not break.

**Retention**: calendar year. Keep the current year and the previous one; from 1 January of year N, every CVE
published in N-2 is dropped (in 2026 the mirror holds 2025 and 2026; in 2027 the 2025 CVEs are dropped). A daily job on the
`maintenance` queue, logging the number dropped, and not touching `cve_tracker`.

**Tabs and behaviour**
- **All Tech**: a global catalog, search first (autocomplete; not a list to scroll), a Monitor action.
  Products not yet in the catalog may be added as **custom**, flagged as unverified.
- **Monitored Tech**: per client. Monitored techs are **always** enriched as today
  (score/risk exposure+hosting, KEV, EPSS, ticket); no new enrichment in the first version.
- **Not monitored = hidden** (an active flag; the dashboard already has an "active techstack" scope). Tickets
  are never lost.
- **CVEs**: only CVEs for monitored techs. **CVE DB** (a new, read-only tab): browses every CVE in the
  mirror (limited to the retention depth), and from one CVE you can click its affected product and Monitor it. Needs
  indexes (date, severity, product).
- **Notifications: already built separately from #19 (2026-10-07, branch `nameless/roadmap-runners`).** User
  decision: Telegram only, every new CVE for monitored techs, one summary per run (per client),
  built now in the existing sink. Its original premise (that per-new-CVE alerts already existed) turned out to be wrong; before
  this there were only article alerts, the Top CVE report, PoC alerts, and the manual email draft. Its call point (a new
  `cve_tracker` row was created) stays the same when the pipeline is replaced by mirror -> promotion. Details: `docs/CVE_TRACKER_FLOW.md`
  7. Remaining: the old reports/alerts (articles, Top CVE) still use the techstack names combined across all clients.

**Impact on other items**: #3 ("Populate now") **goes away** -- a newly monitored tech is filled immediately from the
mirror (as deep as retention; history before 2025 is already in the tracker from the Mongo migration), so the 8-day window,
the 180-day backfill, and MITRE pacing are no longer relevant. #7 gets a basis for version-based relevance if version
ranges are stored. `new_cve` changes from "search per name" to "fetch every new/changed CVE once an hour,
project onto the monitored techs".

**There are actually seven tech name matchers, not six** (`reports/cve_record.py::applicable_to_stack` was not
recorded before and is not touched by phase 1; see `docs/CVE_TRACKER_FLOW.md` 9).

**A text matcher is still needed** for articles and tweets (they have no CPE): `cti_core.tech_match` (on the
branch) is kept; its terms will eventually be derived from the catalog.

**The full technical design (tables, resolver, ingest, matching, retention, API/UI, migration, PR slices)**:
`docs/CVE_CATALOG_DESIGN.md`. **Slice 1 (the pure resolver `cti_core.catalog_resolve` + 58 tests), slice 2
(schema + models + catalog/mirror/target repositories, revision `b7e3d9a1c5f2`, 21 Postgres tests), slice 3
(`cve.mirror_sync` ingest + retention + backfill script, flag `CVE_MIRROR__ENABLED` off by default), slice 4
(mirror -> `cve_tracker` promotion with shadow mode, flag `CVE_MIRROR__PROMOTE` default `off`), slice 5
(catalog / CVE DB / Monitor API + contract, inactive entry scope), slice 6 (UI: Monitored Tech, All Tech,
CVE DB, mapping entries through "Map to catalog"), and slice 7 (the cutover switch: `new_cve` suspended when
`CVE_MIRROR__PROMOTE=live`, export/import of mappings across environments, `--since` for live history, runbook) are done
and merged (PR #12, release 0.3.0). **All the #19 code exists; what remains is operational, done by the user**: mapping the 34 entries on dev,
shadow mode, then the dev and prod cutovers. The exact steps: `docs/CVE_CATALOG_CUTOVER.md`.** Decision 2026-10-07: the picker
hides 1-CVE families (search still shows everything).

### Phases

1. **Measurement spike** -- **run on the full data 2026-10-07 (117,220 CVEs); results and implications in `docs/CVE_TECH_MATCHING.md` 7.1.3, reports in `docs/spikes/`; needs re-running with the fixed script and `--since` = the date `new_cve` started running**: `tools/ops/spike_cve_catalog.py` (stdlib only; usage in the docstring and `docs/CVE_TECH_MATCHING.md` 7.1.2). Read-only, does not change the product: pull CVEs from 2025 to now, count the unique
   (vendor, product) pairs, the percentage of junk (`n/a`, repo names, version strings), spelling duplicates, and how many of the
   34 production techs come out clean. It doubles as the recall number (`docs/CVE_TECH_MATCHING.md` 7.2.1).
   The result decides how heavy catalog normalisation is -- the biggest risk of this design.
2. **Mirror + catalog (read-only)**: schema, ingest, automatic normalisation, the retention job, the CVE DB tab.
3. **Monitor**: the All Tech / Monitored Tech tabs, `techstack_entries` pointing into the catalog, API validation,
   regenerating `docs/openapi.json` and `schema.d.ts`. Mapping the 34 old techs to the catalog is **reviewed by hand**.
4. **Replace `new_cve`**: mirror -> tracker projection. **Shadow mode first** (running alongside the
   old `new_cve` for a few days, comparing CVEs found by only one side), then switched over.
5. **Product merging by admins** (merging product A into B in the catalog): later, once it is clear how
   messy the automatic normalisation is.

Everything is tested on the **dev server first**, then production.

### Open (needs user confirmation)
- **Status 2026-10-10**: code done and merged (PR #12, release 0.3.0); what remains is manual mapping, shadow mode,
  and cutover (runbook). The worker log posted on 2026-10-08 shows the mirror ingest running (`cve_mirror_synced` is
  `ok`/`noop`, `failed=0`, no gap) with `CVE_MIRROR__PROMOTE=off`. **Before `live`**, clean the stored `affected` text (0.4.1 upgrade step 2,
  `tools/ops/fix_affected_double_operator.sql`): promotion copies `affected_lines` as they are. Items below not marked
  DECIDED are still open.
- **Data source**: CVE List V5 as the primary; the spike supports it (ADP rescues only 0.1% of CVEs and CPE
  is only present in 7.5% of CNA data, so NVD/CPE cannot be the identity source; NVD is still useful as a
  supplement for CVSS/KEV). Waiting for user confirmation.
- **The monitored unit: DECIDED (user 2026-10-07): two levels, vendor and product family.** 9 of the 34
  production techs are of the "one vendor, many products" type (fortinet 311 CVEs, splunk 182, juniper 168, palo alto
  150, ...). One Monitor entry may have many targets (see `docs/CVE_CATALOG_DESIGN.md` 3.4).
- **Re-running the spike: half done.** Re-run with the fixed script (the identity and
  coverage numbers are now correct, the v2 report). **Recall is not separated yet**: `--since 2025-01-01` and `tracker.csv` (73
  rows; production had 125 at `reconcile` time) are the same as before. It needs `--since` = the date `new_cve` started
  running and `tracker.csv` from the same DB; confirm which DB / was it already cleaned up?
- **The date for retention and the mirror window**: proposed publish date. The consequence: old CVEs that change
  recently (e.g. added to KEV in 2026 although published in 2023) do not enter the mirror -- the same limitation as
  today's 8-day window; it could be closed by specifically fetching old CVEs that changed and hit a monitored tech.
- **Affected versions: user decision 2026-10-07 = follow what exists.** No new structured version-range
  storage; the Affected column stays text (`cve_affected.affected`) and tickets keep the
  analyst-filled `affected_version`/`fixed_version`. Version-based relevance (#7) is not done in #19
  (the structured-range proposal is cancelled, not deferred).
- **The seventh matcher: DECIDED (user 2026-10-08) = an exception.** `applicable_to_stack` (the Top CVE report) is deliberately
  NOT unified into `cti_core.tech_match`: `test_cve_record.py` locks `c++` ~ `c++ inc` (substring), and that report
  does not follow the catalog path. Its test stays, its behaviour is not changed.
- **Mapping `grafana`: DECIDED (user 2026-10-08) = vendor level** (the Grafana vendor: catches Grafana OSS/
  Enterprise, `mcp-k6`, k6, etc.; the risk is bringing in unused Grafana products).

**Touch points (estimated)**: models + a new Alembic migration (mirror, catalog, `techstack_entries.catalog_id`;
checked by `test_migrations_match_models`), ingest and retention jobs in `apps/worker` (the `maintenance` queue),
`feeds/new_cve.py`, `routers/techstack.py` + `schemas/techstack.py` (+ openapi/`schema.d.ts`),
`apps/web/src/components/cve/techstack-panel.tsx` + the CVE DB tab, `routers/cve.py`, `services/cve_priority.py`,
`cti_enrich/stages/score.py`, `cti_scraper/reference_data.py`, `tools/ops/reconcile_cve_tech.py`.

**Done when**: the spike is reported with numbers; pressing Monitor on a catalog product fills its history from the
mirror without touching other techs; the CVEs tab only contains monitored techs; on the dev server, the shadow mode
vs old `new_cve` results are documented (CVEs found by only one side, with an explanation); the
`reconcile_cve_tech` tool on production data no longer produces name-caused `DELETE`s; retention is
proven to delete year N-2 without touching `cve_tracker`; before/after recall numbers are recorded.

---

## 20. Known follow-ups from releases 0.4.0 / 0.4.1

Collected from the "Known / not yet done" parts of `CHANGELOG.md` (0.4.0 and 0.4.1) so they are not lost; the changelog
has the detail and the evidence. (D) = needs a product decision before anyone starts. Nothing here was asked
formally; order = a suggestion.

**Decisions first**
- (D) Exec dashboard: the "Critical CVEs" / "KEV CVEs" cards and the CVE exposure table count the tracker of **all clients**
  (no `client_id` filter) and the table lists only the top 10 techs. Should the numbers be per client? (PR #29 made the card
  totals complete but kept this scope.)
- (D) The lower bound of a `lessThan` range is not written in the `affected` text (`version: "3.3.0", lessThan: "3.5.4"`
  reads as `< 3.5.4`). Adding it changes almost every stored `affected` text (193 of 333 on dev), so it is its own decision.
- (D) "Severity" has three versions in the UI (raw, "effective" which goes up one level with a PoC, and
  `adjusted_risk_score`); `cisa_kev_detail` (including `due_date`) is stored but never shown.

**Security / access**
- KEV, EPSS and Exploit-DB lookups are open to every analyst (`require_auth`); the bulk Exploit-DB lookup is heavy and any
  analyst can trigger it.

**Data correctness**
- `cisa_kev` / `active_exploitation` are never reset to `false` when CISA removes an entry from the KEV catalog.
- Status "Resolved" without `actual_remediation_date` is not counted in MTTR (visible in the `n` on the dashboard);
  field validation for tickets is #18.
- Tickets orphaned by an old `purge-orphaned` are not cleaned automatically (check: a ticket without a tracker row).
- `recap` and `crossref` return one row per client, so a CVE tracked by two clients appears twice.
- `cve_newsletter_mentions` is written to only one tracker row (any client) and nothing reads it yet.
- No code writes `cve_threat_actors` and `cve_ttps`, so the TA/TTP branch of `crossref` has no data.
- The dashboard tables "Mean time metrics by severity" and "Monthly CVE volume by severity" do not show unrated CVEs yet
  (the API does not send that bucket).

**Coverage**
- `trending_cve` only searches `CVE-<current year>-`; last year's CVEs that are trending are missed (adding them costs more
  X API tweets and the query syntax must be validated against the real API).

**Done when**: each point is either fixed (with a test) or dropped with a one-line reason here.


---

## 21. Improve the Recap feature (PRIORITY)

> **Priority item, requested by the team on 2026-10-10. Scope decided with the user the same day. Nothing is built
> yet.** This section records the current state, what was decided, the design of each part, and what is still open.

**Asked (team feedback 2026-10-10)**: (1) make the recap weekly; (2) optimise the LLM call(s); (3) "any more suggestions?"

**Decided (user, 2026-10-10)**
- The recap becomes **weekly and scheduled**. There is **no scheduled daily recap any more**, but the **manual trigger
  for a single day stays** (`POST /api/recap/generate?date=`, and the UI button).
- **No delivery channel**: the recap stays on the web page only (no Telegram, no email).
- From the additions proposed, **approved**: week-over-week comparison, grounding check of the LLM output against the
  input, forecast accuracy scorecard. **Not selected** (left out of this item, can be revived later): sending the recap
  to Telegram/email, a "what hit our stack" section for monitored techs, retry + alert when the run fails.

**Current state** (read from the code on 2026-10-10)
- One recap per **day**: beat task `recap.generate_daily` runs at 06:00 **UTC** (`beat.py`, `app.conf.timezone = "UTC"`);
  `generate_daily_recap()` (`apps/api/src/cti_api/services/recap.py`) summarises **yesterday** plus a 1-3 day forecast.
  Stored in `daily_recaps` (`date` is a unique `YYYY-MM-DD` string key; JSONB `yesterday`, `forecast`, `counts`,
  `token_usage`). Any logged-in user can regenerate with `POST /api/recap/generate?date=&force=`.
- **One LLM call per recap** (`temperature=0`, free-form JSON parsed with `parse_json_response`). The prompt holds up to
  60 articles, 50 tweets, 30 CVEs, an IOC count line, the new threat actors and 8 campaign clusters (collected from up to
  200 / 150 / 50 / 200 rows first, then cut). The article list is sorted by a source-name heuristic, not by importance.
- **Nothing measures the cost**: `token_usage` is always stored as `{}` (the completion's `usage` is never read), and
  `LlmSettings.rate_limit` ("global spend throttle, Redis token bucket") is declared in `config.py` but has no consumer.
  The client retries twice (`max_retries=2`, 60 s timeout), then the task fails; a reply that is not JSON is stored as
  an empty recap with the text in `raw_llm`.
- The CVE list is **global**: `_collect_cves` -> `list_registered_on` returns tracker rows of every client, capped at 50
  by `limit(50)` **without an ORDER BY**, so on a busy day which 50 reach the prompt is arbitrary.
- Output is **English** and the web page is the only consumer (`/recap`, `GET /api/recap/latest|list|{date}`).

**Design: weekly**
- Storage: `daily_recaps` is keyed by one day, so add `kind` (`weekly` | `daily`) and `period_start`/`period_end`
  (hand-written migration, `test_migrations_match_models` updated). Weekly rows are the scheduled ones; `daily` rows
  exist only when someone triggers a day by hand. History/list/latest endpoints and the UI show the kind and the range.
- **Week boundary (proposal, to confirm): Friday to Thursday, generated Friday 00:15 WIB.** The newsletter (#22) is
  built on Fridays, so two consecutive weekly recaps cover exactly the newsletter's 14-day window and are ready before
  it runs. The alternative is Monday to Sunday generated Monday morning; then the newest recap is already 4+ days old
  when the Friday newsletter is built. The beat entry must use WIB (`crontab` is UTC today: Friday 00:15 WIB is
  Thursday 17:15 UTC).
- A week is about 7x the volume of a day, so the weekly prompt is built from **aggregates**, not from a wider date range:
  top N per category ranked by signal (confidence/score, confirmed incident, KEV/PoC, source reliability, cluster size),
  per-category counts, clusters collapsed to one line each. Forecast horizon becomes 1-2 weeks.
- **Language**: the newsletter (#22) is going Indonesian and reuses this content for its executive summary, so generate the
  weekly recap **in Indonesian directly** (a prompt change, no extra call), keeping the JSON keys English. This changes the
  language of the Recap page; if the team wants it to stay English, the newsletter would need a translation call.

**Design: LLM optimisation**
1. **Measure first**: store `completion.usage` (prompt/completion tokens) and the wall time in `token_usage` for every
   recap and log them. Record the baseline before changing anything, so the saving is a number written in this item.
2. **Shrink the input** with the ranking and caps above; collapse duplicate stories by cluster; drop low-signal tweets.
3. **Skip the call when there is nothing to say** (no articles, tweets or CVEs in the window): store the deterministic
   "no notable activity" result the prompt already asks the model to produce.
4. **Never pay twice**: keep the cache per period; `force=true` stays an explicit admin choice.
5. After the baseline, evaluate: a smaller model for the recap (it summarises given text, it does not classify), JSON mode
   / `response_format` to stop non-JSON replies, and provider prompt caching for the static system prompt. Either wire
   `LlmSettings.rate_limit` or delete the dead setting.

**Design: approved additions**
- **Week-over-week comparison**: compare `counts` with the previous weekly recap (articles, tweets, IOCs, CVEs, campaigns,
  new threat actors) as absolute and percentage deltas, plus "new this week" for threat actors, campaigns and CVEs that
  are in this week's output and not in the previous one. Computed in code, **no LLM**, stored in a `comparison` field;
  omitted when there is no previous weekly recap.
- **Grounding check**: after parsing the reply, verify against the prompt input (a) every CVE id in `notable_cves` and in
  free text, (b) every name in `active_threat_actors` / `new_threat_actors_added`, (c) every campaign `theme`, and (d)
  that each `top_stories` title matches an input article (then attach its article id and URL; the page links to it). Items
  that fail are **removed from what is shown and recorded** in a `grounding` field (what was dropped and why), never
  dropped silently. Tests include a reply that invents a CVE and an actor.
- **Forecast scorecard**: store each `likely_events` item with an id and its confidence (`low|med|high`). When the next
  weekly recap is generated, **the same call** also reviews the previous forecast items against the new input (verdict
  `happened | partly | not_happened | unclear` with the evidence it used), so there is no extra LLM call and only a few
  hundred extra input tokens. The analyst can override a verdict on the page. The Recap page shows the hit rate of the
  last 8 weeks, split by stated confidence (does "high" actually come true more often than "low"?).

**Touch points**: `services/recap.py` (collect, aggregate, prompt, grounding, comparison, scorecard), `routers/recap.py`,
`tasks/periodic.py`, `beat.py` (WIB schedule, remove the daily entry), `db/models/recap.py` + migration,
`repositories/recap.py`, `schemas` + `openapi.json` + `schema.d.ts`, `apps/web/src/components/recap/*`
(range/kind, deltas, scorecard, article links), `tests/` (unit for grounding/comparison/window, integration for the
repository and the router snapshot).
**Needed from the user**: (1) confirm the week boundary and time (proposal: Friday-Thursday, Friday 00:15 WIB); (2)
confirm the recap becomes Indonesian (changes the Recap page language).
**Done when**: a weekly recap is generated on schedule and shown with its date range; a day can still be generated by
hand; every run records its token usage; the measured input size/tokens per recap is lower than the recorded baseline
(numbers written here); a run with no activity makes no LLM call; the page shows the week-over-week deltas, the
dropped-item count from the grounding check and the forecast scorecard; tests cover the weekly window, aggregation,
comparison, grounding and the no-activity path.

---

## 22. Newsletter: biweekly, Indonesian, redesign, recommended articles (PRIORITY)

> **Priority item, requested by the team on 2026-10-10. Scope decided with the user the same day. Nothing is built
> yet** (the template is only drawn: `docs/mockups/newsletter-redesign.html`). Depends on #21 for the executive summary
> and for LLM usage logging.

**Asked (team feedback 2026-10-10)**: (1) biweekly; (2) translate the content to Indonesian; (3) redesign the template;
(4) add recommendations for the newsletter content; (5) "any more suggestions?"

**Decided (user, 2026-10-10)**
- **Biweekly, every other Friday, 13:00 WIB** ("jam 1" = 13:00, confirmed). 13:00 WIB is read as the **time the edition
  is due out**; the suggested draft is prepared before it so the analyst can review in time (see Design: biweekly).
- **Edition label "Bulan X minggu N"** (for example "Oktober, minggu 4") instead of "Week N" or a running edition
  number. **N = the ordinal of the publishing Friday inside its month** (1-5); the date range of the window stays next
  to it, so the label is never ambiguous.
- **Mockup approved** (2026-10-10), with the edition label changed to the one above.
- **Reviewer = the analysts**, inside the existing flow. Today: (1) the team picks articles by hand in the Newsroom,
  (2) maps them to the categories, (3) previews or sends the draft email. Wanted: (1) the composer already holds the
  **recommended content, already mapped to the categories**; the team **reviews it** before clicking preview or send
  draft; (2) the team can **still pick content from the Newsroom** and add it, swap it or remove it. No separate
  language reviewer and no approval step: the analyst's review of the draft is the quality check.
- **"Recommendations" = recommended articles to include** (not an actions section inside the email).
- Design: the user asked for the redesign to be **drawn first**; the colours follow the brand palette already in use
  (`#430a23` burgundy, `#d0002f` red, `#f2e8dd` / `#fbf6f1` / `#e8dacb` beige, `#fbbfa1` peach accent).
- From the additions proposed, **approved**: reuse the weekly recap for the executive summary; cache the per-article
  summary and make one send leave exactly one history row. **Not selected** (left out): a draft/approved/sent status flow,
  a "CVEs to act on" block, per-client editions, delivery beyond the Graph draft (distribution list, archive, PDF), the
  analyst-feedback loop for the ranking, and recommended actions inside the email.

**Current state** (read from the code on 2026-10-10)
- The newsletter is **composed by hand**, there is no schedule. An analyst queues articles from the Newsroom
  ("+ Newsletter", kept in browser `localStorage`), assigns them to **Highlight** (1) and the sections **APAC**,
  **Global**, **Indonesia** (max 5 each, enforced by `routers/newsletter.py`), optionally adds an intro, footer, custom
  CSS, per-article analyst notes and campaign clusters (7 days by default), previews it and creates an **Outlook draft
  through Microsoft Graph** (`create_graph_draft`; nobody is emailed automatically). Subject: `[CTI Newsletter] Threat
  Intelligence Digest — Week N, YYYY`; the number is the ISO week of the generation time.
- Per article (up to 16), `build_newsletter_context()` runs **sequentially**: a Playwright fetch of the body, one LLM call
  for `key_points` + `summary` (English prompt written for a "weekly newsletter"; from the body, or from metadata when the
  page is paywalled), IOC extraction and CVE-mention detection. `articles` has no summary column, so nothing is reused.
- **`preview` and `draft-email` both rebuild everything** (fetch + LLM + IOC extraction again) and **both save a new
  `newsletters` row**, so one send can leave two or more history rows. The rebuild also **writes IOCs and CVE mentions
  into the database** as a side effect of what looks like a preview.
- Template: `apps/api/src/cti_api/templates/newsletter_email.html` (233 lines) extends `_base_email.html`; headings,
  labels and the title are hardcoded English. It uses `display:flex`, which Outlook desktop (the Word rendering engine)
  does not support, and its rendering in real email clients was never checked (#2, "email client verification not yet").
- The saved row has `week`/`year` (small integers), `generated_at` (string), the rendered `html` and a `sections` JSON;
  there is no period range and no edition number.

**Design: biweekly**
- A beat task runs every second Friday and **prepares the suggested content**: the recommended articles (below) already
  placed in Highlight / APAC / Global / Indonesia, plus the executive summary from the recaps. The weekly recap is
  generated Friday 00:15 WIB (#21), so the task runs after it: **assumed Friday 09:00 WIB (02:00 UTC)**, which leaves
  about four hours of review before the 13:00 WIB target (06:00 UTC). The analyst opens the Newsletter page, reviews and
  edits, and previews or creates the Outlook draft as today. No Telegram notice and no automatic sending.
- The suggestion is stored **server-side** (a `newsletter_suggestions` row per window: period, the placed article ids with
  their section and reasons), because the composer queue today lives only in the browser's `localStorage`. When the
  composer opens and its queue is empty it loads the suggestion; when the analyst already has a queue it shows a banner
  ("rekomendasi tersedia") with "pakai rekomendasi" / "gabungkan" instead of overwriting their work. Articles added from
  the Newsroom ("+ Newsletter") keep working as now. There is no draft/approved/sent status (not selected).
- Window = the last 14 days (Friday to Thursday), the same range as the two latest weekly recaps (#21);
  `cluster_days` becomes 14. "Every second Friday" is counted from a **first edition date** written in the config, not
  from ISO-week parity, so it survives a year change. Section caps (5) are probably too small for two weeks: decide with
  the first real edition.
- Replace "Week N" by the **"Bulan X minggu N" label and a date range** ("Oktober, minggu 4, 9-22 Okt 2026"): add
  `period_start`, `period_end` to `newsletters` (migration); the label is derived from the publishing date, so no edition
  counter is stored. Old rows keep `week`/`year`. The subject becomes `[CTI Newsletter] Buletin Intelijen Ancaman: Oktober,
  minggu 4`.

**Design: Indonesian content**
- Generate `key_points` and `summary` **in Indonesian in the same LLM call** as today (prompt change; no second
  translation call, no extra cost per article). Keep CVE ids, product names, threat actor names, ATT&CK technique names
  and IOCs untranslated; give the prompt a short glossary of recurring terms so wording stays consistent between
  editions. Translate the template labels, section headings, subject and footer. A `language` field (default `id`, `en`
  still possible) goes on the build request so the English edition is not lost.
- Article **titles** keep their original wording by default (links, searching); a translated line under the title is
  possible later. The analyst's own intro and notes are used as typed. Quality check: the analyst who reviews the suggested draft also
  reads the Indonesian wording; corrections go into the glossary so later editions improve.

**Design: template redesign**
- Drawn in `docs/mockups/newsletter-redesign.html` (sample data, Indonesian, brand palette). It is built the way the real
  template must be built: a `table` layout with inline styles, a 640 px container, a fallback font stack, solid colours
  instead of the CSS gradient, a hidden preheader line, and a stacked layout under 480 px, so it can become
  `newsletter_email.html` without a second redesign.
- Structure: header with edition and date range; **executive summary** and **period in numbers** (with the
  week-over-week deltas from #21), both taken from the weekly recaps; the highlight; the APAC / Global / Indonesia
  sections; campaign clusters; footer. The colour coding per section is kept (APAC blue, Global purple, Indonesia red).
- Acceptance includes screenshots from Outlook desktop, Outlook web and Gmail attached to this item.

**Design: recommended articles (request 4)**
- When the composer opens, and when the biweekly draft is built, rank the candidate articles of the window with signals
  already stored: `confidence_score`, `confirmed_incident`, KEV/PoC on the CVEs they mention, a hit on a **monitored
  tech** (#19) or on a customer industry/country, source reliability, cluster size, APAC / Indonesia relevance, with
  duplicate stories collapsed. Suggest a Highlight and up to N per section, show **why** each was suggested (the signals),
  and let the analyst accept, swap or remove. The suggestion never sends anything by itself.

**Design: approved additions**
- **Executive summary from the weekly recap**: the summary block and the "period in numbers" are read from the weekly
  recaps inside the window (headline, summary, counts with deltas); no separate LLM call. If a recap is missing for the
  window the block is left out, not generated on the spot.
- **Summary cache and one row per send**: cache each article's `key_points` / `summary` (a table keyed by article id and
  language, or persisted at enrichment time) so `preview` and `draft-email` never redo Playwright + LLM; `preview` does
  not save a row and does not write IOCs/CVE mentions; the single save happens when the Outlook draft is created, and a
  second preview of the same articles makes no new LLM or Playwright calls.

**Touch points**: `services/newsletter.py`, `routers/newsletter.py`, `schemas/newsletter.py`,
`templates/newsletter_email.html` (+ `_base_email.html`), `db/models/newsletter.py` + migration (and a summary cache
table), `repositories/newsletter.py`, `beat.py` + a new task, a new ranking service, `apps/web/src/components/newsletter/*`
(suggestions, edition/range), `openapi.json` + `schema.d.ts`, `.env.example` + `.env.prod.template` for the first edition
date, and a `newsletter_suggestions` table.
**Needed from the user**: (1) the **first edition date** (assumed Friday 23 Oct 2026, as in the mockup; the second Friday
after it is the next); (2) confirm the suggested content is prepared **Friday 09:00 WIB** and 13:00 WIB is the due time, not
the preparation time.
**Done when**: suggested content is prepared on the biweekly schedule, already placed in the sections, and the composer
loads it for review while the Newsroom picking flow still works; every edition carries the "Bulan X minggu N" label and a date range; summaries and
labels are in Indonesian (English still selectable); the new template renders correctly in Outlook desktop, Outlook web
and Gmail (screenshots attached here); the composer shows recommended articles with their reasons; one send creates
exactly one history row; a second preview of the same articles makes no new LLM or Playwright call; the executive
summary comes from the weekly recaps; tests cover the language switch, edition/period numbering, the ranking, the cache
and the no-duplicate-row case.
