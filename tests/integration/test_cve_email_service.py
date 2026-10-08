"""Integration test `cti_api.services.cve_email.draft_email_for_cves` --
Postgres REAL (testcontainers), LLM + Graph draft di-mock (sama pola
kayak `test_cve_lookup_service.py`) -- verifikasi template render+context
beneran jalan, tanpa manggil API eksternal."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from cti_api.services import cve_email as svc
from cti_core.db.models.cve import CveAffected, CveReference, CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()


_FAKE_VALIDATION = {
    "product_name": "WordPress",
    "summary": "Attackers can execute arbitrary PHP code.",
    "risk_context": "Full compromise possible if unpatched.",
    "primary_remediation_action": [{"version_branch": "< 6.5", "fixed_version": "6.5"}],
    "alternative_remediation_action": ["Disable the plugin", "Enable WAF rule X"],
}


async def test_draft_email_for_cves_renders_and_dispatches(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    cve = CveTracker(
        cve_id="CVE-2026-0001",
        client_id="default",
        tech="WordPress",
        summary="Stored XSS",
        cve_severity="CRITICAL",
        cve_score=9.8,
    )
    cve.references = [CveReference(url="https://example.com/advisory")]
    cve.affected = [CveAffected(affected="wp-plugin < 6.5")]
    async_db_session.add(cve)
    await async_db_session.flush()

    with (
        patch.object(svc, "_llm_cve_validator", MagicMock(return_value=_FAKE_VALIDATION)),
        patch.object(
            svc,
            "_dedup_mitigation",
            MagicMock(return_value={"alternative_remediation_action": ["Deduped control"]}),
        ),
        patch.object(svc, "_dedup_risk_context", MagicMock(return_value="<strong>Risky</strong>")),
        patch.object(svc, "create_graph_draft", MagicMock(return_value="graph-msg-123")),
    ):
        result = await svc.draft_email_for_cves(
            async_db_session, ["CVE-2026-0001"], "CTI-2026-09-001", client_id="default"
        )

    assert result["email_id"] == "graph-msg-123"
    assert result["method"] == "graph"
    assert result["cve_count"] == 1
    assert "CVE-2026-0001" not in result["subject"]  # subject pakai product_name, bukan cve_id
    # `.title()` (port apa adanya legacy) -> "WordPress" jadi "Wordpress"
    assert "Wordpress" in result["subject"]


async def test_draft_email_for_cves_raises_when_no_cves_found(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    with pytest.raises(ValueError, match="No CVE documents found"):
        await svc.draft_email_for_cves(
            async_db_session, ["CVE-DOES-NOT-EXIST"], "CTI-2026-09-001", client_id="default"
        )


async def test_draft_email_for_cves_deduplicates_vendor_advisory_urls(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    cve1 = CveTracker(cve_id="CVE-2026-0002", client_id="default", tech="nginx")
    cve1.references = [CveReference(url="https://shared.example/advisory")]
    cve2 = CveTracker(cve_id="CVE-2026-0003", client_id="default", tech="nginx")
    cve2.references = [CveReference(url="https://shared.example/advisory")]
    async_db_session.add_all([cve1, cve2])
    await async_db_session.flush()

    captured_context: dict[str, object] = {}

    def _capture_render(context: dict[str, object]) -> str:
        captured_context.update(context)
        return "<html/>"

    with (
        patch.object(svc, "_llm_cve_validator", MagicMock(return_value=_FAKE_VALIDATION)),
        patch.object(
            svc,
            "_dedup_mitigation",
            MagicMock(return_value={"alternative_remediation_action": []}),
        ),
        patch.object(svc, "_dedup_risk_context", MagicMock(return_value="")),
        patch.object(svc, "_render_email", MagicMock(side_effect=_capture_render)),
        patch.object(svc, "create_graph_draft", MagicMock(return_value="graph-msg-456")),
    ):
        result = await svc.draft_email_for_cves(
            async_db_session,
            ["CVE-2026-0002", "CVE-2026-0003"],
            "CTI-2026-09-002",
            client_id="default",
        )

    assert result["cve_count"] == 2
    assert captured_context["vendor_advisory_url"] == ["https://shared.example/advisory"]


async def test_draft_email_is_scoped_to_the_callers_client(
    async_db_session: AsyncSession,
) -> None:
    """CVE yang sama di-track dua client dengan tech berbeda: draft untuk acme hanya memuat baris
    acme -- satu CVE, produk acme -- dan CVE yang tidak di-track client itu dianggap tidak ada."""
    await _ensure_clients(async_db_session)
    await AsyncClientRepo(async_db_session).create(client_id="acme", name="Acme", countries=[])
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-0010", client_id="default", tech="nginx"),
            CveTracker(cve_id="CVE-2026-0010", client_id="acme", tech="apache"),
            CveTracker(cve_id="CVE-2026-0011", client_id="default", tech="nginx"),
        ]
    )
    await async_db_session.flush()

    llm_calls = MagicMock(return_value=_FAKE_VALIDATION)
    with (
        patch.object(svc, "_llm_cve_validator", llm_calls),
        patch.object(
            svc,
            "_dedup_mitigation",
            MagicMock(return_value={"alternative_remediation_action": []}),
        ),
        patch.object(svc, "_dedup_risk_context", MagicMock(return_value="")),
        patch.object(svc, "create_graph_draft", MagicMock(return_value="graph-msg-789")),
    ):
        result = await svc.draft_email_for_cves(
            async_db_session, ["CVE-2026-0010"], "CTI-2026-09-003", client_id="acme"
        )
        assert result["cve_count"] == 1
        assert "Apache" in result["subject"]
        assert llm_calls.call_count == 1

        with pytest.raises(ValueError, match="No CVE documents found"):
            await svc.draft_email_for_cves(
                async_db_session, ["CVE-2026-0011"], "CTI-2026-09-004", client_id="acme"
            )
