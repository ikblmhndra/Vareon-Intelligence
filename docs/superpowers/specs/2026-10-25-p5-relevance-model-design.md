# P5 local relevance model: classify gate without the LLM, plus embeddings for story dedup

Date: 2026-10-25. Status: Implemented in 0.8.9 (branch claude/p5-relevance-model-a447e0).
Release: **0.8.9** (one PR, after P4 / 0.8.8; merged into `origin/Dev` and tested on the dev instance
first).
Parent documents: `docs/LLM_ASSIST_REDESIGN.md` (section 2 "Tier 2", rollout row P5, evidence E2/E15),
`docs/superpowers/specs/2026-10-25-p3-story-dedup-design.md` (appendix A, embedding experiment) and
`docs/superpowers/specs/2026-10-25-p4-deterministic-extractors-design.md` (Tier 1, incident rule).

**Depends on P4** (branch `claude/p4-deterministic-extractors-336b29`, not merged when this was
written). P5 uses P4's `merge_industries` and its incident rule (`tier1/incident.py`). Implementation
starts after P4 merges; the P5 branch is rebased onto it.

## 1. Goal and success criteria

A local model decides, from the title alone, which articles are clearly threat news, and those skip
the LLM classify call. Everything else goes to the LLM as today. The model trains itself weekly on
each instance's own labels, runs in shadow first and turns the gate on (and off) automatically from
measured agreement. The same local embedding runtime is offered to the P3 story resolver.

Success (release gate, section 9):

1. On a held-out set of prod labels, the confident band covers at least 35% of titles with exact
   agreement with the LLM of at least 95%.
2. The story replay test passes with `STORY__EMBEDDING_SIMILARITY=0.8`.
3. On dev, a model trains and becomes active by itself and shadow mode records decisions.
4. After the gate turns on in prod, Data health shows the classify calls avoided (expected about
   35% of classify calls: band share x (1 - audit rate)).

## 2. Evidence behind the design (read-only, 2026-10-25)

Labels:

| Instance | Accepted | Rejected by the LLM | Failed enrichment (excluded) | Analyst overrides |
|----------|---------:|--------------------:|-----------------------------:|------------------:|
| dev (0.8.7) | 1,468 | 295 | 132 | 0 |
| prod (0.8.2) | 1,760 (247 best practice) | 370 | 35 | 0 |

Prod classify audit: 816 `gpt-4o`, 214 `openrouter/free`, 48 `vareon-prod`, 682 rows from before the
audit trail. Dev and prod largely scrape the same titles (2,123 unique when merged), and **112 titles
got different labels from the dev LLM and the prod LLM**: the label noise ceiling is around 6%. Merging
dev into prod adds nothing; each instance trains on its own data.

Offline experiment on the prod labels (5-fold CV; TF-IDF word 1-2 grams + char 3-5 grams, logistic
regression, `class_weight=balanced`; embeddings `sentence-transformers/all-MiniLM-L6-v2` via
`fastembed`, 3 ms per title on CPU):

| Model (3 classes: reject / best practice / threat news) | Band | Titles | Exact agreement |
|------|------|-------:|----------------:|
| TF-IDF, C=4 | p(threat news) >= 0.85 | 43% | 98.8% |
| TF-IDF, C=4 | p(threat news) >= 0.9 | 35% | 99.6% |
| embedding only, C=4 | p(threat news) >= 0.85 | 36% | 98.2% |
| TF-IDF + embedding, C=4 | p(threat news) >= 0.9 | 47% | 98.5% |
| TF-IDF + embedding, C=4 | p(threat news) >= 0.85 | 53% | 97.9% |

A time split (train up to 16 Oct, test the 426 titles after) gives the same picture. Two findings
shape the design:

- **The reject side is weak** in every variant (72-86% agreement at p(reject) >= 0.85): too few
  negatives. P5 does not reject without the LLM.
- **Best practice cannot be told from the title** (about 55% agreement). A two-class gate would
  route best-practice articles as threat news, so the model has three classes and only the
  "threat news" band skips the LLM.

## 3. Decisions taken in the brainstorm

| Question | Decision |
|----------|----------|
| Fields that classify fills besides relevance, for gated articles | Best practice false, industries from P4 keywords, countries from NER, `confirmed_incident` and `victim_name` from the P4 incident rule (option B) |
| Training data | Each instance's own database; prod's labels are the freshest and cleanest |
| Embeddings | In P5, for the gate and for story dedup (`union >= 0.8`) |
| Where training runs and the model lives | Weekly Celery task on `worker-nlp`; model stored in a `relevance_models` table; activated only when it passes the threshold |
| Shadow to gate | Automatic, both ways, from measured agreement |

## 4. Components

New package `cti_enrich/relevance/`: pure functions, no Session or HTTP, except one stage (same
pattern as P4's `tier1/`).

| Unit | Responsibility | Interface |
|------|----------------|-----------|
| `embedder.py` | Wraps `fastembed` `TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")` (ONNX, CPU, 384 dims, L2-normalised). Loaded once per process from the bundled cache directory with `local_files_only=True`, so there is no network access at run time. `fastembed` is imported lazily. Injectable for tests. | `get_embedder() -> Embedder`, `Embedder.embed(titles) -> ndarray` |
| `features.py` | Feature union: TF-IDF words (1-2 grams, sublinear) + TF-IDF characters (`char_wb` 3-5, `min_df=2`) + the embedding. The same object is used for training and prediction. | part of the sklearn pipeline |
| `model.py` | Logistic regression, three classes `reject` / `best_practice` / `threat_news`, `C=4`, `class_weight="balanced"`. Serialised with `joblib` to bytes. | `train(examples, embedder) -> TrainedModel`, `predict(model, title, embedder) -> Probs` |
| `dataset.py` | Builds labelled examples from the database (section 6). | `load_examples(session) -> list[Example]` |
| `gate.py` | Decision for one title: band, audit sample, current gate state. | `decide(probs, url_hash, state, cfg) -> GateDecision` |
| `stages/relevance.py` | The only unit that touches the database: loads the active model from `relevance_models` (cached per process, re-checked every 10 minutes), calls `predict` and `decide`. Any exception returns "no decision", which means the LLM. | `run_relevance(session, title, url) -> RelevanceResult` |

Story dedup: `story/similarity.py` gains `embedding_similarity(query, titles)` using the same
embedder. The resolver's title rule matches when TF-IDF >= `title_similarity` (0.5) **or** embedding
cosine >= `STORY__EMBEDDING_SIMILARITY`; `0` (default) disables it. A match found only by the
embedding records `story_match = "title_embedding"` (new value next to `cve`, `title_exact`,
`title`). The CVE veto, the other-source requirement and the windows are unchanged.

Out of scope: `classify_tweet` (tweets), rejecting without the LLM, analyst "mark irrelevant" on
accepted articles (no such action exists today), new pages beyond the Data health section.

## 5. Pipeline flow and the automatic gate

Position (on top of P4; the `pipeline.py` change is one call and one branch):

```
fetch_text -> resolve_story -> [Tier 0 | story inheritance | RELEVANCE -> (gated | LLM classify)]
           -> summarize -> extract_iocs -> tier1 -> ...
```

- `run_relevance` runs only on the branch that calls the LLM classify today. Tier 0 and story
  follow-ups are unchanged.
- Every run records `raw_enrichment["relevance"] = {model_id, probs, decision}` with `decision` in
  `shadow` (LLM called, gate off), `gated` (LLM skipped), `audit` (in band, LLM called as a sample),
  `llm` (outside the band). Rejected articles record it in `rejected_articles.raw_enrichment`.
- No active model, a model that fails to load or predict, or `RELEVANCE__MODE=off`: the LLM classify
  runs as today. Failure always falls back to the LLM.

A gated article (decision B):

- `ClassifyResult(related_cyber=True, security_tech_best_practice=False, industries_impacted=[],
  reason="relevance model p=0.93")` with `audit={"skipped": "relevance_gate", "model_id": ...,
  "p": ...}`. The existing `skipped` marker already keeps Tier 0 out of `stories.classify`
  (`stages/persist.py`), so a gated lead does not fill its story either, and the same marker keeps
  gated articles out of the training data.
- Industries: P4's `merge_industries` already stores keyword industries when the LLM list is empty.
- Countries: `persist` already falls back to `score_result.mentioned_countries` for victims when
  `victim_countries` is empty; the `actor` role stays empty.
- `confirmed_incident` and `victim_name` come from P4's incident verdict. `IncidentVerdict` gains a
  `victim` field; the source is recorded as `raw_enrichment["relevance"]["incident_source"] = "rule"`.
- The LLM TTP extraction still runs. P5 saves the classify call only.

Gate state lives on the active `relevance_models` row so every process sees the same value. Task
`relevance.evaluate` runs hourly:

| Transition | Condition |
|------------|-----------|
| shadow -> gate | `RELEVANCE__MODE=auto`, an active model, and in the last `GATE_WINDOW_DAYS` (14) at least `GATE_MIN_TITLES` (200) titles with p(threat news) >= `ACCEPT_THRESHOLD` and an LLM verdict, with exact agreement >= `GATE_MIN_AGREEMENT` (0.95) |
| gate -> shadow | among the last `REVERT_SAMPLES` (50) audit samples, agreement < `REVERT_MIN_AGREEMENT` (0.92); or `RELEVANCE__MODE` set to `shadow`/`off` |

- The window is 14 days because prod sees about 30 in-band titles a day.
- Agreement is counted per decision, whatever model version made it, so the weekly retrain does not
  reset the count. A newly activated model inherits the gate state of the model it replaces.
- **Audit sample**: in gate state, `AUDIT_RATE` (20%) of in-band titles still go to the LLM, picked
  deterministically from the URL hash. This keeps agreement measurable and makes the automatic revert
  possible. Effective saving: band share x 0.8, about 35% of classify calls.
- Every state change, a rejected training run and a model that fails to load send
  `send_alert("scraper_health", ...)` (the channel of the enrichment-failure alert) with a Redis
  dedupe, and log a line.

## 6. Dataset and weekly training

Labels (`dataset.load_examples`):

| Source | Class |
|--------|-------|
| `articles` with `news_type = "Security Technology & Best Practices"` | `best_practice` |
| other `articles`, including `news_type = "Manually Restored"` (analyst restore from Filtered) | `threat_news` |
| `rejected_articles` with `failure_kind IS NULL` and `reason` not starting with `[enrichment_failed]` | `reject` |

- Both reject conditions apply, because rows written before 0.8.5 have no `failure_kind`.
- An analyst override of `news_type` (`articles.overrides`) wins when present (none today).
- Excluded: classify audit with `skipped` (Tier 0 and gated: the model never learns from itself),
  classify inherited from a story (`inherited_from_story`), failed enrichment (this covers the
  dev quota-exhaustion period).
- Included: LLM verdicts from shadow, audit and middle-band titles. That is the "every LLM verdict
  on an uncertain title becomes training data" loop from the parent document.
- Titles are normalised (lowercase, collapsed whitespace) and deduplicated; on conflicting labels
  the most recent wins.
- Training runs only with at least `TRAIN_MIN_EXAMPLES` (1,000) examples and `TRAIN_MIN_PER_CLASS`
  (100) per class. Prod today: 1,513 / 247 / 370.

Training (`relevance.train`, `enrich` queue so it runs on `worker-nlp`, Sunday 02:00 local time;
`relevance.evaluate` also triggers it when no model is active, so a fresh deploy needs no manual
step; CLI `python -m cti_enrich.relevance.train [--dry-run]`):

1. Holdout: examples from the last `HOLDOUT_DAYS` (14); if fewer than 150, a stratified 20%.
2. Fit on the rest, measure on the holdout: band share, exact agreement in the band, per-class
   confusion.
3. Pass (agreement >= `GATE_MIN_AGREEMENT` and band share >= `MIN_BAND_SHARE` (0.2)): refit on all
   examples, store as `active`, previous active becomes `retired`. Fail: store as `rejected` with the
   reason; the previous model stays active.

Cost on prod's data: about 7 s to embed 2,130 titles plus a few seconds of fitting.

## 7. Data model (one Alembic migration)

`relevance_models`:

| Column | Detail |
|--------|--------|
| `id`, `created_at` | |
| `status` | `varchar(10)`: `active`, `retired`, `rejected`; checked in the repository (same convention as `ArticleCountry.role`) |
| `artifact` | `bytea`: the fitted sklearn pipeline via `joblib`, without the embedder (embeddings are computed at prediction time) |
| `feature_version` | `varchar(200)`: embedding model name and revision, `fastembed` and `scikit-learn` versions. A mismatch with the runtime means "no usable model" (LLM fallback) and triggers a retrain |
| `n_examples`, `class_counts`, `metrics` | `integer`, `jsonb`, `jsonb` |
| `gate_state`, `gate_changed_at` | `varchar(10)` `shadow`/`gate`, `timestamptz` |
| `reason` | `text`, why a run was rejected |

A unique partial index `WHERE status = 'active'` allows one active model. Rows other than the active
one are purged after 90 days by the same task. The artifact is a pickle read from the instance's own
database and written only by `relevance.train`; anyone who can write that table can already change
any enrichment result, so this adds no new trust boundary. It is stated here so the choice is
explicit.

## 8. Configuration, Data health and deployment

`RelevanceSettings` (all fields have defaults, so no new required `.env` key; changes need a worker
restart):

| Key | Default |
|-----|---------|
| `RELEVANCE__MODE` | `auto` (`off`: model not called; `shadow`: measure, never gate; `auto`: gate on/off by section 5) |
| `RELEVANCE__ACCEPT_THRESHOLD` | `0.85` |
| `RELEVANCE__AUDIT_RATE` | `0.2` |
| `RELEVANCE__GATE_MIN_TITLES`, `GATE_WINDOW_DAYS`, `GATE_MIN_AGREEMENT` | `200`, `14`, `0.95` |
| `RELEVANCE__REVERT_SAMPLES`, `REVERT_MIN_AGREEMENT` | `50`, `0.92` |
| `RELEVANCE__TRAIN_MIN_EXAMPLES`, `TRAIN_MIN_PER_CLASS`, `HOLDOUT_DAYS`, `MIN_BAND_SHARE` | `1000`, `100`, `14`, `0.2` |
| `STORY__EMBEDDING_SIMILARITY` | `0` (off); `0.8` once the replay test passes |

`.env.example` and `.env.prod.template` are updated in the same commit. To keep prod in shadow, set
`RELEVANCE__MODE=shadow` there before the deploy.

Data health gains a "Relevance model" section: mode and gate state (since when), the active model
(trained at, examples, holdout agreement and band share), the last 14 days (in-band titles with an
LLM verdict, agreement, middle-band size), agreement of the last 50 audit samples, classify calls
avoided over 24 h and 7 d. The story section adds matches by `title_embedding`. `DataHealthOut`
changes, so `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts` are regenerated.

Image and deployment:

- `fastembed` joins the `nlp` extra of `cti-enrich`; only `worker-nlp` loads the model. The API only
  reads the database.
- The model is baked into the `worker-nlp` image like NLTK `punkt_tab` (`docker/worker.Dockerfile`):
  a `RUN` step downloads `Qdrant/all-MiniLM-L6-v2-onnx` at a pinned revision into `/opt/fastembed`,
  then a smoke step loads it with `HF_HUB_OFFLINE=1`.
- **Needs the user's approval before implementation**: that download, about 87 MB from
  `huggingface.co`, on every `worker-nlp` image build (CI and the prod deploy). The plan's first step
  checks read-only (`curl -I`) that prod can reach `huggingface.co`, and measures the size of the new
  wheels (`fastembed`, `onnxruntime`, `tokenizers`) instead of guessing it here.
- One Alembic migration, version 0.8.9, CHANGELOG entry in Indonesian.
- Rollout: merge into `origin/Dev`, deploy; the model trains within the hour; run the story replay
  with embeddings, then enable `STORY__EMBEDDING_SIMILARITY=0.8` on dev; watch shadow on dev (dev has
  little volume, so the gate may never turn on there). Then the PR to `main`.

## 9. Testing and evaluation

CI installs `--extra dev` without `nlp`, so `fastembed` is not in the test environment:

- **Unit** (fake deterministic embedder, token-hash vectors):
  - `dataset`: exclusions (`skipped`, inherited, failed), "Manually Restored" as `threat_news`,
    override wins, title dedup with latest label.
  - `gate.decide`: thresholds, deterministic audit sample by URL hash, no model means LLM.
  - `relevance.evaluate` transitions: on at 200 titles / 95%, off below 92% over 50 audits, state
    inherited by a new model, `MODE=shadow` forces shadow.
  - `train`: accepted vs rejected run; `feature_version` mismatch means no model.
  - Pipeline: gated path makes no `classify` call and takes incident fields from the rule; `skipped`
    keeps the story empty; shadow still calls the LLM and records `relevance`; a model exception
    falls back to the LLM.
- **Integration** (Docker): migration matches models; the partial index allows one `active` row;
  `relevance.train` end to end on a seeded database with the fake embedder; Data health snapshot.
- **Story replay**: MiniLM vectors for the 1,390 titles of the P3 fixture are computed once and
  committed (`float16`, about 1 MB), so `tests/unit/test_story_replay.py` checks `union 0.8` without
  the model. Expected from P3 appendix A: about 194 follow-ups, PHP2Shell / NetScaler / Atlassian
  waves unchanged, Asec monthly reports still apart.
- **Image smoke**: the CI "in-image smoke import" step also loads the model with
  `HF_HUB_OFFLINE=1`, so a missing bundled model fails the build, not the deploy.

Evaluation: `tools/eval/relevance_eval.py` (not product code) runs on a read-only export of prod
labels, with outputs kept outside the repo (prod titles are not committed). It uses the product's
`train` and `decide`: a 14-day holdout plus 5-fold CV. Release gate: section 1 criteria 1-3. The
numbers go into `docs/LLM_ASSIST_REDESIGN.md` (P5).

## 10. Risks

- **Noisy labels.** The LLM disagrees with itself on about 6% of titles (section 2); agreement above
  that is not achievable and the 95% target sits below it on purpose. The confident band avoids
  most of the noise.
- **Missed incident fields.** Gated articles get `confirmed_incident` from a rule whose precision
  P4 measures; dashboards that count confirmed incidents mix LLM and rule values. The source is
  recorded so the two can be separated.
- **Drift.** New topics fall into the middle band (LLM) rather than the confident band; the audit
  sample and the revert rule catch a drop in agreement.
- **Build dependency on `huggingface.co`.** If the prod host cannot reach it, the image cannot be
  built there; the plan's first step checks this before any code is written.
