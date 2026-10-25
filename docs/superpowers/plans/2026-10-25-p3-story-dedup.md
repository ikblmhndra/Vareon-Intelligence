# P3 story dedup at ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group articles into stories at ingest with deterministic keys, so a follow-up article of a known story inherits the lead's classification and skips the classify and TTP LLM calls.

**Architecture:** A pure resolver (`cti_enrich.story`) matches a new article against stories of the last 72 h by CVE keys, exact title, then cross-source TF-IDF title similarity. `run_pipeline` fetches the text before classify, resolves in a short separate session under an advisory lock, and inherits `stories.classify` when set. Stories live in a new `stories` table; `articles` gains `story_id` and `story_match`.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic (hand-written migration), Postgres `text[]` + GIN, scikit-learn TF-IDF, Celery, FastAPI, Next.js 16 (Base UI shadcn).

**Spec:** `docs/superpowers/specs/2026-10-25-p3-story-dedup-design.md`

## Global Constraints

- Branch `claude/p3-story-dedup-363be8`, already rebased on P2 `48f2600`; do not edit P2-only behaviour beyond what a task names.
- Migration `down_revision = "f3c9e1b5a7d2"`.
- Settings defaults: `STORY__ENABLED=true`, `STORY__WINDOW_HOURS=72`, `STORY__MAX_AGE_DAYS=7`, `STORY__MAX_KEY_CVES=5`, `STORY__CVE_OVERLAP=0.5`, `STORY__TITLE_SIMILARITY=0.5`. No required `.env` key is added.
- `STORY__ENABLED=false` must reproduce the 0.8.6 pipeline exactly (classify before fetch, no story writes).
- Alerts stay per article. TTPs are never copied to follow-up rows.
- Tier 0 (`default_relevance="always"`) members never fill `stories.classify`.
- `scikit-learn>=1.5` added to `packages/cti-enrich/pyproject.toml`; `uv lock` must not add a new package.
- Comments and docstrings Indonesian, docs English, CHANGELOG Indonesian; commit messages English conventional ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Fast suite: `uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro` (plus the other known local failure in memory, deselected, not diagnosed).
- No write on dev, no push, no merge to `origin/Dev`, no model download without the user's explicit approval.

## Review Focus

1. **Wave burst under concurrency**: two articles of a new story enriched at the same time must produce one story, not two. Pinned by `test_concurrent_resolve_creates_one_story` (Task 2).
2. **Lead parked by an LLM outage, then replayed**: the replay must re-attach to its own empty story, not create a second one. Pinned by `test_replay_reuses_empty_story` (Task 4).
3. **Roundup and digest articles** (more than 5 CVEs, "Week in security") must not become the hub that pulls unrelated stories together. Pinned by `test_roundup_has_no_cve_key` (Task 3) and the replay assertions.
4. **Same-source serial titles** (CIS "Multiple Vulnerabilities in ...", Asec monthly reports) must not merge on title. Pinned by `test_title_rule_requires_other_source` (Task 3) and the replay assertion on Asec reports.
5. **Empty fetch** (paywall, timeout): resolver must still run on title-only CVEs and the pipeline must not crash. Pinned by `test_empty_fetch_uses_title_cves` (Task 4).

---

### Task 1: `Settings.story`

**Files:**
- Modify: `packages/cti-core/src/cti_core/config.py` (new `StorySettings(_StrictModel)`, field `story` on `Settings` next to `cve_mirror`)
- Modify: `.env.example`, `.env.prod.template` (commented `STORY__*` block with the defaults)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `StorySettings` with `enabled: bool = True`, `window_hours: int = 72`, `max_age_days: int = 7`, `max_key_cves: int = 5`, `cve_overlap: float = 0.5`, `title_similarity: float = 0.5`; reached as `get_settings().story`.

- [ ] **Step 1: Write failing test** `test_story_settings_defaults`: `Settings(_env_file=None, database=..., auth=...)` (reuse the file's existing minimal fixture) has `story.enabled is True`, `story.window_hours == 72`, `story.max_age_days == 7`, `story.max_key_cves == 5`, `story.cve_overlap == 0.5`, `story.title_similarity == 0.5`; and `STORY__ENABLED=false` in env gives `enabled is False`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_config.py -q` — expect FAIL (no attribute `story`).
- [ ] **Step 3: Implement** the model with an Indonesian docstring per field pointing to spec 3.3; add the env blocks.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_config.py tests/unit/test_env_prod_template.py -q` — expect PASS.
- [ ] **Step 5: Commit** `feat(config): story dedup settings`.

### Task 2: `stories` table, `articles.story_id`, `StoryRepo`

**Files:**
- Create: `packages/cti-core/src/cti_core/db/models/story.py`, `packages/cti-core/src/cti_core/db/repositories/story.py`, `alembic/versions/<rev>_stories.py`
- Modify: `packages/cti-core/src/cti_core/db/models/__init__.py`, `packages/cti-core/src/cti_core/db/models/article.py` (`story_id`, `story_match`)
- Test: `tests/integration/test_story_repo.py`, `tests/integration/test_migrations_match_models.py` (existing, must pass)

**Interfaces:**
- Produces model `Story` with columns exactly as spec section 5; `Article.story_id: Mapped[int | None]`, `Article.story_match: Mapped[str | None]` (varchar 20).
- Produces dataclasses in `cti_core/db/repositories/story.py` (pure data, reused by the resolver):
  - `StoryMember(title: str, source: str)`
  - `StoryCandidate(id: int, cve_ids: frozenset[str], first_seen_at: datetime, last_seen_at: datetime, members: list[StoryMember], has_classify: bool)` — `members` includes the story's own `title` with the lead's source when no article is attached yet.
- Produces `StoryRepo(session)` (sync):
  - `lock() -> None` — `pg_advisory_xact_lock(7_311_002, 0)`; docstring notes the namespace next to `_URL_LOCK_NAMESPACE = 7_311_001`.
  - `candidates(now: datetime, *, window_hours: int, max_age_days: int) -> list[StoryCandidate]`
  - `create(*, title: str, source: str, cve_ids: set[str], now: datetime) -> int` — `article_count=0`, `source_count=0`; stores `source` in `lead_source` so the empty story has one member.
  - `get_classify(story_id: int) -> dict | None`
  - `attach(story_id: int, *, article_id: int, source: str, cve_ids: set[str], now: datetime, classify: dict | None) -> None` — single `UPDATE`: `article_count + 1`, `source_count` recomputed as `count(DISTINCT source)` over `articles WHERE story_id`, `last_seen_at = greatest(...)`, `cve_ids` union (`array(SELECT DISTINCT unnest(cve_ids || :new))`), `lead_article_id = coalesce(lead_article_id, :article_id)`, `classify = coalesce(classify, :classify)`.
  - `discard_if_empty(story_id: int) -> bool`
  - `purge_empty(older_than: datetime) -> int`
- Produces `AsyncStoryRepo(session)`: `counts(ids: Sequence[int]) -> dict[int, tuple[int, int]]` (article_count, source_count) and `stats_since(since: datetime) -> StoryStats(new_stories: int, followups: int, inherited: int)` for Tasks 7.

- [ ] **Step 1: Write failing integration tests** in `tests/integration/test_story_repo.py`:
  - `test_create_then_candidates`: create at `now`, `candidates(now + 1h)` returns it with `members == [StoryMember(title, source)]`, `has_classify is False`; `candidates(now + 73h)` is empty; a story with `first_seen_at = now - 8d` and `last_seen_at = now - 1h` is excluded.
  - `test_attach_updates_counts`: two articles from sources "A" and "A" then "B" attached → `article_count == 3`, `source_count == 2`, `cve_ids` is the union, `lead_article_id` is the first article, `classify` keeps the first non-null value.
  - `test_discard_if_empty` and `test_purge_empty` (only stories with `article_count = 0` and `created_at < older_than` go).
  - `test_concurrent_resolve_creates_one_story`: two threads with their own `sync_session()`, each `lock()`, `candidates()`, `create()` only if no candidate has the same title, commit → exactly one row.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_story_repo.py -q` — expect FAIL.
- [ ] **Step 3: Implement** model, repo, and migration (create `stories` with GIN on `cve_ids` and btree on `last_seen_at`; add `articles.story_id` FK `ON DELETE SET NULL` + index, `articles.story_match`; `stories.lead_article_id` FK `ON DELETE SET NULL`; downgrade drops columns and table).
- [ ] **Step 4: Run** the new file and `uv run pytest tests/integration/test_migrations_match_models.py -q` — expect PASS.
- [ ] **Step 5: Commit** `feat(story): stories table and repository`.

### Task 3: Pure resolver, TF-IDF similarity, replay fixture

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/story/__init__.py`, `.../story/similarity.py`, `.../story/resolver.py`
- Create: `tests/fixtures/story_replay/dev_2026-10.json`
- Modify: `packages/cti-enrich/pyproject.toml` (`scikit-learn>=1.5`), `uv.lock`
- Test: `tests/unit/test_story_resolver.py`, `tests/unit/test_story_replay.py`

**Interfaces:**
- Consumes: `StoryCandidate`, `StoryMember` (Task 2), `StorySettings` (Task 1).
- Produces:
  - `similarity.title_similarity(query: str, titles: list[str]) -> list[float]` — TF-IDF (`stop_words="english"`, `token_pattern=r"(?u)\b[\w-]{2,}\b"`, `sublinear_tf=True`) fitted on `titles + [query]`; cosine of `query` against each title; `[]` for empty `titles`; `[0.0]*n` when the vocabulary is empty (catch `ValueError`).
  - `resolver.normalize_title(title: str) -> str` — lowercase, `re.sub(r"\W+", " ")`, strip.
  - `resolver.ArticleKeys(title: str, source: str, cve_ids: frozenset[str], at: datetime)`
  - `resolver.Match(story_id: int, rule: Literal["cve", "title_exact", "title"])`
  - `resolver.key_cves(cve_ids: Iterable[str], max_key_cves: int) -> frozenset[str]` — uppercase; empty set when more than `max_key_cves`.
  - `resolver.resolve(keys: ArticleKeys, candidates: list[StoryCandidate], cfg: StorySettings) -> Match | None` — rules exactly spec 3.2 in order; window filter applied again here (`last_seen_at >= at - window_hours`, `first_seen_at >= at - max_age_days`) so the replay can feed all stories.

- [ ] **Step 1: Write failing unit tests** in `tests/unit/test_story_resolver.py` (build candidates by hand, `cfg = StorySettings()`):
  - `test_cve_rule_majority_overlap`: keys `{A, B}`, story `{A, C}` → `Match(id, "cve")`; keys `{A, B, D}`, story `{A}` → `None` via CVE (1/3 < 0.5).
  - `test_cve_tie_break`: two stories overlap 1 and 2 → the overlap-2 story; equal overlap → later `last_seen_at`.
  - `test_roundup_has_no_cve_key`: `key_cves` of 6 ids is empty, so a 6-CVE article whose title is unrelated gets `None`.
  - `test_exact_title_any_source`: same normalised title, same source → `"title_exact"`.
  - `test_title_rule_requires_other_source`: "2026-117: Multiple Vulnerabilities in Google Chrome Could Allow for Arbitrary Code Execution" vs "2026-114: Multiple Vulnerabilities in Adobe Products Could Allow for Arbitrary Code Execution", both source "Cis" → `None`; same pair with different sources and similarity >= 0.5 → `"title"`.
  - `test_cve_veto_blocks_title`: story `cve_ids={CVE-2026-88771}`, article title near-identical, article keys `{CVE-2026-88779}` → `None`; article with no CVEs → `"title"`.
  - `test_window_and_age`: story `last_seen_at = at - 73h` → `None`; `first_seen_at = at - 8d`, `last_seen_at = at - 1h` → `None`.
- [ ] **Step 2: Export the replay fixture** (read-only on dev, via the scratchpad `q.sh` helper; no approval needed for reads): JSON list ordered by `first_seen_at` of `{id, title, source, scraper_id, first_seen_at, cves}` for all articles, `cves` from `article_cves`. Commit it under `tests/fixtures/story_replay/dev_2026-10.json` with a `README` line in the test docstring saying how it was produced and the date.
- [ ] **Step 3: Write failing replay test** `tests/unit/test_story_replay.py::test_dev_replay`: feed articles in order through `resolve`, keeping an in-memory list of `StoryCandidate` (new story when `None`, otherwise append member, union CVEs, bump `last_seen_at`); Tier 0 articles (`scraper_id in {"cisa_kev", "exploitdb", "cis"}`) take part normally. Assert: the story holding article 1302 (PHP2Shell) has >= 22 members; the story holding 162 (NetScaler) has >= 14; the story holding 713 (Atlassian) has >= 8; no two of articles 956, 957, 958 (Asec monthly reports) share a story; total follow-ups between 150 and 220. Print the top-10 story sizes on failure.
- [ ] **Step 4: Run** both files — expect FAIL (module missing).
- [ ] **Step 5: Implement** `similarity.py` and `resolver.py`; add the dependency and run `uv lock` (confirm `git diff uv.lock` adds no package).
- [ ] **Step 6: Run** `uv run pytest tests/unit/test_story_resolver.py tests/unit/test_story_replay.py -q` — expect PASS. If the replay misses a threshold, report the numbers instead of retuning defaults silently: the defaults are spec values.
- [ ] **Step 7: Commit** `feat(story): deterministic story resolver with dev replay test`.

### Task 4: Pipeline: fetch first, resolve, inherit, attach

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/pipeline.py`, `packages/cti-enrich/src/cti_enrich/stages/persist.py`
- Create: `packages/cti-enrich/src/cti_enrich/story/attach.py`
- Test: `tests/unit/test_pipeline_story.py`, `tests/integration/test_pipeline_story.py`

**Interfaces:**
- Consumes: `StoryRepo` (Task 2), `resolve`, `key_cves`, `ArticleKeys`, `Match` (Task 3), `extract_cves` (`cti_enrich.stages.extract_cves`).
- Produces in `story/attach.py`:
  - `StoryLink(story_id: int, rule: Literal["lead", "cve", "title_exact", "title"], inherited: dict | None)`
  - `resolve_story(*, title: str, source: str, text: str, now: datetime, cfg: StorySettings) -> StoryLink` — opens its own `sync_session()`, `StoryRepo.lock()`, `candidates`, `resolve`; on `None` calls `create` and returns `rule="lead"`; on a match returns `inherited = repo.get_classify(id)`; commits.
  - `classify_from_story(data: dict, *, story_id: int, rule: str, lead_article_id: int | None) -> ClassifyResult` — every `ClassifyResult` field from `data`, `audit={"inherited_from_story": story_id, "lead_article_id": ..., "match": rule}`.
  - `classify_to_story(result: ClassifyResult) -> dict` — `dataclasses.asdict` without `audit`.
- `persist(...)` gains keyword `story: StoryLink | None = None` and, when set, writes `story_id`/`story_match` and calls `StoryRepo(session).attach(...)` with `classify = classify_to_story(classify_result)` only when the classify came from the LLM (not inherited, not `default_relevance="always"`).
- `PipelineOutcome` gains `story_id: int | None = None`.

- [ ] **Step 1: Write failing unit tests** in `tests/unit/test_pipeline_story.py`, reusing the fixture style of `tests/unit/test_pipeline_tier0.py` and a fake `resolve_story` that records calls and returns a chosen `StoryLink`; also record call order of `fetch_text` and `classify`:
  - `test_inherited_skips_llm`: link `rule="cve"`, `inherited={"related_cyber": True, "industries_impacted": ["Finance"], ...}` → `classify == 0`, `ttp == 0`, persisted `classify_result.industries_impacted == ["Finance"]`, audit has `inherited_from_story`, persisted `story` is the link.
  - `test_known_story_without_classify_enriches_fully`: `inherited=None` → `classify == 1`, `ttp == 1`, `story` still passed to persist.
  - `test_fetch_before_classify` (order `["fetch", "classify"]`) and `test_empty_fetch_uses_title_cves`: `fetch_text` returns `""`, title "Patch for CVE-2026-0001" → fake `resolve_story` received `text == ""` and the pipeline completes.
  - `test_story_disabled_is_0_8_6`: `STORY__ENABLED=false` (monkeypatch settings) → `resolve_story` never called, order `["classify", "fetch"]`, persist gets `story=None`.
  - `test_tier0_never_fills_story_classify`: `default_relevance="always"` with a lead link → `attach` is called with `classify=None` (assert on the fake repo call). Rule in `persist`: pass `classify=None` when `"inherited_from_story" in audit` or `"skipped" in audit`, else `classify_to_story(classify_result)`.
  - `test_rejected_lead_discards_empty_story`: classify rejects on a `rule="lead"` link → `StoryRepo.discard_if_empty` called with the story id.
- [ ] **Step 2: Write failing integration test** `tests/integration/test_pipeline_story.py` with real DB and fakes only for LLM/fetch/alerts: lead article then follow-up sharing two CVEs → second has same `story_id`, `story_match == "cve"`, `stories.article_count == 2`, LLM fakes called once; `test_replay_reuses_empty_story`: first run raises from fake classify after `resolve_story` (story created, no article), second run with the same title succeeds → one story, `article_count == 1`.
- [ ] **Step 3: Run** both — expect FAIL.
- [ ] **Step 4: Implement**: in `run_pipeline`, when `get_settings().story.enabled`, call `fetch_text` right after `_known_article`, compute CVEs with `extract_cves(title + " " + text)`, call `resolve_story`, then branch as spec 4.1; keep the disabled path byte-for-byte equivalent to 0.8.6 ordering. Update the module docstring (Indonesian) with the new order and why the resolve session is separate (spec 4.2).
- [ ] **Step 5: Run** both files plus the fast suite — expect PASS.
- [ ] **Step 6: Commit** `feat(enrich): follow-up articles of a known story inherit classification`.

### Task 5: Purge empty stories

**Files:**
- Modify: `apps/worker/src/cti_worker/tasks/llm_maintenance.py` (task `story.purge_empty`, queue `QUEUE_MAINTENANCE`), `apps/worker/src/cti_worker/beat.py` (entry `story-purge-empty`, `crontab(hour=3, minute=50)`)
- Test: `tests/unit/test_beat_schedule.py` (or the existing beat test file), `tests/integration/test_story_repo.py`

**Interfaces:**
- Consumes: `StoryRepo.purge_empty(older_than)` with `older_than = now - max_age_days`.

- [ ] **Step 1: Write failing tests**: beat schedule contains `story-purge-empty` with task `story.purge_empty` on the maintenance queue; calling the task function with a seeded empty old story deletes it and returns `{"purged": 1}`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** `feat(worker): purge empty stories daily`.

### Task 6: Backfill command

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/story_backfill.py`
- Test: `tests/integration/test_story_backfill.py`

**Interfaces:**
- Consumes: `resolve`, `key_cves` (Task 3), `StoryRepo.create/attach` (Task 2), `ArticleCveRepo.cve_ids_by_article` (P2).
- Produces: `backfill(session: Session, *, since: date | None, dry_run: bool) -> BackfillReport(stories: int, followups: int, top: list[tuple[int, int]])`; CLI `python -m cti_enrich.story_backfill [--dry-run] [--since YYYY-MM-DD]` in the style of `cti_enrich.backfill`.

- [ ] **Step 1: Write failing tests**: three seeded articles (two sharing CVEs, one unrelated) → two stories, `story_match` set, `stories.classify` NULL; second run changes nothing (idempotent); `dry_run=True` returns the same report and leaves no rows.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement**: iterate `articles` without `story_id` in `first_seen_at` order, keep candidates in memory like the replay test, write with `create`/`attach(classify=None)`; `dry_run` rolls back; module docstring in Indonesian with usage lines.
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** `feat(enrich): story backfill command`.

### Task 7: API: story on articles, `story_id` filter, Data health

**Files:**
- Modify: `apps/api/src/cti_api/schemas/article.py` (`StoryRef(id: int, article_count: int, source_count: int)`, `ArticleOut.story: StoryRef | None = None`, `ArticleOut.classify_inherited_from: int | None = None` (lead article id from the audit))
- Modify: `apps/api/src/cti_api/routers/articles.py` (`story_id: int | None = Query(None)`; one `AsyncStoryRepo.counts` call per request, like `ratings`), `packages/cti-core/src/cti_core/db/repositories/article.py` (`list_filtered(..., story_id: int | None = None)`)
- Modify: `apps/api/src/cti_api/schemas/data_health.py` (`StoryHealthOut(new_stories: int, followups: int, inherited: int, llm_calls_avoided: int)` on `LlmHealthOut` as `stories_24h`, `stories_7d`), `apps/api/src/cti_api/services/data_health.py`
- Modify: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts` (regenerated)
- Test: `tests/integration/test_articles_router_story.py`, existing data-health and articles snapshot tests (update snapshots only for the new fields; say so in the commit body)

**Interfaces:**
- Consumes: `AsyncStoryRepo.counts`, `AsyncStoryRepo.stats_since` (Task 2). `llm_calls_avoided = inherited * 2`.

- [ ] **Step 1: Write failing tests**: `GET /api/articles?story_id=X` returns exactly the story's members; each carries `story == {id, article_count, source_count}`; an article without story has `story is None`; a follow-up with inherited audit has `classify_inherited_from == lead id`; Data health `llm.stories_24h` counts one new story and one inherited follow-up with `llm_calls_avoided == 2`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement**, then `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`.
- [ ] **Step 4: Run** the new tests, `uv run pytest tests/integration -q -k "article or data_health"`, and the contract drift check — expect PASS.
- [ ] **Step 5: Commit** `feat(api): story reference on articles and story stats on data health`.

### Task 8: Web: sources badge, story sheet, inherited line

**Files:**
- Modify: `apps/web/src/components/newsroom/front-section.tsx` (`Kicker`: badge "+N sumber" when `a.story && a.story.source_count > 1`), `apps/web/src/components/newsroom/article-list-sheet.tsx` (`Source` gains `{ story: number }`, query param `story_id`), `apps/web/src/components/newsroom/article-modal.tsx` (line "Klasifikasi diwarisi dari artikel lead" with a button opening the lead), `apps/web/src/app/(app)/newsroom/page.tsx` (open the sheet for a story), plus the Data health LLM card (story counts)
- Test: `pnpm lint`, `pnpm exec next typegen && pnpm exec tsc --noEmit`, `pnpm build`; manual check in the browser pane in light and dark mode

**Interfaces:**
- Consumes: `ArticleOut.story`, `ArticleOut.classify_inherited_from`, `LlmHealthOut.stories_24h/7d` (Task 7).

- [ ] **Step 1: Read** `apps/web/AGENTS.md` and `apps/web/CLAUDE.md` (Base UI, not Radix; no `backdrop-blur`; theme tokens).
- [ ] **Step 2: Implement** the badge (a `Badge variant="outline"` rendered as a button, label `+${source_count - 1} sumber`), the sheet source and the inherited line; Data health shows "Cerita baru / Susulan / LLM dihindari" for 24 h and 7 d.
- [ ] **Step 3: Run** lint, typegen + tsc, build — expect PASS.
- [ ] **Step 4: Check** in the browser pane against the local API with seeded data, 375 px and desktop, light and dark.
- [ ] **Step 5: Commit** `feat(web): story sources badge and inherited classification`.

### Task 9: Embedding experiment (offline, not merged)

**Files:**
- Create (scratchpad only): experiment script reading `tests/fixtures/story_replay/dev_2026-10.json`
- Modify: `docs/superpowers/specs/2026-10-25-p3-story-dedup-design.md` (append "Appendix A: embedding experiment result")

- [ ] **Step 1: Ask the user** to approve downloading one small sentence-embedding model (name, source, size) before anything is fetched.
- [ ] **Step 2: Run** the replay with rule 4 replaced, then joined, by embedding cosine at thresholds 0.6, 0.7, 0.8; report follow-ups, PHP2Shell size (does 1278 join?), and every embedding-only merge for manual precision judgement.
- [ ] **Step 3: Write** the appendix (numbers, the false merges seen, recommendation for P5) and commit `docs: P3 embedding experiment result`.

### Task 10: Release 0.8.7 and docs

**Files:**
- Modify: root and every package `pyproject.toml`, each `__version__`, `apps/web/package.json`, `uv.lock`, `docs/openapi.json`, the health snapshot, `CHANGELOG.md` (`## [0.8.7] - 2026-10-xx`, Indonesian), `docs/LLM_ASSIST_REDESIGN.md` (P3 progress and corrected PHP2Shell count 24), `docs/ARCHITECTURE.md` (story step in the data flow), config documentation for `STORY__*`

- [ ] **Step 1: Bump** versions following the previous release commit (`git show abc37c8 --stat` for the file list).
- [ ] **Step 2: Run** `uv run ruff check . && uv run ruff format --check .`, `uv run mypy packages/cti-core/src packages/cti-scraper/src`, the fast suite, `uv run pytest tests/integration -q` (background, ~7 min), and the web checks — expect PASS; report any failure with output.
- [ ] **Step 3: Commit** `chore(release): 0.8.7 - story dedup at ingest`.
- [ ] **Step 4: Stop and ask** the user before merging into `origin/Dev`, deploying, running the backfill on dev, or pushing.
