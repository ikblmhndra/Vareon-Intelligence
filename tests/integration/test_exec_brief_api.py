"""Pembuatan brief bersama (`draft_brief`): tanpa bagian analyst/klien, error LLM jadi
`BriefGenerationError`. LLM selalu di-stub."""

from __future__ import annotations

from typing import Any

import pytest
from cti_api.services import exec_brief as eb
from cti_api.services import exec_dashboard
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _boom(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("bagian analyst/klien tidak boleh dihitung untuk brief")


async def test_brief_skips_analyst_and_client_sections(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "_get_recent_clusters",
        "_get_pending_fp_queue",
        "_get_critical_cves",
        "_get_source_reliability_spread",
    ):
        monkeypatch.setattr(exec_dashboard, name, _boom)
    monkeypatch.setattr(eb, "_call_llm", lambda _m: ("# Brief", "model-x"))
    draft = await eb.draft_brief(async_db_session, filters=eb.DEFAULT_FILTERS)
    assert (draft.markdown, draft.model) == ("# Brief", "model-x")
    assert draft.prompt_version == eb._PROMPT_VERSION


async def test_draft_empty_answer_raises(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(eb, "_call_llm", lambda _m: ("  \n", "m"))
    with pytest.raises(eb.BriefGenerationError) as ei:
        await eb.draft_brief(async_db_session, filters=eb.DEFAULT_FILTERS)
    assert ei.value.error_type == "empty"


async def test_draft_llm_error_raises_generation_error(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(_m: str) -> tuple[str, str]:
        raise TimeoutError

    monkeypatch.setattr(eb, "_call_llm", _fail)
    with pytest.raises(eb.BriefGenerationError) as ei:
        await eb.draft_brief(async_db_session, filters=eb.DEFAULT_FILTERS)
    assert ei.value.error_type == "TimeoutError"
