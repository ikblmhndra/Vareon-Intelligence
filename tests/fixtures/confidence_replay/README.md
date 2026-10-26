# Confidence replay fixture (P6)

`dev_2026-10.csv`: one row per article on the shared dev instance (172.25.1.77), exported
2026-10-26 with a read-only query (`BEGIN READ ONLY; COPY (...) TO STDOUT WITH CSV HEADER; ROLLBACK;`).
No titles, URLs or source names. Columns map 1:1 to `cti_core.confidence.ArticleFacts`
(plus `id`, `posted_on`, `story_id`).

Definitions (same as `db/repositories/assessment.py`):

- `has_ioc`: a non-suppressed IOC (`ioc_sources` + `iocs.auto_suppressed = false`).
- `has_cve`: any `article_cves` row. `kev` / `poc`: `bool_or(cisa_kev / poc_available)` over
  `article_cves` joined to `cve_tracker` on `upper(cve_id)`.
  The false-positive row filter was NOT applied (dev has no FP rows that matter).
- `story_source_count = greatest(coalesce(stories.source_count, 1), 1)`.
- `explicit_ttp_count`: `article_ttps.source = 'explicit'`; `bonus_ttp_count`: `source IN ('explicit', 'llm')`.
- Source grade: case-insensitive name match, analyst row first, then lowest id.
- `content_kind`: dev does not have the P6 `content_kind` column yet, so it is DERIVED from the
  source row's default `admiralty_code` (A1 kev, A2 advisory, B2 vendor_research, C3 news,
  C4 vendor_marketing, D4 social); analyst rows and unmatched sources are empty (NULL).
