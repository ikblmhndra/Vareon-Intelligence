"""Bahan bersama tes runtime secrets (ROADMAP #23): `Settings` palsu yang SEMUA key-nya terisi,
baris DB palsu, dan pemasang overlay (monkeypatch `get_settings` + `_fetch_rows`).

Import modul `runtime_secrets` di sini SENGAJA lazy (di dalam fungsi): tes registry/crypto tidak
boleh ikut gagal-import cuma gara-gara modul overlay belum ada.

Semua nilai di sini PALSU (`gitleaks:allow`), unik per field supaya tes bisa tahu persis nilai
MANA yang bocor atau tertimpa, dan panjangnya >= 6 (batas `MIN_SCRUB_LEN`) kecuali disebut lain.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet
from cti_core.config import Settings

# Kunci master Fernet palsu, dibangkitkan tiap proses (bukan literal, biar tidak mirip secret
# di git).
KEYS = Fernet.generate_key().decode()
OTHER_KEYS = Fernet.generate_key().decode()

JWT_SECRET = "jwt-env-aaaaaa"  # gitleaks:allow

# (provider, field) -> nilai di `.env` palsu. HANYA field secret; urutannya = urutan registry.
ENV_VALUES: dict[tuple[str, str], str] = {
    ("llm", "api_key"): "sk-env-llm-aaaaaa",  # gitleaks:allow
    ("telegram", "bot_token"): "111:env-telegram-aaaaaa",  # gitleaks:allow
    ("graph", "client_secret"): "env-graph-aaaaaa",  # gitleaks:allow
    ("nvd", "api_key"): "env-nvd-aaaaaa",  # gitleaks:allow
    ("github", "token"): "ghp-env-aaaaaa",  # gitleaks:allow
    ("twitter", "api_key"): "env-twitter-aaaaaa",  # gitleaks:allow
    ("x", "bearer_token"): "env-x-bearer-aaaaaa",  # gitleaks:allow
    ("otx", "api_key"): "env-otx-aaaaaa",  # gitleaks:allow
    ("abuseipdb", "api_key"): "env-abuseipdb-aaaaaa",  # gitleaks:allow
    ("virustotal", "api_key"): "env-virustotal-aaaaaa",  # gitleaks:allow
}

# Field NON-secret yang sengaja diisi cukup panjang: tes scrub harus bisa bilang "ini TIDAK ikut".
NON_SECRET_VALUES = {
    "llm_model": "env-model-aaaaaa",
    "llm_url": "http://gw.env.example/v1",
    "telegram_chat_id": "-1001234567",
    "graph_tenant_id": "tenant-env-aaaaaa",
    "graph_client_id": "graph-client-aaaaaa",
    "graph_sender": "cti@env.example",
}


def _group(provider: str, /, **extra: Any) -> Any:
    """Grup settings (`LlmSettings`, `NvdSettings`, ...) berisi nilai secret dari `ENV_VALUES`."""
    fields = {f: v for (p, f), v in ENV_VALUES.items() if p == provider}
    group_cls = Settings.model_fields[provider].annotation
    assert group_cls is not None
    return group_cls(**{**fields, **extra})


def make_settings(*, keys: str = "", **over: Any) -> Settings:
    """`Settings` tes dengan semua key terisi (`ENV_VALUES`). `keys` = `secrets_encryption_keys`
    (kosong = overlay tidak terkonfigurasi, persis perilaku produksi tanpa kunci master).
    `over`: ganti grup/field top-level, mis. `github=GithubSettings(token="")`."""
    base: dict[str, Any] = {
        "database": {
            "url": "postgresql+asyncpg://x:x@h/x",
            "sync_url": "postgresql+psycopg://x:x@h/x",
        },
        "auth": {"jwt_secret": JWT_SECRET, "session_secret_key": "s"},
        "llm": _group(
            "llm",
            provider="openai",
            model=NON_SECRET_VALUES["llm_model"],
            url="",
        ),
        "telegram": _group(
            "telegram",
            chat_id=NON_SECRET_VALUES["telegram_chat_id"],
            thread_ids={"global": 7},
        ),
        "graph": _group(
            "graph",
            tenant_id=NON_SECRET_VALUES["graph_tenant_id"],
            client_id=NON_SECRET_VALUES["graph_client_id"],
            sender=NON_SECRET_VALUES["graph_sender"],
        ),
        "nvd": _group("nvd"),
        "github": _group("github"),
        "twitter": _group("twitter"),
        "x": _group("x"),
        "otx": _group("otx"),
        "abuseipdb": _group("abuseipdb"),
        "virustotal": _group("virustotal"),
    }
    if keys:
        base["secrets_encryption_keys"] = keys
    return Settings(_env_file=None, **{**base, **over})  # type: ignore[call-arg]


def make_row(
    provider: str,
    fields: dict[str, str] | None = None,
    *,
    client_id: str | None = None,
    keys: str = KEYS,
    secrets_enc: bytes | None = None,
) -> Any:
    """Baris `RuntimeSecret` palsu: cukup 3 atribut yang dibaca overlay (`provider`, `client_id`,
    `secrets_enc`). SEMUA field override (secret DAN non-secret) ada di payload terenkripsi, jadi
    `fields` dienkripsi apa adanya dengan `keys`, terikat ke `provider` dan `client_id`.
    `secrets_enc` mentah menimpa hasil enkripsi (buat token rusak atau salah ikat)."""
    from cti_core.runtime_secrets import crypto

    enc = secrets_enc
    if enc is None:
        enc = crypto.encrypt_fields(provider, fields or {}, client_id=client_id, keys=keys)
    return SimpleNamespace(provider=provider, client_id=client_id, secrets_enc=enc)


class FetchSpy:
    """Pengganti `overlay._fetch_rows`: hitung pemanggilan; `rows` boleh diganti antar panggilan
    dan `error` (kalau diisi) di-raise di setiap panggilan, jadi DB bisa "mati" lalu "hidup"."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows: list[Any] = rows or []
        self.error: BaseException | None = None
        self.calls = 0

    def __call__(self) -> list[Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.rows)


def install_overlay(
    monkeypatch: pytest.MonkeyPatch, base: Settings, rows: list[Any] | None = None
) -> FetchSpy:
    """Arahkan overlay ke `base` (pengganti `get_settings()`) dan ke baris palsu (pengganti DB).
    Tes yang memakai ini harus punya fixture autouse yang memanggil `overlay.invalidate()`."""
    from cti_core.runtime_secrets import overlay

    spy = FetchSpy(rows)
    monkeypatch.setattr(overlay, "get_settings", lambda: base)
    monkeypatch.setattr(overlay, "_fetch_rows", spy)
    return spy
