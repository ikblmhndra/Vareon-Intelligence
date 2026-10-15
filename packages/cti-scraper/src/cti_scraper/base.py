"""Kontrak inti scraper. Lihat docs/ADDING_A_SCRAPER.md buat cara pakai
dari sudut pandang orang yang nambah scraper -- dokumen ini fokus KENAPA
bentuknya begini.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    from playwright.sync_api import Page

import structlog

from cti_scraper.http import DEFAULT_USER_AGENT, ScraperHttpClient
from cti_scraper.items import Item

Runtime = Literal["light", "browser"]


def _utcnow_naive() -> datetime:
    """Pengganti `datetime.utcnow()` (deprecated sejak 3.12 -- di test jadi
    ERROR lewat `filterwarnings` pyproject, dan baru ketauan Fase 10 karena
    sebelumnya gak ada test yang lewat `Runner` asli). Nilainya SAMA persis:
    UTC NAIVE, bukan aware -- sebagian scraper bergantung ke naive-nya
    (lihat komentar di `feeds/unit42_github.py`)."""
    return datetime.now(UTC).replace(tzinfo=None)


class ConfigError(Exception):
    """Kesalahan SETUP (runtime mismatch, dependency belum ke-install) --
    beda dari `cti_scraper.errors.ScraperError` yang soal hasil fetch. Ini
    harus keliatan pas dev/CI, bukan diam-diam gagal di produksi."""


@dataclass(frozen=True, slots=True)
class OptionChoice:
    """Satu pilihan di `ScraperOption`."""

    value: str
    label: str
    credential: str | None = None
    """Kredensial yang dipasang `Runner` KALAU pilihan ini aktif (menggantikan
    `ScraperMeta.credential`). `None` = pakai `ScraperMeta.credential` apa adanya."""


@dataclass(frozen=True, slots=True)
class ScraperOption:
    """Pilihan yang boleh diubah admin dari control plane TANPA deploy (mis. sumber data
    Twitter: twitterapi.io vs API resmi X). Disimpan di `ScraperConfig.options`
    (`{key: value}`), dibaca `Runner` tiap run, dan sampai ke `fetch()` lewat
    `ctx.options`. Sengaja HANYA tipe pilihan-tertutup (`choices`): nilai bebas dari UI
    bisa berisi apa saja, pilihan tertutup bisa divalidasi penuh di API.

    Kode scraper selalu jalan dengan `default` kalau admin tidak memilih apa-apa -- opsi
    yang tidak pernah disentuh tidak mengubah perilaku."""

    key: str
    label: str
    choices: tuple[OptionChoice, ...]
    default: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class ScraperMeta:
    """Semua yang platform butuh tau soal scraper TANPA nge-jalanin dia.
    Dibaca beat (jadwal), router Celery (runtime -> queue), control plane
    API (semuanya), dan contract test CI (validasi)."""

    id: str
    """Slug stabil. Namespace dedup DAN key control plane. JANGAN PERNAH
    diubah setelah deploy pertama -- itu ngereset seluruh dedup state
    scraper ini, dan dia bakal nge-yield ulang semua yang kelihatan
    sekarang."""

    source: str
    """Nama tampilan, mis. "GBHackers". Ditulis ke Article.source."""

    schedule: str
    """Ekspresi cron. Buat family declarative (RssScraper dkk) pakai
    `cti_scraper.schedule.spread()` biar N scraper gak nembak bareng di
    tick yang sama -- lihat modul itu."""

    runtime: Runtime = "light"
    """'light' -> httpx/lxml, gak butuh Chromium. 'browser' -> Playwright,
    dibutuhin `ctx.page()`. Nentuin image mana yang nyalain scraper ini
    (Fase 9) dan queue Celery mana (Fase 6) -- BUKAN preferensi kosmetik."""

    rate_limit: str = "20/minute"
    """Token-bucket budget. Di-key per DOMAIN registrable, bukan per
    scraper -- dua scraper yang mukul host sama berbagi budget yang sama."""

    timeout_s: float = 30.0
    max_retries: int = 3
    """Retry cuma buat TransientFetchError. ParseError TIDAK PERNAH
    di-retry -- itu artinya situs berubah, bukan blip jaringan."""

    dedup_ttl_days: int = 180
    max_items: int = 50
    """Batas keras per run. Parser yang tiba-tiba nge-yield 10rb item
    (bug, atau situsnya berubah format) gak boleh bisa banjirin queue
    enrichment."""

    enabled: bool = True
    """Default waktu compile. `scraper_config` di DB (control plane,
    Fase 9) nge-override runtime, bukan field ini."""

    credential: str | None = None
    """Nama kredensial yang mau di-suntik `Runner`/`verify --record` ke
    `ctx.http` sebagai default header SEBELUM `fetch()` dipanggil --
    "github"/"nvd"/"twitter" (lihat `cti_scraper.credentials`). `fetch()`
    gak pernah manggil ini atau lihat token mentahnya sendiri; cukup
    `ctx.http.get(url)` biasa, header auth udah nempel. `None` (default) =
    scraper publik, gak butuh apa-apa."""

    options: tuple[ScraperOption, ...] = ()
    """Pilihan yang bisa diubah dari control plane (lihat `ScraperOption`). `()` =
    tidak ada -- mayoritas scraper. Nilai efektif: `cti_scraper.options.resolve_options()`."""

    reference_data: tuple[str, ...] = ()
    """Nama dataset internal (Postgres KITA, bukan sumber eksternal) yang
    `fetch()` butuh baca -- mis. "techstack", "true_positive_cves". Sama
    filosofi kayak `credential`: `Runner` yang query DB SEBELUM manggil
    `fetch()` (lihat `cti_scraper.reference_data`), hasilnya data BIASA
    (list/dict) nempel di `ctx.reference[nama]`. `fetch()` gak pernah
    pegang `Session`/koneksi DB sendiri -- itu kelas bug yang sama kayak
    `newCveThreat.py`/`githubPOCMonitor.py` lama (`MongoClient` langsung
    dari config di tengah script), cuma versi Postgres-nya. `()` (default)
    = scraper gak butuh apa-apa selain sumber eksternalnya sendiri."""

    tags: tuple[str, ...] = ()

    legacy_label: str | None = None
    """Label `push_job` lama, mis. "NEW ARTICLE FROM GBHACKER" -- kompat
    mundur `scraper_health_service` selama migrasi. Hapus 1 rilis setelah
    cutover, lihat plan §8.5."""

    legacy_script: str | None = None
    """Nama file lama, mis. "gbHackerThreat" -- dipakai migrasi
    `threatintel.offsets` doang, gak dipakai runtime."""

    notes: str = ""


@dataclass
class ScrapeContext:
    """Semua yang `fetch()` boleh pegang. SENGAJA gak ada akses LANGSUNG ke
    Mongo/Postgres/Telegram/kredensial mentah di sini -- itu pagar
    keamanan, bukan gaya nulis kode. Waktu ngerekam fixture Fase 0, dua
    scraper lama (`newCveThreat.py`, `githubPOCMonitor.py`) kebukti bikin
    MongoClient LANGSUNG dari config dan satu lagi
    (`threatActorTrendTele.py`) punya token Telegram hardcoded -- kelas
    bug itu gak mungkin lagi di sini karena `fetch()` gak pernah pegang
    `Session`/koneksi/token mentah.

    `reference` itu PENGECUALIAN TERKONTROL, bukan lubang di pagar ini:
    isinya data BIASA (list/dict) yang `Runner` udah query dari Postgres
    KITA SEBELUM `fetch()` dipanggil (lihat `ScraperMeta.reference_data` +
    `cti_scraper.reference_data`) -- `fetch()` baca datanya, gak pernah
    pegang `Session` buat query sendiri.
    """

    meta: ScraperMeta
    run_id: str
    http: ScraperHttpClient
    log: structlog.typing.FilteringBoundLogger
    now: datetime = field(default_factory=_utcnow_naive)
    """Injectable buat test deterministik -- jangan panggil
    `datetime.now()` langsung di `fetch()`, pakai `ctx.now`."""

    options: dict[str, str] = field(default_factory=dict)
    """Nilai EFEKTIF `ScraperMeta.options` (default kode + pilihan admin + override CLI),
    key -> value. `{}` kalau scraper tidak mendeklarasikan opsi. `fetch()` cuma membaca
    -- pilihan yang berimbas ke kredensial sudah diterapkan `Runner` sebelum sampai sini."""

    reference: dict[str, Any] = field(default_factory=dict)
    """Diisi `Runner` dari `ScraperMeta.reference_data` SEBELUM `fetch()`
    dipanggil -- key-nya nama dataset (mis. "techstack"), value-nya data
    Python biasa. Kosong (`{}`) kalau scraper gak declare `reference_data`
    apa pun (mayoritas)."""

    route_handler: Any = None
    """Hook TESTING doang -- bukan API buat scraper pakai. Kalau diisi
    (lihat `cti_scraper.testing`), `page()` masang `page.route("**/*", ...)`
    pakai handler ini SEBELUM diserahin ke scraper, jadi `page.goto()` di
    scraper gak pernah nyentuh jaringan beneran -- byte-nya dari fixture
    Fase 0. Produksi selalu `None`; jalur network asli gak berubah."""

    partial_reason: str | None = None
    """Alasan run ini TERPOTONG, diisi lewat `mark_partial()`; `None` = run lengkap. `Runner`
    membacanya SESUDAH `fetch()` habis dan mencatat status `partial` (bukan `ok`)."""

    def mark_partial(self, reason: str) -> None:
        """Tandai run ini terpotong sebelum semua kandidat sumber diproses (mis. kena
        `meta.max_items`). Cuma menaikkan status ke `partial` -- item yang sudah di-`yield`
        tetap diproses normal, dan error (`fetch_error` dst.) tetap menang atas `partial`.
        Pemanggilan kedua menimpa alasan sebelumnya."""
        self.partial_reason = reason

    @contextmanager
    def page(self, **kwargs: Any) -> Iterator[Page]:
        """Playwright page. Raise `ConfigError` kalau `meta.runtime` bukan
        'browser' -- declaring `runtime='browser'` itu yang nge-route ke
        image yang punya Chromium (Fase 9), jadi mismatch ini harus
        keliatan pas dev, bukan `ImportError` jam 3 pagi di produksi."""
        if self.meta.runtime != "browser":
            raise ConfigError(
                f"scraper '{self.meta.id}' manggil ctx.page() tapi "
                f"meta.runtime='{self.meta.runtime}' -- ganti jadi 'browser'"
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise ConfigError(
                "playwright belum ke-install -- jalanin "
                "`uv sync --extra browser` di packages/cti-scraper"
            ) from e

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                pg = browser.new_page(**kwargs)
                pg.set_extra_http_headers({"User-Agent": DEFAULT_USER_AGENT})
                if self.route_handler is not None:
                    pg.route("**/*", self.route_handler)
                yield pg
            finally:
                browser.close()


class BaseScraper(abc.ABC):
    """Subclass ini di SATU file di bawah `cti_scrapers/` dan selesai.

    Framework (lewat `runner.Runner`) pegang, urut begini:
      1. baca `scraper_config` DB buat override enable/schedule/rate_limit
      2. akuisisi token rate-limit per-domain
      3. buka `ScraperRun` (heartbeat: started_at)
      4. panggil `fetch()`, tarik maksimum `meta.max_items`
      5. validasi tiap item (Pydantic udah nanganin ini otomatis)
      6. dedup RESERVE (bukan commit) per item
      7. serahin item yang ke-reserve ke sink yang kedaftar buat tipenya
      8. dedup COMMIT kalau sink sukses / RELEASE kalau sink gagal
      9. tutup `ScraperRun` (items_found/items_new/status/traceback)
     10. retry+backoff di `TransientFetchError`

    Yang kamu pegang: `fetch()`. Itu doang.
    """

    meta: ClassVar[ScraperMeta]
    __abstract__: ClassVar[bool] = False
    """Set `True` di family base (RSSScraper dkk) yang sengaja belum
    konkret. JANGAN diwarisin diam-diam -- tiap subclass konkret harus
    nulis `meta`-nya sendiri (lihat __init_subclass__ di bawah)."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("__abstract__", False):
            return  # family base, sengaja gak didaftarin

        if "meta" not in cls.__dict__:
            # GAGAL SEKARANG, di waktu import -- bukan diam-diam gak
            # kedaftar. Lupa nulis `meta` itu kesalahan yang harus keliatan
            # pas file scraper-nya di-import, bukan pas orang lain nyariin
            # kenapa scraper dia gak pernah jalan.
            raise ConfigError(
                f"{cls.__module__}.{cls.__qualname__} subclass BaseScraper tapi "
                "gak nulis `meta` sendiri, dan gak di-mark __abstract__=True. "
                "Scraper konkret: tambahin `meta = ScraperMeta(...)`. Family "
                "base baru: set `__abstract__: ClassVar[bool] = True`."
            )

        from cti_scraper.registry import register

        register(cls)

    @abc.abstractmethod
    def fetch(self, ctx: ScrapeContext) -> Iterator[Item]:
        """Yield nol atau lebih Item. JANGAN dedup, persist, alert, atau
        nyatet run di sini -- semua itu tanggung jawab framework.

        Pakai `ctx.http` buat HTTP (client bersama, UA/timeout/retry udah
        diset) dan `ctx.page()` buat Playwright (runtime='browser' doang).

        Raise `TransientFetchError` (`cti_scraper.errors`) buat apa pun
        yang worth di-retry (5xx, timeout, connection reset). Raise
        `ParseError` kalau dokumennya kebaca tapi strukturnya gak sesuai
        yang diharap -- itu situs berubah, bukan blip, dan framework bakal
        nyatet run `status='parse_error'` lalu eskalasi ke health sweep,
        BUKAN nyoba tiga kali ulang buat kegagalan yang gak bakal beda.

        Yield nol item itu SAH dan kecatat `status='empty'` -- beberapa
        run kosong berturut-turut itu yang dipakai health sweep buat
        mbedain "sumber lagi sepi" dari "selector rusak", sesuatu yang
        sistem lama gak bisa lakuin sama sekali.
        """

    def dedup_key(self, item: Item) -> str | None:
        """Override cuma kalau key bawaan item salah buat sumber ini.
        Return `None` buat skip dedup sepenuhnya (mis. collector snapshot
        penuh yang emang mau nulis ulang tiap run)."""
        return item.dedup_key()

    def on_run_error(self, exc: BaseException, ctx: ScrapeContext) -> None:
        """Hook buat cleanup spesifik-sumber. JANGAN nelen exception di
        sini -- framework tetap nyatet dan mengklasifikasikan apa pun yang
        terjadi, hook ini cuma buat efek samping (mis. tutup file handle)."""
        return None
