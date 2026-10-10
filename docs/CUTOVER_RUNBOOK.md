# Cutover & Operations Runbook (Phase 10.G)

This document combines two things: the **cutover sequence** from the old system (Rundeck + Mongo + old web)
to the new platform, and the **operations guide** afterwards (backup, rollback, health, hypercare).
> The cutover of CVE Tracker filling from `new_cve` to the catalog + CVE mirror (ROADMAP #19) has its own runbook:
> `docs/CVE_CATALOG_CUTOVER.md`.

Every timing here was **measured in a staging drill** except where marked *not yet drilled*.
The "What is NOT yet proven" section at the end is deliberately honest about that.

> Ground rules: never paste/copy the contents of `.env` or any secret into chat, tickets, or logs.
> Check that something exists with `grep -q "^KEY=." .env`, not by printing its value.

---

## 0. Quick map

```
     nginx (compose; TLS, XFF)                 old Rundeck (100 active jobs)  ── SWITCHED OFF at cutover
                    │                          cti-web.service, nlp_worker, iocSyncer, mongod
                    ▼                                   (do not delete -- needed for rollback)
        web (Next.js BFF :3000)
                    │  /api/proxy/*
                    ▼
        api (FastAPI :8000)  ── postgres ── redis
                                   ▲           ▲
   beat ──(cron)──► queue ─────────┴───────────┘
        scrape.rss/api/notify/maintenance → worker          (RSS, API, reports, health digest)
        scrape.browser                    → worker-browser   (Chromium, 25 scrapers)
        enrich                            → worker-nlp       (spaCy + LLM)
```

For the data flows and code paths behind this picture, see `docs/ARCHITECTURE.md`.

| What | Value |
|---|---|
| Deploy | 1 VM, `docker compose --profile app` (postgres, redis, migrate, api, worker, worker-browser, worker-nlp, beat, web, **nginx**) |
| TLS / external access | the **`nginx`** service in compose (section 2.4): an automatic self-signed certificate or your own certificate; **only nginx** is exposed (80/443), api/web/postgres/redis only on `127.0.0.1`. Using your own host nginx? Template: `docker/ops/nginx-cti.conf.example` |
| Secrets | `.env` (chmod 600) for now; Vault after cutover (`docs/SECRETS_ROTATION.md`) |
| Image tag | `CTI_TAG` in `docker/stack.env` (e.g. `v20260927`); keep the previous tag for rollback |
| Report time zone | `WORKER__REPORT_UTC_OFFSET_HOURS=7` (WIB) |

---

## 1. Prerequisites (all must be green before T-0)

The gate checklist is in `docs/PROGRESS.md` ("Checklist cutover"). A summary the person running the cutover
must hold on to. **The four items that need manual work on the production host (Mongo backup
+ restore drill, Rundeck snapshot, rollback drill to the old stack, Postgres backup timer +
off-host copy) have step-by-step guides in `docs/PROD_PREP.md`** -- do those first.

- [x] **13 LEGACY secrets rotated** (10.F, see `docs/SECRETS_ROTATION.md`) -- **delegated to the user's ops
      team 2026-09-30**, executed by that team. This is about leaked tokens/credentials of the OLD apps
      (ScraperNews/ScraperNewsWeb/techstackLibrary + `legacy/config.yml`), NOT the new platform's secrets.
- [ ] **`tools/ops/check_secrets.py` is green with the PROD `.env`** (read-only: LLM `/models`, Telegram
      `getMe`/`getChat`, NVD, GitHub, twitterapi.io, the X bearer if set) -- this differs from the item above:
      it checks that the NEW secrets (from the filled-in `.env.prod.template`) work, not that the old ones have been
      revoked. On a host without `uv`: `docker run --rm --env-file .env -v "$PWD/tools:/tools:ro"
      cti-worker:$CTI_TAG python /tools/ops/check_secrets.py`.
- [ ] The prod `.env` is complete. The most often forgotten:
  - `TELEGRAM__THREAD_IDS` contains **all 22 topics**: `global apac apac_indo apt ot zero_day
    data_breach data_breach_indo vendor_report tech_stack tech_stack_unrelated best_practice darkweb
    pir scraper_health notd debug library_advisory logbook top_ta github_poc feed_twitter`. A topic used by the code
    but missing here = `UnknownAlertTopic` (a hard failure, not a silent wrong channel).
    **`github_poc` and `feed_twitter` are new (2026-10-02)**: env files created before then do not have them --
    add them, otherwise GitHub PoC / general tweet alerts fail on every run (the PoC data itself is still stored).
    `feed_twitter` = a dedicated thread for "general" tweets (formerly `global`/`apac`/`apac_indo`/`apt`); tweets in
    specific categories still go to `zero_day`/`data_breach*`/`vendor_report`/`ot`/`tech_stack*`. The tweet notice dedup key
    changed (`<id>:global` -> `<id>:feed_twitter`): tweets still within the search window at the first deploy
    may be re-sent ONCE to `feed_twitter`. `thread_id` 0 = no thread (goes to the main
    chat): if they are ALL 0, every topic piles up in one place. `check_secrets.py` prints a NOTE
    (`telegram_threads`). How to get a `thread_id`: right-click the topic > Copy Link, the last number in
    `https://t.me/c/<chat>/<thread_id>`; the chat must be a forum group (Topics enabled).
  - `TWITTER__API_KEY` (twitterapi.io = the PRIMARY Twitter source). `X__BEARER_TOKEN` only if the
    official X fallback is to be prepared -- **one underscore** between `BEARER` and `TOKEN`; a wrong name =
    the container fails to start (`extra="forbid"`).
  - `WORKER__REPORT_UTC_OFFSET_HOURS` (assumed 7 = WIB; set 0 if the old Rundeck server turns out to be UTC).
  - Compose-level variables (`BIND_ADDR`, `*_PORT`, `POSTGRES_*`, `CTI_TAG`, `TRUSTED_PROXY_HOPS`,
    `*_CONCURRENCY`, `NGINX_*`) go in `docker/stack.env`, **not** in `.env`.
- [ ] **nginx (section 2.4)**: `NGINX_TLS_HOSTS` in `docker/stack.env` holds the names/IPs people really use
      to open the platform; ports 80/443 on the host are **free** (`ss -ltnp | grep -E ':(80|443)\b'`,
      empty). The `X-Forwarded-For` header is already correct in the image config. If you use your own host nginx,
      it must set it (`docker/ops/nginx-cti.conf.example`) -- without it the login rate limit
      locks everyone out at once.
- [~] **Feed census** -- repeated from staging on 2026-09-30 after `warp-cli`/`warp-svc` (Cloudflare WARP)
      was switched off (staging's public IP went back to the real ISP, Moratelindo -- no longer a Cloudflare range). Result:
      **24 of 94 failed** (down from 30/92), and the comparison is informative -- see `docs/PROGRESS.md`
      for the details. **5 earlier failures DISAPPEARED** after WARP was switched off (strongly suspected to be an effect of the
      Cloudflare IP, not the sites actually changing): `monitor_x`/`new_cve` (rate limit, also helped by
      the 10.G2 pacing fix) + `ecrime` (timeout) + `cybersecnews`/`exploitdb`/`threatmon` (formerly
      "XML tak valid" (invalid XML) -- probably a block/CAPTCHA page wrongly parsed as a feed).
      **18 XPath mismatches EXACTLY THE SAME** before/after -- these are genuinely changed site selectors,
      not the IP, and need a code fix per scraper. **Fixed 2026-09-30 to 2026-10-01** (details in
      `docs/PROGRESS.md` 10.I, root-cause table in `docs/KNOWN_BROKEN.md`): 9 scrapers moved to
      `RSSScraper`, 8 use `link_card_xpaths`, the `sentinel`/`crowdstrike` category filters updated,
      `github_poc_monitor`/`new_cve` now wait for the rate-limit window, `monitor_x` fails hard when
      credit runs out. **5 written WAIVERS** (`enabled=False`): `blackberry`, `koisec`, `google`, `cisa`
      (Akamai WAF 403, not bypassed), `nquiring_minds`. Remaining: `intel471` not yet stable (Vercel 429), 5
      occasionally flaky scrapers (beat retry). Waived scrapers show as `disabled` in the health sweep.
      **Not yet repeated from the REAL PRODUCTION IP** -- staging is now trustworthy enough (WARP off),
      but production may still be re-tested if its egress differs again. **Health sweep after a full night
      (2026-10-02):** ok 85 / disabled 5 / zero_yield 2 (legitimate) / degraded 4 (all Twitter, credit exhausted).
- [ ] **Mongo backup < 24 hours old** + restore tested (user; the old dump = the only historical archive).
- [ ] **Old stack snapshot** (see 2.3) taken -- without it, rolling back to the old stack cannot be
      guaranteed in <5 minutes.
- [ ] A clean end-to-end rehearsal on staging (seed, warm start, prime, beat) with a large sample.
- [ ] Scheduled Postgres backup (section 6) and **one successful `verify`**.
- [ ] A second person knows where this runbook is and who decides on a rollback.

---

## 2. D-1 preparation

### 2.1 Build and tag

```bash
export CTI_TAG=v20260927                 # release tag; note the PREVIOUS release tag for rollback
docker compose --env-file docker/stack.env --profile app build
docker images | grep -E "cti-(api|worker|worker-nlp|web):$CTI_TAG"
docker images | grep cti-nginx          # edge: a FIXED tag (cti-nginx:1), NOT part of CTI_TAG
```

Build once per release. On a shared box, repeated builds pile up cache -- if disk is tight:
`docker builder prune -f --filter until=6h` (see section 9, "Disk full").

### 2.2 Verify secrets and configuration

```bash
docker run --rm --env-file .env -v "$PWD/tools:/tools:ro" cti-worker:$CTI_TAG python /tools/ops/check_secrets.py
docker compose --env-file docker/stack.env --profile app config -q   # compose syntax
```

### 2.3 Old stack snapshot (for rollback)

Take it **right before** the cutover, not at D-7 (the Phase 0 recording in `docs/legacy/` may be stale):

```bash
export RD_URL=http://10.8.20.78:4440 RD_PROJECT=Threat-Information RD_TOKEN=...   # keep the token OUT of history:
python3 tools/ops/rundeck_schedule.py snapshot --out rundeck-before-cutover.json  # `read -s RD_TOKEN`
# on the old server:
systemctl is-active mongod cti-web nlp_worker iocSyncer | paste - - - -   # note which are active
```

Keep `rundeck-before-cutover.json` **off** the old host and out of the repo (it holds job names, not secrets,
but still do not commit it).

### 2.4 nginx and the TLS certificate

The `nginx` service comes with `docker compose --profile app up -d`. Only `docker/stack.env` needs filling in:

```bash
NGINX_TLS_HOSTS=cti.company.internal,10.20.30.40      # EVERY name/IPv4 people use, comma-separated
NGINX_BIND_ADDR=0.0.0.0                               # default; the only service exposed externally
NGINX_HTTP_PORT=80
NGINX_HTTPS_PORT=443
```

- **A self-signed certificate is created automatically** when the container first starts (SAN = `localhost`, `127.0.0.1` +
  `NGINX_TLS_HOSTS`, RSA 2048, valid 365 days), stored in `docker/nginx/tls/` (gitignored + dockerignored:
  it holds the private key). Its fingerprint is printed to the log: `docker compose ... logs nginx | grep 05-selfsigned`.
- **Re-created automatically** if `NGINX_TLS_HOSTS` changes, the key does not match, or the remaining validity is <= 30 days
  (checked at start-up and every 24 hours, then `nginx -s reload`). Otherwise **the fingerprint is stable** across restarts.
- **Browsers will warn** ("not secure"/`ERR_CERT_AUTHORITY_INVALID`) -- expected for self-signed. To get a
  clean result, trust the certificate once per device:
  `docker compose ... cp nginx:/etc/nginx/tls/cti.crt ./cti.crt`, then import it into the OS/browser (macOS: Keychain Access ->
  Always Trust; Windows: Trusted Root Certification Authorities). If you see "**name mismatch**"
  (`ERR_CERT_COMMON_NAME_INVALID`), the address you opened is not in `NGINX_TLS_HOSTS`: add it, `up -d nginx`.
- **Your own certificate (internal CA)**: put `cti.crt` + `cti.key` in `docker/nginx/tls/` (or `NGINX_TLS_DIR`)
  before `up`. The generator **never touches them**, whatever the other settings. Replace the files, then
  `docker compose ... restart nginx`.
- Deliberately **no HSTS**: with self-signed, HSTS makes the browser refuse the "proceed" button entirely when
  the certificate changes. Add it once you use a CA certificate.
- The edge is not part of `CTI_TAG`: an application rollback (section 7.1) does not touch it, and a re-created `web`
  is found by nginx within <= 10 seconds without a restart.
- The healthcheck uses plain HTTP on the loopback listener `127.0.0.1:8081` (unreachable from outside the container), not
  https: busybox `wget` over TLS left orphan processes that made nginx write 2 `notice` lines every 15 s
  (~11,500 lines/day). The nginx log now contains only access logs of real requests.
- IPv6 is not yet supported by the certificate generator (use your own certificate).

---

## 3. Cutover (T-0)

This order comes from the 10.C/10.E notes. **The point of no easy return** is marked ⚠️: before it, rollback = turn
Rundeck back on; after it, the new platform has already written data that does not flow back to Mongo.

| # | Step | Command / notes | Estimate |
|---|---|---|---|
| 1 | Announce the cutover window | Telegram + team | -- |
| 2 | **Disable the Rundeck schedule** | `python3 tools/ops/rundeck_schedule.py disable --snapshot rundeck-before-cutover.json` then `... status` must be `0/N`. Let running jobs finish. | <1 min |
| 3 | **Stop** (not disable/mask) the old units | `sudo systemctl stop cti-web nlp_worker iocSyncer` (those active in the snapshot). `mongod` **stays up** (the dump + rollback need it). | <1 min |
| 4 | Final Mongo dump (10.4) | `mongodump` to a directory off the host; note its name/time. This is also the warm start source. | ~minutes |
| 5 | Bring up the foundation | `docker compose ... up -d postgres redis` then `up -d migrate api web` (no worker/beat!). `curl -f localhost:$API_PORT/healthz` | ~1 min |
| 6 | Seed reference data | `tools/seed/fase10_reference_data.py --dry-run` then without `--dry-run` (idempotent; how to run it: 3.2). The script prints the **list of old users**: re-create them through the UI with new passwords (old hashes are deliberately not carried over). Since QA 2026-10-01 it also fills `threat_actor_groups` (~4000), `monitored_people`, `ioc_allowlist_entries` -- without `threat_actor_groups` NO article gets a threat actor (empty TA dropdown, TA-based PIRs 0 matches). Check: the `threat_actor_groups` row count in the output > 0. | ~minutes |
| 7 | Dedup warm start | `tools/seed/fase10_warm_start.py --dry-run` then for real (how to run it: 3.2), with `--dump-dir <dump from step 4>` and `--legacy-dir <a fresh copy of /opt/ScraperNews/offset + /opt/techstackLibrary/offset>`. Without it every scraper starts cold (only the 5-item cap, alerts are still sent). | ~minutes |
| 8 | CVE tracker migration (Phase 10.F, optional but recommended) | `tools/seed/fase10_cve_migrate.py --dry-run` then for real (how to run it: 3.2), with `--dump-dir <dump from step 4>`. Fills `cve_tracker`/`cve_false_positives`/`cve_tickets` from the old Mongo history, so the CVE tab is NOT empty on day one (`new_cve` itself only reaches 8 days back). Idempotent, safe to repeat; CVEs that already exist (e.g. `new_cve` already ran) are not overwritten. | ~minutes |
| 9 | **Prime** watchers whose history cannot be carried over | `docker compose ... exec -T worker cti-scraper run <id> --prime` for `github_ttps sophoslabs_github mitre_github` and `techstack_npm techstack_pypi techstack_go` (those without offset files). Prime = a real fetch, marks EVERYTHING seen, **without** sending anything. | ~minutes |
| 10 | ⚠️ Bring up the workers, then beat | `up -d worker worker-browser worker-nlp`, wait until healthy, **last** `up -d beat`. Beat is the trigger: as soon as it is up, scrapers start running. | ~2 min |
| 11 | Smoke test | See 3.1 | ~5 min |
| 12 | Open the new platform to users | make sure host ports 80/443 are free (stop the old nginx/proxy holding them), then `docker compose ... up -d nginx`; test login from **another laptop** and check `audit_log` (3.1) | ~2 min |
| 13 | Announce completion; start the **4-hour watch** (section 4) | | -- |

### 3.0 Two steps not in that table but mandatory on an EMPTY database

The table above assumes a database that has been used before (staging). On a truly new host:

- **First admin**: `POST /api/auth/init` creates the first superadmin and only works while there are no users
  (409 afterwards; unauthenticated, so call it BEFORE nginx is opened to the network). Without it nobody can
  log in to "re-create users through the UI" (step 6).
- **ATT&CK catalog sync** (the Sync button in Intelligence > ATT&CK DB, or
  `AsyncAttackSyncRepo.sync_all_domains()` from inside the `api` container). The periodic task `attack_sync_check`
  will fill it on its own (domain status "never"), but do it BEFORE beat so the first articles already
  get normalised TTPs.

For a deploy from ZERO without an old stack, do not assemble this table by hand: `make fresh-deploy`
(`tools/ops/fresh_deploy.sh`, steps in `README.md`) does both automatically, plus seeding the default
reference data (`tools/seed/reference/`) in place of a Mongo dump for the three reference tables.

### 3.1 Smoke test (step 10)

```bash
curl -fs localhost:$API_PORT/healthz                                  # {"status":"ok"}
docker compose ... ps                                                # all healthy
docker compose ... logs beat | grep -E "beat_leader|beat_standby"      # exactly ONE beat_leader
docker compose ... exec -T worker cti-scraper dry-run bleepcomp         # one scraper, no DB writes
docker compose ... exec -T worker celery -A cti_worker.celery_app call scraper.health_digest   # one digest
python3 tools/ops/notify_telegram.py --env-file .env --topic debug --text "cutover: notification test"
curl -ks https://localhost/nginx-health                                # edge alive ("ok"); port per NGINX_HTTPS_PORT
docker compose ... exec -T worker cti-scraper run new_cve               # initial fill of the CVE tab (see the note below)
```

Then in the UI (/scrapers): **Trigger** one scraper and watch the run arrive with status `ok`/`empty`.

**The CVE tab is no longer empty at the start** if step 8 (CVE tracker migration) was run -- the history from the old
Mongo (`cve_tracker`/`cve_false_positives`/`cve_tickets`) is already in. If step 8 was SKIPPED: the tab is empty until
`new_cve`'s first hourly tick, and its history only reaches 8 days back (the NVD/Tenable search window per techstack)
-- techstacks added AFTER the cutover hit the same limitation, that is `docs/ROADMAP.md` item 3. If
`new_cve` shows `rate_limited` (the 60/minute limit on the MITRE domain), run it again; items already stored
are not lost.

**Client IPs must be real** (otherwise the login rate limit locks everyone out): log in ONCE from another laptop through
`https://<host>`, then

```bash
docker compose ... exec -T postgres psql -U cti -d cti -c \
  "select username, action, ip_address, at from audit_log order by id desc limit 3"
```

`ip_address` must be **that laptop's IP**, not `172.x.0.1` (the Docker gateway; see the troubleshooting row).

### 3.2 Running the seed scripts from a host without `uv`

The seed scripts need `pymongo` (not in the runtime image). Through the worker container, pymongo is installed temporarily
(the pattern used in the staging rehearsal, `seed_run.sh`):

```bash
docker run --rm --network <project>_default --env-file .env \
  -v "$PWD/tools:/tools:ro" -v /path/to/mongo-dump:/dump:ro -v /path/to/old-offsets:/legacy-offsets:ro \
  --entrypoint sh cti-worker:$CTI_TAG -c '
    pip install --target /tmp/pm -q pymongo &&
    PYTHONPATH=/tmp/pm python /tools/seed/fase10_reference_data.py --dump-dir /dump --dry-run'
# then without --dry-run; warm start: fase10_warm_start.py --dump-dir /dump --legacy-dir /legacy-offsets
# CVE tracker migration: fase10_cve_migrate.py --dump-dir /dump (does not need --legacy-dir)
```

### 3.2a Backfilling the enrichment of articles already stored (once, after the seed)

For a DB that already received articles BEFORE `threat_actor_groups` was seeded / before the
`mentioned` country role fix (staging 2026-10): threat actors are re-matched against the **titles** of old articles (summaries were not
stored, so old articles only get TAs named in the title) and `victim`/`actor` countries get
`mentioned` rows (Risk Matrix, country filter). No LLM, no alerts; it only adds rows, idempotent.

```bash
docker compose ... exec -T worker python -m cti_enrich.backfill --dry-run   # numbers + examples, rolled back
docker compose ... exec -T worker python -m cti_enrich.backfill
```

It refuses to run (exit 1, writes nothing) while `threat_actor_groups` is still empty. The Risk Matrix is cached
for 15 minutes per API process -- new results appear after that (or restart `api`).

### 3.3 What must not be done during the cutover

- Do not `systemctl disable`/`mask`/delete the old units, do not delete Rundeck jobs, do not delete Mongo --
  all of these are rollback material.
- Do not start `beat` before the warm start + prime are done (scrapers that run first are already past the cold
  phase; conflicting warm-start rows are skipped, and items already capped cannot be saved).
- Do not run two beats at once on two hosts (the Redis singleton lock protects, but do not rely on it).

---

## 4. Watching the first 4 hours (10.6)

| Check | How | Normal | Action if not |
|---|---|---|---|
| `enrich` queue | `docker compose ... exec -T redis redis-cli llen enrich` | goes up and down; **backpressure threshold 2000** | keeps rising: slow LLM/quota exhausted -> check the `worker-nlp` log, reduce load |
| `scrape.*` / `notify` queues | `llen scrape.rss` etc. | ~0 | piling up = worker dead/stuck |
| Health digest | the `scraper_health` thread | many `stale` at first (not run yet) -> shrinking | `dead`/`degraded` that persists = look at the last run in /scrapers |
| Error log | `docker compose ... logs --since 30m worker worker-nlp \| grep -E "ERROR\|Traceback"` | zero or a few | investigate per pattern |
| Telegram flood | the global/apt/... threads | cold scrapers max **5** items/scraper | far more = warm start problem: **stop beat** (`stop beat`), investigate |
| LLM | `OpenAIQuotaExhausted` log, `[enrichment_failed]` in /filtered-articles | none | quota/gateway; failed articles are recorded, not lost |
| Resources | `docker stats --no-stream`, `df -h /` | `worker-nlp` RAM stable | raise/lower `NLP_WORKER_CONCURRENCY` |

Behaviour that is **normal but surprising**:
- **The health digest is re-sent every 30 minutes while problems remain** (no dedupe; "silence = healthy").
  In the first hours it is long. This is deliberately simple; if it is annoying, dedupe/cooldown can be added.
- Scrapers whose **last run was long ago** show as `dead` until their next cron slot fires, even though
  the infrastructure is healthy (seen on staging right after beat was started).
- Twitter scrapers on the twitterapi.io free tier hit `429` and retry after 6 seconds (runs of 30-35 s, not failures).
- **A beat that was `stop`ped manually does NOT come back on its own** (`restart: unless-stopped`), and a partial deploy
  (`up -d worker web`) does not start it either. Staging incident 2026-09-26 15:42 -> 09-30 17:17 UTC: beat
  was stopped after a rehearsal, the schedule was dead for ~97 hours without anyone noticing (the health digest died too because
  beat schedules it). Now: a red banner on `/scrapers` + a Telegram alert (the `scraper_health` thread)
  from the **watchdog in the worker container** when the beat heartbeat is older than `WORKER__BEAT_HEARTBEAT_STALE_S`
  (300 s), repeated every `WORKER__BEAT_STALE_ALERT_REPEAT_MIN` (60), plus a "PULIH" (recovered) message. If beat
  is DELIBERATELY off (warm start, steps 5-8), that alert will indeed arrive -- ignore it until beat is started.
- A beat that comes back after a long outage does **not** fire every schedule at once: slots missed by
  more than `WORKER__BEAT_CATCHUP_GRACE_S` (600 s) are skipped to the next slot (the log
  `beat_stale_catchup_skipped` lists the entries). A short restart is still caught up.
- Retried runs (fetch_error/rate_limited) are recorded as `trigger=beat_retry`/`manual_retry`, with 60/120/240 s pauses.

---

## 5. One-week hypercare (10.7)

Daily (5 minutes): /scrapers (number of `dead`/`degraded`/`zero_yield`), the health digest, queue depth, disk, last night's backup
(`ls -la /var/backups/cti`), the `debug` thread.

Scheduled outputs you can check (WIB):

| Report | When | Topic |
|---|---|---|
| Daily counter | every day 23:55 | `debug` |
| News of the day | every day 23:58 | `notd` |
| Logbook (Excel) | checked every day at 07:00, sent every 14 days (the FIRST call only records the date) | `logbook` |
| Weekly top CVE | Sunday 07:01 | `tech_stack` |
| Top CVE tweets | 00/06/12/18 | `tech_stack` / `tech_stack_unrelated` + `vendor_report` |
| Threat actor trend | **Monday 13:00** | `top_ta` |

A missed report can be re-run by hand, e.g.
`celery -A cti_worker.celery_app call report.daily_counters --args='["2026-09-25"]'`.

---

## 6. Postgres backup & restore

Tool: `tools/ops/pg_backup.py` (stdlib; Postgres commands run in the container via `docker compose exec`).

```bash
PG="docker compose --env-file docker/stack.env --profile app exec -T postgres"
python3 tools/ops/pg_backup.py --pg-exec "$PG" backup  --dir /var/backups/cti     # dump -Fc + sha256, chmod 600, prune
python3 tools/ops/pg_backup.py --pg-exec "$PG" verify  --file /var/backups/cti/cti-<UTC>.dump
python3 tools/ops/pg_backup.py --pg-exec "$PG" restore --file <dump> --to-db cti_restore_test
python3 tools/ops/pg_backup.py --pg-exec "$PG" prune   --dir /var/backups/cti --keep-days 14 --keep-min 3
```

- **Schedule**: `docker/ops/cti-pg-backup.{service,timer}` (daily 02:30, `Persistent=true`), failure -> a Telegram
  alarm on the `debug` topic (`tools/ops/notify_telegram.py`).
- **Retention**: 14 days, and the 3 most recent backups are **always** kept (a backup job that stops running does not
  use up the stock). Age is computed from the file NAME, not mtime.
- **Off-host**: copy off the machine (rsync/rclone) -- not automated yet; a backup on the same disk is not a backup.
- **Moving hosts with a DB from a backup**: `make fresh-deploy ARGS='--restore-from <dump>'` (README.md, section
  "Deploy with a database from a backup"). `pg_backup.py` runs on the HOST's python3 >= 3.9.
- **Weekly verification**: `verify` restores the dump into a scratch DB, compares `alembic_version` and the row counts
  of key tables with the live DB, then DROPs the scratch. A dump never test-restored is not a backup yet.
- **`restore` safeguards**: refuses the live DB unless `--force-live`; refuses a non-empty DB unless
  `--replace`; checks the checksum + `pg_restore --list` BEFORE touching any DB.

Staging drill results (a small DB, 1.1 MB; the production DB will take longer, scale accordingly):

| Operation | Time |
|---|---|
| `backup` (dump + TOC validation + checksum) | 0.45 s |
| `verify` (restore into scratch + compare + drop) | 3.4 s |
| `restore` into a named DB | 1.2 s |
| Refusing a restore into the live DB / a non-empty DB / failure -> alarm | proven, exit 1 |

**Full restore into the live DB** (worst case: corrupted data) -- *not yet drilled on staging* (needs permission
because it is destructive). Procedure: stop the writers (`stop api worker worker-browser worker-nlp beat web`),
`restore --file <dump> --to-db cti --force-live --replace`, start again (`up -d`), check the row counts.
Drill it on staging before go-live and write the time down here.

---

## 7. Rollback

Three levels, from the lightest. **Decide the level first**, do not jump straight to the heaviest.

### 7.1 Platform version rollback (bad code, good data) -- 19-23 seconds

```bash
python3 tools/ops/rollback.py --current-tag v20260927 --tag v20260920 \
    --compose "docker compose --env-file docker/stack.env --profile app" \
    --env-file .env --network <project>_default --api-url http://127.0.0.1:8000/healthz
# add --yes if the pre-flight says a DB downgrade is needed; --dry-run to see the plan first
```

What it does (and why it must not be done casually by hand):

> ⚠️ **`CTI_TAG=<old> docker compose up -d` alone is DANGEROUS.** The `migrate` service runs
> `alembic upgrade head` on every `up`. If the DB is already at a revision newer than the old image knows
> -> `Can't locate revision` -> `migrate` fails -> compose has already **stopped** the running api/worker
> (they depend on `migrate`) -> **outage**. Proven in the staging drill (the API went down).

This tool: (1) reads the DB revision and the target image's head, (2) merges the migration history of BOTH images
(the old image does not know the new revisions), (3) if the DB is newer than the target -> `alembic downgrade` with the
**current** image (only it knows the new revisions), needing `--yes` because a downgrade can drop
columns/tables, (4) `up -d` with `CTI_TAG=<target>`, waits for the API + everything healthy, verifies the final revision.
It refuses (changing nothing) when the history branches, a revision is unknown, or `--yes` is missing.
**Take a backup first** (`pg_backup.py backup`) when a downgrade is coming.

Measured on staging (images already local): rollback 19.2-23.1 s (including the downgrade), roll-forward
22.3 s, a full back+forward cycle 41.9 s. Pulling images from a registry adds time.

### 7.2 Restoring data from a backup (corrupted data)

Section 6, "Full restore into the live DB". Data loss = since the last backup (daily) -- decide together.

### 7.3 Back to the OLD STACK (the new platform is called off) -- target <5 minutes, *not yet drilled in production*

Prerequisites: step 2.3 (snapshot) and nothing deleted in 3.3.

```bash
# 1. stop the new platform's writers (to avoid duplicate alerts with the old system)
docker compose ... stop beat worker worker-browser worker-nlp nginx    # nginx: frees 80/443 for the old proxy
# 2. start the old stack (what was active in the snapshot)
sudo systemctl start mongod cti-web            # + nlp_worker iocSyncer if active in the snapshot
# 3. re-enable exactly the Rundeck schedules that were on before
python3 tools/ops/rundeck_schedule.py enable --snapshot rundeck-before-cutover.json
python3 tools/ops/rundeck_schedule.py status --snapshot rundeck-before-cutover.json   # must be N/N
# 4. start the OLD proxy/nginx that held 80/443 (systemctl start nginx; nginx -t first)
```

What has to be accepted (decide before the cutover): data written by the new platform **does not flow back to Mongo**;
the old scrapers' offsets fall behind during the cutover window, so some alerts may be re-sent. That is why
the cutover window is kept short and its start/end times are recorded. **Drill this in production at least once**
(on and off with a stopwatch) before go-live; write the time: `____ minutes` (target <5).

---

## 8. Twitter data source: primary and fallback

Policy (user decision 2026-09-27): **twitterapi.io = primary and forced first; the official X API = fallback**,
used only when twitterapi.io really cannot be used. Switching is **manual**, per scraper.

- **When to switch** (a proposal, not yet confirmed by the user): key rejected / credit exhausted / service down -- visible
  as repeated `fetch_error`/`parse_error` on `tweet_alerts_1h`, `tweet_alerts_30m`, `trending_cve`, or a
  health status of `degraded`/`dead`. **Not** a reason to switch: free-tier 429s (there is retry+backoff, it is only slow),
  a difference of a few tweets between providers.
- **How**: /scrapers -> pick the scraper -> "Sumber data Twitter/X" (Twitter/X data source) -> `X API resmi (cadangan)` (official X API, fallback) -> Save Config.
  Applies from the next run. To go back: pick `twitterapi.io (utama)` (primary) or **Reset to Defaults**.
- **Official X cost** (pay-per-use): ~$0.005 per tweet read; the same tweet on the same UTC day is not
  billed twice. **`trending_cve` should STAY on twitterapi.io**: it searches every "CVE-<year>-" tweet
  across all of X (thousands/day). Set a **spending limit** in the X Developer Console before using it.
- Switching source does not cause duplicate alerts (dedup key = tweet id, the same in both APIs; proven on staging).
- Test before switching: `cti-scraper dry-run tweet_alerts_1h --option provider=x_official` (without changing the configuration).

---

## 9. Troubleshooting (all of these have happened in rehearsals)

| Symptom | Cause | Action |
|---|---|---|
| Everyone locked out of login after one person mistyped a password | the proxy does not send `X-Forwarded-For` (the compose nginx is already correct; this happens with your own host nginx) or `TRUSTED_PROXY_HOPS` does not equal the number of proxies | set the header (section 1); check `TRUSTED_PROXY_HOPS` |
| Browser: "connection not secure" / `ERR_CERT_AUTHORITY_INVALID` | self-signed certificate (expected) | trust `cti.crt` (2.4) or install a CA certificate |
| Browser: "name mismatch" / `ERR_CERT_COMMON_NAME_INVALID` | the address opened is not in `NGINX_TLS_HOSTS` | add that name/IP, `docker compose ... up -d nginx` (the certificate is re-created; trust the new one again) |
| nginx will not start: `address already in use` | 80/443 used by another process (host nginx/Apache, the old stack) | `ss -ltnp \| grep -E ':(80\|443)\b'`; stop it, or change `NGINX_HTTP_PORT`/`NGINX_HTTPS_PORT` |
| nginx: 502 Bad Gateway | `web` down/not healthy yet | `docker compose ... ps web` + `logs web`; nginx finds the new `web` within <= 10 s, no nginx restart needed |
| `audit_log.ip_address` is the same for every client (e.g. `172.x.0.1`) | (a) tested from **the same host** (localhost through docker-proxy always shows as the Docker gateway -- seen on staging); (b) Docker Desktop/rootless NATs every connection; (c) a load balancer/firewall in front of the host does SNAT | test from **another laptop**. If there is an LB in front of nginx: the LB must send `X-Forwarded-For` and `TRUSTED_PROXY_HOPS` raised to 2 (`docker/stack.env`). While the IP is the same for everyone, the login rate limit is global -- do not go live before this is fixed |
| A container fails to start, the log mentions an unknown field | a mistyped env var (`extra="forbid"`), e.g. `X__BEARER__TOKEN`, `TELEGRAM__BOTTOKEN` | fix the name; `__` = the nesting separator |
| `.env` broken after `echo "X=1" >> .env` | the file did not end with a newline -> the line got glued to the previous value (e.g. a **token**) | `printf "\nKEY=val\n" >> .env`; always verify afterwards |
| `alembic` fails with `SyntaxError: null bytes` when building from a Mac | macOS tar carries `._*` files (AppleDouble) | `COPYFILE_DISABLE=1 tar ...`; check `find . -name "._*"` |
| A rollback `up -d` takes the API down | `migrate` rejects a newer DB revision | use `tools/ops/rollback.py` (section 7.1) |
| `no space left on device` during a build | Docker build cache piled up (once 30 GB) | `docker image prune -f && docker builder prune -f --filter until=6h`; do not touch volumes |
| A Telegram alert fails with `UnknownAlertTopic` | the topic is not in `TELEGRAM__THREAD_IDS` | add it (thread 0 = the main channel) |
| `[enrichment_failed]` articles pile up | LLM gateway 401/quota/a non-JSON persona | check `python3 tools/ops/check_secrets.py`; `tools/llm/probe_json.py` |
| A scraper is `stale` although beat is running | it has not fired since beat started / it is disabled | wait for the cron slot; `enabled`? check /scrapers |
| A scraper is `dead` right after beat was started | its last run was long ago (from before) | expected until the next cron slot |
| After a long worker outage, a burst of runs on start-up | beat ticks piled up | already handled: scrape ticks expire after 1 interval (`expires`) |
| The health digest keeps coming | no dedupe, the problem is still there | fix the problem, or add dedupe |
| `monitor_x` (the X Intel tab) `fetch_error`/`rate_limited`, then `degraded` | the twitterapi.io **free tier** allows ~1 request/5-6 s for the whole key, shared by 4 scrapers (`monitor_x`+`tweet_alerts_1h`+`tweet_alerts_30m`+`trending_cve`) that all hit the same domain | **2026-09-30**: fixed -- the `rate_limit` of all 4 scrapers aligned to `10/minute` (before, `monitor_x` alone differed at `15/minute`, violating the `cti_scraper.ratelimit` invariant that a domain is shared evenly), a PROACTIVE `window_s/capacity` (6 s) pause between ACCOUNTS (not just reactively after hitting the limit), and `_get_with_backoff` now waits for the window to reset when OUR OWN LOCAL budget (not just a server 429) runs out first. **Proven live on staging 2026-10-01** (a new twitterapi.io key): `monitor_x` `ok` 385 s / 30 items (before: `empty` ~108 s without an error message because the credit was exhausted), `tweet_alerts_30m`/`trending_cve` `ok`; since then 401/402/403 fail hard (`parse_error` with the HTTP message). **That new key's credit ran out again within ~3 hours** (402 from 14:53 UTC; 120 failed runs overnight, 4 scrapers `degraded`) -- do not install a low-credit key in production; first work out the credit needs of the four scrapers sharing that balance. **The cause: `monitor_x` defaulted to `*/15` while legacy ran every 3 hours -- corrected to `8 */3 * * *` on 2026-10-02** (the cadence of all 4 Twitter scrapers is now locked to legacy by a test). If it is still `rate_limited`/`degraded` in production, the old options still apply: a paid twitterapi.io key, or a redesign to one OR query per run (losing the per-account `since_id`) |
| `new_cve` status `rate_limited` | the 60/minute limit on the MITRE domain exceeded (many CVE candidates) | normal occasionally; if persistent, candidates > 60/run: raise the scraper's `rate_limit` via /scrapers or reduce the techstack scope |
| `alembic current` fails on an old image | the DB is at a revision that image does not know | run it with a newer image / `rollback.py` |

**Known blind spots** (do not assume they are covered):
- The health digest is sent through the `notify` queue served by the **`worker`** container -- if `worker` itself
  dies, the digest cannot report it (the alarm dies with it). Monitor the containers from outside (an uptime monitor already
  on the host, or a cron `docker ps` + `notify_telegram.py`).
- A feed whose fetch succeeds but whose content is frozen (every item already seen) is not flagged (`zero_yield`
  only when the fetch returns 0 items). The replacement for the old `offsetAlert` does not detect this.
- Off-host backup is not automated yet.

---

## 10. What is NOT yet proven (honestly)

| Item | Status |
|---|---|
| Rollback to the **old stack** in <5 minutes in production | *not yet drilled* -- needs Rundeck/the old host (user). `rundeck_schedule.py` has only been tested against a fake API, not the real Rundeck |
| Full restore into the **live DB** | *not yet drilled* -- destructive, needs permission; its guards are unit + live tested (the refusals), the destructive step is not |
| Feed census from the **production IP** | not yet (staging egress differs) |
| **Deploy from zero** (`make fresh-deploy`) | proven 2026-10-02 on local Docker (arm64), clean-room from a copy of the repo: build from scratch, seed 3991/30/9, admin created, ATT&CK 943 techniques, login through nginx 200 (wrong password 401), exactly one `beat_leader`, 0 tracebacks, re-running changes nothing, 4 prerequisite failure paths. **Not yet**: a real Linux amd64 host, the `check_secrets` probe with real keys (in the drill: dummy secrets + `--skip-secret-check`; its failure path is proven), real load, scrapers firing from that host's IP |
| Production load: `NLP_WORKER_CONCURRENCY` > 1 with the real LLM, real volume | not yet; concurrency bugs only show up with the real LLM + parallelism (lesson from 10.B) |
| nginx (compose) + self-signed certificate in **production** | tested on staging (login, `Secure` cookie, redirect, certificate, `web` re-created) **including external clients**: a login from a laptop through the published port is recorded in `audit_log` with that laptop's IP, not the Docker gateway; + 44 automated tests (`tests/edge`, 62 mutations: 0 survived). **Not yet** installed on the production host |
| Postgres backup: systemd scheduling and the off-host copy | unit files ready, not yet installed/tested on the production host |
| Vault | post-cutover (`docs/SECRETS_ROTATION.md`) |
