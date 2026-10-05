# Progress Tracker — CTI Platform Revamp

Dokumen ini satu-satunya sumber kebenaran soal "udah sampai mana".
Update checkbox-nya tiap kali ada item selesai. Jangan tandai fase selesai
sebelum **semua exit criteria**-nya hijau.

**Legend:** `[ ]` belum · `[~]` jalan · `[x]` selesai · `[!]` keblokir

Plan lengkap: `~/.claude/plans/oke-bro-jadi-gini-sparkling-fern.md`

---

## Ringkasan

| # | Fase | Status | Perkiraan | Exit criteria |
|---|---|---|---|---|
| 0 | [Salvage & prep](phases/PHASE_0_SALVAGE.md) | `[~]` 0.2 & 0.5 gagal, ulangi | 3–5 hari | `static/` aman, crontab terekam, fixture terekam, secret dirotasi |
| 1 | Skeleton monorepo | `[~]` | 1 minggu | `uv sync` hijau, CI jalan |
| 2 | `cti-core` + skema Postgres | `[x]` | 2–3 minggu | Alembic up, repo + model ada test |
| 3 | Framework scraper | `[x]` | 2 minggu | 5 scraper referensi lolos golden test |
| 4 | Migrasi scraper (**100 aktif**) | `[x]` | ~2 minggu | ≥95% fixture identik, semua modul ke-import |
| 5 | `cti-enrich` | `[x]` | 2–3 minggu | Output cocok dgn baseline, tiap cabang routing ada test |
| 6 | Celery + beat | `[x]` inti; sisanya dipindah 7.8/10.1d/10.1e | 1–2 minggu | ~~5 loop web pindah~~ (→ 7.8) · ~~beat singleton terverifikasi~~ (→ 10.1d) |
| 7 | `apps/api` | `[x]` | 4–6 minggu | Semua endpoint ada snapshot test · 5 loop jadi beat task (7.8) |
| 8 | `apps/web` (Next.js) | `[x]` | 4–6 minggu | Semua tab lama ada padanannya |
| 9 | Control plane scraper | `[x]` | 1 minggu | Scraper mati kedeteksi dlm 3 interval |
| 10 | Cutover | `[~]` 10.A–10.E + 10.G + 10.G2 (nginx compose) (kode/dokumen/latihan staging) selesai; sisa 10.F + langkah operasional (butuh user/prod) | 1 minggu | Semua checklist cutover hijau |

> **Realistis: 4–6 bulan untuk satu developer.** Fase 0–4 udah ngasih nilai
> nyata (framework + scraper jalan) walaupun fase sesudahnya mundur.

---

## Fase 0 — Salvage & prep `[~]`

Runbook lengkap: **[phases/PHASE_0_SALVAGE.md](phases/PHASE_0_SALVAGE.md)**

Fase ini **blocking**. Big-bang tanpa baseline itu gak bisa diverifikasi.

> **Soal 3 hari perekaman:** yang ngeblok cuma **hari ke-1**. Format fixture
> nyimpen per tanggal dan digabung, jadi hari ke-2 dan ke-3 numpuk belakangan
> tanpa ngulang apa pun. Satu respons RSS juga udah berisi 10–20 item, jadi
> variasi bentuk item sebagian besar ketangkep di hari pertama — hari
> berikutnya nilainya buat bentuk yang jarang muncul.

> **Audit terakhir: 2026-09-16.** Dua item kelihatan selesai padahal **belum**
> — baca catatannya, jangan cuma lihat checkbox.

- [x] **0.1** Tarik `ScraperNewsWeb/static/` dari prod
      <br>**29 file (28 `.js`, 1 `.css`)** di `legacy/static/`. Sesuai harapan (~27).
      <br>**Sudah di-commit** (`641e6c1`). Gak lagi bergantung satu laptop.
- [x] **0.2** Rekam jadwal scraper
      <br>**Penjadwalnya Rundeck, bukan cron.** Itu sebabnya dump crontab kosong.
      <br>`rundeck_export_full.sh` udah jalan → `rundeck-jobs-full.json` +
      `rundeck-jobs-map.json`. **233 job, 100 aktif, 229 ada path script.**
      <br>Jadwalnya per-jam dengan menit distagger (`:15`, `:30`, `:31`, `:46`) —
      Rundeck udah ngelakuin *spread* yang direncanain di plan.
      <br>**96 dari 100 job aktif** kecocokan ke `ScraperNews/`: 91 langsung,
      4 lewat `python3 -m supportFile.X`, 2 beda penamaan
      (`threatactorTrendGraylog` vs `threatActorTrendGraylog`,
      `threatactorTrendTelegram` vs `threatActorTrendTele.py` — di Linux yang
      case-sensitive, dua job ini kemungkinan gagal diam-diam).
      <br>⚠️ Job `Offset Checker` manggil `supportFile.offsetAlert` yang
      **udah rusak** sejak dedup pindah ke Mongo — dijadwalin tapi sia-sia.
- [x] **0.3** Ambil `config/config.yml`
      <br>`legacy/config.yml` (2.911 byte). Mode file **644, harusnya 600**.
      <br>Ngungkap 2 hal baru: key **`devo:`** (SIEM, ada token — masuk daftar
      rotasi) dan referensi **`cve_db`**.
- [x] **0.4** `mongodump` + **tes restore**
      <br>**Restore terverifikasi** ke container lokal `cti-mongo-legacy`
      (`mongodb://localhost:27017`) pakai `tools/salvage/restore_local.sh`.
      <br>`news_db` 34 collection / 86.250 dok · `threatintel` 14 / 107.580 dok ·
      `test_backup` 4.354 dok · **`cve_db` 0 dok**.
      <br>Container ini dipertahankan: jadi sumber data asli buat rancang skema
      Postgres di Fase 2, tanpa perlu nyentuh produksi.
- [x] **0.5** Rekam fixture — **hari 1-2, ditutup**
      <br>Harness diperbaiki bertahap: guard interpreter, auto-stub `modules.*`,
      timeout adaptif, dependency ketinggalan (`yaml`/`pycountry`/`packaging`/
      `telegram`), config dummy otomatis buat 9 scraper yang buka
      `config/config.yml` langsung.
      <br>⚠️ **Ketemu risiko nyata waktu ngerjain ini**: `newCveThreat.py` +
      `githubPOCMonitor.py` bikin `MongoClient` langsung dari config (bisa
      nulis ke Mongo produksi), dan `threatActorTrendTele.py` punya token bot
      Telegram + Graylog **hardcoded di source** (bisa ngirim pesan asli).
      Ketiganya ditambal di level harness (`pymongo.MongoClient` +
      `telegram.Bot` dibikin inert, `threatActorTrendTele` diblokir permanen
      di `SKIP` — menang lawan `--only` eksplisit, udah diverifikasi paksa).
      Detail: [SECRETS_ROTATION.md](SECRETS_ROTATION.md#-bahaya-operasional-yang-ketemu-di-lapangan-bukan-cuma-di-git-history).
      <br>**Hasil final: 53 dari 96 job aktif (55%) punya baseline valid.**
      Di bawah target awal, tapi sesuai keputusan: **sisanya gak ngeblok** —
      masuk `verify` satu-per-satu pas Fase 4 (baseline direkam live saat itu,
      lihat [ADDING_A_SCRAPER.md](ADDING_A_SCRAPER.md)). Rincian lengkap:
      [KNOWN_BROKEN.md](KNOWN_BROKEN.md#hasil-final-perekaman-fase-05-2026-09-16--17).
      <br>9 di antaranya butuh **token API asli** (GitHub/NVD/Twitter) —
      **user bikin token baru pas mau testing scraper itu, bukan sekarang.**
- [x] **0.6-0.7** Hari ke-2/3 — **gak diperlukan lagi**
      <br>Target "3 hari" awalnya buat nangkep variasi bentuk item. Karena
      sisa yang belum ada baseline sekarang ditangani `verify` on-demand
      (bukan snapshot statis), gak ada nilai tambah nunggu hari ke-3.
- [x] **0.8** Arsitektur secret diputuskan + Vault masuk stack
      <br>**Keputusan final:** `.env` satu sumber terpusat sekarang, Vault
      dipakai beneran pas produksi. Bukan cuma dicatat — **sudah diverifikasi
      jalan**: `docker-compose.yml` punya service `vault` (profile opt-in),
      dites nyala → healthy → unseal otomatis → KV v2 aktif di `cti/` →
      tulis/baca sukses → dimatiin lagi (dev-mode, gak ada state yang perlu
      dipertahankan).
      <br>Yang **belum** dan sengaja ditunda ke fase testing: `cti_core`
      belum baca dari Vault (`SECRETS_BACKEND=env` masih satu-satunya jalur),
      dan token asli (11 item di [SECRETS_ROTATION.md](SECRETS_ROTATION.md))
      belum dirotasi — dirotasi sekali aja pas integrasi Vault beneran jalan.
      <br>⚠️ Rotasi tetap wajib **sebelum** repo lama di-import ke monorepo
      (Fase 1) — itu satu-satunya bagian yang gak bisa ditunda.
- [x] **0.9** Verifikasi `torch` / `bert-extractive-summarizer` gak kepake
      <br>**Terkonfirmasi nol importer.** Yang kepake cuma `sumy.LsaSummarizer`.
- [x] **0.10** Verifikasi cakupan bug regex `\b` di `nlp.py`
      <br>**Cuma L421 yang rusak** (raw string). L35/396/400/414 pakai f-string
      non-raw dan sudah benar — **jangan ikut diubah**.

Temuan dari uji coba harness → lihat [KNOWN_BROKEN.md](KNOWN_BROKEN.md)

**Exit criteria fase 0:**
- [x] `legacy/static/` ada, 28 file `.js`
- [x] `legacy/static/` ke-commit (29 file)
- [x] Penjadwal teridentifikasi: **Rundeck**, 233 job / 100 aktif
- [x] `rundeck-jobs-map.json` ada, 96/100 job aktif kecocokan eksak
- [x] `legacy/config.yml` ada di lokal, gak di-commit
- [x] Restore dump Mongo terverifikasi
- [x] Fixture: 53/96 (55%) baseline valid + jalur `verify`-menangkap-baseline
      buat sisanya — **gate dipenuhi lewat kombinasi, bukan angka tunggal**
- [x] Arsitektur secret diputuskan + Vault terverifikasi di stack
- [ ] 11 secret dirotasi, `gitleaks` bersih _(ditunda ke fase testing, disengaja)_

## Fase 1 — Skeleton monorepo `[~]`

- [x] **1.1** Struktur direktori `cti-platform/`
- [x] **1.2** `pyproject.toml` workspace root + 4 package member
- [x] **1.3** `.python-version` (3.12)
- [x] **1.4** `uv sync` berhasil, `uv.lock` ke-commit
      <br>4 package (`cti-core`, `cti-scraper`, `cti-enrich`, `cti-alerts`)
      resolve tanpa konflik. `apps/api`/`apps/worker` DIKELUARIN dari
      workspace members buat sementara -- direktori masih kosong, baru
      masuk lagi pas Fase 6/7 nulis kode beneran di sana.
      <br>Dikonfirmasi: **gak ada `pymongo`** di dependency tree manapun --
      konsisten sama keputusan pindah ke Postgres.
- [x] **1.5** `.gitignore` + `.env.example` (semua key, tanpa nilai)
- [x] **1.6** `git init` + commit pertama (`641e6c1`, 54 file)
- [x] **1.7** CI: ruff, mypy, pytest, gitleaks
      <br>`.github/workflows/ci.yml` (4 job) + `.gitleaks.toml`. **Keempat
      check dijalanin lokal dan dipastiin hijau sebelum di-commit** --
      bukan cuma ditulis, karena `tools/salvage/record_fixtures.py` yang
      ditulis lewat patch manual belum pernah lewat `ruff format`
      (3 lint error + 1 file gak ke-format, sekarang beres).
      <br>`mypy --strict` cuma di `cti-core`+`cti-scraper` sesuai plan §12 --
      `cti_scrapers/feeds/` hasil migrasi digate golden test (Fase 4), bukan mypy.
      <br>Ditambah 1 test nyata (`test_workspace_skeleton.py`): keempat
      package ke-import. Bukan placeholder buat nutup exit-code pytest --
      pytest exit 5 kalau 0 test, dan test ini genuinely berguna: kalau
      salah satu package berhenti bisa di-import, ketahuan di sini duluan.
- [~] **1.8** `docker-compose.yml` — **cukup buat Fase 1, belum final**
      <br>postgres + redis + vault (opt-in) pakai image resmi, gak butuh
      Dockerfile custom. Dites jalan (lihat commit `3829d5c`).
      <br>Belum ada, disengaja: Dockerfile + service `api`/`worker`/`web` --
      nunggu kode fase-nya masing-masing (2/6/7/8). Checklist ini ditutup
      total pas Fase 9 (`docker compose up -d` full stack).

**Exit criteria:** `uv sync` hijau · `pytest` jalan (boleh 0 test) · CI hijau

---

## Fase 2 — `cti-core` + skema Postgres `[x]` SELESAI

- [x] **2.1** `config.py` — pydantic-settings, `extra="forbid"`
      <br>Bug nyata ketemu+dibenerin: `extra="forbid"` gak nurun ke nested
      `BaseModel` (typo `TELEGRAM__BOTTOKEN` diam-diam ke-drop) — lihat
      `_StrictModel` di config.py dan `test_config.py`.
- [x] **2.2** `db/engine.py` — sesi async (asyncpg, FastAPI) + sync
      (psycopg3, Celery/CLI), satu model dipakai dua-duanya. Timestamp
      `ScraperRun` di-set eksplisit di Python, bukan `server_default` +
      implicit-reload — itu bakal meledak di jalur async.
- [x] **2.3** Model SQLAlchemy: `Article` + 4 tabel anak (countries+peran,
      industries, threat_actors, ttps). `confidence_score` SATU kolom,
      `overrides` (JSONB) buat koreksi analis yang gak boleh ketimpa scraper.
- [x] **2.4** Model: IOC (+sources/tags/threat_actors/feedback), CVE
      tracker (+references/affected/pocs/false_positives/tickets),
      ransomware victim, tweet + monitored_accounts, techstack, package
      vuln (+aliases/dep_edges). 35 tabel total.
- [x] **2.5** Model: user/role/client(+countries)/user_clients/audit_log.
      `client_id` jadi PRIMARY KEY string (natural key), bukan surrogate.
- [x] **2.6** Model: `ScraperRun` (heartbeat per-run — INI yang bikin
      nol-item vs crash bisa dibedain, gantiin `scraper_health.py` lama),
      `ScraperItem`, `ScraperConfig`, `ScraperSeen` (dedup two-phase,
      kolom `dedup_key` sengaja beda nama dari `Article.url_hash` — beda
      namespace, lihat docstring model).
- [x] **2.7** Alembic init + migrasi pertama — **diverifikasi ke Postgres
      beneran** (docker compose), bukan diasumsikan: `alembic upgrade head`
      sukses, 35 tabel kebentuk, `alembic downgrade base` bersih balik ke 0,
      `alembic upgrade head` lagi sukses, `alembic check` bilang "No new
      upgrade operations detected" (migrasi match persis model).
- [x] **2.8** Repository layer — `ArticleRepo`/`AsyncArticleRepo` (upsert
      dgn field mesin vs overrides, nolak nulis field identitas/typo),
      `IOCRepo`/`AsyncIOCRepo` (upsert+sources, feedback TP/FP),
      `ScraperRunRepo`/`AsyncScraperRunRepo` (heartbeat start/finish).
      Sisanya (CVE, tweet, dst) nyusul pas Fase 7 butuh.
- [x] **2.9** `urlkit.py` — `canonicalize_url()` + `url_hash()`. 75 test
      lolos (target ~60). Bug nyata ketemu+dibenerin: decode-lalu-encode
      path SEKALIGUS ketimbun `%2F` (slash sbg data) sama `/` (pemisah
      segment) — dibenerin proses per-segmen.
- [x] **2.10** `logging.py` — structlog JSON, gantiin `print()` polos.

**Exit criteria — SEMUA terverifikasi jalan, bukan diasumsikan:**
- [x] `alembic upgrade head` jalan di container Postgres kosong (35 tabel)
- [x] `alembic check` konfirmasi migrasi match persis model (0 diff)
- [x] `alembic downgrade base` → `upgrade head` lagi, reversibel penuh
- [x] Repo ada 96 unit+integration test, semua hijau (2x run, gak flaky)
- [x] `canonicalize_url` lolos 75 test (target ~60)
- [x] Integration test lawan Postgres BENERAN (testcontainers), bukan mock

**Bug test-isolation ketemu+dibenerin di jalan:** fixture integrasi yang
ngubah `os.environ` global (scope semula "session") bocor ke
`tests/unit/test_config.py` kalau `tests/integration/` kebetulan jalan
duluan (urutan alfabetis). Dibenerin: scope turun ke "package" + tambah
`__init__.py` di kedua folder test (syarat resmi pytest biar package-scope
fixture teardown bener kapan waktunya).

---

## Fase 3 — Framework scraper `[x]` SELESAI

- [x] **3.1** `items.py` — `ArticleItem`, `RansomwareVictimItem`, `CveItem`,
      `PackageVulnItem`. Sink cuma dipasang buat 2 pertama (sesuai
      kebutuhan 5 referensi); `CveItem`/`PackageVulnItem` nunggu Fase 4/7.
- [x] **3.2** `base.py` — `BaseScraper` + `ScraperMeta` + `ScrapeContext`.
      Lupa nulis `meta` di subclass = `ConfigError` di waktu IMPORT (fail
      loud), bukan diam-diam gak kedaftar.
- [x] **3.3** `registry.py` — auto-discovery via `__init_subclass__` +
      `pkgutil`. Modul yang gagal import GAGAL KERAS (fail loud) — ini yang
      nangkep kelas bug "lupa import lxml.html" di CI/boot, bukan diam-diam
      mati selamanya kayak sistem lama.
- [x] **3.4** `sinks.py` — dispatch berdasarkan TIPE item, bukan nama
      scraper. `RansomwareVictimItem` kebukti beneran lewatin pipeline
      artikel dan nulis langsung ke `ransomware_victims`.
- [x] **3.5** `dedup.py` + `cti_core.db.repositories.scraper_seen.py` —
      reserve/commit/release two-phase. Diverifikasi ke Postgres beneran:
      run pertama scraper live 15 item baru, run kedua 15 di-drop semua.
- [x] **3.6** `runner.py` — rate limit → fetch → dedup → sink → heartbeat.
- [x] **3.7** Family: `RSSScraper`, `XPathScraper` (runtime light+browser
      SATU class), `ApiScraper`.
- [x] **3.8** `spread()` — jitter deterministik. Diverifikasi: 142 scraper
      simulasi tersebar 5-13 per menit dari 15 slot (bukan numpuk di :00).
- [x] **3.9** CLI (`cti-scraper`) — `list`, `dry-run`, `run`, `verify`
      (+`--record` buat baseline baru), `enable`, `disable`. Semua
      diverifikasi jalan lawan Postgres+situs asli, bukan diasumsikan.
- [x] **3.10** 5 scraper referensi — **bukan "satu per family" tapi "satu
      per jalur kode berbeda"**, disengaja lebih luas dari 3 family:
      `bitdefender` (RSS), `cyfirma` (XPath light), `trendmicro` (XPath
      browser, Playwright+route-interception), `ransomware_live` (BaseScraper
      langsung, item bespoke), `cisa_kev` (BaseScraper langsung, ArticleItem
      tapi logic gak muat di ApiScraper.field_map). `ApiScraper` sendiri
      dipakai internal ketiganya lewat family class, diuji contract test.
- [x] **3.11** Harness golden test (`cti_scraper.testing`) — byte fixture
      Fase 0 disuntik lewat `httpx.MockTransport` (light) atau Playwright
      `page.route()` (browser, MockTransport gak ngaruh ke navigasi
      Playwright). Ketauan pas jalan, bukan ditebak: `RansomwareVictimItem`
      butuh normalisasi tanggal (fixture lama kadang nyimpen datetime
      penuh, item baru bertipe `date` bersih -- itu perbaikan, bukan bug).

**Exit criteria — SEMUA terverifikasi jalan lawan Postgres+jaringan asli:**
- [x] 5 scraper referensi lolos golden test lawan fixture Fase 0
- [x] Contract test jalan (31 test, semua scraper kedaftar otomatis dicek)
- [x] `dry-run bitdefender` narik 15 item beneran dari bitdefender.com asli
- [x] `run bitdefender` 2x: run-1 15 baru, run-2 15 di-drop (dedup nyata)
- [x] `enable`/`disable` nulis `scraper_config` beneran

**Bug nyata ketemu+dibenerin selagi jalan (bukan diasumsikan aman):**
1. `RansomwareVictimItem.dedup_key()` draft pertama 4 bagian, format asli 5
   bagian (`group:victim:country:industry:tanggal`) — ketauan dari golden
   test gagal, bukan review kode.
2. `ScraperRun.run_id` di Fase 2 `String(30)`, tapi `uuid.uuid4()` di
   runner.py ngasilin 36 karakter — `StringDataRightTruncation` pas run
   pertama BENERAN ke Postgres (bukan pas test unit, karena test unit gak
   nyentuh Postgres asli). Migrasi Fase 2 diregenerate ulang.

---

## Fase 4 — Migrasi scraper `[x]`

> **Scope dikoreksi dari temuan Rundeck:** yang dimigrasi **~91 scraper aktif**
> dulu, bukan 241. Sisanya masuk backlog terpisah, digarap setelah cutover.
> Ini motong Fase 4 dari 3–4 minggu jadi sekitar 2 minggu.

> **Pendekatan: satu per satu lewat jalur yang sama kayak nambah scraper baru**
> ([ADDING_A_SCRAPER.md](ADDING_A_SCRAPER.md)). Codemod bikin kandidatnya, tapi
> tiap scraper tetap lewat `dry-run` → `verify` → `enable` satu-satu.
>
> Alasannya bukan kehati-hatian, tapi supaya **kontraknya ke-uji**. Migrasi 91
> scraper = 91 kali nyoba alur "nambah scraper". Kalau ada langkah yang kerasa
> maksa di scraper ke-12, itu ketahuan pas masih murah dibenerin — bukan nanti
> pas orang lain nambah scraper ke-92.
>
> Aturannya: **kalau migrasi butuh akalan di file scraper, itu bug framework.**
> Benerin framework-nya, jangan diakalin per file.

- [x] **4.1** `tools/codemod/classify.py` — klasifikasi family via AST
      (import-based: selenium→SELENIUM, playwright→XPATH_BROWSER,
      defusedxml→RSS, requests+lxml→XPATH_STATIC, sisanya→BESPOKE)
- [x] **4.2** `tools/codemod/extract.py` — ekstraktor AST per family, gagal
      ke `needs_review` (bukan nebak) kalau kodenya nyimpang dari bentuk
      kanonik
- [x] **4.3** `tools/codemod/emit.py` + `templates/{rss,xpath}.py.jinja`
- [x] **4.4** `import_rundeck.py` — `rundeck-jobs-map.json` → `schedule` +
      `enabled` per scraper (bukan crontab; penjadwalnya Rundeck. Temuan:
      job Rundeck pakai menit TETAP per job, bukan pola `*/N`)
- [x] **4.5** Generate RSS — **37/47 (79%) otomatis**, +1 udah ada dari Fase 3
      (`bitdefender`) _(job aktif)_
- [x] **4.6** Generate XPath/Playwright — **20/23 (87%) otomatis**, +1 udah
      ada dari Fase 3 (`trendmicro`)
- [x] **4.7** Generate requests+lxml (`xpath_static`) — **checklist ini
      sempat basi**: dicek ulang lewat re-run `run_migration.py` (2026-09-18),
      classifier nemuin 3 stem `xpath_static` (`cyfirmaThreat`, `landthThreat`,
      `newCveThreat`), BUKAN 2 -- salah hitung sebelumnya. Auto-generate
      emang 0/3 (semuanya butuh `needs_review`: `landth.py` variabel loop
      non-standar, `newCveThreat.py` multi-source jadi keklasifikasi bespoke
      di praktiknya), tapi KETIGANYA udah ada file lengkap + terdaftar di
      registry: `cyfirma.py` (Fase 3), `landth.py` (ditulis manual ronde 2,
      lihat 4.11), `new_cve.py` (bespoke, item 4.9). Verifikasi ulang:
      `run_migration.py` regenerate laporan bersih (0 generate, 0
      needs_review, 83/83 target udah "skipped_existing"). Gak ada kerjaan
      nyata yang ketinggalan -- cuma checklist yang gak ke-update pas
      ketiga file itu kelar lewat jalur lain (bukan auto-generate).
- [x] **4.8** ~~Tulis ulang 8 Selenium → `XPathScraper(render=True)`~~ —
      **dipindah ke 10.1c** (2026-09-18, keputusan user, sama alasan 4.12):
      dicek dulu sebelum diputus pindah -- SEMUA 6 script Selenium real
      (`0xToxinThreat`, `emailnewsThreat`, `forcepointThreat`,
      `mandiantThreat`, `trellixThreat`, `vxMalwareDefenseThreat`) `enabled:
      false` di Rundeck, `cyborgHuntingIdea` malah gak kedaftar sama
      sekali. Nol fixture (perekaman Fase 0 cuma nyakup job aktif). Satu
      dicek langsung isinya (`stopped_script/mandiantThreat.py`) — 100%
      ke-comment, `CHROMEDRIVERLOC = "./chromedriver_mac64_arm64/chromedriver"`
      -- konfirmasi konkret gak pernah jalan di host Linux produksi, persis
      alasan yang plan sebutin. **Test-rewrite 1 (Mandiant) sebelum
      dipindah** — lihat 10.1c buat hasilnya: JAUH lebih gampang dari
      dugaan (situs asli udah pindah ke Google Cloud Blog + ada RSS resmi,
      bukan butuh browser automation sama sekali).
- [x] **4.9a** Buat token API baru (GitHub PAT, NVD, twitterapi.io) khusus
      buat testing scraper yang butuh kredensial asli — **user udah bikin +
      isi ke `.env`** (`GITHUB__TOKEN`/`NVD__API_KEY`/`TWITTER__API_KEY`,
      dikonfirmasi kebaca bener lewat `Settings`, gak pernah ditampilin di
      chat). Dipakai buat verifikasi live `blackorbird`/`unit42_github`/
      `new_cve`/`github_poc_monitor` (4.9) — token twitterapi.io masih
      nunggu `monitorX` gak lagi ke-block klarifikasi TwitterScrap.
      <br>⚠️ Jangan pakai token produksi lama yang di `legacy/config.yml` —
      itu masuk daftar rotasi karena udah ke-expose ke laptop dev.
- [x] **4.10** Triage `migration_report.json` — SELESAI setelah 3 ronde.
      Akhir: dari 96 job aktif mentah Rundeck, **13 di luar scope** (bukan
      scraper/repo lain/diblokir), **83 target migrasi**: 76 udah punya
      scraper (57 auto-generate + 13 tulisan tangan ronde 2 + 3 referensi
      Fase 3 + `ransomware_live`/`cisa_kev`/`sophos`, lihat di bawah), **7
      sisa** butuh porting bespoke penuh (4.9) — semua udah ditriage &
      dikategorikan, bukan cuma "belum sempat dicek".

      **Ronde ke-3** (nuntasin 4.10 — baca SEMUA 13 item `needs_review`
      yang tersisa dari ronde 2, bukan cuma yang gampang):

      - **Bug skip-check ketemu**: `run_migration.py` dulu cuma ngecek
        file udah ada di `feeds/` lewat nama hasil `legacy_stem_to_id()` --
        gak nangkep scraper bespoke Fase 3 yang nama file-nya gak ngikut
        konvensi itu. Akibatnya `ransomwareLiveThreat` (udah lengkap di
        `collectors/ransomware_live.py`) dan `cisacatalogThreat` (udah
        lengkap di `collectors/cisa_kev.py`) **nyangkut terus di
        "needs_review: bespoke" walau UDAH SELESAI dari Fase 3**. Fix:
        `_find_already_covered()` scan field `legacy_script="..."` di
        SEMUA scraper yang ada (`feeds/` + `collectors/`), bukan nebak
        nama file — bener buat family apa pun.
      - **`sophosThreat.py` — misklasifikasi ketauan & dibenerin**:
        classifier nge-tag "bespoke" gara-gara pakai `xmltodict.parse()`,
        padahal strukturnya KANONIK 100% (satu feed, loop item, gak ada
        filter). Ditulis manual ke `sophos.py` (declaratif murni, `RSSScraper`
        biasa) — golden-test match persis 4/4.
      - **5 item lagi ternyata BUKAN scraper** (pola sama kayak
        logbook/sendCounter/offsetAlert/trendingNewsToday/threatactorTrendGraylog
        yang ketauan ronde 2): `githubSophoslab`, `githubTTPs`,
        `mitreGithub`, `githubAptTTPSimulation` — "GitHub commit watcher"
        yang cuma poll `api.github.com/.../commits` terus alert Telegram
        (`send_alert_report`/`send_report_file`), **nol panggilan
        dbMongo/push_job di keempatnya** — gak pernah nulis apa pun ke DB,
        murni notifikasi sepihak. `topCve` malah gak fetch keluar sama
        sekali — baca `cve_tracker` LOKAL (hasil scraper lain), agregat,
        kirim digest Telegram. Dipindah ke `NOT_A_SCRAPER_STEMS`, keluar
        dari target migrasi (ranahnya Fase 6 beat task).
      - **7 sisa dikategorikan buat 4.9**:

        | Scraper | Kategori | Status |
        |---|---|---|
        | `anyrunTrendThreat` | Rusak, butuh keputusan produk | **SELESAI** → `any_run_trends.py`, fitur baru penuh (lihat 4.9) |
        | `blackorbirdGithub`, `githubUnit42` | GitHub commit-watcher yang NULIS artikel | **SELESAI** → `blackorbird.py`, `unit42_github.py` (lihat 4.9) |
        | `newCveThreat`, `githubPOCMonitor` | Subsistem CVE | **SELESAI** → `new_cve.py`, `github_poc_monitor.py` (lihat 4.9) |
        | `deepdarkCTI` | **PINDAH ke Fase 5** | Extract IOC dari diff commit GitHub (`fastfire/deepdarkCTI`) butuh `iocExtractor.extract_iocs()`-equivalent — itu SCOPE Fase 5 (`cti_enrich/ioc/`, item 5.9). Bukan lagi tugas Fase 4 — lihat Fase 5 buat detail |
        | `monitorX` | **PINDAH ke Fase 5** | Pertanyaan tabrakan sama `TwitterScrap` **udah terjawab TIDAK** (user tarik repo-nya, dibaca lengkap — lihat "Scope ditunda" di bawah), jadi bukan itu blocker-nya lagi. Blocker sebenarnya: `monitorX.py` manggil `articleValidator()` (LLM, filter cyber-relevance + extract field insiden `victim_name`/`confirmed_incident`/dst) — SCOPE Fase 5 (`cti_enrich/llm/`, item 5.10). Model `Tweet` (`cti_core/db/models/tweet.py`) juga ketauan belum lengkap — ada `confidence_score`/`confirmed_incident` tapi kolom LLM lain (`industries_impacted`, `victim_countries`, `actor_countries`, `victim_name`, `incident_confidence`, `incident_indicators`) belum ada. Bukan lagi tugas Fase 4 — lihat Fase 5 buat detail |
- [x] **4.9** Port manual scraper bespoke — **5 dari 5 target Fase 4 beres**
      (`blackorbird`, `unit42_github`, `new_cve`, `github_poc_monitor`,
      `any_run_trends`), + 2 udah dari Fase 3 (`ransomware_live`, `cisa_kev`).
      `deepdarkCTI` & `monitorX` **DIPINDAH ke Fase 5** (item 5.9/5.10 di
      bawah) -- keduanya genuinely butuh modul yang belum ada
      (`cti_enrich/ioc/`, `cti_enrich/llm/`), bukan kerjaan scraper lagi.
      Klarifikasi TwitterScrap (dulu dikira blocker `monitorX`) UDAH KELAR
      -- user tarik repo-nya, dibaca lengkap, TERNYATA BUKAN tabrakan
      (lihat "Scope ditunda" di bawah).

      **`any_run_trends.py`** (`anyrunTrendThreat` lama): satu-satunya
      scraper Fase 4 yang beneran FITUR BARU, bukan migrasi -- script lama
      gak pernah nulis apa pun (`featured_message` dihitung terus dibuang,
      fixture Fase 0 `expected_items.json` isinya `[]`, lihat KNOWN_BROKEN.md).
      Keputusan user: lanjutin jadi beneran. Baru dari nol: tabel
      `malware_trends` (migrasi `21d5ede00400`, diverifikasi upgrade/
      downgrade + `alembic check` bersih), `MalwareTrendRepo`,
      `MalwareTrendItem` + sink (upsert `(source, snapshot_date, rank)`,
      `dedup_key()` scraper di-override `None` -- pola sama kayak `CveItem`,
      posisi ranking bisa geser dalam hari yang sama antar-run). **Bug
      ketemu & dibenerin waktu tulis**: lupa prefix `xpath=` di
      `page.locator()` (beda dari family `XPathScraper` yang lewat lxml,
      ini manggil Playwright langsung) -- ketauan lewat `dry-run` pertama
      (`Locator.text_content: Unexpected token "/"`), langsung ketauan
      jelas. **Perbaikan lain**: href hasil scrape RELATIF
      (`/malware-trends/kali365/`) -- script lama gak masalah karena
      hasilnya emang gak pernah dipakai, sekarang beneran jadi link yang
      diklik orang, jadi digabung `urljoin` ke absolut. Diverifikasi live
      penuh: `dry-run` 10/10 item, `run` nulis ke Postgres, re-run
      ke-upsert di tempat yang sama (row count tetap 10, bukan dobel).

      **Framework baru** (dipicu kebutuhan nyata, bukan dibangun duluan):
      - **`ScraperMeta.credential`** + `cti_scraper.credentials` -- scraper
        yang butuh API key (GitHub/NVD/Twitter) declare nama kredensialnya,
        `Runner`/`verify --record` yang nyuntik header ke `ctx.http`
        SEBELUM `fetch()` dipanggil. `fetch()` gak pernah pegang token
        mentah -- persis nutup kelas bug yang didokumentasiin
        `ScrapeContext` (`newCveThreat.py`/`githubPOCMonitor.py` lama bikin
        `MongoClient` langsung dari config). Standarin GitHub ke
        `Authorization: Bearer` (script lama campur `token`/`Bearer`,
        GitHub nerima dua-duanya). **Bug lama ketauan**: NVD API key gak
        PERNAH kepake di `newCveThreat.py` (field ada di config, gak ada
        satu pun `apiKey` di request) -- sekarang beneran kepasang, rate
        limit naik dari 5 ke 50 req/30dtk.
      - **`ScraperMeta.reference_data`** + `cti_scraper.reference_data` --
        pola SIMETRIS buat data internal Postgres (techstack, CVE true-
        positive) yang beberapa scraper butuh baca tapi BUKAN sumber
        eksternal. `Runner` query DB SEBELUM `fetch()`, `fetch()` cuma
        baca `ctx.reference[nama]` (data biasa, list/dict) -- `Session`
        gak pernah nyampe ke `fetch()`. CLI `dry-run`/`verify --record`
        ikut dibenerin biar buka session read-only kalau scraper-nya
        declare `reference_data`.
      - **`CveTrackerRepo`** (`cti_core/db/repositories/cve.py`) + sink
        `CveItem`/`CvePocItem` baru di `sinks.py` -- satu-satunya jalur
        tulis `cve_tracker`, dipakai DUA scraper (`new_cve.py` upsert
        penuh, `github_poc_monitor.py` push POC) biar gak drift lagi kayak
        `newCveThreat.py`/`githubPOCMonitor.py`/`cve_service.py` lama.
      - **Migrasi skema baru** (`3f6cadc03383`): `cve_pocs.poc_type`
        ("poc"/"exploit") -- kolom ketinggalan pas `CvePoc` ditulis Fase 2,
        ditambah begitu `github_poc_monitor.py` beneran butuh. Diverifikasi
        upgrade/downgrade/upgrade + `alembic check` = 0 diff, sama standar
        kayak migrasi Fase 2.
      - **`CveItem.cve_modified_date`** ditambah ke Item (field DB-nya
        udah ada dari Fase 2, ketinggalan di draft Item Fase 3).

      **Verifikasi**: fixture Fase 0 gak kepake (golden-test harness belum
      dukung `reference_data`/multi-request berantai, lihat KNOWN_BROKEN.md)
      -- keempat scraper diverifikasi lewat `dry-run`/`run` LIVE lawan API
      asli + Postgres lokal beneran (docker-compose): `blackorbird`
      (`items_found=1`), `unit42_github` (`items_found=3`), `new_cve`
      (272 CVE ke-upsert, spot-check data lengkap & bener), `github_poc_monitor`
      (diverifikasi DUA jalur: 189 kandidat broad-search di-filter techstack
      dengan bener/ketolak semua pas techstack gak cocok, terus 10 POC
      ke-attach bener pas techstack DAN CVE tracked cocok -- `poc_available`
      jadi `True`, `poc_type` ke-klasifikasi bener). 497 test hijau, `ruff
      check .` + `mypy --strict` (scope `cti-core`+`cti-scraper`) bersih,
      9 integration test hijau lawan schema baru.

      **Temuan minor, gak di-fix (biaya > manfaat)**: `_cve_poc_sink` bisa
      no-op diam-diam kalau POC ketemu buat CVE yang gak ke-track sama
      sekali (`items_new` di `RunResult` tetep ke-hitung sukses walau
      `add_pocs()` gak nemu baris buat ditempelin) -- setara perilaku
      Fase-1 script lama (juga gak nulis DB buat CVE yang gak dikenal,
      cuma alert). Bakal makin jarang kejadian begitu Fase 10 seed
      techstack/CVE beneran, gak worth bangun mekanisme "sink partial-
      success reporting" buat satu edge case ini sekarang.
- [x] **4.11** Catat gesekan DX yang ketemu waktu migrasi → balik benerin
      framework. Ini output nyata dari pendekatan satu-per-satu. **3 bug
      framework ketemu & dibenerin** lewat verifikasi golden-test bulk atas
      57 hasil generate (bukan diakalin per file — sesuai aturan Fase 4):

      1. **`RSSScraper` gak nge-unescape HTML entity sebelum parse XML.**
         51 dari 52 scraper RSS lama yang punya rantai `.replace()` buat
         entity malformed JUGA bungkus hasilnya dengan
         `html_lib.unescape(...)` sebelum `ET.fromstring()` — tanpa langkah
         ini, entity numerik yang sebenarnya udah valid (mis. `&#038;`) kena
         double-escape sama `.replace("&","&amp;")` terus gak pernah
         ke-decode. Ketauan dari `anyrun` (title `ANY.RUN &#038; SentinelOne`
         harusnya `ANY.RUN & SentinelOne`). **Fix:** field baru
         `RSSScraper.html_unescape: ClassVar[bool]`, di-apply di
         `_parse_feed()` setelah `xml_fixups`, sebelum parse XML. Extractor
         deteksi pola ini otomatis (cek apakah argumen `ET.fromstring(...)`
         dibungkus `.unescape(...)`). Dampak: **5 scraper RSS lain ikut lolos
         golden-test** (darkreading, eclecticiq, embeeresearch, exploitdb,
         threatmon) yang sebelumnya keliatan gagal karena entity yang sama.
      2. **`XPathScraper.base_url` gak pernah kedeteksi otomatis.** Field-nya
         udah ada dari Fase 3 (`XPathScraper` udah punya `urljoin()` bawaan),
         tapi `extract_xpath()` gak punya logic buat nemuin pola umum di 28
         scraper lama: `"url": "https://situs.com" + article_url` di dalam
         dict literal (href dari DOM-nya relatif, di-absolut-kan manual).
         Ketauan dari `bizone` (URL ke-generate relatif
         `/eng/expertise/blog/...`, harusnya absolut
         `https://bi.zone/eng/expertise/blog/...`). **Fix:**
         `_find_base_url_concat()` di `extract.py`, nyari `ast.Dict` dengan
         key mengandung "url"/"link" yang value-nya `BinOp(Add, literal-http,
         ...)`. Verifikasi: `bizone` sekarang match persis (4/4).
      3. **BOM/CRLF sebelum deklarasi XML bikin parse gagal.** 28 scraper RSS
         lama defensif soal ini (`.decode("utf-8-sig")` dan/atau `.lstrip()`)
         karena deklarasi `<?xml ...?>` wajib jadi karakter pertama di
         dokumen. Ketauan dari `munit` (`ParseError: XML or text declaration
         not at start of entity` — fixture-nya diawali `\r\n` sebelum
         `<?xml`). **Fix:** `RSSScraper._parse_feed()` sekarang
         `resp.text.lstrip("﻿ \t\r\n")` sebelum parse — selalu aman
         (no-op buat feed yang udah rapi), jadi gak perlu deteksi per-scraper
         kayak dua bug di atas.

      **Divergensi yang KETAHUAN bukan bug** (dicatat di
      [KNOWN_BROKEN.md](KNOWN_BROKEN.md), jangan diakalin biar "lolos"
      golden-test byte-exact):

      | Scraper | Golden-test bulk | Kenapa bukan bug |
      |---|---|---|
      | `anyrun` | overlap URL 0% (title match sempurna) | Script lama double-concat `"https://any.run" + link` walau `<link>` RSS-nya udah absolut — bug lama, sengaja gak di-port |
      | `qualys`, `resecurity`, `rhinosec`, `cisa`, `wiz` | 1-4 item beda per title (selisih NBSP/spasi) | Script lama gak pernah `.strip()` title (`item.find('title').text` mentah) — framework baru SELALU strip, itu perbaikan disengaja |
      | `elastic_lab`, `eset`, `fortinet`, `starlabs`, `vectra`, `akamai`, `f5` | jumlah item ke-cap di `max_items` (default 50) | `ScraperMeta.max_items` itu cold-start guard yang disengaja (lihat §keputusan "Postgres + DB kosong") — bukan extraction gap. `akamai`/`f5` juga punya 1-2 item minor yang belum di-root-cause (bukan pola jelas kayak yang lain, dampaknya kecil) |
      | `artic` | overlap 10/20 (subset persis) | Limitasi golden-test harness (§4.11 di atas), bukan extraction gap — scraper punya 2 URL feed, harness cuma replay 1 fixture body |

      3 `ParseError` awal (checkpoint, cloudflare, munit) — **munit
      kebenerin** (BOM/CRLF, lihat di atas). `checkpoint` & `cloudflare`
      **bukan bug ekstraksi** — XPath/URL/`base_url`-nya struktural bener
      (disalin apa adanya dari locator Playwright lama yang jalan), tapi
      fixture Fase 0-nya nyimpen resource yang SALAH: `checkpointThreat`
      nyimpen halaman tantangan bot AWS WAF (2KB, cuma script
      `AwsWafIntegration.*`, bukan konten asli), `cloudflareThreat` nyimpen
      RSS feed blog Cloudflare (357KB `.xml`, `https://blog.cloudflare.com/`)
      yang gak ada hubungannya sama DOM `resource-hub` yang di-XPath. Kedua
      situs ini butuh rekam ULANG live pas `enable` (`verify --record`,
      ADDING_A_SCRAPER.md) — golden-test mock gak bisa "benerin" fixture yang
      dari awal salah rekam.

      20 scraper `xpath_browser` udah diverifikasi terpisah (subprocess
      per-scraper, hindarin noise event-loop Playwright kalau di-loop satu
      proses): **3 pass bersih** (`bizone`, `esentire`, `volexity`, +
      `trendmicro` dari Fase 3 = 4 total), 2 gagal karena fixture salah
      (checkpoint, cloudflare, di atas), **15 gak punya fixture sama sekali**
      — bukan bug, situs `runtime="browser"` emang paling banyak kena "0 item
      kedua hari perekaman" di Fase 0.5 (lihat KNOWN_BROKEN.md), tinggal
      `verify --record` pas giliran `enable`-nya.

      5 scraper RSS gak punya fixture sama sekali (doyensec, google,
      nquiring_minds, sysdig, trustwave) — bukan bug, tinggal
      `verify --record` pas giliran `enable`-nya (ADDING_A_SCRAPER.md).

      **Ronde ke-2** ("yang gampang dulu" — beresin `needs_review`,
      prioritas non-bespoke): 40 → **15** (13 bespoke + `newCveThreat`,
      salah-klasifikasi XPath padahal pipeline bespoke, + `anyrunTrendThreat`,
      butuh keputusan produk). 13 scraper baru (12 ditulis manual + 1
      ke-auto-generate lagi via fix extractor):

      - **Koreksi scope** (`run_migration.py`): 8 dari "100 job aktif" itu
        BUKAN target migrasi sama sekali, sebelumnya nyampur jadi
        "unresolved"/"bespoke" yang membingungkan. Sekarang eksplisit 3
        kategori (`NOT_A_SCRAPER_STEMS`, `EXTERNAL_REPO_STEMS`,
        `PERMANENTLY_BLOCKED`), laporan punya field `out_of_scope` sendiri:
        - `logbook`/`sendCounter`/`trendingNewsToday`/`threatactorTrendGraylog`
          — utility internal (laporan/counter/flush log ke Telegram/Graylog),
          BUKAN scraper (gak ada `push_job()`). Ranahnya Fase 6 (beat task).
        - `trendingCve`/`twitter`/`twitter30` — `/opt/TwitterScrap`, repo lain
          yang emang udah dicatat "Scope ditunda" (gak ada di checkout ini).
        - `techstackGO`/`techstackNPM`/`techstackPYPI` — **ketauan bahaya**:
          ada salinan lokal di `ScraperNews/` yang KEBETULAN ke-klasifikasi
          "bespoke", tapi salinan itu diduga FORK BASI (Rundeck nunjuk ke
          `/opt/techstackLibrary`, bukan `/opt/ScraperNews`, lihat "Scope
          ditunda" di atas). Auto-generate dari fork basi lebih bahaya
          daripada di-skip — sekarang dikeluarin eksplisit dari target.
        - `threatactorTrendTelegram` — nama job Rundeck beda ejaan dari file
          asli (`threatActorTrendTele.py`), yang UDAH `PERMANENTLY_BLOCKED`
          (kredensial hardcoded) — masuk situ, bukan entry baru.
      - **Framework** (`RSSScraper`): 2 tambahan generik, bukan per-file:
        - `_include_item(node) -> bool` — hook filter per-item SEBELUM
          di-parse (kategori/URL/tanggal), default semua lolos. Dipakai 6
          scraper (`akamai`, `bleepcomp`, `crowdstrike`, `f5`, `cisa`,
          `sentinel`) yang sebelumnya gak bisa diekspresiin murni
          deklaratif.
        - `escape_bare_ampersands()` (dulu langkah `BARE_AMPERSAND.sub()`
          polos) sekarang **CDATA-aware** — ngelewatin isi
          `<![CDATA[...]]>` utuh. **Bug asli ketemu**: `wiz.py` punya title
          CDATA berisi `"CVE-A & CVE-B"` (bare `&`, valid krn CDATA
          dikecualikan dari entity processing) yang kena escape jadi
          literal `&amp;` gara-gara regex whole-text yang gak ngerti
          batas CDATA — parser XML gak decode isi CDATA, jadi salah selamanya.
          Fix: split per-segmen CDATA, cuma escape bagian DI LUAR CDATA.
      - **Extractor** (`extract.py`): deteksi daftar URL feed sekarang dari
        ISI list (semua elemen literal `http...`), bukan nama variabel
        harus ngandung "url" — `articThreat.py` makai nama `link_list`,
        sebelumnya ke-skip padahal strukturnya kanonik. Auto-generate
        langsung jalan setelah fix ini (gak perlu ditulis manual).
      - **3 scraper "kelihatan ngasih banyak item" tapi ternyata rusak**
        (ditemuin pas migrasi, dicatat di KNOWN_BROKEN.md):
        - `huntressThreat.py` — `exit()` sebelum loop `push_job()`, dead
          code SELAMANYA. Logic ekstraksinya valid → **diselamatkan**
          manual ke `huntress.py` (CSS class diterjemahin ke XPath
          `contains()`), bug `exit()`-nya sengaja gak ikut.
        - `socradarThreat.py` — loop `range(1,5)` tapi XPath-nya gak pernah
          pakai `{i}`, jadi SELALU cuma 1 item/run (dedup dalam-run
          nyaring 3 iterasi sisanya). Diport manual ke `socradar.py` dengan
          `max_items=1` — golden-test match persis 1/1.
        - `anyrunTrendThreat.py` — ngumpulin ringkasan trend tapi **gak
          pernah manggil `push_job()` sama sekali**, dari awal incomplete.
          Fixture Fase 0 ngonfirmasi (`expected_items.json` isinya `[]`).
          **Sengaja gak di-port** — butuh keputusan produk (Item type baru
          buat ringkasan, bukan per-artikel), bukan ekstraksi mekanis.
      - **`sentinelThreat.py` — kuirk filter kategori yang SENGAJA
        dipertahankan** (bukan bug ekstraksi, bukan bug yang harus
        dibuang): `skip_status` cuma di-set di dalam `for cat in
        item.findall('category')`, jadi item TANPA `<category>` sama
        sekali otomatis LOLOS filter (loop-nya gak pernah jalan). Beda dari
        `bleepcomp.py`/`crowdstrike.py` yang bentuknya mirip tapi
        default-nya "exclude". Diverifikasi lewat fixture (item "Agents at
        Large..." gak punya category tapi tetap di expected) sebelum
        direplikasi — golden-test match persis 1/1.
      - **`landth.py`** — satu-satunya kasus yang extractor SENGAJA gak
        digeneralisasi: variabel loop-nya (`recent_count`) sinkron 1:1 sama
        `range(1,4)`, tapi ngenalin ITU secara umum (bukan cuma nama `i`)
        beresikonya lebih besar daripada nulis manual satu file. Ditulis
        manual, perilakunya diverifikasi identik.
      - **`rapid7.py`, `cisa.py`** — butuh override method penuh (bukan
        cuma field deklaratif): rapid7 parsernya beda (`lxml.etree
        recover=True`, `resolve_entities=False`/`no_network=True` buat
        nutup XXE manual karena gak lewat `defusedxml`), cisa punya
        sanitasi byte custom (`remove_invalid_xml_bytes`, filter range byte
        valid, beda dari `xml_fixups` yang cuma string replace). Keduanya
        tetap subclass `RSSScraper`/`BaseScraper` satu file, cuma override
        method yang emang perlu.
      - **`cybersecnews.py`** — kebutuhannya BERTENTANGAN sama urutan
        default framework: butuh `html.unescape()` SEBELUM smart-escape
        (bukan sesudah) biar entity HTML bernama (`&nbsp;`/`&mdash;`, ada
        beneran di feed-nya, diverifikasi lewat fixture) ke-decode bener.
        Sempat dicoba jadiin urutan DEFAULT baru di `RSSScraper`, tapi itu
        bikin REGRESI di `embeeresearch.py` (interaksi sama `xml_fixups`
        yang nyentuh CDATA) — direvert, `cybersecnews.py` override
        `_parse_feed()` sendiri buat urutan yang beda ini secara lokal.
      - **`artic.py`** (auto-generate) — golden-test "gagal" (10/20) itu
        **limitasi test harness**, bukan bug: scraper ini punya 2 URL feed
        beda, tapi `cti_scraper.testing._build_http_transport()` cuma
        rekam/replay SATU response buat scraper apa pun URL-nya diminta —
        request ke feed ke-2 kebagian byte feed ke-1 lagi. `feeds` tuple
        hasil ekstraksi udah dicek bener secara struktural. Perlu
        peningkatan harness (per-URL fixture) buat multi-feed scraper,
        belum digarap — dicatat di KNOWN_BROKEN.md.
- [x] **4.12** ~~Backlog: job nonaktif~~ — **dipindah ke 10.1b** (2026-09-18,
      keputusan user): ini kerjaan cutover, bukan migrasi scraper aktif,
      jadi gak lagi nge-blok status Fase 4.

**Exit criteria:** 241 modul ke-import semua · contract test hijau · ≥95% fixture identik · sisa delta ada waiver tertulis

---

## Fase 5 — `cti-enrich` `[x]`

- [x] **5.1** Stage `fetch_text` (`stages/fetch_text.py`) — trafilatura (HTTP
      langsung) + fallback Playwright-render lalu trafilatura lagi. GANTI
      `sumy.HtmlParser`-buat-ekstraksi + `newspaper3k` lama jadi SATU library
      dua jalur (keduanya udah scaffold Fase 1). Live-verified thehackernews.com.
- [x] **5.2** Stage `classify` (`stages/classify.py`) — prompt disalin
      verbatim, **fix**: `response_format={"type":"json_object"}` +
      `llm.client.parse_json_response()` gantiin `.replace("json","")` hack
      (`articleValidator.py:141-146`). Live-verified via gateway 9router
      (model reasoning yang balikin `<think>` block -- `parse_json_response`
      nyaring itu juga, ketauan pas testing live, bukan ditebak).
      **3 bug robustness lagi ketemu+dibenerin pas korpus test 200-artikel
      (2026-09-18)** -- ketiganya spesifik ke gateway dev (9router, model
      reasoning), gak ada di source lama karena OpenAI asli gak butuh:
      1. Gak ada `max_tokens` eksplisit -- server motong respons DI TENGAH
         blok `<think>`, JSON jawaban gak pernah lahir. `finish_reason`
         konfirmasi "length" bukan "stop". Fix: `_MAX_TOKENS=3000`
         (classify)/`2000` (extract_ttps, sama risiko).
      2. Respons kosong/rusak transien (~15-20% dari sampel awal, ilang
         total setelah fix #1+#3, sisa 0/30 di re-test) -- fix: 1 retry
         (`_MAX_ATTEMPTS=2`) di `classify()`/`extract_ttps()`, sama
         semangat retry `TransientFetchError` di scraper framework.
      3. Gateway kadang balikin `content` UDAH KE-PARSE (dict), bukan
         string JSON, di mode `response_format=json_object` -- bukan
         bagian spec OpenAI, quirk proxy. `parse_json_response()` sekarang
         terima `str | dict | None`, dict di-passthrough langsung.
- [x] **5.3** Stage `summarize` (`stages/summarize.py`) — sumy LSA,
      `PlaintextParser` gantiin `HtmlParser` (ekstraksi udah pindah ke 5.1).
      Butuh corpus NLTK `punkt_tab` -- auto-download sekali per proses
      (`_ensure_nltk_data()`), gak perlu langkah manual terpisah.
- [x] **5.4** Stage `extract_ttps` (port apa adanya, udah bener dari
      sononya), `extract_iocs` (`stages/extract_iocs.py`, TTL cache
      allowlist/C2 dipertahankan), `extract_cves` (regex title/body)
- [x] **5.5** Stage `score` (`stages/score.py`) — keyword list + regex +
      spaCy NER title/body, `checkCVE`/`checkTechStack` (HTTP MITRE) port ke
      `_check_cve_vendor`. **Perubahan disengaja**: `country_list` dari
      `pycountry` (seluruh ISO 3166-1) gantiin ~150 nama kuratif Mongo
      `apac-country`/`global-country` yang gak pernah ke-port ke Postgres --
      lihat docstring modul buat alasan lengkap (juga nyelesain kebutuhan
      konversi nama->kode `ArticleCountry.country_code`).
- [x] **5.6** `routing.py` — **fungsi murni**, 17 test (`tests/unit/
      test_routing.py`), 1-per-cabang + kasus tepi (double alert OT,
      sub-routing Indonesia, `related_tech_cve_status` cuma valid di cabang
      Global). **Fix**: zero-day regex `nlp.py:421` (`r"\\b...\\b"` raw-string
      jadi literal backslash, gak pernah match) -- versi bener
      `r"\b(zero|0)[-.]day\b"` dipakai di `stages/score.py`.
- [x] **5.7** Stage `persist` (`stages/persist.py`) — **satu-satunya
      penulis**, `ArticleRepo.set_enrichment()` (baru, Fase 5) buat
      countries/industries/threat_actors/ttps + `IOCRepo` per-IOC. Country
      role (victim/actor/mentioned) di-derive dari 3 field lama, lihat
      docstring modul.
- [x] **5.8** Stage `alert` (`stages/alert.py`) — **terpisah total** dari
      persist, `pipeline.py` manggil persist DULU baru alert (kebalik dari
      `_sendAlert()` lama yang gabung keduanya).
- [x] **5.9** SATU IOC extractor (`cti_enrich/ioc/extractor.py`) — port
      byte-identik, diverifikasi lawan korpus REAL (bukan cuma sintetis):
      **0 mismatch di 7899 title + 55 body artikel asli** (live-fetched)
      lawan `iocExtractor.py` asli. Unit test resmi ditambahin
      (`tests/unit/test_ioc_extractor.py`, 12 test).
      **BUG SERIUS ketemu+dibenerin (2026-09-18, korpus test 200-artikel)**:
      `_RE_DOMAIN_DEFANGED` -- ReDoS/catastrophic backtracking. Artikel real
      (elastic.co/security-labs/.../operation-bleeding-bear, ~12KB prosa
      natural) bikin `extract_iocs()` GANTUNG TANPA BATAS (proses dibunuh
      manual setelah >5 menit, CPU 98%). Root cause: `(?:...)* ` gak
      dibatasi + `\s*` di dua sisi tiap repetisi -- prosa Inggris biasa
      ("kata. kata. kata.") ambigu banget buat regex ini walau HASIL AKHIRNYA
      gak pernah match. **Bug ini ADA di `iocExtractor.py` asli juga** (regex
      sama persis, byte-identik) -- bukan sesuatu yang ke-introduce port ini,
      TAPI kelas bug DoS/availability, beda dari "logic beda" yang wajib
      dipertahankan verbatim, jadi diputuskan dibenerin: `(?:...)*` ->
      `(?:...){0,10}` (gak ada domain defanged asli >10 label). Diverifikasi
      ULANG abis fix: 0 mismatch tetap di korpus 7899 title + 55 body yang
      sama, PLUS test regresi ReDoS baru (`test_domain_defanged_regex_does_
      not_catastrophically_backtrack`, timeout keras 5 detik pakai
      `signal.alarm`) biar gak bisa balik diam-diam.
      Butuh tabel baru `ioc_allowlist_entries`/`threat_feed_entries`
      (migrasi `5b7fe9a443b8`, verified upgrade/check/downgrade/upgrade) --
      dua-duanya KOSONG, belum di-seed (lihat "Belum dikerjain" di bawah).
      **`deepdark_cti.py` scraper SEKARANG UDAH DITULIS** (`scrapers/src/
      cti_scrapers/feeds/deepdark_cti.py`) -- `IocFeedItem` baru (SATU per
      commit, bukan per-IOC) + sink `_ioc_feed_sink` (upsert IOC + dual-write
      `threat_feed_entries` kalau kategori "c2" + alert Telegram "darkweb").
      Live-verified: `dry-run` + `run` jalan bersih lawan GitHub API asli,
      registry discovery + 539 test + mypy --strict + ruff semua bersih.
      **TEMUAN + FIX**: `_IOC_PATH_PREFIXES` asli (`c2/`, `ioc/`, dst,
      asumsi struktur folder) gak PERNAH match repo `fastfire/deepdarkCTI`
      SAAT INI -- dikonfirmasi lewat GitHub Contents API, repo-nya sekarang
      flat (`phishing.md`, `ransomware_gang.md`, dst di root). Bukan bug
      portingan (logic identik source asli), assumption source asli soal
      struktur repo yang udah basi. **Keputusan user**: sesuaikan ke skema
      flat -- `_category_for()` sekarang cocokin KATA di nama file (dipisah
      `_`/`-`) lawan 6 kategori asli, bukan folder prefix. Live-verified
      IOC beneran ke-extract & tersimpan dari commit real (`.onion` URL dari
      `ransomware_gang.md`, kategori "ransomware").
- [x] **5.10** SATU LLM client (`cti_enrich/llm/client.py`) — port + fix
      nyata: fork `ScraperNewsWeb` gak pasang `timeout`/`max_retries` sama
      sekali (dikonfirmasi baca langsung file-nya), fork `ScraperNews` yang
      dipertahankan. **Tambahan gak ada di source manapun**: `LlmSettings.url`
      buat gateway custom (9router, dev), karena provider="openai" gak lagi
      selalu berarti api.openai.com asli. **`monitor_x.py` scraper SEKARANG
      UDAH DITULIS** (`scrapers/src/cti_scrapers/feeds/monitor_x.py`) --
      `TweetItem` baru + sink `_tweet_sink` (insert-only, `TweetRepo`).
      Migrasi kolom `Tweet` (`industries_impacted`, `victim_countries`,
      `actor_countries`, `victim_name`, `incident_confidence`,
      `incident_indicators`) selesai (`a6f893e1319d`, verified roundtrip).
      Reuse `cti_enrich.stages.score.score_with_lists()` (title-pass doang,
      `_scan_tweet` lama emang gak ada NER) dan `classify()` langsung --
      refactor `score.py` jadi `score()` (wrapper Session) +
      `score_with_lists()` (murni) biar scraper (`fetch()` gak boleh pegang
      Session) bisa reuse logic yang sama tanpa DB access langsung. Dua
      resolver `reference_data` baru: `monitored_accounts`,
      `tweet_last_seen_ids` (gantiin `state.json` lokal, MAX tweet_id per
      akun dari Postgres). **Live-verified logic penuh** (scan+classify+
      persist, pakai tweet sintetis -- hasil match GPT: victim=Philippines,
      actor=China, mentioned_group=[APT41]) TAPI **panggilan API
      twitterapi.io beneran ke-block**: `TWITTER__API_KEY` di `.env` balikin
      `401 Unauthorized {"error":"Invalid API key"}` pas dites lawan endpoint
      asli. **Bug asli ketemu+diperbaiki dalam proses ini**: draft pertama
      `_fetch_tweets_for_account` gak cek `resp.status_code` (kode lama PUNYA
      cek ini, `monitorX.py:280-281`, sempat kelewat pas port) -- tanpa cek,
      respons error 401 ke-`.get("tweets", [])` jadi `[]` diam-diam, keliatan
      kayak "gak ada tweet baru" padahal auth-nya gagal. Udah diperbaiki:
      sekarang log warning eksplisit tiap status non-200.
- [x] **5.11** SATU `send_alert(topic, msg)` (`cti_alerts/telegram.py`) —
      12 topic (bukan 9 placeholder awal, lihat `.env.example`), termasuk
      sub-routing global/apac/apac_indo/apt/data_breach_indo yang di kode
      lama implisit di `_send_alert()`. Live-verified kirim ke bot Telegram
      dev user. **Beda dari kode lama**: gak nelan exception (`except:
      pass`) -- aman karena persist selalu duluan (lihat 5.8).
- [x] **5.12** Fix regex zero-day `nlp.py:421` — lihat 5.6.

**Pipeline penuh** (`cti_enrich/pipeline.py`, `run_pipeline()`) live-verified
3 jalur: `related_cyber=False` (reject dini), `security_tech_best_practice=True`
(short-circuit, skip extract_ttps+score), dan jalur penuh (classify->fetch_text
->summarize->extract_ttps->score->routing->persist->alert) — ketiganya nulis
ke Postgres lokal + kirim completion beneran ke LLM gateway dev + Telegram.
539 test lulus (`pytest tests/`, termasuk contract test yang otomatis nyakup
`deepdark_cti`/`monitor_x` dari registry), `mypy --strict` bersih 73 file,
`ruff` bersih.

**2026-09-18 update:**
- **`TWITTER__API_KEY` diganti user -- WORKS.** Live-verified lawan
  twitterapi.io asli (200, tweet beneran balik). `monitor_x.py` sekarang
  end-to-end teruji, bukan cuma logic-nya doang.
- **Seed data KELAR** -- `tools/seed/fase5_reference_data.py` (baru, baca
  BSON pakai `pymongo` ad-hoc lewat `uv run --with pymongo`, SENGAJA gak
  masuk dependency package manapun karena ini script sekali-pakai/migrasi).
  Sumbernya, dikonfirmasi langsung (catatan lama soal lokasi file KELIRU --
  `apac-people.bson` ada di `threatintel/`, bukan `news_db/`):
  - `legacy/dump/threatintel/groups.bson` -> **3991** `threat_actor_groups` (malpedia)
  - `legacy/dump/threatintel/apac-people.bson` -> **30** `monitored_people`
    (isinya demonym/nasionalitas -- "Afghan", "Australian", dst -- BUKAN
    nama orang walau nama koleksinya "apac-people")
  - `legacy/dump/news_db/ioc_allowlist.bson` -> **9** `ioc_allowlist_entries`

  Idempoten (upsert by unique constraint), diverifikasi re-run kedua = 0
  baris baru. Live-verified `score()` (`"Lazarus Group"` -> match, `"Afghan"`
  -> match) dan `extract_iocs()` (`wiz.io` ke-filter allowlist bener).
- `update_cve_mention` (tracking mention CVE/bulan) gak diport -- itu makan
  buat `cveEmailAutomation` (laporan mingguan CVE), yang di-scope keluar
  Fase 5 (territory Fase 7/apps-api, sama kayak `GRAPH__*` credential).
- **Exit criteria "200 artikel historis" -- KELAR.** `tools/` scratch
  script (bukan dikomit, sekali-pakai) jalanin stage individual
  (`classify->fetch_text->summarize->extract_ttps->score->routing`, TANPA
  `persist()`/`route_alerts()` biar gak nulis 200 baris test/kirim 200
  alert Telegram beneran) atas 200 artikel real dari
  `legacy/dump/news_db/articles.bson`, dibandingin lawan `news_type` yang
  kesimpen dulu. Angka final (200 artikel, SEMUA lewat kode final --
  gabungan 2 batch: 30 artikel `docs[100:130]` + 170 artikel
  `docs[130:300]`, non-overlap, ronde awal yang kepake kode SEBELUM 4 fix
  di bawah SENGAJA gak dihitung biar angkanya jujur ngukur kode final):
  - **Error rate: 13/200 (6.5%)** -- SEMUANYA gagal parsing/timeout LLM
    (gateway dev 9router, bukan pipeline logic) setelah 3x retry, bukan
    crash/bug. Turun jauh dari ~15-20% di percobaan awal (lihat 4 fix di
    5.2/5.9), tapi gak bisa dikejar ke nol -- itu batas reliability
    gateway LLM dev yang dipakai, dilaporkan apa adanya.
  - **Acceptance rate (`related_cyber=True`): 193/200 (96.5%)**
  - **`news_type` exact match vs hasil lama (dari yang accepted): 106/193
    (55%)** -- ANGKA INI SECARA JUJUR gak bisa 100%: (1) LLM beda (gateway
    dev 9router, bukan GPT-4o asli yang kemungkinan dipakai produksi dulu),
    (2) teks body di-fetch LIVE SEKARANG, bisa beda dari yang di-fetch
    dulu (halaman berubah/link rot), (3) **`techstack` BELUM di-seed**
    (Fase 10 scope, lihat 10.1) -- `related_tech_status` SELALU `False`
    buat sekarang, jadi cabang "Tech Stack Article"/"Unrelated Tech Stack
    Article" sistematis gak pernah kepilih walau title/body-nya cocok;
    pola ini keliatan jelas di data (banyak `old=Tech Stack Article`/
    `Unrelated Tech Stack Article` -> `new=global`). Bukan bug routing,
    konsekuensi LANGSUNG dari gap seed data yang udah dicatat.
  - **IOC extractor byte-identik: 0 mismatch di 7899 title + 51-55 body
    artikel real** (dua kali verifikasi, sebelum & sesudah fix ReDoS) --
    lihat detail lengkap di 5.9, jauh ngelewatin syarat "korpus 500 artikel".

> **Disiplin:** port logika apa adanya. Perbaiki **hanya** bug yang sudah
> disebut. Kalau enrichment dan scraping berubah semantik barengan, diff
> verifikasi jadi gak bisa dibaca.

---

## Fase 6 — Celery + beat `[x]` inti kelar, sisanya dipindah ke 7.8/10.1d/10.1e

**2026-09-18 — "inti" Fase 6 (arahan: mulai dari core dulu, 5 loop web
nyusul belakangan).** Dibangun di `apps/worker` (package baru `cti-worker`,
masuk uv workspace) + `cti_core.celery_client` (producer-side, biar
`cti_scraper.sinks` -- sebuah package -- gak perlu depend ke `apps/worker`
-- sebuah app):

- [x] **6.1** `apps/worker/src/cti_worker/celery_app.py` -- app Celery
      SATU, dua "image" (scrape vs enrich) dibedain lewat `-Q` + extra
      `nlp` yang ke-install/nggak, bukan app terpisah. `task_acks_late=True`
      + `broker_transport_options={"visibility_timeout": 3600}` ditambahin
      belakangan (exit criteria 6.1 minta ini eksplisit) -- ack cuma
      setelah task selesai (worker mati di tengah run gak bikin task hilang
      diam-diam), visibility_timeout 3600s jauh di atas task terlama yang
      keukur LIVE (`enrich.article` ~10-13s, `scrape.run` ~1-2s).
- [x] **6.2** Queue: `scrape.rss` / `scrape.api` / `scrape.browser` /
      `enrich` (nama beda dari draft plan `scrape.light`/`io`/`control` --
      dipetakan ke family scraper riil yang udah ada dari Fase 3/4, bukan
      istilah generik yang gak ke-pakai). `notify`/`maintenance` didefinisiin
      di `queues.py` tapi belum ada consumer -- placeholder buat 6.6.
- [x] **6.3** `apps/worker/src/cti_worker/queues.py::queue_for()` --
      baca `ScraperMeta.runtime` ("browser" → `scrape.browser`) +
      `credential` (`is not None` → `scrape.api`, else `scrape.rss`).
      Dipakai beat (opsi per-entry) DAN bakal dipakai trigger manual Fase 9.
- [x] **6.4** `apps/worker/src/cti_worker/beat.py::build_beat_schedule()`
      -- generate dari `cti_scraper.registry.discover()`, `ScraperMeta.schedule`
      (cron 5-field) → `celery.schedules.crontab`. **Verified LIVE**: build
      berhasil buat SEMUA scraper aktif riil di registry, gak ada yang gagal
      parse. Nemu 1 bug nyata pas verifikasi: `crontab()` Celery nolak
      sintaks cron valid `"0/N"` (cuma terima `*/N`) -- scraper `eset`
      (jadwal dipulihin dari Rundeck Fase 4) pakai `"0 0/1 * * *"`. Fix:
      `_normalize_field()` regex `0/N` → `*/N` (aman, N=0 = minimum field
      manapun); `N/M` non-zero SENGAJA dibiarin apa adanya, gak ada kasus
      itu di scraper aktif sekarang.
- [x] **6.5** Token bucket Redis (`TokenBucket`, dibangun Fase 3, belum
      pernah disambung ke Redis client beneran) sekarang disambung
      `redis.Redis.from_url(settings.redis.url)` di `tasks/scrape.py`.
- [x] **6.6** ~~Pindahkan 5 loop web → beat task~~ -- **dipindah ke 7.8**,
      biar progress rapih. Alasan sama kayak 6.7/6.8 di bawah: loop-loop itu
      (PIR alert, ATT&CK sync, IOC decay, daily recap, CVE enrichment)
      logikanya nempel di service `ScraperNewsWeb/app/services/*` yang
      MEMANG bakal di-port ke Postgres bareng 56 service lain di Fase 7 --
      misah-misahin kerjaan cuma bikin dobel, digabung natural pas Fase 7
      jalan (bukan item Fase 6 yang genuinely selesai).
- [x] **6.7** ~~Lock singleton (cegah beat double-fire)~~ -- **dipindah ke
      10.1d**. Soft-depend, bukan blocker teknis (infra Redis+Celery udah
      lengkap, lock bisa dibangun kapan aja) -- cuma gak ada gunanya diuji
      sekarang, baru 1 proses beat lokal yang jalan. Nyambung langsung ke
      checklist cutover "Beat terverifikasi singleton" di bawah.
- [x] **6.8** ~~Guard backpressure antrian `enrich`~~ -- **dipindah ke
      10.1e**. Sama, soft-depend: nyambung ke pemisahan image `worker-nlp`
      (Fase 9/10, concurrency dibatasi RAM spaCy/sumy) yang diprediksi
      baru beneran bikin antrian numpuk -- belum ada indikasi nyata sekarang.

**Task lain:**
- `apps/worker/src/cti_worker/tasks/scrape.py::run_scraper` (`scrape.run`)
  -- eksekusi `Runner` (Fase 3), `result.status in ("fetch_error",
  "rate_limited")` → raise `_RetryableRunError` biar `autoretry_for` Celery
  yang urus backoff (`Runner` sendiri SENGAJA gak retry, lihat docstring
  `runner.py`). `max_retries=3`, `retry_backoff=True`.
- `apps/worker/src/cti_worker/tasks/enrich.py::enrich_article` (`enrich.article`,
  `queue="enrich"`) -- panggil `cti_enrich.pipeline.run_pipeline()` (Fase 5)
  lewat import LAZY (worker scrape-only, image tanpa extra `nlp`, tetep
  bisa start & register nama task ini walau manggil beneran bakal
  `ImportError` -- `-Q` yang jamin worker itu gak pernah di-assign task
  ini, plan §4). Retry cuma buat `json.JSONDecodeError` residual yang lolos
  dari retry internal `classify()`/`extract_ttps()` (Fase 5, ~6.5% residual
  korpus test) -- `max_retries=2`. `OpenAIQuotaExhausted` SENGAJA gak
  di-retry (kuota abis butuh tindakan manusia, retry cuma nge-spam queue).
- `packages/cti-scraper/src/cti_scraper/sinks.py::_article_sink` -- ganti
  dari nulis `ArticleRepo` LANGSUNG (Fase 3) jadi `send_task("enrich.article",
  ...)`. Tulis-DB-nya sekarang di dalam task `enrich.article` (lewat
  `run_pipeline` → `persist.py`), bukan di sink lagi -- kontrak tipe yang
  masuk sink (`ArticleItem`) gak berubah, cuma titik tulisnya pindah dari
  SINKRON ke ASINKRON.
- `packages/cti-core/src/cti_core/celery_client.py::get_celery_client()`
  -- Celery client MINIMAL (cuma tau broker URL, `send_task` by string
  name) buat dipanggil dari `cti_scraper.sinks` TANPA `cti_scraper` (sebuah
  package) depend ke `apps/worker` (sebuah app) -- dependency inversion,
  producer gak perlu tau implementasi task, cuma nama + kwargs-nya.

**Verifikasi LIVE end-to-end (2026-09-18), bukan cuma unit test:**
1. `uv run celery -A cti_worker.celery_app worker -Q scrape.rss,scrape.api,scrape.browser,enrich --pool=solo` --
   start bersih, register `scrape.run` + `enrich.article`, beat schedule
   ke-build buat semua scraper aktif riil.
   (Catatan dev macOS: `--pool=solo` wajib lokal -- default prefork
   nge-crash `ValueError: not enough values to unpack` karena spawn-based
   multiprocessing macOS gak cocok sama asumsi prefork Celery; BUKAN
   masalah produksi karena Docker/Linux pakai `fork`.)
2. Dispatch manual `scrape.run("mandiant")` (scraper hasil rewrite 4.8) 2x
   -- run pertama `items_new=0` (dedup bener-bener kerja, semua 20 item
   udah `scraper_seen` dari testing sesi sebelumnya); abis `scraper_seen`
   di-clear buat scraper ini, run kedua `items_new=20`.
3. Ke-20 item nge-trigger `send_task("enrich.article", ...)` dari
   `_article_sink` -- worker yang SAMA (consume `enrich` juga) nangkep,
   jalanin `run_pipeline()` penuh (fetch_text → classify LLM → summarize →
   extract_ttps → extract_iocs → score → persist → route_alerts) buat
   tiap artikel, termasuk kirim alert Telegram beneran buat yang lolos
   filter.
4. Query Postgres `SELECT ... WHERE source ILIKE '%mandiant%' ORDER BY
   created_at DESC` -- **20 baris Article baru** ke-persist, `news_type`
   ke-klasifikasi (`global`, `apac`, `Zero Day Article`,
   `Security Technology & Best Practices`, sebagian `None` = ditolak
   klasifikasi -- konsisten sama rate penolakan yang udah didokumentasiin
   Fase 5).
5. Full suite abis semua perubahan: `pytest tests/ -q` → **556 passed**,
   `ruff check .` → clean, `mypy apps/worker + celery_client.py + sinks.py`
   → clean (0 issues, 9 source file).

**Bug ketemu pas kerjain ini:**
- `pytest tests/` sempat KEBACA hang abis `_article_sink` diubah --
  root cause BUKAN kode baru, tapi `.env` punya `REDIS__URL=redis://redis:6379/0`
  (hostname Docker-network, gak resolve dari host) dan `get_celery_client().send_task()`
  block nunggu retry koneksi. Fix: export `REDIS__URL=redis://localhost:6379/0`
  buat run host-side (pola sama kayak override `DATABASE__URL`/`DATABASE__SYNC_URL`
  yang udah dipakai sepanjang sesi). Abis di-override, 556 test lulus ~16s --
  suite lama emang gak nge-exercise real dispatch path dengan cara yang
  kebuka sama perubahan ini.
- mypy `untyped-decorator` di `@app.task(...)` -- stub Celery gak preserve
  signature fungsi yang di-decorate. Inline `# type: ignore[misc]` gak
  stabil posisinya buat decorator multi-baris (kadang "unused-ignore",
  kadang "invalid syntax"). Fix proper: `[[tool.mypy.overrides]]` scoped
  ke `cti_worker.tasks.scrape` + `cti_worker.tasks.enrich` doang di root
  `pyproject.toml`, bukan disable strict buat seluruh `apps/worker`.

**Exit criteria (draft plan):** 5 loop web hilang dari `main.py` · uvicorn
jalan multi-worker · beat singleton terverifikasi (restart, cek gak
double-fire) -- ketiganya dipindah jadi exit criteria fase lain (5 loop →
**7.8**, beat singleton → **10.1d**, lihat 6.6/6.7 di atas) karena
nunggu kondisi yang belum ada di deployment lokal sekarang (`apps/api`
buat 5 loop, deployment multi-node buat beat singleton). Yang UDAH
terverifikasi LIVE di Fase 6 sendiri: rantai penuh scrape → sink → enrich
queue → enrich task → persist jalan tanpa satu pun langkah disintesis/di-mock.

---

## Fase 7 — `apps/api` `[x]`

**2026-09-18 — 7.1 + 7.2 (auth vertical slice), diverifikasi LIVE lewat
HTTP beneran (curl), bukan cuma pytest.** Package baru `apps/api`
(`cti-api`), masuk uv workspace. OIDC (bagian dari 7.2) **belum** diport --
`oidc.enabled=False` default (Fase 2), toggle-nya nunggu giliran; auth
lokal (username+password, JWT) yang jadi fokus "inti" duluan.

**cti-core (shared, dipakai `apps/api`):**
- `db/models/auth.py` -- tambah kolom yang kepake legacy tapi belum ada di
  skema Fase 2 (ketauan pas porting beneran, bukan dugaan): `Role.display_name`/
  `created_by`/`created_at`/`updated_at` (sekarang `TimestampMixin`),
  `AuditLogEntry.target_id`, model baru `PasswordPolicy` (singleton row
  `id=1`, kolom eksplisit -- bentuknya tetap/gak cair, beda kasus dari
  JSONB `detail`). Migrasi `5a456e9251a0`.
- `db/repositories/auth.py` -- `AsyncUserRepo`/`AsyncRoleRepo`/
  `AsyncClientRepo`/`AsyncAuditLogRepo`/`AsyncPasswordPolicyRepo`. Async-only
  (bukan dual sync+async) -- satu-satunya konsumer `apps/api`, gak ada
  Celery/CLI yang nyentuh tabel ini (pola sama kayak `CveTrackerRepo`/
  `TweetRepo`, sync-only karena konsumen tunggal arah kebalikannya).

**apps/api (`cti_api`) -- port dari `ScraperNewsWeb/app/{auth.py,
services/{auth,role,client,audit,policy,rate_limit}_service.py,
routers/auth.py, models/auth.py}`:**
- `main.py` -- `create_app()` factory, lifespan (`ensure_default_client` +
  `ensure_system_roles`, idempoten tiap startup), CORS. **TANPA** 5
  background loop (`_pir_alert_loop` dkk -- itu **7.8**) dan **TANPA**
  Jinja2/StaticFiles (frontend server-rendered lama diganti Next.js
  terpisah Fase 8, `apps/api` murni JSON API).
- `security.py` -- hash password (bcrypt) + JWT encode/decode, baca
  `cti_core.config.Settings.auth` (bukan `os.getenv()` manual + `RuntimeError`
  kayak `main.py` lama -- container udah gagal start duluan lewat Pydantic
  kalau `JWT_SECRET`/`SESSION_SECRET_KEY` kosong, Fase 2).
- `rate_limit.py` -- **BUKAN port langsung** dari `rate_limit_service.py`
  lama (dict in-memory per-proses). Sengaja diganti ke Redis fixed-window
  (`INCR`+`EXPIRE`): goal eksplisit plan §4/§7 "API bisa di-scale horizontal"
  -- limiter in-memory salah per-proses begitu >1 worker uvicorn (limit
  efektif N kali lipat, silent). Redis udah infra baku platform ini.
- `deps.py` -- `get_current_user`/`require_auth`/`require_admin`/
  `require_superadmin`/`effective_client_id` (port 1:1 `app/auth.py`), plus
  `get_db`/`get_redis` (keduanya `@lru_cache`/lazy -- BUKAN singleton
  modul-level yang konek pas import, biar gampang di-override test/beda env).
- `services/roles.py` -- 26 permission (`ALL_PERMISSIONS`) + 3 role sistem
  (`SYSTEM_ROLES`) + `ensure_system_roles()`. `services/policy.py` --
  validasi kompleksitas password.
- `routers/auth.py` -- 13 endpoint (`policy` get/put, `login`, `logout`,
  `change-password`, `init`, `me`, `users` get/post, `reset-password`,
  `clients` put, `role` put, `audit-log`). Alur/aturan bisnis dipertahankan
  APA ADANYA (termasuk satu kemungkinan bug legacy yang SENGAJA gak
  "diperbaiki" diam-diam: `flag_force_pw_change_all_non_admin` cuma
  exclude role=="admin", "superadmin" ikut ke-flag -- didokumentasiin di
  docstring repo, bukan didaftar sebagai bug resmi kayak §7 plan).
- `routers/health.py` -- `GET /healthz`.

**Verifikasi LIVE (2026-09-18), curl asli lawan uvicorn + Postgres + Redis
lokal:** `/healthz` · `/api/auth/policy` get/put (min_length berubah,
persist) · `/api/auth/init` (bootstrap superadmin, 409 kalau user udah
ada) · `/api/auth/login` (benar/salah password, cookie `cti_auth` keset) ·
`/api/auth/me` · RBAC (401 tanpa token, 403 non-admin ke endpoint admin) ·
`/api/auth/users` create/list · `/api/auth/users/{u}/role` put · rate
limit login (429 persis di request ke-11 per IP, window 60s) · audit log
kecatat benar (`create_user`/`login` dengan `target_id`) · `change-password`
+ login ulang pakai password baru · `/api/auth/users/{u}/clients` put.

**Bug ketemu pas kerjain ini:**
- `AsyncUserRepo.update_client_ids` -- `session.delete()` pada child
  (`UserClient`) gak otomatis nyabut dia dari koleksi `user.clients` yang
  UDAH ke-load di memori (beda dari `parent.children.remove(child)`).
  Tanpa expire, caller yang baca `user.clients` di sesi yang sama abis ini
  masih liat client_ids LAMA walau row DB udah bener. Ketauan dari test
  integrasi (bukan dugaan), fix: `session.expire(user, ["clients"])`
  abis flush. Re-verified via HTTP live (`PUT /users/{u}/clients` + `GET
  /users`) setelah fix.
- **Gap infra test, bukan bug kode**: `pytest.ini_options` (`asyncio_mode
  = "auto"`) default scope event loop pytest-asyncio itu "function" (loop
  BARU tiap test) -- `cti_core.db.engine.get_async_engine()` di-`@lru_cache`
  SEKALI per proses (disengaja, Fase 2: satu connection pool). Begitu ada
  LEBIH DARI SATU test async dalam satu run (sebelumnya cuma 1 di seluruh
  suite, `test_async_article_repo_upsert_works` -- gak pernah kebuka),
  connection asyncpg dari test pertama bawa referensi ke event loop yang
  udah ditutup test-runner, `RuntimeError: Event loop is closed` pas
  teardown test kedua dst. Fix: `asyncio_default_fixture_loop_scope` +
  `asyncio_default_test_loop_scope = "session"` di root `pyproject.toml`
  -- satu event loop buat seluruh sesi pytest, cocok sama engine yang
  di-cache proses-wide. Regresi-tested: full suite (596 test, unit+integration+contract)
  lulus abis perubahan ini.
- Skema Fase 2 (`db/models/auth.py`) kurang lengkap buat kebutuhan nyata
  router: `Role` gak ada `display_name`/`created_by`/timestamp,
  `AuditLogEntry` gak ada `target_id`, `PasswordPolicy` belum ada model
  sama sekali. Ketauan pas porting router lama beneran butuh field-field
  itu -- migrasi `5a456e9251a0` nambahin, bukan didesain ulang skemanya.

**Test:** `tests/unit/test_auth_security.py` (7 test -- hash/verify
password, JWT roundtrip, token ditolak kalau di-tamper/salah secret),
`tests/unit/test_password_policy.py` (9 test -- tiap aturan kompleksitas +
hint), `tests/integration/test_auth_repositories.py` (24 test, Postgres
REAL via testcontainers -- kelima repo). Full suite abis semua ini: **596
passed**, `ruff check .` bersih, `mypy` bersih buat semua modul yang
disentuh (`apps/api` + `db/repositories/auth.py` + `db/models/auth.py`).

**Belum dikerjain (masih `[ ]`):** OIDC/SSO (`services/oidc_service.py`,
184 baris, nunggu `oidc.enabled=True` beneran dipakai), 7.3 (27 router
lain), 7.4 (56 service lain, termasuk logika 7.8), 7.5 (buang duplikasi
pkg_vuln/cve_email/ioc/llm -- versi kanonik IOC+LLM udah disatukan Fase 5,
tinggal pkg_vuln+cve_email), 7.6 (snapshot test), 7.7 (ekspor OpenAPI), 7.8.
~~Catatan ini soal IOC+LLM ternyata JADI STALE lagi begitu `apps/api` lahir
(Fase 7.3) -- exit criteria "gak ada import `cti_enrich` dari API" bikin
`llm` harus di-duplikat ULANG buat `apps/api`. `ioc` kena masalah sama tapi
udah dibenerin Fase 7.3 Bagian 4; `llm` nyusul dibenerin Fase 7.5
(2026-09-23), lihat catatan lengkap di bawah.~~

- [x] **7.1** ~~Bootstrap FastAPI (tanpa background loop)~~ -- `apps/api`
      + `main.py` (`create_app()`, lifespan, CORS), lihat catatan di atas.
- [x] **7.2** Auth: JWT + RBAC + multi-tenant -- lihat catatan di atas.
      **OIDC bagian dari 7.2 ini BELUM diport** (`oidc.enabled=False`
      default, 184 baris `oidc_service.py` nunggu giliran terpisah, bukan
      bagian "inti").
- [x] **7.3** Port 27 router ke repository Postgres -- **SELESAI** (5/5
      Bagian survei 2026-09-18 kelar). `ScraperNewsWeb/app/routers/`
      isinya 28 file: `auth` (Fase 7.2, udah kelar duluan), `oidc`
      (`oidc.enabled=False` default, sengaja ditunda, lihat catatan
      7.2), `scraper_health` (diganti control plane, Fase 9, beda fase)
      -- sisa **25 router**, SEMUANYA ketutup lintas 6 sebelum survei +
      Bagian 1-5 (rincian tiap bagian di bawah). "27" di estimasi awal
      survei sedikit meleset (25 aktual), bukan ada router yang
      kelewat -- daftar file di atas cross-check lengkap.
      (`clients`, `roles`, `articles` [baca doang], `iocs` [baca+kurasi],
      `techstack` [CRUD inti], `cve` [baca+false-positive+purge],
      `tweets`, `monitored_accounts`, `ransomware`, `changelog`,
      `filtered_articles`, `rfi`, `pir`, `source_reliability`, `attack`,
      `ta_groups`, `mitre`, `crossref`), verified LIVE via curl
      (create/update/delete, RBAC superadmin-only buat mutasi, 422
      permission gak dikenal, 400 hapus role sistem/client default).
      `clients`/`roles` nyaris gratis: repo-nya (`AsyncClientRepo`/
      `AsyncRoleRepo`) udah lengkap dari 7.2.

      **`articles`** (2026-09-18) -- router paling besar/penting, cuma
      permukaan BACA (`GET /api/articles` list+filter+paginate, `GET
      /api/filters`, `GET /api/articles/{id}`). `AsyncArticleRepo` (Fase 2)
      sebelumnya cuma punya `upsert`/`get_by_url(_hash)`/`set_overrides` --
      ditambah `list_filtered()` (translate query dict Mongo lama ke SQL
      join atas tabel anak ternormalisasi: `article_industries`/
      `article_countries`[+role]/`article_threat_actors`) dan
      `get_filter_options()` (distinct value per tabel, ganti `col.distinct()`
      Mongo). Tiga field negara Mongo lama (`mentioned_countries`/
      `victim_countries`/`actor_countries`, tiga array terpisah) sekarang
      SATU tabel `article_countries` + kolom `role` -- `country` (param
      umum) = role `"mentioned"`, cocok 1:1 sama nama field lama.
      **Sengaja di-skip/ditunda** (didokumentasiin di docstring router,
      bukan didiemin): `/api/dashboard` (agregasi berat + `normalize_country()`
      lama -- SEKARANG kejadian di enrichment `cti_enrich.countries`,
      bukan query-time), `/api/articles/dedup-groups` (butuh scikit-learn,
      belum dependency `cti-api`), `/api/articles/{id}/confidence`
      +`/confidence/recompute` (butuh router `source_reliability` ke-port
      duluan), `/api/articles/backfill-iocs` (hack migrasi era Mongo,
      kemungkinan besar OBSOLETE -- `persist.py` Fase 5 udah nulis IOC
      lewat jalur normal), `/api/country-groups` (peta nama->varian buat
      data FREE-TEXT lama; skema baru `country_code` udah ISO alpha-2 dari
      enrichment, gak ada lagi varian nama yang perlu di-grup di layer API).

      **Bug nyata ketemu lewat test integrasi** (bukan dugaan):
      `AsyncArticleRepo.set_enrichment` (baru, port dari versi sync buat
      dipakai test) `MissingGreenlet` -- ganti koleksi relationship
      (`article.countries = [...]`) di sesi ASYNC butuh state koleksi LAMA
      buat ngitung diff cascade delete-orphan, itu lazy-load implisit yang
      gak jalan sinkron di luar `await` (versi sync `ArticleRepo` gak kena
      ini). Fix: `await session.refresh(article, attribute_names=[...])`
      eksplisit sebelum assign ulang.

      **`iocs`** (2026-09-18) -- permukaan BACA + kurasi manual (tag/TA/
      feedback/allowlist), **BUKAN** jalur tulis IOC baru: `upsert_ioc`/
      `persist_iocs_from_extraction` (`ioc_service.py` lama) SENGAJA gak
      diport -- itu udah digantikan `IOCRepo.upsert()` (Fase 5, dipanggil
      `cti_enrich.stages.persist` via Celery task `enrich.article`,
      live-verified Fase 6). `AsyncIOCRepo` (Fase 2, sebelumnya cuma
      `upsert`/`get`/`add_feedback`) ditambah `list_filtered`/`get_stats`/
      `add_tags`/`add_threat_actors`/`remove_threat_actor`/`delete`/
      `bulk_delete`. `ioc_allowlist_entries` (Fase 5, tabel dibaca doang
      buat `extract_iocs` -- sekarang jalur TULIS-nya juga ada,
      `AsyncIocAllowlistRepo` baru) ketahuan kurang kolom `added_by`
      (dipakai router lama buat audit trail) -- migrasi `9faf52bcc2a1`
      nambahin (`server_default='system'` buat 9 baris seed Fase 5 yang
      udah ada, dicabut lagi abis backfill).

      **Sengaja di-skip/ditunda**: `_sweep_delete_matching()` (legacy:
      nambah allowlist entry retroaktif nge-hapus baris IOC lama yang
      cocok) -- filtering IOC udah kejadian di EXTRACTION time sekarang
      (`extract_iocs.py`, cache TTL 300s), entry baru otomatis efektif
      buat artikel BARU; bersihin baris LAMA yang kepalang ke-extract itu
      fitur admin terpisah, bukan bagian inti nambah allowlist entry.
      `GET /fp-analytics`+`/apply-suggestions` (butuh `fp_analytics_service`,
      statistik berat), `GET /ta-links/{type}/{value}` (butuh router
      `ta_groups`/`attack` ke-port duluan), `decay_sweep()` (item **7.8**,
      salah satu dari 5 loop Celery beat), recompute confidence/actionability
      pas feedback (`confidence_service`, ditunda bareng `articles`).

      **Bug proaktif dicegah** (pola sama kayak `update_client_ids` Fase
      7.2 dan `set_enrichment` di atas): `remove_threat_actor` pakai
      `.remove()` dari koleksi `ioc.threat_actors` (cascade delete-orphan
      yang urus DELETE pas flush), BUKAN `session.delete()` langsung ke
      child -- ditulis dari awal biar gak kena staleness in-memory
      collection, bukan ketauan lewat test gagal kayak kasus sebelumnya.
      Diverifikasi eksplisit test integrasi: `ioc.threat_actors` di objek
      yang sama langsung ke-update tanpa fetch ulang.

      Verified LIVE via curl: list/filter/stats/detail (dengan sources),
      tag/threat-actor add+remove, feedback (tp_count nambah), allowlist
      add (idempoten by type+value)/list/delete (404 kalau gak ada),
      delete single + bulk (count akurat), RBAC 401/403 (termasuk
      ketauan satu user test dari sesi sebelumnya udah ke-promote admin --
      bukan bug, state nyata dari testing Fase 7.2 yang persist).

      **`techstack`** (2026-09-18) -- **prasyarat buat `cve.py`**, sengaja
      dikerjain SEBELUM CVE (bukan gantian urutan tanpa alasan): `cve_service.
      get_cves()` legacy nyari active tech stack + `get_tech_risk_context()`
      buat `adjusted_risk_score` (exposure/hosting multiplier) di HAMPIR
      SETIAP fungsi -- gak mungkin diport bermakna tanpa `AsyncTechStackRepo`
      ada duluan. `TechStackEntry` (Fase 2) udah dibaca `cti_scraper.
      reference_data`/`cti_enrich.stages.score` (pola "web kurasi, scraper
      patuh" yang UDAH live sejak Fase 3/4/5) -- router ini yang jadi jalur
      admin ngisi/ubah datanya, `AsyncTechStackRepo` baru (belum ada
      sebelumnya, cuma dibaca lewat query ad-hoc di enrichment).

      **Sengaja di-skip/ditunda ke `cve.py`** (bukan tanggung jawab
      `techstack_entries` sendiri, semua NULIS ke `cve_tracker`):
      `POST /backfill-cves` (copy CVE existing dari client lain),
      `POST /{id}/backfill-historical` (trigger fetch 180 hari NVD+detail
      MITRE per-CVE -- `httpx` ke API eksternal, belum ada di dependency
      `cti-api`), cascade-delete CVE pas tech dihapus (`delete_techstack`
      lama nge-hapus `cve_tracker`/`cve_false_positives`/`cve_tickets`
      terkait -- di sini `DELETE /{id}` MURNI hapus baris techstack).
      `_client_filter` fallback OR Mongo lama (`client_id=="default"` ATAU
      field gak ada) juga di-skip -- `client_id` NOT NULL di skema Postgres
      sejak awal, kasus "field gak ada" gak mungkin kejadian.

      Verified LIVE via curl: list (data seed lama "WordPress"/"Linux"
      ke-detect), tambah tech + duplikat case-insensitive ditolak, patch
      exposure/hosting (404 kalau value gak valid ATAU tech beda client),
      search filter, delete + delete-lagi (idempoten, `success:false`),
      401 tanpa token. 11 test integrasi baru (termasuk isolasi per-client:
      nama sama di dua client beda-beda baris, update tech client lain
      ditolak).

      **`cve`** (2026-09-18) -- permukaan BACA + false-positive + purge
      orphaned. `CveTracker`/`CveFalsePositive` (Fase 2) udah lengkap,
      cuma kurang layer BACA (`AsyncCveTrackerRepo`/
      `AsyncCveFalsePositiveRepo` baru) -- jalur TULIS CVE baru TETAP
      `CveTrackerRepo` sync yang udah ada (Celery task, Fase 4), gak
      disentuh. `adjusted_risk_score`/`tech_exposure`/`hosting_type`
      lewat `AsyncTechStackRepo.get_risk_context()` (**inilah kenapa
      `techstack` dikerjain duluan** -- kebukti kepetakan bener pas live
      test, satu entri Linux `exposure=public`/`hosting=saas` ngubah
      `adjusted_risk_score`-nya).

      **Sengaja di-skip/ditunda** (masing-masing alasan beda, didokumentasiin
      di docstring router): `GET /export` (Excel, `openpyxl` belum
      dependency), `POST /draft-email` (email/Graph), `POST /cisa-lookup`+
      `/epss-lookup`+`/exploit-lookup` (API eksternal CISA/FIRST.org/
      exploit-db), `GET /{id}/mindmap` (`mermaid_service`), `GET /prioritize`
      (konsep "campaign" belum ada modelnya). **`ticket`/`acknowledge`
      (termasuk `ack_filter`) SENGAJA ditunda karena alasan DESAIN, bukan
      cuma "belum sempat"**: `CveTicket` Pydantic lama itu record
      remediation KAYA per-CVE (14+ field -- affected_asset, owner_email,
      remediation_status, dst), sedang model Postgres `CveTicket`/
      `CveTicketItem` (Fase 2) didesain buat konsep BEDA (satu ticket_id +
      status, bisa nyakup banyak cve_id, gak ada kolom `client_id`/
      `acknowledged_by` sama sekali) -- butuh keputusan desain sendiri
      soal bentuk final tabelnya, bukan sekadar nambah kolom kayak
      gap-gap sebelumnya.

      **Insiden kecil pas kerjain ini**: nulis file repo baru pakai
      `cat > ...` (bukan Edit/append) TIMPA `CveTrackerRepo` (sync) yang
      udah ada dari Fase 4 -- ketauan LANGSUNG dari `mypy` full-repo
      (`cti_scraper.sinks` gagal import). Dipulihin dari `git show
      HEAD:...` + digabung manual sama kelas baru, di-reverifikasi mypy
      211 file bersih + full suite + live curl ulang abis fix. Pelajaran:
      file yang udah ada isinya HARUS di-Edit/append, bukan di-overwrite
      `cat >`, walau niatnya nambah bukan ganti.

      Verified LIVE via curl: list/stats/tech-list (dengan data real 4
      CVE termasuk yang ada POC dari github_poc_monitor), false-positive
      mark/unmark/bulk (exclude dari list default, `include_fp=true`
      nampilin lagi), filter tech/severity/search, purge-orphaned dry-run
      (0 delete karena tech aktif cocok techstack). 22 test integrasi baru
      (Postgres real, termasuk isolasi per-client dan cascade FP-delete
      pas purge beneran jalan).

      **2026-09-18 -- survei 21 router sisa + rencana 5 bagian** (diminta
      user sebelum lanjut, biar gak nemu gap bertumpuk di tengah jalan):
      Bagian 1 quick-wins (`tweets`/`monitored_accounts`/`ransomware`/
      `changelog`/`filtered_articles`, model udah siap) → Bagian 2 domain
      baru self-contained (`rfi`/`pir`/`source_reliability`) → Bagian 3
      ATT&CK/TA (`attack` [prasyarat, sama pola `techstack`→`cve`] →
      `ta_groups` → `mitre` → `crossref`) → Bagian 4 fitur besar mandiri
      (`pkg_vuln`/`newsletter`/`stix`/`mindmap`) → Bagian 5 dashboard
      agregator (`intelligence`/`recap`/`exec_dashboard`, PALING BELAKANGAN
      karena nyedot data dari hampir semua domain lain). Detail lengkap +
      alasan urutan ada di riwayat percakapan; ringkasan tiap bagian nyusul
      di sini pas masing-masing dikerjain.

      **Bagian 1 (2026-09-18) -- 3/5 kelar** (`tweets`, `monitored_accounts`,
      `ransomware`). `Tweet`/`MonitoredAccount`/`RansomwareVictim` model
      udah lengkap dari Fase 4/5 -- tinggal nambah query layer async, pola
      sama kayak `cve`/`techstack`. `MonitoredAccount` ketauan kurang
      `display_name`/`notes` pas porting beneran (migrasi `22b43affdcac`,
      sama pola gap-gap sebelumnya). `apac_indicator`/`ot_status` tweet
      ada DI DALAM `scan_results` JSONB (bukan kolom top-level) -- filter
      pakai operator JSONB Postgres `.as_boolean()`, ekuivalen persis
      `query["apac_indicator"] = True` Mongo lama.

      **`changelog` dan `filtered_articles` SENGAJA di-skip** dari Bagian 1
      (bukan "quick win" beneran begitu diperiksa): `changelog` baca file
      `CHANGELOG.md` langsung dari disk -- monorepo baru ini GAK PUNYA file
      itu (commit message aja, gak ada convention changelog manual), bikin
      satu itu keputusan produk/dokumentasi, bukan keputusan porting
      mekanis. `filtered_articles` baca `scraper_runs` dengan `accepted=False`
      (artikel yang DITOLAK pipeline enrichment) -- skema Postgres (Fase 5)
      cuma nulis artikel yang DITERIMA ke tabel `articles`, gak ada tabel
      "artikel ditolak" sama sekali. Butuh keputusan desain (tabel log
      baru? just skip?) sebelum bisa diport, bukan sekadar tambah kolom.

      Bug nyata ketemu lewat test integrasi (bukan dugaan):
      `AsyncRansomwareVictimRepo.list_filtered` declare `date_start`/
      `date_end` sebagai `str`, dibandingin langsung ke kolom `Date` --
      asyncpg GAK auto-cast varchar ke date (beda dari psycopg2/sync),
      query gagal `UndefinedFunctionError` di runtime. Fix: `datetime.date`
      typed, sama pola kayak `articles`/`cve` (harusnya emang gitu dari
      awal, kelewat pas ngetik cepat). Live-reverified abis fix: endpoint
      yang tadinya 500 sekarang 200.

      Verified LIVE via curl: tweets list/stats/filter (apac/ot/confirmed/
      author/search/date), monitored-accounts CRUD penuh (normalisasi
      `@username` lowercase, 409 duplikat), ransomware victims/filters/
      related-articles. 26 test integrasi baru (Postgres real). Full suite:
      690 passed, mypy 218 file bersih, ruff bersih.

      **Bagian 1 (2026-09-18) -- 5/5 KELAR.** User eksplisit minta kerjain
      `changelog`/`filtered_articles` juga (bukan skip permanen kayak
      opsi default), dua-duanya ternyata butuh keputusan produk/desain
      dulu (ditanyain ke user via `AskUserQuestion`, bukan diputus sendiri):

      - **`changelog`**: user pilih "bikin `CHANGELOG.md` beneran". File
        baru di root repo (`CHANGELOG.md`, format `## [versi] - tanggal`,
        entry pertama `[0.1.0]` ngerangkum Fase 0-7.3 sejauh ini). Router
        port apa adanya (baca+parse regex) -- path file dicari lewat
        walk-up ke root repo (pola sama `_find_repo_root()` di
        `tests/integration/conftest.py`), bukan hitung `.parent` tetap N
        kali kayak legacy (rapuh kalau struktur `apps/api` berubah).

      - **`filtered_articles`**: user pilih "bikin tabel baru + wire ke
        pipeline Fase 5" (opsi yang LEBIH BESAR, nyentuh balik kode yang
        udah live-verified). Tabel baru `rejected_articles` (migrasi
        `8c208279c67f`) + `RejectedArticleRepo` (sync, jalur tulis) +
        `AsyncRejectedArticleRepo` (baca+restore, Fase 7.3). `cti_enrich.
        pipeline.run_pipeline()` sekarang manggil `persist_rejected()`
        (fungsi baru, `stages/persist.py`) pas `classify_result.
        related_cyber == False` -- SEBELUMNYA (Fase 5 awal) artikel yang
        ditolak diam-diam ilang, gak ke-log di mana pun yang bisa
        di-query. `reason` (alasan LLM nolak) DITANGKEP -- ini genuinely
        LEBIH KAYA dari legacy (Mongo `scraper_runs` cuma nyimpen boolean
        `accepted`, gak ada alasan). `restore()` SENGAJA bukan `upsert()`
        biasa -- kalau artikel udah ADA (misal ke-restore manual tapi
        juga keterima normal lewat run enrichment lain), `upsert()` bakal
        NIMPA `news_type` artikel asli jadi "Manually Restored", itu
        salah; `restore()` cek exists-by-URL dulu, no-op kalau udah ada
        (port perilaku lama persis).

        **Verified LIVE end-to-end, bukan cuma test**: `run_pipeline()`
        beneran dipanggil lawan LLM gateway asli dengan judul yang jelas
        gak nyambung cyber ("10 Best Pasta Recipes...") -- LLM nolak,
        `persist_rejected()` nulis baris, `GET /api/filtered-articles`
        nampilin `reason` asli dari LLM, `POST /restore` beneran
        nge-insert ke `articles` dengan `news_type="Manually Restored"`
        dan langsung ke-query balik lewat `/api/articles?search=pasta`.

        **Ketemu (bukan diakibatkan perubahan ini)**: re-test jalur
        ACCEPTED (judul yang genuinely cyber-related) gagal di
        `extract_ttps` dengan `JSONDecodeError` berulang -- ditelusuri
        lebih lanjut, ternyata gateway LLM dev
        (`172.25.0.77:20128`) sekarang ngebalikin respons dari persona
        lain ("Kiro", nolak ngikutin instruksi format JSON) alih-alih
        model reasoning yang biasa dipakai sepanjang Fase 5/6/7 -- indikasi
        gateway/model di baliknya keganti/kereset di luar kendali sesi
        ini. **BUKAN regresi dari perubahan Fase 7.3** -- `git diff
        pipeline.py` dicek eksplisit, cuma nyentuh docstring + cabang
        reject, nol baris di cabang accepted (`fetch_text`/`summarize`/
        `extract_ttps`/`score`/`persist` sama sekali gak diubah). Dilaporin
        ke user sebagai temuan operasional terpisah, bukan dibenerin
        diam-diam di sini.

        7 test unit (`changelog`, parsing regex + walk-up path) + 7 test
        integrasi (`RejectedArticleRepo` sync + dedup by url_hash) + 5 test
        integrasi (`AsyncRejectedArticleRepo`: list/filter/restore/restore
        no-op) -- semua Postgres real. Full suite abis Bagian 1 lengkap:
        **701 passed**, mypy 223 file bersih, ruff bersih.

      Sisa 13 router (Bagian 3-5) nyusul bertahap.

      **Bug infra ketemu pas kerjain ini (di luar scope router itu
      sendiri, tapi ketauan justru dari nge-`mypy` `apps/api` doang):**
      gak ada paket workspace (`cti-core`, `cti-scraper`, `cti-enrich`,
      `cti-alerts`, `cti-scrapers`, `cti-worker`, `cti-api`) yang punya
      marker `py.typed` (PEP 561) -- tanpa itu, mypy DIAM-DIAM nge-`Any`-in
      semua import lintas-paket kalau paket sumbernya gak ikut jadi target
      check eksplisit (bukan cuma di-`import`). Semua "mypy bersih" Fase
      6/7 sebelumnya kebetulan lolos karena SELALU nyertain file
      `cti_core` yang relevan eksplisit di command-nya (`mypy apps/worker
      packages/cti-core/src/cti_core/celery_client.py`, dst) -- begitu
      `mypy apps/api` doang, dua "Returning Any" muncul di
      `services/policy.py` walau kodenya gak berubah. Fix: `touch
      py.typed` di 7 paket sekaligus. Full repo-wide check abis fix: 0
      error baru ketemu (bug ini gak nyembunyiin bug LAIN, tapi infra-nya
      sendiri rapuh -- scoped mypy check ke depan sekarang bener-bener
      independen per paket).

      **Bagian 2 (2026-09-18) -- 3/3 KELAR** (`rfi`, `pir`,
      `source_reliability`) -- user bilang "gas lanjut bagian 2" langsung
      abis Bagian 1. Tiga domain baru self-contained, model Postgres baru
      semua: `rfi_requests`, `pir_requirements`+`pir_notes`,
      `source_reliability_entries` (migrasi `f5a204cd523a`).

      **`pir` matching TIDAK punya query builder sendiri** -- kode lama
      py DUA salinan identik (`pir_service.py::_build_query` DAN
      `scripts/export_pir_docx.py::_build_article_query`). Di sini
      kriteria PIR (`threat_actors`/`industries`/`countries`/`news_types`/
      `keywords`/`ttps`) di-map ke parameter `AsyncArticleRepo.
      list_filtered()` yang UDAH ADA dari router `articles` -- nambah SATU
      param baru (`ttps`, filter `ArticleTTP.ttp_id`) ke situ, bukan bikin
      builder baru. `criteria.keywords` -> `title_keywords` (OR-match
      `Article.title` doang -- skema baru gak nyimpen `body`/`content` per
      artikel, beda dari Mongo lama yang nyari lintas 4 field, tapi ini
      SUBSET yang faithful terhadap apa yang beneran ada, bukan
      pengurangan scope sembunyi-sembunyi).

      Docx export (`GET /{id}/export/docx`) port `build_docx()` dari
      `scripts/export_pir_docx.py` verbatim ke `services/pir_docx.py` --
      nambah dependency baru `python-docx` di `apps/api/pyproject.toml`.
      Verified LIVE: hasil file beneran kebuka valid Word doc (`file`
      command konfirmasi "Microsoft OOXML"), bukan cuma HTTP 200 doang.

      **Dua asimetri port apa adanya dari kode lama, didokumentasikan di
      docstring `cti_core.db.repositories.rfi`/`pir`, BUKAN keputusan baru
      di sini:**
      1. Baca-vs-tulis: banyak `GET` di `rfi`/`pir` (articles/note/export/
         export-docx/options) SAMA SEKALI gak `require_auth` di kode lama --
         sama pola kayak `articles.py`/`filtered_articles.py` sebelumnya.
      2. Client-scoping: `list`/`create` di-filter `client_id`, tapi
         `get`(PIR)/`update`/`delete`/notes/export SAMA SEKALI gak (RFI:
         `get` scoped, `update`/`delete` TIDAK). Siapa pun yang tahu ID
         bisa update/delete lintas client -- keliatan konsisten di DUA
         file (bukan typo satu tempat), jadi diikutin apa adanya + di-flag
         jelas biar user bisa minta diperbaiki belakangan kalau mau.

      **Kuirk port apa adanya dari `_compute_coverage()` lama:** PIR
      dengan kriteria KOSONG semua match-all buat `coverage_count`/
      `last_match`, tapi `recent_coverage` di-hardcode 0 (bukan dihitung
      beneran) -- efeknya PIR tanpa kriteria SELALU `is_gap=true`.
      Kemungkinan sengaja (dorong analis isi kriteria), bukan lupa nulis
      kode -- test `test_compute_coverage_empty_criteria_recent_always_zero`
      ngunci perilaku ini.

      **Bug real ketemu + dibenerin dari live-test (BUKAN dari test suite
      -- integration test lolos duluan karena gak assert `updated_at`
      abis path UPDATE beneran):** `PUT /api/pir/{id}`, `PUT /api/pir/{id}/
      note`, `PUT /api/rfi/{id}` semua 500 `MissingGreenlet` pas nyerialisasi
      `.updated_at` abis `session.commit()`. Sebab: kolom `updated_at`
      (`onupdate=func.now()`, nilai dihitung SERVER pas UPDATE) gak
      selalu eager-fetch via RETURNING kayak kolom sejenis pas INSERT --
      `POST` (create) jalan mulus, `PUT` (update) yang genuinely UPDATE
      baris yang UDAH ADA yang kena. Fix: `await session.refresh(obj)`
      eksplisit sebelum serialize, di tiga tempat itu. Ketauan justru dari
      nyoba UPDATE beneran (bukan cuma create-lalu-baca) waktu live-test
      manual -- pengingat kenapa live verification tetap dijalanin walau
      integration test udah 729 passed.

      10 test integrasi `AsyncRFIRepo` + 9 test `AsyncPIRRepo` + 8 test
      `AsyncSourceReliabilityRepo` + 1 test baru `AsyncArticleRepo.
      list_filtered(ttps=...)` -- semua Postgres real (testcontainers).
      Live-verified via curl: RFI create/list/update/delete, PIR create/
      list/coverage/articles/note-save+get/export-json/export-docx/update/
      delete, SR add/list/labels/ungraded-sources/update/delete -- token
      JWT superadmin asli, lewat `apps/api` uvicorn ngobrol ke Postgres+
      Redis docker-compose lokal (bukan testcontainers efemeral). Full
      suite: **729 passed**, mypy 77 file (`cti-core`+`apps/api`) bersih,
      ruff bersih.

      **Bagian 3 (2026-09-19) -- 4/4 KELAR** (`attack`, `ta_groups`,
      `mitre`, `crossref`) -- user bilang "gas lanjut bagian 3". Rantai
      ATT&CK/TA sesuai urutan dependency yang direncanakan: `attack`
      (prasyarat) → `ta_groups` → `mitre` → `crossref`.

      **`attack`** -- katalog MITRE ATT&CK (technique/tactic/mitigation/
      group/software/relationship), 6 tabel baru + `attack_sync_log`.
      `sync_domain()` fetch bundel STIX (JSON, bisa puluhan MB) dari
      GitHub `mitre/cti` per domain (enterprise/ics/mobile), upsert
      batched `INSERT ... ON CONFLICT (stix_id) DO UPDATE` (500/batch,
      port angka yang sama dari `_bulk_write()` lama). `domains` (ARRAY)
      butuh merge-dedup manual di klausa `SET` (`array_agg DISTINCT`
      gabungan array lama+baru) -- tanpa itu re-sync domain yang sama
      numpuk entry duplikat, `$addToSet` Mongo lama otomatis nyegah ini.
      `stix_id` (bukan `attack_id`/`group_id`) yang jadi kunci upsert,
      persis `_id: obj["id"]` Mongo lama -- kode manusia-readable
      ("T1059"/"G0016") SENGAJA gak diberi UNIQUE constraint (gak
      dijamin unik lintas domain bundel MITRE). `POST /sync`/
      `GET /sync/{domain}` pakai FastAPI `BackgroundTasks` port apa
      adanya -- BUKAN salah satu dari 5 loop Fase 7.8 (itu loop
      KONTINYU, ini aksi admin sekali-pakai), butuh session sendiri
      (`async_session()` langsung) karena session request-scoped ke-close
      begitu response terkirim. Full-text search Mongo (`$text`) -> ILIKE,
      konsisten sama router lain. Verified LIVE: sync domain `mobile`
      beneran (137 technique/22 group/127 software/1889 relationship dari
      GitHub asli), re-sync gak numpuk `domains` duplikat (delta=0),
      semua endpoint query (techniques/tactics/mitigations/groups/
      software/navigator-layer) jalan atas data hasil sync itu.

      **`ta_groups`** -- daftar nama TA utama REUSE `ThreatActorGroup`
      (`threat_reference.py`, Fase 5, dipakai bareng `cti_enrich.stages.
      score` buat `mentioned_group` matching) alih-alih bikin tabel baru
      terpisah -- ketauan pas baca model itu, itu PERSIS collection yang
      sama kayak `TA_GROUPS_COLLECTION` lama. Nambah kolom `source` yang
      ketinggalan (tabelnya awalnya cuma dibaca, belum ada jalur tulis).
      3 tabel baru: `ta_whitelist` (suppression list, bukan whitelist
      beneran -- nama TA yang DITOLAK jadi group), `ta_watchlist`
      (per-client), `ta_profiles` (JSONB, profil terstruktur hasil LLM).
      Timeline (`get_ta_timeline`) + dormancy detection cross-reference
      artikel+tweet+ransomware victim per bulan.

      **Bug real ketemu dari test integrasi** (bukan hipotesis): query
      `get_timeline` pakai `func.to_char(Article.posted_on, "YYYY-MM")`
      DUA KALI terpisah (SELECT + GROUP BY) -- SQLAlchemy generate dua
      bind parameter beda (`$1`/`$4`) walau nilainya sama, Postgres nolak
      ("must appear in GROUP BY clause") karena validasinya SINTAKS,
      bukan nilai. Fix: assign `func.to_char(...)` ke variabel, dipakai
      ULANG objek yang sama di SELECT dan GROUP BY.

      LLM client-nya SENGAJA gak reuse `cti_enrich.llm.client` walau itu
      "SATU LLM client" kanonik Fase 5 -- `apps/api` punya exit criteria
      eksplisit (atas, Fase 7): "gak ada import `cti_scraper`/`cti_enrich`
      dari API". Duplikat sempit (~15 baris) `OpenAI(**kwargs)` di
      `services/ta_profile.py`, `LlmSettings`/`get_settings()`-nya tetap
      dari `cti_core`.

      CVE crossref (`exploited_vulnerabilities` LLM vs `cve_tracker`
      real) butuh kolom yang belum ada: `cisa_kev`/`active_exploitation`
      (bool) + `threat_actors`/`ttps` (tabel anak baru `CveThreatActor`/
      `CveTTP`, pola sama `ArticleThreatActor`/`ArticleTTP`). Field ini
      ADA di dokumen Mongo lama tapi ditulis loop enrichment CVE
      (`_cve_enrichment_loop`, Fase 7.8, BELUM diport) -- kolomnya
      ditambah sekarang (gap ketauan pas porting) supaya query crossref
      udah bener begitu 7.8 ngisi datanya, buat sekarang selalu
      kosong/false (bukan bug, cold-start biasa).

      **Verified LIVE dengan LLM gateway asli:** `POST /api/ta/profile/
      generate` kena isu "Kiro persona" yang udah didokumentasikan di
      Bagian 1 (gateway dev balikin response non-JSON) -- `HTTP 200` dari
      gateway tapi `json.loads` gagal ("Expecting value"). Bukan bug baru
      di sini, konsisten sama temuan operasional yang udah dilaporkan.

      **`mitre`** -- heatmap TA/industri x TTP, baca `articles`/
      `article_ttps`/dst (Fase 2, ternormalisasi) -- BUKAN katalog
      `attack_techniques` (`attack` di atas): heatmap ngukur TTP yang
      BENERAN keobservasi di pemberitaan (ekstraksi LLM Fase 5), beda
      sumber data dari katalog referensi MITRE, gak saling gantiin (sama
      pola `source_score_service.py` vs `source_score_db_service.py` di
      Bagian 2). `d3fend_service.py` (`urllib` sync-in-thread) diganti
      `httpx.AsyncClient`, port perilaku sama (cache in-memory, gagal ->
      list kosong) -- verified LIVE manggil API publik D3FEND asli, 15
      countermeasure buat T1059.

      **`crossref`** -- nyambungin CVE/PIR/TA lewat overlap threat_actors/
      TTPs, dikerjain TERAKHIR (butuh `cve`/`pir`/`ta_groups` semua udah
      ada). SEMUA query lintas client, TANPA filter `client_id` -- port
      apa adanya, kode lama juga gak nge-scope endpoint ini. `pir_id`
      sekarang `int` path param, gak perlu try/except `ObjectId(...)`.
      Verified LIVE: crossref CVE real (severity/KEV data bener), PIR
      overlap TA/TTP, TA cross-ref narik artikel+PIR+profil.

      23 test integrasi baru (`AsyncAttackSyncRepo`/`AsyncAttackQueryRepo`
      lewat live sync, `AsyncTARepo`/`AsyncTAProfileRepo`,
      `AsyncMitreHeatmapRepo`, `cti_api.services.crossref`). Full suite:
      **752 passed**, mypy 90 file bersih, ruff bersih.

      **Bagian 4 (2026-09-19) -- 4/4 KELAR** (`newsletter`, `mindmap`,
      `stix`, `pkg_vuln`) -- user bilang "gas fase 4 bro". Urutan kerja:
      newsletter → mindmap → stix → pkg_vuln (terbesar, dikerjain
      terakhir).

      **Byproduct arsitektur**: `cti_enrich/ioc/extractor.py` (SATU IOC
      extractor kanonik, Fase 5) dipindah ke `cti_core/ioc/extractor.py`
      -- modul itu nol dependency internal `cti_enrich`, jadi relokasi
      mekanis, zero behavior-change, yang ngebolehin `apps/api` (exit
      criteria: gak boleh import `cti_scraper`/`cti_enrich`) DAN
      `cti_enrich` sama-sama impor SATU ekstraktor yang sama, gak perlu
      fork lagi. `cti-alerts/mailer.py` (baru) ngelengkapin janji
      `pyproject.toml` package itu sendiri ("Telegram sender + Graph/SMTP
      mailer") -- `send_newsletter_email()` Graph-only (POST
      `/users/{sender}/messages`, bikin DRAFT bukan `/sendMail`, analis
      review manual di Outlook -- persis kode lama), SMTP DIBUANG
      (`SmtpSettings` gak pernah ada di skema config baru, `.env` cuma
      punya kredensial Graph).

      **`newsletter`** -- fetch artikel (Playwright + `trafilatura`,
      deteksi paywall keyword-based), ringkasan per-artikel via LLM,
      korelasi CVE (tabel anak baru `CveNewsletterMention`, ganti
      Mongo array-push-dedup jadi `UniqueConstraint(cve_tracker_id, url)`
      asli). `include_clusters` (analisis cluster kampanye,
      `cluster_service.py` 784 baris TF-IDF/Jaccard) SENGAJA belum
      diport -- di luar 27 router, sama alasan kayak `mindmap`'s builder
      `cluster` di bawah. **Bug real ketemu dari test integrasi**:
      `AsyncNewsletterRepo.list_all()` non-deterministic -- Postgres
      `now()` itu waktu TRANSAKSI bukan waktu STATEMENT, jadi banyak
      baris yang di-insert dalam satu transaksi test dapet `created_at`
      identik, `ORDER BY created_at DESC` doang gak cukup. Fix: tambah
      `Newsletter.id.desc()` sebagai tie-breaker kedua. Endpoint kirim
      email (`/resend`, `/draft-email`) SENGAJA belum di-live-test --
      butuh izin eksplisit user dulu (kirim email beneran/draft ke
      mailbox asli), cuma diverifikasi lewat unit test mock. Sisa
      pipeline (fetch Playwright, ekstraksi IOC, render HTML) verified
      LIVE (artikel Wikipedia asli, 11231 karakter ke-ekstrak).

      **`mindmap`** -- generate diagram Mermaid per domain (newsletter/
      threat_actor/cve/pir/ransomware), cache generik `(feature_type,
      doc_id) -> syntax` + custom-edit override. `doc_id` per
      feature_type dipetakan ke identifier yang SAMA dipakai router lain
      buat domain itu (`cve_id` string, nama TA, `PIRRequirement.id`/
      `Newsletter.id`, `group_name`) -- BUKAN internal PK Postgres,
      simplifikasi dari dual ObjectId-lalu-fallback-nama kode lama,
      konsisten sama pola yang udah ada di router lain. Builder
      `cluster` (butuh `cluster_service.py` yang sama kayak di atas)
      SENGAJA belum diport. Verified LIVE: generate + cache-hit
      (ganti data CVE abis generate pertama, syntax gak ikut berubah
      tanpa `/regenerate` eksplisit) pakai data real dev Postgres.

      **`stix`** -- export bundle STIX 2.1 (article/TA/IOC/PIR), builder
      STATELESS (baca-transform doang, gak ada tabel baru sama sekali).
      Asimetri auth port apa adanya: cuma `/article/{id}` yang
      `require_auth`, 3 endpoint lain publik. `article_id` sekarang
      `int` (bukan ObjectId hex), `AsyncPIRRepo.list_active_unscoped()`
      (dipakai bareng `crossref` Bagian 3) ditambah `order_by(priority)`
      biar cocok sama `.sort("priority", 1)` lama. Verified LIVE:
      export artikel real (Unc6671/T-technique beneran, 13 objek STIX +
      relationship `uses`), TA-not-found -> 404, IOC bundle + filter
      type, PIR bundle keurut priority.

      **`pkg_vuln`** -- terbesar (1109 baris service lama), monitoring
      vulnerability paket (osv.dev + deps.dev). **Ketemu skema Fase 2
      yang udah ada duluan** (`models/package.py`,
      `MonitoredPackage`/`PackageVuln`/`PackageVulnAlias`/
      `PackageDepEdge`) -- ditulis SEBELUM `pkg_vuln_service.py` lama
      dibaca detail, 3 tabel kosong (gak pernah ke-wire router/service/
      test manapun), DIGANTI TOTAL (bukan alter bertahap, aman karena
      kosong): `PackageVuln.monitored_package_id` FK STRICT gak bisa
      nampung kasus nyata (`resolve_package_deps(scan_transitive=True)`
      scan dependensi TRANSITIF yang BUKAN package dimonitor, `update_one`
      TANPA `upsert=True` lama diem2 no-op kalau gak ketemu tapi vuln-nya
      tetap kesimpen) -- diganti `package_name`/`ecosystem`/`client_id`
      DENORMALIZED, port apa adanya dari bentuk Mongo lama. Field yang
      ilang total di sketsa (rollup `vuln_count`/`*_count`/
      `highest_severity` dkk, `cvss_score`/`adjusted_score`/`published`/
      dst) ditambahin lengkap. `_enrich_vulns_composite()` (EPSS dari
      FIRST.org + KEV dari CISA) SENGAJA belum diport -- `epss_service.py`/
      `cisa_kev_service.py` SAMA yang udah didokumentasikan belum ke-port
      di `routers/cve.py` (`/cisa-lookup`/`/epss-lookup`), bukan concern
      `pkg_vuln` doang; kolom `epss_*`/`kev*` tetap ada di skema, `adjusted_
      score` dihitung dari `cvss_score` doang saat scan (formula sama,
      cuma belum "boosted" pass kedua). Fire-and-forget
      `asyncio.create_task(scan_package(...))` lama (dipanggil dari 4
      tempat beda: `add_package`/`update_package`/`import_lockfile`/
      `resolve_package_deps`) DIPINDAH ke router pakai `BackgroundTasks`
      + `async_session()` sendiri, pola sama `attack.py` Bagian 3 --
      service jadi murni CRUD+orkestrasi eksternal, gak nge-spawn task
      sendiri. `scan_all_packages()` SEKUENSIAL (bukan `asyncio.gather`
      batch-10 + `sleep(2)` lama) -- satu `AsyncSession` gak aman
      concurrent, throttling lama ikut dibuang (gak ada concurrency yang
      perlu ditahan). Ketemu dependency baru yang kelewat pas nulis
      endpoint upload lockfile: `python-multipart` (FastAPI butuh ini
      buat `UploadFile`), ditambah ke `apps/api/pyproject.toml`.
      Verified LIVE end-to-end pakai osv.dev/deps.dev BENERAN: `lodash@
      4.17.15` narik 6 CVE asli (CVE-2020-8203/CVE-2021-23337/dst,
      3 HIGH/3 MEDIUM), `flask@2.0.0` narik 4 CVE asli, `resolve-deps`
      narik OSSF Scorecard asli (skor 5.4, checks asli) + dep graph,
      import-lockfile (package asli + package fiktif yang bener2 gak ada
      di registry -- gak crash, 0 vuln doang), ack toggle, delete
      cascade ke vuln anak-nya.

      75 test baru (22 unit parser lockfile/CVSS murni + 53 integrasi
      Postgres real: newsletter/mailer/mindmap/stix/pkg_vuln). Full
      suite: **827 passed**, mypy 108 file (`cti-core`+`cti-api`)
      bersih, ruff bersih.

      **Bagian 5 (2026-09-19) -- 3/3 KELAR** (`intelligence`, `recap`,
      `exec_dashboard`) -- user bilang "gas bagian 5 bro", TERAKHIR
      dari 5 bagian karena nyedot data dari hampir semua domain lain
      (persis alasan urutan yang direncanakan sejak survei 2026-09-18).

      **`intelligence` -- 3 dari 7 endpoint lama SENGAJA belum diport**:
      `/clusters`, `/clusters/recent`, `/clusters/evolution`,
      `/clusters/{id}/trends`, `/intelligence/geopolitical` (5
      sebenarnya) SEMUA transitif butuh `cluster_service.py` (784 baris
      TF-IDF/Jaccard, di luar 27 router) -- `campaign_trend_service.py`/
      `geopolitical_service.py` ikut kena karena masing-masing baca
      output cluster (`CLUSTERS_COLLECTION`) atau nerima `campaigns`
      sebagai parameter. Sama alasan persis kayak deferred `cluster`
      di `newsletter`/`mindmap`/`exec_dashboard` (Bagian 4-5). Yang
      PORTABLE (`/spikes`, `/intelligence/risk-matrix`, `/source-scores`)
      -- ketiganya baca `articles` langsung, gak ada dependency cluster.

      **Repo baru `AsyncDashboardRepo`** (`cti_core.db.repositories.
      dashboard`) -- ~20 method agregasi lintas `articles`/`cve_tracker`/
      `iocs`, dipakai bareng `intelligence`/`exec_dashboard`/`recap`.
      Bucket bulanan pakai `func.to_char(Article.posted_on, 'YYYY-MM')`
      ganti `$substr` Mongo lama -- HARUS diassign ke variabel & dipakai
      ULANG objek yang sama di SELECT+GROUP BY, bug real yang sama
      persis kayak `AsyncTARepo.get_timeline()` (Bagian 3) kalau lupa.
      **Semua query SEKUENSIAL**, bukan `asyncio.gather` kayak lama --
      dashboard-v2 aja manggil ~15 query terpisah, satu `AsyncSession`
      emang gak aman concurrent (constraint yang sama berkali-kali
      ketemu sesi ini).

      **2 bug REAL ketemu & DIPERBAIKI (bukan asimetri desain)**, dua-duanya
      typo/field-salah yang bikin sebagian output LLM/skor mati diam-diam:
      1. `risk_matrix_service.py` lama baca `doc.get("attack_techniques")`
         buat komponen skor TTP -- field itu TIDAK PERNAH ada di dokumen
         artikel manapun (field TTP artikel asli namanya `ttps`), jadi
         komponen `unique_ttps * 2` di formula skor SELALU 0. Di sini
         pakai `ttps` asli.
      2. `exec_brief_service.py` lama baca `ta.get('name')`/`('count')`/
         `('velocity')` dari entry `ta_velocity`, tapi `_compute_ta_
         velocity()` beneran ngehasilin key `actor`/`total`/`velocity_pct`
         -- section "TOP THREAT ACTORS BY VELOCITY" di brief eksekutif
         SELALU nge-render "Unknown: 0 incidents". Di sini pakai key yang
         beneran dihasilin.

      **`_get_recent_clusters()`/`recent_clusters_summary` (exec_dashboard
      v2) DAN `_collect_campaigns()` (recap) SENGAJA balikin `[]`** --
      cluster_service lagi, TAPI kode lama sendiri udah bungkus dua-duanya
      `try/except -> []`, jadi cuma selalu hit fallback yang udah ada,
      bukan kontrak baru yang dilanggar.

      **`recap`** -- digest harian (artikel+tweet+IOC+CVE+TA baru) + LLM
      forecast 1-3 hari, cache per-tanggal (`daily_recaps`, tabel baru).
      Artikel diurutin heuristik `source_score.get_source_reliability()`
      (nama sumber) gantiin field `source_reliability` per-dokumen lama
      yang gak ada analognya di skema baru (grading itu sekarang query
      terpisah `AsyncSourceReliabilityRepo`, bukan kolom artikel).
      `AsyncTARepo.list_added_on()` (baru) pakai `created_at::date`
      gantiin kolom `added_date` yang emang gak pernah ada di skema
      (`ThreatActorGroup` cuma punya `TimestampMixin.created_at`,
      semantiknya sama). **Verified LIVE dengan LLM gateway asli**:
      `POST /api/recap/generate` jalan bersih (gak kena isu "Kiro
      persona" yang beberapa kali muncul Bagian 1/3/4) -- recap hari
      sepi (0 artikel/tweet/CVE, 89 IOC, 3991 TA baru dari seed data)
      dihasilin JUJUR ("no notable activity", sesuai rule system prompt),
      bukan dikarang. Cache-hit + `/list`/`/{date}` + validasi format
      tanggal semua diverifikasi LIVE juga.

      **`exec_dashboard`** -- `GET /dashboard` (v1) **SENGAJA TANPA
      AUTH**, port apa adanya (`/dashboard-v2` dan `POST /brief` tetap
      di-gate) -- asimetri yang gak biasa (bukan pola baca-publik/tulis-
      digate yang udah sering ketemu, ini "v1 publik, v2+brief di-gate")
      tapi dipertahankan sesuai kode lama. `_get_critical_cves()` cuma
      filter `cisa_kev` (cabang `epss_score >= 0.5` gak ada kolomnya,
      sama alasan `pkg_vuln`/`cve.py`). **Verified LIVE**: v1+v2+brief
      ketiganya jalan atas data dev Postgres real (15 insiden, 6 TA unik,
      leaderboard Unc6671/Turla/Apt41/dst, top TTPs T1005/T1190/T1570),
      `POST /api/exec/brief` ngehasilin brief markdown 5-section lengkap
      dari LLM gateway asli, ground di data real (nyebut UNC6671, CVE
      WordPress, risk score per sektor -- bukan generik).

      22 test baru (`AsyncDashboardRepo` x9, `exec_dashboard`/`spike`/
      `risk_matrix` service x5, `AsyncRecapRepo` x3, `recap` service x5
      dengan LLM di-mock). Full suite: **849 passed**, mypy 120 file
      (`cti-core`+`cti-api`) bersih, ruff bersih.

      **Fase 7.3 SELESAI -- 25/25 router** (lihat catatan di atas soal
      angka "27" awal). Lanjut ke sisa Fase 7 (**7.4** port 56 service,
      **7.5** buang duplikasi, **7.6** snapshot test, **7.7** ekspor
      OpenAPI, **7.8** 5 loop jadi Celery beat) sebelum Fase 8 (`apps/web`).
- [x] **7.4** Port 56 service -- **survei + urutan kerja kelar
      (2026-09-19, user minta "cek dulu servicenya, urutkan mana duluan
      mana belakangan")**: ~37/56 service TERNYATA udah keport sebagai
      efek samping porting 27 router (Fase 7.3). 19 sisa dipetakan jadi
      5 grup (B → D → C → A, plan lengkap di
      `~/.claude/plans/oke-bro-jadi-gini-sparkling-fern.md` §"Fase 7.4"):
      **Grup A** "mesin cluster" (`cluster_service.py` 784 baris TERNYATA
      punya 5 dependency internal -- `campaign_scoring_service`/
      `killchain_service`/`cve_priority_service`/`campaign_link_service`/
      `diamond_model_service` -- total 1510 baris, bukan 784; plus
      `campaign_trend_service`/`geopolitical_service` consumer-nya, 1773
      baris total, butuh keputusan taruh sklearn di mana), **Grup B**
      lookup eksternal CVE (KELAR, lihat bawah), **Grup C** ticket/email/
      export CVE (KELAR, lihat bawah), **Grup D**
      standalone tanpa blocker (`confidence_service`/`fp_analytics_
      service`/`dedup_service` + 2 endpoint ketinggalan -- KELAR, lihat
      bawah), **Grup E** keluar scope (`wisemap_service.py` 391
      baris + `wisemap_cti.py` ternyata DEAD CODE -- nol referensi
      router manapun, `oidc_service`/`scraper_health_service` beda
      fase/udah dideferred).

      **Grup B (2026-09-19) -- 3/3 KELAR** (`epss_service`,
      `cisa_kev_service`, `exploit_db_service`, 299 baris gabung 1 file
      `cti_api.services.cve_lookup`) -- paling kecil, paling gak ada
      dependency baru, LANGSUNG nutup kolom yang UDAH ADA tapi SELALU
      kosong di kode yang baru dibangun Bagian 4/5 (`PackageVuln.epss_*`/
      `kev_date_added`, `exec_dashboard`'s cabang `epss_score >= 0.5`).
      4 endpoint baru nempel di router `cve.py` yang udah ada
      (`POST /cisa-lookup`/`/epss-lookup`/`/exploit-lookup`/
      `/{id}/exploit-lookup`), bukan router baru. 8 kolom baru
      `CveTracker` (`epss_score`/`epss_percentile`/`epss_date`/
      `epss_checked_at`, `cisa_kev_checked_at`+`cisa_kev_detail` JSONB,
      `exploit_db_checked_at`+`exploit_db_hits` JSONB) -- migrasi butuh
      `server_default` di 2 kolom JSONB NOT NULL karena `cve_tracker`
      UDAH ada isinya (4 baris), bukan tabel baru kosong.

      Fungsi service (`run_epss_lookup`/`run_cisa_kev_lookup`/`run_
      exploit_db_bulk_lookup`/`run_exploit_db_single_lookup`) sengaja
      `session`-pertama -- FONDASI Fase 7.8 ("CVE enrichment", salah
      satu dari 5 loop Celery beat): begitu 7.8 dikerjain, tinggal
      bungkus fungsi yang SAMA jadi task beat, gak perlu nulis ulang.

      **EPSS/CISA-KEV/exploit-db itu properti CVE ITU SENDIRI, bukan
      spesifik client** -- lookup lama `update_many` lintas SEMUA baris
      client yang nge-track cve_id yang sama, method repo baru
      (`apply_epss_scores`/`apply_cisa_kev_hits`/`apply_exploit_hits`)
      port perilaku itu, BEDA dari `add_newsletter_mention` (Bagian 4)
      yang baris pertama doang.

      **1 bug legacy ketemu & DIPERBAIKI, bukan silent fix** --
      `exploit_db_service.py` lama cek dedup POC dari SATU dokumen
      (`find_one`, ambil sembarang) lalu `$push` hasil yang sama ke
      SEMUA baris client lewat `update_many` -- kalau >1 client nge-
      track CVE yang sama, baris client lain bisa kebagian POC duplikat.
      Di sini dedup dihitung ULANG per baris (per client), koreksi
      kecil yang konsisten sama niat aslinya ("jangan taro POC dobel"),
      bukan ubah kontrak.

      **1 bug API EKSTERNAL ketemu LEWAT LIVE TEST, bukan port issue** --
      exploit-db beneran ganti bentuk respons sejak kode lama ditulis:
      field `description` SEKARANG list `[edb_id, title]`, bukan string
      polos (`row.get("description", "").strip()` lama crash
      `AttributeError` kalau dibiarin). Ini bukan "port apa adanya" --
      kontrak API pihak ketiga yang berubah, bukan keputusan desain lama
      -- diperbaiki (`_extract_title()`, tetap dukung string polos buat
      jaga-jaga), ketauan justru KARENA live-test terhadap API asli,
      bukan cuma baca kode lama.

      **Verified LIVE 100% terhadap API eksternal asli** (bukan mock
      doang buat verifikasi akhir): `CVE-2021-44228` (Log4Shell)
      disisipin manual ke dev DB buat test -- `/cisa-lookup` match asli
      lawan katalog CISA KEV 1721 entry (`Apache Log4j2 Remote Code
      Execution Vulnerability`), `/epss-lookup` narik skor EPSS asli
      dari FIRST.org (`0.99999`, persentil `1.0` -- cocok sama fakta
      publik Log4Shell EPSS-nya emang salah satu yang tertinggi pernah
      ada), `/{id}/exploit-lookup` narik 3 exploit ASLI dari exploit-db
      (ID 50590/50592/51183, URL bener, judul ke-parse bener SETELAH
      fix bug di atas). `GET /api/cve?tech=Log4j` konfirmasi ketiga
      field nyantol bareng di satu baris (`epss=0.99999, kev=true,
      active_exploitation=true, pocs=3`).

      13 test baru (4 unit parser murni + 9 integrasi Postgres real,
      HTTP eksternal di-mock buat suite otomatis -- verifikasi LIVE
      manual terpisah kayak di atas). Full suite: **862 passed**, mypy
      121 file bersih, ruff bersih.

      **Grup D (2026-09-23) -- 4/4 KELAR** (`confidence_service`,
      `fp_analytics_service`, `dedup_service`, + 2 endpoint yang
      ketinggalan pas Fase 7.3 -- `articles.py`'s `/dashboard` dan
      `iocs.py`'s `/ta-links/{type}/{value}`) -- semua nempel ke router
      `articles.py`/`iocs.py` yang UDAH ADA, bukan router baru.
      `confidence.py`+`fp_analytics.py`+`dedup.py`+`article_dashboard.py`
      (services) + `ioc_ta_links.py`.

      **3 kolom baru `IOC`** (`actionability_score`/`actionability_label`/
      `recommended_action`, semua nullable) -- migrasi gak butuh
      `server_default` (nullable, bukan JSONB NOT NULL kayak kolom Grup B).

      **Confidence artikel ditulis lewat `AsyncArticleRepo.set_overrides()`,
      BUKAN kolom `confidence_score` langsung** -- keputusan sengaja:
      docstring `Article.overrides` (Fase 2) nyebut `confidence_score`
      sebagai CONTOH field yang dilacak lewat overrides, walau tulisan
      Mongo lama (`compute_and_store`) `$set` langsung tanpa konsep
      override sama sekali. Ngikutin dokumentasi skema yang UDAH ADA,
      bukan port literal.

      **`compute_ioc_actionability`'s `campaign_score` PERMANEN 0** --
      butuh `CLUSTERS_COLLECTION` (mesin cluster, Grup A, BELUM diport).
      Legacy sendiri fallback `try/except -> 0` kalau lookup gagal; di
      sini fallback yang sama, cuma permanen sampai Grup A ada. TIDAK
      mengubah kontrak, cuma selalu hit jalur yang udah ada.

      **Dependency baru `scikit-learn`** (`apps/api`, buat
      `dedup_service`'s TF-IDF+cosine similarity) -- kelas keputusan
      sama kayak kenapa `cti-enrich` naruh torch/spacy di belakang extra
      `[nlp]` (compute-heavy). `uv sync` polos WIPE lagi extra
      `cti-enrich[nlp]` (udah kejadian & didokumentasikan pas Bagian 4)
      -- di-restore manual abis nambah dependency.

      **1 method repo baru per file, gak ada yang berat**:
      `AsyncIOCRepo.apply_confidence_and_actionability()`+
      `list_with_feedback()`, `AsyncTARepo.get_watchlist_names_unscoped()`
      (asimetri legacy: watchlist check LINTAS SEMUA client, bukan
      `client_id`-scoped kayak model barunya -- dipertahankan apa
      adanya, pola sama kayak `AsyncPIRRepo.list_active_unscoped()`),
      `AsyncAttackQueryRepo.get_group_by_name_or_alias_ci()` (case-
      insensitive nama ATAU alias -- scan Python di tabel kecil ~150
      baris, gak ada cara bersih match ARRAY(String) Postgres case-
      insensitive tanpa unnest per-baris yang sama beratnya),
      `AsyncSourceReliabilityRepo.get_all_ratings()` (preload semua
      rating sekali biar `recompute_all_confidence` gak N+1 query per
      artikel), 6 method baru `AsyncDashboardRepo` (`distinct_source_
      count`/`unique_mentioned_country_count`/`top_countries`/
      `top_sources`/`top_industries`/`article_timeline` -- semua terima
      `posted_on_start`/`posted_on_end` OPSIONAL dua-duanya, beda dari
      method exec_dashboard lain yang `posted_on_start` wajib).

      **`/api/dashboard`'s `top_countries` SENGAJA gak re-normalize nama
      negara** kayak `normalize_country()` Python-side lama -- masalah
      itu (negara FREE-TEXT butuh grouping manual) UDAH BERES di data
      model (`ArticleCountry.country_code` udah ISO alpha-2 kanonik dari
      enrichment, Fase 2/5), bukan lagi query-time. Query SQL `GROUP BY`
      langsung, tanpa post-process Python.

      **`/articles?dedup=true` gak nambah field baru ke `ArticleOut`** --
      ketauan dari baca legacy Pydantic model: `model_config =
      {"extra": "ignore"}`, jadi `_dup_count`/`_dup_sources`/`_dup_urls`
      dari `find_dedup_groups()` SELALU didrop diam-diam pas serialize
      ke `ArticleOut` di endpoint list -- cuma listnya yang efektif
      terfilter (dedup), metadata dup gak pernah nyampe response.
      `/articles/dedup-groups` (endpoint terpisah, raw dict response)
      yang beneran nampilin `_dup_count` dkk.

      **1 gap ketemu LEWAT LIVE TEST, langsung diperbaiki** --
      `iocs.py`'s `_serialize_summary()`/`_serialize_detail()` gak
      pernah include `actionability_score`/`actionability_label`/
      `recommended_action` walau kolomnya udah ada & udah kehitung --
      ketauan pas live-test `POST /{ioc_id}/feedback` (endpoint yang
      justru INTINYA nampilin actionability baru), bukan dari baca kode
      doang. Ditambahin ke serializer.

      **Verified LIVE terhadap dev DB real** (uvicorn lokal, Postgres+
      Redis via `localhost` override, token JWT di-mint langsung lewat
      `create_token()` -- gak ada password admin1 yang diketahui):
      `/api/dashboard` (38 artikel real, agregasi negara/sumber/TA/TTP/
      timeline semua ke luar bener), `/api/articles/dedup-groups`
      (jalan lewat scikit-learn beneran, gak crash), `POST /{ioc_id}/
      feedback` (IOC id=7 real, confidence 50->89->86 abis 2 feedback,
      actionability `monitor` + recommended action bener), `GET
      /ta-links/domain/...` (nemu TA `Breeze comet` dari artikel
      linked beneran), `POST /articles/{id}/confidence` +
      `/confidence/recompute` (38/38 artikel keupdate, override
      ke-merge bener pas dibaca ulang). Data feedback sintetis di IOC
      id=7 DIBERSIHIN abis verifikasi (`DELETE ioc_feedback` + reset
      counter/confidence/actionability) -- confidence recompute di 38
      artikel real DIBIARIN (bukan data sintetis, hasil legit fitur
      "recompute" yang emang gunanya nimpa skor lama).

      59 test baru (2 file unit murni -- `compute_score`/
      `compute_ioc_confidence`/`compute_ioc_actionability`/
      `find_dedup_groups` -- + 7 file integrasi Postgres real). Full
      suite: **921 passed**, mypy 126 file bersih, ruff bersih. SATU
      commit nutup Grup D.

      **Grup C (2026-09-23) -- 3/3 KELAR** (`cve_ticket_service`,
      `cve_email_service`, `cve_export_service`) -- didahuluin diskusi
      desain sama user (3 keputusan konkret, semua dijawab "Recommended"):
      tanggal ticket jadi `Date` asli (bukan string bebas kayak legacy),
      `ticket_id` tetap GLOBAL lintas semua client per bulan (port apa
      adanya), `cve_reported_date` di-drop (readonly di UI lama, gak
      pernah beneran di-override -- selalu derive dari `CveTracker.
      published`).

      **`CveTicket` DIROMBAK TOTAL dari placeholder Fase 2** (`CveTicket`
      1:N `CveTicketItem`, "satu ticket nyakup banyak CVE") -- ketauan
      baca `cve_ticket_service.py` lama: konsepnya SATU record flat per
      (cve_id, client_id), bukan container. `CveTicketItem` di-drop total,
      `CveTicket` jadi 17 kolom (affected_asset/owner_email/remediation_*/
      escalation_required/comments/risk_acceptance/closure_date/
      acknowledged_by/acknowledge_time). `ack_filter` (parameter
      list/stats lama yang di-skip pas Fase 7.3 karena nunggu ini) SEKARANG
      jalan lagi, subquery lawan `cve_tickets.acknowledged_by`.

      **1 fungsi mailer di-generalize, bukan diduplikat** --
      `cti_alerts.mailer.send_newsletter_email` (Bagian 4) namanya diganti
      `create_graph_draft` (logic-nya 100% generic, gak ada yang
      newsletter-spesifik) biar `cve_email.py` bisa numpang langsung,
      bukan nyalin ulang ~40 baris logic Graph API. Satu-satunya caller
      lama (`newsletter.py`) ikut di-update, gak ada perubahan perilaku.

      **1 bug DITEMUKAN & DIPERBAIKI di export, bukan port apa adanya** --
      `cve_export_service.export_cves_to_excel()` legacy TIDAK PERNAH
      nge-scope `client_id` sama sekali (query CVE maupun query false-
      positive), beda dari SEMUA endpoint lain di router yang sama yang
      konsisten pakai `effective_client_id()`. Di multi-tenant beneran
      ini kebocoran data lintas client. Diperbaiki: di-scope `client_id`
      (lihat docstring `cti_api.services.cve_export`).

      **1 asimetri legacy DIPERTAHANKAN, didokumentasikan eksplisit** --
      `cve_export_service.py` filter tanggal di `detected_on`, sedangkan
      `cve_service.py` (list/stats) filter `published` -- ini asimetri
      yang UDAH ADA di kode lama sendiri (bukan penyimpangan baru dari
      porting), jadi `AsyncCveTrackerRepo.list_for_export()` sengaja jadi
      method terpisah dari `list_filtered()`/`get_stats()`, bukan numpang
      `_apply_filters()` yang sama.

      Dependency baru `openpyxl` (`apps/api`). Template `CVE_Tracker_
      template.xlsx` + `cve_notification_email.html` disalin ke
      `apps/api/src/cti_api/templates/`. 3 panggilan LLM (`_llm_cve_
      validator`/`_dedup_mitigation`/`_dedup_risk_context`) port apa
      adanya (prompt verbatim), dibungkus `asyncio.to_thread()` (bukan
      `run_in_executor` legacy -- API sama, `to_thread` modern).

      **Verified LIVE terhadap dev DB real** (uvicorn lokal, Postgres+
      Redis via `localhost`): `next-ticket-id` (CTI-2026-09-001, generate
      bener), `PUT`/`GET /{cve_id}/ticket` (round-trip field remediation
      lengkap), `acknowledge`/`bulk-acknowledge`/`ack-statuses` (3 CVE
      real diacknowledge, status kebaca bener), `ack_filter=acked|unacked`
      di list DAN stats (angka cocok), `GET /export` (download xlsx
      beneran, 4 baris CVE real + ticket ID/severity/score/affected_asset
      semua kecantol bener di kolom yang tepat). Data ticket sintetis
      DIBERSIHIN abis verifikasi (`DELETE FROM cve_tickets`).

      **`POST /draft-email` SENGAJA BELUM live-tested** -- 3 panggilan
      LLM beneran (cost token) + bikin draft ASLI di mailbox Graph yang
      dikonfigurasi `.env` -- keputusan user (2026-09-23): cukup mocked
      integration test (3 test, `_llm_cve_validator`/`_dedup_mitigation`/
      `_dedup_risk_context`/`create_graph_draft` di-patch) buat sekarang,
      **live-test endpoint ini dicatat sebagai TODO sebelum deploy ke
      production** -- jangan anggap fitur ini "fully verified" sampai itu
      kejadian.

      30 test baru (2 file unit murni + 4 file integrasi Postgres real,
      LLM/Graph di-mock buat `cve_email`). Full suite: **951 passed**,
      mypy 131 file bersih, ruff bersih. SATU commit nutup Grup C.

      **Grup A (2026-09-23) -- KELAR, nutup Fase 7.4 seutuhnya**
      (A+B+C+D+E semua beres). Didahuluin 1 keputusan arsitektur
      (`AskUserQuestion`, dijawab "Recommended"): komputasi TF-IDF/
      sklearn taruh LANGSUNG di `apps/api` (bukan Celery worker),
      konsisten sama presedan `dedup_service` (Grup D) -- CPU-bound
      dibungkus `asyncio.to_thread()`, bukan diproses di worker
      terpisah.

      **Temuan arsitektur paling penting sesi ini: `cluster_service.py`
      itu DUA PIPELINE INDEPENDEN, bukan satu.** `get_clusters()`
      (Pipeline 1: greedy TF-IDF fixed-centroid, threshold default
      0.35, PERSISTED ke tabel `clusters` + cache in-process 900s) dan
      `get_recent_campaigns()` (Pipeline 2: union-find TF-IDF,
      threshold FIXED 0.75 -- gak bisa diubah caller, NEVER di-cache/
      di-persist, dihitung ulang tiap call, enrichment jauh lebih kaya:
      severity scoring, CVE prioritization, diamond model, kill chain,
      PIR matching, campaign links, geopolitical feed). Dua fungsi ini
      keliatan mirip dari nama tapi beda total secara algoritma DAN
      beda konsumen -- distinction ini yang nentuin seluruh layout file
      port-nya (`cluster.py` = Pipeline 1, `campaign.py` = Pipeline 2,
      5 service lain jadi shared building block: `cluster_tokenize.py`,
      `campaign_analysis.py` [kill chain + campaign links + severity
      factors], `cve_priority.py`, `diamond_model.py`, ditambah 2
      consumer `campaign_trend.py`/`geopolitical.py`).

      **Skema baru: tabel `clusters`** (`cluster_id` unik, `cluster_
      name`, `first_seen`/`last_seen` [Date asli], `last_count`/
      `peak_count`, `daily_counts` JSONB list -- dipangkas 90 hari
      kebelakang tiap upsert). Cuma buat Pipeline 1 (Pipeline 2 gak
      pernah nulis DB sama sekali, sesuai desain lama).

      **4 repo method baru** (dipakai sekali doang tapi genuinely gak
      ada sebelumnya): `AsyncIOCRepo.list_by_article_ids`/`list_by_ids`
      (nyatuin 2 jalur ekstraksi CVE-mention lama jadi 1 query lewat
      `IOC.type="cve"` + reverse lookup `IOCSource.article_id`),
      `AsyncPIRRepo.list_active_by_client` (beda dari `list_active_
      unscoped` yang udah ada), `AsyncTARepo.list_all_names`,
      `AsyncSourceReliabilityRepo.list_low_reliability_source_names`.
      Method yang SEMANTIKNYA udah persis sama yang ada (TA profile,
      CVE criticality, tech stack) numpang langsung, gak dibikin
      duplikat.

      **1 param mati DIBUANG** -- `cve_priority_service.prioritize_
      campaign_cves()`'s `campaign_context: dict` dibaca lengkap,
      TERNYATA gak pernah dipakai sama sekali di badan fungsi manapun.
      Beda dari "diam-diam ubah perilaku" (efeknya nol baik dibuang
      maupun dipertahankan) -- didrop, dicatet eksplisit di docstring.

      **1 bug DITEMUKAN, SENGAJA DIPERTAHANKAN (bukan diperbaiki
      diam-diam)** -- `mindmap.py`'s `build_cluster_mindmap()` baca
      field-field yang cuma ada di output Pipeline 2 (severity/diamond
      model/kill chain) padahal manggil Pipeline 1 (`get_clusters()`,
      gak punya field itu) -- 6 branch mindmap (Adversary/Capability/
      Infrastructure/Victim Industries/Victim Countries/CVEs) SELALU
      kosong di produksi, cuma "Stats" yang keisi. Ini bug lama yang
      genuinely ada di kode legacy. Diport APA ADANYA (gak dibenerin)
      karena benerinnya butuh KEPUTUSAN PRODUK (pindah ke Pipeline 2 --
      ubah semantik "mindmap dari cluster ID stabil, persisted" jadi
      "dari campaign yang cuma idup pas dihitung", atau nambahin field
      yang hilang ke Pipeline 1 -- ubah kontrak `clusters` table),
      bukan keputusan porting yang bisa diambil sepihak. Didokumentasikan
      panjang di docstring `mindmap.py` + di-assert eksplisit di test
      (`test_build_cluster_mindmap_stats_branch_populated` verifikasi
      branch header yang HARUSNYA muncul emang gak muncul).

      **1 bug DITEMUKAN & DIPERBAIKI (beda dari kasus mindmap di
      atas)** -- `recap.py`'s `_collect_campaigns()` (producer) dan
      `_build_user_message()` (consumer prompt LLM "active campaigns")
      pakai nama field yang GAK NYAMBUNG (`theme` vs yang diharapkan
      consumer, dst) -- akibatnya section itu di prompt LLM SELALU
      nunjukin placeholder "(unlabeled) — 0 articles", walau campaign
      beneran ada. Beda dari kasus mindmap: ini bukan pilihan
      desain/pipeline, cuma nama key yang salah ketik/gak sinkron --
      di-fix jadi rename key yang unambiguous, dites eksplisit
      (`test_collect_campaigns_maps_fields_for_build_user_message`)
      supaya gak pernah balik lagi.

      **4 titik "unlock" ke-wire semua**: `newsletter`'s
      `include_clusters` (query Pipeline 2, map ke bentuk field legacy,
      top 5), `mindmap`'s builder `"cluster"` (baca Pipeline 1, bug di
      atas dipertahankan), `exec_dashboard`'s `recent_clusters_
      summary` (dari stub `[]` jadi query Pipeline 2 real, try/except
      jaga-jaga), `recap`'s `active_campaigns` (bug fix di atas).
      Plus endpoint baru: `intelligence.py`'s `GET /clusters` +
      `/clusters/recent` + `/clusters/evolution` + `/clusters/{id}/
      trends` + `/intelligence/geopolitical`, dan `cve.py`'s
      `GET /prioritize`.

      8 file service baru (`cluster_tokenize`/`cluster`/`campaign_
      analysis`/`cve_priority`/`diamond_model`/`campaign`/`campaign_
      trend`/`geopolitical`), 80 test baru (42 unit murni + sisanya
      integrasi Postgres real + wiring 4 unlock point). Full suite:
      **1031 passed**, mypy 184 file bersih, ruff bersih.

      **Verified LIVE terhadap dev DB real** (uvicorn lokal, data asli
      -- 20 artikel real bertanggal, termasuk konten threat-intel
      genuine APT41/Philippines, BREEZE COMET, UNC6671 dari Mandiant/
      GBHackers): `GET /clusters` (Pipeline 1, `days=90`) NEMU 1
      cluster REAL dari data asli (2 artikel Mandiant UNC6671/Russia-
      targeting yang emang mirip topiknya, confidence "low" -- bukan
      data sintetis yang disuntik), `/clusters/evolution` +
      `/clusters/{cluster_id}/trends` jalan lawan cluster real itu,
      `/intelligence/geopolitical` (kosong, valid -- Pipeline 2 emang
      gak nemu campaign yang lolos threshold 0.75 di dataset ini),
      `GET /cve/prioritize` lawan 4 CVE real dari `cve_tracker` (skor
      terurut bener, termasuk kasus unknown-CVE dapet default 20/low),
      `exec-dashboard-v2?role=analyst` (`recent_clusters_summary` key
      ada, kosong -- konsisten sama Pipeline 2 gak nemu campaign),
      `mindmap/cluster/{id}` (404 bersih -- cluster real ini di luar
      window `days=30` yang di-hardcode `mindmap.py`, port apa adanya
      dari legacy, BUKAN bug baru). **Cluster row hasil komputasi real
      di atas SENGAJA DIBIARKAN** di tabel `clusters` (bukan data
      sintetis yang disuntik, dihitung dari artikel asli yang emang
      ada di DB) -- presedan sama kayak Grup D's "confidence recompute
      dibiarkan nempel di 38 artikel real".

      **`newsletter`'s `include_clusters=true` SENGAJA BELUM live-
      tested** -- baru ketauan pas nyoba: `/newsletter/preview` juga
      manggil LLM client asli (summarization), sama kelas biaya kayak
      `POST /draft-email` Grup C. Panggilan yang kepalang jalan
      di-KILL manual pas retry macet (belum sempat ngirim token dalam
      jumlah besar) -- wiring `include_clusters` divalidasi lewat
      mocked integration test aja (`test_newsletter_clusters.py`, 2
      test, `campaign_service.get_recent_campaigns` di-patch). Sama
      logika kayak `draft-email`: **live-test endpoint LLM-consuming
      ini (newsletter preview/draft-email DAN `recap generate`, yang
      juga kepanggil `get_llm_client()`) dicatat jadi TODO bareng
      sebelum deploy ke production**, jangan dianggap "fully verified"
      sebelum itu kejadian.

      SATU commit nutup Grup A, sekaligus nutup Fase 7.4 seutuhnya
      (Grup E udah diputus keluar scope sejak survei 2026-09-19, gak
      butuh kerjaan lagi). Lanjut **7.5** (buang duplikasi sisa: pkg_
      vuln/cve_email/ioc/llm client), **7.6** (snapshot test tiap
      endpoint), **7.7** (ekspor skema OpenAPI), **7.8** (5 loop jadi
      Celery beat) -- belum dimulai, nunggu arahan user.
- [x] **7.5** Buang duplikasi (pkg_vuln, cve_email, ioc, llm) --
      **(2026-09-23) audit 4 item, 1 genuinely butuh kerjaan.**
      Catatan lama (Bagian 7.2, "IOC+LLM udah disatukan Fase 5") jadi
      STALE tanpa disadari: bener SAAT ditulis (`cti_enrich` cuma satu
      salinan), tapi begitu `apps/api` lahir (Fase 7.3) dengan exit
      criteria "gak ada import `cti_scraper`/`cti_enrich` dari API",
      LLM client harus di-duplikat ULANG (`cti_api.services.llm_client.
      py`, ~15 baris, versi sempit) buat 5 service yang butuh -- gap
      baru yang gak ke-cover catatan lama. `ioc` udah kena masalah SAMA
      lebih dulu dan UDAH dibenerin (Fase 7.3 Bagian 4, relokasi
      `cti_core.ioc.extractor`) -- pattern-nya identik, cuma belum
      diterapkan ke `llm`.

      **Hasil audit 4 item:**
      - **`ioc`** -- KELAR dari Fase 7.3 Bagian 4, diverifikasi ulang,
        gak ada kerjaan.
      - **`pkg_vuln`** -- KELAR dari Fase 4 (`pkg_vuln.py` satu
        implementasi, gak ada fork tersisa), diverifikasi, gak ada
        kerjaan.
      - **`cve_email`** -- KELAR dari Grup C (Fase 7.4), satu template
        (`cve_notification_email.html`), diverifikasi, gak ada kerjaan.
      - **`llm`** -- GENUINELY DUPLIKAT, dikerjain sesi ini (lihat
        bawah).
      - *(bonus, di luar 4 item yang disebut plan tapi ada di §6 asli)*
        **`send_alert`** (Telegram) -- juga udah KELAR dari Bagian 4
        (`cti_alerts.telegram.send_alert()`, satu fungsi gantiin 14).

      **`llm` -- relokasi `cti_enrich.llm.client` → `cti_core.llm.
      client`**, persis presedan `cti_core.ioc.extractor`: modul ini
      dari awal ZERO dependency internal `cti_enrich` (cuma
      `cti_core.config` + `openai` + stdlib), jadi mekanis murni buat
      dipindah. `apps/api`'s duplikat sempit (`cti_api.services.
      llm_client.py`) DIHAPUS TOTAL, 5 caller-nya (`ta_profile`/
      `exec_brief`/`cve_email`/`newsletter`/`recap`) import langsung
      dari `cti_core.llm.client`, sama kayak 2 caller internal
      `cti_enrich` (`stages/classify.py`/`stages/extract_ttps.py`).
      `openai>=1.30` ditambahin ke dependency `cti-core`.

      **Bonus correctness fix, ketauan gara-gara audit ini (bukan yang
      dicari dari awal):** 6 titik parsing JSON-dari-LLM di `apps/api`
      (`cve_email.py` x2, `newsletter.py` x2, `ta_profile.py` x1,
      `recap.py`'s `_extract_json`) SEMUANYA re-implementasi terpisah,
      dan 5 dari 6 (semua kecuali `recap.py`) cuma `json.loads(content
      or "{}")` POLOS -- gak nahan `<think>...</think>` preamble atau
      code-fence markdown, padahal edge case itu UDAH KEBUKTIAN
      kejadian beneran lawan dev gateway (dicatat di docstring
      `parse_json_response()` sejak Fase 5). Kelima titik itu rawan
      `JSONDecodeError` gak ketangkep kalau gateway kebetulan mbalikin
      salah satu bentuk itu. Diganti semua numpang `cti_core.llm.
      client.parse_json_response()` -- pola `parse_json_response(content
      or "{}")` (bukan `parse_json_response(content)` polos) dipilih
      biar behavior identik lawan kode lama buat kasus falsy
      (`raw or "{}"` sebelumnya, sekarang `parse_json_response("{}")`
      == `{}` juga). `recap.py`'s `_extract_json()` beda kasus -- dia
      PUNYA kontrak sendiri (gak pernah raise, fallback `{"_raw": raw}`
      yang dipakai `generate_daily_recap()` mutusin nyimpen `raw_llm`
      atau kagak), jadi BUKAN diganti langsung, tapi dibungkus try/
      except di sekitar `parse_json_response()` -- kontrak lama tetap
      sama persis, cuma sekarang IKUT dapet proteksi `<think>`-block
      yang sebelumnya gak ada di situ juga.

      18 test baru: `tests/unit/test_llm_client.py` (13 test --
      `parse_json_response`/`get_llm_client`/`store_param`, belum
      pernah ada test khusus sebelum ini walau dipakai 7 caller),
      `tests/unit/test_recap_extract_json.py` (5 test, verifikasi
      kontrak fallback `_extract_json` gak berubah pasca refactor).
      Full suite: **1049 passed** (dari 1031), mypy 183 file bersih
      (turun dari 184 -- 1 file duplikat kehapus), ruff bersih.
- [x] **7.6** Snapshot test tiap endpoint -- **(2026-09-23/24) 27/27
      router, 179 endpoint, 183 test baru (`syrupy`).**

      **Pola infra baru, gak ada presedennya sebelum ini** -- SEMUA test
      integrasi sebelumnya manggil fungsi service/repo LANGSUNG lewat
      `async_db_session` (skip router: routing, dependency injection
      auth, validasi Pydantic, `response_model` serialization gak pernah
      kena test). Fase ini nambah `api_client`/`api_session` (`tests/
      integration/conftest.py`) -- `httpx.AsyncClient` + `ASGITransport`
      langsung ke `create_app()`, `get_db` di-override numpang session
      yang sama, request BENERAN lewat HTTP.

      **3 masalah infra ketemu & dibenerin sebelum bisa dipercaya:**
      1. Router SERING manggil `session.commit()` sendiri (pola "unit of
         work per request") -- `AsyncSession(bind=connection)` polos
         bakal KETUTUP beneran kena commit, isolasi rollback-per-test
         jadi gak ngefek. Fix: `join_transaction_mode="create_savepoint"`
         (recipe resmi SQLAlchemy 2.0).
      2. `expire_on_commit=False` WAJIB dipasang di session test itu juga
         -- production (`cti_core.db.engine`) udah pasang ini, dan tanpa
         itu akses attribute abis commit (`entry.id` di `iocs.py`) trigger
         `MissingGreenlet` yang ketubruk event listener savepoint di atas.
         Ketauan lewat reproduksi langsung, bukan dugaan.
      3. **6 service (`cluster`/`article_dashboard`/`risk_matrix`/
         `fp_analytics`/`spike`/`d3fend`) punya cache in-process module-
         level (900s TTL)** -- dirancang buat produksi (satu proses long-
         lived), tapi bikin test SALING NUMPANG hasil basi kalau dua test
         beda manggil endpoint yang sama dengan parameter default yang
         sama. Ketauan pas full-suite run: 2 test Fase 7.6 sendiri DAN 1
         test PRA-ADA (`test_mindmap_query.py`) sama-sama kena. Fix:
         fixture `autouse=True` (`_clear_in_process_caches`,
         `conftest.py`) yang clear SEMUA 6 cache itu sebelum tiap test
         integrasi -- proteksi nutup seluruh suite, bukan cuma titik yang
         kebetulan ketauan gagal.

      **Endpoint eksternal (LLM/Graph/osv.dev/D3FEND/MITRE GitHub) di-
      mock di titik yang SAMA kayak test service-layer yang udah ada**
      (`cve_lookup._fetch_cisa_kev` dkk, `pkg_vuln._package_exists_on_
      registry`, `AsyncAttackSyncRepo.sync_domain`, `ta_profile._call_llm`,
      `exec_brief._call_llm`, `recap._call_llm`, `newsletter._enrich_
      articles`, `mitre.get_d3fend_countermeasures`) -- gak ada panggilan
      jaringan asli dari test manapun di fase ini. `BackgroundTasks`
      FastAPI (`attack.py`/`pkg_vuln.py`) KETAUAN beneran ke-`await`
      SEBELUM `httpx.ASGITransport` balikin response (efektif sinkron di
      test), jadi endpoint-nya bisa dites langsung tanpa perlu nunggu.

      **Field non-deterministik dinormalisasi lewat `syrupy.matchers.
      path_type`** (diganti placeholder TIPE, bukan dihapus dari
      perbandingan -- drift shape/tipe tetap ketahuan): `id` auto-
      increment (Postgres SEQUENCE gak ke-reset rollback transaksi test,
      jadi nilai literalnya gak pernah stabil lintas run/urutan test),
      field lain yang JUGA int tapi namanya bukan `id` polos (`article_id`,
      `pir_id`, dst -- ketauan lewat full-suite run, pattern awal `id$`
      cuma nangkep field bernama PERSIS "id") timestamp wall-clock
      (`last_updated`/`generated_at`/dst), dan `ticket_id`/next-ticket-id
      (nempel bulan-tahun kalender asli, presedan dari cve.py duluan).

      **1 bug non-determinism GENUINE ketemu di kode APLIKASI (bukan
      test)**: `cluster_service`'s field `sources` di respons `/api/
      clusters` dibangun dari Python `set` (unik doang, gak di-sort) --
      urutan iterasi `set` string di-randomize per PROSES Python
      (`PYTHONHASHSEED`), jadi 2 run `pytest` beda bisa ngasih urutan
      `sources` yang beda walau isinya sama. Bukan dibenerin di kode
      (di luar scope minimal Fase 7.6), tapi dinormalisasi di level test
      (`sorted()` sebelum dibandingin) -- dicatat di sini biar gak
      ketebak lagi kalau nanti nyari root cause snapshot yang "kadang
      beda kadang enggak".

      **1 bug pra-ada, TIDAK terkait Fase 7.6, ketemu gak sengaja**:
      `test_recap_service.py::test_collect_iocs_and_cves_and_new_tas`
      pakai `datetime.date.today()` (timezone LOKAL mesin, WIB/UTC+7 di
      dev environment ini) buat filter kolom yang di-stamp Postgres
      `server_default=func.now()` (UTC) -- flaky tiap hari jam 00:00-
      07:00 WIB (tanggal lokal udah besok, UTC masih hari ini). Bukan
      regresi dari Fase 7.6 (kejadian juga kalau file itu dites sendirian,
      gak connect ke perubahan apa pun di sini) -- di-flag jadi task
      terpisah (`task_a3ad146d`), BUKAN dibenerin di sini (scope beda).

      Endpoint yang genuinely gak cocok snapshot literal: export biner
      (`GET /api/cve/export`, `/api/pir/{id}/export/docx`) dites lewat
      assert struktur (header/kolom/row-count), bukan byte mentah;
      `changelog.py` baca `CHANGELOG.md` ASLI dari disk (isinya SENGAJA
      berubah tiap rilis) dites lewat assert struktur juga, bukan
      snapshot literal yang bakal basi tiap entry baru ditambah.

      Full suite abis semua ini: **1231 passed** (dari 1049 sebelum Fase
      7.6, +183 -- 1 pra-ada yang flaky di atas gak dihitung, bukan
      kegagalan baru), mypy 28 file test bersih, ruff bersih. Determinism
      diverifikasi lewat run ulang berkali-kali (per-file, gabungan
      27 file, DAN full suite project) -- bukan cuma "generate sekali terus
      percaya".
- [x] **7.7** Ekspor skema OpenAPI

      `tools/export_openapi.py` -- panggil `create_app().openapi()`
      (murni introspeksi route/Pydantic model, GAK connect ke Postgres/
      Redis beneran) terus tulis ke `docs/openapi.json` (di-commit ke
      git, bukan `.gitignore` -- diff-nya kelihatan di code review tiap
      kali kontrak endpoint berubah). Ini yang bakal dibaca
      `openapi-typescript` buat generate client TypeScript pas Fase 8
      (`apps/web`, plan §9) -- drift frontend-backend ketahuan saat
      compile, bukan pas runtime.

      **Satu keputusan kecil**: `create_app()` butuh `Settings` valid
      buat kebentuk (`FastAPI(...)` + router registration), dan 4 field
      `database.url`/`sync_url`/`auth.jwt_secret`/`session_secret_key`
      gak punya default (`cti_core.config`, sengaja -- container app
      beneran WAJIB gagal start kalau kosong). Skrip ini `os.environ.
      setdefault(...)` 4 placeholder (gak pernah kepake buat I/O asli,
      cuma biar validasi Pydantic lolos) SEBELUM import `cti_api.main`
      (yang punya `app = create_app()` di level modul) -- jadi jalan di
      mana aja, dev lokal TANPA `.env` maupun CI TANPA testcontainer,
      gak butuh secret apa pun.

      Jalanin: `uv run python tools/export_openapi.py` -> **156 path**
      ke-export, `openapi` 3.1.0, `info.title`/`version` kebaca dari
      `create_app()`. Test unit (`tests/unit/test_export_openapi.py`,
      2 test -- shape schema + JSON-serializable) gak butuh Postgres,
      lolos di CI job `test` biasa tanpa perubahan workflow.

      **3 bug flaky full-suite kesenggol pas verifikasi Fase 7.6
      (bukan bagian 7.7 langsung, tapi ketemu re-run full suite abis
      fix timezone `task_a3ad146d`) udah dibenerin di commit `1e32357`
      sebelum item ini**: 2 snapshot ke-bake tanggal literal
      (`test_recap_router_snapshot.py`'s `date`, `test_stix_router_
      snapshot.py`'s `valid_from`/`x_last_seen`) + 1 `SELECT DISTINCT`
      tanpa `ORDER BY` (`list_all_distinct_cve_ids`, `test_cve_router_
      snapshot.py::test_bulk_exploit_lookup`) -- lihat commit message
      buat detail lengkap, gak diulang di sini.

      Full suite abis 7.7: **1234 passed** (dari 1232 abis fix di atas,
      +2 test baru), mypy+ruff bersih, diverifikasi 2x berturut-turut.
- [x] **7.8** *(dipindah dari 6.6)* Pindahkan 5 loop `ScraperNewsWeb/app/main.py`
      (PIR alert, ATT&CK sync, IOC decay, daily recap, CVE enrichment) jadi
      Celery beat task.

      **5 loop -> 6 task**: `_pir_alert_loop` lama (satu loop, dua interval
      P1/P2+ internal, dedup pakai GLOBAL `_alerted_urls`/`_alerted_date`
      in-process) dipecah jadi `pir.check_p1_alerts` (tiap 5 menit) +
      `pir.check_all_alerts` (tiap 15 menit, exclude P1) -- masing-masing
      partisi PRIORITY-nya sendiri (gak overlap window), TANPA state
      in-process sama sekali: `Article.created_at >= since` (kolom BARU,
      bukan `posted_on`) yang jadi kebenaran "baru sejak tick terakhir",
      bukan set dedup yang gak aman lintas worker/restart (persis masalah
      struktural yang jadi alasan revamp ini -- lihat plan). 4 loop
      lainnya 1:1 jadi 1 task masing-masing, jam tetap (04:00/06:00 UTC,
      tiap 3 jam) HARDCODED port apa adanya dari `_seconds_until_04h_utc()`
      dkk lama (gak pernah env-configurable), PIR P1/all-interval DAN
      ATT&CK sync interval pindah ke `Settings.worker` (field baru,
      `WorkerSettings`, `packages/cti-core/src/cti_core/config.py`).

      **3 fungsi service BARU** (logic-nya emang belum pernah diport --
      router `pir`/`iocs`/`attack` docstring-nya sendiri udah nyebut item
      ini "belum diport, masuk 7.8"):
      - `cti_api.services.pir_alert.check_new_articles_vs_pirs()` --
        reuse `AsyncPIRRepo.list_articles_for_pir()` yang UDAH ada
        (`_criteria_filters`), cuma nambahin parameter `created_at_start`
        yang di-plumbing sampai ke `_apply_list_filters()`
        (`AsyncArticleRepo`, SATU sumber filter artikel, bukan query
        builder terpisah -- pola yang sama kayak `ttps` sebelumnya).
      - `cti_api.services.ioc_decay.decay_sweep()` -- repo method baru
        `AsyncIOCRepo.list_needing_decay()`, iterasi loop-sampai-kosong
        (bukan Mongo bulk_write 500/batch lama), tiap IOC lewat
        `confidence.recompute_ioc_confidence_and_actionability()` yang
        UDAH ada (dipakai endpoint feedback juga -- satu sumber logic).
      - `cti_api.services.attack_sync_check.sync_if_needed()` -- `_needs_
        sync()` (pure function, gampang ditest) + `AsyncAttackSyncRepo.
        get_sync_status()`/`sync_all_domains()` yang UDAH ada dari Fase
        7.3 Bagian 3, cuma keputusan "kapan" yang belum ada.

      **2 fungsi EXISTING langsung dipakai (session-first, "FONDASI 7.8"
      sesuai catatan pas dibangun)**: `cve_lookup.run_cisa_kev_lookup`/
      `run_epss_lookup`/`run_exploit_db_bulk_lookup` (Fase 7.4 Grup B) dan
      `recap.generate_daily_recap` (Fase 7.3 Bagian 5, dipanggil `date=None`
      sama kayak lama).

      **Keputusan arsitektur: `cti-worker` sekarang depend ke `cti-api`**
      (`apps/worker/pyproject.toml`). Semua fungsi di atas `AsyncSession`-
      first (ditulis buat FastAPI), task Celery sendiri fungsi SYNC biasa
      -- daripada nulis ulang jadi versi sync (duplikat logic bisnis),
      task manggil LANGSUNG lewat `asyncio.run()`. Belum ada image Docker
      terpisah worker/api (plan §10 belum dikerjain) jadi belum ada beban
      nyata dari `fastapi`/`playwright`/`scikit-learn` ikut ke image
      worker -- dicatat sebagai hal yang perlu di-revisit kalau/pas image
      dipisah beneran.

      **1 bug GENUINE ketemu pas verifikasi LIVE (bukan test), bukan
      dugaan**: engine/sessionmaker async `cti_core.db.engine` di-
      `@lru_cache` SEKALI per PROSES (didesain buat FastAPI -- satu event
      loop uvicorn yang idup terus). Di worker Celery yang manggil
      `asyncio.run()` BERULANG (task beda-beda, tick beda-beda, satu
      proses worker yang sama), event loop LAMA ketutup begitu
      `asyncio.run()` kelar, tapi engine cache-nya nyangkut ke situ --
      panggilan `asyncio.run()` BERIKUTNYA (task lain) pecah
      `RuntimeError: Event loop is closed` / "attached to a different
      loop" pas nyoba pakai koneksi yang keiket ke loop mati. Reproduksi
      LIVE: dispatch manual `ioc.decay_sweep` lalu `cve.enrichment_sweep`
      ke worker Celery beneran (`--pool=solo`, Redis+Postgres dev
      container) -- CISA KEV lookup pecah PERSIS gini, Exploit-DB/EPSS
      (jalan setelahnya, kebetulan gak butuh session BARU di titik yang
      sama) tetep sukses. Fix: `_run_async()` (`tasks/periodic.py`) --
      wrapper `asyncio.run()` yang manggil `reset_engines()` (SUDAH ada,
      dipakai fixture test buat alasan serupa) di `finally`, jadi
      panggilan berikutnya bikin engine baru di loop barunya sendiri.
      Diverifikasi ulang urutan yang SAMA PERSIS abis fix -- `cve.
      enrichment_sweep` sukses penuh (CISA KEV+Exploit-DB+EPSS
      semua jalan, `catalog_size: 1721`).

      **Verifikasi LIVE end-to-end** (worker Celery beneran, `--pool=
      solo`, Redis+Postgres dev container lewat `docker compose`, BUKAN
      testcontainer efemeral): `ioc.decay_sweep` -- 92/92 IOC di DB dev
      ke-decay bener. `attack.sync_check` -- correctly SKIP (3 domain
      semua masih fresh dari sync live Fase 7.3). `cve.enrichment_sweep`
      -- CISA KEV/Exploit-DB/EPSS ketiganya jalan lewat API eksternal
      ASLI (bukan mock), data ke-tulis ke Postgres dev. **`pir.check_*`/
      `recap.generate_daily` SENGAJA GAK di-live-dispatch** -- `.env` dev
      punya kredensial Telegram+LLM ASLI, risiko kirim alert Telegram
      beneran / kena biaya API LLM kalau ada PIR+artikel yang kebetulan
      cocok; cukup diverifikasi lewat integration test (mocked) + bukti
      mekanisme `_run_async` yang sama udah kebukti benar di 2 task lain.

      11 test baru (`test_pir_alert_service.py` 5, `test_ioc_decay_
      service.py` 3, `test_attack_sync_check_service.py` 3) -- Postgres
      REAL (testcontainers), `AsyncAttackSyncRepo.sync_domain` di-mock
      (pola sama kayak `test_attack_router_snapshot.py`). Gak ada test
      buat task Celery-nya sendiri (`@app.task(...)` wrapper) -- sama
      pola kayak `scrape.run`/`enrich.article` (Fase 6), diverifikasi
      LIVE bukan lewat unit test.

      Full suite: **1245 passed** (dari 1234 abis 7.7, +11 test baru),
      mypy (`cti-core` strict + `cti-worker`/`cti-api` file yang disentuh)
      bersih, ruff bersih (80 file lain butuh reformat tapi PRA-ADA, gak
      ada satupun file Fase 7.8 -- gak disentuh, di luar scope).

**Exit criteria:** semua endpoint ada snapshot test · gak ada import `cti_scraper`/`cti_enrich` dari API · 5 loop web hilang dari `main.py`, jadi beat task (7.8) -- **SEMUA TERPENUHI**, Fase 7 `[x]` lengkap.

---

## Fase 8 — `apps/web` (Next.js) `[x]`

### Survei frontend lama + urutan kerja (2026-09-24)

Checklist 8.1-8.6 di bawah ini kedengeran kayak 6 kerjaan datar, padahal ini
fase terbesar yang tersisa (4-6 minggu). Sebelum eksekusi, disurvei dulu
28 file JS (11.751 baris) + 14 template Jinja (7.726 baris) legacy
(`legacy/static/js/newsroom/*.js` + `ScraperNewsWeb/templates/`) lewat 4
subagent paralel, cross-check ke 156 endpoint / 27 router API yang udah
ada (`docs/openapi.json`, hasil Fase 7.7). Sama pola kayak survei 56-service
Fase 7.4 -- user minta disurvei dulu sebelum ngoding, bukan langsung gas.

**Temuan yang mengubah asumsi rencana awal (plan §9, 8 route):**

1. **`/intelligence` BUKAN satu halaman** -- `tab_intelligence.html` (944
   baris) punya 11 sub-view internal yang di-switch murni `display:none`
   (TANPA ubah URL sama sekali): News Clusters, Source Reliability, Early
   Warning/Spikes, MITRE Heatmap, ATT&CK DB, PIR, RFI, Threat Actor Room
   (+3 sub-sub-view: Tracked/Whitelist/Watchlist), IOC Management,
   **Campaign Clusters**, Risk Matrix. Rekomendasi: pecah jadi sub-route
   Next.js beneran (`/intelligence/clusters`, `/intelligence/campaigns`,
   dst) -- dapet deep-link/bookmark yang SEKARANG gak bisa, plus code-
   splitting otomatis (±4700 baris JS logic di area ini doang).
2. **Newsletter itu GAP nyata** -- gak ada di 8 route awal, padahal
   `newsletter.html` (1261 baris) halaman STANDALONE (route `/newsletter`
   sendiri di app lama, bukan tab), backend-nya (`newsletter.py`,
   `mindmap.py`) UDAH lengkap ke-port dari Fase 7.3. Skala sebanding
   `exec.js` (composer 4-section + history drawer + editor mindmap
   Mermaid). Ditambahin jadi route ke-9.
3. **Pkg Vuln BUKAN gap** -- `tab_pkgvuln.html` udah nested DI DALAM tab
   CVE Tracker di app lama (submenu "Pkg Vuln" vs "Tech Stack Vuln"), jadi
   tetap masuk `/cve` (nested), bukan route terpisah. Konsisten sama 8
   route awal, bukan revisi.
4. **`/cve` 3 level nested tab**: `/cve` -> Tech Stack Vuln (default) /
   Pkg Vuln, masing-masing punya sub-tab lagi (CVEs/Tech Stack,
   Vulnerabilities/Packages). File tunggal terkompleks di SELURUH
   frontend lama (`cve.js` 1284 baris): bulk action dengan business rule
   lintas-baris (draft-email cuma aktif kalau semua row tech sama), ticket
   workflow 15+ field, 3 lookup eksternal (CISA/EPSS/exploit-db), export
   Excel, embed mindmap inline.
5. **2 endpoint belum diport** (tombol bakal 404 kalau di-port apa
   adanya): `POST /api/techstack/{id}/backfill-historical` +
   `POST /api/techstack/backfill-cves` -- docstring `techstack.py` sendiri
   udah nyebut ini sengaja gak diport (trigger NVD/MITRE, cascade-delete
   lintas-client). Perlu keputusan produk: hidupin lagi backend-nya, atau
   drop tombolnya di rewrite.
6. **`/api/scraper/health` juga belum diport** -- `health.py` baru
   docstring-nya sendiri bilang ini Fase 9 punya, bukan Fase 8. Blocking
   sebagian widget Scraper Health di `/dashboard` (accept-rate chart +
   tabel per-script) sampai itu ada.
7. **Kontrak `/api/iocs/feedback` BERUBAH** -- `exec.js` manggil bentuk
   lama `POST /api/iocs/feedback` (body `{ioc_type, value,
   is_true_positive}`), backend baru `POST /api/iocs/{ioc_id}/feedback`
   (body `{verdict, note}`). Bukan blocker (endpoint-nya ADA), tapi bukan
   port literal -- widget FP-vote di Exec Dashboard perlu ditulis ulang
   melawan kontrak baru.
8. **`scraper.js` BUKAN control plane** -- namanya menyesatkan, isinya cuma
   2 widget MONITORING read-only (Scraper Health di `/dashboard`, MITRE
   Heatmap di `/intelligence`), gak ada start/stop/pause/schedule/config
   sama sekali. Fase 9 ("control plane scraper" beneran) GAK PUNYA
   preseden kode buat di-port -- desain dari nol, bukan port.
9. **Tanpa framework CSS** -- gak ada Bootstrap/Tailwind, cuma 1627 baris
   `&lt;style&gt;` inline custom (dark theme GitHub-ish + font "Share Tech
   Mono"/"Rajdhani", identitas visual yang cukup khas buat tool CTI).
   Chart.js dipakai di Dashboard/Exec/TA-profile (6+6+1 chart), Mermaid.js
   di Mindmap (dipakai lintas TA Room + Campaign Clusters + Newsletter)
   dan gak ada lib visualisasi lain.
10. **Auth murni Bearer JWT, gak ada session cookie** -- token di
    `localStorage` (`cti_jwt`), header `Authorization: Bearer` +
    `X-Client-ID` (multi-tenant). 3 role (analyst/admin/superadmin,
    `deps.py::require_admin`/`require_superadmin`). CORS backend udah
    disiapin buat browser manggil API langsung (`cors_origins` default
    `http://localhost:3000`) -- BUKAN proxy server-side lewat Next.js,
    jadi client-side fetch langsung ke API adalah arsitektur yang emang
    udah dianggep dari sisi backend.

**Peringkat kompleksitas (gabungan 4 laporan survei, kecil→sangat besar):**

| Kompleksitas | Area | Baris (JS/HTML) | Catatan |
|---|---|---|---|
| Kecil | Changelog (modal global) | 94 | custom md renderer mini, ganti `react-markdown` |
| Kecil | Login | - | form standalone |
| Kecil | Risk Matrix (`/intelligence`) | 90 | tabel + filter client-side |
| Kecil | TTP/D3FEND (shared) | 134 | KECIL kodenya, tapi dipakai lintas MITRE heatmap + modal artikel generik -- taruh di `shared/` |
| Kecil | Recap | 249 | read-mostly, 1 modal konfirmasi |
| Sedang | Dashboard | 191 | 6 chart, blocked sebagian sama gap `/api/scraper/health` |
| Sedang | Source Reliability (`/intelligence`) | 327 | CRUD + autocomplete custom |
| Sedang | X-Intel | 546 | 2 sub-tab + 1 modal, no chart |
| Sedang | Tech Stack (nested `/cve`) | 309 | CRUD tabel, 2 tombol 404 (gap #5) |
| Sedang | News Clusters (`intel.js`, `/intelligence`) | 231 | beda dari Campaign Clusters, nama mirip -- jangan ketuker |
| Besar | PIR + RFI (`/intelligence`) | 453 | 2 fitur CRUD tergabung 1 file |
| Besar | Admin/User Mgmt | 837 | CRUD user+role+client+policy+audit, custom dropdown/picker |
| Besar | ATT&CK DB (`/intelligence`) | 519 | polling 5s, 4 sub-tab paginated |
| Besar | Mindmap (shared, lintas TA/Campaign/Newsletter/CVE-ticket) | 379 | satu-satunya pemakai Mermaid.js, editor+live-preview |
| Besar | IOC Management (`/intelligence`) | 692 | 3 sub-section (tabel+allowlist+FP-analytics) |
| Besar | Exec Dashboard | 869 | 6 chart+heatmap+AI-brief, kontrak IOC feedback beda (gap #7) |
| Besar | Package Vuln (nested `/cve`) | 908+192 | dep-graph+scorecard+lockfile-import, coupling ke modal CVE |
| Besar | Newsroom (gak ada file sendiri) | tersebar | 8 panel paralel (APAC/Global/RW/Indo/TA-watch/Tech-watch + 2 subview) |
| Besar | Newsletter (route BARU) | 1261 | composer+history+editor mindmap, GAP dari rencana awal |
| Besar | CVE Tracker (core) | ~1200 | **terkompleks tunggal** -- ticket 15 field, bulk-action business rule, 3 lookup eksternal |
| Sangat besar | Threat Actor Room (`/intelligence`) | 1103 | 3 sub-view + profile modal masif + Chart.js timeline |
| Sangat besar | Campaign Clusters (`/intelligence`) | 907 | Diamond Model + Kill Chain viz + geopolitical heatmap, semua custom-render tanpa lib |

**Urutan kerja diusulkan (Grup A base dulu, baru per-route, kecil→besar,
`/intelligence` dipecah lagi jadi sub-grup karena sendirian udah ~4700
baris):**

- **Grup A -- Fondasi** (blocking semua grup lain): setup Next.js App
  Router+TS+Tailwind+shadcn/ui (di-tema pakai token dari CSS lama),
  `openapi-typescript` dari `docs/openapi.json`, auth httpOnly-cookie
  (Route Handler login yang taruh JWT ke cookie, Route Handler proxy
  `app/api/proxy/[...path]` yang baca cookie+pasang Bearer buat semua
  panggilan Client Component, Server Component boleh fetch API langsung
  server-side, middleware guard route pakai keberadaan cookie,
  client-switcher, role-gate, lazy-auth-gate -- lihat keputusan #3 di
  atas), API client wrapper (TanStack Query di atas proxy route, buat
  cache/polling), primitif modal/dialog (shadcn Dialog, gantiin 16
  overlay manual), `<Pagination>`/`<ConfirmDialog>`/`<CountryMultiSelect>`
  reusable, modal Changelog (validasi pola modal).
- **Grup B -- Kecil, validasi pola end-to-end**: `/recap`, `/dashboard`
  (nunggu keputusan gap #6 buat widget scraper-health-nya).
- **Grup C -- Sedang, mandiri**: `/xintel`, `/admin/users`.
- **Grup D -- `/newsroom`**: 8 panel paralel, butuh pola panel+pagination
  dari Grup A udah solid.
- **Grup E -- `/cve`**: area terbesar tunggal (core+techstack+pkgvuln),
  ticket workflow, 3 lookup eksternal.
- **Grup F -- `/exec`**: charts+heatmap+brief, includes fix kontrak IOC
  feedback (gap #7).
- **Grup G -- `/intelligence`** (dipecah sub-grup, kecil ke besar): G1
  Risk Matrix+Source Reliability+Early Warning, G2 PIR+RFI, G3 MITRE
  (heatmap+ATT&CK DB), G4 IOC Management, G5 komponen Mindmap (shared,
  dipakai G6/G7/Newsletter/CVE-ticket), G6 Threat Actor Room, G7 Campaign
  Clusters.
- **Grup H -- `/newsletter`**: route baru, numpang komponen Mindmap dari
  G5.

**4 keputusan arsitektur -- DIPUTUSKAN user (2026-09-24):**
1. **Styling: Tailwind + shadcn/ui, di-tema ulang.** Palet warna+font dari
   1627 baris CSS lama diekstrak jadi Tailwind token; komponen aksesibel
   (dropdown/dialog/table) dari shadcn, bukan rebuild manual.
2. **`/intelligence`: sub-route Next.js beneran** (`/intelligence/clusters`
   dst, Threat Actor Room nested lagi `/intelligence/threat-actors/tracked`
   dst) -- sesuai rekomendasi survei, deep-link+code-split.
3. **Auth token: httpOnly cookie** (BUKAN rekomendasi awal -- user pilih
   lebih aman dari XSS ketimbang simpel). **Implikasi buat Grup A**:
   backend cuma nerima `Authorization: Bearer` (gak ada cookie auth sama
   sekali di `deps.py`), jadi arsitektur browser-manggil-API-langsung
   (CORS direct) GAK dipakai buat request yang butuh auth -- Next.js jadi
   proxy (pola BFF): (a) Route Handler login (`app/api/auth/login`) yang
   manggil FastAPI, taruh JWT hasilnya ke httpOnly cookie; (b) Server
   Component boleh fetch API langsung server-side (baca cookie via
   `next/headers`, pasang jadi Bearer header sebelum manggil FastAPI);
   (c) Client Component (mutasi, polling, interaksi) manggil Route
   Handler proxy Next.js sendiri (`app/api/proxy/[...path]`), BUKAN
   FastAPI langsung -- proxy itu yang baca cookie + pasang Bearer;
   (d) middleware Next.js buat guard route (cek cookie ada/nggak sebelum
   render halaman admin/protected). Kerjaan Grup A "API client wrapper"
   nambah satu lapis (proxy route handler), bukan cuma fetch wrapper
   biasa.
4. **`/admin`: tetap 1 route `/admin/users`, tab internal** -- 4 area
   (users/roles/clients/audit) gak dipecah sub-route, sesuai rencana
   awal (areanya emang saling terhubung erat, edit role langsung reload
   user table).

### Grup A -- selesai (2026-09-25)

`apps/web` -- Next.js 16.3.6 (App Router, Turbopack) + React 19 + TS
strict + Tailwind v4 + shadcn/ui. Palet+font (Rajdhani/Share Tech Mono/
IBM Plex Mono) diekstrak dari 1627 baris `<style>` `newsroom.html` lama
ke token Tailwind (`globals.css`) -- app dark-only (`.dark` KELAS TETAP
nempel di `<html>`, gak ada toggle).

**Auth BFF (keputusan #3, httpOnly cookie) lengkap**: `lib/auth/
session.ts` (cookie helper) + 3 Route Handler (`api/auth/login`
taruh `access_token` FastAPI ke cookie, `api/auth/logout` hapus,
`api/auth/me` proxy buat `AuthProvider` populate state client) + proxy
catch-all `api/proxy/[...path]` (baca cookie, pasang `Authorization:
Bearer`+`X-Client-ID`, forward apa adanya termasuk response binary
--`Content-Disposition` diteruskan buat export Excel/DOCX nanti) +
`src/proxy.ts` (guard optimistic, redirect ke `/login?redirect=...` kalau
cookie gak ada -- BUKAN `middleware.ts`, Next.js 16 rename konvensi ini).
`AuthProvider` pakai `useQuery` (bukan `useEffect` manual -- kena lint
`react-hooks/set-state-in-effect`, React 19 baru).

**API client**: `openapi-typescript` generate `lib/api/schema.d.ts` dari
`docs/openapi.json` (`pnpm run gen:api`), `openapi-fetch` client
ke-bind ke `/api/proxy` (browser gak pernah kontak FastAPI langsung).

**Shell**: `AppHeader` (nav 9 route + Changelog + ClientSwitcher +
UserMenu), route group `(app)` buat guard client-side kedua (cookie ada
tapi invalid/expired -- proxy.ts sengaja gak decode JWT). `ChangelogDialog`
jadi vertical-slice validasi PENUH (Dialog+Query+client+proxy+
`react-markdown`, gantiin mini-parser regex lama).

**2 bug Base UI (shadcn migrasi dari Radix, BUKAN dikira) ketemu LIVE**
(browser, bukan cuma typecheck) -- dicatat di `apps/web/CLAUDE.md` biar
gak keulang: (1) `asChild` gak dikenali Base UI, harus `render={<Elem
/>}`, kalau kepake tetap nge-render `<button>` default sendiri di
sekitar child -> nested `<button>` (hydration error); (2)
`DropdownMenuLabel` WAJIB dibungkus `<DropdownMenuGroup>`, beda dari
Radix yang boleh berdiri sendiri.

**Deferred, BUKAN lupa**: `<Pagination>`/`<ConfirmDialog>`/
`<CountryMultiSelect>` generik ditunda sampai Grup B/C butuh beneran
(primitif shadcn `pagination.tsx`/`dialog.tsx` udah ke-install, tinggal
dikomposisi) -- daripada desain API generik tanpa use-case nyata di
tangan. Role-gate per halaman (admin-only dst) juga ditunda ke Grup yang
beneran punya halaman admin, `require_admin` FastAPI tetap jadi
enforcement asli (frontend cuma sembunyiin UI, bukan satu-satunya
lapis).

Verifikasi LIVE end-to-end (browser beneran, bukan cuma `pnpm build`):
login (`admin1`/superadmin) -> dashboard -> nav 9 route render -> buka
Changelog (data asli dari `/api/changelog` lewat proxy) -> user menu ->
logout -> akses `/admin/users` tanpa sesi -> redirect ke `/login?
redirect=%2Fadmin%2Fusers` (proxy.ts guard). Console browser BERSIH
(tab baru, bukan history lama) setelah 2 bug Base UI di atas dibenerin.
`pnpm build`/`tsc --noEmit`/`pnpm lint` semua bersih.

### Grup B -- selesai (2026-09-24)

`/dashboard` + `/recap` (docs/PROGRESS.md urutan kerja: "kecil, validasi
pola end-to-end"). Port `legacy/static/js/newsroom/{dashboard,recap}.js`
+ `tab_{dashboard,recap}.html`, bukan desain baru.

**`/dashboard`**: 2 `useQuery` independen (`/api/dashboard` typed penuh
lewat `DashboardStats`, `/api/ta/stats` -- backend balikin
`dict[str,object]` jadi di-cast ke `TaStats` lokal, field-nya dicek
langsung dari `AsyncTARepo.get_ta_stats()` biar gak nebak) gantiin
`Promise.all` lama -- tiap section render begitu datanya sendiri siap.
`chart.js`+`react-chartjs-2` (dependency baru) buat 8 chart (bar
horizontal/doughnut/line), warna hex LITERAL sama persis kayak
`.dark` block `globals.css` (canvas gak bisa resolve `var(--x)` tanpa
`getComputedStyle`, jadi bukan port yang males, itu keterbatasan teknis).
**Scraper Health widget (accept-rate chart + tabel per-script) SENGAJA
belum diisi** -- `/api/scraper/health` punya Fase 9 (gap #6 survei),
diganti placeholder kartu yang bilang jelas alasannya, bukan endpoint
di-fake atau section dihapus diam-diam.

**`/recap`**: toolbar (date picker + Load/Generate/Force Regen) + grid
2 kolom (history sidebar + body). `RecapDoc`/`RecapListItem`/`TaStats`
di `lib/api/loose-types.ts` -- 4 endpoint `/api/recap/*` juga
`dict[str,object]` di backend (`routers/recap.py` balikin dict polos,
bukan Pydantic model), jadi shape-nya di-declare manual dari baca
`cti_api.services.recap._to_dict()`/`SYSTEM_PROMPT` langsung, bukan
tebakan dari nama field lama. 404 di `/api/recap/{date}` (belum ada
recap buat tanggal itu) DIBACA dari `response.status` sebelum cek
`error` openapi-fetch -- endpoint itu gak deklarasiin 404 di OpenAPI
spec (cuma 200/422), jadi tipe `error` gak nyakup dia; power lewat
`response.status` langsung lebih aman daripada gantungin narrowing tipe
yang emang gak lengkap.

**`<ConfirmDialog>` generik dibangun** (`src/components/confirm-
dialog.tsx`) -- gantiin `.modal-overlay#recap-confirm-overlay` manual
lama, ini use-case nyata pertama yang disebut di catatan deferred
Grup A. Dipakai buat Generate/Force Regen (Force Regen nampilin baris
peringatan tambahan).

Verifikasi LIVE (browser beneran, tab baru): `/dashboard` -- semua 8
chart render benar (warna/legend/tooltip cocok sama lama), stat box
kebaca dari data asli (38 artikel dev DB), Scraper Health placeholder
muncul. `/recap` -- state kosong (belum pernah ada recap di DB dev)
render dengan benar (history "No recaps yet", body "No recap stored for
<date>" + tombol Generate Now), buka dialog Generate DAN Force Regen
(warning bander muncul cuma di Force Regen), Cancel nutup tanpa mutate.
**Gak nge-klik confirm beneran** -- `POST /api/recap/generate` manggil
LLM asli (biaya token + 10-30 detik), sengaja gak dites end-to-end
biar gak buang token tanpa diminta; wiring-nya sama persis pola
`ChangelogDialog` yang udah divalidasi Grup A (`api.POST` typed +
`useMutation`), jadi risiko rendah. 404 `/api/recap/{date}` MUNCUL di
console sebagai "Failed to load resource" (browser bawaan buat fetch
non-2xx) -- itu bukan bug, response-nya DIBACA dan ditangani (empty
state), bukan unhandled. `chart.js` sempet warning `Filler` plugin
(dipake `fill:true` di line chart) -- diregister, verified ilang di
tab baru abis fix. `pnpm build`/`tsc --noEmit`/`pnpm lint` semua bersih.

### Grup C -- selesai (2026-09-24)

`/xintel` + `/admin/users` ("sedang, mandiri"). Port `legacy/static/js/
newsroom/{xintel,usermgmt}.js` + `tab_{xintel,usermgmt}.html`.

**`/xintel`**: sub-tab lokal (bukan sub-route -- cuma `/intelligence`
yang diputuskan sub-route beneran, keputusan #2) Tweets + Monitored
Accounts. Tweets: filter bar (teks/tanggal butuh APPLY, 3 checkbox APAC/
OT/Confirmed langsung apply on-change, port `_xiState` lama), stats row,
card list + modal detail penuh (signals, threat groups, CVE, APAC, negara
victim/actor, incident), pager pakai `<SimplePager>` baru (lihat bawah).
`confidence`/`incident_confidence` DIRENDER LANGSUNG sebagai `%` -- BUKAN
`*100` kayak `(t.confidence*100).toFixed(0)` legacy: skema baru
`TweetOut.confidence: int | None` UDAH 0-100, beda dari field lama yang
0-1 float, ikut kaliin ulang bakal salah (ketemu baca skema, bukan asumsi
port apa adanya). "+ Newsletter" queue nulis ke `localStorage
newsletter_queue` KONTRAK SAMA PERSIS kayak lama (Grup H nanti baca key
yang sama, forward-compatible, bukan reimplementasi). **𝕏 API balance
chip (popover recharge/bonus credits) SENGAJA DIDROP, bukan lupa** --
`GET /api/tweets/balance` sendiri gak pernah diport (`routers/tweets.py`
docstring Fase 7.3: "passthrough eksternal doang, gak genting buat
inti"), gak ada backend buat dipanggil.

**`/admin/users`**: role-gate di level HALAMAN (admin+superadmin) --
**ini "Grup yang beneran punya halaman admin"** yang disebut di catatan
deferred Grup A, jadi role-gate per-halaman dieksekusi di sini pertama
kali (`require_admin`/`require_superadmin` FastAPI tetap enforcement
ASLI, ini cuma UI). 5 section: Users (tabel + Add User + dropdown aksi
⋮ Reset Password/Edit Clients/Change Role -- 2 terakhir admin+ doang,
port asimetri `isAdmin` lama), User Roles (tabel + Add Role modal
superadmin-only, grid permission dari `/api/roles/permissions`),
Password Policy (form pakai pola "derived state" `override` BUKAN
`useEffect`+`setState` -- itu persis pola yang kena
`react-hooks/set-state-in-effect` di `AuthProvider` Grup A, lihat
komentar di `password-policy-section.tsx`), Audit Log (filter user/
action debounce 400ms, page-size select, pager), Client Tenants
(superadmin-only, Add/Edit pakai `<CountryMultiSelect>` baru).

**2 komponen generik deferred Grup A akhirnya kepake beneran**:
`<ConfirmDialog>` (dipakai lagi buat Remove Account/Delete Role/Delete
Client) dan `<CountryMultiSelect>` (Client Tenant country assignment).
`<Pagination>` shadcn TETAP gak kepake -- primitif itu `<a href>`-based
(buat pagination URL asli), sedangkan tiap list di app ini state
halamannya di React state (page di-`useState`, bukan query-string) --
dibikin `<SimplePager>` baru (Prev/Next + info halaman, plain `Button`,
sama persis pola pager lama) buat X Intel tweets dan Admin audit log.

**Self password-change ditambahin ke `UserMenu`** (`ChangePasswordDialog`,
dropdown item baru) -- gap NYATA dari Grup A: sebelum ini gak ada cara
user ganti password sendiri sama sekali dari UI. Numpang
`usePasswordPolicy()`/`validatePasswordClient()` (`lib/auth/password-
policy.ts`, hook baru dipakai bareng Add User/Reset Password/Change
Password). **Force-password-change gate (redirect paksa abis login kalau
`force_pw_change=true`) SENGAJA BELUM dibangun** -- `GET /api/auth/me`
gak balikin `force_pw_change` sama sekali (cuma `POST /api/auth/login`
response yang punya field itu, JWT sendiri gak nyimpennya), jadi begitu
halaman di-refresh infonya hilang; butuh keputusan kecil dulu (tambah
field ke `/me`, atau baca dari cookie terpisah) sebelum bisa dibangun
bener, bukan sesuatu yang bisa diselesaikan sambil lalu di Grup ini.
Dicatat di sini sebagai gap eksplisit, bukan lupa.

**2 bug REAL ketemu LIVE (browser beneran, bukan cuma tsc/lint)**:

1. **`client_countries.country_code` Postgres `VARCHAR(2)`** -- `POST
   /api/clients` dengan nama negara penuh ("Indonesia", ikutin
   `_COUNTRIES` legacy apa adanya) 500
   `StringDataRightTruncationError`. Skema baru pakai ISO alpha-2 (sama
   konvensi kayak `ArticleCountry.country_code` yang UDAH dipakai
   Dashboard Grup B), BUKAN nama penuh kayak Mongo lama. Fix: `lib/
   countries.ts` diulang total jadi `{code, name}[]` ISO 3166-1 alpha-2,
   `<CountryMultiSelect>` kirim `code`, tampilin `name`. Verified live:
   `POST /api/clients` 201 abis fix, badge tabel Client Tenants resolve
   code->nama lewat `countryName()`.
2. **Base UI `Select` crash kalau `SelectItem` children lebih dari satu
   ekspresi/teks JSX** -- `AddUserForm`'s Role select (`{r.name}{cond ?
   ... : ""}`, DUA children) bikin `Uncaught TypeError: c.toLowerCase is
   not a function`, crash SELURUH Select (Base UI extract label buat
   typeahead/keyboard-match, `.toLowerCase()` di hasil extract yang
   ternyata bukan string tunggal). Fix: gabung jadi SATU string
   (`` `${a} — ${b}` : a ``), sama pola yang dipakai Select lain yang
   emang gak pernah crash. Dicatat sebagai gotcha ke-3 di `apps/web/
   CLAUDE.md` (gotcha #1/#2 dari Grup A: `render` vs `asChild`,
   `DropdownMenuLabel` butuh `DropdownMenuGroup`).

Verifikasi LIVE (tab baru tiap kali abis fix, biar console bersih):
`/xintel` tweets (real data + filter+pager+modal), Monitored Accounts
(toggle+remove ConfirmDialog, real data `@blueteamsec1`). `/admin/users`
4 user asli, 3 role asli+permission badge, Password Policy pre-filled
data server asli, Audit Log 128 entries real+pager (entry toggle account
dari tes X Intel MUNCUL di sini, konfirmasi audit trail jalan), Client
Tenants 2 client asli (`acme`/`default`) + add/delete client test
(`qa_test_grp_c`, dibuat lalu dihapus buat bersihin data tes) full
round-trip. Dialog Change Role/Add Role/Add Client semua kebuka+keisi
data benar (beberapa sempet keliatan "gak kebuka" di screenshot doang --
accessibility tree/network selalu konfirmasi bener-bener kebuka,
sekadar delay render screenshot tool, bukan bug). `pnpm build`/
`tsc --noEmit`/`pnpm lint` semua bersih (setelah 2 fix bug di atas).

**Gak dites live**: role-gate `/admin/users` buat role `analyst` (gak
ada kredensial test analyst di tangan) -- diverifikasi lewat code review
+ tsc doang, pola sama persis kayak conditional `isSuperadmin` yang
UDAH kebukti kerja (`ClientsSection`/`RolesSection`). Force-password-
change gate (lihat gap di atas) juga gak dites karena emang belum
dibangun.

### Grup D -- selesai (2026-09-24)

`/newsroom` (survei: "8 panel paralel, butuh pola panel+pagination dari
Grup A udah solid"). Port `tab_newsroom.html` + `{core,api,tabs,render,
modal,ttp}.js` -- newsroom gak punya file lama sendiri, logic-nya
tersebar 7 file (termasuk `loadPanel()`/`PANEL_CONFIG` yang nangkring di
`cve.js`, `loadWatchlistPanel()`/`loadTechStackPanel()` di `ta.js` --
disposisi legacy, bukan salah taruh port di sini).

**6 panel**: APAC (`news_type=apac`), Global (6 `news_type` sekaligus),
Ransomware Activity (2 sub-section independen: tabel live victims
`ransomware.live` dengan mini-filter sendiri group/country/industry +
artikel terkait tanpa filter apa pun), Local (di-scope `client_countries`
user aktif -- `AuthUser` yang sama dipakai `<ClientSwitcher>` Grup A,
BUKAN filter country di filter bar, judul jadi "Global News" kalau
client gak punya negara ke-assign, port `localPanelTitle([])` apa
adanya), TA Watchlist (resolve `/api/ta/watchlist-names` dulu baru query
artikel, cuma respect filter `search`), Tech Stack (resolve
`/api/techstack?page_size=500` dulu, respect date/industry/actor/search
tapi BUKAN country). **Tiap panel beda subset filter yang dipakai --
port asimetri persis dari `loadPanel()`/`loadLocalPanel()`/
`loadWatchlistPanel()`/`loadTechStackPanel()`/`loadRwArticles()` lama,
bukan "apply semua filter ke semua panel" yang lebih gampang tapi
salah.**

**Filter bar default 7 hari terakhir** (`posted_on_start`/`_end`), port
`autorefresh.js`'s init -- BUKAN unfiltered/all-time, itu perilaku
lama yang gampang kelewat kalau cuma baca nama fungsinya. Country/
industry/actor SELECT isinya `/api/filters` langsung (kode ISO alpha-2
buat country) -- `variantToCanonical`/`expandCountry`/`/api/country-
groups` legacy SENGAJA gak diport, `routers/articles.py` sendiri bilang
peta nama-negara-bebas-teks itu obsolete (skema baru udah ISO alpha-2
dari enrichment).

**Modal artikel** (`openModal()`): meta bar, industries, countries
(victim/actor role-based atau fallback mentioned), threat actors, tabel
MITRE TTP + toggle D3FEND per baris (`toggleD3fend()` -- BUKAN
`openTtpDrill()` penuh, itu punya MITRE heatmap `/intelligence` Grup G),
IOC section (terstruktur tapi PASTI kosong sekarang -- `ArticleOut.iocs`
selalu `{}`, linkage artikel<->IOC belum diport, placeholder yang udah
didokumentasikan sejak schema Fase 7.3, bukan bug baru), newsletter
queue (localStorage, kontrak sama kayak X Intel Grup C), export IOC CSV.

**Sub-view "Not Related Cyber"** (`rejected_articles`) -- di-gate admin+
di level KOMPONEN (tombol submenu-nya gak dirender buat non-admin,
beda dikit dari legacy yang render tombolnya terus redirect balik kalau
diklik -- efeknya sama, presentasinya lebih bersih di app route-based).
Search + Restore (re-queue ke NLP pipeline).

**3 hal SENGAJA didefer, dicatat eksplisit bukan lupa**:
1. **Filter bar gak dibagi ke `/dashboard`** -- legacy nge-share SATU
   filter bar buat tab Dashboard+Newsroom sekaligus (`applyFilters()`
   manggil `loadDashboard()` juga). Di app baru itu 2 ROUTE terpisah;
   nyambungin filter state lintas-route (URL search params, atau store
   di layout `(app)`) butuh keputusan arsitektur baru yang belum
   diambil. `/dashboard` (Grup B) tetap unfiltered.
2. **Auto-refresh countdown** (`autorefresh.js`'s `setAutoRefresh()`)
   gak diport -- chrome "nice to have", tiap panel udah punya tombol
   refresh manual (core requirement udah kepenuhin).
3. **Admiralty/source-reliability badge** di kartu+modal artikel
   (`_srScoreMap`) belum -- itu punya Source Reliability
   (`/intelligence`, Grup G, belum dibangun).
4. `loadCvePanel()` yang ikut kepanggil di `loadAllPanels()` lama GAK
   diport -- itu prefetch optimasi buat SPA monolitik lama (biar tab CVE
   gak nge-flash loading pas di-switch), obsolete di arsitektur
   route+TanStack-Query baru (`/cve`, Grup E, bakal fetch sendiri pas
   route-nya diakses).

**2 bug REAL ketemu live**:
1. **`Select` trigger nampilin VALUE MENTAH (`__all__`) bukan label**
   ("All Countries") pas belum pernah dibuka sekali -- Base UI
   `Select.Value` cuma resolve label dari item yang UDAH ke-render
   (`SelectContent` di-portal). Fix: prop `items` di `Select.Root`
   (`Record<string,label>`), API yang didesain Base UI persis buat ini.
   Dicatat gotcha ke-4 di `apps/web/CLAUDE.md`.
2. (Ketemu sepanjang nulis kode, dibenerin sebelum sempet ke-commit,
   dicatat di sini biar histori nyambung) `Object.values(a.iocs).reduce`
   ke-infer `unknown` tanpa generic eksplisit (`iocs` tipe `{[key:
   string]: unknown}`) -- fix `.reduce<number>(...)`.

Verifikasi LIVE (tab baru): 6 panel render data ASLI (APAC 1 artikel
nyata, Global 1, Local 2 -- konsisten karena client `default` gak punya
country assignment jadi keduanya masuk, Watchlist+Techstack 0 tapi
techstack RESOLVE nama asli `Apache Struts`/`Linux`/`WordPress` sebelum
query -- kebukti dari network request, bukan cuma UI kosong). Modal
artikel buka data lengkap termasuk 2 TTP asli (`T1555.003`/`T1574`) +
D3FEND toggle manggil API asli. Filter Apply narrow-in hasil bener
(search "Zero Trust" bikin APAC 0/Global 1, ransomware TETAP gak
kepengaruh -- konfirmasi asimetri filter per-panel jalan), Reset balikin
ke default 7-hari. "Not Related Cyber" nampilin artikel rejected asli
("10 Best Pasta Recipes..."). Console bersih di tab baru sepanjang
seluruh alur. `pnpm build`/`tsc --noEmit`/`pnpm lint` semua bersih.

### Grup E -- selesai (2026-09-25)

`/cve` -- area terbesar tunggal Fase 8 (docs/PROGRESS.md urutan kerja:
"core+techstack+pkgvuln, ticket workflow, 3 lookup eksternal"). Port
`legacy/static/js/newsroom/{cve,techstack,pkgvuln}.js` (1284+309+908 =
2501 baris) terhadap backend yang UDAH lengkap diport sejak Fase 7 --
murni build frontend, gak ada kerjaan backend baru. Dua agen Explore
paralel dulu buat riset (peta UI legacy + kontrak backend lengkap,
termasuk cross-check ke test snapshot `.ambr` buat shape response yang
gak declare `response_model`) sebelum nulis komponen apa pun.

**2 level view-switch**, niru struktur legacy persis: `CveTrackerPage`
(view "CVE Tracker" vs "Package Vulnerabilities", `cveSwitchView`), dan
di dalam CVE Tracker, sub-view "CVEs" vs "Tech Stack"
(`cveSwitchTSVSubview`).

**CVE core** (`CveCoreView`+`CveList`+`CveRow`+`CveDetailModal`+
`CveTicketTab`+`CveLookupToolbar`): tabel 13 kolom (checkbox, CVE ID,
Tech, Score, Severity, Summary, Affected, Published, Solution, Flags,
News, EPSS, Action) dengan sort per-kolom, bulk-select+bulk-ack+bulk-FP+
draft-email (disable kalau tech beda), filter bar (search/severity/tech/
date range/show-FP/unacked-only), stats bar, 3 lookup eksternal (CISA
KEV/EPSS/Exploit-DB, bulk+single-row), export Excel. Modal detail 2 tab
(Details statis dari row ter-cache -- gak fetch ulang, sama kayak
legacy -- dan Ticket: form 16 field uncontrolled + `FormData` pas save,
niru pola legacy baca DOM langsung, sekalian ngehindarin `useEffect`
buat sync state pas data ticket pertama kali datang).

**Tech Stack** (`TechStackPanel`): CRUD table -- add/remove/inline
exposure+hosting cycle (PATCH). Tombol "↺ Historical backfill"/
"↺ Backfill CVEs" legacy TIDAK diport -- endpoint-nya emang belum ada
di `routers/techstack.py` (docstring router sendiri bilang nyusul bareng
`cve.py`, yang sekarang UDAH diport tapi backfill-nya sendiri masih
belum -- dicatat sebagai gap terpisah, bukan lupa).

**Package Vulnerability** (`PkgVulnView`+`PackagesPanel`+`VulnsPanel`+
`DepsModal`+`LockfileImportDialog`+`EditPackageDialog`+
`VulnDetailModal`): sub-view Packages (CRUD+scan+resolve-deps+import
lockfile drag-drop) dan Vulns (filter+ack+detail). Semua aksi
scan/resolve-deps/import-lockfile fire-and-forget (`BackgroundTasks`
FastAPI, gak ada job-status endpoint sama sekali) -- port pola legacy:
invalidate query abis delay tetap (4-30 detik tergantung aksi), bukan
nunggu sinyal "selesai" yang emang gak ada di kontrak API.

**Adaptasi karena kontrak API beda dari legacy** (bukan bug, field-nya
emang gak ke-expose):
- `affected` berubah shape dari dict Mongo-era (`{product:[ranges]}`)
  jadi flat string `"Product: constraint"` di skema Postgres baru --
  parsing baru (`parseAffected()`) ditulis dari nol, bukan port
  `_renderAffected()` lama yang bakal crash kena shape baru.
- `CvePocOut.poc_type` (bukan `p.type` kayak legacy baca) -- field-nya
  emang direname pas port.
- Detail CISA-KEV (vendor/product/date_added/due_date/name/description/
  action) dan `epss_date` GAK ada di `CveOut` -- cuma `cisa_kev` bool +
  `epss_score`/`epss_percentile`. Modal detail disederhanain ke apa yang
  beneran ada, bukan nebak-nebak field yang gak dikirim API.
- ~~Mind Map button (CVE ticket) DIDEFER~~ -- selesai Grup G5
  (2026-09-25), lihat writeup di bawah.
- Cross-link klik package-vuln row → buka modal CVE tab (`pvShowVulnDetail`
  legacy) DIDEFER -- butuh fetch tambahan cuma buat kemungkinan-kecil
  match, sementara `VulnDetailModal` fallback SUDAH nampilin semua data
  riil yang ada.

**1 bug nyata ketemu live**: gak ada -- kali ini semua kontrak API
match ekspektasi (hasil riset 2-agen Explore yang udah cross-check ke
test snapshot beneran, bukan tebak dari nama field lama). Yang KETEMU
malah masalah environment: dev server `.next` cache korup abis
`pnpm build` production dijalanin bareng `next dev` (turbopack) di
folder yang sama -- fix: stop task lama, `rm -rf .next`, restart.
Terpisah dari itu, cookie sesi lama (dari testing Grup A-D sebelumnya)
udah expired tapi `proxy.ts` cuma cek KEBERADAAN cookie (bukan validasi
JWT, sengaja -- lihat docstring situ), jadi `/login`↔`/dashboard` muter
infinite pas cookie ada-tapi-invalid. Bukan bug baru dari Grup E,
edge-case pre-existing yang baru ketemu sekarang -- fix sesi ini cukup
`POST /api/auth/logout` manual buat clear cookie-nya, gak perlu ubah
kode `proxy.ts`.

Verifikasi LIVE end-to-end (tab baru, login `admin1`/superadmin):
**CVE core** -- 4 CVE real render (WordPress×3 + Linux), stats bar
Critical/High/Medium bener, modal detail CVSS vector table expand bener
+ affected versions parse bener dari flat string, tab Ticket render 16
field + prefill affected asset/version dari CVE asli + ticket ID
auto-generate (`CTI-2026-09-001`), Save Ticket (PUT 200) + Acknowledge
(POST 200, banner ijo muncul + row live-patch badge ACK + Mark FP
kebuka), Mark FP/Unmark FP round-trip (row ilang/muncul sesuai filter
`include_fp`), 3 lookup eksternal jalan BENERAN ke API luar (CISA KEV:
1721 entri katalog asli, toast muncul), Export Excel 200 dengan
`include_fp=true` kebawa bener. **Tech Stack** -- 3 entri asli (Apache
Struts/Linux/WordPress), inline PATCH exposure+hosting jalan, Add+Remove
round-trip bersih. **Package Vulnerability** -- add `lodash` npm beneran
manggil registry npm + osv.dev ASLI, background scan nemu 10 vuln nyata
(GHSA-jf85-cpcp-j695 dst, CVSS/severity/fixed-in semua kebaca bener),
Vuln detail modal render lengkap, Ack toggle (PATCH 200), Resolve-deps
manggil deps.dev ASLI (OSSF Scorecard 5.4 dengan breakdown Packaging/
Signed-Releases/Branch-Protection/Pinned-Dependencies/Code-Review/
License), Edit + Delete package round-trip bersih. Console bersih di
tab baru sepanjang seluruh alur (dicek 2x, termasuk tab baru terpisah
abis semua testing). `pnpm build`/`tsc --noEmit`/`pnpm lint` semua
bersih.

### Grup F -- selesai (2026-09-25)

`/exec` -- Executive Dashboard: 6 chart+2 heatmap+AI-brief+FP-vote
widget, port `legacy/static/js/newsroom/exec.js` (869 baris, satu file
mandiri -- BUKAN scattered kayak newsroom). Backend (`exec_dashboard.py`/
`exec_brief.py`/`spike.py`) udah lengkap sejak Fase 7; satu-satunya
perubahan backend di Grup ini adalah fix kontrak IOC feedback (gap #7,
lihat di bawah). `_pirXxx` functions (`exec.js:757+`, Priority
Intelligence Requirements) TIDAK ikut diport -- fitur beda (`/intelligence`
Grup G2), cuma numpang 1 file fisik sama legacy.

**Riset**: 1 agen Explore (peta lengkap legacy+backend+kontrak IOC
feedback lama-vs-baru) + baca langsung `exec.js` full buat detail
rendering/formula yang butuh presisi tinggi (risk score, peer benchmark,
warna threshold) -- laporan agen dipakai buat orientasi awal, detail
implementasi dicek ulang dari source asli.

**Dibangun**: KPI strip (7 tile + trend arrow naik=merah/turun=hijau
khusus metrik keamanan), Sector Risk Matrix (formula Volume+Trend+Spike,
0-100) + peer benchmark (share sektor vs rata-rata, dihitung client-side
sama kayak legacy), TA Leaderboard (badge NEW/REC + confidence),
6 chart Chart.js (sector/country/victim-country trend multi-series,
incident-type doughnut, incident-type monthly stacked bar, Source
Reliability Spread doughnut grade A-F -- role-gated), tabel CVE
Exposure, 2 heatmap (Sector×Month biru + drill-down klik sel ->
`GET /api/articles`, Sector×Actor merah tanpa drill), 4 panel Tier 2
(Top TTPs, TA Velocity, Sector Co-occurrence -- semua di
`components/exec/tier2-panels.tsx`), 3 section role-gated (Cluster List,
IOC FP Queue, Critical CVE Feed -- render kondisional dari
`view_config.sections`, bukan selalu ditampilin kayak legacy yang gak
bedain "gak berhak lihat" vs "emang kosong"), modal AI Brief
(`react-markdown`, generate on-demand), export CSV client-side, watchlist
localStorage, role-preview switcher (admin/superadmin only).

**Fix backend -- gap #7 (kontrak `/api/iocs/feedback`)**: legacy
`execFpVote()` manggil `POST /api/iocs/feedback` (`{ioc_type,value,
is_true_positive}`) yang UDAH GAK ADA; kontrak baru `POST /api/iocs/
{ioc_id}/feedback` (`{verdict,note}`) butuh `ioc_id` numerik yang
sebelumnya GAK ke-serialize di `_get_pending_fp_queue()`
(`services/exec_dashboard.py`) -- ditambahin `id` ke row (1 baris + 1
test integrasi baru), FP-vote widget sekarang manggil kontrak yang
beneran ada. Bukan perubahan skema DB.

**Adaptasi field yang beda dari legacy** (didokumentasikan, bukan silent
drop): `critical_cves` gak punya `epss_score`/`first_seen` (kolom
`epss_score` emang gak ada di `CveTracker`, `_get_critical_cves()` cuma
filter `cisa_kev`) -- 2 kolom itu didrop dari tabel, bukan ditampilin
kosong. TA Leaderboard row click (`drillToNewsroomTA()` legacy: pindah
tab + auto-pilih filter actor + reload) disederhanain jadi navigasi
polos ke `/newsroom` TANPA auto-filter -- filter newsroom gak
addressable lewat query param (state lokal ke komponen, Grup D), gap
kecil dicatat bukan pura-pura jalan. Cluster List row click (legacy:
pindah tab Intelligence) dihapus link-nya sama sekali -- rute itu belum
ada (Grup G7). Critical CVE Feed row click cuma link polos ke `/cve`
(bukan auto-buka modal detail -- butuh row `CveOut` lengkap yang cuma
ada di query list `/cve`, pola defer sama kayak cross-link pkg-vuln->CVE
di Grup E).

**1 bug nyata ketemu live**: React duplicate-key warning di Top TTPs
list -- `ttp_counts()` (repo) group-by `(ttp_id, ttp_name)` BUKAN
`ttp_id` doang, jadi id yang sama (`T1583`) bisa muncul 2 baris kalau
enrichment nyimpen 2 varian nama beda ("Acquire Infrastructure" vs
"Resource Development") buat id yang sama -- KETEMU dari data dev DB
beneran, bukan data buatan. Ini data quality upstream (di luar scope
Grup F buat dibenerin), fix di frontend: key gabung `id+name+index`
biar cocok sama kenyataan API (2 entry beda konten, bukan 1 entry
diduplikasi).

Verifikasi LIVE end-to-end (tab baru, login `admin1`/superadmin):
semua 6 chart + 2 heatmap render data asli (7 insiden, 3 TA, 5 sektor).
Drill-down klik sel heatmap "General · 2026-09" -> 2 artikel asli
kebuka lengkap (judul+tanggal+sumber+news_type+TA tags). Generate
Brief manggil LLM ASLI (~15 detik), balikin markdown 5-section
(Vulnerability Exposure/Key Findings dst) -- render `react-markdown`
BENERAN terformat (bold/bullet/heading), bukan raw `#` kayak bug
legacy. FP-vote widget: seed 1 IOC test manual di DB dev, klik 👍 ->
`POST /api/iocs/99/feedback` 200, toast "Marked as true positive.",
row ilang dari queue abis refetch (confidence naik keluar rentang
40-74) -- IOC test dibersihin abis verifikasi. Role-preview switcher:
ganti ke "soc" -> refetch dengan `role=soc`, badge "View: SOC" muncul,
section role-gated berubah SESUAI (Cluster List+FP Queue ilang,
Critical CVE Feed tetap ada, chart Source Reliability Spread ilang) --
konfirmasi `view_config.sections` bener-bener ngontrol render, bukan
cuma dekorasi. Export CSV + clipboard-copy brief jalan (clipboard
`NotAllowedError` di browser tool otomasi -- permission browser
environment testing, BUKAN bug kode, pattern yang sama kayak
`navigator.clipboard` manapun di browser automation headless). Console
bersih di tab baru terpisah abis seluruh alur testing (dicek 2x).
Backend: 10 test (7 lama + 3 baru termasuk `test_pending_fp_queue_
includes_ioc_id`) semua pass. `pnpm build`/`tsc --noEmit`/`pnpm lint`
semua bersih.

### Grup G1 -- selesai (2026-09-25)

`/intelligence` sub-grup pertama dari 7 (G1-G7, dipecah karena
`/intelligence` sendirian ~4700 baris legacy): **Risk Matrix + Source
Reliability + Early Warning**, sesuai urutan "kecil ke besar" yang
diusulkan survei. Keputusan arsitektur Fase 8 #2 diterapkan pertama
kali di sini: `/intelligence` jadi sub-route Next.js BENERAN
(`/intelligence/risk-matrix` dst, `layout.tsx` shared + nav), bukan
client-state tab switcher kayak legacy `intelSwitchView()`
(`intel.js`, 11 sub-view dalam 1 shell). Nav sub-route cuma nampilin
3 yang UDAH dibangun -- bakal nambah entry tiap G2-G7 landing, bukan
placeholder buat 8 sub-view yang belum ada.

**Riset**: dibaca langsung (gak lewat agen) -- `risk_matrix.js` (90
baris) + bagian spikes `intel.js` (~50 baris) + `source_reliability.js`
(327 baris) semua ukuran kecil-sedang, backend (`risk_matrix.py`,
`spike.py` -- udah dikenal detail dari Grup F, `source_score.py`,
`routers/source_reliability.py`) juga udah lengkap sejak Fase 7.

**Temuan penting**: `GET /api/source-scores` (`source_score.py`,
heuristik grading OTOMATIS per nama sumber, lookup tabel hardcoded)
**KONFIRMASI dead code** -- `loadSourceScores()` di `intel.js` cuma
DI-DEFINE, NOL call site di seluruh `legacy/static/js/` manapun (grep
lintas file). Sub-view "scores" yang beneran dipakai (`intelSwitchViewAndLoad`)
manggil `loadSREntries()` (grading MANUAL analis tersimpan DB), bukan
fungsi itu. Sama presedennya kayak `wisemap_service.py` (Grup E survei
2026-09-19) -- endpoint gak dipanggil UI manapun, sengaja gak diporting,
bukan lupa.

**Dibangun**:
- **Risk Matrix** -- grid Industry×Country, skor 0-100 (Volume+Trend+
  Spike, formula sama kayak yang dipakai Grup F), 4 tier warna
  (mapping ke token Tailwind success/primary/warning/destructive,
  bukan rgba literal legacy), filter `days`/`compare_days` (server)
  + `min_score` (client-side, port apa adanya).
- **Early Warning** -- `GET /api/spikes` versi standalone (endpoint +
  service PERSIS sama kayak spike banner Grup F, cuma `lookback_days`/
  `z_threshold` sekarang jadi filter user-facing, bukan hardcoded),
  4 kategori (Overall/Threat Actor/Country/Industry) urut z-score desc.
- **Source Reliability** -- CRUD grading Admiralty (grade A-F ×
  credibility 1-6, kode `admiralty_code` = gabungan keduanya), search+
  filter grade+sort+pagination, modal Add/Edit dengan autocomplete
  source picker custom (Input+dropdown lokal dengan arrow-key nav,
  BUKAN Base UI `Select` -- itu buat fixed-option, bukan free-text+
  filter; gak ada komponen Combobox siap pakai di `ui/`). Analyst Name
  di-prefill `user.username` (perbaikan kecil atas legacy yang kosong
  defaultnya -- sekarang ada JWT asli, bukan password bersama).

**1 bug nyata ketemu live** (bukan kode, cara nge-test): pas nyoba
verifikasi Risk Matrix pakai data seed manual, cell-nya kosong terus
biarpun 2 artikel share industry+country yang sama -- ternyata
`risk_matrix_rows()` (repo) cuma ngitung `ArticleCountry` dengan
`role="mentioned"`, bukan `"victim"` (beda dari cara Grup F seed data
buat exec dashboard yang gak peduli role). Bukan bug kode yang perlu
difix, cuma kesalahan seed data pas testing -- re-seed pakai role
`"mentioned"` langsung nunjukin cell "Healthcare×US: 100↑" bener.

Verifikasi LIVE end-to-end (tab baru, login `admin1`/superadmin): nav
3 sub-route + redirect `/intelligence`->`/intelligence/risk-matrix`
jalan. Risk Matrix filter re-fetch pas parameter ganti (cache 900s
backend per kombinasi `days|compare_days`, dites lewat beberapa
kombinasi biar gak kena cache basi), cell render warna+tooltip bener
pas ada data seed manual (dibersihin abis verifikasi). Early Warning
render 4-kategori grouping, empty-state bener buat dev DB yang sepi
(logic `get_spikes()` udah diverifikasi ketat Grup F, gak diulang
seeding di sini). Source Reliability CRUD PENUH: Add (autocomplete
munculin sumber ASLI dari DB -- "Bitdefender Labs"/"Mandiant"/
"gbhacker"/"live-test-feed", grade+code select populate dari
`/api/sr/labels` beneran, preview badge A1 ijo) -> Edit (notes update,
PUT 200) -> Remove (confirm dialog nyebut nama sumber bener, DELETE
200, row ilang). Console bersih di tab baru terpisah abis seluruh
alur. `pnpm build`/`tsc --noEmit`/`pnpm lint` semua bersih.

### Grup G2 -- selesai (2026-09-25)

`/intelligence` sub-grup kedua: **PIR (Priority Intelligence
Requirements) + RFI (Request for Information)**. Legacy: file
`pir.js` (453 baris) -- ternyata PIR *dan* RFI dua-duanya numpang 1
file fisik (pola disorganisasi yang sama kayak "Newsroom" Grup D:
panel loader numpang di file gak nyambung), plus multi-select criteria
UI (`_pirMsXxx`) numpang lagi di `exec.js` (udah dibaca lengkap Grup
F). Backend (`routers/pir.py` 305 baris + `routers/rfi.py` 127 baris +
`services/pir_docx.py`) udah lengkap sejak Fase 7, semua endpoint
`response_model`-typed penuh KECUALI `/{id}/export` (JSON mentah,
bukan docx) dan 2 endpoint delete -- murni build frontend.

**Dibangun**:
- **PIR**: kartu list (priority badge, coverage bar, badge COVERAGE
  GAP kalau `is_gap` -- match historis ada tapi 0 match 14 hari
  terakhir), modal Add/Edit dengan 5 `MultiSelectField` (Threat
  Actors/Industries/Countries/News Types/TTPs -- komponen baru,
  Input+dropdown+tag chip, gak ada Combobox siap pakai di `ui/`, sama
  pola kayak autocomplete Source Reliability Grup G1 tapi versi
  multi-pick) + keywords comma-separated + priority/owner/status(edit
  doang)/date range, overlay artikel yang match (paginated) dengan
  note analis per-artikel (`GET`/`PUT /api/pir/{id}/note`), export
  DOCX.
- **RFI**: kartu list + filter status (All/Open/In Progress/Closed),
  modal Add/Edit dengan dropdown Linked PIR (native `<select>`,
  populate dari `GET /api/pir` beneran).
- Analyst Name/field prefill `user.username` di form note (perbaikan
  kecil atas legacy yang kosong defaultnya, sama alasan kayak Grup
  G1's Source Reliability).

**Pola React tanpa `useEffect`**: `NoteForm` (dalam `PirArticlesDialog`)
awalnya nyimpen state `note`/`analyst` di parent + "seed once" flag --
disederhanain jadi `useState(initialNote)` LANGSUNG di `NoteForm`,
valid karena `NoteForm` cuma pernah mount SETELAH `noteQuery.data`
resolve (di-gate kondisional render `noteQuery.isPending ? loading :
&lt;NoteForm/&gt;`), jadi `initialNote` udah pasti nilai final pas
`NoteForm` pertama kali mount -- gak butuh sinkronisasi effect sama
sekali, konsisten sama konvensi proyek ini (`react-hooks/set-state-in-effect`).

**0 bug ketemu live** -- kontrak backend match ekspektasi penuh dari
baca source langsung (bukan tebak dari nama field). Satu detail teknis
ketemu pas nyiapin data test: `_criteria_filters()` (repo) nge-mapping
tiap field kriteria PIR (`threat_actors`/`industries`/`keywords` dst)
ke parameter `AsyncArticleRepo.list_filtered()` yang UDAH ADA (bukan
query builder terpisah) -- semua kriteria di-AND, bukan di-OR, jadi
artikel test harus match SEMUA field yang diisi PIR buat kehitung
coverage-nya.

Verifikasi LIVE end-to-end (tab baru, login `admin1`/superadmin): PIR
create dengan 2 multi-select field (Threat Actors: "Breeze comet",
Industries: "Healthcare & Life Sciences" -- opsi ASLI dari
`/api/pir/options`) + keywords, kartu render lengkap dengan semua tag.
Seed 1 artikel manual yang match SEMUA kriteria -> reload -> coverage
count update jadi 1, "View 1" muncul, badge "Last Hit"/"14d: 1" bener.
Buka overlay artikel -> artikel asli kebuka -> buka note -> isi ->
save (PUT 200) -> badge "✓ NOTED" muncul abis refetch. Export DOCX
beneran manggil `python-docx` di server (200, bukan 501). Edit PIR
prefill semua field termasuk Status (field edit-doang) + 2 tag
multi-select yang udah dipilih. RFI create dengan Linked PIR dropdown
populate PIR asli ("[P2] Ransomware activity targeting Healthcare"),
filter status "Open" trigger query param bener, delete round-trip
bersih. Semua data test (PIR/RFI/artikel/note) dibersihin abis
verifikasi. Console bersih di tab baru terpisah. `pnpm build`/
`tsc --noEmit`/`pnpm lint` semua bersih.

### Grup G3 -- selesai (2026-09-25)

`/intelligence` sub-grup ketiga: **MITRE Heatmap + ATT&CK DB**. Dua
fitur legacy beda sumber data yang numpang nama "MITRE" doang, sama
kelas keputusan kayak `source_score.py` vs `source_reliability` di
G1 -- gak saling gantiin. Heatmap = TTP OBSERVED di artikel
(`ArticleTTP`, hasil ekstraksi enrichment); ATT&CK DB = katalog
referensi dari STIX bundle MITRE, sinkron manual/berkala. Legacy:
heatmap numpang di `scraper.js` (bareng Scraper Health read-only, gap
#6 -- lihat catatan lama "`scraper.js` BUKAN control plane") + drill-down
di `ttp.js` (134 baris), ATT&CK DB penuh di `attack_db.js` (519 baris).
Backend (`routers/mitre.py` 92 baris + `routers/attack.py` 222 baris +
`services/d3fend.py`) udah lengkap sejak Fase 7 -- `attack_sync_check.py`
(polling Celery-beat) dikonfirmasi di luar scope, murni infrastruktur
Fase 7.8, gak ada router exposure sama sekali. Murni build frontend.

**Temuan penting**: SEMUA 17 endpoint (`mitre.py` 5 + `attack.py` 12)
untyped (`dict[str,object]`/`list[dict]`, gak ada `response_model`) --
beda dari kebanyakan Grup sebelumnya yang mayoritas typed, butuh
tambahan manual besar di `loose-types.ts`. Dan dua vocabulary "domain"
yang KELIATAN sama tapi beda: `domain_key` sinkron ("enterprise"/
"ics"/"mobile", dipakai `GET/POST /api/attack/sync[/{domain_key}]`)
vs `domain` filter browse ("enterprise-attack"/"ics-attack"/
"mobile-attack", nilai STIX asli di kolom array `domains` tiap row) --
ketuker bakal bikin filter domain di 4 panel browse gak pernah match.

**Dibangun**:
- **MITRE Heatmap** -- grid Threat Actor/Industry × TTP observed,
  intensitas warna `rgba()` inline dari `val/max` (bukan token Tailwind
  diskrit, port apa adanya dari legacy), filter view+period. Klik sel
  -> `TtpDrillDialog` (artikel yang match, paginated) + `D3fendToggle`
  di-reuse APA ADANYA dari Grup D (`components/newsroom/d3fend-toggle.tsx`)
  -- manggil endpoint `GET /api/mitre/d3fend/{technique_id}` yang persis
  sama, gak ada alasan bikin ulang.
- **ATT&CK DB** -- kartu sync status per-domain (Enterprise/ICS/Mobile,
  tombol Sync per-domain + Sync All, polling 5s SELAMA ada domain
  `"syncing"`, delta indicator teknik/grup/software/mitigasi vs sync
  sebelumnya) + 4 sub-tab browse (Techniques/Groups/Software/Mitigations,
  search+domain filter, +tactic/subtechnique khusus Techniques, +type
  khusus Software) dengan pagination. 3 dari 4 sub-tab row-nya clickable
  -> `AttackDetailDialog` SATU dialog dibagi (bukan modal ke-stack),
  cross-link technique<->group<->software lewat `onNavigate` ganti
  target + refetch, niru pola `_openModal()` legacy yang dipakai ulang
  tanpa nge-stack. Mitigations SENGAJA gak clickable (`attack_db.js`'s
  `_fetchMitigations()` render row TANPA `onclick`, beda dari 3 lainnya
  yang semua punya `onclick="show*Detail(...)"`).
- **Navigator export** -- `downloadLayer()` (blob download lewat
  `/api/proxy/...`, pola direct-fetch+`getActiveClientId()` yang sama
  kayak export lain) + `openNavigator()`/`openNavigatorForGroup()`
  (buka MITRE Navigator eksternal dengan `layerURL` nunjuk balik ke
  backend kita). **Keterbatasan yang DIWARISI, bukan bug baru**: session
  cookie httpOnly same-site-only gak kebawa pas Navigator (origin lain)
  ngambil `layerURL` itu sendiri lewat `fetch()` -- legacy punya masalah
  analog (Bearer JWT di localStorage juga gak nempel ke navigasi
  eksternal polos). Diputuskan port APA ADANYA (pola URL sama), bukan
  bikin auth-bypass baru -- dicatat di sini biar gak disalahartikan bug
  yang belum ketangkep.

**0 bug ketemu live** -- kontrak backend (17 endpoint untyped) tetap
match penuh setelah baca `AsyncAttackQueryRepo`/`AsyncMitreQueryRepo`
langsung (bukan tebak dari nama field). Satu self-correction pas nulis
kode (bukan bug live): `mitre-heatmap-view.tsx` awalnya punya helper
`heatBgClass()` yang gak kepake -- kalkulasi warna di-inline langsung
di JSX `style`, fungsi lama dihapus sebelum final.

Verifikasi LIVE end-to-end (tab existing, session admin1 masih valid):
MITRE Heatmap render grid asli (3 threat actor × 20 TTP, data real dari
enrichment) -> klik sel "Apt41 × T1555.003: 1 articles" -> drill dialog
buka artikel asli ("China-linked APT41 breaches Philippine government
network...", gbhacker) -> toggle D3FEND -> fetch sukses ("No D3FEND
countermeasures mapped" -- respons valid, teknik ini emang gak ada
mapping). ATT&CK DB: sync status 3 kartu SUCCESS (Enterprise 709
teknik/191 grup/828 software, ICS 97/16/23, Mobile 137/22/127) --
data real dari sync yang udah jalan sebelumnya. Techniques tab (943
total, paginated) -> klik T0800 -> detail lengkap (8 mitigasi, 1
software) -> klik cross-ref "S0604 Industroyer" -> dialog GANTI isi
jadi Software detail (1 grup, 44 teknik) TANPA modal baru -> klik
cross-ref "G0034 Sandworm Team" -> ganti lagi jadi Group detail (85
teknik, 28 software) -- triangle technique<->group<->software full
jalan. Mitigations tab render (943 baris cek M0800-dst) TANPA row
clickable, sesuai desain. `pnpm build`/`tsc --noEmit`/`pnpm lint`
(scope `intelligence/mitre`+`intelligence/attack-db`+`loose-types.ts`)
semua bersih.

### Grup G4 -- selesai (2026-09-25)

`/intelligence` sub-grup keempat: **IOC Management** (tabel IOC +
Allowlist + FP Analytics). Legacy: `ioc_mgmt.js` (692 baris) -- SATU
file numpang 3 fitur (`iocmgmtLoad()` dkk, `allowlistLoad()` dkk,
`fpAnalyticsLoad()` dkk) yang di sub-view `iocmgmt` legacy dimuat
BARENGAN pas view dibuka (`intel.js:28`), bukan sub-tab terpisah --
disusun vertikal di satu halaman di sini juga (tabel utama di atas,
Allowlist+FP Analytics di bawah), niru urutan muat legacy apa adanya.
Backend (`routers/iocs.py` 424 baris) udah lengkap dari Fase 7.3+7.4
Grup D, tapi survei baca kode nemuin **2 gap nyata** (bukan dead code
kayak G1 -- field/param yang MESTINYA ada tapi ketinggalan pas port):

1. **`enrichment` (TIP provider payload) ada di model IOC
   (`ioc.enrichment`, JSONB) tapi `_serialize_detail()` gak pernah
   nyertain di respons** -- UI `_renderIocEnrichment()` di legacy
   nunggu field itu, jadi tanpa fix bakal selalu kosong walopun data
   provider ada. Fix: tambahin `"enrichment": ioc.enrichment or None`
   ke `_serialize_detail()` (`routers/iocs.py`).
2. **Filter `actionability` di `list_iocs()` gak pernah diport** --
   docstring `list_filtered()` bilang "sengaja gak diport, gak ada
   kolomnya di skema baru", TAPI itu docstring BASI: kolom
   `actionability_label` UDAH ada sejak Fase 7.4 Grup D nambahin
   confidence/actionability scoring. Filter client-side-only bakal
   ngerusak paginasi (total count gak sinkron sama hasil ke-filter).
   Fix: wire `actionability` jadi query param asli
   (`AsyncIOCRepo.list_filtered(actionability=...)` + `WHERE
   IOC.actionability_label == actionability`), regen
   `docs/openapi.json`+`schema.d.ts` (`pnpm run gen:api`), update
   docstring basi.

Dua fix ini KECIL (dalam blast radius satu router+satu repo method,
no migration) tapi WAJIB biar frontend gak port fitur yang keliatan
jalan padahal diam-diam gak pernah ngirim data sebenernya (enrichment)
atau nge-filter di client dengan paginasi rusak (actionability).
Snapshot test `test_iocs_router_snapshot.py` di-update (`enrichment:
None` nongol di 2 snapshot) -- 72 test terkait IOC lolos abis fix.

**Dibangun**:
- **IOC Table** -- stat bar per-tipe (klik buat filter, 9 tipe: IP/
  Domain/URL/URL+Path/Email/SHA256/SHA1/MD5/CVE, warna literal per
  tipe port apa adanya sama kayak keputusan heatmap MITRE G3, bukan
  token Tailwind diskrit -- nuansanya sengaja beda tiap tipe buat scan
  cepat), filter search/type/actionability/sort/page size, feedback
  👍/👎 inline (invalidate query abis submit, BUKAN manual DOM-patch
  kayak legacy -- lebih idiomatik React, query cache yang jadi source
  of truth).
- **IOC Detail Dialog** -- badge tipe/confidence/actionability, delete
  (via `ConfirmDialog`, BUKAN `window.confirm()` browser native --
  satu-satunya di app ini yang legacy-nya pake native confirm, diganti
  biar konsisten sama seluruh app), recommended_action banner, stat
  grid (seen/first/last), tags, TIP enrichment cards (provider
  score/verdict/malware families/tags -- baru bisa dirender abis fix
  gap #1 di atas), TA links (list + add/remove manual tag + badge
  WATCHED/ATT&CK-group-id/MANUAL sumber), linked articles.
- **IOC Allowlist** -- add (type url_domain/email_domain/ip + value) +
  tabel + remove. **Perbedaan sengaja dari legacy**: toast "Added to
  allowlist" TANPA klaim "N existing IOC dihapus" -- backend
  `AsyncIocAllowlistRepo` punya docstring eksplisit "SENGAJA gak port
  `_sweep_delete_matching()`" (filtering sekarang kejadian di
  EXTRACTION time, bukan sweep retroaktif), jadi field
  `deleted_iocs` yang legacy harapkan emang gak pernah ada di respons
  -- pesan UI disesuaikan biar gak klaim sesuatu yang gak kejadian.
- **FP Analytics** -- FP rate by source + by type (progress bar warna
  by threshold), suggested allowlist entries (>=3 FP, 0 TP) + "Apply
  All" (`ConfirmDialog`, warning text disesuaikan sama alasan di atas
  -- BUKAN "matching IOCs will be deleted" kayak legacy, karena
  `apply-suggestions` cuma manggil `create()` yang sama, gak ada sweep
  delete juga).

**0 bug live selain 2 gap backend di atas** (yang keduanya kefix
sebelum frontend nyentuh sama sekali, bukan ketemu pas testing UI).

Verifikasi LIVE end-to-end (tab baru, session admin1 masih valid): 92
IOC real ke-load, stat bar filter (klik CVE -> 8 IOCs, semua tipe
CVE match). Detail dialog CVE-2026-5426 -> Add TA "Test Actor G4" ->
count 0->1, badge MANUAL muncul -> Remove -> balik ke 0 (round-trip
POST/DELETE `/threat-actors` bersih). Feedback TP pada IOC id=90 ->
`confidence_score` 50->95, `actionability_label` null->"monitor"
(verified via fetch langsung ke endpoint detail) -- **direvert manual
lewat SQL** abis testing (DELETE row `ioc_feedback` + UPDATE kolom
`iocs` balik ke nilai semula) karena gak ada endpoint "undo feedback"
di router, IOC ini data seed lama yang dipakai testing Grup lain juga.
Allowlist add "test-g4-allowlist.example" -> muncul di tabel (Added
By: admin1) -> remove -> hilang, bersih. Filter Actionability
"block_now" pada IOC type=CVE -> `GET /api/iocs?...&actionability=
block_now` beneran ke-kirim ke backend (bukan diem-diem di-drop) ->
hasil 0 IOCs (kedelapan CVE itu semua "monitor", bukan "block_now") --
konfirmasi filter server-side REAL, bukan no-op. Console bersih
(1 warning 405 ternyata dari debug `fetch()` manual sendiri via
`javascript_tool`, bukan dari kode app). `pytest tests/ -k ioc`: 72
lolos. `pnpm build`/`tsc --noEmit`/`pnpm lint` semua bersih.

### Grup G5 -- selesai (2026-09-25)

Beda dari G1-G4: **G5 BUKAN sub-route `/intelligence` baru** -- ini
komponen BERSAMA (`docs/PROGRESS.md` Fase 8 breakdown: "komponen
Mindmap, dipakai bareng G6/G7/Newsletter/CVE-ticket"), niru
`mindmap.js` (379 baris) yang di legacy juga berdiri sendiri lepas
dari tab manapun (dipanggil dari `clusters.js`/`ta.js`/`cve.js`).
Backend (`routers/mindmap.py` 106 baris + `services/mindmap.py` 317
baris, 6 builder: newsletter/threat_actor/cve/pir/ransomware/cluster)
udah lengkap dari Fase 7.3-7.4 -- murni build frontend + wiring.

**Riset penting** -- grep `mmInlineWidget`/`mmToggleInline`/
`mmOpenEditor` lintas SEMUA file `legacy/static/js/` buat mastiin
di mana widget ini BENERAN kepake di UI (bukan cuma backend builder-nya
ada), ketemu CUMA 3 call site: `clusters.js` (feature_type `cluster`,
pola toggle inline), `ta.js` 2x (feature_type `threat_actor`, pola
toggle inline), `cve.js` (feature_type `cve`, pola BEDA -- satu tombol
`generateCveMindmap()` langsung buka editor, TANPA toggle inline).
`pir`/`newsletter`/`ransomware` builder ADA di backend tapi **NOL call
site ditemukan di UI legacy manapun** -- sama presedennya kayak
`source-scores`/`wisemap_service` (G1/survei 2026-09-19): backend
siap tapi frontend legacy emang gak pernah makenya, jadi TIDAK
diwire di sini juga (bukan lupa, port apa adanya).

**Dibangun**:
- **`renderMindmap()`** (`lib/mindmap/render.ts`) -- port `_mmRender()`/
  `_mmInjectColors()` byte-identik: init `mermaid.js` (npm package
  BARU, `mermaid@12`, belum ada dependency sebelumnya) tema dark +
  font mono sekali (module-level flag), render syntax ke SVG, inject
  `<style>` warna literal per-level (`_MM_LEVEL_COLORS`, 6 warna) ATAU
  satu warna custom kalau `nodeBg` di-set -- port apa adanya, BUKAN
  token Tailwind (sama keputusan kayak heatmap MITRE G3).
- **`lib/mindmap/colors.ts`** -- preferensi warna per-viewer di
  `localStorage` (port `_mmLoadColors()`/`_mmSaveColors()`), BUKAN
  state server -- benar-benar per-browser kayak legacy, gak sinkron
  lintas device/analyst.
- **`MindmapEditorDialog`** -- editor full-layar (`max-w-[95vw] h-[90vh]`):
  color picker node (+ toggle "Auto" balik ke level-colors) & font,
  textarea syntax + preview live (debounce 400ms), Save (`PUT`, timpa
  `custom_syntax`) + Regenerate (`POST .../regenerate`, timpa balik ke
  hasil builder, `custom_syntax` ke-reset null). Body dialog cuma
  MOUNT pas `open` (`key={featureType:docId}` maksa remount fresh)
  daripada `useEffect` buat reset state pas dibuka ulang -- ke-flag
  `react-hooks/set-state-in-effect` pas lint pertama kali, difix
  dengan pola yang sama kayak `NoteForm` PIR Grup G2 (mount baru =
  state fresh otomatis, gak butuh sinkronisasi effect).
- **`MindmapWidget`** -- toggle inline + tombol edit (port
  `mmInlineWidget()`/`mmToggleInline()`), disiapkan buat G6 (Threat
  Actor Room)/G7 (Campaign Clusters) yang bakal makenya -- BELUM ada
  consumer live hari ini (kedua Grup itu belum dibangun), jadi belum
  bisa live-tested lewat UI asli, tapi logic render/color-nya SAMA
  persis kayak `MindmapEditorDialog` yang UDAH live-tested (lihat di
  bawah) -- risiko rendah.
- **Wiring 1 consumer yang UDAH ada**: `CveDetailModal` (`cve.js:1149-
  1155`'s `generateCveMindmap()`) -- tombol "⬡ Mind Map" di header
  modal, langsung buka `MindmapEditorDialog` (bukan toggle inline,
  match perilaku asli CVE). Komentar deferred lama ("Mind Map button
  DIDEFER -- nunggu Grup G5") dihapus, diganti penjelasan wiring-nya.

**0 bug live**. Satu fix lint (bukan bug fungsional) diceritain di atas
(`set-state-in-effect`).

Verifikasi LIVE end-to-end (tab existing, session admin1 masih valid,
dev server di-restart dulu -- user stop manual sebelum sesi ini): buka
CVE-2026-12956 -> Mind Map -> editor kebuka, syntax REAL ke-generate
dari data CVE asli (Severity/Published/Tech/Affected), preview render
mindmap SVG level-colors (root merah, Overview oranye, dst) -- match
persis warna legacy. Toggle "Auto" -> off -> SEMUA node ganti jadi 1
warna biru custom instan (live preview, gak nunggu save). Save -> `PUT
/api/mindmap/cve/CVE-2026-12956` 200, toast "✓ Saved", query
invalidate+refetch. Regenerate -> `POST .../regenerate` 200, "✓
Regenerated", syntax balik ke hasil builder segar (`custom_syntax`
ke-reset null di DB -- gak ninggalin data test kotor, beda dari
feedback IOC G4 yang butuh revert manual). Buka CVE KEDUA
(CVE-2026-13359) -> state FRESH sepenuhnya (warna balik ke Auto/level,
bukan nyisa warna biru custom CVE pertama) -- konfirmasi
`key={featureType:docId}` remount jalan bener, gak ada state bocor
antar dokumen. Console bersih di kedua percobaan. `pnpm build`/
`tsc --noEmit`/`pnpm lint` semua bersih.

### Grup G6 -- selesai (2026-09-25)

`/intelligence` sub-grup keenam: **Threat Actor Room** (Tracked Groups
+ Whitelist + Watchlist + profil TA AI-generated + activity timeline).
Legacy: `ta.js` (1103 baris, terbesar di antara semua Grup G sejauh
ini) -- 3 sub-view (`taSwitchView()`) ditambah modal profil terpisah
(10 section terstruktur) dan Mind Map (consumer PERTAMA dari
`MindmapWidget` G5 yang beneran ke-pasang, sesuai rencana). Backend
(`routers/ta_groups.py` 358 baris, fully typed Pydantic response
model, + `services/ta_profile.py` 297 baris LLM profiler + repo 487
baris) udah lengkap dari Fase 7.3 -- murni build frontend.

**Riset penting**: `requireTAAuth()` (legacy, popup re-entry password
sebelum aksi privileged) dikonfirmasi RELIK sistem auth LAMA (Bearer
JWT localStorage) -- app baru udah punya session cookie httpOnly
(`require_auth` di semua endpoint tulis), jadi popup itu SENGAJA gak
diport, backend 403 yang nge-gate kalau somehow gak authenticated
(`AppLayout` udah blokir akses unauth duluan). Desain keputusan:
`MindmapWidget` (toggle+edit) dipasang di WATCHLIST CARD juga, padahal
legacy card cuma punya toggle-only (hand-rolled, gak lewat
`mmInlineWidget()`) -- disatuin ke komponen bersama biar konsisten,
bukan pertahanin 2 implementasi toggle mindmap yang beda (deviasi
kecil disengaja, bukan port apa adanya).

**1 bug backend nyata ketemu LIVE** (bukan frontend): `AsyncTARepo.
get_by_name_ci()` (`packages/cti-core/.../repositories/ta.py:37`)
pakai `scalar_one_or_none()` tanpa unique constraint di
`lower(name)` -- tabel `threat_actor_groups` cuma unique di `name`
mentah, jadi 2 baris case-variant (`"APT41"` id=1 vs `"apt41"` id=99,
data seed lama dari sesi sebelumnya) bikin query nemu 2 baris dan
CRASH 500 (`MultipleResultsFound`) tiap kali Mind Map widget dibuka
buat threat actor manapun yang kena tabrakan case. Fix: ganti ke
`.limit(1)` + `.scalars().first()` -- ambil satu baris deterministik,
gak butuh migration atau hapus data. Confirmed via traceback live,
BUKAN tebakan -- 46 test `-k "ta_group or ta_profile or threat_actor
or mindmap"` tetep lolos abis fix.

**Dibangun**:
- **Tracked Groups** -- tabel sort klik-header (Name/Added Date/
  Source, beda dari Watchlist yang `<Select>` karena ini tabel
  beneran), search, Add (validasi whitelisted/duplicate dari backend),
  toggle Watch/Unwatch inline, Remove (`ConfirmDialog`, whitelist
  otomatis + gak bisa di-re-add).
- **Whitelist** -- tabel grup yang di-remove, Restore (`ConfirmDialog`)
  ngehapus dari whitelist (BUKAN muncul lagi di Tracked otomatis --
  restore cuma buka jalan buat di-Add ulang manual, sama presedennya
  kayak legacy).
- **Watchlist** -- card grid (BUKAN tabel), tiap card ngecek profile
  existence + article count PARALEL (`useQueries`, port
  `Promise.allSettled` legacy), dormancy badge (ACTIVE/DORMANT/
  RESURGENT, 3 warna), AI Generate -> buka Profile Dialog otomatis
  abis sukses (match legacy), View Profile, Mind Map (`MindmapWidget`),
  tombol artikel (disabled kalau 0), Unwatch, "Open in Navigator"
  (export TTP coverage watchlist ke MITRE Navigator eksternal --
  keterbatasan cross-origin auth yang sama kayak G3, diwarisi bukan
  bug baru).
- **Profile Dialog** -- 10 section (Identity/Motivation/Targeting/
  Capability/Infrastructure/Campaign History/Detection & Defense/Org
  Relevance/Gaps/References) + meta chips (actor type/confidence/TLP/
  nation) + Activity Timeline (`TAActivityTimelineChart`, Chart.js 3
  series stacked+filled: Articles/Tweets/Ransom, + state transitions
  DORMANT<->ACTIVE<->RESURGENT) + Regenerate (invalidate profile+
  watchlist query, refresh badge card) + `MindmapWidget`. Field
  enrichment backend (`_confirmed`/`_article_cves` dari
  `_enrich_profile_cves()`) SENGAJA gak dirender -- legacy
  `_renderProfileBody()` juga gak pernah nampilin field itu (data
  dihitung tapi gak pernah disurface UI, presenden sama kayak
  `enrichment` IOC G4 tapi arah kebalik: di sini backend LEBIH kaya
  dari yang ditampilin, bukan lebih miskin).
- **Articles Dialog** -- `GET /api/articles?threat_actor=...`, pola
  sama persis kayak `PirArticlesDialog` G2 (title+url, source/
  posted_on/news_type, pager).

Verifikasi LIVE end-to-end (tab existing, session admin1 masih valid,
dev server di-restart abis user stop manual sebelum sesi ini): 3992
grup TA real ke-load (stats bar match). Watch APT41 dari Tracked ->
muncul di Watchlist card (RESURGENT, "1 Article", NO PROFILE) -> AI
Generate -> LLM call ~20 detik -> profil REAL ke-generate (nation-state/
China/MITRE G0096/alias Winnti+BlackFly+Wicked Panda+Axiom/malware
Poison Ivy+Winnti+ShadowPad+DarkSide/TTP lengkap per-tactic) -> Profile
Dialog kebuka OTOMATIS -> timeline chart render (DORMANT->ACTIVE
transition beneran dari data artikel) -> **Mind Map widget crash 500**
(bug di atas, langsung ke-debug+fix+verify ulang LIVE -> mindmap
render sukses, warna level, semua branch keisi data profil real) ->
Edit Mindmap -> editor+preview jalan (pola sama kayak G5). Round-trip
Add ("Test Actor G6 Round Trip") -> Remove (whitelist) -> muncul di
Whitelist tab -> Restore -> bersih total (3992/1 balik ke baseline,
gak ninggalin data test). Console bersih (4 error 500 sisa DARI
SEBELUM fix, gak ada error baru abis fix). `pytest -k "ta_group or
ta_profile or threat_actor or mindmap"`: 46 lolos abis fix.
`pnpm build`/`tsc --noEmit`/`pnpm lint` semua bersih.

### Grup G7 -- selesai (2026-09-25) -- Grup G (`/intelligence`) KOMPLET

`/intelligence` sub-grup ketujuh, TERAKHIR dari Grup G: **Campaign
Clusters**. Legacy: `clusters.js` (907 baris) + bagian atas `intel.js`
(148 baris) -- ternyata DUA pipeline TF-IDF independen numpang di dua
sub-view berbeda (`intelSwitchViewAndLoad`'s dispatch table):
- **`clusters`** (Pipeline 1, `cti_api.services.cluster`) -- greedy
  fixed-centroid, threshold TUNABLE (0.2-0.7), DI-PERSIST ke tabel
  `clusters` (cache 900s), **manual-generate ONLY** (komentar legacy
  eksplisit: "do not auto-load on tab switch").
- **`campaigns`** (Pipeline 2, `cti_api.services.campaign`) --
  union-find, threshold TETAP 0.75, enrichment kaya (severity/kill
  chain/diamond model/prioritized CVE/matched PIR/campaign links),
  NOL cache/persist, **auto-load**.

Backend (`routers/intelligence.py` 139 baris + 7 service file,
~1770 baris total: `cluster`/`campaign`/`campaign_analysis`/
`campaign_trend`/`diamond_model`/`geopolitical`/`cluster_tokenize`)
udah lengkap dari Fase 7.4 Grup A (2026-09-23) -- murni build
frontend, TANPA nyentuh backend sama sekali (beda dari G4/G6 yang
masing-masing nemuin 1 bug backend nyata).

**Riset penting**: grep `clusters/evolution`/`campaign_evolution`
lintas SEMUA `legacy/static/js/` -- NOL match. Endpoint
`GET /clusters/evolution` ada di backend tapi gak PERNAH dipanggil UI
legacy manapun (beda dari `/intelligence/geopolitical` yang awalnya
dikira sama tapi TERNYATA dipakai -- panel collapsible DI DALAM view
Campaigns, `loadGeopoliticalOverview()`). Sama presedennya kayak
`pir`/`newsletter`/`ransomware` mindmap builder G5 -- sengaja gak
diwire, backend siap tapi frontend legacy emang gak pernah makenya.

**Dibangun**:
- **Clusters (Simple)** -- filter days/threshold/exclude-low-
  reliability, tombol Generate manual, card expand/collapse per
  cluster, sparkline SVG tanggal artikel, badge spike-match (baca
  `/api/spikes` paralel) + re-emerging, toggle "show single-source".
- **Campaigns** -- filter days/min_size, sort bar (size/velocity/
  severity/first_seen/last_seen), tabel expand-row: severity
  breakdown (5 faktor weighted bar), kill chain coverage (12 fase
  MITRE, segmen visual), Diamond Model (4 kuadran + expand detail
  penuh per-tactic -- data TA di kuadran Adversary/Victim PULL
  LANGSUNG dari TA profile G6 kalau ada, integrasi cross-Grup nyata),
  matched PIRs (buka `ClusterPirDialog`, numpang `PirArticlesDialog`
  G2 lewat objek minimal `{id,title}`), member articles (`ArticleModal`
  Grup D lewat wrapper fetch-by-id), IOCs, prioritized CVEs, Mind Map
  (`MindmapWidget` G5, consumer KEDUA), related campaigns (jump-to
  scroll+expand), Hunt Pack (download JSON client-side, tanpa request
  backend). Panel Geopolitical Overview collapsible (alert list,
  heatmap nation×sector, motivation breakdown bar) di atas tabel.
- **Deviasi disengaja dari legacy** (dicatat eksplisit di kode, BUKAN
  port apa adanya):
  1. CVE chip klik -- legacy `openCveDetail()` cross-tab (SPA satu-
     halaman lama bisa buka modal CVE Tracker dari tab manapun). Di
     sini `/cve` sub-route TERPISAH (keputusan arsitektur Fase 8), gak
     ada state cross-page -- diganti buka NVD langsung.
  2. Nation×sector heatmap -- `nation_state_activity[nation].
     targeted_sectors` backend DEDUP per nation (beda dari legacy yang
     gak dedup), jadi heatmap di sini jadi biner (terisi/kosong) bukan
     gradasi intensitas -- BUKAN bug baru, warisan data-shape Fase 7.4
     Grup A yang udah lama commit, logic hitung diport apa adanya,
     cuma hasil visualnya beda dari desain original.

**1 bug ketemu LIVE, tapi di kode SENDIRI (bukan backend)**: query
spike `SimpleClustersPanel` awalnya port literal legacy
`lookback_days=7` (`intel.js:118`) mentah-mentah -- TERNYATA backend
BARU (`GET /api/spikes`, di-establish Grup G1) punya constraint
`Query(30, ge=14, le=90)` yang lebih ketat dari backend lama, jadi
`lookback_days=7` selalu 422. Fix: pakai nilai minimum valid (14),
dicatat di komentar kenapa beda dari literal legacy.

**0 bug backend** -- konsisten sama G3/G5 (Grup yang gak nyentuh
backend sama sekali), beda dari G4/G6.

Verifikasi LIVE end-to-end (tab existing, session admin1 masih valid):
Clusters (Simple) -- `days=90` nemu ULANG cluster REAL dari Fase 7.4
Grup A (UNC6671/Russia, 2 artikel Mandiant, `source_count=1` makanya
butuh toggle "show single-source" buat muncul -- BUKAN bug, port apa
adanya dari filter default legacy), expand nunjukin 2 artikel asli
lengkap source+tanggal. Campaigns -- default `days=7,min_size=3`
kosong (0.75 threshold Pipeline 2 emang jauh lebih ketat dari 0.35
Pipeline 1, gak ada campaign yang lolos di dataset asli ini, expected
per catatan verifikasi Fase 7.4 Grup A). **Seed 2 artikel test**
("APT41 breaches Philippine government...", judul sengaja mirip biar
lolos threshold 0.75) + 1 IOC CVE-2025-8088 -> campaign REAL
kebentuk, severity MEDIUM 56 (TA Sophistication 100 -- PULL LANGSUNG
dari profil APT41 asli hasil generate G6, bukan data sintetis),
velocity ACTIVE, kill chain 0%/limited (jujur -- TTP seed pakai nama
teknik tanpa embed ID `T####`, `analyze_kill_chain()`'s regex emang
gak nemu match, bukan bug tampilan), Diamond Model quadrant Victim
nunjukin "gov"/"telco" dari `targeting_profile` asli APT41. Member
Article klik -> `ArticleModal` full data. Mind Map toggle -> render
sukses, confirmed CUMA branch "Stats" keisi (bug cross-pipeline yang
udah didokumentasikan Fase 7.4, direproduksi ulang di sini sebagai
BUKTI port yang jujur, bukan disembunyiin). CVE chip klik -> popup
NVD ke-block browser pane (sandboxing otomatis, bukan bug -- konfirmasi
`window.open()` terpanggil bener). Geopolitical panel toggle -> render
"0 campaigns" gracefully sebelum seed, isi lengkap (alert/heatmap/
motivation) setelah. **1 bug ketemu & fix** (spike query 422) di atas.
Semua data test dibersihin abis verifikasi (artikel+IOC source, raw
SQL DELETE dengan cascade FK yang udah dikonfirmasi `ondelete=CASCADE`
di model). Console bersih abis fix (422 lama, bukan baru). `pnpm build`/
`tsc --noEmit`/`pnpm lint` semua bersih.

**Grup G (`/intelligence`) KOMPLET**: G1 Risk Matrix+Source
Reliability+Early Warning, G2 PIR+RFI, G3 MITRE Heatmap+ATT&CK DB, G4
IOC Management, G5 komponen Mindmap bersama, G6 Threat Actor Room, G7
Campaign Clusters -- 7 sub-grup, 9 sub-route `/intelligence/*`, ~30
komponen baru, 2 bug backend nyata ketemu+fix (G4 enrichment+
actionability, G6 `get_by_name_ci` MultipleResultsFound), 0 bug
backend di G3/G5/G7.

### Grup H -- selesai (2026-09-25) -- `/newsletter`, route ke-9, Fase 8 KOMPLET

Port `ScraperNewsWeb/templates/newsletter.html` (1261 baris, satu file
HTML+JS standalone, route berdiri sendiri di app lama -- BUKAN tab).
Backend (`routers/newsletter.py`, `services/newsletter.py`, builder
`newsletter` di `services/mindmap.py`) udah lengkap ke-port sejak Fase
7.3 Bagian 4 -- Grup H murni kerjaan frontend, 0 endpoint baru, 0
regenerate OpenAPI.

**Baca legacy dulu, ketemu 2 blok dead code signifikan** -- `init()`
cuma manggil `checkAuth()`/`loadPaywallHints()`/`renderSections()`/
`renderQueuedArticles()`, GAK PERNAH manggil `loadArticles()` (search
artikel via `/api/articles?search=...`). Fungsi itu ADA di file tapi
elemen HTML yang dipakainya (`#f-search`/`#f-date-start`/`#btn-prev`/
dst) GAK ADA di markup -- artinya satu-satunya jalur artikel masuk ke
composer beneran cuma queue `localStorage.newsletter_queue` (diisi dari
Newsroom). Kedua, `_renderQueueBanner()`/`toggleQueueBanner()`/
`loadNewsroomQueue()` (mekanisme banner alternatif, referensi elemen
`#queue-banner`/`#queue-toggle-btn` yang JUGA gak ada di markup) --
sisa iterasi UI lama yang ketinggalan, tumpang tindih sama
`renderQueuedArticles()` yang beneran jalan. Kedua blok ini SENGAJA gak
diport, sama prinsip kayak `requireTAAuth()` G6 -- port perilaku yang
kebukti hidup, bukan tiap baris kode yang ada di file.

**Ketemu kontrak queue yang UDAH disiapin dari Grup D** -- `article-
modal.tsx` (Newsroom, dibangun jauh sebelum Grup H) udah punya tombol
"+ Newsletter" nulis ke `localStorage["newsletter_queue"]` persis
kontrak lama (`{...article, _id: article.id}`). Grup H tinggal
KONSUMSI key itu, gak nulis ulang. Logic queue lokal di
`article-modal.tsx` (`queueForNewsletter()`) diekstrak jadi
`lib/newsletter/queue.ts` (`getQueue`/`addToQueue`/`removeFromQueue`/
`clearQueue`) SATU sumber, `article-modal.tsx` di-refactor numpang itu
juga -- bukan fitur baru, cuma nyatuin 2 salinan logic yang sama biar
gak drift.

**Dibangun**: `NewsletterQueuePanel` (kartu queue + dropdown assign
Highlight/APAC/Global/Indonesia, paywall hint dari `/source-hints`),
`NewsletterComposerSections` (4 section slot filled/empty + analyst
note per artikel, port `renderSection()`), `NewsletterTemplatePanel`
(collapsible custom CSS/intro/footer + toggle "Include Top Campaign
Clusters" -- jalan nyata sejak Fase 7.4 Grup A), `NewsletterPreviewDialog`
(SATU dialog dipakai 2 mode -- "compose" hasil `POST /preview` dari
draft yang lagi disusun, "saved" hasil `GET /{id}/html` dari histori,
port `openPreview()`/`previewSaved()` yang di legacy numpang modal
sama), `NewsletterHistoryPanel` (collapsible, port drawer bawah jadi
panel biasa -- `/newsletter` sekarang route App Router biasa, bukan
Jinja standalone page yang butuh `position:fixed` drawer sendiri, sama
simplifikasi kayak `GeopoliticalPanel` G7). "Mind Map" per histori
numpang `MindmapWidget` (G5) langsung -- GANTI modal bespoke
`_nlShowMindmapModal()`/`_nlMmEdit()`/`_nlMmSave()` legacy (~120 baris
JS custom), konsisten sama pola inline-toggle G6/G7. Ini konsumer
KE-4 `MindmapWidget` dan yang PERTAMA numpang `featureType="newsletter"`
-- builder-nya udah ada di backend sejak G5 tapi waktu itu 0 call site
legacy (dicatat G5 sebagai "backend-only"), sekarang materialisasi di
sini.

**Validasi payload port apa adanya** dari `buildPayload()` -- wajib ada
Highlight, wajib minimal 1 artikel APAC atau Global, `notes` keyed
`String(article.id)` (backend docstring eksplisit nyebut ini pola yang
sama kayak dulu `String(ObjectId)`).

**0 bug backend** -- Grup H gak nyentuh backend sama sekali (sama
kayak G3/G5/G7).

Verifikasi LIVE: queue 2 artikel real (APT41 Philippines, Zero Trust
best-practices) dari Newsroom lewat tombol "+ Newsletter" yang UDAH
ada -- muncul benar di `NewsletterQueuePanel`. Assign artikel 1 ->
Highlight, artikel 2 -> Global lewat dropdown -- toast konfirmasi,
queue berkurang, slot section keisi, textarea analyst note nulis. Klik
Preview -> `POST /api/newsletter/preview` 200 OK, HTML hasil beneran
lewat pipeline enrichment penuh (Playwright fetch body + LLM
summarize + IOC extract) -- key points/summary asli ke-generate,
analyst note ke-embed persis di kartu Highlight, newsletter tersimpan
`id=1`. **Tombol "Send Draft Email"/"Resend" SENGAJA gak diklik pas
verifikasi** -- keduanya manggil `cti_alerts.mailer.create_graph_draft`
beneran (nulis draft ke mailbox Graph API asli, efek eksternal di luar
DB lokal), di luar scope yang aman buat dites otomatis tanpa
konfirmasi eksplisit; endpoint-nya sendiri udah live-tested waktu
backend-nya diport Fase 7.3 Bagian 4. Verifikasi jalur baca lain lewat
API langsung (bukan klik UI, browser pane lagi dipakai bareng): `GET
/api/newsletter/history` balikin shape `sections` persis yang
dideklarasikan di `loose-types.ts`, `GET /api/mindmap/newsletter/1`
generate Mermaid syntax REAL merefleksikan isi newsletter yang baru
disusun ("Highlights 1" / "Global News 1" node), `GET
/api/newsletter/1/html` balikin HTML tersimpan 9111 char. Data test
(`newsletters` id=1 + `mindmaps` baris terkait) dibersihin raw SQL abis
verifikasi (gak ada FK yang nunjuk ke `newsletters`, aman). `pnpm
build`/`tsc --noEmit`/`pnpm lint` semua bersih, route `/newsletter`
muncul di build output (28 route total).

**Fase 8 KOMPLET**: 9 route (`/dashboard` Grup B, `/newsroom` Grup D,
`/cve` Grup E, `/intelligence` Grup G 7 sub-grup, `/exec` Grup F,
`/xintel` Grup C, `/recap` Grup B, `/admin/users` Grup C, `/newsletter`
Grup H) -- 8 route awal + 1 gap nyata dari survei, semua selesai.

### Checklist

- [x] **8.1** Setup Next.js App Router + TS + keputusan arsitektur di atas
- [x] **8.2** Generate client API dari OpenAPI (`docs/openapi.json` udah
      siap dari Fase 7.7)
- [x] **8.3** Auth + session (Grup A)
- [x] **8.4** Route: `/dashboard` (Grup B, selesai) `/newsroom`
      (Grup D, selesai) `/cve` (Grup E, selesai, +Mind Map G5)
      `/intelligence` (G1 -- Risk Matrix+Source Reliability+Early
      Warning, G2 -- PIR+RFI, G3 -- MITRE Heatmap+ATT&CK DB, G4 -- IOC
      Management, G5 -- komponen Mindmap, G6 -- Threat Actor Room, G7
      -- Campaign Clusters -- SEMUA selesai, Grup G komplet)
- [x] **8.5** Route: `/exec` (Grup F, selesai) `/xintel` (Grup C, selesai)
      `/recap` (Grup B, selesai) `/admin/users` (Grup C, selesai)
      `/newsletter` (Grup H, selesai)
      *(route ke-9, ditambahin dari survei -- gap nyata, bukan revisi
      scope sepihak)*
- [x] **8.6** Halaman control plane scraper -- selesai Fase 9 Grup H4
      (`/scrapers`, 2026-09-25), bukan digabung `/dashboard` -- keputusan
      user, halaman sendiri

**Exit criteria:** tiap tab lama ada padanannya · `static/` lama dipakai sebagai spesifikasi perilaku, bukan di-port

---

## Fase 9 — Control plane scraper `[x]`

### Survei (2026-09-25)

Beda karakter dari Fase 8 -- ini BUKAN port dari legacy (survei Fase 8
udah nyimpulin `scraper.js` cuma 2 widget monitoring read-only, "Fase 9
GAK PUNYA preseden kode buat di-port -- desain dari nol"). Survei fokus
ke state SEKARANG framework `cti-scraper` (Fase 3-4), bukan baca legacy.

**Yang udah ada (fondasi solid)**: framework scraper penuh (84 scraper
terdaftar: 60 `light`/httpx + 24 `browser`/Playwright), skema DB 4 tabel
persis plan §8 (`ScraperRun` heartbeat, `ScraperItem` log accept/reject,
`ScraperConfig` override enable/disable/schedule/rate_limit/max_items,
`ScraperSeen` dedup), task Celery `scrape.run` yang docstring-nya SENDIRI
udah bilang "control plane Fase 9 bakal manggil task yang sama",
`cti_alerts.telegram.send_alert()` (fungsi alert konsolidasi udah ada),
placeholder card eksplisit di `/dashboard` ("Scraper Health widget
sengaja belum diisi, nunggu Fase 9").

**Gap nyata**: `ScraperItem`/`ScraperConfig` PUNYA skema tapi NOL kode
yang baca/tulis (grep kosong total di luar `models/scraper.py` sendiri).
`Runner._handle_item()` cuma update counter, gak pernah nulis
`ScraperItem`. Gak ada yang cek `ScraperConfig.enabled` di mana pun --
`ScraperMeta.enabled`'s docstring SENDIRI (Fase 3) udah bilang
"`scraper_config` di DB nge-override runtime, bukan field ini", jadi ini
emang gap yang disengaja ditinggal ke Fase 9. Gak ada router
`/api/scraper/*` (cuma `/healthz` liveness, docstring-nya sendiri bilang
"BUKAN control plane"). Gak ada health-sweep logic. Gak ada frontend.

**2 keputusan dari user (2026-09-25)**: (1) scope Fase 9 = backend +
frontend sekalian, bukan backend doang -- API tanpa UI gak kepake, dan
Fase 8.6 emang nunggu ini buat kelar. (2) `ScraperItem` log SEMUA item
(accept+reject) + purge periodik (bukan reject-doang+sample) -- paling
berguna buat debug, konsisten pola `ScraperSeen`.

**Urutan kerja**: H1 (data layer+worker wiring) -> H2 (read+trigger API)
-> H3 (config write API+health sweep+alert) -> H4 (frontend dashboard
widget) -> H5 (frontend halaman control plane penuh).

### Grup H1 -- selesai (2026-09-25) -- data layer + worker wiring

Migration `scraper_items.expire_at` (kolom baru, tabel kosong -- gak ada
kode yang pernah nulis ke sini sebelum ini). `ScraperItemRepo`/
`AsyncScraperItemRepo` (create/list_by_scraper/list_by_run/purge_expired)
+ `ScraperConfigRepo`/`AsyncScraperConfigRepo` (get/get_all/upsert pakai
sentinel `UNSET` biar `None` tetep bisa berarti "hapus override"/reset)
di `cti_core.db.repositories.scraper` -- numpang file yang sama kayak
`ScraperRunRepo` (satu domain "control plane scraper"). `AsyncScraperSeenRepo.
reset_scraper()` ditambahin buat endpoint reset-dedup (H2 nanti) --
versi sync-nya (`reset_scraper()`) udah ada dari Fase 3, cuma belum ada
padanan async buat dipanggil router.

**`Runner` (`cti_scraper/runner.py`) di-wire 3 hal**: (1) `execute()`
baca `ScraperConfig` di awal, `enabled=False` short-circuit SEBELUM
`_run_body()` (gak ada fetch/HTTP/dedup sama sekali) langsung nulis
heartbeat `status="disabled"`, ditambahin ke `_TERMINAL_STATUSES`. (2)
`rate_limit`/`max_items` override via `dataclasses.replace()`. (3)
`_handle_item()` nulis `ScraperItem` buat SEMUA 3 outcome (accept/
duplicate-drop/sink-fail) lewat helper baru `item_display.
display_title_url()` (dispatch per tipe `Item` -- `ArticleItem`/
`TweetItem`/`RansomwareVictimItem`/`CveItem`/`CvePocItem`/
`MalwareTrendItem`/`IocFeedItem`, fallback generik buat tipe custom masa
depan) buat judul+URL yang "cukup manusiawi" di log. Item-log write
best-effort (kegagalan nulis baris log TIDAK BOLEH nggagalin run yang
udah kelar).

**`beat.py`** baca `ScraperConfig` (SATU query, `_scraper_configs()`)
pas `build_beat_schedule()` jalan -- `enabled=False` skip entri dari
schedule (gak buang-buang dispatch Celery), `schedule` override
dipakai kalau ada. Efeknya baru keliatan abis restart worker/beat
berikutnya (gak ada scheduler dinamis yang polling DB tiap tick, gak
ada kebutuhan nyata yang minta itu sekarang) -- `Runner.execute()` TETAP
cek ulang `enabled` pas eksekusi beneran, jaring pengaman buat race
antara beat-build dan tick berikutnya ATAU trigger manual (API, H2) di
luar beat sama sekali. Task `scrape.run` sekarang terima param `trigger`
(default "beat") -- sebelumnya di-hardcode, blocker buat trigger manual
API kirim `trigger="manual"`.

**2 gap tambahan ketemu+fix sekalian** (bukan diminta, ketemu pas baca
kode buat wiring di atas): `ScraperSeenRepo` gak punya `purge_expired()`
sama sekali -- model docstring-nya SENDIRI (Fase 3) udah nyebut
"dibersihin task Celery periodik (Fase 6: cti.maintenance.
purge_expired_seen)", tapi task itu gak pernah beneran ditulis (grep
kosong total) -- baris in-flight (1 hari)/committed (`dedup_ttl_days`,
default 180) numpuk dari hari pertama deploy sampai sekarang. Ditambahin
`purge_expired()` + task `scraper.purge_expired_seen` (crontab 03:15)
bareng `scraper.purge_expired_items` (03:00) punya `ScraperItem`,
keduanya di `tasks/scrape.py` (sync native, bukan `_run_async()` kayak
`tasks/periodic.py` -- manggil repo sync langsung, gak ada layer
`cti_api.services` async yang dibungkus).

**1 bug ketemu di kode sendiri (bukan backend lama, kode BARU sesi
ini)**: override `max_items`/`rate_limit` awalnya cuma nempel ke
`Runner.meta` (`self.meta = dataclasses.replace(...)`), tapi family
(`RSSScraper.fetch()` dkk) baca `self.meta.max_items` dari ATRIBUT
KELAS scraper instance (`BaseScraper.meta: ClassVar[ScraperMeta]`),
BUKAN dari `ctx.meta` atau `Runner.meta` -- override gak pernah nyampe.
**Ketemu LIVE, bukan dari baca kode**: set `ScraperConfig.max_items=2`
buat `bleepcomp`, run beneran, `items_found` tetep 11 bukan 2. Fix:
`scraper.meta = self.meta` (assignment instance, nge-shadow ClassVar
SATU instance scraper itu doang) tepat setelah `scraper = self.scraper_cls()`
dibikin di `_run_body()`. Re-test: `items_found=2`, kombinasi
`enabled=False` (short-circuit tanpa fetch) dan `max_items` override
KEDUANYA diverifikasi ulang lewat scraper real (`bleepcomp`, Bleeping
Computer RSS) via `cti-scraper run` CLI langsung ke DB dev -- bukan cuma
unit test. Data test (config/items/runs/seen row `bleepcomp`) dibersihin
abis verifikasi; dicek dulu gak ada artikel real yang ke-insert (worker
Celery consumer emang lagi mati, task `enrich.article` yang di-publish
ke Redis gak ke-consume, jadi gak ada efek samping nyata ke `articles`).

`pnpm`-nya gak relevan (Fase 9 backend Python doang buat H1). `mypy`/
`ruff check`/`ruff format` semua bersih, 435 test unit+contract existing
tetep lolos (gak ada regresi ke framework scraper yang udah jalan).

### Grup H2 -- selesai (2026-09-25) -- read + trigger API

Router baru `apps/api/src/cti_api/routers/scraper.py` (`/api/scraper/*`,
skema `schemas/scraper.py`) -- 6 endpoint: `GET ""` (list 84 scraper,
`registry.discover()` digabung `ScraperConfig`+run terakhir per scraper
lewat `AsyncScraperRunRepo.latest_per_scraper()`, SATU query `DISTINCT
ON`), `GET /{id}` (detail meta+config), `GET /{id}/runs` + `GET /{id}/items`
(paginated, `items` terima filter `accepted`), `POST /{id}/trigger`
(manual, admin-only), `POST /{id}/dry-run` (admin-only). Read
(`dependencies=[Depends(require_auth)]` di level router) kebuka semua
user login, trigger/dry-run tambahan `require_admin` -- keduanya efek
nyata (trigger beneran jalanin scraper produksi, dry-run mukul situs
eksternal asli), beda dari widget monitoring pasif yang legacy pernah
punya.

**Gap arsitektur ketemu pas nulis trigger endpoint**: `apps/api` gak
depends ke `cti-scraper` sama sekali (pyproject.toml-nya gak nyebut,
padahal butuh `registry.discover()`+`ScraperMeta` buat semua endpoint
baru). Ditambahin `"cti-scraper"` ke `apps/api/pyproject.toml`. Trigger
juga butuh route ke QUEUE yang bener per scraper (`queue_for()`, biar
`send_task()` gak nyasar ke queue default) -- fungsi ini sebelumnya di
`cti_worker.queues` (`apps/worker`), tapi `apps/api` gak boleh depends ke
`apps/worker` (arah dependency sama kayak `cti_core.celery_client`'s
docstring: apps -> packages, bukan apps -> apps lain). Pindahin
`QUEUE_RSS`/`QUEUE_API`/`QUEUE_BROWSER`/`queue_for()` ke `cti_scraper.
queues` (murni fungsi `ScraperMeta`, bukan worker-spesifik) -- `beat.py`
ikut diupdate importnya, `cti_worker.queues` tinggal `QUEUE_ENRICH`/
`QUEUE_NOTIFY`/`QUEUE_MAINTENANCE` (non-scrape). Trigger manggil task
`scrape.run` yang SAMA kayak beat (H1 udah nambahin param `trigger`),
lewat `cti_core.celery_client.get_celery_client()` (producer ringan,
fire-and-forget, result backend gak di-set).

**Regresi environment ketemu (bukan bug kode, gotcha `uv sync` yang UDAH
didokumentasikan sebelumnya)** -- nambah `cti-scraper` ke
`apps/api/pyproject.toml` lalu `uv sync` polos WIPE extra `cti-enrich
[nlp]` (spacy/torch), PERSIS masalah yang dicatat pas Fase 7 Bagian 4
("`uv sync` polos WIPE lagi extra `cti-enrich[nlp]`"). Fix: `uv sync
--all-packages --extra nlp --extra dev` (bukan `--extra nlp` doang dari
root -- `nlp` dideklarasiin di `cti-enrich`'s pyproject sendiri, bukan
root; `--package cti-enrich --extra nlp` juga SALAH, itu nyempitin sync
ke closure dependency `cti-enrich` doang, ngilangin `fastapi`/`mypy`/dst).

**Response schema Pydantic eksplisit** (`ScraperListItem`/`ScraperDetail`/
`ScraperRunOut`/`ScraperItemOut`/`ScraperTriggerResult`/
`ScraperDryRunResult`) -- BUKAN `dict[str,object]` polos kayak
`newsletter`/`recap` (pola itu buat PORT dari kode lama yang emang balikin
dict bebas; Fase 9 desain baru dari nol, jadi langsung model tervalidasi,
ke-generate bersih ke `schema.d.ts` frontend). Dry-run response CUMA
status/items_found/duration_ms/errors (SAMA persis `RunResult` -- CLI
`dry-run` command juga gak nampilin preview item, `_handle_item()` return
langsung tanpa nyimpen apa pun pas `dry_run=True`, nambahin item-preview
bakal nambah state yang gak ada di `RunResult` buat fitur yang gak
diminta).

Live-tested lewat instance API sungguhan (port 8010) + JWT `admin`/
`analyst` racik manual (`cti_api.security.create_token`, bukan tebak
password dev): `GET /api/scraper` -> 84 scraper, `GET /{id}` -> detail
`bleepcomp`, 404 buat id gak ada, `POST /{id}/dry-run` -> `status=ok
items_found=11` cepat (392ms) tanpa nulis DB, `POST /{id}/trigger` ->
`celery_task_id` asli + `queue=scrape.rss` bener + audit log kecatat
(`trigger_scraper`, `admin1`). Auth gating dicek 3 arah: analyst bisa
`GET` (200), analyst DITOLAK `trigger` (403 "Admin role required"), tanpa
token 401. `runs`/`items` (termasuk filter `accepted=false`) diverifikasi
lewat scraper real yang dijalanin ulang via CLI abis dry-run/trigger test.
Data test dibersihin abis (items/runs/seen/audit-log baris `bleepcomp`).
`tsc --noEmit` frontend bersih abis `pnpm run gen:api` (schema baru
ke-generate, belum ada consumer sampe H4/H5).

### Grup H3 -- selesai (2026-09-25) -- config write API + health sweep + alert digest

5 endpoint baru di router yang sama: `POST /{id}/enable`, `POST
/{id}/disable` (body `{reason}` -> `ScraperConfig.paused_reason`), `PUT
/{id}/config` (PATCH-style -- `schedule`/`rate_limit`/`max_items`/
`paused_reason`, `body.model_dump(exclude_unset=True)` biar field yang
gak dikirim client gak kesentuh, numpang sentinel `UNSET` `ScraperConfigRepo.
upsert()` H1), `POST /{id}/reset-config` (hapus SEMUA override, balik ke
default kode), `POST /{id}/reset-dedup` (numpang `AsyncScraperSeenRepo.
reset_scraper()` H1). Semua admin-only + audit log.

**Health sweep** -- modul BARU `cti_scraper/health.py` (FUNGSI MURNI, gak
ada I/O), ditaruh di `cti_scraper` (bukan `apps/api/services`) dari awal
biar `apps/api` (`GET /api/scraper/health`) DAN task digest periodik
(worker) numpang logic SAMA tanpa apps-depends-apps -- pelajaran H2
(`queue_for()`) diterapkan proaktif kali ini, bukan ketemu ulang.
`expected_interval()` pakai `croniter` (udah jadi dependency `cti-scraper`
sejak Fase 3, TAPI GAK PERNAH KEPAKE di mana pun sampai sekarang) buat
ngitung gap 2 fire-time cron terakhir -- bener buat cron kompleks hasil
`spread()` (`"7-59/15 * * * *"`), bukan cuma parsing `*/N` manual.

5 status (`Exit criteria` Fase 9 nyebut 4 -- `disabled` DITAMBAHIN karena
scraper yang sengaja dimatiin operator, beat skip dia total dari
schedule, bakal salah keklasifikasi `dead` seiring waktu tanpa status
ini): `disabled` (`ScraperConfig.enabled=False`), `stale` (gak pernah ada
run), `dead` (run terakhir >3x interval jadwal -- match persis "scraper
yang dimatiin kedeteksi dead dalam 3 interval"), `degraded` (run terakhir
`fetch_error`/`parse_error`/`rate_limited`/`timeout`/`backpressure` --
kedeteksi SATU run, match persis "selector dirusak kedeteksi parse_error
dalam 1 interval", GAK nunggu 3x kayak `dead`), `zero_yield` (3 run
beruntun `status="empty"`), `ok`. `GET /api/scraper/health` (didaftarin
SEBELUM `/{scraper_id}` di router -- FastAPI cocokin berurutan, kebalik
"health" ketangkep jadi `scraper_id`) balikin `counts` per status +
`problems` (subset non-`ok`/non-`disabled`) -- endpoint YANG SAMA yang
ditunggu placeholder "Scraper Health" widget `/dashboard` sejak Grup B.

**Task `scraper.health_digest`** (beat tiap `Settings.worker.
scraper_health_sweep_interval_min`, default 30 menit) -- SATU pesan
Telegram konsolidasi kalau ADA scraper bermasalah, DIAM kalau semua
`ok`/`disabled` (bukan spam tiap tick). Topic BARU `scraper_health`
ditambahin ke `.env.example`'s `TELEGRAM__THREAD_IDS` -- operator wajib
konfigurasi thread_id-nya sendiri, `send_alert()` raise `UnknownAlertTopic`
kalau belum. **SENGAJA gak pernah beneran dipanggil pas verifikasi** --
`.env` dev PUNYA kredensial Telegram ASLI (bot token + chat_id + thread_id
nyata), manggil task ini beneran (atau `send_alert()` langsung) bakal
ngirim pesan ke channel Telegram sungguhan. Logic agregasi (`summarize_
fleet_health()`) diverifikasi lewat `GET /api/scraper/health` (jalur yang
SAMA, tanpa `send_alert()`) + unit-level manual (lihat di bawah).

**1 bug ketemu LIVE** (bukan dugaan) -- `_config_out()` baca `config.
updated_at` abis `upsert()` PAS row-nya UDAH ADA (UPDATE, bukan INSERT):
`sqlalchemy.exc.MissingGreenlet`. `ScraperConfig` extend `TimestampMixin`
(`updated_at` punya `onupdate=func.now()`), dan `onupdate` NANDAIN kolom
itu EXPIRED abis UPDATE TERLEPAS dari `expire_on_commit=False` level-sesi
-- persis warning yang UDAH ada di docstring `ScraperRunRepo` (atas file
yang sama) sejak H1, "kejadian lagi" di kode yang gak baca ulang
docstring itu sendiri pas nulis `ScraperConfigRepo`. Fix: `updated_at`/
`created_at` di-set EKSPLISIT di Python di `upsert()`, gak diserahin ke
server-side value yang dibaca balik.

Live-tested lewat instance API sungguhan: enable/disable (+reason)/PATCH
config (single-field update, field lain SURVIVE, `null` eksplisit vs
gak-dikirim dibedain bener)/reset-config (balik ke default kode, `has_
override=false`)/reset-dedup, semua audit log kecatat (11 baris, urutan
bener). Auth gating dicek analyst DITOLAK di semua 5 write endpoint
(403), `GET /health` tetep 200 buat analyst. `GET /api/scraper/health`
real: 78 stale (fresh dev DB) + beberapa dead dari sisa run test sesi
sebelumnya + 1 ok -- `disabled` scraper KEBUKTI dikecualikan dari
`problems`. Data test dibersihin abis (config+audit-log baris
`bleepcomp`). `mypy`/`ruff` bersih, unit+contract 686 lolos, full suite
(termasuk integration) tetep 1243 lolos (3 kegagalan snapshot date-
sensitive pre-existing, sama kayak sebelumnya).

**Fase 9 backend KOMPLET** (9.1-9.6 semua selesai). Sisa: frontend.

### Grup H4 -- selesai (2026-09-25) -- halaman control plane `/scrapers`

**Keputusan user (2026-09-25)**: control plane scraper dapet halaman
SENDIRI (`/scrapers`, nav top-level baru), BUKAN widget kecil di
`/dashboard` kayak yang direncanakan awal (rencana lama numpang scope
legacy "Scraper Health" widget yang emang bagian tab Dashboard). Placeholder
card yang udah ada di `/dashboard` sejak Grup B (Fase 8) DICABUT, bukan
diisi -- H4 ini gabungin apa yang tadinya dipisah H4 (widget)/H5 (halaman
penuh) di rencana awal jadi SATU halaman.

**Dibangun** (`apps/web/src/components/scrapers/`): `HealthSummaryBar`
(counts per status + chip "Needs attention" yang bisa diklik buka detail
langsung, `GET /health`, `refetchInterval` 60d), `ScrapersTable` (84 baris,
search id/source + filter runtime/status client-side, status DIGABUNG
client-side dari `/health`'s `problems` + `enabled` -- partition DIJAMIN
backend, compute_health() selalu balikin TEPAT satu dari 6 status jadi gak
ada ambiguitas, dropdown aksi per baris Trigger/Dry-run/Enable-Disable),
`ScraperDetailDialog` (mount-gates-freshness, sama pola `NoteForm`/
`MindmapEditorForm` -- form config lazy-init dari data yang UDAH ada,
bukan reset-effect) berisi meta info+aksi (Trigger/Dry-run/Enable-Disable/
Reset Dedup)+form config PATCH (`ScraperRunsPanel`/`ScraperItemsPanel`
paginated, numpang `SimplePager` Grup A), `DisableScraperDialog` (reason
opsional). `StatusBadge`/`RunStatusText` -- pill warna per status, pola
sama kayak `SeverityBadge` G7.

**Status per baris DIHITUNG client-side** (bukan endpoint baru) -- scraper
yang gak muncul di `/health`'s `problems` DAN `enabled=true` dianggap
`ok`, `!enabled` `disabled`. Awalnya nyoba nebak status dari `enabled`
doang di parent (`ScrapersView`) pas problem-chip diklik -- SALAH buat
scraper `disabled` (gak pernah muncul di `problems`, defaultnya kena
tebak "ok"). Fix: `ScrapersTable`/`HealthSummaryBar` kirim status yang
UDAH bener lewat callback (`onOpenDetail(id, status)`), bukan nebak ulang
di parent.

Live-tested penuh via browser beneran (bukan cuma `tsc`/`build`) --
**ketemu 1 masalah operasional** (bukan bug kode): cookie sesi `cti_session`
basi dari testing sesi sebelumnya bikin redirect loop `/login`<->`/dashboard`
(`proxy.ts`'s guard optimistic ngeliat cookie ADA lalu redirect `/login`
duluan, padahal invalid, `/api/auth/me` 401, balik lagi) -- fix `POST
/api/auth/logout` manual buat clear cookie httpOnly-nya (`document.cookie`
JS gak bisa, httpOnly). Password dev `admin1` di-reset manual (`bcrypt`
langsung ke DB) karena credential asli gak diketahui -- **flag ke user**:
password `admin1` sekarang `DevTest123!` di DB dev, bukan yang lama.

Verifikasi: 84 scraper ke-load (78 stale/5 dead/1 ok, cocok sama H3),
search+filter jalan, klik problem-chip DAN klik baris tabel dua-duanya
buka detail yang bener. Detail dialog: meta info bener, form config
pre-fill BENER (`bitdefender` yang punya override REAL dari sesi jauh
sebelumnya nunjukin `schedule`/`rate_limit`/`max_items` asli, bukan
placeholder). **Dry-run REAL end-to-end** (bitdefender, browser -> proxy
-> API -> `Runner(dry_run=True)` -> fetch asli ke feed Bitdefender ->
"ok -- 15 item found (309ms)"). Enable/Disable/Reset-Config REAL
end-to-end di `akamai` (scraper tanpa override, dipilih spesifik biar gak
ganggu data asli) -- toast konfirmasi, `updated_by`/`updated_at` kebukti
kepopulasi bener (verifikasi ulang fix `MissingGreenlet` H3 lewat UI, bukan
cuma curl), ConfirmDialog reset-dedup/reset-config render bener. Data test
dibersihin abis (config+audit-log baris `akamai`), dikonfirmasi
`bitdefender` (data asli) gak keganggu, dry-run kebukti 0 DB write.
`tsc --noEmit`/`eslint`/`pnpm build` semua bersih (29 route).

**Fase 9 KOMPLET SELURUHNYA** (backend 9.1-9.6 + frontend `/scrapers`).

- [x] **9.1** API: list/detail/runs/items
- [x] **9.2** API: trigger + **dry-run** _(endpoint paling berguna, sekarang gak ada)_
- [x] **9.3** API: enable/disable/schedule
- [x] **9.4** API: reset dedup
- [x] **9.5** Health sweep: `dead` / `degraded` / `zero_yield` / `stale`
- [x] **9.6** Alert digest (satu pesan, bukan 198)

**Exit criteria:** scraper yang dimatiin kedeteksi `dead` dalam 3 interval · selector yang dirusak kedeteksi `parse_error` dalam 1 interval

---

## Fase 10 — Cutover `[ ]`

### Survei (2026-09-26) -- hasil + keputusan user

Estimasi plan awal ("1 minggu, seed + `docker compose up`") **gak
realistis**: beberapa hal yang dikira udah ada ternyata belum. Temuan
(semua diverifikasi langsung dari repo, bukan dari catatan):

- **Gak ada Dockerfile sama sekali** -- `docker/` kosong, gak ada
  `.dockerignore` (tanpa itu `legacy/config.yml` + `legacy/dump/` ~110MB
  ikut build context). `docker-compose.yml` cuma postgres/redis/vault.
- **Cold-start guard belum ada kodenya** -- cuma setting
  `SCRAPER__COLD_START_MAX_ITEMS=5` (`config.py:133`), gak ada yang baca.
  Runner gak punya logika "run pertama". Run pertama 84 scraper = ratusan
  s/d ribuan task `enrich.article` (~10-13 detik + 1 panggilan LLM
  masing-masing) + tiap artikel lolos ke Telegram channel asli, gak ada
  filter umur artikel.
- **Beat singleton lock (10.1d) + backpressure `enrich` (10.1e) belum
  ada** -- yang backpressure cuma setting `enrich_queue_max_depth=2000`
  + nama status `backpressure`.
- **CI cuma 4 job** (ruff/mypy/pytest/gitleaks): gak ada job web, gak ada
  docker build. `tests/fixtures/` (46MB, 103 dir) **UNTRACKED** -- golden
  test gak punya bahan di CI, gate "≥95% fixture identik" cuma bisa
  dicek lokal.
- **`torch>=2.3` masih di extra `cti-enrich[nlp]`** padahal Fase 0.9
  ngonfirmasi nol importer (`git grep` juga kosong) -- image `worker-nlp`
  bengkak multi-GB tanpa alasan.
- **Web belum siap prod**: `next.config.ts` kosong (belum
  `output: "standalone"`); cookie session `secure` di production =>
  wajib HTTPS di depan.
- **Seed**: sumbernya ada di dump Mongo (`techstack` di dump
  `threatintel`, `monitored_accounts` 18, `clients` 2, `roles` 3,
  `users` 6). `POST /api/auth/init` udah bikin superadmin pertama.
- **Dump Mongo 2026-09-16** (>10 hari) -- checklist minta <24 jam +
  udah dites restore => perlu dump final pas cutover. Backup Postgres
  stack baru belum dipikirin.
- **11 secret belum dirotasi**; `cti_core` belum bisa baca Vault.
- **17 job Rundeck aktif gak punya padanan** (100 aktif = 83 scraper +
  17): 4 GitHub watcher (`githubTTPs`/`mitreGithub`/`githubSophoslab`/
  `githubAptTTPSimulation`), `topCve`, `logbook`/`sendCounter`/
  `trendingNewsToday` (baca Mongo lama -- data basi kalau dibiarin),
  `techstackGO/NPM/PYPI`, `trendingCve`/`twitter`/`twitter30`,
  `threatactorTrendGraylog`/`threatactorTrendTelegram`, `offsetAlert`.
- Docker Desktop lokal cuma 4GB RAM -- cukup buat smoke test, mepet
  buat `worker-nlp`.
- Item checklist "`static/` dilayani container web" **basi** (web
  sekarang Next.js, `static/` cuma spesifikasi); yang relevan cuma
  "ke-commit" -- udah beres (29 file).

**Keputusan user (2026-09-26):**

1. **Cold-start = cap saja.** Run pertama tiap scraper cuma enrich N
   item terbaru (`cold_start_max_items`, default 5), sisanya ditandai
   `seen` tanpa diproses. Alert Telegram **TETAP kirim normal** --
   risiko yang DITERIMA sadar: worst case ~84 x 5 = ~420 pesan burst ke
   channel asli pas run pertama. (Opsi "mute alert" ditawarin dan
   ditolak.) **Direvisi di keputusan 5** (warm start): cap tetap dibangun,
   tapi perannya jadi jaring pengaman, bukan jalur utama cutover.
2. **17 job Rundeck = port semua** (bukan cuma yang murah). Catatan
   tafsiran yang perlu dikonfirmasi: `offsetAlert` (rusak dari dulu,
   diganti heartbeat + control plane Fase 9) dan `threatactorTrend
   Graylog`/`...Telegram` (Graylog dibuang di plan §6; yang kedua
   diblokir permanen karena token hardcoded) dianggap **di luar** "port
   semua" kecuali user bilang lain. Prasyarat dari user: narik
   `/opt/techstackLibrary` dari prod (buat `techstack*`); token Twitter
   baru (buat trio Twitter -- `TwitterScrap` udah ada di checkout).
3. **Deploy = 1 VM + nginx/ingress yang udah ada** -- compose cuma expose
   port internal, TLS dipegang proxy di luar compose (bukan Caddy).
   **DIGANTI user 2026-09-26 (10.G2): nginx sekarang service di compose** (self-signed otomatis);
   template nginx host tetap ada sebagai alternatif (`docker/ops/nginx-cti.conf.example`).
4. **Go-live pakai `.env`** (chmod 600 di host); integrasi Vault jadi
   item PASCA-cutover, gak nge-blok Fase 10.
5. **Warm start (skenario C) sekarang, migrasi riwayat (skenario D)
   bertahap pasca-cutover** (user: "ngikut lu"). Dasar keputusan -- semua
   diverifikasi dari kode/dump 2026-09-26:
   - `run_pipeline()` GAK ngecek apakah URL udah ada di `articles`: langsung
     `classify` (LLM) -> ... -> `persist` -> `route_alerts` (Telegram).
     Gerbang dedup SATU-SATUNYA = `scraper_seen` (`sha256(scraper_id + NUL +
     URL kanonik)`). Jadi migrasi `articles` doang TANPA isi `scraper_seen`
     = artikel lama diproses + di-alert ULANG (skenario B, jelek).
   - Sumber seed `scraper_seen`: `articles` di dump (7.899 URL, posted_on
     2026-01-05..2026-09-15) -- key dihitung ulang dari URL. `threatintel.
     offsets` (8.737) formatnya `title+url` mentah tanpa pemisah, GAK
     dipakai langsung; selisih ~840 kemungkinan item yang ditolak LLM
     (kalau gak diseed: diklasifikasi ulang, cuma ongkos LLM, tanpa alert).
   - Pemetaan `Article.source` -> `scraper_id`: cocok persis ke
     `meta.source` cuma ~70% (5.513/7.899); 14 label perlu tabel alias
     manual (terbesar "Cybersecurity News" 1.845, "Socradar" 147, "Cisa" 127,
     "Cyfirma" 92). Tidak ada `source` yang dipakai >1 scraper.
   - "Cold" didefinisikan = scraper gak punya SATU PUN baris `scraper_seen`
     (bukan "belum pernah ada `ScraperRun`"), biar scraper yang udah
     di-warm-start gak kena cap dan kehilangan item baru sejak dump.
     `reset-dedup` otomatis bikin scraper "cold" lagi -> cap jalan sbg
     jaring pengaman (masuk akal: reset tanpa cap = re-ingest seluruh feed).
   - Urutan cutover: stop Rundeck -> `mongodump` final -> seed `scraper_seen`
     -> nyalain stack baru (dump basi = alert item di antaranya kekirim
     ulang).
   - Skenario D (migrasi penuh) ditunda: ~40rb dokumen (bukan volume yang
     jadi masalah, tapi mapping skema): `articles`+tabel anak, `iocs`,
     `cve_tracker`, `cve_tickets`, `tweets`, `ransomware_victims`,
     `audit_log`, `daily_recaps`, `clusters`, `newsletters`. `logbook_
     entries` (4.657) dan `cve_mentions` (4.058) BELUM punya tabel
     padanan -- perlu keputusan sebelum D. `attack_*` (~27rb dok) GAK
     perlu dimigrasi (re-sync otomatis lewat beat `attack.sync_check`);
     `scraper_runs`/`nlp_jobs`/`offsets`/`openai_cache` semantik lama, skip.
     Import riwayat aman dijalankan kapan pun karena `articles.url_hash`
     unique (idempoten) -- data lama diimpor TANPA lewat pipeline
     (kalau lewat = LLM + Telegram dobel).
6. **Staging tersedia** (server shared user, SSH key udah ada; detail akses
   sengaja gak ditulis di repo). Direcon baca-doang 2026-09-26: 8 CPU, 23GB
   RAM, 35GB disk bebas (75% kepake), Docker 29 + Compose v5, outbound OK,
   gateway LLM lokal (9router) kejangkau dari host. Catatan: box SHARED sama
   stack lain -> deploy CTI di compose project/direktori terpisah, publish
   port ke `127.0.0.1` + SSH tunnel (cookie `secure` Next.js cuma diterima
   di HTTPS atau `localhost`), `.env` + bot Telegram TES sendiri (JANGAN
   channel asli). Ada container `cti-mongo` (restore dump legacy) yang
   ke-publish di `0.0.0.0:27017` -- belum dicek pakai auth atau nggak.

**Rencana blok kerja (urutan):**

- [x] **10.A2** Ketahanan `enrich.article` (2026-09-26) -- KELAR, live-verified
      di staging. Prinsip: artikel yang sudah lolos dedup (`scraper_seen`
      di-commit pas `send_task`) TIDAK BOLEH hilang tanpa jejak.
      - **Retry per kategori** (`apps/worker/.../tasks/enrich.py`): TRANSIEN
        (LLM mati/timeout/5xx/429-bukan-kuota, koneksi DB putus, jaringan) 6x,
        backoff 30s->10 mnt +jitter (~30 mnt total); JSON rusak 2x; sisanya
        (401, kuota abis, bug) langsung gagal. **Live**: LLM dimatiin (URL tak
        terjangkau) -> 10 retry tercatat, 0 task gagal, semua terselesaikan
        pas LLM pulih.
      - **Gagal permanen -> `rejected_articles`** (`on_failure`, sekali di
        kegagalan FINAL): `reason="[enrichment_failed] <Tipe>: <pesan>"`
        (tipe asli dari `einfo.type` -- Celery nurunin exception openai ke
        kelas dasarnya), muncul di Filtered Articles + bisa di-restore.
        Best-effort (gagal nyatet gak nutupi kegagalan aslinya); secret
        yang dikonfigurasi di-SCRUB dari pesan. **Live**: key salah (401) ->
        5/5 tercatat, 0 retry. Berhasil di-replay -> baris `rejected` basi
        DIHAPUS di `persist()` (gak dobel artikel + "ditolak").
      - **`persist` di-commit SEBELUM `route_alerts`** -- keduanya satu
        transaksi dan `sync_session()` rollback saat exception: alert
        Telegram gagal dulu ikut MEMBATALKAN artikel yang sudah ke-persist.
      - **PERSONA "KIRO" DIREPRODUKSI & DISELESAIKAN**: `my-combo` ->
        `claude-haiku-4.5` lewat backend Kiro njawab "I'm Kiro, a development
        environment assistant, not a threat intelligence analyst" / "I'm
        ready to classify, please provide a title" (BUKAN JSON). Bergantung
        isi judul + gak deterministik; probe 4-input generik tadi GAK
        nangkep (100/100). `temperature=0` bikin retry identik ngulang
        jawaban sama. Diukur (6 percobaan, 2 judul gagal): polos 0/6 & 1/6;
        + pengingat terpisah 1/6 & 6/6; **system + `<article_title>` +
        pengingat di pesan user yg sama 6/6 & 6/6** (juga satu-pesan-user
        6/6). Fix: `cti_enrich/stages/llm_messages.py::build_messages` --
        percobaan PERTAMA tetap verbatim (prompt bisnis + perilaku Fase 5
        gak berubah), percobaan ULANG pakai bentuk dikuatkan (`classify` +
        `extract_ttps`). Probe di gateway staging: polos `classify_kiro_1`
        0/8, `_2` 7/8; `--hardened` 48/48. Replay 7 artikel `[enrichment_
        failed]` -> 7/7 pulih <1 menit (3 artikel, 4 ditolak LLM normal).
        CATATAN: bentuk dikuatkan belum dievaluasi AKURASI-nya vs bentuk
        polos di korpus besar -> jangan dijadikan percobaan pertama dulu.
      - `tools/llm/probe_json.py` +2 judul Kiro bawaan, `--hardened`,
        `--titles-file` (replay judul asli). 4 -> 6 input.
      - **Suite penuh: 1346 lulus, 3 gagal** (3 gagal = snapshot sensitif
        tanggal yang sama kayak sebelumnya). Test baru 10.A2: kegagalan task
        (13), retry JSON dikuatkan (5), probe (+3), ketahanan pipeline (+1).
        Semua mutasi (commit-sebelum-alert, `on_failure`, retry transien)
        terdeteksi. `mypy` bersih; `ruff` cuma sisa E501 `ta.py:50` (10.D).
        Belum di-commit (commit di akhir Fase 10).
      - Sisa yang diterima: retry ETA di Redis yang ditahan worker
        yang di-SIGKILL nyangkut sampai `visibility_timeout` (1 jam) --
        shutdown normal (SIGTERM/`docker stop`) mengembalikannya seketika.
- [x] **10.A** Hardening kode (2026-09-26) -- KELAR, live-verified.
      - **Cold-start guard** (`Runner._cold_start_cap`/`_cold_start_skipped`,
        `ScraperSeenRepo.has_any`): "cold" = nol baris `scraper_seen` (BUKAN
        "belum pernah ada `ScraperRun`", biar scraper warm-start gak kena cap).
        Run cold nge-buffer item, enrich N `ArticleItem` TERBARU (`posted_on`
        desc; sort stabil -> feed tanpa tanggal tetap urutan feed), sisanya
        di-mark seen tanpa diproses (`ScraperItem.reason="cold_start_cap"`).
        Cuma `ArticleItem` yang kena (jalur ke `enrich` + Telegram); sink lain
        (ransomware/CVE/IOC/tweet) nulis langsung ke DB, gak kena.
        `Runner(cold_start_max_items=...)` bisa di-override, `<= 0` = mati.
        **Live** (bleepcomp asli, dev DB): 10 item -> 5 enrich + 5 cap-skipped,
        `LLEN enrich`=5; `reset-dedup` bikin scraper cold lagi.
      - **Beat singleton (=10.1d)** `cti_worker.beat_lock.BeatLock` (`SET NX PX`
        + Lua renew/release, token per-proses) + `cti_worker.beat_main`:
        standby GAK ngejalanin Celery beat sama sekali (jadi ambil alih tanpa
        catch-up buat slot yang lewat), leader renew tiap `ttl/3`, renew
        ditolak / Redis putus > TTL = `os._exit(1)` (fail-stop, restart policy
        Compose yang bawa balik ke standby). **Compose pakai `python -m
        cti_worker.beat_main`, GANTI `celery beat`.** `WORKER__BEAT_LOCK_TTL_S`
        (default 30). **Live** (2 proses asli + Redis sementara): tetap 1
        leader lewat > 1 TTL, SIGTERM -> takeover 2.1s, SIGKILL -> takeover
        6.1s (= TTL).
      - **Backpressure (=10.1e)** `sinks.ensure_enrich_capacity()`: `LLEN
        enrich` >= `enrich_queue_max_depth` -> `BackpressureError` -> Runner
        berhenti, `status="backpressure"` (kelihatan di control plane +
        health), lease dilepas (item BUKAN ditandai seen, dicoba lagi run
        berikutnya). Asumsi "queue Celery = LIST Redis bernama `enrich`"
        dibuktikan lawan producer Celery + Redis asli (test + live). **Live**:
        batas 3 -> 3 terkirim, item ke-4 backpressure, `LLEN`=3. Ambang 2000
        masih tebakan awal -- setel ulang pas ada angka nyata `worker-nlp`.
      - **`torch` dibuang** dari extra `nlp` (`uv.lock` -331 baris: torch, 12
        paket nvidia-*, triton, sympy, ...; ~2-3GB di image Linux). spaCy
        `en_core_web_sm` + sumy diverifikasi tetap jalan.
      - **Temuan sampingan yang ikut dibenerin:** (1) Runner/`DedupStore`/
        `ScraperSeenRepo` **GAK PUNYA test otomatis sama sekali** sebelumnya
        -> `tests/integration/test_runner.py` (18 test), `test_beat_lock.py`
        (8), `test_enrich_queue_depth.py` (2, Redis asli via testcontainers);
        (2) `ScrapeContext.now` pakai `datetime.utcnow()` (deprecated, jadi
        ERROR di test lewat `filterwarnings`) -> `_utcnow_naive()`, nilai SAMA
        persis (naive UTC, `unit42_github` bergantung ke itu); (3)
        `dedup.commit()` cuma flush -- state "done" numpang commit
        `_log_item()`; kalau log itu gagal item balik `in_flight` dan
        di-dispatch ULANG begitu lease basi (enrich + alert dobel) -> commit
        eksplisit + test regresi (mutation-check: gagal tanpa fix).
      - Batas yang diterima: backpressure di tengah run COLD bikin sisa item
        yang belum diproses jalan TANPA cap di run berikutnya (bounded
        `max_items`, cuma kejadian pas antrian penuh).
      - **Suite penuh: 1271 lulus, 3 gagal** (1243 lama + 28 baru). Tiga
        gagal = snapshot sensitif tanggal yang UDAH gagal sebelum Fase 10
        (`test_recent_campaigns`, `test_get_pirs`, `test_pir_export`), bukan
        dari perubahan ini. `mypy` (cti-core + cti-scraper) bersih; file yang
        disentuh lolos `ruff check` + `ruff format`. Belum di-commit (commit
        di akhir Fase 10, sesuai preferensi).
- [x] **10.B** Containerization (2026-09-26) -- KELAR, smoke test penuh LULUS
      di staging (project `cti-stg`, secret dummy).
      - **File**: `.dockerignore` (ngeblok `.env*`, `legacy/`, `tools/salvage/`,
        `tests/fixtures/`, `.git`), `docker/{api,worker,web}.Dockerfile`
        (worker = SATU file, dua target `worker`/`worker-nlp`),
        `docker/stack.env.example`, `docker-compose.yml` (profile `app`),
        `apps/web/next.config.ts` -> `output: "standalone"`,
        `apps/web/public/.gitkeep` (dir kosong gak ke-track git -> `COPY` gagal
        di clone bersih).
      - **Compose**: default tetap cuma `postgres`+`redis` (alur dev gak
        berubah); stack penuh = `docker compose --profile app up -d --build`
        -> `migrate` (one-shot `alembic upgrade head`, gagal = stack gak
        naik) -> `api` / `worker` (rss+api+notify+maintenance) /
        `worker-browser` (`scrape.browser`, `shm_size: 1gb`) / `worker-nlp`
        (`enrich`) / `beat` (`python -m cti_worker.beat_main`) -> `web`.
        Semua port di-publish ke `${BIND_ADDR:-127.0.0.1}` (nginx yang
        terminasi TLS). `web` SENGAJA tanpa `env_file` (gak boleh megang
        secret DB/LLM/Telegram). Variabel level compose (`BIND_ADDR`, port,
        concurrency, `POSTGRES_PASSWORD`, `CTI_TAG`) di `docker/stack.env`,
        BUKAN `.env` (pydantic-settings `extra="forbid"` bakal nolak).
        `CTI_ENV_FILE` buat ganti file env (smoke test pakai secret dummy).
      - **Image (terukur)**: web 321MB, api 1.87GB, worker 1.89GB,
        worker-nlp 2.12GB; semua non-root (uid 10001 / `node`), tanpa torch.
        Chromium (~600MB) di stage `browser-base` TERPISAH dari venv, layer
        dishare api<->worker lewat cache (rebuild source = detik, bukan menit);
        `playwright==` di-pin lewat ARG + smoke launch pas build +
        `tests/unit/test_docker_build_context.py` (pin == uv.lock, stage
        identik, `.dockerignore` ngeblok secret). `worker-nlp`: spaCy +
        sumy + data NLTK `punkt_tab` di-bake, terbukti jalan `--network none`.
      - **BUG NYATA ketemu pas build/smoke (semua gak kelihatan di dev karena
        env dev install semuanya)**:
        1. `discover()` gagal di image tanpa extra `nlp`: scraper `monitor_x`
           -> `cti_enrich.stages.score` -> `import spacy` di level modul ->
           API/worker/beat GAGAL START. Fix: `score._get_nlp()` lazy
           (`lru_cache`); test kontrak `tests/contract/test_registry_without_
           nlp.py` (subprocess, `sys.modules[spacy]=None`; mutation-check gagal
           tanpa fix).
        2. **Image API gak punya paket `cti-scrapers`** -> `discover()` balik
           `{}` DIAM-DIAM -> `GET /api/scraper` = 0 scraper, halaman
           `/scrapers` kosong total di prod. Fix: `cti-scrapers` masuk deps
           `cti-api`; beat sekarang RAISE kalau registry kosong (`beat.py`,
           `tests/unit/test_beat_schedule.py`, 3 test -- sebelumnya
           `build_beat_schedule` gak punya test); Dockerfile nge-assert
           `len(discover()) > 50` pas build.
        3. **Web = BFF, API cuma lihat IP container `web`** -> rate limit
           login (`login:{ip}`, 10/menit) GLOBAL + audit log IP gak berguna.
           Fix: `apps/web/src/lib/auth/client-ip.ts` (login + proxy route
           nerusin SATU IP hop ke-N dari kanan `X-Forwarded-For`,
           `TRUSTED_PROXY_HOPS`=1, divalidasi) + uvicorn `--proxy-headers`.
           **Terbukti live**: rantai `6.6.6.6, 203.0.113.9, 198.51.100.7` ->
           key Redis `ratelimit:login:198.51.100.7` (entri palsu di kiri
           diabaikan); tanpa XFF Next.js ngisi IP socket sendiri; XFF sampah
           diabaikan (bukan 500). **nginx WAJIB set
           `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`** --
           kalau enggak API lihat IP nginx buat semua orang (10.G runbook).
        4. **Race bootstrap API di DB kosong**: `lifespan` (client `default` +
           role sistem, pola "cek dulu baru insert") jalan di TIAP proses
           uvicorn, `WEB_CONCURRENCY=2` -> dua proses tabrakan di `pk_clients`
           -> "Child process failed to start" -> container mati, cuma
           self-heal lewat restart policy (start pertama SELALU flap).
           Fix: `bootstrap_reference_rows()` di `cti_api/main.py` pakai
           `pg_advisory_xact_lock`; `tests/integration/test_api_bootstrap_
           race.py` maksa race-nya deterministik (mutation-check: gagal dgn
           `UniqueViolation pk_clients` persis kayak di staging tanpa lock).
           **Live**: boot bersih dari DB kosong -> 0 traceback, restart count 0.
      - **Smoke di STAGING (2026-09-26, project `cti-stg`, dir
        `~/cti-platform-stg`, secret acak di-generate DI server)**:
        - Build 4 image di server: api ~1 mnt, worker ~20s, worker-nlp ~30s,
          web ~40s (cache Chromium dishare). Ukuran: web 302MB, api 1.85GB,
          worker 1.85GB, worker-nlp 2.1GB. Build cache ~7GB di server
          (`docker builder prune` kalau butuh ruang).
        - `migrate` naikin skema dari DB kosong (20 migrasi, exit 0); 9
          service healthy; RAM idle total ~1.3GB (api 534MB, nlp 327MB,
          worker 249MB, browser 156MB, beat 105MB, web 48MB).
        - Login lewat web (cookie `Secure; HttpOnly; SameSite=lax`), `init`
          admin lewat proxy; **registry API = 84 scraper** (sebelum fix = 0);
          IP klien: rantai `6.6.6.6, 203.0.113.9, 198.51.100.7` -> key
          `ratelimit:login:198.51.100.7`.
        - **Chromium di image API** (dry-run `any_run_trends` = 10 item, 3s)
          dan **di image worker** (trigger Celery ke `worker-browser`:
          `ok`, 10 item). `worker` (rss) jalan: `bleepcomp` 11 item -> 5
          diproses + 6 `cold_start_cap` (cap live di container).
        - `worker-nlp` menerima task `enrich.article` dari antrian dan
          nyampe langkah LLM (gagal 401 = API key dummy, sesuai rencana;
          e2e enrichment butuh endpoint LLM staging asli -> 10.G).
        - **2 container `beat`**: 1 leader + 1 standby; SIGTERM leader ->
          takeover 4,1s; SIGKILL -> 17,5s (TTL 15s + interval cek).
        - `abnormalsecurity` -> `parse_error` di DUA jalur (dry-run API +
          worker-browser) = situs/selector, BUKAN container; cek di 10.D/hypercare.
      - **TEMUAN (belum dikerjain, butuh keputusan): kegagalan `enrich.article`
        = artikel HILANG.** Retry cuma buat `JSONDecodeError`
        (`tasks/enrich.py`); error lain (LLM mati/timeout/5xx/401, jaringan pas
        `fetch_text`) -> task gagal permanen, padahal dedup UDAH commit pas
        `send_task` -> gak akan dicoba lagi, jejaknya cuma di log. Pas LLM
        gateway gangguan (riwayat: persona "Kiro", ~6,5% JSON rusak) semua
        artikel di jendela itu lenyap tanpa suara. Usulan: (a) retry error
        transien (koneksi/timeout/5xx/429-bukan-kuota) dgn backoff panjang,
        (b) `on_failure` nulis ke `rejected_articles` (`reason=enrichment_
        failed: ...`) biar muncul di UI Filtered Articles + bisa di-restore.
      - **Suite penuh: 1279 lulus, 3 gagal** (1271 + 8 test baru 10.B: registry
        tanpa nlp, guard Docker/`.dockerignore` x3, jadwal beat x3, race
        bootstrap API). 3 gagal = snapshot sensitif tanggal yang sama kayak
        sebelumnya. `mypy` bersih; `ruff` cuma sisa E501 `ta.py:50` (10.D).
        Belum di-commit (commit di akhir Fase 10).
      - **Daftar secret staging/prod (2026-09-26)** -- WAJIB: `LLM__URL`/
        `LLM__MODEL`/`LLM__API_KEY` (9router; tanpa itu `enrich.article` 401 +
        fitur LLM API mati) dan `TELEGRAM__BOT_TOKEN`/`CHAT_ID`/`THREAD_IDS`
        (`send_alert` RAISE kalau kosong, jadi tiap artikel lolos = task gagal
        SETELAH tersimpan). OPSIONAL per scraper (cuma 6 dari 84):
        `NVD__API_KEY` (`new_cve`, sumber CVE tracker; 5 -> 50 req/30s),
        `GITHUB__TOKEN` (`blackorbird`, `deepdark_cti`, `github_poc_monitor`,
        `unit42_github`; PAT tanpa scope cukup), `TWITTER__API_KEY`
        (`monitor_x`). JANGAN diisi di staging: `GRAPH__*` (bikin draft/email
        BENERAN di mailbox). Gak dipakai kode: `OTX__API_KEY`.
      - **Bug ikut ketemu (nyusun daftar itu)**: `Runner._run_body` manggil
        `resolve_credential_headers` SEBELUM blok `try` -> secret kosong =
        `ConfigError` nembus `execute()`, run nyangkut `running` tanpa
        `finish`, task Celery crash tiap jadwal. Sekarang jadi run
        `fetch_error` dgn `errors[0].stage="config"` (kelihatan di control
        plane), test `test_missing_credential_is_a_clean_failed_run_not_a_
        stuck_one` (test integrasi baca `.env` dev lewat `get_settings()` --
        test dikunci dgn env kosong biar deterministik). **Image staging
        sekarang BELUM punya fix ini -- rebuild dulu sebelum 10.G.**
      - **E2E staging dgn key ASLI (2026-09-26, user isi `stg.env`)**:
        - `tools/ops/check_secrets.py` (BARU, 8 test, read-only, TIDAK nyetak
          secret -- termasuk lewat pesan error httpx yg memuat URL Telegram):
          LLM `GET /models`, Telegram `getMe`+`getChat` (tanpa kirim pesan),
          NVD, GitHub `/rate_limit`, twitterapi.io; Graph cuma dilaporin
          terisi/kosong. Hasil staging: SEMUA OK (LLM 48 model, `my-combo`
          ada; bot `@privhemdall_bot` di chat "Bot Status" (forum); GitHub
          5000/jam). Pakai lagi buat verifikasi setelah rotasi secret (10.F).
        - **Dua instance 9router BERBEDA**: dev `172.25.0.77` (26 model) vs
          server staging `172.25.1.77` (48 model). Hasil probe `my-combo` ->
          `claude-haiku-4.5` itu buat instance DEV; isi combo di staging bisa
          beda -> probe ulang ke `172.25.1.77` (`--url`).
        - Trigger manual 3 scraper (`beat` sengaja MATI biar gak banjir
          Telegram/LLM): 9 artikel ke-enrich end-to-end (8 `global`, 1
          `apac`), Telegram jalan tanpa error, `unit42_github` (credential
          GitHub) jalan.
        - **4 MASALAH NYATA ketemu, semua sudah diperbaiki + mutation-check**:
          1. **TTP kembar hapus artikel** -- LLM ngembaliin `T1176` 2x dgn
             nama beda; `set_enrichment` dedup per tuple `(id, nama)` padahal
             kunci `uq_article_ttp` = `(article_id, ttp_id)` -> UniqueViolation
             -> seluruh transaksi rollback, artikel HILANG. Fix `_dedup_ttps()`
             per `ttp_id` (sync + async, dua tempat).
          2. **Koneksi DB dipakai bareng antar proses hasil fork** -- engine
             dibuat di induk Celery (`build_beat_schedule()` baca DB pas
             import), anak prefork mewarisi socket yang sama ->
             `OperationalError: server closed the connection` +
             `PendingRollbackError`. Fix `discard_inherited_connections()`
             (`dispose(close=False)`) di sinyal `worker_process_init`; test
             fork 3 anak (gagal 3/3 tanpa fix).
          3. **Run nyangkut `running`** -- `_run_body` bisa selesai dgn sesi
             DB rusak lalu `finish()` raise. Fix: rollback sebelum finish.
          4. **Halaman blokir WAF dianggap isi artikel** -- Arctic Wolf
             (Wordfence 403): Playwright `goto` gak raise di 403 dan
             `page.content()` = halaman blokir; boilerplate 158 karakter jadi
             "ringkasan" -> LLM njawab prosa ("saya gak lihat ringkasan
             artikelnya", BUKAN persona Kiro) -> JSON gagal -> artikel hilang.
             Fix: `fetch_text` cek status >= 400 + `looks_blocked()` (teks
             pendek + frasa khas WAF) -> title-only; DAN `extract_ttps` gagal
             JSON = artikel TETAP disimpan tanpa TTP (`_extract_ttps_or_empty`,
             log `ttp_extraction_failed_article_kept`) -- TTP itu pengayaan
             opsional, klasifikasi bukan (classify gagal tetap raise ->
             retry Celery). Pipeline sebelumnya GAK punya test otomatis.
        - **Hasil setelah semua fix (sampel 50 artikel, 3 batch, concurrency
          2 + 1)**: dikirim ke enrich 50 = tersimpan 35 + ditolak LLM 15,
          **HILANG 0** (sebelum fix: 3 dari 30 = 10%). Log: 0 `raised
          unexpected`, 0 `OperationalError`, 0 `PendingRollback`.
        - **Census feed RSS dari egress staging** (49 feed ringan): 41 OK
          (84%). Gagal 8: 3 MATI (404: `google`, `nquiring_minds`, `sysdig` --
          URL feed pindah), 4 DIBLOKIR WAF (`cisa` 403, `exploitdb` 403
          Sucuri, `threatmon` 403 Cloudflare, `cybersecnews` 202+HTML), 1
          gak terjangkau (`ecrime` ConnectTimeout). Plus run nyata: `cisa`/
          `cybersecnews`/`doyensec`/`abnormalsecurity` `parse_error`,
          `crowdstrike` `empty`. **Hipotesis UA bot ditolak** (UA browser
          nyelamatin 0 feed, malah 3 lebih jelek) -> JANGAN ganti UA.
          CATATAN: WAF berbasis reputasi IP -- hasil dari egress staging
          belum tentu sama dgn egress prod -> ulang census dari IP prod
          sebelum cutover; gate 10.D "tiap scraper live punya golden test
          hijau ATAU waiver" perlu data ini (feed mati = perbaiki URL,
          diblokir = waiver/proxy). Cuma 49 feed ringan diuji; browser + API
          scraper belum.
        - Pelajaran: bug #1, #2, #4 SELALU lolos di dev (satu proses, satu
          LLM yang "sopan") -- cuma ketahuan lewat e2e dgn LLM asli +
          concurrency > 1. Makanya 10.G rehearsal wajib pakai sampel besar.
      - **Suite penuh (setelah e2e staging + semua fix): 1324 lulus, 3
        gagal** (3 gagal = snapshot sensitif tanggal yang sama kayak
        sebelumnya). Test baru sejak 1279: probe LLM (17), `check_secrets`
        (8), fetch_text/blokir WAF (10), ketahanan pipeline (4), fork-safety
        DB (2), dedup TTP (2), run-finish (1), credential kosong (1).
        `mypy` bersih; `ruff` cuma sisa E501 `ta.py:50` (10.D). Belum
        di-commit (commit di akhir Fase 10).
      - **Catatan operasional**: nginx WAJIB `proxy_set_header X-Forwarded-For
        $proxy_add_x_forwarded_for;`. Build image di laptop ~10GB (bikin disk
        Mac penuh sampai Docker VM read-only) -- build berikutnya di staging.
        Stack `cti-stg` sekarang DIMATIKAN (`docker compose stop`; image +
        volume tetap): `cd ~/cti-platform-stg && docker compose -p cti-stg
        --env-file stg.stack.env --profile app up -d`.
- [x] **10.C** Seed & bootstrap + warm start (2026-09-26). Dua script,
      keduanya idempoten, `--dry-run`, `--dump-dir` (default `legacy/dump`;
      di hari cutover arahkan ke mongodump TERAKHIR), dan jalan tanpa
      `pymongo` di test (dump palsu `MemoryDump`); bacaan BSON asli lewat
      `uv run --with pymongo`. Pembaca dump di `tools/seed/_dump.py`.
      - **`tools/seed/fase10_reference_data.py`** (data referensi kurasi
        manusia). Hasil di dump arsip 2026-09-16: `clients` 2 (+3 baris
        `client_countries`: nama negara -> ISO alpha-2 lewat
        `cti_enrich.countries`, nama gak dikenal = ABORT bukan tebak),
        `techstack_entries` 33 (dokumen lama tanpa `client_id` -> `default`),
        `monitored_accounts` 18, `ta_profiles` 2, `ta_watchlist` 2,
        `ta_whitelist` 2, `source_reliability_entries` 2, `pir_requirements`
        3, `pir_notes` 3, `roles` 3 (sudah ada -- dibikin API pas start).
        Identitas per tabel = kunci alami (mis. PIR = `title`+`created_at`
        ASLI, karena dump punya DUA PIR berjudul sama; catatan PIR dipetakan
        lewat ObjectId lama -> id baru). Baris yang sudah ada DILEWATI, bukan
        di-update (perubahan di UI baru gak ketimpa seed ulang). `created_at`
        asli dipertahankan.
        **Cek drift izin role**: izin peran sistem di KODE (`SYSTEM_ROLES`)
        dibandingkan dengan produksi lama -- hasilnya SAMA (nol drift), jadi
        user lama gak diam-diam dapat hak akses beda.
        **User TIDAK dimigrasi** (keputusan): script cuma ngeprint daftar 6
        user lama (username/role/client) sbg daftar kerja buat dibikin ulang
        lewat UI; hash bcrypt gak dibawa. `users.bson` sengaja TIDAK diupload
        ke staging (isinya hash) -- script tahan kalau file itu gak ada.
      - **`tools/seed/fase10_warm_start.py`** (skenario C). Isi `scraper_seen`
        (`state=done`, TTL = `dedup_ttl_days` scraper) dari riwayat lama.
        TEMUAN yang mengubah rancangan: `offsets.script` dipetakan PERSIS ke
        `ScraperMeta.legacy_script` (field ini emang dibikin buat ini) dan
        `nlp_jobs.script_name` ke `legacy_label` -- jadi gak perlu tabel alias
        tebak-tebakan; `ALIASES` cuma buat 11 label `articles.source` yang
        beda tulisan (mis. "Cybersecurity News" = 1845 artikel). Sumber yang
        digabung per scraper: `offsets` (key lama = `str(title)+str(url)`
        TANPA pemisah -> URL dicari dari pasangan (title,url) di `nlp_jobs`/
        `articles`, lalu judul-prefix terpanjang, lalu ekor `https://`),
        `nlp_jobs` (termasuk artikel yang ditolak klasifikasi -- gak ada di
        `articles`), `articles`, `ransomware_victims.offset_key` (format SAMA
        dgn `RansomwareVictimItem.dedup_key`) dan `tweets.tweet_id`.
        Tipe item non-artikel (CVE/tweet/dst) dikenali dari anotasi return
        `fetch()` -- kunci mereka gak boleh ditebak dari URL.
        Hasil dump arsip: **17.410 kunci di 71 scraper, NOL key offsets yang
        gagal dipetakan** (termasuk 131 key berbentuk CISA "judul+tanggal" dan
        Splunk "judul+path relatif"). Data 4 script lama yang memang gak
        diport (detectionEngineering, sekoia, paloaltonet, validin) dilaporkan
        "diabaikan". **13 scraper tetap dingin** (kena cap di run pertama):
        abnormalsecurity, blackberry, crowdstrike, dragos, huntio, mandiant,
        prodraft, sans, sysdig (gak punya riwayat di dump -- rusak/mati/baru),
        deepdark_cti, github_poc_monitor (kunci non-URL, tanpa sumber),
        + `new_cve`, `any_run_trends` (dedup DIMATIKAN, upsert idempoten --
        gak butuh warm start).
      - **Bukti di staging** (dump subset tanpa `users.bson`; script jalan di
        container worker, `pymongo` dipasang ke `/tmp`): seed referensi 2x
        (kedua: 0 baru, semua "sudah ada"); warm start 2x (kedua: 0 baru;
        baris yang bentrok dgn sisa e2e lama di-skip `ON CONFLICT`).
        Lalu `securelist` DIJALANKAN BENERAN: feed 10 item -> **6 duplikat
        (dari seed), 4 baru diproses, NOL `cold_start_cap`**; `scraper_seen`
        47 -> 51. (`dry-run` CLI TIDAK bisa jadi bukti: `Runner(dry_run=True)`
        mematikan dedup total, `items_new` selalu 0.) Tanpa warm start feed
        yang sama kena cap 5 dari 10.
      - **Test** (mutation-checked: hash beda dari runner, tanpa resolusi
        judul-prefix, `write_plan` gak nulis, catatan PIR nempel PIR salah,
        drift gak dilaporkan, techstack gak idempoten -- semua digagalkan test):
        `tests/integration/test_seed_reference_data.py` (12),
        `tests/integration/test_warm_start.py` (17, termasuk 3 test lewat
        `Runner` beneran: scraper hangat lolosin CUMA item baru dan gak kena
        cap, kunci seed == kunci yang di-reserve runner, kontrol negatif tanpa
        seed tetap kena cap; + test dump ASLI -- pagar buat dump cutover: key
        yang gak bisa dipetakan atau sumber tak dikenal = test merah),
        `tests/unit/test_seed_dump.py` (2), `tests/contract/
        test_scraper_labels.py` (3).
      - **BUG DITEMUKAN & DIPERBAIKI di jalur ini**: `blackberry` punya
        `source="Name"` -- skrip lama `blackberryThreat.py` nge-push label
        templat "NEW ARTICLE FROM NAME" yang gak pernah diganti, codemod
        memindahkannya apa adanya -> artikel BlackBerry tampil bersumber
        "Name". Sekarang `BlackBerry`; `legacy_label` sengaja dibiarkan
        (kompat mundur). Test kontrak baru: gak ada `source` placeholder,
        `source` unik, `legacy_script`/`legacy_label` unik.
      - **Parity `threat_feeds`/`threatintel.domain|ip|hash`** (pertanyaan
        terbuka survei): `threat_feeds` (C2) kosong di prod lama juga ->
        `check_c2_hit` selalu False, bukan regresi. `threatintel.domain/ip/
        hash` (76rb/9rb/431): TIDAK ada konsumen di kode lama (helper generik
        `dbMongo.list_existing` cuma dipanggil buat `groups`/`apac-*`/
        `global-country`, yang sudah di-seed Fase 5) -> arsip saja, tidak
        dimigrasi.
      - **Suite penuh: 1380 lulus, 3 gagal** (sebelumnya 1346; +34 = 12 seed
        referensi + 17 warm start + 2 pembaca dump + 3 kontrak label). 3 gagal =
        snapshot sensitif tanggal yang SAMA seperti sebelumnya
        (`test_recent_campaigns`, `test_get_pirs`, `test_pir_export`).
        `ruff`/`mypy` bersih di file baru. Belum di-commit (akhir Fase 10).
      - **Urutan hari cutover**: stop Rundeck -> mongodump TERAKHIR -> API
        start (bikin `default` + role sistem) -> `fase10_reference_data.py
        --dump-dir <dump baru>` -> user dibikin ulang lewat UI ->
        `fase10_warm_start.py --dump-dir <dump baru>` -> BARU nyalakan beat.
        Kalau beat sempat jalan duluan, scraper sudah lewat fase dingin dan
        item yang ke-cap gak terselamatkan. Selalu `--dry-run` dulu dan baca
        bagian "key yang gak ketemu"/"tanpa scraper" -- itu yang berubah kalau
        dump terakhir bawa bentuk baru.
- [x] **10.D** CI & gate (2026-09-26). Cara kerjanya: BUKAN nulis workflow lalu
      berharap -- tiap job dijalanin lokal, dan job `test` disimulasikan di
      **checkout bersih** (`git ls-files -co --exclude-standard` -> folder baru,
      `uv sync --extra dev --locked`, TANPA `.env`, TANPA extra `nlp`, TANPA
      `tests/fixtures`) = kondisi runner GitHub. Simulasi itu nemu 6 masalah yang
      GAK kelihatan di laptop (lihat "CI-only" di bawah); putaran terakhir:
      **1385 lulus, 7 skip, exit 0** (lokal penuh dgn `.env`/fixtures/pymongo:
      lihat baris "Suite penuh"). Belum pernah jalan di GitHub beneran -- `origin`
      ada, tapi push = keputusan user; yang bisa dibuktikan lokal sudah dibuktikan.
      - **Suite penuh (lokal: `.env` + fixtures + pymongo): 1392 lulus, 0 gagal**
        (sebelumnya 1380 lulus + 3 gagal). Simulasi CI bersih: 1385 lulus, 7 skip
        (5 golden yang saat itu di-skip krn fixtures di-.gitignore + 2 dump-asli tanpa
        `legacy/dump`), exit 0; sekarang golden jalan penuh (fixtures ikut repo).
        Belum di-commit (akhir Fase 10).
      - **Lint**: `ruff format .` (79 file: 60 `cti_scrapers` hasil codemod, sisanya
        core/api/tools/tests) + E501 `ta.py:50` + E501 `run_migration.py` (muncul
        SESUDAH format). `ruff check`/`ruff format --check`/`mypy` hijau.
        **Format = commit TERPISAH saat Fase 10 di-commit**: bikin dari
        `git worktree` di HEAD (`ruff format .` -> commit), lalu di working dir
        `git reset --mixed <commit-format>` + commit sisanya -- diff kerjaan asli
        gak tercampur 79 file mekanis. (Format sudah diterapkan di working tree.)
      - **CI-only** (semua diperbaiki + dikunci):
        1. `test_api_bootstrap_race.py` import `cti_api.main` di level modul ->
           `create_app()` butuh env DB -> error COLLECTION, seluruh sesi pytest
           mati (exit 2, nol test jalan). Sekarang import lazy.
        2. `stages/summarize.py` import `nltk`/`sumy` di level modul -> pipeline
           gak bisa di-import tanpa extra `nlp`. Sekarang lazy DAN dipanggil di
           luar `try/except` (dependency hilang = gagal KERAS, bukan diam-diam
           "ringkasan = teks asli"). Test: `test_registry_without_nlp.py` +2
           (import pipeline tanpa NLP; summarize meledak kalau nltk hilang) --
           mutation-checked keduanya.
        3. `test_enrich_pipeline_resilience` lupa nge-stub `extract_ttps` ->
           test itu MANGGIL LLM BENERAN di laptop (lewat `.env`), OpenAIError di CI.
           Bug gua sendiri dari 10.A2; artinya test itu juga nondeterministik lokal.
        4. `test_auth_security.py` (4 test, dari Fase 7.2) ngandelin `.env`
           (docstring-nya malah nulis itu sbg kesengajaan). Sekarang env di-set
           `monkeypatch` per-test.
        5. 3 snapshot sensitif tanggal (`test_recent_campaigns`, `test_get_pirs`,
           `test_pir_export`) yang selama ini "gagal sebelum Fase 10": nilai
           `last_match`/`first_seen`/`last_seen` (`today - N hari`) dinormalisasi
           jadi `str` di matcher syrupy; diff `.ambr` cuma 6 baris tanggal. Suite
           sekarang 0 gagal.
        6. `test_golden.py` (5 test) butuh `tests/fixtures/`: sempat di-skip waktu
           folder itu di-.gitignore, lalu skip DICABUT lagi (lihat keputusan
           fixture) -- fixture ikut repo, jadi folder hilang = merah, bukan skip.
      - **Job baru di `.github/workflows/ci.yml`** (actionlint bersih): `web`
        (pnpm install --frozen-lockfile, eslint, `next typegen` + `tsc --noEmit`,
        `next build`; tsc standalone tanpa typegen MERAH palsu: `LayoutProps`
        cuma ada setelah typegen), `api-contract` (export OpenAPI + `gen:api` +
        `git diff --exit-code` atas `docs/openapi.json` & `schema.d.ts` -- dicek
        sekarang: nol drift), `compose` (`docker compose config -q`, 2 profil),
        `docker` (matrix 4 image: build + smoke-import DI DALAM image + cek
        non-root; smoke = `cti_api/cti_scrapers` ke-import, registry >= 80,
        punkt_tab + spaCy load, `server.js` ada -- SEMUA perintah smoke dijalankan
        di image staging beneran dan lolos). Ditambah `permissions: contents:
        read` + `concurrency` (batalkan run lama di ref yang sama).
      - **Gitleaks**: 61 temuan (default rules) di 16 fixture -- semuanya konten
        publik pihak ketiga (key BOOMR/reCAPTCHA, form-id HubSpot, 24 ID `AKIA...`
        di artikel berita, 1 JWT konfigurasi halaman, sampel `curl -u`). Di-scrub
        (715 kemunculan; panjang string dijaga) pakai `tools/ops/scrub_fixtures.py`
        (baca laporan gitleaks; 7 test) -> scan ulang 0 temuan, golden 430 tetap
        hijau. `.gitleaks.toml`: allowlist `tests/fixtures/` DICABUT (sebelumnya
        gate buta buat rekaman baru). Scan atas pohon yang akan di-commit + riwayat
        git: bersih; 3 secret PALSU di test (`test_check_secrets`,
        `test_scrub_fixtures`) ditandai `# gitleaks:allow` per baris.
      - **KEPUTUSAN FIXTURE (final, user)**: `tests/fixtures/` (46MB, 332 file) IKUT
        repo -- user mengeluarkannya dari `.gitignore` setelah sempat di-ignore
        (`.vscode/` tetap di-ignore). Fixture sudah di-scrub; scan gitleaks atas
        seluruh pohon yang akan di-commit (1087 file, fixtures ikut) = bersih, jadi
        golden test scraper JADI gate CI. `tests/fixture_report.2026-09-17.json`
        (laporan rekaman) ikut di-commit bareng fixture. Alur rekam ulang fixture:
        docstring `tools/ops/scrub_fixtures.py`.
- [x] **10.E** 14 dari 17 job Rundeck -> scraper/beat task (2026-09-26). Sisa 3
      (`offsetAlert`, `threatactorTrendGraylog`, `threatactorTrendTelegram`) semula
      DI LUAR scope; sesudah user bilang tidak paham fungsinya dan diskusi, hasilnya
      lihat **10.E2**: pasangan `threatactorTrend*` DIPORT (jadi satu laporan mingguan),
      `offsetAlert` tetap tidak diport. `techstackLibrary`
      sudah ditarik user (`cti-revamp/techstackLibrary`, DI LUAR repo git).
      Tiap job dibaca dulu dari skrip aslinya; bug lama yang ketemu DIPERBAIKI
      (bukan diport), disebut per job di bawah. Semua kode ter-test (mutation-checked)
      dan tiap komponen dijalankan LIVE di staging (LLM, Telegram, GitHub, deps.dev,
      MITRE, twitterapi.io asli).
      - **Fondasi**: `NoticeItem` (pesan Telegram murni tanpa enrichment; dedup per
        `key`; sink TIDAK menelan error -> item di-release dan diulang run berikutnya,
        beda dari `send_alert_*` lama; kena cold-start cap seperti artikel),
        `CveMentionItem` (+ sink ke `cve_mentions`), `cti_alerts.send_document`
        (caption > 1024 karakter -> pesan terpisah; nama file di-basename),
        mode **`--prime`** di `Runner`/`cti-scraper run` (lihat bawah),
        tabel **`cve_mentions`** + **`job_state`** (migrasi `a10e5c0de001`; test baru
        `test_migrations_match_models` -> ternyata SELURUH skema nol drift, jadi guard
        itu berlaku untuk semua migrasi berikutnya), hook penghitung mention CVE di
        pipeline enrichment (hanya artikel BARU `seen_count == 1`, di SAVEPOINT --
        `update_cve_mention` yang di Fase 5 dicatat "belum diport").
      - **Watcher commit GitHub** (`GithubCommitWatcher`, 1 family): `github_ttps`
        (`githubTTPs`, topik `apt`), `sophoslabs_github` (`githubSophoslab`),
        `apt_ttp_simulation` (`githubAptTTPSimulation`, patch jadi lampiran),
        `mitre_github` (`mitreGithub` + port `mitreValidator` sbg fungsi murni
        `mitre_changelog.py`). Bug lama diperbaiki: Sophoslab cuma mengabarkan file
        TERAKHIR per commit dan `commit_detail` tanpa token; `exit()` di commit yang
        sudah diproses menghentikan seluruh run; offset MITRE tercatat sebelum semua
        file terkirim; changelog MITRE gagal total kalau satu objek kurang field
        (`KeyError`), format waktu `%H:%M%:%S` rusak, dan blok "has a parent" salah
        kunci; field GitHub tidak di-escape untuk HTML Telegram.
      - **Advisory library** (`LibraryAdvisoryScraper`): `techstack_npm/pypi/go`
        (`techstackLibrary/*`). Bug lama: pesan dibangun SETELAH loop advisory ->
        cuma advisory TERAKHIR per versi yang dikabarkan (efek fix: 3 advisory lama
        yang tak pernah terkirim muncul sebagai notice baru di rehearsal); versi
        dibandingkan sebagai STRING; "5 versi terbaru" dicocokkan normalisasi-vs-mentah;
        `details` tanpa escape/batas. Dedup key = `<AdvisoryID>:<ModifiedDate>` =
        identitas `offset/techstack_*_offset.txt` lama. Daftar paket masih
        hardcoded (lodash/debug/request; requests/selenium/pandas; docker/runc) seperti
        skrip lama -- `monitored_packages` di dump KOSONG, jadi belum ada konfigurasi
        lain. **Token bot Telegram + chat/thread hardcoded di ketiga skrip** -> 12th
        secret di `docs/SECRETS_ROTATION.md`; kode baru pakai topik `library_advisory`.
      - **Alert tweet**: `tweet_alerts_1h`/`tweet_alerts_30m` (`twitter`/`twitter30`,
        495 dari 498 baris identik) + routing murni `tweet_routing.route_tweet`
        (cascade `_sendAlert` tweet, BEDA dari routing artikel: aturan "shame-site",
        `#threatreport`, "hacktivist alliance"). SATU query `(from:a OR from:b ...)`
        per run (bukan satu request per akun). LLM dipanggil terakhir (skrip lama
        SEBELUM filter murah). `trending_cve` (`trendingCve`) = pengumpul mention
        (dedup id tweet menggantikan kursor `lastTweetId.txt`); laporan 6 jamnya =
        task `report.trending_cve`. Bug/kuirk dipertahankan: filter `falconfeedsio`
        (`re.search(" ")` = praktis tanpa filter).
        **TEMUAN REHEARSAL**: free tier twitterapi.io = ~1 request / 5 detik; halaman
        ke-2 pencarian kena 429 -> run gagal total. Sekarang `_twitterapi` menunggu 6
        detik dan mengulang 429 (maks 3x). Cek tier API key produksi.
      - **Laporan periodik (task beat, `report.*`, queue `notify`)**: `daily_counters`
        (`sendCounter` -> topik `debug`; angka dihitung dari DB per hari lokal, bukan
        file `.txt`), `news_of_the_day` (`trendingNewsToday`; LLM; prompt jadi OBJEK
        `{"topics": [...]}` karena `json_object` menolak array), `logbook`
        (`logbook.py`; xlsx dari templat resmi, tanggal Indonesia dari tabel statis --
        bukan `GoogleTranslator` per tanggal), `weekly_top_cve` (`topCve`) dan
        `trending_cve`. Prinsip: baca DB -> TUTUP sesi -> kirim Telegram -> baru
        reset counter/state (kode lama mereset/mengosongkan SEBELUM kirim).
        Jam = jam LOKAL Rundeck lama -> UTC lewat `report_utc_offset_hours` (default 7,
        WIB): counter 23:55, NOTD 23:58, logbook 07:00, top CVE Minggu 07:01, trending
        tiap 6 jam. **ASUMSI: server Rundeck lama berjalan di WIB** -- set 0 kalau UTC.
      - **`--prime`** (`Runner(prime=True)` / `cti-scraper run <id> --prime`): fetch
        beneran, SEMUA item ditandai seen, sink dilewati (juga item non-artikel).
        Dipakai di cutover untuk scraper yang riwayat dedup-nya gak bisa dibawa dari
        sistem lama: watcher commit (offset lama cuma SHA, notice baru per (SHA,file))
        dan advisory library -- tanpa duplikat, tanpa "drip" advisory lama. Warm start
        (`fase10_warm_start.py --legacy-dir`) sekarang juga membaca file offset lama
        `APTattack_offset.txt` dan `techstack_*_offset.txt` (kunci formatnya identik;
        dijaga test kontrak yang membandingkan dengan kunci scraper aslinya).
      - **Topik Telegram baru** (wajib diisi di `.env` produksi, `.env.example`
        sudah): `notd`, `debug`, `library_advisory`, `logbook`. Guard baru
        `test_alert_topics`: topik yang dipakai kode harus ada di `.env.example`
        (typo topik = `UnknownAlertTopic` baru di produksi).
      - **Bug ASLI ketemu di jalan** (diperbaiki + regresi): `ArticleRepo.
        set_enrichment` gagal `UniqueViolation` kalau artikel yang sama di-persist
        dua kali dengan industri/negara yang sama (SQLAlchemy INSERT sebelum DELETE
        di flush yang sama) -- kejadian nyata kalau DUA scraper meliput URL yang
        sama (dedup itu per-scraper): artikel sehat dicatat `[enrichment_failed]`.
        Sekarang child dipakai ulang (`_reconcile`). Juga: urutan `count DESC` tanpa
        tie-break di statistik IOC (`test_ioc_stats` flaky di full suite) -> tie-break
        `IOC.type`. (~10 query `count DESC` lain di `dashboard.py`/`ta.py`/
        `tweet.py` punya risiko tie yang sama -- belum disentuh.)
      - **Rehearsal staging** (image dibangun ulang dari kode ini; migrasi
        `71dc81d1e99c -> a10e5c0de001` jalan): 10 scraper baru dry-run + real,
        `github_ttps` dingin -> cap 5 dari 14, `techstack_go --prime` -> 8 dari 8 di-skip,
        `techstack_npm` -> 3 notice baru (advisory yang dulu tak pernah terkirim),
        `apt_ttp_simulation` 4 notice dgn lampiran, `tweet_alerts_1h` 1 alert lewat
        LLM+429-retry, `trending_cve` 1 mention; 5 task laporan jalan (counter
        64 artikel + 2 file, NOTD global+apac, logbook 33 baris xlsx, top CVE MITRE
        asli, trending). Kejadian tak terduga: `tar` dari macOS ikut membawa 3.472
        file `._*` (AppleDouble) ke staging dan bikin `alembic` gagal `SyntaxError:
        null bytes` -- sync berikutnya WAJIB `COPYFILE_DISABLE=1 tar ...`.
      - **Test baru (mutation-checked; angka = fungsi test, kasus terparametrisasi
        lebih banyak)**: `test_notice_item` (9), `test_github_watchers` (13),
        `test_mitre_changelog` (9), `test_library_advisories` (11),
        `test_tweet_routing` (8), `test_tweet_alerts` (18), `test_cve_mention_sink`
        (3), `test_report_state_repo` (6), `test_report_tasks` (18), `test_logbook`
        (8), `test_cve_record` (10), `test_report_timeutil` (4), `test_alert_topics`
        (3), `test_migrations_match_models` (1); tambahan di `test_runner` (+4 prime),
        `test_repositories` (+4 idempotensi), `test_enrich_pipeline_resilience` (+4
        mention CVE), `test_warm_start` (+4), `test_beat_schedule` (+3).
      - **Verifikasi akhir 10.E**: simulasi CI di checkout bersih (tanpa `.env`, dengan
        fixtures yang sekarang ikut repo): `ruff check`, `ruff format --check`, `mypy`
        hijau; **1615 lulus, 2 skip** (2 test dump-asli tanpa `legacy/dump`), 0 gagal.
        Belum di-commit (akhir Fase 10).
      - **Belum / perlu keputusan user**: (1) konfirmasi zona waktu Rundeck lama
        (WIB?); (2) thread ID Telegram produksi untuk 4 topik baru; (3) tier
        twitterapi.io produksi (free tier = 1 req/5 dtk); (4) `logbook` sekarang DIKIRIM
        ke Telegram (skrip lama cuma menulis file, baris `send_file` dikomentari) --
        ok?; (5) nama penandatangan logbook default = nilai hardcoded lama
        (`WORKER__LOGBOOK_*`); (6) 3 job di luar scope (lihat atas).
- [x] **10.E2** Keputusan user sesudah 10.E + sumber Twitter ganda (2026-09-26/27).
      Jawaban user: zona waktu ikut asumsi WIB; thread ID Telegram staging sudah diisi
      (termasuk topik baru `top_ta`); logbook boleh dikirim ke Telegram (user menulis
      "twitter", dibaca Telegram -- isinya file Excel); API resmi X **pay-per-use**;
      pilihan sumber **per-scraper**, **manual** (tanpa auto-fallback); laporan tren
      threat actor dihidupkan, **Senin 13:00 WIB**; bearer di `stg.env` (nama
      `X__BEARER_TOKEN`, dikoreksi user dari `X__BEARER__TOKEN`).
      - **Opsi per-scraper** (`ScraperMeta.options`, generik -- bukan khusus Twitter):
        `ScraperOption`/`OptionChoice` (pilihan TERTUTUP, tiap pilihan boleh membawa
        `credential`), `cti_scraper/options.py` (`resolve_options` toleran terhadap
        data DB usang, `validate_options` ketat buat API/CLI, `credential_for`),
        `ScrapeContext.options`. `Runner` memilih kredensial dari opsi aktif; override
        eksplisit `Runner(options=...)`/CLI `--option key=value` menang atas pilihan
        admin dan TIDAK menulis DB (coba sumber lain sekali jalan). Kolom
        `scraper_config.options` (JSONB, migrasi `a10e5c0de002`). API: `GET /{id}`
        memuat `options[]` (pilihan + nilai efektif), `PUT /{id}/config` memvalidasi
        (422 + daftar pilihan valid), `POST /{id}/dry-run` memakai pilihan TERSIMPAN
        (kalau tidak, "uji dulu sebelum ganti" menguji sumber yang salah). UI: dropdown
        di dialog detail scraper (Base UI `Select` dengan `items`), hanya pilihan yang
        beda dari default yang disimpan, penanda "belum disimpan".
      - **KEBIJAKAN sumber Twitter (keputusan user 2026-09-27)**: **twitterapi.io = jalur
        UTAMA dan dipaksa duluan; API resmi X = CADANGAN**, dipakai hanya kalau twitterapi.io
        memang tidak bisa. Pindah **MANUAL** (tanpa auto-fallback -- keputusan sebelumnya:
        biar kuota tidak terbakar diam-diam). Default di kode tetap `twitterapi_io`, tidak ada
        baris `scraper_config.options` kecuali admin sengaja memilih, dan teks dropdown
        menyebut X resmi "cadangan". Yang dianggap "tidak bisa" (usulan gua, belum
        dikonfirmasi user): kunci ditolak / kredit habis / layanan mati -- tampak sebagai
        `fetch_error` atau `parse_error` berulang di `tweet_alerts_*`/`trending_cve`, atau
        status health `degraded`/`dead`. BUKAN alasan pindah: 429 free tier (sudah ada
        retry+backoff, hanya lambat), atau selisih beberapa tweet antar provider.
      - **Sumber Twitter**: `collectors/_twitter.py` (bentuk netral `Tweet`/`TweetSearch`,
        dispatcher, deklarasi opsi), `_twitterapi.py` (perilaku lama, sekarang lewat
        bentuk netral -- 23 test `test_tweet_alerts` lama lolos TANPA diubah),
        `_x_official.py` (`GET /2/tweets/search/recent`: `-is:reply`, `start_time`,
        `expansions=author_id`, `note_tweet` untuk tweet panjang, teks di-unescape
        supaya pesan Telegram tak ter-escape dua kali, paginasi `next_token`,
        401/402/403/400 -> `ParseError` berisi judul+detail X, 429/5xx dibiarkan ke retry
        Runner karena jendela rate limit X 15 menit). Dedup tetap `{id tweet}:{topik}`
        (id sama di kedua API) -> ganti sumber tidak bikin alert dobel.
        `tweet_alerts_1h/30m` dan `trending_cve` punya opsi `provider`; **default tetap
        twitterapi.io**. `trending_cve` diberi peringatan biaya di dropdown (mencari
        SEMUA tweet "CVE-<tahun>-" di seluruh X = ribuan tweet/hari; ~$0,005/tweet).
        Secret: `XSettings.bearer_token` -> `X__BEARER_TOKEN` (SATU underscore; `__` =
        nesting, dan `extra="forbid"` membuat nama salah gagal-START, ada test-nya);
        credential `"x"` -> `Authorization: Bearer`. Cuma bearer -- consumer/access
        key tidak dipakai dan tidak boleh ditaruh di server.
        **Pengaman biaya**: maks 2 halaman x 100 = 200 tweet dibaca per run (~$1) dan
        pemotongan dicatat (`x_official_truncated`); tiap pencarian mencatat tweet
        dibaca + perkiraan biaya (`x_official_search`); resource yang sama di hari UTC
        yang sama tidak ditagih dua kali (jendela 2x interval aman); batas belanja
        bulanan dipasang user di X Developer Console.
      - **Laporan tren threat actor** `report.weekly_threat_actor_trend` -> topik `top_ta`,
        Senin 13:00 WIB (jadwal pilihan user, BUKAN jadwal Rundeck lama; ikut
        `WORKER__REPORT_UTC_OFFSET_HOURS`, hari ikut bergeser lewat tengah malam).
        Gantiin pasangan `threatactorTrendGraylog`+`Telegram`: datanya dihitung dari
        `article_threat_actors` + `articles.first_seen_at` -- TANPA Graylog, tanpa file
        `ThreatActorName.txt`, tanpa dua token hardcoded (yang tetap harus dicabut,
        SECRETS_ROTATION #1/#2). Sama: dua jendela bergulir 7 hari, top 5 menurut jumlah
        artikel, banding naik/turun/tetap/baru; beda: ejaan digabung tanpa peduli
        huruf besar/kecil, "Baru muncul" tanpa persen (lama: jumlah x 100 = tak bermakna),
        pekan kosong tidak kirim pesan, nama grup di-escape HTML. `as_of` (ISO) buat
        mengulang. Bug yang ketemu SAAT menulis test: jumlah per-ejaan dijumlahkan ->
        satu artikel yang menyebut "APT41" dan "Apt41" terhitung dua kali (diperbaiki).
      - **`offsetAlert` tetap tidak diport**: alarm "file offset > 30 hari" sudah rusak
        dari lama (semua scraper tampak mati sejak dedup pindah ke Mongo) dan file offset
        tidak ada lagi; health sweep Fase 9 (`dead`/`degraded`/`zero_yield`) menggantikan.
        Celah kecil yang DISADARI: feed yang fetch-nya sukses tapi isinya beku (semua item
        sudah pernah terlihat) tidak ditandai (`zero_yield` hanya kalau fetch balik 0 item).
        Sinyal "tak ada item BARU N hari" bisa ditambah nanti; berisik buat feed jarang-update.
      - **Test baru (92)**: `test_scraper_options` (9), `test_x_official` (23; 12 mutasi
        adapter mati semua), `test_cli_options` (7), `test_credentials` (+3),
        `tests/contract/test_scraper_options` (16; opsi tiap scraper konsisten -- default
        termasuk pilihan, kredensial dikenal, `meta.credential` = kredensial pilihan default),
        `test_runner_options` (6; DB -> Runner -> header HTTP), `test_scraper_options_api`
        (13; termasuk dry-run memakai pilihan tersimpan), `test_threat_actor_trend` (12),
        `test_beat_schedule` (+1), `test_x_official` (+2 lagi untuk `with_author`). Semuanya mutation-checked; 3 mutan yang sempat SELAMAT
        (urutan peringkat, `as_of` naif, `{}` vs `null`) menemukan test yang lemah dan
        sudah diperketat.
      - **Verifikasi terhadap API X asli** (bearer staging; total belanja seluruh uji live
        ~17 tweet unik = di bawah $0,10):
        `GET /2/usage/tweets` HTTP 200 (batas proyek 3.000.000 baca; `project_usage` tidak
        real-time -- selisih sebelum/sesudah probe 0 padahal 5 tweet dibaca, jadi jangan
        dijadikan alat ukur biaya per run). Nama parameter `tweet.fields` (termasuk
        `note_tweet`, `referenced_tweets`, `entities`, `created_at`), `expansions=author_id`,
        `user.fields=username` DITERIMA (X memvalidasi field dulu lalu berhenti di error
        pertama -- dibuktikan dengan `start_time` masa depan + kontrol field ngawur; validasi
        query justru SESUDAH validasi parameter, jadi sintaks hanya terbukti lewat pencarian
        sungguhan). Probe sungguhan: `(from:a OR from:b ...) -is:retweet -is:reply` dan
        `CVE-2026- -is:retweet -is:reply -is:quote` -> HTTP 200; `"CVE-2026-"` dengan/tanpa
        kutip memberi hasil identik -> **tanpa kutip**. Tweet panjang akun sungguhan
        (DailyDarkWeb) datang dengan `note_tweet` -> penanganan `note_tweet` terbukti
        perlu. Dokumentasi X menulis `post.fields`; `tweet.fields` yang dipakai dan valid.
      - **Temuan biaya**: `expansions=author_id` membuat X ikut mengirim objek user, yang
        kemungkinan ditagih terpisah (lookup user ~$0,010 per user unik per hari UTC). Untuk
        `tweet_alerts_*` (<= 21 akun) itu maksimal beberapa sen per hari; untuk `trending_cve`
        (ribuan penulis unik) bisa melipatgandakan tagihan -- makanya `TweetSearch.with_author`
        (default True) dimatikan di `trending_cve`: tanpa `expansions`, tanpa username, URL
        `x.com/i/status/<id>`. Terbukti di API asli (dry-run `trending_cve` X resmi: HTTP 200,
        8 tweet, tanpa `includes`).
      - **Uji di staging** (image dibangun ulang, migrasi `a10e5c0de002` dijalankan,
        7 container healthy, `X__BEARER_TOKEN` termuat):
        dry-run twitterapi.io vs X resmi -> `tweet_alerts_30m` 0 vs 0, `tweet_alerts_1h`
        4 vs 4 notice, `trending_cve` 6 vs 8 (indeks berbeda, selisih detik). X resmi ~0,5 dtk
        untuk pencarian vs 18-35 dtk di twitterapi.io free tier (429 + backoff).
        **Dedup lintas provider terbukti**: run sungguhan `tweet_alerts_1h` via X resmi
        `items_new=4`, lalu via twitterapi.io tweet yang sama `items_new=0 items_dropped=4`.
        Kontrol plane e2e lewat proxy web (login `stg-admin`): GET memuat `options` + nilai
        efektif, PUT menyimpan (`updated_by` tercatat), nilai/key salah 422 dengan daftar
        pilihan valid, scraper tanpa opsi 422, gagal-PUT tidak mengubah pilihan tersimpan,
        dry-run memakai pilihan TERSIMPAN (log `x_official_search` muncul di container api),
        `options=null` dan `reset-config` mengembalikan default. State staging dibersihkan
        (semua scraper kembali ke default twitterapi.io). **Dropdown di UI belum dilihat mata
        di browser** (login browser butuh kredensial; lint + `tsc` + `next build` di image
        lolos).
      - **Verifikasi**: simulasi CI di checkout bersih (tanpa `.env`): `ruff check`, `ruff
        format --check` (ruff juga memformat blok kode di `docs/*.md` -- ketahuan di sini),
        `mypy` hijau; **1707 lulus, 2 skip** (1709 test = 1617 + 92 baru), 0 gagal.
        `openapi.json` + `schema.d.ts` di-generate ulang (diff = hanya penambahan `options`);
        `eslint` + `tsc --noEmit` web bersih. Belum di-commit (akhir Fase 10).
- [x] **10.E2 sisa**: dropdown "Sumber data Twitter/X" DIVERIFIKASI di browser (staging via SSH
      tunnel `13000`, login server-side `stg-admin`, izin user) -- label "twitterapi.io (utama)"/
      "X API resmi (cadangan)" muncul benar, simpan bertahan setelah reload, Reset to Defaults
      jalan. Dua cacat kosmetik (label terpotong, teks dialog reset) dibenerin. Browser sudah
      logout. Disk staging sempat 100% penuh (Docker build cache 30 GB dari build gua berulang) ->
      di-prune dengan izin user (`docker image prune` + `docker builder prune --filter until=6h`,
      17,9 GB kembali, sekarang ~16 GB kosong); volume TIDAK disentuh.
- [x] **10.F** Rotasi 13 secret (lihat `docs/SECRETS_ROTATION.md`) -- **didelegasikan ke tim ops user
      2026-09-30, dieksekusi tim tersebut di luar sesi/repo ini** (bukan hasil verifikasi teknis; token
      belum dicek ulang dari sisi platform baru). Template `.env` prod (keputusan 4) SELESAI dikerjakan
      di sesi ini (`.env.prod.template`).
- [~] **10.G** Runbook cutover + latihan + bukti (2026-09-27). **Kode, dokumen, dan latihan
      di staging SELESAI; sisanya butuh user/produksi** (daftar di "Belum" bawah).
      - **Runbook**: `docs/CUTOVER_RUNBOOK.md` (prasyarat, cutover 12 langkah dengan perintah,
        pantau 4 jam, hypercare, backup, rollback 3 tingkat, sumber Twitter utama/cadangan,
        troubleshooting dari kejadian nyata, dan bagian "Yang BELUM terbukti" yang jujur).
        Templat: `docker/ops/nginx-cti.conf.example` (`X-Forwarded-For` WAJIB),
        `cti-pg-backup.{service,timer}`. Komentar `CTI_TAG` di `stack.env.example` yang menyuruh
        "rollback = ganti tag + up -d" DIKOREKSI (itu jebakan, lihat temuan 1).
      - **Alat baru `tools/ops/`** (stdlib, jalan di host tanpa `uv`; semua mutation-checked):
        `pg_backup.py` backup/verify/restore/prune (33 test), `notify_telegram.py` (10),
        `rollback.py` (21), `rundeck_schedule.py` (12), `check_secrets.py` +cek bearer X (+3).
      - **Latihan backup Postgres** (staging, DB kecil 1,1 MB): backup 0,45 dtk, `verify`
        (restore ke DB scratch + banding `alembic_version` dan 6 tabel kunci + drop scratch)
        3,4 dtk -> semua cocok, restore ke DB bernama 1,2 dtk. Pengaman terbukti live: restore
        ke DB live DITOLAK, ke DB berisi DITOLAK tanpa `--replace`, pg-exec salah -> exit 1 +
        alarm (`--on-failure-cmd`) jalan dan tidak meninggalkan berkas.
      - **Latihan rollback versi** (image `:stg` = N, `:prev` = N-1 tanpa migrasi terakhir):
        (1) **TEMUAN 1 -- rollback naif `CTI_TAG=prev docker compose up -d` bikin OUTAGE**:
        `migrate` (jalan tiap `up`) gagal "Can't locate revision a10e5c0de002" dan compose sudah
        terlanjur menghentikan api/worker yang bergantung padanya. (2) Prosedur benar (downgrade
        pakai image BARU, lalu ganti tag): 21,9 dtk sampai semua healthy. Dijadikan alat
        `rollback.py` (pre-flight revisi DB vs head target, gabung riwayat KEDUA image, downgrade
        hanya dengan `--yes`, tolak riwayat bercabang, tidak lanjut `up` kalau downgrade gagal,
        verifikasi revisi akhir). Waktu terukur: rollback 19,2-23,1 dtk, roll-forward 22,3 dtk,
        satu siklus mundur+maju 41,9 dtk. **Bug di alat ini ketemu OLEH LATIHAN**: roll-forward
        salah dianggap "bercabang" karena riwayat cuma dari image sekarang (image lama tak kenal
        revisi baru) -> sekarang riwayat digabung; dan **oleh tes**: baris riwayat merge/cabang
        DILEWATI diam-diam oleh regex (harusnya ditolak) -> parser diganti.
      - **Bukti health sweep dengan beat** (staging, sweep tiap 3 mnt, thread `scraper_health`
        asli): beat terpilih `beat_leader`; digest pertama 14:42:00 `problems=92 total=94`
        terkirim ke Telegram dalam ~2 dtk; scraper browser `any_run_trends` (jadwal dipaksa
        tiap menit) jalan normal, lalu `worker-browser` DIMATIKAN -> 6 menit kemudian status
        **`dead`** dan tercantum di digest 14:48 (isi pesan diambil dengan fungsi asli, kirim
        Telegram diganti print: `dead (22): ... any_run_trends ...`, `degraded (1): doyensec`);
        `worker-browser` dinyalakan -> `ok` di run pertama, backlog terkuras. `degraded` juga
        terdeteksi alami (parse_error XPath/XML). Pesan digest 2.350 karakter (< batas 4096).
        Catatan desain (masuk runbook): digest dikirim ULANG tiap sweep selama masih ada
        masalah (tidak ada dedupe); dan digest lewat queue `notify` yang dilayani container
        `worker` -- kalau `worker` yang mati, digest tidak bisa melaporkannya (alarm ikut mati).
      - **TEMUAN 2 -- thundering herd** (dari latihan di atas): worker mati -> beat terus
        mengirim tick -> saat worker nyala SEMUA tick menumpuk dieksekusi sekaligus (di produksi:
        mati 24 jam = puluhan run per scraper, 25 scraper Chromium serentak). Perbaikan: tick
        scrape kedaluwarsa setelah SATU interval jadwalnya (`options.expires` di beat; task
        periodik/laporan sengaja TIDAK kedaluwarsa). Terbukti live: worker-browser mati 3,4 mnt
        -> 12 tick menumpuk -> saat nyala tick basi dibuang (`Discarding revoked task`) dan
        `any_run_trends` cuma jalan 1x. (4 test, mutasi mati semua.)
      - **TEMUAN 3 -- `monitor_x` TIDAK viable di twitterapi.io free tier** (ketemu di beat staging):
        satu query PER AKUN x 18 akun berturut-turut; free tier ~1 request/5 dtk untuk SELURUH
        key, dibagi juga dengan `tweet_alerts_*`/`trending_cve`. Sudah ditambah backoff 429
        (`_twitterapi._get_with_backoff`: tunggu 6 dtk, ulang maks 3x; 3 test) -- **TAPI di live
        BELUM menyelesaikan**: run berubah dari gagal-cepat jadi gagal-lambat (`fetch_error`
        40-130 dtk, nol tweet) lalu `rate_limited` dari token bucket domain lokal. Bucket Redis
        itu rata-rata, bukan jeda 5 dtk antar request, jadi tidak menolong. Yang BELUM
        diputuskan: (a) tier PRODUKSI twitterapi.io berbayar (QPS jauh lebih tinggi) -> scraper ini
        jalan apa adanya; atau (b) redesign: SATU query OR per run + dedup id tweet (kunci sudah
        id tweet), pindah ke lapisan sumber netral (`collectors/_twitter.py`) -- butuh `Tweet`
        netral diperluas (nama, avatar, followers, media, lang) dan `since_id` per akun diganti
        jendela `since_time`. **Pertanyaan terbuka ke user: tier produksi twitterapi.io?** Sampai
        dijawab, tab X Intel di staging kosong dan `monitor_x` akan `degraded` di digest.
      - **Update 2026-09-30 (permintaan user "kasih delay biar gak kena rate limit", bukan minta tier
        berbayar)**: dua bug ketemu, dua-duanya diperbaiki. (1) `rate_limit` `monitor_x` beda dari 3
        scraper lain di domain yang sama ("15/minute" vs "10/minute" ke-3 lainnya) -- melanggar
        invarian modul `ratelimit.py` sendiri ("domain dibagi rata"), disamakan ke "10/minute". (2)
        18 akun berturut-turut TANPA jeda menghabiskan budget LOKAL kita sendiri (Redis token
        bucket) sebelum server sempat balas 429 sama sekali -- itu penyebab `rate_limited` yang
        belum kejelasan di TEMUAN 3, bukan cuma bucket "rata-rata" yang disebut di atas. Diperbaiki:
        jeda PROAKTIF `window_s/capacity` (6 dtk, diturunkan dari `rate_limit` yang sama, bukan angka
        baru) di antara akun, dan `_get_with_backoff` sekarang menangkap `RateLimited` (budget lokal)
        selain `TransientFetchError` "HTTP 429" (server), nunggu jendela reset yang BENAR (60 dtk,
        bukan 6 dtk punya-nya 429) baru mengulang. 6 test `monitor_x_backoff` (dari 3) + mutasi 8/8
        mati. **Masih BELUM dibuktikan live/staging** -- opsi (a) tier berbayar dan (b) redesign OR-
        query di atas masih relevan kalau ini terbukti belum cukup.
      - **TEMUAN 4 -- `new_cve` membungkus SEMUA exception MITRE jadi `ParseError`**, jadi batas
        laju domain (`RateLimited`) dan 429/5xx tampil sebagai "struktur situs berubah"
        (`degraded`) -- terlihat di digest. Sekarang error framework diteruskan apa adanya
        (status run `rate_limited`/`fetch_error`). (6 test.) Yang BELUM ditangani: `new_cve`
        tanpa dedup (upsert ulang tiap run) dan `rate_limit=60/minute` -> kalau kandidat CVE per
        run > 60, run selalu terhenti di kandidat yang sama (starvation potensial).
      - **Rehearsal sampel besar = beat asli 60 menit di staging** (14:40-15:41 UTC, LLM gateway
        asli, Telegram tes asli; 16 dari 94 scraper masih "dingin"): **92/94 scraper sempat jalan**;
        run: ok 121, parse_error 28, fetch_error 17, rate_limited 8, empty 5 (dedup membuang
        **1.074 item duplikat** -> warm start terbukti bekerja; `cold_start_cap` memotong 15 item
        `mandiant`, 5 lolos); **106 artikel baru diproses, 19 ditolak klasifikasi, 0 gagal
        diproses** (`[enrichment_failed]` = 0); queue `enrich` puncak 13 (concurrency NLP = 1,
        habis dalam beberapa menit); 12 digest health terkirim tanpa satu pun kegagalan Telegram;
        **nol ERROR di api/beat/worker-browser**, dan di worker/worker-nlp hanya: `_RetryableRunError`
        (pembungkus retry Celery untuk run yang memang gagal) dan `HTTP 403` dari
        `bleepingcomputer.com` saat mengambil teks artikel (IP staging diblokir; artikel tetap
        diproses). RAM: worker-nlp 449 MB, worker 365 MB, worker-browser 250 MB, api 432 MB.
        BELUM teruji: `NLP_WORKER_CONCURRENCY` > 1 dengan volume produksi (pelajaran 10.B).
      - **CENSUS dari IP staging** (run terakhir non-ok per scraper; 30 dari 92 = 33%): **18
        XPath tak cocok** -- abnormalsecurity aquasec blackberry cis cloudflare cymru dragos groupib
        huntio huntress intel471 k7security koisec landth prodraft proofpoint sans splunk (situs
        berubah ATAU bot-protection memblokir IP staging); **7 XML tak valid (respons bukan
        feed)** -- cisa cybersecnews exploitdb google nquiring_minds sysdig threatmon; **2 `item_path`
        Atom tak cocok** -- doyensec trustwave; **2 batas laju domain** -- monitor_x (twitterapi.io,
        temuan 3) dan new_cve (MITRE 60/mnt, temuan 4; status kini `rate_limited` sesudah perbaikan);
        **1 timeout** -- ecrime. Sebagian besar sudah dikenal dari census 10.B/KNOWN_BROKEN, tapi
        angkanya JAUH lebih besar dari yang tercatat (10.B hanya menguji 49 feed ringan; browser +
        API belum). **Wajib diulang dari IP PRODUKSI sebelum cutover** -- dari staging tidak bisa
        dibedakan "selector rusak" vs "IP diblokir" -- lalu tiap scraper live tanpa golden test
        hijau butuh perbaikan atau waiver tertulis (gate 10.D). Health sweep sudah menampilkan
        semuanya sebagai `degraded` di digest (itu memang fungsinya).
      - **CENSUS DIULANG 2026-09-30** (permintaan user): user sadar staging punya `warp-cli`/`warp-svc`
        (Cloudflare WARP) yang mungkin nge-tunnel egress lewat IP yang di-block situs anti-bot --
        dimatikan sebelum ulang census. Diverifikasi dulu (read-only): `systemctl is-active warp-svc`
        masih `active` (daemon-nya idle, bukan mati total), TAPI IP publik staging SEKARANG
        (`ipinfo.io`) balik ke `AS131111 PT Mora Telematika Indonesia` (ISP asli, Jakarta) -- BUKAN
        range Cloudflare -- dan default route langsung ke gateway LAN, bukan interface WARP. Skrip
        census ditulis ulang (`census2.py`, yang lama sudah kehapus bareng scratchpad sesi
        sebelumnya) -- satu proses Python jalan DI DALAM `cti-worker:stg`, iterasi `Runner(...,
        dry_run=True)` per scraper (bukan 94x `docker run` terpisah), 658 detik total.

        **Hasil: 24 dari 94 gagal** (turun dari 30/92) -- **18 XPath tak cocok** (LIST IDENTIK
        dengan sebelumnya, huruf demi huruf: abnormalsecurity aquasec blackberry cis cloudflare
        cymru dragos groupib huntio huntress intel471 k7security koisec landth prodraft proofpoint
        sans splunk); **4 XML tak valid** -- cisa google nquiring_minds sysdig (turun dari 7: cybersecnews
        exploitdb threatmon HILANG dari daftar gagal); **2 `item_path` kosong** -- doyensec trustwave
        (tetap); **0 batas laju** (turun dari 2: monitor_x DAN new_cve sekarang `ok` -- lihat detail
        `monitor_x` di TEMUAN 3, tapi `new_cve` yang tadinya `rate_limited` juga sekarang lolos tanpa
        sentuhan kode APAPUN di sesi ini, jadi murni efek WARP mati); **0 timeout** (turun dari 1:
        `ecrime` sekarang `ok`).

        **Baca hasil ini apa adanya**: 18 XPath yang PERSIS SAMA sebelum/sesudah WARP dimatikan adalah
        bukti kuat itu genuinely selector situs berubah (bukan IP diblokir) -- kalau itu IP-blocking,
        harusnya ikut hilang juga seperti 5 yang lain. Sebaliknya, 5 yang hilang (rate-limit x2, timeout,
        XML x3 minus yang masih gagal) adalah kandidat kuat "itu WARP", walau tidak 100% bisa dipisah
        dari kemungkinan lain (jam berbeda, situs berubah kebetulan bersamaan). `monitor_x` KHUSUSNYA
        punya bukti live tambahan: 429 tetap terjadi tiap akun (1x per akun, 18 kali, ~330 detik total)
        TAPI sekarang berhasil sampai selesai (`status=ok`, 23 item) -- pacing 10.G2 yang menyelamatkannya
        dari 429 berulang, bukan cuma soal WARP.

        **Belum diuji sama sekali di census ini**: fetch teks artikel penuh (stage enrichment, BUKAN
        `fetch()` scraper) -- termasuk 403 `bleepingcomputer.com` yang tercatat sebelumnya; `dry-run`
        berhenti di `fetch()`, gak sampai ke situ. **Kesimpulan soal gate 10.D**: staging sekarang cukup
        dipercaya buat mastiin 24 sisa itu genuine (bukan sekadar "IP staging diblokir") -- census dari
        IP PRODUKSI SUNGGUHAN jadi TIDAK LAGI wajib blocking, tapi tetap direkomendasikan sebagai sanity
        check terakhir sebelum go-live kalau egress produksi beda jalur dari staging.

      - **Perbaikan selector 2026-09-30** (permintaan user, "prioritas paling gampang" dulu): dari 24
        sisa, 2 `item_path` diperbaiki, 1 dari 4 "XML tak valid" dikonfirmasi flaky (bukan bug), 3
        dikonfirmasi BUKAN gampang (site migration tanpa pengganti jelas). 18 XPath BELUM disentuh.
        - **`doyensec` -- FIXED, bug MIGRASI (bukan situs berubah)**: feed-nya Atom sejak awal
          (`<feed xmlns="...atom...">`, `<entry>`, `<link href="...">`), tapi codemod Fase 4 nge-generate
          scraper ini pakai default `RSSScraper` yang RSS-shaped (`.//item`, `link` `.text`) --
          overridenya emang gak pernah ada. Fix: `item_path=".//{ns}entry"`, `title_path="{ns}title"`,
          `link_path="{ns}link"`, `link_attr="href"`.
        - **`trustwave` -- FIXED, URL pindah (rebrand jadi LevelBlue)**: URL lama 301 ke feed yang
          SENGAJA dikosongkan sumbernya (`<title>[DO NOT USE] SpiderLabs Blog</title>`, nol `<item>`) --
          BUKAN selector yang salah, dan `follow_redirects=True` sudah bekerja benar, cuma tujuannya
          mati. Feed aktif ketemu dari `<link rel="alternate" type="application/rss+xml">` di halaman
          blog live: `levelblue.com/blogs/spiderlabs-blog/rss.xml` (tanpa `en-us`). `meta.source` diganti
          "LevelBlue SpiderLabs (dulu Trustwave)" -- efek samping: alias `by_source` di
          `fase10_warm_start.py` builds dari `meta.source` LIVE, jadi dump lama (masih label
          "trustwave") gak ke-match lagi. Ditambal: entri `ALIASES["trustwave"] = "trustwave"` eksplisit
          (test regresi `test_real_dump_resolves_every_key_and_only_retired_sources_are_dropped` yang
          nangkep ini butuh fix, bukan cuma teori).
        - **`cisa` -- KEMUNGKINAN FLAKY, TIDAK diubah**: fetch ulang 4x berturut-turut (byte SAMA
          persis tiap kali) parse bersih tanpa error -- gagal di census kemungkinan hiccup transien
          sesaat (jaringan/server), bukan bug yang reproducible. Tidak ada kode yang disentuh.
        - **`google`, `nquiring_minds`, `sysdig` -- DIKONFIRMASI BUKAN gampang, belum diperbaiki**:
          `google` (`blog.google/threat-analysis-group/rss/`) sekarang balikin halaman 404 Google
          sendiri (`<title>Error 404 (Not Found)!!!</title>`) -- blog TAG dibubarkan/direstrukturisasi;
          `blog.google/threat-analysis-group/` redirect ke `blog.google/security/` yang RSS-nya
          (`blog.google/security/rss/`) isinya keamanan PRODUK umum (Android/Chrome/AI), bukan threat
          intel -- ganti scope, bukan ganti URL doang, butuh keputusan bukan cuma perbaikan.
          `nquiring_minds` (`/feed/`) sekarang 404, homepage-nya gak nyantumin link blog/news/feed sama
          sekali di HTML mentah (kemungkinan pindah CMS/SPA) -- gak ada sitemap.xml juga. `sysdig`
          (`/blog/topic/threat-research/feed/`) redirect ke URL yang JUGA 404. Ketiganya butuh
          investigasi manual lebih dalam (mungkin browser interaktif) atau waiver tertulis (gate 10.D).
        - **18 XPath tak cocok -- belum disurvei sama sekali**: abnormalsecurity aquasec blackberry cis
          cloudflare cymru dragos groupib huntio huntress intel471 k7security koisec landth prodraft
          proofpoint sans splunk. Menyusul.
        - Test baru `test_census_selector_fixes.py` (5, fixture dari HTML/XML NYATA yang ditarik live
          2026-09-30) + `test_warm_start.py` alias (1 baru via dump asli). 7 mutasi, 0 selamat. Full
          suite sesudahnya: **1880 lulus, 0 gagal, 0 skip.**
      - **KESALAHAN gua yang harus diketahui**: (a) cek kunci `stg.env` dengan `${v:+..}${v:-..}`
        MENCETAK nilai NVD/GitHub/LLM-gateway/twitterapi.io ke transkrip sesi -> dilaporkan ke
        user, rotasi diserahkan ke keputusan user (memori `never-echo-secrets`); (b) `echo "K=v" >> stg.env`
        menempelkan baris ke akhir `X__BEARER_TOKEN=...` karena file tanpa newline akhir -- ketahuan
        seketika (grep) dan dipulihkan dari backup `stg.env.bak-10G`; (c) harness mutation-check
        gua cacat (cache `.pyc` mutan sebelumnya dipakai kalau ukuran file sama dalam detik yang
        sama -> "KILLED"/"SURVIVED" bisa palsu) -> diperbaiki (`PYTHONDONTWRITEBYTECODE` + hapus
        `.pyc` + cek baseline hijau) dan SEMUA mutation-check sesi ini diulang: 0 selamat.
        Mutation-check 10.E di sesi sebelumnya memakai harness lama dan BELUM diulang.
      - **Disk staging** sempat 100% (build cache 30 GB) lalu 95% lagi sesudah build berulang;
        di-prune dengan izin user (`image prune` + `builder prune --filter until=`); volume tidak disentuh.
      - **Latihan restore penuh ke DB live DIBLOKIR pengaman** (memuat `TRUNCATE` + `DROP DATABASE` di
        staging) -- tidak dijalankan, tidak diakali; menunggu izin eksplisit user.
      - **Belum / butuh user atau produksi**: (1) restore penuh ke DB live (izin); (2) latihan
        rollback ke STACK LAMA <5 menit di produksi (`rundeck_schedule.py` baru diuji dengan API
        palsu, belum ke Rundeck asli); (3) census feed dari IP produksi + waiver; (4) pasang
        nginx/systemd timer backup/salinan off-host di host produksi; (5) tier twitterapi.io
        produksi; (6) rotasi kunci yang tercetak (lihat KESALAHAN a) dan 10.F.
      - **Test baru 10.G (91)**: `pg_backup` 33, `notify_telegram` 10, `rollback` 21,
        `rundeck_schedule` 12, `monitor_x_backoff` 3, `new_cve_errors` 6, `beat_schedule` +3,
        `check_secrets` +3. Simulasi CI checkout bersih: ruff, format, mypy hijau,
        **1798 lulus, 2 skip** (simulasi CI FINAL di checkout bersih, sesudah semua perubahan 10.G).

- [x] **10.G2** nginx di compose + sertifikat self-signed + temuan CVE Tracker (2026-09-26/27, permintaan user).
      - **nginx = service compose** (`profile app`, dibuka ke luar di `NGINX_BIND_ADDR:80/443`; api/web/postgres/redis
        tetap `127.0.0.1`). Image sendiri `docker/nginx.Dockerfile` (nginx:1.27-alpine + openssl; `nginx:alpine`
        polos TIDAK punya openssl), tag `cti-nginx:1` **tidak ikut `CTI_TAG`** supaya `rollback.py` tak menyentuh edge.
        Berkas: `docker/nginx/templates/cti.conf.template`, `05-selfsigned-cert.sh`, `06-cert-renew-loop.sh`;
        variabel `NGINX_*` di `docker/stack.env.example`; `docker/nginx/tls/` (kunci privat) di-gitignore +
        di-dockerignore.
      - **Sertifikat**: dibuat otomatis saat start (SAN = `localhost`, `127.0.0.1` + `NGINX_TLS_HOSTS`, RSA 2048,
        365 hari, `CA:FALSE`, EKU serverAuth, kunci mode 600). Dibuat ulang bila daftar host berubah / kunci tak cocok /
        sisa <= 30 hari; selain itu **fingerprint tetap**. Sertifikat operator (subject tanpa penanda) **tidak pernah
        disentuh**. Loop latar belakang memeriksa tiap 24 jam dan `nginx -s reload` -- tanpa ini nginx yang jalan
        > 1 tahun tanpa restart kedaluwarsa diam-diam. IPv6 belum didukung generator.
      - **Config proxy**: `X-Forwarded-For $proxy_add_x_forwarded_for` (WAJIB), `Host $http_host` (bukan `$host`,
        yang membuang port), `proxy_pass` lewat variabel + `resolver 127.0.0.11 valid=10s` (nginx yang menyimpan IP
        `web` saat start = 502 selamanya setelah `web` di-recreate/rollback; terbukti pulih 3 dtk), tanpa HSTS
        (self-signed), TLS 1.2/1.3, `server_tokens off`, upload 20 MB.
      - **Bukti staging** (nginx di 127.0.0.1:18443): e2e 13/13 (login lewat nginx, cookie `Secure`+`HttpOnly`, sesi valid,
        redirect http->https membawa port, sertifikat yang disajikan = berkas, SAN, TLS 1.3, `Server: nginx` tanpa versi,
        pulih setelah `web` di-recreate); **IP klien asli sampai `audit_log`** dari container klien (`172.21.0.10`)
        walau klien mengirim `X-Forwarded-For: 6.6.6.6` + `X-Real-IP: 9.9.9.9`; fingerprint stabil antar recreate.
      - **Test `tests/edge` (44)** container Docker sungguhan (skip tanpa Docker): generator (SAN, izin kunci, idempoten,
        host berubah, hampir kedaluwarsa, sertifikat operator tak tersentuh, pasangan setengah, kunci tertukar, host
        tak valid, wildcard/duplikat), proxy (XFF ditambah bukan ditimpa, header identitas klien ditimpa, port di Host,
        redirect, `web` diganti -> ditemukan lagi, start tanpa `web`, batas upload, healthcheck, konfigurasi efektif),
        loop pembaruan, healthcheck (log tetap kosong; listener internal tak terjangkau dari jaringan), dan kabel compose
        (profil, port, tag tak ikut `CTI_TAG`, tanpa secret aplikasi, mount TLS).
        **Mutation check: 62 mutasi, 0 selamat** (template 16, skrip 21, Dockerfile 4, compose 10, loop 6, healthcheck 5).
        Temuan tentang test sendiri: 413 yang "lolos" di percobaan pertama ternyata datang dari upstream palsu
        (nginx polos, batas 1 MB), bukan dari edge -> upstream palsu dilonggarkan.
      - **Spam log ketemu user + diperbaiki** (2026-09-26): log nginx berisi 2 baris `notice` (`SIGCHLD received` +
        `unknown process N exited`) tiap 15 dtk. Penyebab dibuktikan: healthcheck https -> `wget` busybox memakai proses anak
        `ssl_client` yang yatim, di-reap nginx (PID 1); 1x `wget` manual = persis 2 baris itu. Diperbaiki dengan memindah
        healthcheck ke HTTP polos di listener loopback `127.0.0.1:8081` (bukan dijadikan harian: container akan `starting`
        24 jam dan nginx mati baru ketahuan besoknya). Live: 0 notice dalam 3 menit (tadinya 12).
      - **IP klien eksternal TERBUKTI** (2026-09-26): login user dari laptop lewat `https://172.25.1.77` tercatat di
        `audit_log.ip_address` = IP laptop (`10.251.64.143`), bukan gateway Docker (`172.21.0.1` hanya untuk akses lewat
        tunnel SSH/localhost). Staging kini publish `0.0.0.0:80/443` (setelan `stg.stack.env` user).
      - **Belum**: dipasang di host produksi.
      - **CVE Tracker**: teks kosong "Run newCveThreat.py to populate" (legacy) diganti (satu-satunya teks legacy
        yang tampil di UI). Tab kosong di staging karena `new_cve` **belum pernah sukses** di sana (run terakhir
        berhenti kena batas MITRE); dijalankan manual: **80 CVE / 12 tech / 49 dtk** (11 CRITICAL, 37 HIGH).
      - **Bug ketemu + diperbaiki**: kandidat CVE membawa nama ter-encode URL (`palo%20alto`/`palo+alto`) tetapi peta
        tech->client berkunci nama asli, jadi techstack **multi-kata dibuang diam-diam** (4 dari 33 di staging:
        `palo alto`, `microsoft 365`, `new relic`, `harmony sase`); skrip lama meng-index kedua bentuk dan menyimpan
        nama ter-decode. Sekarang kandidat membawa nama asli (encode hanya untuk URL). Bukti live: run ulang ->
        81 CVE, `microsoft 365` masuk (CRITICAL), warning `no_client_match` 0. Test baru `test_new_cve_multiword_tech`
        (5; NVD + Tenable), 4 mutasi 0 selamat.
      - **Tidak diperbaiki -> `docs/ROADMAP.md` item 3**: jendela pencarian hanya 8 hari (riwayat techstack **baru
        setelah cutover** tak pernah terisi -- riwayat SEBELUM cutover sekarang diatasi migrasi, lihat 10.F di bawah),
        token bucket MITRE tidak menunggu (kandidat > 60/mnt = run berhenti `rate_limited`), `new_cve` tanpa dedup.
      - **Roadmap baru** `docs/ROADMAP.md`: (1) rebranding nama + UI, (2) rebranding email newsletter/CVE,
        (3) tombol "Populate now" (semua / hanya yang baru ditambahkan).
      - **Validasi akhir**: simulasi CI di checkout bersih -- ruff, format (514 file), mypy hijau, **1845 lulus, 2 skip**
        (CI-sim penuh terakhir; sesudahnya +2 test edge healthcheck, 44/44 lulus) (+47 dari 1798: 42 `tests/edge` + 5 `new_cve` multi-kata); eslint + tsc web bersih; image web staging (`next build`) sukses.

- [x] **10.F (sebagian)** Template `.env` prod, panduan operasional prod, migrasi CVE tracker
      (2026-09-30, permintaan user).
      - **`.env.prod.template`** (baru, ke-commit -- beda dari `.env.example` yang dev-oriented): tiap secret
        ditandai `[ ] ROTASI [R#]` merujuk `docs/SECRETS_ROTATION.md`, nilai operasional non-secret sudah diisi
        keputusan yang sudah dikunci (WIB, 20 topik Telegram). `.env.example` dilengkapi field `WORKER__*` yang
        sebelumnya tak terlihat (logbook signer, health sweep interval, dst -- semua sengaja di-comment supaya
        gak menimpa default kode dengan string kosong). Test baru `test_env_prod_template.py` (18): parity ke
        field `Settings` beneran (bukan disalin manual), key level-compose gak nyasar, secret bertanda ROTASI
        tetap kosong, `Settings()` beneran bisa nyala dari file ini. 5 mutasi (isi ke file, bukan ke test) 0 selamat.
      - **`docs/PROD_PREP.md`** (baru): panduan langkah-demi-langkah 4 item yang cuma bisa dijalankan MANUAL di
        host produksi (backup Mongo + drill restore, snapshot Rundeck, latihan rollback ke stack lama dengan
        stopwatch, timer backup Postgres + salinan off-host rsync/rclone) -- ditautkan dari `CUTOVER_RUNBOOK.md`.
      - **KESALAHAN sesi ini**: nyari IP Mongo non-secret di `legacy/config.yml` pakai `cat`+`sed` dengan regex
        redaksi yang cuma nutup `password|pwd|pass|user|uri` -- `token`/`secret` TIDAK ikut, jadi **token Devo**
        (sudah tercatat rotasi #10) DAN **token GitHub** (belum pernah tercatat sama sekali) tercetak polos ke
        transkrip. User diberi tahu segera (tanpa mengulang nilai). Token GitHub ditambahkan sebagai item #13 di
        `SECRETS_ROTATION.md`; checklist naik prioritas buat dua-duanya. Memori diperbarui
        ([[never-echo-secrets-in-shell-checks]]): regex redaksi manual gak bisa dipercaya, harus baca daftar KEY
        dulu sebelum mengizinkan diri mencetak value apa pun dari file config asing.
      - **`tools/seed/fase10_cve_migrate.py`** (baru): migrasi `cve_tracker`/`cve_false_positives`/`cve_tickets`
        dari dump Mongo lama (`legacy/dump/news_db/`) -- BUKAN pembalikan keputusan "mulai dari DB kosong" (itu
        buat 38 collection yang besar/beda skema; CVE beda kasus: dump kecil, field map hampir 1:1). Field lama
        (`reference`/`affected` dict, `cisa_kev_*` rata, timestamp naive) dipetakan ke skema baru; `affected`
        di-flatten ke format string SAMA dengan yang di-generate `_new_cve.py`. Idempoten (`ON CONFLICT DO
        NOTHING` per `(cve_id, client_id)` di ketiga tabel) -- CVE yang sudah ada (mis. `new_cve` sudah jalan)
        TIDAK ditimpa. Timestamp naive diasumsikan WIB (konsisten `WORKER__REPORT_UTC_OFFSET_HOURS=7`).
      - **Bug data ketemu (bukan bug kode)**: 11 dari 505 dokumen tiket lama punya pasangan (cve_id, client_id)
        DUPLIKAT -- dump lama gak punya unique index seperti skema baru; analis yang sama acknowledge dua kali
        beda menit. Diputuskan: simpan yang `acknowledge_time`-nya PALING BARU, bukan yang pertama ketemu di
        file (urutan dump = urutan insersi Mongo, BUKAN urutan waktu -- terbukti kebalik untuk beberapa pasangan).
      - **Regresi terhadap dump asli** (`legacy/dump`, guard `skipif` kalau dump tak ada): 575 CVE + 20 FP +
        494 tiket (setelah dedup 11 pasangan) bermigrasi tanpa error; `microsoft 365` (multi-kata) tersimpan
        dengan nama asli. Test 17 (`tests/integration/test_cve_migrate.py`), 11 mutasi 0 selamat. Ditambahkan
        sebagai langkah 8 di `CUTOVER_RUNBOOK.md` (opsional tapi disarankan, sebelum nyalakan beat).
      - **Menunggu user**: nama lengkap yang ada di dump (`dyah.palupi`, `Michael`, `michael.dragon`) dianggap
        aman dimigrasi apa adanya (nama analis internal, bukan PII pelanggan) -- user belum eksplisit
        mengonfirmasi ini, cek sebelum jalan di produksi kalau ada keberatan.
      - **Validasi akhir (2026-09-30)**: simulasi CI penuh di checkout bersih (rsync `git ls-files`, `--with
        pymongo`) -- ruff, format (518 file), mypy hijau, **1868 lulus, 4 gagal**. Ke-4 gagal PRA-ADA, tidak
        disentuh sesi ini: `test_articles_router_snapshot`/`test_newsletter_router_snapshot` (4 test) nge-assert
        `datetime.now()` ISO-week terhadap snapshot yang di-hardcode "week 39" -- minggu kalender berganti ke 40
        di tengah sesi ini (tanggal sistem maju dari 2026-09-26 ke 2026-09-30), snapshot-nya belum di-refresh.
        Bukan regresi dari perubahan Fase 10.F/10.G2 -- akan gagal lagi di minggu berikutnya kalau tidak
        diperbaiki (saran: freeze waktu di test, jangan hardcode nomor minggu). Test template `.env` prod
        sempat gagal di checkout tanpa `.git` (`git check-ignore` fatal error, bukan exit 1) -- diperbaiki,
        sekarang cocokkan pola `.gitignore` langsung tanpa shell ke git.

- [x] **10.F (lanjutan)** `monitor_x` pacing, rotasi secret didelegasikan, `gitleaks` + hook
      pre-commit (2026-09-30, sambungan permintaan user hari yang sama).
      - **`monitor_x` pacing** -- lihat detail lengkap di TEMUAN 3 (10.G rehearsal). Ringkas: `rate_limit`
        disamakan `"10/minute"` ke 4 scraper Twitter yang berbagi domain (tadinya `monitor_x` beda sendiri
        "15/minute", melanggar invarian `ratelimit.py`), jeda proaktif antar akun (`window_s/capacity`, 6
        dtk), `_get_with_backoff` sekarang menangkap `RateLimited` (budget lokal habis) selain `TransientFetchError`
        429 (server), nunggu jendela reset yang benar (60 dtk, bukan 6 dtk punya 429). 6 test (dari 3), 8
        mutasi 0 selamat. **Belum dibuktikan live/staging.**
      - **Rotasi 13 secret legacy**: user memutuskan **didelegasikan ke tim ops-nya**, dieksekusi di luar
        sesi/repo ini -- `docs/SECRETS_ROTATION.md` checklist diupdate merekam KEPUTUSAN delegasi ini
        (bukan verifikasi teknis bahwa token sudah mati).
      - **`gitleaks` + hook pre-commit -- INI diverifikasi teknis beneran** (beda dari rotasi di atas):
        `brew install gitleaks` (8.30.1) + `brew install pre-commit` (4.6.2). `gitleaks detect` atas
        seluruh history git (61 commit, 6,33 MB) -> **0 temuan**. Scan working tree penuh (`--no-git`,
        226 MB) -> 47 temuan, SEMUANYA di 8 file yang sudah dikonfirmasi `git check-ignore` + belum
        ter-track (`.env`, `legacy/config.yml`, `legacy/dump/**/*.bson`, `docs/legacy/rundeck-get-schedule.sh`,
        cache `graphify-out/`, `__pycache__/*.pyc`) -- nol yang akan ke-commit. Dibuktikan presisi:
        scan ulang HANYA himpunan file yang benar-benar akan ikut commit (`git ls-files -co
        --exclude-standard`, pola sama dengan CI-sim sesi ini) -> **1.168 file, 0 temuan**.
        `.pre-commit-config.yaml` baru (gitleaks `v8.30.1`, sinkron versi CLI) + `pre-commit install`.
        **Diuji langsung, bukan cuma dipasang**: commit dummy berisi pola AWS access key DITOLAK
        (`exit code 1`), file uji dibersihkan tanpa nyangkut commit. CI (`.github/workflows/ci.yml` job
        `secrets`, `gitleaks-action@v2`, `fetch-depth: 0`) sudah lebih dulu ada dari sesi sebelumnya --
        sekarang lapisan lokal (pre-commit) dan lapisan CI dua-duanya aktif.

- [x] **Alat bantu: probe kepatuhan-JSON model LLM** (2026-09-26, permintaan
      user) -- `tools/llm/probe_json.py`. Nge-tes model di gateway (9router)
      SATU per SATU pakai panggilan yang SAMA dgn produksi (prompt/parameter
      diimpor dari `classify.py`/`extract_ttps.py`, parser = `parse_json_
      response`, `max_retries=0`): 4 input tetap (judul cyber, non-cyber,
      judul berisi kata "JSON", ringkasan TTP) x `--runs`. Kategori gagal
      dibedain: `PERSONA` (prosa/penolakan ala "Kiro"), `TERPOTONG`
      (`finish=length`), `KOSONG`, `BUKAN-JSON`, `SCHEMA` (mis. `"false"`
      string -> `bool("false")` True di produksi = salah diam-diam), `http_NNN`
      (mis. 400 kalau `response_format` ditolak), `TIMEOUT`. Hasil: verdict
      PASS/USABLE/FAIL + perkiraan peluang gagal setelah 3x percobaan produksi
      `(1-p)^3` + model yang BENERAN njawab (`served_by`, ketahuan kalau combo
      nge-route ke backend lain). `tests/unit/test_llm_probe.py` (15 test,
      server OpenAI palsu tiap mode gagal). `pyproject.toml` +`pythonpath=["."]`
      biar test bisa `import tools.*`. Temuan: dari `--list` 9router dev, awalan
      **`kr/` = provider Kiro** (9 model claude/glm/qwen/MiniMax/deepseek);
      persona "Kiro" kemungkinan besar datang dari `kr/*` yang kepilih lewat
      `my-combo` -- probe `--model my-combo` nunjukkin backend mana lewat
      `served_by`. Dijalanin USER (bukan gua, hemat kuota), hasil 2026-09-26:
      `kr/claude-sonnet-4.5` 20/20 PASS (median ~4.7s), `cf/@cf/meta/llama-3.3-
      70b-instruct-fp8-fast` 20/20 PASS (~4.4s), **`my-combo` 100/100 PASS**
      (median 2.3-4.6s, batas atas laju gagal 95% ~3%), SEMUA 100 panggilan
      di-serve `claude-haiku-4.5`. Artinya: kondisi sehat sekarang bersih;
      persona "Kiro" (Fase 7.3) kemungkinan state sementara / anggota
      fallback combo yang belum kepilih -- `served_by` cuma 1 model, jadi
      JALUR FALLBACK combo BELUM teruji. Belum dicek: komposisi combo di
      dashboard 9router + probe tiap anggotanya; akurasi klasifikasi (probe
      ini cuma ngukur kepatuhan format).
      **KOREKSI (10.A2, 2026-09-26)**: kesimpulan "persona Kiro kemungkinan
      state sementara" di atas SALAH. Persona itu nyata, bergantung isi judul
      dan gak deterministik -- 4 input generik probe awal gak memicunya. Probe
      sekarang punya 2 judul pemicu bawaan; `my-combo` -> `claude-haiku-4.5`
      di gateway staging: 0/8 dan 7/8 dgn bentuk polos, 48/48 dgn `--hardened`.
      Lihat 10.A2.

Yang cuma bisa dikerjain user (butuh akses prod): rotasi secret di
sistem asal (BotFather/Graylog/Mongo/Devo/Rundeck), `mongodump` final,
matiin Rundeck + systemd lama, provisioning VM, narik `techstackLibrary`.

### 10.H QA UI staging + fix (2026-10-01) `[x]` ke-merge DAN ke-deploy ke staging (sisa terbuka di bawah)

Dikerjakan di DUA sesi terpisah setelah commit Fase 10 (`a92e7ea`), keduanya sudah di `origin/main`.
Checkout lokal utama masih di `a92e7ea` -- `git pull` dulu sebelum lanjut apa pun.

**Sumber temuan:** QA manual lewat browser ke staging, 4 laporan (A Core+Admin 52 TC, B News+X Intel
54 TC, C CVE+Intel 71 TC, D Scrapers+Analisis 38 TC = 215 TC, ~75 entri bug; beberapa kembar antar
laporan, mis. TTP muncul di A/B/C dan threat actor di B/D). Laporan HTML + screenshot ada di
`qa-report/` pada worktree `halo-bro-02ad66` dan **TIDAK ke-commit** -- salin dulu kalau masih dibutuhkan,
sebelum worktree itu diarsipkan/dihapus.

| PR / commit | Area | Bug QA |
|---|---|---|
| PR #1 `0e5f4c0` | Scheduler: heartbeat `CtiScheduler`->Redis (`cti:beat:heartbeat`), watchdog di proses worker (alert Telegram thread `scraper_health` + "PULIH"), `next_run_at` per scraper + banner di `/scrapers`, catch-up basi dilompati (>600 dtk), retry 60/120/240 dtk | D2, D6, D7, D8 |
| PR #1 `8f4a411` | Seed `threat_actor_groups` pindah ke `fase10_reference_data.py`; `mentioned` berisi semua negara; nama grup di-escape (`re.error` utk `noname057(16)`); `python -m cti_enrich.backfill` | B2, D1, D4 |
| PR #1 `fa0767b` | Dialog edit admin selalu terisi; `ClientUpdate.countries` opsional (gak dikirim = gak berubah) | A BUG-01/02 |
| PR #1 `db662c9` | Filter negara cocok ke role apa pun; reset page; tiebreaker `id` paging; X Intel tanggal "To" inklusif + strip `@` | B1, B3-B6, C02 |
| PR #1 `c62d229` | TTP dinormalisasi ke katalog ATT&CK; migrasi `c3a7e9d1f2b4` (`article_ttps.extracted_id/name`, tabel `attack_technique_aliases`) | C01, A BUG-04, B8, C17, C18 |
| PR #2 `333dce9` | `test_get_actor_timeline`: `_today()` di `ta.py` di-monkeypatch, gak ikut tanggal lagi | -- |

**Selaras dengan Fase 10 (dicek 2026-10-01, bukan asumsi):** `CtiScheduler` dipasang lewat
`app.conf.beat_scheduler`, jadi `beat_main.py` (lock singleton 10.1d) otomatis memakainya; migrasi
`c3a7e9d1f2b4` bersambung di atas head Fase 10 (`down_revision = a10e5c0de002`), tetap satu head;
watchdog dedupe lewat `SET NX` di Redis (3 container worker gak kirim alert 3x). QA BUG-22 (IP audit
log = gateway docker) itu efek SSH tunnel, bukan regresi -- bukti 10.G2 dari laptop langsung tetap berlaku.

**KOREKSI klaim Fase 10 sebelumnya:**
1. `threat_actor_groups` "kelar Fase 5" -- cuma di kode, lihat koreksi di 10.1.
2. "Health sweep terbukti deteksi scraper mati" (checklist cutover) benar hanya buat SCRAPER mati.
   Beat mati ~97,6 jam (26 Sep 15:42 -> 30 Sep 17:17 UTC, di-stop manual habis rehearsal 10.G,
   `restart: unless-stopped` gak menyalakannya lagi) gak ketahuan sama sekali karena digest health
   DIJADWALKAN beat itu sendiri. Watchdog PR #1 menutup lubang ini -- tapi belum ke-deploy.
3. Keluhan "scraper stg gak jalan otomatis" valid buat periode itu. Dicek langsung 2026-10-01 ~07:40
   UTC: container `beat` Up 14 jam, 1837 run dalam 24 jam terakhir SEMUANYA `trigger=beat` (terakhir
   07:38 UTC), nol `manual`.
4. CI-sim "4 gagal pra-ada" (snapshot ikut tanggal) sudah gak relevan: yang terakhir
   (`test_get_actor_timeline`) dibekukan PR #2. Angka: merge PR #1 = 1939 lulus / 3 skip / 1 gagal
   (yang gagal itu tadi); PR #2 di basis `a92e7ea` = 1891 lulus / 3 skip. **Suite penuh di `main`
   gabungan (#1 + #2) BELUM dijalankan ulang.**

**Status deploy staging -- DI-DEPLOY 2026-10-01 ~08:30-08:40 UTC (atas permintaan user, dijalankan
manual per tahap, bukan lewat draf `stg_postdeploy.sh`):** sebelum deploy, DB `a10e5c0de002`, image
`:stg` berumur 4 hari, dan kode di `~/cti-platform-stg` ternyata SUDAH identik dgn `HEAD` (rsync
`--checksum` dry-run: cuma 2 dokumen yang beda -- sync kode sudah dilakukan sebelumnya).
`~/cti-platform-stg` itu file-sync, BUKAN git checkout (langkah "tarik main" di runbook gak berlaku).
Urutan yang dijalankan:
1. Backup Postgres (`pg_backup.py`, 7,1 MB) -> `~/backups/cti-stg/cti-20261001T083207Z.dump`; backup
   kedua tepat sebelum remap TTP (`...T083840Z.dump`). `verify` sengaja gak dijalankan (DROP DB scratch
   rawan diblok classifier mass-delete).
2. Tag image lama `:prev` (api/worker/worker-nlp/web) buat rollback -- `:prev` lama (Sep) sudah gak ada.
3. Build `stg_build.sh` (4 image, ~2,5 menit, semua exit 0); dicek image berisi `beat_watchdog`,
   `scheduler`, `attack_ttp`, `backfill`, dan migrasi `c3a7e9d1f2b4`. Disk 34 GB -> 25 GB bebas (83%).
4. `up -d`: migrasi `a10e5c0de002 -> c3a7e9d1f2b4` jalan, 9 container healthy.
5. Seed `fase10_reference_data.py`: dry-run lalu sungguhan -- `threat_actor_groups` +3993 (total
   3995), `monitored_people` +30, `ioc_allowlist_entries` +9, tabel lain 0 baru (idempoten). **Dump
   subset staging gak punya `groups.bson`/`apac-people.bson`/`ioc_allowlist.bson`** -- ketiganya dicopy
   dari dump penuh `~/backups/mongo-cti/20260930T120307Z` ke `legacy/dump/` (BUKAN `users.bson`).
6. Backfill (`cti_enrich.backfill`): 334 artikel, +28 baris TA di 26 artikel, +94 negara `mentioned`
   di 65 artikel.
7. Sync ATT&CK dijalankan server-side lewat `AsyncAttackSyncRepo.sync_all_domains()` (repo yang sama dgn
   tombol Sync di UI, TANPA baris audit log `attack_sync` karena gak lewat route API): enterprise 709
   teknik, katalog total 943 teknik / 193 revoked.
8. `remap_article_ttps`: dry-run lalu sungguhan -- 171 artikel berubah, `article_ttps` 781 -> 699 baris;
   teks asli LLM tersimpan di `extracted_id`/`extracted_name` (699/699 baris terisi).
9. Restart `api`.

**Hasil verifikasi (SESUDAH deploy, 08:39-08:40 UTC):** heartbeat beat segar (`age_s` 3, `state=ok`),
96 scraper semuanya punya `next_run_at`, 37 run dalam 15 menit semuanya `trigger=beat`; watchdog
`beat_watchdog_started` di 3 container worker; log 15 menit tanpa ERROR/Traceback; PIR options 13
threat actor (tadinya 0); Risk Matrix 18 sel (tadinya 0, sama utk period 30 & 90); MITRE heatmap 13
baris x 20 TTP. Health scraper: 63 ok / 27 degraded / 5 zero_yield / 1 stale -- yang `degraded`
didominasi kelompok XPath lama dari census 10.D (abnormalsecurity, aquasec, blackberry, cis, cloudflare,
cymru, ...), bukan efek deploy ini.

`remap_article_ttps` cuma perlu buat DB yang SUDAH punya artikel lama (staging); DB hasil cutover
bersih seharusnya gak butuh karena `persist` sudah menormalisasi artikel baru -- ini kesimpulan dari
diff, belum dibuktikan. Draf `qa-report/stg_postdeploy.sh` TIDAK dipakai (masih belum dijalankan, belum
ke-commit, dan sudah usang karena sync-nya sudah dilakukan).

**Runbook:** `docs/CUTOVER_RUNBOOK.md` sudah di-update di PR #1 (langkah 6 sekarang ngisi
`threat_actor_groups`, bagian 3.2a backfill, catatan hypercare soal beat yang gak nyala sendiri +
catch-up). Dokumen ini (`PROGRESS.md`) sebelumnya TIDAK ikut di-update -- ini catatannya.

**Belum ditangani / terbuka:**
- ~~`monitor_x`: twitterapi.io balikin HTTP 402 "Credits is not enough"~~ -- **kelar 2026-10-01**
  (lihat 10.I): kunci diganti user, 402 terverifikasi hilang, dan 401/402/403 sekarang gagal keras
  (`ParseError`) alih-alih run `empty` tanpa pesan.
- Newsletter tersimpan dobel (A BUG-06): tombol sudah di-disable saat pending di frontend, dugaan gap
  idempotency di backend `/api/newsletter/draft-email`.
- Early Warning default 30 hari gak nangkep spike besar (D5); sisa bug Medium/Low di laporan QA
  (mis. B12 HTML entity di judul, B14 judul berupa nama file dari watcher GitHub + `posted_on` kosong,
  C22 data uji `testactor`/`testing` di whitelist TA).
- **Keputusan reviewer MITRE belum dikonfirmasi user:** entri TTP bernama taktik dibuang (T1547
  "Persistence" hilang); kalau ID dan nama bentrok, NAMA yang dipakai (T1518.001 "System Service
  Discovery" jadi T1007).
- **Kualitas remap TTP -- ada hasil janggal di dry-run/apply staging 2026-10-01** (dinilai dari contoh
  yang tercetak, BUKAN audit penuh 171 artikel): nama karangan LLM + ID valid diganti nama kanonik ID
  itu, jadi maknanya bisa ngaco -- `T1593.003 'Prompt Injection'` -> `'Code Repositories'`,
  `T1598.003 'Prompt Injection'` -> `'Spearphishing Link'`; nama yang cocok teknik domain LAIN menang
  -- `T1059.001 'Code Injection'` -> `T1631.001 'Ptrace System Calls'` (teknik Mobile, di artikel soal
  ekstensi browser). Sisi bagusnya: duplikat ID/nama (mis. `T1548` x3, `T1110` "Credential Dumping")
  terkoreksi. Teks asli ada di `extracted_id`/`extracted_name`, jadi aturan bisa diubah dan dijalankan
  ulang tanpa kehilangan input LLM-nya. Perlu keputusan user: terima apa adanya, atau perketat aturan
  (mis. buang entri yang namanya gak ada di katalog alih-alih relabel).
- Rotasi password `stg-admin` (dan sisa kredensial dev dari Fase 9) -- wajib sebelum host ini dianggap
  prod.

### 10.I Census scraper: perbaikan + waiver (2026-10-01) `[~]` kode + deploy stg beres + siklus semalam terukur; sisa: kredit twitterapi.io

Pemicu: census staging 10.D (30 dari 92 scraper non-ok di census pertama; 18 di antaranya XPath absolut
yang lapuk SEMUA sekaligus). Dikerjakan setelah user ganti kunci twitterapi.io. Tabel akar masalah per
scraper (terverifikasi, bukan tebakan) ada di `docs/KNOWN_BROKEN.md` bagian "Update 2026-10-01".

**Hasil (39 baris di tabel itu):** 27 diperbaiki/pulih (termasuk `doyensec`/`trustwave` dari putaran
sebelumnya dan 3 scraper Twitter yang cuma butuh kredit), 5 di-**WAIVER** (`enabled=False` + paragraf
WAIVER di docstring: `blackberry`, `koisec`, `google`, `cisa`, `nquiring_minds`), 2 `empty` ternyata sah
(`mitre_github`, `techstack_pypi`), 5 flaky sesekali dibiarkan ke retry backoff beat (`asec_ahn`, `bizone`,
`exploitdb`, `resecurity`, `techstack_npm`).

**Pola perbaikan:**
1. **9 scraper XPath -> `RSSScraper`** (situs ternyata punya feed resmi, ketemu probe path umum):
   `aquasec`, `groupib`, `huntress`, `landth` (domain jadi `depi.security`), `sysdig` (feed berisi host
   `webflow.sysdig.com`, ditulis ulang lewat `xml_fixups`), `cymru`, `cloudflare`, `intel471`, `k7security`.
2. **8 scraper tanpa RSS -> `link_card_xpaths`** (`feeds/_links.py`: dipegang POLA HREF artikel + panjang teks
   link, bukan posisi div ke-N): `abnormalsecurity`, `huntio`, `prodraft`, `sans`, `splunk`, `proofpoint`,
   `cis`, `dragos`.
3. **Filter kategori basi**: `sentinel` (10/10 item terbuang, kategori lama gak ada) dan `crowdstrike`
   (kategori diganti nama situsnya; kesimpulan Fase 0.5 "filter sah" ternyata BASI).
4. **Pacing**: `github_poc_monitor` (~100 request/run vs budget 30/menit, 76 run 0 sukses) dan `new_cve`
   (22 dari 44 run mati `rate_limited`) sekarang MENUNGGU jendela reset (`feeds/_pacing.py::get_waiting`,
   maks 5x) alih-alih langsung gagal. Override DB 10/menit di staging dihapus lewat
   `POST /api/scraper/{id}/reset-config` (ter-audit).
5. **`monitor_x`**: HTTP 401/402/403 dari twitterapi.io sekarang `ParseError` (loud); dulu `break` per akun
   dan run tercatat `empty` tanpa jejak -- itulah kenapa kredit habis gak ketahuan.
6. **Health sweep**: scraper yang di-waive di KODE (`meta.enabled=False`) tetap dihitung `degraded` lalu
   `dead` selamanya (health cuma baca baris config DB). Sekarang aturannya sama dengan beat: config menang,
   kalau gak ada baris config baru `meta.enabled`. Tanpa ini 5 waiver akan nyepam digest Telegram.
   Di-deploy ke staging 2026-10-01 ~12:50 UTC (api/worker/worker-nlp di-rebuild); sesudahnya 5 waiver
   tampil `disabled` di sweep.

**Bukti live dari staging (setelah deploy):** `dry-run` status `ok` untuk 18 scraper yang diperbaiki
(aquasec 10, groupib 10, huntress 10, landth 19, sysdig 10, cymru 50, cloudflare 20, k7security 10,
abnormalsecurity 6, huntio 6, prodraft 6, sans 6, splunk 6, proofpoint 4, cis 6, dragos 6, sentinel 10,
crowdstrike 3). Run manual: `new_cve` ok (33 item, 102 dtk); `github_poc_monitor` ok (666 dtk -- 10 kali
menunggu jendela ~70 dtk, lalu selesai tanpa gagal; 6 item, 2 baru). Beat sudah menembak ulang sebagian
scraper dengan kode baru: `cis`, `crowdstrike`, `huntress`, `sans`, `sentinel`, `sysdig` semuanya `ok`. `monitor_x` (beat 12:38 UTC, kunci baru) `ok` 385 dtk / 30 item -- sebelumnya `empty` ~108 dtk tanpa pesan
karena kredit habis; `tweet_alerts_30m` dan `trending_cve` juga `ok`.
Sisanya belum kebagian slot cron sejak deploy -- run terakhir mereka masih `parse_error` LAMA.

**Test:** 5 file baru (`test_census_rss_conversions`, `test_census_link_card_scrapers`, `test_request_pacing`,
`test_monitor_x_account_wide_errors`, `test_census_category_filters`) + `test_health_code_disabled`; mutation
check tiap perbaikan, 0 selamat. `ruff` + `mypy --strict` bersih. Unit+contract+package: 1254 lulus.

**Yang BELUM terbukti / catatan jujur:**
- **`intel471` belum stabil:** Vercel membalas 429 setelah beberapa request berturut-turut dari dua IP
  berbeda (dry-run staging: `fetch_error` HTTP 429). Proteksinya TIDAK dicoba dilewatin. Kalau 429 menetap
  di polling per jam, jadi kandidat waiver.
- **Health sweep SESUDAH semalam penuh (diukur 2026-10-02 05:27 UTC, beat Up 17 jam):** `ok` 85,
  `disabled` 5 (waiver), `zero_yield` 2, `degraded` 4. Semua scraper hasil perbaikan `ok` di run terakhir
  -- termasuk `intel471` (12 dari 12 run `ok` dalam 12 jam; 429 Vercel yang tadinya dikhawatirkan tidak
  muncul dari egress staging, tapi itu belum jaminan di produksi). 12 jam terakhir: 1052 run `ok`, 24
  `empty`, 17 `fetch_error` (flaky yang memang dipantau: `techstack_npm` 6, `resecurity` 6, `exploitdb` 3,
  `proofpoint` 1, `techstack_go` 1), 120 `parse_error` -- SEMUANYA Twitter, lihat poin berikutnya.
  `zero_yield` 2 = `mitre_github` + `techstack_pypi`, keduanya `empty` yang SAH (tabel KNOWN_BROKEN) tapi
  akan terus tampil di digest; belum diputuskan mau dibiarkan atau di-mute.
- **KREDIT twitterapi.io HABIS LAGI** (kunci baru mulai ~12:00 UTC 1 Okt; `monitor_x` run `ok` terakhir
  14:38, 402 mulai 14:53 -> ~3 jam). Sejak itu 120 run gagal KERAS (`monitor_x` 48, `trending_cve` 48,
  `tweet_alerts_30m` 12, `tweet_alerts_1h` 12) dengan pesan `HTTP 402` -- ini perubahan 10.I bekerja
  (dulu `empty` diam-diam), dan 4 scraper itu tampil `degraded` di digest. BUKAN bug kode: empat scraper
  berbagi satu kunci/saldo dan `monitor_x` saja menarik 18-30 tweet per 15 menit.
- **Frekuensi diturunkan (keputusan user 2026-10-02)** -- akar masalahnya ketemu: Rundeck asli menjalankan
  `monitorX` tiap **3 jam** (`0/3`), tapi default platform (Fase 5) `*/15` = 12x lebih sering. Tiga scraper
  Twitter lain sudah sama dgn legacy (`trending_cve` 15 mnt, `tweet_alerts_1h`/`30m` per jam; dicek via
  `expected_interval`). Default KODE `monitor_x` diganti `8 */3 * * *` (menit 8 = offset lama, gak numpuk
  dgn scraper Twitter lain di bucket `10/minute`); tes baru `test_twitter_schedules_match_legacy` mengunci
  cadence ke-4 scraper ke angka legacy (6 mutasi, 0 selamat). Di-deploy ke staging 2026-10-02 ~05:36 UTC;
  `GET /api/scraper` menunjukkan `schedule=8 */3 * * *`, `next_run_at=06:08`. Tidak ada override jadwal di
  DB (cuma `max_items=50` di `monitor_x` dan `100` di `new_cve` -- sisa override manual, belum diaudit).
  **Saldo twitterapi.io tetap 0 sampai di-top up**: ini cuma mengurangi laju pemakaian berikutnya, tidak
  memulihkan 4 scraper yang `degraded`.
- **Scope artikel BERUBAH** untuk beberapa scraper (jumlah vs legacy sengaja beda): lihat
  `docs/PARALLEL_RUN_COMPARISON.md` §1 -- jangan dihitung sebagai gap.
- Waiver `cisa`: `all.xml` dibalas 403 WAF Akamai 19/19 run (BUKAN flaky -- dugaan lama salah); KEV tetap
  masuk lewat `cisa_kev`.

### 10.J Deploy dari nol (2026-10-02) `[x]` skrip + README + latihan clean-room lokal; belum di host sungguhan

Pemicu: user mau tahu apakah host baru "tinggal isi key". Jawaban awal: belum -- ada empat celah di jalur
fresh deploy (lihat bawah). Semuanya ditutup dan dilatih dari salinan bersih repo di Docker lokal.

**Celah yang ditemukan lewat pembacaan kode (bukan asumsi):**
1. Admin pertama tidak ada di runbook; adanya `POST /api/auth/init` (terbuka selama belum ada user).
2. Sinkron ATT&CK tidak ada di runbook (task periodik mengisinya sendiri, tapi telat).
3. Seed `threat_actor_groups`/`monitored_people`/`ioc_allowlist_entries` membaca `legacy/dump/` (gitignored) --
   host tanpa Mongo lama menjalankan platform dengan TA kosong. Tiga file `.bson` kecil (370 KB, data umum:
   nama threat actor dari malpedia/ORKL/MITRE dll, demonym, 9 baris allowlist) kini dibundel di
   `tools/seed/reference/`.
4. Tidak ada README dan tidak ada satu perintah deploy.

**Yang ditambahkan:** `tools/ops/fresh_deploy.sh` + `Makefile` (`make fresh-deploy`, `make fresh-status`),
`README.md`, `tools/seed/reference/`, bagian 3.0 + baris di "Yang BELUM terbukti" pada `CUTOVER_RUNBOOK.md`.
Skrip: cek prasyarat (placeholder `GANTI_INI`, password Postgres konsisten antara `.env` dan `stack.env`, bukan
default `cti`) -> membangkitkan `AUTH__JWT_SECRET`/`AUTH__SESSION_SECRET_KEY` bila kosong -> build ->
`check_secrets` -> postgres/redis/migrasi/api -> seed referensi -> admin (password acak ke
`secrets/admin_password`, mode 600, tidak dicetak; body 422 tidak dicetak karena memuat input) -> ATT&CK ->
worker -> beat TERAKHIR -> web + nginx. Idempoten, tidak pernah menghapus volume.

**Dua keputusan teknis yang dibuktikan, bukan ditebak:** langkah cek-secret dan seed memakai
`docker compose run` bukan `docker run --env-file`, karena yang terakhir tidak membuang komentar inline di
`.env` (template punya baris `KEY=nilai   # komentar`).

**Latihan (2026-10-02, Docker lokal arm64, 4 GB RAM, concurrency 1, secret dummy):** run 1 dari nol: build
sukses, `check_secrets` gagal karena key dummy (LLM `ConnectError`, Telegram 404) dengan pesan yang benar.
Run 2 `--skip-build --skip-secret-check`: 9 container healthy; DB `users 1` (admin/superadmin), `roles 3`,
`clients 1`, `threat_actor_groups 3991`, `attack_techniques 943` (sama dengan staging), tepat satu `beat_leader`,
0 traceback; login lewat nginx `200`, password salah `401`. Run 3 (ulang): seed `0 baru`, admin tidak dibuat
ulang, hash password tidak berubah. Empat jalur gagal prasyarat dites. Stack latihan dibongkar (hanya project
`ctirehearsal`).

**Tambahan 2026-10-02 -- `--restore-from <dump>` / `--replace-db`** (deploy memakai DB dari backup
`pg_backup.py`, mis. staging): restore di langkah 3, sesudah postgres+redis dan SEBELUM api (migrasi menaikkan dump
berrevisi lama). Hanya di DB KOSONG; `--replace-db` menimpa (destruktif, menghentikan semua service dulu, minta
ketikan `timpa` kalau interaktif). Admin baru tidak dibuat, login pakai user dari backup (username dicetak).
Dilatih di Docker lokal, 7 skenario: (T1) berkas tidak ada -> berhenti di prasyarat; (T2) dump rusak -> `checksum
TIDAK cocok`, DB tetap kosong; (T3) restore normal -> baris penanda unik ikut pulih, login dengan password LAMA 200,
seed `0 baru / 3991 sudah ada`, hash file password tidak berubah; (T4) restore ulang ke DB berisi -> DITOLAK, data
utuh; (T5) `--replace-db` -> penanda sesudah-restore hilang (ditimpa), penanda dump kembali, stack naik lagi; (T6) dump
revisi lama (`a10e5c0de002`, dibuat lewat `alembic downgrade`) -> otomatis naik ke `c3a7e9d1f2b4`, kolom baru ada,
login 200; (T7) dump berrevisi tak dikenal -> migrasi gagal dengan pesan penjelasan + log migrate.
**Dua temuan dari latihan itu, sudah diperbaiki:** `pg_backup.py` memakai `datetime.UTC` (python >= 3.11) sehingga
GAGAL di python3 host yang lebih tua (python3 Mac 3.9; Ubuntu 22.04 punya 3.10) -> diganti `datetime.timezone.utc`,
4 tool host (`pg_backup`, `notify_telegram`, `rundeck_schedule`, `rollback`) dites `--help` di 3.9, skrip deploy kini
mensyaratkan python3 >= 3.9; dan peringatan palsu "beat_leader = 2" pada rerun (log beat menumpuk lintas restart)
-> dihitung sejak start terakhir.

**Alert GitHub PoC + visibilitas thread Telegram (2026-10-02):** audit alert legacy vs baru (100 job aktif Rundeck)
menemukan SATU gap nyata: `githubPOCMonitor` mengirim `send_alert_poc` ke thread `github_exploit`, platform baru
tidak mengirim apa pun (scraper hanya menulis `cve_tracker.pocs`). Sekarang `github_poc_monitor` menyertakan
`NoticeItem` topik **`github_poc`** (topik ke-21 di `TELEGRAM__THREAD_IDS`, ditambahkan ke `.env.example` dan
`.env.prod.template`) untuk repo baru dari pencarian broad -- fase targeted tetap hanya menyimpan, sama seperti
legacy. Beda dari legacy, sengaja: sekali per repo (alert "UPDATED" per SHA dihapus), hanya repo <= 3 hari (tanpa
ini deploy ke DB yang sudah berisi membanjiri channel dengan PoC lama; di DB kosong cold-start cap 5 tetap
berlaku karena `NoticeItem` kena cap), semua teks luar di-`html.escape`, field panjang dipotong. 15 test, 15
mutasi 0 selamat. Dua beda perilaku lain yang ditemukan audit TIDAK diubah: `blackorbird`/`unit42_github` (legacy
kirim langsung ke thread report; sekarang `ArticleItem` lewat NLP, topik mengikuti klasifikasi) -- belum dicek
dengan data nyata. **Topik `feed_twitter` (2026-10-02, permintaan user -- topik ke-22):** tweet "umum" (yang tidak masuk kategori
khusus) dulu dibagi ke `global`/`apac`/`apac_indo`/`apt`, thread yang DIBAGI dengan alert artikel; sekarang
semuanya ke `feed_twitter` (`tweet_routing.FEED_TOPIC`). Kategori khusus (`zero_day`, `data_breach*`,
`vendor_report`, `ot`, `tech_stack`, `tech_stack_unrelated`) TIDAK berubah, termasuk aturan "dua topik" (`ot` +
umum). Field `news_type`/`mentioned_group` di `TweetRoutingInput` dan `_generic_topic` dihapus (tak lagi
mempengaruhi topik; riwayat git bila mau kembali). 7 test scraper + 19 test routing diperbarui, 11 mutasi 0
selamat. **Efek samping:** kunci dedup notice tweet berubah `<id>:global` -> `<id>:feed_twitter`, jadi tweet yang
masih di jendela pencarian saat deploy pertama bisa terkirim ulang sekali. `monitor_x` (X Intel) tetap TIDAK
mengirim Telegram (legacy juga tidak). Semua topik mendarat di satu thread kalau `thread_id`-nya 0 -- itu
konfigurasi, bukan bug. `check_secrets.py` kini punya cek
offline `telegram_threads` (NOTE bila semua 0 / sebagian 0 / berbagi id; tidak menggagalkan exit code), 6 test, 7
mutasi 0 selamat. `test_alert_topics` kini juga menjaga `.env.prod.template` identik dengan `.env.example`.

**`GRAPH__CC` multi-alamat (2026-10-02):** kode hanya memecah dengan koma, jadi `a@x.com;b@x.com` (format Outlook) terkirim sebagai SATU alamat rusak dan Graph menolak draft. `cti_alerts.mailer.split_addresses` kini menerima koma ATAU titik koma (campuran boleh, spasi/entri kosong diabaikan); 11 test, 4 mutasi 0 selamat; komentar di kedua template env diperbarui.

**Belum terbukti:** host Linux amd64 sungguhan; probe `check_secrets` dengan key asli; beban nyata /
concurrency bawaan; scraper menembak dari IP host baru (census ulang); jalur `--skip-nginx` dan sertifikat
sendiri; timer backup Postgres tidak dipasang skrip (sengaja, butuh systemd + keputusan lokasi off-host).

**Konteks rencana (keputusan user 2026-09-30):** host staging ini kandidat PRODUKSI (dipakai internal
kantor, TLS self-signed cukup), dan legacy TIDAK langsung dimatikan -- dibandingkan dulu. Ceklis
bandingnya: `docs/PARALLEL_RUN_COMPARISON.md`. Banding baru bermakna SETELAH post-deploy di atas jalan.

**Langkah operasional cutover (10.1-10.7 di bawah tetap berlaku):**

- [ ] **10.1** Seed data referensi: `techstack`, `monitored_accounts`,
      user/role/client -- masih kosong, ini yang genuinely nunggu Fase 10.
      `ioc_allowlist`/`threat_actor_groups`/`monitored_people` **UDAH
      KELAR duluan Fase 5** (2026-09-18, `tools/seed/fase5_reference_data.py`)
      -- lihat catatan lengkap di Fase 5.
      **KOREKSI 2026-10-01 (QA, lihat 10.H):** "kelar" itu cuma benar di KODE.
      `fase5_reference_data.py` gak pernah dijalankan di staging, dan runbook cutover
      cuma nyuruh jalanin `fase10_reference_data.py` (yang waktu itu gak ngisi tabel-tabel
      ini) -- hasilnya `threat_actor_groups` kosong di staging: dropdown TA kosong,
      PIR berbasis TA 0 artikel, Risk Matrix 0 sel. Sejak PR #1 seed-nya ikut di
      `fase10_reference_data.py` (~3991 grup + `monitored_people` + `ioc_allowlist_entries`).
- [x] **10.1b** **Dipindah dari 4.12** (2026-09-18, biar Fase 4 gak keblok
      kerjaan yang sifatnya emang cutover, bukan migrasi): job nonaktif
      diarsipkan, digarap di sini bareng seed data lain -- bukan lagi
      dependency buat nutup Fase 4. **Keputusan user 2026-09-30: udah gak
      relevan, gak usah dikasih action apa pun** -- diceklis biar ketauan
      statusnya, bukan hasil kerjaan arsip beneran.
- [~] **10.1c** **Dipindah dari 4.8** (2026-09-18): rewrite 6 scraper
      Selenium nonaktif (`0xToxinThreat`, `emailnewsThreat`,
      `forcepointThreat`, `mandiantThreat`, `trellixThreat`,
      `vxMalwareDefenseThreat`) + `cyborgHuntingIdea` (gak kedaftar
      Rundeck). **1 dari 7 UDAH DIKERJAIN sebagai test case** (sebelum
      pindah, biar tau seberapa berat sisanya): `mandiant.py` --
      `mandiant.com/resources/blog` (target XPath lama) SEKARANG REDIRECT
      ke `cloud.google.com` (Mandiant diakuisisi Google, konten
      threat-intel pindah ke Google Cloud Blog topic "Threat
      Intelligence"). Ternyata situs barunya nyediain RSS resmi
      (`feeds.feedburner.com/threatintelligence/...`) -- jadi BUKAN
      `runtime="browser"` sama sekali, `RSSScraper` 20 baris biasa.
      Live-verified: `dry-run`/`run` 20 item, persisted bersih, 544 test
      lulus, `ruff`+`mypy --strict` bersih. **Pelajaran buat sisa 6**: gak
      bisa ditebak dari kode lama doang -- tiap situs kudu dicek satu-satu
      (bisa jadi gampang kayak Mandiant, bisa jadi beneran butuh browser
      automation, gak ada cara tau tanpa ngecek langsung).

      **Lanjutan 2026-09-30 -- 2 dari 6 sisanya KELAR, 1 DROPPED, 3 diblokir/di luar scope:**

      - **`toxinlabs.py` (0xToxin) -- KELAR.** Homepage-nya nyediain Atom
        feed resmi (`0xtoxin.github.io/feed.xml`), jadi `RSSScraper` biasa
        kayak Mandiant. Ketemu bug BARU pas port: feednya nge-paste konten
        analisis malware/IOC mentah yang bawa byte kontrol ilegal XML 1.0
        (`\x01`-`\x05`), bikin `defusedxml` nolak "not well-formed" --
        diperbaiki DI FRAMEWORK (`RSSScraper._parse_feed`,
        `strip_illegal_xml_chars()`), bukan `xml_fixups` per-scraper, karena
        ini masalah generik (feed apapun yang nge-paste output
        terminal/hexdump bisa kena). Live-verified: `dry-run` 10 item.
        **Catatan:** blog-nya sendiri MATI TOTAL sejak Agustus 2023 (entry
        terbaru di feed = 2023-08-06) -- diport buat kelengkapan, bukan
        karena diharapkan aktif.
      - **`forcepoint.py` -- KELAR.** Gak ada RSS, tapi struktur `/blog`
        skarang beda dari script lama: kartu ke-1 (hero) pakai `<h2>` nested
        di beberapa `<div>`, kartu grid di bawahnya pakai `<h4>` langsung
        anak `<a>`, dan ada blok non-artikel (newsletter signup) nyempil di
        antara kartu yang bikin index `div[N]` lompat-lompat -- jadi dipakai
        `indexed=False` + XPath union `h2`/`h4`, bukan `{i}` tetap kayak
        script lama (yang cuma nangkep 2 kartu, gak termasuk hero).
        Live-verified: `dry-run` 5 item, urutan & URL cocok sama browser
        interaktif.
      - **`trellix.py` -- DROPPED (keputusan user 2026-09-30).** Selector-nya
        (struktur situsnya PERSIS sama kayak script lama, beda dari
        forcepoint) diverifikasi manual lewat browser interaktif dan lolos
        unit test XPath. TAPI `cti-scraper dry-run trellix` gagal
        `net::ERR_HTTP2_PROTOCOL_ERROR` -- dicoba dari DUA network beda
        (sandbox lokal & staging 172.25.1.77), sama persis, `curl` polos ke
        domain ini juga kena hal serupa dari kedua network. Ini keliatan
        kayak proteksi bot di level CDN Trellix yang nolak client
        non-browser/headless secara konsisten -- BUKAN dicoba dilewatin
        (di luar scope kerjaan ini buat evasion bot-detection). User
        memutuskan drop, bukan coba network lain/waiver. File `trellix.py`
        + test-nya sudah dihapus dari tree.
      - **`vxMalwareDefenseThreat` -- BELUM diport, DIBLOKIR Cloudflare
        Turnstile, DICEK sumber alternatif (keputusan user), GAK KETEMU yang
        bersih.** `vx-underground.org` sekarang mewajibkan captcha
        "Verify you are human" (Cloudflare Turnstile) buat SELURUH domain --
        bukan cuma path `/Papers`, `robots.txt` dan `sitemap.xml` juga kena
        --, termasuk lewat browser interaktif asli, bukan cuma `curl`. Sesuai
        kebijakan, captcha/bot-detection TIDAK dicoba dilewatin. Dicek 2
        alternatif dari channel resmi vx-underground:
          - GitHub `vxunderground/VXUG-Papers` -- ADA, tapi kategori kontennya
            BEDA (riset teknik malware development dari member vx-underground
            sendiri, 40 commit total sepanjang sejarah repo) -- bukan
            pengganti "Malware Defense/Malware Analysis" bulanan (kompilasi
            analisis pihak ketiga) yang ditarget script lama.
          - Telegram publik `t.me/s/vxunderground` -- GAK kena gate (halaman
            preview publik Telegram, beda infra dari domain utama), TAPI
            isinya campur random (meme, curhat pribadi, obrolan off-topic)
            dengan SESEKALI pengumuman upload paper -- gak ada feed
            terstruktur, butuh classifier buat misahin "pengumuman paper
            baru" dari mayoritas konten gak relevan. Bukan pengganti
            langsung, effort-nya beda kelas dari "port scraper" (lebih ke
            proyek NLP kecil).
        **Kesimpulan: gak ada pengganti 1:1 yang bersih.** Tetap gak diport.
        Kalau mau lanjut nanti: opsi realistisnya cuma nunggu source lain
        yang user tau, atau terima waiver permanen -- JANGAN re-investigasi
        GitHub/Telegram dari nol, triase di atas udah final.
      - **`emailnewsThreat` -- DI LUAR SCOPE migrasi framework ini.** Bukan
        scraper web sama sekali -- polling inbox Gmail via IMAP, parsing
        ad-hoc per pengirim (newsletter SimplyCyber/Gerald Auger,
        LetsDefend, CrowdStrike Intelligence Weekly, Metacurity Substack).
        Alert-nya sendiri udah dikomentar di script lama (gak pernah
        beneran ngirim). Framework `RSSScraper`/`XPathScraper` gak
        nyediain "family" buat polling email -- butuh infrastruktur baru
        kalau mau dihidupkan lagi, bukan port 3 baris. **Ketemu credential
        Gmail app-password hardcoded di script-nya** -- ditambahin ke
        `docs/SECRETS_ROTATION.md` (item #14), TIDAK dicetak di sini/shell
        sesuai kebijakan secret. **Rotasinya DIDELEGASIKAN ke tim ops user
        2026-09-30** (sama pola kayak item 1-13) -- lihat SECRETS_ROTATION.md.
        Migrasi script itu sendiri (bukan rotasi secret-nya) **DIPARKIR
        atas permintaan user 2026-09-30** ("di notes dulu aja, nanti
        dipikirin lagi") -- bukan keputusan final (drop ATAU lanjut bangun
        infra IMAP), cuma ditunda. Jangan dikerjain lebih jauh sebelum user
        bawa ini lagi.
      - **`cyborgHuntingIdea` -- DI LUAR SCOPE, bukan scraper alert sama
        sekali.** Ini tool riset one-off: login ke produk berbayar
        `hunter.cyborgsecurity.io`, paginasi ratusan "hunting package",
        dump ke file JSON lokal -- gak ada `push_job`/`send_alert`/`nlp_scan`
        di mana pun, jadi gak fit ke model "scraper artikel" platform ini
        sama sekali. **Ketemu credential login (email + password) hardcoded
        di script-nya** untuk akun berbayar Cyborg Security -- ditambahin
        ke `docs/SECRETS_ROTATION.md` (item #15), TIDAK dicetak di
        sini/shell. **Rotasinya DIDELEGASIKAN ke tim ops user 2026-09-30**
        (sama pola kayak item 1-13). Migrasi script itu sendiri (bukan
        rotasi secret-nya) **DIPARKIR atas permintaan user 2026-09-30**
        sama kayak `emailnewsThreat` di atas -- ditunda, bukan keputusan
        final.

      **Keputusan user 2026-09-30 (setelah laporan di atas): trellix DROP,
      vxMalwareDefense cari alternatif (gak ketemu, lihat triase di atas),
      2 secret baru (#14, #15) didelegasikan ke tim ops, migrasi
      `emailnewsThreat`/`cyborgHuntingIdea` DIPARKIR (bukan drop, bukan
      lanjut -- user mau pikir lagi nanti).**

      **Total final 10.1c: 3/7 kelar & live (mandiant, toxinlabs,
      forcepoint), 1/7 dropped (trellix), 1/7 gak diport -- gak ada
      pengganti (vxMalwareDefense, captcha), 2/7 diparkir (emailnewsThreat,
      cyborgHuntingIdea -- secret-nya sudah didelegasikan, migrasi
      script-nya ditunda sampai user angkat lagi).** 2 file baru
      (toxinlabs, forcepoint) + fix framework (`strip_illegal_xml_chars`)
      lolos test (1108 -> 1114 sempat, balik ke lebih sedikit setelah
      trellix's test dihapus) + mutation check manual (17 mutasi dicoba,
      13 relevan setelah trellix dihapus, 0 selamat) -- lihat
      `tests/unit/test_rss_illegal_xml_chars.py` dan
      `tests/unit/test_fase10_1c_dormant_scrapers.py`.
- [x] **10.1d** **Dipindah dari 6.7** (2026-09-18, keputusan user): lock
      singleton buat Celery beat (cegah dua proses beat sama-sama fire
      schedule yang sama pas deploy multi-node). Redis udah kepake luas
      (broker Celery, `TokenBucket`) -- pola paling gampang: `SET NX PX`
      di `redis.Redis` yang sama, lock diperpanjang tiap beat tick (bukan
      lock sekali pas start, biar proses yang macet ketauan lewat TTL
      abis, bukan nyangkut lock permanen). Ini yang dicek checklist
      cutover "Beat terverifikasi singleton" di bawah.
      **KELAR di 10.A (2026-09-26)** -- lihat catatan 10.A.
- [x] **10.1e** **Dipindah dari 6.8** (2026-09-18, keputusan user): guard
      backpressure antrian `enrich` -- baru relevan begitu `worker-nlp`
      (image terpisah, concurrency dibatasi RAM spaCy/sumy, plan §10)
      beneran jalan dan kelihatan antrian numpuk lebih cepat dari yang
      bisa diproses. Opsi paling murah: cek `queue.enrich` depth via
      Redis (`LLEN`) sebelum `_article_sink` dispatch, log warning/tolak
      dispatch kalau ngelewatin ambang -- keputusan ambang & aksi pasti
      nunggu angka nyata dari `worker-nlp` produksi, bukan ditebak sekarang.
      **Mekanisme KELAR di 10.A (2026-09-26)** (ambang default 2000 tetap
      tebakan, setel ulang pas ada angka nyata) -- lihat catatan 10.A.
- [x] **10.2** Verifikasi cold-start guard -- checkbox lama, SUDAH terverifikasi berkali-kali lewat
      jalur lain sebelum sempat dicentang: unit (10.A, `Runner._cold_start_cap`), container live
      (10.B, 6 `cold_start_cap` live), warm start (10.C, 0 `cold_start_cap` setelah seed = kerja
      benar), rehearsal beat sampel besar (10.G, 1.074 duplikat + `cold_start_cap` hidup live).
- [ ] **10.3** Stop cron lama + systemd unit lama
- [ ] **10.4** Arsipkan dump Mongo final
- [ ] **10.5** `docker compose up -d`
- [ ] **10.6** Pantau 4 jam
- [ ] **10.7** Hypercare 1 minggu

**Checklist cutover — semua wajib hijau:**
- [x] `static/` ke-commit (29 file di `legacy/static/`); "dilayani container web" N/A -- web sekarang Next.js, `static/` cuma spesifikasi perilaku (keputusan survei 2026-09-26)
- [~] Tiap scraper live punya golden test hijau **atau** waiver tertulis -- 2026-10-01 (10.I): census staging dikerjakan, 5 waiver tertulis (docstring + `KNOWN_BROKEN.md`), 18 scraper diperbaiki terbukti `dry-run ok` DAN `ok` sepanjang semalam di beat (health 2026-10-02: ok 85 / disabled 5 / zero_yield 2 sah / degraded 4). **Tinggal:** 4 scraper Twitter `degraded` karena kredit twitterapi.io habis lagi (butuh top up/keputusan user, bukan bug), `intel471` baru stabil dari egress staging, dan census ulang dari IP produksi bila egress-nya beda
- [x] Semua secret dirotasi, `gitleaks` bersih, gak ada secret di layer image -- rotasi 15 secret
      legacy **didelegasikan ke tim ops user 2026-09-30** (13 awal + 2 ketemu susulan investigasi
      10.1c); `gitleaks` **diverifikasi teknis** hari yang sama (history 61 commit + 1.168 file
      calon-commit, 0 temuan) dan hook pre-commit terpasang + teruji beneran nyegat (lihat
      `docs/SECRETS_ROTATION.md`). **"gak ada secret di layer image" -- diverifikasi 2026-09-30**:
      scan SEMUA 5 image staging (`cti-api`, `cti-worker`, `cti-worker-nlp`, `cti-web`,
      `cti-nginx`; 61 layer total) pakai `gitleaks detect --no-git` per-layer (bukan cuma state
      final image -- layer yang KEHAPUS di layer berikutnya tetap ketauan lewat cara ini) +
      pengecekan nama file (`.env`, `*.pem`, `credentials*`, dll). Hasil: **nol secret PLATFORM
      KITA yang bocor**. Temuan yang ADA, semua false-positive atau bukan secret kita:
      `certifi/cacert.pem` (bundle CA publik, bukan secret), kunci publik ekstensi Chromium
      (`reading_mode_gdocs_helper_manifest.json`, dari binary Chromium vendor, bukan milik kita),
      variabel/identifier ber-entropy tinggi di JS yang di-minify, dan beberapa file bernama
      `credentials.py` (punya `cti_scraper`, `openai`, `telegram`, `redis` -- SEMUA modul yang
      cuma ngedefinisiin CARA baca/pegang kredensial dari env, dicek isinya satu-satu, nol nilai
      secret hardcoded). **Satu kategori nyata tapi bukan secret KITA**: `previewModeSigningKey`
      + `previewModeEncryptionKey` (`.next/prerender-manifest.json`) dan `encryptionKey`
      (`.next/server/server-reference-manifest.json`) di image `cti-web` -- kunci acak yang
      Next.js generate SENDIRI tiap build buat fitur Preview Mode & Server Actions. Dicek:
      `apps/web` **gak pakai** `"use server"` atau draft/preview mode sama sekali (`grep` 0 match)
      -- kunci ini ada tapi gak ke-exploit karena fitur-nya gak dipakai. Gak perlu tindakan
      sekarang, dicatat aja buat kalau nanti fitur itu mulai dipakai.
- [x] Backup Mongo <24 jam, sudah dites restore -- **diverifikasi 2026-09-30 di staging**
      (`cti-mongo`, dump `/home/nameless/backups/mongo-cti/20260930T120307Z`, umur <1 jam saat
      dites): restore `news_db`+`threatintel` ke namespace sementara, total 2 detik, 205.446
      dokumen, 9 collection kunci dicek cocok PERSIS lawan file dump asli (0 selisih). Ketemu &
      diperbaiki 2 jebakan di command yang didokumentasikan (lihat `docs/PROD_PREP.md` §1 --
      `mongorestore` nunjuk folder per-db langsung gak jalan, dan `--nsInclude` wajib ada biar gak
      diam-diam nulis ke database lain di folder yang sama). Ini drill di STAGING, bukan host
      produksi lama yang jadi target asli dokumen -- membuktikan mekanismenya benar, bukan
      pengganti drill produksi.
- [ ] Stack lama bisa dinyalakan lagi <5 menit (sudah dilatih) -- 10.G: prosedur + alat (`rundeck_schedule.py`, runbook 7.3) SIAP, latihan di produksi BELUM (butuh Rundeck/host lama)
- [x] Health sweep terbukti bisa deteksi scraper mati (tes di staging) -- 10.G: beat asli + thread `scraper_health`; `worker-browser` dimatikan -> `dead` di digest, pulih -> `ok`. **Catatan 2026-10-01 (10.H):** terbukti buat SCRAPER mati, BUKAN beat mati (97 jam gak ketahuan); watchdog beat ada di PR #1 dan SUDAH ke-deploy ke staging 2026-10-01 (aktif di 3 container worker, heartbeat `ok`)
- [x] Beat terverifikasi singleton (10.1d) -- 10.A: test Redis asli + 2 proses live
- [ ] Data referensi ter-seed -- staging SUDAH (2026-10-01: `threat_actor_groups` 3995, `monitored_people` 30, `ioc_allowlist_entries` 9); yang tersisa di item ini cuma seed PRODUKSI (10.1)
- [x] Fix QA (10.H) ke-deploy ke staging + post-deploy dijalankan & diverifikasi (revisi DB `c3a7e9d1f2b4`, `threat_actor_groups` 3995, backfill, remap TTP, watchdog beat aktif) -- 2026-10-01, detail di 10.H
- [ ] Data uji & kredensial uji di host kandidat prod dibersihkan (TA whitelist `testactor`/`testing`, password `stg-admin` + sisa kredensial dev Fase 9)
- [ ] Banding paralel legacy vs platform baru lolos kriteria `docs/PARALLEL_RUN_COMPARISON.md` §7 (minimal 1 minggu, hijau 3 hari berturut-turut) -- baru boleh mulai setelah item deploy di atas beres

---

## Pertanyaan terbuka

- ~~**`/opt/HuntingScript/`**~~ dan ~~**`/opt/alertRundeck/`**~~ — **kelar:
  Rundeck gak jadwalin keduanya.** Di luar scope.
- ~~**Simpen raw response LLM buat audit trail produksi**~~ **kelar 2026-10-05
  (stage klasifikasi)**: `classify()` nyimpen model, `PROMPT_VERSION` (hash prompt),
  dan SETIAP percobaan (isi mentah + `finish_reason`) ke `raw_enrichment["classify"]`
  -- artikel diterima (`Article`) DAN ditolak (`RejectedArticle`). Gagal total
  (JSON rusak semua percobaan) -> respons mentah masuk log `classify_json_failed`,
  bukan DB. Belum: stage `extract_ttps`, dan tampilan di UI/API (query lewat SQL).
  Catatan asli: (2026-09-18,
  diusulkan user pas nemuin gateway LLM dev ngebalikin persona "Kiro" yang
  nolak instruksi JSON, lihat catatan bug Fase 7.3 Bagian 1 di atas) --
  BELUM dikerjain, dicatet dulu biar gak lupa.

  Precedent udah ada di skema: `Article.raw_enrichment` (JSONB, Fase 2)
  komentarnya eksplisit bilang "output LLM mentah... cadangan/audit
  trail", tapi `persist.py` gak PERNAH nulis ke kolom itu -- infra-nya
  ada, belum disambung. `RejectedArticle` (baru, Fase 7.3) cuma nyimpen
  `reason` (ringkasan satu baris dari LLM), bukan raw completion penuh --
  justru buat kasus kayak "Kiro persona" itu ARTIKEL YANG DITOLAK yang
  paling kepake diaudit (biar keliatan LLM-nya lagi ngaco jawabnya),
  bukan yang diterima.

  Scope kalau dikerjain: (1) `classify()`/`extract_ttps()` (`cti_enrich.
  stages`) balikin raw completion, bukan cuma hasil ke-parse, (2)
  `persist.py::persist()` isi `Article.raw_enrichment`, (3) migrasi baru
  nambah kolom serupa di `RejectedArticle`, (4) `persist_rejected()` isi
  itu. Nyentuh jalur enrichment yang udah live-verified Fase 5/6/7 --
  butuh re-test kayak yang dilakuin pas `filtered_articles` kemarin,
  bukan sekadar tambah kolom pasif.
- ~~**`cve_db`**~~ — **kelar: 0 dokumen.** Database mati. Gak usah masuk skema
  Postgres.
- ~~**Devo (SIEM)**~~ — **di-skip**, gak masuk scope revamp. Token-nya tetap
  ada di daftar rotasi karena `config.yml` udah disalin ke laptop.

---

## Scope ditunda — 3 codebase di luar ScraperNews

**Keputusan: dicatat dulu, belum digarap.** Bukan blocker Fase 0.

Export Rundeck ngungkap 9 job (6 aktif) yang nunjuk ke kode di luar
`/opt/ScraperNews` — dan ketiganya **gak ada di checkout ini**:

| Repo | Job | Script | Jadwal | Status |
|---|---|---|---|---|
| `BreachForums` | Breachforums Capture  | `BFcapture.py` | `20 * * *` | nonaktif |
| `BreachForums` | Breachforums Scraping  | `BFurl.py` | `10 * * *` | nonaktif |
| `TwitterScrap` | Twitter CVE Trending | `trendingCve.py` | `0/15 * * *` | **aktif** |
| `TwitterScrap` | Twitter Scrap (1 Hour) | `twitter.py` | `0 * * *` | **aktif** |
| `TwitterScrap` | Twitter Scrap (1.30 Hour) | `twitter30.py` | `30 * * *` | **aktif** |
| `TwitterScrap` | Twitter Chris Sanders | `investigateScenario.py` | `0 * * *` | nonaktif |
| `techstackLibrary` | TechStack Golang | `techstackGO.py` | `46 * * *` | **aktif** |
| `techstackLibrary` | TechStack NPM | `techstackNPM.py` | `46 * * *` | **aktif** |
| `techstackLibrary` | TechStack PyPi | `techstackPYPI.py` | `46 * * *` | **aktif** |

Yang perlu diperhatiin nanti:

- **`techstackLibrary` kemungkinan sumber sebenarnya.** `techstackNPM.py` juga
  ada di `ScraperNews/`, tapi yang dijadwalin Rundeck versi
  `/opt/techstackLibrary`. Salinan di ScraperNews kemungkinan fork yang basi.
  Ini juga nyambung ke duplikasi package-vuln yang udah dicatat di plan
  (`pkg_vuln_service.py` 1109 baris vs `pkgVulnScanner.py` 419 baris) — jadi
  fitur ini kemungkinan dibangun **tiga kali**, bukan dua.
- **`TwitterScrap` DIBACA, TERNYATA BUKAN tabrakan.** User tarik repo dari
  produksi, dibaca lengkap (4.9): `twitter.py`/`twitter30.py`/`trendingCve.py`
  pakai API Twitter RESMI (bearer token), daftar akun dari file teks statis
  (`supportFile/usernames_*.txt`), dan **gak nulis DB sama sekali** — murni
  klasifikasi konten (APAC/CVE/OT/zero-day) yang berakhir di Telegram alert
  doang. `monitorX.py` pakai API BEDA (twitterapi.io), akun dari DB
  (`monitored_accounts`), dan itu SATU-SATUNYA yang beneran nulis ke
  `tweets`. Dua jalur independen, gak ada overlap — `trendingCve`/`twitter`/
  `twitter30` dipindah ke `NOT_A_SCRAPER_STEMS` (`run_migration.py`), bukan
  scraper dalam pengertian framework baru (Fase 6 beat task kalau mau
  dilanjutin). `investigateScenario.py` (nonaktif) dan `newTwitter.py`
  (gak ada di Rundeck sama sekali, Selenium peninggalan) gak masuk scope
  Fase 4 sama sekali.
- **`techstackLibrary` masih belum ditarik** — `monitorX` sendiri sekarang
  ketunda karena alasan LAIN (LLM client, lihat Fase 4.9), bukan ini.
- **`BreachForums` dua-duanya nonaktif** — prioritas paling rendah.

**Kalau nanti mau digarap:** `techstackLibrary`/`BreachForums` masih perlu
ditarik dari prod (`TwitterScrap` udah, per catatan di atas). Detail jadwal
tiap job udah ada di `docs/legacy/rundeck-jobs-map.json`.
