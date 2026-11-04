"""Task `sigma.sync`: cek rilis terbaru SigmaHQ seminggu sekali; bila tag berbeda dari yang
tersimpan, unduh `sigma_all_rules.zip` dan ganti seluruh `sigma_rules` (P7e spec 4.2 butir 3).

Zip yang ditolak guard `load_sigma_zip` (terlalu kecil, menyusut >20 %) atau gagal diunduh tidak
mengubah baris lama; galatnya dicatat di snapshot `sigma` (`last_error`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import structlog
from cti_core.config import get_settings
from cti_core.db.models.entity import ReferenceSnapshot
from cti_core.hunt.sigma import SIGMA_SNAPSHOT, load_sigma_zip, record_sigma_error
from sqlalchemy.orm import Session

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE

log = structlog.get_logger()

RELEASES_URL = "https://api.github.com/repos/SigmaHQ/sigma/releases/latest"
ASSET_NAME = "sigma_all_rules.zip"
MAX_BYTES = 20 * 1024 * 1024
HTTP_TIMEOUT_S = 60.0
_HEADERS = {"User-Agent": "vareon-intelligence"}


def http_get_json(url: str) -> dict[str, Any]:
    resp = httpx.get(url, timeout=HTTP_TIMEOUT_S, follow_redirects=True, headers=_HEADERS)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("isi bukan objek JSON")
    return data


def http_get_bytes(url: str) -> bytes:
    """Unduh streaming; berhenti dengan galat begitu melewati `MAX_BYTES`."""
    buf = bytearray()
    with httpx.stream(
        "GET", url, timeout=HTTP_TIMEOUT_S, follow_redirects=True, headers=_HEADERS
    ) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ValueError(f"zip melebihi {MAX_BYTES} byte")
    return bytes(buf)


def sync_sigma(
    session: Session,
    get_json: Callable[[str], dict[str, Any]],
    get_bytes: Callable[[str], bytes],
) -> dict[str, Any]:
    """Tidak commit; pemanggil yang commit. Galat apa pun menjadi `failed` + `last_error`."""
    snap = session.get(ReferenceSnapshot, SIGMA_SNAPSHOT)
    stored = snap.content.get("release") if snap is not None else None
    release: str | None = None
    try:
        rel = get_json(RELEASES_URL)
        release = str(rel["tag_name"])
        if release == stored:
            return {"status": "unchanged", "release": release}
        url = next(a["browser_download_url"] for a in rel["assets"] if a["name"] == ASSET_NAME)
        data = get_bytes(url)
        # savepoint: load yang ditolak di tengah jalan tidak boleh meninggalkan baris separuh
        with session.begin_nested():
            res = load_sigma_zip(session, data, release=release, source_url=url)
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        record_sigma_error(session, msg)
        return {"status": "failed", "release": release, "error": msg}
    return {"status": "loaded", "release": release, "rules": res.rules}


@app.task(name="sigma.sync", queue=QUEUE_MAINTENANCE)
def sync() -> dict[str, Any]:
    if not get_settings().sigma.sync_enabled:
        log.info("sigma_sync_disabled")
        return {"skipped": "disabled"}
    from cti_core.db.engine import sync_session

    with sync_session() as session:
        out = sync_sigma(session, http_get_json, http_get_bytes)
        session.commit()
    log.info("sigma_synced", **out)
    return out
