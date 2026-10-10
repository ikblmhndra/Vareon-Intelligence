# Tech Matching in the CVE Tracker

A single-topic note: the **Tech** column in the CVE Tracker does not match **Affected**. It covers the problem,
the root cause, the solution already running, how to verify it, the remaining limitations, and the development
plan (techstack standardisation, `docs/ROADMAP.md` #19).

**Status** (2026-10-07): the filter fix and the cleanup tool shipped in release 0.2.1 (PR #8); the
version-number bug correction (`graylog2-server`) is on `main`. **The standardisation direction changed today**: no longer
manual aliases + a curated catalog, but **CVE mirror -> tech catalog -> Monitor** (7.1, full design in
`docs/ROADMAP.md` #19); the code already exists (slices 1-7, `docs/CVE_CATALOG_DESIGN.md`). The shared matcher `cti_core.tech_match`
(without the `aliases` column, which was dropped) is on the `nameless/roadmap-runners` branch, not yet on `main` (7.1.1). The command to run the cleanup
tool: `docs/SCRAPER_MAINTENANCE.md` 4.G.

---

## 1. The problem

CVEs are recorded under a tech that is not their affected product. Reported from the UI (2026-10-05):

| CVE | Tech | Affected | Actually |
|---|---|---|---|
| CVE-2026-59783 | MARIADB | Zabbix | a Zabbix CVE that mentions MariaDB in its description |
| CVE-2026-105640 | GITLAB | plane | a Plane CVE that mentions GitLab in its description |
| CVE-2026-105766 | NGINX | Chainguard Academy (edu) | a CVE for the Chainguard Academy site that mentions `nginx.conf` |
| CVE-2026-75786 | GRAFANA | Pandora FMS | a Pandora FMS CVE that mentions a Grafana datasource |

Not every odd-looking row is wrong: CVE-2026-21589 (Tech JIRA, Affected showing Bamboo
Data Center, Bamboo Server, and 14 others) is a multi-product Atlassian advisory whose summary mentions
Jira Service Management Data Center. That row passed the assessment in the production report (it is not in `DELETE`).

**How big.** The `reconcile_cve_tech` report in production (2026-10-07), 125 `cve_tracker` rows
(125 unique CVEs, one client):

| Result | Count | Meaning |
|---|---|---|
| Correct | 63 | the tech matches the affected product |
| Wrong, delete (`DELETE`) | 52 | another product that happens to mention the tech |
| Wrong label (`RETAG`) | 2 | another tech of the same client matches |
| Wrong, but has an ACK (`REVIEW`) | 1 | Pandora FMS/Grafana, decided by hand |
| Unverified | 7 | MITRE unreachable or no data |

Of the 118 rows that could be verified, **only 63 (about 53%) are correct**. The 52 `DELETE` rows
per tech:

| Tech | Rows | Actual affected products |
|---|---|---|
| jira | 31 | `mcp-atlassian` (29), `gocd`, `project-management` |
| nginx | 11 | wolfSSL (3), frigate (2), Mailu, Eclipse Open VSX, grav, froxlor, sogo_yhn, Chainguard Academy |
| gitlab | 4 | drawio, dokploy, zammad, plane |
| mariadb | 3 | dbhub (2), Zabbix |
| grafana, microsoft 365, crowdstrike | 1 + 1 + 1 | novu, zammad, AiSOC |

## 2. Root cause

**2.1 Tech and Affected come from two sources that were never compared.** `new_cve` searches
NVD with `keywordSearch=<tech name>`, which matches words **anywhere in the description** (all words,
any order). The Affected column is taken from the MITRE record (`containers.cna.affected`). Search results
were written directly with tech = the keyword used to search; no step checked that the
affected product really was that tech.

**2.2 Global dedup per `cve_id`.** The `seen` set made a CVE that hits several techs (e.g. Atlassian:
Jira, Confluence, Bamboo) stick only to whichever tech happened to be searched first. A client that only has
Confluence never got that CVE.

**2.3 Old rows were never cleaned up.** The scraper only *upserts*, and only for CVEs that are still
found within the 8-day window. A CVE that is later rejected by the filter is not fetched again, so its row
stays forever. Fixing the scraper alone is not enough.

**2.4 Structural: tech names are free text, used by six matchers with different rules.** The UI input
is just "Tech name…" without validation. That name is used in:

| # | Where | Matches | Rule | Used for |
|---|---|---|---|---|
| 1 | `new_cve._nvd_candidates` | tech name against the CVE description | NVD `keywordSearch` | finding candidates |
| 2 | `new_cve._tenable_candidates` | tech name against the result summary | per word (`_mentions`) | finding candidates |
| 3 | `new_cve` gate (`relevant_techs`) | tech name against MITRE vendor/product/CPE | per word + attached digits | `cve_tracker` rows |
| 4 | `score.py` `related_tech_status` | tech name against the article/tweet title | `\b{tech}\b`, **without `re.escape`** | `tech_stack` topic alerts |
| 5 | `score.py` `_check_cve_vendor` → `check_tech_stack` | MITRE vendor against the tech name | substring, **without word boundaries** | `tech_stack` topic alerts |
| 6 | `cve_priority.in_tech_stack` | CVE tracker name against techstack names | substring **in both directions** (`t in name or name in t`) | priority score (20% weight) and `patch_urgency` |

In addition: the CVE router looks up `risk_ctx.get(cve.tech.lower())` in the map of `techstack_entries.name` (lower
case) from `get_risk_context` for `adjusted_risk_score` (exposure and hosting). So `name` now
works as a **join key**, not just a label.

**Correction 2026-10-07: there are actually seven matchers.** The seventh, `reports/cve_record.py::applicable_to_stack`
(the Top CVE report, label "Might Applicable to Organization!"), uses a `re.escape(tech)` substring against the
vendor without word boundaries; see `docs/CVE_TRACKER_FLOW.md` 9.

Number 3 is the only one fixed in 0.2.1. Numbers 4-6 carry a similar risk (short techs
like `go` or `edge` match words that merely contain those letters; punctuated techs like
`node.js` or `c++` in number 4 are treated as a regex).

**Since phase 1 (2026-10-07)** numbers 2-6 call a single module, `cti_core.tech_match`. Number 1 (the NVD
`keywordSearch` query) is not really a matcher, just a candidate finder, and keeps using the tech name as-is.

## 3. The solution already running

### 3.1 Relevance gate in `new_cve` (0.2.1)

NVD/Tenable candidates are only used if the tech name appears in one of: `vendor`, `product`,
`packageName`, or `cpes` in the MITRE record's `containers.cna.affected`. Code: `relevant_techs`,
`affected_products`, `usable_products`, `_mentions` in `scrapers/src/cti_scrapers/feeds/new_cve.py`.

Matching rules (`_mentions`):
- Lower case; every non-alphanumeric run becomes one space (`Palo_Alto-Networks` = `palo alto networks`).
- The tech name must be a whole word. **Digits (max 4) attached at the end are treated as a major version of
  the same product**: `graylog2-server` matches `graylog`, `Log4j2` matches `log4j`. Attached letters
  do not: `nginxplus` and `nginxy` are not `nginx`.
- If the CNA did not fill in a product, or only a placeholder (`n/a`, `unknown`, `unspecified`, `none`,
  `various`), it falls back to the CVE summary. With no product and no summary there is no evidence, and the candidate
  does not pass.
- Only CNA data is used (not ADP).

Rejected CVEs are logged at info level: event `cve_candidate_tech_not_affected` (fields `cve_id`,
`techs`, `products`) in the `worker` container.

### 3.2 One CVE, one candidate

Candidates are grouped per `cve_id` and carry every tech that surfaced them. After the gate, each
client that has one of the affected techs gets its row. The tracker key `(cve_id, client_id)` only
stores **one** tech per row, so if a client has several affected techs, the
**alphabetically first** one is used (the techstack list in `reference_data` is indeed sorted alphabetically).

### 3.3 Cleaning up old rows: `tools/ops/reconcile_cve_tech.py`

Re-fetches the MITRE record of every CVE in the tracker and assesses each row with the same function as the
scraper (one definition of "matches"):

| Action | When | Effect with `--apply` |
|---|---|---|
| (left alone) | the tech matches | none |
| `RETAG` | no match, but another tech of the same client matches | change `tech` |
| `DELETE` | none of the client's techs match | delete the row, its children, and its false positive marks |
| `REVIEW` | no match, but it already has a ticket/ACK | **never touched** |
| (skipped) | MITRE unreachable, or no product and no summary | reported as "tak terverifikasi" (unverified) |

Default is **report only**. The safe order: report, read, back up Postgres, `--apply`. The tool uses the
matcher from the **worker image**, not from the mounted `tools/` folder, so the image must be rebuilt
whenever the matcher changes. Full command: `docs/SCRAPER_MAINTENANCE.md` 4.G.

### 3.4 A follow-up bug found through the report

The first production report flagged `DELETE CVE-2026-69190 graylog`, although its Affected was
`graylog2-server`: the 0.2.1 matcher treated `graylog2` as a different word from `graylog`. Two consequences:
the tool nearly deleted a legitimate CVE, and `new_cve` itself was dropping real CVEs for products named
`Graylog2`, `Log4j2`, `Struts2`. Fixed in `f96d23b` (the attached-digits rule above), with a regression
test. Lesson: **a filter that drops things silently must always have its report checked before it is trusted**
(see 6 and 7.2).

## 4. How to verify

- Tests: `tests/unit/test_new_cve_tech_relevance.py` (cases from the UI, products with version numbers, multi-product
  CVEs, vendor only, underscored CPEs, summary fallback, Tenable),
  `tests/unit/test_reconcile_cve_tech.py` (the assessor and the MITRE fetch),
  `tests/integration/test_reconcile_cve_tech.py` (cascading deletes to children, protected tickets, retag,
  client filter; needs Docker).
- Production: run the tool's report periodically. New `DELETE` rows appearing after a deploy
  mean the scraper still lets wrong CVEs through; rows you consider legitimate but marked `DELETE` mean the
  matcher is too strict (the Graylog case).
- Logs: `docker compose logs worker | grep cve_candidate_tech_not_affected` shows what the
  filter dropped.

## 5. Design decisions

| Decision | Reason |
|---|---|
| The gate uses products from **MITRE**, not CPEs from NVD | NVD CPEs are only filled in after analysis (often delayed by days); the CNA fills them in at publish time. The Affected shown in the UI also comes from MITRE, so the gate and the display use the same data. |
| Fall back to the summary when the CNA did not fill in a product | Without a fallback, CVEs from CNAs that do not bother filling in products disappear entirely. With the fallback the behaviour for that case is the same as before 0.2.1. |
| Rows with a ticket/ACK are never deleted automatically | Deleting them erases the analysts' work trail. A wrong label is cheaper than lost data. |
| The cleanup tool defaults to report only | Deletion is permanent; the report must be read by a human first (Graylog was found this way). |
| One matcher for the scraper and the tool | Two definitions of "matches" will inevitably drift; a tool that assesses with different rules deletes legitimate data. |

## 6. Known limitations

- **Recall has never been measured.** What 0.2.1 fixed is precision (wrong CVEs showing up). There is no number yet for CVEs that
  should show up but do not. The sources of risk:
  - `keywordSearch` only searches words in the description: a CVE that mentions "PAN-OS" is not found by
    the tech `palo alto`.
  - The filter drops silently when the CNA product name differs from your tech name (GitHub repo names, `graylog2-server`).
  - Tenable is scraped through a hardcoded XPath and only the first 6 rows.
  - The 8-day window is based on publish date: old CVEs whose affected data is completed later are not
    re-evaluated (`lastModStartDate` is not used).
- **Lexical matching.** `nginx-ui` or `nginx-proxy-manager` still match `nginx` (word boundary).
  Techs that are common words can match unrelated things.
- **The running version is unknown.** The tracker flags every CVE for a tech, not just those whose
  version is affected.
- **Product hierarchy.** Outlook is part of Microsoft 365/Office, but the CNA only writes "Microsoft 365
  Apps". Two `outlook` rows were `RETAG`ged to `microsoft 365` because of that.
- **CNA data quality varies** (product `n/a`, repo names, empty vendor).
- **Small display/data defects found along the way** (not from this change): the Affected column shows
  `<= < 30.2.7` (`_mitre_detail` always prepends `<=` to a `version` value that already contains an
  operator); `seen_products` skips the second entry for the same product (its range is lost); a 0.0 score
  and an empty severity when the CNA did not fill in CVSS (NVD/ADP scores are not used).

## 7. Development plan

### 7.1 Techstack standardisation: a catalog from the CVE mirror + Monitor (`docs/ROADMAP.md` #19)

**Why the direction changed.** Manual per-tech aliases do not scale (every client adds techs, someone has to
write aliases), and the root problem remains: free names matched as text. The idea agreed on
2026-10-07: let **the CVE data** define the products, and let users **pick** those products
instead of typing their names.

**Flow**: mirror every CVE (2025 to now) in our own DB -> a **tech catalog** (normalised vendor + product)
derived from that data -> the techstack menu: an **All Tech** tab (the catalog; search, click Monitor) and
**Monitored Tech** (per client) -> new CVEs are matched through the **product identity** from the CVE data -> the CVEs tab
only shows CVEs for monitored techs, and a **CVE DB** tab (read-only) browses the whole mirror.

**Why this is stronger than searching by name:**
- Search stops using `keywordSearch` (words anywhere in the description, the source of the 52 `DELETE` rows).
  `new_cve` fetches every new/changed CVE once an hour and filters locally by affected product:
  fewer requests, better recall, and a CVE that only mentions "MariaDB" in its description
  does not come along.
- No MITRE call per CVE (the CNA data is already in the bulk feed), so the 60/minute limit is no longer a
  bottleneck, and "Populate now" (#3) is not needed: a new tech is filled from the mirror.
- Product hierarchy (Outlook under Microsoft 365) becomes data, not a patch.
- **Affected versions: stay as they are now** (text in the Affected column + ticket fields); structured version ranges
  are not built (user decision 2026-10-07).

**The data layers and their life cycles** (do not conflate them):

| Layer | Life cycle |
|---|---|
| CVE mirror | dropped by retention: calendar year, keep the current year + the previous one (on 1 Jan 2027, 2025 CVEs are dropped) |
| Tech catalog | permanent; monitored rows are never deleted (never a transient derivative of the mirror) |
| Monitored tech (`techstack_entries`) | permanent, per client, points into the catalog (nullable for "custom") |
| `cve_tracker` | permanent; matching CVEs are promoted (copied) here at ingest, with no FK cascade to the mirror |

Tickets/ACKs live in `cve_tracker`, so they are never subject to retention. Un-monitor = **hide** (an active flag;
the dashboard already has an "active techstack" scope), not delete.

**Main risk**: CNA data is messy (product `n/a`, GitHub repo names, one product with five spellings, "Microsoft 365
Apps" vs "Microsoft Office"), so catalog normalisation is the hardest work; the picker must be
search-first. Products that have never had a CVE are not in the catalog (a "custom" path marked as not yet
verified). The data sources have different strengths: CVE List V5 (CNA data) is fast and complete but its names are
dirty, NVD (CPE) is clean but often late and some CVEs are never enriched; both are probably needed.
**Old CVEs that changed recently** (e.g. added to KEV) do not enter the mirror if its window is by publish
date. Details, phases, open items, and done criteria: `docs/ROADMAP.md` #19.

**Order**: (1) a read-only measurement spike (number of unique products, percentage of junk, how many of the 34 production techs
come out clean, plus the 7.2.1 recall); (2) mirror + read-only catalog + retention job + CVE DB tab;
(3) All/Monitored tabs + `catalog_id` + API validation; (4) replace `new_cve`, **shadow mode first** on the dev server;
(5) product merging by admins. Mapping the 34 old techs to the catalog is reviewed by hand (`name` stays the join key).

#### 7.1.1 The shared matcher `cti_core.tech_match`: on a branch, not yet on `main`

Done before the direction above was agreed. The version with a `techstack_entries.aliases` column, a migration, a seed of 8
techs, and the `techstack_aliases` reference data **was dropped** (user 2026-10-07): product identity will come from
the catalog, not hand-written aliases. What remains:

- **`cti_core.tech_match`** (`packages/cti-core/src/cti_core/tech_match.py`): one definition of "this text
  mentions that tech". Its rules are lifted from the 0.2.1 gate: lower case, non-alphanumerics become spaces
  (`Node.js` = `node js`), the tech must be a **whole word**, digits (max 4) attached at the end
  count as a major version (`graylog2-server` ~ `graylog`), attached letters do not (`nginxy` is not
  `nginx`). One safeguard: a term that is shorter than 2 characters after normalisation (the name `c++` becomes `c`)
  never matches.
- **Its callers**: the gate and the Tenable filter in `new_cve`, `score.py` (`related_tech_status` for article and
  tweet titles, `check_tech_stack` for CVE vendors), `cve_priority.in_tech_stack`, and the assessor in
  `tools/ops/reconcile_cve_tech.py` (so the tool and the scraper keep one definition). No migration.
- **Exception (user decision 2026-10-08)**: `reports/cve_record.py::applicable_to_stack` (the seventh matcher)
  is deliberately NOT unified. Its test (`test_cve_record.py`) locks `c++` ~ `c++ inc`, which contradicts the
  rule for short terms, and the Top CVE report does not follow the catalog path; its behaviour is not changed.
- **Other names for the same product** (`PAN-OS` for `palo alto`, `RouterOS` for `mikrotik`) are **not**
  handled without aliases; that is the catalog's job. Until the catalog exists, CVEs whose CNA product has a different name
  from the tech name are still rejected by the gate (the same limitation as 0.2.1; see 6).

**What changes in production if this branch is merged (read before deploying):**

1. No migration.
2. **`tech_stack` topic alerts and CVE priority scores may drop**: matcher 5 (substring without word
   boundaries) and 6 (two-way substring) are now whole-word. Pairs that used to match only as a substring
   (`go` ~ `google`) no longer do. That is the intent, but it shows up as a change in numbers/alerts.
3. **The worker image must be rebuilt before running `reconcile_cve_tech`** (the tool uses the matcher
   from the image, not from the `tools/` folder; same as the 0.2.1 note).

#### 7.1.2 Running the measurement spike

`tools/ops/spike_cve_catalog.py` (Python 3.10+ standard library only, no DB/network/image; runs on
the dev server or any laptop). Source: a CVE List V5 clone.

```bash
git clone --depth 1 https://github.com/CVEProject/cvelistV5          # several GB, once only
# optional, for recall against the tracker (run on a host with Postgres access):
docker compose --env-file docker/stack.env --profile app exec -T postgres psql -U cti -d cti -c \
  "\copy (SELECT DISTINCT cve_id, tech FROM cve_tracker WHERE tech IS NOT NULL) TO STDOUT CSV HEADER" \
  > tracker.csv
python3 tools/ops/spike_cve_catalog.py --source cvelistV5 --since 2025-01-01 \
  --tracker-csv tracker.csv --out spike_report.md --catalog-csv spike_catalog.csv
```

`--source` also accepts a release zip (nested zips are handled; that nested shape is an **assumption** not yet
checked against a real release, so use a clone if in doubt). `--id-years` widens the scanned ID years
(default: the year before `--since` up to this year; the year in a file name is NOT the publish year). Scale test:
60,000 synthetic files finished in 31 seconds and 154 MB.

The report answers: how many CVEs have a usable product (CNA, and rescued by ADP), how many raw
(vendor, product) identities vs normalised vs spelling-merged vs **product families** (Windows version
variants, etc.), kinds and examples of junk, the long tail (how many identities have >= 5 CVEs), merge candidates,
top products, **the verdict per 34 techs** (`bersih` (clean) / `satu vendor, banyak produk` (one vendor, many products) / `ambigu` (ambiguous) / `tidak ada` (none)),
and recall against the tracker (`keduanya` (both) / `hanya-tracker` (tracker only) / `hanya-katalog` (catalog only)). The report's "Measurement limits" section
says what is not measured.

**Read from 10 real 2025 CVE records used to validate the script** (not the full spike result):
(a) Microsoft writes every Windows version as its own product, so the catalog size is misleading without
family counts; (b) Palo Alto appears as `Palo Alto Networks` AND `paloaltonetworks` (from CPE), and
one tech touches many products (PAN-OS, Prisma, Cloud NGFW): a hierarchy case, not an ambiguous one;
(c) `kubernetes | ingress-nginx` matches the whole word `nginx` and its verdict is `bersih` (clean) although it is not F5 nginx:
the verdict measures name consistency, not product correctness, so human review is still mandatory.

#### 7.1.3 Spike results on the full data (2026-10-07)

Report: `docs/spikes/2026-10-07_cve_catalog_report_v2.md` (the fixed script; **the numbers below
come from this report**). The first report (`..._report.md`) is superseded: its script counted CJK names and
titles/`owner/repo` as junk. 153,413 files read, **117,220 CVEs published since 2025-01-01**.
The design derived from it: `docs/CVE_CATALOG_DESIGN.md`.

**1. Volume is growing fast.** 2025 = ~43.8 thousand CVEs; 2026 up to 7 October = ~73.4 thousand (already 1.7x last
year). Per month: March 2026 5.9 thousand, July 9.7 thousand, **September 14.9 thousand (3.9x September 2025)**.
Currently ~500 CVEs/day. With calendar-year retention, the mirror at the end of 2026 is > 130 thousand CVEs and 2027 may be
bigger still (a rough projection, not a measurement). The size is still reasonable for Postgres, but **ingest and the
filter must be designed for hundreds of CVEs per day, not dozens**.

**2. Spelling is not the main problem.** Raw identities 42,710 -> normalised 41,507 -> spellings merged 41,265:
automatic merging is only **242 (0.6%)**. Simple normalisation is enough; admin *merge* does not need to be
in the first version (in line with the "follow for now" decision). What remains to be merged is mostly **vendor spellings**
(`palo_alto_networks` vs `paloaltonetworks`, `n8n io` vs `n8n`, `graylog2` vs `graylog`).

**3. Catalog size is dominated by the long tail, not by variants.** 15,290 vendors (**79% have only one
identity**, 814 have >= 5); **62.9% of identities (26,117) have only 1 CVE**, 9,844 have 2-4, **5,546
(13.4%) have >= 5 CVEs**. Folding version variants only reduces it by 3.7% (41,507 -> 39,979), and **only 562
families have more than one variant (1,915 identities, 4.6%)**: outside Windows and devices
(Dell, D-Link, Siemens) a "family" is practically the same as a product. This means the picker must be **search-first**, with the initial view limited
to identities with >= 5 CVEs and search across the whole catalog.

**4. Granularity, not spelling, is the real problem.** The top list by CVE count is dominated by Windows
edition variants (each version/edition 1.4-2.5 thousand CVEs) and `linux | linux` (10,064, the kernel); the families with
the most variants: Dell Latitude 47, Siemens Industrial Edge 42, D-Link DIR 41 (device models). A list
sorted by popularity is useless without **family/vendor grouping**.

**5. Identity coverage.** **93.8% of CVEs have >= 1 usable product**; 6.2% (7,232) only have real junk
(placeholder `n/a`, `_`, generic words, URLs, digits). **ADP rescues only 42 CVEs (0.04%)**, so ADP
is not worth handling; **CPE is present in only 7.5% of CNA data**, so identities come almost entirely from free-form CNA
input (the old "CPE-based NVD query" plan does not have much material). 4,008 + 1,256 + 996 entries
have odd shapes (containing `and`/`&`, long titles, `owner/repo`) but are still real products. Vendors without a usable
name: `unknown` 1,236, `n/a` 520, empty 211 identities (4.7%); identities without a vendor need their own rule.

**6. Verdicts for the 34 techs: clean 10, one vendor many products 9, ambiguous 10, none 5.**
- *Clean*: anydesk, burp suite, ejbca, gitlab, harmony sase, microsoft 365, mikrotik, n8n, suricata, wazuh.
- *One vendor, many products* (needs a **vendor-level or per-family** choice): crowdstrike, fortinet
  (311 CVEs: fortios 80, fortiproxy 44, fortimanager 40, ...), juniper, junos, nessus, okta, palo alto (150),
  proofpoint, splunk (182).
- *Ambiguous* (third-party products also mention the tech name; **this is the cause of the 52 production `DELETE` rows**,
  and a choice a human must make in the picker): `nginx` (f5 nginx open source/plus 44 vs `0xjacky nginx ui`
  vs kubernetes `ingress-nginx`), `esxi` (vmware esxi vs an Intel driver that mentions esxi, vendor `n/a`),
  `jira` (Jira Align vs Jira Service Management/Software), grafana, graylog, mariadb (connector), nagios,
  outlook, proxmox, thales.
- *None*: `fortigate` (the CNA writes **FortiOS**, identity `fortinet | fortios` 80 CVEs: the tech name
  differs from the CNA product name), `new relic`, `maxscale`, `extrahop` (no CVEs in the window), `perimeter81`
  (none; the same product as `harmony sase`, so two production entries point to one product).

**7. Tracker recall: 65 of the 66 rows in the window were found by identity matching (98.5%).** The only
`hanya-tracker` (tracker only) is CVE-2026-75786 (Pandora FMS mentioning Grafana), **an already known false match**
(section 1 of this document), so every correct row was found. The tracker in the CSV is only 73 rows (7 outside the
window), far below the 125 rows of the production `reconcile` report: probably a different DB or already cleaned up,
to be confirmed. **The opposite direction cannot be concluded yet**: the catalog finds far more CVEs
than the tracker (fortinet 311 vs 2, palo alto 150 vs 0, splunk 182 vs 0, juniper 168 vs 0, microsoft 365
542 vs 2), but that mixes CVEs the pipeline MISSED with history published BEFORE the tracker/tech
existed. Separating them needs `--since` = the date `new_cve` started running, on the same DB.

**Design implications** (full design: `docs/CVE_CATALOG_DESIGN.md`):
1. What is *monitored* has **two levels (user decision 2026-10-07)**: **vendor** (every product, e.g.
   Fortinet/Splunk/Juniper/Palo Alto, which the production techstack indeed writes at vendor level) or
   **product family**. One entry may have **many targets** (`junos` = three Juniper families; `nginx` =
   two F5 families; `graylog`/`nagios` = two vendors spelled differently).
2. The picker presents a **tiered vendor -> family catalog**, search-first, default >= 5 CVEs.
3. Because 10 techs are "ambiguous", **mapping the 34 old techs to the catalog must be reviewed by a human** (the plan already exists);
   automatic guessing would repeat the keyword search's mistakes.
4. Automatic normalisation is enough for the first version; `n/a`/empty vendors and vendor spellings
   (`graylog2`/`graylog`) need rules, admin merging can come later.
5. Ignore ADP; do not depend on CPE; keep the fallback to the summary text for CVEs without an identity.
6. Search in the picker will not find tech nicknames (`fortigate` will not find `fortios`
   because the data does not contain that word); users search for "forti". That is a data limit, not a bug.

### 7.2 Supporting steps (not yet their own roadmap items)

1. **Measure recall.** A one-off script on the server: for each tech, compare the tracker's contents with a
   CPE query to NVD for the last 30-90 days, then report the missed CVEs per tech. The result decides
   how urgent phase 3 is.
2. **A table of filtered candidates**, the `rejected_articles` pattern: store dropped CVEs (`cve_id`, tech,
   product, reason) and show them in the UI so analysts can promote or close them. It replaces
   the `cve_candidate_tech_not_affected` log that is currently the only trace, and closes the risk of silent
   loss (the Graylog case).
3. **Version-based relevance** (roadmap #7): store the running version, compare it with the affected
   range, flag Affected / Not affected / Unknown. Needs tidy asset data.
4. **Small fixes** in `new_cve`: the doubled `<=` prefix, `seen_products`, a score fallback from NVD/ADP,
   `lastModStartDate`, and Tenable (an official API or drop it).

## 8. References

| What | Where |
|---|---|
| Scraper and gate | `scrapers/src/cti_scrapers/feeds/new_cve.py` |
| Cleanup tool | `tools/ops/reconcile_cve_tech.py` |
| How to run it | `docs/SCRAPER_MAINTENANCE.md` 4.G |
| Release 0.2.1 PR | PR #8 (`ikblmhndra/Vareon-Intelligence#8`) |
| Version-number correction | commit `f96d23b` (`nameless/dev`) |
| Shared matcher | `packages/cti-core/src/cti_core/tech_match.py` (on a branch, not yet on `main`) |
| Its callers | `packages/cti-enrich/src/cti_enrich/stages/score.py`, `apps/api/src/cti_api/services/cve_priority.py` |
| Techstack list for the scraper | `packages/cti-scraper/src/cti_scraper/reference_data.py` |
| Plan (new direction) | `docs/ROADMAP.md` #19 |
