# P6 confidence that means something: Admiralty per article, priority for ranking

Date: 2026-10-26. Status: design approved in chat, awaiting review of this written spec.
Release: the next free **0.8.x** after P5 (one PR, merged into `origin/Dev` and tested on the dev
instance first, opened against `main` after the P5 PR has merged).
Parent documents: `docs/LLM_ASSIST_REDESIGN.md` (section 3 "Confidence that means something",
rollout row P6, evidence E7 and E11), `docs/TARGET_ARCHITECTURE.md` (priority score, step 6) and
`docs/UI_DATA_AUDIT.md` (U5, U15). Builds on P2 (default grades, `content_kind`), P3 (`stories`,
`source_count`) and P4 (TTP `source`).

**Coordination with P5** (branch `claude/p5-relevance-model-a447e0`, in dev testing). P5 changes
`cti_enrich/pipeline.py`, `stages/persist.py` and `story/attach.py`. P6 does not touch the pipeline
or `story/attach.py`; in `stages/persist.py` it replaces only `_confidence_score` and its call. This
branch is rebased on `main` after P5 merges.

## 1. Goal and success criteria

Today an article's "B2 · 72" is the **source's** grade plus a bonus for TTPs and actors. The
credibility digit is a per-source constant (every Hackernews article is C3, every vendor article
B2), which is not what Admiralty credibility means, and the bonus saturates the score: 245 of
1,542 dev articles sit at exactly 100, so the dashboard "Perlu dibaca" ranking bunches at the top
(U5).

P6 splits the number in two:

- **Confidence**: pure Admiralty. Reliability A-F from the source grade, credibility 1-6 computed
  per article from corroboration, primary vs aggregator, and technical artefacts.
- **Priority**: confidence plus relevance signals (confirmed incident, KEV/PoC, TTPs, actor,
  corroboration), stored, uncapped, used for sorting.

It also gives analysts a review workflow to confirm or refine the default source grades.

Success:

1. Every article has a reliability grade and a credibility code; the UI shows the code (for
   example `C1`) on every place an article appears (dashboard, Newsroom front section and list,
   article modal).
2. On the dev snapshot (section 8.2): no single priority value holds more than 20% of articles
   (ties remain legitimate at the bottom, where articles have no signal at all), the top 10% of
   articles by priority span at least 20 distinct values (today the top 10% sit on 95-100), at
   least 8 distinct Admiralty codes occur, and the top 10 of any week by priority, collapsed per
   story, covers at least 5 distinct stories.
3. The Source reliability page lists every `default` grade with its statistics and a suggested
   grade, and an analyst can confirm it in one click.

### 1.1 Evidence (dev 172.25.1.77, read-only, 2026-10-26, 1,542 articles)

| Fact | Number |
|------|--------|
| Score distribution today | 371 at 60, 694 at 75-80, 273 at 95-100 (245 exactly 100) |
| Source grades | 78 default B2, 8 A2, 6 C3, 4 D4, 1 A1 default, 3 analyst A1 |
| Article codes today | C3 740, B2 720, A1 52, A2 30 |
| Single-source, no CVE / non-suppressed IOC / explicit-or-llm TTP | 571 (37%) |
| Articles in a multi-source story | 261 (17%); one story has 28 sources |
| TTP rows by source | explicit 769, llm 2,304, keyword 663 |

Simulated with the rules below: 10 codes (A1 59, A2 22, A3 1, B1 53, B2 280, B3 387, C1 70, C2 52,
C3 256, C4 362), confidence spread over 40-90 in six values, priority 40-141 with 85 distinct
values (most common value 60, 260 articles = 17%: single-aggregator articles with no signal; the
top 10% span 32 distinct values, 100-141).
Uncollapsed, the top 10 of 19-26 Oct was all PHP2Shell, which is why ranking collapses per story
(section 5.2).

## 2. Scoring model (`cti_core.confidence`, pure functions)

One pure function `assess(facts: ArticleFacts) -> Assessment`, used by enrich persist (sync,
worker) and by recompute (async, API service), so the formula exists once. No I/O.

`ArticleFacts`:

| Field | Meaning |
|-------|---------|
| `reliability_grade` | source grade A-F, `None` if the source has no row |
| `content_kind` | source's `content_kind`, `None` if unknown |
| `story_source_count` | `stories.source_count` of the article's story, 1 without a story |
| `has_cve` | article has a row in `article_cves` |
| `has_ioc` | article has a non-suppressed IOC (`ioc_sources` join `iocs.auto_suppressed = false`) |
| `explicit_ttp_count` | TTP rows with `source = 'explicit'` |
| `bonus_ttp_count` | TTP rows with `source in ('explicit', 'llm')` (existing `BONUS_TTP_SOURCES`) |
| `has_actor` | at least one `article_threat_actors` row |
| `confirmed_incident` | `articles.confirmed_incident` |
| `kev`, `poc` | any of the article's CVEs is KEV / has a public PoC (`AsyncCveTrackerRepo.exploit_flags` semantics: tracked CVEs only, FP rows ignored) |
| `credibility_override` | `overrides["credibility"]` (1-6) or `None` |
| `confidence_override` | `overrides["confidence_score"]` (P2 analyst value) or `None` |

`Assessment`: `reliability_grade` (A-F), `credibility` (1-6), `confidence_score` (int),
`priority_score` (int), `reasons` (section 3.1 shape). `admiralty_code` is a property
`f"{reliability_grade}{credibility}"`.

### 2.1 Reliability

The source grade; `F` ("cannot be judged") when the source has no `source_reliability_entries`
row. Unchanged from P2 apart from the F fallback.

### 2.2 Credibility (rule ladder, first match wins)

Definitions:

- **Artefact**: `has_cve` or `has_ioc` or `explicit_ttp_count > 0`. LLM and keyword TTPs do not
  count (measured precision 35% and 70%, P4 evaluation).
- **Primary**: `content_kind in {kev, advisory, vendor_research, exploit}`. `news`,
  `vendor_marketing`, `social` and unknown are not primary.

| Code | Admiralty meaning | Rule | Reason codes |
|------|-------------------|------|--------------|
| (override) | | `credibility_override` set | `analyst` |
| 6 | Cannot be judged | no source grade | `ungraded` |
| 1 | Confirmed | `content_kind == 'kev'`, or `story_source_count >= 3` and artefact | `official`, `corroborated_3` + artefact codes |
| 2 | Probably true | `story_source_count >= 2` and artefact, or primary and artefact | `corroborated_2` / `primary` + artefact codes |
| 3 | Possibly true | primary, or artefact, or `story_source_count >= 2` | `primary` / artefact codes / `corroborated_2` |
| 4 | Doubtful | otherwise (single aggregator source, no artefact) | `single_aggregator` |
| 5 | Improbable | only via analyst override | `analyst` |

Artefact reason codes: `cve`, `ioc`, `explicit_ttp` (all that apply).

The per-source `credibility_code` stored on `source_reliability_entries` is no longer used for
scoring (section 4.2).

### 2.3 Confidence score

STIX 2.1 Admiralty-to-confidence scale for both halves: A/1 = 90, B/2 = 70, C/3 = 50, D/4 = 30,
E/5 = 10, F/6 = 50 (neutral). `confidence_score = round((rel + cred) / 2)`, so always 10-90.

`confidence_override` (P2) wins: `confidence_score` = the override value. Credibility and
priority are still computed (priority uses the overridden confidence).

### 2.4 Priority score

`priority_score = confidence_score + points`, no upper cap, no time factor (the dashboard and
Newsroom already filter by period with `posted_on_start`):

| Signal | Points | Reason code |
|--------|--------|-------------|
| `confirmed_incident` | +25 | `confirmed_incident` |
| `kev` | +15 | `kev` |
| `poc` (only when not `kev`) | +8 | `poc` |
| `bonus_ttp_count` | +3 each, max 12 | `ttps` |
| `has_actor` | +8 | `actor` |
| `story_source_count - 1` | +4 each, max 16 | `corroboration` |

Weights are module constants next to the existing ones, so they can be tuned in one place. The
old `compute_score` and its TTP/actor bonus are removed; `BONUS_TTP_SOURCES` /
`bonus_ttp_count` stay (used for the TTP points).

## 3. Storage

### 3.1 `articles` (one additive migration, model updated)

| Column | Type | Notes |
|--------|------|-------|
| `reliability_grade` | `varchar(1)` null | snapshot of the source grade when assessed |
| `credibility` | `smallint` null, check 1-6 | |
| `priority_score` | `smallint` null, indexed (`priority_score desc nulls last`) | |
| `score_reasons` | `jsonb` not null default `'{}'` | `{"credibility": ["corroborated_3", "ioc"], "priority": [{"code": "kev", "points": 15}, ...]}` |

`confidence_score` stays, with the meaning of section 2.3. All new columns are nullable; the
migration does not backfill (section 4.4 does). `NULL` credibility marks "not yet assessed".

### 3.2 `source_reliability_entries`

- New `content_kind varchar(20) null`. The API bootstrap (`ensure_defaults`, already under the
  advisory lock) fills it from the scraper registry for every row whose name matches a
  `meta.source` (case-insensitive), default and analyst rows alike, and refreshes it on every
  start. Non-scraper sources (for example CYFIRMA) stay `NULL` and count as not primary.
- `credibility_code` and `admiralty_code` are kept (no destructive migration) but no longer drive
  scoring. New and confirmed rows keep writing them as before so existing readers do not break;
  the edit form stops asking for credibility and the API defaults it from the P2 mapping.

## 4. When scores are computed

### 4.1 Enrich persist

`stages/persist.py`: `_confidence_score(...)` is replaced by a helper that builds `ArticleFacts`
(source grade and `content_kind` from `SourceReliabilityRepo`, story `source_count` read after
`StoryRepo.attach` has run, artefacts from the merged TTPs, IOCs and CVEs being persisted, KEV/PoC
from a sync `exploit_flags` equivalent) and writes the four columns plus `confidence_score`. This
is the only change in persist.

### 4.2 Older story members

When a new source joins a story, the credibility and priority of the existing members change.
Instead of touching `story/attach.py`, a new beat task **`confidence.refresh_stories`** (every
10 minutes, `maintenance` queue) recomputes all articles of stories whose `updated_at` is newer
than the last successful run. `attach` already sets `updated_at = now()`. The watermark is kept in
Redis and advanced only after a successful run, so a failed run is retried by the next one.
Members are at most 10 minutes stale.

### 4.3 Changes outside the article

- Source grade created, edited or confirmed: the existing `confidence.recompute_source`.
- KEV/PoC flags (CVE enrichment), IOC suppression, `content_kind` changes: the existing
  `confidence.recompute_all`, now also scheduled **daily** in beat (paging 500, commit per batch;
  1,542 articles on dev).

### 4.4 After deploy

The API bootstrap already enqueues `confidence.recompute_all` when new default grades appear.
P6 adds a second trigger: if any article has `credibility IS NULL`, enqueue it once. No new `.env`
key.

### 4.5 Overrides and errors

- Every path calls `assess`, so `overrides["credibility"]` and `overrides["confidence_score"]`
  are respected everywhere.
- A failed KEV lookup in persist is treated as `kev = poc = false`; the daily recompute corrects it.
- `assess` is pure and cannot fail on I/O.

## 5. API

### 5.1 Article shapes

`ArticleOut`:

- `admiralty_code` becomes the **article's** code (`reliability_grade + credibility`), same
  field name so the web keeps compiling; `None` only before the first assessment.
- New: `reliability_grade`, `credibility` (int), `priority_score`, `score_reasons`.
- `grade_origin` stays and means the origin of the **source** grade (`default` | `analyst`).
- `confidence_score` stays (section 2.3 meaning).

New endpoint **`PUT /api/articles/{id}/credibility`** (`manage_intel`): body
`{"credibility": 1-6 | null, "note": str}`. Sets or clears `overrides["credibility"]`,
re-assesses the article, writes an audit-log entry (`action="set_credibility"`). There is no
generic article PATCH today; this follows the existing `POST /articles/{id}/confidence` pattern.

The existing `POST /articles/{id}/confidence` and `POST /articles/confidence/recompute` keep
their routes and now run `assess`.

### 5.2 Ranking

`AsyncArticleRepo.list(sort="priority")` (dashboard "Perlu dibaca", Newsroom front section):

- order `priority_score desc nulls last, posted_on desc nulls last, id desc`;
  `confirmed_incident` is no longer the first key (it is +25 inside priority);
- **one article per story**: `DISTINCT ON (coalesce(story_id, -id))` keeping the member with the
  highest priority, then ordered as above; `total` counts collapsed rows. The "+N sources" badge
  (P3) shows the rest. `sort="recent"` and every other list are unchanged.

`list_top_between` (weekly recap candidates) orders by `priority_score` instead of
`confirmed_incident, confidence_score`, without story collapse (the recap already groups).

Other readers of `confidence_score` (STIX `confidence`, newsletter ranking, campaign average)
need no code change; the scale is still 0-100. Newsletter ranking gives points only above 50, so
fewer articles get them; this is intended.

### 5.3 Source review (`manage_sources`)

**`GET /api/sr/review`**: every `origin='default'` row with 30-day statistics:

| Statistic | Source |
|-----------|--------|
| `articles` | accepted articles of the source |
| `rejected_pct` | `rejected_articles` of the source excluding `[enrichment_failed]`, over articles + rejected |
| `artefact_pct` | share of articles with an artefact (section 2.2) |
| `multi_source_stories`, `lead_count` | stories with `source_count > 1` the source is in, and how many it led (`lead_article_id`) |
| `ioc_fp_pct`, `ioc_verdicts` | FP share of IOC feedback on IOCs first reported by the source |

plus `suggested_grade` and `suggestion_reasons`. Suggestion rules (module constants in
`cti_core.confidence`, first match wins, `null` when `articles < 10`):

| Suggestion | Rule | On dev today |
|------------|------|--------------|
| one grade lower | `rejected_pct >= 30` and `artefact_pct < 30` | Dfirch, Sophos, Akamai, Forcepoint, Sans, Cymru, Cloudflare |
| one grade lower | `ioc_verdicts >= 5` and `ioc_fp_pct >= 20` | no data yet |
| C to B | `multi_source_stories >= 5` and `lead_count / multi_source_stories >= 0.5` | Bleeping Computer (19/34) |
| keep | otherwise | |

The system never suggests A; only an analyst sets A. The rejected rate measures off-topic
content (marketing, best practice), not inaccuracy; the UI says so in the column help.

**`POST /api/sr/entries/{id}/confirm`**: body `{"reliability_grade": "A"-"F" | null}`. Sets
`origin='analyst'`, `analyst_name` = the signed-in user, optionally the new grade (also
`admiralty_code` for old readers), and enqueues `confidence.recompute_source` when the grade
changed. Audit-logged.

`docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts` regenerated.

## 6. Web

- **`GradeChip`** shows the article's code and priority, `C1 · P131`, coloured by reliability.
  Tooltip: source reliability with origin (`Source reliability C (default)`), credibility with its
  reasons (`Credibility 1: 3+ independent sources, IOC present`), confidence, and the priority
  breakdown (`Priority 131: KEV +15, 7 more sources +16, ...`). Reason codes map to English text
  in one place in the web.
- The chip appears on the dashboard "Perlu dibaca" card and Newsroom front section (today), plus
  **the Newsroom list rows and the article modal** (new).
- Article modal: a small "Why this grade" section listing the reasons, and for `manage_intel`
  users a credibility override select (1-6 or "computed") with a note, calling
  `PUT /api/articles/{id}/credibility`.
- Source reliability page: a "Needs review" tab with the statistics, suggested grade and reasons,
  and "Confirm" (current or suggested grade) / "Edit" actions. The entry dialog no longer asks
  for credibility.
- Light and dark theme checked; no `backdrop-blur`; Base UI conventions (`apps/web/CLAUDE.md`).

## 7. Out of scope

- Detecting contradictions between sources (credibility 5 stays analyst-only).
- Grade suggestions from Splunk sightings.
- PIR and techstack exposure in priority (P7).
- `stories.credibility` / story-level priority (`docs/TARGET_ARCHITECTURE.md`); credibility stays
  per article, with the story as one input.
- Dropping `source_reliability_entries.credibility_code`.

## 8. Testing

### 8.1 Unit

- `assess`: every ladder row and its boundaries (2 vs 3 sources, artefact kinds, primary kinds,
  `kev` source, ungraded source, credibility override including 5, confidence override still
  yielding credibility and priority); confidence scale; each priority signal and its cap; reasons
  shape.
- Suggestion rules: each row, `null` under 10 articles, never A.
- Beat schedule contains `confidence.refresh_stories` (10 min) and daily `confidence.recompute_all`.

### 8.2 Replay fixture

`tests/fixtures/confidence_replay/dev_2026-10.csv`: the per-article facts of the 1,542 dev
articles (id, posted_on, story id, source grade, `content_kind`, artefact flags, counts, KEV/PoC,
confirmed incident; no titles or URLs). A unit test runs `assess` over it and asserts the three
targets of section 1 (success 2); the per-week story check uses `posted_on` and the story id in
the fixture.

### 8.3 Integration (testcontainers)

- Migration and `test_migrations_match_models.py`.
- Persist writes reliability, credibility, confidence, priority and reasons.
- `refresh_stories` raises an older member to credibility 1 after a third source joins.
- `sort=priority` returns one article per story, in priority order, with a correct `total`.
- `GET /api/sr/review` statistics and suggestions on seeded rows; `confirm` sets origin, analyst
  and enqueues recompute on grade change.
- `PUT /articles/{id}/credibility` sets and clears the override and audit-logs it.
- Bootstrap enqueues `recompute_all` while unassessed articles exist.
- Router snapshots updated.

### 8.4 Web and dev

- `pnpm lint`, `next typegen && tsc --noEmit`, `pnpm build`.
- On dev after merging to `origin/Dev` (with the user's approval): read-only queries for the
  priority and code distribution, the "Perlu dibaca" card and Newsroom in light and dark, the
  "Needs review" tab showing the suggestions of section 5.3 (or their current equivalents).

## 9. Release

Next free 0.8.x after P5, usual version bump in every package, Indonesian CHANGELOG entry. Upgrade
notes: one additive migration (nullable columns, no backfill in the migration); every article is
re-assessed once by the bootstrap-triggered `recompute_all`; article confidence scores change
meaning and drop (10-90); the dashboard ranks one article per story; no new `.env` keys. Update
`docs/LLM_ASSIST_REDESIGN.md` (Progress, P6 row) and `docs/TARGET_ARCHITECTURE.md` (step 6).
