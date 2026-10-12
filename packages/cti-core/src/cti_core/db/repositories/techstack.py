"""AsyncTechStackRepo -- CRUD inti `techstack_entries` (Fase 2). Pola "web
kurasi, scraper patuh" -- `cti_scraper.reference_data`/`cti_enrich.stages.
score` UDAH baca tabel ini (Fase 3/4/5, live), router ini yang jadi jalur
admin buat ngisi/ubah datanya.

**Sengaja gak diport ke sini** (tetap di `techstack_service.py` lama buat
sekarang, nyusul bareng `cve.py`): backfill CVE dari client lain
(`_backfill_cves_for_tech`), trigger fetch historis NVD/MITRE
(`backfill_nvd_for_tech`/`_fetch_nvd_cves`/`_fetch_mitre_details`), dan
cascade-delete CVE pas tech dihapus (`delete_techstack` lama) -- semua itu
NULIS ke `cve_tracker` (`CveTrackerRepo`, plan §7.3 cve.py), bukan tanggung
jawab tabel `techstack_entries` sendiri. Router ini murni CRUD daftar tech
stack, gak nyentuh CVE sama sekali.

`_client_filter` Mongo lama punya fallback OR (`client_id == "default"`
ATAU field gak ada sama sekali) -- itu kompat data lama pra-multi-tenant.
Skema Postgres `client_id` NOT NULL (FK ke `clients`) sejak awal, kasus
"field gak ada" gak mungkin kejadian -- filter langsung `== client_id`,
gak perlu fallback."""

from __future__ import annotations

import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.catalog_resolve import VENDOR_NONE_KEY
from cti_core.db.models.catalog import CatalogFamily, CatalogVendor
from cti_core.db.models.techstack import TechStackEntry, TechStackTarget

_VALID_EXPOSURE = frozenset({"public", "internal", "both"})
_VALID_HOSTING = frozenset({"on_prem", "cloud", "saas"})
_SORT_FIELDS = {
    "name": TechStackEntry.name,
    "added_date": TechStackEntry.added_date,
    "source": TechStackEntry.source,
    "exposure": TechStackEntry.exposure,
    "hosting_type": TechStackEntry.hosting_type,
}


class AsyncTechStackRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_filtered(
        self,
        *,
        client_id: str,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_dir: str = "asc",
        active: bool | None = None,
    ) -> tuple[list[TechStackEntry], int]:
        stmt = select(TechStackEntry).where(TechStackEntry.client_id == client_id)
        if active is not None:
            stmt = stmt.where(TechStackEntry.active.is_(active))
        if search:
            stmt = stmt.where(TechStackEntry.name.ilike(f"%{search}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        order_col = _SORT_FIELDS.get(sort_by, TechStackEntry.name)
        order = order_col.desc() if sort_dir == "desc" else order_col.asc()
        list_stmt = stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(list_stmt)
        return list(result.scalars().all()), total

    async def get_by_name_ci(self, name: str, client_id: str) -> TechStackEntry | None:
        result = await self.session.execute(
            select(TechStackEntry).where(
                func.lower(TechStackEntry.name) == name.lower(),
                TechStackEntry.client_id == client_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, tech_id: int, client_id: str) -> TechStackEntry | None:
        result = await self.session.execute(
            select(TechStackEntry).where(
                TechStackEntry.id == tech_id, TechStackEntry.client_id == client_id
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        client_id: str,
        exposure: str = "internal",
        hosting_type: str = "on_prem",
    ) -> tuple[TechStackEntry | None, str]:
        """`(None, "duplicate")` kalau nama udah ada (case-insensitive) buat
        client ini -- port perilaku `add_techstack()` lama, bukan raise."""
        if await self.get_by_name_ci(name, client_id) is not None:
            return None, "duplicate"
        entry = TechStackEntry(
            name=name,
            client_id=client_id,
            exposure=exposure if exposure in _VALID_EXPOSURE else "internal",
            hosting_type=hosting_type if hosting_type in _VALID_HOSTING else "on_prem",
            source="manual",
            added_date=datetime.date.today(),
            targets=[],  # entri custom; tanpa ini akses `.targets` memicu lazy-load async
        )
        self.session.add(entry)
        await self.session.flush()
        return entry, "ok"

    async def update_exposure(self, tech_id: int, exposure: str, client_id: str) -> bool:
        if exposure not in _VALID_EXPOSURE:
            return False
        entry = await self.get_by_id(tech_id, client_id)
        if entry is None:
            return False
        entry.exposure = exposure
        await self.session.flush()
        return True

    async def update_hosting(self, tech_id: int, hosting_type: str, client_id: str) -> bool:
        if hosting_type not in _VALID_HOSTING:
            return False
        entry = await self.get_by_id(tech_id, client_id)
        if entry is None:
            return False
        entry.hosting_type = hosting_type
        await self.session.flush()
        return True

    async def delete(self, tech_id: int, client_id: str) -> bool:
        entry = await self.get_by_id(tech_id, client_id)
        if entry is None:
            return False
        await self.session.delete(entry)
        await self.session.flush()
        return True

    # ── scope tab CVEs: aktif vs semua ────────────────────────────────────────────────────────

    async def visible_names(self, client_id: str) -> list[str] | None:
        """Nama entri AKTIF client ini, untuk menyaring tab CVEs/stats/dashboard/export.

        `None` = client belum punya entri sama sekali (perilaku lama: tanpa filter tech).
        `[]` = punya entri tapi semuanya nonaktif: tab tidak menampilkan apa pun. Dibedakan dengan
        sengaja; "kosong" yang tadinya berarti "tanpa filter" akan membalik arti "disembunyikan"."""
        rows = (
            await self.session.execute(
                select(TechStackEntry.name, TechStackEntry.active).where(
                    TechStackEntry.client_id == client_id
                )
            )
        ).all()
        if not rows:
            return None
        return [name for name, active in rows if active]

    async def active_names_all_clients(self) -> list[str]:
        """Nama entri AKTIF dari SEMUA client, unik dan urut. Persis himpunan yang dipakai
        `cti_enrich.stages.score.score()` untuk menandai artikel yang menyebut tech terpantau,
        versi async untuk API. Kosong = tidak ada tech terpantau (bukan "semua cocok")."""
        result = await self.session.execute(
            select(TechStackEntry.name)
            .where(TechStackEntry.active.is_(True))
            .distinct()
            .order_by(TechStackEntry.name)
        )
        return list(result.scalars().all())

    async def all_names(self, client_id: str) -> list[str]:
        """Semua nama entri, aktif maupun nonaktif (`purge-orphaned`: yang disembunyikan BUKAN
        yatim, barisnya tidak boleh ikut terhapus)."""
        result = await self.session.execute(
            select(TechStackEntry.name).where(TechStackEntry.client_id == client_id)
        )
        return list(result.scalars().all())

    # ── Monitor berbasis katalog (ROADMAP #19) ────────────────────────────────────────────────

    async def _target_ref(
        self, vendor_id: int | None, family_id: int | None
    ) -> tuple[CatalogVendor | None, CatalogFamily | None, str]:
        """Validasi satu rujukan katalog -> (vendor, keluarga, alasan). Tepat satu id harus diisi;
        vendor tanpa identitas (`~none`) tidak bisa di-Monitor di tingkat vendor."""
        if (vendor_id is None) == (family_id is None):
            return None, None, "invalid_target"
        if vendor_id is not None:
            vendor = await self.session.get(CatalogVendor, vendor_id)
            if vendor is None:
                return None, None, "not_found"
            if not vendor.monitorable or vendor.key == VENDOR_NONE_KEY:
                return None, None, "vendor_not_monitorable"
            return vendor, None, "ok"
        assert family_id is not None
        family = await self.session.get(CatalogFamily, family_id)
        if family is None:
            return None, None, "not_found"
        return None, family, "ok"

    async def create_from_target(
        self,
        *,
        client_id: str,
        vendor_id: int | None = None,
        family_id: int | None = None,
        name: str | None = None,
        exposure: str = "internal",
        hosting_type: str = "on_prem",
    ) -> tuple[TechStackEntry | None, str]:
        """Tombol Monitor di All Tech: entri baru (label = nama tampilan katalog, atau `name`
        bila diberikan) dengan SATU target. Label tetap kunci join ke `cve_tracker.tech`, jadi
        harus unik per client (`duplicate` bila sudah dipakai: beri `name` lain)."""
        vendor, family, reason = await self._target_ref(vendor_id, family_id)
        if reason != "ok":
            return None, reason
        label = name or (vendor.display_name if vendor else family.display_name if family else "")
        label = label.strip()
        if not label:
            return None, "invalid_target"
        if await self.get_by_name_ci(label, client_id) is not None:
            return None, "duplicate"
        entry = TechStackEntry(
            name=label,
            client_id=client_id,
            exposure=exposure if exposure in _VALID_EXPOSURE else "internal",
            hosting_type=hosting_type if hosting_type in _VALID_HOSTING else "on_prem",
            source="catalog",
            added_date=datetime.date.today(),
        )
        self.session.add(entry)
        await self.session.flush()
        self.session.add(
            TechStackTarget(entry_id=entry.id, vendor_id=vendor_id, family_id=family_id)
        )
        await self.session.flush()
        await self.session.refresh(entry, ["targets"])
        return entry, "ok"

    async def add_target(
        self,
        tech_id: int,
        client_id: str,
        *,
        vendor_id: int | None = None,
        family_id: int | None = None,
    ) -> tuple[TechStackEntry | None, str]:
        entry = await self.get_by_id(tech_id, client_id)
        if entry is None:
            return None, "entry_not_found"
        _vendor, _family, reason = await self._target_ref(vendor_id, family_id)
        if reason != "ok":
            return None, reason
        if any(t.vendor_id == vendor_id and t.family_id == family_id for t in entry.targets):
            return None, "target_duplicate"
        self.session.add(
            TechStackTarget(entry_id=entry.id, vendor_id=vendor_id, family_id=family_id)
        )
        await self.session.flush()
        await self.session.refresh(entry, ["targets"])
        return entry, "ok"

    async def remove_target(
        self, tech_id: int, target_id: int, client_id: str
    ) -> tuple[TechStackEntry | None, str]:
        """Entri tidak boleh kehilangan target TERAKHIR: tanpa target ia kembali dicocokkan lewat
        teks (`docs/CVE_CATALOG_DESIGN.md` 3.4), perubahan perilaku diam-diam. Hapus entrinya atau
        nonaktifkan."""
        entry = await self.get_by_id(tech_id, client_id)
        if entry is None:
            return None, "entry_not_found"
        target = next((t for t in entry.targets if t.id == target_id), None)
        if target is None:
            return None, "target_not_found"
        if len(entry.targets) == 1:
            return None, "last_target"
        await self.session.delete(target)
        await self.session.flush()
        await self.session.refresh(entry, ["targets"])
        return entry, "ok"

    async def set_active(self, tech_id: int, client_id: str, active: bool) -> TechStackEntry | None:
        """Aktifkan/nonaktifkan (sembunyikan) entri. Tidak menghapus apa pun: baris `cve_tracker`
        dan ticket-nya tetap, hanya tidak muncul di tab CVEs."""
        entry = await self.get_by_id(tech_id, client_id)
        if entry is None:
            return None
        entry.active = active
        await self.session.flush()
        return entry

    async def get_risk_context(self, client_id: str) -> dict[str, dict[str, str]]:
        """`{name_lower: {exposure, hosting_type}}` -- port `get_tech_risk_context()`,
        dipakai `cve.py` (nyusul) buat `adjusted_risk_score`."""
        result = await self.session.execute(
            select(TechStackEntry).where(TechStackEntry.client_id == client_id)
        )
        return {
            e.name.lower(): {
                "exposure": e.exposure or "internal",
                "hosting_type": e.hosting_type or "on_prem",
            }
            for e in result.scalars().all()
        }
