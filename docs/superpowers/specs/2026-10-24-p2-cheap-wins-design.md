# P2 cheap wins: structured sources skip the LLM, canonical IOCs, CVEs out of IOCs, deterministic confidence

Date: 2026-10-24. Status: design approved in chat, awaiting review of this written spec.
Release: **0.8.6** (one PR, merged into `origin/Dev` and tested on the dev instance first).
Parent documents: `docs/LLM_ASSIST_REDESIGN.md` (P2, Tier 0, Tier 1 IOCs, section 3) and
`docs/UI_DATA_AUDIT.md` (U5, U14, U15). The TTP evidence check listed under P2 already shipped in
0.8.5.

## 1. Goal and success criteria

Cut LLM calls that add nothing, make the IOC store usable for matching and export, give every
article a confidence score that is not the LLM's self-rating, and break nothing that reads these
data today.

Success, checked on the dev instance after deploy:

1. Articles from `cisa_kev`, `exploitdb` and `cis` produce no `llm_calls` rows (neither
   `classify` nor `ttp`).
2. No IOC value is stored defanged (`[.]`, `(.)`, `[dot]`, `hxxp`, `[@]`, `[:]`), and no two IOC
   rows share the same canonical `(type, value)`.
3. No IOC row has `type = 'cve'`; `article_cves` holds the 4,427 article-CVE pairs that exist on
   dev today, and the CVE lists of campaigns and newsletter suggestions are the same before and
   after the migration.
4. Article `confidence_score` is no longer the LLM self-rating (54% at 90-100 today, none below
   60, E7); every scraped source has a reliability row.

Dev data behind the design (read-only, 2026-10-24):

| Fact | Number |
|------|--------|
| Sources the LLM never rejects | `cisa_kev` 23, `exploitdb` 20, `cis` 24, `ecrime` 44, `asec_ahn` 36 accepted, 0 rejected; together ~9% of accepted articles |
| News type of the three structured sources | from techstack routing (`Tech Stack` / `Unrelated Tech Stack` / `global`), not from classify |
| IOCs stored defanged | all 1,351 domains, 534 of 803 IPs, 70 of 152 emails |
| Defanged values with a refanged twin | 73 |
| Rows that differ only in case | 100 hashes, 43 domains, 23 emails |
| CVE IOCs | 3,061 rows, 4,427 distinct article-CVE pairs, 0 without an article |
| Graded sources | 3 (CYFIRMA, CrowdStrike, Mandiant), matched to articles by name |

## 2. Tier 0: structured sources skip the LLM

### 2.1 Scraper contract

`cti_scraper.base.ScraperMeta` gains two fields with defaults, so no scraper breaks:

- `content_kind: Literal["advisory", "kev", "exploit", "vendor_research", "news",
  "vendor_marketing", "social"] = "news"`
- `default_relevance: Literal["always", "classify"] = "classify"`

A contract test (`tests/contract/`) fails when `default_relevance == "always"` is combined with a
`content_kind` other than `advisory`, `kev` or `exploit`. Every scraper file under
`scrapers/src/cti_scrapers/` sets `content_kind` explicitly (it drives the default source grade,
section 5); only `cisa_kev` (`kev`), `exploitdb` (`exploit`) and `cis` (`advisory`) set
`default_relevance="always"`. `ecrime` and `asec_ahn` stay on `classify`: they are news and
research whose industry, country, incident and victim fields come from classify.

### 2.2 Enrichment flow

- `apps/worker/src/cti_worker/tasks/enrich.py` (`enrich.article`) resolves the scraper meta from
  `cti_scraper.registry` by `scraper_id` and passes `content_kind` and `default_relevance` to
  `run_pipeline`. `cti_enrich` does not import `cti_scraper`. An unknown or missing `scraper_id`
  (deleted scraper, old message) means `classify`. Manual and automatic replay go through the same
  task, so they behave the same.
- `run_pipeline(..., content_kind: str | None = None, default_relevance: str = "classify")`.
  With `always`:
  - `classify()` is not called. The pipeline builds
    `ClassifyResult(related_cyber=True, reason=f"structured source: {content_kind}",
    audit={"skipped": "default_relevance=always", "content_kind": content_kind})`; industries,
    countries, incident and victim stay empty.
  - TTP extraction is skipped (`ttp_result` empty); Exploit-DB entries produced hallucinated TTPs
    (E8).
  - IOC extraction, scoring, techstack routing, persist and alerts run as today.
- Expected effect: ~9% of accepted articles make no LLM call. The spec states this number, not
  "a large share"; it is measured with `llm_calls` after deploy.

## 3. Canonical IOCs and the allowlist

### 3.1 Canonical form

New `cti_core.ioc.canonical.canonical(ioc_type: str, value: str) -> str`, called by every IOC
writer before `IOCRepo.upsert` / `AsyncIOCRepo.upsert` (enrich persist, newsletter
`write_article_findings`, the deepdarkCTI sink):

| Type | Rule |
|------|------|
| `ip` | refang (`[.]`, `(.)`, `{.}`, `[dot]`, `(dot)` to `.`), strip whitespace |
| `domain` | refang, lowercase, strip a trailing `.` |
| `url` | refang (`hxxp(s)` to `http(s)`, `fxp` to `ftp`, `[.]`, `[:]`), lowercase scheme and host; path, query and fragment keep their case |
| `email` | refang (`[@]`, `(@)`, `[at]`, `(at)` to `@`, dots as above), lowercase |
| `sha256`, `sha1`, `md5` | lowercase |

The newsletter's `url_with_path` type becomes `url`, as in persist. `url_with_path` leaves the
code (`newsletter.py` map, `stix.py`, `confidence.py`, the web type list).

### 3.2 Display

- Web (IOC table, IOC detail, FP queue): a `defang()` helper shows `evil[.]com`, `1.2.3[.]4`,
  `hxxp://...`, `user[@]host[.]com`; the copy action copies the defanged form.
- API, STIX export: canonical value (what a SIEM needs).

### 3.3 Migration of existing rows

In the 0.8.6 migration, with a frozen copy of the canonical rules (no import of app code):

1. Compute the canonical value of every IOC row.
2. Group rows by canonical `(type, value)`. Within a group the lowest `id` survives:
   - `ioc_sources`, `ioc_tags`, `ioc_threat_actors`, `ioc_feedback` move to the survivor,
     skipping pairs that would break their unique constraints;
   - `seen_count`, `tp_count`, `fp_count` are summed; `first_seen_at` is the minimum,
     `last_seen_at` the maximum; `enrichment` is the survivor's, or the first non-empty one;
   - the other rows are deleted.
3. Update the survivor's `value` to the canonical value.

The merge is not reversible; downgrade only drops the new structures. `make deploy` takes a
Postgres backup first, and the CHANGELOG says so.

### 3.4 Allowlist: flag, do not drop

- Behaviour change: an allowlist match (seed or analyst entry) is stored with
  `auto_suppressed = true` and `suppression_reason = "allowlist:<type>:<entry> (infrastructure-abuse)"`
  instead of being dropped at extraction. Domain, URL host and email domain match by suffix
  (`files.gofile.io` matches `gofile.io`); IPs match exactly. Private and reserved IPs and links
  to the article's own site are still dropped (they are not indicators). Domains are now checked
  too (today only IPs, URLs and emails are).
- Seed: a curated list of about 150 domains (major SaaS, file sharing such as `gofile.io`, CDNs,
  cloud providers, code hosting, security vendors) in a data file in the repository, inserted into
  `ioc_allowlist_entries` with `added_by = "seed"`; analysts can delete entries as today. No
  external download.
- The migration flags existing IOCs that match the allowlist (seed and current entries).
- Consumers that exclude suppressed IOCs: STIX IOC export, `GET /api/iocs/stats`, campaign IOC
  lists (and so diamond and IOC-similarity), recap IOC counts, the FP queue. Provider reputation
  enrichment already excludes them.
- `GET /api/iocs` gains `include_suppressed: bool = False`; the web IOC list shows a "Suppressed"
  badge and a filter to include them.

## 4. CVEs move out of IOCs

### 4.1 Table

`article_cves`: `article_id` (FK `articles.id`, `ON DELETE CASCADE`), `cve_id` (varchar(20),
uppercase), `in_title` (bool), `first_seen_at` (timestamptz, default now). Primary key
`(article_id, cve_id)`; index on `cve_id`.

### 4.2 Writers and readers

- Enrich persist writes the extractor's `cves` into `article_cves` (insert, ignore duplicates;
  `in_title` when the ID also appears in the title) and no longer into `iocs`.
- Newsletter `write_article_findings` does the same; `cve_newsletter_mentions` is unchanged.
- `cve_ids_by_article` moves to a new `AsyncArticleCveRepo` reading `article_cves`; its consumer
  `newsletter_suggestion` only changes the import.
- `campaign._build_ioc_map` stops splitting `type == "cve"`; `cve_ids` per campaign come from
  `article_cves` in one query. The campaign dict keeps the same `cve_ids` field, so
  `cve_priority`, `campaign_analysis` (CVE Jaccard and criticality) and the mindmap do not change.
- `cve` leaves `_VALID_TYPES`, the persist and newsletter IOC type maps, the decay half-life table
  and the web IOC type list and badge style. The STIX `vulnerability` pattern stays.

### 4.3 Migration

1. Insert into `article_cves` every distinct `(ioc_sources.article_id, upper(iocs.value))` for
   `iocs.type = 'cve'` with a non-null `article_id` (4,427 pairs on dev); `in_title` from the
   article title; `first_seen_at` from the earliest `ioc_sources.first_seen_at`.
2. Delete `iocs` rows with `type = 'cve'` (3,061 on dev); sources, tags and feedback cascade.
   No CVE IOC on dev lacks an article link.

## 5. Deterministic confidence and default source grades

### 5.1 Default grades

- `source_reliability_entries` gains `origin varchar(10) not null default 'analyst'`
  (`default` | `analyst`); existing rows are `analyst`.
- At API startup (existing `lifespan` bootstrap, under its advisory lock), every registered
  scraper whose `meta.source` has no row (case-insensitive) gets a `default` row: `source_name =
  meta.source`, `analyst_name = "system"`, grade from its `content_kind`:

| `content_kind` | Reliability / credibility |
|----------------|---------------------------|
| `kev` | A1 |
| `advisory` | A2 |
| `exploit`, `vendor_research` | B2 |
| `news` | C3 |
| `vendor_marketing` | C4 |
| `social` | D4 |

- Analyst rows are never overwritten. Editing a `default` row through the existing API sets
  `origin = 'analyst'`.

### 5.2 Article score

- The pure `compute_score(reliability_grade, credibility_code, ttp_count, ta_count)` moves to
  `cti_core.confidence`; `cti_api.services.confidence` re-exports it, so existing callers do not
  change.
- Enrich persist sets `confidence_score` from `compute_score` with the source's grade (looked up
  by `Article.source`, case-insensitive) and the article's TTP and threat-actor counts, instead of
  `classify.confidence * 100`. The LLM value stays in `raw_enrichment["classify"]`.
- Recompute writes the `confidence_score` column directly. Today `recompute_all_confidence` and
  `compute_and_store_article_confidence` write it into `overrides` (the analyst-edit field); that
  changes, and an article whose `overrides` carries `confidence_score` keeps the override value
  (none on dev).
- Creating or changing a source grade (startup default rows, analyst edit) enqueues a
  `confidence.recompute_source` maintenance task for that source's articles. On the first start
  of 0.8.6 every scraped source gets a default row, so every article is recomputed once; no
  frozen source-to-kind map is needed in the migration. Articles whose source matches no scraper
  and no row get the formula's ungraded base (50, plus TTP and actor bonuses) on that recompute.

### 5.3 UI

- Dashboard "Perlu dibaca" and Newsroom front section: "Confidence 100" becomes the Admiralty
  code plus score (for example `B2 · 72`); the tooltip names the source grade and whether it is a
  default or an analyst grade.
- Source reliability page: every source listed, `default` rows labelled.
- The API exposes `admiralty_code` and `grade_origin` next to `confidence_score` on the article
  shapes that the two cards use.

## 6. Out of scope

- CVEs in the article modal and `ArticleOut` (follow-up once `article_cves` exists).
- Story dedup (P3), deterministic actor/malware/ATT&CK extractors (P4), local relevance model
  (P5), credibility from corroboration (part of P6).
- Persist-first enrichment (LLM off the critical path), token ceilings, caching.

## 7. Testing

- Unit: `canonical()` per type (refang forms, case, URL path case kept); suffix allowlist match;
  `compute_score` unchanged results; default grade mapping; scraper contract test for
  `content_kind` / `default_relevance`; `run_pipeline` with `always` calls neither classify nor
  TTP and stores the skip audit.
- Integration (testcontainers): migration on seeded rows (defanged twins merged with sources, tags,
  feedback moved and counts summed; case duplicates merged; CVE IOCs moved to `article_cves` and
  deleted; allowlist matches flagged; confidence recomputed); `GET /api/iocs` hides suppressed by
  default; STIX export excludes suppressed; campaign `cve_ids` equal before and after;
  `newsletter_suggestion` CVE flags unchanged; startup creates default grades without touching
  analyst rows; `tests/integration/test_migrations_match_models.py` green.
- Web: `tsc`, `eslint`, `next build`; manual check of the IOC table (defanged display, suppressed
  filter) and the confidence chips on dev, light and dark.
- API contract: `docs/openapi.json` and `apps/web/src/lib/api/schema.d.ts` regenerated.

## 8. Release

0.8.6 with the usual version bump and an Indonesian CHANGELOG entry. Upgrade notes: one migration
(IOC merge is irreversible; deploy takes a backup), default source grades appear on the Source
reliability page, the allowlist now flags instead of dropping, no new `.env` keys.
