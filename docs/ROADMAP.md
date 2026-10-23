# Post-cutover roadmap

A record of requests, written on 2026-09-26 (user requests, order = the order of work) and updated as they are
delivered; **status as of 2026-10-23: the "Status" column of the index below, and "Delivered so far" right after it**. Not a
schedule commitment: each open item only needs the input/decision written under it.

> **2026-10-22: this repository is frozen for new work.** The user decided to plan a v2 as a new application in a separate
> repository and to leave this one untouched for now (no further hotfix or 0.7.x release is planned). The open items below stay
> as a record and as input for the v2 plan; production keeps running 0.7.4.

**Status legend**: **Done** = nothing left; **Live** = merged and running in production, with follow-ups listed in the item;
**Mostly done** = the work is done, only decisions or small leftovers remain; **Open** = not done, the item says what it needs;
**Parked** = set aside on purpose by the user, do not start without a trigger; **Superseded** / **Dropped** = no longer pursued.

> Several internal documents that older text in this file points to were **removed from the repository on 2026-10-16**
> (`docs/PROGRESS.md`, `CUTOVER_RUNBOOK.md`, `PLAN_RECAP_NEWSLETTER.md`, `CVE_CATALOG_DESIGN.md`, `CVE_CATALOG_CUTOVER.md`,
> `SECRETS_ROTATION.md`, `PROD_PREP.md`, `KNOWN_BROKEN.md`, `PARALLEL_RUN_COMPARISON.md`, `docs/mockups/`, `docs/spikes/`).
> Those references are historical and no longer resolve; `CHANGELOG.md`, `docs/ARCHITECTURE.md` and `docs/CVE_END_TO_END.md`
> remain.

Each item contains: **what** was asked, **the current state** (facts from the repo/staging, not guesses),
**touch points** (files), **what is needed** before starting, and **how to prove it is done**.

| # | Status | Item | Needs from the user | Depends on |
|---|---|---|---|---|
| 21 | **Done** | **PRIORITY (team feedback 2026-10-10)** -- **Improve the Recap feature**: weekly instead of daily (a manual daily trigger stays), fewer/cheaper LLM calls, week-over-week comparison, grounding check, forecast scorecard -- **code merged 2026-10-11/12 (PR 1-4: #34, #36, #40, #42), released as 0.5.0 (2026-10-14), deployed to prod (by the user; running 0.5.0 by 2026-10-15); the weekly recaps of 28 Sep and 5 Oct exist on prod and the Monday schedule is registered in `beat` (read-only check 2026-10-16)** | nothing | -- |
| 22 | **Live** | **PRIORITY (team feedback 2026-10-10)** -- **Newsletter**: monthly (first working day of the month), Indonesian article summaries under English headings, redesigned template with the company logo (mockup drawn, `docs/mockups/newsletter-redesign.html`), recommended articles in the composer, denser layout (full cards plus a compact list), executive summary paragraph from the weekly recaps, per-article summary cache and one history row per send -- **code merged 2026-10-11/14 (PR 5-9: #35, #39, #38, #43, #44), released as 0.5.0 and deployed to prod (by the user; running 0.5.0 by 2026-10-15); the APAC set and the real-mailbox checks (new Outlook light and dark mode, Outlook web and desktop, Gmail) were confirmed by the user on 2026-10-15; file-name titles no longer take a Highlight (#53); no edition has been prepared yet (`newsletter_suggestions` is still empty on prod on 2026-10-23; the October edition is due Mon 2 Nov)** | the first real edition on Mon 2 Nov | #21 (the executive summary reads the weekly recaps; shared LLM usage logging) |
| 1 | **Done** | Rebranding the platform name + UI (colour palette, typography, animation) -- **DONE 2026-10-02; the SVG logo is parked by the user (2026-10-15); confirmed done by the user on 2026-10-23** | nothing | -- |
| 2 | **Done** | Rebranding the `newsletter_email` and `cve_notification_email` templates -- **code 2026-10-02; the newsletter email is verified in real clients (new Outlook light and dark mode seen 2026-10-14; Outlook web, Outlook desktop and Gmail confirmed fine by the user on 2026-10-15); confirmed done by the user on 2026-10-23, `cve_notification_email` included** | nothing | #1 |
| 3 | **Done** | A "Populate now" button in the CVE Tracker (all / only newly added) -- **covered by #19 (the Monitor flow fills a tech's history from the mirror); confirmed done by the user on 2026-10-23** | nothing | -- |
| 4 | **Live** | IOC enrichment + reputation (VirusTotal, AbuseIPDB, urlscan, Shodan/GreyNoise) -- **code merged 2026-10-15 (#55, #58), released as 0.6.0 and deployed to prod; all three keys (AbuseIPDB, VirusTotal, OTX) are set there and 956 of 7,375 IOCs already carry cards (2026-10-16); OTX was stalled in most runs by HTTP 400 on some IOCs (fixed in 0.6.1, see the item; prod runs 0.7.4 since 2026-10-21, so the fix is live); urlscan, GreyNoise and Shodan are not built** | a look at which IOCs OTX rejects; whether the VirusTotal plan behind the key allows commercial use is the owner's call | -- |
| 5 | **Parked** | Outbound IOC/CVE feeds (TAXII 2.1 and/or CSV/JSON) + integration API keys | target tooling (Wazuh/Splunk/Fortinet?) | #4 |
| 6 | **Open** | IOC lifecycle: first/last seen, sightings, expiry/decay -- **first/last seen, sighting count and confidence decay already exist; only expiry in the outbound feed is missing** | an IOC age decision | #4, #5 |
| 7 | **Open** | Relevance to our own assets: threats x techstack, alerts for actors targeting our stack | tidy asset data | -- |
| 8 | **Parked** | MISP/OpenCTI connector (import + export) | a target instance | #5 |
| 9 | **Parked** | Dark web monitoring through aggregator sources (breaches, ransomware leak sites, Telegram) -- not crawling onions ourselves | budget, a list of executive domains/emails, internal approval | -- |
| 10 | **Parked** | Case/RFI workflow (assignment, SLA, status, audit) linked to CVE tickets | the team's workflow | -- |
| 11 | **Parked** | Consistent TLP/PAP on every object + MFA/SSO | a TLP policy | #5 |
| 12 | **Open** | Improving the article classification prompt based on the audit trail (false accept / false reject) | examples of misclassified articles | the `raw_enrichment` audit trail (running since 2026-10-05) |
| 13 | **Dropped** | **CI on `main` is red** (3 jobs), so the Deploy job has never run (5 runs, all `skipped`) -- **dropped 2026-10-15: CI on `main` is green; the Deploy workflow is disabled on purpose (user) and production is updated with `make deploy`** | -- | -- |
| 14 | **Done** | Logo missing from the CVE Tracker Excel export (Pillow is not yet a dependency) -- **done 2026-10-07 (PR #9); the API image build with pillow is green in CI (PR #12)** | -- | -- |
| 15 | **Open** | Use `published_at` in the UI/API/dashboard + align the export date formats -- **prod has 7 `cve_tracker` rows without `published_at` (2026-10-15, unchanged on 2026-10-23)** | a decision on the format of the Acknowledged column | the `published_at` backfill in production |
| 16 | **Open** | CVE dashboard: SLA per severity (replacing fixed-threshold ratings) | ack/remediation SLA targets per severity | -- |
| 17 | **Done** | CVE dashboard: backlog/aging panels, KEV/EPSS, most frequently affected products -- **DONE (#54), released as 0.6.0 and deployed; the panels have not been looked at in a browser** | -- | -- |
| 18 | **Open** | CVE ticket field validation + a ticket model decision (1 ticket per CVE vs one ticket for many CVEs) | a list of standard values, the model decision | -- |
| 19 | **Open** (operational) | **Tech catalog from the CVE mirror + Monitor** (new direction 2026-10-07, replacing the alias/phase 2-3 plan; the `aliases` column is dropped): mirror every CVE (calendar-year retention) -> a vendor+product catalog -> All Tech / Monitored Tech tabs -> the CVEs tab only for monitored techs. **Code done (slices 1-7), merged to `main` 2026-10-08 (PR #12, release 0.3.0)**; what remains is operational: finish the mapping (prod, 2026-10-23: 27 of 37 entries mapped), shadow mode (not started: `CVE_MIRROR__PROMOTE` unset, `cve_promotion_shadow` empty on 2026-10-23), cutover (the runbook and design documents were removed from the repository on 2026-10-16) | manual mapping + shadow on dev | test on the dev server first, then prod |
| 20 | **Mostly done** | **Known follow-ups from releases 0.4.0 / 0.4.1** (found while reviewing the CVE Tracker; none is blocking) -- **the data-correctness points were fixed 2026-10-15 (#51, #52) or earlier (#21); what is left (the (D) decisions, the KEV/EPSS/Exploit-DB access point, `trending_cve` in January) is marked in the item** | product decisions on the points marked (D) | -- |
| 23 | **Live** | **Runtime secrets** (asked 2026-10-16): manage the third-party keys (LLM, Telegram, Graph, NVD, GitHub, twitterapi.io, X, OTX, AbuseIPDB, VirusTotal) from a superadmin-only admin page, encrypted in the database and applied without a restart or rebuild; the deployment-level secrets (database, Redis, JWT/session, OIDC) stay in `.env` -- **merged 2026-10-16 as one pull request (#63), released as 0.7.0 and deployed to prod (running 0.7.4 since 2026-10-21); the master key is set there and the page is in use (one override, `llm`, on 2026-10-23)** | one check that the OTX probe (`GET /api/v1/users/me`) answers 200 for a real key; the re-auth decision for OIDC-only superadmins | -- (touches #11 for the OIDC question) |
| 24 | **Open** (PR-A live; PR-B not started) | **Data platform audit follow-ups** (asked 2026-10-17): stop losing articles when the LLM fails (a structured failure kind, replay, an alert, an honest run status, a reaper and a purge) and show the pipeline's health in the UI (a **Data health** page, a reliable previous-period delta, reasons on `/scrapers`) -- **PR-A merged 2026-10-21 (#65, release 0.7.2) and deployed to prod (0.7.4, Alembic head `b7e4c1a9d256`); the replay has not been run on prod (38 rows wait: 34 `transient`, 4 `permanent`, 2026-10-23); on dev the user replayed a first batch of 10 of 147 on 2026-10-21; PR-B (Data health, Dashboard, Scrapers) is not started** | run `make replay-failed-enrichment` on prod (report first, then `--apply`) and finish it on dev; a go-ahead for PR-B (the repository is frozen, see the note at the top) | -- (PR-B reads `failure_kind` from PR-A) |
---

## Priority queue (team feedback 2026-10-10)

The team asked for two items to be treated as priorities; they go before everything that is still open. Order:
**#21 Recap first** (it introduces LLM usage logging and the weekly content that #22 reuses), then **#22 Newsletter**.
Scope was decided with the user on 2026-10-10 (which proposed additions were approved and which were left out are
listed in each item); both are written out at the end of this file. The implementation plan (nine pull requests, order,
tests, rollback) was `docs/PLAN_RECAP_NEWSLETTER.md` (removed from the repository on 2026-10-16). **All nine pull requests are merged into `main` (2026-10-11 to
2026-10-14).** Each item has an "Implementation status" block: what was built, what was proven on the dev instance, and
what is still open. **Both are deployed to prod (running 0.5.0 by 2026-10-15) and the real-mailbox checks are closed; the only thing
left is the first real newsletter edition on Mon 2 Nov.** The sections "Current state" below describe the code **before**
these pull requests.

---

## Delivered so far (as of 2026-10-23)

PRs #2-#68 are all merged into `main` (release tags in `CHANGELOG.md`: 0.2.0, 0.2.1, 0.3.0, 0.4.0, 0.4.1, 0.5.0, 0.6.0, 0.6.1,
0.6.2, 0.7.0, 0.7.1, 0.7.2, 0.7.3, 0.7.4; 0.6.1 has a `CHANGELOG.md` entry but no git tag or GitHub Release). Production runs
**0.7.4** (deployed by the user 2026-10-21; `/healthz` and Alembic head `b7e4c1a9d256` checked read-only on 2026-10-23).

**Roadmap items by status**

| # | Status | Delivered by | What is left |
|---|---|---|---|
| 1 | Done | PRs #3, #4 (+ the rename to Vareon Intelligence, 2026-10-05) | nothing (confirmed by the user 2026-10-23; the SVG logo stays parked) |
| 2 | Done | PR #3; newsletter email verified 2026-10-14/15 | nothing (confirmed by the user 2026-10-23) |
| 3 | Done (through #19) | PR #12 | nothing (confirmed by the user 2026-10-23) |
| 4 | Live | PRs #55, #58 (0.6.0), the OTX 400 fix (0.6.1); on prod since 2026-10-15/16 | which IOCs OTX rejects (after 0.6.1); OTX threshold review; urlscan/GreyNoise/Shodan; scoring integration |
| 13 | Dropped | PR #11 (CI green on `main`) | nothing: the Deploy workflow is disabled on purpose |
| 14 | Done | PR #9 (pillow), CI image build green in PR #12 | nothing |
| 17 | Done | PR #54 (0.6.0) | look at the panels in a browser |
| 19 | Code done, merged | PR #12 (release 0.3.0), PR #27 (cutover runbook fix) | operational only: finish the mapping (prod: 27 of 37 on 2026-10-23), shadow mode, cutover dev then prod |
| 20 | Mostly done | PRs #21, #51, #52, #53 (0.4.x-0.6.0) | the (D) decisions, the KEV/EPSS/Exploit-DB access point, `trending_cve` in January |
| 21 | Done | PRs #34, #36, #40, #42 (0.5.0), on prod by 2026-10-15 | nothing |
| 22 | Live | PRs #35, #39, #38, #43, #44 (0.5.0), #53 (0.6.0), on prod by 2026-10-15 | the first real edition, Mon 2 Nov |
| 5, 8, 9, 10, 11 | Parked | -- | set aside by the user on 2026-10-15; do not start without a trigger |
| 6, 7, 12, 15, 16, 18 | Open | -- | see each item; #6 mostly exists (only expiry is missing), #7 waits for the #19 cutover, #15 waits for the `published_at` backfill (7 prod rows), #12 for labelled examples, #16 and #18 for SLA targets and the list of ticket values |
| 23 | Live | PR #63 (0.7.0), on prod with the master key set | the OTX probe against a real key; the OIDC re-auth decision; a re-encrypt helper for master key rotation |
| 24 | Open (PR-A live) | PR #65 (0.7.2), on prod since 0.7.4 | replay the failed articles (prod: 38 waiting; dev: 10 of 147 done); PR-B |

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
| after 0.4.1 (2026-10-10 to 2026-10-12) | #32, #33 | roadmap status update ("Delivered so far", #20); the #21/#22 implementation plan |
| after 0.4.1 (2026-10-11 to 2026-10-14) | #34, #36, #40, #42 | **#21 recap**: token usage stored and one row per CVE (PR 1); weekly Monday-Sunday recap on a Monday 00:15 UTC schedule (PR 2); week-over-week comparison, grounding check and forecast scorecard (PR 3); the Recap page shows them (PR 4) |
| after 0.4.1 (2026-10-11 to 2026-10-14) | #35, #37, #38, #39, #43, #44 | **#22 newsletter**: summary cache, side-effect-free preview and one row per send (PR 5); alembic head fix (#37); ranking and `newsletter_suggestions` (PR 7); new template, inline logo, Indonesian summaries (PR 6); monthly schedule and Executive Summary (PR 8); composer filled with the suggestion (PR 9) |
| after 0.4.1 | #41, #45 | scraper additions (`aws_security`, news scraper); not part of #21/#22 |
| 0.6.0 (2026-10-16) | #50-#56, #58, #59 | `new_cve` no longer drops CVEs silently at `max_items` (#50); dashboard UNRATED bucket and one crossref row per CVE (#51); KEV flag reset and the read-only `check-orphaned-tickets` tool (#52); file-name titles never take a newsletter Highlight (#53); dashboard backlog, exploit-risk and top-tech panels, **#17** (#54); IOC enrichment writer with AbuseIPDB, **#4** (#55) and VirusTotal + OTX (#56 was merged into the #55 branch because that branch had not been deleted yet, so it reached `main` through #58); the release PR #59 also synced this file and `docs/ARCHITECTURE.md` |
| 0.6.1 (2026-10-16) | #60 | fix release: enrichment no longer stalls on IOCs a provider rejects with HTTP 400 (OTX stalled in 45 of 60 runs on prod); roadmap status column and prod facts |
| 0.6.2 (2026-10-16) | #61, #62 | the alert path also fills X Intel and `monitor_x` gets a provider option (#61, inside the 0.6.2 tag but not in its `CHANGELOG.md` entry); main Dashboard and Exec no longer mislead: period selector, "General" is not a sector, honest previous-period deltas (#62) |
| 0.7.0 (2026-10-16) | #63 | **#23 runtime secrets**: the Third-party Keys admin page, `runtime_secrets` table, probes, rate-limited password change |
| 0.7.1 (2026-10-17) | #64 | web redesign and accessibility fixes from a visual audit (frontend only) |
| 0.7.2 (2026-10-21) | #65 | **#24 PR-A**: `failure_kind`, enrichment-failure alert, replay (CLI + Newsroom button), "Filtered Articles" tab, honest `partial` run status, run reaper and purge |
| 0.7.3 (2026-10-21) | #66, #67 | security fixes from an audit (Threat Actor watchlist tenant scoping, `navigator-layer` needs a login, `fetch_text` only reaches public addresses, escaped Telegram alerts); Dashboard and Newsroom restyle |
| 0.7.4 (2026-10-21) | #68 | one article goes to one Telegram topic (no OT duplicate), and one broken thread no longer stops alerts to the other topics |

Release 0.5.0 (tag `0.5.0`, GitHub Release `v0.5.0`, 2026-10-14) carries everything after 0.4.1 and sits on `f55132d`, the
merge of #48, so the dark-mode fix is inside (the `CHANGELOG.md` line about it was added after the tag). The plan expected 0.5.0 after #21 and 0.6.0 after #22, but both were on `main` before either was cut, so
there is one release. Follow-ups found while delivering 0.4.x are collected in #20
below.

Release 0.6.1 (2026-10-16) is a fix release on top of 0.6.0: the OTX 400 stall described in #4, and this status update.

Release 0.6.0 (tag `0.6.0`, GitHub Release `v0.6.0`, 2026-10-16) is the merge of #59 (`3015304`) and carries everything after
0.5.0 (#50-#58) plus the docs sync; CI on that commit was green. It is deployed on prod (`/healthz` says 0.6.0 on 2026-10-16,
Alembic head unchanged at `7e51efe6d78b`).

---

## 1. Rebranding the platform name and UI

> **Status 2026-10-02 -- done** (PRs #3 and #4). Display name **Vareon Intelligence** (one constant
> `apps/web/src/lib/brand.ts` + the `platform_name` setting in `cti_core.config`); light and dark themes
> (`globals.css`, separate severity tokens, contrast checked to AA); the Google Sans Flex font; `prefers-reduced-motion`;
> the sidebar, dashboard + world map, every tab and the main dialogs checked on staging. Technical identifiers (`cti-platform`,
> `cti_*`, images) deliberately stay. **Remaining**: the SVG logo (the header is still the letter "N" + text), and a `grep` for the old name in
> LLM prompts ("Cyber Threat Intelligence" as a generic term) is deliberately left alone.
>
> **Update 2026-10-15**: the SVG logo is parked by the user. The header still shows a round "V" mark + the name
> (`app-header.tsx`, `Brand()`); `apps/web/public/` is empty. It needs the brand's vector file. The newsletter uses a different
> logo (the company PNG), not this one.

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

> **Status 2026-10-23 -- done** (confirmed by the user, both templates).
>
> **Status 2026-10-02 -- code done, verification not yet**: `templates/_base_email.html` (Jinja `extends`) is used by
> both emails; brand palette, hex only, a fallback font stack, `platform_name` from the setting. **Not yet**: sent through
> Graph to a test account and checked in Outlook desktop/web, Gmail, mobile (the "Done when" criteria below). Note:
> the newsletter preview on staging still fails with `500: Expecting value` on the server side (suspected LLM configuration
> in `.env`), separate from this template.
>
> **Update 2026-10-15**: the newsletter no longer extends `_base_email.html` (new template, #22) and its real-client checks are
> closed (new Outlook light and dark mode seen 2026-10-14; Outlook web, Outlook desktop and Gmail confirmed fine by the user).
> What remains is `cve_notification_email`, which still extends `_base_email.html` and was not part of those checks.

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

> **Status 2026-10-23 -- done** (confirmed by the user; delivered through #19).
>
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
**Current state** (before #55): IOCs are extracted from articles (`cti-enrich`); there was no external enrichment, although
the `iocs.enrichment` column, the API serialisation and the "TIP Enrichment" cards in `ioc-detail-dialog.tsx` already
existed: nothing wrote them.
**Needed**: an API key + quota per service (stored through the same secret mechanism as
`docs/SECRETS_ROTATION.md`), a decision on which IOCs are enriched (all vs only those linked to priority CVEs/actors)
so quotas do not run out.
**Done when**: the IOC detail shows the verdict + a source link, results are cached, rate limits are respected,
and one service failing does not fail the others.

**Status 2026-10-23**: deployed; prod runs 0.7.4 (it carries the 0.6.1 OTX 400 fix). The block below is the state at merge time.

**Status 2026-10-15 -- code merged (#55 AbuseIPDB, #58 VirusTotal + OTX), not deployed, never run against a real service**
- **Only the writer was missing**, so the work was backend-only: the periodic task `ioc.enrich_pending` (maintenance queue,
  every 15 minutes, no-op without a provider key) -> `cti_api.services.ioc_enrichment.enrich_pending` -> provider clients and
  card mapping in `ioc_providers`. The card shape is the one the UI already read (`key`, `name`, `verdict`, `score`, `raw`,
  `tags`, `malware_families`, plus `checked_at`); `iocs.enrichment.updated_at` is shown by the dialog. See
  `docs/ARCHITECTURE.md` section 3.7.
- **Why a periodic task and not a pipeline stage**: the enrichment pipeline already costs 10-13 s + an LLM call per article;
  a slow or dead provider must not hold articles back.
- **Selection**: supported types, not `auto_suppressed`, no card for that provider or a card older than its TTL, newest first.
  No priority filter: measured on prod (2026-10-15) about 143 non-CVE IOCs and 24 IPs per day (791 IPs in total), far below
  the free quotas, so every supported IOC is checked, capped by an hourly budget (Redis fixed window, `<PROVIDER>__RATE`).
- **Providers** (a key left empty keeps that provider off; lookups only, nothing is ever submitted or scanned):

  | Provider | Types | Verdict | TTL | Budget |
  |---|---|---|---|---|
  | AbuseIPDB (`ABUSEIPDB__API_KEY`) | ip | confidence >= 75 malicious, >= 25 suspicious, reports but low = clean, no reports = unknown | 3 days | `40/hour` (free plan: 1000/day) |
  | VirusTotal (`VIRUSTOTAL__API_KEY`) | ip, domain, url, hashes | >= 3 engines malicious = malicious, 1-2 (or >= 3 suspicious) = suspicious; `score` = % of engines flagging | 30 days | `20/hour`, >= 15 s between calls (public API: 4/min, 500/day) |
  | OTX (`OTX__API_KEY`) | ip, domain, hashes (URL not supported) | pulse count >= 3 malicious, 1-2 suspicious, 0 unknown; no score | 7 days | `300/hour` |

  The thresholds are starting values (constants at the top of `ioc_providers.py`).
- **Failure isolation**: one failed IOC (network, 5xx) leaves no card and is retried on the next run (a 4xx rejection stores an
  `unknown` card since 0.6.1); 401/403/429 or three failures in a row stop that provider for the run; the log carries the exception class and the status code only, never the message (it can
  echo a key). A private or invalid IP is not sent anywhere: it gets a `skipped` card so it is not picked again.
- **Licence**: VirusTotal's own documentation says the public (free) API must not be used in commercial products or
  services. Fill `VIRUSTOTAL__API_KEY` only from a plan that allows it. AbuseIPDB's and OTX's terms of use were NOT checked
  (only AbuseIPDB's API documentation, which does not mention commercial use): confirm before relying on a free plan.
- **OTX starts on its own at deploy**, because `OTX__API_KEY` is already set on prod: about 3,300 IOCs of the supported types
  are waiting, and the 25-per-run cap (four runs an hour) makes the backfill take roughly a day and a half.
- **Open**: deploy; fill the AbuseIPDB key (and a VirusTotal key if the licence question is settled); look at a real card in
  the IOC detail; urlscan, GreyNoise and Shodan are not built; no scoring integration (`confidence_score` and
  `actionability_*` ignore the verdicts for now); OTX URL lookups need the path encoding checked against the real API.

**Update 2026-10-16 -- deployed and running on prod (0.6.0), read-only check**
- **All three keys are set** on prod (`OTX__API_KEY`, `ABUSEIPDB__API_KEY`, `VIRUSTOTAL__API_KEY`). Whether the VirusTotal plan behind the
  key allows commercial use was not verified here; the licence is the owner's call (see the Licence point above).
- **Cards written**: 956 of 7,375 IOCs carry at least one card. AbuseIPDB 591 (471 unknown, 85 clean, 18 suspicious, 17 malicious),
  OTX 453 (160 unknown, 142 suspicious, 151 malicious; domains 177, hashes 166, IPs 110), VirusTotal 270 (31 unknown, 56 clean,
  46 suspicious, 137 malicious), plus 7 `skipped` cards. AbuseIPDB and VirusTotal mostly stop on their hourly budget, as designed.
- **Bug found: OTX is stalled in most runs.** In the last 16 hours 45 of 60 OTX runs stopped with `consecutive_failures` and 43 of
  them checked nothing: the log shows `ioc_enrich_failed provider=otx status=400`. Cause: a failed IOC leaves no card, so it is
  selected again at the head of the queue (newest first) on every run; three such IOCs block the whole provider for the run.
  The failing values are not logged (by design). Three IOCs seen at the head of the queue later (an IPv4 address and two domains)
  were tried directly against OTX's public endpoint and answered normally, so they are probably not the cause; the failing values
  are still unidentified. 3,076 IOCs still have no OTX card
  (domains 1,142, sha256 810, IPs 713, md5 295, sha1 116).
- **Fixed in 0.6.1**: a client error that is about the IOC itself (HTTP 4xx other than 401/403/429, 400 first of all) now stores an
  `unknown` card ("rejected by provider (HTTP 400)"), like the `skipped` card, so the IOC is not retried until its TTL and does not
  count toward the three-in-a-row stop; five rejections in a row stop the provider for the run (a wrong request shape must not
  poison every IOC). 5xx and network errors keep the old behaviour (retry next run). The log line now carries `ioc_id` and
  `ioc_type`. **The cause of the 400 is still unknown**: after deploying 0.6.1 the rejected IOCs can be listed (cards whose
  `raw.skipped` starts with "rejected by provider") and looked at.
- **Thresholds to review**: 151 of 453 OTX cards (33%) are `malicious` with the "three or more pulses" rule; OTX pulses can list
  benign indicators as context, so the rule may be too eager. Starting values, constants in `ioc_providers.py`.

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
**Current state** (checked 2026-10-15): the allowlist exists (`IocAllowlistEntry`), and `iocs` already has `first_seen_at`,
`last_seen_at`, `seen_count`, `confidence_score` + `confidence_decayed_at` (the `ioc.decay_sweep` task keeps the decay
current). What does not exist is **expiry**: nothing drops an old IOC out of a feed, and there is no feed yet (#5).
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
**Decision 2026-10-15**: the Deploy workflow is disabled on purpose (user); production is updated with `make deploy`.
This item is no longer pursued.

**Finding, corrected 2026-10-15**: the earlier claim that `extract_iocs()` takes ~5 seconds on a ~12KB article only holds for
artificial text. Measured: ordinary prose of 12,000 characters takes 26-32 ms; only `"word. " x 2000` (12,004 characters)
takes 4.7 s, which is the shape the ReDoS test uses. On 100 real pages from the test fixtures (tags stripped by hand, so
inflated) the median was 19 ms and p90 361 ms; the slow ones were pages of 1-2 million characters, and two pages of 5.4-5.9
million characters took more than 8 s. In production `fetch_text` gives article text, so the cost is small; the only risk is
an outlier of huge text, and there is no overall length cap in `fetch_text.py` (only a 1500-character per-block limit).
If it is ever worth guarding: skip `_RE_DOMAIN_DEFANGED` when the text contains none of its mandatory defang separators
(`[.`, `.  ]`, `(.)`, `{.}`, `[dot]`, `(dot)`). The output is identical by construction (checked on three samples) and the
pathological case drops from 4.7 s to 2.5 ms; the check must run on the same string given to `findall`
(`text_no_urls_or_paths`). Not planned.

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
**Measured on prod 2026-10-15**: 382 tracker rows (one client), 7 without `published_at`, so the backfill is nearly complete.
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

**Status 2026-10-15 -- done in #54 (merged), not yet looked at in a browser** (`tsc`, `eslint` and `pnpm build` pass; the
panels were not rendered against real data). Computed in `build_dashboard`, drawn in `cve-dashboard-view.tsx`:
- **Unresolved backlog by age**: CVEs that are unacknowledged, awaiting status, Open or In Progress (Completed, Risk Accepted
  and Not Affected are not backlog), by severity x age band (0-7, 8-14, 15-30, 31+ calendar days in WIB since detection).
  `OVERDUE_DAYS = 14` is the same limit as the "Fair" MTTA rating; there is no per-severity SLA yet (#16).
- **Exploited or likely to be exploited, still unresolved**: unresolved CVEs in the CISA KEV catalog or with EPSS >= 0.1 (the
  same threshold the CVEs tab colours as a warning), KEV first, then EPSS descending, then the oldest; capped at 10 with the
  real count in `exploit_risk_total`. `list_dashboard_rows` now also reads `cisa_kev` and `epss_score`.
- **Most affected tech**: top 10 techs by CVEs detected in the year (critical, high, and how many are unresolved).
- `build_dashboard(today=)` takes the day the ages are measured from (default: today in WIB) so tests and the response
  snapshot do not move with the clock.
- **Open**: look at the three panels on the dev or prod instance; `OVERDUE_DAYS` and `EPSS_HIGH` are starting values.

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
- **Status 2026-10-23 (prod, read-only check)**: `CVE_MIRROR__ENABLED=true`, `CVE_MIRROR__PROMOTE` still not set,
  `cve_promotion_shadow` still empty; **27 of 37 techstack entries are mapped** to the catalog (2026-10-15: 25 of 35). Nothing else moved: mapping, shadow and cutover are still the remaining steps.
- **Status 2026-10-15 (prod, read-only check)**: `CVE_MIRROR__ENABLED=true`, `CVE_MIRROR__PROMOTE` not set (= `off`), `cve_promotion_shadow`
  empty (shadow not started); the mirror holds 122,910 CVEs (newest published 2026-10-15), the catalog 15,303 vendors and 40,954
  families; `cve_mirror_synced` is `failed=0`, `gap_unrecoverable=False`; **25 of 35 techstack entries are mapped** to the catalog.
  `new_cve` is still the live ingest there: 14 of its runs in three days ended `fetch_error` (NVD 503 on keyword searches), the
  failure class the cutover removes.
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
- **Fixed 2026-10-15 (#52)**: `cisa_kev` / `active_exploitation` were never reset to `false` when CISA removed an entry from
  the KEV catalog. `run_cisa_kev_lookup` now clears them for checked CVEs missing from the catalog, but only when the catalog
  has at least 1000 entries (an empty or truncated response must not clear every flag; the summary then says
  `reset_skipped`). `CveTracker.active_exploitation` is written by KEV only; the analyst's value lives on the ticket.
- Status "Resolved" without `actual_remediation_date` is not counted in MTTR (visible in the `n` on the dashboard);
  field validation for tickets is #18.
- **Checked 2026-10-15 (#52)**: tickets orphaned by an old `purge-orphaned` are not cleaned automatically. `make
  check-orphaned-tickets` lists them (read-only, deliberately without `--apply`: an orphan reconnects by itself if its tracker
  row is created again, e.g. by the mirror promotion after the #19 cutover). On prod there were 0.
- **Fixed**: `recap` and `crossref` returned one row per client, so a CVE tracked by two clients appeared twice. Recap was
  fixed in #21 (`list_registered_between`), the PIR and actor crossrefs in #51 (`_strongest_per_cve`, one row per CVE, limit
  applied after the dedupe).
- `cve_newsletter_mentions` is written to only one tracker row (any client) and nothing reads it yet.
- No code writes `cve_threat_actors` and `cve_ttps`, so the TA/TTP branch of `crossref` has no data.
- **Fixed 2026-10-15 (#51)**: the dashboard tables "Mean time metrics by severity" and "Monthly CVE volume by severity" did
  not show unrated CVEs. `by_severity` now ends with an `UNRATED` row (only when there are unrated CVEs) and
  `MonthMetrics.unrated` exists; the stacked chart is unchanged (no colour token for unrated).

**Coverage**
- `trending_cve` only searches `CVE-<current year>-`; last year's CVEs that are trending are missed (adding them costs more
  X API tweets and the query syntax must be validated against the real API). **It starts to matter in early January 2027**,
  when December's CVE-2026 ids are still trending: check the cost, then search the previous year too until about March.

**Done when**: each point is either fixed (with a test) or dropped with a one-line reason here.


---

## 21. Improve the Recap feature (PRIORITY)

> **Priority item, requested by the team on 2026-10-10. Scope decided with the user the same day. Built in PR 1-4
> (#34, #36, #40, #42), merged 2026-10-11 and 2026-10-12.** This section records the current state (as it was **before**
> those pull requests), what was decided, the design of each part, the measurements, and what is still open.

**Implementation status (2026-10-14)**
- **Merged**: PR 1 #34 (token usage stored, one CVE row per `cve_id` in a fixed order), PR 2 #36 (weekly Monday-Sunday
  recap built from aggregates, `kind` + `period_start`/`period_end` on `daily_recaps` with a unique `(kind, date)`,
  beat entry Monday 00:15 UTC, migration `f6c3a9d2b8e1`), PR 3 #40 (`quality`: comparison, grounding, scorecard; the
  grounding helper is shared with #22; migration `7e51efe6d78b`), PR 4 #42 (the Recap page shows them). Manual trigger
  kept: `kind` defaults to `daily`, `kind=weekly` takes the week's Monday. No new setting; `LLM__RATE_LIMIT` is left
  alone (removing the field would stop the prod app, see Design: LLM optimisation).
- **Proven on the dev instance** (it runs 0.5.0, deployed from `f55132d` on 2026-10-14; `/healthz` says 0.5.0): the
  baseline and the weekly measurements below, and the scheduled run: on Monday 12 Oct at 00:15 UTC `beat` created the
  recap of 5-11 Oct by itself (318 articles, 49 CVEs, 30.8 s). A week that has not ended and a date that is not a Monday
  are refused with 400.
- **The quality layer on real data (dev, 2026-10-14)**: the weeks of 28 Sep and 5 Oct were regenerated with Force Regen in
  chronological order (26-28 s each). The risk that the model leaves `article_id` empty did **not** happen: all 8 top
  stories of 5 Oct carry an article id. The grounding check dropped 3 items in 28 Sep and 5 in 5 Oct, all of them campaign
  themes (and one threat actor) that were not in the input: the model invents `active_campaigns` when dev has no campaign
  clusters, which is exactly what the check is for (a prompt that does not ask for campaigns when there are none would
  save the noise). 28 Sep has no comparison (no recap for the week before). 5 Oct has it: articles -33.8%, tweets -100%
  (the X feed stopped on 3 Oct), IOCs -30.3%, CVEs +48.5%, and new this week 4 threat actors and 8 CVEs. Its scorecard
  reviewed the 5 forecast events of 28 Sep: 2 happened, 1 partly, 2 unclear, a hit rate of 83.3% over the 3 judged events.
  Only the API output was read; the rendering of the page was not looked at.
- **Closed 2026-10-15/16**: deployed to prod by the user (0.5.0, then 0.6.0). Read-only check on 2026-10-16: the weekly recaps of
  28 Sep and 5 Oct exist (`daily_recaps`, `kind=weekly`, generated 2026-10-14), `recap-generate-weekly` is in the `beat`
  schedule, Alembic head `7e51efe6d78b`. The week of 12 Oct is the first one the schedule creates on prod, on Mon 19 Oct 00:15 UTC.

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
- **Nothing measured the cost** (fixed by PR 1, merged 2026-10-11, #34): `token_usage` used to be stored as `{}` (the
  completion's `usage` was never read); it now holds the gateway's tokens, `wall_ms`, `input_chars` and the items per
  prompt section. `LlmSettings.rate_limit` ("global spend throttle, Redis token bucket") is still declared in `config.py`
  with no consumer.
  The client retries twice (`max_retries=2`, 60 s timeout), then the task fails; a reply that is not JSON is stored as
  an empty recap with the text in `raw_llm`.
- The CVE list is **global**: `_collect_cves` -> `list_registered_on` returns tracker rows of every client, capped at 50
  by `limit(50)` **without an ORDER BY**, so on a busy day which 50 reach the prompt is arbitrary. The tracker has one
  row per client, so a CVE tracked by several clients appears (and is counted) once per client (found 2026-10-11).
- The campaign clusters are the last 7 days **counted from today** (`get_recent_campaigns` uses `date.today()`), not
  from the recap date, so regenerating an old day uses today's campaigns (found 2026-10-11).
- Output is **English** and the web page is the only consumer (`/recap`, `GET /api/recap/latest|list|{date}`). The page
  opens on yesterday's date.

**Design: weekly**
- Storage: `daily_recaps` is keyed by one day, so add `kind` (`weekly` | `daily`) and `period_start`/`period_end`
  (hand-written migration, `test_migrations_match_models` updated). Weekly rows are the scheduled ones; `daily` rows
  exist only when someone triggers a day by hand. History/list/latest endpoints and the UI show the kind and the range;
  reads take the kind, because a weekly and a daily row can share a Monday. The Recap page opens on the latest weekly
  recap. The daily beat entry is removed in the same change (no setting; the manual daily trigger stays).
- **A week is generated only after it has ended** (Sunday over in UTC). A hand run before that would cache an
  incomplete week, and the scheduled run (`force=false`) would then return the cached row.
- The collectors take the window: range variants of the single-day queries, and the campaign clusters of the window
  (`get_recent_campaigns` gets optional start/end dates) instead of the 7 days before today.
- **Week boundary (confirmed by the user, 2026-10-11): Monday to Sunday by UTC date, generated Monday 07:15 WIB**
  (Monday 00:15 UTC); in WIB terms a week runs from Monday 07:00 to the next Monday 07:00. The
  collectors use UTC calendar dates, so a week is only complete once Sunday ends in UTC; a 00:15 WIB run would miss
  Sunday 17:00-24:00 UTC. The earlier proposal (Friday to Thursday) existed only so two recaps would match a 14-day
  newsletter window; the newsletter (#22) is now monthly and takes the weekly recaps whose week overlaps the month, so
  that reason is gone and the usual Monday-Sunday week is simpler to read. It fits a newsletter built on the first
  working day when the month ends on a Sunday (October 2026): the recap of its last week is generated Monday 07:15 WIB,
  before the newsletter is prepared that morning (09:00 WIB). When the month ends on another day, its last days are in
  a week that is not finished yet; see #22, Design: executive summary.
- A week is about 7x the volume of a day, so the weekly prompt is built from **aggregates**, not from a wider date range:
  top N per category ranked by signal (confidence/score, confirmed incident, KEV/PoC, source reliability, cluster size),
  per-category counts, clusters collapsed to one line each. Forecast horizon becomes 1-2 weeks.
- **Language: the recap stays English** (decided by the user, 2026-10-10), so the Recap page and the prompt language do not
  change. The newsletter (#22) writes its Indonesian executive summary in its own single call from the stored recaps.

**Design: LLM optimisation**
1. **Measure first**: store `completion.usage` (prompt/completion tokens) and the wall time in `token_usage` for every
   recap and log them. Record the baseline before changing anything, so the saving is a number written in this item.
2. **Shrink the input** with the ranking and caps above; collapse duplicate stories by cluster; drop low-signal tweets.
3. **Skip the call when there is nothing to say** (no articles, tweets or CVEs in the window): store the deterministic
   "no notable activity" result the prompt already asks the model to produce.
4. **Never pay twice**: keep the cache per period; `force=true` stays an explicit admin choice.
5. After the baseline, evaluate: a smaller model for the recap (it summarises given text, it does not classify), JSON mode
   / `response_format` to stop non-JSON replies, and provider prompt caching for the static system prompt. Either wire
   `LlmSettings.rate_limit` or delete the dead setting. Deleting takes two releases: `LLM__RATE_LIMIT` is in
   `.env.prod.template`, and with `extra="forbid"` a key left in the prod `.env` after its field is gone stops the app
   from starting (checked 2026-10-11), so the key goes first and the field later.

**Baseline (measured 2026-10-11)**: the seven daily recaps of 4-10 Oct 2026 (UTC), regenerated with Force Regen on the dev
instance right after PR 1 was deployed there (gateway model `my-combo`; the dev data has no tweets and no campaign clusters,
so those prompt sections were empty). One LLM call per day:

| Measure | Sum of the 7 calls | Per call (average, range) |
|---|---|---|
| User message (`input_chars`) | 41,188 chars | 5,884 (1,122 - 10,794) |
| Prompt tokens | 73,833 | 10,548 (8,237 - 12,918) |
| Completion tokens | 12,501 | 1,786 |
| Total tokens | 86,334 | 12,333 |
| Wall time of the LLM call | 121.9 s | 17.4 s |

Collected that week: 320 articles (237 reached a prompt: the daily cap is 60), 79 CVEs, IOC rows at the collector cap (200) on
4 of the 7 days. Reproduce one day with Force Regen on the Recap page (or `POST /api/recap/generate?date=D&force=true`) and read
`token_usage` and `counts` in `GET /api/recap/D`.

Reading the numbers: the gateway reports about 7.9k prompt tokens even for an almost empty message. A least-squares fit over the
seven calls gives roughly `7,900 + 0.45 x chars` prompt tokens (an estimate): the fixed part is far larger than our ~2.2k-character
system prompt, so most of it is overhead outside our text, most likely the gateway. A weekly call pays that fixed part once
instead of seven times, and beats the 73.8k prompt-token sum as long as its user message stays under ~147k characters (aim for far
less). Compare the weekly recap against this table using `input_chars` and the total tokens in its `token_usage`; the daily
figures are a sample of one week, not a constant. The 4-10 Oct rows stored on dev were overwritten (three) or created (four)
by this measurement.

**Weekly measurement (dev, 2026-10-11)**: the week 28 Sep-4 Oct, generated by hand right after PR 2 was deployed to dev
(one call; collected 480 articles, 33 CVEs, 162 tweets, 2,043 IOC rows), against the seven daily calls above:

| Measure | 7 daily calls (4-10 Oct) | 1 weekly call (28 Sep-4 Oct) | Change |
|---|---|---|---|
| User message (`input_chars`) | 41,188 chars | 29,826 chars | -28% |
| Prompt tokens | 73,833 | 21,142 | -71% |
| Completion tokens | 12,501 | 2,644 | -79% |
| Total tokens | 86,334 | 23,786 | -72% |
| Wall time of the LLM call | 121.9 s | 32.7 s | -73% |

How far to trust it: the two samples are **different weeks** (the weekly one is the busier: 480 articles against 320, and
it still had tweets, which the daily week did not), so the saving is conservative, but it is one sample. The fit above
predicted about 21.3k prompt tokens for 29,826 characters and the call used 21.1k, so the fixed gateway overhead is paid
once instead of seven times, as expected. That row was measured **before PR 3**, which adds article ids and the previous
forecast items to the prompt, so the same week was regenerated with Force Regen after PR 3 reached dev (2026-10-14):

| Measure | 7 daily calls (4-10 Oct) | 1 weekly call, 28 Sep-4 Oct, with PR 3 | Change vs daily | Change vs the call before PR 3 |
|---|---|---|---|---|
| User message (`input_chars`) | 41,188 chars | 30,386 chars | -26% | +1.9% |
| Prompt tokens | 73,833 | 21,510 | -71% | +1.7% |
| Completion tokens | 12,501 | 2,431 | -81% | -8% |
| Total tokens | 86,334 | 23,941 | -72% | +0.7% |
| Wall time of the LLM call | 121.9 s | 27.3 s | -78% | -17% |

So the quality layer costs almost nothing: the saving holds at -72% total tokens. The week of 5-11 Oct, which also carries
the scorecard review of the previous forecast, used 19,064 tokens for 19,317 characters (a lighter week, so not
comparable; it is the first call with a comparison and a review in it).

**Design: approved additions**
- **Week-over-week comparison**: compare `counts` with the previous weekly recap (articles, tweets, IOCs, CVEs, campaigns,
  new threat actors) as absolute and percentage deltas, plus "new this week" for threat actors, campaigns and CVEs that
  are in this week's output and not in the previous one. Computed in code, **no LLM**, stored in a `comparison` field;
  omitted when there is no previous weekly recap.
- **Grounding check**: after parsing the reply, verify against the prompt input (a) every CVE id in `notable_cves` and in
  free text, (b) every name in `active_threat_actors` / `new_threat_actors_added`, (c) every campaign `theme`, and (d)
  that each `top_stories` item cites the id of an input article (each article line in the prompt carries its id; titles
  are not compared because the model paraphrases them), then attach the article URL; the page links to it. Items
  that fail are **removed from what is shown and recorded** in a `grounding` field (what was dropped and why), never
  dropped silently. Tests include a reply that invents a CVE and an actor.
- **Forecast scorecard**: store each `likely_events` item with an id and its confidence (`low|med|high`). When the next
  weekly recap is generated, **the same call** also reviews the previous forecast items against the new input (verdict
  `happened | partly | not_happened | unclear` with the evidence it used), so there is no extra LLM call and only a few
  hundred extra input tokens. The analyst can override a verdict on the page. The Recap page shows the hit rate of the
  last 8 weeks, split by stated confidence (does "high" actually come true more often than "low"?); proposed: `partly`
  counts as half and `unclear` is left out.

**Touch points**: `services/recap.py` (collect, aggregate, prompt, grounding, comparison, scorecard), `routers/recap.py`,
`services/campaign.py` (window), `tasks/periodic.py`, `beat.py` (weekly entry at Monday 00:15 UTC, remove the daily
entry), `db/models/recap.py` + migration, `repositories/recap.py` (keyed by kind and date),
`repositories/cve.py` (order, dedupe), `schemas` + `openapi.json` + `schema.d.ts`, `apps/web/src/app/(app)/recap/page.tsx`
and `apps/web/src/components/recap/*` (range/kind, deltas, scorecard, article links), `tests/` (unit for
grounding/comparison/window, integration for the repository and the router snapshot).
**Implementation plan**: `docs/PLAN_RECAP_NEWSLETTER.md` (PR 1-4).
**Needed from the user**: the recommended defaults listed in the plan's section 7 (no daily-schedule setting,
`rate_limit` left alone, hit-rate rule).
**Done when**: a weekly recap is generated on schedule and shown with its date range; a day can still be generated by
hand; every run records its token usage; the measured input size/tokens per recap is lower than the recorded baseline
(written above, 2026-10-11); a run with no activity makes no LLM call; the page shows the week-over-week deltas, the
dropped-item count from the grounding check and the forecast scorecard; tests cover the weekly window, aggregation,
comparison, grounding and the no-activity path.
**Status of each criterion (2026-10-14)**: weekly recap on schedule with its range, **met** (dev, 12 Oct); a day by hand,
**met** (PR 2); token usage recorded on every run, **met**; lower than the baseline, **met on dev** (-72% total tokens,
table above, repeated after PR 3 with the same result); no LLM call without activity, **met** (`token_usage` =
`skipped`, reason `no_activity`, covered by tests); the page shows deltas, dropped items and the scorecard, **met in the
API output on dev, the page itself not yet looked at there**; tests, **met** (all gates green in each PR).

---

## 22. Newsletter: monthly, Indonesian, redesign, recommended articles (PRIORITY)

> **Priority item, requested by the team on 2026-10-10. Scope decided with the user the same day. Built in PR 5-9
> (#35, #39, #38, #43, #44, plus #37), merged 2026-10-11 to 2026-10-14** (the template was first drawn in
> `docs/mockups/newsletter-redesign.html`). Depends on #21 for the executive summary and for LLM usage logging. The
> "Current state" below is the code **before** those pull requests.

**Implementation status (2026-10-14)**
- **Merged**: PR 5 #35 (summary cache `newsletter_article_summaries` keyed by `(article_id, language)`, a preview with no
  side effects, one history row per send, period columns on `newsletters`, the 3/4/15 tier limits; migration
  `a042eff910ac`), PR 6 #39 (table-based template that no longer extends `_base_email.html`, the logo as an inline
  attachment, Indonesian summaries with a glossary, a subject built from the period), PR 7 #38 (the ranking with reasons,
  `newsletter_suggestions`, `GET /api/newsletter/suggestion` and `POST .../rebuild`; migration `1dbf6006abaf`), PR 8 #43
  (beat entry `newsletter-prepare-monthly`, Monday-Friday 02:00 UTC; the Executive Summary; see
  `docs/ARCHITECTURE.md` section 3.5), PR 9 #44 (the composer opens filled with the suggestion; the old request fields
  `highlight`, `apac`, `global_news` and `indonesia` are removed from the API). #37 fixed the second alembic head that
  appeared when PR 5 and PR 2 were merged in the wrong order. No new setting, no new dependency.
- **Differences from the design below**: a failed summary call **keeps the ranking** (empty summary, `summary_meta.error` holds
  only the exception class and HTTP status, never the message, because it can echo a key; the following weekdays of the
  catch-up window retry only the summary). Recap weeks are used whole, so a month that ends mid-week leaves a tail that is
  **not** in the summary: `summary_meta.uncovered` lists it and the composer warns (the October edition is not affected:
  31 Oct is a Saturday and the week of 26 Oct ends on Sunday 1 Nov).
- **Checked so far**: unit and integration tests with router snapshots in every PR; the template rendered in Chromium; the
  composer in a browser against an isolated local stack (fake LLM, September data, widths 375/1024/1440, both themes).
  **Dev has run PR 1-9 since 2026-10-14, and 0.5.0 with the dark-mode fix since the afternoon of that day** (the api container holds the new modules and `beat` lists
  `newsletter-prepare-monthly`). A suggestion for **September 2026** was built there the same morning (06:35 UTC, by the
  team): 40 articles (3 highlights, 8 full cards, 29 compact rows; 20 APAC, 19 Global, 1 Indonesia), an Indonesian
  Executive Summary of 938 characters, no error and no CVE dropped. It covers only the week of 28 Sep because dev holds one
  weekly recap in September, and `uncovered` says so (1-27 Sep). One quality observation: the first highlight is titled
  like a file name (`2026-09-28-AgtaBackup-RAT-Campaign.txt`), which an analyst would rewrite; the ranking did not filter
  such titles (fixed 2026-10-15, #53: see Open 1).
- **Real draft in Outlook (2026-10-14, screenshots from the team)**: the September draft was created through the real
  Microsoft Graph and opened in Outlook (the new Outlook: Aptos font, rounded window). In **light mode** it is right: the
  logo shows inline without a white panel, the burgundy header, the "September 2026 Edition" label, the period line and
  the Indonesian Executive Summary all render as designed. In **dark mode** Outlook inverted the colours on its own (the
  burgundy header turned a muddy pink, white text turned dark, the cards went grey) because Outlook ignores `color-scheme`.
  The team decided the email needs **no dark mode**, so the template now pins its light palette with the `[data-ogsc]` /
  `[data-ogsb]` overrides Outlook honours (`docs/ARCHITECTURE.md` section 3.6); the fix is on dev since 2026-10-14 and a **new** draft (old ones keep their stored HTML)
  still needs a second look in Outlook dark mode, and Gmail's apps invert on their own and cannot be pinned from the email. Still
  **not verified**: Outlook desktop (classic), Outlook web, and Gmail.
- **Update 2026-10-16**: open items 1 and 2 below are **closed** by the user on 2026-10-15 (the APAC set is confirmed; the Outlook
  dark-mode re-check and the Outlook web/desktop and Gmail screenshots are fine), item 4 is **done** (0.5.0 and then 0.6.0 are on
  prod; `recap-generate-weekly` and `newsletter-prepare-monthly` are registered in `beat`), and the file-name title question is closed
  by #53. What is left: the first real edition (`newsletter_suggestions` is empty on prod, as expected before Mon 2 Nov; if the
  recap of 26 Oct-1 Nov is late that morning, rebuild the suggestion by hand), tuning the ranking weights after it, and the small
  follow-ups in item 5.
- **Open** (as of 2026-10-14, kept for the record):
  1. On dev: let an analyst read the Indonesian wording of the September suggestion, re-check the draft in Outlook dark
     mode after the dark-mode fix is deployed, and capture screenshots from Outlook desktop, Outlook web and Gmail.
     File-name titles: decided and merged 2026-10-15 (#53): a title that is one bare file name (no spaces, a document
     extension) never takes a Highlight slot; the article stays in its section. The source is the `blackorbird` scraper
     (`blackorbird/APT_REPORT` uses the file name as the title); the Newsroom still shows the file name, and cleaning it
     in the scraper is a separate, undecided change.
  2. The team confirms the **APAC country set** in `cti_core/regions.py` (World Bank East Asia & Pacific plus South Asia;
     Central Asia, the Middle East and Russia are out). It is a new decision: the pipeline had no APAC list before. The
     `mentioned` role also holds the actor's country, so a US victim hit by a Chinese actor lands in APAC; that follows
     the "victim or mentioned" rule of the design.
  3. Ranking weights are starting values (constants at the top of `newsletter_ranking.py`); tune them after the first edition.
  4. Prod: the October edition is prepared on Mon 2 Nov at 09:00 WIB and needs the recap of 26 Oct-1 Nov, which the schedule
     creates at 07:15 WIB that morning; if it is late, rebuild the suggestion by hand. Release: 0.5.0 (tagged 2026-10-14) carries both #21 and #22.
  5. Small follow-ups: the composer state is not persisted (a reload refills it from the suggestion and drops edits;
     `localStorage` would fix it), the draft error that names a Graph id has no copy button, and the composer itself is not
     described in `docs/ARCHITECTURE.md` yet (section 3.6 added with this status update).

**Asked (team feedback 2026-10-10)**: (1) biweekly (changed to **monthly** the same day); (2) translate the content to Indonesian; (3) redesign the template;
(4) add recommendations for the newsletter content; (5) "any more suggestions?"

**Decided (user, 2026-10-10)**
- **Monthly, on the first working day of the month** (corrected twice by the user: biweekly, then monthly, then the day
  was set). The last edition went out on 1 Oct 2026 (the September edition), so the next is the **October edition on
  Monday 2 Nov 2026**. There is no fixed send time: an analyst creates the Outlook draft and sends it when ready.
  "Working day" = **Monday-Friday; public holidays are not tracked** (user, 2026-10-11), so there is no holiday list.
- **Edition label = the month it covers** ("October 2026 Edition"), which matches current practice (the September edition
  went out on 1 Oct). No running number, no "week N". The window is the **previous full calendar month**; the label is
  derived from it, so nothing is counted or configured for numbering.
- **Headings are English** (user, 2026-10-10): Executive Summary, Highlights, Asia Pacific, Global,
  Indonesia, Campaigns, Analyst Note. The article summaries and key points under them are Indonesian. The current
  template's labels are already English, so no label translation is needed.
- **Executive summary is a paragraph, not a timeline.** The weekly recaps stay English (#21), so the paragraph needs one
  LLM call per edition to condense them into Indonesian (see Design). Confirmed 2026-10-11: Indonesian for the
  newsletter only, prepared at 09:00 WIB; "Campaigns" is the heading.
- **Company logo** in the header: `https://privy.zmidevelopment.com/_ipx/_/images/Privy_Logo_Red.png` (red logo),
  placed directly on the header **without a white panel** (user, 2026-10-11).
- **Content must stay dense**: the user rejected a small fixed cap per section; see Design: density.
- **Mockup approved** (2026-10-10) and then adjusted for the points above.
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
  into the database** as a side effect of what looks like a preview. `draft-email` commits its row before calling
  Graph, so a failed Graph call still leaves a row (found 2026-10-11).
- Template: `apps/api/src/cti_api/templates/newsletter_email.html` (233 lines) extends `_base_email.html`, which
  `cve_notification_email.html` also extends; headings,
  labels and the title are hardcoded English. It uses `display:flex`, which Outlook desktop (the Word rendering engine)
  does not support, and its rendering in real email clients was never checked (#2, "email client verification not yet").
- `create_graph_draft` (`cti_alerts/mailer.py`) posts only `subject`, an HTML body and CC recipients: no attachments.
- The saved row has `week`/`year` (small integers, `NOT NULL`), `generated_at` (string), the rendered `html` and a
  `sections` JSON; there is no period range and no edition label. The history view (`GET /{id}/html`) and `resend` reuse
  the stored HTML, and `resend` builds its own "Week N" subject.

**Design: monthly schedule**
- **First working day** = the first Monday-Friday of the month. Public holidays are not tracked (user, 2026-10-11): when
  that day is a holiday (1 Jan 2027 is a Friday), the suggestion is simply ready before the analysts are back, and since
  nothing is sent automatically, preparing it early costs nothing. No setting is needed.
- A beat entry runs **every weekday at 09:00 WIB (02:00 UTC)**; the task does something only when today is **within 7
  days of the month's first weekday and** the previous month has no suggestion yet. The beat's first run in a month is
  that first weekday; the following days are the catch-up if the worker was down, so the edition is late rather than
  missing; the 7-day limit stops a mid-month deploy from building a suggestion for a month already sent. After that,
  only the manual rebuild. One suggestion per window makes the task idempotent.
- The task **prepares the suggested content**: the recommended articles (below) already placed in Highlights / Asia
  Pacific / Global / Indonesia, and the Executive Summary paragraph. The analyst opens the Newsletter page,
  reviews and edits, and previews or creates the Outlook draft as today. No Telegram notice and no automatic sending.
- The suggestion is stored **server-side** (a `newsletter_suggestions` row per window: period, the placed article ids with
  their section, tier and reasons, the summary paragraph), because the composer queue today lives only in the browser's
  `localStorage`. When the composer opens and its queue is empty it loads the suggestion; when the analyst already has a
  queue it shows a banner with "use suggestion" / "merge" instead of overwriting their work. Articles added from the
  Newsroom ("+ Newsletter") keep working as now. There is no draft/approved/sent status (not selected).
- Window = the previous calendar month; the campaign clusters use that window (start/end dates, see #21) instead of
  a number of days counted back from today. Replace "Week N" by the **month label and its range**: add `period_start`
  and `period_end` to `newsletters` (migration); the label is derived. `week`/`year` stay `NOT NULL` and new rows keep
  filling them, so old rows and the current history UI keep working. A hand-built edition takes the period from the
  request, defaulting to the previous calendar month in WIB. Subject: `[CTI Newsletter] Threat Intelligence Digest —
  October 2026`, built by one helper used by both `draft-email` and `resend`.

**Design: density (a month of content without a long email)**
- Replace the fixed "max 5 per section" with **depth by rank**: in each section the top few articles (default 4; the
  Highlights block up to 3) get the **full card** (key points + summary), and the rest go into a **compact list**
  ("Also Noted": one row per article with title link, source, date and type, up to about 15 per section). The analyst can
  promote a row to a full card or demote a card, and the numbers above are starting values to tune on the first edition.
- Compact rows need **no Playwright fetch and no LLM call** (title and stored metadata only; a cached summary is used if
  one exists), so a denser newsletter costs fewer calls than today, where every item costs a fetch and an LLM call.
- Size guard: Gmail clips a message whose HTML is larger than about 102 KB, and inline styles make the HTML heavy. The
  build measures the rendered size and the composer warns above about 90 KB before the draft is created.
- `routers/newsletter.py` swaps the 5-per-section check for these two limits (full cards and compact rows per section).

**Design: executive summary**
- **Executive Summary** = one paragraph (about 100-130 words, Indonesian) condensing the weekly recaps whose week
  **overlaps** the month. It is **one LLM call per edition**, which reverses the earlier "no extra call" idea: the recaps
  stay English and the user wants a paragraph, so something has to condense and translate. Input is only the stored
  recap texts; no recommended actions in the output (not selected); the same **grounding check** as #21 (CVE ids, actor
  names and campaign names must appear in the input) runs on it. The paragraph is saved in the suggestion and shown in
  an **editable field** in the composer, so the analyst corrects it like the rest of the draft. Missing recaps: the
  field is left empty, not generated from raw articles. The call is logged with its token usage (#21).
- Only weekly recaps that **exist** on the first working day are used, and the weeks used are stored with the
  suggestion. When the month does not end on a Sunday, its last days are in a week that is not finished yet (November
  2026 ends on Monday 30 Nov, and that week ends 6 Dec, after Tuesday 1 Dec), so they are not in the summary; they are
  still in the recommended articles. No daily recap is generated to fill the gap. Rebuilding the suggestion by hand also
  redoes the summary (e.g. when the Monday recap was late).
- The Executive Summary block in the template shows the composer's existing intro field, so a hand-built edition can
  carry a summary before the suggestion exists, and the suggestion only pre-fills that field.
- There is **no statistics block** in the newsletter (**By the Numbers** was drawn and then dropped by the user,
  2026-10-10): no monthly counts and no deltas, so nothing is counted from the database for the edition. The
  week-over-week comparison stays in the Recap page (#21).

**Design: Indonesian content**
- Generate `key_points` and `summary` **in Indonesian in the same LLM call** as today (prompt change; no second
  translation call, no extra cost per article). Keep CVE ids, product names, threat actor names, ATT&CK technique names
  and IOCs untranslated; give the prompt a short glossary of recurring terms so wording stays consistent between
  editions. Headings, labels, subject and footer stay English. A `language` field (default `id`, `en` still possible)
  goes on the build request and into the cache key, so an English edition is not lost.
- Article **titles** keep their original wording by default (links, searching); a translated line under the title is
  possible later. The analyst's own intro and notes are used as typed. Quality check: the analyst who reviews the
  suggested draft also reads the Indonesian wording; corrections go into the glossary so later editions improve.

**Design: template redesign**
- Drawn in `docs/mockups/newsletter-redesign.html` (sample data, brand palette). It is built the way the real template
  must be built: a `table` layout with inline styles, a 640 px container, a fallback font stack, solid colours instead of
  the CSS gradient, a hidden preheader line, and a stacked layout under 480 px, so it can become `newsletter_email.html`
  without a second redesign.
- Structure: header with the **company logo**, the edition label and the date range; **Executive Summary** (paragraph);
  **Highlights**; **Asia Pacific**, **Global** and **Indonesia** sections (full cards
  plus the compact "Also Noted" list); **Campaigns**; footer. The colour coding per section is kept (Asia Pacific blue,
  Global purple, Indonesia red).
- **Logo**: the PNG has a transparent background and sits directly on the burgundy header, without the white panel the
  first mockup had (user, 2026-10-11). For the real email, prefer an **inline (CID) attachment** on the Graph draft over a link to the company domain: Outlook blocks
  linked images until the reader allows them, and a link breaks if that domain changes. That means the PNG lives in the
  repo (a static file next to the template) and `create_graph_draft` gains an inline attachment parameter
  (`fileAttachment` with `isInline` and `contentId`). Email clients do not render SVG, so a PNG is needed even if an SVG
  logo exists (#1). The logo URL could not be reached from the sandbox on 2026-10-10 and could on 2026-10-11 (PNG,
  about 60 KB), so the template PR adds the file to the repo, scaled down for a 28 px display height; until then the
  mockup links the URL directly. The stored HTML keeps the `cid:`
  reference, so the history view maps it to a data URI when serving a saved row and `resend` attaches the image again.
- `_base_email.html` is shared with the CVE notification email, so the newsletter template stops extending it instead
  of changing it.
- Acceptance includes screenshots from Outlook desktop, Outlook web and Gmail attached to this item.

**Design: recommended articles (request 4)**
- When the composer opens, and when the monthly draft is built, rank the candidate articles of the window with signals
  already stored: `confidence_score`, `confirmed_incident`, KEV/PoC on the CVEs they mention, a hit on a **monitored
  tech** (#19) or on a client country, source reliability, cluster size, APAC / Indonesia relevance, with
  duplicate stories collapsed. The newsletter is global, so the client signals use the union over all clients. Clients
  have countries but **no industry field**, so there is no industry signal. Suggest the Highlights, the full cards and
  the compact rows per section (the rank decides the tier), show **why** each was suggested (the signals), and let the
  analyst accept, swap or remove. The suggestion never sends anything by itself.

**Design: approved additions**
- **Executive summary from the weekly recap**: see Design: executive summary.
- **Summary cache and one row per send**: cache each article's `key_points` / `summary` (a table keyed by article id and
  language, or persisted at enrichment time) so `preview` and `draft-email` never redo Playwright + LLM. The cache also
  keeps the IOCs and CVE ids found in the fetched body, because the draft step writes them and would otherwise have to
  fetch the page again. `preview` does not save a row and does not write IOCs/CVE mentions (it only fills the two
  caches: summaries and paywall hints); the single save happens after the Outlook draft is created, so a failed Graph
  call leaves no row, and a second preview of the same articles makes no new LLM or Playwright calls.

**Touch points**: `services/newsletter.py`, `routers/newsletter.py` (including `GET /{id}/html` and `resend`),
`schemas/newsletter.py`, `templates/newsletter_email.html` (no longer extending `_base_email.html`) and the logo file,
`cti_alerts/mailer.py` (inline attachment), `services/campaign.py` (window, from #21),
`db/models/newsletter.py` + migration (a summary cache table and `newsletter_suggestions`),
`repositories/newsletter.py`, `beat.py` + a new task, a new ranking service (no new setting),
`apps/web/src/components/newsletter/*` (suggestions, tiers, editable summary, size warning), `openapi.json` +
`schema.d.ts`.
**Needed from the user**: the recommended defaults listed in the plan's section 7 (`docs/PLAN_RECAP_NEWSLETTER.md`,
PR 5-9). Answered 2026-10-11: the logo URL (no white panel), the "Campaigns" heading, the Indonesian summary at 09:00
WIB, and no holiday list.
**Done when**: suggested content is prepared on the first working day of each month, already placed in the sections
and tiers, and the composer loads it for review while the Newsroom picking flow still works; every edition carries the
month label and its date range and the company logo; summaries are in Indonesian, headings in English; the new template
renders correctly in Outlook desktop, Outlook web and Gmail (screenshots attached here) and stays under the size limit;
the composer shows recommended articles with their reasons; one send creates exactly one history row; a second preview
of the same articles makes no new LLM or Playwright call; the Executive Summary is one grounded paragraph and editable;
tests cover the language switch, the first-working-day and catch-up logic, the period label, the ranking and tiers, the
cache, the grounding check and the no-duplicate-row case.
**Status of each criterion (2026-10-14)**: suggested content prepared on the first working day, **code and tests merged, the
scheduled run itself not yet seen** (first real one: Mon 2 Nov; rebuild by hand to try it earlier); the composer loads it
and the Newsroom flow still works, **met** (browser check, local stack); month label, range and logo on every edition,
**met in code, and the inline logo was seen in the new Outlook (light mode, 2026-10-14)**; Indonesian summaries under English headings, **met in code, wording not
yet reviewed by an analyst**; screenshots of a real draft: **new Outlook in light mode done (2026-10-14), dark mode
fixed and waiting for a re-check, Outlook desktop / Outlook web / Gmail not done**; the size limit on a real draft, **not
measured**; recommended articles with their reasons, **met**; one send, one history row, and a second preview with no
new LLM or Playwright call, **met** (integration tests); an Executive Summary that is one grounded, editable paragraph,
**met**; the listed tests, **met**.

---

## 23. Runtime secrets: manage third-party keys from the admin UI

**Asked (2026-10-16)**: is it safe to manage the third-party keys (LLM vendor, Twitter API, OTX, ...) from an admin menu
for operations (change a key, and so on)? Pros and cons first, then a plan. Clarified in the same conversation: the
product is becoming multi-workspace (SaaS), so the keys that change often must be changeable **without a restart or a
rebuild**; the deployment-level secrets (database, Redis, JWT/session, OIDC) are initial-deployment config that rarely
changes and stay in `.env`. Not the same as #5 (that is about keys **we issue** to other tools); this item is about the keys
we **use**. It also makes the keys needed by #4 (AbuseIPDB, VirusTotal, OTX) changeable without touching the prod host.

**Status 2026-10-23 -- live.** PR #63 merged 2026-10-16 (`242bdb7`), tag `0.7.0` and GitHub Release `v0.7.0`; prod runs 0.7.4
with `SECRETS_ENCRYPTION_KEYS` set and one admin override in `runtime_secrets` (`llm`). Left: confirm once with a real OTX key that
the `users/me` probe answers 200 (only the rejection of a fake key is proven); the re-auth decision for OIDC-only superadmins; the
two open points at the end of "Delivered as ONE pull request" (re-encrypt on master key rotation, an old token replayed from a
backup). The rest of this section describes the plan as written before the build.

**Current state** (facts from the repo before the build):
- Every third-party key lives only in `.env` and is read through `get_settings()` (`lru_cache`, per process,
  `packages/cti-core/src/cti_core/config.py`). Changing one means editing the file on the host and restarting `api`,
  `worker`, `worker-browser`, `worker-nlp` and `beat`.
- The read points already resolve the key **when it is used**, not at import: `cti_scraper/credentials.py`
  (`resolve_credential_headers`, called per run by `Runner`), `cti_core/llm/client.py` (`get_llm_client` builds a new client on
  every call), `cti_alerts/telegram.py` (a `Bot` per send), `cti_alerts/mailer.py` (an MSAL app per call),
  `services/ioc_enrichment.py` (`build_specs`, called from `tasks/periodic.py`) and `services/newsletter_summary.py` (log
  scrub). That is why a hot reload needs one overlay on `Settings` and not a rewrite of the consumers.
- Tenancy today: the `clients` table and a `client_id` on the analysis tables (techstack, PIR, RFI, CVE tracker, IOC, TA).
  Ingestion, the LLM, Telegram and Graph are global singletons (one key, one bot, one chat, one sender).
- Building blocks that exist: `require_superadmin`, the `audit_log` table, the singleton precedent `PasswordPolicy`, the
  current-password re-check in `routers/auth.py` (change password), `rate_limit.is_rate_limited`, the read-only provider probes
  in `tools/ops/check_secrets.py` (LLM, Telegram, NVD, GitHub, twitterapi.io, X; Graph is only reported as set), and the admin
  page `apps/web/src/app/(app)/admin/users` made of sections. `psycopg[binary]` is already a `cti-core` dependency;
  `cryptography` is only transitive (through `python-jose` in `apps/api`).
- `SECRETS_BACKEND=vault` is accepted by `Settings` but no Vault reader exists.
- An existing gap, independent of this item: `_scrub_secrets` in `tasks/enrich.py` does not cover `x.bearer_token`, `otx`,
  `abuseipdb` or `virustotal`, so those can still appear in an error message.

**Decision record (2026-10-16)**
- Pros: a leaked key is rotated in minutes without SSH or a restart; fewer people need a shell on the prod host; the page
  shows which providers are filled and whether the key is still accepted (an empty key silently turns a provider off today);
  there is an audit trail; a mistyped key is caught before it goes live.
- Decided with the user: **platform scope first** (the operator holds every vendor key; per-workspace keys, BYOK, are not built,
  but the table keeps a nullable `client_id` so they can follow additively) and **superadmin only**.
- Risks and how the design answers them:

| Risk | Answer in the design |
|---|---|
| One stolen superadmin session reads or rotates every key; writing is worse than reading (pointing `LLM__URL` at an attacker host sends all article text there, a swapped Telegram token redirects alerts) | the API never returns a secret value; the **current password is required on every write and delete**; audit; rate limit; an allowlist for the LLM URL |
| Keys land in Postgres and in its backups | Fernet encryption at rest; the master key lives only in `.env` (later Vault), kept apart from the DB backups, so a backup alone opens nothing |
| Two sources of truth (`.env` and the database) make "which key is live?" hard to answer | DB over `.env`, a `source` shown per provider (db / env / unset), and a "Revert to .env" action |
| Five long-lived processes each cache their settings | an overlay with a 30-second per-process cache; no restart |
| New leak surfaces: responses, logs, error text | no secret in any response or audit row; one helper builds the scrub list for all providers (also closes the existing gap above) |
| A wrong key stalls the pipeline or bills the wrong account | the candidate key is probed **before** it is saved; a failed probe means nothing is stored |
| SSRF through a custom LLM URL once admins other than the operator exist | outside `dev` only hosts in an env allowlist, https only |
| Bootstrap secrets cannot live in the database they unlock | they stay in `.env` |
| Conflict with the planned Vault | `overlay.py` is the seam where a Vault reader plugs in later |

**Design (agreed 2026-10-16)**
- **Table `runtime_secrets`** (`cti_core/db/models/runtime_secret.py` + a hand-written migration after head `a3d91c5e7b24`):
  `provider`, `client_id` (nullable FK to `clients`, NULL = platform, only NULL is written in this item), `secrets_enc`
  bytea (NOT NULL; a Fernet token of `{provider, client_id, fields}` holding **every** overridden field, secret or not,
  so there is no plaintext column an attacker with write access to the database could use to change behaviour, for
  example by pointing `llm.url` at their own host; provider and `client_id` are checked on decrypt),
  `updated_by`, `updated_at`, `last_test_ok`, `last_test_at`. Two partial unique indexes (platform: `provider`; client:
  `client_id, provider`).
- **Overridable fields** (one registry, `cti_core/runtime_secrets/registry.py`): `llm.api_key|provider|model|url`,
  `telegram.bot_token`, `graph.client_secret`, `nvd.api_key`, `github.token`, `twitter.api_key`, `x.bearer_token`,
  `otx.api_key`, `abuseipdb.api_key`, `virustotal.api_key`. Deliberately **not** editable from the page: the Telegram chat and
  thread ids, the Graph identity (tenant, client, sender, cc), rates and timeouts. Those are deployment decisions or change as
  one set; they stay in `.env`.
- **Crypto**: `MultiFernet` built from `SECRETS_ENCRYPTION_KEYS` (comma-separated; the first key encrypts, all of them
  decrypt, so the master key can be rotated without a data migration). `cryptography` becomes a direct `cti-core` dependency.
- **Overlay** (`cti_core/runtime_secrets/overlay.py`): `effective_settings()` is `get_settings()` plus the database overrides,
  cached per process for 30 seconds (`invalidate()` in the process that just wrote). The loader is synchronous through
  `sync_session()`. It never raises, and it **serves stale rather than reverting**: if the database cannot be read it keeps
  the last healthy overrides (so a database blip never brings back a key that was already revoked) and retries after
  10 seconds; only a process that has never had a healthy snapshot falls back to `.env`. A row that cannot be decrypted
  skips that provider (keeping its previous override if there was one) and the others carry on. A refresh never makes
  another thread wait, and `invalidate()` does not wait for I/O. The sync engine gets a 5-second `connect_timeout`
  because this loader runs on the API event loop. A field that has no override falls back to `.env`; an empty
  non-secret field is a real override ("vendor default", so `llm.url=""` replaces a gateway URL in `.env`), while an empty
  secret is ignored.
- **Consumers** change only their default expression `get_settings()` to `effective_settings()`: `cti_alerts/telegram.py`,
  `cti_alerts/mailer.py`, `cti_core/llm/client.py`, `cti_scraper/credentials.py`, the settings handed to `build_specs` in
  `tasks/periodic.py`, `services/newsletter_summary.py`. The two scrub sites use `scrub_candidates()`: the `.env` values **and** the overridden ones (a key that was just rotated can still appear in an error from a call that was already running), longest first, never raising, and the master keys included.
- **API** (`routers/secrets.py` + `services/runtime_secrets.py`, all `require_superadmin`): `GET /api/secrets` (per provider:
  `source`, non-secret fields as they are, secret fields only as `set` plus the last four characters, `updated_by/at`,
  `last_test`); `PUT /api/secrets/{provider}` with `{fields: {name: value | null}, current_password}` (a string sets, `null`
  removes the override, an absent field is unchanged, an **empty string is rejected** so a working `.env` key is never
  overwritten with a blank; the order is registry check, LLM URL check, probe the candidate, encrypt, upsert, invalidate, audit);
  `DELETE /api/secrets/{provider}` (also needs the password); `POST /api/secrets/{provider}/test`. Audit actions `secret_set`,
  `secret_clear`, `secret_test`, `secret_set_rejected`, `secret_reauth_failed` with `target_id=provider`; `secret_set` carries
  `detail={fields, values}` where `values` are the non-secret fields only (so the new `llm.url` can be traced), never a secret.
- **LLM URL guard**: outside `dev`, only hosts listed in `SECRETS_LLM_URL_ALLOWED_HOSTS` (empty by default, so the page cannot set a
  custom URL in prod) and only https; in `dev` anything goes (local gateways such as 9router).
- **Probes** move from `tools/ops/check_secrets.py` into `apps/api/.../services/secret_probes.py` (the API image does not ship
  `tools/`); the CLI stays and keeps exporting `run_checks`, `CHECKS`, `Result`, `exit_code` and `main`, and
  `tests/unit/test_check_secrets.py` (it mocks HTTP with `respx`) is the regression net. Add an API-only Graph probe that
  only acquires a token (it never creates a message). AbuseIPDB and VirusTotal are probed with the production lookup of
  `8.8.8.8` (no verifiable "check key" endpoint exists, and it tests the real code path; it costs one lookup of the daily quota,
  so the Test endpoint has a 30-second cooldown per provider). OTX is probed with `GET /api/v1/users/me` because its indicator
  lookup is public (a fake key also gets 200: confirmed with a live request); that endpoint rejects a fake key with 403, and
  its answer for a valid key should be confirmed once with the real key on prod.
- **Web** (`apps/web/src/components/admin/secrets-section.tsx` plus an edit dialog): one card per provider with the source
  badge, the masked tail, Test, Edit and "Revert to .env". Password inputs, `autocomplete="new-password"`, never pre-filled,
  cleared on close and on submit. Mounted for `superadmin` in `admin/users/page.tsx` like `ClientsSection`. Follow
  `apps/web/CLAUDE.md` (Base UI: `render=`, not `asChild`; a `SelectItem` takes one string).
- **New config** (both optional, empty by default, so a deploy never fails on them): `SECRETS_ENCRYPTION_KEYS`,
  `SECRETS_LLM_URL_ALLOWED_HOSTS`; update `.env.example`, `.env.prod.template`, `tests/unit/test_config.py` and
  `tests/unit/test_env_prod_template.py` in the same commit. Without a master key writes are refused (503), the overlay reads
  nothing, and behaviour is exactly today's.

**Delivered as ONE pull request** (decision 2026-10-16: do not split this roadmap item), in this order inside the branch: the
core (dependency, config, model and migration, registry, crypto, overlay, consumers switched, scrub list widened), the API
(probes extracted, service and router, audit, re-auth, rate limit, `docs/openapi.json` and `schema.d.ts`), the web section,
the docs, and the `chore(release): 0.7.0` commit (version bump and `CHANGELOG.md`, as the release convention asks). Findings
from the agent reviews that shaped the final code (all fixed in the branch): serve-stale instead of reverting to `.env` on a
database error; every overridden field inside the authenticated blob (no plaintext column); a shared per-user failure counter
with session revocation, because `POST /api/auth/change-password` had no limit and would have let a stolen cookie guess the
password; an advisory lock per provider; the OTX probe moved to `users/me` (its lookup endpoint answers 200 without a key);
the URL allowlist re-checked on every `llm` write; the `httpx` log level lowered in the Celery worker too; and the server's
error messages actually reaching the UI. Still open: nothing re-encrypts rows when the master key is rotated (a
`MultiFernet.rotate` helper), and an old token replayed from a backup is accepted (no version in the payload).

**Touch points**: `packages/cti-core/src/cti_core/{config.py, runtime_secrets/*, db/models/runtime_secret.py,
db/models/__init__.py, db/repositories/runtime_secret.py, llm/client.py}`, `alembic/env.py` (model import) and
`alembic/versions/` (new revision), `packages/cti-alerts/src/cti_alerts/{telegram.py, mailer.py}`,
`packages/cti-scraper/src/cti_scraper/credentials.py`, `apps/worker/src/cti_worker/tasks/{enrich.py, periodic.py}`,
`apps/api/src/cti_api/{routers/secrets.py, services/runtime_secrets.py, services/secret_probes.py,
services/newsletter_summary.py, main.py}`, `tools/ops/check_secrets.py`, `.env.example`, `.env.prod.template`,
`pyproject.toml` of `cti-core` and `uv.lock`, `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`,
`apps/web/src/components/admin/secrets-section.tsx`, `apps/web/src/app/(app)/admin/users/page.tsx`.
**Needed from the user**: a go-ahead per pull request; for prod, a generated Fernet key set as `SECRETS_ENCRYPTION_KEYS` in the
prod `.env` before the API and UI are used (pull request 1 is safe without it), and `SECRETS_LLM_URL_ALLOWED_HOSTS` only if a
custom LLM gateway is wanted; whether any prod superadmin signs in **only** through OIDC (see the assumptions); the quota
limits of the AbuseIPDB and VirusTotal plans, for the probes.
**Done when**: a superadmin can set, test and revert every provider above from the admin page, and a key changed there is
used by the next scraper run, LLM call, Telegram send and IOC lookup within 30 seconds **without restarting any service**
(shown on the dev instance); no endpoint response, log line or audit row contains a secret value (tests assert it) and `psql`
shows `secrets_enc` is not plaintext; an admin who is not a superadmin gets 403, a wrong password is refused, and a candidate
key that fails its probe is not saved; with no master key set the behaviour is identical to today; a database restored without
the master key leaves the platform running from `.env`; the scrub list covers every provider; all repo gates are green and
`docs/openapi.json` and `schema.d.ts` do not drift.
**Not in scope**: per-workspace keys (BYOK) and the client-aware enrichment and alert consumers they would need, the Vault
reader (`overlay.py` is its seam), editing the deployment-level secrets from the page, Telegram chat and thread ids, the Graph
identity, rates and timeouts, a version history of keys (rollback is "Revert to .env" or typing the old key again; the
probe-before-save already covers a mistyped key), and turning off a provider whose key is in `.env` from the page.
**Assumptions to confirm**: Telegram is limited to `bot_token` and Graph to `client_secret` because rotation is the operational
need (moving the chat or the sender stays a deploy decision); re-auth uses the local password, and a superadmin who signs in only
through OIDC may have none, so check `OIDC__ENABLED` on prod and pick a fallback (for example a fresh login within a few
minutes) before pull request 2; the section lives on the existing admin page and is easy to move to its own route.

---

## 24. Data platform audit follow-ups: do not lose articles, show the pipeline's health

**Asked (2026-10-17)**: audit the data platform end to end, check whether the dev UI is informative, then plan the fixes. This item
records the audit and the plan for two pull requests. **Status 2026-10-23: PR-A merged 2026-10-21 (#65, `d2332ab`, tag `0.7.2`)
and deployed to dev (2026-10-21) and prod (0.7.4, head `b7e4c1a9d256`). Decisions 1-3 below were taken as recommended (silent
replay with `--rate`, 90 days / 2 hours, CLI and admin button). Replay: on dev the user ran a first batch (10 of 147
`permanent` rows) on 2026-10-21; on prod it has not been run (38 rows wait: 34 `transient`, 4 `permanent`). PR-B is not started.** How the facts were gathered: the dev database over SSH
with `default_transaction_read_only=on` (aggregates only, no row contents, no writes), the dev UI through the user's signed-in Chrome
(GET only, no button that writes or triggers a run), and the code at `6a5734a` (0.7.1). The dev instance is three weeks old (first
scraper run 2026-09-26), so trends over a longer time are not visible yet.

**Current state** (dev instance, 2026-10-17 around 04:45 UTC):
- **Articles are lost without a trace.** On 2026-10-16 all 101 `[enrichment_failed]` rows were written with `BadRequestError 400
  "Unsupported model mimo-auto"`: 0 before that day and 0 since 2026-10-17 00:00 UTC (the newest article arrived at 00:50 UTC), so it
  looks stopped but is not proven fixed. Over 7 days: 237 articles accepted, 35 classifier rejects, 101 failures (27% of what was
  processed). By source: hackernews 31, darkreading 14, bleepcomp 13, huntress 10. The only marker is a text prefix in
  `rejected_articles.reason` (`apps/worker/src/cti_worker/tasks/enrich.py:107`); the only signal is the 23:55 daily counters message
  (`debug` topic); there is no alert and no replay.
- **The only recovery path does not do what the UI says.** Newsroom > "Not Related Cyber" lists the 101 together with 259 classifier
  rejects (360 items), shows no reason, and says "Articles LLM classified as not cyber-related. Restore to re-queue through NLP
  pipeline." But `restore` only creates an `Article` with `news_type="Manually Restored"` and no enrichment
  (`packages/cti-core/src/cti_core/db/repositories/article.py:671-686`), leaves the rejected row in the list, and the stub then makes
  `_known_article` (`packages/cti-enrich/src/cti_enrich/pipeline.py:153-167`) short-circuit any later re-run of that URL.
- **A run can be `ok` while its items fail.** 108 runs with status `ok` and `items_failed>0` in 7 days (590 items: `github_poc_monitor`
  558 in 96 runs, `tweet_alerts_1h` 39, `tweet_alerts_30m` 6); `/scrapers` shows `github_poc_monitor` as OK although the same 4 items
  fail every hour. `runner.py:220` starts every run at `ok` and the sink-failure path (`:475-489`) never changes it; `compute_health`
  reads only the status of the latest 3 runs. Failed items retry forever because `release()` deletes the dedup row. The likely cause on
  dev is the topic `github_poc` missing from `TELEGRAM__THREAD_IDS` (the Items tab shows `UnknownAlertTopic`; unverified).
- **Orphans and growth.** 8 runs sit in `running` for more than an hour (the oldest since 2026-09-26 04:21). `scraper_runs` has 25,864
  rows (about 1.2k a day, 8.9 MB) and no purge. `celery_task_id`, `worker`, `attempt>1` and status `timeout` are 0 of 25,864. The setup
  code in `_run_body` (`runner.py:222-285`) runs outside the `try`, so an exception there leaves the row `running`.
- **The Dashboard delta is misleading.** "Total Articles 855 ▲ +852 vs prev 30d" and "Confirmed Incidents 316 ▲ +316" while the
  previous 30 days hold 3 articles. The Exec page, for the same data, says "no prior-period data" because it has
  `prev_period_reliable` (`services/exec_dashboard.py:58,140,180`); `article_dashboard.py` has no such flag.
- **No page except `/scrapers` shows pipeline health.** X Intel's newest tweet was fetched 2026-10-02 (`monitor_x` fails with
  `parse_error`, `tweet_alerts_*` are disabled) and the page does not say so. On `/scrapers`: the Items tab's Accepted column is empty
  (`apps/web/src/components/scrapers/scraper-items-panel.tsx:88` renders `""` for both branches since commit `9a0fc73`; the same bug is
  at `intelligence/campaign-clusters/geopolitical-panel.tsx:68`), the Runs tab shows `927361ms` and no error column, DISABLED has no
  reason (the list payload has no `paused_reason`), and the table shows every enabled scraper as "ok" while the health query is still
  loading. IOC enrichment coverage is partial and invisible (domain 379 of 1,206, ip 177 of 716, sha256 308 of 829, md5 167 of 295,
  url 0 of 742). Article coverage is 198 of 855 with a country and about 81 with an actor.
- **Performance is not a problem yet** (EXPLAIN ANALYZE on dev: `DISTINCT ON` over `scraper_runs` 22 ms, `articles ORDER BY posted_on`
  0.5 ms, `cve_records` by severity 0.7 ms). The missing indexes are real in the schema but are listed under "Not in this item".
- **Guesses the data disproved** (do not "fix" them): the five scrapers with no run since 2026-10-01 (`google`, `blackberry`, `cisa`,
  `nquiring_minds`, `koisec`) are deliberate `enabled=False` waivers shown correctly as DISABLED; domain IOCs stored defanged are by
  design (`ioc_enrichment.py:189` refangs before a provider lookup); the weekly recap stopping daily rows at 2026-10-10 is by design
  (#21).

**Reproduce the numbers** (read-only, on the host: `docker exec -e PGOPTIONS="-c default_transaction_read_only=on" ... psql -U cti -d cti`):
`select count(*), count(*) filter (where reason like '[enrichment_failed]%') from rejected_articles;` ·
`select count(*), sum(items_failed) from scraper_runs where status='ok' and items_failed>0 and started_at > now()-interval '7 days';` ·
`select count(*) from scraper_runs where status='running' and started_at < now()-interval '1 hour';` ·
`select count(*) filter (where posted_on >= current_date-30), count(*) filter (where posted_on >= current_date-60 and posted_on < current_date-30) from articles;`

**Update 2026-10-21 (before building PR-A).** The user took all four recommendations below. Read-only checks first:
- **Prod** (0.7.0, head `a3f81c2d9b47`, effective LLM `openrouter/free` set from the admin page): no mass failure like dev's, but
  3 `[enrichment_failed]` rows on 2026-10-20/21 (cybersecnews, qualys, wiz), all `TypeError: 'NoneType' object is not subscriptable`
  at `extract_ttps.py:95`: the gateway answered 200 without `choices`, `TypeError` is not retried, so the articles were lost. The same
  unguarded `completion.choices[0]` is in `classify.py`. Fixed as the first commit of PR-A (`first_choice()` raises
  `EmptyLLMResponse`, which the task retries like a 5xx). Prod also has 10 `ok` runs with failed items in 7 days, 6 runs stuck `running`
  and 51,319 `scraper_runs` rows (25 days, about 2k a day).
- **Dev** was down for a while (no Vareon containers; the user started it again the same day). Read-only checks afterwards (0.7.1,
  head `a3f81c2d9b47`, so PR-A is not deployed there): the failures did **not** stop. `[enrichment_failed]` rows by day: 16 Oct 101,
  17 Oct 1, 19 Oct 27, 21 Oct 9, all `BadRequestError ... Unsupported model mimo-auto`, against 35, 18, 20 and 3 accepted articles
  (more than 70% lost on 21 Oct). The app sends `LLM__MODEL=my-combo` to the 9router gateway (`172.25.1.77:20128`), not `mimo-auto`:
  the combo routes some requests to a member that the upstream rejects. Five probe calls from `worker-nlp` gave 4 failures and 1 success
  (served by `minimax/minimax-m3.1-flash:free`). So the cause is the combo in 9router, outside this repository, and a replay on dev must
  wait until that member is removed and a fresh probe passes. The earlier statement that the failures "look stopped" was wrong (it
  rested on 4.7 hours of data of the new day). **The user removed `mimo-auto` from the combo the same day** (08:0x UTC): a new probe
  gave 10 successes out of 10 (served by `@cf/deepseek-ai/deepseek-r1-distill-qwen-32b`), the last failure is at 08:01:26 UTC, and 4
  articles were accepted afterwards without a failure. The 138 failed rows on dev are waiting for PR-A to be deployed and replayed.

### PR-A: do not lose articles, do not report a false OK (backend + the Newsroom tab)

Commits, in order (each one keeps `main` green; one migration):
1. **`failure_kind`.** A nullable `rejected_articles.failure_kind VARCHAR(30)` (`NULL` = the classifier rejected it; `transient`,
   `json` or `permanent` = enrichment failed). A hand-written migration after head `a3f81c2d9b47` that backfills from the existing
   prefix (class name after `[enrichment_failed]`: connection, 5xx, rate-limit and DB errors = `transient`; `JSONDecodeError` =
   `json`; anything else `permanent`), and the model change in `models/article.py:203-238` (the drift test compares both).
   `RejectedArticleRepo.upsert` gets a `failure_kind` argument that **always overwrites**, `None` included, so a replayed article
   that the classifier then rejects clears it (`persist_rejected` passes `None`). `_record_enrichment_failure` derives the kind
   from `einfo.type` with the same exception sets the retry policy uses. The prefix stays in `reason` for one release, and
   `reports/daily_counters.py` counts `failure_kind IS NOT NULL OR prefix` so a rolling deploy cannot undercount. While on those
   lines, scrub secrets before truncating the message (today it is cut to 300 characters first). Update `docs/ARCHITECTURE.md`
   (the three places that describe `[enrichment_failed]`).
2. **Alert.** After the upsert, in its own `try/except` so it can never mask the original failure: a Redis `SET cti:enrich:failed_alerted
   NX EX <cooldown>` guard (the pattern in `beat_watchdog.py:74`), then one message to the existing `scraper_health` topic (no new
   key on the prod host) with the error class, the first 200 escaped characters and the number of failures still waiting for a replay.
   New setting `worker.enrich_failure_alert_cooldown_min` (default 60) with `.env.example`, `.env.prod.template` and the two env
   tests updated in the same commit; the existing task-failure tests get an autouse stub for Redis and Telegram.
3. **Replay tool.** `tools/ops/replay_failed_enrichment.py` (+ a Makefile target and `tests/unit/test_ops_makefile.py`), report-only by
   default, `--apply` to enqueue. Filters `--kind`, `--since`, `--source`, `--limit`, `--rate` (messages per minute). It enqueues
   `enrich.article` with the five keyword arguments the sink sends (`title`, `url`, `posted_on` ISO or `None`, `source`, `scraper_id`),
   after `ensure_enrich_capacity`. Plan categories: `enqueue`, `skip_article_exists`, `stub_restored` (an analyst already restored it,
   so a replay would silently do nothing; handled only with an explicit `--replace-restored-stubs`, which deletes the stub article,
   a cascade that nulls `iocs.article_id`). It prints a reminder to prove the LLM works first. A successful replay deletes the failed
   row by itself (`persist.py:161-165`); a replay the classifier rejects keeps a row with `failure_kind` cleared; a replay that fails
   again keeps the old `rejected_at`.
4. **API and the Newsroom tab.** `RejectedArticleOut.failure_kind`; `GET /api/filtered-articles?kind=unrelated|failed|all`;
   `POST /api/filtered-articles/{id}/replay` behind `require_admin` (it spends LLM quota and sends alerts), answering 409 when the
   article already exists, and written to the audit log; `restore` refuses a failed row with a 409 that points to Replay. Regenerate
   `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts` and the syrupy snapshot
   `test_filtered_articles_router_snapshot.ambr`. `apps/web/src/components/newsroom/filtered-view.tsx`: a `TabPills` switch "Not
   cyber-related" / "Failed enrichment", show `reason`, an honest hint per tab (the current text is wrong), a Replay button with a
   per-row `aria-label`, an `onError` toast (the server's 404/409 text is discarded today), `useDebounced` + `usePageResetOn` for
   the search, and an `aria-label` on the search input.
5. **An honest run status.** In `runner.py` right after the success path (`:319`): `if result.items_failed and result.status == "ok":
   result.status = "partial"`, with the final-status decision pulled into a pure function so it can be unit-tested (dry-run returns
   before `_handle_item`, so the current unit tests cannot reach it). `partial` is chosen on purpose: it is already terminal, a success
   status for `cve_check` and the web freshness code, not retried, and has a warning style; a new status name would not fit
   `String(20)`, would be rejected by `_finish_fields` and would count as failed in `new_cve` freshness. Wrap the `_run_body` setup
   (`:222-285`) in the `try` so `finish()` always runs. `health.py::compute_health`: skip `running` rows when picking the latest run;
   `degraded` when the latest finished run is failing (a bad status **or** `items_failed>0`); `ScraperHealthEntry` and
   `ScraperHealthEntryOut` gain defaulted `reason`, `items_failed_last`, `consecutive_failing` and `last_success_at` (one grouped
   query in both repo twins, not the 3-run window). The Telegram digest (`tasks/scrape.py:148-185`) is stateless today and would
   repeat the same alert every 30 minutes; give it a Redis `SET NX EX` window per problem set (`worker.scraper_health_repeat_min`,
   same template/test updates). Fix the sentence in `docs/SCRAPER_MAINTENANCE.md` that says `partial` "does not make the scraper
   degraded". Tests: add the first unit tests for the `dead`, `degraded` and `zero_yield` thresholds (the existing helpers use
   `SimpleNamespace(status, started_at)`, so read `items_failed` with `getattr`).
6. **Reaper, purge, populated columns.** `scraper.reap_stale_runs` every 30 minutes on `maintenance`: `running` rows older than
   `worker.scraper_run_stale_hours` (default 2, above the 3600 s visibility timeout) become `timeout` with
   `errors=[{"stage":"reaper","type":"StaleRun"}]` and `finished_at` left NULL (stamping it would make an old row look like the
   latest result in `/api/cve/freshness`). `scraper.purge_old_runs` at 03:05: rows older than `worker.scraper_run_retention_days`
   (default 90, never below the 30-day item retention because `scraper_items.run_id` cascades) and never `running`. Runner
   constructor keywords `celery_task_id`, `worker` and `attempt` (not `execute()`, whose signature the retry test fakes), passed from
   `run_scraper`. These are the first tests of any purge.

**Release**: one pull request, suggested **0.7.2** (a fix release: one migration, no new page); version, `CHANGELOG.md`, `uv.lock`,
`docs/openapi.json` and the health snapshot ride in it per the release convention.

### PR-B: show the pipeline's health (a small API + the web)

Starts after PR-A is merged (it reads `failure_kind`).
1. **Dashboard.** `DashboardStats.prev_period_reliable`, computed in `article_dashboard.py` with
   `distinct_day_count(**prev_filters) >= days * PREV_MIN_DAY_COVERAGE` (import the constant from `exec_dashboard`, as the file already
   does for two other names); `False` in the all-time path. `components/dashboard/stat-box.tsx::Delta` gets a `reliable` prop and renders
   "no prior-period data" like `components/exec/kpi-strip.tsx:18`. Handle `ta.isError` in `dashboard/page.tsx` so a Threat Actor stats
   failure no longer removes the article KPIs. Update the syrupy snapshot `test_dashboard_stats` and add the "few previous days" and
   "enough previous days" cases to `test_article_dashboard_service.py`.
2. **Scrapers.** `ScraperListItem` gains `disabled_by` (`code`, `admin` or `mirror`) and `paused_reason`; the table shows both under a
   DISABLED status, no longer shows "ok" while the health query is pending or failed, and the "Needs attention" chips show
   `problems[].reason`. A `<details>` legend of the statuses (stale = never ran, dead = last run older than 3x the interval, degraded,
   zero_yield, partial) in the pattern of the CVE Dashboard's "How these metrics are calculated". Runs tab: an error column built from
   `errors[].stage/type/message` (never a traceback; they can leak) and a human duration. Items tab: lucide `CheckIcon`/`XIcon` with
   screen-reader text in place of the empty glyphs, in both panels that have the bug.
3. **Data health API.** Extract `build_scraper_health(session, redis, now)` and `_scheduler_status` from `routers/scraper.py`, then
   `GET /api/data-health` (`require_auth`, typed schemas, no `dict[str, object]`): `generated_at`; `enrichment` (failed in 24 h and 7 d,
   processed in 7 d, failures still waiting for a replay, last failure time); `queues` (`LLEN enrich` through `deps.get_redis` plus
   `scraper.enrich_queue_max_depth`); `sources` (newest `articles.first_seen_at`, newest `tweets.fetched_at`, newest `iocs.last_seen_at`);
   `ioc_enrichment` per type (total vs enriched, using `providers[].raw.skipped IS NULL` on the `enrichment` JSONB, not the `?` operator
   inside `text()`). A 60-second per-process cache like the other dashboards, registered in the autouse `_clear_in_process_caches`
   fixture; `_FakeRedis` in `tests/integration/conftest.py` needs an `llen`. CVE and ATT&CK freshness are not re-composed: the page
   calls the existing `/api/cve/freshness` and `/api/attack/status`.
4. **`/data-health` page.** `layout.tsx` (`PageHeader`, `metadata.title`) + `page.tsx` like `/scrapers`; a `NAV_ITEMS` entry between
   Scrapers and Admin (icon from `lucide-react`; `ShellSkeleton` goes from 10 to 11 rows); one shared hook per query (the scrapers health
   `queryFn` is copied three times today). Four `h2` sections of `Card`/`surface-raised`: pipeline (scheduler, fleet counts, problems with
   reasons, link to `/scrapers`), enrichment (failed 24 h / 7 d, rate, last failure, link to Newsroom > Failed enrichment), source
   freshness (articles, X Intel with the monitor's state, IOCs, CVE, ATT&CK), and coverage (article country/actor/TTP from
   `/api/dashboard`, IOC enrichment per type). Times use `relativeTime` and `formatWib` from `apps/web/src/lib/cve/freshness.ts`
   behind a null/invalid guard (they throw or print "NaNd ago" otherwise). The thresholds that colour a card are written on the page
   in a "How to read this page" `<details>`, not in `title=`. Follow `apps/web/CLAUDE.md` (Base UI `render=`, `aria-label`, `font-code`
   for data, `text-X-text` on tints, no `backdrop-blur`, no opacity dimming).

**Release**: suggested **0.8.0** (a new page).

### Needs from the user (decisions before PR-A)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Should replayed articles send their normal Telegram alerts? 101 day-old articles would hit the topics at once | A backward-compatible `replay: bool = False` keyword on `enrich.article` that skips alert routing, plus `--rate` pacing |
| 2 | `scraper_runs` retention (90 days) and the reaper threshold (2 hours) | accept both |
| 3 | Replay entry points | the CLI **and** the admin button |
| 4 | Is the model behind `mimo-auto` fixed on dev, and does prod run the same model? | confirm on dev before any replay; a read-only look at prod's `rejected_articles` first (the prod host may have lost articles the same way) |

### Done when

- On dev, replaying the 101 rows leaves them in `articles` with enrichment (countries/actors/TTPs filled where the text has them) and
  removes their rows from `rejected_articles`; a second replay is a no-op. A forced LLM error (a wrong model name in a throwaway
  environment) produces exactly one alert per cooldown window and a `failure_kind` on the row.
- `github_poc_monitor` shows as degraded with a reason and `consecutive_failing`; the digest does not repeat the same list every
  30 minutes; the 8 orphan `running` rows turn into `timeout`; `scraper_runs` older than the retention is gone and `celery_task_id` is
  populated on new rows.
- The Dashboard shows "no prior-period data" on a dev instance this young; `/data-health` shows the same numbers as the reproduction
  queries above; no page shows a bare "ok" while its data is loading or failed.
- Gates: ruff, strict mypy (`cti-core`, `cti-scraper`), `pytest tests/unit tests/contract packages`, the Docker integration suite for
  the migration/snapshot/purge tests, the OpenAPI drift check, and for the web `pnpm lint`, `next typegen && tsc --noEmit` and
  `pnpm build` (the worktree has no `node_modules` and no `pnpm`; use `npx pnpm@10.11.0 install --frozen-lockfile` or the main
  checkout's `node_modules`). After the user deploys to dev, re-run this audit's read-only checks and look at `/data-health`,
  `/scrapers` and the Newsroom tab in light and dark mode.

### Not in this item (known, not scheduled)

- **Indexes and retention** (not urgent at this size): `scraper_runs (scraper_id, started_at)`; `articles.posted_on`/`created_at`,
  `rejected_articles.rejected_at`, `iocs.last_seen_at`, `tweets.posted_on`, `scraper_items.url_hash`, the child FKs of `cve_*` and
  `ioc_sources`; `pg_trgm` for `ILIKE '%x%'`; no retention for `rejected_articles`, `audit_log`, `ioc_sources`, `tweets`,
  `ransomware_victims`, `package_vulns`; `threat_feed_entries` has no last-seen so a removed C2 never expires.
- **Data quality**: `ioc_sources` has 108 duplicate `(ioc_id, url)` rows and no unique constraint; IOC upserts are check-then-insert
  (two workers can collide); IOC values are not case-normalised (10 duplicate groups); ATT&CK sync never flags techniques MITRE
  deprecates later; `cisa_kev_checked_at` is stamped only on KEV hits, so a NULL cannot tell "not KEV" from "never checked";
  `cve_tracker.registered_date` is NULL in every row yet sits in the digest window predicate.
- **Multi-tenancy** (harmless with one client, a blocker before a second one): `/api/mindmap` (a PIR by id across tenants, a cache
  without `client_id`), `GET /api/stix/pir` (`list_active_unscoped`), crossref and `ta_profile` across clients, recap and newsletter
  reading all clients' tracker rows, an `X-Client-ID` the user does not belong to silently falling back to the first client, and
  deleting a client cascading to its tickets (against `docs/CVE_TECH_MATCHING.md:169`).
- **PR-C, consistency** (UI): one date format and zone everywhere (today WIB, UTC, browser-local, ISO and `m/d/yyyy` all appear);
  a freshness stamp on Exec, Newsroom, X Intel, IOC Management and Risk Matrix; metric help that works with keyboard and touch
  instead of `title=` (Exec 194, Risk Matrix 136, Newsroom 106); a Risk Matrix legend; `h2`/`h3` on Recap, Newsletter and Admin;
  the empty states of Package Vulnerabilities ("nothing monitored" vs "clean") and Campaign Clusters (the default 7 days / size 3
  shows 0 while 30 days / size 3 has 7); the Recap history labels `6a · 0t · 0c`; the Indonesian "(tanpa vendor)" in All Tech.
- **A deep `/healthz`** (database, Redis, workers): `deploy.sh` and the Docker `HEALTHCHECK` depend on the current shallow one, so it
  needs its own change.
- **Docs drift**: `docs/ARCHITECTURE.md` §7 note 1 (a URL that is already an article is not re-enriched since #31);
  `docs/SCRAPER_MAINTENANCE.md` still points to the removed `KNOWN_BROKEN.md` and §4.B ("read the error in Runs") does not match
  the UI (PR-B adds that column).
- **Not yet looked at**: the Monitored Accounts tab of X Intel, the body of the Admin page (it holds third-party keys), contrast
  measured in both themes, a real 375 px viewport, keyboard use at runtime, and whether `logbook.last_report_date` (2026-09-26,
  14-day interval) means a logbook report was missed.
