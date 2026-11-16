# FigCraft redesign 5a: Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the full v5 Dashboard mockup on `/dashboard` (period switch in the URL, "Needs action" hero with the APAC signal map, lead story with "Why it ranks first", "By the numbers", Must read, Trending for actor / malware / CVE, four fixed 30-day charts, CVE watchlist, a "More" disclosure, per-panel states) with every pre-redesign feature DB1-DB20 still reachable, plus the six backend items it needs (B-D1 to B-D4, B-N1 `articles.summary`, B-N2 `first_seen_at`), inside the 0.8.16 release.

**Architecture:** Backend first, each item its own pytest cycle: Tasks 1-4 are the four dashboard endpoints (one file chain, in order), Tasks 5-7 are the summary column (model + migration in one commit, the pure `make_dek`, then the pipeline change), Task 8 puts both new fields on `ArticleOut`, Task 9 regenerates the contract once. Then shared web pieces (10-12), a shell (13) that replaces the page with `DashboardView` mounting eight section components as stubs with their final props, so Tasks 14-22 each fill one file and can run side by side, then the LLM banner and cleanup (23), a states and permissions sweep (24), docs (25) and the final verification (26). Between Task 13 and Task 23 the page is partly empty on the branch; the old components stay on disk (unmounted) as the source to lift from and are deleted in Task 23.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async + sync), Alembic, pytest + testcontainers + syrupy; Next.js 16 App Router, React 19 (`useSyncExternalStore`), TanStack Query (`keepPreviousData`), Tailwind v4, shadcn on Base UI, `openapi-fetch` (`api` from `@/lib/api/client`), `d3-geo` (`WorldDots`), chart.js (only inside "More").

**Spec:** `docs/superpowers/specs/2026-11-14-figcraft-redesign-5a-dashboard-design.md` (binding, including P1-P21; section numbers below refer to it, `C` / `D` / `P` / `DB` ids are its conflicts, decisions, flagged choices and feature map). All fixed UI copy, the hero row table, the "Why it ranks first" label table, the chart card table, the table column widths and the panel-error titles are in the spec (6.1-6.7); tasks cite them and do not repeat them. Where the inventory (`.superpowers/brainstorm/sp5-inventory.md`) differs, the spec wins.

**Parallel map (the controller's schedule).** Chain A: 1 → 2 → 3 → 4 (shared files). Chain B: 5 → 7, with 6 free (disjoint from 1-5). A and B run side by side. Then 8, then 9. Then 10 ∥ 11 ∥ 12. Then 13. Then 14 → 15 (same file) ∥ 16 ∥ 17 ∥ 18 ∥ 19 ∥ 20 ∥ 21 ∥ 22. Then 23, 24, 26 in order. 25 (docs) is disjoint from everything after Task 9. Every task lists its files; two tasks that name the same file never run together.

## Global Constraints

- One migration, no new `Settings` field: `d9f2b6a4c1e7` on top of `c4e8a1f2b9d6`; `.env.example` and `.env.prod.template` unchanged; `uv run --no-sync alembic heads` prints one line. If another revision lands on the branch first, `down_revision` is that head. Release stays 0.8.16 (`## [0.8.16] - 2026-11-08`), one PR, no version bump.
- Backend scope: additive only. Routes stay in `apps/api/src/cti_api/routers/articles.py` under the router dependency `view_news`; no new route (`tests/unit/test_route_permissions.py` untouched). `brief`, `window_label` and `incident_only` stay in the API. `get_attention` and `routers/newsroom.py` keep calling `get_trending` without `kinds`. `persist_rejected`, `ArticleRepo.upsert`, `ArticleModal`, Newsroom pages and the Session-expired dialog are not modified. Comments and docstrings Indonesian, explaining *why*, matching the file. Docs under `docs/` English; `CHANGELOG.md` Indonesian; `docs/PROGRESS.md` is not touched.
- Contract: regenerated once, in Task 9, never inside Tasks 1-8. Snapshots: `--snapshot-update` only for the files Task 8 names, and every `.ambr` diff is read before committing.
- Commits: English conventional; the body ends with a blank line + the implementer's own model trailer (`Co-Authored-By: <the model that wrote the commit> <noreply@anthropic.com>`; the session's attribution reminder is authoritative, not a copy of an older trailer). Stage only your own files (`git add <paths>`, never `-A`). Never push, merge or switch branches (`claude/figcraft-design-data`).
- Python checks: `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src packages/cti-scraper/src` (covers the new repository methods and the model column). Fast suite: `uv run pytest tests/unit tests/contract packages --deselect tests/contract/test_golden.py::test_golden_trendmicro` (also deselect the two known Mac-only failures). Integration needs Docker (testcontainers; never touch `deploy-postgres-1`). New async tests are `async def` on `api_client` / `api_session` / `auth_header` / `async_db_session`; `tests/integration/conftest.py:366-372` already clears the `trending` and `dashboard_overview` caches per test. An ellipsis in Python source is built with `chr(0x2026)`, never typed or written as an escape (ruff RUF001).
- Seed and fixture shapes match the API's `Literal` types exactly: trend `kind` `actor | ttp | malware | cve`, breaker `closed | open | half_open`, `llm_ttp_status` `pending | done | skipped | failed`. Any other value is a bug in the seed, not a case to render. TypeScript unions come from `components["schemas"]` (`ArticleOut`, `DashboardAttention`, `DashboardMap`, `TrendingResponse`, `TrendItemOut`, `RansomwareOverview`, `CveExposure`, `DashboardStats`), never hand-written strings.
- Web (`apps/web`): read `apps/web/AGENTS.md` and `apps/web/CLAUDE.md` first. Desktop 1440 first (content 1328). Two-column rows `lg:grid-cols-[minmax(0,820fr)_minmax(0,468fr)]`, one column below 1024 px; chart cards `sm:grid-cols-2 xl:grid-cols-4`. Base UI, not Radix (`render={<X/>}`, never `asChild`; `SelectItem` children a single string, `items` on every `Select`; 5a adds no `Select`). Theme tokens only; text on tints `text-X-text`; inside the hero only hero tokens (`text-hero-foreground`, `text-hero-muted`, `bg-hero-panel`, `heroLinkClass`) and no `Chip`; no `backdrop-blur`; minimum text 11 px (`text-2xs`); CVE ids, technique ids, ticket ids and counts in `font-code` (`font-mono` is not monospace here); the mockup's wide separators are " · "; focus ring `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background`. Dates and times browser zone through `lib/format.ts`; the `id-ID` formatters disappear. UI copy English (D2); numbers through `toLocaleString("en-US")`.
- Lessons from sub-projects 1-4c (each is a review item): (a) a nested layout with a string `metadata.title` resets the root template: `app/(app)/dashboard/layout.tsx` is deleted and the title is static `metadata` on the server `page.tsx`; a static title is never `usePageTitle` (the h1 is a date, the tab title is not data-driven); (b) check `response.ok`, never only `if (error)` (an empty-body 502 passes the latter): every query goes through `unwrap` from `lib/scrapers/queries.ts`; (c) never retry a 4xx: every query uses `retry: noClientRetry`; (d) no interactive element nested in another: hero rows are one `Link` with text only, article titles are `<button>`s with chips beside them, table rows have no `onClick`; (e) `table-fixed` always with explicit column widths; (f) gate on the real backend permission via `useCan()`, never a stricter or looser one: the table in spec 6.8 is the only source; (g) legend and bar colours equal the data colours: map legend `bg-hero-accent` / `bg-hero-eyebrow`, industries swatches `SHARE_BAR_SEGMENT[i]`, highlighted bars `destructive`; (h) a closed `Disclosure` is hidden in print unless `printOpen` is set: "More" sets it; (i) never call `Date.now()` or `new Date()` in render: "now" is read inside the `queryFn` and returned with the data (`fetchedAt`), the period start for `/api/articles` is computed in the `queryFn`, today's h1 comes from `useSyncExternalStore` with the server snapshot `"Dashboard"`; (j) never `router.replace` or `router.push` to an unchanged URL and never rewrite a URL as a pure normalisation: the period handler returns when the next URL equals the current one, and no effect writes the URL; (k) every pre-redesign feature stays reachable, with a checklist DB1-DB20 in the PR (Task 24); (l) no polling: no Dashboard query sets `refetchInterval`; one added later must be `(q) => isClientError(q.state.error) ? false : N`; (m) every task's runtime checklist is the controller's job: implementers explain each item by construction (which line makes it true) and must not run `pnpm build` while a dev server on :3010 runs (both write `.next`); (n) raw proxy calls (downloads, streams) go through `proxyFetch`, never a bare `fetch("/api/proxy/…")` (5a makes none); (o) show the server's message, not a generic permission sentence: error panels and the page gate print `error.message` (the API `detail`), with a fixed fallback only when the response has none; (p) a dialog cannot be dismissed mid-save (5a adds no dialog; `ArticleModal` is unchanged); (q) password and secret values never leave component state (5a handles none; nothing from `/api/data-health` is logged or stored); (r) when two tasks touch the same file, they run one after the other (see the parallel map).
- Web verification per task, from `apps/web` after `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"`: `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit` (typegen first); `pnpm build`; all exit 0. **When web tasks run in parallel** they share one `.next`: the controller runs `next typegen` once before dispatch, each implementer runs only `pnpm lint` and `pnpm exec tsc --noEmit`, and the controller runs `pnpm build` once after the batch, before the next task starts. The controller then runs each task's checklist in `pnpm dev --port 3010` against the local `qafig` stack (`.superpowers/qa/README.md`). No web test runner exists; do not add one.
- No subagent re-delegation inside a task. Do not push.

## Review Focus

1. **An excerpt with nothing to cut at.** When the summarizer fails it returns the whole article, which can be one unbroken token or text with a single early space: the stored value must still be at most 601 characters and never empty by accident (Task 6, `test_make_dek_long_text_without_spaces`).
2. **The second `persist` call site.** "Security Technology & Best Practices" articles take a separate branch in `pipeline.complete`; a summary passed only on the main branch leaves a whole news type without a dek and no test notices (Task 7, `test_pipeline_stores_summary_on_best_practice_branch`).
3. **A repeated `kinds` value.** `?kinds=cve&kinds=cve` must return the same counts as `?kinds=cve`; a loop over the raw list adds every bucket twice (Task 4, `test_trending_repeated_kind_counts_once`).
4. **Calendar dates east of UTC.** `generated_at` and `timeline[].date` are date strings; `new Date("2026-11-14")` is the previous day's evening west of UTC and misplaces labels. The 30 bars, their labels and `posted_on` go through `parseLocalDate`, and the last bar is the date part of `generated_at` in every browser zone (Task 20 checklist, "Dates" line; Task 24 grep).
5. **A hand-edited period URL.** `?period=7`, `?period=0`, `?period=ALL`, `?period=1&period=30` and `?period=30&x=1` all load without a redirect or a navigation loop, unknown values read as 7d, other parameters survive a period change, and re-selecting the current option sends no navigation (Task 13 checklist, "Period URL" line).

---

### Task 1: B-D1 `cve-exposure` takes a row limit (4.1, D7, C12)

**Files:**
- Modify: `apps/api/src/cti_api/routers/articles.py:366-376` (`dashboard_cve_exposure`), `apps/api/src/cti_api/services/dashboard_overview.py:291-296` (`get_cve_exposure`)
- Test: `tests/integration/test_dashboard_overview_api.py`

**Interfaces:**
- Produces: `GET /api/dashboard/cve-exposure?limit=` with `limit: int = Query(3, ge=1, le=10)`; `get_cve_exposure(session, *, client_id: str, days: int | None, limit: int = 3)` passes `limit` to `AsyncDashboardRepo.cve_exposure(limit=…)` (which already takes it). `CveExposure` schema and the order (KEV first, CVSS descending nulls last, `cve_id`) unchanged.

- [ ] **Step 1: Write the failing test** `test_cve_exposure_limit_param`: client `acme` (as `test_attention_is_client_scoped` seeds one), five open `CveTracker` rows with `tech="Nginx"`: `CVE-2026-0001` (`cisa_kev=True`, `cve_score=7.5`), `CVE-2026-0002` (`cisa_kev=True`, no score), `CVE-2026-0003` (9.8), `CVE-2026-0004` (8.8), `CVE-2026-0005` (no score). No parameter → `[i["cve_id"] for i in items] == ["CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0003"]`; `limit=4` → those plus `"CVE-2026-0004"`; `limit=0` and `limit=11` → 422.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_dashboard_overview_api.py -q -k cve_exposure_limit`. Expected: FAIL (`limit=4` returns 3 rows; `limit=0` returns 200).
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the Step 2 command, `uv run pytest tests/integration/test_dashboard_overview_api.py tests/integration/test_dashboard_overview_service.py -q`, ruff. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): row limit on the dashboard cve-exposure endpoint`

### Task 2: B-D4 ransomware top groups: five (4.4, D7)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/ransomware.py:161-172,206-211` (`AsyncRansomwareVictimRepo.summary`), `apps/api/src/cti_api/services/dashboard_overview.py:278` (`get_ransomware`)
- Test: `tests/integration/test_dashboard_overview_query.py`

**Interfaces:**
- Produces: `summary(self, *, since, apac_codes, client_codes, top_n: int = 3)`; `.limit(top_n)` replaces `.limit(3)`; `get_ransomware` passes `top_n=5`; `get_map` and `get_attention` keep the default. The docstring's "3 teratas" becomes "`top_n` teratas".

- [ ] **Step 1: Write the failing test** `test_ransomware_summary_top_n`: victims dated `_TODAY` in six groups with counts `Akira` 3, `Bashe` 2, `Cactus` 2, `Dragon` 1, `Eldorado` 1, `Fog` 1. `summary(since=_TODAY - 30 days, apac_codes=(), client_codes=())["top_groups"] == [("Akira", 3), ("Bashe", 2), ("Cactus", 2)]`; with `top_n=5` the list is those three plus `("Dragon", 1), ("Eldorado", 1)`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_dashboard_overview_query.py -q -k ransomware_summary`. Expected: `test_ransomware_summary_top_n` FAILS (`TypeError: ... unexpected keyword argument 'top_n'`); `test_ransomware_summary_and_weekly` passes.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the Step 2 command, `uv run pytest tests/integration -q -k "ransomware or dashboard_overview"`, mypy, ruff. Expected: PASS, `test_ransomware_summary_and_weekly` unchanged.
- [ ] **Step 5: Commit** `feat(api): dashboard ransomware overview returns the top five groups`

### Task 3: B-D2 `DashboardAttention` gains names and a previous window (4.2, P3, C5, C6)

**Files:**
- Modify: `apps/api/src/cti_api/schemas/dashboard_overview.py:31-38,66-68` (`DashboardAttention`; `NameCount` moves above it), `packages/cti-core/src/cti_core/db/repositories/dashboard.py` (two methods after `watchlist_hit_count`, line 762, and after `cve_exposure_counts`, line 838), `packages/cti-core/src/cti_core/db/repositories/ransomware.py` (two methods after `summary`), `apps/api/src/cti_api/services/dashboard_overview.py:206-272` (`get_attention`)
- Test: `tests/integration/test_dashboard_overview_query.py`, `tests/integration/test_dashboard_overview_service.py`, `tests/integration/test_dashboard_overview_api.py`

**Interfaces:**
- Produces (schema, all five in the spec 4.2 table): `kev_tech: list[str]`, `ransomware_prev_in_client_scope: int | None`, `ransomware_client_top_industry: NameCount | None`, `watchlist_top: list[str]`, `client_countries: list[str]`. No existing field changes.
- `AsyncDashboardRepo.kev_tech_names(self, *, client_id: str, tech: Sequence[str] | None, exclude_cve_ids: Sequence[str] | None, limit: int = 3) -> list[str]` and `AsyncDashboardRepo.watchlist_top_names(self, *, client_id: str, posted_on_start: datetime.date | None, limit: int = 3) -> list[str]`: statements exactly as spec 4.2 "Queries" (the first through `_open_cve_stmt` + `_tracker_ticket_join`, the second the `watchlist_hit_count` join grouped by `m.c.entity_id, m.c.name`).
- `AsyncRansomwareVictimRepo.count_in_countries(self, *, since: datetime.date, until: datetime.date, codes: Collection[str]) -> int` (half-open `since <= when < until`; 0 without a query when `codes` is empty) and `top_industry_in_countries(self, *, since: datetime.date | None, codes: Collection[str]) -> tuple[str, int] | None` (date rule of `summary`; `industry` not null and `func.trim(industry) != ""`; count descending then name; `None` without a query when `codes` is empty).
- `get_attention`: keeps `scope = await _cve_scope(session, client_id)` in a variable and reuses it for `kev_tech_names(**scope)`; previous window only when `days is not None`: `count_in_countries(since=since - timedelta(days=days), until=since, codes=client_codes)`, else `None`; `client_countries = sorted(client_codes)`; top industry as `{"name": …, "count": …}` or `None`. All sequential on the one session, inside the cached block; cache key unchanged.

- [ ] **Step 1: Write failing tests.** Query file: `test_kev_tech_names_orders_by_count_and_skips_closed` (client `default`: open KEV rows `Nginx` ×2, `Apache` ×1, `Citrix` ×1, `Zimbra` ×1; one KEV row `Exchange` whose ticket has a `closure_date`; one KEV row with `tech=None`; one non-KEV row `Redis`; a KEV row `Nginx` for client `other` → `kev_tech_names(client_id="default", tech=None, exclude_cve_ids=None) == ["Nginx", "Apache", "Citrix"]`, and for `other` `== ["Nginx"]`); `test_watchlist_top_names_scoped_to_client` (watch `Qilin` and `Akira` for `default`, `LockBit` for `other`; articles dated `_TODAY`: two naming `Qilin`, one `Akira`, three `LockBit` → `default` `== ["Qilin", "Akira"]`, `other` `== ["LockBit"]`, `posted_on_start=_TODAY + 1 day` → `[]`); `test_ransomware_count_in_countries_window_is_half_open` (`SG` victims discovered at `since - 1 day`, `since`, `until - 1 day`, `until`, and a `US` victim at `since` → `count_in_countries(since=…, until=…, codes={"SG"}) == 2`; `codes=()` → 0); `test_ransomware_top_industry_ignores_blank` (`SG` victims with industry `"Finance"`, `"Finance"`, `"Health"`, `""`, `"   "`, `None` → `("Finance", 2)`; only blank ones → `None`; `codes=()` → `None`; a tie `Energy` 1 / `Health` 1 → `("Energy", 1)`). Service file: `test_attention_previous_window_none_for_all_time` (client with country `SG`, one victim 10 days ago, one today: `days=None` → `ransomware_prev_in_client_scope is None`; `days=7` → `== 1` and `ransomware_in_client_scope == 1`); `test_attention_kev_tech_excludes_false_positive` (seed as `test_attention_excludes_false_positive_and_applies_pir_period` does, with the false-positive CVE on its own tech → `kev_tech` lists the other tech and not the false-positive one). API file: `test_attention_new_fields_are_client_scoped` (clients `acme` with countries `["SG"]` and `other` with `["US"]`, each its own KEV tech, watched actor and an in-country victim with an industry; each response lists only its own `kev_tech`, `watchlist_top`, `client_countries` and `ransomware_client_top_industry`); extend `test_attention_client_without_countries` with `client_countries == []`, `ransomware_prev_in_client_scope == 0` and `ransomware_client_top_industry is None`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_dashboard_overview_query.py tests/integration/test_dashboard_overview_service.py tests/integration/test_dashboard_overview_api.py -q -k "kev_tech or watchlist_top or count_in_countries or top_industry or previous_window or new_fields or without_countries"`. Expected: FAIL (`AttributeError` on the four methods; `KeyError` on the new keys).
- [ ] **Step 3: Implement** per Interfaces. Indonesian docstrings: why `kev_tech_names` takes the `_cve_scope` dict (same exclusions as `kev_in_stack`, so the names can never mention a tech the count ignores), and why no day-coverage rule is applied to the previous ransomware window (victims are not articles).
- [ ] **Step 4: Run** the three files in full, `uv run pytest tests/integration/test_newsroom_api.py -q`, mypy, ruff. Expected: PASS; `test_attention_brief_headline_uses_real_trend` unchanged.
- [ ] **Step 5: Commit** `feat(api): dashboard attention returns kev tech, watched actors, client countries and the previous ransomware window`

### Task 4: B-D3 Trending learns malware and CVE (4.3, D8, P19)

**Files:**
- Modify: `apps/api/src/cti_api/schemas/dashboard_overview.py:41-50` (`TrendItemOut`), `packages/cti-core/src/cti_core/db/repositories/dashboard.py:36,511-553` (import `CVE`, `MALWARE_TYPES`; `daily_entity_counts`), `packages/cti-core/src/cti_core/db/repositories/ransomware.py` (`known_group_names`), `apps/api/src/cti_api/services/trending.py`, `apps/api/src/cti_api/routers/articles.py:352-356` (`dashboard_trending`)
- Test: `tests/unit/test_trending.py`, `tests/integration/test_dashboard_overview_query.py`, `tests/integration/test_dashboard_overview_api.py`

**Interfaces:**
- Produces: `TrendKind = Literal["actor", "ttp", "malware", "cve"]` exported by `services/trending.py`; `TrendItem.kind: TrendKind`, `TrendItem.ransomware_group: bool = False` (last field, after `entity_id`); `TrendItemOut.kind` the same four values, `ransomware_group: bool = False`.
- `daily_entity_counts(dimension=…)` accepts `"malware"` → `mention_rows(*MALWARE_TYPES)` keyed by `m.c.name`, and `"cve"` → `mention_rows(CVE)` keyed by `m.c.external_id`. The four existing dimensions and callers unchanged.
- `AsyncRansomwareVictimRepo.known_group_names(self, names: Collection[str]) -> set[str]`: one query, `select(func.lower(group_name)).where(func.lower(group_name).in_(lowered)).distinct()`; returns lower-cased names; an empty input returns `set()` without a query.
- `get_trending(session, *, days, countries=None, news_types=None, search=None, confirmed_only=False, limit=10, kinds: Sequence[TrendKind] = ("actor", "ttp"))`: iterates the fixed tuple `("actor", "ttp", "malware", "cve")` and skips kinds not requested (so order and repeats in the request do not matter), with `_DIMENSION = {"actor": "threat_actor", "ttp": "ttp", "malware": "malware", "cve": "cve"}`; the cache key gains `sorted(set(kinds))`. `rank_trends` passes `kind` through unchanged. The inner `_key` treats every kind except `"ttp"` as a plain name (today it is `if kind == "actor"`, which would send malware and CVE names through `_split_ttp`). `_attach_entity_ids` leaves `entity_id=None` for `malware` and `cve`. New `async def _flag_ransomware_groups(session, items: list[TrendItem]) -> list[TrendItem]`, called after `_attach_entity_ids`, sets `ransomware_group` on `actor` items whose `name.lower()` is in `known_group_names(...)`; skipped when no item is an actor.
- Route: `kinds: list[TrendKind] = Query(["actor", "ttp"])`.

- [ ] **Step 1: Write failing tests.** Unit: `test_rank_trends_keeps_malware_and_cve_kinds` (`rank_trends({("malware", "Cobalt Strike", None): [3], ("cve", "CVE-2026-1111", None): [4], ("actor", "Qilin", None): [5]}, {})` → `{i.name: i.kind for i in items} == {"Cobalt Strike": "malware", "CVE-2026-1111": "cve", "Qilin": "actor"}` and every `ransomware_group is False`). Query: `test_daily_entity_counts_malware_and_cve` (one article dated `_TODAY` with a `malware` entity `Emotet` and a `tool` entity `Cobalt Strike` through `set_enrichment(malware=…)`, plus a `vulnerability` entity with `external_id="CVE-2026-1111"` mentioned through an `EntityMention` row as `tests/integration/test_entities_api.py:93` does → `dimension="malware"` gives two rows named `Emotet` and `Cobalt Strike`; `dimension="cve"` gives one row whose entity is `"CVE-2026-1111"`). API: `test_trending_default_kinds_are_actor_and_ttp` (three articles each for an actor, a malware and a CVE; no parameter → `{i["kind"] for i in items} <= {"actor", "ttp"}` and every item has the key `ransomware_group`); `test_trending_kinds_param` (`params=[("kinds", "malware"), ("kinds", "cve")]` → kinds are exactly `{"malware", "cve"}` and their `entity_id is None`; `kinds=bogus` → 422); `test_trending_flags_ransomware_group` (victim `group_name="Qilin"`, actor articles named `qilin` → that item has `ransomware_group is True`; another actor has `False`); `test_trending_repeated_kind_counts_once` (Review Focus 3: `[("kinds", "cve"), ("kinds", "cve")]` returns the same `count` for the CVE as `[("kinds", "cve")]`).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_trending.py -q` and `uv run pytest tests/integration/test_dashboard_overview_query.py tests/integration/test_dashboard_overview_api.py -q -k "malware or trending"`. Expected: FAIL (kind folded to `actor`; `KeyError: 'malware'` in the dimension map; unknown query parameter ignored).
- [ ] **Step 3: Implement** per Interfaces. Extend the `daily_entity_counts` docstring (Indonesian) with the two dimensions; docstring on `_flag_ransomware_groups`: a name match against leak-site group names, case-insensitive, can mislabel an actor that shares a name (spec 9).
- [ ] **Step 4: Run** the Step 2 commands in full, `uv run pytest tests/integration/test_newsroom_api.py tests/integration/test_dashboard_overview_service.py -q` (unchanged, still green), mypy, ruff.
- [ ] **Step 5: Commit** `feat(api): trending covers malware and CVE and flags ransomware groups`

### Task 5: B-N1 `articles.summary`: model and migration (4.5 Model, 5)

**Files:**
- Create: `alembic/versions/d9f2b6a4c1e7_articles_summary.py`
- Modify: `packages/cti-core/src/cti_core/db/models/article.py:69` (`Article`, after `posted_on`)
- Test: `tests/integration/test_migrations_match_models.py` (existing, unchanged)

**Interfaces:**
- Produces: `Article.summary: Mapped[str | None] = mapped_column(Text)`; revision `"d9f2b6a4c1e7"`, `down_revision = "c4e8a1f2b9d6"`, `upgrade()` = `op.add_column("articles", sa.Column("summary", sa.Text(), nullable=True))`, `downgrade()` = `op.drop_column("articles", "summary")`. No data statement, index or constraint.

- [ ] **Step 1: Add the model column** with an Indonesian docstring: the capped extractive excerpt (not LLM text, P4), `NULL` for articles stored before 0.8.16 and for articles whose text could not be fetched.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_migrations_match_models.py -q`. Expected: FAIL (the model has a column the migrations do not create).
- [ ] **Step 3: Write the migration** per Interfaces, with the header docstring style of `alembic/versions/` (Indonesian, why nullable and why no backfill: the article text is not stored).
- [ ] **Step 4: Run** the Step 2 command (PASS), `uv run --no-sync alembic heads` (prints `d9f2b6a4c1e7 (head)` and nothing else), mypy, ruff.
- [ ] **Step 5: Commit** model and migration together: `feat(db): nullable articles.summary column for the stored excerpt`

### Task 6: B-N1 `make_dek`, the capped excerpt (4.5 Excerpt, P4, C28)

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/stages/summarize.py`
- Create: `tests/unit/test_summarize_dek.py`

**Interfaces:**
- Produces: `DEK_MAX_CHARS = 600`; `make_dek(summary: str, *, max_chars: int = DEK_MAX_CHARS) -> str | None`, the four rules of spec 4.5 in order (collapse whitespace, empty → `None`; short → unchanged; cut at the last ". ", "! " or "? " found at index 200 or more inside the first `max_chars` characters, keeping the punctuation mark; else `cut.rsplit(" ", 1)[0]` + `chr(0x2026)`). Module-level imports stay free of `nltk` / `sumy`.

- [ ] **Step 1: Write failing tests** (`ELL = chr(0x2026)`): `test_make_dek_empty_is_none` (`""` and `" \n\t "` → `None`); `test_make_dek_collapses_whitespace` (`"a \n\n b\t c"` → `"a b c"`); `test_make_dek_short_text_unchanged` (a 600-character string of words is returned as is); `test_make_dek_cuts_at_last_sentence_end` (`"Sentence one is here. " * 40` → the result ends with `"."`, is at most 600 long and equals the input up to a sentence end); `test_make_dek_without_sentence_end_cuts_at_word_with_ellipsis` (`"word " * 300` → ends with `ELL`, no trailing space before it, length at most 601; and a text whose only ". " sits at index 50 also takes this branch); `test_make_dek_never_exceeds_max_chars_plus_ellipsis` (for the inputs above and `max_chars=250`, `len(result) <= max_chars + 1`); `test_make_dek_long_text_without_spaces` (Review Focus 1: `"x" * 2000` → length 601 ending with `ELL`; `"ab " + "x" * 2000` → `"ab" + ELL`).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_summarize_dek.py -q`. Expected: FAIL with `ImportError: cannot import name 'make_dek'`.
- [ ] **Step 3: Implement** per Interfaces; Indonesian docstring: the value is a verbatim excerpt of the publisher's text, the summarizer's failure path returns the whole article, and the cap is what keeps the stored value at snippet length.
- [ ] **Step 4: Run** the Step 2 command and ruff. Expected: PASS, with no `nlp` extra installed.
- [ ] **Step 5: Commit** `feat(enrich): make_dek caps the extractive summary at 600 characters`

### Task 7: B-N1 the pipeline stores the excerpt (4.5 Persist)

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/stages/persist.py:160-200` (`persist`), `packages/cti-enrich/src/cti_enrich/pipeline.py:444-460,528-546` (both `persist(…)` calls in `complete`; `summary` is computed at line 408)
- Test: `tests/integration/test_pipeline_tier1_db.py`

**Interfaces:**
- Consumes: `Article.summary` (Task 5), `make_dek` (Task 6).
- Produces: `persist(..., summary: str | None = None)` passing `**({"summary": summary} if summary else {})` to `article_repo.upsert` (the pattern of `ttp_status` at `persist.py:199`); both calls in `pipeline.complete` pass `summary=make_dek(summary)`. `persist_rejected` unchanged.

- [ ] **Step 1: Write failing tests.** `test_pipeline_stores_capped_summary`: `LONG = "Kalimat uji nomor satu. " * 100`; `monkeypatch.setattr(pipeline, "summarize", lambda text: LONG)`; `_seed`, `_run`; the stored article (read as `test_pipeline_writes_sources` reads it) has `summary == make_dek(LONG)`, `len(summary) <= 601` and `summary.endswith(".")`. `test_persist_keeps_summary_when_none`: `_run` once (the autouse fixture's summary `"Ringkasan."` is stored), then `monkeypatch.setattr(pipeline, "summarize", lambda text: "")` and `_run` again for the same URL → `summary == "Ringkasan."` (if the pipeline refuses a second run for a stored URL, call `persist` directly with the first run's arguments and no `summary`). `test_pipeline_stores_summary_on_best_practice_branch` (Review Focus 2): the same run with a verdict whose `security_tech_best_practice` is true (a copy of `VERDICT` with that flag) → `summary == "Ringkasan."`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_pipeline_tier1_db.py -q -k summary`. Expected: FAIL (`summary is None`).
- [ ] **Step 3: Implement** per Interfaces; extend the `persist` docstring (Indonesian): a re-run without text must never erase a stored excerpt, the rule `llm_ttp_status` already follows.
- [ ] **Step 4: Run** `uv run pytest tests/integration/test_pipeline_tier1_db.py -q`, `uv run pytest tests/integration -q -k "pipeline or persist or enrich"`, `uv run pytest tests/unit packages -q -k "pipeline or persist"`, ruff. Expected: PASS.
- [ ] **Step 5: Commit** `feat(enrich): the pipeline stores the capped summary excerpt on both persist paths`

### Task 8: B-N1 + B-N2 `ArticleOut.summary` and `first_seen_at` (4.5 API, 4.6, D3, D4, C7)

**Files:**
- Modify: `apps/api/src/cti_api/schemas/article.py:100` (`ArticleOut`, after `posted_on`), `apps/api/src/cti_api/routers/articles.py:155` (`_serialize`)
- Test: `tests/integration/test_articles_router_snapshot.py:34-49,69-77`, `tests/integration/__snapshots__/test_articles_router_snapshot.ambr` and `test_newsletter_router_snapshot.ambr` (generated; the newsletter router reuses `_serialize`)

**Interfaces:**
- Produces: `ArticleOut.summary: str | None = None` (`summary=article.summary`) and `ArticleOut.first_seen_at: str | None = None` (`first_seen_at=article.first_seen_at.isoformat()`, ISO 8601 with offset). Every endpoint returning `ArticleOut` gains both keys.

- [ ] **Step 1: Write failing tests.** `_NORMALIZE` gains `r"(.*\.)?first_seen_at$": (str,)`; `_seed_one_article` passes `summary="Apt41 breached a government network."` to `upsert`; new `test_article_out_first_seen_at_is_iso_with_offset` (`GET /api/articles/{id}` → `datetime.datetime.fromisoformat(body["first_seen_at"]).tzinfo is not None` and `body["summary"] == "Apt41 breached a government network."`).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_articles_router_snapshot.py -q -k first_seen_at`. Expected: FAIL with `KeyError: 'first_seen_at'`.
- [ ] **Step 3: Implement** per Interfaces; Indonesian comment on `first_seen_at`: when the scraper first stored the article, not its publication time, and never changed by a re-crawl.
- [ ] **Step 4: Update snapshots** `uv run pytest tests/integration/test_articles_router_snapshot.py tests/integration/test_newsletter_router_snapshot.py --snapshot-update -q`, then `git diff tests/integration/__snapshots__`. Expected: per article exactly two new keys (`first_seen_at`, `summary`), nothing else. Re-run both files without the flag, then `uv run pytest tests/integration -q -k "article or newsletter or newsroom or entity_ids or inferred"`; any other snapshot file that fails is updated the same way and must show only the two keys. Ruff.
- [ ] **Step 5: Commit** `feat(api): summary and first_seen_at on article responses`

### Task 9: Contract regeneration (4.7)

**Files:**
- Modify (generated): `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`

- [ ] **Step 1: Run** `uv run python tools/export_openapi.py`, then `cd apps/web && pnpm run gen:api`.
- [ ] **Step 2: Read** `git diff --stat` and `git diff docs/openapi.json`. Expected, and nothing else: the `limit` parameter on `/api/dashboard/cve-exposure`; the `kinds` parameter on `/api/dashboard/trending`; five new `DashboardAttention` properties; the four-value `kind` enum and `ransomware_group` on `TrendItemOut` and `TopicOut`; `summary` and `first_seen_at` on `ArticleOut`. Any other change means a schema was touched by mistake: stop and report.
- [ ] **Step 3: Verify** from `apps/web`: `pnpm exec next typegen && pnpm exec tsc --noEmit` exit 0 (the old page still compiles against the wider `kind` union).
- [ ] **Step 4: Commit** `chore(api): regenerate the contract for the dashboard and article fields`

### Task 10: Shared web pieces A: period model, country names, the Dashboard data layer (6.1 period model, 6.4 must-read query, 6.8; P1, P2, P21; constraints 2, 3, 10, 11)

**Files:**
- Create: `apps/web/src/lib/dashboard/period.ts`, `apps/web/src/lib/dashboard/countries.ts`
- Modify: `apps/web/src/components/dashboard/use-dashboard-overview.ts` (rewritten), `apps/web/src/components/newsroom/rubric-queries.ts:47-90`; one-line call-site updates so the old page keeps compiling until Task 23: `components/dashboard/signal-hero.tsx` (drops `incidentOnly` from `useDashboardAttention`, imports `countryName` from the new file), `components/dashboard/overview-cards.tsx` and `app/(app)/dashboard/page.tsx` (pass the new arguments)

**Interfaces:**
- `period.ts`: `type PeriodKey = "1" | "7" | "30" | "90" | "all"`; `PERIODS: readonly { key: PeriodKey; label: string; days: number | null; words: string; suffix: string }[]` with the five rows of the spec 6.1 table (labels "24h", "7d", "30d", "90d", "All"); `periodInfo(key: PeriodKey)`; `parsePeriod(value: string | null): PeriodKey` (anything but `"1" | "30" | "90" | "all"` is `"7"`); `periodHref(pathname: string, searchParams: URLSearchParams, key: PeriodKey): string` (copies the params, sets `period` or deletes it for `"7"`, returns `pathname + (qs ? "?" + qs : "")`).
- `countries.ts`: `normalizeCountry(code: string): string` and `countryName(code: string): string`, moved from `signal-hero.tsx:12-17` with the locale registration and the `UK → GB`, `EL → GR` aliases.
- `use-dashboard-overview.ts`: every `queryFn` through `unwrap(await api.GET(…), "Failed to load {thing}")`, every query `retry: noClientRetry`, no `refetchInterval`, period-driven ones `placeholderData: keepPreviousData`. Exports and keys: `useDashboardStats(days: number | null, incidentOnly: boolean)` `["dashboard","stats",days,incidentOnly]` (moved from `page.tsx:43`); `useDashboardMap(days)` `["dashboard","map",days,clientId]`; `useDashboardAttention(days)` `["dashboard","attention",days,clientId]` (no `incident_only` sent); `TREND_KINDS = ["actor","malware","cve"] as const` and `useDashboardTrending(days, kinds: readonly TrendItem["kind"][])` `["dashboard","trending",days,kinds.join(",")]`; `useDashboardRansomware(days)` `["dashboard","ransomware",days]`; `useCveExposure(days, limit: number)` `["dashboard","cve-exposure",days,limit,clientId]`; `useMustRead(days)` `["dashboard","must-read",days]` → `GET /api/articles` with `page: 1, page_size: 5, sort: "priority"` and `posted_on_start` computed inside the `queryFn` (omitted for `null`), returning `{ articles: Article[]; fetchedAt: number }` with `fetchedAt: Date.now()` read in the `queryFn`; `useTaStats(enabled: boolean)` `["dashboard","ta-stats"]` (moved from `page.tsx:59`); `useNewestCluster(enabled: boolean)` `["dashboard","newest-cluster"]` (moved from `overview-cards.tsx:301`); `useLlmQueue(enabled: boolean)` `["dashboard","llm-queue"]` → `GET /api/data-health`, `select` = `llm.queue`, `staleTime: 60_000`. Types `Article`, `TrendItem`, `DashboardStats` exported from the schema.
- Also here: `articleWhen(a: Pick<Article, "first_seen_at" | "posted_on">, fetchedAt: number, compact = false): { text: string; title?: string }`: under 24 h since `first_seen_at` → `fmtAgo` (or `fmtCompactAge` when `compact`), else `fmtShortDate(parseLocalDate(posted_on))`, else `fmtShortDate(first_seen_at)`; `title` = `"First seen " + fmtDateTime(first_seen_at)` when set (D4, P7, C7).
- `rubric-queries.ts`: `useWatchlistNames` and `useTechStackNames` move to `unwrap` + `retry: noClientRetry` (keys unchanged); `useArticleMatchers()` calls them with `can("view_ta")` and `can("view_cve")` (`useCan`); its return type is unchanged. Its Newsroom caller (`front-section.tsx`) is unchanged.

- [ ] **Checklist:** `parsePeriod` for `null`, "7", "1", "all", "abc", "0", "ALL" gives 7, 7, 1, all, 7, 7, 7; `periodHref("/dashboard", new URLSearchParams("x=1&period=30"), "7")` is `/dashboard?x=1` and with `"90"` is `/dashboard?x=1&period=90`; the old `/dashboard` still renders every card; `/api/dashboard/attention` is requested without `incident_only`; a 403 on any Dashboard query is requested once, a 500 at most three times, an empty-body 502 is an error and not empty data; a role without `view_ta` / `view_cve` sends no `/api/ta/watchlist-names` / `/api/techstack` on Dashboard and Newsroom; switching the client changes the keys of map, attention and cve-exposure; `articleWhen` for an article first seen 2 h ago, 30 h ago, with an empty `posted_on`, and with `first_seen_at` null and `posted_on` empty (prints "—", no throw).
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `refactor(web): dashboard period model and queries through unwrap without client retries`

### Task 11: Shared web pieces B: priority lines and chip, grade code, article opener (6.4 label table, 6.8; D10, D19, P16, P18, C25)

**Files:**
- Create: `apps/web/src/components/newsroom/priority-chip.tsx`, `apps/web/src/components/dashboard/article-opener.tsx`
- Modify: `apps/web/src/components/newsroom/score-reasons.ts`, `apps/web/src/components/newsroom/grade-chip.tsx`

**Interfaces:**
- `score-reasons.ts`: `priorityTone(score: number): "destructive" | "warning" | "info"` (`>= 90`, `>= 70`, else); `PRIORITY_LINE: Record<string, (a: Article) => string>` with the eight codes of the spec 6.4 table, and `priorityLines(a: Article): string[]`: items of `a.score_reasons.priority` sorted by `points` descending (stable), each `"{label} +{points}"` with "−" (U+2212) for negative points, an unknown code printed as received. `describePriority` and `PRIORITY_TEXT` unchanged.
- `PriorityChip({ score }: { score: number })`: a `<span>` "PRIORITY {score}" (the raw number, C25), `bg-{tone}/15 text-{tone}-text` from `priorityTone` through a literal class map (Tailwind cannot see built class names), `text-2xs` semibold, not interactive.
- `GradeChip({ a, codeOnly = false })`: with `codeOnly` the label is `a.admiralty_code` alone; the tooltip is unchanged. Newsroom callers keep the default.
- `useArticleOpener(): { openArticle: (a: Article) => void; host: ReactNode }`: selected article in state, `host = <ArticleModal article={selected} onOpenChange={(o) => { if (!o) setSelected(null); }} />`. `ArticleModal` is not modified.

- [ ] **Checklist:** `priorityTone` for 69, 70, 89, 90, 176 gives info, warning, warning, destructive, destructive; `priorityLines` for an article with `confirmed_incident` 25, `kev` 15 and `ttps` 8 (three TTPs) gives three lines in that order with "+25", "+15", "+8" and "3 ATT&CK techniques"; `corroboration` without `story` reads "Corroborated by other sources"; `pir_match` with an empty `pir` list reads "Matches a PIR"; an unknown code prints as received; Newsroom's grade chip still reads "B2 · P131".
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): priority chip and ranking lines, code-only grade chip and the dashboard article opener`

### Task 12: `WorldDots` APAC view (6.3 View, 6.8; P8)

**Files:**
- Modify: `apps/web/src/components/world-dots.tsx`

**Interfaces:**
- Produces: `type WorldView = "world" | "apac"`; `WorldDots` gains `view?: WorldView` (default `"world"`: Login and the `fit` behaviour unchanged). `"apac"` fits the equirectangular projection to longitudes 60° E to 180° and latitudes 50° S to 55° N so the box is filled, ignores `fit`, and draws neither land dots nor points outside that range. `export function inView(code: string, view: WorldView): boolean`: `"world"` → the code has a coordinate; `"apac"` → that coordinate lies in the range. It reads the same coordinate the component places the point with (centroid or `SMALL_STATES`), so the centroid table moves from the in-component `useMemo` to a lazily built module-level map shared by both.

- [ ] **Checklist:** `/login` looks as before (no prop passed); with `view="apac"` Indonesia, Japan, India and Australia are inside and Europe and the Americas are not drawn; `inView("SG", "apac")`, `inView("ID", "apac")` true, `inView("US", "apac")` false, `inView("UK", "world")` true (alias), `inView("", "world")` and `inView("ZZ", "world")` false; a point whose code is not in view gets no transparent `<button>`; resizing the box keeps the range filled; light and dark.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): world dots map gains an APAC view and an in-view test`

### Task 13: Page shell: server page, header, period in the URL, toggle, gate, section stubs (6 constraint 1, 6.1, 6.7 No access, 6.8; D5, D6, P1, P15, P17, C29)

**Files:**
- Create: `apps/web/src/components/dashboard/dashboard-view.tsx`, and stubs `needs-action.tsx`, `lead-story.tsx`, `by-the-numbers.tsx`, `must-read.tsx`, `trending.tsx`, `month-charts.tsx`, `cve-watchlist.tsx`, `more-section.tsx` in the same folder
- Modify: `apps/web/src/app/(app)/dashboard/page.tsx` (rewritten), `apps/web/src/components/dashboard/stat-box.tsx` (adds `PanelError`)
- Delete: `apps/web/src/app/(app)/dashboard/layout.tsx`

**Interfaces:**
- Consumes: Task 10 (`parsePeriod`, `periodHref`, `PERIODS`, `PeriodKey`), Task 11 (`useArticleOpener`).
- `page.tsx` (server component): `export const metadata: Metadata = { title: "Dashboard" }`; default export renders `<Suspense><DashboardView /></Suspense>`. No `usePageTitle`.
- `stat-box.tsx`: `PanelError({ title, error, onRetry, className }: { title: string; error: unknown; onRetry: () => void; className?: string })` = `StatePanel variant="error"` with `description` = `` `${message} Other panels are fine.` `` (`message` = `error.message`, fallback "The request failed.") and `action` = a "Retry" button.
- Section props, final from this task on (each stub is a client component returning `null`): `NeedsAction({ period }: { period: PeriodKey })`; `LeadStory({ period, openArticle }: { period: PeriodKey; openArticle: (a: Article) => void })`; `ByTheNumbers({ period, threatOnly }: { period: PeriodKey; threatOnly: boolean })`; `MustRead({ period, openArticle })` (as `LeadStory`); `Trending({ period })`; `MonthCharts({ threatOnly }: { threatOnly: boolean })`; `CveWatchlist({ period })`; `MoreSection({ period, threatOnly })`.
- `DashboardView()`: `period = parsePeriod(useSearchParams().get("period"))` on every render, no mirrored state; `threatOnly` in `useState(true)`. Without `can("view_news")`: only the header and `StatePanel variant="no-access"` "Dashboard needs the view_news permission" / "Your role ({user.role}) does not have it."; the sections are not mounted, so no request is sent. Header: `PageHeader` with kicker "THREAT BRIEFING · {CLIENT}" (`useActiveClientName()` upper-cased; "THREAT BRIEFING" while `null`), title = today from `useSyncExternalStore` (client snapshot `new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" }).format(new Date())`, server snapshot `"Dashboard"`), no description, `actions` = `SegmentedControl aria-label="Period"` over `PERIODS`, then a `Checkbox` with a real `<label>` "Threat news only" (`text-xs`). Period handler: `next = periodHref(pathname, new URLSearchParams(searchParams.toString()), key)`; return when `next === pathname + (searchParams.toString() ? "?" + searchParams.toString() : "")`; else `router.replace(next, { scroll: false })`. Body, in order: `<NeedsAction>`; a two-column row (`LeadStory` | `ByTheNumbers`); a two-column row (`MustRead` | `Trending`); `<MonthCharts>`; `<CveWatchlist>`; `<MoreSection>`; `{host}` once.

- [ ] **Checklist (controller):** the tab reads "Dashboard · {PLATFORM_NAME}" after a full load and after client navigation; the h1 is today's date in English and the kicker the client in upper case; no hydration warning. **Period URL** (Review Focus 5): each option changes the URL once; 7d removes the parameter; `/dashboard?period=90` loads on 90d; `?period=abc`, `?period=7`, `?period=0`, `?period=ALL` and `?period=1&period=30` load without a redirect (the first four on 7d, the last on 24h); `?period=30&x=1` keeps `x=1` when the period changes; clicking the selected option sends no navigation (Network panel); Back leaves the page. The toggle is checked by default, is not in the URL and is reachable by keyboard with its label. A role without `view_news` sees the no-access panel with its role name and the Network panel shows no `/api/proxy/api/dashboard*` or `/api/proxy/api/articles` request. `pnpm build` passes (proves the `Suspense` boundary).
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard shell with a server page title, period in the URL and a view_news gate`

### Task 14: Needs action: headline, three rows and "No data yet" (6.2, 6.7 No data yet; D6, D17, P2, P9, C4, C5, C6, C13; DB7, DB8)

**Files:**
- Modify: `apps/web/src/components/dashboard/needs-action.tsx` (lift layout from the unmounted `signal-hero.tsx`)

**Interfaces:**
- Consumes: `useDashboardAttention(days)`, `useDashboardMap(days)`, `periodInfo`, `countryName`, `useWatchlistNames`, `useTechStackNames`, `useCan`, `useActiveClientName`.
- `NeedsAction({ period })`: `<section aria-label="Needs action">` holding `HeroPanel` (kicker "NEEDS ACTION", `title` = the headline) with body `lg:grid-cols-[minmax(0,752fr)_500px]`. Left column = this task; the right column is an empty 500 × 380 box until Task 15. The hero skeleton shows only while attention and map are both pending; stale data dims (`opacity-60`).
- Headline, rows, second lines and links exactly per the spec 6.2 text and table (value through `toLocaleString("en-US")`; each row one `Link` with `heroLinkClass`, `aria-label` "{title}: {value}. Open", "Open →" on the right, rows divided by `divide-hero-foreground/15`; the Newsroom links add `&period={days}` only for 1, 7 and 30 and `&country={code}` only with exactly one country). Empty parts of a second line are dropped before joining with " · ".
- Attention error: the left column shows "Could not load the signals", the server message and a "Retry" button in hero tokens (not `PanelError`, which uses page tokens).
- "No data yet": `noData = can("view_cve") && can("view_ta") && tech.isSuccess && watch.isSuccess && tech.data.length === 0 && watch.data.length === 0` with `useTechStackNames(can("view_cve"))` and `useWatchlistNames(can("view_ta"))`; when true the kicker, title, body and the "Set up tech stack" `Link` (→ `/cve`) of spec 6.7 replace the headline and rows; the right column stays.

- [ ] **Checklist (controller):** headline for 0, 1 and 3 signals and for each of the five periods ("since yesterday" … "of all time"), with "your organisation" before the client name resolves; the three second lines against SQL counts, including value 0 on row 1 ("None open right now"), `kev_without_ticket` 0 (part omitted), the ransomware comparison up / down / same and absent on "All", "1 active PIR with new articles"; the one-country, three-country and no-country titles, second line and links; `&period=` present on 24h / 7d / 30d and absent on 90d / All; each row is a single link in the accessibility tree with no nested control; the attention request forced to 500 shows the hero error with the server text and a working "Retry" while the map side is unaffected; the empty client shows "Nothing is matched to … yet" and the button goes to `/cve`; a role without `view_cve` never sees that state and sends no `/api/techstack`; no `Chip` inside the hero; light and dark.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard needs-action hero with named signals, the previous-window comparison and a get-started state`

### Task 15: Signal map (6.3; P8; DB5, DB6)

**Files:**
- Modify: `apps/web/src/components/dashboard/needs-action.tsx` (after Task 14; lift the map code from `signal-hero.tsx:49-180`)

**Interfaces:**
- Consumes: `WorldDots` with `view` and `inView` (Task 12), `useDashboardMap(days)`, `countryName`, `MeterBar onHero`.
- Right column of the hero: a 500 × 380 box with `WorldDots` (`dynamic`, `ssr: false`), title "Signal map", subtitle "Incidents & ransomware victims, {words}". View in `useState<WorldView>("apac")`, switched by two text buttons "APAC" and "World" (`heroLinkClass`, `aria-pressed`) in the box's top right corner. Points as today (weight `incidents + ransomware_victims`, tone, `ring` for `client_countries`), memoised on `map.data` and the view; `label` "{country}: {i} incidents, {v} ransomware victims"; a row without a country code is "Unknown country" and is not passed to the map. Kept: focus and hover tooltip (country; "{i} incidents · {v} ransomware victims"; "Top: {actor}, {industry}" when present), click or Enter → `router.push("/newsroom?country={code}")`, the legend ("Incidents" `bg-hero-accent`, "Ransomware" `bg-hero-eyebrow`, "Your countries (ring)") bottom left, the `sr-only` ordered list of the ten heaviest points with `inView(code, view)`.
- "TOP COUNTRIES" overlay (bottom right, `bg-hero-panel`): the four heaviest points with `inView(code, view)`: name, `MeterBar onHero` (`value` = weight, `max` = the first row's weight, `aria-label` naming the country), number; plain text, no links; hidden when the view has no point.
- Empty (`points.length === 0`): centred "No incidents with a country in this period." Error: centred "Could not load the map", the server message and "Retry".

- [ ] **Checklist (controller):** the map opens on APAC; "World" redraws and `aria-pressed` follows; tooltip on hover and on keyboard focus; click and Enter go to `/newsroom?country=XX`; a client country carries the ring; the legend swatches are the two point colours in light and dark; "TOP COUNTRIES" equals the four heaviest points of the current view and changes with it; a client whose only country is outside APAC shows its ring after switching to "World"; the map request forced to 500 shows the map error with the server text while the three rows stay; an empty period shows the empty sentence and no overlay; the subtitle follows the period; `/login` unchanged.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard signal map with an APAC default, a world switch and a top-countries list`

### Task 16: Lead story (6.4 Lead; D3, D4, D10, D19, P6, P7, P10, P16, C7, C25, C28; DB10)

**Files:**
- Modify: `apps/web/src/components/dashboard/lead-story.tsx`

**Interfaces:**
- Consumes: `useMustRead(days)`, `articleWhen`, `PriorityChip`, `priorityLines`, `EntityChip`, `Chip`, `PanelError`.
- `LeadStory({ period, openArticle })`: `<article aria-label="Lead story">` over `articles[0]`. Kicker "LEAD STORY · " + `PriorityChip` (omitted when `priority_score` is `null`) + " · {n} SOURCES" ("1 SOURCE" for 1; omitted when `story` is `null`), then `Chip kind="flag" value="ATT&CK PENDING"` when `llm_ttp_status === "pending"`. `<h2>` holding a `<button>` → `openArticle(article)`. Dek = `summary` with `line-clamp-3`, not rendered when `null`. Byline "{source} · {when}" with `articleWhen(a, fetchedAt)` (`text` shown, `title` attribute). Beside the byline: the first two `ttps` as `EntityChip type="attack-pattern" name={id}` and the first two `entities` of type `vulnerability` as `EntityChip type="vulnerability" name={external_id ?? name}`. "WHY IT RANKS FIRST" box (`bg-primary/10`, `<h3>`), not rendered when `priority_score` is `null`: one line per `priorityLines(article)`; an empty list prints "Ranked on source confidence alone."
- States: first load `Skeleton` (`aria-hidden`); stale data dims; error → `PanelError` "Could not load the lead story" with `refetch`; no article → `StatePanel variant="empty"` "Nothing to read {suffix}" / "Widen the period to see the highest-priority story."

- [ ] **Checklist (controller):** the dek shows for an article with a summary and the block is absent without one; "2 h ago" for the two-hour-old article and the date after 24 h, with "First seen …" on hover; "1 SOURCE" and "{n} SOURCES"; the priority chip tones at 69 / 70 / 89 / 90 / 131 and the raw 131 printed; every "Why it ranks first" line matches `score_reasons` (order, sign, PIR titles, own assets); the title opens `ArticleModal` and focus returns to it on close; the chips are siblings of the button, not children. **Sparse article:** an article with `priority_score`, `story`, `summary` null, empty `ttps`, `entities` and `score_reasons.priority`, and an empty `posted_on` renders title and byline only and throws nothing. `/api/articles` forced to 500 shows the error with the server text and "Retry" refetches; a period with no article shows the empty panel; one `/api/articles` request serves the lead and Must read.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard lead story with dek, first-seen time and the reasons it ranks first`

### Task 17: By the numbers (6.4 By the numbers; P5, C8; DB9)

**Files:**
- Modify: `apps/web/src/components/dashboard/by-the-numbers.tsx`

**Interfaces:**
- Consumes: `useDashboardStats(days, threatOnly)`, `useDashboardRansomware(days)`, `useCveExposure(days, 4)` (the limit the CVE watchlist uses, so one request), `useDashboardAttention(days)`, `Sparkline`, `periodInfo`.
- `ByTheNumbers({ period, threatOnly })`: heading "BY THE NUMBERS · {WORDS}" (+ " · THREAT NEWS ONLY" when the toggle is on); a `dl` of the four rows of the spec 6.4 table (number, label, second line, 96 px graphic slot; row 4's slot stays empty). Delta text for rows 1 and 2 exactly per the spec paragraph under the table ("▲ {p}% vs previous period" / "▼ …" / "no change vs previous period" / "no prior-period data" / "all time"), the arrow `aria-hidden` plus visually hidden "up" / "down". Sparklines `aria-hidden`; row 3's has `title="Last 8 weeks"`.
- Per row: source pending → a skeleton line; source failed → "–", "Could not load" and a "Retry" text button calling that source's `refetch`; the other rows unaffected. Attention failing or pending only removes the attention-fed parts of rows 3 and 4. Stale rows dim.

- [ ] **Checklist (controller):** the four numbers against SQL for 7d and 30d; the heading follows period and toggle; deltas: up, down, no change, "no prior-period data" on a young window and "all time" on All, with a previous value of 0 never printing "Infinity" or "NaN"; row 3 prints "{apac} in APAC" alone for a client without countries and adds "· {n} in your countries" otherwise; row 4 prints "all KEV have a ticket" or "{n} KEV without a ticket"; toggling "Threat news only" changes rows 1-2 only and sends one `/api/dashboard` request; `/api/dashboard/ransomware` forced to 500 fails row 3 only, with a working "Retry"; no extra `cve-exposure` request beyond the watchlist's.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard by-the-numbers rows with period deltas and per-row failure states`

### Task 18: Must read (6.5 Must read; D10, D19, P7, P10, P18; DB10)

**Files:**
- Modify: `apps/web/src/components/dashboard/must-read.tsx`

**Interfaces:**
- Consumes: `useMustRead(days)`, `articleWhen(a, fetchedAt, true)`, `PriorityChip`, `GradeChip codeOnly`, `useArticleMatchers`, `Chip`, `PanelError`.
- `MustRead({ period, openArticle })`: `<h2>` "Must read", subtitle "Ranked by priority score", an `<ol>` of `articles.slice(1, 5)`. Row: kicker `PriorityChip` (omitted when `null`) + " · " + `news_type.toUpperCase()` (omitted when empty); `<h3>` holding a `<button>` → `openArticle(a)`, `line-clamp-2`; dek `summary` `line-clamp-2`, not rendered when `null`; meta "{source} · {when} · {first TTP id}" (TTP id `font-code`, omitted when none); then `Chip kind="flag"` chips "Incident" (`confirmed_incident`), "Watchlist" and "Tech stack" (matchers), "ATT&CK PENDING" (`llm_ttp_status === "pending"`), and `GradeChip codeOnly` when `admiralty_code` is set.
- States: skeleton; dim; error → `PanelError` "Could not load the reading list"; zero articles → the component renders nothing (the lead's empty panel speaks); exactly one article → "No other story in this period."

- [ ] **Checklist (controller):** four rows in priority order, none repeating the lead; "7 h" for a recent article and the date after 24 h; `"apac"` prints "APAC"; the chips appear per article and are siblings of the title button; the grade chip shows the code alone with the full tooltip; a title opens `ArticleModal` (its "Open Article ↗" still links out, DB10); two articles in the period → one row; one → the sentence; none → nothing; a `view_news`-only role sees no "Watchlist" / "Tech stack" chip and sends no names request; the error state shares "Retry" with the lead (one refetch).
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard must-read list with deks, compact ages and match chips`

### Task 19: Trending (6.5 Trending; D8, P11; DB11)

**Files:**
- Modify: `apps/web/src/components/dashboard/trending.tsx`

**Interfaces:**
- Consumes: `useDashboardTrending(days, TREND_KINDS)`, `EntityChip`, `Chip`, `PanelError`.
- `Trending({ period })`: `<h2>` "Trending"; subtitle "vs previous {window_days} days" when `baseline_reliable`, else "last {window_days} days · not enough history to compare"; the first six items as rows: `EntityChip` (`type="intrusion-set"` with `id={entity_id}` for `actor`; `type="malware,tool"` for `malware`; `type="vulnerability"` for `cve`), kind chip `Chip kind="flag"` ("Ransomware" for an actor with `ransomware_group`, else "Actor"; "Malware"; "CVE"), `Chip kind="status" value="action"` with the text "NEW" when `is_new`, count in `font-code` right-aligned, then "+{change_pct}%" in `text-muted-foreground` when `change_pct` is not `null` and the item is not new. Empty: "Nothing is rising in this period." Error: `PanelError` "Could not load trending". Skeleton and dim as elsewhere. The API's `window_label` is not rendered.

- [ ] **Checklist (controller):** the request carries `kinds=actor&kinds=malware&kinds=cve`; six rows at most; the three kind chips, "Ransomware" on the actor named like a victim group, "NEW" on a new item and "+n%" on a risen one, never both; each name links to its entity (actor by id, malware and CVE through resolve); on "All" the subtitle says 7 days; a young instance shows the "not enough history" subtitle and no "NEW"; a `ttp` item never appears; 500 → the panel error with "Retry"; no nested control in a row.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard trending across actors, malware and CVEs with ransomware and new chips`

### Task 20: The month in charts (6.6 charts; D5, D7, P13, P20, C9, C11; DB12, DB16, DB17)

**Files:**
- Modify: `apps/web/src/components/dashboard/month-charts.tsx`

**Interfaces:**
- Consumes: `useDashboardStats(30, threatOnly)`, `useDashboardRansomware(30)` (same keys as the period requests, so no extra request on 30d), `BarSeries`, `MeterBar`, `ShareBar`, `SHARE_BAR_SEGMENT`, `EntityChip`, `entityHref`, `parseLocalDate`, `fmtShortDate`, `PanelError`.
- `MonthCharts({ threatOnly })`: `<h2>` "The month in charts", subtitle "Last 30 days · all sources" (+ " · threat news only"); four cards (`sm:grid-cols-2 xl:grid-cols-4`), each an `<h3>` title, a subtitle and a 220 px body, content exactly per the spec 6.6 card table. Decisions the table leaves to code: the 30 dates are built from the date part of `generated_at` through `parseLocalDate` going back 29 days, never through `new Date(isoDate)` (Review Focus 4); "three highest" = bars above 0 sorted by value descending then date descending, first three; industries percentages are of the shown total, rounded, the last row taking `100 − sum of the others`; the technique name splits at the first " — "; "Show all 10" / "Show 5" is component state with `aria-expanded`.
- Each card has its own error panel (titles of the spec 6.7 table); the three fed by `/api/dashboard` share one `refetch`. Skeleton on first load; dim on a toggle change.

- [ ] **Checklist (controller):** changing the period sends no request from this section, and with the period on 30d the section sends none of its own; toggling "Threat news only" refetches `/api/dashboard?days=30` and changes the subtitle and "Mentions in threat news". **Dates:** with the browser zone set to UTC+7 and to UTC−8 the last bar is the date part of `generated_at` and the 30 labels are consecutive days; a `timeline` of three entries still draws 30 bars. Three bars highlighted in the destructive tone, with the visually hidden "Highest: …" text naming the same three; all-zero → the empty sentence. Ransomware: up to five groups, "Other" = total minus the rows, hidden at 0, group names link to the entity. Industries: no "General", four + "Other", swatches equal the bar segments, the column sums to 100 (also with one and with two industries), names link to the `identity` entity, the footnote appears when `industry_unspecified` is above 0. Techniques: five rows, "Show all 10" expands and collapses, ids in `font-code` link to the technique, the denominator footnote prints. `/api/dashboard` forced to 500 → three error panels, the ransomware card fine, one "Retry" restores all three.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard month charts for incidents, ransomware groups, industries and techniques`

### Task 21: CVE watchlist (6.6 CVE watchlist; P12, C12; DB13)

**Files:**
- Modify: `apps/web/src/components/dashboard/cve-watchlist.tsx`

**Interfaces:**
- Consumes: `useCveExposure(days, 4)`, `periodInfo`, `Table`, `Chip`, `StatePanel`, `PanelError`.
- `CveWatchlist({ period })`: `<h2>` "CVE watchlist", subtitle "Open CVEs in your tech stack, KEV first", right-hand `Link` "{open_critical} open critical · View all →" to `/cve`. `Table framed` with `table-fixed` and a `<colgroup>` of 18% | 26% | 8% | 10% | 8% | 14% | 16%; the seven cells per the spec 6.6 list (CVE a `Link` to `/cve?search={cve_id}` in `font-code`; CVSS one decimal; "public" in `text-destructive-text`; `Chip kind="cve" value="kev"`; "no ticket" in `text-warning-text`; "{ticket_age_days} d"; "–" for every missing value). Footer line "{closed_in_period} tickets closed {suffix}" + " · mean {mean_days_to_close} days to close" when the mean is not `null`. Empty: `StatePanel variant="empty"` "No open CVE in your tech stack" inside the card, footer kept. Error: `PanelError` "Could not load the CVE watchlist". No "closed" chip. Rows have no `onClick`.

- [ ] **Checklist (controller):** four rows in KEV-then-CVSS order equal to `GET /api/dashboard/cve-exposure?limit=4`; one request shared with "By the numbers" (same key); every "–" case; the link opens `/cve?search=CVE-…`; the footer follows the period ("since yesterday" … "of all time") and omits the mean when null; the empty client shows the empty panel with the footer; columns hold their widths with a long product name (truncated, not wrapping the row); 500 → the panel error with the server text; the only focusable elements in a row are its links.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard cve watchlist table with ticket age and the closed-tickets line`

### Task 22: "More" (6.7 More; D6, P14; DB9, DB12, DB14, DB15, DB18)

**Files:**
- Modify: `apps/web/src/components/dashboard/more-section.tsx` (lift the chart wiring from `page.tsx:200-296` and `overview-cards.tsx:194-353`)

**Interfaces:**
- Consumes: `useDashboardStats(days, threatOnly)`, `useDashboardRansomware(days)`, `useDashboardAttention(days)`, `useDashboardTrending(days, TREND_KINDS)`, `useTaStats(enabled)`, `useNewestCluster(enabled)`, `Disclosure`, `MapCard`, `ChartCard`, `DashboardSectionLabel`, `TimelineChart`, `HorizontalBarChart`, `BreakdownList`, `PanelError`, `useCan`.
- `MoreSection({ period, threatOnly })`: `Disclosure title="More" headingLevel={2} printOpen` controlled, closed by default; `opened` (set once on first open, never reset) gates the body and the two extra queries: `useTaStats(opened && can("view_ta"))`, `useNewestCluster(opened && can("view_intel"))`. Body `lg:grid-cols-12`, the four panels of the spec 6.7 table with English titles and notes: "Articles over time" (`TimelineChart`, secondary series "Incidents"), "Ransomware victims per week" (`weekly`, `emphasizeLast`, note "{total} victims · {apac} in APAC"), "Your context" (a `dl`: "Watchlist matches", "PIRs with new articles", "Actors in the news" with "{n} new this period" = trending items of kind `actor` with `is_new`, and with `view_intel` "Newest campaign cluster" as a `Link` "{cluster_name} · {size} articles" → `/intelligence/campaign-clusters` or "No campaign cluster yet."), "Threat Actor Room" (`view_ta` only; aside "All time. The period filter does not apply here."; "APT Groups by Source", "Tracked APT Groups in the News"). A panel without its permission is not rendered. Each panel: skeleton, and `PanelError` "Could not load {panel title in lower case}".

- [ ] **Checklist (controller):** closed on load and no `/api/ta/stats` or `/api/clusters/recent` request until first opened; closing and reopening sends nothing new; the two charts follow period and toggle as the table says; "Your context" numbers equal the hero's; the `view_news`-only role sees no Threat Actor Room and no cluster line and sends neither request; `/api/ta/stats` forced to 500 fails only that panel; print preview shows "More" open; the heading is an `<h2>`; keyboard opens and closes it; charts readable in light and dark.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard more section keeps the timeline, weekly ransomware chart, client context and threat actor room`

### Task 23: LLM banner and removal of the old page parts (6.7 LLM gateway down; 6 Files; D17, P10, C14)

**Files:**
- Modify: `apps/web/src/components/dashboard/dashboard-view.tsx`, `apps/web/src/components/dashboard/stat-box.tsx` (only if `rg` shows `StatBox` or `Delta` without an importer)
- Delete: `apps/web/src/components/dashboard/signal-hero.tsx`, `dashboard-filters.tsx`, `overview-cards.tsx` (after `rg "signal-hero|dashboard-filters|overview-cards|SignalHero|DashboardFilterBar" apps/web/src` shows no importer)

**Interfaces:**
- Consumes: `useLlmQueue(can("view_ops"))`, `Notice`, `fmtTime`.
- In `DashboardView`, between the header and `<NeedsAction>`: when the query succeeded and `breaker !== "closed"`, `Notice tone="warning"` with the title, body (both counts, and " Next retry {fmtTime(retry_at)}." when `retry_at` is set) and `action` link "Open Data health" → `/data-health`, verbatim from spec 6.7. Any error, a closed breaker or no `view_ops`: nothing is rendered and nothing is logged.
- Kept: `stat-box.tsx` (`DashboardSectionLabel`, `MapCard`, `ChartCard`, `PanelError`), `charts.tsx`, `breakdown-list.tsx`. Pre-existing dead exports are reported, not deleted.

- [ ] **Checklist (controller):** with the breaker forced open (three failed `classify` rows in `llm_calls`) a `view_ops` user sees the banner with both counts and the retry time, and the link opens Data health; the `view_news`-only role sees no banner and sends no `/api/data-health`; a closed breaker shows nothing; `/api/data-health` forced to 500 shows nothing and no error text; the Network panel shows the request once per page load and none on a timer over three minutes; `half_open` also shows the banner; `rg -n "signal-hero|dashboard-filters|overview-cards" apps/web/src` is empty; the Exec pages that import `stat-box` and `charts` still build.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): dashboard llm queue banner for ops users, old dashboard components removed`

### Task 24: States and permissions sweep (6 constraints 1-17, 6.7, 6.8, 6.9)

**Files:**
- Modify: any file from Tasks 10-23 that the greps below flag

- [ ] **Sweep** (paths `D` = `apps/web/src/components/dashboard apps/web/src/lib/dashboard "apps/web/src/app/(app)/dashboard"`): `rg -n "if \(error\) throw|HTTP \$\{" $D apps/web/src/components/newsroom/rubric-queries.ts` none; `rg -n "useQuery" $D` and confirm each has `retry: noClientRetry`; `rg -n "refetchInterval" $D` none; `rg -n "id-ID|usePageTitle|font-mono|asChild|backdrop-blur|window_label|\.brief\b|incident_only" $D` shows only the `incident_only` query parameter of `useDashboardStats`; `rg -n "Date\.now\(\)|new Date\(" $D` only inside a `queryFn`, the `useSyncExternalStore` snapshot of the h1 and `period.ts` helpers called from a `queryFn`, never in render and never `new Date(<date string>)` (Review Focus 4); `rg -n "router\.(replace|push)" $D` shows the one guarded `replace` in `dashboard-view.tsx` and the map's `push`; `rg -n "fetch\(" $D` none (no raw proxy call; a later one must use `proxyFetch`); `rg -n "onClick" $D` shows handlers on buttons only; `rg -n "<Chip" apps/web/src/components/dashboard/needs-action.tsx` none; every `table-fixed` has a `<colgroup>`; `rg -n "Klien|Artikel|hari|Belum|Gagal|baru\b" $D` empty (no Indonesian copy left); every `PanelError` title is one of the spec 6.7 table.
- [ ] **Permissions:** walk as superadmin, analyst, a role with only `view_news` and a role without it: requests and panels match the spec 6.8 table exactly (`/api/techstack` only with `view_cve`; `/api/ta/*` only with `view_ta`; `/api/clusters/recent` only with `view_intel`; `/api/data-health` only with `view_ops`); the gate prints the role.
- [ ] **Retry and states:** each of the eleven endpoints stopped in turn (500 from a local patch) shows that panel's error with the server text and a working "Retry" while every other panel renders; a 403 and a 404 are requested once; an empty-body 502 shows the error state; a period or toggle change dims old content and blanks nothing (DB19).
- [ ] **Keyboard and structure:** tab order period control, toggle, hero rows, view switch, map points, article buttons, chips, "Show all 10", table links, "More"; focus rings visible in both themes; one h1; headings h2 per section and h3 per card; no nested interactive element in a hero row, an article row or a table row (accessibility tree).
- [ ] **Feature walk:** DB1-DB20 of spec 6.9, each reachable in its new home; write the checklist into the PR description draft, with the re-homed and the dropped ones (DB4, DB7) noted, and list the flagged choices P1-P21 and the frame deviations of spec 9 for the reviewer.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `fix(web): consistent states, permission gates and copy across the dashboard`

### Task 25: Docs, CHANGELOG and prod-upgrade notes (4.8, S3)

**Files:**
- Modify: `CHANGELOG.md` (extend `## [0.8.16] - 2026-11-08`), `docs/prod-upgrade/0.8.16.md`, `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` (its `## 0.8.16` section, line 365 on), `docs/ARCHITECTURE.md:185` (the `persist` step). Not `docs/PROGRESS.md`.

- [ ] **CHANGELOG (Indonesian):** keep the header paragraph (add one clause for the Dashboard). `### Ditambahkan` and `### Diubah`: the items of spec 4.8, in its wording. After the "**Catatan 0.8.16 (Access):**" line: "**Catatan 0.8.16 (Dashboard):** migrasi `d9f2b6a4c1e7` menambah kolom nullable `articles.summary`, tanpa backfill, tanpa key `.env` baru; artikel lama tidak punya ringkasan."
- [ ] **Prod upgrade (both files, English, extend the existing 0.8.16 section; do not touch the items of earlier sub-projects):** *Migrations*: "Two additive migrations" becomes three, adding the `d9f2b6a4c1e7` paragraph of spec 4.8 (the `ALTER TABLE`, catalog-only, no rewrite, no backfill, no index) and changing the closing sentence to "After deploy `alembic_version` is `d9f2b6a4c1e7`"; note from spec 9 that the `ALTER` waits behind a long transaction on `articles` and that rerunning the deploy retries it. *Settings*: none. *Behaviour change*, *Contract*, *Post-deploy check* (the three SQL checks and the dek under the lead story) and *Rollback* (image rollback only; the column stays; a manual `alembic downgrade -1` drops the excerpts) as spec 4.8 words them.
- [ ] **ARCHITECTURE:** the `persist` step gains "stores the capped summary excerpt in `articles.summary`".
- [ ] **Verify:** `uv run python -c "from cti_api.routers.changelog import _parse; print(_parse()[0]['version'])"` prints `0.8.16`; `rg -n "c4e8a1f2b9d6" docs/prod-upgrade/0.8.16.md docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` no longer names it as the final `alembic_version`; `git diff --stat` lists only the four files.
- [ ] Commit `docs(release): note the Dashboard redesign and the articles.summary migration in 0.8.16`

### Task 26: Final verification (spec 8)

- [ ] **Backend:** `uv run pytest tests/unit/test_summarize_dek.py tests/unit/test_trending.py -q`; with Docker `uv run pytest tests/integration/test_dashboard_overview_api.py tests/integration/test_dashboard_overview_query.py tests/integration/test_dashboard_overview_service.py tests/integration/test_pipeline_tier1_db.py tests/integration/test_articles_router_snapshot.py tests/integration/test_newsroom_api.py tests/integration/test_migrations_match_models.py -q`; then `uv run pytest tests/integration` and `uv run pytest tests/unit tests/contract packages` with the known deselects. The named tests of Tasks 1-8 pass; `git diff origin/Dev --stat -- tests/integration/__snapshots__` shows only article-carrying files, each diff the two new keys.
- [ ] **Migration:** `uv run --no-sync alembic heads` prints `d9f2b6a4c1e7 (head)` only; on the `qafig` database (`source .superpowers/qa/env.sh`): `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` all succeed and `\d articles` shows `summary | text |` nullable.
- [ ] **Static:** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src packages/cti-scraper/src`; `uv run python tools/export_openapi.py && (cd apps/web && pnpm run gen:api) && git diff --exit-code docs/openapi.json apps/web/src/lib/api/schema.d.ts`; `git diff --stat origin/Dev -- .env.example .env.prod.template tests/unit/test_route_permissions.py apps/web/src/components/newsroom/article-modal.tsx` empty.
- [ ] **Web:** stop the dev server on :3010 first; `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit`; `pnpm build`, all exit 0. Pure helpers checked in QA (browser console or a scratch page, not committed): `parsePeriod` with `null`, "7", "1", "all", "abc", "0"; `priorityTone` with 69, 70, 89, 90, 176; the industries percentages sum to 100; the 30-bar padding with a `timeline` of 3 entries.
- [ ] **Visual and behaviour (controller, local `qafig` stack per `.superpowers/qa/README.md`: `source .superpowers/qa/env.sh`, API via uvicorn on :8010, web via `pnpm dev --port 3010`; synthetic data from a scratch `.superpowers/qa/seed5a.py` whose values match the API `Literal`s: the seed list of spec 8, that is two clients (one country, tech stack, two watched actors, a PIR; and none of them), a client with three countries, open KEV rows on three products with one false positive, ransomware victims in the current and previous 7 days with and without an industry, an actor named like a victim group, malware, tool and CVE mentions, articles with and without `summary`, one first seen two hours ago, one `llm_ttp_status = "pending"`, one with `priority_score` 131, and a role with only `view_news`):** the six check groups of spec 8 "Visual and behaviour" in full (Period; Hero; Lead and feed; Charts and table; States; Two clients). The Review Focus lines 1-5 are re-run here end to end, whatever earlier tasks reported. Screenshots at 1440 and 1000 px, light and dark, against frames 2 / 702 and 32816 / 33283. Keyboard pass; the tab title reads "Dashboard · {PLATFORM_NAME}"; print preview shows "More" open; no hydration warning in the console; `ArticleModal` opened from the lead and from Must read readable in light and dark.
- [ ] **Delivery:** report results; the commits per backend item, the contract, and each page part happened in earlier tasks; merge into `origin/Dev` under the standing approval. On dev 172.25.1.77: `alembic upgrade head` through the normal deploy, then read-only checks of `/dashboard` with the `claude` account (signed in by the user). Nothing on dev is written by hand.
- [ ] No commit unless a fix was needed (then a `fix(...)` commit per fix).

## Spec coverage

| Spec section | Tasks |
|---|---|
| 2 S1, S2 | Global Constraints, 24 (features kept) |
| 2 S3 | Global Constraints, 5, 25 |
| 2 D1 | 5-8 (B-N1, B-N2 ship here) |
| 2 D2 | Global Constraints, 13-23, 24 (grep) |
| 2 D3 | 5, 6, 7, 8, 16, 18 |
| 2 D4 | 8, 10 (`articleWhen`), 16, 18 |
| 2 D5 | 10, 13, 20 |
| 2 D6 | 13, 14, 22 |
| 2 D7 | 1, 2, 3, 4, 20 |
| 2 D8 | 4, 19 |
| 2 D10 | 11, 16, 18 |
| 2 D17 | 14, 23, 13 (`PanelError`), 16-22 |
| 2 D19 | 11, 16, 18 |
| 2 P1, P2 | 10, 13, 14 |
| 2 P3 | 3 |
| 2 P4 | 5, 6, 7 |
| 2 P5 | 17 |
| 2 P6, P7 | 10, 16, 18 |
| 2 P8 | 12, 15 |
| 2 P9 | 14 |
| 2 P10 | 10 (`useLlmQueue`), 16, 18, 23 |
| 2 P11 | 19 |
| 2 P12 | 21 |
| 2 P13 | 20 |
| 2 P14 | 10, 22 |
| 2 P15 | 13 |
| 2 P16 | 11, 16 |
| 2 P17 | 13 |
| 2 P18 | 11, 18 |
| 2 P19 | 4 |
| 2 P20 | 20 |
| 2 P21 | 10 |
| 3 C1, C2, C3 | 13, 22, 24 |
| 3 C4, C5, C6 | 3, 14 |
| 3 C7 | 8, 10, 16 |
| 3 C8 | 17 |
| 3 C9, C11 | 20 |
| 3 C10, C23 | 13 (`PanelError`), 16-22, 24 |
| 3 C12 | 1, 21 |
| 3 C13, C14 | 14, 23 |
| 3 C25 | 11 |
| 3 C28 | 6, 16, 18 |
| 3 C29 | 13 |
| 3 map, byline, sparkline, "previous 7 days" notes | 15, 16, 17, 14 |
| 4.1 | 1 |
| 4.2 | 3 |
| 4.3 | 4 |
| 4.4 | 2 |
| 4.5 | 5, 6, 7, 8 |
| 4.6 | 8 |
| 4.7 | 9 |
| 4.8 | 25 |
| 5 | 5, 26 |
| 6 global rules, constraints 1-17 | Global Constraints, 10-24 |
| 6 Files | 10-13, 23 |
| 6.1 | 10, 13 |
| 6.2 | 14 |
| 6.3 | 12, 15 |
| 6.4 | 10, 11, 16, 17 |
| 6.5 | 18, 19 |
| 6.6 | 20, 21 |
| 6.7 | 13 (no access, panel error), 14 (no data), 16-22 (loading, errors), 22 (More), 23 (LLM banner) |
| 6.8 | 10, 11, 12, 13, 24 (permission table) |
| 6.9 | 24 |
| 7 | Global Constraints (excluded items not planned) |
| 8 | 9, 26 |
| 9 | Review Focus, 3 (cache, sequential queries), 4 (ransomware name match docstring), 6 (cap), 7 (both persist paths), 14 (period wording), 15 (APAC default), 23 (one request), 25 (runbook lock note) |
