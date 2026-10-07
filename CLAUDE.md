# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Vareon Intelligence: a cyber threat intelligence platform. ~95 scrapers (RSS, HTML, APIs, X/Twitter, GitHub) feed an NLP + LLM enrichment pipeline; results are served by a FastAPI API and a Next.js UI, and pushed to Telegram. It replaces the older `ScraperNews` + `ScraperNewsWeb` systems, and many modules are ports of that code (docstrings say so). The product was renamed, but the Python packages are still `cti_*` (`cti_core`, `cti_api`, ...).

Code identifiers are English, but **comments, docstrings, docs and commit messages are mostly Indonesian**. Match the surrounding language when editing. Docstrings are often long and explain *why* (past incidents, phase numbers like "Fase 10.B"); keep that habit.

## Commands

Python 3.12 + [uv](https://docs.astral.sh/uv/) workspace; the web app uses pnpm (Node 22).

```bash
uv sync --extra dev --locked                          # install everything

uv run pytest tests/unit tests/contract packages      # fast suite, no Docker
uv run pytest tests/unit/test_config.py::test_valid_config_loads -q   # single test
uv run pytest tests/contract -k <scraper_id> -q       # contract tests for one scraper
uv run pytest tests/integration                       # needs Docker (testcontainers Postgres/Redis), ~7 min
uv run pytest tests/integration/test_cve_router_snapshot.py --snapshot-update   # syrupy snapshots

uv run ruff check . && uv run ruff format --check .
uv run mypy packages/cti-core/src packages/cti-scraper/src   # strict, ONLY these two packages (same as CI)
```

API contract (CI fails if the committed files drift): after changing any endpoint or response schema,

```bash
uv run python tools/export_openapi.py                 # rewrites docs/openapi.json
cd apps/web && pnpm run gen:api                       # rewrites src/lib/api/schema.d.ts
```

Web (`apps/web`; no test runner, CI = lint + typecheck + build):

```bash
pnpm install --frozen-lockfile
pnpm dev                                              # needs cti-api on API_BASE_URL (default http://localhost:8000)
pnpm lint
pnpm exec next typegen && pnpm exec tsc --noEmit      # typegen first, or tsc gives false errors
pnpm build
```

Scraper CLI (`cti-scraper`, typer): `list`, `dry-run <id>`, `verify <id> [--record]`, `run <id> [--prime]`, `enable|disable <id>`. `dry-run` hits the real source but writes nothing. Full workflow: `docs/ADDING_A_SCRAPER.md`.

Local services: `docker compose up -d` starts only Postgres + Redis (app runs on the host via uv/pnpm). `docker compose --profile app up -d --build` is the full stack. Run the API with `uvicorn cti_api.main:app`; migrations with `alembic upgrade head`. Ops: `make fresh-deploy`, `make deploy` (see Deployment).

## Architecture

### Workspace layout (uv workspace: `packages/*`, `scrapers`, `apps/worker`, `apps/api`)

- `cti-core`: settings, SQLAlchemy models + repositories, LLM client, IOC extractor. Everyone depends on it.
- `cti-scraper`: the scraper framework (`BaseScraper`, `ScraperMeta`, registry, `Runner`, dedup, sinks, CLI).
- `cti-scrapers` (`scrapers/`): the plugins themselves, `feeds/` (one file per source) and `collectors/` (bespoke).
- `cti-enrich`: the enrichment pipeline (classify, fetch text, summarize, IOCs, TTPs, score, persist, alert). The `nlp` extra (spaCy/sumy) is installed only in the `worker-nlp` image.
- `cti-alerts`: Telegram and Microsoft Graph mail.
- `cti-api`: FastAPI. `cti-worker`: Celery. **`cti-worker` depends on `cti-api`**: periodic tasks call the async `cti_api.services.*` functions via `asyncio.run` so business logic has one implementation.

### Data flow

`beat` (cron) → Celery `scrape.run` → `Runner.execute()` → scraper `fetch()` yields typed items → dedup (`scraper_seen`) → **sink chosen by item type** (`cti_scraper/sinks.py`, `@sink_for(ItemType)`) → `ArticleItem`s enqueue `enrich.article` on the `enrich` queue → `cti_enrich.pipeline` → `articles` table + Telegram alert.

Backpressure: scraping is much faster than enrichment (~10-13 s + LLM per article), so the article sink refuses new items (run status `backpressure`) once the `enrich` queue depth reaches `scraper.enrich_queue_max_depth`.

Pipeline short-circuits: `related_cyber == False` returns early (only a light row in `rejected_articles`); `security_tech_best_practice` skips TTP extraction and scoring.

Celery queues: `scrape.rss`, `scrape.api` (scrapers with a `credential`), `scrape.browser` (`runtime="browser"`, Playwright), `enrich`, `notify`, `maintenance`. Compose runs `worker` (rss/api/notify/maintenance), `worker-browser`, `worker-nlp` (enrich) and a singleton `beat` (`beat_main` takes a Redis lock). One Celery app (`cti_worker.celery_app`) serves all of them; `-Q` picks the role. Tasks use `acks_late`.

### Scraper framework rules that span files

- **Auto-discovery**: a scraper is one file under `scrapers/src/cti_scrapers/`; `registry.discover()` imports the package. No registry or `pyproject` edits. `meta.id` is permanent (it namespaces dedup); `meta.source` must be unique, enforced by `tests/contract/test_scraper_labels.py`.
- `fetch()` may only use `ctx.http`, `ctx.page()`, `ctx.now`, `ctx.options`, `ctx.reference`. No DB, Telegram, raw tokens or `datetime.now()`. Credentials are declared in `meta.credential` and injected by `Runner`.
- **Beat schedule is built once at import** (`cti_worker.beat.build_beat_schedule`) from the registry plus `ScraperConfig` rows. New scrapers and schedule/`enabled` overrides take effect only after `beat` (and `api`, for the `/scrapers` page) restarts. `Runner` re-checks `enabled` at run time.
- **Cold start cap**: a scraper with no `scraper_seen` rows processes only its newest `scraper.cold_start_max_items` (5) items. Use `run --prime` to mark everything seen instead.
- Fixtures in `tests/fixtures/<legacy_script>/` are recorded HTTP bytes + `expected_items.json`; `tests/contract/test_golden.py` replays them. Commit them with the scraper.

### Config

One `cti_core.config.Settings` (pydantic-settings, `extra="forbid"` at every nested level; nested keys use `__`, e.g. `DATABASE__URL`). A typo or unknown key makes the process **fail to start**, by design. Consequences:
- `.env` (app config) and `docker/stack.env` (compose-level: ports, tags, `POSTGRES_PASSWORD`) must never be mixed.
- Adding a `Settings` field means updating `.env.example` (and `.env.prod.template`) in the same commit; `tests/unit/test_config.py` and `test_env_prod_template.py` check them.

### Database

Same Postgres, two drivers: async (`asyncpg`, FastAPI) and sync (`psycopg`, Celery/CLI). Only the compose `migrate` service runs `alembic upgrade head`; API and workers never migrate. Migrations are often hand-written, and `tests/integration/test_migrations_match_models.py` fails on any drift between migrations and models, so new columns need both.

### CVE Tracker

Alur lengkap yang sekarang (ingest `new_cve`, upsert, enrichment, scope tab CVEs, ticket, notifikasi, tujuh
pencocok nama tech, dan checklist invarian saat mengubah desain) ada di `docs/CVE_TRACKER_FLOW.md`; baca itu
sebelum menyentuh `cve_tracker`, `techstack_entries`, atau `new_cve`. Rencana katalog tech + mirror CVE:
`docs/ROADMAP.md` #19.

### API (`apps/api/src/cti_api`)

`routers/` (thin) → `services/` (logic, "session-first" async functions) → `cti_core` repositories. Auth: JWT bearer with Redis-backed revocation (Redis must be up for any authenticated request); multi-tenant via the `X-Client-ID` header (`deps.effective_client_id` / `ensure_client_access`). `lifespan` bootstraps reference rows under a Postgres advisory lock because uvicorn runs several processes.

### Web (`apps/web`, Next.js 16 App Router)

The browser never calls `cti-api` directly. Client components call `/api/proxy/[...path]` (Route Handler), which reads the httpOnly session cookie and forwards with `Authorization: Bearer` + `X-Client-ID`; `src/proxy.ts` is the (optimistic) route guard. API types come from `docs/openapi.json` → `src/lib/api/schema.d.ts`.
- This Next.js has breaking changes versus common knowledge. `apps/web/AGENTS.md` says to read `node_modules/next/dist/docs/` before writing code (note `proxy.ts` replaces `middleware.ts`).
- shadcn/ui here is built on **Base UI, not Radix** (`render={<X/>}` not `asChild`; `SelectItem` children must be a single string; etc.). See `apps/web/CLAUDE.md` before touching `components/ui` or dialogs/selects.

### Deployment

CI (`.github/workflows/ci.yml`): ruff, mypy, full pytest, web build, API-contract drift check, compose syntax, Docker image build + in-image smoke import, gitleaks. CD (`deploy.yml`) runs on a self-hosted runner on the prod host after CI is green on `main` and calls `tools/ops/deploy.sh`: Postgres backup, tag running images `:prev`, build, `up -d` (migrate first), wait healthy, auto-rollback on failure (never auto-downgrades the DB). There is no staging. New required `.env` keys must be set on the prod host **before** merging, or the app refuses to start and the deploy rolls back. If you change the runner label in `deploy.yml`, update `tests/unit/test_deploy_pipeline.py`. Details: `docs/CI_CD.md`, `docs/CUTOVER_RUNBOOK.md`.

## Conventions and gotchas

- Ruff: line length 100, rules `E,F,I,UP,B,SIM,RUF`. `E501` is deliberately off for verbatim-copied LLM prompts and generated scraper files (see `[tool.ruff.lint.per-file-ignores]`); `B008` is off for FastAPI `Depends` and typer defaults.
- pytest runs with a single session-scoped event loop (cached async engine; per-function loops break teardown). `filterwarnings` turns `DeprecationWarning` from `cti_*` into errors. `tests/edge` needs Docker; `playwright`-marked tests need Chromium.
- Releases bump the version in the root and every package `pyproject.toml`, each `__version__`, `apps/web/package.json`, `uv.lock`, `docs/openapi.json` and the health snapshot, plus a `CHANGELOG.md` entry. `routers/changelog.py` parses the header format `## [x.y.z] - YYYY-MM-DD` exactly.
- Commit style: conventional (`feat(scrapers): ...`, `fix(cd): ...`, `chore(release): ...`).
- `pre-commit` runs gitleaks; never paste secret values into files, logs or chat.
