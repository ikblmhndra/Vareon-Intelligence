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

_STATUSES = ("active", "retired", "rejected")
_GATE_STATES = ("shadow", "gate")


_BEST_PRACTICE = "Security Technology & Best Practices"
"""Salinan `cti_enrich.relevance.dataset.BEST_PRACTICE` (cti_core tidak boleh mengimpor
cti_enrich); vonis LLM `best_practice` dibaca dari `articles.news_type`."""


@dataclass(frozen=True)
class GateStats:
    """Ukuran kesepakatan band model dengan LLM. `audit_last`: sampel audit terbaru lebih dulu,
    True = LLM setuju `threat_news`."""

    band_n: int
    band_agree: int
    audit_last: list[bool]


def check_status(status: str) -> str:
    """`ValueError` kalau bukan status yang dikenal (konvensi `ArticleCountry.role`)."""
    if status not in _STATUSES:
        raise ValueError(f"status model relevansi tidak dikenal: {status!r}")
    return status


class RelevanceModelRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock(self) -> None:
        """Kunci advisory tingkat transaksi: satu latih/aktivasi sekaligus, supaya dua worker
        tidak sama-sama membuat baris `active`."""
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, 0)"), {"ns": RELEVANCE_LOCK_NAMESPACE}
        )

    def get_active(self) -> RelevanceModel | None:
        return self.session.execute(
            select(RelevanceModel).where(RelevanceModel.status == "active")
        ).scalar_one_or_none()

    def add_rejected(
        self,
        *,
        feature_version: str,
        n_examples: int,
        class_counts: dict[str, int],
        metrics: dict[str, Any],
        reason: str,
    ) -> int:
        row = RelevanceModel(
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
    ) -> int:
        """Pensiunkan model aktif lalu sisipkan yang baru; `gate_state` dan `gate_changed_at`
        diwarisi (default `shadow`/NULL). Urutan penting: indeks unik parsial menolak dua baris
        `active` sekaligus, jadi yang lama harus `retired` dulu. `now` belum dipakai kolom
        apa pun (created_at server-side); tetap diterima agar antarmuka sama dengan
        `set_gate_state`."""
        current = self.get_active()
        gate_state, gate_changed_at = "shadow", None
        if current is not None:
            gate_state, gate_changed_at = current.gate_state, current.gate_changed_at
            current.status = check_status("retired")
            self.session.flush()
        row = RelevanceModel(
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

    def gate_stats(self, *, since: datetime.datetime, revert_samples: int) -> GateStats:
        """Hitung baris dalam band (`in_band` true, keputusan shadow/audit) dari `articles` dan
        `rejected_articles`. Setuju = vonis LLM `threat_news`: artikel bukan best practice;
        baris rejected tidak pernah setuju. Keputusan `gated` tidak dihitung (LLM tidak
        dipanggil, tidak ada vonis)."""
        union = """
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
        """
        band = self.session.execute(
            text(
                f"SELECT count(*), count(*) FILTER (WHERE agree) FROM ({union}) r "
                "WHERE ts >= :since"
            ),
            {"bp": _BEST_PRACTICE, "since": since},
        ).one()
        audits = self.session.execute(
            text(
                f"SELECT agree FROM ({union}) r WHERE decision = 'audit' ORDER BY ts DESC LIMIT :n"
            ),
            {"bp": _BEST_PRACTICE, "n": revert_samples},
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

    async def get_active(self) -> RelevanceModel | None:
        result = await self.session.execute(
            select(RelevanceModel).where(RelevanceModel.status == "active")
        )
        return result.scalar_one_or_none()
