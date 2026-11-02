"""Keputusan murni replay otomatis artikel `[enrichment_failed]` (spec 4.2).

Modul ini TIDAK menyentuh DB atau Redis: semua masukan (status LLM terakhir, kedalaman antrian,
kandidat) dikumpulkan pemanggil (`cti_worker.tasks.llm_maintenance`), sehingga aturannya bisa diuji
tanpa Docker.

Aturan: LLM terbukti sehat (`llm_calls` terbaru untuk classify/ttp berstatus `ok`) -> kirim satu
batch sebesar `BATCH`, dibatasi sisa ruang antrian `enrich`. Status tidak jelas (error, kosong,
belum ada baris) atau kedalaman antrian tidak terbaca -> canary: tepat satu artikel, hasilnya
yang menentukan putaran berikutnya.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass

from cti_core.llm.breaker import ALERT_WINDOW, is_fresh

__all__ = ["ALERT_WINDOW", "is_fresh"]

BATCH = 20
MAX_ATTEMPTS = 3
BACKOFF_BASE = datetime.timedelta(minutes=30)
"""Jeda minimal sebelum percobaan berikutnya: `BACKOFF_BASE * 2 ** auto_replay_count`."""


@dataclass(frozen=True)
class ReplayCandidate:
    id: int
    url: str
    title: str
    source: str
    scraper_id: str | None
    posted_on: datetime.date | None
    auto_replay_count: int
    last_auto_replay_at: datetime.datetime | None


def plan_auto_replay(
    candidates: Sequence[ReplayCandidate],
    *,
    last_status: str | None,
    queue_depth: int | None,
    max_depth: int,
    now: datetime.datetime,
) -> list[ReplayCandidate]:
    """Pilih kandidat yang dikirim ulang sekarang (urutan `candidates` dipertahankan: tertua dulu).
    `max_depth <= 0` berarti guard antrian mati (sama seperti `ensure_enrich_capacity`)."""
    if not candidates:
        return []
    if last_status != "ok" or queue_depth is None:
        return list(candidates[:1])
    room = BATCH if max_depth <= 0 else max(0, max_depth - queue_depth)
    return list(candidates[: min(BATCH, room)])
