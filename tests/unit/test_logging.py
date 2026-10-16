import json
import logging
from collections.abc import Iterator

import pytest
import structlog
from cti_core.logging import configure_logging, get_logger


def test_json_log_has_bound_context_and_required_fields(
    capsys: object,
) -> None:
    configure_logging(level="INFO", json=True)
    log = get_logger(scraper_id="gbhackers", run_id="r1")
    log.info("run_started", items_found=3)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    line = json.loads(captured.out.strip().splitlines()[-1])

    assert line["scraper_id"] == "gbhackers"
    assert line["run_id"] == "r1"
    assert line["items_found"] == 3
    assert line["event"] == "run_started"
    assert line["level"] == "info"
    assert "timestamp" in line


def test_configure_logging_is_idempotent() -> None:
    # Dipanggil beberapa kali (mis. tiap test) gak boleh numpuk processor
    # atau ngelempar exception.
    configure_logging()
    configure_logging()
    configure_logging(json=False)
    structlog.reset_defaults()
    configure_logging(json=True)


@pytest.fixture
def restore_httpx_level() -> Iterator[None]:
    """`configure_logging` menyetel level logger "httpx" (global proses): kembalikan setelah tes.

    `disabled` ikut dijaga. `alembic/env.py` memanggil `fileConfig`, yang menonaktifkan logger yang
    sudah ada, dan di CI tes integrasi (migrasi) jalan SEBELUM tes ini. Logger yang `disabled`
    membuang semua rekaman: tes "WARNING tetap lolos" gagal, dan tes "INFO dibuang" lulus tanpa
    menguji apa pun.
    """
    logger = logging.getLogger("httpx")
    level, disabled = logger.level, logger.disabled
    logger.disabled = False
    yield
    logger.setLevel(level)
    logger.disabled = disabled


def test_configure_logging_lowers_the_httpx_logger_to_warning(
    restore_httpx_level: None,
) -> None:
    """httpx mencatat URL lengkap di INFO, dan token bot Telegram ada di path URL-nya (token itu
    sekarang bisa diatur dari halaman admin): INFO dari httpx tidak boleh sampai ke log
    container."""
    logging.getLogger("httpx").setLevel(logging.NOTSET)

    configure_logging(level="INFO")

    assert logging.getLogger("httpx").level == logging.WARNING


def test_httpx_info_records_with_the_full_url_are_dropped_after_configure_logging(
    restore_httpx_level: None, caplog: pytest.LogCaptureFixture
) -> None:
    configure_logging(level="INFO")
    url = "https://api.telegram.org/bot111222333:probe-telegram-aaaaaa/sendMessage"

    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info('HTTP Request: POST %s "HTTP/1.1 200 OK"', url)

    assert "probe-telegram-aaaaaa" not in caplog.text


def test_httpx_warnings_still_get_through_after_configure_logging(
    restore_httpx_level: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Menurunkan ke WARNING, bukan membisukan: kegagalan sungguhan tetap tercatat."""
    configure_logging(level="INFO")

    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").warning("kegagalan httpx sungguhan")

    assert "kegagalan httpx sungguhan" in caplog.text
