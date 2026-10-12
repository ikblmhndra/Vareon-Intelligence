"""Logo di header newsletter (ROADMAP #22): satu PNG di samping template, dikirim sebagai lampiran
inline (`cid:`) pada draft Graph.

Kenapa lampiran inline, bukan tautan ke domain perusahaan: Outlook memblokir gambar tertaut sampai
pembaca mengizinkannya, dan tautan putus kalau domainnya pindah. Karena itu berkasnya tinggal di
repo (`templates/newsletter_logo.png`) dan HTML merujuknya lewat `cid:`.

Asal berkas: logo merah perusahaan dari
`https://privy.zmidevelopment.com/_ipx/_/images/Privy_Logo_Red.png` (PNG transparan 2115x561,
sekitar 60 KB), dikecilkan ke 211x56 px (2x tinggi tampil 28 px, 9 KB) dengan
`sips --resampleHeight 56`. Untuk menggantinya: skala ulang ke 2x tinggi tampil, tanpa latar, lalu
sesuaikan `width`/`height` di template (dijaga `tests/unit/test_newsletter_logo.py`).

Aturan yang harus dipegang SEMUA tempat yang menampilkan atau mengirim HTML edisi, karena HTML
yang disimpan di tabel `newsletters` tetap berisi `cid:` (persis yang dikirim):
- menampilkan di browser (preview, `GET /{id}/html`): `with_data_uris()`, karena browser tidak
  mengerti `cid:`;
- mengirim (`draft-email`, `resend`): `inline_images_for()` untuk lampirannya.
Ukuran email (guard Gmail) diukur pada versi `cid:`, bukan versi data URI yang lebih besar."""

from __future__ import annotations

import base64
from functools import cache
from pathlib import Path

from cti_alerts.mailer import InlineImage

LOGO_CONTENT_ID = "newsletter-logo"
"""`contentId` lampiran dan nama di `cid:` pada template (template menerimanya sebagai `logo_cid`,
jadi tidak ada dua salinan string ini)."""

LOGO_PATH = Path(__file__).parent.parent / "templates" / "newsletter_logo.png"


@cache
def logo_image() -> InlineImage:
    """Logo sebagai lampiran inline. Dibaca sekali per proses; berkas yang hilang gagal keras di
    pemakaian pertama (dan di test paket), bukan diam-diam menghasilkan email tanpa logo."""
    return InlineImage(
        content_id=LOGO_CONTENT_ID,
        content_type="image/png",
        data=LOGO_PATH.read_bytes(),
        name="logo.png",
    )


def inline_images_for(html: str) -> list[InlineImage]:
    """Lampiran inline yang BENAR-BENAR dirujuk `html` lewat `cid:`.

    Disaring supaya `resend` baris lama (dibuat sebelum template punya logo, tanpa `cid:`) tidak
    menempelkan lampiran yatim yang muncul di daftar lampiran Outlook."""
    image = logo_image()
    return [image] if f"cid:{image.content_id}" in html else []


def with_data_uris(html: str) -> str:
    """HTML yang sama dengan `cid:` diganti data URI, untuk iframe preview dan riwayat. Tanpa
    penggantian ini logo tampil sebagai gambar rusak, karena browser tidak punya lampirannya."""
    for image in inline_images_for(html):
        data = base64.b64encode(image.data).decode("ascii")
        html = html.replace(f"cid:{image.content_id}", f"data:{image.content_type};base64,{data}")
    return html
