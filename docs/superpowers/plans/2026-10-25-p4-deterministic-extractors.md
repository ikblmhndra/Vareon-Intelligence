# P4 Deterministic Extractors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill actors, malware/tools, ATT&CK techniques and industries for every accepted article with deterministic code over the full text, label each fact with its source, and measure it against the LLM.

**Architecture:** A pure package `cti_enrich/tier1/` (dictionary, matcher, techniques, industry, incident, merge) plus one DB-touching stage `stages/tier1.py`. The pipeline calls it after `extract_iocs`, merges it with the LLM output, and `persist` writes `source` columns and a new `article_malware` table. Inferred techniques are computed on read by a new API endpoint.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic, FastAPI, pytest (+ testcontainers), Next.js 16 / Base UI shadcn.

**Spec:** `docs/superpowers/specs/2026-10-25-p4-deterministic-extractors-design.md`

## Global Constraints

- Release **0.8.8**, one PR, built on top of P3 (0.8.7). Alembic `down_revision = "a7d3f1c9e5b2"` (P3 `stories`), or whatever head `main` has if P3 merged with a different head.
- No new dependency (matcher = compiled `re` alternation, not `pyahocorasick`). No new `.env` key.
- `cti_enrich/tier1/*` (except `stages/tier1.py`) imports no Session, no HTTP, no spaCy.
- Tier 1 never fails an article: any exception in the stage → log `tier1_failed`, continue with an empty `Tier1Result`.
- Stored actor names go through `cti_enrich.routing.threat_actor_names()` (`capitalize()`), unchanged.
- Source values: `article_ttps.source` ∈ `llm|explicit|keyword` (default `'llm'`); `article_threat_actors.source` ∈ `dictionary|llm|analyst` (default `'dictionary'`); `article_industries.source` ∈ `llm|keyword` (default `'llm'`); `article_malware.source` = `dictionary`. Checked in the repository, no Postgres CHECK.
- TTP merge priority by ID: `explicit > llm > keyword`. Confidence bonus counts `explicit` + `llm` only.
- `confirmed_incident` stays the LLM value; the rule writes only `raw_enrichment["tier1"]["incident"]`.
- Comments/docstrings Indonesian (match surroundings); docs English; `CHANGELOG.md` Indonesian; commit messages English conventional ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Ruff line length 100; mypy strict on `cti-core` and `cti-scraper` only. Build non-ASCII characters in Python source with `chr()` (RUF001 rejects literal confusables).
- Web: theme tokens only, no `backdrop-blur`, Base UI (`render={...}`, not `asChild`); check 375 px and desktop, light and dark.
- Fast suite: `uv run pytest tests/unit tests/contract packages`. Two known Mac-only failures may be deselected; do not re-diagnose them.

## Review Focus

1. **Non-Latin and mixed-script text** (ASEC Korean/Japanese posts): the matcher must not crash and must not match names inside CJK runs; owned by Task 1 (`test_cjk_text_no_false_hits`).
2. **Fetch failed, title only** (`text == ""`, summary empty): Tier 1 still runs on the title and can return an actor and an industry; owned by Task 6 (`test_run_tier1_title_only`).
3. **ATT&CK not synced yet** (empty `attack_*` tables): dictionary falls back to `threat_actor_groups`, explicit IDs are dropped, nothing raises; owned by Task 6 (`test_run_tier1_without_attack_data`).
4. **Same name as ATT&CK group and software** (e.g. an alias shared by both): the entity is an actor, consistent with `list_non_actor_software_names`; owned by Task 1 (`test_group_and_software_same_name_is_actor`).
5. **T-number look-alikes** ("T1000 router", "T1059.999", "t1059" lowercase): only catalog IDs in canonical case are kept; an unknown sub-technique is dropped, not mapped to its parent; owned by Task 2 (`test_explicit_ids_validated`).

---

### Task 0: Base the branch on P3

**Files:** none (git only).

- [ ] **Step 1:** `git fetch origin`. If `origin/main` contains P3 (`git merge-base --is-ancestor origin/claude/p3-story-dedup-363be8 origin/main`), run `git rebase origin/main`; otherwise run `git rebase origin/claude/p3-story-dedup-363be8`. The branch holds only the spec/plan commits, so no conflicts are expected.
- [ ] **Step 2:** `uv sync --extra dev --locked && uv run pytest tests/unit -q -x` → passes (minus the known local failures).
- [ ] **Step 3:** Note the Alembic head in the task report: `uv run alembic heads` (expected `a7d3f1c9e5b2`).

---

### Task 1: Entity dictionary and matcher

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/tier1/__init__.py` (empty), `tier1/dictionary.py`, `tier1/entities.py`
- Test: `tests/unit/test_tier1_entities.py`

**Interfaces:**
- Produces:
  - `Kind = Literal["actor", "malware", "tool"]`
  - `@dataclass(frozen=True) class Entity: canonical: str; kind: Kind; needs_context: bool; case_sensitive: bool`
  - `@dataclass(frozen=True) class EntityDictionary: entries: Mapping[str, Entity]; version: str` (key = the name as written for case-sensitive entries, lowercase otherwise; `version` = first 8 hex chars of sha256 of the sorted keys)
  - `build_dictionary(groups: Iterable[tuple[str, Sequence[str]]], software: Iterable[tuple[str, str, Sequence[str]]], ta_names: Iterable[str], suppressed: Iterable[str]) -> EntityDictionary`. `groups` = `(name, aliases)`; `software` = `(name, software_type, aliases)`.
  - `@dataclass(frozen=True) class EntityHit: canonical: str; kind: Kind; matched: str; offset: int`
  - `match_entities(text: str, dictionary: EntityDictionary) -> list[EntityHit]` (one hit per canonical, first offset, ordered by offset)
  - Constants in `entities.py`: `AMBIGUOUS: frozenset[str]`, `CONTEXT_WORDS: tuple[str, ...]`, `CONTEXT_WINDOW = 200`

Rules (spec section 2): ATT&CK groups → actor (canonical = ATT&CK name); ATT&CK software → `malware`/`tool` by `software_type`, unless the lowercase name/alias is also a group name/alias (→ actor); `threat_actor_groups` names → actor with canonical = the name itself, dropped when the lowercase name is ATT&CK software, skipped if a key already exists (ATT&CK wins); names in `suppressed` (`ta_whitelist`, lowercase) dropped. `case_sensitive` = ATT&CK name/alias of ≤4 characters or all capitals. `needs_context` = single token (`re.fullmatch(r"[a-z]+", name)`) known only from `threat_actor_groups`, or lowercase name in `AMBIGUOUS`. Matching: one alternation regex for case-insensitive keys and one for case-sensitive keys, each sorted longest first, boundaries `(?<!\w)` / `(?!\w)`; collect all matches of both, resolve overlaps by keeping the longest span; drop `needs_context` hits without a `CONTEXT_WORDS` match (case-insensitive, word boundaries) within `CONTEXT_WINDOW` characters either side. `CONTEXT_WORDS`: ransomware, group, gang, APT, threat actor, hackers, operators, affiliate, crew, cluster, tracked as, malware, backdoor, loader, stealer, RAT. `AMBIGUOUS` at least: cobalt, play, royal, hive, medusa, castle, slug, akira, cactus, cicada, dune, lynx, karma, everest, nemesis, phobos, mercury, nickel, copper, outlaw.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_tier1_entities.py` with a small hand-built dictionary (`groups=[("APT29", ["Cozy Bear", "NOBELIUM"]), ("Lazarus Group", ["HIDDEN COBRA"]), ("Cobalt Group", ["Cobalt"])]`, `software=[("Cobalt Strike", "tool", []), ("Emotet", "malware", ["Geodo"]), ("Lazarus Group", "malware", [])]`, `ta_names=["castle", "kimsuky", "shinyhunters", "emotet"]`, `suppressed=["shinyhunters"]`):
  - `test_cobalt_strike_is_tool_not_actor`: text "Operators deployed Cobalt Strike beacons." → `[("Cobalt Strike", "tool")]` only.
  - `test_alias_maps_to_canonical`: "Cozy Bear phished diplomats" → canonical `"APT29"`, kind actor.
  - `test_all_caps_alias_case_sensitive`: "NOBELIUM struck" hits; "nobelium is an element" does not.
  - `test_common_word_needs_context`: "the castle gate" → no hit; "the Castle ransomware gang" → actor `"castle"`.
  - `test_single_token_ta_name_needs_context`: "Kimsuky sent lures" → none; "North Korean APT Kimsuky sent lures" → `"kimsuky"`.
  - `test_suppressed_name_dropped`: "ShinyHunters ransomware group" → no hit.
  - `test_attack_wins_over_ta_list`: "Emotet ransomware loader" → kind `"malware"`, canonical `"Emotet"` (not actor).
  - `test_group_and_software_same_name_is_actor`: "Lazarus Group hackers" → kind actor.
  - `test_word_boundary`: "APT290 and xAPT29" → no hit.
  - `test_cjk_text_no_false_hits`: Korean/Japanese text built with `chr()` containing no dictionary names → `[]`; same text with " APT29 " inserted → one hit.
  - `test_dictionary_version_stable`: same inputs in different order → same `version`.
  - `test_matcher_speed_on_large_text`: dictionary of 5,000 synthetic names, 100 KB text → `match_entities` under 2 seconds.
- [ ] **Step 2:** `uv run pytest tests/unit/test_tier1_entities.py -q` → FAIL (module not found).
- [ ] **Step 3:** Implement `dictionary.py` and `entities.py` per the interface and rules above. Cache the two compiled regexes on the `EntityDictionary` instance (`functools.cached_property` on a non-frozen helper, or a module-level `lru_cache` keyed by `version`).
- [ ] **Step 4:** `uv run pytest tests/unit/test_tier1_entities.py -q` → PASS; `uv run ruff check packages/cti-enrich tests/unit/test_tier1_entities.py`.
- [ ] **Step 5:** Commit `feat(enrich): tier 1 entity dictionary and matcher`.

---

### Task 2: ATT&CK techniques (explicit + keyword)

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/tier1/ttps.py`, `tier1/keyword_map.py`
- Test: `tests/unit/test_tier1_ttps.py`

**Interfaces:**
- Consumes: `cti_core.attack_ttp.TechniqueCatalog` (`.names: Mapping[attack_id, name]`, `.is_empty`).
- Produces:
  - `TtpSource = Literal["explicit", "keyword", "llm"]`
  - `@dataclass(frozen=True) class SourcedTechnique: ttp_id: str; ttp_name: str; source: TtpSource; evidence: str`
  - `extract_techniques(text: str, catalog: TechniqueCatalog) -> list[SourcedTechnique]` (one per ID; explicit wins over keyword for the same ID)
  - `keyword_map.KEYWORD_MAP: tuple[KeywordRule, ...]` with `@dataclass(frozen=True) class KeywordRule: ttp_id: str; ttp_name: str; phrases: tuple[str, ...]; requires: tuple[str, ...] = ()` (a rule fires when any phrase matches and, if `requires` is set, any `requires` phrase also appears in the text); `KEYWORD_MAP_VERSION: str` (sha256[:8] of the rules' repr)
  - `sentence_at(text: str, offset: int) -> str` (the sentence around an offset, at most 300 characters, whitespace collapsed)

Explicit: `re.finditer(r"(?<![\w.])T\d{4}(?:\.\d{3})?(?!\w|\.\d)", text)`, case-sensitive; keep only IDs in `catalog.names` (exact; unknown sub-technique dropped, not mapped to its parent); empty catalog → no explicit results. Keyword: phrases matched case-insensitively on word boundaries; name taken from `catalog.names` when present, else `KeywordRule.ttp_name`. Evidence = `sentence_at(...)` of the first match.

`KEYWORD_MAP` covers at least 40 of these 60 most frequent dev IDs, with phrases that state the behaviour (not a bare tactic word): T1190 T1566 T1078 T1068 T1041 T1566.002 T1566.001 T1195 T1548 T1005 T1203 T1036 T1486 T1027 T1059 T1555 T1663 T1003 T1105 T1570 T1210 T1684 T1195.001 T1563 T1213 T1059.001 T1552.007 T1684.001 T1505.003 T1589 T1552.001 T1556 T1204.002 T1082 T1583.006 T1552 T1189 T1071.001 T1530 T1539 T1555.003 T1133 T1020 T1685 T1195.002 T1090 T1528 T1083 T1055 T1199 T1565.001 T1588 T1036.005 T1557 T1491.001 T1598.003 T1098 T1548.004 T1657 T1496. Examples that the tests pin: "spear-phishing attachment"/"malicious attachment" → T1566.001; "phishing link"/"malicious link" → T1566.002; "web shell"/"webshell" → T1505.003; "powershell" → T1059.001; "encrypt(ed|s) files" requires "ransomware" → T1486; "exploited (a|the) vulnerability in" / "exploit(ed|ing) .{0,40}(public-facing|internet-facing)" → T1190; "supply chain attack|supply-chain compromise" → T1195; "credential dumping|dumped credentials|lsass" → T1003; "cryptominer|cryptomining|cryptojacking" → T1496.

- [ ] **Step 1: Write the failing tests** with a fake catalog `TechniqueCatalog(names={"T1059": "Command and Scripting Interpreter", "T1059.001": "PowerShell", "T1486": "Data Encrypted for Impact", "T1566.001": "Spearphishing Attachment", "T1505.003": "Web Shell", "T1190": "Exploit Public-Facing Application"})`:
  - `test_explicit_ids_validated`: "Uses T1059.001 and T1059. Not T1000 routers, not T1059.999, not t1059" → IDs `["T1059.001", "T1059"]`, both `source == "explicit"`.
  - `test_explicit_beats_keyword`: "PowerShell (T1059.001) was used" → one `T1059.001`, `source == "explicit"`.
  - `test_keyword_requires_second_phrase`: "files were encrypted" → no T1486; "the ransomware encrypted files" → T1486 `keyword`.
  - `test_keyword_evidence_is_sentence`: evidence equals the full sentence containing "web shell".
  - `test_empty_catalog_keeps_keywords_drops_explicit`: empty catalog, "T1059 via PowerShell" → only keyword T1059.001 with `ttp_name == "PowerShell"`.
  - `test_keyword_map_size_and_ids`: `len({r.ttp_id for r in KEYWORD_MAP}) >= 40` and every ID matches `^T\d{4}(\.\d{3})?$`.
  - `test_no_bare_tactic_phrases`: no phrase in `KEYWORD_MAP` equals one of "execution", "persistence", "exfiltration", "initial access", "discovery", "collection", "impact".
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement `ttps.py` and `keyword_map.py`.
- [ ] **Step 4:** `uv run pytest tests/unit/test_tier1_ttps.py -q` → PASS; ruff clean.
- [ ] **Step 5:** Commit `feat(enrich): tier 1 explicit and keyword ATT&CK techniques`.

---

### Task 3: Industry taxonomy and incident rule

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/tier1/industry.py`, `tier1/incident.py`
- Test: `tests/unit/test_tier1_industry_incident.py`

**Interfaces:**
- Produces:
  - `INDUSTRY_KEYWORDS: Mapping[str, tuple[str, ...]]` — keys exactly the 19 specific industries of the classify prompt (`cti_enrich.stages.classify._PROMPT` list minus "General"); at least 5 keywords each.
  - `INDUSTRY_TAXONOMY_VERSION: str`
  - `match_industries(title: str, text: str) -> list[str]` — over `title` and `text[:1500]`; an industry counts with ≥1 keyword hit in the title or ≥2 distinct keywords in the text; at most 3, ordered by total hits then taxonomy order.
  - `@dataclass(frozen=True) class IncidentVerdict: confirmed: bool; reasons: tuple[str, ...]`
  - `incident_verdict(title: str, text: str, victim_name: str | None) -> IncidentVerdict` — `confirmed` when (victim present: `victim_name`, or a "<Capitalised Name> (confirms|discloses|reports|says) ..." pattern in title/first 500 chars) AND an incident verb (breached, hacked, confirms (cyber)?attack, ransomware attack on, data (was )?stolen, leaked, data breach at, disrupted by (a )?cyberattack, systems encrypted) AND NOT a guide pattern in the title (how to, guide, best practices, what is, explained, tips, report:, predictions, could, may). `reasons` lists which parts fired (`"victim:<how>"`, `"verb:<phrase>"`, `"guide:<phrase>"`). No spaCy (pure rule).

- [ ] **Step 1: Write the failing tests:**
  - `test_industry_keys_match_prompt`: `set(INDUSTRY_KEYWORDS) == set(prompt list) - {"General"}`, parsing the list out of `classify._PROMPT` with `re.search(r'\["Government.*?"General"\]', ...)`.
  - `test_title_hit_counts`: `match_industries("Hospital network hit by ransomware", "")` → `["Healthcare & Life Sciences"]`.
  - `test_body_needs_two_hits`: one bank keyword in the body only → `[]`; "bank" + "credit union" in body → `["Finance & Insurance"]`.
  - `test_max_three`: text naming 5 sectors → `len(...) == 3`.
  - `test_body_beyond_1500_ignored`.
  - `test_incident_confirmed`: `incident_verdict("Acme Corp confirms data breach after ransomware attack", "", None).confirmed is True`.
  - `test_incident_guide_title_not_confirmed`: "How to respond to a data breach" → `False` with a `guide:` reason.
  - `test_incident_needs_victim`: "Ransomware attacks rise 30%" → `False`.
  - `test_incident_victim_from_llm`: `("Hospital systems encrypted", "", "Regional Hospital")` → `True`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement both modules.
- [ ] **Step 4:** run → PASS; ruff clean.
- [ ] **Step 5:** Commit `feat(enrich): tier 1 industry taxonomy and shadow incident rule`.

---

### Task 4: Merge rules

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/tier1/merge.py`
- Test: `tests/unit/test_tier1_merge.py`

**Interfaces:**
- Consumes: `SourcedTechnique` (Task 2); `cti_enrich.stages.extract_ttps.TtpResult` / `Technique` (existing: `technique_id`, `technique_name`, `evidence`, `extracted_id`, `extracted_name`).
- Produces:
  - `merge_ttps(llm: TtpResult | None, tier1: Sequence[SourcedTechnique]) -> list[NormalizedTTP]` — one entry per ID, priority `explicit > llm > keyword`, carrying `source` and `evidence` of the winner; LLM entries keep `extracted_id`/`extracted_name`. Order: winners in LLM order first, then Tier 1 order.
  - `merge_industries(llm: list[str], tier1: list[str]) -> tuple[list[str], Literal["llm", "keyword"]]` — `resolve_industries(llm)` result if it is not `["General"]`/empty, else `(tier1, "keyword")` when `tier1` is non-empty, else `(resolve_industries(llm), "llm")`.
  - `confidence_ttp_count(ttps: Sequence[NormalizedTTP]) -> int` — count with `source in {"explicit", "llm"}`.

`NormalizedTTP` (in `cti_core/attack_ttp.py`) gains two trailing fields with defaults, `source: str = "llm"` and `evidence: str | None = None`, so every existing constructor call keeps working. This edit lands in this task; mypy strict covers `cti-core`.

- [ ] **Step 1: Write the failing tests:**
  - `test_explicit_beats_llm_beats_keyword`: LLM T1059.001 (evidence "a"), Tier 1 explicit T1059.001 (evidence "b") and keyword T1486 + keyword T1059.001 → `[("T1059.001", "explicit", "b"), ("T1486", "keyword", ...)]`.
  - `test_llm_beats_keyword_keeps_extracted`: LLM T1190 with `extracted_name="Exploit public app"`, keyword T1190 → source `llm`, `extracted_name` kept.
  - `test_none_llm`: `merge_ttps(None, [...])` returns the Tier 1 list.
  - `test_general_replaced_only_when_tier1_found`: `(["General"], ["Finance & Insurance"])` → `(["Finance & Insurance"], "keyword")`; `(["General"], [])` → `(["General"], "llm")`; `(["Healthcare & Life Sciences"], ["Finance & Insurance"])` → LLM kept; `([], ["Energy & Utilities"])` → keyword.
  - `test_confidence_counts_only_explicit_and_llm`.
  - `test_normalized_ttp_backward_compatible`: `NormalizedTTP("T1", "x")` has `source == "llm"` and `evidence is None`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Extend `NormalizedTTP`; implement `merge.py`.
- [ ] **Step 4:** `uv run pytest tests/unit/test_tier1_merge.py tests/unit -q -k "ttp or tier1"` → PASS; `uv run mypy packages/cti-core/src packages/cti-scraper/src` clean.
- [ ] **Step 5:** Commit `feat(enrich): merge tier 1 techniques and industries with LLM output`.

---

### Task 5: Schema, models and repository

**Files:**
- Create: `alembic/versions/<rev>_tier1_sources_article_malware.py`
- Modify: `packages/cti-core/src/cti_core/db/models/article.py` (`ArticleTTP`, `ArticleThreatActor`, `ArticleIndustry`, new `ArticleMalware`, `Article.malware` relationship), `packages/cti-core/src/cti_core/db/repositories/article.py` (`set_enrichment`, `_apply_enrichment`, `apply_ttps`, async twin)
- Test: `tests/integration/test_article_tier1_columns.py`; existing `tests/integration/test_migrations_match_models.py` must stay green.

**Interfaces:**
- Consumes: `NormalizedTTP.source/evidence` (Task 4).
- Produces:
  - Columns per Global Constraints; `ArticleTTP.evidence: Mapped[str | None]` (`Text`).
  - `class ArticleMalware(Base)`: `__tablename__ = "article_malware"`, `id`, `article_id` FK `articles.id` `ondelete="CASCADE"`, `name String(200)` indexed, `kind String(10)`, `source String(10)` server default `'dictionary'`, `UniqueConstraint("article_id", "name", name="uq_article_malware")`; `Article.malware` relationship `cascade="all, delete-orphan"`, mirrored by `back_populates`.
  - `ArticleRepo.set_enrichment(article, *, countries=(), industries=(), threat_actors=(), ttps=(), malware: Sequence[tuple[str, str]] = (), industry_source: str = "llm")` — same on `AsyncArticleRepo`. `apply_ttps` writes `row.source`/`row.evidence` from `NormalizedTTP`; tuple inputs `(id, name)` get `source="llm"`. Invalid source/kind values raise `ValueError` (repository check). New actor rows get `source="dictionary"`.
  - `ArticleRepo.add_tier1(article, *, ttps: Sequence[NormalizedTTP], threat_actors: Sequence[str], malware: Sequence[tuple[str, str]], industries: Sequence[str]) -> dict[str, int]` — **add-only** for the backfill (Task 10): adds TTP IDs not present, actors/malware not present, and industries with `source="keyword"` only when the current industries are exactly `["General"]` (then the General row is removed); returns counts per kind.

- [ ] **Step 1: Write the failing integration tests** (Docker): `test_set_enrichment_writes_sources` (ttps with explicit/keyword/llm, malware, `industry_source="keyword"` → rows carry those values; actor row source `dictionary`), `test_invalid_source_rejected` (`ValueError`), `test_add_tier1_is_add_only` (existing LLM T1190 row untouched, keyword T1190 not added, new T1486 added, General replaced, specific LLM industry kept), `test_existing_rows_default_sources` (insert via raw SQL without source → `llm`/`dictionary`/`llm`).
- [ ] **Step 2:** `uv run pytest tests/integration/test_article_tier1_columns.py -q` → FAIL.
- [ ] **Step 3:** Write the migration (hand-written, `down_revision` = head from Task 0; downgrade drops the table and columns), models and repository changes.
- [ ] **Step 4:** `uv run pytest tests/integration/test_article_tier1_columns.py tests/integration/test_migrations_match_models.py -q` → PASS; mypy clean.
- [ ] **Step 5:** Commit `feat(db): source columns on article enrichment and article_malware table`.

---

### Task 6: Tier 1 stage and one actor matcher in `score.py`

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/stages/tier1.py`
- Modify: `packages/cti-enrich/src/cti_enrich/stages/score.py` (`score`, `score_with_lists`), `packages/cti-core/src/cti_core/db/repositories/threat_reference.py` (loader helpers)
- Test: `tests/unit/test_tier1_stage.py`, `tests/integration/test_tier1_stage_db.py`; existing `tests/unit/test_threat_actor_extraction.py`, `test_ui_data_quick_fixes.py`, `test_tweet_alerts.py`, `tests/contract/test_registry_without_nlp.py` stay green.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces:
  - `threat_reference.load_entity_sources(session) -> tuple[list[tuple[str, list[str]]], list[tuple[str, str, list[str]]], list[str], list[str]]` (groups, software, ta names, `ta_whitelist` names).
  - `@dataclass class Tier1Result: entities: list[EntityHit]; techniques: list[SourcedTechnique]; industries: list[str]; incident: IncidentVerdict | None; versions: dict[str, str]` with `actors` / `malware` properties (`malware` = `[(canonical, kind)]` for malware+tool) and `audit() -> dict[str, object]` (versions, hits with offsets, incident verdict) for `raw_enrichment["tier1"]`. `Tier1Result.empty()` classmethod.
  - `get_dictionary(session: Session) -> EntityDictionary` — process cache, TTL 3600 s, same pattern as `extract_iocs._get_allowlist`; on load error returns the last good dictionary or an empty one.
  - `run_tier1(*, session: Session, title: str, text: str, victim_name: str | None, techniques: bool = True) -> Tier1Result` — matches entities over `title + "\n" + text`; techniques (when `techniques=True`) and incident over `text` (title if `text` empty); industries `match_industries(title, text)`. Wraps everything in `try/except Exception` → `log.warning("tier1_failed", ...)` and `Tier1Result.empty()`.
  - `score_with_lists(..., dictionary: EntityDictionary | None = None)` — actor matching uses `match_entities` (kind `actor` only, canonical names, lowercased for `mentioned_group` so `threat_actor_names()` keeps producing the same stored form); when `dictionary` is None it builds one with `build_dictionary([], [], group_list, [])` plus `non_actor_names` as software (`"tool"`) so masking still works. `score(...)` passes `get_dictionary(session)`. `compile_name_patterns`/`match_names` stay (used by `cti_enrich.backfill`); note in the docstring that only the old backfill uses them.

- [ ] **Step 1: Write the failing tests:**
  - unit `test_run_tier1_title_only`: monkeypatched `get_dictionary`/`load_catalog`; `run_tier1(title="Lazarus Group hackers hit bank", text="", ...)` → actor `"Lazarus Group"`, industries `["Finance & Insurance"]`.
  - unit `test_run_tier1_exception_returns_empty`: `match_entities` raising → `Tier1Result.empty()` and a `tier1_failed` log.
  - unit `test_score_with_lists_cobalt_strike` (existing U8 tests keep passing) and `test_score_with_lists_alias_canonical`.
  - integration `test_run_tier1_without_attack_data`: empty `attack_*` tables, `threat_actor_groups` seeded with "kimsuky" → "North Korean APT Kimsuky ... T1059" → actor `kimsuky`, no explicit techniques, no exception.
  - integration `test_dictionary_cache_ttl`: second call within TTL does not query (count statements with an event listener).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement loader, stage and `score.py` switch.
- [ ] **Step 4:** `uv run pytest tests/unit tests/contract -q` and the two integration files → PASS; mypy + ruff clean.
- [ ] **Step 5:** Commit `feat(enrich): tier 1 stage; score uses the tier 1 actor matcher`.

---

### Task 7: Pipeline and persist wiring

**Files:**
- Modify: `packages/cti-enrich/src/cti_enrich/pipeline.py`, `packages/cti-enrich/src/cti_enrich/stages/persist.py`
- Test: `tests/unit/test_pipeline_tier1.py` (same monkeypatch style as `tests/unit/test_pipeline_tier0.py`), `tests/integration/test_pipeline_tier1_db.py`

**Interfaces:**
- Consumes: Tasks 4-6.
- Produces:
  - `persist(..., tier1: Tier1Result | None = None, merged_ttps: Sequence[NormalizedTTP] | None = None, industries: tuple[list[str], str] | None = None)` — when given, `set_enrichment` receives `merged_ttps`, `malware=tier1.malware`, `industries`/`industry_source` from the tuple, and `raw_enrichment["tier1"] = tier1.audit()` (merged into existing `raw_enrichment`, not replacing `classify`). `_confidence_score` uses `confidence_ttp_count(merged_ttps)` when given. Without the new arguments behaviour is unchanged.
  - Pipeline: `tier1 = run_tier1(session=session, title=title, text=text or summary, victim_name=classify_result.victim_name, techniques=not best_practice)` right after `extract_iocs`; best-practice branch passes `tier1` + `industries=merge_industries(...)` to `persist`; main branch: after LLM TTP normalize/verify, `merged = merge_ttps(ttp_result, tier1.techniques)`; `ttp_string` built from `merged`; after `score_stage.score(...)`, `score_result.mentioned_group = list(dict.fromkeys([*score_result.mentioned_group, *(a.lower() for a in tier1.actors)]))`; `routing_input.industries_impacted` = merged industries. Tier 0 and P3 inherited paths run Tier 1 the same way (they only skip the LLM calls).

- [ ] **Step 1: Write the failing tests:**
  - unit `test_tier1_runs_on_always_path`: `default_relevance="always"` → `persist` kwargs contain a `tier1` and `merged_ttps` with the keyword technique from the fetched text; `calls["ttp"] == 0`.
  - unit `test_keyword_not_sent_to_llm`: the string passed to `extract_ttps` equals `_ttp_input(text, summary)` exactly.
  - unit `test_actor_from_full_text_reaches_routing`: actor only in the body (summary stub has none) → `route()` receives it in `mentioned_group`.
  - unit `test_tier1_failure_keeps_article`: `run_tier1` patched to return `Tier1Result.empty()` after logging → article persisted, LLM results stored as before.
  - unit `test_best_practice_gets_entities_and_industry_only`.
  - integration `test_pipeline_writes_sources`: mocked LLM (classify returns `["General"]`, TTP returns T1190 with verifiable evidence), article text with "T1059.001", "web shell", "Cobalt Strike", "bank" → rows: T1059.001 explicit, T1505.003 keyword, T1190 llm; malware `Cobalt Strike`/tool; industry `Finance & Insurance` source keyword; `raw_enrichment` has both `classify` and `tier1`; `confidence_score` bonus counts 2 TTPs.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement; keep the `pipeline.py` diff to the call, the merge and the extra `persist` arguments. Update the module docstring's stage order line.
- [ ] **Step 4:** `uv run pytest tests/unit -q` + the integration file + `tests/integration/test_enrich_pipeline_resilience.py` → PASS.
- [ ] **Step 5:** Commit `feat(enrich): run tier 1 in the pipeline and persist sourced results`.

---

### Task 8: API — sources, malware, inferred techniques, `ttp_source`

**Files:**
- Create: `apps/api/src/cti_api/services/inferred_ttps.py`
- Modify: `apps/api/src/cti_api/schemas/article.py`, `apps/api/src/cti_api/routers/articles.py` (`_serialize`, list params, new route), `apps/api/src/cti_api/routers/mitre.py` (`/heatmap` param), `packages/cti-core/src/cti_core/db/repositories/mitre.py` (`get_heatmap(..., ttp_sources)`), `packages/cti-core/src/cti_core/db/repositories/article.py` (`list_filtered(..., ttp_sources)`), `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`, syrupy snapshots touched by the new fields
- Test: `tests/integration/test_inferred_ttps.py`, `tests/integration/test_article_sources_api.py`

**Interfaces:**
- Consumes: Task 5 columns.
- Produces:
  - `class TTP(BaseModel): id: str; name: str; source: Literal["explicit", "keyword", "llm"] = "llm"; evidence: str | None = None`
  - `class MalwareRef(BaseModel): name: str; kind: Literal["malware", "tool"]`; `ArticleOut.malware: list[MalwareRef] = []`; `ArticleOut.industry_source: Literal["llm", "keyword"] | None = None` (from the first industry row; `None` when no rows).
  - `class InferredEntity(BaseModel): entity: str; kind: Literal["actor", "malware", "tool"]; attack_id: str; techniques: list[InferredTechnique]` with `class InferredTechnique(BaseModel): id: str; name: str` (no `source`: nothing is stored).
  - `GET /api/articles/{article_id}/inferred-ttps` → `list[InferredEntity]`, dependency `require_auth` (same as article detail), 404 for unknown article.
  - `inferred_ttps.for_article(session: AsyncSession, article: Article) -> list[InferredEntity]`: names from `article.threat_actors` (case-insensitive) and `article.malware` matched to `attack_groups`/`attack_software` name or alias (lowercase compare); relationships `relationship_type='uses'`, `target_type='attack-pattern'`, `source_ref = stix_id`; techniques from `attack_techniques` by `stix_id`, sorted by `attack_id`, deduplicated; entities without an ATT&CK match are omitted.
  - `ttp_source: list[Literal["explicit","keyword","llm"]] | None = Query(None)` on `GET /api/articles` (applies together with `ttp`: an article matches when it has a TTP row whose source is in the list, and, if `ttp` is set, whose ID is in `ttp`) and on `GET /api/mitre/heatmap` (counts only rows with those sources).

- [ ] **Step 1: Write the failing integration tests:** `test_inferred_ttps_for_attack_actor` (seed group APT29 + one `uses` relationship + technique → one entity with that technique), `test_inferred_ttps_alias_and_malware`, `test_inferred_ttps_unknown_entity_omitted`, `test_inferred_ttps_404`, `test_article_out_has_sources_and_malware`, `test_ttp_source_filter_list_and_heatmap`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement; then `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`; update syrupy snapshots with `--snapshot-update` only for files whose diff is the new fields.
- [ ] **Step 4:** Run the two new files and `uv run pytest tests/integration -q -k "snapshot or article or mitre"` → PASS; `git diff --stat docs/openapi.json apps/web/src/lib/api/schema.d.ts` shows only the new fields/route.
- [ ] **Step 5:** Commit `feat(api): TTP sources, article malware, inferred techniques endpoint`.

---

### Task 9: Article modal

**Files:**
- Modify: `apps/web/src/components/newsroom/article-modal.tsx`
- Create (if the modal file would exceed ~400 lines): `apps/web/src/components/newsroom/inferred-ttps-section.tsx`

**Interfaces:**
- Consumes: `ArticleOut.ttps[].source/evidence`, `ArticleOut.malware`, `ArticleOut.industry_source`, `GET /api/proxy/articles/{id}/inferred-ttps`.

Requirements: TTP table gets a "Source" column (badge `ID` / `KW` / `LLM`, `Tooltip` with the evidence when present); a "Malware / Tools" `Section` with `Tags` (kind in tooltip) placed after Threat Actors, hidden when empty; industries with `industry_source === "keyword"` show a small `KW` badge after the tags; a collapsed section "Known TTPs of <entity>" per inferred entity, fetched only on first expand, with the caption "Inferred from ATT&CK, not stated in this article", empty-state "No ATT&CK techniques known for these entities". Labels in English (the modal's existing section titles are English).

- [ ] **Step 1:** Implement.
- [ ] **Step 2:** `cd apps/web && pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build` → all succeed.
- [ ] **Step 3:** Visual check moves to dev QA (after the Dev merge), at 375 px and desktop, light and dark; record that in the task report.
- [ ] **Step 4:** Commit `feat(web): show TTP source, malware and inferred techniques in the article modal`.

---

### Task 10: Add-only backfill command

**Files:**
- Create: `packages/cti-enrich/src/cti_enrich/backfill_tier1.py`
- Test: `tests/integration/test_backfill_tier1.py`

**Interfaces:**
- Consumes: `fetch_text`, `run_tier1` (Task 6), `ArticleRepo.add_tier1` (Task 5).
- Produces: `backfill_tier1(session: Session, *, since: datetime.date | None, limit: int | None, sleep: float, dry_run: bool, fetch: Callable[[str], str] = fetch_text) -> Tier1BackfillStats` (`scanned`, `fetched`, `fetch_failed`, `ttp_rows_added`, `actor_rows_added`, `malware_rows_added`, `industry_replaced`); CLI `python -m cti_enrich.backfill_tier1 [--since YYYY-MM-DD] [--limit N] [--sleep S] [--dry-run]` printing the stats. Commits per article (a long run must not hold one transaction); `--dry-run` rolls back every article. Articles are processed by ascending `id`; best-practice articles get entities and industry only (same as the pipeline). Actor names stored through `threat_actor_names()`.

- [ ] **Step 1: Write the failing tests** with a fake `fetch`: `test_dry_run_writes_nothing`, `test_adds_only_missing_rows` (existing LLM rows untouched), `test_fetch_failure_counted_and_skipped`, `test_since_and_limit`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement (module docstring in Indonesian in the style of `cti_enrich/backfill.py`, with the run commands).
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** Commit `feat(enrich): add-only tier 1 backfill command`.

---

### Task 11: Evaluation tool

**Files:**
- Create: `tools/eval/__init__.py`, `tools/eval/tier1_eval.py`, `tools/eval/sample.sql`
- Test: `tests/unit/test_tier1_eval.py`

**Interfaces:**
- Consumes: pure `tier1` functions (Tasks 1-3), `fetch_text`.
- Produces: CLI `uv run python -m tools.eval.tier1_eval {fetch,run,score} --workdir DIR`:
  - `sample.sql` (read-only, run by the operator over SSH into `DIR/sample.jsonl`): 100 accepted articles, stratified: 40 with LLM TTPs, 20 with actors, 40 others, at most 6 per source, excluding best practice; per article `id, url, title, source, victim_name, confirmed_incident, actors[], ttps[{id,name}], industries[]`; plus a second query block for reference data → `DIR/reference.json` (`groups`, `software`, `ta_names`, `suppressed`, `techniques{id: name}`).
  - `fetch`: text per article into `DIR/texts/<id>.txt` (skip existing; record failures).
  - `run`: builds the dictionary/catalog from `reference.json`, runs Tier 1, writes `DIR/candidates.jsonl` with one line per `(article_id, field, value)` for fields `actor`, `malware`, `ttp`, `industry`, `incident`, **no source**, and `DIR/provenance.jsonl` mapping candidate id → sources (`dictionary`, `explicit`, `keyword`, `llm`, `stored`).
  - `score`: reads `DIR/labels.jsonl` (`candidate_id, correct: bool, quote, labeller`) and `provenance.jsonl`; prints precision per field and source, coverage before (stored LLM-era data) vs after (merged) per field, and agreement between labellers `subagent` and `user` on candidates both labelled.
  - `score_precision(labels: Sequence[Label], provenance: Mapping[str, set[str]]) -> dict[tuple[str, str], tuple[int, int]]` (field, source) → (correct, total) — the unit-tested core.

- [ ] **Step 1: Write the failing tests:** `test_score_precision_counts_per_source` (a candidate with two sources counts for both), `test_agreement_rate`, `test_candidates_have_no_source_field`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement. Work directory default: the session scratchpad, never inside the repo.
- [ ] **Step 4:** run → PASS; ruff clean.
- [ ] **Step 5:** Commit `feat(tools): tier 1 evaluation harness`.

---

### Task 12: Run the evaluation and record it

Operational task for the controller (needs dev read-only SSH and the user).

- [ ] **Step 1:** Run `sample.sql` on dev read-only (`docker compose exec -T postgres psql -U cti -d cti -At` with `set default_transaction_read_only = on`), then `fetch` and `run`.
- [ ] **Step 2:** Dispatch a labelling subagent: for each article, read `texts/<id>.txt` and its candidates, mark each `correct` with a supporting quote (incorrect when not supported by the text), write `labels.jsonl` with `labeller = "subagent"`.
- [ ] **Step 3:** Pick 20 random articles; give the user their candidates (no sources) and record the user's labels with `labeller = "user"`.
- [ ] **Step 4:** `score` → check success criteria 1-2 of the spec. If `keyword` TTP precision < `llm`, remove the failing `KEYWORD_MAP` entries (commit `fix(enrich): drop imprecise keyword rules`), rerun `run` + `score` (labels for unchanged candidates are reused).
- [ ] **Step 5:** Write the numbers (silver standard, agreement rate, sample size, date) into `docs/LLM_ASSIST_REDESIGN.md` (Progress + P4 row) and commit `docs: P4 tier 1 evaluation results`.

---

### Task 13: Docs and release 0.8.8

**Files:** root and package `pyproject.toml`, every `__version__`, `apps/web/package.json`, `uv.lock`, `docs/openapi.json`, the health snapshot, `CHANGELOG.md`, `docs/ARCHITECTURE.md` (pipeline stage order + Tier 1), `CLAUDE.md` only if the data-flow line changes.

- [ ] **Step 1:** Bump to `0.8.8` everywhere listed in CLAUDE.md "Releases"; `uv lock`; regenerate `docs/openapi.json`; update the health snapshot.
- [ ] **Step 2:** `CHANGELOG.md` entry `## [0.8.8] - <date>` in Indonesian: Tier 1 deterministik (aktor/malware dari teks penuh, TTP explicit/keyword, industri fallback, label sumber), endpoint inferred TTP, kolom baru, backfill manual `python -m cti_enrich.backfill_tier1`, catatan perilaku (sebagian artikel baru pindah ke "TA Group Article").
- [ ] **Step 3:** Full verification: `uv run ruff check . && uv run ruff format --check .`, `uv run mypy packages/cti-core/src packages/cti-scraper/src`, `uv run pytest tests/unit tests/contract packages`, `uv run pytest tests/integration` (background, ~7 min), web lint/typecheck/build.
- [ ] **Step 4:** Commit `chore(release): 0.8.8`.
- [ ] **Step 5:** Stop. Merging into `origin/Dev`, the dev backfill and the PR to `main` each need the user's explicit approval.
