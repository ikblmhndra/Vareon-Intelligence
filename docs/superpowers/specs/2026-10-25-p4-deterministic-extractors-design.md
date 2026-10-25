# P4 deterministic extractors: actors, malware, ATT&CK techniques, industry, incident rule

Date: 2026-10-25. Status: design approved in chat, awaiting review of this written spec.
Release: **0.8.8** (one PR, after P3 / 0.8.7; merged into `origin/Dev` and tested on the dev
instance first).
Parent documents: `docs/LLM_ASSIST_REDESIGN.md` (section 2 "Tier 1: deterministic enrichment",
rollout row P4, evidence E8/E9) and `docs/UI_DATA_AUDIT.md` (U8, U9, U11).

## 1. Goal and success criteria

Fill threat actors, malware/tools, ATT&CK techniques and industries for every accepted article with
deterministic code over the full article text, label every derived fact with how it was obtained,
and measure it against the LLM. In this release Tier 1 **complements** the LLM: classify and TTP
extraction keep running as today; token savings come in a later step, once the numbers below exist.

Success:

1. Coverage (share of articles with at least one actor, TTP, specific industry) measured before and
   after on the same 100-article set, and Tier 1 coverage is higher than the LLM-era baseline.
2. On that set, precision of dictionary actors >= precision of the actors stored today, and
   precision of `explicit` + `keyword` TTPs >= precision of `llm` TTPs. The labels are a **silver
   standard** (section 7): a subagent labels every candidate, the user adjudicates 20 random
   articles, and the agreement rate is reported next to the result.
3. "Cobalt Strike" in a text never yields an actor (U8); common-word names (Castle, Slug, Hive,
   Medusa, Play, ...) need context to match.
4. Every stored TTP, actor, industry and malware row carries its `source`; the article modal shows
   it.

Dev data behind the design (read-only, 2026-10-25, 1,469 articles):

| Fact | Number |
|------|--------|
| Articles with an actor | 103 (7%) |
| Articles with a TTP | 597 (41%); 2,248 TTP rows, 343 distinct IDs |
| Articles whose only industry is "General" | 883 (60%) |
| Confirmed incidents (LLM, title only) | 402; `victim_name` set on 237 |
| `threat_actor_groups` | 3,995 flat names, no alias -> canonical mapping, no type; sources: malpedia 2,272, eternal-library 582, threat-card 465, mstic 187, orkl 185, ransomlook 137, manual 75, others 92 |
| Names that are also ATT&CK software | 70 |
| Names of 4 characters or fewer | 79; single plain words: 1,145 |
| ATT&CK | 197 groups, 975 software (878 malware, 97 tool), 19,466 `uses` -> attack-pattern relationships |
| Inferred techniques per entity (`uses`) | intrusion set 27.2, malware 14.1, tool 9.2, campaign 22.1 on average |
| Article body text stored | no (`articles` has no text column) |

Two causes of low actor coverage found in the code: the matcher runs over the sumy summary, not the
full text (`pipeline.py`: `score(title, summary, ...)`), and the LLM never fills actors.

## 2. Components (`cti_enrich/tier1/`, pure functions, no Session or HTTP)

| Unit | Responsibility | Interface |
|------|----------------|-----------|
| `dictionary.py` | Builds `EntityDictionary`: lowercase name/alias -> `Entity(canonical, kind)`, `kind` in `actor`, `malware`, `tool`. Sources in priority order: ATT&CK groups (actor; name + aliases), ATT&CK software (`software_type` malware/tool; name + aliases), `threat_actor_groups` (actor; dropped when the name is ATT&CK software, as 0.8.3 already does). Names in `ta_whitelist` (the suppression list) are dropped. On a name clash ATT&CK wins. | `build_dictionary(groups, software, ta_names, suppressed) -> EntityDictionary` |
| `entities.py` | Matcher. One compiled alternation regex, longest name first, boundaries `(?<!\w)...(?!\w)`, case-insensitive, except ATT&CK names/aliases of 4 characters or fewer or written in capitals ("APT1", "NICKEL"), which match with their exact casing. A **context word** within 200 characters (ransomware, group, gang, APT, threat actor, hackers, operators, affiliate, crew, cluster, "tracked as", malware, backdoor, loader, stealer, RAT) is required for (a) every single-token name known only from `threat_actor_groups` (1,145 on dev are plain words such as castle, copper, mercury, nickel, paladin, karma; stored lowercase, so casing cannot help) and (b) names in the curated `AMBIGUOUS` set (Cobalt, Play, Royal, Hive, Medusa, ... for ATT&CK names that are common words). Overlapping matches: the longest wins, so "Cobalt Strike" (tool) masks "Cobalt" (actor). | `match_entities(text, dictionary) -> list[EntityHit(canonical, kind, matched, offset)]` |
| `ttps.py` | (a) `explicit`: regex `\bT\d{4}(?:\.\d{3})?\b`, kept only when the ID is in the ATT&CK catalog (`load_catalog`). (c) `keyword`: curated `KEYWORD_MAP` for about 60 of the most frequent techniques (seeded from the dev top list: T1190, T1566(.001/.002), T1078, T1068, T1041, T1548, T1195, T1005, T1203, T1486, T1036, T1027, T1059, ...), phrase -> ID, some entries requiring a second phrase (e.g. "encrypted" with "ransomware" -> T1486). Every hit stores the sentence it came from as `evidence`. | `extract_techniques(text, catalog) -> list[Technique(id, name, source, evidence)]` |
| `industry.py` | Keyword taxonomy for the 19 specific industries of the classify prompt (not "General"), over title + first 1,500 characters. An industry counts with one hit in the title or two distinct hits in the text; at most 3, ordered by hits. | `match_industries(title, text) -> list[str]` |
| `incident.py` | Confirmed-incident rule, **shadow only**: a victim (LLM `victim_name`, a spaCy ORG in the title, or a pattern "X confirms/discloses/reports ...") + an incident verb set (breached, hacked, confirms attack, ransomware attack on, data stolen, leaked, disrupted, ...) + not a how-to / guide / report / prediction pattern. | `incident_verdict(title, text, victim_name) -> IncidentVerdict(confirmed, reasons)` |
| `merge.py` | Combines Tier 1 with LLM output (section 3). | `merge_ttps(...)`, `merge_industries(...)` |

`stages/tier1.py` is the only unit that touches the database: it loads ATT&CK groups/software,
`threat_actor_groups`, `ta_whitelist` and the technique catalog through a Session, caches the built
dictionary per process for one hour (same pattern as the IOC allowlist), runs the units and returns
`Tier1Result(entities, techniques, industries, incident, versions)`.

The actor matching in `stages/score.py` (`match_names` over title, body and NER entities) is
replaced by the Tier 1 matcher, so there is one implementation. `score_with_lists` keeps its
signature for `monitor_x` (title-only, no `nlp` extra); it builds a dictionary from the lists it
receives.

## 3. Pipeline flow and merge rules

Tier 1 runs after `fetch_text`, `summarize` and `extract_iocs`, before the LLM TTP call, on
`text or summary` (the same input as IOC extraction; a failed fetch leaves the title only).

| Path | Tier 1 |
|------|--------|
| Accepted, not best practice | entities, techniques, industry, incident |
| Security Technology & Best Practices | entities and industry only (TTP and scoring are skipped on this branch today) |
| Tier 0 (`default_relevance="always"`) and P3 story follow-ups | full Tier 1: it needs no LLM, and these paths have no LLM TTP |
| Rejected (`related_cyber = false`) | not run |

Merge:

- **Actors:** `mentioned_group` = canonical names from Tier 1 over title + full text + the NER
  entities already computed. Stored through the existing `threat_actor_names()` (`capitalize()`),
  so old and new rows do not split ("Apt29"). Aliases collapse: "Cozy Bear" and "APT29" become one
  actor. The LLM never filled actors, so nothing is merged.
- **Malware/tools:** Tier 1 only -> `article_malware`.
- **TTPs:** union by technique ID. When the same ID comes from several sources, one row is kept with
  the strongest source, `explicit > llm > keyword`, and that source's evidence. LLM techniques still
  pass `normalize_ttp_result` and `verify_evidence`. Keyword hits are **not** sent to the LLM as
  hints, so the two stay independent for measurement.
- **Industry:** when the LLM returned only "General" or nothing and Tier 1 found at least one
  industry, the Tier 1 industries are stored with `source = keyword` and "General" is dropped.
  Otherwise the LLM industries are kept.
- **Incident:** `confirmed_incident` stays the LLM value. The rule's verdict and reasons go to
  `raw_enrichment["tier1"]["incident"]` only.

Intended side effects:

1. Actors from the full text send more new articles to the "TA Group" / APAC routing branches and
   add a "Related Threat Actor" line to their Telegram alert; some `news_type` values move from
   "Global Article" to "TA Group Article". That is the coverage goal.
2. The confidence bonus (`cti_core.confidence.compute_score`) counts `explicit` and `llm` TTPs and
   actors; `keyword` TTPs get no bonus until their precision is measured.
3. Aggregates (MITRE heatmap, topics, trending) count every stored source. An API parameter
   `ttp_source` allows comparing them.

Failure handling: Tier 1 never fails an article. An exception in the stage is logged as
`tier1_failed` and the pipeline continues with an empty `Tier1Result`, like
`_extract_ttps_or_empty`. Empty ATT&CK tables (before the first sync) give a dictionary from
`threat_actor_groups` only and no explicit/keyword validation (explicit IDs are dropped, keyword
hits are kept with the names from the map).

Coordination with P3: the `pipeline.py` change is one `run_tier1(...)` call plus the merge before
`routing.route`, and one extra argument to `persist`. P4 branches from `main` after P3 (0.8.7) is
merged; if P3 is not merged when execution starts, the P4 branch is rebased onto it.

## 4. Data model (one Alembic migration)

| Change | Detail |
|--------|--------|
| `article_ttps.source` | `varchar(10)`, not null, server default `'llm'` (every existing row came from the LLM): `llm`, `explicit`, `keyword` |
| `article_ttps.evidence` | `text`, nullable; the quoted sentence (LLM evidence or Tier 1 sentence) |
| `article_threat_actors.source` | `varchar(10)`, not null, server default `'dictionary'` (existing rows came from the matcher): `dictionary`, `llm` (reserved), `analyst` (reserved) |
| `article_industries.source` | `varchar(10)`, not null, server default `'llm'`: `llm`, `keyword` |
| `article_malware` (new) | `id`, `article_id` FK cascade, `name` (canonical, `varchar(200)`), `kind` (`malware`/`tool`), `source` (`dictionary`), unique `(article_id, name)`, index on `name` |
| `raw_enrichment["tier1"]` | dictionary version (hash of the built name set), keyword-map version, raw hits with offsets, incident verdict |

Values are checked in the repository (same convention as `ArticleCountry.role`), not with a
Postgres CHECK. `ArticleRepo.set_enrichment` gains `malware` and accepts `(value, source[, evidence])`
inputs; analyst overrides (`articles.overrides`) are unchanged and still win on read.

Inferred techniques are **not stored** (section 5).

## 5. API and UI

API:

- `TTP` schema gains `source: Literal["explicit", "keyword", "llm"]` and `evidence: str | None`,
  wherever article TTPs are returned.
- `ArticleOut` gains `malware: list[{name, kind}]` and `industry_source: "llm" | "keyword" | None`.
- New `GET /api/articles/{id}/inferred-ttps` (same permission as article detail): for each actor
  and malware/tool of the article that exists in ATT&CK, `{entity, kind, attack_id, techniques:
  [{id, name}]}` from `attack_relationships` (`uses` -> `attack-pattern`), computed on read. Entities
  only known to Malpedia / `threat_actor_groups` have no relationships and return no techniques.
- `ttp_source` query parameter (multi-value, default all) on the article list and the MITRE heatmap.
- `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts` regenerated.

UI (article modal only, no new page):

- TTP chips get a small source marker (`ID`, `KW`, `LLM`) with the evidence sentence in the tooltip.
- New row "Malware / tools" with chips (kind in the tooltip).
- Industries from keywords carry the `KW` marker.
- Collapsed section "Known TTPs of <entity>", loaded lazily from the new endpoint and labelled as
  inferred, not stated in this article.
- Checked at 375 px and desktop, light and dark, theme tokens only.

Dashboard, Exec and Newsroom keep their current aggregates; they receive more complete data, not a
new layout.

## 6. Backfill

`python -m cti_enrich.backfill_tier1 [--since DATE] [--limit N] [--sleep SECONDS] [--dry-run]`
refetches each article's text with `fetch_text`, runs Tier 1 and **only adds**: `explicit`/`keyword`
TTPs whose ID the article does not have, actors and malware not yet present, and keyword industries
only when the article's sole industry is "General". It never removes or rewrites LLM rows, analyst
overrides, `news_type`, confidence or alerts. Failed fetches are skipped and counted in the summary.
It is run by hand after deploy; on dev only with the user's approval.

## 7. Evaluation

`tools/eval/tier1_eval.py` (not product code; outputs outside the repo):

1. `sample`: 100 accepted articles from dev (read-only), stratified by source and by whether the
   LLM stored actors/TTPs; texts refetched to local files.
2. `run`: Tier 1 over those texts plus the stored LLM actors/TTPs/industries/incident ->
   `candidates.jsonl`, one line per candidate, **without** its source.
3. Labelling: a subagent marks each candidate correct/incorrect with a supporting quote and may add
   missed entities; the user adjudicates 20 random articles; the agreement between subagent and user
   is reported.
4. `score`: precision per source (dictionary vs stored actors; `explicit`, `keyword`, `llm` TTPs;
   `keyword` vs `llm` industries; incident rule vs LLM) and coverage before/after on the same set.

The results go into `docs/LLM_ASSIST_REDESIGN.md` (P4) as silver-standard numbers. Release gate:
success criteria 1-2. If `keyword` precision is below `llm`, the offending map entries are removed
and the set is scored again; the target is not lowered.

## 8. Testing

- Unit, per `tier1/` module: U8 ("Cobalt Strike" -> tool, no actor "Cobalt"), ambiguous common words
  with and without context, alias -> canonical, short names case-sensitive, explicit IDs not in the
  catalog dropped, keyword entries needing two phrases, industry fallback over "General", incident
  rule on how-to titles.
- Unit, `merge`: source priority by ID, LLM evidence kept, General replaced only when Tier 1 found
  something.
- Integration (Docker): pipeline with mocked LLM writes the right `source` values and
  `article_malware`; Tier 0 and story follow-up paths get Tier 1; Tier 1 exception keeps the
  article; `inferred-ttps` endpoint; backfill (dry-run writes nothing, never overwrites LLM rows);
  migrations match models.
- Contract: `score_with_lists` from `monitor_x` still works without the `nlp` extra.
- Performance: matcher over a 100 KB text with the full dictionary measured in a unit test with a
  generous bound, to catch a pathological regex.

## 9. Release

0.8.8 in one PR: version bump and Indonesian `CHANGELOG.md` entry in the same PR. Merged into
`origin/Dev` first (dev check: article modal, backfill dry-run, then a real backfill with approval),
then a PR to `main`. No new `.env` keys.

## 10. Out of scope

- Turning off LLM TTP extraction for some articles (decided after the evaluation numbers).
- Victim vs actor country from the actor's known origin.
- A full entity table (`intrusion_set`, `malware`, relationships) and analyst editing of the
  dictionary: P7.
- A victim name -> industry lookup that grows from analyst edits.
- Using the incident rule for `confirmed_incident` (shadow only in this release).
