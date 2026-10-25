# P3 story dedup at ingest: one enrichment per story

Date: 2026-10-25. Status: design approved in chat, awaiting review of this written spec.
Release: **0.8.7** (one PR, merged into `origin/Dev` and tested on the dev instance first, opened
against `main` only after the P2 PR has merged).
Parent documents: `docs/LLM_ASSIST_REDESIGN.md` (section 2 "Story dedup before enrichment", rollout
row P3, evidence E5 and E16), `docs/TARGET_ARCHITECTURE.md` (story resolver, `stories`) and
`docs/UI_DATA_AUDIT.md` (U12, U25).

**Depends on P2** (0.8.6, branch `claude/p2-cheap-wins`, HEAD `48f2600`, on `origin/Dev`, not yet
on `main`). This branch is rebased on it. P3 uses P2's `article_cves` for the backfill, P2's
`default_relevance` for the Tier 0 rule in section 4.3, and its migration follows P2's head
`f3c9e1b5a7d2`.

## 1. Goal and success criteria

The same event reported by many sources is today enriched once per article: classify and TTP
extraction run on the LLM for every copy. P3 groups articles into **stories** at ingest, with
deterministic keys only, and lets a follow-up article of a known story inherit the lead's
classification and skip both LLM calls. Follow-ups stay full articles, so their IOCs, CVEs and
alerts are not lost.

Success:

1. The replay test (section 7) on a snapshot of dev data puts at least 22 of the 24 PHP2Shell
   articles in one story, CVE-2026-88771/88772 (NetScaler) at least 14 and CVE-2026-21589
   (Atlassian) at least 8, and does not merge the Asec monthly trend reports with each other.
2. After the backfill on dev, the PHP2Shell story has 23 members and `source_count >= 15`.
3. A new wave on dev produces at most 2 `classify` calls per story (the lead, plus one follow-up
   that may arrive while the lead is still being enriched), visible in `llm_calls` and the classify
   audit. The OpenRouter free quota on dev is exhausted at the time of writing, so this one can only
   be judged after the quota recovers; until then 1 and 2 are the evidence.
4. `STORY__ENABLED=false` restores the 0.8.6 pipeline exactly.

## 2. Evidence (dev 172.25.1.77, read-only, 2026-10-25)

| Fact | Number |
|------|--------|
| Accepted articles on dev | 1,451 (2026-09-26 to 2026-10-24) |
| Articles sharing a CVE with another article in the previous 72 h | 186 (13%) |
| PHP2Shell wave | 24 articles, 21-24 Oct; 23 share CVE-2026-109618/109619 in the body, only 4 titles contain a CVE; 1 (id 1278, Hackernews "What Actually Protects You...") has no CVE and a best title similarity of 0.22 |
| Other waves (shared CVE, 72 h) | NetScaler 15, ShinyHunters/PeopleSoft 8, Atlassian 7, Ivanti 6, Zammad 6, Apple 6 |
| CVEs per article | 1: 149, 2-3: 133, 4-10: 79, >10: 21 (roundups such as "ThreatsDay") |
| Average tokens per call | classify ~3,870 in + 670 out; TTP ~3,500 in + 1,020 out (the two calls cost about the same) |
| `articles` body text | not stored (only `raw_enrichment.classify`), so the backfill uses `article_cves` |

Simulation of resolver rules over all 1,451 articles in arrival order (scripts kept outside the
repo; the replay test in section 7 replaces them):

| Rules | Follow-ups (skip LLM) | Precision notes |
|-------|----------------------|-----------------|
| CVE only | 135 | clean, misses stories without CVEs (breaches, campaigns) |
| CVE + title >= 0.5, no age cap, + actor + title >= 0.25 | 229 | chained stories (NetScaler grew to 28 over four weeks), same-source series merged, actor rule merged the Qilin arrests in Japan and Germany |
| **CVE + exact title + title >= 0.5 across sources + story age <= 7 days** | **180 (12%)** | about 55 of 60 title merges correct; the misses are Threatmon/Asec monthly reports and the later NetScaler SAML zero-day, which the CVE veto (section 3.2) blocks |

## 3. Resolver

### 3.1 Units

| Unit | Content | Depends on |
|------|---------|------------|
| `cti_core/db/models/story.py` | `Story` model (section 5) | - |
| `cti_core/db/repositories/story.py` | `StoryRepo`: `candidates(now)` (stories in the window with their member titles and sources), `create`, `attach` (counts, `cve_ids`, lead, classify), `discard_if_empty`, `purge_empty(older_than)` | model |
| `cti_enrich/story/similarity.py` | `title_similarity(titles: list[str]) -> matrix`; TF-IDF (word, English stop words, sublinear tf) fitted on the candidate titles plus the new one. Years, month names and generic period/report words (report, weekly, quarter, q1-q4, trend, ...) join the stop list, so two "September 2026 report" titles do not look alike. This is the swap point for an embedding model later (section 8) | scikit-learn |
| `cti_enrich/story/resolver.py` | pure `resolve(keys: ArticleKeys, candidates: list[Candidate], now) -> Match | None`, no DB, so it is unit-testable and replayable | similarity |

`scikit-learn` becomes an explicit dependency of `cti-enrich`; it is already in `uv.lock` through
`cti-api`, so no new package enters any image. `apps/api/.../services/dedup.py` and `cluster.py`
are not changed: they are read models of other pages, outside P3.

### 3.2 Rules

`ArticleKeys` = normalised title, source, CVE ids from title and body (uppercase), arrival time.
The rules run in order; the first match wins.

1. **Candidates**: stories with `last_seen_at >= now - 72 h` and `first_seen_at >= now - 7 days`.
2. **CVE**: the article's key CVEs are its CVEs only if there are at most 5 (more is a roundup and
   gives no key). Match a story when at least 50% of the key CVEs are in `stories.cve_ids`. Several
   matches: the largest overlap, then the story with more members (it is the established wave), then the lowest story id. `match = "cve"`.
3. **Exact title**: the normalised title (lowercase, punctuation collapsed to spaces) equals a
   member title, from any source. This is a repost under another URL. `match = "title_exact"`.
4. **Similar title**: TF-IDF cosine >= 0.5 against a member title **from a different source**.
   `match = "title"`.
   - **CVE veto** for rules 3 and 4: if the article has key CVEs and none of them is in the
     story's `cve_ids` while the story has CVEs, the title rules do not apply.
5. No match: the article starts a new story (`match = "lead"`).

Actor, victim and named-vulnerability keys are deliberately left out: the actor rule produced the
worst false merges in the simulation, `victim_name` comes from the LLM today, and the named
vulnerability added almost nothing over the CVE rule. They come back with P4's deterministic
extractors.

### 3.3 Settings

New nested `Settings.story` (`STORY__*`), every field with a default so no required key is added:

| Key | Default |
|-----|---------|
| `STORY__ENABLED` | `true` |
| `STORY__WINDOW_HOURS` | `72` |
| `STORY__MAX_AGE_DAYS` | `7` |
| `STORY__MAX_KEY_CVES` | `5` |
| `STORY__CVE_OVERLAP` | `0.5` |
| `STORY__TITLE_SIMILARITY` | `0.5` |

`.env.example` and `.env.prod.template` list them in the same commit (`test_config.py`,
`test_env_prod_template.py`). Turning P3 off is `STORY__ENABLED=false` plus a worker restart.

## 4. Pipeline

### 4.1 Order

With `STORY__ENABLED=false` the 0.8.6 order is unchanged. With it on, `run_pipeline` becomes:

1. `normalize_title`, `_known_article` (URL lock, unchanged).
2. `fetch_text` (moved in front of classify), then key CVEs from title and body.
3. **Resolve** in a separate short session (section 4.2).
4. Branch:
   - **Match, story `classify` set**: build the `ClassifyResult` from `stories.classify`, with
     `audit = {"inherited_from_story": id, "lead_article_id": ..., "match": rule}`. Skip TTP.
     Summarize, IOCs, score, routing, persist and alert run as for any article.
   - **Match, story `classify` NULL** (lead still running, or every member so far is Tier 0): full
     enrichment as today, article still linked to the story.
   - **No match**: the new story was created in step 3; full enrichment.
5. On persist, in the article's transaction: set `articles.story_id` and `story_match`; update the
   story (`article_count + 1`, `source_count` = distinct sources of its members, `last_seen_at`,
   `cve_ids` union, `lead_article_id` when NULL, `classify` when NULL and this article's classify
   came from the LLM).

Rejected articles (classify says not cyber) never update a story. The fetch now also runs for
the ~17% of articles that classify rejects; a failed fetch gives empty text and title-only CVEs, as
today.

### 4.2 Concurrency

`worker-nlp` runs with concurrency above 1, and a wave can arrive minutes apart (Bleeping Computer
and Wiz on PHP2Shell, 17 minutes). Step 3 uses its own session: take a global advisory transaction
lock in a new namespace (a two-int key, like `_URL_LOCK_NAMESPACE`), read candidates, insert the
new story with its title and `cve_ids` when there is no match, commit. The lock is held for
milliseconds. It cannot run in the main transaction, because that transaction holds the URL lock
across the LLM calls and committing it early would release that lock.

So the second article of a wave already sees the story that the first created, takes the
"classify NULL" branch while the lead is still enriching, and every later article inherits.

### 4.3 Edge cases

- **Tier 0 lead** (`default_relevance="always"`, e.g. CISA KEV titled only `CVE-2026-87902`): Tier 0
  articles join and can lead stories, but their synthetic classify never fills `stories.classify`;
  otherwise a news follow-up would inherit empty industries and no victim.
- **Lead rejected by classify**: the story is deleted if `article_count = 0`; otherwise it stays and
  the next accepted LLM-classified member fills `classify`.
- **Task fails after the story was created** (LLM 503, article parked): on replay, the exact-title
  rule finds the empty story again. Stories still empty after `STORY__MAX_AGE_DAYS` are removed by
  a daily `maintenance` task.
- **Replay and auto-replay** go through the same pipeline, no special case.
- **Inheritance scope**: everything in `ClassifyResult` except `audit` (relevance, best-practice
  flag, industries, victim/actor countries, incident fields, victim name). TTPs are **not** copied
  to follow-up rows; they stay on the lead, so per-article TTP counts no longer multiply by the
  size of a wave. A follow-up of a best-practice lead follows the best-practice branch.
- **Alerts** stay per article (decision 2026-10-25): grouping is visible in the UI only.

## 5. Data model

One hand-written migration, `down_revision = "f3c9e1b5a7d2"` (P2 head);
`test_migrations_match_models.py` keeps it in line with the models.

`stories` (global corpus like `articles`, not per client):

| Column | Type | Notes |
|--------|------|-------|
| `id` | bigint PK | |
| `title` | text | lead title |
| `lead_source` | varchar(200) | lead source, so a story without attached articles yet still has one member for the cross-source title rule |
| `lead_article_id` | bigint FK `articles.id`, nullable, `ON DELETE SET NULL` | filled when the first member persists |
| `cve_ids` | `text[]` not null default `{}`, GIN index | union of members' key CVEs |
| `classify` | jsonb, nullable | lead's `ClassifyResult` without `audit`; NULL = not inheritable yet |
| `first_seen_at`, `last_seen_at` | timestamptz, indexed on `last_seen_at` | window and age cap |
| `article_count`, `source_count` | integer not null default 0 | |
| `created_at`, `updated_at` | timestamptz | |

`articles` gains `story_id` (bigint FK `stories.id`, nullable, `ON DELETE SET NULL`, indexed) and
`story_match` (varchar(20), nullable: `lead`, `cve`, `title_exact`, `title`).

Not built: `story_sources` from the design document (with follow-ups kept as articles, a story's
sources are `articles WHERE story_id = X`), a separate `story_cves` table (`article_cves` still
holds the per-article CVEs), and no change to the old `clusters` table.

## 6. API, UI, backfill, measurement

**API** (schema changes, so `tools/export_openapi.py` and `pnpm run gen:api` in the same PR):

- Article list and detail gain `story: {id, article_count, source_count} | null` and
  `classify_inherited_from: int | null` (the lead article id from the classify audit).
- `GET /api/articles?story_id=X` lists a story's members; no new `/stories` endpoint.
- `dedup=true` (read-time TF-IDF) is unchanged.

**Web**: a "+N sources" badge on the article card when `source_count > 1`, linking to the article
list filtered by `story_id`; on a follow-up's detail, one line "Classification inherited from
<lead title>". Checked in light and dark mode, no blur effects.

**Backfill** `python -m cti_enrich.story_backfill [--dry-run] [--since YYYY-MM-DD]`, following
`cti_enrich.backfill`: runs the same resolver over stored articles in `first_seen_at` order, with
`article_cves` as the CVE keys (no body text is stored). Writes only `stories`, `story_id` and
`story_match`, and leaves `stories.classify` NULL (the audit holds raw model replies, not a parsed
result; the next LLM-classified member of a still-open story fills it, section 4.1); no LLM call,
no alert, no change to existing enrichment. Idempotent (articles with a
`story_id` are skipped); `--dry-run` prints the story summary and rolls back. Writing to dev needs
the user's approval.

**Data health** (LLM section, 24 h and 7 d): new stories, follow-ups, share of inherited
classifications, and estimated LLM calls avoided (inherited follow-ups x 2), computed from
`articles.story_match` and the classify audit.

## 7. Testing

| Level | Covers |
|-------|--------|
| Unit, resolver | CVE rule (at most 5, at least 50%, tie-break), roundup gives no key, exact title, similar title only across sources, CVE veto, window and age cap, no match -> new story |
| Unit, pipeline (fakes, style of `test_pipeline_tier0.py`) | inherited branch calls neither `classify` nor `extract_ttps`; classify-NULL branch enriches fully and links; `fetch_text` before `classify`; `STORY__ENABLED=false` matches 0.8.6; a Tier 0 member never fills `stories.classify` |
| Integration (Docker) | migration matches models; two concurrent resolves of the same title give one story; persist updates counts, `cve_ids`, lead and classify; rejected lead deletes an empty story; maintenance purge; backfill idempotent, `--dry-run` rolls back |
| Replay | fixture `tests/fixtures/story_replay/dev_2026-10.json` (id, title, source, `first_seen_at`, CVEs for the 1,451 dev articles; public news, no user data) through the real resolver: the thresholds of success criterion 1, plus follow-ups between 150 and 220 as a regression guard when thresholds change |
| Contract | `STORY__*` in `.env.example` and `.env.prod.template`; `openapi.json` and `schema.d.ts` regenerated |

## 8. Embedding experiment (offline, input for P5)

The title signal sits behind `title_similarity` so a local embedding model can replace or join
TF-IDF later. P3 does not ship one: on dev data TF-IDF plus CVEs already caught every paraphrase
checked except id 1278, embeddings judge topic rather than event (the many "AI agent" headlines
are close in meaning but different stories, and a false merge here skips classify and TTP), and the
local model runtime belongs to P5's relevance gate. The plan includes one offline task: run a small
sentence-embedding model over the replay fixture, compare recall and precision with TF-IDF, and
append the result to this spec. Downloading the model needs the user's approval; the experiment
code is not merged.

## 9. Rollout

1. This branch (on P2 `48f2600`) merged into `origin/Dev` with the user's approval, deployed to dev,
   `story_backfill --dry-run`, then the real backfill (approval), QA in the UI and Data health.
2. PR to `main` after the P2 PR has merged; release 0.8.7 (versions in every package, Indonesian
   CHANGELOG entry), tag and GitHub Release after CI on `main` is green.
3. Docs (English): P3 progress in `docs/LLM_ASSIST_REDESIGN.md`, story flow in
   `docs/ARCHITECTURE.md`, `STORY__*` in the config documentation.

## 10. Out of scope (follow-ups)

- U12: campaign clusters page reading `stories` instead of read-time TF-IDF.
- U25: spikes counting stories instead of articles.
- One LLM summary per story (Tier 3 item 4).
- `source_count` as a credibility signal (P6, on top of P2's deterministic confidence).
- Actor, victim and named-vulnerability keys (P4); embeddings (P5, see section 8).
- Story merge and split by analysts (`/api/v2/stories`, `docs/TARGET_ARCHITECTURE.md`).
