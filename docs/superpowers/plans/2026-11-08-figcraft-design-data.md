# FigCraft design data (0.8.15) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the three missing data sources from the FigCraft mockup (PIR weekly coverage, Early Warning daily series, heatmap-scoped Navigator layer) and align small design-system rules in the web app.

**Architecture:** Repository functions in `cti_core` (mypy strict) do the queries; thin FastAPI routers build Pydantic models; pure helpers (window maths, zero-fill, layer building) are unit-tested without a DB, endpoints are covered by testcontainers integration tests.

**Tech Stack:** Python 3.12, SQLAlchemy async, FastAPI/Pydantic v2, pytest + syrupy, Next.js 16 + Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-08-figcraft-design-data-design.md`

## Global Constraints

- Release 0.8.15; no migration, no new `.env` keys.
- Comments/docstrings Indonesian (match surrounding code); commit messages English conventional; docs English; `CHANGELOG.md` and `docs/PROGRESS.md` Indonesian.
- Ruff line length 100; mypy strict on `packages/cti-core/src` and `packages/cti-scraper/src`.
- After any endpoint/schema change: `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api`.
- pnpm/node come from fnm (not on PATH by default; see memory `local-dev-tooling-path`).
- Existing outputs must not change when new optional params are absent (navigator endpoints, existing spike fields).

## Review Focus

1. PIR with `start_date` in the future → `weeks: []`, 200 not 500 (Task 1 `test_window_future_start`).
2. PIR with `end_date` in the past → window ends at `end_date`, not today (Task 1 `test_window_past_end`).
3. Spike entity with no rows on some days → zeros in the series, length == `len(dates)` (Task 2 `test_daily_zero_fill`).
4. Heatmap with no rows/techniques (empty DB or narrow filter) → valid layer with `techniques: []` and `maxValue` ≥ 1 (Navigator rejects max 0) (Task 3 `test_heatmap_layer_empty`).
5. Heatmap column whose ID is not `T…` (bad LLM output) → excluded from the layer (Task 3 `test_heatmap_layer_skips_non_t_ids`).

---

### Task 1: PIR weekly coverage

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/pir.py` (add `weekly_window`, `AsyncPIRRepo.weekly_coverage`)
- Modify: `apps/api/src/cti_api/schemas/pir.py` (add `PIRWeekCount`, `PIRWeeklyCoverage`)
- Modify: `apps/api/src/cti_api/routers/pir.py` (add route; declare BEFORE any conflicting `/{pir_id}` routes — none use `/coverage` today)
- Test: `tests/unit/test_pir_weekly_window.py` (new), `tests/integration/test_pir_query.py`, `tests/integration/test_pir_router_snapshot.py`

**Interfaces:**
- Produces: `weekly_window(start_date: date | None, end_date: date | None, today: date, weeks: int) -> tuple[date, date] | None` — returns `(since_monday, until)` or `None` when `since > until`.
- Produces: `AsyncPIRRepo.weekly_coverage(pir: PIRRequirement, *, weeks: int, today: date) -> tuple[date, date, list[tuple[date, int]]] | None` — every Monday from `since` to Monday-of-`until`, zero-filled, ascending.
- Produces: `GET /api/pir/{pir_id}/coverage/weekly?weeks=26` (`ge=1, le=52`) → `PIRWeeklyCoverage{pir_id:int, since:str|None, until:str|None, weeks:list[PIRWeekCount{week_start:str, count:int}]}` (ISO dates as strings, like the rest of `PIROut`).

- [ ] **Step 1: Unit tests for the window** (`today = date(2026, 11, 8)`, a Sunday; Monday of that week is 2026-11-02)
  - `test_window_from_start_date`: `weekly_window(date(2026,9,1), None, today, 26) == (date(2026,8,31), today)`
  - `test_window_capped_by_weeks`: `weekly_window(date(2025,1,1), None, today, 4) == (date(2026,10,12), today)`
  - `test_window_no_start`: `weekly_window(None, None, today, 2) == (date(2026,10,26), today)`
  - `test_window_past_end`: `weekly_window(date(2026,9,1), date(2026,9,30), today, 26) == (date(2026,8,31), date(2026,9,30))`
  - `test_window_future_start`: `weekly_window(date(2026,12,1), None, today, 26) is None`
- [ ] **Step 2:** `uv run pytest tests/unit/test_pir_weekly_window.py -q` → FAIL (ImportError).
- [ ] **Step 3:** Implement `weekly_window` (Monday = `d - timedelta(days=d.weekday())`; floor = Monday(until) − (weeks−1)·7 days).
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Integration test** `test_weekly_coverage_counts_matches_per_week` in `test_pir_query.py`: seed with `_seed_articles`, PIR `{"threat_actors": ["Apt41"]}` no dates, `weekly_coverage(pir, weeks=12, today=date.today())` → 12 entries, sum of counts == 2 (a1 at today−2d and a2 at today−60d are both inside 12 weeks), the week of `today−60d` has count 1, the unrelated article is never counted. Plus `test_weekly_coverage_future_start_returns_none`.
- [ ] **Step 6:** Implement `weekly_coverage`: `_apply_list_filters(select(Article), posted_on_start=since, posted_on_end=<until+1 day, exclusive>, …criteria…)` then `with_only_columns(func.date_trunc('week', Article.posted_on).cast(Date), func.count(distinct(Article.id))).group_by(1)`; zero-fill in Python. Check `_apply_list_filters` end semantics (exclusive vs inclusive) and pass accordingly.
- [ ] **Step 7:** Router + schemas; integration test in `test_pir_router_snapshot.py`: `test_pir_weekly_coverage` (200, `len(weeks) == weeks param or fewer`, 404 for unknown id, 422 for `weeks=0`).
- [ ] **Step 8:** `uv run pytest tests/unit/test_pir_weekly_window.py tests/integration/test_pir_query.py tests/integration/test_pir_router_snapshot.py -q` → PASS; mypy on cti-core clean.
- [ ] **Step 9:** Commit `feat(pir): weekly coverage endpoint for the PIR coverage chart`.

### Task 2: Early Warning daily series + typed response

**Files:**
- Modify: `apps/api/src/cti_api/services/spike.py` (add `_daily_series`, include `daily`)
- Create: `apps/api/src/cti_api/schemas/spike.py` (`EntitySpike`, `OverallSpike`, `SpikeDaily`, `SpikeParameters`, `SpikesResponse`)
- Modify: `apps/api/src/cti_api/routers/intelligence.py` (`response_model=SpikesResponse`)
- Test: `tests/unit/test_spike_daily.py` (new), `tests/integration/test_intelligence_router_snapshot.py` (add normalizer `r"daily\.dates\.\d+$": (str,)`, update snapshot)

**Interfaces:**
- Produces: `_daily_series(raw: list[tuple[date, str, int]], entities: Iterable[str], start: date, end: date) -> dict[str, list[int]]` and `_date_axis(start: date, end: date) -> list[date]` (inclusive).
- Produces: response key `daily: {dates: list[str], threat_actors: dict[str, list[int]], countries: dict[str, list[int]], industries: dict[str, list[int]], overall: list[int]}`.
- Check whether `exec_dashboard` or others call `_detect_entity_spikes`/`get_spikes` and rely on the dict shape (`grep -rn "spike" apps/api/src`); `get_spikes` keeps returning a dict.

- [ ] **Step 1: Unit tests**
  - `test_daily_zero_fill`: raw `[(d1,"A",3),(d3,"A",1),(d2,"B",5)]`, entities `["A"]`, start d1, end d3 → `{"A": [3, 0, 1]}` ("B" excluded).
  - `test_date_axis_inclusive`: `len(_date_axis(d, d + 29 days)) == 30`.
  - `test_spikes_response_model_accepts_service_shape`: build a dict like `_compute_spikes` output (one actor spike with `entity_id=None`, empty overall, a `daily` block) → `SpikesResponse.model_validate(d).model_dump() == d`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement helpers + schemas; in `_compute_spikes` build `daily` with axis `cutoff..today`, entities = names in each spike list, `overall` from `daily_total`.
- [ ] **Step 4:** Unit tests PASS.
- [ ] **Step 5:** Add normalizer line to `_NORMALIZE`, run `uv run pytest tests/integration/test_intelligence_router_snapshot.py --snapshot-update -q`, inspect the `.ambr` diff: only a new `daily` block (old keys unchanged).
- [ ] **Step 6:** Commit `feat(intelligence): daily series per spiking entity in /api/spikes`.

### Task 3: Navigator layer from the heatmap

**Files:**
- Modify: `packages/cti-core/src/cti_core/db/repositories/mitre.py` (add `_layer_envelope`, `build_heatmap_layer`, `AsyncMitreHeatmapRepo.get_heatmap_navigator_layer`)
- Modify: `apps/api/src/cti_api/routers/mitre.py` (optional `top_rows`, `top_ttps`, `ttp_source` on both navigator routes)
- Modify: `apps/web/src/components/intelligence/mitre/mitre-heatmap-view.tsx` (export passes filters; filename)
- Test: `tests/unit/test_mitre_heatmap_layer.py` (new), `tests/integration/test_mitre_router_snapshot.py`

**Interfaces:**
- Produces: `build_heatmap_layer(heatmap: dict[str, Any], *, view: str, days: int) -> dict[str, Any]` (pure; input = `get_heatmap` output).
- Produces: `get_heatmap_navigator_layer(*, view: str, days: int, top_rows: int, top_ttps: int, ttp_sources: Sequence[str] | None) -> dict[str, Any]`.
- `get_navigator_layer` keeps its exact output (refactor to `_layer_envelope` must keep the snapshot identical).

- [ ] **Step 1: Unit tests** with heatmap `{"rows": ["LockBit", "APT41"], "ttps": [{"id":"T1486","name":"Data Encrypted"},{"id":"T1190","name":"Exploit"}], "matrix": [[22,5],[0,18]], ...}`:
  - `test_heatmap_layer_scores_are_column_sums`: scores `{"T1486": 22, "T1190": 23}`.
  - `test_heatmap_layer_comment_lists_nonzero_rows_desc`: T1190 comment `"APT41: 18, LockBit: 5"`; T1486 `"LockBit: 22"`.
  - `test_heatmap_layer_gradient_max`: `gradient == {"colors": [...same as today...], "minValue": 0, "maxValue": 23}`.
  - `test_heatmap_layer_skips_non_t_ids`: column id `"X999"` absent from techniques.
  - `test_heatmap_layer_empty`: empty heatmap → `techniques == []`, `maxValue == 1`.
  - `metadata == [{"name": "row", "value": "LockBit"}, {"name": "row", "value": "APT41"}]`; layer keeps `versions`/`domain` identical to `get_navigator_layer`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; router: heatmap mode when any of the three params is not None, defaults `top_rows=15, top_ttps=20`; export filename `cti_navigator_{view}_{days}d_r{rows}_c{cols}.json` in heatmap mode.
- [ ] **Step 4:** Unit PASS; existing mitre snapshot unchanged (`uv run pytest tests/integration/test_mitre_router_snapshot.py -q`), add `test_navigator_export_heatmap_mode` (200, `Content-Disposition` has `_r10_c12`, every technique ID in heatmap `ttps` of the same params).
- [ ] **Step 5:** Web: export URL adds `&top_rows=${topRows}&top_ttps=${topTtps}` (+ `ttp_source` values the view uses) and matching download filename.
- [ ] **Step 6:** Commit `feat(mitre): export the visible heatmap as an ATT&CK Navigator layer`.

### Task 4: Frontend alignment

**Files:**
- Modify: `apps/web/src/components/intelligence/risk-matrix-view.tsx` (`riskTierClass` → 3 tiers 0-39/40-69/70-100; legend text if any; `lg:` breakpoints on 2-3 column grids)
- Modify: `apps/web/src/app/globals.css` (`--input: #8f7565` / dark `#8a6a7c`; `--ring: var(--foreground)` both themes; light `--warning: #a04a07`)
- Modify: `apps/web/CLAUDE.md` (breakpoint rule: 2-3 column layouts collapse to one column below 1024 px, `lg:`)
- Check: grep `md:grid-cols-[23]` in risk-matrix and heatmap views → `lg:`.
- Check: anything that styles focus via `ring-primary` explicitly instead of `ring-ring` (leave, report).

- [ ] **Step 1:** Edits above. Tier tints reuse existing tokens (`bg-success/20 text-success-text`, `bg-warning/25 text-warning-text`, `bg-severity-critical/25 text-severity-critical-text`).
- [ ] **Step 2:** `pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build` → all pass.
- [ ] **Step 3:** Commit `feat(web): one risk-tier scale, input/ring/warn tokens, lg breakpoint rule`.

### Task 5: Contract, keys report, release, PR

- [ ] **Step 1:** `uv run python tools/export_openapi.py`; `cd apps/web && pnpm run gen:api`; `git diff --stat docs/openapi.json apps/web/src/lib/api/schema.d.ts` shows only the new route/params/models.
- [ ] **Step 2:** Third-party keys: list providers in `services/runtime_secrets.py` / `routers/secrets.py`, compare with the Admin mockup frames (FigCraft ids 4380 and 44619 sub-tabs); write the difference list into the PR body.
- [ ] **Step 3:** Release bump to 0.8.15 per memory `release-convention` (root + each package `pyproject.toml`, every `__version__`, `apps/web/package.json`, `uv lock`, openapi, health snapshot); `CHANGELOG.md` `## [0.8.15] - 2026-11-08` in Indonesian; `docs/prod-upgrade/0.8.15.md` + `docs/PROD_UPGRADE_0.8.14_TO_0.8.15.md` per memory `feedback-prod-upgrade-docs-per-release`.
- [ ] **Step 4:** Full verification: `uv run ruff check . && uv run ruff format --check .`, mypy (both packages), `uv run pytest tests/unit tests/contract packages -q`, the touched integration files, web lint/typecheck/build.
- [ ] **Step 5:** `superpowers:requesting-code-review` on the branch; fix findings.
- [ ] **Step 6:** Push branch, merge into `origin/Dev`, open PR to `main`.
