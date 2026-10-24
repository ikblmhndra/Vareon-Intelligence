"""MITRE ATT&CK Release Monitor -- gantiin `ScraperNews/mitreGithub.py`.

Pantau `mitre-attack/attack-stix-data`. Commit rilis = pesan persis
`Update with ATT&CK vX.Y`; tiap file `<domain>-attack-X.Y.json` yang DITAMBAHKAN
diunduh dan diubah jadi changelog (objek yang dibuat <= 7 hari; lihat
`mitre_changelog.py`), dikirim ke `vendor_report` sebagai dokumen.

Beda dari skrip lama:
  - `requests.get(raw_url)` tanpa timeout (bundle STIX puluhan MB) -> `ctx.http`
    dengan `timeout_s` 180.
  - File offset ditulis di dalam loop file: commit dengan 3 file (enterprise/ics/
    mobile) yang gagal di file kedua sudah tercatat "selesai" setelah file pertama.
    Sekarang dedup per (commit, file).
  - Seluruh changelog gagal kalau satu objek kekurangan field (KeyError) -> lihat
    `mitre_changelog.py`.

Batas umur commit 7 hari sama seperti lama (`diff_date >= 7` dilewati).
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from typing import Any

from cti_scraper.base import ScrapeContext, ScraperMeta
from cti_scraper.errors import ParseError
from cti_scraper.families.github_commits import GithubCommitWatcher, commit_date
from cti_scraper.items import NoticeItem

from cti_scrapers.collectors.mitre_changelog import build_changes, render

_RELEASE_MESSAGE = re.compile(r"^update with att&ck v\d+\.\d+$")
_BUNDLE_FILE = re.compile(r".+-\d+\.\d+\.json$")
_VERSION = re.compile(r".+-(\d+\.\d+)\.json$")


class MitreGithub(GithubCommitWatcher):
    meta = ScraperMeta(
        id="mitre_github",
        content_kind="vendor_research",
        source="MITRE ATT&CK GitHub Monitor",
        schedule="15 * * * *",
        credential="github",
        timeout_s=180.0,
        max_items=6,
        tags=("migrated", "bespoke", "github"),
        legacy_script="mitreGithub",
    )
    owner = "mitre-attack"
    repo = "attack-stix-data"
    max_commits = 4
    max_age_days = 7

    def skip_commit(self, ctx: ScrapeContext, summary: dict[str, Any]) -> bool:
        if super().skip_commit(ctx, summary):
            return True
        message = str(summary["commit"]["message"]).lower()
        return _RELEASE_MESSAGE.fullmatch(message) is None

    def notices(
        self, ctx: ScrapeContext, summary: dict[str, Any], detail: dict[str, Any]
    ) -> Iterator[NoticeItem]:
        sha = summary["sha"]
        posted = summary["commit"]["committer"]["date"].replace("T", " ").replace("Z", "")
        for file in detail.get("files", []):
            filename = file["filename"]
            if file["status"] != "added" or not _BUNDLE_FILE.fullmatch(filename):
                continue

            raw_url = file["raw_url"]
            resp = ctx.http.get(raw_url)
            try:
                bundle = resp.json()
            except ValueError as e:
                raise ParseError(f"{raw_url}: bukan JSON STIX valid -- {e}") from e

            short_name = filename.split("/")[-1]
            match = _VERSION.fullmatch(short_name)
            version = match.group(1) if match else "unknown"
            changelog_text, summary_html = render(build_changes(bundle, now=ctx.now))

            text = (
                "=== <b>NEW VERSION OF MITRE ATT&amp;CK UPLOADED ON GIT</b> ===\n"
                f"<b>Report Name</b>: {html.escape(short_name)}\n"
                f"<b>Posted On</b>: {posted}\n"
                f'<b>Raw File URL</b>: <a href="{html.escape(raw_url, quote=True)}">Read Now</a>\n'
                f"{summary_html}"
            )
            yield NoticeItem(
                topic="vendor_report",
                text=text,
                key=f"{sha}:{filename}",
                title=f"MITRE ATT&CK {version}: {short_name}",
                url=raw_url,
                posted_on=commit_date(summary).date(),
                attachment_name=f"Mitre_ATTCK_{version}_Changelog.txt",
                attachment_text=changelog_text,
            )
