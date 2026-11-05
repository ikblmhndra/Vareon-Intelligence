# P7f PIR and own-asset relevance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Articles matching an active PIR or naming our own technology get `pir_match` / `own_asset` points in the P6 `priority_score`, with the matched PIRs and techs shown (per client) in the grade reasons.

**Architecture:** Two new signals in the pure `cti_core.confidence.assess`; the facts loader `cti_core.db.repositories.assessment` computes them per batch (PIR filter reused from the PIR page via `_apply_list_filters`, tech names via `cti_core.tech_match`). No table, no migration, no enrichment-pipeline file touched. PIR/techstack mutations enqueue `confidence.recompute_all`. The article serializer filters the new reasons to the effective client.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (sync psycopg + async asyncpg), FastAPI, pytest + testcontainers, Next.js 16 (web).

**Spec:** `docs/superpowers/specs/2026-11-05-p7f-pir-own-asset-relevance-design.md`

## Global Constraints

- Release 0.8.11, **no version bump**; add to the existing `## [0.8.11]` CHANGELOG entry (Indonesian).
- No Alembic migration, no new `Settings` / `.env` key.
- Do not modify `packages/cti-enrich/src/cti_enrich/pipeline.py` or `stages/persist.py` (P7g, PR #84).
- Weights: `PRIORITY_PIR = {"P1": 20, "P2": 15, "P3": 10, "P4": 5}` (unknown priority = 5), best PIR only; `PRIORITY_OWN_ASSET = 15`.
- Reason codes: priority signals `"pir_match"`, `"own_asset"`; reason keys `"pir"`, `"own_asset"` present only when non-empty; `own_asset` capped at 5 entries.
- Comments/docstrings Indonesian (match surrounding), docs English, commit messages English conventional, each ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Integration tests: use the rollback fixtures `db_session` / `async_db_session`; never leave committed PIR/techstack rows behind.
- mypy strict on `packages/cti-core/src`; ruff line length 100.

## Review Focus

1. **Committed PIR/techstack rows from other tests** (API tests commit) leaking into unrelated assessment tests via the global "all active PIRs" query → existing P6 tests must stay green in any order. Task 2 adds a test that seeds an active PIR matching nothing and asserts unchanged P6 results; Task 3/4 API tests delete what they create.
2. **Article with `posted_on` NULL and a PIR without dates** → must match like the PIR page does (no date filter applied). Pinned in Task 2.
3. **Tech names with punctuation or multiple words** (`"Oracle Java SE"`, `"n8n"`, `"microsoft 365"`) and case (`GitLab` vs `gitlab`) → whole-word, case-insensitive match (`tech_match` normalisation). Pinned in Task 2.
4. **Same tech in two clients, or a title hit plus a CVE hit on the same tech** → one reason entry per (name, client), points once. Pinned in Tasks 1 and 2.
5. **Request without `X-Client-ID`, and the ransomware/newsletter callers of `_serialize`** → no leak: the default (`client_id=None`) hides all `pir`/`own_asset` entries; list/detail endpoints pass the effective client. Pinned in Task 3.

---

### Task 1: Scoring signals in `cti_core.confidence`

**Files:**
- Modify: `packages/cti-core/src/cti_core/confidence.py`
- Test: `tests/unit/test_confidence.py`

**Interfaces:**
- Produces: `PirHit(id: int, title: str, priority: str, client_id: str)`, `AssetHit(name: str, client_id: str)` (frozen, slots dataclasses); `ArticleFacts.pir_hits: tuple[PirHit, ...] = ()`, `ArticleFacts.own_asset_hits: tuple[AssetHit, ...] = ()` (appended after the existing defaulted fields); constants `PRIORITY_PIR`, `PRIORITY_OWN_ASSET`, `OWN_ASSET_REASON_MAX = 5`.
- `assess()` reasons: `"pir": [{"id", "title", "priority", "client_id"}]` sorted by `(priority, id)`; `"own_asset": [{"name", "client_id"}]` deduplicated on `(name.lower(), client_id)`, sorted by that key, first 5.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_confidence.py` (reuse the file's existing base-facts helper):
  - `test_pir_match_uses_best_priority_only`: hits P3 (id 2) and P1 (id 9) → priority entry `{"code": "pir_match", "points": 20}`; `priority_score == base + 20`; `[h["id"] for h in reasons["pir"]] == [9, 2]`.
  - `test_pir_unknown_priority_counts_as_p4`: priority `"P9"` → 5 points.
  - `test_own_asset_flat_15_and_dedup`: hits `AssetHit("gitlab","default")`, `AssetHit("GitLab","default")`, `AssetHit("nginx","acme")` → one `own_asset` signal of 15; `reasons["own_asset"] == [{"name": "gitlab", "client_id": "default"}, {"name": "nginx", "client_id": "acme"}]`.
  - `test_own_asset_reasons_capped_at_5`: 7 distinct names → 5 entries, points still 15.
  - `test_no_hits_no_new_keys`: base facts → `"pir"` and `"own_asset"` not in `reasons`; `priority_score` equals the pre-P7f value.
  - `test_relevance_does_not_change_confidence`: same facts with/without hits → equal `confidence_score`, `credibility`, `reliability_grade`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_confidence.py -q` → new tests FAIL (ImportError on `PirHit`).
- [ ] **Step 3: Implement** the dataclasses, fields, constants and the two signals in `assess()` (append to `signals` before the existing sort; build the reason lists as above). Add one P7f sentence to the module docstring.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_confidence.py tests/unit/test_confidence_replay.py -q` → all PASS (replay unchanged).
- [ ] **Step 5: Commit** `feat(core): add PIR and own-asset priority signals`.

### Task 2: Relevance facts in the loader

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/pir.py` (new public helpers)
- Modify: `packages/cti-core/src/cti_core/db/repositories/assessment.py`
- Test: `tests/integration/test_assessment_relevance.py` (new)

**Interfaces:**
- Consumes: Task 1 `PirHit`, `AssetHit`, `ArticleFacts` fields.
- Produces in `pir.py`:
  - `pir_article_ids_stmt(pir: PIRRequirement, article_ids: Sequence[int]) -> Select[tuple[int]]`: `select(Article).where(Article.id.in_(ids))` passed through `_apply_list_filters(posted_on_start=pir.start_date, posted_on_end=pir.end_date, <every other required kwarg None>, **_criteria_filters(pir.criteria))`, then `.with_only_columns(Article.id)`.
  - `active_pirs_stmt(today: datetime.date) -> Select[tuple[PIRRequirement]]`: `status == "active"`, `start_date IS NULL OR <= today`, `end_date IS NULL OR >= today`.
  - `_criteria_filters` and `_has_criteria` coerce a value that is not a list of strings to "absent" (malformed JSONB → criterion ignored, never an exception).
- Produces in `assessment.py`:
  - `active_techstack_stmt() -> Select[tuple[str, str]]`: `(name, client_id)` where `active`.
  - `tracked_cve_techs_stmt(article_ids: Sequence[int]) -> Select[tuple[int, str, str]]`: `(article_id, CveTracker.tech, CveTracker.client_id)` via `mention_rows(CVE)` joined on `upper(cve_id) == upper(external_id)`, `~is_false_positive_row()`, `tech IS NOT NULL`.
  - `facts_stmt` adds `Article.title.label("title")`; `facts_from_row(row, pir_hits=(), own_asset_hits=())`.
  - Pure `_relevance(fact_rows, pirs, pir_matches: Mapping[int, set[int]], tech_rows, cve_rows) -> dict[int, tuple[tuple[PirHit, ...], tuple[AssetHit, ...]]]` so the sync and async runners differ only by `await`.
- Behaviour per batch in `apply_assessments` / `apply_assessments_async`: facts → active PIRs (skip `not _has_criteria`) → one `pir_article_ids_stmt` per PIR → techstack → tracked CVE techs → `_relevance`. Title hits = `tech_match.matching_names(active_names_of_client, title)` per client. CVE hits = for each tracker row, `matching_names(active_names_of_row_client, tech)`; reported under the techstack name. `today = datetime.datetime.now(datetime.UTC).date()`. Import graph: `assessment.py` → `pir.py` → `article.py`; confirm `article.py` does not import `assessment.py`.

- [ ] **Step 1: Write failing tests** in `tests/integration/test_assessment_relevance.py` (pattern of `tests/integration/test_assessment_repo.py`: seed with the rollback session, call `apply_assessments_async`, read `priority_score` / `score_reasons`):
  - `test_pir_actor_match_adds_points`: P2 PIR `threat_actors=["ShinyHunters"]`, article with that actor mention → `pir_match` 15, `reasons["pir"][0]["id"] == pir.id`, `client_id == "default"`.
  - `test_pir_hits_equal_pir_page` (parametrised: actor, malware, ttps, keywords, countries, industries, actor+keywords): over 4 seeded articles, ids with a `pir` reason == ids that `AsyncPIRRepo.list_articles_for_pir(pir, AsyncArticleRepo(s), page_size=100)` returns among them.
  - `test_pir_inactive_outside_dates_or_empty_criteria_no_hit` (status `archived`; `end_date` yesterday; `start_date` tomorrow; all-empty criteria).
  - `test_pir_window_filters_posted_on` (PIR `start_date` 2026-11-01, article posted 2026-10-20 → no hit) and `test_null_posted_on_matches_pir_without_dates`.
  - `test_malformed_criteria_ignored` (`criteria={"threat_actors": "x", "keywords": [1]}` → no hit, no exception).
  - `test_title_tech_hit` (active `"gitlab"`, title `"GitLab patches critical flaw"` → `own_asset` 15) and `test_multiword_and_punctuated_names` (`"Oracle Java SE"`, `"n8n"`, `"microsoft 365"`).
  - `test_inactive_techstack_no_hit`.
  - `test_cve_path_hit_and_fp_excluded` (tracker row `tech="fortinet"` for a mentioned CVE, techstack `"fortinet"` active → hit; same with FP row → no hit).
  - `test_title_and_cve_hit_same_tech_one_entry`.
  - `test_two_clients_same_tech` (both clients have `"nginx"` → two reason entries, 15 points).
  - `test_unmatched_active_pir_keeps_p6_scores` (Review Focus 1: active PIR matching nothing → identical assessment to no PIR).
  - `test_sync_and_async_agree_with_relevance` (`apply_assessments(db_session, ...)` vs async on equal seeds → equal `priority_score` and `score_reasons`).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_assessment_relevance.py -q` → FAIL.
- [ ] **Step 3: Implement** the helpers and wiring; update the `assessment.py` module docstring (queries per batch are now `1 + n_PIR + 3`, not one).
- [ ] **Step 4: Run** `uv run pytest tests/integration/test_assessment_relevance.py tests/integration/test_assessment_repo.py tests/integration/test_pir_query.py tests/integration/test_confidence_service.py tests/integration/test_pir_alert_service.py -q` → PASS; `uv run mypy packages/cti-core/src packages/cti-scraper/src` → clean.
- [ ] **Step 5: Commit** `feat(core): match PIR criteria and techstack in the assessment loader`.

### Task 3: API reasons, per-client filtering, contract

**Files:**
- Modify: `apps/api/src/cti_api/schemas/article.py`
- Modify: `apps/api/src/cti_api/routers/articles.py` (`_serialize`, `list_articles`, `get_article_by_id`, `set_article_credibility`)
- Modify (generated): `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`
- Test: `tests/integration/test_article_score_reasons_api.py` (new)

**Interfaces:**
- Produces: `PirReason(id: int, title: str, priority: str)`; `ScoreReasons.pir: list[PirReason] = []`, `ScoreReasons.own_asset: list[str] = []`.
- `_serialize(..., client_id: str | None = None)`: keeps `pir`/`own_asset` entries whose `client_id == client_id` (none when `None`), drops `client_id` from output, skips malformed entries (not a dict, missing keys). The three endpoints add `user: AuthedUser = Depends(require_auth)`, `x_client_id: str | None = Header(None)` and pass `effective_client_id(user, x_client_id)`. Ransomware/newsletter callers stay as they are (default `None`).

- [ ] **Step 1: Write failing tests** (API client fixtures of `tests/integration/conftest.py`; write `score_reasons` directly on a seeded article; clean up committed rows):
  - `test_detail_shows_only_own_client_reasons`: reasons with PIR and tech entries for `default` and `acme` → `GET /api/articles/{id}` as `default` returns only the `default` ones, no `client_id` key.
  - `test_list_filters_reasons_per_client` (same via `GET /api/articles`).
  - `test_serialize_without_client_hides_reasons` (direct `_serialize(article, ..., client_id=None)` → `pir == []`, `own_asset == []`, `priority` untouched).
  - `test_malformed_reason_entries_skipped` (`"pir": ["x", {"id": 1}]` → 200, `pir == []`).
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement**; regenerate with `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`.
- [ ] **Step 4: Run** the new tests, the article router snapshot tests (`--snapshot-update` only if the diff is exactly the two new empty fields) and `uv run pytest tests/contract -q` → PASS.
- [ ] **Step 5: Commit** `feat(api): expose PIR and own-asset score reasons per client`.

### Task 4: Recompute on PIR and techstack changes

**Files:**
- Modify: `apps/api/src/cti_api/routers/pir.py` (`post_pir`, `put_pir`, `remove_pir`)
- Modify: `apps/api/src/cti_api/routers/techstack.py` (create, update, targets add, targets remove, delete)
- Modify: `tests/integration/conftest.py` (default no-op patch next to the existing `send_recompute_source` one, ~line 395)
- Test: `tests/integration/test_relevance_recompute_triggers.py` (new)

**Interfaces:**
- Produces: in each router a module-level `_enqueue_recompute_all() -> None` calling `send_recompute_all()` (imported from `cti_core.celery_client` into the router module so tests patch `cti_api.routers.<name>.send_recompute_all`) inside `try/except Exception` with `log.warning("recompute_all_enqueue_failed", reason="pir" | "techstack", exc_info=True)`; called after a successful `commit()`, never on 4xx paths. Exposure and hosting edits do not affect matching and do **not** enqueue.

- [ ] **Step 1: Write failing tests** (monkeypatch with a list appender, as in `tests/integration/test_source_review.py`):
  - `test_pir_create_update_delete_enqueue_recompute` → 3 calls.
  - `test_pir_404_does_not_enqueue`.
  - `test_techstack_mutations_enqueue_recompute` (create, patch name/active, add target, remove target, delete → 5 calls; exposure patch → none).
  - `test_enqueue_failure_keeps_2xx` (patched to raise → 200, PIR stored).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus `tests/integration/test_pir_router_snapshot.py tests/integration/test_techstack_router_snapshot.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(api): recompute article scores after PIR or techstack changes`.

### Task 5: Web reason text and modal

**Files:**
- Modify: `apps/web/src/components/newsroom/score-reasons.ts`
- Modify: `apps/web/src/components/newsroom/article-modal.tsx` ("Why this grade" section)

**Interfaces:**
- Consumes: `ArticleOut.score_reasons.pir` (`{id, title, priority}[]`) and `.own_asset` (`string[]`) from the regenerated `schema.d.ts`.
- Produces: `PRIORITY_TEXT.pir_match = "PIR match"`, `PRIORITY_TEXT.own_asset = "own asset"`; the modal shows, when non-empty, one line per PIR `PIR: <title> (<priority>)` and one line `Own asset: <names joined by ", ">`, in the section's existing text styles (no new component, theme tokens only, no `backdrop-blur`; read `apps/web/CLAUDE.md` first).

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Run** in `apps/web`: `pnpm lint`, `pnpm exec next typegen && pnpm exec tsc --noEmit`, `pnpm build` → pass.
- [ ] **Step 3: Commit** `feat(web): show PIR and own-asset reasons in the grade explanation`.

### Task 6: Release docs

**Files:**
- Modify: `CHANGELOG.md` (`## [0.8.11]`, one Indonesian bullet)
- Modify: `docs/prod-upgrade/0.8.11.md`: title line plus each existing heading — What changes; Migrations ("none for P7f"); Settings ("none"); Before deploy (read-only counts of active PIRs and active techstack per client); After deploy (`select count(*) from articles where score_reasons ? 'pir'` and `? 'own_asset'`, grade tooltip); One-off commands (`POST /api/articles/confidence/recompute`, needs user approval, dev duration); Rollback (old image ignores the new keys, the next old-code recompute removes the points); Known risks (global score, points visible across clients, D1).
- Modify: `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md` (0.8.11 section, same facts in its style)
- Modify: `docs/LLM_ASSIST_REDESIGN.md` (Progress paragraph "Also built for 0.8.11 (P7f ...)", P7 table row, section 4 items 5 and 7 "partly delivered")
- Modify: `docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md` (section 0 row P7f: state and spec link)

- [ ] **Step 1: Write the docs** (English except CHANGELOG; numbers from the spec's dev survey; dev recompute numbers added in Task 7).
- [ ] **Step 2: Run** `uv run pytest tests/unit -q -k "changelog or env_prod or prod_upgrade"` → PASS.
- [ ] **Step 3: Commit** `docs: document P7f for the 0.8.11 release`.

### Task 7: Full verification and dev check

- [ ] **Step 1:** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src packages/cti-scraper/src`; `uv run pytest tests/unit tests/contract packages -q` (deselect the two known Mac-only failures); `uv run pytest tests/integration -q` in the background; `uv run python tools/export_openapi.py && git diff --exit-code docs/openapi.json` → all green.
- [ ] **Step 2 (user approval):** push branch, merge to `origin/Dev`, deploy dev (`make deploy` detached), run the recompute (write, separate approval).
- [ ] **Step 3 (read-only):** dev checks from spec section 1: articles with `score_reasons ? 'pir'` = articles PIR #5 lists; `own_asset` in 30 days >= 80; top 10 of `sort=priority` explained by reasons; tooltip/modal in light, dark and narrow width via Chrome.
- [ ] **Step 4:** add the dev numbers to the Task 6 docs, commit `docs: record P7f dev numbers`; then (user approval) PR to `main`.
