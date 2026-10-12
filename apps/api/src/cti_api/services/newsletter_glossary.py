"""Glosarium untuk ringkasan newsletter berbahasa Indonesia (ROADMAP #22, "Design: Indonesian
content").

Kenapa modul sendiri: model menerjemahkan istilah teknis dengan pilihan kata berbeda dari edisi ke
edisi ("exfiltration" jadi "pencurian data" sekarang, "eksfiltrasi" bulan depan), dan koreksi
analis harus menempel. Daftar di bawah disuntik ke kedua prompt ringkasan
(`services/newsletter.py`); analis yang mengoreksi pilihan kata cukup mengubah SATU baris di sini,
dan `tests/unit/test_newsletter_glossary.py` menjaga bentuknya (tanpa duplikat, tanpa istilah yang
muncul di dua daftar).

Isinya titik mulai, bukan kamus lengkap: pilihan kata awalnya mengikuti contoh teks di mockup yang
disetujui (`docs/mockups/newsletter-redesign.html`). Satu panggilan LLM menghasilkan terjemahan dan
ringkasan sekaligus, jadi daftar ini juga satu-satunya cara menjaga konsistensi antar edisi.
Panjangnya ikut membayar token tiap ringkasan baru (hasilnya di-cache), jadi tambahkan istilah yang
memang berulang, bukan semua yang mungkin muncul."""

from __future__ import annotations

from cti_api.schemas.newsletter import SummaryLanguage

KEEP_AS_WRITTEN: tuple[str, ...] = (
    "CVE identifiers",
    "product and vendor names",
    "threat actor and malware family names",
    "MITRE ATT&CK technique names and IDs",
    "indicators of compromise (IP addresses, domains, URLs, file hashes)",
)
"""Disalin persis dari sumber: tidak diterjemahkan dan tidak ditransliterasi. Ditulis sebagai
kategori (bukan daftar nama) karena nama produk, aktor, dan teknik tidak habis."""

KEEP_IN_ENGLISH: tuple[str, ...] = (
    "ransomware",
    "phishing",
    "spear phishing",
    "malware",
    "botnet",
    "backdoor",
    "spyware",
    "infostealer",
    "trojan",
    "wiper",
    "zero-day",
    "exploit kit",
    "web shell",
    "brute force",
    "credential stuffing",
    "business email compromise (BEC)",
    "KEV (CISA Known Exploited Vulnerabilities)",
)
"""Istilah yang di tim Indonesia lazim dipakai apa adanya; menerjemahkannya justru membingungkan."""

TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("vulnerability", "kerentanan"),
    ("exploitation / to exploit", "eksploitasi / mengeksploitasi"),
    ("actively exploited", "dieksploitasi secara aktif"),
    ("patch / security update", "pembaruan keamanan"),
    ("emergency patch / out-of-band update", "pembaruan darurat"),
    ("remote code execution (RCE)", "eksekusi kode jarak jauh (RCE)"),
    ("privilege escalation", "eskalasi hak akses"),
    ("unauthorized access", "akses tanpa izin"),
    ("initial access", "akses awal"),
    ("lateral movement", "pergerakan lateral"),
    ("data exfiltration", "eksfiltrasi data"),
    ("data breach / data leak", "kebocoran data"),
    ("extortion", "pemerasan"),
    ("double extortion", "pemerasan ganda"),
    ("ransom demand", "permintaan tebusan"),
    ("credential theft", "pencurian kredensial"),
    ("stolen credentials", "kredensial curian"),
    ("account takeover", "pengambilalihan akun"),
    ("multi-factor authentication (MFA)", "autentikasi multifaktor (MFA)"),
    ("managed service provider (MSP)", "penyedia layanan terkelola (MSP)"),
    ("supply chain attack", "serangan rantai pasok"),
    ("open-source", "sumber terbuka"),
    ("threat actor", "pelaku ancaman"),
    ("hackers", "peretas"),
    ("attack surface", "permukaan serangan"),
    ("mass scanning", "pemindaian massal"),
    ("misconfiguration", "kesalahan konfigurasi"),
    ("insider threat", "ancaman orang dalam"),
    ("critical infrastructure", "infrastruktur kritis"),
    ("state-sponsored", "disponsori negara"),
    ("denial of service (DoS)", "penolakan layanan (DoS)"),
    ("command and control (C2)", "komando dan kendali (C2)"),
    ("indicator of compromise (IOC)", "indikator kompromi (IOC)"),
    ("proof of concept (PoC)", "bukti konsep (PoC)"),
    ("incident response", "respons insiden"),
    ("end of life (EOL)", "akhir masa dukungan (EOL)"),
)
"""`(istilah Inggris, padanan Indonesia)`. Sisi Inggris boleh memuat varian dengan ` / ` (satu
padanan untuk beberapa ejaan). Sisi Indonesia selalu berbeda dari sisi Inggris: kalau istilahnya
dibiarkan, tempatnya di `KEEP_IN_ENGLISH`."""

_LANGUAGE_NAMES: dict[str, str] = {"id": "Indonesian (Bahasa Indonesia)", "en": "English"}


def language_instructions(language: SummaryLanguage) -> str:
    """Blok instruksi bahasa untuk prompt ringkasan.

    `id`: perintah menulis Indonesia, apa yang tidak boleh diterjemahkan, dan glosariumnya. `en`:
    hanya perintah menulis Inggris (tanpa glosarium), supaya artikel sumber berbahasa Indonesia
    tidak menarik ringkasan edisi Inggris ke bahasa lain. Kunci JSON (`key_points`, `summary`)
    SELALU Inggris karena itulah yang dibaca kode; hanya nilainya yang berganti bahasa."""
    if language not in _LANGUAGE_NAMES:
        raise ValueError(
            f"unsupported summary language {language!r}; valid: {sorted(_LANGUAGE_NAMES)}"
        )
    name = _LANGUAGE_NAMES[language]
    lines = [
        f'Write the values of "key_points" and "summary" in {name}, in a clear, professional '
        "register for a security leadership audience. Keep the JSON keys exactly as shown."
    ]
    if language == "id":
        lines += [
            "Copy these exactly as they appear in the source; never translate or transliterate "
            "them: " + "; ".join(KEEP_AS_WRITTEN) + ".",
            "Leave these terms in English: " + ", ".join(KEEP_IN_ENGLISH) + ".",
            "Use these Indonesian renderings for recurring terms so the wording stays "
            "consistent between editions:",
            *(f"- {english}: {indonesian}" for english, indonesian in TRANSLATIONS),
        ]
    return "\n".join(lines)
