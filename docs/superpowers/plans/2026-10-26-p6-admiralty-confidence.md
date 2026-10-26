# P6 Admiralty Confidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every article carries its own Admiralty code (source reliability A-F x computed credibility 1-6), a confidence score derived from it, and an uncapped priority score that drives the "Perlu dibaca" ranking, one article per story; analysts get a review queue for default source grades.

**Architecture:** One pure function `assess(ArticleFacts) -> Assessment` in `cti_core.confidence`. One SQL statement builder loads `ArticleFacts` for a set of article ids; a sync and an async `apply_assessments` execute it and write the columns, so enrich persist, recompute tasks, the story refresh task and the API all share the formula and the query. Ranking and review are API/repository changes; the web shows the code everywhere.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (sync psycopg + async asyncpg), Alembic, FastAPI, Celery beat, Redis, pytest + testcontainers, Next.js 16 + Base UI shadcn.

**Spec:** `docs/superpowers/specs/2026-10-26-p6-admiralty-confidence-design.md` (read it first; section numbers below refer to it).

## Global Constraints

- Branch `claude/p6-admiralty-confidence-9bbec2` is rebased on `origin/claude/p5-relevance-model-a447e0` (P5, 0.8.9, PR #78 open). When P5 merges, rebase onto `origin/main`. Do not modify P5's relevance code.
- Do not modify `packages/cti-enrich/src/cti_enrich/pipeline.py` or `story/attach.py`. In `stages/persist.py` only the confidence computation changes.
- Alembic: new revision's `down_revision` = current head (`c4f1a9d27e6b` at plan time; confirm with `uv run alembic heads`).
- Comments and docstrings in Indonesian (match surrounding code); docs under `docs/` in English; `CHANGELOG.md` in Indonesian; commit messages in English, conventional, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Credibility ladder, confidence scale and priority weights exactly as spec 2.2-2.4; suggestion rules exactly as spec 5.3; all as module constants in `cti_core.confidence`.
- No new `.env` keys.
- After any endpoint/schema change: `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`.
- Checks before each commit that touches Python: `uv run ruff check . && uv run ruff format --check .`; for `cti-core`: `uv run mypy packages/cti-core/src packages/cti-scraper/src`.
- Web: shadcn on Base UI (`render={<X/>}`, single-string `SelectItem` children), no `backdrop-blur`, theme tokens; read `apps/web/CLAUDE.md` and `apps/web/AGENTS.md` before web tasks. Node via fnm is not on PATH (see memory: load it before `pnpm`).
- Known local-only failures (memory `local-known-test-failures.md`): deselect them, do not re-diagnose.

## Review Focus

1. Source names that differ only in case, or two `source_reliability_entries` rows for one name: facts must use the analyst row first, then lowest id (same order as `_by_name_ci_stmt`). Test in Task 3.
2. Articles with `story_id IS NULL` (pre-P3 or failed resolver): `story_source_count = 1`, never 0 (P3 stories can show `source_count = 0` on dev: 37 rows). Test in Task 3 (`max(source_count, 1)`).
3. `sort=priority` combined with a join filter (industries, threat actors, TTPs) that already needs `.distinct()`: the per-story collapse must not return duplicates or wrong `total`. Test in Task 7.
4. An analyst credibility override must survive every recompute path, and clearing it (`null`) must return to the computed value. Test in Task 6.
5. `confidence.refresh_stories` with no watermark in Redis (first run, or Redis flushed): process stories updated in the last 24 h, then store the watermark; with Redis down the task raises and does not touch articles. Test in Task 5.

---

### Task 1: Pure scoring model

**Files:**
- Modify: `packages/cti-core/src/cti_core/confidence.py`
- Test: `tests/unit/test_assess.py` (new)

**Interfaces:**
- Produces (all in `cti_core.confidence`):
  - `PRIMARY_KINDS: frozenset[str] = {"kev", "advisory", "vendor_research", "exploit"}`
  - `@dataclass(frozen=True, slots=True) class ArticleFacts` with fields (spec 2 table): `reliability_grade: str | None`, `content_kind: str | None`, `story_source_count: int`, `has_cve: bool`, `has_ioc: bool`, `explicit_ttp_count: int`, `bonus_ttp_count: int`, `has_actor: bool`, `confirmed_incident: bool`, `kev: bool`, `poc: bool`, `credibility_override: int | None = None`, `confidence_override: int | None = None`
  - `@dataclass(frozen=True, slots=True) class Assessment`: `reliability_grade: str`, `credibility: int`, `confidence_score: int`, `priority_score: int`, `reasons: dict[str, Any]`; property `admiralty_code -> str`
  - `def assess(facts: ArticleFacts) -> Assessment`
  - `reasons` shape: `{"credibility": list[str], "priority": list[{"code": str, "points": int}]}`; priority entries only for signals that scored, ordered by points desc then code.
- `compute_score`, `_RELIABILITY_SCORE`, `_CREDIBILITY_SCORE` stay in this task (callers move in Task 4, which deletes them).

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_assess.py`, a `_facts(**kw)` helper defaulting to a graded `B` `vendor_research` single-source article with no signals:

```python
def test_ungraded_source_is_f6():
    a = assess(_facts(reliability_grade=None))
    assert (a.reliability_grade, a.credibility, a.confidence_score) == ("F", 6, 50)
    assert a.reasons["credibility"] == ["ungraded"]

def test_kev_source_is_official():
    assert assess(_facts(reliability_grade="A", content_kind="kev")).credibility == 1

def test_three_sources_with_artefact_is_1_two_is_2():
    assert assess(_facts(content_kind="news", story_source_count=3, has_ioc=True)).credibility == 1
    assert assess(_facts(content_kind="news", story_source_count=2, has_ioc=True)).credibility == 2
    assert assess(_facts(content_kind="news", story_source_count=3)).credibility == 3

def test_primary_with_artefact_is_2_without_is_3():
    assert assess(_facts(has_cve=True)).credibility == 2
    assert assess(_facts()).credibility == 3

def test_llm_ttp_is_not_an_artefact():
    assert assess(_facts(content_kind="news", bonus_ttp_count=4)).credibility == 4
    assert assess(_facts(content_kind="news", explicit_ttp_count=1, bonus_ttp_count=1)).credibility == 3

def test_single_aggregator_without_artefact_is_4():
    a = assess(_facts(reliability_grade="C", content_kind="news"))
    assert (a.admiralty_code, a.confidence_score, a.reasons["credibility"]) == ("C4", 40, ["single_aggregator"])

def test_unknown_content_kind_is_not_primary():
    assert assess(_facts(content_kind=None)).credibility == 4

def test_credibility_override_wins_including_5():
    a = assess(_facts(credibility_override=5, has_cve=True))
    assert (a.credibility, a.confidence_score, a.reasons["credibility"]) == (5, 40, ["analyst"])

def test_confidence_override_keeps_credibility_and_feeds_priority():
    a = assess(_facts(confidence_override=95, confirmed_incident=True))
    assert (a.credibility, a.confidence_score, a.priority_score) == (3, 95, 120)

def test_confidence_scale():  # B=70, 2=70 / C=50, 1=90
    assert assess(_facts(has_cve=True)).confidence_score == 70
    assert assess(_facts(reliability_grade="C", content_kind="news", story_source_count=3, has_cve=True)).confidence_score == 70

def test_priority_points_and_caps():
    a = assess(_facts(confirmed_incident=True, kev=True, poc=True, bonus_ttp_count=9,
                      has_actor=True, story_source_count=12, has_cve=True))
    # conf B1 = 80; +25 +15 (poc ignored with kev) +12 +8 +16
    assert a.priority_score == 156
    assert [p["code"] for p in a.reasons["priority"]] == ["confirmed_incident", "corroboration", "kev", "ttps", "actor"]

def test_poc_without_kev_is_8():
    assert assess(_facts(poc=True)).priority_score == 68  # B3 = (70 + 50) / 2 = 60, + 8

def test_artefact_reason_codes():
    r = assess(_facts(has_cve=True, has_ioc=True, explicit_ttp_count=1)).reasons
    assert r["credibility"] == ["primary", "cve", "ioc", "explicit_ttp"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_assess.py -q`
Expected: FAIL, `ImportError: cannot import name 'assess'`.

- [ ] **Step 3: Implement** `ArticleFacts`, `Assessment`, `assess` and the constants in `cti_core/confidence.py`. Ladder first-match order: override, ungraded, 1, 2, 3, 4 (spec 2.2). Reason code order inside credibility: rule code(s) first (`official` | `corroborated_3` | `corroborated_2` | `primary` | `single_aggregator`), then artefact codes `cve`, `ioc`, `explicit_ttp` in that order. Rounding: `round((rel + cred) / 2)` with Python `round`. Constants: `CONFIDENCE_SCALE_RELIABILITY = {"A": 90, "B": 70, "C": 50, "D": 30, "E": 10, "F": 50}`, `CONFIDENCE_SCALE_CREDIBILITY = {1: 90, 2: 70, 3: 50, 4: 30, 5: 10, 6: 50}`, `PRIORITY_CONFIRMED_INCIDENT = 25`, `PRIORITY_KEV = 15`, `PRIORITY_POC = 8`, `PRIORITY_PER_TTP = 3`, `PRIORITY_TTP_MAX = 12`, `PRIORITY_ACTOR = 8`, `PRIORITY_PER_EXTRA_SOURCE = 4`, `PRIORITY_CORROBORATION_MAX = 16`. Update the module docstring (Indonesian) to describe P6.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_assess.py tests/unit/test_confidence.py -q && uv run mypy packages/cti-core/src packages/cti-scraper/src`
Expected: all pass, mypy clean.

- [ ] **Step 5: Commit** — `feat(core): Admiralty assess() with computed credibility and priority`

---

### Task 2: Schema: assessment columns and source content_kind

**Files:**
- Create: `alembic/versions/<rev>_article_assessment.py`
- Modify: `packages/cti-core/src/cti_core/db/models/article.py`, `packages/cti-core/src/cti_core/db/models/source_reliability.py`, `packages/cti-core/src/cti_core/db/repositories/source_reliability.py` (`ensure_defaults`), `apps/api/src/cti_api/main.py` (only if `ensure_defaults` signature changes; it should not)
- Test: `tests/integration/test_migrations_match_models.py` (existing, must pass), `tests/integration/test_default_grades_content_kind.py` (new)

**Interfaces:**
- Produces: `Article.reliability_grade: Mapped[str | None]` (`String(1)`), `Article.credibility: Mapped[int | None]` (`SmallInteger`, check constraint `credibility BETWEEN 1 AND 6` named `credibility_range`), `Article.priority_score: Mapped[int | None]` (`SmallInteger`, index `ix_articles_priority_score` on `priority_score DESC NULLS LAST`), `Article.score_reasons: Mapped[dict[str, Any]]` (JSONB, not null, `server_default='{}'`); `SourceReliabilityEntry.content_kind: Mapped[str | None]` (`String(20)`).
- `AsyncSourceReliabilityRepo.ensure_defaults(sources: Mapping[str, str]) -> list[str]` keeps its signature; it now also sets `content_kind` on **every** row whose lowercased name is in `sources` (new and existing, default and analyst), and inserts default rows with `content_kind` set.

- [ ] **Step 1: Write the failing test** `test_ensure_defaults_sets_content_kind_on_existing_rows`: seed an analyst row "Mandiant" (no kind) and call `ensure_defaults({"mandiant": "vendor_research", "Hackernews": "news"})`; assert the analyst row's `content_kind == "vendor_research"`, its grade untouched, the new "Hackernews" row has `content_kind == "news"`, return value `["Hackernews"]`. Second call with `{"Hackernews": "advisory"}` updates the kind to `advisory`.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/integration/test_default_grades_content_kind.py -q` → FAIL (`content_kind` attribute missing).
- [ ] **Step 3: Implement** model columns, the hand-written migration (add columns, check constraint, index, `server_default '{}'` for `score_reasons`; downgrade drops them), and the `ensure_defaults` change. Model docstrings in Indonesian name the spec section.
- [ ] **Step 4: Run** — `uv run pytest tests/integration/test_default_grades_content_kind.py tests/integration/test_migrations_match_models.py tests/unit/test_default_grades.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(db): article assessment columns and source content_kind`

---

### Task 3: Facts query and apply_assessments (sync + async)

**Files:**
- Create: `packages/cti-core/src/cti_core/db/repositories/assessment.py`
- Test: `tests/integration/test_assessment_repo.py` (new)

**Interfaces:**
- Consumes: Task 1 `ArticleFacts`, `assess`; Task 2 columns; `cti_core.db.repositories.cve.is_false_positive_row`.
- Produces:
  - `def facts_stmt(article_ids: Sequence[int]) -> Select[Any]` — one row per article id: `id`, source grade and `content_kind` (lateral/correlated pick of the matching SR row ordered analyst-first then id, case-insensitive name), `story_source_count = greatest(coalesce(stories.source_count, 1), 1)`, `has_cve`, `has_ioc` (exists `ioc_sources` join `iocs` with `auto_suppressed = false`), `explicit_ttp_count`, `bonus_ttp_count`, `has_actor`, `confirmed_incident`, `kev`, `poc` (exists `article_cves` join `cve_tracker` on `upper(cve_id)` with `~is_false_positive_row()`, `bool_or` of `cisa_kev` / `poc_available`), `overrides`.
  - `def facts_from_row(row: RowMapping) -> ArticleFacts` — reads `overrides["credibility"]` and `overrides["confidence_score"]` as ints when present.
  - `def apply_assessments(session: Session, article_ids: Sequence[int]) -> int` and `async def apply_assessments_async(session: AsyncSession, article_ids: Sequence[int]) -> int` — run `facts_stmt`, `assess` each row, write `reliability_grade`, `credibility`, `confidence_score`, `priority_score`, `score_reasons` with one `UPDATE ... FROM (VALUES ...)` (or `bulk_update_mappings`-style executemany) per call; flush only, no commit; return rows updated. Callers pass at most 500 ids.

- [ ] **Step 1: Write the failing tests** (async session fixture `async_db_session`, as in `tests/integration/test_confidence_service.py`):
  - `test_bare_aggregator_article_is_c4`: source "Hackernews" with SR row C / content_kind news, no children → after `apply_assessments_async`, article has `("C", 4, 40, 40)` for grade/credibility/confidence/priority.
  - `test_suppressed_ioc_is_not_an_artefact`: same article linked to one suppressed IOC → credibility 4; add a non-suppressed IOC → 3.
  - `test_story_with_three_sources_and_cve_is_1`: three articles from three sources in one story (`StoryRepo` create/attach), the target has an `article_cves` row → credibility 1, `score_reasons["priority"]` contains `{"code": "corroboration", "points": 8}`.
  - `test_null_story_and_zero_source_count_count_as_one`: article without story; article in a story whose `source_count` is 0 → both `story_source_count == 1` via `facts_from_row`.
  - `test_kev_ignores_false_positive_tracker_rows`: CVE in `cve_tracker` with `cisa_kev=True` but marked FP by its owner → no `kev` points; a second non-FP row → `kev` points.
  - `test_case_variant_rows_prefer_analyst`: SR rows "unit42" (default B) and "Unit42" (analyst A) → article from "UNIT42" gets reliability A.
  - `test_overrides_respected`: `overrides={"credibility": 5}` → credibility 5; `overrides={"confidence_score": 88}` → confidence 88.
  - `test_sync_and_async_agree`: same seeded article through `apply_assessments` (sync `db_session` fixture) and the async variant gives identical columns.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/integration/test_assessment_repo.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `assessment.py` per the interfaces. Docstring (Indonesian) explains why one statement serves both drivers.
- [ ] **Step 4: Run** — same command plus `uv run mypy packages/cti-core/src packages/cti-scraper/src` → PASS.
- [ ] **Step 5: Commit** — `feat(core): load article facts and apply Admiralty assessments in one query`

---

### Task 4: Persist and recompute use apply_assessments

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/stages/persist.py` (remove `_confidence_score` and the `confidence_score=` upsert argument; call `apply_assessments(session, [article.id])` after the `ArticleCveRepo.add_many` line, preceded by `session.flush()`)
- Modify: `apps/api/src/cti_api/services/confidence.py` (`compute_article_confidence`, `compute_and_store_article_confidence`, `recompute_all_confidence` built on `apply_assessments_async`; paging by id stays, batch 500, `commit_each_batch` stays; the "skip articles with `confidence_score` override" branch is removed because `assess` handles overrides)
- Modify: `packages/cti-core/src/cti_core/confidence.py` (delete `compute_score` and its scale dicts), `apps/api/src/cti_api/services/confidence.py` (`__all__` re-export removed), `packages/cti-enrich/src/cti_enrich/tier1/merge.py` (drop `confidence_ttp_count` only if nothing else uses it)
- Modify: `apps/api/src/cti_api/routers/articles.py` (`POST /articles/{id}/confidence` returns `{"article_id", "confidence_score", "admiralty_code", "priority_score"}`)
- Test: update `tests/integration/test_confidence_service.py`, `tests/unit/test_confidence.py` (drop `compute_score` cases), the persist tests that assert `confidence_score` (find with `grep -rn confidence_score tests/`)

**Interfaces:**
- Consumes: Task 3 `apply_assessments`, `apply_assessments_async`.
- Produces: `async def compute_and_store_article_confidence(session, article_id) -> Assessment | None` (was `int | None`); `async def recompute_all_confidence(session, *, batch_size=500, source_name=None, commit_each_batch=False, story_ids: Sequence[int] | None = None) -> dict[str, int]` — `story_ids` restricts to members of those stories (used by Task 5).

- [ ] **Step 1: Update the tests first**: persist integration test asserts that a persisted accepted article from a C/news source with one non-suppressed IOC has `credibility == 3`, `priority_score` not null and `score_reasons["credibility"] == ["ioc"]`; service test asserts `recompute_all_confidence(story_ids=[s])` touches only that story's members; router test for `POST /articles/{id}/confidence` returns the new keys.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/integration/test_confidence_service.py tests/integration/test_article_grade_fields.py -q` plus the persist test file → FAIL.
- [ ] **Step 3: Implement** the changes listed under Files. `persist.py` loses the `compute_score`, `SourceReliabilityRepo` and `confidence_ttp_count` imports if unused.
- [ ] **Step 4: Run** — `uv run pytest tests/unit tests/contract packages -q` and the touched integration files → PASS; ruff and mypy clean.
- [ ] **Step 5: Commit** — `feat(enrich): assess Admiralty credibility and priority at persist and recompute`

---

### Task 5: Story refresh task, daily recompute, bootstrap trigger

**Files:**
- Modify: `apps/worker/src/cti_worker/tasks/confidence.py` (new task `confidence.refresh_stories`)
- Modify: `apps/worker/src/cti_worker/beat.py` (`_periodic_schedule`: `"confidence-refresh-stories"` every 10 min, `"confidence-recompute-all"` daily at 03:20, both `QUEUE_MAINTENANCE`)
- Modify: `packages/cti-core/src/cti_core/db/repositories/story.py` (`async def updated_since(self, since: datetime.datetime) -> list[int]` on the async story repo, or a new async method if only a sync repo exists)
- Modify: `apps/api/src/cti_api/main.py` (after bootstrap: enqueue `send_recompute_all()` once when new default rows were inserted **or** any article has `credibility IS NULL`; keep one enqueue at most)
- Test: `tests/unit/test_beat_schedule.py`, `tests/integration/test_refresh_stories.py` (new), `tests/integration/test_bootstrap_recompute.py` (new or extend the existing bootstrap test)

**Interfaces:**
- Consumes: Task 4 `recompute_all_confidence(..., story_ids=...)`.
- Produces: Celery task `confidence.refresh_stories() -> dict[str, int]` returning `{"stories": n, "updated": m}`. Watermark Redis key `cti:confidence:refresh_stories:watermark` (ISO timestamp, UTC). Start time captured before querying; watermark set to that start time only after the recompute commits. No watermark → `since = now - 24 h`.

- [ ] **Step 1: Write the failing tests**:
  - beat: `"confidence-refresh-stories"` has `crontab(minute="*/10")`, `"confidence-recompute-all"` has `crontab(hour=3, minute=20)`, both on the maintenance queue.
  - `test_refresh_raises_older_member_to_1`: story with articles from 2 sources (target has a CVE, credibility 2), attach a third source's article, run the task body (call the inner async function with a fake Redis, e.g. `fakeredis` if already a dev dependency, else a dict-backed stub passed in) → target credibility 1; watermark stored.
  - `test_refresh_without_watermark_looks_back_24h`: story updated 30 h ago is not touched; one updated 1 h ago is.
  - `test_refresh_redis_down_raises_without_updates`: Redis stub raising `redis.ConnectionError` on `get` → task raises, article columns unchanged.
  - bootstrap: with an article whose `credibility IS NULL` and no new default rows, startup enqueues `confidence.recompute_all` exactly once (patch `send_recompute_all`).
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_beat_schedule.py tests/integration/test_refresh_stories.py tests/integration/test_bootstrap_recompute.py -q` → FAIL.
- [ ] **Step 3: Implement.** Structure the task as a thin Celery wrapper over `async def refresh_stories(session, redis_client, now) -> dict[str, int]` so tests inject the client; the wrapper builds `redis.Redis.from_url(get_settings().redis.url)` like `beat_main.py`.
- [ ] **Step 4: Run** the same tests → PASS.
- [ ] **Step 5: Commit** — `feat(worker): refresh story members' credibility and recompute scores daily`

---

### Task 6: Article API fields and credibility override endpoint

**Files:**
- Modify: `apps/api/src/cti_api/schemas/article.py` (`ArticleOut`), `apps/api/src/cti_api/routers/articles.py` (`_serialize`, new `PUT /articles/{article_id}/credibility`), any other serializer that sets `admiralty_code` (`grep -rn admiralty_code apps/api/src`)
- Create: `apps/api/src/cti_api/schemas/article.py` additions `CredibilityOverrideIn`, `ScoreReasons`, `PriorityReason`
- Test: `tests/integration/test_article_grade_fields.py` (update), `tests/integration/test_article_credibility_override.py` (new), router snapshots (`--snapshot-update` after reviewing the diff)

**Interfaces:**
- Consumes: Task 3 `apply_assessments_async`.
- Produces: `ArticleOut` fields `admiralty_code: str | None` (article's `reliability_grade + credibility`, `None` when `credibility` is null), `grade_origin` (source row origin, unchanged), `reliability_grade: str | None`, `credibility: int | None`, `priority_score: int | None`, `score_reasons: ScoreReasons` where `class PriorityReason(BaseModel): code: str; points: int` and `class ScoreReasons(BaseModel): credibility: list[str] = []; priority: list[PriorityReason] = []`. Endpoint `PUT /api/articles/{article_id}/credibility`, permission `manage_intel`, body `CredibilityOverrideIn(credibility: int | None = Field(None, ge=1, le=6), note: str = Field("", max_length=500))`, response `ArticleOut`; 404 when missing; audit action `set_credibility` with detail `{"credibility": value, "note": note}`.

- [ ] **Step 1: Write the failing tests**:
  - `ArticleOut` for an assessed C4 article has `admiralty_code == "C4"`, `credibility == 4`, `priority_score == 40`, `score_reasons.credibility == ["single_aggregator"]`; an unassessed article has `admiralty_code is None`.
  - `PUT .../credibility {"credibility": 5}` → response `credibility == 5`, `overrides["credibility"] == 5`, audit row written; then `recompute_all_confidence(session)` keeps 5; `PUT {"credibility": null}` → back to computed 4 and key removed from `overrides`.
  - Without `manage_intel` → 403; `{"credibility": 7}` → 422.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/integration/test_article_grade_fields.py tests/integration/test_article_credibility_override.py -q` → FAIL.
- [ ] **Step 3: Implement**; regenerate `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts`; update router snapshots after checking that only the new fields changed.
- [ ] **Step 4: Run** — the two files plus `uv run pytest tests/integration/test_articles_router_snapshot.py -q` → PASS; `cd apps/web && pnpm exec next typegen && pnpm exec tsc --noEmit` still compiles (`GradeChip` uses only fields that remain).
- [ ] **Step 5: Commit** — `feat(api): per-article Admiralty code, priority and credibility override`

---

### Task 7: Priority ranking, one article per story

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/article.py` (`list(... sort="priority")` and `list_top_between`)
- Test: `tests/integration/test_article_query.py` (extend)

**Interfaces:**
- Produces: `sort="priority"` returns at most one article per story (`coalesce(story_id, -id)` group key), the member with the highest `priority_score` (tie: newest `posted_on`, then highest id), ordered `priority_score desc nulls last, posted_on desc nulls last, id desc`; `total` = number of collapsed rows. Implementation: a subquery with `row_number() over (partition by coalesce(story_id, -id) order by ...)` built from the already-filtered (and, with joins, distinct) id set, then `rn = 1`; do not use `DISTINCT ON` together with the existing `.distinct()`. `list_top_between` orders by `priority_score desc nulls last, posted_on desc, id desc`, no collapse.

- [ ] **Step 1: Write the failing tests**:
  - three members of one story (priorities 90, 120, 60) plus two standalone articles (100, 50) → page returns `[120-member, 100, 50]`, `total == 3`.
  - same data with an `industries=[...]` filter matching every article through two industry rows each → no duplicates, `total == 3`.
  - `sort="recent"` unchanged (returns all 5).
  - `list_top_between` returns the 120 member first and includes all three story members.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/integration/test_article_query.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — that file plus `tests/integration/test_articles_router_snapshot.py` and the recap tests (`grep -ln list_top_between tests/`) → PASS (update snapshots only where ordering legitimately changed).
- [ ] **Step 5: Commit** — `feat(api): rank by priority with one article per story`

---

### Task 8: Source review API

**Files:**
- Modify: `packages/cti-core/src/cti_core/confidence.py` (`SourceStats`, `GradeSuggestion`, `suggest_grade`)
- Modify: `packages/cti-core/src/cti_core/db/repositories/source_reliability.py` (`review_stats`, `confirm`; `add_entry`/`update_entry` with optional credibility)
- Modify: `apps/api/src/cti_api/routers/source_reliability.py`, `apps/api/src/cti_api/schemas/source_reliability.py`
- Test: `tests/unit/test_suggest_grade.py` (new), `tests/integration/test_source_review.py` (new), `tests/integration/test_source_reliability_router_snapshot.py` (update)

**Interfaces:**
- Produces in `cti_core.confidence`:
  - `@dataclass(frozen=True, slots=True) class SourceStats`: `articles: int`, `rejected: int`, `artefact_articles: int`, `multi_source_stories: int`, `lead_count: int`, `ioc_verdicts: int`, `ioc_fp: int`; properties `rejected_pct`, `artefact_pct`, `ioc_fp_pct` (floats 0-100; 0 when denominators are 0; `rejected_pct = rejected / (articles + rejected)`).
  - `@dataclass(frozen=True, slots=True) class GradeSuggestion`: `grade: str`, `reasons: list[str]`.
  - `def suggest_grade(current: str, stats: SourceStats) -> GradeSuggestion | None` — rules and order of spec 5.3, constants `REVIEW_MIN_ARTICLES = 10`, `REVIEW_REJECTED_PCT = 30`, `REVIEW_ARTEFACT_PCT = 30`, `REVIEW_IOC_MIN_VERDICTS = 5`, `REVIEW_IOC_FP_PCT = 20`, `REVIEW_MIN_MULTI_STORIES = 5`, `REVIEW_LEAD_RATIO = 0.5`. "One grade lower" = next letter A→B→C→D→E; an E or F source gets no lowering suggestion. Raising is only C→B. Never returns A. Reason codes: `off_topic`, `ioc_false_positives`, `reports_first`. Returns `None` for "keep" and for too little data.
- Repository: `async def review_stats(self, *, since: datetime.date) -> list[tuple[SourceReliabilityEntry, SourceStats]]` for `origin='default'` rows (case-insensitive source match; rejected excludes `reason LIKE '[enrichment_failed]%'`; IOC verdicts from `ioc_feedback` on IOCs whose `ioc_sources.source_name` matches); `async def confirm(self, entry_id: int, *, analyst_name: str, reliability_grade: str | None) -> tuple[SourceReliabilityEntry | None, bool]` returning `(entry, grade_changed)`.
- API: `GET /api/sr/review` (permission `manage_sources`) → `SRReviewResponse(items: list[SRReviewItem])`, `SRReviewItem`: `entry: SREntryOut`, the seven raw counts plus the three percentages, `suggested_grade: str | None`, `suggestion_reasons: list[str]`; window 30 days. `POST /api/sr/entries/{entry_id}/confirm` body `SRConfirmIn(reliability_grade: str | None = Field(None, pattern="^[A-Fa-f]$"))` → `SREntryOut`; 404 when missing; audit action `confirm_source_rating`; enqueue `send_recompute_source` only when the grade changed.
- `SREntryAdd.credibility_code` and `SREntryUpdate.credibility_code` become optional (`str | None = Field(None, pattern="^[1-6]$")`): update keeps the stored value when omitted; add uses `"6"` when omitted. `SREntryOut` gains `content_kind: str | None`.

- [ ] **Step 1: Write the failing tests**:
  - unit: B source with `articles=16, rejected=9, artefact_articles=0` → `GradeSuggestion("C", ["off_topic"])`; C source with `multi_source_stories=34, lead_count=19` → `("B", ["reports_first"])`; B source with the same lead stats → `None` (no A, no B→A); `articles=9` → `None`; E source off-topic → `None`; IOC rule with `ioc_verdicts=5, ioc_fp=1` → lower.
  - integration: seeded sources reproduce one "lower" and one "C to B" row in `GET /api/sr/review`; analyst rows are absent; confirm without grade flips `origin` to `analyst`, sets `analyst_name` to the user and does not enqueue; confirm with a new grade enqueues once (patch `send_recompute_source`); PUT without `credibility_code` keeps the stored code.
- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_suggest_grade.py tests/integration/test_source_review.py -q` → FAIL.
- [ ] **Step 3: Implement**; regenerate OpenAPI and `schema.d.ts`; update the SR router snapshot.
- [ ] **Step 4: Run** the same tests plus the SR snapshot test → PASS; mypy clean.
- [ ] **Step 5: Commit** — `feat(api): source grade review queue with data-based suggestions`

---

### Task 9: Replay fixture and distribution test

**Files:**
- Create: `tests/fixtures/confidence_replay/dev_2026-10.csv`, `tests/fixtures/confidence_replay/README.md` (how it was produced, the query, date)
- Create: `tests/unit/test_confidence_replay.py`

**Interfaces:**
- Consumes: Task 1 `ArticleFacts`, `assess`.
- Fixture columns: `id,posted_on,story_id,reliability_grade,content_kind,story_source_count,has_cve,has_ioc,explicit_ttp_count,bonus_ttp_count,has_actor,confirmed_incident,kev,poc` (no titles, URLs or source names).

- [ ] **Step 1: Produce the fixture** with a read-only query on dev (allowed without extra approval; use `BEGIN READ ONLY; COPY (...) TO STDOUT WITH CSV HEADER; ROLLBACK;` through `ssh nameless@172.25.1.77 'cd ~/Vareon-Intelligence && docker compose exec -T postgres sh -c "psql -q -U $POSTGRES_USER -d $POSTGRES_DB"'`). `content_kind` comes from the dev registry's mapping; if dev's `source_reliability_entries.content_kind` is not yet populated (P6 not deployed), derive it in the query from the default grade (A1 → kev, A2 → advisory, B2 → vendor_research, C3 → news, C4 → vendor_marketing, D4 → social; analyst rows → NULL) and say so in the README.
- [ ] **Step 2: Write the test** `test_dev_snapshot_distribution`: load rows into `ArticleFacts`, `assess` each, assert (spec section 1, success 2): max share of any single `priority_score` <= 0.20; top 10% (by priority, `len // 10`) has >= 20 distinct values; >= 8 distinct `admiralty_code`; for every ISO week with >= 20 articles, the top 10 after keeping the best article per `story_id` (or per id when empty) span >= 5 distinct keys.
- [ ] **Step 3: Run** — `uv run pytest tests/unit/test_confidence_replay.py -q`. Expected: PASS (the plan-time simulation gave 16.9% max share, 32 distinct top-decile values, 10 codes). If an assertion fails, stop and report the numbers to the user before changing any weight.
- [ ] **Step 4: Commit** — `test: replay Admiralty scoring over the dev snapshot`

---

### Task 10: Web: grade chip everywhere, reasons, override

**Files:**
- Modify: `apps/web/src/components/newsroom/grade-chip.tsx`
- Create: `apps/web/src/components/newsroom/score-reasons.ts` (reason code → English text, one place)
- Modify: `apps/web/src/components/newsroom/rubric-queries.ts` / `rubric.tsx` (chip in rubric rows), `filtered-view.tsx` (row meta), `article-list-sheet.tsx` (row meta), `article-modal.tsx` (chip in header, "Why this grade" section, override control)
- Create: `apps/web/src/components/newsroom/credibility-override.tsx`

**Interfaces:**
- Consumes: Task 6 `ArticleOut` fields and `PUT /api/articles/{id}/credibility` via the existing `/api/proxy` client pattern used by other modal mutations; `useCan()` from `@/lib/auth/permissions`.
- Produces: `GradeChip({ a }: { a: Pick<Article, "admiralty_code" | "reliability_grade" | "credibility" | "grade_origin" | "confidence_score" | "priority_score" | "score_reasons"> })` renders `"{admiralty_code} · P{priority_score}"`, colour class by `reliability_grade` (reuse `GRADE_BADGE_CLASS` from `sr-table.tsx` by moving it to a shared module), `title` tooltip of 3-4 lines (spec section 6). Renders nothing when `admiralty_code` is null. `describeCredibility(codes: string[]): string`, `describePriority(items: {code: string; points: number}[]): string` in `score-reasons.ts`, with texts: `official` "official source", `corroborated_3` "3+ independent sources", `corroborated_2` "2 independent sources", `primary` "primary source", `single_aggregator` "single aggregator source", `ungraded` "source not graded", `analyst` "set by analyst", `cve` "CVE present", `ioc` "IOC present", `explicit_ttp` "explicit ATT&CK ID"; priority `confirmed_incident` "confirmed incident", `kev` "KEV", `poc` "public PoC", `ttps` "TTPs", `actor` "threat actor", `corroboration` "more sources".
- Override control: Base UI `Select` with items "Computed", "1" … "6" (single-string children), note input, Save; shown only when `useCan()("manage_intel")`; on success invalidate the article queries the modal and lists use.

- [ ] **Step 1: Implement** the files above.
- [ ] **Step 2: Verify** — `cd apps/web && pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build` → all succeed.
- [ ] **Step 3: Manual check** — run the API locally against the integration-seeded or local DB (`pnpm dev`) and confirm chip and tooltip on the dashboard card, Newsroom front, a rubric list, the article list sheet and the modal; override round-trip; light and dark theme. Screenshot each to the scratchpad.
- [ ] **Step 4: Commit** — `feat(web): Admiralty code and priority on every article, credibility override`

---

### Task 11: Web: "Needs review" tab and entry dialog

**Files:**
- Modify: `apps/web/src/app/(app)/intelligence/source-reliability/page.tsx` (tabs: "All sources" = existing `SrTable`, "Needs review" = new component)
- Create: `apps/web/src/components/intelligence/source-reliability/sr-review-table.tsx`
- Modify: `apps/web/src/components/intelligence/source-reliability/sr-entry-dialog.tsx` (drop the credibility field), `sr-table.tsx` (show reliability grade and `content_kind` instead of the source-level code; import moved `GRADE_BADGE_CLASS`)

**Interfaces:**
- Consumes: Task 8 `GET /api/sr/review`, `POST /api/sr/entries/{id}/confirm`.
- Produces: review table columns Source, Kind, Grade, Articles (30 d), Rejected %, Artefact %, Leads (`lead_count / multi_source_stories`), IOC FP %, Suggestion (grade + reason text: `off_topic` "often off-topic (rejected ≥30%) with few artefacts", `ioc_false_positives` "IOCs often marked false positive", `reports_first` "often reports first"), actions "Confirm" (current grade), "Confirm {suggested}" when a suggestion exists, "Edit" (existing dialog). Column help on Rejected % states it measures off-topic content, not inaccuracy. Actions visible only with `manage_sources`.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Verify** — `pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build` → succeed.
- [ ] **Step 3: Manual check** — both tabs, confirm flows, dialog without credibility, light and dark.
- [ ] **Step 4: Commit** — `feat(web): source grade review tab`

---

### Task 12: Docs, version and release notes

**Files:**
- Modify: version in root and every package `pyproject.toml`, each `__version__`, `apps/web/package.json`, `uv.lock` (`uv lock`), `docs/openapi.json` (re-export), health snapshot (`--snapshot-update` on `tests/integration/test_health_router_snapshot.py` after checking only the version changed)
- Modify: `CHANGELOG.md` (Indonesian, header `## [0.8.10] - YYYY-MM-DD`, or the next free 0.8.x if P5 shipped differently), `docs/LLM_ASSIST_REDESIGN.md` (status line, Progress section for P6, rollout row P6 "built for 0.8.10"), `docs/TARGET_ARCHITECTURE.md` (step 6 status), `docs/ARCHITECTURE.md` only if it describes confidence

- [ ] **Step 1: Bump and write notes.** CHANGELOG upgrade notes (spec section 9): additive migration, one automatic `recompute_all` after start, confidence values change meaning (10-90), dashboard ranks one article per story, new "Needs review" tab, no new `.env` keys.
- [ ] **Step 2: Full verification** — `uv run ruff check . && uv run ruff format --check . && uv run mypy packages/cti-core/src packages/cti-scraper/src && uv run pytest tests/unit tests/contract packages -q && uv run pytest tests/integration -q` (background, ~7 min) and the web trio; `git diff --exit-code docs/openapi.json apps/web/src/lib/api/schema.d.ts` after regenerating.
- [ ] **Step 3: Commit** — `chore(release): 0.8.10`

After Task 12: whole-branch review, then ask the user before merging into `origin/Dev`, deploying to dev, and running the dev checks of spec 8.4. PR to `main` only after P5 has merged and this branch is rebased on `main`.
