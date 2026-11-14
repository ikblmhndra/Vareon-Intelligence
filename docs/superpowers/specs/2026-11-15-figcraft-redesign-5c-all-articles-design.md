# FigCraft redesign, sub-project 5c: Newsroom All articles and reader

Date: 2026-11-15. Status: draft for review. Branch: `claude/figcraft-design-data`. Same one-PR release 0.8.16 (the
CHANGELOG entry and the 0.8.16 runbooks are extended, no extra version bump).

## 1. Context and goal

Sub-project 5 is split into 5a Dashboard (done, Dev `6cdc0dbe`), 5b Newsroom Front page and Filtered (done, Dev
`18fc5902`) and **5c Newsroom All articles + reader (this spec)**. 5c is the last Newsroom piece: the N2 Analyst Reader
frame (FigCraft node 2194, light), as an "All articles" view with a filter rail, a selectable list and a reader pane.

Why: analysts read the feed article by article. Today they do it in a dialog opened from many places and in a list
sheet for "See all" and deep links; the frame replaces both with one working view where the filters, the list and the
article sit side by side, the filters live in the URL so a view can be shared, and Intelligence pages land directly on
the filtered list.

Inputs: `.superpowers/brainstorm/sp5-inventory.md` (features NR1-NR28, gaps GNR18-GNR44, conflicts C17-C27, decisions
D9-D11, D15, D16, backend B-N3, B-N5; accepted 2026-11-13), the 5b spec
`docs/superpowers/specs/2026-11-14-figcraft-redesign-5b-newsroom-design.md` (whose rules this spec inherits), and the
5c design conversation of 2026-11-15. Where the inventory differs, this spec wins.

## 2. Goals, non-goals, anti-goals

Goals:
- "All articles" view on `/newsroom?view=all`: rail (period, rubric list with counts, source reliability A-F, country
  multi-select, sector, top sources, reset), list (count, sort, rows, load more), reader pane per frame 2194 with a
  "More" disclosure for the features the frame leaves out (D9).
- B-N3 source-reliability filter and B-N5 article IOC endpoint.
- Every way into an article list or an article on the Newsroom and the Dashboard goes to All articles (D10, D11):
  Front page and Dashboard article clicks, "See all", "+N sources", topic clicks, ransomware victims, and the
  Intelligence deep links (`lib/newsroom/links.ts`). `ArticleListSheet` is deleted.
- Every pre-redesign feature NR1-NR28 still reachable (6.9).

Non-goals:
- **`ArticleModal` is not restyled or changed** (user decision 2026-11-15, "2: separate pane"). It stays as it is for
  the entity Stories tab (`components/entities/entity-stories-tab.tsx`) and campaign clusters
  (`components/intelligence/campaign-clusters/article-by-id-dialog.tsx`). The reader is a separate component.
- No live per-filter source counts (B-N6), no "new since last visit" (B-N7), no story-cluster topics (B-N8), no ⌘K
  shortcut, no utility bar (D16).

Anti-goals (would make this a failure even if it works):
- A count on the source page (Early Warning, Risk Matrix, MITRE, entity pages, the Dashboard hero) that differs from
  the "{n} articles match" it links to.
- A request sent without the backend permission for it (`view_intel` for ransomware, `view_ta` watchlist names,
  `view_cve` tech stack, `view_stix` STIX, `manage_pir` watch, `manage_intel` override).
- A reader that loses the analyst's place: Back, refresh or a shared link must show the same filters and article.

## 3. Approaches considered

1. **Shared reader body** used by the pane and wrapped by `ArticleModal` (restyled modal everywhere). Rejected by the
   user.
2. **Separate reader pane; `ArticleModal` left as is. Chosen** (user, 2026-11-15). Cost: two article views exist
   (the new reader in the Newsroom, the old dialog on entity and cluster pages); accepted.
3. **Drop the dialog**, every page links into the reader. Rejected in the design discussion (entity and cluster pages
   would lose in-place reading).

## 4. Backend

### 4.1 B-N3 source-reliability filter

`GET /api/articles` gains `reliability_grade: list[Literal["A","B","C","D","E","F"]] | None = Query(None)`, applied as
`Article.reliability_grade.in_(...)` in `_apply_list_filters` (`packages/cti-core/.../repositories/article.py`).
Articles without a grade (`NULL`) are excluded when the filter is set. The same parameter is accepted wherever
`_apply_list_filters` is reached from `/api/articles` only; `list_filtered` (rejected articles) has no grade and is not
changed. Invalid letters give 422 (FastAPI `Literal`). Tests in `tests/integration/test_articles_combined_filters.py`:
one letter, two letters, combined with country and `sort=priority` (story dedup still applies), NULL excluded, 422.

### 4.2 B-N5 article IOC endpoint

`GET /api/articles/{article_id}/iocs` (router dependency `view_news`, same router as the other article routes) →
`list[ArticleIocOut]`, 404 when the article does not exist (the same way `GET /api/articles/{id}` does).

`ArticleIocOut`: `type: str`, `value: str` (stored value, **not** defanged; the UI defangs), `context: str | None`
(`IndicatorSource.context` of the source row for this article; the first non-empty one when several), `reputation:
str | None`. Response `ArticleIocsOut { items: list[ArticleIocOut], total: int }`. A new repository method
`AsyncIndicatorRepo.list_for_article(article_id, *, limit=200) -> tuple[list[tuple[Indicator, str | None]], int]`
(usable indicators joined to this article's `IndicatorSource` rows, one row per indicator with its first non-empty
context, ordered by type then value, capped at `limit`, plus the uncapped total); `list_by_article_ids` is not
changed. The UI header shows `total`; when `total > len(items)` the block adds "Showing the first 200."

`reputation` (builder's call within this rule): the worst verdict across the provider cards stored in
`Indicator.enrichment` (card shape in `apps/api/src/cti_api/services/ioc_providers.py`: `key`, `name`, `verdict`
`malicious | suspicious | clean | unknown`), rendered as "{verdict} ({provider name})", e.g. "malicious
(VirusTotal)"; `None` when there is no card or all are `unknown`.

`ArticleOut.iocs` stays `{}` (its docstring says so). Tests in a new `tests/integration/test_article_iocs_api.py`:
an article with two indicators from two source rows (one with context), an unusable indicator excluded, reputation
from a stored card, 404, 401 without auth, a role without `view_news` 403.

### 4.3 Contract

Regenerated once after 4.1 and 4.2 (`docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`): the `reliability_grade`
query parameter and the new route and schema, nothing else.

## 5. Migration and documentation

No migration, no `Settings` key. `CHANGELOG.md` (Indonesian) extends 0.8.16: All articles view with reader; grade
filter; article IOC endpoint; Newsroom and Intelligence links open All articles; list sheet removed.
`docs/prod-upgrade/0.8.16.md` and the 0.8.16 section of `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md`: one behaviour line and
the contract additions. `docs/PROGRESS.md` untouched.

## 6. UI

All 5a/5b web rules apply unchanged (theme tokens, `text-X-text` on tints, `text-2xs` floor, ids and counts in
`font-code`, " · " separators, no nested interactive elements, no clock reads in render, `parseLocalDate`,
`toLocaleString("en-US")`, every query through `unwrap` + `noClientRetry`, no polling, skeletons `aria-hidden`, stale
data dims, error panels only without data and with the server message, Base UI rules, one h1, h2 per section, h3 per
card, collapse below 1024 px).

### 6.1 View and URL

- The view switch becomes "Front page | All articles | Filtered" (`?view=all`, `?view=filtered`, none = Front page).
- **Derived view:** when `?view` is absent but any of `article`, `rubric`, `actor`, `industry`, `ttp`, `story` is
  present, the view is All articles (old links and the existing `newsroomHref` contract land here without a
  redirect). No effect rewrites the URL.
- All articles state, all in the URL (shareable, Back works), each written through 5b's guarded `writeParams`:
  `period` (`1|30|all`, none = 7d) or `from=YYYY-MM-DD` (as 5b); `country` (repeatable); `sector` (one industry);
  `source` (repeatable); `grade` (repeatable A-F); `rubric` (`apac|global|local|ransomware|watchlist|techstack`, none =
  All news); `actor` (repeatable), `ttp` (repeatable), `industry` (alias for `sector`, kept for `newsroomHref`),
  `story` (story id); `sort` (`recent`, none = priority); `article` (selected id). Search stays component state (5b).
- Filters set only by links (`actor`, `ttp`, `story`) have no rail control: they show as removable chips above the
  list ("Actor: Qilin ×", "Technique: T1486 ×", "Story: {lead title} ×").
- Without `view_news` the page gate of 5b applies. A `rubric` value the user may not see (ransomware without
  `view_intel`, watchlist without `view_ta`, techstack without `view_cve`) is ignored (All news), with no request.

### 6.2 Rail (D15; 236 px)

- PERIOD: 24h / 7d / 30d / All (5b period model).
- RUBRIC: list rows with counts: "All news", "APAC", "Global", "Local", "Ransomware", "Watchlist", "Tech stack" (the
  last three only with `view_intel` / `view_ta` / `view_cve`). Counts: one `page_size=1` query per row with the
  current filters except the rubric (articles via `rubricArticleQuery`, Ransomware via the victims total); a row whose
  count is loading shows a skeleton, a failed count shows "–". The selected row is tinted.
- SOURCE RELIABILITY (ADMIRALTY): six square toggles A-F (`aria-pressed`), none selected = all; tooltip per letter
  from the existing grade text table (`score-reasons.ts`).
- COUNTRY: multi-select (existing `CountryMultiSelect` if it fits Base UI rules, else a multi-select built on the
  same `/api/filters` country list) with selected names as chips.
- SECTOR: `Select` over `/api/filters` industries ("All sectors" first).
- SOURCES: the period's top 10 sources from `useDashboardStats(days)` `top_sources`, as checkboxes with their period
  count (labelled "in period", not live under the other filters).
- "Reset filters": clears every URL filter except `view` and `article`.

### 6.3 List (452 px)

- Header: "{n} articles match" (`total` of the list query; for Ransomware "{n} victims") and "Sort: Priority" /
  "Sort: Recent" (`Select`, `items` passed). Under priority sort the API returns one row per story, so `n` counts
  stories; the header says "{n} stories match" under priority sort and "{n} articles match" under recent sort (C15).
- Article row (`SelectableList`): `PriorityChip` + rubric labels (news type upper-cased; "WATCHLIST" / "TECH STACK"
  from `useArticleMatchers`), title (`line-clamp-2`), "{source}" + " +{source_count − 1}" when a story has more than
  one source + " · {articleWhen compact}", `GradeChip codeOnly`. Selected row tinted with a 2 px primary left rule;
  clicking a row writes `article`; ↑ / ↓ move the selection when the list has focus.
- Paging: 20 per step, `LoadMoreFooter` ("Load more", the existing component); new pages append.
- Ransomware rubric: victim rows "{victim} · {group}" / "{industry} · {countryName} · {date}", the victim name an
  external link to `post_url` when known, no reader selection; the rail adds "Group" and "Industry" selects from
  `/api/ransomware/victims/filters` (moved from the sheet); the list header shows "Related articles" as a second
  section under the victims with the `/api/ransomware/related-articles` rows (selectable into the reader), as the sheet
  had (NR13).
- States: first-load skeleton rows; empty: "No articles match these filters." with "Reset filters"; error with no
  data: 5a `PanelError` "Could not load the articles".

### 6.4 Reader (frame 2194; 638 px)

Data: the selected article from the loaded list when present, else `GET /api/articles/{id}` (deep link or an article
outside the current filters); IOCs from 4.2 (lazy, when the reader shows the article). With no `article` selected the
reader shows "Select an article to read it." (empty state). Unknown or deleted id: "This article is not available."

Top to bottom:
1. Action bar: "Open source ↗" (primary, external link, `rel="noopener noreferrer"`); "Watch {actor}" for the first
   threat actor with an entity id, only with `manage_pir` (`PUT /api/entities/{id}/watch`; "Watching ✓" when the actor
   is in `useWatchlistNames` or after success; with `view_ta` absent the state cannot be read, so the button always
   reads "Watch"); "+ Newsletter" (the queue in `lib/newsletter/queue.ts`, as `ArticleModal` does, with its
   "Queued" feedback); "{i} of {n} ‹ ›" stepping through the loaded rows (hidden when the article is not in the list).
2. Head: rubric labels + `PriorityChip`; `<h2>` title; "{source} · {fmtDateTime(first_seen_at)}" + " · also reported
   by {A, B, C} +{N}" from `GET /api/articles?story_id=` (other sources of the story, distinct, first three).
3. Credibility panel: big `admiralty_code`, the plain sentence and "Why this grade: …" lines from
   `score-reasons.ts` (`gradeLines` / `describePriority` family), the confidence score, the PIR and own-asset matches
   as lines; "Override" text button (only `manage_intel`) expands the existing `CredibilityOverride` form below.
4. "WHY IT RANKS" box (C20: not "first"): `priorityLines(article)`, hidden when `priority_score` is null.
5. Summary: `summary`, hidden when null.
6. Cards (2 x 2): THREAT ACTORS, MALWARE / TOOLS, COUNTRIES (role as small text: "victim", "origin"), IMPACTED
   INDUSTRIES (KW as small text) — names via `EntityChip`; empty cards hidden.
7. MITRE ATT&CK TTPS: chips "{id} {name}" with a source badge (ID / KW / LLM) and the evidence in a tooltip; "ATT&CK
   tagging pending" when `llm_ttp_status === "pending"`.
8. INDICATORS OF COMPROMISE · {n}: rows type | value (defanged: `.` → `[.]`, `http` → `hxxp`, `font-code`) | context
   (+ " · " + reputation) | copy button (copies the original value); "Copy all" (newline-separated originals);
   "Export STIX" only with `view_stix` (`GET /api/stix/article/{id}` download through `proxyFetch`); "Export CSV"
   (the existing CSV shape of `ArticleModal`). Hidden when there are no IOCs; loading skeleton; error `PanelError`
   "Could not load the indicators".
9. "More" `Disclosure` (closed by default, `printOpen` false): the hunting pack (`HuntPanel` for the story), D3FEND
   per technique (`D3fendToggle`), known TTPs of related entities (`InferredTtpsSection`), and the note
   "Classification inherited from the lead article." when `classify_inherited_from` is set. Their lazy requests run
   only after the disclosure is first opened.

### 6.5 Where clicks and links go (D10, D11)

- Front page and Dashboard article clicks: navigate to `/newsroom?view=all&article={id}` plus the source page's period
  (Newsroom period as is; Dashboard `1|7|30|all` as is, `90` as `from` = today − 89 days). The 5a `useArticleOpener`
  is replaced by a navigation helper on the Dashboard; `ArticleModal` is no longer mounted on the Dashboard or the
  Newsroom.
- "See all" on a rubric column → `?view=all&rubric={key}` with the current period and country; "+N sources" →
  `&story={id}`; topic click → `&actor={name}` or `&ttp={id}`.
- Dashboard hero links (5a `needs-action.tsx`): `?rubric=ransomware|watchlist…` keep working through the derived view
  (6.1); their `href`s are updated to include `view=all` for clarity.
- `newsroomHref` (`lib/newsroom/links.ts`) gains `view: "all"` in its output; its parameters and meaning are unchanged,
  so Early Warning, Risk Matrix, MITRE, Exec and entity links land on All articles with the same filters (`actor`,
  `industry` → sector, `ttp`, `country`, `from`, `period`) and the same count.
- `ArticleListSheet` and its imports are deleted.

### 6.6 States

- Loading: rail counts, list and reader each show their own skeleton.
- Errors: per panel (`PanelError` with the server message, Retry); the reader's IOC block fails on its own.
- Empty: list empty state (6.3); reader with no selection (6.4).
- No access: page gate (5b).

### 6.7 Responsive

Three columns from 1280 px (236 / flexible list ≥ 360 / reader ≥ 520); 1024-1279 px: rail collapses into a "Filters"
`Disclosure` above the list, list and reader side by side; below 1024 px: one column, the reader below the list and the
selected row scrolls the reader into view.

### 6.8 Permissions (summary)

`view_news` page; rail rows / rubric / deep links: Ransomware `view_intel`, Watchlist `view_ta`, Tech stack `view_cve`;
reader: Watch `manage_pir` (watched state needs `view_ta`), Override `manage_intel`, Export STIX `view_stix`; IOC
endpoint `view_news`.

### 6.9 Feature map (changes from 5b)

| Pre-redesign | After 5c |
|---|---|
| NR12 list sheet (rubric / actor / TTP / story / combined) | All articles with the matching filters (6.5) |
| NR13 ransomware sheet (group / industry filters, related articles) | Ransomware rubric in All articles (6.3) |
| NR14 deep links | derived view + URL filters (6.1); `newsroomHref` output adds `view=all` |
| NR15-NR25 article modal (on Newsroom and Dashboard) | reader pane (6.4); the modal remains for entity and cluster pages (NR28) |
| NR22 IOC section + CSV (always empty) | IOC block from 4.2 with Copy all, CSV, STIX |
| NR23 "+ Newsletter" | reader action bar |

### 6.10 Rules settled after the builder check (binding; the author's calls, for the user to check)

1. **Rubric + link filters combine as AND.** Watchlist with an `actor` chip uses the intersection of the watched names
   and the chip's names (case-insensitive) as `threat_actor`; an empty intersection shows the list empty state without
   a request. Tech stack (`title_keyword`) and the `ttp` / `story` / `country` / `sector` / `source` / `grade` filters
   combine with any rubric as AND (separate API parameters).
2. **Rubric with no names.** The Watchlist / Tech stack rail row shows count 0 when the names list is empty, and the
   list shows "No watched actors yet." / "No tech stack yet." (5b copy, with "Set up tech stack" → `/cve`); while names
   load, the row count and the list show skeletons. Tech stack sends the names exactly as `useRubric` does today (no
   change in 5c).
3. **Sources outside the top 10** (from a `source` URL value) are listed first, checked, without a count. The sources
   list uses `useDashboardStats(days)` with `days` from the period, and for `from` the number of days from `from` to
   today (inclusive).
4. **Sort.** The All articles default stays priority (frame), but every link that carries a count to match lands with
   `sort=recent`: `newsroomHref` adds `sort=recent`, and so do "See all", topic, story and Dashboard hero links. The
   header wording follows the sort ("{n} articles match" under recent, "{n} stories match" under priority). Rail
   rubric counts always count articles (recent semantics), labelled as such by the header sort choice.
5. **Story.** The `story` filter forces recent sort (a story under priority sort would collapse to one row), and the
   reader's "also reported by" query uses `story_id` with `sort=recent`.
6. **Search and incidents in the URL.** In All articles, search is `q` and "Incidents only" is `incidents=1` (a rail
   checkbox under PERIOD), both shareable and cleared by "Reset filters"; the Front page keeps them as component state
   (5b), and a Front-page click into the reader passes the current search and incidents into the link.
7. **Ransomware filters.** Victims use period (`date_start`), country (first selected country, as the victims API
   takes one) and the Group / Industry selects; grade, sector, sources, search and incidents do not apply and are
   shown disabled with the hint "Not used for victims". The Ransomware rail count is the victims total under period +
   country. "Related articles" uses the period only.
8. **Blast radius.** `ArticleListSheet` is imported only by `newsroom-view.tsx`; `ArticleModal` is mounted by
   `components/dashboard/article-opener.tsx` (Dashboard) and `newsroom-view.tsx` (removed in 5c) and stays in
   `entity-stories-tab.tsx` and `campaign-clusters/article-by-id-dialog.tsx`. `useArticleOpener` is deleted once the
   Dashboard uses the navigation helper. Leaving the Front page for the reader keeps the Front page's URL state (Back
   returns to it); its component state (search, rubric select) is not kept.
9. **Back below 1024 px** is browser Back (the URL holds `article`); selecting a row scrolls the reader into view
   once, after the article loads.
10. **Keyboard.** ↑ / ↓ use `SelectableList`'s existing key handling; when it has none, the list `ul` handles
    ArrowUp / ArrowDown while focused and moves `article` to the previous / next loaded row.
11. **Watch** with `manage_pir` but without `view_ta`: the button reads "Watch" and a successful PUT changes it to
    "Watching ✓" for that article view; a repeat watch is harmless (idempotent PUT).
12. **`sector` wins over `industry`** when both are present.

## 7. Out of scope

`ArticleModal` restyle; B-N6, B-N7, B-N8; ⌘K; utility bar; mobile below 375 px.

## 8. Verification

- Backend: the 4.1 and 4.2 tests; `tests/integration -k "article or newsroom or stix"`; fast suite; ruff, mypy; the
  regenerated contract shows only 4.3's additions.
- Web: lint, `next typegen && tsc --noEmit`, build.
- Browser (local `qafig` + seed5a; add a few indicators with source rows for two articles):
  - URL: every filter round-trips through the URL; Back and refresh keep filters and the selected article; an old
    `/newsroom?actor=Qilin&ttp=T1486&from=2026-11-03` link lands on All articles with chips and the same count as
    `/api/articles` with those parameters; Dashboard hero links and article clicks land with the right period.
  - Rail: counts per rubric equal the list total after selecting that rubric; grade toggles narrow the list; reset.
  - List: priority vs recent header wording; load more appends; ↑ / ↓ selection; ransomware victim rows and related
    articles.
  - Reader: every block on an article with full data and on a sparse article; IOCs defanged, copy and copy all,
    STIX only with `view_stix`; Watch only with `manage_pir`; Override only with `manage_intel`; More loads only on
    open.
  - Roles: `view_news`-only role sends no ransomware, watchlist-names, techstack, STIX or hunt requests it may not.
  - Light and dark; 1440, 1100 and 1000 px.

## 9. Risks

- **Count parity with Intelligence pages** depends on `newsroomHref` parameters mapping one-to-one onto the list
  query (the sheet's combined query today); covered by the URL check in 8.
- **Rubric counts cost** seven small queries per filter change; acceptable (each `page_size=1`), and they share
  React Query caching with the Front page.
- **Two article views** (reader and the unchanged modal) can drift in content; accepted by the user (section 3).
