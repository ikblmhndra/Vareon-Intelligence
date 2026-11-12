# FigCraft redesign 4a: Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the full FigCraft mockups for X Intel (Tweets, Accounts), Recap (Weekly) and the Newsletter composer (with preview dialog) with every pre-redesign feature X1-X21, R1-R21 and N1-N18 still reachable, plus the two backend items the mockup needs (B-X1 tweet stats, B-X2 search and filters), inside the 0.8.16 release.

**Architecture:** Backend first: Task 1 extends `GET /api/tweets/stats` (counters, most-named victims) and Task 2 the shared tweet filters (search over text, handle, victim and CVE; `has_cve`; `signal`), each with its own pytest cycle; Task 3 regenerates the API contract once. Then the web: shared pieces and layouts (4), Recap (5-6), X Intel (7-10), Newsletter (11-13), a states and permissions sweep (14), docs (15) and the final verification (16). `lib/newsletter/composer.ts`, `queue.ts` and `summary.ts` are never modified; Newsletter changes the render tree, the period parameter and the `response.ok` checks only.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), pytest + testcontainers + syrupy; Next.js 16 App Router, React 19, TanStack Query, Tailwind v4, shadcn on Base UI (`@base-ui/react`), `openapi-fetch` (`api` from `@/lib/api/client`), `react-markdown`, `lucide-react`, `sonner`.

**Spec:** `docs/superpowers/specs/2026-11-12-figcraft-redesign-4a-content-design.md` (binding; section numbers below refer to it, `C`/`D` ids are its conflicts and decisions). The gap inventory (`.superpowers/brainstorm/sp4-inventory.md`, X*, R*, N*) is context only; where it differs, the spec wins.

## Global Constraints

- No migration, no new `Settings` field: `.env.example`, `.env.prod.template` and the Alembic head (`c4e8a1f2b9d6`) stay as they are. Release stays 0.8.16 (`## [0.8.16] - 2026-11-08`), one PR, no version bump; `uv.lock` stays `revision = 3`.
- Only `routers/tweets.py` and `cti_core/db/repositories/tweet.py` change on the backend. Router permission `view_tweets` stays; `monitored_accounts.py`, `recap.py`, `newsletter.py` are untouched. Comments and docstrings Indonesian, explaining *why*, matching the file. Docs under `docs/` English; `CHANGELOG.md` and `docs/PROGRESS.md` Indonesian.
- Commits: English conventional (`feat(api): ...`, `feat(web): ...`); the body ends with a blank line + the implementer's own model trailer (`Co-Authored-By: <the model that wrote the commit> <noreply@anthropic.com>`; the session's attribution reminder is authoritative, not a copy of an older trailer). Stage only your own files. Never push, merge or switch branches (`claude/figcraft-design-data`).
- Python checks: `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src packages/cti-scraper/src` (covers the repository change). Fast suite: `uv run pytest tests/unit tests/contract packages --deselect tests/contract/test_golden.py::test_golden_trendmicro` (also deselect the two known Mac-only failures). Integration needs Docker, isolated compose project `qacve` only (never `deploy-postgres-1`): `uv run pytest tests/integration -k "<pattern>"`.
- Contract: regenerated ONCE in Task 3. Tasks 1-2 do not run `tools/export_openapi.py`, and do not run `tests/integration/test_tweets_router_snapshot.py::test_tweet_stats` (its snapshot changes with Task 1; Task 3 reviews and updates it). `GET /api/tweets/stats` stays an untyped `dict[str, object]`, so its new fields go to `apps/web/src/lib/api/loose-types.ts::TweetStats` by hand.
- openapi-typescript marks defaulted query params required: every web call to `GET /api/tweets` and `/api/tweets/stats` sends `apac_only`, `ot_only`, `confirmed_only` and `has_cve` explicitly; `signal`, `search`, `posted_on_*` and `tz` are sent only when set.
- Web (`apps/web`): read `apps/web/AGENTS.md` and `apps/web/CLAUDE.md` first. Base UI, not Radix: `render={<X/>}` (never `asChild`), `SelectItem` children a single string, `items` on `Select` for sentinel values, `DropdownMenuLabel` inside a `DropdownMenuGroup`. Theme tokens only; text on tints `text-X-text`; no `backdrop-blur`; minimum text 11 px (`text-2xs`); CVE ids, counters, handles and cron-like values in `font-code`; focus ring `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background`; every input an `aria-label` or a real `<label htmlFor>`; icon-only buttons an `aria-label`; two- and three-column rows collapse below 1024 px (`lg:`; the composer below `xl:`). Dates only through `lib/format.ts` (`fmtShortDate`, `fmtDateTime`, `fmtAgo`, `parseLocalDate`, `browserZoneName`), except Recap windows (UTC calendar dates, plain, spec C8/D32).
- Lessons from sub-projects 1-3 (each is a review item): (a) a nested layout with a string `metadata.title` resets the root template, so the three layouts export `{ default, template: "%s · ${PLATFORM_NAME}" }` and pages set `document.title` with the restore-on-unmount pattern of `entity-view.tsx`; (b) check `response.ok`, never only `if (error)` (an empty-body 502 passes the latter); (c) no react-query retry on 4xx: every new or changed query throws `new Error(msg, { cause: response.status })` and uses `retry: (n, e) => n < 2 && !isClientError(e)` from `lib/exec/query.ts`; (d) no interactive element nested in another (a real `<button>` for the primary action, links and menus as siblings, never `role="button"` around a link); (e) gate each control on the real backend permission via `useCan()`, never a stricter one; (f) a `Chip` inside `HeroPanel` needs hero-safe tokens (4a adds no `HeroPanel`); (g) legend and bar colours equal the cell colours (hit-rate bar and its percentage share one token); (h) `table-fixed` always with explicit column widths; (i) `useDebounced` inputs are strings or memoised values, and the period anchor is state, never `new Date().toISOString()` in render; (j) every pre-redesign feature stays reachable, with a checklist X1-X21, R1-R21, N1-N18 in the PR (Task 14).
- Web verification per task, from `apps/web` after `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"`: `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit` (typegen first, or tsc gives false errors); `pnpm build`; all exit 0, plus the task's checklist in `pnpm dev` (API via uvicorn on `qacve`). No web test runner exists; do not add one.
- No subagent re-delegation inside a task. Do not push.

## Review Focus

1. The stats header and rail always describe the posts the list shows: every counter and `top_victims` follow the same filters as `GET /api/tweets`, and a missing key, `[]` and JSON `null` all count as none (Task 1, `test_get_stats_counters`, `test_get_stats_counters_follow_filters`).
2. Search and the new filters combine with AND and never widen: free text matches text, handle, victim or CVE; `has_cve` and `signal` narrow; an unknown `signal` is a 422 (Task 2, `test_filters_combine_with_and`, `test_list_tweets_signal_and_has_cve_params`).
3. No page treats a failed response as success or retries a 4xx: `response.ok` in `feed-status-chip`, the Newsletter preview, draft, resend, rebuild and history calls, and the new queries (Task 13 checklist, blocking a request with a 502 in the Network panel; repeated in Tasks 5, 7 and 11 for their calls).
4. No interactive element is nested: tweet card (Task 9) and newsletter article card (Task 12) are checked in the accessibility tree; history rows, queue rows and the History select follow the same shape.
5. The Newsletter state machine is untouched and everything stays reachable: `git diff --stat origin/Dev -- apps/web/src/lib/newsletter/composer.ts queue.ts summary.ts` is empty and the N1-N18 walk passes (Task 12, Task 14).

---

### Task 1: B-X1 tweet stats, counters and most-named victims (4.1)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/tweet.py` (`AsyncTweetRepo.get_stats`, new module helper `_has_items`)
- Test: `tests/integration/test_tweet_query.py` (`TestAsyncTweetRepo`)

**Interfaces:**
- Produces: `_has_items(key: str) -> ColumnElement[bool]`: `case((func.jsonb_typeof(Tweet.scan_results[key]) == "array", func.jsonb_array_length(Tweet.scan_results[key])), else_=0) > 0`, so a missing key, `[]` and JSON `null` are none (Task 2 reuses it).
- Produces: `get_stats` returns `total`, `top_authors` (unchanged) plus `confirmed`, `apac`, `ot`, `with_cve`, `databreach`, `zero_day` (ints, `count().filter(...)` in one aggregate query over `Tweet` with the same `_apply_tweet_filters` applied; booleans via `.as_boolean()` on `apac_indicator` / `ot_status`, lists via `_has_items("cve_list" | "databreach_list" | "zero_day_list")`, `confirmed` via `confirmed_incident.is_(True)`) and `top_victims: list[{victim, count}]` (`group by lower(btrim(victim_name))` over non-null, non-blank names, label `max(victim_name)`, order count desc then label, limit 5). Four queries in all (total, authors, counters, victims); no index (spec 4.1 Performance).

- [ ] **Step 1: Write failing tests** in `test_tweet_query.py` with a new `_seed_signals` helper (rows with every key present, missing, `[]` and `null`): `test_get_stats_counters` (each of the six counters, `null` / `[]` / missing count as none), `test_get_stats_counters_follow_filters` (`apac_only`, `confirmed_only` and a date range shrink every counter and `top_victims` together), `test_get_stats_top_victims` ("LockBit Bank" and " lockbit bank " merge case-insensitively, order by count then label, limit 5 with seven distinct names, `None` and blank skipped). The existing `test_get_stats_top_authors` and `test_get_stats_respects_filters` stay green.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_tweet_query.py -q -k "get_stats"` (Docker, `qacve`). Expected: FAIL (new keys missing).
- [ ] **Step 3: Implement** per Interfaces. Indonesian docstring: why the figures follow the feed's filters (header and rail must describe the listed posts), why `_has_items` guards with `jsonb_typeof` (`jsonb_array_length` raises on non-arrays; `CASE` is evaluated lazily), and why the victim label is `max(victim_name)`.
- [ ] **Step 4: Run** the Step 2 command, then `uv run mypy packages/cti-core/src packages/cti-scraper/src` and `uv run ruff check . && uv run ruff format --check .`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): counters and most-named victims in the tweet stats`

### Task 2: B-X2 search over handle, victim and CVE; `has_cve` and `signal` (4.2)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/tweet.py` (`_apply_tweet_filters`, `list_filtered`, `get_stats`, `list_top_between`), `apps/api/src/cti_api/routers/tweets.py` (`list_tweets`, `tweet_stats`)
- Test: `tests/integration/test_tweet_query.py`, `tests/integration/test_tweets_router_snapshot.py`

**Interfaces:**
- Produces: `_apply_tweet_filters(..., has_cve: bool = False, signal: str | None = None)`. `search` becomes an OR of `Tweet.text ilike %q%`, `Tweet.author_username ilike %q-without-leading-@%`, `Tweet.victim_name ilike %q%` and `cast(Tweet.scan_results["cve_list"], Text) ilike %q%`; the separate `author` filter keeps its behaviour. `has_cve` = `_has_items("cve_list")`. `signal`: `zero_day` / `databreach` = `_has_items(f"{signal}_list")`, `ot` / `report` = `scan_results["ot_status" | "report_status"].as_boolean()`. All other predicates are ANDed.
- Produces: `list_filtered`, `get_stats` and `list_top_between` gain keyword-only `has_cve` and `signal` with defaults (the recap caller stays unchanged); `list_tweets` and `tweet_stats` take `has_cve: bool = Query(False)` and `signal: Literal["ot", "zero_day", "databreach", "report"] | None = Query(None)` and pass them through; `ot_only` stays for API clients. An unknown `signal` is FastAPI's 422.

- [ ] **Step 1: Write failing tests.** `test_tweet_query.py`: `test_search_matches_text_handle_victim_and_cve`, `test_search_handle_with_at` ("@rst_cloud" matches the handle), `test_list_filtered_has_cve`, `test_list_filtered_signal_each_value` (the four values on seeded rows, a non-matching row excluded), `test_filters_combine_with_and` (search + `signal` + `confirmed_only` + `has_cve`; also checks `get_stats` totals agree with `list_filtered` totals). `test_tweets_router_snapshot.py::test_list_tweets_signal_and_has_cve_params` (each valid `signal` and `has_cve=true` give 200 on both endpoints, `signal=bogus` gives 422).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_tweet_query.py tests/integration/test_tweets_router_snapshot.py::test_list_tweets_signal_and_has_cve_params -q -k "search or has_cve or signal or combine"`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; extend the `_apply_tweet_filters` docstring (Indonesian) with why free text now also matches handle, victim and CVE (the mockup's single search box replaces the separate handle filter), and the `%` / `@` handling.
- [ ] **Step 4: Run** the Step 2 command plus `uv run pytest tests/integration -k "tweet or recap or monitored" -q --deselect tests/integration/test_tweets_router_snapshot.py::test_tweet_stats` and `uv run pytest tests/unit/test_tweet_alerts.py -q`; ruff and mypy as Task 1. Expected: PASS (`test_recap_*` and the alerts tests unchanged).
- [ ] **Step 5: Commit** `feat(api): tweet search over handle, victim and CVE, plus has_cve and signal filters`

### Task 3: API contract, loose types and snapshot (4.1, 4.2, 5)

**Files:**
- Modify: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts` (generated), `apps/web/src/lib/api/loose-types.ts`, `tests/integration/__snapshots__/test_tweets_router_snapshot.ambr`

**Interfaces:**
- Produces for the web: `has_cve` and `signal` query parameters on `GET /api/tweets` and `/api/tweets/stats` in `paths`.
- Produces in `loose-types.ts`: `TweetStats` gains `confirmed`, `apac`, `ot`, `with_cve`, `databreach`, `zero_day: number` and `top_victims: { victim: string; count: number }[]` (Indonesian comment naming `AsyncTweetRepo.get_stats` as the serialiser).

- [ ] **Step 1: Regenerate** `uv run python tools/export_openapi.py`, then `cd apps/web && pnpm run gen:api`. Expected: `git diff --stat` shows only those two generated files.
- [ ] **Step 2: Update `loose-types.ts`** per Interfaces.
- [ ] **Step 3: Snapshot.** `uv run pytest tests/integration/test_tweets_router_snapshot.py -q`; read the diff (only the six counters at 0 or 1 and `top_victims: []`), then rerun with `--snapshot-update`.
- [ ] **Step 4: Verify:** `uv run ruff check . && uv run ruff format --check .`; mypy; fast suite; `uv run pytest tests/integration -k "tweet or monitored or api_permissions" -q`; web `pnpm exec next typegen && pnpm exec tsc --noEmit` (expected clean: the old `tweet-list.tsx` still compiles against the extended `TweetStats`).
- [ ] **Step 5: Commit** `chore(api): regenerate the API contract for the tweet stats and filters`

### Task 4: Shared pieces, layouts and title template (6.6 #1, 6 constraint 1, C17)

**Files:**
- Create: `apps/web/src/components/ui/disclosure.tsx`, `apps/web/src/lib/use-page-title.ts`
- Modify: `apps/web/src/app/(app)/xintel/layout.tsx`, `apps/web/src/app/(app)/recap/layout.tsx`, `apps/web/src/app/(app)/newsletter/layout.tsx`, `apps/web/src/app/(app)/xintel/page.tsx`, `apps/web/src/app/(app)/recap/page.tsx`, `apps/web/src/app/(app)/newsletter/page.tsx`

**Interfaces:**
- Produces: `Disclosure({ title: ReactNode; defaultOpen?: boolean; printOpen?: boolean; children; className? })`: a `<button type="button" aria-expanded aria-controls>` header (chevron, focus ring) and a region with the matching `id` (`useId`); closed regions are `hidden`, or `hidden print:block` when `printOpen`; the header button carries `print:hidden` when `printOpen`.
- Produces: `usePageTitle(title: string | null)`: effect with the restore-on-unmount logic of `entity-view.tsx` (save `document.title`, set it, restore only if it is still ours); `null` is a no-op. Full text is passed in by pages as `"X Intel"`, `"Weekly recap 2026-W45"` and so on; the layout template adds the suffix only to the server-rendered title, so the hook sets the same `"{title} · {PLATFORM_NAME}"` itself (import `PLATFORM_NAME` from `@/lib/brand`).
- The three layouts become metadata-only like `app/(app)/exec/layout.tsx` (`{ default: "X Intel" | "Recap" | "Newsletter", template: "%s · ${PLATFORM_NAME}" }`, `return children`). Until Tasks 5, 7 and 11 build the real headers, each page renders the old `PageHeader` itself with the old title and description, so nothing regresses between commits.

- [ ] **Checklist:** `Disclosure` toggles with Enter and Space, announces `aria-expanded`, region reachable by `aria-controls`, `printOpen` region visible in print preview; the browser tab on `/xintel`, `/recap` and `/newsletter` reads "X Intel · Vareon Intelligence" etc. after a full load and after client navigation from another page (template kept), and returns to the previous title on leaving; the three pages still show their old h1.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): disclosure primitive, page title hook and template-safe layouts for the content pages`

### Task 5: Recap shell, routing, header, history select and Regenerate dialog (6.2 routing, header, Regenerate dialog, Export PDF, C7-C9)

**Files:**
- Create: `apps/web/src/components/recap/recap-page-header.tsx`, `apps/web/src/components/recap/recap-generate-dialog.tsx`
- Modify: `apps/web/src/app/(app)/recap/page.tsx` (rewritten shell), `apps/web/src/lib/recap/period.ts`, `apps/web/src/app/globals.css` (`@media print` block)
- Delete (after `grep -rn "recap-history\|RecapHistory" apps/web/src` shows no other user): `apps/web/src/components/recap/recap-history.tsx`

**Interfaces:**
- Produces in `period.ts`: `isoWeek(mondayIso: string): number` (ISO week of that Monday's Thursday, all UTC; year boundaries give 52/53/1), `weekHeading(start: string, end: string): string` ("Week 45: 27 Oct – 2 Nov"), `previousPeriod(kind, date): string` (previous Monday / previous day). `formatRange`, `recapTitle`, `mondayOf`, `sundayOf`, `lastFinishedWeekStart` stay.
- Produces: `RecapPageHeader({ doc, kind, date, list, canGenerate, onSelect, onPrevious, onRegenerate, generating })` rendering `PageHeader` with kicker, h1, description and `actions` per 6.2 (previous button, `Select` "History" with `items` and single-string labels, `aria-label` "Recap history", "Export PDF", primary "✦ Regenerate" only with `manage_intel`); empty and loading give h1 "Recap". `RecapGenerateDialog({ open, onOpenChange, defaultKind, defaultDate, existing: ReadonlySet<string>, pending, error, onConfirm: ({ kind, date, force }) => void })` built on `Dialog` + `DialogDescription` + footer buttons (`ConfirmDialog` cannot host a form): `SegmentedControl` "Week | Day" (`aria-label` "Recap kind"), `DateField` "Week of" snapped by `mondayOf` with caption "{range} (Mon-Sun, UTC)" or "Date", the 10-30 s body, the overwrite warning when `existing` has the period (force = true), the inline "A week can only be generated after its Sunday has ended in UTC." with confirm disabled, title "Regenerate recap" / "Generate recap".
- `page.tsx`: `?kind=weekly|daily&date=YYYY-MM-DD` via `useSearchParams` (both absent = latest weekly), `router.replace` on selection, `selected` derived from the URL. Query keys unchanged (`["recap","list"]`, `["recap","doc",kind,date]`, `["recap","doc","latest"]`); queries and the `useGenerateRecap` mutation keep their `response.ok` handling, add `{ cause: status }` to thrown errors and the 4xx no-retry. Success selects the returned `kind`/`date` and toasts "Recap generated"; failure toasts the `detail` and keeps the dialog open. `Notice busy` "Generating the recap. This can take up to 30 seconds." replaces the content during the mutation. Empty state per 6.5 (`StatePanel`, "Generate recap" only with `manage_intel`, else the Monday-generation sentence). `usePageTitle`. Export PDF per 6.2: title, remove `dark` from `<html>`, `window.print()`, restore in an `afterprint` listener that is also removed on unmount; the `@media print` block (white page, no shadows, `break-inside: avoid` on cards, links print text) and `print:hidden` on the masthead, utility bar, mobile nav and page actions.

- [ ] **Checklist:** `/recap` opens the latest weekly; `?kind=daily&date=...` opens that daily and the header reads "Recap for ..."; the previous button walks back one Monday (or day) and updates the URL; the History select lists both kinds, its trigger shows the label (not the raw value) before it is opened; dialog defaults to the kind on screen, snaps a Wednesday to its Monday, blocks the current unfinished week with the inline error, warns when overwriting, Cancel posts nothing, a 400/502 detail toasts and keeps the dialog open; Regenerate and the empty-state button hidden without `manage_intel`; a 404 or 403 shows the error once (Network panel, no retry loop), a 500 retries at most twice; Export PDF from dark mode prints light, restores dark and the title afterwards; `isoWeek` checked on 2026-12-28 (53), 2027-01-04 (1) and a Monday in mid-year, and `weekHeading` across a year end.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): recap shell with URL state, history select, regenerate dialog and print export`

### Task 6: Recap content, tiles, forecast, hit rate and More signals (6.2, C9, C10, D27)

**Files:**
- Create: `apps/web/src/components/recap/recap-tiles.tsx`
- Modify: `apps/web/src/components/recap/recap-view.tsx` (restructured), `apps/web/src/components/recap/recap-quality.tsx` (`HitRateBlock`, `ScorecardBlock`, `ComparisonBlock` restyled; `GroundingBlock` kept), `apps/web/src/components/recap/recap-parts.tsx`

**Interfaces:**
- Produces: `RecapTiles({ doc })`: six `StatTile`s in `lg:grid-cols-6` (ARTICLES, POSTS, IOCs, CVEs, CAMPAIGNS, NEW ACTORS) with subs from `doc.quality.comparison.counts[key]` ("{±n}% vs week {N-1}" for the first four, "{±n} vs week {N-1}" for campaigns, new actors and a null `delta_pct`), muted, `signed()` for the U+2212 minus, "no prior week" when weekly has no comparison, no sub when daily.
- `RecapView({ doc, hitRate })` order: grounding `Notice` (warning, with the existing `<details>` list and `dropReason` wording) or empty-recap `Notice` (with the raw LLM output in a `Disclosure`), tiles, `lg:grid-cols-[minmax(0,1fr)_432px]` with SUMMARY card + "Top stories" (numbered rows, `safeHttpUrl` source link or plain text, subtitle per C9) on the left and "Active threat actors" / "Notable CVEs" (`Chips`) / "APAC signals" on the right, then the row with the forecast card (summary, one row per event with `ConfidenceBadge` and "Basis: ...", Watch items) and the "Forecast hit rate" card (`table-fixed`, widths 28 / 26 / 28 / 18 %, bar and percentage both `bg-primary`, "n/a" when nothing judged, partial/unclear footnote with "{reviewed_weeks} weeks reviewed", the "Week {N-1} scorecard: f1 hit, ..." line from `effectiveVerdict`, and a `Disclosure` "Review verdicts" revealing the existing `ScorecardBlock` with the per-event verdict `Select` and `PATCH` override). Finally `<h2>` "More signals" with a `Disclosure` (`printOpen`) holding Week over week (`ComparisonBlock`, `table-fixed` widths 36 / 16 / 16 / 16 / 16 %, "New this week" chips), Top tweets and Active campaigns. Daily recaps show no comparison, scorecard or hit rate and say "Daily forecasts are not scored."; footer text per 6.2 ("Generated {fmtDateTime} · {model} · {n} tokens" or "LLM skipped (no activity)", grounding line, Monday-Sunday line for weekly).

- [ ] **Checklist (QA against a weekly with comparison, one with dropped grounding items, an empty one, one without a previous week, and a daily):** deltas never red/green; "Each links to its source article" only when every story has a `url`; the verdict override is visible to a `view_intel` user without `manage_intel` and its `PATCH` still checks `response.ok`; hit-rate bar colour equals its legend/percentage in light and dark; every `table-fixed` table keeps its columns at 1000 px; Top tweets, Active campaigns, Week over week and "New this week" are reachable under More signals and open in print preview; entity chips still link to their pages; nothing interactive is nested inside a story row.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): recap tiles, forecast, hit-rate card and more-signals disclosure`

### Task 7: X Intel shell, tabs, feed chip, filters lib and toolbar (6.1 routing, header, feed chip, toolbar, period anchor)

**Files:**
- Create: `apps/web/src/lib/xintel/filters.ts`, `apps/web/src/components/xintel/xintel-page-header.tsx`, `apps/web/src/components/xintel/feed-status-chip.tsx`, `apps/web/src/components/xintel/xintel-toolbar.tsx`
- Modify: `apps/web/src/app/(app)/xintel/page.tsx`
- Delete (after grep): `apps/web/src/components/xintel/feed-status-banner.tsx`

**Interfaces:**
- Produces in `filters.ts`: `XIntelFilters = { search: string; period: "24h" | "7d" | "30d" | "custom"; from: string | null; to: string | null; signal: Signal | "all"; confirmed: boolean; apac: boolean; cve: boolean }`, `DEFAULT_FILTERS` (period `7d`), `isDefault(f)`, `periodTitle(f)` ("Last 24 hours" / "This week" / "Last 30 days" / "Selected range"), `toQuery(f, anchor: number)` returning the params shared by list and stats (preset: `posted_on_start` = ISO instant `anchor - N`; custom: `YYYY-MM-DD` From/To plus `tz` from `Intl`; `apac_only`, `confirmed_only`, `has_cve`, `signal` only when not `all`, `ot_only` always `false`, `search` only when non-empty).
- Produces: `XIntelPageHeader({ tab, ... })` (`PageHeader` kicker "SOCIAL SIGNALS", h1 and description per tab, `actions` = `FeedStatusChip` on Tweets) with `UnderlineTabs` "Tweets {total}" | "Monitored Accounts {n}" (`aria-label` "X Intel views"; counts from `GET /api/tweets?page_size=1` total and `GET /api/monitored-accounts` length, shown when loaded, same `retry` rule). `FeedStatusChip`: query `["xintel","feed-status"]` on `GET /api/data-health` returning `{ newest, nowMs }` computed in `queryFn`, `if (!response.ok) throw new Error(..., { cause: response.status })`, a 403 hides the chip with no retry; age ≤ 24 h nothing, 24-72 h warning `Chip` "Feed delayed · newest post {fmtAgo}", above 72 h or none destructive `Chip` "Feed stalled · newest post {fmtAgo}" / "No posts collected yet", under it the `monitor_x` reason from `useScraperHealth()` and "Open Data health". `XIntelToolbar` props `{ value, onChange, total, confirmed }`: `SearchInput` (placeholder per spec, 400 ms `useDebounced` on the string, `onEnter` applies at once), period `SegmentedControl` (`aria-label` "Period"), two `DateField optional` ("From", "To") when custom, Signal `Select` with `items`, three `aria-pressed` toggle buttons, count text "{total} posts · {confirmed} confirmed incidents", "Clear filters" ghost button when not default. `page.tsx` reads `?tab=tweets|accounts` (`useSearchParams`, invalid becomes `tweets`, `router.replace`), holds `filters` and `anchor` state (`anchor` set on mount, on period change and by a "Refresh" action, never computed in render), `usePageTitle("X Intel" | "Monitored accounts")`. Until Task 8 the Tweets tab renders the old `TweetList`.

- [ ] **Checklist:** `/xintel?tab=accounts` opens Accounts, `?tab=x` falls back; header and h1 follow the tab (Accounts: "Monitored accounts"); counts appear and match the unfiltered totals; chip hidden for a fresh feed, warning at 25 h, destructive at 73 h and for an empty table (shift data on `qacve`), hidden (no console loop) for a user without `view_ops`; Network panel shows the query key stable across renders (no refetch storm), typing refetches once after 400 ms and Enter at once; Custom shows both date fields and a same-day range still returns that day; Clear filters appears only off-default; search accepts `@handle`, a CVE id and a victim name (Task 2 contract); keyboard reaches every toolbar control; the tab title keeps "· Vareon Intelligence".
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): x intel shell with url tabs, feed chip and live filter toolbar`

### Task 8: X Intel feed list, pager and rail (6.1 feed, rail, pager, 6.5 states)

**Files:**
- Create: `apps/web/src/components/xintel/xintel-rail.tsx`
- Modify: `apps/web/src/components/xintel/tweet-list.tsx` (rewritten as the feed column), `apps/web/src/app/(app)/xintel/page.tsx`

**Interfaces:**
- `TweetList({ filters, anchor, onSearchHandle, onClear })`: `useTweets(filters, anchor, page)` and `useTweetStats(filters, anchor)` share `toQuery` (stats query key excludes `page`), both throw `new Error(\`HTTP ${status}\`, { cause })` and retry only `n < 2 && !isClientError(e)`; page resets to 1 on any filter change; `NumberedPager` with summary "Showing {from}-{to} of {total}", 20 per page (replaces `SimplePager`); layout `lg:grid-cols-[minmax(0,1fr)_432px]`, rail stacks below under 1024 px; states: skeleton cards, error `StatePanel` with Retry (`role=alert`), empty "No posts match these filters" + Clear filters, or "No posts collected yet" when nothing is filtered. The toolbar count comes from the stats query.
- `XIntelRail({ stats, period, onPickAccount })`: card 1 titled by `periodTitle`, subtitle "What the classifier pulled from {total} posts", six rows in the 6.1 order (`font-code` numbers, "0" shown as 0, "–" while loading); card 2 "Most-named victims" / "From victim names, {period}" (5 rows, empty "No victim named in this period"); card 3 "Most active accounts" / "Top 5 by posts in this period" with rows as `<button>`s that set the search to `@handle`.

- [ ] **Checklist:** header and rail agree with the list on every filter (compare the total, then toggle Confirmed / APAC / CVEs and a Signal option on `qacve` data); rail title follows the period and Custom reads "Selected range"; clicking an account row fills the search and the list narrows; pager summary correct on the last page; a 4xx on either query shows the error once, a 500 retries at most twice; empty feed offers Clear filters only when filtered; rail stacks under 1024 px; X9 and X10 reachable.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): x intel feed column with counters rail and numbered pager`

### Task 9: X Intel tweet card and detail dialog (6.1 feed card, 6.4, C1)

**Files:**
- Modify: `apps/web/src/components/xintel/tweet-card.tsx`, `apps/web/src/components/xintel/tweet-detail-dialog.tsx`
- Delete (after grep): `apps/web/src/components/xintel/tweet-badges.tsx` (its rules move into the card chip row)

**Interfaces:**
- `TweetCard({ tweet, onOpen })` is an `<article class="surface-raised">`: avatar (initial, image when `author_avatar` loads), display name, "@handle · {followers compact} followers · {fmtAgo}" (`title` = `fmtDateTime`, followers omitted when 0), destructive `Chip` "CONFIRMED INCIDENT" and "confidence {n}" (`incident_confidence` for a confirmed incident, else `confidence` when not null; integer, C1). The body is one real `<button type="button">` containing only the 4-line clamped text and the chip row (order and caps of 6.1, "+{n}" overflow); media thumbnails (max 2, links to the post) and "Open on X ↗" are siblings below it. CVE ids `font-code`.
- `TweetDetailDialog` keeps every `MetaRow` (Signals, Threat Groups, APAC, CVEs, Zero-Day, Data Breach, Industries, Country Roles, Incident block, LLM relevance, `fetched_at`, `tweet_id`) with `DialogDescription`, close "✕" (`aria-label` "Close"), footer actions "+ Newsletter" (writes the shared queue through `lib/newsletter/queue.ts::addToQueue`, "Queued" / "Already queued" feedback) and "Open on X ↗"; times through `fmtDateTime`.

- [ ] **Checklist:** accessibility tree of a card shows one button and separate links, no `role="button"` containing a link; Enter and Space on the button open the dialog and focus returns to it on close; chip row order and the 6-chip cap on a tweet with many signals; a tweet without followers, victim or CVEs renders without gaps; confidence prints "91" for 91; media and Open on X open the post in a new tab with `rel="noopener"`; "+ Newsletter" from the dialog appears in the Newsletter queue (other tab or later visit); dialog legible in light and dark; X11-X14 reachable.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): x intel tweet card with chip row and restyled detail dialog`

### Task 10: X Intel Monitored accounts tab (6.1 accounts, C4, 6.5)

**Files:**
- Modify: `apps/web/src/components/xintel/monitored-accounts.tsx`

**Interfaces:**
- The tab body (header and counts already come from Task 7): add row only with `useCan()("manage_tweets")` (inputs "Handle" placeholder "@FalconFeedsio", "Display name", "Notes (optional)", each with a real `<label htmlFor>`; "Add account" disabled while empty or pending; 409/400 `detail` inline); `Table framed` with `table-fixed` widths HANDLE 18 % | DISPLAY NAME 18 % | NOTES 30 % | ADDED 12 % | ACTIVE 10 % | (Remove) 12 %; handle `font-code`, ADDED `fmtShortDate`, ACTIVE a `Switch` (`aria-label` "Active: @handle", disabled without `manage_tweets`, errors toast), Remove a destructive text button opening the existing `ConfirmDialog` "Remove monitored account"; inactive rows muted, not hidden; foot line "{n} accounts monitored · {k} active"; empty "No accounts monitored yet" (+ the add row when permitted); list query keeps `response.ok`, adds `{ cause }` and the 4xx no-retry; every mutation invalidates `["xintel","accounts"]` and the tab count key.

- [ ] **Checklist:** an analyst without `manage_tweets` sees the list but no add row, no enabled switch and no Remove, while the admin sees all three and each works against the API (add, duplicate gives inline 409, toggle, remove with confirm; the account's tweets stay in the feed); the tab count and foot line update after each write; columns hold their widths at 1000 px; inactive row readable in dark mode; X16-X20 reachable.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): monitored accounts table with switch, permission gates and live counts`

### Task 11: Newsletter shell, period, suggestion bar and Template column (6.3 shell, suggestion bar, Template, C13, C14, C16, D29)

**Files:**
- Create: `apps/web/src/lib/newsletter/period.ts`, `apps/web/src/components/newsletter/newsletter-template-column.tsx`
- Modify: `apps/web/src/components/newsletter/newsletter-view.tsx` (render tree, `fetchSuggestion(period)`, `response.ok`, `storage` listener), `apps/web/src/components/newsletter/newsletter-suggestion-bar.tsx`, `apps/web/src/app/(app)/newsletter/page.tsx`

**Interfaces:**
- Produces in `period.ts` (fixed UTC+7 constant with a comment pointing at `WORKER__REPORT_UTC_OFFSET_HOURS`, spec 9): `recentMonths(now?: Date): { value: string; start: string; end: string; label: string }[]` (last 6 calendar months, newest first, `value` = `YYYY-MM`, label "1 – 31 Oct 2026") and `monthWindow(value)`; `daysIn(start, end): number`.
- `NewsletterView` renders `PageHeader` (kicker "NEWSLETTER", h1 "Newsletter composer", description per 6.3, `actions`: "History" outline opening the Task 13 sheet, "Preview" outline and "Generate edition" primary, the last two only with `manage_newsletter`; until Task 13 both open the existing preview), `usePageTitle("Newsletter composer")`, the restyled suggestion bar (`Notice`; ready copy and buttons per 6.3 incl. `formatBuiltAt`, k = non-empty blocks; loading, none, error and applied variants keep their copy and logic) and the three-column grid `xl:grid-cols-[300px_minmax(0,640px)_minmax(0,356px)] justify-between` (stacking order Template, content, queue). State, refs, `receiveSuggestion`, `applyArticles` and every handler stay; changes: `fetchSuggestion(period)` passes `period_start/period_end` of the selected month, the effect reloads when the period changes, `onBuild` and `doRebuild` send that period; `doRebuild`, `handlePreview`, `handleSendDraft`, `handleResend` and `handlePreviewSaved` check `response.ok` (throw `new Error(msg, { cause: status })` with the server `detail` when present) instead of only `if (error)`; a `storage` event listener re-reads `getQueue()` so articles queued from another tab appear.
- `NewsletterTemplateColumn`: card "Template" / "Period and sections"; `Select` PERIOD (`items`, `aria-label` "Period", caption "{n} days"), `Select` LANGUAGE (`items`, "Indonesian | English") with an "About summaries" `Disclosure` holding today's cost explainer; `SelectableList` (`aria-label` "Content blocks") of Highlights ("{n} of 3"), Indonesia, Asia Pacific, Global ("{full} full · {compact} compact"), divider "Also in the email", then "Executive summary" (sub "{n} characters" / "empty"), "Campaign clusters" (sub "Off" / "Last {cluster_days} days"), "Footer and CSS" (sub "Default" / "Customised"); default block = first non-empty of Indonesia, Asia Pacific, Global, else Highlights. The selected block id lives in `NewsletterView` and is passed to Task 12's column.

- [ ] **Checklist:** `recentMonths` checked on a 28-day month (Feb) and on a January run (previous December); changing the period reloads the suggestion, a month without one shows "No suggestion yet" + "Build suggestion" which builds that month; the bar's four states and Use / Merge / Rebuild still work with the confirm when the intro was edited; period and language selects show labels (not raw values) before opening; the block list is keyboard operable and counts match placed articles; blocking `POST /api/newsletter/suggestion/rebuild` with a 502 in the Network panel shows the failure toast and never "rebuilt"; queueing an article from `/newsroom` in a second tab adds it to the queue here without reload; layout stacks below 1280 px; `git diff --stat origin/Dev -- apps/web/src/lib/newsletter/composer.ts apps/web/src/lib/newsletter/queue.ts apps/web/src/lib/newsletter/summary.ts` is empty.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): newsletter composer shell with month period, template column and checked responses`

### Task 12: Newsletter content column and queue (6.3 content, queue, C15, D30, D31)

**Files:**
- Create: `apps/web/src/components/newsletter/newsletter-content-column.tsx`
- Modify: `apps/web/src/components/newsletter/newsletter-composer-sections.tsx` (renders one block's tier list; cards keep `SwapMenu`/`TierButton`/`ItemActions` logic), `apps/web/src/components/newsletter/newsletter-queue-panel.tsx` (restyled), `apps/web/src/components/newsletter/newsletter-template-panel.tsx` (collapsible shell removed; inputs reused), `apps/web/src/components/newsletter/newsletter-view.tsx` (wiring only)

**Interfaces:**
- `NewsletterContentColumn({ block, ... })` header = selected block. Section blocks: title, "{n} full cards · {m} compact", `SegmentedControl` "Full | Compact" (`aria-label` "Card style shown"; none for Highlights), the tier list below. Full view: cards (title, "{source} · {date}", summary sentence, flag chip, icon buttons "⇄", "↧", "✕" each with `aria-label`) and a one-line "ALSO NOTED · {m} compact items" button switching the segmented to Compact; compact view: the existing rows. Each card has a "Note and options" `Disclosure`-style toggle (`aria-expanded`, a real `<button>`) revealing the analyst note textarea and the "Regenerate summary" `Switch`; the flag chip reads "CHECK SUMMARY · page could not be read" after a preview proved `body_sources === "metadata"`, else "CHECK SUMMARY · source is often paywalled" from `source-hints`. Executive summary block: `NewsletterSummaryField` unchanged. Campaign clusters block: `Switch` "Include top campaign clusters" and, when on, `Select` "Lookback: 7 | 14 | 30 days". Footer and CSS block: the two textareas, HTML-allowed notes kept. Empty block: "No articles here yet. Place some from the queue." No drag-to-reorder and no "drag" caption.
- `NewsletterQueuePanel`: card "Your queue" / "{n} articles · {k} suggested, not placed"; groups "Suggested, not placed" and "Queued articles"; each row title + section chip (suggested: the item's `section`; queued: "Indonesia" when `ID` is among victim or mentioned countries, else none), a "+" menu to place into a slot with the existing limit toasts, a remove button, "Clear all", "Why suggested" reasons and the paywall hint as `text-2xs` lines; footer link "+ Add articles" to `/newsroom` (`target="_blank" rel="noopener"`) with the hint "Use + Newsletter on any article"; empty "Your queue is empty" + the same link.

- [ ] **Checklist (the N1-N18 walk for this task):** place, move, swap and remove articles through every menu and hit the limits (3 highlights, 4 full and 15 compact per section) with the same toasts as before; the counts in the Template column and card headers stay in sync; accessibility tree of an article card has the title text, the three icon buttons, the note toggle and nothing interactive nested; note and regenerate switch persist per article and reach the preview request body (inspect `POST /api/newsletter/preview`); Executive summary suggested-paragraph states and the replace confirm still work; clusters switch and lookback and the footer/CSS fields reach the request; queue "+" places to the chosen slot; "+ Add articles" opens Newsroom in a new tab; light and dark legible; composer.ts, queue.ts, summary.ts diff empty.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): newsletter content blocks, article cards and restyled queue`

### Task 13: Newsletter preview dialog and history sheet (6.3 History sheet, Preview dialog, C11, C12)

**Files:**
- Modify: `apps/web/src/components/newsletter/newsletter-preview-dialog.tsx` (rebuilt), `apps/web/src/components/newsletter/newsletter-history-panel.tsx` (becomes the sheet body), `apps/web/src/components/newsletter/types.ts`, `apps/web/src/components/newsletter/newsletter-view.tsx`

**Interfaces:**
- `PreviewDialogState` gains `origin: "preview" | "generate"` (set by the header button that opened it). `NewsletterPreviewDialog`: `DialogTitle` "Preview · {label} edition" (saved: "Saved · {label} edition"), close "✕" (`aria-label` "Close"), `DialogDescription` "The email as the recipient will see it. Paywalled summaries are flagged.", a `Notice` above the iframe listing size and CVE-marker warnings and the metadata-only titles, the sandboxed iframe scrolling inside (width `sm:max-w-3xl`, no pixel width stated), footer left "{n} articles · {k} summary to check" (n placed articles of the previewed request, k metadata-only count), right "Close" ghost and "Create Outlook draft" / "Create draft anyway" (outline with focus on Close for `origin: "preview"`, primary and focused once loaded for `"generate"`); disabled until the preview loaded; the draft is built from the previewed body. Saved mode: "Resend" with `manage_newsletter`. Both header buttons open this one dialog.
- History: `Sheet` (title "Saved newsletters") wrapping `NewsletterHistoryPanel` (label, period, `created_by`, highlight, section counts, Preview, Resend with `manage_newsletter`, `MindmapWidget`); query `["newsletter","history",refreshKey]` with `enabled: open`, `page_size: 20`, `if (!response.ok) throw new Error(..., { cause: status })`, no 4xx retry; choosing Preview closes the sheet and opens the dialog in saved mode; the collapsible "Saved Newsletters" block in the view is removed.

- [ ] **Checklist:** blocking `POST /api/newsletter/preview` with a 502 shows an error and leaves the draft button disabled; blocking `POST /draft-email` and `/{id}/resend` with a 502 shows the failure toast, not success; warnings (oversized email, CVE markers) appear above the iframe and switch the button to "Create draft anyway"; footer counts match the preview request; "Preview" focuses Close, "Generate edition" focuses the primary button; draft creation only after a loaded preview (never from the header directly); the sheet loads on open only, lists editions, Resend/Preview gated by `manage_newsletter`, Mindmap opens, Preview closes the sheet first; a user with `view_newsletter` only sees History but no Preview, Generate edition, Rebuild or Resend; focus returns to the trigger after closing each overlay; dialog and sheet readable in light and dark.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): newsletter preview dialog to the frame and history as a side sheet`

### Task 14: States and permissions sweep (6.5, constraint list)

**Files:**
- Modify: any file from Tasks 4-13 that the greps below flag

- [ ] **Sweep:** `grep -rn "Loading\.\.\.\|Loading…\|Failed to load" apps/web/src/components/{xintel,recap,newsletter} "apps/web/src/app/(app)/"{xintel,recap,newsletter}` becomes `StatePanel` or skeletons; `grep -rn "asChild\|backdrop-blur" ...` none; `grep -rn "formatWib\|UTC\|WIB" apps/web/src/components/xintel` none, and in Recap/Newsletter only the stated "UTC" copy of Recap windows and the WIB period comment; `grep -rn "if (error) throw error" apps/web/src/components/{xintel,recap,newsletter}` none; every `useQuery` in those folders has the `isClientError` retry rule; every dialog and sheet has `DialogDescription`/description, close "✕" and a ghost Cancel; every `table-fixed` has widths; `SelectItem` children are single strings; no `role="button"` wrapping a link.
- [ ] **Permissions:** walk as admin, analyst and a `view_newsletter`-only role: Regenerate / empty-state Generate need `manage_intel`; the scorecard override needs only `view_intel`; account add / switch / Remove need `manage_tweets`; Preview, Generate edition, Rebuild, Resend need `manage_newsletter`; History needs `view_newsletter`; each hidden control is visible for a user who has the permission.
- [ ] **Retry and keyboard:** a 403/404 on any new query shows the error panel once, a 500 retries at most twice; keyboard pass over tabs, period, toggles, Signal select, History select, previous week, Regenerate dialog, block list, segmented, card menus, Disclosures, Sheet and dialogs.
- [ ] **Feature walk:** X1-X21, R1-R21 and N1-N18, each reachable; write the checklist (with the re-homed ones noted) into the PR description draft.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `fix(web): consistent states, dialog anatomy and permission gates across X Intel, Recap and Newsletter`

### Task 15: Docs, CHANGELOG and prod-upgrade notes (4.3)

**Files:**
- Modify: `CHANGELOG.md` (extend `## [0.8.16] - 2026-11-08`), `docs/prod-upgrade/0.8.16.md`, `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md`, `docs/PROGRESS.md` (Indonesian work-log line)

- [ ] **CHANGELOG (Indonesian):** keep the header paragraph (still no new migration, no `.env` key; add one clause for the content pages). `### Ditambahkan`: X Intel, pencarian juga mencocokkan handle, nama korban dan CVE; filter `has_cve` dan `signal` (`ot`, `zero_day`, `databreach`, `report`) di `GET /api/tweets` dan `/api/tweets/stats`; statistik periode (insiden terkonfirmasi, APAC, CVE, data breach, zero-day, OT, korban paling sering disebut); halaman X Intel, Recap dan Newsletter didesain ulang (komposer tiga kolom, Export PDF recap lewat cetak browser). `### Diubah`: tombol Apply/Reset X Intel diganti filter langsung; riwayat newsletter dibuka sebagai panel samping.
- [ ] **Prod upgrade (both files, English, extend the existing 0.8.16 section):** *Migrations* none from 4a; *Settings* none; *Contract* two new optional query parameters on the tweets endpoints (additive) and extra keys in the untyped stats response; *Behaviour* free-text search can return more rows than before; *Rollback* image rollback only, no data change. Do not touch the Exec items.
- [ ] **Verify:** `uv run python -c "from cti_api.routers.changelog import _parse; print(_parse()[0]['version'])"` prints `0.8.16`; `uv run ruff format --check .`.
- [ ] Commit `docs(release): note the X Intel, Recap and Newsletter redesign in 0.8.16`

### Task 16: Final verification (spec 8)

- [ ] **Backend:** `uv run pytest tests/integration -k "tweet or monitored or api_permissions" -q` (Docker, `qacve`), then `uv run pytest tests/unit tests/contract packages` with the known deselects. The named tests of Tasks 1-2 pass; `test_recap_*` and `test_tweet_alerts.py` unchanged.
- [ ] **Static:** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src packages/cti-scraper/src`; re-run `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`, then `git diff --exit-code docs/openapi.json apps/web/src/lib/api/schema.d.ts`; `grep -n "^revision" uv.lock` prints `revision = 3`; no new Alembic revision.
- [ ] **Web:** `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit`; `pnpm build`, all exit 0. Pure helpers checked in QA: `isoWeek` at the year boundary (2026-12-28 gives 53, 2027-01-04 gives 1), `recentMonths` on a 28-day month, `toQuery` period parameters and the custom same-day range.
- [ ] **Visual (controller, local `qacve`, API via uvicorn, web via `pnpm dev`; synthetic data: tweets over 40 days with confirmed / APAC / CVE / zero-day / data-breach / OT / report mixes and a stale-feed case, monitored accounts with one inactive, weekly recaps for several weeks (dropped grounding, empty, no previous week), a daily recap, scorecard events, a monthly suggestion and a month without one, a queue of Newsroom and X Intel articles with a paywalled source, saved editions; LLM stubbed):** screenshots of all five frames' states at 1440 and 1000 px, light and dark, against 27680/28830, 38457/40021, 27898/29048, 28635/29284 and 35311/36240. Print preview in Chrome and Safari (light output from dark mode, no masthead, cards unbroken, More signals open, title and theme restored). Contrast of chips and the hit-rate bar in both themes; the tab title keeps "· Vareon Intelligence" on all three pages; a 4xx is not retried; the a11y tree check on the tweet card and the article card; every X / R / N feature reachable (PR checklist).
- [ ] **Delivery:** report results; commits per backend item and per page happened in earlier tasks; merge into `origin/Dev` under the standing approval. On dev 172.25.1.77 (read-only): X Intel with a real period, Recap of the latest week, Newsletter suggestion load; no Regenerate, Rebuild or draft creation without the user's go (LLM calls and a Graph draft).
- [ ] No commit unless a fix was needed (then a `fix(...)` commit per fix).

## Spec coverage

| Spec section | Tasks |
|---|---|
| 2 S1-S4 | 14 (features kept), 15 |
| 2 D7, D32 | Global Constraints, 5-13 |
| 2 D19, D23, D24 | 7, 8 |
| 2 D25, D26 | 5 |
| 2 D27 | 6 |
| 2 D28-D31 | 11, 12, 13 |
| 2 D33, D34 | 9, 3 |
| 3 C1 | 9 |
| 3 C2, C3, C4, C5, C6 | 7, 8, 10 |
| 3 C7, C8, C9, C10 | 5, 6 |
| 3 C11, C12 | 13 |
| 3 C13, C14, C15, C16 | 11, 12 |
| 3 C17 | 4 |
| 4.1 | 1 |
| 4.2 | 2 |
| 4.3 | 15 |
| 5 | Global Constraints, 3, 16 |
| 6 constraints 1-10 | Global Constraints, 4, 5, 7-14 |
| 6.1 | 7, 8, 9, 10 |
| 6.2 | 5, 6 |
| 6.3 | 11, 12, 13 |
| 6.4 | 9 |
| 6.5 | 5, 8, 10, 12, 14 |
| 6.6 | 4, 5, 7, 11 |
| 7 | Global Constraints (excluded items not planned) |
| 8 | 3, 16 |
| 9 | Review Focus, 3 (contract), 5 (print), 11 (WIB), 12 (Newsletter regression) |
