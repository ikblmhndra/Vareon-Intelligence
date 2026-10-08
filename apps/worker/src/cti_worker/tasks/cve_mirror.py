"""Task mirror CVE (ROADMAP #19, irisan 3): `cve.mirror_sync` (tiap 5 menit) dan
`cve.mirror_purge` (harian), keduanya queue `maintenance`. Logikanya di
`cti_core.cve_mirror_sync` (murni terhadap fetcher yang disuntik); di sini hanya HTTP (httpx) dan
penyalaan lewat `Settings.cve_mirror.enabled`.

Native sync (seperti `scraper.purge_*`), bukan `_run_async()`: repositori yang dipanggil sync.
Tidak ada retry otomatis: tick berikutnya mengulang sendiri dan state di DB menjaga kursor dan
antrean percobaan ulang. Mati (default) = kembali segera, supaya deploy skema ini tidak mengubah
perilaku apa pun."""

from __future__ import annotations

import datetime
from typing import Any

import httpx
import structlog
from cti_core.config import get_settings
from cti_core.cve_mirror_sync import DELTA_LOG_URL, Fetcher, FetchError

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE

log = structlog.get_logger()

_USER_AGENT = "VareonIntelligence-cve-mirror/1.0 (+https://github.com/CVEProject/cvelistV5)"
_LOG_TIMEOUT_FACTOR = 3  # deltaLog.json ~24 MB


def make_fetcher(client: httpx.Client, timeout_s: float) -> Fetcher:
    def fetch(url: str) -> bytes:
        timeout = timeout_s * (_LOG_TIMEOUT_FACTOR if url == DELTA_LOG_URL else 1)
        try:
            resp = client.get(url, timeout=timeout)
        except httpx.HTTPError as e:
            raise FetchError(f"{type(e).__name__}: {url}") from e
        if resp.status_code != 200:
            raise FetchError(f"HTTP {resp.status_code}: {url}")
        return resp.content

    return fetch


@app.task(bind=True, name="cve.mirror_sync", queue=QUEUE_MAINTENANCE)
def cve_mirror_sync(self: Any) -> dict[str, object]:
    from cti_core.cve_mirror_sync import sync_once
    from cti_core.db.engine import sync_session
    from cti_scraper.sinks import finish_run

    cfg = get_settings().cve_mirror
    if not cfg.enabled:
        return {"status": "disabled"}
    with (
        httpx.Client(
            headers={"User-Agent": _USER_AGENT}, follow_redirects=False, trust_env=True
        ) as client,
        sync_session() as session,
    ):
        report = sync_once(
            session,
            make_fetcher(client, cfg.request_timeout_s),
            datetime.datetime.now(datetime.UTC),
            max_files=cfg.max_files_per_run,
            promote=cfg.promote,
        )
        # Sama dengan `Runner`: ringkasan Telegram CVE baru dikirim SETELAH commit (ia membaca ulang
        # baris dari DB). Tanpa baris baru (mode off/shadow) ini tidak melakukan apa pun.
        session.commit()
        finish_run(session)
    return report.as_dict()


@app.task(bind=True, name="cve.mirror_purge", queue=QUEUE_MAINTENANCE)
def cve_mirror_purge(self: Any) -> dict[str, object]:
    from cti_core.cve_mirror_sync import purge_expired
    from cti_core.db.engine import sync_session

    if not get_settings().cve_mirror.enabled:
        return {"status": "disabled"}
    today = datetime.datetime.now(datetime.UTC).date()
    with sync_session() as session:
        deleted = purge_expired(session, today)
    return {"status": "ok", "deleted": deleted}


@app.task(bind=True, name="cve.promote_entry", queue=QUEUE_MAINTENANCE, max_retries=5)
def cve_promote_entry(self: Any, entry_id: int) -> dict[str, object]:
    """Satu entri baru di-Monitor / diaktifkan / dapat target: isi riwayatnya dari mirror
    (`cti_core.cve_promotion.promote_entry`), dipicu API setelah commit. Tanpa notifikasi
    Telegram (riwayat bukan "CVE baru"). Menunggu kunci ingest (`acquire_lock`): bila ingest
    sedang jalan, coba lagi 1 menit kemudian."""
    from cti_core.cve_mirror_sync import acquire_lock, release_lock
    from cti_core.cve_promotion import promote_entry
    from cti_core.db.engine import sync_session

    cfg = get_settings().cve_mirror
    if not cfg.enabled or cfg.promote == "off":
        return {"status": "disabled"}
    with sync_session() as session:
        if not acquire_lock(session):
            raise self.retry(countdown=60)
        try:
            summary = promote_entry(session, entry_id, cfg.promote)
        finally:
            release_lock(session)
    log.info(
        "cve_promote_entry",
        entry_id=entry_id,
        mode=cfg.promote,
        scanned=summary.scanned,
        matched=summary.matched,
        created=summary.created,
        shadow=summary.shadow,
    )
    return {
        "status": "ok",
        "mode": cfg.promote,
        "scanned": summary.scanned,
        "matched": summary.matched,
        "created": summary.created,
        "updated": summary.updated,
        "shadow": summary.shadow,
    }
