"""`cti_alerts.mailer.create_graph_draft` -- port `_send_newsletter_email()`/
`_create_graph_draft()` lama (jalur Graph doang, lihat docstring modul).
Mock `msal`/`httpx` -- gak boleh manggil Azure AD/Graph API beneran dari
test unit."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
from cti_alerts.mailer import (
    GraphAuthError,
    GraphSendError,
    InlineImage,
    create_graph_draft,
    split_addresses,
)
from cti_core.config import GraphSettings

_SETTINGS = GraphSettings(
    tenant_id="tenant-1",
    client_id="client-1",
    client_secret="secret-1",
    sender="cti@example.com",
    cc="a@example.com, b@example.com",
)


def _mock_msal_app(token: str | None = "fake-token") -> MagicMock:
    app = MagicMock()
    app.acquire_token_for_client.return_value = (
        {"access_token": token} if token else {"error_description": "bad creds"}
    )
    return app


def test_auth_failure_raises_graph_auth_error() -> None:
    with (
        patch(
            "cti_alerts.mailer.msal.ConfidentialClientApplication",
            return_value=_mock_msal_app(None),
        ),
        pytest.raises(GraphAuthError),
    ):
        create_graph_draft("<html/>", "subject", settings=_SETTINGS)


def test_non_201_response_raises_graph_send_error() -> None:
    mock_resp = MagicMock(status_code=400, text="Bad Request")
    with (
        patch(
            "cti_alerts.mailer.msal.ConfidentialClientApplication", return_value=_mock_msal_app()
        ),
        patch("cti_alerts.mailer.httpx.post", return_value=mock_resp) as mock_post,
        pytest.raises(GraphSendError),
    ):
        create_graph_draft("<html/>", "subject", settings=_SETTINGS)
    assert mock_post.called


def test_successful_send_returns_message_id() -> None:
    mock_resp = MagicMock(status_code=201)
    mock_resp.json.return_value = {"id": "msg-123"}
    with (
        patch(
            "cti_alerts.mailer.msal.ConfidentialClientApplication", return_value=_mock_msal_app()
        ),
        patch("cti_alerts.mailer.httpx.post", return_value=mock_resp) as mock_post,
    ):
        result = create_graph_draft("<html/>content", "subject line", settings=_SETTINGS)

    assert result == "msg-123"
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["json"]["subject"] == "subject line"
    assert call_kwargs["json"]["body"] == {"contentType": "html", "content": "<html/>content"}
    assert call_kwargs["json"]["ccRecipients"] == [
        {"emailAddress": {"address": "a@example.com"}},
        {"emailAddress": {"address": "b@example.com"}},
    ]
    assert f"/users/{_SETTINGS.sender}/messages" in mock_post.call_args.args[0]


def test_empty_cc_produces_empty_recipient_list() -> None:
    settings = GraphSettings(
        tenant_id="t", client_id="c", client_secret="s", sender="cti@example.com", cc=""
    )
    mock_resp = MagicMock(status_code=201)
    mock_resp.json.return_value = {"id": "msg-1"}
    with (
        patch(
            "cti_alerts.mailer.msal.ConfidentialClientApplication", return_value=_mock_msal_app()
        ),
        patch("cti_alerts.mailer.httpx.post", return_value=mock_resp) as mock_post,
    ):
        create_graph_draft("<html/>", "subject", settings=settings)

    assert mock_post.call_args.kwargs["json"]["ccRecipients"] == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a@x.com", ["a@x.com"]),
        ("a@x.com,b@x.com", ["a@x.com", "b@x.com"]),
        ("a@x.com, b@x.com", ["a@x.com", "b@x.com"]),
        ("a@x.com;b@x.com", ["a@x.com", "b@x.com"]),  # format Outlook
        ("a@x.com; b@x.com ; c@x.com", ["a@x.com", "b@x.com", "c@x.com"]),
        ("a@x.com, b@x.com; c@x.com", ["a@x.com", "b@x.com", "c@x.com"]),  # campuran
        ("a@x.com;", ["a@x.com"]),  # pemisah di ujung
        (" ;, a@x.com ,; ", ["a@x.com"]),
        ("", []),
        ("   ", []),
    ],
)
def test_split_addresses_accepts_comma_and_semicolon(raw: str, expected: list[str]) -> None:
    assert split_addresses(raw) == expected


def test_semicolon_separated_cc_becomes_separate_recipients() -> None:
    settings = GraphSettings(
        tenant_id="t",
        client_id="c",
        client_secret="s",
        sender="cti@example.com",
        cc="user@domain.com;user2@domain.com",
    )
    mock_resp = MagicMock(status_code=201)
    mock_resp.json.return_value = {"id": "msg-1"}
    with (
        patch(
            "cti_alerts.mailer.msal.ConfidentialClientApplication", return_value=_mock_msal_app()
        ),
        patch("cti_alerts.mailer.httpx.post", return_value=mock_resp) as mock_post,
    ):
        create_graph_draft("<html/>", "subject", settings=settings)

    assert mock_post.call_args.kwargs["json"]["ccRecipients"] == [
        {"emailAddress": {"address": "user@domain.com"}},
        {"emailAddress": {"address": "user2@domain.com"}},
    ]


# ── Lampiran inline (`cid:`) -- ROADMAP #22, PR template ─────────────────────────────────────

_LOGO = InlineImage(
    content_id="newsletter-logo",
    content_type="image/png",
    data=b"\x89PNG\r\n\x1a\n-bukan-gambar-sungguhan-",
    name="logo.png",
)


def _post_draft(*, inline_images: tuple[InlineImage, ...] | None = None) -> MagicMock:
    """Panggil `create_graph_draft` dengan msal/httpx di-mock; kembalikan mock `httpx.post`."""
    mock_resp = MagicMock(status_code=201)
    mock_resp.json.return_value = {"id": "msg-1"}
    kwargs = {} if inline_images is None else {"inline_images": inline_images}
    with (
        patch(
            "cti_alerts.mailer.msal.ConfidentialClientApplication", return_value=_mock_msal_app()
        ),
        patch("cti_alerts.mailer.httpx.post", return_value=mock_resp) as mock_post,
    ):
        create_graph_draft(
            '<img src="cid:newsletter-logo">', "subject", settings=_SETTINGS, **kwargs
        )
    return mock_post


def test_inline_images_become_inline_file_attachments_in_the_same_request() -> None:
    mock_post = _post_draft(inline_images=(_LOGO,))

    mock_post.assert_called_once()  # satu POST: lampiran ikut membuat pesan, bukan panggilan kedua
    assert mock_post.call_args.kwargs["json"]["attachments"] == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "logo.png",
            "contentType": "image/png",
            "contentBytes": base64.b64encode(_LOGO.data).decode("ascii"),
            "contentId": "newsletter-logo",
            "isInline": True,
        }
    ]
    # Sisa payload tidak berubah karena ada lampiran.
    body = mock_post.call_args.kwargs["json"]
    assert body["subject"] == "subject"
    assert body["body"] == {"contentType": "html", "content": '<img src="cid:newsletter-logo">'}


def test_several_inline_images_keep_their_order() -> None:
    other = InlineImage(content_id="b", content_type="image/gif", data=b"GIF89a", name="b.gif")

    mock_post = _post_draft(inline_images=(_LOGO, other))

    attachments = mock_post.call_args.kwargs["json"]["attachments"]
    assert [a["contentId"] for a in attachments] == ["newsletter-logo", "b"]


def test_without_inline_images_the_payload_has_no_attachments_key() -> None:
    """Pemanggil lama (email CVE) dan default tidak berubah: tanpa kunci `attachments` sama sekali,
    bukan daftar kosong."""
    assert "attachments" not in _post_draft().call_args.kwargs["json"]
    assert "attachments" not in _post_draft(inline_images=()).call_args.kwargs["json"]
