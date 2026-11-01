# P7c-2: entity web (design addendum)

Status: **design, awaiting review** (2026-11-01). Addendum to section 7 of
`docs/superpowers/specs/2026-10-29-p7c-entity-model-design.md` (the "parent spec"); everything not
restated here follows the parent spec. Ships in release **0.8.11**, no version bump. Branch
`claude/p7c2-entity-web-f1a8bd`, based on PR #82 (P7c-1) head `7379c51`; the P7c-2 PR is opened
against `main` **after PR #82 merges** (not stacked).

## 0. Why an addendum

The parent spec has a gap between D2 ("every feature ... is moved to entity **ids** and links")
and 5.1 ("v1 response shapes do not change; names come from `entities.name`"). P7c-1 implemented
5.1, so v1 responses carry names only, and section 7.3 does not say where `EntityChip` gets the id.
A read-only inventory (2026-11-01) found about 26 GET endpoints and ~85 name-bearing fields behind
the features of 7.3 (~29 typed Pydantic fields, ~55 keys of untyped `dict` responses), and several
name sources that can never carry an id: LLM output (recap, diamond-model profile fields,
geopolitical nations), user-typed PIR criteria, raw ransomware columns, and newsletter queue items
stored in `localStorage`.

## 1. Decisions (brainstorming 2026-11-01)

| # | Topic | Decision |
|---|---|---|
| W1 | Chip linking | **Hybrid.** `EntityChip` links straight to `/intelligence/entities/{id}` when it has an id, otherwise to the resolve route (section 2) with `{type, name}`. |
| W2 | Long-term rule | Written rule: **every value that comes from an entity mention carries its `entity_id`; resolving by name is only for text that has no entity behind it** (LLM output, user-typed criteria, raw scraped columns, stored copies). New or touched endpoints follow it. P7c-2 adds ids where cheap (section 3); exec aggregates and campaign clusters move to ids in a follow-up PR after 0.8.11 (section 8). |
| W3 | PIR malware | Add a `malware` criterion (malware **and** tool entities) to PIR in P7c-2 (section 5). |
| W4 | Kept endpoints | `/api/ta/stats` (dashboard), `/api/ta/watchlist-names` (newsroom), `/api/ta/watchlist/navigator-layer` (Actors tab button), `/api/attack/status`, `/api/attack/sync`, `/api/attack/sync/{domain_key}` (sync card, Data health) and `/api/attack/navigator-layer` stay. Every other TA Room / ATT&CK DB endpoint is removed (section 6). |
| W5 | Spec 7.3 corrections | The exec filter bar has no entity pickers (days, role preview, toggles only): nothing to replace there. PIR had no malware criterion: added by W3. |
| W6 | PR | Open against `main` after #82 merges; merge to `origin/Dev` and test on dev first, with the user's approval. |

## 2. Resolve route

- **API** `GET /api/entities/resolve?type=<entity type>&name=<text>` (permission `view_ta`, like the
  rest of `/api/entities`). Matching, in order: `alias_norm(name)` against `entity_aliases` of that
  type; then case-insensitive `external_id` (CVE id, technique id, ISO country code). Follows
  `merged_into_id` to the live entity. Returns `EntityRef`; 404 when nothing matches. `type` may be
  a comma list (`malware,tool`) for names whose type the caller does not know.
- **Web** `/intelligence/entities/resolve?type=&name=`: client page that calls the API and
  `router.replace`s to `/intelligence/entities/{id}`; on 404 it shows "No entity named X" with a
  link to the list filtered by `q=X` (and "New entity" for `manage_entities`).
- **`EntityChip`** (`components/entities/entity-chip.tsx`): props `type`, `name`, optional `id`,
  optional `label` (display text when it differs from the name, e.g. "T1059 Command and
  Scripting Interpreter"). Renders a type icon + name as a `next/link`; `font-code` for CVE and
  technique ids; theme tokens, 24 px min target. One `EntityChipList` for lists with "+N more".

## 3. Ids added in P7c-2 (additive only)

Additive means a new optional field; no existing field changes type, name or meaning.

| Response | Addition | Feeds |
|---|---|---|
| `ArticleOut` | `entities: list[ArticleEntityRef]` (live mentioned entities, deduped per entity and role; new schema `ArticleEntityRef(EntityRef)` with `role: str \| None` for countries, so other `EntityRef` users are unchanged) | newsroom modal and front section, dashboard must-read, newsletter suggestion, exec sector-heatmap drill |
| `InferredEntity`, `InferredTechnique` | `entity_id: int \| None` | newsroom inferred TTPs |
| trending items (`TrendItemOut`) | `entity_id: int \| None` | dashboard trending card |
| `/api/spikes` items | `entity_id` | early warning |
| `/api/mitre/heatmap` rows and `ttps[]` | `entity_id` | MITRE heatmap and TTP drill |

Each is built from `mention_rows` / ORM mentions that already have the id (inventory), by adding
`entity_id` to the selected columns or `group_by` **next to** the existing name key, so counts
do not change. Snapshot diffs (`test_list_articles`, `test_get_article_by_id`, newsletter) are
reviewed and allowed only for the added keys.

Everything else in 7.3 links through the resolve route: dashboard map/ransomware/CVE/charts, exec
panels, risk matrix, IOC detail, CVE ticket tab, recap, newsletter queue, PIR list, campaign
clusters, diamond model, kill chain, geopolitical.

## 4. Pages

As parent spec 7.1, with these specifics:

- **`/intelligence/entities`**: tabs as `TabPills` with the tab in the URL (`?type=`), search
  `?q=` (aliases, debounced), Watched toggle (`?watched=1`), table columns name (chip), aliases
  (first 3 + count), source, 30 d / 90 d mentions, last seen; cursor paging ("Load more"). Tabs map
  to types: Actors `intrusion-set`, Malware & tools `malware,tool`, Techniques `attack-pattern`,
  Vulnerabilities `vulnerability`, Campaigns `campaign`, Sectors `identity` class, Countries
  `location`, Victims `identity` organization. Actors tab: watchlist Navigator layer button.
  Techniques tab (admin): ATT&CK sync status card (moved from ATT&CK DB). "New entity" dialog for
  `manage_entities`. Suppressed toggle for `manage_entities`.
- **`/intelligence/entities/[id]`**: header (name, type badge, aliases, source, ATT&CK id, Watch
  button for `manage_pir`). If the entity is a tombstone (`merged_into_id`), `router.replace` to
  the target. Tabs (`?tab=`): Overview (description; actors: stored LLM profile with
  Generate/Regenerate for `manage_intel`), Relationships (SRO table both directions with revoke for
  `manage_entities`; "Often mentioned together" with "Make relationship" dialog), Stories,
  Indicators, CVEs (paged tables, limit/offset + total), Timeline (monthly chart), ATT&CK (only for
  actor, malware, tool, technique: techniques, mitigations, Navigator layer download). Actions menu
  for `manage_entities`: Edit (name, description), Aliases (add, remove; 409 message shown),
  Merge (search target of the same type, preview counts from `merge-preview`, confirm), Split
  (pick aliases; the tombstone's own-name alias is pre-selected, Ruling 17; 409 message shown),
  Suppress / Unsuppress.
- **Navigation**: `IntelligenceNav` replaces "ATT&CK DB" and "Threat Actor Room" with one
  "Entities" item.

## 5. PIR malware criterion

- `PIRCriteria.malware: list[str] = []` and `_CRITERIA_KEYS` gain `malware` (JSONB, no migration).
- The article filter gains `malware`, matching mentions of `malware` or `tool` entities through
  `entity_ids_named` (same pattern as `threat_actors`); coverage, PIR article lists, PIR matching
  and the PIR DOCX export use it.
- The PIR form replaces free-text actor/malware/industry/country/TTP inputs with an alias
  autocomplete over `GET /api/entities?type=&q=`; criteria keep storing names (parent 5.1).
  The PIR list shows criteria as `EntityChip`s (resolve route).

## 6. Retired

- Removed web: `app/(app)/intelligence/threat-actor-room`, `app/(app)/intelligence/attack-db`,
  `components/intelligence/threat-actor-room/*`, `components/intelligence/attack-db/*` (the sync
  card moves to `components/entities/`).
- Redirects: `/intelligence/threat-actor-room` -> `/intelligence/entities?type=intrusion-set`,
  `/intelligence/attack-db` -> `/intelligence/entities?type=attack-pattern` (permanent redirects
  in `next.config`, following the Next.js 16 docs in `node_modules/next/dist/docs/`).
- Removed API (only these two pages used them; checked again by grep in the plan, web and
  Python): `/api/ta/groups` (GET, POST), `/api/ta/groups/{id}` (DELETE), `/api/ta/watchlist`
  (GET, POST), `/api/ta/watchlist/{name}` (DELETE), `/api/ta/whitelist` (GET, POST, DELETE),
  `/api/ta/profile/{name}`, `/api/ta/profile/generate`, `/api/ta/{actor}/timeline`,
  `/api/attack/techniques`, `/api/attack/techniques/{attack_id}`, `/api/attack/tactics`,
  `/api/attack/tactics/distinct`, `/api/attack/mitigations`, `/api/attack/groups`,
  `/api/attack/groups/{group_id}`, `/api/attack/software`, `/api/attack/software/{software_id}`,
  with their now-unused service/repository functions, tests and route-permission entries.
  `docs/openapi.json` and `schema.d.ts` regenerated.

## 7. Admin > API tokens

Create form gains scope checkboxes `indicators:read` (default checked) and `intel:read`; the token
list shows the scopes. At least one must be checked (the API already requires `min_length=1`).

## 8. Follow-up (not in P7c-2)

A separate PR after 0.8.11 moves exec aggregates (`ta_leaderboard`, `sector_*`, `top_ttps`,
`ta_velocity`, trends, `industry_spikes`, role-gated cluster actors) and campaign clusters
(`dominant_*`, `attack_techniques`, shared elements, diamond model, kill chain) to carry
`entity_id`, typing those `dict` responses with `response_model` at the same time. Until then those
chips resolve by name, so no link is missing.

## 9. Rules and testing

- Parent 7.4 rules (Base UI `render=`, `SelectItem` children a single string, `items` prop on
  selects with a sentinel default, no `backdrop-blur`, theme tokens, `surface-raised`, `font-code`
  for ids, light + dark, 375 px without page-level horizontal scroll, `useCan` hides actions,
  touched `loose-types.ts` entries replaced by generated types).
- Backend: unit/integration tests for the resolve endpoint (alias, external id, merged follow,
  comma type, 404), the PIR `malware` criterion (filter, coverage, options), the added id fields,
  route-permission entries for removed and added routes; existing snapshots pass with reviewed
  additive diffs.
- Web CI: `pnpm lint`, `pnpm exec next typegen && pnpm exec tsc --noEmit`, `pnpm build`.
- Browser QA on the isolated `qacve` compose project: entity list (every tab, search, watched),
  entity page (every tab), merge/split/suppress/alias dialogs incl. 409 messages, merged redirect,
  resolve route (hit and miss), every touched feature's chips, both redirects, PIR malware
  criterion end to end, API token scopes, analyst vs admin vs a read-only role, light + dark,
  375 px.
- Release: add to the `## [0.8.11]` CHANGELOG entry (Indonesian) and to `docs/prod-upgrade/0.8.11.md`
  + the 0.8.11 section of `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md` (identical): TA Room / ATT&CK DB
  replaced by Entities with redirects, removed endpoints, PIR malware criterion, token scopes.
