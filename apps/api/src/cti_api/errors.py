"""Format galat per prefix (P7b): `/api/v2` pakai `{error: {code, message, details}}`, `/taxii2`
pakai objek galat TAXII 2.1 (bagian 3.6.1). Path lain jatuh ke handler bawaan FastAPI /
handler yang sudah ada di `create_app`, jadi respons v1 tidak berubah. Handler didaftarkan pada
`StarletteHTTPException` supaya 404/405 dari routing ikut terformat."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

TAXII_MEDIA_TYPE = "application/taxii+json;version=2.1"


def _prefix(request: Request) -> str | None:
    path = request.url.path
    if path == "/api/v2" or path.startswith("/api/v2/"):
        return "v2"
    if path == "/taxii2" or path.startswith("/taxii2/"):
        return "taxii"
    return None


def _format(
    kind: str,
    status: int,
    message: str,
    details: list[Any] | None,
    headers: dict[str, str] | None,
) -> Response:
    phrase = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "Error"
    if kind == "v2":
        code = phrase.lower().replace(" ", "_").replace("-", "_")
        body: dict[str, Any] = {"error": {"code": code, "message": message, "details": details}}
        return JSONResponse(body, status_code=status, headers=headers)
    body = {"title": phrase, "http_status": status, "description": message}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status, headers=headers, media_type=TAXII_MEDIA_TYPE)


async def http_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    kind = _prefix(request)
    if kind is None:
        return await http_exception_handler(request, exc)
    return _format(kind, exc.status_code, str(exc.detail), None, exc.headers)


def validation_details(exc: RequestValidationError) -> list[Any]:
    # Tanpa `input`/`ctx`/`url`: respons bawaan memantulkan input klien.
    return [
        {k: v for k, v in e.items() if k not in ("input", "ctx", "url")}
        for e in jsonable_encoder(exc.errors())
    ]


def validation_error_for_prefix(request: Request, exc: RequestValidationError) -> Response | None:
    """Respons untuk `/api/v2` dan `/taxii2`; `None` untuk path lain."""
    kind = _prefix(request)
    if kind is None:
        return None
    return _format(kind, 422, "Validation error", validation_details(exc), None)
