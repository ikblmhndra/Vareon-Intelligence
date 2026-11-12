# FigCraft redesign, sub-project 4a: Content (X Intel, Recap, Newsletter)

Date: 2026-11-12. Status: draft for review. Branch: `claude/figcraft-design-data`. Same one-PR release 0.8.16
(the CHANGELOG entry and the 0.8.16 runbooks are extended, no extra version bump).

## 1. Context and goal

Sub-projects 1 (foundation), 2a (CVE Tracker), 2b (Intelligence) and 3 (Exec) delivered the shell and the shared
primitives in `apps/web/src/components/ui/` (`HeroPanel`, `StatTile` with `spark`, `SegmentedControl`, `UnderlineTabs`,
`SelectableList`, `Sheet`, `Switch`, `DateField`, `NumberedPager`, `Chip`, `StatePanel`, `Notice`, `ConfirmDialog`
with note and tone), the browser-timezone formatters in `apps/web/src/lib/format.ts`, `lib/exec/query.ts::isClientError`,
`lib/cve/catalog.ts::useDebounced` and `lib/newsroom/links.ts::newsroomHref`. This spec is **4a: the three content
pages, X Intel, Recap and Newsletter**. Sub-project 4 is split into 4a (this spec), 4b (Scrapers, Data Health) and
4c (Login, Admin, session-expired dialog).

FigCraft frames (light; dark variant in brackets): X Intel / Tweets 27680 (28830), X Intel / Accounts 38457 (40021),
Recap / Weekly 27898 (29048), Newsletter / Composer 28635 (29284), Newsletter / Dialogs 35311 (36240, preview dialog
only). There is no states frame for any of the three pages, no daily-recap frame, no tweet-detail frame, no history
frame.

Today all three pages are pre-redesign: layouts render a plain `<PageHeader title description />`, X Intel filters
need an Apply click, Recap is a Week/Day button bar plus a 240 px history sidebar with long stacked sections, and the
Newsletter composer is one 600-line `NewsletterView` that stacks every section in one scrolling card. The mockup
turns them into a social-signal feed with a counters rail, a weekly briefing with tiles and a forecast scorecard, and
a three-column composer.

Goal: deliver the **full mockup, keep every existing feature reachable** (X1-X21, R1-R21, N1-N18 in the gap
inventory), add the data the mockup needs (B-X1, B-X2), and keep the Newsletter state machine
(`lib/newsletter/composer.ts`) untouched. Backend lands first, the contract is regenerated once, then the pages are
built on real data. The inventory behind this spec (`.superpowers/brainstorm/sp4-inventory.md`, not committed) lists
every frame element and its source; where they differ, this spec wins.

## 2. Decisions (binding, from the user)

Scope
- **S1** Sub-project 4 is split into 4a (this spec), 4b and 4c. The session-expired dialog (inventory D6) belongs to
  4c, not 4a.
- **S2** Full mockup; every pre-redesign feature stays reachable, re-homed where the mockup has no place.
- **S3** Release stays 0.8.16, one PR; `CHANGELOG.md` (Indonesian), `docs/prod-upgrade/0.8.16.md` and
  `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` are extended.
- **S4** All recommended defaults D1-D34 of the inventory are accepted. Those that shape 4a:

| Id | Decision |
|---|---|
| D7 | UI copy in English (no Indonesian strings on these pages). |
| D19 | Freshness thresholds stay the code's (tweets: warning above 24 h, red above 72 h); the X Intel "Feed delayed" chip uses them. |
| D23 | X Intel filters: period 24h / 7d / 30d (default 7d) plus "Custom range" (`DateField`) so From / To stay; Confirmed / APAC / CVEs are multi-select toggles; Signal options: all, OT / ICS, zero-day, data breach, report. |
| D24 | The rail's counters and victims follow the selected period; its title reads "Last 24 hours" / "This week" / "Last 30 days". |
| D25 | Daily recaps stay reachable from the History select; the Regenerate dialog gets a Week / Day switch and keeps the force warning. |
| D26 | Recap "Export PDF" = `window.print()` with a print stylesheet; no server PDF. |
| D27 | Scorecard verdict override stays inside the forecast / scorecard card; Week-over-Week becomes the tile deltas with the table in a disclosure; grounding stays a `Notice`; Top Tweets and Active Campaigns move to a "More signals" disclosure. |
| D28 | "Generate edition" = the existing Outlook draft flow (the dialog footer button stays "Create Outlook draft"); History opens as a sheet; "Send test to me" and Preview Full / Compact are deferred. |
| D29 | Period select = last 6 calendar months (WIB), client-derived, loading `GET /api/newsletter/suggestion?period_start=&period_end=`; Lookback stays inside the clusters row. |
| D30 | No drag-to-reorder (no dnd library, no reorder logic); the "drag to reorder" caption is dropped. |
| D31 | "+ Add articles" links to Newsroom (the existing "+ Newsletter" intake); no picker. |
| D32 | Browser time zone with `browserZoneName()` where a zone is shown; Recap windows stay UTC calendar dates. |
| D33 | Confidence is an integer ("confidence 91"). |
| D34 | One contract regen for 4a (B-X2). |

## 3. Conflicts between inputs, and how they are resolved

- **C1 Confidence scale.** Mockup "confidence 0.91"; `incident_confidence` / `confidence` are integers 0-100 → "confidence 91"
  (D33). The card prints `incident_confidence` for a confirmed incident, else `confidence` when not null.
- **C2 Freshness numbers.** Mockup chip "newest post 2 h ago" and "watch after 1 h"; code and D19: warning above 24 h,
  red above 72 h. The chip only appears from 24 h. The sentence "Collector retried at 14:10; nothing is lost" is sample
  text: "nothing is lost" cannot be proven from the data, so the line shows the `monitor_x` scraper `reason` (when
  `useScraperHealth()` lists it as a problem) and a link to Data health instead.
- **C3 X Intel titles and tab styles.** The Tweets frame has an underline sub-nav with counts and h1 "X Intel"; the
  Accounts frame has pill tabs and h1 "Monitored accounts". Resolved: `UnderlineTabs` (level-1 views of one page,
  `apps/web/CLAUDE.md`) in both; the page header follows the tab (h1 "X Intel" / "Monitored accounts"). The designer
  note "MonitoredAccountOut: the handles the X collector reads" is an annotation, not UI copy.
- **C4 Accounts add row.** Mockup shows it to everybody; the API needs `manage_tweets` for add, toggle and remove. The row,
  the switch and Remove are gated on `manage_tweets`, the list on `view_tweets` (the router permission), never
  stricter.
- **C5 Filter model.** Mockup: three "tabs" plus Signal select plus period; code: three checkboxes plus a date range.
  Resolved per D23: Confirmed incidents / APAC / CVEs are independent toggles combined with AND; OT moves into the
  Signal select (the `ot_only` API parameter stays for API clients).
- **C6 Tab counts.** "Tweets 1,204" is the unfiltered total, "Monitored Accounts 48" the account count; both come from
  existing endpoints (`GET /api/tweets?page_size=1` total, `GET /api/monitored-accounts` length), no counts endpoint.
- **C7 Recap is weekly only in the frame.** The code also has daily recaps (D25). Header, tiles and cards adapt by
  `kind`; a daily recap has no comparison, scorecard or hit rate and says so.
- **C8 "Week 45".** An ISO week number derived from `period_start` (UTC Monday), never stored. Dates are UTC calendar
  dates, shown as plain dates (`parseLocalDate`, no conversion); the card footer says "Weeks run Monday-Sunday by UTC
  date."
- **C9 Recap copy that depends on data.** "Each links to its source article" holds only when every story has a `url` (old
  recaps have none): otherwise "Links appear for stories matched to an article." "Each forecast is scored next week" is
  weekly only; the daily copy is "Daily forecasts are not scored." Tile deltas exist only for weekly recaps with a
  previous week (`quality.comparison`).
- **C10 Recap quality blocks without a place.** Forecast summary and Watch items (R14), overall hit-rate row and
  reviewed weeks (R18), Week-over-Week table and "New this week" (R15), Top tweets (R10), Active campaigns (R12): kept,
  see 6.2.
- **C11 Newsletter naming.** "Generate edition" creates an Outlook **draft** through Graph; nothing is ever sent by the
  platform and users have no email column. The mockup's "Send test to me" (needs a recipient, B-N1) and Preview
  "Full | Compact" (no global render mode, B-N2) are deferred (D28). The email is server-rendered at a 640 px container
  (`templates/newsletter_email.html`), not the mockup's 712 px: the dialog states no pixel width.
- **C12 Header buttons.** The mockup has both "Preview" and "Generate edition". The product rule (ROADMAP #22, PR 9) is
  that a draft is only created from the preview dialog so size and CVE-marker warnings are seen first. Resolved: both
  buttons open the same preview dialog; they differ only in emphasis and focus (6.3). This is a choice, not a mockup
  statement.
- **C13 Lookback.** Mockup "LOOKBACK 31 days" has no equivalent; it equals the period length. It is shown as a read-only
  caption under Period; the real lookback (7 / 14 / 30 days, `cluster_days`) stays inside the Campaign clusters block.
- **C14 Suggestion bar "from 642 articles".** `NewsletterSuggestionResponse` has no candidate count. The sentence becomes
  "Built {time} · ranked by severity, APAC relevance and source grade"; no backend change.
- **C15 Section column.** The frame shows one section ("Indonesia") with a Full | Compact segmented, while the code shows
  all sections stacked. Resolved: the Template column is a selector of **content blocks**; the middle column edits the
  selected block (6.3). The segmented picks which tier list is shown. This is a layout choice that keeps all logic.
- **C16 Time zone.** Newsletter periods are calendar months in WIB (the report zone, D29), which the client cannot read
  from the API: `lib/newsletter/period.ts` uses a fixed UTC+7 constant, see Risks. Times shown to the user are browser
  zone (`fmtDateTime`); `lib/cve/freshness.ts::formatWib` is no longer used by X Intel.
- **C17 Page h1.** The Recap h1 and the X Intel h1 depend on data or tab, so the pages render their own `PageHeader`; the
  layouts keep only `metadata`.

## 4. Backend

Conventions. Only the tweets endpoints change. Router `routers/tweets.py` keeps `require_permission("view_tweets")`;
`monitored_accounts.py`, `recap.py` and `newsletter.py` are untouched. Comments and docstrings in Indonesian,
matching the files. New query parameters change `docs/openapi.json` → `uv run python tools/export_openapi.py` and
`cd apps/web && pnpm run gen:api`. `GET /api/tweets/stats` stays an untyped `dict[str, object]`, so its new fields
go into `apps/web/src/lib/api/loose-types.ts::TweetStats`.

### 4.1 B-X1 `GET /api/tweets/stats`: counters and most-named victims
- **Contract.** The response gains `confirmed`, `apac`, `ot`, `with_cve`, `databreach`, `zero_day` (ints) and
  `top_victims: list[{victim, count}]` (at most 5); `total` and `top_authors` are unchanged. All figures follow the
  same filters as the feed, so the header "214 posts · 31 confirmed incidents" and the rail always describe the posts
  the list shows.
- **Logic.** `AsyncTweetRepo.get_stats`: the base subquery also selects `confirmed_incident`, `victim_name` and the
  needed `scan_results` keys; one aggregate query with `count().filter(...)` per counter; `top_victims` is
  `group by lower(btrim(victim_name))` over non-null names, label = `max(victim_name)`, ordered by count then label,
  limit 5. List-valued keys use a helper `_has_items(key)`: `CASE WHEN jsonb_typeof(scan_results->key) = 'array' THEN
  jsonb_array_length(...) ELSE 0 END > 0`, so a missing key, `[]` and JSON `null` all count as none. Booleans reuse
  the existing `.as_boolean()`.
- **Performance.** Two more queries (four instead of two), each over the already-filtered set; no index. The existing
  `ilike` filters already scan; revisit only if tweets queries show up slow on `/data-health` or the table reaches
  seven figures (a `pg_trgm` index is out of scope).
- **Tests.** `tests/integration/test_tweet_query.py::TestAsyncTweetRepo::test_get_stats_counters` (each counter,
  missing key / `[]` / `null`), `::test_get_stats_counters_follow_filters`, `::test_get_stats_top_victims` (case
  insensitive merge, order, limit 5, nulls skipped). Snapshot `tests/integration/test_tweets_router_snapshot.py::
  test_tweet_stats` updated with `--snapshot-update` after review.

### 4.2 B-X2 search and new filters
- **Contract.** `GET /api/tweets` and `GET /api/tweets/stats` gain `has_cve: bool = False` and
  `signal: Literal["ot", "zero_day", "databreach", "report"] | None = None`. `ot_only` stays. An unknown `signal` is a
  422 from FastAPI.
- **Logic.** `_apply_tweet_filters` (`packages/cti-core/src/cti_core/db/repositories/tweet.py`): `search` becomes an
  OR of `text ilike %q%`, `author_username ilike %q-without-@%`, `victim_name ilike %q%` and `cast(scan_results->
  'cve_list' as text) ilike %q%`; the separate `author` filter keeps its behaviour. `has_cve` = `_has_items("cve_list")`.
  `signal`: `zero_day` / `databreach` = `_has_items(key + "_list")`, `ot` / `report` = `.as_boolean()` on
  `ot_status` / `report_status`. The router passes both through list and stats, and `list_filtered`, `get_stats`
  and `list_top_between` signatures gain the keyword arguments with defaults (the recap caller is unchanged).
- **Performance.** Same scan as today with more predicates; no extra query.
- **Tests.** `test_tweet_query.py`: `::test_search_matches_text_handle_victim_and_cve`, `::test_search_handle_with_at`,
  `::test_list_filtered_has_cve`, `::test_list_filtered_signal_each_value`, `::test_filters_combine_with_and`.
  `test_tweets_router_snapshot.py`: `::test_list_tweets_signal_and_has_cve_params` (valid values 200, `signal=bogus`
  422). Existing `test_recap_*` and `test_tweet_alerts.py` stay green.

### 4.3 Documentation touched
- `CHANGELOG.md`, 0.8.16 entry (Indonesian). *Ditambahkan:* X Intel: pencarian juga mencocokkan handle, nama korban dan
  CVE; filter `has_cve` dan `signal`; statistik periode (insiden terkonfirmasi, APAC, CVE, data breach, zero-day, OT,
  korban paling sering disebut); halaman X Intel, Recap dan Newsletter didesain ulang (komposer tiga kolom,
  Export PDF recap lewat cetak browser). *Diubah:* tombol Apply/Reset X Intel diganti filter langsung; riwayat
  newsletter dibuka sebagai panel samping. Header line: no new migration, no new `.env` key.
- `docs/prod-upgrade/0.8.16.md` and `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md`: *Migrations:* none from 4a. *Settings:*
  none. *Contract:* two new optional query parameters on the tweets endpoints (additive). *Rollback:* image rollback
  only; no data change.

## 5. Migration summary

None. 4a adds no table, no column and no `Settings` field, so `.env.example` and `.env.prod.template` are unchanged and
the Alembic head stays whatever the Exec spec left (`c4e8a1f2b9d6`). Syrupy snapshot to update after review:
`test_tweets_router_snapshot.py::test_tweet_stats`. Contract files to regenerate and commit: `docs/openapi.json`,
`apps/web/src/lib/api/schema.d.ts`.

## 6. UI

Global rules (as 2b and 3). Desktop 1440 first (content width 1328). Two- and three-column rows collapse to one column
below 1024 px (`lg:`). No `backdrop-blur`. Colours only through tokens; text on tints uses `text-X-text`. Focus ring
`focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background`.
Minimum text 11 px (`text-2xs`). Base UI, not Radix (`render={<X/>}`, `SelectItem` children a single string, `Select
items` for sentinel values). CVE ids, counters and other data values in `font-code`. The mockup's wide separators are
visual spacing, rendered " · ". Fixed copy below is verbatim from the frames unless a C-rule says otherwise.

Constraints carried over from earlier sub-projects (each is a review checklist item):
1. A nested layout with a string `metadata.title` resets the root title template. The three layouts use
   `{ default, template: "%s · ${PLATFORM_NAME}" }` (as `app/(app)/exec/layout.tsx`) and stop rendering `PageHeader`;
   pages set `document.title` with the restore-on-unmount pattern of `components/entities/entity-view.tsx`.
2. No interactive element nested inside another: tweet cards (6.1), history rows, article cards and queue rows get a
   real `<button>` for the primary action and keep links and menus as siblings, never `role="button"` around a link.
3. Gate controls on the real backend permission, never a stricter one: Generate / Regenerate `manage_intel`; scorecard
   override `view_intel` (it only needs the router permission); accounts writes `manage_tweets`; newsletter preview,
   draft, resend, rebuild `manage_newsletter`; history list `view_newsletter` (router).
4. A `Chip` inside `HeroPanel` needs hero-safe tokens. 4a uses no `HeroPanel`; if one is added, check the chip first.
5. Heat or legend colours must match the cells. 4a has no heat grid; the hit-rate bar uses the same token as its legend.
6. A `table-fixed` table needs explicit column widths (Accounts, Recap hit-rate, Week-over-Week).
7. Do not retry 4xx in react-query: every changed or new query throws `new Error(msg, { cause: response.status })` and
   uses `retry: (n, e) => n < 2 && !isClientError(e)` from `lib/exec/query.ts`.
8. `useDebounced` needs memoised inputs: it is fed a string (search) and the period anchor is state, never an
   expression like `new Date().toISOString()` in render.
9. Check `response.ok`, not just `if (error)`: `feed-status-banner.tsx`, `newsletter-view.tsx` (`handlePreview`,
   `handleSendDraft`, `handleResend`, history query) and `newsletter-history-panel.tsx` use `if (error) throw error`,
   which lets an empty-body 502 through as success; they are fixed in passing.
10. Every pre-redesign feature stays reachable; the PR carries a checklist X1-X21, R1-R21, N1-N18 (maps in 6.1-6.3).

### 6.1 X Intel (frames 27680, 38457)
- **Routing.** `app/(app)/xintel/page.tsx` reads `?tab=tweets|accounts` (`useSearchParams`, invalid → `tweets`,
  `router.replace` on change). Header (`components/xintel/xintel-page-header.tsx`): Tweets: kicker "SOCIAL SIGNALS", h1
  "X Intel", description "Posts from monitored researchers and leak-watchers, classified for incidents, CVEs and APAC
  relevance", `actions` = the feed chip. Accounts: kicker "SOCIAL SIGNALS", h1 "Monitored accounts", description "The
  handles the X collector reads. Deactivating keeps the history; removing deletes the account from the list but keeps
  its posts." (true: `AsyncMonitoredAccountRepo.remove` deletes only the account row). Below it
  `UnderlineTabs` "Tweets {total}" | "Monitored Accounts {n}" (`aria-label` "X Intel views"; counts per C6, shown
  when loaded).
- **Feed chip** (`feed-status-chip.tsx`, replaces `feed-status-banner.tsx`, X15). Query `["xintel","feed-status"]`
  reads `GET /api/data-health` (`view_ops`; a 403 hides the chip silently, no retry) and returns `{newest, nowMs}`
  computed in `queryFn`. Age ≤ 24 h: nothing. 24-72 h: warning `Chip` "Feed delayed · newest post {fmtAgo}". Above
  72 h or no tweet at all: destructive `Chip` "Feed stalled · newest post {fmtAgo}" / "No posts collected yet". Under
  it `text-2xs` muted: the `monitor_x` reason ("X collector {status}: {reason}") and the link "Open Data health".
- **Toolbar** (`xintel-toolbar.tsx`, one row, wraps): `SearchInput` "Search text, handle, CVE or victim" (400 ms
  debounce on a string; Enter applies at once); period `SegmentedControl` "24h | 7d | 30d | Custom" (`aria-label`
  "Period", default 7d); with Custom, two `DateField optional` "From" / "To" (inclusive days in the browser zone, sent
  as `YYYY-MM-DD` + `tz` exactly as today, X4); `Select` "Signal: all | Signal: OT / ICS | Signal: Zero-day | Signal:
  Data breach | Signal: Report" (`items` prop); three toggle buttons "Confirmed incidents", "APAC", "CVEs" (`aria-pressed`,
  AND); right: "{total} posts · {confirmed} confirmed incidents" and, when any filter differs from the default, a
  "Clear filters" ghost button (replaces Apply / Reset, X8). The handle filter (X3) is the search box: backend search
  matches the handle (4.2); the rail's "Most active accounts" rows fill it with `@handle`.
- **Period anchor.** Preset periods send `posted_on_start` as an ISO instant (`now - N`). The instant is held in state
  (`anchor`, set on mount, on period change and on a "Refresh" action), so the query key is stable and the list does
  not refetch every render; the feed does not slide until the next anchor, and the open upper bound still includes
  new posts.
- **Feed** (`tweet-card.tsx`, restyled; `tweet-badges.tsx` replaced by chips). One column, 880 px of the 1328 content
  (`lg:grid-cols-[minmax(0,1fr)_432px]`). Card = `<article class="surface-raised">` with: avatar (initial of display
  name or handle; the image when `author_avatar` loads), display name, "@handle · {followers compact} followers ·
  {fmtAgo}" (`title` = `fmtDateTime`; followers omitted when 0), a destructive `Chip` "CONFIRMED INCIDENT" when
  `confirmed_incident`, "confidence {n}" (C1). Body: a real `<button type="button">` wrapping the cleaned text (4-line
  clamp) and the chip row, opening the detail dialog (6.4); only non-interactive content inside. Chip row in this order,
  capped at 6 then "+{n}": "victim · {victim_name}", groups (`mentioned_group`, 2), "{victim country} / data breach"
  when `databreach_list` is non-empty, CVE ids (`font-code`, 2), industries (2), APAC, OT, 0-DAY (severity critical),
  REPORT; everything remains in the dialog. Footer row (siblings of the button): up to 2 media thumbnails as links to
  the post, and "Open on X ↗" (X12).
- **Rail** (right, `xintel-rail.tsx`; stacks below the feed under 1024 px). Card 1: title per D24 ("Last 24 hours" /
  "This week" / "Last 30 days" / "Selected range"), subtitle "What the classifier pulled from {total} posts", six rows
  in this order: "Confirmed incidents", "Mentions an APAC country", "CVEs mentioned", "Data breach claims",
  "Zero-days", "OT / ICS related" (numbers `font-code`, 0 shown as "0"). Card 2 "Most-named victims" / "From victim
  names, {period}": up to 5 rows name + count; empty "No victim named in this period". Card 3 "Most active accounts" /
  "Top 5 by posts in this period" (the old top authors, X9): rows are buttons that set the search to `@handle`.
- **Pager.** `NumberedPager` with summary "Showing {from}-{to} of {total}", 20 per page; page resets on any filter
  change.
- **Accounts tab** (`monitored-accounts.tsx`). Add row (only with `manage_tweets`): inputs "Handle" (placeholder
  "@FalconFeedsio"), "Display name", "Notes (optional)" each with a real `<label htmlFor>`, button "Add account"
  (disabled while empty or pending; 409/400 `detail` shown inline). `Table framed` with `table-fixed` and widths
  HANDLE 18% | DISPLAY NAME 18% | NOTES 30% | ADDED 12% | ACTIVE 10% | (Remove) 12%: handle `font-code`, ADDED
  `fmtShortDate`, ACTIVE a `Switch` ("Active: @handle", disabled without `manage_tweets`, errors toast), Remove a text
  button (destructive tone) opening the existing `ConfirmDialog` "Remove monitored account" (X19). Foot line
  "{n} accounts monitored · {k} active" (X20). Inactive rows are muted, not hidden.
- **Feature map.** X1 tabs; X2/X3 search; X4 Custom range; X5 APAC toggle; X6 Signal OT / ICS; X7 Confirmed toggle;
  X8 live filters + Clear filters; X9 header count + Most active accounts; X10 pager; X11 card; X12 Open on X; X13/X14
  detail dialog and "+ Newsletter"; X15 feed chip; X16-X20 accounts; X21 states (6.5).

### 6.2 Recap (frame 27898)
- **Routing and data.** `app/(app)/recap/page.tsx` reads `?kind=weekly|daily&date=YYYY-MM-DD` (both absent = latest
  weekly, as `GET /api/recap/latest` today); `selected` is derived from the URL and `router.replace` updates it.
  Query keys unchanged (`["recap","list"]`, `["recap","doc",kind,date]`, `["recap","doc","latest"]`) because the
  override and generate caches depend on them.
- **Header** (`recap-page-header.tsx`). Weekly: kicker "WEEKLY RECAP", h1 "Week {isoWeek}: {d Mon} – {d Mon}" (e.g.
  "Week 45: 27 Oct – 2 Nov", from `period_start` / `period_end`), description "AI-written recap of the week, grounded
  in the articles and posts it cites". Daily: kicker "DAILY RECAP", h1 "Recap for {fmtShortDate(date, withYear)}",
  description "AI-written recap of the day, grounded in the articles and posts it cites". Empty / loading: h1 "Recap".
  `actions`: "‹ Week 44" (outline; loads the previous Monday; daily: "‹ {previous date}"), `Select` "History" (items from
  `GET /api/recap/list?limit=60`, value `{kind}:{date}`, label single string "27 Oct - 2 Nov · week · 642 articles" /
  "2026-10-06 · day · 31 articles", `aria-label` "Recap history"), "Export PDF" (outline), primary "✦ Regenerate"
  (only with `manage_intel`). `lib/recap/period.ts` gains `isoWeek(mondayIso)` and `weekHeading(...)`; `formatRange`
  and `recapTitle` stay (history and tests rely on them).
- **Tiles** (`StatTile`, six in `lg:grid-cols-6`, two rows below): "ARTICLES", "POSTS" (`tweets`), "IOCs", "CVEs",
  "CAMPAIGNS", "NEW ACTORS" (`new_threat_actors`). Values from `doc.counts`. Sub from `quality.comparison.counts[key]`:
  "{±n}% vs week {N-1}" for articles, posts, IOCs, CVEs; "{±n} vs week {N-1}" for campaigns and new actors, and when
  `delta_pct` is null; muted, no red/green (more activity is not worse). No comparison: weekly "no prior week", daily no
  sub. Minus uses U+2212 (`signed()`).
- **Left column** (`lg:grid-cols-[minmax(0,1fr)_432px]`). Card SUMMARY: kicker, headline (`doc.headline`), paragraph
  (`yesterday.summary`); footer `text-2xs` muted: "Generated {fmtDateTime(generated_at)} · {model} · {n} tokens" (or "LLM
  skipped (no activity)"), "Grounding check: nothing was dropped" when `quality.grounding.count` is 0, "Weeks run
  Monday-Sunday by UTC date." (weekly). A grounding with dropped items is a `Notice tone="warning"` above the card
  ("Grounding check: {n} items dropped") with the existing `<details>` list and `dropReason` wording (R16). An empty
  recap (no headline and no summary) shows `Notice tone="warning"` "This recap is empty" with the existing sentence
  (model reply unreadable vs no content) and the raw output in a disclosure (R19). Card "Top stories" / subtitle per C9:
  numbered rows "01"…, title, `why_it_matters`, and the source as the link "{source} ↗" (`safeHttpUrl`, new tab; plain
  text when no `url`).
- **Right column.** "Active threat actors" (`Chips entity="intrusion-set"`), "Notable CVEs" (`Chips
  entity="vulnerability"`), "APAC signals" (lines; hidden when empty). Empty lists keep `EmptyNote`.
- **Row 2.** Card "Forecast for week {N+1}" / "Each forecast is scored next week" (C9; daily: "Forecast for the next 1-3
  days"): the forecast summary paragraph (muted), then one row per likely event: `f1` id, event, `ConfidenceBadge`
  (HIGH / MED / LOW), "Basis: …"; then "Watch items" as a list when present (R14). Card "Forecast hit rate" /
  "Does the stated confidence hold up? · last {hit_rate.weeks} weeks": `table-fixed` CONFIDENCE 28% | HITS / JUDGED 26% |
  HIT RATE 28% | UNCLEAR 18% rows high, med, low plus an "all" row; the rate bar and its percentage use the same
  `bg-primary`; "n/a" when nothing judged; the existing explanation of partial / unclear stays as a `text-2xs` footnote
  with "{reviewed_weeks} weeks reviewed". Below the table the line "Week {N-1} scorecard: f1 hit, f2 hit, f3 miss." (from
  `effectiveVerdict`: happened → hit, partly → partly, not_happened → miss, unclear → unclear) and a disclosure button
  "Review verdicts" that reveals the existing `ScorecardBlock` rows with the per-event verdict `Select` (R17). Weekly
  only; absent for daily or when the scorecard is missing.
- **More signals** (D27): `<h2>` "More signals" with a `Disclosure` (closed by default, open in print): "Week over week"
  (the existing `ComparisonBlock` table and "New this week" chips, `table-fixed` widths METRIC 36% | THIS WEEK 16% |
  LAST WEEK 16% | CHANGE 16% | % 16%), "Top tweets" (author, signal chip, summary), "Active campaigns" (theme,
  article count, why it matters). Raw LLM output (parse fallback) stays a disclosure at the bottom.
- **Regenerate dialog** (`recap-generate-dialog.tsx`, replaces the confirm and the date bar, R1-R5): title
  "Regenerate recap" when a recap exists for the chosen period (known from the history list), else "Generate recap";
  `SegmentedControl` "Week | Day" (default = the kind on screen, `aria-label` "Recap kind"); `DateField` "Week of" (snapped
  to its Monday, caption "{range} (Mon-Sun, UTC)") or "Date"; body "This calls the LLM and may take 10-30 seconds."; when
  overwriting, the warning "This overwrites the stored recap for this {week | date}." and force = true; confirm
  "Regenerate" / "Generate" (`confirmLoading`). A week whose Sunday has not ended in UTC shows the inline error "A week
  can only be generated after its Sunday has ended in UTC." and disables confirm (the API also answers 400).
  Success selects the returned `kind`/`date` and toasts "Recap generated"; failure shows the `detail` (502 empty,
  400 window) as a toast with the dialog kept open. Generating shows `Notice busy` "Generating the recap. This can take
  up to 30 seconds." in place of the content header.
- **Export PDF.** The button sets `document.title` to "Weekly recap 2026-W45" (daily: "Daily recap 2026-10-06"), removes
  the `dark` class from `<html>` for the print, calls `window.print()` and restores both in an `afterprint` listener.
  `globals.css` gains an `@media print` block (white page, no shadows, `break-inside: avoid` on cards, links print their
  text) and the masthead, utility bar, mobile nav, page actions, tabs and the More-signals toggle carry `print:hidden`.
- **Feature map.** R1/R2 dialog + previous button + history; R3/R4 dialog (force when it exists); R5 `Notice` and toasts;
  R6 History select; R7 summary footer; R8 summary; R9 top stories; R10 More signals; R11 chips; R12 More signals; R13 APAC
  signals; R14 forecast card; R15 More signals; R16 grounding `Notice`; R17 Review verdicts; R18 hit-rate card; R19 empty
  Notice + raw output; R20 empty state (6.5); R21 `manage_intel` gate.

### 6.3 Newsletter (frames 28635, 35311)
- **Shell.** `app/(app)/newsletter/layout.tsx` keeps metadata only; `NewsletterView` renders `PageHeader` kicker
  "NEWSLETTER", h1 "Newsletter composer", description "Monthly client newsletter: pick the articles, the AI writes the
  summaries, you approve", `actions`: "History" (outline, opens the sheet), "Preview" (outline) and "Generate edition"
  (primary), the last two only with `manage_newsletter`. State, refs and handlers in `newsletter-view.tsx` are kept as
  they are (`latest` ref, `receiveSuggestion`, `applyArticles`, queue sync); only the render tree, the period parameter
  and the `response.ok` checks change. `lib/newsletter/composer.ts`, `queue.ts`, `summary.ts` are not modified.
- **Suggestion bar** (`newsletter-suggestion-bar.tsx`, restyled with `Notice`): ready: "✦ Suggestion for {label} ready:
  {n} articles across {k} sections" (k = non-empty blocks among Highlights, Indonesia, Asia Pacific, Global) /
  "Built {formatBuiltAt} · ranked by severity, APAC relevance and source grade" (C14), buttons "Merge", "Use suggestion",
  ghost "Rebuild" (`manage_newsletter`). The loading, "No suggestion yet" (+ "Build suggestion"), error (+ Retry) and
  applied variants keep today's copy and logic (N1, N16).
- **Three columns** (`xl:grid-cols-[300px_minmax(0,640px)_minmax(0,356px)]` and `justify-between`; stack under 1280
  px with order Template, content, queue):
  1. **Template** (`newsletter-template-column.tsx`): card "Template" / "Period and sections". `Select` PERIOD with the
     last 6 calendar months ("1 – 31 Oct 2026", `lib/newsletter/period.ts::recentMonths`, WIB, C16), `aria-label`
     "Period", caption "{n} days" (C13); `Select` LANGUAGE "Indonesian | English" (`items`) with an "About summaries"
     `Disclosure` holding today's cost explainer (N6). Then a `SelectableList` (`aria-label` "Content blocks") of
     blocks: Highlights ("{n} of 3"), Indonesia, Asia Pacific, Global ("{full} full · {compact} compact"), a divider
     "Also in the email", then "Executive summary" (sub "{n} characters" / "empty"), "Campaign clusters" (sub "Off" /
     "Last {cluster_days} days") and "Footer and CSS" (sub "Default" / "Customised"). Default block = first non-empty
     of Indonesia, Asia Pacific, Global, else Highlights.
  2. **Content** (card, header = selected block). Section blocks: title + "{n} full cards · {m} compact" + `SegmentedControl`
     "Full | Compact" (`aria-label` "Card style shown"; Highlights has no segmented). Full view: article cards (title,
     "{source} · {date}", summary sentence, `CHECK SUMMARY` flag chip, actions: swap menu "⇄", move tier "↧", remove "✕",
     all icon buttons with `aria-label`, existing `SwapMenu`/`TierButton`/`ItemActions` logic) and, below them, a one-line
     "ALSO NOTED · {m} compact items" button that switches the segmented to Compact. Compact view: the existing rows.
     Each card has a "Note and options" toggle (`aria-expanded`) revealing the analyst note textarea (N9) and the
     "Regenerate summary" `Switch` (N10). The flag chip reads "CHECK SUMMARY · page could not be read" once a preview
     proved `body_sources === "metadata"` (N11), and "CHECK SUMMARY · source is often paywalled" before that, from
     `source-hints` (`paywall_likely`). Executive summary block: the existing `NewsletterSummaryField` (textarea, suggested
     paragraph states, replace confirm, rebuild; N5, N16). Campaign clusters block: `Switch` "Include top campaign
     clusters" and, when on, `Select` "Lookback: 7 | 14 | 30 days" (N12). Footer and CSS block: the two textareas of
     today's template panel (HTML allowed notes kept).
  3. **Your queue** (`newsletter-queue-panel.tsx`, restyled): card "Your queue" / "{n} articles · {k} suggested, not
     placed"; groups "Suggested, not placed" and "Queued articles" as today (N3, N4); each row is title + section chip
     (suggested rows: the item's `section`; queued rows: "Indonesia" when `ID` is among victim or mentioned countries,
     else no chip), a "+" menu to place into a slot with the existing limit toasts (N7), a remove button, "Clear all"; the
     "Why suggested" reasons and the paywall hint stay as `text-2xs` lines. Footer button "+ Add articles": a link to
     `/newsroom` with `target="_blank" rel="noopener"` and the hint "Use + Newsletter on any article" (D31). Because it
     opens a new tab, the view adds a `storage` event listener that re-reads `getQueue()` so articles queued in the
     other tab appear without a reload.
- **History sheet** (`Sheet`, title "Saved newsletters"): today's `NewsletterHistoryPanel` list (label, period,
  `created_by`, highlight, section counts, Preview, Resend with `manage_newsletter`, `MindmapWidget`), loaded when the
  sheet opens (`enabled: open`), first 20 as today. Choosing Preview closes the sheet and opens the dialog (N15).
- **Preview dialog** (`newsletter-preview-dialog.tsx`, rebuilt to the frame, 760 wide): `DialogTitle` "Preview · {label}
  edition" (saved mode: "Saved · {label} edition"), close "✕" (`aria-label` "Close"); `DialogDescription` "The email as the
  recipient will see it. Paywalled summaries are flagged." Above the iframe a `Notice` listing warnings (size, CVE
  markers) and the metadata-only titles (N13). Body: the server HTML in a sandboxed iframe, scrolling inside. Footer left:
  "{n} articles · {k} summary to check" (n = placed articles in the previewed request, k = metadata-only count); right:
  "Close" ghost and "Create Outlook draft" (primary, or "Create draft anyway" when warnings exist; for the header button
  "Preview" it is rendered outline and focus starts on Close; for "Generate edition" it is primary and focused once the
  preview loaded, C12); saved mode: "Resend" (`manage_newsletter`). The draft button stays disabled until the preview
  loaded, and the draft is built from the previewed body (N14).
- **Feature map.** N1 bar; N2 auto-fill (logic kept); N3/N4 queue; N5/N6 summary block and language; N7/N8 cards and
  menus; N9/N10 note and options; N11 flag chip; N12 clusters and footer blocks; N13/N14 dialog; N15 sheet; N16 confirms;
  N17 queue intake (kept) plus `storage` sync; N18 gates.

### 6.4 Tweet detail dialog
Restyled to the shared anatomy (`Dialog` + `DialogDescription`, close "✕", footer buttons), all `MetaRow`s kept (Signals,
Threat Groups, APAC, CVEs, Zero-Day, Data Breach, Industries, Country Roles, Incident block, LLM relevance, `fetched_at`,
`tweet_id`, X13), "+ Newsletter" (writes the shared localStorage queue, "Queued" / "Already queued" feedback, X14) and "Open
on X ↗" as footer actions; times through `fmtDateTime`; CVE ids `font-code`.

### 6.5 States
Pages: `StatePanel` loading (skeleton cards / tiles), error with Retry (`role=alert`), no access (the route guard already
hides the nav item). X Intel: empty feed "No posts match these filters" with action "Clear filters" (or "No posts
collected yet" when nothing is filtered), empty accounts "No accounts monitored yet" (+ the add row for `manage_tweets`),
rail cards show "–" while loading. Recap: empty "No weekly recap for {range}" / "No recap for {date}" with "Generate recap"
for `manage_intel`, else "Weekly recaps are generated automatically early on Mondays (UTC)." (R20); generating `Notice`
(6.2). Newsletter: the suggestion-bar states, empty queue "Your queue is empty" with the Newsroom link, empty block "No
articles here yet. Place some from the queue." Write actions hidden without permission (add / remove / toggle account,
Regenerate, Preview, Generate edition, Rebuild, Resend); the scorecard override is visible to every `view_intel` user.

### 6.6 New primitives and domain pieces (existing ones reused as they are)
1. **`Disclosure`** (`components/ui/disclosure.tsx`): a `<button aria-expanded aria-controls>` header and a region,
   `defaultOpen`, optional `printOpen` (region gets `hidden print:block` when closed). Used by Recap (More signals, Week over
   week, Review verdicts, raw output) and Newsletter (About summaries, Note and options).
2. Domain: `components/xintel/{xintel-page-header,xintel-toolbar,xintel-rail,feed-status-chip}.tsx`,
   `lib/xintel/filters.ts` (period → request params, anchor); `components/recap/{recap-page-header,recap-generate-dialog}.tsx`,
   `lib/recap/period.ts` (`isoWeek`, `weekHeading`); `components/newsletter/newsletter-template-column.tsx`,
   `lib/newsletter/period.ts` (`recentMonths`, `monthWindow`). `TweetStats` in `loose-types.ts` gains the B-X1 fields.
3. Reused: `UnderlineTabs`, `SegmentedControl`, `SelectableList`, `StatTile`, `Chip` (`kind` `status`, `severity`, `flag`),
   `Notice`, `StatePanel`, `Sheet`, `Switch`, `DateField`, `NumberedPager`, `SearchInput`, `ConfirmDialog`, `EntityChip` /
   `Chips`, `MindmapWidget`.

Replaced or removed: `feed-status-banner.tsx`, `tweet-badges.tsx` (as a component; its rules move into the card chip row),
the Week / Day button bar and the history sidebar in `recap/page.tsx`, `recap-history.tsx` (replaced by the History
select), the collapsible body of `newsletter-template-panel.tsx` (its inputs move into the Clusters and Footer blocks),
`newsletter-composer-sections.tsx` as an all-sections stack (it renders the selected block).

## 7. Out of scope
- Newsletter: "Send test to me" and its recipient / email column (B-N1), Preview Full | Compact (B-N2), a server
  lookback (B-N3), drag-to-reorder, an in-page article picker, an email template redesign, pagination of the history
  beyond the first 20.
- Recap: server-side PDF (B-R1), a "next week" arrow, changing the recap prompts, scorecard rules or the weekly schedule.
- X Intel: a `pg_trgm` index, filters in the URL, per-counter click-through filtering, the X API balance chip (still not
  ported), changing the collector or the freshness thresholds.
- The session-expired dialog (4c), Scrapers and Data Health (4b), Login and Admin (4c); mobile layouts beyond the 1024 px
  collapse.

## 8. Verification
- **Backend tests.** `uv run pytest tests/integration -k "tweet or monitored or api_permissions"` (Docker), then `uv run pytest
  tests/unit tests/contract packages` (deselect the two known Mac-only failures). Named tests: 4.1 and 4.2.
- **Static.** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src
  packages/cti-scraper/src` (covers the repository change).
- **Contract.** `uv run python tools/export_openapi.py`; `cd apps/web && pnpm run gen:api`; commit both; update `TweetStats`;
  review and `--snapshot-update` `test_tweets_router_snapshot.py`.
- **Web.** `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit`; `pnpm build`. The pure helpers (`isoWeek`,
  `recentMonths`, period → params) have no unit runner: check them in QA on the year boundary (week 53 / 1) and on a month
  with 28 days.
- **Visual (local).** Isolated compose project `qacve`, API via uvicorn, web via `pnpm dev`, synthetic data: tweets across 40
  days with confirmed / APAC / CVE / zero-day / data-breach / OT / report mixes and a stale-feed case, monitored accounts
  (one inactive), weekly recaps for several weeks (one with dropped grounding items, one empty, one without a previous
  week), a daily recap, scorecard events, a monthly suggestion (and a month without one), a queue of Newsroom and X Intel
  articles with a paywalled source, saved editions; LLM stubbed. Screenshots of all five frames' states at 1440 and 1000 px,
  light and dark, against 27680/28830, 38457/40021, 27898/29048, 28635/29284 and 35311/36240. Checks: keyboard pass (tabs,
  period, toggles, Signal select, History select, previous week, Regenerate dialog, block list, segmented, card menus,
  Disclosures, Sheet, dialogs), no nested interactive element (a11y tree check on the tweet card and article card), print
  preview in Chrome and Safari (light output even from dark mode, no masthead, cards unbroken, More signals open), contrast of
  chips and the hit-rate bar in both themes, every X / R / N feature reachable (checklist in the PR), the tab title keeps
  the "· {PLATFORM_NAME}" suffix on all three pages, a 4xx is not retried.
- **Delivery.** Commit per backend item and per page; merge into `origin/Dev` (standing approval). On dev 172.25.1.77
  (read-only checks): X Intel with a real period, Recap of the latest week, Newsletter suggestion load; no generation or
  draft creation without the user's go (LLM calls and a Graph draft).

## 9. Risks
- **Newsletter regression.** The composer is the largest change surface (a 600-line state machine). Mitigated by leaving
  `composer.ts`, `queue.ts`, `summary.ts` and the handlers untouched and changing the render tree; if 4a grows too big,
  Newsletter is cut out as 4a-2 (inventory D1 fallback).
- **WIB months on the client.** `recentMonths` uses a fixed UTC+7; if `WORKER__REPORT_UTC_OFFSET_HOURS` is ever changed, the
  period list and the server default window disagree by a few hours at month edges. Acceptable for the current
  deployment; an API field would fix it.
- **Stats cost.** Two more queries per stats call, called on every filter change (debounced). Fine at current size; the
  Performance note in 4.1 names the trigger to revisit.
- **Print.** Dark-mode removal and `afterprint` restore differ across browsers (Safari fires it late); a failed restore
  leaves the page light until reload. Checked in both browsers; the title restore is the same listener.
- **Search semantics change.** Free text now also matches handles, victims and CVEs, so counts for an existing search
  can rise; intended (mockup), noted in the changelog.
- **Two buttons, one flow** (C12) may read as redundant; it follows the mockup and the draft-only-from-preview rule.
- **Lost composer state when leaving the page** is unchanged (placements live in React state); the new-tab "+ Add
  articles" avoids it for the common case.
- **Contract drift.** Forgetting the regen fails the CI drift check; it is in the verification list.
