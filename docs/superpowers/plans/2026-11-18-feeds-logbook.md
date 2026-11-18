# Logbook Threat Information Feeds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A monthly "Logbook Threat Information Feeds" `.xlsx` (one row per registered scraper) sent to the Telegram
`logbook` topic on the last day of each month, replacing the retired Rundeck script.

**Architecture:** Scraper facts (when added, source URLs, method) come from code: two new optional `ScraperMeta` fields
and a pure helper module in `cti_scraper`. Run facts (last new items, health) come from `scraper_runs` /
`scraper_config`. A report module in `cti_worker.reports` turns both into rows and fills a committed template; a
Celery task in `tasks/reports.py` schedules, guards and sends it, same pattern as `report.logbook`.

**Tech Stack:** Python 3.12, openpyxl, SQLAlchemy (sync session), Celery beat, pytest (+ testcontainers for
integration).

**Spec:** `docs/superpowers/specs/2026-11-18-feeds-logbook-design.md`

## Global Constraints

- Branch `claude/feeds-logbook` from `main` (`bae755b8`); later merged to `origin/Dev` for the dev test, then PR to
  `main`. Commit messages in English, conventional style, ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Comments and docstrings in Indonesian, explaining why (match surrounding files). Docs under `docs/` in English;
  `CHANGELOG.md` in Indonesian.
- Nothing from `~/Downloads/TIreport` enters the repo except the edited template. Never copy tokens from its `.py`
  files or `config/config.yml`.
- No new `Settings` fields, no new `.env` keys, no migration.
- Signer name and title cells stay empty; "Disusun Oleh" / "Disetujui Oleh" labels stay.
- Dates in the document are Indonesian (`cti_worker.reports.logbook.format_date_id`): rows zero-padded
  (`05 Maret 2026`), header/period/Tanggal not padded (`1 Oktober 2026`).
- Release 0.8.21 in this same branch (last task).
- `mypy` strict covers `packages/cti-core/src` and `packages/cti-scraper/src`; keep new code there fully typed.
- Local test runs deselect `tests/contract/test_golden.py::test_golden_trendmicro` (Chromium not installed on this Mac;
  known, not a regression).

## Review Focus

1. A scraper added after this ships without `added` or a resolvable URL: the contract test must fail CI, not the report
   at month end (Task 2 contract tests).
2. A manual test run mid-month (dev, or prod right after deploy) must not suppress the real month-end report (Task 5:
   `test_feeds_logbook_manual_run_mid_month_leaves_state_and_month_end_still_sends`).
3. A fleet-wide enrichment backlog (`backpressure`) or a single timeout at 07:00 must not print `ERROR` in the signed
   document (Task 4 notes tests).
4. Telegram failure must not mark the month as sent, so an operator's manual run can resend it (there is one tick a
   day, so no automatic retry; the failure shows in the Celery log like the other reports) (Task 5:
   `..._telegram_failure_leaves_state_unwritten`).
5. A scraper whose newest run with new items is after the period end (manual replay of a past month) must not show a
   Last Update later than the period (Task 3 test: the 11-02 run is excluded by `before`).

---

### Task 1: `ScraperMeta.added` / `source_url` and the inventory helpers

**Files:**
- Modify: `packages/cti-scraper/src/cti_scraper/base.py` (import; two fields at the end of `ScraperMeta`)
- Create: `packages/cti-scraper/src/cti_scraper/inventory.py`
- Test: `tests/unit/test_scraper_inventory.py`

**Interfaces:**
- Produces:
  - `ScraperMeta.added: date | None = None`, `ScraperMeta.source_url: str | None = None`
  - `cti_scraper.inventory.Method = Literal["XML", "Playwright", "Request"]`
  - `source_urls(cls: type[BaseScraper]) -> tuple[str, ...]`
  - `hosts(urls: Iterable[str]) -> tuple[str, ...]`
  - `method_for(cls: type[BaseScraper]) -> Method`

- [ ] **Step 0: Branch and commit the design docs**

```bash
git switch -c claude/feeds-logbook
git add docs/superpowers/specs/2026-11-18-feeds-logbook-design.md docs/superpowers/plans/2026-11-18-feeds-logbook.md
git commit -m "docs: design and plan for the feeds logbook report"
```

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_scraper_inventory.py`. Fake scrapers use
  `__abstract__ = True` so they never enter the global registry (pattern from `tests/unit/test_runner_partial.py`).

```python
def test_rss_lists_every_feed_and_reads_as_xml():
    cls = discover()["anyrun"]
    assert source_urls(cls) == ("https://any.run/cybersecurity-blog/feed/",)
    assert method_for(cls) == "XML"

def test_browser_xpath_reads_as_playwright():
    cls = discover()["abnormalsecurity"]
    assert source_urls(cls) == ("https://abnormal.ai/blog?filter=threat-intel",)
    assert method_for(cls) == "Playwright"

def test_github_watcher_points_at_the_repo():
    cls = discover()["mitre_github"]
    assert source_urls(cls) == ("https://github.com/mitre-attack/attack-stix-data",)
    assert method_for(cls) == "Request"

def test_explicit_source_url_wins_and_a_bare_collector_without_one_resolves_nothing():
    # fake BaseScraper subclass: meta.source_url="https://x.com" -> ("https://x.com",), method "Request"
    # same fake without source_url -> ()
    # fake XPathScraper with url="https://a.example/list" and meta.source_url="https://b.example" -> ("https://b.example",)

def test_hosts_are_unique_in_order_and_keep_www():
    assert hosts(["https://www.a.com/x", "https://b.com/y", "https://www.a.com/z"]) == ("www.a.com", "b.com")
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_scraper_inventory.py -q`
Expected: FAIL (`ModuleNotFoundError: cti_scraper.inventory`)

- [ ] **Step 3: Implement.** In `base.py` change the import to `from datetime import UTC, date, datetime` and append
  `added` and `source_url` after `notes` with Indonesian docstrings (why: the monthly feeds logbook; `added` seeded
  from the old Rundeck report for continuity; `source_url` only when the family has no URL attribute). In
  `inventory.py`, precedence for `source_urls`: `meta.source_url` if set; else `RSSScraper.feeds`; else `url`
  (`XPathScraper`, `ApiScraper`); else `GithubCommitWatcher` -> `f"https://github.com/{owner}/{repo}"`; else `()`.
  `method_for`: `issubclass(cls, RSSScraper)` -> `"XML"`; `meta.runtime == "browser"` -> `"Playwright"`; else
  `"Request"`. Use `issubclass` on the family classes, not attribute sniffing.

- [ ] **Step 4: Run tests, lint, types**

Run: `uv run pytest tests/unit/test_scraper_inventory.py -q && uv run ruff check packages/cti-scraper tests/unit/test_scraper_inventory.py && uv run mypy packages/cti-core/src packages/cti-scraper/src`
Expected: all pass, `Success: no issues found`

- [ ] **Step 5: Commit** `feat(scraper): add ScraperMeta.added/source_url and inventory helpers`

---

### Task 2: Seed `added` and `source_url` on every scraper + contract tests

**Files:**
- Modify: every scraper file under `scrapers/src/cti_scrapers/feeds/` and `collectors/` (100 scrapers)
- Create: `tests/contract/test_scraper_inventory.py`
- Modify: `docs/ADDING_A_SCRAPER.md` (both `ScraperMeta(...)` examples + one paragraph)
- Scratch (not committed): `<scratchpad>/seed_added.py`, `<scratchpad>/added_seed.md`

**Interfaces:**
- Consumes: Task 1 `source_urls`, `hosts`.
- Produces: every registered scraper has `meta.added` (a `date`) and a non-empty `source_urls(cls)`.

- [ ] **Step 1: Write the failing contract tests** in `tests/contract/test_scraper_inventory.py`:

```python
def test_every_scraper_declares_when_it_was_added():
    assert {s for s, c in discover().items() if not isinstance(c.meta.added, date)} == set()


def test_added_dates_are_not_in_the_future():
    assert {
        s: c.meta.added
        for s, c in discover().items()
        if c.meta.added and c.meta.added > date.today()
    } == {}


def test_every_scraper_resolves_an_absolute_source_url():
    bad = {
        s
        for s, c in discover().items()
        if not source_urls(c)
        or not all(
            urlparse(u).scheme in ("http", "https") and urlparse(u).netloc for u in source_urls(c)
        )
    }
    assert bad == set()
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/contract/test_scraper_inventory.py -q`
Expected: FAIL, 100 ids missing `added`, 16 ids without URL

- [ ] **Step 3: Add `source_url=` by hand** (one line after `source=`) to these 16 scrapers:

| id | `source_url` |
|---|---|
| `any_run_trends` | `https://any.run/malware-trends/` |
| `blackorbird` | `https://github.com/blackorbird/APT_REPORT` |
| `cisa_kev` | `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json` |
| `deepdark_cti` | `https://github.com/fastfire/deepdarkCTI` |
| `github_poc_monitor` | `https://api.github.com/search/repositories` |
| `monitor_x`, `trending_cve`, `tweet_alerts_1h`, `tweet_alerts_30m` | `https://x.com` |
| `new_cve` | `https://services.nvd.nist.gov/rest/json/cves/2.0` |
| `ransomware_live` | `https://api.ransomware.live/v2/victims` |
| `rapid7` | `https://www.rapid7.com/rss.xml` |
| `unit42_github` | `https://github.com/PaloAltoNetworks/Unit42-timely-threat-intel` |
| `techstack_go` / `techstack_npm` / `techstack_pypi` | `https://osv.dev/list?ecosystem=Go` / `...=npm` / `...=PyPI` |

- [ ] **Step 4: Write and run the seed script** (scratchpad, run with `uv run python`). For each `sid, cls` in
  `discover()`:
  - match hosts = `hosts(source_urls(cls))` plus the hosts of every literal `https?://` URL in the scraper's module
    source (`inspect.getsource(sys.modules[cls.__module__])`, ignore URLs containing `{`);
  - legacy rows from `~/Downloads/TIreport/Logbook Threat Information Feeds 2026-10-31.xlsx` (rows from 24 where
    column B is an int; C = Added Date `"16 Juni 2025"`, D = comma-separated domains, G hyperlink target). Compare
    hosts with `www.` stripped. First rows whose Source Link host is in the match hosts; if none, rows whose Domain
    set intersects them;
  - exactly one distinct legacy date -> that date (parse the Indonesian month name), reason `legacy`; otherwise
    `git log --follow --diff-filter=A --format=%ad --date=short -- <file> | tail -1`, reason `git (no match)` or
    `git (ambiguous: <dates>)`;
  - insert `added=date(Y, M, D),` on its own line right after the line containing `id="<sid>",` (same indent) in
    `inspect.getsourcefile(cls)`, and add `from datetime import date` after `from __future__ import annotations`;
  - write `<scratchpad>/added_seed.md`: table `id | added | reason | matched legacy row (domain, link)`, for the PR.

  Expected from the dry match done during design: about 85 `legacy`, 2 ambiguous (`github_poc_monitor`, `new_cve`),
  13 no match.

- [ ] **Step 5: Normalise and check**

Run: `uv run ruff check --fix scrapers && uv run ruff format scrapers && uv run pytest tests/contract -q --deselect tests/contract/test_golden.py::test_golden_trendmicro`
Expected: ruff merges the `datetime` imports with no other diff; all contract tests pass (golden fixtures unaffected).

- [ ] **Step 6: Review the seed table.** Open `added_seed.md`; for rows matched only through a shared host
  (`github.com`, `api.github.com`, `twitter.com`, `x.com`, `cveawg.mitre.org`) check the matched legacy row really is
  the same source; if not, switch that scraper to its git date and mark the reason `git (shared host)`.

- [ ] **Step 7: Docs.** In `docs/ADDING_A_SCRAPER.md` add `added=date(...)` to both `ScraperMeta(...)` examples and one
  paragraph: `added` is required (contract test), it is the date the source joins the platform and appears in the
  monthly feeds logbook; `source_url` is needed only when the family exposes no URL (`feeds`/`url`/GitHub repo).

- [ ] **Step 8: Commit** `feat(scrapers): record when each source was added and its source URL`

---

### Task 3: Newest run with new items per scraper

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/scraper.py` (`ScraperRunRepo`)
- Test: `tests/integration/test_scraper_run_maintenance.py` (where `last_success_by_scraper` is tested)

**Interfaces:**
- Produces: `ScraperRunRepo.last_new_items_by_scraper(self, *, before: datetime.datetime) -> dict[str, datetime.datetime]`
  (one grouped query: `max(finished_at)` where `items_new > 0`, `finished_at IS NOT NULL`, `finished_at < before`,
  grouped by `scraper_id`)

- [ ] **Step 1: Write the failing test**

```python
def test_last_new_items_takes_the_newest_productive_run_before_the_bound():
    # scraper "a": items_new=2 finished 10-05, items_new=0 finished 10-20, items_new=1 finished 11-02
    # scraper "b": only items_new=0 runs
    got = ScraperRunRepo(s).last_new_items_by_scraper(before=datetime(2026, 11, 1, tzinfo=UTC))
    assert got == {"a": datetime(2026, 10, 5, ..., tzinfo=UTC)}
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/integration/test_scraper_run_maintenance.py -k last_new_items -q`
Expected: FAIL (`AttributeError: ... last_new_items_by_scraper`)

- [ ] **Step 3: Implement** the method (Indonesian docstring: feeds logbook "Last Update", bounded by the period end so a
  replay of a past month does not show later dates).

- [ ] **Step 4: Run test + mypy**

Run: `uv run pytest tests/integration/test_scraper_run_maintenance.py -q && uv run mypy packages/cti-core/src packages/cti-scraper/src`
Expected: PASS, no mypy issues

- [ ] **Step 5: Commit** `feat(core): query the newest scraper run that produced new items`

---

### Task 4: Template + report module

**Files:**
- Create: `apps/worker/src/cti_worker/reports/templates/feeds_logbook_template.xlsx` (binary, made by a scratch script)
- Create: `apps/worker/src/cti_worker/reports/feeds_logbook.py`
- Test: `tests/unit/test_feeds_logbook.py`

**Interfaces:**
- Consumes: Task 1 (`source_urls`, `hosts`, `method_for`), Task 3 (`last_new_items_by_scraper`),
  `cti_scraper.supersede.effective_enabled` / `disabled_by`, `cti_scraper.health.compute_health` / `run_is_failing`,
  `ScraperConfigRepo.get_all()`, `ScraperRunRepo.list_recent_by_scraper_bulk(limit=3)`, `logbook.format_date_id`.
- Produces (all in `cti_worker.reports.feeds_logbook`):
  - `@dataclass(frozen=True) FeedRow(added: date | None, domain: str, status: Literal["Running", "Disabled"], method: str, link: str, last_update: date | None, notes: str, source: str)`
  - `period_for(day: date) -> tuple[date, date]` -> `(day.replace(day=1), day)`
  - `is_last_day_of_month(day: date) -> bool`
  - `notes_for(meta: ScraperMeta, config: ScraperConfig | None, runs: Sequence[ScraperRun], *, now: datetime) -> str`
  - `collect(session: Session, *, end: date, offset_hours: int, now: datetime) -> list[FeedRow]`
  - `build(rows: Sequence[FeedRow], *, start: date, end: date) -> bytes`
  - `filename_for(end: date) -> str`, `caption(start: date, end: date) -> str`

- [ ] **Step 1: Make the template** with a scratch openpyxl script from `~/Downloads/TIreport/templateNEW.xlsx`:
  1. `E2` = the `E2` value of `reports/templates/logbook_template.xlsx` (CIBIS Nine address).
  2. Legend: write Playwright/Request/XML (values of `C10:D10`, `C12:D12`, `C14:D14`) into `C8:D8`, `C10:D10`,
     `C12:D12`; numbers in `B8/B10/B12` stay 1/2/3.
  3. Unmerge `B14:B15`, `C14:C15`, `D14:F15`, `B17:C20`, `D17:F20`; `ws.delete_rows(14, 2)`; merge `B15:C18`,
     `D15:F18`; move every explicit row height of rows >= 16 up by 2 (16->14, 17->15, 18->16, 22->20, 23->21, 30->28)
     and clear the old ones.
  4. Clear the signer cells now at `E36`, `G36`, `E37`, `G37`.
  5. Save; dump every non-empty cell + merged ranges + `len(ws._images) == 1` and check: header row 21 =
     `No | Added Date | Domain | Status | Method | Source Link | Last Update | Notes` (B..I), Notes paragraph at `D15`,
     labels `Disusun Oleh` `E28` / `Disetujui Oleh` `G28`, no text at `E36:G37`, legend 1 Playwright 2 Request 3 XML.

- [ ] **Step 2: Write the failing tests** in `tests/unit/test_feeds_logbook.py` (fake `ScraperRun`/`ScraperConfig` as
  `SimpleNamespace` with `status`, `started_at`, `items_failed`, `enabled`, `paused_reason`; meta via
  `dataclasses.replace` on a real meta):

```python
def test_period_runs_from_the_first_of_the_month_to_the_given_day():
    assert period_for(date(2026, 11, 20)) == (date(2026, 11, 1), date(2026, 11, 20))
    assert is_last_day_of_month(date(2026, 2, 28)) and not is_last_day_of_month(date(2026, 10, 30))

def test_disabled_notes_follow_reason_then_mirror_then_code_then_temporary():
    # paused_reason "WEB HAS BEEN SHUTDOWN" -> that text
    # meta.id "new_cve" with CVE_MIRROR__PROMOTE live (superseded) -> "REPLACED BY CVE MIRROR"  (monkeypatch supersede)
    # meta.enabled=False, no config -> "DISABLED"
    # config.enabled=False, no reason -> "TEMPORARY DISABLED"

def test_running_notes_flag_only_lasting_problems():
    # no runs -> "NO RUN RECORDED"
    # last run older than 3 schedule intervals -> "NOT RUNNING"
    # 3 newest runs fetch_error -> "ERROR"
    # [backpressure, fetch_error, fetch_error] -> "-"
    # [timeout] only -> "-";  [fetch_error, ok, ok] -> "-";  3x "empty" (zero_yield) -> "-"

def test_workbook_fills_header_rows_and_leaves_signers_blank():
    data = build([row_a, row_b], start=date(2026, 10, 1), end=date(2026, 10, 31))
    ws = load(data)
    assert ws["I4"].value == "Tanggal : 31 Oktober 2026"
    assert ws["E5"].value == "Logbook Threat Information Feeds Periode\n1 Oktober 2026 - 31 Oktober 2026"
    assert "1 Oktober 2026 – 31 Oktober 2026" in ws["D15"].value and "Mei 2025" not in ws["D15"].value
    assert [c.value for c in ws[22][1:9]] == [1, "05 Maret 2026", "any.run", "Running", "XML",
                                              "Link to Scrape", "20 Oktober 2026", "-"]
    assert ws["G22"].hyperlink.target == "https://any.run/cybersecurity-blog/feed/"
    assert ws["E22"].font.i
    # signature block moved down by 2 rows: label row 30, name row 38, title row 39
    assert ws["E30"].value == "Disusun Oleh" and ws["G30"].value == "Disetujui Oleh"
    assert all(ws[c].value in (None, "") for c in ("E38", "G38", "E39", "G39"))
    assert {"E30:F30", "G30:H30", "E38:F38", "G38:H38", "E39:F39", "G39:H39"} <= {str(r) for r in ws.merged_cells.ranges}

def test_missing_dates_render_as_dash():  # added=None / last_update=None -> "-"

def test_filename_and_caption():
    assert filename_for(date(2026, 10, 31)) == "Logbook Threat Information Feeds 2026-10-31.xlsx"
    assert caption(date(2026, 10, 1), date(2026, 10, 31)) == (
        "\n    === <b>THREAT INFORMATION FEEDS REPORT</b> ===\n"
        "<b>Start Entry Date</b>: 01 Oktober 2026\n<b>End Entry Date</b>: 31 Oktober 2026")
```

- [ ] **Step 3: Run to see them fail**

Run: `uv run pytest tests/unit/test_feeds_logbook.py -q`
Expected: FAIL (`ModuleNotFoundError: cti_worker.reports.feeds_logbook`)

- [ ] **Step 4: Implement** `feeds_logbook.py` (module docstring in Indonesian: replaces the Rundeck `report.py`, what
  differs and why, mirroring `logbook.py`'s docstring).
  - `notes_for`: rules exactly as the spec's "Notes rules"; "finished" runs exclude `running`/`overlap`; `ERROR` needs
    3 finished runs, all `run_is_failing`, none `backpressure`.
  - `collect`: `discover()`; configs `ScraperConfigRepo(session).get_all()`; recent runs
    `ScraperRunRepo(session).list_recent_by_scraper_bulk(limit=3)`; last new items with
    `before = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC) - timedelta(hours=offset_hours)`;
    Last Update date = `(ts + timedelta(hours=offset_hours)).date()`; Domain = `", ".join(hosts(urls))`, link =
    `urls[0]`; sort by `(added or date.min, source)`.
  - `build`: load the template with `importlib.resources` like `logbook.build`; find the header row (column B `"No"`
    and column C `"Added Date"`), `insert_rows(header + 1, len(rows))`, write B..I with a thin border and centred
    alignment (wrap on D, italic on E, `style = "Hyperlink"` on G with text `Link to Scrape`); fill I4, E5 and the
    Notes paragraph (find the column-D cell starting `"Laporan ini disusun setiap bulan"`, replace the period with a
    regex on `\d{1,2} \w+ \d{4} – \d{1,2} \w+ \d{4}`); then find `"Disusun Oleh"` and merge `E:F` and `G:H` on
    that row, +8 and +9 (insert_rows does not move merged ranges, the old script merged after inserting too).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_feeds_logbook.py -q && uv run ruff check apps/worker tests/unit/test_feeds_logbook.py`
Expected: PASS

- [ ] **Step 6: Commit** `feat(worker): build the feeds logbook workbook from the scraper registry`

---

### Task 5: Celery task, beat entry, integration tests

**Files:**
- Modify: `apps/worker/src/cti_worker/tasks/reports.py` (new task after `report_logbook`; module docstring list)
- Modify: `apps/worker/src/cti_worker/beat.py` (`_report_schedule` + its docstring)
- Test: `tests/integration/test_report_tasks.py`, `tests/unit/test_beat_schedule.py`

**Interfaces:**
- Consumes: Task 4 functions.
- Produces: `FEEDS_LOGBOOK_STATE_KEY = "feeds_logbook.last_report_month"`;
  `report_feeds_logbook(self, day: str | None = None) -> dict[str, object]`, Celery name `report.feeds_logbook`, queue
  `notify`; returns `{"status": "not_due"}`, `{"status": "already_sent", "month": "YYYY-MM"}` or
  `{"status": "sent", "rows": n, "start": iso, "end": iso, "manual": bool}`; beat key `report-feeds-logbook`.

- [ ] **Step 1: Write the failing tests.** Scheduled runs pass no `day`; a `today_is` fixture pins "today" with
  `monkeypatch.setattr(reports, "local_now", lambda offset, **_kw: <aware datetime at 07:00 UTC+offset on that day>)`. Extend `_clean` to
  delete `ScraperRun` rows whose `run_id` starts with the test prefix and the `JobState` rows (already wiped).

```python
def test_feeds_logbook_does_nothing_before_the_last_day(tg, today_is):      # today 2026-10-30 -> not_due, no docs
def test_feeds_logbook_sends_on_the_last_day_and_records_the_month(tg, today_is):
    # today 2026-10-31; add ScraperRun(anyrun, items_new=2, finished 2026-10-20 03:00 UTC)
    # -> status sent; tg.docs[0][0] == "logbook"; name "Logbook Threat Information Feeds 2026-10-31.xlsx"
    # -> data rows == len(discover()); anyrun row Last Update "20 Oktober 2026"; state == "2026-10"
def test_feeds_logbook_sends_once_per_month(tg, today_is):                   # second call -> already_sent
def test_feeds_logbook_telegram_failure_leaves_state_unwritten(tg, today_is):  # tg.fail -> raises; state None
def test_feeds_logbook_manual_run_mid_month_leaves_state_and_month_end_still_sends(tg, today_is):
    # run(day="2026-11-20") -> sent, manual True, E5 period "1 November 2026 - 20 November 2026", state None
    # then today 2026-11-30, run() -> sent
```

  In `test_beat_schedule.py`: add `"report-feeds-logbook": "report.feeds_logbook"` to the expected dict and
  `assert _cron(reports["report-feeds-logbook"]) == ("0", "0", "*")  # 07:00 WIB`.

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_beat_schedule.py -q && uv run pytest tests/integration/test_report_tasks.py -k feeds -q`
Expected: FAIL (missing beat entry / `ImportError: report_feeds_logbook`)

- [ ] **Step 3: Implement** the task (order as the other report tasks: read DB in `sync_session()`, close it, send, then
  write state in a new session only on success; manual runs never read or write the state key) and the beat entry
  `crontab(**local_to_utc_cron(7, 0, offset))` on `QUEUE_NOTIFY`. Docstring: the scheduled/manual split and why
  (a mid-month test run must not suppress the month-end report); manual command
  `celery -A cti_worker.celery_app call report.feeds_logbook --args='["2026-10-31"]'`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_beat_schedule.py tests/integration/test_report_tasks.py -q`
Expected: PASS

- [ ] **Step 5: Commit** `feat(worker): send the feeds logbook on the last day of each month`

---

### Task 6: Docs and release 0.8.21

**Files:**
- Modify: `docs/ARCHITECTURE.md` (report table row at the `report.*` line), `docs/CI_CD.md` (upgrade runbook chain)
- Create: `docs/prod-upgrade/0.8.21.md`, `docs/PROD_UPGRADE_0.8.20_TO_0.8.21.md` (same shape as the 0.8.20 pair)
- Modify: the 16 version files (`pyproject.toml`; `apps/api`, `apps/worker`, `packages/cti-{alerts,core,enrich,scraper}`,
  `scrapers` `pyproject.toml`; `apps/api/src/cti_api/__init__.py`, `apps/worker/src/cti_worker/__init__.py`,
  `packages/*/src/*/__init__.py`; `apps/web/package.json` line 3 only), `uv.lock`, `docs/openapi.json`,
  `tests/integration/__snapshots__/test_health_router_snapshot.ambr`, `CHANGELOG.md`

- [ ] **Step 1: Docs.** ARCHITECTURE: add "feeds logbook" to the `report.*` list. `prod-upgrade/0.8.21.md` with the
  fixed headings (What changes in prod / Migrations: none / Settings-.env: none / Before deploy: nothing / After
  deploy: restart `beat`; optional check `celery ... call report.feeds_logbook --args='["<today>"]'` on dev only,
  it does not touch the month state / One-off commands: optional `cti-scraper disable <id> --reason "..."` for
  specific Notes on the five code-disabled scrapers / Rollback: previous image, no DB change / Known risks: `added`
  seeded from the retired report, shared-host matches listed in the PR; Status/Notes are a snapshot at build time).
  Combined runbook `PROD_UPGRADE_0.8.20_TO_0.8.21.md` and the `CI_CD.md` chain sentence, same pattern as 0.8.20.

- [ ] **Step 2: Bump** `0.8.20` -> `0.8.21` in the 16 files, then:

Run: `uv lock && uv run python tools/export_openapi.py && uv run pytest tests/integration/test_health_router_snapshot.py --snapshot-update -q && uv sync --extra dev --locked`
Expected: only version lines change (`git diff --stat` shows no other content in those files)

- [ ] **Step 3: CHANGELOG** entry `## [0.8.21] - 2026-11-18` (Indonesian): laporan bulanan "Logbook Threat Information
  Feeds" dari registry scraper, kolom dan aturan Notes, `ScraperMeta.added`/`source_url` wajib untuk scraper baru.
  Check the parser: `uv run python -c "from cti_api.routers.changelog import _parse; print(_parse()[0]['version'])"`
  prints `0.8.21` (if the key differs, print the dict and read the version from it).

- [ ] **Step 4: Full verification**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy packages/cti-core/src packages/cti-scraper/src && uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro && uv run pytest tests/integration -q`
Expected: all green (integration needs Docker, ~7 min, run in background)

- [ ] **Step 5: Sample for the user.** Generate one workbook against the local test data (or dev, read-only) into the
  session folder and ask the user to open it in Excel: layout, logo, legend, signature block, a few rows.

- [ ] **Step 6: Commit** `chore(release): 0.8.21 - feeds logbook report`
