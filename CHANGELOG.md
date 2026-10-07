# Changelog

Format ngikutin [Keep a Changelog](https://keepachangelog.com/), versi
ngikutin `pyproject.toml` (root). Baca lewat `GET /api/changelog` (API,
router `changelog.py`) -- parser-nya expect header persis
`## [versi] - tanggal`, jangan ubah formatnya tanpa liat
`apps/api/src/cti_api/routers/changelog.py`.

## [Unreleased] - 2026-10-06

**Saat upgrade dari 0.2.1:**
1. Jalankan migrasi (`up -d` sudah menjalankan service `migrate`): revisi baru `e8c2a4b6d1f3` (kolom
   nullable `cve_tracker.published_at`, aman untuk data lama). Kontrak API hanya bertambah:
   `GET /api/cve/dashboard`.
2. Jalankan sekali `make backfill-published-at` (laporan dulu, lalu `ARGS='--apply'`;
   `docs/SCRAPER_MAINTENANCE.md` 4.H) supaya CVE lama punya jam di kolom "CVE Reported Date" export --
   tanpa itu mereka tampil tanggal saja.
3. **Export Excel CVE Tracker: kolom bergeser satu ke kanan** mulai kolom E (lihat Diubah). Makro atau
   skrip yang membaca file export per posisi kolom harus disesuaikan.

### Ditambah
- **Dashboard CVE Tracker** (sub-view "Dashboard" di `/cve`, endpoint `GET /api/cve/dashboard?year=`):
  pengganti sheet Dashboard di workbook Excel `CVE_Tracker_Dashboard.xlsx`. Isinya KPI, MTTD/MTTA/MTTR
  per severity dan per owner team, tren bulanan per severity (chart + tabel), posisi CVE per tahap, dan
  10 CVE paling lambat. Scope sama dengan tab CVEs (client aktif, techstack aktif, tanpa false positive).
  Tidak butuh migrasi, dan data Excel tidak diimpor. Definisi metrik ada di
  `cti_api.services.cve_dashboard`; beda dari rumus Excel yang disengaja: nol ikut dihitung (plus median,
  p90, dan jumlah data), resolution rate dibagi CVE yang memang butuh tindakan (bukan semua baris), MTTD
  dalam hari (`detected_on` - `published`; di Excel selalu 1 atau 6 jam), MTTR tidak dihitung untuk
  "Not Affected", dan tidak ada batas baris.
- **Jam publish MITRE disimpan** di `cve_tracker.published_at`. `new_cve` dulu memotong
  `cveMetadata.datePublished` jadi tanggal (`published`, tetap ada); sekarang jam lengkapnya ikut
  tersimpan (UTC). Scraper tidak menimpa nilai yang sudah ada dengan kosong.
- **`tools/ops/backfill_cve_published_at.py`**: mengisi `published_at` untuk CVE lama dengan mengambil ulang
  record MITRE. Default laporan saja; `--apply` baru menulis; `--client` membatasi cakupan. Hanya mengisi
  yang kosong, dan tidak menulis kalau tanggal MITRE beda dengan `published` yang tersimpan (dilaporkan
  `MISMATCH`). Dijalankan lewat `make backfill-published-at [ARGS='--apply --client <id>']` (container
  `worker` yang sudah ada, `tools/` di-mount read-only). Playbook: `docs/SCRAPER_MAINTENANCE.md` 4.H.
- **CD otomatis ke produksi**: `.github/workflows/deploy.yml` men-deploy tiap push ke `main` yang lolos
  CI, lewat runner self-hosted di host produksi (host privat, tanpa port masuk). `tools/ops/deploy.sh`
  (juga `make deploy`) melakukan backup Postgres, menandai image berjalan sebagai `:prev`, build,
  `up -d` (migrasi dulu), menunggu sehat, dan rollback otomatis + alarm Telegram bila gagal (tanpa
  `--yes`: downgrade DB tidak pernah otomatis). Setup dan batasan: `docs/CI_CD.md`.

### Diubah
- **Export Excel CVE Tracker (`GET /api/cve/export`)**: kolom baru **Reported by System** tepat di
  sebelah kanan **CVE Reported Date**. Isinya `detected_on`, kapan scraper pertama dapat CVE-nya.
  "CVE Reported Date" sekarang `HH:MM DD-MM-YYYY` (WIB, mis. `20:53 31-08-2026`) dan berisi jam publish
  asli dari MITRE (`published_at`); CVE yang belum punya jamnya tampil tanggal saja (`DD-MM-YYYY`), bukan
  jam tebakan. Sebelumnya kolom "CVE Reported Date" sendiri memakai `detected_on`, jadi dua kolom itu tidak
  bisa dibedakan. Kolom sesudahnya bergeser satu ke kanan (Severity jadi F, Closure Date jadi V).
  Template `CVE_Tracker_template.xlsx` ikut diubah: header tabel, lebar kolom, dan kotak form kanan atas
  (R1:V4) digeser; dropdown sisa di V3/V4 (daftar "On Track, At Risk, ...", tidak dipakai apa pun) dibuang.
  Kolom "Date Acknowledged by CTI Team" tidak berubah (`YYYY-MM-DD HH:MM:SS`).

### Diperbaiki
- **Export CVE Tracker (`GET /api/cve/export`) tidak membawa logo.** Template `.xlsx` punya logo
  (`xl/media/image1.png`, di B1:H4), tetapi openpyxl hanya membaca gambar kalau Pillow terpasang dan
  `pillow` belum jadi dependency `cti-api`, jadi logo hilang tanpa error di file hasil export.
  `pillow` sekarang jadi dependency `cti-api` (`uv.lock` ikut diperbarui) dan ada test regresi di
  `tests/integration/test_cve_export_service.py`.

### Diketahui / belum dikerjakan
- **CI di `main` merah** (`lint`: 2 file belum ter-format; `compose`: `.env` tidak ada di runner; `test`:
  `test_golden_trendmicro` butuh Chromium Playwright dan `test_article_dedup_groups` memakai tanggal
  hard-code), sehingga job Deploy belum pernah jalan. Sampai CI hijau, produksi hanya bisa di-update
  manual (`make deploy`, atau Actions > Deploy > Run workflow). Rinciannya di `docs/ROADMAP.md` #13.
- Usulan lanjutan Dashboard CVE dan validasi ticket: `docs/ROADMAP.md` #15-#18.

## [0.2.1] - 2026-10-06

Perbaikan pemetaan Tech di CVE Tracker. Tidak ada migrasi dan tidak ada perubahan kontrak API.

**Saat upgrade dari 0.2.0:** baris lama di `cve_tracker` yang sudah terlanjur salah (mis. Tech
`mariadb` dengan Affected "Zabbix") **tidak dibersihkan otomatis**. Scraper hanya menulis ulang CVE
yang masih lolos filter baru; CVE yang sekarang ditolak tidak diambil lagi, jadi barisnya tetap ada.
Bersihkan dengan `tools/ops/reconcile_cve_tech.py` (lihat Ditambah): jalankan dulu tanpa `--apply`
dan baca laporannya. Baris yang sudah punya ticket atau status ACK tidak pernah dihapus otomatis.

### Ditambah
- **`tools/ops/reconcile_cve_tech.py`**: menilai ulang baris `cve_tracker` dengan aturan yang sama
  dengan scraper (record MITRE diambil ulang per CVE) lalu `RETAG` ke tech lain milik client yang
  cocok, `DELETE` yang tidak cocok sama sekali, atau `REVIEW` kalau sudah punya ticket/ACK. Default
  laporan saja; `--apply` baru menulis; `--client` membatasi cakupan. Playbook: `docs/SCRAPER_MAINTENANCE.md` 4.G.

### Diperbaiki
- **CVE Tracker: kolom Tech tidak cocok dengan Affected.** `keywordSearch` NVD mencocokkan kata di
  deskripsi mana pun, jadi CVE yang cuma menyebut sebuah teknologi sambil lalu ikut tercatat di
  bawahnya: CVE Zabbix yang menyebut MariaDB muncul sebagai `mariadb`, CVE Plane yang menyebut
  GitLab OAuth sebagai `gitlab`, CVE repo Chainguard Academy sebagai `nginx`, CVE Pandora FMS sebagai
  `grafana`. Kandidat NVD/Tenable sekarang hanya dipakai kalau nama tech muncul di vendor, product,
  packageName, atau CPE record MITRE (jatuh ke ringkasan kalau CNA tidak mengisi produk).
- **CVE yang kena beberapa tech hanya menempel ke satu tech.** Dedup per `cve_id` yang global
  membuat CVE multi-produk (mis. Atlassian: Jira + Confluence + Bamboo) hanya tercatat di tech yang
  kebetulan ketemu duluan, jadi client yang hanya punya tech lain tidak pernah dapat. Sekarang tiap
  client yang punya salah satu tech terdampak dapat barisnya; client dengan beberapa tech terdampak
  tetap satu baris, dengan tech yang paling awal di techstack.

## [0.2.0] - 2026-10-05

Rilis hasil QA end-to-end (kode sampai UI) plus rebranding, Ticketing CVE, dan audit trail klasifikasi.

**Saat upgrade dari 0.1.0:**
1. Jalankan migrasi (`up -d` sudah menjalankan service `migrate`): revisi baru `d7b1f3a9c2e5`
   (kolom `rejected_articles.raw_enrichment`). Ambil backup Postgres dulu.
2. **Redis wajib hidup** untuk setiap request yang butuh login (cek pencabutan token).
3. **Perubahan kontrak API**: `POST /api/auth/change-password` sekarang wajib `current_password`;
   endpoint baca yang dulu publik (lihat Keamanan) sekarang butuh token -- klien eksternal
   (mis. penarik STIX) harus login.
4. Token yang terbit sebelum upgrade tetap berlaku sampai kedaluwarsa; pencabutan hanya untuk
   kejadian setelah upgrade.

### Keamanan
- **Endpoint baca yang dulu terbuka sekarang wajib login**: articles, filtered-articles, PIR,
  source reliability, TA groups, STIX, exec dashboard, newsletter source-hints. Pengecualian:
  `GET /api/ta/watchlist/navigator-layer` tetap publik (dibuka dari ATT&CK Navigator eksternal).
- **Scoping tenant**: PIR dan RFI by id dicek kepemilikan client (404 jika bukan milik client user;
  superadmin bebas).
- **Eskalasi privilege**: `admin` tidak bisa lagi membuat atau mengubah superadmin (buat user, reset
  password, ubah role, ubah client), dan tidak bisa memberi akses client yang tidak dia miliki.
- **Sesi/JWT**: token punya `jti` + `iat` dan bisa dicabut (denylist Redis) -- logout, ganti/reset
  password, dan ubah role/client mencabut sesi lama. `change-password` wajib password lama.
  `force_pw_change` ditegakkan di server (403 `Password change required` kecuali change-password,
  me, logout, policy); web menampilkan dialog ganti password yang tidak bisa ditutup.
  `POST /api/auth/init` memakai advisory lock (tidak bisa dobel).
- **Email/newsletter**: Jinja autoescape aktif (judul/ringkasan hasil scraping dan LLM tidak lagi
  jadi HTML), link artikel hanya http(s). Field HTML buatan analis (CSS/intro/footer) tetap `| safe`.
- Rate limit login atomik (tidak bisa terkunci permanen), login tidak membedakan user ada/tidak
  lewat waktu respons, upload lockfile dibaca dengan batas 2 MB, token tanpa `sub` -> 401 (bukan 500).
- Web: security header dasar (`X-Frame-Options`, `nosniff`, `Referrer-Policy`, `frame-ancestors`),
  `X-Powered-By` dimatikan, open redirect di halaman login ditutup.

### Diubah
- **Dokumentasi scraper** ditulis ulang: `docs/ADDING_A_SCRAPER.md` (step by step nambah scraper,
  diverifikasi ke kode dan prod; koreksi: tidak ada `cti-scraper new`, beat tidak hot-reload) dan
  `docs/SCRAPER_MAINTENANCE.md` (status kesehatan, playbook per masalah, rutinitas).
- **Audit trail respons LLM klasifikasi**: `raw_enrichment["classify"]` (artikel diterima
  dan ditolak) menyimpan model, `prompt_version`, dan isi mentah tiap percobaan --
  buat membandingkan keputusan valid/tidak-valid lintas revisi prompt.
- **Rebranding**: nama tampilan platform jadi **Vareon Intelligence**
  (sebelumnya Niskala Intelligence) -- judul tab, login, logo header, judul
  API/OpenAPI, template email, dan README. Identifier teknis (`cti-platform`,
  `cti_*`, nama image/container) tidak ikut berubah.

### Ditambah
- **CVE Tracker > Ticketing**: sub-view baru buat daftar semua ticket
  (cari by ticket/CVE/asset/owner, filter Remediation Status), klik baris
  buka tab Ticket di modal CVE. Backend: `GET /api/cve/tickets`.
- Web: halaman 404 dan halaman error sendiri, indikator loading saat cek sesi, kartu **Low** di
  statistik CVE.

### Diperbaiki
- **Artikel yang ditolak classifier gagal tersimpan**: `rejected_articles` tidak punya kolom
  `raw_enrichment` padahal dipakai audit trail di atas (migrasi `d7b1f3a9c2e5`).
- **`/api/cve` paginasi**: baris dobel di dua halaman dan sebagian tidak pernah tampil, karena
  urutan tanpa tie-breaker; sekarang diurut sekunder `id`.
- **Web, sesi**: redirect loop saat cookie expired/invalid (cookie dihapus sebelum ke `/login`), 401
  di tengah sesi mengarahkan ke login.
- **Web, CVE**: pencarian di-debounce 400 ms (sebelumnya satu request + "Loading..." berkedip per
  huruf), header sort dan baris tabel bisa dipakai lewat keyboard.
- **Web, a11y/layout**: label form Add User/Add Role/Reset Password terhubung ke input
  (`autocomplete="new-password"`), nav pill dan topbar tidak meluap di layar 375 px.
- **Export CVE Excel** disamain sama format logbook: kolom A "No" nomor
  urut, CVE Reported Date + Date Acknowledged jadi `YYYY-MM-DD HH:MM:SS`
  (WIB, sebelumnya tanggal doang / ISO mentah), Reported Date ambil dari
  `detected_on` jadi gak kosong lagi, Affected Version fallback ke data
  CVE kalau ticket belum ada, baris diurut `detected_on` naik.

### Diketahui / belum dikerjakan
- `GET /api/ta/watchlist/navigator-layer` masih publik dan membaca watchlist client mana pun lewat
  header `X-Client-ID`; butuh keputusan karena dipakai Navigator eksternal.
- IOC duplikat karena bentuk defang berbeda (`1.2.3[.]4` vs `1.2.3.4`) -- butuh migrasi data.
- CSP penuh dan HSTS belum dipasang.

## [0.1.0] - 2026-09-18

Revamp platform CTI dari dua repo terpisah (`ScraperNews` + `ScraperNewsWeb`,
Mongo) jadi satu monorepo (`cti-platform`, Postgres + Celery + FastAPI).
Masih dalam pengerjaan aktif -- lihat `docs/PROGRESS.md` buat status
per-fase yang selalu up to date.

### Selesai
- **Fase 0-2**: prep (rotasi secret, arsip data lama), skeleton monorepo
  (`uv` workspace, CI), skema Postgres penuh (`cti-core`) gantiin 38+
  collection Mongo.
- **Fase 3-4**: framework scraper plugin (`BaseScraper` + 4 family) +
  migrasi ~100 scraper aktif, verifikasi golden-test lawan feed live.
- **Fase 5**: `cti-enrich` -- pipeline enrichment artikel (klasifikasi,
  ringkasan, ekstraksi TTP/IOC, skoring, routing), IOC extractor + LLM
  client disatukan (gantiin 4 salinan lama). Ketemu 1 bug ReDoS lama yang
  ikut kebawa dari sistem lama + 3 gap reliability LLM gateway baru.
- **Fase 6**: Celery worker + beat -- scrape/enrich task terjadwal
  otomatis dari registry scraper, rate limit per-domain, verified live
  end-to-end (scrape -> sink -> enrich -> persist).
- **Fase 7 (jalan)**: `apps/api` (FastAPI) -- auth JWT/RBAC/multi-tenant,
  dan porting bertahap router lama ke repository Postgres (`auth`,
  `clients`, `roles`, `articles`, `iocs`, `techstack`, `cve`, `tweets`,
  `monitored_accounts`, `ransomware` kelar; sisanya nyusul).

### Belum
- `apps/web` (Next.js, Fase 8), control plane scraper (Fase 9), cutover
  ke produksi (Fase 10).
