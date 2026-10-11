"""Unit test cache ringkasan newsletter (`generate_article_summary`, `_enrich_articles`,
`build_newsletter_context`) -- ROADMAP #22, PR 5. Tanpa DB: `AsyncNewsletterRepo` diganti repo di
memori, `fetch_article_body` dan klien LLM diganti stub yang menghitung panggilan.

Yang dijaga: baris cache ada = nol fetch dan nol LLM; `regenerate` melewatinya SEKALI per build;
`cve_ids` disimpan SEBELUM disaring true-positive dan irisannya dihitung tiap build; baris compact
tidak pernah fetch/LLM. Jalur yang sama lewat Postgres + HTTP ada di
`tests/integration/test_newsletter_router_snapshot.py`."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from cti_api.services import newsletter as newsletter_service

ALLOWLIST: dict[str, set[str]] = {"url_domains": set(), "email_domains": set(), "ips": set()}
BODY = "The actor used 203.0.113.77 and exploited CVE-2026-2222 against exposed servers."
SUMMARY_JSON = json.dumps({"key_points": ["p1", "p2"], "summary": "ringkasan satu"})

Rows = dict[tuple[int, str], SimpleNamespace]


class FakeLlm:
    """Klien OpenAI palsu: menghitung panggilan, membalas `content` yang bisa diganti per test."""

    def __init__(self, content: str = SUMMARY_JSON, *, with_usage: bool = True) -> None:
        self.calls = 0
        self.content = content
        self.with_usage = with_usage
        self.system_prompts: list[str] = []
        """Isi pesan `system` tiap panggilan, untuk memeriksa bahasa dan glosarium yang dikirim."""
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        self.system_prompts.append(kwargs["messages"][0]["content"])
        message = SimpleNamespace(content=self.content)
        completion = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        if self.with_usage:
            completion.usage = SimpleNamespace(
                prompt_tokens=11, completion_tokens=7, total_tokens=18
            )
        return completion


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> Rows:
    """Repo di memori menggantikan `AsyncNewsletterRepo`; dict-nya dikembalikan agar test bisa
    memeriksa dan mengisi baris cache langsung."""
    rows: Rows = {}

    class FakeRepo:
        def __init__(self, session: object) -> None:
            pass

        async def get_article_summary(self, article_id: int, language: str) -> Any:
            return rows.get((article_id, language))

        async def get_article_summaries(self, ids: list[int], language: str) -> dict[int, Any]:
            return {i: rows[(i, language)] for i in ids if (i, language) in rows}

        async def upsert_article_summary(
            self, *, article_id: int, language: str, **values: Any
        ) -> None:
            rows[(article_id, language)] = SimpleNamespace(
                article_id=article_id, language=language, **values
            )

    monkeypatch.setattr(newsletter_service, "AsyncNewsletterRepo", FakeRepo)
    return rows


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    fake = FakeLlm()
    monkeypatch.setattr(newsletter_service, "get_llm_client", lambda: (fake, "stub-model"))
    return fake


@pytest.fixture
def fetch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=(BODY, False))
    monkeypatch.setattr(newsletter_service, "fetch_article_body", mock)
    return mock


def _article(article_id: int = 7, title: str = "Patch CVE-2026-1111 now") -> dict[str, Any]:
    return {
        "id": article_id,
        "title": title,
        "url": f"https://example.com/{article_id}",
        "source": "gbhackers",
        "posted_on": "2026-10-02",
        "news_type": "vulnerability",
    }


async def _summary(article: dict[str, Any], *, regenerate: bool = False) -> dict[str, Any]:
    return await newsletter_service.generate_article_summary(
        MagicMock(), article, allowlist=ALLOWLIST, regenerate=regenerate
    )


# ── generate_article_summary ─────────────────────────────────────────────────


async def test_miss_fetches_summarizes_and_stores_everything_the_draft_will_need(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    result = await _summary(_article())

    fetch.assert_awaited_once()
    assert llm.calls == 1
    assert result["key_points"] == ["p1", "p2"]
    assert result["summary"] == "ringkasan satu"
    assert result["body_source"] == "fetched"
    assert result["iocs"]["ips"] == ["203.0.113.77"]
    # Judul + body, semuanya, belum disaring true-positive.
    assert result["cve_ids"] == ["CVE-2026-1111", "CVE-2026-2222"]

    row = cache[(7, "id")]  # tanpa `language` = default produk (Indonesia)
    assert row.language == "id"
    assert row.model == "stub-model"
    assert row.token_usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert (row.key_points, row.summary, row.body_source) == (
        ["p1", "p2"],
        "ringkasan satu",
        "fetched",
    )
    assert row.iocs == result["iocs"]
    assert row.cve_ids == result["cve_ids"]


async def test_hit_makes_no_fetch_and_no_llm_call(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    first = await _summary(_article())
    second = await _summary(_article())

    assert second == first
    fetch.assert_awaited_once()
    assert llm.calls == 1


async def test_regenerate_bypasses_the_cache_and_overwrites_the_row(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    await _summary(_article())
    llm.content = json.dumps({"key_points": ["baru"], "summary": "ringkasan dua"})

    fresh = await _summary(_article(), regenerate=True)

    assert fetch.await_count == 2
    assert llm.calls == 2
    assert fresh["summary"] == "ringkasan dua"
    assert cache[(7, "id")].summary == "ringkasan dua"
    assert len(cache) == 1  # menimpa, bukan baris kedua

    # Dan build berikutnya tanpa `regenerate` memakai hasil yang baru, tanpa panggilan lagi.
    again = await _summary(_article())
    assert again["summary"] == "ringkasan dua"
    assert fetch.await_count == 2
    assert llm.calls == 2


async def test_each_article_has_its_own_cache_row(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    await _summary(_article(1))
    await _summary(_article(2))
    await _summary(_article(1))

    assert llm.calls == 2
    assert sorted(cache) == [(1, "id"), (2, "id")]


async def test_without_a_readable_page_the_summary_comes_from_metadata_and_is_cached_as_such(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    fetch.return_value = (None, True)  # paywall

    result = await _summary(_article())

    assert result["body_source"] == "metadata"
    assert result["iocs"] == {}
    assert result["cve_ids"] == ["CVE-2026-1111"]  # hanya dari judul
    assert llm.calls == 1
    assert cache[(7, "id")].body_source == "metadata"


async def test_an_empty_llm_result_is_returned_but_not_cached(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    """Dulu LLM yang membalas kosong dicoba lagi build berikutnya; menyimpannya akan menempel."""
    llm.content = "{}"

    result = await _summary(_article())

    assert result["key_points"] == []
    assert result["summary"] == ""
    assert cache == {}

    llm.content = SUMMARY_JSON
    await _summary(_article())
    assert fetch.await_count == 2  # tidak ada hit, jadi dicoba lagi
    assert (7, "id") in cache


async def test_a_gateway_without_usage_still_caches_with_empty_token_usage(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    llm.with_usage = False

    await _summary(_article())

    assert cache[(7, "id")].token_usage == {}


async def test_token_usage_comes_from_usage_from_so_dict_and_partial_usage_are_kept(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pemakaian token dibaca `cti_core.llm.client.usage_from` (satu pembaca untuk semua LLM):
    gateway yang membalas `usage` berupa dict, atau hanya sebagian field, tetap tercatat."""

    def create(**kwargs: Any) -> SimpleNamespace:
        message = SimpleNamespace(content=SUMMARY_JSON)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_tokens": 5, "completion_tokens": None},
        )

    llm.chat.completions.create = create
    await _summary(_article())

    assert cache[(7, "id")].token_usage == {"prompt_tokens": 5}


# ── Ekstraksi CVE id ─────────────────────────────────────────────────────────


def test_extract_cve_ids_reads_title_and_body_uppercases_dedupes_and_sorts() -> None:
    found = newsletter_service._extract_cve_ids(
        "Patch cve-2026-0002 now",
        "Exploits for CVE-2026-0002 and CVE-2025-12345 and cve-2026-0001.",
    )
    assert found == ["CVE-2025-12345", "CVE-2026-0001", "CVE-2026-0002"]


def test_extract_cve_ids_without_body_or_matches_is_empty() -> None:
    assert newsletter_service._extract_cve_ids("No identifiers here", None) == []
    assert newsletter_service._extract_cve_ids("", "") == []


def test_find_cve_mentions_is_the_sorted_intersection_with_the_true_positive_set() -> None:
    cached = ["CVE-2026-0003", "CVE-2026-0001", "CVE-2026-0002"]
    assert newsletter_service._find_cve_mentions(cached, {"CVE-2026-0002", "CVE-2026-0003"}) == [
        "CVE-2026-0002",
        "CVE-2026-0003",
    ]
    assert newsletter_service._find_cve_mentions(cached, set()) == []
    assert newsletter_service._find_cve_mentions([], {"CVE-2026-0001"}) == []


# ── _enrich_articles ─────────────────────────────────────────────────────────


@pytest.fixture
def tp_set(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """Set true-positive yang bisa diubah test di tengah jalan (tanpa DB)."""
    tp: set[str] = set()
    monkeypatch.setattr(newsletter_service, "_get_tp_cve_ids", AsyncMock(side_effect=lambda s: tp))
    monkeypatch.setattr(
        newsletter_service, "_get_allowlist_sets", AsyncMock(return_value=ALLOWLIST)
    )
    return tp


async def test_cve_mentions_are_the_cached_ids_intersected_with_the_current_tp_set(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock, tp_set: set[str]
) -> None:
    tp_set.add("CVE-2026-2222")
    [first] = await newsletter_service._enrich_articles(MagicMock(), [_article()])
    assert first["cve_mentions"] == ["CVE-2026-2222"]
    assert first["possibly_exploited_wild"] is True
    assert cache[(7, "id")].cve_ids == ["CVE-2026-1111", "CVE-2026-2222"]  # tidak tersaring

    # Set true-positive berubah (CVE lain mulai di-track, yang tadi ditandai FP): build kedua
    # memakai cache (nol fetch/LLM) tapi hasilnya mengikuti set yang SEKARANG.
    tp_set.clear()
    tp_set.add("CVE-2026-1111")
    [second] = await newsletter_service._enrich_articles(MagicMock(), [_article()])
    assert second["cve_mentions"] == ["CVE-2026-1111"]
    fetch.assert_awaited_once()
    assert llm.calls == 1

    tp_set.clear()
    [third] = await newsletter_service._enrich_articles(MagicMock(), [_article()])
    assert third["cve_mentions"] == []
    assert third["possibly_exploited_wild"] is False


async def test_enriched_article_keeps_the_keys_the_template_and_history_read(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock, tp_set: set[str]
) -> None:
    [enriched] = await newsletter_service._enrich_articles(MagicMock(), [_article()])

    for key in ("title", "url", "source", "posted_on", "news_type"):
        assert enriched[key] == _article()[key]
    assert {"key_points", "summary", "body_source", "iocs"} <= set(enriched)
    assert {"cve_mentions", "possibly_exploited_wild"} <= set(enriched)


async def test_regenerate_is_spent_on_the_first_occurrence_only(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock, tp_set: set[str]
) -> None:
    await _summary(_article())  # cache sudah ada
    fetch.reset_mock()
    llm.calls = 0

    await newsletter_service._enrich_articles(MagicMock(), [_article(), _article()], regenerate=[7])

    fetch.assert_awaited_once()  # kemunculan kedua sudah memakai baris yang baru ditulis
    assert llm.calls == 1


async def test_regenerate_only_touches_the_listed_articles(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock, tp_set: set[str]
) -> None:
    await newsletter_service._enrich_articles(MagicMock(), [_article(1), _article(2)])
    fetch.reset_mock()
    llm.calls = 0

    await newsletter_service._enrich_articles(
        MagicMock(), [_article(1), _article(2)], regenerate=[2, 999]
    )

    assert fetch.await_count == 1
    assert llm.calls == 1


# ── build_newsletter_context ─────────────────────────────────────────────────


@pytest.fixture
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime.datetime]:
    """`_now()` dipin lewat daftar satu elemen (diganti test) + zona laporan WIB tanpa env."""
    now = [datetime.datetime(2026, 11, 2, 2, 0, tzinfo=datetime.UTC)]
    monkeypatch.setattr(newsletter_service, "_now", lambda: now[0])
    settings = SimpleNamespace(worker=SimpleNamespace(report_utc_offset_hours=7))
    monkeypatch.setattr(newsletter_service, "get_settings", lambda: settings)
    return now


@pytest.fixture
def enrich_passthrough(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """`_enrich_articles` yang mengembalikan artikelnya apa adanya, supaya test konteks tidak
    ikut menguji cache."""
    mock = AsyncMock(side_effect=lambda session, articles, **kw: [dict(a) for a in articles])
    monkeypatch.setattr(newsletter_service, "_enrich_articles", mock)
    return mock


async def test_context_period_defaults_to_the_previous_month_of_the_pinned_clock(
    cache: Rows, fixed_clock: list[datetime.datetime], enrich_passthrough: AsyncMock
) -> None:
    ctx = await newsletter_service.build_newsletter_context(MagicMock(), _article(), [], [], [])

    assert ctx["period_start"] == datetime.date(2026, 10, 1)
    assert ctx["period_end"] == datetime.date(2026, 10, 31)
    assert ctx["period_label"] == "October 2026"
    # week/year tetap minggu ISO dari waktu pembuatan, persis seperti sebelumnya.
    assert (ctx["year"], ctx["week"]) == (2026, 45)
    assert ctx["generated_at"] == "2026-11-02 02:00 UTC"


async def test_context_period_in_january_is_december_of_the_previous_year(
    cache: Rows, fixed_clock: list[datetime.datetime], enrich_passthrough: AsyncMock
) -> None:
    fixed_clock[0] = datetime.datetime(2027, 1, 4, 2, 0, tzinfo=datetime.UTC)

    ctx = await newsletter_service.build_newsletter_context(MagicMock(), _article(), [], [], [])

    assert (ctx["period_start"], ctx["period_end"]) == (
        datetime.date(2026, 12, 1),
        datetime.date(2026, 12, 31),
    )
    assert ctx["period_label"] == "December 2026"


async def test_context_uses_the_requested_period_instead_of_the_default(
    cache: Rows, fixed_clock: list[datetime.datetime], enrich_passthrough: AsyncMock
) -> None:
    ctx = await newsletter_service.build_newsletter_context(
        MagicMock(),
        _article(),
        [],
        [],
        [],
        period_start=datetime.date(2026, 9, 28),
        period_end=datetime.date(2026, 10, 4),
    )

    assert ctx["period_start"] == datetime.date(2026, 9, 28)
    assert ctx["period_label"] == "September - October 2026"


async def test_highlights_accept_one_dict_or_a_list_and_the_first_stays_the_old_key(
    cache: Rows, fixed_clock: list[datetime.datetime], enrich_passthrough: AsyncMock
) -> None:
    legacy = await newsletter_service.build_newsletter_context(MagicMock(), _article(1), [], [], [])
    assert legacy["highlight"]["id"] == 1
    assert [h["id"] for h in legacy["highlights"]] == [1]

    tiered = await newsletter_service.build_newsletter_context(
        MagicMock(), [_article(1), _article(2)], [_article(3)], [], []
    )
    assert tiered["highlight"]["id"] == 1  # yang dirender template lama
    assert [h["id"] for h in tiered["highlights"]] == [1, 2]
    assert [a["id"] for a in tiered["apac"]] == [3]


async def test_a_context_without_any_highlight_is_refused(
    cache: Rows, fixed_clock: list[datetime.datetime], enrich_passthrough: AsyncMock
) -> None:
    with pytest.raises(ValueError, match="highlight"):
        await newsletter_service.build_newsletter_context(MagicMock(), [], [], [], [])


async def test_analyst_notes_reach_full_cards_in_every_tier_position(
    cache: Rows, fixed_clock: list[datetime.datetime], enrich_passthrough: AsyncMock
) -> None:
    ctx = await newsletter_service.build_newsletter_context(
        MagicMock(),
        [_article(1), _article(2)],
        [_article(3)],
        [],
        [],
        notes={"2": "catatan highlight", "3": "catatan apac"},
    )

    assert ctx["highlights"][0].get("analyst_note") is None
    assert ctx["highlights"][1]["analyst_note"] == "catatan highlight"
    assert ctx["apac"][0]["analyst_note"] == "catatan apac"


async def test_compact_rows_come_from_the_article_row_and_never_fetch_or_call_the_llm(
    cache: Rows,
    fixed_clock: list[datetime.datetime],
    enrich_passthrough: AsyncMock,
    llm: FakeLlm,
    fetch: AsyncMock,
) -> None:
    cache[(30, "id")] = SimpleNamespace(
        article_id=30, language="id", key_points=["dari cache"], summary="ringkasan cache"
    )

    ctx = await newsletter_service.build_newsletter_context(
        MagicMock(),
        _article(1),
        [],
        [],
        [],
        compact={"apac": [_article(30), _article(31)], "indonesia": [_article(32)]},
    )

    fetch.assert_not_awaited()
    assert llm.calls == 0
    # Artikel compact tidak ikut `_enrich_articles` (yang memanggil fetch/LLM): hanya highlight.
    assert [a["id"] for a in enrich_passthrough.await_args.args[1]] == [1]

    cached_row, plain_row = ctx["apac_compact"]
    assert cached_row == {
        "id": 30,
        "title": "Patch CVE-2026-1111 now",
        "url": "https://example.com/30",
        "source": "gbhackers",
        "posted_on": "2026-10-02",
        "news_type": "vulnerability",
        "key_points": ["dari cache"],
        "summary": "ringkasan cache",
    }
    assert "summary" not in plain_row and "key_points" not in plain_row
    assert plain_row["id"] == 31
    assert ctx["global_news_compact"] == []
    assert [r["id"] for r in ctx["indonesia_compact"]] == [32]
    # Kartu penuh tidak terpengaruh baris compact.
    assert ctx["apac"] == [] and ctx["indonesia"] == []


async def test_context_without_compact_has_empty_compact_lists(
    cache: Rows, fixed_clock: list[datetime.datetime], enrich_passthrough: AsyncMock
) -> None:
    ctx = await newsletter_service.build_newsletter_context(MagicMock(), _article(), [], [], [])

    assert ctx["apac_compact"] == ctx["global_news_compact"] == ctx["indonesia_compact"] == []


async def test_regenerate_ids_are_passed_on_to_enrichment(
    cache: Rows, fixed_clock: list[datetime.datetime], enrich_passthrough: AsyncMock
) -> None:
    await newsletter_service.build_newsletter_context(
        MagicMock(), _article(), [], [], [], regenerate=[7, 9]
    )

    assert enrich_passthrough.await_args.kwargs["regenerate"] == [7, 9]


# ── Bahasa ringkasan (ROADMAP #22, PR template) ──────────────────────────────


def test_the_request_defaults_to_indonesian_and_accepts_only_id_or_en() -> None:
    from cti_api.schemas.newsletter import DEFAULT_SUMMARY_LANGUAGE, NewsletterSectionsBody
    from pydantic import ValidationError

    assert DEFAULT_SUMMARY_LANGUAGE == "id"
    assert NewsletterSectionsBody(highlight=1).language == "id"
    assert NewsletterSectionsBody(highlight=1, language="en").language == "en"
    with pytest.raises(ValidationError):
        NewsletterSectionsBody(highlight=1, language="fr")  # type: ignore[arg-type]


async def test_the_indonesian_prompt_asks_for_indonesian_keeps_names_and_carries_the_glossary(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    from cti_api.services import newsletter_glossary

    await _summary(_article())

    [prompt] = llm.system_prompts  # satu panggilan: tanpa panggilan terjemahan kedua
    assert llm.calls == 1
    assert "Indonesian (Bahasa Indonesia)" in prompt
    assert "Keep the JSON keys exactly as shown" in prompt
    assert '"key_points"' in prompt and '"summary"' in prompt
    assert "CVE identifiers" in prompt and "MITRE ATT&CK technique names and IDs" in prompt
    assert "indicators of compromise (IP addresses" in prompt
    for english, indonesian in newsletter_glossary.TRANSLATIONS:
        assert f"- {english}: {indonesian}" in prompt
    for term in newsletter_glossary.KEEP_IN_ENGLISH:
        assert term in prompt
    assert "<<language>>" not in prompt  # slot terisi, tidak bocor ke model


async def test_the_metadata_only_prompt_gets_the_same_language_block_and_keeps_its_habit(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    fetch.return_value = (None, True)  # paywall -> ringkasan dari metadata

    await _summary(_article())

    [prompt] = llm.system_prompts
    assert "Indonesian (Bahasa Indonesia)" in prompt
    assert "- vulnerability: kerentanan" in prompt
    # Perilaku prompt metadata-only dipertahankan; `body_source` di cache yang menandainya.
    assert "generate plausible key points" in prompt
    assert "Do not mention that the article was paywalled" in prompt
    assert cache[(7, "id")].body_source == "metadata"


async def test_the_english_prompt_asks_for_english_and_has_no_glossary(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    await newsletter_service.generate_article_summary(
        MagicMock(), _article(), allowlist=ALLOWLIST, language="en"
    )

    [prompt] = llm.system_prompts
    assert "in English, in a clear, professional register" in prompt
    assert "Indonesian" not in prompt and "kerentanan" not in prompt
    assert "monthly newsletter" in prompt and "weekly" not in prompt


async def test_each_language_has_its_own_cache_row_and_never_reuses_the_other(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    indonesian = await _summary(_article())
    llm.content = json.dumps({"key_points": ["a"], "summary": "english summary"})
    english = await newsletter_service.generate_article_summary(
        MagicMock(), _article(), allowlist=ALLOWLIST, language="en"
    )

    # Baris `id` bukan hit untuk permintaan `en`: fetch + LLM jalan lagi, dan tidak menimpa.
    assert (llm.calls, fetch.await_count) == (2, 2)
    assert sorted(cache) == [(7, "en"), (7, "id")]
    assert cache[(7, "id")].summary == indonesian["summary"] == "ringkasan satu"
    assert cache[(7, "en")].summary == english["summary"] == "english summary"

    # Sesudahnya keduanya hit.
    await _summary(_article())
    await newsletter_service.generate_article_summary(
        MagicMock(), _article(), allowlist=ALLOWLIST, language="en"
    )
    assert (llm.calls, fetch.await_count) == (2, 2)


async def test_regenerate_rebuilds_only_the_requested_language(
    cache: Rows, llm: FakeLlm, fetch: AsyncMock
) -> None:
    await _summary(_article())
    await newsletter_service.generate_article_summary(
        MagicMock(), _article(), allowlist=ALLOWLIST, language="en"
    )
    llm.content = json.dumps({"key_points": ["baru"], "summary": "ringkasan baru"})

    await _summary(_article(), regenerate=True)

    assert cache[(7, "id")].summary == "ringkasan baru"
    assert cache[(7, "en")].summary == "ringkasan satu"  # bahasa lain tidak tersentuh


async def test_the_language_reaches_enrichment_and_the_compact_row_lookup(
    cache: Rows,
    fixed_clock: list[datetime.datetime],
    enrich_passthrough: AsyncMock,
) -> None:
    cache[(30, "en")] = SimpleNamespace(
        article_id=30, language="en", key_points=["en kp"], summary="english summary"
    )
    compact = {"apac": [_article(30)]}

    english = await newsletter_service.build_newsletter_context(
        MagicMock(), _article(1), [], [], [], compact=compact, language="en"
    )
    indonesian = await newsletter_service.build_newsletter_context(
        MagicMock(), _article(1), [], [], [], compact=compact
    )

    assert enrich_passthrough.await_args_list[0].kwargs["language"] == "en"
    assert enrich_passthrough.await_args_list[1].kwargs["language"] == "id"
    # Ringkasan compact yang di-cache hanya terbaca dalam bahasa yang diminta.
    assert english["apac_compact"][0]["summary"] == "english summary"
    assert "summary" not in indonesian["apac_compact"][0]
    assert (english["language"], indonesian["language"]) == ("en", "id")
