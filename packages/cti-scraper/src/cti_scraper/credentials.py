"""Resolusi kredensial buat scraper yang butuh API key (GitHub, NVD,
Twitter/twitterapi.io, X resmi). `fetch()` scraper SENGAJA gak pernah pegang objek
ini langsung (lihat docstring `ScrapeContext` di base.py) -- cuma dipanggil
dari `Runner`/`_record_baseline` (CLI `verify --record`), yang keduanya
udah punya akses `cti_core.config` buat bikin `ScraperHttpClient` SEBELUM
diserahin ke scraper lewat `ctx.http`. Header auth udah nempel di situ;
scraper cuma manggil `ctx.http.get(url)` biasa.

Header per-API DISENGAJAKAN beda-beda cara (bukan satu skema generik) --
itu emang gimana masing-masing API-nya kerja, ngikutin apa yang kebukti
jalan di script lama (lihat grep lintas scraper GitHub: campuran
"Authorization: token X" / "Authorization: Bearer X" -- distandarin ke
Bearer, GitHub nerima dua-duanya). NVD: header lama sama sekali GAK PERNAH
makai `apiKey` (bug lama, gak pernah otentikasi) -- sekarang dipasang
bener, benefit langsung naik dari rate limit publik 5/30dtk ke 50/30dtk.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from cti_scraper.base import ConfigError

if TYPE_CHECKING:
    from cti_core.config import Settings

_Resolver = Callable[["Settings"], "dict[str, str] | None"]

_CREDENTIAL_RESOLVERS: dict[str, _Resolver] = {
    "github": lambda s: {"Authorization": f"Bearer {s.github.token}"} if s.github.token else None,
    "nvd": lambda s: {"apiKey": s.nvd.api_key} if s.nvd.api_key else None,
    "twitter": lambda s: {"X-API-Key": s.twitter.api_key} if s.twitter.api_key else None,
    # API resmi X (pay-per-use). Beda dari "twitter" (= twitterapi.io): header dan host lain.
    "x": lambda s: {"Authorization": f"Bearer {s.x.bearer_token}"} if s.x.bearer_token else None,
}


def resolve_credential_headers(name: str, *, settings: Settings | None = None) -> dict[str, str]:
    """`name` -> header dict siap pasang ke `ScraperHttpClient(default_headers=...)`.
    Raise `ConfigError` (bukan diam-diam kirim request tanpa auth) kalau
    nama gak dikenal atau secret-nya kosong (di `.env` DAN di override halaman admin) -- gagal pas
    start run, bukan 401 yang membingungkan di tengah fetch.

    `settings`: buat testing doang -- `get_settings()` di-cache lintas
    proses (lihat docstring-nya), jadi test yang mau env beda-beda harus
    suntik `Settings` sendiri lewat sini, bukan mutate cache global."""
    resolver = _CREDENTIAL_RESOLVERS.get(name)
    if resolver is None:
        raise ConfigError(
            f"credential '{name}' gak dikenal -- pilihan yang ada: {sorted(_CREDENTIAL_RESOLVERS)}"
        )

    if settings is None:
        from cti_core.runtime_secrets.overlay import effective_settings

        settings = effective_settings()

    headers = resolver(settings)
    if headers is None:
        raise ConfigError(
            f"credential '{name}' butuh secret yang masih kosong di .env dan di override halaman "
            "admin (lihat .env.example; kalau seharusnya terisi dari halaman admin, cek log "
            "runtime_secrets_*)"
        )
    return headers
