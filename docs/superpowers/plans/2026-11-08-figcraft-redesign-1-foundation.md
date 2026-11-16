# FigCraft redesign 1: foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sidebar with the mockup's masthead shell and restyle/add the shared UI primitives so every page shows the new look without layout changes.

**Architecture:** Shared components in `apps/web/src/components/ui/` are restyled in place (props kept); five small primitives are added there; the shell moves to `apps/web/src/components/app-shell/` and replaces `app-header.tsx` in `app/(app)/layout.tsx`. No API change.

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind v4, shadcn on **Base UI** (not Radix: `render={<X/>}` instead of `asChild`), `class-variance-authority`, `lucide-react`, `sonner`.

**Spec:** `docs/superpowers/specs/2026-11-08-figcraft-redesign-1-foundation-design.md` (values below are copied from it; the spec wins on conflict).

## Global Constraints

- Read `apps/web/AGENTS.md` and `apps/web/CLAUDE.md` before writing code (Next 16 breaking changes; Base UI rules: `SelectItem` children a single string, etc.).
- No `backdrop-blur`/`backdrop-filter` anywhere (commit `8f0655e`); `.prose` keeps theme tokens, never `prose-invert`.
- Colours only via tokens in `apps/web/src/app/globals.css` (`--foreground` ink `#2B0D19`, `--primary` `#D0002F`, `--border` `#E3D6C6`, `--input` `#8F7565`, `--surface`, `--panel`, `--muted-foreground`); every new token gets a `.dark` value.
- Focus (`:focus-visible`): 2 px ink ring with a 2 px gap — `ring-2 ring-ring ring-offset-2 ring-offset-background`.
- Breakpoint rule: 2-3 column layouts collapse below 1024 px (`lg:`). Minimum text 11 px.
- Comments match surrounding language (mostly Indonesian); commit messages English conventional ending with a blank line + `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No web test runner exists; do not add one. Verification per task = `pnpm lint`, `pnpm exec next typegen && pnpm exec tsc --noEmit`, `pnpm build` (from `apps/web`; node via `export PATH="$HOME/.local/share/fnm/aliases/default/bin:$PATH"`).
- Do not push, do not merge, do not switch branches (`claude/figcraft-design-data`). Stage only your own files.

## Review Focus

1. Keyboard user on the masthead: Tab reaches every nav item, More opens with Enter/Space and arrows, Escape closes it and returns focus to the trigger (Task 6 manual check list).
2. Active route inside More (`/scrapers`, `/data-health`, `/admin/*`) → the More trigger shows the red underline and `aria-current` lives on the menu item (Task 6).
3. Long client names in the utility bar and switcher → truncated with ellipsis, no wrap that pushes the masthead (Task 6).
4. Disabled `outline` button inside a dialog in dark mode → still readable (≥4.5:1 label), no `--input` fill (Task 1, Task 2 dark screenshots).
5. `Input` with `aria-invalid` and a visible error message → red border, message linked via `aria-describedby` by callers; the primitive must not hide the border on focus (Task 2).

---

### Task 1: Button + `--primary-hover` token

**Files:** Modify `apps/web/src/components/ui/button.tsx`, `apps/web/src/app/globals.css`.

**Interfaces:** Produces `Button` with the same `variant`/`size` props plus `loading?: boolean`; `buttonVariants` export unchanged in name.

- [ ] Add `--primary-hover: #b00025` in `:root` and a dark value one step lighter than dark `--primary` (`#ff6b85`); expose as Tailwind colour `primary-hover` the same way other tokens are exposed in `globals.css` (`@theme inline`).
- [ ] Restyle `buttonVariants` per spec §3: base radius 10 (`rounded-[10px]`), `text-sm` → 14 px Semi Bold, gap 8, default size `h-9 px-3.5` (keep `max-sm:h-11` touch size), focus = global focus constraint (replace `ring-3 ring-focus`). Variants: `default` = `bg-primary text-primary-foreground hover:bg-primary-hover`; `outline` and `secondary` = `border-foreground bg-background text-foreground hover:bg-surface`; `destructive` = `border-primary bg-background text-primary hover:bg-primary/10`; `ghost` = transparent, `hover:bg-surface`; `link` unchanged. Disabled: `disabled:bg-panel disabled:text-muted-foreground disabled:border-border disabled:opacity-100`. Remove every `bg-input`/`dark:bg-input` class. Keep `xs/sm/lg/icon*` sizes but switch `rounded-full` to `rounded-[10px]` (icon sizes too).
- [ ] Add `loading` prop to `Button`: renders `<Loader2Icon className="size-3.5 animate-spin" aria-hidden />` before children, sets `disabled` and `aria-busy="true"`.
- [ ] Verify: lint + tsc + build pass.
- [ ] Commit `feat(web): mockup button variants with loading state and primary-hover token`.

### Task 2: Fields — Input, Textarea, Select trigger, Checkbox; `--input` is border-only

**Files:** Modify `components/ui/input.tsx`, `components/ui/textarea.tsx`, `components/ui/select.tsx` (`SelectTrigger` only), `components/ui/checkbox.tsx`, `components/cve/cve-ticket-tab.tsx`, `components/intelligence/rfi/rfi-form-dialog.tsx`, `components/intelligence/source-reliability/sr-entry-dialog.tsx` (all under `apps/web/src`).

**Interfaces:** Props unchanged.

- [ ] Input + SelectTrigger (default size): `h-10 rounded-[10px] border border-input bg-background px-3 text-[15px]`; `sm` select size `h-8 text-[13px]`. Focus: global focus ring, border stays visible. `aria-invalid:border-primary` (no ring change). Disabled/read-only: `bg-panel text-muted-foreground`. Placeholder `text-muted-foreground`.
- [ ] Textarea: same border/radius/fill/focus as Input, `px-3 py-2 text-[15px]`.
- [ ] Checkbox: 16 px, `rounded-[4px] border border-input bg-background`, checked `bg-foreground border-foreground text-background`.
- [ ] Replace every `bg-input/NN` / `dark:bg-input/NN` fill in the three feature files (and any left in `ui/`) with `bg-surface` (or `bg-panel` where it marked a disabled/read-only state). After this, `grep -rn "bg-input" apps/web/src` returns nothing.
- [ ] Verify: lint + tsc + build; grep above empty.
- [ ] Commit `feat(web): bordered fields; --input is a border colour only`.

### Task 3: TabPills, Card, Table, Dialog restyle

**Files:** Modify `components/ui/tab-pills.tsx` (`tabPillClass`, container), `components/ui/card.tsx`, `components/ui/table.tsx`, `components/ui/dialog.tsx`.

**Interfaces:** `tabPillClass(active, tone)` signature unchanged (also used by `IntelligenceNav`). `Card` gains optional `variant?: "default" | "tile"`. `TableRow` gains optional `selected?: boolean` (sets `data-selected`).

- [ ] `tabPillClass`: `h-[31px] px-3 py-[7px] rounded-full text-[13px] border`; inactive `border-border bg-background text-foreground hover:bg-surface`; active `border-foreground bg-foreground text-background`; destructive tone active keeps its tint. `count` badge kept. Container gap 6 px.
- [ ] Card: `rounded-xl` (12 px) `border border-border bg-background p-5`; `tile` = `bg-surface border-transparent`. Keep sub-components; adjust header/title type to 18 px Semi Bold title, 13 px muted description.
- [ ] Table: rows `border-b border-border`, `hover:bg-surface`, `data-[selected=true]:bg-surface data-[selected=true]:shadow-[inset_3px_0_0_var(--foreground)]`; `TableHead` 11 px Semi Bold uppercase tracking-wide `text-muted-foreground`.
- [ ] Dialog: content radius 12, `border border-border`, overlay `bg-foreground/40` with no blur; footer puts the primary action on the right (`flex-row-reverse` order or `justify-end` — keep existing children order working).
- [ ] Verify: lint + tsc + build.
- [ ] Commit `feat(web): mockup pill tabs, cards, table rows and dialog`.

### Task 4: New primitives

**Files:** Create in `apps/web/src/components/ui/`: `underline-tabs.tsx`, `segmented-control.tsx`, `side-nav.tsx`, `chip.tsx`, `state-panel.tsx`.

**Interfaces (Produces):**
- `UnderlineTabs<T extends string>({ items: readonly { value: T; label: string }[]; value: T; onChange: (v: T) => void; "aria-label": string; className?: string })` — same ARIA/keyboard model as `TabPills` (roving tabindex, arrows/Home/End, selection follows focus).
- `SegmentedControl<T extends string>({ options: readonly { value: T; label: string }[]; value: T; onChange: (v: T) => void; "aria-label": string; size?: "sm" | "default"; className?: string })` — `role="radiogroup"`, items `role="radio"` + `aria-checked`, arrows move and select.
- `SideNav({ items: readonly { href: string; label: string }[]; "aria-label": string; className?: string })` — `<nav>` of Next `Link`s; active = `usePathname().startsWith(href)` → `aria-current="page"`.
- `Chip({ kind, value, children?, className? })` where `kind: "severity" | "status" | "grade" | "flag" | "risk"`; severity values `critical|high|medium|low`; status `ok|watch|action|open|in_progress|completed`; risk takes a numeric score and renders `LOW|MED|HIGH` via `RISK_MED_MIN`/`RISK_HIGH_MIN` from `@/lib/exec/format`; grade/flag render `children` on a neutral tint. Text = the state word (uppercase), 11 px Semi Bold, `rounded-md px-2 py-0.5`, tint+text token pairs already in `globals.css` (`bg-*-/15 text-*-text`).
- `StatePanel({ variant: "empty" | "loading" | "error" | "no-access"; title: string; description?: string; action?: ReactNode; className?: string })` — centred block in a dashed `border-border` rounded-xl area; `loading` shows a spinner and `role="status"`; `error` uses `role="alert"`.

- [ ] Implement the five files per the interfaces and spec §4 values (UnderlineTabs 15 px Semi Bold, active ink + 2 px red underline; Segmented track `bg-surface rounded-[10px] p-0.5`, items 13 px, active `bg-foreground text-background rounded-lg`; SideNav 14 px, active `bg-surface rounded-lg font-semibold`).
- [ ] Verify: lint + tsc + build (components unused yet is fine; ensure no "unused export" lint rule fails).
- [ ] Commit `feat(web): underline tabs, segmented control, side nav, chip and state panel`.

### Task 5: PageHeader kicker

**Files:** Modify `components/page-header.tsx`.

**Interfaces:** `PageHeader({ title, description?, actions?, className?, kicker?: string })`.

- [ ] Remove the red bar span. Title block `pt-6 pb-4`; kicker `text-[11px] font-bold uppercase tracking-[0.12em] text-primary`; title `text-[44px] font-bold tracking-[-0.02em] leading-tight text-foreground` (`text-3xl` below `sm`); description `text-sm text-muted-foreground`; `actions` bottom-aligned right.
- [ ] Verify: lint + tsc + build.
- [ ] Commit `feat(web): page header kicker and mockup type scale`.

### Task 6: Masthead shell replaces the sidebar

**Files:**
- Create `apps/web/src/components/app-shell/nav-items.ts`, `utility-bar.tsx`, `masthead.tsx`, `avatar-menu.tsx`, `mobile-nav.tsx`, `app-shell.tsx`.
- Modify `apps/web/src/app/(app)/layout.tsx` (use `AppShell`, new `ShellSkeleton`), `components/client-switcher.tsx` (trigger label "Client: {name}", ghost look, `max-w-48 truncate`), `components/changelog-dialog.tsx` (accept controlled `open`/`onOpenChange` so the avatar menu can open it; keep current trigger usage working or remove it if unused after this task).
- Delete `apps/web/src/components/app-header.tsx`, `components/user-menu.tsx`, `components/theme-toggle.tsx` once nothing imports them (`grep -rn` first); move any still-needed logic into `avatar-menu.tsx`.

**Interfaces:**
- `NAV_PRIMARY: readonly NavItem[]` = Dashboard `/dashboard`, Newsroom `/newsroom`, CVE Tracker `/cve`, Intelligence `/intelligence`, Exec `/exec`, X Intel `/xintel`, Recap `/recap`, Newsletter `/newsletter`; `NAV_MORE` = Scrapers `/scrapers`, Data health `/data-health`, Admin `/admin/users` (active match prefix `/admin`). `type NavItem = { href: string; label: string; match?: string }`; `isActive(pathname, item)`.
- `AppShell({ children })` renders `UtilityBar`, `Masthead`, then `<main>` in `mx-auto w-full max-w-[1328px] px-4 lg:px-8 min-[1440px]:px-0`.

- [ ] UtilityBar (spec §1): `h-[54px]`, left "{PLATFORM_NAME} · {client name}" 12 px muted (truncate), right `ClientSwitcher` + `AvatarMenu`; `border-b-2 border-foreground`.
- [ ] Masthead: wordmark "Vareon" `text-[46px] font-bold tracking-[-0.026em]` + `size-2.5 rounded-full bg-primary` dot, `Link` to `/dashboard`; nav from `lg:` up, gap 24, labels 13 px Semi Bold, active underline `h-0.5 w-6 bg-primary` under the label + `aria-current="page"`; More = `DropdownMenu` with `NAV_MORE` items (active item `aria-current`, trigger underlined when any is active). Below `lg`: `MobileNav` button "Menu" opening `Sheet` with all items. `border-b border-foreground`, `pt-[18px] pb-3.5`.
- [ ] AvatarMenu: initials avatar button; items: user name (label), Change password (opens existing `ChangePasswordDialog`), Theme: light/dark toggle (same `next-themes` logic as `theme-toggle.tsx`), Changelog (opens `ChangelogDialog`), Log out (`useAuth().logout`).
- [ ] Layout: replace `AppSidebar`/`AppTopbar` with `AppShell`; rewrite `ShellSkeleton` to two bars + content placeholders; remove sidebar localStorage code (`cti.sidebar.collapsed`).
- [ ] Manual keyboard check (record in report): Tab order utility → nav → More (Enter opens, arrows, Escape returns focus) → avatar menu; `/scrapers` underlines More; long client name truncates.
- [ ] Verify: lint + tsc + build; `grep -rn "app-header\|AppSidebar\|SIDEBAR_KEY" apps/web/src` empty.
- [ ] Commit `feat(web): masthead shell with utility bar replaces the sidebar`.

### Task 7: Local visual check, token pass, CHANGELOG

**Files:** Modify `CHANGELOG.md` (0.8.15 entry, Indonesian, `### Diubah`), `docs/prod-upgrade/0.8.15.md` + `docs/PROD_UPGRADE_0.8.11_TO_0.8.15.md` "After deploy" (shell check). Scratch only (not committed): local compose project + synthetic data script in the session scratchpad.

- [ ] Start Postgres + Redis in an isolated compose project (`docker compose -p qafig up -d postgres redis` with non-default host ports; never touch `deploy-postgres-1`), run `alembic upgrade head`, API via uvicorn, web via `pnpm dev`; create an admin user and a little synthetic data (articles, one PIR, a few CVEs) with a scratch script.
- [ ] Screenshots at 1440 and 1000 px, light and dark: Dashboard, Intelligence › Early Warning, CVE Tracker, one form dialog (e.g. RFI), a table page, Admin. Compare with FigCraft frames 45286/46600 (Design System) and 15766/18951 (Early Warning): shell, page header, pills, buttons (all states), fields, chips. Fix token regressions found (dark disabled buttons, `--warning`, risk tiers).
- [ ] Add CHANGELOG bullet: shell masthead (nav atas + More, tanpa sidebar), tombol/field/tab/kartu/tabel/dialog mengikuti mockup, komponen baru; runbook "After deploy" gets a shell/theme check line.
- [ ] Verify: lint + tsc + build; `uv run python -c "from cti_api.routers.changelog import _parse; print(_parse()[0]['version'])"` prints `0.8.15`.
- [ ] Commit `docs(release): note the masthead shell and restyled primitives in 0.8.15`; tear down the compose project.
