# FigCraft redesign: UI audit fixes (0.8.16)

Status: approved 2026-11-15. Ships inside PR #91 (release 0.8.16, no version bump).

## Intent

A UI audit of dev (`312ac8bd`, light everywhere, dark on Dashboard/CVE/Exec/Analyst board, 1024 px) found
two things the user feels directly: on a ~2000 px screen the app sits in a narrow 1328 px column with wide
empty margins, and the UI reads "not colorful enough" because every KPI card is the same beige tile with
the same top line and chart colors carry no consistent meaning. It also found a set of smaller polish
defects. The user agreed to fix all of it on this branch before the PR merges.

Success: on a wide screen the content uses the width; a glance at a KPI row or chart tells you what kind of
thing it counts by its color, and the same category has the same color on every page, in light and dark;
the per-page defects below are gone.

## Goals

1. Full-width shell.
2. One chart style everywhere.
3. Color accents by KPI kind plus one consistent categorical chart palette (user picked option A).
4. Card fill and radius consistency.
5. Mono font follows the design.
6. Per-page fixes (list below).

## Non-goals

- Data/content quality (the audit ignored data on purpose).
- Pages the audit did not check: Login, Admin beyond Users, dialogs other than Executive brief, dark mode
  of unchecked pages. They only get what shared changes give them; no page-specific work. They are still
  spot-checked in light and dark after the shared token/shell changes, and anything those changes break
  is fixed (builder call).
- Mobile below 1024 px (still out of scope per `apps/web/CLAUDE.md`).
- Backend or API changes. No migration, no `.env` key, no OpenAPI change.

## Anti-goals (a failure even if it "works")

- Rainbow UI: color without meaning, or more than one accent per KPI tile.
- Text that fails AA (4.5:1) in either theme; tinted text must use the `*-text` tokens.
- Breaking what the audit called good: consistent dark mode, readable brief dialog, 1024 px with no
  horizontal page scroll, the "Needs action" hero and the "Selected cell" panel as focal points.
- `backdrop-blur`, `prose-invert`, hex/raw palette classes in components (house rules).

## Constraints

- Next.js 16 + Base UI + Tailwind v4 tokens in `src/app/globals.css`; Chart.js via `react-chartjs-2`,
  colors through `src/lib/chart-theme.ts` (canvas cannot read `var(--x)`).
- Verify in light and dark at a wide width (≥1920), 1440 and 1024 px.
- CI = lint + typecheck + build; no web test runner. Pure helpers (enum labels, category colors) get unit
  coverage only if a runner exists; otherwise they are verified in the browser.

## Approaches considered

Color (user decision): **A, accent per KPI kind + fixed categorical palette** (picked) vs B, color only
for meaning (severity/status, burgundy ramps for charts). B barely answers "not colorful enough".

Chart unification: **restyle the shared components in `components/dashboard/charts.tsx` (and
`entity-timeline-chart.tsx`) to the new style** (picked: one file carries most old-style charts, callers
unchanged) vs migrating every caller to `BarSeries` (more churn; `BarSeries` has no multi-line/stacked
modes).

Width: **full width with a 1920 px cap** (picked; the audit tested a CSS override at 1794 px and the
Dashboard grid stayed tidy) vs a larger fixed cap like 1600 px (still wastes space on 2000+ screens).

## Design

### 1. Width

`SHELL_COLUMN` in `src/components/app-shell/app-shell.tsx` becomes full width with a 40 px gutter from
1024 px up (`lg:`) and a 1920 px cap (content plus gutters, so content tops out at 1840 px), centered
beyond that. Small-screen gutters unchanged. Header and main both use it, so they stay aligned (builder
call). Text-heavy surfaces keep whatever inner max-width they already have; none is added (builder call). Then check each wide table/heatmap the audit listed at ≥1920, 1440 and 1024: Risk matrix (25
countries), MITRE heatmap, Exec Sector risk (Top TA column), Source reliability (Analyst column),
Ticketing (PL… column), IOC table (SE… column), Scrapers (Disable button at the edge). At wide widths
they should show whole columns; at 1024 they keep today's behavior (inner scroll where they had it,
no page scroll).

### 2. One chart style

"New style" = what `month-charts.tsx` / `BarSeries` already do. Apply it to every component in
`components/dashboard/charts.tsx` (`MultiLineChart`, `StackedBarChart`, `TimelineChart`,
`HorizontalBarChart`, `TAActivityTimelineChart`, `GradedDoughnutChart`, `SeverityStackedChart`) and to
`entities/entity-timeline-chart.tsx`:
- straight segments (no smoothing), points only on hover;
- legend swatches as line/dot (point style), not boxes;
- date ticks short ("8 Nov"), never rotated, auto-skipped;
- grid, ticks and tooltip from the chart theme tokens; series colors from §3, never Chart.js defaults.
Callers seen by the audit: Dashboard "More" (All news / Incidents, Tracked APT groups), Exec Analyst
board (News types, Sector trend, Victim country trend), entity "Mentions by month".

### 3. Color

**KPI kinds.** Each KPI tile carries exactly one accent, chosen by what it counts:

| Kind | Counts | Accent (top line + number) |
|---|---|---|
| threat | articles, incidents, victims, actors, techniques | red (destructive) |
| vuln | CVEs, KEV, tickets, exposure | amber (warning) |
| intel | IOCs, entities, PIRs/RFIs, sources, campaigns | teal (new token) |
| ops | scrapers, queues, data health, freshness | blue (info) |

Severity/status tiles that already carry meaning (CVE Critical/High/Medium, Scrapers health) keep it.
`StatTile` already has a `tone` prop and `StatBox`/Exec KPI row have their own; add the kinds there (the
teal token pair `--intel` / `--intel-text` in both themes, AA for text) and set the kind at each caller.
The beige tile surface stays.

**Single-series bars** take the color of the kind they count (incidents, techniques, APT groups =
threat red), so Dashboard, Exec Top techniques and Tracked APT groups agree.

**Categorical palette.** Multi-series charts (sectors, news types, countries, groups) color by category
*name*, not series index: a fixed name→color map for the known sectors and news types, a stable hash into
the palette for the rest, so a category has the same color on every page. Take the known names from the
lists the code already uses (sector/industry and news-type options), not from dev data (builder call). Rebalance the 10 `--chart-*`
values so every pair is distinguishable in both themes (today dark `--chart-3` orange vs `--chart-4` peach,
e.g. Financial Services vs Government, are nearly identical); check with a hand-run color-distance script (no web test runner; builder call). KPI kinds and the
categorical palette are separate systems: the palette may keep red/amber/teal/blue-family hues
(builder call).

### 4. Cards

- Focus cards that sit half empty because they stretch to the neighbour column's height (Dashboard "Lead
  story", Newsroom "Top story", Exec "Threat actors"): no large empty interior. Prefer showing more of
  their existing content (longer summary, more rows) when the data has it; otherwise the card sizes to its
content and the row aligns to the top, an uneven row being acceptable (builder call).
- Radius: Lead/Top story use the same radius as neighbouring cards (`rounded-lg`).

### 5. Mono font

The design uses Google Sans Flex everywhere, including data values. User decision: follow it for short
identifiers and numbers, but keep IBM Plex Mono for long machine strings that are read or copied
character by character (Flex is proportional and `l`/`1`, `O`/`0` look alike).
- `font-code` (IBM Plex Mono) stays, but only for machine strings: hashes, IOC values, IP addresses,
  URLs/domains shown as indicators, hunting-pack queries, cron schedules.
- Callers that use `font-code` for short identifiers and numbers (CVE IDs, ATT&CK technique codes,
  counts, scores, dates) drop it and use the body font (Google Sans Flex) with `tabular-nums`. The builder
  picks them by grepping `font-code`. No new token: `font-mono` already means Google Sans Flex here and is
  used widely, so it is not repurposed (builder call).
- Update the "Fonts" rule in `apps/web/CLAUDE.md` to say this.

### 6. Per-page fixes

- **Newsroom All articles:** at ≥1024 px with no `article` in the URL, select the first article of the
  current list (after filters and sort; URL replace through the guarded writer, no history entry) instead
  of showing "Select an article". It fires only when `article` is absent; a filter change keeps today's
  behaviour for an already-selected article (builder call). Below 1024 nothing auto-opens.
- **Newsroom Active topics:** sparklines without axis labels.
- **CVE:** the Ticketing segmented control sits in the toolbar row, not a third stacked navigation row;
  search placeholder fits without truncation; date filters use the house `DateField` instead of native
  dd/mm/yyyy inputs; the Package Vulnerabilities (Import lockfile / Scan all / + Add package) and Monitored
  Tech (Add custom / + Add from catalog) actions sit on the header/filter row, right-aligned, not
  floating on their own row.
- **Exec:** Save watchlist / Export CSV / Generate brief on the filter row, right-aligned; "updated just
  now" never wraps.
- **Entities:** sector rows show "—" in ATT&CK ID instead of the slug; 30D and 90D values visibly
  separated; aliases not truncated to "Cloud …" (wrap, or full text on hover/focus).
- **IOC:** the 8 KPI tiles lay out as full rows (4×2, or 8 in one row when wide), no orphan; type labels
  humanized ("URL with path", not `URL_WITH_PATH`).
- **Source reliability:** origin chips humanized ("Vendor research", not `VENDOR_RESEARCH`). One shared
  enum-label helper serves IOC and SR.
- **Risk matrix and Analyst board Sector heatmap:** empty cells drawn plain (no outlined box).

## Left to the builder

Exact gutter class, exact hex values for the rebalanced palette and teal token (within the AA and
distinguishability rules), the name→color map contents, the kind assignment of each individual tile
(by the table), how each focus card fills, and the IOC grid breakpoints.

## Delivery

Spec → plan → subagent-driven implementation with per-task review → local QA (qafig, light + dark,
≥1920 / 1440 / 1024) → merge into origin/Dev (pre-approved) → recheck on dev in Chrome → `CHANGELOG.md`
`[0.8.16]` entry extended (Indonesian), runbook only if deploy steps change (they should not). Pushing to
the PR #91 branch needs the user's OK.
