"""RelevanceModelRepo -- model relevansi lokal + status gate (P5).

Repo sync dipakai worker (latih, gate); repo async dipakai API (Data health). Method tulis
tidak commit: caller yang memegang transaksi (sama seperti `StoryRepo`).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.relevance import RelevanceModel

RELEVANCE_LOCK_NAMESPACE = 7_311_003
"""Namespace kunci advisory latih/aktivasi model relevansi; bersebelahan dengan
`STORY_LOCK_NAMESPACE = 7_311_002` (resolver story) dan `_URL_LOCK_NAMESPACE = 7_311_001`.
Beda namespace supaya ketiganya tidak saling bentur."""

_LOCK_KEYS = {"article": 0, "tweet": 1}
"""Kunci kedua advisory per kind; `article` tetap 0 (sama dengan kunci sebelum ada `kind`)
supaya latih artikel lama dan baru tetap saling mengunci selama deploy bergulir."""

_STATUSES = ("active", "retired", "rejected")
_GATE_STATES = ("shadow", "gate")


_BEST_PRACTICE = "Security Technology & Best Practices"
"""Salinan `cti_enrich.relevance.dataset.BEST_PRACTICE` (cti_core tidak boleh mengimpor
cti_enrich); vonis LLM `best_practice` dibaca dari `articles.news_type`."""

_BAND_UNION_SQL = """
    SELECT created_at AS ts, (news_type IS DISTINCT FROM :bp) AS agree,
           raw_enrichment->'relevance'->>'decision' AS decision
    FROM articles
    WHERE raw_enrichment->'relevance'->>'in_band' = 'true'
      AND raw_enrichment->'relevance'->>'decision' IN ('shadow', 'audit')
    UNION ALL
    SELECT rejected_at AS ts, false AS agree,
           raw_enrichment->'relevance'->>'decision' AS decision
    FROM rejected_articles
    WHERE raw_enrichment->'relevance'->>'in_band' = 'true'
      AND raw_enrichment->'relevance'->>'decision' IN ('shadow', 'audit')
      AND failure_kind IS NULL
      AND COALESCE(reason, '') NOT LIKE '[enrichment_failed]%'
"""
"""Satu teks SQL untuk repo sync (gate, worker) dan async (Data health): angka yang dilihat
operator dan yang dipakai gate tidak boleh berbeda."""

_TWEET_BAND_SQL = """
    SELECT created_at AS ts, related_cyber AS agree, relevance->>'decision' AS decision
    FROM tweet_verdicts
    WHERE source = 'llm'
      AND relevance->>'in_band' = 'true'
      AND relevance->>'decision' IN ('shadow', 'audit')
"""
"""Padanan `_BAND_UNION_SQL` untuk model tweet: vonis LLM di `tweet_verdicts`, setuju =
`related_cyber`. `relevance` yang dicatat `None` tersimpan sebagai JSON `null` (bukan SQL NULL);
`->>` pada JSON `null` maupun SQL NULL sama-sama menghasilkan NULL, jadi keduanya tersaring."""


def _band_count_sql(band: str) -> str:
    return f"SELECT count(*), count(*) FILTER (WHERE agree) FROM ({band}) r WHERE ts >= :since"


def _audit_last_sql(band: str) -> str:
    return (
        f"SELECT agree FROM ({band}) r WHERE decision = 'audit' "
        "AND (CAST(:audit_since AS timestamptz) IS NULL "
        "OR ts >= CAST(:audit_since AS timestamptz)) "
        "ORDER BY ts DESC LIMIT :n"
    )


_BAND_COUNT_SQL = _band_count_sql(_BAND_UNION_SQL)
_AUDIT_LAST_SQL = _audit_last_sql(_BAND_UNION_SQL)
"""`:audit_since` NULL = tanpa batas waktu: itu yang dipakai tampilan Data health (N audit
terakhir apa adanya). Gate memakai `gate_changed_at` supaya sampel basi dari periode gate
sebelumnya tidak membalik gate lagi."""
_TWEET_BAND_COUNT_SQL = _band_count_sql(_TWEET_BAND_SQL)
_TWEET_AUDIT_LAST_SQL = _audit_last_sql(_TWEET_BAND_SQL)
_MIDDLE_BAND_SQL = """
    SELECT (SELECT count(*) FROM articles WHERE created_at >= :since
              AND raw_enrichment->'relevance'->>'in_band' = 'false')
         + (SELECT count(*) FROM rejected_articles WHERE rejected_at >= :since
              AND raw_enrichment->'relevance'->>'in_band' = 'false')
"""
_GATED_SQL = """
    SELECT count(*) FROM articles WHERE created_at >= :since
      AND raw_enrichment->'relevance'->>'decision' = 'gated'
"""
_TWEET_MIDDLE_BAND_SQL = """
    SELECT count(*) FROM tweet_verdicts WHERE created_at >= :since AND source = 'llm'
      AND relevance->>'in_band' = 'false'
"""
_TWEET_GATED_SQL = """
    SELECT count(*) FROM tweet_verdicts WHERE created_at >= :since AND source = 'gate'
"""
"""Padanan tweet: vonis `gate` = classify yang dilewati; luar band = vonis LLM dengan
`in_band` false (selalu ke LLM)."""


@dataclass(frozen=True)
class GateStats:
    """Ukuran kesepakatan band model dengan LLM. `audit_last`: sampel audit terbaru lebih dulu,
    True = LLM setuju `threat_news`."""

    band_n: int
    band_agree: int
    audit_last: list[bool]


def check_kind(kind: str) -> str:
    """`ValueError` kalau bukan kind yang dikenal (cermin CHECK `kind_valid`)."""
    if kind not in _LOCK_KEYS:
        raise ValueError(f"kind model relevansi tidak dikenal: {kind!r}")
    return kind


def _gate_queries(kind: str) -> tuple[str, str, dict[str, Any]]:
    """`(SQL hitungan band, SQL audit terakhir, parameter tambahan)` per kind model. Satu sumber
    untuk repo sync dan async supaya Data health dan gate memakai angka yang sama."""
    if check_kind(kind) == "tweet":
        return _TWEET_BAND_COUNT_SQL, _TWEET_AUDIT_LAST_SQL, {}
    return _BAND_COUNT_SQL, _AUDIT_LAST_SQL, {"bp": _BEST_PRACTICE}


def check_status(status: str) -> str:
    """`ValueError` kalau bukan status yang dikenal (konvensi `role` mention negara)."""
    if status not in _STATUSES:
        raise ValueError(f"status model relevansi tidak dikenal: {status!r}")
    return status


class RelevanceModelRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock(self, kind: str = "article") -> None:
        """Kunci advisory tingkat transaksi: satu latih/aktivasi sekaligus PER kind, supaya dua
        worker tidak sama-sama membuat baris `active` untuk kind yang sama, sementara latih
        artikel dan tweet tidak saling menunggu."""
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, :k)"),
            {"ns": RELEVANCE_LOCK_NAMESPACE, "k": _LOCK_KEYS[check_kind(kind)]},
        )

    def get_active(self, kind: str = "article") -> RelevanceModel | None:
        return self.session.execute(
            select(RelevanceModel).where(
                RelevanceModel.status == "active", RelevanceModel.kind == kind
            )
        ).scalar_one_or_none()

    def add_rejected(
        self,
        *,
        feature_version: str,
        n_examples: int,
        class_counts: dict[str, int],
        metrics: dict[str, Any],
        reason: str,
        kind: str = "article",
    ) -> int:
        row = RelevanceModel(
            kind=check_kind(kind),
            status=check_status("rejected"),
            feature_version=feature_version,
            n_examples=n_examples,
            class_counts=class_counts,
            metrics=metrics,
            gate_state="shadow",
            reason=reason,
        )
        self.session.add(row)
        self.session.flush()
        return row.id

    def activate(
        self,
        *,
        artifact: bytes,
        feature_version: str,
        n_examples: int,
        class_counts: dict[str, int],
        metrics: dict[str, Any],
        now: datetime.datetime,
        kind: str = "article",
    ) -> int:
        """Pensiunkan model aktif KIND INI lalu sisipkan yang baru; `gate_state` dan
        `gate_changed_at` diwarisi (default `shadow`/NULL). Urutan penting: indeks unik parsial
        menolak dua baris `active` sekaligus, jadi yang lama harus `retired` dulu. `now` belum
        dipakai kolom apa pun (created_at server-side); tetap diterima agar antarmuka sama dengan
        `set_gate_state`."""
        check_kind(kind)
        current = self.get_active(kind)
        gate_state, gate_changed_at = "shadow", None
        if current is not None:
            gate_state, gate_changed_at = current.gate_state, current.gate_changed_at
            current.status = check_status("retired")
            self.session.flush()
        row = RelevanceModel(
            kind=kind,
            status=check_status("active"),
            artifact=artifact,
            feature_version=feature_version,
            n_examples=n_examples,
            class_counts=class_counts,
            metrics=metrics,
            gate_state=gate_state,
            gate_changed_at=gate_changed_at,
        )
        self.session.add(row)
        self.session.flush()
        return row.id

    def set_gate_state(
        self, model_id: int, state: Literal["shadow", "gate"], now: datetime.datetime
    ) -> None:
        if state not in _GATE_STATES:
            raise ValueError(f"gate_state tidak dikenal: {state!r}")
        self.session.execute(
            update(RelevanceModel)
            .where(RelevanceModel.id == model_id)
            .values(gate_state=state, gate_changed_at=now)
        )

    def gate_stats(
        self,
        *,
        since: datetime.datetime,
        revert_samples: int,
        audit_since: datetime.datetime | None = None,
        kind: str = "article",
    ) -> GateStats:
        """Hitung baris dalam band (`in_band` true, keputusan shadow/audit) dari `articles` dan
        `rejected_articles`. Setuju = vonis LLM `threat_news`: artikel bukan best practice;
        baris rejected tidak pernah setuju. Keputusan `gated` tidak dihitung (LLM tidak
        dipanggil, tidak ada vonis). `audit_since` hanya membatasi daftar audit, bukan hitungan
        band. Kind `tweet` menghitung dari `tweet_verdicts` (setuju = `related_cyber`)."""
        band_sql, audit_sql, extra = _gate_queries(kind)
        band = self.session.execute(text(band_sql), {**extra, "since": since}).one()
        audits = self.session.execute(
            text(audit_sql), {**extra, "n": revert_samples, "audit_since": audit_since}
        ).scalars()
        return GateStats(
            band_n=int(band[0]), band_agree=int(band[1]), audit_last=[bool(a) for a in audits]
        )

    def purge(self, older_than: datetime.datetime) -> int:
        """Hapus baris non-aktif yang dibuat sebelum `older_than`; model aktif tidak pernah
        dihapus."""
        result = self.session.execute(
            delete(RelevanceModel).where(
                RelevanceModel.status != "active", RelevanceModel.created_at < older_than
            )
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


class AsyncRelevanceModelRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, kind: str = "article") -> RelevanceModel | None:
        result = await self.session.execute(
            select(RelevanceModel).where(
                RelevanceModel.status == "active", RelevanceModel.kind == kind
            )
        )
        return result.scalar_one_or_none()

    async def gate_stats(
        self,
        *,
        since: datetime.datetime,
        revert_samples: int,
        audit_since: datetime.datetime | None = None,
        kind: str = "article",
    ) -> GateStats:
        """Cermin `RelevanceModelRepo.gate_stats` (SQL yang sama) untuk API."""
        band_sql, audit_sql, extra = _gate_queries(kind)
        band = (await self.session.execute(text(band_sql), {**extra, "since": since})).one()
        audits = (
            await self.session.execute(
                text(audit_sql), {**extra, "n": revert_samples, "audit_since": audit_since}
            )
        ).scalars()
        return GateStats(
            band_n=int(band[0]), band_agree=int(band[1]), audit_last=[bool(a) for a in audits]
        )

    async def middle_band_count(self, since: datetime.datetime, kind: str = "article") -> int:
        """Baris yang skornya di luar band sejak `since`: articles + rejected_articles, atau
        vonis LLM di `tweet_verdicts` untuk kind tweet."""
        sql = _TWEET_MIDDLE_BAND_SQL if check_kind(kind) == "tweet" else _MIDDLE_BAND_SQL
        return int((await self.session.execute(text(sql), {"since": since})).scalar_one())

    async def gated_count(self, since: datetime.datetime, kind: str = "article") -> int:
        """Item yang classify-nya dilewati gate sejak `since` (panggilan LLM yang dihemat)."""
        sql = _TWEET_GATED_SQL if check_kind(kind) == "tweet" else _GATED_SQL
        return int((await self.session.execute(text(sql), {"since": since})).scalar_one())
