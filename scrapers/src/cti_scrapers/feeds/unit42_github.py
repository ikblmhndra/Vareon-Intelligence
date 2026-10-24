"""Unit42 GitHub -- BESPOKE, family sama kayak `blackorbird.py` (commit
GitHub, `yield ArticleItem`, header auth lewat `meta.credential="github"`).
Id-nya SENGAJA "unit42_github", bukan "unit42" -- itu udah kepake scraper
RSS `unit42Threat` (sumber beda, blog resmi Unit42) yang udah ke-generate
duluan. Dua-duanya boleh jalan bareng, sumbernya emang beda.

Beda dari `blackorbird.py`: loop SEMUA commit dalam 5 hari terakhir
(bukan cuma commit terbaru), match `ScraperNews/githubUnit42.py` asli.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.errors import ParseError
from cti_scraper.items import ArticleItem

_REPO = "PaloAltoNetworks/Unit42-timely-threat-intel"
_COMMITS_URL = f"https://api.github.com/repos/{_REPO}/commits"


def _parse_commit_date(raw: str) -> datetime:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise ParseError(f"tanggal commit gak sesuai format: {raw!r}") from e


class Unit42Github(BaseScraper):
    meta = ScraperMeta(
        id="unit42_github",
        content_kind="vendor_research",
        source="Unit42 GitHub",
        schedule="16 * * * *",
        rate_limit="30/minute",
        credential="github",
        tags=("migrated", "bespoke"),
        legacy_label="NEW REPORT UPLOADED ON UNIT42 GIT",
        legacy_script="githubUnit42",
    )

    def fetch(self, ctx: ScrapeContext) -> Iterator[ArticleItem]:
        commits = ctx.http.get(_COMMITS_URL).json()
        # ctx.now naive (default produksi, `datetime.utcnow()`) vs aware
        # (verify --record pakai `datetime.now(UTC)`) -- keduanya jam
        # dinding UTC yang sama, cuma beda ke-tag. Samain ke naive biar bisa
        # dikurangin lawan commit_date (dari strptime, selalu naive).
        now = ctx.now.replace(tzinfo=None) if ctx.now.tzinfo is not None else ctx.now

        for commit in commits:
            commit_date = _parse_commit_date(commit["commit"]["committer"]["date"])
            if (now - commit_date).days > 5:
                continue

            detail = ctx.http.get(f"{_COMMITS_URL}/{commit['sha']}").json()
            if detail.get("commit", {}).get("message") != "Add files via upload":
                continue

            for file_detail in detail.get("files", []):
                filename = str(file_detail["filename"])
                parts = filename.split("/")
                title = parts[2] if len(parts) > 2 else filename
                yield ArticleItem(
                    title=title, url=str(file_detail["raw_url"]), posted_on=commit_date.date()
                )
