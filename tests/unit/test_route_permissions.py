"""Setiap route `/api` menyatakan permission-nya (audit keamanan 2026-10-24).

Dulu 26 permission disimpan di role tapi tidak ada router yang mengeceknya: analyst bisa mengirim
newsletter, email CVE, atau memicu generate LLM. Test ini gagal untuk route baru yang lupa memasang
`require_permission`, kecuali route itu memang terdaftar di `EXEMPT` dengan alasannya."""

from __future__ import annotations

from typing import Any

import pytest
from cti_api.services.roles import ALL_PERMISSIONS, SYSTEM_ROLES

# (method, path) -> alasan tidak memakai permission.
EXEMPT: dict[tuple[str, str], str] = {
    ("POST", "/api/auth/login"): "public",
    ("POST", "/api/auth/init"): "public, first-run bootstrap only",
    ("GET", "/api/auth/policy"): "public, login page shows the rules",
    ("GET", "/api/auth/me"): "any signed-in user",
    ("POST", "/api/auth/logout"): "any signed-in user",
    ("POST", "/api/auth/change-password"): "any signed-in user, own password",
    ("GET", "/api/changelog"): "any signed-in user",
    ("GET", "/api/changelog/{version}"): "any signed-in user",
    ("GET", "/api/roles/permissions"): "any signed-in user, catalogue only",
    ("GET", "/api/roles"): "any signed-in user, role names only",
    ("GET", "/api/secrets"): "require_superadmin, no permission key for secrets",
    ("PUT", "/api/secrets/{provider}"): "require_superadmin",
    ("DELETE", "/api/secrets/{provider}"): "require_superadmin",
    ("POST", "/api/secrets/{provider}/test"): "require_superadmin",
}


def _app_routes(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from cti_core.config import get_settings

    for key, value in {
        "DATABASE__URL": "postgresql+asyncpg://x:x@localhost/x",
        "DATABASE__SYNC_URL": "postgresql+psycopg://x:x@localhost/x",
        "AUTH__JWT_SECRET": "unit-test-jwt-secret",
        "AUTH__SESSION_SECRET_KEY": "unit-test-session-secret",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    from cti_api.main import create_app

    def flat(routes: list[Any]) -> list[Any]:
        out: list[Any] = []
        for r in routes:
            contexts = getattr(r, "effective_route_contexts", None)
            if contexts is not None:
                out.extend(contexts() if callable(contexts) else contexts)
            elif hasattr(r, "dependant"):
                out.append(r)
        return out

    return [r for r in flat(create_app().routes) if r.path.startswith("/api")]


def _permissions(dependant: Any) -> set[str]:
    found: set[str] = set()
    for sub in dependant.dependencies:
        perm = getattr(sub.call, "permission", None)
        if perm:
            found.add(perm)
        found |= _permissions(sub)
    return found


def test_every_api_route_requires_a_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    missing: list[str] = []
    seen: set[tuple[str, str]] = set()
    for route in _app_routes(monkeypatch):
        perms = _permissions(route.dependant)
        for method in route.methods:
            key = (method, route.path)
            seen.add(key)
            if not perms and key not in EXEMPT:
                missing.append(f"{method} {route.path}")
    assert missing == [], "routes without require_permission:\n" + "\n".join(sorted(missing))
    stale = sorted(f"{m} {p}" for m, p in EXEMPT if (m, p) not in seen)
    assert stale == [], f"EXEMPT lists routes that no longer exist: {stale}"


def test_system_roles_only_use_known_permissions() -> None:
    for name, spec in SYSTEM_ROLES.items():
        unknown = set(spec["permissions"]) - set(ALL_PERMISSIONS)  # type: ignore[arg-type]
        assert not unknown, (name, unknown)


def test_analyst_keeps_cve_triage_and_ops_views() -> None:
    analyst = set(SYSTEM_ROLES["analyst"]["permissions"])  # type: ignore[arg-type]
    assert {"manage_cve", "view_ops", "manage_pir", "manage_rfi", "manage_ioc"} <= analyst
    assert not {"manage_newsletter", "send_cve_email", "manage_intel"} & analyst
    assert "manage_api_tokens" not in analyst


def test_admin_has_manage_api_tokens() -> None:
    assert "manage_api_tokens" in SYSTEM_ROLES["admin"]["permissions"]
