# Changelog

Format ngikutin [Keep a Changelog](https://keepachangelog.com/), versi
ngikutin `pyproject.toml` (root). Baca lewat `GET /api/changelog` (API,
router `changelog.py`) -- parser-nya expect header persis
`## [versi] - tanggal`, jangan ubah formatnya tanpa liat
`apps/api/src/cti_api/routers/changelog.py`.

## [Unreleased] - 2026-10-05

### Diubah
- **Rebranding**: nama tampilan platform jadi **Vareon Intelligence**
  (sebelumnya Niskala Intelligence) -- judul tab, login, logo header, judul
  API/OpenAPI, template email, dan README. Identifier teknis (`cti-platform`,
  `cti_*`, nama image/container) tidak ikut berubah.

### Ditambah
- **CVE Tracker > Ticketing**: sub-view baru buat daftar semua ticket
  (cari by ticket/CVE/asset/owner, filter Remediation Status), klik baris
  buka tab Ticket di modal CVE. Backend: `GET /api/cve/tickets`.

### Diperbaiki
- **Export CVE Excel** disamain sama format logbook: kolom A "No" nomor
  urut, CVE Reported Date + Date Acknowledged jadi `YYYY-MM-DD HH:MM:SS`
  (WIB, sebelumnya tanggal doang / ISO mentah), Reported Date ambil dari
  `detected_on` jadi gak kosong lagi, Affected Version fallback ke data
  CVE kalau ticket belum ada, baris diurut `detected_on` naik.

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
