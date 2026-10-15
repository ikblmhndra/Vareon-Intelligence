"""CVE Tracker (NVD + Tenable + MITRE) -- BESPOKE, subclass `BaseScraper`
langsung. Nge-`yield` `CveItem` per (CVE, client) pasangan -- satu CVE bisa
relevan buat lebih dari satu client (lihat `reference_data="techstack_by_client"`).

Bandingkan sama `ScraperNews/newCveThreat.py` asli (391 baris):
- Bikin `MongoClient` LANGSUNG dari config buat preload state dedup DAN
  buat baca techstack -- dua-duanya kelas bug yang `ScrapeContext` sengaja
  cegah sekarang (lihat docstring-nya). Techstack sekarang lewat
  `ctx.reference` (`Runner` yang query, `fetch()` cuma baca data jadi).
- NVD API key gak PERNAH kepake di script lama (field-nya ada di config,
  tapi gak ada satu pun `apiKey` di header/query) -- rate limit publik
  5 req/30dtk. Di sini `meta.credential="nvd"` beneran masang header
  `apiKey`, naik ke 50 req/30dtk.
- `time.sleep(10)`/`time.sleep(15)` manual antar request -- gak
  dibutuhin lagi, `meta.rate_limit` (token bucket per-domain) udah
  nanganin throttle-nya.
- Dedup `is_new_and_mark`-style DIGANTI: `dedup_key()` di-override return
  `None` (skip dedup framework sepenuhnya) -- CVE HARUS di-upsert ulang
  tiap run walau udah pernah keliatan, karena MITRE bisa update skor/
  referensi/affected-version-nya kapan aja. Script lama juga selalu upsert
  ulang (cuma skip ALERT-nya kalau `cve_modified_date` gak berubah, dan
  alert itu di luar scope scraper -- lihat cti-alerts, belum dibangun).
- **Bug lama gak ikut di-port**: `severity_string` di skrip asli di-set
  DI DALAM loop metrics, gak di-reset di awal tiap CVE -- kalau CVE
  berikutnya punya `metrics` list KOSONG (bukan KeyError, jadi gak
  ke-`except`), `severity_string` bocor bawa nilai dari CVE SEBELUMNYA.
  Di sini `severity` selalu direset `None` per kandidat.
- Telegram alert + email (`cveEmailAutomation`) -- BUKAN tanggung jawab
  scraper, itu ranah `cti-alerts` (belum dibangun).
- **Techstack harus cocok dengan produk yang terdampak**: `keywordSearch` NVD cuma mencocokkan
  kata di deskripsi mana pun, jadi CVE Zabbix yang menyebut "MariaDB" ikut tercatat sebagai
  tech `mariadb` (affected-nya "Zabbix"), CVE Plane yang menyebut "GitLab OAuth" jadi tech `gitlab`,
  dst. Sekarang kandidat hanya lolos kalau nama tech muncul di vendor/product/packageName/CPE
  record MITRE (lihat `relevant_techs`). Satu CVE juga dikelompokkan per `cve_id` -- dulu `seen`
  global membuat CVE yang kena beberapa tech menempel ke tech pertama yang kebetulan ketemu.
- **`max_items` tidak boleh membuang CVE diam-diam** (prod 2026-10-15: override `max_items=100`,
  tiap run FOUND=100 persis berstatus `ok`, CVE Palo Alto -- huruf "p" -- tak pernah tercatat).
  Dulu kandidat diproses menurut urutan `techstack` (abjad) lalu `return` begitu cap tercapai, jadi
  tech di belakang abjad kelaparan setiap kali tech awal ramai. Sekarang kandidat diproses
  round-robin antar tech (`_fair_order`) dan run yang berhenti karena cap ditandai `partial`
  + warning `cve_max_items_reached` (lihat `_report_cap_reached`).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import quote, quote_plus

import lxml.html
from cti_core.cve_record import (
    MitreDetail,
    affected_products,  # noqa: F401  (re-ekspor: dipakai tools/ops/reconcile_cve_tech.py)
    mitre_datetime,  # noqa: F401  (re-ekspor: dipakai tools/ops/backfill_cve_published_at.py)
    parse_cve_record,
)
from cti_core.tech_match import (
    mentions,
    relevant_techs,
    usable_products,  # noqa: F401  (re-ekspor: dipakai tools/ops/reconcile_cve_tech.py)
)
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.errors import ParseError, ScraperError
from cti_scraper.items import CveItem, Item
from cti_scraper.schedule import spread

from cti_scrapers.feeds._pacing import get_waiting

_NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_TENABLE_URL = "https://www.tenable.com/cve/search"
_MITRE_URL = "https://cveawg.mitre.org/api/cve"


class NewCve(BaseScraper):
    meta = ScraperMeta(
        id="new_cve",
        source="NVD/Tenable CVE Tracker",
        schedule=spread("0 * * * *", "new_cve"),
        rate_limit="60/minute",
        max_items=300,  # fan-out per client bisa ngalahin 50 default gampang
        credential="nvd",
        reference_data=("techstack", "techstack_by_client"),
        tags=("migrated", "bespoke", "cve"),
        legacy_label="NEW CVE",
        legacy_script="newCveThreat",
    )

    def dedup_key(self, item: Item) -> str | None:
        """Selalu upsert ulang -- lihat penjelasan di docstring modul."""
        return None

    def fetch(self, ctx: ScrapeContext) -> Iterator[CveItem]:
        tech_list: list[str] = ctx.reference["techstack"]
        tech_by_client: dict[str, list[str]] = ctx.reference["techstack_by_client"]
        if not tech_list:
            return

        # Kunci = nama ASLI techstack ("palo alto"), sama dengan `cand["tech"]`. Bentuk ter-encode
        # ("palo%20alto" / "palo+alto") HANYA untuk URL -- kandidat yang membawanya tidak pernah
        # cocok dengan peta ini dan CVE-nya dibuang diam-diam (ketemu di staging: 4 dari 33
        # techstack bernama multi-kata, termasuk Palo Alto dan Microsoft 365, tak pernah dapat CVE).
        tech_to_clients: dict[str, list[str]] = {}
        for client_id, techs in tech_by_client.items():
            for tech in techs:
                tech_to_clients.setdefault(tech.strip(), []).append(client_id)

        # Satu CVE = satu kandidat, membawa SEMUA tech yang memunculkannya (NVD/Tenable).
        candidates: dict[str, dict[str, Any]] = {}
        self._nvd_candidates(ctx, tech_list, candidates)
        self._tenable_candidates(ctx, tech_list, candidates)

        tech_order = {tech.strip(): i for i, tech in enumerate(tech_list)}
        ordered = self._fair_order(candidates, tech_order)
        found = 0
        for pos, cand in enumerate(ordered):
            if found >= self.meta.max_items:
                self._report_cap_reached(ctx, ordered[pos:], tech_order)
                return

            techs = [t for t in cand["techs"] if t in tech_to_clients]
            if not techs:
                ctx.log.warning(
                    "cve_candidate_no_client_match", tech=cand["techs"], cve_id=cand["id"]
                )
                continue

            detail = self._mitre_detail(ctx, cand)
            relevant = relevant_techs(techs, cand["summary"], detail.products)
            if not relevant:
                # Kata kunci NVD/Tenable ketemu di deskripsi, tapi produk terdampaknya lain
                # (CVE Zabbix yang menyebut MariaDB) -- bukan CVE-nya techstack ini.
                ctx.log.info(
                    "cve_candidate_tech_not_affected",
                    cve_id=cand["id"],
                    techs=techs,
                    products=detail.products[:5],
                )
                continue

            # Satu baris per (CVE, client) -- kalau satu client punya beberapa tech yang kena,
            # pakai yang paling awal menurut abjad (urutan `techstack` di reference data) biar deterministik.
            client_tech: dict[str, str] = {}
            for tech in sorted(relevant, key=tech_order.__getitem__):
                for client_id in tech_to_clients[tech]:
                    client_tech.setdefault(client_id, tech)

            for client_id, tech in client_tech.items():
                if found >= self.meta.max_items:
                    # Kandidat ini baru sebagian client yang tercatat -- ikut dihitung sisa.
                    self._report_cap_reached(ctx, ordered[pos:], tech_order)
                    return
                found += 1
                yield CveItem(client_id=client_id, tech=tech, **detail.fields)

    @staticmethod
    def _fair_order(
        candidates: dict[str, dict[str, Any]], tech_order: dict[str, int]
    ) -> list[dict[str, Any]]:
        """Urutan proses kandidat: round-robin antar tech, bukan tech demi tech.

        `candidates` terisi menurut urutan `techstack` (abjad), jadi diproses apa adanya cap
        `max_items` selalu menghantam tech paling belakang (palo alto, proofpoint, splunk, ...)
        ketika tech awal (fortinet, gitlab, ...) ramai. Di sini tiap putaran mengambil satu
        kandidat dari antrean tiap tech (urutan antar tech tetap `techstack`, urutan dalam satu
        tech tetap urutan NVD/Tenable), sehingga bila cap memotong run, sisa yang tak terproses
        tersebar tipis di semua tech -- bukan satu huruf yang hilang total. Kandidat yang dibawa
        beberapa tech cuma diproses sekali (di antrean tech yang lebih dulu mengambilnya); `cve_id`
        dan pemilihan tech per client (abjad, di `fetch`) tidak berubah.
        """
        queues: dict[str, list[dict[str, Any]]] = {}
        for cand in candidates.values():
            for tech in cand["techs"]:
                queues.setdefault(tech, []).append(cand)

        techs = sorted(queues, key=tech_order.__getitem__)
        ordered: list[dict[str, Any]] = []
        taken: set[str] = set()
        for depth in range(max(map(len, queues.values()), default=0)):
            for tech in techs:
                if depth < len(queues[tech]) and queues[tech][depth]["id"] not in taken:
                    cand = queues[tech][depth]
                    taken.add(cand["id"])
                    ordered.append(cand)
        return ordered

    def _report_cap_reached(
        self, ctx: ScrapeContext, remaining: list[dict[str, Any]], tech_order: dict[str, int]
    ) -> None:
        """`fetch()` berhenti karena `max_items`, bukan karena kandidat habis: log + tandai run
        `partial` supaya control plane tidak menampilkan `ok`. `remaining` itu batas ATAS CVE yang
        tak terproses -- sebagian mungkin akan dibuang gate relevansi teks kalau diperiksa."""
        pending_techs = sorted(
            {tech for cand in remaining for tech in cand["techs"]}, key=tech_order.__getitem__
        )
        ctx.log.warning(
            "cve_max_items_reached",
            max_items=self.meta.max_items,
            remaining_candidates=len(remaining),
            first_tech=pending_techs[0],
            pending_techs=pending_techs,
        )
        ctx.mark_partial(
            f"max_items={self.meta.max_items} tercapai; {len(remaining)} kandidat CVE belum "
            f"diproses (tech pertama yang terdampak: {pending_techs[0]})"
        )

    @staticmethod
    def _add_candidate(
        candidates: dict[str, dict[str, Any]], cve_id: str, tech: str, link: str, summary: str
    ) -> None:
        cand = candidates.setdefault(
            cve_id, {"id": cve_id, "link": link, "summary": summary, "techs": []}
        )
        if tech not in cand["techs"]:
            cand["techs"].append(tech)

    def _nvd_candidates(
        self, ctx: ScrapeContext, tech_list: list[str], candidates: dict[str, dict[str, Any]]
    ) -> None:
        now_str = ctx.now.strftime("%Y-%m-%dT%H:%M:%S.000")
        start_str = (ctx.now - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S.000")

        for tech in tech_list:
            tech_enc = quote(tech.strip(), safe="")
            # `ctx.now` itu UTC naive, jadi offset-nya +00:00. Dulu `+07:00`: jam UTC dilabeli WIB,
            # `pubEndDate` mundur 7 jam dan CVE yang baru terbit telat tercatat.
            url = (
                f"{_NVD_URL}?keywordSearch={tech_enc}"
                f"&pubStartDate={start_str}%2B00:00&pubEndDate={now_str}%2B00:00"
            )
            data = get_waiting(ctx, url).json()

            for cve in data.get("vulnerabilities", []):
                cve_id = cve["cve"]["id"]
                summary = next(
                    (d["value"] for d in cve["cve"].get("descriptions", []) if d["lang"] == "en"),
                    "",
                )
                self._add_candidate(
                    candidates,
                    cve_id,
                    tech.strip(),
                    f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                    summary,
                )

    def _tenable_candidates(
        self, ctx: ScrapeContext, tech_list: list[str], candidates: dict[str, dict[str, Any]]
    ) -> None:
        now_str = ctx.now.strftime("%Y-%m-%d")
        start_str = (ctx.now - timedelta(days=8)).strftime("%Y-%m-%d")

        for tech in tech_list:
            tech_enc = quote_plus(tech.strip())
            url = (
                f"{_TENABLE_URL}?q={tech_enc}+AND+publication_date%3A"
                f"%28%5B{start_str}+TO+{now_str}%5D%29&sort=newest&page=1"
            )
            resp = get_waiting(ctx, url)
            tree = lxml.html.fromstring(resp.content)

            for i in range(1, 7):
                row = (
                    "/html/body/div/div/div[2]/div/div/div[2]/div/div/div[3]"
                    f"/div/section/div/div/table/tbody/tr[{i}]"
                )
                id_nodes = tree.xpath(f"{row}/td[1]/a/text()")
                sum_nodes = tree.xpath(f"{row}/td[2]/text()")
                if not id_nodes or not sum_nodes:
                    continue
                cve_id, cve_sum = id_nodes[0], sum_nodes[0]

                # Tenable kadang balikin hasil yang gak beneran nyebut tech-nya --
                # validasi tech-nya ada literal di summary sebelum dipakai.
                if not mentions(tech, cve_sum):
                    continue
                self._add_candidate(
                    candidates,
                    cve_id,
                    tech.strip(),
                    f"https://www.tenable.com/cve/{cve_id}",
                    cve_sum,
                )

    def _mitre_detail(self, ctx: ScrapeContext, cand: dict[str, Any]) -> MitreDetail:
        try:
            data = get_waiting(ctx, f"{_MITRE_URL}/{cand['id']}").json()
        except ScraperError:
            # `RateLimited` / `TransientFetchError` dari `ctx.http` sudah diklasifikasi framework
            # (status run `rate_limited` / `fetch_error`, bisa dicoba lagi). Dibungkus jadi
            # `ParseError` (dulu: `except Exception`) mereka tampil sebagai "situs berubah"
            # (`degraded`) -- ketemu di rehearsal beat staging 10.G: `new_cve` kena batas 60/mnt
            # domain MITRE tapi dilaporkan parse_error.
            raise
        except Exception as e:  # MITRE kadang balikin bentuk gak terduga
            raise ParseError(f"MITRE detail gak kebaca buat {cand['id']}: {e}") from e

        return parse_cve_record(data, cve_id=cand["id"], link=cand["link"], summary=cand["summary"])
