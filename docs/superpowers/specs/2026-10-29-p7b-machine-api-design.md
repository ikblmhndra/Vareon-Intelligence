# P7b: machine API (scoped tokens, REST feed, TAXII 2.1) (design)

Status: **design, awaiting review** (2026-10-29). Ships in release **0.8.11** together with the
other P7 sub-projects (one release, one PR per sub-project); P7b does **not** bump the version.
Builds on P7a (PR #80, merged at `b717980`, migration head `a9e4c7b1d3f6`).

Source documents: `docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md` (section 0:
P7 decomposition and the API-first decision; sections 2-4: indicators, state, TLP/PAP),
`docs/LLM_ASSIST_REDESIGN.md` section 4 (items 2-3), `docs/TARGET_ARCHITECTURE.md` section 4.
Protocol reference: OASIS TAXII 2.1 (`taxii-v2.1-os`), STIX 2.1.

## 0. Decisions taken in brainstorming (2026-10-29)

| Topic | Decision |
|---|---|
| Interface | API-first, vendor-neutral: TAXII 2.1 as published plus plain REST. No Splunk-specific connector (P7a section 0). |
| Token management | Admins, through a new `manage_api_tokens` permission and a web page *Admin > API tokens* (create, show once, revoke). |
| Scopes | A scope list with one value today, `indicators:read`, covering REST and TAXII. P7d adds `sightings:write` later without a schema change. |
| Expiry | Optional. The form defaults to 365 days; "never" is allowed; the list warns before expiry. |
| Approach | **A, native in cti-api**: routers and services in `cti_api`, objects built at read time, a dedicated feed clock column. Rejected: B (OASIS `medallion` as a separate Flask service: a second app and auth for a few GET endpoints) and C (stored `stix_objects` version table: write hooks on every indicator path, unbounded growth, no consumer needs history). |
| Collections | One TAXII collection `indicators`, filtered per token by TLP. |
| `/api/v2` auth | Token only (no web JWT); the web does not call v2 yet. |
| Revoked / allowlisted | Kept forever and published with `revoked: true`. |

## 1. Goal and success criteria

Let machines (Splunk first, any TAXII 2.1 client or script after) pull indicators with a revocable
credential, see only what their TLP clearance allows, sync incrementally, and learn when an
indicator must be deleted.

Success criteria:

- An admin creates a token in the web, sees it once, and a client pulls the `indicators` collection
  over TAXII 2.1 with it (Bearer, or HTTP Basic with the token as password).
- A token with `max_tlp=clear` never receives an indicator marked above `clear` through any
  endpoint (list, objects, manifest, object by id, REST JSON or CSV).
- Incremental sync with `added_after` / `changed_after` or the cursor returns every change exactly
  once in order; the daily confidence decay sweep does **not** make indicators reappear.
- An analyst FP makes the indicator reappear in the feed with `revoked: true`.
- A revoked or expired token gets 401 at once; prod needs **no new `.env` key**.
- `taxii2-client` (OASIS reference client) can read discovery, the API root, the collection,
  manifest and objects (section 7, pending dependency approval).

## 2. Evidence (dev 172.25.1.77, 0.8.11/P7a, read-only, 2026-10-29)

- 5,469 indicators, all TLP `clear`; 0 revoked, 29 allowlisted, 157 expired (IPs). Types: domain
  1,703, sha256 1,260, ip 974, url 898, md5 345, email 166, sha1 122, `url_with_path` 1.
- **`updated_at` is unusable as a feed clock**: all 5,469 rows have the same `updated_at`
  (2026-10-29 04:00:25), written by the daily `ioc.decay_sweep` (beat 04:00), which recomputes
  confidence through the ORM. 130 rows had `last_seen_at` in the last day.
- No token, service-account or TAXII code exists; `deps.get_current_user` handles only web JWTs
  (Redis revocation).
- `services/stix.py::_build_indicator` sets `created`/`modified` to the export time (unstable
  versions), has no pattern for `url_with_path`, and escapes only `'` in patterns (a value with `\`
  gives an invalid pattern).
- cti-api is **not reachable from outside**: compose binds it to `127.0.0.1:8000` and the nginx
  template proxies only `web` (`docker/nginx/templates/cti.conf.template`). uvicorn runs with
  `--proxy-headers --forwarded-allow-ips *`.

## 3. Data model and migration

One hand-written Alembic migration, `machine_api`, after `a9e4c7b1d3f6`.

### 3.1 Table `api_tokens`

| Column | Type | Meaning |
|---|---|---|
| `id` | bigint PK | |
| `name` | varchar(200) not null | label, e.g. "Splunk ES prod" |
| `token_prefix` | varchar(12) not null | first characters of the token, shown in UI and logs |
| `token_hash` | char(64) not null, unique | sha256 hex of the full token; the token itself is never stored |
| `scopes` | text[] not null | today only `{indicators:read}` |
| `max_tlp` | varchar(12) not null default `clear` | CHECK in `TLP_LEVELS` |
| `created_by` | varchar(200) not null | username |
| `created_at` | timestamptz not null default now() | |
| `expires_at` | timestamptz null | `NULL` = never |
| `last_used_at` | timestamptz null | throttled write (section 4.1) |
| `revoked_at`, `revoked_by` | timestamptz / varchar(200) null | set on revoke; the row is kept for audit |

Token format: `vrn_` + `secrets.token_urlsafe(32)`. A plain sha256 is enough because the secret is
random with 256 bits of entropy (no password stretching needed). Model: `cti_core.db.models.auth`
(`ApiToken`), repository `AsyncApiTokenRepo`. Allowed scopes live in one constant
(`API_TOKEN_SCOPES`); unknown scopes are rejected at creation.

### 3.2 Column `indicators.feed_changed_at`

`timestamptz not null default clock_timestamp()`, index `(feed_changed_at, id)`. It is the feed clock: TAXII
`date_added` and STIX `modified`, and the REST cursor. Backfill in the migration:
`greatest(created_at, coalesce(revoked_at, created_at))`.

It is maintained by **Postgres triggers**, not application code, so every write path is covered:
both upserts, feedback, the marking PATCH, the raw `UPDATE` in `reconcile_validity`, and writes
through the P7a compatibility views from rolled-back 0.8.2/0.8.10 code.

- `BEFORE UPDATE ON indicators FOR EACH ROW`: set `NEW.feed_changed_at = clock_timestamp()` when any of
  `type`, `value`, `valid_from`, `valid_until`, `revoked_at`, `auto_suppressed`, `tlp`, `pap`,
  `seen_count`, `last_seen_at` is `DISTINCT FROM` the old value. Confidence, actionability,
  enrichment and `updated_at` do not count, so the decay sweep does not touch the clock.
- `AFTER INSERT OR DELETE ON indicator_tags FOR EACH ROW`: `UPDATE indicators SET feed_changed_at =
  clock_timestamp() WHERE id = <indicator_id>` (tags become STIX `labels`).

The model declares the column; the triggers live only in the migration (autogenerate does not
compare triggers), so section 7 has a dedicated trigger test. Downgrade drops triggers, functions,
index, column and table.

Expected churn: every re-sighting extends `valid_until`, so roughly the 130 rows/day seen on dev
are re-sent, instead of all 5,469 if `updated_at` were used.

### 3.3 Settle lag (commit-order safety)

The clock is `clock_timestamp()`, the statement time of the write, not `now()` (transaction start): the
enrich pipeline holds its transaction open across LLM calls, so a `now()` stamp could be minutes older than
the commit. Even so, a row becomes visible only at commit, after its stamp, so a client that already paged past the
stamp could skip it. The feed therefore never returns rows with `feed_changed_at > now() - 60 s`
(`FEED_SETTLE_SECONDS = 60`, a code constant, not a setting); the lag only has to cover write -> commit
(persist is the last step before commit). Changes become visible in the feed within about a minute. Lookups by
STIX id (`object-by-id`, versions) skip the lag.

## 4. Auth and the REST feed

### 4.1 `require_token(scope)` (`cti_api/machine_auth.py`)

- Accepts `Authorization: Bearer vrn_...` or `Authorization: Basic base64(any_user:vrn_...)`.
  Basic matters because many TAXII clients only take a username and password (TAXII 2.1 section
  1.6.9 recommends Basic).
- Hashes the token and looks the row up. Unknown, revoked or expired: **401** with
  `WWW-Authenticate: Basic realm="vareon", Bearer`; one message for all three, so the response does
  not reveal whether a token exists. Scope missing: **403**.
- Returns `MachinePrincipal(token_id, name, scopes, max_tlp)`. `last_used_at` is written only when
  the stored value is older than 60 seconds (one cheap conditional `UPDATE`).
- No JWT and no Redis: the feed keeps working when Redis is down.
- The dependency carries `.scope` like `require_permission` carries `.permission`;
  `tests/unit/test_route_permissions.py` is extended so every `/api/v2/*` and `/taxii2/*` route must
  use `require_token`, and every other route still needs `require_permission` (or its existing
  exemption).

### 4.2 One feed query (`cti_api/services/feed.py`)

A single query builder used by REST and TAXII, so no read path can skip a filter:

- TLP: `Indicator.tlp.in_(tlp_allowed(principal.max_tlp))`, where `tlp_allowed` returns the
  `TLP_LEVELS` up to and including `max_tlp` (in `cti_core/indicator/marking.py`).
- Settle lag (section 3.3); order `feed_changed_at, id` ascending; keyset pagination on that pair.
- Optional filters: state (through the `Indicator.state` hybrid), type, `changed_after`
  (strictly after), ids.
- Cursor: opaque URL-safe base64 of `(feed_changed_at isoformat, id)`; a malformed cursor is a 400.

### 4.3 `GET /api/v2/indicators` (`routers/v2_indicators.py`)

| Parameter | Meaning |
|---|---|
| `state` | repeatable; default **`active` only**, so a naive consumer never blocks revoked values; `state=any` for incremental sync |
| `type` | repeatable, the indicator types |
| `changed_after` | RFC 3339, strictly after `feed_changed_at` |
| `cursor` | from the previous page |
| `limit` | default 500, max 5000 |
| `format` | `json` (default) or `csv`; `Accept: text/csv` also selects CSV |

JSON: `{items, next_cursor}` (`next_cursor` null at the end). CSV: the same columns, tags joined
with `;`, the cursor in an `X-Next-Cursor` header. Item fields: `id`, `stix_id`, `type`, `value`,
`state`, `valid_from`, `valid_until`, `first_seen`, `last_seen`, `seen_count`, `confidence`, `tlp`,
`pap`, `tags`, `revoked_at`, `changed_at`. `confidence` is the live column value (it is excluded
from STIX, section 5.3, because the decay sweep changes it daily).

Errors under `/api/v2` use `{error: {code, message, details}}` (`TARGET_ARCHITECTURE` section 4);
the handler is registered for that prefix only, so v1 responses do not change.

Not built: per-token rate limiting, `GET /api/v2/indicators/{id}`, other v2 resources.

## 5. TAXII 2.1 server (`routers/taxii.py`)

### 5.1 Endpoints

All paths end with `/` (TAXII 2.1 section 3.1); all use `require_token("indicators:read")`.

| Endpoint | Response |
|---|---|
| `GET /taxii2/` | discovery: `title`, `default`, `api_roots` (absolute URLs from `request.base_url`) |
| `GET /taxii2/api/` | API root: `title`, `versions: ["application/taxii+json;version=2.1"]`, `max_content_length` |
| `GET /taxii2/api/collections/` | `{collections: [<indicators>]}` |
| `GET /taxii2/api/collections/{id}/` | the collection: fixed UUID, `title`, `description`, `can_read: true`, `can_write: false`, `media_types: ["application/stix+json;version=2.1"]` |
| `GET .../{id}/manifest/` | `{more, next, objects: [{id, date_added, version, media_type}]}` |
| `GET .../{id}/objects/` | envelope `{more, next, objects}` |
| `GET .../{id}/objects/{object_id}/` | envelope with the one object |
| `GET .../{id}/objects/{object_id}/versions/` | `{more: false, versions: [<modified>]}` |
| `POST .../objects/`, `DELETE .../objects/{object_id}/` | **403** (`can_write: false`) |
| `GET /taxii2/api/status/{id}/` | **404** (no write operations, so no status resources) |
| unknown collection id | **404** |

### 5.2 Protocol rules

- `Accept` must contain `application/taxii+json` (with `version=2.1` or no version); otherwise
  **406**. Every response, errors included, has `Content-Type: application/taxii+json;version=2.1`.
- Errors are TAXII error objects `{title, http_status, description}`.
- Paging: `limit` default 500, max 1000; `added_after` strictly after `feed_changed_at`; `next` is
  the cursor of section 4.2; `more: true` while rows remain. `X-TAXII-Date-Added-First` and
  `X-TAXII-Date-Added-Last` on manifest, objects, object by id and versions.
- Filters: `match[id]` and `match[type]` (comma-separated values are ORed, fields are ANDed; a type
  other than `indicator` returns an empty result, not an error); `match[version]` `last`, `first`
  and `all` return the single stored version, a timestamp matches only an equal `modified`;
  `match[spec_version]` only `2.1`. Malformed parameters: **400**. Unknown `match[...]` fields are
  ignored.
- TLP through the shared query (section 4.2); an object above the token's `max_tlp` is **404** on
  object by id and versions.
- Only the latest version is stored. TAXII 2.1 sets no retention rule, so `versions` lists one
  version.

### 5.3 STIX object per indicator

`_build_indicator` in `services/stix.py` is fixed and reused (the snapshot export benefits too):

- `id` `indicator--uuid5(type:value)`, unchanged, so ids stay stable across the export and TAXII.
- `created` = `created_at`, `modified` = `feed_changed_at` (millisecond precision, `Z`;
  `modified >= created` holds because the backfill uses `greatest`).
- `valid_from`, `valid_until` (omitted for hashes), `labels` (tags), `object_marking_refs` with the
  official TLP 2.0 marking id, `x_seen_count`, `x_last_seen`.
- **`revoked: true`** when the state is `revoked` or `allowlisted`, so subscribers delete it; an
  indicator allowlisted after it was published is retracted the same way.
- No `confidence` (it changes daily through decay; REST carries it).
- `url_with_path` maps to the `url` pattern; pattern escaping handles `\` before `'`.
- Marking-definition objects are not put in the collection: the five TLP 2.0 definitions are
  standard OASIS objects known by id, and including them would complicate keyset paging (risk R2).
  No `identity` / `created_by_ref`.

## 6. Token administration and web

### 6.1 API (`routers/api_tokens.py`, `require_permission("manage_api_tokens")`, audit-logged)

- New permission `manage_api_tokens` in `ALL_PERMISSIONS`, granted to the built-in `admin` role
  (superadmin has every permission); not to `analyst`.
- `GET /api/api-tokens`: list without hashes, with a computed `status` (`active | expired |
  revoked`).
- `POST /api/api-tokens` `{name, max_tlp, expires_in_days: int | null}`: returns the token **once**
  with the row; unknown TLP or `expires_in_days` outside 1-3650 is 422.
- `DELETE /api/api-tokens/{id}`: sets `revoked_at`/`revoked_by` (idempotent); 404 for unknown ids.
- Regenerate `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts`. The TAXII and v2 routes
  appear in OpenAPI with an `apiToken` security scheme.

### 6.2 Web (`app/(app)/admin/api-tokens/page.tsx`)

- Under the existing admin layout, next to `admin/users`; the nav entry and page are hidden
  without `useCan("manage_api_tokens")`.
- Table: name, prefix, max TLP, created by/at, last used, expires, status; a warning badge when a
  token expires within 14 days.
- "Create token" dialog: name, TLP select, expiry (365 days / 90 days / never). The result dialog
  shows the token once with a copy button and a "you will not see this again" note.
- Revoke with a confirmation dialog.
- Base UI rules from `apps/web/CLAUDE.md` (`SelectItem` children a single string, `render=`), no
  `backdrop-blur`, tested in light and dark mode and at 375 px.

### 6.3 Nginx (`docker/nginx/templates/cti.conf.template`)

Two locations, `location /taxii2/` and `location /api/v2/`, proxy to `http://api:8000` with the same
`set $var` + resolver pattern as `web` and the same forwarded headers. The rest of `/api/*` stays
unexposed; the header comment ("API TIDAK lewat sini") is updated to name the two exceptions.

## 7. Testing

- **Unit**: token generation, prefix and hash; `tlp_allowed`; cursor round trip and malformed
  cursor; STIX builder (`created`/`modified` from the row, `revoked`, `url_with_path`, `\` and `'`
  escaping, no `confidence`); `match[...]` and `Accept` parsing; route coverage
  (`require_token` on v2 and taxii; `manage_api_tokens` on the admin routes); permission catalog.
- **Integration** (testcontainers):
  - migration up/down and the `feed_changed_at` backfill; `test_migrations_match_models` green;
  - triggers: revoke, restore, marking, `valid_until` (including the raw reconcile `UPDATE`), tag
    insert/delete bump the clock; confidence and enrichment updates do not;
  - auth: Bearer and Basic accepted; revoked, expired and unknown tokens 401 with
    `WWW-Authenticate`; wrong scope 403; `last_used_at` throttled;
  - TLP: a `clear` token never sees an `amber` indicator on REST JSON, CSV, manifest, objects, or
    object by id (404);
  - paging: no duplicates or gaps across pages; rows inside the settle lag are not returned;
    `added_after`; `X-TAXII-Date-Added-*` headers; 406, 400, 403 on POST, 404 on status;
  - REST default `state=active`, `state=any`, CSV columns and `X-Next-Cursor`;
  - an FP makes the indicator reappear with `revoked: true`;
  - token admin CRUD, audit rows, analyst 403.
- **Interop**: one integration test drives `taxii2-client` (OASIS reference client) against the test
  app through discovery, API root, collection, manifest and objects with Basic auth. It is a new
  **dev-only** dependency; adding it needs the user's approval when the plan is reviewed. Without
  it, the same flow is tested with plain `httpx` calls.
- **Snapshots**: syrupy snapshots updated if a touched router has them.
- **Web**: `pnpm lint`, `next typegen` + `tsc --noEmit`, `pnpm build`; browser check of the token
  page on the isolated `qacve` compose project.

## 8. Release (part of 0.8.11, no version bump)

- `CHANGELOG.md`: add to the existing `## [0.8.11]` entry (Indonesian).
- `docs/prod-upgrade/0.8.11.md` and the 0.8.11 part of `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`
  (same eight headings): the `machine_api` migration; **no new `.env` key**; nginx must be
  recreated so the new template is used; after deploy: create a test token, `curl` discovery and
  one objects page with it, check `last_used_at`, revoke it; rollback: 0.8.2 code ignores the new
  table and column, and the triggers only maintain a column it never reads.
- `docs/LLM_ASSIST_REDESIGN.md` (section 4 item 3 partly delivered: TAXII yes, Splunk lookup export
  dropped by the API-first decision) and `docs/TARGET_ARCHITECTURE.md` progress.
- Merge to `origin/Dev`, test on dev (token page, TAXII pull from a client outside the host), then
  the PR to `main` with the user's approval. The 0.8.11 tag and Release come after the last P7
  sub-project merges.

## 9. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | An indicator's TLP is raised after it was published; a consumer below the new level stops receiving it and never gets the deletion. A tombstone would leak the value (STIX requires `pattern`). | Markings only rise through an analyst PATCH; everything is `clear` today. Documented as a known limitation in the runbook; revisit when a non-public source exists. |
| R2 | A strict client requires the `marking-definition` objects inside the collection. | Interop test with `taxii2-client`; if a consumer needs them, add the referenced definitions with a fixed `date_added` before all indicators. |
| R3 | `/taxii2/` and `/api/v2/` are now exposed on 443. | Token required on every route, read-only, one scope, hashed tokens, revocation takes effect on the next request. Per-token rate limiting is a follow-up. |
| R4 | Discovery returns wrong absolute URLs behind the proxy. | nginx passes `Host`, uvicorn runs with `--proxy-headers`; checked on dev from outside the host. |
| R5 | A write commits more than 60 s after its statement and a client already past that stamp skips it. | The clock is statement time, so only write -> commit must fit in the lag (persist is last); the lag is one constant; the next change to the row (re-sighting) re-sends it. Documented. |
| R6 | Triggers are invisible to the drift test and to readers of the model. | Dedicated trigger tests; a docstring on `feed_changed_at` names the triggers and the migration. |
| R7 | Hard delete (`DELETE /api/iocs/{id}`, bulk delete) removes an indicator from the feed without a retraction. | Known limitation: subscribers keep it until `valid_until`; analysts mark FP (revoke) to retract a published indicator. Documented in the runbook. |
| R8 | A TP after an FP, or removing an allowlist entry, re-publishes the same `indicator--` id without `revoked`; STIX 2.1 treats revocation as permanent. | Known limitation: strict consumers may keep it deleted. Documented. |
| R9 | Expiry is time-based and does not move the feed clock; REST `state` is a snapshot at sync time. | Consumers evaluate `valid_until` themselves. Documented. |

## 10. Out of scope

- Sightings (P7d, deferred), entities and relationships (P7c), hunting packs (P7e).
- Splunk-specific lookup / KV-store exports or connectors.
- TAXII writes (`POST` objects, status resources), version history, more collections.
- TLP on articles, stories or entities; other `/api/v2` resources; web pages on v2.
- Per-token rate limiting, IP allowlists, token rotation helpers.
