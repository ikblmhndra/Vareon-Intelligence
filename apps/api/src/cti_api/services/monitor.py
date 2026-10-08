"""Pemicu promosi saat Monitor berubah (ROADMAP #19, irisan 5).

Entri baru di-Monitor / diaktifkan / dapat target baru: riwayatnya diisi dari mirror oleh tugas
Celery `cve.promote_entry` (`apps/worker/.../tasks/cve_mirror.py`), tanpa tombol "Populate now".
API hanya MENGIRIM tugas lewat nama (`cti_core.celery_client`, tanpa import worker), dan hanya
SESUDAH commit: tugas membaca entri dari DB.

Best effort dan sengaja tidak pernah menggagalkan request: broker mati = riwayat entri itu belum
terisi (jalankan `make promote-cve-mirror MODE=... ARGS='--apply --entry <nama>'`); perubahan
Monitor-nya sendiri sudah tersimpan."""

from __future__ import annotations

import structlog
from cti_core.celery_client import get_celery_client
from cti_core.config import get_settings

log = structlog.get_logger()

QUEUE = "maintenance"
TASK = "cve.promote_entry"


def enqueue_promote_entry(entry_id: int) -> bool:
    """`True` bila tugas terkirim. Mati bila mirror/promosi belum dinyalakan (`cve_mirror`)."""
    cfg = get_settings().cve_mirror
    if not cfg.enabled or cfg.promote == "off":
        return False
    try:
        get_celery_client().send_task(TASK, kwargs={"entry_id": entry_id}, queue=QUEUE)
    except Exception as e:
        log.warning("promote_entry_enqueue_failed", entry_id=entry_id, error=str(e))
        return False
    return True
