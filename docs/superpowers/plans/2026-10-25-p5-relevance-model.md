# P5 Local Relevance Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local three-class title model lets confidently-threat-news articles skip the LLM classify call, trains itself weekly per instance, gates automatically from measured agreement, and gives the P3 story resolver an embedding similarity rule.

**Architecture:** Pure units in `cti_enrich/relevance/` (embedder, features, model, dataset, gate, evaluate), one DB-touching stage (`stages/relevance.py`), one table `relevance_models` holding the joblib artifact and the gate state, two Celery tasks on the `enrich` queue (`relevance.train` weekly, `relevance.evaluate` hourly). The pipeline calls the stage only where it calls the LLM classify today.

**Tech Stack:** Python 3.12, scikit-learn (already a `cti-enrich` dependency), `fastembed` (new, `nlp` extra) with `sentence-transformers/all-MiniLM-L6-v2` ONNX, SQLAlchemy + Alembic, Celery, FastAPI, Next.js 16.

**Spec:** `docs/superpowers/specs/2026-10-25-p5-relevance-model-design.md`

## Global Constraints

- Starts only after P4 (`claude/p4-deterministic-extractors-336b29`, 0.8.8) is merged into `main`; this branch is rebased onto it (Task 0). P4 names used here: `run_tier1`, `Tier1Result.incident: IncidentVerdict | None`, `IncidentVerdict(confirmed, reasons)`, `merge_industries`.
- Release **0.8.9**: root and every package `pyproject.toml`, each `__version__`, `apps/web/package.json`, `uv.lock`, `docs/openapi.json`, the health snapshot, `CHANGELOG.md` header `## [0.8.9] - YYYY-MM-DD` (Indonesian entry).
- No new required `.env` key: every `RelevanceSettings` field has a default; `.env.example` and `.env.prod.template` list them commented out, same style as `STORY__*`.
- Defaults (verbatim from spec 8): `MODE=auto`, `ACCEPT_THRESHOLD=0.85`, `AUDIT_RATE=0.2`, `GATE_MIN_TITLES=200`, `GATE_WINDOW_DAYS=14`, `GATE_MIN_AGREEMENT=0.95`, `REVERT_SAMPLES=50`, `REVERT_MIN_AGREEMENT=0.92`, `TRAIN_MIN_EXAMPLES=1000`, `TRAIN_MIN_PER_CLASS=100`, `HOLDOUT_DAYS=14`, `MIN_BAND_SHARE=0.2`; `STORY__EMBEDDING_SIMILARITY=0`.
- Classes, in this order everywhere: `("reject", "best_practice", "threat_news")`.
- Every failure in the relevance path falls back to the LLM classify; no article fails because of P5.
- `cti_enrich.pipeline` must stay importable without the `nlp` extra (`test_enrich_pipeline_imports_without_nlp_extra`): import `fastembed` lazily, only inside `embedder.py` functions.
- The model is never downloaded at run time: `local_files_only=True`, cache dir from env `FASTEMBED_CACHE_PATH` (`/opt/fastembed` in the image).
- Gated decisions (`audit["skipped"]`) never become training labels.
- Code comments and docstrings in Indonesian, docs in English, commit messages in English (conventional), each ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- mypy strict applies to `cti-core` (new model + repo); ruff line length 100.
- Read-only on dev and prod unless the user approves a named action. No push, deploy or PR without approval.

## Review Focus

1. A model row written by an older `scikit-learn`/`fastembed` (image upgrade) must not crash or mispredict: `feature_version` mismatch means "no model", LLM fallback, and `relevance.evaluate` triggers a retrain (test in Task 7).
2. Empty, one-word or non-English titles must predict without error (test in Task 4).
3. Two trainings at once (weekly beat + one triggered by `evaluate`) must leave exactly one `active` row: advisory lock in `run_training` plus the partial unique index (test in Task 6).
4. A holdout with no examples of one class (no best practice in the last 14 days) must not divide by zero; metrics use the in-band count only and the stratified fallback applies below 150 examples (test in Task 6).
5. Redis or Telegram down during a gate transition: the state change is still committed; the alert is best effort (test in Task 9).

---

### Task 0: Preconditions (no product code)

**Files:** none.

- [ ] **Step 1:** Confirm P4 is merged into `origin/main`: `git fetch origin && git log --oneline origin/main | grep -i "tier 1\|0.8.8"`. If not, stop and report.
- [ ] **Step 2:** Rebase: `git rebase origin/main`; then `uv sync --extra dev --locked` and `uv run pytest tests/unit tests/contract packages -q` (deselect the two known local failures from memory `local-known-test-failures`). Expected: green.
- [ ] **Step 3:** Ask the user, in chat, for approval of: (a) downloading `Qdrant/all-MiniLM-L6-v2-onnx` (~87 MB) from `huggingface.co` on every `worker-nlp` image build (CI and prod deploy); (b) a read-only reachability check from prod. Wait for an explicit yes.
- [ ] **Step 4:** Reachability (read-only): `ssh -o BatchMode=yes privy-admin@10.8.20.78 'curl -sI https://huggingface.co/api/models/Qdrant/all-MiniLM-L6-v2-onnx | head -1'` and the same on dev `nameless@172.25.1.77`. Expected `HTTP/2 200`. If not 200: stop and report (the bake-in approach in Task 12 cannot work there).
- [ ] **Step 5:** Record the pinned revision: `curl -s https://huggingface.co/api/models/Qdrant/all-MiniLM-L6-v2-onnx | python -c "import json,sys; print(json.load(sys.stdin)['sha'])"`. This SHA is used in Task 12. (Wheel sizes are read from `uv.lock` after Task 3's `uv add`: `fastembed`, `onnxruntime`, `tokenizers`, `manylinux x86_64`; they go in the PR body.)

### Task 1: Settings

**Files:**
- Modify: `packages/cti-core/src/cti_core/config.py` (new `RelevanceSettings` after `StorySettings`; `StorySettings.embedding_similarity`; `Settings.relevance`)
- Modify: `.env.example`, `.env.prod.template` (block after `STORY__TITLE_SIMILARITY`)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `RelevanceSettings` with fields `mode: Literal["off", "shadow", "auto"]`, `accept_threshold: float`, `audit_rate: float`, `gate_min_titles: int`, `gate_window_days: int`, `gate_min_agreement: float`, `revert_samples: int`, `revert_min_agreement: float`, `train_min_examples: int`, `train_min_per_class: int`, `holdout_days: int`, `min_band_share: float` (defaults in Global Constraints); `StorySettings.embedding_similarity: float = 0.0`; `get_settings().relevance`.

- [ ] **Step 1: Failing tests** in `tests/unit/test_config.py`:

```python
def test_relevance_defaults():
    s = Settings(_env_file=None, **_minimal())  # same helper the file already uses
    assert s.relevance.mode == "auto"
    assert s.relevance.accept_threshold == 0.85
    assert s.relevance.audit_rate == 0.2
    assert (s.relevance.gate_min_titles, s.relevance.gate_window_days) == (200, 14)
    assert (s.relevance.revert_samples, s.relevance.revert_min_agreement) == (50, 0.92)
    assert s.story.embedding_similarity == 0.0


def test_relevance_mode_rejects_unknown(monkeypatch):
    monkeypatch.setenv("RELEVANCE__MODE", "gate")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **_minimal())
```

Use the file's existing fixture/helper for a minimal valid config instead of `_minimal()` if it is named differently.

- [ ] **Step 2:** `uv run pytest tests/unit/test_config.py -q` → the two new tests FAIL.
- [ ] **Step 3:** Implement. Docstrings per field in Indonesian, explaining *why* (spec 5/8), like `StorySettings`. Add the commented `RELEVANCE__*` and `STORY__EMBEDDING_SIMILARITY=0` lines to both env files.
- [ ] **Step 4:** `uv run pytest tests/unit/test_config.py tests/unit/test_env_prod_template.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(config): relevance model and story embedding settings`.

### Task 2: `relevance_models` table and repository

**Files:**
- Create: `packages/cti-core/src/cti_core/db/models/relevance.py`, `packages/cti-core/src/cti_core/db/repositories/relevance.py`, `alembic/versions/<rev>_relevance_models.py` (`down_revision` = output of `uv run alembic heads` after Task 0)
- Modify: `packages/cti-core/src/cti_core/db/models/__init__.py`
- Test: `tests/integration/test_relevance_repo.py`

**Interfaces:**
- Produces: model `RelevanceModel` (columns per spec 7: `id` BigInteger, `created_at` via `TimestampMixin` pattern, `status` String(10), `artifact` LargeBinary, `feature_version` String(200), `n_examples` Integer, `class_counts` JSONB, `metrics` JSONB, `gate_state` String(10) default `"shadow"`, `gate_changed_at` timestamptz nullable, `reason` Text nullable); partial unique index `uq_relevance_models_active` on `(status)` `WHERE status = 'active'`.
- Produces: `RelevanceModelRepo(session: Session)` with
  - `get_active() -> RelevanceModel | None`
  - `add_rejected(*, feature_version: str, n_examples: int, class_counts: dict[str, int], metrics: dict[str, Any], reason: str) -> int`
  - `activate(*, artifact: bytes, feature_version: str, n_examples: int, class_counts: dict[str, int], metrics: dict[str, Any], now: datetime) -> int` — retires the current active row and copies its `gate_state`/`gate_changed_at` to the new one (default `shadow`)
  - `set_gate_state(model_id: int, state: Literal["shadow", "gate"], now: datetime) -> None`
  - `purge(older_than: datetime) -> int` — deletes non-active rows
  - `lock() -> None` — `pg_advisory_xact_lock(7_311_003)` (next to `STORY_LOCK_NAMESPACE = 7_311_002`)
  - status values validated in the repo (`ValueError` on others), like `ArticleCountry.role`
- Produces: `AsyncRelevanceModelRepo(session: AsyncSession).get_active()` for Data health.

- [ ] **Step 1: Failing integration tests**: `test_activate_retires_previous_and_inherits_gate_state` (activate A, `set_gate_state(A, "gate")`, activate B → A `retired`, B `active` with `gate_state == "gate"`); `test_only_one_active_row` (raw INSERT of a second `active` row raises `IntegrityError`); `test_purge_keeps_active`; `test_invalid_status_rejected`.
- [ ] **Step 2:** `uv run pytest tests/integration/test_relevance_repo.py -q` → FAIL (import error).
- [ ] **Step 3:** Implement model, repo, hand-written migration (same style as the P3 `stories` migration).
- [ ] **Step 4:** `uv run pytest tests/integration/test_relevance_repo.py tests/integration/test_migrations_match_models.py -q` → PASS; `uv run mypy packages/cti-core/src packages/cti-scraper/src` → clean.
- [ ] **Step 5:** Commit `feat(db): relevance_models table and repository`.

### Task 3: Embedder and dependency

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/relevance/__init__.py`, `packages/cti-enrich/src/cti_enrich/relevance/embedder.py`, `tests/unit/relevance_fakes.py`
- Modify: `packages/cti-enrich/pyproject.toml` (`fastembed` in the `nlp` extra), `uv.lock`
- Test: `tests/unit/test_relevance_embedder.py`

**Interfaces:**
- Produces: `EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"`, `EMBEDDING_DIM = 384`
- Produces: `class Embedder(Protocol): name: str; def embed(self, titles: Sequence[str]) -> np.ndarray: ...` (shape `(n, 384)`, float32, L2-normalised rows)
- Produces: `get_embedder() -> Embedder` — process-wide singleton wrapping `fastembed.TextEmbedding(EMBEDDING_MODEL, cache_dir=os.environ["FASTEMBED_CACHE_PATH"] if set, local_files_only=True)`; raises `EmbedderUnavailable(RuntimeError)` when `fastembed` is missing or the model is not on disk.
- Produces: `set_embedder(e: Embedder | None) -> None` (test hook, resets the singleton).
- Produces (tests): `tests/unit/relevance_fakes.py::FakeEmbedder` — deterministic: each lowercase token hashed (`hashlib.blake2b`, 8 bytes) to an index in 384 dims, summed, L2-normalised; `name = "fake"`.

- [ ] **Step 1: Failing tests**: `test_fake_embedder_is_deterministic_and_normalised` (same input twice → equal; norms ≈ 1; shape `(2, 384)`); `test_get_embedder_without_fastembed_raises` (monkeypatch `sys.modules["fastembed"] = None` → `EmbedderUnavailable`); `test_pipeline_still_imports_without_fastembed` (same block, `import cti_enrich.pipeline` succeeds).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; `uv add --package cti-enrich --optional nlp "fastembed>=0.9"`.
- [ ] **Step 4:** Run tests → PASS. Locally, with the model cached (`FASTEMBED_CACHE_PATH` pointing to a cache from Task 0 approval), `uv run --extra nlp python -c "from cti_enrich.relevance.embedder import get_embedder; print(get_embedder().embed(['test']).shape)"` → `(1, 384)`.
- [ ] **Step 5:** Commit `feat(enrich): local title embedder for the relevance model`.

### Task 4: Features and model

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/relevance/model.py` (features live here: one file, they change together)
- Test: `tests/unit/test_relevance_model.py`

**Interfaces:**
- Consumes: `Embedder` (Task 3).
- Produces: `CLASSES: tuple[str, str, str] = ("reject", "best_practice", "threat_news")`
- Produces: `@dataclass(frozen=True) class Example: title: str; label: str; at: datetime`
- Produces: `@dataclass(frozen=True) class Probs: reject: float; best_practice: float; threat_news: float`
- Produces: `@dataclass class TrainedModel: pipeline: Any; feature_version: str`
- Produces: `fit(examples: Sequence[Example], embedder: Embedder) -> TrainedModel` — sklearn `Pipeline` over an index-free design: precompute embeddings for the titles, then `hstack` of word TF-IDF `(1, 2)`, `sublinear_tf=True`; char TF-IDF `analyzer="char_wb"`, `(3, 5)`, `sublinear_tf=True`, `min_df=2`; and the dense embedding; `LogisticRegression(C=4, class_weight="balanced", max_iter=3000)`. Keep the two vectorizers and the classifier in one picklable object; embeddings are not pickled.
- Produces: `predict(model: TrainedModel, titles: Sequence[str], embedder: Embedder) -> list[Probs]`
- Produces: `feature_version(embedder: Embedder) -> str` = `f"{embedder.name}|fastembed={v}|sklearn={v}"` (`importlib.metadata.version`, `"none"` when absent)
- Produces: `dumps(model) -> bytes`, `loads(data: bytes) -> TrainedModel` (joblib via `io.BytesIO`)

- [ ] **Step 1: Failing tests** (FakeEmbedder, small synthetic set: 60 titles, 20 per class, built from distinct vocabularies, e.g. "ransomware attack on hospital N", "best practices for zero trust N", "webinar product launch N"):
  - `test_fit_predict_separates_synthetic_classes`: argmax of `predict` equals the label on the training titles for ≥ 95%.
  - `test_probs_sum_to_one`.
  - `test_roundtrip_bytes`: `predict(loads(dumps(m)))` equals `predict(m)`.
  - `test_predict_odd_titles`: `["", "x", "Анализ угроз"]` returns three `Probs` without raising.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(enrich): three-class title relevance model`.

### Task 5: Dataset

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/relevance/dataset.py`
- Test: `tests/unit/test_relevance_dataset.py`, `tests/integration/test_relevance_dataset_db.py`

**Interfaces:**
- Consumes: `Example` (Task 4).
- Produces: `@dataclass(frozen=True) class LabelRow: title: str; kind: Literal["article", "rejected"]; news_type: str | None; override_news_type: str | None; audit: dict[str, Any] | None; reason: str | None; failure_kind: str | None; at: datetime`
- Produces: `to_examples(rows: Iterable[LabelRow]) -> list[Example]` (pure, the rules of spec 6)
- Produces: `load_examples(session: Session) -> list[Example]` — two `SELECT`s (articles: `title, news_type, overrides->>'news_type', raw_enrichment->'classify', created_at`; rejected: `title, raw_enrichment->'classify', reason, failure_kind, rejected_at`) mapped to `LabelRow`, then `to_examples`.
- Rule constants: `BEST_PRACTICE = "Security Technology & Best Practices"`, `FAILED_PREFIX = "[enrichment_failed]"`.

- [ ] **Step 1: Failing unit tests** on `to_examples`:
  - `test_best_practice_and_threat_news_labels` (`news_type` BP → `best_practice`; `"Manually Restored"` → `threat_news`; other → `threat_news`).
  - `test_override_news_type_wins`.
  - `test_rejected_label_and_failed_excluded` (`failure_kind="transient"` excluded; `failure_kind=None, reason="[enrichment_failed] 503"` excluded; plain reason → `reject`).
  - `test_skipped_and_inherited_excluded` (`audit={"skipped": "relevance_gate"}`, `{"skipped": "default_relevance=always"}`, `{"inherited_from_story": 3}` → no example).
  - `test_dedup_latest_wins` (`"PHP2Shell  flaw"` rejected at t1 and `"php2shell flaw"` accepted at t2 > t1 → one example, `threat_news`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Integration test `test_load_examples_reads_both_tables` (seed 2 articles, 2 rejected incl. one failed) → 3 examples. Run unit + integration → PASS.
- [ ] **Step 5:** Commit `feat(enrich): relevance training labels from articles and rejected articles`.

### Task 6: Training run, CLI and weekly task

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/relevance/train.py` (with `if __name__ == "__main__":` CLI), `apps/worker/src/cti_worker/tasks/relevance.py`
- Modify: `apps/worker/src/cti_worker/celery_app.py` (import the task module), `apps/worker/src/cti_worker/beat.py` (entry `relevance-train`: Sunday 02:00 local via `local_to_utc_cron(2, 0, offset, weekday=0)`, queue `QUEUE_ENRICH`)
- Test: `tests/unit/test_relevance_train.py`, `tests/integration/test_relevance_train_db.py`, beat test file that already checks schedule entries

**Interfaces:**
- Consumes: `load_examples` (5), `fit`/`predict`/`dumps`/`feature_version` (4), `RelevanceModelRepo` (2), `RelevanceSettings` (1).
- Produces: `@dataclass(frozen=True) class Holdout: train: list[Example]; test: list[Example]; kind: Literal["time", "stratified"]`
- Produces: `split_holdout(examples, *, now: datetime, holdout_days: int, min_time_holdout: int = 150) -> Holdout` (stratified fallback: `sklearn.model_selection.train_test_split(test_size=0.2, stratify=labels, random_state=0)`)
- Produces: `band_metrics(probs: list[Probs], labels: list[str], threshold: float) -> dict[str, float | int]` with keys `band_share`, `band_n`, `agreement` (`threat_news` share among in-band; `0.0` when `band_n == 0`), `n`
- Produces: `@dataclass(frozen=True) class TrainOutcome: status: Literal["active", "rejected", "skipped"]; model_id: int | None; metrics: dict[str, Any]; reason: str | None`
- Produces: `run_training(session: Session, embedder: Embedder, cfg: RelevanceSettings, now: datetime, *, dry_run: bool = False) -> TrainOutcome` — takes `repo.lock()` first; `skipped` when below `train_min_examples` / `train_min_per_class` (no row written); `rejected` row when `agreement < gate_min_agreement` or `band_share < min_band_share`; else refit on all examples and `activate`; purges rows older than 90 days.
- Produces: Celery task `relevance.train` (queue `QUEUE_ENRICH`) → `run_training(...)` in `sync_session()`, returns `asdict(outcome)`; on `rejected` calls `alert_ops(...)` from Task 9 (import inside the function).
- CLI: `python -m cti_enrich.relevance.train [--dry-run]` prints the outcome as JSON.

- [ ] **Step 1: Failing unit tests**: `test_split_holdout_time_and_fallback` (300 examples spread over 30 days → `kind == "time"`; 100 examples → `stratified`); `test_band_metrics_empty_band` (all probs below threshold → `band_n == 0`, `agreement == 0.0`, no exception); `test_band_metrics_counts` (hand-made probs/labels).
- [ ] **Step 2: Failing integration tests** (FakeEmbedder, seeded synthetic titles): `test_run_training_activates` (enough examples → `active`, one active row, `metrics["agreement"] >= 0.95`); `test_run_training_skipped_below_minimum` (cfg `train_min_examples=10_000` → `skipped`, no row); `test_run_training_rejected_keeps_previous` (cfg `gate_min_agreement=1.01` → `rejected` row, earlier active unchanged); `test_concurrent_training_one_active` (two threads with their own sessions call `run_training` → exactly one `active`).
- [ ] **Step 3:** Run → FAIL. Implement. Run → PASS.
- [ ] **Step 4:** Beat test: entry `relevance-train` exists with task `relevance.train` and queue `enrich`. Run the beat tests → PASS.
- [ ] **Step 5:** Commit `feat(worker): weekly relevance model training`.

### Task 7: Gate decision and relevance stage

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/relevance/gate.py`, `packages/cti-enrich/src/cti_enrich/stages/relevance.py`
- Test: `tests/unit/test_relevance_gate.py`, `tests/unit/test_relevance_stage.py`

**Interfaces:**
- Consumes: `Probs`, `loads`, `predict`, `feature_version` (4); `get_embedder`, `EmbedderUnavailable` (3); `RelevanceModelRepo.get_active` (2).
- Produces: `Decision = Literal["shadow", "gated", "audit", "llm"]`
- Produces: `@dataclass(frozen=True) class GateDecision: decision: Decision; in_band: bool`
- Produces: `in_audit_sample(url_hash: str, rate: float) -> bool` = `int(url_hash[:8], 16) / 0xFFFFFFFF < rate`
- Produces: `decide(probs: Probs, *, url_hash: str, gate_state: Literal["shadow", "gate"], cfg: RelevanceSettings) -> GateDecision` — `in_band = probs.threat_news >= cfg.accept_threshold`; gate state `shadow` or `cfg.mode != "auto"` → `shadow`; gate state `gate`: in band and sampled → `audit`, in band → `gated`, else `llm`.
- Produces: `@dataclass(frozen=True) class RelevanceResult: model_id: int; probs: Probs; decision: GateDecision` with `to_audit() -> dict[str, Any]` = `{"model_id", "probs": {...}, "in_band", "decision"}`
- Produces: `run_relevance(session: Session, *, title: str, url: str, cfg: RelevanceSettings) -> RelevanceResult | None` — `None` when `cfg.mode == "off"`, no active model, `feature_version` mismatch, `EmbedderUnavailable`, or any exception (logged `relevance_failed`). Active model cached per process with a 600 s TTL keyed on `model_id`; `gate_state` re-read from the cached row on TTL expiry only.
- Produces: `needs_retrain(session) -> bool` (no active row, or active `feature_version` differs from runtime) for Task 9.

- [ ] **Step 1: Failing tests** for `decide`: shadow state → `shadow` for in-band and out-of-band; gate state, `probs.threat_news=0.9`, hash not sampled → `gated`; sampled → `audit`; `0.5` → `llm`; `cfg.mode="shadow"` with gate state `gate` → `shadow`. `in_audit_sample`: over 10,000 sha256 hashes the sampled share is within 0.18-0.22 for rate 0.2.
- [ ] **Step 2: Failing tests** for `run_relevance` (FakeEmbedder via `set_embedder`, repo monkeypatched): returns `None` for `mode="off"`, for no active model, for a row with `feature_version="other"`, and when `predict` raises; returns a result with `model_id` otherwise.
- [ ] **Step 3:** Run → FAIL. Implement. Run → PASS.
- [ ] **Step 4:** Commit `feat(enrich): relevance gate decision and stage`.

### Task 8: Pipeline integration

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/pipeline.py` (classify branch; incident fields after `run_tier1`), `packages/cti-enrich/src/cti_enrich/stages/persist.py` (`raw_enrichment["relevance"]` in `persist` and `persist_rejected`), `packages/cti-enrich/src/cti_enrich/tier1/incident.py` (`IncidentVerdict.victim: str | None = None`, filled from the victim the rule found)
- Test: `tests/unit/test_pipeline_relevance.py`, `tests/unit/test_tier1_industry_incident.py` (victim field)

**Interfaces:**
- Consumes: `run_relevance`, `RelevanceResult` (7); P4 `run_tier1`, `Tier1Result.incident`.
- Produces: `gated_classify(result: RelevanceResult) -> ClassifyResult` in `stages/relevance.py`: `related_cyber=True`, `security_tech_best_practice=False`, `industries_impacted=[]`, `confidence=result.probs.threat_news`, `reason=f"relevance model p={p:.2f}"`, `audit={"skipped": "relevance_gate", "model_id": ..., "p": ...}`.
- Produces: `persist(..., relevance: RelevanceResult | None = None)` and `persist_rejected(..., relevance: RelevanceResult | None = None)` write `raw_enrichment["relevance"] = relevance.to_audit()` next to `"classify"`; for gated articles also `"incident_source": "rule"`.

Flow in `run_pipeline` (only the `else: classify_result = classify(title)` branch changes):

```python
relevance = run_relevance(session, title=title, url=url, cfg=get_settings().relevance)
if relevance is not None and relevance.decision.decision == "gated":
    classify_result = gated_classify(relevance)
else:
    classify_result = classify(title)
```

After `run_tier1`, when the classify audit has `skipped == "relevance_gate"` and `tier1.incident` is not None: set `classify_result.confirmed_incident = tier1.incident.confirmed` and `classify_result.victim_name = tier1.incident.victim`. Note `run_tier1` is called with `victim_name=classify_result.victim_name` (None for gated articles), which is intended.

- [ ] **Step 1: Failing tests** (`classify`, `fetch_text`, `run_tier1`, `run_relevance` monkeypatched; style of `tests/unit/test_pipeline_tier1.py`):
  - `test_gated_article_skips_classify` (relevance decision `gated` → `classify` not called; persisted audit `skipped == "relevance_gate"`; `raw_enrichment["relevance"]["decision"] == "gated"`).
  - `test_gated_article_incident_from_rule` (`tier1.incident = IncidentVerdict(True, ("breached",), victim="Acme")` → persisted `confirmed_incident is True`, `victim_name == "Acme"`).
  - `test_gated_lead_does_not_fill_story` (`_story_classify` returns None for the gated audit).
  - `test_shadow_calls_classify_and_records` (decision `shadow` → `classify` called once; record kept, also on a rejected article via `persist_rejected`).
  - `test_relevance_none_falls_back` (`run_relevance` returns None → `classify` called, no `relevance` key).
  - `test_tier0_and_inherited_do_not_run_relevance` (`default_relevance="always"` and story inheritance → `run_relevance` not called).
- [ ] **Step 2:** Run → FAIL. Implement. Run the new tests plus `tests/unit/test_pipeline_tier1.py` and the P3 pipeline tests → PASS.
- [ ] **Step 3:** Commit `feat(enrich): relevance gate in the pipeline`.

### Task 9: Automatic gate transitions

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/relevance/evaluate.py`
- Modify: `packages/cti-core/src/cti_core/db/repositories/relevance.py` (stats queries), `apps/worker/src/cti_worker/tasks/relevance.py` (task `relevance.evaluate`, helper `alert_ops`), `apps/worker/src/cti_worker/beat.py` (entry `relevance-evaluate`: `crontab(minute=7)`, queue `QUEUE_ENRICH`)
- Test: `tests/unit/test_relevance_evaluate.py`, `tests/integration/test_relevance_stats_db.py`

**Interfaces:**
- Produces (repo): `@dataclass(frozen=True) class GateStats: band_n: int; band_agree: int; audit_last: list[bool]` and `RelevanceModelRepo.gate_stats(*, since: datetime, revert_samples: int) -> GateStats`. Rows = `articles` and `rejected_articles` whose `raw_enrichment->'relevance'->>'in_band' = 'true'` and `decision in ('shadow', 'audit')`. LLM verdict: rejected row → `reject`; article with `news_type = BEST_PRACTICE` → `best_practice`; else `threat_news`. Agreement = verdict `threat_news`. `band_*` counts rows since `since`; `audit_last` = agreement of the latest `revert_samples` rows with `decision = 'audit'`, newest first.
- Produces (pure): `next_state(current: Literal["shadow", "gate"], stats: GateStats, cfg: RelevanceSettings) -> Literal["shadow", "gate"]`:
  - `cfg.mode != "auto"` → `shadow`
  - `shadow` → `gate` when `stats.band_n >= cfg.gate_min_titles` and `band_agree / band_n >= cfg.gate_min_agreement`
  - `gate` → `shadow` when `len(audit_last) >= cfg.revert_samples` and `sum(audit_last) / len(audit_last) < cfg.revert_min_agreement`
  - otherwise unchanged
- Produces (worker): `alert_ops(text: str, *, key: str, cooldown_s: int = 3600) -> None` — `send_alert("scraper_health", text)` with a Redis `SET NX EX` dedupe on `key`; swallows every exception (logs `relevance_alert_failed`).
- Produces (task): `relevance.evaluate` — in one session: if the active row exists but `loads(artifact)` raises → `alert_ops(..., key="relevance:load")`, then treat as retrain; if `needs_retrain(session)` → `relevance.train.delay()` and return; else `gate_stats(since=now - gate_window_days)`, `next_state`, on change `set_gate_state` + commit, then `alert_ops` (Indonesian text naming old → new state and the numbers), log `relevance_gate_changed`.

- [ ] **Step 1: Failing unit tests** for `next_state`: 199 titles at 100% → stays `shadow`; 200 at 95% → `gate`; 200 at 94.9% → `shadow`; gate with 49 audits all wrong → stays `gate`; 50 audits at 92% → stays; 50 at 90% → `shadow`; `mode="shadow"` with `gate` → `shadow`.
- [ ] **Step 2: Failing integration tests**: `test_evaluate_alerts_and_retrains_on_corrupt_artifact` (active row with `artifact=b"x"` → `alert_ops` called with key `relevance:load`, `relevance.train.delay` called); `test_gate_stats_counts_band_and_audit` (seed articles/rejected with relevance records: in-band shadow agree/disagree, out-of-band, gated (not counted), audit rows → exact counts); `test_evaluate_commits_state_when_alert_fails` (monkeypatch `send_alert` to raise and Redis URL to an unreachable host → `gate_state` changed in DB).
- [ ] **Step 3:** Run → FAIL. Implement. Run → PASS. Beat test includes `relevance-evaluate`.
- [ ] **Step 4:** Commit `feat(worker): automatic relevance gate from measured agreement`.

### Task 10: Embedding rule in the story resolver

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/story/similarity.py` (`embedding_similarity`), `packages/cti-enrich/src/cti_enrich/story/resolver.py` (parameter + rule), `packages/cti-enrich/src/cti_enrich/story/attach.py` (`StoryLink.rule` literal, pass the function when enabled), `tests/unit/test_story_replay.py`
- Create: `tests/fixtures/story_replay/dev_2026-10_minilm.npz` (`titles`, `vecs` float16), `tools/eval/embed_story_fixture.py`
- Test: `tests/unit/test_story_resolver.py` (existing file; add cases), `tests/unit/test_story_replay.py`

**Interfaces:**
- Consumes: `get_embedder` (3).
- Produces: `embedding_similarity(query: str, titles: list[str], embedder: Embedder | None = None) -> list[float]` (cosine of normalised vectors; `[]` for no titles).
- Produces: `resolve(keys, candidates, cfg, *, embedding_similarity: Callable[[str, list[str]], list[float]] | None = None) -> Match | None`; `Match.rule` gains `"title_embedding"`. In the title rule, compute TF-IDF scores as today; when `cfg.embedding_similarity > 0` and the callable is given, also compute embedding scores; a member qualifies if `tfidf >= cfg.title_similarity or emb >= cfg.embedding_similarity` (other-source rule and veto unchanged); pick the best by `max(tfidf, emb)`, ties by lowest story id; rule is `"title"` when the TF-IDF score alone qualifies, else `"title_embedding"`.
- `resolve_story` passes `embedding_similarity` only when `cfg.embedding_similarity > 0`; an `EmbedderUnavailable` there is logged once and the resolver runs without it.
- `articles.story_match` (`String(20)`) already fits `"title_embedding"` (15 chars); no migration.

- [ ] **Step 1:** Build the fixture: `tools/eval/embed_story_fixture.py <fixture.json> <out.npz>` embeds the unique titles of `dev_2026-10.json` with `get_embedder()` and saves float16. Run it with the approved model cache; commit the `.npz` (expected ~1 MB).
- [ ] **Step 2: Failing tests**: resolver unit — `embedding match only when enabled` (stub callable returning 0.85, TF-IDF low: cfg 0 → no match; cfg 0.8 → `title_embedding`); `embedding respects other-source and CVE veto`. Replay — new `test_dev_replay_with_embeddings` using a callable backed by the `.npz`, `StorySettings(embedding_similarity=0.8)`: `sizes[story_of[1302]] >= 22`, `sizes[story_of[162]] >= 14`, `sizes[story_of[713]] >= 8`, Asec 956/957/958 in three stories, `175 <= follow_ups <= 215` (P3 appendix A: 194). Existing `test_dev_replay` unchanged.
- [ ] **Step 3:** Run → FAIL. Implement. Run → PASS.
- [ ] **Step 4:** Commit `feat(enrich): optional embedding title rule for story dedup`.

### Task 11: Data health API and page

**Files:**
- Modify: `apps/api/src/cti_api/schemas/data_health.py`, `apps/api/src/cti_api/services/data_health.py`, `packages/cti-core/src/cti_core/db/repositories/relevance.py` (async stats), `packages/cti-core/src/cti_core/db/repositories/story.py` (`StoryStats.by_embedding`), `apps/web/src/components/data-health/data-health-view.tsx`, `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`
- Test: `tests/integration/test_data_health*.py` (existing snapshot; update with `--snapshot-update` after review), new `tests/integration/test_data_health_relevance.py`

**Interfaces:**
- Produces: `RelevanceHealthOut` on `DataHealthOut.relevance` with fields: `mode: Literal["off", "shadow", "auto"]`, `gate_state: Literal["shadow", "gate"] | None`, `gate_changed_at: str | None`, `model_trained_at: str | None`, `n_examples: int | None`, `holdout_agreement: float | None`, `holdout_band_share: float | None`, `band_titles_14d: int`, `band_agreement_14d: float | None`, `middle_band_14d: int`, `audit_samples: int`, `audit_agreement: float | None`, `classify_avoided_24h: int`, `classify_avoided_7d: int`. `StoryHealthOut.by_embedding: int`.
- Avoided = count of articles with `raw_enrichment->'relevance'->>'decision' = 'gated'` in the window.

- [ ] **Step 1: Failing integration test** `test_data_health_relevance_section` (seed one active model + relevance records → exact numbers above).
- [ ] **Step 2:** Run → FAIL. Implement API. Run → PASS. Regenerate: `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`.
- [ ] **Step 3:** Web: a "Relevance model" card in `data-health-view.tsx` following the existing LLM/story cards (theme tokens only, no `backdrop-blur`); the stories card shows `by_embedding`. `pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build` → clean.
- [ ] **Step 4:** Commit `feat(api): relevance model section in data health`.

### Task 12: Image bake-in and CI smoke

**Files:**
- Modify: `docker/worker.Dockerfile` (`worker-nlp` stage), `.github/workflows/ci.yml` (worker-nlp smoke)

**Interfaces:**
- Consumes: revision SHA from Task 0 Step 5; `EMBEDDING_MODEL` (3).

- [ ] **Step 1:** In `worker-nlp`, before `USER cti`: `ENV FASTEMBED_CACHE_PATH=/opt/fastembed HF_HUB_OFFLINE=0`, a `RUN` that instantiates `TextEmbedding(EMBEDDING_MODEL, cache_dir="/opt/fastembed")` pinned to the recorded revision (pass `revision=` if `fastembed` supports it for this model; otherwise `huggingface_hub.snapshot_download("Qdrant/all-MiniLM-L6-v2-onnx", revision=<sha>, cache_dir=...)`), `chmod -R a+rX /opt/fastembed`, then `ENV HF_HUB_OFFLINE=1` and a smoke `RUN python -c "from cti_enrich.relevance.embedder import get_embedder; assert get_embedder().embed(['x']).shape == (1, 384)"`. Indonesian comment in the style of the NLTK block.
- [ ] **Step 2:** CI matrix `worker-nlp` smoke appends `; from cti_enrich.relevance.embedder import get_embedder; get_embedder().embed(['x'])`.
- [ ] **Step 3:** Local build: `docker build -f docker/worker.Dockerfile --target worker-nlp -t cti-worker-nlp:p5 .` → succeeds; `docker run --rm --network none --entrypoint python cti-worker-nlp:p5 -c "<smoke>"` → exit 0 (proves offline). Record the image size delta vs `main` for the PR body.
- [ ] **Step 4:** Commit `build(worker): bake the MiniLM embedding model into worker-nlp`.

### Task 13: Evaluation, docs, release, dev rollout

**Files:**
- Create: `tools/eval/relevance_eval.py`
- Modify: `docs/LLM_ASSIST_REDESIGN.md` (Progress + P5 row), `docs/ARCHITECTURE.md` (pipeline/relevance paragraph), `docs/superpowers/specs/2026-10-25-p5-relevance-model-design.md` (status line), `CHANGELOG.md`, version files listed in Global Constraints

**Interfaces:**
- Consumes: `to_examples`, `fit`, `predict`, `split_holdout`, `band_metrics` (4-6).

- [ ] **Step 1:** `tools/eval/relevance_eval.py <labels.csv> [--folds 5]`: CSV columns `kind,title,news_type,reason,failure_kind,at`; builds `LabelRow`s, runs `to_examples`, then the 14-day holdout and 5-fold CV with the real embedder; prints `band_share`, `agreement` at 0.85 and 0.9, and the per-class confusion. Outputs stay outside the repo.
- [ ] **Step 2:** Export prod labels read-only (pattern from memory `prod-instance-ssh`, `default_transaction_read_only=on`) to the session scratchpad; run the eval. Gate: `agreement >= 0.95` and `band_share >= 0.35` at 0.85. If it fails, stop and report; do not lower the target.
- [ ] **Step 3:** Docs with the measured numbers; CHANGELOG `## [0.8.9] - <date>` in Indonesian; version bump; `uv lock`; regenerate `docs/openapi.json` + `schema.d.ts`; health snapshot `--snapshot-update`.
- [ ] **Step 4:** Full verification: `uv run ruff check . && uv run ruff format --check .`, `uv run mypy packages/cti-core/src packages/cti-scraper/src`, `uv run pytest tests/unit tests/contract packages`, `uv run pytest tests/integration` (background, ~7 min), web lint/typecheck/build. All green.
- [ ] **Step 5:** Commit `chore(release): 0.8.9 local relevance model`.
- [ ] **Step 6 (needs the user's approval, ask with the exact actions):** push the branch, merge into `origin/Dev`, deploy on dev. Then read-only checks on dev: a `relevance_models` row `active` within the hour (or `skipped` with the reason if dev has too few labels, which is acceptable and reported); new articles carry `raw_enrichment->'relevance'`; Data health shows the section. With approval, set `STORY__EMBEDDING_SIMILARITY=0.8` on dev and restart `worker-nlp`.
- [ ] **Step 7:** Open the PR to `main` only after the user approves, body ending with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`, including wheel sizes, image size delta, eval numbers, and the note "set `RELEVANCE__MODE=shadow` in prod `.env` before deploy to hold the gate".
