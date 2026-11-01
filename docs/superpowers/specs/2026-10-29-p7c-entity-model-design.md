# P7c: entity and relationship model (design)

Status: **design, awaiting review** (2026-10-29). Ships in release **0.8.11** with the other P7
sub-projects; P7c does **not** bump the version. Builds on P7b (PR #81, `main` at `4da216e`,
migration head `c4f1a8d27b93`). Delivered as **two PRs from this one spec**: P7c-1 backend
(sections 3-6) and P7c-2 web (section 7), each with its own plan and its own dev test.

Source documents: `docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md` (section 0:
P7 decomposition), `docs/superpowers/specs/2026-10-29-p7b-machine-api-design.md` (tokens, feed
clock, TAXII), `docs/LLM_ASSIST_REDESIGN.md` section 4 items 1 and 8, `docs/TARGET_ARCHITECTURE.md`
sections 1, 3.1 and 3.3. Protocol reference: STIX 2.1, TAXII 2.1. Alias data: MISP Galaxy
(`github.com/MISP/misp-galaxy`, CC0 1.0).

## 0. Decisions taken in brainstorming (2026-10-29)

| # | Topic | Decision |
|---|---|---|
| D1 | Outcome | Foundation (schema, backfill, live writes), machine interface (TAXII + REST) **and** web entity pages. |
| D2 | Old pages | Entity pages **replace** TA Room and ATT&CK DB; every feature that touches actors, malware, techniques, CVEs, sectors or countries is moved to entity ids and links in the same work. Campaign clusters and the MITRE heatmap stay as analytic views that link to entities. |
| D3 | Entity types | `intrusion-set`, `malware`, `tool`, `attack-pattern`, `vulnerability`, `campaign`, `identity` (sectors as class, ransomware victims as organization), `location` (countries). Stories are STIX `report`s. ATT&CK mitigations stay reference data. |
| D4 | Identity | ATT&CK is the anchor; names actually used become entities; external alias data merges names automatically; analysts merge and split. |
| D5 | Alias source | MISP Galaxy snapshot committed to the repo (used by the backfill, no internet at deploy) plus a weekly sync task that fetches the latest version and keeps the old one on failure. |
| D6 | Relationships | Only explicit SROs are published: ATT&CK, analyst, and story -> entity as `report.object_refs`. Co-mentions are computed and shown as "often mentioned together" with a "make relationship" action; they never reach TAXII unconfirmed. |
| D7 | TAXII | A second collection `intel` with every SDO, SRO, report and indicator; `indicators` unchanged. Entities and relationships get `tlp` (default `clear`) and a feed clock. New token scope `intel:read`. |
| D8 | Approach | **A**: one generic `entity_mentions` table replaces every link table; the old tables become writable compatibility views. Rejected: B (an `entity_id` column on each of 8 link tables: two sources of truth and 8 shapes kept), C (entities as a nightly read-model: analyst merges would have to be replayed, unstable ids). |
| D9 | Delivery | One spec, two plans, two PRs (P7c-1 backend, P7c-2 web), both in 0.8.11. |

## 1. Goal and success criteria

One id per real-world thing. An actor, malware family, technique, CVE, sector, country or victim
has exactly one entity with its aliases, its relationships with provenance, and every story,
indicator and CVE that mentions it. Analysts see and fix it on one page; machines pull it as a
STIX graph.

Success criteria:

- Every row of the old link tables is reachable as an `entity_mentions` row after the migration
  (counts equal per source table), and no mention points to a missing entity.
- Names that MISP Galaxy or ATT&CK list as aliases of one actor resolve to one entity: on dev,
  the 106 article actor strings that share a Galaxy cluster collapse; "apt36" and "Transparent
  tribe" on the watchlist become one watched entity.
- A merge or split by an analyst is exact and reversible (section 3.4) and audit-logged.
- TAXII `intel` returns a graph whose every `*_ref` resolves inside the same collection, filtered
  by the token's TLP, with incremental sync through `added_after`.
- 0.8.2 and 0.8.10 code (deploy.sh auto-rollback) still reads and writes through the old table
  names.
- The web has no TA Room or ATT&CK DB page any more; every actor/malware/technique/CVE/sector/
  country name in the app links to its entity page.
- Prod needs **no new `.env` key**.

## 2. Evidence (dev 172.25.1.77, 0.8.11 with P7b, read-only, 2026-10-29)

- `article_threat_actors`: 733 rows, 309 distinct names (lowercased), all `source=dictionary`;
  305 resolve to `threat_actor_groups`, 76 to ATT&CK groups by name or alias, 0 unmatched.
  Names are stored `capitalize()`d ("Shinyhunters", "Volt typhoon").
- `threat_actor_groups`: 3,995 flat names without aliases or type (malpedia 2,272, eternal-library
  582, threat-card 465, mstic 187, orkl 185, ransomlook 137, manual 75, others); 609 of them are an
  ATT&CK group name or alias, 70 are ATT&CK software names. Loaded once from the legacy Mongo dump
  (`tools/seed/reference/`); no live source.
- `article_malware`: 530 rows, 151 names, all of them ATT&CK software (malware 340, tool 190).
- `article_ttps` 3,930 rows / 449 techniques; `article_cves` 4,817 / 3,278 CVEs; `article_countries`
  911 / 84 ISO codes (with a `role`); `article_industries` 2,405 / 28 free-text labels ("General"
  966; near duplicates such as "Cloud Services" and "Cloud Infrastructure Providers").
- `ransomware_victims`: 1,337 rows, 1,314 victims, 90 groups (33 in `threat_actor_groups`, 3 in
  ATT&CK), 96 countries, 14 industries.
- `indicator_threat_actors`, `cve_threat_actors`, `cve_ttps`: empty. `ta_watchlist` 6 rows
  (including "apt36" and "Transparent tribe", "0ktapus" and "shinyhunters"), `ta_profiles` 6,
  `ta_whitelist` 2 ("testing", "testactor").
- ATT&CK: 197 groups, 975 software, 961 techniques, 25,554 relationships (`malware uses
  attack-pattern` 12,335, `intrusion-set uses attack-pattern` 4,889, `intrusion-set uses malware`
  705, `intrusion-set uses tool` 475, `campaign uses ...` 1,447). **Campaign objects are not
  stored** by `sync_domain` (only referenced from relationships).
- 1,537 stories, 104 with more than one article; 1,698 articles, all with a story.
- MISP Galaxy (2026-10-29): `threat-actor.json` 1,103 clusters, 1,425 synonyms. Of the 309 article
  actor names 226 are in it, and 106 share a cluster with another article name (for example
  `apt29 / cloaked ursa / bluebravo / ice relic`, `0ktapus / scattered spider / scatter swine /
  muddled libra`). 72 of 90 ransomware groups resolve (threat-actor + ransomware + malpedia);
  95 of 151 malware names resolve in `malpedia.json`. Questionable merges exist (`basin`, `polaris`
  into Mustang Panda).
- The old link tables are read or written by **66 Python files**; ~25 web files show actor,
  malware or campaign data.
- P7b follow-up: `ioc.decay_sweep` writes only confidence, actionability, `decayed_at` and
  `updated_at` (`AsyncIndicatorRepo.apply_confidence_and_actionability`); none is in the
  `trg_indicators_feed_bump` column list, so the sweep does not move `feed_changed_at`. On dev the
  trigger was installed on 2026-10-29 after that day's 04:00 sweep; the data check after the next
  sweep is part of the P7c-1 dev test.

## 3. Data model and migration (P7c-1)

One hand-written Alembic migration, `entity_model`, after `c4f1a8d27b93`. Models in
`cti_core.db.models.entity`; repositories `AsyncEntityRepo` / `EntityRepo` (sync for Celery/CLI).

### 3.1 Tables

**`entities`**

| Column | Type | Meaning |
|---|---|---|
| `id` | bigint PK | |
| `type` | varchar(20) not null | CHECK in `ENTITY_TYPES` (D3) |
| `stix_id` | varchar(100) not null unique | ATT&CK objects keep their ATT&CK `stix_id`; others `<type>--uuid5(NAMESPACE, "<type>:<lower(name)>")` at creation, never recomputed |
| `name` | varchar(300) not null | display name (ATT&CK name when anchored) |
| `description` | text null | |
| `external_id` | varchar(50) null | G0016, S0154, T1566.001, C0024, CVE-2024-1234, ISO alpha-2, sector vocabulary value |
| `identity_class` | varchar(20) null | `class` (sector) or `organization` (victim); only for `identity` |
| `source` | varchar(20) not null | `attack, galaxy, dictionary, analyst, cve, iso, sector, ransomware, legacy` |
| `suppressed` | bool not null default false | replaces `ta_whitelist`: never matched, hidden from lists, published as `revoked` |
| `merged_into_id` | bigint FK `entities.id` null | tombstone after a merge (section 3.4) |
| `first_seen`, `last_seen` | timestamptz null | from mentions |
| `tlp` | varchar(12) not null default `clear` | CHECK in `TLP_LEVELS` |
| `created_at`, `updated_at` | timestamptz | `TimestampMixin` |
| `feed_changed_at` | timestamptz not null default `clock_timestamp()` | feed clock (section 3.5) |

Unique index `(type, lower(name)) WHERE merged_into_id IS NULL`; index `(type, external_id)`;
index `(feed_changed_at, id)`.

**`entity_aliases`**: `id`, `entity_id` FK cascade, `entity_type` (denormalised, kept equal by the
repository and a trigger), `alias` varchar(300), `alias_norm` varchar(300) (lowercase, collapsed
whitespace), `source` (`attack, galaxy, analyst, legacy, dictionary`), `created_at`. Unique
`(entity_type, alias_norm)`: one alias belongs to one entity per type. The entity's own name is
always also an alias row.

**`relationships`** (STIX SRO)

| Column | Type | Meaning |
|---|---|---|
| `id` | bigint PK | |
| `stix_id` | varchar(100) unique | ATT&CK relationships keep theirs; others `relationship--uuid5(source_stix:type:target_stix)` |
| `relationship_type` | varchar(30) | CHECK in `uses, targets, attributed-to, exploits, indicates, variant-of, located-at, related-to, subtechnique-of` |
| `source_entity_id` | bigint FK null | exactly one of the two sources (CHECK) |
| `source_indicator_id` | bigint FK `indicators.id` null | for `indicator indicates X` |
| `target_entity_id` | bigint FK not null | |
| `confidence` | smallint null | 0-100; ATT&CK rows 85, analyst rows set by the analyst (default 75) |
| `first_seen`, `last_seen` | timestamptz null | |
| `provenance` | varchar(20) not null | `attack, analyst, ransomware` |
| `description` | text null | |
| `created_by` | varchar(200) null | username or `system:<task>` |
| `revoked_at`, `revoked_by` | null | delete = revoke; published `revoked: true` |
| `tlp`, `created_at`, `updated_at`, `feed_changed_at` | | as `entities` |

Unique `(coalesce(source_entity_id, 0), coalesce(source_indicator_id, 0), relationship_type,
target_entity_id)`. FKs cascade on delete (entities are never hard-deleted by the app; merges
repoint instead).

**`entity_mentions`** (replaces every link table)

| Column | Type | Meaning |
|---|---|---|
| `id` | bigint PK | |
| `article_id`, `indicator_id`, `cve_tracker_id` | bigint FK cascade, null | exactly one (CHECK) |
| `entity_id` | bigint FK not null | |
| `method` | varchar(12) not null | `dictionary, llm, keyword, explicit, analyst, legacy` |
| `matched_alias` | varchar(300) not null | the text form that produced the mention (Tier 1 `matched`, LLM name, or the old link-table string); makes split exact |
| `role` | varchar(10) null | countries: the old `article_countries.role`; else null |
| `evidence` | text null | TTP evidence sentence |
| `extracted` | jsonb null | old extra columns: TTP `extracted_id`/`extracted_name`, CVE `in_title`/`first_seen_at` |
| `created_at` | timestamptz | |

Unique `(article_id, indicator_id, cve_tracker_id, entity_id, role)` with `NULLS NOT DISTINCT`;
indexes on `(entity_id, article_id)`, `article_id`, `indicator_id`, `cve_tracker_id`.

Story mentions are not stored: they are the union of the member articles' mentions.

**Per-client and profile tables**

- `entity_watches(id, client_id FK cascade, entity_id FK cascade, created_at)`, unique
  `(client_id, entity_id)`; replaces `ta_watchlist`.
- `entity_profiles(id, entity_id FK cascade unique, profile jsonb, generated_at)`; replaces
  `ta_profiles` (same JSON shape).

**Feed clock on stories**: `stories.feed_changed_at` with the same default and index (section 3.5).

### 3.2 Migration steps (pure SQL, set-based, no Python, no network)

1. Create the tables above.
2. ATT&CK: `attack_groups` -> `intrusion-set`, `attack_software` -> `malware`/`tool` by
   `software_type`, `attack_techniques` -> `attack-pattern` (`external_id` = technique id), each
   with its official aliases (`source=attack`). `attack_relationships` whose both ends are now
   entities and whose type is in the CHECK list -> `relationships` (`provenance=attack`,
   `confidence=85`, ATT&CK `stix_id`); `revoked-by`, `detects`, `mitigates` and `x-mitre-*` stay
   only in `attack_relationships`. Campaign objects arrive with the next ATT&CK sync (section 4.3).
3. Names from the old tables, per type, by lowercase match against `entity_aliases.alias_norm`;
   unmatched names become entities (`source=legacy` for actors and malware, keeping the old
   string as name and alias):
   actors from `article_threat_actors`, `indicator_threat_actors`, `cve_threat_actors`,
   `ta_watchlist`, `ta_profiles.actor_name`, `ransomware_victims.group_name`, and PIR actor
   criteria; malware/tools from `article_malware` (`kind`); techniques from `article_ttps` and
   `cve_ttps` (by technique id; unknown ids become `legacy` attack-patterns); `vulnerability` from
   `article_cves` and `cve_tracker` (`source=cve`); `location` from `article_countries` and
   `ransomware_victims.country_code` (`source=iso`, names from a static ISO table inserted by the
   migration); `identity class` from `article_industries` and `ransomware_victims.industry`
   through the sector mapping (section 3.3); `identity organization` from
   `ransomware_victims.victim` (`source=ransomware`).
4. Copy every link row into `entity_mentions` (method from the old `source` column; old string as
   `matched_alias`; TTP/CVE extras into `extracted`). Ransomware: `group targets victim` and
   `victim located-at country` relationships (`provenance=ransomware`, `confidence=50`, first/last
   seen from `discovered`).
5. `ta_watchlist` -> `entity_watches`, `ta_profiles` -> `entity_profiles`, `ta_whitelist` names ->
   `suppressed = true` on the matching (or a new `legacy`) actor entity.
6. `first_seen`/`last_seen` from mentions (`articles.published_at`, falling back to `created_at`).
7. Backfill feed clocks with `greatest(created_at, ...)` as P7b; stories from `last_seen_at`.
8. Rename the old tables to `_legacy_<name>` (kept until the release after 0.8.11 for audit and a
   manual undo), then create the compatibility views (section 3.6) and the feed triggers.

The migration sets `lock_timeout` so a stuck lock fails the deploy fast instead of hanging it.
Downgrade: drop views and triggers, rename the legacy tables back, drop the new tables and the
stories column. Rows written after the upgrade through the new tables are lost on downgrade; the
runbook says so (deploy.sh never downgrades).

### 3.3 Sector mapping

A constant in `cti_core.entity.sectors` maps the LLM industry labels (and the ransomware
`industry` values) to the STIX 2.1 `industry-sector-ov` vocabulary, for example
"Information Technology & Software", "Technology & Software", "Cloud Services", "Cloud
Infrastructure Providers", "Cloud & Hosting Providers" -> `technology`; "Finance & Insurance" ->
`financial-services`; "Government & Public Sector" -> `government`; "Healthcare & Life Sciences"
-> `healthcare`; "Critical Infrastructure" -> `infrastructure`; "Energy & Utilities" -> `energy`.
"General" maps to nothing (no mention). The migration SQL is generated from the same table and a
unit test keeps them equal; unknown labels become `legacy` sector identities, so nothing is lost,
and the test lists them.

### 3.4 Merge, split and suppression (exact and reversible)

- **Merge** `A into B` (same type): aliases of A move to B; mentions, relationships (deduplicated
  by the unique key, keeping the higher confidence and the wider seen range), watches and the
  profile (only when B has none) repoint to B; A gets `merged_into_id = B` and stays as a
  tombstone with its `stix_id`. One transaction; an `audit_log` row lists every moved alias id.
- **Split** `alias_ids out of B`: creates a new entity, or revives the tombstone whose original
  aliases they were (its `stix_id` comes back), and moves those aliases plus every mention whose
  `matched_alias` normalises to one of them. Relationships are not moved automatically; the dialog
  lists them for the analyst.
- **Suppress**: `suppressed = true`; the dictionary drops all its aliases, lists hide it, STIX
  publishes it `revoked`. Existing mentions are kept, so unsuppress restores everything.
- Automatic merges (Galaxy, section 4.2) use the same code path with actor `system:galaxy`, so
  Split undoes them like analyst merges.

### 3.5 Feed clocks (pattern of P7b)

- `entities`: `BEFORE UPDATE` trigger bumps `feed_changed_at = clock_timestamp()` when `name`,
  `description`, `external_id`, `suppressed`, `merged_into_id`, `identity_class` or `tlp` change;
  `AFTER INSERT OR DELETE OR UPDATE OF alias, entity_id ON entity_aliases` bumps the entity (on an
  UPDATE both the old and the new entity, so a merge that repoints aliases moves both). `first_seen`/`last_seen` do **not** bump (they change
  with every article and are not published).
- `relationships`: bumps on `relationship_type`, ends, `confidence`, `description`, `revoked_at`,
  `tlp`.
- `stories`: bumps on `title` and `article_count`; `AFTER INSERT OR DELETE OR UPDATE OF entity_id,
  article_id ON entity_mentions` with an `article_id` bumps the article's story (its `object_refs`
  changed; on an UPDATE both the old and the new story). The UPDATE cases exist because merge and
  split repoint mentions and aliases by UPDATE (plan Ruling 14). A change of an entity's
  `suppressed`, `merged_into_id` or `tlp` also bumps the relationships touching it and the stories
  whose articles mention it, and `indicator_sources` changes bump the article's story (Ruling 33).
- The model docstrings name the triggers and the migration; dedicated trigger tests (section 8).

### 3.6 Compatibility views (rollback safety)

Each old name becomes a view with the old columns:

| View | Reads from | `INSTEAD OF` triggers |
|---|---|---|
| `article_threat_actors(id, article_id, threat_actor, source)` | `intrusion-set` mentions with `article_id`; `threat_actor` = entity name | INSERT, DELETE |
| `article_malware(id, article_id, name, kind, source)` | `malware`/`tool` mentions | INSERT, DELETE |
| `article_ttps(id, article_id, ttp_id, ttp_name, extracted_id, extracted_name, source, evidence)` | `attack-pattern` mentions | INSERT, DELETE |
| `article_cves(article_id, cve_id, in_title, first_seen_at)` | `vulnerability` mentions | INSERT, DELETE |
| `article_countries(id, article_id, country_code, role)` | `location` mentions | INSERT, DELETE |
| `article_industries(id, article_id, industry, source)` | sector mentions; `industry` = the original label (`matched_alias`) | INSERT, DELETE |
| `indicator_threat_actors`, `cve_threat_actors`, `cve_ttps` | mentions with `indicator_id` / `cve_tracker_id` | INSERT, DELETE |
| `ta_watchlist(id, name, client_id, created_at, updated_at)` | `entity_watches` | INSERT, DELETE |
| `ta_profiles(id, actor_name, profile, generated_at)` | `entity_profiles` | INSERT, UPDATE, DELETE |
| `ta_whitelist(id, name, added_date)` | suppressed actors | INSERT, DELETE |

The INSERT triggers call one SQL function `entity_resolve(type, name, source)` with the same rules
as the Python resolver (alias lookup, else create a `legacy` entity), so rolled-back code produces
the same rows as new code. Conflict behaviour matches the old unique constraints. Which views
0.8.2 and 0.8.10 actually write is confirmed in the plan by grep at the tags; views that neither
writes stay read-only. The views are dropped in the first release after 0.8.11.

## 4. Resolution and write paths (P7c-1)

### 4.1 Resolver (`cti_core.entity.resolve`)

`resolve(session, type, name, *, source) -> Entity`: normalise, look up `entity_aliases` for the
type (following `merged_into_id`), else insert the entity and its alias (`ON CONFLICT` on the alias
index, then re-read: safe under concurrent workers). Suppressed entities are returned so the caller
can skip them. Used by the pipeline, the API and the commands; the SQL `entity_resolve` mirrors it
and a test runs both on the same inputs.

### 4.2 Galaxy alias merge (`cti-entity merge-aliases`)

- Input: `tools/seed/reference/misp-galaxy/{threat-actor,ransomware,malpedia}.json` (CC0; snapshot
  date and upstream commit in a `SOURCE` file), or the copy stored by the sync task.
- For each cluster: actor clusters (`threat-actor`, `ransomware`) merge `intrusion-set` entities,
  `malpedia` clusters merge `malware`/`tool` entities. The target is the ATT&CK entity when exactly
  one is in the cluster, else the entity with the most mentions. All synonyms become aliases
  (`source=galaxy`) of the target, also for clusters with no existing entity (so future articles
  resolve).
- Guards:
  1. a cluster touching **two different ATT&CK entities** is skipped and reported;
  2. a synonym in the Tier 1 `AMBIGUOUS` set, or a single common word known only from
     `threat_actor_groups` (the P4 context-rule list), is added as an alias only when no other
     entity owns it and **never causes a merge** of an existing entity;
  3. an alias already owned by another entity is not moved (ATT&CK and analyst aliases win);
  4. a merge an analyst has undone (an audit row splitting a `system:galaxy` merge) is never redone.
- `--dry-run` prints the planned merges, skips and conflicts as CSV; `--apply` performs them
  through the merge code path (section 3.4). The runbook runs `--dry-run` first and has the CSV
  reviewed before `--apply`.
- Idempotent: a second run changes nothing.

### 4.3 Writers

- `cti_enrich.stages.persist`: writes `entity_mentions` through the resolver for actors, malware,
  tools, TTPs, CVEs, countries and sectors, instead of the old link tables; updates the entities'
  `first_seen`/`last_seen` with one statement per article.
- Tier 1 dictionary (`cti_enrich.tier1.dictionary`): built from `entity_aliases` of non-suppressed,
  non-merged entities plus `threat_actor_groups` names that are not yet aliases; the canonical
  form is the entity name. The dictionary version hash includes the alias set, so the per-process
  cache refreshes when aliases change.
- ATT&CK sync (`AttackRepo.sync_domain`): after a domain sync, upserts entities, aliases and
  relationships from the same bundle, **including campaign objects** (`campaign` entities with
  `external_id` C0xxxx and their `uses`/`attributed-to` relationships).
- Ransomware sink: victims, group, country and sector go through the resolver, plus the `targets`
  and `located-at` relationships.
- `entity.alias_sync` (Celery, `maintenance` queue, weekly beat, Sunday 05:00): fetches the three
  Galaxy files from GitHub raw with timeouts, validates the schema, rejects a file whose cluster
  count drops more than 20 % against the stored copy, stores the copy in
  `reference_snapshots(name, fetched_at, sha256, content jsonb)` and runs the merge in apply mode.
  On any failure it logs and keeps the previous copy. Switch: `Settings.entity.alias_sync_enabled`,
  default `true`, so prod needs no `.env` key (documented in `.env.example` and
  `.env.prod.template` as an optional key).

## 5. API (P7c-1)

### 5.1 v1 readers

Every reader of the old tables moves to `entity_mentions` join `entities` (66 files: services,
repositories, routers, Celery tasks, newsletter/recap/exec/PIR/dashboard code). **v1 response
shapes do not change**; names come from `entities.name`. Behaviour changes on purpose: aliases of
one entity count as one series in dashboards, leaderboards, trends, filters, PIR matching and
recaps. PIR criteria keep storing names but match through `entity_aliases`.

### 5.2 Entity API (`/api/entities`, web JWT, `require_permission`)

| Endpoint | Permission | Notes |
|---|---|---|
| `GET /api/entities?type&q&watched&cursor&limit` | `view_ta` | `q` matches aliases; mention counts over 30/90 days; excludes merged and (unless `include_suppressed`) suppressed |
| `GET /api/entities/{id}` | `view_ta` | aliases, sources, `merged_into_id` (the web redirects) |
| `GET /api/entities/{id}/relationships` | `view_ta` | SROs both directions; `co_mentions`: top entities co-mentioned in the same stories (computed at read time, 365-day window, limit 50, excluding pairs that already have a relationship) |
| `GET /api/entities/{id}/stories`, `/indicators`, `/cves`, `/timeline` | `view_ta` | from mentions (stories through member articles) |
| `GET /api/entities/{id}/attack` | `view_ta` | techniques, mitigations, Navigator layer JSON (replaces the ATT&CK DB detail endpoints) |
| `POST /api/entities` | `manage_entities` | type, name, aliases, description |
| `PATCH /api/entities/{id}` | `manage_entities` | name, description, `suppressed` |
| `POST /api/entities/{id}/aliases`, `DELETE /api/entities/{id}/aliases/{alias_id}` | `manage_entities` | 409 when the alias belongs to another entity |
| `GET /api/entities/{id}/merge-preview?into_id` | `manage_entities` | counts that would move |
| `POST /api/entities/{id}/merge` `{into_id}` | `manage_entities` | 409 across types; returns moved counts |
| `POST /api/entities/{id}/split` `{alias_ids}` | `manage_entities` | returns the new or revived entity |
| `POST /api/relationships`, `DELETE /api/relationships/{id}` | `manage_entities` | create (including "make relationship"), revoke |
| `PUT` / `DELETE /api/entities/{id}/watch` | `manage_pir` | per active client, as the old watchlist |
| `POST /api/entities/{id}/profile` | `manage_intel` | LLM profile, moved from `ta_profile.py`; actors only |

`manage_entities` is a new permission granted to `admin` and `analyst`. Every write is in
`audit_log`. Schemas are typed; `docs/openapi.json` and `schema.d.ts` are regenerated. The old TA
and ATT&CK endpoints stay in P7c-1 (the old web still calls them, now reading the new tables) and
are removed in P7c-2 together with their pages.

### 5.3 Machine API

- `GET /api/v2/entities?type&changed_after&cursor&limit` and `GET /api/v2/relationships?...`:
  P7b feed pattern (the shared query builder generalised over the feed tables: TLP per token,
  60 s settle lag, keyset cursor on `(feed_changed_at, id)`), scope `intel:read`.
- TAXII: collection `intel` (fixed UUID) next to `indicators`. Objects: entities (merged and
  suppressed ones as `revoked: true` with the minimum required properties), relationships,
  reports and indicators. Paging merges the per-table feeds by `(feed_changed_at, kind, id)` with
  one cursor. `match[type]` filters the STIX type. Every `*_ref` of a returned object points to an
  object in the collection for the same token: a relationship whose end is above the token's TLP is
  not returned, and `object_refs` are filtered to visible objects.
- Report per story: `name` = title, `published` = first seen, `object_refs` = visible entities and
  indicators of the member articles, `external_references` = article URLs, `created` =
  `stories.created_at`, `modified` = `stories.feed_changed_at`. Stories with no refs are skipped
  (STIX requires at least one).
- Scope `intel:read` is added to `API_TOKEN_SCOPES`; the token create API takes `scopes` (default
  `["indicators:read"]`, so existing behaviour and tokens are unchanged).

### 5.4 STIX builders (`services/stix.py`)

One builder per entity type from the row (`created` = `created_at`, `modified` =
`feed_changed_at`, `aliases`, `external_references` for ATT&CK/CVE, `object_marking_refs` TLP 2.0,
`identity_class` / `sectors`, `location.country`). The existing TA, article and IOC bundle exports
use the same builders, so ids agree between exports and TAXII; their LLM-derived extra objects
(profile techniques, `known_iocs`) keep working through the entity rows.

## 6. Not built in the backend

Co-mentions as SROs (D6), LLM relationship assessment, sightings, MISP/OpenCTI connectors, fuzzy
name merging, re-enriching old articles, TLP above `clear` for any input.

## 7. Web (P7c-2)

### 7.1 New pages (Intelligence section, deep-linkable)

- `/intelligence/entities`: tabs Actors, Malware & tools, Techniques, Vulnerabilities, Campaigns,
  Sectors, Countries, Victims; alias search; "Watched" filter; mention counts 30/90 days and last
  seen; "New entity" for `manage_entities`; ATT&CK sync status card on Techniques (admin); the
  watchlist Navigator layer button on Actors.
- `/intelligence/entities/[id]`: header (name, type, aliases, source, ATT&CK id, Watch button);
  tabs Overview (description, LLM profile generate/regenerate), Relationships (SROs and "Often
  mentioned together" with "Make relationship"), Stories, Indicators, CVEs, Timeline, ATT&CK
  (actors, software, techniques: techniques, mitigations, Navigator layer). Actions for
  `manage_entities`: edit, aliases add/remove, Merge (search target, preview counts, confirm),
  Split (pick aliases), Suppress. A merged entity redirects to its target.

### 7.2 Retired

TA Room and ATT&CK DB pages, components and their v1 endpoints are removed; their routes redirect
(`/intelligence/threat-actor-room` -> Actors tab, `/intelligence/attack-db` -> Techniques tab).
Mapping: TA groups -> Actors tab; watchlist -> Watch + filter; whitelist -> Suppress; profile ->
Overview; TA articles dialog -> Stories tab; ATT&CK groups/software/techniques -> entity tabs;
mitigations -> technique ATT&CK tab; sync status -> Techniques card and Data health.

### 7.3 Touching features

A single `EntityChip` (type icon + name, linking to the entity page) replaces plain names in:
dashboard (overview cards, signal hero), exec (filter bar entity pickers, sector heatmap on sector
entities, role-gated panels), newsroom (article modal chips, inferred TTPs, list sheet), PIR form
(actor/malware criteria from an alias autocomplete instead of free text) and list, IOC detail TA
links, CVE ticket tab, recap, newsletter queue, early warning, risk matrix, campaign clusters
(clusters, diamond model, kill chain) and the MITRE heatmap (technique drill links).
*Admin > API tokens* gets scope checkboxes (`indicators:read`, `intel:read`).

### 7.4 Rules

Base UI (`render=`, `SelectItem` children a single string), no `backdrop-blur`, theme tokens,
light and dark mode, 375 px without page-level horizontal scroll, `useCan` hides actions the role
cannot use, `loose-types.ts` entries replaced by generated types where touched.

## 8. Testing

- **Unit**: resolver (alias order, merged redirect, suppressed, create); sector mapping covers
  every dev label; Galaxy merge on a small fixture (two-ATT&CK skip, ambiguous synonym does not
  merge, analyst alias not moved, undone merge not redone, idempotent second run); merge/split
  logic; STIX builders per type and report (refs, revoked tombstone); feed cursor over several
  tables; route coverage (`manage_entities`, `require_token("intel:read")`); permission catalog.
- **Integration** (testcontainers):
  - migration up/down on seeded data with the dev shapes: mention count per old table equal, no
    orphan mention, ATT&CK relationship count, watch/profile/suppressed moved;
    `test_migrations_match_models` green;
  - **rollback**: 0.8.2 and 0.8.10 code (worktrees at the tags, pattern of the P7a controller
    check) run `persist`, IOC upsert, watchlist add/remove and profile save against the migrated
    DB through the views; the rows are readable through the new tables and resolve to the same
    entities as new code; Python resolver and SQL `entity_resolve` agree on the same inputs;
  - triggers: entity, alias, relationship and story clocks bump on the listed columns only;
    `last_seen` updates do not bump; a mention insert bumps the story;
  - merge/split: mentions, relationships, watches and profile move; split after merge restores
    the original entity, `stix_id` and mentions exactly;
  - v1 behaviour: existing router tests and syrupy snapshots pass; snapshot diffs are reviewed and
    allowed only where aliases now collapse;
  - TAXII `intel`: paging without gaps or duplicates across the merged feeds, TLP filtering of
    objects and refs, `match[type]`, revoked tombstones, every ref resolvable; `taxii2-client`
    (already a dev dependency since P7b) reads the collection;
  - REST v2 entities/relationships; token scopes (an `indicators:read` token gets 403 on `intel`).
- **Data check on dev** (read-only, after the merge to `origin/Dev`): entities per type; actor
  entities before and after `merge-aliases --dry-run` and `--apply`; 10 random merges inspected
  by hand and listed in the PR; no orphans; PIR match counts before/after; the P7b decay-sweep
  check (no `feed_changed_at` jump at the 04:00 sweep).
- **Migration timing**: the migration run on a `pg_dump` of dev restored into the isolated `qacve`
  project; duration recorded in the runbook.
- **Web (P7c-2)**: `pnpm lint`, `next typegen` + `tsc --noEmit`, `pnpm build`; browser QA on
  `qacve` (entity list and page, merge/split dialogs, every touched feature, redirects, analyst vs
  admin, light/dark, 375 px).

## 9. Release (part of 0.8.11, no version bump)

- `CHANGELOG.md`: add to `## [0.8.11]` (Indonesian), including the deliberate change that aliases
  of one actor now count as one (dashboards, PIR results, recaps).
- `docs/prod-upgrade/0.8.11.md` and the 0.8.11 part of `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`
  (eight headings): migration `entity_model` and its measured duration; no new `.env` key;
  one-off commands in order: ATT&CK sync (campaigns), `cti-entity merge-aliases --dry-run`
  (review the CSV), `--apply`; after deploy: counts per type, an entity page, a TAXII `intel` pull
  with an `intel:read` token; rollback: 0.8.2 code works through the views, merges are undone with
  Split; known risks.
- `docs/LLM_ASSIST_REDESIGN.md` section 4 item 1 and `docs/TARGET_ARCHITECTURE.md` step 5 marked
  delivered; `docs/ARCHITECTURE.md` data model section updated; the P7c row of the P7a spec
  section 0 links this spec; `tools/seed/reference/README.md` lists the Galaxy snapshot.
- Each PR: merge to `origin/Dev`, test on dev, PR to `main` with the user's approval.

## 10. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | A wrong automatic merge from Galaxy (common-word synonyms, over-wide clusters) mixes two actors. | Guards in section 4.2 (two-ATT&CK skip, ambiguous synonyms never merge, ATT&CK/analyst aliases never move, undone merges never redone); `--dry-run` CSV reviewed before `--apply` in prod; every merge audit-logged and exactly reversible by Split (`matched_alias`, revived tombstone); 10 sampled merges checked on dev and listed in the PR. |
| R2 | A compatibility-view trigger is wrong and deploy.sh's auto-rollback to 0.8.2 cannot write articles. | Views written by 0.8.2/0.8.10 found by grep at the tags in the plan; an integration test runs the real 0.8.2 and 0.8.10 code paths against the migrated DB; the trigger uses the same rules as the Python resolver (tested side by side); legacy tables kept renamed for a manual undo. |
| R3 | 66 reader files change and one silently returns different data. | v1 shapes kept; existing router tests and syrupy snapshots must pass; snapshot diffs reviewed and allowed only for alias collapse; reader moves grouped per area in the plan, each with its own tests and review. |
| R4 | Users notice changed numbers (actor counts, PIR results, leaderboards) after aliases collapse. | Deliberate; stated in CHANGELOG and runbook with before/after counts from dev; PIR match counts compared in the dev check. |
| R5 | The migration takes long or locks tables in prod. | Set-based SQL on a few tens of thousands of rows; timed on a dev dump in `qacve`; runs in the `migrate` service before the app starts; `lock_timeout` so a stuck lock fails fast instead of hanging the deploy. |
| R6 | The weekly sync pulls a broken or shrunk Galaxy file. | Schema validation, 20 % shrink guard, previous copy kept, merges still pass the R1 guards; switch `entity.alias_sync_enabled`. |
| R7 | A TAXII consumer cannot resolve a ref (object filtered by TLP, or a tombstone). | Refs filtered to visible objects; relationships with an invisible end not returned; tombstones published as revoked objects; interop test with `taxii2-client` and a ref-integrity test. |
| R8 | New mentions keep the old capitalised strings and show duplicates. | Writers resolve to entities; views return `entities.name`, so old and new rows show the same name. |
| R9 | P7c-1 is deployed without P7c-2 (web still old). | P7c-1 keeps every v1 endpoint the old web calls, reading the new tables; both ship in 0.8.11, and the tag waits for the last P7 PR. |
| R10 | The `stories` feed trigger fires on every article attach and makes reports churn. | Only `title`/`article_count` and mention changes bump; churn equals new articles per day (similar to the P7b indicator churn); settle lag as P7b. |

## 11. Out of scope

Co-mention SROs, LLM relationship assessment, sightings (P7d), hunting packs (P7e), PIR at ingest
(P7f), MISP/OpenCTI connectors (roadmap #8), fuzzy merging, TLP above `clear` for inputs,
per-client entities, dropping the compatibility views and `_legacy_*` tables (first release after
0.8.11).
