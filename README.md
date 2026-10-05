# Vareon Intelligence

Platform Cyber Threat Intelligence: mengumpulkan berita dan sinyal ancaman dari ~90 sumber (RSS, situs web,
API, X/Twitter, GitHub), memperkaya dengan NLP + LLM (klasifikasi, threat actor, TTP MITRE ATT&CK, negara),
lalu menyajikannya lewat web UI dan alert Telegram. Pengganti sistem lama `ScraperNews` + `ScraperNewsWeb`.

| Bagian | Isi |
|---|---|
| `apps/api` | FastAPI (REST, auth, kontrol scraper) |
| `apps/web` | Next.js (UI) |
| `apps/worker` | Celery: `worker` (RSS/API), `worker-browser` (Playwright), `worker-nlp` (spaCy), `beat` (jadwal) |
| `packages/*`, `scrapers/` | inti DB/enrich, framework scraper, daftar scraper |
| `docker/`, `docker-compose.yml` | image, nginx (TLS), contoh env tingkat compose |
| `tools/ops`, `tools/seed` | skrip operasi (deploy, backup, rollback) dan seed |
| `docs/` | runbook, catatan fase, daftar scraper yang rusak |

## Deploy dari nol

Untuk host baru tanpa data lama. Skrip deploy-nya idempoten: aman dijalankan ulang dan **tidak pernah**
menghapus volume atau data.

### Prasyarat

- Linux dengan **Docker + plugin `docker compose`**, `python3` (>= 3.9), `curl`, `git`.
- Akses keluar internet: registry image (base image, PyPI saat seed), `raw.githubusercontent.com`/GitHub
  (katalog ATT&CK), situs sumber scraper, endpoint LLM, `api.telegram.org`.
- Disk lapang untuk image (~6 GB; build di staging memakai ~9 GB termasuk cache) dan RAM untuk `worker-nlp`
  (spaCy) + `worker-browser` (Chromium). Latihan 2026-10-02: seluruh stack naik sehat di Docker dengan RAM 4 GB
  pada `*_CONCURRENCY=1` (idle). Concurrency bawaan (4/2/2) dan beban nyata belum diuji di mesin sekecil itu.

### Langkah

```bash
git clone https://github.com/ikblmhndra/Niskala-Intelligence.git cti-platform && cd cti-platform

cp .env.prod.template .env              # 1. isi nilainya (tabel key di bawah); chmod 600 .env
cp docker/stack.env.example docker/stack.env   # 2. ganti POSTGRES_PASSWORD, NGINX_TLS_HOSTS, port

make fresh-deploy                       # 3. build + cek secret + migrasi + seed + admin + worker + beat + web + nginx
```

Aturan isi file:

- `.env` = konfigurasi **aplikasi**; `docker/stack.env` = variabel level **compose** (port, tag, password
  Postgres). Jangan dicampur: aplikasi menolak key asing dan gagal start.
- Password Postgres di `docker/stack.env` **harus sama** dengan yang ada di `DATABASE__URL` dan
  `DATABASE__SYNC_URL`. Ganti semua `GANTI_INI` di `.env`. Skrip memeriksa ini sebelum build.
- Jangan tempel nilai secret ke chat/tiket/log; isi langsung di editor di server.
- `AUTH__JWT_SECRET` dan `AUTH__SESSION_SECRET_KEY` boleh dibiarkan kosong: skrip membangkitkannya acak.

Opsi: `make fresh-deploy ARGS='--skip-build'` (image sudah dibangun), `--skip-secret-check`,
`--skip-nginx` (kalau sudah punya reverse proxy sendiri; template: `docker/ops/nginx-cti.conf.example`).
`make fresh-status` menampilkan status container.

### Key yang dibutuhkan

| Key di `.env` | Status | Catatan |
|---|---|---|
| `LLM__API_KEY`, `LLM__URL`, `LLM__MODEL` | **wajib** | endpoint kompatibel OpenAI; diuji `GET /models` (tanpa generate) |
| `TELEGRAM__BOT_TOKEN`, `TELEGRAM__CHAT_ID`, `TELEGRAM__THREAD_IDS` | **wajib** | diuji `getMe`/`getChat` (tidak mengirim pesan). `THREAD_IDS` = 22 topik (termasuk `github_poc` dan `feed_twitter`, thread khusus tweet umum); `thread_id` 0 = masuk chat utama, jadi isi id masing-masing topik (Copy Link pada topik di Telegram, angka terakhir) kalau mau terpisah. `check_secrets` memberi NOTE kalau masih menumpuk |
| `NVD__API_KEY` | opsional | tanpa key kena batas publik NVD yang jauh lebih kecil |
| `GITHUB__TOKEN` | opsional | scraper GitHub (PoC, TTP) memakainya |
| `TWITTER__API_KEY` | opsional | twitterapi.io, dipakai 4 scraper Twitter yang **berbagi satu saldo kredit** (lihat `docs/CUTOVER_RUNBOOK.md` bagian 8) |
| `X__BEARER_TOKEN` | opsional | X API resmi, hanya cadangan twitterapi.io |
| `OTX__API_KEY` | opsional | |
| `GRAPH__*` | opsional | pengiriman email (newsletter, CVE) lewat Microsoft Graph |
| `OIDC__*` | opsional | SSO |

Skrip menjalankan `tools/ops/check_secrets.py` (probe baca-doang ke tiap provider, tidak mencetak secret)
sebelum menyalakan apa pun. Key opsional yang kosong dilaporkan `SKIP`, bukan gagal.

### Yang dilakukan skrip

1. Cek prasyarat dan isi `.env`/`docker/stack.env`. 2. Build image. 3. Cek secret. 4. Postgres + Redis, migrasi
skema, API. 5. Seed data referensi bawaan (`tools/seed/reference/`: ~4000 nama threat actor, demonym APAC,
allowlist IOC). 6. Admin pertama lewat `POST /api/auth/init`, password acak ditulis ke
`secrets/admin_password` (mode 600, tidak pernah dicetak). 7. Sinkron katalog MITRE ATT&CK. 8. Worker, lalu
**beat terakhir** (beat yang menembak jadwal). 9. Web + nginx (sertifikat self-signed otomatis).

### Sesudah naik

1. Buka `https://<host pertama di NGINX_TLS_HOSTS>`, login `admin` dengan password di `secrets/admin_password`,
   **ganti password lewat UI lalu hapus file itu**. Endpoint `auth/init` hanya bisa dipakai selama belum ada
   user; jalankan skrip sebelum host dibuka ke jaringan.
2. Isi data lewat UI. Tanpa ini beberapa scraper sengaja idle:
   - **Admin**: client + negara, user lain;
   - **CVE → Techstack**: tanpa techstack, `new_cve` tidak menghasilkan apa-apa;
   - **X Intel → Monitored Accounts**: tanpa akun, `monitor_x` melewati run.
3. Scraper pertama kali jalan memakai mode *cold start* (maks 5 item per scraper). Tab Scrapers
   menampilkan status tiap scraper; scraper tanpa data wajibnya (poin 2) akan terlihat `empty`/idle, itu wajar.
4. Pasang timer backup Postgres (`docs/PROD_PREP.md`, `docker/ops/cti-pg-backup.*`) dan jalankan satu kali
   `verify`. Belum ada backup terjadwal secara bawaan.
5. Pantau: `docs/CUTOVER_RUNBOOK.md` bagian 4 (jam pertama), 5 (minggu pertama), 9 (troubleshooting).

### Deploy memakai DB dari backup (mis. pindah dari staging)

Untuk host baru yang database-nya mau diisi dari backup `tools/ops/pg_backup.py`, bukan DB kosong:

```bash
# di host lama: buat backup (dump + .sha256, mode 600) lalu verifikasi
PG="docker compose --env-file docker/stack.env --profile app exec -T postgres"
python3 tools/ops/pg_backup.py --pg-exec "$PG" backup --dir ~/backups
python3 tools/ops/pg_backup.py --pg-exec "$PG" verify --file ~/backups/cti-<UTC>.dump

# salin dump DAN .sha256-nya ke host baru (dump berisi hash password: jangan lewat kanal terbuka)
scp ~/backups/cti-<UTC>.dump* user@host-baru:/path/aman/

# di host baru, setelah .env dan docker/stack.env diisi:
make fresh-deploy ARGS='--restore-from /path/aman/cti-<UTC>.dump'
```

- Restore berjalan di langkah 3, sesudah Postgres naik dan **sebelum** API. Dump dari revisi migrasi yang
  lebih lama otomatis dinaikkan ke versi terbaru saat API start. Dump dari revisi yang LEBIH BARU dari kode
  ditolak oleh migrasi (jalankan kode yang sama atau lebih baru dari yang membuat dump).
- Hanya jalan di database **kosong**. Kalau sudah berisi, skrip berhenti tanpa mengubah apa pun. Menimpa
  database yang ada: tambahkan `--replace-db` (menghapus semua data; minta ketikan `timpa` kalau dijalankan
  interaktif).
- Admin baru **tidak** dibuat: login dengan user dari backup. Skrip mencetak daftar username-nya.
- Yang ikut terbawa apa adanya: password lama, data uji, dan override scraper (`scraper_config`: jadwal,
  `max_items`). Ganti password dan bersihkan data uji sebelum dipakai produksi.
- Dedup scraper (`scraper_seen`) ada di Postgres dan ikut, jadi tidak ada banjir item "cold start". Redis
  tidak ikut backup (isinya sementara).
- Password Postgres di host baru bebas berbeda dari host lama: backup tidak membawa role/password database.

### Reset total (menghapus SEMUA data)

Tidak ada target `make` untuk ini, sengaja. Kalau memang perlu mengulang dari nol di host latihan:

```bash
docker compose --env-file docker/stack.env --profile app down -v   # -v = hapus volume Postgres/Redis
rm -rf secrets                                                     # password admin lama
```

## Migrasi dari sistem lama (bukan deploy dari nol)

Butuh dump Mongo + file offset dedup dari server lama, warm start, dan cutover bertahap:
`docs/CUTOVER_RUNBOOK.md` bagian 3. Untuk membandingkan dengan sistem lama selama paralel:
`docs/PARALLEL_RUN_COMPARISON.md`.

## Dokumentasi

| File | Untuk apa |
|---|---|
| `docs/CUTOVER_RUNBOOK.md` | cutover, pantau, backup/restore, rollback, troubleshooting, **yang belum terbukti** (bagian 10) |
| `docs/PROD_PREP.md` | backup Mongo lama, timer backup Postgres, latihan rollback |
| `docs/CI_CD.md` | CI dan **CD otomatis ke produksi** (runner self-hosted, `make deploy`, rollback otomatis) |
| `docs/SECRETS_ROTATION.md` | daftar secret dan status rotasinya |
| `docs/ADDING_A_SCRAPER.md` | menambah scraper baru |
| `docs/KNOWN_BROKEN.md` | scraper yang rusak/di-waive dan akar masalahnya |
| `docs/PROGRESS.md` | catatan kerja per fase |

## Pengembangan lokal

```bash
uv sync --extra dev --locked
uv run pytest tests/unit tests/contract packages      # cepat
uv run pytest tests/integration                       # butuh Docker (testcontainers: Postgres/Redis sementara), ~7 menit
uv run ruff check . && uv run ruff format --check .
uv run mypy packages/cti-core/src packages/cti-scraper/src   # --strict hanya untuk dua paket ini (sama dengan CI)
```

Pre-commit memasang `gitleaks` (`.pre-commit-config.yaml`): commit yang berisi pola secret ditolak.
