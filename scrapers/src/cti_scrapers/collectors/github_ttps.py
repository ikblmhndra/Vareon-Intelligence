"""ThreatActors-TTPs (crocodyli) GitHub Monitor -- gantiin `ScraperNews/githubTTPs.py`.

Satu notice PER FILE yang berubah di tiap commit baru (kabari channel APT).
Beda dari skrip lama:
  - `exit()` begitu ketemu commit yang sudah pernah diproses -> commit LEBIH
    LAMA yang belum diproses (mis. gagal kirim kemarin) ikut terlewat. Dedup
    sekarang per (commit, file) oleh framework, jadi yang gagal kirim dicoba lagi.
  - Alert lewat `send_alert(msg, "group_name", "global")` = topik `apt`
    (grup non-kosong + berita global; lihat `cti_enrich.routing`).
  - Field dari GitHub di-`html.escape` (nama file ber-`&`/`<` bikin Telegram
    menolak seluruh pesan, dan skrip lama menelan errornya).
"""

from __future__ import annotations

import html
from collections.abc import Iterator
from typing import Any

from cti_scraper.base import ScrapeContext, ScraperMeta
from cti_scraper.families.github_commits import GithubCommitWatcher, commit_date
from cti_scraper.items import NoticeItem


class GithubTtps(GithubCommitWatcher):
    meta = ScraperMeta(
        id="github_ttps",
        content_kind="vendor_research",
        source="ThreatActors-TTPs GitHub Monitor",
        schedule="0 * * * *",
        credential="github",
        max_items=30,
        tags=("migrated", "bespoke", "github"),
        legacy_script="githubTTPs",
    )
    owner = "crocodyli"
    repo = "ThreatActors-TTPs"
    max_commits = 5

    def notices(
        self, ctx: ScrapeContext, summary: dict[str, Any], detail: dict[str, Any]
    ) -> Iterator[NoticeItem]:
        sha = summary["sha"]
        when = commit_date(summary)
        for file in detail.get("files", []):
            filename = file["filename"]
            status = file["status"]
            label = "NEW" if status == "added" else "MODIFIED"
            text = (
                f"=== <b>{label} TTP POSTED ON CROCODYLI GITHUB</b> ===\n"
                f"<b>Commit ID On</b>: {html.escape(sha)}\n"
                f"<b>Commited On</b>: {when}\n"
                f"<b>Filename</b>: {html.escape(filename)}\n"
                f"<b>Status</b>: {html.escape(status)}\n"
                f'<b>Github Link</b>: <a href="{html.escape(file["blob_url"], quote=True)}">Link</a>'
            )
            yield NoticeItem(
                topic="apt",
                text=text,
                key=f"{sha}:{filename}",
                title=f"{label} TTP: {filename}",
                url=file["blob_url"],
                posted_on=when.date(),
            )
