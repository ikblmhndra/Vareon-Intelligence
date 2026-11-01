"""Laporan mingguan tren threat actor (`report.weekly_threat_actor_trend`) -- gantiin pasangan
job Rundeck `threatactorTrendGraylog`/`threatactorTrendTelegram`.

DB beneran (testcontainers), task jalan eager lewat `apply()`; yang di-patch cuma Telegram.
`AS_OF` = Senin 28 Sep 2026 13:00 WIB (06:00 UTC), jadwal yang dipilih user.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article
from cti_core.db.repositories.article import ArticleRepo, MentionInput
from cti_core.urlkit import url_hash
from sqlalchemy import delete

UTC = datetime.UTC
AS_OF = datetime.datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
AS_OF_ISO = AS_OF.isoformat()
PREFIX = "https://ta-trend.example/"
_counter = iter(range(1, 10_000))


def days_ago(days: float) -> datetime.datetime:
    return AS_OF - datetime.timedelta(days=days)


def add_article(actors: list[str], first_seen: datetime.datetime) -> None:
    n = next(_counter)
    url = f"{PREFIX}a{n}"
    with sync_session() as s:
        article = Article(
            url=url, url_hash=url_hash(url), title=f"Judul {n}", source="T",
            first_seen_at=first_seen, last_seen_at=first_seen, seen_count=1,
            news_type="global",
        )  # fmt: skip
        s.add(article)
        ArticleRepo(s).add_mentions(
            article, [MentionInput("intrusion-set", a, "dictionary", a) for a in actors]
        )


def this_week(*actors: str) -> None:
    add_article(list(actors), days_ago(2))


def last_week(*actors: str) -> None:
    add_article(list(actors), days_ago(9))


@pytest.fixture(autouse=True)
def _clean(_migrated_schema: None) -> Iterator[None]:
    def wipe() -> None:
        with sync_session() as s:
            s.execute(delete(Article).where(Article.url.like(f"{PREFIX}%")))

    wipe()
    yield
    wipe()


class Telegram:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str]] = []
        self.fail = False

    def send_alert(self, topic: str, msg: str, **_kw: object) -> None:
        if self.fail:
            raise ConnectionError("telegram down")
        self.alerts.append((topic, msg))


@pytest.fixture
def tg(monkeypatch: pytest.MonkeyPatch) -> Telegram:
    fake = Telegram()
    from cti_worker.tasks import reports

    monkeypatch.setattr(reports, "send_alert", fake.send_alert)
    return fake


def run(as_of: str | None = AS_OF_ISO):
    from cti_worker.tasks.reports import report_weekly_threat_actor_trend

    return report_weekly_threat_actor_trend.apply(kwargs={"as_of": as_of}).get()


def lines(tg: Telegram) -> list[str]:
    [(_, message)] = tg.alerts
    return message.splitlines()


# --- isi laporan ---------------------------------------------------------------------------


def test_ranks_by_articles_this_week_and_compares_with_last_week(tg: Telegram) -> None:
    """Urutan menurut JUMLAH pekan ini (bukan abjad): Volt Typhoon paling banyak walau
    namanya paling akhir."""
    for _ in range(4):
        this_week("Volt Typhoon")  # baru muncul
    for _ in range(3):
        this_week("APT41")
    for _ in range(2):
        last_week("APT41")  # 2 -> 3: naik 50%
    for _ in range(2):
        this_week("Lazarus")
    for _ in range(4):
        last_week("Lazarus")  # 4 -> 2: turun 50%
    this_week("Sandworm")
    last_week("Sandworm")  # 1 -> 1: tetap

    result = run()

    assert result == {"status": "sent", "actors": 4}
    assert tg.alerts[0][0] == "top_ta"
    assert lines(tg) == [
        "=== <b>TOP 5 WEEKLY THREAT ACTORS BY GROWTH (%)</b> ===",
        "- Volt Typhoon: 0 -> 4 (Baru muncul)",
        "- APT41: 2 -> 3 (Naik, 50.00%)",
        "- Lazarus: 4 -> 2 (Turun, 50.00%)",
        "- Sandworm: 1 -> 1 (Tidak ada perubahan)",
    ]


def test_only_the_top_five_are_reported_with_ties_broken_alphabetically(tg: Telegram) -> None:
    for name in ("g", "f", "e", "d", "c", "b", "a"):
        this_week(name)  # semua 1 artikel -> seri

    run()

    assert [ln.split(":")[0] for ln in lines(tg)[1:]] == ["- a", "- b", "- c", "- d", "- e"]


def test_an_actor_only_seen_last_week_is_not_reported(tg: Telegram) -> None:
    this_week("APT41")
    last_week("Hantu")

    run()

    assert [ln.split(":")[0] for ln in lines(tg)[1:]] == ["- APT41"]


def test_an_article_naming_two_actors_counts_for_each_but_once_per_actor(tg: Telegram) -> None:
    this_week("APT41", "Lazarus")
    this_week("APT41")

    run()

    assert lines(tg)[1:] == ["- APT41: 0 -> 2 (Baru muncul)", "- Lazarus: 0 -> 1 (Baru muncul)"]


def test_spelling_variants_merge_and_the_most_common_spelling_is_shown(tg: Telegram) -> None:
    """Graylog membedakan huruf besar/kecil, jadi "APT41" dan "Apt41" dulu dua grup."""
    this_week("APT41")
    this_week("APT41")
    this_week("Apt41")
    last_week("apt41")

    run()

    assert lines(tg)[1:] == ["- APT41: 1 -> 3 (Naik, 200.00%)"]


def test_an_article_naming_two_spellings_of_one_actor_counts_once(tg: Telegram) -> None:
    this_week("APT41", "Apt41")

    run()

    assert lines(tg)[1:] == ["- APT41: 0 -> 1 (Baru muncul)"]  # ejaan seri -> abjad paling awal


def test_actor_names_are_html_escaped_for_the_telegram_html_mode(tg: Telegram) -> None:
    this_week("<b>Evil & Co</b>")

    run()

    assert lines(tg)[1] == "- &lt;b&gt;Evil &amp; Co&lt;/b&gt;: 0 -> 1 (Baru muncul)"


# --- jendela waktu ---------------------------------------------------------------------------


def test_window_edges_the_start_is_inclusive_and_as_of_itself_is_excluded(tg: Telegram) -> None:
    add_article(["Awal"], days_ago(7))  # tepat batas awal pekan ini -> ikut pekan ini
    add_article(["Akhir"], AS_OF)  # tepat as_of -> belum masuk (pekan ini = [as_of-7d, as_of))
    add_article(["Lalu"], days_ago(14))  # tepat awal pekan lalu -> ikut pembanding
    add_article(["Lalu"], days_ago(7))  # ini pekan ini, bukan pekan lalu
    add_article(["Lalu"], days_ago(14.001))  # lebih tua dari 14 hari -> tak dihitung sama sekali

    run()

    assert lines(tg)[1:] == ["- Awal: 0 -> 1 (Baru muncul)", "- Lalu: 1 -> 1 (Tidak ada perubahan)"]


def test_a_naive_as_of_is_read_as_utc(tg: Telegram, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dicek pada nilai yang sampai ke `collect`, bukan lewat hasil query: sesi DB berzona UTC
    membuat naif vs UTC tak terbedakan di sana, padahal di server lain bisa berbeda."""
    from cti_worker.reports import threat_actor_trend

    received: list[datetime.datetime] = []
    monkeypatch.setattr(
        threat_actor_trend, "collect", lambda session, as_of, **kw: received.append(as_of)
    )

    run("2026-09-28T06:00:00")

    assert received == [AS_OF] and received[0].tzinfo is not None


def test_without_as_of_the_window_ends_now(tg: Telegram) -> None:
    add_article(["APT41"], datetime.datetime.now(UTC) - datetime.timedelta(hours=1))

    assert run(None)["status"] == "sent"
    assert lines(tg)[1] == "- APT41: 0 -> 1 (Baru muncul)"


# --- kegagalan & kosong -------------------------------------------------------------------------


def test_a_week_without_any_actor_sends_nothing(tg: Telegram) -> None:
    add_article([], days_ago(2))  # artikel tanpa grup

    assert run() == {"status": "empty"}
    assert tg.alerts == []


def test_a_telegram_failure_is_not_swallowed(tg: Telegram) -> None:
    this_week("APT41")
    tg.fail = True

    with pytest.raises(ConnectionError):
        run()
