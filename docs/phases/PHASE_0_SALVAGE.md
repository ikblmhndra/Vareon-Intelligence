# Phase 0 — Salvage & Prep

**Status: `[~]` in progress · Blocking — do not start Phase 1 before this is done.**

## Why this phase is blocking

You chose a **big-bang rewrite**. A big-bang is only safe if there is a way to prove
the rewrite is still correct. Three things live only on the production server and
**cannot be reconstructed from source**:

| Asset | Why it cannot be reconstructed | If lost |
|---|---|---|
| `ScraperNewsWeb/static/` | Gitignored, 27 JS files, not in the repo | The entire frontend is gone — and it is the behavioural spec for the Next.js rewrite |
| Crontab | Was never in the repo | No way to know which scrapers are live and how often they run |
| `ScraperNews/config/config.yml` | Gitignored | No way to know the DB/collection names and the real config structure |

Plus one thing that has to be recorded **while the old scrapers are still running**:
**fixtures** — the old scrapers' output, to compare against the rewrite's results.
Once the old scripts are deleted, that baseline is gone forever.

> **Priority #1 today: `pull_static.sh`.** If the prod host dies before that is
> pulled, your frontend is gone. This outranks every other technical risk in the plan.

---

## Prerequisites

```bash
export CTI_PROD_HOST=user@prod-server        # adjust
export CTI_PROD_WEB=/opt/ScraperNewsWeb
export CTI_PROD_SCRAPER=/opt/ScraperNewsRevamp   # NB: the dir name differs from the repo name
```

Check the paths first:
```bash
ssh "$CTI_PROD_HOST" 'ls -d /opt/ScraperNewsWeb /opt/ScraperNewsRevamp 2>&1'
```

> **Transport notes.** Two things already found in the field:
>
> - `/usr/bin/rsync` on macOS is **openrsync** (rsync 2.6.9 compatible), not
>   rsync 3.x — the `--info=progress2` flag is rejected. The script probes and falls back
>   to `--progress`. For real rsync: `brew install rsync`.
> - **The prod host has no rsync.** `pull_static.sh` automatically falls back to
>   tar-over-ssh (`tar -czf - | tar -xzf -`), and if tar is missing too,
>   to `scp -r`. Nothing needs to be installed on prod.
>
> This host still uses **password auth**, so the scripts use SSH ControlMaster
> so the password is asked only once per run. To remove the prompt entirely
> (and make the other Phase 0 scripts nicer):
>
> ```bash
> ssh-copy-id "$CTI_PROD_HOST"
> ```

---

## 0.1 — Pull `static/` `[ ]`

```bash
./tools/salvage/pull_static.sh
```

Copies `$CTI_PROD_WEB/static/` to `legacy/static/`. It should get ~27 JS files
(`api.js`, `core.js`, `newsroom/*.js`, etc.) plus CSS.

**Verification:**
```bash
find legacy/static -name '*.js' | wc -l      # expect ~27
```

**Commit immediately.** Do not wait for the phase to finish.

---

## 0.2 — Record the crontab `[ ]`

```bash
./tools/salvage/dump_crontab.sh
```

Captures every user's crontab, `/etc/crontab`, `/etc/cron.d/*`, and systemd timers
into `docs/legacy/crontab.txt`.

**Verification:** the file contains lines like
`*/15 * * * * cd /opt/... && .../python3 bleepcompThreat.py`

**If the crontab is already gone**, the fallback: reconstruct the cadence from data —
group `threatintel.offsets.seen_at` by `script` and take the median gap between run
clusters. That is a decent lower bound. The last resort: per-family defaults
(RSS 15m, static XPath 30m, browser 2h) through `spread()`.

---

## 0.3 — Fetch `config.yml` `[ ]`

```bash
./tools/salvage/pull_config.sh
```

Stored at `legacy/config.yml` — **do not commit it** (it contains credentials; already
in `.gitignore`). Its purpose is to confirm the real DB/collection names before
the Postgres schema is designed.

---

## 0.4 — Mongo backup + restore test `[ ]`

```bash
./tools/salvage/backup_mongo.sh
```

Dumps `news_db` + `threatintel`, then **restores into a scratch container** and
compares document counts per collection. The script already does this —
a backup whose restore has not been tested is not a backup.

Since the cutover starts from an empty DB, this dump is the **only** archive of historical
data. Keep it off the prod host.

---

## 0.5–0.7 — Record fixtures (3 days) `[ ]`

```bash
./tools/salvage/record_fixtures.py --scrapers-dir ../ScraperNews --out ../cti-platform/tests/fixtures
```

For each old scraper, this script:
1. Patches `push_job` and `is_new_and_mark` so they **write nothing** —
   they only collect `(title, url)`
2. Saves the raw HTTP bytes → `<scraper>/<date>.input.*`
3. Saves the produced items → `<scraper>/expected_items.json`

Later, in Phase 4, the new plugin is given the same bytes and **must** produce
the same items. That is the cutover gate.

**Why 3 days:** feeds rotate. A one-day snapshot makes coverage feel
sufficient when it is not — a parser that only works on one item shape will
pass on day 1 and fail in production.

**Verification:**
```bash
ls tests/fixtures | wc -l                    # expect ≥200
```

### Prerequisite: the recorder venv

The old scripts need their fetch/parse dependencies. But they do **not** need the NLP stack
(spacy/sumy) because `modules.nlp` is stubbed, so the env is light:

```bash
./tools/salvage/setup_legacy_env.sh      # creates .venv-legacy
.venv-legacy/bin/python tools/salvage/record_fixtures.py ...
```

### Prerequisite: the context file

Some scrapers read their configuration from MongoDB. If that is empty, they
produce **0 items and the fixture lies**. Pull the data from prod:

```bash
mongosh "$MONGO_URI" --quiet --eval \
  'JSON.stringify(db.getSiblingDB("threatintel").techstack.distinct("name"))'
```

Put it into a file shaped like `tools/salvage/fixture_context.example.json`, then:

```bash
... record_fixtures.py --context tools/salvage/fixture_context.json ...
```

Affects `cisacatalogThreat`, `newCveThreat`, `techstackNPM`, `monitorX`.
This file also becomes the basis for the **reference data seed in Phase 10.1** — since the cutover
starts from an empty DB, `techstack` must be seeded or the CVE pipeline is dead.

---

## Field reality (from trial runs of the harness)

The harness has been tested against real scrapers. There are three failure modes you will
run into, and how to tell them apart:

### 1. Blocked by the site — the fixture is NOT valid

```
[  2/3] gbHackerThreat            0 item  BLOCKED
  gbHackerThreat    https://gbhackers.com/feed/
```

`gbhackers.com` returns a Cloudflare challenge page, not RSS. The old scraper
takes the `else` branch, prints an error, and finishes — silently zero items. Exactly the kind of
failure that has gone undetected all along.

**This means: record fixtures from the same IP as the production host**, because that is
where the old scrapers actually run. Recording from a laptop gives fake
fixtures for every site that filters by IP/geo. The easiest way:
rsync the repo to the prod host, run the recorder there, pull the results.

The recorder flags this as `BLOCKED` (403/429/5xx) and stores `http_status` +
`blocked_urls` in `meta.json`, so a bad fixture is not used silently.

### 2. A LEGITIMATE zero items — the feed is quiet

```
[  1/3] cisacatalogThreat         0 item  EMPTY
```

`cisacatalogThreat` filters `dateAdded` to today/yesterday. The CISA catalog's
last release was a few days ago, so zero is **correct**.

**This is why recording for 3 days is mandatory.** "EMPTY" cannot be told apart from
"broken" from a single day — and being unable to tell these two apart is exactly
problem #2 this revamp is meant to fix.

### 3. Scripts that really are broken — free findings

```
securityaffairsThreat    NameError: name 'html' is not defined
theRecordThreat          5 item, lalu NameError: name 'message_list' is not defined
```

`securityaffairsThreat` was already known (`lxml.html` is not imported).
`theRecordThreat` is a **new finding** — it pushes 5 items and then crashes, so all
along it has been running halfway without anyone knowing.

Record all of them in `KNOWN_BROKEN.md`. Broken scripts **do not need a golden
test** — there is no correct behaviour to preserve. What needs deciding
per script: fix it during the rewrite, or drop it.

---

## 0.8 — Secret rotation `[ ]`

See **[../SECRETS_ROTATION.md](../SECRETS_ROTATION.md)**.

Rotate **before** the old repos are imported into the monorepo, so the imported blobs
contain only dead values.

---

## 0.9 — Verify `torch` `[x]` DONE

```
torch                   → 0 importers
bert-extractive-summarizer → 0 importers
transformers            → 0 importers
sumy                    → used (nlp.py, nlp_worker.py)
```

**Conclusion:** `torch` and `bert-extractive-summarizer` are dead weight in
`requirements.txt`. Remove them. The enrich image shrinks by ~2.5 GB, so splitting the images
is no longer a heavy constraint — it is still done (Chromium & spaCy have no business
in the API image), but it is much cheaper than first estimated in the plan.

---

## 0.10 — Verify the `\b` regex bug `[x]` DONE

```python
# nlp.py:35,396,400,414 — NON-raw f-string → "\\b" becomes \b → CORRECT
if re.search(f"\\b{str(keyword).lower()}\\b", ...)

# nlp.py:421 — raw string → "\\b" stays a literal backslash+b → BROKEN
zero_day_list = re.findall(r"\\b(zero|0)[-.]day\\b", ...)
```

**Conclusion:** only **L421** is broken. Zero-day detection has never matched.
The other four lines are already correct — **do not "fix" them too**, that would break
what works. The plan has been corrected.

---

## Exit criteria

Phase 0 is done when all of these hold:

- [ ] `legacy/static/` committed, ~27 JS files
- [ ] `docs/legacy/crontab.txt` committed, containing the real schedule
- [ ] `legacy/config.yml` present locally (not committed)
- [ ] Mongo dump exists, **restore tested**, stored off-host
- [ ] Fixtures for ≥200 scrapers × 3 days
- [ ] 7 secrets rotated, `gitleaks` clean
- [x] `torch` finding verified
- [x] Scope of the `\b` bug verified

**If 0.5–0.7 cannot be completed** (host no longer reachable, feeds behind
auth), stop and say so. Without fixtures there is no way to prove the 206 rewritten parsers
are still correct, and the strategy has to drop to per-family — the old one
removed one family at a time, while the old stack keeps running for comparison.
