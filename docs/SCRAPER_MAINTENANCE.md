# Merawat Scraper

Panduan operasional untuk scraper yang **sudah jalan**: cara tahu ada yang rusak,
apa artinya tiap status, dan langkah memperbaikinya. Cara menambah scraper baru ada di
[`ADDING_A_SCRAPER.md`](ADDING_A_SCRAPER.md).

> Diverifikasi terhadap kode (`health.py`, `runner.py`, `beat.py`, `routers/scraper.py`) dan
> container prod, 2026-10-05. Nama container di prod masih berawalan `niskala-intelligence-`
> (mengikuti nama folder), jadi pakai `docker compose exec <service>` dari folder project
> supaya tidak bergantung pada nama itu.

---

## 1. Cara tahu ada yang rusak

| Sumber | Isi | Kapan dilihat |
|---|---|---|
| Halaman **/scrapers** (UI, admin) | status kesehatan tiap scraper, ringkasan di atas, tab **Runs** dan **Items** per scraper | rutin, dan saat ada laporan artikel kurang |
| **Digest Telegram** `scraper_health` | satu pesan berisi daftar scraper non-`ok`, dikirim tiap `scraper_health_sweep_interval_min` (default **30 menit**). **Tidak mengirim apa-apa kalau semua `ok`/`disabled`**: diam = sehat | otomatis |
| `GET /api/scraper/health` | data yang sama untuk UI | integrasi/skrip |
| Log worker | satu baris `run_finished` per run dengan status dan jumlah item | investigasi |

Catatan: topik `scraper_health` harus ada di `TELEGRAM__THREAD_IDS`, kalau tidak
digest tidak punya tujuan.

```bash
# log satu scraper (sejam terakhir)
docker compose logs --since 1h worker worker-browser | grep "scraper_id=<id>"
```

---

## 2. Arti status kesehatan

Dihitung `cti_scraper.health.compute_health` dari run terakhir (urut terbaru dulu):

| Status | Artinya | Biasanya | Langkah |
|---|---|---|---|
| `ok` | sehat | | |
| `disabled` | sengaja dimatikan (config atau `meta.enabled=False`) | | tidak perlu tindakan |
| `stale` | belum pernah ada run sama sekali | scraper baru belum dijadwalkan | cek `beat` sudah di-restart (bagian 5) |
| `dead` | run terakhir lebih dari **3x interval** jadwalnya | `beat`/`worker` mati, queue macet | bagian 4.A |
| `degraded` | run terakhir gagal (`fetch_error`, `parse_error`, `rate_limited`, `timeout`, `backpressure`) | situs berubah atau memblokir | bagian 4.B-D |
| `zero_yield` | **3 run terakhir berturut-turut** `empty` | selector rusak **atau** sumber memang sepi | bagian 4.C |

Status per **run** (kolom Runs): `ok`, `empty` (jalan, nol item), `parse_error`,
`fetch_error`, `rate_limited`, `backpressure`, `disabled` (dilewati karena config mati).

---

## 3. Alat bantu

```bash
# di container (prod) -- tidak butuh repo
docker compose exec worker cti-scraper list                 # semua scraper + on/off + jadwal
docker compose exec worker cti-scraper list --tag vendor
docker compose exec worker cti-scraper dry-run <id>         # ambil dari sumber asli, TIDAK menulis apa pun
docker compose exec worker cti-scraper run <id>             # jalan sungguhan (menulis DB, dedup aktif)
docker compose exec worker cti-scraper run <id> --prime     # tandai semua item sebagai seen, tanpa menyimpan
docker compose exec worker cti-scraper disable <id> --reason "situs berubah"
docker compose exec worker cti-scraper enable <id>
```

Di **UI /scrapers** (admin): Dry-run, Trigger (jalan sekali via Celery di queue yang benar),
Enable/Disable, ubah Config, Reset config, Reset dedup.

| Aksi | Efek | Butuh restart? |
|---|---|---|
| Disable (UI/CLI) | run berikutnya langsung berstatus `disabled`, tidak menyentuh HTTP | **Tidak** (Runner mengecek config tiap run) |
| Enable scraper yang tadinya tidak terjadwal | mulai dijadwalkan | **Ya, restart `beat`** (beat membangun jadwal saat start dan melewati yang disabled) |
| Ubah `schedule` | jadwal baru | **Ya, restart `beat`** |
| Ubah `rate_limit` / `max_items` / opsi | dipakai run berikutnya | Tidak |
| Reset config | hapus semua override, kembali ke default kode | beat bila ada `schedule` yang berubah |
| Reset dedup | run berikutnya menganggap SEMUA item baru (tetap kena cold-start cap 5 item) | Tidak |

Restart beat: `docker compose restart beat`.

`dry-run` dan `trigger` di UI memakai pilihan admin yang tersimpan; `cti-scraper dry-run`
di CLI memakai default kode kecuali diberi `--option key=value`.

---

## 4. Playbook per masalah

### A. `dead` / scraper tidak pernah jalan

1. `docker compose ps`: `beat`, `worker`, `worker-browser`, `redis`, `postgres` harus `Up (healthy)`.
2. `docker compose logs --since 30m beat | tail`: beat menolak start kalau registry kosong (`registry scraper KOSONG`).
3. Run terakhir kapan? Tab Runs. Kalau semua scraper `dead` sekaligus, itu masalah infra (beat/redis/worker), bukan satu scraper.
4. Satu scraper saja `dead` padahal beat jalan: cek jadwalnya (`cti-scraper list`) dan apakah ia `enabled`. Tick kedaluwarsa setelah satu interval jadwalnya (`expires`), jadi worker yang mati lama tidak memicu banjir saat pulih.
5. Scraper `browser` saja: cek `worker-browser` (memori/`shm_size`, crash Chromium).

### B. `parse_error` (situs berubah)

Artinya dokumen terbaca tapi strukturnya tidak sesuai, **bukan** gangguan jaringan, dan
framework sengaja **tidak** me-retry.

1. Lihat pesan error di Runs (`ParseError: ...`): "gak ada node di item_path", "XML gak valid", atau "title_xpath ... gak match".
2. Lihat apa yang sebenarnya dikembalikan sumber sekarang:
   ```bash
   curl -sL -A "Mozilla/5.0" "<url feed/halaman>" | head -60
   ```
   - Halaman berisi challenge/captcha/blokir (Cloudflare, "Access denied")? Ini pemblokiran, bukan perubahan struktur: lanjut ke bagian D.
   - RSS-nya pindah URL (redirect, `/feed` -> `/rss.xml`)? Ubah `feeds`.
   - Struktur HTML berubah? Perbaiki XPath.
3. Perbaiki di repo dev, lalu:
   ```bash
   uv run cti-scraper dry-run <id>
   uv run cti-scraper verify <id> --record     # rekam baseline BARU setelah perbaikan terbukti benar
   uv run cti-scraper verify <id>              # harus OK
   ```
   Periksa `tests/fixtures/<legacy_script>/expected_items.json` secara manual sebelum commit.
4. Deploy (`worker worker-browser beat api`, lihat ADDING bagian 8), tunggu satu tick, cek Runs.
5. Kalau parser sempat mengeluarkan sampah (judul/URL salah) ke dedup/artikel: setelah perbaikan,
   **Reset dedup** supaya item benar diproses ulang. Artikel sampah yang sudah masuk tidak
   terhapus otomatis (belum ada alat khusus; bersihkan lewat SQL dengan hati-hati,
   cek dulu dengan `select` berdasarkan `source` dan rentang waktu).

### C. `zero_yield` / `empty` terus

Bedakan "sumber sepi" dari "selector rusak":

```bash
docker compose exec worker cti-scraper dry-run <id>      # status=empty?
curl -sL "<url>" | grep -c "<item\|<article"             # sumber punya item?
```

- Sumber punya item tapi scraper kosong -> selector/`item_path` rusak, perbaiki seperti bagian B.
- Sumber memang jarang terbit (blog bulanan) -> wajar. Longgarkan jadwal (mis. harian) supaya tidak terus ditandai; jangan dimatikan hanya karena sepi.
- Filter `_include_item` terlalu ketat (mis. kategori yang sumber hapus) -> cek filternya.

### D. `fetch_error` / `rate_limited`

| Pesan | Penyebab | Langkah |
|---|---|---|
| 403 / 429 / halaman challenge | situs memblokir bot atau laju terlalu tinggi | naikkan interval `schedule`, turunkan `rate_limit`; kalau tetap, pertimbangkan `runtime="browser"` atau sumber lain. **Jangan** menembus captcha. |
| timeout / connection reset | sumber lambat atau jaringan | transient, di-retry otomatis (`max_retries`); kalau permanen, naikkan `timeout_s` |
| `ConfigError` stage `config` | secret/credential kosong di env (mis. `NVD__API_KEY`) | isi secret di `stack.env`, restart service |
| 5xx terus-menerus | sumber down | tunggu; `disable --reason` kalau berhari-hari |

`rate_limit` dihitung **per domain**: dua scraper ke host yang sama berbagi budget,
jadi menambah scraper baru ke domain yang sudah dipakai bisa memicu `rate_limited` pada
yang lama.

### E. `backpressure`

Antrian `enrich` melewati `Settings.scraper.enrich_queue_max_depth` (default **2000**), jadi
sink sengaja menolak dispatch. Item **tidak** ditandai seen (dicoba lagi run berikutnya
setelah antrian surut). Yang dicek adalah sisi enrichment, bukan scraper: apakah `worker-nlp`
hidup, apakah gateway LLM sehat (lihat log `classify_json_failed`), dan apakah ada ledakan
artikel dari satu scraper (Runs -> `items_new` besar).

### F. Scraper mengeluarkan terlalu banyak / sampah

- `max_items` membatasi per run. Kalau tiba-tiba mentok di batas, parser kemungkinan menangkap elemen salah (menu, iklan).
- Lihat tab **Items**, cari pola judul/URL yang tidak masuk akal, perbaiki selector, lalu Reset dedup.

### G. CVE Tracker: kolom Tech tidak cocok dengan Affected

Gejala: CVE tercatat di bawah tech yang bukan produk terdampaknya (Tech `mariadb`, Affected
"Zabbix"). Penyebabnya `keywordSearch` NVD yang mencocokkan kata di deskripsi mana pun; sejak 0.2.1
`new_cve` hanya menerima CVE kalau nama tech muncul di vendor/product/CPE record MITRE. Run yang
sehat TIDAK membersihkan baris lama -- CVE yang sekarang ditolak tidak pernah di-fetch lagi.
Latar belakang, aturan pencocokan, dan batasannya: `docs/CVE_TECH_MATCHING.md`.

Jalankan dari folder repo di server (yang berisi `docker-compose.yml`). `compose run` otomatis masuk
jaringan dan env aplikasi, jadi tidak perlu `--network` ataupun `--env-file`:

```bash
# 1) laporan saja (default) -- tidak menulis apa pun
docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \
  -v "$PWD/tools:/tools:ro" --entrypoint python worker /tools/ops/reconcile_cve_tech.py

# 2) satu client saja: tambahkan di ujung perintah yang sama, mis.  --client acme
# 3) setelah laporan dibaca dan masuk akal: tambahkan di ujung perintah yang sama  --apply
```

Pakai `docker compose run`, bukan `docker run --env-file .env`: yang terakhir tidak membuang komentar
inline di `.env` (lihat `tools/ops/deploy.sh`, pola yang sama).

Tiap baris dinilai ulang dengan aturan yang sama dengan scraper: `RETAG` (tech lain milik client
yang sama yang cocok), `DELETE` (tidak ada yang cocok), `REVIEW` (tidak cocok tapi sudah punya
ticket/ACK -- **tidak pernah dihapus otomatis**, putuskan manual). CVE yang record MITRE-nya tak
terjangkau atau tanpa data dilewati dan dihitung "tak terverifikasi". Butuh akses ke
`cveawg.mitre.org`, ~1 request/detik per CVE unik. Idempoten, aman diulang.

### H. Export Excel: "CVE Reported Date" tampil tanggal saja (tanpa jam)

Gejala: di export CVE Tracker kolom **CVE Reported Date** berisi `31-08-2026`, bukan
`20:53 31-08-2026`. Kolom itu membaca `cve_tracker.published_at` (jam publish dari MITRE, ditulis
`new_cve`); CVE yang masuk sebelum kolom itu ada, atau yang MITRE-nya tidak memberi jam, kosong dan
jatuh ke tanggal `published`. (**Reported by System** tidak terpengaruh: itu `detected_on`, kapan
scraper pertama dapat CVE-nya.)

```bash
# di host produksi (checkout repo, stack sudah jalan). Laporan saja (default) -- tidak menulis apa pun
make backfill-published-at                      # atau ARGS='--client <client_id>' untuk satu client
# setelah laporan dibaca dan masuk akal:
make backfill-published-at ARGS='--apply'
```

Target `make` menjalankan tool di container `worker` yang sudah ada (image, `.env`, dan network ikut
service itu; `tools/` di-mount read-only; postgres/redis/migrate tidak disentuh). Tanpa checkout repo, pakai
bentuk `docker run` seperti 4.G dengan `/tools/ops/backfill_cve_published_at.py`.

Hanya baris dengan `published_at` NULL yang disentuh, dan yang sudah terisi tidak pernah ditimpa.
Baris yang tanggal MITRE-nya beda dengan `published` tersimpan dilaporkan `MISMATCH` dan **tidak
ditulis**; CVE yang MITRE-nya tak terjangkau atau tanpa jam dilewati ("tak terverifikasi"). Butuh
akses ke `cveawg.mitre.org`, ~1 request/detik per CVE unik. Idempoten, aman diulang.

---

## 5. Perubahan yang perlu deploy

| Perubahan | Rebuild | Restart |
|---|---|---|
| File scraper baru/diubah | `worker worker-browser beat api` | otomatis lewat `up -d --build` |
| Hanya config via UI (rate_limit, max_items, opsi, enable/disable) | tidak | tidak (kecuali jadwal/enable dari kondisi tak terjadwal: `beat`) |
| Variabel env (secret/credential) | tidak | service yang memakainya |

```bash
docker compose --profile app up -d --build worker worker-browser beat api
```

Kenapa `api` ikut: ia membaca registry untuk daftar di `/scrapers`, dry-run, dan trigger.

---

## 6. Aturan jangan dilanggar

- **Jangan mengubah `meta.id`** scraper yang sudah jalan. `id` = namespace dedup + kunci control plane; mengubahnya mereset dedup. Mau mengganti nama tampilan? Ubah `source` (perhatikan: label artikel lama tidak ikut berubah). Mau benar-benar pindah id? Buat scraper baru, `--prime`, matikan yang lama.
- **Jangan menghapus file scraper** untuk "mematikan". Gunakan `disable --reason "..."` (jejak alasan tersimpan di config) atau `meta.enabled=False`. Menghapus file membuat riwayat run dan config yatim, dan efeknya ke UI belum diuji.
- **Jangan menelan error di `fetch()`**. Scraper rusak yang kelihatan sehat lebih berbahaya dari yang kelihatan rusak.
- **Jangan menaikkan frekuensi tanpa alasan**. 15-60 menit cukup untuk blog vendor; kebanyakan sumber tidak terbit tiap menit, dan itu cuma menambah risiko diblokir.
- Perbaikan selector **harus** disertai fixture baru yang diperiksa manual, supaya regresi berikutnya tertangkap.

---

## 7. Rutinitas berkala

**Mingguan (±10 menit)**
- Buka `/scrapers`: urutkan menurut status. Tangani `parse_error` dan `dead` dulu.
- `zero_yield`: bedakan sepi vs rusak (bagian 4.C). Jangan dibiarkan menumpuk tanpa keputusan; kalau sengaja dibiarkan, catat di `docs/KNOWN_BROKEN.md` atau matikan dengan `--reason`.
- Cek digest Telegram: scraper yang sama muncul berulang = ada masalah yang belum selesai.

**Bulanan**
- Tinjau sumber yang sudah mati permanen (situs tutup, RSS dihentikan): `disable --reason` atau hapus lewat PR.
- Tinjau kualitas, bukan hanya jalan: scraper mana yang artikelnya paling banyak ditolak
  (`rejected_articles`, kelompokkan per `source`)? Sumber yang hampir semuanya ditolak
  membuang kuota LLM; pertimbangkan matikan atau filter lewat `_include_item`.
- Perbarui dependensi (`uv lock --upgrade-package ...`), terutama `playwright` (image Chromium) dan
  `lxml`/`httpx`; jalankan `pytest tests/contract tests/unit`.
- Segarkan fixture scraper yang berubah banyak (`verify --record`, periksa hasilnya).

**Saat menambah scraper ke domain yang sudah dipakai**
- Ingat budget rate limit dibagi per domain (bagian 4.D).

---

## 8. Ringkasan: "scraper X bermasalah, ngapain?"

```
UI /scrapers atau digest Telegram -> status?
  dead        -> infra: beat/worker/redis/queue            (4.A)
  parse_error -> situs berubah: curl, perbaiki, verify     (4.B)
  zero_yield  -> sepi atau rusak? curl bandingkan          (4.C)
  fetch_error -> blokir/credential/timeout                 (4.D)
  backpressure-> cek enrichment, bukan scraper             (4.E)
  CVE: Tech tidak cocok dengan Affected -> reconcile_cve_tech (4.G)
  Export CVE: Reported Date tanpa jam    -> backfill_cve_published_at (4.H)
Sudah diperbaiki? -> deploy (bagian 5) -> tunggu satu tick -> cek Runs -> (kalau perlu) Reset dedup
```
