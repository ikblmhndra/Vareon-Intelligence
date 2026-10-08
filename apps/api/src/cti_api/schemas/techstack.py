"""Adaptasi dari `ScraperNewsWeb/app/models/techstack.py` -- `id` sekarang
`int`, `added_date` sekarang tanggal ISO string (bisa kosong)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

EXPOSURE_MULTIPLIER = {"public": 1.5, "both": 1.25, "internal": 1.0}
HOSTING_MULTIPLIER = {"on_prem": 1.0, "cloud": 1.0, "saas": 0.8}
"""Dipakai `cve.py` (nyusul) buat `adjusted_risk_score` -- didefinisikan
di sini (bukan di router `cve.py` yang belum ada) karena ini genuinely
punya `techstack`, bukan `cve`."""


class TechStackTargetOut(BaseModel):
    """Satu sasaran katalog entri Monitor: vendor ATAU keluarga (tepat satu terisi)."""

    id: int
    kind: Literal["vendor", "family"]
    vendor_id: int | None = None
    family_id: int | None = None
    label: str
    """Nama tampilan katalog ("Fortinet", "FortiOS")."""
    vendor_label: str = ""
    """Vendor pemilik keluarga (kosong untuk target vendor)."""


class TechStackOut(BaseModel):
    id: int
    name: str
    added_date: str = ""
    source: str = ""
    exposure: str = "internal"
    hosting_type: str = "on_prem"
    active: bool = True
    """False = disembunyikan (tidak dicocokkan, tidak tampil di tab CVEs); tidak dihapus."""
    kind: Literal["catalog", "custom"] = "custom"
    """`catalog` = punya target katalog; `custom` = entri lama/bebas (dicocokkan lewat teks nama,
    belum terverifikasi terhadap katalog)."""
    targets: list[TechStackTargetOut] = []


class TechStackAdd(BaseModel):
    """Tiga bentuk: `name` saja (entri custom, perilaku lama), `vendor_id` atau `family_id` (entri
    katalog; `name` opsional menimpa label bawaan = nama tampilan katalog)."""

    name: str | None = None
    vendor_id: int | None = None
    family_id: int | None = None
    exposure: str = "internal"
    hosting_type: str = "on_prem"

    @model_validator(mode="after")
    def _one_shape(self) -> TechStackAdd:
        if self.vendor_id is not None and self.family_id is not None:
            raise ValueError("isi vendor_id ATAU family_id, bukan keduanya")
        if self.vendor_id is None and self.family_id is None and not (self.name or "").strip():
            raise ValueError("isi name (entri custom), vendor_id, atau family_id")
        return self


class TechStackTargetAdd(BaseModel):
    vendor_id: int | None = None
    family_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> TechStackTargetAdd:
        if (self.vendor_id is None) == (self.family_id is None):
            raise ValueError("isi tepat satu: vendor_id atau family_id")
        return self


class TechStackPatch(BaseModel):
    active: bool


class TechStackExposureUpdate(BaseModel):
    exposure: str


class TechStackHostingUpdate(BaseModel):
    hosting_type: str


class TechStackListResponse(BaseModel):
    items: list[TechStackOut]
    total: int
    page: int
    page_size: int
