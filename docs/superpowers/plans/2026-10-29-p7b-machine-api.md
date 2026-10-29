# P7b Machine API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let machines pull indicators with scoped, revocable, TLP-limited API tokens over a REST
feed (`/api/v2/indicators`) and a TAXII 2.1 server (`/taxii2/`), with revocations published as
`revoked: true`.

**Architecture:** Everything native in cti-api (spec approach A). A new `api_tokens` table and a
`require_token(scope)` dependency authenticate machines; a trigger-maintained
`indicators.feed_changed_at` column is the feed clock; one shared query in `services/feed.py`
applies TLP, settle lag and keyset paging for both REST and TAXII; STIX objects are built at read
time by the fixed `_build_indicator`. Admins manage tokens in a new section of the admin page;
nginx exposes only `/taxii2/` and `/api/v2/`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic (hand-written), Postgres 16
triggers, pytest + testcontainers, Next.js 16 + Base UI shadcn, nginx.

**Spec:** `docs/superpowers/specs/2026-10-29-p7b-machine-api-design.md`

## Global Constraints

- Release: part of **0.8.11**; do **not** bump any version. Add to the existing `## [0.8.11]`
  CHANGELOG entry (Indonesian).
- No new `.env` / `Settings` key. `FEED_SETTLE_SECONDS = 60` is a code constant.
- Token format `vrn_` + `secrets.token_urlsafe(32)`; stored as sha256 hex only.
- Scopes: `API_TOKEN_SCOPES = ("indicators:read",)`.
- TLP 2.0 levels from `cti_core.indicator.marking.TLP_LEVELS`; official marking ids from
  `services/stix.py::TLP_MARKING_IDS`.
- TAXII media types exactly `application/taxii+json;version=2.1` and
  `application/stix+json;version=2.1`; all TAXII paths end with `/`.
- REST `limit` default 500, max 5000; TAXII `limit` default 500, max 1000.
- Code comments/docstrings Indonesian; docs English; commit messages English conventional, ending
  with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Local QA only on the isolated compose project
  (`POSTGRES_PORT=55433 REDIS_PORT=56379 docker compose -p qacve up -d postgres redis`), torn down
  with `docker compose -p qacve down -v`. Never the user's `deploy-postgres-1`.
- Known local-only failure, deselect: `tests/contract/test_golden.py::test_golden_trendmicro`.
- Node/pnpm: `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"`.

## Decisions added while planning (deviations from the spec, to confirm at plan review)

1. **`indicators.stix_id` (uuid, nullable, unique index)**. TAXII `match[id]` and object-by-id
   receive `indicator--<uuid5(type:value)>`, which cannot be reversed to a row. The column stores
   the UUID part, computed in Python by the same formula as `services/stix.py::_uuid5`: set on
   insert in `_apply_upsert`, backfilled in the migration (Python loop), and filled for `NULL` rows
   by the daily `reconcile_validity` (rows inserted by rolled-back code). A Postgres generated
   column via `uuid-ossp` was rejected: it needs an extension on prod, and Postgres `lower()` may
   differ from Python's for the 13 non-ASCII/whitespace values on dev. Serialisation computes the
   id in Python when `stix_id` is `NULL`, so ids never differ.
2. **Web: a section, not a page.** `/admin/users` already renders every admin area as a section
   (`UsersSection`, `RolesSection`, ...). The token UI is `ApiTokensSection` on that page, gated by
   `can("manage_api_tokens")`, instead of a new `admin/api-tokens` route.
3. **Errors**: one app-level `HTTPException`/`RequestValidationError` formatter by path prefix:
   `/api/v2/*` → `{error: {code, message, details}}`, `/taxii2/*` → TAXII error object with the
   TAXII content type, everything else unchanged.
4. **`taxii2-client`** as a dev-only dependency for the interop test (Task 6) needs the user's yes;
   if declined, Task 6 step 5 uses the `httpx` fallback named there.

## Review Focus

- A token whose `max_tlp` is `clear` must not see an `amber` indicator through **any** route,
  including object-by-id, versions, manifest and CSV: pinned in Tasks 4, 5 and 6.
- Many rows share one `feed_changed_at` (a test transaction, a bulk reconcile): paging must not
  skip or repeat rows at a page boundary inside a tie; pinned in Task 4 (`test_page_ties`).
- `Basic` with an empty username, a token with whitespace, or a non-`vrn_` string must be 401, not
  500; pinned in Task 2 (`test_malformed_credentials_401`).
- A garbled `cursor` / `next` / `added_after` must be 400, not 500; pinned in Tasks 4, 5 and 6.
- An admin revoking a token while a client is mid-paging: the next request is 401; pinned in Task 2
  (`test_revoked_token_401_immediately`).

---

### Task 0: Baseline

- [ ] **Step 1:** `git fetch origin && git status`: branch `nameless/p7b-machine-api-d65264` on
  `origin/main` (`b717980`) plus the spec and plan commits; clean tree.
- [ ] **Step 2:** `uv sync --extra dev --locked && uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro`
  Expected: all pass. Record the counts in the ledger.
- [ ] **Step 3:** `uv run alembic heads` → `a9e4c7b1d3f6 (head)`.

### Task 1: Schema: `api_tokens`, `feed_changed_at`, `stix_id`, triggers

**Files:**
- Create: `alembic/versions/<rev>_machine_api.py` (down_revision `a9e4c7b1d3f6`)
- Create: `packages/cti-core/src/cti_core/indicator/stix_id.py`
- Modify: `packages/cti-core/src/cti_core/db/models/auth.py` (add `ApiToken`),
  `packages/cti-core/src/cti_core/db/models/indicator.py` (two columns),
  `packages/cti-core/src/cti_core/db/models/__init__.py` (export `ApiToken`),
  `packages/cti-core/src/cti_core/db/repositories/indicator.py` (`_apply_upsert` sets `stix_id`
  for new rows; `reconcile_validity` fills `NULL` `stix_id` in its always-run step)
- Test: `tests/unit/test_stix_id.py`, `tests/integration/test_machine_api_migration.py`

**Interfaces:**
- Produces: `cti_core.indicator.stix_id.indicator_uuid(type: str, value: str) -> uuid.UUID`
  (= `uuid.uuid5(uuid.NAMESPACE_DNS, f"{type}:{value}".lower().strip())`, exactly the formula of
  `services/stix.py::_uuid5`); `ApiToken` (columns of spec 3.1, `scopes` as `ARRAY(Text)`);
  `Indicator.feed_changed_at: Mapped[datetime]` (not null, `server_default=func.now()`);
  `Indicator.stix_id: Mapped[uuid.UUID | None]` (unique); index
  `ix_indicators_feed_changed_at_id` on `(feed_changed_at, id)`.

- [ ] **Step 1: Unit test** `test_indicator_uuid_matches_stix_export`: for `("ip", "1.2.3.4")`,
  `("domain", "Example.COM ")`, `("url", "http://a/b\\c")` assert
  `str(indicator_uuid(t, v)) == stix._uuid5(f"{t}:{v}")`.
- [ ] **Step 2: Integration tests** (pattern of `tests/integration/test_indicators_migration.py`:
  `_load_migration` / `_run` on `db_session`). `now()` is constant inside the test transaction, so
  each bump test first sets `feed_changed_at = '2020-01-01Z'` with a plain UPDATE (no watched
  column changes, so the trigger keeps the assigned value), then changes the field and asserts
  `feed_changed_at = now()`:
  - `test_upgrade_backfills_feed_changed_at_and_stix_id`: downgrade, seed two rows (one with
    `revoked_at` later than `created_at`), upgrade; assert `feed_changed_at =
    greatest(created_at, coalesce(revoked_at, created_at))` and `stix_id = indicator_uuid(...)`.
  - `test_trigger_bumps_on_feed_fields`: parametrised over `revoked_at`, `auto_suppressed`, `tlp`,
    `pap`, `valid_until`, `seen_count`, `last_seen_at`.
  - `test_trigger_ignores_confidence_and_enrichment`: `confidence_score`, `actionability_score`,
    `enrichment`, `updated_at` leave `2020-01-01`.
  - `test_tag_insert_delete_bumps_parent`.
  - `test_reconcile_raw_update_bumps` (`IndicatorRepo.reconcile_validity` after a TTL change).
  - `test_reconcile_fills_null_stix_id`.
  - `test_upsert_sets_stix_id` (sync and async upsert of a new row).
  - `test_insert_through_compat_view_gets_defaults` (INSERT into view `iocs` → `feed_changed_at`
    set, `stix_id` NULL).
  - `test_downgrade_removes_everything` (table, columns, index, functions and triggers gone).
- [ ] **Step 3:** Run both; expected FAIL (module and migration missing).
- [ ] **Step 4: Implement.** Upgrade order: create `api_tokens` (CHECK `max_tlp`, unique
  `token_hash`); add `feed_changed_at` with `server_default now()`, then the backfill UPDATE; add
  `stix_id` uuid, backfill with a Python loop over `SELECT id, type, value` in batches of 1000
  using `indicator_uuid`, then the unique index; create the `(feed_changed_at, id)` index; create
  functions `indicators_feed_bump()` (BEFORE UPDATE, the ten columns of spec 3.2 compared with
  `IS DISTINCT FROM`) and `indicator_tags_feed_bump()` (AFTER INSERT OR DELETE, uses
  `COALESCE(NEW.indicator_id, OLD.indicator_id)`, returns NULL) and their triggers. Downgrade in
  reverse. The `feed_changed_at` docstring names the triggers and this migration (spec R6).
- [ ] **Step 5:** Run the Step 1-2 tests plus `tests/integration/test_migrations_match_models.py`
  and `tests/integration/test_indicators_migration.py`; expected PASS.
- [ ] **Step 6: Commit** `feat(db): add api_tokens, the indicator feed clock and stix_id`.

### Task 2: Token logic and `require_token`

**Files:**
- Modify: `packages/cti-core/src/cti_core/indicator/marking.py` (add `tlp_allowed`),
  `packages/cti-core/src/cti_core/db/repositories/auth.py` (add `AsyncApiTokenRepo`)
- Create: `apps/api/src/cti_api/machine_auth.py`
- Test: `tests/unit/test_machine_auth.py`, `tests/integration/test_machine_auth.py`

**Interfaces:**
- Consumes: `ApiToken` (Task 1).
- Produces:
  - `tlp_allowed(max_tlp: str) -> tuple[Tlp, ...]`: levels up to and including `max_tlp`; unknown
    → `ValueError`.
  - `AsyncApiTokenRepo(session)`: `create(*, name: str, token_prefix: str, token_hash: str,
    scopes: list[str], max_tlp: str, created_by: str, expires_at: datetime | None) -> ApiToken`;
    `list_all() -> list[ApiToken]` (newest first); `get(token_id: int) -> ApiToken | None`;
    `get_by_hash(token_hash: str) -> ApiToken | None`; `revoke(token: ApiToken, *, by: str) ->
    ApiToken` (keeps the first `revoked_at`); `touch_last_used(token_id: int) -> None` (one
    `UPDATE ... SET last_used_at = now() WHERE id = :id AND (last_used_at IS NULL OR last_used_at <
    now() - interval '60 seconds')`).
  - `cti_api.machine_auth`: `API_TOKEN_SCOPES`, `TOKEN_PREFIX = "vrn_"`,
    `generate_token() -> str`, `hash_token(token: str) -> str`,
    `token_status(token: ApiToken, now: datetime) -> Literal["active", "expired", "revoked"]`
    (revoked wins), `@dataclass(frozen=True) MachinePrincipal(token_id: int, name: str,
    scopes: tuple[str, ...], max_tlp: str)`,
    `require_token(scope: str) -> Callable[..., Awaitable[MachinePrincipal]]`, whose result carries
    `.scope = scope` (unknown scope → `ValueError` at import time, like `require_permission`).
  - 401 = `HTTPException(401, "Invalid or missing API token", headers={"WWW-Authenticate":
    'Basic realm="vareon", Bearer'})`; 403 = `HTTPException(403, f"Token lacks scope: {scope}")`.

- [ ] **Step 1: Unit tests:** `test_tlp_allowed` (`clear` → `("clear",)`, `amber` →
  `("clear", "green", "amber")`, `red` → all five, `"x"` raises); `test_generate_token_format`
  (starts with `vrn_`, at least 40 chars, two calls differ); `test_hash_token_is_sha256_hex`;
  `test_token_status_precedence` (revoked and expired → `revoked`; past `expires_at` → `expired`;
  `None` → `active`); `test_require_token_unknown_scope_raises`.
- [ ] **Step 2: Integration tests** (a minimal `FastAPI()` built in the test with one route
  `GET /probe` using `require_token("indicators:read")`, `get_db` overridden to `api_session`):
  `test_bearer_ok`; `test_basic_ok` (username `"splunk"`, password = token);
  `test_basic_empty_username_ok`; `test_unknown_token_401_with_www_authenticate`;
  `test_expired_token_401`; `test_revoked_token_401_immediately` (200 → revoke → 401);
  `test_wrong_scope_403` (row with `scopes=[]` inserted through the repo);
  `test_malformed_credentials_401` (`Bearer`, `Bearer abc`, `Basic !!!`, Basic of `"user"` with no
  colon, `Token vrn_x`, Bearer with a trailing space); `test_last_used_throttled` (two calls → one
  write; set `last_used_at` two minutes back → updated).
- [ ] **Step 3:** Run; expected FAIL.
- [ ] **Step 4: Implement.** Header parsing never raises anything but `HTTPException` (bad base64
  or UTF-8 → 401); one message for unknown/revoked/expired; on success `touch_last_used` and
  `session.commit()`.
- [ ] **Step 5:** Run; expected PASS. `uv run mypy packages/cti-core/src packages/cti-scraper/src`
  clean.
- [ ] **Step 6: Commit** `feat(api): add scoped API tokens and require_token`.

### Task 3: Token administration API and permission

**Files:**
- Modify: `apps/api/src/cti_api/services/roles.py` (`manage_api_tokens`),
  `apps/api/src/cti_api/main.py` (include router), `tests/unit/test_route_permissions.py`
- Create: `apps/api/src/cti_api/routers/api_tokens.py`, `apps/api/src/cti_api/schemas/api_token.py`
- Test: `tests/integration/test_api_tokens_router.py`
- Regenerate: `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`

**Interfaces:**
- Consumes: `AsyncApiTokenRepo`, `generate_token`, `hash_token`, `token_status`,
  `API_TOKEN_SCOPES` (Task 2).
- Produces: `ALL_PERMISSIONS["manage_api_tokens"] = "Create and revoke machine API tokens"` (in the
  Platform administration group). `admin` gets it automatically (its list is `_ALL` minus two) and
  `ensure_system_roles` rewrites system roles at startup; `analyst` does not get it. Schemas:
  `ApiTokenOut{id, name, token_prefix, scopes, max_tlp, created_by, created_at, expires_at,
  last_used_at, revoked_at, revoked_by, status}`; `ApiTokenCreate{name: str (stripped, 1-200),
  max_tlp: Tlp = "clear", expires_in_days: int | None = 365 (1-3650)}`;
  `ApiTokenCreated(ApiTokenOut){token: str}`. Routes under `/api/api-tokens`: `GET ""` →
  `list[ApiTokenOut]`; `POST ""` → 201 `ApiTokenCreated` (scopes always `list(API_TOKEN_SCOPES)`,
  `token_prefix` = first 12 chars); `DELETE "/{token_id}"` → `ApiTokenOut` (404 when unknown).
  Audit actions `api_token_create` (detail `{name, max_tlp, expires_at}`) and `api_token_revoke`.
  The token value is never logged or audited.

- [ ] **Step 1: Tests.** In `test_route_permissions.py`, extend
  `test_analyst_keeps_cve_triage_and_ops_views` with `"manage_api_tokens" not in analyst` and add
  `test_admin_has_manage_api_tokens`. Integration: `test_create_returns_token_once` (POST → 201,
  `token` starts with `vrn_`; the GET list has no `token` or `token_hash` key);
  `test_created_token_hash_matches` (`hash_token(token)` equals the stored hash);
  `test_create_never_expires` (`expires_in_days: null` → `expires_at` null);
  `test_create_validation_422` (`max_tlp: "white"`, `expires_in_days: 0`, `name: "  "`);
  `test_revoke_idempotent_and_audited` (two DELETEs keep the first `revoked_at`; audit rows
  `api_token_create` and `api_token_revoke`; no audit detail contains the token);
  `test_revoke_unknown_404`; `test_analyst_403` (role `analyst` after `ensure_system_roles`).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3: Implement** the router and schemas; register them in `create_app`.
- [ ] **Step 4:** Run the tests, then `uv run python tools/export_openapi.py` and
  `cd apps/web && pnpm run gen:api`; commit both generated files.
- [ ] **Step 5: Commit** `feat(api): add API token administration`.

### Task 4: Feed query, cursor and STIX builder fixes

**Files:**
- Create: `apps/api/src/cti_api/services/feed.py`
- Modify: `apps/api/src/cti_api/services/stix.py` (`_IOC_PATTERN_MAP`, `_ioc_pattern`,
  `_build_indicator`, `build_ioc_stix_bundle`; add `stix_ts`, `indicator_to_stix`)
- Test: `tests/unit/test_feed_cursor.py`, `tests/unit/test_stix_indicator_builder.py`,
  `tests/integration/test_feed_query.py`

**Interfaces:**
- Consumes: `tlp_allowed` (Task 2), `Indicator.feed_changed_at` / `stix_id` and `indicator_uuid`
  (Task 1).
- Produces (`services/feed.py`):
  - `FEED_SETTLE_SECONDS = 60`. The filter is `feed_changed_at <= now() - make_interval(secs =>
    FEED_SETTLE_SECONDS)`, so tests that monkeypatch it to `0` see rows written in their own
    transaction.
  - `encode_cursor(changed_at: datetime, indicator_id: int) -> str`;
    `decode_cursor(cursor: str) -> tuple[datetime, int]` (`ValueError` on anything malformed,
    including a naive datetime).
  - `@dataclass FeedPage(items: list[Indicator], next_cursor: str | None)`.
  - `async def feed_page(session: AsyncSession, *, max_tlp: str, limit: int, states:
    Collection[str] | None = None, types: Collection[str] | None = None, changed_after: datetime |
    None = None, after: tuple[datetime, int] | None = None, stix_ids: Collection[uuid.UUID] | None
    = None) -> FeedPage`: TLP `tlp.in_(tlp_allowed(max_tlp))`, settle lag, filters, keyset
    `tuple_(feed_changed_at, id) > after`, order `feed_changed_at, id`, fetch `limit + 1` to
    decide `next_cursor` (the cursor of the last returned row). `states=None` means all states.
- Produces (`services/stix.py`):
  - `_IOC_PATTERN_MAP["url_with_path"]` = the `url` template; `_ioc_pattern` escapes `\` → `\\`
    first, then `'` → `\'`.
  - `_build_indicator(..., created: str | None = None, modified: str | None = None, revoked: bool
    = False)`: `created`/`modified` default to `ts` (TA bundle unchanged); `revoked=True` adds
    `"revoked": True`.
  - `stix_ts(dt: datetime) -> str`: UTC, millisecond precision, `Z` (e.g.
    `2026-10-29T04:00:25.542Z`).
  - `indicator_to_stix(ind: Indicator) -> dict[str, Any] | None`: id from `ind.stix_id`, else
    `indicator_uuid(...)`; `created = stix_ts(ind.created_at)`, `modified =
    stix_ts(ind.feed_changed_at)`, `valid_from = stix_ts(ind.valid_from)`, `valid_until` (omitted
    when `None`), labels, TLP marking, `x_seen_count`, `x_last_seen` (date), `revoked = ind.state
    in ("revoked", "allowlisted")`; no `confidence`.
  - `build_ioc_stix_bundle` uses `indicator_to_stix`, so the snapshot export gets stable
    `created`/`modified` too; it still excludes revoked and allowlisted rows.

- [ ] **Step 1: Unit tests:** `test_cursor_round_trip`; `test_decode_cursor_rejects` (`""`, `"!!"`,
  base64 of `"x|1"`, of a naive timestamp, of `"2026-10-29T00:00:00+00:00|abc"`);
  `test_url_with_path_pattern`; `test_pattern_escapes_backslash_then_quote` (value `a\'b` →
  `[url:value = 'a\\\'b']`); `test_indicator_to_stix_stable_times` (two calls equal; `created` and
  `modified` come from the row); `test_revoked_and_allowlisted_flagged`; `test_no_confidence_key`;
  `test_hash_has_no_valid_until`; `test_stix_id_fallback_matches_column`.
- [ ] **Step 2: Integration tests** (`async_db_session`; monkeypatch `feed.FEED_SETTLE_SECONDS` to
  0 except where stated): `test_tlp_filter` (clear/green/amber rows: `max_tlp="clear"` → only
  clear, `"amber"` → all three); `test_settle_lag_hides_fresh_rows` (lag 60: fresh rows absent,
  a row whose `feed_changed_at` is set two minutes back present); `test_page_ties` (7 rows with the
  same `feed_changed_at`, `limit=3` → pages of 3/3/1, union = all ids, no repeats, final
  `next_cursor` None); `test_changed_after_strict`; `test_state_and_type_filters`;
  `test_stix_ids_filter`.
- [ ] **Step 3:** Run; expected FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5:** Run the new tests plus `uv run pytest tests -q -k stix`; expected PASS (existing
  STIX export tests still pass, revoked rows still excluded). Update syrupy snapshots only where
  `created`/`modified` legitimately changed (`--snapshot-update`, review the diff).
- [ ] **Step 6: Commit** `feat(api): add the shared feed query and stable STIX indicators`.

### Task 5: REST feed `GET /api/v2/indicators`

**Files:**
- Create: `apps/api/src/cti_api/routers/v2_indicators.py`, `apps/api/src/cti_api/schemas/feed.py`
- Modify: `apps/api/src/cti_api/main.py` (router; prefix-aware formatting of `HTTPException` and
  `RequestValidationError` for `/api/v2` and `/taxii2`), `tests/unit/test_route_permissions.py`
- Test: `tests/integration/test_v2_indicators.py`
- Regenerate: `docs/openapi.json`, `schema.d.ts`

**Interfaces:**
- Consumes: `require_token` (Task 2), `feed_page`, `encode_cursor`, `decode_cursor` (Task 4),
  `indicator_uuid` (Task 1).
- Produces: `IndicatorFeedItem` with the 16 fields of spec 4.3 (`stix_id` as
  `"indicator--<uuid>"`, `tags: list[str]`, `changed_at` = `feed_changed_at`) and `IndicatorFeedPage
  {items, next_cursor}`. Route `GET /api/v2/indicators`: `state: list[str] = Query(["active"])`
  (`any` = no filter; values outside the four states and `any` → 400), `type: list[str] | None`,
  `changed_after: datetime | None` (naive → 400), `cursor: str | None`, `limit: int = Query(500,
  ge=1, le=5000)`, `format: Literal["json", "csv"] | None`. CSV when `format=csv` or `Accept`
  contains `text/csv`: header row = the 16 field names in spec order, `tags` joined by `;`, header
  `X-Next-Cursor` (absent at the end), `Content-Type: text/csv; charset=utf-8`. v2 error shape
  `{"error": {"code": <snake_case HTTP phrase, e.g. "unauthorized">, "message": <detail>,
  "details": <validation errors or null>}}`; the formatter keeps the exception's headers
  (`WWW-Authenticate`).
- Route coverage: `test_every_api_route_requires_a_permission` skips `/api/v2/` paths; new
  `test_every_machine_route_requires_a_token` walks all app routes (not only `/api`) and asserts
  every `/api/v2/*` and `/taxii2/*` route has a dependency with `.scope` and none with
  `.permission`.

- [ ] **Step 1: Integration tests** (token created through `AsyncApiTokenRepo`, settle lag patched
  to 0): `test_default_active_only` (active, expired, revoked and allowlisted rows → only active);
  `test_state_any_includes_revoked`; `test_cursor_paging` (limit 2 over 5 rows);
  `test_tlp_clear_token_never_sees_amber` (JSON and CSV); `test_csv_columns_and_next_cursor`;
  `test_bad_cursor_400_v2_shape`; `test_bad_state_400`; `test_limit_over_max_422_v2_shape`;
  `test_no_token_401_v2_shape` (body `{"error": {"code": "unauthorized", ...}}` and
  `WWW-Authenticate`); `test_jwt_is_not_accepted` (a web `auth_header()` JWT → 401);
  `test_v1_error_shape_unchanged` (`GET /api/iocs/999999` still `{"detail": ...}`).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3: Implement** the router, schemas, formatter and the route-coverage change.
- [ ] **Step 4:** Run the tests and the unit suite; regenerate OpenAPI (security scheme
  `apiToken`, HTTP bearer) and `schema.d.ts`.
- [ ] **Step 5: Commit** `feat(api): add the /api/v2/indicators REST feed`.

### Task 6: TAXII 2.1 server

**Files:**
- Create: `apps/api/src/cti_api/routers/taxii.py`
- Modify: `apps/api/src/cti_api/main.py` (include router); root `pyproject.toml` dev extra and
  `uv.lock` only if the user approves `taxii2-client`
- Test: `tests/unit/test_taxii_params.py`, `tests/integration/test_taxii.py`,
  `tests/integration/test_taxii_interop.py`

**Interfaces:**
- Consumes: `require_token` (Task 2), `feed_page`, `encode_cursor`, `decode_cursor`,
  `indicator_to_stix`, `stix_ts` (Task 4), the prefix error formatter (Task 5).
- Produces: `TAXII_MEDIA = "application/taxii+json;version=2.1"`,
  `STIX_MEDIA = "application/stix+json;version=2.1"`,
  `COLLECTION_ID = "6f0e1a52-6a43-4f0b-9b8e-2a7c1d9e4b10"`. Pure helpers:
  `accepts_taxii(accept: str | None) -> bool` (true when any media range is
  `application/taxii+json` with no `version` or `version=2.1`; `*/*` alone is false, since TAXII
  requires a TAXII media range); `parse_match(query: Mapping[str, str]) -> MatchFilter` with
  `@dataclass MatchFilter(ids: set[uuid.UUID] | None, types: set[str] | None, version:
  Literal["last", "first", "all"] | datetime, spec_versions: set[str] | None)` (malformed →
  `ValueError`; unknown `match[...]` keys ignored); `parse_added_after(value: str | None) ->
  datetime | None` (RFC 3339 with a zone, else `ValueError`).
  Routes of spec 5.1. Discovery `api_roots = [str(request.base_url) + "taxii2/api/"]`, `default`
  the same URL; API root `max_content_length = 10485760`. `next` = `encode_cursor`, `more = next is
  not None`; `X-TAXII-Date-Added-First/Last` = `stix_ts` of the first/last returned row's
  `feed_changed_at`, omitted when there are no rows. `match[type]` without `indicator` and
  `match[spec_version]` without `2.1` return an empty envelope without a query;
  `match[version]=<timestamp>` keeps rows whose `stix_ts(feed_changed_at)` equals it. When both
  `added_after` and `next` are sent, `next` wins. Object-by-id and versions use
  `feed_page(stix_ids={uuid}, states=None)`; empty → 404.

- [ ] **Step 1: Unit tests:** `accepts_taxii` (`application/taxii+json;version=2.1` ✓,
  `application/taxii+json` ✓, `application/taxii+json;version=2.0` ✗, `application/json` ✗,
  `*/*` ✗, `None` ✗, a list with a TAXII range among others ✓); `parse_match` (comma OR, `last`
  default, `all`, a timestamp, `match[id]=indicator--bad` raises, `match[foo]` ignored);
  `parse_added_after` (`Z` ✓, naive raises, garbage raises).
- [ ] **Step 2: Integration tests** (`api_client`, Basic and Bearer, settle lag 0): bodies and
  `Content-Type` of discovery, API root, collections and collection; `test_406_without_taxii_accept`;
  `test_objects_paging_and_headers` (limit 2 over 5 → `more`, `next`, both headers; last page
  `more: false`); `test_added_after_strict`; `test_manifest_records` (`version` = the object's
  `modified`, `media_type` = `STIX_MEDIA`); `test_object_by_id_and_versions`;
  `test_object_above_tlp_404` (amber row, clear token: excluded from objects and manifest, 404 on
  object-by-id and versions); `test_revoked_published` (FP via `AsyncIndicatorRepo.add_feedback` →
  `revoked: true`); `test_match_type_other_empty`; `test_bad_next_400_taxii_error` (body has
  `title` and `http_status: 400`, TAXII content type); `test_post_objects_403`;
  `test_delete_object_403`; `test_status_404`; `test_unknown_collection_404`;
  `test_no_token_401_www_authenticate`.
- [ ] **Step 3:** Run; expected FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Interop test** `test_taxii2_client_reads_collection`: serve `create_app()` (with
  the `api_client` fixture's `get_db` override pattern) on a free local port with `uvicorn.Server`
  in a background thread; with `taxii2client.v21` (`Server`, `as_pages`) read discovery → API root
  → collection → `get_manifest()` → every page of `get_objects()` using Basic auth; assert each
  seeded indicator id arrives exactly once. If the user declined the dependency, write the same
  sequence with `httpx`, following `next` and asserting media types, named
  `test_taxii_flow_without_client_library`.
- [ ] **Step 6:** Run all TAXII tests and the unit suite; regenerate OpenAPI and `schema.d.ts`.
- [ ] **Step 7: Commit** `feat(api): add the TAXII 2.1 server`.

### Task 7: Web: API tokens section

**Files:**
- Create: `apps/web/src/components/admin/api-tokens-section.tsx`
- Modify: `apps/web/src/app/(app)/admin/users/page.tsx` (render
  `{can("manage_api_tokens") && <ApiTokensSection />}` and add `"manage_api_tokens"` to
  `adminPermissions`), `apps/web/src/app/(app)/admin/layout.tsx` (description mentions API tokens)

**Interfaces:**
- Consumes: `/api/api-tokens` (Task 3) through `api` from `@/lib/api/client` with types from
  `schema.d.ts` (not `loose-types`); the pattern of `components/admin/clients-section.tsx`
  (TanStack Query key `["admin", "api-tokens"]`, `Dialog`, `ConfirmDialog`, `Table`, `Badge`).
- UI copy (exact): card title `API tokens`; button `Create token`; dialog fields `Name`, `Max TLP`
  (`TLP:CLEAR`, `TLP:GREEN`, `TLP:AMBER`, `TLP:AMBER+STRICT`, `TLP:RED`), `Expires` (`365 days`,
  `90 days`, `Never`); result dialog title `Token created`, note `Copy it now. You will not see
  this token again.`, button `Copy`; revoke confirmation `Revoke token "<name>"? Clients using it
  stop working at once.`; status badges `active`, `expired`, `revoked`, plus `expires in N d` when
  fewer than 14 days remain.

- [ ] **Step 1: Implement** the section after reading `apps/web/CLAUDE.md` and
  `apps/web/AGENTS.md` (Base UI `Select` with single-string `SelectItem` children, `render=` not
  `asChild`; no `backdrop-blur`; theme tokens).
- [ ] **Step 2: Verify:** `pnpm lint`, `pnpm exec next typegen && pnpm exec tsc --noEmit`,
  `pnpm build`; all pass.
- [ ] **Step 3: Commit** `feat(web): add the API tokens admin section`.
- [ ] **Step 4: Browser QA (controller, not a subagent):** on the `qacve` stack as admin: create
  (token shown once, Copy works), the list shows prefix, TLP and expiry; `curl -u x:<token> -H
  'Accept: application/taxii+json;version=2.1' http://localhost:8000/taxii2/` → 200; revoke → the
  same curl → 401; `last_used_at` filled; an analyst sees no section; light, dark and 375 px. Tear
  the stack down.

### Task 8: Nginx exposure, docs and release notes

**Files:**
- Modify: `docker/nginx/templates/cti.conf.template`, `CHANGELOG.md` (`## [0.8.11]`),
  `docs/prod-upgrade/0.8.11.md`, `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md` (0.8.11 part),
  `docs/LLM_ASSIST_REDESIGN.md` (section 4 item 3 and the 0.8.11 block),
  `docs/TARGET_ARCHITECTURE.md` (progress), `docs/ARCHITECTURE.md` (a machine API paragraph:
  tokens, feed clock and triggers, TAXII)
- Test: `tests/unit/test_nginx_template.py` (create it unless `grep -rl cti.conf.template tests`
  finds an existing nginx test to extend)

**Interfaces:**
- nginx: `location /taxii2/ { set $cti_api http://api:8000; proxy_pass $cti_api; ... }` and the
  same for `/api/v2/`, with the `web` location's forwarded headers and timeouts; the header
  comment names the two exceptions.

- [ ] **Step 1: Test** `test_nginx_exposes_only_machine_api_paths`: the template has
  `location /taxii2/` and `location /api/v2/` proxying to `api:8000`, and no other location
  proxies to `api`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Edit the template; run; PASS; `docker compose config -q` passes.
- [ ] **Step 4: Docs** per spec section 8. CHANGELOG bullets in Indonesian (token API mesin, feed
  REST, server TAXII 2.1, indikator dicabut dipublikasikan sebagai `revoked`, nginx membuka
  `/taxii2/` dan `/api/v2/`). Runbooks keep their eight headings; content: the
  `<rev>_machine_api` migration; no new `.env` key; nginx recreated by the deploy (`up -d` with the
  rebuilt image); after-deploy checks (create a test token; `curl -u x:<token> -H 'Accept:
  application/taxii+json;version=2.1' https://<host>/taxii2/` → 200; one objects page; check
  `last_used_at`; revoke → 401); read-only query `SELECT count(*), count(stix_id),
  min(feed_changed_at) FROM indicators`; rollback (0.8.2 ignores the table and columns; the
  triggers are harmless); known risks R1-R6.
- [ ] **Step 5: Full verification:** `uv run ruff check . && uv run ruff format --check .`; mypy;
  `uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro`;
  `uv run pytest tests/integration -q` (in the background, about 7 min); OpenAPI drift
  (`uv run python tools/export_openapi.py && git diff --exit-code docs/openapi.json`).
- [ ] **Step 6: Commit** `feat(nginx): expose the machine API paths` and
  `docs: record the P7b machine API in the 0.8.11 notes`.

### Task 9: Dev test and PR (each outward step needs the user's approval)

- [ ] **Step 1:** Ask the user; on yes, merge the branch into `origin/Dev` and deploy on dev the
  usual way.
- [ ] **Step 2:** On dev (read-only DB checks): migration head; `count(stix_id) = count(*)`;
  `feed_changed_at` values are not all the 04:00 decay time. Create a token in the web; from the
  Mac (outside the host) `curl -k -u x:<token> -H 'Accept: application/taxii+json;version=2.1'
  https://172.25.1.77/taxii2/` → discovery URLs use the external host; page through objects; revoke
  → 401. Next day: confirm the decay sweep did not move `feed_changed_at`.
- [ ] **Step 3:** Ask the user; on yes, open the PR to `main` (body ends with the Claude Code
  line). No tag or Release (P7 ships as one 0.8.11 release later).
