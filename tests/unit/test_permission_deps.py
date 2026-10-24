"""`require_permission` dan `effective_client_id` (audit keamanan 2026-10-24) tanpa DB."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from cti_api import deps
from fastapi import HTTPException

pytestmark = pytest.mark.asyncio


def _user(role: str, client_ids: list[str] | None = None) -> deps.AuthedUser:
    return deps.AuthedUser(
        username="u", role=role, client_ids=client_ids or ["a"], force_pw_change=False
    )


@pytest.fixture(autouse=True)
def _roles(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str] | None]:
    deps.invalidate_role_permissions()
    table: dict[str, list[str] | None] = {"analyst": ["view_news", "view_cve"], "custom": None}

    class _Repo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get(self, name: str) -> Any:
            perms = table.get(name)
            return None if perms is None else SimpleNamespace(permissions=perms)

    monkeypatch.setattr(deps, "AsyncRoleRepo", _Repo)
    return table


async def test_superadmin_needs_no_lookup() -> None:
    check = deps.require_permission("manage_clients")
    assert (await check(user=_user("superadmin"), session=None))["role"] == "superadmin"  # type: ignore[arg-type]


async def test_missing_permission_is_403() -> None:
    check = deps.require_permission("manage_newsletter")
    with pytest.raises(HTTPException) as e:
        await check(user=_user("analyst"), session=None)  # type: ignore[arg-type]
    assert e.value.status_code == 403
    assert e.value.detail == "Missing permission: manage_newsletter"


async def test_granted_permission_passes() -> None:
    check = deps.require_permission("view_cve")
    assert (await check(user=_user("analyst"), session=None))["username"] == "u"  # type: ignore[arg-type]


async def test_system_role_without_row_falls_back_to_code(_roles: dict[str, Any]) -> None:
    del _roles["analyst"]
    check = deps.require_permission("manage_cve")
    await check(user=_user("analyst"), session=None)  # type: ignore[arg-type]


async def test_unknown_role_without_row_has_no_permission() -> None:
    check = deps.require_permission("view_news")
    with pytest.raises(HTTPException):
        await check(user=_user("ghost"), session=None)  # type: ignore[arg-type]


async def test_cache_invalidation_picks_up_role_change(_roles: dict[str, Any]) -> None:
    check = deps.require_permission("manage_rfi")
    with pytest.raises(HTTPException):
        await check(user=_user("analyst"), session=None)  # type: ignore[arg-type]
    _roles["analyst"] = ["manage_rfi"]
    deps.invalidate_role_permissions("analyst")
    await check(user=_user("analyst"), session=None)  # type: ignore[arg-type]


def test_unknown_permission_fails_at_import_time() -> None:
    with pytest.raises(ValueError):
        deps.require_permission("does_not_exist")


def test_foreign_client_header_is_403() -> None:
    with pytest.raises(HTTPException) as e:
        deps.effective_client_id(_user("admin", ["a"]), "b")
    assert e.value.status_code == 403


def test_client_header_rules() -> None:
    assert deps.effective_client_id(_user("analyst", ["a", "b"]), "b") == "b"
    assert deps.effective_client_id(_user("analyst", ["a", "b"]), None) == "a"
    assert deps.effective_client_id(_user("superadmin", ["a"]), "zzz") == "zzz"
