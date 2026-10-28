# LLM as an assistant: enrichment redesign and CTI gaps

Status: **in progress** (updated 2026-10-28). Building blocks shipped in 0.8.3 and 0.8.4, and
P0 and P1 shipped in 0.8.5, P2 in 0.8.6, P3 in 0.8.7, P4 in 0.8.8 and P5 in 0.8.9 (see Progress
below). P6 is built for 0.8.10 (branch not yet merged to `main`); P7 has not started.

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

Shipped in **0.8.5** (P0 and P1, plus prompt correctness fixes):

- **P0 Measure.** `llm_calls` logs every LLM call (task, model, prompt version, tokens, latency,
  status `ok`/`empty`/`error`; 90-day retention via `llm.purge_calls`). Every call site names its
  task. Data health has an LLM section (status, parked articles, tokens per task over 24 h and 7 d).
- **P1 Self-healing enrichment.** Gateway config errors (400/401/403/404) are parked at once as
  `config`. `enrich.auto_replay` runs every 10 minutes: one canary article when the model status is
  unknown, a batch of up to 20 when healthy, at most 3 attempts with backoff, Telegram alert only for
  articles posted within 24 h. Existing `permanent` rows from those errors become `config`.
- **Prompt fixes.** Classify prompt shortened with boundary examples; TTPs kept only when the
  evidence is found in the full article text; newsletter metadata no longer invents content; TA
  profile built from ATT&CK data; exec brief separates threat news from confirmed incidents; CVE
  email uses computed fields; JSON mode on the six calls whose reply is parsed as JSON. The TTP
  evidence check is also the core of P2's "TTP evidence substring check".

Shipped in **0.8.6** (P2 cheap wins):

- **Tier 0.** `ScraperMeta.content_kind` / `default_relevance`: the structured sources `cisa_kev`,
  `exploitdb` and `cis` skip LLM classify and TTP extraction.
- **IOC hygiene.** IOC values are stored canonical (refang, lowercase; URL path and query kept) and
  the web shows them defanged. CVEs moved out of IOCs into `article_cves`. The allowlist now flags
  (`auto_suppressed`, reason `allowlist:<type>:<entry> (infrastructure-abuse)`) instead of dropping,
  with a curated seed of 124 domains (no tenant-subdomain services; a URL with a path is never
  flagged). Suppressed IOCs leave STIX export, stats, campaigns, recap counts and the FP queue;
  `GET /api/iocs?include_suppressed=`.
- **Confidence.** Default Admiralty grades per `content_kind` (`origin` default|analyst); article
  confidence = source grade + TTP/actor bonus instead of the LLM self-rating; chip "B2 · 72";
  one recompute-all task after the first start.
- Moved out of scope (spec section 6): CVEs in the article modal and `ArticleOut`; deterministic
  actor/malware/ATT&CK extractors (P4), local relevance model (P5), credibility from
  corroboration (P6); persist-first enrichment, token ceilings and caching.

Shipped in **0.8.7** (P3 story dedup at ingest, spec `docs/superpowers/specs/2026-10-25-p3-story-dedup-design.md`):

- **Stories.** A deterministic resolver (no LLM) groups articles about the same event into a `stories`
  row: shared CVE (at most 5 key CVEs, at least 50% overlap; ties go to the story with more members, then
  the lowest id), an identical title, or a similar title (TF-IDF >= 0.5, different source, period words such
  as "report"/"weekly"/month names ignored), within 72 h and a story age of 7 days. A CVE mismatch vetoes the
  title rules. `articles.story_id` / `story_match` record the link.
- **Inheritance.** A follow-up inherits the lead's classification and skips the classify and TTP LLM calls
  (TTPs stay on the lead; alerts stay per article). A Tier 0 member never fills or inherits
  `stories.classify`. `fetch_text` now runs before classify when `STORY__ENABLED=true`; the resolver runs
  in its own short session under an advisory lock so concurrent workers see one story per wave.
  A rejected lead keeps its story; only the daily `story.purge_empty` removes empty ones.
- **UI and measurement.** "+N sources" badge, "classification inherited" line, `GET /api/articles?story_id=`,
  story and avoided-call figures in Data health, and `python -m cti_enrich.story_backfill [--dry-run]`.
- **Replay on the 1,401-article dev snapshot** (`tests/fixtures/story_replay/dev_2026-10.json`): 171 follow-ups
  (12%) that would skip both LLM calls; PHP2Shell 24 articles in one story, NetScaler 15, Atlassian 9; the
  Asec monthly reports stay separate. The LLM-call reduction on a live wave still has to be measured on dev
  once the OpenRouter quota recovers.

Built for **0.8.8** (P4 deterministic extractors, branch not yet merged; spec
`docs/superpowers/specs/2026-10-25-p4-deterministic-extractors-design.md`, plan
`docs/superpowers/plans/2026-10-25-p4-deterministic-extractors.md`):

- **Tier 1 runs on every accepted article and complements the LLM** (classify and TTP extraction still run).
  Actor/malware dictionary over the full text (ATT&CK groups and software plus `threat_actor_groups`, alias
  -> canonical name; single-token and common-word names need a context word; Windows utilities only as
  `<name>.exe`). ATT&CK techniques from explicit `T####` IDs and a keyword map (~60 techniques). Industry
  keywords only when the LLM answered "General". The confirmed-incident rule is shadow-only (measured, not
  applied).
- **Provenance and read path.** `source` on TTP, actor and industry rows plus the new `article_malware`;
  inferred TTPs are computed on read (`GET /api/articles/{id}/inferred-ttps`).
- **Backfill and measurement.** Add-only `python -m cti_enrich.backfill_tier1`; evaluation harness
  `tools/eval/tier1_eval.py`.

### Evaluation (2026-10-25, silver standard)

- **Sample.** 100 accepted dev articles, stratified 40 with LLM TTPs / 20 with actors / 40 other, 34 sources.
  Text was refetched for 86 (14 failed). The sample unintentionally included best-practice articles (a literal
  bug in the filter, fixed after sampling).
- **Labels.** All 575 candidates on the 86 articles were labelled blind (no provenance) by an LLM subagent;
  20 random articles (113 candidates) were labelled again independently by a second, stronger LLM. Agreement
  92% (104/113; actor 21/24, TTP 57/61, malware 16/18, industry 4/4, incident 6/6). The user delegated the
  human adjudication step, so no human-verified labels exist.
- **Precision, full set (first labeller), after the evaluation-driven fixes.**
  - Actor dictionary 35/49 (71%) vs stored (LLM-era) actors 14/20 (70%).
  - TTP: explicit 101/102 (99%), keyword 52/74 (70%), LLM 51/144 (35%).
  - Industry keyword 5/5 vs LLM 19/49 (39%).
  - Malware/tool dictionary 28/59 (47%).
  - Incident rule 2/2 vs LLM 9/24 (38%).
- **Stricter second labeller, 20-article subset.** Actor dictionary 15/24 (63%) vs LLM 5/9 (56%); TTP
  keyword 18/22 (82%) vs LLM 20/39 (51%); malware 7/18 (39%).
- **Coverage, same stratified sample** (not dashboard population numbers): actor 23 -> 32, malware 0 -> 30,
  TTP 40 -> 58, specific industry 39 -> 40.
- **Fixes driven by the evaluation.** Windows-utility ATT&CK names (at, cmd, net, route, expand, reg, ...)
  only as `<name>.exe` (malware precision 22% -> 47%); common-word ATT&CK names need a context word; keyword
  rules for T1078 (0/5) and bare "powershell" (0/4) dropped.
- **Verdict against the P4 success criteria.** Met on silver labels for actor and TTP precision and for
  coverage; the actor margin is small. Malware precision is the weakest field (the second labeller treats
  legitimate OS binaries used by attackers as false).

Built for **0.8.9** (P5 local relevance model, branch `claude/p5-relevance-model-a447e0`, not yet merged; spec
`docs/superpowers/specs/2026-10-25-p5-relevance-model-design.md`, plan
`docs/superpowers/plans/2026-10-25-p5-relevance-model.md`):

- **Gate.** A local model (word and char TF-IDF plus MiniLM sentence embeddings, logistic regression, three classes
  `reject` / `best_practice` / `threat_news`) scores the title. When `p(threat_news) >= 0.85` the article skips the
  classify LLM call, takes its incident fields from the Tier 1 rule and carries `raw_enrichment.relevance`. Everything else
  goes to the LLM as before. Any failure in the relevance path falls back to the LLM.
- **Automatic gate.** The model starts in shadow (decisions recorded, LLM still called). `relevance.evaluate` (hourly)
  turns the gate on once at least 200 titles in 14 days show >= 95% agreement with the LLM, and off again when the audit
  sample drops below 92% over the last 50. `RELEVANCE__MODE=shadow` holds the gate off, `off` disables the model.
- **Audit sample.** 20% of gated articles (deterministic by URL hash) still call the LLM, so agreement keeps being
  measured and the model never trains on its own decisions (gated decisions are excluded from labels).
- **Weekly training.** `relevance.train` runs on Sunday 02:00 local on each instance's own labels (articles plus
  rejected articles, analyst overrides applied, titles deduplicated). Training needs at least 1,000 titles and 100 per class; a model is activated only if its 14-day time holdout shows
  >= 95% agreement and a band share >= 20% (otherwise the run is stored as `rejected` with the reason); the artifact is stored in `relevance_models` (one migration, `c4f1a9d27e6b`).
  A first model is trained within the hour after deploy, or up to 24 h later if that attempt is skipped or
  rejected (the retrain trigger has a 24 h cooldown).
- **Embedding story rule.** `STORY__EMBEDDING_SIMILARITY` (default 0, off) adds a MiniLM title rule to the P3
  resolver. Replay of the 1,390-title fixture at 0.8: 194 follow-ups (P3 replay without embeddings: 171), PHP2Shell 24 / NetScaler 17 /
  Atlassian 9 waves intact, Asec monthly reports still apart.
- **Image.** `worker-nlp` bakes the MiniLM model in at build (download ~90 MB, ~88 MB on disk) (downloaded from huggingface.co at a pinned
  revision); at run time it is loaded with `local_files_only`, never downloaded.
- **Data health** has a relevance section (active model, mode, gate state, band share, audit agreement, avoided calls).

### P5 evaluation (2026-10-26, prod labels, read-only export)

`tools/eval/relevance_eval.py` on 2,175 prod rows (2,112 distinct titles after dedup: 1,507 threat news, 359 reject,
246 best practice) with the real embedder, using the product's own train and decision code. Prod runs 0.8.2, so
`failure_kind` is empty (failed rows are caught by the `[enrichment_failed]` reason prefix); the exported classify audit
is passed to the product's label rules where present (most prod rows predate the audit trail).

| Split | Threshold | Band share | Agreement | Band n |
|---|---|---|---|---|
| 14-day holdout (n=871, train 1,241) | 0.85 | 54.5% | 98.1% | 475 |
| 14-day holdout | 0.90 | 49.8% | 98.6% | 434 |
| 5-fold CV (n=2,112) | 0.85 | 52.2% | 97.6% | 1,103 |
| 5-fold CV | 0.90 | 46.2% | 98.5% | 976 |

Release gate (agreement >= 95% and band share >= 35% at 0.85): met on both the holdout and the CV. The offline
experiment in the brainstorm (TF-IDF + embedding, same labels) gave 53% / 97.9% at 0.85 and 47% / 98.5% at 0.9, so the
product model reproduces it. Expected effect once the gate is on: about 52% x (1 - 0.2) = 42% fewer classify calls.
Measured avoided calls on dev and prod are still to be read from Data health after deploy.

### P5 on dev (2026-10-26): a dev-only threshold to remember

- **Dev `.env` differs from prod on purpose.** Dev has `RELEVANCE__MODE=auto`, `STORY__ENABLED=true`,
  `STORY__EMBEDDING_SIMILARITY=0.8` and **`RELEVANCE__GATE_MIN_AGREEMENT=0.94`** (backup of the previous file:
  `.env.bak-sebelum-0.8.9`). Prod keeps the default **0.95**: do not copy the 0.94 line to prod.
- **Why 0.94 on dev.** The first dev training (1,799 titles: 1,244 threat news, 295 reject, 260 best practice) reached
  94.89% agreement over 50.8% of the 14-day holdout (313 titles in the band) and was correctly rejected at 0.95, which left dev with
  no active model and therefore no shadow data. Dev labels come from the free OpenRouter models and are noisier than
  prod's (`gpt-4o`). With 0.94 the same model (id 2) became active in shadow. The same setting is also the threshold
  that turns the dev gate on, so the dev gate can open at 94%.
- **First shadow decision** (08:24-09:10 UTC): one article, in band (`p = 0.85`), accepted by the LLM, so it agreed.
  Dev ingests only a few articles per hour, so the automatic gate (200 in-band titles with an LLM verdict in 14 days) will
  take several days. Follow progress in Data health > Relevance model.
- **Revisit** when dev has a week of shadow data: if the shadow agreement on dev stays >= 95%, remove the 0.94 line so
  dev and prod use the same threshold.

Built for **0.8.10** (P6 Admiralty confidence and priority, branch `claude/p6-admiralty-confidence-9bbec2`, not yet
merged; spec `docs/superpowers/specs/2026-10-26-p6-admiralty-confidence-design.md`):

- **Scoring model.** One pure function, `cti_core.confidence.assess`, used by enrich persist and by every recompute.
  Reliability A-F is the source grade (`F` when the source has no row). Credibility 1-6 is computed **per article** from a
  rule ladder: 1 for a KEV source or 3+ story sources with an artefact, 2 for 2 sources or a primary source
  (`kev`, `advisory`, `vendor_research`, `exploit`) with an artefact, 3 for primary or artefact or 2 sources, 4 for a
  single aggregator without artefact, 6 for an ungraded source; 5 only by analyst override. Artefacts are a CVE, a
  non-suppressed IOC or an explicit TTP (LLM and keyword TTPs do not count). Confidence is the STIX 2.1 Admiralty scale
  averaged over both halves (A/1 = 90 ... E/5 = 10, F/6 = 50), so always 10-90; the P2 analyst confidence override still wins.
- **Priority.** `priority_score` = confidence + confirmed incident 25, KEV 15 (or PoC 8), 3 per explicit/LLM TTP (max 12),
  actor 8, 4 per extra story source (max 16), uncapped. Stored with `reliability_grade`, `credibility` and `score_reasons`
  (one additive migration, `d7a3e1b94c52`; `source_reliability_entries.content_kind` is filled from the scraper registry at
  API start).
- **When it runs.** At persist; `confidence.refresh_stories` (every 10 minutes) re-assesses members of stories that
  changed since the last successful run; `confidence.recompute_all` daily and once after deploy while any article is
  unassessed; `confidence.recompute_source` after a grade change.
- **Ranking.** `sort=priority` (dashboard "Perlu dibaca", Newsroom front section) orders by priority and keeps one article
  per story (`total` counts collapsed rows); the weekly recap candidates order by priority without collapsing.
- **API and UI.** `ArticleOut.admiralty_code` is now the article's code, plus `reliability_grade`, `credibility`,
  `priority_score`, `score_reasons`. `PUT /api/articles/{id}/credibility` sets or clears an analyst credibility override.
  The grade chip (`C1 · P131`, reasons in the tooltip) shows on the dashboard, Newsroom front section and list rows and the
  article modal, which also has a "Why this grade" section and the override control.
- **Source review.** `GET /api/sr/review` lists every `default` grade with 30-day statistics (articles, rejected share,
  artefact share, multi-source stories led, IOC FP share) and a suggested grade (never A; `null` under 10 articles);
  `POST /api/sr/entries/{id}/confirm` makes it an analyst grade in one click. The Source reliability page has a
  "Needs review" tab, and the entry dialog no longer asks for credibility.
- **Replay** (`tests/fixtures/confidence_replay/dev_2026-10.csv`, 1,546 dev articles, `tests/unit/test_confidence_replay.py`):
  the most common priority value holds 16.9% of articles (target <= 20%), the top decile spans 33 distinct values
  (target >= 20; before P6 it sat on 95-100), and 11 distinct Admiralty codes occur (target >= 8).

Not started: P7 (CTI model; persist-first
enrichment). Cost measurement over a week of real data is now possible
on dev.

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
| E5 | The same story is enriched many times: 16 accepted articles for "PHP2Shell" alone (the title search; counting articles that share its CVEs in the body as well gives 24, see the P3 spec). Dedup before enrichment is by exact URL hash only; the TF-IDF title clustering exists but runs only at API read time. | `/api/articles?search=PHP2Shell`, `services/dedup.py`, `services/cluster.py` |
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

Note for P5 if a sentence-embedding model is chosen: the same runtime can also feed the story
resolver. The P3 offline experiment (`all-MiniLM-L6-v2`, appendix A of
`docs/superpowers/specs/2026-10-25-p3-story-dedup-design.md`) found that adding "embedding cosine
>= 0.8" as an alternative to TF-IDF in the title rule gives about 13% more follow-ups at the same
precision (about 91%). Below 0.8 the model merges by topic, not event (about 68% precision in the
0.7-0.8 band). Use 0.8 or higher, keep the CVE veto and the other-source rule, and re-run the replay
test (`tests/unit/test_story_replay.py`) before switching it on.

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
| P0 Measure (**done in 0.8.5**) | `llm_calls` table + token logging on classify/TTP/tweets; model health probe on `/data-health` (empty-output guard for recap shipped in 0.8.3) | One week of real cost per call site visible on dev; misconfigured model shows red |
| P1 Self-healing enrichment (**done in 0.8.5**) | Articles parked as `[enrichment_failed]` are replayed automatically once the model probe is healthy again; a gateway 400/404 is treated as "wait for health", not permanent; the 218 parked rows on dev are recovered | After a gateway outage on dev, parked articles reach the news feed without anyone pressing Replay |
| P2 Cheap wins (**done in 0.8.6**) | `content_kind`/`default_relevance` on scrapers; refang + CVE-out-of-IOC + allowlist seed; TTP evidence substring check; drop LLM `confidence` from UI in favour of `services/confidence.py` | Structured sources make 0 LLM calls; duplicate defanged IOCs = 0; no TTP without verifiable evidence |
| P3 Story dedup at ingest (**done in 0.8.7**) | Clustering in `cti_core`, `story_sources`, skip Tier 3 for known stories | "PHP2Shell"-type waves enriched once per story |
| P4 Deterministic extractors (**built for 0.8.8**) | Actor/malware dictionary matcher, explicit + inferred ATT&CK, industry taxonomy, incident rule | Coverage (E9) measured before/after on the same article set; equal or better than LLM for actor and TTP precision on a 100-article hand-labelled sample. Measured 2026-10-25 on silver labels: met for actor (71% vs 70%) and TTP (keyword 70%, explicit 99% vs LLM 35%) precision and for coverage; malware precision 47% is the weakest field |
| P5 Local relevance model (**built for 0.8.9**) | Train on audit trail, shadow mode, then gate | Agreement with LLM >= 95% on the confident bands; LLM classify calls down by the measured share. Measured 2026-10-26 on prod labels at 0.85: holdout 98.1% agreement over 54.5% of titles, 5-fold CV 97.6% over 52.2%; the share of calls actually avoided is read from Data health after deploy |
| P6 Confidence (**built for 0.8.10**) | Grade all sources, Admiralty score in API/UI | Every article shows A-F/1-6. Replay of 1,546 dev articles: top priority value 16.9% of articles, 33 distinct values in the top decile, 11 Admiralty codes |
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
