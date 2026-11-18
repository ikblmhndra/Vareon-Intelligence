"""`to_examples` -- aturan label spec 6 (murni, tanpa DB)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from cti_enrich.relevance.dataset import BEST_PRACTICE, LabelRow, to_examples

T1 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
T2 = T1 + dt.timedelta(days=1)


def _art(title: str = "A title", **kw: Any) -> LabelRow:
    base: dict[str, Any] = {
        "title": title, "kind": "article", "news_type": "Threat News",
        "override_news_type": None, "audit": None, "reason": None,
        "failure_kind": None, "at": T1,
    }  # fmt: skip
    base.update(kw)
    return LabelRow(**base)


def _rej(title: str = "Rejected one", **kw: Any) -> LabelRow:
    return _art(title, **{"kind": "rejected", "news_type": None, "reason": "not cyber", **kw})


def test_best_practice_and_threat_news_labels() -> None:
    rows = [
        _art("bp", news_type=BEST_PRACTICE),
        _art("restored", news_type="Manually Restored"),
        _art("other", news_type="Ransomware"),
        _art("none", news_type=None),
    ]
    got = {e.title: e.label for e in to_examples(rows)}
    assert got == {
        "bp": "best_practice", "restored": "threat_news",
        "other": "threat_news", "none": "threat_news",
    }  # fmt: skip


def test_override_news_type_wins() -> None:
    rows = [
        _art("a", news_type="Ransomware", override_news_type=BEST_PRACTICE),
        _art("b", news_type=BEST_PRACTICE, override_news_type="Ransomware"),
    ]
    got = {e.title: e.label for e in to_examples(rows)}
    assert got == {"a": "best_practice", "b": "threat_news"}


def test_rejected_label_and_failed_excluded() -> None:
    rows = [
        _rej("plain"),
        _rej("transient", failure_kind="transient"),
        _rej("legacy", reason="[enrichment_failed] 503"),
    ]
    got = {e.title: e.label for e in to_examples(rows)}
    assert got == {"plain": "reject"}


def test_skipped_and_inherited_excluded() -> None:
    rows = [
        _art("g1", audit={"skipped": "relevance_gate"}),
        _art("g2", audit={"skipped": "default_relevance=always"}),
        _rej("i1", audit={"inherited_from_story": 3}),
        _art("ok", audit={"related_cyber": True}),
    ]
    assert [e.title for e in to_examples(rows)] == ["ok"]


def test_analyst_decisions_are_labels() -> None:
    """P7g: analis menerima/menolak job `classify` = putusan manusia, label yang sah (spec 4.3)."""
    rows = [
        _art("accepted", audit={"skipped": "analyst"}),
        _rej("rejected", reason="analyst", audit={"skipped": "analyst"}),
    ]
    got = {e.title: e.label for e in to_examples(rows)}
    assert got == {"accepted": "threat_news", "rejected": "reject"}


def test_dedup_latest_wins() -> None:
    rows = [_rej("PHP2Shell  flaw", at=T1), _art("php2shell flaw", at=T2)]
    out = to_examples(rows)
    assert len(out) == 1
    assert out[0].label == "threat_news"
    assert out[0].title == "php2shell flaw"  # judul asli baris terbaru
    assert out[0].at == T2


def test_dedup_tie_keeps_later_in_iteration() -> None:
    out = to_examples([_rej("Same", at=T1), _art("same", at=T1)])
    assert [e.label for e in out] == ["threat_news"]


# ── tweet (spec tweet-llm-cost, Part C) ──────────────────────────────────────────────────


def _verdict(text: str, related: bool, at: dt.datetime = T1) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(text=text, related_cyber=related, created_at=at, source="llm")


def _fake_verdict_repo(monkeypatch: Any, rows: list[Any]) -> list[Any]:
    """`TweetVerdictRepo` palsu yang hanya punya `llm_rows`: sumber data lain akan error."""
    import cti_enrich.relevance.dataset as dataset

    sessions: list[Any] = []

    class _Repo:
        def __init__(self, session: Any) -> None:
            sessions.append(session)

        def llm_rows(self, since: dt.datetime | None = None) -> list[Any]:
            return rows

    monkeypatch.setattr(dataset, "TweetVerdictRepo", _Repo)
    return sessions


def test_tweet_examples_use_llm_rows_only(monkeypatch: Any) -> None:
    from cti_enrich.relevance.dataset import load_tweet_examples

    session = object()
    rows = [
        _verdict("LockBit  claims ACME", True, at=T2),
        _verdict("lockbit claims acme", False, at=T1),  # duplikat ternormalisasi, lebih tua
        _verdict("Lunch thread", False),
    ]
    sessions = _fake_verdict_repo(monkeypatch, rows)

    got = load_tweet_examples(session)  # type: ignore[arg-type]

    assert sessions == [session]
    assert sorted((e.title, e.label, e.at) for e in got) == [
        ("LockBit  claims ACME", "threat_news", T2),
        ("Lunch thread", "reject", T1),
    ]


def test_tweet_labels_are_binary(monkeypatch: Any) -> None:
    from cti_enrich.relevance.dataset import load_tweet_examples
    from cti_enrich.relevance.model import KIND_CLASSES

    rows = [_verdict(f"tweet {i}", i % 2 == 0) for i in range(10)]
    _fake_verdict_repo(monkeypatch, rows)

    labels = {e.label for e in load_tweet_examples(object())}  # type: ignore[arg-type]

    assert labels == set(KIND_CLASSES["tweet"]) == {"reject", "threat_news"}
