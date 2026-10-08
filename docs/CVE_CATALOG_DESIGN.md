# Rancangan: mirror CVE, katalog tech, dan Monitor (ROADMAP #19)

Status: **irisan 1 (resolver), 2 (skema, model, repositori), 3 (ingest), 4 (promosi + mode
bayangan), dan 5 (API) SELESAI di branch; irisan 6-7 masih rancangan** (2026-10-07). Diturunkan dari keputusan user, hasil spike di data
penuh (`docs/spikes/2026-10-07_cve_catalog_report_v2.md`, tafsir di `docs/CVE_TECH_MATCHING.md` 7.1.3), dan
alur CVE Tracker yang sekarang (`docs/CVE_TRACKER_FLOW.md`; **baca bagian 10-nya**, itu invarian yang
harus dijaga). Hal yang belum diverifikasi ditandai **[asumsi]**; yang diverifikasi ditandai **[dicek]**.

## 1. Keputusan yang sudah diambil (user, 2026-10-07)

1. Semua CVE terbit >= 2025 disimpan di DB sendiri (**mirror**). **Retensi tahun kalender**: simpan tahun
   berjalan dan tahun sebelumnya; 1 Januari 2027 CVE terbitan 2025 dibuang.
2. Katalog tech (vendor, produk) diturunkan dari data CVE. Produk yang belum ada boleh ditambah sebagai
   **custom** (bertanda belum terverifikasi).
3. Menu techstack punya tab **All Tech** (katalog) dan **Monitored Tech** (per client). Tab **CVEs** hanya
   menampilkan CVE untuk tech yang di-monitor. Tab baru **CVE DB** (baca-saja) menjelajah seluruh mirror.
4. **Unit Monitor dua tingkat: vendor dan keluarga produk.**
5. Tech yang tidak di-monitor **disembunyikan** (flag aktif), tidak dihapus; ticket tidak pernah hilang.
6. Enrichment untuk yang di-monitor = yang sudah ada sekarang (skor/risk, KEV, EPSS, ticket).
7. Versi terdampak: ikut yang sudah ada (teks di Affected + isian ticket). Tidak ada range terstruktur.
8. Notifikasi CVE baru: **sudah dibangun** (`cti_scraper.cve_alert`), memakai penanda "baris tracker baru
   dibuat"; rancangan ini harus tetap memanggil titik yang sama.
9. Normalisasi otomatis dulu; merge produk oleh admin menyusul. Diuji di **server dev** dulu, **mode
   bayangan** sebelum mengganti `new_cve`.

## 2. Fakta dari data yang membentuk rancangan

| Fakta (117.220 CVE, 2025-01-01 s.d. 2026-10-07) | Akibat pada rancangan |
|---|---|
| Volume: 2025 ±43,8 ribu; Sep 2026 14,9 ribu (3,9x Sep 2025); kemarin 1.010 baru + 929 diperbarui | Ingest harus tahan ratusan-ribuan perubahan/hari; filter per run, bukan per kandidat |
| 93,8% CVE punya identitas; ADP menyelamatkan 42; CPE hanya 7,5% | Identitas dari isian CNA; **abaikan ADP**; jangan bergantung pada CPE/NVD |
| 15.290 vendor, **79% berproduk tunggal**; 41.507 identitas; **62,9% hanya 1 CVE**; 5.546 (13,4%) >= 5 CVE | Picker search-first; tampilan awal >= 5 CVE; katalog sebagian besar ekor |
| Ejaan digabung otomatis hanya 242 (0,6%) | Normalisasi otomatis cukup untuk v1; merge admin boleh menyusul |
| **Hanya 562 keluarga bervarian > 1** (1.915 identitas, 4,6%): lipat versi otomatis nyaris tak mengubah apa pun di luar Windows/perangkat | "Keluarga" praktis = produk, dengan lipat versi untuk Windows/Dell/D-Link/Siemens; **vendor-level adalah jaring pengaman** bila lipat keluarga salah |
| Vendor tanpa nama layak: `unknown` 1.236, `n/a` 520, kosong 211 identitas (4,7%) | Vendor placeholder dibuang jadi "(tanpa vendor)", tidak bisa di-monitor di tingkat vendor |
| Vendor yang sama dieja beda: `Palo Alto Networks`/`paloaltonetworks`, `n8n io`/`n8n`, `graylog2`/`graylog`, `nagios`/`nagios enterprises llc` | Kunci vendor = bentuk kompak; sisanya perlu alias/merge manual |
| Label tech lama sering mencakup **beberapa** keluarga (`junos` = junos os + evolved + space; `jira`; `nginx` = open source + plus) atau beberapa vendor (`graylog`, `nagios`) | **Satu entri Monitor harus bisa punya banyak target** (lihat 3.4) |
| **Feed delta CVE List V5 [dicek]**: `cves/delta.json` (4 KB) hanya memuat jendela fetch terakhir; selang fetch median 18 menit, maks 62; `deltaLog.json` 24 MB menyimpan 30 hari | Polling per jam kehilangan data; lihat 5 |

## 3. Model data

Umur berbeda, jangan disamakan:

| Lapisan | Tabel | Siklus hidup |
|---|---|---|
| Mirror | `cve_records`, `cve_record_products` | dibuang retensi |
| Katalog | `catalog_vendors`, `catalog_families`, `catalog_family_aliases` | **permanen**; baris yang dirujuk Monitor tidak pernah dihapus |
| Monitor | `techstack_entries` (+kolom), `techstack_targets` | permanen, per client |
| Hasil | `cve_tracker` dst (sudah ada) | permanen, tanpa FK ke mirror |

### 3.1 Mirror

`cve_records`: `cve_id` PK; `published_date` (index; dasar retensi), `published_at`, `modified_at`;
`summary`, `cvss_score`, `cvss_severity`, `cvss_vector`, `link`, `solutions`; `references` JSONB (daftar URL);
`affected_lines` JSONB (daftar string **persis format yang kini ditulis `new_cve`**, mis. `Zabbix: < 7.0`);
`ingested_at`, `source_updated_at`. Ini semua yang dibutuhkan untuk menyalin ke `cve_tracker` (padanan
`CveItem`), jadi **tidak menyimpan JSON mentah**.

`cve_record_products`: `cve_id` FK (`ON DELETE CASCADE`), `family_id` FK (nullable bila tak teridentifikasi),
`vendor_id` FK, `vendor_raw`, `product_raw`, `has_cpe`. Index `(family_id, cve_id)` dan `(vendor_id, cve_id)`.
String mentah disimpan supaya pemetaan ulang (aturan keluarga diperbaiki) bisa dihitung ulang untuk data
yang masih dalam retensi.

### 3.2 Katalog

- `catalog_vendors`: `id`, `key` unik (**bentuk kompak**: `palo alto networks` = `paloaltonetworks`),
  `display_name` (ejaan mentah paling sering), `monitorable` (false untuk "(tanpa vendor)"), `first_seen`,
  `last_cve_at`, `cve_seen_total` (naik tiap ingest; **tidak turun saat retensi**, supaya urutan
  popularitas stabil).
- `catalog_families`: `id`, `vendor_id` FK, `key` (unik bersama `vendor_id`), `display_name`, `source`
  (`auto` | `manual` | `custom`), statistik yang sama. `custom` = ditambah pengguna, belum terverifikasi.
- `catalog_family_aliases`: `alias_key` unik -> `family_id`. Diisi otomatis untuk tiap varian yang dilipat
  (`windows 10 version 1507` -> keluarga `windows`) dan, kelak, oleh merge admin. Resolver mencari di sini
  dulu, jadi koreksi manual tidak hilang saat ingest berikutnya.

Tidak ada tabel produk terpisah: varian dilipat ke keluarga saat resolusi; nama mentah ada di
`cve_record_products` (selama retensi).

### 3.3 Resolver identitas (`cti_core.catalog_resolve`, **sudah ada**, 58 tes)

`resolve(vendor_raw, product_raw, cpes) -> (vendor_key, vendor_display, family_key, family_display) | None`.
Aturan = hasil spike, ditulis ulang sebagai modul dengan tes (spike tetap salinan lokal tanpa dependensi):
1. CPE dipakai kalau ada dan tidak wildcard; jika tidak isian CNA (`product`, lalu `packageName`).
2. Normalisasi sadar-unicode (huruf kecil, tanda baca jadi spasi, nama CJK utuh).
3. Produk **sampah** -> `None`: placeholder (`n/a`, `unknown`, ...), generik (`software`, `firmware`, ...),
   mirip-versi, angka-saja, URL. **Bukan sampah** (tetap identitas): `owner/repo`, judul panjang, memuat
   `and`/`&`.
4. Vendor placeholder/kosong -> vendor "(tanpa vendor)" (`monitorable=false`).
5. Keluarga = produk dengan token versi di ujung dibuang (`version`, `22h2`, angka, `edition`, `x64`, ...),
   dicek ke `catalog_family_aliases` lebih dulu. Akhiran noise `server core installation` ikut dibuang
   (keputusan irisan 1; tanpa itu tiap versi Windows Server menjadi dua keluarga). Pengaman: keluarga hasil
   lipat yang sama dengan vendornya tidak dipakai (`Microsoft 365` tidak boleh jadi `microsoft`).
6. Kunci vendor = bentuk kompak **tanpa akhiran legal** (`inc`, `corporation`, `ltd`, `llc`, `gmbh`, ...):
   di katalog nyata ini menggabungkan 127 grup vendor tambahan, semuanya benar (Microsoft/Microsoft Inc,
   Oracle/Oracle Corporation, D-Link/D-Link Corporation). Akhiran satu huruf sengaja tidak dipakai (menggabung
   `n` dengan `n a`).

**Hasil resolver di seluruh katalog spike (41.507 identitas, 0,5 detik)**: **39.896** pasangan (vendor,
keluarga) dan **14.911** vendor (dari 15.290); 810 keluarga melipat > 1 identitas (2.421 identitas); 1.971
identitas tanpa vendor (4,7%). Target pemetaan tabel 8 semuanya ada: `fortinet/fortios`, `junos os`/`junos os
evolved`/`junos space`, `f5/nginx open source` + `nginx plus`, `mikrotik/routeros`, vendor Fortinet (51
keluarga), Palo Alto Networks (32, dua ejaan vendor bersatu), Splunk (31). **Tetap terpisah, butuh alias
manual**: `n8nio` vs `n8n` (175 vs 22), `graylog2` vs `graylog`, `nagios` vs `nagios enterprises llc`.

### 3.4 Monitor: satu entri, banyak target

`techstack_entries` tetap: `name` (label **dan kunci join** ke `cve_tracker.tech`, tidak berubah),
`exposure`, `hosting_type`, `source`, `added_date`; **tambah** `active` (default true).

`techstack_targets` (baru): `entry_id` FK (`ON DELETE CASCADE`), `vendor_id` FK **atau** `family_id` FK
(`CHECK` tepat satu terisi). Contoh: `junos` -> {family `junos os`, `junos os evolved`, `junos space`};
`fortinet` -> {vendor `fortinet`}; `nginx` -> {family `nginx open source`, `nginx plus`}.

Entri **tanpa target** = entri lama/custom, tetap dicocokkan lewat teks seperti sekarang (gate `new_cve`),
sehingga tidak ada yang berhenti bekerja sebelum dipetakan.

Tombol **Monitor** di All Tech membuat entri (label = nama tampilan, hak `exposure`/`hosting` default
seperti sekarang) dengan **satu** target; menambah target ke entri yang ada = langkah terpisah (UI sederhana
dulu).

## 4. Pencocokan dan promosi ke `cve_tracker`

Untuk tiap record mirror yang baru/berubah:
1. Resolve produknya -> himpunan `(vendor_id, family_id)`.
2. Entri aktif per client yang punya target cocok (target vendor cocok bila `vendor_id` ada di himpunan;
   target keluarga bila `family_id` ada) **ATAU** entri tanpa target yang lolos gate teks lama
   (`relevant_techs` pada string vendor/produk, ringkasan sebagai cadangan).
3. Satu baris per `(cve_id, client_id)` (invarian: satu tech per baris). Bila beberapa entri cocok, pilih
   **yang paling spesifik** (ada target keluarga cocok > hanya vendor > teks), lalu yang paling awal menurut
   abjad (aturan sekarang), agar deterministik.
4. `CveTrackerRepo.upsert_with_status` dengan field yang disalin dari `cve_records`; **`detected_on` diisi
   saat INSERT** (waktu sistem menemukan, bukan tanggal publish; dasar MTTD) dan **tidak ditimpa**. Baris yang
   dibuat dicatat ke `Session.info["cve_new_rows"]` sehingga ringkasan Telegram yang ada jalan tanpa diubah.
5. Tidak mengecek false positive saat ingest (sama seperti sekarang; disembunyikan di query).

Pemicu lain: entri **baru di-Monitor** -> jalankan sekali terhadap seluruh mirror (riwayat langsung terisi;
tombol "Populate now" #3 tidak diperlukan). Ringkasan Telegram tidak ikut mengumumkan riwayat itu karena
batas umur 3 hari di `cve_alert`.

## 5. Ingest dari CVE List V5

**[dicek]** `https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/delta.json` berisi
`fetchTime`, `numberOfChanges`, `new[]`, `updated[]`, `error[]`; tiap elemen punya `cveId`, `githubLink`
(URL berkas raw), `dateUpdated`. Hanya jendela fetch terakhir; `deltaLog.json` (24 MB, 30 hari) menyimpan
riwayat.

- Tugas `cve.mirror_sync` (queue `maintenance`) **tiap 5 menit**: ambil `delta.json`, bandingkan
  `fetchTime` dengan kursor (disimpan di DB), proses hanya yang baru, unduh tiap berkas `githubLink`, parse
  dengan logika parser MITRE yang sudah ada, simpan ke mirror, resolve, promosikan. **[dicek pada 2 record
  asli]** record CVE List V5 punya semua yang dibaca parser (`metrics` dengan `cvssV3_1`/`format`/`scenarios`,
  `affected[].versions` dengan `lessThan`/`lessThanOrEqual`/`status`, `references`, `solutions`, tanggal)
  serta `descriptions[lang=en]`. **Tetapi parser itu belum bisa dipakai ulang**: ia menyatu di
  `NewCve._mitre_detail` (bukan fungsi murni), dan `summary` serta `link` datang dari kandidat NVD/Tenable,
  bukan dari record MITRE. Perlu **refactor**: ekstrak `parse_cve_record(data, *, link, summary)` murni,
  dipakai `new_cve` (perilaku tidak berubah, tes yang ada jadi pengaman) dan ingest mirror
  (`summary` = `descriptions[en]`, `link` = `https://nvd.nist.gov/vuln/detail/<id>`; teks NVD dan CNA
  umumnya sama, tapi perbedaannya perlu diukur di mode bayangan).
- **Celah**: bila worker mati > selang fetch (maks 62 menit teramati), `delta.json` sudah menimpa jendela
  yang terlewat. Deteksi: `fetchTime` baru terlalu jauh dari kursor -> **catch-up lewat `deltaLog.json`**
  (24 MB, jarang), atau lewat clone/git pull. Tanpa ini data hilang diam-diam.
- **Backfill awal**: skrip ops sekali jalan memakai iterator sumber dari `spike_cve_catalog.py` (clone atau
  zip), parser dan resolver yang sama.
- Batas: `raw.githubusercontent.com` terjangkau dari environment ini **[dicek]**; ratusan sampai ~2.000
  berkas per hari. Hormati `User-Agent`/jeda; kegagalan satu berkas tidak menghentikan batch (dicatat,
  dicoba lagi di siklus berikut).

## 6. Retensi

Tugas harian (queue `maintenance`): `DELETE FROM cve_records WHERE published_date < make_date(
extract(year FROM now())::int - 1, 1, 1)` (cascade ke `cve_record_products`). Catat jumlah di log; **tidak
menyentuh** `cve_tracker`, ticket, katalog. Tes: setelah retensi, baris tracker yang berasal dari CVE yang
dibuang tetap utuh. Statistik katalog tidak turun (kolom `*_seen_total`).

## 7. API dan UI

- Katalog: `GET /api/catalog/vendors?q=&show_all=` , `GET /api/catalog/vendors/{id}/families?show_all=`,
  `GET /api/catalog/families?q=` (search lintas keluarga, hasil menyertakan vendor). **Keputusan user
  2026-10-07: tampilan jelajah menyembunyikan keluarga yang hanya punya 1 CVE** (`show_all=true` untuk
  menampilkan semuanya). Pengecualian: **pencarian (`q`) tidak menyembunyikan apa pun** (produk baru
  dengan CVE pertamanya harus tetap bisa ditemukan dan di-monitor), dan keluarga/vendor yang sudah dirujuk
  Monitor selalu tampil. Di data nyata ini menyembunyikan 24.562 dari 39.896 keluarga (61,6%): tampil 15.334
  keluarga di 5.815 vendor. Hitungan "CVE per keluarga" adalah **CVE unik per keluarga** (satu CVE yang
  mencantumkan tiga varian Windows dihitung sekali; jumlah entri di CSV spike menghitung dobel). Pagination
  wajib.
- Monitor: `POST /api/techstack` menerima `{vendor_id | family_id | custom_name}`; `POST/DELETE
  /api/techstack/{id}/targets`; `PATCH /api/techstack/{id}` untuk `active`. Perubahan kontrak ->
  regenerasi `docs/openapi.json` dan `apps/web/src/lib/api/schema.d.ts` (CI memeriksa drift).
- CVE DB: `GET /api/cve-db?q=&vendor=&family=&severity=&date_start=` baca-saja atas mirror; dari satu CVE,
  tiap produk terdampak punya aksi Monitor.
- UI: sub-view Tech Stack dipecah **All Tech** (pohon vendor -> keluarga, search-first) dan **Monitored
  Tech** (daftar sekarang + target + toggle aktif). Mengikuti `apps/web/CLAUDE.md` (Base UI, bukan Radix).
- Scope tab CVEs/stats/dashboard/export: tambah filter `active` pada techstack. **Putuskan perilaku
  techstack kosong** (sekarang = tanpa filter tech; lihat `docs/CVE_TRACKER_FLOW.md` 10.4).

## 8. Migrasi dan cutover

1. Skema baru ditambahkan **tanpa mengubah perilaku**: entri lama tanpa target, `new_cve` tetap jalan.
2. Backfill mirror + katalog dari clone (skrip ops) di dev; verifikasi jumlah dengan angka spike.
3. **Pemetaan 34 entri lama ke target ditinjau manusia** (tabel usulan di bawah), dari hasil spike:

   | Label lama | Usulan target | Catatan dari spike |
   |---|---|---|
   | fortinet | vendor Fortinet | 51 keluarga, 311 CVE |
   | fortigate | keluarga fortinet/fortios | CNA menulis `FortiOS`, nama label beda dari produk |
   | juniper | vendor Juniper Networks | 168 CVE |
   | junos | keluarga junos os, junos os evolved, junos space | butuh banyak target |
   | palo alto | vendor Palo Alto Networks | vendor dieja dua cara (kompak menyatukan) |
   | splunk, okta, proofpoint, crowdstrike | vendor masing-masing | satu vendor, banyak produk |
   | nginx | keluarga f5/nginx open source + nginx plus | JANGAN vendor/nama bebas: `nginx ui`, `ingress-nginx` ikut |
   | jira | keluarga atlassian/jira software/service management (+align?) | putusan manusia |
   | graylog, nagios | dua vendor yang dieja beda | butuh alias vendor |
   | microsoft 365, outlook | keluarga Microsoft 365 Apps / Outlook | hierarki Office |
   | harmony sase + perimeter81 | satu produk (Check Point) | dua entri menunjuk produk sama |
   | gitlab, n8n, wazuh, suricata, mikrotik, anydesk, ejbca, burp suite | keluarga bersih | n8n: vendor `n8n io` dan `n8n` |
   | new relic, maxscale, extrahop, thales, esxi, grafana, mariadb, proxmox | **ditinjau satu per satu** | tak ada CVE di jendela, atau ambigu |

4. **Mode bayangan** di dev beberapa hari: pipeline baru menulis ke `cve_tracker` hanya bila flag aktif;
   sebelum itu menulis ke tabel pembanding. Hasil: CVE yang hanya ditemukan satu pihak, dengan penjelasan.
5. Alihkan; `new_cve` lama tetap tersedia sebagai cadangan (flag) beberapa rilis.
6. **Rollback**: matikan flag -> `new_cve` lama kembali; skema baru tidak perlu diturunkan.

## 9. Pembagian pekerjaan (satu PR per irisan, tiap irisan bisa di-merge sendiri)

1. **Resolver murni + tes** dari data spike (fixture asli), tanpa DB. Termasuk keputusan sufiks `server core
   installation`.
2. **Migrasi + model** mirror/katalog/target + repositori. Tes migrasi (`test_migrations_match_models`).
   **SELESAI**: revisi `b7e3d9a1c5f2`; `cti_core.db.repositories.catalog` (`CatalogRepo`, `CveMirrorRepo`,
   `retention_cutoff`); `tests/integration/test_catalog_mirror.py` (21 tes). Statistik `cve_seen_total`
   naik sekali per CVE per keluarga/vendor (idempoten, tahan urutan, tidak turun saat retensi); record
   dengan `modified_at` lebih lama ditolak; entri techstack lama tetap `active` tanpa target dan tetap
   dicocokkan lewat teks. Belum ada kode yang MEMAKAI tabel ini (tidak ada perubahan perilaku).
3. **Ingest**: refactor `_mitre_detail` jadi fungsi murni (tanpa mengubah perilaku `new_cve`), tugas
   `cve.mirror_sync`, kursor, catch-up, retensi. Tes dengan delta palsu + fixture asli.
   **SELESAI** (dengan flag `CVE_MIRROR__ENABLED`, default MATI):
   - `cti_core.cve_record.parse_cve_record` (parser murni; `new_cve` memakainya, 71 tes lama jadi
     pengaman), `cti_core.cve_mirror_sync` (`sync_once`, `purge_expired`), tugas `cve.mirror_sync`
     (tiap 5 menit) dan `cve.mirror_purge` (03:30 UTC) di queue `maintenance`, skrip
     `tools/ops/backfill_cve_mirror.py` (`make backfill-cve-mirror`).
   - Keputusan di luar rancangan awal: kursor + antrean percobaan ulang di `job_state`
     (`cve_mirror.state`, tanpa migrasi); **catch-up dipicu dua hal**, poll sukses terakhir > 12 menit
     (kita sendiri yang telat) atau `fetchTime` melompat > 90 menit (selang fetch teramati maks 62
     menit, jadi satu jendela hilang tak terdeteksi bila hanya melihat `fetchTime`); kunci advisory
     Postgres (satu siklus sekaligus, dipakai juga backfill); hanya tautan
     `raw.githubusercontent.com/CVEProject/cvelistV5/` yang diunduh; record REJECTED dibuang dari
     mirror; record tanpa tanggal atau di luar retensi tidak disimpan; kelebihan di atas
     `max_files_per_run` dibawa ke siklus berikut (kursor tetap maju).
   - Tes: `tests/unit/test_cve_mirror_sync.py`, `test_cve_mirror_task.py`,
     `tests/integration/test_cve_mirror_sync.py`, `test_backfill_cve_mirror.py`.
   - **Belum**: promosi ke `cve_tracker` (irisan 4), jadi mirror terisi tapi tidak mengubah apa pun yang
     dilihat user. Ukuran tabel dan waktu retensi/backfill belum diukur di data penuh (lakukan di dev
     sebelum menyalakan flag di prod).
4. **Promosi + pencocokan** ke `cve_tracker` (flag, mode bayangan), memakai `upsert_with_status`.
   **SELESAI** (flag `CVE_MIRROR__PROMOTE=off|shadow|live`, default `off`, hanya berlaku bila
   `CVE_MIRROR__ENABLED`):
   - `cti_core.cve_promotion`: `choose` (murni: target keluarga > target vendor > teks, lalu nama
     abjad, lalu `entry_id`; entri bertarget TIDAK dicocokkan lewat teks; entri tanpa target memakai gate
     teks lama `tech_match.relevant_techs`, kini dipindah ke `cti_core.tech_match`), `promote_record`,
     `promote_all`. `live` menulis `cve_tracker` lewat `upsert_with_status` (bentuk baris sama dengan
     `_cve_sink`: skor 0.0 dan vektor "" bila tak ada metrik; `detected_on` server saat INSERT; enrichment,
     ticket, FP tidak disentuh; tidak pernah menghapus baris tracker) dan mengisi
     `Session.info["cve_new_rows"]`, jadi ringkasan Telegram yang ada jalan lewat `finish_run` (dipanggil
     tugas `cve.mirror_sync` sesudah commit). `shadow` menulis tabel baru `cve_promotion_shadow`
     (revisi `e5b2d8f4a7c1`) dan tidak menyentuh tracker; bayangan ikut dibuang retensi.
   - Promosi satu record jalan di savepoint yang sama dengan upsert mirror (gagal = record dicoba ulang).
   - `reference_data` (`techstack`, `techstack_by_client`) kini hanya memuat entri `active`.
   - Tool: `tools/ops/promote_cve_mirror.py` (`make promote-cve-mirror`; seluruh mirror; laporan =
     rollback; jalur "entri baru di-Monitor" lewat `--entry`) dan `tools/ops/compare_promotion_shadow.py`
     (`make compare-promotion-shadow`; kategori sama / tech beda / hanya bayangan / hanya tracker +
     sebab).
   - **Belum / sengaja ditunda**: mematikan `new_cve` (irisan 7; selama `live` dan `new_cve` jalan
     bersama, keduanya meng-upsert baris yang sama dan `tech` bisa bergantian, tidak ada data hilang);
     tab CVEs/dashboard yang menyembunyikan entri nonaktif (irisan 5, perubahan API); pemicu otomatis
     "entri baru di-Monitor" dari UI (irisan 5, saat ini lewat tool). Gate teks memakai vendor/produk
     hasil resolver (`vendor_raw`/`product_raw`/`product_norm`), bukan `packageName`/CPE mentah seperti
     `new_cve`: selisihnya akan terlihat di perbandingan bayangan.
5. **API katalog/CVE DB/Monitor** + kontrak.
   **SELESAI** (`docs/openapi.json` dan `schema.d.ts` diregenerasi, hanya penambahan; 8 operasi baru, 2 skema
   bertambah/berubah):
   - Katalog (baca-saja, global, status Monitor per client): `GET /api/catalog/vendors`,
     `GET /api/catalog/vendors/{id}/families`, `GET /api/catalog/families?q=` (min 2 huruf). Jelajah
     menyembunyikan keluarga `cve_seen_total < 2` dan vendor yang semua keluarganya begitu (`hidden` di respons
     = berapa); `q` dan `show_all=true` tidak menyembunyikan; yang sudah dirujuk Monitor selalu tampil. Input
     `q` diperlakukan literal (bukan pola LIKE). `page_size` maks 100. Vendor "(tanpa vendor)" muncul dengan
     `monitorable=false`.
   - CVE DB: `GET /api/cve-db?q=&vendor=&family=&severity=&date_start=&date_end=` dan `GET /api/cve-db/{cve_id}`;
     tiap produk membawa `monitored`/`monitor_entry_id` (langsung atau lewat target vendor). Ringkasan di daftar
     dipotong 400 karakter, detail utuh.
   - Monitor: `POST /api/techstack` kini menerima `name` saja (entri **custom**, kontrak lama), atau
     `vendor_id` / `family_id` (entri **katalog**, `name` opsional menimpa label bawaan; label harus unik per
     client, `duplicate` bila bentrok). `POST /{id}/targets`, `DELETE /{id}/targets/{target_id}` (404/409/422
     lewat status HTTP; **target terakhir tidak bisa dilepas**, karena entri tanpa target kembali dicocokkan
     lewat teks), `PATCH /{id}` `{active}`, dan `GET /api/techstack?active=`. `TechStackOut` bertambah
     `active`, `kind` (`catalog`/`custom`), `targets`.
   - Pemicu promosi: tambah/aktifkan/target baru -> API mengirim tugas `cve.promote_entry` (setelah commit,
     best effort, hanya bila `CVE_MIRROR__ENABLED` dan `CVE_MIRROR__PROMOTE` != off) yang mengisi riwayat entri
     itu dari mirror (kandidat = record yang produknya cocok target; entri custom memindai seluruh mirror).
   - Scope tab CVEs/stats/dashboard/export/`tech-list`/`purge-orphaned`: lihat 9.5.
   - Tes: `tests/integration/test_catalog_api.py` (23), `test_cve_promotion.py` (+5 `promote_entry`),
     `tests/unit/test_monitor_trigger.py`.
6. **UI** All Tech / Monitored Tech / CVE DB.
7. Pemetaan 34 entri + cutover.

### 9.5 Keputusan irisan 5 (DIKONFIRMASI user 2026-10-08)

- **Nonaktif** (`active=false`) = berhenti dipantau dan disembunyikan, TIDAK dihapus: baris tracker, ticket,
  ACK, dan false positive tetap; mengaktifkan lagi memunculkannya kembali (dan mengisi riwayatnya dari mirror).
  Beda dari menghapus entri, yang membuat barisnya yatim dan bisa dibuang `purge-orphaned`.
- **Techstack kosong**: client tanpa entri sama sekali = tab CVEs tanpa filter tech (tidak berubah); client
  yang punya entri tapi semuanya nonaktif = tab kosong. Alternatif: selalu kosong bila tanpa entri aktif.
- **Export Excel** hanya CVE yang dimonitor, sama dengan tab (keputusan user: "export hanya cve yang
  termonitor"). Sebelumnya tidak menyaring techstack sama sekali;
  baris yatim (tech sudah dihapus) tidak lagi ikut export.
- **`score.py`/`reference_data`** hanya memakai entri aktif (artikel dan scraper tidak lagi mencari/mencocokkan
  tech yang dinonaktifkan).
- **Label entri katalog** = nama tampilan katalog (mis. "FortiOS"), harus unik per client; bentrok -> beri
  `name` lain. Label tetap kunci join ke `cve_tracker.tech`.

## 10. Risiko dan hal terbuka

- **Kualitas keluarga otomatis**: lipat versi hanya efektif di 810 keluarga; sisanya identitas = produk. Aman
  karena Monitor vendor-level ada. Picker panjang (Microsoft 425 keluarga, Siemens 1.053) **diputuskan**:
  keluarga ber-1 CVE disembunyikan di tampilan jelajah (bagian 7), pencarian tetap menampilkan semuanya.
- **Volume** terus naik (Sep 2026 14,9 ribu/bulan). Mirror akhir 2026 > 130 ribu CVE; 2027 proyeksi kasar
  lebih besar. Ukur ukuran tabel dan waktu retensi di dev sebelum prod.
- **Delta feed** bukan kontrak stabil resmi **[asumsi]**; jaga pengganti (clone/`git pull`) dan alarm bila
  `fetchTime` berhenti maju.
- **Recall pipeline vs riwayat belum terpisah**: spike dijalankan dengan `--since 2025-01-01`. Jalankan ulang
  dengan `--since` = tanggal `new_cve` mulai berjalan (dan `tracker.csv` dari DB yang sama) sebelum klaim
  apa pun tentang "kelewat keyword search".
- **Identitas tanpa vendor** (4,7%) dan CVE tanpa produk layak (6,2%): hanya terjangkau lewat teks;
  jalur teks lama dipertahankan untuk entri tanpa target, tapi CVE tanpa identitas tidak bisa dicocokkan ke
  target katalog sama sekali.
- **Tab CVEs untuk techstack kosong** dan **tahun yang dipertahankan bila CVE lama berubah** (KEV) belum
  diputuskan (lihat `docs/ROADMAP.md` #19 "Terbuka").
