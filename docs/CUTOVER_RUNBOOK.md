# Runbook Cutover & Operasi (Fase 10.G)

Dokumen ini gabungan dua hal: **urutan cutover** dari sistem lama (Rundeck + Mongo + web lama)
ke platform baru, dan **panduan operasi** sesudahnya (backup, rollback, health, hypercare).
> Cutover pengisian CVE Tracker dari `new_cve` ke katalog + mirror CVE (ROADMAP #19) punya runbook sendiri:
> `docs/CVE_CATALOG_CUTOVER.md`.

Semua angka waktu di sini **terukur di latihan staging** kecuali yang ditandai *belum dilatih*.
Bagian "Yang BELUM terbukti" di akhir sengaja jujur soal itu.

> Aturan main: jangan pernah menempel/menyalin isi `.env` atau secret ke chat, tiket, atau log.
> Cek keberadaan dengan `grep -q "^KEY=." .env`, bukan dengan mencetak nilainya.

---

## 0. Peta singkat

```
     nginx (compose; TLS, XFF)                 Rundeck lama (100 job aktif)  ── DIMATIKAN saat cutover
                    │                          cti-web.service, nlp_worker, iocSyncer, mongod
                    ▼                                   (jangan dihapus -- untuk rollback)
        web (Next.js BFF :3000)
                    │  /api/proxy/*
                    ▼
        api (FastAPI :8000)  ── postgres ── redis
                                   ▲           ▲
   beat ──(cron)──► queue ─────────┴───────────┘
        scrape.rss/api/notify/maintenance → worker          (RSS, API, laporan, health digest)
        scrape.browser                    → worker-browser   (Chromium, 25 scraper)
        enrich                            → worker-nlp       (spaCy + LLM)
```

| Yang | Nilai |
|---|---|
| Deploy | 1 VM, `docker compose --profile app` (postgres, redis, migrate, api, worker, worker-browser, worker-nlp, beat, web, **nginx**) |
| TLS / akses luar | service **`nginx`** di compose (bagian 2.4): sertifikat self-signed otomatis atau sertifikat sendiri; **cuma nginx** yang dibuka ke luar (80/443), api/web/postgres/redis hanya `127.0.0.1`. Pakai nginx host sendiri? template: `docker/ops/nginx-cti.conf.example` |
| Secret | `.env` (chmod 600) sekarang; Vault sesudah cutover (`docs/SECRETS_ROTATION.md`) |
| Tag image | `CTI_TAG` di `docker/stack.env` (mis. `v20260927`); simpan tag sebelumnya untuk rollback |
| Zona waktu laporan | `WORKER__REPORT_UTC_OFFSET_HOURS=7` (WIB) |

---

## 1. Prasyarat (semua wajib hijau sebelum T-0)

Checklist gate ada di `docs/PROGRESS.md` ("Checklist cutover"). Ringkasan yang harus dipegang
orang yang menjalankan cutover. **Empat item yang butuh tangan manual di host produksi (backup
Mongo+drill restore, snapshot Rundeck, latihan rollback ke stack lama, timer backup Postgres +
off-host) punya panduan langkah-per-langkah di `docs/PROD_PREP.md`** -- kerjakan itu duluan.

- [x] **13 secret LEGACY dirotasi** (10.F, lihat `docs/SECRETS_ROTATION.md`) -- **didelegasikan ke tim ops
      user 2026-09-30**, dieksekusi tim tersebut. Ini soal token/kredensial app LAMA yang bocor
      (ScraperNews/ScraperNewsWeb/techstackLibrary + `legacy/config.yml`), BUKAN secret platform baru.
- [ ] **`tools/ops/check_secrets.py` hijau dengan `.env` PROD** (read-only: LLM `/models`, Telegram
      `getMe`/`getChat`, NVD, GitHub, twitterapi.io, X bearer bila diisi) -- ini beda dari item di atas:
      mengecek secret BARU (dari `.env.prod.template` yang sudah diisi) bekerja, bukan mengecek yang lama
      sudah dicabut. Di host tanpa `uv`: `docker run --rm --env-file .env -v "$PWD/tools:/tools:ro"
      cti-worker:$CTI_TAG python /tools/ops/check_secrets.py`.
- [ ] `.env` prod lengkap. Yang paling sering terlupa:
  - `TELEGRAM__THREAD_IDS` memuat **semua 22 topik**: `global apac apac_indo apt ot zero_day
    data_breach data_breach_indo vendor_report tech_stack tech_stack_unrelated best_practice darkweb
    pir scraper_health notd debug library_advisory logbook top_ta github_poc feed_twitter`. Topik yang dipakai kode
    tapi tak ada di sini = `UnknownAlertTopic` (kegagalan keras, bukan diam-diam salah channel).
    **`github_poc` dan `feed_twitter` baru (2026-10-02)**: env yang dibuat sebelum itu belum punya --
    tambahkan, kalau tidak alert PoC GitHub / tweet umum gagal tiap run (data PoC-nya tetap tersimpan).
    `feed_twitter` = thread khusus tweet "umum" (dulu `global`/`apac`/`apac_indo`/`apt`); tweet kategori
    khusus tetap ke `zero_day`/`data_breach*`/`vendor_report`/`ot`/`tech_stack*`. Kunci dedup notice tweet
    berubah (`<id>:global` -> `<id>:feed_twitter`): tweet yang masih di jendela pencarian saat deploy
    pertama bisa terkirim ulang SEKALI ke `feed_twitter`. `thread_id` 0 = tanpa thread (masuk chat
    utama): kalau SEMUA 0, semua topik menumpuk di satu tempat. `check_secrets.py` memberi NOTE
    (`telegram_threads`). Cara dapat `thread_id`: klik kanan topik > Copy Link, angka terakhir pada
    `https://t.me/c/<chat>/<thread_id>`; chat harus grup forum (Topics aktif).
  - `TWITTER__API_KEY` (twitterapi.io = sumber Twitter UTAMA). `X__BEARER_TOKEN` hanya kalau
    cadangan X resmi mau disiapkan -- **satu underscore** antara `BEARER` dan `TOKEN`; nama salah =
    container gagal start (`extra="forbid"`).
  - `WORKER__REPORT_UTC_OFFSET_HOURS` (asumsi 7 = WIB; set 0 kalau server Rundeck lama ternyata UTC).
  - Variabel level compose (`BIND_ADDR`, `*_PORT`, `POSTGRES_*`, `CTI_TAG`, `TRUSTED_PROXY_HOPS`,
    `*_CONCURRENCY`, `NGINX_*`) di `docker/stack.env`, **bukan** di `.env`.
- [ ] **nginx (bagian 2.4)**: `NGINX_TLS_HOSTS` di `docker/stack.env` berisi nama/IP yang benar-benar dipakai
      orang untuk membuka platform; port 80/443 di host **bebas** (`ss -ltnp | grep -E ':(80|443)\b'`,
      kosong). Header `X-Forwarded-For` sudah benar di config image. Kalau memakai nginx host sendiri,
      dialah yang wajib memasangnya (`docker/ops/nginx-cti.conf.example`) -- tanpa itu rate limit login
      mengunci semua orang sekaligus.
- [~] **Census feed** -- diulang dari staging 2026-09-30 setelah `warp-cli`/`warp-svc` (Cloudflare WARP)
      dimatikan (IP publik staging balik ke ISP asli, Moratelindo -- bukan range Cloudflare lagi). Hasil:
      **24 dari 94 gagal** (turun dari 30/92), dan perbandingannya informatif -- lihat `docs/PROGRESS.md`
      untuk rincian. **5 kegagalan sebelumnya HILANG** setelah WARP dimatikan (kuat diduga itu efek
      IP Cloudflare, bukan situs beneran berubah): `monitor_x`/`new_cve` (rate-limit, juga dibantu
      perbaikan pacing 10.G2) + `ecrime` (timeout) + `cybersecnews`/`exploitdb`/`threatmon` (dulu
      "XML tak valid" -- kemungkinan halaman blokir/CAPTCHA yang keliru diparsing sebagai feed).
      **18 XPath tak cocok PERSIS SAMA** sebelum/sesudah -- ini genuinely selector situs berubah,
      bukan IP, dan butuh perbaikan kode per scraper. **Diperbaiki 2026-09-30 s/d 2026-10-01** (rincian
      `docs/PROGRESS.md` 10.I, tabel akar masalah `docs/KNOWN_BROKEN.md`): 9 scraper pindah ke
      `RSSScraper`, 8 pakai `link_card_xpaths`, filter kategori `sentinel`/`crowdstrike` diperbarui,
      `github_poc_monitor`/`new_cve` sekarang menunggu jendela rate-limit, `monitor_x` gagal keras saat
      kredit habis. **5 WAIVER tertulis** (`enabled=False`): `blackberry`, `koisec`, `google`, `cisa`
      (WAF Akamai 403, tidak dilewati), `nquiring_minds`. Sisa: `intel471` belum stabil (Vercel 429), 5
      scraper flaky sesekali (retry beat). Scraper yang di-waive tampil `disabled` di health sweep.
      **Belum diulang dari IP PRODUKSI SUNGGUHAN** -- staging sekarang cukup dipercaya (WARP mati),
      tapi produksi tetap boleh dites ulang kalau egress-nya beda lagi. **Health sweep sesudah semalam penuh
      (2026-10-02):** ok 85 / disabled 5 / zero_yield 2 (sah) / degraded 4 (semua Twitter, kredit habis).
- [ ] **Backup Mongo < 24 jam** + sudah dites restore (user; dump lama = satu-satunya arsip historis).
- [ ] **Snapshot stack lama** (lihat 2.3) sudah diambil -- tanpa itu rollback ke stack lama tidak bisa
      dijamin <5 menit.
- [ ] Rehearsal di staging bersih dari ujung ke ujung (seed, warm start, prime, beat) dengan sampel besar.
- [ ] Backup Postgres terjadwal (bagian 6) dan **satu kali `verify` sukses**.
- [ ] Orang kedua tahu di mana runbook ini dan siapa yang memutuskan rollback.

---

## 2. Persiapan H-1

### 2.1 Build dan beri tag

```bash
export CTI_TAG=v20260927                 # tag rilis; catat tag rilis SEBELUMNYA untuk rollback
docker compose --env-file docker/stack.env --profile app build
docker images | grep -E "cti-(api|worker|worker-nlp|web):$CTI_TAG"
docker images | grep cti-nginx          # edge: tag TETAP (cti-nginx:1), TIDAK ikut CTI_TAG
```

Bangun sekali per rilis. Pada box shared, build berulang menumpuk cache -- kalau disk mepet:
`docker builder prune -f --filter until=6h` (lihat bagian 9, "Disk penuh").

### 2.2 Verifikasi secret dan konfigurasi

```bash
docker run --rm --env-file .env -v "$PWD/tools:/tools:ro" cti-worker:$CTI_TAG python /tools/ops/check_secrets.py
docker compose --env-file docker/stack.env --profile app config -q   # sintaks compose
```

### 2.3 Snapshot stack lama (untuk rollback)

Ambil **tepat sebelum** cutover, bukan H-7 (rekaman Fase 0 di `docs/legacy/` bisa sudah basi):

```bash
export RD_URL=http://10.8.20.78:4440 RD_PROJECT=Threat-Information RD_TOKEN=...   # token TIDAK di history:
python3 tools/ops/rundeck_schedule.py snapshot --out rundeck-before-cutover.json  # `read -s RD_TOKEN`
# di server lama:
systemctl is-active mongod cti-web nlp_worker iocSyncer | paste - - - -   # catat mana yang aktif
```

Simpan `rundeck-before-cutover.json` **di luar** host lama dan di luar repo (isinya nama job, bukan secret,
tetap jangan di-commit).

### 2.4 nginx dan sertifikat TLS

Service `nginx` ikut `docker compose --profile app up -d`. Yang perlu diisi hanya `docker/stack.env`:

```bash
NGINX_TLS_HOSTS=cti.perusahaan.internal,10.20.30.40   # SEMUA nama/IPv4 yang dipakai orang, pisah koma
NGINX_BIND_ADDR=0.0.0.0                               # default; satu-satunya service yang dibuka keluar
NGINX_HTTP_PORT=80
NGINX_HTTPS_PORT=443
```

- **Sertifikat self-signed dibuat sendiri** saat container pertama start (SAN = `localhost`, `127.0.0.1` +
  `NGINX_TLS_HOSTS`, RSA 2048, berlaku 365 hari), disimpan di `docker/nginx/tls/` (di-gitignore + di-dockerignore:
  ada kunci privatnya). Fingerprint-nya dicetak ke log: `docker compose ... logs nginx | grep 05-selfsigned`.
- **Dibuat ulang otomatis** kalau `NGINX_TLS_HOSTS` berubah, kunci tidak cocok, atau sisa masa berlaku <= 30 hari
  (dicek saat start dan tiap 24 jam, lalu `nginx -s reload`). Selain itu **fingerprint tetap** antar restart.
- **Browser akan memperingatkan** ("tidak aman"/`ERR_CERT_AUTHORITY_INVALID`) -- itu wajar untuk self-signed. Agar
  bersih, percayakan sertifikatnya sekali per perangkat:
  `docker compose ... cp nginx:/etc/nginx/tls/cti.crt ./cti.crt`, lalu impor ke OS/browser (macOS: Keychain Access ->
  Always Trust; Windows: Trusted Root Certification Authorities). Kalau muncul "**nama tidak cocok**"
  (`ERR_CERT_COMMON_NAME_INVALID`), alamat yang dibuka tidak ada di `NGINX_TLS_HOSTS`: tambahkan, `up -d nginx`.
- **Sertifikat sendiri (CA internal)**: taruh `cti.crt` + `cti.key` di `docker/nginx/tls/` (atau `NGINX_TLS_DIR`)
  sebelum `up`. Generator **tidak pernah menyentuhnya**, apa pun setelan lainnya. Ganti file, lalu
  `docker compose ... restart nginx`.
- Sengaja **tanpa HSTS**: dengan self-signed, HSTS bikin browser menolak tombol "lanjutkan" sama sekali saat
  sertifikat berganti. Tambahkan setelah pakai sertifikat CA.
- Edge tidak ikut `CTI_TAG`: rollback aplikasi (bagian 7.1) tidak menyentuhnya, dan `web` yang di-recreate
  ditemukan nginx dalam <= 10 detik tanpa restart.
- Healthcheck memakai HTTP polos di listener loopback `127.0.0.1:8081` (tak terjangkau dari luar container), bukan
  https: `wget` busybox lewat TLS meninggalkan proses yatim yang membuat nginx menulis 2 baris `notice` tiap 15 dtk
  (~11.500 baris/hari). Log nginx sekarang hanya berisi access log permintaan nyata.
- IPv6 belum didukung generator sertifikat (pakai sertifikat sendiri).

---

## 3. Cutover (T-0)

Urutan ini dari catatan 10.C/10.E. **Titik tanpa-balik-mudah** ditandai ⚠️: sebelum itu, rollback = nyalakan
lagi Rundeck; sesudahnya platform baru sudah menulis data yang tidak ikut kembali ke Mongo.

| # | Langkah | Perintah / catatan | Estimasi |
|---|---|---|---|
| 1 | Umumkan jendela cutover | Telegram + tim | -- |
| 2 | **Matikan jadwal Rundeck** | `python3 tools/ops/rundeck_schedule.py disable --snapshot rundeck-before-cutover.json` lalu `... status` harus `0/N`. Job yang sedang berjalan biarkan selesai. | <1 mnt |
| 3 | **Stop** (bukan disable/mask) unit lama | `sudo systemctl stop cti-web nlp_worker iocSyncer` (yang aktif di snapshot). `mongod` **tetap nyala** (dump + rollback butuh). | <1 mnt |
| 4 | Dump Mongo terakhir (10.4) | `mongodump` ke direktori di luar host; catat nama/waktunya. Ini sekaligus sumber warm start. | ~menit |
| 5 | Nyalakan fondasi | `docker compose ... up -d postgres redis` lalu `up -d migrate api web` (tanpa worker/beat!). `curl -f localhost:$API_PORT/healthz` | ~1 mnt |
| 6 | Seed data referensi | `tools/seed/fase10_reference_data.py --dry-run` lalu tanpa `--dry-run` (idempoten; cara menjalankan: 3.2). Script mencetak **daftar user lama**: buat ulang lewat UI dengan password baru (hash lama sengaja tidak dibawa). Sejak QA 2026-10-01 ikut mengisi `threat_actor_groups` (~4000), `monitored_people`, `ioc_allowlist_entries` -- tanpa `threat_actor_groups` TIDAK ADA artikel yang dapat threat actor (dropdown TA kosong, PIR berbasis TA 0 match). Cek: baris `threat_actor_groups` di output > 0. | ~menit |
| 7 | Warm start dedup | `tools/seed/fase10_warm_start.py --dry-run` lalu sungguhan (cara menjalankan: 3.2), dengan `--dump-dir <dump langkah 4>` dan `--legacy-dir <salinan segar /opt/ScraperNews/offset + /opt/techstackLibrary/offset>`. Tanpa ini tiap scraper mulai dingin (hanya cap 5 item, alert tetap terkirim). | ~menit |
| 8 | Migrasi CVE tracker (Fase 10.F, opsional tapi disarankan) | `tools/seed/fase10_cve_migrate.py --dry-run` lalu sungguhan (cara menjalankan: 3.2), dengan `--dump-dir <dump langkah 4>`. Isi `cve_tracker`/`cve_false_positives`/`cve_tickets` dari riwayat Mongo lama, supaya tab CVE TIDAK kosong di hari pertama (`new_cve` sendiri cuma menjangkau 8 hari ke belakang). Idempoten, aman diulang; CVE yang sudah ada (mis. `new_cve` sudah sempat jalan) tidak ditimpa. | ~menit |
| 9 | **Prime** watcher yang riwayatnya tak bisa dibawa | `docker compose ... exec -T worker cti-scraper run <id> --prime` untuk `github_ttps sophoslabs_github mitre_github` dan `techstack_npm techstack_pypi techstack_go` (yang tidak punya file offset). Prime = fetch sungguhan, tandai SEMUA seen, **tanpa** kirim apa pun. | ~menit |
| 10 | ⚠️ Nyalakan worker, lalu beat | `up -d worker worker-browser worker-nlp` tunggu healthy, **terakhir** `up -d beat`. Beat itu penembak: begitu nyala scraper mulai jalan. | ~2 mnt |
| 11 | Smoke test | Lihat 3.1 | ~5 mnt |
| 12 | Buka platform baru ke pengguna | pastikan 80/443 host bebas (matikan nginx/proxy lama yang memegangnya), lalu `docker compose ... up -d nginx`; uji login dari **laptop lain** dan cek `audit_log` (3.1) | ~2 mnt |
| 13 | Umumkan selesai; mulai **pantau 4 jam** (bagian 4) | | -- |

### 3.0 Dua langkah yang tidak ada di tabel itu tapi wajib di database KOSONG

Tabel di atas mengasumsikan database sudah pernah dipakai (staging). Di host yang benar-benar baru:

- **Admin pertama**: `POST /api/auth/init` membuat superadmin pertama dan hanya jalan selama belum ada user
  (409 sesudahnya; tanpa autentikasi, jadi panggil SEBELUM nginx dibuka ke jaringan). Tanpa ini tidak ada yang bisa
  login untuk "membuat ulang user lewat UI" (langkah 6).
- **Sinkron katalog ATT&CK** (tombol Sync di Intelligence > ATT&CK DB, atau
  `AsyncAttackSyncRepo.sync_all_domains()` dari dalam container `api`). Task periodik `attack_sync_check`
  akan mengisinya sendiri (status domain "never"), tapi lakukan SEBELUM beat supaya artikel pertama sudah
  mendapat TTP yang dinormalisasi.

Untuk deploy dari NOL tanpa stack lama, jangan susun tabel ini manual: `make fresh-deploy`
(`tools/ops/fresh_deploy.sh`, langkah-langkahnya di `README.md`) mengerjakan keduanya otomatis, ditambah seed
data referensi bawaan (`tools/seed/reference/`) sebagai pengganti dump Mongo untuk tiga tabel referensi.

### 3.1 Smoke test (langkah 10)

```bash
curl -fs localhost:$API_PORT/healthz                                  # {"status":"ok"}
docker compose ... ps                                                # semua healthy
docker compose ... logs beat | grep -E "beat_leader|beat_standby"      # tepat SATU beat_leader
docker compose ... exec -T worker cti-scraper dry-run bleepcomp         # satu scraper, tanpa tulis DB
docker compose ... exec -T worker celery -A cti_worker.celery_app call scraper.health_digest   # digest sekali
python3 tools/ops/notify_telegram.py --env-file .env --topic debug --text "cutover: tes notifikasi"
curl -ks https://localhost/nginx-health                                # edge hidup ("ok"); port sesuai NGINX_HTTPS_PORT
docker compose ... exec -T worker cti-scraper run new_cve               # isi awal tab CVE (lihat catatan di bawah)
```

Lalu di UI (/scrapers): tarik **Trigger** satu scraper dan lihat run masuk dengan status `ok`/`empty`.

**Tab CVE tidak lagi kosong di awal** kalau langkah 8 (migrasi CVE tracker) dijalankan -- riwayat dari Mongo
lama (`cve_tracker`/`cve_false_positives`/`cve_tickets`) sudah masuk. Kalau langkah 8 DILEWATI: tab kosong sampai
tick per-jam pertama `new_cve`, dan riwayatnya cuma 8 hari ke belakang (jendela pencarian NVD/Tenable per techstack)
-- techstack yang ditambah SETELAH cutover tetap kena keterbatasan ini, itu `docs/ROADMAP.md` item 3. Kalau
`new_cve` berstatus `rate_limited` (batas 60/menit domain MITRE), jalankan lagi; item yang sudah tersimpan
tidak hilang.

**IP klien harus asli** (kalau tidak, rate limit login mengunci semua orang): login SEKALI dari laptop lain lewat
`https://<host>`, lalu

```bash
docker compose ... exec -T postgres psql -U cti -d cti -c \
  "select username, action, ip_address, at from audit_log order by id desc limit 3"
```

`ip_address` harus **IP laptop itu**, bukan `172.x.0.1` (gateway Docker; lihat baris troubleshooting).

### 3.2 Menjalankan script seed dari host tanpa `uv`

Script seed butuh `pymongo` (tidak ada di image runtime). Lewat container worker, pymongo dipasang sementara
(pola yang dipakai di rehearsal staging, `seed_run.sh`):

```bash
docker run --rm --network <project>_default --env-file .env \
  -v "$PWD/tools:/tools:ro" -v /path/ke/dump-mongo:/dump:ro -v /path/ke/offset-lama:/legacy-offsets:ro \
  --entrypoint sh cti-worker:$CTI_TAG -c '
    pip install --target /tmp/pm -q pymongo &&
    PYTHONPATH=/tmp/pm python /tools/seed/fase10_reference_data.py --dump-dir /dump --dry-run'
# lalu tanpa --dry-run; warm start: fase10_warm_start.py --dump-dir /dump --legacy-dir /legacy-offsets
# migrasi CVE tracker: fase10_cve_migrate.py --dump-dir /dump (gak butuh --legacy-dir)
```

### 3.2a Backfill enrichment artikel yang sudah masuk (sekali, setelah seed)

Untuk DB yang sudah menerima artikel SEBELUM `threat_actor_groups` di-seed / sebelum fix role negara
`mentioned` (staging 2026-10): threat actor dicocokkan ulang ke **judul** artikel lama (ringkasan tidak
tersimpan, jadi artikel lama hanya dapat TA yang disebut di judul) dan negara `victim`/`actor` diberi baris
`mentioned` (Risk Matrix, filter negara). Tanpa LLM, tanpa alert; hanya menambah baris, idempoten.

```bash
docker compose ... exec -T worker python -m cti_enrich.backfill --dry-run   # angka + contoh, di-rollback
docker compose ... exec -T worker python -m cti_enrich.backfill
```

Menolak jalan (exit 1, tidak menulis apa pun) kalau `threat_actor_groups` masih kosong. Risk Matrix di-cache
15 menit per proses API -- hasil baru muncul setelah itu (atau restart `api`).

### 3.3 Yang tidak boleh dilakukan saat cutover

- Jangan `systemctl disable`/`mask`/hapus unit lama, jangan hapus job Rundeck, jangan hapus Mongo --
  itu semua bahan rollback.
- Jangan nyalakan `beat` sebelum warm start + prime selesai (scraper yang jalan duluan sudah lewat fase
  dingin; baris warm start yang bentrok di-skip, item yang terlanjur di-cap tidak terselamatkan).
- Jangan jalankan dua beat sekaligus di dua host (lock singleton di Redis melindungi, tapi jangan andalkan).

---

## 4. Pantau 4 jam pertama (10.6)

| Cek | Cara | Wajar | Tindakan bila tidak |
|---|---|---|---|
| Queue `enrich` | `docker compose ... exec -T redis redis-cli llen enrich` | naik-turun; **ambang backpressure 2000** | terus naik: LLM lambat/quota habis -> cek `worker-nlp` log, turunkan beban |
| Queue `scrape.*` / `notify` | `llen scrape.rss` dst | ~0 | menumpuk = worker mati/macet |
| Digest health | thread `scraper_health` | awalnya banyak `stale` (belum sempat jalan) -> menyusut | `dead`/`degraded` yang menetap = lihat run terakhir di /scrapers |
| Error log | `docker compose ... logs --since 30m worker worker-nlp \| grep -E "ERROR\|Traceback"` | nol atau sedikit | investigasi per pola |
| Banjir Telegram | thread global/apt/... | scraper dingin maks **5** item/scraper | jauh lebih banyak = warm start bermasalah: **hentikan beat** (`stop beat`), periksa |
| LLM | log `OpenAIQuotaExhausted`, `[enrichment_failed]` di /filtered-articles | tidak ada | quota/gateway; artikel gagal dicatat, bukan hilang |
| Resource | `docker stats --no-stream`, `df -h /` | RAM `worker-nlp` stabil | naikkan/turunkan `NLP_WORKER_CONCURRENCY` |

Perilaku yang **normal tapi mengejutkan**:
- **Digest health dikirim ulang tiap 30 menit selama masih ada masalah** (tidak ada dedupe; "diam = sehat").
  Di jam-jam awal isinya panjang. Ini disengaja sederhana; kalau mengganggu, dedupe/cooldown bisa ditambah.
- Scraper yang **run terakhirnya lama** tampil `dead` sampai slot cron berikutnya menembak, walau
  infrastrukturnya sehat (terlihat di staging tepat setelah beat dinyalakan).
- Scraper Twitter di twitterapi.io free tier kena `429` lalu retry 6 detik (run 30-35 dtk, bukan gagal).
- **Beat yang di-`stop` manual TIDAK nyala sendiri** (`restart: unless-stopped`), dan deploy parsial
  (`up -d worker web`) juga gak nyalain dia. Insiden staging 2026-09-26 15:42 -> 09-30 17:17 UTC: beat
  di-stop habis rehearsal, jadwal mati ~97 jam tanpa ada yang sadar (digest health ikut mati karena
  dijadwalkan beat). Sekarang: banner merah di `/scrapers` + alert Telegram (thread `scraper_health`)
  dari **watchdog di container worker** kalau heartbeat beat basi > `WORKER__BEAT_HEARTBEAT_STALE_S`
  (300 dtk), diulang tiap `WORKER__BEAT_STALE_ALERT_REPEAT_MIN` (60), plus pesan "PULIH". Kalau beat
  SENGAJA dimatikan (warm start, langkah 5-8), alert itu memang akan datang -- abaikan sampai beat dinyalakan.
- Beat yang nyala lagi sesudah mati lama **tidak** menembak semua jadwal sekaligus: slot yang terlewat
  lebih dari `WORKER__BEAT_CATCHUP_GRACE_S` (600 dtk) dilompati ke slot berikutnya (log
  `beat_stale_catchup_skipped` berisi daftar entrinya). Restart singkat tetap di-catch-up.
- Run hasil retry (fetch_error/rate_limited) tercatat `trigger=beat_retry`/`manual_retry`, jeda 60/120/240 dtk.

---

## 5. Hypercare 1 minggu (10.7)

Harian (5 menit): /scrapers (jumlah `dead`/`degraded`/`zero_yield`), digest health, queue depth, disk, backup semalam
(`ls -la /var/backups/cti`), thread `debug`.

Terjadwal yang bisa dilihat hasilnya (WIB):

| Laporan | Kapan | Topik |
|---|---|---|
| Counter harian | tiap hari 23:55 | `debug` |
| News of the day | tiap hari 23:58 | `notd` |
| Logbook (Excel) | dicek tiap hari 07:00, terkirim tiap 14 hari (panggilan PERTAMA hanya mencatat tanggal) | `logbook` |
| Top CVE mingguan | Minggu 07:01 | `tech_stack` |
| Top CVE tweet | 00/06/12/18 | `tech_stack` / `tech_stack_unrelated` + `vendor_report` |
| Tren threat actor | **Senin 13:00** | `top_ta` |

Laporan yang terlewat bisa diulang manual, mis.
`celery -A cti_worker.celery_app call report.daily_counters --args='["2026-09-25"]'`.

---

## 6. Backup & restore Postgres

Alat: `tools/ops/pg_backup.py` (stdlib; perintah Postgres dijalankan di container lewat `docker compose exec`).

```bash
PG="docker compose --env-file docker/stack.env --profile app exec -T postgres"
python3 tools/ops/pg_backup.py --pg-exec "$PG" backup  --dir /var/backups/cti     # dump -Fc + sha256, chmod 600, prune
python3 tools/ops/pg_backup.py --pg-exec "$PG" verify  --file /var/backups/cti/cti-<UTC>.dump
python3 tools/ops/pg_backup.py --pg-exec "$PG" restore --file <dump> --to-db cti_restore_test
python3 tools/ops/pg_backup.py --pg-exec "$PG" prune   --dir /var/backups/cti --keep-days 14 --keep-min 3
```

- **Jadwal**: `docker/ops/cti-pg-backup.{service,timer}` (harian 02:30, `Persistent=true`), gagal -> alarm
  Telegram topik `debug` (`tools/ops/notify_telegram.py`).
- **Retensi**: 14 hari, dan 3 backup terbaru **selalu** dipertahankan (backup yang berhenti jalan tidak
  menghabiskan stok). Umur dihitung dari NAMA berkas, bukan mtime.
- **Off-host**: salin ke luar mesin (rsync/rclone) -- belum diotomasi; backup di disk yang sama bukan backup.
- **Pindah host dengan DB dari backup**: `make fresh-deploy ARGS='--restore-from <dump>'` (README.md, bagian
  "Deploy memakai DB dari backup"). `pg_backup.py` jalan di python3 HOST >= 3.9.
- **Verifikasi mingguan**: `verify` me-restore dump ke DB scratch, membandingkan `alembic_version` dan jumlah
  baris tabel kunci dengan DB live, lalu DROP scratch. Dump yang tak pernah dites restore belum backup.
- **Pengaman `restore`**: menolak DB live kecuali `--force-live`; menolak DB yang sudah berisi kecuali
  `--replace`; memeriksa checksum + `pg_restore --list` SEBELUM menyentuh DB apa pun.

Hasil latihan staging (DB kecil, 1,1 MB; DB produksi akan lebih lama, skalakan sesuai ukuran):

| Operasi | Waktu |
|---|---|
| `backup` (dump + validasi TOC + checksum) | 0,45 dtk |
| `verify` (restore ke scratch + banding + drop) | 3,4 dtk |
| `restore` ke DB bernama | 1,2 dtk |
| Penolakan restore ke DB live / DB berisi / kegagalan -> alarm | terbukti, exit 1 |

**Restore penuh ke DB live** (skenario terburuk: data rusak) -- *belum dilatih di staging* (butuh izin
karena destruktif). Prosedur: hentikan penulis (`stop api worker worker-browser worker-nlp beat web`),
`restore --file <dump> --to-db cti --force-live --replace`, nyalakan lagi (`up -d`), cek jumlah baris.
Latih di staging sebelum go-live dan tulis waktunya di sini.

---

## 7. Rollback

Tiga tingkat, dari yang paling ringan. **Tentukan tingkatnya dulu**, jangan langsung loncat ke yang terberat.

### 7.1 Rollback versi platform (kode salah, data baik) -- 19-23 detik

```bash
python3 tools/ops/rollback.py --current-tag v20260927 --tag v20260920 \
    --compose "docker compose --env-file docker/stack.env --profile app" \
    --env-file .env --network <project>_default --api-url http://127.0.0.1:8000/healthz
# tambahkan --yes bila pre-flight bilang perlu downgrade DB; --dry-run untuk melihat rencananya dulu
```

Yang dilakukan (dan kenapa tidak boleh dilakukan manual seenaknya):

> ⚠️ **`CTI_TAG=<lama> docker compose up -d` saja itu BERBAHAYA.** Service `migrate` menjalankan
> `alembic upgrade head` di setiap `up`. Kalau DB sudah di revisi yang lebih baru dari yang dikenal image
> lama -> `Can't locate revision` -> `migrate` gagal -> compose sudah terlanjur **menghentikan** api/worker
> yang jalan (mereka bergantung pada `migrate`) -> **outage**. Terbukti di latihan staging (API mati).

Alat ini: (1) membaca revisi DB dan head image target, (2) menggabungkan riwayat migrasi KEDUA image
(image lama tidak kenal revisi baru), (3) kalau DB lebih baru dari target -> `alembic downgrade` dengan image
**sekarang** (hanya dia yang kenal revisi barunya), butuh `--yes` karena downgrade bisa menghapus
kolom/tabel, (4) `up -d` dengan `CTI_TAG=<target>`, tunggu API + semua healthy, verifikasi revisi akhir.
Menolak (tanpa mengubah apa pun) bila riwayat bercabang, revisi tidak dikenal, atau `--yes` tidak ada.
**Ambil backup dulu** (`pg_backup.py backup`) bila akan downgrade.

Waktu terukur di staging (image sudah lokal): rollback 19,2-23,1 dtk (termasuk downgrade), roll-forward
22,3 dtk, satu siklus mundur+maju 41,9 dtk. Menarik image dari registry menambah waktu.

### 7.2 Restore data dari backup (data rusak)

Bagian 6, "Restore penuh ke DB live". Kehilangan data = sejak backup terakhir (harian) -- putuskan bersama.

### 7.3 Kembali ke STACK LAMA (platform baru dibatalkan) -- target <5 menit, *belum dilatih di produksi*

Prasyarat: langkah 2.3 (snapshot) dan tidak ada yang dihapus di 3.3.

```bash
# 1. hentikan penulis platform baru (supaya tidak dobel-alert dengan sistem lama)
docker compose ... stop beat worker worker-browser worker-nlp nginx    # nginx: membebaskan 80/443 untuk proxy lama
# 2. nyalakan stack lama (yang aktif di snapshot)
sudo systemctl start mongod cti-web            # + nlp_worker iocSyncer bila aktif di snapshot
# 3. nyalakan lagi jadwal Rundeck persis yang dulu menyala
python3 tools/ops/rundeck_schedule.py enable --snapshot rundeck-before-cutover.json
python3 tools/ops/rundeck_schedule.py status --snapshot rundeck-before-cutover.json   # harus N/N
# 4. nyalakan lagi proxy/nginx LAMA yang tadi memegang 80/443 (systemctl start nginx; nginx -t dulu)
```

Yang harus diterima (putuskan sebelum cutover): data yang ditulis platform baru **tidak kembali ke Mongo**;
offset scraper lama tertinggal selama jendela cutover sehingga beberapa alert bisa terkirim ulang. Karena itu
jendela cutover dibuat pendek dan waktu mulai/selesainya dicatat. **Latih ini di produksi minimal sekali**
(nyalakan-matikan dengan pengukur waktu) sebelum go-live; tulis waktunya: `____ menit` (target <5).

---

## 8. Sumber data Twitter: utama dan cadangan

Kebijakan (keputusan user 2026-09-27): **twitterapi.io = utama dan dipaksa duluan; API resmi X = cadangan**,
dipakai hanya kalau twitterapi.io memang tidak bisa. Pindah **manual**, per-scraper.

- **Kapan pindah** (usulan, belum dikonfirmasi user): kunci ditolak / kredit habis / layanan mati -- tampak
  sebagai `fetch_error`/`parse_error` berulang di `tweet_alerts_1h`, `tweet_alerts_30m`, `trending_cve`, atau
  health `degraded`/`dead`. **Bukan** alasan pindah: 429 free tier (ada retry+backoff, hanya lambat),
  selisih beberapa tweet antar provider.
- **Cara**: /scrapers -> pilih scraper -> "Sumber data Twitter/X" -> `X API resmi (cadangan)` -> Save Config.
  Berlaku di run berikutnya. Kembali: pilih `twitterapi.io (utama)` atau **Reset to Defaults**.
- **Biaya X resmi** (pay-per-use): ~$0,005 per tweet yang dibaca; tweet yang sama di hari UTC yang sama tidak
  ditagih dua kali. **`trending_cve` sebaiknya TETAP di twitterapi.io**: ia mencari semua tweet "CVE-<tahun>-"
  di seluruh X (ribuan/hari). Pasang **batas belanja** di X Developer Console sebelum memakainya.
- Ganti sumber tidak menyebabkan alert dobel (kunci dedup = id tweet, sama di kedua API; terbukti di staging).
- Uji sebelum pindah: `cti-scraper dry-run tweet_alerts_1h --option provider=x_official` (tanpa mengubah konfigurasi).

---

## 9. Troubleshooting (semua ini pernah terjadi di rehearsal)

| Gejala | Penyebab | Tindakan |
|---|---|---|
| Semua orang terkunci login setelah satu orang salah password | proxy tidak mengirim `X-Forwarded-For` (nginx compose sudah benar; ini terjadi pada nginx host sendiri) atau `TRUSTED_PROXY_HOPS` tidak sama dengan jumlah proxy | pasang header (bagian 1); cek `TRUSTED_PROXY_HOPS` |
| Browser: "koneksi tidak aman" / `ERR_CERT_AUTHORITY_INVALID` | sertifikat self-signed (wajar) | percayakan `cti.crt` (2.4) atau pasang sertifikat CA |
| Browser: "nama tidak cocok" / `ERR_CERT_COMMON_NAME_INVALID` | alamat yang dibuka tidak ada di `NGINX_TLS_HOSTS` | tambahkan nama/IP itu, `docker compose ... up -d nginx` (sertifikat dibuat ulang; percayakan lagi yang baru) |
| nginx tidak mau start: `address already in use` | 80/443 dipakai proses lain (nginx/Apache host, stack lama) | `ss -ltnp \| grep -E ':(80\|443)\b'`; hentikan, atau ganti `NGINX_HTTP_PORT`/`NGINX_HTTPS_PORT` |
| nginx: 502 Bad Gateway | `web` mati/belum sehat | `docker compose ... ps web` + `logs web`; nginx menemukan `web` yang baru dalam <= 10 dtk, tak perlu restart nginx |
| `audit_log.ip_address` sama untuk semua klien (mis. `172.x.0.1`) | (a) diuji dari **host yang sama** (localhost lewat docker-proxy selalu tampil sebagai gateway Docker -- terlihat di staging); (b) Docker Desktop/rootless meng-NAT semua koneksi; (c) load balancer/firewall di depan host melakukan SNAT | uji dari **laptop lain**. Kalau ada LB di depan nginx: LB harus mengirim `X-Forwarded-For` dan `TRUSTED_PROXY_HOPS` dinaikkan jadi 2 (`docker/stack.env`). Selama IP-nya sama untuk semua, rate limit login global -- jangan go-live sebelum ini beres |
| Container gagal start, log menyebut field tak dikenal | env var salah ketik (`extra="forbid"`), mis. `X__BEARER__TOKEN`, `TELEGRAM__BOTTOKEN` | perbaiki namanya; `__` = pemisah nesting |
| `.env` rusak setelah `echo "X=1" >> .env` | file tidak berakhir newline -> baris menempel ke nilai sebelumnya (mis. **token**) | `printf "\nKEY=val\n" >> .env`; selalu verifikasi setelahnya |
| `alembic` gagal `SyntaxError: null bytes` saat build dari Mac | tar macOS membawa file `._*` (AppleDouble) | `COPYFILE_DISABLE=1 tar ...`; cek `find . -name "._*"` |
| Rollback `up -d` bikin API mati | `migrate` menolak revisi DB yang lebih baru | pakai `tools/ops/rollback.py` (bagian 7.1) |
| `no space left on device` saat build | build cache Docker menumpuk (pernah 30 GB) | `docker image prune -f && docker builder prune -f --filter until=6h`; jangan sentuh volume |
| Alert Telegram gagal `UnknownAlertTopic` | topik tak ada di `TELEGRAM__THREAD_IDS` | tambahkan (thread 0 = channel utama) |
| Artikel `[enrichment_failed]` menumpuk | LLM gateway 401/kuota/persona non-JSON | cek `python3 tools/ops/check_secrets.py`; `tools/llm/probe_json.py` |
| Scraper `stale` padahal beat nyala | belum sempat menembak sejak beat start / dinonaktifkan | tunggu slot cron; `enabled`? cek /scrapers |
| Scraper `dead` sesudah beat baru nyala | run terakhir lama (dari sebelum) | wajar sampai slot cron berikutnya |
| Setelah worker mati lama, sekali nyala terjadi lonjakan run | tick beat menumpuk | sudah diatasi: tick scrape kedaluwarsa 1 interval (`expires`) |
| Digest health datang terus-menerus | tidak ada dedupe, masalah masih ada | perbaiki masalahnya, atau tambahkan dedupe |
| `monitor_x` (tab X Intel) `fetch_error`/`rate_limited`, terus `degraded` | twitterapi.io **free tier** ~1 request/5-6 dtk untuk seluruh key, dibagi 4 scraper (`monitor_x`+`tweet_alerts_1h`+`tweet_alerts_30m`+`trending_cve`) yang semua mukul domain sama | **2026-09-30**: diperbaiki -- `rate_limit` ke-4 scraper disamakan jadi `10/minute` (sebelumnya `monitor_x` beda sendiri, `15/minute`, melanggar invarian domain-dibagi-rata `cti_scraper.ratelimit`), jeda PROAKTIF `window_s/capacity` (6 dtk) di antara AKUN (bukan cuma reaktif sesudah kena limit), dan `_get_with_backoff` sekarang menunggu jendela reset kalau BUDGET LOKAL kita sendiri (bukan cuma 429 server) yang habis duluan. **Terbukti live di staging 2026-10-01** (kunci twitterapi.io baru): `monitor_x` `ok` 385 dtk / 30 item (sebelumnya `empty` ~108 dtk tanpa pesan error karena kredit habis), `tweet_alerts_30m`/`trending_cve` `ok`; sejak itu 401/402/403 gagal keras (`parse_error` dengan pesan HTTP-nya). **Kredit kunci baru itu habis lagi dalam ~3 jam** (402 mulai 14:53 UTC; 120 run gagal semalam, 4 scraper `degraded`) -- jangan pasang kunci berkredit kecil di produksi; hitung dulu kebutuhan kredit empat scraper yang berbagi saldo itu. **Penyebabnya: default `monitor_x` `*/15` padahal legacy tiap 3 jam -- sudah dibetulkan ke `8 */3 * * *` 2026-10-02** (cadence ke-4 scraper Twitter sekarang dikunci test ke legacy). Kalau masih `rate_limited`/`degraded` di produksi, opsi lama masih berlaku: key twitterapi.io berbayar, atau redesign satu query OR per run (kehilangan `since_id` per akun) |
| `new_cve` status `rate_limited` | batas 60/menit domain MITRE terlewati (banyak kandidat CVE) | wajar sesekali; kalau menetap, kandidat > 60/run: naikkan `rate_limit` scraper via /scrapers atau kurangi cakupan techstack |
| `alembic current` di image lama gagal | DB di revisi yang tak dikenal image itu | jalankan dengan image yang lebih baru / `rollback.py` |

**Blind spot yang disadari** (jangan diasumsikan tertutup):
- Digest health dikirim lewat queue `notify` yang dilayani container **`worker`** -- kalau `worker` sendiri yang
  mati, digest tidak bisa melaporkannya (alarm ikut mati). Pantau container dari luar (monitor uptime yang sudah
  ada di host, atau cron `docker ps` + `notify_telegram.py`).
- Feed yang fetch-nya sukses tapi isinya beku (semua item sudah pernah terlihat) tidak ditandai (`zero_yield`
  hanya bila fetch balik 0 item). Pengganti `offsetAlert` lama tidak mendeteksi ini.
- Backup off-host belum otomatis.

---

## 10. Yang BELUM terbukti (jujur)

| Item | Status |
|---|---|
| Rollback ke **stack lama** <5 menit di produksi | *belum dilatih* -- butuh Rundeck/host lama (user). `rundeck_schedule.py` hanya diuji dengan API palsu, belum ke Rundeck asli |
| Restore penuh ke **DB live** | *belum dilatih* -- destruktif, butuh izin; guard-nya teruji unit + live (penolakan), langkah destruktifnya belum |
| Census feed dari **IP produksi** | belum (egress staging beda) |
| **Deploy dari nol** (`make fresh-deploy`) | terbukti 2026-10-02 di Docker lokal (arm64), clean-room dari salinan repo: build dari nol, seed 3991/30/9, admin dibuat, ATT&CK 943 teknik, login lewat nginx 200 (salah 401), tepat satu `beat_leader`, 0 traceback, dijalankan ulang tidak mengubah apa pun, 4 jalur gagal prasyarat. **Belum**: host Linux amd64 sungguhan, probe `check_secrets` dengan key asli (di latihan: secret dummy + `--skip-secret-check`; jalur gagalnya terbukti), beban nyata, scraper yang menembak dari IP host itu |
| Beban produksi: `NLP_WORKER_CONCURRENCY` > 1 dengan LLM asli, volume asli | belum; bug concurrency baru muncul dengan LLM asli + paralel (pelajaran 10.B) |
| nginx (compose) + sertifikat self-signed di **produksi** | teruji di staging (login, cookie `Secure`, redirect, sertifikat, `web` di-recreate) **termasuk klien eksternal**: login dari laptop lewat port yang di-publish tercatat di `audit_log` dengan IP laptop itu, bukan gateway Docker; + 44 test otomatis (`tests/edge`, 62 mutasi: 0 selamat). **Belum** dipasang di host produksi |
| Backup Postgres: penjadwalan systemd dan salinan off-host | unit file siap, belum dipasang/diuji di host produksi |
| Vault | pasca-cutover (`docs/SECRETS_ROTATION.md`) |
