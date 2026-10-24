"""Blackorbird GitHub -- BESPOKE: subclass `BaseScraper` langsung, sumbernya
commit GitHub (`blackorbird/APT_REPORT`), bukan RSS/XPath. Nge-`yield`
`ArticleItem` biasa -- laporan yang di-upload di commit itu SECARA ISI
memang artikel (nama file + link + tanggal), cuma cara nemuinnya yang beda.

Bandingkan sama `ScraperNews/blackorbirdGithub.py` asli:
- Auth GitHub lewat header manual + token dari `config.yml` -- di sini
  `meta.credential="github"` yang urus (`Runner` nyuntik header SEBELUM
  `fetch()` dipanggil, lihat `cti_scraper.credentials` -- scraper ini gak
  pernah pegang token-nya sendiri).
- Dedup manual `offset/githubsha.txt` (dan lucu-nya file offset itu
  KEBAGI sama `githubUnit42.py`/`githubSophoslab.py` -- tiga scraper beda
  nulis SHA repo yang beda-beda ke satu file yang sama) -- gak dibutuhin
  lagi. `ArticleItem.dedup_key()` = hash URL, dan `DedupStore` udah
  namespace per `scraper_id` sendiri-sendiri (lihat dedup.py) -- kelas bug
  "offset file kebagi" itu terstruktur gak mungkin lagi kejadian.
- Telegram alert (`send_alert_report`) -- BUKAN tanggung jawab scraper,
  itu ranah `cti-alerts` (belum dibangun, fase selanjutnya).

Cuma cek commit TERBARU (`commits[0]`), sama kayak script lama -- bukan
loop N hari terakhir kayak `unit42_github.py` (family sama, tapi
perilakunya emang beda di source aslinya).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.errors import ParseError
from cti_scraper.items import ArticleItem

_REPO = "blackorbird/APT_REPORT"
_COMMITS_URL = f"https://api.github.com/repos/{_REPO}/commits"


def _parse_commit_date(raw: str) -> datetime:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise ParseError(f"tanggal commit gak sesuai format: {raw!r}") from e


class Blackorbird(BaseScraper):
    meta = ScraperMeta(
        id="blackorbird",
        content_kind="vendor_research",
        source="Blackorbird GitHub",
        schedule="47 * * * *",
        rate_limit="30/minute",
        credential="github",
        tags=("migrated", "bespoke"),
        legacy_label="NEW REPORT UPLOADED ON BLACKORBIRD GIT",
        legacy_script="blackorbirdGithub",
    )

    def fetch(self, ctx: ScrapeContext) -> Iterator[ArticleItem]:
        commits = ctx.http.get(_COMMITS_URL).json()
        if not commits:
            return

        sha = commits[0]["sha"]
        detail = ctx.http.get(f"{_COMMITS_URL}/{sha}").json()
        if detail.get("commit", {}).get("message") != "Add files via upload":
            return

        commit_date = _parse_commit_date(detail["commit"]["committer"]["date"])
        for file_detail in detail.get("files", []):
            filename = str(file_detail["filename"])
            parts = filename.split("/")
            title = parts[2] if len(parts) > 2 else filename
            yield ArticleItem(
                title=title, url=str(file_detail["raw_url"]), posted_on=commit_date.date()
            )
