"""Rute klasifikasi -> (`news_type`, topic alert) buat SATU artikel. PURE
FUNCTION -- gak ada I/O (HTTP/DB/LLM) di sini sama sekali, semua sinyal
(termasuk `related_tech_cve_status` yang di kode lama butuh panggilan HTTP
ke MITRE) harus SUDAH dihitung caller (`stages/score.py`) sebelum masuk ke
sini. Itu yang bikin tiap cabang bisa dites langsung tanpa mock apa pun --
lihat `tests/unit/test_routing.py`.

Port dari `nlp.py:533-719` (cascade 4 cabang: Global/Regional+TA/Regional/TA
Group) + `_sendAlert()` (nlp.py:27-73, cascade 7 tipe alert) + `_send_alert()`
(telegramAlert.py:6-31, dispatcher global/apac/apt). Detail yang keliatan
aneh TAPI disalin apa adanya karena emang begitu di kode asli:

- OT keyword pre-check (`_OT_INDUSTRY_KEYWORDS`, dicek ke `industries_impacted`
  hasil GPT) jalan TERPISAH dari cascade utama. Di kode asli (`_sendAlert`) itu
  mengirim alert KEDUA ke `ot` di samping hasil cascade, jadi satu artikel
  muncul dua kali dengan teks yang persis sama (prod 2026-10-21: 30 dari 657
  artikel dalam 14 hari). SEKARANG dihentikan (keputusan user): pre-check hanya
  menambah satu baris penanda `OT-relevant` di teks, topiknya tetap SATU dari
  cascade. Cabang cascade `ot_status` tetap ke `ot` (artikel OT sungguhan,
  satu pesan, tanpa penanda).
- `report_status`/`ot_status` konsumsi counter KUMULATIF title+body (lihat
  `stages/score.py`) -- routing cuma baca hasil akhirnya sebagai bool.
- `related_tech_cve_status` di kode lama CUMA pernah dihitung di cabang
  "Global Article" (mentioned_group/countries/people kosong semua) --
  3 cabang lain gak pernah manggil `checkCVE` sama sekali, jadi nilainya
  tetap `False` di sana. Caller (`score.py`) yang jaga kondisi ini, BUKAN
  `route()` -- lihat docstring `RoutingInput.related_tech_cve_status`.
- Cabang "TA Group Article" (D) lolos ke `elif` terakhir dengan kondisi
  `mentioned_apac_people == 0 or mentioned_countries == 0` (OR, bukan AND) --
  keliatan ganjil TAPI given urutan elif di atasnya, kondisi ini emang
  selalu true kalau sampai ke sini (branch B udah nyaring kasus
  people!=0-or-countries!=0). Disalin verbatim, bukan disederhanakan.
"""

from __future__ import annotations

import html
import re
from collections import OrderedDict
from dataclasses import dataclass, field

# Industri yang, kalau GPT nandain artikel ini kena, bikin pesan dikasih penanda
# "OT-relevant" WALAUPUN cascade utama berakhir milih topic lain (TIDAK dikirim
# ulang ke topic `ot`). `industries_impacted` (GPT) yang dicek, BUKAN ot_list
# keyword (itu `stages/score.py`, sinyal beda).
_OT_INDUSTRY_KEYWORDS = [
    "critical infrastructure",
    "energy & utilities",
    "manufacturing & industrial",
    "transportation & logistics",
    "aerospace & defense contractors",
]

_VULN_KEYWORD_LIST = [
    "flaws? (.+)?(enables?|expose|lets?|allows?)",
    "critical (.+)?(flaws?|vulnerability|vulnerabilities)",
    "(vulnerability|vulnerabilities) (.+)?(allows?|exposes?|enables?|lets?)",
]

_RE_INDONESIA = re.compile(r"\bindonesia[n]?\b", re.IGNORECASE)
_FLAG_INDONESIA = "🇮🇩"


def _keyword_hit(keywords: list[str], text: str) -> str | None:
    lowered = text.lower()
    for kw in keywords:
        if re.search(rf"\b{kw.lower()}\b", lowered):
            return kw
    return None


def _is_indonesia(text: str) -> bool:
    return bool(_RE_INDONESIA.search(text.lower()) or _FLAG_INDONESIA in text.lower())


@dataclass
class RoutingInput:
    """Semua sinyal yang dibutuhin buat mutusin satu artikel -- hasil
    `stages/classify.py` + `stages/score.py`, SUDAH dihitung, gak ada yang
    dikerjain ulang di `route()`."""

    msg_data_base: str
    """Pesan Telegram yang UDAH kebentuk sampai baris "Impacted Industries"
    (+ baris Funding kalau match) -- lihat `stages/score.py::build_msg_base`.
    `route()` cuma NAMBAHIN baris (Threat Actor/Country-People/TTP), gak
    pernah nulis ulang bagian ini."""
    industries_impacted: list[str]

    mentioned_group: list[str]
    mentioned_countries: list[str]
    mentioned_apac_people: list[str]

    cve_list_title: list[str]
    report_status: bool
    ot_status: bool
    related_tech_status: bool
    related_tech_cve_status: bool
    """CUMA boleh `True` kalau caller udah verifikasi kondisi "Global Article"
    (3 list mention di atas kosong semua) DAN manggil `checkCVE` beneran --
    lihat docstring modul. `route()` gak validasi ini, cuma konsumsi."""
    databreach_list: list[str]
    zero_day_list: list[str]

    ttp_string: str = ""


@dataclass
class RoutingResult:
    news_type: str
    """Buat kolom `Article.news_type` -- SATU nilai final, hasil cascade
    utama. Nilai OT pre-check (kalau kepicu) TIDAK pernah nyampe sini --
    ketimpa cascade utama persis kayak kode lama (lihat docstring modul)."""
    alert_topics: list[str]
    """1 atau 2 entri -- lihat catatan "double alert" di docstring modul.
    Tiap entri = key ke `TelegramSettings.thread_ids`."""
    msg_data: str
    """`msg_data_base` + baris tambahan (Threat Actor/Country-People/TTP)
    sesuai cabang yang kepilih -- teks final yang beneran dikirim."""
    threat_actors: list[str] = field(default_factory=list)
    mentioned_countries: list[str] = field(default_factory=list)
    is_global_branch: bool = False
    """True kalau `mentioned_group`/`mentioned_apac_people`/
    `mentioned_countries` kosong semua ("Global Article", cabang A) --
    `stages/persist.py` butuh ini buat aturan fallback `victim_countries`
    (lihat docstring di sana), dihitung SEKALI di sini biar gak drift
    dari kondisi yang sama yang `route()` pakai buat milih cabang."""


def threat_actor_names(mentioned_group: list[str]) -> list[str]:
    """Bentuk nama TA yang DISIMPAN (`ArticleThreatActor.threat_actor`) dari
    hasil `score` -- `capitalize()` persis kode lama, mis. `shinyhunters` ->
    `Shinyhunters`. Dipakai `route()` dan `cti_enrich.backfill` biar dua
    jalur tulis gak bisa beda format."""
    seen = list(OrderedDict.fromkeys(mentioned_group))
    return list(OrderedDict.fromkeys(g.capitalize().replace("\\-", "-") for g in seen))


def _group_string(mentioned_group: list[str]) -> str:
    return " || ".join(threat_actor_names(mentioned_group))


def _apac_string(countries: list[str], people: list[str]) -> str:
    parts = [c.capitalize() for c in countries] + [p.capitalize() for p in people]
    return " || ".join(parts)


def _esc(text: str) -> str:
    """`msg_data` dikirim sebagai HTML Telegram; di teks biasa cukup `& < >` yang di-escape.
    Hanya dipakai saat menyusun pesan: `group_string`/`apac_string` mentah tetap dipakai untuk
    kolom `threat_actors`/`mentioned_countries` yang disimpan."""
    return html.escape(text, quote=False)


def _generic_topic(group_empty: bool, news_type_branch: str, msg_data: str) -> str:
    """Port `telegramAlert._send_alert`'s 3-way dispatch (global/apac/apt)."""
    if group_empty and news_type_branch == "global":
        return "global"
    if news_type_branch == "apac":
        return "apac_indo" if _is_indonesia(msg_data) else "apac"
    return "apt"


def route(inp: RoutingInput) -> RoutingResult:
    mentioned_group = list(OrderedDict.fromkeys(inp.mentioned_group))
    mentioned_countries = list(OrderedDict.fromkeys(inp.mentioned_countries))
    mentioned_apac_people = list(OrderedDict.fromkeys(inp.mentioned_apac_people))

    alert_topics: list[str] = []
    msg_data = inp.msg_data_base

    # Pre-check independen, tapi TIDAK menambah topik -- lihat docstring modul. Penandanya
    # ditempel di akhir (setelah cascade) supaya gak mengubah `_is_indonesia`/`_VULN_KEYWORD_LIST`
    # yang membaca `msg_data`.
    industries_text = " ".join(inp.industries_impacted).lower()
    ot_industry_hit = _keyword_hit(_OT_INDUSTRY_KEYWORDS, industries_text)

    is_global_branch = not mentioned_group and not mentioned_apac_people and not mentioned_countries
    is_ta_and_regional = bool(mentioned_group) and (
        bool(mentioned_apac_people) or bool(mentioned_countries)
    )
    is_regional_only = not mentioned_group and (
        bool(mentioned_apac_people) or bool(mentioned_countries)
    )
    # cabang ke-4 ("TA Group") = sisanya (mentioned_group non-kosong, gak kena is_ta_and_regional)

    threat_actors: list[str] = []
    out_countries: list[str] = []

    if is_global_branch:
        news_type_branch = "global"
        group_string = ""
        if inp.ttp_string:
            msg_data += f"<b>Related TTP</b>: {_esc(inp.ttp_string)}\n"
        out_countries = []
    elif is_ta_and_regional:
        news_type_branch = "apac"
        group_string = _group_string(mentioned_group)
        apac_string = _apac_string(mentioned_countries, mentioned_apac_people)
        msg_data += f"<b>Related Threat Actor</b>: {_esc(group_string)}\n"
        msg_data += f"<b>Mentioned Country/People</b>: {_esc(apac_string)}\n"
        if inp.ttp_string:
            msg_data += f"<b>Related TTP</b>: {_esc(inp.ttp_string)}\n"
        threat_actors = group_string.split(" || ") if group_string else []
        out_countries = apac_string.split(" || ") if apac_string else []
    elif is_regional_only:
        news_type_branch = "apac"
        group_string = ""
        apac_string = _apac_string(mentioned_countries, mentioned_apac_people)
        msg_data += f"<b>Mentioned Country/People</b>: {_esc(apac_string)}\n"
        if inp.ttp_string:
            msg_data += f"<b>Related TTP</b>: {_esc(inp.ttp_string)}\n"
        out_countries = apac_string.split(" || ") if apac_string else []
    else:  # "TA Group Article"
        news_type_branch = "global"
        group_string = _group_string(mentioned_group)
        msg_data += f"<b>Related Threat Actor</b>: {_esc(group_string)}\n"
        if inp.ttp_string:
            msg_data += f"<b>Related TTP</b>: {_esc(inp.ttp_string)}\n"
        threat_actors = group_string.split(" || ") if group_string else []

    # Cascade utama -- port `_sendAlert()`, urutan elif WAJIB persis ini.
    if inp.zero_day_list:
        alert_topics.append("zero_day")
        news_type = "Zero Day Article"
    elif inp.databreach_list:
        alert_topics.append("data_breach_indo" if _is_indonesia(msg_data) else "data_breach")
        news_type = "Data Breach Article"
    elif inp.report_status:
        alert_topics.append("vendor_report")
        news_type = "Vendor Report Article"
    elif inp.ot_status:
        alert_topics.append("ot")
        news_type = "OT Article"
    elif inp.related_tech_status or inp.related_tech_cve_status:
        alert_topics.append("tech_stack")
        news_type = "Tech Stack Article"
    elif inp.related_tech_status is False and inp.cve_list_title:
        alert_topics.append("tech_stack_unrelated")
        news_type = "Unrelated Tech Stack Article"
    else:
        hit = _keyword_hit(_VULN_KEYWORD_LIST, msg_data)
        if hit:
            alert_topics.append("tech_stack_unrelated")
            news_type = "Unrelated Tech Stack Article"
        else:
            alert_topics.append(_generic_topic(group_string == "", news_type_branch, msg_data))
            news_type = news_type_branch

    if ot_industry_hit and "ot" not in alert_topics:
        msg_data += f"<b>OT-relevant</b>: Yes ({_esc(ot_industry_hit)})\n"

    return RoutingResult(
        news_type=news_type,
        alert_topics=alert_topics,
        msg_data=msg_data,
        threat_actors=threat_actors,
        mentioned_countries=out_countries,
        is_global_branch=is_global_branch,
    )
