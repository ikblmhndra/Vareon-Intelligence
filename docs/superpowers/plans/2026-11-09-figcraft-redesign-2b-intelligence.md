# FigCraft redesign 2b: Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the full FigCraft Intelligence mockup (Risk Matrix, Source Reliability, Early Warning, PIR, RFI, MITRE heatmap, Entities, IOC management, Campaign clusters, the entity detail page and their dialogs) with every pre-2b feature still reachable and the missing data added, inside the 0.8.16 release.

**Architecture:** Backend first, no migration: Tasks 1-10 add endpoints, query params and response fields (spec 4.1-4.10), each with its own pytest cycle; Task 11 regenerates the API contract once, updates `loose-types.ts` and the four syrupy snapshots. Then the web: shell and primitives (12-13), the Newsroom URL contract (14), one task per view in the spec order (15-25), docs (26) and the final verification (27).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), pytest + testcontainers + syrupy; Next.js 16 App Router, React 19, TanStack Query, Tailwind v4, shadcn on Base UI (`@base-ui/react`), `openapi-fetch` (`api` from `@/lib/api/client`), Chart.js (registration as in `components/dashboard/charts.tsx`), `lucide-react`, `sonner`.

**Spec:** `docs/superpowers/specs/2026-11-09-figcraft-redesign-2b-intelligence-design.md` (binding; section numbers below refer to it). The gap inventory in the session scratchpad lists the pre-2b features per view; where it differs from the spec, the spec wins.

## Global Constraints

- No migration: Alembic head stays `b7d41e9a2c63`; `tests/integration/test_migrations_match_models.py` passes after every backend task. No new `Settings` field; `.env.example` and `.env.prod.template` unchanged.
- Release stays 0.8.16 (`## [0.8.16] - 2026-11-08`), one PR, no extra version bump; `uv.lock` stays `revision = 3`.
- Tenant: `cid = effective_client_id(user, x_client_id)`. Router permissions unchanged (`/api/pir`, `/api/rfi`, `/api/sr`, `/api/intelligence`, `/api/mitre` = `view_intel`; `/api/iocs` = `view_ioc`; `/api/entities` = `view_ta`). Every new export requires `export_data` and writes an audit row (`AsyncAuditLogRepo.write`, then `session.commit()`).
- Comments and docstrings Indonesian, matching the surrounding file, explaining *why*. Docs under `docs/` English; `CHANGELOG.md` Indonesian.
- Commits: English conventional (`feat(api): ...`, `feat(web): ...`), body ends with a blank line + `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage only your own files.
- Python checks: `uv run ruff check . && uv run ruff format --check .` (`ruff format` also checks Python code blocks in Markdown); `uv run mypy packages/cti-core/src packages/cti-scraper/src` (covers the `pir`, `rfi`, `indicator`, `ioc_reference`, `source_reliability` repository changes).
- Fast suite: `uv run pytest tests/unit tests/contract packages --deselect tests/contract/test_golden.py::test_golden_trendmicro`; integration needs Docker: `uv run pytest tests/integration -k "<pattern>"`.
- Contract: regenerated ONCE in Task 11 (`uv run python tools/export_openapi.py`; `cd apps/web && pnpm run gen:api`; `loose-types.ts` for untyped dicts). Backend Tasks 1-10 do not run the export and do not run the four snapshot tests (`test_pir_router_snapshot.py`, `test_rfi_router_snapshot.py`, `test_source_reliability_router_snapshot.py`, `test_iocs_router_snapshot.py`); Task 11 reviews and updates them.
- Web (`apps/web`): read `apps/web/AGENTS.md` and `apps/web/CLAUDE.md` first. Base UI, not Radix: `render={<X/>}` (never `asChild`), `SelectItem` children a single string, `items` on `Select` for sentinel values, `DropdownMenuLabel` inside `DropdownMenuGroup`.
- Theme tokens only (no hex, `rgb()`, raw palette classes); text on tints `text-X-text`; heat tints cap alpha instead of flipping text colour; no `backdrop-blur`/`backdrop-filter`; minimum text 11 px (`text-2xs`); IDs, IOC values, TTP/CVE ids in `font-code`.
- Focus ring: `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background` (`ring-offset-hero` inside `HeroPanel`). Two-column layouts collapse below 1024 px (`lg:`). Search inputs without a visible label and icon-only buttons have `aria-label`.
- Dates only through `lib/format.ts` (browser timezone): `fmtShortDate`, `fmtDateTime`, `fmtTime`, `fmtCompactAge` (+ " ago" where the mockup says "ago"), `parseLocalDate`, `daysUntil`; no `WIB`/`UTC` literal in Intelligence views. Loading, empty, error and no-access states use `StatePanel`.
- No web test runner; do not add one. Web verification per task, from `apps/web` after `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"`: `pnpm lint`, `pnpm exec next typegen && pnpm exec tsc --noEmit`, `pnpm build`, all exit 0, plus the task's behaviour checklist in `pnpm dev`.
- Do not push, merge or switch branches (`claude/figcraft-design-data`). No subagent re-delegation inside a task.

## Review Focus

1. IOC export rows that tie on the sort key across a keyset batch boundary must be neither duplicated nor skipped (Task 6, `test_export_batches_ties_complete`, batch size monkeypatched to 2, five rows with one `last_seen_at`).
2. Entities cursors of the other shape in both directions, and ties on the 30-day count between non-ASCII names (Task 8, `test_list_sort_name_rejects_mentions_cursor`, `test_list_sort_mentions_non_ascii_tie`: "Ärger" vs "apt" with equal counts pages exactly like `ORDER BY` with collation C).
3. Linked RFIs with a legacy status outside `open|in_progress|closed` and with null due dates: they sort after `closed`, never count in `linked_rfi_open`, and stay client-scoped (Task 4, `test_linked_rfis_unknown_status_sorts_last`).
4. CSV cells with commas, double quotes, newlines, integers, non-ASCII text and a formula behind a leading space (Task 2, `test_csv_quoting_and_types`: `" =1+1"` kept as is, `42` stays `42`, BOM once at the start).
5. Blank or duplicate PIR criteria chips (`keywords: [" "]`): ChipInput never sends them, and the preview still equals coverage for what is stored (Task 3, `test_preview_matches_coverage_with_blank_keyword`; Task 13 ChipInput checklist).

---

### Task 1: Newsroom combined-filter regression test (4.1, backend part)

**Files:**
- Create: `tests/integration/test_articles_combined_filters.py`
- Read only: `apps/api/src/cti_api/routers/articles.py` (`list_articles`), `packages/cti-core/src/cti_core/db/repositories/article.py` (`list_filtered`, `_apply_list_filters`), `apps/api/src/cti_api/services/risk_matrix.py`

**Interfaces:**
- Consumes: `GET /api/articles?threat_actor=&industry=&ttp=&country=&posted_on_start=` (unchanged contract).
- Produces: a pinned contract for Tasks 14-17 (`newsroomHref` relies on it).

- [ ] **Step 1: Write the tests:** `test_actor_and_ttp_and_together` (three articles: actor+ttp, actor only, ttp only → only the first), `test_industry_and_country_and_together`, `test_actor_alias_name_matches` (`threat_actor=wicked panda` returns the APT41 article through `entity_ids_named`), `test_total_equals_risk_matrix_current_count` (seed two articles for (Finance, ID) in the window plus one with `posted_on` null; `GET /api/articles?industry=Finance&country=ID&posted_on_start={today-30}` `total` equals the risk-matrix cell `current_count` for `days=30`).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_articles_combined_filters.py -q` — Expected: PASS (pins existing behaviour, C3). A failure is a real bug: stop and report, do not change the filter code here.
- [ ] **Step 3: Commit** `test(api): pin combined Newsroom filters behind the Intelligence deep links`

### Task 2: Shared CSV helper (4.10)

**Files:**
- Create: `apps/api/src/cti_api/services/csv_export.py`, `tests/unit/test_csv_export.py`

**Interfaces:**
- Produces: `safe_cell(value: object) -> str | int | float` (`None` → `""`, `datetime`/`date` → ISO, `list`/`tuple` → `";"`-joined `safe_cell` strings, `bool` → `"true"`/`"false"`, numbers unchanged, any string starting with `=`, `+`, `-`, `@`, `\t` or `\r` prefixed with `'`); `csv_response(header: Sequence[str], rows: Iterable[Sequence[object]], filename: str, *, headers: Mapping[str, str] | None = None) -> Response` (`media_type="text/csv; charset=utf-8"`, body `"﻿"` + `csv.writer(lineterminator="\r\n")`, `Content-Disposition: attachment; filename="{filename}"`, extra headers merged; used by Tasks 5 and 6). The v2 `_csv` in `routers/v2_indicators.py` is left unchanged.

- [ ] **Step 1: Write failing tests:** `test_safe_cell_formula_prefixes` (each of `"=1"`, `"+1"`, `"-1"`, `"@x"`, `"\tx"`, `"\rx"` gets a leading `'`), `test_safe_cell_types` (`None` → `""`, `datetime(2026, 11, 9, 1, 2, tzinfo=UTC)` → `"2026-11-09T01:02:00+00:00"`, `["a", "b"]` → `"a;b"`, `["=x"]` → `"'=x"`), `test_csv_response_headers` (filename in `Content-Disposition`, body starts with BOM, rows end with `\r\n`), `test_csv_quoting_and_types` (Review Focus 4).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_csv_export.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** per Interfaces; module docstring says why the guard exists and why v2 stays untouched (machine contract).
- [ ] **Step 4: Run** the Step 2 command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): shared CSV export helper with formula-injection guard`

### Task 3: PIR preview match count (4.2)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/pir.py` (public `criteria_filters`, `has_criteria`; old `_criteria_filters`, `_has_criteria` kept as aliases), `apps/api/src/cti_api/schemas/pir.py`, `apps/api/src/cti_api/routers/pir.py` (new route next to `/options`)
- Create: `tests/unit/test_pir_preview_body.py`, `tests/integration/test_pir_preview_api.py`

**Interfaces:**
- Produces: `criteria_filters(criteria: dict[str, Any]) -> dict[str, Any]`, `has_criteria(criteria: dict[str, Any]) -> bool`.
- Produces schemas: `PIRPreviewCriteria(PIRCriteria)` with `model_config = ConfigDict(extra="forbid")` (the shared `PIRCriteria` stays permissive so `POST`/`PUT /api/pir` keep accepting old payloads); `PIRPreviewIn(criteria: PIRPreviewCriteria, days: int = Field(90, ge=1, le=365))`, also `extra="forbid"`; `PIRPreviewOut(count: int, days: int, since: datetime.date, has_criteria: bool)`.
- Produces endpoint: `POST /api/pir/preview` (`require_permission("manage_pir")`, response `PIRPreviewOut`): `since = date.today() - timedelta(days=body.days)`; `_, count = await AsyncArticleRepo(session).list_filtered(page=1, page_size=1, posted_on_start=since, **criteria_filters(body.criteria.model_dump()))`; no client filter, no write, no audit; PIR start/end dates ignored.

- [ ] **Step 1: Write failing tests.** Unit: `test_days_bounds` (`days=0` and `days=366` raise `ValidationError`, `days=365` ok), `test_unknown_criteria_key_rejected` (`{"criteria": {"sectors": ["x"]}}` raises). Integration: `test_preview_equals_coverage_total` (PIR with the same criteria and `start_date = since`; `count == compute_coverage(...)[0]`), `test_empty_criteria_has_criteria_false` (`has_criteria is False`, `count` = every article in the window), `test_preview_requires_manage_pir` (analyst without `manage_pir` → 403), `test_preview_422_body` (`days=0` → 422), `test_preview_matches_coverage_with_blank_keyword` (Review Focus 5).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_pir_preview_body.py tests/integration/test_pir_preview_api.py tests/integration/test_pir_query.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; existing callers keep the underscore names (aliases), `compute_coverage` and `weekly_coverage` call the public names.
- [ ] **Step 4: Run** the Step 2 command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): PIR criteria preview count`

### Task 4: `PIROut` linked RFIs and matched campaigns (4.3, D17)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/rfi.py` (`AsyncRFIRepo.list_by_pirs`), `apps/api/src/cti_api/schemas/pir.py`, `apps/api/src/cti_api/routers/pir.py` (`_to_out`, `get_pirs`, `post_pir`, `put_pir`)
- Test: `tests/integration/test_pir_query.py`, create `tests/integration/test_pir_campaign_matches.py`

**Interfaces:**
- Produces repo: `AsyncRFIRepo.list_by_pirs(client_id: str, pir_ids: Sequence[int]) -> dict[int, list[RFIRequest]]` (one `SELECT ... WHERE client_id = :cid AND linked_pir_id IN (...)`, ordered by `case` `open`=0, `in_progress`=1, `closed`=2, else 3, then `due_date NULLS LAST`, then `id`; at most 20 per PIR, cut in Python); `_LINKED_RFI_CAP = 20`.
- Produces schemas: `PIRLinkedRFI(id: int, status: str, question: str, due_date: str | None)` (`question` = first 120 chars); `PIRMatchedCampaign(cluster_id: str, title: str, size: int, severity_label: str, last_seen: str | None)` (`title` = `summary_title` or `cluster_id`); `PIROut.linked_rfis: list[PIRLinkedRFI] = []`, `linked_rfi_open: int = 0` (status `open` or `in_progress`), `matched_campaigns: list[PIRMatchedCampaign] | None = None`.
- Produces endpoint params: `GET /api/pir?include_campaigns=false&campaign_days=30` (`campaign_days: int = Query(30, ge=7, le=90)`). With `include_campaigns`: one `campaign_service.get_recent_campaigns(session, days=campaign_days, client_id=cid, min_size=3)`, invert `matched_pirs[*].id` to `{pir_id: [campaign...]}`, sorted by `severity_score` desc, at most 5 per PIR; every listed PIR gets a list (`[]` when none, incl. paused and archived). No audit row. `POST`/`PUT` return `linked_rfis` filled and `matched_campaigns=None`.
- Flag kept for the controller (spec 4.3): if alternative (a) or (b) is chosen before this task starts, replace the `include_campaigns` part only; `linked_rfis` stays.

- [ ] **Step 1: Write failing tests.** `test_pir_query.py`: `test_linked_rfis_open_count` (open + in_progress + closed → `linked_rfi_open == 2`, order open, in_progress, closed), `test_linked_rfis_other_client_excluded` (acme RFI pointing at a default PIR is not listed), `test_linked_rfis_cap_20` (25 RFIs → 20), `test_linked_rfis_order_due_nulls_last`, `test_linked_rfis_unknown_status_sorts_last` (Review Focus 3). `test_pir_campaign_matches.py` (monkeypatch `cti_api.services.campaign.get_recent_campaigns`): `test_campaigns_inverted_per_pir` (two campaigns matching PIR 1, one PIR 2; severity order; cap 5 with 7 matches), `test_paused_pir_gets_empty_list`, `test_campaigns_null_when_not_requested`, `test_campaign_days_bounds` (`6` and `91` → 422), `test_put_returns_null_campaigns`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_pir_query.py tests/integration/test_pir_campaign_matches.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; `AsyncPIRRepo.list_pirs` stays unchanged; the router joins the RFI map; docstring notes that `linked_pir_id` is an FK without a client check (hence the client filter) and that coverage is computed twice when the page fetches both variants.
- [ ] **Step 4: Run** the Step 2 command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): linked RFIs and opt-in matched campaigns on PIRs`

### Task 5: Source reliability origin filter and CSV export (4.4, D6, D8)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/source_reliability.py` (`AsyncSourceReliabilityRepo.list_entries`), `apps/api/src/cti_api/routers/source_reliability.py`
- Test: `tests/integration/test_source_reliability_query.py`, create `tests/integration/test_sr_export_api.py`

**Interfaces:**
- Consumes: `csv_response`, `safe_cell` (Task 2).
- Produces: `list_entries(..., origin: str | None = None)` (`WHERE origin = :origin`; ordering gains `SourceReliabilityEntry.id` as tie-breaker in the same direction as the sort); `GET /api/sr/entries?origin=default|analyst` (`origin: Literal["default", "analyst"] | None = None`); `GET /api/sr/entries/export` (`require_permission("export_data")`, params `search`, `grade`, `origin`, `sort_by`, `sort_dir`; declared before `/entries/{entry_id}`), `_EXPORT_CAP = 5000`, filename `source-reliability-YYYYMMDD.csv`, columns `source_name, admiralty_code, reliability_grade, reliability_label, credibility_code, credibility_label, content_kind, origin, analyst_name, notes, added_date, last_updated` (labels from `RELIABILITY_LABELS` / `CREDIBILITY_LABELS`); audit `export_source_reliability` with `detail={"filters": {...}, "rows": n}`.

- [ ] **Step 1: Write failing tests.** `test_source_reliability_query.py`: `test_origin_filter` (`origin="analyst"` returns only analyst rows), `test_id_tiebreaker_stable_pages` (five rows with one `last_updated`, `sort_by=last_updated&sort_dir=desc`, `page_size=2` → three pages disjoint and complete). `test_sr_export_api.py`: `test_export_requires_export_data` (403), `test_export_honours_filters` (grade + origin + search), `test_export_header_row` (first line equals the column list), `test_export_neutralises_formula_note` (note `=HYPERLINK(...)` → `'=HYPERLINK(...)`), `test_export_writes_audit` (action `export_source_reliability`, `rows` matches), `test_export_path_not_parsed_as_entry_id`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_source_reliability_query.py tests/integration/test_sr_export_api.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the Step 2 command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): source reliability origin filter and CSV export`

### Task 6: IOC CSV export and stable list order (4.5, D22)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/indicator.py` (`AsyncIndicatorRepo.list_filtered` split, new `iter_export`), `apps/api/src/cti_api/routers/iocs.py` (new route before `/{ioc_type}/{value:path}`)
- Test: `tests/integration/test_ioc_query.py`, create `tests/integration/test_ioc_export_api.py`

**Interfaces:**
- Consumes: `csv_response`, `safe_cell` (Task 2).
- Produces repo: `_filtered_stmt(self, *, ioc_type, search, tags, actionability, include_suppressed, state, include_revoked) -> Select[tuple[Indicator]]` (filters only, same rules as today); `list_filtered` keeps its signature and orders by `order_col.desc(), Indicator.id.desc()`; `iter_export(self, *, sort_by: str | None, batch_size: int = _EXPORT_BATCH, limit: int, **filters) -> AsyncIterator[list[Indicator]]` (keyset on `(order_col, Indicator.id)` descending, `_EXPORT_BATCH = 2000`).
- Produces endpoint: `GET /api/iocs/export` (router `view_ioc` + `require_permission("export_data")`; params `ioc_type`, `search`, `sort_by`, `actionability`, `include_suppressed`, `state`; `search` through `canonical(ioc_type or "url", search)` exactly as `list_iocs`); `_EXPORT_CAP = 50_000` (reads `cap + 1` to detect truncation; header `X-Export-Truncated: true` when hit); filename `iocs-YYYYMMDD.csv`; columns `id, type, value, state, tlp, pap, confidence_score, actionability_score, actionability_label, recommended_action, seen_count, first_seen, last_seen, tp_count, fp_count, threat_actors, tags, auto_suppressed, suppression_reason, revoked_at` (values canonical, not defanged; lists `;`-joined); audit `export_iocs` with filters and row count. One `Response`, no streaming.

- [ ] **Step 1: Write failing tests.** `test_ioc_query.py::test_list_stable_order_ties` (five IOCs with one `last_seen_at`, `page_size=2` → disjoint, complete). `test_ioc_export_api.py`: one test per filter (`ioc_type`, `search`, `actionability`, `state`), `test_suppressed_excluded_by_default`, `test_state_allowlisted_includes_hidden_rows`, `test_cap_sets_truncated_header` (monkeypatch `_EXPORT_CAP` to 3, four rows → three data lines + header `X-Export-Truncated: true`), `test_export_requires_export_data` (403), `test_value_starting_with_at_is_neutralised` (email `@x` → `'@x`), `test_export_writes_audit`, `test_export_batches_ties_complete` (Review Focus 1).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_ioc_query.py tests/integration/test_ioc_export_api.py tests/integration/test_ioc_suppressed_exclusion.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; Indonesian docstring on why the export keysets instead of offsets and why every TLP is included (C2: IOCs are platform-wide, the file carries `tlp`/`pap`).
- [ ] **Step 4: Run** the Step 2 command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): IOC CSV export with the list filters and a stable list order`

### Task 7: FP suggestion TP count and allowlist note (4.6)

**Files:**
- Modify: `apps/api/src/cti_api/services/fp_analytics.py` (`get_fp_analytics`), `apps/api/src/cti_api/routers/iocs.py` (`AllowlistBody`, `ioc_allowlist_add`), `packages/cti-core/src/cti_core/db/repositories/ioc_reference.py` (`AsyncIocAllowlistRepo.create`)
- Test: `tests/integration/test_fp_analytics_service.py`, `tests/integration/test_ioc_allowlist_flag.py`

**Interfaces:**
- Produces: each `suggested_allowlist` item gains `"tp_count": tp` (15-minute cache unchanged); `AllowlistBody.note: str | None = Field(None, max_length=300)`; `AsyncIocAllowlistRepo.create(*, entry_type: str, value: str, added_by: str, note: str | None = None) -> IocAllowlistEntry` (stripped, blank → `None`; an existing entry keeps its note); `POST /api/iocs/allowlist` response gains `"note"`.

- [ ] **Step 1: Write failing tests:** `test_fp_analytics_service.py::test_suggestion_has_tp_count` (`tp_count == 0` on the suggestion), `test_ioc_allowlist_flag.py::test_allowlist_add_with_note` (note `"  from IOC 1.2.3.4 "` stored as `"from IOC 1.2.3.4"`, listed by `GET /api/iocs/allowlist`, 301 chars → 422, blank → `null`, re-add with another note keeps the first).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_fp_analytics_service.py tests/integration/test_ioc_allowlist_flag.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the Step 2 command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): TP count on allowlist suggestions and a note on allowlist entries`

### Task 8: Entities list total, first_seen and `sort=mentions` (4.7, C6)

**Files:**
- Modify: `apps/api/src/cti_api/services/entities.py` (`encode_cursor`, `decode_cursor`, `list_entities`), `apps/api/src/cti_api/routers/entities.py` (`list_entities`), `apps/api/src/cti_api/schemas/entities.py` (`EntityListItem`, `EntityListResponse`)
- Test: `tests/integration/test_entities_api.py`, create `tests/unit/test_entity_cursor.py`

**Interfaces:**
- Produces schemas: `EntityListResponse.total: int | None = None`; `EntityListItem.first_seen: datetime.datetime | None = None`.
- Produces: `encode_cursor(sort_key: str, entity_id: int, count: int | None = None) -> str` (`[name_key, id]`, or `[n30, name_key, id]` when `count` is given); `decode_cursor(cursor: str, *, sort: Literal["name", "mentions"] = "name") -> tuple[int | None, str, int]` (`ValueError` when the shape does not match `sort`); `list_entities(..., sort: Literal["name", "mentions"] = "name")`; `GET /api/entities?sort=name|mentions` (default `name`; only `entities-list-view.tsx` sends `mentions`).
- Logic: `total` only when `cursor is None` (`stmt.with_only_columns(func.count(Entity.id)).order_by(None)` before cursor/limit); `mentions` LEFT JOINs a subquery `count(distinct(EntityMention.article_id))` per `entity_id` joined to `Article` where `_article_day() >= _today() - timedelta(days=30)`, key `coalesce(n30, 0)`; order `n30 DESC, _sort_key() ASC, Entity.id ASC`; keyset `n30 < c OR (n30 = c AND tuple_(_sort_key(), Entity.id) > tuple_(c_name, c_id))`; the cursor stores the SQL values of the last row.

- [ ] **Step 1: Write failing tests.** Unit `test_entity_cursor.py`: round trip in both shapes, `decode_cursor(name_cursor, sort="mentions")` and `decode_cursor(mentions_cursor, sort="name")` raise `ValueError`, garbage raises. Integration `test_entities_api.py`: `test_list_total_first_page_only` (total with `type`, `q`, `watched`, `include_suppressed`; `null` with a cursor; merged tombstones not counted), `test_list_item_first_seen`, `test_list_sort_mentions` (order by 30-day count, ties by name then id, zero-mention entities last, row `mentions_30d` equals the sort key, `limit=2` pages disjoint and complete across a tie boundary, `type` filter still applies), `test_list_sort_mentions_bad_cursor` (`name` cursor with `sort=mentions` → 422), `test_list_sort_name_rejects_mentions_cursor` and `test_list_sort_mentions_non_ascii_tie` (Review Focus 2), `test_default_sort_unchanged` (no `sort` → name order as before).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_entity_cursor.py tests/integration/test_entities_api.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the Step 2 command — Expected: PASS.
- [ ] **Step 5: Timing note.** In the local compose project `qacve` (never `deploy-postgres-1`), scale the synthetic seed (about 5 000 entities, 200 000 mentions over 120 days) and run `EXPLAIN ANALYZE` of the first and a later `sort=mentions` page (`limit=50`). Record both timings in the task report and the commit body. Above 300 ms for one page: stop and report to the controller (an index would need a migration, which this release excludes); do not add one.
- [ ] **Step 6: Commit** `feat(api): entities total, first_seen and sort by 30-day mentions`

### Task 9: RFI status counts, server search, PIR filter and due sort (4.8)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/rfi.py` (`list_filtered`, new `status_counts`), `apps/api/src/cti_api/schemas/rfi.py`, `apps/api/src/cti_api/routers/rfi.py` (`get_rfis`)
- Test: `tests/integration/test_rfi_query.py`

**Interfaces:**
- Produces: `RFIStatusCounts(open: int = 0, in_progress: int = 0, closed: int = 0)`; `RFIListResponse.status_counts: RFIStatusCounts`; `AsyncRFIRepo.status_counts(client_id: str) -> dict[str, int]` (one `GROUP BY status`, missing → 0, unknown ignored, independent of the `status` filter).
- Produces (flag accepted, spec 4.8 "small, recommended"): `list_filtered(..., q: str | None = None, linked_pir: int | None = None, sort: Literal["created", "due"] = "created")` (`q`: `question ILIKE` or `requester ILIKE`, wildcards escaped; `due`: `due_date ASC NULLS LAST, id`; `created`: `created_at DESC, id DESC`); `GET /api/rfi?q=&linked_pir=&sort=created|due`.

- [ ] **Step 1: Write failing tests:** `test_status_counts_per_client` (acme rows not counted), `test_status_counts_filter_independent` (`status=closed` still returns all three counts), `test_status_counts_unknown_status_ignored`, `test_search_and_linked_pir_filter` (`q` matches question and requester case-insensitively; `%` in `q` is literal), `test_sort_due` (nulls last, id tie-breaker).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_rfi_query.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the Step 2 command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): RFI status counts, search, linked PIR filter and due sort`

### Task 10: Entity profile summary and article count (4.9, D24)

**Files:**
- Modify: `apps/api/src/cti_api/services/ta_profile.py` (`_SYSTEM_PROMPT`, `build_profile_input`, `generate_ta_profile`, new `normalise_summary`, `ProfileInput`), `apps/api/src/cti_api/services/entities.py` (`entity_detail` where `profile=` is built), `apps/api/src/cti_api/schemas/entities.py` (`EntityDetail`)
- Test: `tests/unit/test_prompt_correctness.py`, `tests/integration/test_ta_profile_context.py`, `tests/integration/test_entities_api.py`, keep `tests/unit/test_llm_call_sites.py` green

**Interfaces:**
- Produces: `_SYSTEM_PROMPT` schema gains, as the first top-level key, `"summary": "<2-3 plain sentences, at most 600 characters: who the actor is, what it targets and what the recent reporting in the context adds. Use only the provided context; write null when the context says nothing>"` (`_PROMPT_VERSION` changes automatically; `get_llm_client(task="ta_profile")` unchanged; no new task name or Settings key).
- Produces: `class ProfileInput(NamedTuple): message: str; mitre_group_id: str | None; article_count: int` returned by `build_profile_input` (`article_count = len(news)`, at most 10); `SUMMARY_MAX = 600`; `normalise_summary(profile: dict[str, Any], context: str) -> str | None` (non-string → `None`; whitespace collapsed; unknown CVE ids scrubbed with `grounding.Grounder(grounding.Known.build(text=context)).free_text("summary", ...)`; cut at 600 characters on a word boundary; empty → `None`); `generate_ta_profile` stores `profile["summary"]` and `profile["_article_count"]`.
- Produces: `EntityDetail.profile_summary: str | None = None`, `profile_article_count: int | None = None` (from `profile.get("summary")`, `profile.get("_article_count")`; old profiles → `null`).

- [ ] **Step 1: Write failing tests.** Unit: `test_ta_profile_schema_has_summary_first`, `test_normalise_summary_non_string` (`None`, `123`, `[]` → `None`), `test_normalise_summary_overlong` (650 chars → ≤ 600, ends on a word), `test_normalise_summary_unknown_cve_replaced` (`CVE-2099-0001` not in context is scrubbed), `test_normalise_summary_known_cve_kept`. Integration: update `test_ta_profile_context.py` for the 3-field `ProfileInput` (`article_count` equals seeded titles; 12 titles → 10); `test_entities_api.py::test_profile_summary_exposed` (stub `ta_profile._call_llm`; after `POST /api/entities/{id}/profile`, `GET` returns `profile_summary` and `profile_article_count`; an old stored profile returns both `null`).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_prompt_correctness.py tests/unit/test_llm_call_sites.py tests/integration/test_ta_profile_context.py tests/integration/test_entities_api.py -k "summary or profile or prompt or call_site" -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces (the new prompt line may exceed 100 characters: `pyproject.toml` already ignores `E501` for `services/ta_profile.py`).
- [ ] **Step 4: Run** the Step 2 command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): AI summary and article count in entity profiles`

### Task 11: API contract, loose types and snapshots

**Files:**
- Modify: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts` (generated), `apps/web/src/lib/api/loose-types.ts`, snapshots under `tests/integration/__snapshots__/` for `test_pir_router_snapshot.py`, `test_rfi_router_snapshot.py`, `test_source_reliability_router_snapshot.py`, `test_iocs_router_snapshot.py`

**Interfaces:**
- Produces for the web: `components["schemas"]` gains `PIRPreviewIn`, `PIRPreviewOut`, `PIRLinkedRFI`, `PIRMatchedCampaign`, `RFIStatusCounts`, and the new fields on `PIROut`, `RFIListResponse`, `EntityListItem`, `EntityListResponse`, `EntityDetail`; new paths `/api/pir/preview`, `/api/sr/entries/export`, `/api/iocs/export`.
- Produces in `loose-types.ts`: `SpikeDaily { dates: string[]; threat_actors: Record<string, number[]>; industries: Record<string, number[]>; countries: Record<string, number[]>; overall: number[] }` and `SpikesResponse.daily: SpikeDaily`; `IocFpSuggestion.tp_count: number`; `IocAllowlistEntry.note: string | null`; `IocListResponse` checked against `list_iocs` (fields unchanged unless the router differs).

- [ ] **Step 1: Regenerate** `uv run python tools/export_openapi.py`, then `cd apps/web && pnpm run gen:api`. Expected: `git diff --stat` shows only these two generated files.
- [ ] **Step 2: Update `loose-types.ts`** per Interfaces (Indonesian comment naming the serialiser each shape comes from).
- [ ] **Step 3: Snapshots.** `uv run pytest tests/integration/test_pir_router_snapshot.py tests/integration/test_rfi_router_snapshot.py tests/integration/test_source_reliability_router_snapshot.py tests/integration/test_iocs_router_snapshot.py -q`; read the diff (only the new keys: `linked_rfis`, `linked_rfi_open`, `matched_campaigns`, `status_counts`, `note`, `tp_count`, new routes), then rerun with `--snapshot-update`.
- [ ] **Step 4: Verify** ruff + format check; mypy; fast suite; `uv run pytest tests/integration -k "pir or rfi or source_reliability or sr_export or ioc or fp_analytics or entities or ta_profile or articles_combined or migrations" -q`; web `pnpm exec next typegen && pnpm exec tsc --noEmit` (existing code still type-checks).
- [ ] **Step 5: Commit** `chore(api): regenerate the API contract for the Intelligence data changes`

### Task 12: Intelligence shell and primitives A (6.0, 6.13 #1, #2, #5, #9-#13)

**Files:**
- Create: `apps/web/src/components/intelligence/intelligence-page-header.tsx`, `apps/web/src/lib/intelligence/routes.ts`, `apps/web/src/components/ui/hero-panel.tsx`, `meter-bar.tsx`, `preset-control.tsx`, `star-toggle.tsx`, `legend-row.tsx`; one `layout.tsx` per segment under `apps/web/src/app/(app)/intelligence/` (`risk-matrix`, `source-reliability`, `early-warning`, `pir`, `rfi`, `mitre`, `entities`, `ioc-management`, `campaign-clusters`)
- Modify: `apps/web/src/app/(app)/intelligence/layout.tsx`, `apps/web/src/components/intelligence/intelligence-nav.tsx` (hidden on `/intelligence/entities/[id]`), `apps/web/src/lib/intelligence/format.ts`, `apps/web/src/components/ui/selectable-list.tsx`, `apps/web/src/components/ui/stat-tile.tsx`

**Interfaces (Produces):**
- `INTELLIGENCE_ROUTES: readonly { segment: string; href: string; title: string; description: string; docTitle: string }[]` with the inventory H1/description table verbatim (e.g. `mitre`: "MITRE ATT&CK heatmap" / "Which techniques each threat actor is reported using; click a cell for the articles behind it") and `routeFor(pathname: string): IntelligenceRoute | null` (`null` for `/intelligence/entities/{id}`; `/intelligence/entities/resolve` → Entities).
- `IntelligencePageHeader()` (client, `usePathname()`, pattern of `components/cve/cve-page-header.tsx`): `PageHeader kicker="INTELLIGENCE" title description`, then `IntelligenceNav`, then the rule; renders nothing for the entity detail. `layout.tsx` stays a Server Component rendering it; segment layouts export `metadata.title` ("Risk matrix", "Source reliability", "Early warning", "PIR", "RFI", "MITRE ATT&CK heatmap", "Entities", "IOC management", "Campaign clusters").
- `lib/intelligence/format.ts` adds: `displayId(prefix: "PIR" | "RFI", id: number): string` (`padStart(2, "0")`); `pirPriority(p: string): { label: string; tone: "destructive" | "warning" | "info" | "neutral" }` (P1 Critical destructive, P2 High warning, P3 Medium info, else verbatim neutral); `PIR_PRIORITY_OPTIONS = [{value: "P1", label: "Critical"}, {value: "P2", label: "High"}, {value: "P3", label: "Medium"}] as const`; `confidenceWord(n: number | null): "high" | "medium" | "low" | "unrated"` (≥ 80, ≥ 50, else low; `null` unrated); `originLabel(o: string): string` (`default` → "auto", `analyst` → "analyst"); `actionLabel(label: string | null): { word: "BLOCK" | "INVESTIGATE" | "MONITOR" | "ARCHIVE"; tone: "destructive" | "warning" | "info" | "neutral" } | null` (`block_now`, `investigate`, `monitor`, `archive`).
- `HeroPanel({ kicker?: ReactNode; title: ReactNode; children?: ReactNode; footer?: ReactNode; className?: string })` (`bg-hero`, `text-hero-foreground`, kicker `text-hero-eyebrow`, muted `text-hero-muted`; exports `heroLinkClass` = `text-hero-accent` + focus ring with `ring-offset-hero`).
- `MeterBar({ value: number; max: number; tone?: "neutral" | "primary" | "destructive" | "warning" | "success"; variant?: "default" | "baseline" | "diverging"; baseline?: number; label?: ReactNode; "aria-label": string; className?: string })` (`role="meter"`, `aria-valuenow/min/max`, text alternative; `diverging` centres zero, positive destructive, negative success).
- `PresetControl({ label: string; presets: readonly { value: number; label: string }[]; value: number; onChange: (v: number) => void; min: number; max: number; step?: number; "aria-label": string })` (micro label `text-2xs` uppercase above, `SegmentedControl` + "Custom" segment revealing a number `Input`, committed on Enter/blur, out of range → `Field` error "Enter a value from {min} to {max}.").
- `StarToggle({ on: boolean; onToggle?: () => void; name: string; disabled?: boolean })` (`aria-pressed`, `aria-label` "Watch {name}" / "Stop watching {name}", filled `text-primary` star when on, 24 px target; read-only without `onToggle`).
- `LegendRow({ items: readonly { label: string; swatchClass: string }[] })` (swatches `aria-hidden`).
- `SelectableList` gains `variant?: "row" | "card"` (card: full 1 px border, selected 2 px `border-foreground` + `bg-surface`). `StatTile` gains `selected?: boolean; onSelect?: () => void` (renders `<button aria-pressed>` when `onSelect` is set).

- [ ] **Checklist:** every Intelligence tab shows kicker "INTELLIGENCE", its own `<h1>`, description and the 9 pills in today's order; browser tab title "{docTitle} · {platform}"; entity detail shows no pills and no Intelligence `<h1>`; `/intelligence/entities/resolve` keeps the Entities header; PresetControl Custom accepts 45 for a 14-90 range and refuses 5 with the field error; StarToggle announces its state.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): intelligence page header, hero panel, meter, preset and star primitives`

### Task 13: Primitives B (6.13 #3, #4, #6-#8) and `lib/csv.ts`

**Files:**
- Create: `apps/web/src/components/ui/bar-series.tsx`, `heat-grid.tsx`, `use-grid-roving-keys.ts`, `chip-input.tsx`, `date-field.tsx`; `apps/web/src/lib/csv.ts`
- Modify: `apps/web/src/components/confirm-dialog.tsx`, `apps/web/src/components/entities/entity-timeline-chart.tsx` (internals → `BarSeries`, export unchanged)

**Interfaces (Produces):**
- `BarSeries({ labels: string[]; values: number[]; highlight?: (index: number) => boolean; highlightLast?: number; referenceLine?: number; height?: number; "aria-label": string; tone?: "neutral" | "primary"; highlightTone?: "primary" | "destructive" })` (Chart.js bar; reference line as a line dataset, no plugin; colours from CSS variables; visually hidden `<table>` with the same data).
- `useGridRovingKeys(rows: number, cols: number, active: [number, number] | null, onMove: (r: number, c: number) => void, onSelect: (r: number, c: number) => void)` → `{ onKeyDown, tabIndexFor(r, c), setRef(r, c) }` (arrows, Home/End, Enter/Space).
- `HeatGrid({ rowLabels: ReactNode[]; colLabels: ReactNode[]; renderCell: (r: number, c: number) => ReactNode; active: [number, number] | null; onSelect: (r: number, c: number) => void; "aria-label": string })` (sticky headers, `role="grid"`); `HeatCell({ variant: "tier" | "scale"; value: number | null; tier?: "low" | "med" | "high"; step?: 0 | 1 | 2 | 3 | 4 | 5; selected?: boolean; outlined?: boolean; trend?: "rising" | "falling" | "stable"; "aria-label": string; title?: string })` (tier tints `bg-success/15`, `bg-warning/20`, `bg-destructive/20` with `text-X-text`; scale steps capped `bg-primary/10..45`, step 5 `bg-hero text-hero-foreground`; `null` = bordered empty box; selected = 2 px ink ring; trend icon with `aria-label` "rising/falling/stable").
- `ChipInput({ values: string[]; onChange: (v: string[]) => void; "aria-label": string; placeholder?: string; suggest?: (q: string) => Promise<string[]>; id?: string })` (Enter/comma adds the trimmed value; blank and case-insensitive duplicates ignored; Backspace on empty input removes the last chip; chip list `aria-live="polite"`).
- `DateField({ id: string; value: string | null; onChange: (v: string | null) => void; "aria-label"?: string; optional?: boolean })` (button shows `fmtShortDate` with year, e.g. "1 Nov 2026", calls `showPicker()` on a visually hidden `<input type="date">`, falls back to focus; clear button when `optional`; value `YYYY-MM-DD` via `parseLocalDate`).
- `ConfirmDialog` adds `note?: { label: string; placeholder?: string; maxLength: number }`, `onConfirm: (note?: string) => void`, `tone?: "default" | "danger"` (danger → `Button variant="destructive"`), `confirmLoading?: boolean`; existing callers compile unchanged.
- `lib/csv.ts`: `csvCell(v: unknown): string` (same guard as Task 2), `toCsv(header: string[], rows: unknown[][]): string` (BOM + `\r\n`), `downloadCsv(filename: string, text: string): void`; `downloadBlob(url: string, fallbackName: string): Promise<{ truncated: boolean }>` (fetch through `/api/proxy`, filename from `Content-Disposition`, reads `X-Export-Truncated`).

- [ ] **Checklist:** entity Overview "Mentions per month" still renders through `BarSeries`; ChipInput ignores `" "` and a second "LockBit" (Review Focus 5); DateField shows "1 Nov 2026" for `2026-11-01` in a west-of-UTC zone; existing `ConfirmDialog` users (recap etc.) unchanged.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): bar series, heat grid, chip input, date field, confirm-with-note and CSV helpers`

### Task 14: Newsroom URL contract and `newsroomHref` (4.1 web, D4)

**Files:**
- Create: `apps/web/src/lib/newsroom/links.ts`
- Modify: `apps/web/src/app/(app)/newsroom/page.tsx`, `apps/web/src/components/newsroom/article-list-sheet.tsx` (`Source` union, `useSheetList`)

**Interfaces:**
- Produces: `newsroomHref(p: { actor?: string; industry?: string; ttp?: string | string[]; country?: string; from?: string; period?: 1 | 7 | 30 }): string` (`/newsroom?...`, values URL-encoded, `ttp` repeatable, empty values omitted).
- Produces: `ArticleListSheet` source `{ query: { threat_actor?: string[]; industry?: string[]; ttp?: string[]; country?: string[]; posted_on_start?: string }; title: string }` with its own `useArticlesQuery(["sheet-query", query], { page, page_size: PAGE_SIZE, sort: "recent", ...query }, open && "query" in source, true)` (independent of the masthead filters, so the count matches the source number).
- Page reads once on load: `actor`, `industry`, `ttp` (repeatable), `country`, `period` (1|7|30), new `from` (`YYYY-MM-DD`, valid local date; wins over `period`). With `actor`, `industry` or `ttp` the sheet opens with title = values joined by " × "; `country` alone keeps the masthead behaviour.

- [ ] **Checklist:** `/newsroom?actor=LockBit&ttp=T1486&from=2026-10-10` opens the sheet "LockBit × T1486" with that count; `industry=Finance&country=ID` opens a sheet; `?country=ID` alone filters the masthead as today; malformed `from=2026-13-40`, `period=45`, empty `actor=` are ignored without errors.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): Newsroom deep links for actor, industry, technique and date`

### Task 15: Early Warning (6.3)

**Files:**
- Modify: `apps/web/src/components/intelligence/early-warning-view.tsx`
- Create: `apps/web/src/components/intelligence/early-warning/strongest-signal-panel.tsx`, `apps/web/src/components/intelligence/early-warning/anomaly-list.tsx`

**Interfaces:**
- Consumes: `SpikesResponse` incl. `daily` (Task 11); `PresetControl`, `HeroPanel`, `MeterBar`, `BarSeries`, `StatTile`, `SelectableList` (Tasks 12-13); `newsroomHref` (Task 14); `EntityChip`.
- Produces: `EarlyWarningView()` (export unchanged).

- [ ] **Toolbar:** LOOKBACK 14d | 30d | 60d | 90d (+ Custom 14-90, default 30); Z-SCORE THRESHOLD 1.5σ | 2σ | 2.5σ | 3σ (+ Custom 1.5-4.0 step 0.1, default 2); meta "{n} anomalies · recent window: last 7 days · updated {fmtTime(generated_at)}, refreshes every 15 min".
- [ ] **Tiles:** Threat actors, Industries, Countries, Overall volume: count, sub "top: {entity} · z {z}" and "{h} high · {m} medium" (high `text-destructive-text`).
- [ ] **Anomalies card:** `SegmentedControl` Grouped | All by z; Grouped sections in order actor, industry, country, overall ("THREAT ACTOR SPIKES · 4"), each by z; rows per spike day: name (`EntityChip` text style when `entity_id`), "threat actor · {fmtShortDate(date)}", `MeterBar variant="baseline"` (count vs group max, tick `baseline_mean`, caption "{count} articles that day · baseline {baseline_mean}/day"), HIGH/MEDIUM chip, "z {z}σ"; HIGH rows on a faint destructive tint. Row click selects (D5); default = highest z.
- [ ] **Strongest signal (`HeroPanel`):** name, "{type} · spike on {date}", "{z}σ" + chip, "{count} articles vs {baseline_mean}/day", `BarSeries` of the `daily` series (category + entity name; overall `daily.overall`), bars on or after today − 7 destructive, reference line `baseline_mean`, caption "Daily articles, last {lookback} days"; links "Open in Newsroom" (`newsroomHref({ actor | industry | country, period: 7 })`; overall → `period: 7` only) and "Entity page" (hidden when `entity_id` is null).
- [ ] **How detection works:** the five steps of spec 6.3 verbatim (C9).
- [ ] **States:** loading skeleton; empty "No anomalies above {z}σ in the last {lookback} days" with the hint to lower the threshold; error with Retry.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): early warning with grouped anomalies and strongest-signal panel`

### Task 16: Risk Matrix (6.1)

**Files:**
- Modify: `apps/web/src/components/intelligence/risk-matrix-view.tsx`
- Create: `apps/web/src/components/intelligence/risk-matrix/selected-cell-panel.tsx`, `apps/web/src/components/intelligence/risk-matrix/pairs-and-movers.tsx`

**Interfaces:**
- Consumes: `RiskMatrixResponse`; `RISK_MED_MIN` 40 / `RISK_HIGH_MIN` 70 (`lib/exec/format.ts`), `Chip kind="risk"`; `HeatGrid`, `HeatCell variant="tier"`, `HeroPanel`, `LegendRow`, `MeterBar variant="diverging"`, `PresetControl`, `FilterSelect` (Tasks 12-13); `toCsv`/`downloadCsv` (Task 13); `newsroomHref` (Task 14); `EntityChip`.

- [ ] **Toolbar:** PERIOD 7d | 30d | 60d | 90d (+ Custom 7-90, default 30); COMPARE WITH `FilterSelect` "Previous 7 / 14 / 30 / 60 / 90 days" (+ "Custom…" 7-90); MIN RISK SCORE All | ≥25 | ≥50 | ≥75 (+ Custom 0-100); meta "Generated {fmtTime(generated_at)} · {n} cells · {i} industries × {c} countries".
- [ ] **Grid card** (`lg:col-span-3` of 5): "Industry × country", subtitle, `LegendRow` Low / Med / High; sticky text labels; tier cells with score + trend icon; cells below MIN score empty; hottest outlined; selected ring; `aria-label` "Finance × Indonesia, score 100, high, rising"; `title` tooltip kept; default selection = hottest.
- [ ] **Selected cell (`HeroPanel`):** "SELECTED CELL", "{industry} × {country name}", score + risk chip + arrow + "hottest cell in the matrix"; This period, Compare period, Change "+56%" ("new" when previous is 0); TOP ACTORS `EntityChip`s; HOW THE SCORE WORKS verbatim from spec 6.1; "Open in Newsroom" (`newsroomHref({ industry, country, from: today − days })`), industry and country `EntityChip`s; footnote "Opens Newsroom with the same industry, country and period".
- [ ] **Highest-risk pairs:** top 8, #, INDUSTRY × COUNTRY, SCORE chip + arrow, ARTICLES "42 / 27", TOP ACTOR; row click selects; "Export CSV" (`export_data`) of all cells via `lib/csv.ts`.
- [ ] **Biggest movers:** "{pair} prev → curr" + diverging `MeterBar`, only `previous_count ≥ 3` (footnote "Only pairs with at least 3 articles in the compare period."), top 8 by absolute change.
- [ ] **Checklist:** arrow keys move across cells, Enter selects; the Newsroom sheet count equals "This period" for a seeded cell; dark mode tier contrast.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): risk matrix heat grid with selected-cell panel, pairs and movers`

### Task 17: MITRE heatmap (6.6, D9, D10, D27)

**Files:**
- Modify: `apps/web/src/components/intelligence/mitre/mitre-heatmap-view.tsx`
- Create: `apps/web/src/components/intelligence/mitre/ttp-drill-card.tsx` (logic from `ttp-drill-dialog.tsx`), `apps/web/src/components/intelligence/mitre/attack-data-card.tsx` (logic from `components/entities/attack-sync-card.tsx`)
- Delete (after `grep -rn ttp-drill-dialog apps/web/src` shows only the view): `ttp-drill-dialog.tsx`

**Interfaces:**
- Consumes: `GET /api/mitre/heatmap` (`top_rows`, `top_ttps`), `/api/mitre/articles`, `/api/mitre/navigator-export`, `/api/mitre/d3fend/{technique_id}`, `GET /api/attack/status`, `POST /api/attack/sync`; `HeatGrid`, `HeatCell variant="scale"`, `LegendRow`, `PresetControl`, `FilterSelect`, `NumberedPager`, `RowMenu` (Tasks 12-13, 2a); `newsroomHref` (Task 14).
- Produces: `AttackDataCard()` (read-only for `view_intel`, "Sync now" only `manage_intel`).

- [ ] **Toolbar:** VIEW Actors | Industries (`view=ta|industry`); PERIOD 30d | 90d | 180d | 365d (+ Custom 7-365, default 90); ROWS "Top 5/10/15/20/30 {actors|industries}" (default 10); COLUMNS "Top 8/12/20/30/40 techniques" (default 12); "Export ATT&CK Navigator layer" and "⋯ → Open in ATT&CK Navigator", both sending the selected `view/days/top_rows/top_ttps` (no hardcoded 15/20).
- [ ] **Heatmap card:** "Actor × technique" / "Articles mentioning both · max {max_val}", `LegendRow` 0 → max, five swatches; column headers TTP id (`font-code`, link to the entity page when `entity_id`) + wrapped name; 5 scale steps by `count / max_val`; 0 = bordered empty; keyboard as 6.1; default selection = max cell.
- [ ] **Drill card:** "{row} × {TTP id} {name}" / "{n} articles · newest first", "Open in Newsroom →" (`actor` or `industry` + `ttp`, `from` = today − days), article rows (title link, "{source} · {date}", news type chip), `NumberedPager`; collapsible "Countermeasures (D3FEND)" with the existing call and rendering.
- [ ] **ATT&CK data card:** rows per domain (label, version, `fmtShortDate(last_sync)`, dot success / warning "sync error {date}" with error tooltip), "Sync now" (existing POST + polling), footnote "Techniques not in the catalog show without a link to their entity page."
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): MITRE heatmap with presets, inline drill and ATT&CK data card`

### Task 18: Source Reliability (6.2, D6, D8)

**Files:**
- Modify: `apps/web/src/app/(app)/intelligence/source-reliability/page.tsx`, `apps/web/src/components/intelligence/source-reliability/sr-table.tsx`, `sr-review-table.tsx`, `sr-entry-dialog.tsx` (read-only mode)
- Create: `apps/web/src/components/intelligence/source-reliability/sr-grid.tsx`, `sr-aside.tsx`

**Interfaces:**
- Consumes: `GET /api/sr/entries?origin=`, `/api/sr/entries/export` (Task 5), `/api/sr/stats` (`SrStats`), `/api/sr/labels`, `/api/sr/review`; `originLabel`, `MeterBar`, `FilterSelect`, `SearchInput`, `RowMenu`, `NumberedPager`, `ConfirmDialog tone="danger"`, `downloadBlob` (Tasks 12-13).
- Produces: `SrEntryDialog` gains `readOnly?: boolean`.

- [ ] **Toolbar:** `TabPills` "All sources {entries.total}" | "Needs review {review.items.length}" (second pill and its query only with `manage_sources`); `SearchInput` "Search source name"; `FilterSelect` Grade (all, A-F), Origin (all | auto | analyst); "Export CSV" (`export_data`, current filters) and "+ Add source" (`manage_sources`).
- [ ] **Sources card:** "{total} sources · sorted by {sort label}"; `SegmentedControl` Table | Grid; Table SOURCE, ADMIRALTY (`Chip kind="grade"`, A/B success, C warning, D/E destructive, F muted), RELIABILITY, KIND, ORIGIN, ANALYST, UPDATED (`fmtCompactAge`); sortable headers with `aria-sort` (default `last_updated desc`); row click opens the dialog (edit or read-only with Notes); `RowMenu` Edit / Remove (`ConfirmDialog` danger); Grid cards (3 columns `lg`, 2 below) with the same fields + first line of notes; `NumberedPager` "Showing 1-25 of 96", 25 per page.
- [ ] **Aside:** Grade distribution `MeterBar` rows A-F from `by_grade` (click sets the Grade filter); "Reading an Admiralty code" legend from `/labels` + footnote "Grades set by an analyst override the automatic grade. 'Needs review' lists auto-graded sources."
- [ ] **Needs review:** SOURCE, KIND, GRADE "C → B3", LEADS `lead_count` / `multi_source_stories`, ARTICLES (30 d), OFF-TOPIC, ARTEFACT %, IOC FP % (destructive text > 50 %), WHY (`REASON_TEXT`), outline "Apply {code}" (existing confirm call) and "⋯ → Edit".
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): source reliability table and grid with origin filter, export and grade aside`

### Task 19: PIR list, detail and dialog (6.4, D14-D18)

**Files:**
- Modify: `apps/web/src/app/(app)/intelligence/pir/page.tsx`, `apps/web/src/components/intelligence/pir/pir-list.tsx`, `pir-form-dialog.tsx` (rebuilt)
- Create: `apps/web/src/components/intelligence/pir/pir-detail-card.tsx`, `apps/web/src/lib/intelligence/pir.ts`
- Delete (after `grep -rn multi-select-field apps/web/src` shows only the dialog): `multi-select-field.tsx`

**Interfaces:**
- Consumes: `PIROut.linked_rfis`, `linked_rfi_open`, `matched_campaigns`, `GET /api/pir?include_campaigns=true`, `POST /api/pir/preview` (Tasks 3-4, 11); `GET /api/pir/{id}/coverage/weekly?weeks=12`, `/export`, `/export/docx`, `GET /api/stix/pirs`, `GET /api/pir/options`; `pir-articles-dialog.tsx` (kept); `displayId`, `pirPriority`, `PIR_PRIORITY_OPTIONS`, `SelectableList variant="card"`, `MeterBar`, `BarSeries`, `ChipInput`, `DateField`, `RowMenu`, `ConfirmDialog` (Tasks 12-13).
- Produces in `lib/intelligence/pir.ts`: `usePirs(): UseQueryResult<PIROut[]>` (key `["pir", "list"]`), `usePirCampaigns(): UseQueryResult<PIROut[]>` (key `["pir", "list", "campaigns"]`, `include_campaigns=true`, `staleTime` 10 min), `usePirPreview(criteria: PIRCriteria, enabled: boolean)` (500 ms debounce, key `["pir", "preview", JSON.stringify(criteria)]`).

- [ ] **URL state:** `?status=active|paused|archived` (default active), `?id=`.
- [ ] **Toolbar:** `TabPills` Active {n} | Paused {n} | Closed {n} (Closed = `archived`); `FilterSelect` Owner, Priority (Critical/High/Medium); "Export" dropdown (`export_data`: "STIX bundle of active PIRs"); "+ New PIR" (`manage_pir`).
- [ ] **List cards:** `displayId` (`font-code`), priority chip, `COVERAGE GAP` chip when `is_gap`, "Owner: {owner} · last match {fmtCompactAge(last_match)} ago" ("never"), title, filled criteria rows (THREAT ACTORS, MALWARE, INDUSTRIES, COUNTRIES, TTPS, KEYWORDS, NEWS TYPES), `MeterBar` (destructive when gap) + "{coverage_count} articles matched · {recent_coverage} in 14 days"; "⋯" Edit, Export JSON, Export DOCX, Delete (`ConfirmDialog` danger).
- [ ] **Detail:** "{PIR-03} coverage" / "Articles matched per week, since {fmtShortDate(since)}" `BarSeries` (last 2 destructive when `is_gap`, else primary); Matched articles; Linked RFIs "{linked_rfi_open} open" → `/intelligence/rfi?pir={id}` (tooltip lists `linked_rfis`); Campaigns matched (links `/intelligence/campaign-clusters?id=`, skeleton while loading, "Only active PIRs are matched to campaigns" for others, "none in the last 30 days" when empty); Period "{start} - {end}" ("open-ended"); description markdown collapsible; "View articles", "Export JSON", "⋯" Export DOCX, Edit, Delete. Static card "What a coverage gap means": "A PIR shows COVERAGE GAP when it has matched articles before but none in the last 14 days. A PIR without criteria always shows a gap."
- [ ] **Dialog:** title "New priority intelligence requirement" / "Edit PIR-03"; Title `Field` error "Give the PIR a title, for example …" (no toast); Priority `SegmentedControl` Critical | High | Medium; Owner; Start date / End date (optional) `DateField`; label "CRITERIA · AN ARTICLE MATCHES WHEN IT HITS ANY CHIP IN EVERY FILLED ROW"; `ChipInput` Threat actors, Industries, Countries, ATT&CK techniques (suggestions from `/api/pir/options` and entity autocomplete), Keywords; "Advanced" collapsible with Description, Malware and tools, News types, Status (edit only), open automatically when any has a value; footer "Preview: {count} articles in the last 90 days would match" ("No criteria: every article matches ({count})" when `has_criteria` is false; spinner; hidden on error), Cancel (ghost), Create PIR / Save (`loading`). API errors inline, input kept.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): PIR master-detail with coverage chart, linked RFIs, campaigns and rebuilt dialog`

### Task 20: RFI master-detail and dialog (6.5, D19)

**Files:**
- Modify: `apps/web/src/app/(app)/intelligence/rfi/page.tsx`, `apps/web/src/components/intelligence/rfi/rfi-list.tsx`, `rfi-form-dialog.tsx`
- Create: `apps/web/src/components/intelligence/rfi/rfi-detail-card.tsx`

**Interfaces:**
- Consumes: `GET /api/rfi?status=&q=&linked_pir=&sort=due` + `status_counts` (Tasks 9, 11), `PUT /api/rfi/{id}`, `DELETE /api/rfi/{id}`; `usePirs()` (Task 19) for "PIR-03 {title}" labels; `displayId`, `LoadMoreFooter`, `Table` selected row, `daysUntil`, `DateField`, `ConfirmDialog tone="danger"`.
- Produces: `RfiFormDialog({ open; onOpenChange; rfi?: RFIOut | null })` (create when `rfi` is null; edit adds Status and Response).

- [ ] **URL state:** `?status=open|in_progress|closed` (default open), `?pir=`, `?id=`.
- [ ] **Toolbar:** `TabPills` Open | In progress | Closed with `status_counts`; `SearchInput` "Search questions" (`q`, 300 ms debounce); `FilterSelect` Linked PIR (all, none, "PIR-03 {title}"); "+ New RFI" (`manage_rfi`).
- [ ] **Requests card:** "Due soonest first"; QUESTION (2-line clamp), REQUESTER, PIR (`displayId` link or "—"), DUE (`fmtShortDate`; destructive overdue, warning within 2 days), STATUS chip; `LoadMoreFooter` 25; row click and roving keys select.
- [ ] **Detail:** "RFI-12", "Opened {fmtShortDate(created_at)} by {requester} · due {date}, {in n days | n days overdue}", status chip, question `<h2>`, Linked PIR chip, RESPONSE `Textarea`, `SegmentedControl` Open | In progress | Closed, "Delete" (destructive outline → confirm), "Save response" (`PUT` `response` + `status`); "⋯ → Edit" opens the dialog; read-only without `manage_rfi`.
- [ ] **Dialog:** Question (`Textarea`, hint), Requester, Due date (`DateField`), Linked PIR (`Select` with `items`); "Create RFI" (`loading` "Creating…").
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): RFI master-detail with status counts, search and edit dialog`

### Task 21: IOC management: indicators, detail panel, remove dialog, allowlist and FP analytics (6.9, D20-D23)

**Files:**
- Modify: `apps/web/src/components/intelligence/ioc/ioc-management-view.tsx`, `ioc-table.tsx`, `ioc-allowlist-panel.tsx`, `ioc-fp-analytics-panel.tsx`, `ioc-detail-dialog.tsx` (becomes a thin `Dialog` around `IocDetailBody`, still used by `components/entities/entity-indicators-tab.tsx`)
- Create: `apps/web/src/components/intelligence/ioc/ioc-detail-body.tsx` (content moved from the dialog), `ioc-detail-panel.tsx`

**Interfaces:**
- Consumes: `GET /api/iocs/export` (Task 6), allowlist `note`, `tp_count` (Tasks 7, 11); existing IOC endpoints (`/stats`, list, detail, `/feedback`, `/marking`, `/ta-links`, `DELETE /{id}`, `/allowlist`, `/fp-analytics`, `/apply-suggestions`); `actionLabel`, `StatTile onSelect`, `ConfirmDialog note`, `MeterBar`, `BarSeries`, `NumberedPager`, `downloadBlob` (Tasks 12-13).
- Produces: `IocDetailBody({ target: IocTarget; onChanged: () => void; layout: "panel" | "dialog" })`; `IocDetailPanel({ target: IocTarget | null })`.

- [ ] **View switch:** `TabPills` Indicators {stats.total} | Allowlist {entries.length} | FP analytics (`?view=`).
- [ ] **Indicators toolbar:** `SearchInput` "Search value"; `FilterSelect` Type (all + 7), State (active default, expired, revoked, allowlisted, "All visible", "All incl. suppressed" → `include_suppressed`), Action (all + 4 → `actionability`), Sort (last seen | confidence); "Export CSV" (`export_data`, current filters; toast when `truncated`).
- [ ] **Type tiles:** one `StatTile` per `stats.by_type` entry, `aria-pressed`, toggles the Type filter.
- [ ] **Table:** "{total} {state} · page {p} of {n}"; VALUE (`font-code`, truncated with title; State and TLP chips on line 2 when not active/default), TYPE, CONF. (integer), ACTIONABILITY (score + small `MeterBar`, "—"), ACTION chip (BLOCK destructive, INVESTIGATE warning, MONITOR info, ARCHIVE neutral), SEEN, FEEDBACK "{tp} TP · {fp} FP"; row click and keys select; `NumberedPager` + "Rows 25 | 50 | 100" (default 50); footnote when auto-suppressed rows are hidden.
- [ ] **Detail panel (all dialog content kept, D23):** value + ACTION chip, "{type} · first seen {date} · last seen {age} ago", state/suppression line, `recommended_action`; ENRICHMENT rows (known `raw` keys → "100 / 100", "14 / 94 engines", "6 pulses", fallback `score`), provider tags (first 8), "updated {date}"; THREAT ACTORS + editor (`manage_ioc`); SOURCES · n (article link → `article-by-id-dialog`); MARKING TLP/PAP (`manage_ioc`); TAGS; footer "TP / restore", "FP: remove", "Allowlist" (`ip` → `ip`, domain/url → `url_domain`, email → `email_domain`, note "from IOC {value}"; disabled with tooltip for hashes), "⋯ → Delete IOC" (`ConfirmDialog` danger "This deletes the indicator and its history. It cannot be undone."); `Notice` warning with `source_fp_warning` after an FP.
- [ ] **Remove dialog:** title "Remove {value} from feeds?", body "It stops appearing in STIX and CSV exports for every client. Analysts can restore it with TP.", optional Note (max 2000), Cancel (ghost) + "Remove from feeds" (destructive) → `POST /{id}/feedback {verdict: "fp", note}`.
- [ ] **Allowlist view:** inline Type, Value, Note, "Add to allowlist" (`manage_ioc`); table TYPE, VALUE, NOTE, ADDED "{added_by} · {date}", "Remove" (confirm).
- [ ] **FP analytics view:** "FP rate by IOC type" `MeterBar`s; "Suggested for allowlist" IOC VALUE, TYPE, VERDICTS "{tp_count} TP · {fp_count} FP", ALLOWLIST AS + "Apply all suggestions" (`manage_ioc`); "FP rate by source" table; "FP verdicts per day, 30 days" `BarSeries` (`fp_trend`).
- [ ] **Checklist:** the entity Indicators tab still opens the IOC dialog with identical content; focus returns to the selected row after each dialog.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): IOC management views with detail panel, remove-from-feeds dialog and CSV export`

### Task 22: Campaign clusters and Clusters (Simple) (6.10, D11-D13)

**Files:**
- Modify: `apps/web/src/components/intelligence/campaign-clusters/campaign-clusters-view.tsx`, `campaigns-panel.tsx`, `kill-chain-view.tsx`, `diamond-model-view.tsx`, `simple-clusters-panel.tsx`
- Rename: `campaign-expanded-panel.tsx` → `campaign-detail-card.tsx` (`git mv`, export `CampaignDetailCard`)

**Interfaces:**
- Consumes: `GET /api/clusters/recent` (`CampaignsResponse`), `/api/clusters/{id}/trends`, `GET /api/clusters`; `sortCampaigns`, `GeopoliticalPanel`, `MindmapWidget`, `cluster-pir-dialog.tsx`, `article-by-id-dialog.tsx` (kept); `SelectableList variant="card"`, `PresetControl`, `FilterSelect`, `Switch`, `Notice` (Tasks 12-13, 2a).

- [ ] **URL state:** `?view=campaigns|simple`, `?id=`.
- [ ] **Toolbar:** `TabPills` Campaigns {total} | Clusters (Simple); DAYS 7d | 30d | 90d (+ Custom 1-90, default 7); MIN SIZE 2 / 3 / 5 / 10 articles (+ Custom 2-50, default 3); meta "{total} campaigns · {campaign_links.length} links between them".
- [ ] **List:** "Campaigns" / "Sorted by {sort}" + Sort `FilterSelect` (severity, size, velocity, last seen); cards: "{LABEL} {score}", VELOCITY ALERT, NEW {n} IOCs, trend arrow; "{size} articles · {days_active} days active"; title; actors, industries, countries "ID · SG · MY"; "{label} · {rate}/day" with dot.
- [ ] **Detail:** title, "First seen {date} · last seen {date} · {n} new IOCs in 24 h"; KILL CHAIN "{completeness_label}, {covered} of 7 phases", 7 tiles "n TTP"; DIAMOND MODEL counts ("4 IPs · 2 domains"); PRIORITIZED CVEs (score, id, critical patch / KEV / PoC / in tech stack); "Matches PIR-03 '{title}'" + "Link to PIR →" (`/intelligence/pir?id=`) and "+{n} more PIRs" (opens `cluster-pir-dialog`); "Hunt pack" button in the header; collapsible in order: Severity breakdown, Trend, Member articles, IOCs, Related campaigns (selects), Mind map, Geopolitical context ("all campaigns, {days} days").
- [ ] **Simple:** DAYS 7 | 14 | 30 (+ Custom 7-90); "Similarity threshold" `Input` 0.20-0.70 step 0.05 default 0.35, hint "Higher means tighter clusters."; two `Switch`es (exclude low reliability, single-source); auto-load on mount and change (500 ms debounce), no Generate button, busy `Notice` "Clustering may take a few seconds" on first load; rows `cluster_name`, "{3 names} +n", "{article_count} articles"; spike lookup kept.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): campaign master-detail and auto-loading simple clusters`

### Task 23: Entities list with preview panel (6.7, C5, C6, D27, D28)

**Files:**
- Modify: `apps/web/src/components/entities/entities-list-view.tsx`, `apps/web/src/lib/entities/types.ts` (`ENTITY_TABS` labels + `all`)
- Create: `apps/web/src/components/entities/entity-preview-panel.tsx`
- Delete (after `grep -rn attack-sync-card apps/web/src` shows nothing): `apps/web/src/components/entities/attack-sync-card.tsx`

**Interfaces:**
- Consumes: `GET /api/entities?sort=mentions` + `total`, `first_seen` (Tasks 8, 11), `GET /api/entities/{id}` (`profile_summary`, `profile_generated_at`); `HeroPanel`, `StarToggle`, `LoadMoreFooter`, `Notice`, `RowMenu`.
- Produces: `ENTITY_TABS` gains `{ key: "all", label: "All", types: [] }` first; labels Threat actors, Malware & tools, Techniques, CVEs, Campaigns, Sectors, Locations, Victims (keys unchanged).

- [ ] **URL state:** `tab` (default `all`), `q`, `watched`, `suppressed`, `new`, `id`.
- [ ] **Toolbar:** `SearchInput` "Search name, alias or ATT&CK ID"; type `SegmentedControl` (scrolls inside its group below 1024 px); "Watched only" toggle (`aria-pressed`); "⋯": "Include suppressed" (`manage_entities`), "Download watchlist Navigator layer"; "+ New entity" (`manage_entities`).
- [ ] **List card:** "{tab label}" / "{total} entities · sorted by mentions (30 d)"; NAME (`StarToggle`, `manage_pir` to toggle) + name link, ATT&CK ID, ALIASES (2 + "+n"), 30 D (bold, trend arrow), 90 D, LAST SEEN, TYPE (All only); "Suppressed" chip; row click selects, Enter opens the entity page; `LoadMoreFooter`; card list below 640 px kept.
- [ ] **Preview (`HeroPanel`):** "{TYPE} · {external_id}", name, "Also known as …", tiles Mentions 30 d / 90 d / First seen (month + year), "AI PROFILE · generated {date}" + `profile_summary` (actors; "No AI profile yet"), "{source} · first seen {date}", bullets ON THE ENTITY PAGE (Overview, Relationships, Stories, Indicators, CVEs, Timeline, ATT&CK, Hunt), "Open entity page →"; default selection = first row.
- [ ] **Techniques tab:** `Notice` "ATT&CK sync status moved to MITRE heatmap" with a link.
- [ ] **Checklist:** pickers (`entity-autocomplete`, create, merge, relationship dialogs) still list by name (no `sort` param).
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): entities list sorted by 30-day mentions with preview panel and All tab`

### Task 24: Entity detail page (6.8, D24-D26)

**Files:**
- Modify: `apps/web/src/components/entities/entity-view.tsx`, `entity-actions-menu.tsx` (drop `heroButtonClass`, mockup labels), `entity-overview-tab.tsx` (`AboutCard`), `entity-relationships-tab.tsx` (`EntityRelationshipsSummary`)
- Create: `apps/web/src/components/entities/entity-header.tsx`
- Delete (after `grep -rn entity-hero apps/web/src` shows only the view): `entity-hero.tsx`

**Interfaces:**
- Consumes: `EntityDetail.profile_summary`, `profile_article_count` (Tasks 10-11); `/timeline`, `/relationships`; `confidenceWord`, `StarToggle`, `StatTile`, `BarSeries`, `TabPills`; `HuntPanel`, `MindmapWidget` (kept).

- [ ] **Header:** kicker "ENTITIES › {TYPE} · {external_id}" ("Entities" links back to the list tab), `<h1>` name + `StarToggle`, "Suppressed" chip, "Also known as …" (+n disclosure), "Sources: {source} · first seen {date}"; "Watching" / "Watch" (`manage_pir`) and "Actions ▾" (Edit name and description, Manage aliases, Split aliases, Merge into another entity…, Suppress from feeds; permissions unchanged); `document.title = "{name} · Entities"` once loaded.
- [ ] **Tiles:** Mentions 30 days, Stories, Indicators, CVEs, Last seen. **Tabs:** Overview, Relationships {n}, Stories {n}, Indicators {n}, CVEs {n}, Timeline, ATT&CK, Hunt (`view_ioc`).
- [ ] **Overview:** "AI profile" card (actors): "Generated {date} from {profile_article_count} recent articles" + `REVIEW BEFORE SHARING` chip, "AI summary" paragraph, key/value table (Actor type, Motivation, Sponsor, Targets: sectors, Targets: geographies, Malware, Tools), "Generate profile" / "Regenerate" (`manage_intel`), "Regenerate to add a summary" hint when `profile_summary` is null and the user has `manage_intel`, collapsible "Description"; non-actors: "About" with the description. Right: "Mentions by month" `BarSeries` (last two primary); "Relationships · {n} links · 3 shown" (kind chip, "{name} · {type}", `confidenceWord`) + co-mention sentence, "See all"; actors: `MindmapWidget` below.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `feat(web): entity detail header, tiles and AI profile overview`

### Task 25: Dialog and state sweep (6.11, 6.12)

**Files:**
- Modify: any Intelligence view from Tasks 15-24 that still renders ad-hoc "Loading…" text, a dialog without `DialogDescription`, or an export/write control without its permission gate (found by the greps below)

- [ ] **Sweep:** `grep -rn "Loading\.\.\.\|Loading…" apps/web/src/components/intelligence apps/web/src/components/entities` → each replaced by `StatePanel variant="loading"` (skeleton matching the card); `grep -rn "DialogContent" ...` → each Intelligence dialog has `DialogDescription`, close "×", ghost Cancel and `loading` on the primary; `grep -rn "WIB\|UTC" apps/web/src/components/intelligence apps/web/src/components/entities` → none.
- [ ] **No-access:** Needs review absent without `manage_sources`; every export hidden without `export_data`; write actions hidden or disabled with tooltip as today.
- [ ] Verify: lint + typegen/tsc + build exit 0.
- [ ] Commit `fix(web): consistent states, dialog anatomy and permission gates across Intelligence`

### Task 26: Docs, CHANGELOG and prod-upgrade notes (4.11)

**Files:**
- Modify: `docs/ARCHITECTURE.md`, `CHANGELOG.md` (extend `## [0.8.16] - 2026-11-08`), `docs/prod-upgrade/0.8.16.md`, `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md`

- [ ] **ARCHITECTURE.md (English):** PIR campaign-match cost (`include_campaigns` runs the uncached campaign pipeline, coverage counted twice), export endpoints (`/api/sr/entries/export`, `/api/iocs/export`: `export_data`, audit, CSV formula guard, 50 000 cap with `X-Export-Truncated`), entities `sort=mentions`.
- [ ] **CHANGELOG (Indonesian):** `### Ditambahkan`: halaman Intelligence mengikuti mockup (header per tab, preset + Custom, panel detail), preview jumlah artikel PIR, RFI terkait dan kampanye cocok di PIR, hitungan status RFI + pencarian, filter origin + export CSV Source reliability, export CSV IOC, catatan allowlist, ringkasan AI profil entitas + jumlah artikel, Entities diurutkan menurut sebutan 30 hari + total, parameter URL Newsroom `actor`, `industry`, `ttp`, `from`; `### Diubah`: dialog detail IOC dan drill TTP jadi panel, tab RFI default Open, kartu sinkron ATT&CK pindah ke MITRE, grid MITRE default 10 × 12; catatan: ringkasan profil baru terisi sesudah profil dibuat ulang; export IOC/SR butuh `export_data`.
- [ ] **Prod upgrade (both files):** no migration (head stays `b7d41e9a2c63`), no new env keys; optional after deploy: regenerate profiles of watched actors to fill summaries (one LLM call each, only with the operator's go).
- [ ] **Verify:** `uv run python -c "from cti_api.routers.changelog import _parse; print(_parse()[0]['version'])"` prints `0.8.16`; `uv run ruff format --check .`.
- [ ] Commit `docs(release): note the Intelligence redesign and its data changes in 0.8.16`

### Task 27: Final verification (spec 8)

- [ ] **Backend:** `uv run pytest tests/integration -k "pir or rfi or source_reliability or sr_export or ioc or fp_analytics or entities or ta_profile or articles_combined or migrations" -q`; fast suite with the known deselect; cross-cutting: client B never sees client A's RFIs in `linked_rfis` or `status_counts`; both exports 403 without `export_data` and write an audit row; `alembic heads` prints `b7d41e9a2c63`.
- [ ] **Static:** ruff check + format check; mypy; `git diff --exit-code docs/openapi.json apps/web/src/lib/api/schema.d.ts` after re-running the export and `gen:api`; `grep -n "^revision" uv.lock` prints `revision = 3`.
- [ ] **Web:** lint, typegen + tsc, build exit 0.
- [ ] **Visual (controller, local `qacve`):** the page must show, at 1440 and 1000 px, light and dark, against frames 15766, 16221, 16600, 17074, 17342, 18079, 34382, 37115, 37946, 41332, 41886, 44165 and their dark variants: every view, dialog and state; keyboard pass (pills, presets incl. Custom, heat grids, selectable lists and tables, row menus, dialogs, chip input, date field); heat cells, tier tiles and `HeroPanel` links legible in both themes; no `WIB`/`UTC`; every "Open in Newsroom" lands on a sheet whose count matches its source number; every pre-2b feature in the inventory's drop-risk sections reachable (checklist for the PR).
- [ ] Report results; no commit unless a fix was needed (then a `fix(...)` commit per fix).

## Spec coverage

| Spec section | Tasks |
|---|---|
| 2 S1, S2 | 21-25 (features kept), 26 |
| 2 D1-D4 | 12, 14 |
| 2 D5-D10 | 15, 17, 18 |
| 2 D11-D13 | 22 |
| 2 D14-D19 | 4, 9, 12, 19, 20 |
| 2 D20-D23 | 6, 7, 12, 21 |
| 2 D24-D28 | 8, 10, 12, 23, 24 |
| 3 C1-C10 | 12 (C1), 6 (C2), 1 (C3), 12/21 (C4), 23 (C5), 8/23 (C6), 10 (C7), all (C8), 15/16/19 (C9), 19 (C10) |
| 4.1 | 1, 14 |
| 4.2 | 3, 19 |
| 4.3 | 4, 19 |
| 4.4 | 5, 18 |
| 4.5 | 6, 21 |
| 4.6 | 7, 21 |
| 4.7 | 8, 23 |
| 4.8 | 9, 20 |
| 4.9 | 10, 23, 24 |
| 4.10 | 2, 13 |
| 4.11 | 26 |
| 5 | Global Constraints, 11, 27 |
| 6.0 | 12, 14 |
| 6.1-6.10 | 16, 18, 15, 19, 20, 17, 23, 24, 21, 22 |
| 6.11, 6.12 | 19-21 (per dialog), 25 |
| 6.13 | 12, 13 |
| 7 | Global Constraints (excluded items not planned) |
| 8 | 11, 27 |
| 9 | Review Focus, 8 (timing), 14 (sheet scope) |
