# Pencocokan Tech di CVE Tracker

Catatan satu topik: kolom **Tech** di CVE Tracker tidak cocok dengan **Affected**. Isinya: masalah,
akar masalah, solusi yang sudah berjalan, cara memverifikasi, batasan yang masih ada, dan rencana
pengembangan (standarisasi techstack, `docs/ROADMAP.md` #19).

**Status** (2026-10-07): perbaikan filter dan tool pembersih sudah di rilis 0.2.1 (PR #8); koreksi
bug angka-versi (`graylog2-server`) sudah di `main`. **Arah standarisasi berubah hari ini**: bukan lagi
alias manual + katalog kurasi, melainkan **mirror CVE -> katalog tech -> Monitor** (7.1, desain lengkap di
`docs/ROADMAP.md` #19); belum ada kode untuk bagian barunya. Fase 1 lama (kolom `aliases` + pencocok
bersama) ada di branch `nameless/roadmap-runners`, belum di `main` (7.1.1). Perintah menjalankan tool
pembersih: `docs/SCRAPER_MAINTENANCE.md` 4.G.

---

## 1. Masalah

CVE tercatat di bawah tech yang bukan produk terdampaknya. Dilaporkan dari UI (2026-10-05):

| CVE | Tech | Affected | Sebenarnya |
|---|---|---|---|
| CVE-2026-59783 | MARIADB | Zabbix | CVE Zabbix yang menyebut MariaDB di deskripsinya |
| CVE-2026-105640 | GITLAB | plane | CVE Plane yang menyebut GitLab di deskripsinya |
| CVE-2026-105766 | NGINX | Chainguard Academy (edu) | CVE situs Chainguard Academy yang menyebut `nginx.conf` |
| CVE-2026-75786 | GRAFANA | Pandora FMS | CVE Pandora FMS yang menyebut datasource Grafana |

Tidak semua baris yang tampak janggal itu salah: CVE-2026-21589 (Tech JIRA, Affected menampilkan Bamboo
Data Center, Bamboo Server, dan 14 lainnya) advisory multi-produk Atlassian yang ringkasannya menyebut
Jira Service Management Data Center. Baris itu lolos penilaian di laporan produksi (tidak masuk `DELETE`).

**Seberapa besar.** Laporan `reconcile_cve_tech` di produksi (2026-10-07), 125 baris `cve_tracker`
(125 CVE unik, satu client):

| Hasil | Jumlah | Arti |
|---|---|---|
| Sesuai | 63 | tech cocok dengan produk terdampak |
| Salah, hapus (`DELETE`) | 52 | produk lain yang kebetulan menyebut tech |
| Salah label (`RETAG`) | 2 | tech lain milik client yang sama yang cocok |
| Salah, tapi punya ACK (`REVIEW`) | 1 | Pandora FMS/Grafana, diputuskan manual |
| Tak terverifikasi | 7 | MITRE tak terjangkau atau tanpa data |

Dari 118 baris yang bisa diverifikasi, **hanya 63 (sekitar 53%) yang benar**. Sebaran 52 baris `DELETE`
per tech:

| Tech | Baris | Produk terdampak sebenarnya |
|---|---|---|
| jira | 31 | `mcp-atlassian` (29), `gocd`, `project-management` |
| nginx | 11 | wolfSSL (3), frigate (2), Mailu, Eclipse Open VSX, grav, froxlor, sogo_yhn, Chainguard Academy |
| gitlab | 4 | drawio, dokploy, zammad, plane |
| mariadb | 3 | dbhub (2), Zabbix |
| grafana, microsoft 365, crowdstrike | 1 + 1 + 1 | novu, zammad, AiSOC |

## 2. Akar masalah

**2.1 Tech dan Affected datang dari dua sumber yang tidak pernah dibandingkan.** `new_cve` mencari ke
NVD dengan `keywordSearch=<nama tech>`, yang mencocokkan kata di **deskripsi mana pun** (semua kata,
urutan bebas). Kolom Affected diambil dari record MITRE (`containers.cna.affected`). Hasil pencarian
langsung ditulis dengan tech = kata kunci yang dipakai mencari; tidak ada langkah yang mengecek bahwa
produk terdampaknya memang tech itu.

**2.2 Dedup global per `cve_id`.** Himpunan `seen` membuat satu CVE yang kena beberapa tech (mis. Atlassian:
Jira, Confluence, Bamboo) hanya menempel ke tech yang kebetulan dicari duluan. Client yang hanya punya
Confluence tidak pernah dapat CVE itu.

**2.3 Baris lama tidak pernah dibersihkan.** Scraper hanya *upsert*, dan hanya untuk CVE yang masih
ditemukan dalam jendela 8 hari. CVE yang kemudian ditolak filter tidak diambil lagi, jadi barisnya
bertahan selamanya. Memperbaiki scraper saja tidak cukup.

**2.4 Struktural: nama tech teks bebas, dipakai oleh enam pencocok yang aturannya berbeda.** Input UI
hanya "Tech name…" tanpa validasi. Nama itu dipakai di:

| # | Tempat | Mencocokkan | Aturan | Dipakai untuk |
|---|---|---|---|---|
| 1 | `new_cve._nvd_candidates` | nama tech lawan deskripsi CVE | `keywordSearch` NVD | menemukan kandidat |
| 2 | `new_cve._tenable_candidates` | nama tech lawan ringkasan hasil | per kata (`_mentions`) | menemukan kandidat |
| 3 | `new_cve` gate (`relevant_techs`) | nama tech lawan vendor/product/CPE MITRE | per kata + angka menempel | baris `cve_tracker` |
| 4 | `score.py` `related_tech_status` | nama tech lawan judul artikel/tweet | `\b{tech}\b`, **tanpa `re.escape`** | alert topik `tech_stack` |
| 5 | `score.py` `_check_cve_vendor` → `check_tech_stack` | vendor MITRE lawan nama tech | substring, **tanpa batas kata** | alert topik `tech_stack` |
| 6 | `cve_priority.in_tech_stack` | nama CVE tracker lawan nama techstack | substring **dua arah** (`t in nama or nama in t`) | skor prioritas (bobot 20%) dan `patch_urgency` |

Tambahan: router CVE mencari `risk_ctx.get(cve.tech.lower())` ke peta `techstack_entries.name` (huruf
kecil) dari `get_risk_context` untuk `adjusted_risk_score` (exposure dan hosting). Jadi `name` sekarang
berfungsi sebagai **kunci join**, bukan sekadar label.

Nomor 3 adalah satu-satunya yang diperbaiki di 0.2.1. Nomor 4-6 punya risiko serupa (tech pendek
seperti `go` atau `edge` cocok ke kata yang cuma mengandung huruf itu; tech bertanda baca seperti
`node.js` atau `c++` di nomor 4 diperlakukan sebagai regex).

**Sejak fase 1 (2026-10-07)** nomor 2-6 memanggil satu modul, `cti_core.tech_match`. Nomor 1 (query
`keywordSearch` NVD) memang bukan pencocok, hanya pencari kandidat, dan tetap memakai nama tech apa adanya.

## 3. Solusi yang sudah berjalan

### 3.1 Gate relevansi di `new_cve` (0.2.1)

Kandidat NVD/Tenable hanya dipakai kalau nama tech muncul di salah satu dari: `vendor`, `product`,
`packageName`, atau `cpes` di `containers.cna.affected` record MITRE. Kode: `relevant_techs`,
`affected_products`, `usable_products`, `_mentions` di `scrapers/src/cti_scrapers/feeds/new_cve.py`.

Aturan pencocokan (`_mentions`):
- Huruf kecil; semua non-alfanumerik jadi satu spasi (`Palo_Alto-Networks` = `palo alto networks`).
- Nama tech harus kata utuh. **Angka (maks 4 digit) yang menempel di ujung dianggap versi mayor produk
  yang sama**: `graylog2-server` cocok dengan `graylog`, `Log4j2` dengan `log4j`. Huruf yang menempel
  tidak: `nginxplus` dan `nginxy` bukan `nginx`.
- Kalau CNA tidak mengisi produk, atau hanya placeholder (`n/a`, `unknown`, `unspecified`, `none`,
  `various`), jatuh ke ringkasan CVE. Tanpa produk dan tanpa ringkasan tidak ada bukti, dan kandidat
  tidak lolos.
- Hanya data CNA yang dipakai (bukan ADP).

CVE yang ditolak dicatat di log level info: event `cve_candidate_tech_not_affected` (field `cve_id`,
`techs`, `products`) di container `worker`.

### 3.2 Satu CVE, satu kandidat

Kandidat dikelompokkan per `cve_id` dan membawa semua tech yang memunculkannya. Setelah gate, tiap
client yang punya salah satu tech terdampak dapat barisnya. Kunci tracker `(cve_id, client_id)` hanya
menyimpan **satu** tech per baris, jadi kalau satu client punya beberapa tech yang terdampak, dipakai
yang **paling awal menurut abjad** (daftar techstack di `reference_data` memang diurutkan abjad).

### 3.3 Membersihkan baris lama: `tools/ops/reconcile_cve_tech.py`

Mengambil ulang record MITRE tiap CVE di tracker dan menilai baris dengan fungsi yang sama dengan
scraper (satu definisi "cocok"):

| Aksi | Kapan | Efek dengan `--apply` |
|---|---|---|
| (dibiarkan) | tech cocok | tidak ada |
| `RETAG` | tidak cocok, tapi tech lain milik client yang sama cocok | ganti `tech` |
| `DELETE` | tidak ada tech client yang cocok | hapus baris, anak-anaknya, dan penanda false positive |
| `REVIEW` | tidak cocok, tapi sudah punya ticket/ACK | **tidak pernah disentuh** |
| (dilewati) | MITRE tak terjangkau, atau tanpa produk dan tanpa ringkasan | dilaporkan "tak terverifikasi" |

Default **laporan saja**. Urutan aman: laporan, baca, backup Postgres, `--apply`. Tool memakai
pencocok dari **image worker**, bukan dari folder `tools/` yang di-mount, jadi image harus dibangun
ulang setiap pencocoknya berubah. Perintah lengkap: `docs/SCRAPER_MAINTENANCE.md` 4.G.

### 3.4 Bug lanjutan yang ketemu lewat laporan

Laporan pertama di produksi menandai `DELETE CVE-2026-69190 graylog`, padahal Affected-nya
`graylog2-server`: pencocok 0.2.1 menganggap `graylog2` kata lain dari `graylog`. Akibatnya dua:
tool hampir menghapus CVE yang sah, dan `new_cve` sendiri membuang CVE nyata untuk produk bernama
`Graylog2`, `Log4j2`, `Struts2`. Diperbaiki di `f96d23b` (aturan angka menempel di atas), dengan test
regresi. Pelajaran: **filter yang membuang diam-diam harus selalu dilihat laporannya sebelum dipercaya**
(lihat 6 dan 7.2).

## 4. Cara memverifikasi

- Test: `tests/unit/test_new_cve_tech_relevance.py` (kasus dari UI, produk berangka versi, CVE
  multi-produk, vendor saja, CPE bergaris-bawah, fallback ringkasan, Tenable),
  `tests/unit/test_reconcile_cve_tech.py` (penilai dan fetch MITRE),
  `tests/integration/test_reconcile_cve_tech.py` (hapus berantai ke anak, ticket terlindungi, retag,
  filter client; butuh Docker).
- Produksi: jalankan laporan tool secara berkala. Baris `DELETE` baru yang muncul sesudah deploy
  berarti scraper masih membiarkan CVE salah lolos; baris yang menurut lu sah tapi `DELETE` berarti
  pencocok terlalu ketat (kasus Graylog).
- Log: `docker compose logs worker | grep cve_candidate_tech_not_affected` menunjukkan apa yang
  dibuang filter.

## 5. Keputusan desain

| Keputusan | Alasan |
|---|---|
| Gate memakai produk dari **MITRE**, bukan CPE dari NVD | CPE NVD baru terisi setelah analisis (sering tertunda berhari-hari); CNA mengisi saat publish. Affected yang tampil di UI juga dari MITRE, jadi gate dan tampilan memakai data yang sama. |
| Fallback ke ringkasan saat CNA tidak mengisi produk | Tanpa fallback, CVE dari CNA yang malas mengisi produk hilang total. Dengan fallback perilakunya sama seperti sebelum 0.2.1 untuk kasus itu. |
| Baris ber-ticket/ACK tidak pernah dihapus otomatis | Menghapusnya menghilangkan jejak kerja analis. Salah label lebih murah dari hilang data. |
| Tool pembersih default laporan saja | Penghapusan permanen; laporan harus dibaca manusia dulu (Graylog ketemu dari sini). |
| Satu pencocok untuk scraper dan tool | Dua definisi "cocok" pasti bergeser; tool yang menilai dengan aturan berbeda menghapus data yang sah. |

## 6. Batasan yang diketahui

- **Recall belum pernah diukur.** Yang dibenahi 0.2.1 adalah presisi (CVE salah yang muncul). CVE yang
  seharusnya muncul tapi tidak, belum ada angkanya. Sumber risikonya:
  - `keywordSearch` hanya mencari kata di deskripsi: CVE yang menyebut "PAN-OS" tidak ditemukan oleh
    tech `palo alto`.
  - Filter membuang diam-diam bila nama produk CNA beda dari nama tech lu (nama repo GitHub, `graylog2-server`).
  - Tenable di-scrape lewat XPath yang di-hardcode dan hanya 6 baris pertama.
  - Jendela 8 hari berdasarkan tanggal publish: CVE lama yang data affected-nya baru dilengkapi tidak
    dievaluasi ulang (`lastModStartDate` tidak dipakai).
- **Pencocokan leksikal.** `nginx-ui` atau `nginx-proxy-manager` tetap cocok dengan `nginx` (batas kata).
  Tech yang berupa kata umum bisa cocok ke hal yang tidak terkait.
- **Tidak tahu versi yang dijalankan.** Tracker menandai semua CVE untuk sebuah tech, bukan hanya yang
  versinya terdampak.
- **Hierarki produk.** Outlook bagian dari Microsoft 365/Office, tapi CNA hanya menulis "Microsoft 365
  Apps". Dua baris `outlook` ter-`RETAG` ke `microsoft 365` karena itu.
- **Kualitas data CNA beragam** (produk `n/a`, nama repo, vendor kosong).
- **Cacat tampilan/data kecil yang ikut ketemu** (bukan dari perubahan ini): kolom Affected menampilkan
  `<= < 30.2.7` (`_mitre_detail` selalu menambah `<=` di depan isian `version` yang sudah memuat
  operator); `seen_products` melewatkan entri kedua untuk produk yang sama (range-nya hilang); skor 0.0
  dan severity kosong bila CNA tidak mengisi CVSS (skor NVD/ADP tidak dipakai).

## 7. Rencana pengembangan

### 7.1 Standarisasi techstack: katalog dari mirror CVE + Monitor (`docs/ROADMAP.md` #19)

**Kenapa arahnya berubah.** Alias manual per tech tidak skala (tiap client menambah tech, ada yang harus
menulis alias), dan akar masalahnya tetap: nama bebas dicocokkan sebagai teks. Ide yang disepakati
2026-10-07: biarkan **data CVE** yang mendefinisikan produk, dan biarkan pengguna **memilih** produk itu,
bukan mengetik namanya.

**Alur**: mirror semua CVE (2025 sampai sekarang) di DB sendiri -> **katalog tech** (vendor + produk
ternormalisasi) turun dari data itu -> menu techstack: tab **All Tech** (katalog; cari, klik Monitor) dan
**Monitored Tech** (per client) -> CVE baru dicocokkan lewat **identitas produk** dari data CVE -> tab CVEs
hanya menampilkan CVE untuk tech yang di-monitor, tab **CVE DB** (baca-saja) menjelajah seluruh mirror.

**Mengapa lebih kuat dari pencarian per nama:**
- Pencarian berhenti memakai `keywordSearch` (kata di deskripsi mana pun, sumber 52 baris `DELETE`).
  `new_cve` mengambil semua CVE baru/berubah sekali per jam lalu memfilter lokal berdasarkan produk
  terdampak: request lebih sedikit, recall lebih baik, dan CVE yang cuma menyebut "MariaDB" di deskripsi
  tidak ikut.
- Tidak ada panggilan MITRE per CVE (data CNA sudah ada dari feed massal), jadi batas 60/menit bukan
  bottleneck lagi, dan "Populate now" (#3) tidak diperlukan: tech baru terisi dari mirror.
- Range versi terdampak bisa disimpan -> dasar relevansi berbasis versi (7.2.3, #7).
- Hierarki produk (Outlook di bawah Microsoft 365) jadi data, bukan tambalan.

**Lapisan data dan siklus hidupnya** (jangan disamakan):

| Lapisan | Siklus hidup |
|---|---|
| Mirror CVE | dibuang retensi: tahun kalender, simpan tahun berjalan + sebelumnya (di 1 Jan 2027, CVE 2025 dibuang) |
| Katalog tech | permanen; baris yang di-monitor tidak pernah dihapus (jangan turunan sesaat dari mirror) |
| Monitored tech (`techstack_entries`) | permanen, per client, menunjuk ke katalog (nullable untuk "custom") |
| `cve_tracker` | permanen; CVE yang cocok dipromosikan (disalin) ke sini saat ingest, tanpa FK cascade ke mirror |

Ticket/ACK hidup di `cve_tracker`, jadi tidak pernah ikut retensi. Un-monitor = **sembunyikan** (flag aktif;
dashboard sudah punya scope "techstack aktif"), bukan hapus.

**Risiko utama**: data CNA berantakan (produk `n/a`, nama repo GitHub, satu produk lima ejaan, "Microsoft 365
Apps" vs "Microsoft Office"), jadi normalisasi katalog adalah pekerjaan terberat; picker harus
search-first. Produk yang belum pernah punya CVE tidak ada di katalog (jalur "custom" bertanda belum
terverifikasi). Sumber data punya kekuatan berbeda: CVE List V5 (data CNA) cepat dan lengkap tapi namanya
kotor, NVD (CPE) bersih tapi sering telat dan sebagian CVE tak pernah diperkaya; kemungkinan butuh
keduanya. **CVE lama yang baru berubah** (mis. masuk KEV) tidak masuk mirror kalau jendelanya tanggal
publish. Detail, fase, hal terbuka, dan kriteria selesai: `docs/ROADMAP.md` #19.

**Urutan**: (1) spike pengukuran, hanya baca (jumlah produk unik, persen sampah, berapa dari 34 tech produksi
ketemu bersih, sekaligus recall 7.2.1); (2) mirror + katalog baca-saja + job retensi + tab CVE DB;
(3) tab All/Monitored + `catalog_id` + validasi API; (4) ganti `new_cve`, **mode bayangan dulu** di server dev;
(5) merge produk oleh admin. Pemetaan 34 tech lama ke katalog ditinjau manual (`name` tetap kunci join).

#### 7.1.1 Fase 1 lama (alias + pencocok bersama): di branch, belum di `main`

Dikerjakan sebelum arah di atas disepakati. Keputusan: `cti_core.tech_match` dan perbaikan pencocok 5-6
(kata utuh, tanpa regex tak ter-escape) tetap berguna; kolom `aliases` + seed kemungkinan tumpang tindih
dengan katalog (rekomendasi: dibuang sebelum merge, lihat "Terbuka" di ROADMAP #19). Di bawah deskripsi
apa adanya, berlaku **hanya jika** branch itu di-merge.

**Isi:**

- **`cti_core.tech_match`** (`packages/cti-core/src/cti_core/tech_match.py`): satu definisi "teks ini
  menyebut tech itu". Aturannya diangkat dari gate 0.2.1: huruf kecil, non-alfanumerik jadi spasi
  (`Node.js` = `node js`), tech harus **kata utuh**, angka (maks 4 digit) yang menempel di ujung
  dianggap versi mayor (`graylog2-server` ~ `graylog`), huruf yang menempel bukan (`nginxy` bukan
  `nginx`). Ditambah **alias** (diperlakukan sama dengan nama) dan satu pengaman: istilah yang setelah
  dinormalisasi kurang dari 2 karakter (nama `c++` jadi `c`) tidak pernah cocok.
- **Kolom `techstack_entries.aliases`** (JSONB, NOT NULL, default `[]`), migrasi `a9d4e6f81b3c`.
  Entri yang dibuat lewat UI mulai kosong; `name` dan kunci join tidak berubah.
- **Pemanggil yang kini memakai modul itu**: gate dan filter Tenable di `new_cve`
  (`relevant_techs(..., alias_map)`), `score.py` (`related_tech_status` untuk judul artikel dan tweet,
  `check_tech_stack` untuk vendor CVE), `cve_priority.in_tech_stack`, dan penilai
  `tools/ops/reconcile_cve_tech.py` (membaca alias dari DB, jadi tool dan scraper tetap satu definisi).
  Scraper menerima alias lewat reference data baru `techstack_aliases` (`{nama ternormalisasi: [alias]}`,
  gabungan lintas client); `techstack` dan `techstack_by_client` tetap `list[str]`.
- **Seed alias** (dari daftar produksi 2026-10-07, 34 nama; sengaja konservatif):

  | Tech | Alias | Alasan |
  |---|---|---|
  | `palo alto` | `paloaltonetworks`, `pan-os`, `panos`, `globalprotect` | CNA menulis vendor/produk gaya CPE tanpa spasi |
  | `fortigate` | `fortios` | FortiOS = OS FortiGate; CNA menulis produknya `FortiOS` |
  | `mikrotik` | `routeros` | produk MikroTik di CNA bernama `RouterOS` |
  | `microsoft 365` | `office 365`, `m365` | |
  | `harmony sase` | `perimeter 81` | Harmony SASE = Perimeter 81 yang di-rebrand |
  | `perimeter81` | `perimeter 81` | nama tech tanpa spasi, CNA menulisnya dengan spasi |
  | `burp suite` | `burpsuite` | |
  | `new relic` | `newrelic` | nama paket/CPE tanpa spasi |

  Draf ini hasil penilaian, bukan data CNA. Tinjau sebelum dipercaya, dan jalankan
  `reconcile_cve_tech` (laporan saja) sesudah deploy: baris `DELETE` yang menurut lu sah berarti
  alias kurang. Alias yang terlalu umum membawa balik masalah yang diperbaiki di sini.

**Mengubah alias** (hanya jika fase 1 lama di-merge; belum ada UI/API)

```sql
-- lihat
SELECT name, aliases FROM techstack_entries WHERE aliases <> '[]'::jsonb ORDER BY name;
-- ubah (alias dinormalisasi saat dibaca, jadi huruf besar/kecil dan tanda baca bebas)
UPDATE techstack_entries SET aliases = '["pan-os","paloaltonetworks"]'::jsonb
 WHERE lower(name) = 'palo alto';
```

Berlaku di run/artikel/permintaan berikutnya **tanpa restart**: reference data dibaca tiap run
scraper, `score()` tiap artikel, `cve_priority` tiap permintaan. Alias per entri (per client), tapi
scraper menggabungkannya lintas client karena alias itu sifat produknya.

**Yang berubah di produksi bila fase 1 lama di-merge (baca sebelum deploy):**

1. **Migrasi**: `up -d` menjalankan service `migrate` (kolom nullable-safe: NOT NULL dengan default
   sementara, aman untuk data lama).
2. **Alert topik `tech_stack` dan skor prioritas CVE bisa berkurang**: pencocok 5 (substring tanpa batas
   kata) dan 6 (substring dua arah) kini kata utuh. Pasangan yang dulu cocok hanya karena substring
   (`go` ~ `google`) tidak lagi. Itu tujuannya, tapi terlihat sebagai perubahan angka/alert.
3. **Image worker harus dibangun ulang sebelum menjalankan `reconcile_cve_tech`** (tool memakai pencocok
   dari image, bukan dari folder `tools/`; sama seperti catatan 0.2.1).
4. **Belum ditangani**: pencarian kandidat (`keywordSearch` NVD, Tenable) tetap memakai nama tech
   tanpa alias, jadi CVE yang deskripsinya hanya menyebut `PAN-OS` (bukan `palo alto`) belum ditemukan
   sejak awal; alias baru menyelamatkan CVE yang SUDAH jadi kandidat dari gate. Menambah alias sebagai
   kata kunci pencarian menambah request NVD (batas 60/menit) dan jadi bahan fase 3.

Keputusan yang dibutuhkan dari user untuk fase 2-3: sumber katalog (kurasi manual dari techstack yang
ada, atau pencarian ke API CPE NVD saat menambah) dan aturan hierarki produk.

Risiko: pemetaan entri lama ke katalog harus ditinjau manusia; katalog yang tidak dirawat membuat alias
usang; sisi CNA tetap tidak terkendali, jadi alias saja tidak cukup (lihat 7.2).

### 7.2 Langkah pendukung (belum jadi item roadmap sendiri)

1. **Ukur recall.** Skrip sekali jalan di server: untuk tiap tech, bandingkan isi tracker dengan query
   CPE ke NVD untuk 30-90 hari terakhir, lalu laporkan CVE yang kelewat per tech. Hasilnya menentukan
   seberapa mendesak fase 3.
2. **Tabel kandidat yang difilter**, pola `rejected_articles`: simpan CVE yang dibuang (`cve_id`, tech,
   produk, alasan) dan tampilkan di UI supaya analis bisa mempromosikan atau menutupnya. Menggantikan
   log `cve_candidate_tech_not_affected` yang sekarang satu-satunya jejak, dan menutup risiko hilang
   diam-diam (kasus Graylog).
3. **Relevansi berbasis versi** (roadmap #7): simpan versi yang dijalankan, bandingkan dengan range
   affected, tandai Affected / Not affected / Unknown. Butuh data aset yang rapi.
4. **Perbaikan kecil** di `new_cve`: awalan `<=` ganda, `seen_products`, fallback skor dari NVD/ADP,
   `lastModStartDate`, dan Tenable (API resmi atau dibuang).

## 8. Referensi

| Apa | Di mana |
|---|---|
| Scraper dan gate | `scrapers/src/cti_scrapers/feeds/new_cve.py` |
| Tool pembersih | `tools/ops/reconcile_cve_tech.py` |
| Playbook menjalankan | `docs/SCRAPER_MAINTENANCE.md` 4.G |
| PR rilis 0.2.1 | PR #8 (`ikblmhndra/Vareon-Intelligence#8`) |
| Koreksi angka-versi | commit `f96d23b` (`nameless/dev`) |
| Pencocok bersama (fase 1) | `packages/cti-core/src/cti_core/tech_match.py`, migrasi `alembic/versions/a9d4e6f81b3c_techstack_aliases.py` |
| Pemanggilnya | `packages/cti-enrich/src/cti_enrich/stages/score.py`, `apps/api/src/cti_api/services/cve_priority.py` |
| Daftar techstack ke scraper | `packages/cti-scraper/src/cti_scraper/reference_data.py` |
| Rencana (arah baru) | `docs/ROADMAP.md` #19 |
