# Changelog

Format ngikutin [Keep a Changelog](https://keepachangelog.com/), versi
ngikutin `pyproject.toml` (root). Baca lewat `GET /api/changelog` (API,
router `changelog.py`) -- parser-nya expect header persis
`## [versi] - tanggal`, jangan ubah formatnya tanpa liat
`apps/api/src/cti_api/routers/changelog.py`.

## [0.8.9] - 2026-10-26

**Model lokal kini menilai relevansi tiap artikel dari judulnya: artikel yang jelas berita ancaman (p >= 0,85) melewati panggilan LLM classify, sisanya tetap ke LLM. Model berlatih sendiri tiap minggu dari label instance itu, mulai dari mode shadow, dan gate menyala/mati otomatis dari kesepakatan terukur dengan LLM.**
Satu migrasi (`c4f1a9d27e6b`), tanpa kunci `.env` baru. Evaluasi pada label prod (2.112 judul unik, embedder asli): holdout 14 hari band 54,5% dengan kesepakatan 98,1%, CV 5-fold band 52,2% dengan kesepakatan 97,6% (ambang 0,85). Perkiraan: sekitar 42% panggilan classify berkurang (band x (1 - sampel audit 20%)).

**Saat upgrade dari 0.8.8:** `make deploy` (migrasi jalan otomatis). Model pertama dilatih sendiri dalam satu jam setelah worker naik, atau paling lama 24 jam kemudian bila percobaan itu dilewati atau ditolak (pemicu latih ulang punya cooldown 24 jam; tugas `relevance.evaluate` tiap jam memicunya bila belum ada model aktif; pelatihan rutin Minggu 02:00 lokal). Instance dengan label kurang dari 1.000 judul (atau kurang dari 100 per kelas) mencatat run `skipped` beserta alasannya. Model mulai dari shadow dan baru menyala sendiri setelah 200 judul dalam 14 hari menunjukkan kesepakatan >= 95%. Untuk menahan gate tetap mati di prod, isi `RELEVANCE__MODE=shadow` di `.env` prod sebelum deploy. `STORY__EMBEDDING_SIMILARITY` tetap 0 (aturan embedding story mati) sampai diaktifkan. Image `worker-nlp` kini mengunduh model (unduhan sekitar 90 MB, sekitar 88 MB di disk) dari huggingface.co saat build (bukan saat jalan).
Catatan dev: `.env` dev sengaja memakai `RELEVANCE__GATE_MIN_AGREEMENT=0.94` (label dev dari model gratis lebih berisik; model pertama dev 94,89% ditolak di 0,95). **Jangan salin baris itu ke prod**: prod tetap default 0,95. Detail di `docs/LLM_ASSIST_REDESIGN.md` bagian "P5 on dev".

### Ditambah
- Tabel `relevance_models` (artefak model, metrik holdout, status `active`/`retired`/`rejected`, gate state) dan repository-nya.
- Model tiga kelas (`reject`, `best_practice`, `threat_news`) dari TF-IDF kata dan karakter plus embedding MiniLM, dilatih dari `articles` dan `rejected_articles` (override analis berlaku, judul di-dedup, keputusan gate/Tier 0, warisan story dan baris gagal tidak jadi label).
- Tugas `relevance.train` (mingguan) dan `relevance.evaluate` (tiap jam): gate menyala di 200 judul dengan kesepakatan >= 95%, mati di bawah 92% pada 50 sampel audit, dengan alert Telegram untuk perubahan dan pelatihan yang ditolak.
- Gate relevansi di pipeline: keputusan `gated` melewati classify, vonis insiden dan korban datang dari aturan Tier 1, 20% sampel audit (deterministik dari hash URL) tetap memanggil LLM, dan hasilnya dicatat di `raw_enrichment.relevance`. Gagal apa pun jatuh ke LLM classify.
- Mode `RELEVANCE__MODE` (`auto`, `shadow`, `off`) dan pengaturan `RELEVANCE__*` lain (semua punya default).
- Aturan judul berbasis embedding untuk story dedup, opsional lewat `STORY__EMBEDDING_SIMILARITY` (default 0). Replay fixture pada 0,8: 194 follow-up.
- Bagian "Relevance model" di Data health (model aktif, mode, status gate, kesepakatan band dan audit, panggilan classify yang dihindari 24 jam dan 7 hari).
- Alat evaluasi `tools/eval/relevance_eval.py` (holdout 14 hari + CV 5-fold pada ekspor label).

### Diubah
- Image `worker-nlp` membawa model embedding MiniLM (unduhan sekitar 90 MB, sekitar 88 MB di disk) dan memuatnya dengan `local_files_only`; model tidak pernah diunduh saat jalan.
- CI smoke import di dalam image ikut memuat model, sehingga model yang hilang menggagalkan build, bukan deploy.

## [0.8.8] - 2026-10-25

**Setiap artikel yang diterima kini melewati Tier 1 deterministik (tanpa LLM) yang mengekstrak aktor, malware, TTP dan industri dari teks penuh, lengkap dengan label asal datanya (kecuali artikel best practice: hanya malware dan industri, tanpa TTP dan tanpa aktor tersimpan).**
Satu migrasi (`b8e2c4a6d1f3`), **tanpa kunci `.env` baru.** LLM classify dan TTP tetap jalan; Tier 1 hanya melengkapi.

**Saat upgrade dari 0.8.7:** `make deploy` (migrasi jalan otomatis). Artikel lama tidak berubah sendiri. Untuk mengisi artikel yang sudah ada,
jalankan manual `python -m cti_enrich.backfill_tier1 [--since YYYY-MM-DD] [--limit N] [--sleep S] [--dry-run]` (hanya menambah baris,
tanpa LLM, aman diulang). Untuk menyatukan nama aktor lama berbentuk alias dengan nama kanonik, jalankan manual
`python -m cti_enrich.canonicalise_actors` (dry-run, di-rollback) lalu `python -m cti_enrich.canonicalise_actors --apply`. Aman diulang.

### Ditambah
- Aktor dan malware dicari di teks penuh lewat kamus ATT&CK + `threat_actor_groups`, alias dipetakan ke nama kanonik, dengan aturan kata
  konteks untuk nama yang berupa kata umum.
- Nama utilitas Windows dari ATT&CK (at, cmd, net, dst.) hanya cocok sebagai `<nama>.exe`, dan nama kata-umum butuh kata konteks.
- TTP keyword tidak memberi bonus confidence. Rule keyword T1078 dan "powershell" polos dibuang setelah evaluasi.
- TTP explicit dari ID `T####` di teks, dan TTP keyword dari peta ~60 teknik. Gabungan per ID: explicit > llm > keyword.
- Industri dari taksonomi kata kunci, hanya dipakai saat LLM cuma memberi "General".
- Rule confirmed-incident berjalan shadow (hasilnya di `raw_enrichment`, belum memengaruhi perilaku).
- Label sumber: `article_ttps.source` dan `evidence`, `article_threat_actors.source`, `article_industries.source`, serta tabel baru `article_malware`.
- `GET /api/articles/{id}/inferred-ttps` (dihitung saat dibaca dari relasi ATT&CK aktor dan malware artikel).
- Parameter `ttp_source` pada daftar artikel dan heatmap MITRE.
- Modal artikel menampilkan asal tiap TTP, malware, dan TTP inferred.
- Alat evaluasi `tools/eval/tier1_eval.py`.
- `python -m cti_enrich.canonicalise_actors [--apply]`: perintah sekali jalan yang mengganti nama alias lama ke nama kanonik di
  `article_threat_actors`, `ta_watchlist`, `ta_profiles` dan daftar aktor di kriteria PIR, lalu mencetak jumlah per `lama -> baru`, supaya
  satu aktor tidak tampil sebagai dua seri (mis. "Midnight blizzard" dan "Apt29"). Baris alias yang nama kanoniknya sudah ada di
  artikel/watchlist client/PIR yang sama digabung (dihapus). Bila dua profil TA jatuh ke nama yang sama, profil dengan `generated_at`
  terbaru dipertahankan dan sisanya dihapus (namanya dicetak).

### Diubah
- Aktor dicari di teks penuh, jadi sebagian artikel baru pindah dari "Global Article" ke "TA Group Article", dan alert Telegram mendapat
  baris "Related Threat Actor".
- TTP keyword ikut tampil di baris TTP alert.
- Industri dari keyword bisa memicu penanda OT.
- Tagging tweet X Intel tidak berubah (nama, urutan daftar, dan nama kata umum seperti "Akira" tetap ditandai tanpa kata konteks).

### Catatan perilaku
- Confidence artikel baru lebih sering naik: aktor Tier 1 dari teks penuh memberi bonus aktor, dan TTP explicit ikut dihitung (juga di
  artikel Tier 0 dan follow-up story yang sebelumnya 0). Recompute confidence memakai aturan yang sama (TTP keyword tanpa bonus).
- Aturan kata konteks berlaku untuk SETIAP nama satu kata yang hanya dikenal dari `threat_actor_groups`, bukan hanya kata umum: judul
  "ShinyHunters members ..." tanpa kata konteks tidak lagi menandai aktor.
- Perubahan `threat_actor_groups` / `ta_whitelist` dari UI baru berlaku ke artikel paling lambat 1 jam per proses worker (cache kamus).
- Nama aktor lama berbentuk alias (mis. "Lazarus") tetap apa adanya; artikel baru memakai nama kanonik ATT&CK ("Lazarus group"), jadi
  seri bisa terpecah sampai `canonicalise_actors --apply` dijalankan. Backfill tidak menambah nama kanonik bila alias yang sama sudah ada
  di artikel.
- `canonicalise_actors` hanya mengubah nama yang di kamus Tier 1 berjenis aktor; nama di luar kamus, nama yang dikenal sebagai
  malware/tool (mis. "Qilin"), `raw_enrichment`, `cve_threat_actors` dan `ioc_threat_actors` tidak disentuh. Beda huruf besar saja tidak
  dianggap alias. Ukuran per 2026-10-25: prod 7 baris artikel (6 nama), dev 4 baris; satu profil TA ("apt36" -> "Transparent tribe").
- Watchlist/profil yang ditambahkan nanti dengan nama alias tetap tidak cocok dengan artikel baru berbentuk kanonik; perintah ini hanya
  membereskan data yang sudah ada.

## [0.8.7] - 2026-10-25

**Artikel yang membahas peristiwa yang sama dikelompokkan jadi satu "cerita" (story) saat ingest, dan artikel lanjutan memakai ulang
klasifikasi artikel pertama tanpa memanggil LLM.** Satu migrasi, **tanpa kunci `.env` baru** (semua `STORY__*` punya default).

**Saat upgrade dari 0.8.6:** `make deploy` (migrasi jalan otomatis). Untuk mematikan fitur ini: `STORY__ENABLED=false` lalu restart
worker; pipeline kembali persis seperti 0.8.6 (classify sebelum fetch, tanpa tulisan ke `stories`).
- Cerita lama tidak terbentuk sendiri. Untuk mengelompokkan artikel yang sudah ada, hitung dulu dengan
  `python -m cti_enrich.story_backfill --dry-run` (hanya menghitung lalu rollback), lalu jalankan tanpa `--dry-run`
  (opsional `--since YYYY-MM-DD`). Backfill hanya menulis `stories`, `story_id` dan `story_match`; tanpa LLM, tanpa alert, dan aman
  diulang.

### Ditambah
- Tabel `stories` serta kolom `articles.story_id` dan `articles.story_match` (`lead`, `cve`, `title_exact`, `title`).
- Pencocok cerita deterministik: CVE yang sama (paling banyak 5 CVE kunci, minimal 50% overlap; bila seri, cerita dengan anggota
  lebih banyak lalu id terkecil), judul identik dari sumber mana pun, atau judul mirip (TF-IDF >= 0.5) dari sumber lain. Kata periode
  seperti "report", "weekly", "Q3" atau nama bulan tidak dihitung, dan CVE yang berbeda memveto kecocokan judul. Jendela 72 jam, umur
  cerita maksimum 7 hari.
- Badge "+N sumber" pada kartu artikel (menuju daftar artikel dengan filter `story_id`); di detail artikel lanjutan ada keterangan
  klasifikasi diwarisi dari artikel pertama.
- `GET /api/articles?story_id=` dan field `story` / `classify_inherited_from` pada artikel.
- Data health: cerita baru, artikel lanjutan, persentase klasifikasi diwarisi, dan perkiraan panggilan LLM yang dihemat (24 jam dan 7 hari).
- Task harian `story.purge_empty` (antrean `maintenance`) menghapus cerita kosong yang lebih tua dari `STORY__MAX_AGE_DAYS`.
- Pengaturan `STORY__ENABLED`, `STORY__WINDOW_HOURS`, `STORY__MAX_AGE_DAYS`, `STORY__MAX_KEY_CVES`, `STORY__CVE_OVERLAP`,
  `STORY__TITLE_SIMILARITY`.

### Diubah
- Dengan `STORY__ENABLED=true`, `fetch_text` jalan sebelum classify (untuk membaca CVE dari isi artikel); artikel yang ditolak classify
  kini juga ikut mengunduh teksnya.
- Artikel lanjutan mewarisi klasifikasi artikel pertama dan melewati classify serta ekstraksi TTP; ringkasan, IOC, skor, routing dan
  alert tetap per artikel. TTP tidak disalin ke artikel lanjutan.
- Sumber Tier 0 (`default_relevance="always"`) ikut bergabung ke cerita tetapi tidak pernah mengisi atau mewarisi klasifikasi.
- Artikel pertama yang ditolak classify tidak menghapus ceritanya; hanya purge harian yang membuang cerita kosong.
- Replay pada snapshot dev (1.401 artikel): 171 artikel lanjutan; gelombang PHP2Shell 24 artikel jadi satu cerita, NetScaler 15,
  Atlassian 9.
- `scikit-learn` jadi dependensi eksplisit `cti-enrich` (sudah ada di `uv.lock` lewat `cti-api`, tidak ada paket baru).

## [0.8.6] - 2026-10-25

**Sumber terstruktur tidak lagi melewati LLM, IOC disimpan dalam bentuk kanonik, allowlist menandai (bukan membuang) IOC infrastruktur,
dan skor artikel kini berasal dari grade sumber.** Tiga migrasi, **tanpa kunci `.env` baru.**

**Saat upgrade dari 0.8.5:** `make deploy` (migrasi jalan otomatis; deploy mengambil backup Postgres lebih dulu, dan penggabungan
IOC kanonik **tidak bisa dibatalkan**, jadi backup itu satu-satunya jalan mundur).
- IOC bertipe CVE dipindahkan dari tabel `iocs` ke tabel baru `article_cves`.
- Allowlist sekarang menandai IOC (`auto_suppressed`, alasan `allowlist:<tipe>:<entri> (infrastructure-abuse)`), tidak membuangnya.
- Grade bawaan sumber muncul di halaman Source reliability.
- Semua skor artikel dihitung ulang sekali setelah start pertama (task `confidence.recompute_all`). Bila broker mati saat start,
  jalankan `POST /api/articles/confidence/recompute` manual.
- Sebelum deploy ke prod, cek `SELECT count(*) FROM articles WHERE overrides ? 'confidence_score'`: baris di situ mempertahankan
  skor lamanya sebagai override analis. Catat hasilnya saja; perbaikannya dijalankan sesudah deploy (lihat di bawah).
- Sesudah deploy, cek:
  - bila hitungan di atas > 0: semua `overrides.confidence_score` yang ada ditulis mesin oleh recompute lama (tidak ada UI analis
    yang menulisnya), jadi jalankan `UPDATE articles SET overrides = overrides - 'confidence_score' WHERE overrides ?
    'confidence_score'`, lalu `POST /api/articles/confidence/recompute`. **Hanya sesudah 0.8.6 live**: di 0.8.5 POST itu menulis
    `overrides.confidence_score` untuk SETIAP artikel, jadi menjalankannya sebelum deploy justru mengunci semua skor;
  - baris log `confidence_recompute_all` muncul; bila tidak, jalankan `POST /api/articles/confidence/recompute` manual (worker lama
    bisa membuang task itu selama `up -d`);
  - `SELECT count(*) FROM iocs WHERE type='cve'` = 0; bila tidak, jalankan ulang `DELETE FROM iocs WHERE type = 'cve'`.

### Ditambah
- `ScraperMeta.content_kind` dan `default_relevance`: sumber terstruktur (`cisa_kev`, `exploitdb`, `cis`) melewati classify LLM dan
  ekstraksi TTP.
- Tabel `article_cves` (artikel ke CVE), menggantikan IOC bertipe CVE.
- Seed allowlist 124 domain infrastruktur yang sering disalahgunakan (tanpa layanan subdomain-per-tenant; URL dengan path tidak
  pernah ditandai).
- Grade Admiralty bawaan per `content_kind` (`origin` = `default` atau `analyst`); chip skor di UI, misalnya "B2 · 72".
- Parameter `GET /api/iocs?include_suppressed=` dan filter "suppressed" di tabel IOC.

### Diubah
- Nilai IOC disimpan kanonik (refang, huruf kecil; path dan query URL dipertahankan); web menampilkannya dalam bentuk defanged.
- IOC yang ditandai allowlist keluar dari ekspor STIX, statistik, kampanye, hitungan recap, dan antrean false positive.
- Skor confidence artikel = grade sumber + bonus TTP/actor, bukan lagi self-rating LLM.
- `threat_feed_entries` ikut dikanonikalkan.

## [0.8.5] - 2026-10-24

**Setiap panggilan LLM sekarang tercatat, artikel yang parkir karena gangguan LLM diputar ulang otomatis, dan beberapa prompt yang
menyatakan hal di luar data diperbaiki.** Satu migrasi, dua entri beat baru, **tanpa kunci `.env` baru.**

**Saat upgrade dari 0.8.4:** `make deploy` (migrasi jalan dulu, lalu `beat` restart karena ada dua entri beat baru:
`enrich.auto_replay` dan `llm.purge_calls`). Migrasi membuat tabel `llm_calls` dan menambah dua kolom di `rejected_articles`;
baris `permanent` lama yang berasal dari BadRequest/NotFound/Authentication/PermissionDenied otomatis menjadi `config`. Baris
`config` yang parkir akan mulai diputar ulang otomatis setelah deploy (canary dulu, lalu batch bila model sehat).
Token input task `ttp` naik sekitar 3x karena TTP sekarang membaca sampai 6.000 karakter teks artikel, bukan ringkasan
2.000 karakter.

### Ditambah
- Tabel `llm_calls`: log tiap panggilan LLM (nama task, model, versi prompt, token, latensi, status `ok`/`empty`/`error`).
  Dihapus otomatis setelah 90 hari.
- Data health punya bagian LLM: status model, artikel yang parkir, dan pemakaian token per task (24 jam dan 7 hari).
- Auto-replay artikel parkir tiap 10 menit: satu artikel canary bila status model belum diketahui, batch sampai 20 bila model
  sehat, maksimal 3 percobaan dengan backoff, dan alert Telegram hanya untuk artikel yang diposting dalam 24 jam terakhir.

### Diubah
- Error konfigurasi gateway (400/401/403/404) langsung diparkir sebagai `config`, tidak dihitung sebagai kegagalan artikel
  permanen.
- Prompt classify lebih ringkas dan murah, dengan contoh batas kasus.
- Enam panggilan LLM yang balasannya di-parse sebagai JSON sekarang memakai JSON mode.

### Diperbaiki
- Ekstraksi TTP hanya menyimpan TTP yang bukti kutipannya ditemukan di teks lengkap artikel.
- Metadata newsletter tidak lagi mengarang isi yang tidak ada di data.
- Profil threat actor disusun dari data ATT&CK, bukan tebakan model.
- Exec brief membedakan berita ancaman dari insiden yang terkonfirmasi.
- Email CVE memakai field hasil hitungan, bukan diminta dikarang ulang oleh model.

## [0.8.4] - 2026-10-24

**Permission role sekarang benar-benar ditegakkan per endpoint, dan data antar-client tidak lagi bocor.** Sebelumnya 26 permission
disimpan di role tetapi tidak ada endpoint yang mengeceknya. **Tanpa migrasi, tanpa kunci `.env` baru, dan tanpa entri beat baru.**

**Saat upgrade dari 0.8.3:** deploy biasa (`make deploy`); image `api` dan `web` berubah. Role sistem (`superadmin`, `admin`,
`analyst`) diperbarui otomatis saat `api` start. **Custom role** perlu ditambah `manage_cve` dan `view_ops` lewat Admin kalau
penggunanya masih harus bisa ack/ticket CVE dan membuka Scrapers/Data health.

### Ditambah
- `GET /api/auth/me` dan respons login membawa `permissions` (permission efektif role user). Web memakainya untuk menyembunyikan
  tombol yang tidak boleh dipakai role tersebut: generate recap/brief/profil TA, kirim newsletter dan email CVE, sync ATT&CK,
  edit grup/whitelist TA, source reliability, IOC (hapus, allowlist, tautan aktor), akun X, aksi Scrapers, Restore/Replay
  artikel, aksi CVE/tech/paket, PIR/RFI, export, dan bagian Admin.

### Diubah
- Setiap endpoint `/api` sekarang mensyaratkan permission. Endpoint yang dulu terbuka untuk semua user login sekarang ditolak
  `403 Missing permission: ...` bila role-nya tidak punya izin itu. Untuk role **analyst** artinya: tidak bisa lagi mengirim/
  resend newsletter, mengirim email CVE, generate recap/exec brief/profil TA (LLM), mengubah grup/whitelist TA, sync ATT&CK, atau
  mengubah source reliability. Analyst tetap bisa membaca semua halaman, triase CVE, PIR/RFI, watchlist TA, feedback IOC, mindmap,
  dan override verdict scorecard recap.
- Permission baru: `manage_cve` (ack, ticket, FP CVE, tech yang dimonitor, paket) dan `view_ops` (Scrapers, Data health).
- `X-Client-ID` untuk client yang bukan milik user sekarang ditolak `403`, bukan diam-diam diganti ke client pertama user. Web
  membuang header itu di proxy dan mengembalikan client aktif ke client milik user setelah login.

### Diperbaiki
- Halaman Exec tidak lagi kosong (403 "Role preview is admin-only") untuk non-admin yang memakai browser bekas admin: pilihan
  "Role preview" yang tersimpan di browser hanya dikirim oleh admin.
- `GET /api/crossref/{cve,pir,ta}`, `GET /api/stix/pirs`, dan mindmap PIR tidak lagi menampilkan PIR dan CVE yang di-track client
  lain. PIR milik client lain dijawab `404`.

## [0.8.3] - 2026-10-24

**Angka di Dashboard, Exec, CVE, Recap, dan Newsroom sekarang sesuai datanya** (hasil audit UI vs data, `docs/UI_DATA_AUDIT.md`).
**Tanpa migrasi, tanpa kunci `.env` baru, dan tanpa entri beat baru.**

**Saat upgrade dari 0.8.2:** deploy biasa (`make deploy`); image `api`, `web`, dan worker berubah (scraper RSS dan enrichment).
Data lama tidak dikoreksi otomatis: artikel yang sudah tersimpan tetap memakai tanggal scrape, aktor "Cobalt strike", dan judul lamanya.

### Diubah
- Toggle "Incidents only" di Dashboard dan Exec berganti nama jadi **"Threat news only"** (isinya memang berita ancaman, bukan
  insiden terkonfirmasi). Kartu utama Exec dinamai sesuai filter aktif, dan brief Dashboard ikut toggle yang sama
  (`GET /api/dashboard/attention` menerima `incident_only`).
- "CVE kritis terbuka" dan KEV terbuka memakai definisi backlog CVE Dashboard: ticket Not Affected, Risk Accepted, dan yang sudah
  selesai tidak lagi dihitung. Sub-label KEV menyebut "semua severity".
- Rating MTTA di CVE Dashboard jadi **Backlog** bila kurang dari separuh CVE di baris itu sudah di-acknowledge.
- Tren "naik tajam" dan topik aktif tidak lagi menandai "baru"/persen bila periode pembanding hampir kosong; respons trending dan
  topik membawa `baseline_reliable`.
- Scraper RSS memakai tanggal dari feed (`pubDate`, Atom `published`/`updated`, `dc:date`), bukan waktu scrape. Sebelumnya 61 scraper
  memakai waktu scrape, sehingga postingan lama tampil sebagai berita baru.
- Nama yang menurut ATT&CK adalah software (mis. Cobalt Strike) tidak lagi dicatat sebagai threat actor, dan nama terpanjang
  dicocokkan lebih dulu.
- Judul artikel dibersihkan saat ingest: entity HTML di-decode, judul berupa nama berkas dari repo GitHub jadi kalimat.

### Diperbaiki
- Recap yang dibalas kosong oleh model tidak lagi disimpan (HTTP 502, recap lama tetap), dan recap kosong tidak lagi ditandai
  "Grounding check: nothing was dropped".
- Brief Dashboard tidak lagi membandingkan insiden dengan periode lalu yang hampir kosong ("naik 37400%"); aturannya sama dengan
  kartu KPI.
- Korban ransomware tanpa negara di peta Dashboard diberi nama "Negara tidak diketahui".
- X Intel memberi peringatan bila kolektor tweet diam lebih dari 72 jam. Data health menulis "Newest IOC extracted", bukan "sighting".

## [0.8.2] - 2026-10-24

**Redesain Login, Dashboard, dan Newsroom.** Login punya panel brand, Dashboard jadi peta sinyal dunia dengan brief dan daftar
prioritas, Newsroom jadi halaman depan berita utama dengan topik aktif dan rubrik. **Tanpa migrasi, tanpa kunci `.env` baru, dan
tanpa entri beat baru.**

**Saat upgrade dari 0.8.0:** deploy biasa (`make deploy`); image `api` dan `web` berubah. `beat` dan worker tidak perlu restart.

### Ditambah
- **Login baru**: panel brand dengan peta titik dekoratif. Peta ini murni hiasan dan tidak memuat data apa pun sebelum login.
- **Dashboard baru**: peta sinyal dunia, brief dengan tiga aksi, daftar *perlu dibaca*, topik yang *naik tajam*, ransomware,
  CVE exposure, dan konteks klien.
- **Newsroom baru**: berita utama, topik aktif, rubrik, dan panel samping.
- Endpoint `GET /api/dashboard/{map,attention,trending,ransomware,cve-exposure}` dan `GET /api/newsroom/topics`.
- `GET /api/articles` menerima parameter `sort`, `ttp`, dan `confirmed_only`; `GET /api/newsroom/topics` juga menerima
  `confirmed_only`.
- Artikel di respons API membawa field baru `confirmed_incident`.

### Diubah
- Timeline `GET /api/dashboard` sekarang membawa `incidents`.

## [0.8.1] - 2026-10-24

**Perbaikan: user dengan lebih dari satu client tidak lagi ter-logout sendiri.** **Tanpa migrasi, tanpa kunci `.env` baru, dan
tanpa entri beat baru.**

**Saat upgrade dari 0.8.0:** deploy biasa (`make deploy`); hanya image `api` yang berubah.

### Diperbaiki
- **`GET /api/auth/me` kadang 500 untuk user dengan >1 client**: data client dimuat dengan `asyncio.gather` di satu sesi
  database, padahal SQLAlchemy melarang operasi konkuren di satu sesi (`InvalidRequestError: ... concurrent operations are not
  permitted`). Web menganggap 500 itu sebagai sesi habis lalu me-logout user. Sekarang client dimuat berurutan; bentuk respons
  (`client_countries`, `clients_map`) tidak berubah. Ada test regresi baru (`test_me_multiple_clients`).

## [0.8.0] - 2026-10-23

**Halaman baru Data health, dan Dashboard serta `/scrapers` tidak lagi menampilkan angka atau status yang menyesatkan** (ROADMAP #24,
PR-B), plus **retheme web ke token tema** (fokus keyboard yang terlihat, tanpa warna literal). **Tanpa migrasi, tanpa kunci `.env`
baru, dan tanpa entri beat baru.**

**Saat upgrade dari 0.7.4:** deploy biasa (`make deploy`); image `api` dan `web` berubah. `beat` dan worker tidak perlu restart.

### Ditambah
- **Halaman Data health** (`/data-health`, menu baru di antara Scrapers dan Admin): empat bagian dalam satu layar. *Pipeline*
  (heartbeat scheduler, jumlah scraper per status, scraper yang perlu perhatian beserta alasannya); *Enrichment* (gagal 24 jam dan
  7 hari beserta rasionya, artikel yang menunggu replay, kegagalan terakhir, kedalaman antrian `enrich` vs batas backpressure);
  *Source freshness* (artikel, tweet X Intel beserta status `monitor_x`, IOC, cek CVE, sync ATT&CK); *Coverage* (artikel yang punya
  negara/aktor/teknik, dan IOC per tipe yang sudah dicek provider reputasi). Ambang warnanya ditulis di "How to read this page".
- **`GET /api/data-health`** (semua user login, cache 60 detik per proses). Kesegaran CVE dan ATT&CK tetap dari
  `/api/cve/freshness` dan `/api/attack/status`.
- `/scrapers`: legenda status ("What the statuses mean"), kolom **Error** di tab Runs (stage, tipe, dan pesan singkat; traceback
  tidak pernah ditampilkan) dan durasi yang terbaca ("12.4 s"), serta ikon centang/silang dengan teks pembaca layar di tab Items
  (dulu sel kosong).

### Diubah
- **Delta Dashboard mengikuti aturan Exec**: bila kurang dari separuh hari periode sebelumnya punya artikel, kartu menulis "no
  prior-period data" alih-alih "+316" (`DashboardStats.prev_period_reliable`).
- **Scraper DISABLED punya alasan**: siapa yang mematikan (admin, default kode, atau digantikan mirror CVE) dan alasan admin
  (`ScraperListItem.disabled_by`, `paused_reason`). Chip "Needs attention" menampilkan alasannya, bukan hanya di tooltip.
- **Retheme ke token**: band "Need Attention", scrim dialog, dan warna amber/emerald lama memakai token tema (`bg-hero`,
  `bg-overlay`, ...); cincin fokus keyboard `ring-focus` (3.0-3.9:1, dulu 2.2-2.6:1); ukuran huruf literal (`text-[13px]`, 68 tempat)
  jadi skala `text-xs`/`text-2xs`. Kartu tweet bisa dibuka dengan keyboard (Enter/Spasi).
- `build_scraper_health` dan status scheduler pindah ke `cti_api.services.scraper_health` (dipakai `/api/scraper/health` dan
  `/api/data-health`); perilaku `/api/scraper/health` tidak berubah.

### Diperbaiki
- **`/scrapers` tidak lagi menulis "ok" saat data kesehatan belum datang atau gagal**: statusnya skeleton saat memuat dan UNKNOWN
  bila gagal.
- **Dashboard**: statistik Threat Actor yang gagal dimuat tidak lagi menghilangkan semua kartu KPI artikel.
- Teks peringatan amber 1.9:1 di atas beige dan track skor yang tak terlihat di mode terang (retheme).
- Alert geopolitik di Campaign Clusters punya ikon (dulu glyph kosong) dengan teks pembaca layar.

### Diketahui / belum dikerjakan
- Halaman Data health dan perubahan `/scrapers` belum dicek visual di dev atau prod; baru di stack lokal.
- Tautan dari Data health ke Newsroom membuka Newsroom biasa; Newsroom belum membaca parameter URL, jadi tab "Filtered Articles >
  Failed enrichment" dibuka manual.

## [0.7.4] - 2026-10-21

**Satu artikel tidak lagi muncul dua kali di Telegram, dan satu thread yang rusak tidak lagi menghentikan alert ke topik lain.** Di prod
(14 hari sampai 2026-10-21), 30 dari 657 artikel yang lewat `route()` dikirim dengan teks yang persis sama ke dua thread: `ot` (pre-check
industri OT) dan topik hasil cascade. **Tidak ada migrasi dan tidak ada kunci `.env` baru.**

**Saat upgrade dari 0.7.3:** deploy biasa (`make deploy`) dan restart `worker-nlp` supaya kode routing yang baru terpakai. Di sisi
konfigurasi, 40 dari 46 artikel `global` dalam 24 jam gagal dikirim dengan `Message thread not found`: entri `global` di
`TELEGRAM__THREAD_IDS` menunjuk thread yang sudah tidak ada. Perbaiki ID-nya (halaman Third-party Keys atau `.env`). Artikel yang
terlewat sudah tersimpan, tetapi alert-nya tidak akan dikirim ulang.

### Diubah
- **Pre-check OT tidak lagi mengirim ke topik `ot`.** Artikel yang industrinya kena OT (`critical infrastructure`, `energy & utilities`,
  dst.) sekarang dikirim SEKALI ke topik hasil cascade, dengan satu baris penanda `OT-relevant: Yes (...)` di pesan. Cabang cascade
  `ot_status` (artikel OT sungguhan) tetap ke `ot`, sekali, tanpa penanda. `news_type` tidak berubah. Alert tweet tidak diubah (tweet OT
  tetap ke `ot` dan `feed_twitter`).

### Diperbaiki
- **`route_alerts` mengirim ke tiap topik sekali dan tidak berhenti di topik pertama yang gagal.** Topik kembar dibuang. Kalau satu
  thread error, topik sisanya tetap dicoba, kegagalannya dicatat (`alert_send_failed` beserta nama topiknya), lalu error pertama
  di-raise seperti sebelumnya, jadi penanganan di pipeline tidak berubah.

## [0.7.3] - 2026-10-21

**Perbaikan keamanan hasil audit dan restyle Dashboard serta Newsroom.** Tanpa migrasi dan tanpa kunci `.env` baru. Satu perubahan
perilaku API: `GET /api/ta/watchlist/navigator-layer` kini wajib login.

**Saat upgrade dari 0.7.2:** deploy biasa (`make deploy`). Perbaikan `fetch_text` dan alert Telegram berjalan di worker, jadi restart
semua worker; container `web` ikut dibangun ulang untuk restyle.

### Diperbaiki
- **Scoping tenant di watchlist Threat Actor**: `GET /api/ta/watchlist-names`, `POST /api/ta/watchlist`, dan
  `GET /api/ta/watchlist/navigator-layer` memakai client milik akun (`effective_client_id`), sehingga header `X-Client-ID` milik
  client lain diabaikan.
- **`navigator-layer` tidak lagi publik**: wajib login (header `Authorization`). Tombol "Open in ATT&CK Navigator" di panel watchlist
  memakai endpoint ini; fetch lintas-situs dari Navigator eksternal tidak membawa token.
- **`fetch_text` hanya mengambil http(s) ke alamat publik**: URL dari feed tidak lagi bisa menjangkau host internal (loopback,
  service compose, metadata cloud).
- **Alert Telegram di-escape**: judul, URL, industri, TTP, aktor, dan negara di-`html.escape` sebelum dikirim dengan `parse_mode`
  HTML. Judul feed bertag seperti `<redacted>` membuat Telegram menolak pesan dan alert hilang diam-diam.

### Diubah
- **Dashboard**: angka utama punya hierarki (`StatBox` prop `emphasis`), label section menampilkan cakupan data, bar chart satu warna
  data, dan skeleton seukuran grid.
- **Newsroom**: panel tanpa titik berwarna dan judulnya `<h2>`, tombol refresh berikon dengan `aria-label`, kartu artikel berupa
  `<button>` (bisa difokus, Enter membuka), filter berlabel, dan `aria-label` pada filter ransomware.

### Diketahui / belum dikerjakan
- Guard `fetch_text` belum mengecek redirect dan DNS rebinding.
- Halaman `/exec` memakai komponen yang sama dengan restyle ini tetapi belum dicek visual di terang dan gelap.
- Tombol Navigator di panel watchlist kini mengarah ke endpoint wajib login, sama seperti dua tombol Navigator lain; perlu diputuskan
  apakah itu perilaku yang diinginkan.

## [0.7.2] - 2026-10-21

**Artikel yang gagal diproses tidak lagi hilang diam-diam, dan status scraper tidak lagi berbohong** (ROADMAP #24, PR-A). Di dev,
101 artikel hilang dalam sehari karena model LLM salah (`Unsupported model`) tanpa alert maupun jalan pulang, dan `github_poc_monitor`
gagal 4 item tiap jam (558 item dalam 7 hari) sementara `/scrapers` menampilkannya OK. **Ada satu migrasi baru (kolom nullable),
tiga kunci `.env` baru yang opsional, dan satu tool ops baru.**

**Saat upgrade dari 0.7.1:** deploy biasa (`make deploy`): migrasi `b7e4c1a9d256` menambah `rejected_articles.failure_kind` dan mengisinya
dari baris lama lewat service `migrate`. Restart `beat` dan semua worker (jadwal beat dibangun saat import dan ada dua task
pemeliharaan baru; kunci `.env` baru punya default, jadi tidak ada yang wajib diisi sebelum deploy). Sesudah memastikan LLM-nya sehat,
artikel yang sudah gagal dikirim ulang dengan `make replay-failed-enrichment` (laporan saja), lalu `ARGS='--apply'`.

### Ditambah
- **`rejected_articles.failure_kind`** (`transient`, `json`, `permanent`; kosong = ditolak klasifikasi) menggantikan penanda teks
  `[enrichment_failed]` yang tidak bisa difilter. Awalan itu tetap ditulis satu rilis agar worker lama tetap terbaca.
- **Alert Telegram saat enrichment gagal final** ke topik `scraper_health` yang sudah ada: satu pesan per jendela
  `WORKER__ENRICH_FAILURE_ALERT_COOLDOWN_MIN` (60), berisi kelas error dan jumlah artikel yang menunggu replay.
- **Replay**: `make replay-failed-enrichment` (`tools/ops/replay_failed_enrichment.py`, laporan saja tanpa `--apply`, `--rate`,
  cek kedalaman antrian tiap kiriman, melewati URL yang sudah jadi artikel dan stub "Manually Restored") dan tombol **Replay** admin
  di Newsroom. Replay senyap: artikel disimpan tanpa alert Telegram (`--alerts` untuk menyalakannya).
- **Tab Newsroom "Filtered Articles"** dengan dua sub-tab, "Not cyber-related" dan "Failed enrichment", menampilkan alasan dan jenis
  kegagalan. API: `GET /api/filtered-articles?kind=unrelated|failed|all`, `POST /api/filtered-articles/{id}/replay` (admin, masuk
  audit log).
- **Reaper dan purge `scraper_runs`**: `scraper.reap_stale_runs` (tiap 30 menit) menutup run `running` yang yatim lebih dari
  `WORKER__SCRAPER_RUN_STALE_HOURS` (2) sebagai `timeout`; `scraper.purge_old_runs` (03:05 UTC) menghapus riwayat lebih tua dari
  `WORKER__SCRAPER_RUN_RETENTION_DAYS` (90, tidak pernah di bawah retensi `scraper_items`).
- `GET /api/scraper/health` membawa `reason`, `items_failed_last`, `consecutive_failing`, dan `last_success_at` per scraper.

### Diperbaiki
- **Respons LLM 200 tanpa `choices`** (model `openrouter/free`) di-retry seperti 5xx. Sebelumnya `TypeError` tidak di-retry dan 3 artikel
  hilang di prod (20-21 Okt: cybersecnews, qualys, wiz).
- **Run scraper dengan item gagal tidak lagi `ok`**: statusnya `partial` dan scraper `degraded` dengan alasan; baris `running`
  dilewati saat menilai kesehatan. Setup run yang gagal menutup run sebagai `fetch_error` (dulu run nyangkut `running` selamanya).
- **Digest Telegram `scraper_health`** menyertakan alasan dan tidak mengulang daftar masalah yang sama dalam
  `WORKER__SCRAPER_HEALTH_REPEAT_MIN` (240); daftar yang berubah langsung terkirim.
- **Tombol Restore** menolak baris yang gagal di-enrich (409): ia hanya membuat artikel tanpa enrichment dan stub itu memblokir replay.
  Teks lama di Newsroom yang menjanjikan "re-queue through NLP pipeline" dihapus.
- `celery_task_id`, `worker`, dan `attempt` pada `scraper_runs` kini terisi (dulu kosong di semua baris, retry tampil `attempt=1`).
- Pesan error enrichment di-scrub dari secret SEBELUM dipotong 300 karakter, bukan sesudahnya.

### Diketahui / belum dikerjakan
- Halaman **Data health**, delta Dashboard yang tidak menyesatkan, dan alasan DISABLED di `/scrapers` menyusul di PR-B (ROADMAP #24).
- Indeks `scraper_runs (scraper_id, started_at)` dan retensi tabel lain belum dikerjakan: di skala sekarang query terlama 22 ms.

## [0.7.1] - 2026-10-17

**Redesain tampilan web dan perbaikan aksesibilitas hasil audit visual.** Hanya frontend (`apps/web`): tanpa migrasi, tanpa kunci
`.env` baru, tanpa perubahan API. Deploy biasa (`make deploy`); hanya container `web` yang berubah.

### Diubah
- Header halaman seragam (judul besar, deskripsi, slot aksi) di semua halaman, dan judul tab per halaman
  ("CVE Tracker · Vareon Intelligence").
- Kartu memakai satu gaya (`surface-raised`: bayangan bertinta burgundy + garis tipis); panel KPI dashboard jadi satu panel,
  grid dashboard asimetris (peta 8/4, timeline 7/5, TTP 7/5), dan angka KPI memakai pemisah ribuan.
- Sidebar bisa diciutkan jadi icon rail (opsional, default tetap terbuka, pilihan tersimpan di browser, tooltip + keyboard).
- Ukuran teks data `text-xs` 12px → 13px. Di bawah 640px tombol, input, select, dan nav utama setinggi 44px.
- Nilai data (IOC, CVE/TTP ID, ID dan jadwal scraper, IP audit, 4 karakter key) memakai IBM Plex Mono. Sebelumnya `font-mono`
  ternyata Google Sans Flex (proporsional) di 582 tempat.
- Tab pil jadi komponen `TabPills` (role tab, navigasi panah kiri/kanan); `/intelligence` jadi `<nav>` dengan `aria-current`.
- Delta KPI dengan pembanding kecil (< 10) menampilkan selisih absolut ("+316") alih-alih persen ekstrem ("▲ 28400%").

### Ditambah
- Skip-link "Skip to content", skeleton shell saat sesi dimuat, dan halaman 404 / error / login bermerek.

### Diperbaiki
- Kontras mode terang (WCAG AA): Risk Matrix (87 elemen), IOC (73), Newsroom (20), X Intel (14), Exec (9), Admin (5), Scrapers (4),
  Recap (1). Token teks-di-atas-tint baru (`--primary-text`, `--success-text`, dst.); heatmap Exec membatasi alfa tint.
- Teks dialog Changelog dan Executive Brief tidak lagi putih di atas beige di mode terang (`prose-invert`).
- Input date/number (19), checkbox baris CVE, dan tombol hapus IOC kini punya nama untuk pembaca layar; 404, error, dan login punya
  landmark `<main>`; heading IOC tidak lagi melompat h1 → h3.
- Target sentuh minimal 24px; scrollbar horizontal nav mobile tidak lagi tampil sebagai pil abu-abu; kolom Summary tabel CVE tidak
  menyempit di mobile; `100vh` → `100dvh` (bug viewport iOS Safari).

## [0.7.0] - 2026-10-16

**Key third-party bisa diganti dari UI admin, tanpa restart** (ROADMAP #23). Halaman baru **Admin > Third-party Keys**
(khusus superadmin) mengelola key LLM, Telegram, Microsoft Graph, NVD, GitHub, twitterapi.io, X, OTX, AbuseIPDB, dan VirusTotal:
disimpan terenkripsi di database dan berlaku di semua proses dalam sekitar 30 detik, tanpa restart atau rebuild. Secret level
deployment (database, Redis, JWT/session, OIDC) tetap di `.env`. **Ada satu migrasi baru, dua kunci `.env` baru yang opsional,
dan satu dependensi langsung baru (`cryptography`, sebelumnya hanya ikut transitif). Tanpa `SECRETS_ENCRYPTION_KEYS` fiturnya
mati dan perilaku sama persis seperti 0.6.2.**

**Saat upgrade dari 0.6.2:** deploy biasa (`make deploy`): migrasi `a3f81c2d9b47` (tabel `runtime_secrets`, baru dan kosong) jalan
lewat service `migrate`. Untuk MENGAKTIFKAN fiturnya: bikin master key (`python -c "from cryptography.fernet import Fernet;
print(Fernet.generate_key().decode())"`), taruh di `.env` host sebagai `SECRETS_ENCRYPTION_KEYS`, simpan salinannya TERPISAH dari
backup database, lalu restart api dan semua worker sekali supaya memuatnya. Sesudah itu key diganti dari halaman, tanpa restart.
`SECRETS_LLM_URL_ALLOWED_HOSTS` hanya perlu diisi kalau mau memakai gateway LLM kustom dari halaman (di luar `dev` URL kustom
ditolak kecuali hostnya terdaftar). Nilai key di `.env` tetap jadi cadangan: samakan dengan key yang aktif atau kosongkan, jangan
biarkan key yang sudah dicabut di sana.

### Ditambah
- **Halaman Third-party Keys** (`/admin/users`, hanya superadmin): status per provider (sumber: override admin, `.env`, atau kosong;
  empat karakter terakhir key; hasil tes terakhir), tombol **Test**, **Edit**, dan **Revert to .env**. Nilai key tidak pernah
  dikirim balik dari server. Edit dan revert meminta password akun yang sedang login. Key baru diprobe ke vendor SEBELUM disimpan:
  key salah ketik ditolak dan tidak ada yang tersimpan. API: `GET /api/secrets`, `PUT` dan `DELETE /api/secrets/{provider}`,
  `POST /api/secrets/{provider}/test` (batas 5 tulis dan 10 tes per menit per user, cooldown 30 detik per provider untuk
  AbuseIPDB, VirusTotal, dan OTX karena tiap tes memakai kuotanya; audit `secret_set`, `secret_clear`, `secret_test`,
  `secret_set_rejected`, `secret_reauth_failed` tanpa nilai secret). Tulis dan hapus pada satu provider diserialisasi dengan
  advisory lock, dan kirim ulang nilai yang sama tidak memakai kuota vendor.
- **Tabel `runtime_secrets` dan `effective_settings()`**: satu blob Fernet per provider berisi semua field override, terikat ke
  provider dan scope; pengganti `get_settings()` di konsumen key (Runner scraper, klien LLM, Telegram, Graph, enrichment IOC).
  Gagal baca database tidak menghidupkan lagi key yang sudah dicabut: override terakhir yang sehat tetap dipakai dan dicoba ulang
  tiap 10 detik. Override `llm` selalu satu paket (provider, model, url).
- **Probe baru**: Graph (cukup meminta token, tidak membuat email), serta AbuseIPDB, VirusTotal, dan OTX (satu lookup `8.8.8.8`
  lewat kode produksi, jadi tes memakai satu lookup dari kuota provider itu).

### Diubah
- **Ganti password (`POST /api/auth/change-password`) sekarang dibatasi**: 5 kegagalan dalam 15 menit memberi 429 dan MENCABUT semua
  sesi akun itu (penghitungnya dipakai bersama konfirmasi password di Third-party Keys). Sebelumnya endpoint ini menerima tebakan
  password tanpa batas dari pemegang cookie sesi, yang sekarang bisa dipakai untuk mengonfirmasi perubahan key.
- Galat validasi 422 di `/api/secrets` tidak lagi memuat `input` (body request): bawaan FastAPI memantulkan key yang baru
  diketik dan password konfirmasi.
- Probe OTX memakai `GET /api/v1/users/me` (endpoint lookup indikatornya publik, jadi key salah pun lolos). 429 dari NVD, GitHub,
  twitterapi.io, dan X di probe sekarang NOTE (key diterima tapi kena batas), bukan FAIL; semua exception probe jadi
  `FAIL "probe error (<tipe>)"`, bukan 500.
- Probe `tools/ops/check_secrets.py` pindah ke `cti_api.services.secret_probes` (halaman admin memakai kode yang sama). CLI-nya
  berperilaku sama dan tetap hanya membaca `.env`.
- Engine sync memakai `connect_timeout` 5 detik (berlaku untuk semua koneksi sync, termasuk Celery) supaya host database yang tidak
  menjawab tidak membekukan event loop API.
- `Settings` memakai `hide_input_in_errors`: galat validasi tidak lagi mencetak potongan nilai secret. Log `httpx` diturunkan ke
  WARNING karena token bot Telegram ada di path URL-nya.

### Diperbaiki
- Daftar penyamaran secret di pesan error (`rejected_articles`, log) tidak mencakup `X__BEARER_TOKEN`, OTX, AbuseIPDB, dan
  VirusTotal; sekarang diturunkan dari satu registry, memuat nilai `.env` dan override, serta master key.

## [0.6.2] - 2026-10-16

**Dashboard utama dan Exec lebih informatif**: perbaikan angka yang menyesatkan di prod. Penyebabnya dua: 62% artikel berlabel
industri "General" (bukan sektor, tapi selalu jadi baris teratas), dan datanya baru ±4 minggu (3 artikel sebelum 21 Sep), jadi
periode pembanding kosong dan lonjakan ingestion terbaca sebagai lonjakan ancaman. **Tanpa migrasi, tanpa kunci `.env` baru,
tanpa dependensi baru, dan tanpa entri beat baru.**

**Saat upgrade dari 0.6.1:** deploy biasa (bangun ulang image api dan web). Tidak ada migrasi dan `beat` tidak perlu restart.

### Ditambah
- **Dashboard utama**: selector periode (7/30/90 hari atau semua) dan "Incidents only"; kartu KPI **Confirmed Incidents**;
  delta vs periode sebelumnya di Total Articles dan Confirmed Incidents; catatan penyebut di chart ("27 of 138 articles name a
  country"; negara, aktor, dan TTP hanya ada di sebagian artikel); cap "Updated" (hasil di-cache 15 menit per proses).
  `GET /api/dashboard` menerima `days` dan `incident_only` (bawaan tetap semua waktu dan semua tipe) dan mengembalikan
  `confirmed_incidents`, `prev_total_articles`, `prev_confirmed_incidents`, `coverage`, `industry_unspecified`, `generated_at`.
- **Exec**: `prev_period_reliable` (periode pembanding dianggap andal bila minimal separuh harinya punya artikel),
  `sector_unspecified`, `risk_volume_only`, dan `pending_fp_total` di payload; total antrean FP tampil ("Showing 20 of N pending").

### Diubah
- **"General" tidak lagi dihitung sebagai sektor**: keluar dari "Top Targeted Industries" dan band "Need Attention" di dashboard
  utama, serta dari Sector Risk Matrix, Highest-Risk Sector, Sector Trend, heatmap, Sector x Actor, dan spike di Exec. Jumlahnya
  dicatat ("N articles with no specific sector"). Konsekuensi: `top_sectors` di payload Exec, yang juga dipakai ringkasan
  Executive Brief, tidak lagi memuat "General".
- **Exec, delta dan NEW/REC**: bila periode sebelumnya kosong atau jarang, KPI menulis "no prior-period data" (dulu "—" di 90 hari
  dan "↑32767%" di 30 hari) dan penanda NEW/REC aktor disembunyikan (CSV: `n/a`).
- **Exec, risk score dan TA velocity** hanya memakai bulan riwayat dengan minimal 30 insiden. Selama belum ada dua bulan seperti itu,
  skor = volume saja (ada catatan di UI); komponen trend dan spike menyala sendiri sesudahnya. Untuk data yang sudah matang
  gating ini tidak mengubah hasil (selain efek "General" keluar dari peringkat).
- **Band "Need Attention"**: "Risk Score" (selalu 50/100 di jendela 30 hari) diganti jumlah insiden sektor teratas; "Open CVE
  Critical" jadi "Critical CVEs (CVSS >= 9)" karena hitungannya tidak memfilter ack atau status.
- Label: "Threat Actors Tracked" jadi "Threat Actors in News"; Exec "Active Spikes" menghitung sektor unik dan tidak lagi mengklaim
  "statistically significant" (ambang z >= 1.5); "Critical CVE Feed" jadi "KEV CVE Feed" (isinya memang hanya KEV); "verified by
  GPT-4o" jadi "verified by LLM"; catatan bahwa panel CVE di Exec tidak ikut periode; pesan panel kosong tidak lagi "feature
  pending".

### Diperbaiki
- Exec "Active Sectors" tidak lagi mentok di 8 (dulu `len(top_sectors)`, sedangkan pembandingnya tanpa batas, jadi trennya timpang).
- Kartu KPI dengan nilai teks panjang (nama sektor) tidak lagi kepotong.

### Diketahui / belum dikerjakan
- Belum dilihat di dev atau prod; dicek di stack lokal dengan data sintetik berbentuk prod.
- Drill-down dari chart ke Newsroom dan panel "confirmed incident terbaru" belum ada (Newsroom belum membaca parameter URL).
- Nama aktor belum dinormalisasi ("Cobalt strike" itu tool, bukan aktor). "Critical" punya dua definisi: band dashboard utama
  memakai CVSS >= 9, Exec memakai `cve_severity`.
- Yang tercatat di 0.6.1 tetap berlaku (penyebab HTTP 400 OTX belum diketahui, ambang verdict OTX agresif).

## [0.6.1] - 2026-10-16

Perbaikan hasil pemeriksaan prod untuk 0.6.0: **enrichment OTX macet di 45 dari 60 run** dalam 16 jam karena IOC yang ditolak
provider dengan HTTP 400. **Tanpa migrasi, tanpa kunci `.env` baru, tanpa dependensi baru, dan tanpa entri beat baru.**

**Saat upgrade dari 0.6.0:**
1. Deploy biasa (bangun ulang image api dan worker). Tidak ada migrasi.
2. Sesudah deploy, IOC yang ditolak provider tampil sebagai kartu `unknown` dengan `raw.skipped` berawalan "rejected by provider".
   Untuk melihat nilai mana yang ditolak (penyebab 400-nya belum diketahui):

   ```sql
   select i.id, i.type, left(i.value, 80) as value, p ->> 'key' as provider, p -> 'raw' ->> 'skipped' as reason
   from iocs i, jsonb_array_elements(i.enrichment -> 'providers') p
   where p -> 'raw' ->> 'skipped' like 'rejected by provider%';
   ```
3. Backlog OTX (3.076 IOC tanpa kartu per 2026-10-16) kini terkejar normal, 25 per run dan empat run per jam.

### Diperbaiki
- **Enrichment IOC berhenti oleh IOC yang ditolak provider** (#4): IOC yang gagal tidak mendapat kartu, jadi dipilih ulang di kepala
  antrean tiap run, dan tiga yang begitu menghentikan seluruh provider untuk run itu (log:
  `ioc_enrich_failed provider=otx status=400`). Error 4xx selain 401/403/429 kini disimpan sebagai kartu `unknown` ("rejected by
  provider (HTTP 400)") dan baru dicek ulang sesudah TTL provider (AbuseIPDB 3 hari, OTX 7, VirusTotal 30), serta tidak dihitung
  sebagai kegagalan beruntun. Lima penolakan beruntun tanpa satu keberhasilan menghentikan provider itu di run tersebut: kalau
  semua permintaan ditolak, yang salah bentuk permintaan kita, dan kartu `unknown` berumur TTL tidak boleh ditulis untuk seluruh
  IOC. 5xx, jaringan putus, dan respons aneh tetap tanpa kartu dan dicoba lagi di run berikutnya.

### Diubah
- Log `ioc_enrich_failed` memuat `ioc_id` dan `ioc_type` (cukup untuk menemukan IOC-nya di DB); nilai IOC dan pesan exception tetap
  tidak dicatat. Ringkasan run `ioc.enrich_pending` mendapat kunci `rejected`, dan `stopped` bisa bernilai `consecutive_rejections`.
- Dokumentasi: `docs/ROADMAP.md` mendapat kolom Status per item (Done, Live, Mostly done, Open, Parked, Dropped, Superseded) dan fakta prod
  per 2026-10-16; `docs/ARCHITECTURE.md` 3.7 memuat penanganan penolakan.

### Diketahui / belum dikerjakan
- **Penyebab HTTP 400 dari OTX belum diketahui**: nilai yang gagal tidak dicatat sebelum ini. Tiga IOC dari kepala antrean yang
  dicoba langsung ke endpoint publik OTX (satu IPv4, dua domain) dijawab normal, jadi kemungkinan bukan mereka.
- **Ambang verdict OTX** (tiga pulse atau lebih = malicious) tampak agresif: 151 dari 453 kartu OTX di prod (33%) berstatus
  `malicious`. Nilai awal, konstanta di `ioc_providers.py`; belum diubah.
- Yang tercatat di 0.6.0 tetap berlaku (verdict belum memengaruhi `confidence_score`, urlscan/GreyNoise/Shodan belum ada, panel dashboard
  belum dilihat di browser, cutover #19 belum dijalankan).

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
