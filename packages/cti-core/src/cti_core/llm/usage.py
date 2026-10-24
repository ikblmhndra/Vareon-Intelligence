"""Pencatatan tiap panggilan LLM ke tabel `llm_calls` (best-effort).

Dipanggil dari klien terinstrumentasi (`get_llm_client(task=...)`), jadi satu titik menutup
semua pemanggil. Kegagalan mencatat TIDAK PERNAH boleh menggagalkan panggilan LLM: token sudah
terbayar dan pemanggilnya (enrichment, recap, email CVE) tidak tahu soal log ini.

Pengecualian yang diterima (spec bagian 3.2): `fetch()` scraper di `monitor_x`/`tweet_alerts`
dilarang menyentuh DB, tetapi mereka memanggil LLM lewat klien ini, jadi `fetch()` mereka
mencapai DB lewat log best-effort ini saja. Tidak ada jalur baca/tulis lain dari scraper."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


def prompt_version(prompt: str) -> str:
    """Sidik 8 hex dari teks prompt; berubah otomatis kalau prompt diedit."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:8]


def record_call(**fields: Any) -> None:
    """Tulis satu baris `llm_calls`; telan dan log semua exception."""
    try:
        # Import malas: `cti_core.db` menarik `cti_core.config`, hindari siklus saat import.
        from cti_core.db.engine import sync_session
        from cti_core.db.repositories.llm_call import LlmCallRepo

        with sync_session() as session:
            LlmCallRepo(session).add(**fields)
    except Exception:
        logger.warning("llm_call_record_failed", exc_info=True)
