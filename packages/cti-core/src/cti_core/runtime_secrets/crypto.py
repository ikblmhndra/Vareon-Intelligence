"""Enkripsi at-rest buat field secret di `runtime_secrets.secrets_enc` (ROADMAP #23).

Fernet (AES-128-CBC + HMAC-SHA256, berversi) lewat `MultiFernet`: `Settings.secrets_encryption_keys`
boleh berisi beberapa kunci dipisah koma; yang PERTAMA mengenkripsi, SEMUA mendekripsi. Rotasi
master key = taruh kunci baru di depan, tanpa migrasi data (token lama tetap kebaca sampai ditulis
ulang).

Payload yang dienkripsi adalah JSON `{"provider": ..., "client_id": ..., "fields": {...}}`, dan
`decrypt_fields` memverifikasi provider DAN client_id-nya: token milik baris `llm` yang tertukar ke
baris `nvd`, atau token milik workspace yang disalin ke baris platform (salah salin, atau seseorang
dengan akses tulis DB), ditolak, bukan diam-diam dipakai. `client_id` diikat sekarang selagi
tabelnya masih kosong: mengubah format payload sesudah ada data butuh migrasi.

Tidak ada fallback diam-diam di sini: tanpa master key `encrypt_fields` raise
`SecretsNotConfigured`. Keputusan "tanpa key = fitur mati, perilaku seperti sekarang" ada di
pemanggil (`overlay`, dan endpoint admin yang menjawab 503), bukan di lapis kripto.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from cti_core.config import get_settings


class SecretsNotConfigured(RuntimeError):
    """`SECRETS_ENCRYPTION_KEYS` kosong, jadi tidak ada master key."""


class SecretDecryptError(Exception):
    """Token tidak bisa dibuka: kunci salah/rotasi lupa, token rusak, atau bentuk/provider tidak
    cocok. Pesannya sengaja tidak memuat isi token atau nilai apa pun."""


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _split(keys: str | None) -> list[str]:
    raw = get_settings().secrets_encryption_keys if keys is None else keys
    return [k.strip() for k in raw.split(",") if k.strip()]


def is_configured(keys: str | None = None) -> bool:
    return bool(_split(keys))


def _multifernet(keys: str | None) -> MultiFernet:
    parts = _split(keys)
    if not parts:
        raise SecretsNotConfigured("SECRETS_ENCRYPTION_KEYS kosong: tidak ada master key.")
    return MultiFernet([Fernet(k) for k in parts])


def encrypt_fields(
    provider: str,
    fields: Mapping[str, str],
    *,
    client_id: str | None = None,
    keys: str | None = None,
) -> bytes:
    """`client_id` None = scope platform (satu-satunya yang ditulis di irisan pertama)."""
    payload = json.dumps(
        {"provider": provider, "client_id": client_id, "fields": dict(fields)},
        separators=(",", ":"),
    )
    return _multifernet(keys).encrypt(payload.encode())


def decrypt_fields(
    provider: str,
    token: bytes,
    *,
    client_id: str | None = None,
    keys: str | None = None,
) -> dict[str, str]:
    try:
        raw = _multifernet(keys).decrypt(token)
    except InvalidToken:
        raise SecretDecryptError("token tidak bisa didekripsi dengan kunci yang ada") from None
    try:
        payload = json.loads(raw)
    except ValueError:
        raise SecretDecryptError("payload bukan JSON") from None
    if (
        not isinstance(payload, dict)
        or payload.get("provider") != provider
        or payload.get("client_id") != client_id
    ):
        raise SecretDecryptError("payload bukan milik provider/scope ini")
    fields = payload.get("fields")
    if not isinstance(fields, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in fields.items()
    ):
        raise SecretDecryptError("bentuk payload tidak dikenal")
    return fields
