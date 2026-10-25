"""deepdarkCTI GitHub Monitor -- BESPOKE, subclass `BaseScraper` langsung.
Nge-`yield` `IocFeedItem` (Fase 5) -- SATU per commit di `fastfire/
deepdarkCTI` (daftar kuratif C2/IOC/phishing/ransomware/tor/darkweb),
gantiin `ScraperNews/deepdarkCTI.py`.

Bandingkan sama script lama:
- Auth GitHub lewat header manual + `cfg['github']['token']` -- di sini
  `meta.credential="github"` (pola sama `blackorbird.py`), scraper gak
  pernah pegang token-nya sendiri.
- Dedup `offset/deepdarkCTI_offset.txt` (list SHA manual) -- gak dibutuhin,
  `IocFeedItem.dedup_key()` = SHA commit, dedup framework yang urus.
- Ekstraksi IOC pake `iocExtractor.extract_iocs()` langsung (module lokal)
  -- di sini `cti_core.ioc.extractor.extract_iocs()` (Fase 5, SATU
  ekstraktor kanonik yang byte-identik sama fork asli ini; pindah dari
  `cti_enrich.ioc` ke `cti_core.ioc` Fase 7.3 Bagian 4, lihat docstring
  modulnya -- import di sini ikut nyesuain, gak ada perubahan perilaku).
- Upsert IOC (`dbMongo.upsert_ioc_from_feed`) + dual-write C2 feed
  (`dbMongo.upsert_threat_feed`) + alert Telegram (`send_alert_darkweb`) --
  SEMUA pindah ke sink `_ioc_feed_sink` (`cti_scraper/sinks.py`), `fetch()`
  cuma nge-yield data terstruktur (lihat prinsip `ScrapeContext`: gak ada
  Session/alert di sini).

Cuma cek 5 commit TERBARU (`pulls[:5]`) -- sama kayak script lama, BUKAN
window N hari kayak `unit42_github.py` (source asli emang pake COUNT bukan
tanggal buat scraper ini)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from cti_core.ioc.extractor import extract_iocs
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import IocFeedItem
from cti_scraper.schedule import spread

_OWNER = "fastfire"
_REPO = "deepdarkCTI"
_COMMITS_URL = f"https://api.github.com/repos/{_OWNER}/{_REPO}/commits"
_MAX_COMMITS = 5

# 6 kategori ASLI `deepdarkCTI.py` lama (`_IOC_PATH_PREFIXES = ("c2/",
# "ioc/", "phishing/", "ransomware/", "tor/", "darkweb/")`) -- asumsinya
# repo punya SUBFOLDER per kategori. Dikonfirmasi lewat GitHub Contents API
# (2026-09-17): `fastfire/deepdarkCTI` SEKARANG flat -- `phishing.md`,
# `ransomware_gang.md`, dst langsung di root, gak ada folder `phishing/`
# sama sekali. Filter path lama gak PERNAH match struktur ini (kemungkinan
# udah lama inert bahkan di produksi lama, sebelum repo-nya direstrukturisasi).
# Keputusan user (Fase 5): sesuaikan ke skema flat -- cocokin kategori
# dari KATA di nama file (dipisah "_"), bukan folder prefix. 6 kategori
# tetap SAMA PERSIS, cuma cara nemuin match-nya yang berubah.
_IOC_CATEGORIES = ("c2", "ioc", "phishing", "ransomware", "tor", "darkweb")
# Nilai kanan = `IOC.type` KANONIK Postgres (Fase 2), BUKAN nama
# `hash_sha256`/dst yang dipakai `dbMongo.upsert_ioc_from_feed` lama --
# itu penamaan spesifik Mongo, gak ada padanannya di skema baru.
_IOC_FIELD_TYPE_MAP = {
    "ips": "ip",
    "domains": "domain",
    "urls": "url",
    "urls_with_path": "url",
    "sha256": "sha256",
    "sha1": "sha1",
    "md5": "md5",
    "emails": "email",
}


def _category_for(filename: str) -> str | None:
    """`filename` = path penuh dari GitHub API (biasanya cuma nama file di
    root repo skema flat sekarang, mis. "ransomware_gang.md"). Match kata
    di stem (dipisah "_"/"-", extension dibuang) lawan 6 kategori asli --
    "ransomware_gang.md" -> {"ransomware","gang"} -> match "ransomware".
    File yang gak jelas kategorinya (mis. "markets.md", "forum.md") sengaja
    DILEWATIN, bukan ditebak masuk kategori mana -- konsisten sama filosofi
    "skip daripada nebak" (`new_cve.py`, Fase 4)."""
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    words = set(stem.replace("-", "_").split("_"))
    for category in _IOC_CATEGORIES:
        if category in words:
            return category
    return None


def _added_lines(patch: str) -> str:
    return "\n".join(
        line[1:].strip()
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _patch_preview(patch: str) -> str:
    """Port format tampilan `deepdarkCTI.py:122-128` -- baris +/- doang,
    '||' disatuin dulu (biar gak kena replace dobel jadi ' |  | '), '|'
    diganti ' | ' buat kebacaan, 3 karakter terakhir tiap baris dibuang
    (disalin apa adanya dari source asli, termasuk yang keliatan ganjil ini)."""
    lines = []
    for line in patch.splitlines():
        if line.startswith("+") or line.startswith("-"):
            fixed = line.replace("||", "|").replace("|", " | ")
            lines.append(fixed[:-3] if len(fixed) > 3 else fixed)
    return "\n".join(lines)


class DeepDarkCti(BaseScraper):
    meta = ScraperMeta(
        id="deepdark_cti",
        content_kind="vendor_research",
        source="deepdarkCTI GitHub Monitor",
        schedule=spread("0 */6 * * *", "deepdark_cti"),
        credential="github",
        tags=("migrated", "bespoke", "ioc"),
        legacy_label="DEEPDARKCTI GITHUB MONITOR",
        legacy_script="deepdarkCTI",
    )

    def fetch(self, ctx: ScrapeContext) -> Iterator[IocFeedItem]:
        commits = ctx.http.get(_COMMITS_URL).json()
        for commit_summary in commits[:_MAX_COMMITS]:
            sha = commit_summary["sha"]
            detail = ctx.http.get(f"{_COMMITS_URL}/{sha}").json()
            commit = detail["commit"]
            commit_date = datetime.strptime(commit["author"]["date"], "%Y-%m-%dT%H:%M:%SZ")

            files_changed: list[dict[str, Any]] = []
            all_iocs: list[dict[str, str]] = []
            for file_detail in detail.get("files", []):
                filename = file_detail["filename"]
                patch = file_detail.get("patch")
                files_changed.append(
                    {
                        "filename": filename,
                        "additions": file_detail.get("additions", 0),
                        "deletions": file_detail.get("deletions", 0),
                        "patch_preview": _patch_preview(patch) if patch else "",
                    }
                )

                category = _category_for(filename)
                if not category or not patch:
                    continue
                added = _added_lines(patch)
                if not added:
                    continue
                extracted = extract_iocs(added)
                for field_name, ioc_type in _IOC_FIELD_TYPE_MAP.items():
                    for value in extracted.get(field_name, []):
                        all_iocs.append({"type": ioc_type, "value": value, "category": category})

            yield IocFeedItem(
                commit_sha=sha,
                commit_message=commit["message"],
                commit_author=commit["author"]["name"],
                commit_date=commit_date,
                commit_url=detail["html_url"],
                files_changed=files_changed,
                iocs=all_iocs,
            )
