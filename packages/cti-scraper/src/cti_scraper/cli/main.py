"""Permukaan DX scraper. Lihat docs/ADDING_A_SCRAPER.md buat alur lengkap
(scaffold -> isi -> dry-run -> verify -> enable) dan alasan tiap langkah.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import typer

from cti_scraper import registry
from cti_scraper.base import BaseScraper
from cti_scraper.items import ArticleItem
from cti_scraper.testing import (
    FixtureNotFound,
    article_keys,
    dedup_keys,
    expected_article_keys,
    make_fixture_context,
)

app = typer.Typer(
    name="cti-scraper",
    help="Framework scraper CTI platform. Lihat docs/ADDING_A_SCRAPER.md.",
    no_args_is_help=True,
)

DEFAULT_FIXTURES_DIR = Path("tests/fixtures")

_OPTION_HELP = (
    "Timpa satu opsi scraper SEKALI JALAN, format key=value (boleh diulang), mis. "
    "--option provider=x_official. Tidak menulis apa pun ke DB; pilihan admin di "
    "control plane tidak berubah."
)


def _parse_options(pairs: list[str]) -> dict[str, str]:
    options: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise typer.BadParameter(
                f"format harus key=value, dapat '{pair}'", param_hint="--option"
            )
        options[key.strip()] = value.strip()
    return options


@app.command("list")
def list_scrapers(
    tag: str | None = typer.Option(None, "--tag", help="Filter berdasarkan tag"),
) -> None:
    """List semua scraper yang kedaftar (auto-discovery dari cti_scrapers/)."""
    scrapers = registry.all_scrapers()
    if not scrapers:
        typer.echo(
            "gak ada scraper kedaftar -- cek cti_scrapers/ ada isinya, dan modulnya ke-import"
        )
        raise typer.Exit(1)

    for scraper_id, cls in sorted(scrapers.items()):
        meta = cls.meta
        if tag and tag not in meta.tags:
            continue
        flag = "on " if meta.enabled else "off"
        typer.echo(f"[{flag}] {scraper_id:24} {meta.runtime:8} {meta.schedule:16} {meta.source}")


@app.command("dry-run")
def dry_run(
    scraper_id: str,
    option: list[str] = typer.Option([], "--option", "-o", help=_OPTION_HELP),
) -> None:
    """Jalanin fetch() beneran lawan sumber ASLI, TANPA nulis DB/dedup/alert.

    Ini yang gak ada sama sekali di sistem lama -- satu-satunya cara nguji
    scraper dulu adalah nyalain di produksi dan nungguin.
    """
    from cti_scraper.options import OptionError
    from cti_scraper.runner import Runner

    cls = registry.get(scraper_id)
    options = _parse_options(option)

    try:
        if cls.meta.reference_data:
            # Reference data (techstack, dst) dibaca dari Postgres KITA, bukan
            # sumber eksternal -- dry-run tetap butuh session buat baca ini
            # walau gak nulis apa-apa (sink/dedup tetap di-skip di bawah).
            from cti_core.db.engine import sync_session

            with sync_session() as session:
                result = Runner(cls, session=session, dry_run=True, options=options).execute(
                    trigger="manual"
                )
        else:
            result = Runner(cls, dry_run=True, options=options).execute(trigger="manual")
    except OptionError as e:
        typer.echo(f"opsi ditolak: {e}", err=True)
        raise typer.Exit(2) from e

    typer.echo(
        f"status={result.status} items_found={result.items_found} duration_ms={result.duration_ms}"
    )
    for err in result.errors:
        typer.echo(f"  ERROR [{err['stage']}] {err['type']}: {err['message']}", err=True)
    if result.status not in ("ok", "empty", "partial"):
        raise typer.Exit(1)


@app.command("run")
def run_scraper(
    scraper_id: str,
    prime: bool = typer.Option(
        False,
        "--prime",
        help="Tandai SEMUA item yang ketemu sebagai sudah-terlihat TANPA mengirim/menyimpan "
        "apa pun (buat cutover: scraper yang dedup-nya gak bisa dibawa dari sistem lama).",
    ),
    option: list[str] = typer.Option([], "--option", "-o", help=_OPTION_HELP),
) -> None:
    """Jalanin beneran -- nulis DB, dedup aktif, heartbeat kecatat."""
    from cti_core.db.engine import sync_session

    from cti_scraper.options import OptionError
    from cti_scraper.runner import Runner

    cls = registry.get(scraper_id)
    options = _parse_options(option)
    try:
        with sync_session() as session:
            result = Runner(
                cls, session=session, dry_run=False, prime=prime, options=options
            ).execute(trigger="manual")
    except OptionError as e:
        typer.echo(f"opsi ditolak: {e}", err=True)
        raise typer.Exit(2) from e

    typer.echo(
        f"status={result.status} items_found={result.items_found} "
        f"items_new={result.items_new} items_dropped={result.items_dropped} "
        f"items_failed={result.items_failed} duration_ms={result.duration_ms}"
    )
    if result.status not in ("ok", "empty", "partial"):
        raise typer.Exit(1)


@app.command("verify")
def verify(
    scraper_id: str,
    fixtures_dir: Path = typer.Option(DEFAULT_FIXTURES_DIR, "--fixtures-dir"),
    record: bool = typer.Option(
        False, "--record", help="Belum ada fixture? Rekam baseline baru dari sumber asli."
    ),
) -> None:
    """Adu output scraper lawan fixture Fase 0 (byte HTTP yang direkam).

    Belum ada fixture: scraper BARU (bukan hasil migrasi) atau scraper lama
    yang kebetulan gak sempat kerekam -- jalanin ulang dengan `--record`,
    baseline direkam LIVE saat itu juga (lihat docs/ADDING_A_SCRAPER.md).
    """
    cls = registry.get(scraper_id)

    try:
        ctx, fixture = make_fixture_context(cls, fixtures_dir=fixtures_dir)
    except FixtureNotFound as e:
        if not record:
            typer.echo(f"gak ada fixture: {e}", err=True)
            typer.echo("Jalanin ulang dengan --record buat bikin baseline pertama.", err=True)
            raise typer.Exit(1) from None
        _record_baseline(cls, fixtures_dir)
        return

    items = list(cls().fetch(ctx))

    # Dispatch berdasarkan TIPE item, bukan scraper_id -- konsisten sama
    # sinks.py: yield tipe beda = ditangani beda, gak ada special-case nama.
    # Anotasi eksplisit set[Any]: dua cabang balikin bentuk key yang beda
    # (tuple 3-elemen buat artikel, string dedup_key buat item lain).
    got: set[Any]
    want: set[Any]
    if items and isinstance(items[0], ArticleItem):
        got = article_keys(items)
        want = expected_article_keys(fixture.expected_items)
    else:
        got = dedup_keys(items)
        want = {e["offset_key"] for e in fixture.expected_items if "offset_key" in e}

    if got == want:
        typer.echo(f"OK -- {len(items)} item cocok persis lawan fixture ({fixture.day})")
        return

    typer.echo(f"BEDA lawan fixture {fixture.day}:", err=True)
    for extra in sorted(str(x) for x in got - want):
        typer.echo(f"  + {extra}", err=True)
    for missing in sorted(str(x) for x in want - got):
        typer.echo(f"  - {missing}", err=True)
    raise typer.Exit(1)


class _RecordingTransport(httpx.BaseTransport):
    """Nembus ke jaringan ASLI, sambil nyimpen (url, byte, content-type)
    tiap respons -- dasar dari fixture baru. Cuma buat scraper
    `runtime='light'`; `runtime='browser'` butuh Playwright route
    recording, belum didukung lewat CLI ini (pakai
    `tools/salvage/record_fixtures.py`, sudah ada dari Fase 0)."""

    def __init__(self) -> None:
        self._real = httpx.HTTPTransport()
        self.recorded: list[tuple[str, bytes, str]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._real.handle_request(request)
        response.read()
        self.recorded.append(
            (str(request.url), response.content, response.headers.get("content-type", ""))
        )
        return response


_EXT_HINTS = (("json", ".json"), ("xml", ".xml"), ("html", ".html"))


def _ext_for(content_type: str) -> str:
    ct = content_type.lower()
    for needle, ext in _EXT_HINTS:
        if needle in ct:
            return ext
    return ".txt"


def _record_baseline(cls: type[BaseScraper], fixtures_dir: Path) -> None:
    from cti_scraper.base import ScrapeContext
    from cti_scraper.http import ScraperHttpClient

    meta = cls.meta
    if meta.runtime == "browser":
        typer.echo(
            f"'{meta.id}' runtime='browser' -- perekaman via CLI ini belum "
            "didukung. Pakai tools/salvage/record_fixtures.py (Fase 0), yang "
            "udah nanganin Playwright.",
            err=True,
        )
        raise typer.Exit(1)

    import structlog

    default_headers = None
    if meta.credential is not None:
        from cti_scraper.credentials import resolve_credential_headers

        default_headers = resolve_credential_headers(meta.credential)

    reference: dict[str, object] = {}
    if meta.reference_data:
        from cti_core.db.engine import sync_session

        from cti_scraper.reference_data import resolve_reference_data

        with sync_session() as session:
            reference = resolve_reference_data(meta.reference_data, session)

    transport = _RecordingTransport()
    http = ScraperHttpClient(
        timeout_s=meta.timeout_s,
        rate_limit=meta.rate_limit,
        transport=transport,
        default_headers=default_headers,
    )
    now = datetime.now(UTC)
    ctx = ScrapeContext(
        meta=meta,
        run_id="record-baseline",
        http=http,
        log=structlog.get_logger(),
        now=now,
        reference=reference,
    )
    items = list(cls().fetch(ctx))

    if not meta.legacy_script:
        typer.echo(
            f"'{meta.id}' gak punya meta.legacy_script -- gak tau nama "
            "direktori fixture yang harus dipakai. Set legacy_script (boleh "
            "sama kayak meta.id buat scraper baru) lalu ulangi.",
            err=True,
        )
        raise typer.Exit(1)

    out_dir = fixtures_dir / meta.legacy_script
    out_dir.mkdir(parents=True, exist_ok=True)
    day = now.date().isoformat()

    for i, (_url, body, content_type) in enumerate(transport.recorded):
        suffix = "" if i == 0 else f".{i}"
        (out_dir / f"{day}.input{suffix}{_ext_for(content_type)}").write_bytes(body)

    expected = [
        {
            "title": it.title,
            "url": it.url,
            "posted_on": it.posted_on.isoformat() if it.posted_on else "",
        }
        if isinstance(it, ArticleItem)
        else {"dedup_key": it.dedup_key()}
        for it in items
    ]
    expected_path = out_dir / "expected_items.json"
    existing = json.loads(expected_path.read_text()) if expected_path.exists() else {}
    existing[day] = expected
    expected_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

    typer.echo(f"baseline direkam: {len(items)} item -> {out_dir} (hari {day})")


@app.command("enable")
def enable(scraper_id: str) -> None:
    """Nyalain scraper di control plane (`scraper_config.enabled=True`).
    Beat (Fase 6) baca ini tiap refresh -- gak perlu deploy ulang."""
    from cti_core.db.engine import sync_session
    from cti_core.db.models.scraper import ScraperConfig

    registry.get(scraper_id)  # validasi scraper-nya emang kedaftar
    with sync_session() as session:
        cfg = session.get(ScraperConfig, scraper_id)
        if cfg is None:
            session.add(ScraperConfig(scraper_id=scraper_id, enabled=True))
        else:
            cfg.enabled = True
            cfg.paused_reason = None  # alasan pause lama gak relevan lagi setelah nyala ulang
        session.commit()
    typer.echo(f"'{scraper_id}' enabled")


@app.command("disable")
def disable(scraper_id: str, reason: str = typer.Option("", "--reason")) -> None:
    """Matiin scraper di control plane."""
    from cti_core.db.engine import sync_session
    from cti_core.db.models.scraper import ScraperConfig

    registry.get(scraper_id)
    with sync_session() as session:
        cfg = session.get(ScraperConfig, scraper_id)
        if cfg is None:
            session.add(
                ScraperConfig(scraper_id=scraper_id, enabled=False, paused_reason=reason or None)
            )
        else:
            cfg.enabled = False
            cfg.paused_reason = reason or None
        session.commit()
    typer.echo(f"'{scraper_id}' disabled" + (f" ({reason})" if reason else ""))


if __name__ == "__main__":
    app()
