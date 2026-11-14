# FigCraft redesign, sub-project 5a: Dashboard

Date: 2026-11-14. Status: draft for review. Branch: `claude/figcraft-design-data`. Same one-PR release 0.8.16
(the CHANGELOG entry and the 0.8.16 runbooks are extended, no extra version bump).

## 1. Context and goal

Sub-projects 1 to 4c delivered the shell and the shared primitives in `apps/web/src/components/ui/` (`HeroPanel`
with `heroLinkClass`, `StatTile`, `Chip`, `StatePanel`, `Notice`, `SegmentedControl`, `Disclosure` with `printOpen`
and `headingLevel`, `BarSeries` with `highlight`, `ShareBar` with `SHARE_BAR_SEGMENT`, `MeterBar` with `onHero`,
`LegendRow`, `Sparkline`, `Table framed`), `PageHeader` with `kicker`, the browser-timezone formatters in
`lib/format.ts` (`fmtTime`, `fmtDateTime`, `fmtShortDate`, `fmtAgo`, `fmtCompactAge`, `parseLocalDate`),
`lib/use-page-title.ts::usePageTitle`, `lib/exec/query.ts::isClientError`, the `unwrap` / `noClientRetry` pair in
`lib/scrapers/queries.ts`, `lib/api/client.ts::proxyFetch` and the session-expired dialog. Sub-project 5 is split
into **5a Dashboard (this spec)** and 5b Newsroom.

FigCraft frames (light; dark variant in brackets): Dashboard / v5 Combo 2 (702) and Dashboard / States 32816
(33283). The dark frames carry the same strings as the light ones. There is no frame for loading, for anything
below 1440, or for the features the v5 frame leaves out (brief, weekly ransomware chart, client context, articles
over time, Threat Actor Room). The Session expired state of 32816 was built in 4c and is not touched.

Today `/dashboard` is the 0.7.1 redesign: a client page (`app/(app)/dashboard/page.tsx`) with `SignalHero`, a
five-number KPI strip, five summary cards and four chart.js cards. Its copy is mostly Indonesian, two sentences are
built in Indonesian by the API (`brief`, `window_label`), errors are a red text line without retry, and it uses
none of the sub-project 1 to 4 primitives.

Goal: deliver the **full v5 mockup, keep every existing feature reachable** (DB1-DB20, table in 6.9) and add the
six backend items the mockup needs (B-D1 to B-D4, B-N1, B-N2). Backend lands first, the contract is regenerated
once, then the page is built on real data. The inventory behind this spec
(`.superpowers/brainstorm/sp5-inventory.md`, not committed) lists every frame element and its source; where they
differ, this spec wins.

## 2. Decisions (binding, from the user)

Scope
- **S1** 5a covers `/dashboard` only, plus the two shared article fields (B-N1, B-N2) that 5b reuses. Newsroom,
  `ArticleModal` restyling and the reader pane are 5b.
- **S2** Full mockup; every pre-redesign feature stays reachable, re-homed where the mockup has no place (6.9).
- **S3** Release stays 0.8.16, one PR; `CHANGELOG.md` (Indonesian), `docs/prod-upgrade/0.8.16.md` and
  `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` are extended. **One migration** (B-N1), no `.env` key.
- **S4** All inventory defaults D1-D19 are accepted. Those that shape 5a:

| Id | Decision |
|---|---|
| D1 | Split 5a Dashboard / 5b Newsroom; B-N1 and B-N2 ship in 5a. |
| D2 | English copy. The UI composes its sentences from numbers; the API's Indonesian `brief` and `window_label` are no longer rendered. |
| D3 | Store the summary the pipeline already computes; show the dek when present, hide it when `null`; no backfill, no LLM call. |
| D4 | Relative time from `first_seen_at` for items under 24 h old, the date otherwise. |
| D5 | Period switch 24h / 7d / 30d / 90d / All, default 7d; hero texts follow it; the four charts are fixed at 30 days. |
| D6 | A small "Threat news only" toggle beside the period. A "More" disclosure holds articles over time, Threat Actor Room, the weekly ransomware chart and the client context numbers. The brief sentence and "Updated HH:MM" are dropped. "n without a ticket" and "n PIRs" stay as second lines. |
| D7 | Build B-D1 to B-D4. No "Spikes: …" caption (the three highest bars are highlighted instead). No open-CVE history (B-D5 skipped). |
| D8 | Trending lists Actor, Malware and CVE, with a "Ransomware" chip for ransomware groups and a "NEW" chip; techniques leave the list. |
| D10 | Article clicks open the existing `ArticleModal` in 5a; 5b switches them to Newsroom `?view=all&article=<id>`. |
| D17 | "No data yet" when the client has no tech stack and no watchlist, button "Set up tech stack" → `/cve`, copy about matching. LLM banner for `view_ops` users only, "ATT&CK tagging is catching up". Per-panel error with Retry; the page is never blanked. |
| D19 | Separate priority and grade chips; priority tones ≥ 90 red, ≥ 70 amber, else blue. |

Declined: B-D5 (daily snapshot of open critical CVEs) and B-D6 (`GET /api/dashboard/pipeline`).

Choices this spec makes that the user did not spell out (each is flagged for review):
- **P1** The period lives in the URL as `?period=1|30|90|all`; 7d is the absence of the parameter. The "Threat
  news only" toggle is component state (default on) and is not in the URL.
- **P2** "24h" is `days=1`, which the API reads as "dated yesterday or today"; the headline suffix for it is
  "since yesterday". The KEV row is prefixed "Open now" because that count ignores the period (C4).
- **P3** B-D2 adds five fields to `DashboardAttention`, not one: `kev_tech`, `ransomware_prev_in_client_scope`,
  `ransomware_client_top_industry`, `watchlist_top` (the inventory's B-D2) and `client_countries` (so the hero
  does not depend on the map request for its wording).
- **P4** The stored summary is **not LLM text**. `summarize()` is an extractive LSA summary (sumy): sentences
  copied verbatim from the article, as many as the article has paragraphs, and the whole article text when the
  summarizer fails. B-N1 therefore stores a capped excerpt (`make_dek`, at most 600 characters), not the raw
  value (C28, section 9).
- **P5** The fourth "By the numbers" row (open critical CVEs) has no sparkline; its slot stays empty.
- **P6** The lead byline prints one source; the source count is in the kicker. No extra `story_id` request.
- **P7** Relative times use the house formatters ("2 h ago", "7 h"), not the mockup's "2 hrs ago" / "7 hrs".
- **P8** The signal map opens on an APAC view with a "World" switch; "TOP COUNTRIES" follows the view.
- **P9** The "No data yet" panel replaces the hero's headline and three rows (the map stays); its copy is in 6.7.
- **P10** The LLM banner reads `GET /api/data-health` once per page load without polling; its copy is in 6.7.
  Articles whose `llm_ttp_status` is `pending` carry an "ATT&CK PENDING" chip.
- **P11** Trending keeps "+n%" as small text beside the count (DB11); the mockup shows no percentage.
- **P12** The CVE watchlist header reads "Open CVEs in your tech stack, KEV first" (C12) and the "tickets closed"
  line stays as a footer.
- **P13** "Top techniques" lists five with a "Show all 10" button.
- **P14** The panels inside "More" keep their existing chart.js components and load only when it is first opened.
- **P15** `dashboard/page.tsx` becomes a server component with static `metadata`; `dashboard/layout.tsx` is
  deleted.
- **P16** The wording of the "Why it ranks first" lines (6.4).
- **P17** The page has a `view_news` gate (today it has none and shows eleven failed cards).
- **P18** Must-read rows keep small "Incident", "Watchlist", "Tech stack" and grade chips on the meta line (DB10).
- **P19** `/api/dashboard/trending` gets `kinds` (default `actor`, `ttp`) and `TrendItemOut.ransomware_group`.
- **P20** The four month charts follow the "Threat news only" toggle; the subtitle says so.
- **P21** The Dashboard no longer sends `incident_only` to `/api/dashboard/attention` (it only shaped the brief).

## 3. Conflicts between inputs, and how they are resolved

- **C1 Language.** Page copy, the `id-ID` date and two API-built sentences are Indonesian; the mockup and the
  rest of the app are English. English everywhere (D2). `brief` and `window_label` stay in the API responses
  (the Newsroom topics strip still prints `window_label` until 5b) and are not rendered on the Dashboard.
- **C2 Already redesigned once.** The mockup removes the brief, the client context card, Threat Actor Room and
  the weekly ransomware chart. All but the brief sentence move into "More" (D6).
- **C3 Default period.** Mockup 7d and a 24h option; code 30 days and 7 / 30 / 90 / all. Mockup wins (D5).
- **C4 Period wording in the hero.** The frame prints "since yesterday" and "30 days" while 7d is selected. The
  headline suffix and the map subtitle follow the selected period (table in 6.2). One row cannot follow it:
  `kev_in_stack` counts KEV CVEs that are **open now**, whatever the period. Its second line starts with "Open
  now" (P2).
- **C5 "Ransomware victims in Indonesia".** The count is "victims in the client's countries", which can be none,
  one or several, and the Newsroom link accepts one `country`. Title and link by number of countries (6.3).
- **C6 Watchlist sample "Lazarus, banking phishing, QRIS".** The watchlist is watched actors only. The second
  line prints up to three actor names (`watchlist_top`) and the PIR count (D6); keywords are not shown.
- **C7 Time of day.** `articles.posted_on` is a date. Relative time comes from `first_seen_at` (when the scraper
  first saw the article), which is not the publication time, so the element carries `title="First seen
  {fmtDateTime(first_seen_at)}"` (D4, 6.4).
- **C8 "11 on KEV · all tracked".** `open_kev` counts open KEV CVEs of any severity, not a share of the critical
  ones. The row prints "{open_kev} open KEV (any severity)" and "all KEV have a ticket" only when
  `kev_without_ticket` is 0, else "{n} KEV without a ticket".
- **C9 Fixed 30-day charts under a period switch.** Kept as drawn (D5); the section subtitle states the window.
  "all sources" is true for every toggle state and is kept; "threat news only" is appended when the toggle is on
  (P20).
- **C10 Panel-error sample cards** ("Threat pulse", "Sector heatmap") do not exist on the v5 frame. The state is
  applied to the real cards; the sample "The query timed out after 30 s" is replaced by the server message (C23).
- **C11 Industry share.** An article can carry several sectors and most carry none. The subtitle is "Share of
  sector mentions", not "Share of incident articles"; "General" is excluded and the note about articles without
  a sector stays (DB16).
- **C12 CVE watchlist.** The subtitle says "Open critical CVEs" but the list is "open CVEs, KEV first, then
  CVSS" (the sample itself has an 8.8 row), and "27" is `open_critical`, not the length of the list behind "View
  all". Header per P12. A "closed" ticket chip cannot occur in a list of open CVEs and is not built. The service
  serves 3 rows; B-D1 makes it 4.
- **C13 "No data yet".** Articles are global, so a new client sees the full feed at once; what is empty is the
  tech stack, the watchlist and the PIRs. "Scrapers run every 30 minutes" is not true for every source and
  "sectors" are not a client setting. Trigger and copy per D17 and 6.7.
- **C14 LLM-down copy.** "Summaries … are catching up" is wrong twice: the summary is not produced by the LLM
  (P4), and articles whose relevance needs the model are not in the feed at all while they wait. The banner
  says "ATT&CK tagging is catching up" and names both queues (6.7). The "SUMMARY PENDING" chip becomes "ATT&CK
  PENDING", driven by `llm_ttp_status == "pending"`. The breaker state is behind `view_ops`; other roles see no
  banner (B-D6 declined).
- **C23 Error copy.** The web client has no 30 s timeout. Error panels print the message of the failed response.
- **C25 Priority chip.** `priority_score` is not capped at 100 (it can reach 176). The chip prints the raw
  number; the tone bands of D19 apply to it as it is.
- **C28 Summary.** The frame draws a two-sentence dek. The pipeline's `summary` is an extractive summary of
  unbounded length (P4). The stored value is capped at 600 characters and the UI clamps it to three lines on
  the lead and two on Must-read rows.
- **C29 Layout title.** `dashboard/layout.tsx` sets a string `metadata.title`. Resolved by P15.
- **Mockup byline "BleepingComputer, CISA KEV".** A second source name needs one more request per page load
  (`/api/articles?story_id=`). Not built (P6); the kicker already prints "{n} SOURCES".
- **Mockup sparkline on "open critical CVEs".** There is no history of that number (B-D5 declined). No sparkline
  (P5).
- **Mockup map.** The frame draws APAC only, with no legend, tooltip, click-through or client ring. The code
  draws the world with all four. APAC is the default view and the four features stay (P8, DB5, DB6).
- **Mockup "Up 6 from last week".** "Last week" is a calendar week; the number is "same-length window before
  the current one". Copy: "Up 6 from the previous 7 days".

## 4. Backend

Conventions. All six items are additive. Routes stay in `routers/articles.py` under the router dependency
`view_news`; no new route, so `tests/unit/test_route_permissions.py` is untouched. Comments and docstrings in
Indonesian, matching the files. Client-scoped numbers keep using `effective_client_id(user, x_client_id)`.
Repositories are in `packages/cti-core/src/cti_core/db/repositories/` (mypy strict applies).

### 4.1 B-D1 `cve-exposure` takes a row limit
- **Contract.** `GET /api/dashboard/cve-exposure` gains `limit: int = Query(3, ge=1, le=10)`. Response schema
  `CveExposure` unchanged; `items` holds at most `limit` rows. The default keeps today's behaviour.
- **Logic.** `dashboard_overview.get_cve_exposure(session, *, client_id, days, limit: int = 3)` passes `limit` to
  `AsyncDashboardRepo.cve_exposure(limit=…)`, which already takes it. Order is unchanged: KEV first, then CVSS
  descending with nulls last, then `cve_id`.
- **Tests.** `tests/integration/test_dashboard_overview_api.py::test_cve_exposure_limit_param`: five open CVEs
  seeded; no parameter → 3 rows, `limit=4` → 4 rows in the documented order, `limit=0` and `limit=11` → 422.

### 4.2 B-D2 `DashboardAttention`: names and a previous window for the hero
- **Contract.** `schemas/dashboard_overview.py::DashboardAttention` gains:

| Field | Type | Meaning |
|---|---|---|
| `kev_tech` | `list[str]` | At most 3 distinct `CveTracker.tech` values of the client's open KEV rows, most rows first, ties by name. Same scope as `kev_in_stack`. |
| `ransomware_prev_in_client_scope` | `int \| None` | Victims in the client's countries in the window of the same length just before the current one. `None` when `days` is `None`. |
| `ransomware_client_top_industry` | `NameCount \| None` | The industry with the most victims in the client's countries in the current window; `None` when no such victim has an industry. |
| `watchlist_top` | `list[str]` | At most 3 names of watched actors with the most distinct matching articles in the window, ties by name. |
| `client_countries` | `list[str]` | The client's ISO alpha-2 codes, sorted; the same list `DashboardMap.client_countries` returns. |

  `NameCount` moves above `DashboardAttention` in the file. No existing field changes; `brief` stays.
- **Queries** (all inside the cached `get_attention`, run sequentially on the one session):
  - `AsyncDashboardRepo.kev_tech_names(*, client_id, tech, exclude_cve_ids, limit: int = 3) -> list[str]`:
    `_open_cve_stmt(select(CveTracker.tech, func.count()).select_from(CveTracker).outerjoin(CveTicket,
    self._tracker_ticket_join()), …)` with `.where(CveTracker.cisa_kev.is_(True), CveTracker.tech.is_not(None))`,
    `group_by(CveTracker.tech)`, `order_by(func.count().desc(), CveTracker.tech)`, `limit`. It takes the same
    `_cve_scope` dict as `cve_exposure_counts`, so false positives and inactive tech are excluded identically.
  - `AsyncDashboardRepo.watchlist_top_names(*, client_id, posted_on_start, limit: int = 3) -> list[str]`: the join
    of `watchlist_hit_count` (`mention_rows(ACTOR)` joined to `EntityWatch` on `entity_id` and `client_id`) with
    `select(m.c.name, func.count(func.distinct(Article.id)))`, `group_by(m.c.entity_id, m.c.name)`, ordered by
    count descending then name.
  - `AsyncRansomwareVictimRepo.count_in_countries(*, since: datetime.date, until: datetime.date, codes:
    Collection[str]) -> int`: victims with `since <= coalesce(discovered, published) < until` and `country_code`
    in `codes`. Returns 0 without a query when `codes` is empty.
  - `AsyncRansomwareVictimRepo.top_industry_in_countries(*, since: datetime.date | None, codes: Collection[str])
    -> tuple[str, int] | None`: same date rule as `summary` (`when >= since`, or `when IS NOT NULL` for all
    time), `country_code` in `codes`, `industry` not null and not blank after `trim`, grouped by `industry`,
    ordered by count descending then name, first row. `None` without a query when `codes` is empty.
- **Window.** With `since = today - days`: the previous window is `since - days <= when < since`. No
  day-coverage rule is applied (victims are not articles); the UI prints the comparison whenever the value is
  not `None`.
- **Cache.** Unchanged key `client_id|days|incident_only|date`, 900 s. The Dashboard stops sending
  `incident_only` (P21), so it uses one entry per client and period instead of two.
- **Tests.** `tests/integration/test_dashboard_overview_query.py`:
  `test_kev_tech_names_orders_by_count_and_skips_closed`, `test_watchlist_top_names_scoped_to_client`,
  `test_ransomware_count_in_countries_window_is_half_open`, `test_ransomware_top_industry_ignores_blank`.
  `tests/integration/test_dashboard_overview_service.py`: `test_attention_previous_window_none_for_all_time`,
  `test_attention_kev_tech_excludes_false_positive`. `tests/integration/test_dashboard_overview_api.py`:
  `test_attention_new_fields_are_client_scoped` (two clients with different stacks, countries and watches; each
  sees only its own names), and `test_attention_client_without_countries` additionally asserts
  `client_countries == []`, `ransomware_prev_in_client_scope == 0` and `ransomware_client_top_industry is None`.

### 4.3 B-D3 Trending learns malware and CVE
- **Contract.** `TrendItemOut.kind` becomes `Literal["actor", "ttp", "malware", "cve"]` and gains
  `ransomware_group: bool = False`. `GET /api/dashboard/trending` gains `kinds: list[Literal["actor", "ttp",
  "malware", "cve"]] = Query(["actor", "ttp"])`. Without the parameter the response is what it is today plus the
  new key. `TopicOut` (`schemas/newsroom.py`) inherits both schema changes; `GET /api/newsroom/topics` does not
  pass `kinds`, so its items stay `actor` / `ttp`.
- **Repo.** `AsyncDashboardRepo.daily_entity_counts` accepts two more `dimension` values: `"malware"` →
  `mention_rows(*MALWARE_TYPES)` keyed by `m.c.name`; `"cve"` → `mention_rows(CVE)` keyed by `m.c.external_id`
  (the CVE id). The existing four dimensions and every existing caller are unchanged.
- **Service** (`services/trending.py`). `TrendKind = Literal["actor", "ttp", "malware", "cve"]`;
  `TrendItem.kind: TrendKind`; `TrendItem.ransomware_group: bool = False`. `rank_trends` passes the kind through
  instead of folding everything that is not `ttp` into `actor`. `get_trending(…, kinds: Sequence[TrendKind] =
  ("actor", "ttp"))` loops over the requested kinds in the fixed order actor, ttp, malware, cve using the map
  `{"actor": "threat_actor", "ttp": "ttp", "malware": "malware", "cve": "cve"}`; the cache key gains the sorted
  kinds. Ranking is one list across the requested kinds (as today across actor and ttp), limit 10.
  After ranking, `_flag_ransomware_groups` sets `ransomware_group` on actor items whose name equals a
  `ransomware_victims.group_name`, case-insensitively, through
  `AsyncRansomwareVictimRepo.known_group_names(names: Collection[str]) -> set[str]` (one query,
  `func.lower(group_name).in_(…)`, `distinct`; skipped when the list has no actor). Malware and CVE items keep
  `entity_id = None` (the web resolves them by type and name).
- **Not changed.** `get_attention` and `routers/newsroom.py` call `get_trending` without `kinds`.
- **Tests.** `tests/unit/test_trending.py::test_rank_trends_keeps_malware_and_cve_kinds`.
  `tests/integration/test_dashboard_overview_query.py::test_daily_entity_counts_malware_and_cve` (a `malware` and
  a `tool` mention with different names give two rows; a CVE mention is keyed by its id).
  `tests/integration/test_dashboard_overview_api.py`: `test_trending_default_kinds_are_actor_and_ttp`,
  `test_trending_kinds_param` (`kinds=malware&kinds=cve` returns only those; `kinds=bogus` → 422),
  `test_trending_flags_ransomware_group` (an actor named like a seeded victim group, in a different letter
  case). `tests/integration/test_newsroom_api.py` passes unchanged.

### 4.4 B-D4 Ransomware top groups: five
- **Contract.** None. `RansomwareOverview.top_groups` holds up to 5 items instead of 3.
- **Logic.** `AsyncRansomwareVictimRepo.summary(…, top_n: int = 3)` replaces the hard-coded `.limit(3)`;
  `get_ransomware` passes `top_n=5`; `get_map` and `get_attention` keep the default. The docstring's "3 teratas"
  is updated.
- **Tests.** `tests/integration/test_dashboard_overview_query.py::test_ransomware_summary_top_n` (six groups;
  default → 3, `top_n=5` → 5, ties by name). `test_ransomware_summary_and_weekly` passes unchanged.

### 4.5 B-N1 `articles.summary`
- **Where the summary is computed.** `packages/cti-enrich/src/cti_enrich/pipeline.py`, in `complete`: `summary =
  summarize(text)` (line 408 at HEAD `3697f78b`). It feeds IOC extraction, Tier 1, the TTP job input and
  `score_stage.score(title, summary, session)` and is then discarded: neither of the two `persist(…)` calls (the
  "Security Technology & Best Practices" branch and the main branch) receives it.
- **What it is** (P4). `stages/summarize.py::summarize` is sumy's LSA summarizer: it returns
  `max(1, text.count("\n\n") + 1)` sentences taken verbatim from the fetched article text, the whole text when
  parsing fails, and `""` when no text was fetched. It is not LLM output.
- **Excerpt.** New pure function in `stages/summarize.py`:
  `make_dek(summary: str, *, max_chars: int = DEK_MAX_CHARS) -> str | None` with `DEK_MAX_CHARS = 600`.
  1. `s = " ".join(summary.split())`; empty → `None`.
  2. `len(s) <= max_chars` → `s`.
  3. Otherwise `cut = s[:max_chars]`; if `cut` contains ". ", "! " or "? " at an index of 200 or more, return
     `cut` up to and including the punctuation mark of the last such occurrence.
  4. Otherwise return `cut.rsplit(" ", 1)[0]` followed by an ellipsis character (U+2026).
  It imports nothing from `nltk` / `sumy`, so it runs in every image and in CI.
- **Model.** `packages/cti-core/src/cti_core/db/models/article.py::Article` gains, after `posted_on`:
  `summary: Mapped[str | None] = mapped_column(Text)` with a docstring saying it is the capped extractive
  excerpt, `NULL` for articles stored before 0.8.16 and for articles whose text could not be fetched.
- **Persist.** `stages/persist.py::persist` gains the keyword argument `summary: str | None = None` and passes
  `**({"summary": summary} if summary else {})` to `ArticleRepo.upsert`, so a re-run without text never erases a
  stored value (the rule `llm_ttp_status` already follows). Both `persist(…)` calls in `pipeline.complete` pass
  `summary=make_dek(summary)`. `persist_rejected` is not changed. `ArticleRepo.upsert` needs no change:
  `_apply_machine_fields` accepts any column name.
- **API.** `schemas/article.py::ArticleOut` gains `summary: str | None = None`; `routers/articles.py::_serialize`
  sets `summary=article.summary`. Every endpoint that returns `ArticleOut` gains the key.
- **No backfill.** The article text is not stored, so rows written before 0.8.16 keep `NULL` and the UI hides
  the dek for them.
- **Tests.** New `tests/unit/test_summarize_dek.py`: `test_make_dek_empty_is_none`,
  `test_make_dek_collapses_whitespace`, `test_make_dek_short_text_unchanged`,
  `test_make_dek_cuts_at_last_sentence_end`, `test_make_dek_without_sentence_end_cuts_at_word_with_ellipsis`,
  `test_make_dek_never_exceeds_max_chars_plus_ellipsis`. `tests/integration/test_pipeline_tier1_db.py`:
  `test_pipeline_stores_capped_summary` (`pipeline.summarize` is monkeypatched, as the file already does because
  CI has no `nlp` extra, here to return a 2,000-character string; the stored `articles.summary` equals
  `make_dek` of it and is at most 601 characters) and `test_persist_keeps_summary_when_none` (a second `persist` for the same URL without `summary`
  leaves the column as it was). `tests/integration/test_articles_router_snapshot.py`: one seeded article gets a
  summary; snapshots updated (4.6).

### 4.6 B-N2 `ArticleOut.first_seen_at`
- **Contract.** `ArticleOut` gains `first_seen_at: str | None = None`, ISO 8601 with offset
  (`2026-11-14T02:12:00+00:00`), from `articles.first_seen_at` (timestamptz, not null, set by `upsert` on first
  insert and never changed by a re-crawl). `_serialize` sets `first_seen_at=article.first_seen_at.isoformat()`.
  No migration.
- **Meaning.** The moment the scraper first stored the article, not its publication time (C7).
- **Tests.** `tests/integration/test_articles_router_snapshot.py`: `_NORMALIZE` gains
  `r"(.*\.)?first_seen_at$": (str,)`; run `--snapshot-update` for this file and review the diff (two new keys per
  article). New `test_article_out_first_seen_at_is_iso_with_offset` (parses with
  `datetime.datetime.fromisoformat` and has a `tzinfo`). Any other syrupy file that embeds `ArticleOut` and
  fails is updated the same way; its diff must be the two new keys only.

### 4.7 Contract
One regeneration after 4.1 to 4.6: `uv run python tools/export_openapi.py`, then `cd apps/web && pnpm run
gen:api`. Expected diff in `docs/openapi.json`: the `limit` and `kinds` parameters, five `DashboardAttention`
properties, the wider `kind` enum and `ransomware_group` on `TrendItemOut` and `TopicOut`, and `summary` and
`first_seen_at` on `ArticleOut`. Nothing else.

### 4.8 Documentation touched
- `CHANGELOG.md`, 0.8.16 entry (Indonesian). *Ditambahkan:* Dashboard baru (hero "Needs action" dengan peta
  sinyal APAC, lead story dengan alasan peringkat, "By the numbers", Must read, Trending aktor / malware / CVE,
  empat grafik 30 hari, CVE watchlist, bagian "More"); kolom `articles.summary` (kutipan ringkasan ekstraktif,
  maksimal 600 karakter) dan field `summary` serta `first_seen_at` di respons artikel; `limit` di
  `/api/dashboard/cve-exposure`; `kinds` dan `ransomware_group` di `/api/dashboard/trending`; lima field baru di
  `/api/dashboard/attention`. *Diubah:* periode bawaan Dashboard menjadi 7 hari dengan pilihan 24 jam; teks
  Dashboard berbahasa Inggris; kalimat brief dan "Updated HH:MM" tidak lagi ditampilkan; grup ransomware teratas
  menjadi lima. A "Catatan 0.8.16 (Dashboard)" line: migrasi `d9f2b6a4c1e7` menambah kolom nullable
  `articles.summary`, tanpa backfill, tanpa key `.env` baru; artikel lama tidak punya ringkasan.
- `docs/prod-upgrade/0.8.16.md` and `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` (English). *Migrations:* a third
  revision, `d9f2b6a4c1e7`, on top of `c4e8a1f2b9d6`, applied by the `migrate` service during `make deploy`:
  `ALTER TABLE articles ADD COLUMN summary text` (nullable, no default, no backfill, no index; a catalog-only
  change that does not rewrite the table and holds its lock for milliseconds). After deploy `alembic_version`
  is `d9f2b6a4c1e7`. *Settings:* none. *Behaviour change:* the Dashboard defaults to 7 days; articles enriched
  after the deploy carry a summary, older ones do not and nothing fills them in. *Contract:* the additive
  fields of 4.7. *Post-deploy check:* `alembic_version` reads `d9f2b6a4c1e7`; after the next enrichment run
  `SELECT count(*) FROM articles WHERE summary IS NOT NULL` is above 0 and `SELECT max(length(summary)) FROM
  articles` is at most 601; `/dashboard` shows a dek under the lead story once such an article ranks first.
  *Rollback:* image rollback only. The old code ignores the column; it is left in place (the deploy never
  downgrades the database). A manual `alembic downgrade -1` drops the column and the stored excerpts with it.
- `docs/ARCHITECTURE.md`: in the enrichment code-path list, the `persist` step gains "stores the capped summary
  excerpt in `articles.summary`".

## 5. Migration summary

One hand-written Alembic revision, `alembic/versions/d9f2b6a4c1e7_articles_summary.py`:
`revision = "d9f2b6a4c1e7"`, `down_revision = "c4e8a1f2b9d6"` (the current single head, confirmed with `uv run
--no-sync alembic heads`). `upgrade()`: `op.add_column("articles", sa.Column("summary", sa.Text(),
nullable=True))`. `downgrade()`: `op.drop_column("articles", "summary")`. The model change of 4.5 is in the same
commit, so `tests/integration/test_migrations_match_models.py` stays green. No data statement, no index, no
constraint. No `Settings` field, so `.env.example` and `.env.prod.template` are unchanged. If another revision
lands on the branch first, `down_revision` is that new head and `alembic heads` must still print one line.

## 6. UI

Global rules (as 2b to 4c). Desktop 1440 first (content width 1328). Two-column rows are
`lg:grid-cols-[minmax(0,820fr)_minmax(0,468fr)]` and collapse to one column below 1024 px; the four chart cards
are `sm:grid-cols-2 xl:grid-cols-4`. No `backdrop-blur`. Colours only through tokens; text on tints uses
`text-X-text`; everything inside the hero uses hero tokens (`text-hero-foreground`, `text-hero-muted`,
`bg-hero-panel`, `heroLinkClass`). Focus ring `focus-visible:ring-2 focus-visible:ring-ring
focus-visible:ring-offset-2 focus-visible:ring-offset-background`. Minimum text 11 px (`text-2xs`). Base UI, not
Radix. CVE ids, technique ids, ticket ids and counts in `font-code` (`font-mono` is not monospace here). The
mockup's wide separators are rendered " · ". Fixed copy below is verbatim from the frames unless a C-rule or
P-rule says otherwise. Dates and times are browser zone through `lib/format.ts`; the `id-ID` formatters in
`page.tsx` and `overview-cards.tsx` are removed.

Constraints carried over from earlier sub-projects (each is a review checklist item):
1. **Titles.** A static title is static `metadata`, never `usePageTitle`. `app/(app)/dashboard/page.tsx` becomes
   a server component: `export const metadata: Metadata = { title: "Dashboard" }` and `<Suspense><DashboardView
   /></Suspense>` (the boundary is required by `useSearchParams`). `app/(app)/dashboard/layout.tsx` is deleted,
   so the root title template applies and the tab reads "Dashboard · {PLATFORM_NAME}". The page does not call
   `usePageTitle`: the h1 is a date, the tab title is not data-driven.
2. **`response.ok`.** Every query destructures through `unwrap` (`lib/scrapers/queries.ts`), which throws `new
   Error(detail ?? fallback, { cause: response.status })`. The current `if (error) throw error` calls in
   `use-dashboard-overview.ts`, `overview-cards.tsx`, `page.tsx` and the two name hooks in
   `components/newsroom/rubric-queries.ts` move to it. An empty-body 502 must not read as success.
3. **No 4xx retry, no polling.** Every query uses `retry: noClientRetry`. No Dashboard query sets
   `refetchInterval`; if one is added later it must return `false` while `isClientError(query.state.error)`.
4. **Never `router.replace` to an unchanged URL.** The period handler builds the next URL and returns when it
   equals the current `pathname` plus search string (6.1). No effect writes the URL.
5. **`table-fixed` needs explicit column widths** (CVE watchlist, 6.6).
6. **No interactive element nested inside another.** Hero rows are one `Link` with text only. Article titles are
   `<button>`s; chips that are links sit beside them, never inside. Table rows have no `onClick`.
7. **Base UI `Select`.** `SelectItem` children are a single string and every `Select` passes `items`. 5a adds no
   `Select` (the period becomes a `SegmentedControl`); the rule applies to any added later.
8. **Theme tokens only**; every panel and `ArticleModal` opened from the page is checked in light and dark.
9. **Legend colours equal data colours.** The map legend uses `bg-hero-accent` and `bg-hero-eyebrow`, the two
   colours `WorldDots` reads for its points. The industries legend takes its swatches from `SHARE_BAR_SEGMENT`
   by index, the array `ShareBar` paints with. Highlighted bars and any text that refers to them use the same
   `destructive` token.
10. **Gate on the real permission** (table in 6.8, copied from the router dependencies). Never stricter, never
    looser.
11. **No `Date.now()` in render.** "Now" for relative times is read inside the `queryFn` and returned with the
    data (`fetchedAt`); the period start for `/api/articles` is computed inside the `queryFn`; today's date in
    the h1 comes from `useSyncExternalStore` with the server snapshot `"Dashboard"`, as today.
12. **`Literal`-typed seeds.** Seed and fixture data use the API's values exactly: trend `kind` `actor | ttp |
    malware | cve`, breaker `closed | open | half_open`, `llm_ttp_status` `pending | done | skipped | failed`.
    TypeScript unions come from the generated schema types, not hand-written strings.
13. **`proxyFetch` for raw proxy calls.** 5a makes none; any download or stream added to this page goes through
    `proxyFetch`, never a bare `fetch("/api/proxy/…")`.
14. **The server message, not a generic sentence.** Error panels and the page gate print `error.message` (the
    API `detail`); a fixed fallback is used only when the response has none.
15. A `Chip` inside `HeroPanel` needs hero-safe tokens. The hero uses no `Chip`.
16. A closed `Disclosure` is hidden in print unless `printOpen` is set: "More" sets it.
17. Every pre-redesign feature stays reachable; the PR carries a checklist DB1-DB20 (6.9).

Files. New `components/dashboard/dashboard-view.tsx` (the page body), `needs-action.tsx`, `lead-story.tsx`,
`by-the-numbers.tsx`, `must-read.tsx`, `trending.tsx`, `month-charts.tsx`, `cve-watchlist.tsx`,
`more-section.tsx`, `article-opener.tsx`, `lib/dashboard/period.ts`. Changed: `use-dashboard-overview.ts`,
`components/world-dots.tsx`, `components/newsroom/score-reasons.ts`, `components/newsroom/grade-chip.tsx`.
Deleted: `signal-hero.tsx`, `dashboard-filters.tsx`, `overview-cards.tsx`, `app/(app)/dashboard/layout.tsx`.
Kept for other pages and for "More": `stat-box.tsx` (`DashboardSectionLabel` is used by Exec; `MapCard` by
"More"), `charts.tsx`, `breakdown-list.tsx`.

### 6.1 Header (frame 2, node 57)

- `PageHeader` kicker "THREAT BRIEFING · {CLIENT}" where `{CLIENT}` is `useActiveClientName()` in upper case;
  while it is `null` the kicker is "THREAT BRIEFING". h1 = today in the browser zone, `new
  Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" })` ("Thursday, November 5").
  No description.
- `actions`: the period control, then the toggle.
  - `SegmentedControl` (`aria-label` "Period") with options "24h", "7d", "30d", "90d", "All".
  - `Checkbox` with the label "Threat news only", `text-xs`, default checked, component state.
- **Period model** (`lib/dashboard/period.ts`), the only place that knows these values:

| Key | URL | `days` sent to the API | Words | Headline suffix |
|---|---|---|---|---|
| `1` | `?period=1` | 1 | "24 hours" | "since yesterday" |
| `7` | (no parameter) | 7 | "7 days" | "in the last 7 days" |
| `30` | `?period=30` | 30 | "30 days" | "in the last 30 days" |
| `90` | `?period=90` | 90 | "90 days" | "in the last 90 days" |
| `all` | `?period=all` | (omitted) | "all time" | "of all time" |

- **URL** (P1). The period is derived from `useSearchParams().get("period")` on every render; a missing or
  unknown value is `7`. There is no mirrored state. On change the handler copies the current search params, sets
  `period` (or deletes it for `7`), builds `next = pathname + (qs ? "?" + qs : "")`, returns when `next` equals
  the current URL, and otherwise calls `router.replace(next, { scroll: false })`. Other parameters are kept.
  `replace`, not `push`: the back button leaves the Dashboard instead of stepping through periods.
- **What the controls drive.** Period: everything except "The month in charts", Threat Actor Room and the weekly
  ransomware chart. Toggle (`incident_only`): the two `/api/dashboard` requests only, that is "By the numbers"
  rows 1 and 2, the month charts except "Ransomware by group", and "Articles over time" in "More".
- While a period or toggle change is loading, panels keep the previous data at `opacity-60`
  (`placeholderData: keepPreviousData`, `isPlaceholderData`), as today (DB19).

### 6.2 Needs action: hero (node 72)

`HeroPanel` with kicker "NEEDS ACTION" and the headline as `title`, body `lg:grid-cols-[minmax(0,752fr)_500px]`.
`section` label "Needs action".

- **Data.** `useDashboardAttention(days)` (no `incident_only`, P21) and `useDashboardMap(days)`. Each side
  loads and fails on its own; the hero skeleton shows only while both are pending.
- **Headline.** `n` = how many of the three row values are above 0. "{n} signals for {client} {suffix}" ("3
  signals for Acme Bank since yesterday"); "1 signal for {client} {suffix}"; "No signals for {client} {suffix}"
  for 0. `{client}` is `useActiveClientName()`, "your organisation" while `null`. `{suffix}` from the period
  table.
- **Rows.** Each row is one `Link` (`heroLinkClass`): the value (`toLocaleString("en-US")`), the title, the
  second line (`text-hero-muted`, omitted when empty) and "Open →" at the right. `aria-label` "{title}: {value}.
  Open". Rows are separated by `divide-hero-foreground/15`.

| Row | Value | Title | Second line | Link |
|---|---|---|---|---|
| 1 | `kev_in_stack` | "KEV CVEs hit your tech stack" | "Open now" + " · " + `kev_tech` joined by ", " (when not empty) + " · {kev_without_ticket} without a ticket" (when above 0). Value 0: "None open right now". | `/cve` |
| 2 | `ransomware_in_client_scope` | by `client_countries`: one → "Ransomware victims in {country name}"; two or more → "Ransomware victims in your {n} countries"; none → "Ransomware victims in your countries" | Parts joined by " · ". Comparison, when `ransomware_prev_in_client_scope` is not `null`, with `d` = value minus previous: `d > 0` "Up {d} from the previous {words}"; `d < 0` "Down {-d} from the previous {words}"; `d == 0` "Same as the previous {words}". Industry, when `ransomware_client_top_industry` is not `null`: "{count} in {name}". No countries: "No country is set for this client". | `/newsroom?rubric=ransomware`, plus `&country={code}` when there is exactly one country, plus `&period={days}` when days is 1, 7 or 30 |
| 3 | `watchlist_hits` | "Articles matching your watchlist" | `watchlist_top` joined by ", " (when not empty) + " · " + "{pir_hits} active PIRs with new articles" ("1 active PIR with new articles" for 1) | `/newsroom?rubric=watchlist`, plus `&period={days}` when days is 1, 7 or 30 |

  Country names come from `i18n-iso-countries` (English), with the `UK → GB`, `EL → GR` aliases already in
  `signal-hero.tsx`; that helper moves to `lib/dashboard/countries.ts`.
- **Attention error.** The left column shows "Could not load the signals" with the server message and a
  "Retry" button in hero tokens; the map side is unaffected.

### 6.3 Signal map (node 72, right)

- A 500 × 380 box with `WorldDots` (`dynamic`, `ssr: false`). Title "Signal map", subtitle "Incidents &
  ransomware victims, {words}".
- **View** (P8). `WorldDots` gains `view?: "world" | "apac"` (default `"world"`, so Login is unchanged).
  `"apac"` draws longitudes 60° E to 180° and latitudes 50° S to 55° N scaled to fill the box; points outside
  are not drawn. `components/world-dots.tsx` also exports `inView(code: string, view: "world" | "apac"):
  boolean`, computed from the same coordinates it draws with. Two text buttons "APAC" and "World"
  (`heroLinkClass`, `aria-pressed`) in the box's top right corner switch the view; component state, default
  "APAC".
- **Points** as today: weight `incidents + ransomware_victims`, tone `incident` when incidents are at least the
  victims, else `ransomware`, `ring` for client countries; the points array is memoised on `map.data` and the
  view. `label` in English: "{country}: {i} incidents, {v} ransomware victims"; a row without a country code is
  "Unknown country" and is drawn in no view.
- **Kept from today** (DB5, DB6): the focus and hover tooltip (country; "{i} incidents · {v} ransomware
  victims"; "Top: {actor}, {industry}" when present); click or Enter on a point → `/newsroom?country={code}`;
  the legend ("Incidents", "Ransomware", "Your countries (ring)") at the bottom left; the `sr-only` ordered list
  of the ten heaviest points of the current view.
- **"TOP COUNTRIES"** overlay (bottom right, `bg-hero-panel`): the four heaviest points with `inView(code,
  view)`, each a country name, a `MeterBar onHero` (`value` = weight, `max` = the first row's weight) and the
  number. Plain text, no links. Hidden when the view has no point.
- **Empty** (`points.length == 0`): centred "No incidents with a country in this period." **Error**: centred
  "Could not load the map" with the server message and "Retry".

### 6.4 Lead story and By the numbers (node 149)

**Must-read query** (shared by the lead and the feed). Key `["dashboard", "must-read", days]`; `GET
/api/articles` with `page: 1`, `page_size: 5`, `sort: "priority"` and `posted_on_start` = the ISO date `days`
days ago, computed in the `queryFn` (omitted for "All"). The `queryFn` returns `{ articles, fetchedAt:
Date.now() }`. Row 1 is the lead; rows 2 to 5 are "Must read". `sort=priority` returns one article per story.
The toggle does not apply (the endpoint has no `incident_only`).

**Lead** (left). `article` element, label "Lead story".
- Kicker: "LEAD STORY · PRIORITY {priority_score} · {n} SOURCES". The "PRIORITY {n}" part is a `PriorityChip`
  (6.8) and is left out when `priority_score` is `null`; "{n} SOURCES" uses `story.source_count`, reads "1
  SOURCE" for 1 and is left out when `story` is `null`. An "ATT&CK PENDING" chip (`Chip kind="flag"`, neutral tint)
  follows when `llm_ttp_status == "pending"`.
- Title: an `<h2>` holding a `<button>` that calls `openArticle(article)` (6.8).
- Dek: `summary`, `line-clamp-3`, not rendered when `null`.
- Byline: "{source} · {when}" (P6). `{when}` (D4, P7): if `first_seen_at` is set and `fetchedAt` minus it is
  under 24 hours, `fmtAgo(first_seen_at, fetchedAt)`; else `fmtShortDate(parseLocalDate(posted_on))`; when
  `posted_on` is empty, `fmtShortDate(first_seen_at)`. The element has `title="First seen
  {fmtDateTime(first_seen_at)}"`.
- Chips, beside the byline: the first two `ttps` as `EntityChip type="attack-pattern" name={id}` and the first
  two `entities` of type `vulnerability` as `EntityChip type="vulnerability" name={external_id ?? name}`.
- **"WHY IT RANKS FIRST"** box (tinted `bg-primary/10`, heading `<h3>`). Not rendered when `priority_score` is
  `null`. One line per item of `score_reasons.priority`, ordered by `points` descending then by the order
  received: "{label} +{points}" (the sign is "−" for negative points). Labels from a new map `PRIORITY_LINE` in
  `components/newsroom/score-reasons.ts`, next to the existing `PRIORITY_TEXT` (P16):

| `code` | Label |
|---|---|
| `confirmed_incident` | "Confirmed incident" |
| `kev` | "On CISA KEV" |
| `poc` | "Public proof of concept" |
| `ttps` | "{n} ATT&CK techniques" with `n = ttps.length`; "ATT&CK techniques" when `n` is 0 |
| `actor` | "Named threat actor" |
| `corroboration` | "Corroborated by {story.source_count} sources"; "Corroborated by other sources" without `story` |
| `pir_match` | "Matches your PIR: {titles}" with the `title` of each `score_reasons.pir` entry joined by ", "; "Matches a PIR" when that list is empty |
| `own_asset` | "Mentions your assets: {own_asset.join(", ")}"; "Mentions your assets" when the list is empty |
| any other | the code as received |

  An empty list prints "Ranked on source confidence alone." The points are the API's (25, 15, 8, …), not the
  mockup's sample numbers. `score_reasons` is already client-scoped by the API (`_client_score_reasons`).
- **No article in the period:** the lead area is `StatePanel variant="empty"` "Nothing to read {suffix}" /
  "Widen the period to see the highest-priority story." and "Must read" (6.5) is not rendered.

**By the numbers** (right). Heading "BY THE NUMBERS · {WORDS}" (words in upper case: "7 DAYS", "ALL TIME"),
plus " · THREAT NEWS ONLY" when the toggle is on. Four rows, each: number, label, second line, graphic slot
(96 px wide, right). Rows are a `dl`; sparklines are `aria-hidden`.

| # | Number | Label | Second line | Graphic | Source |
|---|---|---|---|---|---|
| 1 | `total_articles` | "articles collected" | delta | `Sparkline` of `timeline[].count` | `/api/dashboard` |
| 2 | `confirmed_incidents` | "confirmed incidents" | delta | `Sparkline` of `timeline[].incidents` | `/api/dashboard` |
| 3 | `total` | "ransomware victims" | "{apac} in APAC · {ransomware_in_client_scope} in your countries" (the second part only when attention has loaded and `client_countries` is not empty) | `Sparkline` of `weekly[].victims` (eight weeks, whatever the period; `title="Last 8 weeks"`) | `/api/dashboard/ransomware`, attention |
| 4 | `open_critical` | "open critical CVEs" | "{open_kev} open KEV (any severity) · " + ("all KEV have a ticket" when `kev_without_ticket` is 0, else "{n} KEV without a ticket"); the part after " · " only when attention has loaded | none (P5) | `/api/dashboard/cve-exposure`, attention |

  Delta (rows 1 and 2), the rule of today's `Delta` component: shown when the period is not "All",
  `prev_period_reliable` is true and the previous value is above 0: "▲ {p}% vs previous period" / "▼ {p}% vs
  previous period" / "no change vs previous period" with `p = round(|cur − prev| × 100 / prev)`; otherwise "no
  prior-period data" ("all time" for "All"). The arrow is `aria-hidden` and the text carries visually hidden
  "up" / "down".
  A row whose source is pending shows a skeleton line; a row whose source failed shows "–" and "Could not load"
  with a "Retry" text button for that source. The other rows are unaffected.

### 6.5 Feed (node 245)

**Must read** (left). `<h2>` "Must read", subtitle "Ranked by priority score". An `ol` of rows 2 to 5 of the
must-read query:
- Kicker: `PriorityChip` "PRIORITY {n}" (left out when `null`) + " · " + the kind: `news_type` in upper case
  (`"apac"` → "APAC", `"Data Breach Article"` → "DATA BREACH ARTICLE"); left out when `news_type` is empty.
- Title: `<h3>` holding a `<button>` → `openArticle(article)`. `line-clamp-2`.
- Dek: `summary`, `line-clamp-2`, not rendered when `null`.
- Meta line: "{source} · {when} · {first TTP id}" with `{when}` as in 6.4 but through `fmtCompactAge` ("7 h")
  for the under-24-hours case; the TTP id is `font-code` and left out when there is none. Then, as small
  neutral chips (`Chip kind="flag"` with the word as `value`; P18, DB10): "Incident" when `confirmed_incident`, "Watchlist" and "Tech stack"
  from `useArticleMatchers()`, "ATT&CK PENDING" when `llm_ttp_status == "pending"`, and `GradeChip codeOnly`
  (6.8) when `admiralty_code` is set.
- Fewer than five articles: the list shows what there is; with exactly one article the section shows "No other
  story in this period."

**Trending** (right). `<h2>` "Trending". Data: `GET /api/dashboard/trending` with `days` and `kinds=actor`,
`kinds=malware`, `kinds=cve`; key `["dashboard", "trending", days, "actor,malware,cve"]`. Subtitle: "vs previous
{window_days} days" when `baseline_reliable`, else "last {window_days} days · not enough history to compare"
(`window_days` is 7 for "All": the API falls back to it). The first six items, each a row:
- Name: `EntityChip` with `type` `intrusion-set` and `id={entity_id}` for `actor`, `malware,tool` for `malware`,
  `vulnerability` for `cve`.
- Kind chip (`Chip kind="flag"`, neutral): "Ransomware" for an actor with `ransomware_group`, else "Actor";
  "Malware"; "CVE".
- "NEW" chip (`Chip kind="status" value="action"` with the text "NEW") when `is_new`.
- Count in `font-code`, right-aligned; after it "+{change_pct}%" in `text-muted-foreground` when `change_pct` is
  not `null` and the item is not new (P11).
- Empty: "Nothing is rising in this period."

Both panels use the error and loading states of 6.7.

### 6.6 The month in charts and CVE watchlist (nodes 483, 599)

**The month in charts.** `<h2>` "The month in charts", subtitle "Last 30 days · all sources", plus " · threat
news only" when the toggle is on (P20). Two requests, fixed at 30 days: `/api/dashboard?days=30&incident_only=`
and `/api/dashboard/ransomware?days=30`. They use the same query keys as the period requests, so with the
period on 30d no extra request is sent. Four cards, each with an `<h3>` title, a subtitle and a fixed body
height of 220 px:

| Card | Subtitle | Body |
|---|---|---|
| "Incidents per day" | "Confirmed, 30 days" | `BarSeries` over 30 dates ending on the date part of `generated_at`; a date missing from `timeline` is 0, dates outside the range are dropped; `values` = `incidents`. `highlight` marks the three highest bars among those above 0 (ties: the later date first), `highlightTone="destructive"`. No caption (D7). Below the chart, visually hidden: "Highest: {date} {n}, {date} {n}, {date} {n}". All zero: "No confirmed incident in the last 30 days." |
| "Ransomware by group" | "Victims, 30 days" | Up to five rows from `top_groups` (B-D4): `EntityChip type="intrusion-set"`, `MeterBar tone="destructive"` (`max` = the largest row), count. A sixth row "Other" (plain text) with `total` minus the sum of the rows, when that is above 0. Empty: "No victim in the last 30 days." |
| "Targeted industries" | "Share of sector mentions" (C11) | `top_industries` without "general" (case-insensitive): the first four plus "Other" = the sum of the rest of the list. `ShareBar` over those values, and under it a list: swatch (`SHARE_BAR_SEGMENT[i]`), the name in title case as a link to the `identity` entity ("Other" is plain text), and the percentage of the shown total, rounded, the last row taking the remainder so the column sums to 100. Footnote when `industry_unspecified` is above 0: "{n} articles without a specific sector are not counted." Empty: "No sector was mentioned in the last 30 days." |
| "Top techniques" | "Mentions in articles" ("Mentions in threat news" when the toggle is on) | The first five of `top_ttps`; each name is split at the first " — " into id and name. Row: id (`font-code`, link to the `attack-pattern` entity), name (truncated), `MeterBar` (`max` = the first row), count. A text button "Show all 10" / "Show 5" (`aria-expanded`) when the list has more than five (P13). Footnote: "{coverage.with_ttp} of {total_articles} articles map to a technique." (DB17). |

**CVE watchlist.** `<h2>` "CVE watchlist", subtitle "Open CVEs in your tech stack, KEV first" (P12), and on the
right a link "{open_critical} open critical · View all →" to `/cve`. Data: `GET
/api/dashboard/cve-exposure?limit=4` with `days`; key `["dashboard", "cve-exposure", days, 4, clientId]`.
`Table framed`, `table-fixed`, widths CVE 18% | PRODUCT 26% | CVSS 8% | POC 10% | KEV 8% | TICKET 14% | TICKET
AGE 16%:
- CVE: a `Link` to `/cve?search={cve_id}` in `font-code` (DB13).
- PRODUCT: `tech`, "–" when `null`.
- CVSS: one decimal, "–" when `null`.
- POC: "public" in `text-destructive-text` when `public_poc`, else "–".
- KEV: `Chip kind="cve" value="kev"` when `cisa_kev`, else "–".
- TICKET: `ticket_id` in `font-code`; "no ticket" in `text-warning-text` when `null`.
- TICKET AGE: "{ticket_age_days} d"; "–" without a ticket.
- Footer line under the table (DB13): "{closed_in_period} tickets closed {suffix}" + " · mean
  {mean_days_to_close} days to close" when the mean is not `null`.
- Empty (`items` is empty): `StatePanel variant="empty"` "No open CVE in your tech stack" inside the card; the
  footer line stays.

### 6.7 More, and the states (frame 32816)

**"More"** (D6, P14). `Disclosure` with `title="More"`, `headingLevel={2}`, `printOpen`, closed by default,
controlled; the queries below have `enabled` set from "has been opened at least once". Contents, in a
`lg:grid-cols-12` grid, each a `MapCard` / `ChartCard` with English titles:

| Panel | Was | Content | Needs |
|---|---|---|---|
| "Articles over time" | DB15 | the existing `TimelineChart`: all news and the "Incidents" secondary series, selected period and toggle (data already loaded by 6.4) | `view_news` |
| "Ransomware victims per week" | DB12 | the existing `TimelineChart` over `weekly` (eight weeks, `emphasizeLast`), note "{total} victims · {apac} in APAC" for the selected period | `view_news` |
| "Your context" | DB14, DB9 | a `dl`: "Watchlist matches" `watchlist_hits`; "PIRs with new articles" `pir_hits`; "Actors in the news" `total_threat_actors` with "{n} new this period" (trending items of kind `actor` with `is_new`); and "Newest campaign cluster": a link "{cluster_name} · {size} articles" to `/intelligence/campaign-clusters` (`GET /api/clusters/recent?days=30`), "No campaign cluster yet." when there is none | `view_news`; the cluster line `view_intel` |
| "Threat Actor Room" | DB18 | section label with the aside "All time. The period filter does not apply here."; "APT Groups by Source" (`BreakdownList`) and "Tracked APT Groups in the News" (`HorizontalBarChart`), from `GET /api/ta/stats` | `view_ta` |

A panel whose permission the user lacks is not rendered. chart.js stays in the bundle for these three charts
and for the pages that already use `charts.tsx`.

**No data yet** (state 32868, D17, P9).
- Condition: `can("view_cve")` and `can("view_ta")`, both name queries succeeded, and both lists are empty:
  `useTechStackNames` (`GET /api/techstack`, `view_cve`) and `useWatchlistNames` (`GET /api/ta/watchlist-names`,
  `view_ta`), the hooks Must-read already uses through `useArticleMatchers`, so no extra request. A pending or
  failed query, or a missing permission, means "unknown" and the state is not shown.
- Rendering: inside the hero, in place of the headline and the three rows; the map side stays. Kicker "GET
  STARTED". Title "Nothing is matched to {client} yet". Body "Articles are already arriving. Matching starts
  once a tech stack and a watchlist are set: add the products you run and the actors you track, and this panel
  fills in." Button "Set up tech stack" (a `Link` styled as the hero's primary button) → `/cve`.
- The rest of the page renders normally: articles are global (C13).

**LLM gateway down** (state 32880, D17, P10).
- Data source: `GET /api/data-health` (`view_ops`), which already returns `llm.queue.breaker`
  (`closed | open | half_open`), `retry_at`, `pending_classify` and `pending_ttp`. Query key `["dashboard",
  "llm-queue"]` (its own key: the Data health page stores a different shape under `["data-health"]`),
  `enabled: can("view_ops")`, `staleTime` 60 s, no `refetchInterval`, `retry: noClientRetry`.
- Shown when the query succeeded and `breaker` is not `"closed"`: a `Notice tone="warning"` between the header
  and the hero. Title "ATT&CK tagging is catching up". Body "The LLM gateway is failing. {pending_ttp} articles
  wait for technique tagging and {pending_classify} wait for classification; both run on their own when it
  recovers. Articles that are already classified keep appearing." plus " Next retry {fmtTime(retry_at)}." when
  `retry_at` is set. `action`: a link "Open Data health" → `/data-health`.
- Any error of this query, a closed breaker or a user without `view_ops`: no banner and no error text (the
  banner is advisory).
- Per article: the "ATT&CK PENDING" chip of 6.4 and 6.5, for every role (the field is part of `ArticleOut`).

**Panel error** (state 32896). Every panel keeps its heading, subtitle and height and renders, in place of its
body, `StatePanel variant="error"` with the title below, `description` = "{error.message} Other panels are
fine." and `action` = a "Retry" button that calls that query's `refetch`. A failed panel never hides or blanks
another one. When two panels share a query (lead and Must read; the three charts fed by `/api/dashboard`), each
shows its own error panel and any "Retry" refetches the shared query.

| Panel | Title |
|---|---|
| Lead story | "Could not load the lead story" |
| By the numbers | per row (6.4) |
| Must read | "Could not load the reading list" |
| Trending | "Could not load trending" |
| Incidents per day | "Could not load incidents per day" |
| Ransomware by group | "Could not load ransomware groups" |
| Targeted industries | "Could not load targeted industries" |
| Top techniques | "Could not load top techniques" |
| CVE watchlist | "Could not load the CVE watchlist" |
| panels in "More" | "Could not load {panel title in lower case}" |

**Loading** (no frame). Each panel shows a `Skeleton` of its body height with `aria-hidden` on first load; a
period or toggle change dims the old content instead (6.1).

**No access** (P17). Without `view_news`, `DashboardView` renders only the header and `StatePanel
variant="no-access"` "Dashboard needs the view_news permission" / "Your role ({role}) does not have it." and
sends no request.

**Session expired** (state 32948): the 4c dialog, unchanged.

### 6.8 New primitives and domain pieces (existing ones reused as they are)

- **`components/dashboard/article-opener.tsx`** (D10): `useArticleOpener(): { openArticle: (a: Article) => void;
  host: ReactNode }`. In 5a it keeps the selected article in state and `host` is `<ArticleModal article={…}
  onOpenChange={…} />`; `DashboardView` renders `host` once. The lead title and the four Must-read titles are
  its only callers. 5b replaces the body of this one hook with `router.push("/newsroom?view=all&article=" +
  a.id)` and `host = null`; no caller changes. `ArticleModal` itself is not modified in 5a (its "Open Article
  ↗" keeps the external link of DB10).
- **`components/newsroom/priority-chip.tsx::PriorityChip`** (`{ score: number }`, D19, shared with 5b): text
  "PRIORITY {score}", tint from `priorityTone(score)` exported by `score-reasons.ts`: `score >= 90` →
  `destructive`, `score >= 70` → `warning`, else `info` (`bg-X/15 text-X-text`). Not interactive.
- **`GradeChip`** gains `codeOnly?: boolean` (default `false`): when set the label is `admiralty_code` alone;
  the tooltip (`gradeLines`) is unchanged. Newsroom keeps the default until 5b.
- **`PRIORITY_LINE`** and `priorityTone` in `components/newsroom/score-reasons.ts` (6.4). `describePriority`
  and `PRIORITY_TEXT` are unchanged (the chip tooltip and the modal use them).
- **`WorldDots view`** and `inView` (6.3).
- **`lib/dashboard/period.ts`**: the table of 6.1 as a typed constant, `parsePeriod(value: string | null)` and
  `periodHref(pathname, searchParams, key)`.
- **`use-dashboard-overview.ts`**: `useDashboardStats(days, incidentOnly)` moves here from `page.tsx`;
  `useDashboardTrending(days, kinds)` and `useCveExposure(days, limit)` take the new arguments and put them in
  the key; `useDashboardAttention(days)` loses `incidentOnly`; all use `unwrap` and `noClientRetry`.
- **Permissions used by the page** (constraint 10):

| Request | Permission (router dependency) | Without it |
|---|---|---|
| `/api/dashboard`, `/map`, `/attention`, `/trending`, `/ransomware`, `/cve-exposure`, `/api/articles` | `view_news` | the page gate |
| `/api/techstack` | `view_cve` | not requested; no "Tech stack" chip, no "No data yet" state |
| `/api/ta/watchlist-names`, `/api/ta/stats` | `view_ta` | not requested; no "Watchlist" chip, no "No data yet" state, no Threat Actor Room |
| `/api/clusters/recent` | `view_intel` | not requested; no cluster line |
| `/api/data-health` | `view_ops` | not requested; no banner |

  `useArticleMatchers` gains the two `enabled` conditions above; its Newsroom callers pass through the same
  hook and are covered by the same permissions.

### 6.9 Feature map

| # | Pre-redesign feature | New home |
|---|---|---|
| DB1 | h1 = today's date, description "Klien: {client}" | h1 in English; the client moves to the kicker "THREAT BRIEFING · {CLIENT}" (6.1) |
| DB2 | Period select 7 / 30 / 90 / All, default 30 | `SegmentedControl` 24h / 7d / 30d / 90d / All, default 7d, in the URL (6.1) |
| DB3 | "Threat news only" toggle | Checkbox beside the period; drives the `/api/dashboard` panels (6.1) |
| DB4 | "Updated HH:MM" | Dropped (D6, approved). The server cache is still 15 minutes |
| DB5 | Signal map: sized points, two tones, client ring, legend, period label | Hero right side, APAC by default with a World switch; all four kept (6.3) |
| DB6 | Map tooltip, click to `/newsroom?country=`, sr-only top 10 | Kept (6.3); plus the visible "TOP COUNTRIES" list |
| DB7 | Brief headline and detail; "Recap mingguan →" link | Sentences dropped (D6, approved). Recap stays one click away in the masthead |
| DB8 | Three action rows with deep links and second facts | Hero rows (6.2), with names, the previous-window comparison, "n without a ticket" and "n active PIRs" |
| DB9 | KPI strip of five with deltas, sparkline and the "no prior-period data" rule; per-number loading and error | "By the numbers" rows 1 to 4 (6.4); "Actors in the news" and "n new" move to "More" → "Your context" |
| DB10 | Must read: 4 priority articles, external link, source, date, type, actor chip, why-it-matters badges, grade chip | Lead + 4 Must-read rows (6.4, 6.5); the external link and the actor chips are in `ArticleModal`, one click away |
| DB11 | Trending top 4 actor / TTP with entity links, count, "baru" or +% | Trending, six rows, Actor / Malware / CVE with entity links, NEW and +% (6.5); techniques are in "Top techniques" |
| DB12 | Ransomware card: 8-week chart, top-3 groups with bars and links, totals | "Ransomware by group" (top 5 + Other, 6.6); the weekly chart and totals in "More" |
| DB13 | CVE exposure: top 3, KEV or CVSS badge, entity chip, tech, ticket age, `/cve?search=`, closed footer | "CVE watchlist" table, 4 rows, same link and footer (6.6); the CVE entity page is reached from `/cve` |
| DB14 | Client context: watchlist hits, PIR hits, newest campaign cluster | "More" → "Your context" |
| DB15 | "Artikel dari waktu ke waktu" (all news vs incidents) | "More" → "Articles over time"; incidents also in "Incidents per day" |
| DB16 | Targeted industries top 8 with entity links and the "General" note | "Targeted industries" share bar, top 4 + Other, links and note kept (6.6) |
| DB17 | Top MITRE ATT&CK TTPs (10) with the denominator note | "Top techniques", 5 with "Show all 10", note kept (6.6) |
| DB18 | Threat Actor Room: two all-time panels | "More" → "Threat Actor Room" |
| DB19 | Each card loads and fails on its own; old numbers dimmed on a period change | Kept; errors gain the server message and "Retry" (6.7) |
| DB20 | Client-aware query keys; hydration-safe date and client name | Kept: `clientId` stays in the keys of map, attention and cve-exposure; `useSyncExternalStore` for the date; `useActiveClientName` for the name |

## 7. Out of scope

- Newsroom, the reader pane, restyling `ArticleModal`, `?view=all&article=` (5b). The Newsroom topics strip keeps
  printing `window_label` until then.
- B-D5 (history of open critical CVEs) and B-D6 (a pipeline endpoint for roles without `view_ops`).
- Backfilling `articles.summary`; an LLM-written summary; translating summaries; putting the summary into
  Telegram alerts, the newsletter, STIX or the machine feed; a full-text index on it.
- Removing `brief`, `window_label` or `incident_only` from the API; changing how `priority_score` or trending is
  computed; a "since my last visit" marker.
- A second source name in the lead byline; the "Spikes: …" caption; masthead count badges.
- A KEV filter on `/cve` for the first hero row; a multi-country ransomware link; passing 90 days or "All" to
  Newsroom (its `?period` accepts 1, 7 and 30).
- Layouts below 1024 px beyond the one-column collapse; the period toggle in the URL; a user-set default period.
- Rebuilding the three "More" charts on `BarSeries`; removing chart.js.

## 8. Verification

- **Backend tests.** `uv run pytest tests/unit/test_summarize_dek.py tests/unit/test_trending.py`; with Docker,
  `uv run pytest tests/integration/test_dashboard_overview_api.py tests/integration/test_dashboard_overview_query.py
  tests/integration/test_dashboard_overview_service.py tests/integration/test_pipeline_tier1_db.py
  tests/integration/test_articles_router_snapshot.py tests/integration/test_newsroom_api.py
  tests/integration/test_migrations_match_models.py`, with `--snapshot-update` once for
  `test_articles_router_snapshot.py` and the diff reviewed; then `uv run pytest tests/integration` and `uv run
  pytest tests/unit tests/contract packages` (deselect the two known Mac-only failures). Named tests: 4.1 to 4.6.
- **Migration.** `uv run --no-sync alembic heads` prints `d9f2b6a4c1e7 (head)` and nothing else; on the isolated
  compose project `qacve`: `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` all succeed and
  `\d articles` shows `summary | text |` nullable.
- **Static.** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src
  packages/cti-scraper/src` (covers the new repository methods and the model column).
- **Contract.** `uv run python tools/export_openapi.py` and `pnpm run gen:api`; the diff is exactly the list in
  4.7; both files committed with the backend.
- **Web.** `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit`; `pnpm build` (also proves the
  `Suspense` boundary around `useSearchParams`). The pure helpers have no unit runner; check in QA: `parsePeriod`
  with `null`, "7", "1", "all", "abc", "0"; `priorityTone` with 69, 70, 89, 90, 176; the industries percentages
  sum to 100; the 30-bar padding with a `timeline` of 3 entries.
- **Visual and behaviour (local).** Compose project `qacve`, API via uvicorn, web via `pnpm dev`. Seed: two
  clients (one with one country, a tech stack, two watched actors and a PIR; one with no country, no tech stack
  and no watch), a client with three countries, open KEV rows on three products with one false positive,
  ransomware victims in the current and the previous 7 days with and without an industry, an actor named like a
  victim group, malware, tool and CVE mentions, articles with and without `summary`, one with `first_seen_at`
  two hours ago, one with `llm_ttp_status = "pending"`, one with `priority_score` 131, and a role with only
  `view_news`. Checks:
  - Period: each option changes the URL once (the network panel shows no navigation when the selected option is
    clicked again); `/dashboard?period=90` loads on 90d; `?period=abc` loads on 7d; choosing 7d removes the
    parameter; Back leaves the page; the four month charts send no new request when the period changes, and
    none at all when it is 30d.
  - Hero: headline for 0, 1 and 3 signals and for each period; the three second lines against SQL counts; the
    one-country, three-country and no-country titles and links; APAC / World switch; tooltip, click-through,
    ring and legend; "TOP COUNTRIES" equals the four heaviest points of the view.
  - Lead and feed: dek shown and hidden; "2 h ago" then the date after 24 h; chips; every line of "Why it ranks
    first" against `score_reasons`; priority tones at 69 / 70 / 89 / 90 / 131; a title opens `ArticleModal`;
    Trending kinds, "Ransomware", "NEW" and "+n%".
  - Charts and table: three highlighted bars; "Other" rows; percentages; "Show all 10"; four CVE rows in KEV
    then CVSS order; the footer line.
  - States: the empty client shows "Nothing is matched to … yet" with the map still drawn and "Set up tech
    stack" → `/cve`; with the breaker forced open (three failed `classify` rows in `llm_calls`) a `view_ops` user
    sees the banner and the `view_news`-only role does not, and no request repeats on a timer; each endpoint
    stopped in turn (return 500 from a local patch) shows that panel's error with the server text and a working
    "Retry" while every other panel renders; a 403 and a 404 are not retried; an empty-body 502 shows the error
    state; the `view_news`-only role sees no Threat Actor Room, no cluster line and no request to
    `/api/techstack`, `/api/ta/*`, `/api/clusters/recent` or `/api/data-health`; a role without `view_news` sees
    the no-access panel and sends nothing.
  - Two clients: switching the client changes every hero number, the names and the CVE table, and no value of
    the other client appears (cache keys).
  - Screenshots at 1440 and 1000 px, light and dark, against frames 2 / 702 and 32816 / 33283. Keyboard pass
    (period control, toggle, hero rows, map points, view switch, article buttons, chips, "Show all 10", table
    links, "More"). No nested interactive element in a hero row, an article row or a table row. The tab title
    reads "Dashboard · {PLATFORM_NAME}". Print preview shows "More" open. No hydration warning in the console.
- **Delivery.** One commit per backend item (B-N1 carries the model and the migration together), one for the
  contract, then the page in the order header and period, hero and map, lead and numbers, feed, charts and
  table, "More" and states, cleanup of the deleted files. Merge into `origin/Dev` (standing approval). On dev
  172.25.1.77: `alembic upgrade head` through the normal deploy, then read-only checks of `/dashboard` with the
  `claude` account. Nothing on dev is written by hand.

## 9. Risks

- **Query cost of the new aggregates.** `get_attention` gains four queries (KEV tech names, watchlist top
  names, the previous ransomware window, the top industry) on top of an already heavy call (a PIR loop, a
  trending run for the unused brief). They are small grouped counts on `cve_tracker` (client-filtered),
  `ransomware_victims` (`country_code` is indexed) and the mention join the hit count already uses, and the
  result is cached 900 s per client and period; dropping `incident_only` from the Dashboard halves the number of
  cache entries. Trending with three kinds runs six `daily_entity_counts` queries instead of four per cache
  miss, each a join of `articles` and entity mentions over `2 × days` days: with 90d or a 3,650-day Newsroom
  window this is the most expensive new read, and CVE mentions are more numerous than actor mentions.
  `known_group_names` filters on `lower(group_name)`, which the plain index on `group_name` does not serve, so
  it scans `ransomware_victims` once per cache miss. All three are behind the 900 s cache; the caches are per
  process and per worker, so a cold start under several uvicorn workers repeats the work. If the Dashboard
  slows down, first drop the brief's trending call from `get_attention` (it is no longer rendered), then add an
  expression index for `lower(group_name)`.
- **More requests per page load.** The page sends up to twelve requests on 7d (eleven today) because the month
  charts need their own 30-day `/api/dashboard` and ransomware responses. Both are cached server side and
  shared by key when the period is 30d.
- **Summary column: size.** At most 601 characters per row, so at the upper bound about 60 MB of table data per
  100,000 articles, less in practice (many excerpts are shorter and long values are compressed). `ArticleOut` grows by the same amount per article, and
  list endpoints return up to 100 articles a page, so a full page gains at most about 60 kB. No index is added.
- **Summary column: nature of the text.** It is not model output. It is a verbatim excerpt of the publisher's
  article, chosen by an extractive summarizer, so (1) it is third-party copyrighted text stored and shown by
  the platform: the cap, the visible source name and the link to the original keep it at snippet length, and
  the uncapped fallback (the whole article when the summarizer fails) is the reason the cap is enforced in code
  and checked after deploy; (2) it can contain personal names that the article prints (victims, suspects,
  researchers), as titles already do, and it now also appears in every API response that carries `ArticleOut`;
  (3) the sentences LSA picks are not always the lead, so a dek can read oddly or be cut mid-thought, and
  non-English articles are summarized with English stop words and tokenization. It is deliberately not added
  to alerts, the newsletter, STIX or the machine feed (section 7). Dropping the column removes every excerpt.
- **Migration on a large `articles` table.** Adding a nullable column without a default is a catalog-only
  change in Postgres: no table rewrite, no backfill, and an `ACCESS EXCLUSIVE` lock held for milliseconds. The
  lock still has to be acquired: a long-running transaction on `articles` makes the `ALTER` wait, and every
  query behind it queues. `migrate` runs first in `up -d`, while the old containers are still serving, so
  this is possible; the usual holders are short enrichment transactions, and the `ALTER` is retried by rerunning
  the deploy if it fails. Rollback leaves the column in place and the old code ignores it. An old worker that
  persists an article during the switch simply writes no summary.
- **The period changes what the hero means.** The default moves from 30 to 7 days, so every number on first
  view is smaller than yesterday's Dashboard and users may read it as a drop. "24h" is "dated yesterday or
  today" on the server's date, not a rolling 24 hours, and near midnight it differs from the browser's day. The
  KEV row ignores the period ("Open now"), so the headline's "{n} signals … in the last 7 days" counts one
  signal that is not time-bound. The comparison on the ransomware row compares windows of the selected length;
  on a young instance the previous window can be empty and read "Up 17". Victim dates are
  `coalesce(discovered, published)`, so a late-published victim moves between windows. "All" has no previous
  window and no comparison. The Newsroom links pass the period only for 1, 7 and 30 days; from 90d or "All" the
  list opens on Newsroom's default and its count differs from the hero's.
- **Client-scoped data.** `kev_tech`, `watchlist_top`, `client_countries`, the ransomware scope values and the
  CVE table are per client; trending, the map points, the charts and the article list are global. The scoped
  values come only from `effective_client_id`, the attention cache key starts with the client id, and the web
  keeps `clientId` in the query keys of map, attention and cve-exposure (a client switch is a full reload). The
  new names are more identifying than the old counts: a product list and a watched-actor list of one client
  must never render for another, which `test_attention_new_fields_are_client_scoped` and the two-client QA pass
  check. `score_reasons.pir` and `own_asset`, printed in "Why it ranks first", are filtered per client by the
  API already. `summary` and `first_seen_at` are not client data.
- **`first_seen_at` is not the publication time.** A backlog scrape or a newly added source stamps old articles
  "2 h ago". The `title` says "First seen", and after 24 hours the date shown is `posted_on`.
- **Trending vocabulary.** CVE and malware mentions are noisier than actors (one advisory round-up mentions
  dozens of CVEs), so the six rows can fill with CVEs. The ranking is still "largest absolute rise". The
  "Ransomware" chip is a name match against leak-site group names and can mislabel an actor that shares a name.
- **The map's APAC default.** Countries outside the view are not drawn and are missing from "TOP COUNTRIES"
  until the user switches to "World", so a client with a country outside APAC sees no ring by default.
- **"No data yet" hides the three rows** for a client that has countries but no tech stack and no watchlist;
  the ransomware number for those countries is then only in "By the numbers".
- **One request for the LLM banner.** It is not polled, so a breaker that opens after the page loaded is not
  announced until a reload, and the banner stays until one. Roles without `view_ops` never see it.
- **Largest regression surface.** The whole page is rebuilt: three components deleted, eleven queries moved to
  `unwrap`, the title moved from the layout to the page, and the default period changed. The DB1-DB20 checklist
  and the per-panel error pass are the guard. `useArticleMatchers` gains permission gates that also apply on
  Newsroom: a role without `view_ta` or `view_cve` stops sending two failing requests there.
- **Deviations from the frames**, listed for the reviewer: the toggle, the "More" section and the map's legend,
  tooltip and view switch (not drawn); the house time format (P7); one source in the byline (P6); no fourth
  sparkline (P5); no "Spikes" caption (D7); "Share of sector mentions" (C11); the CVE watchlist header and no
  "closed" chip (C12); "+n%" in Trending (P11); extra chips on Must-read rows (P18); "Show all 10" (P13); new
  copy for "No data yet" and the LLM banner (C13, C14); real points in "Why it ranks first".
