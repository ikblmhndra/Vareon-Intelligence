"""Stage: ringkas teks artikel -- port bagian LSA summarizer dari
`nlp.py:293-309`. Ekstraksi teks udah dipindah ke `fetch_text.py` (stage
terpisah, lihat docstring di sana), jadi stage ini SEKARANG murni "teks
polos masuk, ringkasan keluar" -- pakai `sumy.PlaintextParser`, bukan
`HtmlParser` kayak kode lama (yang HTML-nya udah gak ada di titik ini).

`SENTENCES_COUNT` kode lama = jumlah paragraf hasil parse HTML MENTAH
(`str(parser.document)` -> `"<DOM with N paragraphs>"` -> ambil N) --
angka itu ngikutin struktur DOM seluruh halaman (termasuk nav/footer/iklan),
bukan cuma badan artikel. Di sini dihitung dari teks yang BENERAN mau
diringkas (`text.count("\\n\\n") + 1`, trafilatura mempertahankan jeda
paragraf sebagai baris kosong) -- analog paling deket buat parser baru,
bukan angka baku beda; sama-sama "jumlah paragraf -> jumlah kalimat ringkasan"."""

from __future__ import annotations

from typing import Any

_LANGUAGE = "english"
_nltk_data_checked = False


def _import_nlp() -> Any:
    """Import `nltk`/`sumy` LAZY, bukan di level modul: keduanya cuma ada di
    image yang bawa extra `nlp` (`worker-nlp`) -- `pipeline.py` meng-import
    modul ini, dan test/proses tanpa extra itu (CI `--extra dev`, image `worker`
    ringan) gak boleh gagal cuma karena nge-import pipeline (sama kasusnya
    dengan spaCy di `score._get_nlp()`).

    Dipanggil DI LUAR `try/except` `summarize()`: dependency yang hilang harus
    gagal KERAS di sini, bukan ditelan `except Exception` dan diam-diam jadi
    "ringkasan = teks asli" di produksi."""
    import nltk
    from sumy.nlp.stemmers import Stemmer
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.parsers.plaintext import PlaintextParser
    from sumy.summarizers.lsa import LsaSummarizer
    from sumy.utils import get_stop_words

    return nltk, Stemmer, Tokenizer, PlaintextParser, LsaSummarizer, get_stop_words


def _ensure_nltk_data(nltk: Any) -> None:
    """`sumy`'s tokenizer butuh corpus NLTK `punkt_tab` -- BUKAN dapet dari
    `pip install`/`uv sync` (beda dari `en_core_web_sm` di `cti-enrich`'s
    `nlp` extra, yang bisa dipin lewat URL wheel). Download sekali per
    proses, diam-diam, dan cache hasilnya (`nltk.download` sendiri no-op
    kalau udah ada) -- gak ada langkah manual terpisah yang harus
    didokumentasiin buat dev/image baru."""
    global _nltk_data_checked
    if _nltk_data_checked:
        return
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)
    _nltk_data_checked = True


def summarize(text: str) -> str:
    """String kosong -> string kosong (gak ada yang bisa diringkas). Gagal
    parse/summarize -> balik teks asli apa adanya (stage ini gak boleh jadi
    titik gagal keras buat pipeline; scoring/extract_ttps tetep jalan pakai
    teks penuh kalau ringkasan gagal dibikin)."""
    if not text:
        return ""
    nltk, Stemmer, Tokenizer, PlaintextParser, LsaSummarizer, get_stop_words = _import_nlp()
    try:
        _ensure_nltk_data(nltk)
        parser = PlaintextParser.from_string(text, Tokenizer(_LANGUAGE))
        stemmer = Stemmer(_LANGUAGE)
        summarizer = LsaSummarizer(stemmer)
        summarizer.stop_words = get_stop_words(_LANGUAGE)
        sentences_count = max(1, text.count("\n\n") + 1)
        return " ".join(str(s) for s in summarizer(parser.document, sentences_count))
    except Exception:
        return text


DEK_MAX_CHARS = 600


def make_dek(summary: str, *, max_chars: int = DEK_MAX_CHARS) -> str | None:
    """Potong ringkasan jadi kutipan pendek buat `articles.summary` (5a, 4.5).

    Nilainya kutipan VERBATIM dari teks penerbit, bukan keluaran LLM. Jalur
    gagal `summarize()` mengembalikan SELURUH artikel, jadi tanpa batas ini
    kolom bisa menyimpan puluhan ribu karakter; batas 600 yang menjaganya
    tetap sepanjang snippet. Murni, tanpa import nltk/sumy, jadi jalan di
    semua image dan CI.

    Urutan: rapikan whitespace (kosong -> None); pendek -> apa adanya; potong
    di akhir kalimat terakhir (". ", "! ", "? " di indeks >= 200, tanda baca
    ikut); kalau tidak ada, potong di batas kata + elipsis. Hasil paling
    panjang `max_chars + 1`. Teks tanpa spasi dipotong keras di `max_chars`."""
    s = " ".join(summary.split())
    if not s:
        return None
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars]
    end = max(cut.rfind(m) for m in (". ", "! ", "? "))
    if end >= 200:
        return cut[: end + 1]
    return cut.rsplit(" ", 1)[0] + chr(0x2026)
