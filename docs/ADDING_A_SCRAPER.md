# Nambah Scraper Baru (step by step)

Panduan buat nambah **satu scraper baru** dari nol sampai jalan di produksi. Cara
merawat scraper yang sudah jalan (rusak, kosong, mati) ada di
[`SCRAPER_MAINTENANCE.md`](SCRAPER_MAINTENANCE.md).

Prinsipnya: **satu scraper = satu file** di `scrapers/src/cti_scrapers/feeds/`.
Tidak ada registry yang diedit, tidak ada jadwal terpusat, tidak ada entri
`pyproject.toml`. Taruh file, framework menemukannya sendiri (auto-discovery,
`cti_scraper.registry`). Saat ini ada ±95 scraper terdaftar.

> Terakhir diverifikasi terhadap kode dan container prod: 2026-10-05
> (`cti-scraper list`, `cti-scraper dry-run bitdefender` jalan di container `worker`).

---

## 0. Peta singkat: apa yang terjadi pada scraper

```
beat (jadwal cron)  ->  Celery task scrape.run  ->  Runner  ->  fetch() milik scraper
                                                      |
                              dedup (reserve) <-------+------->  sink (sesuai tipe item)
                                                                    |
                                                  ArticleItem -> enrich task (LLM, skor, IOC) -> tabel articles
```

Yang kamu tulis cuma `fetch()` (atau, untuk RSS/XPath/API sederhana, cuma isi
atribut kelas). **Dedup, retry, rate limit, heartbeat, logging, penyimpanan,
alert ditangani framework** -- jangan ditulis ulang di file scraper.

---

## 1. Pilih jenis scraper

| Sumber | Family | `meta.runtime` | Contoh |
|---|---|---|---|
| RSS / Atom | `RSSScraper` | `light` | `feeds/bitdefender.py` |
| Halaman HTML statis | `XPathScraper` | `light` | `feeds/cyfirma.py` |
| Halaman HTML yang perlu JavaScript | `XPathScraper` | `browser` | `feeds/abnormalsecurity.py` |
| JSON API sederhana (daftar item) | `ApiScraper` | `light` | `families/api.py` |
| Selain itu (state, auth, dokumen sendiri) | turunan `BaseScraper` langsung | sesuai kebutuhan | `collectors/ransomware_live.py` |

Urutan coba: **RSS dulu** (paling stabil, paling murah), lalu API, lalu XPath
`light`, dan `browser` hanya kalau memang wajib (Chromium berat dan jalan di
worker terpisah dengan concurrency kecil).

Cek sumbernya dulu sebelum menulis apa pun:

```bash
curl -sI https://contoh.com/feed | head -5          # status + content-type
curl -s  https://contoh.com/feed | head -40         # RSS? Atom? isinya apa?
curl -s  https://contoh.com/robots.txt              # ada larangan crawling?
```

Kalau ada RSS/Atom, selalu pakai itu, bukan scrape HTML-nya. Kalau situs
melarang crawling atau butuh login/captcha, **berhenti dan putuskan dulu**
(jangan menembus captcha atau bikin akun di sumber).

---

## 2. Siapkan lingkungan dev

```bash
git checkout -b feat/scraper-<nama>
uv sync --extra dev                                  # dari root repo
uv run cti-scraper list | head                       # harus menampilkan daftar scraper
```

Scraper `runtime="browser"` butuh Playwright: `uv sync --extra browser` di
`packages/cti-scraper`, lalu `playwright install chromium`.

---

## 3. Buat file scraper

**Tidak ada perintah scaffold** (`cti-scraper new` *tidak ada*): salin scraper
referensi yang sejenis lalu ubah.

```bash
cp scrapers/src/cti_scrapers/feeds/bitdefender.py scrapers/src/cti_scrapers/feeds/<slug>.py
```

### 3a. RSS (kasus paling umum)

```python
"""Nama Sumber -- apa yang dipantau, dan kenapa."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class NamaSumber(RSSScraper):
    meta = ScraperMeta(
        id="nama_sumber",                       # slug, huruf kecil. JANGAN diubah setelah deploy
        source="Nama Sumber",                   # label tampilan, harus UNIK dan bermakna
        schedule=spread("*/30 * * * *", "nama_sumber"),
        tags=("vendor",),
        legacy_script="nama_sumber",            # dipakai nama folder fixture (lihat langkah 5)
    )
    feeds = ("https://contoh.com/feed.xml",)
```

Atribut RSS yang sering perlu diubah (semua `ClassVar`, lihat
`packages/cti-scraper/src/cti_scraper/families/rss.py`):

| Atribut | Default | Kapan diubah |
|---|---|---|
| `item_path` | `.//item` | Atom: `.//{http://www.w3.org/2005/Atom}entry` |
| `link_path` / `link_attr` | `link` / `None` | Atom: `link_attr = "href"` |
| `date_path` | `pubDate` | `None` kalau feed tidak punya tanggal (dipakai waktu scrape) |
| `base_url` | `""` | link di feed relatif |
| `xml_fixups` / `html_unescape` | kosong / `False` | feed dengan entity rusak (jarang perlu) |
| `_include_item(node)` | semua lolos | filter per item, mis. kategori tertentu saja |

### 3b. XPath

```python
class NamaSumber(XPathScraper):
    meta = ScraperMeta(id="nama_sumber", source="Nama Sumber",
                       schedule=spread("0 */2 * * *", "nama_sumber"), runtime="light")
    url = "https://contoh.com/blog"
    title_xpath = "(//article//h2)[{i}]"       # {i} diisi 1..max_items kalau indexed=True
    link_xpath = "(//article//h2/a/@href)[{i}]"
    base_url = "https://contoh.com"
```

`indexed = False` memakai satu XPath untuk semua kartu (judul dan link dipasangkan
berurutan). Kalau `title_xpath` tidak cocok sama sekali, framework melempar
`ParseError` (artinya: situs berubah). Untuk halaman yang butuh JavaScript:
`runtime="browser"` plus `wait_for = "<css selector>"`.

### 3c. API JSON

Isi `url`, `root_path` (kunci yang menunjuk list), dan `field_map`
(`{"title": "<kunci json>", "url": "<kunci json>"}`). Kalau mapping tidak sesederhana
itu, turunkan `BaseScraper` langsung dan tulis `fetch()` sendiri.

### 3d. Menulis `fetch()` sendiri (bespoke)

```python
def fetch(self, ctx):
    resp = ctx.http.get("https://api.contoh.com/items")   # client bersama: UA, timeout, rate limit
    for row in resp.json()["items"]:
        yield ArticleItem(title=row["title"], url=row["url"], posted_on=ctx.now.date())
```

Aturan `fetch()`:
- HTTP **hanya** lewat `ctx.http`; browser lewat `ctx.page()`. Jangan bikin `httpx.Client`/`requests` sendiri.
- Waktu **hanya** lewat `ctx.now` (bukan `datetime.now()`), supaya test deterministik.
- Jangan akses DB, Telegram, atau token mentah. Butuh data internal? Deklarasikan `meta.reference_data`; butuh API key? Deklarasikan `meta.credential`.
- Jangan `try/except` untuk menelan error. Lempar `TransientFetchError` untuk yang layak di-retry (5xx, timeout) dan `ParseError` kalau dokumen terbaca tapi strukturnya berubah.
- Yield nol item itu sah (tercatat `empty`). Jangan `yield` sampah supaya "kelihatan jalan".
- Tipe item lain (`NoticeItem`, `CveItem`, `RansomwareVictimItem`, ...) menentukan tujuan lewat *sink*; lihat `cti_scraper/items.py` dan `sinks.py`.

### 3e. Isi `ScraperMeta` dengan benar

| Field | Catatan |
|---|---|
| `id` | **Permanen.** Jadi namespace dedup dan kunci control plane. Mengubahnya = mereset dedup, scraper meng-yield ulang semua item. |
| `source` | Tampil di artikel, Telegram, dan UI. Harus unik (case-insensitive) dan bukan placeholder ("Name", "Source", ...), dijaga `tests/contract/test_scraper_labels.py`. |
| `schedule` | Cron 5 field. Pakai `spread("*/N * * * *", id)` supaya puluhan scraper tidak menembak di menit yang sama. Untuk RSS vendor, 15-60 menit cukup. |
| `runtime` | `light` (httpx) atau `browser` (Playwright). Menentukan queue Celery: `browser` -> `scrape.browser`, ada `credential` -> `scrape.api`, sisanya -> `scrape.rss`. |
| `rate_limit` | Default `20/minute`, **per domain** (dua scraper ke host sama berbagi budget). Turunkan untuk situs yang sensitif. |
| `max_items` | Batas keras per run (maks 1000). Pagar kalau parser tiba-tiba meledak. |
| `tags` | Bebas, dipakai filter (`cti-scraper list --tag vendor`). |
| `legacy_script` / `legacy_label` | Untuk scraper baru, `legacy_script` cukup diisi sama dengan `id` (dipakai nama folder fixture). Harus unik. |
| `enabled` | Default `True`. Lihat langkah 8 sebelum deploy. |

---

## 4. Dry-run (nyata, tidak menulis apa pun)

```bash
uv run cti-scraper dry-run nama_sumber
# status=ok items_found=15 duration_ms=147
```

Mengambil dari sumber asli, **tanpa** menyentuh DB, dedup, atau alert. Output-nya
cuma ringkasan (status, jumlah item, error), **bukan daftar item**. Untuk melihat
isi item (judul/URL/tanggal) sungguhan, pakai snippet ini:

```bash
uv run python - <<'PY'
from datetime import UTC, datetime
import structlog
from cti_scraper import registry
from cti_scraper.base import ScrapeContext
from cti_scraper.http import ScraperHttpClient

cls = registry.get("nama_sumber")
m = cls.meta
ctx = ScrapeContext(
    meta=m, run_id="dev", log=structlog.get_logger(),
    http=ScraperHttpClient(timeout_s=m.timeout_s, rate_limit=m.rate_limit),
    now=datetime.now(UTC).replace(tzinfo=None),
)
for it in cls().fetch(ctx):
    print(it.title, it.url, it.posted_on)
PY
```

(Hanya untuk `runtime="light"`; scraper `browser` cukup dicek lewat `dry-run` dan `verify`.)
Cek: jumlah item masuk akal, judul dan URL benar, tanggal terisi, dan tidak ada
`ERROR [...]` di `dry-run`.

Status yang mungkin: `ok`, `empty` (nol item), `parse_error` (struktur berubah),
`fetch_error`, `rate_limited`, `backpressure`.

Dry-run juga bisa dijalankan di container prod (read-only terhadap data):

```bash
docker compose exec worker cti-scraper dry-run nama_sumber
```

---

## 5. Fixture + verify (baseline regression)

Fixture = byte HTTP yang direkam, supaya test tidak bergantung pada internet.

```bash
uv run cti-scraper verify nama_sumber --record     # rekam baseline dari sumber asli
uv run cti-scraper verify nama_sumber              # jalankan ulang lawan fixture, harus "OK"
```

- Hasil rekaman ada di `tests/fixtures/<legacy_script>/` (`<tanggal>.input.xml|html|json`
  dan `expected_items.json`). **Commit folder ini.**
- `--record` memerlukan `meta.legacy_script`. Scraper `runtime="browser"` tidak bisa
  direkam lewat CLI ini (pakai `tools/salvage/record_fixtures.py`).
- `verify` hanya jalan di **repo dev** (container prod tidak membawa `tests/fixtures`).
- Setelah merekam, **buka `expected_items.json`** dan pastikan isinya memang benar,
  jangan menyimpan baseline yang salah.

---

## 6. Test dan lint

```bash
uv run pytest tests/contract -k nama_sumber -q     # kontrak: id cocok, cron valid, fetch generator, max_items, runtime
uv run pytest tests/contract/test_scraper_labels.py -q   # label unik, bukan placeholder
uv run ruff check scrapers && uv run ruff format --check scrapers
```

Contract test jalan otomatis untuk semua scraper terdaftar. Kalau gagal,
**benerin framework atau meta-nya**, jangan mengakali di `fetch()`.

---

## 7. Commit dan review

```bash
git add scrapers/src/cti_scrapers/feeds/<slug>.py tests/fixtures/<slug>
git commit -m "feat(scraper): tambah <Nama Sumber>"
```

Hanya dua hal yang berubah: file scraper dan folder fixture. Kalau kamu merasa
perlu mengedit file lain, tanyakan dulu kenapa (biasanya itu tanda ada masalah di
framework).

---

## 8. Deploy ke produksi

Kode scraper ikut **image** (`COPY scrapers scrapers`), dan registry hanya dibaca
saat proses start. Jadi scraper baru perlu **rebuild image dan restart proses**
yang membaca registry:

```bash
git pull
docker compose --profile app up -d --build worker worker-browser beat api
```

| Service | Kenapa ikut rebuild |
|---|---|
| `worker` | menjalankan scraper `scrape.rss` dan `scrape.api` |
| `worker-browser` | menjalankan scraper `runtime="browser"` (tetap rebuild walau scraper `light`, image yang sama) |
| `beat` | **membangun jadwal saat start**; tanpa restart scraper baru tidak pernah dijadwalkan |
| `api` | daftar scraper di halaman `/scrapers` dan endpoint dry-run/trigger dibaca dari registry |

> Jadwal TIDAK di-hot-reload. Dokumen lama menulis "beat baca ulang tiap 60 detik":
> itu **tidak benar** untuk kode sekarang. `ScraperConfig.schedule`/`enabled` yang
> diubah lewat control plane baru dipakai beat setelah restart (lihat docstring
> `cti_worker.beat.build_beat_schedule`).

### Run pertama scraper baru (cold start)

Scraper yang belum punya riwayat dedup (nol baris `scraper_seen`) kena
**cold-start cap**: hanya `Settings.scraper.cold_start_max_items` (default **5**) item
**terbaru** yang diproses (enrichment, LLM, Telegram), sisanya langsung ditandai
"sudah dilihat" tanpa diproses (`Runner._cold_start_cap`). Jadi feed dengan ratusan
item lama tidak membanjiri antrian, tapi **5 item terbaru tetap masuk** sebagai artikel.

Kalau kamu mau **nol** item dari run pertama (mis. feed baru tapi isinya tidak
relevan sebelum hari ini):

```bash
docker compose exec worker cti-scraper run nama_sumber --prime
```

`--prime` menandai semua item yang ketemu sebagai seen tanpa menyimpan atau
mengirim apa pun; run terjadwal berikutnya hanya memproses yang benar-benar baru.

Kalau mau menguji dulu di prod tanpa menjadwalkan: deploy dengan `enabled=False`
di `meta`, cek lewat `dry-run` di container, lalu aktifkan (`cti-scraper enable
nama_sumber` atau tombol di `/scrapers`) dan **restart `beat`**.

---

## 9. Verifikasi setelah deploy

1. `/scrapers` di UI: scraper muncul, status bukan `stale`/`dead`.
2. Setelah satu tick jadwalnya: buka detail scraper -> **Runs**: `status=ok`, `items_found>0`.
3. Tab **Items**: item muncul; cek satu artikel di Newsroom (judul, URL, sumber benar).
4. Kalau status `empty`, `parse_error`, atau `fetch_error`, ikuti
   [`SCRAPER_MAINTENANCE.md`](SCRAPER_MAINTENANCE.md).

Di UI (admin) tersedia juga **Dry-run** dan **Trigger** manual per scraper; trigger
mengirim tugas ke queue yang benar sesuai `meta.runtime`/`credential`.

---

## Kasus khusus

**API key / kredensial** -- isi `meta.credential = "github" | "nvd" | "twitter" | ...`
(lihat `cti_scraper/credentials.py`). `Runner` memasang header auth ke `ctx.http`
sebelum `fetch()`; kode scraper tidak pernah memegang token. Secret kosong di env
membuat run gagal `fetch_error` (stage `config`), bukan crash. Scraper
ber-credential masuk queue `scrape.api`.

**Data internal (techstack, dst.)** -- `meta.reference_data = ("techstack",)`;
`Runner` membaca dari Postgres lalu menaruhnya di `ctx.reference["techstack"]`.
`dry-run` tetap butuh koneksi DB untuk ini.

**Dua cara ambil data, admin boleh pindah tanpa deploy** -- deklarasikan
`ScraperOption` di `meta.options` (pilihan tertutup, divalidasi API). Dibaca lewat
`ctx.options["key"]`. Coba tanpa mengubah konfigurasi:
`cti-scraper dry-run <id> --option provider=x_official`. Kalau salah satu pilihan
berbayar per pemakaian, tulis peringatan biaya di `description` dan jangan jadikan default.
Kontrak dijaga `tests/contract/test_scraper_options.py`.

**Bentuk dokumen sendiri** (ransomware, CVE) -- cukup `yield` tipe item yang sesuai;
sink dipilih dari tipe item. Butuh tujuan baru: daftarkan `@sink_for(ItemKu)` di
file yang sama.

**Browser** -- `runtime="browser"`, pakai `with ctx.page() as page:`. Memanggil
`ctx.page()` dengan `runtime="light"` melempar `ConfigError` (sengaja, supaya
ketahuan saat dev). Concurrency worker browser sengaja kecil (`BROWSER_WORKER_CONCURRENCY`, default 2).

---

## Kenapa `fetch()` tidak boleh akses DB/Telegram langsung

Ini pagar keamanan, bukan gaya. Saat merekam fixture dari scraper lama, ada yang
membuat `MongoClient` langsung dari config dan ada yang menyimpan token Telegram
hardcoded: scraper yang "cuma dites" bisa menulis ke database produksi atau
mengirim pesan ke channel asli. `fetch()` hanya diberi `ctx.http`, `ctx.page()`,
`ctx.now`, `ctx.options`, `ctx.reference`. Jadi kelas bug itu tidak mungkin terulang.

---

## Checklist selesai

- [ ] `cti-scraper dry-run <id>` mengeluarkan item yang benar
- [ ] Fixture direkam, `expected_items.json` sudah dicek manual, `cti-scraper verify <id>` = OK
- [ ] `pytest tests/contract -k <id>` dan `test_scraper_labels.py` lolos; `ruff` bersih
- [ ] `id` final (tidak akan diubah), `source` unik dan bermakna
- [ ] `schedule` memakai `spread()`, `runtime` sesuai cara ambil, `rate_limit` wajar
- [ ] Tidak ada `try/except` yang menelan error, tidak ada `print` sisa debug
- [ ] Hanya file scraper + folder fixture yang berubah
- [ ] Setelah deploy: run pertama `ok`, item muncul (ingat cold start: 5 item terbaru; pakai `--prime` kalau tidak mau)

## Masalah umum saat menambah

| Gejala | Penyebab | Solusi |
|---|---|---|
| `scraper '<id>' gak kedaftar` | file di luar `cti_scrapers/`, class bukan subclass `BaseScraper`, atau `meta.id` beda | cek lokasi file dan `meta.id` |
| `ConfigError ... gak nulis meta sendiri` | subclass konkret tanpa `meta` | tambah `meta = ScraperMeta(...)` |
| `DuplicateScraperId` | `id` sudah dipakai file lain | ganti slug |
| `parse_error ... gak ada node di item_path` | feed Atom tapi `item_path` default RSS | set `item_path`/`link_attr` untuk Atom |
| `parse_error ... XML gak valid` | feed rusak/diblokir, kadang halaman challenge | `curl` URL-nya, cek isi; mungkin butuh `xml_fixups` atau situs memblokir bot |
| `fetch_error` 403/429 | situs memblokir UA/laju | turunkan `rate_limit`, cek apakah perlu `browser` |
| `empty` terus | selector salah, atau sumber memang sepi | bandingkan dengan `curl` isi halaman |
| Scraper baru tidak pernah jalan | `beat` belum di-restart | `docker compose up -d --build beat` |
| UI `/scrapers` tidak menampilkan scraper baru | `api` belum di-rebuild | rebuild `api` |
| Run pertama menghasilkan 5 artikel padahal tidak diinginkan | cold-start cap (normal) | pakai `--prime` sebelum dijadwalkan |
