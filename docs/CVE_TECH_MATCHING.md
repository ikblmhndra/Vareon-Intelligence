# Pencocokan Tech di CVE Tracker

Catatan satu topik: kolom **Tech** di CVE Tracker tidak cocok dengan **Affected**. Isinya: masalah,
akar masalah, solusi yang sudah berjalan, cara memverifikasi, batasan yang masih ada, dan rencana
pengembangan (standarisasi techstack, `docs/ROADMAP.md` #19).

**Status** (2026-10-07): perbaikan filter dan tool pembersih sudah di rilis 0.2.1 (PR #8); koreksi
bug angka-versi (`graylog2-server`) sudah di `main`. **Arah standarisasi berubah hari ini**: bukan lagi
alias manual + katalog kurasi, melainkan **mirror CVE -> katalog tech -> Monitor** (7.1, desain lengkap di
`docs/ROADMAP.md` #19); belum ada kode untuk bagian barunya. Pencocok bersama `cti_core.tech_match`
(tanpa kolom `aliases`, dibuang) ada di branch `nameless/roadmap-runners`, belum di `main` (7.1.1). Perintah menjalankan tool
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

**Koreksi 2026-10-07: sebenarnya ada tujuh pencocok.** Yang ketujuh, `reports/cve_record.py::applicable_to_stack`
(laporan Top CVE, label "Might Applicable to Organization!"), memakai substring `re.escape(tech)` terhadap
vendor tanpa batas kata; lihat `docs/CVE_TRACKER_FLOW.md` 9.

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
- Hierarki produk (Outlook di bawah Microsoft 365) jadi data, bukan tambalan.
- **Versi terdampak: tetap seperti sekarang** (teks di kolom Affected + isian ticket); range versi terstruktur
  tidak dibangun (keputusan user 2026-10-07).

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

#### 7.1.1 Pencocok bersama `cti_core.tech_match`: di branch, belum di `main`

Dikerjakan sebelum arah di atas disepakati. Versi dengan kolom `techstack_entries.aliases`, migrasi, seed 8
tech, dan reference data `techstack_aliases` **dibuang** (user 2026-10-07): identitas produk nanti datang dari
katalog, bukan alias tulis tangan. Yang tersisa:

- **`cti_core.tech_match`** (`packages/cti-core/src/cti_core/tech_match.py`): satu definisi "teks ini
  menyebut tech itu". Aturannya diangkat dari gate 0.2.1: huruf kecil, non-alfanumerik jadi spasi
  (`Node.js` = `node js`), tech harus **kata utuh**, angka (maks 4 digit) yang menempel di ujung
  dianggap versi mayor (`graylog2-server` ~ `graylog`), huruf yang menempel bukan (`nginxy` bukan
  `nginx`). Satu pengaman: istilah yang setelah dinormalisasi kurang dari 2 karakter (nama `c++` jadi `c`)
  tidak pernah cocok.
- **Pemanggilnya**: gate dan filter Tenable di `new_cve`, `score.py` (`related_tech_status` untuk judul
  artikel dan tweet, `check_tech_stack` untuk vendor CVE), `cve_priority.in_tech_stack`, dan penilai
  `tools/ops/reconcile_cve_tech.py` (jadi tool dan scraper tetap satu definisi). Tidak ada migrasi.
- **Belum disatukan**: `reports/cve_record.py::applicable_to_stack` (pencocok ketujuh). Tesnya
  (`test_cve_record.py`) mengunci `c++` ~ `c++ inc`, bertentangan dengan aturan istilah pendek, jadi itu
  perubahan perilaku yang harus diputuskan.
- **Nama lain produk yang sama** (`PAN-OS` untuk `palo alto`, `RouterOS` untuk `mikrotik`) **tidak**
  tertangani tanpa alias; itu tugas katalog. Selama katalog belum ada, CVE yang produk CNA-nya bernama lain
  dari nama tech tetap ditolak gate (batasan yang sama dengan 0.2.1; lihat 6).

**Yang berubah di produksi bila branch ini di-merge (baca sebelum deploy):**

1. Tidak ada migrasi.
2. **Alert topik `tech_stack` dan skor prioritas CVE bisa berkurang**: pencocok 5 (substring tanpa batas
   kata) dan 6 (substring dua arah) kini kata utuh. Pasangan yang dulu cocok hanya karena substring
   (`go` ~ `google`) tidak lagi. Itu tujuannya, tapi terlihat sebagai perubahan angka/alert.
3. **Image worker harus dibangun ulang sebelum menjalankan `reconcile_cve_tech`** (tool memakai pencocok
   dari image, bukan dari folder `tools/`; sama seperti catatan 0.2.1).

#### 7.1.2 Menjalankan spike pengukuran

`tools/ops/spike_cve_catalog.py` (hanya pustaka standar Python 3.10+, tanpa DB/jaringan/image; jalan di
server dev atau laptop mana pun). Sumber: clone CVE List V5.

```bash
git clone --depth 1 https://github.com/CVEProject/cvelistV5          # beberapa GB, sekali saja
# opsional, untuk recall terhadap tracker (jalankan di host yang punya akses Postgres):
docker compose --env-file docker/stack.env --profile app exec -T postgres psql -U cti -d cti -c \
  "\copy (SELECT DISTINCT cve_id, tech FROM cve_tracker WHERE tech IS NOT NULL) TO STDOUT CSV HEADER" \
  > tracker.csv
python3 tools/ops/spike_cve_catalog.py --source cvelistV5 --since 2025-01-01 \
  --tracker-csv tracker.csv --out spike_report.md --catalog-csv spike_catalog.csv
```

`--source` juga menerima zip rilis (zip bersarang ditangani; bentuk bersarang itu **asumsi** yang belum
dicek terhadap rilis sungguhan, jadi pakai clone kalau ragu). `--id-years` melebarkan tahun ID yang dipindai
(default tahun sebelum `--since` sampai tahun ini; tahun di nama berkas BUKAN tahun terbit). Uji skala:
60.000 berkas sintetis selesai dalam 31 detik dan 154 MB.

Laporan menjawab: berapa CVE punya produk yang layak (CNA, dan yang diselamatkan ADP), berapa identitas
(vendor, produk) mentah vs ternormalisasi vs digabung ejaannya vs **keluarga produk** (varian versi
Windows dst.), jenis dan contoh sampah, ekor panjang (berapa identitas punya >= 5 CVE), kandidat merge,
produk teratas, **vonis per 34 tech** (`bersih` / `satu vendor, banyak produk` / `ambigu` / `tidak ada`),
dan recall terhadap tracker (`keduanya` / `hanya-tracker` / `hanya-katalog`). Bagian "Batas pengukuran"
di laporan menyebut apa yang tidak diukur.

**Dibaca dari 10 record asli CVE 2025 yang dipakai memvalidasi skrip** (bukan hasil spike penuh):
(a) Microsoft menulis tiap versi Windows sebagai produk sendiri, jadi ukuran katalog menyesatkan tanpa
hitungan keluarga; (b) Palo Alto muncul sebagai `Palo Alto Networks` DAN `paloaltonetworks` (dari CPE) dan
satu tech menyentuh banyak produk (PAN-OS, Prisma, Cloud NGFW): kasus hierarki, bukan ambigu;
(c) `kubernetes | ingress-nginx` cocok kata utuh `nginx` dan vonisnya `bersih` padahal bukan F5 nginx:
vonis mengukur konsistensi nama, bukan kebenaran produk, jadi tinjau manusia tetap wajib.

#### 7.1.3 Hasil spike di data penuh (2026-10-07)

Laporan lengkap: `docs/spikes/2026-10-07_cve_catalog_report.md` (versi pertama skrip; baca catatan di
atasnya soal tiga angka yang menyesatkan). 153.413 berkas dibaca, **117.220 CVE terbit sejak 2025-01-01**.

**1. Volume tumbuh cepat.** 2025 = ±43,8 ribu CVE; 2026 sampai 7 Oktober = ±73,4 ribu (sudah 1,7x tahun
lalu). Per bulan: Maret 2026 5,9 ribu, Juli 9,7 ribu, **September 14,9 ribu (3,9x September 2025)**.
Sekarang ±500 CVE/hari. Dengan retensi tahun kalender, mirror di akhir 2026 > 130 ribu CVE dan 2027 bisa
lebih besar lagi (proyeksi kasar, bukan hasil ukur). Ukuran masih wajar untuk Postgres, tapi **ingest dan
filter harus dirancang untuk ratusan CVE per hari, bukan puluhan**.

**2. Ejaan bukan masalah utama.** Identitas mentah 42.710 -> ternormalisasi 37.988 -> ejaan digabung 37.770:
penggabungan otomatis hanya **218 (0,6%)**. Normalisasi sederhana cukup; *merge* oleh admin tidak perlu
masuk versi pertama (sesuai keputusan "ikut dulu"). Yang tersisa untuk digabung kebanyakan **ejaan vendor**
(`palo_alto_networks` vs `paloaltonetworks`, `n8n io` vs `n8n`, `graylog2` vs `graylog`).

**3. Ukuran katalog didominasi ekor panjang, bukan varian.** 14.633 vendor; **62,7% identitas (23.808)
hanya punya 1 CVE**, 8.994 punya 2-4, **5.186 (13,7%) punya >= 5 CVE**. Melipat varian versi hanya
mengurangi 3,8% (37.988 -> 36.543). Artinya picker harus **search-first**, dengan tampilan awal terbatas
pada identitas >= 5 CVE dan pencarian di seluruh katalog.

**4. Granularitas, bukan ejaan, masalah sebenarnya.** Daftar teratas menurut jumlah CVE didominasi varian
edisi Windows (tiap versi/edisi 1,4-2,5 ribu CVE) dan `linux | linux` (10.064, kernel); keluarga dengan
varian terbanyak: Dell Latitude 47, Siemens Industrial Edge 42, D-Link DIR 41 (model perangkat). Daftar
yang diurutkan menurut popularitas tidak berguna tanpa **pengelompokan keluarga/vendor**.

**5. Cakupan identitas.** 89,3% CVE punya >= 1 produk layak; **ADP menyelamatkan hanya 105 (0,1%)**, jadi
ADP tidak layak diurus; **CPE hanya ada di 7,5% data CNA**, jadi identitas hampir seluruhnya berasal dari
isian CNA bebas (rencana lama "query NVD berbasis CPE" tidak punya banyak bahan). "10,7% tanpa produk" adalah
**batas atas yang menggelembung** (nama CJK dan tiga heuristik sampah yang terlalu galak; sudah diperbaiki,
angka baru menunggu laporan ulang). 458 identitas (1.030 entri CVE) punya vendor `n/a`, dan 199 vendor
kosong: identitas tanpa vendor perlu aturan sendiri.

**6. Vonis 34 tech: bersih 10, satu vendor banyak produk 9, ambigu 10, tidak ada 5.**
- *Bersih*: anydesk, burp suite, ejbca, gitlab, harmony sase, microsoft 365, mikrotik, n8n, suricata, wazuh.
- *Satu vendor, banyak produk* (butuh pilihan **vendor-level atau per-keluarga**): crowdstrike, fortinet
  (311 CVE: fortios 80, fortiproxy 44, fortimanager 40, ...), juniper, junos, nessus, okta, palo alto (150),
  proofpoint, splunk (182).
- *Ambigu* (produk pihak ketiga ikut menyebut nama tech; **inilah penyebab 52 baris `DELETE` produksi**,
  dan pilihan yang harus dibuat manusia di picker): `nginx` (f5 nginx open source/plus 44 vs `0xjacky nginx ui`
  vs kubernetes `ingress-nginx`), `esxi` (vmware esxi vs driver Intel yang menyebut esxi, vendor `n/a`),
  `jira` (Jira Align vs Jira Service Management/Software), grafana, graylog, mariadb (connector), nagios,
  outlook, proxmox, thales.
- *Tidak ada*: `fortigate` (CNA menulis **FortiOS**, identitas `fortinet | fortios` 80 CVE: nama tech
  berbeda dari nama produk CNA), `new relic`, `maxscale`, `extrahop` (tidak ada CVE di jendela), `perimeter81`
  (tidak ada; produk yang sama dengan `harmony sase`, jadi dua entri produksi menunjuk satu produk).

**7. Recall tracker: 65 dari 66 baris di jendela ditemukan oleh pencocokan identitas (98,5%).** Satu-satunya
`hanya-tracker` adalah CVE-2026-75786 (Pandora FMS yang menyebut Grafana), **salah-cocok yang sudah diketahui**
(bagian 1 dokumen ini), jadi baris yang benar semuanya ditemukan. Tracker di CSV hanya 73 baris (7 di luar
jendela), jauh di bawah 125 baris laporan `reconcile` produksi: kemungkinan DB berbeda atau sudah dibersihkan,
perlu dikonfirmasi. **Arah sebaliknya belum bisa disimpulkan**: katalog menemukan jauh lebih banyak CVE
daripada tracker (fortinet 311 vs 2, palo alto 150 vs 0, splunk 182 vs 0, juniper 168 vs 0, microsoft 365
542 vs 2), tetapi itu mencampur CVE yang KELEWAT pipeline dengan riwayat yang terbit SEBELUM tracker/tech itu
ada. Memisahkannya butuh `--since` = tanggal `new_cve` mulai berjalan di DB yang sama.

**Implikasi desain** (sebagai usulan; keputusan di `docs/ROADMAP.md` #19 "Terbuka"):
1. Yang di-*monitor* perlu dua tingkat: **vendor** (semua produk, mis. Fortinet/Splunk/Juniper/Palo Alto,
   yang di techstack produksi memang ditulis tingkat vendor) atau **keluarga produk**. Satu tingkat saja
   tidak cukup untuk 9 tech "satu vendor, banyak produk".
2. Picker menyajikan **katalog bertingkat vendor -> keluarga**, search-first, default >= 5 CVE.
3. Karena 10 tech "ambigu", **pemetaan 34 tech lama ke katalog harus ditinjau manusia** (rencana sudah ada);
   tebakan otomatis akan mengulang kesalahan keyword search.
4. Normalisasi otomatis sudah cukup untuk versi pertama; vendor `n/a`/kosong dan ejaan vendor
   (`graylog2`/`graylog`) perlu aturan, merge admin boleh menyusul.
5. Abaikan ADP; jangan bergantung pada CPE; jaga fallback ke teks ringkasan untuk CVE tanpa identitas.
6. Pencarian di picker tidak akan menemukan nama panggilan tech (`fortigate` tidak akan menemukan `fortios`
   karena datanya tidak memuat kata itu); pengguna mencari "forti". Itu batas data, bukan bug.

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
| Pencocok bersama | `packages/cti-core/src/cti_core/tech_match.py` (di branch, belum di `main`) |
| Pemanggilnya | `packages/cti-enrich/src/cti_enrich/stages/score.py`, `apps/api/src/cti_api/services/cve_priority.py` |
| Daftar techstack ke scraper | `packages/cti-scraper/src/cti_scraper/reference_data.py` |
| Rencana (arah baru) | `docs/ROADMAP.md` #19 |
