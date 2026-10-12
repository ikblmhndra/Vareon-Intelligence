"""Alur email newsletter lewat HTTP + Postgres: logo `cid:`, subject, dan guard ukuran --
ROADMAP #22, PR template.

Yang dibuktikan di sini (bukan bentuk JSON; itu `test_newsletter_router_snapshot.py`):
- HTML yang DISIMPAN dan DIKIRIM tetap berisi `cid:`; yang DITAMPILKAN (preview, riwayat) berisi
  data URI. Satu-satunya tempat gambar dipetakan ada di jalur tampil, jadi tidak ada versi ketiga.
- `draft-email` dan `resend` memakai SATU helper subject (bulan, atau "Week N" untuk baris lama)
  dan sama-sama melampirkan logo; payload ke Graph dites dengan `httpx` di-mock, bukan dengan
  `create_graph_draft` diganti, supaya terbukti lampirannya sampai ke request.
- Preview mengukur versi `cid:`, dan memperingatkan di atas ~90 KB tanpa menggagalkan apa pun.
Playwright dan LLM diganti stub (`newsletter_stubs`)."""

from __future__ import annotations

import base64
import datetime
import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cti_api.services import newsletter as newsletter_service
from cti_api.services import newsletter_logo
from cti_core.config import GraphSettings
from cti_core.db.models.newsletter import Newsletter
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.newsletter_stubs import patched_pipeline, seed_articles

pytestmark = pytest.mark.asyncio

_GRAPH = "cti_api.routers.newsletter.create_graph_draft"
_OCTOBER_SUBJECT = "[CTI Newsletter] Threat Intelligence Digest \N{EM DASH} October 2026"
_DATA_URI = re.compile(r'src="(data:image/png;base64,[^"]+)"')

_GRAPH_SETTINGS = GraphSettings(
    tenant_id="tenant-1",
    client_id="client-1",
    client_secret="secret-1",
    sender="cti@example.com",
    cc="",
)


@pytest.fixture
def graph_http() -> Any:
    """Graph tanpa `create_graph_draft` diganti: hanya msal dan `httpx.post` di-mock, jadi payload
    yang benar-benar dikirim ke Graph bisa diperiksa. `post.call_args_list[i].kwargs["json"]`."""
    response = MagicMock(status_code=201)
    response.json.return_value = {"id": "graph-msg-1"}
    app = MagicMock()
    app.acquire_token_for_client.return_value = {"access_token": "fake-token"}
    with (
        patch(
            "cti_alerts.mailer.get_settings", return_value=SimpleNamespace(graph=_GRAPH_SETTINGS)
        ),
        patch("cti_alerts.mailer.msal.ConfidentialClientApplication", return_value=app),
        patch("cti_alerts.mailer.httpx.post", return_value=response) as post,
    ):
        yield post


async def _draft(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]], payload: dict[str, Any]
) -> dict[str, Any]:
    resp = await api_client.post("/api/newsletter/draft-email", headers=auth_header(), json=payload)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


# ── Preview ──────────────────────────────────────────────────────────────────


async def test_preview_shows_the_logo_as_a_data_uri_and_measures_the_cid_version(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    [highlight] = await seed_articles(api_session, 1)

    with patched_pipeline():
        resp = await api_client.post(
            "/api/newsletter/preview", headers=auth_header(), json={"highlight": highlight}
        )

    assert resp.status_code == 200
    body = resp.json()
    # Kunci lama tetap ada; yang baru hanya ditambahkan.
    assert {"html", "week", "year", "newsletter_id"} <= set(body)
    assert body["newsletter_id"] is None
    assert set(body) - {"html", "week", "year", "newsletter_id"} == {"html_bytes", "size_warning"}

    shown = body["html"]
    assert "cid:" not in shown  # browser tidak mengerti cid: -> logo jadi data URI
    [data_uri] = _DATA_URI.findall(shown)
    assert base64.b64decode(data_uri.split(",", 1)[1]) == newsletter_logo.LOGO_PATH.read_bytes()

    # `html_bytes` = ukuran versi yang DIKIRIM (cid:), bukan versi tampil yang lebih besar.
    sent = shown.replace(data_uri, "cid:newsletter-logo")
    assert body["html_bytes"] == len(sent.encode("utf-8"))
    assert body["html_bytes"] < len(shown.encode("utf-8"))
    assert body["size_warning"] is None


async def test_preview_warns_above_90_kb_but_still_returns_the_edition(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    [highlight] = await seed_articles(api_session, 1)
    payload = {"highlight": highlight, "custom_intro": "<p>" + "x" * 95_000 + "</p>"}

    with patched_pipeline():
        resp = await api_client.post("/api/newsletter/preview", headers=auth_header(), json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["html_bytes"] > newsletter_service.HTML_WARN_BYTES
    assert "KB" in body["size_warning"] and "Gmail" in body["size_warning"]
    assert body["html"].startswith("<!DOCTYPE html>")


# ── Draft: lampiran, subject, HTML tersimpan ─────────────────────────────────


async def test_draft_attaches_the_logo_and_stores_the_cid_version(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    [highlight] = await seed_articles(api_session, 1)

    with patched_pipeline(), patch(_GRAPH, MagicMock(return_value="graph-1")) as graph:
        body = await _draft(api_client, auth_header, {"highlight": highlight})

    graph.assert_called_once()
    sent_html, sent_subject = graph.call_args.args
    assert "cid:newsletter-logo" in sent_html and "data:image" not in sent_html
    assert sent_subject == body["subject"] == _OCTOBER_SUBJECT  # NOW = 2 Nov -> edisi Oktober
    assert graph.call_args.kwargs["inline_images"] == [newsletter_logo.logo_image()]

    # Baris riwayat = persis yang dikirim (cid:), bukan versi tampil.
    [row] = (await api_session.execute(select(Newsletter))).scalars().all()
    assert row.html == sent_html
    assert (row.period_start, row.period_end) == (
        datetime.date(2026, 10, 1),
        datetime.date(2026, 10, 31),
    )


async def test_the_history_view_maps_cid_to_a_data_uri_without_touching_the_stored_html(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    [highlight] = await seed_articles(api_session, 1)
    with patched_pipeline(), patch(_GRAPH, MagicMock(return_value="graph-1")):
        saved = await _draft(api_client, auth_header, {"highlight": highlight})

    resp = await api_client.get(
        f"/api/newsletter/{saved['newsletter_id']}/html", headers=auth_header()
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "cid:" not in resp.text
    assert len(_DATA_URI.findall(resp.text)) == 1
    stored = await AsyncNewsletterRepo(api_session).get_html(saved["newsletter_id"])
    assert stored is not None and "cid:newsletter-logo" in stored and "data:image" not in stored


async def test_an_old_history_row_without_the_logo_opens_unchanged(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    old = await AsyncNewsletterRepo(api_session).save(
        week=38,
        year=2026,
        generated_at="2026-09-19 10:00 UTC",
        created_by="analyst1",
        html="<html><body>Edisi lama</body></html>",
        sections={},
    )

    resp = await api_client.get(f"/api/newsletter/{old.id}/html", headers=auth_header())

    assert resp.status_code == 200
    assert resp.text == "<html><body>Edisi lama</body></html>"


# ── Resend ───────────────────────────────────────────────────────────────────


async def test_resend_reattaches_the_logo_and_uses_the_same_subject_helper(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    [highlight] = await seed_articles(api_session, 1)
    with patched_pipeline(), patch(_GRAPH, MagicMock(return_value="graph-1")) as graph:
        drafted = await _draft(api_client, auth_header, {"highlight": highlight})
    stored_html = graph.call_args.args[0]

    with patch(_GRAPH, MagicMock(return_value="graph-2")) as resend_graph:
        resp = await api_client.post(
            f"/api/newsletter/{drafted['newsletter_id']}/resend", headers=auth_header()
        )

    assert resp.status_code == 200
    assert resp.json()["subject"] == drafted["subject"] == _OCTOBER_SUBJECT
    resend_html, resend_subject = resend_graph.call_args.args
    assert resend_html == stored_html  # HTML tersimpan dikirim apa adanya
    assert resend_subject == _OCTOBER_SUBJECT
    assert resend_graph.call_args.kwargs["inline_images"] == [newsletter_logo.logo_image()]


async def test_resend_of_an_old_row_keeps_the_week_subject_and_attaches_nothing(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    old = await AsyncNewsletterRepo(api_session).save(
        week=38,
        year=2026,
        generated_at="2026-09-19 10:00 UTC",
        created_by="analyst1",
        html="<html><body>Edisi lama</body></html>",
        sections={},
    )

    with patch(_GRAPH, MagicMock(return_value="graph-old")) as graph:
        resp = await api_client.post(f"/api/newsletter/{old.id}/resend", headers=auth_header())

    assert resp.status_code == 200
    expected = "[CTI Newsletter] Threat Intelligence Digest \N{EM DASH} Week 38, 2026"
    assert resp.json()["subject"] == expected
    assert graph.call_args.args == ("<html><body>Edisi lama</body></html>", expected)
    assert graph.call_args.kwargs["inline_images"] == []  # tanpa lampiran yatim


# ── Payload ke Graph (httpx di-mock; create DAN resend) ──────────────────────


def _graph_payloads(post: MagicMock) -> list[dict[str, Any]]:
    return [call.kwargs["json"] for call in post.call_args_list]


def _assert_logo_attachment(payload: dict[str, Any]) -> None:
    [attachment] = payload["attachments"]
    assert attachment["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert attachment["isInline"] is True
    assert attachment["contentId"] == "newsletter-logo"
    assert attachment["contentType"] == "image/png"
    assert base64.b64decode(attachment["contentBytes"]) == newsletter_logo.LOGO_PATH.read_bytes()
    assert (
        'src="cid:newsletter-logo"' in payload["body"]["content"]
    )  # yang dirujuk = yang dilampirkan


async def test_the_graph_payloads_of_create_and_resend_both_carry_the_inline_logo(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    graph_http: MagicMock,
) -> None:
    [highlight] = await seed_articles(api_session, 1)
    with patched_pipeline():
        drafted = await _draft(api_client, auth_header, {"highlight": highlight})
    resp = await api_client.post(
        f"/api/newsletter/{drafted['newsletter_id']}/resend", headers=auth_header()
    )
    assert resp.status_code == 200

    created, resent = _graph_payloads(graph_http)
    for payload in (created, resent):
        assert payload["subject"] == _OCTOBER_SUBJECT
        _assert_logo_attachment(payload)
    assert created["body"] == resent["body"]  # kirim ulang = isi yang sama persis


async def test_the_graph_payload_of_an_old_row_has_no_attachments_key(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    graph_http: MagicMock,
) -> None:
    old = await AsyncNewsletterRepo(api_session).save(
        week=38,
        year=2026,
        generated_at="2026-09-19 10:00 UTC",
        created_by="analyst1",
        html="<html><body>Edisi lama</body></html>",
        sections={},
    )

    resp = await api_client.post(f"/api/newsletter/{old.id}/resend", headers=auth_header())

    assert resp.status_code == 200
    [payload] = _graph_payloads(graph_http)
    assert "attachments" not in payload
    assert payload["subject"].endswith("Week 38, 2026")


# ── Subject mengikuti periode permintaan ─────────────────────────────────────


async def test_an_explicit_period_names_the_subject_and_the_draft_response(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    [highlight] = await seed_articles(api_session, 1)
    payload = {"highlight": highlight, "period_start": "2026-09-01", "period_end": "2026-09-30"}

    with patched_pipeline(), patch(_GRAPH, MagicMock(return_value="graph-1")) as graph:
        body = await _draft(api_client, auth_header, payload)

    expected = "[CTI Newsletter] Threat Intelligence Digest \N{EM DASH} September 2026"
    assert body["subject"] == graph.call_args.args[1] == expected
    assert "September 2026 Edition" in graph.call_args.args[0]
