# FigCraft redesign 5c: Newsroom All articles and reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Newsroom "All articles" view (rail, list, reader pane per frame 2194) with the B-N3 grade filter and the B-N5 article IOC endpoint, route every Newsroom, Dashboard and Intelligence path into it, and delete the list sheet, inside release 0.8.16.

**Architecture:** Backend first (grade filter, IOC endpoint, one contract regeneration). On the web: a URL-state + query layer for All articles, a shell that adds the third view and mounts the rail, list, reader and two reader sub-blocks as stubs with final props, then those five pieces in parallel, the link rewiring (Front page, Dashboard, `newsroomHref`, sheet deletion), a sweep and docs. `ArticleModal` is not modified.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, pytest + testcontainers; Next.js 16 App Router, React 19, TanStack Query (`useInfiniteQuery`, `keepPreviousData`), Tailwind v4, shadcn on Base UI, `openapi-fetch`.

**Spec:** `docs/superpowers/specs/2026-11-15-figcraft-redesign-5c-all-articles-design.md` (binding, including 6.10 rules 1-12; section numbers below refer to it). Fixed copy is in the spec and is not repeated here. 5b's spec and code are the base (`components/newsroom/*`, `lib/newsroom/*`).

**Parallel map.** Task 1 → Task 2 → Task 3 (shared backend files, one contract). Task 12 (docs) any time. Task 4 after Task 3. Task 5 after Task 4. Tasks 6, 7, 8, 9 and 10 after Task 5, side by side (disjoint files). Task 11 after 6-10. Task 13 last.

## Global Constraints

- No migration, no `Settings` key. One contract regeneration, in Task 3 only. Release stays 0.8.16, no version bump.
- Not modified: `components/newsroom/article-modal.tsx` (user decision), `components/entities/entity-stories-tab.tsx`, `components/intelligence/campaign-clusters/article-by-id-dialog.tsx`, `components/hunt/hunt-panel.tsx`, `components/newsroom/d3fend-toggle.tsx`, `components/newsroom/inferred-ttps-section.tsx`, `components/newsroom/credibility-override.tsx` (reused as they are).
- Backend: comments and docstrings Indonesian, why-focused; additive changes; new route under the articles router's `view_news` dependency (`tests/unit/test_route_permissions.py` is updated only if it enumerates routes and fails).
- Commits English conventional with the implementer's own model trailer; stage only your own files (`git diff --cached --stat` before committing); never push, merge or switch branches.
- Python checks: ruff check + format, mypy on cti-core and cti-scraper, fast suite with the known deselect; integration via testcontainers (never touch `deploy-postgres-1`).
- Web: read `apps/web/AGENTS.md` and `apps/web/CLAUDE.md`. All 5a/5b web rules hold (theme tokens, `text-X-text`, `text-2xs` floor, `font-code` for ids and counts, " · ", focus-ring tokens, Base UI `render` / single-string `SelectItem` / `items`, no `backdrop-blur`, no clock reads in render, `parseLocalDate`, `toLocaleString("en-US")`, `unwrap` + `noClientRetry` on every query, no `refetchInterval`, skeleton `aria-hidden`, stale dims on `isPlaceholderData`, error panels only without data with the server message via 5a `PanelError`, one h1, h2 per section, h3 per card, no nested interactive elements, gate on the real permission).
- Permissions (spec 6.8): `view_intel` ransomware; `view_ta` watchlist names; `view_cve` tech stack; `manage_pir` Watch; `manage_intel` Override; `view_stix` Export STIX. No request without its permission.
- URL writes only through 5b's guarded `writeParams` in `newsroom-view.tsx` (never replace to the current URL, no effect writes the URL). Links that carry a count to match add `sort=recent` (6.10 rule 4).
- Web verification: `pnpm lint`, `pnpm exec tsc --noEmit`; implementers never run `pnpm build`, `next typegen` (except Task 5) or `pnpm dev` (shared `.next`); browser checklists are run by the controller; implementers explain each line by construction (file:line).
- No subagent re-delegation. Do not push.

## Review Focus

1. **Count parity on Intelligence links.** A `newsroomHref({ actor, ttp, from })` link must show "{n} articles match" equal to `/api/articles` `total` with the same parameters and `sort=recent` (Task 4 `allStateToQuery` mapping; Task 10 checklist).
2. **Selected article outside the list.** `?article=<id>` for an article filtered out, or a deleted id, must still open the reader (fetch by id) or say "This article is not available.", and "{i} of {n}" hides (Task 8 checklist).
3. **Watchlist ∩ actor chip empty.** `rubric=watchlist&actor=X` where X is not watched must send no `/api/articles` request and show the empty state (Task 4 returns `"empty"`; Task 7 checklist).
4. **Defanging odd values.** URLs with a scheme, a port or a path, IPv6 and emails must defang readably (`hxxps://evil[.]com/x.php`, `1[.]2[.]3[.]4`) while copy returns the original string (Task 9 `defang` self-check).
5. **Filter change while paged.** Changing any filter after "Load more" must reset to page 1 (the infinite query is keyed by the filter params), never append rows of the old filter (Task 7 checklist).

---

### Task 1: B-N3 `reliability_grade` filter (spec 4.1)

**Files:** Modify `packages/cti-core/src/cti_core/db/repositories/article.py` (`_apply_list_filters` + the list method that passes filters), `apps/api/src/cti_api/routers/articles.py` (list route); Test `tests/integration/test_articles_combined_filters.py`.

**Interfaces:** Produces `GET /api/articles?reliability_grade=A&reliability_grade=B` (`list[Literal["A","B","C","D","E","F"]] | None = Query(None)`) → `Article.reliability_grade.in_(...)`; NULL grades excluded when set; `list_filtered` untouched.

- [ ] **Step 1: Failing tests:** `test_reliability_grade_single`, `test_reliability_grade_multiple`, `test_reliability_grade_with_country_and_priority_sort` (story dedup still one row per story), `test_reliability_grade_excludes_null`, `test_reliability_grade_invalid_letter_422`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_articles_combined_filters.py -q -k reliability` → FAIL.
- [ ] **Step 3: Implement** per Interfaces (Indonesian comment: NULL excluded because "graded A" cannot include ungraded).
- [ ] **Step 4: Run** Step 2 + `uv run pytest tests/integration -q -k "article"` + mypy + ruff → PASS. Do not regenerate the contract.
- [ ] **Step 5: Commit** `feat(api): reliability grade filter on the article list`

### Task 2: B-N5 article IOC endpoint (spec 4.2)

**Files:** Modify `packages/cti-core/src/cti_core/db/repositories/indicator.py` (new method), `apps/api/src/cti_api/schemas/article.py` (two schemas), `apps/api/src/cti_api/routers/articles.py` (route), maybe a small service in `apps/api/src/cti_api/services/` for the reputation rule; Create `tests/integration/test_article_iocs_api.py`.

**Interfaces:** Produces `AsyncIndicatorRepo.list_for_article(article_id: int, *, limit: int = 200) -> tuple[list[tuple[Indicator, str | None]], int]`; `ArticleIocOut { type: str, value: str, context: str | None, reputation: str | None }`; `ArticleIocsOut { items: list[ArticleIocOut], total: int }`; `GET /api/articles/{article_id}/iocs` → `ArticleIocsOut`, 404 for an unknown article. Reputation: worst verdict across `Indicator.enrichment` provider cards (`malicious` > `suspicious` > `clean`; `unknown` ignored) as "{verdict} ({card name})"; `None` otherwise (`reputation_label(enrichment: Mapping[str, Any]) -> str | None`, pure, with a unit test in `tests/unit/test_ioc_reputation_label.py`).

- [ ] **Step 1: Failing tests:** integration `test_article_iocs_two_sources_first_context`, `test_article_iocs_excludes_unusable`, `test_article_iocs_reputation_from_card`, `test_article_iocs_total_and_cap` (205 indicators → 200 items, total 205), `test_article_iocs_unknown_article_404`, `test_article_iocs_requires_auth` (401) and `test_article_iocs_requires_view_news` (403); unit `test_reputation_label_worst_verdict`, `test_reputation_label_none_when_unknown_or_empty`. Read the stored card shape in `apps/api/src/cti_api/services/ioc_providers.py` / `ioc_enrichment.py` and seed `enrichment` the way the enrichment job writes it.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_article_iocs_api.py tests/unit/test_ioc_reputation_label.py -q` → FAIL.
- [ ] **Step 3: Implement** per Interfaces (ordered by type, value; `list_by_article_ids` unchanged).
- [ ] **Step 4: Run** Step 2 + `uv run pytest tests/integration -q -k "article or indicator or ioc"` + mypy + ruff → PASS.
- [ ] **Step 5: Commit** `feat(api): article IOC endpoint with context and reputation`

### Task 3: Contract regeneration (spec 4.3)

- [ ] Run `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`; `git diff docs/openapi.json` shows only the `reliability_grade` parameter, the new route and the two schemas (anything else: stop and report); `pnpm exec next typegen && pnpm exec tsc --noEmit` exit 0.
- [ ] Commit `chore(api): regenerate the contract for the grade filter and article IOCs`

### Task 4: All-articles URL state and query layer (spec 6.1, 6.2 counts, 6.3 query, 6.4 data, 6.10 rules 1-7, 12)

**Files:** Create `apps/web/src/lib/newsroom/all-state.ts`, `apps/web/src/components/newsroom/all-articles-queries.ts`.

**Interfaces:**
- `type AllState = { period: NewsroomPeriod; from: string | null; countries: string[]; sector: string | null; sources: string[]; grades: Grade[]; rubric: RubricKey | null; actors: string[]; ttps: string[]; story: number | null; sort: "priority" | "recent"; q: string; incidents: boolean; article: number | null; group: string | null; vindustry: string | null }`, `type Grade = "A"|"B"|"C"|"D"|"E"|"F"`.
- `parseAllState(sp: URLSearchParams): AllState` (`country`/`source`/`grade`/`actor`/`ttp` repeatable; `sector` wins over `industry` (rule 12); invalid grade letters and ids dropped; `story` forces `sort: "recent"` (rule 5); `period` via `parseNewsroomPeriod`; `from` via the existing `validFrom`; `group` / `vindustry` are the ransomware Group / Industry selects).
- `allStateToParams(patch: Partial<AllState>, current: URLSearchParams): URLSearchParams` (writes the URL form; omits defaults: 7d, priority, empty lists, false).
- `isAllViewUrl(sp: URLSearchParams): boolean` (spec 6.1 derived view: `view=all`, or no `view` and any of `article`, `rubric`, `actor`, `industry`, `ttp`, `story`).
- `allStateToQuery(s: AllState, ctx: { clientCountries: string[]; watchNames: string[] | undefined; techNames: string[] | undefined }): ArticlesQuery | "empty" | "no-names" | "pending" | "victims"` — base filters (`posted_on_start` from period/from via `periodStart`, `country`, `industry: [sector]`, `source`, `reliability_grade`, `threat_actor` = actors, `ttp`, `story_id`, `search` = q, `confirmed_only` = incidents, `sort`) + the rubric via `rubricArticleQuery` (rule 1: Watchlist ∩ actors case-insensitive, `"empty"` when the intersection is empty; `"no-names"` when the names list is empty; `"pending"` while loading).
- `newsroomAllHref(patch: Partial<AllState> & { keepFrom?: URLSearchParams }): string` — `/newsroom?view=all&...` for callers outside the view (Dashboard, Front page).
- Queries (all `unwrap` + `noClientRetry`): `useAllArticles(query)` — `useInfiniteQuery`, `page_size: 20`, key `["newsroom","all",query]`, `getNextPageParam` from `total`; `useRubricCounts(state)` → `Record<"all" | RubricKey, number | null | undefined>` (one `page_size=1` query per visible rubric with the state minus the rubric; Ransomware via victims total with period + first country; respects `view_intel` / `view_ta` / `view_cve`; `undefined` while loading, `null` on error); `useArticleById(id, enabled)`; `useArticleIocs(id)` → `ArticleIocsOut`; `useStorySources(storyId, excludeId)` → distinct source names (query `story_id`, `sort: "recent"`, `page_size: 50`); `useVictimRows(state, enabled)` and `useRelatedArticles(state, enabled)` (the requests the sheet makes today, with rule 7's filters).
- [ ] **Checklist:** `parseAllState` round-trips through `allStateToParams` for a state with every field set; `?industry=Energy&sector=Finance` reads `sector: "Finance"`; `?story=5` reads `sort: "recent"`; `allStateToQuery` for `rubric: "watchlist", actors: ["X"]` with watch names `["Qilin"]` is `"empty"` (Review Focus 3); a `newsroomHref({actor: "Qilin", ttp: "T1486", from: "2026-11-03"})` URL parses to a query whose params equal what the old combined sheet sent plus `sort: "recent"` (Review Focus 1). Check pure functions with a throwaway snippet, not committed.
- [ ] **Verify:** lint + tsc. **Commit** `feat(web): all-articles URL state and queries`

### Task 5: Shell: third view, layout, stubs (spec 6.1, 6.7)

**Files:** Modify `apps/web/src/components/newsroom/newsroom-view.tsx`; Create `components/newsroom/all-articles-view.tsx` and stubs `all-rail.tsx`, `all-list.tsx`, `article-reader.tsx`, `reader-iocs.tsx`, `reader-more.tsx`.

**Interfaces:**
- View switch "Front page | All articles | Filtered"; view = `?view` or `isAllViewUrl` (no redirect, no URL rewrite).
- `AllArticlesView({ state, onChange }: { state: AllState; onChange: (patch: Partial<AllState>) => void })`: three-column layout per spec 6.7 (≥1280 rail 236 / list ≥360 / reader ≥520; 1024-1279 rail in a "Filters" `Disclosure`; <1024 one column, reader below the list), the removable link chips above the list (actor, technique, story with its lead title from the first list row or "Story {id}"), and the stubs.
- `NewsroomView` builds `state = parseAllState(searchParams)` and `onChange` writes through `writeParams(allStateToParams(patch, current))`.
- Stub props (final): `AllRail({ state, onChange })`; `AllList({ state, onChange, selected, onSelect })` where `onSelect: (id: number) => void`; `ArticleReader({ articleId, listArticles, onStep })` where `listArticles: Article[]` is the loaded list and `onStep: (id: number) => void`; `ReaderIocs({ articleId })`; `ReaderMore({ article }: { article: Article })`.
- [ ] **Checklist (controller):** `/newsroom?view=all` shows three columns at 1440, a Filters disclosure at 1100, one column at 1000; old `?rubric=ransomware` and `?actor=X` links land on All articles without a redirect; the Front page and Filtered views unchanged; tab title "Newsroom · {PLATFORM_NAME}".
- [ ] **Verify:** `next typegen` + lint + tsc. **Commit** `feat(web): newsroom all-articles view shell`

### Task 6: Rail (spec 6.2, 6.10 rules 2, 3, 7)

**Files:** Modify `components/newsroom/all-rail.tsx`.
**Interfaces:** Consumes `useRubricCounts`, `useDashboardStats`, `useFilterOptions` (from `lib/newsroom/filters.ts`), `CountryMultiSelect` (`components/country-multi-select.tsx`; if it breaks the Base UI rules, build the multi-select from `Select` + chips), grade text from `score-reasons.ts`. Sections and copy per spec 6.2; "Incidents only" checkbox under PERIOD (rule 6); ransomware: Group / Industry selects and the disabled filters with "Not used for victims" (rule 7); "Reset filters".
- [ ] **Checklist (controller):** each rubric row's count equals the list total after selecting it; A-F toggles narrow the list and set `aria-pressed`; a `?source=` outside the top 10 is listed first, checked, without a count; Ransomware row only with `view_intel`, Watchlist with `view_ta`, Tech stack with `view_cve`; reset clears every filter except view and article.
- [ ] **Verify:** lint + tsc. **Commit** `feat(web): all-articles filter rail`

### Task 7: List (spec 6.3, 6.10 rules 1, 2, 4, 7, 10)

**Files:** Modify `components/newsroom/all-list.tsx`.
**Interfaces:** Consumes `useAllArticles`, `allStateToQuery`, `useNarrowing`-style names hooks (`useWatchlistNames`, `useTechStackNames` gated), `useVictimRows`, `useRelatedArticles`, `SelectableList` (its roving keys give ↑ / ↓; values are article ids as strings), `LoadMoreFooter`, `PriorityChip`, `GradeChip codeOnly`, `useArticleMatchers`, `articleWhen` (with the query's `dataUpdatedAt`).
- Header wording by sort (rule 4); rows, load more, empty, error per spec 6.3; `"empty"` / `"no-names"` states without a request; ransomware victim rows + "Related articles" section.
- [ ] **Checklist (controller):** Review Focus 3 and 5; priority vs recent header wording; load more appends 20; ↑ / ↓ moves the selection and the URL; victim rows link out, related articles open the reader.
- [ ] **Verify:** lint + tsc. **Commit** `feat(web): all-articles list with load more and victim rows`

### Task 8: Reader (spec 6.4 blocks 1-7, 6.10 rules 5, 11)

**Files:** Modify `components/newsroom/article-reader.tsx`.
**Interfaces:** Consumes `useArticleById` (when the id is not in `listArticles`), `useStorySources`, `useWatchlistNames` (gated by `view_ta`), `PUT /api/entities/{id}/watch` via `api` (mutation, `manage_pir`), `lib/newsletter/queue.ts`, `gradeLines` / `describePriority` / `priorityLines` (`score-reasons.ts`), `CredibilityOverride`, `PriorityChip`, `EntityChip`, `Chip`, `fmtDateTime`; mounts `<ReaderIocs articleId>` and `<ReaderMore article>` after block 7.
- [ ] **Checklist (controller):** Review Focus 2; every block on a full and a sparse article; Watch only with `manage_pir`, "Watching ✓" after success; "+ Newsletter" queues; Override only with `manage_intel`; "also reported by" lists other story sources; "{i} of {n} ‹ ›" steps through loaded rows; no-selection empty state.
- [ ] **Verify:** lint + tsc. **Commit** `feat(web): newsroom reader pane`

### Task 9: Reader IOCs and More (spec 6.4 blocks 8-9)

**Files:** Modify `components/newsroom/reader-iocs.tsx`, `components/newsroom/reader-more.tsx`; Create `apps/web/src/lib/newsroom/defang.ts`.
**Interfaces:** `defang(value: string): string` — `http`/`https`/`ftp` schemes → `hxxp`/`hxxps`/`fxp`, every `.` in the host and IPv4 → `[.]`, `@` → `[@]`, `:` before a port → `[:]`, path kept, IPv6 left as is (no dots). No web test runner exists: verify with a throwaway snippet outside the repo on `https://evil.com/x.php`, `http://1.2.3.4:8080/a`, `1.2.3.4`, `user@mail.evil.com`, `2001:db8::1`, `evil.com` and paste the outputs in the report (Review Focus 4). `ReaderIocs` consumes `useArticleIocs`, `proxyFetch` for STIX (`/api/stix/article/{id}`, `view_stix`), the CSV shape of `article-modal.tsx`'s export (copy the column order, do not import from the modal). `ReaderMore` = `Disclosure` "More" mounting `HuntPanel` (story), `D3fendToggle` per technique, `InferredTtpsSection`, and the inherited-classification note, all after first open.
- [ ] **Checklist (controller):** defanged display, copy and Copy all give originals; STIX only with `view_stix`; "Showing the first 200." when capped; More sends no hunt / d3fend / inferred request before it is opened.
- [ ] **Verify:** lint + tsc. **Commit** `feat(web): reader indicators and more sections`

### Task 10: Rewire links, delete the sheet (spec 6.5, 6.10 rules 4, 6, 8)

**Files:** Modify `components/newsroom/newsroom-view.tsx` (Front page callbacks → `newsroomAllHref`; remove the sheet and `useArticleOpener`), `components/dashboard/dashboard-view.tsx` (navigation helper instead of `useArticleOpener`; `90` → `from`), `components/dashboard/needs-action.tsx` (hero hrefs add `view=all&sort=recent`), `lib/newsroom/links.ts` (`newsroomHref` adds `view=all` and `sort=recent`; parameters unchanged); Delete `components/newsroom/article-list-sheet.tsx`, `components/dashboard/article-opener.tsx`.
**Interfaces:** Front page article click → `newsroomAllHref({ article, period/from, country, q, incidents })`; "See all" → `{ rubric, sort: "recent" }` + period/country; "+N sources" → `{ story }`; topic → `{ actors: [name] }` or `{ ttps: [id] }` with `sort: "recent"`.
- [ ] **Checklist (controller):** Review Focus 1 on an Early Warning and a MITRE link; Dashboard lead / Must read click lands on the reader with the period; hero links land filtered; `rg -n "ArticleListSheet|article-list-sheet|useArticleOpener" apps/web/src` empty; entity Stories tab and campaign clusters still open `ArticleModal`.
- [ ] **Verify:** lint + tsc. **Commit** `feat(web): newsroom and dashboard links open all articles; list sheet removed`

### Task 11: Sweep (Global Constraints)

- [ ] Run the 5b sweep greps over `components/newsroom`, `lib/newsroom`, `app/(app)/newsroom`, `components/dashboard` (no `if (error) throw`, every `useQuery` / `useInfiniteQuery` with `noClientRetry`, no `refetchInterval`/`usePageTitle`/`asChild`/`backdrop-blur`, clock reads only in query functions or helpers, `router.replace|push` only in the guarded writer or the navigation helper, no Indonesian UI copy); fix findings in Tasks 4-10 files; write `.superpowers/brainstorm/pr-checklist-5c.md` (gitignored): the 6.9 rows, rules 1-12, the "two article views" note. Verify lint + tsc. Commit `refactor(web): all-articles sweep`.

### Task 12: Docs (spec 5)

- [ ] Extend `CHANGELOG.md` 0.8.16 (Indonesian) and both 0.8.16 runbooks (English) per spec 5; changelog parser prints `0.8.16`; only those three files. Commit `docs(release): note the all-articles view, grade filter and article IOCs in 0.8.16`.

### Task 13: Final verification (spec 8)

- [ ] Backend: full integration suite, fast suite, ruff, mypy, single alembic head, contract has no drift.
- [ ] Web: stop the dev server; lint, typegen + tsc, build.
- [ ] Browser (controller, `qafig` + seed5a + indicators with source rows on two articles): every line of spec 8, Review Focus 1-5, light and dark, 1440 / 1100 / 1000 px, roles (superadmin-like qa, news-only, no-news).
- [ ] Merge into `origin/Dev` under the standing approval; update the handover note and memory.
