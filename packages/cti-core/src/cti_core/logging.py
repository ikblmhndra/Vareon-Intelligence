"""Logging terstruktur (JSON) buat seluruh platform.

Menggantikan `print()` polos yang dipakai di mana-mana di kedua repo lama
(nol pemakaian modul `logging` sama sekali -- lihat plan §"Observability").
JSON dari awal supaya bisa diagregasi (per scraper_id, per run_id) tanpa
parsing teks, dan supaya field kayak `scraper_id`/`run_id` konsisten posisi
dan namanya di semua log, bukan disisipkan manual ke dalam pesan.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def quiet_http_loggers() -> None:
    """httpx mencatat `POST https://api.telegram.org/bot<TOKEN>/sendMessage` di INFO: token bot
    (yang sekarang bisa diatur dari halaman admin) akan masuk log container tiap kirim. WARNING
    tetap memunculkan kegagalan sungguhan. Dipanggil `configure_logging` (API, beat) DAN worker
    Celery lewat sinyal logger-nya, karena worker tidak memanggil `configure_logging`."""
    logging.getLogger("httpx").setLevel(logging.WARNING)


def configure_logging(*, level: str = "INFO", json: bool = True) -> None:
    """Panggil sekali di entrypoint tiap proses (API, worker, CLI).

    `json=False` buat dev lokal di terminal (output berwarna, gampang dibaca)
    -- `json=True` (default) buat container, biar log bisa di-parse infra
    logging (journald/Loki/dst).
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    quiet_http_loggers()

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(**initial_context: Any) -> structlog.typing.FilteringBoundLogger:
    """Logger dengan context awal udah di-bind, mis.
    `get_logger(scraper_id="gbhackers")`. Semua log berikutnya dari logger
    ini otomatis bawa field itu -- gak perlu disisipkan manual tiap panggil.
    """
    return structlog.get_logger(**initial_context)  # type: ignore[no-any-return]
