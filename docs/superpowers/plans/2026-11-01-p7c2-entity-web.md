# P7c-2 Entity Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the web half of P7c: entity list and entity pages replacing TA Room and ATT&CK DB, one `EntityChip` for every actor/malware/technique/CVE/sector/country/victim name, a PIR malware criterion, and API token scope checkboxes.

**Architecture:** Hybrid linking (spec W1): `EntityChip` links to `/intelligence/entities/{id}` when the response carries an id, otherwise to `/intelligence/entities/resolve?type=&name=`, a client page that calls the new `GET /api/entities/resolve` and redirects. A few backend responses gain additive `entity_id`s (spec section 3). TA Room / ATT&CK DB pages and the endpoints only they used are removed last, once nothing calls them.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, pytest + testcontainers + syrupy; Next.js 16 App Router, React 19, TanStack Query 5, openapi-fetch, shadcn on Base UI, Tailwind 4, lucide-react.

**Spec:** `docs/superpowers/specs/2026-11-01-p7c2-entity-web-design.md` (addendum, decisions W1-W6) on top of section 7 of `docs/superpowers/specs/2026-10-29-p7c-entity-model-design.md`. Visual reference: `docs/superpowers/specs/2026-11-01-p7c2-mockup.html` (approved).

## Global Constraints

- No version bump; release 0.8.11. CHANGELOG addition goes in the existing `## [0.8.11]` entry (Indonesian).
- Additive API changes only: no existing response field changes name, type or meaning.
- Every value that comes from an entity mention carries its `entity_id`; resolving by name is only for text with no entity behind it (W2). New or touched endpoints follow it.
- Base UI: `render={<X/>}` not `asChild`; `SelectItem` children a single string; `items` prop on a `Select` whose default is a sentinel; `DropdownMenuLabel` inside `DropdownMenuGroup`; Base UI `Checkbox` read via `fd.get(name) != null`.
- Visual rules (`apps/web/CLAUDE.md`): one `<h1>` per route (the `PageHeader` of `intelligence/layout.tsx`), so the entity name in the hero is an `<h2>`; `surface-raised` cards; hero band `bg-hero` / `text-hero-*`; `font-code` for ids (CVE, technique, ATT&CK); `text-2xs` floor; tinted badges use `text-X-text`; no hex/rgb/raw palette classes; no `backdrop-blur`; no `opacity-*` on text; focus `focus-visible:ring-3 focus-visible:ring-focus`; inputs labelled; icon-only buttons `aria-label`; `max-sm:h-11` on primary controls; tab switchers use `TabPills`.
- Light and dark mode, 375 px without page-level horizontal scroll (tables scroll inside their own wrapper).
- `useCan(permission)` hides actions: `manage_entities` (edit, aliases, merge, split, suppress, new entity, relationships), `manage_pir` (watch), `manage_intel` (profile generate), admin-only sync card (`useCan("manage_attack")` if that permission exists, else `user.role` admin/superadmin as `data-health-view.tsx` does today).
- Merge/split/alias 409 `detail` strings are English and shown verbatim in the dialog.
- Comments in code mostly Indonesian; docs English; commit messages English conventional ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Node/pnpm: `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"`. Web CI = `pnpm lint`, `pnpm exec next typegen && pnpm exec tsc --noEmit`, `pnpm build` (no web test runner).
- After any endpoint/schema change: `uv run python tools/export_openapi.py` then `cd apps/web && pnpm run gen:api`; commit both.
- Local QA only on compose project `qacve` (`POSTGRES_PORT=55433 REDIS_PORT=56379 docker compose -p qacve up -d postgres redis`), never `deploy-postgres-1`.

## Review Focus

1. A name with no entity behind it (LLM recap actor, typo, unknown ransomware group) → the resolve page shows "No entity named X" with a search link, never a blank page or crash. Pinned in Task 1 (`test_resolve_unknown_404`) and Task 5 (page states).
2. Names with URL-hostile characters (`#play`, `1.php group`, `APT-C-36`, `Cl0p`, `Sandworm/Voodoo Bear`) → chip href is `encodeURIComponent`-safe and resolves. Pinned in Task 1 (`test_resolve_special_chars`) and Task 5 (`entityHref` uses `URLSearchParams`).
3. Country values in v1 responses are ISO codes (`ID`, `RU`) → the chip resolves them through `external_id` and still labels them readably. Pinned in Task 1 (`test_resolve_country_code`).
4. Old bookmarked id of a merged entity → the page redirects to the target instead of showing a tombstone. Pinned in Task 7 (redirect step) and QA in Task 14.
5. A role without `view_ta` or `manage_entities` (custom roles) → actions are hidden and the PIR autocomplete degrades to free-text entry when `/api/entities` returns 403. Pinned in Task 13 (fallback step) and QA in Task 14.

---

### Task 1: Entity API: list filters and resolve endpoint

**Files:**
- Modify: `apps/api/src/cti_api/services/entities.py` (`list_entities`, new `resolve_entity`)
- Modify: `apps/api/src/cti_api/routers/entities.py` (query params; `GET /resolve` declared **before** `GET /{entity_id}`)
- Test: `tests/integration/test_entities_api.py`, `tests/unit/test_route_permissions.py`

**Interfaces:**
- Produces: `GET /api/entities?type=malware,tool&identity_class=class|organization` (comma list; `identity_class` only narrows `identity`); `GET /api/entities/resolve?type=<comma list>&name=<text>` → `EntityRef` (200) or 404 `{"detail": "no entity named <name>"}`; permission `view_ta`.
- Produces (service): `async def resolve_entity(session: AsyncSession, types: Sequence[str], name: str) -> EntityRef | None` in `services/entities.py`.
- Produces: `EntityDetail.merged_from: list[EntityRef] = []` (tombstones whose `merged_into_id` is this entity, newest merge first), filled in `entity_detail`; the Split dialog (Task 8) needs it to know which own-name alias revives which tombstone.

- [ ] **Step 1: Write failing tests** in `test_entities_api.py` (use `entity_support.py` fixtures):
  - `test_list_type_comma_list`: one malware + one tool + one actor; `?type=malware,tool` returns exactly the two.
  - `test_list_identity_class`: a sector (`class`) and a victim (`organization`); `?type=identity&identity_class=organization` returns only the victim.
  - `test_resolve_by_alias`: actor "APT29" with alias "Cozy Bear"; `?type=intrusion-set&name=cozy%20BEAR` → `{"id": <apt29>, "name": "APT29", "type": "intrusion-set"}`.
  - `test_resolve_follows_merge`: merge "Cozy Duke" into APT29; resolving "Cozy Duke" returns APT29.
  - `test_resolve_external_id`: `?type=attack-pattern&name=t1566` → the T1566 entity; `?type=vulnerability&name=cve-2024-3400` → that CVE.
  - `test_resolve_country_code`: location "Indonesia" (`external_id="ID"`); `?type=location&name=id` → Indonesia.
  - `test_resolve_special_chars`: actor "#play"; `?type=intrusion-set&name=%23play` → it.
  - `test_resolve_unknown_404`: `name=nope` → 404, detail `"no entity named nope"`.
  - `test_resolve_suppressed_still_resolves`: a suppressed actor resolves (the page shows it with a "Suppressed" badge).
  - `test_detail_merged_from`: after merging "Cozy Duke" into APT29, `GET /api/entities/{apt29}` has `merged_from == [{"id": <cozy duke>, "name": "Cozy Duke", "type": "intrusion-set", "external_id": None}]`; empty after splitting it back.
  - In `test_route_permissions.py` `_ENTITY_PERMS`: add `("GET", "/api/entities/resolve"): "view_ta"`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_entities_api.py -k "comma or identity_class or resolve" tests/unit/test_route_permissions.py -q` → FAIL.
- [ ] **Step 3: Implement.** `list_entities`: `type` split on `,` into `Entity.type.in_(...)`; `identity_class: str | None` filter. `resolve_entity`: first `entity_ids_named(types, [name])` without the `live_entity()` suppressed clause (merged aliases already moved, spec 3.4; suppressed must still resolve), then live-or-merged `Entity.external_id` case-insensitive match following `merged_into_id` to the live end; return `_ref(entity)`. Router validates every `type` against `ENTITY_TYPES` (422 otherwise).
- [ ] **Step 4: Run** the same command → PASS; `uv run ruff check . && uv run mypy packages/cti-core/src packages/cti-scraper/src` clean.
- [ ] **Step 5: Regenerate contract** (`uv run python tools/export_openapi.py`, `pnpm run gen:api`) and **commit** `feat(api): entity resolve endpoint and list type filters`.

### Task 2: Additive entity ids in v1 responses

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/entity.py` (`NameKeys.entity_id`)
- Modify: `apps/api/src/cti_api/schemas/article.py` (`ArticleEntityRef`, `ArticleOut.entities`, `InferredEntity.entity_id`, `InferredTechnique.entity_id`), `apps/api/src/cti_api/routers/articles.py` (`_serialize`), `apps/api/src/cti_api/services/inferred_ttps.py`
- Modify: `apps/api/src/cti_api/schemas/dashboard_overview.py` (`TrendItemOut.entity_id`), `apps/api/src/cti_api/services/trending.py`, `apps/api/src/cti_api/services/spike.py`, `packages/cti-core/src/cti_core/db/repositories/mitre.py`
- Test: `tests/integration/test_articles_router_snapshot.py` (+ snapshots), `tests/integration/test_inferred_ttps.py`, `tests/integration/test_mitre_query.py`, new `tests/integration/test_entity_ids_in_v1.py`

**Interfaces:**
- Produces: `NameKeys.entity_id(name: str) -> int | None`.
- Produces: `class ArticleEntityRef(EntityRef): role: str | None = None`; `ArticleOut.entities: list[ArticleEntityRef] = []` (one per live mentioned entity and role, in mention order); `InferredEntity.entity_id: int | None = None`; `InferredTechnique.entity_id: int | None = None`; `TrendItemOut.entity_id: int | None = None`; `/api/spikes` items gain `"entity_id": int | None`; `/api/mitre/heatmap` `rows` stay `list[str]` and gain sibling `row_ids: list[int | None]` (same order), `ttps[]` items gain `"entity_id"`.
- Counts never change: ids are looked up **after** aggregation with one `name_keys_async` (names) or one `external_id IN (...)` query (technique ids) per response, never added to a `GROUP BY`.

- [ ] **Step 1: Write failing tests** in `test_entity_ids_in_v1.py`: seed one article mentioning APT29, WellMess, T1566, Government, Indonesia (victim):
  - `test_article_out_entities`: `GET /api/articles/{id}` → `entities` contains `{"id": apt29, "type": "intrusion-set", "name": "APT29", "role": None}` and the Indonesia ref with `"role": "victim"`; every old field unchanged.
  - `test_trending_entity_id`, `test_spikes_entity_id`, `test_mitre_row_ids_and_ttp_ids`: the APT29/T1566 items carry the right ids; counts equal the values before the change (assert against the existing expected numbers in those tests).
  - In `test_inferred_ttps.py`: `test_inferred_entity_and_technique_ids`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_entity_ids_in_v1.py tests/integration/test_inferred_ttps.py -q` → FAIL.
- [ ] **Step 3: Implement** the fields above. `_serialize` builds `entities` from `article.mentions` already loaded (no extra query).
- [ ] **Step 4: Run** the step 2 command → PASS. Then `uv run pytest tests/integration/test_articles_router_snapshot.py tests/integration/test_mitre_router_snapshot.py tests/integration/test_filtered_articles_router_snapshot.py --snapshot-update -q`, and **review the snapshot diff**: only added `entities` / `entity_id` / `row_ids` keys allowed. Run the newsletter snapshot tests the same way (`-k newsletter`).
- [ ] **Step 5: Regenerate contract and commit** `feat(api): add entity ids to article, trending, spike and MITRE responses`.

### Task 3: PIR malware criterion

**Files:**
- Modify: `apps/api/src/cti_api/schemas/pir.py` (`PIRCriteria.malware`, `PIROptions.malware`), `packages/cti-core/src/cti_core/db/repositories/pir.py` (`_CRITERIA_KEYS`, `_criteria_filters`, `get_options`), `packages/cti-core/src/cti_core/db/repositories/article.py` (`_apply_list_filters`, `list_articles`, the count path), `apps/api/src/cti_api/services/pir_docx.py` (criteria row "Malware and tools")
- Test: `tests/integration/test_pir_query.py`, `tests/integration/test_pir_alias_match.py`, `tests/integration/test_pir_router_snapshot.py` (+ snapshot)

**Interfaces:**
- Produces: `PIRCriteria.malware: list[str] = []`; `_apply_list_filters(..., malware: Sequence[str] | None = None)` matching `_mentioning` over `entity_ids_named(("malware", "tool"), malware)`; `AsyncArticleRepo.list_articles(..., malware=...)` and its count twin; `PIROptions.malware: list[str]` (distinct live malware/tool names, same source as `threat_actors`).

- [ ] **Step 1: Write failing tests**:
  - `test_pir_query.py::test_malware_criterion_matches_malware_and_tool`: article A mentions tool "Cobalt Strike" (body only, not title), article B mentions malware "Lumma Stealer", C neither; PIR `{"malware": ["cobalt strike", "Lumma"]}` where "Lumma" is an alias of "Lumma Stealer" → A and B, not C; coverage counts 2.
  - `test_pir_alias_match.py::test_malware_criterion_via_alias`: alias hit counted like actors.
  - `test_pir_query.py::test_old_pir_without_malware_key_unchanged`: criteria JSON without the key returns the same set as before.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_pir_query.py tests/integration/test_pir_alias_match.py -q` → FAIL.
- [ ] **Step 3: Implement** as in Interfaces; the PIR alert path inherits it through `_criteria_filters` (no worker change).
- [ ] **Step 4: Run** → PASS; `test_pir_router_snapshot.py --snapshot-update`, diff shows only `malware` keys.
- [ ] **Step 5: Regenerate contract and commit** `feat(pir): malware and tool criterion`.

### Task 4: EntityChip, entity type metadata and the resolve page

**Files:**
- Create: `apps/web/src/lib/entities/types.ts`, `apps/web/src/components/entities/entity-chip.tsx`, `apps/web/src/app/(app)/intelligence/entities/resolve/page.tsx`, `apps/web/src/components/entities/entity-resolve-view.tsx`

**Interfaces:**
- Produces (`lib/entities/types.ts`):
  - `type EntityType = "intrusion-set" | "malware" | "tool" | "attack-pattern" | "vulnerability" | "campaign" | "identity" | "location"`
  - `const ENTITY_TABS: readonly { key: string; label: string; types: EntityType[]; identityClass?: "class" | "organization" }[]` in spec order: Actors, Malware & tools, Techniques, Vulnerabilities, Campaigns, Sectors, Countries, Victims (keys `actors, malware, techniques, vulnerabilities, campaigns, sectors, countries, victims`).
  - `function entityTypeMeta(type: string, identityClass?: string | null): { label: string; Icon: LucideIcon; colorClass: string }` (icons/colours from the mockup: actor `Skull` `text-chart-4`, malware `Bug` / tool `Wrench` `text-chart-3`, technique `Crosshair` `text-chart-1`, vulnerability `ShieldAlert` `text-severity-critical-text`, campaign `Flag` `text-chart-9`, sector `Landmark` / victim `Building2` `text-chart-2`, country `Globe` `text-chart-5`).
  - `function entityHref(ref: { id?: number | null; type: string; name: string }): string` → `/intelligence/entities/${id}` or `/intelligence/entities/resolve?${new URLSearchParams({ type, name })}`.
- Produces (`entity-chip.tsx`): `EntityChip({ type, name, id?, label?, className? })` (a `next/link`, one line, `min-w-0` truncating label, `aria-label="<type label> <name>"`, `font-code` when type is technique/vulnerability or `label` starts with an id) and `EntityChipList({ items: {type,name,id?,label?}[], max?: number = 6 })` with an operable "+N more" button that expands in place.
- Produces (resolve page): reads `type`, `name`; calls `api.GET("/api/entities/resolve")`; on 200 `router.replace(/intelligence/entities/{id})`; on 404 shows "No entity named {name}", a link to `/intelligence/entities?tab=<tab of type>&q=<name>` and, with `manage_entities`, a "New entity" link prefilled (`?new=1&type=&name=`); loading skeleton meanwhile.

- [ ] **Step 1: Implement the three files** per Interfaces and the mockup section A.
- [ ] **Step 2: Verify**: `pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit` pass.
- [ ] **Step 3: Commit** `feat(web): EntityChip and entity resolve page`.

### Task 5: Entities list page

**Files:**
- Create: `apps/web/src/app/(app)/intelligence/entities/page.tsx`, `apps/web/src/components/entities/entities-list-view.tsx`, `apps/web/src/components/entities/entity-create-dialog.tsx`, `apps/web/src/components/entities/attack-sync-card.tsx` (moved from `components/intelligence/attack-db/sync-status-cards.tsx`, same endpoints `/api/attack/status`, `/api/attack/sync`, `/api/attack/sync/{domain_key}`)
- Modify: `apps/web/src/components/intelligence/intelligence-nav.tsx` (replace "ATT&CK DB" and "Threat Actor Room" with `{ href: "/intelligence/entities", label: "Entities" }`, active for any `/intelligence/entities*` path), `apps/web/next.config.ts` (`redirects()`: `/intelligence/threat-actor-room` → `/intelligence/entities?tab=actors`, `/intelligence/attack-db` → `/intelligence/entities?tab=techniques`, `permanent: true`; read `node_modules/next/dist/docs/` for the Next 16 `redirects` shape first)

**Interfaces:**
- Consumes: Task 1 list params, Task 4 `ENTITY_TABS`, `EntityChip`, `entityTypeMeta`.
- URL state: `tab`, `q` (debounced 300 ms), `watched=1`, `suppressed=1`; `?new=1&type=&name=` opens the create dialog prefilled.
- Table: name chip + `external_id` (`font-code`), aliases (first 3 + "+N"), source, 30 d with trend arrow (`mentions_30d` vs `mentions_90d / 3`: up when ≥ 10 % higher, down when ≥ 10 % lower, else none), 90 d, last seen (relative), Watch button (`PUT/DELETE /api/entities/{id}/watch`, `manage_pir`). Cursor paging ("Load more" with `next_cursor`). Below 640 px rows render as cards (mockup F).
- Actors tab: "Watchlist Navigator layer" button downloading `/api/ta/watchlist/navigator-layer`. Techniques tab: `AttackSyncCard` for admins.
- Create dialog (`manage_entities`): type select (`items` prop), name, aliases (comma separated), description, `external_id` required for technique; `POST /api/entities`; 409/422 detail shown.

- [ ] **Step 1: Implement** per Interfaces and mockup B.
- [ ] **Step 2: Verify** lint + typegen + tsc pass; `pnpm build` passes.
- [ ] **Step 3: Commit** `feat(web): entities list page and nav`.

### Task 6: Entity page shell, header and Overview

**Files:**
- Create: `apps/web/src/app/(app)/intelligence/entities/[id]/page.tsx`, `apps/web/src/components/entities/entity-view.tsx`, `apps/web/src/components/entities/entity-hero.tsx`, `apps/web/src/components/entities/entity-overview-tab.tsx`, `apps/web/src/components/entities/entity-timeline-chart.tsx`

**Interfaces:**
- Consumes: `GET /api/entities/{id}`, `/stories|/indicators|/cves?limit=1` (for `total` KPIs), `/timeline`, `POST /api/entities/{id}/profile` (`manage_intel`, actors only), `MindmapWidget featureType="threat_actor" docId={entity.name}` for actors (kept from TA Room).
- Produces: `EntityView({ id }: { id: number })` with tab state `?tab=overview|relationships|stories|indicators|cves|timeline|attack` (ATT&CK tab only for `intrusion-set`, `malware`, `tool`, `attack-pattern`); slots used by Tasks 7-8: `EntityRelationshipsTab`, `EntityStoriesTab`, `EntityIndicatorsTab`, `EntityCvesTab`, `EntityAttackTab` (each `{ entity: EntityDetail }`), and `EntityActionsMenu` (Task 8).
- Hero (mockup C): `bg-hero` band, eyebrow type + `external_id`, name as `<h2>`, aliases (+N disclosure), sources, first seen, Suppressed badge when `suppressed`, Watch button, five KPIs (30 d mentions, stories total, indicators total, CVEs total, last seen).
- Overview: description; actors: stored profile fields rendered with chips (by name → resolve) and Generate/Regenerate; timeline bar chart (12 months, Chart.js via the existing `chart-theme.ts` tokens).

- [ ] **Step 1: Implement** shell + hero + overview; a 404 shows "Entity not found"; when `merged_into_id` is set, `router.replace` to `/intelligence/entities/{merged_into_id}` keeping `tab`.
- [ ] **Step 2: Verify** lint + typegen + tsc pass.
- [ ] **Step 3: Commit** `feat(web): entity page header and overview`.

### Task 7: Entity page data tabs

**Files:**
- Create: `apps/web/src/components/entities/entity-relationships-tab.tsx`, `apps/web/src/components/entities/relationship-create-dialog.tsx`, `apps/web/src/components/entities/entity-stories-tab.tsx`, `apps/web/src/components/entities/entity-indicators-tab.tsx`, `apps/web/src/components/entities/entity-cves-tab.tsx`, `apps/web/src/components/entities/entity-attack-tab.tsx`

**Interfaces:**
- Consumes: `/relationships` (SROs + `co_mentions`), `POST /api/relationships` (`RelationshipCreate`: `source_id`, `relationship_type` from `RELATIONSHIP_TYPES` in the schema enum, `target_id`, `confidence` default 75, `description`), `DELETE /api/relationships/{id}` (revoke, confirm dialog), `/stories|/indicators|/cves` with `limit`/`offset` (`SimplePager`, 25 per page), `/attack` (techniques, mitigations, Navigator layer JSON download as `<entity name>-layer.json`).
- Relationships: table both directions (relationship verb, other end as chip; indicator sources as `font-code` value), provenance badge, confidence, created by; Revoke only for `provenance == "analyst"` and `manage_entities`. "Often mentioned together" list with a strength meter (`stories / max stories`) and "Relate" opening the create dialog prefilled.
- Stories/Indicators/CVEs tables link to the existing newsroom article, IOC detail dialog and CVE modal respectively.

- [ ] **Step 1: Implement** per Interfaces and mockup C/D.
- [ ] **Step 2: Verify** lint + typegen + tsc pass.
- [ ] **Step 3: Commit** `feat(web): entity relationships, stories, indicators, CVEs and ATT&CK tabs`.

### Task 8: Entity actions (edit, aliases, merge, split, suppress)

**Files:**
- Create: `apps/web/src/components/entities/entity-actions-menu.tsx`, `entity-edit-dialog.tsx`, `entity-aliases-dialog.tsx`, `entity-merge-dialog.tsx`, `entity-split-dialog.tsx` (all under `apps/web/src/components/entities/`)

**Interfaces:**
- Consumes: `PATCH /api/entities/{id}` (`name`, `description`, `suppressed`), `POST /api/entities/{id}/aliases`, `DELETE /api/entities/{id}/aliases/{alias_id}`, `GET /api/entities/{id}/merge-preview?into_id`, `POST /api/entities/{id}/merge` `{into_id}`, `POST /api/entities/{id}/split` `{alias_ids}`.
- Menu items (mockup C): Edit name and description, Manage aliases, Merge into another …, Split aliases, one "Undo merge of {name}" per `merged_from` (Task 1), separator, Suppress / Unsuppress (confirm dialog). Whole menu hidden without `manage_entities`.
- Merge: target search over `GET /api/entities?type=<same type>&q=` excluding self; preview counts (`moved_aliases`, `moved_mentions`, `moved_relationships`, `moved_watches`, `moved_profile`); button "Merge into {target}"; on success navigate to the target.
- Split: alias list with checkboxes. The Actions menu has one "Undo merge of {name}" item per `merged_from` tombstone; it opens the Split dialog with that tombstone's own-name alias (the alias equal to its name after trim, lower-case and space collapse; technique: its `external_id`) pre-checked and labelled "Required to bring back {name}" (Ruling 17). Plain "Split aliases" pre-checks nothing. Result navigates to the returned entity. Any 409 `detail` (e.g. `reviving entity N requires its own name alias in the split`) is shown in red inside the dialog.
- After any action: invalidate `["entity", id]` and `["entities"]` queries; toast on success.

- [ ] **Step 1: Implement** per Interfaces and mockup D.
- [ ] **Step 2: Verify** lint + typegen + tsc pass.
- [ ] **Step 3: Commit** `feat(web): entity edit, alias, merge, split and suppress actions`.

### Task 9: EntityChip where responses carry ids

**Files:**
- Modify: `apps/web/src/components/newsroom/article-modal.tsx`, `apps/web/src/components/newsroom/front-section.tsx`, `apps/web/src/components/newsroom/inferred-ttps-section.tsx`, `apps/web/src/components/dashboard/overview-cards.tsx` (must-read, trending), `apps/web/src/components/intelligence/early-warning-view.tsx`, `apps/web/src/components/intelligence/mitre/mitre-heatmap-view.tsx`, `apps/web/src/components/intelligence/mitre/ttp-drill-dialog.tsx`, `apps/web/src/components/newsletter/newsletter-queue-panel.tsx`, `apps/web/src/components/exec/sector-heatmap.tsx` (drill list)
- Modify: `apps/web/src/lib/api/loose-types.ts` (spike and MITRE types gain the id fields; drop entries now covered by generated types where touched)

**Interfaces:**
- Consumes: Task 2 fields; ids looked up from `article.entities` by `(type, name)` (countries by `external_id` ISO code, labelled with `lib/countries.ts` names). Newsletter queue items from `localStorage` without `entities` fall back to name chips (resolve).

- [ ] **Step 1: Replace** plain names/badges with `EntityChip`/`EntityChipList` in each file.
- [ ] **Step 2: Verify** lint + typegen + tsc + build pass.
- [ ] **Step 3: Commit** `feat(web): entity chips in newsroom, dashboard, early warning, MITRE and newsletter`.

### Task 10: EntityChip by name (resolve) in the remaining features

**Files:**
- Modify: `apps/web/src/components/dashboard/signal-hero.tsx`, `apps/web/src/components/dashboard/overview-cards.tsx` (ransomware, CVE cards), `apps/web/src/app/(app)/dashboard/page.tsx` (top industries/TTPs/actors), `apps/web/src/components/exec/ta-leaderboard.tsx`, `sector-risk.tsx`, `sector-actor-matrix.tsx`, `tier2-panels.tsx`, `charts-section.tsx`, `role-gated-panels.tsx`, `sector-heatmap.tsx` (sector labels), `apps/web/src/components/intelligence/risk-matrix-view.tsx`, `apps/web/src/components/intelligence/ioc/ioc-detail-dialog.tsx`, `apps/web/src/components/cve/cve-detail-modal.tsx`, `apps/web/src/components/cve/cve-ticketing-view.tsx`, `apps/web/src/components/recap/recap-view.tsx`, `apps/web/src/components/recap/recap-quality.tsx`, `apps/web/src/components/intelligence/campaign-clusters/campaigns-panel.tsx`, `campaign-expanded-panel.tsx`, `diamond-model-view.tsx`, `kill-chain-view.tsx`, `geopolitical-panel.tsx`, `apps/web/src/components/intelligence/pir/pir-list.tsx`, `apps/web/src/components/intelligence/campaign-clusters/cluster-pir-dialog.tsx`

**Interfaces:**
- Consumes: Task 4 `EntityChip` with `{ type, name }` only. Chart axis labels stay plain text (a chart label is not a link); the chip goes in the adjacent list/legend/tooltip-free table cell. Free text that is clearly not a name (e.g. recap `notable_cves` entries with prose) renders a chip only for the extracted `CVE-\d{4}-\d+` match.

- [ ] **Step 1: Replace** names in each file; keep layouts and charts as they are.
- [ ] **Step 2: Verify** lint + typegen + tsc + build pass.
- [ ] **Step 3: Commit** `feat(web): entity chips in exec, risk matrix, IOC, CVE, recap, clusters and PIR list`.

### Task 11: PIR form autocomplete and API token scopes

**Files:**
- Create: `apps/web/src/components/entities/entity-autocomplete.tsx`
- Modify: `apps/web/src/components/intelligence/pir/pir-form-dialog.tsx`, `apps/web/src/components/admin/api-tokens-section.tsx`

**Interfaces:**
- Produces: `EntityAutocomplete({ label, types: string[], identityClass?, value: string[], onChange(names: string[]) })`: token input; suggestions from `GET /api/entities?type=&q=&limit=8` (debounced 250 ms) showing the canonical name and, when the match was an alias, "matches “{alias}”"; Enter adds the typed text as-is (free text) so names without an entity and roles without `view_ta` (403 → suggestions hidden, help text "Suggestions unavailable for your role") still work.
- PIR form fields: Threat actors (`intrusion-set`), **Malware and tools** (`malware,tool`, new, `PIRCriteria.malware`), Industries (`identity` + `class`), Countries (`location`), TTPs (`attack-pattern`, stores the technique id), Keywords and News types unchanged. Saved criteria stay names (TTPs stay ids).
- API tokens create form: two Base UI checkboxes `indicators:read` (default checked) and `intel:read` with the help texts from mockup E; at least one required (inline error); `scopes` sent in the create body; the token list shows scopes as `font-code` badges.

- [ ] **Step 1: Implement** per Interfaces.
- [ ] **Step 2: Verify** lint + typegen + tsc pass.
- [ ] **Step 3: Commit** `feat(web): PIR entity autocomplete with malware criterion; API token scopes`.

### Task 12: Retire TA Room and ATT&CK DB

**Files:**
- Delete: `apps/web/src/app/(app)/intelligence/threat-actor-room/`, `apps/web/src/app/(app)/intelligence/attack-db/`, `apps/web/src/components/intelligence/threat-actor-room/`, `apps/web/src/components/intelligence/attack-db/`
- Modify: `apps/api/src/cti_api/routers/ta_groups.py`, `apps/api/src/cti_api/routers/attack.py` (remove the routes listed in spec section 6; keep `/api/ta/stats`, `/api/ta/watchlist-names`, `/api/ta/watchlist/navigator-layer`, `/api/attack/status`, `/api/attack/sync`, `/api/attack/sync/{domain_key}`, `/api/attack/navigator-layer`), plus service/repository/schema functions left unused (find with grep; list the removed names in the commit body)
- Modify tests: `tests/integration/test_ta_groups_router_snapshot.py`, `tests/integration/test_attack_router_snapshot.py` (drop removed-route cases and their snapshots), `tests/integration/test_api_permissions.py:46`, `tests/unit/test_qa_2026_10_05_regressions.py:100-101`, `tests/unit/test_route_permissions.py` (removed routes)

- [ ] **Step 1: Grep gate**: `grep -rn "/api/ta/\(groups\|watchlist\b\|watchlist/{\|whitelist\|profile\|{actor}\)\|/api/attack/\(techniques\|tactics\|mitigations\|groups\|software\)" apps packages tests docs/openapi.json --include=*` shows only the files being changed. Any other hit stops the task and is reported.
- [ ] **Step 2: Delete and modify** the files above.
- [ ] **Step 3: Run** `uv run pytest tests/unit tests/contract packages -q` and `uv run pytest tests/integration/test_ta_groups_router_snapshot.py tests/integration/test_attack_router_snapshot.py tests/integration/test_api_permissions.py tests/integration/test_data_health_api.py -q` → PASS; ruff + mypy clean.
- [ ] **Step 4: Regenerate contract**; `pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build` → PASS (proves no web caller left).
- [ ] **Step 5: Commit** `refactor!: retire TA Room and ATT&CK DB pages and their endpoints`.

### Task 13: Release notes and docs

**Files:**
- Modify: `CHANGELOG.md` (`## [0.8.11]`, Indonesian: halaman Entities menggantikan TA Room dan ATT&CK DB dengan redirect; chip entitas di seluruh aplikasi; kriteria PIR malware dan tool; checkbox scope token API; endpoint lama yang dihapus), `docs/prod-upgrade/0.8.11.md` and the 0.8.11 section of `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md` (identical text: removed endpoints, redirects, no new `.env` key, after-deploy check: open an entity page, a chip from Newsroom, the two redirects, a PIR with a malware criterion), `docs/ARCHITECTURE.md` (web section: entity pages, `EntityChip`, resolve route, W2 rule)

- [ ] **Step 1: Write** the four edits; `diff <(sed -n '/## 0.8.11/,$p' docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md) docs/prod-upgrade/0.8.11.md` shows the sections match (adjust the pattern to the actual heading).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_changelog*.py -q` (header parser) → PASS.
- [ ] **Step 3: Commit** `docs: P7c-2 release notes and runbook`.

### Task 14: Browser QA on qacve and final verification

- [ ] **Step 1: Bring up** `qacve` Postgres/Redis, `alembic upgrade head`, seed via the existing dev-seed path (or a `pg_dump` of dev restored, as in P7c-1), run `uvicorn cti_api.main:app` and `pnpm dev`.
- [ ] **Step 2: Walk the QA list** from spec section 9 as admin, analyst and a read-only custom role (no `manage_entities`, no `view_ta`), in light and dark, at 1440 px and 375 px: entity list (every tab, search by alias, Watched, suppressed), entity page (every tab, KPIs, profile generate), merge with preview, split (own-name alias pre-checked; unchecking shows the 409 text), alias add 409, suppress, merged-id redirect, resolve hit/miss/special characters/country code, both redirects, every Task 9/10 feature's chips, PIR malware criterion end to end (create PIR, see matching articles), API token scopes create. Record findings in the shared notes folder (`p7c2-qa.md`) and fix each in its owning task's files with a `fix(web): ...` commit.
- [ ] **Step 3: Full suite**: `uv run pytest tests/unit tests/contract packages -q`, `uv run pytest tests/integration -q` (background, ~7 min), ruff, mypy, web lint/typegen/tsc/build; API contract drift check (`git diff --exit-code docs/openapi.json apps/web/src/lib/api/schema.d.ts` after regenerating).
- [ ] **Step 4: Tear down** `docker compose -p qacve down -v`.
