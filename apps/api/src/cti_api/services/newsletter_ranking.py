"""Peringkat artikel kandidat newsletter -- fungsi MURNI (tanpa DB, tanpa jam), ROADMAP #22, PR 7.

Masukan: artikel-artikel satu jendela (`Candidate`) dengan fakta yang SUDAH dibaca dari DB.
Keluaran: per artikel yang terpilih, skor, section, tier, peringkat, dan ALASAN (kode mesin + teks
Inggris pendek) supaya composer bisa menunjukkan kenapa artikel itu disarankan. Pembangunan
kandidat dari DB ada di `newsletter_suggestion.py`; di sini hanya urusan menilai dan menyusun,
supaya semuanya bisa dites dengan kandidat buatan tangan.

Aturan yang SENGAJA begitu:

- **Satu section per artikel**: Indonesia kalau `ID` ada di negara victim ATAU mentioned, selain itu
  Asia Pacific kalau salah satu negaranya ada di `APAC_COUNTRY_CODES`, selain itu Global. Negara
  `actor` tidak dihitung (aturan dari rencana). Catatan: role `mentioned` di DB sudah memuat negara
  victim dan actor (`persist._country_roles`), jadi korban AS dengan pelaku dari China jatuh ke
  Asia Pacific. Itu perilaku aturan yang disepakati, bukan salah hitung di sini.
- **Highlights itu TIER, bukan section**: tiga artikel teratas secara keseluruhan. Artikel yang
  masuk Highlights tidak diulang di section-nya (satu artikel, satu item), tapi `section`-nya tetap
  diisi supaya composer tahu ke mana ia kembali kalau analis menurunkannya. Sisanya per section:
  `MAX_FULL_PER_SECTION` pertama kartu penuh, `MAX_COMPACT_PER_SECTION` berikutnya baris compact.
  Batasnya diimpor dari `schemas.newsletter` (PR 5), bukan disalin.
- **Tanpa alasan = tidak disarankan**: kandidat yang tidak punya satu pun sinyal tidak dimasukkan,
  jadi bulan yang sepi tidak "diisi" artikel tanpa dasar sampai batas jumlah.
- **Duplikat runtuh jadi satu pilihan**, lewat `dedup.find_dedup_groups` (bukan rutin kemiripan
  baru). Yang bertahan anggota grup dengan skor tertinggi, karena kandidat diurutkan menurut skor
  sebelum dedup (kanonik = yang pertama). Banyaknya sumber lain yang melaporkan cerita yang sama
  dihitung sebagai sinyal liputan; artikel dari sumber yang sama (mis. seri mingguan) tidak
  menambah liputan.
- **Urutan pasti**: skor terbesar, lalu `posted_on` terbaru, lalu `article_id` terkecil. Hasilnya
  tidak bergantung urutan masukan.

Bobot di bawah adalah NILAI AWAL yang akan disetel setelah edisi pertama (sama seperti batas
tier); hanya urutan relatifnya yang bermakna. Tiap poin selalu punya satu alasan yang menjelaskannya
(`sum(poin alasan) == skor`), jadi tidak ada skor yang tidak bisa dijelaskan ke analis."""

from __future__ import annotations

import datetime
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from cti_core.regions import APAC_COUNTRY_CODES
from cti_core.tech_match import matching_names

from cti_api.schemas.newsletter import (
    MAX_COMPACT_PER_SECTION,
    MAX_FULL_PER_SECTION,
    MAX_HIGHLIGHTS,
    SectionName,
    TierName,
)
from cti_api.services.dedup import find_dedup_groups
from cti_api.services.newsletter_edition import SECTIONS
from cti_api.services.source_score import get_source_reliability

SECTION_INDONESIA: SectionName = "indonesia"
SECTION_APAC: SectionName = "apac"
SECTION_GLOBAL: SectionName = "global_news"
"""Nama section = `newsletter_edition.SECTIONS` (nama field request tier); test menjaga
kesamaannya."""

TIER_HIGHLIGHT: TierName = "highlight"
TIER_FULL: TierName = "full"
TIER_COMPACT: TierName = "compact"

INDONESIA = "ID"

DEDUP_POOL_PER_SECTION = 100
"""Hanya sebanyak ini kandidat teratas DI TIAP SECTION yang masuk dedup. `find_dedup_groups`
membandingkan semua pasangan (kuadrat) dan sebulan artikel bisa ribuan, jadi masukannya dibatasi
(paling banyak 3 x 100). Per section, bukan global: kuota tier juga per section, dan pool global
bisa dipenuhi satu section (mis. 300 artikel Indonesia berskor tinggi) sehingga section lain
kosong padahal punya kandidat. Satu section hanya butuh 4 + 15 pilihan (dan 3 highlight yang
pasti ada di 3 teratas section-nya), jadi 100 masih menyisakan ruang untuk puluhan duplikat."""

# ── Bobot (nilai awal, lihat docstring modul) ───────────────────────────────────────────────────

POINTS_KEV = 30
POINTS_POC = 10
POINTS_CONFIRMED_INCIDENT = 20
POINTS_MONITORED_TECH = 20
POINTS_CLIENT_COUNTRY = 15
POINTS_INDONESIA_VICTIM = 25
POINTS_INDONESIA_MENTIONED = 12
POINTS_APAC_VICTIM = 8
POINTS_APAC_MENTIONED = 4
"""Urutan tegas: Indonesia korban > Indonesia disebut > korban APAC lain > APAC lain disebut.
Hanya satu dari keempatnya yang berlaku per artikel (yang paling spesifik)."""
POINTS_PER_RELATED_ARTICLE = 3
POINTS_COVERAGE_MAX = 15
POINTS_SOURCE = {"A": 8, "B": 5, "C": 2}
"""Grade Admiralty `source_score.get_source_reliability`; D/E dan F ("tidak bisa dinilai") 0."""
CONFIDENCE_FLOOR = 50
POINTS_CONFIDENCE_MAX = 12
"""`confidence_score` 0-100: di bawah `CONFIDENCE_FLOOR` tidak menambah apa pun, di atasnya naik
linear sampai `POINTS_CONFIDENCE_MAX` di 100."""

_LISTED = 3
"""Maksimum nama/id yang disebut di teks alasan; sisanya "(+N more)"."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """Satu artikel kandidat. Semua field selain `article_id` punya nilai netral, jadi test cukup
    mengisi yang relevan. `article_id` harus unik di satu panggilan.

    `kev_cves`/`poc_cves`: CVE yang disebut artikel dan berstatus KEV / punya PoC publik (dibaca
    dari `cve_tracker` oleh service). `cluster_size`: banyaknya artikel dalam kampanye yang memuat
    artikel ini di jendela, 1 kalau tidak ada. Sisanya fakta artikel apa adanya."""

    article_id: int
    title: str = ""
    source: str = ""
    posted_on: datetime.date | None = None
    confidence_score: int | None = None
    confirmed_incident: bool = False
    victim_countries: tuple[str, ...] = ()
    mentioned_countries: tuple[str, ...] = ()
    kev_cves: tuple[str, ...] = ()
    poc_cves: tuple[str, ...] = ()
    cluster_size: int = 1


@dataclass(frozen=True, slots=True)
class Reason:
    """Satu alasan. `code` stabil (untuk badge di UI), `text` Inggris pendek untuk dibaca analis,
    `points` sumbangannya ke skor (tidak disimpan ke suggestion; dipakai untuk mengurutkan dan
    membuktikan bahwa skor = jumlah alasan)."""

    code: str
    text: str
    points: int


@dataclass(frozen=True, slots=True)
class RankedArticle:
    """Satu pilihan akhir. `rank` = urutan 1-based di seluruh pilihan (skor terbesar = 1); di dalam
    satu section dan tier, urutan tampil = urutan `rank`. `reasons` urut dari sumbangan terbesar."""

    article_id: int
    score: int
    section: SectionName
    tier: TierName
    rank: int
    reasons: tuple[Reason, ...]

    def to_item(self) -> dict[str, Any]:
        """Bentuk yang disimpan di `newsletter_suggestions.items` dan dikirim API."""
        return {
            "article_id": self.article_id,
            "section": self.section,
            "tier": self.tier,
            "rank": self.rank,
            "reasons": [{"code": r.code, "text": r.text} for r in self.reasons],
        }


@dataclass(frozen=True, slots=True)
class _Context:
    client_countries: frozenset[str]
    monitored_techs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Scored:
    candidate: Candidate
    section: SectionName
    score: int
    reasons: tuple[Reason, ...]


def _codes(values: Iterable[str]) -> frozenset[str]:
    return frozenset(v.strip().upper() for v in values if v and v.strip())


def _distinct_names(names: Iterable[str]) -> tuple[str, ...]:
    """Nama tanpa yang kosong dan tanpa duplikat beda huruf besar-kecil ("Fortinet" dari satu
    client dan "fortinet" dari client lain), urutan tetap."""
    kept: dict[str, str] = {}
    for name in sorted({n.strip() for n in names if n.strip()}, key=lambda n: (n.casefold(), n)):
        kept.setdefault(name.casefold(), name)
    return tuple(kept.values())


def _listing(items: Sequence[str]) -> str:
    shown = ", ".join(items[:_LISTED])
    return f"{shown} (+{len(items) - _LISTED} more)" if len(items) > _LISTED else shown


def _section(victims: frozenset[str], mentioned: frozenset[str]) -> SectionName:
    countries = victims | mentioned
    if INDONESIA in countries:
        return SECTION_INDONESIA
    if countries & APAC_COUNTRY_CODES:
        return SECTION_APAC
    return SECTION_GLOBAL


def _grade(source: str) -> str:
    """Grade A-F. Sumber kosong dijaga di sini: `get_source_reliability("")` cocok ke entri tabel
    pertama lewat substring dan mengembalikan "A"."""
    return get_source_reliability(source) if source.strip() else "F"


def _score(
    candidate: Candidate, ctx: _Context, *, related_articles: int
) -> tuple[SectionName, int, tuple[Reason, ...]]:
    """Section, skor, dan alasan satu kandidat. `related_articles` = jumlah artikel tentang cerita
    yang sama termasuk dirinya (cluster kampanye atau grup duplikat, mana yang lebih besar)."""
    victims = _codes(candidate.victim_countries)
    mentioned = _codes(candidate.mentioned_countries)
    reasons: list[Reason] = []

    def add(code: str, text: str, points: int) -> None:
        if points > 0:
            reasons.append(Reason(code, text, points))

    if candidate.kev_cves:
        add(
            "kev",
            f"Mentions {_listing(candidate.kev_cves)} in the CISA KEV catalog",
            POINTS_KEV,
        )
    if candidate.poc_cves:
        add(
            "poc",
            f"A public proof-of-concept exists for {_listing(candidate.poc_cves)}",
            POINTS_POC,
        )
    if candidate.confirmed_incident:
        add("confirmed_incident", "Confirmed incident", POINTS_CONFIRMED_INCIDENT)

    techs = matching_names(ctx.monitored_techs, candidate.title)
    if techs:
        add("monitored_tech", f"Mentions monitored tech: {_listing(techs)}", POINTS_MONITORED_TECH)

    client_hits = sorted((victims | mentioned) & ctx.client_countries)
    if client_hits:
        add(
            "client_country",
            f"Involves a client country: {_listing(client_hits)}",
            POINTS_CLIENT_COUNTRY,
        )

    apac_victims = sorted(victims & APAC_COUNTRY_CODES)
    apac_mentioned = sorted(mentioned & APAC_COUNTRY_CODES)
    if INDONESIA in victims:
        add("indonesia", "Indonesia is a victim country", POINTS_INDONESIA_VICTIM)
    elif INDONESIA in mentioned:
        add("indonesia", "Indonesia is mentioned", POINTS_INDONESIA_MENTIONED)
    elif apac_victims:
        add("apac", f"Victim in APAC: {_listing(apac_victims)}", POINTS_APAC_VICTIM)
    elif apac_mentioned:
        add("apac", f"APAC country mentioned: {_listing(apac_mentioned)}", POINTS_APAC_MENTIONED)

    if related_articles >= 2:
        add(
            "coverage",
            f"Covered by {related_articles} related articles",
            min((related_articles - 1) * POINTS_PER_RELATED_ARTICLE, POINTS_COVERAGE_MAX),
        )

    grade = _grade(candidate.source)
    add("source", f"Source reliability grade {grade}", POINTS_SOURCE.get(grade, 0))

    confidence = candidate.confidence_score
    if confidence is not None:
        above = max(0, min(confidence, 100) - CONFIDENCE_FLOOR)
        add(
            "confidence",
            f"Confidence score {confidence}/100",
            above * POINTS_CONFIDENCE_MAX // (100 - CONFIDENCE_FLOOR),
        )

    ordered = tuple(sorted(reasons, key=lambda r: (-r.points, r.code)))
    return _section(victims, mentioned), sum(r.points for r in ordered), ordered


def _order(scored: _Scored) -> tuple[int, int, int]:
    """Skor terbesar, lalu `posted_on` terbaru, lalu `article_id` terkecil."""
    posted = scored.candidate.posted_on
    return (-scored.score, -(posted.toordinal() if posted else 0), scored.candidate.article_id)


def _collapse_duplicates(pool: list[_Scored], ctx: _Context) -> list[_Scored]:
    """Satu pilihan per cerita. `pool` SUDAH urut skor, jadi anggota pertama tiap grup (yang
    dijadikan kanonik oleh `find_dedup_groups`) adalah yang terbaik. Kanonik yang punya duplikat
    dinilai ulang dengan liputan = jumlah sumber berbeda yang melaporkannya (atau ukuran cluster
    kalau lebih besar)."""
    rows = [
        {"id": s.candidate.article_id, "title": s.candidate.title, "source": s.candidate.source}
        for s in pool
    ]
    by_id = {s.candidate.article_id: s for s in pool}
    survivors: list[_Scored] = []
    for row in find_dedup_groups(rows):
        scored = by_id[row["id"]]
        if row["_dup_count"] > 1:
            own = scored.candidate.source.casefold()
            others = {s.casefold() for s in row["_dup_sources"]} - {own}
            section, score, reasons = _score(
                scored.candidate,
                ctx,
                related_articles=max(scored.candidate.cluster_size, 1 + len(others)),
            )
            scored = replace(scored, section=section, score=score, reasons=reasons)
        survivors.append(scored)
    return survivors


def rank_candidates(
    candidates: Sequence[Candidate],
    *,
    client_countries: Collection[str] = (),
    monitored_techs: Collection[str] = (),
) -> list[RankedArticle]:
    """Nilai, runtuhkan duplikat, lalu bagi ke tier. Hasil urut `rank` (1, 2, 3, ...).

    `client_countries`: gabungan negara SEMUA client (newsletter ini global, bukan per client).
    `monitored_techs`: gabungan nama entri techstack AKTIF semua client; dicocokkan ke judul oleh
    `cti_core.tech_match.matching_names` (pencocok yang sama dengan `score.py`: kata utuh, tech
    satu huruf tidak pernah cocok). Daftar kosong berarti tidak ada sinyal itu, BUKAN "semua cocok".
    """
    ctx = _Context(
        client_countries=_codes(client_countries), monitored_techs=_distinct_names(monitored_techs)
    )

    scored: list[_Scored] = []
    for candidate in candidates:
        section, score, reasons = _score(candidate, ctx, related_articles=candidate.cluster_size)
        if reasons:
            scored.append(_Scored(candidate, section, score, reasons))
    scored.sort(key=_order)

    pooled: dict[str, int] = dict.fromkeys(SECTIONS, 0)
    pool: list[_Scored] = []
    for item in scored:  # sudah urut skor, jadi yang masuk pool = teratas tiap section
        if pooled[item.section] < DEDUP_POOL_PER_SECTION:
            pooled[item.section] += 1
            pool.append(item)

    final = sorted(_collapse_duplicates(pool, ctx), key=_order)

    taken = dict.fromkeys(SECTIONS, 0)
    ranked: list[RankedArticle] = []
    for position, item in enumerate(final):
        if position < MAX_HIGHLIGHTS:
            tier = TIER_HIGHLIGHT
        else:
            used = taken[item.section]
            if used < MAX_FULL_PER_SECTION:
                tier = TIER_FULL
            elif used < MAX_FULL_PER_SECTION + MAX_COMPACT_PER_SECTION:
                tier = TIER_COMPACT
            else:
                continue
            taken[item.section] = used + 1
        ranked.append(
            RankedArticle(
                article_id=item.candidate.article_id,
                score=item.score,
                section=item.section,
                tier=tier,
                rank=len(ranked) + 1,
                reasons=item.reasons,
            )
        )
    return ranked
