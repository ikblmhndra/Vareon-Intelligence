# LLM as an assistant: enrichment redesign and CTI gaps

Status: **in progress** (updated 2026-10-24). A few building blocks shipped in 0.8.3 and 0.8.4
(see Progress below); phases P0-P7 have not started.

Goal: turn Vareon from "every article goes through an LLM" into a CTI platform where
deterministic code, curated reference data and analyst feedback do the bulk of the work, and
the LLM is called only where it adds value that code cannot. Expected effects: lower token
cost, no articles left waiting for a manual replay when the LLM gateway fails, and intelligence whose confidence means
something.

## Progress (2026-10-24)

Shipped in **0.8.3** (PR #71, quick fixes from `docs/UI_DATA_AUDIT.md`), which this plan builds on:

- **Feed dates.** The 61 RSS scrapers that used the scrape time now read `pubDate`, Atom
  `published`/`updated` or `dc:date`. Trend windows, spikes and the future story resolver
  depend on correct dates.
- **Actor matching** (a first piece of P4). Names that ATT&CK lists as software and not as a
  group are dropped from the actor dictionary and masked in the text; the longest name is
  matched first ("Cobalt Strike" no longer yields actors "Cobalt" and "Cobalt strike").
- **Titles normalised at ingest** (HTML entities, file-name titles from GitHub monitors), so
  classification sees clean text.
- **Empty-output guard for recaps** (part of P0). A parsed but empty model reply is not stored;
  the page shows an empty or unreadable recap as failed.
- **E14 rechecked.** A few hours later Data health showed 78 scrapers ok and 12 needing
  attention: the 37 `dead` were the scheduler restart, not broken scrapers.

Shipped in **0.8.4** (PR #73, step 1 of `docs/TARGET_ARCHITECTURE.md`, security half): every
endpoint requires a permission, so the LLM-spending and outbound actions (recap, exec brief and
TA profile generation, newsletter send, CVE email) now need `manage_intel`, `manage_newsletter`
or `send_cve_email` instead of any signed-in user.

Not started: P0 (`llm_calls`, model health probe), P1 (self-healing enrichment), P2 to P7.

Correction (2026-10-24, rereading against the code): E4 first said these articles were
"lost"; they are parked and replayable by hand, so P1 is now about recovering them
automatically. Persisting before the LLM moves to step 4 of `docs/TARGET_ARCHITECTURE.md`,
together with the `documents` table.

## 1. Evidence (dev instance 172.25.1.77, v0.8.2, read-only, 2026-10-24)

Numbers come from the API on the dev instance and from the code, not from guesses.

| # | Finding | Evidence |
|---|---------|----------|
| E1 | Every new URL costs at least one LLM call; every accepted non-best-practice article costs two (classify on the title, TTP extraction on the summary). Tweets cost one each. | `cti_enrich/pipeline.py` (`classify(title)`, `_extract_ttps_or_empty`), `monitor_x.py`, `tweet_alerts.py` |
| E2 | The classify system prompt is ~7,000 characters (~1.7k tokens) and is resent for every title, including the ~17% that end up rejected (284 of 1,652 classified titles on dev). | `stages/classify.py:40-148` |
| E3 | Worst case per article is 18 LLM calls (3 JSON retries x 2 steps x 3 Celery runs), because nothing is persisted before the LLM steps. | `tasks/enrich.py`, `pipeline.py` |
| E4 | **The LLM is a single point of failure.** 218 of 502 rows in `rejected_articles` are `[enrichment_failed]`: 128 x `400 Unsupported model mimo-auto` (gateway misconfiguration), 8 x other `APIStatusError`, 80 x `503`, 2 x `404`. Spikes on 16 Oct (91) and 23 Oct (82). Real incidents are in there (Quest Diagnostics breach, SBI PII leak, Storm-0940, M365 token spray). These articles are not lost but parked: `tasks/enrich.py` retries transient errors 6 times over ~30 minutes, then records the row, alerts on Telegram and waits for an analyst to press **Replay** (`POST /api/filtered-articles/{id}/replay`). A gateway 400/404 (wrong model name) is treated as permanent and never retried. About 12% of everything ingested sat outside the news feed until someone replayed it. | `/api/filtered-articles`, `tasks/enrich.py` |
| E5 | The same story is enriched many times: 16 accepted articles for "PHP2Shell" alone. Dedup before enrichment is by exact URL hash only; the TF-IDF title clustering exists but runs only at API read time. | `/api/articles?search=PHP2Shell`, `services/dedup.py`, `services/cluster.py` |
| E6 | Structured sources go through the LLM for no reason: CISA KEV entries titled just `CVE-2026-...`, Exploit-DB entries (`[remote] ... - command execution`), CIS advisories. | `/api/articles` samples |
| E7 | `confidence_score` is the LLM's self-rating x 100: 54% of articles are 90-100, none below 60. It carries no information. | distribution over 1,368 articles |
| E8 | TTP extraction hallucinates. Exploit-DB "Open eClass 3.15 - RCE" got PowerShell, DNS C2 and Keylogging; an opinion piece "AI Tools Are Generating Massive Attacks" got Boot/Logon Autostart. The prompt asks for an "exact phrase from input" as evidence, but nothing checks that the phrase exists. | `/api/articles`, `extract_ttps.py:20`, `cti_core/attack_ttp.py` |
| E9 | Enrichment coverage is thin: industry unspecified on 835/1,368 (61%), country on 17%, threat actor on 7%, TTP on 41%. | `/api/dashboard` `coverage` |
| E10 | IOC hygiene: defanged and refanged forms are stored as separate IOCs (`144.172.64[.]99` and `144.172.64.99`), 3,052 of 7,506 "IOCs" are CVE IDs, and legitimate services (`gofile.io`, `ably.io`, `litellm.dev`) are IOCs with no allowlist hit. | `/api/iocs` |
| E11 | Analyst feedback loops exist in the schema but are empty: IOC TP/FP feedback on 1 IOC, 3 of ~70 sources graded for reliability, 1 PIR, 1 (test) RFI, 0 campaign clusters. | `/api/iocs/fp-analytics`, `/api/sr/*`, `/api/pir`, `/api/rfi`, `/api/clusters/recent` |
| E12 | A failed LLM reply looked like a valid recap: the weekly recap for 2026-10-12 has an empty headline, `{}` forecast and 84 completion tokens for 8,432 prompt tokens (an unreadable reply kept in `raw_llm`), yet the page said "Grounding check: nothing was dropped". Fixed in 0.8.3. | `/api/recap/latest` |
| E13 | No token accounting for the high-volume calls (classify, TTP, tweets). Only recap and newsletter record usage. `llm.rate_limit` is defined but never read. | `cti_core/llm/client.py`, `config.py` |
| E14 | Scraper health showed 37 `dead`, 32 a few minutes later. The scheduler had restarted at 22:28 UTC, so this is mostly recovery, not 30+ broken scrapers. Recheck after a full day before acting. | `/api/scraper/health` |
| E15 | A 30-line naive Bayes on titles (5-fold CV over 1,368 accepted + 284 LLM-rejected titles, computed in the browser) puts 43% of titles at p >= 0.95 with **97.9% agreement** with the LLM. Its confident "errors" are mostly LLM leniency (Optiv awareness-training launch, Let's Encrypt cert lifetimes, DORA explainer accepted as cyber threat news), so the LLM labels are noisy themselves. The reject side is weak (50% at p <= 0.05) because there are only 284 negatives. | browser-side experiment, section 2 Tier 2 |
| E16 | `/api/articles?dedup=true` still returns all 16 PHP2Shell articles: title TF-IDF does not group the same story under different headlines. Story clustering must key on shared entities (CVE ID, named vulnerability, actor, victim) within a time window, with title similarity as a secondary signal. | `/api/articles?search=PHP2Shell&dedup=true` |

What already exists and should be reused rather than rebuilt: the regex IOC extractor, sumy
LSA summary, spaCy NER, pycountry, keyword lists in `stages/score.py`, the ATT&CK catalog
(718 techniques, 845 software, 193 groups, 21,819 relationships), 3,995 threat-actor names
from Malpedia/MSTIC/ORKL/etc., TF-IDF title clustering, the deterministic confidence score in
`services/confidence.py`, IOC decay and actionability, and the classify audit trail in
`raw_enrichment["classify"]` (about 1,900 labelled titles to train on).

## 2. Target pipeline

```
ingest -> normalise -> story dedup -> PERSIST (status=pending) -> deterministic enrichment
       -> relevance gate (rules + small model) --uncertain only--> LLM assist (async, budgeted)
       -> scoring (Admiralty + signals) -> alert
```

### Tier 0: structured sources skip classification

Declare it on the scraper, not in the prompt: `ScraperMeta.content_kind`
(`advisory`, `exploit`, `kev`, `vendor_research`, `news`, `vendor_marketing`, `social`) plus a
`default_relevance` (`always`, `classify`, `never`). KEV, NVD-like feeds, Exploit-DB, CIS and
vendor PSIRT feeds get `always` and a fixed `news_type`; no LLM call. This alone removes a
large share of calls (E6) and is a one-line change per scraper file.

### Tier 1: deterministic enrichment (runs for every article, no LLM)

| Field | Method |
|-------|--------|
| IOCs | existing regex extractor + **refang before hashing/dedup**, CVE moved to its own `article_cves` relation (not an IOC), allowlist seeded from Tranco top-10k + known SaaS/file-sharing/CDN domains, flagged as `context=infrastructure-abuse` instead of dropped |
| Threat actors | dictionary match over the 3,995 names + aliases (Aho-Corasick), word-boundary and case rules, ambiguous short names (e.g. "Cobalt") require a co-occurring keyword |
| Malware / tools | ATT&CK software (845) + Malpedia families, same matcher |
| ATT&CK | (a) explicit `T\d{4}(\.\d{3})?` IDs in the text (vendor reports list them), (b) procedure examples via the actor/software -> technique relationships already in `attack_relationships`, marked `inferred`, (c) curated keyword -> technique map for the top ~60 techniques |
| CVE | regex + join to `cve_mirror` (CVSS, KEV, EPSS) |
| Countries | pycountry + spaCy GPE (exists); victim vs actor role from actor-country lookup (the actor's known origin) rather than from the LLM |
| Industry | keyword taxonomy per industry (the 20 fixed industries) over title + first paragraphs; victim name -> industry lookup table that grows from analyst edits |
| Confirmed incident | rule: victim entity present + incident verb set (`breached`, `confirms attack`, `ransomware attack on`, `leak`) + not in a "how to / guide" pattern |
| Summary | sumy LSA (exists) |

### Tier 2: relevance gate without the LLM

Train a small classifier (TF-IDF + logistic regression, or a sentence-embedding model run
locally on CPU) on the ~1,900 titles the LLM already labelled, corrected by analyst
overrides. Output a probability.

- `p >= 0.85`: accept, `p <= 0.15`: reject, no LLM.
- `0.15 < p < 0.85`: send to the LLM (expected to be a minority; measure it).
- Every LLM verdict on an uncertain title becomes new training data; retrain weekly.

Shadow-run it next to the current LLM classify first and report agreement before switching.

### Tier 3: LLM as assistant

The LLM is called only for:

1. **Uncertain relevance** (Tier 2 middle band), with a **short prompt** (the 7k-char prompt
   is reduced to the decision and the fields code cannot fill), batched 10-20 titles per call.
2. **High-value articles only** for TTP extraction: `vendor_research` sources, confirmed
   incidents, or PIR matches. Input is the full text (not a 2,000-char summary) so that the
   evidence is real. **Every technique must quote a span that exists in the text**
   (substring check after whitespace normalisation); otherwise it is dropped. The result is
   merged with Tier 1 and each TTP is labelled `source = explicit | inferred | llm`.
3. **Analyst-triggered work** (already the case): TA profile, exec brief, newsletter summary,
   recap. Keep them, add caching and an empty-output guard (E12: reject and retry or mark
   `failed` instead of storing an empty recap).
4. **Story-level, not article-level**: once articles are clustered into a story (section 2,
   dedup), one LLM summary per story, not per article.

Guard rails for every LLM call:

- **Never on the critical path.** The article is persisted with deterministic fields first;
  LLM fields are filled by a separate `enrich.llm` task. A gateway outage (E4) then means
  "fields arrive later", not "article parked until someone replays it". Failed LLM tasks retry with backoff and a
  circuit breaker; the replay tool from #24 handles the rest.
- **Budget**: `llm_calls` table (call site, model, prompt/completion tokens, latency, outcome,
  article/story id). Daily token budget per call site with a hard stop that degrades to
  deterministic output. Enforce the existing `llm.rate_limit`.
- **Cache** by `(call_site, prompt_version, sha256(input))`.
- **Validate model config at startup**: a health probe that calls the configured model once
  and marks `/data-health` red (would have caught `mimo-auto` before 128 articles were parked).

### Story dedup before enrichment

Build a story key at ingest from Tier 1 entities (CVE IDs, named vulnerability, actor, victim)
plus the existing TF-IDF title similarity (`services/dedup.py`, moved into `cti_core`) as a
secondary signal, matched against the last 72 h (title similarity alone fails, E16): same story -> attach the new URL as an additional source of
the existing story (`story_sources`), bump `source_count`, skip Tier 3. Number of independent
sources becomes a credibility signal.

## 3. Confidence that means something

Replace the LLM self-rating (E7) with an explainable score:

- **Source reliability** (Admiralty A-F) per source: seed all ~70 sources once (a one-hour
  analyst job; currently 3 graded), then adjust from feedback.
- **Information credibility** (1-6) computed: number of independent sources in the story,
  vendor-primary vs aggregator, presence of technical artefacts (IOCs, CVE, TTP with evidence).
- Store both, show `B2` style in the UI, keep a numeric score for sorting.

## 4. CTI capabilities to make it a "proper" platform

Ordered by value for the effort, assuming Splunk is the first consumer.

1. **Entity model**: first-class `intrusion_set`, `malware`, `campaign`, `vulnerability`,
   `indicator`, `report` (= story) and a generic `relationship` table (STIX SRO shaped:
   `source_ref, type, target_ref, confidence, first_seen, last_seen, provenance`). Today
   campaigns are computed on the fly and malware has no table.
2. **TLP/PAP on every object** (column + inheritance from source default), enforced on export.
3. **Outbound**: TAXII 2.1 collection (`stix.py` already builds the objects) and a Splunk
   lookup/KV-store export of active IOCs with decay-based expiry.
4. **IOC lifecycle**: sightings (from Splunk hits), TP/FP feedback in the IOC UI one click
   away, automatic expiry by type (IP 30 d, domain 90 d, hash none), allowlist suggestions
   from FP analytics.
5. **PIR-driven collection**: PIR criteria matched at ingest (not only at read time), PIR
   matches raise priority and unlock Tier 3 LLM; weekly PIR coverage report. RFI linked to
   PIR and stories.
6. **Hunting packages**: for a story with TTPs/IOCs, generate (template, not LLM) a Splunk SPL
   pack: IOC search over the standard CIM data models + links to the matching Sigma rules
   (SigmaHQ indexed by ATT&CK ID). LLM may draft a hunt hypothesis on demand.
7. **Relevance to own assets**: join stories/CVEs to the techstack catalog (exists for CVEs)
   so the dashboard leads with "what affects us".
8. **MISP/OpenCTI connector** later, once the entity model exists (roadmap #8).

## 5. Rollout plan

Each phase is one PR with a small version bump (release convention), merged to `Dev` for
testing first. Phases 1-3 can start without schema redesign.

| Phase | Scope | Done when |
|-------|-------|-----------|
| P0 Measure | `llm_calls` table + token logging on classify/TTP/tweets; model health probe on `/data-health` (empty-output guard for recap shipped in 0.8.3) | One week of real cost per call site visible on dev; misconfigured model shows red |
| P1 Self-healing enrichment | Articles parked as `[enrichment_failed]` are replayed automatically once the model probe is healthy again; a gateway 400/404 is treated as "wait for health", not permanent; the 218 parked rows on dev are recovered | After a gateway outage on dev, parked articles reach the news feed without anyone pressing Replay |
| P2 Cheap wins | `content_kind`/`default_relevance` on scrapers; refang + CVE-out-of-IOC + allowlist seed; TTP evidence substring check; drop LLM `confidence` from UI in favour of `services/confidence.py` | Structured sources make 0 LLM calls; duplicate defanged IOCs = 0; no TTP without verifiable evidence |
| P3 Story dedup at ingest | Clustering in `cti_core`, `story_sources`, skip Tier 3 for known stories | "PHP2Shell"-type waves enriched once per story |
| P4 Deterministic extractors | Actor/malware dictionary matcher, explicit + inferred ATT&CK, industry taxonomy, incident rule | Coverage (E9) measured before/after on the same article set; equal or better than LLM for actor and TTP precision on a 100-article hand-labelled sample |
| P5 Local relevance model | Train on audit trail, shadow mode, then gate | Agreement with LLM >= 95% on the confident bands; LLM classify calls down by the measured share |
| P6 Confidence | Grade all sources, Admiralty score in API/UI | Every article shows A-F/1-6 |
| P7+ CTI model | Entity + relationship tables, TLP, TAXII, Splunk export, sightings, PIR at ingest, hunting packs | Per item in section 4 |

Success metrics tracked from P0: LLM tokens per accepted article, LLM calls per day by call
site, articles left parked as `[enrichment_failed]` after the model is healthy again (target 0), TTP precision on the labelled sample,
coverage percentages from `/api/dashboard`.

## 6. Open decisions

1. ~~v1 or v2~~ Decided 2026-10-24: implement in v1, independently of the v2 documents.
2. Acceptable cost/quality trade: is a local model for relevance acceptable, or must every
   accepted article still be confirmed by an LLM?
3. Which sources count as `vendor_research` (unlocks LLM TTP extraction).
4. Who grades source reliability and owns the allowlist.
