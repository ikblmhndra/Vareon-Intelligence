"""`EnrichJobRepo` tiruan untuk test unit pipeline (P7g), tanpa DB.

Dipasang sebagai `pipeline.EnrichJobRepo` (instance-nya callable, jadi `EnrichJobRepo(session)`
mengembalikan dirinya sendiri). `finish` meniru bagian deterministik `run_job` (Task 4): job
`classify` dilanjutkan dengan vonis classify yang diberikan test, lewat `Prepared.from_job` +
`complete`, persis jalur yang dipakai job runner.
"""

from __future__ import annotations

from typing import Any

from cti_core.db.models.enrich_job import EnrichJob
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult


class FakeJobRepo:
    def __init__(self) -> None:
        self.jobs: list[EnrichJob] = []
        self.create_calls = 0

    def __call__(self, session: Any) -> FakeJobRepo:
        return self

    def create(self, **kw: Any) -> EnrichJob | None:
        self.create_calls += 1
        h = url_hash(kw["url"])
        if any(j.kind == kw["kind"] and j.url_hash == h for j in self.jobs):
            return None
        state = kw.pop("state", "pending")
        job = EnrichJob(id=len(self.jobs) + 1, url_hash=h, state=state, **kw)
        self.jobs.append(job)
        return job

    def has_classify(self, h: str) -> bool:
        return any(j.kind == "classify" and j.url_hash == h for j in self.jobs)

    def of_kind(self, kind: str) -> list[EnrichJob]:
        return [j for j in self.jobs if j.kind == kind]


def finish(
    repo: FakeJobRepo, classify_result: ClassifyResult, *, alert: bool = True
) -> pipeline.PipelineOutcome:
    """Selesaikan job `classify` terakhir dengan vonis `classify_result` (pengganti LLM)."""
    from unittest.mock import MagicMock

    job = repo.of_kind("classify")[-1]
    repo.jobs.remove(job)
    return pipeline.complete(
        pipeline.Prepared.from_job(job), classify_result, session=MagicMock(), alert=alert
    )
