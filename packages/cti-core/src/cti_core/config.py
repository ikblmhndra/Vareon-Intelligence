"""Satu sumber config buat seluruh platform. Lihat .env.example di root repo
untuk daftar lengkap key -- file ini HARUS tetap sinkron 1:1 sama file itu;
kalau nambah field di sini, `.env.example` ikut di-update di commit yang sama.

Kenapa `extra="forbid"`: env var yang salah ketik (mis. TELEGRAM__BOTTOKEN)
harus bikin container GAGAL START, bukan diam-diam mati kayak yang kejadian
di app lama (lihat plan §7.1). Pydantic-settings ngasih ini gratis lewat
validasi schema -- gak perlu manual RuntimeError check kayak
`ScraperNewsWeb/app/main.py` lakuin buat SESSION_SECRET_KEY/JWT_SECRET.

Skema secret sekarang vs nanti (docs/SECRETS_ROTATION.md):
  SECRETS_BACKEND=env   (default, sekarang) -- .env satu-satunya sumber.
  SECRETS_BACKEND=vault (produksi)          -- integrasi baca Vault BELUM
                                               diimplementasikan di sini,
                                               disengaja (dikerjain di fase
                                               testing). `vault_token` cuma
                                               divalidasi WAJIB ADA kalau
                                               backend ini dipilih, gak lebih.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class _StrictModel(BaseModel):
    """Base buat semua grup settings nested.

    `extra="forbid"` di `Settings` (BaseSettings) TIDAK otomatis nurun ke
    model nested biasa -- kebukti waktu testing: `TELEGRAM__BOTTOKEN` (typo)
    kepetakan ke field `telegram` yang valid, terus sub-key `bottoken`-nya
    diam-diam ke-drop sama `TelegramSettings` karena BaseModel polos default
    permisif. Persis mode kegagalan "salah ketik = diam-diam mati" yang mau
    dicegah field ini. Tiap grup nested WAJIB inherit dari sini, bukan
    BaseModel langsung.
    """

    model_config = ConfigDict(extra="forbid")


class DatabaseSettings(_StrictModel):
    url: str
    """postgresql+asyncpg://... -- dipakai FastAPI (async session)."""
    sync_url: str
    """postgresql+psycopg://... -- dipakai Celery/CLI (sync session).
    Sama database, driver beda; lihat db/engine.py buat alasannya."""
    pool_size: int = 20
    max_overflow: int = 10


class RedisSettings(_StrictModel):
    url: str = "redis://localhost:6379/0"


class AuthSettings(_StrictModel):
    jwt_secret: str
    """WAJIB ADA, gak ada default. Kosong di .env = container gagal start
    saat Settings() dibikin -- pengganti RuntimeError manual di app lama."""
    jwt_algorithm: str = "HS256"
    jwt_expire_min: int = 480
    session_secret_key: str
    """WAJIB ADA, alasan sama kayak jwt_secret."""


class OidcSettings(_StrictModel):
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    discovery_url: str = ""
    redirect_uri: str = ""


class LlmSettings(_StrictModel):
    provider: Literal["openai", "deepseek", "gemini"] = "openai"
    api_key: str = ""
    url: str = ""
    """Override `base_url` client OpenAI-compatible -- kosong = endpoint
    default provider. Dipakai dev buat nunjuk ke gateway lokal (mis. 9router)
    alih-alih API provider asli."""
    model: str = "gpt-4o"
    timeout_s: float = 60.0
    max_retries: int = 2
    rate_limit: str = "60/minute"
    """Throttle spend global lewat token bucket Redis -- sengaja belum ada
    di app lama (lihat plan §6.4: LLM client web gak punya timeout sama
    sekali, ini yang bikin field ini ada)."""


class TelegramSettings(_StrictModel):
    bot_token: str = ""
    chat_id: str = ""
    thread_ids: dict[str, int] = Field(default_factory=dict)
    """Satu dict, bukan 17 field thread_id_* terpisah kayak config.yml lama.
    Menggantikan 14 fungsi send_alert_* yang masing-masing hardcode satu
    thread (lihat plan §6.5)."""


class GraphSettings(_StrictModel):
    """Microsoft Graph -- pengiriman email CVE notification."""

    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    sender: str = ""
    cc: str = ""
    """Dulunya hardcoded di ScraperNewsWeb/app/config.py:59-60."""


class NvdSettings(_StrictModel):
    api_key: str = ""


class GithubSettings(_StrictModel):
    token: str = ""


class TwitterSettings(_StrictModel):
    """twitterapi.io (sumber Twitter DEFAULT) -- BUKAN API resmi X, lihat `XSettings`."""

    api_key: str = ""


class XSettings(_StrictModel):
    """API resmi X (pay-per-use, https://api.x.com) -- sumber Twitter ALTERNATIF yang
    dipilih per-scraper lewat opsi `provider` di control plane.

    Cuma bearer token (app-only) yang dipakai: baca/search tidak butuh yang lain.
    Consumer key/secret dan access token/secret cuma perlu buat POSTING atau endpoint
    user-context, dan platform ini tidak posting -- sengaja tidak ada field-nya di sini
    (least privilege; kalau salah satu tertempel di env, `extra="forbid"` bikin
    container gagal start, bukan diam-diam terbaca).

    Env: `X__BEARER_TOKEN` (SATU underscore antara BEARER dan TOKEN -- `__` itu
    pemisah nesting, `X__BEARER__TOKEN` dibaca sebagai `x.bearer.token`)."""

    bearer_token: str = ""


class OtxSettings(_StrictModel):
    api_key: str = ""


class ScraperSettings(_StrictModel):
    default_rate_limit: str = "20/minute"
    default_timeout_s: float = 30.0
    dedup_ttl_days: int = 180
    cold_start_max_items: int = 5
    """Run "cold" scraper (nol baris `scraper_seen`) cuma enrich segini item
    TERBARU, sisanya ditandai seen tanpa diproses (`Runner._cold_start_cap`,
    Fase 10). Tanpa ini, DB kosong + ~91 scraper aktif = seluruh isi feed
    masuk sekaligus di hari pertama (lihat plan, konsekuensi "Postgres + DB
    kosong"). Jaring pengaman: jalur cutover utama = warm start (seed
    `scraper_seen` dari dump lama), jadi cap ini cuma kena scraper baru atau
    yang habis `reset-dedup`. `<= 0` = guard dimatiin."""
    enrich_queue_max_depth: int = 2000
    """Guard backpressure -- scraper bisa jauh lebih cepat dari enrichment
    (spaCy/LLM). Lihat plan §4.7."""


class CveMirrorSettings(_StrictModel):
    """Ingest mirror CVE dari CVE List V5 (ROADMAP #19, `cti_core.cve_mirror_sync`)."""

    enabled: bool = False
    """MATI secara default: tugas `cve.mirror_sync`/`cve.mirror_purge` tetap terjadwal tapi langsung
    kembali. Dinyalakan dulu di dev (mode bayangan, `docs/CVE_CATALOG_DESIGN.md` 8); ganti nilai
    butuh restart worker (env dibaca sekali per proses)."""
    max_files_per_run: int = 3000
    """Batas unduhan record per siklus (kelebihan dibawa ke siklus berikut lewat state). Hari
    biasa ratusan sampai ~2.000 berkas; catch-up setelah mati lama bisa lebih besar."""
    request_timeout_s: float = 30.0
    """Timeout satu unduhan; `deltaLog.json` (24 MB) memakai tiga kali lipat nilai ini."""


class WorkerSettings(_StrictModel):
    """Interval buat 2 dari 5 loop Celery beat (Fase 7.8) yang nentuin
    LOGIKA task, bukan cuma jadwal cron-nya -- IOC decay/daily recap/CVE
    enrichment jam tetap (04:00/06:00/tiap 3 jam UTC, port apa adanya dari
    `_seconds_until_04h_utc()` dkk lama) di-hardcode langsung di `beat.py`,
    gak butuh entri di sini."""

    pir_p1_alert_interval_min: int = 5
    """Port `PIR_P1_INTERVAL_MIN` lama -- P1 dicek tiap segini menit."""
    pir_alert_interval_min: int = 15
    """Port `PIR_ALERT_INTERVAL_MIN` lama -- P2+ dicek tiap segini menit."""
    attack_sync_interval_days: int = 7
    """Port `ATTACK_SYNC_INTERVAL_DAYS` lama -- re-sync kalau domain
    manapun belum pernah sync ATAU sync terlama udah lebih dari ini."""
    scraper_item_retention_days: int = 30
    """Fase 9 -- umur baris `scraper_items` (log accept/reject per artikel,
    84 scraper) sebelum kena purge periodik. Gak ada padanan lama (tabel
    ini gak pernah ada di skema Mongo)."""
    scraper_health_sweep_interval_min: int = 30
    """Fase 9 -- tiap berapa menit `scraper.health_digest` jalan (hitung
    ulang status SEMUA scraper, kirim SATU digest Telegram kalau ada yang
    non-`ok`). Gak ada padanan lama."""
    report_utc_offset_hours: int = 7
    """Fase 10.E -- zona waktu laporan periodik (jam UTC+N; 7 = WIB). Job Rundeck
    lama jalan di jam LOKAL server ("23:55", "07:00"), sedangkan beat berjalan
    UTC: offset ini dipakai untuk (1) menerjemahkan jam laporan ke cron UTC dan
    (2) menentukan batas "hari ini" (counter harian, berita hari ini). Set 0 kalau
    server produksi lama ternyata berjalan di UTC."""
    news_of_the_day_max_titles: int = 400
    """Fase 10.E -- batas judul yang dikirim ke LLM per kategori per hari."""
    logbook_interval_days: int = 14
    logbook_preparer_name: str = "Dyah Retno Palupi"
    logbook_preparer_title: str = "Threat Intel"
    logbook_approver_name: str = "Ikbal Mahendra"
    logbook_approver_title: str = "Infrastructure Security, Lead"
    """Fase 10.E -- kolom tanda tangan logbook (hardcoded di `logbook.py` lama)."""
    beat_lock_ttl_s: int = 30
    """Fase 10.1d -- umur lock singleton beat (`cti_worker.beat_main`).
    Leader memperpanjangnya tiap `ttl/3` detik; leader mati/macet = standby
    ambil alih paling lama segini detik. Jangan terlalu kecil (GC pause /
    Redis lambat bikin lock lepas terus leader ke-kill), jangan terlalu
    gede (failover lama)."""
    beat_heartbeat_stale_s: int = 300
    """QA BUG-D2/D8 -- heartbeat beat (`cti_core.beat_heartbeat`) dianggap
    BASI kalau tick terakhir lebih tua dari ini. Beat nge-tick minimal tiap
    `beat_max_interval` (60 dtk, `celery_app.py`), jadi 300 = lima tick
    kelewat berturut-turut, bukan satu tick yang telat."""
    beat_watchdog_interval_s: int = 60
    """Tiap berapa detik watchdog di proses WORKER (bukan beat -- itu
    intinya) ngecek heartbeat. Lihat `cti_worker.beat_watchdog`."""
    beat_stale_alert_repeat_min: int = 60
    """Alert Telegram "scheduler mati" diulang paling sering segini menit
    selama beat masih basi (dedupe lintas container worker lewat Redis)."""
    beat_catchup_grace_s: int = 600
    """QA BUG-D7 -- pas beat start, jadwal yang slot terakhirnya terlewat
    LEBIH LAMA dari ini TIDAK di-catch-up (dilompatin ke slot berikutnya).
    Tanpa ini `PersistentScheduler` nembak SEMUA entri yang `last_run_at`-nya
    basi sekaligus -- di staging 09-30: 94 scraper + laporan MINGGUAN
    (`report-weekly-*`) jalan hari Rabu. Restart singkat (deploy) tetap
    di-catch-up selama slot yang kelewat masih dalam jendela ini."""


DEFAULT_PLATFORM_NAME = "Vareon Intelligence"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="forbid",
        case_sensitive=False,
    )

    service_name: str = "cti"
    # Nama TAMPILAN (UI/email/STIX); identifier teknis `cti-*` sengaja tetap.
    platform_name: str = DEFAULT_PLATFORM_NAME
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    secrets_backend: Literal["env", "vault"] = "env"
    vault_addr: str = "http://vault:8200"
    vault_token: str = ""

    database: DatabaseSettings
    redis: RedisSettings = Field(default_factory=RedisSettings)
    auth: AuthSettings
    oidc: OidcSettings = Field(default_factory=OidcSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    nvd: NvdSettings = Field(default_factory=NvdSettings)
    github: GithubSettings = Field(default_factory=GithubSettings)
    twitter: TwitterSettings = Field(default_factory=TwitterSettings)
    x: XSettings = Field(default_factory=XSettings)
    otx: OtxSettings = Field(default_factory=OtxSettings)
    scraper: ScraperSettings = Field(default_factory=ScraperSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    cve_mirror: CveMirrorSettings = Field(default_factory=CveMirrorSettings)

    cors_origins: str = "http://localhost:3000"
    api_base_url: str = "http://api:8000"

    @model_validator(mode="after")
    def _vault_token_required_when_selected(self) -> Settings:
        if self.secrets_backend == "vault" and not self.vault_token:
            raise ValueError(
                "SECRETS_BACKEND=vault tapi VAULT_TOKEN kosong. "
                "cti_core belum baca secret lain dari Vault (disengaja, "
                "lihat docs/SECRETS_ROTATION.md) -- tapi kalau backend ini "
                "dipilih, token minimal harus ada."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Satu instance per proses. Testing: pakai `Settings(_env_file=None, **overrides)`
    langsung, jangan panggil fungsi ini (cache-nya lintas-test kalau dipanggil)."""
    return Settings()  # type: ignore[call-arg]  # nilai datang dari env/.env


def platform_name() -> str:
    """Nama tampilan platform. Settings lengkap (DB/auth) tidak selalu ada di
    konteks render murni (unit test, tooling), jadi jatuh ke default."""
    try:
        return get_settings().platform_name
    except ValidationError:
        return DEFAULT_PLATFORM_NAME
