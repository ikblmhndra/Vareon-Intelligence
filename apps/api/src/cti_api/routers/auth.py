"""Port 1:1 dari `ScraperNewsWeb/app/routers/auth.py` -- alur/aturan bisnis
dipertahankan (rate limit login, policy password, audit tiap aksi admin),
storage-nya yang pindah dari koleksi Mongo ke repo Postgres (Fase 2/7)."""

from __future__ import annotations

from cti_core.config import get_settings
from cti_core.db.models.auth import User
from cti_core.db.repositories.auth import (
    AsyncAuditLogRepo,
    AsyncClientRepo,
    AsyncRoleRepo,
    AsyncUserRepo,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    get_db,
    get_redis,
    request_ip,
    require_auth,
    require_permission,
)
from cti_api.rate_limit import (
    check_password_lockout,
    clear_password_failures,
    is_rate_limited,
    note_password_failure,
)
from cti_api.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetRequest,
    PolicySettings,
    TokenResponse,
    UserClientsUpdate,
    UserCreate,
    UserRoleUpdate,
)
from cti_api.security import create_token, decode_token, hash_password, verify_password
from cti_api.services import policy as policy_service
from cti_api.token_revocation import revoke_token, revoke_user_tokens

router = APIRouter(prefix="/api/auth", tags=["auth"])

_DUMMY_HASH = hash_password("dummy-password-for-timing")
_INIT_LOCK_KEY = 7_261_001  # pg_advisory_xact_lock untuk bootstrap /init


def _pw_error(errors: list[str]) -> HTTPException:
    return HTTPException(status_code=422, detail=f"Password missing: {', '.join(errors)}")


def _user_client_ids(user: User) -> list[str]:
    return [uc.client_id for uc in user.clients] or ["default"]


# ── Policy ───────────────────────────────────────────────────


@router.get("/policy")
async def get_pw_policy(session: AsyncSession = Depends(get_db)) -> dict[str, object]:
    policy = await policy_service.get_policy(session)
    return {**policy, "hint": policy_service.policy_hint(policy)}


@router.put("/policy")
async def update_pw_policy(
    body: PolicySettings,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_policy")),
) -> dict[str, object]:
    policy = body.model_dump(exclude={"force_all_change"})
    await policy_service.save_policy(session, policy)
    flagged = 0
    if body.force_all_change:
        flagged = await AsyncUserRepo(session).flag_force_pw_change_all_non_admin()
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="update_pw_policy",
        detail={**policy, "force_all_change": body.force_all_change},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True, "flagged_users": flagged, "hint": policy_service.policy_hint(policy)}


# ── Auth ─────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    ip = request_ip(request)
    if await is_rate_limited(redis, f"login:{ip}", max_requests=10, window_seconds=60):
        raise HTTPException(
            status_code=429, detail="Too many login attempts. Try again in a minute."
        )
    user_repo = AsyncUserRepo(session)
    user = await user_repo.get_by_username(body.username)
    if not user:
        verify_password(body.password, _DUMMY_HASH)  # samakan waktu respons dgn user yang ada
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.password_hash:
        raise HTTPException(
            status_code=400, detail="This account uses SSO. Please sign in via the SSO button."
        )
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    client_ids = _user_client_ids(user)
    token = create_token(
        user.username, user.role_name, client_ids=client_ids, force_pw_change=user.force_pw_change
    )
    client_doc = await AsyncClientRepo(session).get(client_ids[0]) if client_ids else None
    client_countries = [c.country_code for c in client_doc.countries] if client_doc else []
    await AsyncAuditLogRepo(session).write(username=user.username, action="login", ip_address=ip)
    await user_repo.update_last_sign_in(user.username)
    await session.commit()
    settings = get_settings().auth
    response.set_cookie(
        key="cti_auth",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.jwt_expire_min * 60,
        path="/",
    )
    return TokenResponse(
        access_token=token,
        username=user.username,
        role=user.role_name,
        client_ids=client_ids,
        client_countries=client_countries,
        force_pw_change=user.force_pw_change,
    )


@router.post("/logout")
async def logout(
    response: Response,
    authorization: str | None = Header(None),
    redis: Redis = Depends(get_redis),
    _user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    response.delete_cookie(key="cti_auth", path="/")
    # token yang sudah lolos `require_auth` pasti ter-decode; cabut supaya tidak bisa dipakai lagi
    if authorization:
        await revoke_token(redis, decode_token(authorization.split(" ", 1)[1]))
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    current = await AsyncUserRepo(session).get_by_username(user["username"])
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Penghitung kegagalan dipakai bersama halaman Third-party Keys (lihat `rate_limit`): endpoint
    # ini dulu menerima tebakan password tanpa batas dari pemegang cookie sesi, lalu hasilnya bisa
    # dipakai untuk mengonfirmasi perubahan key di tempat lain.
    await check_password_lockout(redis, user["username"])
    try:
        password_ok = bool(current.password_hash) and verify_password(
            body.current_password, current.password_hash
        )
    except ValueError:  # bcrypt menolak password > 72 byte: itu tebakan yang salah, bukan 500
        password_ok = False
    if not password_ok:
        await note_password_failure(redis, user["username"])
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    await clear_password_failures(redis, user["username"])
    policy = await policy_service.get_policy(session)
    errors = policy_service.validate_password(body.new_password, policy)
    if errors:
        raise _pw_error(errors)
    ok = await AsyncUserRepo(session).reset_password(
        user["username"], hash_password(body.new_password)
    )
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"], action="change_password", ip_address=request_ip(request)
    )
    await session.commit()
    await revoke_user_tokens(redis, user["username"])  # sesi lama (termasuk ini) harus login ulang
    return {"ok": True}


@router.post("/init")
async def init_admin(
    body: UserCreate, session: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    """Bootstrap: bikin superadmin pertama. Gagal kalau udah ada user."""
    # kunci transaksi: dua /init bersamaan tidak bisa sama-sama melihat count()==0
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INIT_LOCK_KEY})
    user_repo = AsyncUserRepo(session)
    if await user_repo.count() > 0:
        raise HTTPException(status_code=409, detail="Users already exist — use /api/auth/users")
    policy = await policy_service.get_policy(session)
    errors = policy_service.validate_password(body.password, policy)
    if errors:
        raise _pw_error(errors)
    await AsyncClientRepo(session).ensure_default()
    user = await user_repo.create(
        username=body.username,
        password_hash=hash_password(body.password),
        role_name="superadmin",
        client_ids=["default"],
    )
    await session.commit()
    return {"username": user.username, "role": user.role_name, "client_ids": ["default"]}


@router.get("/me")
async def me(
    session: AsyncSession = Depends(get_db), user: AuthedUser = Depends(require_auth)
) -> dict[str, object]:
    client_ids = user["client_ids"]
    client_repo = AsyncClientRepo(session)
    # Sekuensial, bukan asyncio.gather -- satu AsyncSession gak boleh dipakai konkuren; user
    # dengan >1 client dulu kadang kena 500 (InvalidRequestError) lalu di-logout web.
    client_docs = [await client_repo.get(cid) for cid in client_ids]
    clients_map = {
        cid: [c.country_code for c in doc.countries] if doc else []
        for cid, doc in zip(client_ids, client_docs, strict=True)
    }
    first_countries = clients_map.get(client_ids[0], []) if client_ids else []
    return {**user, "client_countries": first_countries, "clients_map": clients_map}


@router.get("/users")
async def get_users(
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_users")),
) -> list[dict[str, object]]:
    users = await AsyncUserRepo(session).list_all()
    return [
        {
            "username": u.username,
            "role": u.role_name,
            "client_ids": [uc.client_id for uc in u.clients] or ["default"],
            "force_pw_change": u.force_pw_change,
            "last_sign_in": u.last_sign_in.isoformat() if u.last_sign_in else None,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


async def _forbid_admin_touching_superadmin(
    session: AsyncSession, admin: AuthedUser, username: str
) -> None:
    """Admin (non-superadmin) tidak boleh mengubah akun superadmin."""
    if admin["role"] == "superadmin":
        return
    target = await AsyncUserRepo(session).get_by_username(username)
    if target is not None and target.role_name == "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can modify a superadmin")


def _forbid_foreign_clients(admin: AuthedUser, client_ids: list[str]) -> None:
    """Admin (non-superadmin) hanya boleh memberi akses ke client yang dia sendiri punya."""
    if admin["role"] == "superadmin":
        return
    outside = sorted(set(client_ids) - set(admin["client_ids"]))
    if outside:
        raise HTTPException(
            status_code=403, detail=f"Cannot grant access to client(s) you do not have: {outside}"
        )


@router.post("/users")
async def add_user(
    body: UserCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_users")),
) -> dict[str, object]:
    policy = await policy_service.get_policy(session)
    errors = policy_service.validate_password(body.password, policy)
    if errors:
        raise _pw_error(errors)
    if not await AsyncRoleRepo(session).exists(body.role):
        raise HTTPException(status_code=422, detail=f"Role '{body.role}' does not exist")
    if body.role == "superadmin" and admin["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can grant superadmin role")
    _forbid_foreign_clients(admin, body.client_ids)
    user_repo = AsyncUserRepo(session)
    if await user_repo.get_by_username(body.username):
        raise HTTPException(status_code=409, detail="Username already exists")
    user = await user_repo.create(
        username=body.username,
        password_hash=hash_password(body.password),
        role_name=body.role,
        client_ids=body.client_ids,
    )
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="create_user",
        target_id=body.username,
        detail={"role": body.role, "client_ids": body.client_ids},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"username": user.username, "role": user.role_name, "client_ids": body.client_ids}


@router.post("/users/{username}/reset-password")
async def reset_user_password(
    username: str,
    body: PasswordResetRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    admin: AuthedUser = Depends(require_permission("reset_password")),
) -> dict[str, bool]:
    await _forbid_admin_touching_superadmin(session, admin, username)
    user_repo = AsyncUserRepo(session)
    target = await user_repo.get_by_username(username)
    if target and not target.password_hash:
        raise HTTPException(
            status_code=400, detail="SSO-provisioned accounts do not support password reset."
        )
    policy = await policy_service.get_policy(session)
    errors = policy_service.validate_password(body.new_password, policy)
    if errors:
        raise _pw_error(errors)
    ok = await user_repo.reset_password(username, hash_password(body.new_password))
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="reset_password",
        target_id=username,
        ip_address=request_ip(request),
    )
    await session.commit()
    await revoke_user_tokens(redis, username)
    return {"ok": True}


@router.put("/users/{username}/clients")
async def update_user_client_list(
    username: str,
    body: UserClientsUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    admin: AuthedUser = Depends(require_permission("manage_users")),
) -> dict[str, object]:
    if not body.client_ids:
        raise HTTPException(status_code=400, detail="client_ids must not be empty")
    await _forbid_admin_touching_superadmin(session, admin, username)
    _forbid_foreign_clients(admin, body.client_ids)
    ok = await AsyncUserRepo(session).update_client_ids(username, body.client_ids)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="update_user_clients",
        target_id=username,
        detail={"client_ids": body.client_ids},
        ip_address=request_ip(request),
    )
    await session.commit()
    await revoke_user_tokens(redis, username)
    return {"ok": True, "client_ids": body.client_ids}


@router.put("/users/{username}/role")
async def update_user_role_endpoint(
    username: str,
    body: UserRoleUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    admin: AuthedUser = Depends(require_permission("manage_users")),
) -> dict[str, object]:
    if not await AsyncRoleRepo(session).exists(body.role):
        raise HTTPException(status_code=422, detail=f"Role '{body.role}' does not exist")
    if body.role == "superadmin" and admin["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can grant superadmin role")
    await _forbid_admin_touching_superadmin(session, admin, username)
    ok = await AsyncUserRepo(session).update_role(username, body.role)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="update_user_role",
        target_id=username,
        detail={"role": body.role},
        ip_address=request_ip(request),
    )
    await session.commit()
    await revoke_user_tokens(redis, username)
    return {"ok": True, "role": body.role}


@router.get("/audit-log")
async def audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: str | None = None,
    action: str | None = None,
    session: AsyncSession = Depends(get_db),
    _admin: AuthedUser = Depends(require_permission("view_audit_log")),
) -> dict[str, object]:
    entries, total = await AsyncAuditLogRepo(session).query(
        page=page, page_size=page_size, username=user, action=action
    )
    logs = [
        {
            "user": e.username,
            "action": e.action,
            "target_id": e.target_id,
            "detail": e.detail,
            "ip": e.ip_address or "",
            "timestamp": e.at.isoformat(),
        }
        for e in entries
    ]
    return {"logs": logs, "total": total, "page": page, "page_size": page_size}
