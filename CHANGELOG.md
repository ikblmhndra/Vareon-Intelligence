# Changelog

Format ngikutin [Keep a Changelog](https://keepachangelog.com/), versi
ngikutin `pyproject.toml` (root). Baca lewat `GET /api/changelog` (API,
router `changelog.py`) -- parser-nya expect header persis
`## [versi] - tanggal`, jangan ubah formatnya tanpa liat
`apps/api/src/cti_api/routers/changelog.py`.

## [0.6.0] - 2026-10-15

**Enrichment reputasi IOC** (ROADMAP #4: AbuseIPDB, VirusTotal, OTX), **tiga panel baru di Dashboard CVE** (#17), dan
beberapa perbaikan kebenaran data dari #20. **Tanpa migrasi dan tanpa dependensi baru**; ada **kunci `.env` baru yang
opsional** (kosong = provider mati, jadi `.env` prod yang ada tetap start) dan **satu entri beat baru**. Rancangan:
`docs/ROADMAP.md` #4/#17/#20 dan `docs/ARCHITECTURE.md` bagian 3.7.

**Saat upgrade dari 0.5.0:**
1. Deploy biasa (bangun ulang image api, worker, dan web). Tidak ada migrasi.
2. **Restart `beat`** (deploy yang membuat ulang container sudah cukup): jadwal dibangun sekali saat import, dan entri
   `ioc-enrich-pending` (tiap 15 menit, antrean `maintenance`) baru muncul sesudahnya.
3. **OTX langsung aktif** kalau `OTX__API_KEY` sudah terisi (di prod sudah): sekitar 3.300 IOC bertipe IP, domain, dan hash
   mengantre, dan batas 25 per run (empat run per jam) membuat backfill-nya makan kira-kira satu setengah hari. Jatahnya
   `OTX__RATE` (bawaan `300/hour`).
4. **Opsional**: isi `ABUSEIPDB__API_KEY` (gratis 1000 cek per hari; jatah platform `ABUSEIPDB__RATE=40/hour`). **Jangan
   isi `VIRUSTOTAL__API_KEY` dengan key gratis**: dokumentasi VirusTotal melarang API publiknya untuk produk atau layanan
   komersial. Syarat pemakaian AbuseIPDB dan OTX belum dicek.
5. Default `max_items` scraper `new_cve` naik dari 300 ke 600. Override dari control plane (`scraper_config`) tetap menang atas
   default; kalau pernah diset kecil (mis. 100) saat memadamkan masalah, reset supaya default baru berlaku.

### Ditambah
- **Enrichment reputasi IOC** (#4, #55, #58): task `ioc.enrich_pending` mengisi kartu "TIP Enrichment" di detail IOC (UI-nya
  sudah ada, belum ada yang menulisnya). Provider: **AbuseIPDB** (IP), **VirusTotal** (IP, domain, URL, hash), dan **OTX**
  (IP, domain, hash); hanya lookup (GET), tidak pernah mengirim atau memindai apa pun. Dipilih IOC yang belum punya kartu
  provider itu atau kartunya lebih tua dari TTL (3, 30, dan 7 hari), terbaru dulu; nilai di-refang; IP non-publik tidak
  dikirim; jatah per jam lewat Redis; commit per IOC. Satu IOC gagal tidak menghentikan yang lain; 401/403/429 atau tiga
  kegagalan beruntun menghentikan provider itu di run tersebut; log hanya memuat nama kelas exception dan kode status
  (tanpa pesan, karena bisa memuat potongan kunci). Setting baru: `ABUSEIPDB__API_KEY`/`ABUSEIPDB__RATE`,
  `VIRUSTOTAL__API_KEY`/`VIRUSTOTAL__RATE`, `OTX__RATE`.
- **Tiga panel Dashboard CVE** (#17, #54): **Unresolved backlog by age** (CVE yang belum selesai per severity dan pita umur
  0-7, 8-14, 15-30, 31+ hari, plus jumlah yang melewati 14 hari), **Exploited or likely to be exploited, still
  unresolved** (KEV atau EPSS >= 0,1 yang belum selesai, KEV dulu, 10 teratas dengan jumlah sebenarnya), dan **Most
  affected tech**. Respons `GET /api/cve/dashboard` mendapat `backlog`, `exploit_risk`, `exploit_risk_total`, dan `top_tech`
  (hanya menambah).
- `make check-orphaned-tickets [ARGS='--client acme']` (#52): daftar tiket CVE tanpa baris tracker (sisa `purge-orphaned`
  lama). Hanya membaca dan sengaja tanpa `--apply`; di prod hasilnya 0.
- Dashboard CVE: baris `UNRATED` di tabel "Mean time metrics by severity" (hanya bila ada CVE tanpa severity dan tanpa skor)
  dan kolom Unrated di tabel volume bulanan (#51).

### Diubah
- **`new_cve`** (#50): kandidat diproses bergiliran antar tech (dulu menurut urutan abjad techstack, sehingga tech di
  belakang abjad kelaparan saat cap tercapai); run yang berhenti karena `max_items` kini berstatus **`partial`** dan mencatat
  peringatan `cve_max_items_reached` (dulu `ok` tanpa jejak); default `max_items` 300 menjadi 600. Status `partial` kini
  benar-benar dikeluarkan `Runner` (sebelumnya dikenali DB dan UI tetapi tidak pernah muncul); CLI memperlakukannya sebagai
  run selesai.
- **Ranking newsletter** (#53): judul yang utuh satu nama berkas (tanpa spasi, berakhiran ekstensi dokumen) tidak lagi
  mengambil slot Highlight; artikelnya tetap disarankan di section-nya. Judul di Newsroom tidak berubah.
- Respons `POST /api/cve/cisa-lookup` dan task `cve.enrichment_sweep` memuat `removed_cves` dan `reset_skipped` (hanya menambah).

### Diperbaiki
- **Flag KEV tidak pernah turun** (#52): CVE yang dicabut CISA dari katalog KEV tetap bertanda `cisa_kev` dan
  `active_exploitation` selamanya. `run_cisa_kev_lookup` kini menurunkannya untuk CVE yang dicek, **hanya bila katalog berisi
  minimal 1000 entri** (respons kosong atau terpotong, mis. bentuk JSON yang berubah, tidak boleh menurunkan flag semua CVE;
  dilewati dengan `reset_skipped` dan peringatan `cisa_kev_reset_skipped`). Isian analis di tiket tidak tersentuh.
- **Crossref PIR dan aktor** (#51): CVE yang valid di dua client keluar dua kali dan memakai dua slot dari batas 50/30; kini
  satu baris per CVE (baris terkuat), dedupe dilakukan sebelum batas.

### Diketahui / belum dikerjakan
- **Provider enrichment belum pernah dipanggil ke layanan sungguhan**: pemetaan dan klien dites dengan respons tiruan, dan
  bentuk respons OTX serta atribut VirusTotal dicek ke dokumentasi atau endpoint publiknya. Hasilnya belum memengaruhi
  `confidence_score` atau `actionability_*`. URL belum didukung di OTX; urlscan, GreyNoise, dan Shodan belum ada.
- **Tiga panel Dashboard CVE belum dilihat di browser** (lolos `tsc`, `eslint`, dan build). `OVERDUE_DAYS` (14) dan `EPSS_HIGH`
  (0,1) adalah nilai awal; belum ada target SLA per severity (ROADMAP #16). Grafik stacked bulanan tidak memuat CVE
  unrated.
- Judul Newsroom untuk artikel dari `blackorbird` tetap berupa nama berkas (keputusan membersihkannya di scraper belum diambil).
- `trending_cve` hanya mencari tahun berjalan; mulai terasa awal Januari 2027 (ROADMAP #20).
- `new_cve` masih bergantung pada pencarian kata kunci NVD: di prod 14 run `fetch_error` dalam tiga hari terakhir karena NVD
  503. Akar masalahnya (nama tech dicocokkan sebagai teks) baru hilang setelah cutover #19.

## [0.5.0] - 2026-10-14

Dua fitur prioritas dari masukan tim (ROADMAP #21 dan #22): **Recap mingguan** yang lebih murah dan diperiksa kualitasnya,
dan **Newsletter bulanan** berbahasa Indonesia dengan template baru, logo, dan artikel yang sudah disarankan. Ada **empat
revisi migrasi**, **tanpa kunci `.env` baru** dan **tanpa dependensi baru**. Beberapa perilaku berubah dan bisa memutus
skrip atau klien API (lihat langkah upgrade dan Diubah). Rancangan dan hasil ukur: `docs/ROADMAP.md` #21/#22 dan
`docs/PLAN_RECAP_NEWSLETTER.md`; alur teknis: `docs/ARCHITECTURE.md` bagian 3.5 dan 3.6.

**Saat upgrade dari 0.4.1:**
1. Deploy biasa (bangun ulang image api, worker, dan web). Service `migrate` menjalankan empat revisi berurutan:
   `f6c3a9d2b8e1` (recap: `kind`, `period_start`, `period_end`; kunci unik pindah dari `date` ke `(kind, date)`),
   `a042eff910ac` (cache ringkasan artikel newsletter dan kolom periode), `1dbf6006abaf` (tabel `newsletter_suggestions`),
   `7e51efe6d78b` (kolom `daily_recaps.quality`). Semuanya aditif kecuali pergantian kunci unik di `daily_recaps`;
   downgrade revisi pertama bisa gagal kalau recap mingguan dan harian sudah berbagi tanggal. Backup Postgres dari
   `make deploy` tepat sebelumnya adalah jalan mundurnya.
2. **Restart `beat`** (deploy yang membuat ulang container sudah cukup): jadwal dibangun sekali saat import. Entri recap
   harian hilang; muncul `recap-generate-weekly` (Senin 00:15 UTC = 07:15 WIB) dan `newsletter-prepare-monthly`
   (Senin-Jumat 02:00 UTC = 09:00 WIB, hanya bekerja di hari kerja pertama bulan dan 7 hari sesudahnya).
3. **Backfill recap mingguan** untuk pekan yang sudah berakhir sebelum deploy dan belum punya recap (untuk edisi Oktober:
   pekan Senin 28 Sep, 5, 12, dan 19 Okt; pekan yang berakhir sesudah deploy datang dari jadwal): halaman Recap, pilih **Week**, pilih tanggal di pekan itu, Generate, atau
   `POST /api/recap/generate?kind=weekly&week_start=<Senin>`. **Buat berurutan dari yang paling lama**: perbandingan dan
   scorecard hanya dihitung saat sebuah pekan dibuat dan memakai pekan sebelumnya. Pekan yang dibuat sebelum 0.5.0 tidak
   punya data `quality`; regenerasi dengan `force=true`. Edisi newsletter Oktober (Senin 2 Nov) memakai recap pekan
   28 Sep sampai 1 Nov, jadi recap pekan 26 Okt harus lahir dari jadwal Senin 2 Nov 00:15 UTC (atau dipicu tangan).
4. **Klien API newsletter**: field request `highlight`, `apac`, `global_news`, dan `indonesia` dihapus dari
   `POST /api/newsletter/preview` dan `/draft-email`. Pakai `highlights` (minimal satu) dan `<section>_full` /
   `<section>_compact`. Satu-satunya pemakai field lama yang diketahui adalah halaman Newsletter di web, dan itu sudah diganti.
5. **Build newsletter berbahasa Indonesia yang pertama lebih mahal**: semua cache ringkasan yang ada berbahasa Inggris,
   jadi tiap kartu penuh diringkas ulang (satu fetch dan satu panggilan LLM per kartu; baris compact tidak kena).
6. `LLM__RATE_LIMIT` tidak dipakai siapa pun tetapi **jangan dihapus** dari `.env` prod: fieldnya masih ada di `Settings`
   dan tetap diterima.

### Ditambah
- **Recap mingguan** (#21): recap Senin-Minggu menurut tanggal UTC, dibuat otomatis Senin 07:15 WIB. Prompt dibangun dari
  agregat (artikel satu klaster jadi satu baris, batas per kategori), sehingga satu panggilan LLM menggantikan tujuh.
  Pekan yang Minggunya belum lewat dan tanggal yang bukan Senin ditolak (400); pekan tanpa artikel, tweet, dan CVE tidak
  memanggil LLM. Pemicu tangan satu hari tetap ada (`kind=daily`, default). Hasil ukur di dev: dibanding tujuh recap harian,
  token prompt -71%, total token -72%, waktu -73% (pekan beda, lihat ROADMAP #21).
- **Token usage tercatat** di tiap recap (`token_usage`: token dari gateway, `wall_ms`, `input_chars`, jumlah item per
  seksi prompt) dan halaman Recap menampilkannya.
- **Kualitas recap**: perbandingan dengan pekan sebelumnya (selisih mutlak dan persen, plus "baru pekan ini" untuk threat
  actor, kampanye, dan CVE; dihitung di kode, tanpa LLM), **pemeriksaan grounding** (CVE id, nama actor, tema kampanye, dan
  sumber story harus ada di masukan; yang gagal dibuang dari tampilan dan dicatat di `quality.grounding.dropped`), dan
  **scorecard prakiraan** (panggilan yang sama menilai prakiraan pekan lalu: happened / partly / not_happened / unclear;
  analis bisa meng-override lewat `PATCH /api/recap/{recap_id}/scorecard/{event_id}`; hit rate 8 pekan, `partly` = 0,5,
  `unclear` tidak dihitung). Semuanya tampil di halaman Recap, termasuk tautan ke artikel sumber tiap story.
- **Newsletter bulanan** (#22): jadwal `newsletter.prepare_monthly` menyiapkan saran edisi bulan sebelumnya di hari kerja
  pertama (Senin-Jumat, tanpa daftar libur), dengan kejar sampai 7 hari kalau worker sempat mati. Tidak ada yang dikirim
  otomatis; hasilnya menunggu di tabel `newsletter_suggestions`.
- **Saran artikel dengan alasan**: ranking dari data tersimpan (KEV, PoC, insiden terkonfirmasi, tech terpantau, negara
  client, Indonesia/APAC, liputan, sumber, confidence) menempatkan artikel ke Highlights, Asia Pacific, Global, dan
  Indonesia dalam tiga tier (kartu highlight, kartu penuh, baris compact "Also Noted"). `GET /api/newsletter/suggestion`
  dan `POST /api/newsletter/suggestion/rebuild`. Set negara APAC baru ada di `cti_core/regions.py`.
- **Executive Summary** berbahasa Indonesia: satu panggilan LLM merangkum recap mingguan yang menyentuh bulan itu, dengan
  pemeriksaan grounding yang sama (CVE karangan diganti `[CVE tidak terverifikasi]`). Kalau panggilan gagal, ranking tetap
  tersimpan, ringkasan kosong, dan `summary_meta.error` hanya memuat nama exception dan kode HTTP (tanpa pesan, karena bisa
  memuat potongan kunci); hari kerja berikutnya mengulang hanya langkah ringkasan.
- **Composer newsletter** terbuka sudah terisi saran (banner Use suggestion / Merge bila antrean sudah ada, tombol Build
  suggestion bila belum ada saran), bisa dinaik-turunkan tier-nya, ditukar, dan dibuang; Executive Summary bisa disunting
  dengan peringatan untuk ekor bulan yang belum tercakup; peringatan ukuran email sebelum draft; badge untuk kartu yang
  diringkas dari metadata dengan tombol Re-summarise; pilihan bahasa `id`/`en`.
- **Template email baru** (layout tabel dengan CSS inline, tanpa flex, kontainer 640 px, fallback Outlook desktop; **tanpa mode
  gelap**: Outlook membalik warna email sendiri dan mengabaikan `color-scheme`, jadi palet terang dikunci dengan aturan
  `[data-ogsc]` / `[data-ogsb]`, sedangkan app Gmail membalik sendiri dan tidak bisa dikunci) dengan
  **logo perusahaan inline** (lampiran `cid:` pada draft Graph, tanpa panel putih) dan **ringkasan artikel berbahasa
  Indonesia** (glosarium istilah `newsletter_glossary.py`; heading tetap Inggris termasuk "Campaigns").
- **Cache ringkasan artikel** (`newsletter_article_summaries`, kunci `(article_id, language)`): preview dan draft tidak lagi
  mengulang fetch Playwright dan panggilan LLM.
- **Scraper baru**: AWS Security Blog (`aws_security`), Red Hat Security, Cloud Vulnerability Database, dan Zeroday
  Initiative.

### Diubah
- **Daftar CVE di prompt recap**: satu baris per `cve_id` (dulu CVE yang sama dihitung per client), diurutkan KEV, PoC, CVSS
  menurun (dulu urutannya sembarang), baris false-positive dibuang lebih dulu.
- **Recap harian tidak lagi dijadwalkan**; entri beat dan task `recap.generate_daily` dihapus. Halaman Recap membuka recap
  mingguan terbaru dan punya toggle Day/Week.
- **Newsletter**: subject memakai periode (`[CTI Newsletter] Threat Intelligence Digest — October 2026`; baris riwayat lama
  tetap "Week N, YYYY"); `preview` tidak lagi menyimpan baris riwayat dan tidak menulis IOC atau mention CVE; draft yang
  gagal di Graph tidak meninggalkan baris; satu pengiriman = satu baris. `newsletter_id` di respons preview selalu `null`.
- **Batas isi newsletter**: Highlights maksimal 3, kartu penuh maksimal 4 dan baris compact maksimal 15 per section (dulu
  satu highlight dan maksimal 5 kartu per section). Field request lama dihapus (langkah upgrade 4).
- Dialog preview newsletter selebar email (dulu terkunci 24 rem di desktop); jumlah per section di riwayat menjumlah kartu
  dan baris compact.

### Diketahui / belum dikerjakan
- **Draft Graph asli sudah dilihat hanya di new Outlook**: mode terang rapi (logo inline, header, Executive Summary
  Indonesia), mode gelap dikunci ke palet terang tetapi belum dicek ulang di draft baru. Outlook desktop (klasik), Outlook
  web, dan Gmail belum dilihat; tangkapan layar menutup ROADMAP #22.
- **Set negara APAC** (`cti_core/regions.py`: Bank Dunia East Asia & Pacific dan South Asia) adalah keputusan baru dan
  belum dikonfirmasi tim; bobot ranking adalah nilai awal yang disetel setelah edisi pertama.
- Ringkasan bulanan tidak mencakup ekor bulan yang pekannya belum selesai pada hari kerja pertama (bulan yang berakhir di
  tengah pekan; edisi Oktober tidak terkena). Ekor itu tercatat di `summary_meta.uncovered` dan tetap ada di artikel
  ter-ranking.
- State composer newsletter tidak disimpan: reload mengisi ulang dari saran dan menghapus suntingan.
- Saat tidak ada klaster kampanye di data, model tetap mengarang tema `active_campaigns` dan nama actor; pemeriksaan
  grounding membuangnya (`quality.grounding.dropped`, terlihat di dev) sehingga tidak tampil, tetapi promptnya belum
  dirapikan untuk kasus itu. `article_id` terisi untuk semua top story di dev.
- Judul artikel yang berupa nama file (mis. `2026-09-28-AgtaBackup-RAT-Campaign.txt`) bisa menjadi highlight di saran;
  ranking belum menyaringnya, analis menulis ulang judulnya.

## [0.4.1] - 2026-10-09

Perbaikan kecil hasil pemeriksaan 0.4.0 di server dev: teks versi terdampak (`affected`) yang diawali `<=` dua kali, dua
keterangan di UI yang tidak sesuai isinya, dan satu perbaikan runbook. **Tanpa migrasi, tanpa kunci `.env` baru, tanpa
perubahan dependensi, tanpa perubahan kontrak API.**

**Saat upgrade dari 0.4.0:**
1. Deploy biasa (bangun ulang image api, worker, dan web). Tidak ada revisi migrasi baru.
2. **Perbaiki teks `affected` yang sudah tersimpan, SESUDAH deploy** (kode 0.4.0 menulis ulang teks rusak untuk CVE 8 hari
   terakhir di tiap run `new_cve`, jadi menjalankannya sebelum deploy percuma). Cek jumlahnya dulu:
   `SELECT count(*) FROM cve_affected WHERE affected ~ '^.*?: <= [<>=!]';`. Lalu jalankan skrip (idempoten, satu transaksi
   yang batal sendiri bila jumlah baris tidak cocok; cadangannya backup Postgres dari `make deploy` tepat sebelumnya):
   `docker compose --env-file docker/stack.env --profile app exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -q' < tools/ops/fix_affected_double_operator.sql`.
   Di dev terukur 46 baris `cve_affected` dan 14.378 record mirror `cve_records` (12% dari 117.898) yang rusak.
   **Wajib sebelum cutover `CVE_MIRROR__PROMOTE=live`**: promosi menyalin `affected_lines` apa adanya ke tracker.

### Diperbaiki
- **Teks versi terdampak diawali `<=` dua kali** (mis. `mariadb-connector-nodejs: <= >= 3.3.0, < 3.5.4`): CNA seperti GitHub
  menulis rentang versinya sendiri di `versions[].version`, dan parser meng-awali semuanya dengan `<=`. Teks itu tampil di
  tab Details dan CVE DB serta mengisi Affected Version di form Ticket. Sekarang hanya versi polos (`1.12.0`, `22.7R2.4`) yang
  diberi `<=`; teks bebas dipakai apa adanya dan `version` kosong dilewati. `lessThan` dan `lessThanOrEqual` tidak berubah.
  Berlaku untuk `new_cve` dan sinkronisasi mirror. Baris yang sudah tersimpan: langkah upgrade 2.
- **Exec: keterangan kartu "Critical CVEs"** tertulis "cisa_kev flagged", padahal angkanya jumlah CVE berseverity critical
  (di dev 12, yang KEV hanya 1). Keterangannya kini "by CVSS severity"; angkanya tidak berubah.
- **Dashboard CVE: tile "CVEs detected"** tidak menyebut CVE tanpa skor CVSS, sehingga rinciannya (89) tidak menjumlah ke total
  (101). Kini ditutup ` · N unrated` bila ada.
- **Runbook cutover** (`docs/CVE_CATALOG_CUTOVER.md`): perintah pantau `cve_mirror_synced` dipindah ke blok kode sendiri
  (disalin utuh ke shell, `ok|noop` terbaca sebagai pipe), dan Tahap 3 memuat langkah membersihkan teks `affected` di mirror.

### Diketahui / belum dikerjakan
- Batas bawah rentang `lessThan` tidak ikut ditulis (`version: "3.3.0", lessThan: "3.5.4"` menjadi `< 3.5.4`, jadi rentang
  tertutup terbaca seperti "semua versi sebelum 3.5.4"). Menambahkannya mengubah hampir semua teks `affected` tersimpan
  (193 dari 333 di dev), jadi dipisahkan sebagai keputusan sendiri.
- KPI "Critical CVEs" dan tabel CVE exposure di Exec menghitung tracker **semua client** (tanpa filter `client_id`) dan hanya
  10 tech teratas (diurut jumlah critical). Apakah angkanya harus per client, atau berbasis KEV, menunggu keputusan produk.
- Tabel "Mean time metrics by severity" dan "Monthly CVE volume by severity" di Dashboard CVE belum menyebut CVE unrated
  (API belum mengirim bucket-nya).
- Butir "Diketahui" 0.4.0 lainnya masih berlaku.

## [0.4.0] - 2026-10-09

Perbaikan logic CVE Tracker hasil analisa end to end (scraper, repo, API, UI), ditambah info "diupdate per kapan" dan
tombol cek manual CVE baru di tab CVEs. **Tanpa migrasi, tanpa kunci `.env` baru, tanpa perubahan dependensi.**
Beberapa perilaku API berubah dan bisa memutus skrip (lihat langkah upgrade dan Diubah). Alur lengkap CVE Tracker:
`docs/CVE_TRACKER_FLOW.md` (ikut diperbarui).

**Saat upgrade dari 0.3.0:**
1. Tidak ada langkah khusus selain deploy biasa (bangun ulang image api, worker, dan web). Tidak ada revisi migrasi baru.
2. **Skrip dan klien API yang memanggil CVE Tracker** perlu dicek terhadap perubahan di bawah: FP, ticket, dan ack atas
   CVE yang tidak ada di tracker client kini `404`; ID CVE yang formatnya salah `422`; `analyst_name` di body
   acknowledge diabaikan (nama = user yang login); `purge-orphaned` hanya admin/superadmin.
3. **Export Excel CVE Tracker dari UI** memfilter tanggal menurut pilihan **Date by** (default *Published*). Laporan
   bulanan berbasis tanggal deteksi harus memilih *Detected* (sebelumnya export dari UI selalu memakai tanggal deteksi).
4. Digest `recap`, tabel CVE exposure di Exec, `crossref`, dan daftar CVE untuk monitor PoC GitHub kini menilai false
   positive **per client**, jadi CVE yang dulu hilang karena satu client menandainya FP bisa muncul lagi (lihat Diubah).

### Ditambah
- **Info "diupdate per kapan" dan tombol cek manual CVE baru** di tab CVEs: baris di bawah filter menampilkan kapan sumber
  terakhir dicek dengan sukses (WIB), CVE terbaru yang terdeteksi, dan kapan cek otomatis berikutnya; percobaan terakhir
  yang gagal (mis. `rate_limited`) dilaporkan terpisah supaya data tidak tampak baru. Tombol **Check for new CVEs**
  (admin saja) mengirim tugas yang sama dengan jadwal ke jalur yang aktif, yaitu scraper `new_cve` (default) atau mirror
  CVE List V5 bila promosi `live`; UI menunggu hasilnya sendiri dan melaporkan "N new CVEs" (menyerah setelah 15 menit).
  API: `GET /api/cve/freshness` dan `POST /api/cve/check-new` (audit `check_new_cves`; `409` kalau run masih berjalan
  atau scraper dimatikan, `429` + `Retry-After` selama cooldown 120 detik, `503` kalau broker mati). Cek `new_cve`
  memproses **semua client** sekaligus; yang per client hanya hitungan "CVE baru". Ini bukan "Populate now"
  (`docs/ROADMAP.md` #3).
- **Pilihan "Date by"** (`published` | `detected`, parameter `date_basis`) di `GET /api/cve`, `/stats`, dan `/export`;
  "detected" = hari kalender WIB. UI memakainya sama untuk list, stats, dan Export Excel. Default API tidak berubah
  (list/stats `published`, export `detected`).
- **Ticketing**: `GET /api/cve/tickets?include_fp=` (default `false`) + field `false_positive`, checkbox **Show FP**, dan
  badge FP.
- **`unrated` di `GET /api/cve/stats`** (CVE tanpa skor CVSS: 0 atau NULL) dan kartu **Unrated**, supaya
  critical + high + medium + low + unrated = total.
- **`POST /api/cve/purge-orphaned` melaporkan `protected` dan `protected_cve_ids`** (baris yang dilewati karena punya ticket).
- **`POST /api/cve/draft-email` menerima header `X-Client-ID`** (lihat Diubah).

### Diubah
- **False positive dinilai per baris client `(cve_id, client_id)` di semua tempat yang tidak ber-scope satu client**: lookup
  KEV/EPSS/Exploit-DB (dulu hanya FP client `default` yang dihitung, port perilaku legacy), korelasi CVE di newsletter,
  digest `recap`, tabel CVE exposure di `exec_dashboard`, `crossref` (CVE, PIR, TA), dan daftar CVE monitor PoC GitHub.
  CVE hilang dari digest itu hanya bila **semua** barisnya di-FP oleh pemiliknya masing-masing, dan FP dari client yang
  tidak men-track CVE-nya tidak berlaku untuk client lain. Efeknya: CVE dan hitungan yang dulu tersembunyi karena satu
  client menandai FP kini tampil, dan monitor PoC melakukan beberapa pencarian GitHub tambahan.
- **`acknowledged_by` selalu username yang login.** `analyst_name` dihapus dari body `POST /{cve_id}/acknowledge` (tanpa body)
  dan `bulk-acknowledge` (hanya `cve_ids`); klien lama yang masih mengirimnya diterima, field-nya diabaikan. Audit tidak
  lagi memuat nama kedua. Data lama tidak dimigrasi.
- **Ack pertama menang**: ack tunggal tidak lagi menimpa ack yang sudah ada (nama, `acknowledge_time`, nomor ticket);
  ack ulang tetap `200` tanpa efek, dan dua ack bersamaan berurutan. Dulu ack ulang menggeser `acknowledge_time` (dasar MTTA).
- **FP, ticket, dan ack hanya untuk CVE yang ada di tracker client pemanggil** (`POST /{cve_id}/false-positive`,
  `bulk-false-positive`, `PUT /{cve_id}/ticket`, `POST /{cve_id}/acknowledge`, `bulk-acknowledge`): selain itu `404`
  (`CVE not tracked by this client: ...`; bulk semua-atau-tidak-sama-sekali). Pengecualian: CVE yang sudah punya ticket
  (mis. yatim sesudah purge) tetap boleh diubah. `DELETE /{cve_id}/false-positive` dan `GET /{cve_id}/ticket` tidak diperiksa.
- **`purge-orphaned`**: hanya admin/superadmin (termasuk dry run; sebelumnya analis biasa bisa mengeksekusi penghapusan
  permanen), dan **tidak pernah menghapus baris tracker yang punya ticket atau ack** (definisi sama dengan
  `reconcile_cve_tech`); penanda FP baris yang dilindungi dibiarkan. Eksekusi tanpa yang bisa dihapus dilaporkan
  `dry_run: false`, `deleted: 0` (dulu `dry_run: true`).
- **List, stats, dan Export Excel dari UI memakai satu pilihan "Date by"** (default Published); lihat langkah upgrade 3.
- **Ticketing menyembunyikan CVE FP secara default** (mengikuti tab CVEs, dashboard, dan export); aturan UI "Acknowledge
  dulu sebelum Mark FP" tidak berubah.
- **Nomor ticket**: bulan dibaca dalam WIB (dulu UTC) dan penomoran diserialkan dengan `pg_advisory_xact_lock`. Tracking ID
  di draft email memakai nomor ticket yang sudah ada (multi-CVE: dipisah koma), bukan nomor "intipan" yang tidak pernah
  disimpan. Tab Ticket melabeli nomor sebelum disimpan sebagai pratinjau.
- **`draft-email` dan `GET /api/cve/prioritize` ber-scope client pemanggil** (baris client lain tidak lagi memberi CVE dobel,
  `product_name`, atau `in_tech_stack`). CVE yang belum di-track client pemanggil di `/prioritize` tetap jatuh ke baris client lain.
- **ID CVE divalidasi dan dinormalisasi** di path dan body FP, ticket, acknowledge, exploit-lookup, dan draft-email: huruf
  besar, spasi pinggir dibuang, format `CVE-YYYY-NNNN` (4-11 digit ASCII); selain itu `422` dan tidak ada yang ditulis
  (satu id salah menggagalkan seluruh daftar bulk). Id kembar di bulk dihitung sekali.
- **Dropdown Tech di tab CVEs** (`GET /api/cve/tech-list`) hanya menawarkan tech yang bisa tampil di tab (entri aktif);
  baris yatim dan entri nonaktif tidak lagi ditawarkan. Client tanpa entri techstack tetap tanpa filter.

### Diperbaiki
- **`new_cve` melabeli jam UTC dengan `+07:00`**: `pubEndDate` mundur 7 jam, CVE baru telat tercatat dan MTTD membengkak.
  Sekarang offset `+00:00`.
- **Mention artikel memakai substring**: `CVE-2026-1234` cocok ke `CVE-2026-12345`. Sekarang batas angka.
- **Nomor ticket bisa kembar**: dua request bersamaan membaca nomor maksimum yang sama dan yang kedua gagal
  `IntegrityError` (500); ack pertama atas ticket yang sama-sama belum ada juga bisa bertabrakan.
- **`bulk-acknowledge` dan `bulk-false-positive` dengan id kembar** kena `IntegrityError`.
- **`/stats`: jumlah bucket tidak sama dengan `total`** untuk CVE tanpa skor CVSS (kini bucket `unrated`).
- **Korelasi CVE di newsletter** (`cve_mentions`, `possibly_exploited_wild`) memakai FP client `default` saja; kini
  true positive per baris client, sama dengan lookup KEV/EPSS/Exploit-DB.
- **Dashboard: console React "two children with the same key"**: peta negara memberi key `"undefined"` untuk N. Cyprus,
  Somaliland, dan Kosovo (tanpa id numerik di `world-atlas`).
- **Form Ticket**: Acknowledge me-remount form sehingga isian yang belum disimpan hilang; ticket kosong yang baru dibuat
  menghapus prefill Affected Asset/Version; Save/Acknowledge tidak me-refresh Ticketing, dashboard, dan list CVE;
  Ticketing salah menampilkan "CVE sudah di-purge" untuk CVE yang techstack-nya dihapus; tautan "NVD" bisa mengarah
  ke Tenable (label kini mengikuti host).

### Diketahui / belum dikerjakan
- Lookup KEV, EPSS, dan Exploit-DB masih terbuka untuk semua analis (`require_auth`); Exploit-DB bulk berat dan bisa
  dipicu analis mana pun.
- "Severity" punya tiga versi di UI (mentah, "effective" yang naik satu tingkat bila ada PoC, dan `adjusted_risk_score`);
  `cisa_kev_detail` (termasuk `due_date`) tersimpan tapi tidak ditampilkan.
- Flag `cisa_kev`/`active_exploitation` tidak pernah dikembalikan ke `false` kalau CISA menghapus entri dari katalog KEV.
- `trending_cve` hanya mencari `CVE-<tahun berjalan>-`; CVE tahun lalu yang sedang ramai tidak tertangkap (menambahkannya
  menambah biaya tweet di X API dan sintaks query perlu divalidasi ke API asli).
- Tidak ada kode yang menulis `cve_threat_actors` dan `cve_ttps`, jadi cabang TA/TTP di `crossref` tanpa data.
- `recap` dan `crossref` mengembalikan satu baris per client: CVE yang di-track dua client muncul dua kali.
- Status "Resolved" tanpa `actual_remediation_date` tidak masuk MTTR (terlihat dari `n` di dashboard); validasi isian ticket:
  `docs/ROADMAP.md` #18.
- Ticket yatim dari `purge-orphaned` versi lama tidak dibersihkan otomatis (cek: ticket tanpa baris tracker).
- `cve_newsletter_mentions` hanya ditulis ke satu baris tracker (client mana pun) dan belum dibaca siapa pun.

## [0.3.0] - 2026-10-08

Katalog tech + mirror CVE (`docs/ROADMAP.md` #19), notifikasi Telegram CVE baru, satu pencocok nama tech
bersama, dan Chromium di CI. Fitur katalog/mirror/cutover **mati secara default**: tanpa flag `CVE_MIRROR__*`
perilaku pipeline CVE sama seperti 0.2.1. Ada 4 migrasi baru dan satu topik Telegram baru, `cve_new` (lihat di bawah).

**Saat upgrade dari 0.2.1:**
1. Jalankan migrasi (`up -d` sudah menjalankan service `migrate`): revisi baru `e8c2a4b6d1f3` (kolom
   nullable `cve_tracker.published_at`, aman untuk data lama), `b7e3d9a1c5f2` (tabel katalog/mirror/target +
   `techstack_entries.active`, semua entri tetap aktif) dan `d4a9c7e1b3f6` (`cvss_vector` jadi TEXT, hanya
   mengubah metadata) dan `e5b2d8f4a7c1` (tabel `cve_promotion_shadow`, kosong). Kontrak API hanya bertambah:
   `GET /api/cve/dashboard`.
2. Jalankan sekali `make backfill-published-at` (laporan dulu, lalu `ARGS='--apply'`;
   `docs/SCRAPER_MAINTENANCE.md` 4.H) supaya CVE lama punya jam di kolom "CVE Reported Date" export --
   tanpa itu mereka tampil tanggal saja.
3. **Tambahkan topik `cve_new` ke `TELEGRAM__THREAD_IDS` di `.env` host** (`"cve_new": <thread id>`; `0` = chat
   utama tanpa thread). `.env.example` dan `.env.prod.template` sudah memuatnya. Tanpa ini aplikasi tetap
   jalan, hanya ringkasan CVE baru yang tidak terkirim.
4. **Export Excel CVE Tracker: kolom bergeser satu ke kanan** mulai kolom E (lihat Diubah). Makro atau
   skrip yang membaca file export per posisi kolom harus disesuaikan.

### Ditambah
- **Cutover katalog tech** (`docs/ROADMAP.md` #19, irisan 7): saat `CVE_MIRROR__PROMOTE=live` scraper `new_cve`
  ditangguhkan (tidak dijadwalkan beat, `Runner` menolak, health `disabled`, tampil nonaktif); tracker diisi
  pipeline mirror + ringkasan Telegram. Env baru opsional `CVE_MIRROR__KEEP_LEGACY_NEW_CVE` (default `false`;
  `true` = jalan berdampingan). Rollback = `PROMOTE=off` + restart, tanpa migrasi. `tools/ops/catalog_mapping.py`
  (`make catalog-mapping`): ekspor/impor pemetaan techstack->katalog lewat kunci stabil, plus `suggest`.
  `promote_cve_mirror --since`. Runbook langkah demi langkah: `docs/CVE_CATALOG_CUTOVER.md`.
- **UI katalog tech** (`docs/ROADMAP.md` #19, irisan 6; tanpa perubahan backend): halaman CVE Tracker, sub-view
  "Tech Stack" diganti **Monitored Tech** (daftar entri + target, Pause/Resume, tanda "Unmapped" untuk entri lama
  dan tombol **Map to catalog** untuk memetakannya ke katalog; target banyak per entri), **All Tech** (vendor ->
  produk, search-first, produk ber-1 CVE disembunyikan kecuali dicari / "Show all", tombol Monitor) dan **CVE DB**
  (penjelajah mirror CVE dengan aksi Monitor per produk).
- **API katalog, CVE DB, dan Monitor berbasis katalog** (`docs/ROADMAP.md` #19, irisan 5; kontrak hanya
  bertambah): `GET /api/catalog/vendors`, `/vendors/{id}/families`, `/families?q=` (jelajah menyembunyikan
  keluarga ber-1 CVE; `q`/`show_all`/yang sudah di-Monitor selalu tampil; pagination maks 100),
  `GET /api/cve-db` dan `/{cve_id}` (baca-saja atas mirror, tiap produk membawa status Monitor),
  `POST /api/techstack` menerima `vendor_id`/`family_id` (entri katalog; `name` saja = custom seperti dulu),
  `POST/DELETE /api/techstack/{id}/targets` (target terakhir tidak bisa dilepas), `PATCH /api/techstack/{id}`
  `{active}`, `GET /api/techstack?active=`; `TechStackOut` + `active`/`kind`/`targets`. Tugas
  `cve.promote_entry` mengisi riwayat entri yang baru di-Monitor dari mirror (hanya bila
  `CVE_MIRROR__ENABLED` dan `CVE_MIRROR__PROMOTE` menyala). Tanpa migrasi baru.
- **Promosi mirror -> `cve_tracker` dengan mode bayangan** (`docs/ROADMAP.md` #19, irisan 4):
  `cti_core.cve_promotion` mencocokkan tiap CVE mirror ke entri techstack aktif per client (target keluarga >
  target vendor > gate teks lama untuk entri tanpa target; satu baris per (CVE, client)). Flag
  `CVE_MIRROR__PROMOTE=off|shadow|live` (default `off`, hanya berlaku bila `CVE_MIRROR__ENABLED=true`):
  `shadow` menulis tabel baru `cve_promotion_shadow` (revisi `e5b2d8f4a7c1`) tanpa menyentuh `cve_tracker`;
  `live` menulis `cve_tracker` (+ ringkasan Telegram CVE baru yang sudah ada). Tool `make promote-cve-mirror`
  (seluruh mirror, laporan dulu) dan `make compare-promotion-shadow` (bayangan vs `new_cve`, dengan sebab
  selisih). Gate teks `relevant_techs` pindah ke `cti_core.tech_match` (perilaku `new_cve` tidak berubah).
  Entri techstack nonaktif (`active=false`) tidak lagi ikut `reference_data` (semua entri sekarang aktif,
  jadi tidak ada perubahan perilaku). `new_cve` tetap jalan; mematikannya = irisan 7.
  Tool perbandingan membedakan "mirror basi" (CVE terbit pada/setelah record mirror terbaru) dari "tidak ada di mirror".
- **Ingest mirror CVE dari CVE List V5** (`docs/ROADMAP.md` #19, irisan 3): tugas `cve.mirror_sync` (tiap 5 menit,
  kursor + catch-up lewat `deltaLog.json` + antrean percobaan ulang di `job_state`) dan `cve.mirror_purge`
  (retensi tahun kalender, harian 03:30 UTC), skrip isi awal `tools/ops/backfill_cve_mirror.py`
  (`make backfill-cve-mirror SOURCE=... [ARGS=--apply]`, default laporan saja). **Mati secara default**:
  `CVE_MIRROR__ENABLED=false` di `.env.example` dan `.env.prod.template` (key opsional, aman bila belum
  ada di `.env` host); mirror belum dipakai apa pun yang terlihat user (promosi ke `cve_tracker` = irisan 4).
  Default tahun ID yang dipindai skrip backfill = `default_years` (2024-2026 di 2026), bukan hanya tahun
  berjalan dan lalu: CVE berID 2024 yang terbit 2025+ (mis. CVE-2024-11741) harus ikut, retensi memakai
  tanggal terbit.
  Skrip backfill mencetak progress + ETA ke stderr tiap 2000 berkas (laju ukur lokal ~110 berkas/dtk,
  jadi ~17 menit untuk 117 ribu CVE; tanpa progress ia diam sampai selesai).
  Skrip backfill berhenti dengan kode 4 dan menampilkan isi sumber (folder, tahun yang ada) bila tidak ada
  satu pun berkas CVE terbaca, bukan melapor "0" dengan sukses.
  Parser record dipisah jadi `cti_core.cve_record.parse_cve_record`; `new_cve` memakainya tanpa
  perubahan perilaku.
- **Skema katalog tech, mirror CVE, dan target Monitor** (`docs/ROADMAP.md` #19, irisan 2; revisi `b7e3d9a1c5f2`):
  tabel `catalog_vendors`/`catalog_families`/`catalog_family_aliases` (permanen, statistik hanya naik),
  `cve_records`/`cve_record_products` (mirror, dibuang retensi tahun kalender), `techstack_targets`
  (vendor ATAU keluarga per entri) dan kolom `techstack_entries.active` (default true). Repositori
  `cti_core.db.repositories.catalog`. **Belum dipakai aplikasi**: semua entri techstack tetap aktif tanpa
  target dan dicocokkan lewat teks seperti sebelumnya; migrasi aman untuk data lama.
- **`cti_core.catalog_resolve`** (`docs/ROADMAP.md` #19, irisan 1): resolver murni (vendor, produk) mentah dari data
  CNA -> (vendor, keluarga) katalog: normalisasi sadar-unicode, produk sampah tanpa identitas, kunci vendor
  kompak tanpa akhiran legal, lipat versi/edisi jadi keluarga, CPE diutamakan, alias manual. **Belum dipakai
  aplikasi** (tanpa migrasi, tanpa perubahan perilaku); rancangan: `docs/CVE_CATALOG_DESIGN.md`.
- **`tools/ops/spike_cve_catalog.py`**: spike pengukuran katalog tech dari CVE List V5 (`docs/ROADMAP.md` #19, `docs/CVE_TECH_MATCHING.md` 7.1.2). Hanya baca, stdlib saja, jalan di luar image; melaporkan ukuran/kebersihan katalog, keluarga produk, duplikasi ejaan, vonis per tech, dan recall terhadap `cve_tracker` (lewat CSV). Tidak ada migrasi dan tidak mengubah perilaku aplikasi.
- **Ringkasan Telegram CVE baru untuk tech yang di-monitor.** Sebelumnya tidak ada notifikasi otomatis saat CVE
  masuk `cve_tracker`. Sekarang tiap baris tracker yang **baru dibuat** (bukan update) dikumpulkan sepanjang run
  `new_cve` dan dikirim **sekali di akhir run, satu pesan per client**, ke topik Telegram baru `cve_new`:
  maksimal 10 CVE (severity terparah dulu) + "dan N lainnya", selalu < 4096 karakter. Hanya CVE yang terbit
  <= 3 hari (tech baru/backfill tidak membanjiri channel), bukan false positive client itu. Kegagalan kirim tidak
  menggagalkan run (dicatat `cve_new_alert_failed`). Kode: `cti_scraper.cve_alert`, hook `sinks.finish_run`
  dipanggil `Runner`; `CveTrackerRepo.upsert_with_status` mengembalikan penanda baru/update.
- **`cti_core.tech_match`** (`docs/ROADMAP.md` #19): satu definisi "teks ini menyebut tech itu" (kata utuh,
  angka versi menempel diterima, huruf menempel ditolak, istilah < 2 karakter tak pernah cocok), dipakai
  gate dan filter Tenable `new_cve`, `score.py`, `cve_priority`, dan `reconcile_cve_tech`. Tidak ada
  migrasi dan tidak ada kolom baru (kolom `aliases` yang sempat direncanakan dibuang).
- **`docs/CVE_TECH_MATCHING.md`**: catatan satu topik soal kolom Tech di CVE Tracker (masalah, akar masalah,
  solusi 0.2.1, cara memverifikasi, batasan, dan rencana standarisasi techstack). Rencananya dicatat di
  `docs/ROADMAP.md` #19; belum dikerjakan.
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
- **Entri techstack nonaktif (`active=false`) = disembunyikan, tidak dihapus** (irisan 5): tidak tampil di tab
  CVEs, `/stats`, dashboard, export, dan `tech-list`; tidak ikut `reference_data`/`score.py`; `purge-orphaned`
  tidak menghapus barisnya; ticket tetap. Client yang punya entri tapi semuanya nonaktif melihat tab kosong
  (bukan "tanpa filter"); client tanpa entri sama sekali tetap tanpa filter. **`GET /api/cve/export` kini
  mengikuti scope tab (entri aktif)**: sebelumnya tidak menyaring techstack, jadi baris yatim ikut export
  dan sekarang tidak.
- **Pencocok tech di `score.py` dan `cve_priority` kini kata utuh (sebelumnya substring).**
  Alert topik `tech_stack` (judul artikel/tweet dan vendor CVE) dan flag `in_tech_stack` di skor prioritas
  CVE tidak lagi cocok ke kata yang hanya mengandung nama tech (`go` ~ `google`, `edge` ~ `knowledge`), dan
  nama tech bertanda baca (`node.js`, `c++`) tidak lagi diperlakukan sebagai regex. Efeknya terlihat sebagai
  alert/bobot prioritas yang berkurang untuk pasangan yang dulu cocok kebetulan. `reconcile_cve_tech`
  memakai pencocok yang sama dengan scraper: **bangun ulang image worker sebelum menjalankannya**.
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
- **`cve_tracker.cvss_vector` dan `cve_records.cvss_vector` terlalu sempit (`VARCHAR(100)`)**: vektor CVSS dengan
  metrik temporal/environmental mencapai 117-125 karakter (CVE-2025-1787, CVE-2025-27363) dan gagal
  `StringDataRightTruncation`. Ketemu di backfill mirror pada data nyata; `new_cve` punya kerentanan yang sama
  terhadap CVE seperti itu. Revisi `d4a9c7e1b3f6` mengubahnya jadi TEXT.
- **Export CVE Tracker (`GET /api/cve/export`) tidak membawa logo.** Template `.xlsx` punya logo
  (`xl/media/image1.png`, di B1:H4), tetapi openpyxl hanya membaca gambar kalau Pillow terpasang dan
  `pillow` belum jadi dependency `cti-api`, jadi logo hilang tanpa error di file hasil export.
  `pillow` sekarang jadi dependency `cti-api` (`uv.lock` ikut diperbarui) dan ada test regresi di
  `tests/integration/test_cve_export_service.py`.
- **Filter Tech 0.2.1 salah menolak produk yang namanya berakhiran angka versi.** `graylog2-server`
  tidak cocok dengan tech `graylog` (juga `Log4j2` untuk `log4j`, `Struts2` untuk `struts`), jadi
  `new_cve` membuang CVE yang sah dan `reconcile_cve_tech` menandainya `DELETE`. Ketemu dari laporan
  `reconcile_cve_tech` di produksi (CVE-2026-69190). Angka yang menempel di ujung nama sekarang dianggap
  versi mayor produk yang sama; huruf yang menempel tetap produk lain (`nginxplus` bukan `nginx`).
  **Image worker harus dibangun ulang sebelum `reconcile_cve_tech` dijalankan lagi**: tool memakai
  pencocok dari image, bukan dari folder `tools/`. Jangan `--apply` dengan image 0.2.1.

- **CI di `main` merah sejak run #11 (tiga job, tiga sebab berbeda), sehingga job Deploy tidak pernah
  terpicu.** `lint`: `docs/ADDING_A_SCRAPER.md` dan `tests/unit/test_rss_illegal_xml_chars.py` belum
  ter-format (`ruff format`). `compose`: `env_file: ${CTI_ENV_FILE:-.env}` butuh `.env` yang tidak ada di
  git, sekarang job menunjuk `CTI_ENV_FILE=.env.example`. `test`: `test_golden_trendmicro` butuh Chromium
  Playwright (sekarang job `test` menjalankan `uv run playwright install --with-deps chromium`, versi
  mengikuti `uv.lock`), dan `test_article_dedup_groups` seed-nya memakai tanggal tetap sementara
  `get_dedup_groups` hanya melihat 7 hari terakhir, jadi mati sendiri sejak 2026-10-01 (sekarang seed
  dengan tanggal hari ini; `test_list_articles_dedup` tetap pinned karena snapshot-nya memuat `week`).
  Ketemu saat PR dijalankan di CI: `test_domain_defanged_regex_does_not_catastrophically_backtrack`
  memakai alarm 5 detik padahal ekstraksi domain berbiaya linear ±5 detik untuk teks uji itu (bukan
  ReDoS), jadi hasilnya mengikuti kecepatan runner. Alarm jadi 60 detik; regex tak terbatas tetap
  tertangkap. Kode produksi tidak berubah.

### Diketahui / belum dikerjakan
- **Hijau CI di `main` dan Deploy otomatis belum terbukti.** Perbaikan di atas baru diuji lokal per
  penyebab; CI penuh baru jalan setelah PR dibuat. Sampai Deploy terpicu sekali dan lolos `deploy.sh`,
  produksi hanya bisa di-update manual (`make deploy`, atau Actions > Deploy > Run workflow). Rinciannya
  di `docs/ROADMAP.md` #13.
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
  GitLab sebagai `gitlab`, CVE repo Chainguard Academy sebagai `nginx`, CVE Pandora FMS sebagai
  `grafana`. Kandidat NVD/Tenable sekarang hanya dipakai kalau nama tech muncul di vendor, product,
  packageName, atau CPE record MITRE (jatuh ke ringkasan kalau CNA tidak mengisi produk).
- **CVE yang kena beberapa tech hanya menempel ke satu tech.** Dedup per `cve_id` yang global
  membuat CVE multi-produk (mis. Atlassian: Jira + Confluence + Bamboo) hanya tercatat di tech yang
  kebetulan ketemu duluan, jadi client yang hanya punya tech lain tidak pernah dapat. Sekarang tiap
  client yang punya salah satu tech terdampak dapat barisnya; client dengan beberapa tech terdampak
  tetap satu baris, dengan tech yang paling awal menurut abjad.

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
