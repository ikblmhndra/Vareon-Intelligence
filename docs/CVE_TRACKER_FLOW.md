# Alur CVE Tracker yang sekarang (as-is)

Catatan **keadaan nyata** CVE Tracker per 2026-10-07, ditulis sebelum merancang katalog tech + mirror CVE
(`docs/ROADMAP.md` #19) supaya rancangan baru tidak merusak apa yang sudah berjalan. Semua isi di sini
dibaca dari kode, bukan dari ingatan; yang **tidak** sempat diverifikasi ada di bagian 10. Kalau kode
berubah, perbarui file ini (bukan sebaliknya).

Dokumen terkait: `docs/CVE_TECH_MATCHING.md` (kenapa kolom Tech salah-cocok, solusi 0.2.1),
`docs/ROADMAP.md` #13-#19, `docs/SCRAPER_MAINTENANCE.md` 4.G-4.H (tool ops).

## 1. Gambaran satu halaman

```
beat (tiap jam)                                         analis (UI /cve)
  └─ scrape.run new_cve  ──► NVD keywordSearch ┐          ├─ tab CVEs: filter, lookup KEV/EPSS/Exploit-DB, export Excel
       (queue scrape.api)    Tenable (XPath)   ├─ kandidat ├─ detail modal: tab Ticket (acknowledge, isi ticket)
                             MITRE per kandidat┘          ├─ sub-view Dashboard (MTTD/MTTA/MTTR), Ticketing
                                  │ gate relevansi (nama tech ~ vendor/produk CNA)
                                  ▼                       └─ sub-view Tech Stack (tambah/hapus/exposure/hosting)
                    CveItem(client_id, tech, ...) ──► sink ──► cve_tracker  (+ references, affected)
                                                                  ▲   ▲   ▲
   cve.enrichment_sweep (tiap 3 jam, maintenance) ── KEV/EPSS/Exploit-DB ┘   │   │
   github_poc_monitor (scraper) ── CvePocItem ── cve_pocs + poc_available ───┘   │
   ticket/ack/false-positive (API) ── cve_tickets, cve_false_positives ──────────┘
```

Intinya: **`techstack_entries` (per client) menentukan CVE apa yang masuk `cve_tracker`**, lewat satu
scraper (`new_cve`). Semua yang lain (enrichment, ticket, dashboard, export) bekerja di atas baris tracker.

## 2. Ingest: scraper `new_cve`

`scrapers/src/cti_scrapers/feeds/new_cve.py`. `meta`: `id="new_cve"`, jadwal `spread("0 * * * *")` (tiap jam,
menit digeser), `rate_limit="60/minute"`, `max_items=300`, `credential="nvd"` (jadi masuk queue `scrape.api`),
`reference_data=("techstack", "techstack_by_client")`, `dedup_key()` = `None`
(**selalu upsert ulang**, karena MITRE bisa memperbarui skor).

Langkah satu run (`NewCve.fetch`):
1. Baca `ctx.reference`: daftar nama tech (distinct lintas client) dan `{client_id: [nama tech]}`.
2. **Cari kandidat** per nama tech: (a) NVD `keywordSearch=<nama>` dengan `pubStartDate`..`pubEndDate` =
   **8 hari terakhir** (berdasarkan tanggal publish), (b) Tenable `cve/search` (XPath di-hardcode, hanya 6
   baris pertama; hasil dibuang kalau ringkasannya tidak menyebut nama tech). Per tech = 2 request;
   34 tech = 68 request/jam, dipacu `get_waiting` (batas 60/menit).
3. **Satu CVE = satu kandidat** (dikelompokkan per `cve_id`, membawa semua tech yang memunculkannya).
4. **Detail dari MITRE** (`cveawg.mitre.org/api/cve/<id>`), satu panggilan per kandidat: vendor, produk,
   `affected` + range versi (jadi teks), referensi, solusi, CVSS (hanya dari CNA), tanggal modifikasi.
5. **Gate relevansi** (`relevant_techs`, 0.2.1): kandidat dipakai hanya kalau nama tech muncul di
   vendor/product/packageName/CPE milik CNA; kalau CNA tidak mengisi produk (atau placeholder `n/a`...)
   jatuh ke ringkasan. Yang ditolak dicatat di log `cve_candidate_tech_not_affected`.
6. **Proyeksi ke client**: untuk tiap client yang punya salah satu tech terdampak, satu `CveItem`. Kalau
   satu client punya beberapa tech yang kena, dipakai **yang paling awal menurut abjad**. Berhenti di
   `max_items` (300).
7. `CveItem` (`cti_scraper/items.py`) → sink (`cti_scraper/sinks.py::_cve_sink`) → `CveTrackerRepo.upsert`.

Perilaku `upsert` yang penting (`cti_core/db/repositories/cve.py`):
- Kunci `(cve_id, client_id)`. Baris baru: `INSERT`. Baris ada: **semua field yang dikirim ditimpa** (termasuk
  `tech`, `summary`, skor), `references` dan `affected` **diganti utuh** (bukan di-merge).
- `detected_on` diisi `server_default now()` hanya saat INSERT, jadi = waktu scraper pertama menemukannya
  (dasar MTTD/MTTA/MTTR); update tidak mengubahnya.
- `published_at` (jam publish MITRE) hanya ikut kalau MITRE memberinya, jadi tidak menimpa hasil backfill
  dengan `NULL`.
- Scraper **tidak** memeriksa false-positive: baris yang ditandai FP tetap di-upsert, hanya disembunyikan
  di query (bagian 5).
- Baris lama yang kemudian ditolak gate **tidak pernah dihapus** otomatis (scraper hanya upsert); pembersih
  manual: `tools/ops/reconcile_cve_tech.py` dan `POST /api/cve/purge-orphaned` (**hanya admin/superadmin**,
  termasuk dry run; default dry run).
- Data awal sebelum cutover masuk dari dump Mongo lewat `tools/seed/fase10_cve_migrate.py` (satu kali).

## 3. Model data (`cti_core/db/models/cve.py`, `techstack.py`)

| Tabel | Kunci | Isi / penulis |
|---|---|---|
| `techstack_entries` | `(name, client_id)` unik | `name` teks bebas (**label sekaligus kunci join**), `exposure` (`public`/`internal`/`both`), `hosting_type` (`on_prem`/`cloud`/`saas`), `source`, `added_date`. Ditulis UI/API (`routers/techstack.py`). Tidak ada flag aktif: ada = dipantau. |
| `cve_tracker` | `(cve_id, client_id)` unik | metadata CVE (ditulis `new_cve`), `tech` (satu nilai, teks), `cisa_kev`/`active_exploitation` (bool mesin), `epss_*`, `cisa_kev_detail`/`exploit_db_hits` (JSONB), `poc_available`, `detected_on`, `registered_date`. |
| `cve_references`, `cve_affected` | `cve_tracker_id` | anak, diganti utuh tiap upsert. `affected` = **satu string per baris** (mis. `Zabbix: < 7.0`), bukan data terstruktur. |
| `cve_pocs` | `cve_tracker_id` | ditulis `github_poc_monitor` (dan exploit-db lookup). |
| `cve_threat_actors`, `cve_ttps`, `cve_newsletter_mentions` | `cve_tracker_id` | anak lain (aktor/TTP lewat cross-reference, mention lewat newsletter). |
| `cve_false_positives` | `(cve_id, client_id)` unik | ditandai analis. **Kunci pakai `cve_id`, bukan id tracker.** |
| `cve_tickets` | `(cve_id, client_id)` unik | satu ticket per (CVE, client), `ticket_id` unik global (`CTI-2026-09-001`, urut per bulan **WIB**, **lintas client**; penomoran diserialkan `pg_advisory_xact_lock` di jalur yang langsung menyimpan ticket). Dibuat saat acknowledge atau edit manual. Juga **pakai `cve_id`, bukan id tracker**. |

`CveItem` menyimpan versi terdampak hanya sebagai teks di `cve_affected.affected`; ticket punya
`affected_version`/`fixed_version` isian analis. **Tidak ada penyimpanan range versi terstruktur**, dan itu
keputusan yang dipertahankan (user 2026-10-07: versi ikut yang sudah ada).

Hubungan penting:
- `cve_tracker.tech` ↔ `techstack_entries.name` **dibandingkan sebagai teks huruf kecil** (`get_risk_context`
  memetakan `name.lower()`), bukan foreign key. Mengganti nama entri memutus join.
- Hapus `cve_tracker` → anaknya ikut (cascade). Ticket dan FP **tidak** ikut (tidak ber-FK ke tracker):
  `purge_orphaned` menghapus FP-nya sendiri, tidak ticket-nya.
- Hapus entri techstack **tidak** menghapus CVE-nya (router sengaja tidak cascade); baris tracker tetap ada
  tapi tersembunyi dari tab CVEs sampai `purge-orphaned` dijalankan (bagian 5).

## 4. Enrichment sesudah ingest

**`cve.enrichment_sweep`** (`apps/worker/.../tasks/periodic.py`), beat tiap 3 jam, queue `maintenance`.
Tiga langkah, masing-masing try/except sendiri (gagal satu tidak menghentikan yang lain), memakai fungsi
yang sama dengan tombol manual di UI (`cti_api/services/cve_lookup.py`):
- **CISA KEV**: unduh seluruh katalog, cocokkan dengan semua CVE → `cisa_kev=True`,
  `active_exploitation=True`, `cisa_kev_detail`.
- **Exploit-DB**: scraping situs (tanpa API), batch 5 + jeda 1 detik, **per CVE**, tulis `exploit_db_hits`
  dan menambah `cve_pocs`.
- **EPSS** (FIRST.org): batch 100 → `epss_score`, `epss_percentile`, `epss_date`.

Sifat yang perlu diketahui (bukan bug yang saya tulis, apa adanya):
- Himpunan CVE = `cve_id` yang masih **true positive untuk minimal satu client**: ada satu baris tracker yang
  TIDAK ditandai FP oleh clientnya sendiri (`list_true_positive_cve_ids()`; FP dinilai per `(cve_id, client_id)`).
  Dulu hanya FP client `"default"` yang dihitung (diubah di PR #14). Hasilnya ditulis ke **semua baris
  (lintas client)** untuk `cve_id` itu.
- **Tidak ada penyaring kesegaran**: tiap 3 jam semuanya dicek ulang. Biayanya naik linear dengan ukuran
  tracker (Exploit-DB paling berat: ≥1 detik per 5 CVE + HTTP per CVE).
- Tombol "KEV/EPSS/Exploit-DB" di tab CVEs menjalankan lookup yang sama (tidak di-scope client).

**`github_poc_monitor`** (scraper, `CvePocItem` → `cve_pocs`, set `poc_available`): dua strategi
(broad: repo `cve-<tahun>-*` disaring lewat vendor/produk MITRE terhadap techstack; targeted: tiap CVE
true-positive). Alert Telegram topik `github_poc` hanya dari strategi broad.

Terkait: `trending_cve` (scraper) mengumpulkan mention CVE dari tweet ke `cve_mentions` (bukan `cve_tracker`).

## 5. Scope tab CVEs, statistik, dashboard, export

`routers/cve.py`. **"Hanya CVE untuk tech di-monitor" sebenarnya sudah begitu**, lewat dua lapis:
1. Baris `cve_tracker` hanya dibuat untuk (client, tech) yang cocok saat ingest.
2. Query list/stats/dashboard memakai `effective_tech = tech (param) or nama semua techstack client`
   (`_active_tech_names`). Sejak irisan 5 (#19) "semua techstack" = entri **aktif** (`techstack_entries.active`;
   nonaktif = disembunyikan, barisnya tidak dihapus). **Client TANPA entri sama sekali: `effective_tech = None` =
   tanpa filter tech** (semua baris tampil, perilaku lama). **Client yang punya entri tapi semuanya nonaktif:
   `[]` = tab kosong** (bukan tanpa filter; kalau tidak, "disembunyikan" berbalik arti). `purge_orphaned` memakai
   SEMUA nama (aktif + nonaktif): yang disembunyikan bukan yatim.

Filter lain: `search` (cve_id/summary/tech, ILIKE), `severity`, rentang tanggal (`date_basis`: `published` = default,
atau `detected` = hari kalender WIB saat CVE pertama terdeteksi), `ack_filter`
(`acked`/`unacked` lewat `cve_tickets.acknowledged_by`), FP disembunyikan kecuali `include_fp`. Urutan
`published`/`tech`/`severity`/`epss`. Serialisasi (`_serialize`) menambah `adjusted_risk_score` =
`cve_score × EXPOSURE_MULTIPLIER × HOSTING_MULTIPLIER` (dari `techstack_entries` lewat nama huruf kecil), jumlah dan daftar
artikel yang menyebut CVE di judul (`get_article_mentions`: ILIKE hanya penyaring kasar, lalu cocok persis dengan batas
angka, jadi `CVE-2026-1234` bukan `CVE-2026-12345`), dan status FP.
- `GET /stats`, `GET /dashboard?year=` (MTTD/MTTA/MTTR, `services/cve_dashboard.py`), `GET /export` (Excel
  dari template `CVE_Tracker_template.xlsx`, `services/cve_export.py`) memakai **scope yang sama** (client,
  techstack aktif, tanpa FP) sehingga angkanya konsisten dengan tab CVEs. (Koreksi: sebelum irisan 5 `/export`
  TIDAK menyaring techstack sama sekali, hanya `tech` dari query; sekarang `tech or entri aktif`, jadi baris
  yatim dan baris entri nonaktif tidak ikut export.)
- `GET /stats` punya bucket `unrated` (skor CVSS 0/NULL: CNA tidak mengisi CVSS) supaya critical + high + medium +
  low + unrated = total. `date_basis` juga ada di `/stats` dan `/export`. Default API: `published` untuk list/stats,
  `detected` untuk export (laporan bulanan); UI mengirim dasar yang sama ke ketiganya (default Published).
- `GET /tech-list`: tech distinct yang ada di tracker client (untuk dropdown filter).
- **`GET /freshness`** ("diupdate per kapan", `services/cve_check.py`): kapan tracker terakhir dicek, per jalur yang
  sedang mengisinya. Jalur = scraper `new_cve` (waktu dari `scraper_runs`) atau mirror CVE List V5 (`polled_at` di
  `job_state` `cve_mirror.state`) bila promosi `live`; keduanya saat `KEEP_LEGACY_NEW_CVE` (aturannya sama dengan
  `cti_scraper.supersede`, dikunci test). `last_checked_at` = run **sukses** terakhir (`ok`/`empty`/`partial`);
  percobaan terakhir yang gagal (`rate_limited`, dst.) dilaporkan terpisah (`last_run_status`) supaya tidak tampak
  seperti data baru saja diperbarui. Run `running` lebih tua dari 30 menit dianggap nyangkut (worker mati), bukan
  sedang berjalan. Juga `newest_detected_at` dan, bila `new_since` (ISO) diberikan, `new_since` = jumlah CVE baru
  tercatat (`detected_on`) sejak itu, di lingkup yang sama dengan tab CVEs (client aktif, tech dimonitor, tanpa FP).
- **`POST /check-new`** (tombol cek manual; **admin**, audit `check_new_cves`): mengirim tugas cek rutin ke jalur
  yang aktif: `scrape.run(new_cve, trigger=manual)` ke queue scraper atau `cve.mirror_sync` ke `maintenance`
  (API hanya mengirim lewat nama, pola `services/monitor.py`). Ditolak **409** bila run masih berjalan atau scraper
  dimatikan di control plane, **429** selama cooldown 120 dtk (`Retry-After` = sisa waktu; penolakan 409 tidak
  memakai cooldown), **503** bila broker mati (cooldown dilepas). Catatan: cek `new_cve` memproses **semua client**
  sekaligus (satu run global); yang per client hanya hitungan "CVE baru". Ini BUKAN "Populate now" (ROADMAP #3,
  backfill riwayat): hanya menjalankan cek rutin sekarang juga.
- `GET /prioritize`: skor prioritas (`services/cve_priority.py`): CVSS 30%, KEV 20%, exploited 20%, PoC
  10%, `in_tech_stack` 20% → label dan `patch_urgency`. Kalau satu CVE punya baris di beberapa client, baris client
  pemanggil yang dipakai (baris client lain hanya cadangan saat CVE belum di-track client itu).
- Multi-tenant: `X-Client-ID` → `effective_client_id`.

## 6. Ticket, acknowledge, false positive

- **Acknowledge** (`POST /{cve_id}/acknowledge`, `bulk-acknowledge` maks 100): wajib `analyst_name`;
  membuat/menyentuh `cve_tickets` (isi `acknowledged_by`, `acknowledge_time`, `ticket_id` bila belum ada).
- **Ticket** (`PUT /{cve_id}/ticket`): `affected_asset`/`affected_version`/`fixed_version`, `asset_owner`,
  `owner_email`/`owner_team`, `active_exploitation` (isian analis, beda dari bool mesin),
  `remediation_status`/`remediation_date_plan`/`actual_remediation_date`, `escalation_required`, `comments`,
  `risk_acceptance`, `closure_date`. Nilai status "soft enum" **tanpa validasi** (ROADMAP #18).
- **False positive** (`POST/DELETE /{cve_id}/false-positive`, `bulk-false-positive` maks 100): per
  `(cve_id, client_id)`, dicatat di audit log.
- Aksi tulis yang dibaca (false-positive, ticket, bulk-acknowledge, purge) memanggil
  `AsyncAuditLogRepo.write` lalu `commit`.
- **Ticketing view** = `GET /tickets` (ticket + ringkasan CVE: severity, skor, tech, `detected_on`, `false_positive`).
  Ticket CVE FP disembunyikan kecuali `include_fp=true` (UI mewajibkan Acknowledge sebelum Mark FP, jadi tiap CVE FP
  punya ticket).
- **Draft email** (`POST /draft-email`): 3 panggilan LLM + template `cve_notification_email.html`, membuat
  draft lewat Microsoft Graph. **Manual**, dipicu analis. Hanya baris tracker milik client aktif (`X-Client-ID`) yang
  dipakai. Tracking ID = nomor ticket yang sudah ada untuk CVE-nya (dipisah koma); nomor "intipan" berikutnya (tidak
  disimpan) hanya dipakai kalau belum ada ticket sama sekali.

## 7. Notifikasi: apa yang ADA

**CVE baru di `cve_tracker` -> ringkasan Telegram (baru 2026-10-07, di branch `nameless/roadmap-runners`, belum
di `main`).** Sebelumnya **tidak ada** notifikasi otomatis per CVE baru: `_cve_sink` hanya upsert, dan
`legacy_label="NEW CVE"` cuma label kompatibilitas health. (Koreksi atas asumsi lisan sebelumnya.) Sekarang:
- `_cve_sink` memakai `CveTrackerRepo.upsert_with_status`; kalau baris **dibuat** (INSERT, bukan update) dicatat
  `(cve_id, client_id)` di `Session.info["cve_new_rows"]`.
- `Runner.execute()` memanggil `sinks.finish_run(session)` **sesudah** run dicatat selesai ->
  `cti_scraper.cve_alert.notify_new_cves`: baca ulang baris itu dari DB, saring, kirim **satu pesan per client
  per run** ke topik Telegram `cve_new` (`TELEGRAM__THREAD_IDS`).
- Penyaring: hanya `published` dalam **3 hari terakhir** (tech baru/backfill/DB baru tidak membanjiri channel;
  tanpa tanggal publish = tidak dikirim), bukan false positive client itu. "Tech di-monitor" tidak perlu
  penyaring sendiri: baris tracker memang hanya dibuat untuk (client, tech) di `techstack_entries`.
- Format: judul + nama client + jumlah; maksimal 10 CVE (severity terparah dulu), sisanya "dan N lainnya";
  selalu < 4096 karakter (baris dikurangi sampai muat); semua teks luar di-`html.escape`.
- **Kegagalan kirim tidak menggagalkan run dan tidak dicoba ulang** (`cve_new_alert_failed` di log): karena sink
  sudah commit, run berikutnya melihat baris itu sebagai update. Topik `cve_new` belum ada di `.env` prod =
  alert tidak terkirim, ingest tetap jalan.
- **Deploy**: tambahkan `"cve_new": <thread id>` ke `TELEGRAM__THREAD_IDS` di `.env` host (nilai `0` = chat
  utama tanpa thread). `.env.example` dan `.env.prod.template` sudah memuatnya.
- Kalau pipeline diganti mirror -> promosi (#19), titik panggilnya sama: "baris `cve_tracker` baru dibuat".
  Sudah begitu di kode (irisan 4, `CVE_MIRROR__PROMOTE=live`; saat `live` scraper `new_cve` ditangguhkan, irisan 7,
  `docs/CVE_CATALOG_CUTOVER.md`): `cve_promotion` mengisi
  `Session.info["cve_new_rows"]` dan tugas `cve.mirror_sync` memanggil `finish_run` sesudah commit. Default
  `off`: alur di atas tidak berubah.

Yang lain terkait CVE (tidak berubah):

| Apa | Pemicu | Tujuan | Memakai techstack? |
|---|---|---|---|
| Alert artikel (`cti_enrich` routing) | tiap artikel di-enrich; `related_tech_status` (judul menyebut tech) atau `related_tech_cve_status` (vendor CVE di judul cocok) | topik `tech_stack` | ya, **daftar nama distinct lintas client** (`score()`) |
| Top CVE mingguan (`report.weekly_top_cve`, Minggu 07:01) | beat | `tech_stack` | ya (`techstack_names`, **lintas client**) + `applicable_to_stack` |
| Trending CVE (`report.trending_cve`, jam tertentu menit 5) | beat | `tech_stack` bila cocok, jika tidak `tech_stack_unrelated` + `vendor_report` | ya, sama |
| Alert PoC GitHub (`github_poc_monitor`) | repo baru <= 3 hari dari pencarian broad | `github_poc` | ya (lewat vendor/produk MITRE) |
| Draft email CVE | analis menekan tombol | Graph (draft) | tidak |

Digest dan alert artikel/laporan memakai nama techstack **gabungan semua client**, tidak per client; ringkasan
CVE baru di atas adalah satu-satunya yang per client.

Newsletter (`services/newsletter._enrich_articles`, global, bukan per client) juga mengkorelasikan artikel dengan
tracker: artikel yang judul/badannya menyebut CVE yang masih **true positive untuk minimal satu client**
(`list_true_positive_cve_ids()`; FP dinilai per baris client, bukan hanya `"default"`, diubah di PR #14) diberi
`cve_mentions` dan `possibly_exploited_wild`. Mention-nya ditulis ke `cve_newsletter_mentions` pada **satu** baris
tracker (client mana pun, urutan DB), dan tabel itu belum dibaca siapa pun.

## 8. Peta UI (`apps/web/src/app/(app)/cve/page.tsx`)

Dua view: **CVEs** dan **Package Vulnerabilities** (`pkgvuln/`, tidak dipelajari di sini). Di dalam CVEs ada
empat sub-view: **CVEs** (`cve-core-view`: filter bar, baris "Updated ... + Check for new CVEs" (`cve-check-new`:
waktu cek terakhir, tombol admin yang polling sampai cek selesai lalu melaporkan jumlah CVE baru), toolbar lookup KEV/EPSS/Exploit-DB + Export Excel,
list, `cve-detail-modal` dengan tab Ticket), **Dashboard** (`cve-dashboard-view`), **Ticketing**
(`cve-ticketing-view`), **Tech Stack** (`techstack-panel`: tambah, hapus, ubah exposure/hosting; input teks
"Tech name..." tanpa validasi). Browser tidak memanggil API langsung; lewat `/api/proxy/[...path]`.

## 9. Pencocok nama tech (tujuh, bukan enam)

`docs/CVE_TECH_MATCHING.md` 2.4 menyebut enam. Sebenarnya ada **tujuh**; yang ketujuh tidak tercatat dan
**tidak disentuh fase 1**:

| # | Tempat | Aturan di `main` |
|---|---|---|
| 1 | `new_cve._nvd_candidates` | NVD `keywordSearch` (pencari kandidat, bukan pencocok) |
| 2 | `new_cve._tenable_candidates` | kata per kata (`_mentions`) |
| 3 | `new_cve` gate (`relevant_techs`) | kata utuh + angka versi menempel |
| 4 | `score.py` `related_tech_status` | `\b{tech}\b` **tanpa `re.escape`** |
| 5 | `score.py` `check_tech_stack` | substring tanpa batas kata |
| 6 | `cve_priority.in_tech_stack` | substring dua arah |
| **7** | **`reports/cve_record.py::applicable_to_stack`** | **substring `re.escape(tech)` terhadap vendor, tanpa batas kata** (label "Might Applicable to Organization!") |

Branch `nameless/roadmap-runners` (belum di `main`) menyatukan 2-6 ke `cti_core.tech_match`; **#7 pengecualian
yang disengaja (keputusan user 2026-10-08)**: `test_cve_record.py` mengunci `c++` ~ `c++ inc`, yang bertentangan
dengan aturan "istilah < 2 karakter tak pernah cocok"; laporan Top CVE tidak ikut jalur katalog dan perilakunya
tidak diubah.

## 10. Hal yang harus dipertahankan saat mengubah desain (checklist invarian)

1. `cve_tracker.tech` adalah **teks yang cocok dengan `techstack_entries.name` huruf kecil**; `get_risk_context`,
   filter `tech`, `purge_orphaned`, dan dashboard bergantung padanya. Kalau katalog menggantikan nama, label
   tampilan harus tetap jadi `name` (atau join diganti sekaligus di semua tempat itu).
2. **Ticket dan FP berkunci `(cve_id, client_id)`, tidak ber-FK ke tracker**: aman dari cascade, tapi artinya
   kalau baris tracker dibuang (retensi, `purge-orphaned`) ticketnya yatim. Promosi ke `cve_tracker` harus
   menjaga baris yang punya ticket/ACK.
3. Satu baris tracker = **satu tech** per (CVE, client); `upsert` menimpa `tech` tiap run.
4. **Techstack kosong = tab CVEs tanpa filter tech** (tapi `purge_orphaned` menganggap semua yatim). **Diputuskan
   irisan 5**: tanpa entri sama sekali tetap tanpa filter (tidak ada perubahan perilaku); ada entri tapi semuanya
   nonaktif = kosong. Dikonfirmasi user 2026-10-08 (`docs/CVE_CATALOG_DESIGN.md` 9.5).
5. Enrichment sweep bekerja **lintas client** dan tanpa penyaring kesegaran; skala "selalu di-enrich" untuk
   banyak tech perlu `*_checked_at` sebagai penyaring.
6. `detected_on` diisi saat INSERT pertama; dasar KPI dashboard. CVE yang dipromosikan dari mirror harus
   menetapkan `detected_on` dengan sengaja (waktu ditemukan sistem, bukan tanggal publish) supaya MTTD tetap
   bermakna.
7. Notifikasi CVE baru bergantung pada **INSERT baris tracker** (bagian 7): jalur apa pun yang membuat baris
   (promosi dari mirror) harus lewat `upsert_with_status` + `finish_run`, bukan insert langsung.
8. Export, `/stats`, dan dashboard harus tetap memakai **scope yang sama** dengan tab CVEs.

## 11. Belum diverifikasi (jujur)

Tidak dibaca sampai tuntas: `pkgvuln` (view Package Vulnerabilities), isi `cve_export.py`, `cve_email.py`,
`campaign_analysis`/`crossref` (siapa yang benar-benar menulis `cve_threat_actors`/`cve_ttps` sekarang),
detail UI `cve-detail-modal`/`cve-ticket-tab`, `tools/seed/fase10_cve_migrate.py`, task `scrape.run`
(pemicu manual `POST /api/scraper/{id}/trigger`). Perilaku `new_cve` di produksi (berapa kandidat per run,
berapa yang lolos gate) hanya diketahui dari laporan `reconcile_cve_tech` 2026-10-07 di
`docs/CVE_TECH_MATCHING.md`.
