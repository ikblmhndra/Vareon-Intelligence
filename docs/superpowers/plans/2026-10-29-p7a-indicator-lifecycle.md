# P7a Indicator Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `iocs` to `indicators`, give every indicator a computed lifecycle state (`valid_until` by type, analyst revoke) and TLP/PAP markings, and surface them in the API, the IOC page and the STIX export (release 0.8.11).

**Architecture:** One hand-written Alembic migration renames the five IOC tables in place, leaves compatibility views under the old names, and adds six columns. `state` is a hybrid property (never stored). `valid_until` is filled at ingest by a pure validity module and backfilled/re-synced by an idempotent `indicator.reconcile_validity` task keyed on a TTL fingerprint in `job_state`. Markings default per scraper (`ScraperMeta.tlp/pap`) and travel the same path as `content_kind`.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (sync + async), Alembic, FastAPI, Celery, pydantic-settings, pytest + testcontainers + syrupy, Next.js 16 (Base UI shadcn).

**Spec:** `docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md`

## Global Constraints

- Starts only after P6 (PR #79, 0.8.10) is merged to `main`; rebase this branch on `main` first. Latest migration head after P6: `d7a3e1b94c52`.
- Release version **0.8.11**; prod upgrades from 0.8.2.
- TTL defaults: `ip` 30 d; `domain`, `url`, `url_with_path`, `email` 90 d; `md5`, `sha1`, `sha256` no expiry (`valid_until = NULL`).
- TLP values (TLP 2.0): `clear`, `green`, `amber`, `amber+strict`, `red`. PAP values: `clear`, `green`, `amber`, `red`. Default `clear` for both.
- State precedence: `revoked` > `allowlisted` > `expired` > `active`.
- `/api/iocs` routes and `cti_core/ioc/*`, `services/ioc_*` module names do not change; `ioc_allowlist_entries` is not renamed.
- Code comments and docstrings in Indonesian; docs in English; `CHANGELOG.md` and `docs/PROGRESS.md` in Indonesian; commit messages English conventional ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Every new `Settings` field goes into `.env.example` and `.env.prod.template` in the same commit.
- Ruff line length 100; mypy strict on `cti-core` and `cti-scraper`.
- Web: Base UI shadcn (`render=`, `SelectItem` children a single string), no `backdrop-blur`, test light and dark.
- No write on dev, no push, no merge to `origin/Dev`, no PR without the user's explicit approval.

## Review Focus

1. **Expired indicator seen again** in a new article must become `active` (new `valid_until = now + TTL`), and a **revoked** one seen again must stay `revoked` while its new source is still recorded. → Task 3 tests `test_upsert_reactivates_expired`, `test_upsert_keeps_revocation`.
2. **`state=allowlisted` filter** must return suppressed rows even though `include_suppressed` defaults to false. → Task 5 test `test_list_state_allowlisted_ignores_include_suppressed`.
3. **TTL changed in `.env`** must re-sync existing rows once, skip revoked rows, and be a no-op on the next run. → Task 4 tests.
4. **Downgrade after upgrade** must succeed although views now occupy the old table names, and give back identical ids/child rows. → Task 1 test `test_downgrade_restores_iocs`.
5. **A pre-reconcile row** (`valid_until IS NULL`, non-hash type) seen again must get `now + TTL`, not stay `NULL`. → Task 2 test `test_extend_from_null_non_hash`.

---

### Task 0: Preflight (no code)

- [ ] **Step 1:** `git fetch origin && git log -1 origin/main` shows the P6 merge (0.8.10). If not, stop and report.
- [ ] **Step 2:** `git rebase origin/main` on this branch; `uv sync --extra dev --locked`; `uv run pytest tests/unit tests/contract packages -q` green (deselect the two known local failures recorded in memory).
- [ ] **Step 3:** Ask the user (one message) whether `feat/ioc-enrichment-abuseipdb`, `feat/ioc-enrichment-virustotal-otx` and `claude/react-retheme-ui-ux-pro-max-00bc1b` are dead or still to land. If any is to land first, wait and rebase onto it.
- [ ] **Step 4:** Record the baseline of old table names outside application code: `grep -rnwE "iocs|ioc_sources|ioc_tags|ioc_threat_actors|ioc_feedback" tools docker Makefile docs alembic | grep -v "api/iocs"`, saved to the scratchpad; Task 8 works this list off.

### Task 1: Mechanical rename + compatibility views

Purely mechanical: no behaviour change. Full fast suite and integration suite green at the end.

**Files:**
- Move: `packages/cti-core/src/cti_core/db/models/ioc.py` → `packages/cti-core/src/cti_core/db/models/indicator.py`
- Move: `packages/cti-core/src/cti_core/db/repositories/ioc.py` → `packages/cti-core/src/cti_core/db/repositories/indicator.py`
- Modify: `packages/cti-core/src/cti_core/db/models/__init__.py` and every importer (the ~25 production files of spec 2.4: `grep -rlE '\b(IOC|IOCSource|IOCTag|IOCThreatActor|IOCFeedback|AsyncIOCRepo|IOCRepo)\b' packages apps scrapers tools --include='*.py'`) and the 31 test files
- Create: `alembic/versions/<rev>_iocs_to_indicators.py` (`down_revision = "d7a3e1b94c52"`)
- Modify: `tools/ops/pg_backup.py` (`KEY_TABLES`)
- Test: `tests/integration/test_indicators_migration.py`, `tests/unit/test_pg_backup.py`

**Interfaces:**
- Produces: classes `Indicator`, `IndicatorSource`, `IndicatorTag`, `IndicatorThreatActor`, `IndicatorFeedback` (`__tablename__` `indicators`, `indicator_sources`, `indicator_tags`, `indicator_threat_actors`, `indicator_feedback`; FK column `indicator_id`; constraint names `uq_indicators_type_value`, `uq_indicator_tag`, `uq_indicator_threat_actor`); repos `IndicatorRepo`, `AsyncIndicatorRepo` with the same methods and signatures as before (parameter `ioc` → `indicator`, `ioc_id`/`ioc_ids` → `indicator_id`/`indicator_ids`). Relationship attribute names (`sources`, `tags`, `threat_actors`, `feedback`) unchanged.

- [ ] **Step 1: Write the failing migration test** `tests/integration/test_indicators_migration.py`, following the load-the-module pattern of `tests/integration/test_canonical_ioc_migration.py`:
  - `test_upgrade_keeps_rows_and_ids`: seed 2 `iocs` rows with one child row in each of the four child tables at `d7a3e1b94c52`; upgrade; `indicators` has the same ids/values, each child table has its row with `indicator_id` equal to the old `ioc_id`, and `iocs` is a view (`pg_class.relkind = 'v'`).
  - `test_compat_views_readable`: after upgrade, `SELECT ioc_id FROM ioc_sources` and `SELECT count(*) FROM iocs` return the seeded data.
  - `test_insert_after_rename_uses_sequence`: insert into `indicators` without id → id = max(seeded id) + 1.
  - `test_downgrade_restores_iocs`: upgrade then downgrade; `iocs` is a table again (`relkind = 'r'`), ids and child rows identical, no `indicators` relation left.
- [ ] **Step 2:** `uv run pytest tests/integration/test_indicators_migration.py -q` → FAIL (migration missing).
- [ ] **Step 3: Write the migration.** `upgrade()`: `op.rename_table` for the five tables; `op.alter_column(..., new_column_name="indicator_id")` on the four child tables; rename the five sequences (`iocs_id_seq` → `indicators_id_seq`, ...); rename PKs, FKs, unique constraints and indexes to the names the new models produce (get the exact names from `\d` on a scratch DB built with `Base.metadata.create_all` of the new models); then `CREATE VIEW iocs AS SELECT * FROM indicators` and per child `CREATE VIEW ioc_<x> AS SELECT id, indicator_id AS ioc_id, <remaining columns> FROM indicator_<x>`, each with `COMMENT ON VIEW ... IS 'deprecated since 0.8.11: read-only compatibility view, use indicator_*'`. `downgrade()`: drop the five views first, then reverse every rename. No new columns yet (Task 2).
- [ ] **Step 4: Rename the Python code.** `git mv` the two files; rename classes, repos, `ForeignKey("indicators.id")`, constraint names, imports and test references. Local variables named `ioc` in otherwise untouched functions stay (surgical).
- [ ] **Step 5:** `tools/ops/pg_backup.py`: `KEY_TABLES = ("articles", "iocs", "indicators", "scraper_runs", "scraper_seen", "users", "monitored_accounts")` plus a one-line comment on why both names. Add `test_key_tables_include_indicators` to `tests/unit/test_pg_backup.py` asserting `"indicators" in pb.KEY_TABLES`.
- [ ] **Step 6:** `uv run pytest tests/integration/test_indicators_migration.py tests/integration/test_migrations_match_models.py -q` → PASS. If the drift test reports the views, add an `include_object` filter (in `alembic/env.py` and the test's `MigrationContext` options) that skips the five view names, and say so in the commit message.
- [ ] **Step 7:** `uv run ruff check . && uv run ruff format --check . && uv run mypy packages/cti-core/src packages/cti-scraper/src && uv run pytest tests/unit tests/contract packages -q`, then `uv run pytest tests/integration -q` in the background (~7 min) → all green.
- [ ] **Step 8: Commit** `refactor(core): rename iocs tables and models to indicators`.

### Task 2: Lifecycle columns, state, validity and marking modules

**Files:**
- Create: `packages/cti-core/src/cti_core/indicator/__init__.py`, `packages/cti-core/src/cti_core/indicator/validity.py`, `packages/cti-core/src/cti_core/indicator/marking.py`
- Modify: `packages/cti-core/src/cti_core/config.py`, `.env.example`, `.env.prod.template`
- Modify: `packages/cti-core/src/cti_core/db/models/indicator.py`, the Task 1 migration file
- Test: `tests/unit/test_indicator_validity.py`, `tests/unit/test_indicator_marking.py`, `tests/unit/test_config.py`, `tests/integration/test_indicator_state.py`, `tests/integration/test_indicators_migration.py`

**Interfaces:**
- Produces:
  - `cti_core.indicator.marking`: `Tlp = Literal["clear","green","amber","amber+strict","red"]`, `Pap = Literal["clear","green","amber","red"]`, `TLP_LEVELS: tuple[Tlp, ...]` and `PAP_LEVELS: tuple[Pap, ...]` ordered least to most restrictive, `stricter_tlp(a: str, b: str) -> Tlp`, `stricter_pap(a: str, b: str) -> Pap` (unknown value → `ValueError`).
  - `cti_core.config.IndicatorSettings` (`ttl_ip_days: int = 30`, `ttl_domain_days: int = 90`, `ttl_url_days: int = 90`, `ttl_email_days: int = 90`, each `Field(ge=1)`); `Settings.indicator: IndicatorSettings = Field(default_factory=IndicatorSettings)`.
  - `cti_core.indicator.validity`: `HASH_TYPES = frozenset({"md5", "sha1", "sha256"})`; `ttl_days(ioc_type: str, cfg: IndicatorSettings) -> int | None` (`url_with_path` uses the URL TTL; unknown type → `ValueError`); `extend(current: datetime | None, ioc_type: str, now: datetime, cfg: IndicatorSettings) -> datetime | None`; `ttl_fingerprint(cfg: IndicatorSettings) -> str`.
  - `Indicator` columns `valid_from`, `valid_until`, `revoked_at`, `revoked_by`, `tlp`, `pap`; hybrid properties `Indicator.state` (Python `str`; SQL `case(...)` against `func.now()`) and `Indicator.usable` (Python `bool`; SQL `and_(auto_suppressed.is_(False), revoked_at.is_(None))`).

- [ ] **Step 1: Write failing unit tests.**
  - `test_indicator_validity.py`:
    - `ttl_days("ip", cfg) == 30`; `ttl_days("url_with_path", cfg) == 90`; `ttl_days("sha256", cfg) is None`; `ttl_days("cve", cfg)` raises `ValueError`.
    - `extend(None, "sha1", now, cfg) is None`.
    - `test_extend_from_null_non_hash`: `extend(None, "ip", now, cfg) == now + 30 d`.
    - `extend(now + 80 d, "domain", now, cfg) == now + 90 d`; `extend(now + 200 d, "domain", now, cfg) == now + 200 d` (never shortens).
    - `ttl_fingerprint` equal for equal settings, different with `ttl_ip_days=31`.
  - `test_indicator_marking.py`: `stricter_tlp("clear", "amber") == "amber"`; `stricter_tlp("red", "green") == "red"`; `stricter_tlp("amber", "amber+strict") == "amber+strict"`; `stricter_pap("green", "clear") == "green"`; `stricter_tlp("purple", "clear")` raises `ValueError`.
  - `tests/unit/test_config.py::test_indicator_ttl_defaults`: default settings give `indicator.ttl_ip_days == 30` and `ttl_domain_days == 90`.
- [ ] **Step 2:** Run them → FAIL (modules missing).
- [ ] **Step 3: Implement** `marking.py`, `validity.py` (fingerprint = `json.dumps(cfg.model_dump(), sort_keys=True)`), `IndicatorSettings` with an Indonesian docstring in the style of `StorySettings` (all defaults, no required `.env` key), and the commented block in both `.env.example` and `.env.prod.template`:
  ```
  # INDICATOR__TTL_IP_DAYS=30
  # INDICATOR__TTL_DOMAIN_DAYS=90
  # INDICATOR__TTL_URL_DAYS=90
  # INDICATOR__TTL_EMAIL_DAYS=90
  ```
- [ ] **Step 4:** Unit tests plus `tests/unit/test_config.py tests/unit/test_env_prod_template.py` → PASS.
- [ ] **Step 5: Write failing integration tests.**
  - `test_indicators_migration.py::test_new_columns_backfill`: after upgrade, `valid_from == first_seen_at`, `valid_until IS NULL`, `tlp == 'clear'`, `pap == 'clear'`; inserting `tlp = 'purple'` raises `IntegrityError`; downgrade still passes.
  - `test_indicator_state.py`: one row per case, asserting both the Python `state` and `select(Indicator.state)`: revoked + suppressed → `revoked`; suppressed → `allowlisted`; `valid_until` yesterday → `expired`; `valid_until` NULL → `active`; `valid_until` tomorrow → `active`. `select(Indicator).where(Indicator.usable)` excludes the revoked and suppressed rows.
- [ ] **Step 6: Implement** the columns on the model (types and CHECKs from spec 2.2; CHECK names `ck_indicators_tlp`, `ck_indicators_pap`; index `ix_indicators_valid_until`) and in the migration `upgrade()` (`UPDATE indicators SET valid_from = first_seen_at` before `SET NOT NULL`), reversed in `downgrade()` before the renames. Create the `iocs` view after the columns exist so `SELECT *` includes them. Hybrid properties as in Interfaces.
- [ ] **Step 7:** Step 5 tests and `test_migrations_match_models.py` → PASS.
- [ ] **Step 8: Commit** `feat(core): indicator validity, state and TLP/PAP columns`.

### Task 3: Ingest rules and per-scraper markings

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/indicator.py` (`IndicatorRepo.upsert`, `AsyncIndicatorRepo.upsert`)
- Modify: `packages/cti-scraper/src/cti_scraper/base.py` (`ScraperMeta.tlp`, `ScraperMeta.pap`)
- Modify: `apps/worker/src/cti_worker/tasks/enrich.py` (`_relevance_for` and its caller), `packages/cti-enrich/src/cti_enrich/pipeline.py` (`run_pipeline`, both `persist(...)` calls), `packages/cti-enrich/src/cti_enrich/stages/persist.py` (`persist`)
- Test: `tests/integration/test_indicator_upsert.py`, `tests/unit/test_enrich_markings.py`, `tests/contract/test_scraper_content_kind.py`

**Interfaces:**
- Consumes: `validity.extend`, `marking.stricter_tlp`, `marking.stricter_pap`, `get_settings().indicator` (Task 2).
- Produces: `upsert(..., tlp: str = "clear", pap: str = "clear") -> Indicator` on both repos; `ScraperMeta.tlp: Tlp = "clear"`, `ScraperMeta.pap: Pap = "clear"`; `_relevance_for(scraper_id) -> tuple[str | None, str, str, str]` = `(content_kind, default_relevance, tlp, pap)`, `(None, "classify", "clear", "clear")` for an empty or unknown id; `run_pipeline(..., tlp: str = "clear", pap: str = "clear")`; `persist(..., tlp: str = "clear", pap: str = "clear")`.

- [ ] **Step 1: Write failing tests.**
  - `tests/integration/test_indicator_upsert.py` (sync repo unless stated):
    - `test_new_ip_gets_ttl`: `valid_from ≈ now`, `valid_until ≈ now + 30 d`.
    - `test_new_hash_never_expires`: `valid_until is None`.
    - `test_upsert_reactivates_expired`: row with `valid_until` 10 days ago → `state == "active"`, `valid_until ≈ now + TTL`, `valid_from` unchanged.
    - `test_upsert_keeps_revocation`: revoked row → `revoked_at` unchanged, `state == "revoked"`, one more `IndicatorSource` row.
    - `test_marking_only_goes_up`: `amber` upserted with `clear` stays `amber`; `clear` upserted with `green` becomes `green`; same for `pap`.
    - `test_async_upsert_same_rules`: the expired + marking case through `AsyncIndicatorRepo`.
  - `tests/unit/test_enrich_markings.py`: `_relevance_for(None) == (None, "classify", "clear", "clear")`; a registered scraper id ends with `("clear", "clear")`; a monkeypatched registry entry with `tlp="amber"` returns `"amber"`.
  - `tests/contract/test_scraper_content_kind.py::test_scraper_markings_default_clear`: every real scraper has `meta.tlp == "clear"` and `meta.pap == "clear"` (documents today's state; a non-public source changes this test on purpose).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement** spec 3.2 in both `upsert`s through one private helper in the repo module shared by both classes; the two `ScraperMeta` fields with Indonesian docstrings like `content_kind`; and the threading `_relevance_for` → `run_pipeline` → both `persist(...)` calls → `IndicatorRepo.upsert`. Update `_relevance_for`'s docstring.
- [ ] **Step 4:** New tests plus `uv run pytest tests/unit/test_pipeline_story.py tests/integration/test_pipeline_tier1_db.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(enrich): indicator validity and source markings at ingest`.

### Task 4: Reconcile task, beat entry and startup enqueue

**Files:**
- Create: `apps/worker/src/cti_worker/tasks/indicator.py`
- Modify: `packages/cti-core/src/cti_core/db/repositories/indicator.py` (`IndicatorRepo.reconcile_validity`)
- Modify: `apps/worker/src/cti_worker/beat.py`, `packages/cti-core/src/cti_core/celery_client.py`, `apps/api/src/cti_api/main.py` (`lifespan`), the module that imports worker task modules (where `tasks/confidence.py` is registered)
- Test: `tests/integration/test_indicator_reconcile.py`, `tests/unit/test_beat_schedule.py`

**Interfaces:**
- Consumes: `validity.ttl_days`, `validity.HASH_TYPES`, `validity.ttl_fingerprint`; `JobState` (table `job_state`, key `indicator.ttl_fingerprint`).
- Produces: `IndicatorRepo.reconcile_validity(cfg: IndicatorSettings) -> dict[str, int]` returning `{"updated": n, "skipped": 0 | 1}`; Celery task `indicator.reconcile_validity` on `QUEUE_MAINTENANCE`; beat key `"indicator-reconcile-validity"` at `crontab(hour=4, minute=15)`; `celery_client.send_reconcile_validity() -> None`.

- [ ] **Step 1: Write failing tests.**
  - `tests/integration/test_indicator_reconcile.py`:
    - `test_first_run_fills_valid_until`: ip/domain/sha256 rows with `valid_until NULL` → ip `last_seen_at + 30 d`, domain `+ 90 d`, sha256 stays NULL; fingerprint stored.
    - `test_second_run_noop`: second call returns `{"updated": 0, "skipped": 1}`.
    - `test_ttl_change_resyncs`: `ttl_ip_days=7` → ip rows `last_seen_at + 7 d`; stored fingerprint changes.
    - `test_revoked_rows_untouched`: a revoked ip row keeps its `valid_until`.
  - `tests/unit/test_beat_schedule.py::test_reconcile_validity_scheduled`: entry present with the task name and queue above.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement** the repo method (per TTL group one `UPDATE indicators SET valid_until = last_seen_at + make_interval(days => :d) WHERE type = ANY(:types) AND revoked_at IS NULL`, plus `SET valid_until = NULL` for hash types, then upsert the `job_state` row), the task (sync session; structlog event `indicator_validity_reconciled` with `updated` and the TTLs), the beat entry, `send_reconcile_validity()` (`send_task("indicator.reconcile_validity", queue="maintenance")`), and in `lifespan` an unconditional enqueue after the P6 recompute block, wrapped like `send_recompute_all` with `log.error("reconcile_validity_enqueue_failed", remedy="send task indicator.reconcile_validity manually", exc_info=True)`.
- [ ] **Step 4:** Tests above and `uv run pytest tests/integration/test_bootstrap_recompute.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(worker): reconcile indicator validity from TTL settings`.

### Task 5: Revoke/restore, marking endpoint, state in the API

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/indicator.py` (`add_feedback` in both repos, `list_filtered`, new `AsyncIndicatorRepo.set_marking`)
- Modify: `apps/api/src/cti_api/routers/iocs.py` (feedback permission, `MarkingBody`, `PATCH /{ioc_id}/marking`, serializers, `state` query param)
- Modify (regenerated): `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`
- Test: `tests/integration/test_ioc_lifecycle_api.py`; the existing IOC router snapshot (update with `--snapshot-update`)

**Interfaces:**
- Consumes: `Indicator.state`, `Tlp`, `Pap` (Task 2).
- Produces: `add_feedback(indicator, *, verdict, submitted_by, note=None) -> Indicator` also sets/clears `revoked_at`/`revoked_by`; `AsyncIndicatorRepo.set_marking(indicator: Indicator, *, tlp: str | None, pap: str | None) -> Indicator`; `list_filtered(..., state: str | None = None, include_revoked: bool = True)`; serializer keys `state`, `valid_from`, `valid_until`, `revoked_at`, `revoked_by`, `tlp`, `pap` (ISO strings or `null`).

- [ ] **Step 1: Write failing tests** `tests/integration/test_ioc_lifecycle_api.py` (client fixtures as in the existing IOC router tests):
  - `test_fp_revokes`: feedback `fp` → `state == "revoked"`, `revoked_by` = the username; a second `fp` keeps the first `revoked_at`.
  - `test_tp_restores`: `tp` on a revoked row → `state == "active"`, `revoked_at is None`, `tp_count == 1`.
  - `test_feedback_requires_manage_ioc`: role with `view_ioc` but not `manage_ioc` → 403.
  - `test_patch_marking`: `{"tlp": "amber"}` → 200, `tlp == "amber"`, `pap` unchanged, audit row `action == "ioc_marking"`; `{"tlp": "purple"}` → 422; without `manage_ioc` → 403.
  - `test_list_state_filter`: active/expired/revoked rows; `?state=expired` returns only the expired one; the default list includes the revoked row.
  - `test_list_state_allowlisted_ignores_include_suppressed`: `?state=allowlisted` returns suppressed rows.
  - `test_detail_has_lifecycle_fields`: all seven keys present.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** Feedback endpoint dependency → `require_permission("manage_ioc")`. `MarkingBody(BaseModel)` next to `FeedbackBody`: `tlp: Tlp | None = None`, `pap: Pap | None = None`. `PATCH /{ioc_id}/marking`: `require_permission("manage_ioc")`, 404 when missing, `AsyncAuditLogRepo.write(action="ioc_marking", target_id=str(ioc_id), detail={"tlp": ..., "pap": ...})`, returns `_serialize_detail`. `list_filtered`: with `state` given, filter `Indicator.state == state` and skip the `include_suppressed` clause; `include_revoked=False` adds `revoked_at IS NULL`. `GET /api/iocs` gains `state: Literal["active", "expired", "revoked", "allowlisted"] | None = None`.
- [ ] **Step 4:** New tests; IOC router snapshot updated and its diff reviewed; `uv run pytest tests/unit/test_route_permissions.py -q` → PASS.
- [ ] **Step 5:** `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api` (node via fnm, see memory); the diff holds only the new route, query param and permission.
- [ ] **Step 6: Commit** `feat(api): revoke, restore and marking for indicators`.

### Task 6: Readers exclude revoked; STIX validity and TLP markings

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/indicator.py` (`list_first_seen_on`, `count_first_seen_by_type_between`, `list_needing_enrichment`, `list_by_article_ids`, `get_stats`), `packages/cti-core/src/cti_core/db/repositories/dashboard.py` (the two `auto_suppressed.is_(False)` filters near lines 846 and 862)
- Modify: `apps/api/src/cti_api/services/stix.py` (`_build_indicator`, `build_ioc_stix_bundle`, the article bundle's indicator path, `_make_bundle`)
- Test: `tests/integration/test_indicator_readers.py`; existing STIX tests (`grep -rl build_ioc_stix_bundle tests`)

**Interfaces:**
- Consumes: `Indicator.usable`, `list_filtered(include_revoked=False)`, `Tlp`.
- Produces: `_build_indicator(..., valid_until: str | None = None, tlp: str = "clear")`; module constant `TLP_MARKING_IDS: dict[str, str]`.

- [ ] **Step 1: Write failing tests** `tests/integration/test_indicator_readers.py` with one active, one revoked and one suppressed indicator on the same article:
  - `test_stats_exclude_revoked` (`get_stats` counts only the active one);
  - `test_campaign_rows_exclude_revoked` (`list_by_article_ids`);
  - `test_recap_first_seen_excludes_revoked` (`list_first_seen_on`, `count_first_seen_by_type_between`);
  - `test_enrichment_queue_excludes_revoked` (`list_needing_enrichment`);
  - `test_fp_analytics_keeps_revoked` (`list_with_feedback` still returns the revoked FP row);
  - `test_stix_ioc_bundle`: no indicator for the revoked value; the active one has `valid_until` (RFC 3339 with `Z`) and `object_marking_refs == [TLP_MARKING_IDS["clear"]]`; the bundle holds that `marking-definition` object once; a hash indicator has no `valid_until` key.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** Replace `auto_suppressed.is_(False)` with `Indicator.usable` in exactly the listed methods (`list_filtered` keeps the Task 5 logic; `list_with_feedback` unchanged). STIX: `TLP_MARKING_IDS` maps the five TLP values to the official TLP 2.0 marking-definition ids; **verify every id against the OASIS STIX 2.1 TLP 2.0 marking definitions before committing**. Candidates:

  | TLP | Marking-definition id |
  |---|---|
  | `clear` | `marking-definition--94868c89-83c2-464b-929b-a1a8aa3c8487` |
  | `green` | `marking-definition--bab4a63c-aed9-4cf5-a766-dfca5abac2bb` |
  | `amber` | `marking-definition--55d920b0-5e8b-4f79-9ee9-91f868d9b421` |
  | `amber+strict` | `marking-definition--939a9414-2ddd-4d32-a0cd-375ea402b003` |
  | `red` | `marking-definition--e828b379-4e03-4974-9ac4-e53a884c97c1` |

  `_make_bundle` appends the standard marking-definition object once per referenced id. `build_ioc_stix_bundle` passes `include_revoked=False`, `valid_until` and `tlp`.
- [ ] **Step 4:** New tests, existing STIX tests and `uv run pytest tests/integration -k "stix or dashboard or recap or campaign" -q` → PASS; update STIX snapshots if any, reviewing the diff.
- [ ] **Step 5: Commit** `feat(api): keep revoked indicators out of readers and add STIX markings`.

### Task 7: Web IOC page

**Files:**
- Modify: `apps/web/src/lib/api/loose-types.ts` (IOC type gains `state`, `valid_from`, `valid_until`, `revoked_at`, `revoked_by`, `tlp`, `pap`)
- Modify: `apps/web/src/components/intelligence/ioc/ioc-table.tsx`, `apps/web/src/components/intelligence/ioc/ioc-detail-dialog.tsx`, and the IOC toolbar/filter component next to them

**Interfaces:**
- Consumes: `GET /api/iocs?state=`, `PATCH /api/iocs/{ioc_id}/marking`, the feedback endpoint (Task 5); `useCan()` from `@/lib/auth/permissions`.

- [ ] **Step 1:** Read `apps/web/AGENTS.md`, `apps/web/CLAUDE.md` and the Base UI `Select` usage already in the `ioc-*` components.
- [ ] **Step 2: Implement:**
  - state badge (active/expired/revoked/allowlisted) and TLP chip columns;
  - state filter in the toolbar wired to `?state=`;
  - revoked rows at reduced opacity;
  - FP/TP buttons only when `can("manage_ioc")`, tooltips "FP: remove from feeds" and "TP / restore";
  - detail dialog shows `valid_until` ("never" for `null`) and "revoked by X at Y", plus TLP and PAP `Select`s (disabled without `manage_ioc`) that call the PATCH and refresh the row.

  UI copy follows the page's existing language.
- [ ] **Step 3:** `cd apps/web && pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build` → all pass.
- [ ] **Step 4:** Run the app locally (`docker compose up -d`, API via uvicorn, `pnpm dev`) and check the IOC page in the in-app browser, light and dark, desktop and 375 px: the state filter works, FP turns the row revoked and dimmed, TP restores it, and a TLP change survives a reload.
- [ ] **Step 5: Commit** `feat(web): indicator state, TLP/PAP and revoke on the IOC page`.

### Task 8: Release 0.8.11 docs and old-name sweep

**Files:**
- Modify: version in the root and every package `pyproject.toml`, each `__version__`, `apps/web/package.json`, `uv.lock`, `docs/openapi.json`, the health snapshot (`tests/integration/__snapshots__/test_health_router_snapshot.ambr`)
- Modify: `CHANGELOG.md`
- Create: `docs/prod-upgrade/0.8.11.md`
- Move + modify: `docs/PROD_UPGRADE_0.8.2_TO_0.8.10.md` → `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`; the link in `docs/CI_CD.md`
- Modify: `docs/LLM_ASSIST_REDESIGN.md`, `docs/TARGET_ARCHITECTURE.md`, `docs/ARCHITECTURE.md` (table names), and every hit of the Task 0 baseline

- [ ] **Step 1:** Work off the Task 0 list: each reference to the old table names becomes `indicator*`, except (a) runbook steps that run **before** the 0.8.11 migration (keep `iocs`, add "(on 0.8.2)") and (b) `pg_backup.py` (both names on purpose). Re-run the grep; every remaining hit is one of those two cases.
- [ ] **Step 2:** `docs/prod-upgrade/0.8.11.md` with exactly the eight headings: What changes in prod, Migrations, Settings / .env, Before deploy, After deploy, One-off commands, Rollback / if it goes wrong, Known risks and follow-ups. After deploy contains:
  - `SELECT CASE WHEN revoked_at IS NOT NULL THEN 'revoked' WHEN auto_suppressed THEN 'allowlisted' WHEN valid_until < now() THEN 'expired' ELSE 'active' END AS state, count(*) FROM indicators GROUP BY 1;`
  - `SELECT value FROM job_state WHERE key = 'indicator.ttl_fingerprint';` (non-empty)
  - `SELECT count(*) FROM iocs;` (compatibility view works and equals `indicators`)
  - an IOC page smoke check.

  Known risks: R1-R6 of the spec, the compatibility views to drop in a later release, and `manage_ioc` now required for TP/FP.
- [ ] **Step 3:** Consolidated runbook: header to 0.8.11; order of operations gains the 0.8.11 step; migration-chain table gains the new revision; verification queries that run after the 0.8.11 migration use `indicators`/`indicator_sources`. Point the `docs/CI_CD.md` link at the new file name.
- [ ] **Step 4:** `CHANGELOG.md` entry in Indonesian with the header format `## [0.8.11] - YYYY-MM-DD` exactly; bump all versions; `uv lock`; regenerate `docs/openapi.json`; update the health snapshot.
- [ ] **Step 5:** `docs/LLM_ASSIST_REDESIGN.md`: a "Built for 0.8.11 (P7a)" progress block with a pointer to the P7 decomposition in the spec; section 4 item 4 marked partly delivered (sightings deferred); section 5 row P7 points to the spec. `docs/TARGET_ARCHITECTURE.md` progress table: "indicator state/expiry" of step 2 done in 0.8.11.
- [ ] **Step 6:** Full verification: `uv run ruff check . && uv run ruff format --check . && uv run mypy packages/cti-core/src packages/cti-scraper/src && uv run pytest tests/unit tests/contract packages -q`; `uv run pytest tests/integration -q` (background); web lint/typecheck/build → all green.
- [ ] **Step 7: Commit** `chore(release): 0.8.11`.

### Task 9: Dev rollout (each outward step needs the user's approval)

- [ ] **Step 1:** Ask the user to approve merging this branch into `origin/Dev` and deploying on dev (172.25.1.77).
- [ ] **Step 2:** After deploy, run the read-only After deploy queries of `docs/prod-upgrade/0.8.11.md` on dev and compare the state distribution with the spec baseline (5,281 active / 157 expired / 29 allowlisted / 0 revoked on 2026-10-28, plus IOCs added since). Record results in the shared notes folder.
- [ ] **Step 3:** Report the results; the PR to `main` is opened only on the user's go.
