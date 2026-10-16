"""`effective_settings()` -- `get_settings()` + override key dari `runtime_secrets` (ROADMAP #23).

Kenapa ada lapis ini: `get_settings()` di-cache seumur proses, jadi ganti key selalu berarti edit
`.env` lalu restart api, worker, worker-browser, worker-nlp, dan beat. Konsumen key (Runner untuk
header scraper, `get_llm_client`, kirim Telegram, mailer Graph, provider IOC) sudah me-resolve key
SAAT DIPAKAI, bukan saat import, jadi cukup mereka memanggil `effective_settings()` alih-alih
`get_settings()` dan key baru berlaku di pemakaian berikutnya, tanpa restart.

Aturan yang tidak boleh dilanggar:
  - Tanpa master key (`secrets_encryption_keys` kosong) overlay TIDAK menyentuh DB dan mengembalikan
    objek `get_settings()` itu sendiri: perilaku persis seperti sebelum fitur ini.
  - TIDAK PERNAH raise ke konsumen, dan gangguan DB tidak boleh menghidupkan lagi key lama yang
    SUDAH dicabut. Gagal baca DB = tetap pakai override terakhir yang sehat (serve-stale) dan coba
    lagi `RETRY_SECONDS` kemudian; baru kalau belum pernah ada snapshot sehat (proses baru) jatuh ke
    `.env`. Pesan error yang dicatat hanya nama tipe exception: pesan SQLAlchemy/psycopg bisa memuat
    DSN beserta password DB.
  - Satu baris yang rusak (tidak bisa didekripsi, payload cacat) hanya melewati provider itu dan
    mempertahankan override lamanya kalau ada; provider lain tetap jalan. Override satu provider
    diterapkan UTUH dari satu blob terotentikasi, tidak pernah setengah.
  - Presedensi: DB > `.env`; field tanpa override jatuh ke `.env`.

Semua field override (secret DAN non-secret) datang dari payload terenkripsi, jadi tidak ada kolom
plaintext yang bisa dipakai penyerang dengan akses tulis DB untuk mengubah perilaku.

Cache per proses (Celery prefork = satu cache per anak): `TTL_SECONDS` kalau sukses,
`RETRY_SECONDS` kalau gagal. Pemanggil yang datang saat thread lain sedang me-refresh langsung
dapat snapshot lama, tidak menunggu; `invalidate()` tidak menunggu I/O (counter generasi: load yang
mulai sebelum invalidate tidak boleh mengisi ulang cache). Ini penting karena loader sync
(`sync_session()`) dipanggil juga dari event loop API: satu query kecil per `TTL_SECONDS`, bukan per
panggilan, dan thread lain tidak boleh ikut menunggu I/O DB.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

import structlog
from sqlalchemy.exc import SQLAlchemyError

from cti_core.config import Settings, get_settings
from cti_core.runtime_secrets import crypto
from cti_core.runtime_secrets.registry import PROVIDERS, scrub_values

if TYPE_CHECKING:
    from cti_core.db.models.runtime_secret import RuntimeSecret

log = structlog.get_logger(__name__)

TTL_SECONDS = 30.0
RETRY_SECONDS = 10.0
"""Jeda coba ulang sesudah gagal baca DB: cukup pendek supaya pulih cepat, cukup panjang supaya DB
yang sedang mati tidak dihujani query (dan event loop API tidak terus-terusan menunggu koneksi)."""

_clock = time.monotonic
"""Dipisah jadi atribut modul supaya tes bisa memajukan waktu tanpa tidur."""


@dataclass(frozen=True)
class OverlaySnapshot:
    overrides: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)
    """provider -> {nama field -> nilai}, sudah didekripsi. `repr=False`: nilainya secret, jangan
    sampai ikut tercetak di traceback/log debug."""
    errors: dict[str, str] = field(default_factory=dict)
    """provider (atau `"*"` kalau DB tidak terbaca) -> alasan singkat tanpa nilai secret."""


def _fetch_rows() -> list[RuntimeSecret]:
    """Seam buat tes. Import di dalam fungsi: modul ini diimpor dari mana-mana (alerts, scraper) dan
    tidak boleh menarik engine DB hanya karena di-import."""
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.runtime_secret import RuntimeSecretRepo

    with sync_session() as session:
        return RuntimeSecretRepo(session).list_platform()


def _log_load_failure(error: Exception) -> None:
    if isinstance(error, SQLAlchemyError | OSError):
        log.error("runtime_secrets_load_failed", error=type(error).__name__)
    else:
        # Bukan gangguan DB/jaringan (ImportError, AttributeError, ...) berarti bug kode: tanpa
        # traceback ia tampak seperti outage DB biasa dan tidak akan pernah ditemukan.
        log.error("runtime_secrets_load_failed", error=type(error).__name__, exc_info=True)


def load_snapshot(
    base: Settings | None = None, previous: OverlaySnapshot | None = None
) -> OverlaySnapshot:
    """Baca dan dekripsi override scope platform. Tanpa cache: itu urusan `effective_settings`.

    `previous` = snapshot sehat sebelumnya; dipertahankan untuk provider yang kali ini gagal dibaca.
    """
    keys = (base if base is not None else get_settings()).secrets_encryption_keys
    if not crypto.is_configured(keys):
        return OverlaySnapshot()
    kept = previous.overrides if previous is not None else {}
    try:
        rows = _fetch_rows()
    except Exception as e:
        _log_load_failure(e)
        return OverlaySnapshot(overrides=dict(kept), errors={"*": type(e).__name__})

    overrides: dict[str, dict[str, str]] = {}
    errors: dict[str, str] = {}
    for row in rows:
        provider = "?"
        try:
            provider = row.provider
            if row.client_id is not None or provider not in PROVIDERS:
                continue
            overrides[provider] = crypto.decrypt_fields(provider, bytes(row.secrets_enc), keys=keys)
        except crypto.SecretDecryptError:
            errors[provider] = "decrypt_failed"
            log.error("runtime_secret_decrypt_failed", provider=provider)
        except Exception as e:  # satu baris cacat tidak boleh menjatuhkan semua konsumen key
            errors[provider] = "invalid_row"
            log.error("runtime_secret_invalid_row", provider=provider, error=type(e).__name__)
    for provider in errors:
        if provider in kept:
            overrides[provider] = kept[provider]
    return OverlaySnapshot(overrides=overrides, errors=errors)


def apply_overrides(settings: Settings, overrides: Mapping[str, Mapping[str, Any]]) -> Settings:
    """`Settings` BARU dengan override terpasang; input tidak diubah.

    Nilai di-strip (salah tempel dengan spasi/newline = key tidak valid). Field SECRET yang kosong
    sesudah strip diabaikan: kosong berarti "tidak di-override", bukan "matikan provider", jadi key
    `.env` yang jalan tidak tertimpa blank. Field non-secret boleh kosong dan itu BERMAKNA ("pakai
    default vendor", mis. `llm.url=""` menimpa URL gateway di `.env`, supaya key vendor asli tidak
    terkirim ke gateway lama). Field ber-`choices` harus salah satu pilihan. Yang tidak dikenal
    (registry bisa berubah antar versi) atau bukan string dilewati dan dicatat tanpa nilainya."""
    updates: dict[str, Any] = {}
    for key, fields in overrides.items():
        provider = PROVIDERS.get(key)
        if provider is None:
            log.warning("runtime_secret_field_ignored", provider=key, field="*")
            continue
        specs = {f.name: f for f in provider.fields}
        group_update: dict[str, str] = {}
        for name, value in fields.items():
            spec = specs.get(name)
            if spec is None or not isinstance(value, str):
                log.warning("runtime_secret_field_ignored", provider=key, field=name)
                continue
            value = value.strip()
            if spec.choices:
                if value not in spec.choices:
                    log.warning("runtime_secret_field_ignored", provider=key, field=name)
                    continue
            elif spec.secret and not value:
                continue
            group_update[name] = value
        if group_update:
            updates[key] = getattr(settings, key).model_copy(update=group_update)
    return settings.model_copy(update=updates)


class _Entry(NamedTuple):
    key: tuple[str, str]
    snapshot: OverlaySnapshot
    expires_at: float


_state_lock = threading.Lock()
"""Melindungi `_entry`/`_derived`/`_generation`/`_refreshing`. TIDAK PERNAH dipegang saat I/O."""
_entry: _Entry | None = None
_generation = 0
_refreshing = 0
"""Jumlah loader yang sedang jalan (bukan boolean: dua loader cold bersamaan tidak boleh saling
menghapus penanda)."""
_derived: tuple[Settings, OverlaySnapshot, Settings] | None = None
"""(base, snapshot, hasil): hasil `apply_overrides` dipakai ulang selama base dan snapshot-nya sama
(identitas), supaya tiap panggilan tidak menyalin `Settings`."""


def invalidate() -> None:
    """Buang cache. Tidak menunggu loader yang sedang jalan; hasilnya dibuang lewat generasi."""
    global _entry, _derived, _generation
    with _state_lock:
        _generation += 1
        _entry = None
        _derived = None


def _current_snapshot(base: Settings) -> OverlaySnapshot:
    global _entry, _refreshing
    # Kunci cache ikut DB tujuan, bukan cuma master key: tes (dan failover ke DB lain) yang
    # mengganti `database.sync_url` dengan master key yang sama tidak boleh memakai snapshot DB
    # sebelumnya.
    key = (base.secrets_encryption_keys, base.database.sync_url)
    with _state_lock:
        entry = _entry
        previous: OverlaySnapshot | None = None
        if entry is not None and entry.key == key:
            if _clock() < entry.expires_at or _refreshing > 0:
                return (
                    entry.snapshot
                )  # masih segar, atau thread lain sedang me-refresh: jangan tunggu
            previous = entry.snapshot
        generation = _generation
        _refreshing += 1
    try:
        snapshot = load_snapshot(base, previous)
    finally:
        with _state_lock:
            _refreshing -= 1
    ttl = RETRY_SECONDS if "*" in snapshot.errors else TTL_SECONDS
    with _state_lock:
        if generation == _generation:
            _entry = _Entry(key, snapshot, _clock() + ttl)
    before = sorted(previous.overrides) if previous is not None else []
    after = sorted(snapshot.overrides)
    if before != after:
        log.info("runtime_secrets_active", providers=after)
    return snapshot


def effective_settings() -> Settings:
    """Pengganti `get_settings()` buat konsumen key third-party. Jangan disimpan lama-lama (di
    atribut kelas/modul): nilainya sengaja berubah begitu override berubah."""
    global _derived
    base = get_settings()
    snapshot = _current_snapshot(base)
    if not snapshot.overrides:
        return base
    cached = _derived
    if cached is not None and cached[0] is base and cached[1] is snapshot:
        return cached[2]
    result = apply_overrides(base, snapshot.overrides)
    _derived = (base, snapshot, result)
    return result


def scrub_candidates() -> list[str]:
    """Nilai secret yang harus disamarkan dari teks error: gabungan `.env` (base) DAN override DB.

    Dua-duanya perlu: setelah key dirotasi lewat UI, error dari panggilan yang sudah berjalan atau
    dari vendor yang masih mengenali key lama dapat memuat nilai `.env` yang lama, sedangkan error
    baru memuat nilai override. Urut dari yang terpanjang: kalau satu secret prefiks secret lain,
    `replace` yang pendek lebih dulu akan meninggalkan ekor yang panjang. TIDAK PERNAH raise: jalur
    error (`rejected_articles`, log) tidak boleh gagal gara-gara penyamaran."""
    try:
        values = set(scrub_values(get_settings()))
    except Exception:
        return []
    try:
        values.update(scrub_values(effective_settings()))
    except Exception:
        log.warning("runtime_secrets_scrub_overlay_failed")
    return sorted(values, key=lambda v: (-len(v), v))
