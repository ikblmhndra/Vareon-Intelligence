# FigCraft redesign, sub-project 2b: Intelligence (backend + UI)

Date: 2026-11-09. Status: draft for review. Branch: `claude/figcraft-design-data`. Same one-PR release 0.8.16
(the CHANGELOG entry and the 0.8.16 runbooks are extended, no extra version bump).

## 1. Context and goal

Sub-project 1 (foundation) restyled the shell and the shared primitives; sub-project 2a (CVE Tracker) added the
master/detail, list and form primitives that now live in `apps/web/src/components/ui/` (`MasterDetail`,
`SelectableList`, `StatTile`, `Field`, `FilterSelect`, `SearchInput`, `RowMenu`, `Notice`, `NumberedPager`,
`LoadMoreFooter`, `Switch`, `RadioList`, `Dropzone`, `Chip` kinds incl. `risk`) and the browser-timezone formatters in
`apps/web/src/lib/format.ts`. This spec is **2b: the nine Intelligence tabs, the entity detail page and their dialogs**.

FigCraft frames (light; each has a dark variant beside it): Early Warning 15766, Source Reliability 16221, MITRE
Heatmap 16600, Campaign Clusters 17074, PIR 17342, IOC Management 18079, Dialogs 34382, Entity Detail 37115, More Tabs
37946 (Needs review, Allowlist, FP analytics, Clusters (Simple)), Risk Matrix 41332, Entities 41886, RFI 44165.

Today every tab is a stack of ad-hoc inputs and full-width tables under one fixed `<PageHeader title="Intelligence">`
(`app/(app)/intelligence/layout.tsx`). The mockup gives each tab its own header, preset toolbars, stat tiles, a
list card plus a detail or accent card, and several data points that do not exist yet.

Goal: deliver the **full mockup, keep every existing feature reachable**, and add the missing data (section 4). Backend
lands first, the contract is regenerated once, then the views are built on real data. The gap inventory behind this
spec (session scratchpad, not committed) lists every frame element and its source; where they differ, this spec wins.

## 2. Decisions (binding, from the user)

Scope
- **S1** Full mockup. Every existing feature stays reachable: re-homed into panels, sections or menus, never dropped.
- **S2** Release stays 0.8.16, one PR; `CHANGELOG.md` (Indonesian) and `docs/prod-upgrade/0.8.16.md` +
  `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` are extended.

Shell and controls
- **D1** Kicker "INTELLIGENCE" plus a per-tab `<h1>` and description; the document title is per tab.
- **D2** Toolbars use the mockup presets, plus a **"Custom…"** option that keeps free values within the API range.
- **D3** One `HeroPanel` primitive (dark accent panel) built on the `bg-hero`/`text-hero-*` tokens.
- **D4** Newsroom gains `actor` / `industry` URL filters so every "Open in Newsroom" link really filters.
- **D7** Row click opens the detail or edit dialog; secondary row actions live in a "⋯" `RowMenu`.

Early Warning, Source Reliability, MITRE
- **D5** Early Warning row click selects the spike into "Strongest signal"; the default selection is the highest z.
- **D6** SR origin labels: `default` → "auto", `analyst` → "analyst".
- **D8** SR **Grid view** and **Export CSV** are built; export goes through a new endpoint.
- **D9** MITRE Industry view stays, via a segmented "Actors | Industries".
- **D10** The D3FEND countermeasures toggle stays, inside the cell drill panel.

Campaigns
- **D11** Cluster similarity threshold API range unchanged (0.2-0.7); the UI adapts (mockup 0.72 is not offered).
- **D12** Clusters (Simple) load automatically; the existing toggles (exclude low reliability, single-source) stay.
- **D13** Geopolitical panel, trends, mind map, hunt pack, related campaigns, member articles and IOC list all stay, in
  the campaign detail panel.

PIR and RFI
- **D14** Display ids `PIR-03` / `RFI-12`: zero-padded to two digits, wider when the id is 100 or more.
- **D15** PIR priority display P1 → Critical, P2 → High, P3 → Medium. No "Low", no migration of stored values.
- **D16** The backend 14-day gap rule stays; UI copy says "14 days".
- **D17** New fields on `PIROut` for linked RFIs and matched campaigns (backend).
- **D18** The PIR dialog keeps description, malware, news types and status in an **"Advanced"** section; no data loss.
- **D19** RFI question, requester, due date and linked PIR stay editable after create, via "⋯ → Edit".

IOC
- **D20** All four actionability values are shown with the mockup chip style (BLOCK, INVESTIGATE, MONITOR, ARCHIVE).
- **D21** "Remove from feeds" = FP verdict with a note (revokes, restorable by TP). Hard delete stays in "⋯" with a
  confirm.
- **D22** IOC CSV export through a new endpoint that honours the full filter set.
- **D23** The IOC panel keeps TLP/PAP marking, the threat-actor link editor, the source FP warning and delete.

Entities
- **D24** Build the entity AI summary sentence and article count: extend the LLM entity-profile prompt and the API
  (new fields), existing profiles fill on regeneration; repo prompt-version and `llm_calls` conventions apply.
- **D25** Relationship confidence words: ≥ 0.8 high, ≥ 0.5 medium, else low (see 3, C1 for the 0-100 scale).
- **D26** The entity page keeps the Hunt tab, the mind map, "Generate profile" and the description.
- **D27** Entities gets an "All" tab; the ATT&CK sync card moves to MITRE; the suppressed filter and the Watchlist
  Navigator export stay reachable.
- **D28** The existing mobile card fallback in Entities (< 640 px) stays.

Already on this branch (consumed, not rebuilt): `GET /api/pir/{id}/coverage/weekly`, the `daily` block and zero-filled
baseline on `GET /api/spikes`, heatmap-scoped `navigator-layer` / `navigator-export` params, the Open-in-Navigator
download flow, and the risk tier scale LOW/MED/HIGH (`Chip kind="risk"`, `RISK_MED_MIN` 40 / `RISK_HIGH_MIN` 70 in
`lib/exec/format.ts`).

## 3. Conflicts between inputs, and how they are resolved

- **C1 Relationship confidence scale.** D25 states 0.8 / 0.5, but `entity_relationships.confidence` is
  `SmallInteger` 0-100 (`CheckConstraint("confidence BETWEEN 0 AND 100")`, `RelationshipOut.confidence: int | None`).
  Applied as ≥ 80 high, ≥ 50 medium, else low; `null` → "unrated".
- **C2 IOC export "tenant-scoped".** `indicators` has no `client_id`; IOCs are platform-wide and `GET /api/iocs` ignores
  `X-Client-ID`. The export is exactly as scoped as the list (permission-gated, not client-filtered). Section 4.5.
- **C3 Newsroom filters are already in the API.** `GET /api/articles` (`routers/articles.py::list_articles`) already
  takes `threat_actor[]`, `industry[]`, `ttp[]`, `country[]`; D4 is a web URL contract plus a regression test (4.1).
- **C4 IOC "Action" column.** The chip value is `actionability_label` (`block_now|investigate|monitor|archive`, from
  `services/confidence.py::_ACTIONABILITY_LABELS`); `recommended_action` is a sentence ("Add to EDR blocklist") and is
  shown in the detail panel. Confidence is an integer 0-100, shown as "92" (mockup "0.92" is illustrative).
- **C5 Entity tabs.** Mockup: All, Threat actors, Malware, Techniques, Sectors, Locations, CVEs. Code has eight tabs
  (`lib/entities/types.ts::ENTITY_TABS`, incl. Campaigns and Victims). Result: All + all eight, with the mockup words
  where they map (Threat actors, Malware & tools, Techniques, CVEs, Campaigns, Sectors, Locations, Victims).
- **C6 Entities sort.** Mockup "sorted by mentions in 30 days"; the API keyset-sorts by `lower(name)` and `Entity.id`
  (`services/entities.py::list_entities`). User decision: the Entities page sorts by 30-day mentions (new opt-in
  `sort=mentions`, 4.7); pickers and dialogs keep the name sort. The card subtitle says "sorted by mentions (30 d)".
- **C7 Article count in the profile.** "from 143 articles" is illustrative: the model is given at most 10 article
  titles from the last 90 days (`AsyncTAProfileRepo.fetch_recent_news(days=90, limit=10)`). The stored count is the
  number of articles in the context, and the UI says "from N recent articles".
- **C8 Migration.** No backend item needs a schema change (summary lives in the profile JSONB, SR `origin` and the
  allowlist `note` columns exist, counts are computed). **No migration**; Alembic head stays `b7d41e9a2c63`.
- **C9 Copy against code.** "How detection works", "How the score works" and the gap card are rewritten from the code
  (`services/spike.py`, `services/risk_matrix.py`, `repositories/pir.py::compute_coverage`), not copied from the mockup.
- **C10 PIR priority Low and the 4-option dialog.** D15 wins: the dialog segmented control has three options.

## 4. Backend

Conventions. Tenant: `cid = effective_client_id(user, x_client_id)`. Router permissions are unchanged: `/api/pir`,
`/api/rfi`, `/api/sr`, `/api/intelligence`, `/api/mitre` = `view_intel`; `/api/iocs` = `view_ioc`;
`/api/entities` = `view_ta`. Writes keep their existing permissions. Every new export requires `export_data` and writes
an audit row (`AsyncAuditLogRepo.write`, then `session.commit()`). Comments and docstrings in Indonesian, matching the
files. After the API changes: `uv run python tools/export_openapi.py`, `cd apps/web && pnpm run gen:api`, and update
`apps/web/src/lib/api/loose-types.ts` for the untyped dict responses (spikes `daily`, IOC list, FP analytics).

### 4.1 Newsroom actor / industry filters (D4)
- **Contract.** No API change. `GET /api/articles` already ANDs `threat_actor[]`, `industry[]`, `ttp[]`, `country[]`,
  `posted_on_start` (`AsyncArticleRepo.list_filtered` → `_apply_list_filters`; actor and sector go through
  `entity_ids_named`, so aliases match; country = ISO alpha-2, any role).
- **Web URL contract** (`app/(app)/newsroom/page.tsx`, read once on load like `?country=`): `actor`, `industry`, `ttp`
  (repeatable), `country`, `period` (1|7|30, existing) and new `from` (local `YYYY-MM-DD`; sets `dateStart`, wins over
  `period`). When `actor`, `industry` or `ttp` is present the page opens `ArticleListSheet` with a new source
  `{ query: { threat_actor?, industry?, ttp?, country? }, title }` (one more `useArticlesQuery` branch beside
  `byActor`/`byTtp`); `country` alone keeps today's behaviour (masthead filter). Title = the values joined with " × ".
- **Producers.** `lib/newsroom/links.ts::newsroomHref({actor, industry, ttp, country, from, period})`, used by Early
  Warning (actor/industry/country spike, `period=7`), Risk Matrix (industry × country, `from` = start of the selected
  period: today − days), MITRE (row × technique: `actor` or `industry` + `ttp`, `from` = today − days).
- **Tests.** `tests/integration/test_articles_combined_filters.py`: actor + ttp, industry + country and an alias name
  each return only articles matching all filters; `total` equals the risk-matrix `current_count` for a seeded cell when
  the window matches (guards the "N articles" number shown before the click).
- **Risk.** Risk-matrix cells need ≥ 2 articles and count articles per (industry, country) mention pair; the Newsroom
  list for the same pair may differ by articles whose `posted_on` is null (excluded by both). Documented in the panel
  footnote "Opens Newsroom with the same industry, country and period".

### 4.2 PIR preview match count
- **Contract.** `POST /api/pir/preview` (permission `manage_pir`, the dialog's permission) with body
  `PIRPreviewIn {criteria: PIRCriteria, days: int = 90 (1..365)}` → `PIRPreviewOut {count: int, days: int, since:
  date, has_criteria: bool}`. POST because criteria are seven string lists.
- **Logic.** In `routers/pir.py`: `since = today - days`; `_, count = await AsyncArticleRepo(session).list_filtered(
  page=1, page_size=1, posted_on_start=since, **_criteria_filters(body.criteria.model_dump()))` (the same helper as
  `compute_coverage`, so the preview equals the future coverage definition). `has_criteria =
  _has_criteria(criteria)`; with no criteria the count is "every article" (the existing match-all quirk) and the UI
  says so. The PIR's own start/end dates are ignored on purpose: the mockup copy is "in the last 90 days".
  `_criteria_filters` and `_has_criteria` become public names in `cti_core.db.repositories.pir` (`criteria_filters`,
  `has_criteria`; old names kept as aliases for the existing callers).
- **Scoping.** Articles are global (as for coverage), so no client filter; no write, no audit.
- **Performance.** One `COUNT(*)` over the 90-day window with the entity `EXISTS` filters; the UI debounces 500 ms and
  caches per criteria JSON (react-query key).
- **Tests.** `tests/unit/test_pir_preview_body.py` (days bounds 422, unknown criteria key 422 through
  `PIRCriteria`); `tests/integration/test_pir_preview_api.py` (count equals `compute_coverage` total for a PIR with the
  same criteria and `start_date = since`; empty criteria → `has_criteria=false`; 403 without `manage_pir`).

### 4.3 `PIROut` linked RFIs and matched campaigns (D17)
- **Contract.** `PIROut` gains `linked_rfis: list[PIRLinkedRFI] = []` with `PIRLinkedRFI {id, status, question
  (first 120 chars), due_date}`, `linked_rfi_open: int = 0` (status `open` or `in_progress`) and `matched_campaigns:
  list[PIRMatchedCampaign] | None = None` with `PIRMatchedCampaign {cluster_id, title, size, severity_label,
  last_seen}`. `GET /api/pir` gains `include_campaigns: bool = False` and `campaign_days: int = 30 (7..90)`.
  `matched_campaigns` is `null` unless requested. `POST`/`PUT` responses keep `linked_rfis` filled and
  `matched_campaigns: null`.
- **Linked RFIs logic.** `AsyncRFIRepo.list_by_pirs(client_id, pir_ids)`: one `SELECT` on `rfi_requests WHERE
  client_id = :cid AND linked_pir_id IN (...)` ordered `open, in_progress, closed`, then `due_date NULLS LAST`; at most
  20 per PIR in Python. `AsyncPIRRepo.list_pirs` stays as is; the router joins the two results (no change to the
  coverage loop). The client filter matters: `linked_pir_id` is an FK without a client check, so an RFI of another
  client pointing at this PIR must not leak.
- **Matched campaigns logic.** Only when `include_campaigns`: one call `campaign_service.get_recent_campaigns(session,
  days=campaign_days, client_id=cid, min_size=3)` per request, then invert each campaign's `matched_pirs` into
  `{pir_id: [campaign…]}` (sorted by `severity_score` desc, at most 5 per PIR). `_match_pirs` matches only **active**
  PIRs (`list_active_by_client`), so paused and archived PIRs get `[]`; the UI states it. No audit row (the PIR page is
  not the campaigns view; `/api/clusters/recent` keeps its `view_campaigns` audit).
- **Performance.** Linked RFIs: one indexed query (`ix` on `client_id`; the table is small). Campaigns: the full
  uncached pipeline (≤ 2000 articles, CVE prioritisation, diamond models; seconds on dev), hence opt-in: the PIR page
  renders from `GET /api/pir` and fetches `GET /api/pir?include_campaigns=true` in the background (separate
  react-query key, `staleTime` 10 min), filling only the "Campaigns matched" row. Coverage counts are computed twice in
  that flow (two `list_filtered` counts per PIR; acceptable for < 50 PIRs).
- **Flag (controller decides).** Smaller alternatives: (a) no backend for campaigns: the PIR panel reverse-looks-up
  `matched_pirs` from the `/api/clusters/recent?days=30` query the Campaigns tab already uses; or (b) a separate
  `GET /api/pir/campaign-matches?days=30` returning `{pir_id: [...]}` so coverage is not computed twice. The UI row is
  identical in all three.
- **Tests.** `tests/integration/test_pir_query.py::test_linked_rfis_*` (open count, other-client RFI excluded, cap 20,
  order); `tests/integration/test_pir_campaign_matches.py` (campaign service monkeypatched: inversion, paused PIR gets
  `[]`, `null` when not requested, `campaign_days` bounds); update `test_pir_router_snapshot.py` (`--snapshot-update`).

### 4.4 Source reliability: origin filter and CSV export (D6, D8)
- **Contract.** `GET /api/sr/entries` gains `origin: Literal["default", "analyst"] | None = None`. New `GET
  /api/sr/entries/export` (`export_data`) with the same `search`, `grade`, `origin`, `sort_by`, `sort_dir` → `text/csv;
  charset=utf-8`, `Content-Disposition: attachment; filename="source-reliability-YYYYMMDD.csv"`. Columns:
  `source_name, admiralty_code, reliability_grade, reliability_label, credibility_code, credibility_label,
  content_kind, origin, analyst_name, notes, added_date, last_updated`. Labels from `RELIABILITY_LABELS` /
  `CREDIBILITY_LABELS` (the `/api/sr/labels` maps). Declared before the `/entries/{entry_id}` routes.
- **Logic.** `AsyncSourceReliabilityRepo.list_entries(..., origin)` adds `WHERE origin = :origin` (the column has a
  CHECK `origin IN ('default','analyst')`). Ordering gains the tie-breaker `SourceReliabilityEntry.id` (stable pages;
  the UI default `sort_by=last_updated&sort_dir=desc` has many equal dates). Export reuses the same statement with
  `page_size` = `_EXPORT_CAP` 5000 (the table holds one row per source, ~100-300) through the shared CSV helper (4.10).
  Audit `export_source_reliability` with the filters and row count.
- **Scoping.** SR entries are global (no `client_id`), as today.
- **Tests.** `tests/integration/test_source_reliability_query.py` (origin filter, id tie-breaker across pages);
  `tests/integration/test_sr_export_api.py` (403 without `export_data`, filters honoured, header row, a note starting
  with `=` is neutralised, audit row); snapshot update `test_source_reliability_router_snapshot.py`.

### 4.5 IOC CSV export (D22)
- **Contract.** New `GET /api/iocs/export` (`view_ioc` router-level + `export_data`) with the list's filters:
  `ioc_type`, `search`, `sort_by`, `actionability`, `include_suppressed`, `state` → CSV, filename
  `iocs-YYYYMMDD.csv`. Columns: `id, type, value, state, tlp, pap, confidence_score, actionability_score,
  actionability_label, recommended_action, seen_count, first_seen, last_seen, tp_count, fp_count, threat_actors
  (";"-joined), tags (";"-joined), auto_suppressed, suppression_reason, revoked_at`. Values stay canonical (as stored,
  not defanged), the same as the v2 feed. Declared before `/{ioc_type}/{value:path}`.
- **Logic.** `AsyncIndicatorRepo.list_filtered` is split into `_filtered_stmt(...)` (filters only) and the paging part;
  the export uses `_filtered_stmt` with the same ordering plus the new tie-breaker `Indicator.id.desc()` (also added
  to the list: today equal `last_seen_at` values can repeat or skip rows across pages). Rows are read in keyset batches
  of 2000, written to a `StringIO` and returned as one `Response` (the v2 `_csv` pattern; no streaming across the
  request-scoped session). Cap `_EXPORT_CAP = 50_000` rows; when hit, header `X-Export-Truncated: true` and the UI shows
  a toast. `search` goes through `canonical(...)` exactly as `list_iocs`. Audit `export_iocs` with filters and count.
- **Scoping.** Platform-wide (C2). Every TLP is included, as in the UI list; the file carries the `tlp`/`pap` columns.
- **Tests.** `tests/integration/test_ioc_export_api.py` (each filter, suppressed excluded by default, `state=allowlisted`
  includes hidden rows, cap header with the cap monkeypatched to 3, 403 without `export_data`, a value starting with
  `@` is neutralised, audit row); `tests/integration/test_ioc_query.py::test_list_stable_order_ties`.

### 4.6 Allowlist suggestions TP count (and allowlist note)
- **Contract.** Each `suggested_allowlist` item of `GET /api/iocs/fp-analytics` gains `tp_count: int`.
- **Logic.** `services/fp_analytics.py::get_fp_analytics` adds `"tp_count": tp`. By the suggestion rule (`fp >= 3 and tp
  == 0`) it is always 0 today; the field makes the "0 TP · 6 FP" cell data-driven if the rule changes. The 15-minute
  cache is unchanged.
- **Needed addition (beyond the approved list, flagged).** The Allowlist tab has a Note input, but `AllowlistBody` has
  no `note` although `ioc_allowlist.note VARCHAR(300)` exists and `GET /api/iocs/allowlist` returns it. Add `note:
  str | None = Field(None, max_length=300)` to `AllowlistBody`; `AsyncIocAllowlistRepo.create(*, entry_type, value,
  added_by)` gains `note: str | None = None` (stored stripped, blank → NULL; an existing entry keeps its note); return
  it in the POST response. The detail panel's "Allowlist" button sends `note = "from IOC {value}"`.
- **Tests.** `tests/integration/test_fp_analytics_service.py::test_suggestion_has_tp_count`;
  `tests/integration/test_ioc_allowlist_flag.py::test_allowlist_add_with_note` (stored, listed, 422 over 300 chars).

### 4.7 Entities list: total and first_seen
- **Contract.** `EntityListResponse.total: int | None = None`; `EntityListItem.first_seen: datetime | None`.
- **Logic.** `services/entities.py::list_entities`: when `cursor is None`, `total = SELECT count(*)` over the same
  filtered statement without cursor and limit (`stmt.with_only_columns(func.count(Entity.id)).order_by(None)`); later
  pages return `null` and the UI keeps the first value. `first_seen=e.first_seen` (column exists). "All" tab = no
  `type` param, which `_check_types(None)` already accepts.
- **Performance.** One extra count per first page; the alias `EXISTS` filter is the same as the page query.
- **Tests.** `tests/integration/test_entities_api.py::test_list_total_first_page_only` (total with `type`, `q`,
  `watched`, `include_suppressed`; `null` with a cursor; tombstones excluded) and `::test_list_item_first_seen`.
- **Sort by 30-day mentions (C6).** New query param `sort: Literal["name", "mentions"] = "name"` on `GET
  /api/entities`; the default keeps today's behaviour for `entity-autocomplete`, `entity-create-dialog`,
  `entity-merge-dialog` and `relationship-create-dialog`. Only `entities-list-view.tsx` sends `sort=mentions`.
  - Logic: `mentions` LEFT JOINs a subquery `count(DISTINCT article_id)` per `entity_id` over `EntityMention` joined to
    `Article` where `_article_day() >= today - 30 days` (same window and day expression as `_mention_counts`, so the
    sort key equals the row's `mentions_30d`), `coalesce(n30, 0)`. Order `n30 DESC, _sort_key() ASC, Entity.id ASC`.
  - Cursor: `encode_cursor` gains an optional count; a `mentions` cursor is the JSON `[n30, name_key, id]`, a `name`
    cursor stays `[name_key, id]` (old cursors keep working). Keyset predicate `n30 < c OR (n30 = c AND
    (name_key, id) > (c_name, c_id))`. A cursor of the wrong shape for the requested `sort` is a 422, as today.
  - Counts shift while paging (a new article can move an entity across pages); accepted, as with any live keyset.
  - Performance: the 30-day subquery is bounded by the window and served by
    `ix_entity_mentions_entity_id_article_id`; no new index. The plan runs `EXPLAIN ANALYZE` on dev-sized data
    (read-only, local copy of the synthetic seed scaled up) and records the timing; add an index only if one page
    exceeds 300 ms.
  - Tests: `tests/integration/test_entities_api.py::test_list_sort_mentions` (order by 30-day count, ties by name then
    id, zero-mention entities last, `mentions_30d` in the row equals the sort key, cursor pages are disjoint and
    complete across a tie boundary, filters still apply) and `::test_list_sort_mentions_bad_cursor` (a `name` cursor
    with `sort=mentions` returns 422); a unit test for the cursor round trip in both shapes.

### 4.8 RFI per-status counts
- **Contract.** `RFIListResponse.status_counts: RFIStatusCounts {open: int, in_progress: int, closed: int}`, computed
  for the client independent of the `status` filter.
- **Logic.** `AsyncRFIRepo.status_counts(client_id)`: one `SELECT status, count(*) ... WHERE client_id = :cid GROUP BY
  status`, missing statuses → 0, unknown stored statuses ignored.
- **Flag (small, recommended).** Search, "Linked PIR" filter and "due soonest" sort are client-side over loaded pages
  (25 per page with load more), so a search can miss unloaded rows. Smallest fix in the same query: `q`
  (`question ILIKE` or `requester ILIKE`), `linked_pir: int | None` and `sort: Literal["created", "due"] = "created"`
  (`due`: `due_date ASC NULLS LAST, id`). The UI below is written to use them if accepted and falls back to client-side
  filtering if not.
- **Tests.** `tests/integration/test_rfi_query.py::test_status_counts_*` (per client, filter-independent); with the flag:
  `::test_search_and_linked_pir_filter`, `::test_sort_due`. Snapshot update `test_rfi_router_snapshot.py`.

### 4.9 Entity profile summary and article count (LLM, D24)
- **Prompt.** `services/ta_profile.py::_SYSTEM_PROMPT` gains a top-level schema key placed first:
  `"summary": "<2-3 plain sentences, at most 600 characters: who the actor is, what it targets and what the recent
  reporting in the context adds. Use only the provided context; write null when the context says nothing>"`.
  `_PROMPT_VERSION = prompt_version(_SYSTEM_PROMPT)` changes automatically, so `llm_calls.prompt_version` separates old
  and new calls; `_call_llm` keeps `get_llm_client(task="ta_profile")` (instrumented `llm_calls` logging, JSON mode). No
  new task name, no new Settings key.
- **Post-processing.** New pure `normalise_summary(profile, context)`: non-string → `None`; collapse whitespace; scrub
  CVE ids not present in the context with `grounding.Grounder(grounding.Known.build(text=context)).free_text("summary",
  …)` (the newsletter-summary pattern, `services/newsletter_summary.py`); cut at 600 characters on a word boundary.
  `build_profile_input` returns a `NamedTuple ProfileInput(message, mitre_group_id, article_count)` with
  `article_count = len(news)` (C7). `generate_ta_profile` stores `profile["summary"]` and `profile["_article_count"]`
  beside the existing `_generated_at` / `_actor_name` keys (JSONB, no migration).
- **API.** `EntityDetail` gains `profile_summary: str | None` and `profile_article_count: int | None`, read in
  `services/entities.py` (where `profile=` / `profile_generated_at=` are built) from `profile.get("summary")` and
  `profile.get("_article_count")`. Profiles generated before this change return `null` for both until regenerated; the
  UI then shows the profile table without a paragraph and a hint "Regenerate to add a summary" (only with
  `manage_intel`). TA Room responses carry the new keys inside the JSON blob (additive).
- **Tests.** `tests/unit/test_prompt_correctness.py` (schema contains `"summary"`, `normalise_summary` cases: non-string,
  overlong, unknown CVE replaced, known CVE kept); `tests/integration/test_ta_profile_context.py` (update for the
  3-field `ProfileInput`, `article_count` equals the number of seeded titles, capped at 10);
  `tests/integration/test_entities_api.py::test_profile_summary_exposed` (LLM stubbed); keep
  `tests/unit/test_llm_call_sites.py` green (no new call site).
- **Risk.** The model may still write a generic sentence; the "REVIEW BEFORE SHARING" chip stays and the paragraph is
  labelled "AI summary".

### 4.10 Shared CSV helper
New `apps/api/src/cti_api/services/csv_export.py`: `csv_response(header, rows, filename) -> Response` (UTF-8 with BOM
for Excel, `\r\n`) and `safe_cell(value)`: `None` → "", datetimes ISO, lists `;`-joined, and any string starting with
`=`, `+`, `-`, `@`, tab or CR is prefixed with `'` (CSV formula injection; the existing v2 CSV has no guard and is left
unchanged to keep its machine contract). Used by 4.4 and 4.5. Test `tests/unit/test_csv_export.py`.

### 4.11 Documentation touched
`docs/ARCHITECTURE.md` (PIR campaign-match cost, export endpoints), `CHANGELOG.md` 0.8.16 entry (Indonesian: new
endpoints, Newsroom URL params, profile summary needs regeneration, IOC/SR exports need `export_data`),
`docs/prod-upgrade/0.8.16.md` and `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` (no migration, no new env keys; optional
post-deploy step: regenerate profiles of watched actors to fill summaries, which costs one LLM call each).

## 5. Migration summary

None (C8). Current head `b7d41e9a2c63` (`alembic/versions/b7d41e9a2c63_cve_tracker_mockup_data.py`, added by 2a) stays
the head; `tests/integration/test_migrations_match_models.py` is unaffected. No new `Settings` field, so `.env.example`
and `.env.prod.template` are unchanged. Syrupy snapshots to update after review: `test_pir_router_snapshot.py`,
`test_rfi_router_snapshot.py`, `test_source_reliability_router_snapshot.py`, `test_iocs_router_snapshot.py`.

## 6. UI

Global rules. Desktop 1440 first (content width 1328). Two-column layouts collapse to one column below 1024 px (`lg:`).
No `backdrop-blur`. Colours only through tokens; text on tints uses `text-X-text`; heat tints cap alpha instead of
flipping text colour. Focus ring `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2
focus-visible:ring-offset-background`. Minimum text 11 px (`text-2xs`). Base UI, not Radix (`render={<X/>}`,
`SelectItem` children a single string, `Select items` prop for sentinel values). IDs, IOC values, TTP/CVE ids in
`font-code`. All dates through `lib/format.ts` (browser timezone): `fmtShortDate`, `fmtDateTime`, `fmtTime`,
`fmtCompactAge` (+ " ago" where the mockup says "ago"); no `WIB`/`UTC` literal remains in Intelligence views. Every
search input without a visible label has `aria-label`; icon-only buttons have `aria-label`. Loading, empty, error and
no-access states use `StatePanel` everywhere (replacing the ad-hoc "Loading…" text in every view).

### 6.0 Page shell (all tabs)
- `app/(app)/intelligence/layout.tsx` stays a Server Component and renders a new client `IntelligencePageHeader`
  (`components/intelligence/intelligence-page-header.tsx`, keyed on `usePathname()`, pattern of
  `components/cve/cve-page-header.tsx`): `PageHeader kicker="INTELLIGENCE" title description` from a route table
  (`lib/intelligence/routes.ts`, the inventory's H1/description table; e.g. "MITRE ATT&CK heatmap" / "Which techniques
  each threat actor is reported using; click a cell for the articles behind it"), then `IntelligenceNav` (same 9 pills,
  same order), then the thin rule. For `/intelligence/entities/[id]` the header and the pills render nothing; the
  entity page owns its `<h1>` (6.11). `/intelligence/entities/resolve` keeps the Entities header.
- Document title (D1): each route segment gets a tiny server `layout.tsx` exporting `metadata.title` ("Risk matrix",
  "Source reliability", "Early warning", "PIR", "RFI", "MITRE ATT&CK heatmap", "Entities", "IOC management", "Campaign
  clusters"); the root template appends the platform name. The entity detail sets `document.title = "{name} · Entities"`
  in a `useEffect` once loaded (pages are client components).
- Toolbar pattern: one row of labelled `SegmentedControl` groups (micro label above, `text-2xs` uppercase), `FilterSelect`
  / `SearchInput`, right-aligned meta text and actions; wraps on narrow widths.
- Presets with "Custom…" (D2): new `PresetControl` (6.13 #9): segmented presets plus a final "Custom" segment that
  reveals an inline number `Input` (aria-labelled, `min`/`max`/`step` = API bounds, committed on Enter/blur, invalid →
  `Field` error). Used by every numeric toolbar control below.
- Display helpers in `lib/intelligence/format.ts`: `displayId("PIR", 3)` → "PIR-03" (D14), `pirPriority("P1")` →
  `{label: "Critical", tone}` (D15; unknown stored value shown verbatim), `confidenceWord(n)` (C1),
  `originLabel(o)` (D6), `actionLabel(label)` (D20).

### 6.1 Risk Matrix (frame 41332)
- **Toolbar.** PERIOD `PresetControl` 7d | 30d | 60d | 90d (+ Custom 7-90, default 30); COMPARE WITH `FilterSelect`
  "Previous 7 / 14 / 30 / 60 / 90 days" (+ "Custom…" 7-90); MIN RISK SCORE All | ≥25 | ≥50 | ≥75 (+ Custom 0-100);
  right meta "Generated {fmtTime(generated_at)} · {n} cells · {i} industries × {c} countries" (derived).
- **Grid card** (left, `lg:col-span-3` of 5): title "Industry × country", subtitle (score scaled to hottest cell; arrow =
  change vs compare period), `LegendRow` Low / Med / High. `HeatGrid` (new) with sticky text row/column labels (no
  chips; links move to the panel): each cell a `HeatCell variant="tier"` (tier tint from the `risk` scale: < 40 low/success
  tint, 40-69 warning tint, ≥ 70 destructive tint; score number + trend arrow icon with `aria-label` "rising/falling/
  stable"); cells below MIN score render as empty boxes (grid keeps its shape); hottest cell has an outline; selected
  cell has the 2 px ink ring. Keyboard: arrow keys move, Enter/Space select (`useGridRovingKeys`), `aria-label` per
  cell "Finance × Indonesia, score 100, high, rising". Today's `title` tooltip stays as fallback.
- **Selected cell** (right, `HeroPanel`): kicker "SELECTED CELL", "{industry} × {country name}", big score + `Chip
  kind="risk"` + arrow + "hottest cell in the matrix" when it is; rows This period `current_count`, Compare period
  `previous_count`, Change `+56%` (derived; "new" when previous is 0); TOP ACTORS chips (`top_actors`, `EntityChip`);
  HOW THE SCORE WORKS (from code, C9): "3 × unique threat actors + 2 × unique ATT&CK techniques + articles in this
  period, scaled so the hottest cell is 100. Cells need at least 2 articles. The arrow rises when articles grow by more
  than 20 % and falls when they drop by more than 20 %." Links: "Open in Newsroom" (4.1), and the industry and country as
  `EntityChip`s (resolve by name, today's behaviour) replacing the header chip links. Default selection = hottest cell.
- **Highest-risk pairs** (bottom left): top 8 by score, table #, INDUSTRY × COUNTRY, SCORE chip + arrow, ARTICLES "42 /
  27", TOP ACTOR; row click selects the cell. "Export CSV" (`export_data`): client-side CSV of **all** cells (the
  response is complete, not paged) via `lib/csv.ts` (same formula guard as 4.10).
- **Biggest movers** (bottom right): rows "{pair} prev → curr" with a diverging `MeterBar` (+ destructive up, − success
  down), only pairs with `previous_count ≥ 3` (footnote says so), top 8 by absolute change.
- **Behaviour change.** Free numeric inputs → presets + Custom; header EntityChips → text labels (links in the panel).

### 6.2 Source Reliability (frames 16221, 37946 Needs review)
- **Toolbar.** `TabPills` "All sources {entries.total}" | "Needs review {review.items.length}" (second pill only with
  `manage_sources`; the count query only runs then); `SearchInput` "Search source name" (`search`, also matches analyst
  and notes as today); `FilterSelect` Grade (A-F), Origin (all | auto | analyst → `origin` param, 4.4); right "Export
  CSV" secondary (`export_data`, downloads 4.4 with current filters) and "+ Add source" primary (`manage_sources`, opens
  `sr-entry-dialog.tsx`).
- **Sources card** (left): subtitle "{total} sources · sorted by {sort label}"; `SegmentedControl` Table | Grid.
  Table: SOURCE, ADMIRALTY (`Chip kind="grade"`, tint by letter: A/B success, C warning, D/E destructive, F muted),
  RELIABILITY (label from `/api/sr/labels`), KIND (neutral chip `content_kind`), ORIGIN (`originLabel`), ANALYST,
  UPDATED (`fmtCompactAge(last_updated)`). Sortable headers stay (`aria-sort`; default `last_updated desc`). Row click
  opens the entry dialog (edit for `manage_sources`, read-only view otherwise, where Notes are visible); "⋯" `RowMenu`
  Edit / Remove (Remove → `ConfirmDialog` danger). Grid: cards (3 columns on `lg`, 2 below) with name, admiralty chip,
  reliability label, kind chip, origin, analyst, updated, first line of notes; same click and menu. `NumberedPager`
  "Showing 1-25 of 96", 25 per page.
- **Grade distribution** (right): `MeterBar` rows A-F from `GET /api/sr/stats` `by_grade` (count + bar, grade tint);
  clicking a row sets the Grade filter.
- **Reading an Admiralty code** (right): two-column legend from `/api/sr/labels` (reliability A-F, credibility 1-6) +
  footnote "Grades set by an analyst override the automatic grade. 'Needs review' lists auto-graded sources."
- **Needs review view.** Table SOURCE, KIND chip, GRADE "C → B3" (current `admiralty_code` → `suggested_grade` +
  current `credibility_code`), LEADS `lead_count` / `multi_source_stories`, ARTICLES (30 d), OFF-TOPIC `rejected_pct`,
  ARTEFACT %, IOC FP % (destructive text when > 50 %), WHY (`REASON_TEXT` mapping, existing), actions: outline "Apply
  {code}" (existing confirm call) and "⋯ → Edit". Articles (30 d) and Artefact % stay (S1).
- **Re-homed.** Notes column → dialog and Grid card; per-row buttons → row click + RowMenu; "default" badge → ORIGIN.

### 6.3 Early Warning (frame 15766)
- **Toolbar.** LOOKBACK 14d | 30d | 60d | 90d (+ Custom 14-90, default 30); Z-SCORE THRESHOLD 1.5σ | 2σ | 2.5σ | 3σ
  (+ Custom 1.5-4.0 step 0.1, default 2); right meta "{n} anomalies · recent window: last 7 days · updated
  {fmtTime(generated_at)}, refreshes every 15 min" (cache TTL 900 s in `services/spike.py`).
- **Tiles.** Four `StatTile`s in fixed order Threat actors, Industries, Countries, Overall volume: count of entries,
  sub "top: {entity} · z {z}" and "{h} high · {m} medium" (high in `text-destructive-text`).
- **Anomalies card** (left): `SegmentedControl` Grouped | All by z. Grouped: sections in the fixed order actor,
  industry, country, overall ("THREAT ACTOR SPIKES · 4"), each sorted by z. All by z = today's global sort. Row (a
  `SelectableList` item, D5): name (`EntityChip` text style when `entity_id`), "threat actor · {fmtShortDate(date)}",
  `MeterBar variant="baseline"` (fill = `count` vs max count in the group, tick = `baseline_mean`, caption "{count}
  articles that day · baseline {baseline_mean}/day"), severity chip HIGH/MEDIUM, "z {z}σ"; HIGH rows on a faint
  destructive tint. An entity with several spike days shows one row per day (as the API returns).
- **Strongest signal** (right, `HeroPanel`): selected spike (default highest z): name, "{type} · spike on {date}", big
  "{z}σ" + chip, "{count} articles vs {baseline_mean}/day", `BarSeries` of the `daily` block (`dates`, series looked up
  by category + entity name; overall uses `daily.overall`), bars on or after today − 7 in the destructive tone (same
  cut-off as `recent_cutoff`), the rest neutral, a baseline-mean reference line; caption "Daily articles, last {lookback}
  days"; links "Open in Newsroom" (4.1; overall → period 7 only) and "Entity page" (`/intelligence/entities/{entity_id}`,
  hidden when null). `loose-types.ts` `SpikesResponse` gains `daily`.
- **How detection works** (right, static, from code C9): 1 count articles per day for each actor, industry, country and
  overall over the lookback; 2 baseline = every day before the last 7, days without articles count as 0; 3 skip
  entities with fewer than 5 baseline days with articles; 4 z = (day count − baseline mean) / baseline deviation; days
  in the last 7 with z ≥ threshold are anomalies; 5 z ≥ 3 is HIGH, otherwise MEDIUM; at most 20 per group.

### 6.4 PIR (frames 17342, 34382 PIR dialog)
- **URL state.** `?status=active|paused|archived` (default active), `?id=` preselects a PIR (used by Campaigns "Link to
  PIR" and RFI chips).
- **Toolbar.** `TabPills` Active {n} | Paused {n} | Closed {n} (Closed = stored `archived`; counts from the list);
  `FilterSelect` Owner (distinct owners) and Priority (Critical/High/Medium), client-side; right "Export" (`RowMenu`-style
  dropdown, `export_data`: "STIX bundle of active PIRs" → existing `GET /api/stix/pirs`) and "+ New PIR" (`manage_pir`).
- **List** (left): `SelectableList variant="card"`. Card: `displayId` in `font-code`, priority chip, `COVERAGE GAP` chip
  when `is_gap`, "Owner: {owner} · last match {fmtCompactAge(last_match)} ago" ("never"), title, criteria groups as
  labelled text rows (THREAT ACTORS, MALWARE, INDUSTRIES, COUNTRIES, TTPS, KEYWORDS, NEWS TYPES; only filled ones),
  `MeterBar` (coverage relative to the max in view; destructive when gap) + "{coverage_count} articles matched ·
  {recent_coverage} in 14 days" (D16). "⋯" on the card: Edit, Export JSON, Export DOCX, Delete (`ConfirmDialog` danger).
- **Detail** (right): "{PIR-03} coverage" / "Articles matched per week, since {fmtShortDate(since)}" with `BarSeries`
  from `GET /api/pir/{id}/coverage/weekly?weeks=12` (last 2 bars destructive when `is_gap`, else primary); rows Matched
  articles `coverage_count`, Linked RFIs "{linked_rfi_open} open" (link → `/intelligence/rfi?pir={id}`; tooltip lists
  `linked_rfis`), Campaigns matched (`matched_campaigns` titles as links to `/intelligence/campaign-clusters?id=`,
  skeleton while the background query runs, "Only active PIRs are matched to campaigns" for others, "none in the last 30
  days" when empty), Period "{start} - {end}" ("open-ended"); description (markdown, collapsible when long); buttons
  "View articles" (existing `pir-articles-dialog.tsx`, notes kept), "Export JSON" (`/export`), "⋯" Export DOCX, Edit,
  Delete.
- **What a coverage gap means** (static, C9): "A PIR shows COVERAGE GAP when it has matched articles before but none in
  the last 14 days. A PIR without criteria always shows a gap."
- **PIR dialog** (create and edit, rebuilt `pir-form-dialog.tsx`): title "New priority intelligence requirement" /
  "Edit PIR-03", subtitle per mockup; Title (`Field` inline error "Give the PIR a title, for example …", replaces the
  toast); Priority `SegmentedControl` Critical | High | Medium (P1/P2/P3); Owner; Start date / End date (optional)
  (`DateField`); section label "CRITERIA · AN ARTICLE MATCHES WHEN IT HITS ANY CHIP IN EVERY FILLED ROW"; `ChipInput`
  rows Threat actors, Industries, Countries, ATT&CK techniques (suggestions from `GET /api/pir/options` and
  `EntityAutocomplete`), Keywords (free chips); **Advanced** collapsible (D18): Description, Malware and tools, News
  types, Status (edit only); it opens automatically when any of them has a value so existing criteria stay visible.
  Footer: "Preview: {count} articles in the last 90 days would match" (4.2, debounced; "No criteria: every article
  matches ({count})" when `has_criteria` is false; spinner while loading; hidden on error), Cancel (ghost), Create PIR /
  Save (primary, `loading`).

### 6.5 RFI (frames 44165, 34382 RFI dialog)
- **URL state.** `?status=open|in_progress|closed` (default open), `?pir=` (Linked PIR filter), `?id=` (selection).
- **Toolbar.** `TabPills` Open | In progress | Closed with `status_counts` (4.8); `SearchInput` "Search questions";
  `FilterSelect` Linked PIR (all, none, each PIR as "PIR-03 {title}" from the PIR list); right "+ New RFI"
  (`manage_rfi`). The old all-status view is gone as a default; "Closed" lists the rest (every RFI is reachable).
- **Requests card** (left): "Due soonest first"; table QUESTION (2-line clamp), REQUESTER, PIR (`displayId` link or "—"),
  DUE (`fmtShortDate`; destructive when overdue, warning within 2 days), STATUS chip; `LoadMoreFooter` 25 per page.
  Row click selects; keyboard row selection (`Table` selected row + roving keys).
- **Detail** (right): "RFI-12", "Opened {fmtShortDate(created_at)} by {requester} · due {date}, {in n days | n days
  overdue}", status chip, question as `<h2>`, "Linked PIR" chip "PIR-03 {title}" (link to the PIR page), RESPONSE
  `Textarea` (placeholder per mockup), footer `SegmentedControl` Open | In progress | Closed, "Delete" (destructive
  outline → `ConfirmDialog`), "Save response" (primary; `PUT /api/rfi/{id}` with `response` and `status`). "⋯ → Edit"
  (D19) opens the RFI dialog in edit mode with all fields. Without `manage_rfi` the detail is read-only.
- **RFI dialog** (`rfi-form-dialog.tsx`): create = Question (`Textarea`, hint), Requester, Due date (`DateField`),
  Linked PIR (optional `Select` with `items` labels "PIR-03 {title}"); footer Cancel + "Create RFI" (`loading`
  "Creating…"). Edit mode adds Status and Response (today's fields).

### 6.6 MITRE Heatmap (frame 16600)
- **Toolbar.** VIEW `SegmentedControl` Actors | Industries (D9, `view=ta|industry`); PERIOD 30d | 90d | 180d | 365d (+
  Custom 7-365, default 90); ROWS `FilterSelect` "Top 5/10/15/20/30 {actors|industries}" (default 10; API 3-30);
  COLUMNS "Top 8/12/20/30/40 techniques" (default 12; API 5-40); right "Export ATT&CK Navigator layer" (download via
  `navigator-export` with the selected `view/days/top_rows/top_ttps`) and "⋯" "Open in ATT&CK Navigator" (existing
  download + open flow, now sending the same params instead of the hardcoded 15/20).
- **Heatmap card.** "Actor × technique" / "Articles mentioning both · max {max_val}", `LegendRow` 0 → max with five
  swatches. Column headers: TTP id (`font-code`, primary text, link to the entity page when `entity_id`, else plain text)
  + wrapped `ttps[].name`; row labels: name text. `HeatGrid` of `HeatCell variant="scale"` (5 steps by `count /
  max_val`, darkest = `bg-hero` with `text-hero-foreground`, others a capped `primary` tint; 0 = bordered empty cell);
  same keyboard model as 6.1. Default selection = the maximum cell.
- **Drill card** (bottom left, replaces `ttp-drill-dialog.tsx`): "{row} × {TTP id} {name}" / "{n} articles · newest first",
  "Open in Newsroom →" (4.1), article rows (title link, "{source} · {date}", news type chip) from `GET /api/mitre/articles`
  with `NumberedPager` "Page 1 of 5"; collapsible "Countermeasures (D3FEND)" section (D10, existing
  `/api/mitre/d3fend/{technique_id}` call and rendering).
- **ATT&CK data card** (bottom right, moved from Entities, D27): rows per domain from the attack status endpoint used by
  `AttackSyncCard` (label, version, `fmtShortDate(last_sync)`, status dot success / warning with "sync error {date}" and
  the error in a tooltip), "Sync now" (only `manage_intel`; existing POST and polling), footnote "Techniques not in the
  catalog show without a link to their entity page." Visible read-only to everyone with `view_intel`.

### 6.7 Entities list (frame 41886)
- **URL state (unchanged keys).** `tab` (+ new `all`, the default), `q`, `watched`, `suppressed`, `new`; new `id`
  (selection).
- **Toolbar.** `SearchInput` "Search name, alias or ATT&CK ID"; type `SegmentedControl` All | Threat actors | Malware &
  tools | Techniques | CVEs | Campaigns | Sectors | Locations | Victims (C5; scrolls horizontally inside its group below
  1024 px); right `StarToggle`-style toggle button "Watched only" (`aria-pressed`), "⋯" menu: "Include suppressed"
  (checkbox item, `manage_entities`), "Download watchlist Navigator layer" (actors, existing call), and "+ New entity"
  primary (`manage_entities`, existing dialog).
- **List card** (left): "{tab label}" / "{total} entities · sorted by mentions (30 d)" (4.7; C6). Table NAME (`StarToggle` +
  name; `manage_pir` to toggle, read-only star otherwise), ATT&CK ID (`font-code`, primary text), ALIASES (first 2 +
  "+n"), 30 D (bold, trend arrow kept from today), 90 D, LAST SEEN (`fmtCompactAge`), TYPE column only on "All".
  Source column → preview panel; "Suppressed" chip on suppressed rows when shown. Row click selects (does not
  navigate); Enter on a selected row opens the entity page; the name is also a link. `LoadMoreFooter` (cursor). Below
  640 px the existing card list stays (D28).
- **Preview** (right, `HeroPanel`): kicker "{TYPE} · {external_id}", name, "Also known as …", tiles Mentions 30 d / 90 d
  / First seen (`first_seen`, month + year), "AI PROFILE · generated {date}" + `profile_summary` (from `GET
  /api/entities/{id}` for the selection, react-query cached; "No AI profile yet" when null; actors only), source line
  "{source} · first seen {date}", static "ON THE ENTITY PAGE" bullets (Overview, Relationships, Stories, Indicators,
  CVEs, Timeline, ATT&CK, Hunt), "Open entity page →". Default selection = first row.
- **Re-homed.** `AttackSyncCard` → MITRE (6.6); the Techniques tab shows a one-line `Notice` "ATT&CK sync status moved to
  MITRE heatmap" with a link.

### 6.8 Entity detail (frame 37115)
- **Header** (replaces `EntityHero` burgundy band; `heroButtonClass` removed from `entity-actions-menu.tsx`): kicker
  "ENTITIES › {TYPE} · {external_id}" (the "Entities" part links back to the list tab, replacing the breadcrumb), `<h1>`
  name + `StarToggle` (watched), "Suppressed" chip when suppressed, "Also known as …" (+n disclosure kept), meta line
  "Sources: {source} · first seen {date}"; right: "Watching" / "Watch" secondary toggle (`manage_pir`) and "Actions ▾"
  (`EntityActionsMenu`, labels per mockup: Edit name and description, Manage aliases, Split aliases, Merge into another
  entity…, Suppress from feeds (destructive); permissions unchanged).
- **Tiles.** Five `StatTile`s: Mentions 30 days, Stories, Indicators, CVEs, Last seen (sources as today).
- **Tabs** (`TabPills`, URL `tab` as today): Overview, Relationships {n}, Stories {n}, Indicators {n}, CVEs {n},
  Timeline, ATT&CK, Hunt (D26, `view_ioc`, existing `HuntPanel`).
- **Overview.** Left "AI profile" card (actors): "Generated {date} from {profile_article_count} recent articles" +
  `REVIEW BEFORE SHARING` warning chip, `profile_summary` paragraph labelled "AI summary", the existing key/value table
  (Actor type, Motivation, Sponsor, Targets: sectors, Targets: geographies, Malware, Tools), "Generate profile" /
  "Regenerate" button in the card header (`manage_intel`, D26), collapsible "Description" section (markdown, existing).
  Non-actors: the card is "About" with the description only. Right: "Mentions by month" `BarSeries` from `/timeline`
  (last two bars primary, rest neutral); "Relationships · {n} links · 3 shown" rows (kind chip, target "{name} · {type}",
  `confidenceWord`) + co-mention sentence from `co_mentions`, "See all" → Relationships tab; actors: `MindmapWidget`
  card below (D26).
- `app/(app)/intelligence/entities/[id]` renders without the Intelligence header and pills (6.0).

### 6.9 IOC Management (frames 18079, 37946 Allowlist / FP analytics, 34382 Remove)
- **View switch.** `TabPills` Indicators {stats.total} | Allowlist {entries.length} | FP analytics, as page-level views
  (React state + `?view=`), replacing the three stacked sections of `ioc-management-view.tsx`.
- **Indicators toolbar.** `SearchInput` "Search value" (`search`); `FilterSelect` Type (all + 7 types), State (active
  default, expired, revoked, allowlisted, "All visible", "All incl. suppressed" → `state` unset + `include_suppressed`),
  Action (all + 4 values → `actionability`), Sort (last seen | confidence); right "Export CSV" (`export_data`, 4.5 with
  the current filters; truncated toast).
- **Type tiles.** `StatTile` per `stats.by_type` entry (all types present, not just six), clickable (`aria-pressed`)
  to set or clear the Type filter.
- **Indicators card** (left): "{total} {state} · page {p} of {n}"; table VALUE (`font-code`, truncated with title), TYPE
  chip, CONF. (`confidence_score`), ACTIONABILITY (`actionability_score` + small `MeterBar`, "—" when null), ACTION chip
  (D20: BLOCK destructive, INVESTIGATE warning, MONITOR info, ARCHIVE neutral), SEEN (`seen_count`), FEEDBACK "{tp} TP ·
  {fp} FP"; State and TLP shown as chips inside VALUE's second line when not active / not default. Row click selects;
  keyboard row selection. `NumberedPager` with a "Rows 25 | 50 | 100" `FilterSelect` (page size kept, default 50).
  Footnote when `state` hides auto-suppressed rows.
- **Detail panel** (right; replaces `ioc-detail-dialog.tsx`, all its content kept, D23): value + ACTION chip, "{type} ·
  first seen {date} · last seen {age} ago", state/suppression line (`suppression_reason`, revoked by/at),
  `recommended_action` sentence; ENRICHMENT rows per provider (name, verdict chip, score; "100 / 100", "14 / 94
  engines", "6 pulses" from known `raw` keys with a fallback to `score`), provider tags (first 8) and "updated
  {enrichment.updated_at}" as in today's dialog; THREAT
  ACTORS chips + add/remove editor (`manage_ioc`); SOURCES · n (source name, context snippet, article link →
  `article-by-id-dialog`); MARKING TLP / PAP selects (`manage_ioc`, `PATCH /marking`); TAGS. Footer (`manage_ioc`): "TP /
  restore" (`feedback tp`), "FP: remove" (opens the Remove dialog), "Allowlist" (`POST /allowlist`, type derived: ip →
  `ip`, domain/url → `url_domain`, email → `email_domain`; disabled with tooltip for hashes), "⋯ → Delete IOC" (hard
  delete, `ConfirmDialog` danger "This deletes the indicator and its history. It cannot be undone."). After an FP verdict
  a `Notice` warning shows `source_fp_warning` when returned.
- **Remove dialog** (D21): `ConfirmDialog` with note: title "Remove {value} from feeds?", body "It stops appearing in STIX
  and CSV exports for every client. Analysts can restore it with TP.", optional Note (`Textarea`, max 2000), Cancel
  (ghost) + "Remove from feeds" (destructive outline) → `POST /{id}/feedback {verdict: "fp", note}`.
- **Allowlist view.** Inline form Type select, Value input, Note input (4.6), "Add to allowlist" (`manage_ioc`); table
  TYPE, VALUE (`font-code`), NOTE, ADDED "{added_by} · {date}", "Remove" text button (`ConfirmDialog`).
- **FP analytics view.** "FP rate by IOC type" `MeterBar` rows (`fp_by_type`); "Suggested for allowlist" table IOC VALUE,
  TYPE, VERDICTS "{tp_count} TP · {fp_count} FP", ALLOWLIST AS, with "Apply all suggestions" (`manage_ioc`); kept below:
  "FP rate by source" table (`fp_by_source`) and "FP verdicts per day, 30 days" `BarSeries` (`fp_trend`).

### 6.10 Campaign Clusters (frames 17074, 37946 Clusters (Simple))
- **URL state.** `?view=campaigns|simple`, `?id=` (selected campaign).
- **Toolbar.** `TabPills` Campaigns {total} | Clusters (Simple); Campaigns: DAYS 7d | 30d | 90d (+ Custom 1-90, default
  7 as the API), MIN SIZE `FilterSelect` 2 / 3 / 5 / 10 articles (+ Custom 2-50, default 3); right meta "{total}
  campaigns · {campaign_links.length} links between them".
- **Campaign list** (left): "Campaigns" / "Sorted by {sort}" with `FilterSelect` Sort (severity, size, velocity, last
  seen; existing `sortCampaigns`). `SelectableList variant="card"`: chips severity "{LABEL} {score}", VELOCITY ALERT, NEW
  {n} IOCs (when `new_iocs_24h`), trend arrow; "{size} articles · {days_active} days active"; title (`summary_title`,
  fallback `cluster_id`); actor chips, industries, countries "ID · SG · MY"; velocity "{label} · {rate}/day" with dot.
- **Detail** (right): title, "First seen {date} · last seen {date} · {n} new IOCs in 24 h"; KILL CHAIN restyled
  `kill-chain-view.tsx` ("{completeness_label}, {covered} of 7 phases", 7 tiles with "n TTP"); DIAMOND MODEL restyled
  `diamond-model-view.tsx` (counts like "4 IPs · 2 domains"); PRIORITIZED CVEs (score, CVE id, chips critical patch /
  KEV / PoC / in tech stack); footer "Matches PIR-03 '{title}'" + "Link to PIR →" (`/intelligence/pir?id=`) and "+{n}
  more PIRs" listing all `matched_pirs` (the existing `cluster-pir-dialog.tsx` keeps the full view). Collapsible
  sections below, in this order (D13): Severity breakdown, Trend (existing `/api/clusters/{id}/trends` chart),
  Member articles (opens `article-by-id-dialog`), IOCs, Related campaigns (click selects that campaign), Mind map
  (`MindmapWidget`), Geopolitical context (existing `GeopoliticalPanel`, labelled "all campaigns, {days} days"), and a
  "Hunt pack" button in the detail header (existing JSON download).
- **Clusters (Simple).** DAYS 7 | 14 | 30 (+ Custom 7-90); "Similarity threshold" number `Input` (0.20-0.70, step 0.05,
  default 0.35, hint "Higher means tighter clusters.", D11); the two existing toggles as `Switch`es; auto-load on mount
  and on change (500 ms debounce), "Generate" button removed (D12), busy `Notice` "Clustering may take a few seconds" on
  the first load; rows: `cluster_name`, sources "{3 names} +n", chip "{article_count} articles"; the spike lookup stays
  as today.

### 6.11 Dialogs
PIR (6.4), RFI (6.5), Remove IOC (6.9). All use `Dialog` with `DialogDescription` and the close "×"; Cancel is a ghost
button; primary buttons use `loading`. Errors from the API show inline (`Field` error or `Notice`) and keep the input.

### 6.12 States
Every card: `StatePanel` loading (skeleton matching the card), empty (per view copy, e.g. "No anomalies above 2σ in the
last 30 days" with a hint to lower the threshold), error with Retry, no-access (e.g. Needs review without
`manage_sources` is not rendered at all; export buttons hidden without `export_data`; write actions hidden or disabled
with a tooltip as today).

### 6.13 New primitives (existing ones reused as they are)
Already exist (reuse): `MasterDetail`, `SelectableList`, `StatTile`, `Field`, `FilterSelect`, `SearchInput`, `RowMenu`,
`SegmentedControl`, `TabPills` (with counts), `NumberedPager`, `LoadMoreFooter`, `Notice`, `Switch`, `Chip` (`risk`,
`grade`, `severity`, `status`), `Button variant="destructive"` (= danger outline), `ConfirmDialog`
(`components/confirm-dialog.tsx`), `Table` selected row, `use-roving-keys.ts`, Chart.js wrappers in
`components/dashboard/charts.tsx`. New, in `components/ui/` unless noted:
1. **HeroPanel** (D3): `bg-hero` surface, `text-hero-foreground`, `text-hero-muted`, `text-hero-eyebrow` kicker slot,
   title, body, footer links (`text-hero-accent`, focus ring offset on `ring-offset-hero`); used by 6.1, 6.3, 6.7.
2. **MeterBar**: horizontal bar with `value`/`max`, tone, optional baseline tick (`variant="baseline"`), diverging
   variant (centre zero), label slot, `role="meter"` with `aria-valuenow/min/max` and a text alternative.
3. **BarSeries**: small Chart.js bar chart (same registration as `charts.tsx`) with `labels`, `values`,
   `highlight: (index) => boolean` or `highlightLast: n`, optional reference line (plugin-free: drawn as a line dataset),
   tokens read from CSS variables, hidden data table for screen readers; replaces `entity-timeline-chart.tsx` internals.
4. **HeatCell** + **HeatGrid**: `HeatCell variant="tier" | "scale"`, empty, selected, outlined; `HeatGrid` lays out sticky
   headers and wires **`useGridRovingKeys`** (new hook beside `use-roving-keys.ts`: 2-D arrows, Home/End, Enter/Space).
5. **SelectableList `variant="card"`**: extension of the existing list: full 1 px border, selected = 2 px ink border
   + `bg-surface` (rich cards for PIR and Campaigns).
6. **ChipInput**: tags with "×" and an inline text input; suggestions from a passed async source (wraps
   `EntityAutocomplete` behaviour), Enter/comma adds, Backspace removes the last chip, `aria-label`, chip list announced.
   Replaces `multi-select-field.tsx` in the PIR dialog.
7. **DateField**: shows the value as `fmtShortDate` with year ("1 Nov 2026") on a button that calls `showPicker()` on a
   visually hidden native `<input type="date">` (falls back to focusing the input); clear button for optional dates;
   values stay `YYYY-MM-DD` local (`parseLocalDate`).
8. **ConfirmDialog extension** (`components/confirm-dialog.tsx`): optional `note` (`{label, placeholder, maxLength}`,
   value passed to `onConfirm(note)`), `tone="danger"` → confirm button `variant="destructive"`, `confirmLoading`.
9. **PresetControl** (6.0): `SegmentedControl` + "Custom" segment + bounded number `Input`.
10. **StarToggle**: icon button (`aria-pressed`, `aria-label` "Watch {name}" / "Stop watching {name}"), filled star in
    primary when on, 24 px target.
11. **LegendRow**: swatches with labels (heat scale or tiers), `aria-hidden` swatches with text labels.
12. **StatTile `onSelect`/`selected`**: renders as `<button aria-pressed>` when given (IOC type tiles).
13. Domain: `IntelligencePageHeader`, `lib/intelligence/{routes,format}.ts`, `lib/newsroom/links.ts`, `lib/csv.ts`.

## 7. Out of scope
- Mockup sample numbers and copy that are illustrative ("143 articles", "0.72", "Acme Bank", masthead badges).
- A 4th PIR priority "Low" or any PIR priority/status migration (D15).
- A user-selectable sort on the Entities page (C6 fixes it to 30-day mentions), changing the cluster threshold
  range (D11), the spike cache or algorithm.
- Server-side caching of the campaign pipeline, and client scoping of IOCs (C2).
- Mobile layouts beyond the 1024 px collapse and the kept Entities card fallback (D28).
- `/intelligence/entities/resolve` (unchanged), TA Room, Exec, X Intel and other pages.

## 8. Verification
- **Backend tests.** The unit and integration tests named in 4.1-4.10 (Docker for integration):
  `uv run pytest tests/integration -k "pir or rfi or source_reliability or sr_export or ioc or fp_analytics or entities
  or ta_profile or articles_combined"`, then the fast suite `uv run pytest tests/unit tests/contract packages`
  (deselect the two known Mac-only failures). Cross-cutting checks: client A cannot see client B's RFIs in `linked_rfis`
  or `status_counts`; exports return 403 without `export_data` and write an audit row; `test_migrations_match_models.py`
  still passes (no revision).
- **Static.** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src
  packages/cti-scraper/src` (covers the `pir` and `indicator` repository changes).
- **Contract.** `uv run python tools/export_openapi.py`; `cd apps/web && pnpm run gen:api`; commit both; update
  `loose-types.ts` (`SpikesResponse.daily`, IOC list/FP analytics shapes, `tp_count`); review and `--snapshot-update`
  the four syrupy snapshots in section 5.
- **Web.** `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit`; `pnpm build`.
- **Visual (local).** Isolated compose project `qacve` (not the user's `deploy-postgres-1`), API via uvicorn, web via
  `pnpm dev`, synthetic data script in the session scratchpad (spikes in all four groups, a full risk matrix, PIRs in all
  statuses with and without gaps and linked RFIs, RFIs in all statuses and overdue, IOCs of every type, state and
  action incl. suppressed and revoked, allowlist and FP history, campaigns with links and matched PIRs, entities of every
  type incl. suppressed, an actor with an old and a regenerated profile, LLM stubbed). Screenshots of every view, dialog
  and state at 1440 and 1000 px, light and dark, compared with each light frame in section 1 and its dark variant.
  Checks: keyboard pass (pills, presets incl. Custom, heat grids, selectable lists and tables, row menus, dialogs, chip
  input, date field), contrast of heat cells, tier tiles and `HeroPanel` links in both themes, no `WIB`/`UTC` literal in
  Intelligence views, every "Open in Newsroom" lands on a sheet whose count matches the source number, every pre-2b
  feature listed in the inventory's drop-risk sections is reachable (checklist in the PR).
- **Delivery.** Commit per backend item and per view; merge into `origin/Dev` (standing approval) and check on dev
  172.25.1.77 read-only with real data; regenerating one actor profile on dev (one LLM call) only with the user's go.

## 9. Risks
- **Large single spec** (10 backend items, 12 views). Mitigation: backend first, contract regenerated once, views in the
  order shell + primitives, Early Warning, Risk Matrix, MITRE, SR, PIR + RFI, IOC, Campaigns, Entities, Entity detail.
- **Campaign match cost** on the PIR page (4.3): seconds per background request and double coverage counting;
  alternatives are flagged for the controller.
- **Exports** put every TLP marking into a file (IOC) and can be large (50 000-row cap, truncation header); CSV formula
  injection is guarded only in the new helper.
- **Profile summaries** are empty until regenerated and remain model text; grounding scrubs only unknown CVE ids, not
  invented names, hence the review chip.
- **Preset controls** change the default MITRE grid (15 × 20 → 10 × 12) and replace free inputs; Custom keeps every
  previous value reachable.
- **Removing dialogs** (IOC detail, TTP drill) changes deep-link and focus behaviour; selection lives in the URL where
  listed (`id`), focus returns to the selected row after dialogs.
- **Entities sort** (C6) is computed per request over the 30-day window; entities move between pages while new
  articles arrive, and a slow aggregate would slow the first paint of the Entities page (timing checked in 4.7).
- **RFI default tab** changes from all statuses to Open; status counts make the other tabs visible at a glance.
- **Newsroom URL params** add a second way into `ArticleListSheet`; the sheet scope must not combine with the masthead
  filters in a way that changes the count (the new source carries its own country and date, independent of the
  masthead state).
- **Heat and tier tints** in dark mode: cells cap alpha; verified on the dense pages (Risk Matrix, IOC) per
  `apps/web/CLAUDE.md`.
