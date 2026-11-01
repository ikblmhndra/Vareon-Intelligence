# P7c-1 Entity Model (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every actor, malware/tool, technique, CVE, campaign, sector, country and ransomware
victim one entity with aliases, STIX-shaped relationships and mentions, keep v1 and rolled-back
code working, and serve the graph through `/api/entities`, `/api/v2/entities|relationships` and a
TAXII collection `intel`.

**Architecture:** One hand-written migration `entity_model` creates `entities`,
`entity_aliases`, `relationships`, `entity_mentions`, `entity_watches`, `entity_profiles`,
`reference_snapshots`, backfills them set-based from the old tables, renames the old tables to
`_legacy_*` and replaces them with writable compatibility views whose `INSTEAD OF` triggers call a
SQL `entity_resolve()` that mirrors the Python resolver. All Python readers and writers move to
the new tables; v1 response shapes stay. Galaxy aliases merge through the same merge code path
analysts use; the feed pattern of P7b is generalised to entities, relationships and stories.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (async + sync), Alembic (hand-written), Postgres 16
(triggers, `NULLS NOT DISTINCT`), FastAPI, Celery beat, pytest + testcontainers + syrupy,
`taxii2-client` (dev dependency since P7b).

**Spec:** `docs/superpowers/specs/2026-10-29-p7c-entity-model-design.md` (this plan covers
sections 3-6, 8 and 9 for the backend; section 7 is the P7c-2 web plan).

## Global Constraints

- Release: part of **0.8.11**; do **not** bump any version. Add to `## [0.8.11]` in `CHANGELOG.md`
  (Indonesian).
- Migration revision `entity_model` with `down_revision = "c4f1a8d27b93"`; sets
  `SET LOCAL lock_timeout = '10s'` first.
- `ENTITY_TYPES = ("intrusion-set", "malware", "tool", "attack-pattern", "vulnerability",
  "campaign", "identity", "location")`.
- `RELATIONSHIP_TYPES = ("uses", "targets", "attributed-to", "exploits", "indicates",
  "variant-of", "located-at", "related-to", "subtechnique-of")`.
- `MENTION_METHODS = ("dictionary", "llm", "keyword", "explicit", "analyst", "legacy")`.
- Entity `source` values: `attack, galaxy, dictionary, analyst, cve, iso, sector, ransomware,
  legacy`; alias `source`: `attack, galaxy, analyst, legacy, dictionary`; relationship
  `provenance`: `attack, analyst, ransomware`.
- Confidence: ATT&CK relationships 85, ransomware relationships 50, analyst default 75.
- `stix_id` for non-ATT&CK rows: `f"{type}--{uuid5(ENTITY_NAMESPACE, f'{type}:{name.lower()}')}"`,
  computed once at creation, never recomputed. `ENTITY_NAMESPACE =
  uuid.UUID("3c9f4b1e-7a52-5d8e-9b0c-6f1e2d3a4b5c")`. Relationships:
  `relationship--uuid5(ENTITY_NAMESPACE, f"{src_stix}:{type}:{dst_stix}")`.
- `alias_norm(s) = " ".join(s.lower().split())`; the SQL twin is
  `lower(regexp_replace(btrim(s), '\s+', ' ', 'g'))`. Python and SQL must agree (Task 2 test).
- TLP from `cti_core.indicator.marking.TLP_LEVELS` / `tlp_allowed`; default `clear`.
- Feed: `FEED_SETTLE_SECONDS = 60`, cursor encoding of `services/feed.py`; clocks use
  `clock_timestamp()`.
- New permission `manage_entities` (admin + analyst). Reads `view_ta`; watch `manage_pir`;
  profile `manage_intel`.
- New token scope `intel:read`; `API_TOKEN_SCOPES = ("indicators:read", "intel:read")`. Token
  create default scopes `["indicators:read"]`.
- New setting `EntitySettings.alias_sync_enabled: bool = True` under `Settings.entity`; prod needs
  no `.env` key; add commented `ENTITY__ALIAS_SYNC_ENABLED=true` to `.env.example` and
  `.env.prod.template`.
- Galaxy alias sync: weekly beat Sunday 05:00, `maintenance` queue, shrink guard 20 %, HTTP
  timeout 30 s, URLs `https://raw.githubusercontent.com/MISP/misp-galaxy/main/clusters/{name}.json`
  for `threat-actor`, `ransomware`, `malpedia`.
- Co-mentions: 365-day window, limit 50, never stored, never published.
- v1 response shapes do not change (names from `entities.name`). Only the intended alias collapse
  may change values.
- Code comments/docstrings Indonesian; docs English; CHANGELOG Indonesian; commits English
  conventional ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Local QA only on `POSTGRES_PORT=55433 REDIS_PORT=56379 docker compose -p qacve up -d postgres
  redis`, torn down with `docker compose -p qacve down -v`. Deselect locally:
  `tests/contract/test_golden.py::test_golden_trendmicro`.

## Decisions added while planning (confirm at plan review)

1. **Rollback proof (R2) in two layers.** CI cannot check out tags, so
   `tests/integration/test_entity_compat_views.py` carries a **frozen copy of the 0.8.10 ORM
   classes** (`ArticleThreatActor`, `ArticleMalware`, `ArticleTTP`, `ArticleCve`,
   `ArticleCountry`, `ArticleIndustry`, `TAProfile`, `TAWatchlistEntry`, `TAWhitelistEntry`) on a
   separate `DeclarativeBase` and drives the same ORM operations old code does (add via
   relationship, `pg_insert ... on_conflict_do_nothing`, delete-orphan, profile update). In
   addition the controller runs the real 0.8.2 and 0.8.10 code from worktrees at the tags against a
   migrated `qacve` DB (Task 16), as P7a did.
2. **Writable views needed** (grep at the tags, 2026-10-29): 0.8.2 and 0.8.10 write
   `article_threat_actors`, `article_ttps`, `article_countries`, `article_industries`,
   `ta_profiles` (insert + update), `ta_watchlist`, `ta_whitelist`; 0.8.10 also `article_malware`
   and `article_cves`. `indicator_threat_actors`, `cve_threat_actors`, `cve_ttps` are never written
   and become read-only views.
3. **Sector entities** get a display name and a vocabulary id: `name` = "Financial Services",
   `external_id` = `financial-services`. v1 `industry` values therefore become the sector display
   name (for example "Cloud Services" and "Information Technology & Software" both show
   "Technology"). This is part of the deliberate collapse (spec R4) and goes into the CHANGELOG.
4. **Reader helpers instead of per-file SQL rewrites.** `Article.mentions` (ORM) plus
   `Article.entity_names(*types)`, and one SQL helper `mention_rows(*types)` returning a subquery,
   so the 40-odd reader files swap a column reference instead of re-deriving joins.

## Review Focus

1. An alias that differs only in case or whitespace ("APT 29" vs "apt29") from an existing one:
   expected to resolve to the same entity, never create a second one (Task 2).
2. Two workers resolving the same new name at the same moment: expected one entity, both callers
   get it (Task 2, concurrent test).
3. A merge whose target already has the same relationship or mention: expected one row with the
   higher confidence and the wider seen range, no unique-violation (Task 6).
4. A story whose only mentioned entities are above the token's TLP or suppressed: expected the
   report is not returned rather than returned with an empty `object_refs` (Task 14).
5. Rolled-back code inserting a link row whose name is suppressed (`ta_whitelist`): expected the
   insert is silently dropped as before (old suppression dropped the name at extraction), not an
   error that aborts the article transaction (Task 4).

---

## File structure

| File | Responsibility |
|---|---|
| `packages/cti-core/src/cti_core/entity/__init__.py` | constants (`ENTITY_TYPES`, `RELATIONSHIP_TYPES`, `MENTION_METHODS`, `ENTITY_NAMESPACE`), `alias_norm`, `entity_stix_id`, `relationship_stix_id` |
| `packages/cti-core/src/cti_core/entity/sectors.py` | `SECTORS` (vocab -> display name), `LABEL_TO_SECTOR` (lowercased label -> vocab), `sector_for_label` |
| `packages/cti-core/src/cti_core/entity/countries.py` | `ISO_COUNTRY_NAMES` (alpha-2 -> name, from `pycountry`, generated constant) |
| `packages/cti-core/src/cti_core/entity/resolve.py` | sync + async `resolve()` |
| `packages/cti-core/src/cti_core/entity/merge.py` | `merge_entities`, `split_aliases`, `merge_preview` (sync core, async wrappers) |
| `packages/cti-core/src/cti_core/entity/galaxy.py` | parse Galaxy files, plan merges with guards, apply |
| `packages/cti-core/src/cti_core/entity/cli.py` | `cti-entity` typer app (`merge-aliases`) |
| `packages/cti-core/src/cti_core/db/models/entity.py` | ORM models |
| `packages/cti-core/src/cti_core/db/repositories/entity.py` | `AsyncEntityRepo` / `EntityRepo`, `mention_rows()` |
| `alembic/versions/<rev>_entity_model.py` + `alembic/versions/entity_model_sql/*.sql` | migration and its SQL bodies (views, triggers, backfill) |
| `tools/seed/reference/misp-galaxy/{threat-actor,ransomware,malpedia}.json`, `SOURCE` | snapshot |
| `apps/worker/src/cti_worker/tasks/entity.py` | `entity.alias_sync` |
| `apps/api/src/cti_api/routers/entities.py`, `services/entities.py`, `schemas/entities.py` | entity API |
| `apps/api/src/cti_api/services/feed.py`, `routers/v2_entities.py`, `routers/taxii.py` | machine API |
| `apps/api/src/cti_api/services/stix.py` | builders |

---

### Task 1: Entity models, constants and table DDL

**Files:**
- Create: `packages/cti-core/src/cti_core/entity/__init__.py`, `entity/sectors.py`,
  `entity/countries.py`, `packages/cti-core/src/cti_core/db/models/entity.py`,
  `alembic/versions/<rev>_entity_model.py` (DDL part only)
- Modify: `packages/cti-core/src/cti_core/db/models/__init__.py`, `db/models/story.py`
  (`feed_changed_at`)
- Test: `tests/unit/test_entity_constants.py`, `tests/integration/test_migrations_match_models.py`
  (existing, must stay green)

**Interfaces:**
- Produces: `Entity`, `EntityAlias`, `Relationship`, `EntityMention`, `EntityWatch`,
  `EntityProfile`, `ReferenceSnapshot` ORM classes with the spec 3.1 columns (exact names).
  `EntityMention.entity` relationship `lazy="joined"`. `Entity.aliases` (selectin).
  `alias_norm(s: str) -> str`, `entity_stix_id(type: str, name: str) -> str`,
  `relationship_stix_id(src_stix: str, rel_type: str, dst_stix: str) -> str`,
  `sector_for_label(label: str) -> str | None` (vocab id; `None` for "General"),
  `SECTORS: dict[str, str]`, `ISO_COUNTRY_NAMES: dict[str, str]`.
- `ReferenceSnapshot(name varchar(50) PK, fetched_at timestamptz, sha256 char(64), content jsonb)`.

- [ ] **Step 1: Write failing unit tests** — `test_alias_norm` (`alias_norm("  APT  29 ") ==
  "apt 29"`), `test_stix_ids_stable` (same input twice → same id; prefix `intrusion-set--`;
  case-insensitive on name), `test_every_dev_industry_label_mapped` (the 28 labels of spec §2 /
  evidence list in `tests/unit/data/dev_industry_labels.txt`: each maps to a vocab key in
  `SECTORS` except "General" → `None`), `test_sectors_are_stix_vocab` (keys subset of the STIX 2.1
  `industry-sector-ov` list written in the test), `test_iso_names` (`ISO_COUNTRY_NAMES["ID"] ==
  "Indonesia"`, 249 entries).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_entity_constants.py -q` — FAIL (module missing).
- [ ] **Step 3: Implement constants and ORM models**, and the migration `upgrade()` part that
  creates the seven tables, `stories.feed_changed_at` (default `clock_timestamp()`, index
  `(feed_changed_at, id)`), CHECKs from Global Constraints, the exactly-one CHECKs
  (`num_nonnulls(article_id, indicator_id, cve_tracker_id) = 1`, `num_nonnulls(source_entity_id,
  source_indicator_id) = 1`), the indexes of spec 3.1 (partial unique `(type, lower(name)) WHERE
  merged_into_id IS NULL`; unique `(entity_type, alias_norm)`; mentions unique with
  `postgresql_nulls_not_distinct=True`), and the matching `downgrade()` drops.
- [ ] **Step 4: Run** unit tests PASS; `uv run pytest tests/integration/test_migrations_match_models.py -q` PASS.
- [ ] **Step 5: Commit** `feat(core): add entity model tables and constants`.

### Task 2: Resolver (Python + SQL twin)

**Files:**
- Create: `packages/cti-core/src/cti_core/entity/resolve.py`,
  `alembic/versions/entity_model_sql/resolve.sql`
- Modify: migration (`op.execute` the SQL file in `upgrade`, drop the function in `downgrade`)
- Test: `tests/integration/test_entity_resolve.py`

**Interfaces:**
- Consumes: Task 1 models and helpers.
- Produces: `resolve(session: Session, type: str, name: str, *, source: str, external_id: str |
  None = None, identity_class: str | None = None) -> Entity` and
  `async resolve_async(session: AsyncSession, ...)` with the same parameters. Follows
  `merged_into_id` to the live entity; returns suppressed entities (caller decides). SQL:
  `entity_resolve(p_type text, p_name text, p_source text) RETURNS bigint` (live entity id).

- [ ] **Step 1: Write failing tests**: `test_resolve_by_alias_case_and_space` ("APT 29" resolves
  to the entity aliased "apt 29"); `test_resolve_creates_once` (new name → one entity + one alias
  row with `source`); `test_resolve_follows_merge`; `test_resolve_same_name_other_type_is_separate`;
  `test_resolve_concurrent` (two sessions on separate connections resolve "NewActor" and commit;
  one entity); `test_sql_twin_agrees` (for 12 inputs incl. whitespace/case/merged, `SELECT
  entity_resolve(...)` returns the same id as `resolve()`).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_entity_resolve.py -q` — FAIL.
- [ ] **Step 3: Implement**: lookup by `(entity_type, alias_norm)`; else `INSERT ... ON CONFLICT DO
  NOTHING` for entity (partial unique) and alias, then re-select (no exception-driven retry).
  Display name keeps the given casing. SQL twin uses identical rules.
- [ ] **Step 4: Run** tests — PASS.
- [ ] **Step 5: Commit** `feat(core): add entity resolver with SQL twin`.

### Task 3: Migration backfill

**Files:**
- Create: `alembic/versions/entity_model_sql/backfill.sql` (generated sector/ISO `VALUES` lists
  from Task 1 constants by `tools/dev/gen_entity_sql.py`, committed; unit test keeps them equal)
- Modify: migration (`upgrade` runs it after Task 2's function)
- Test: `tests/integration/test_entity_migration.py`, `tests/unit/test_entity_sql_generated.py`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: populated tables per spec 3.2 steps 2-7; `_legacy_*` renames are Task 4.

- [ ] **Step 1: Write failing tests** with the `test_indicators_migration.py` harness (downgrade
  to the old shape inside the session, seed, run `upgrade()`):
  - `test_mention_counts_equal_per_old_table` (seed rows in all nine link tables incl. a CVE with
    `in_title`, a TTP with `extracted_*`/`evidence`, a country with `role`, two industry labels
    mapping to one sector and one "General"); expected mention counts per table, "General" yields
    none;
  - `test_no_orphans` (every mention's entity exists and is not merged);
  - `test_attack_backfill` (seed 2 groups with aliases, 1 malware, 1 tool, 2 techniques,
    relationships `uses`, `revoked-by`, `subtechnique-of`): entities keep ATT&CK `stix_id`,
    aliases `source=attack`, relationships only for allowed types, confidence 85;
  - `test_old_names_resolve_to_attack_alias` ("Cozy bear" in `article_threat_actors` → APT29
    entity, `matched_alias = "Cozy bear"`);
  - `test_ransomware` (victim → identity organization, group → intrusion-set, `targets` +
    `located-at`, confidence 50);
  - `test_watch_profile_whitelist_moved` (watch rows → `entity_watches`, profile → `entity_profiles`,
    whitelist name → `suppressed`);
  - `test_seen_and_clocks` (`first_seen`/`last_seen` from `articles.published_at`;
    `feed_changed_at >= created_at`);
  - `test_pir_actor_criteria_become_entities`.
  - unit `test_generated_sql_matches_constants` (re-runs the generator in memory, compares to the
    committed file).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the set-based SQL in the order of spec 3.2 (ATT&CK first so old names
  hit ATT&CK aliases; unknown TTP ids become `legacy` attack-patterns; CVEs `source=cve`,
  `name = external_id = cve_id`; countries `name` from ISO table, `external_id` alpha-2).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(db): backfill entities, aliases, relationships and mentions`.

### Task 4: Legacy rename and writable compatibility views

**Files:**
- Create: `alembic/versions/entity_model_sql/compat_views.sql`
- Modify: migration (rename the twelve old tables to `_legacy_<name>`, keep their sequences, then
  create views + `INSTEAD OF` triggers; downgrade reverses)
- Test: `tests/integration/test_entity_compat_views.py`

**Interfaces:**
- Consumes: `entity_resolve` (Task 2).
- Produces: views with the exact old column lists of spec 3.6. View `id` = `entity_mentions.id`
  (or `entity_watches.id` / `entity_profiles.id`); INSERT triggers return `NEW` with `id` filled so
  ORM `RETURNING id` works.

- [ ] **Step 1: Write failing tests** using frozen 0.8.10 ORM copies (Decision 1):
  `test_old_orm_append_actor_via_relationship` (old `Article.threat_actors.append(...)`, flush,
  row visible in `entity_mentions` with `method=dictionary`, `matched_alias` = string);
  `test_old_pg_insert_article_cves_on_conflict` (same row twice → one mention);
  `test_old_delete_orphan_removes_mention`; `test_old_profile_update` (UPDATE `profile` through the
  view changes `entity_profiles`); `test_old_watchlist_add_remove`; `test_old_whitelist_add_suppresses`;
  `test_suppressed_name_insert_is_dropped` (Review Focus 5: no error, no mention);
  `test_industry_view_returns_original_label`; `test_read_only_views_reject_writes`
  (`indicator_threat_actors` insert raises); `test_old_and_new_writes_same_entity`
  (old ORM insert "Cozy bear" and new `resolve()` give one entity id).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the views and plpgsql trigger functions (one per view; DELETE by `id`;
  ON CONFLICT DO NOTHING on the mentions unique key).
- [ ] **Step 4: Run** — PASS; re-run Task 3 tests (still PASS).
- [ ] **Step 5: Commit** `feat(db): replace link tables with writable compatibility views`.

### Task 5: Feed clock triggers

**Files:**
- Create: `alembic/versions/entity_model_sql/feed_triggers.sql`
- Modify: migration; model docstrings on `Entity.feed_changed_at`, `Relationship.feed_changed_at`,
  `Story.feed_changed_at` naming the triggers
- Test: `tests/integration/test_entity_feed_triggers.py`

**Interfaces:**
- Produces: triggers per spec 3.5 (entities: `name, description, external_id, suppressed,
  merged_into_id, tlp`; alias insert/delete bumps entity; relationships: `relationship_type,
  source_entity_id, source_indicator_id, target_entity_id, confidence, description, revoked_at,
  tlp`; stories: `title, article_count`; mention insert/delete with `article_id` bumps the story).

- [ ] **Step 1: Write failing tests**: one test per listed column that it bumps (parametrised),
  `test_last_seen_does_not_bump`, `test_updated_at_only_does_not_bump`,
  `test_alias_insert_bumps_entity`, `test_mention_insert_bumps_story`,
  `test_relationship_confidence_bumps`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(db): add feed clocks for entities, relationships and stories`.

### Task 6: Merge, split, suppress

**Files:**
- Create: `packages/cti-core/src/cti_core/entity/merge.py`
- Test: `tests/integration/test_entity_merge.py`

**Interfaces:**
- Produces: `merge_entities(session: Session, source_id: int, into_id: int, *, actor: str) ->
  MergeResult` (`MergeResult(moved_aliases: int, moved_mentions: int, moved_relationships: int,
  moved_watches: int, moved_profile: bool)`); `merge_preview(session, source_id, into_id) ->
  MergeResult` (no writes); `split_aliases(session, entity_id: int, alias_ids: list[int], *, actor:
  str) -> Entity`; `set_suppressed(session, entity_id: int, suppressed: bool, *, actor: str) ->
  Entity`; async wrappers `*_async` via `session.run_sync`. Each writes one `audit_log` row
  (`action` = `entity_merge` / `entity_split` / `entity_suppress`, `detail` with moved alias ids and
  `source_id`/`into_id`). Raises `EntityMergeError` (different types, same id, already merged).

- [ ] **Step 1: Write failing tests**: `test_merge_moves_everything`; `test_merge_dedups_relationship`
  (Review Focus 3: keeps max confidence, min first_seen, max last_seen);
  `test_merge_dedups_mentions_and_watches`; `test_merge_profile_only_if_target_has_none`;
  `test_merge_rejects_cross_type`; `test_split_after_merge_restores_exactly` (revives tombstone,
  same `stix_id`, mentions whose `matched_alias` normalises to the split aliases move back, counts
  equal to before the merge); `test_split_new_entity_when_no_tombstone`;
  `test_suppress_keeps_mentions`; `test_audit_rows_written`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(core): add entity merge, split and suppression`.

### Task 7: Galaxy snapshot and `cti-entity merge-aliases`

**Files:**
- Create: `tools/seed/reference/misp-galaxy/{threat-actor,ransomware,malpedia}.json` and
  `SOURCE` (upstream commit sha + date + CC0 note), `packages/cti-core/src/cti_core/entity/galaxy.py`,
  `packages/cti-core/src/cti_core/entity/cli.py`
- Modify: `packages/cti-core/pyproject.toml` (`[project.scripts] cti-entity =
  "cti_core.entity.cli:app"`), `tools/seed/reference/README.md`
- Test: `tests/unit/test_galaxy_plan.py`, `tests/integration/test_galaxy_apply.py`,
  fixture `tests/fixtures/galaxy/mini-threat-actor.json`

**Interfaces:**
- Consumes: Task 2 `resolve`, Task 6 `merge_entities`, Tier 1 `AMBIGUOUS` and the
  single-word rule list from `cti_enrich.tier1.entities` (import the constants; cti-core must not
  import cti-enrich, so **move** `AMBIGUOUS` and `WINDOWS_UTILITY_NAMES` to
  `cti_core.entity.ambiguous` and re-export from `cti_enrich.tier1.entities`).
- Produces: `load_galaxy(name: str, content: dict) -> list[GalaxyCluster]`
  (`GalaxyCluster(uuid: str, value: str, synonyms: list[str], kind: Literal["actor","malware"])`);
  `plan_merges(session, clusters) -> GalaxyPlan` (`merges: list[PlannedMerge]`, `skips:
  list[PlannedSkip]` with `reason` in `two_attack, ambiguous, owned, undone`, `new_aliases:
  list[tuple[int, str]]`); `apply_plan(session, plan, *, actor="system:galaxy") -> GalaxyResult`;
  `galaxy_sources(session) -> dict[str, dict]` (stored `reference_snapshots` copy when present,
  else the repo snapshot). CLI: `cti-entity merge-aliases [--dry-run | --apply] [--csv PATH]`
  (default `--dry-run`; CSV columns `action,cluster,source_entity,target_entity,alias,reason`).

- [ ] **Step 1: Write failing tests**: unit on the mini fixture — `test_two_attack_cluster_skipped`,
  `test_ambiguous_synonym_never_merges` ("basin"), `test_target_is_attack_entity`,
  `test_target_most_mentions_without_attack`, `test_owned_alias_not_moved`; integration —
  `test_apply_merges_and_adds_aliases`, `test_second_run_noop`, `test_undone_merge_not_redone`
  (split a `system:galaxy` merge, rerun, still split), `test_dry_run_writes_nothing`,
  `test_cli_csv_columns`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**; download the three files once with `curl` (public CC0 data,
  user-approved source in the spec), record the commit sha from
  `https://api.github.com/repos/MISP/misp-galaxy/commits/main` in `SOURCE`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(core): merge entity aliases from a MISP Galaxy snapshot`.

### Task 8: Writers (pipeline, Tier 1 dictionary, ransomware sink, tools)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/article.py` (write paths: TTP/actor/
  malware/industry/country/CVE inserts), `db/repositories/article_cve.py`,
  `db/repositories/threat_reference.py` (`load_entity_sources`), `cti_enrich/stages/persist.py`,
  `cti_enrich/tier1/dictionary.py`, `cti_enrich/backfill.py`, `cti_enrich/canonicalise_actors.py`
  (becomes a thin wrapper that runs `merge-aliases`-style resolution, or is deleted if unused by
  docs/runbooks — check `git grep canonicalise_actors docs tools`), `cti_enrich/story_backfill.py`,
  `tools/ops/remap_article_ttps.py`, `tools/seed/fase10_reference_data.py`,
  `packages/cti-core/src/cti_core/db/repositories/ransomware.py` (`RansomwareVictimRepo` insert),
  `db/models/article.py` (add `Article.mentions` and `entity_names()`; the old link classes stay
  mapped to the views until Task 12 removes them, so readers keep working in between)
- Test: existing `tests/unit/test_tier1_*.py`, `tests/integration/test_persist*.py`,
  `test_threat_actor_backfill.py`, `test_seed_reference_data.py` updated; new
  `tests/integration/test_entity_writers.py`

**Interfaces:**
- Consumes: `resolve`, models.
- Produces: `Article.mentions: Mapped[list[EntityMention]]` (cascade `all, delete-orphan`,
  `lazy="selectin"`), `Article.entity_names(*types: str) -> list[str]` (entity names, ordered by
  mention id, de-duplicated), `Article.mentions_of(*types: str) -> list[EntityMention]`;
  `ArticleRepo.add_mentions(article, hits: Iterable[MentionInput])` (sync + async) where
  `MentionInput(type, name, method, matched_alias, role=None, evidence=None, extracted=None,
  external_id=None)`; dictionary built from `entity_aliases` + leftover `threat_actor_groups`,
  canonical = `Entity.name`, version hash over the sorted alias keys.

- [ ] **Step 1: Write failing tests** in `test_entity_writers.py`: `test_persist_writes_mentions`
  (article with actor alias, malware, TTP + evidence, CVE in title, country role, industry →
  mentions with right types/methods/extras); `test_persist_updates_seen`;
  `test_dictionary_uses_entity_name_as_canonical` ("Cozy Bear" hit → canonical "APT29");
  `test_dictionary_version_changes_with_alias`; `test_ransomware_sink_creates_relationships`;
  `test_seed_fase10_writes_new_tables`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**; update the existing tests that construct old link classes to use
  `MentionInput`/`resolve` (no behaviour change except names now canonical entity names).
- [ ] **Step 4: Run** `uv run pytest tests/unit tests/contract packages -q --deselect
  tests/contract/test_golden.py::test_golden_trendmicro` and the touched integration files — PASS.
- [ ] **Step 5: Commit** `refactor(enrich): write entity mentions instead of link tables`.

### Task 9: ATT&CK sync upserts entities (incl. campaigns)

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/attack.py` (`sync_domain` end)
- Test: `tests/integration/test_attack_entity_sync.py` (bundle fixture with one campaign)

**Interfaces:**
- Produces: `upsert_attack_entities(session, bundle_objects: list[dict]) -> dict[str, int]`
  (counts per type) called at the end of `sync_domain`; campaigns → `campaign` entities
  (`external_id` from `external_references[mitre-attack]`), their `uses`/`attributed-to`
  relationships.

- [ ] **Step 1: Failing tests**: `test_sync_creates_campaign_entity`,
  `test_sync_is_idempotent`, `test_sync_keeps_analyst_aliases`, `test_sync_renamed_group_updates_name`.
- [ ] **Step 2-4**: run FAIL, implement, run PASS.
- [ ] **Step 5: Commit** `feat(attack): upsert ATT&CK objects into entities after sync`.

### Task 10: `entity.alias_sync` task and setting

**Files:**
- Create: `apps/worker/src/cti_worker/tasks/entity.py`
- Modify: `packages/cti-core/src/cti_core/config.py` (`EntitySettings`, `Settings.entity`),
  `.env.example`, `.env.prod.template`, `apps/worker/src/cti_worker/beat.py`
  (`"entity-alias-sync"`, `crontab(hour=5, minute=0, day_of_week=0)`, queue `maintenance`),
  worker task registration
- Test: `tests/unit/test_entity_alias_sync.py` (httpx mocked with `respx` if already a dev
  dependency, else monkeypatched client), `tests/unit/test_config.py`,
  `tests/unit/test_env_prod_template.py`, beat schedule test

**Interfaces:**
- Produces: `sync_galaxy(session: Session, fetch: Callable[[str], dict]) -> SyncResult`
  (`stored: list[str]`, `rejected: dict[str, str]`, `applied: GalaxyResult | None`) and the Celery
  task `entity.alias_sync` that skips when `settings.entity.alias_sync_enabled` is false.

- [ ] **Step 1: Failing tests**: `test_shrink_guard_rejects` (stored 1,000 clusters, new 790 →
  rejected, stored copy unchanged); `test_bad_schema_rejected`; `test_http_error_keeps_previous`;
  `test_success_stores_and_applies`; `test_disabled_setting_skips`; beat entry present.
- [ ] **Step 2-4**: FAIL, implement, PASS.
- [ ] **Step 5: Commit** `feat(worker): weekly MISP Galaxy alias sync`.

### Task 11: Readers part 1 — repositories

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/{article,dashboard,mitre,ta,cve,
  indicator,ransomware,relevance,assessment,threat_reference,ttp_catalog}.py`,
  `packages/cti-core/src/cti_core/{attack_ttp,regions}.py`,
  `packages/cti-core/src/cti_core/db/repositories/entity.py` (create: `mention_rows`)
- Test: the existing tests of these repositories; new `tests/integration/test_mention_rows.py`

**Interfaces:**
- Produces: `mention_rows(*types: str) -> Subquery` with columns `article_id, indicator_id,
  cve_tracker_id, entity_id, name, external_id, type, method, matched_alias, role, evidence,
  extracted` (live, non-suppressed entities). Mapping for readers: actor/malware name →
  `name`; `ttp_id` → `external_id`; `country_code` → `external_id`; `industry` → `name`;
  `cve_id` → `external_id`; old `source` → `method`. `AsyncTARepo` watchlist/profile/whitelist
  methods keep their signatures but read/write `entity_watches`, `entity_profiles`,
  `entities.suppressed` (names from `entities.name`; watch by name resolves through aliases).

- [ ] **Step 1: Write failing tests** in `test_mention_rows.py`: `test_aliases_collapse_in_counts`
  (two articles mention "APT29" and "Cozy Bear" → dashboard actor count returns one row with 2),
  `test_suppressed_hidden`, `test_watchlist_by_alias` (watch "apt36" → `is_watched` true for
  "Transparent Tribe").
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the swaps file by file; keep each public repository method signature.
- [ ] **Step 4: Run** the repository test files and `tests/integration/test_dashboard*.py`,
  `test_ta*.py`, `test_mitre*.py`, `test_cve*.py` — PASS (snapshot diffs only from alias collapse;
  update snapshots with `--snapshot-update` and list each changed value in the commit body).
- [ ] **Step 5: Commit** `refactor(core): read entity mentions in repositories`.

### Task 12: Readers part 2 — services, routers, worker, enrich

**Files:**
- Modify: `apps/api/src/cti_api/routers/{articles,newsroom,ta_groups}.py`,
  `apps/api/src/cti_api/services/{campaign,crossref,diamond_model,exec_dashboard,inferred_ttps,
  newsletter_suggestion,ta_profile,ioc_ta_links,pir}.py`,
  `apps/worker/src/cti_worker/reports/threat_actor_trend.py`,
  `packages/cti-enrich/src/cti_enrich/{routing,countries}.py`,
  `packages/cti-enrich/src/cti_enrich/stages/{classify,score}.py`,
  `scrapers/src/cti_scrapers/feeds/malwarebytes.py`; finally remove the old ORM classes
  (`ArticleThreatActor`, `ArticleMalware`, `ArticleTTP`, `ArticleCountry`, `ArticleIndustry` in
  `db/models/article.py`; `ArticleCve`; `IndicatorThreatActor`; `CveThreatActor`, `CveTTP`;
  `TAWatchlistEntry`, `TAProfile`, `TAWhitelistEntry`) and their relationship attributes, and
  update `db/models/__init__.py`
- Test: existing router/service tests and snapshots; new `tests/integration/test_pir_alias_match.py`

**Interfaces:**
- Consumes: `Article.entity_names`, `mention_rows`, `AsyncTARepo`.
- Produces: unchanged v1 shapes. PIR actor/malware criteria match by `entity_aliases.alias_norm`
  of the criterion's resolved entity.

- [ ] **Step 1: Failing test** `test_pir_actor_criterion_matches_alias` (PIR criterion "apt36",
  article mentions "Transparent Tribe" → matched) and
  `test_ioc_ta_links_uses_entity_names`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.**
- [ ] **Step 4: Run** full fast suite + `uv run pytest tests/integration -q` — PASS; `git grep -nE
  "ArticleThreatActor|ArticleMalware|ArticleTTP\b|ArticleCve\b|ArticleCountry|ArticleIndustry|
  TAWatchlistEntry|TAProfile\b|TAWhitelistEntry|IndicatorThreatActor|CveThreatActor|CveTTP\b" --
  '*.py' ':!tests/integration/test_entity_compat_views.py' ':!alembic'` returns nothing.
- [ ] **Step 5: Commit** `refactor(api): read entities in services and routers`.

### Task 13: Entity API (`/api/entities`)

**Files:**
- Create: `apps/api/src/cti_api/routers/entities.py`, `services/entities.py`, `schemas/entities.py`
- Modify: `apps/api/src/cti_api/services/roles.py` (`manage_entities`, granted to admin and
  analyst built-in roles), router registration, `docs/openapi.json`,
  `apps/web/src/lib/api/schema.d.ts` (regenerated only), `tests/unit/test_route_permissions.py`
- Test: `tests/integration/test_entities_api.py`

**Interfaces:**
- Produces the endpoints and permissions of spec 5.2 exactly. List response `{items, next_cursor}`
  with `EntityListItem(id, type, name, aliases: list[str], external_id, source, suppressed,
  mentions_30d, mentions_90d, last_seen, watched)`; detail `EntityDetail(... description,
  identity_class, merged_into_id, first_seen, aliases: list[AliasOut(id, alias, source)])`;
  relationships `{relationships: list[RelationshipOut], co_mentions: list[CoMention(entity:
  EntityRef, stories: int)]}`; merge returns `MergeResult`; 409 bodies `{detail}`.

- [ ] **Step 1: Failing tests**: list filter by type and alias `q`; detail of merged entity returns
  `merged_into_id`; co-mentions exclude pairs with an existing relationship and respect the
  365-day window; create/alias/merge/split/suppress/relationship create+revoke with audit rows;
  409 alias owned by another entity; 409 cross-type merge; watch per client; analyst can merge;
  a role without `manage_entities` gets 403; profile generation calls the moved LLM function
  (mocked).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** Regenerate the contract:
  `uv run python tools/export_openapi.py && (cd apps/web && pnpm run gen:api)`.
- [ ] **Step 4: Run** tests + `tests/unit/test_route_permissions.py` — PASS.
- [ ] **Step 5: Commit** `feat(api): add entity endpoints`.

### Task 14: STIX builders and reports

**Files:**
- Modify: `apps/api/src/cti_api/services/stix.py` (builders; TA/article/IOC bundle exports use them)
- Test: `tests/unit/test_stix_entities.py`, existing `tests/integration/test_stix*.py`

**Interfaces:**
- Produces: `entity_to_stix(e: Entity) -> dict` (tombstone/suppressed → `revoked: true` with
  required properties only), `relationship_to_stix(r: Relationship, src_stix: str, dst_stix: str)
  -> dict`, `story_to_report(story: Story, refs: list[str], urls: list[str]) -> dict | None`
  (`None` when `refs` empty: Review Focus 4).

- [ ] **Step 1: Failing tests**: one per type (required STIX 2.1 properties; `identity_class`,
  `sectors` for sector identities; `country` for locations; `external_references` for ATT&CK and
  CVE; `created`/`modified` from columns; TLP marking ref); report with no refs returns `None`;
  TA bundle ids equal TAXII ids for the same entity.
- [ ] **Step 2-4**: FAIL, implement, PASS.
- [ ] **Step 5: Commit** `feat(api): build STIX objects from entity rows`.

### Task 15: Machine API (REST v2 + TAXII `intel` + scopes)

**Files:**
- Modify: `apps/api/src/cti_api/services/feed.py` (generalise), `machine_auth.py`
  (`API_TOKEN_SCOPES`), `routers/api_tokens.py` + schema (`scopes` on create, validated),
  `routers/taxii.py` (second collection), `docs/openapi.json`, `schema.d.ts`
- Create: `apps/api/src/cti_api/routers/v2_entities.py`
- Test: `tests/integration/test_feed_query.py` (extend), `tests/integration/test_taxii_intel.py`,
  `tests/integration/test_taxii_interop.py` (extend), `tests/integration/test_api_tokens*.py`

**Interfaces:**
- Produces: `intel_feed_page(session, *, max_tlp: str, limit: int, types: Collection[str] | None,
  changed_after: datetime | None, after: tuple[datetime, str, int] | None, stix_ids:
  Collection[str] | None) -> IntelPage(objects: list[dict], next_cursor: str | None)` merging
  entities, relationships, reports and indicators by `(feed_changed_at, kind, id)` (kind order
  `entity < relationship < indicator < report` so referenced objects come first at equal times);
  the cursor encodes `(changed_at, kind, id)`. `GET /api/v2/entities`, `GET
  /api/v2/relationships` reuse the indicator feed pattern. TAXII collection id
  `INTEL_COLLECTION_ID` (new fixed UUID constant), title "Vareon intel".

- [ ] **Step 1: Failing tests**: paging over mixed kinds has no gaps/duplicates across pages;
  `added_after`; `match[type]=intrusion-set`; amber entity hidden from a clear token, relationships
  touching it hidden, story `object_refs` without it, a story whose refs are all hidden absent
  (Review Focus 4); merged entity appears `revoked`; every ref in a full pull resolves inside the
  pull (ref-integrity); `indicators:read` token gets 403 on `intel` and on `/api/v2/entities`;
  token create with unknown scope 422, default scopes `["indicators:read"]`; `taxii2-client` reads
  `intel`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**; regenerate the contract files.
- [ ] **Step 4: Run** — PASS; existing `test_taxii.py` unchanged and PASS.
- [ ] **Step 5: Commit** `feat(api): serve entities and relationships over TAXII and REST v2`.

### Task 16: Rollback check, timing, release docs

**Files:**
- Modify: `CHANGELOG.md` (`## [0.8.11]`, Indonesian), `docs/prod-upgrade/0.8.11.md`,
  `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`, `docs/LLM_ASSIST_REDESIGN.md` §4 item 1,
  `docs/TARGET_ARCHITECTURE.md` step 5 + progress, `docs/ARCHITECTURE.md` (data model),
  `docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md` (§0 P7c row links the
  P7c spec), `tools/seed/reference/README.md`

- [ ] **Step 1: Controller rollback check** (not a subagent step): start `qacve`, `alembic upgrade
  head`, seed one article; from worktrees at tags `0.8.2` and `0.8.10` (in the scratchpad, removed
  afterwards) run, against that DB, the old `persist` of a fixture article, `AsyncTARepo` watchlist
  add/remove, profile save, whitelist add; then query the new tables. Expected: no error; rows
  resolve to the same entities as new code. Record the commands and result in the runbook's
  Rollback section.
- [ ] **Step 2: Migration timing**: `pg_dump` of dev (read-only, `--no-owner`) restored into
  `qacve` at `c4f1a8d27b93`, `time alembic upgrade head`; record the duration; tear down.
- [ ] **Step 3: Write the docs** per spec §9 (runbook one-off order: ATT&CK sync, `cti-entity
  merge-aliases --dry-run --csv /tmp/galaxy.csv`, review, `--apply`; before/after counts from the
  dev check; R4 wording; Settings note "no key required").
- [ ] **Step 4: Verify**: `uv run ruff check . && uv run ruff format --check . && uv run mypy
  packages/cti-core/src packages/cti-scraper/src && uv run pytest tests/unit tests/contract
  packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro && uv run pytest
  tests/integration -q`; `cd apps/web && pnpm lint && pnpm exec next typegen && pnpm exec tsc
  --noEmit` (contract files compile). All green.
- [ ] **Step 5: Commit** `docs: P7c-1 release notes and prod runbook`.

### After the tasks (controller, needs the user's approval for each outward step)

1. Merge the branch into `origin/Dev`, deploy on dev, run `cti-entity merge-aliases --dry-run`,
   share the CSV, `--apply` after the user's yes.
2. Dev data check of spec §8 (read-only): entities per type, actors before/after, 10 random merges
   listed for the PR, no orphans, PIR match counts before/after, `feed_changed_at` unchanged by
   the 04:00 decay sweep, a TAXII `intel` pull from outside the host.
3. PR to `main` with the user's approval; the P7c-2 web plan starts after this PR is merged.
