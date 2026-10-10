# Implementation plan: #21 Recap and #22 Newsletter

> **Status: plan only. Nothing here is built.** Scope and decisions are in `docs/ROADMAP.md` (#21, #22); this file
> turns them into pull requests, in order, with the files each one touches, the tests it needs and how to roll it back.
> Written 2026-10-10 from the code on `main` (0.4.1 + PRs #29-#31). The mockup is `docs/mockups/newsletter-redesign.html`.

## 1. Target and the date that drives the order

The next newsletter is the **October 2026 edition, due Monday 2 Nov 2026** (first working day of November; the
September edition went out on 1 Oct). It must be producible **by hand with today's flow** even if nothing below is
merged, so nothing here can block it. What this plan adds is: the redesigned Indonesian email, recommended articles
already placed in the composer, and an Executive Summary drafted from weekly recaps.

For the Executive Summary of the 2 Nov edition, weekly recaps for **28 Sep - 1 Nov** must exist (5 weeks, 5 LLM
calls). They are created by the manual weekly trigger (a backfill), so the weekly recap (PR 2) has to be **deployed by
Fri 30 Oct at the latest**; the target is a week earlier so someone can read the first output.

## 2. Ground rules for every PR

- One PR per slice below, each mergeable and revertible alone, each with its own tests. Branch from `main`.
- Hand-written alembic migration plus the model change in the same PR (`test_migrations_match_models`). Migrations
  are additive (new nullable or defaulted columns, new tables); nothing is dropped except the one unique constraint in PR 2.
- **New settings have safe defaults** and `.env.example` + `.env.prod.template` change in the same commit
  (`test_config`, `test_env_prod_template`). A required key would make the prod app refuse to start and roll the deploy
  back (CLAUDE.md, Deployment), so no setting is required.
- API changes: `uv run python tools/export_openapi.py` and `cd apps/web && pnpm run gen:api` in the same PR (CI drift check).
- Gates before pushing: `ruff check`, `ruff format --check`, `mypy` (strict, `cti-core` and `cti-scraper` only), unit +
  contract tests, and the integration tests for what changed. Web PRs: lint, `next typegen` + `tsc --noEmit`, build.
- Code comments, docstrings and commit messages in Indonesian, docs in English (CLAUDE.md). Releases bump the version
  files and `CHANGELOG.md` (Indonesian): one release after #21 (0.5.0) and one after #22 (0.6.0).
- LLM calls always go through one helper that records token usage (PR 1), so every later PR logs usage for free.

## 3. Order and dependencies

```
PR 1  usage logging + CVE ordering + baseline        (#21)  small, independent
PR 2  weekly recap: storage, collectors, generation  (#21)  needs PR 1; deploy by 30 Oct
PR 3  recap quality: comparison, grounding, scorecard(#21)  needs PR 2
PR 4  Recap page (web)                               (#21)  needs PR 3

PR 5  newsletter foundation: cache, pure preview,    (#22)  independent of #21
      one row per send, period columns, tiers
PR 6  template + logo + Indonesian summaries         (#22)  needs PR 5
PR 7  ranking + suggestions (API)                    (#22)  needs PR 5
PR 8  monthly schedule + executive summary           (#22)  needs PR 2, 7 (and PR 3 for the grounding helper)
PR 9  composer (web)                                 (#22)  needs PR 6, 7, 8
```

Recommended sequence, driven by 2 Nov: **PR 1, PR 2** first (they unblock the backfill and the summary), then **PR 5,
PR 6** (the visible improvement, usable by hand on 2 Nov), then **PR 7, PR 8, PR 9**, with **PR 3, PR 4** (recap quality)
slotted wherever there is room, in parallel if a second person is available. If time runs short, the cut line is:
PR 1, 2, 5, 6 are what the 2 Nov edition really benefits from; PR 3, 4, 7, 8, 9 can land after it without changing it.

## 4. PR by PR

### PR 1 - LLM usage logging, CVE ordering, baseline (#21) - size S

Why first: small, independent, and it produces the **baseline** the "fewer tokens" Done-when criterion needs.

- `cti_core/llm/client.py`: add `usage_from(completion) -> dict` (prompt/completion/total tokens, `{}` if the gateway
  returns none; the dev gateway may omit `usage`, so it must not raise) and a thin `chat_json(...)` wrapper if it
  removes the duplicated call code in `recap.py` and `newsletter.py`.
- `services/recap.py`: fill `token_usage` (today always `{}`); also record `input_chars` and the per-section item counts
  in it, so the size of the prompt is visible even when the gateway reports no tokens.
- Fix the CVE list: `CveTrackerRepo.list_registered_on` has `limit(50)` with **no ORDER BY**, so the 50 are arbitrary. Add
  an order (KEV, then PoC, then CVSS desc, then id) and the same for the 30 the prompt keeps.
- `LlmSettings.rate_limit` is declared and unused: either enforce it in the helper or delete the field (and its
  `.env.example` lines). Decide in the PR; deleting is the smaller change.
- Baseline: run the daily recap for a few recent days (`POST /api/recap/generate?force=true`) and write the measured
  `input_chars` / tokens into ROADMAP #21 under "Done when". Without this number the criterion cannot be checked later.
- Tests: unit for `usage_from` (present, missing, partial), for the ordering, and for `recap` storing the usage.

### PR 2 - Weekly recap (#21) - size L

- **Migration**: `daily_recaps` gets `kind` (`weekly`|`daily`, default `daily`), `period_start` and `period_end`
  (`Date`). Backfill existing rows: `kind='daily'`, both dates = `date`. Replace `uq_daily_recap_date` by a unique
  constraint on `(kind, date)`; for a weekly row `date` is the **Monday** of the week. The table name stays
  (`daily_recaps`), renaming it is not worth the churn.
- **Window**: Monday-Sunday by the **calendar dates the collectors already use** (`posted_on`, `func.date(...)`), which
  are UTC dates. That fixes the generation time: the week is only complete once Sunday ends in UTC, so the beat entry is
  **Monday 00:15 UTC = 07:15 WIB**, not 00:15 WIB (a 00:15 WIB run would miss Sunday 17:00-24:00 UTC). The newsletter
  task (09:00 WIB) still runs after it. The DB session timezone must be UTC for `func.date(timestamptz)` to mean what
  this assumes: a test or startup check asserts it.
- **Collectors**: the single-day repo methods (`list_registered_on`, `list_first_seen_on`, `list_added_on`, tweets)
  get range variants (`..._between(start, end)`). `AsyncArticleRepo.list_filtered` already takes a date range.
- **Aggregates, not a wider prompt**: per category take the top N by signal (confidence/score, confirmed incident,
  KEV/PoC, source reliability, cluster size), plus per-category counts via `GROUP BY`, and clusters collapsed to one
  line. The prompt grows far less than 7x. Output language stays **English**; forecast horizon becomes 1-2 weeks;
  `top_stories` caps are raised only as far as the baseline allows.
- **No-activity path**: a week with nothing to summarise stores a row with empty content and makes **no LLM call**.
- **Service/API**: `generate_weekly_recap(session, week_start, force)`; `POST /api/recap/generate` gets `kind` and
  `week_start` (a day can still be generated by hand: `kind=daily`, `date=`, unchanged); `GET /list`, `/latest` and
  `/{date}` return `kind` and the range. `/latest` returns the latest **weekly** row (today it assumes "yesterday").
- **Beat**: `recap.generate_weekly` on Monday 00:15 UTC (`crontab(day_of_week=1, hour=0, minute=15)`, queue
  `maintenance`). The daily entry is controlled by a new setting **`RECAP__SCHEDULE`** (`daily` default | `weekly`):
  flip it to `weekly` in prod after the first manual weekly run looks right; rollback is flipping it back. Beat builds
  its schedule at import, so a restart of `beat` applies the change.
- **Backfill** (needed for 2 Nov): after deploy, generate the weeks starting 28 Sep, 5, 12, 19 and 26 Oct by hand.
- Tests: unit for the window (week containing a month/year boundary, Monday start), the aggregate builder and the
  no-activity path; integration for the migration backfill, the unique `(kind, date)` rule (a weekly and a daily row
  on the same date coexist), the range collectors and the router snapshots (update with `--snapshot-update` after
  reading the diff).

### PR 3 - Recap quality: comparison, grounding, scorecard (#21) - size M

- **Migration**: add `quality` (JSONB, default `{}`) to `daily_recaps`.
- **Week-over-week comparison** (no LLM): `counts` of this week against the previous weekly row as absolute and
  percentage deltas, plus "new this week" for threat actors, campaigns and CVEs (set difference with the previous
  week's stored items). Stored in `quality.comparison`.
- **Grounding check** (no LLM): after parsing, every CVE id, threat actor, campaign theme, story title and source in the
  output must exist in the input sets used to build the prompt. Anything else is **removed from the displayed fields
  and listed** in `quality.grounding.dropped` (field, value), with the count. Nothing is dropped silently. The same
  function is reused by the newsletter summary (PR 8), so it lives in a shared module, not in `recap.py`.
- **Forecast scorecard** (same call, no extra call): the weekly prompt also receives last week's `likely_events` with
  their `basis` and `confidence`, and returns `forecast_review` (`hit|partial|miss|unclear` plus one line of evidence per
  event). Code stores it in `quality.scorecard` and computes the hit rate over the last 8 weeks, split by confidence.
- Tests: unit for the comparison (first week with no previous row, a CVE that appears twice), for grounding (an invented
  CVE id is dropped and listed; a real one stays; case and spacing), and for the scorecard maths with a stubbed LLM.

### PR 4 - Recap page (web) (#21) - size M

- `components/recap/recap-view.tsx` (219 lines) and `recap-history.tsx`: show the kind and date range, the
  week-over-week deltas, the count of items dropped by the grounding check (with a way to see them), the scorecard and
  the 8-week hit rate; history lists weeks. Types come from the regenerated `schema.d.ts`.
- Done check: lint, `tsc`, build, and a manual pass against a real weekly row.
- **Release 0.5.0** after PR 4 (or after PR 2 if the quality PRs are late: the weekly recap alone is shippable).

### PR 5 - Newsletter foundation (#22) - size L

All of it is invisible to readers, and it removes the defects found while scoping.

- **Summary cache**: new table `newsletter_article_summaries` (`article_id`, `language`, `key_points` JSONB, `summary`,
  `body_source`, `model`, `token_usage`, `created_at`; unique `(article_id, language)`). `generate_article_summary`
  reads it first; a hit makes no Playwright fetch and no LLM call. A `regenerate` flag per article bypasses it.
- **Side-effect-free preview**: `preview` builds from the cache and writes nothing (today it saves a row and writes IOCs
  and CVE mentions). `draft-email` does the **single** save, and the IOC/CVE-mention writes move into that save step.
  Test: preview twice, then draft, and count rows (exactly one) and LLM/Playwright calls (zero on the second preview).
- **Period columns**: `period_start`, `period_end` (`Date`, nullable) on `newsletters`; old rows keep `week`/`year`. The
  history list returns the derived label ("October 2026") when the period is set, else "Week N, YYYY".
- **Tiers**: the request schema gains `highlights: list[int]` and, per section, `full: list[int]` and
  `compact: list[int]`; limits move from "5 per section" to **full <= 4 (Highlights <= 3) and compact <= 15** (constants
  in one place, tuned after the first edition). The old fields stay accepted until PR 9 ships so the web does not break
  between PRs. Compact entries are built from the article row (no fetch, no LLM; a cached summary is used if present).
- Tests: unit for the cache hit/miss, the limits, the tier split; integration for the one-row rule and the router snapshot.

### PR 6 - Template, logo, Indonesian summaries (#22) - size L

- **Template**: rewrite `templates/newsletter_email.html` after the mockup: table layout, inline styles, 640 px
  container, fallback fonts, solid colours, hidden preheader, stacked under 480 px, English headings (Executive Summary,
  Highlights, Asia Pacific, Global, Indonesia, Campaigns, Analyst Note, Also Noted), full cards plus the compact list.
  First check who else extends `_base_email.html` (the CVE email may); if it is shared, the newsletter stops extending
  it instead of changing it.
- **Logo**: the PNG is added under the API's static/template directory (needs the file from the user, see section 6);
  `cti_alerts.mailer.create_graph_draft` gains `inline_images` (Graph `fileAttachment` with `isInline` and `contentId`),
  and the template references `cid:`. The preview in the browser maps `cid:` to a data URI so it renders there too.
- **Indonesian summaries**: both summary prompts (`_llm_summarize_with_body`, `_llm_summarize_from_metadata`) ask for
  Indonesian `key_points` and `summary` in the same call; CVE ids, products, actors, ATT&CK names and IOCs stay as
  written; a glossary (a small module, so it is reviewable and testable) is injected into the prompt. A `language`
  field (`id` default, `en`) goes on the build request and into the cache key. The metadata-only prompt's habit of
  writing "plausible" text is kept as is, but `body_source` is stored so PR 9 can badge such items.
- **Size guard**: the render returns `html_bytes`, and the preview response carries a warning above ~90 KB (Gmail clips
  around 102 KB).
- **Period/label**: the context uses the month label and range instead of ISO week; the subject becomes
  `[CTI Newsletter] Threat Intelligence Digest — October 2026`.
- Tests: a static test that the template contains none of `display:flex`, `display:grid`, `gradient` or external CSS; a
  render test with a fixed context (snapshot of the HTML); a Playwright render at 640 and 390 px (marked `playwright`,
  needs Chromium); unit for `inline_images` in the Graph payload with `httpx` mocked; unit for the prompt language and cache key.
- Real-client checks (Outlook desktop, Outlook web, Gmail) cannot be run from this environment: the acceptance
  screenshots come from the analysts' mailboxes (draft sent to themselves) and are attached to ROADMAP #22.

### PR 7 - Ranking and suggestions API (#22) - size M

- `services/newsletter_ranking.py`: a **pure function** over candidate rows (the articles of the window) returning, per
  article, a score, a section (APAC / Global / Indonesia), a tier and the list of **reasons**. Signals: confidence score,
  confirmed incident, KEV/PoC on mentioned CVEs, a hit on a monitored tech (#19) or on a client industry/country, source
  reliability, cluster size, APAC/Indonesia relevance; duplicate stories collapsed (reuse `services/dedup.py` and
  `services/cluster.py` where they fit instead of a new similarity routine).
- **Migration**: `newsletter_suggestions` (`period_start`, `period_end` unique, `items` JSONB of `{article_id, section,
  tier, rank, reasons}`, `summary_text`, `summary_meta` JSONB, `created_at`). No status column (not selected).
- API: `GET /api/newsletter/suggestion` (latest, or by period) and `POST /api/newsletter/suggestion/rebuild` (auth,
  rebuilds a window by hand; also what an analyst uses if the scheduled run was late).
- Tests: unit for the ranking with hand-made candidates (each signal changes the order; duplicates collapse; reasons
  are listed; caps respected); integration for the repository and the router snapshot.

### PR 8 - Monthly schedule and Executive Summary (#22) - size M

- **First working day**: a pure function `first_working_day(year, month, holidays)` (Monday-Friday, not in
  `holidays`), and `should_prepare(today, holidays, has_suggestion_for_previous_month)` which is true on the first
  working day **or** when the previous month still has no suggestion (the catch-up).
- **Settings**: a nested `NewsletterSettings` (`holidays: list[date]`, default empty) with `NEWSLETTER__HOLIDAYS` in
  `.env.example` and `.env.prod.template`; `extra="forbid"` still applies. Empty means weekends only, so the list has to
  be filled once a year (and before January, since 1 Jan is a holiday).
- **Beat**: `newsletter.prepare_monthly` every weekday at 09:00 WIB (`local_to_utc_cron(9, 0, offset)` gives 02:00 UTC;
  `day_of_week` Monday-Friday), queue `maintenance`. The task calls `should_prepare`; if false it returns at once.
  One suggestion per window makes it idempotent, and a duplicate delivery (`acks_late`) costs at most one extra LLM call.
- **Preparation**: build the candidate list for the previous calendar month, run the ranking, store the suggestion;
  then the **Executive Summary**: read the weekly recaps overlapping the month, one LLM call producing one Indonesian
  paragraph (about 100-130 words, no recommended actions), run the shared grounding check on it, store the text and the
  usage. No recaps for the window means an empty summary field and no call.
- Tests: unit for `first_working_day` (month starting on a weekend, a holiday on the 1st, a holiday on the first
  Monday, year change) and for `should_prepare` (the catch-up, the idempotent second run); the summary call with a
  stubbed LLM and recaps (grounding drops an invented CVE; no recaps means no call); a test that the beat entry exists and
  maps to 02:00 UTC.

### PR 9 - Composer (web) (#22) - size L

- On open, if the queue is empty the composer loads the suggestion; if the analyst already has a queue it shows a
  banner with "use suggestion" and "merge". The reasons are visible per article; the analyst accepts, swaps, removes,
  or promotes a compact row to a full card. "+ Newsletter" from the Newsroom keeps working (`lib/newsletter/queue.ts`
  stays as it is).
- The Executive Summary is an editable field. A badge marks items whose summary came from metadata only. The size
  warning from the preview is shown before the draft is created. History shows the month label and range.
- Remove the old request fields once the web uses the new ones.
- Done check: lint, `tsc`, build, then a manual run of the whole flow on a copy of production data (suggestion, edit,
  preview twice, create the draft once).
- **Release 0.6.0** after PR 9.

## 5. Cross-cutting

| Concern | Plan |
|---|---|
| LLM cost | Recap: one call per week (was seven) with a smaller input; scorecard and comparison add no calls. Newsletter: one call per cached article instead of per build, none for compact rows, plus one call per edition for the summary. Every call records usage (PR 1). |
| Rollback | PR 2: `RECAP__SCHEDULE=daily` and restart `beat`. PR 8: remove the beat entry or set the task to no-op; the composer works without a suggestion. Migrations are additive, so reverting the code leaves harmless columns/tables. |
| Observability | Log lines in the style of `cve_mirror_synced` for `recap_weekly_generated` and `newsletter_prepared` (window, counts, tokens, dropped items), so the worker log shows each run. |
| Docs | Update `docs/ARCHITECTURE.md` (recap/newsletter flows), the ROADMAP statuses, and a short runbook section for the monthly routine (where the suggestion appears, how to rebuild it, the holiday list). |
| Tests that need Docker | The integration and snapshot tests; they take about 7 minutes in CI, so group changes to avoid repeated `--snapshot-update` cycles. |

## 6. Risks

- **Deploy is unproven**: Deploy runs #8-#10 were all `cancelled` (ROADMAP #13). If merges to `main` do not reach the prod
  host, PR 2 will not be live by 30 Oct and the backfill cannot run. Check the host before relying on this plan.
- **Time zones**: the collectors use UTC calendar dates and the team works in WIB. The weekly boundary and the 07:15 WIB
  run follow the UTC dates; a story posted late Sunday WIB lands in the next week's recap. Accepted; stated on the page.
- **Gateway differences**: the dev LLM gateway sometimes returns no `usage` or an already-parsed object. The usage
  helper and the JSON parsing must keep tolerating both.
- **Indonesian quality**: wording will need analyst corrections (the glossary is how they stick). The metadata-only summary
  can state things the article does not, which is why it is badged and reviewed.
- **Email clients**: nothing here proves rendering in Outlook desktop; the template rules (tables, inline, no flex) are the
  mitigation, and the acceptance screenshots are the proof.
- **Holiday list**: if nobody updates it, the task can run on a public holiday (1 Jan); the analyst can still rebuild the
  suggestion by hand, so the cost is a wrong day, not a missing edition.

## 7. Needed from the user (before the PR that needs it)

| Before | What | Default if unanswered |
|---|---|---|
| PR 2 | Confirm the weekly boundary and time: Monday-Sunday, generated **Monday 07:15 WIB** (the earlier 00:15 WIB proposal would miss the end of Sunday UTC) | as written |
| PR 6 | The **logo PNG** in the repo, or `privy.zmidevelopment.com` added to the environment's allowed domains | the template ships with a text wordmark until the file exists |
| PR 6 | Confirm the heading **Campaigns** (written "Campaign") | Campaigns |
| PR 8 | Confirm the Executive Summary paragraph is **Indonesian** and the preparation time **09:00 WIB** | as written |
| PR 8 | The holiday list for the rest of 2026 and 2027 | empty (weekends only) |
| PR 6 / PR 9 | Analyst screenshots from Outlook desktop, Outlook web and Gmail | acceptance stays open |
