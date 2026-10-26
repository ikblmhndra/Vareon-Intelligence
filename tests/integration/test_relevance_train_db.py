"""`run_training` -- Postgres REAL (testcontainers), FakeEmbedder."""

from __future__ import annotations

import datetime as dt
import threading

from cti_core.config import RelevanceSettings
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.relevance import RelevanceModel
from cti_enrich.relevance.dataset import load_examples
from cti_enrich.relevance.train import run_training
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tests.unit.relevance_fakes import FakeEmbedder

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.UTC)
BP = "Security Technology & Best Practices"

# Kosakata tiap kelas sengaja terpisah jelas supaya holdout mudah lolos.
VOCAB = {
    "reject": ["recipe", "football", "celebrity", "holiday", "concert", "weather", "fashion"],
    "best_practice": ["hardening", "checklist", "guideline", "framework", "baseline", "policy"],
    "threat_news": ["ransomware", "breach", "exploit", "malware", "botnet", "zeroday", "attack"],
}
SMALL = RelevanceSettings(train_min_examples=60, train_min_per_class=20)


def _title(label: str, n: int) -> str:
    words = VOCAB[label]
    a, b, c = (words[(n + k) % len(words)] for k in (0, 2, 3))
    return f"{a} {b} {c} x{label[0]}{n}"


def _seed(session: Session, per_class: int = 40) -> None:
    session.execute(delete(Article))
    session.execute(delete(RejectedArticle))
    rows: list[object] = []
    for n in range(per_class):
        rows.append(
            Article(
                url=f"https://tr.example/t{n}", url_hash=f"tr-t{n}",
                title=_title("threat_news", n), source="T",
                first_seen_at=NOW, last_seen_at=NOW, seen_count=1, news_type="Ransomware",
            )
        )  # fmt: skip
        rows.append(
            Article(
                url=f"https://tr.example/b{n}", url_hash=f"tr-b{n}",
                title=_title("best_practice", n), source="T",
                first_seen_at=NOW, last_seen_at=NOW, seen_count=1, news_type=BP,
            )
        )  # fmt: skip
        rows.append(
            RejectedArticle(
                url=f"https://tr.example/r{n}", url_hash=f"tr-r{n}",
                title=_title("reject", n), source="T", reason="not cyber", rejected_at=NOW,
            )
        )  # fmt: skip
    # Override analis harus menang -> best_practice; keputusan gerbang harus dikeluarkan.
    rows.append(
        Article(
            url="https://tr.example/ov", url_hash="tr-ov", title="override judul unik zzz",
            source="T", first_seen_at=NOW, last_seen_at=NOW, seen_count=1, news_type="Ransomware",
            overrides={"news_type": BP},
        )
    )  # fmt: skip
    rows.append(
        Article(
            url="https://tr.example/gate", url_hash="tr-gate", title="judul gerbang unik yyy",
            source="T", first_seen_at=NOW, last_seen_at=NOW, seen_count=1, news_type="Ransomware",
            raw_enrichment={"classify": {"skipped": "relevance_gate"}},
        )
    )  # fmt: skip
    session.add_all(rows)
    session.flush()


def _active_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(RelevanceModel)
            .where(RelevanceModel.status == "active")
        )
        or 0
    )


def test_seed_exercises_json_extraction(db_session: Session) -> None:
    _seed(db_session)
    by_title = {e.title: e.label for e in load_examples(db_session)}
    assert by_title["override judul unik zzz"] == "best_practice"
    assert "judul gerbang unik yyy" not in by_title


def test_run_training_activates(db_session: Session) -> None:
    db_session.execute(delete(RelevanceModel))
    _seed(db_session)
    out = run_training(db_session, FakeEmbedder(), SMALL, NOW)
    assert out.status == "active", out.reason
    assert out.model_id is not None
    assert out.metrics["agreement"] >= 0.95
    assert out.metrics["holdout_kind"] == "stratified"
    assert _active_count(db_session) == 1


def test_run_training_skipped_below_minimum(db_session: Session) -> None:
    db_session.execute(delete(RelevanceModel))
    _seed(db_session)
    cfg = RelevanceSettings(train_min_examples=10_000)
    out = run_training(db_session, FakeEmbedder(), cfg, NOW)
    assert out.status == "skipped"
    assert db_session.scalar(select(func.count()).select_from(RelevanceModel)) == 0


def test_run_training_rejected_keeps_previous(db_session: Session) -> None:
    db_session.execute(delete(RelevanceModel))
    _seed(db_session)
    first = run_training(db_session, FakeEmbedder(), SMALL, NOW)
    assert first.status == "active"
    strict = RelevanceSettings(
        train_min_examples=60, train_min_per_class=20, gate_min_agreement=1.01
    )
    second = run_training(db_session, FakeEmbedder(), strict, NOW)
    assert second.status == "rejected"
    assert second.reason and "agreement" in second.reason
    rows = {r.id: r.status for r in db_session.execute(select(RelevanceModel)).scalars()}
    assert rows[first.model_id] == "active"
    assert rows[second.model_id] == "rejected"


def test_run_training_dry_run_writes_nothing(db_session: Session) -> None:
    db_session.execute(delete(RelevanceModel))
    _seed(db_session)
    out = run_training(db_session, FakeEmbedder(), SMALL, NOW, dry_run=True)
    assert out.status == "active"
    assert out.model_id is None
    assert db_session.scalar(select(func.count()).select_from(RelevanceModel)) == 0


def test_concurrent_training_one_active(_migrated_schema: None) -> None:
    with sync_session() as session:
        session.execute(delete(RelevanceModel))
        _seed(session)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    statuses: list[str] = []

    def worker() -> None:
        try:
            with sync_session() as session:
                barrier.wait(timeout=10)
                out = run_training(session, FakeEmbedder(), SMALL, dt.datetime.now(dt.UTC))
                statuses.append(out.status)
        except BaseException as exc:
            errors.append(exc)

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        assert not errors
        assert statuses == ["active", "active"]
        with sync_session() as session:
            assert _active_count(session) == 1
            assert session.scalar(select(func.count()).select_from(RelevanceModel)) == 2
    finally:
        with sync_session() as session:
            session.execute(delete(RelevanceModel))
            session.execute(delete(Article))
            session.execute(delete(RejectedArticle))
