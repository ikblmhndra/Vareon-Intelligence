"""Bantuan test integrasi pipeline P7g: menyelesaikan job `classify` dengan vonis yang diberikan
test (pengganti LLM), lewat jalur yang sama dengan job runner (`Prepared.from_job` + `complete`).
Kunci URL, cek ulang artikel, dan penghapusan job yang sebenarnya milik `run_job` (Task 4)."""

from __future__ import annotations

from cti_core.db.models.enrich_job import EnrichJob
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from sqlalchemy import select
from sqlalchemy.orm import Session


def job_for(session: Session, url: str, kind: str = "classify") -> EnrichJob | None:
    return session.scalar(
        select(EnrichJob).where(EnrichJob.kind == kind, EnrichJob.url_hash == url_hash(url))
    )


def finish_classify(
    session: Session, url: str, classify_result: ClassifyResult, *, alert: bool = True
) -> pipeline.PipelineOutcome:
    job = job_for(session, url)
    assert job is not None, "tidak ada job classify untuk URL ini"
    prepared = pipeline.Prepared.from_job(job)
    session.delete(job)
    session.flush()
    outcome = pipeline.complete(prepared, classify_result, session=session, alert=alert)
    session.commit()
    return outcome


def run_with_verdict(
    session: Session,
    classify_result: ClassifyResult,
    *,
    alert: bool = True,
    **kwargs: object,
) -> pipeline.PipelineOutcome:
    """`run_pipeline`, lalu job `classify`-nya (kalau ada) diselesaikan dengan `classify_result`."""
    outcome = pipeline.run_pipeline(session=session, alert=alert, **kwargs)  # type: ignore[arg-type]
    if outcome.pending_job_id is None:
        return outcome
    return finish_classify(session, str(kwargs["url"]), classify_result, alert=alert)
