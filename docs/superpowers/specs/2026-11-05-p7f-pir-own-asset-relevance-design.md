# P7f: PIR at ingest and own-asset relevance (design)

Status: **design, awaiting review** (2026-11-05). Part of release **0.8.11** (no version bump; P7
sub-projects share one release). Branch `nameless/p7f-pir-relevance` on `main` `0b26f7c`.

Source documents: `docs/LLM_ASSIST_REDESIGN.md` section 4 items 5 and 7, P7 decomposition in
`docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md` section 0 (row P7f), P6 scoring
in `docs/superpowers/specs/2026-10-26-p6-admiralty-confidence-design.md`, tech matchers in
`docs/CVE_TRACKER_FLOW.md` section 9.

## 1. Goal and success criteria

An article that answers one of our Priority Intelligence Requirements, or that concerns technology we
run, ranks higher in "Perlu dibaca" (dashboard) and the Newsroom front section, and the grade chip says
why. Today PIRs are matched only at read time (PIR page, PIR Telegram alert) and the techstack check in
`stages/score.py` (`related_tech_status`) only picks a Telegram topic; neither touches `priority_score`.

Success criteria:

- `priority_score` gains two signals, `pir_match` and `own_asset` (section 3), computed by the same P6
  path (`confidence.assess` via `repositories/assessment.py`) at persist, story refresh, daily and
  manual recompute.
- The set of articles carrying `pir_match` for a PIR equals the set the PIR page lists for that PIR
  (same `_apply_list_filters` semantics), for every PIR that is active today.
- On dev after a recompute: articles with `pir_match` = articles listed by PIR #5 on that date;
  articles with `own_asset` in the last 30 days >= 80 (the title path alone gave 80 of 1,331 on the
  2026-11-05 survey); the top 10 of `sort=priority` is explainable from `score_reasons`.
- The P6 replay test (`tests/unit/test_confidence_replay.py`) stays green unchanged.
- No migration, no new `.env` key; code from before P7f reads rows written by P7f without error.
- A client never sees another client's PIR titles or techstack names.

## 2. Decisions (brainstorm 2026-11-05)

| # | Question | Decision |
|---|---|---|
| D1 | Boost global or per client? (`articles` has no `client_id`, `priority_score` is global; PIRs and techstack are per client) | **Global.** A match against any client's PIR or techstack raises the one `priority_score`. Matched details are stored with their `client_id` and filtered per client in the API (section 5). |
| D2 | What is "own asset"? | **Title mentions an active techstack name** (whole word, `cti_core.tech_match.mentions_any`) **or the article mentions a CVE with a non-FP `cve_tracker` row whose `tech` matches an active techstack name.** Body text is excluded (too noisy: "Linux", "nginx"). |
| D3 | Weights | `pir_match`: P1 20, P2 15, P3 10, P4 5, best PIR only (not summed). `own_asset`: 15 flat. |
| D4 | Where matching runs | **In the P6 facts loader**, no new table. Alternatives rejected: match tables written at persist (migration, second source of truth, separate invalidation on PIR edit); matching in `score.py` (not repeatable by recompute without the text, collides with P7g's pipeline changes). |

Dev data (read-only, 2026-11-05): 1 client (`default`), 1 active PIR (#5, P2, `threat_actors:
["Shinyhunters"]`, 11 titles name it in 30 days), 35 active techstack entries, 554 `cve_tracker`
rows, 2,040 articles; `priority_score` median 70, p90 101, p99 126. Top title hits in 30 days: Linux
27, gitlab 17, fortinet 7, microsoft 365 7, palo alto 6.

## 3. Scoring (`cti_core.confidence`)

New frozen dataclasses and `ArticleFacts` fields (defaults keep every existing caller and the replay
fixture valid):

```python
@dataclass(frozen=True, slots=True)
class PirHit:
    id: int
    title: str
    priority: str  # "P1".."P4"
    client_id: str


@dataclass(frozen=True, slots=True)
class AssetHit:
    name: str  # techstack entry name as stored
    client_id: str


# ArticleFacts
pir_hits: tuple[PirHit, ...] = ()
own_asset_hits: tuple[AssetHit, ...] = ()
```

Constants: `PRIORITY_PIR = {"P1": 20, "P2": 15, "P3": 10, "P4": 5}` (unknown priority = P4 points),
`PRIORITY_OWN_ASSET = 15`.

`assess()`:

- if `pir_hits`: signal `("pir_match", max points over hits)`;
- if `own_asset_hits`: signal `("own_asset", 15)`;
- both join the existing `signals` list (same sort, same sum into `priority_score`).
- `reasons` gains `"pir"`: hits sorted by (priority, id), each `{id, title, priority, client_id}`;
  `"own_asset"`: hits sorted by (name, client_id), deduplicated, at most 5,
  each `{name, client_id}`. Keys are present only when non-empty.

Confidence, reliability, credibility and the Admiralty code are unchanged: relevance to us is not
evidence that a report is true.

## 4. Loader and recompute (`cti_core.db.repositories.assessment`)

The P6 pattern stays: statements are built once by plain helpers, the sync (`apply_assessments`) and
async (`apply_assessments_async`) runners differ only by `await`. Per batch (<= 500 ids, as today):

1. `facts_stmt` adds `Article.title`.
2. `active_pirs_stmt(today)`: `pir_requirements` with `status='active'`, `start_date` null or
   `<= today`, `end_date` null or `>= today`. Rows whose criteria have no non-empty list
   (`_has_criteria`) are skipped (match-all, same rule as the PIR alert). A criteria value that is not
   a list of strings is treated as empty, so a malformed JSONB never fails a batch (same spirit as
   `_override_int`).
3. Per PIR: `select(Article.id).where(Article.id.in_(ids))` passed through the same
   `_apply_list_filters(posted_on_start=pir.start_date, posted_on_end=pir.end_date,
   **_criteria_filters(criteria))`, exactly what `AsyncPIRRepo.list_articles_for_pir` passes to
   `list_filtered` (both helpers made importable without a cycle; no second query builder). So an
   article posted outside the PIR's date window does not match even while the PIR is active.
4. `active_techstack_stmt()`: `(name, client_id)` of `techstack_entries` with `active = true`.
5. `tracked_cve_techs_stmt(ids)`: `(article_id, cve_tracker.tech, cve_tracker.client_id)` through CVE
   mentions (`mention_rows(CVE)`), excluding rows marked FP (`is_false_positive_row`), `tech` not null.
6. In Python: title hit = `mentions_any([name], title)` per active entry; CVE hit = tracker `tech`
   matched by `mentions_any` against the active names of the same client (so `active=false` entries
   never count, the CVEs-tab invariant). Results become `pir_hits` and `own_asset_hits`.

`today` is the UTC date at run time. Re-assessing an old article applies today's PIRs and techstack;
that is intended (relevance as of now).

When scores are recomputed:

- **Ingest**: unchanged call, `persist.py` already runs `apply_assessments` for the new article.
  No file of the enrichment pipeline changes (P7g, PR #84, owns those).
- **Story refresh** (every 10 min) and **`confidence.recompute_all`** (daily, after deploy while any
  article is unassessed): pick up the new facts through the same loader. The daily run also covers PIRs
  whose date window opens or closes.
- **PIR create/update/delete** (`routers/pir.py`) and **techstack create/update/delete, target add/
  remove, active toggle** (`routers/techstack.py`): after commit, call `send_recompute_all()`; an
  enqueue failure is logged (`recompute_all_enqueue_failed`) and the request still succeeds, as in
  `routers/source_reliability.py`. No debounce: a full recompute is 5 batches on dev.

## 5. API and web

`schemas/article.py`:

```python
class PirReason(BaseModel):
    id: int
    title: str
    priority: str


class ScoreReasons(BaseModel):
    credibility: list[str] = []
    priority: list[PriorityReason] = []
    pir: list[PirReason] = []
    own_asset: list[str] = []
```

The serializer that fills `ArticleOut.score_reasons` keeps only `pir` and `own_asset` entries whose
`client_id` equals the request's effective client (`deps.effective_client_id`) and drops `client_id`
from the output. The `priority` list (points) is not filtered: under D1 another client may see
"PIR match +15" without the PIR behind it. That is the accepted limit of a global score; revisit if a
second client with its own PIRs goes live. `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts`
are regenerated.

Web (`components/newsroom/score-reasons.ts`, `article-modal.tsx`): `PRIORITY_TEXT` adds
`pir_match: "PIR match"`, `own_asset: "own asset"`; the modal's "Why this grade" section lists matched
PIR titles with priority and matched tech names. No new component. Checked on dev in light and dark
and at narrow width.

## 6. Error handling and compatibility

- Malformed PIR criteria: PIR skipped for scoring, batch continues.
- Old code reading new rows: `score_reasons` is JSONB; P6's `ScoreReasons` ignores unknown keys
  (pydantic default), so a rollback image serves the same rows. Old scores keep the P7f points until
  the next recompute by the old code, which removes them. No DB downgrade needed.
- Prod can deploy without new keys; the recompute after deploy is a runbook step.

## 7. Testing

- Unit (`tests/unit/test_confidence*.py`): points per PIR priority, best PIR only, unknown priority,
  own asset flat 15, combined with existing signals, reason shape and ordering, cap of 5 names,
  empty keys absent.
- Integration (testcontainers, `tests/integration/`):
  - PIR hit set equals `list_articles_for_pir` for actor, malware, TTP, keyword, country, industry and
    combined criteria;
  - PIR inactive, outside its dates, or without criteria gives no hit; malformed criteria give no hit
    and no error;
  - title path and CVE path hit; FP tracker row and `active=false` entry do not;
  - sync and async runners return identical assessments.
- API: PIR and techstack mutations enqueue `send_recompute_all` (mocked), enqueue failure keeps the
  response 2xx; `ArticleOut.score_reasons` shows only the effective client's PIR and tech entries.
- Replay: `test_confidence_replay` unchanged and green.
- Suites: `uv run pytest tests/unit tests/contract packages`, integration in background, ruff, mypy,
  web lint/typecheck/build, API contract drift.

## 8. Release and docs

- `CHANGELOG.md` `## [0.8.11]` (Indonesian): new bullet for P7f.
- `docs/prod-upgrade/0.8.11.md` and the 0.8.11 section of `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`: no
  migration, no keys; after deploy run `POST /api/articles/confidence/recompute` once (or wait for the
  daily run); check that `score_reasons` carries `pir`/`own_asset` on matching articles.
- `docs/LLM_ASSIST_REDESIGN.md`: P7 row and section 4 items 5 and 7 marked partly delivered; P7a spec
  section 0 row P7f points to this spec.
- Dev: merge to `origin/Dev`, deploy, recompute, read-only checks of section 1; then PR to `main`.
  All outward steps need the user's approval.

## 9. Out of scope

- PIR matches unlocking Tier 3 LLM TTP extraction (item 5): touches the LLM path P7g is reworking.
- Weekly PIR coverage report; RFI linked to PIR and stories.
- The dashboard "Tech stack" badge, which is matched client-side (`useArticleMatchers`); it may later
  read `score_reasons.own_asset` instead.
- Per-client priority scores (rejected in D1).
- Joining stories (not just articles) to the techstack catalog beyond the CVE path.
