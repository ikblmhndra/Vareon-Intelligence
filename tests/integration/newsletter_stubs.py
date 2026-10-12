"""Stub dan seed bersama test integrasi newsletter (ROADMAP #22, PR 5).

Playwright dan LLM tidak pernah dijalankan sungguhan di test: `fetch_article_body` dan klien LLM
diganti stub yang MENGHITUNG panggilan, karena yang dibuktikan test-test ini justru "berapa kali
dipanggil" (preview kedua dan draft sesudah preview harus nol). Dipakai
`test_newsletter_router_snapshot.py` dan `test_newsletter_cve_correlation.py`."""

from __future__ import annotations

import contextlib
import datetime
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from cti_api.services import newsletter as newsletter_service
from cti_api.services import newsletter_suggestion
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from sqlalchemy.ext.asyncio import AsyncSession

TP_CVE = "CVE-2026-1111"
"""Di-track client `default` tanpa FP -> true positive; muncul di judul artikel stub."""

NON_TP_CVE = "CVE-2026-2222"
"""Muncul di body tapi tidak di-track siapa pun -> BUKAN true positive."""

IOC_IP = "203.0.113.77"

BODY = f"The actor used {IOC_IP} and exploited {TP_CVE} and {NON_TP_CVE} against exposed servers."

# 2 Nov 2026 02:00 UTC = Senin 09:00 WIB, hari edisi Oktober disiapkan.
NOW = datetime.datetime(2026, 11, 2, 2, 0, tzinfo=datetime.UTC)


class FakeLlm:
    """Klien OpenAI palsu: balas ringkasan tetap dan hitung panggilan."""

    def __init__(self) -> None:
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        content = json.dumps({"key_points": ["poin satu", "poin dua"], "summary": "ringkasan"})
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


class Pipeline:
    """Stub fetch + LLM yang dipasang bersamaan, plus penghitung panggilannya."""

    def __init__(self, *, body: str | None = BODY, paywall: bool = False) -> None:
        self.llm = FakeLlm()
        self.fetch = AsyncMock(return_value=(body, paywall))

    @property
    def calls(self) -> tuple[int, int]:
        """(fetch, LLM), untuk dibandingkan sebelum/sesudah satu langkah."""
        return self.fetch.await_count, self.llm.calls


@contextlib.contextmanager
def patched_pipeline(*, body: str | None = BODY, paywall: bool = False) -> Iterator[Pipeline]:
    """Pasang stub fetch + LLM di namespace service newsletter dan pin `_now()` ke `NOW`."""
    pipeline = Pipeline(body=body, paywall=paywall)
    with (
        patch.object(newsletter_service, "fetch_article_body", pipeline.fetch),
        patch.object(
            newsletter_service,
            "get_llm_client",
            MagicMock(return_value=(pipeline.llm, "stub-model")),
        ),
        patch.object(newsletter_service, "_now", return_value=NOW),
    ):
        yield pipeline


async def seed_articles(session: AsyncSession, count: int) -> list[int]:
    """`count` artikel dengan judul/URL berbeda; mengembalikan id-nya berurutan."""
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    ids = []
    for i in range(1, count + 1):
        article = await repo.upsert(
            url=f"https://example.com/story-{i}",
            title=f"Story {i} mentions {TP_CVE}" if i == 1 else f"Story {i} about intrusions",
            source="gbhackers",
            posted_on=datetime.date(2026, 10, i),
        )
        ids.append(article.id)
    return ids


async def seed_true_positive_cve(session: AsyncSession) -> None:
    """Satu baris `cve_tracker` untuk `TP_CVE` (client default, tanpa FP)."""
    await AsyncClientRepo(session).ensure_default()
    session.add(CveTracker(cve_id=TP_CVE, client_id="default", tech="nginx"))
    await session.flush()


def no_campaigns() -> Any:
    """Matikan cluster kampanye di saran: `get_recent_campaigns` membaca 2000 artikel terbaru dari
    HARI INI, bukan jendela test, jadi hasilnya bergantung tanggal asli. Test yang memang tentang
    cluster memakai stub sendiri atau pemanggilan sungguhan."""
    return patch.object(newsletter_suggestion, "_campaigns", AsyncMock(return_value=[]))


def suggestion_clock() -> Any:
    """Pin jam saran ke `NOW` (Senin 2 Nov 2026, 09:00 WIB): jendela default = Oktober 2026."""
    return patch.object(newsletter_suggestion, "_now", return_value=NOW)
