# Login, Dashboard and Newsroom Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Login, Dashboard and Newsroom pages of `apps/web` to the approved mockups, and add the API endpoints that feed the new dashboard and newsroom sections.

**Architecture:** One PR, one commit per task, in five parts: Login (web), Dashboard API, Dashboard web, Newsroom API, Newsroom web. New API logic lives in two services (`trending.py`, shared by dashboard and newsroom; `dashboard_overview.py`) on top of new query methods in the existing `cti_core` repositories. The web keeps the current pattern of one `useQuery` per section, so each section loads and fails on its own.

**Tech Stack:** FastAPI + SQLAlchemy async (Python 3.12, uv), pytest + testcontainers; Next.js 16 App Router, TanStack Query, Tailwind, Base UI (shadcn), d3-geo + world-atlas + topojson-client (already installed).

**Spec:** `docs/superpowers/specs/2026-10-23-redesign-login-dashboard-newsroom-design.md`
**Mockups:** https://claude.ai/artifact/879LVfcCxbJ47nZ6tmMoR1 (Login, "Dashboard (A + C)", Newsroom tab "Usulan · N1 + N3")

## Global Constraints

- Theme tokens in `apps/web/src/app/globals.css` do not change; any new color is a token with light and dark values. No `backdrop-blur`. Prose uses theme tokens, not `prose-invert`.
- shadcn/ui is Base UI: `render={<X/>}`, not `asChild`; `SelectItem` children are a single string. Read `apps/web/CLAUDE.md` before touching `components/ui`.
- Next.js 16: read `apps/web/node_modules/next/dist/docs/` before writing route code.
- Data values (CVE IDs, TTP IDs, counts in tables) use `font-code`.
- The login page makes no API call and shows no platform numbers.
- Comments and docstrings in Indonesian, matching the surrounding code; commit messages in English, conventional style, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- After any endpoint or schema change: `uv run python tools/export_openapi.py` then `cd apps/web && pnpm run gen:api`, both outputs committed.
- Every endpoint that returns per-client data resolves the client with `effective_client_id(user, x_client_id)` (`cti_api.deps`).
- Periods: `days` query param, `ge=1, le=3650`, empty = all time; the window is `today - days` to today, the previous window is the same length right before it (as `article_dashboard._fetch_dashboard_stats`).
- One PR for the whole redesign, one commit per task. The release is a single commit at the end (Task 12): version `0.8.1` in the root and every package `pyproject.toml`, each `__version__`, `apps/web/package.json`, `uv.lock`, `docs/openapi.json` and the health snapshot, plus one `CHANGELOG.md` entry (Indonesian) with header `## [0.8.1] - YYYY-MM-DD`. No task before Task 12 bumps the version.
- Local tooling: node is under fnm and not on PATH by default; macOS has no `timeout`.

## Decisions made while planning (deviations from the spec text)

1. **Map data**: the spec planned a committed land mask and centroid table. `world-atlas/countries-110m.json`, `d3-geo` and `i18n-iso-countries` are already dependencies (used by `country-map.tsx`), so `world-dots.tsx` builds the dot mask and the centroids at runtime from them. No static geo data is added.
2. **APAC for ransomware**: the Newsroom APAC panel filters by `news_type="apac"`, not by countries, so there is no country list to reuse. A constant `APAC_COUNTRY_CODES` is added in `dashboard_overview.py` (see Task 5).
3. **PIR hits**: cached for 900 s per (client, days) from the start, the same TTL as `spike.py`, instead of measuring first. Running `list_articles_for_pir` once per active PIR is N queries per dashboard load.
4. **"Open" CVE**: `cve_tracker` has no ack column; the ack and closure fields live on `cve_tickets`. A CVE is open when it has no ticket or its ticket has `closure_date IS NULL`.
5. **Side sheet**: there is no sheet component; Task 9 adds `components/ui/sheet.tsx` on Base UI Dialog.

## Review Focus

1. **Client with no tech stack entries** (`visible_names` returns `None`): CVE exposure must fall back to "no tech filter" exactly as `/api/cve/stats` does, not to zero. Test in Task 4.
2. **Client with no countries**: the map shows no rings, "ransomware in client scope" is 0 and the attention row still renders. Test in Task 6.
3. **"All time" period** (`days` empty): trending must use the last 7 days vs the 7 before and say so in `window_label`, not compare all history against nothing. Test in Task 3.
4. **Country codes the map cannot place** (`UK`, `EL`, unknown codes): normalised with the same alias table as `country-map.tsx` (`UK→GB`, `EL→GR`), and codes with no centroid are skipped without breaking the canvas. Covered by the manual check in Task 7.
5. **Newsroom search with no results**: every block shows its empty state, and the topics strip is hidden rather than showing four empty cards. Manual check in Task 11.

---

## Part 1: Login

### Task 1: World dot map component

**Files:**
- Create: `apps/web/src/components/world-dots.tsx`

**Interfaces:**
- Produces:
  ```ts
  export interface WorldDotPoint {
    code: string;            // ISO alpha-2 from the API, normalised inside (UK→GB, EL→GR)
    weight: number;          // >= 0, drives the glow radius
    tone: "incident" | "ransomware";
    ring?: boolean;          // client country
    label: string;           // accessible name, e.g. "Singapore: 31 insiden, 4 korban ransomware"
  }
  export function WorldDots(props: {
    points?: WorldDotPoint[];
    className?: string;
    onPointFocus?: (p: WorldDotPoint | null) => void;   // hover/focus for the tooltip
    onPointSelect?: (p: WorldDotPoint) => void;         // click / Enter
  }): JSX.Element;
  ```

- [ ] **Step 1: Implement `WorldDots`**

  Canvas fills its parent (`absolute inset-0`). Build once per mount with `useMemo`: project `world-atlas/countries-110m.json` (`topojson-client` `feature`) with `geoEquirectangular` fitted to the canvas size, draw the land to an offscreen canvas, then sample every 9 CSS px and draw a 1.4 px dot where the sample is land. Country centroids: `geoCentroid` per feature, keyed by `i18n-iso-countries` `numericToAlpha2(feature.id)`. Colors from `getComputedStyle(document.documentElement)`: dots `--hero-foreground` at 16% alpha, incident points `--hero-accent`, ransomware points `--hero-eyebrow`, rings `--hero-foreground`. Redraw on resize (`ResizeObserver`) and when the `class` of `<html>` changes (`MutationObserver`, theme switch). Point radius `4 + 14 * weight / maxWeight`, glow radius 2.2× with a radial gradient. Points are not canvas-only: render one visually transparent `<button>` per point, absolutely positioned on the centroid (min 24 × 24 px), `aria-label={label}`, calling `onPointFocus` on hover/focus/blur and `onPointSelect` on click. Points whose code has no centroid are skipped. With `prefers-reduced-motion` nothing animates (there is no animation anyway; keep it that way).

- [ ] **Step 2: Typecheck and lint**

  Run: `cd apps/web && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm lint`
  Expected: no errors.

- [ ] **Step 3: Commit**

  ```bash
  git add apps/web/src/components/world-dots.tsx
  git commit -m "feat(web): world dot map component for login and dashboard"
  ```

### Task 2: Login page layout

**Files:**
- Modify: `apps/web/src/app/login/page.tsx`

**Interfaces:**
- Consumes: `WorldDots` from Task 1 (no `points`).

- [ ] **Step 1: Rewrite the layout, keep `LoginForm` logic**

  Keep `safeRedirect`, the `useAuth().login` flow, error `role="alert"`, the pending label and the `<Suspense>` wrapper exactly. New layout: `main` is a grid, `md:grid-cols-[1.1fr_1fr]`, `min-h-dvh`. Left panel `relative overflow-hidden bg-hero text-hero-foreground` with `<WorldDots className="opacity-100" />` behind the content, loaded with `next/dynamic` and `ssr: false` so world-atlas is not in the first paint. Copy, verbatim:
  - Brand row: `<BrandMark />` + `{PLATFORM_NAME}`
  - Eyebrow (`text-hero-eyebrow`, uppercase, `tracking-widest`, 11 px): `Cyber threat intelligence`
  - Headline (32 px, 750, `text-balance`, max 16ch): `Tahu lebih dulu. Bertindak lebih cepat.`
  - Three lines (`text-hero-muted`, bullet dot `bg-hero-accent`):
    `Berita ancaman dari banyak sumber, dirangkum dan diberi skor.` /
    `CVE dicocokkan dengan tech stack organisasi Anda.` /
    `Aktor, TTP dan IOC dipetakan ke MITRE ATT&CK.`
  - Footer (`text-hero-muted`, 11.5 px): `Akses terbatas untuk pengguna terdaftar`
  - Right panel form: heading `Masuk`, helper `Gunakan akun Vareon Anda.`, labels `Username` / `Password`, button `Sign in` (pending `Signing in...`), footer line `Lupa password? Hubungi admin platform.`
  Below `md`: the hero panel collapses to brand + eyebrow + headline only (`hidden md:block` on the three lines and the footer), above the form.

- [ ] **Step 2: Verify build and that the page makes no API call**

  Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm lint && pnpm build`
  Expected: build passes, `/login` still prerendered as static.
  Then `pnpm dev`, open `http://localhost:3000/login` in the browser pane, read the network list: no request to `/api/proxy/*` before submitting. Check light and dark, 1440 px and 375 px.

- [ ] **Step 3: Commit**

  ```bash
  git add -A apps/web && git commit -m "feat(web): redesigned login page"
  ```

---

## Part 2: Dashboard API

### Task 3: Trending service

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/dashboard.py` (`daily_entity_counts`)
- Create: `apps/api/src/cti_api/services/trending.py`
- Test: `tests/unit/test_trending.py`, `tests/integration/test_dashboard_query.py` (add one test)

**Interfaces:**
- Consumes: `AsyncDashboardRepo.daily_entity_counts(dimension=..., posted_on_start=..., ...)`.
- Produces:
  ```python
  # cti_core repo: dimension now also accepts "ttp"; for "ttp" the entity is "T1566.002|Spearphishing Link"
  # (ttp_id and ttp_name joined by "|"), split again by the service.

  @dataclass(frozen=True)
  class TrendItem:
      kind: Literal["actor", "ttp"]
      name: str               # actor name, or TTP name
      ttp_id: str | None
      count: int
      prev_count: int
      change_pct: int | None  # None when prev_count < 3
      is_new: bool            # prev_count == 0
      daily: list[int]        # one bucket per day of the current window, oldest first

  def rank_trends(
      current: Mapping[tuple[str, str, str | None], list[int]],   # (kind, name, ttp_id) -> daily counts
      previous: Mapping[tuple[str, str, str | None], int],
      *, min_count: int = 3, limit: int = 10,
  ) -> list[TrendItem]

  async def get_trending(
      session: AsyncSession, *, days: int | None,
      countries: Sequence[str] | None = None, news_types: Sequence[str] | None = None,
      search: str | None = None, limit: int = 10,
  ) -> dict[str, Any]   # {"items": [TrendItem as dict], "window_days": int, "window_label": str, "generated_at": str}
  ```

- [ ] **Step 1: Write the failing unit tests** (`tests/unit/test_trending.py`)

  ```python
  def test_change_pct_only_with_enough_baseline():
      items = rank_trends({("actor", "Qilin", None): [5, 6, 12]}, {("actor", "Qilin", None): 5})
      assert items[0].count == 23 and items[0].prev_count == 5 and items[0].change_pct == 360
      items = rank_trends({("actor", "X", None): [2, 2]}, {("actor", "X", None): 2})
      assert items[0].change_pct is None and items[0].is_new is False

  def test_new_entity_flagged():
      items = rank_trends({("ttp", "Spearphishing Link", "T1566.002"): [1, 1, 3]}, {})
      assert items[0].is_new is True and items[0].change_pct is None and items[0].ttp_id == "T1566.002"

  def test_below_min_count_dropped_and_ranked_by_absolute_rise():
      items = rank_trends(
          {("actor", "A", None): [1, 1], ("actor", "B", None): [10], ("actor", "C", None): [6]},
          {("actor", "B", None): 9, ("actor", "C", None): 0},
      )
      assert [i.name for i in items] == ["C", "B"]   # C rose 6, B rose 1, A (2) under min_count

  def test_falling_entities_excluded():
      assert rank_trends({("actor", "D", None): [4]}, {("actor", "D", None): 9}) == []
  ```
  `change_pct = round((count - prev_count) * 100 / prev_count)`. Only items with `count - prev_count > 0` are kept. Ties broken by `count` desc, then `name`.

- [ ] **Step 2: Run, verify failure**

  Run: `uv run pytest tests/unit/test_trending.py -q`
  Expected: FAIL, `ModuleNotFoundError: cti_api.services.trending`.

- [ ] **Step 3: Implement `rank_trends` and `TrendItem`**

- [ ] **Step 4: Run, verify pass**

  Run: `uv run pytest tests/unit/test_trending.py -q` → PASS.

- [ ] **Step 5: Extend `daily_entity_counts` with `dimension="ttp"` and add filters**

  Add `"ttp": (ArticleTTP, func.concat(ArticleTTP.ttp_id, "|", ArticleTTP.ttp_name))` to the mapping, and keyword args `posted_on_end: date | None = None`, `countries: Sequence[str] | None = None`, `news_types: Sequence[str] | None = None`, `search: str | None = None` (title `ILIKE`), applied only when given so `/api/spikes` and `exec_dashboard` behave as before. Add `test_daily_entity_counts_ttp_dimension` to `tests/integration/test_dashboard_query.py` using the existing `_seed_articles` (expects `(today, "T1059|Command Scripting", 1)`).

- [ ] **Step 6: Implement `get_trending`**

  Window: `days` given → current = `[today - days, today]`, previous = `[today - 2*days, today - days)`; `days is None` → 7 and 7, `window_label = "7 hari terakhir vs 7 hari sebelumnya"`, else `f"{days} hari terakhir vs {days} hari sebelumnya"`. Two calls per dimension (`threat_actor`, `ttp`), bucket the current rows into `daily` by day index. Cache 900 s keyed on all args plus `date.today()` in a module dict `_CACHE`, like `article_dashboard`; add `trending._CACHE.clear()` to `_clear_in_process_caches` in `tests/integration/conftest.py`. Add `test_get_trending_all_time_uses_7_day_window` (integration, `async_db_session`): seed one actor article today, call with `days=None`, assert `window_days == 7` and the label above.

- [ ] **Step 7: Run and commit**

  Run: `uv run pytest tests/unit/test_trending.py tests/integration/test_dashboard_query.py -q` → PASS.
  ```bash
  git add packages/cti-core apps/api/src/cti_api/services/trending.py tests
  git commit -m "feat(api): trending service for actors and TTPs over two windows"
  ```

### Task 4: Repository queries for the dashboard overview

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/dashboard.py`
- Modify: `packages/cti-core/src/cti_core/db/repositories/ransomware.py` (`AsyncRansomwareVictimRepo`)
- Test: `tests/integration/test_dashboard_overview_query.py`

**Interfaces:**
- Produces (all `async`, all dates are `datetime.date`):
  ```python
  # AsyncDashboardRepo
  async def incident_country_profile(self, *, posted_on_start: date | None) -> list[tuple[str, int, str | None, str | None]]
      # (country_code, confirmed incident articles, top actor or None, top non-"General" industry or None)
  async def watchlist_hit_count(self, *, client_id: str, posted_on_start: date | None) -> int
      # distinct articles mentioning a name from ta_watchlist of the client
  async def cve_exposure(self, *, client_id: str, tech: Sequence[str] | None, exclude_cve_ids: Sequence[str] | None, limit: int = 3)
      -> list[tuple[CveTracker, CveTicket | None]]
      # open CVEs (no ticket, or ticket.closure_date IS NULL), order: cisa_kev desc, cve_score desc nulls last
  async def cve_exposure_counts(self, *, client_id: str, tech: Sequence[str] | None, exclude_cve_ids: Sequence[str] | None)
      -> dict[str, int]   # keys: open_critical, open_kev, kev_without_ticket
  async def tickets_closed(self, *, client_id: str, since: date | None) -> tuple[int, float | None]
      # (count with closure_date >= since, mean days closure_date - created_at::date, 1 decimal)

  # AsyncRansomwareVictimRepo
  async def weekly_counts(self, *, weeks: int = 8) -> list[tuple[date, int]]   # Monday-start weeks, oldest first, zero-filled
  async def summary(self, *, since: date | None, apac_codes: Collection[str], client_codes: Collection[str])
      -> dict[str, Any]   # {"total", "apac", "client_scope", "undated", "top_groups": [(name, count)] top 3, "by_country": {code: count}}
  ```
  Victim date = `coalesce(discovered, published)`; `undated` counts rows where both are NULL (never filtered by `since`). "Critical" = `cve_severity` upper-cased equals `"CRITICAL"`. `tech=None` means no tech filter; `tech=[]` means nothing matches (same contract as `_active_tech_names`).

- [ ] **Step 1: Write the failing integration tests** (`tests/integration/test_dashboard_overview_query.py`, `pytestmark = pytest.mark.asyncio`, `async_db_session`)

  - `test_incident_country_profile_counts_confirmed_only`: seed two articles in `ID` (one confirmed with actor `Qilin`, industry `Finance`), one unconfirmed; expect `[("ID", 1, "Qilin", "Finance")]`.
  - `test_watchlist_hits_scoped_to_client`: clients `default` and `other`; watchlist `Qilin` only for `default`; one article with `Qilin`; expect `1` for `default`, `0` for `other`.
  - `test_cve_exposure_orders_kev_first_and_skips_closed`: three CVEs for `default` (KEV 9.1, non-KEV 9.8, KEV 9.8 with a ticket having `closure_date`); expect the list `[KEV 9.1, non-KEV 9.8]` and counts `open_kev == 1`, `kev_without_ticket == 1`.
  - `test_cve_exposure_tech_none_vs_empty`: `tech=None` returns the CVE, `tech=[]` returns nothing.
  - `test_tickets_closed_mean_days`: two tickets closed 2 and 4 days after creation within the window → `(2, 3.0)`.
  - `test_ransomware_summary_and_weekly`: victims in `SG` (today), `US` (today), one with no dates; `apac_codes={"SG"}`, `client_codes={"SG"}`; expect `total == 2`, `apac == 1`, `client_scope == 1`, `undated == 1`; `weekly_counts(weeks=8)` has 8 entries and the last one is `2`.

  Seed with the existing repos (`AsyncArticleRepo.upsert/set_enrichment`, `AsyncClientRepo.create`, `AsyncTARepo.add_to_watchlist`) and plain model inserts for `CveTracker`, `CveTicket`, `RansomwareVictim` (follow `tests/integration/test_cve_ticket_query.py` for ticket fields that are required).

- [ ] **Step 2: Run, verify failure**

  Run: `uv run pytest tests/integration/test_dashboard_overview_query.py -q`
  Expected: FAIL with `AttributeError` on the new methods.

- [ ] **Step 3: Implement the methods** in the two repository files, with Indonesian docstrings that state the definitions above.

- [ ] **Step 4: Run, verify pass; run mypy**

  Run: `uv run pytest tests/integration/test_dashboard_overview_query.py -q` → PASS.
  Run: `uv run mypy packages/cti-core/src packages/cti-scraper/src` → no errors.

- [ ] **Step 5: Commit**

  ```bash
  git add packages/cti-core tests/integration/test_dashboard_overview_query.py
  git commit -m "feat(core): dashboard overview queries for map, CVE exposure, watchlist and ransomware"
  ```

### Task 5: Dashboard overview service and brief

**Files:**
- Create: `apps/api/src/cti_api/services/dashboard_overview.py`
- Test: `tests/unit/test_dashboard_brief.py`

**Interfaces:**
- Consumes: Task 3 `get_trending`, `TrendItem`; Task 4 repo methods; `AsyncTechStackRepo.visible_names`, `AsyncCveFalsePositiveRepo.list_cve_ids`, `AsyncClientRepo.get`, `AsyncPIRRepo.list_active_by_client`, `AsyncPIRRepo.list_articles_for_pir`.
- Produces:
  ```python
  APAC_COUNTRY_CODES: frozenset[str]  # AU BD BN BT CN FJ HK ID IN JP KH KR LA LK MM MN MO MV MY NP NZ PG PH PK SG TH TL TW VN

  def build_brief(*, top_trend: TrendItem | None, kev_in_stack: int, incidents: int,
                  prev_incidents: int | None, drivers: Sequence[str]) -> dict[str, str]  # {"headline", "detail"}

  async def get_map(session, *, client_id: str, days: int | None) -> dict[str, Any]
  async def get_attention(session, *, client_id: str, days: int | None) -> dict[str, Any]
  async def get_ransomware(session, *, days: int | None) -> dict[str, Any]
  async def get_cve_exposure(session, *, client_id: str, days: int | None) -> dict[str, Any]
  ```
  Return shapes are exactly the response models of Task 6.

- [ ] **Step 1: Write the failing brief tests** (`tests/unit/test_dashboard_brief.py`)

  ```python
  def test_brief_with_trend_and_kev():
      t = TrendItem(kind="actor", name="Qilin", ttp_id=None, count=23, prev_count=5,
                    change_pct=360, is_new=False, daily=[])
      b = build_brief(top_trend=t, kev_in_stack=3, incidents=214, prev_incidents=155,
                      drivers=["Ransomware", "Data breach"])
      assert b["headline"] == "Qilin naik 360% dan 3 CVE KEV cocok dengan tech stack klien."
      assert b["detail"] == "Insiden naik 38% dibanding periode sebelumnya, didorong Ransomware dan Data breach."

  def test_brief_new_trend_no_kev():
      t = TrendItem(kind="ttp", name="Spearphishing Link", ttp_id="T1566.002", count=5,
                    prev_count=0, change_pct=None, is_new=True, daily=[])
      b = build_brief(top_trend=t, kev_in_stack=0, incidents=10, prev_incidents=None, drivers=[])
      assert b["headline"] == "T1566.002 Spearphishing Link baru muncul pada periode ini."
      assert b["detail"] == "10 insiden terkonfirmasi pada periode ini."

  def test_brief_nothing_notable():
      b = build_brief(top_trend=None, kev_in_stack=0, incidents=0, prev_incidents=0, drivers=[])
      assert b["headline"] == "Tidak ada lonjakan atau CVE KEV baru pada periode ini."
      assert b["detail"] == "Belum ada insiden terkonfirmasi pada periode ini."
  ```
  Remaining combinations follow the same pieces: trend part (`"{name} naik {pct}%"`, or `"{name} baru muncul"`, or `"{name} naik"` when `change_pct` is None and not new), KEV part (`"{n} CVE KEV cocok dengan tech stack klien"`), joined with `" dan "`; KEV only → `"{n} CVE KEV cocok dengan tech stack klien."`. Detail: change `round((incidents - prev) * 100 / prev)` when `prev` > 0 using `naik`/`turun`, `"stabil"` at 0%; drivers (max two) appended as `", didorong A dan B."`.

- [ ] **Step 2: Run, verify failure**

  Run: `uv run pytest tests/unit/test_dashboard_brief.py -q` → FAIL (import error).

- [ ] **Step 3: Implement `APAC_COUNTRY_CODES` and `build_brief`; run, verify pass**

  Run: `uv run pytest tests/unit/test_dashboard_brief.py -q` → PASS.

- [ ] **Step 4: Implement the four `get_*` functions**

  - `get_map`: `incident_country_profile` + `RansomwareVictimRepo.summary(...)["by_country"]`, merged per code into `points` (`incidents`, `ransomware_victims`, `top_actor`, `top_industry`), sorted by `incidents + ransomware_victims` desc; `client_countries` from `AsyncClientRepo.get(client_id).countries`.
  - `get_attention`: `cve_exposure_counts` (tech from `visible_names`, FP ids excluded) → `kev_in_stack = open_kev`, `kev_without_ticket`; `summary(...)["client_scope"]`; `watchlist_hit_count`; `pir_hits` = number of `list_active_by_client` PIRs whose `list_articles_for_pir(..., page_size=1)` total > 0 with the PIR's own date window intersected with the period; `brief = build_brief(top_trend=first item of get_trending(days=days), kev_in_stack=..., incidents=confirmed count, prev_incidents=prev confirmed count or None for all time, drivers=top 2 news types of confirmed articles)`. Cache the whole attention payload 900 s per `(client_id, days, date.today())` in `_CACHE`; add `dashboard_overview._CACHE.clear()` to the conftest autouse fixture.
  - `get_ransomware`: `weekly_counts(weeks=8)`, `summary(since=..., apac_codes=APAC_COUNTRY_CODES, client_codes=())` → `weekly`, `top_groups`, `total`, `apac`, `undated`.
  - `get_cve_exposure`: `cve_exposure(limit=3)` + `cve_exposure_counts` + `tickets_closed(since=period start)`; per item `ticket_age_days = today - ticket.created_at.date()` when a ticket exists, `public_poc = poc_available`.
  Each payload gets `generated_at` in the `%Y-%m-%dT%H:%M:%SZ` format used by `spike.py`.

- [ ] **Step 5: Commit**

  ```bash
  git add apps/api/src/cti_api/services/dashboard_overview.py tests/unit/test_dashboard_brief.py tests/integration/conftest.py
  git commit -m "feat(api): dashboard overview service with deterministic brief"
  ```

### Task 6: Dashboard endpoints, schemas and contract

**Files:**
- Create: `apps/api/src/cti_api/schemas/dashboard_overview.py`
- Modify: `apps/api/src/cti_api/routers/articles.py` (new routes next to `/dashboard`)
- Test: `tests/integration/test_dashboard_overview_api.py`
- Regenerate: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`

**Interfaces:**
- Consumes: Task 3 `get_trending`; Task 5 `get_map`, `get_attention`, `get_ransomware`, `get_cve_exposure`.
- Produces (routes, all `GET`, `days: int | None = Query(None, ge=1, le=3650)`, client-scoped ones take `user: AuthedUser = Depends(require_auth)` and `x_client_id: str | None = Header(None)`):

  | Route | Response model | Fields |
  | --- | --- | --- |
  | `/api/dashboard/map` | `DashboardMap` | `points: list[MapPoint]` (`country_code`, `incidents`, `ransomware_victims`, `top_actor: str | None`, `top_industry: str | None`), `client_countries: list[str]`, `generated_at` |
  | `/api/dashboard/attention` | `DashboardAttention` | `kev_in_stack`, `kev_without_ticket`, `ransomware_in_client_scope`, `watchlist_hits`, `pir_hits`, `brief: Brief` (`headline`, `detail`), `generated_at` |
  | `/api/dashboard/trending` | `TrendingResponse` | `items: list[TrendItemOut]` (TrendItem fields), `window_days`, `window_label`, `generated_at` |
  | `/api/dashboard/ransomware` | `RansomwareOverview` | `weekly: list[WeekCount]` (`week_start: date`, `victims`), `top_groups: list[NameCount]`, `total`, `apac`, `undated`, `generated_at` |
  | `/api/dashboard/cve-exposure` | `CveExposure` | `items: list[CveExposureItem]` (`cve_id`, `tech: str | None`, `cvss: float | None`, `cisa_kev`, `ticket_id: str | None`, `ticket_age_days: int | None`, `public_poc`), `open_critical`, `open_kev`, `closed_in_period`, `mean_days_to_close: float | None`, `generated_at` |

  Route order: declare these before any `/dashboard/{...}` path param route (there is none today; keep it that way).

- [ ] **Step 1: Write the failing API tests** (`tests/integration/test_dashboard_overview_api.py`, fixtures `api_client`, `auth_header`, `api_session`)

  - `test_dashboard_endpoints_return_200_and_shape`: call all five with `days=7`; assert status 200 and the top-level keys listed above.
  - `test_attention_is_client_scoped`: two clients; a KEV CVE and a watchlist entry only for `acme`; `auth_header(role="analyst", client_ids=["acme", "other"])`; with `X-Client-ID: acme` expect `kev_in_stack == 1` and `watchlist_hits == 1`; with `X-Client-ID: other` expect both `0`.
  - `test_attention_client_without_countries`: client with no countries → 200, `ransomware_in_client_scope == 0`; map `client_countries == []`.
  - `test_trending_all_time_label`: no `days` → `window_label == "7 hari terakhir vs 7 hari sebelumnya"`.
  - `test_dashboard_requires_auth`: no header → 401 on `/api/dashboard/map`.

- [ ] **Step 2: Run, verify failure**

  Run: `uv run pytest tests/integration/test_dashboard_overview_api.py -q` → FAIL (404).

- [ ] **Step 3: Add the schemas and routes** (routes thin: resolve `cid = effective_client_id(user, x_client_id)`, call the service, return the model).

- [ ] **Step 4: Add confirmed incidents to the existing timeline**

  The "Artikel dari waktu ke waktu" card needs two series. Add `incidents: int = 0` to `TimelinePoint` (`apps/api/src/cti_api/schemas/article.py`), make `AsyncDashboardRepo.article_timeline` also return `count(*) FILTER (WHERE confirmed_incident)` per day, and fill it in `article_dashboard._fetch_dashboard_stats`. Add `test_article_timeline_counts_incidents` to `tests/integration/test_dashboard_query.py` (the seeded data gives today `count == 2`, `incidents == 1`).

- [ ] **Step 5: Run, verify pass**

  Run: `uv run pytest tests/integration/test_dashboard_overview_api.py tests/integration/test_dashboard_query.py tests/integration/test_articles_router_snapshot.py -q` → PASS. The `/api/dashboard` snapshot changes only by the new `incidents` field; update it with `--snapshot-update` and check the diff shows nothing else.

- [ ] **Step 6: Regenerate the contract**

  Run: `uv run python tools/export_openapi.py && cd apps/web && pnpm run gen:api`
  Expected: `docs/openapi.json` and `src/lib/api/schema.d.ts` contain `DashboardAttention`, `CveExposure`, etc.

- [ ] **Step 7: Full fast suite + lint**

  Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest tests/unit tests/contract packages -q` (deselect the two known local-only failures from memory if they appear).
  Expected: PASS.

- [ ] **Step 8: Commit**

  ```bash
  git add apps/api tests docs/openapi.json apps/web/src/lib/api/schema.d.ts
  git commit -m "feat(api): dashboard map, attention, trending, ransomware and CVE exposure endpoints"
  ```

---

## Part 3: Dashboard web

### Task 7: Signal hero (map + brief + actions)

**Files:**
- Create: `apps/web/src/components/dashboard/signal-hero.tsx`
- Create: `apps/web/src/components/dashboard/use-dashboard-overview.ts`
- Delete: `apps/web/src/components/dashboard/attention-band.tsx`, `apps/web/src/components/dashboard/country-map.tsx`

**Interfaces:**
- Consumes: Task 1 `WorldDots`, `WorldDotPoint`; Task 6 routes via `api.GET` and `components["schemas"][...]`.
- Produces:
  ```ts
  // use-dashboard-overview.ts: one hook per endpoint, query key ["dashboard", <name>, days, clientId]
  export function useDashboardMap(days: number | null): UseQueryResult<DashboardMap>;
  export function useDashboardAttention(days: number | null): UseQueryResult<DashboardAttention>;
  export function useDashboardTrending(days: number | null): UseQueryResult<TrendingResponse>;
  export function useDashboardRansomware(days: number | null): UseQueryResult<RansomwareOverview>;
  export function useCveExposure(days: number | null): UseQueryResult<CveExposure>;
  export function SignalHero(props: { days: number | null }): JSX.Element;
  ```
  All hooks use `placeholderData: keepPreviousData`. The active client id comes from the same place the existing queries get it (`api` client adds `X-Client-ID`; include the client id from `useAuth()` in the key so switching client refetches).

- [ ] **Step 1: Build `SignalHero`**

  `section aria-label="Signal map"`, `rounded-3xl bg-hero text-hero-foreground overflow-hidden`, grid `lg:grid-cols-[1fr_360px]`, min height 420 px. Left: `WorldDots` with points from `useDashboardMap` (`weight = incidents + ransomware_victims`, `tone = incidents >= ransomware_victims ? "incident" : "ransomware"`, `ring` when the code is in `client_countries`, `label` = `"{country name}: {incidents} insiden, {victims} korban ransomware"`), title `Signal map · {periodLabel}`, caption `Ukuran titik = artikel insiden + korban ransomware per negara`, legend (Insiden / Ransomware / Negara klien (cincin)), a tooltip card (`bg-card text-card-foreground`) positioned at the focused point showing name, both counts, `Teratas: {top_actor}, {top_industry}`; selecting a point navigates to `/newsroom?country={code}`. Under the canvas, a `sr-only` `<ol>` of the top 10 points. Right panel (`bg-black/20` is not a token: use a new token `--hero-panel` = `rgb(0 0 0 / .18)` in both themes, added to `globals.css` and the Tailwind theme): eyebrow `Brief`, `brief.headline` (17 px, 650), `brief.detail` (`text-hero-muted`), link `Recap mingguan →` to `/recap`, then three action rows as `next/link`:
  1. `{kev_in_stack}` · `CVE KEV kena tech stack` · `{kev_without_ticket} tanpa tiket` → `/cve`
  2. `{ransomware_in_client_scope}` · `Korban ransomware di negara klien` → `/newsroom?rubric=ransomware`
  3. `{watchlist_hits + pir_hits}` · `Hit watchlist / PIR` · `{pir_hits} PIR` → `/newsroom?rubric=watchlist`
  Loading: `Skeleton` with the same height. Errors: map error shows the dots with `Gagal memuat peta.`; attention error shows `Gagal memuat brief.` in the right panel; neither hides the other. Empty map: `Belum ada insiden dengan negara pada periode ini.` over the dots.

- [ ] **Step 2: Typecheck, lint**

  Run: `cd apps/web && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm lint` → no errors.

- [ ] **Step 3: Commit**

  ```bash
  git add -A apps/web
  git commit -m "feat(web): dashboard signal hero with world map, brief and actions"
  ```

### Task 8: Dashboard page: KPI strip, cards, layout

**Files:**
- Modify: `apps/web/src/app/(app)/dashboard/page.tsx`
- Create: `apps/web/src/components/dashboard/overview-cards.tsx` (`MustReadCard`, `TrendingCard`, `RansomwareCard`, `CveExposureCard`, `ClientContextCard`)
- Modify: `apps/web/src/components/dashboard/stat-box.tsx` only if a card needs a variant (no restyle of unrelated props)

**Interfaces:**
- Consumes: Task 7 hooks and `SignalHero`; existing `useDashboardStats`, `useTaStats`, `TimelineChart`, `HorizontalBarChart`, `BreakdownList`; `/api/articles` with `sort=priority` arrives in Task 9, so `MustReadCard` uses `/api/articles?page_size=4` with `posted_on_start` for now and switches to `sort: "priority"` in Task 9 (one-line change listed there).

- [ ] **Step 1: Rebuild the page in this order** (spec 4.1)

  Header (`PageHeader`: title = today formatted `id-ID` `weekday long, day numeric, month long`; description = `Klien: {client name} · diperbarui {HH:mm} WIB`; actions = existing `DashboardFilterBar`). Then `SignalHero`. Then KPI strip (existing `StatBox` flat cells, five columns at `xl`): Articles (+`Delta`), Confirmed incidents (+`Delta`), `Korban ransomware` = `ransomware.total` with sub `{apac} di APAC`, `CVE kritis terbuka` = `open_critical` with sub `{open_kev} KEV`, `Aktor di berita` = `total_threat_actors` with sub `{n} baru periode ini` (n = trending items with `kind == "actor" && is_new`). Then the 12-column grid: MustRead (7), Trending (5, top 4: name, kind label `Aktor`/`TTP`, `font-code` count, `+{change_pct}%` in `text-destructive-text` or a `baru` badge), Ransomware (4: 8-week area line via `TimelineChart` with the last point emphasised, then top 3 groups as bars), CVE exposure (4: three rows with `KEV` badge or CVSS badge, `font-code` CVE id, `{tech} · CVSS {cvss} · {tanpa tiket | tiket {age}h}`, last row `{closed_in_period} tiket selesai · rata-rata {mean_days_to_close} hari`, each row links to `/cve?search={cve_id}`), Client context (4: watchlist hits, PIR hits, newest cluster from the existing `/api/clusters/recent?limit=1`), Articles over time (8: `stats.timeline`, two series, `count` as "Semua berita" in `--info` and `incidents` (Task 6 Step 4) as "Insiden" in `--primary`), Industries (4: existing industry data, "General" excluded). Then the Threat Actor Room section and the TTP chart, moved below, unchanged in data.
  Every card has its own skeleton and its own `Gagal memuat …` line. Remove imports of the deleted `AttentionBand` and `CountryMap`.

- [ ] **Step 2: Verify**

  Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm lint && pnpm build` → pass.
  Run the API (`uvicorn cti_api.main:app`) against local Postgres and `pnpm dev`; open `/dashboard` in the browser pane: light and dark, 1440 px and 375 px, Tab through the map points (tooltip follows focus, Enter navigates), switch period (old numbers dim, then update), switch client (numbers change). Map codes `UK`/`EL` place on GB/GR.

- [ ] **Step 3: Commit**

  ```bash
  git add -A apps/web
  git commit -m "feat(web): redesigned dashboard with KPI strip and overview cards"
  ```

---

## Part 4: Newsroom API

### Task 9: `sort` and `ttp` on `/api/articles`, topics endpoint

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/article.py` (`list_filtered`)
- Modify: `apps/api/src/cti_api/routers/articles.py` (`list_articles`)
- Create: `apps/api/src/cti_api/routers/newsroom.py`, `apps/api/src/cti_api/schemas/newsroom.py`
- Modify: `apps/api/src/cti_api/main.py` (include the new router)
- Test: `tests/integration/test_article_query.py` (add), `tests/integration/test_newsroom_api.py`
- Regenerate: contract files

**Interfaces:**
- Consumes: Task 3 `get_trending` (with `countries`, `news_types`, `search`).
- Produces:
  - `AsyncArticleRepo.list_filtered(..., sort: Literal["recent", "priority"] = "recent")`. `ttps` already exists.
  - `GET /api/articles` new query params `sort: Literal["recent","priority"] = "recent"` and `ttp: list[str] | None`.
  - `GET /api/newsroom/topics` (`require_auth`), params `posted_on_start`, `posted_on_end`, `country: list[str] | None`, `news_type: list[str] | None`, `search: str | None`, `limit: int = Query(4, ge=1, le=10)`. Response `TopicsResponse`: `items: list[TopicOut]` where `TopicOut` = TrendItem fields + `top_countries: list[str]` (max 3) + `latest_article: TopicArticle | None` (`id`, `title`, `posted_on`); plus `window_days`, `window_label`, `generated_at`. The period is `posted_on_end - posted_on_start` in days when both given, `days=None` handling otherwise as in `get_trending`.

- [ ] **Step 1: Write the failing tests**

  - `tests/integration/test_article_query.py::test_list_filtered_priority_sort`: seed (a) unconfirmed, confidence 90; (b) confirmed, confidence 50, `seen_count` 1; (c) confirmed, confidence 50, `seen_count` 4; (d) confirmed, confidence NULL. Expect order `[c, b, d, a]` with `sort="priority"`; with default sort the order stays `posted_on desc, id desc`.
  - `tests/integration/test_newsroom_api.py::test_topics_returns_latest_article_and_countries`: three articles mentioning `Qilin` this week (countries SG, ID), none before; expect one item `name == "Qilin"`, `is_new is True`, `top_countries` ⊆ `["SG","ID"]`, `latest_article.title` = newest title.
  - `test_topics_respects_search`: `search="bank"` only counts articles whose title matches.
  - `test_articles_ttp_filter`: `/api/articles?ttp=T1059` returns only the article with that TTP.

- [ ] **Step 2: Run, verify failure**

  Run: `uv run pytest tests/integration/test_article_query.py tests/integration/test_newsroom_api.py -q` → FAIL.

- [ ] **Step 3: Implement**

  Priority order (spec 5.3): `confirmed_incident desc, confidence_score desc nulls last, seen_count desc, posted_on desc nulls last, id desc`. Topic `top_countries` and `latest_article`: one query per returned item (max 10), filtering by `ArticleThreatActor.threat_actor` or `ArticleTTP.ttp_id` within the period.

- [ ] **Step 4: Run, verify pass; regenerate contract; lint**

  Run: `uv run pytest tests/integration/test_article_query.py tests/integration/test_newsroom_api.py tests/integration/test_articles_router_snapshot.py -q` → PASS.
  Run: `uv run python tools/export_openapi.py && cd apps/web && pnpm run gen:api && cd ../.. && uv run ruff check . && uv run ruff format --check .`

- [ ] **Step 5: Switch the dashboard "Perlu dibaca" card to priority**

  In `overview-cards.tsx` `MustReadCard`, add `sort: "priority"` to the `/api/articles` query. Run `pnpm exec tsc --noEmit`.

- [ ] **Step 6: Commit**

  ```bash
  git add -A
  git commit -m "feat(api): priority sort and TTP filter on articles, newsroom topics endpoint"
  ```

---

## Part 5: Newsroom web

### Task 10: Sheet, rubric and article list building blocks

**Files:**
- Create: `apps/web/src/components/ui/sheet.tsx`
- Create: `apps/web/src/components/newsroom/article-list-sheet.tsx`, `apps/web/src/components/newsroom/rubric.tsx`
- Create: `apps/web/src/components/newsroom/rubric-queries.ts`
- Modify: `apps/web/src/components/newsroom/use-articles.ts` (accept `sort`, `ttp`)

**Interfaces:**
- Produces:
  ```ts
  // ui/sheet.tsx: Base UI Dialog styled as a right side panel (w-full sm:max-w-xl, full height),
  // focus trapped, Escape closes, overlay without blur.
  export function Sheet(props: { open: boolean; onOpenChange: (o: boolean) => void; title: string;
                                 description?: string; children: React.ReactNode }): JSX.Element;

  // rubric-queries.ts: one entry per current panel, holding the query each panel uses today
  export type RubricKey = "apac" | "global" | "local" | "ransomware" | "watchlist" | "techstack";
  export function useRubric(key: RubricKey, filters: NewsroomFilters, page: number, pageSize: number):
    { items: RubricItem[]; total: number | undefined; isPending: boolean; isError: boolean; refetch: () => void };
  export interface RubricItem { id: string; title: string; meta: string; article?: Article } // victims have no article

  export function Rubric(props: { rubric: RubricKey; title: string; filters: NewsroomFilters;
    onSelect: (a: Article) => void; onSeeAll: () => void; hideWhenEmpty?: boolean }): JSX.Element;

  export function ArticleListSheet(props: { open: boolean; onOpenChange: (o: boolean) => void; title: string;
    source: { rubric: RubricKey } | { actor: string } | { ttp: string };
    filters: NewsroomFilters; onSelect: (a: Article) => void }): JSX.Element;   // paged, 20 per page, SimplePager
  ```
  `useRubric` moves the existing queries out of `panels/*.tsx` unchanged: APAC = `news_type: ["apac"]`; Global = the `GLOBAL_NEWS_TYPES` list from `newsroom/page.tsx`; Local = `country: user.client_countries`; Ransomware = the request in `ransomware-panel.tsx`; Watchlist = names from `/api/ta/watchlist-names` then `threat_actor`; Tech stack = names from `/api/techstack?page_size=500` then the query in `techstack-panel.tsx`. Read each panel file and copy its params exactly.

- [ ] **Step 1: Implement the four files and the `use-articles.ts` params**

  `Rubric` shows: header (`text-xs uppercase tracking-widest text-primary-text`, count in `text-muted-foreground`), three items (title 13.5 px 600, meta line 11.5 px muted), `Lihat semua →` button calling `onSeeAll`. Clicking an item with `article` calls `onSelect`; ransomware items open the victim `post_url` the same way the current panel does. Loading = 3 skeleton lines; error = `Gagal memuat {title}.`; empty = `Belum ada artikel.`, or render nothing when `hideWhenEmpty`.

- [ ] **Step 2: Typecheck, lint**

  Run: `cd apps/web && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm lint` → no errors.

- [ ] **Step 3: Commit**

  ```bash
  git add -A apps/web
  git commit -m "feat(web): sheet, rubric and article list sheet for the newsroom"
  ```

### Task 11: Newsroom page (masthead, front, topics, rubrics)

**Files:**
- Modify: `apps/web/src/app/(app)/newsroom/page.tsx`
- Create: `apps/web/src/components/newsroom/masthead.tsx`, `front-section.tsx`, `topics-strip.tsx`
- Modify: `apps/web/src/lib/newsroom/filters.ts` (add `incidentOnly: boolean`, `country: string | null`; keep the type name)
- Delete: `apps/web/src/components/newsroom/filter-bar.tsx`, `apps/web/src/components/newsroom/panels/` (all five), and `panel-shell.tsx` / `article-card.tsx` if nothing else imports them (check with `grep -rn` before deleting; `filtered-view.tsx` imports `PanelShell` today, so keep `panel-shell.tsx`)

**Interfaces:**
- Consumes: Task 9 `/api/articles?sort=priority`, `/api/newsroom/topics`; Task 10 `Sheet`, `Rubric`, `ArticleListSheet`, `useRubric`; existing `ArticleModal`, `FilteredView`, `TabPills`.
- Produces:
  ```ts
  export function Masthead(props: { filters: NewsroomFilters; onChange: (f: NewsroomFilters) => void; total?: number }): JSX.Element;
  export function FrontSection(props: { filters: NewsroomFilters; onSelect: (a: Article) => void }): JSX.Element;
  export function TopicsStrip(props: { filters: NewsroomFilters; onOpen: (t: { actor: string } | { ttp: string }, title: string) => void }): JSX.Element;
  ```

- [ ] **Step 1: Build the page** (spec 5.1)

  Keep the `TabPills` "Cyber News" / admin "Filtered Articles" and `FilteredView` as they are. Cyber News view, top to bottom: `Masthead` (title `Newsroom`, date, `{total} artikel` from the front query total, filter row: period chips 24 jam / 7 hari / 30 hari / Semua mapped to `dateStart`, `Insiden saja` toggle, country select (options from `/api/filters`), search `Input` with `placeholder="Cari judul, aktor, CVE…"` debounced 300 ms; changes apply immediately, no Apply/Reset). Initial filters read `?country=` and `?rubric=` from the URL (from the dashboard links); `rubric` opens that rubric's sheet on load. `FrontSection`: `/api/articles?sort=priority&page_size=4` with the filters; item 1 as the lead (`text-3xl font-bold tracking-tight text-balance`, kicker line with `Insiden` badge when `confirmed_incident`, confidence number, news type, relative time; chips for actors, TTPs, countries), items 2-4 in the side column; `lg:grid-cols-[1.6fr_1fr]`. `TopicsStrip`: `/api/newsroom/topics?limit=4`; section label `Topik aktif` + `window_label`; cards in `grid-cols-[repeat(auto-fit,minmax(230px,1fr))]` showing kind (`Threat actor`/`TTP`), `+{change_pct}%` or `baru`, name (`font-code` for TTP ids), `{count} artikel · {top_countries}`, 7-bar mini chart from `daily` (bars `bg-primary/75`, heights relative to the max), latest article title, footer `{count} artikel →`; hidden entirely when `items` is empty. Rubric row: APAC, Global, Local, Ransomware (`lg:grid-cols-4 md:grid-cols-2`); then Watchlist and Tech stack with `hideWhenEmpty`. One `ArticleListSheet` instance driven by state `{ open, title, source }`; one `ArticleModal`.

- [ ] **Step 2: Verify**

  Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm lint && pnpm build` → pass.
  With API + `pnpm dev`, check `/newsroom` in the browser pane: light/dark, 1440/375 px; type a search with no results (every block shows its empty state, topics strip hidden); open a topic card and a "Lihat semua" (sheet traps focus, Escape closes, paging works); open an article (modal works); admin sees "Filtered Articles"; `/newsroom?country=SG` and `/newsroom?rubric=ransomware` from the dashboard links work.

- [ ] **Step 3: Commit**

  ```bash
  git add -A apps/web
  git commit -m "feat(web): redesigned newsroom with front page, active topics and rubrics"
  ```

### Task 12: Whole-branch check and release 0.8.1

- [ ] **Step 1: Full CI-equivalent run**

  Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy packages/cti-core/src packages/cti-scraper/src && uv run pytest tests/unit tests/contract packages -q && uv run pytest tests/integration -q` (background; ~7 min) and `cd apps/web && pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build`.
  Expected: all pass; `git status` shows no drift in `docs/openapi.json` or `schema.d.ts` after re-running the two generators.

- [ ] **Step 2: Release 0.8.1**

  Apply the release from Global Constraints. CHANGELOG entry (`### Ditambahkan` / `### Diubah` as the existing entries use): login baru dengan panel brand dan peta titik dekoratif tanpa data sebelum login; dashboard baru (peta sinyal dunia, brief + tiga aksi, perlu dibaca, naik tajam, ransomware, CVE exposure, konteks klien); newsroom baru (berita utama, topik aktif, rubrik, panel samping); endpoint `/api/dashboard/{map,attention,trending,ransomware,cve-exposure}`, `/api/newsroom/topics`, `sort`/`ttp` di `/api/articles`, `incidents` di timeline `/api/dashboard`. Re-run `tools/export_openapi.py` so the version in `docs/openapi.json` matches.
  ```bash
  git add -A && git commit -m "chore(release): 0.8.1 - Login, dashboard and newsroom redesign"
  ```
