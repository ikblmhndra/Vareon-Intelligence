# FigCraft redesign, sub-project 1: foundation (shell + shared primitives)

Date: 2026-11-08. Status: draft for review. Branch: `claude/figcraft-design-data` (same one-PR release 0.8.15;
the CHANGELOG entry is extended, no extra version bump).

## Context and decomposition

The FigCraft mockup (`~/Documents/Vareon Design.figcraft`) redesigns every web page. The app today has a left sidebar;
the mockup uses an editorial masthead with a top nav. The work is split into five sub-projects, each with its own
spec → plan → implementation → visual check, all on this branch and in the one PR (user-approved order):

1. **Foundation** (this spec): app shell and shared primitives.
2. CVE Tracker + Intelligence pages.
3. Exec (Briefing / Analyst board).
4. X Intel, Recap, Newsletter, Scrapers, Data Health, Admin, Login (with 401 / 429 / force_pw_change states).
5. Dashboard + Newsroom.

Desktop 1440 px first; layouts collapse to one column below 1024 px (`lg:`); full mobile layouts stay out of scope.

## Goal

After this sub-project every page already shows the new shell and the new look of shared controls (buttons, fields,
tabs, chips, cards, tables, dialogs, states), without changing page layouts or data flow. Sub-projects 2-5 then only
rearrange page content.

Approach (approved): restyle the existing shared components in place and keep their props, so the ~178 `outline`
buttons, 13 `PageHeader` pages and 9 `TabPills` uses change at once; add the few primitives the mockup has and the
app lacks. No parallel component set.

## 1. App shell (replaces the sidebar)

Source frames: any page frame, e.g. "Intelligence / Early Warning" (node 15766). Page width 1440, side padding 56,
content width 1328 (`max-w-[1328px]`, centred; `px-4` below `lg`, `px-14` from 1440).

- **Utility bar** (height 54, padding 14 vertical): left text "Vareon Intelligence · {client name}" 12 px regular
  `muted-foreground`; right the existing client switcher (label "Client: {name} ▾") and an avatar button (initials).
  Below it a 2 px rule in `foreground` (ink).
- **Masthead** (height 90, padding 18 top / 14 bottom): left the wordmark "Vareon" 46 px Bold, tracking −1.2, ink,
  followed by a 10 px red dot (`primary`, fully rounded) aligned to the baseline; it links to `/dashboard`. Right the nav,
  bottom-aligned, gap 24: Dashboard, Newsroom, CVE Tracker, Intelligence, Exec, X Intel, Recap, Newsletter, then
  **More ▾** (dropdown: Scrapers, Data health, Admin). Labels 13 px Semi Bold ink. Active item: 2 px × 24 px red
  underline under the label, `aria-current="page"`; when the active route is inside More, the More trigger shows the
  underline. **No count badges** (user decision). All items are shown to every user, as in today's sidebar (pages gate access themselves). Below the masthead
  a 1 px ink rule.
- **Avatar menu** (dropdown): user name, Change password, Theme (light/dark), Changelog, Log out — the actions that
  live in the sidebar/topbar today move here.
- **Below 1024 px**: the nav is replaced by a "Menu" button that opens the existing `Sheet` with the same items.
- The sidebar, its collapse state and `ShellSkeleton`'s sidebar shape are removed; the skeleton mirrors the new shell.

## 2. Page header

`PageHeader` gains an optional `kicker` prop and the mockup type scale (Title block padding 24 top / 16 bottom):
kicker 11 px Bold, tracking 1.3, uppercase, `primary`; title 44 px Bold, tracking −1, ink (one `<h1>`); description
14 px regular `muted-foreground`; `actions` slot right-aligned at the bottom. The red bar accent is removed. Pages pass
their section as kicker in their own sub-project; until then the header renders without one.

## 3. Primitives restyled in place (props unchanged)

- **Button** (`ui/button.tsx`): height 36, padding 9/14, radius 10, label 14 px Semi Bold, gap 8.
  `default` = primary: `primary` fill, white text, hover `#B00025` (new token `--primary-hover`, dark mode derived).
  `outline` = secondary: 1 px ink border, ink text, hover `surface` fill. `destructive`: 1 px `primary` border,
  `primary` text, hover tint. `ghost`: no border, hover `surface`. `secondary` maps to the secondary look; `link`
  unchanged. Disabled: `panel` fill, `muted-foreground` text, no border colour change for outline variants. New
  optional `loading` prop shows a 14 px spinner before the label and sets `aria-busy`, disabled. Keyboard focus
  (`:focus-visible`): 2 px ink ring with a 2 px gap (`ring-2 ring-ring ring-offset-2`), already ink via `--ring`.
- **Input / Textarea / Select trigger**: height 40 (input/select), padding 0/12, radius 10, 15 px text, white
  (`background`) fill, **1 px `--input` border** (visible; today Input and Select are borderless on `bg-muted`).
  Focus: 2 px ink ring with gap. Error (`aria-invalid`): `primary` border, message under the field in `primary`.
  Disabled/read-only: `panel` fill, `muted-foreground` text. Labels above fields 13 px Semi Bold.
  Every use of `--input` as a fill (`bg-input/30`, `/50`, `/80`, `dark:bg-input/…`) is replaced by `surface`/`panel`
  tokens, so `--input` is a border colour only.
- **Checkbox**: 16 px, 1 px `--input` border, checked = ink fill with white check.
- **TabPills** (pill tabs = sub-pages / page tabs): height 31, padding 7/12, fully rounded, 13 px; inactive = white fill
  with 1 px `border`; active = ink fill, white text. Container gap 6, followed by a 1 px `border` rule (as in the frame).
- **Card / panel**: radius 12, 1 px `border`, padding 20, white; "tile" variant = `surface` fill, no border.
- **Table rows**: rows separated by a 1 px `border` line; hover = `surface` tint; selected = `surface` fill plus a 3 px
  ink bar on the left edge. Header 11 px Semi Bold uppercase `muted-foreground`; numbers right-aligned.
- **Dialog**: title states the action; one primary button on the right; destructive actions name what they destroy;
  no backdrop blur (constraint from commit `8f0655e`).

## 4. New primitives

- **UnderlineTabs** (level-1 views of one page, e.g. CVE Tracker / Package): 15 px Semi Bold labels, inactive
  `muted-foreground`, active ink with a 2 px red underline; keyboard arrows move between tabs (`role="tablist"`).
- **SegmentedControl** (filters/modes inside a card or toolbar, e.g. 7d/30d/90d): `surface` track radius 10, items
  13 px; active item ink fill, white text; single-select; `role="radiogroup"`.
- **SideNav** (settings areas, Admin): vertical list, 14 px; active item `surface` fill radius 8 and Semi Bold.
- **Chip**: 11 px Semi Bold label on a tint, radius 6, padding 2/8. Variants: severity (critical/high/medium/low),
  status (ok/watch/action/open/in progress/completed), grade (A1…), flag (KEV, EXPLOITED, PoC, public/internal),
  risk tier (LOW 0-39 / MED 40-69 / HIGH 70-100, via `riskTier` cut points from `lib/exec/format.ts`). The word always
  states the state (colour is never the only signal). Existing `Badge` uses are migrated in the page sub-projects.
- **StatePanel**: empty / loading / error / no-access variants with title, one-line explanation and optional action;
  errors say what failed and what to do next.

## 5. Tokens and the pending light/dark check

- Add `--primary-hover` (light `#B00025`; dark a lighter step of `--primary`).
- Verify every token change from earlier in this release in light and dark: `--input` borders on the restyled fields,
  ink focus ring, `--warning #a04a07`, risk-matrix tiers, and the fills that used `--input`.
- No `backdrop-blur`; `.prose` keeps theme tokens.

## Out of scope

Page layouts and content (sub-projects 2-5), count badges, mobile layouts, new API endpoints.

## Verification

- `pnpm lint`, `pnpm exec next typegen && pnpm exec tsc --noEmit`, `pnpm build`.
- Local stack: Postgres + Redis in an isolated compose project (not the user's `deploy-postgres-1`), API via uvicorn,
  web via `pnpm dev`, a small synthetic data script kept in the session scratchpad (not committed).
- Screenshots at 1440 and 1000 px, light and dark, compared with the Design System frame (45286 / 46600) and the
  Early Warning frame (15766 / 18951): shell, page header, pill tabs, a form dialog, a table, buttons in all states.
- Keyboard: tab through the nav, More menu, avatar menu, tabs and a dialog; focus ring visible everywhere.
- End of sub-project: merge into `origin/Dev` (standing approval) and check on dev 172.25.1.77 with real data.
