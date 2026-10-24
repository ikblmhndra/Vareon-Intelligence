"""Entrypoint FastAPI -- port dari `ScraperNewsWeb/app/main.py`, TANPA
lima background loop (`_pir_alert_loop`, `_cve_enrichment_loop`, dst) dan
TANPA Jinja2/StaticFiles (frontend server-rendered lama diganti Next.js
terpisah, Fase 8 -- `apps/api` murni JSON API).

Lima loop itu bukan "belum sempat", tapi sengaja dipindah jadi item **7.8**
(lihat `docs/PROGRESS.md` Fase 6/7) -- ranahnya emang Celery beat
(`apps/worker`, Fase 6 udah nyediain infra-nya), bukan `asyncio.create_task`
di dalam proses uvicorn kayak dulu (itu masalahnya: >1 worker uvicorn
gandain semua loop N kali, salah satu alasan revamp)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from cti_core.config import get_settings
from cti_core.db.engine import async_session
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.logging import configure_logging, get_logger
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api import __version__
from cti_api.routers import articles as articles_router
from cti_api.routers import attack as attack_router
from cti_api.routers import auth as auth_router
from cti_api.routers import catalog as catalog_router
from cti_api.routers import changelog as changelog_router
from cti_api.routers import clients as clients_router
from cti_api.routers import crossref as crossref_router
from cti_api.routers import cve as cve_router
from cti_api.routers import cve_db as cve_db_router
from cti_api.routers import data_health as data_health_router
from cti_api.routers import exec_dashboard as exec_dashboard_router
from cti_api.routers import filtered_articles as filtered_articles_router
from cti_api.routers import health as health_router
from cti_api.routers import intelligence as intelligence_router
from cti_api.routers import iocs as iocs_router
from cti_api.routers import mindmap as mindmap_router
from cti_api.routers import mitre as mitre_router
from cti_api.routers import monitored_accounts as monitored_accounts_router
from cti_api.routers import newsletter as newsletter_router
from cti_api.routers import newsroom as newsroom_router
from cti_api.routers import pir as pir_router
from cti_api.routers import pkg_vuln as pkg_vuln_router
from cti_api.routers import ransomware as ransomware_router
from cti_api.routers import recap as recap_router
from cti_api.routers import rfi as rfi_router
from cti_api.routers import roles as roles_router
from cti_api.routers import scraper as scraper_router
from cti_api.routers import secrets as secrets_router
from cti_api.routers import source_reliability as source_reliability_router
from cti_api.routers import stix as stix_router
from cti_api.routers import ta_groups as ta_groups_router
from cti_api.routers import techstack as techstack_router
from cti_api.routers import tweets as tweets_router
from cti_api.services.roles import ensure_system_roles

log = get_logger()


_BOOTSTRAP_LOCK_KEY = 7_231_001
"""Kunci `pg_advisory_xact_lock` buat `bootstrap_reference_rows()`. Angka
bebas, yang penting konstan dan gak dipakai lock lain di codebase ini."""


async def bootstrap_reference_rows(session: AsyncSession) -> None:
    """Baris referensi yang API butuh ada (client `default`, role sistem).

    Dijalanin TIAP proses uvicorn pas start -- dan `WEB_CONCURRENCY` > 1
    (default image: 2) artinya BEBERAPA proses start bersamaan. Kedua langkah
    di bawah pola "cek dulu, baru insert", jadi di DB KOSONG dua proses
    sama-sama lolos cek lalu tabrakan di `pk_clients` -- proses yang kalah
    crash di lifespan dan `uvicorn` matiin seluruh container ("Child process
    failed to start"); ketauan pas smoke test staging Fase 10.B (self-heal
    lewat restart policy, tapi start pertama selalu flap).

    Fix: advisory lock tingkat-transaksi. Proses kedua NUNGGU di sini sampai
    yang pertama commit (lock lepas otomatis), lalu cek-nya sudah lihat
    barisnya -- semua bootstrap terserialkan, tanpa ubah logika repo.
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY})
    await AsyncClientRepo(session).ensure_default()
    await ensure_system_roles(session)  # commit di akhir -> lock dilepas


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level, json=settings.environment != "dev")
    async with async_session() as session:
        await bootstrap_reference_rows(session)
    log.info("api_startup_done", version=__version__)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=f"{settings.platform_name} API", version=__version__, lifespan=lifespan)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Client-ID"],
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        # Respons 422 bawaan FastAPI memantulkan `input` (SELURUH body) di tiap galat. Untuk
        # halaman Third-party Keys itu mengembalikan key yang baru diketik dan password konfirmasi
        # ke browser dan ke apa pun yang merekam respons. Di sana cukup `type`, `loc`, dan `msg`.
        if request.url.path.startswith("/api/secrets"):
            errors = [
                {k: v for k, v in e.items() if k not in ("input", "ctx", "url")}
                for e in exc.errors()
            ]
            return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})
        return await request_validation_exception_handler(request, exc)

    app.include_router(health_router.router)
    app.include_router(auth_router.router)
    app.include_router(clients_router.router)
    app.include_router(roles_router.router)
    app.include_router(secrets_router.router)
    app.include_router(articles_router.router)
    app.include_router(newsroom_router.router)
    app.include_router(iocs_router.router)
    app.include_router(techstack_router.router)
    app.include_router(cve_router.router)
    app.include_router(cve_db_router.router)
    app.include_router(catalog_router.router)
    app.include_router(tweets_router.router)
    app.include_router(monitored_accounts_router.router)
    app.include_router(ransomware_router.router)
    app.include_router(changelog_router.router)
    app.include_router(filtered_articles_router.router)
    app.include_router(rfi_router.router)
    app.include_router(pir_router.router)
    app.include_router(pkg_vuln_router.router)
    app.include_router(source_reliability_router.router)
    app.include_router(attack_router.router)
    app.include_router(ta_groups_router.router)
    app.include_router(mitre_router.router)
    app.include_router(crossref_router.router)
    app.include_router(newsletter_router.router)
    app.include_router(mindmap_router.router)
    app.include_router(stix_router.router)
    app.include_router(intelligence_router.router)
    app.include_router(recap_router.router)
    app.include_router(exec_dashboard_router.router)
    app.include_router(scraper_router.router)
    app.include_router(data_health_router.router)
    return app


app = create_app()
