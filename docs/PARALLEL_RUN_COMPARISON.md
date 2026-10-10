# Comparing Legacy vs the New Platform (before legacy is switched off)

This checklist is used AFTER the new platform runs in parallel alongside the legacy app (user decision
2026-09-30: staging becomes the production candidate, legacy is NOT switched off right away -- compare first).
It differs from `CUTOVER_RUNBOOK.md` 10.6/10.7 (4-hour watch + 1-week hypercare, which checks that the new platform
is HEALTHY ON ITS OWN -- queue depth, error logs, resources) -- this document checks that the new platform
produces **output consistent with legacy** for the same sources over the same period. Both are
used together; neither replaces the other.

> **Prerequisite status (2026-10-01):** the QA 10.H fixes (`docs/PROGRESS.md`) are merged AND
> deployed to staging (~08:40 UTC, DB `c3a7e9d1f2b4`, `threat_actor_groups` 3995, beat + watchdog
> active). Remaining prerequisites in §0: test data/credentials cleaned up, the TTP rule decision, and
> twitterapi.io credit. The TTP comparison in particular needs care -- the staging remap produced a few
> odd labels (see `PROGRESS.md` 10.H, "Kualitas remap TTP").

---

## 0. MUST be checked BEFORE comparing (once, not daily)

> ⚠️ **The biggest risk of the parallel period: real users flooded with DUPLICATE alerts.** If the new platform
> and legacy both send to the same PRODUCTION Telegram channel/thread for the same
> article, every story arrives twice. Check ONCE before starting:

- [ ] The new platform's `.env` (on the host that is the prod candidate) uses a `TELEGRAM__BOT_TOKEN` /
      `TELEGRAM__CHAT_ID` **DIFFERENT** from the one legacy uses, OR, if the same channel is used on purpose,
      first disable sending on one side until the comparison period is over (legacy is usually
      easier: `systemctl stop` / disable the Rundeck job that sends, WITHOUT stopping its scraping
      -- if there is such a way; if not, point the new platform at a test chat first).
      Check WITHOUT printing the token: `grep -q "^TELEGRAM__BOT_TOKEN=." .env && echo set`.
- [ ] Both systems scrape the **same** sources (not different subsets) for the comparison period --
      cross-check the scrapers with `enabled=True` on the new platform against the jobs still active in legacy
      Rundeck (`docker exec cti-worker python -c "from cti_scraper.registry import discover;
      [print(c.meta.id) for c in discover()]"` vs the list of active Rundeck jobs).
- [ ] Agree on the comparison **time zone** -- the new platform runs in UTC (beat), legacy probably
      runs on the server's local time (check `date` on the legacy host). A wrong assumption = a "1 day difference" that looks
      like a bug but is just an hour offset.
- [x] **QA 10.H fixes deployed + post-deploy steps run** -- MET on staging 2026-10-01
      ~08:40 UTC (see `docs/PROGRESS.md` 10.H). Re-check every time the host is redeployed or
      moved: without this, the TA/Risk Matrix/PIR/TTP comparison is meaningless (before the deploy
      `threat_actor_groups` was EMPTY: empty TA dropdown, TA-based PIRs with 0 articles, TTPs not normalised).
      ```bash
      PSQL="docker compose --env-file docker/stack.env --profile app exec -T postgres psql -U cti -d cti -tAc"
      $PSQL "SELECT version_num FROM alembic_version"      # must be c3a7e9d1f2b4 (or newer)
      $PSQL "SELECT count(*) FROM threat_actor_groups"     # must be > 0 (expected ~3991)
      ```
- [ ] **The scheduler (beat) is healthy and stays healthy** -- see §1a. If beat is down even briefly, do not
      count that day as comparison data (staging was once down ~97 hours without anyone noticing).
- [ ] Test data and test credentials on the prod candidate host have been cleaned up (TA whitelist `testactor`/
      `testing`, the `stg-admin` password + leftover Phase 9 dev credentials) -- test data that comes along makes
      the new platform's counts "higher" than legacy for no real reason.
- [ ] The version running on the host = the intended `origin/main`. Staging is a **file sync, not a git
      checkout**: `git log` on the host cannot be trusted; use the DB revision (checked above) + the image tag
      as the reference.

---

## 1. Article coverage per scraper/source (most important, check daily)

Goal: prove the new platform catches the SAME articles, not just that "articles come in on both sides".

```bash
# Legacy (Mongo) -- article count per source for a given day. `posted_on` IN MONGO IS STORED
# AS A STRING "YYYY-MM-DD" (verified directly from the 2026-09-30 dump), NOT a Date --
# compare strings, do NOT use new Date(...) (a type mismatch = the query silently matches nothing).
mongosh "$MONGO_URI" --quiet --eval '
db.getSiblingDB("news_db").articles.aggregate([
  { $match: { posted_on: { $gte: "2026-10-01", $lt: "2026-10-02" } } },
  { $group: { _id: "$source", n: { $sum: 1 } } },
  { $sort: { _id: 1 } }
]).forEach(r => print(r._id + "\t" + r.n))'

# New platform (Postgres) -- the equivalent, per scraper_id. Use `posted_on` (NOT `created_at`) --
# for scrapers with `date_path=None` (the majority) both are the scrape time, so the fields are
# comparable; `created_at` in Postgres measures the row insert time, a different meaning from legacy
# `posted_on`.
docker compose --env-file docker/stack.env --profile app exec -T postgres \
  psql -U cti -d cti -c "
    SELECT scraper_id, count(*) FROM articles
    WHERE posted_on >= '2026-10-01' AND posted_on < '2026-10-02'
    GROUP BY scraper_id ORDER BY scraper_id;"
```

- [ ] Run this every day of the comparison period and compare the 2 tables above row by row.
- [ ] **`source`/`scraper_id` names are not always identical** (rebrands, etc.) -- see
      `tools/seed/fase10_warm_start.py` (the `ALIASES` dict) for the previously confirmed mapping of old labels -> new
      ids. If you find a different source that is NOT in `ALIASES`, that is a new
      finding; write it down.
- [ ] A small difference (1-3 articles/scraper/day) is NORMAL -- a polling-time difference when the snapshot was taken.
      A big difference (scraper present on one side, zero on the other) = investigate that scraper
      (check the `/scrapers` dashboard for its live status).
- [ ] Scrapers whose status on the new platform is `enabled=False`/dropped/parked (trellix,
      vxMalwareDefenseThreat, emailnewsThreat, cyborgHuntingIdea -- see `docs/PROGRESS.md`
      10.1c; plus the 5 census 10.I waivers: `blackberry`, `koisec`, `google`, `cisa`, `nquiring_minds`)
      are **EXPECTED to be zero on the new platform and non-zero on legacy** -- that is not a bug, it is a
      deliberate decision. Do not count it as a gap.
- [ ] **Scope DELIBERATELY different from legacy** (census 10.I, 2026-10-01) -- the daily article count may
      differ; that is not a missing scraper:
      - `cloudflare`: formerly resource-hub reports, now the `security` tag on the blog.
      - `intel471`: formerly whitepapers, now the blog (and **not yet stable**: Vercel 429 -- zero articles
        here = check the run status first, not automatically a bug).
      - `huntress`, `sysdig`, `cymru`: the WHOLE blog feed, without the old category filter.
      - `sans`: ALL white papers, not just the former focus areas.
      - `landth`: the domain became `depi.security` (the source is labelled "Depi (dulu L&H)", i.e. "formerly L&H"); old articles
        live on a different host, so do not match them by URL.
      - `sentinel`, `crowdstrike`: new category taxonomy (the old categories no longer exist on the site).
      - `monitor_x`: now fails hard when twitterapi.io credit runs out; legacy was silently empty.
        The schedule was aligned with legacy on 2026-10-02 (every 3 hours, `8 */3 * * *`); before that it was `*/15`, so
        tweet data before that date is denser than legacy -- do not compare per hour.
- [ ] **Data differences KNOWN from staging QA 2026-10-01** (report B, `docs/PROGRESS.md`
      10.H) -- record them as their own category, do not mistake them for a missing scraper:
      - Article titles are still **file names** (`2026-09-28-AgtaBackup-RAT-Campaign.txt`, etc.) from
        the GitHub watchers (`unit42_github`, `blackorbird_github`) -- legacy may be the same or different, check first
        before treating it as a new bug. `posted_on` may be empty (`""`) on some articles.
      - **HTML entities not yet decoded in titles** (B12) -- the same title can look different between
        legacy and new when compared text by text (§6).
      - APAC/Global classification misses on some articles (B14) -- that is an enrichment difference, not
        a coverage difference; do not count it in §1.

## 1a. Scheduler health (check daily, BEFORE trusting the §1 numbers)

The coverage numbers are only valid if beat ran for the whole day being compared. Check:

```bash
# 1) is the beat container up? (must be Up, not Exited)
docker compose --env-file docker/stack.env --profile app ps beat

# 2) runs in the last 24 hours -- almost all of them should be `beat` (+ `beat_retry`); if `manual`
#    dominates, beat is not running and someone is triggering by hand (that was the symptom of the 26-30 Sep staging incident)
docker compose --env-file docker/stack.env --profile app exec -T postgres \
  psql -U cti -d cti -c "
    SELECT trigger, count(*) n, max(started_at) last
    FROM scraper_runs WHERE started_at > now() - interval '24 hours'
    GROUP BY trigger ORDER BY n DESC;"

# 3) is the heartbeat fresh? (exists after the 10.H fix is deployed). JSON value {"last_tick": iso, "started_at": iso};
#    `last_tick` must be <5 minutes from the current `date -u`. An empty key = beat has never run with the new
#    code; a stale value WITHOUT a TTL is deliberate (the information is precisely "last alive at this time").
docker compose --env-file docker/stack.env --profile app exec -T redis redis-cli get cti:beat:heartbeat
```

- [ ] Last verified baseline (2026-10-01 ~07:40 UTC, BEFORE the 10.H fix was deployed): beat `Up 14
      hours`, 1837 runs/24 hours, all `beat`, latest 07:38 UTC. Before 30 Sep 17:17 UTC beat was
      down ~97.6 hours and there were only `manual` runs.
- [ ] The red "scheduler down" banner on `/scrapers` does NOT appear, and the Telegram `scraper_health` thread
      has no "Scheduler (beat) MATI/MACET" (down/stuck) message without a matching "PULIH" (recovered) (needs the 10.H fix).
- [ ] Days on which beat was down/restarted for long are **flagged and excluded** from the "3 green
      days" count in §7 -- not silently struck out; record the dates.

## 2. CVE tracker

```bash
# `detected_on` (a STRING "YYYY-MM-DD HH:MM:SS", verified from the 2026-09-30 dump) = when LEGACY
# started tracking this CVE -- the equivalent of Postgres `created_at`. Do NOT use `published` (that is the
# CVE's own publish date from NVD/the vendor, unrelated to when our system tracked it).
mongosh "$MONGO_URI" --quiet --eval '
db.getSiblingDB("news_db").cve_tracker.countDocuments({
  detected_on: { $gte: "2026-10-01", $lt: "2026-10-02" }
})'

docker compose --env-file docker/stack.env --profile app exec -T postgres \
  psql -U cti -d cti -c "
    SELECT count(*) FROM cve_tracker
    WHERE created_at >= '2026-10-01' AND created_at < '2026-10-02';"
```

- [ ] The number of new CVEs per day is comparable.
- [ ] False positive flag: sample a few CVEs flagged FP on one side and check their status on the
      other -- a difference in FP logic (if any) shows up here, not just in the count.

## 3. IOC

```bash
docker compose --env-file docker/stack.env --profile app exec -T postgres \
  psql -U cti -d cti -c "
    SELECT type, count(*) FROM iocs
    WHERE created_at >= '2026-10-01' AND created_at < '2026-10-02'
    GROUP BY type ORDER BY type;"
```

- [ ] On the legacy side, FIRST check which collection represents "new IOCs extracted from
      articles"; do NOT assume `threatintel.hash`/`ip`/`domain` (those collections look more like
      reference/allowlist data than a daily extraction log -- check whether a date field
      exists and makes sense for a per-day query before using it as the comparison baseline). If legacy has no
      clear "new IOCs per day", this section may be skipped -- the new platform's IOCs are EXTRACTED
      AUTOMATICALLY from articles (a new feature, `cti_enrich`), a different architecture from legacy, which seems
      to be manual/allowlist-based.

## 4. Twitter/X intel (`monitor_x`)

- [ ] Number of tweets recorded per monitored account, same period.
- [ ] **Special attention**: `monitor_x` on the new platform hits twitterapi.io rate limits (there is
      already pacing/backoff, see `docs/PROGRESS.md`) -- if tweets from a given account are ALWAYS
      fewer than legacy, consistently (not just occasionally), the pacing is
      not enough yet; it is not just noise.
- [ ] **twitterapi.io credit must be available first.** QA 2026-10-01: `monitor_x` got HTTP 402 "Credits is
      not enough" -- while credit is exhausted the new platform's tweet count is zero and that is NOT a scraper gap.
      402 is also not yet classified separately from `rate_limited` in the code (`_twitterapi.py` has no
      402 handling), so on the dashboard it looks the same as a rate limit -- check the error message
      in the run detail, not just the status.

## 5. Scheduled reports

Compare the CONTENT (not just "sent"), same period -- the full list of schedules & topics is in
`CUTOVER_RUNBOOK.md` 10.7:

- [ ] Daily counter (`debug`) -- the total articles/day is comparable with the §1 count.
- [ ] News of the day (`notd`) -- the list of titles that appears makes sense (not empty, no odd
      duplicates).
- [ ] Bi-weekly logbook -- the report content (incidents per category) is comparable.
- [ ] Weekly top CVE / threat actor trend -- the top-N numbers are comparable (the order may differ slightly if the
      scoring algorithm differs, but the TOP items must overlap heavily).
- [ ] **Threat actor/Risk Matrix is only comparable for articles that arrived AFTER the seed.** The 10.H backfill
      matched TAs against the **titles** of old articles only (summaries were not stored), so old articles get
      fewer TAs than in legacy -- that is a known limitation, not a bug. Compare TAs using a
      time window AFTER the seed ran. The Risk Matrix is cached for 15 minutes per API process: restart `api`
      after the backfill, or wait.
- [ ] **TTP: do not compare names, compare `ttp_id`.** The 10.H fix normalises TTPs to the ATT&CK catalog
      (revoked techniques/old names are mapped, tactic names dropped, ID vs name conflict = the name wins).
      Legacy still carries raw LLM labels that are sometimes wrong (e.g. `T1110` labelled "Credential
      Dumping"), so the heatmap will deliberately not be identical -- just check that the count per `ttp_id` is sane and that there
      are no duplicated columns.

## 6. Field integrity spot-check

Take 5-10 RANDOM articles from the same scraper on the same day and compare them field by field
(title, url, posted_on) between Mongo and Postgres -- not just that the counts match, but that the CONTENT matches too,
not a coincidence of equal counts with different articles.

## 7. Duration criteria & when it is "safe" to switch off legacy

- [ ] Run in parallel for **at least 1 full week** (so the weekly/bi-weekly reports go through one
      cycle, and weekday vs weekend variation is covered) -- in line with the 10.7 hypercare recommendation.
- [ ] §1-§6 above are GREEN (normal differences, not gaps) for **at least the last 3 consecutive days**
      before the decision to switch off legacy -- one green day is not enough, it has to be consistent.
      A day that fails §1a (beat down/long restart) does NOT count and the 3-day count restarts.
- [ ] No "Scheduler (beat) MATI/MACET" alert without a "PULIH" during the comparison period, and the 10.H fix
      is deployed (without it, beat going down again = silent, like 26-30 Sep).
- [ ] The Mongo restore drill + rollback of the old stack to Rundeck **have been tested** (see
      `docs/PROD_PREP.md` -- as of 2026-09-30 the restore was tested on staging, the rollback drill in
      PRODUCTION not yet) -- if the decision to switch off legacy turns out to be wrong, the way back must already be
      proven to work, not just documented.
- [ ] Everyone who needs access to the new platform (analysts, anyone who usually reads the legacy
      dashboard) already has an account & has actually tried logging in -- not an assumption that "it will work later".

---

**Once everything above is consistently green:** continue with the actual cutover part of `CUTOVER_RUNBOOK.md`
(10.3: stop the old cron). If ANYTHING is repeatedly red, do NOT switch off legacy -- investigate
the gap first until its root cause is clear (broken selector / real bug / a deliberate decision such as
trellix/vxMalwareDefense above).
