"""APT Attack Simulation GitHub Monitor -- gantiin
`ScraperNews/githubAptTTPSimulation.py`.

Satu notice per commit BARU (kecuali yang cuma menyentuh `README.md` root):
ringkasan commit sebagai caption, dan patch (baris +/- saja) sebagai lampiran
`apt_ttp_update.txt` -- kanal `vendor_report`. Beda dari skrip lama:
  - Offset ditulis SEKALI di akhir run (`save_sha_offset(processed + new)`):
    run yang mati di tengah menghilangkan semua commit yang sudah terkirim dari
    catatan -> terkirim ulang. Dedup framework per commit, dicatat tiap notice.
  - Daftar file di caption dibatasi (commit besar melewati batas 4096 karakter
    Telegram, dan skrip lama menelan error-nya diam-diam).
  - Waktu tampilan WIB (UTC+7) dipertahankan.
"""

from __future__ import annotations

import datetime
import html
from collections.abc import Iterator
from typing import Any

from cti_scraper.base import ScrapeContext, ScraperMeta
from cti_scraper.families.github_commits import GithubCommitWatcher, commit_date
from cti_scraper.items import NoticeItem

_MAX_LISTED_FILES = 25


def _filtered_patch(patch: str) -> str:
    return "\n".join(line for line in patch.splitlines() if line.startswith(("+", "-")))


class AptTtpSimulation(GithubCommitWatcher):
    meta = ScraperMeta(
        id="apt_ttp_simulation",
        content_kind="vendor_research",
        source="APT TTP Simulation GitHub Monitor",
        schedule="47 * * * *",
        credential="github",
        max_items=10,
        tags=("migrated", "bespoke", "github"),
        legacy_script="githubAptTTPSimulation",
    )
    owner = "S3N4T0R-0X0"
    repo = "APT-Attack-Simulation"
    max_commits = 5

    def notices(
        self, ctx: ScrapeContext, summary: dict[str, Any], detail: dict[str, Any]
    ) -> Iterator[NoticeItem]:
        files = detail.get("files", [])
        if len(files) == 1 and files[0]["filename"] == "README.md":
            return

        sha = summary["sha"]
        commit = detail["commit"]
        authored = datetime.datetime.strptime(commit["author"]["date"], "%Y-%m-%dT%H:%M:%SZ")
        wib = (authored + datetime.timedelta(hours=7)).strftime("%B %d, %Y, %H:%M:%S")

        lines = [
            "=== <b>APT TTP SIMULATOR GITHUB MONITOR</b> ===",
            f"<b>Commit Message</b>: {html.escape(commit['message'])}",
            f"<b>Author</b>: {html.escape(commit['author']['name'])}",
            f"<b>Date</b>: {wib}",
            "<b>Files changed:</b>",
        ]
        for file in files[:_MAX_LISTED_FILES]:
            lines += [
                f"      Filename: {html.escape(file['filename'])}",
                f"      Status: {html.escape(file['status'])}",
                f"      Additions: {file['additions']}",
                f"      Deletions: {file['deletions']}",
            ]
        if len(files) > _MAX_LISTED_FILES:
            lines.append(f"      ... dan {len(files) - _MAX_LISTED_FILES} file lain")

        patches = []
        for file in files:
            patch = file.get("patch")
            body = _filtered_patch(patch) if patch else "No patch available"
            patches.append(f"\n--- PATCH for {file['filename']} ---\n{body}\n")

        yield NoticeItem(
            topic="vendor_report",
            text="\n".join(lines),
            key=sha,
            title=commit["message"].splitlines()[0][:120] if commit["message"] else sha,
            url=detail.get("html_url", ""),
            posted_on=commit_date(summary).date(),
            attachment_name="apt_ttp_update.txt",
            attachment_text="".join(patches),
        )
