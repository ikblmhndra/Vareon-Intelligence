# FigCraft redesign: missing data and small UI alignment (0.8.15)

Date: 2026-11-08. Status: draft for review. Release: 0.8.15 (main is at 0.8.14, no open PRs).

## Goal

The FigCraft mockup (`~/Documents/Vareon Design.figcraft`) was checked field by field against the API.
Three elements have no data source yet, and a few design-system rules differ from the code. This change
adds the data and aligns the small rules, so the redesign can later be built page by page. Building the
new charts in the UI is **out of scope**: this release only provides their data.

Success: each item has a passing test, `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts` are in
sync, ruff/mypy/web lint+typecheck+build pass, one PR (approved: single PR, single bump).

## 1. PIR weekly coverage

Mockup: PIR detail card "Articles matched per week, since 1 Sep" (bar chart).

- Endpoint: `GET /api/pir/{pir_id}/coverage/weekly?weeks=26` (`weeks` 1..52, default 26). Same router
  dependencies as the rest of `/api/pir` (`view_intel` + login) and the same `_get_pir_or_404` client
  check as `/{pir_id}/articles`.
- Response model `PIRWeeklyCoverage`:
  `{pir_id: int, since: date, until: date, weeks: [{week_start: date, count: int}]}`.
- Window: `until = min(end_date, today)`; `since` = Monday of `start_date`, but never earlier than
  `weeks - 1` weeks before the Monday of `until`. No `start_date` means the last `weeks` weeks.
  A PIR whose `start_date` is in the future (`since > until`) returns an empty `weeks` list.
- Weeks start on Monday (Postgres `date_trunc('week', ...)`), every week in the window is present, and
  empty weeks are 0.
- Matching reuses `_apply_list_filters` with `_criteria_filters(pir.criteria)` plus the window, the same
  definition as `coverage_count` (P7f "one definition"). A PIR with no criteria matches every article,
  as `coverage_count` already does. Count is `count(DISTINCT article.id)` per week.
- Code: `AsyncPIRRepo.weekly_coverage(pir, weeks, today)` in `cti_core` (mypy strict), returning
  `list[tuple[date, int]]`; the router builds the model.

## 2. Early Warning daily series

Mockup: "Strongest signal" card, daily bars over the lookback plus a baseline-mean line.

- `GET /api/spikes` gains a `daily` object. Existing fields are unchanged:
  ```
  daily: {
    dates: ["2026-10-09", ..., today],          # every day from cutoff to today, ascending
    threat_actors: {"LockBit 5.0": [0, 2, ...]}, # aligned with dates, zero-filled
    countries: {"ID": [...]},
    industries: {"Finance": [...]},
    overall: [...]                               # daily totals, zero-filled
  }
  ```
  Only entities that appear in that dimension's spike list are included. It is a map, not a field
  on each spike row, because one entity can spike on several days and the series would repeat.
- The data is already loaded by `_compute_spikes` (`daily_entity_counts`), so there are no new queries.
  The 15-minute cache keeps the whole response.
- The response gets a Pydantic model (`SpikesResponse` with `EntitySpike`, `OverallSpike`, `SpikeDaily`,
  `SpikeParameters`) so `schema.d.ts` is typed; today it is `dict[str, object]`. Field names and
  types stay exactly the same (`entity_id` nullable).
- Baseline (revised 2026-11-08, user decision): detection now counts baseline days without articles
  as 0 for mean and standard deviation, so `baseline_mean` matches the zero-filled `daily` bars. This
  changes detection results on purpose. An entity still needs 5 baseline days with articles; the
  old `mean < 0.5` filter is dropped (it never triggered on non-zero days and would now hide sparse
  entities).

## 3. ATT&CK Navigator layer from the heatmap

Mockup: "Export ATT&CK Navigator layer" button next to Period / Rows / Columns on the heatmap.

`/api/mitre/navigator-layer` and `/navigator-export` already exist (the UI uses them), but they ignore
the heatmap filters: they export every technique observed in the period.

- Both endpoints accept optional `top_rows`, `top_ttps` and `ttp_source`, with the same bounds as
  `/heatmap`. If **none** of them is given, the output is unchanged (backward compatible).
- If any is given, the layer is built from `get_heatmap(...)` with the same arguments (missing ones use
  the heatmap defaults):
  - techniques = heatmap columns whose ID starts with `T`;
  - `score` = column sum over the visible rows (row-technique co-mentions);
  - `comment` = rows with a non-zero cell, highest first, e.g. `"LockBit 5.0: 22, Black Basta: 18"`;
  - `gradient` = `{minValue: 0, maxValue: max score}`; `description` names period, view, rows and
    columns; `metadata` lists the rows.
- Export filename: `cti_navigator_{view}_{days}d_r{rows}_c{cols}.json` in heatmap mode; unchanged otherwise.
- Code: `AsyncMitreHeatmapRepo.get_heatmap_navigator_layer(...)` next to `get_navigator_layer`, with
  the layer envelope shared through one helper.
- Web: the heatmap's export button passes its current rows/columns/source filters.
- "Open in Navigator" (revised 2026-11-08, user decision): `#layerURL=` cannot work (no session cookie
  from mitre-attack.github.io; http internal hosts are mixed content), so the button opens Navigator,
  downloads the same layer as Export, and tells the user to use "Open Existing Layer → Upload from local".
  No auth change.

## 4. Frontend alignment

- **Risk tier, one scale**: LOW 0-39 / MED 40-69 / HIGH 70-100. `lib/exec/format.ts::riskTier` already
  uses it. `risk-matrix-view.tsx::riskTierClass` (4 tiers, 25/50/75) becomes 3 tiers on the same cut
  points, using the existing success / warning / critical tint+text tokens.
- **`--input`**: `#8F7565` light, `#8A6A7C` dark (field borders ≥3:1; `--border` stays for cards).
- **Focus ring**: ink, as decided by the user. `--ring: var(--foreground)` in both themes (`#2B0D19`
  light, `#F6EDE4` dark).
- **Warn text**: the current tokens already pass AA and have higher contrast than the mockup's `#A04A07`
  (`--warning #9a4a00` 5.49:1, `--warning-text #7d3b00` 7.37:1 on surface; `#A04A07` is 5.29:1).
  Proposal: set `--warning` to `#A04A07` to match the mockup hue, and keep `--warning-text`.
  Both still pass.
- **Breakpoint rule**: 2-3 column layouts collapse to one column below 1024 px (Tailwind `lg:`). This is
  recorded in `apps/web/CLAUDE.md` and applied to the pages this change touches (risk matrix, heatmap).
  Mobile layouts remain out of scope.

## 5. Third-party keys check (report only)

Compare the provider list behind the secrets API (`routers/secrets.py`, `services/runtime_secrets.py`)
with the Admin mockup and report differences in the PR. No code change unless a difference is a clear
bug.

## Release

One PR, version 0.8.15 in every place the release convention lists, `CHANGELOG.md` entry in Indonesian,
`docs/prod-upgrade/0.8.15.md` plus the combined runbook from 0.8.10. No migration and no new `.env` keys.
Merge to `origin/Dev` for testing first, then a PR to `main`.

## Testing

- Unit: weekly window maths (start/end/future/no start), spike `daily` zero-fill and inclusion,
  heatmap layer builder (scores, comments, gradient, T-filter).
- Integration (testcontainers): weekly coverage endpoint against real rows; `/api/spikes` response
  validates against the new model; navigator endpoints with and without heatmap params.
- Web: lint, typecheck, build.
