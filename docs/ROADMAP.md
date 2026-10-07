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
| 3 | (kemungkinan tergantikan #19) Tombol "Populate now" di CVE Tracker (semua / hanya yang baru ditambahkan) | keputusan kecil (lihat item) | -- |
| 4 | IOC enrichment + reputasi (VirusTotal, AbuseIPDB, urlscan, Shodan/GreyNoise) | API key tiap layanan, kuota | -- |
| 5 | Feed IOC/CVE keluar (TAXII 2.1 dan/atau CSV/JSON) + API key integrasi | target tooling (Wazuh/Splunk/Fortinet?) | #4 |
| 6 | IOC lifecycle: first/last seen, sightings, expiry/decay | keputusan umur IOC | #4 |
| 7 | Relevansi ke aset sendiri: ancaman x techstack, alert actor yang menarget stack kita | data aset yang rapi | -- |
| 8 | Konektor MISP/OpenCTI (import + export) | instance target | #5 |
| 9 | Dark web monitoring lewat sumber agregator (breach, leak site ransomware, Telegram) -- bukan crawl onion sendiri | budget, daftar domain/email eksekutif, persetujuan internal | -- |
| 10 | Case/RFI workflow (assignment, SLA, status, audit) terhubung ke tiket CVE | alur kerja tim | -- |
| 11 | TLP/PAP konsisten di semua objek + MFA/SSO | kebijakan TLP | #5 |
| 12 | Perbaikan prompt klasifikasi artikel berbasis audit trail (false accept / false reject) | contoh artikel yang salah diklasifikasi | audit trail `raw_enrichment` (sudah jalan 2026-10-05) |
| 13 | **CI di `main` merah** (3 job), jadi job Deploy belum pernah jalan (5 run, semua `skipped`) -- **CI hijau di `main` terbukti 2026-10-07 (run #23); Deploy terpicu pertama kali (run #8) tapi `cancelled` setelah 10m25s, penyebab belum diketahui** | -- | -- |
| 14 | Logo hilang di export Excel CVE Tracker (Pillow belum jadi dependency) -- **kode + test selesai 2026-10-07, smoke build image di CI belum** | -- | -- |
| 15 | Pakai `published_at` di UI/API/dashboard + samakan format tanggal export | keputusan format kolom Acknowledged | backfill `published_at` di produksi |
| 16 | Dashboard CVE: SLA per severity (ganti rating ambang tetap) | target SLA ack/remediasi per severity | -- |
| 17 | Dashboard CVE: panel backlog/aging, KEV/EPSS, produk paling sering terdampak | pilihan panel | -- |
| 18 | Validasi isian ticket CVE + keputusan model ticket (1 ticket per CVE vs satu ticket banyak CVE) | daftar nilai baku, keputusan model | -- |
| 19 | **Katalog tech dari mirror CVE + Monitor** (arah baru 2026-10-07, menggantikan rencana alias/fase 2-3; kolom `aliases` dibuang): mirror semua CVE (retensi tahun kalender) -> katalog vendor+produk -> tab All Tech / Monitored Tech -> tab CVEs hanya tech yang di-monitor. **Desain disepakati, belum ada kode untuk bagian barunya**; pencocok bersama `cti_core.tech_match` (tanpa alias) ada di branch, belum di `main`; rancangan di `docs/CVE_TECH_MATCHING.md` 7 | spike data (butuh akses jaringan ke CVE List V5/NVD), konfirmasi 3 hal terbuka (di item) | uji di server dev dulu |

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

> **Kemungkinan tergantikan oleh #19 (arah baru 2026-10-07).** Kalau mirror CVE + tombol Monitor jadi
> dibangun, tech baru yang di-monitor langsung terisi riwayatnya dari mirror, sehingga tombol ini, jendela
> 8 hari, backfill 180 hari, dan masalah pacing MITRE di bawah tidak relevan lagi. Bagian di bawah dibiarkan
> sebagai catatan keadaan sekarang; jangan dikerjakan sebelum #19 diputuskan.

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

## 12. Perbaikan prompt klasifikasi berbasis audit trail

**Diminta**: prompt klasifikasi perlu di-improve karena sebagian artikel yang seharusnya valid jadi tidak
valid (ditolak) dan sebaliknya.
**Keadaan sekarang**: prompt `_PROMPT` di `packages/cti-enrich/src/cti_enrich/stages/classify.py` (disalin
verbatim dari sistem lama, menilai **hanya dari judul**). Sejak 2026-10-05 respons LLM mentah, model, dan
`prompt_version` tersimpan di `raw_enrichment["classify"]` (artikel diterima dan ditolak), jadi kasus salah
bisa dianalisis dan hasil antar revisi prompt dibandingkan. Hanya artikel yang diproses setelah deploy yang
punya data ini. Angka kesalahan sekarang **belum diukur**.
**Titik sentuh**: `classify.py` (`_PROMPT`, `ClassifyResult`), `routers/filtered_articles.py` (daftar
ditolak), `tests/unit/test_llm_json_retry.py`.
**Yang dibutuhkan**: contoh nyata yang salah di dua arah (ditolak padahal relevan, diterima padahal bukan);
keputusan apakah klasifikasi tetap hanya dari judul atau ikut membaca ringkasan/isi (lebih akurat, tapi
tiap artikel butuh fetch teks sebelum klasifikasi, dan itu menggeser urutan stage di `pipeline.py`).
**Langkah**: (1) kumpulkan 30-50 contoh berlabel dari `rejected_articles` dan `articles`; (2) ukur
precision/recall prompt sekarang sebagai baseline; (3) revisi prompt, ukur ulang di set yang sama; (4) rilis
dengan `prompt_version` baru dan pantau rasio tolak harian.
**Selesai bila**: ada set contoh berlabel tersimpan di repo (tests/fixtures), metrik sebelum dan sesudah
tercatat, dan rasio false reject/false accept turun tanpa menaikkan kegagalan JSON.

---

# Tindak lanjut CVE Tracker dan CI (temuan 2026-10-06)

Item 13-18 berasal dari audit workbook Excel `CVE_Tracker_Dashboard.xlsx`, pengerjaan Dashboard CVE
Tracker, perubahan kolom export Excel, dan pembacaan hasil CI di GitHub pada hari yang sama. 13-14 adalah
cacat nyata dengan bukti; 15-18 usulan (belum diminta resmi), urutan = prioritas yang disarankan.
**Sengaja tidak dimasukkan**: impor riwayat Excel 2026 (811 CVE) ke platform, diputuskan tidak
2026-10-06 (dashboard hanya membaca data platform).

## 13. CI di `main` merah, CD otomatis tidak bisa terpicu

**Diminta (usulan)**: bikin CI hijau lagi supaya `deploy.yml` (hanya jalan kalau CI sukses untuk push ke
`main`) benar-benar terpicu.
**Keadaan sekarang**: run CI #11 sampai #16 (2026-10-05 s/d 10-06, termasuk `main` @ `d3f2a04`) semuanya
`failure`. Tiga job merah, tiga sebab berbeda (dibaca dari log GitHub Actions, run #16):
1. `lint`: `ruff format --check .` menolak 2 file, `docs/ADDING_A_SCRAPER.md` dan
   `tests/unit/test_rss_illegal_xml_chars.py` (reproduksi lokal; `ruff format` memperbaikinya).
2. `compose`: `env file .../.env not found`. `docker-compose.yml` memuat `env_file: ${CTI_ENV_FILE:-.env}`,
   sedangkan job hanya punya `docker/stack.env.example` (`.env` tidak ada di git).
3. `test`: 2 test gagal, 2150 lolos, 3 di-skip. (a) `tests/contract/test_golden.py::test_golden_trendmicro`: Chromium
   Playwright tidak terpasang di runner. (b) `tests/integration/test_articles_router_snapshot.py::
   test_article_dedup_groups`: seed memakai `_TODAY = datetime.date(2026, 9, 24)` hard-code, sedangkan
   `services/dedup.py::get_dedup_groups` memakai jendela 7 hari dari `date.today()`, jadi test ini mati
   sejak 2026-10-01 (bom waktu, bukan regresi kode).
Akibatnya kelima run Deploy (#1-#5) berstatus `skipped` (syaratnya CI `success`): job deploy belum pernah
berjalan sekali pun. Job lain (typecheck, web, api-contract, 4 build image, gitleaks) hijau. Upload codecov juga gagal
("Token required") tapi `continue-on-error`, tidak ikut memerahkan job.
**Titik sentuh**: `.github/workflows/ci.yml` (`compose`, `test`), `tests/integration/
test_articles_router_snapshot.py` (`_TODAY`), 2 file yang disebut di atas.
**Yang dibutuhkan**: tidak ada keputusan; untuk (3a) pilih memasang Chromium di job `test`
(`playwright install --with-deps chromium`, menambah beberapa menit) atau men-skip test marker
`playwright` kalau browser tidak ada (seperti test Docker yang sudah di-skip otomatis).
**Selesai bila**: CI hijau di `main`, dan Deploy terpicu sekali (otomatis atau `workflow_dispatch`) dan
lolos `deploy.sh` dengan health check. Sampai itu, produksi hanya bisa di-update manual (`make deploy`, atau Actions > Deploy > Run workflow).
**Status 2026-10-07**: keempat penyebab diperbaiki, masing-masing direproduksi lalu dibuktikan di lokal:
1. `lint`: `ruff format` pada 2 file (`ruff format --check .` bersih, 574 file).
2. `compose`: step menyetel `CTI_ENV_FILE: .env.example` (mekanisme yang sudah didokumentasikan di kepala
   `docker-compose.yml`); `docker compose config -q` lolos untuk profil default dan `app`.
3a. `test`: step `uv run playwright install --with-deps chromium` sebelum pytest, lewat playwright di venv
   supaya revisi Chromium sama dengan `uv.lock` (1.63.0 minta revisi 1243; gagal lokal dengan penyebab yang
   sama persis dengan CI karena hanya ada revisi 1194). Isi test dibuktikan lolos dengan Chromium asli.
3b. `test_article_dedup_groups` seed dengan `date.today()`; versi lama gagal dan versi baru lolos pada
   Postgres 16 lokal (8/8 snapshot lolos). `_TODAY` pinned sengaja dipertahankan untuk test yang snapshot-nya
   memuat `week`/`month`.
**Belum terbukti**: CI penuh hijau (baru ada setelah PR dibuat; CI hanya jalan pada `pull_request` dan push ke
`main`), dan Deploy yang terpicu pertama kali di runner prod. Langkah `playwright install --with-deps` belum
dijalankan di runner GitHub (sandbox pengembangan tidak boleh memasang browser); `docker/api.Dockerfile` dan
`docker/worker.Dockerfile` memakai perintah yang sama lewat `uv tool run`.
**Hasil setelah PR #11 di-merge (2026-10-07)**: CI di `main` @ `35e6def` hijau (run #23, semua job). Deploy
**terpicu pertama kali** (run #8, `workflow_run` dari CI itu) dan berjalan di runner self-hosted, tetapi berakhir
`cancelled` setelah 10m25s. Bukan timeout (`timeout-minutes: 45`) dan bukan digantikan run lain
(`cancel-in-progress: false`); log job 404 dari GitHub API, jadi penyebabnya tidak bisa dibaca dari sini
(kemungkinan dibatalkan manual atau runner terputus -- belum dikonfirmasi). Yang tersisa dari "Selesai bila":
satu Deploy yang lolos `deploy.sh` dengan health check. **Sesudah deploy yang terputus, cek keadaan host
prod**: `docker compose ps`, tag image `:prev` vs terbaru, dan `alembic current` (apakah `migrate` sempat jalan).
**Ditemukan saat PR #11 dijalankan di CI (2026-10-07), ikut diperbaiki di PR yang sama karena memblokir "CI hijau"**:
`tests/unit/test_ioc_extractor.py::test_domain_defanged_regex_does_not_catastrophically_backtrack` merah di
runner GitHub (satu-satunya kegagalan dari 2240 test; dua test yang diperbaiki di atas lolos, jadi langkah
`playwright install` terbukti jalan). Penyebab: ambang alarm 5 detik untuk 2000 pengulangan, padahal
`_RE_DOMAIN_DEFANGED` (`{0,10}`) berbiaya LINEAR yang besar (±0,45 ms per karakter; 1,3 s / 2,7 s / 5,4 s untuk
500 / 1000 / 2000 pengulangan di mesin dev, ±5 s di runner), jadi lolos-gagalnya mengikuti kecepatan runner, bukan
ReDoS (run #16 lolos tipis). Ambang dinaikkan ke 60 detik; regex tak terbatas (`*`) tumbuh eksponensial (x16
tiap +4 pengulangan) sehingga tetap tertangkap (disimulasikan: gagal tepat di detik ke-60). Tidak ada perubahan
pada regex produksi.
**Temuan yang BELUM dikerjakan**: biaya ±0,45 ms per karakter itu sendiri nyata di produksi -- `extract_iocs()`
pada satu artikel ±12KB makan ±5 detik CPU sinkron di stage enrichment. Bukan ReDoS dan bukan bagian #13; kalau
mau dioptimalkan, titiknya `_RE_DOMAIN_DEFANGED` (mis. saringan awal sebelum regex dijalankan), dengan korpus
`tests/unit/test_ioc_extractor.py` sebagai pengaman byte-identik.

## 14. Logo hilang di export Excel CVE Tracker

**Diminta (usulan)**: file hasil `GET /api/cve/export` membawa logo di kiri atas seperti template.
**Keadaan sekarang**: template `apps/api/src/cti_api/templates/CVE_Tracker_template.xlsx` berisi logo
(`xl/media/image1.png`), tapi hasil export tidak: openpyxl membuang gambar kalau Pillow tidak terpasang,
dan `pillow` tidak ada di `uv.lock` (jadi tidak ada di image API juga). Reproduksi: memuat lalu menyimpan
template asli dengan openpyxl di venv proyek menghasilkan zip tanpa `xl/media/*`. Sudah begitu sebelum
perubahan kolom export 2026-10-06.
**Titik sentuh**: `apps/api/pyproject.toml` (+ `uv.lock`), `services/cve_export.py`,
`tests/integration/test_cve_export_service.py`.
**Yang dibutuhkan**: tidak ada.
**Selesai bila**: `pillow` jadi dependency `cti-api`, image API tetap lolos smoke CI, dan satu test
memastikan workbook hasil export memuat 1 gambar.
**Status 2026-10-07**: `pillow>=10.0` ditambahkan (`uv.lock`: pillow 12.3.0, wheel manylinux saja),
`test_export_keeps_template_logo` ditambahkan (gagal tanpa pillow, lolos dengan pillow). Yang belum
terbukti: job `docker` di CI membangun image API. `uv sync --frozen --no-dev --no-editable --package cti-api`
(langkah stage builder) sudah dicek terpisah dan memasang pillow, tapi `docker build` penuh belum jalan
karena registry `ghcr.io` tidak terjangkau dari sesi pengembangan.

## 15. Pakai `published_at` di UI/API/dashboard + samakan format tanggal

**Diminta (usulan)**: jam publish MITRE (`cve_tracker.published_at`, ditambah 2026-10-06 untuk export)
dipakai juga di tempat lain, dan format tanggal export seragam.
**Keadaan sekarang**: `CveOut` (`schemas/cve.py`) belum mengekspos `published_at`; tab Ticket
(`cve-ticket-tab.tsx`, `reportedDateVal = fmtDt(cve.published)`) menampilkan "CVE Reported Date" tanpa
jam; MTTD di dashboard dihitung dalam **hari** (`detected_on` - `published`) karena `published` tanpa jam
(`services/cve_dashboard.py`). Di export, kolom "Date Acknowledged by CTI Team" masih
`YYYY-MM-DD HH:MM:SS`, beda dari dua kolom di sebelahnya (`HH:MM DD-MM-YYYY`).
**Titik sentuh**: `schemas/cve.py`, `routers/cve.py` (`_serialize`), `cve-ticket-tab.tsx`,
`services/cve_dashboard.py`, `cve-dashboard-view.tsx` (teks definisi MTTD), `services/cve_export.py`.
**Yang dibutuhkan**: `tools/ops/backfill_cve_published_at.py --apply` sudah dijalankan di produksi
(tanpa itu CVE lama tidak punya jam); keputusan apakah kolom Acknowledged ikut `HH:MM DD-MM-YYYY`.
**Selesai bila**: tab Ticket menampilkan jam publish, MTTD tampil dalam jam untuk CVE yang punya
`published_at` (dan jatuh ke hari untuk yang belum, dengan `n` terpisah supaya cakupannya kelihatan),
kontrak API diregenerasi (`export_openapi` + `gen:api`), dan format kolom export konsisten.

## 16. Dashboard CVE: SLA per severity

**Diminta (usulan)**: rating di dashboard berdasarkan target SLA per severity, bukan ambang tetap.
**Keadaan sekarang**: rating (Excellent/Good/Fair/Needs improvement) memakai ambang dari sheet Excel lama
untuk rata-rata MTTA (<=1 / <=7 / <=14 hari) dan sama untuk semua severity
(`apps/web/src/lib/cve/dashboard.ts::ratingForMtta`): CRITICAL dengan MTTA 10 hari dan LOW dengan 10 hari
dinilai sama ("Fair"). Rata-rata juga mudah tertarik outlier; median dan p90 sudah dihitung tapi belum
dipakai untuk menilai.
**Titik sentuh**: `dashboard.ts`, `cve-dashboard-view.tsx`, `services/cve_dashboard.py` (hitung pelanggaran
di server, bukan di browser).
**Yang dibutuhkan**: target per severity untuk acknowledge dan remediasi (hari kalender atau hari kerja,
per client atau global), dan metrik yang dinilai (mean, median, atau persentase CVE dalam SLA).
**Selesai bila**: dashboard menampilkan jumlah/persen CVE yang melanggar SLA per severity dan daftar CVE
yang sedang melewati batas, dengan target tersimpan sebagai konfigurasi (bukan konstanta di kode).

## 17. Dashboard CVE: panel tambahan

**Diminta (usulan)**: panel yang tidak ada di Excel lama tapi datanya sudah ada di platform.
**Keadaan sekarang** (angka dari workbook Excel 2026, 811 CVE, bukan dari DB platform): 511 CVE sudah
di-acknowledge tapi status remediation kosong dan 147 belum di-acknowledge (backlog yang sekarang hanya
terlihat sebagai bucket "Awaiting status" dan "Unacknowledged"); produk paling sering muncul n8n 62,
Splunk Enterprise 60, wazuh 43, suricata 42. Platform menyimpan `cisa_kev`, `epss_score`, dan
`active_exploitation` per CVE (`db/models/cve.py`) yang belum dipakai di dashboard.
**Usulan panel**: (a) aging backlog (CVE tanpa status > N hari, dikelompokkan per severity); (b) CVE
dengan KEV/EPSS tinggi yang belum remediasi; (c) produk/tech paling sering terdampak.
**Titik sentuh**: `services/cve_dashboard.py` (`DashRow` perlu kolom tambahan),
`repositories/cve.py::list_dashboard_rows`, `cve-dashboard-view.tsx`.
**Yang dibutuhkan**: pilihan panel yang berguna dan ambang "terlalu lama" untuk aging.
**Selesai bila**: tiap panel punya test di `tests/unit/test_cve_dashboard.py` dan satu test integrasi yang
mengunci scope client/techstack seperti panel yang sudah ada.

## 18. Validasi isian ticket CVE + model ticket

**Diminta (usulan)**: nilai ticket dibatasi ke daftar baku, dan diputuskan apakah satu ticket boleh
menaungi banyak CVE.
**Keadaan sekarang**: `remediation_status`, `risk_acceptance`, dan `active_exploitation` adalah "soft
enum" tanpa CHECK maupun validasi API (`CveTicketBody` semuanya `str`); dropdown UI memakai
Open/In Progress/Resolved/Risk Accepted/Closed. Dashboard menyerap vocab legenda Excel lewat
`_STATUS_ALIASES` (`services/cve_dashboard.py`) supaya nilai legacy tidak diam-diam salah bucket. Di
workbook Excel akar masalahnya terlihat: dropdown status hanya menutup beberapa baris (daftarnya memuat
"Not Applicable" dobel dan tanpa "Completed"), ada 4 baris berstatus "Closed" di luar legenda, dan 657 dari
811 status kosong. Model: Excel memakai 600 ticket untuk 811 CVE (maks 32 CVE dalam satu ticket, mis. satu
patch Splunk), platform satu `CveTicket` per `(cve_id, client_id)` (docstring `CveTicket`).
**Titik sentuh**: `schemas/cve.py::CveTicketBody`, `routers/cve.py` (`PUT /{cve_id}/ticket`),
`cve-ticket-tab.tsx`, `cve-ticketing-view.tsx`, `db/models/cve.py::CveTicket`.
**Yang dibutuhkan**: daftar nilai baku (termasuk apakah "Not Applicable" dan "Completed" masuk), dan
keputusan model: tetap 1 ticket per CVE, atau izinkan ticket menaungi banyak CVE (perubahan skema +
export + dashboard).
**Selesai bila**: `PUT /ticket` menolak nilai di luar daftar dengan 422 (nilai lama dimigrasi atau
dipetakan), UI dan dashboard memakai satu daftar yang sama, dan keputusan model ticket tertulis di
docstring `CveTicket`.

## 19. Katalog tech dari mirror CVE + Monitor

> **Arah berubah 2026-10-07 (diskusi dengan user).** Rencana lama (kolom `aliases` + katalog yang dikurasi
> tangan + query CPE) tidak dilanjutkan sebagai jalur utama: alias manual per tech tidak skala, dan akar
> masalahnya (nama bebas dicocokkan sebagai teks) tetap ada. Desain di bawah menggantikan fase 2 dan 3 di
> `docs/CVE_TECH_MATCHING.md` 7.1. **Belum ada kode untuk bagian barunya**; yang sudah ada dicatat di
> "Keadaan sekarang".

**Diminta (2026-10-07)**: kolom Tech di CVE Tracker tidak boleh salah-cocok lagi, dan daftar techstack
berhenti jadi "ketik nama manual". Latar belakang, akar masalah, dan solusi 0.2.1:
`docs/CVE_TECH_MATCHING.md`.

**Keadaan sekarang** (alur lengkap CVE Tracker: `docs/CVE_TRACKER_FLOW.md`; fakta dari repo/produksi, bukan
tebakan): `techstack_entries.name` teks bebas, input
UI "Tech name..." tanpa validasi, dan nama itu juga **kunci join** ke `cve_tracker.tech` (`get_risk_context`).
Tujuh pencocok dengan aturan berbeda memakainya (NVD `keywordSearch`; Tenable; gate `new_cve`;
`score.py` `related_tech_status`; `score.py` `check_tech_stack`; `cve_priority.in_tech_stack`; laporan Top CVE
`applicable_to_stack`). Di produksi, 55
dari 118 baris tracker yang bisa diverifikasi salah. `new_cve` mencari per nama tech tiap jam (34 request ke
NVD, mencari kata di deskripsi), jendela 8 hari, dan satu panggilan MITRE per kandidat (batas 60/menit).
**Yang sudah ada di branch `nameless/roadmap-runners` (belum di `main`)**: `cti_core.tech_match` (satu
definisi "cocok": kata utuh, angka versi menempel diterima, huruf menempel ditolak, istilah < 2 karakter tak
pernah cocok) dipakai pencocok 2-6 dan penilai `reconcile_cve_tech`. **Kolom `techstack_entries.aliases`,
migrasi, seed, dan reference data `techstack_aliases` dibuang (keputusan user 2026-10-07)**; tidak ada migrasi
baru. Efek yang terlihat di produksi bila di-merge: alert `tech_stack` dan flag `in_tech_stack` tidak lagi
cocok lewat substring (`go` ~ `google`).

### Desain (disepakati 2026-10-07)

**Alur**: tarik semua CVE (2025 sampai sekarang) ke DB sendiri -> dari data itu keluar **katalog tech**
(vendor + produk) -> menu techstack punya dua tab, **All Tech** (katalog, cari lalu klik **Monitor**) dan
**Monitored Tech** (per client) -> CVE baru dicocokkan lewat **identitas produk dari data CVE**, bukan
lewat teks nama -> tab **CVEs** hanya menampilkan CVE untuk tech yang di-monitor.

**Lapisan data (umur berbeda, ini inti desainnya)**

| Lapisan | Isi | Siklus hidup |
|---|---|---|
| Mirror CVE (baru) | semua CVE: id, tanggal publish/ubah, ringkasan, CVSS, produk terdampak (teks, seperti kolom Affected sekarang) | **habis dibuang retensi** |
| Katalog tech (baru) | vendor + produk ternormalisasi, nama tampilan, `first_seen`, `last_cve_at`, jumlah CVE | **permanen**; baris yang di-monitor tidak pernah dihapus |
| Monitored tech (`techstack_entries`) | per client; menunjuk ke katalog (kolom nullable untuk "custom"); `exposure`, `hosting_type`, flag aktif | permanen |
| `cve_tracker` (sudah ada) | CVE per client untuk tech yang di-monitor, plus ticket/ACK | **permanen**, tanpa FK cascade ke mirror |

- **CVE yang cocok dengan tech di-monitor dipromosikan ke `cve_tracker` saat ingest** (disalin, bukan
  di-join saat query), jadi ticket, export Excel, dan dashboard CVE tidak terpengaruh retensi.
- **Katalog bukan turunan sesaat dari mirror**: tanpa ini produk yang CVE-nya hanya ada di 2025 hilang dari
  katalog di 2027 padahal masih di-monitor.
- `name` tetap label tampilan dan kunci join (`cve_tracker.tech`), jadi ticket dan riwayat tidak putus.

**Retensi**: tahun kalender. Simpan tahun berjalan dan tahun sebelumnya; mulai 1 Januari tahun N, semua CVE
terbitan N-2 dibuang (di 2026 mirror berisi 2025 dan 2026; di 2027 CVE 2025 dibuang). Job harian di queue
`maintenance`, mencatat jumlah yang dibuang di log, dan tidak menyentuh `cve_tracker`.

**Tab dan perilaku**
- **All Tech**: katalog global, pencarian dulu (autocomplete; bukan daftar yang di-scroll), aksi Monitor.
  Produk yang belum ada di katalog boleh ditambah sebagai **custom**, bertanda belum terverifikasi.
- **Monitored Tech**: per client. Tech yang di-monitor **selalu** di-enrich seperti yang sudah ada sekarang
  (skor/risk exposure+hosting, KEV, EPSS, ticket); tidak ada enrichment baru di versi pertama.
- **Tidak di-monitor = disembunyikan** (flag aktif; dashboard sudah punya scope "techstack aktif"). Ticket
  tidak pernah ikut hilang.
- **CVEs**: hanya CVE untuk tech yang di-monitor. **CVE DB** (tab baru, baca-saja): menjelajah semua CVE di
  mirror (terbatas sedalam retensi), dan dari satu CVE bisa klik produk terdampaknya lalu Monitor. Butuh
  index (tanggal, severity, produk).
- **Notifikasi: sudah dibangun terpisah dari #19 (2026-10-07, branch `nameless/roadmap-runners`).** Keputusan
  user: Telegram saja, semua CVE baru untuk tech yang di-monitor, satu ringkasan per run (per client),
  dibangun sekarang di sink yang ada. Premis awalnya (sudah ada alert per CVE baru) ternyata salah; sebelum
  ini hanya ada alert artikel, laporan Top CVE, alert PoC, dan draft email manual. Titik panggilnya (baris
  `cve_tracker` baru dibuat) tetap sama saat pipeline diganti mirror -> promosi. Rinci: `docs/CVE_TRACKER_FLOW.md`
  7. Sisa: laporan/alert lama (artikel, Top CVE) masih memakai nama techstack gabungan semua client.

**Dampak ke item lain**: #3 ("Populate now") **hilang** -- tech baru yang di-monitor langsung terisi dari
mirror (sedalam retensi; riwayat sebelum 2025 sudah ada di tracker dari migrasi Mongo), jadi jendela 8 hari,
backfill 180 hari, dan pacing MITRE tidak relevan lagi. #7 dapat dasar relevansi berbasis versi bila range
versi disimpan. `new_cve` berubah dari "cari per nama" jadi "ambil semua CVE baru/berubah sekali per jam,
proyeksikan ke tech yang di-monitor".

**Pencocok nama tech sebenarnya ada tujuh, bukan enam** (`reports/cve_record.py::applicable_to_stack` tidak
tercatat sebelumnya dan tidak disentuh fase 1; lihat `docs/CVE_TRACKER_FLOW.md` 9).

**Pencocok teks tetap dibutuhkan** untuk artikel dan tweet (tidak punya CPE): `cti_core.tech_match` (di
branch) dipertahankan; istilahnya kelak diturunkan dari katalog.

**Rancangan teknis lengkap (tabel, resolver, ingest, pencocokan, retensi, API/UI, migrasi, irisan PR)**:
`docs/CVE_CATALOG_DESIGN.md`. **Irisan 1 (resolver murni `cti_core.catalog_resolve` + 58 tes) dan irisan 2
(skema + model + repositori katalog/mirror/target, revisi `b7e3d9a1c5f2`, 21 tes Postgres), dan irisan 3
(ingest `cve.mirror_sync` + retensi + skrip backfill, flag `CVE_MIRROR__ENABLED` default mati) selesai
di branch**; irisan 4-7 (promosi, API, UI, cutover) belum. Keputusan 2026-10-07: picker
menyembunyikan keluarga ber-1 CVE (pencarian tetap menampilkan semuanya).

### Fase

1. **Spike pengukuran** -- **dijalankan di data penuh 2026-10-07 (117.220 CVE); hasil dan implikasi di `docs/CVE_TECH_MATCHING.md` 7.1.3, laporan di `docs/spikes/`; perlu dijalankan ulang dengan skrip yang sudah diperbaiki dan `--since` = tanggal `new_cve` mulai berjalan**: `tools/ops/spike_cve_catalog.py` (stdlib saja; cara pakai di docstring dan `docs/CVE_TECH_MATCHING.md` 7.1.2). Hanya baca, tidak mengubah produk: tarik CVE 2025 sampai sekarang, hitung produk
   (vendor, produk) unik, persentase sampah (`n/a`, nama repo, string versi), duplikasi ejaan, dan berapa dari
   34 tech produksi ketemu dengan bersih. Sekaligus jadi angka recall (`docs/CVE_TECH_MATCHING.md` 7.2.1).
   Hasilnya menentukan seberapa berat normalisasi katalog -- risiko terbesar desain ini.
2. **Mirror + katalog (baca-saja)**: skema, ingest, normalisasi otomatis, job retensi, tab CVE DB.
3. **Monitor**: tab All Tech / Monitored Tech, `techstack_entries` menunjuk ke katalog, validasi API,
   regenerasi `docs/openapi.json` dan `schema.d.ts`. Pemetaan 34 tech lama ke katalog **ditinjau manual**.
4. **Ganti `new_cve`**: projeksi mirror -> tracker. **Mode bayangan dulu** (jalan berdampingan dengan
   `new_cve` lama beberapa hari, bandingkan CVE yang hanya ditemukan satu pihak), baru dialihkan.
5. **Merge produk oleh admin** (gabung produk A ke B di katalog): menyusul setelah terlihat seberapa
   berantakan hasil normalisasi otomatis.

Semuanya diuji di **server dev dulu**, baru produksi.

### Terbuka (butuh konfirmasi user)
- **Sumber data**: CVE List V5 sebagai utama; spike mendukungnya (ADP menyelamatkan hanya 0,1% CVE dan CPE
  hanya ada di 7,5% data CNA, jadi NVD/CPE tidak bisa jadi sumber identitas; NVD tetap berguna sebagai
  pelengkap untuk CVSS/KEV). Menunggu konfirmasi user.
- **Unit yang di-monitor: DIPUTUSKAN (user 2026-10-07) dua tingkat, vendor dan keluarga produk.** 9 dari 34
  tech produksi bertipe "satu vendor, banyak produk" (fortinet 311 CVE, splunk 182, juniper 168, palo alto
  150, ...). Satu entri Monitor boleh punya banyak target (lihat `docs/CVE_CATALOG_DESIGN.md` 3.4).
- **Spike ulang: setengah selesai.** Dijalankan ulang dengan skrip yang sudah diperbaiki (angka identitas dan
  cakupan sudah benar, laporan v2). **Recall belum terpisah**: `--since 2025-01-01` dan `tracker.csv` (73
  baris; produksi 125 saat `reconcile`) sama dengan sebelumnya. Perlu `--since` = tanggal `new_cve` mulai
  berjalan dan `tracker.csv` dari DB yang sama; konfirmasi DB mana / sudah dibersihkan?
- **Tanggal untuk retensi dan jendela mirror**: usulan tanggal publish. Konsekuensinya CVE lama yang baru
  berubah (mis. masuk KEV di 2026 padahal terbit 2023) tidak masuk mirror -- keterbatasan yang sama dengan
  jendela 8 hari sekarang; bisa ditutup dengan mengambil khusus CVE lama yang berubah dan kena tech di-monitor.
- **Versi terdampak: keputusan user 2026-10-07 = ikut yang sudah ada.** Tidak ada penyimpanan range versi
  terstruktur baru; kolom Affected tetap teks (`cve_affected.affected`) dan ticket tetap
  `affected_version`/`fixed_version` isian analis. Relevansi berbasis versi (#7) tidak dikerjakan di #19
  (usulan range terstruktur dibatalkan, bukan ditunda).
- **Pencocok ketujuh** (`applicable_to_stack`, laporan Top CVE) belum disatukan: tesnya mengunci `c++` ~
  `c++ inc`. Putuskan: ubah tesnya (istilah < 2 karakter tak pernah cocok) atau beri pengecualian.

**Titik sentuh (perkiraan)**: model + migrasi Alembic baru (mirror, katalog, `techstack_entries.catalog_id`;
dicek `test_migrations_match_models`), job ingest dan retensi di `apps/worker` (queue `maintenance`),
`feeds/new_cve.py`, `routers/techstack.py` + `schemas/techstack.py` (+ openapi/`schema.d.ts`),
`apps/web/src/components/cve/techstack-panel.tsx` + tab CVE DB, `routers/cve.py`, `services/cve_priority.py`,
`cti_enrich/stages/score.py`, `cti_scraper/reference_data.py`, `tools/ops/reconcile_cve_tech.py`.

**Selesai bila**: spike terlapor dengan angka; menekan Monitor pada produk katalog mengisi riwayatnya dari
mirror tanpa menyentuh tech lain; tab CVEs hanya berisi tech di-monitor; di server dev, hasil mode bayangan
vs `new_cve` lama terdokumentasi (CVE yang hanya ditemukan satu pihak, dengan penjelasan); tool
`reconcile_cve_tech` pada data produksi tidak lagi menghasilkan `DELETE` yang disebabkan nama; retensi
terbukti menghapus tahun N-2 tanpa menyentuh `cve_tracker`; angka recall sebelum/sesudah tercatat.
