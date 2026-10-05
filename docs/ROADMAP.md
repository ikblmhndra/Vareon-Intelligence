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
| 4 | IOC enrichment + reputasi (VirusTotal, AbuseIPDB, urlscan, Shodan/GreyNoise) | API key tiap layanan, kuota | -- |
| 5 | Feed IOC/CVE keluar (TAXII 2.1 dan/atau CSV/JSON) + API key integrasi | target tooling (Wazuh/Splunk/Fortinet?) | #4 |
| 6 | IOC lifecycle: first/last seen, sightings, expiry/decay | keputusan umur IOC | #4 |
| 7 | Relevansi ke aset sendiri: ancaman x techstack, alert actor yang menarget stack kita | data aset yang rapi | -- |
| 8 | Konektor MISP/OpenCTI (import + export) | instance target | #5 |
| 9 | Dark web monitoring lewat sumber agregator (breach, leak site ransomware, Telegram) -- bukan crawl onion sendiri | budget, daftar domain/email eksekutif, persetujuan internal | -- |
| 10 | Case/RFI workflow (assignment, SLA, status, audit) terhubung ke tiket CVE | alur kerja tim | -- |
| 11 | TLP/PAP konsisten di semua objek + MFA/SSO | kebijakan TLP | #5 |

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

---

# Gap fitur menuju Threat Intelligence Platform penuh (usulan 2026-10-05)

Item 4-11 di bawah **usulan** (dari audit fitur 2026-10-05), belum diminta resmi: urutan = prioritas
yang disarankan, silakan diubah. Pola gap: platform sudah kuat **mengumpulkan dan membaca** intel
(scraper, enrichment artikel, CVE, ATT&CK, newsletter, exec dashboard), tapi lemah **bertindak dan
terhubung** ke tooling lain. Hasil `git grep` di `apps packages scrapers`: nol hit untuk `taxii`, `misp`,
`opencti`, `virustotal`, `sighting`, `yara|sigma`, `siem|wazuh|splunk`, `api_key`, `sso|oidc|saml|mfa`;
`tlp` hanya di `services/stix.py` dan `services/ta_profile.py`; `webhook` 1 file. Titik sentuh yang sudah
ada: `routers/iocs.py`, `routers/stix.py`, `routers/techstack.py`, `routers/rfi.py`/`pir.py`,
`packages/cti-alerts` (Telegram + email), `db/models/ioc_reference.py` (`IocAllowlistEntry`).

## 4. IOC enrichment + reputasi

**Diminta (usulan)**: tiap IOC diperkaya otomatis (VirusTotal, AbuseIPDB, urlscan, Shodan/GreyNoise)
dengan skor/verdict dan sumbernya tersimpan.
**Keadaan sekarang**: IOC diekstrak dari artikel (`cti-enrich`), belum ada enrichment eksternal.
**Yang dibutuhkan**: API key + kuota tiap layanan (simpan lewat mekanisme secret yang sama dengan
`docs/SECRETS_ROTATION.md`), keputusan IOC mana yang di-enrich (semua vs hanya yang terkait CVE/actor
prioritas) supaya kuota tidak habis.
**Selesai bila**: detail IOC menampilkan verdict + tautan sumber, hasil di-cache, rate limit dihormati,
kegagalan satu layanan tidak menggagalkan yang lain.

## 5. Feed keluar + API key integrasi

**Diminta (usulan)**: endpoint TAXII 2.1 dan/atau CSV/JSON dengan filter TLP, confidence, dan umur IOC,
diakses lewat API key per service (bukan login UI), supaya Wazuh/Splunk/Fortinet menarik IOC + CVE otomatis.
**Keadaan sekarang**: `services/stix.py` sudah membangun bundle STIX; belum ada TAXII, belum ada API key
(auth hanya JWT user).
**Yang dibutuhkan**: tooling target + format yang diminta, kebijakan TLP (#11), keputusan scope key
(per client).
**Selesai bila**: satu tooling nyata berhasil menarik feed memakai key, key bisa dicabut, tiap tarikan
tercatat di audit log, dan hasilnya ter-scope `client_id`.

## 6. IOC lifecycle

**Diminta (usulan)**: first/last seen, hitungan sighting, expiry atau decay, dan false-positive/allowlist.
**Keadaan sekarang**: allowlist sudah ada (`IocAllowlistEntry`); first/last seen, sighting, dan expiry
**belum dicek ada/tidaknya** -- langkah pertama item ini membuktikannya di skema `iocs`.
**Yang dibutuhkan**: keputusan umur IOC per tipe (IP vs hash vs domain).
**Selesai bila**: IOC kedaluwarsa otomatis keluar dari feed (#5) tanpa dihapus dari riwayat.

## 7. Relevansi ke aset sendiri

**Diminta (usulan)**: hubungkan techstack ke ancaman -- alert "actor X menarget teknologi yang kita pakai",
prioritas CVE berbasis exposure, ringkasan "yang relevan untuk kita" di dashboard.
**Keadaan sekarang**: techstack, risk exposure/hosting multiplier di skor CVE (`routers/cve.py`), dan
profil threat actor sudah ada, tapi belum ada penghubung actor -> techstack dan alert-nya.
**Yang dibutuhkan**: techstack yang rapi dan lengkap (kualitas matching mengikuti kualitas data ini).
**Selesai bila**: penambahan satu techstack memunculkan actor/campaign terkait, dan alert Telegram/email
hanya terkirim untuk yang cocok dengan stack client.

## 8. Konektor MISP / OpenCTI

**Diminta (usulan)**: import dan export dua arah.
**Keadaan sekarang**: belum ada. Bergantung pada #5 (format keluar sudah teruji).
**Yang dibutuhkan**: instance MISP/OpenCTI target, atau konfirmasi tidak perlu.

## 9. Dark web monitoring (lewat sumber agregator)

**Diminta (usulan)**: dark web monitoring dengan empat tujuan: (1) **breach monitoring** domain dan email
eksekutif, (2) bahan **Executive Summary**, (3) **enrich newsroom**, (4) **TA monitoring**. Mencakup juga
niat lama item ini (typosquat/brand, sebutan di paste) sebagai fase lanjutan.
**Keputusan desain (dari diskusi 2026-10-05)**: **bukan crawler onion sendiri**. URL onion cepat berubah
sehingga daftar URL, captcha, dan login forum menjadi beban perawatan terus-menerus; butuh infrastruktur
Tor terisolasi dengan risiko keamanan/hukum (konten ilegal, malware); forum butuh akun yang tidak akan
dibuat atau ditembus captcha-nya. Ambil dari sumber yang sudah mengagregasi, jadi URL yang berubah adalah
urusan mereka.
**Keadaan sekarang**: tabel `ransomware_victims` + `routers/ransomware.py` + panel ransomware di newsroom
sudah ada (ditulis scraper). Telegram baru **keluar** (`packages/cti-alerts/telegram.py` mengirim alert);
monitoring channel Telegram **masuk** belum ada (tidak ditemukan di `scrapers/`). Breach/kredensial bocor:
nol hit di kode.

**Fase**
1. **Breach + leak site ransomware**: HIBP (domain search) atau Intelligence X untuk domain dan email
   eksekutif; sumber leak site ransomware tambahan (mis. API ransomware.live) ke tabel yang sudah ada.
   Menutup tujuan 1 dan sebagian besar 4.
2. **Telegram channel actor** (inbound) + hubungkan ke Executive Summary (2) dan newsroom (3): widget
   "korban baru di sektor kita", "kredensial bocor 30 hari", "actor aktif"; artikel ditautkan ke korban/actor
   yang muncul di leak site.
3. **(opsional, bila budget ada)** layanan dark web komersial (mis. Flare, SpyCloud) sebagai pengganti
   crawl sendiri; paste monitoring dan typosquat domain.

**Yang dibutuhkan**: budget (menentukan HIBP saja yang murah dan hanya breach, atau layanan yang juga
mengcover forum); daftar domain dan email eksekutif yang dipantau; keputusan hukum/kebijakan soal
penyimpanan data kredensial bocor (hash saja atau plaintext; siapa boleh melihat); persetujuan internal.
**Selesai bila**: domain yang dipantau memunculkan alert saat muncul di breach/leak baru (tanpa duplikat),
data ter-scope `client_id`, kegagalan satu sumber tidak menghentikan yang lain, dan Executive Summary
menampilkan ringkasan dari data ini.

## 10. Case/RFI workflow

**Diminta (usulan)**: assignment, SLA, status, dan jejak audit di PIR/RFI, terhubung ke tiket CVE
(sub-view Ticketing).
**Keadaan sekarang**: `routers/pir.py` dan `routers/rfi.py` ada; tiket CVE ada (`cve_tickets`); belum
saling terhubung.
**Yang dibutuhkan**: alur kerja tim (siapa menerima RFI, target SLA).

## 11. TLP/PAP konsisten + MFA/SSO

**Diminta (usulan)**: label TLP/PAP di semua objek dan ditegakkan saat distribusi (#5); MFA/TOTP dan SSO
(OIDC) bila dipakai lintas tim.
**Keadaan sekarang**: TLP hanya di STIX dan profil actor; tidak ada MFA/SSO.
**Yang dibutuhkan**: kebijakan TLP internal, IdP yang dipakai.
