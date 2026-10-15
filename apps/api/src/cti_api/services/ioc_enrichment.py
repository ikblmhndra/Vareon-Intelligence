"""Penulis `iocs.enrichment` (ROADMAP #4): reputasi IOC dari provider luar.

Dijalankan PERIODIK oleh task `ioc.enrich_pending` (antrean `maintenance`), BUKAN sebagai langkah
pipeline artikel: pipeline enrichment sudah 10-13 detik + LLM per artikel, dan satu provider yang
lambat atau mati tidak boleh menahan artikel. Hasilnya dibaca UI lewat detail IOC (kartu "TIP
Enrichment" di `ioc-detail-dialog.tsx`); bentuk kartu ada di `ioc_providers`.

Aturan yang SENGAJA begitu:

- **Pemilihan** (`AsyncIOCRepo.list_needing_enrichment`): tipe yang didukung provider, bukan IOC
  yang `auto_suppressed`, belum punya kartu provider itu atau kartunya lebih tua dari TTL; terbaru
  dilihat dulu. Volume produksi (2026-10-15) sekitar 24 IP baru per hari, jauh di bawah jatah
  gratis, jadi tidak ada saringan prioritas tambahan: semua IOC yang didukung dicek, dibatasi
  jatah per jam.
- **Jatah**: `allow(provider, rate)` (bucket Redis per provider, disuntik task) dipanggil sebelum
  tiap lookup; habis = provider berhenti di run ini (`stopped="budget"`), run berikutnya lanjut.
- **Isolasi kegagalan**: satu IOC gagal (jaringan, 5xx, respons aneh) tidak menghentikan yang lain
  dan tidak meninggalkan kartu (dicoba lagi di run berikutnya). Status 401/403/429 (kunci salah,
  kuota habis) menghentikan provider itu di run ini, dan tiga kegagalan beruntun juga, supaya
  provider yang mati tidak dihantam puluhan kali per run. Provider lain tetap jalan.
- **Log**: hanya nama kelas exception dan kode status, TIDAK pernah pesannya (pesan exception
  httpx bisa memuat URL dengan kunci).
- **Nilai di-refang** sebelum dikirim (IOC disimpan apa adanya dari artikel, mis. `1[.]2[.]3[.]4`).
  IP non-publik tidak dikirim; ia diberi kartu `skipped` supaya tidak dipilih ulang tiap run.
- **Commit per IOC**: hasil yang sudah didapat (dan jatah yang sudah terpakai) tidak hilang kalau
  run berikutnya gagal di tengah.
"""

from __future__ import annotations

import asyncio
import datetime
import ipaddress
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

import httpx
import structlog
from cti_core.config import Settings
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.ioc.extractor import refang
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import ioc_providers

log = structlog.get_logger()

MAX_PER_RUN = 25
"""Batas IOC per provider per run (task jalan tiap 15 menit); jatah per jam tetap yang membatasi."""
_STOP_STATUSES = frozenset({401, 403, 429})
_MAX_CONSECUTIVE_FAILURES = 3

AllowFn = Callable[[str, str], bool]
SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class ProviderSpec:
    """Satu provider yang aktif. `lookup` menerima nilai IOC yang SUDAH di-refang dan mengembalikan
    kartu (lihat `ioc_providers`); kegagalan dilempar, bukan dikembalikan."""

    key: str
    name: str
    types: frozenset[str]
    ttl: datetime.timedelta
    rate: str
    min_interval: float
    lookup: Callable[[str], Awaitable[dict[str, Any]]]


def build_specs(settings: Settings, http: httpx.AsyncClient) -> list[ProviderSpec]:
    """Provider yang kuncinya terisi; kunci kosong = provider mati (tidak ada panggilan)."""
    specs: list[ProviderSpec] = []
    abuse = settings.abuseipdb
    if abuse.api_key:
        specs.append(
            ProviderSpec(
                key=ioc_providers.ABUSEIPDB,
                name=ioc_providers.ABUSEIPDB_NAME,
                types=frozenset({"ip"}),
                ttl=datetime.timedelta(days=3),
                rate=abuse.rate,
                min_interval=0.0,
                lookup=partial(ioc_providers.lookup_abuseipdb, http, abuse.api_key),
            )
        )
    return specs


def _skip_reason(ioc_type: str, value: str) -> str | None:
    """Alasan IOC tidak layak dikirim ke provider mana pun, atau `None`."""
    if ioc_type == "ip":
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return "not a valid IP address"
        if not address.is_global:
            return "not a public IP address"
    return None


def _new_stats() -> dict[str, Any]:
    return {"checked": 0, "skipped": 0, "failed": 0, "stopped": None}


async def enrich_pending(
    session: AsyncSession,
    *,
    specs: Sequence[ProviderSpec],
    allow: AllowFn,
    now: datetime.datetime | None = None,
    max_per_run: int = MAX_PER_RUN,
    sleep: SleepFn = asyncio.sleep,
) -> dict[str, dict[str, Any]]:
    """Satu putaran untuk semua `specs`. Mengembalikan statistik per provider:
    `checked`, `skipped`, `failed`, dan `stopped` (`None` | `"budget"` | `"HTTP <kode>"` |
    `"consecutive_failures"`)."""
    now = now or datetime.datetime.now(datetime.UTC)
    repo = AsyncIOCRepo(session)
    summary: dict[str, dict[str, Any]] = {}

    for spec in specs:
        stats = summary[spec.key] = _new_stats()
        candidates = await repo.list_needing_enrichment(
            provider=spec.key,
            types=sorted(spec.types),
            checked_before=now - spec.ttl,
            limit=max_per_run,
        )
        looked_up = 0
        failures_in_a_row = 0
        for ioc in candidates:
            value = refang(ioc.value)
            reason = _skip_reason(ioc.type, value)
            if reason is not None:
                card = ioc_providers.skipped_card(spec.key, spec.name, reason)
                card["checked_at"] = now.isoformat()
                await repo.set_enrichment_provider(ioc, card, now=now)
                await session.commit()
                stats["skipped"] += 1
                continue

            if not allow(spec.key, spec.rate):
                stats["stopped"] = "budget"
                break
            if looked_up and spec.min_interval:
                await sleep(spec.min_interval)
            looked_up += 1

            try:
                card = await spec.lookup(value)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                log.warning(
                    "ioc_enrich_failed", provider=spec.key, error="HTTPStatusError", status=status
                )
                if status in _STOP_STATUSES:
                    stats["stopped"] = f"HTTP {status}"
                    break
                stats["failed"] += 1
                failures_in_a_row += 1
            except (httpx.TransportError, ValueError, KeyError, TypeError) as exc:
                log.warning("ioc_enrich_failed", provider=spec.key, error=type(exc).__name__)
                stats["failed"] += 1
                failures_in_a_row += 1
            else:
                failures_in_a_row = 0
                card["checked_at"] = now.isoformat()
                await repo.set_enrichment_provider(ioc, card, now=now)
                await session.commit()
                stats["checked"] += 1

            if failures_in_a_row >= _MAX_CONSECUTIVE_FAILURES:
                stats["stopped"] = "consecutive_failures"
                break

    return summary
