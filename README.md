# Vareon Intelligence

A Cyber Threat Intelligence platform: it collects news and threat signals from ~90 sources (RSS, websites,
APIs, X/Twitter, GitHub), enriches them with NLP + LLM (classification, threat actors, MITRE ATT&CK TTPs,
countries), and serves them through a web UI and Telegram alerts. It replaces the old `ScraperNews` +
`ScraperNewsWeb` systems.

| Part | Contents |
|---|---|
| `apps/api` | FastAPI (REST, auth, scraper control) |
| `apps/web` | Next.js (UI) |
| `apps/worker` | Celery: `worker` (RSS/API), `worker-browser` (Playwright), `worker-nlp` (spaCy), `beat` (schedule) |
| `packages/*`, `scrapers/` | DB/enrichment core, scraper framework, the scrapers |
| `docker/`, `docker-compose.yml` | images, nginx (TLS), example compose-level env |
| `tools/ops`, `tools/seed` | operations scripts (deploy, backup, rollback) and seeding |
| `docs/` | architecture, runbooks, phase notes, list of broken scrapers |

## Deploy from scratch

For a new host with no existing data. The deploy script is idempotent: it is safe to re-run and **never**
deletes volumes or data.

### Prerequisites

- Linux with **Docker + the `docker compose` plugin**, `python3` (>= 3.9), `curl`, `git`.
- Outbound internet access: image registries (base images, PyPI during seeding), `raw.githubusercontent.com`/
  GitHub (ATT&CK catalog), scraper source sites, the LLM endpoint, `api.telegram.org`.
- Enough disk for the images (~6 GB; the staging build used ~9 GB including cache) and RAM for `worker-nlp`
  (spaCy) + `worker-browser` (Chromium). Drill on 2026-10-02: the whole stack came up healthy in Docker with
  4 GB of RAM at `*_CONCURRENCY=1` (idle). The default concurrency (4/2/2) and real load have not been tested
  on a machine that small.

### Steps

```bash
git clone https://github.com/ikblmhndra/Niskala-Intelligence.git cti-platform && cd cti-platform

cp .env.prod.template .env              # 1. fill in the values (key table below); chmod 600 .env
cp docker/stack.env.example docker/stack.env   # 2. change POSTGRES_PASSWORD, NGINX_TLS_HOSTS, ports

make fresh-deploy                       # 3. build + secret check + migrations + seed + admin + workers + beat + web + nginx
```

Rules for the files:

- `.env` = **application** configuration; `docker/stack.env` = **compose**-level variables (ports, tags,
  Postgres password). Do not mix them: the application rejects unknown keys and fails to start.
- The Postgres password in `docker/stack.env` **must match** the one in `DATABASE__URL` and
  `DATABASE__SYNC_URL`. Replace every `GANTI_INI` in `.env`. The script checks this before building.
- Never paste secret values into chat, tickets or logs; type them directly in an editor on the server.
- `AUTH__JWT_SECRET` and `AUTH__SESSION_SECRET_KEY` may be left empty: the script generates random values.

Options: `make fresh-deploy ARGS='--skip-build'` (images already built), `--skip-secret-check`,
`--skip-nginx` (if you already have your own reverse proxy; template: `docker/ops/nginx-cti.conf.example`).
`make fresh-status` shows the container status.

### Required keys

| Key in `.env` | Status | Notes |
|---|---|---|
| `LLM__API_KEY`, `LLM__URL`, `LLM__MODEL` | **required** | OpenAI-compatible endpoint; tested with `GET /models` (no generation) |
| `TELEGRAM__BOT_TOKEN`, `TELEGRAM__CHAT_ID`, `TELEGRAM__THREAD_IDS` | **required** | tested with `getMe`/`getChat` (no message is sent). `THREAD_IDS` = 22 topics (including `github_poc` and `feed_twitter`, a dedicated thread for general tweets); `thread_id` 0 = the main chat, so fill in each topic's id (Copy Link on the topic in Telegram, the last number) if you want them separate. `check_secrets` prints a NOTE if they are still piled together |
| `NVD__API_KEY` | optional | without a key you hit NVD's much lower public limit |
| `GITHUB__TOKEN` | optional | used by the GitHub scrapers (PoC, TTP) |
| `TWITTER__API_KEY` | optional | twitterapi.io, used by 4 Twitter scrapers that **share one credit balance** (see `docs/CUTOVER_RUNBOOK.md` section 8) |
| `X__BEARER_TOKEN` | optional | official X API, only a fallback for twitterapi.io |
| `OTX__API_KEY` | optional | |
| `GRAPH__*` | optional | email delivery (newsletter, CVE) via Microsoft Graph |
| `OIDC__*` | optional | SSO |

The script runs `tools/ops/check_secrets.py` (a read-only probe against each provider that never prints a
secret) before starting anything. Empty optional keys are reported as `SKIP`, not as failures.

### What the script does

1. Checks prerequisites and the contents of `.env`/`docker/stack.env`. 2. Builds the images. 3. Checks
secrets. 4. Postgres + Redis, schema migration, API. 5. Seeds the default reference data
(`tools/seed/reference/`: ~4000 threat actor names, APAC demonyms, IOC allowlist). 6. Creates the first admin
through `POST /api/auth/init`; the random password is written to `secrets/admin_password` (mode 600, never
printed). 7. Syncs the MITRE ATT&CK catalog. 8. Workers, then **beat last** (beat is what fires the schedule).
9. Web + nginx (self-signed certificate generated automatically).

### After it is up

1. Open `https://<first host in NGINX_TLS_HOSTS>`, log in as `admin` with the password from
   `secrets/admin_password`, **change the password in the UI, then delete that file**. The `auth/init`
   endpoint only works while there are no users; run the script before the host is exposed to the network.
2. Enter data through the UI. Without it some scrapers are idle by design:
   - **Admin**: clients + countries, other users;
   - **CVE → Techstack**: without a techstack, `new_cve` produces nothing;
   - **X Intel → Monitored Accounts**: without accounts, `monitor_x` skips its runs. This list feeds only
     the X Intel tab; the Telegram tweet alerts (`tweet_alerts_*`) use their own account lists (see
     `docs/ARCHITECTURE.md`, "X Intel vs tweet alerts").
3. The first time a scraper runs it uses *cold start* mode (at most 5 items per scraper). The Scrapers tab
   shows each scraper's status; scrapers missing their required data (point 2) show as `empty`/idle, which is
   expected.
4. Install the Postgres backup timer (`docs/PROD_PREP.md`, `docker/ops/cti-pg-backup.*`) and run `verify`
   once. There is no scheduled backup by default.
5. Monitor: `docs/CUTOVER_RUNBOOK.md` sections 4 (first hour), 5 (first week), 9 (troubleshooting).

### Deploy with a database from a backup (e.g. moving from staging)

For a new host whose database should be filled from a `tools/ops/pg_backup.py` backup instead of starting
empty:

```bash
# on the old host: create a backup (dump + .sha256, mode 600) and verify it
PG="docker compose --env-file docker/stack.env --profile app exec -T postgres"
python3 tools/ops/pg_backup.py --pg-exec "$PG" backup --dir ~/backups
python3 tools/ops/pg_backup.py --pg-exec "$PG" verify --file ~/backups/cti-<UTC>.dump

# copy the dump AND its .sha256 to the new host (the dump contains password hashes: never over an open channel)
scp ~/backups/cti-<UTC>.dump* user@new-host:/secure/path/

# on the new host, after .env and docker/stack.env are filled in:
make fresh-deploy ARGS='--restore-from /secure/path/cti-<UTC>.dump'
```

- The restore runs at step 3, after Postgres is up and **before** the API. A dump from an older migration
  revision is upgraded to the latest automatically when the API starts. A dump from a revision NEWER than the
  code is rejected by the migrations (run the same or newer code than the one that created the dump).
- It only runs against an **empty** database. If the database already has data, the script stops without
  changing anything. To overwrite an existing database add `--replace-db` (deletes all data; when run
  interactively it asks you to type `timpa`).
- No new admin is created: log in with a user from the backup. The script prints the list of usernames.
- Carried over as-is: old passwords, test data, and scraper overrides (`scraper_config`: schedule,
  `max_items`). Change passwords and clean up test data before production use.
- Scraper dedup (`scraper_seen`) lives in Postgres and is carried over, so there is no flood of "cold start"
  items. Redis is not part of the backup (its contents are transient).
- The Postgres password on the new host may differ from the old one: the backup does not carry database
  roles or passwords.

### Full reset (deletes ALL data)

There is deliberately no `make` target for this. If you really need to start over on a practice host:

```bash
docker compose --env-file docker/stack.env --profile app down -v   # -v = delete the Postgres/Redis volumes
rm -rf secrets                                                     # old admin password
```

## Migrating from the old system (not a fresh deploy)

Requires the Mongo dump + dedup offset files from the old server, a warm start, and a staged cutover:
`docs/CUTOVER_RUNBOOK.md` section 3. To compare with the old system while both run in parallel:
`docs/PARALLEL_RUN_COMPARISON.md`.

## Documentation

| File | What it is for |
|---|---|
| `docs/ARCHITECTURE.md` | runtime topology, data flows, access patterns, code paths, design decisions and known risks |
| `docs/CUTOVER_RUNBOOK.md` | cutover, monitoring, backup/restore, rollback, troubleshooting, **what is not yet proven** (section 10) |
| `docs/PROD_PREP.md` | old Mongo backup, Postgres backup timer, rollback drill |
| `docs/CI_CD.md` | CI and **automatic CD to production** (self-hosted runner, `make deploy`, automatic rollback) |
| `docs/SECRETS_ROTATION.md` | list of secrets and their rotation status |
| `docs/ADDING_A_SCRAPER.md` | adding a new scraper |
| `docs/KNOWN_BROKEN.md` | broken/waived scrapers and their root causes |
| `docs/CVE_TECH_MATCHING.md` | the Tech column in the CVE Tracker: problem, root cause, solution, limits, techstack standardisation plan |
| `docs/PROGRESS.md` | work log per phase (Indonesian) |

## Local development

```bash
uv sync --extra dev --locked
uv run pytest tests/unit tests/contract packages      # fast
uv run pytest tests/integration                       # needs Docker (testcontainers: throwaway Postgres/Redis), ~7 minutes
uv run ruff check . && uv run ruff format --check .
uv run mypy packages/cti-core/src packages/cti-scraper/src   # --strict only for these two packages (same as CI)
```

Pre-commit installs `gitleaks` (`.pre-commit-config.yaml`): commits containing secret patterns are rejected.
