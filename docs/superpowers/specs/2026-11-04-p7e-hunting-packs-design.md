# P7e: hunting packs (design)

Status: **approved, built for 0.8.11** (2026-11-04). Part of release **0.8.11** (no version bump; the
release rule of 2026-10-29: all P7 work ships as one release, one PR per sub-project). Branch
`claude/p7e-hunting-packs` on `main` `0b26f7c` (P6, P7a, P7b, P7c-1, P7c-2).

Source documents: `docs/LLM_ASSIST_REDESIGN.md` section 4 item 6, P7 decomposition in
`docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md` section 0, the P7b machine API
(`2026-10-29-p7b-machine-api-design.md`) and the entity model (`2026-10-29-p7c-entity-model-design.md`,
`2026-11-01-p7c2-entity-web-design.md`).

## 0. Decisions taken in brainstorming (2026-11-04)

| # | Topic | Decision |
|---|---|---|
| D1 | Anchor | **Story and entity**, one builder. Story: techniques and indicators of its member articles. Entity (`intrusion-set`, `malware`, `tool`, `campaign`): ATT&CK/analyst `uses` techniques plus indicators of the stories that mention it. |
| D2 | TTP sources (story) | **Tiered.** Default `primary` = mentions with method `explicit`/`keyword`/`analyst`. `inferred` (ATT&CK `uses` of the story's actors/malware, `services/inferred_ttps.py`) and `llm` mentions are shown separately as weaker and only feed Sigma when asked for (`include=inferred,llm`). |
| D3 | Sigma source | **Committed pinned SigmaHQ release snapshot plus a weekly sync** (MISP Galaxy precedent, P7c D5). Rules are stored in the product with their YAML; the sync keeps the old set on any failure. |
| D4 | Delivery | **Web + REST v2.** Web tab/section with copy and download; `GET /api/v2/hunt-packs/...` with a new token scope `hunt:read` and TLP per token. Not in TAXII. |
| D5 | SPL shape | **`tstats` over CIM data models with inline values, split at 200 values per search**, plus an IOC CSV per data model for teams that prefer lookups. Only `active` indicators. No hard-coded time range. |
| D6 | LLM hunt hypothesis | **On demand, web only**: a button (`manage_intel`), stored per anchor, logged in `llm_calls`, labelled as an LLM draft. Never automatic, never in SPL, Sigma, the zip or API v2. |
| D7 | Approach | **Built at read time** (`services/hunt_pack.py`): no stored packs. New tables only `sigma_rules` and `hunt_hypotheses`. Rejected: materialised `hunt_packs` (write hooks in the enrichment path, which P7g is changing; staleness; TLP must be filtered at read anyway) and a worker that renders files to storage (new component, same staleness). |

Not built in the product: Sigma-to-SPL conversion (needs pySigma and a Splunk backend; Sigma is the
vendor-neutral format and consumers convert with `sigma-cli`), Sigma rules as STIX objects in TAXII,
sightings (P7d), per-user TLP (section 10, R1).

## 1. Goal and success criteria

Give an analyst, and a machine with a token, a ready-to-run hunt for a story or an entity: an IOC
search over the CIM data models, the Sigma rules for its ATT&CK techniques with attribution, and the
IOC lists, all generated from templates and data.

Success criteria:

- For a story with techniques and indicators, the web shows SPL that pastes into Splunk unchanged,
  the matching Sigma rules with author and link, and a zip download, in under 1 s for the largest
  dev story (563 indicators).
- Only `active` indicators appear; an analyst FP removes the indicator from the next pack.
- A token with `max_tlp=clear` never receives an indicator above `clear` in a pack; a token without
  `hunt:read` gets 403.
- Deploy needs no internet and **no new `.env` key**: `sigma_rules` is filled from the committed
  zip at API start-up; the weekly sync failing leaves the rules as they were.
- The zip and the web page credit Sigma rule authors and state DRL 1.1 (section 2.2).

## 2. Evidence (dev 172.25.1.77, read-only, 2026-11-04)

| Measure | Value |
|---|---|
| Stories | 1,709 (1,147 active in the last 30 days) |
| Stories with any technique mention / `explicit`+`keyword` / `llm` | 847 / 492 / 623 |
| Stories with indicators | 498 |
| Stories with techniques **and** indicators | 374 |
| Indicators per story (p50 / p90 / p99 / max) | 4 / 29 / 155 / 563 |
| Techniques per story (p50 / p90 / p99 / max) | 4 / 8 / 32 / 62 |
| Distinct techniques from `explicit`/`keyword` | 297 |
| Indicator types linked to stories | domain 2,291, sha256 1,304, ip 1,173, url 1,128, md5 366, email 178, sha1 165, url_with_path 1 |
| Indicator TLP | all `clear` (6,630) |
| Stories mentioning intrusion-set / malware / tool | 296 / 240 / 141 |
| `attack_techniques` rows with `data_sources` / `detection` | 0 / 0 of 961 |

Consequences: SPL must be split for large stories (D5). ATT&CK data sources cannot drive a
technique-to-data-model mapping (the columns are empty), so the IOC part maps by indicator type and
the technique part is served by Sigma `logsource`. P4 precision on silver labels (2026-10-25):
`explicit` 99%, `keyword` 70%, `llm` 35%, which is why `llm` is opt-in (D2).

### 2.1 SigmaHQ (read-only check, 2026-11-04)

- Latest release `r2026-07-01`. Asset `sigma_all_rules.zip` (3,172,748 bytes): rules of level
  medium and above, status experimental and above, core and emerging-threats folders. Threat-hunting
  rules are in no release package. The smaller packages (Core = stable/test, high/critical) are
  subsets, so `all_rules` plus the stored `status`/`level` lets the pack rank instead of exclude.
- Rules carry ATT&CK techniques as tags (`attack.t1059.001`).

### 2.2 Licence: Detection Rule License (DRL) 1.1

Permits use, copy, modification, redistribution and sale. Conditions when sharing the rules: keep
the author identification (`author` field), give a link to the rule or rule set where reasonably
practicable, and state DRL 1.1 with the text or a link. When rules are used on data, messages based
on matches keep the author identification. Hence every rule shown or exported carries `author` and
a link to `github.com/SigmaHQ/sigma/blob/<release>/<path>`; the zip carries a README with the
attribution and the DRL 1.1 text; the snapshot directory keeps the licence file.

## 3. Data model and migration

One hand-written Alembic migration (`hunt_packs`), DDL only, chained after the current head. No
data step: the rules are loaded by the API bootstrap (section 4.2), because migrations in this repo
stay pure SQL.

### 3.1 `sigma_rules`

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid PK | the rule's `id` |
| `title` | text not null | |
| `author` | text not null default `''` | verbatim (DRL attribution) |
| `level` | varchar(16) not null | `informational, low, medium, high, critical` |
| `status` | varchar(16) not null | `stable, test, experimental` (others are skipped at load) |
| `ruleset` | varchar(20) not null | `core` or `emerging-threats` (from the path) |
| `logsource` | jsonb not null | `product`, `category`, `service` |
| `techniques` | varchar(20)[] not null | upper-case ATT&CK ids from `tags` (`attack.t1059.001` -> `T1059.001`); GIN index |
| `path` | text not null | path inside the SigmaHQ repository |
| `release` | varchar(40) not null | release tag, for the link |
| `yaml` | text not null | the rule as published |
| `loaded_at` | timestamptz not null default now() | |

Rules without any technique tag are stored too (cheap; later anchors may use them) but never match
a pack.

### 3.2 `hunt_hypotheses`

`id` bigint PK, `anchor_type` varchar(10) CHECK in `story, entity`, `anchor_id` bigint not null,
`text` text not null, `model` varchar(120) not null, `generated_by` varchar(200) not null,
`generated_at` timestamptz not null default now(). Unique `(anchor_type, anchor_id)`; regenerating
replaces the row. No FK (two anchor tables); a deleted story or merged entity leaves an orphan row
that is never read.

### 3.3 Model drift and rollback

Both tables are in the SQLAlchemy models, so `test_migrations_match_models` covers them.
deploy.sh rollback re-tags images and never downgrades: older images ignore both tables. The
migration's downgrade drops them.

## 4. Sigma ingest (`cti_core/hunt/sigma.py`)

### 4.1 `load_sigma_zip(session, data: bytes, release: str) -> SigmaLoadResult`

- Opens the zip in memory; reads `*.yml` under `rules/` and `rules-emerging-threats/` (any top
  folder prefix the release adds is stripped). Path segments containing `deprecated` or
  `unsupported` are skipped.
- Parses each file with `yaml.safe_load`. Required: `id` (UUID), `title`, `logsource`, `level`,
  `status` in `stable, test, experimental`. A file that fails is counted as `skipped` with a reason;
  it does not fail the load. PyYAML is already in `uv.lock` as a transitive dependency (6.0.3); it is
  declared as a direct dependency of `cti-core` (no new package).
- **Guards** (the whole load is refused, the table untouched): the zip cannot be opened; fewer than
  1,000 valid rules; fewer than 80% of the rule count currently stored.
- Replaces the table content in one transaction (`DELETE` + bulk `INSERT`).
- Writes the `reference_snapshots` row `sigma`: `fetched_at`, `sha256` of the zip, `content` =
  `{release, rules, skipped, source_url, last_error: null}` (no rule bodies; the rules live in
  `sigma_rules`).

### 4.2 Three callers

1. **API bootstrap**: `bootstrap_reference_rows` (already under the Postgres advisory lock) calls
   `ensure_sigma_rules`: when `sigma_rules` is empty, load the committed zip
   `packages/cti-core/src/cti_core/hunt/data/sigma/sigma_all_rules.zip` with the release from the
   `SOURCE` file next to it. A failure is logged and does not stop the API (packs then have no
   Sigma part; Data health shows it).
2. **CLI** `cti-sigma import <zip> --release <tag>` (typer, same style as `cti-entity`) for a manual
   update or a prod host without outbound access.
3. **Weekly task `sigma.sync`** on the `maintenance` queue (beat, Sunday 03:30): `GET
   https://api.github.com/repos/SigmaHQ/sigma/releases/latest`; if `tag_name` equals the stored
   release, stop; else download the asset named `sigma_all_rules.zip` (timeout 60 s, size limit
   20 MB) and call `load_sigma_zip`. Any error is logged and written to `content.last_error` of the
   snapshot row; the rules stay as they were. Setting `SigmaSettings.sync_enabled: bool = True`
   (`SIGMA__SYNC_ENABLED`, optional, default on, documented commented-out in `.env.example` and
   `.env.prod.template`).

The committed snapshot directory holds `sigma_all_rules.zip`, `SOURCE` (release tag, asset URL,
sha256, download date) and `LICENSE.Detection.Rules.md` (DRL 1.1 text). Downloading it is a
one-off step that needs the user's approval during implementation.

### 4.3 Data health

`/data-health` gets a `sigma` block: release, rule count, `fetched_at` of the snapshot row, and
`last_error`. Amber when the snapshot is older than 60 days or `last_error` is set, red when the
table is empty.

## 5. Pack builder (`cti_api/services/hunt_pack.py`)

### 5.1 Collectors (async, session-first)

**Story** `collect_story(session, story_id)`:

- Techniques: `entity_mentions` of type `attack-pattern` on the member articles, tier by method:
  `explicit`/`keyword`/`analyst` -> `primary`; `llm` and any other method (for example `legacy`) -> `llm`; plus `inferred_ttps.for_article` per
  member article -> `inferred`. A technique in several tiers keeps the strongest
  (`primary` > `inferred` > `llm`).
- Indicators: `indicator_sources.article_id` in the member articles.

**Entity** `collect_entity(session, entity_id, days=90)`; types `intrusion-set`, `malware`, `tool`,
`campaign`:

- Techniques: non-revoked `relationships` `uses` from the entity to `attack-pattern` entities
  (provenance `attack` or `analyst`), all `primary`.
- Indicators: those linked to stories that mention the entity with `last_seen_at` within `days`,
  plus non-revoked `indicates` relationships to the entity. Indicators of articles without a story
  use the article date `coalesce(posted_on, created_at::date)`. Suppressed `attack-pattern` targets
  are excluded. Capped at **2,000**, newest `last_seen`
  first; the pack reports `truncated: true` when the cap cut.
- An `attack-pattern` entity gets a Sigma-only pack (its own technique). Other types: 404.
- A suppressed anchor entity: 404.
- A merged entity (`merged_into_id` set): 404 with the target id in the error details (the web
  redirects, as the entity page does).

### 5.2 Indicator filter (one place, before building)

State `active` (the `Indicator.state` hybrid of P7a) and, for tokens, `tlp in tlp_allowed(max_tlp)`
(`cti_core.indicator.marking`, the P7b helper). The count hidden by TLP is not reported.

### 5.3 Pure builder `build_pack(techniques, indicators, sigma_rows, include) -> HuntPack`

No I/O; unit-tested on plain values.

**CIM mapping** (one table in code, `CIM_MAP`):

| Indicator types | Data model / dataset | Fields (ORed) |
|---|---|---|
| `ip` | `Network_Traffic.All_Traffic` | `All_Traffic.src`, `All_Traffic.dest` |
| `domain` | `Network_Resolution.DNS` | `DNS.query` |
| `domain` | `Web.Web` | `Web.url_domain` |
| `url`, `url_with_path` | `Web.Web` | `Web.url` |
| `md5`, `sha1`, `sha256` | `Endpoint.Processes` | `Processes.process_hash` |
| `md5`, `sha1`, `sha256` | `Endpoint.Filesystem` | `Filesystem.file_hash` |
| `email` | `Email.All_Email` | `All_Email.src_user` |

**SPL template** (one search per dataset and chunk of at most 200 values):

```
| tstats summariesonly=false count min(_time) as first_seen max(_time) as last_seen
  from datamodel=Network_Traffic.All_Traffic
  where All_Traffic.src IN ("198.51.100.7", ...) OR All_Traffic.dest IN ("198.51.100.7", ...)
  by All_Traffic.src All_Traffic.dest
| convert ctime(first_seen) ctime(last_seen)
```

Values are quoted with `\` and `"` escaped. A value containing `*`, a control character or a
newline is skipped (in SPL `*` is a wildcard) and counted in `skipped_values`. Values are sorted for
stable output. The pack, dataset and chunk are carried in the JSON and in the zip file name, not in
an SPL comment (comment macros are not available in every Splunk deployment).

**Sigma selection**: rules whose `techniques` intersect the techniques of the enabled tiers
(`primary` always; `inferred`, `llm` when in `include`). Match kind: `exact`; `sub` (pack has
`T1059`, rule tags `T1059.001`); `parent` (pack has `T1059.001`, rule tags only `T1059`). Order:
`ruleset` core first, then level critical > high > medium, then status stable > test >
experimental, then title. At most `sigma_per_technique` rules (default 5, `0` = no cap) are kept
per `via_technique`, preferring exact over sub over parent, then the order above; the per-technique
`sigma_count` stays uncapped and `counts.sigma_total` reports the number of matches before the cap.
Each rule: `id, title, level, status, author, link, techniques, match,
via_technique`.

**HuntPack** (JSON): `anchor {type, id, title}`, `generated_at`, `sigma_release`,
`techniques [{attack_id, name, tier, sigma_count}]`, `spl [{dataset, chunk, value_count, query}]`,
`sigma [...]`, `iocs {<dataset>: [{type, value, valid_until, tlp}]}`, `counts {indicators,
skipped_values}`, `truncated`, `include`.

**Zip** (`format=zip`): `README.md` (anchor, generation time, Sigma release, how to run the SPL,
CIM assumptions, attribution and DRL 1.1 notice), `LICENSE.Detection.Rules.md`,
`spl/<dataset>-<n>.spl`, `sigma/<rule id>.yml` (YAML as published), `iocs/<dataset>.csv`
(`type,value,valid_until,tlp`).

## 6. API

### 6.1 Machine: `GET /api/v2/hunt-packs/{anchor_type}/{anchor_id}`

`require_token("hunt:read")`; `hunt:read` is added to `API_TOKEN_SCOPES` (existing tokens are
unchanged; the token form lists the new scope). Parameters: `include` (repeatable, `inferred`,
`llm`), `days` (entity only, 1-365, default 90), `sigma_per_technique` (0-500, default 5, 0 = no cap),
`format` `json` (default) or `zip` (the zip follows the same cap, and its README states it). TLP filter by
the token's `max_tlp`. Errors in the v2 shape `{error: {code, message, details}}`: unknown anchor or
unsupported entity type 404, merged entity 404 with `details.merged_into_id`, invalid parameter 422
(the existing `/api/v2` validation handler).
`test_route_permissions` already requires `require_token` on `/api/v2/*`.

### 6.2 Web: `/api/hunt-packs/{anchor_type}/{anchor_id}`

`GET` (`require_permission("view_ioc")`), same parameters (including `sigma_per_technique`) and builder, no TLP filter (web users have
no TLP clearance today; R1). `GET .../hypothesis` (`view_ioc`) returns the stored row or 404.
`POST .../hypothesis` (`manage_intel`, audit-logged) generates and stores it (section 7.2).

Typed schemas; `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts` regenerated.

## 7. Web and LLM hypothesis

### 7.1 Web

- The API token form lives in `apps/web/src/components/admin/api-tokens-section.tsx`.
- **Entity page** (`intelligence/entities/[id]`): new tab **Hunt** for the supported types.
- **Newsroom article detail**: a **Hunt** section for the article's story (hidden when the story has
  neither techniques nor indicators).
- Content: techniques grouped by tier with `inferred`/`llm` checkboxes (refetch with `include`);
  one card per SPL search with a copy button; Sigma table (title, level, status, author, link,
  logsource; the YAML itself is only in the zip, the JSON pack stays small); buttons *Download pack (zip)* and per-dataset CSV; the line "Sigma rules by
  their authors, Detection Rule License 1.1" with links; a `truncated` note for entities.
- **Hypothesis panel**: shows the stored draft with an "LLM draft" badge, model and time;
  *Draft hypothesis* / *Regenerate* button for `manage_intel`.
- shadcn/ui on Base UI (`apps/web/CLAUDE.md`), no `backdrop-blur`, checked in light and dark and at
  375 px.

### 7.2 Hypothesis generation

`services/hunt_hypothesis.py`, `get_llm_client(task="hunt_hypothesis")`. Input: anchor title, story
summary (`Story.classify["reason"]`; articles have no summary column) or entity description (truncated), `primary` techniques (id + name), and the dataset names
that have indicators. **No indicator values** are sent. The prompt asks for 3-5 hypotheses, each
with the behaviour to look for, the data needed and the technique id; plain text output, stored
as-is. Logged in `llm_calls` by the existing client wrapper. An LLM error returns 502 and keeps the
old row.

## 8. Testing

- **Unit (builder)**: CIM mapping per type; chunking at 200; escaping of `"` and `\`; skipping of
  `*`/newline values; deterministic ordering; tier precedence; Sigma match kinds and order; zip
  members and README attribution.
- **Unit (`load_sigma_zip`)**: a small fixture zip built in the test (no download): good load,
  rule without `id` skipped, `deprecated` path skipped, broken zip refused, below 1,000 / below 80%
  refused with the table unchanged; tag parsing (`attack.t1059.001`; tactic tags ignored).
- **Integration (testcontainers)**: story and entity packs from seeded rows; revoked and expired
  indicators absent; token `max_tlp=clear` never gets an `amber` indicator; token without
  `hunt:read` 403; merged entity 404 with target; bootstrap fills `sigma_rules` once and a second
  run changes nothing; `test_migrations_match_models` green; hypothesis endpoint with a fake LLM.
- **Worker**: `sigma.sync` with a fake fetch: same tag no-op, new tag loads, failure keeps rows and
  sets `last_error`; `sync_enabled=false` returns at once.
- **Contract**: OpenAPI drift check; `.env.example` / `.env.prod.template` tests for the new
  optional key.
- **Web**: lint, typegen + tsc, build; manual check light/dark/375 px.
- **Dev (after merging to `origin/Dev`)**: packs for 3 stories with techniques and indicators,
  including the largest (563 indicators), and one actor entity; response time; SPL syntax checked
  (run in Splunk if the user has access); `sigma_rules` count and Data health block.

## 9. Release (part of 0.8.11, no version bump)

- `CHANGELOG.md` `## [0.8.11]` gets a P7e entry (Indonesian).
- `docs/prod-upgrade/0.8.11.md` and the 0.8.11 part of `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`:
  migration (two tables), optional `SIGMA__SYNC_ENABLED`, after deploy check `select count(*) from
  sigma_rules` and the Data health block, outbound access to `api.github.com` / `github.com` needed
  only for the weekly sync, rollback leaves the tables.
- `docs/LLM_ASSIST_REDESIGN.md` section 4 item 6 and the P7a spec table point to this spec.
- No change to `cti_enrich` or `tasks/enrich.py` (P7g is changing them).

## 10. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | Web users have no TLP clearance; the web pack shows every TLP to `view_ioc` holders | Same as every web IOC view today; all indicators are `clear`. Per-user TLP is a separate follow-up. Tokens are filtered. |
| R2 | The CIM mapping is the standard one; a consumer's field extraction may differ | Mapping in one table; README states the assumptions; Splunk team feedback adjusts it. |
| R3 | The weekly sync follows `releases/latest`, not a pinned tag (decision D3) | Validation, 1,000 / 80% guards, old rules kept on failure, tag and sha256 recorded, switch `SIGMA__SYNC_ENABLED`. |
| R4 | `all_rules` includes experimental rules | Status and level shown; ranked last. |
| R5 | Large entities (e.g. a ransomware family) have thousands of indicators | 90-day window, 2,000 cap, `truncated` flag, chunked SPL. |
| R6 | Repo grows by the 3.2 MB zip per baseline refresh | Updates come through the sync; the committed zip changes only when someone chooses to refresh the baseline. |

## 11. Out of scope

Sigma-to-SPL (or any backend) conversion, Sigma in TAXII, per-user TLP, sightings (P7d), pack
history or versioning, scheduled delivery of packs, hypothesis via API v2.
