# Roadmap pasca-cutover

Catatan permintaan yang **belum dikerjakan**, dicatat 2026-09-26 (permintaan user, urutan = urutan
dikerjakan). Bukan janji jadwal: tiap item tinggal butuh input/keputusan yang ditulis di bawahnya.
Yang **sudah** berjalan dan bukan roadmap ada di `docs/PROGRESS.md`; gate cutover di
`docs/CUTOVER_RUNBOOK.md`.

Isi tiap item: **apa** yang diminta, **keadaan sekarang** (fakta dari repo/staging, bukan tebakan),
**titik sentuh** (file), **yang dibutuhkan** sebelum mulai, dan **cara membuktikannya selesai**.

| # | Item | Butuh dari user | Bergantung pada |
|---|---|---|---|
| 1 | Rebranding nama platform + UI (colorplate, typography, animation) -- **SELESAI 2026-10-02, sisa logo SVG** | aset brand | -- |
| 2 | Rebranding template `newsletter_email` dan `cve_notification_email` -- **kode selesai 2026-10-02, verifikasi klien email belum** | (aset yang sama dengan #1) | #1 |
| 3 | Tombol "Populate now" di CVE Tracker (semua / hanya yang baru ditambahkan) | keputusan kecil (lihat item) | -- |

---

## 1. Rebranding nama platform dan UI

> **Status 2026-10-02 -- dikerjakan** (PR #3 dan #4). Nama tampilan **Vareon Intelligence** (satu konstanta
> `apps/web/src/lib/brand.ts` + setelan `platform_name` di `cti_core.config`); tema light dan dark
> (`globals.css`, token terpisah untuk severity, kontras dicek AA); font Google Sans Flex; `prefers-reduced-motion`;
> sidebar, dashboard + peta dunia, semua tab dan dialog utama dicek di staging. Identifier teknis (`cti-platform`,
> `cti_*`, image) sengaja tetap. **Sisa**: logo SVG (header masih huruf "N" + teks), dan `grep` nama lama di
> prompt LLM ("Cyber Threat Intelligence" sebagai istilah umum) sengaja dibiarkan.

**Diminta**: ganti nama platform dan tampilan UI -- *colorplate*, *typography*, *animation* -- sesuai
aset yang akan diberikan user.

**Keadaan sekarang**
- Nama "CTI PLATFORM" ditulis langsung di 9 file, bukan dari satu sumber:
  `apps/web/src/app/layout.tsx` (judul halaman), `apps/web/src/app/login/page.tsx`,
  `apps/web/src/components/app-header.tsx`, `apps/api/src/cti_api/main.py`,
  `apps/api/src/cti_api/services/stix.py`, `apps/api/src/cti_api/templates/newsletter_email.html`,
  `packages/cti-core/src/cti_core/db/repositories/{attack,mitre}.py`, `tools/codemod/run_migration.py`
  (yang terakhir alat migrasi -- abaikan). Perlu dicek juga judul pesan Telegram dan header Excel
  (belum di-grep).
- Warna: token `oklch(...)` di `apps/web/src/app/globals.css` (`--background`, `--foreground`, `--primary`,
  `--accent`, `--radius`, ...). Tema yang tampil sekarang gelap dengan aksen biru/cyan.
- Font: tiga font Google lewat `next/font` di `apps/web/src/app/layout.tsx` -- Rajdhani (isi),
  Share Tech Mono (judul/angka), IBM Plex Mono (data); dipetakan ke `--font-sans/--font-heading/--font-mono`.
- Animasi: belum diinventarisasi (langkah pertama item ini).

**Yang dibutuhkan dari user**: nama final; logo (SVG); palet warna (light dan/atau dark) beserta warna
severity (kritis/tinggi/sedang/rendah -- semantik, jangan ikut berubah tanpa sengaja); font + lisensinya;
pedoman animasi (dan sikap terhadap `prefers-reduced-motion`).

**Usulan desain (untuk diputuskan bersama)**
- Ganti **nama tampilan** saja (UI, email, Telegram, producer STIX). Identifier teknis (`cti-platform`,
  image `cti-*`, nama package `cti_*`, env var) **tetap**: mengganti itu = churn besar tanpa nilai bagi
  pengguna dan memutus tag/volume/rollback yang sudah dilatih.
- Satu sumber nama (setelan `platform_name` di `cti_core.config` untuk backend; satu konstanta untuk web)
  supaya rebrand berikutnya satu tempat.
- Warna severity dipisah dari warna brand di `globals.css`.

**Selesai bila**: semua tab + halaman login + email + pesan Telegram memakai nama/warna/font baru; kontras
teks-latar memenuhi WCAG AA di tema yang dipakai; screenshot tiap tab dilampirkan; `grep` nama lama = kosong
(kecuali identifier teknis yang sengaja tetap).

---

## 2. Rebranding template email

> **Status 2026-10-02 -- kode selesai, verifikasi belum**: `templates/_base_email.html` (Jinja `extends`) dipakai
> kedua email; palet brand, hex saja, font stack cadangan, `platform_name` dari setelan. **Belum**: dikirim lewat
> Graph ke akun uji dan dicek di Outlook desktop/web, Gmail, mobile (kriteria "Selesai bila" di bawah). Catatan:
> preview newsletter di staging masih gagal dengan `500: Expecting value` dari sisi server (diduga konfigurasi LLM
> di `.env`), terpisah dari template ini.

**Diminta**: template `newsletter_email` dan `cve_notification_email` mengikuti hasil item 1.

**Keadaan sekarang**
- File: `apps/api/src/cti_api/templates/newsletter_email.html` (240 baris) dan
  `apps/api/src/cti_api/templates/cve_notification_email.html` (268 baris).
- Warna ditulis **inline** dan ganda di kedua file (mis. `#1976d2`, `#0d1b2a`, `#00e5ff`, `#d32f2f`,
  `#e8ecf0`), tidak memakai token web -- jadi rebrand web tidak otomatis mengubah email.
- Nama ditulis langsung di header/footer newsletter ("Cyber Threat Intelligence", "CTI Platform").
- Ada test yang menyentuh pengiriman (`tests/unit/test_mailer.py`); asersi string brand (kalau ada)
  perlu ikut diperbarui.

**Batasan klien email** (jangan dilanggar saat mengganti gaya):
- CSS inline; tidak ada web font di banyak klien (Outlook desktop) -> tentukan *font stack* cadangan.
- Tidak ada `oklch()`/CSS variable -> pakai hex/rgb.
- Animasi tidak didukung -> item "animation" dari #1 tidak berlaku di email.
- Warna severity harus tetap terbaca (merah/kuning/hijau) di light dan dark mode klien.

**Usulan**: satu *base layout* Jinja (`{% extends %}`) untuk kedua template, agar rebrand berikutnya cukup di
satu tempat (sekarang CSS-nya diduplikasi).

**Bergantung pada**: #1 (palet + nama final).

**Selesai bila**: kedua email terkirim lewat Graph ke akun uji dan terlihat benar di Outlook desktop, Outlook
web, Gmail, dan mobile; tes render lulus.

---

## 3. Tombol "Populate now" di CVE Tracker

**Diminta**: tombol **Populate now** untuk mengisi CVE, dengan pilihan **populate all** atau **hanya
techstack/package yang baru ditambahkan**. Menggantikan teks petunjuk lama di tab kosong.

> **Update 2026-09-30**: bagian "riwayat CVE kosong di hari pertama" untuk data LAMA (yang sudah pernah
> ditrack sebelum cutover) SUDAH BERES lewat `tools/seed/fase10_cve_migrate.py` (migrasi dari dump Mongo,
> langkah 8 di `docs/CUTOVER_RUNBOOK.md`) -- lihat `docs/PROGRESS.md`. Yang TERSISA di item ini murni soal
> techstack/package yang ditambah SETELAH cutover (tidak ada di dump lama), plus keinginan tombol UI-nya.

**Keadaan sekarang** (semua terukur di staging 2026-09-26, kecuali yang ditandai update di atas)
- CVE hanya diisi oleh scraper `new_cve` (tiap jam, bespoke, `scrapers/src/cti_scrapers/feeds/new_cve.py`):
  per techstack ia query NVD (`keywordSearch`) + Tenable, lalu ambil detail dari MITRE. Jendela pencariannya
  **hanya 8 hari terakhir**.
- Akibatnya: techstack **baru** (ditambah setelah cutover, jadi tidak ada di dump migrasi) hanya dapat CVE
  yang terbit dalam 8 hari terakhir sejak ditambahkan -- **riwayat sebelum itu tidak pernah terisi** kecuali
  dipicu manual.
- **Legacy punya ini dan sengaja belum diport**: `POST /api/techstack/backfill-cves` (semua techstack satu
  client), `POST /api/techstack/{id}/backfill-historical` (NVD **180 hari** untuk satu tech), dan saat menambah
  techstack legacy menyalin CVE yang sudah ada + memicu backfill 180 hari. Dicatat di docstring
  `apps/api/src/cti_api/routers/techstack.py` dan `apps/web/src/components/cve/techstack-panel.tsx`.
- Paket: `POST /api/pkg-vuln/packages/{id}/scan` (satu) dan `POST /api/pkg-vuln/scan` (semua) sudah ada.
  Pemindaian paket **tidak terjadwal** (legacy juga tidak: tak ada job Rundeck untuknya); jadi sisi paket cukup
  aksi tombol, bukan scraper.

**Fondasi yang sudah ada**
- Trigger manual `POST /api/scraper/{id}/trigger` (admin + audit log). Task Celery `scrape.run` sekarang
  **hanya** menerima `scraper_id` dan `trigger`, **belum** meneruskan opsi.
- Kerangka opsi per-scraper (`ScraperOption`, `Runner(options=...)`, `--option key=value`) sudah bisa
  menimpa perilaku satu run **tanpa menulis ke DB** -- cocok untuk `scope`/`window_days`.
- `techstack_entries.added_date` dan `created_at` = dasar "baru ditambahkan".

**Yang perlu dibangun**
1. `new_cve`: opsi `scope` (`all` | `recent`) dan `window_days` (default 8; backfill lebih panjang). Untuk
   `recent`: hanya techstack dengan `added_date` sejak tanggal tertentu.
   NVD membatasi satu request ke **120 hari** (batas dokumentasi NVD API 2.0) -> jendela 180 hari harus dipecah.
2. **Pacing MITRE**: token bucket sekarang *tidak menunggu* -- begitu 60/menit habis, `RateLimited` dan run
   berhenti. Backfill besar (ratusan CVE) pasti kena. Perlu menunggu token / mencicil per batch / melanjutkan
   di run berikutnya. Ini juga risiko run biasa bila kandidat > 60 sekali jalan.
3. **Dedup**: `new_cve` sengaja tanpa dedup (MITRE bisa memperbarui skor), jadi tiap run memanggil ulang MITRE
   untuk semua kandidat. Untuk backfill, lewati CVE yang sudah ada dan `cve_modified_date`-nya tak berubah.
4. Task `scrape.run` + endpoint trigger menerima `options` (divalidasi `validate_options`, 422 bila salah,
   seperti PUT config). Endpoint khusus mis. `POST /api/cve/populate {scope, since}` (admin, audit log)
   yang mengembalikan id run.
5. UI: tombol di tab CVE Tracker -> dialog dua pilihan ("Semua techstack" / "Hanya yang baru ditambahkan
   sejak ...") + status run (link ke `/scrapers`); untuk paket, aksi scan yang sudah ada.
6. Test: unit (opsi + jendela), integrasi (trigger dengan opsi), e2e di staging dengan techstack baru.

**Keputusan yang dibutuhkan dari user**
- Berapa hari riwayat untuk techstack baru? (legacy: 180.)
- "Baru ditambahkan" = sejak kapan? (mis. 7 hari terakhir, atau sejak populate terakhir.)
- Siapa yang boleh menekan tombol? (usulan: admin saja, sama seperti trigger scraper.)
- Scan paket otomatis saat paket ditambahkan, atau tetap manual?

**Selesai bila**: menambah techstack baru lalu menekan "hanya yang baru" mengisi riwayatnya tanpa menyentuh
techstack lain; "populate all" pada techstack besar selesai tanpa `rate_limited`; tab kosong menampilkan tombol
ini alih-alih petunjuk.

> Sudah dikerjakan di sesi yang sama dan **bukan** bagian roadmap ini: teks kosong lama ("Run newCveThreat.py")
> diganti; bug techstack bernama multi-kata (`palo alto`, `microsoft 365`, `new relic`, `harmony sase`) yang
> CVE-nya dibuang diam-diam sudah diperbaiki -- lihat `docs/PROGRESS.md`.
