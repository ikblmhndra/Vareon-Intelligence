# syntax=docker/dockerfile:1.7
#
# Image Celery worker -- SATU Dockerfile, DUA target (plan §10):
#   --target worker      scrape.* + notify + maintenance (+ beat)   -> tanpa spaCy/sumy
#   --target worker-nlp  queue `enrich`                             -> + cti-enrich[nlp]
#
#   docker build -f docker/worker.Dockerfile --target worker     -t cti-worker .
#   docker build -f docker/worker.Dockerfile --target worker-nlp -t cti-worker-nlp .
#
# BuildKit cuma build stage yang dibutuhin target-nya, jadi image `worker`
# gak pernah narik spaCy. (Dulu extra `nlp` juga narik torch ~2-3GB; dibuang
# di Fase 10.A -- nol importer.)
#
# Kenapa worker bawa `cti-api` (fastapi/sklearn/playwright): 5 task periodik
# (Fase 7.8) reuse fungsi async `cti_api.services.*` langsung lewat
# asyncio.run() -- lihat komentar di apps/worker/pyproject.toml.
#
# Chromium ADA di kedua target: scraper `runtime="browser"` (24 scraper,
# queue scrape.browser) DAN `cti_enrich.stages.fetch_text` (fallback render
# JS pas ekstraksi teks artikel) sama-sama pakai Playwright.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_VERSION=0.12.6

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ------------------------------------------------------------ builder-base --
FROM ${PYTHON_IMAGE} AS builder-base
COPY --from=uv /uv /bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY packages/cti-core/pyproject.toml packages/cti-core/pyproject.toml
COPY packages/cti-scraper/pyproject.toml packages/cti-scraper/pyproject.toml
COPY packages/cti-enrich/pyproject.toml packages/cti-enrich/pyproject.toml
COPY packages/cti-alerts/pyproject.toml packages/cti-alerts/pyproject.toml
COPY scrapers/pyproject.toml scrapers/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml

# ----------------------------------------------------------------- builder --
FROM builder-base AS builder
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package cti-worker
COPY packages packages
COPY scrapers scrapers
COPY apps/api apps/api
COPY apps/worker apps/worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package cti-worker

# ------------------------------------------------------------- builder-nlp --
# `--extra nlp` di cti-worker -> cti-enrich[nlp] (spaCy, sumy, nltk,
# en_core_web_sm dari wheel di GitHub releases -- build butuh akses github.com).
FROM builder-base AS builder-nlp
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package cti-worker --extra nlp
COPY packages packages
COPY scrapers scrapers
COPY apps/api apps/api
COPY apps/worker apps/worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package cti-worker --extra nlp

# ------------------------------------------------------------ browser-base --
# Python slim + Chromium + library sistemnya (~600MB, ~2 menit) -- stage
# TERPISAH dari venv, jadi layer-nya GAK ke-invalidate tiap source berubah.
# `playwright==` di-pin lewat ARG dan HARUS sama dengan yang di uv.lock --
# dijaga dua lapis: build GAGAL kalau launch Chromium di stage runtime gagal
# (versi beda = revisi browser beda), dan
# `tests/unit/test_dockerfile_playwright_pin.py` nangkep drift di PR.
# Stage ini sengaja IDENTIK di api.Dockerfile dan worker.Dockerfile, jadi
# layer-nya dishare lewat cache antar-image.
FROM ${PYTHON_IMAGE} AS browser-base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ARG PLAYWRIGHT_VERSION=1.63.0
COPY --from=uv /uv /bin/uv
RUN UV_PYTHON_DOWNLOADS=never uv tool run --from "playwright==${PLAYWRIGHT_VERSION}" \
        playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache

# ------------------------------------------------------------ runtime-base --
FROM browser-base AS runtime-base
RUN useradd --system --uid 10001 --home-dir /home/cti --create-home cti \
    # Working dir beat (`beat_main` nulis celerybeat-schedule di CWD).
    && mkdir -p /var/lib/cti && chown cti:cti /var/lib/cti
WORKDIR /app
# CHANGELOG.md: `cti_api.routers.changelog` (dipakai balik lewat import
# `cti_api` di worker) nyari file ini dengan naik dari lokasi modul.
COPY CHANGELOG.md ./

# ------------------------------------------------------------------ worker --
FROM runtime-base AS worker
COPY --from=builder /app/.venv /app/.venv
# Bukti Chromium bener-bener bisa jalan dgn venv INI (versi + library sistem).
RUN python -c "from playwright.sync_api import sync_playwright as sp; p = sp().start(); p.chromium.launch().close(); p.stop()"
# Registry harus penuh -- `discover()` balik kosong DIAM-DIAM kalau paket
# `cti-scrapers` gak ter-install, jadi kita paksa gagal di build.
RUN python -c "from cti_scraper.registry import discover; n = len(discover()); assert n > 50, f'registry cuma {n} scraper'"
USER cti
# Default = worker "ringan"; compose override `command` per service (lihat
# docker-compose.yml: worker / worker-browser / beat).
CMD ["celery", "-A", "cti_worker.celery_app", "worker", "-Q", "scrape.rss,scrape.api,notify,maintenance", "--loglevel", "INFO"]

# -------------------------------------------------------------- worker-nlp --
FROM runtime-base AS worker-nlp
# NLTK `punkt_tab` (tokenizer sumy) DI-BAKE di sini, bukan didownload
# `summarize._ensure_nltk_data()` pas runtime -- container yang di-recreate
# gak boleh butuh internet buat ngerangkum artikel, dan user `cti` gak punya
# cache yang persisten.
ENV NLTK_DATA=/usr/local/share/nltk_data
COPY --from=builder-nlp /app/.venv /app/.venv
# Bukti Chromium bener-bener bisa jalan dgn venv INI (versi + library sistem).
RUN python -c "from playwright.sync_api import sync_playwright as sp; p = sp().start(); p.chromium.launch().close(); p.stop()"
# Registry harus penuh -- `discover()` balik kosong DIAM-DIAM kalau paket
# `cti-scrapers` gak ter-install, jadi kita paksa gagal di build.
RUN python -c "from cti_scraper.registry import discover; n = len(discover()); assert n > 50, f'registry cuma {n} scraper'"
RUN python -m nltk.downloader -d "${NLTK_DATA}" punkt_tab
# spaCy + model beneran ke-load, dan data NLTK ketemu (OFFLINE) -- gagal di
# sini = build gagal, bukan worker crash-loop di produksi.
RUN python -c "import spacy, nltk; spacy.load('en_core_web_sm'); nltk.data.find('tokenizers/punkt_tab')"
# Model embedding MiniLM (ONNX, ~90MB, model relevansi P5 + story resolver) DI-BAKE
# di sini, di-pin ke revisi tertentu -- sama seperti punkt_tab: container yang
# di-recreate gak boleh butuh internet (egress produksi cuma :443) dan runtime
# gak pernah download (`local_files_only=True`, HF_HUB_OFFLINE=1). Layout cache
# HF standar (`models--Qdrant--all-MiniLM-L6-v2-onnx/snapshots/<rev>`) yang dicari
# fastembed. Build butuh akses huggingface.co. Naikkan revisi = ganti ARG ini.
ARG MINILM_REVISION=d13954661f83248295ba75c1ed411eef3b7b936e
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
# `refs/main` ditulis manual: download dgn revisi SHA tidak membuatnya, padahal
# fastembed (local_files_only) me-resolve snapshot lewat `refs/main`.
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('Qdrant/all-MiniLM-L6-v2-onnx', revision='${MINILM_REVISION}', cache_dir='/opt/fastembed')" \
    && mkdir -p /opt/fastembed/models--Qdrant--all-MiniLM-L6-v2-onnx/refs \
    && printf '%s' "${MINILM_REVISION}" > /opt/fastembed/models--Qdrant--all-MiniLM-L6-v2-onnx/refs/main \
    && chmod -R a+rX /opt/fastembed
ENV HF_HUB_OFFLINE=1
# Model beneran ke-load dari disk (OFFLINE) dan dimensinya 384 -- gagal = build gagal.
RUN python -c "from cti_enrich.relevance.embedder import get_embedder; assert get_embedder().embed(['x']).shape == (1, 384)"
USER cti
CMD ["celery", "-A", "cti_worker.celery_app", "worker", "-Q", "enrich", "--loglevel", "INFO"]
