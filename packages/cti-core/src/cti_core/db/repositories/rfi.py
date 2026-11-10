"""AsyncRFIRepo -- CRUD `rfi_requests` (Fase 7.3, Bagian 2). Port dari
`ScraperNewsWeb/app/services/rfi_service.py`. Client filter langsung
`== client_id` (skema baru NOT NULL FK dari awal) -- gak butuh fallback
OR ("default" ATAU field gak ada) kayak Mongo lama, sama pola yang udah
dipakai `AsyncTechStackRepo`.

**Asimetri client-scoping port apa adanya dari kode lama, BUKAN
keputusan baru:** `list_rfis`/`get_rfi`/`create_rfi` di-filter client_id,
tapi `update_rfi`/`delete_rfi` lama SAMA SEKALI gak nerima/nge-filter
client_id (`rfi_service.py` asli, fungsi `update_rfi(rfi_id, updates)`
dan `delete_rfi(rfi_id)` -- router-nya juga gak manggil
`effective_client_id` buat dua endpoint itu). Efeknya: siapa pun yang
tahu ID RFI bisa update/delete lintas client. Dipertahankan sesuai
instruksi "port apa adanya, flag asimetri, jangan diam-diam diperbaiki"
-- lihat juga pola sama di `articles.py`/`filtered_articles.py`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.rfi import RFIRequest

# Batas RFI tertaut per PIR yang dikirim ke UI: PIR dengan ratusan RFI tidak boleh membengkakkan
# respons daftar PIR; yang masih terbuka sudah diurutkan paling depan.
_LINKED_RFI_CAP = 20

_RFI_STATUSES = ("open", "in_progress", "closed")


def _like(text: str) -> str:
    """Pola ILIKE aman: `%`, `_`, dan `\\` dalam input pengguna diperlakukan literal."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _apply_search[S: Select[Any]](stmt: S, *, q: str | None, linked_pir: int | None) -> S:
    """Filter pencarian + PIR yang dipakai bersama oleh daftar dan hitungan chip status."""
    if q:
        pattern = _like(q)
        stmt = stmt.where(
            or_(
                RFIRequest.question.ilike(pattern, escape="\\"),
                RFIRequest.requester.ilike(pattern, escape="\\"),
            )
        )
    if linked_pir is not None:
        stmt = stmt.where(RFIRequest.linked_pir_id == linked_pir)
    return stmt


class AsyncRFIRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_filtered(
        self,
        *,
        client_id: str,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
        q: str | None = None,
        linked_pir: int | None = None,
        sort: Literal["created", "due"] = "created",
    ) -> tuple[list[RFIRequest], int]:
        stmt = select(RFIRequest).where(RFIRequest.client_id == client_id)
        if status:
            stmt = stmt.where(RFIRequest.status == status)
        stmt = _apply_search(stmt, q=q, linked_pir=linked_pir)

        # `id` jadi tie-breaker supaya halaman stabil saat due_date/created_at sama.
        order = (
            (RFIRequest.due_date.asc().nulls_last(), RFIRequest.id)
            if sort == "due"
            else (RFIRequest.created_at.desc(), RFIRequest.id.desc())
        )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        list_stmt = stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(list_stmt)
        return list(result.scalars().all()), total

    async def status_counts(
        self, client_id: str, *, q: str | None = None, linked_pir: int | None = None
    ) -> dict[str, int]:
        """Jumlah RFI per status untuk chip filter: satu `GROUP BY`, tidak ikut filter `status`
        daftar (chip harus tetap menunjukkan total tiap status). `q` dan `linked_pir` ikut,
        supaya angka chip sama dengan daftar yang sedang dicari/disaring PIR. Status tak dikenal
        diabaikan."""
        stmt = select(RFIRequest.status, func.count()).where(RFIRequest.client_id == client_id)
        stmt = _apply_search(stmt, q=q, linked_pir=linked_pir)
        result = await self.session.execute(stmt.group_by(RFIRequest.status))
        found: dict[str, int] = {status: n for status, n in result.all()}
        return {s: int(found.get(s, 0)) for s in _RFI_STATUSES}

    async def list_by_pirs(
        self, client_id: str, pir_ids: Sequence[int]
    ) -> dict[int, list[RFIRequest]]:
        """RFI tertaut per PIR dalam SATU query. `linked_pir_id` hanyalah FK tanpa cek client,
        jadi RFI client lain yang menunjuk PIR ini harus disaring lewat `client_id`. Urutan:
        open, in_progress, closed, status tak dikenal; lalu due_date terdekat (NULL terakhir),
        lalu id. Dipotong `_LINKED_RFI_CAP` di Python supaya SQL tetap satu pernyataan sederhana."""
        if not pir_ids:
            return {}
        rank = case(
            (RFIRequest.status == "open", 0),
            (RFIRequest.status == "in_progress", 1),
            (RFIRequest.status == "closed", 2),
            else_=3,
        )
        result = await self.session.execute(
            select(RFIRequest)
            .where(RFIRequest.client_id == client_id, RFIRequest.linked_pir_id.in_(pir_ids))
            .order_by(rank, RFIRequest.due_date.asc().nulls_last(), RFIRequest.id)
        )
        out: dict[int, list[RFIRequest]] = {}
        for rfi in result.scalars():
            assert rfi.linked_pir_id is not None
            bucket = out.setdefault(rfi.linked_pir_id, [])
            if len(bucket) < _LINKED_RFI_CAP:
                bucket.append(rfi)
        return out

    async def get_by_id(self, rfi_id: int, client_id: str) -> RFIRequest | None:
        result = await self.session.execute(
            select(RFIRequest).where(RFIRequest.id == rfi_id, RFIRequest.client_id == client_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_unscoped(self, rfi_id: int) -> RFIRequest | None:
        """Dipakai `update`/`delete` -- legacy gak nge-filter client_id di
        sana, lihat docstring modul."""
        result = await self.session.execute(select(RFIRequest).where(RFIRequest.id == rfi_id))
        return result.scalar_one_or_none()

    async def create(self, data: dict[str, Any], *, client_id: str) -> RFIRequest:
        rfi = RFIRequest(
            requester=data["requester"],
            question=data["question"],
            due_date=data.get("due_date"),
            status=data.get("status") or "open",
            linked_pir_id=data.get("linked_pir"),
            response=data.get("response") or "",
            client_id=client_id,
        )
        self.session.add(rfi)
        await self.session.flush()
        return rfi

    async def update(self, rfi_id: int, updates: dict[str, Any]) -> RFIRequest | None:
        rfi = await self.get_by_id_unscoped(rfi_id)
        if rfi is None:
            return None
        for key in ("requester", "question", "due_date", "status", "response"):
            if key in updates:
                setattr(rfi, key, updates[key])
        if "linked_pir" in updates:
            rfi.linked_pir_id = updates["linked_pir"]
        await self.session.flush()
        return rfi

    async def delete(self, rfi_id: int) -> bool:
        rfi = await self.get_by_id_unscoped(rfi_id)
        if rfi is None:
            return False
        await self.session.delete(rfi)
        await self.session.flush()
        return True
