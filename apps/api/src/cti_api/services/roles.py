"""Permission + 3 role sistem -- awalnya port 1:1 dari
`ScraperNewsWeb/app/services/role_service.py` (26 permission). `manage_cve` dan `view_ops`
ditambah saat permission mulai ditegakkan per route (2026-10-24): tanpa keduanya, analyst
kehilangan ack/ticket CVE dan halaman Scrapers/Data health yang selama ini bisa dibuka.
Closed enumeration (konstanta Python), BUKAN tabel terpisah -- lihat docstring
`cti_core.db.models.auth` buat alasannya."""

from __future__ import annotations

from cti_core.db.repositories.auth import AsyncRoleRepo
from sqlalchemy.ext.asyncio import AsyncSession

ALL_PERMISSIONS: dict[str, str] = {
    # News & Intelligence
    "view_news": "View news articles and feeds",
    "export_data": "Export data as CSV / reports",
    "view_intel": "View threat intelligence reports",
    "manage_intel": "Create and edit intelligence reports",
    "view_ta": "View threat actor profiles",
    "view_ioc": "View and search IOC database",
    "manage_ioc": "Add and delete IOCs",
    "view_cve": "View CVE and vulnerability data",
    "manage_cve": "Acknowledge, ticket and mark CVEs; edit monitored tech and packages",
    "send_cve_email": "Send CVE email reports",
    "view_stix": "View STIX intelligence bundles",
    "wisemap_access": "Access WiseMap CTI mind maps",
    # Operations
    "manage_rfi": "Create and manage RFIs",
    "manage_pir": "Create and manage PIRs",
    # Communication
    "view_newsletter": "Access newsletter",
    "manage_newsletter": "Create and send newsletters",
    "view_tweets": "View monitored Twitter/X feeds",
    "manage_tweets": "Configure monitored accounts",
    # Platform administration
    "view_audit_log": "View audit log",
    "manage_users": "Add, edit, and delete users",
    "reset_password": "Reset other users' passwords",
    "manage_clients": "Add and delete client tenants",
    "manage_policy": "Edit password policy",
    "manage_roles": "Create and delete custom roles",
    "view_ops": "View scraper status and data health",
    "manage_scraper": "Configure scraper health settings",
    "manage_sources": "Add and edit news sources",
    "manage_changelog": "Edit changelog entries",
}

_ALL = list(ALL_PERMISSIONS.keys())

SYSTEM_ROLES: dict[str, dict[str, object]] = {
    "superadmin": {
        "display_name": "Super Admin",
        "permissions": _ALL,
    },
    "admin": {
        "display_name": "Admin",
        "permissions": [p for p in _ALL if p not in ("manage_roles", "manage_clients")],
    },
    "analyst": {
        "display_name": "Analyst",
        "permissions": [
            "view_news",
            "export_data",
            "manage_rfi",
            "manage_pir",
            "view_intel",
            "view_ta",
            "view_ioc",
            "view_cve",
            "manage_cve",
            "view_ops",
            "view_newsletter",
            "view_tweets",
            "view_stix",
            "wisemap_access",
        ],
    },
}


async def ensure_system_roles(session: AsyncSession) -> None:
    repo = AsyncRoleRepo(session)
    for name, spec in SYSTEM_ROLES.items():
        permissions = spec["permissions"]
        display_name = spec["display_name"]
        assert isinstance(permissions, list)
        assert isinstance(display_name, str)
        await repo.upsert_system_role(name=name, display_name=display_name, permissions=permissions)
    await session.commit()
