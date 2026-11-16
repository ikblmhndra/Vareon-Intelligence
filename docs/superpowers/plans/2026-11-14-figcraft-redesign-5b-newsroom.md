# FigCraft redesign 5b: Newsroom Front page and Filtered Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the N1 Front page, the four States and the restyled Filtered tab on `/newsroom` (English copy, period and country in the URL, rubric narrowing, six topic cards, 3 x 2 rubric grid), plus the wider search B-N4, inside the 0.8.16 release, with every pre-redesign feature NR1-NR28 still reachable.

**Architecture:** One backend task (B-N4: a shared `article_search_clause` used by the article list and the trend query). On the web: a data-layer task (period model, query hooks through `unwrap`, the extracted `rubricArticleQuery`), a shell task (server page, `NewsroomView` with the gate, URL state, header, filter bar and section stubs), then the sections in parallel (front page with states, topics, rubric grid), the sheet copy and the Filtered restyle (disjoint files, can start early), cleanup and docs. `ArticleModal` and `lib/newsroom/links.ts` are not modified.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, pytest + testcontainers; Next.js 16 App Router, React 19, TanStack Query (`keepPreviousData`), Tailwind v4, shadcn on Base UI, `openapi-fetch`.

**Spec:** `docs/superpowers/specs/2026-11-14-figcraft-redesign-5b-newsroom-design.md` (binding; section numbers below refer to it; P1-P7 are its flagged choices, NR its feature map). Fixed copy is in the spec and is not repeated here. 5a's spec (`docs/superpowers/specs/2026-11-14-figcraft-redesign-5a-dashboard-design.md`) defines the reused helpers.

**Parallel map (the controller's schedule).** Task 1 (backend), Task 2 (data layer), Task 7 (sheet copy), Task 8 (Filtered) and Task 10 (docs) touch disjoint files and can run side by side. Task 3 after Task 2. Tasks 4, 5, 6 after Task 3, side by side. Task 9 after 3-8. Task 11 last.

## Global Constraints

- No migration, no `Settings` key, no new route, no contract change: after Task 1 `uv run python tools/export_openapi.py` and `pnpm run gen:api` give no diff. Release stays 0.8.16, one PR, no version bump.
- Backend: comments and docstrings Indonesian, explaining why. `persist`, `ArticleRepo.upsert`, the trending cache key and every other filter unchanged.
- Not modified: `components/newsroom/article-modal.tsx`, `lib/newsroom/links.ts`, `components/dashboard/*` (5a), `components/world-dots.tsx`.
- Commits: English conventional; body ends with a blank line + the implementer's own model trailer (`Co-Authored-By: <model> <noreply@anthropic.com>`). Stage only your own files; never push, merge or switch branches.
- Python checks: `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src packages/cti-scraper/src`; fast suite `uv run pytest tests/unit tests/contract packages --deselect tests/contract/test_golden.py::test_golden_trendmicro`. Integration needs Docker (never touch `deploy-postgres-1`).
- Web (`apps/web`): read `apps/web/AGENTS.md` and `apps/web/CLAUDE.md` first. All 5a rules hold: theme tokens only, text on tints `text-X-text`, `text-2xs` floor, ids and counts in `font-code`, " · " separators, focus ring `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background`, Base UI (`render={...}`, `SelectItem` one string, `items` on every `Select`), no `backdrop-blur`, no `Date.now()` / `new Date()` in render (read "now" inside a `queryFn` or use a query's `dataUpdatedAt`), `parseLocalDate` for date strings, numbers via `toLocaleString("en-US")`, two-column row `lg:grid-cols-[minmax(0,820fr)_minmax(0,468fr)]`, collapse below 1024 px.
- Lessons (each a review item): (a) no nested layout with a string title; the title is static `metadata` on the server `page.tsx`; (b) every `queryFn` through `unwrap` (`lib/scrapers/queries.ts`), never `if (error) throw`; (c) every query `retry: noClientRetry`; (d) no interactive element inside another (titles are `<button>`s, chips are siblings); (f) gate on the real backend permission via `useCan()`: `view_news` page, `view_ta` Watchlist, `view_cve` Tech stack, `manage_sources` Restore / Accept / Reject, `manage_scraper` Retry; (i) no clock reads in render; (j) never `router.replace` to the current URL or to re-select the current option, and no effect writes the URL; (l) no `refetchInterval`; (o) error panels print the server message, fallback "The request failed."; error panels only when the query has no data (`isError && !data`); stale data dims `opacity-60` on `isPlaceholderData`.
- The Newsroom's own `PanelError` in `panel-shell.tsx` (Filtered tab) and 5a's `PanelError` in `components/dashboard/stat-box.tsx` are different components: the sections of Tasks 4-6 use 5a's (`title`, `error`, `onRetry`).
- Web verification: `export PATH="$HOME/.local/share/fnm/aliases/default/bin:$PATH"`, then from `apps/web` `pnpm lint` and `pnpm exec tsc --noEmit`. When web tasks run in parallel they share `.next`: the controller runs `next typegen` before and `pnpm build` after a batch; implementers never run `pnpm build`, `next typegen` (except Task 3) or `pnpm dev`. Browser checklists are run by the controller on the local `qafig` stack; implementers explain each checklist line by construction (file:line).
- Copy: English (D2), verbatim from the spec. After Task 9, `rg -n "Lihat semua|Insiden|sumber|Korban|Semua|jam|hari|Gagal|Belum|Artikel terkait" apps/web/src/components/newsroom "apps/web/src/app/(app)/newsroom"` shows comments only.
- No subagent re-delegation inside a task. Do not push.

## Review Focus

1. **Search text with SQL wildcards.** "100%", "a_b" and a backslash must match literally, in the list and in the topics trend (Task 1, `test_search_escapes_wildcards`).
2. **Rubric narrowing with no names.** Selecting Watchlist or Tech stack when the client has no watched actors / no tech stack must send no `/api/articles` with an empty `threat_actor` / `title_keyword` (which would mean "no filter" and show the whole feed) and must show the column's empty line (Task 2 `rubricArticleQuery` returns `"no-names"`; Task 4 checklist).
3. **A Dashboard deep link with filters.** `/newsroom?rubric=ransomware&period=1&country=SG` opens the victims sheet and also sets the period and country; `/newsroom?rubric=watchlist&period=7` opens the watchlist sheet on 7d; closing the sheet leaves the URL as it is, with no loop (Task 3 checklist).
4. **`from` with the count line and the empty state.** With `?from=` the count line reads "since {date}", omits "from {m} sources", the empty state offers no widen button, and picking a period removes `from` in one replace (Tasks 3 and 4 checklists).
5. **No match at any time.** When even the period-less query is empty, the empty state says "Nothing matches these filters at any time." and prints no age (Task 4 checklist; the newest-match query is sent only when the period query returned zero).

---

### Task 1: B-N4 wider, literal search (spec 4)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/article.py` (`_apply_list_filters`, new module-level helper), `packages/cti-core/src/cti_core/db/repositories/dashboard.py` (`daily_entity_counts`, the `if search:` line ~586)
- Test: `tests/integration/test_article_query.py`, `tests/integration/test_newsroom_api.py`

**Interfaces:**
- Produces: `article_search_clause(search: str) -> ColumnElement[bool]` in `cti_core.db.repositories.article`: OR of `Article.title`, `Article.source`, `Article.id.in_(select(a.c.article_id).where(a.c.name <match>))` with `a = mention_rows(ACTOR)`, and the same with `c = mention_rows(CVE)` on `c.c.external_id`; `<match>` = `ilike(f"%{esc}%", escape="\\")` where `esc` escapes `\`, `%`, `_` with a backslash. `ACTOR` / `CVE` imported as `dashboard.py` imports them.
- `_apply_list_filters` replaces `search_or` by `[article_search_clause(search)]`, keeping today's `keyword_or` combination. `daily_entity_counts` replaces `Article.title.ilike(...)` by `article_search_clause(search)`.

- [ ] **Step 1: Write failing tests.** In `test_article_query.py` (seed with the file's existing helpers; mentions through `EntityMention` rows as `tests/integration/test_entities_api.py:93` does): `test_search_matches_actor_mention` (article titled "Hospital outage" with an actor mention `Qilin` → `search="qilin"` returns it); `test_search_matches_cve_mention` (`vulnerability` entity `external_id="CVE-2026-1111"` mentioned → `search="cve-2026-1111"` returns it); `test_search_ignores_dead_actor` (mention on an entity that `live_entity()` excludes, e.g. merged → its name does not match); `test_search_escapes_wildcards` (titles "100% uptime", "100 percent", "a_b", "axb" → `"100%"` returns only the first, `"a_b"` only "a_b"); `test_search_with_title_keyword_needs_both` (keyword matches one article, search another → empty). In `test_newsroom_api.py`: `test_topics_search_matches_actor_mentions_like_articles` (three articles in the window mention `Qilin`, titles without "Qilin" → `GET /api/newsroom/topics?search=qilin` has an `actor` item `Qilin` whose `count` equals `GET /api/articles?search=qilin` `total` under the same `posted_on_start`).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_article_query.py tests/integration/test_newsroom_api.py -q -k "search"`. Expected: FAIL (actor / CVE not matched, wildcard over-matches).
- [ ] **Step 3: Implement** per Interfaces, Indonesian docstring on the helper (why both queries share it, why escaping).
- [ ] **Step 4: Run** Step 2's command, then `uv run pytest tests/integration -q -k "article or newsroom or trending or dashboard"`, mypy, ruff, and `uv run python tools/export_openapi.py && git diff --exit-code docs/openapi.json`. Expected: PASS, no contract diff.
- [ ] **Step 5: Commit** `feat(api): newsroom search also matches actor and CVE mentions and treats wildcards literally`

### Task 2: Web data layer (spec 6.1 period, 6.3-6.5 queries, 6.4 narrowing)

**Files:**
- Create: `apps/web/src/lib/newsroom/period.ts`, `apps/web/src/components/newsroom/newsroom-queries.ts`
- Modify: `apps/web/src/components/newsroom/use-articles.ts`, `apps/web/src/components/newsroom/rubric-queries.ts`

**Interfaces:**
- `period.ts`: `type NewsroomPeriod = "1" | "7" | "30" | "all"`; `NEWSROOM_PERIODS: readonly { key: NewsroomPeriod; label: string; days: number | null; words: string; suffix: string }[]` with the four rows of spec 6.1; `parseNewsroomPeriod(value: string | null): NewsroomPeriod` (anything but "1" | "30" | "all" is "7"); `newsroomPeriodInfo(key)`. Also `type NewsroomUi = { period: NewsroomPeriod; from: string | null; country: string | null; search: string; incidentOnly: boolean; rubric: RubricKey | null }` and `uiToFilters(ui: NewsroomUi): NewsroomFilters` (`dateStart` = `ui.from ?? periodStart(days ?? 0)`, `""` for All; `dateEnd` `""`).
- `use-articles.ts`: `useArticlesQuery` keeps its signature and key; `queryFn` through `unwrap(..., "Failed to load articles")`, `retry: noClientRetry`.
- `rubric-queries.ts`: new pure `rubricArticleQuery(key: RubricKey, filters: NewsroomFilters, ctx: { clientCountries: string[]; watchNames: string[] | undefined; techNames: string[] | undefined }): ArticlesQuery | "no-names" | "victims"` returning only the filter params (`posted_on_start/end`, `search`, `confirmed_only`, `news_type`, `country`, `threat_actor`, `title_keyword`) per spec 6.4; `"no-names"` when the Watchlist / Tech stack names are an empty array; `"victims"` for Ransomware. `useRubric` keeps its parameters, builds its params from it (requests unchanged), and its return gains `updatedAt: number` (the active query's `dataUpdatedAt`, 0 while pending). `RubricItem` gains `article?: Article` and `victim?: RansomwareVictim`; existing fields stay.
- `newsroom-queries.ts` (all `unwrap` + `noClientRetry`; period-driven ones `keepPreviousData`):
  - `type Narrowing = ArticlesQuery | "no-names" | "victims" | "pending"`; `useNarrowing(rubric: RubricKey | null, filters: NewsroomFilters): Narrowing` — `rubric === null` gives the plain filter params; otherwise `rubricArticleQuery` with `useAuth` client countries and `useWatchlistNames(rubric === "watchlist" && can("view_ta"))` / `useTechStackNames(rubric === "techstack" && can("view_cve"))`; `"pending"` while the needed names load.
  - `useFrontArticles(narrowing: Narrowing)`: `GET /api/articles` `page: 1, page_size: 4, sort: "priority"` + params; key `["newsroom","front",params]`; enabled only when `narrowing` is params.
  - `useArticleCount(narrowing: Narrowing)`: same params, `sort: "recent", page_size: 1`; data `total`; key `["newsroom","count",params]`.
  - `useNewestMatch(narrowing: Narrowing, enabled: boolean)`: params without `posted_on_start` / `posted_on_end`, `sort: "recent", page_size: 1`; data `{ article: Article | null }`; key `["newsroom","newest",params]`.
  - `useTopics(filters: NewsroomFilters)`: `GET /api/newsroom/topics` `limit: 6` + the query `topics-strip.tsx` sends today; key `["newsroom","topics",...]`.

- [ ] **Checklist:** `parseNewsroomPeriod` for null, "7", "1", "all", "abc", "0", "ALL" gives 7, 7, 1, all, 7, 7, 7; `uiToFilters` with `from` ignores the period; `rubricArticleQuery("watchlist", f, { clientCountries: [], watchNames: [], techNames: undefined })` is `"no-names"`; the old page's six rubric requests are unchanged (Network panel); a 403 is requested once.
- [ ] **Verify:** lint + tsc exit 0.
- [ ] **Commit** `refactor(web): newsroom period model and queries through unwrap with a shared rubric filter`

### Task 3: Shell: server page, view switch, URL state, header, filter bar, stubs (spec 6.1, 6.2, 6.7 No access)

**Files:**
- Create: `apps/web/src/components/newsroom/newsroom-view.tsx`, `apps/web/src/components/newsroom/filter-bar.tsx`, stubs `front-page.tsx`, `topics-section.tsx`, `rubric-grid.tsx` in `components/newsroom/`
- Modify: `apps/web/src/app/(app)/newsroom/page.tsx` (rewritten)
- Delete: `apps/web/src/app/(app)/newsroom/layout.tsx`

**Interfaces:**
- Consumes: Task 2 (`NewsroomUi`, `uiToFilters`, `NEWSROOM_PERIODS`, `parseNewsroomPeriod`, `newsroomPeriodInfo`, `useNarrowing`, `useArticleCount`, `Narrowing`), 5a (`useArticleOpener`, `useDashboardStats`, `normalizeCountry`, `countryName`); `validFrom`, `paramValues`, `linkedSheet`, `RUBRIC_TITLES`, `sheetTitle` move from the old `page.tsx` into `newsroom-view.tsx` unchanged (sheet titles translated in Task 7 only if they live in the sheet; the ones moved here get the English titles of spec 6.6 now).
- `page.tsx`: server component, `metadata = { title: "Newsroom" }`, `<Suspense><NewsroomView /></Suspense>`.
- `NewsroomView()`: gate per spec 6.1; `view` from `?view`; `ui: NewsroomUi` = URL part `{ period: parseNewsroomPeriod(sp.get("period")), from: validFrom(sp.get("from")), country: normalized sp.get("country") ?? null }` + state (`search` debounced 300 ms from a `searchText` state, `incidentOnly`, `rubric`); `onChange(patch: Partial<NewsroomUi>)` writes `period` (and deletes `from`), `from`, `country` through `writeParams` (guard of spec 6.1) and the rest to state. Deep links read once on mount: `?rubric=` → that rubric's sheet (it does not set the rubric select); `linkedSheet` → the combined sheet. Renders `PageHeader` (kicker "NEWSROOM", title, the count line, actions = view `SegmentedControl`), then for `front`: `<FilterBar>`, `<FrontPage>`, `<TopicsSection>`, `<RubricGrid>`; for `filtered`: `<FilteredView />`; plus `ArticleListSheet` (as today) and the opener `host`.
- Stub props (final): `FrontPage({ ui, filters, narrowing, onChange, openArticle, onOpenStory }: { ui: NewsroomUi; filters: NewsroomFilters; narrowing: Narrowing; onChange: (p: Partial<NewsroomUi>) => void; openArticle: (a: Article) => void; onOpenStory: (storyId: number, title: string) => void })`; `TopicsSection({ filters, words, onOpen }: { filters: NewsroomFilters; words: string; onOpen: (source: SheetSource, title: string) => void })`; `RubricGrid({ filters, rubric, openArticle, onSeeAll }: { filters: NewsroomFilters; rubric: RubricKey | null; openArticle: (a: Article) => void; onSeeAll: (key: RubricKey) => void })`. Each stub returns `null`.
- `FilterBar({ ui, searchText, onSearchText, onChange })` per spec 6.2; rubric select items gated by `view_ta` / `view_cve`; the `from` chip.
- Count line per spec 6.2 with `useArticleCount(narrowing)` and `useDashboardStats(days, incidentOnly)` ("from {m} sources" omitted with search, country or `from`; suffix "since {date}" with `from`).

- [ ] **Checklist (controller):** tab title "Newsroom · {PLATFORM_NAME}"; Review Focus 3 and 4; `?period=abc|0|ALL` on 7d, `?period=1&period=30` on 24h, no redirect; each period / country change writes the URL once and re-selecting sends none; `?view=filtered` shows the Filtered tab for a `view_news`-only role; a role without `view_news` sees the no-access panel and no `/api/proxy/api/*` request except auth; no hydration warning.
- [ ] **Verify:** `next typegen` + lint + tsc exit 0.
- [ ] **Commit** `feat(web): newsroom shell with a server title, view switch, URL period and country, and the filter bar`

### Task 4: Front page, Empty and Error states (spec 6.3, 6.4, 6.7)

**Files:** Modify `apps/web/src/components/newsroom/front-page.tsx` (lift kicker / chips logic from the old `front-section.tsx`, which stays on disk until Task 9).

**Interfaces:** Consumes `useFrontArticles`, `useNewestMatch`, `articleWhen` (with the front query's `dataUpdatedAt`), `PriorityChip`, `priorityLines`, `GradeChip codeOnly`, `useArticleMatchers`, `EntityChip`, `Chip`, `StatePanel`, `Notice`, 5a `PanelError`, `newsroomPeriodInfo`, `countryName`, `fmtAgo`, `fmtTime`, `useQueryClient`.
- Lead and secondary exactly per spec 6.3. `narrowing === "victims"` → nothing rendered; `"no-names"` → the column's empty line of spec 6.5 in the front area; `"pending"` → skeleton.
- Empty per spec 6.7 (`useNewestMatch` enabled only when the front query loaded with zero articles); chips call `onChange` (`search: ""`, `country: null`, `rubric: null`, `incidentOnly: false`, `from: null`); the widen button `onChange({ period: next })`.
- Error banner per spec 6.7 when `isError && data`; "Try again" calls `queryClient.refetchQueries({ queryKey: ["newsroom"] })` and `({ queryKey: ["ransomware", "victims"] })`.

- [ ] **Checklist (controller):** lead with and without dek; "+N sources" only when `source_count > 1` and it opens the story sheet; flags; the "why" line order equals `priorityLines`; the title opens `ArticleModal`; chips are siblings of the button; narrowing to each rubric (Ransomware hides the block; Watchlist with no names shows "No watched actors yet." and sends no `/api/articles`, Review Focus 2); empty state for 24h with a country (chips, sentence, age, "Show last 7 days"), for All (no button), with `from` (no button), with no match at any time (Review Focus 5); a refetch failure shows the banner with the server text and time, content stays; light and dark.
- [ ] **Verify:** lint + tsc exit 0.
- [ ] **Commit** `feat(web): newsroom front page with lead, secondary stories, rubric narrowing and the empty and error states`

### Task 5: Active topics (spec 6.5)

**Files:** Modify `apps/web/src/components/newsroom/topics-section.tsx` (replaces `topics-strip.tsx`, deleted in Task 9).

**Interfaces:** Consumes `useTopics`, `BarSeries`, `Chip`, 5a `PanelError`. A click calls `onOpen({ actor: name } | { ttp: ttp_id ?? name }, title)` exactly as `topics-strip.tsx:54-56` does.

- [ ] **Checklist (controller):** six cards at 1440, three per row at 1100, two at 800; "+n today" omitted when the last day is 0; bars `aria-hidden` with the sr-only count; subtitle follows the period ("all time" on All); a click opens the right sheet; empty and error states.
- [ ] **Verify:** lint + tsc exit 0.
- [ ] **Commit** `feat(web): newsroom active topics as six trend cards`

### Task 6: Rubric grid (spec 6.5, 6.4)

**Files:** Modify `apps/web/src/components/newsroom/rubric-grid.tsx` (replaces `rubric.tsx`, deleted in Task 9).

**Interfaces:** Consumes `useRubric(key, filters, 1, rubric ? 9 : 3)` (items with `.article` / `.victim`, `updatedAt`), `articleWhen(item.article, updatedAt, true)`, `GradeChip codeOnly`, `Card`, 5a `PanelError`, `useCan`, `countryName`, `fmtShortDate`, `parseLocalDate`.
- Columns in the order APAC, Global, Local, Ransomware victims, Watchlist, Tech stack; Watchlist / Tech stack only with `view_ta` / `view_cve` (P6); with `rubric` set, only that column, nine items. Copy per spec 6.5.

- [ ] **Checklist (controller):** 3 x 2 at 1440, one column below 1024; totals equal the sheet totals; victim rows link out and show industry · country · date; empty lines for each case (period empty, no watched actors, no tech stack with "Set up tech stack" → `/cve`); a `view_news`-only role sees four columns and sends no `/api/ta/watchlist-names` / `/api/techstack`; a column error shows "Retry".
- [ ] **Verify:** lint + tsc exit 0.
- [ ] **Commit** `feat(web): newsroom rubric grid with grade chips, victim rows and permission-gated columns`

### Task 7: Sheet copy in English (spec 6.6)

**Files:** Modify `apps/web/src/components/newsroom/article-list-sheet.tsx` (copy only).

- [ ] **Change:** every user-visible Indonesian string to English (titles, "Related articles", pager labels, placeholders, empty / error lines, "sources"); no prop, query or layout change. List the before → after pairs in the report.
- [ ] **Verify:** lint + tsc exit 0; `rg -n '"[^"]*(Lihat|Artikel|Korban|Semua|Gagal|Belum|sumber|halaman)' apps/web/src/components/newsroom/article-list-sheet.tsx` empty.
- [ ] **Commit** `fix(web): newsroom list sheet copy in English`

### Task 8: Filtered tab restyle (spec 6.8, D18)

**Files:** Modify `apps/web/src/components/newsroom/filtered-view.tsx`, `apps/web/src/components/newsroom/panel-shell.tsx`.

- [ ] **Change:** `TabPills` → `SegmentedControl aria-label="Filtered articles"`; panel title "Not cyber-related"; hint text in English; every row field kept; buttons only with their permission (Restore, Accept, Reject `manage_sources`; Retry `manage_scraper`); queries through `unwrap` + `noClientRetry`; tokens and focus rings per Global Constraints.
- [ ] **Checklist (controller):** a `view_news`-only role sees both lists without buttons; `manage_sources` shows Restore / Accept / Reject, Retry only with `manage_scraper`; each action still works and refreshes its list; search, count, refresh and pager unchanged.
- [ ] **Verify:** lint + tsc exit 0.
- [ ] **Commit** `feat(web): filtered tab restyle with per-button permissions for every view_news user`

### Task 9: Cleanup and sweep (spec 6.9, Global Constraints)

**Files:** Delete `components/newsroom/masthead.tsx`, `front-section.tsx`, `topics-strip.tsx`, `rubric.tsx` once `rg "masthead|front-section|topics-strip|newsroom/rubric\"|FrontSection|TopicsStrip|Masthead" apps/web/src` shows no importer; fix what the sweep flags in the files of Tasks 2-8.

- [ ] **Sweep** (`N` = `apps/web/src/components/newsroom apps/web/src/lib/newsroom "apps/web/src/app/(app)/newsroom"`): `rg -n "if \(error\) throw" $N` none; every `useQuery` has `retry: noClientRetry`; `rg -n "refetchInterval|usePageTitle|asChild|backdrop-blur|font-mono" $N` none; `rg -n "Date\.now\(\)|new Date\(" $N` only inside a `queryFn`, `periodStart` / `validFrom` or event handlers; `rg -n "router\.(replace|push)" $N` only the guarded `writeParams`; the Indonesian-copy grep of Global Constraints shows comments only; every `table-fixed` has a `<colgroup>`.
- [ ] **Feature walk draft:** write `.superpowers/brainstorm/pr-checklist-5b.md` (gitignored, not committed): NR1-NR28 with their new home (spec 6.9), P1-P7, and the 5c carry-overs.
- [ ] **Verify:** lint + tsc exit 0.
- [ ] **Commit** `refactor(web): remove the old newsroom masthead, front section, topics strip and rubric`

### Task 10: CHANGELOG and runbooks (spec 5)

**Files:** Modify `CHANGELOG.md` (extend `## [0.8.16] - 2026-11-08`, Indonesian), `docs/prod-upgrade/0.8.16.md`, `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` (0.8.16 section); not `docs/PROGRESS.md`.

- [ ] **Change:** the three items of spec 5 in Indonesian under `### Diubah`; one behaviour-change line in each runbook (English), nothing else.
- [ ] **Verify:** `uv run python -c "from cti_api.routers.changelog import _parse; print(_parse()[0]['version'])"` prints `0.8.16`; `git diff --stat` lists only the three files.
- [ ] **Commit** `docs(release): note the Newsroom redesign and the wider search in 0.8.16`

### Task 11: Final verification (spec 8)

- [ ] **Backend:** `uv run pytest tests/integration -q`, the fast suite, ruff, mypy; `export_openapi` + `gen:api` give no diff; `uv run alembic heads` prints `d9f2b6a4c1e7 (head)` only.
- [ ] **Web:** stop the dev server; lint, `next typegen && tsc --noEmit`, `pnpm build` exit 0.
- [ ] **Browser (controller, `qafig` with seed5a plus articles whose only match for "Qilin" or a CVE id is a mention):** every line of spec 8 "Browser", Review Focus 1-5 end to end, both themes, 1440 and 1000 px.
- [ ] **Delivery:** merge into `origin/Dev` under the standing approval; update the handover note and memory.
