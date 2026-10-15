# Secret Rotation — Phase 0.8

**Status: `[x]` items 1-15 were delegated to the user's ops team on 2026-09-30 -- execution (revoking/replacing tokens in
their source systems) is done by that team, OUTSIDE this session/repo, so it no longer blocks Claude's side of the
work. There is no technical verification from this session that the old tokens are actually dead.
Items 14-15 were found LATER (Phase 10.1c port investigation, same session) and delegated
afterwards, so the delegation date is the same but the decision is separate from 1-13.**

Items 1–9 **were committed to git** in the old repos. Item 10 was found during Phase 0.3
(`config.yml` is gitignored, so it is not in git — but it exists on the prod host and
a copy is now on a laptop, so it still has to be handled).

Every secret below is in the
history, so all of them must be treated as **already leaked** — removing them from the
file is not enough, the value has to be replaced in its source system.

The order matters: **rotate first, then import the old repos.** If reversed, the imported
blobs would carry live credentials into the new repo.

> Never print or echo secret values while doing this —
> including to terminal logs, CI, or shell history.

---

## Inventory

Line locations were verified directly against the source.

| # | Location | Type | Action |
|---|---|---|---|
| 1 | `ScraperNews/threatActorTrendTele.py:9` | Graylog API token (`HTTPBasicAuth`) | Revoke in Graylog, issue a new one |
| 2 | `ScraperNews/threatActorTrendTele.py:24` | Telegram bot token | `/revoke` with BotFather, get a new token |
| 3 | `ScraperNews/threatActorTrendTele.py:26` | Telegram chat ID + thread ID | Not a secret, but move it to config |
| 4 | `ScraperNews/scripts/export_db.py:23` | Full Mongo URI + credentials (`news_db`) | Change the Mongo user's password |
| 5 | `ScraperNews/scripts/export_db.py:37` | Full Mongo URI + credentials (`threatintel`) | Change the Mongo user's password |
| 6 | `ScraperNews/scripts/import_db.py:60` | Mongo URI with credentials (f-string) | Same, same user |
| 7 | `ScraperNews/scripts/import_db.py:64` | Mongo URI with credentials (f-string) | Same, same user |
| 8 | `ScraperNewsWeb/insert_to_mongo.py:35` | Production Mongo credentials | Same — _being handled in a separate task_ |
| 9 | `ScraperNewsWeb/app/config.py:59-60` | Hardcoded internal `@privy.id` email addresses | Not a credential; move to `CVE_EMAIL_CC` |
| 10 | `legacy/config.yml` → `devo.token` | **Devo (SIEM) collector token** | Revoke in Devo. Low priority — the integration is skipped, but the token has been copied to a laptop. |
| 11 | `docs/legacy/rundeck-get-schedule.sh:5` | **Rundeck API token** | Revoke in Rundeck, issue a new one. The file is already gitignored. |
| 12 | `techstackLibrary/techstack{GO,NPM,PYPI}.py:5-7` (`/opt/techstackLibrary`, pulled in Phase 10.E) | **Telegram bot token + chat ID + thread ID hardcoded** in all three scripts (the SAME token). Found while porting the `techstack*` jobs to `techstack_npm/pypi/go` (Phase 10.E); the new code sends through the `library_advisory` topic, so this token is no longer used. | `/revoke` with BotFather (check whether it is the same bot as #2). The `techstackLibrary/` folder is OUTSIDE this git repo -- do not add it. |
| 13 | `legacy/config.yml` → `github.token` | **GitHub personal access token hardcoded in config.yml** (used by the old `githubPOCMonitor.py`). Found 2026-09-30 -- **its value was printed into an AI assistant session transcript** (a `sed` redaction pattern mistake, not deliberate; see the note below). Treat it as leaked regardless of this file's status (gitignored, never committed). | Revoke it on GitHub (Settings -> Developer settings -> Personal access tokens) NOW, regardless of the cutover date. The new token for the new platform's `GITHUB__TOKEN` is created separately (do not reuse the old one). |
| 14 | `ScraperNews/emailnewsThreat.py:26` | **Hardcoded Gmail app password** (IMAP login to `imap.gmail.com`, personal account) used to poll CTI newsletters. Found 2026-09-30 during the Phase 10.1c port investigation -- this script does not fit the new scraper framework (not a web scraper, IMAP-based), so it is "out of migration scope", BUT the credential still has to be revoked regardless. Its value was NOT printed to the shell/transcript of this session (unlike item #13 -- this time it was found by `Read`ing the file directly, not by an echo). | Revoke that app password in the Gmail account concerned (Google Account -> Security -> App passwords), not just change the main account password. |
| 15 | `ScraperNews/cyborgHuntingIdea.py:47` | **Hardcoded login password** (email + password) for a paid `hunter.cyborgsecurity.io` (Cyborg Security Hunter) account. Found 2026-09-30, same investigation session as #14. This script is not an alert scraper (a one-off research tool that dumps hunting rules to local JSON, no `push_job`/`send_alert`), so it is also "out of migration scope" -- but the paid account's credential still needs rotating. Its value was NOT printed to the shell/transcript of this session. | Change the account password on `hunter.cyborgsecurity.io`; also check whether the account is used elsewhere (password reuse). |

Note: `app/config.py:30` and `:51` build URIs from env vars — **that is
fine**, leave it.

---

## NEW secrets used by the platform (not from the leak)

Listed here so they are included in periodic rotation and moved to Vault later.

| Env | For | Notes |
|---|---|---|
| `TWITTER__API_KEY` | twitterapi.io (the DEFAULT Twitter source: `tweet_alerts_*`, `trending_cve`, `monitor_x`) | Issue/rotate in the twitterapi.io dashboard. |
| `X__BEARER_TOKEN` | the OFFICIAL X v2 API (alternative source, selected per scraper in the control plane) | **Bearer only (app-only).** The consumer key/secret and access token/secret are NOT used (reading/search does not need them; they are for posting) -- do not put them on the server. Rotation: regenerate in the X Developer Console. Pay-per-use: set a **spending limit** in the console; every tweet read is billed. **ONE underscore** between `BEARER` and `TOKEN` (`__` = the nesting separator; `X__BEARER__TOKEN` makes the container fail to start). |
| `ABUSEIPDB__API_KEY` | AbuseIPDB IP reputation (IOC enrichment, ROADMAP #4) | Issue/rotate in the AbuseIPDB account. Empty = provider off. The free plan allows 1000 checks/day; `ABUSEIPDB__RATE` (default `40/hour`) keeps the platform under it. |
| `VIRUSTOTAL__API_KEY` | VirusTotal reputation (IOC enrichment, ROADMAP #4) | Empty = provider off. **The public (free) API must not be used in commercial products or services** (per VirusTotal's own terms): use a key from a plan whose licence allows it. `VIRUSTOTAL__RATE` defaults to `20/hour` (public limits: 4/min, 500/day). |
| `OTX__API_KEY` | AlienVault OTX (IOC enrichment, ROADMAP #4) | Issue/rotate in the OTX account (Settings -> API Integration). Empty = provider off. `OTX__RATE` (default `300/hour`) caps platform lookups; OTX itself allows far more. |

---

## Secret architecture: now vs production

Two phases, deliberately different:

| | Now (dev / pre-production) | Production |
|---|---|---|
| Source | `.env`, one file, centrally controlled | **HashiCorp Vault** |
| `SECRETS_BACKEND` | `env` (default) | `vault` |
| Reader | `cti_core.settings` directly from env vars | `cti_core.settings` through a Vault client |
| Vault status | **already in `docker-compose.yml`**, opt-in via `docker compose --profile vault up` — dev mode (in-memory, not persistent), tested: auto-unseal, KV v2 enabled at path `cti/`, write/read confirmed | not yet — the `cti_core` Vault reader integration is done in the testing phase |

**Why it is split this way:** the Vault integration (client, path convention, AppRole/token
auth) is real Phase 2/testing work, not something that can be finished
now without app code. Putting Vault in the stack NOW means the integration
can be tested at any time without waiting for a "big migration" moment, and the
path layout (`cti/telegram`, `cti/mongo`, etc. — matching the section names in
`.env.example`) can be designed from now on.

**Timing of the real token rotation:** done in the testing phase, together with the
actual Vault integration — no need to rotate twice (once for `.env`, once more
for Vault). Only two things are mandatory now:

1. The list below is complete and accurate
2. Nothing is committed to the new repo — already safe, every file
   containing credentials is in `.gitignore` and the first commit has been verified

⚠️ One exception that cannot be postponed: rotate **before** the old repos
are imported into the monorepo (Phase 1), so the blobs that come along contain only dead values.

## ⚠️ Operational hazards found in the field (not just in git history)

While recording fixtures in Phase 0.5, something more serious than
"a committed secret" turned up: **scripts that can ACTUALLY SEND messages/write production
data if run carelessly**, independent of whatever config they are
fed.

| File | Hazard | Status |
|---|---|---|
| `ScraperNews/threatActorTrendTele.py` | Telegram bot token + Graylog API token **hardcoded in the source** (not from config.yml). If executed, it sends REAL messages to the real Telegram chat/thread and REAL queries to `privy.graylog.cloud`. | **Permanently blocked** in `record_fixtures.py` (`DANGEROUS_LIVE_SIDE_EFFECTS`), which wins even against `--only`. Verified: never executed in any run. |
| `ScraperNews/newCveThreat.py` | Creates a `MongoClient` directly from `config.yml` and calls `bulk_write` — can write to production `news_db.cve_tracker` if given the real config. | Patched at the source: `pymongo.MongoClient` is patched to be inert in the recording harness, whatever config is fed in. |
| `ScraperNews/githubPOCMonitor.py` | Same — `MongoClient` directly from `config.yml`. | Same, patched at the `pymongo.MongoClient` level. |

**Why this nearly happened:** `threatActorTrendTele.py` was never called
in a normal run only because, by coincidence, its file name (`threatActorTrendTele.py`)
differs from the script name in the Rundeck job (`threatactorTrendTelegram.py`) — not
because anything deliberately protected it. If that name mismatch were ever fixed
(it is indeed one of the fix items), or anyone ran
`--only threatActorTrendTele` to test it on its own, that token would really
be used. That is why the defence sits in `SKIP` — which wins against any `--only`
— instead of relying on the name mismatch.

**Lesson for the new framework (Phase 3):** `BaseScraper` must not give
scrapers direct access to `MongoClient`/`telegram.Bot`/raw credentials at
all — only through sinks provided by the framework. This class of bug (a script
bypassing the abstraction and holding credentials directly) must be structurally impossible in the new platform, not just "don't do it".

## Procedure

### 1. Telegram bot token
1. BotFather → `/revoke` for the bot in use
2. Store the new token in the secret store, **not** in a file
3. It will be read through `TELEGRAM__BOT_TOKEN` in the new platform

> This disables alerting until the new token is deployed. Do it in a quiet hour.

### 2. Graylog API token
1. Revoke the old token in Graylog
2. Graylog `graylogLogging.py` is **dropped in the new platform** (2 importers, 1
   already commented out) — so no replacement token is needed unless
   `threatActorTrendGraylog.py` is kept

### 3. Mongo user password
Applies to items 4–8 (the same user appears in several files).

```javascript
// in mongosh, as admin
db.getSiblingDB("admin").changeUserPassword("<user>", passwordPrompt())
```

`passwordPrompt()` keeps the password out of the shell history.

Update every place that is still running **before** the old password is disabled:
`config/config.yml` on prod, the web app `.env`, the systemd unit.

> If the cutover starts from an empty DB, there will eventually be a new Mongo user for
> the new platform. But the old credentials still have to be rotated — the old stack keeps
> running until the cutover, and the old values are in git.

### 4. Email addresses
Move them from `app/config.py:59-60` to `CVE_EMAIL_CC` in env.

---

## Preventing a repeat

Install in the new repo before the first commit:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks: [{id: gitleaks}]
```

Plus a gate in CI:
```bash
gitleaks detect --no-git --redact --exit-code 1
```

`--redact` keeps CI from printing its findings.

---

## Checklist

> The items below were **delegated to the user's ops team, 2026-09-30** -- this checklist records the DELEGATION
> decision, not a verified result that the tokens were actually revoked/replaced. If in doubt
> before go-live, ask the ops team for confirmation before treating these items as technically done.

- [x] Telegram bot token revoked + replaced -- ops team
- [x] Graylog API token revoked -- ops team
- [x] Mongo user password changed (affects 5 locations) -- ops team
- [x] Every consumer still running updated before the old credentials die -- ops team
- [x] Email moved to env -- ops team
- [x] Devo token revoked + replaced (`devo.token` in config.yml) -- ops team. Its value was
      printed into the 2026-09-30 session transcript.
- [x] GitHub token (`github.token` in config.yml, item 13) revoked on GitHub -- ops team. Its value
      was also printed into the 2026-09-30 session transcript.
- [x] Gmail app password (item 14, `emailnewsThreat.py`) revoked -- ops team. Found 2026-09-30 during
      the Phase 10.1c port investigation, delegated later in the same session. Its value was NOT printed.
- [x] Cyborg Security Hunter account password (item 15, `cyborgHuntingIdea.py`) changed -- ops team.
      Found in the same session, delegated later. Its value was NOT printed.
- [x] Rundeck API token revoked + replaced; use `$RD_TOKEN` from env, do not hardcode -- ops team
- [x] `gitleaks` runs on the new repo and is clean -- **technically verified 2026-09-30** (not
      delegated): `gitleaks detect` over the full 61-commit history (6.33 MB) -> 0 findings. `gitleaks
      detect --no-git` over the 1,168 files that will actually be committed (`git ls-files -co
      --exclude-standard`, same as this session's CI simulation) -> 0 findings. A scan of the FULL working tree
      (including gitignored files; `--no-git` ignores `.gitignore`) found 47 -- ALL in 8
      files confirmed by `git check-ignore` + not yet tracked: `.env`, `legacy/config.yml`
      (the 12 old app secrets already listed in items 1-13), `legacy/dump/**/*.bson` (third-party IOC/article data,
      not our secrets), `docs/legacy/rundeck-get-schedule.sh`, `graphify-out/cache/`
      (file hashes, false positives), `__pycache__/*.pyc` (test bytecode). None of them will be committed.
- [x] Pre-commit hook installed -- **technically verified 2026-09-30**: `.pre-commit-config.yaml`
      (gitleaks `v8.30.1`, in sync with the installed CLI version) + `pre-commit install`. Tested FOR REAL: a dummy
      commit containing an AWS access key pattern was rejected (`exit code 1`, `RuleID: aws-access-token`), then a
      normal commit (no secret) went through. The test file was cleaned up, no commit left behind.
- [ ] Only after all of this: import the old repos into the monorepo -- N/A, the old repos stay a separate archive
      (decision from the original plan), not imported into this monorepo
