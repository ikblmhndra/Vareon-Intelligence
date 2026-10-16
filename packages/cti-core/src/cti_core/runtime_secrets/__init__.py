"""Key third-party yang bisa diganti dari halaman admin tanpa restart (ROADMAP #23).

Tiga bagian, masing-masing satu berkas:
  - `registry`: daftar provider dan field yang BOLEH di-override (satu sumber kebenaran, juga
    dipakai daftar scrub secret).
  - `crypto`: enkripsi at-rest field secret (Fernet, master key di `.env`, bukan di DB).
  - `overlay`: `effective_settings()` = `get_settings()` + override dari tabel `runtime_secrets`,
    di-cache per proses beberapa detik. Dibaca konsumen sebagai pengganti `get_settings()`.

Secret level deployment (DB, Redis, JWT/session, OIDC, master key itu sendiri) SENGAJA tidak ada di
registry: butuh DB untuk bisa dibaca, jadi tetap di `.env`.
"""
