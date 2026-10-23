from cti_api.services.dashboard_overview import APAC_COUNTRY_CODES, build_brief
from cti_api.services.trending import TrendItem


def test_brief_with_trend_and_kev():
    t = TrendItem(
        kind="actor",
        name="Qilin",
        ttp_id=None,
        count=23,
        prev_count=5,
        change_pct=360,
        is_new=False,
        daily=[],
    )
    b = build_brief(
        top_trend=t,
        kev_in_stack=3,
        incidents=214,
        prev_incidents=155,
        drivers=["Ransomware", "Data breach"],
    )
    assert b["headline"] == "Qilin naik 360% dan 3 CVE KEV cocok dengan tech stack klien."
    assert (
        b["detail"]
        == "Insiden naik 38% dibanding periode sebelumnya, didorong Ransomware dan Data breach."
    )


def test_brief_new_trend_no_kev():
    t = TrendItem(
        kind="ttp",
        name="Spearphishing Link",
        ttp_id="T1566.002",
        count=5,
        prev_count=0,
        change_pct=None,
        is_new=True,
        daily=[],
    )
    b = build_brief(top_trend=t, kev_in_stack=0, incidents=10, prev_incidents=None, drivers=[])
    assert b["headline"] == "T1566.002 Spearphishing Link baru muncul pada periode ini."
    assert b["detail"] == "10 insiden terkonfirmasi pada periode ini."


def test_brief_nothing_notable():
    b = build_brief(top_trend=None, kev_in_stack=0, incidents=0, prev_incidents=0, drivers=[])
    assert b["headline"] == "Tidak ada lonjakan atau CVE KEV baru pada periode ini."
    assert b["detail"] == "Belum ada insiden terkonfirmasi pada periode ini."


def test_brief_kev_only_and_trend_without_pct():
    b = build_brief(top_trend=None, kev_in_stack=2, incidents=4, prev_incidents=4, drivers=["X"])
    assert b["headline"] == "2 CVE KEV cocok dengan tech stack klien."
    assert b["detail"] == "Insiden stabil dibanding periode sebelumnya, didorong X."
    t = TrendItem(
        kind="actor",
        name="Akira",
        ttp_id=None,
        count=4,
        prev_count=1,
        change_pct=None,
        is_new=False,
        daily=[],
    )
    b = build_brief(top_trend=t, kev_in_stack=0, incidents=2, prev_incidents=4, drivers=[])
    assert b["headline"] == "Akira naik pada periode ini."
    assert b["detail"] == "Insiden turun 50% dibanding periode sebelumnya."


def test_apac_codes():
    assert len(APAC_COUNTRY_CODES) == 29
    assert {"ID", "SG", "AU"} <= APAC_COUNTRY_CODES
