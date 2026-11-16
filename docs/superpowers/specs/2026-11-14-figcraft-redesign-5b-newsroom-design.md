# FigCraft redesign, sub-project 5b: Newsroom Front page and Filtered

Date: 2026-11-14. Status: draft for review. Branch: `claude/figcraft-design-data`. Same one-PR release 0.8.16 (the
CHANGELOG entry and the 0.8.16 runbooks are extended, no extra version bump).

## 1. Context and goal

Sub-project 5 was split into 5a Dashboard (done, merged into `origin/Dev` at `6cdc0dbe`), **5b Newsroom Front page and
Filtered (this spec)** and 5c Newsroom All articles + reader (user decision 2026-11-14, "Split 5b / 5c"). 5a delivered
the pieces 5b reuses: `ArticleOut.summary` (dek) and `first_seen_at` (hours), `articleWhen`, `PriorityChip`,
`priorityTone`, `priorityLines`, `GradeChip codeOnly`, `PanelError`, `useArticleOpener`, the `unwrap` /
`noClientRetry` query rules, the period-in-URL model (`lib/dashboard/period.ts`) and the guarded `router.replace`
pattern.

FigCraft frames (light): Newsroom / N1 Front Page (1402) and Newsroom / States (32387). N2 Analyst Reader (2194) is
5c. Source inventory: `.superpowers/brainstorm/sp5-inventory.md` (features NR1-NR28, gaps GNR1-GNR45, conflicts
C15-C28, decisions D9-D19); where it differs from this spec, this spec wins.

Goal: the N1 Front page and the four States on `/newsroom`, the Filtered tab restyled, wider search (B-N4), English
copy, with every pre-redesign feature NR1-NR28 still reachable (6.9). 5c will add the "All articles" view, the reader
pane, the grade filter (B-N3), article IOCs (B-N5) and the rewiring of clicks into the reader (D10, D11).

## 2. Decisions (binding)

From the sp5 decision list (accepted 2026-11-13) and the 5b design approval (2026-11-14):

- **D2** English copy everywhere on the page, including the sheet and the Filtered tab.
- **D12** Ransomware stays a victims rubric. The "All rubrics" select narrows the Front page to one rubric (6.4).
  Watchlist and Tech stack columns stay visible with an empty line when the user has the permission.
- **D13** No "new since your last visit"; the kicker is "NEWSROOM".
- **D14** Active topics stay actor / technique trends, six cards (name, count, "+n today", bars).
- **D17** States as drawn, with the real error text (no "30 s").
- **D18** The Filtered tab is visible to every `view_news` user (the API allows it); each action is gated by its own
  permission; no locked tab.
- **D19** Priority and grade are separate chips (`PriorityChip`, `GradeChip codeOnly`).
- **S1 (5b split)** Until 5c: article clicks open `ArticleModal`; "See all", "+N sources", topic clicks and deep links
  open `ArticleListSheet`. Neither component changes beyond the English copy of the sheet (6.6).

Flagged choices (made in the design, the reviewer may object):

- **P1** The period keeps "All" (24h / 7d / 30d / All) and the page keeps an "Incidents only" toggle, although the
  frame has neither, so NR3 and NR4 stay reachable.
- **P2** Period and country live in the URL; search, the incidents toggle and the rubric select are component state.
- **P3** The count line counts **articles** under the current filters (a `sort=recent` query), not stories (C15);
  "from {m} sources" is printed only without a search or country filter, because the source count is unfiltered.
- **P4** The lead and secondary kickers use the article's `news_type` as the rubric word (as Must read does in 5a).
- **P5** "+n today" is the last value of the topic's `daily` series; when it is 0 the part is omitted.
- **P6** Without `view_ta` / `view_cve` the Watchlist / Tech stack columns are hidden and send no request (5a rule:
  gate on the real backend permission); with the permission and no names they show the empty line (D12).
- **P7** The empty state's "newest match" comes from one extra `GET /api/articles` without the period
  (`page_size=1`, `sort=recent`), sent only when the period query returned zero.

## 3. Conflicts resolved

- **C15 Totals.** `sort=priority` returns one row per story. The count line uses a recent-sorted query (P3); rubric
  totals already use recent sort.
- **C16 Active topics** are trends, not clusters (D14); the subtitle names them.
- **C17 Ransomware** stays the victims list with external links (D12); its sheet keeps the group / industry filters.
- **C19 States frame** is older (two views, a "Sector" chip). The view switch has two options in 5b ("Front page",
  "Filtered"; 5c adds "All articles"); filter chips are built from the filters the page has (search, period, country,
  rubric, incidents, `from`). No sector control in 5b (the rail with Sector is 5c).
- **C22** No "48 new" count (D13).
- **C23 Error copy.** The banner prints the server message (`error.message`, fallback "The request failed.") and the
  time of the last good copy; no "30 s".
- **C24 Filtered permission.** Tab shown with `view_news` (D18); Restore, Accept, Reject need `manage_sources`; Retry
  needs `manage_scraper`.
- **C25 Grade chip.** `GradeChip codeOnly` + `PriorityChip` (raw score, tones from `priorityTone`).
- **C29 Layout title.** `app/(app)/newsroom/layout.tsx` (string `metadata.title`) is deleted; the server `page.tsx`
  sets static `metadata = { title: "Newsroom" }`.

## 4. Backend: B-N4 wider search

Today `GET /api/articles` matches `search` against `title` and `source` (`_apply_list_filters`,
`repositories/article.py:147`), and the trending query behind `/api/newsroom/topics` matches the title only
(`repositories/dashboard.py:586`). The placeholder already promises actors and CVEs.

- **Rule (one helper, both places):** `search` matches when any of these case-insensitive substring tests holds:
  `Article.title`, `Article.source`, the `name` of a live threat-actor (`ACTOR`) mention of the article, or the
  `external_id` of a live vulnerability (`CVE`) mention of the article. Mentions through `mention_rows(ACTOR)` /
  `mention_rows(CVE)` as `Article.id.in_(select(m.c.article_id).where(...))` subqueries, so counts do not multiply.
- **Helper:** `article_search_clause(search: str) -> ColumnElement[bool]`, module level in
  `cti_core.db.repositories.article` (Indonesian docstring: why the list and the trend query share it).
  `_apply_list_filters` uses it in place of `search_or`, keeping today's combination with `keyword_or` (both must
  hold). `AsyncDashboardRepo.daily_entity_counts` uses it in place of the title-only `where`.
- **Literal input:** `%`, `_` and `\` in the user's text are escaped and every test uses
  `ilike(pattern, escape="\\")`, so "100%" matches literally. Today's code does not escape; this is a fix in passing,
  named in the CHANGELOG.
- Unchanged: parameters, response schemas, the trending cache key (it already contains `search`), every other filter.
  No contract change, no migration.
- Tests: `tests/integration/test_article_query.py`: title, source, actor name, CVE id each match; a merged (dead)
  actor's name does not; "100%" matches only the literal; search combined with `title_keyword` needs both.
  `tests/integration/test_newsroom_api.py`: a topics search for an actor name returns that actor's trend, and its
  `count` equals the number of articles `/api/articles?search=` returns for the same window.

## 5. Migration and documentation

No migration, no `Settings` key, no contract change. `CHANGELOG.md` (Indonesian) extends the 0.8.16 entry: Newsroom
Front page redesign (English copy, period in the URL, rubric narrowing, six topic cards, the four states), the
Filtered tab for every `view_news` user with per-button permissions, and the wider search (actor names and CVE ids,
`%` / `_` matched literally). `docs/prod-upgrade/0.8.16.md` and the 0.8.16 section of
`docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` gain one behaviour-change line each (Newsroom redesign; search also matches
actors and CVE ids; Filtered visible to `view_news`) and nothing else. `docs/PROGRESS.md` is not touched.

## 6. UI

Global rules (from 5a, binding): theme tokens only; text on tints `text-X-text`; `text-2xs` floor; ids and counts in
`font-code`; separators " · "; no nested interactive elements (titles are `<button>`s, chips are siblings);
`table-fixed` with `<colgroup>`; no `Date.now()` / `new Date()` in render; `parseLocalDate` for date strings; numbers
via `toLocaleString("en-US")`; every query through `unwrap` with `retry: noClientRetry`, no `refetchInterval`;
skeleton on first load (`aria-hidden`), stale data dims (`opacity-60` while `isPlaceholderData`), an error panel only
when the query has no data (the 5a final rule), `PanelError` with the server message; h2 per section, h3 per card;
Base UI (`render={...}`, `SelectItem` single string, `items` on every `Select`); desktop 1440 first (content 1328),
multi-column rows collapse below 1024 px (`lg:`).

### 6.1 Page shell and URL

- `app/(app)/newsroom/page.tsx`: server component, `export const metadata: Metadata = { title: "Newsroom" }`,
  renders `<Suspense><NewsroomView /></Suspense>`. `layout.tsx` deleted.
- `components/newsroom/newsroom-view.tsx` (`NewsroomView`, client):
  - Gate: without `can("view_news")` only the header and `StatePanel variant="no-access"` "Newsroom needs the
    view_news permission" / "Your role ({user.role}) does not have it."; nothing else mounts, no request.
  - View: `view = searchParams.get("view") === "filtered" ? "filtered" : "front"`. `SegmentedControl
    aria-label="Newsroom view"` with "Front page" and "Filtered"; selecting writes `?view=filtered` or removes it.
  - Period: `lib/newsroom/period.ts` exports `NewsroomPeriod = "1" | "7" | "30" | "all"`, `NEWSROOM_PERIODS` (labels
    "24h" / "7d" / "30d" / "All"; `days` 1 / 7 / 30 / null; `words` "24 hours" / "7 days" / "30 days" / "all time";
    `suffix` "in the last 24 hours" / "in the last 7 days" / "in the last 30 days" / "of all time") and
    `parseNewsroomPeriod(value)`: `?period=1|30|all`; no parameter or any other value is 7d. `dateStart =
    periodStart(days)` (`lib/newsroom/filters.ts`, unchanged: local calendar days), `""` for All.
  - `?from=YYYY-MM-DD` (validated by the existing `validFrom`): when valid it wins over `period` as `dateStart`, the
    period control shows no selection, and a removable chip "From {fmtShortDate(parseLocalDate(from))}" sits in the
    filter row; choosing a period or removing the chip deletes `from`. The sentence suffix with `from` is "since
    {fmtShortDate(parseLocalDate(from))}".
  - Country: `?country=XX` (upper-cased through 5a's `normalizeCountry`), or none.
  - URL writes: one helper `writeParams(patch)` copies the current params, applies the patch and calls
    `router.replace(next, { scroll: false })` only when `next` differs from the current URL and the chosen option
    differs from the current one. No effect writes the URL.
  - Deep links kept (NR14), read once on mount exactly as today: `?rubric=` opens that rubric's sheet; `?actor`,
    `?industry`, `?ttp` open the combined sheet (`linkedSheet`, unchanged). `lib/newsroom/links.ts` unchanged.
  - Component state: `search` (300 ms debounce, as today), `incidentOnly` (default false), `rubric` select (default
    all), the sheet. Article clicks call `openArticle` of `useArticleOpener` (5a); its `host` is mounted once.

### 6.2 Header and filters (frames 1457, 1469)

- `PageHeader`: kicker "NEWSROOM", title "Newsroom", description = the count line "{n} cyber articles from {m} sources
  {suffix}" (P3). `n` = `total` of `GET /api/articles` with the current filters, `sort=recent`, `page_size=1`. `m` =
  `total_sources` of `useDashboardStats(days, incidentOnly)` (5a hook; same key as the Dashboard). Without `m` (search
  or country set, `from` set, or `m` not loaded) the line is "{n} cyber articles {suffix}"; while `n` loads, a
  one-line skeleton; on error the line is omitted.
- `actions` = the view `SegmentedControl` (6.1).
- Filter row (Front page only): search `Input` (`aria-label="Search articles"`, placeholder "Search title, source,
  CVE, actor…", 420 px at desktop), period `SegmentedControl aria-label="Period"`, country `Select` ("All countries" +
  the `/api/filters` countries by `countryName`, `items` passed), rubric `Select` ("All rubrics", "APAC", "Global",
  "Local", "Ransomware victims", "Watchlist", "Tech stack"; the last two only with their permission), a `Checkbox` with
  a real `<label>` "Incidents only", then the `from` chip when set.

### 6.3 Front page (frame 1493)

Two-column row `lg:grid-cols-[minmax(0,820fr)_minmax(0,468fr)]`. One query: `GET /api/articles` `sort=priority`,
`page_size=4` with the filters and the rubric narrowing (6.4); `articles[0]` is the lead, `1..3` the secondary.

- **Lead** (`<article aria-label="Top story">`): kicker "TOP STORY" + " · {NEWS_TYPE}" (omitted when empty) + " · " +
  `PriorityChip` (omitted when `priority_score` is null) + `GradeChip codeOnly` (when `admiralty_code`). `<h2>` holding
  a `<button>` → `openArticle`. Dek = `summary` (`line-clamp-3`, not rendered when null). Meta "{source}", then, when
  `story.source_count > 1`, a text button "+{source_count − 1} sources" → the story sheet (NR7), then " · {when}"
  (`articleWhen`, `title` "First seen …"). Chips after the meta: the first two TTPs (`EntityChip attack-pattern`), the
  first `vulnerability` entity (`EntityChip vulnerability`, `external_id`), the first actor (`EntityChip
  intrusion-set`). Flags as in 5a Must read: "Incident", "Watchlist", "Tech stack" (`useArticleMatchers`), "ATT&CK
  PENDING". "WHY IT RANKS FIRST" on one line: label (`text-2xs`, uppercase) then `priorityLines(article).join(" · ")`;
  not rendered when `priority_score` is null or the list is empty.
- **Secondary** (`<ol aria-label="Also on the front page">`, up to three): kicker "{NEWS_TYPE}" + `GradeChip
  codeOnly`; `<h3>` with a `<button>` (`line-clamp-2`); "{source} · {when}" (compact) and the same flags.
- States: first load a skeleton (lead block 280 px + three rows); error with no data → `PanelError` "Could not load the
  front page"; zero articles → the Empty state of 6.7 in place of the lead and secondary.

### 6.4 Rubric narrowing ("All rubrics" select, D12)

The article filter per rubric is the one `useRubric` builds today; it is extracted into a pure
`rubricArticleQuery(key, filters, ctx) -> ArticleQueryParams | null` in `rubric-queries.ts` (`ctx` = client countries,
watch names, tech names) and used by `useRubric` and the front query, so both stay identical: APAC
`news_type=["apac"]` + country; Global `news_type=GLOBAL_NEWS_TYPES` + country; Local `country=client_countries`;
Watchlist `threat_actor=watch names`; Tech stack `title_keyword=tech names`; Ransomware `null` (victims). With a
rubric selected: the front query adds that filter (Ransomware: the lead and secondary block is not rendered); the
count line adds the same filter; Active topics are unchanged; the rubric grid shows only that column, with nine
items. With Watchlist or Tech stack selected and no names configured, the front area shows the column's empty line.

### 6.5 Active topics (frame 1539) and Rubrics (frame 1635)

- **Active topics:** `<h2>` "Active topics", subtitle "Rising actors and techniques, {words}". `GET
  /api/newsroom/topics` with `limit=6` and the filters (as today). Cards in `grid sm:grid-cols-2 lg:grid-cols-3
  xl:grid-cols-6`: the name as a `<button>` → the topic's sheet (as today), a kind chip ("Actor" / "Technique"), the
  count (`font-code`), "+{daily[last]} today" (P5), `BarSeries` over `daily` (`aria-hidden`, plus a visually hidden
  "{count} mentions in {window_days} days"). Empty: "Nothing is rising in this period." Error: `PanelError` "Could not
  load active topics".
- **Rubrics:** `<h2>` "Rubrics"; grid `lg:grid-cols-3` (3 x 2), each column a `Card`: `<h3>` title, total
  (`font-code`), "See all →" text button → sheet; three items (nine when narrowed). Article item: title `<button>`
  (`line-clamp-2`), "{source} · {when}" (compact), `GradeChip codeOnly`. Victim item: "{victim} · {group}" (the victim
  name an external link to `post_url` when known, as today), second line "{industry} · {countryName} · {date}"
  (`fmtShortDate(parseLocalDate(published))`). Column empty: "Nothing in this period."; Watchlist with no names: "No
  watched actors yet."; Tech stack with no names: "No tech stack yet." with a link "Set up tech stack" → `/cve`.
  Column error: `PanelError` "Could not load {title}". Watchlist and Tech stack are rendered only with `view_ta` /
  `view_cve` (P6).

### 6.6 Sheet (`article-list-sheet.tsx`)

Copy translated to English only ("Ransomware victims" instead of "Korban ransomware", "Related articles", pager labels,
empty and error lines); behaviour, props, queries and the ransomware filters unchanged. Replaced in 5c.

### 6.7 States (frame 32387)

- **Loading:** each section's skeleton keeps the grid (no extra delay logic).
- **Empty** (front query loaded with `total === 0`): `StatePanel variant="empty"` in the front area with removable
  chips for the active filters ("“{q}”", "{countryName}", "{rubric title}", "Incidents only", "From {date}"; each
  removes its filter); title "No articles {suffix}", plus " for {countryName}", " matching “{q}”", " in {rubric}"
  when set (in that order, joined with ","); description "The newest match is from {fmtAgo(first_seen_at)}. Widen the
  period or remove a filter." (P7) or, when nothing matches at any time, "Nothing matches these filters at any time.";
  action "Show last 7 days" (from 24h), "Show last 30 days" (from 7d), "Show all time" (from 30d), none for All or
  `from`. Topics and rubrics still render below with their own empty lines.
- **Error:** when the front query fails while it still has data (a failed refetch), a `Notice tone="warning"` above
  the front page: title "Could not refresh the newsroom", body "{message} Showing the copy from
  {fmtTime(dataUpdatedAt)}; your filters are kept.", action "Try again" (refetches the front, count, topics and rubric
  queries). With no data, `PanelError` (6.3).
- **No access:** the page gate of 6.1. No locked Filtered tab (D18).

### 6.8 Filtered tab

`FilteredView` restyled, same queries and actions (NR26, NR27): `SegmentedControl aria-label="Filtered articles"`
"Not cyber-related" | "Enrichment queue" replaces `TabPills`; `PanelShell` keeps title, count, refresh and search;
rows keep every field (state, attempts, age, `p_threat_news`, last error, failure kind, reason). Copy: panel title
"Not cyber-related" (today "Not Related Cyber"); hint text in English. Buttons only with their permission: Restore,
Accept, Reject `manage_sources`; Retry `manage_scraper`. Without them the lists are read-only.

### 6.9 Feature map (NR1-NR28)

| Pre-redesign | After 5b |
|---|---|
| NR1 view tabs | "Front page" / "Filtered" switch (6.1); Filtered for every `view_news` user (D18) |
| NR2 masthead date + total | count line (6.2); date dropped |
| NR3 period incl. All | period control (P1) |
| NR4 "Insiden saja" | "Incidents only" (P1) |
| NR5 country select | country select (6.2) |
| NR6 debounced search | search, wider (B-N4) |
| NR7 front lead + 3, badges, "+N sources" | 6.3 |
| NR8 front skeleton / error / empty | 6.3, 6.7 |
| NR9 active topics | 6.5 (six cards; top countries and latest article leave the card, D14) |
| NR10, NR11 six rubrics and their rules | 6.5, 6.4 (Watchlist / Tech stack with permission, P6) |
| NR12, NR13 list sheet, ransomware sheet | 6.6 (until 5c) |
| NR14 deep links | 6.1 |
| NR15-NR25, NR28 article modal | `ArticleModal` unchanged (5c restyles it) |
| NR26, NR27 Filtered | 6.8 |

## 7. Out of scope (5c or later)

"All articles" view, reader pane, filter rail (grade, multi-country, sector, sources), B-N3, B-N5, rewiring clicks
and deep links into the reader, the `ArticleModal` restyle, Dashboard → reader links, B-N6 / B-N7 / B-N8, the utility
bar.

## 8. Verification

- Backend: the B-N4 tests (section 4); `uv run pytest tests/integration -k "article or newsroom or trending"`; fast
  suite; ruff, mypy. No contract drift (`export_openapi` + `gen:api` give no diff).
- Web: lint, `next typegen && tsc --noEmit`, build.
- Browser (local `qafig` stack with seed5a plus articles whose only match for a search term is an actor or a CVE
  mention):
  - URL: `?period=abc`, `?period=0`, `?period=ALL`, `?period=1&period=30`, `?view=filtered`, `?from=2026-11-03`,
    `?country=sg`, `?rubric=ransomware`, `?actor=Qilin&ttp=T1486` load without a redirect; re-selecting the current
    option sends no navigation; the Dashboard's three hero links land on the right sheet or filter.
  - Front page: lead with dek, "+N sources" opens the story sheet, flags, the "why" line; three secondary; narrowing
    to each rubric (Ransomware hides the lead block); six topic cards; rubrics 3 x 2 with the victims column.
  - Search "Qilin" and a CVE id find articles without the term in the title or source; the Qilin topic count equals
    the article count.
  - States: empty with chips and the widen button; error banner after stopping the API and refocusing the tab;
    no-access role.
  - Filtered: both lists, each button only with its permission.
  - Light and dark, 1440 and 1000 px; tab title "Newsroom · {PLATFORM_NAME}"; no hydration warning.

## 9. Risks

- **Search cost.** Two extra `IN (subquery)` clauses on every searched list and trend query; mentions are indexed by
  article and entity; checked in QA on the seeded database.
- **Interim UX.** Until 5c the Front page uses the dialog and the sheet; the page is coherent on its own.
- **Deep-link contract.** `lib/newsroom/links.ts` and the read-once deep links are unchanged; the Dashboard links
  (`?rubric=ransomware|watchlist`, `?period=1|7|30`, `?country=`) keep their meaning.
