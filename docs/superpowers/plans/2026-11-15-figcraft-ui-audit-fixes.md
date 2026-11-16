# FigCraft UI audit fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the dev UI audit findings on branch `claude/figcraft-design-data` (release 0.8.16): full-width shell, one chart style, color by KPI kind and by category, card fill/radius, font split, per-page polish.

**Architecture:** Web-only (`apps/web`). Shared pieces first (shell, tokens, pure helpers, chart components, tile kinds), then per-page fixes that consume them. Pure helpers get unit tests run by Node's built-in runner (`node --test`, Node 22 strips TS types natively); everything visual is checked by lint/typecheck per task and by a browser QA pass at the end.

**Tech Stack:** Next.js 16 App Router, Base UI, Tailwind v4 tokens in `src/app/globals.css`, Chart.js 4 via react-chartjs-2, `src/lib/chart-theme.ts`.

**Spec:** `docs/superpowers/specs/2026-11-15-figcraft-ui-audit-fixes-design.md`

## Global Constraints

- All paths below are relative to `apps/web/` unless they start with `docs/` or `CHANGELOG.md`.
- Before any pnpm/node command: `export PATH="$HOME/.local/share/fnm/aliases/default/bin:$PATH"` and run from `apps/web`.
- Every task ends green on: `pnpm lint` (0 errors) and `pnpm exec next typegen && pnpm exec tsc --noEmit`.
- No backend, API, migration, `.env` or OpenAPI change. No version bump (ships in 0.8.16).
- House rules: no `backdrop-blur`/`backdrop-filter`, no `prose-invert`, no hex/`rgb()`/raw palette classes (`amber-500`) in components; colors only via tokens. Tinted text uses `text-X-text` tokens. Text must meet AA (4.5:1) in light AND dark.
- 2-3 column layouts collapse below 1024 px with `lg:`, never `md:`. Mobile (<1024) is out of scope; 1024 px must have no horizontal page scroll.
- Base UI, not Radix: `render={<X/>}`, never `asChild`; `SelectItem` children a single string.
- "Anti-goal: rainbow UI": at most one accent per KPI tile; color only where it means something.
- Comments/docstrings in Indonesian (match surrounding code); commit messages English conventional, ending with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `apps/web/AGENTS.md`: this Next.js differs from training data; read `node_modules/next/dist/docs/` before using an unfamiliar Next API.

## Review Focus

1. Category names arriving in a different case/spacing than the known map ("financial services", "Financial Services ") must still get the mapped color, not a hash color (pinned in Task 3 tests).
2. Unknown categories must hash to the same color on every page and every render (pinned in Task 3 tests: same input, same index; index in 0..9).
3. Enum values the helper has never seen (`"weird_new_kind"`, already-human strings like `"Vendor research"`, empty string) must render readably, never `undefined` or `WEIRD_NEW_KIND` (pinned in Task 3 tests).
4. All articles auto-select must not fight the user: it fires only when `article` is absent, never on narrow screens, never adds a history entry, and does nothing when the list is empty or still loading (Task 8 checklist step).
5. Dark theme: the rebalanced palette and the new teal token must stay distinguishable and AA in dark, not just light (pinned by the Task 2 palette script, which checks both themes).

---

### Task 1: Full-width shell

**Files:**
- Modify: `src/components/app-shell/app-shell.tsx:8` (`SHELL_COLUMN`)

**Interfaces:**
- Produces: `SHELL_COLUMN` keeps its name and export; still used by `app-shell.tsx` (header, main) and `src/app/(app)/layout.tsx`.

- [ ] **Step 1: Change `SHELL_COLUMN`** to full width with today's small-screen gutter (`px-4`), a 40 px gutter from `lg:` (`lg:px-10`), and a 1920 px cap that includes the gutters (`max-w-[1920px]`, `mx-auto`). Drop `min-[1440px]:px-0`. Update the comment above it (Indonesian) to say why (audit: 1328 px column wasted ~2000 px screens).
- [ ] **Step 2: Grep for code that assumed 1328 px** (`grep -rn "1328\|max-w-\[13" src`) and adjust only what used it as the shell width. Do not add inner max-widths (spec: text surfaces keep what they have).
- [ ] **Step 3: Lint + typecheck** (Global Constraints). Expected: clean.
- [ ] **Step 4: Commit** `fix(web): let the app shell use the full width up to 1920px`.

Visual check of the wide tables (Risk matrix, MITRE heatmap, Exec Sector risk, Source reliability, Ticketing, IOC table, Scrapers) happens in Task 12.

---

### Task 2: Color tokens and palette check script

**Files:**
- Modify: `src/app/globals.css` (`:root` and `.dark` blocks; `@theme inline` registrations)
- Modify: `src/lib/chart-theme.ts` (add `intel` to `ChartTheme`)
- Create: `scripts/check-palette.mjs`
- Modify: `package.json` (script `"check:palette": "node scripts/check-palette.mjs"`)

**Interfaces:**
- Produces: CSS tokens `--intel`, `--intel-text` (both themes) registered as `--color-intel`, `--color-intel-text` (so `bg-intel`, `text-intel-text` work); `ChartTheme.intel: string` read from `--intel`; rebalanced `--chart-1`..`--chart-10` (same names, new values).

- [ ] **Step 1: Write `scripts/check-palette.mjs`.** It reads `src/app/globals.css`, extracts hex values of `--chart-1..10`, `--intel`, `--intel-text`, `--background`, `--surface`, `--card` (if present) from the `:root` block and from the `.dark` block (resolve `var(--x)` aliases within the same block, falling back to `:root`). Checks, per theme, printing every failure and exiting 1 if any:
  - every pair of `--chart-*` has CIEDE2000 ΔE ≥ 15 (implement sRGB → Lab → ΔE2000 inline, no dependency);
  - every `--chart-*` has contrast ≥ 3:1 against `--background` and `--surface` (WCAG 1.4.11 graphics);
  - `--intel-text` has contrast ≥ 4.5:1 on `--background` and on `--surface`;
  - `--intel` differs from `--info`, `--success` and `--destructive` by ΔE ≥ 15 (teal must read as its own kind).
- [ ] **Step 2: Run it against today's CSS.** `pnpm check:palette`. Expected: FAIL (it must report at least dark `--chart-3` vs `--chart-4`, and missing `--intel`).
- [ ] **Step 3: Add the teal tokens and rebalance the palette** in `globals.css`, light and dark, until the script passes. Keep each `--chart-*` near its current hue family where possible (callers that pick `--chart-N` by number keep their character); the palette may reuse red/amber/teal/blue families (spec builder call). Register `--color-intel` / `--color-intel-text` next to the other `*-text` registrations. Add `intel: v("--intel")` to `useChartTheme`.
- [ ] **Step 4: Run the script.** Expected: exit 0, prints a pass summary for light and dark.
- [ ] **Step 5: Lint + typecheck.** Commit `feat(web): add the intel accent token and rebalance the chart palette`.

---

### Task 3: Pure helpers: category colors, enum labels, short tick labels

**Files:**
- Create: `src/lib/category-colors.ts`, `src/lib/enum-label.ts`, `src/lib/chart-ticks.ts` (no imports at all: they must run under `node --test` without path aliases)
- Create: `tests/unit/category-colors.test.mjs`, `tests/unit/enum-label.test.mjs`, `tests/unit/chart-ticks.test.mjs`
- Modify: `package.json` (script `"test:unit": "node --test tests/unit/"`)

**Interfaces:**
- Produces:
  - `categoryColorIndex(name: string): number` → 0..9, the `--chart-(i+1)` slot. Known names via a fixed map (case-insensitive, trimmed, inner whitespace collapsed); unknown names via a stable string hash (FNV-1a 32-bit, mod 10).
  - `KNOWN_CATEGORY_SLOTS: Readonly<Record<string, number>>` (normalized lowercase keys).
  - `enumLabel(raw: string): string`.
  - `shortTickLabel(label: string): string`.

- [ ] **Step 1: Write the failing tests.**

```js
// tests/unit/category-colors.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { categoryColorIndex, KNOWN_CATEGORY_SLOTS } from "../../src/lib/category-colors.ts";

test("known names ignore case and spacing", () => {
  assert.equal(categoryColorIndex("financial services"), categoryColorIndex("Financial Services "));
  assert.equal(categoryColorIndex("Data  Breach Article"), categoryColorIndex("data breach article"));
});
test("known names use the map, not the hash", () => {
  for (const [k, v] of Object.entries(KNOWN_CATEGORY_SLOTS)) assert.equal(categoryColorIndex(k), v);
});
test("unknown names are stable and in range", () => {
  const a = categoryColorIndex("Some New Sector");
  assert.equal(a, categoryColorIndex("Some New Sector"));
  assert.ok(Number.isInteger(a) && a >= 0 && a <= 9);
  assert.ok(categoryColorIndex("") >= 0);
});
test("news types never share a slot", () => {
  const types = ["global", "Security Technology & Best Practices", "Vendor Report Article",
    "Data Breach Article", "Tech Stack Article", "OT Article"];
  assert.equal(new Set(types.map(categoryColorIndex)).size, types.length);
});
```

```js
// tests/unit/enum-label.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { enumLabel } from "../../src/lib/enum-label.ts";

test("humanizes snake and screaming case", () => {
  assert.equal(enumLabel("url_with_path"), "URL with path");
  assert.equal(enumLabel("URL_WITH_PATH"), "URL with path");
  assert.equal(enumLabel("vendor_research"), "Vendor research");
  assert.equal(enumLabel("VENDOR_RESEARCH"), "Vendor research");
});
test("keeps acronyms", () => {
  assert.equal(enumLabel("ipv4"), "IPv4");
  assert.equal(enumLabel("ipv6_cidr"), "IPv6 CIDR");
  assert.equal(enumLabel("sha256"), "SHA256");
  assert.equal(enumLabel("md5"), "MD5");
  assert.equal(enumLabel("email_domain"), "Email domain");
});
test("unknown, already human, empty", () => {
  assert.equal(enumLabel("weird_new_kind"), "Weird new kind");
  assert.equal(enumLabel("Vendor research"), "Vendor research");
  assert.equal(enumLabel(""), "");
});
```

```js
// tests/unit/chart-ticks.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { shortTickLabel } from "../../src/lib/chart-ticks.ts";

test("ISO day -> '8 Nov'", () => assert.equal(shortTickLabel("2026-11-08"), "8 Nov"));
test("ISO month -> 'Mar 2026'", () => assert.equal(shortTickLabel("2026-03"), "Mar 2026"));
test("other labels pass through", () => {
  assert.equal(shortTickLabel("Financial Services"), "Financial Services");
  assert.equal(shortTickLabel("2026-13-40"), "2026-13-40");
});
```

- [ ] **Step 2: Run** `pnpm test:unit`. Expected: FAIL (modules missing).
- [ ] **Step 3: Implement the three helpers.** Acronym set for `enumLabel`: `URL, IP, IPV4→IPv4, IPV6→IPv6, CIDR, ASN, DNS, MD5, SHA1, SHA256, SHA512, CVE, KEV, TTP, OT, IT, API, SSL, TLS, ID`; first word capitalized, others lowercase unless an acronym; a string with no `_` and not all-caps is returned unchanged. `shortTickLabel` parses with local date components (no `new Date(iso)` UTC shift), English month abbreviations, invalid dates pass through. `KNOWN_CATEGORY_SLOTS`: every `GLOBAL_NEWS_TYPES` entry (`src/lib/newsroom/news-types.ts`) plus the news-type and sector/industry option lists the code already uses (grep `src/lib` and `src/components/exec` for the industry/sector options); copy the strings (the file has no imports) and say in a comment which list each block came from. Within one list of ≤10 names, no shared slot; lists longer than 10 may wrap.
- [ ] **Step 4: Run** `pnpm test:unit`. Expected: PASS, all tests.
- [ ] **Step 5: Lint + typecheck.** Confirm `tsc` does not choke on the `.mjs` tests (they are outside `src`; if `tsconfig.json` `include` picks them up, exclude `tests/`). Commit `feat(web): add category color, enum label and tick label helpers`.

---

### Task 4: One chart style

**Files:**
- Modify: `src/components/dashboard/charts.tsx` (all seven exports)
- Modify: `src/components/ui/bar-series.tsx` (ticks only), `src/lib/chart-theme.ts` (helper below)
- Callers that pass series/tones: `src/components/dashboard/more-section.tsx`, `src/components/exec/charts-section.tsx`, `src/components/exec/more-signals.tsx`, `src/components/cve/cve-dashboard-view.tsx` (only if a prop changes)

**Interfaces:**
- Consumes: `categoryColorIndex` (Task 3), `shortTickLabel` (Task 3), `ChartTheme.intel` (Task 2).
- Produces: `categoryColor(t: ChartTheme, name: string): string` exported from `src/lib/chart-theme.ts` (= `t.series[categoryColorIndex(name)]`). `HorizontalBarChart` / `TimelineChart` `tone` unions gain `"intel"`; existing values unchanged.

- [ ] **Step 1: Apply the new style to every chart in `charts.tsx`:** `tension: 0` (straight), `pointRadius: 0` with `pointHoverRadius: 4` on lines (keep `emphasizeLast` behaviour in `TimelineChart`); legends `usePointStyle: true` (`pointStyle: "line"` for line charts, `"circle"` for bars/doughnut) with `color: t.textDim`; every chart uses `tooltipBase(t)`; x date ticks via `callback` → `shortTickLabel(labels[i])`, `maxRotation: 0`, `autoSkip: true`, `maxTicksLimit: 8`; grid via `gridLine(t)`, `border: { display: false }`. `MultiLineChart` and `StackedBarChart` color each series by `categoryColor(t, s.label)` instead of index. `SeverityStackedChart` and `GradedDoughnutChart` keep their meaning colors (severity/grade). Leave `TAActivityTimelineChart` styled the same way even though it has no caller (do not delete it; mention it as dead code in the report).
- [ ] **Step 2: `BarSeries` ticks:** labels through `shortTickLabel`, `maxRotation: 0` already set; keep `tickEvery` logic.
- [ ] **Step 3: Single-series bars take the kind color** (spec §3): Dashboard "More" incidents timeline and Tracked APT groups bar use `tone="critical"`; check `month-charts.tsx` "Top techniques" and `src/components/exec/top-techniques-card.tsx` use the threat red too (`highlightTone="destructive"` or the equivalent existing prop); do not add new props for this.
- [ ] **Step 4: Lint + typecheck.** Commit `fix(web): one chart style with category-stable colors`.

---

### Task 5: KPI kinds

**Files:**
- Modify: `src/components/ui/stat-tile.tsx`
- Modify the 11 callers: `src/components/recap/recap-tiles.tsx`, `src/components/cve/cve-stat-tiles.tsx`, `src/components/cve/cve-dashboard-view.tsx`, `src/components/intelligence/early-warning-view.tsx`, `src/components/cve/pkgvuln/vulns-panel.tsx`, `src/components/intelligence/ioc/ioc-table.tsx`, `src/components/admin/users-overview.tsx`, `src/components/data-health/data-health-view.tsx`, `src/components/exec/exec-kpi-row.tsx`, `src/components/scrapers/health-summary-bar.tsx`, `src/components/entities/entity-view.tsx`
- Modify: `src/components/dashboard/by-the-numbers.tsx`

**Interfaces:**
- Consumes: tokens `bg-intel`, `text-intel-text` (Task 2).
- Produces: `export type KpiKind = "threat" | "vuln" | "intel" | "ops"` and `StatTile` prop `kind?: KpiKind`. Mapping: threat → destructive, vuln → warning, intel → new `intel` tone (`bg-intel` / `text-intel-text`), ops → info. An explicit `tone` wins over `kind` (severity/status tiles keep their tone).

- [ ] **Step 1: Add the `intel` tone and the `kind` prop** to `StatTile` (class strings written in full, as the file already does).
- [ ] **Step 2: Set `kind` at each caller** by the spec table: threat = articles, incidents, victims, actors, techniques; vuln = CVEs, KEV, tickets, exposure; intel = IOCs, entities, PIRs/RFIs, sources, campaigns; ops = scrapers, queues, data health, freshness. Tiles that already carry severity/status meaning (CVE Critical/High/Medium, Scrapers health states, IOC type filter tiles if they are selectors rather than counts) keep their current tone; record each such exception in the report. Admin users tiles are not in the table: use `ops`.
- [ ] **Step 3: Dashboard "By the numbers"** has no tiles; give each row's number its kind text color (`text-destructive-text` for articles, incidents, victims; `text-warning-text` for open critical CVEs), nothing else.
- [ ] **Step 4: `StatBox` in `src/components/dashboard/stat-box.tsx` has no callers:** leave it, list it as dead code in the report.
- [ ] **Step 5: Lint + typecheck.** Commit `feat(web): color KPI tiles by the kind of thing they count`.

---

### Task 6: Card fill and radius

**Files:**
- Modify: `src/components/dashboard/lead-story.tsx`, `src/components/newsroom/front-page.tsx` (Top story), `src/components/exec/threat-actors-card.tsx`, and the grid that places each of them (find the parent; e.g. `dashboard-view.tsx`, the exec briefing view)

- [ ] **Step 1: Radius:** Lead story and Top story use `rounded-lg` like neighbouring cards (their skeletons too).
- [ ] **Step 2: Fill:** for each of the three cards, first check whether the data it already receives has more to show (longer summary via a larger `line-clamp`, more rows up to what the query already returns); if yes, show it so the card fills its row height. If not, stop the stretch: the card sizes to content (`self-start` on the card, or `items-start` on its grid row). No new requests, no new data.
- [ ] **Step 3: Lint + typecheck.** Commit `fix(web): stop focus cards stretching half empty and align their radius`.

---

### Task 7: Font split

**Files:**
- Modify: `font-code` callers (≈296 uses in ≈112 files; `grep -rn "font-code" src`)
- Modify: `src/app/layout.tsx` (comment only), `apps/web/CLAUDE.md` ("Fonts" bullet)

- [ ] **Step 1: Classify each `font-code` use** by what it renders. Keep `font-code` (IBM Plex Mono) only for machine strings: hashes, IOC values, IP addresses, URLs/domains shown as indicators, hunting-pack/Sigma/query text, cron schedules, file names/paths, package names with versions. Everything else (CVE IDs, ATT&CK technique IDs, counts, percents, scores, dates, display IDs like `PIR-01`) drops `font-code` and gets `tabular-nums` if it is a number in a column or a row of numbers. When one element renders both kinds depending on data (e.g. a generic value cell), keep `font-code`.
- [ ] **Step 2: Update the comment in `src/app/layout.tsx`** (Indonesian) and the "Fonts" bullet in `apps/web/CLAUDE.md` (English): `font-mono` is Google Sans Flex (not monospace); `font-code` (IBM Plex Mono) only for machine strings read character by character (hash, IOC value, IP, URL, query, cron); IDs and numbers use the body font with `tabular-nums`.
- [ ] **Step 3: Lint + typecheck.** Commit `fix(web): keep Plex Mono for machine strings only`.

---

### Task 8: Newsroom (All articles auto-select, topic sparklines)

**Files:**
- Modify: `src/components/newsroom/all-articles-view.tsx` (and/or the list component it renders), `src/components/newsroom/topics-section.tsx`

**Interfaces:**
- Consumes: `AllArticlesView` props `state: AllState`, `onChange: (p: AllPatch) => void` (`src/lib/newsroom/all-state.ts`); `onChange` already writes through the guarded URL writer in `newsroom-view.tsx` with `router.replace` (no history entry).

- [ ] **Step 1: Auto-select:** when `state.article === null`, the viewport is ≥1024 px (`matchMedia("(min-width: 1024px)")`, read in an effect, not during render), and the current list has loaded with at least one item, call `onChange({ article: firstItem.id })` once. Do nothing while loading, on an empty list, below 1024 px, or when `article` is set. Do not touch `newsroom-view.tsx`'s writer.
- [ ] **Step 2: Verify the checklist by reading the code** (no web test runner): (a) loading → no write; (b) empty list → reader keeps "Select an article to read it."; (c) <1024 → no write; (d) a filter change while an article is selected → no write; (e) the write passes through `onChange` (replace, not push).
- [ ] **Step 3: Topic sparklines:** the `BarSeries` in `topics-section.tsx` shows no axis labels (add a `BarSeries` prop `axes?: boolean` defaulting to `true`; `false` hides x and y ticks and grid). Keep the hidden data table.
- [ ] **Step 4: Lint + typecheck.** Commit `fix(web): open the first article on wide screens and drop sparkline axes`.

---

### Task 9: CVE page

**Files:**
- Modify: `src/components/cve/cve-ticketing-view.tsx`, `src/components/cve/cve-toolbar.tsx`, `src/components/cve/cve-db-view.tsx`, `src/components/cve/pkgvuln/pkgvuln-view.tsx`, `src/components/cve/monitored-tech-panel.tsx` (locate exact owners by grepping the labels below)
- Use: `src/components/ui/date-field.tsx` (`DateField`)

- [ ] **Step 1:** Ticketing segmented control moves into the toolbar row (no third stacked navigation row).
- [ ] **Step 2:** Search placeholder fits without truncation at 1024 px (shorten the text or let the input grow; keep the `aria-label`).
- [ ] **Step 3:** Replace native `type="date"` inputs in `cve-toolbar.tsx` and `cve-db-view.tsx` with `DateField` (same value format the code uses today). Leave `ticket-form.tsx` unless it is in the same toolbar (it is a form, not a filter).
- [ ] **Step 4:** Package Vulnerabilities actions (Import lockfile / Scan all / + Add package) and Monitored Tech actions (Add custom / + Add from catalog) sit on the header/filter row, right-aligned, not on their own row. At 1024 px they may wrap under the filters but never overflow.
- [ ] **Step 5: Lint + typecheck.** Commit `fix(web): tidy CVE toolbars and use the house date field`.

---

### Task 10: Exec and Entities

**Files:**
- Modify: `src/components/exec/exec-filter-bar.tsx` (and the view that places Save watchlist / Export CSV / Generate brief), `src/components/entities/entities-list-view.tsx` (and row components it uses)

- [ ] **Step 1: Exec:** Save watchlist / Export CSV / Generate brief on the filter row, right-aligned; the "updated just now" text gets `whitespace-nowrap`.
- [ ] **Step 2: Entities:** sector rows show "—" in the ATT&CK ID column instead of the slug (only techniques have an ATT&CK ID); 30D and 90D values visibly separated (own columns or a clear separator, `tabular-nums`); aliases wrap instead of truncating to "Cloud …" (if a cap is kept, the full list is in `title` and reachable by keyboard focus).
- [ ] **Step 3: Lint + typecheck.** Commit `fix(web): exec actions on the filter row and clearer entity rows`.

---

### Task 11: IOC, Source reliability, heatmaps

**Files:**
- Modify: `src/components/intelligence/ioc/ioc-table.tsx` (tiles grid ~line 333, type chip ~line 260), `src/components/intelligence/ioc/ioc-allowlist-panel.tsx` (`TYPE_LABEL`), `src/components/intelligence/source-reliability/sr-grid.tsx`, `sr-review-table.tsx`, `sr-table.tsx` (origin/content-kind chips), `src/components/ui/heat-grid.tsx` and/or `src/components/intelligence/risk-matrix-view.tsx`, `src/components/exec/sector-heatmap.tsx`

**Interfaces:**
- Consumes: `enumLabel` (Task 3).

- [ ] **Step 1: IOC tiles:** 8 tiles lay out as full rows: `grid-cols-2 sm:grid-cols-4` and 8 across from a wide breakpoint (e.g. `min-[1440px]:grid-cols-8`), no orphan row at 1024/1440/≥1920. If there are fewer or more than 8 type tiles in data, the grid still has no single orphan at those widths (pick column counts that divide the actual tile count).
- [ ] **Step 2: Humanized labels:** IOC type tiles and chips, allowlist type chips, SR content-kind and origin chips render `enumLabel(value)` and in sentence case (pass the label as children and override the chip's `uppercase` for these flag chips only, via `className="normal-case"`). Replace the local `TYPE_LABEL` map only if `enumLabel` gives the same text; otherwise keep the map and fall back to `enumLabel`.
- [ ] **Step 3: Heatmaps:** empty cells (count 0 / no data) in Risk matrix and the Analyst board Sector heatmap render plain (no outlined box); filled cells unchanged; keyboard focus on cells still visible.
- [ ] **Step 4: Lint + typecheck.** Commit `fix(web): humanize IOC and source labels and plain empty heatmap cells`.

---

### Task 12: Build, local QA, changelog (controller)

**Files:**
- Modify: `CHANGELOG.md` (`[0.8.16]` entry, Indonesian)

- [ ] **Step 1:** `pnpm build`, `pnpm test:unit`, `pnpm check:palette`. Expected: all pass.
- [ ] **Step 2: Browser QA** on the local `qafig` stack, light and dark, at ≥1920, 1440 and 1024 px: Dashboard, Newsroom (Front page, All articles), CVE (dashboard, ticketing, DB, packages, monitored tech), Exec (briefing, analyst board, brief dialog), Intelligence (IOC, SR, Risk matrix, MITRE), Entities, Scrapers, Data health; then a light+dark spot check of the pages the audit skipped (Login, Admin, X Intel, Recap, Newsletter) for breakage from shared changes. At 1024 px: no horizontal page scroll anywhere. Fix regressions in a follow-up commit per area.
- [ ] **Step 3:** Extend the `[0.8.16]` entry in `CHANGELOG.md` (Indonesian, keep the header format) with the audit fixes.
- [ ] **Step 4:** Commit `docs(changelog): note the 0.8.16 UI audit fixes`.

After this plan: merge into `origin/Dev` (pre-approved), recheck on dev in Chrome, then ask the user before pushing to the PR #91 branch.
