# Broken Legacy Scripts

Scripts proven broken **before** the rewrite. This matters because:

- A broken script **does not need a golden test** — there is no correct behaviour to
  preserve, so it should not be a cutover gate.
- Its bugs **must not be ported** to the new plugin.
- Some are probably better dropped than rewritten.

Status: `CONFIRMED` = verified directly from the source or by execution.

---

## Total crash

### `securityaffairsThreat.py` — `CONFIRMED`
```
NameError: name 'html' is not defined
```
Uses `html.fromstring()` but never does `from lxml import html`.
`requestsTemplate.py:4` has that import; this file lost it when it was
copied. **Crashes every time cron runs, silently, forever.**

The new framework removes this whole class of bug — `XPathScraper` imports
`lxml.html`, not the scraper file.

### `theRecordThreat.py` — `CONFIRMED` (new finding)
```
5 items pushed, then: NameError: name 'message_list' is not defined
```
Runs **halfway**: pushes 5 articles successfully, then crashes. Because
`is_new_and_mark` has already marked every key before the crash, the failed articles
are never retried. This is exactly the "mark before processing" failure that
two-phase dedup fixes.

---

## Silently broken (runs, but wrong)

### `cisacatalogThreat.py` — `CONFIRMED`
Emits labels without the literal word `"FROM"`:
- `"NEW CISA CATALOG VULNERABILITY"`
- `"NEW CISA CATALOG VULNERABILITY (RELATED)"`

`nlp.py:341` does `str(script_name).upper().split("FROM")[1]` → `IndexError`
→ **every job from this scraper dies in the worker.** 3 of the 198 labels are affected.

There is also a dead branch at L40-51: both sides of the if/else are identical except for the label string.

### `nlp.py:421` — `CONFIRMED`
```python
zero_day_list = re.findall(r"\\b(zero|0)[-.]day\\b", ...)
```
A raw string, so `\\b` is read as a literal backslash+`b`, not a word boundary.
**Zero-day detection never matches.**

> Verified: L35/396/400/414 use **non-raw** f-strings where `"\\b"`
> becomes a correct `\b`. **Do not change them too.**

### `articleValidator.py:141-146` — `CONFIRMED`
Parses the LLM output via `.replace("\n","").replace("```","").replace("json","")`
then `json.loads` **twice**. Articles whose title contains the word "json"
break the parsing.

### `anyrunTrendThreat.py` — `CONFIRMED` (new finding, Phase 4)
Collects the "Top 10 Malware Trends" summary from `any.run/malware-trends/`
into one string (`featured_message`), but **never calls `push_job()`
or `is_new_and_mark()` at all** -- it does not even import them. The string is
just computed and then THROWN AWAY (not `print`ed, not written anywhere).
The Phase 0 fixture confirms it: `expected_items.json` is `[]` on every recorded
day -- consistent; this scraper has never produced any output,
not just a quiet feed.

Different from `huntressThreat.py` (below, same family): huntress's logic is
complete but blocked by `exit()`, so it was still straightforward to salvage.
This one was incomplete from the start -- it is unclear WHAT it was meant to send (one text
summary per week is not an `ArticleItem` shape; continuing it would need a new Item type).
**Deliberately not ported** in Phase 4 -- it needs a product decision
(continue it as a new feature or consider it unused), not a mechanical
extraction. See `scrapers/src/cti_scrapers/feeds/huntress.py` for
a SIMILAR case that was salvaged.

### `huntressThreat.py` — `CONFIRMED` (new finding, Phase 4)
`print(message_list); exit()` right before the
`push_job()`/`is_new_and_mark()` loop -- that loop is **never reached**,
so this scraper never actually sent anything even though its extraction
logic (CSS locators + `.inner_text()`/`.get_attribute("href")`)
is still valid and complete. **Salvaged** -- ported by hand to
`scrapers/src/cti_scrapers/feeds/huntress.py` (XPath family, CSS classes
translated to XPath `contains()`); the `exit()` bug was DELIBERATELY not carried over.

### `socradarThreat.py` — `CONFIRMED` (new finding, Phase 4)
Loops `for i in range(1, 5)` but its XPath never uses `{i}` --
every iteration runs EXACTLY the same XPath query. `is_new_and_mark()` uses the key
`title+url`; the first iteration marks that key, the other 3 iterations are skipped
in the same run. **Effect: always just 1 item per run** (fixed
position), not 4 as the loop suggests. Ported by hand to
`scrapers/src/cti_scrapers/feeds/socradar.py` with `max_items=1` --
verified by a golden test matching exactly 1/1.

### `supportFile/offsetAlert.py` — `CONFIRMED`
The only dead-scraper detector that ever existed. Shells out to
`find offset/ -mtime +30`. **Silently broken** when dedup moved to Mongo —
the offset files stopped being touched, so every scraper looked dead. It also uses
`stat --format` (GNU) and a hardcoded `+0700`.

---

## Cannot run on the deploy host

### 8 Selenium scrapers — `CONFIRMED`
```python
CHROMEDRIVERLOC = "./chromedriver_mac64_arm64/chromedriver"
```
A **macOS ARM64** binary, in a repo that deploys to Linux `/opt`. These eight scrapers
**could never run in production**.

This means that rewriting them as `XPathScraper(render=True)` is **new work,
not a migration** — there is no baseline to compare against, so they cannot be
golden-tested. Treat them as new features with manual acceptance.

**Final outcome for 7 of the 8 (Phase 10.1c, 2026-09-18 & 2026-09-30)** -- a `waiver` for
the 10.D gate, per scraper:

| Old scraper | Outcome | Notes |
|---|---|---|
| `mandiantThreat.py` | **Salvaged** | The site moved to the Google Cloud Blog, which turns out to provide an official RSS feed -- a plain `RSSScraper` (`mandiant.py`), NOT `render=True` at all. Live, `enabled=True`. |
| `0xToxinThreat.py` | **Salvaged** | The homepage provides an official Atom feed -- `RSSScraper` (`toxinlabs.py`). Found a new bug: the feed pastes IOC content carrying bytes that are illegal in XML, fixed IN THE FRAMEWORK (`RSSScraper._parse_feed`, see `families/rss.py`). Live, `enabled=True` -- but the blog itself has been completely dead since August 2023, so realistically it will never trigger a new alert. |
| `forcepointThreat.py` | **Salvaged** | `XPathScraper(runtime="browser")` (`forcepoint.py`); the site's card structure is already different from the old script (a union XPath, not a fixed index). Live, `enabled=True`. |
| `trellixThreat.py` | **DROPPED (user decision 2026-09-30)** | The selector is correct (`indexed=True`, same as the old script, verified by hand + unit test), BUT production fetches are blocked by Trellix's CDN (`net::ERR_HTTP2_PROTOCOL_ERROR`, consistent across 2 networks; NOT attempted to bypass -- bot-detection evasion is out of scope). The `trellix.py` file has been removed from the tree. |
| `vxMalwareDefenseThreat.py` | **Not ported, waiver** | Its source (`vx-underground.org`) now requires a Cloudflare Turnstile captcha for the WHOLE domain (even through a real interactive browser). Checked 2 alternatives from vx-underground's official channels (GitHub `VXUG-Papers` -- a different category; the public Telegram -- unstructured), no suitable replacement found. |
| `emailnewsThreat.py` | **Outside the framework's scope, PARKED** | Not a web scraper -- it polls a Gmail inbox via IMAP. The `RSSScraper`/`XPathScraper` framework has no family for this. A hardcoded Gmail app password was found (`docs/SECRETS_ROTATION.md` item #14, its rotation delegated; migrating the script itself is parked at the user's request). |
| (not one of the 8 Selenium ones, but found & handled together) `cyborgHuntingIdea.py` | **Out of scope, PARKED** | Not an alert scraper -- a one-off research tool that logs into the paid Cyborg Security Hunter product and dumps local JSON, with no `push_job`/`send_alert`/`nlp_scan`. A hardcoded login credential was found (item #15, treated the same as above). |

Full detail for each item: `docs/PROGRESS.md` 10.1c.

### `supportFile/nlp_worker.service` — `CONFIRMED`
`ExecStart` points to `supportFile/nlp_worker.py`, but the file is at the repo
root. With `Restart=always`, this unit **crash-loops forever**.

---

## Phase 0 fixtures stored the wrong resource (not a scraper bug)

Found during the bulk golden-test verification of the 57 Phase 4 generated results —
two `runtime="browser"` scrapers failed with `ParseError` even though the extracted
XPath/URL are structurally correct (copied as-is from old Playwright locators
that were proven to work). The root cause is NOT in the code but in the
fixture bytes recorded in Phase 0:

### `checkpointThreat` — `CONFIRMED`
The fixture (`tests/fixtures/checkpointThreat/*.input.html`, 2073 bytes) contains
an **AWS WAF** bot challenge page (`AwsWafIntegration.saveReferrer()`,
`checkForceRefresh()`...), not `research.checkpoint.com` content. This site
is behind bot protection; the Phase 0 recorder got stuck on the challenge page before
it could capture the real content.

### `cloudflareThreat` — `CONFIRMED`
The fixture (`tests/fixtures/cloudflareThreat/*.input.xml`, 357KB) contains **the Cloudflare
blog RSS feed** (`https://blog.cloudflare.com/`), not the HTML of the
`resource-hub` page that the original scraper XPaths. The recorder probably got caught by a
mismatched request/redirect (the site has many endpoints).

**Implication:** the golden-test mock (`page.route("**/*", ...)` returning the same fixture
bytes for every request) cannot "fix" a fixture that was recorded wrong from
the start — a different site than intended is still a different site even when
replayed exactly. The fix is not in `tools/codemod/extract.py`; it is to
record it AGAIN live when its `enable` turn comes (`cti-scraper verify --record`, see
[ADDING_A_SCRAPER.md](ADDING_A_SCRAPER.md)).

## Deliberate divergence — not a bug, do not "fix" it to pass byte-exact

Found in the same bulk golden-test verification. The golden test compares
**byte-exact** against the OLD script's output (including its quirks) — when
the framework is deliberately more correct than the original, the result "fails" in the
diff even though it is not a regression.

| Scraper | Symptom | Why it is not a bug |
|---|---|---|
| `anyrunThreat` | Golden-test URLs differ: the fixture has `https://any.runhttps://any.run/...` (doubled), the new scraper `https://any.run/...` (correct) | The old script did `"https://any.run" + featured_link` although the RSS `<link>` is already absolute — an old bug, DELIBERATELY not ported |
| `qualysThreat`, `resecurityThreat`, `rhinosecThreat` | 1-3 items differ per scraper, only by whitespace/NBSP at the end of the title | The old script used the raw `item.find('title').text`, never `.strip()`. The new `RSSScraper` ALWAYS strips titles — a deliberate fix, not a regression |
| `elasticLabThreat`, `esetThreat`, `fortinetThreat`, `starlabsThreat`, `vectraThreat`, `akamaiThreat`, `f5Threat` | Exactly `ScraperMeta.max_items` (default 50) items generated, the fixture has more (up to 298) | `max_items` is a deliberate cold-start guard (see the plan, §"Postgres + DB kosong") — not an extraction gap |
| `cisaThreat`, `wizThreat` | Same pattern as qualys/resecurity/rhinosec above | Same reason — titles were not `.strip()`ped in the old script |
| `articThreat` | Golden test 10/20 (an exact subset, no stray items) | **A test harness limitation**, not a scraper bug — see the section below |

## Golden-test harness limitation — scrapers that hit >1 URL per run

`cti_scraper.testing._build_http_transport()` (used by the golden test of EVERY
`runtime="light"` scraper) returns the SAME `fixture.primary_body` for
ANY request, regardless of the URL — `Fixture.primary_body` itself only
reads `input_files[0]`. That is fine for single-request scrapers (the majority), but
FAILS for two patterns:

- **Multi-feed** (`artic.py`, two Arctic Wolf URLs) — both requests get the
  SAME bytes, the scraper parses the same feed twice,
  `article_keys()` (returns a `set`) removes the duplicates itself, and the golden test
  looks like it is "missing items" even though the `feeds` tuple is correct.
- **CHAINED multi-request** (`blackorbird.py`, `unit42_github.py` —
  GitHub commit watchers: the first request lists commits, the SECOND gets the details of a
  specific commit using a SHA from the first response) — the second request gets the
  FIRST response's bytes again (the commit list, not the details), and parsing crashes
  (`KeyError`/`TypeError`) even though the real live run works perfectly. It turned out
  that `_RecordingTransport` (`verify --record`) ALREADY records
  separate bytes per URL correctly (`*.input.1.json` to `*.input.14.json` for
  `unit42_github`) -- only the REPLAY is missing; the `MockTransport` in
  `_build_http_transport` only ever tries file index 0.

**Not a scraper bug** — both were verified via `dry-run` (REAL
network, a valid GitHub token): `blackorbird` `status=ok items_found=1`,
`unit42_github` `status=ok items_found=3`, both as expected.
`verify --record` also successfully records the complete bytes (per URL, not just
one). To golden-test multi-request scrapers accurately,
`Fixture`/`_build_http_transport` needs a PER-URL mock (reading the matching
`input_files[i]`, not always index 0) — not done yet;
a new item for the testing harness backlog, not Phase 4.

**A third class that cannot be golden-tested AT ALL through this harness**:
scrapers that declare `ScraperMeta.reference_data` (`new_cve.py`,
`github_poc_monitor.py`) need `ctx.reference` filled from OUR Postgres
BEFORE `fetch()` runs -- `cti_scraper.testing.make_fixture_context()`
does not touch this at all (it was built before `reference_data` existed).
They were verified via LIVE `dry-run`/`run` against a local Postgres (docker-compose)
+ the real API instead -- see PROGRESS.md Phase 4.9 for the full
results. To golden-test this kind of scraper, the harness needs a way to
inject a fake `reference` too, not just the HTTP transport -- not done yet,
the same backlog as the multi-request limitation above.

## How to add to this list

The fixture recorder looks for these automatically. After each run:

```bash
python3 -c "
import json,sys
for r in json.load(open(sys.argv[1])):
    if r['status'] not in ('ok',): print(r['scraper'], r['status'], (r.get('error') or '')[:80])
" fixture_report.<date>.json
```

---

## Final result of the Phase 0.5 recording (2026-09-16 & 17)

**53 of the 96 active jobs (55%) have a valid baseline** (`ada_item`). Below the
original target (≥85), but per the decision the rest **do not block** — they go through the
`dry-run`/`verify` flow one by one when their turn comes in Phase 4
(see [ADDING_A_SCRAPER.md](ADDING_A_SCRAPER.md) — `verify` records a
live baseline if none exists).

| Category | Count | Action |
|---|---|---|
| Has items, valid baseline | **53** | Ready to be a golden-test gate |
| Has a directory, 0 items on both days | 38 | Check one by one in Phase 4 (table below) |
| No directory at all | 5 | Record in Phase 4; nothing odd, they just had not had their turn yet |

### Needs REAL credentials — deferred to testing time (user decision)

9 scrapers cannot get a valid baseline with a dummy config — tested with
empty tokens, all of them were blocked/errored by their APIs (GitHub 401/403, NVD
empty, twitterapi.io needs a paid key). **The user will create new tokens later
when testing these scrapers, not now:**

| Scraper | Needs | Result with an empty token |
|---|---|---|
| `githubTTPs`, `mitreGithub`, `blackorbirdGithub`, `githubAptTTPSimulation`, `githubSophoslab`, `deepdarkCTI`, `githubUnit42` | GitHub PAT | Blocked 401/403 (anonymous rate limit) |
| `githubPOCMonitor` | GitHub PAT + read access to `cve_tracker` (for the FP filter) | Blocked + `ConnectionError` |
| `newCveThreat` | NVD API key | `TypeError: NoneType` (empty response) |
| `monitorX` | twitterapi.io key | `TypeError` (the response is not the expected JSON) |

⚠️ **`newCveThreat.py` and `githubPOCMonitor.py` create a `MongoClient` directly
from config — NEVER give the real config to the recording harness.** `pymongo.MongoClient`
is already patched to be inert in `record_fixtures.py`, so it is safe even when these two files
are tested — but if they are ever verified by hand outside the harness (not through
`record_fixtures.py`), make sure it still goes through `dry-run`, where the framework
provides a safe sink, not by running the raw script directly.

### Real errors, not dependencies — check one by one

| Scraper | Error | Suspicion |
|---|---|---|
| `landthThreat` | `IndexError: list index out of range` | Probably a real bug — same pattern as `securityaffairsThreat` |
| `techstackGO`, `techstackNPM`, `techstackPYPI` | `ValueError: time data '...571293679Z' does not match format` | **A real bug.** `%f` in `strptime` only reads 6 digits of microseconds, the API returns 9 digits (nanoseconds). Needs `datetime.fromisoformat` or truncating the precision. |
| `groupibThreat`, `cisThreat`, `cymruThreat`, `anyrunTrendThreat`, `k7securityThreat` | `TimeoutError: Page.goto 30000ms` | Could be a slow site, could also be an effect of `--jobs 8` (8 Chromiums at once on a laptop) — try serially before concluding the site really is slow |
| `intel471Threat` | timeout (90s) | Same possibilities |
| `prodraftThreat` | `TargetClosedError` (Playwright) | The browser crashed mid-run; retry first |

### Zero items, not yet clear whether legitimate or broken

One was proven **legitimate**: `crowdstrikeThreat` filters on the category
`"Counter Adversary Operations"` — its feed had 1 item that day, which just did not
pass the filter. Not a bug. `threatActorTrendGraylog` is probably legitimate too (it reads
`supportFile/ThreatActorName.txt`, which may simply be empty).
**CORRECTION 2026-10-01:** the "legitimate" conclusion for `crowdstrikeThreat` is STALE -- the site has renamed
the category and now ALL items are dropped by the filter (see the table below).

**Update 2026-10-01 -- EVERYTHING on the "not yet checked" list above has been checked and handled**
(staging census + direct probes of the sites, Phase 10.D; details in `docs/PROGRESS.md` 10.D). The table
below supersedes the 2026-09-30 version. Final result per scraper:

| Scraper | Root cause (verified) | Action | Status |
|---|---|---|---|
| `doyensec` | Phase 4 migration bug: an Atom feed but the codemod produced an `RSSScraper` with RSS defaults | Atom `item_path`/`link_attr` | Fixed |
| `trustwave` | Rebranded as LevelBlue; the old URL 301s to a deliberately emptied stub | New feed URL | Fixed |
| `aquasec`, `groupib`, `huntress`, `landth` (now Depi), `sysdig`, `cymru`, `cloudflare`, `intel471`, `k7security` | Stale absolute XPath; the sites turned out to have official RSS feeds (found by probing common paths) | Replaced with `RSSScraper` | Fixed (see the scope note) |
| `abnormalsecurity`, `huntio`, `prodraft`, `sans`, `splunk`, `proofpoint`, `cis`, `dragos` | Stale absolute XPath, the site is alive but has no RSS | `link_card_xpaths` (href pattern, not div position) | Fixed |
| `sentinel` | The category filter inherited from the old script ("From the Front Lines") no longer exists in the feed: 10/10 items dropped | New category added | Fixed |
| `crowdstrike` | The category "Counter Adversary Operations" was renamed to "Threat Hunting & Intel" -- the Phase 0.5 "legitimate filter" conclusion is STALE | New name added | Fixed |
| `github_poc_monitor` | ~100 requests/run vs a 30/minute budget with no waiting logic (+ a staging DB override of 10/minute): 76 runs, 0 successes | `get_waiting` (wait for the window to reset) + override removed | Fixed |
| `new_cve` | Same: 22 of 44 runs died `rate_limited` at MITRE/NVD/Tenable | `get_waiting` | Fixed |
| `monitor_x` | twitterapi.io credit exhausted (402) but runs were `empty` WITHOUT an error message (`break` per account) | 401/402/403 fail hard (`ParseError`) -- proven: 120 runs overnight failed with the message `HTTP 402` | Code fixed; **credit exhausted AGAIN** since 2026-10-01 14:53 UTC (~3 hours after the new key); schedule lowered from `*/15` to every 3 hours = the legacy cadence (2026-10-02) |
| `trending_cve`, `tweet_alerts_*` | twitterapi.io credit exhausted (402), the balance is shared by 4 scrapers | Recovered briefly after the new key, then 402 again | **Waiting for a top-up / a frequency decision** |
| `blackberry` | The old URL redirects to a secure-communications (marketing) blog, not CTI | `enabled=False` | **WAIVER** |
| `koisec` | `koi.security` & `koi.ai` redirect to a Palo Alto product page | `enabled=False` | **WAIVER** |
| `google` | The TAG feed is 404; the replacement = the whole Google blog feed | `enabled=False` (`google_cloud`/`mandiant` already cover it) | **WAIVER** |
| `cisa` | `all.xml` answered with an Akamai WAF 403 on 19/19 runs -- NOT flaky (the old suspicion was wrong) | `enabled=False`, bot protection not bypassed (KEV still comes through `cisa_kev`) | **WAIVER** |
| `nquiring_minds` | The old feed is 404; the new feed contains template posts, not CTI | `enabled=False` | **WAIVER** |
| `mitre_github`, `techstack_pypi` | `empty` is LEGITIMATE: mitre only fires on release commits "Update with ATT&CK vNN.N" (<=7 days, released 2x/year); the 5 latest versions of `requests`/`selenium`/`pandas` really have 0 advisories on deps.dev | None | Legitimate |
| `asec_ahn`, `bizone`, `exploitdb`, `resecurity`, `techstack_npm` | Occasionally flaky (3-11 failures out of ~20-30 runs/24 hours: 429, timeout, HTTP 522, dropped connection), not systematic | Unchanged -- covered by the beat retry backoff (PR #1) | Monitored |

**Scope notes that CHANGED** (the article count vs legacy differs on purpose, not a gap -- see
`docs/PARALLEL_RUN_COMPARISON.md` §1): `cloudflare` (resource-hub reports -> the blog's `security` tag),
`intel471` (whitepapers -> blog), `huntress`/`sysdig`/`cymru` (the whole blog feed, without the old category filter), `sans` (ALL white papers, not just the former focus areas), `landth` (the domain became
`depi.security`, old articles on a different host), `sentinel`/`crowdstrike` (new category taxonomy).

**`intel471` only recently stable from the staging egress:** its site (Vercel) answered 429 after several consecutive
requests from two different IPs during repeated dry-runs; but on the hourly beat overnight 12 of 12 runs were `ok`
(2026-10-02). If 429 shows up in production, it becomes a waiver candidate -- it is their protection, and we do not try to bypass it.
