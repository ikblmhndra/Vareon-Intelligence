# Confidence replay fixture (P6)

`dev_2026-10.csv`: one row per article on the shared dev instance (172.25.1.77), exported
2026-10-26 with a read-only query (`BEGIN READ ONLY; COPY (...) TO STDOUT WITH CSV HEADER; ROLLBACK;`).
No titles, URLs or source names. Columns map 1:1 to `cti_core.confidence.ArticleFacts`
(plus `id`, `posted_on`, `story_id`).

Definitions (same as `db/repositories/assessment.py`):

- `has_ioc`: a non-suppressed IOC (`ioc_sources` + `iocs.auto_suppressed = false`).
- `has_cve`: any `article_cves` row. `kev` / `poc`: `bool_or(cisa_kev / poc_available)` over
  `article_cves` joined to `cve_tracker` on `upper(cve_id)`.
  FP filter not applied (`is_false_positive_row` is not part of the query).
- `story_source_count = greatest(coalesce(stories.source_count, 1), 1)`.
- `explicit_ttp_count`: `article_ttps.source = 'explicit'`; `bonus_ttp_count`: `source IN ('explicit', 'llm')`.
- Source grade: case-insensitive name match, analyst row first, then lowest id.
- `content_kind`: dev does not have the P6 `content_kind` column yet, so it is DERIVED from the
  source row's default `admiralty_code` (A1 kev, A2 advisory, B2 vendor_research, C3 news,
  C4 vendor_marketing, D4 social); analyst rows and unmatched sources are empty (NULL).

## Query

Run on dev as `psql -q ... < query.sql > dev_2026-10.csv`:

```sql
BEGIN READ ONLY;
COPY (
WITH pick AS (
  SELECT DISTINCT ON (lower(source_name)) lower(source_name) nm, reliability_grade, admiralty_code, origin
  FROM source_reliability_entries
  ORDER BY lower(source_name), (origin='analyst') DESC, id ASC
)
SELECT a.id, a.posted_on, a.story_id, p.reliability_grade,
  CASE WHEN p.origin='analyst' THEN NULL ELSE CASE p.admiralty_code
    WHEN 'A1' THEN 'kev' WHEN 'A2' THEN 'advisory' WHEN 'B2' THEN 'vendor_research'
    WHEN 'C3' THEN 'news' WHEN 'C4' THEN 'vendor_marketing' WHEN 'D4' THEN 'social' END END AS content_kind,
  greatest(coalesce(s.source_count,1),1) story_source_count,
  EXISTS (SELECT 1 FROM article_cves c WHERE c.article_id=a.id) has_cve,
  EXISTS (SELECT 1 FROM ioc_sources i JOIN iocs x ON x.id=i.ioc_id WHERE i.article_id=a.id AND NOT x.auto_suppressed) has_ioc,
  (SELECT count(*) FROM article_ttps t WHERE t.article_id=a.id AND t.source='explicit') explicit_ttp_count,
  (SELECT count(*) FROM article_ttps t WHERE t.article_id=a.id AND t.source IN ('explicit','llm')) bonus_ttp_count,
  EXISTS (SELECT 1 FROM article_threat_actors x WHERE x.article_id=a.id) has_actor,
  a.confirmed_incident,
  EXISTS (SELECT 1 FROM article_cves c JOIN cve_tracker k ON upper(k.cve_id)=upper(c.cve_id) WHERE c.article_id=a.id AND k.cisa_kev) kev,
  EXISTS (SELECT 1 FROM article_cves c JOIN cve_tracker k ON upper(k.cve_id)=upper(c.cve_id) WHERE c.article_id=a.id AND k.poc_available) poc
FROM articles a LEFT JOIN pick p ON p.nm=lower(a.source) LEFT JOIN stories s ON s.id=a.story_id
ORDER BY a.id) TO STDOUT WITH CSV HEADER;
ROLLBACK;
```
