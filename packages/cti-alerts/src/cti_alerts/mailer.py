"""SATU mailer Microsoft Graph -- gantiin `_send_newsletter_email()` di
`ScraperNewsWeb/app/routers/newsletter.py:62-119` (dua cabang SMTP/Graph
digabung satu fungsi, dipicu `EMAIL_METHOD` env var), DAN
`_create_graph_draft()` di `cve_email_service.py` lama (logic-nya sama
persis, cuma disalin). Dua-duanya kepake sekarang (`newsletter`+`cve`
router, Fase 7.4 Grup C) -- nama fungsi digeneralisasi dari
`send_newsletter_email` biar gak nyesatin, bukan lagi spesifik newsletter.

**Cuma jalur Microsoft Graph yang diport, SMTP TIDAK** -- keputusan
sadar, bukan kelalaian: `GraphSettings` (Fase 2) udah dibikin duluan
khusus buat ini ("pengiriman email CVE notification"), sementara skema
config baru SAMA SEKALI gak punya `SmtpSettings` -- dan `.env` produksi
yang udah ada isinya cuma kredensial Graph (`GRAPH__*`), gak ada satu
pun `SMTP_*`. Nambah SMTP sekarang berarti bikin config path yang gak
ada bukti kepake, ngelanggar prinsip "SATU cara" yang sama dipakai
`telegram.py` (SATU `send_alert()`, bukan 14 fungsi). Kalau nanti
ternyata SMTP beneran dibutuhkan, itu keputusan terpisah yang butuh
`SmtpSettings` baru di `cti_core.config`, bukan tambal di sini.

Dipakai `cti_api` (router `newsletter`, Fase 7.3 Bagian 4) -- BUKAN
`cti_scraper`/`cti_enrich`, jadi gak kena exit criteria "gak ada import
cti_scraper/cti_enrich dari API" (docs/PROGRESS.md Fase 7). `apps/api`
nambah `cti-alerts` sebagai dependency baru, sama kayak `apps/worker`
udah duluan.

Sinkron (bukan `async def`) -- port apa adanya, kode lama juga manggil
`_send_newsletter_email` via `run_in_executor`/thread pool dari endpoint
FastAPI async, bukan native async HTTP. `httpx.Client` sync dipakai di
sini, bukan `AsyncClient`, konsisten sama itu."""

from __future__ import annotations

import base64
import re
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
import msal
from cti_core.config import GraphSettings
from cti_core.runtime_secrets.overlay import effective_settings


class GraphAuthError(Exception):
    """Gagal dapetin access token dari Azure AD."""


class GraphSendError(Exception):
    """Graph API nolak permintaan kirim/draft email."""


@dataclass(frozen=True)
class InlineImage:
    """Gambar yang dirujuk HTML lewat `<img src="cid:{content_id}">` dan dikirim sebagai lampiran
    inline pada draft yang sama.

    Dipilih daripada tautan ke domain luar karena Outlook memblokir gambar tertaut sampai pembaca
    mengizinkannya, dan tautan putus kalau domainnya pindah. `name` adalah nama berkas yang
    tampil kalau klien email menampilkan daftar lampiran."""

    content_id: str
    content_type: str
    data: bytes
    name: str


def split_addresses(raw: str) -> list[str]:
    """Daftar alamat email dari satu string env (`GRAPH__CC`). Pemisah koma ATAU titik koma
    (`;` = format Outlook; tanpa ini `a@x.com;b@x.com` terkirim sebagai SATU alamat rusak dan
    Graph menolak pembuatan draft). Spasi/baris baru di sekitarnya diabaikan, entri kosong
    dibuang."""
    return [addr.strip() for addr in re.split(r"[;,]", raw) if addr.strip()]


def _inline_attachment(image: InlineImage) -> dict[str, object]:
    """`fileAttachment` Graph untuk satu gambar inline. `contentId` yang dicari klien email saat
    menemukan `cid:` di HTML; tanpa `isInline` Outlook menampilkannya sebagai lampiran biasa dan
    gambarnya tidak muncul di badan pesan."""
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": image.name,
        "contentType": image.content_type,
        "contentBytes": base64.b64encode(image.data).decode("ascii"),
        "contentId": image.content_id,
        "isInline": True,
    }


def create_graph_draft(
    html_content: str,
    subject: str,
    *,
    settings: GraphSettings | None = None,
    inline_images: Sequence[InlineImage] = (),
) -> str:
    """Bikin DRAFT message di mailbox `settings.sender` lewat Graph API
    (`POST /users/{sender}/messages`) -- port apa adanya, kode lama juga
    "draft" bukan "send" beneran (gak ada `/sendMail` call), analis yang
    review+kirim manual dari Outlook. Return Graph message id.

    `inline_images`: gambar yang dirujuk `html_content` lewat `cid:`, dikirim di request yang SAMA
    (Graph menerima `attachments` saat membuat pesan, selama tiap lampiran di bawah ~3 MB; logo
    newsletter beberapa KB). Kosong (default) = payload persis seperti sebelumnya, jadi pemanggil
    lama (email CVE) tidak berubah."""
    settings = settings or effective_settings().graph

    authority = f"https://login.microsoftonline.com/{settings.tenant_id}"
    app = msal.ConfidentialClientApplication(
        settings.client_id, authority=authority, client_credential=settings.client_secret
    )
    resp = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    token = resp.get("access_token")
    if not token:
        raise GraphAuthError(
            f"Gagal dapetin Azure access token: {resp.get('error_description', resp)}"
        )

    cc_list = [{"emailAddress": {"address": addr}} for addr in split_addresses(settings.cc)]
    payload: dict[str, object] = {
        "subject": subject,
        "body": {"contentType": "html", "content": html_content},
        "ccRecipients": cc_list,
    }
    if inline_images:
        payload["attachments"] = [_inline_attachment(image) for image in inline_images]
    resp2 = httpx.post(
        f"https://graph.microsoft.com/v1.0/users/{settings.sender}/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30.0,
    )
    if resp2.status_code != 201:
        raise GraphSendError(f"Graph API error {resp2.status_code}: {resp2.text[:200]}")
    result: dict[str, object] = resp2.json()
    return str(result["id"])
