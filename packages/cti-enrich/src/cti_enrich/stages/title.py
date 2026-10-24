"""Stage: rapikan judul sebelum dipakai klasifikasi, alert dan tabel `articles`.

Audit UI U27 (2026-10-24): judul dari feed yang meng-escape dua kali tampil mentah di Newsroom
("Marvell, Microsoft &amp; Oracle ..."), dan repo GitHub yang dipantau (Unit42, Blackorbird)
memberi nama berkas sebagai judul ("2026-10-21-phishing-pages-hosted-on-AI-based-site-builders
.txt"), yang lalu masuk ke highlight newsletter. Murni fungsi teks supaya bisa diuji tanpa DB."""

from __future__ import annotations

import html
import re

_FILE_TITLE = re.compile(r"^[\w.\-]+\.(?:txt|md|json|csv|pdf|yar|yara|rules)$", re.IGNORECASE)
_LEADING_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}[-_]")


def normalize_title(title: str) -> str:
    """Decode entity HTML (sampai dua lapis) dan ubah judul berupa nama berkas jadi kalimat:
    tanggal di depan dan ekstensi dibuang, `-`/`_` jadi spasi. Judul biasa hanya di-trim."""
    text = html.unescape(html.unescape(title or "")).strip()
    text = re.sub(r"\s+", " ", text)
    if _FILE_TITLE.match(text):
        stem = text.rsplit(".", 1)[0]
        stem = _LEADING_DATE.sub("", stem)
        words = re.sub(r"[-_]+", " ", stem).strip()
        if words:
            text = words[0].upper() + words[1:]
    return text
