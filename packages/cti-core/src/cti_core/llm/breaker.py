"""Circuit breaker LLM tanpa state dan batas dispatch (spec P7g 4.4 / 4.5).

Murni: tidak menyentuh DB atau Redis. Status dihitung dari baris `llm_calls` terbaru (task
`classify` dan `ttp`) yang dikumpulkan pemanggil; `error` dan `empty` dihitung gagal. Tanpa state
Redis dan tanpa setting baru, supaya restart worker tidak mengubah keputusan.

Tertutup: kegagalan beruntun < `OPEN_AFTER`. Terbuka: n >= 3 dan cooldown
`min(30 mnt, 2 mnt * 2^(n-3))` belum lewat. Setengah terbuka: cooldown lewat, tepat satu job
dikirim sebagai canary dan hasilnya (tercatat di `llm_calls`) menentukan putaran berikutnya.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

BREAKER_TASKS = ("classify", "ttp")
OPEN_AFTER = 3
BATCH = 20
LEASE = datetime.timedelta(minutes=15)
"""Sewa `next_attempt_at` saat job diklaim: crash antara commit dan send tidak membuat kirim ulang
tanpa henti."""
ALERT_WINDOW = datetime.timedelta(hours=24)
RECENT_CALLS = 12
"""Berapa baris `llm_calls` terbaru yang dibaca untuk `breaker_state`. Cooldown sudah mentok di
batas 30 menit pada n=7 (2 mnt * 2^4 = 32), jadi 12 baris cukup dan bacanya tetap murah."""

_COOLDOWN_BASE = datetime.timedelta(minutes=2)
_COOLDOWN_MAX = datetime.timedelta(minutes=30)
_FAILED = ("error", "empty")


def is_fresh(posted_on: datetime.date | None, now: datetime.datetime) -> bool:
    """Artikel masih layak di-alert Telegram. `posted_on` hanya berupa tanggal, jadi "dalam 24 jam"
    ditafsirkan `posted_on >= (now - 24 jam).date()` (kemarin dan hari ini); None -> False."""
    if posted_on is None:
        return False
    return posted_on >= (now - ALERT_WINDOW).date()


@dataclass(frozen=True)
class CallOutcome:
    status: str
    at: datetime.datetime


@dataclass(frozen=True)
class Breaker:
    state: Literal["closed", "open", "half_open"]
    failures: int
    retry_at: datetime.datetime | None
    """Akhir cooldown; None saat tertutup."""


def breaker_state(recent: Sequence[CallOutcome], now: datetime.datetime) -> Breaker:
    """`recent` terbaru dulu. Hitung kegagalan beruntun dari yang terbaru sampai status non-gagal
    pertama."""
    n = 0
    for outcome in recent:
        if outcome.status not in _FAILED:
            break
        n += 1
    if n < OPEN_AFTER:
        return Breaker("closed", n, None)
    cooldown = min(_COOLDOWN_MAX, _COOLDOWN_BASE * 2 ** (n - OPEN_AFTER))
    retry_at = recent[0].at + cooldown
    return Breaker("open" if now < retry_at else "half_open", n, retry_at)


def dispatch_limit(breaker: Breaker, *, queue_depth: int | None, max_depth: int) -> int:
    """Berapa job yang boleh dikirim sekarang. Terbuka 0, setengah terbuka 1 (canary). Tertutup:
    sisa ruang antrian `enrich` dibatasi `BATCH`; kedalaman tak terbaca -> 1 (ukuran canary);
    `max_depth <= 0` berarti guard antrian mati (sama seperti `ensure_enrich_capacity`)."""
    if breaker.state == "open":
        return 0
    if breaker.state == "half_open":
        return 1
    if queue_depth is None:
        return 1
    if max_depth <= 0:
        return BATCH
    return max(0, min(BATCH, max_depth - queue_depth))
