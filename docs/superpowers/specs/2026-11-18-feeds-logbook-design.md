# Logbook Threat Information Feeds (0.8.21)

## Intent

A second logbook report: **"Logbook Threat Information Feeds"**, a monthly inventory of the sources Threat
Information collects from (one row per source: added date, domain, status, method, link, last update, notes), on the
company document template with a signature block. The user needs this report.

It used to come from a standalone script on the old Rundeck host (`report.py` + `modules/test.py`, examples and
template in the user's `~/Downloads/TIreport`, not in this repo). That script lists the Rundeck jobs of the
`Threat-Information` project and greps each job's Python file for URLs and library names. Since the cutover to
Vareon those jobs are switched off, so the October 2026 output reports 194 of 200 rows as "Disabled / TEMPORARY
DISABLED", with "Last Update" `01 Januari 1` (`datetime.min`) on many rows. The report now describes the retired
system. Vareon must produce it from its own scraper registry.

## Goals / non-goals / anti-goals

- Goals
  - Monthly `.xlsx` built from Vareon's 100 registered scrapers, on the user's new template (`templateNEW.xlsx`).
  - Sent to Telegram on the last day of each month, like the old script; a missed month can be re-run by hand.
  - Every column filled from data Vareon owns. No Rundeck, no file-system scanning, no hard-coded people.
- Non-goals
  - Historical status. Status and Notes are a snapshot taken when the report is built, as in the old script; a
    re-run of a past month shows today's status.
  - A web download / UI page, or editing rows by hand.
  - Collapsing rows per domain (the old script kept one row per domain, preferring Request > XML > Selenium).
    Vareon has one row per scraper; two scrapers on one host give two rows.
- Anti-goals
  - Rows that say "Running" for a scraper that is enabled but broken (the old report hid this; people wrote "WEB
    ERROR" by hand in the Rundeck description).
  - Placeholder or real signer names in the document. The user asked for the signer name and title cells to stay
    **empty** (filled in by hand when signing).
  - Anything from `~/Downloads/TIreport` reaching the repo except the template. Those scripts hard-code a Rundeck
    API token and `config/config.yml` holds a Telegram bot token.
  - A release that needs new `.env` keys on prod before merge.

## Approaches (the "Added Date" column)

Vareon stores no "date this source was added". Three ways were considered; the user handed the choice to Claude.

1. **Explicit date per scraper (picked).** New `ScraperMeta.added: datetime.date | None`, seeded once (see Seeding),
   required for every registered scraper by a contract test so new scrapers cannot forget it. Stable, auditable,
   independent of purged tables, works in `dry-run`, and keeps continuity with reports already signed. Cost: a
   one-time mechanical edit of ~100 scraper files.
2. Earliest article per source from `articles` (no purge on that table). No scraper edits, but ~17 scrapers that do
   not produce articles (CVE, tweet, ransomware, techstack) would be blank, and dates would differ from past reports.
3. Start recording "first seen by the platform" in the DB now. Automatic for new scrapers, but every existing scraper
   would get the deploy date, so the first reports carry no information; needs a migration.

## Design

### Data per row (one per registered scraper, `registry.discover()`)

| Column | Source |
|---|---|
| No | 1..N after sorting |
| Added Date | `meta.added`, Indonesian date (`05 Maret 2026`, zero-padded like the old rows) |
| Domain | unique hosts of the scraper's source URLs, `www.` kept as written, joined with `, ` |
| Status | `Running` if `cti_scraper.supersede.effective_enabled(meta, config)` else `Disabled`, italic (as before) |
| Method | see mapping below |
| Source Link | hyperlink text `Link to Scrape`, target = first source URL |
| Last Update | `finished_at` of the newest `scraper_runs` row with `items_new > 0` and `finished_at <=` period end; `-` if none (runs are kept `worker.scraper_run_retention_days` = 90 days). Meaning: "last time this source gave new items", which is what the old script meant (`modules/test.py` took the mtime of the scraper's offset file, rewritten when new items arrive). The old values themselves are not a model: 123 of 200 rows share `18 April 2026` and 59 show `01 Januari 1` (`datetime.min`), artefacts of the retired host |
| Notes | see rules below |

Rows are sorted by Added Date, then `meta.source`.

**Source URLs**, resolved by one pure function in the report module:
`RSSScraper.feeds` (all), `XPathScraper.url`, `ApiScraper.url`, `GithubCommitWatcher` ->
`https://github.com/{owner}/{repo}`; otherwise the new optional `ScraperMeta.source_url: str | None`. The scrapers
with no URL attribute today get an explicit `source_url`: the 13 collectors (e.g. `cisa_kev`, `ransomware_live`,
`new_cve`, `monitor_x`, `tweet_alerts_*`, `techstack_*`) and the 3 `LibraryAdvisoryScraper` scrapers. A contract
test asserts every registered scraper resolves at least one URL.

**Method mapping**: `RSSScraper` -> `XML`; `runtime == "browser"` -> `Playwright`; everything else (`XPathScraper`
light, `GithubCommitWatcher`, `LibraryAdvisoryScraper`, light collectors) -> `Request`. Selenium no longer exists in
Vareon. No `ApiScraper` subclass is registered today; it maps to `Request` if one appears. Known imprecision: the
`rapid7` collector reads an RSS feed but shows `Request` (one row; accepted rather than adding a per-scraper
override).

**Notes rules.** The report is a signed monthly document, so Notes flag only lasting states, never a blip at the
moment it is built.
- Disabled, in this order:
  1. `ScraperConfig.paused_reason` if set (operators can give any scraper a specific reason with
     `cti-scraper disable <id> --reason "..."`, which also works for the scrapers disabled in code);
  2. `REPLACED BY CVE MIRROR` when `cti_scraper.supersede.disabled_by(...) == "mirror"`;
  3. `DISABLED` when `disabled_by == "code"` (`meta.enabled=False`: `blackberry`, `cisa`, `google`, `koisec`,
     `nquiring_minds`, switched off for permanent reasons recorded in their docstrings, so not "temporary");
  4. otherwise (`admin` without a reason) `TEMPORARY DISABLED`, the old default.
- Running, from the same health inputs as the worker digest (`cti_scraper.health`):
  - `dead` (ran before, last run older than 3 schedule intervals) -> `NOT RUNNING`;
  - `stale` (no run recorded: never ran, or nothing left after the 90-day purge) -> `NO RUN RECORDED`;
  - the 3 newest finished runs all failing (`run_is_failing`) with a status other than `backpressure` -> `ERROR`.
    `degraded` alone (only the latest run failed) is not enough: it includes `timeout`, `rate_limited` and the
    fleet-wide `backpressure`, so a queue backlog at build time would otherwise mark healthy feeds;
  - anything else, including `zero_yield` (a quiet feed is not a fault; Last Update shows it) -> `-`.

### Template

Copy `templateNEW.xlsx` to `apps/worker/src/cti_worker/reports/templates/feeds_logbook_template.xlsx`, edited once:
- Header address (E2) set to the CIBIS Nine address used by `logbook_template.xlsx` (the new template still has the
  old Kemang address).
- Remove the Selenium row from the Method legend (rows 8-9) and renumber, so the legend lists Playwright, Request,
  XML.
- Signer name and title cells (E38/G38, E39/G39 in the template) emptied; "Disusun Oleh" / "Disetujui Oleh" stay.
- `<`/`>` placeholders are no longer used; the code writes the cells directly.

Code fills: `Tanggal : <period end>` (I4), title `Logbook Threat Information Feeds Periode\n<start> - <end>` (E5), the
Notes paragraph (D17) with the real period (the template still says "1 Mei 2025 – 31 Mei 2025", which the old
script never replaced), and the rows from row 24 (header row 23 unchanged). All dates in Indonesian (the old header
used English month names); reuse `logbook.format_date_id`. Keep the old styling: thin borders, centred cells, wrap
on Domain, italic Status, `Hyperlink` style on Source Link, the signature-block merge the old script did.

### Schedule and delivery

- Task `report.feeds_logbook` (queue `notify`) in `cti_worker/tasks/reports.py`, beat entry `report-feeds-logbook`
  daily at 07:00 local (`local_to_utc_cron`), same pattern as `report.logbook`.
- Period rule (both run kinds): from the 1st of `day`'s month to `day`; `Tanggal` and the file name use `day`.
- Scheduled run (`day` = local today): does nothing unless today is the last day of its month, so the period is the
  whole month. Idempotent per month via `JobStateRepo` key `feeds_logbook.last_report_month` (`YYYY-MM`), checked
  before building and written only after Telegram succeeds (same order as the other report tasks).
- Manual run (`day` given, ISO): always builds and sends, and **never reads or writes the state key**. A test run on
  dev or right after deploy (e.g. `day=2026-11-20`, period 1-20 November) therefore cannot suppress the real
  end-of-month report. Re-sending a missed month = pass its last day.
- File name `Logbook Threat Information Feeds <period end ISO>.xlsx` (same as the old files). Sent with
  `send_document("logbook", ...)` (existing topic, no new `TELEGRAM__THREAD_IDS` key). Caption in the old format
  without the `Reporter: @drpalupi` line:
  `=== <b>THREAT INFORMATION FEEDS REPORT</b> ===`, `Start Entry Date`, `End Entry Date`.
- No new settings.

### Seeding `added` (one-time, during implementation)

A throwaway script (not committed) matches each scraper's source hosts against the rows of
`Logbook Threat Information Feeds 2026-10-31.xlsx` (Source Link host first, then any Domain host):
- exactly one legacy date -> that date (85 of 100 today);
- several dates (`github_poc_monitor`, `new_cve`) or no match (13, e.g. `aws_security`, `redhat_security`,
  `monitor_x`, `techstack_*`) -> the date the scraper file was first committed (`git log --diff-filter=A`).

Hosts shared by many sources (`github.com`, `api.github.com`, `twitter.com`, `cveawg.mitre.org`) can give a wrong
legacy match; the PR description carries the full id -> date -> reason table for the user to check.

### Tests

- Unit: URL resolution and method mapping per family; every Notes rule (including `backpressure` streaks and a
  single failed run giving `-`); workbook builder (row count, cell values, blank signer cells, hyperlink target,
  period text in E5/I4/D17); last-day-of-month guard; period rule.
- Contract: every registered scraper has `meta.added` and resolves at least one source URL.
- Integration (`tests/integration/test_report_tasks.py` pattern): not the last day -> no send; last day -> one send
  and state written; second call same month -> no send; Telegram failure -> state unchanged; manual `day` mid-month
  -> sends with period 1st..`day` and leaves the state key untouched, and the scheduled run at month end still
  sends.
- `tests/unit/test_beat_schedule.py`: new entry present.

### Docs and release

- `docs/ADDING_A_SCRAPER.md`: `added` (required) and `source_url` (when the family has no URL).
- `docs/ARCHITECTURE.md` report table: add the feeds logbook.
- Release 0.8.21 in the same PR (versions, `uv.lock`, `docs/openapi.json`, health snapshot, `CHANGELOG.md` in
  Indonesian), `docs/prod-upgrade/0.8.21.md` (no migration, no new env; restart `beat` for the new schedule). Branch ->
  `origin/Dev` for testing on dev -> PR to `main`.

## Left to the builder

- Exact field docstrings (Indonesian, explaining why), names of helper functions, where the URL/method helpers live
  (report module unless the API `/scrapers` page wants them later).
- Cell coordinates after removing the legend row (read them from the edited template, do not hard-code the old ones).
- The new sync repo query for "newest run with new items per scraper" (one grouped query).
