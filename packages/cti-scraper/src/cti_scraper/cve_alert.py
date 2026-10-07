"""Ringkasan Telegram untuk CVE BARU di `cve_tracker` -- satu pesan per client per run.

Latar belakang (`docs/CVE_TRACKER_FLOW.md` 7): sebelum ini tidak ada notifikasi otomatis saat CVE
baru masuk tracker; analis harus membuka tab CVEs. Isinya sekarang: setiap baris `cve_tracker` yang
BARU DIBUAT oleh sink `CveItem` (INSERT, bukan update) dikumpulkan sepanjang run
(`session.info`, lihat `sinks._cve_sink`) dan dikirim SEKALI di akhir run oleh `Runner`
(`sinks.finish_run`).

Sengaja:
- **Hanya tech yang di-monitor**: baris tracker memang hanya dibuat untuk (client, tech) di
  `techstack_entries` (gate `new_cve`), jadi tidak ada penyaring tech tambahan di sini.
- **Satu pesan per client per run**, bukan satu pesan per CVE: `new_cve` bisa memasukkan puluhan CVE
  dalam satu run (batas 300), dan satu channel Telegram dipakai semua client. Maksimal `_MAX_ROWS`
  baris, sisanya "dan N lainnya"; nama client selalu ada di judul.
- **Hanya CVE yang terbit <= `MAX_AGE_DAYS` hari**: tanpa ini tech baru, backfill, atau run
  pertama di database yang baru membanjiri channel dengan CVE lama (aturan yang sama dengan
  alert PoC GitHub).
- **CVE yang sudah ditandai false positive** untuk client itu tidak dikirim (baris bisa dibuat ulang
  sesudah `purge-orphaned`).
- **Kegagalan kirim TIDAK menggagalkan ingest** dan tidak dicoba ulang: data CVE lebih penting dari
  alert, dan karena sink sudah commit, run berikutnya melihat baris itu sebagai update (bukan baru).
  Konsekuensinya alert yang gagal terkirim hilang, dan itu dicatat di log (`cve_new_alert_failed`).
"""

from __future__ import annotations

import datetime
import html
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import structlog
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveFalsePositive, CveTracker
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

TOPIC = "cve_new"
"""Kunci di `TELEGRAM__THREAD_IDS`; belum terdaftar -> `UnknownAlertTopic` (ditangkap)."""

MAX_AGE_DAYS = 3
_MAX_ROWS = 10
_SUMMARY_CHARS = 140
_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class NewCve:
    cve_id: str
    tech: str
    severity: str
    score: float | None
    published: datetime.date | None
    summary: str
    link: str


def _short(text: str, limit: int) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1].rstrip() + "…"


_MAX_LINK_CHARS = 300
_TEXT_BUDGET = 3800
"""Batas Telegram 4096 karakter; dikurangi sisa untuk tag HTML dan baris penutup."""


def _render_row(r: NewCve) -> str:
    sev = r.severity.upper() or "N/A"
    score = f" {r.score:.1f}" if r.score else ""
    pub = f", terbit {r.published.isoformat()}" if r.published else ""
    head = f"<b>{html.escape(r.cve_id)}</b> [{html.escape(r.tech)}] {sev}{score}{pub}"
    body = html.escape(_short(r.summary, _SUMMARY_CHARS)) if r.summary else ""
    link = (
        f'\n<a href="{html.escape(r.link, quote=True)}">detail</a>'
        if r.link and len(r.link) <= _MAX_LINK_CHARS
        else ""
    )
    return f"\n{head}\n{body}{link}".rstrip()


def format_summary(client_name: str, rows: Sequence[NewCve]) -> str:
    """Teks HTML untuk satu client. Urut: severity terparah dulu, lalu skor, lalu id. Maksimal
    `_MAX_ROWS` baris DAN muat di `_TEXT_BUDGET` (pesan > 4096 karakter ditolak Telegram, alert
    hilang): baris dikurangi dari bawah sampai muat, sisanya masuk "dan N lainnya"."""
    ordered = sorted(
        rows,
        key=lambda r: (_SEVERITY_ORDER.get(r.severity.upper(), 4), -(r.score or 0.0), r.cve_id),
    )
    title = f"<b>CVE baru untuk tech yang dimonitor</b> -- {html.escape(client_name)} ({len(rows)})"
    rendered = [_render_row(r) for r in ordered[:_MAX_ROWS]]
    while len(rendered) > 1 and len(title) + sum(len(x) for x in rendered) + 80 > _TEXT_BUDGET:
        rendered.pop()
    lines = [title, *rendered]
    if len(rows) > len(rendered):
        lines.append(f"\n... dan {len(rows) - len(rendered)} lainnya (lihat tab CVEs)")
    return "\n".join(lines)


def collect(
    session: Session, pairs: Iterable[tuple[str, str]], *, today: datetime.date
) -> dict[str, list[NewCve]]:
    """`pairs` = (cve_id, client_id) yang dicatat sink -> {nama client: [NewCve]} setelah disaring.

    Dibaca ULANG dari DB, bukan dari item yang dicatat: baris yang di-rollback sesudah dicatat tidak
    ada lagi, dan yang ditandai false positive dibuang.
    """
    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    cutoff = today - datetime.timedelta(days=MAX_AGE_DAYS)

    rows = session.execute(
        select(CveTracker, Client.name)
        .join(Client, Client.client_id == CveTracker.client_id)
        .where(tuple_(CveTracker.cve_id, CveTracker.client_id).in_(wanted))
    ).all()
    fp = {
        (cve_id, client_id)
        for cve_id, client_id in session.execute(
            select(CveFalsePositive.cve_id, CveFalsePositive.client_id).where(
                tuple_(CveFalsePositive.cve_id, CveFalsePositive.client_id).in_(wanted)
            )
        )
    }

    out: dict[str, list[NewCve]] = defaultdict(list)
    for row, client_name in rows:
        if (row.cve_id, row.client_id) in fp:
            continue
        if row.published is None or row.published < cutoff:
            continue  # tanpa tanggal publish = tak bisa dibuktikan baru; jangan menebak
        out[client_name or row.client_id].append(
            NewCve(
                cve_id=row.cve_id,
                tech=row.tech or "",
                severity=row.cve_severity or "",
                score=row.cve_score,
                published=row.published,
                summary=row.summary or "",
                link=row.link or "",
            )
        )
    return dict(out)


def _telegram_sender() -> Callable[[str, str], None]:
    from cti_alerts.telegram import send_alert

    return send_alert


def notify_new_cves(
    session: Session,
    pairs: Iterable[tuple[str, str]],
    *,
    today: datetime.date | None = None,
    send: Callable[[str, str], None] | None = None,
) -> int:
    """Kirim ringkasan; balikin jumlah pesan terkirim. Tidak pernah raise."""
    try:
        by_client = collect(
            session, pairs, today=today or datetime.datetime.now(datetime.UTC).date()
        )
        sender = send if send is not None else _telegram_sender()

        sent = 0
        for client_name in sorted(by_client):
            try:
                sender(TOPIC, format_summary(client_name, by_client[client_name]))
                sent += 1
            except Exception as e:  # satu client gagal tidak menghentikan yang lain
                log.warning(
                    "cve_new_alert_failed",
                    client=client_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
        return sent
    except Exception as e:
        log.warning("cve_new_alert_failed", error=str(e), error_type=type(e).__name__)
        return 0
