"""cti_enrich.routing -- satu test per cabang cascade (plan Fase 5 exit
criteria: "tiap cabang routing ada test"), plus kasus tepi yang jadi alasan
`route()` didesain kayak gini (penanda OT tanpa alert ganda, sub-routing Indonesia,
`related_tech_cve_status` cuma valid di cabang Global)."""

import dataclasses
from html.parser import HTMLParser
from typing import TypedDict, Unpack

from cti_enrich.routing import RoutingInput, route
from cti_enrich.stages.alert import build_message_base

_BASE_MSG = (
    "\n    === <b>GBHACKER</b> ===\n"
    "<b>Title</b>: Some Article Title\n"
    "<b>Posted On</b>: 2026-01-01\n"
    '<b>Link</b>: <a href="https://example.com">Read Now</a>\n'
    "<b>Impacted Industries</b>: General\n"
)


class _RoutingOverrides(TypedDict, total=False):
    msg_data_base: str
    industries_impacted: list[str]
    mentioned_group: list[str]
    mentioned_countries: list[str]
    mentioned_apac_people: list[str]
    cve_list_title: list[str]
    report_status: bool
    ot_status: bool
    related_tech_status: bool
    related_tech_cve_status: bool
    databreach_list: list[str]
    zero_day_list: list[str]
    ttp_string: str


_DEFAULT_INPUT = RoutingInput(
    msg_data_base=_BASE_MSG,
    industries_impacted=["General"],
    mentioned_group=[],
    mentioned_countries=[],
    mentioned_apac_people=[],
    cve_list_title=[],
    report_status=False,
    ot_status=False,
    related_tech_status=False,
    related_tech_cve_status=False,
    databreach_list=[],
    zero_day_list=[],
    ttp_string="",
)


def _inp(**overrides: Unpack[_RoutingOverrides]) -> RoutingInput:
    return dataclasses.replace(_DEFAULT_INPUT, **overrides)


def test_global_article_no_mentions_routes_global() -> None:
    result = route(_inp())
    assert result.news_type == "global"
    assert result.alert_topics == ["global"]
    assert result.threat_actors == []


def test_regional_and_ta_group_article() -> None:
    """`news_type` tetap "apac" (literal) -- sub-routing "apac_indo" cuma
    ngaruh ke alert_topics (channel Telegram), bukan nilai yang dipersist."""
    result = route(_inp(mentioned_group=["APT41"], mentioned_countries=["Indonesia"]))
    assert result.news_type == "apac"
    assert result.alert_topics == ["apac_indo"]
    assert result.threat_actors == ["Apt41"]
    assert "Related Threat Actor" in result.msg_data
    assert "Mentioned Country/People" in result.msg_data


def test_regional_article_only_country() -> None:
    result = route(_inp(mentioned_countries=["Japan"]))
    assert result.news_type == "apac"
    assert result.alert_topics == ["apac"]
    assert result.threat_actors == []
    assert result.mentioned_countries == ["Japan"]


def test_ta_group_article_routes_apt() -> None:
    """Kuirk asli: `news_type` yang dipersist tetap literal "global" (param
    yang diteruskan ke `_sendAlert` di cabang ini) -- CUMA alert_topics yang
    ke channel APT. Article "Global" (A) dan "TA Group" (D) dua-duanya
    persist "global" saat jatuh ke fallback ini, walau beda channel Telegram."""
    result = route(_inp(mentioned_group=["Lazarus"]))
    assert result.news_type == "global"
    assert result.alert_topics == ["apt"]
    assert result.threat_actors == ["Lazarus"]
    assert "Mentioned Country/People" not in result.msg_data


def test_zero_day_takes_priority_over_everything() -> None:
    result = route(_inp(zero_day_list=["zero-day"], report_status=True, ot_status=True))
    assert result.news_type == "Zero Day Article"
    assert result.alert_topics == ["zero_day"]


def test_databreach_routes_before_report_and_ot() -> None:
    result = route(_inp(databreach_list=["data breach"], report_status=True))
    assert result.news_type == "Data Breach Article"
    assert result.alert_topics == ["data_breach"]


def test_databreach_indonesia_submarks_topic() -> None:
    result = route(_inp(databreach_list=["data breach"], mentioned_countries=["Indonesia"]))
    assert result.news_type == "Data Breach Article"
    assert result.alert_topics == ["data_breach_indo"]


def test_report_status_routes_vendor_report() -> None:
    result = route(_inp(report_status=True))
    assert result.news_type == "Vendor Report Article"
    assert result.alert_topics == ["vendor_report"]


def test_ot_status_routes_ot() -> None:
    result = route(_inp(ot_status=True))
    assert result.news_type == "OT Article"
    assert result.alert_topics == ["ot"]


def test_related_tech_status_routes_tech_stack() -> None:
    result = route(_inp(related_tech_status=True))
    assert result.news_type == "Tech Stack Article"
    assert result.alert_topics == ["tech_stack"]


def test_related_tech_cve_status_routes_tech_stack() -> None:
    """`related_tech_cve_status` cuma valid (dihitung) di cabang Global --
    lihat docstring `RoutingInput`. Di sini cuma diuji route() KONSUMSI-nya
    dengan benar, bukan siapa yang menghitungnya."""
    result = route(_inp(related_tech_cve_status=True))
    assert result.news_type == "Tech Stack Article"
    assert result.alert_topics == ["tech_stack"]


def test_unrelated_tech_with_cve_routes_tech_stack_unrelated() -> None:
    result = route(_inp(related_tech_status=False, cve_list_title=["CVE-2026-1234"]))
    assert result.news_type == "Unrelated Tech Stack Article"
    assert result.alert_topics == ["tech_stack_unrelated"]


def test_vuln_keyword_fallback_routes_tech_stack_unrelated() -> None:
    msg = _BASE_MSG.replace("Some Article Title", "Critical flaws enables remote takeover")
    result = route(_inp(msg_data_base=msg))
    assert result.news_type == "Unrelated Tech Stack Article"
    assert result.alert_topics == ["tech_stack_unrelated"]


def test_no_signal_at_all_falls_through_to_generic_global() -> None:
    result = route(_inp())
    assert result.news_type == "global"
    assert result.alert_topics == ["global"]


def test_ot_industry_pre_check_marks_the_message_but_keeps_one_topic() -> None:
    """Dulu "double alert" warisan `_sendAlert`: pre-check OT (industri GPT) mengirim pesan yang
    PERSIS SAMA ke `ot` DAN topik cascade (prod: 30 dari 657 artikel/14 hari). Sekarang satu
    topik (cascade) + satu baris penanda; `news_type` tetap ikut cascade (bukan OT)."""
    result = route(_inp(industries_impacted=["Energy & Utilities"], zero_day_list=["zero-day"]))
    assert result.alert_topics == ["zero_day"]
    assert result.news_type == "Zero Day Article"
    assert "<b>OT-relevant</b>: Yes (energy &amp; utilities)" in result.msg_data


def test_ot_industry_pre_check_on_the_global_branch_still_routes_global() -> None:
    result = route(_inp(industries_impacted=["Critical Infrastructure"]))
    assert result.alert_topics == ["global"]
    assert result.msg_data.endswith("<b>OT-relevant</b>: Yes (critical infrastructure)\n")


def test_ot_status_with_an_ot_industry_sends_ot_once_without_the_marker() -> None:
    """Dulu `["ot", "ot"]`: pesan identik dua kali di thread yang sama."""
    result = route(_inp(industries_impacted=["Energy & Utilities"], ot_status=True))
    assert result.alert_topics == ["ot"]
    assert result.news_type == "OT Article"
    assert "OT-relevant" not in result.msg_data


def test_no_ot_industry_means_no_marker() -> None:
    result = route(_inp(industries_impacted=["Finance & Insurance"], zero_day_list=["zero-day"]))
    assert result.alert_topics == ["zero_day"]
    assert "OT-relevant" not in result.msg_data


def test_the_ot_marker_does_not_change_indonesia_sub_routing() -> None:
    """Penanda ditempel SETELAH cascade: `_is_indonesia(msg_data)` membaca teks tanpa penanda."""
    msg = _BASE_MSG.replace("Some Article Title", "Indonesian grid operator breached")
    result = route(
        _inp(msg_data_base=msg, industries_impacted=["Energy & Utilities"], databreach_list=["x"])
    )
    assert result.alert_topics == ["data_breach_indo"]


def test_ttp_string_appended_when_present() -> None:
    result = route(_inp(ttp_string="Phishing (T1566)"))
    assert "Related TTP" in result.msg_data
    assert "Phishing (T1566)" in result.msg_data


def test_ttp_string_absent_when_empty() -> None:
    result = route(_inp())
    assert "Related TTP" not in result.msg_data


def test_feed_text_cannot_inject_tags_into_the_telegram_message() -> None:
    """Audit 2026-10-21: Telegram `parse_mode="HTML"` menolak seluruh pesan yang memuat tag tak
    dikenal, jadi judul feed `<redacted>` membuat alert hilang diam-diam."""
    base = build_message_base(
        script_name="a&b",
        title="RCE in <redacted> VPN & more",
        posted_on="2026-01-01",
        url='https://x.example/p?a=1&b="2',
        industries_string="Finance & Insurance",
        funding_keyword=None,
    )
    result = route(
        _inp(msg_data_base=base, mentioned_group=["a<b"], ttp_string="Phish <x> (T1566)")
    )

    tags: list[str] = []

    class _Tags(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            tags.append(tag)

    _Tags().feed(result.msg_data)
    assert set(tags) <= {"a", "b"}
    assert "RCE in &lt;redacted&gt; VPN &amp; more" in result.msg_data
    assert result.threat_actors == ["A<b"]  # kolom yang disimpan tetap mentah
