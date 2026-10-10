# Post-cutover roadmap

A record of requests that have **not been done yet**, written on 2026-09-26 (user requests, order = the order of
work). Not a schedule commitment: each item only needs the input/decision written under it.
What is **already** running and not roadmap is in `docs/PROGRESS.md`; the cutover gate is in
`docs/CUTOVER_RUNBOOK.md`.

Each item contains: **what** was asked, **the current state** (facts from the repo/staging, not guesses),
**touch points** (files), **what is needed** before starting, and **how to prove it is done**.

| # | Item | Needs from the user | Depends on |
|---|---|---|---|
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
| 13 | **CI on `main` is red** (3 jobs), so the Deploy job has never run (5 runs, all `skipped`) -- **green CI on `main` proven 2026-10-07 (run #23); Deploy triggered for the first time (run #8) but `cancelled` after 10m25s, cause unknown** | -- | -- |
| 14 | Logo missing from the CVE Tracker Excel export (Pillow is not yet a dependency) -- **code + test done 2026-10-07, the image smoke build in CI not yet** | -- | -- |
| 15 | Use `published_at` in the UI/API/dashboard + align the export date formats | a decision on the format of the Acknowledged column | the `published_at` backfill in production |
| 16 | CVE dashboard: SLA per severity (replacing fixed-threshold ratings) | ack/remediation SLA targets per severity | -- |
| 17 | CVE dashboard: backlog/aging panels, KEV/EPSS, most frequently affected products | a choice of panels | -- |
| 18 | CVE ticket field validation + a ticket model decision (1 ticket per CVE vs one ticket for many CVEs) | a list of standard values, the model decision | -- |
| 19 | **Tech catalog from the CVE mirror + Monitor** (new direction 2026-10-07, replacing the alias/phase 2-3 plan; the `aliases` column is dropped): mirror every CVE (calendar-year retention) -> a vendor+product catalog -> All Tech / Monitored Tech tabs -> the CVEs tab only for monitored techs. **Code done (slices 1-7) on the `nameless/roadmap-runners` branch, the PR closes this roadmap item**; what remains is operational: mapping the 34 entries on dev, shadow mode, cutover (`docs/CVE_CATALOG_CUTOVER.md`); design `docs/CVE_CATALOG_DESIGN.md` | manual mapping + shadow on dev | test on the dev server first, then prod |

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

> **Superseded by #19 (code done 2026-10-08, not yet on `main`).** A Monitored tech (the Monitor button,
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
**What already exists on the `nameless/roadmap-runners` branch (not yet on `main`)**: `cti_core.tech_match` (one
definition of "matches": whole word, attached version digits accepted, attached letters rejected, terms < 2 characters never
match) used by matchers 2-6 and by the `reconcile_cve_tech` assessor. **The `techstack_entries.aliases` column,
the migration, the seed, and the `techstack_aliases` reference data are dropped (user decision 2026-10-07)**; there is no new
migration. The visible effect in production once merged: `tech_stack` alerts and the `in_tech_stack` flag no longer
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
on the branch. **All the #19 code exists; what remains is operational, done by the user**: mapping the 34 entries on dev,
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
- **Status 2026-10-08**: code done; what remains is manual mapping, shadow mode, and cutover (runbook). Items
  below not marked DECIDED are still open.
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
