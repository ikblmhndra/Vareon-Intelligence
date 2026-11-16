"""`cve_escalation.build_escalation_email`: teks luar di-escape, nilai kosong jadi "-"."""

from __future__ import annotations

from cti_api.services.cve_escalation import build_escalation_email


def _build(**over: object) -> tuple[str, str]:
    args: dict[str, object] = {
        "cve_id": "CVE-2026-1234",
        "severity": "CRITICAL",
        "score": 9.8,
        "kev": True,
        "exploited": False,
        "tech": "nginx",
        "ticket_id": "CTI-2026-11-001",
        "team": "SOC",
        "plan_date": "2026-12-01",
        "actor": "tester",
    }
    args.update(over)
    return build_escalation_email(**args)  # type: ignore[arg-type]


def test_escalation_email_escapes_external_text() -> None:
    subject, html_body = _build(tech="<script>", team="A&B")
    assert "&lt;script&gt;" in html_body
    assert "<script>" not in html_body
    assert "A&amp;B" in html_body
    assert "CVE-2026-1234" in subject


def test_escalation_email_missing_fields_render_dash() -> None:
    _, html_body = _build(severity="", score=None, tech="", plan_date="")
    assert "<td>-</td>" in html_body
    assert html_body.count("<td>-</td>") >= 4
