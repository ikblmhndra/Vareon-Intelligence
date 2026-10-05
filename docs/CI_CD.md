# CI/CD

**CI** (`.github/workflows/ci.yml`): tiap push ke `main` dan tiap PR menjalankan lint, mypy, pytest
(termasuk integration), build web, cek kontrak API, validasi compose, dan build + smoke image.

**CD** (`.github/workflows/deploy.yml`): begitu CI untuk **push ke `main`** hijau, produksi di-update
otomatis. Bisa juga dipicu manual (Actions > Deploy > Run workflow).

```
merge PR -> main --CI hijau--> Deploy (runner self-hosted di host produksi)
                                 git merge --ff-only <sha> di checkout produksi
                                 tools/ops/deploy.sh:
                                   backup Postgres -> tandai image berjalan :prev -> build
                                   -> up -d (migrate dulu) -> tunggu sehat
                                   -> gagal: rollback.py ke :prev + alarm Telegram
```

Kenapa runner self-hosted: host produksi (`10.8.20.78`) IP privat, runner cloud GitHub tidak bisa
menjangkaunya. Runner mengambil pekerjaan dari GitHub lewat koneksi **keluar** (HTTPS), jadi tidak ada
port masuk/SSH yang perlu dibuka.

## Setup (sekali)

1. **Runner di host produksi.** GitHub: repo > Settings > Actions > Runners > *New self-hosted runner*
   (Linux). Ikuti perintah download dari halaman itu, lalu konfigurasi dengan label `cti-prod`:
   ```bash
   ./config.sh --url https://github.com/ikblmhndra/Vareon-Intelligence --token <TOKEN-DARI-HALAMAN-ITU> \
       --labels cti-prod --unattended
   sudo ./svc.sh install <user> && sudo ./svc.sh start
   ```
   `<user>` = user yang memiliki checkout produksi dan ada di grup `docker` (harus bisa `docker compose`
   tanpa sudo). Token berlaku sebentar dan tidak boleh ditempel ke chat/tiket.
2. **Variabel repo** `CTI_PROD_DIR` = path checkout produksi (mis. `/opt/cti-platform`), di Settings >
   Secrets and variables > Actions > *Variables*. Checkout itu berisi `.env`, `docker/stack.env`, dan
   `secrets/` (tidak ada di git).
3. **Checkout produksi harus bisa `git fetch origin` tanpa interaksi** oleh user runner (deploy key atau
   credential helper) dan bersih di branch `main`. `--ff-only` menolak kalau checkout itu menyimpang.
4. **Environment `production`** (Settings > Environments). Opsional tapi dianjurkan: *Required reviewers*,
   supaya setiap deploy menunggu persetujuan satu klik.
5. **Branch protection untuk `main`**: wajibkan status check CI dan PR review. Tanpa ini, siapa pun yang
   bisa push ke `main` otomatis bisa men-deploy ke produksi.
6. **Uji sebelum mengandalkannya**, di host produksi:
   ```bash
   make deploy ARGS='--dry-run'     # cetak rencana, tidak mengubah apa pun
   ```
   lalu jalankan workflow secara manual satu kali dan awasi.

## Yang dilakukan `deploy.sh` (juga bisa manual: `make deploy`)

| Langkah | Gagal -> |
|---|---|
| backup Postgres (`/var/backups/cti`, ubah dengan `CTI_BACKUP_DIR`) | deploy dibatalkan, belum ada yang berubah |
| tandai image container yang **sedang berjalan** sebagai `:prev` | -- |
| `docker compose build` | dibatalkan, stack lama tidak disentuh |
| `docker compose up -d` (service `migrate` menaikkan skema dulu) | rollback ke `:prev` + alarm |
| tunggu `/healthz` dan semua container sehat (maks 300 dtk) | rollback ke `:prev` + alarm |

- `:prev` diambil dari container yang berjalan, bukan dari tag `latest`, supaya deploy yang gagal tidak
  menimpa jangkar rollback dengan image yang rusak.
- Rollback otomatis memakai `tools/ops/rollback.py` **tanpa `--yes`**: kalau rollback butuh
  `alembic downgrade` (bisa menghapus kolom/tabel), skrip berhenti dan mengalarm Telegram (topik
  `debug`) dengan petunjuk manual (`docs/CUTOVER_RUNBOOK.md` bagian 7). Downgrade DB selalu keputusan manusia.
- Hasil deploy (OK atau gagal) dikabarkan ke Telegram topik `debug` lewat `.env` di checkout produksi.

## Batasan yang perlu diketahui

- **Tidak ada staging.** Yang divalidasi sebelum produksi hanya CI. Migrasi yang merusak data tidak
  tertangkap di sini; backup otomatis sebelum deploy adalah jaring pengamannya.
- **`.env` / `docker/stack.env` tidak ikut git.** Kalau sebuah PR menambah key baru, isi dulu di host
  produksi **sebelum** merge, kalau tidak aplikasi menolak start (dan deploy akan rollback).
- **Runner self-hosted = kode berjalan di host produksi.** Jangan pernah memakai label `cti-prod` di
  workflow yang terpicu PR, dan jangan membuka repo ini ke kontributor yang tidak dipercaya tanpa branch
  protection. User runner di grup `docker` setara root di host itu.
- Satu deploy dalam satu waktu (`concurrency` + `flock`). Deploy yang sedang berjalan tidak dibatalkan
  oleh commit baru; commit berikutnya menunggu giliran.
- Matikan CD sementara: Actions > Deploy > *Disable workflow* (atau hentikan service runner).
