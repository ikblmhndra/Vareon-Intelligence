"""Eksekusi satu scraper end-to-end: rate-limit -> fetch -> dedup -> sink
-> heartbeat. Dipanggil CLI (Fase 3) dan nanti task Celery (Fase 6) --
signature sama, beda cuma siapa yang manggil dan gimana retry-nya diatur
(runner ini SENGAJA gak retry sendiri; caller yang urus, lihat plan §4.3).

`ScraperConfig` (Fase 9, control plane) dibaca SEKALI di awal `execute()`
-- `enabled=False` short-circuit sebelum fetch APA PUN (`ScraperMeta.
enabled`'s docstring sendiri, Fase 3: "`scraper_config` di DB nge-override
runtime, bukan field ini"), `options` (pilihan admin, mis. sumber data Twitter --
lihat `cti_scraper.options`) dipilih sekali per run dan menentukan KREDENSIAL yang
dipasang + `ctx.options` buat `fetch()`, `rate_limit`/`max_items` override lewat
`dataclasses.replace()` ke `self.meta` -- family (`RssScraper` dkk) baca
`self.meta.max_items`/`ctx.http` langsung, jadi override nempel otomatis
tanpa nyentuh kode family. `schedule` override SENGAJA gak dibaca di sini
-- itu jadwal beat (`cti_worker.beat`), bukan sesuatu yang mempengaruhi
satu eksekusi, efeknya baru kepake pas worker restart berikutnya.

Cold-start guard (Fase 10, `_cold_start_cap`) -- scraper tanpa satu pun baris
`scraper_seen` (baru, habis `reset-dedup`, atau TTL-nya abis semua) cuma
enrich `cold_start_max_items` artikel TERBARU; sisanya di-mark seen tanpa
diproses. Tanpa ini run pertama ~84 scraper = seluruh isi feed masuk
enrichment (LLM + alert Telegram) sekaligus. Jalur cutover utama BUKAN ini
(itu warm start: seed `scraper_seen` dari dump lama), cap ini jaring
pengaman."""

from __future__ import annotations

import dataclasses
import datetime
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import structlog

from cti_scraper.base import BaseScraper, ConfigError, ScrapeContext
from cti_scraper.dedup import DedupStore
from cti_scraper.errors import BackpressureError, ParseError, RateLimited, TransientFetchError
from cti_scraper.http import ScraperHttpClient
from cti_scraper.item_display import display_title_url
from cti_scraper.items import ArticleItem, NoticeItem
from cti_scraper.options import credential_for, resolve_options, validate_options
from cti_scraper.sinks import dispatch, finish_run
from cti_scraper.supersede import superseded_by_mirror

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from cti_core.db.models.scraper import ScraperConfig
    from sqlalchemy.orm import Session

    from cti_scraper.base import ScraperMeta
    from cti_scraper.items import Item
    from cti_scraper.ratelimit import TokenBucket


class RunnerConfigError(Exception):
    """Runner dipanggil dengan kombinasi argumen yang gak masuk akal, mis.
    `dry_run=False` tanpa `session`."""


@dataclass
class RunResult:
    run_id: str
    scraper_id: str
    status: str
    """ok | empty | partial | parse_error | fetch_error | rate_limited | backpressure |
    disabled. `partial` = run selesai tapi terpotong (`ScrapeContext.mark_partial`) ATAU ada item
    yang gagal di sink (`final_status`)."""
    items_found: int = 0
    items_new: int = 0
    items_dropped: int = 0
    items_failed: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    duration_ms: int = 0
    retry_after: float | None = None
    """Detik minimal sebelum layak dicoba ulang (dari `RateLimited.retry_after`),
    `None` = gak ada petunjuk. Dibaca task `scrape.run` buat jeda retry."""


def final_status(status: str, items_failed: int) -> str:
    """Run yang lolos tanpa error fetch tapi dengan item yang GAGAL di sink bukan `ok`: `partial`
    (dev 2026-10-17: `github_poc_monitor` 4 item gagal tiap jam, 558 item dalam 7 hari, run-nya
    tetap `ok`). `partial` dipilih karena sudah berstatus terminal, dihitung sukses oleh
    `cve_check` dan web, tidak di-retry, dan punya gaya peringatan. Status lain (empty, error)
    tidak diubah."""
    return "partial" if status == "ok" and items_failed else status


def _apply_config_overrides(meta: ScraperMeta, config: ScraperConfig) -> ScraperMeta:
    """`ScraperConfig.rate_limit`/`max_items` (Fase 9, `None` = "gak ada
    override") ke `ScraperMeta` frozen dataclass lewat `dataclasses.
    replace()` -- family (`RssScraper` dkk) baca `self.meta.max_items`,
    `ScraperHttpClient` baca `meta.rate_limit`, keduanya gak tau/peduli
    nilainya dari kode atau DB. `schedule`/`enabled`/`paused_reason` gak
    disentuh di sini -- `enabled` dicek terpisah di `execute()` (short-
    circuit SEBELUM baris ini kepanggil), `schedule` urusan beat."""
    overrides: dict[str, object] = {}
    if config.rate_limit:
        overrides["rate_limit"] = config.rate_limit
    if config.max_items:
        overrides["max_items"] = config.max_items
    if not overrides:
        return meta
    return dataclasses.replace(meta, **overrides)  # type: ignore[arg-type]


class Runner:
    def __init__(
        self,
        scraper_cls: type[BaseScraper],
        *,
        session: Session | None = None,
        bucket: TokenBucket | None = None,
        transport: httpx.BaseTransport | None = None,
        dry_run: bool = False,
        cold_start_max_items: int | None = None,
        prime: bool = False,
        options: Mapping[str, str] | None = None,
    ) -> None:
        """`cold_start_max_items` -- `None` (default) baca `Settings.scraper.
        cold_start_max_items`; angka eksplisit buat test/tooling yang mau
        nentuin sendiri (`<= 0` = guard mati).

        `prime` -- jalanin fetch BENERAN dan tandai SEMUA item yang ketemu sebagai
        "sudah terlihat" TANPA mengirim/menyimpan apa pun (sink dilewati). Buat
        cutover: scraper yang riwayat dedup-nya gak bisa dibawa dari sistem lama
        (watcher commit, advisory library) di-`prime` sebelum dinyalakan, jadi run
        pertamanya gak mengulang backlog. Beda dari cold-start cap (cuma N terbaru
        yang lolos, sisanya di-skip) -- prime melewatkan SEMUANYA.

        `options` -- override EKSPLISIT `ScraperMeta.options` (CLI `--option key=value`),
        menang atas pilihan admin di `ScraperConfig.options`. Tidak menulis apa pun ke DB:
        buat mencoba sumber data lain sekali jalan tanpa mengubah konfigurasi produksi.
        Nilai yang salah = `OptionError` SEKARANG, bukan di tengah run."""
        if options:
            validate_options(scraper_cls.meta, options)
        if not dry_run and session is None:
            raise RunnerConfigError(
                "dry_run=False butuh `session` -- runner nulis heartbeat+sink lewat itu"
            )
        self.scraper_cls = scraper_cls
        self.meta = scraper_cls.meta
        self.session = session
        self.bucket = bucket
        self.transport = transport
        self.dry_run = dry_run
        self._cold_start_max_items = cold_start_max_items
        self._prime = prime
        self._option_overrides = dict(options) if options else None
        self._chosen_options: Mapping[str, str] | None = None

    def execute(self, *, trigger: str = "manual") -> RunResult:
        run_id = str(uuid.uuid4())
        log = structlog.get_logger(scraper_id=self.meta.id, run_id=run_id, trigger=trigger)
        started = time.monotonic()

        run = None
        config = None
        if not self.dry_run:
            from cti_core.db.repositories.scraper import ScraperConfigRepo, ScraperRunRepo

            assert self.session is not None  # dijamin __init__
            run_repo = ScraperRunRepo(self.session)
            config = ScraperConfigRepo(self.session).get(self.meta.id)

            if (config is not None and not config.enabled) or superseded_by_mirror(self.meta.id):
                # Short-circuit SEBELUM `run_repo.start()` -- gak ada
                # heartbeat "running" yang nyangkut, satu baris "disabled"
                # langsung terminal, gak nyentuh HTTP/rate-limit/dedup
                # sama sekali (beda dari status lain yang semuanya lewat
                # `_run_body`).
                run = run_repo.start(run_id=run_id, scraper_id=self.meta.id, trigger=trigger)
                run_repo.finish(run, status="disabled")
                self.session.commit()
                result = RunResult(run_id=run_id, scraper_id=self.meta.id, status="disabled")
                result.duration_ms = int((time.monotonic() - started) * 1000)
                log.info("run_skipped_disabled", duration_ms=result.duration_ms)
                return result

            if config is not None:
                self.meta = _apply_config_overrides(self.meta, config)
                self._chosen_options = config.options

            run = run_repo.start(run_id=run_id, scraper_id=self.meta.id, trigger=trigger)
            self.session.commit()

        try:
            result = self._run_body(run_id, log)
        except Exception as e:
            if self.dry_run:  # tidak ada baris run yang perlu ditutup; error-nya untuk operator
                raise
            # Setup `_run_body` (opsi, kredensial, referensi DB) ada di luar `try` fetch-nya: tanpa
            # ini exception di sana meninggalkan run `running` selamanya (dev: 8 run yatim) dan
            # mematikan task. Sekarang run ditutup sebagai `fetch_error` dengan sebabnya.
            log.error("run_setup_failed", error=str(e), error_type=type(e).__name__)
            result = RunResult(run_id=run_id, scraper_id=self.meta.id, status="fetch_error")
            result.errors.append({"stage": "setup", "type": type(e).__name__, "message": str(e)})

        if not self.dry_run:
            assert self.session is not None
            # `_run_body` bisa selesai dgn sesi DB RUSAK (koneksi putus di
            # tengah -> transaksi "inactive"; `finish()` di bawah bakal raise
            # PendingRollbackError, task crash, run nyangkut `running`).
            # Rollback dulu -- gak ada yang perlu diselamatkan: item yang
            # sukses SUDAH di-commit satu per satu di `_handle_item`.
            try:
                self.session.rollback()
            except Exception as e:  # koneksi mati total: biarin `finish` yang gagal keras
                log.warning("rollback_before_finish_failed", error=str(e))
            run_repo.finish(
                run,  # type: ignore[arg-type]
                status=result.status,
                items_found=result.items_found,
                items_new=result.items_new,
                items_dropped=result.items_dropped,
                items_failed=result.items_failed,
                errors=result.errors,
            )
            self.session.commit()
            # Ringkasan CVE baru (kalau ada) -- sesudah run tercatat; tidak pernah raise.
            finish_run(self.session)

        result.duration_ms = int((time.monotonic() - started) * 1000)
        log.info(
            "run_finished",
            status=result.status,
            items_found=result.items_found,
            items_new=result.items_new,
            items_dropped=result.items_dropped,
            items_failed=result.items_failed,
            duration_ms=result.duration_ms,
        )
        return result

    def _run_body(self, run_id: str, log: structlog.typing.FilteringBoundLogger) -> RunResult:
        result = RunResult(run_id=run_id, scraper_id=self.meta.id, status="ok")

        options = resolve_options(self.meta, self._chosen_options, self._option_overrides)
        if options:
            log.info("scraper_options", options=options)
        credential = credential_for(self.meta, options)

        default_headers = None
        if credential is not None:
            from cti_scraper.credentials import resolve_credential_headers

            try:
                default_headers = resolve_credential_headers(credential)
            except ConfigError as e:
                # Secret kosong di env (mis. NVD__API_KEY belum diisi). Dulu
                # ConfigError nembus `execute()`: run nyangkut `running` tanpa
                # `finish`, task Celery crash tiap jadwal. Sekarang run GAGAL
                # yang jelas penyebabnya (kelihatan di control plane sbg
                # `fetch_error` + stage "config") dan gak ada request tanpa
                # auth yang keluar.
                result.status = "fetch_error"
                result.errors.append({"stage": "config", "type": "ConfigError", "message": str(e)})
                log.error("credential_missing", credential=credential, error=str(e))
                return result

        http = ScraperHttpClient(
            timeout_s=self.meta.timeout_s,
            rate_limit=self.meta.rate_limit,
            bucket=self.bucket,
            transport=self.transport,
            default_headers=default_headers,
        )

        reference: dict[str, object] = {}
        if self.meta.reference_data:
            if self.session is None:
                raise RunnerConfigError(
                    f"scraper '{self.meta.id}' declare reference_data={self.meta.reference_data} "
                    "tapi gak ada `session` -- baca-baca DB internal tetap butuh session "
                    "walau dry_run=True (cuma sink/dedup yang di-skip pas dry-run)"
                )
            from cti_scraper.reference_data import resolve_reference_data

            reference = resolve_reference_data(self.meta.reference_data, self.session)

        ctx = ScrapeContext(
            meta=self.meta,
            run_id=run_id,
            http=http,
            log=log,
            reference=reference,
            options=options,
        )
        scraper = self.scraper_cls()
        # `BaseScraper.meta` DIDEKLARASI `ClassVar` -- tiap family baca
        # `self.meta.max_items` dkk dari ATRIBUT KELAS scraper (mis.
        # `RSSScraper.fetch()`), BUKAN dari `ctx.meta`. Override
        # `ScraperConfig` (`_apply_config_overrides()`) cuma nempel ke
        # `Runner.meta` -- KETEMU LIVE (bukan dugaan): set `max_items=2`
        # via `ScraperConfig` tapi `bleepcomp` tetep nge-yield 11 item,
        # `RSSScraper.fetch()` gak pernah liat override-nya. Assignment
        # instance ini nge-shadow ClassVar SATU scraper instance ini doang
        # (scraper baru dibikin tiap `execute()`, gak nyentuh kelasnya).
        scraper.meta = self.meta  # type: ignore[misc]
        dedup = None if self.dry_run else DedupStore(self.session)  # type: ignore[arg-type]

        try:
            stream: Iterable[Item] = scraper.fetch(ctx)
            cold_skip: set[int] = set()
            cold_cap = self._cold_start_cap()
            if cold_cap is not None:
                # Cold: buffer dulu (bounded `meta.max_items`) biar bisa milih
                # N artikel TERBARU -- streaming langsung bakal ngambil N
                # pertama sesuai urutan feed, yang belum tentu terbaru.
                stream = buffered = list(stream)
                cold_skip = self._cold_start_skipped(buffered, scraper, cold_cap)
                log.info(
                    "cold_start_cap_applied",
                    cap=cold_cap,
                    items_found=len(buffered),
                    items_skipped=len(cold_skip),
                )

            for item in stream:
                result.items_found += 1
                self._handle_item(
                    run_id, item, scraper, dedup, result, log, cold_skip=id(item) in cold_skip
                )

            if result.items_found == 0:
                result.status = "empty"
            if ctx.partial_reason is not None:
                # Scraper bilang sendiri run-nya terpotong (mis. kena `max_items`): jangan
                # tampil `ok` di control plane. Alasannya masuk `errors` supaya terbaca di
                # detail run, bukan cuma di log worker.
                result.status = "partial"
                result.errors.append(
                    {"stage": "fetch", "type": "Partial", "message": ctx.partial_reason}
                )
                log.warning("run_partial", reason=ctx.partial_reason)
            result.status = final_status(result.status, result.items_failed)

        except ParseError as e:
            result.status = "parse_error"
            result.errors.append({"stage": "parse", "type": "ParseError", "message": str(e)})
            log.error("parse_error", error=str(e))
        except BackpressureError as e:
            # Dilempar sink lewat `_handle_item` -- sisa item run ini bakal
            # kena juga, jadi berhenti di sini (bukan diteruskan satu-satu).
            result.status = "backpressure"
            result.errors.append({"stage": "sink", "type": "BackpressureError", "message": str(e)})
            log.warning("backpressure", error=str(e))
        except RateLimited as e:
            result.status = "rate_limited"
            result.retry_after = e.retry_after
            result.errors.append({"stage": "fetch", "type": "RateLimited", "message": str(e)})
            log.warning("rate_limited", error=str(e))
        except TransientFetchError as e:
            result.status = "fetch_error"
            result.errors.append(
                {"stage": "fetch", "type": "TransientFetchError", "message": str(e)}
            )
            log.warning("transient_fetch_error", error=str(e))
        except Exception as e:
            result.status = "fetch_error"
            result.errors.append(
                {
                    "stage": "fetch",
                    "type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                }
            )
            log.error("unhandled_fetch_error", error=str(e), error_type=type(e).__name__)
            scraper.on_run_error(e, ctx)
        finally:
            http.close()

        return result

    def _cold_start_cap(self) -> int | None:
        """Batas item buat run INI, atau `None` = guard gak berlaku (dry-run,
        scraper udah pernah nyimpen dedup, atau setting `<= 0`). Definisi
        "cold" lihat `ScraperSeenRepo.has_any()`."""
        if self.dry_run or self.session is None:
            return None
        if self._prime:
            return 0  # tandai semuanya seen, kirim nol

        cap = self._cold_start_max_items
        if cap is None:
            from cti_core.config import get_settings

            cap = get_settings().scraper.cold_start_max_items
        if cap <= 0:
            return None

        from cti_core.db.repositories.scraper_seen import ScraperSeenRepo

        if ScraperSeenRepo(self.session).has_any(self.meta.id):
            return None
        return min(cap, self.meta.max_items)

    def _cold_start_skipped(self, items: list[Item], scraper: BaseScraper, cap: int) -> set[int]:
        """`id()` item yang di-mark seen TANPA diproses. Cuma `ArticleItem` dan
        `NoticeItem` yang kena cap -- keduanya jalur ke channel Telegram
        (`ArticleItem` lewat antrian `enrich` LLM, `NoticeItem` langsung); sink
        lain (ransomware/CVE/IOC/tweet) nulis langsung ke DB, riwayatnya justru
        berguna dan gak ada yang banjir. Item tanpa dedup key juga dilewatin:
        gak ada cara nge-mark-nya seen, jadi dibuang begitu aja bakal muncul
        lagi tiap run."""
        candidates = [
            i
            for i in items
            if (self._prime or isinstance(i, ArticleItem | NoticeItem))
            and scraper.dedup_key(i) is not None
        ]
        # Terbaru dulu. Sort stabil (juga dgn reverse=True), jadi feed tanpa
        # tanggal tetap urutan feed -- umumnya sudah terbaru-dulu.
        newest_first = sorted(
            candidates,
            key=lambda i: getattr(i, "posted_on", None) or datetime.date.min,
            reverse=True,
        )
        return {id(i) for i in newest_first[cap:]}

    def _handle_item(
        self,
        run_id: str,
        item: object,
        scraper: BaseScraper,
        dedup: DedupStore | None,
        result: RunResult,
        log: structlog.typing.FilteringBoundLogger,
        *,
        cold_skip: bool = False,
    ) -> None:
        if self.dry_run:
            return  # liat hasilnya doang -- gak dedup, gak sink

        assert dedup is not None and self.session is not None
        title, url = display_title_url(item)  # type: ignore[arg-type]
        raw_key = scraper.dedup_key(item)  # type: ignore[arg-type]
        if self._prime and raw_key is None:
            # Item tanpa dedup key gak bisa ditandai seen; di mode prime (nol efek
            # samping) dia dibuang, bukan di-dispatch.
            result.items_dropped += 1
            self._log_item(run_id, title, url, url or title, accepted=False, reason="primed")
            return
        dedup_key: str | None = None
        if raw_key is not None:
            dedup_key = dedup.reserve(scraper_id=self.meta.id, raw_key=raw_key)
            if dedup_key is None:
                result.items_dropped += 1
                self._log_item(run_id, title, url, raw_key, accepted=False, reason="duplicate")
                return  # duplikat, atau lease dipegang worker lain

        try:
            skipped = cold_skip and dedup_key is not None
            if not skipped:
                dispatch(item, self.meta, self.session)  # type: ignore[arg-type]
            self.session.commit()
            if dedup_key is not None:
                dedup.commit(dedup_key, ttl_days=self.meta.dedup_ttl_days)
                # Commit EKSPLISIT -- `dedup.commit()` cuma flush. Tanpa ini
                # state "done" numpang commit `_log_item()` di bawah, dan
                # kalau log itu gagal (rollback), item balik ke `in_flight`
                # terus di-dispatch ULANG begitu lease-nya basi.
                self.session.commit()
            if skipped:
                result.items_dropped += 1
                self._log_item(
                    run_id,
                    title,
                    url,
                    raw_key or url or title,
                    accepted=False,
                    reason="primed" if self._prime else "cold_start_cap",
                )
            else:
                result.items_new += 1
                self._log_item(
                    run_id, title, url, raw_key or url or title, accepted=True, reason=None
                )
        except BackpressureError:
            # Bukan kegagalan item: lepas lease (COMMIT, biar pelepasannya
            # durable) supaya run berikutnya nyoba lagi, lalu naikin ke
            # `_run_body` buat ngehentiin run.
            self.session.rollback()
            if dedup_key is not None:
                dedup.release(dedup_key)
                self.session.commit()
            self._log_item(
                run_id, title, url, raw_key or url or title, accepted=False, reason="backpressure"
            )
            raise
        except Exception as e:
            self.session.rollback()
            if dedup_key is not None:
                dedup.release(dedup_key)
            result.items_failed += 1
            result.errors.append({"stage": "sink", "type": type(e).__name__, "message": str(e)})
            log.error("sink_failed", error=str(e), error_type=type(e).__name__)
            self._log_item(
                run_id,
                title,
                url,
                raw_key or url or title,
                accepted=False,
                reason=f"{type(e).__name__}: {e}",
            )

    def _log_item(
        self,
        run_id: str,
        title: str,
        url: str,
        hash_source: str,
        *,
        accepted: bool,
        reason: str | None,
    ) -> None:
        """Best-effort -- kegagalan nulis baris log item TIDAK BOLEH
        nggagalin run yang udah kelar (accept/reject-nya udah kejadian,
        ini cuma telemetri tambahan buat control plane Fase 9)."""
        from cti_core.config import get_settings
        from cti_core.db.repositories.scraper import ScraperItemRepo
        from cti_core.urlkit import url_hash as compute_url_hash

        assert self.session is not None
        try:
            ScraperItemRepo(self.session).create(
                run_id=run_id,
                scraper_id=self.meta.id,
                url_hash=compute_url_hash(hash_source),
                title=title,
                url=url,
                accepted=accepted,
                reason=reason[:200] if reason else None,
                retention_days=get_settings().worker.scraper_item_retention_days,
            )
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            structlog.get_logger().warning("scraper_item_log_failed", error=str(e))
