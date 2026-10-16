"""Skema halaman admin "Third-party keys" (ROADMAP #23).

Aturan yang dikunci bentuk datanya: NILAI SECRET TIDAK PERNAH ADA di respons. Field secret hanya
membawa `last4` (empat karakter terakhir, dan hanya kalau key cukup panjang supaya empat karakter
itu tidak membuka sebagian besarnya); field non-secret membawa nilai efektifnya apa adanya.
Timestamp `str` ISO 8601, pola yang sama dengan router lain di sini.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["db", "env", "unset"]
"""`db` = ada override dari halaman ini, `env` = nilai dari `.env`, `unset` = kosong."""


class SecretFieldOut(BaseModel):
    name: str
    secret: bool
    source: Source
    value: str | None
    """Hanya field NON-secret; field secret SELALU `None`."""
    last4: str | None
    """Hanya field secret yang terisi dan panjangnya >= 12."""
    choices: list[str]


class SecretTestOut(BaseModel):
    status: Literal["OK", "FAIL", "SKIP", "NOTE"]
    """OK = diterima vendor; FAIL = ditolak/tidak terjangkau; SKIP = tidak ada yang dites (kosong);
    NOTE = key diterima tapi kena batas pemakaian, jadi BELUM terbukti valid."""
    detail: str


class SecretProviderOut(BaseModel):
    key: str
    label: str
    source: Source
    fields: list[SecretFieldOut]
    updated_by: str | None
    updated_at: str | None
    last_test_ok: bool | None
    last_test_at: str | None
    error: str | None
    """`decrypt_failed` / `invalid_row` / `master_key_missing` kalau baris override tidak terbaca
    (provider itu memakai `.env`; proses yang berumur panjang bisa masih memegang override lama
    sampai restart); selain itu `None`."""
    probe: SecretTestOut | None = None
    """Hanya di respons PUT: hasil probe sebelum simpan. Status selain OK berarti key TERSIMPAN
    tetapi tidak terverifikasi."""


class SecretsStatusOut(BaseModel):
    enabled: bool
    """Master key terkonfigurasi. Tanpa itu halaman hanya menampilkan status dari `.env`."""
    providers: list[SecretProviderOut]


class SecretSetBody(BaseModel):
    fields: dict[str, str | None] = Field(..., min_length=1)
    """string = set, `null` = hapus field dari override (balik ke `.env`), tidak dikirim = tetap."""
    current_password: str = Field(..., min_length=1, max_length=200)


class SecretClearBody(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
