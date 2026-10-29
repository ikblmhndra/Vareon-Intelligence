# P7a: indicators, lifecycle and TLP/PAP (design)

Status: **design, awaiting review** (2026-10-28). Target release **0.8.11**, after P6 (0.8.10, PR #79)
is merged; this branch is rebased on `main` before implementation starts.

Source documents: `docs/LLM_ASSIST_REDESIGN.md` section 4 (items 2-4) and section 5 (row "P7+ CTI
model"), `docs/TARGET_ARCHITECTURE.md` section 3.1 (`indicators`).

## 0. P7 decomposition (decided 2026-10-28)

P7 covers several independent subsystems. It is split into sub-projects; each gets its own spec,
plan, PR and small 0.8.x release, merged to `origin/Dev` and tested on dev before the PR to `main`.

Guiding decision: **API-first, vendor-neutral.** The platform exposes standard interfaces (TAXII 2.1
per the OASIS spec, plain REST) and consumers adapt to them. No Splunk-specific connector, lookup
exporter or KV-store push. Splunk is the first consumer, not a design target. The consuming team does
not yet know which TAXII version its tooling supports, so the spec is followed as published.

| # | Sub-project | Scope | Depends on | State |
|---|---|---|---|---|
| **P7a** | Indicators, lifecycle, TLP/PAP | `iocs` renamed to `indicators`; `valid_from`/`valid_until` by type; `revoked` on analyst FP; TLP/PAP on indicators with a per-scraper default; state in API, UI and STIX export | P6 merged | **this spec** |
| P7b | Machine API | Scoped API tokens; `/api/v2/indicators` REST feed (JSON/CSV, cursor); TAXII 2.1 server (discovery, collections, objects, `added_after`); TLP enforced per token | P7a | next |
| P7c | Entity + relationship model | `entities`, `entity_aliases`, `relationships` shaped like STIX SROs with provenance; backfill from `article_*` link tables (dev: 301 actor strings, 297 resolve to `threat_actor_groups`; 148 malware names) | none (TAXII serves the objects once both exist) | later |
| P7e | Hunting packages | Template (not LLM) SPL for a story's IOCs and TTPs over CIM data models, plus Sigma rules indexed by ATT&CK ID (SigmaHQ download needs approval) | stories/TTPs (exist), P7a | later |
| P7f | PIR at ingest + own-asset relevance | PIR criteria and techstack matched at ingest, raising P6 priority | P6 | later; data is thin today (1 client, 1 PIR, 34 techstack entries) |
| P7g | Persist-first enrichment | Article persisted before the LLM tier; LLM fields filled by a separate task | none; conflicts only with `stages/persist.py` | slot in any time after P6 |
| P7d | Sightings in | Generic `POST /api/v2/sightings` (token): indicator, count, first/last seen, data model, external ref. No raw logs, hostnames or usernames | P7b | **deferred** until a consumer actually wants to send sightings |

Order: **P7a → P7b → P7c → P7e → P7f**, P7g in between, P7d when asked for. This differs from the
first guess (entity model first) because of the dev data (read-only, 2026-10-28): the first consumer
ingests indicators, `ioc_threat_actors`, `cve_threat_actors` and `ioc_feedback` are all empty, and no
table has a TLP column, so no export can be opened safely before P7a. Section 4 item 4 of
`docs/LLM_ASSIST_REDESIGN.md` (IOC lifecycle) is only partly delivered while P7d is deferred.

## 1. Goal and success criteria

Give every indicator an explicit, explainable lifecycle and a marking, so a feed (P7b) can answer
"which indicators are valid now, and who may see them" without guessing from a decayed score.

Success criteria:

- `indicators` exists with all rows, ids and child rows of `iocs`; `test_migrations_match_models`
  is green; downgrade restores `iocs` exactly.
- Every indicator has a computed `state` in `active | expired | revoked | allowlisted`. On the dev
  snapshot of 2026-10-28 the rules give **5,281 active, 157 expired, 29 allowlisted, 0 revoked**;
  after deploy on dev the numbers match within the IOCs added since.
- An analyst FP revokes at once and a TP restores; a revoked indicator leaves STIX export, stats,
  campaigns and recap counts (section 4).
- TLP/PAP are visible and editable per indicator; the STIX export carries `valid_from`,
  `valid_until` and TLP 2.0 marking refs.
- Changing a TTL in `.env` re-computes `valid_until` for existing rows without a migration.
- Nothing outside the app that reads `iocs` breaks silently (section 7).

## 2. Data model and migration

One hand-written Alembic migration, `iocs_to_indicators`.

### 2.1 Renames (instant, data and ids kept)

| Old | New |
|---|---|
| `iocs` | `indicators` |
| `ioc_sources`, `ioc_tags`, `ioc_threat_actors`, `ioc_feedback` | `indicator_sources`, `indicator_tags`, `indicator_threat_actors`, `indicator_feedback` |
| column `ioc_id` (4 child tables) | `indicator_id` |
| sequences, indexes, FKs, `uq_iocs_type_value`, `uq_ioc_tag`, `uq_ioc_threat_actor` | renamed to match the new model names |

Only the four child tables reference `iocs.id`; no other table does. `ioc_allowlist_entries` is not
renamed (it is a reference list of domains, not indicator data).

### 2.2 New columns on `indicators`

| Column | Type | Meaning |
|---|---|---|
| `valid_from` | timestamptz not null | set from `first_seen_at` in the migration; never changes afterwards |
| `valid_until` | timestamptz null | `last_seen_at` + TTL of the type; `NULL` = does not expire (hashes) |
| `revoked_at` | timestamptz null | set by an analyst FP |
| `revoked_by` | varchar(200) null | username |
| `tlp` | varchar(12) not null default `clear` | CHECK in `clear`, `green`, `amber`, `amber+strict`, `red` (TLP 2.0) |
| `pap` | varchar(8) not null default `clear` | CHECK in `clear`, `green`, `amber`, `red` |

Index on `valid_until`. The migration does **not** fill `valid_until`; the reconcile task does
(section 3.3), so the TTL values live in one place.

### 2.3 State is computed, not stored

`Indicator.state` is a hybrid property with one SQL expression, evaluated in this order:

1. `revoked_at IS NOT NULL` → `revoked`
2. `auto_suppressed` → `allowlisted`
3. `valid_until < now()` → `expired`
4. otherwise → `active`

Expiry happens by the passage of time, so a stored state would need a sweep and could drift.

### 2.4 Python renames

`models/ioc.py` → `models/indicator.py`; `IOC`, `IOCSource`, `IOCTag`, `IOCThreatActor`,
`IOCFeedback` → `Indicator`, `IndicatorSource`, `IndicatorTag`, `IndicatorThreatActor`,
`IndicatorFeedback`; `IOCRepo`/`AsyncIOCRepo` → `IndicatorRepo`/`AsyncIndicatorRepo`. About 25
production files and 31 test files change mechanically. Modules named for the concept rather than
the table (`cti_core/ioc/extractor.py`, `canonical.py`, `allowlist.py`, `services/ioc_*.py`) keep
their names. The v1 routes stay under `/api/iocs` with the same response shape plus new fields.

## 3. Rules

### 3.1 Validity (TTL by type)

A pure function in `cti_core/indicator/validity.py` computes `valid_until(type, last_seen_at, ttl)`.

| Type | Default TTL | Setting |
|---|---|---|
| `ip` | 30 days | `INDICATOR__TTL_IP_DAYS` |
| `domain` | 90 days | `INDICATOR__TTL_DOMAIN_DAYS` |
| `url`, `url_with_path` | 90 days | `INDICATOR__TTL_URL_DAYS` |
| `email` | 90 days | `INDICATOR__TTL_EMAIL_DAYS` |
| `md5`, `sha1`, `sha256` | none (`NULL`) | none |

The settings are a new nested `IndicatorSettings` with defaults, so prod needs no `.env` change.
They are added to `.env.example` and `.env.prod.template` in the same commit
(`test_config.py`, `test_env_prod_template.py`).

### 3.2 On ingest (both upsert paths)

`IndicatorRepo.upsert` (sync, `stages/persist.py`) and `AsyncIndicatorRepo.upsert` both:

- set `last_seen_at = now` and `valid_until = max(current valid_until, now + TTL)`, so an expired
  indicator seen again becomes active again;
- leave `valid_from` unchanged;
- **do not clear a revocation**: an analyst FP stays final; the new source is still recorded in
  `indicator_sources`, so the analyst can see that it came back;
- set `tlp`/`pap` to the **most restrictive** of the current value and the source default
  (section 3.4). Markings never go down automatically.

### 3.3 Reconcile task `indicator.reconcile_validity`

Enqueued on API start (the `lifespan` hook, same mechanism as P6's `confidence.recompute_all`;
the task is idempotent, so several uvicorn processes enqueueing it is harmless) and daily via beat,
on the `maintenance` queue. It compares a fingerprint of
the current TTL settings with `job_state["indicator.ttl_fingerprint"]`. When they differ it runs one
`UPDATE` that sets `valid_until = last_seen_at + TTL` per type (`NULL` for hashes) on all
non-revoked rows, then stores the new fingerprint. When they match it returns at once (idempotent).
The result (rows, TTLs) is logged through structlog. This is also the initial backfill after the
migration.

### 3.4 Default marking per source

`ScraperMeta.tlp` and `ScraperMeta.pap` (default `clear`), declared in the scraper file like
`content_kind`. `tasks/enrich.py::_relevance_for` already reads `meta.content_kind`; it also
returns the markings, the pipeline passes them to persist, and persist passes them to the upsert.
`source_reliability_entries` (reshaped by P6) is not touched. Today all 100 scrapers are public
(credentialed scrapers only use keys for public GitHub, X and NVD data), so every value is `clear`;
a paid or partner feed later sets `tlp="amber"` in its file.

TLP on articles, stories and entities is out of scope until a non-public input exists.

## 4. API

- `POST /api/iocs/{id}/feedback`: `fp` also sets `revoked_at`/`revoked_by` (no-op if already
  revoked); `tp` on a revoked indicator clears both (restore). Counts, confidence recompute and
  audit log unchanged. Permission rises from any authenticated `view_ioc` user to **`manage_ioc`**,
  because an FP now removes the indicator from feeds.
- `PATCH /api/iocs/{id}/marking`, body `{tlp?, pap?}`, `manage_ioc`, audit-logged; unknown values
  → 422.
- `GET /api/iocs` (list and detail) gain `state`, `valid_from`, `valid_until`, `revoked_at`,
  `revoked_by`, `tlp`, `pap`, and a `state=` filter. `include_suppressed` keeps working.
- Regenerate `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts`.

Effects on existing readers:

- **Revoked** is treated like `auto_suppressed` since P2: excluded from STIX export, stats,
  dashboard counts, campaigns, recap counts and the provider-enrichment queue. It stays visible
  (dimmed) in the IOC list so it can be restored, and FP analytics keeps counting it (a revoked
  indicator is an FP; removing it would erase the FP data).
- **Expired** stays in historical statistics (it was real when seen).
- **STIX export** (`services/stix.py`, a snapshot download): indicators carry `valid_from`,
  `valid_until` and `object_marking_refs` to the standard TLP 2.0 marking definitions (official
  OASIS ids). Revoked indicators are left out of the bundle; publishing them with `revoked: true`
  so subscribers delete them belongs to the TAXII collection (P7b).

## 5. Web (IOC page)

- State badge and TLP chip in the table; state filter in the toolbar; revoked rows dimmed.
- FP button tooltip "FP: remove from feeds", TP button "TP / restore".
- IOC detail: `valid_until`, revoked by/at, TLP and PAP selects (Base UI `Select` rules in
  `apps/web/CLAUDE.md`). Tested in light and dark mode. No `backdrop-blur`.

## 6. Testing

- **Unit**: validity per type, `NULL` for hashes, `max` extension; state precedence; most-restrictive
  marking; TTL fingerprint; `ScraperMeta.tlp`/`pap` default (contract test).
- **Integration** (testcontainers): migration up/down on seeded data (ids, FKs, child rows, index and
  constraint names); compatibility views readable (section 7); `test_migrations_match_models`;
  upsert extends `valid_until` and keeps a revocation; reconcile idempotent and re-runs after a TTL
  change; FP revokes, TP restores, 403 without `manage_ioc`; marking PATCH validation; `state`
  filter; STIX fields and markings; revoked excluded from stats and campaigns; `pg_backup` key
  tables.
- **Snapshots**: IOC router (syrupy) updated.
- **Web**: lint, `next typegen` + `tsc --noEmit`, build.

## 7. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | SQL outside the app that names `iocs` breaks after the rename: hand-run checks, read-only prod check patterns, external dashboards. Concretely, the consolidated runbook runs `SELECT ... FROM iocs` checks after the 0.8.6 step, and prod jumps from 0.8.2 to 0.8.11 in one deploy. | (a) The migration creates **compatibility views** `iocs`, `ioc_sources`, `ioc_tags`, `ioc_threat_actors`, `ioc_feedback` over the new tables (`indicator_id AS ioc_id`), so old read queries keep working. They are read-only by convention, documented as deprecated, and dropped in a later release named in the runbook. (b) The consolidated runbook's post-deploy queries are rewritten to `indicators`/`indicator_sources`; queries run **before** deploy (on 0.8.2) keep `iocs`. (c) A repo-wide grep for the old table names (`tools/`, `docker/`, `Makefile`, `docs/`) is a plan step, with each hit fixed or justified. (d) If Alembic autogenerate reflects views, they are excluded in `include_object` so the drift test stays meaningful. |
| R2 | `tools/ops/pg_backup.py` verifies backups against `KEY_TABLES = (..., "iocs", ...)` and silently skips tables that do not exist, so IOC verification would vanish without an error. | `KEY_TABLES` gets `indicators` next to `iocs` (backups run on both sides of the migration; the missing one is skipped). A unit test asserts `indicators` is in the list. |
| R3 | The rename diff is large and conflicts with other branches touching IOC code. Unmerged today: `feat/ioc-enrichment-abuseipdb` (2 commits) and `feat/ioc-enrichment-virustotal-otx` (3 commits), both 13 days old, touching `repositories/ioc.py` and `services/ioc_*`; `claude/react-retheme-ui-ux-pro-max-00bc1b` (1 commit, web IOC components). | Start only after PR #79 merges, rebase at once. The rename is the **first commit, purely mechanical** (no behaviour change, full suite green), so any rebase conflict is a name substitution. Before starting, ask the user whether the three branches are dead or still to land; if they land first, rebase onto them. The web branch is unaffected by the Python rename (`/api/iocs` unchanged) and conflicts at most textually in `ioc-table.tsx`. |
| R4 | Between the migration and the first reconcile run, `valid_until` is `NULL` and non-hash indicators read as non-expiring. | The reconcile task is enqueued on API start, minutes after `migrate`. No feed exists before P7b. The runbook's after-deploy step checks that `job_state` holds the fingerprint and the state distribution. |
| R5 | The feedback endpoint now needs `manage_ioc`; a user with only `view_ioc` loses the TP/FP buttons. | The built-in `analyst` role is granted `manage_ioc` (user decision 2026-10-29), which also lets analysts delete IOCs and edit the allowlist, tags and threat-actor links; only custom roles without it lose the buttons. The web hides the buttons via `useCan("manage_ioc")`; the release notes say so. |
| R6 | Downgrade: the compatibility views occupy the old table names. | Downgrade drops the views first, then reverses the renames and drops the new columns; covered by the migration up/down test. |

## 8. Release

- Version **0.8.11** in every `pyproject.toml`, `__version__`, `apps/web/package.json`, `uv.lock`,
  `docs/openapi.json`, health snapshot; `CHANGELOG.md` entry (Indonesian).
- `docs/prod-upgrade/0.8.11.md` with the standard headings (What changes in prod, Migrations,
  Settings / .env, Before deploy, After deploy, One-off commands, Rollback / if it goes wrong, Known
  risks and follow-ups). After deploy: state distribution query, `job_state` fingerprint, IOC page
  smoke check, a compatibility-view query.
- Consolidated runbook extended to `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md` (header, order of
  operations, migration-chain table, R1(b) query rewrite) and the link in `docs/CI_CD.md`.
- `docs/LLM_ASSIST_REDESIGN.md` and `docs/TARGET_ARCHITECTURE.md` progress updated (P7 split, P7a
  state, section 4 item 4 partly delivered).
- Tested on dev through `origin/Dev` before the PR to `main`.

## 9. Out of scope

- Machine API: tokens, `/api/v2/indicators`, TAXII 2.1 (P7b).
- Sightings (P7d, deferred).
- TLP/PAP on articles, stories, entities, relationships.
- Renaming `ioc_allowlist_entries`, the `/api/iocs` routes or the `cti_core/ioc/` modules.
- Recalibrating the confidence half-lives in `services/confidence.py`.
- Dropping the compatibility views (a later release).
