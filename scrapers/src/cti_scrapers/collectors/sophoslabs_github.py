"""Sophos Labs IoCs GitHub Monitor -- gantiin `ScraperNews/githubSophoslab.py`.

Laporan baru = commit ber-pesan persis "Add files via upload". Satu notice PER
FILE (kanal `vendor_report`). Beda dari skrip lama:
  - Pesan dibangun di dalam loop file tapi DIKIRIM di luarnya -> commit yang
    mengunggah beberapa laporan cuma mengabarkan yang TERAKHIR. Sekarang tiap file.
  - `requests.get(API_URL/<sha>)` tanpa header auth -> kena limit anonim 60/jam.
    Sekarang lewat `ctx.http` ber-token.
  - `exit()` di commit yang sudah diproses (menghentikan seluruh run) -> dedup
    per (commit, file) oleh framework.
  - Batas umur lama: `diff_date > 5` dilewati => `max_age_days = 6` di sini
    (framework melewati commit yang `>= max_age_days`).
"""

from __future__ import annotations

import html
from collections.abc import Iterator
from typing import Any

from cti_scraper.base import ScrapeContext, ScraperMeta
from cti_scraper.families.github_commits import GithubCommitWatcher, commit_date
from cti_scraper.items import NoticeItem

_UPLOAD_MESSAGE = "Add files via upload"


class SophoslabsGithub(GithubCommitWatcher):
    meta = ScraperMeta(
        id="sophoslabs_github",
        content_kind="vendor_research",
        source="Sophoslabs GitHub Monitor",
        schedule="47 * * * *",
        credential="github",
        max_items=30,
        tags=("migrated", "bespoke", "github"),
        legacy_script="githubSophoslab",
    )
    owner = "sophoslabs"
    repo = "IoCs"
    max_commits = 30  # skrip lama membaca satu halaman penuh (30 commit)
    max_age_days = 6

    def notices(
        self, ctx: ScrapeContext, summary: dict[str, Any], detail: dict[str, Any]
    ) -> Iterator[NoticeItem]:
        if detail.get("commit", {}).get("message") != _UPLOAD_MESSAGE:
            return
        sha = summary["sha"]
        posted = summary["commit"]["committer"]["date"]
        for file in detail.get("files", []):
            filename = file["filename"]
            parts = filename.split("/")
            name = parts[2] if len(parts) > 2 else filename
            raw_url = file["raw_url"]
            text = (
                "=== <b>NEW REPORT UPLOADED ON SOPHOSLAB GIT</b> ===\n"
                f"<b>Report Name</b>: {html.escape(name)}\n"
                f"<b>Posted On</b>: {posted.replace('T', ' ').replace('Z', '')}\n"
                f'<b>Report URL</b>: <a href="{html.escape(raw_url, quote=True)}">Read Now</a>'
            )
            yield NoticeItem(
                topic="vendor_report",
                text=text,
                key=f"{sha}:{filename}",
                title=f"Sophoslabs report: {name}",
                url=raw_url,
                posted_on=commit_date(summary).date(),
            )
