# Runbook cutover: katalog tech + mirror CVE (ROADMAP #19, irisan 7)

Memindahkan pengisian `cve_tracker` dari scraper `new_cve` (pencarian kata kunci NVD/Tenable) ke
pipeline mirror: `cve.mirror_sync` -> katalog -> promosi (`docs/CVE_CATALOG_DESIGN.md`). **Tidak ada
staging**: dev dulu, prod sesudahnya dengan langkah yang sama. Tiap langkah punya cara kembali; tidak
ada yang menurunkan skema DB.

Semua fitur baru **mati secara default** (`CVE_MIRROR__ENABLED=false`, `CVE_MIRROR__PROMOTE=off`).
Men-deploy kodenya TIDAK mengubah perilaku apa pun.

## Peta keadaan (satu sakelar: env, lalu restart)

| `ENABLED` | `PROMOTE` | Mirror terisi | Bayangan | Tracker diisi oleh | `new_cve` |
|---|---|---|---|---|---|
| false | (apa pun) | tidak | tidak | `new_cve` | jalan |
| true | off | ya | tidak | `new_cve` | jalan |
| true | shadow | ya | ya (`cve_promotion_shadow`) | `new_cve` | jalan |
| true | **live** | ya | tidak | **mirror** + ringkasan Telegram | **ditangguhkan** |
| true | live + `KEEP_LEGACY_NEW_CVE=true` | ya | tidak | mirror **dan** `new_cve` | jalan (tumpang tindih) |

Env dibaca sekali per proses: setelah mengubahnya restart `worker`, `beat`, dan `api`.
`new_cve` yang ditangguhkan: tidak dijadwalkan beat, `Runner` menolaknya (status `disabled`), health
menghitungnya `disabled` (tidak muncul `stale`/`dead` di digest), tampil nonaktif di halaman scraper.

## Prasyarat (satu kali, per lingkungan)

1. **Env**: `TELEGRAM__THREAD_IDS` memuat `"cve_new": <thread id>` (`0` = chat utama). Tanpa itu ingest
   tetap jalan, hanya ringkasan CVE baru tidak terkirim. Key `CVE_MIRROR__*` opsional (default mati).
2. **Deploy kode** (CD menjalankan migrasi lebih dulu): revisi `b7e3d9a1c5f2` (katalog/mirror/target,
   `techstack_entries.active`), `d4a9c7e1b3f6` (`cvss_vector` jadi TEXT: **memperbaiki `new_cve` yang gagal
   pada vektor CVSS > 100 karakter**), `e5b2d8f4a7c1` (tabel bayangan). Semuanya aman untuk data lama.
3. **Isi mirror + katalog** dari clone CVE List V5 (`git clone` / `git pull` di mesin yang bisa ke
   github.com), ~10 menit untuk 114 ribu berkas:
   `make backfill-cve-mirror SOURCE=cvelistV5/` (laporan) lalu `ARGS=--apply`. Aman diulang.
4. **Nyalakan ingest**: `CVE_MIRROR__ENABLED=true`, `CVE_MIRROR__PROMOTE=off`, restart `worker`. Tunggu
   sampai 5 menit (jadwal `cve.mirror_sync`), lalu pantau lognya (perintah di bawah, tanpa teks tambahan):

   ```bash
   docker compose logs worker | grep cve_mirror_synced | tail -n 3
   ```

   Yang diharapkan di tiap baris: `status` bernilai `ok` atau `noop`, `failed` bernilai `0`, dan
   `gap_unrecoverable` bernilai `False`. Jalankan backfill ulang bila clone lebih tua dari saat ingest
   dinyalakan (menutup celah di antaranya).

## Tahap 1: pemetaan 34 entri (manusia, di dev)

1. UI: CVE Tracker -> **Monitored Tech** -> tiap entri "Unmapped" -> **Map to catalog**. Draf usulan:
   `docs/CVE_CATALOG_DESIGN.md` 8.3 (mis. `fortigate` = produk FortiOS, `junos` = tiga produk Juniper).
   Label sering beda dari nama CNA (fortigate != FortiOS): dialog memberi petunjuk. Bantuan kandidat:
   `make catalog-mapping CMD=suggest`.
2. Keputusan yang perlu diambil per entri: vendor-level (semua produk vendor; jaring luas, bisa membawa
   produk yang tidak dipakai) atau produk (presisi). Entri yang sengaja dibiarkan "Unmapped" tetap
   dicocokkan lewat teks seperti dulu.
3. Ekspor: `make catalog-mapping CMD=export ARGS='--out /work/mapping.json'`.

## Tahap 2: mode bayangan di dev (beberapa hari)

1. `CVE_MIRROR__PROMOTE=shadow`, restart `worker`.
2. Isi riwayat bayangan: `make promote-cve-mirror MODE=shadow` (laporan) lalu `ARGS=--apply`.
3. Bandingkan: `make compare-promotion-shadow SINCE=<tanggal new_cve mulai berjalan>`.
4. **Kriteria go** (semuanya):
   - bayangan terisi >= 7 hari dan mirror tidak basi (tidak ada "mirror basi?" pada "hanya tracker");
   - "hanya tracker" semuanya terjelaskan: sebab "entri bertarget tidak cocok CVE" berarti target salah/
     kurang (perbaiki di UI), "gate teks" berarti nama entri teks tak muncul di vendor/produk CNA;
   - "hanya bayangan" sudah ditinjau (benar = CVE yang dulu kelewat keyword search; salah = target terlalu
     luas atau gate teks terlalu longgar, mis. plugin pihak ketiga yang menyebut nama produk);
   - "tech beda" dipahami (bayangan memilih entri paling spesifik, `new_cve` memilih abjad);
   - semua entri yang dipakai sudah dipetakan, atau sengaja dibiarkan teks.

## Tahap 3: cutover `live` (dev dulu, lalu prod)

1. Prod: impor pemetaan: `make catalog-mapping CMD=import ARGS='--file /work/mapping.json'` (laporan; periksa
   "masalah" = kunci katalog yang belum ada di mirror prod), lalu `--apply`.
2. Prod: lakukan Tahap 2 singkat (bayangan + bandingkan) bila belum pernah di prod.
3. **Sakelar**: `CVE_MIRROR__PROMOTE=live`, restart `worker`, `beat`, `api`. `new_cve` berhenti dijadwalkan;
   `cve.mirror_sync` mulai menulis `cve_tracker` dan mengirim ringkasan Telegram untuk CVE baru <= 3 hari.
4. Isi riwayat TANPA membanjiri: `make promote-cve-mirror MODE=live ARGS='--since <tanggal mulai bayangan>'`
   (laporan dulu, lalu `--apply`). **Wajib `--since`**: riwayat lama yang baru ketemu masuk tracker dengan
   `detected_on` = sekarang, yang merusak MTTD dashboard. (Entri yang di-Monitor lewat UI mengisi riwayatnya
   sendiri dari seluruh mirror, sesuai keputusan "riwayat langsung terisi"; `detected_on`-nya juga = saat itu.)
5. Verifikasi (hari pertama): log `cve_mirror_synced` (`promoted_new`), ringkasan Telegram topik `cve_new`
   sampai, tab CVEs terisi, dashboard tidak aneh, halaman Scrapers menampilkan `new_cve` nonaktif, digest
   kesehatan tidak melaporkan `new_cve`.

## Rollback (kapan saja, tanpa migrasi)

- **Kembali ke `new_cve`**: `CVE_MIRROR__PROMOTE=off` (atau `shadow`), restart `worker`, `beat`, `api`.
  `new_cve` dijadwalkan lagi. Baris tracker yang sudah dibuat mirror tetap ada (ticket/ACK aman); run
  `new_cve` berikutnya meng-upsert baris yang sama.
- **Tumpang tindih / cadangan**: `CVE_MIRROR__KEEP_LEGACY_NEW_CVE=true` menjalankan keduanya; hanya
  `tech` yang bisa bergantian (mirror memilih paling spesifik, `new_cve` memilih abjad), tidak ada data hilang.
- **Matikan semuanya**: `CVE_MIRROR__ENABLED=false`. Mirror dan katalog tetap di DB (tidak dibaca apa pun).

## Catatan operasional

- **Retensi**: `cve.mirror_purge` (03:30 UTC) membuang mirror terbit sebelum 1 Januari tahun lalu; mulai
  2027-01-01 CVE terbitan 2025 hilang dari mirror. `cve_tracker`, ticket, dan katalog (statistik) tidak
  tersentuh.
- **Entri nonaktif** (Pause) = disembunyikan, tidak dihapus; mengaktifkan lagi mengisi riwayatnya.
- **Mirror basi**: bila `cve_mirror_synced` berhenti atau `gap_unrecoverable=True` (worker mati lebih lama dari
  30 hari log delta), jalankan `make backfill-cve-mirror` dengan clone segar.
- **Notifikasi** hanya untuk CVE baru <= 3 hari, per client, satu pesan per siklus ingest.
