"""Baca dan tulis data referensi IOC -- `ioc_allowlist_entries` dan
`threat_feed_entries` (lihat `db/models/ioc_reference.py`).

`get_ioc_allowlist()`/`get_c2_feed()` (baca, sync) bentuk balik dataset
PERSIS yang `iocExtractor._filter_iocs()`/`nlp.py::_check_c2_hit()` lama
harapkan (`dict[str, set[str]]`) -- caller (`cti_enrich.stages.
extract_iocs`) gak perlu tau bentuk tabel, cuma pasang set ini ke fungsi
lama yang udah ada.

`AsyncIocAllowlistRepo` (tulis, Fase 7.3 -- router `iocs.py`) BARU, gak ada
pas Fase 5 karena tabelnya waktu itu cuma dibaca. **Sengaja gak port**
`_sweep_delete_matching()` (legacy: nambah allowlist entry retroaktif
nge-hapus baris IOC lama yang cocok) -- filtering udah kejadian di
EXTRACTION time sekarang (`extract_iocs.py`, cache TTL 300s), jadi entry
baru otomatis efektif buat artikel BARU tanpa perlu sweep; bersihin baris
LAMA yang udah kepalang ke-extract itu fitur admin terpisah, bukan bagian
inti nambah allowlist entry."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.indicator import Indicator
from cti_core.db.models.ioc_reference import IocAllowlistEntry, ThreatFeedEntry
from cti_core.ioc.allowlist import allowlist_reason

_VALID_ALLOWLIST_TYPES = frozenset({"url_domain", "email_domain", "ip"})


def get_ioc_allowlist(session: Session) -> dict[str, set[str]]:
    rows = session.execute(select(IocAllowlistEntry.type, IocAllowlistEntry.value)).all()
    result: dict[str, set[str]] = {"url_domains": set(), "email_domains": set(), "ips": set()}
    _key = {"url_domain": "url_domains", "email_domain": "email_domains", "ip": "ips"}
    for type_, value in rows:
        key = _key.get(type_)
        if key:
            result[key].add(value.lower() if key != "ips" else value)
    return result


def get_c2_feed(session: Session, *, feed: str = "deepdarkcti_c2") -> dict[str, set[str]]:
    rows = session.execute(
        select(ThreatFeedEntry.type, ThreatFeedEntry.value).where(ThreatFeedEntry.feed == feed)
    ).all()
    result: dict[str, set[str]] = {"ips": set(), "domains": set()}
    for type_, value in rows:
        if type_ == "ip":
            result["ips"].add(value)
        else:
            result["domains"].add(value.lower())
    return result


class AsyncIocAllowlistRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[IocAllowlistEntry]:
        result = await self.session.execute(
            select(IocAllowlistEntry).order_by(IocAllowlistEntry.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, entry_type: str, value: str) -> IocAllowlistEntry | None:
        result = await self.session.execute(
            select(IocAllowlistEntry).where(
                IocAllowlistEntry.type == entry_type, IocAllowlistEntry.value == value
            )
        )
        return result.scalar_one_or_none()

    async def create(self, *, entry_type: str, value: str, added_by: str) -> IocAllowlistEntry:
        if entry_type not in _VALID_ALLOWLIST_TYPES:
            raise ValueError(f"type harus salah satu dari {_VALID_ALLOWLIST_TYPES}")
        value = value.strip().lower()
        existing = await self.get(entry_type, value)
        if existing is not None:
            return existing
        entry = IocAllowlistEntry(type=entry_type, value=value, added_by=added_by)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def delete(self, entry_id: int) -> bool:
        """Hapus entri DAN batalkan tanda `auto_suppressed` yang dibuatnya (sejak 0.8.6 allowlist
        menandai, bukan membuang): hanya IOC yang alasannya persis entri ini, jadi alasan lain
        (entri allowlist lain, FP analis) tidak tersentuh."""
        result = await self.session.execute(
            select(IocAllowlistEntry).where(IocAllowlistEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return False
        await self.session.execute(
            update(Indicator)
            .where(Indicator.suppression_reason == allowlist_reason(entry.type, entry.value))
            .values(auto_suppressed=False, suppression_reason=None)
        )
        await self.session.delete(entry)
        await self.session.flush()
        return True
