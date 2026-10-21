"""Task laporan periodik (Fase 10.E): `report.daily_counters`, `report.news_of_the_day`,
`report.logbook`, `report.weekly_top_cve`, `report.trending_cve`.

DB beneran (testcontainers) dan task dijalankan eager lewat `apply()`; yang
di-patch cuma sisi luar: Telegram, LLM, dan HTTP ke MITRE. Yang dikunci:
  - batas "hari lokal" (WIB) -- artikel 23:59 dan 00:00 WIB jatuh ke hari berbeda;
  - state/counter baru berubah SESUDAH Telegram sukses (kode lama menghapus/mereset
    duluan, jadi kirim gagal = data hilang);
  - routing topik.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.report_state import SCOPE_NEWS, SCOPE_TWEET, CveMention, JobState
from cti_core.db.repositories.report_state import CveMentionRepo, JobStateRepo
from cti_core.urlkit import url_hash
from sqlalchemy import delete, select

UTC = datetime.UTC
DAY = "2026-09-26"  # hari LOKAL (WIB); 00:00 WIB = 2026-09-25 17:00 UTC
PREFIX = "https://rpt.example/"


def utc(day: int, hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 9, day, hour, minute, tzinfo=UTC)


def add_article(n: int, first_seen: datetime.datetime, news_type: str = "global", **kw) -> None:
    url = f"{PREFIX}a{n}"
    with sync_session() as s:
        s.add(
            Article(
                url=url, url_hash=url_hash(url), title=kw.pop("title", f"Judul {n}"), source="T",
                first_seen_at=first_seen, last_seen_at=first_seen, seen_count=1,
                news_type=news_type, **kw,
            )
        )  # fmt: skip


def add_rejected(
    n: int, at: datetime.datetime, reason: str = "not cyber", failure_kind: str | None = None
) -> None:
    url = f"{PREFIX}r{n}"
    with sync_session() as s:
        s.add(
            RejectedArticle(
                url=url, url_hash=url_hash(url), title=f"Ditolak {n}", source="T",
                reason=reason, failure_kind=failure_kind, rejected_at=at,
            )
        )  # fmt: skip


@pytest.fixture(autouse=True)
def _clean(_migrated_schema: None) -> Iterator[None]:
    def wipe() -> None:
        with sync_session() as s:
            s.execute(delete(Article).where(Article.url.like(f"{PREFIX}%")))
            s.execute(delete(RejectedArticle).where(RejectedArticle.url.like(f"{PREFIX}%")))
            s.execute(delete(CveMention))
            s.execute(delete(JobState))

    wipe()
    yield
    wipe()


class Telegram:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str]] = []
        self.docs: list[tuple[str, str, str | bytes, str]] = []
        self.fail = False

    def send_alert(self, topic: str, msg: str, **_kw: object) -> None:
        if self.fail:
            raise ConnectionError("telegram down")
        self.alerts.append((topic, msg))

    def send_document(self, topic: str, name: str, content, caption: str = "", **_kw) -> None:
        if self.fail:
            raise ConnectionError("telegram down")
        self.docs.append((topic, name, content, caption))


@pytest.fixture
def tg(monkeypatch: pytest.MonkeyPatch) -> Telegram:
    fake = Telegram()
    from cti_worker.tasks import reports

    monkeypatch.setattr(reports, "send_alert", fake.send_alert)
    monkeypatch.setattr(reports, "send_document", fake.send_document)
    return fake


def run(task, **kwargs):
    return task.apply(kwargs=kwargs).get()


# --- sendCounter ---------------------------------------------------------------------


def test_daily_counters_split_related_unrelated_and_failed_for_the_local_day(tg: Telegram) -> None:
    from cti_worker.tasks.reports import report_daily_counters

    add_article(1, utc(25, 18))  # 01:00 WIB tgl 26
    add_article(2, utc(26, 10), title="Judul dua")
    add_rejected(1, utc(26, 3))
    add_rejected(2, utc(26, 4), reason="[enrichment_failed] APIConnectionError: x")  # worker lama
    add_rejected(3, utc(26, 5), reason="tanpa prefix", failure_kind="permanent")  # worker baru

    result = run(report_daily_counters, day=DAY)

    assert result["scraped"] == 5
    [(topic, message)] = tg.alerts
    assert topic == "debug"
    assert "Total news scraped on 26 09 2026: 5" in message
    assert "Total unrelated cti news: 1" in message and "Total related cti news: 2" in message
    assert "Total gagal diproses (cek Filtered Articles): 2" in message
    names = {name: (t, c) for t, name, c, _ in tg.docs}
    assert set(names) == {"RELATED_26_09_2026.txt", "UNRELATED_26_09_2026.txt"}
    assert names["RELATED_26_09_2026.txt"][1] == "Judul 1\nJudul dua\n"
    assert names["UNRELATED_26_09_2026.txt"][1] == "Ditolak 1\n"  # yg gagal BUKAN unrelated


def test_day_boundary_is_local_midnight_not_utc_midnight(tg: Telegram) -> None:
    from cti_worker.tasks.reports import report_daily_counters

    add_article(1, utc(25, 16, 59))  # 23:59 WIB tgl 25 -> bukan tgl 26
    add_article(2, utc(25, 17, 0))  # 00:00 WIB tgl 26
    add_article(3, utc(26, 16, 59))  # 23:59 WIB tgl 26
    add_article(4, utc(26, 17, 0))  # 00:00 WIB tgl 27 -> bukan tgl 26

    assert run(report_daily_counters, day=DAY)["scraped"] == 2


def test_a_quiet_day_sends_the_summary_but_no_empty_files(tg: Telegram) -> None:
    from cti_worker.tasks.reports import report_daily_counters

    run(report_daily_counters, day=DAY)

    assert len(tg.alerts) == 1 and "scraped on 26 09 2026: 0" in tg.alerts[0][1]
    assert tg.docs == []  # skrip lama crash / kirim file kosong


# --- trendingNewsToday ------------------------------------------------------------------


class FakeLLM:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        content = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def topics_json(*titles: str, name: str = "Ransomware") -> str:
    return json.dumps({"topics": [{"topic_name": name, "reference_title": list(titles)}]})


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch):
    def install(*replies: str) -> FakeLLM:
        fake = FakeLLM(*replies)
        monkeypatch.setattr(
            "cti_worker.reports.news_of_the_day.get_llm_client", lambda: (fake, "m")
        )
        return fake

    return install


def test_news_of_the_day_groups_todays_global_and_apac_headlines(tg: Telegram, llm) -> None:
    from cti_worker.tasks.reports import report_news_of_the_day

    add_article(1, utc(26, 1), "global", title="Ransomware hits hospital")
    add_article(2, utc(26, 2), "apac", title="Indonesia data leak")
    add_article(3, utc(26, 3), "Security Technology & Best Practices", title="Best practice")
    add_article(4, utc(24, 3), "global", title="Berita kemarin")  # hari lain
    fake = llm(topics_json("Ransomware hits hospital", "Judul halusinasi", name="Ransomware"))

    result = run(report_news_of_the_day, day=DAY)

    assert result["sent"] == ["global", "apac"]
    assert [d[0] for d in tg.docs] == ["notd", "notd"]
    name, content, caption = tg.docs[0][1], tg.docs[0][2], tg.docs[0][3]
    assert name == "Top_News_GLOBAL_26-09-2026.json"
    assert json.loads(content) == [
        {"Ransomware": [{"title": "Ransomware hits hospital", "url": f"{PREFIX}a1"}]}
    ]  # judul halusinasi dibuang
    assert "TOP 5 HOT TOPIC GLOBAL NEWS TODAY" in caption
    sent_titles = fake.calls[0]["messages"][1]["content"]
    assert "Ransomware hits hospital" in sent_titles and "Berita kemarin" not in sent_titles


def test_news_of_the_day_skips_a_category_with_no_articles_and_never_calls_the_llm(
    tg: Telegram, llm
) -> None:
    from cti_worker.tasks.reports import report_news_of_the_day

    fake = llm(topics_json("x"))

    assert run(report_news_of_the_day, day=DAY)["sent"] == []
    assert fake.calls == [] and tg.docs == []


def test_news_of_the_day_retries_prose_with_the_hardened_message_shape(tg: Telegram, llm) -> None:
    from cti_worker.tasks.reports import report_news_of_the_day

    add_article(1, utc(26, 1), "global", title="Ransomware hits hospital")
    fake = llm(
        "I'm Kiro, a development assistant, not an analyst.",
        topics_json("Ransomware hits hospital"),
    )

    run(report_news_of_the_day, day=DAY)

    first, second = (c["messages"][1]["content"] for c in fake.calls)
    assert "<headlines>" not in first and "<headlines>" in second  # percobaan ulang dikuatkan
    assert len(tg.docs) == 1


def test_news_of_the_day_accepts_a_bare_array_and_matches_titles_loosely(tg: Telegram, llm) -> None:
    from cti_worker.tasks.reports import report_news_of_the_day

    add_article(1, utc(26, 1), "global", title="Ransomware  hits HOSPITAL")
    llm(json.dumps([{"topic_name": "T", "reference_title": ["ransomware hits hospital"]}]))

    run(report_news_of_the_day, day=DAY)

    refs = json.loads(tg.docs[0][2])[0]["T"]
    assert refs == [{"title": "ransomware hits hospital", "url": f"{PREFIX}a1"}]


def test_news_of_the_day_fails_loudly_when_the_llm_never_returns_json(tg: Telegram, llm) -> None:
    from cti_worker.tasks.reports import report_news_of_the_day

    add_article(1, utc(26, 1), "global")
    llm("prosa terus")

    with pytest.raises(json.JSONDecodeError):
        run(report_news_of_the_day, day=DAY)
    assert tg.docs == []  # bukan laporan kosong yang seolah sukses


# --- logbook ------------------------------------------------------------------------------


def logbook_state() -> str | None:
    with sync_session() as s:
        return JobStateRepo(s).get("logbook.last_report_date")


def test_logbook_first_run_only_records_today_like_the_old_script(tg: Telegram) -> None:
    from cti_worker.tasks.reports import report_logbook

    assert run(report_logbook, day=DAY)["status"] == "initialized"
    assert logbook_state() == DAY and tg.docs == []


def test_logbook_is_not_due_before_the_interval(tg: Telegram) -> None:
    from cti_worker.tasks.reports import report_logbook

    with sync_session() as s:
        JobStateRepo(s).set("logbook.last_report_date", "2026-09-20")

    assert run(report_logbook, day=DAY)["status"] == "not_due"
    assert logbook_state() == "2026-09-20" and tg.docs == []


def test_logbook_sends_the_workbook_and_only_then_advances_the_state(tg: Telegram) -> None:
    import io

    import openpyxl
    from cti_worker.tasks.reports import report_logbook

    with sync_session() as s:
        JobStateRepo(s).set("logbook.last_report_date", "2026-09-12")
    add_article(
        1, utc(20, 1), "global", title="Berita global", posted_on=datetime.date(2026, 9, 20)
    )
    add_article(2, utc(21, 1), "apac", title="Berita apac", posted_on=datetime.date(2026, 9, 21))
    add_article(
        3, utc(21, 1), "Security Technology & Best Practices", posted_on=datetime.date(2026, 9, 21)
    )
    add_article(4, utc(1, 1), "global", posted_on=datetime.date(2026, 9, 1))  # di luar 14 hari

    result = run(report_logbook, day=DAY)

    assert result == {"status": "sent", "entries": 2}
    [(topic, name, content, caption)] = tg.docs
    assert topic == "logbook"
    assert name == "ThreatInformation_Logbook_12-Sep-2026_to_26-Sep-2026.xlsx"
    ws = openpyxl.load_workbook(io.BytesIO(content)).active
    assert [ws.cell(row=r, column=5).value for r in (14, 15)] == ["Berita global", "Berita apac"]
    assert "LOGBOOK REPORT" in caption
    assert logbook_state() == DAY


def test_logbook_send_failure_keeps_the_state_so_the_next_run_retries(tg: Telegram) -> None:
    from cti_worker.tasks.reports import report_logbook

    with sync_session() as s:
        JobStateRepo(s).set("logbook.last_report_date", "2026-09-12")
    tg.fail = True

    with pytest.raises(ConnectionError):
        run(report_logbook, day=DAY)

    assert logbook_state() == "2026-09-12"  # tidak maju -> laporan tidak "terlewat"


# --- topCve (mingguan) ---------------------------------------------------------------------

RECORD = {
    "containers": {
        "cna": {
            "metrics": [{"cvssV3_1": {"baseScore": 9.8}}],
            "affected": [
                {"vendor": "Acme", "product": "Widget", "versions": [{"status": "affected"}]}
            ],
        }
    }
}


@pytest.fixture
def mitre(monkeypatch: pytest.MonkeyPatch):
    """`{cve_id: record | None}`; CVE yang tak terdaftar -> None (tidak ada di MITRE)."""
    records: dict[str, dict | None] = {}
    monkeypatch.setattr(
        "cti_worker.reports.cve_digest.fetch_record",
        lambda client, cve_id: records.get(cve_id.upper()),
    )
    return records


def bump(scope: str, cve: str, times: int, day: str = DAY) -> None:
    with sync_session() as s:
        CveMentionRepo(s).bump(scope, [cve] * times, on=datetime.date.fromisoformat(day))


def counters(scope: str) -> dict[str, int]:
    with sync_session() as s:
        rows = s.execute(
            select(CveMention.cve_id, CveMention.counter).where(CveMention.scope == scope)
        )
        return dict(rows.all())


def test_weekly_top_cve_reports_the_most_mentioned_and_resets_only_those(
    tg: Telegram, mitre
) -> None:
    from cti_worker.tasks.reports import report_weekly_top_cve

    mitre.update({"CVE-2026-0001": RECORD, "CVE-2026-0002": RECORD})
    bump(SCOPE_NEWS, "CVE-2026-0001", 5)
    bump(SCOPE_NEWS, "CVE-2026-0002", 2)
    bump(SCOPE_NEWS, "CVE-2026-0003", 9)  # tak ada di MITRE -> dilewati, counter dibiarkan

    result = run(report_weekly_top_cve, day=DAY)

    assert result == {"status": "sent", "cves": 2}
    [(topic, text)] = tg.alerts
    assert topic == "tech_stack"
    assert text.index("CVE-2026-0001") < text.index("CVE-2026-0002")  # counter turun
    assert "Total Mentioned: 5" in text and "9.8 <b>Critical</b>" in text
    assert "CVE-2026-0003" not in text
    assert counters(SCOPE_NEWS) == {"CVE-2026-0001": 0, "CVE-2026-0002": 0, "CVE-2026-0003": 9}


def test_weekly_top_cve_ignores_mentions_older_than_seven_days(tg: Telegram, mitre) -> None:
    from cti_worker.tasks.reports import report_weekly_top_cve

    mitre["CVE-2026-0001"] = RECORD
    bump(SCOPE_NEWS, "CVE-2026-0001", 5, day="2026-09-10")  # 16 hari lalu

    assert run(report_weekly_top_cve, day=DAY) == {"status": "empty"}
    assert tg.alerts == []


def test_weekly_top_cve_send_failure_does_not_lose_the_counters(tg: Telegram, mitre) -> None:
    """Kode lama mereset counter DI DALAM loop, sebelum Telegram."""
    from cti_worker.tasks.reports import report_weekly_top_cve

    mitre["CVE-2026-0001"] = RECORD
    bump(SCOPE_NEWS, "CVE-2026-0001", 5)
    tg.fail = True

    with pytest.raises(ConnectionError):
        run(report_weekly_top_cve, day=DAY)

    assert counters(SCOPE_NEWS) == {"CVE-2026-0001": 5}


# --- trendingCve (laporan 6 jam) ------------------------------------------------------------


def test_trending_cve_related_to_the_tech_stack_goes_only_to_tech_stack(
    tg: Telegram, mitre, monkeypatch
) -> None:
    from cti_worker.tasks.reports import report_trending_cve

    monkeypatch.setattr("cti_worker.tasks.reports.techstack_names", lambda s: ["acme"])
    mitre["CVE-2026-0001"] = RECORD
    bump(SCOPE_TWEET, "CVE-2026-0001", 4)

    run(report_trending_cve)

    assert [t for t, _ in tg.alerts] == ["tech_stack"]
    assert "Total Tweet: 4" in tg.alerts[0][1] and "Might Applicable" in tg.alerts[0][1]
    assert counters(SCOPE_TWEET) == {"CVE-2026-0001": 0}


def test_trending_cve_unrelated_goes_to_unrelated_and_vendor_report_and_unknown_cves_stay(
    tg: Telegram, mitre, monkeypatch
) -> None:
    from cti_worker.tasks.reports import report_trending_cve

    monkeypatch.setattr("cti_worker.tasks.reports.techstack_names", lambda s: ["zzz"])
    bump(SCOPE_TWEET, "CVE-2026-0009", 3)  # belum dipublikasikan MITRE: tetap dilaporkan

    run(report_trending_cve)

    assert [t for t, _ in tg.alerts] == ["tech_stack_unrelated", "vendor_report"]
    assert (
        "CVE-2026-0009" in tg.alerts[0][1]
        and "N/A" in tg.alerts[0][1]
        and "Unknown" in tg.alerts[0][1]
    )


def test_trending_cve_with_nothing_mentioned_sends_nothing(tg: Telegram, mitre) -> None:
    from cti_worker.tasks.reports import report_trending_cve

    assert run(report_trending_cve) == {"status": "empty"}
    assert tg.alerts == []
