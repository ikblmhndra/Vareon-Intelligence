# Components fill their cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Heatmaps, focus cards, the Needs-action map and row charts size relative to their card instead of fixed px.

**Architecture:** Web-only CSS/layout changes in four shared spots; no data, no new components. Verified by lint/typecheck/build and a browser pass (no web component test runner).

**Tech Stack:** Next.js 16, Tailwind v4, Chart.js (react-chartjs-2, `maintainAspectRatio: false`).

**Spec:** `docs/superpowers/specs/2026-11-16-figcraft-fluid-cards-design.md`

## Global Constraints

- Paths relative to `apps/web/`. Before pnpm: `export PATH="$HOME/.local/share/fnm/aliases/default/bin:$PATH"`.
- Each task ends green on `pnpm lint` (0 errors) and `pnpm exec next typegen && pnpm exec tsc --noEmit`.
- Text size and spacing unchanged. No chart shorter than today (today's `height` becomes the minimum).
- 1024 px: no page-level horizontal scroll; 2-3 column layouts collapse below 1024 with `lg:`.
- Tailwind classes written in full; no hex/raw palette classes; Tailwind v4 sorts arbitrary px breakpoints before rem ones, so never mix `min-[NNNpx]:` with `sm:/lg:` on the same property (use rem).
- Comments Indonesian; commits English conventional with trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. HeatGrid with many columns (Risk matrix ~15-25 countries, MITRE) must keep its inner horizontal scroll at 1024 and never squeeze cells below `min-w-10` (check `table-layout`/`min-w` interplay).
2. HeatGrid keyboard navigation (arrow keys, roving focus) and sticky row/column headers must still work after the width change.
3. A focus card whose content is TALLER than its neighbour must not be clipped (stretching must not cap height).
4. Chart.js canvases inside a flex-grown body must not grow in a resize loop (body needs `min-h-0`/`relative` and an explicit min height).
5. Needs-action map at 1024 (stacked under the list) must not become huge: cap its height (e.g. `max-h-[380px]` or aspect only from `lg:`).

---

### Task 1: HeatGrid and Needs-action map fill their box

**Files:**
- Modify: `src/components/ui/heat-grid.tsx` (table ~114-150, HeatCell ~60-78)
- Modify: `src/components/dashboard/needs-action.tsx` (~278-281)

- [ ] **Step 1: HeatGrid** — table `w-full`; the row-label column sized to its content (`w-px whitespace-nowrap`), value columns share the rest equally; HeatCell `w-full` inside its cell (keep `h-10 min-w-10`). Keep `max-h-[32rem] overflow-auto`, `border-separate border-spacing-1`, sticky headers, roving keys. Check Review Focus 1-2 by reading the three callers (`risk-matrix-view.tsx`, `mitre/mitre-heatmap-view.tsx`, `exec/sector-heatmap.tsx`) for wrapper widths that would undo `w-full` (e.g. `w-fit`, `inline-block`) and fix those wrappers only.
- [ ] **Step 2: Needs-action map** — grid `lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]` (replacing `minmax(0,752fr)_500px`); map box `relative w-full overflow-hidden rounded-md aspect-[25/19] max-h-[480px]` (drop `h-[380px] w-[500px] max-w-full`); placeholder/skeleton heights adjusted to match. Confirm `WorldDots` (`src/components/world-dots.tsx`, ResizeObserver) reads the new box.
- [ ] **Step 3: Lint + typecheck.** Commit `fix(web): let heatmaps and the signal map fill their cards`.

### Task 2: Focus cards and row charts fill their row

**Files:**
- Modify: `src/components/dashboard/lead-story.tsx`, `src/components/newsroom/front-page.tsx` (Top story `Lead`), `src/components/exec/threat-actors-card.tsx`
- Modify: `src/components/dashboard/stat-box.tsx` (`ChartCard` ~97-117) and callers only if a prop must change (`dashboard/month-charts.tsx`, `dashboard/more-section.tsx`, Exec chart cards)

- [ ] **Step 1: Focus cards** — remove the `self-start` added by the audit fix; card `h-full flex flex-col`; the last block (Lead story "Why it ranks first", Top story ranking line, Threat actors "Show all") gets `mt-auto`. Summary: raise the clamp so a taller card shows more (e.g. `line-clamp-6 lg:line-clamp-[10]`), never cap card height (Review Focus 3). Threat actors keeps 5 collapsed rows.
- [ ] **Step 2: ChartCard** — card `h-full flex flex-col`; chart body `relative flex-1 min-h-0` with `style={{ minHeight: height }}` instead of fixed `height`, so the chart grows with the row but never shrinks below today; check Review Focus 4 (canvas parent must have a definite size: flex-1 + min-height inside a stretched grid item is fine; avoid `height:auto` on the canvas parent). Apply the same to any Exec chart card that wraps charts with a fixed-height div (grep `style={{ height` / `height={` in `components/exec`).
- [ ] **Step 3: Lint + typecheck.** Commit `fix(web): stretch focus cards and row charts to their row`.

### Task 3: Verify (controller)

- [ ] `pnpm build`; local browser (qafig) at ≥1920, 1440, 1024, light + dark: Sector heatmap / Risk matrix / MITRE fill their cards and keep inner scroll at 1024; no empty band under Lead story; Threat actors/Top story footers at the bottom; map scales and is capped at 1024; month charts and Exec charts not squashed and not growing in a loop; no page scroll at 1024.
- [ ] CHANGELOG `[0.8.16]` audit bullet: one line on fluid cards. Merge into origin/Dev.
