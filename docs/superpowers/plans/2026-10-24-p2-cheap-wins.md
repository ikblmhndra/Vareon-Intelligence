# P2 Cheap Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Structured sources skip the LLM, IOCs are stored canonical with allowlist matches flagged, CVEs move from `iocs` to `article_cves`, and article confidence comes from source grades instead of the LLM.

**Architecture:** `ScraperMeta` declares `content_kind`/`default_relevance`; the enrich task reads them from the registry and the pipeline skips classify and TTP for `always`. One `canonical()` function normalises IOC values at every writer; allowlist matching moves out of the extractor into a flagging step at upsert. A new `article_cves` table replaces CVE IOCs behind two repo methods. Source grades get an `origin`, startup fills defaults per `content_kind`, and persist computes `confidence_score` deterministically. Three migrations carry the data.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + hand-written Alembic, Celery, FastAPI + Pydantic, Next.js 16 / React 19 (Base UI shadcn), pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-10-24-p2-cheap-wins-design.md`

## Global Constraints

- Branch `claude/p2-cheap-wins`; one PR; release **0.8.6**; merge into `origin/Dev` and test on the dev instance before the PR to `main`; deploy only after the user's explicit approval.
- Commit messages English, conventional, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Comments and docstrings match the surrounding language (mostly Indonesian); docs English; `CHANGELOG.md` Indonesian.
- Ruff line length 100; `uv run mypy packages/cti-core/src packages/cti-scraper/src` clean.
- No new `.env` keys.
- `content_kind` values (exact): `advisory`, `kev`, `exploit`, `vendor_research`, `news`, `vendor_marketing`, `social`; default `news`. `default_relevance` values: `always`, `classify`; default `classify`. `always` only with `advisory`, `kev`, `exploit`; set only on `cisa_kev` (`kev`), `exploitdb` (`exploit`), `cis` (`advisory`).
- Default grades: `kev` A1, `advisory` A2, `exploit` B2, `vendor_research` B2, `news` C3, `vendor_marketing` C4, `social` D4.
- Suppression reason format: `allowlist:<type>:<entry> (infrastructure-abuse)`.
- After API schema changes: `uv run python tools/export_openapi.py`, then `cd apps/web && pnpm run gen:api` (node via fnm: `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"`).
- Known local failures to deselect: `tests/contract/test_golden.py::test_golden_trendmicro`, `tests/integration/test_backfill_cve_mirror.py::test_zip_source_and_limit`.
- Alembic head before this work: `c4e7a2b9d1f0`.

## Review Focus

- URL with mixed-case path (`HXXPS://Evil[.]com/Payload.EXE?A=B`): host and scheme lowercase, path and query keep their case. Test in Task 3.
- Allowlist suffix match must respect label boundaries: `gofile.io` matches `store1.gofile.io` but not `notgofile.io` or `gofile.io.evil.net`. Test in Task 4.
- Merging twins whose `ioc_feedback`, `ioc_tags` or `ioc_threat_actors` rows would collide on a unique constraint: the duplicate link is dropped, not an error, and counts are summed once. Test in Task 6.
- Replay of an old rejected row whose `scraper_id` no longer exists, or is `None`: classify runs as before. Test in Task 2.
- A source graded by an analyst under different letter case (`mandiant` vs `Mandiant`): startup does not add a default row and never overwrites the analyst grade. Test in Task 7.

---

### Task 1: `content_kind` and `default_relevance` on every scraper

**Files:**
- Modify: `packages/cti-scraper/src/cti_scraper/base.py` (`ScraperMeta`)
- Modify: every scraper file under `scrapers/src/cti_scrapers/feeds/` and `collectors/` that declares a `ScraperMeta`
- Test: `tests/contract/test_scraper_content_kind.py`

**Interfaces:**
- Produces: `ContentKind = Literal["advisory", "kev", "exploit", "vendor_research", "news", "vendor_marketing", "social"]`, `Relevance = Literal["always", "classify"]` in `cti_scraper.base`; `ScraperMeta.content_kind: ContentKind = "news"`, `ScraperMeta.default_relevance: Relevance = "classify"`.

- [ ] **Step 1: Write failing contract tests** in `tests/contract/test_scraper_content_kind.py`:
  - `test_always_only_for_structured_kinds`: for every scraper in `registry.all_scrapers()`, `meta.default_relevance == "always"` implies `meta.content_kind in {"advisory", "kev", "exploit"}`.
  - `test_always_set_exactly_on_structured_sources`: the set of ids with `always` equals `{"cisa_kev", "exploitdb", "cis"}`, with kinds `kev`, `exploit`, `advisory`.
  - `test_every_scraper_declares_content_kind`: parse each scraper source file and assert `content_kind=` appears in its `ScraperMeta(...)` call (explicit, not the default).
- [ ] **Step 2: Run** `uv run pytest tests/contract/test_scraper_content_kind.py -q` — expect FAIL (attribute missing).
- [ ] **Step 3: Add the two fields** with Indonesian docstrings (what each value means; `always` = no classify and no TTP, see spec 2.2).
- [ ] **Step 4: Set `content_kind` on every scraper.** Rule: news outlets and aggregators (`hackernews`, `cybersecnews`, `bleepcomp`, `darkreading`, `ecrime`, and any other id whose source is a news site) → `news`; X/Twitter collectors (`monitor_x`, `tweet_alerts` and similar) → `social`; `cisa_kev` → `kev`; `exploitdb` → `exploit`; `cis`, `cisa` and vendor PSIRT/advisory feeds → `advisory`; techstack/package feeds that do not yield `ArticleItem` → `advisory`; vendor and researcher blogs → `vendor_research`. Add `default_relevance="always"` on `cisa_kev`, `exploitdb`, `cis` only. List every id with its chosen kind in the report.
- [ ] **Step 5: Run** the new tests and `uv run pytest tests/contract -q --deselect tests/contract/test_golden.py::test_golden_trendmicro` — expect PASS.
- [ ] **Step 6: Commit** `feat(scrapers): declare content kind and default relevance per scraper`.

### Task 2: Pipeline skips classify and TTP for `always`

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/pipeline.py` (`run_pipeline`)
- Modify: `apps/worker/src/cti_worker/tasks/enrich.py` (`enrich.article`)
- Test: `tests/unit/test_pipeline_tier0.py`

**Interfaces:**
- Consumes: `ScraperMeta.content_kind`, `ScraperMeta.default_relevance` (Task 1); `cti_scraper.registry.get(scraper_id)` (raises on unknown id).
- Produces: `run_pipeline(*, title, url, posted_on, source, scraper_id, session, alert=True, content_kind: str | None = None, default_relevance: str = "classify") -> PipelineOutcome`; worker helper `_relevance_for(scraper_id: str | None) -> tuple[str | None, str]` returning `(content_kind, default_relevance)`, `(None, "classify")` for `None` or unknown ids.

- [ ] **Step 1: Write failing tests** (patch `classify`, `fetch_text`, `extract_ttps` with call recorders; reuse the fakes style of existing pipeline unit tests):
  - `test_always_skips_classify_and_ttp`: `default_relevance="always", content_kind="kev"` → `classify` and `extract_ttps` not called; outcome accepted; the persisted `raw_enrichment["classify"]` equals `{"skipped": "default_relevance=always", "content_kind": "kev"}`.
  - `test_classify_default_unchanged`: default arguments → `classify` called once.
  - `test_relevance_for_unknown_or_none`: `_relevance_for(None) == (None, "classify")`; `_relevance_for("no_such_scraper") == (None, "classify")`; `_relevance_for("cisa_kev") == ("kev", "always")`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_pipeline_tier0.py -q` — expect FAIL.
- [ ] **Step 3: Implement**: for `always` build `ClassifyResult(related_cyber=True, reason=f"structured source: {content_kind}", audit={...})` and skip `_extract_ttps_or_empty` (empty `TtpResult`); the task calls `_relevance_for(scraper_id)` and passes both values.
- [ ] **Step 4: Run** the test file and `uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro` — expect PASS.
- [ ] **Step 5: Commit** `feat(enrich): structured sources skip classify and TTP extraction`.

### Task 3: Canonical IOC values at every writer

**Files:**
- Create: `packages/cti-core/src/cti_core/ioc/canonical.py`
- Modify: `packages/cti-enrich/src/cti_enrich/stages/persist.py` (IOC loop), `apps/api/src/cti_api/services/newsletter.py` (`_IOC_TYPE_MAP`, `write_article_findings`), `packages/cti-scraper/src/cti_scraper/sinks.py` (`_ioc_feed_sink`)
- Modify: remove `url_with_path` from `apps/api/src/cti_api/services/stix.py` and `apps/api/src/cti_api/services/confidence.py` maps
- Test: `tests/unit/test_ioc_canonical.py`

**Interfaces:**
- Produces: `canonical(ioc_type: str, value: str) -> str` (rules in spec 3.1, unknown types returned stripped); `CANONICAL_RULES_VERSION = 1` (referenced by the Task 6 migration docstring only).

- [ ] **Step 1: Write failing tests**, one per row of spec 3.1, including: `canonical("ip", "1[.]2[.]3(.)4") == "1.2.3.4"`; `canonical("domain", "Evil[.]COM.") == "evil.com"`; `canonical("domain", "a[dot]b[.]c") == "a.b.c"`; `canonical("url", "HXXPS://Evil[.]com/Payload.EXE?A=B") == "https://evil.com/Payload.EXE?A=B"`; `canonical("url", "fxp://h[.]x/a") == "ftp://h.x/a"`; `canonical("email", "Bob[@]Ex[.]Com") == "bob@ex.com"`; `canonical("email", "bob[at]ex[.]com") == "bob@ex.com"`; `canonical("sha256", "ABCDEF") == "abcdef"`; idempotence `canonical(t, canonical(t, v)) == canonical(t, v)` for all samples. Also `test_writers_store_canonical`: persist with `ioc_data={"domains": ["Evil[.]com"], "urls_with_path": ["hxxp://a[.]b/x"]}` calls `IOCRepo.upsert` with `("domain", "evil.com")` and `("url", "http://a.b/x")`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_ioc_canonical.py -q` — expect FAIL.
- [ ] **Step 3: Implement** `canonical()` reusing the defang separators from `cti_core.ioc.extractor` (import the compiled regexes; do not duplicate them); call it in the three writers; map `urls_with_path` to `url` in the newsletter map.
- [ ] **Step 4: Run** the test file plus `uv run pytest tests/unit -q -k "ioc or newsletter or persist or deepdark"` — expect PASS.
- [ ] **Step 5: Commit** `feat(ioc): store IOC values in canonical form`.

### Task 4: Allowlist flags instead of dropping, with a curated seed

**Files:**
- Create: `packages/cti-core/src/cti_core/ioc/allowlist.py`, `packages/cti-core/src/cti_core/ioc/allowlist_seed.txt`
- Modify: `packages/cti-core/src/cti_core/ioc/extractor.py` (`_filter_iocs` keeps private-IP and self-domain drops only), `packages/cti-core/src/cti_core/db/repositories/ioc.py` (`upsert` gets `suppression_reason`), `packages/cti-enrich/src/cti_enrich/stages/extract_iocs.py`, `packages/cti-enrich/src/cti_enrich/stages/persist.py`, `apps/api/src/cti_api/services/newsletter.py`
- Test: `tests/unit/test_ioc_allowlist_match.py`, `tests/integration/test_ioc_allowlist_flag.py`

**Interfaces:**
- Consumes: `canonical()` (Task 3); `get_ioc_allowlist` (`repositories/ioc_reference.py`) returning `{url_domains, email_domains, ips}`.
- Produces: `allowlist_match(ioc_type: str, canonical_value: str, allowlist: dict[str, set[str]]) -> str | None` returning the reason string `allowlist:<type>:<entry> (infrastructure-abuse)` or `None`; `load_seed() -> list[str]` (lowercased domains from `allowlist_seed.txt`, `#` comments ignored); `IOCRepo.upsert(..., suppression_reason: str | None = None)` and the async twin: a non-None reason sets `auto_suppressed = True` and `suppression_reason` on insert and on an existing row that is not yet suppressed.

- [ ] **Step 1: Write failing unit tests**: `allowlist_match("domain", "store1.gofile.io", {"url_domains": {"gofile.io"}, ...})` returns `"allowlist:url_domain:gofile.io (infrastructure-abuse)"`; `"notgofile.io"` and `"gofile.io.evil.net"` return `None`; URL host suffix match (`"https://cdn.gofile.io/x"`); email domain suffix match; IP exact match only; `load_seed()` has between 120 and 200 entries, all lowercase, no duplicates, includes `gofile.io`; extractor no longer drops allowlisted values but still drops `10.0.0.1` and self-domain URLs.
- [ ] **Step 2: Write failing integration test** `test_allowlisted_ioc_is_stored_flagged`: run persist with an IOC on an allowlisted domain → row exists with `auto_suppressed is True` and the reason string; a non-matching IOC has `auto_suppressed is False`.
- [ ] **Step 3: Run** both files — expect FAIL.
- [ ] **Step 4: Implement**; write the seed file (~150 domains: major SaaS, file sharing incl. `gofile.io`, `ably.io`, CDNs, cloud providers, code hosting incl. `github.com`, security vendors); persist and newsletter compute `allowlist_match` per canonical value and pass the reason to `upsert`.
- [ ] **Step 5: Run** the tests and `uv run pytest tests/unit -q -k ioc` — expect PASS.
- [ ] **Step 6: Commit** `feat(ioc): flag allowlisted IOCs instead of dropping them, with a curated seed`.

### Task 5: `article_cves` replaces CVE IOCs

**Files:**
- Create: `packages/cti-core/src/cti_core/db/models/article_cve.py`, `packages/cti-core/src/cti_core/db/repositories/article_cve.py`, `alembic/versions/d1a5c8e3f2b7_article_cves.py` (revises `c4e7a2b9d1f0`)
- Modify: `packages/cti-core/src/cti_core/db/models/__init__.py`; `persist.py` and `newsletter.py` (`cves` go to `article_cves`, removed from both IOC type maps); `repositories/ioc.py` (`cve` out of `_VALID_TYPES`, `cve_ids_by_article` removed); `services/newsletter_suggestion.py`; `services/campaign.py` (`_build_ioc_map`, `cve_ids` from `article_cves`); `services/confidence.py` (`cve` half-life removed)
- Test: `tests/integration/test_article_cves.py`

**Interfaces:**
- Produces: model `ArticleCve` (`article_cves`: `article_id` FK cascade, `cve_id` varchar(20), `in_title` bool, `first_seen_at` timestamptz default now; PK `(article_id, cve_id)`; index `ix_article_cves_cve_id`); sync `ArticleCveRepo(session).add_many(article_id: int, cve_ids: Iterable[str], title: str) -> None` (uppercase, insert-ignore); async `AsyncArticleCveRepo(session).add_many(...)` and `cve_ids_by_article(article_ids: Sequence[int]) -> dict[int, set[str]]`; migration constants `COPY_CVE_SQL`, `DELETE_CVE_IOCS_SQL`.

- [ ] **Step 1: Write failing integration tests**:
  - `test_persist_writes_article_cves_not_iocs`: persist with `ioc_data={"cves": ["cve-2026-1234"]}` and a title containing `CVE-2026-1234` → one `article_cves` row (`CVE-2026-1234`, `in_title=True`), no `iocs` row of type `cve`; persisting again adds no row.
  - `test_cve_ids_by_article_reads_new_table`.
  - `test_campaign_cve_ids_from_article_cves`: two articles in one campaign with CVEs in `article_cves` → the campaign dict's `cve_ids` contains both, same shape as before.
  - `test_migration_moves_cve_iocs`: seed a `cve` IOC linked to two articles through `ioc_sources` (one duplicate link) and one IOC of type `ip`; execute `COPY_CVE_SQL` then `DELETE_CVE_IOCS_SQL` (load the migration with `importlib.util.spec_from_file_location`) → two `article_cves` rows, no `cve` IOC, the `ip` IOC untouched.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** model, repos, migration (create table and index, copy, delete; downgrade drops the table only), writers and readers.
- [ ] **Step 4: Run** the file, `tests/integration/test_migrations_match_models.py`, and `uv run pytest tests/integration -q -k "campaign or newsletter or ioc"` — expect PASS (update snapshots only where they list a `cve` IOC type; say so in the commit body).
- [ ] **Step 5: Commit** `feat(cve): store article CVEs in article_cves instead of IOCs`.

### Task 6: Migration for canonical IOCs and allowlist flags

**Files:**
- Create: `alembic/versions/e7b2d4a9c6f1_canonical_iocs_allowlist_seed.py` (revises `d1a5c8e3f2b7`)
- Test: `tests/integration/test_canonical_ioc_migration.py`

**Interfaces:**
- Consumes: the seed file contents (copied into the migration as a frozen tuple, not read at run time); the canonical rules (frozen copy inside the migration, docstring cites `CANONICAL_RULES_VERSION = 1`).
- Produces: migration functions `canonicalize_and_merge(conn) -> dict[str, int]` (counts `merged`, `rewritten`) and `seed_and_flag_allowlist(conn) -> dict[str, int]` (counts `seeded`, `flagged`), both callable from tests.

- [ ] **Step 1: Write failing integration tests**:
  - `test_merge_defanged_twin`: rows `("domain", "evil[.]com")` (id 1, seen 2, tp 1, first_seen D1) and `("domain", "evil.com")` (id 2, seen 3, fp 1, first_seen D0) with one `ioc_sources` row each → one row id 1, value `evil.com`, seen 5, tp 1, fp 1, first_seen D0, two sources.
  - `test_merge_skips_colliding_links`: both twins carry the same tag and feedback by the same user → merge succeeds, one tag link, one feedback row.
  - `test_case_duplicates_merge`: `("sha256", "ABC")` + `("sha256", "abc")` → one row `abc`.
  - `test_url_path_case_kept`: `("url", "hxxps://A[.]com/X")` → `https://a.com/X`.
  - `test_seed_and_flag`: an existing IOC `("domain", "store1.gofile.io")` → flagged with the reason format; seed rows present with `added_by = "seed"`; running `seed_and_flag_allowlist` twice inserts nothing new.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** in Python inside the migration using `op.get_bind()` and plain SQL; merge by lowest id; for link tables use `INSERT ... SELECT ... ON CONFLICT DO NOTHING` then delete the loser's links; downgrade is a no-op with a docstring saying the merge is irreversible.
- [ ] **Step 4: Run** the file and `tests/integration/test_migrations_match_models.py` — expect PASS.
- [ ] **Step 5: Commit** `feat(ioc): migrate IOCs to canonical form and seed the allowlist`.

### Task 7: Default source grades and deterministic article confidence

**Files:**
- Create: `packages/cti-core/src/cti_core/confidence.py`, `alembic/versions/f3c9e1b5a7d2_source_reliability_origin.py` (revises `e7b2d4a9c6f1`)
- Modify: `packages/cti-core/src/cti_core/db/models/` (source reliability model: `origin`), `packages/cti-core/src/cti_core/db/repositories/source_reliability.py` (sync `SourceReliabilityRepo.get_by_name_ci`, async `ensure_defaults`), `apps/api/src/cti_api/services/confidence.py` (re-export `compute_score`; recompute writes the column), `apps/api/src/cti_api/main.py` (`bootstrap_reference_rows`), `apps/api/src/cti_api/services/source_reliability.py` or its router (edit sets `origin='analyst'` and enqueues recompute), `packages/cti-enrich/src/cti_enrich/stages/persist.py` (score), `packages/cti-core/src/cti_core/celery_client.py` (`send_recompute_source`), `apps/worker/src/cti_worker/tasks/periodic.py` or a new `tasks/confidence.py` + `celery_app.py` import
- Test: `tests/unit/test_default_grades.py`, `tests/integration/test_source_grade_defaults.py`

**Interfaces:**
- Consumes: `ScraperMeta.content_kind` (Task 1); registry (API process already imports it for `/scrapers`).
- Produces: `cti_core.confidence.compute_score(reliability_grade: str | None, credibility_code: str | None, ttp_count: int, ta_count: int) -> int` (moved unchanged); `DEFAULT_GRADES: dict[str, tuple[str, str]]` per Global Constraints; `AsyncSourceReliabilityRepo.ensure_defaults(sources: Mapping[str, str]) -> list[str]` (source name → content_kind; returns names it inserted; case-insensitive existence check; `analyst_name="system"`, `origin="default"`); Celery task `confidence.recompute_source(source_name: str)` on the maintenance queue writing `articles.confidence_score` for that source (skipping articles whose `overrides` has `confidence_score`); `send_recompute_source(source_name: str) -> None`.

- [ ] **Step 1: Write failing tests**:
  - Unit `test_default_grades_table`: exact values from Global Constraints; `compute_score("B", "2", 0, 0) == 80` and `compute_score(None, None, 2, 1) == 70` (unchanged formula).
  - Integration `test_ensure_defaults_respects_analyst_rows`: an analyst row `Mandiant` exists → `ensure_defaults({"mandiant": "vendor_research", "BleepingComputer": "news"})` inserts only `BleepingComputer` (C3, `origin='default'`), leaves `Mandiant` untouched, returns `["BleepingComputer"]`.
  - Integration `test_persist_confidence_from_grade`: source row `B2` → a persisted article with 1 TTP and 0 actors gets `confidence_score == 85`; an ungraded source with 0 TTP gets 50.
  - Integration `test_recompute_source_writes_column_not_overrides`.
  - Integration `test_editing_default_row_marks_analyst`; the source reliability list response includes `origin` per row (schema field `origin: Literal["default", "analyst"]`; regenerate `docs/openapi.json` and `schema.d.ts`).
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement**; bootstrap builds `{meta.source: meta.content_kind}` from the registry, calls `ensure_defaults` and, after commit, `send_recompute_source` for each inserted name (sending failures are logged, never block startup).
- [ ] **Step 4: Run** the tests, `tests/integration/test_migrations_match_models.py`, and the existing confidence/source-reliability tests (`uv run pytest -q -k "confidence or source_reliability"`) — expect PASS.
- [ ] **Step 5: Commit** `feat(confidence): default source grades per kind and deterministic article scores`.

### Task 8: Suppressed IOCs leave exports and counts

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/ioc.py` (`list_filtered(include_suppressed: bool = False)`, `get_stats`, `list_by_article_ids`, `list_first_seen_on`, `count_first_seen_by_type_between`), `packages/cti-core/src/cti_core/db/repositories/dashboard.py` (`pending_fp_queue`, `pending_fp_count`), `apps/api/src/cti_api/routers/iocs.py` (`include_suppressed` query param), `apps/api/src/cti_api/services/stix.py` (IOC export never includes suppressed)
- Modify: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts` (regenerated)
- Test: `tests/integration/test_ioc_suppressed_exclusion.py`

**Interfaces:**
- Consumes: `auto_suppressed` set by Task 4/6.
- Produces: `GET /api/iocs?include_suppressed=true|false` (default false); every consumer listed in spec 3.4 excludes suppressed rows.

- [ ] **Step 1: Write failing tests**: seed one suppressed and one normal IOC linked to an article → `GET /api/iocs` returns 1, with `include_suppressed=true` 2; `/api/iocs/stats` counts 1; `/api/stix/iocs` contains only the normal value; campaign IOC list for the article contains only the normal one; recap IOC count and FP queue exclude it.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** the filters; regenerate the API contract.
- [ ] **Step 4: Run** the file plus `uv run pytest tests/integration -q -k "ioc or stix or recap or campaign or exec"` — expect PASS.
- [ ] **Step 5: Commit** `feat(ioc): keep suppressed IOCs out of exports, counts and campaigns`.

### Task 9: Admiralty code on article shapes

**Files:**
- Modify: `apps/api/src/cti_api/schemas/article.py` (`ArticleOut`), the service that builds `GET /api/articles` items
- Modify: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`
- Test: `tests/integration/test_article_grade_fields.py`

**Interfaces:**
- Consumes: `AsyncSourceReliabilityRepo.get_all_ratings()` (one query per request).
- Produces: `ArticleOut.admiralty_code: str | None` (e.g. `"B2"`) and `ArticleOut.grade_origin: Literal["default", "analyst"] | None`.

- [ ] **Step 1: Write failing test**: article from a source with a `default` `C3` row → item has `admiralty_code == "C3"`, `grade_origin == "default"`; ungraded source → both `None`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement**; regenerate the contract.
- [ ] **Step 4: Run** the test and `uv run pytest tests/integration -q -k "article"` — expect PASS.
- [ ] **Step 5: Commit** `feat(api): source grade on article items`.

### Task 10: Web: defanged IOCs, suppressed filter, grade chips, default labels

**Files:**
- Create: `apps/web/src/lib/intelligence/defang.ts`
- Modify: `apps/web/src/components/intelligence/ioc/ioc-table.tsx` (types list without `cve` and `url_with_path`, defanged display, "Suppressed" badge, include-suppressed toggle), `ioc-detail-dialog.tsx` (defanged display and copy), `apps/web/src/lib/intelligence/ioc-style.ts` (drop `cve`), `apps/web/src/components/exec/role-gated-panels.tsx` (defanged display), `apps/web/src/components/dashboard/overview-cards.tsx` and `apps/web/src/components/newsroom/front-section.tsx` (chip `"<admiralty_code> · <confidence_score>"` with tooltip `"Source grade <code> (default|analyst)"`, falls back to `"Score <n>"` without a code), the source reliability page component (label `default` rows)

**Interfaces:**
- Consumes: `include_suppressed`, `auto_suppressed`, `suppression_reason` (Task 8); `admiralty_code`, `grade_origin` (Task 9); source reliability `origin` (Task 7; regenerate types if the list endpoint exposes it).
- Produces: `defang(type: string, value: string): string` — `.` → `[.]` in hosts/IPs/emails, `http` → `hxxp`, `@` → `[@]`; hashes unchanged.

- [ ] **Step 1: Implement** the helper and the component changes following existing patterns (Base UI shadcn, theme tokens, no backdrop-blur, hooks before early returns, no impure calls in render).
- [ ] **Step 2: Verify** in `apps/web`: `./node_modules/.bin/next typegen && ./node_modules/.bin/tsc --noEmit && ./node_modules/.bin/eslint src` — clean.
- [ ] **Step 3: Commit** `feat(web): defanged IOCs, suppressed filter and source grade chips`.

### Task 11: Release 0.8.6, verification, Dev

**Files:**
- Modify: version strings (root and package `pyproject.toml`, each `__version__`, `apps/web/package.json`), `uv.lock` (member versions only, keep `revision = 3`), `docs/openapi.json`, `tests/integration/__snapshots__/test_health_router_snapshot.ambr`, `CHANGELOG.md`
- Modify: `docs/LLM_ASSIST_REDESIGN.md` and `docs/TARGET_ARCHITECTURE.md` progress sections; `docs/ARCHITECTURE.md` (IOC canonical form, allowlist flag, `article_cves`)

- [ ] **Step 1: Bump** to 0.8.6 and add `## [0.8.6] - <date>` (Indonesian) with upgrade notes: three migrations, the IOC merge is irreversible (deploy takes a backup), CVE IOCs move to `article_cves`, allowlist now flags, default source grades appear and articles are rescored once after the first start, no new `.env` keys.
- [ ] **Step 2: Verify**: ruff check + format check; mypy; `uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro`; `uv run pytest tests/integration -q --deselect tests/integration/test_backfill_cve_mirror.py::test_zip_source_and_limit`; web `tsc`, `eslint .`, `next build`; `export_openapi.py` produces no diff.
- [ ] **Step 3: Update** the progress sections (P2 done in 0.8.6 except what moved out of scope).
- [ ] **Step 4: Commit** `chore(release): 0.8.6 - P2 cheap wins`; push; merge into `origin/Dev` through a temporary worktree (Dev's tree equals main minus nothing new; resolve version conflicts to the branch side).
- [ ] **Step 5: Deploy to dev only after the user approves**; check the four success criteria from spec section 1 read-only on dev; open the PR to `main`.
