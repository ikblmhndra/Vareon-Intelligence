"""Daftar provider dan field yang boleh di-override dari UI admin (ROADMAP #23).

`SecretProvider.key` SAMA dengan nama atribut di `Settings` (`settings.llm`, `settings.otx`, ...)
dan `SecretField.name` sama dengan nama field di model grupnya, jadi overlay cukup
`model_copy(update=...)` tanpa tabel pemetaan lain. `tests/unit/test_runtime_secrets_registry.py`
mengunci kesamaan itu.

Yang SENGAJA tidak ada di sini: chat/thread id Telegram, identitas Graph (tenant, client, sender,
cc), rate dan timeout. Itu keputusan deploy atau berubah sebagai satu paket; rotasi key tidak
menyentuhnya, jadi tetap di `.env`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cti_core.config import Settings

MIN_SCRUB_LEN = 6
"""Secret lebih pendek dari ini tidak ikut disamarkan: nilai sependek itu (mis. "abc") bakal
merusak teks biasa kalau di-`replace`."""


class UnknownProvider(KeyError):
    """`key` yang diminta bukan provider terdaftar."""


@dataclass(frozen=True)
class SecretField:
    name: str
    secret: bool
    choices: tuple[str, ...] = ()
    """Tidak kosong = enum: hanya nilai ini yang diterima overlay."""


@dataclass(frozen=True)
class SecretProvider:
    key: str
    label: str
    fields: tuple[SecretField, ...]


def _provider(key: str, label: str, *fields: SecretField) -> tuple[str, SecretProvider]:
    return key, SecretProvider(key=key, label=label, fields=fields)


PROVIDERS: dict[str, SecretProvider] = dict(
    [
        _provider(
            "llm",
            "LLM",
            SecretField("api_key", secret=True),
            # Ganti vendor = ganti provider+model+key sebagai satu paket, jadi ketiganya boleh
            # di-override bareng; `url` (gateway custom) dijaga ketat di sisi API (PR 2).
            SecretField("provider", secret=False, choices=("openai", "deepseek", "gemini")),
            SecretField("model", secret=False),
            SecretField("url", secret=False),
        ),
        _provider("telegram", "Telegram", SecretField("bot_token", secret=True)),
        _provider("graph", "Microsoft Graph", SecretField("client_secret", secret=True)),
        _provider("nvd", "NVD", SecretField("api_key", secret=True)),
        _provider("github", "GitHub", SecretField("token", secret=True)),
        _provider("twitter", "twitterapi.io", SecretField("api_key", secret=True)),
        _provider("x", "X (API resmi)", SecretField("bearer_token", secret=True)),
        _provider("otx", "AlienVault OTX", SecretField("api_key", secret=True)),
        _provider("abuseipdb", "AbuseIPDB", SecretField("api_key", secret=True)),
        _provider("virustotal", "VirusTotal", SecretField("api_key", secret=True)),
    ]
)


def get_provider(key: str) -> SecretProvider:
    try:
        return PROVIDERS[key]
    except KeyError:
        raise UnknownProvider(key) from None


def secret_field_names(key: str) -> frozenset[str]:
    return frozenset(f.name for f in get_provider(key).fields if f.secret)


def scrub_values(settings: Settings) -> list[str]:
    """Semua nilai secret yang SEDANG terisi (>= `MIN_SCRUB_LEN`), buat disamarkan dari teks error
    sebelum masuk DB/log/UI: provider kadang ngecho (sebagian) key di pesan errornya.

    Satu daftar buat semua pemanggil, diturunkan dari registry, jadi provider baru otomatis ikut
    tersamarkan (daftar tulisan tangan sebelumnya lupa `x`, `otx`, `abuseipdb` dan `virustotal`).
    `auth.jwt_secret` ikut walau bukan provider: ia memang ada di daftar scrub sejak awal. Master
    key enkripsi juga ikut: ia tidak boleh muncul di teks mana pun."""
    values: list[str] = []
    for key, provider in PROVIDERS.items():
        group = getattr(settings, key)
        values.extend(getattr(group, f.name) for f in provider.fields if f.secret)
    values.append(settings.auth.jwt_secret)
    values.extend(k.strip() for k in settings.secrets_encryption_keys.split(","))
    return [v for v in values if isinstance(v, str) and len(v) >= MIN_SCRUB_LEN]
