"""Halaman admin "Third-party keys" (ROADMAP #23): status, ubah, hapus override, dan tes.

Prinsip, berurutan dari yang paling mahal kalau dilanggar:
  - NILAI SECRET TIDAK PERNAH KELUAR dari modul ini ke respons, log, atau audit: hanya `last4`
    di respons (itu pun cuma kalau key >= 12 karakter) dan nama field + nilai field NON-secret di
    audit. Pesan galat tidak memuat nilai apa pun.
  - Setiap tulis/hapus meminta password akun yang sedang login. Cookie sesi curian saja tidak boleh
    cukup untuk memutar key ke milik penyerang (yang lebih berbahaya daripada membacanya: mis.
    `llm.url` ke host penyerang mengirim seluruh teks artikel ke sana). Kegagalan dihitung per
    username bersama endpoint ganti password (`rate_limit.check_password_lockout`): lewat batasnya
    semua sesi akun itu dicabut. Percobaan gagal dicatat sebagai `secret_reauth_failed`.
  - Key baru DIPROBE dulu (settings kandidat = `.env` + override baru) dan baru disimpan kalau tidak
    ditolak vendor; key salah ketik tidak boleh sempat menghentikan pipeline.
  - Override `llm` selalu satu paket (provider + model + url): kalau tidak, key baru bisa terkirim
    ke URL gateway lama yang masih ada di `.env`. `llm.url` di luar `dev` hanya boleh host di
    allowlist env (SSRF dan eksfiltrasi), dan DIVALIDASI ULANG di setiap PUT kecuali nilainya sama
    dengan `LLM__URL` di `.env` (konfigurasi operator yang sudah dipercaya).
  - Tulis dan hapus pada satu provider diserialisasi dengan advisory lock Postgres: baca-gabung-
    simpan dengan probe berdetik-detik di tengahnya tidak boleh saling menimpa (dua admin mengubah
    field `llm` berbeda, atau Revert yang dihidupkan lagi oleh PUT yang sedang berjalan).
  - Menghapus override tidak butuh master key: kalau master key hilang, admin harus tetap bisa
    membersihkan baris yang tidak terbaca. Menulis butuh master key (503 kalau kosong).

Router yang commit transaksi dan memanggil `overlay.invalidate()` sesudahnya; fungsi di sini hanya
`flush`, kecuali jalur yang akan berakhir dengan galat tetapi catatan auditnya harus bertahan
(password salah, penolakan sesudah password benar): `get_db` me-rollback saat exception.
"""

from __future__ import annotations

import asyncio
import datetime
import urllib.parse

from cti_core.config import Settings, get_settings
from cti_core.db.models.runtime_secret import RuntimeSecret
from cti_core.db.repositories.auth import AsyncAuditLogRepo, AsyncUserRepo
from cti_core.db.repositories.runtime_secret import AsyncRuntimeSecretRepo
from cti_core.runtime_secrets import crypto, overlay
from cti_core.runtime_secrets.registry import (
    PROVIDERS,
    SecretProvider,
    UnknownProvider,
    get_provider,
)
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser
from cti_api.rate_limit import (
    check_password_lockout,
    clear_password_failures,
    note_password_failure,
)
from cti_api.schemas.secrets import (
    SecretFieldOut,
    SecretProviderOut,
    SecretsStatusOut,
    SecretTestOut,
    Source,
)
from cti_api.security import verify_password
from cti_api.services.secret_probes import run_probe

MAX_VALUE_LEN = 2048
_LLM_BUNDLE = frozenset({"provider", "model", "url"})
_AUDIT_NAMES_MAX = 20


def mask_last4(value: str) -> str | None:
    """Empat karakter terakhir, hanya kalau key cukup panjang supaya itu bukan sebagian isinya."""
    return value[-4:] if len(value) >= 12 else None


def validate_llm_url(url: str, *, environment: str, allowed_hosts: str) -> str:
    """URL gateway LLM yang sudah di-strip, atau `ValueError` (alasan tanpa memuat URL-nya).

    Kosong sah: artinya default vendor. Spasi dan karakter kontrol di mana pun ditolak (parser
    URL membuang tab/newline diam-diam, jadi nilai mentah yang disimpan bisa beda dari yang
    divalidasi). Di `dev` http/https dan host apa pun boleh (gateway lokal seperti 9router). Di
    luar `dev` wajib https, port 443 (eksplisit atau tidak), DAN hostname ada di `allowed_hosts`:
    URL ini menerima key LLM beserta seluruh teks artikel."""
    value = url.strip()
    if not value:
        return ""
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("URL tidak boleh memuat spasi atau karakter kontrol")
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise ValueError("URL harus http atau https")
    host = parts.hostname or ""
    if not host:
        raise ValueError("URL tanpa host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL tidak boleh memuat kredensial")
    if environment == "dev":
        return value
    if parts.scheme != "https":
        raise ValueError("di luar dev URL wajib https")
    if parts.port not in (None, 443):
        raise ValueError("di luar dev port harus 443")
    allowed = {h.strip().lower() for h in allowed_hosts.split(",") if h.strip()}
    if host not in allowed:
        raise ValueError("host tidak ada di SECRETS_LLM_URL_ALLOWED_HOSTS")
    return value


def _display_url(value: str) -> str:
    """URL untuk ditampilkan: tanpa userinfo dan query. Nilai dari `.env` tidak divalidasi seketat
    override, jadi bisa saja memuat kredensial atau token di URL-nya."""
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    if not parts.netloc:
        return "" if ("@" in value or "?" in value) else value
    netloc = parts.netloc.rpartition("@")[2]
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _spec(provider: str) -> SecretProvider:
    try:
        return get_provider(provider)
    except UnknownProvider:
        raise HTTPException(status_code=404, detail="Unknown provider") from None


def _iso(value: datetime.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _provider_out(
    spec: SecretProvider,
    base: Settings,
    snapshot: overlay.OverlaySnapshot,
    row: RuntimeSecret | None,
    probe: SecretTestOut | None = None,
) -> SecretProviderOut:
    overrides = snapshot.overrides.get(spec.key, {})
    effective = overlay.apply_overrides(base, {spec.key: overrides}) if overrides else base
    group = getattr(effective, spec.key)
    fields: list[SecretFieldOut] = []
    for f in spec.fields:
        raw = getattr(group, f.name)
        in_db = f.name in overrides
        if f.secret:
            source: Source = "db" if in_db and raw else ("env" if raw else "unset")
            fields.append(
                SecretFieldOut(
                    name=f.name,
                    secret=True,
                    source=source,
                    value=None,
                    last4=mask_last4(raw) if raw else None,
                    choices=[],
                )
            )
        else:
            source = "db" if in_db else ("env" if raw else "unset")
            fields.append(
                SecretFieldOut(
                    name=f.name,
                    secret=False,
                    source=source,
                    value=_display_url(raw) if f.name == "url" else raw,
                    last4=None,
                    choices=list(f.choices),
                )
            )
    secret_sources = [fo.source for fo in fields if fo.secret]
    provider_source: Source
    if spec.key in snapshot.overrides:
        provider_source = "db"
    elif any(s != "unset" for s in secret_sources):
        provider_source = "env"
    else:
        provider_source = "unset"
    return SecretProviderOut(
        key=spec.key,
        label=spec.label,
        source=provider_source,
        fields=fields,
        updated_by=row.updated_by if row is not None else None,
        updated_at=_iso(row.updated_at) if row is not None else None,
        last_test_ok=row.last_test_ok if row is not None else None,
        last_test_at=_iso(row.last_test_at) if row is not None else None,
        error=snapshot.errors.get(spec.key),
        probe=probe,
    )


async def _snapshot(
    session: AsyncSession,
) -> tuple[Settings, list[RuntimeSecret], overlay.OverlaySnapshot]:
    base = get_settings()
    keys = base.secrets_encryption_keys
    rows = await AsyncRuntimeSecretRepo(session).list_platform()
    if not crypto.is_configured(keys):
        # Baris yang ada tetap ditampilkan (dengan galat), supaya admin bisa membersihkannya dan
        # tidak ada baris yatim yang hidup lagi diam-diam begitu master key dipasang kembali.
        return (
            base,
            rows,
            overlay.OverlaySnapshot(errors={r.provider: "master_key_missing" for r in rows}),
        )
    return base, rows, overlay.snapshot_from_rows(rows, keys)


async def get_status(session: AsyncSession) -> SecretsStatusOut:
    base, rows, snapshot = await _snapshot(session)
    by_provider = {r.provider: r for r in rows}
    return SecretsStatusOut(
        enabled=crypto.is_configured(base.secrets_encryption_keys),
        providers=[
            _provider_out(spec, base, snapshot, by_provider.get(spec.key))
            for spec in PROVIDERS.values()
        ],
    )


async def _provider_status(
    session: AsyncSession, provider: str, probe: SecretTestOut | None = None
) -> SecretProviderOut:
    base, rows, snapshot = await _snapshot(session)
    row = next((r for r in rows if r.provider == provider), None)
    return _provider_out(_spec(provider), base, snapshot, row, probe)


def _password_matches(plain: str, hashed: str) -> bool:
    try:
        return verify_password(plain, hashed)
    except ValueError:  # bcrypt menolak password > 72 byte: tebakan yang salah, bukan 500
        return False


async def _verify_reauth(
    session: AsyncSession,
    redis: Redis,
    *,
    username: str,
    password: str,
    provider: str,
    ip: str,
) -> None:
    await check_password_lockout(redis, username)
    user = await AsyncUserRepo(session).get_by_username(username)
    if user is None or not user.password_hash:
        raise HTTPException(
            status_code=403,
            detail="This account has no local password; set one before changing keys",
        )
    # bcrypt ~0,2 dtk: di thread supaya event loop API tidak tertahan.
    if not await asyncio.to_thread(_password_matches, password, user.password_hash):
        await note_password_failure(redis, username)
        await AsyncAuditLogRepo(session).write(
            username=username, action="secret_reauth_failed", target_id=provider, ip_address=ip
        )
        await (
            session.commit()
        )  # request ini berakhir 403: tanpa commit, catatan audit ikut rollback
        raise HTTPException(status_code=403, detail="Password confirmation failed")
    await clear_password_failures(redis, username)


async def _lock_provider(session: AsyncSession, provider: str) -> None:
    """Serialkan tulis/hapus pada satu provider sampai transaksi selesai."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"runtime_secrets:{provider}"}
    )


def _validate_and_merge(
    spec: SecretProvider, existing: dict[str, str], requested: dict[str, str | None]
) -> tuple[dict[str, str], list[str]]:
    """(hasil gabungan, nama field yang BENAR-BENAR berubah). 422 untuk apa pun yang tidak valid.

    Nilai yang sama dengan yang sudah tersimpan tidak dihitung berubah: kirim ulang key yang sama
    tidak boleh memakai kuota vendor (probe), jatah tulis, dan mengotori audit."""
    specs = {f.name: f for f in spec.fields}
    merged = dict(existing)
    changed: list[str] = []
    for name, value in requested.items():
        field = specs.get(name)
        if field is None:
            raise HTTPException(status_code=422, detail=f"Unknown field '{name}' for {spec.key}")
        if value is None:
            if merged.pop(name, None) is not None:
                changed.append(name)
            continue
        value = value.strip()
        if len(value) > MAX_VALUE_LEN:
            raise HTTPException(status_code=422, detail=f"Field '{name}' is too long")
        if field.choices and value not in field.choices:
            raise HTTPException(status_code=422, detail=f"Field '{name}' has an invalid value")
        if field.secret:
            if not value:
                raise HTTPException(status_code=422, detail=f"Field '{name}' cannot be empty")
            # Key vendor itu ASCII tanpa spasi; teks hasil paste ("…", kutip melengkung, newline)
            # akan gagal di header HTTP sebelum sampai ke vendor dan hanya menghasilkan galat samar.
            if not value.isascii() or not value.isprintable() or any(c.isspace() for c in value):
                raise HTTPException(
                    status_code=422,
                    detail=f"Field '{name}' contains characters that cannot be part of a key",
                )
        if merged.get(name) == value:
            continue
        merged[name] = value
        changed.append(name)
    if spec.key == "llm" and merged and not merged.keys() >= _LLM_BUNDLE:
        raise HTTPException(
            status_code=422,
            detail="An llm override must set provider, model and url together "
            "(an empty url means the vendor default)",
        )
    if spec.key == "llm" and merged.get("url"):
        settings = get_settings()
        # `LLM__URL` di `.env` adalah konfigurasi operator yang sudah dipercaya: mengirim ulang
        # nilai yang sama (paket llm selalu membawa url) tidak boleh terblokir allowlist, kalau
        # tidak key tidak bisa dirotasi di host yang memakai gateway di `.env`. Selain itu SELALU
        # divalidasi, juga saat url tidak ikut diubah, supaya url lama yang hostnya sudah dicabut
        # dari allowlist tidak menerima key baru.
        if merged["url"] != settings.llm.url:
            try:
                merged["url"] = validate_llm_url(
                    merged["url"],
                    environment=settings.environment,
                    allowed_hosts=settings.secrets_llm_url_allowed_hosts,
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=f"llm.url rejected: {e}") from None
    return merged, sorted(set(changed))


def _decrypt_existing(row: RuntimeSecret | None, keys: str) -> dict[str, str]:
    if row is None:
        return {}
    try:
        return crypto.decrypt_fields(row.provider, bytes(row.secrets_enc), keys=keys)
    except crypto.SecretDecryptError:
        raise HTTPException(
            status_code=409,
            detail="The stored override cannot be read (master key changed?); clear it first",
        ) from None


def _requested_names(fields: dict[str, str | None]) -> list[str]:
    """Nama field untuk audit penolakan: dari klien, jadi dipotong agar audit tak dibanjiri."""
    return sorted(str(name)[:50] for name in list(fields)[:_AUDIT_NAMES_MAX])


async def _audit_rejection(
    session: AsyncSession,
    *,
    username: str,
    provider: str,
    fields: dict[str, str | None],
    reason: str,
    ip: str,
) -> None:
    await AsyncAuditLogRepo(session).write(
        username=username,
        action="secret_set_rejected",
        target_id=provider,
        detail={"fields": _requested_names(fields), "reason": reason},
        ip_address=ip,
    )
    await session.commit()  # request ini berakhir 422/409: tanpa commit audit ikut rollback


async def set_fields(
    session: AsyncSession,
    redis: Redis,
    *,
    user: AuthedUser,
    provider: str,
    fields: dict[str, str | None],
    password: str,
    ip: str,
) -> SecretProviderOut:
    spec = _spec(provider)
    keys = get_settings().secrets_encryption_keys
    if not crypto.is_configured(keys):
        raise HTTPException(
            status_code=503,
            detail="Secrets encryption is not configured (SECRETS_ENCRYPTION_KEYS is empty)",
        )
    username = user["username"]
    await _verify_reauth(
        session, redis, username=username, password=password, provider=provider, ip=ip
    )
    await _lock_provider(session, provider)

    repo = AsyncRuntimeSecretRepo(session)
    row = await repo.get_platform(provider)
    try:
        merged, changed = _validate_and_merge(spec, _decrypt_existing(row, keys), fields)
    except HTTPException as exc:
        reason = exc.detail if isinstance(exc.detail, str) else "invalid"
        await _audit_rejection(
            session, username=username, provider=provider, fields=fields, reason=reason, ip=ip
        )
        raise
    audit = AsyncAuditLogRepo(session)

    if not changed:  # tidak ada yang berubah: tanpa probe, tulis, atau audit
        return await _provider_status(session, provider)

    if not merged:  # semua field dihapus: sama dengan kembali ke `.env`
        if row is not None:
            await repo.delete_platform(provider)
            await audit.write(
                username=username, action="secret_clear", target_id=provider, ip_address=ip
            )
        return await _provider_status(session, provider)

    candidate = overlay.apply_overrides(get_settings(), {provider: merged})
    probe = await run_probe(provider, candidate)
    if probe.status == "FAIL":
        await _audit_rejection(
            session,
            username=username,
            provider=provider,
            fields=fields,
            reason=f"probe {probe.status}",
            ip=ip,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Probe failed; nothing was saved",
                "probe": {"status": probe.status, "detail": probe.detail},
            },
        )
    verified = probe.status == "OK"
    await repo.upsert_platform(
        provider,
        crypto.encrypt_fields(provider, merged, keys=keys),
        username,
        last_test_ok=True if verified else None,
        last_test_at=datetime.datetime.now(datetime.UTC) if verified else None,
    )
    secret_names = {f.name for f in spec.fields if f.secret}
    await audit.write(
        username=username,
        action="secret_set",
        target_id=provider,
        detail={
            "fields": changed,
            # Nilai field NON-secret (provider/model/url llm) dicatat supaya forensik bisa tahu ke
            # gateway mana key diarahkan; nilai secret tidak pernah.
            "values": {n: merged[n] for n in changed if n in merged and n not in secret_names},
        },
        ip_address=ip,
    )
    return await _provider_status(
        session,
        provider,
        SecretTestOut(status=probe.status, detail=probe.detail),  # type: ignore[arg-type]
    )


async def clear_provider(
    session: AsyncSession,
    redis: Redis,
    *,
    user: AuthedUser,
    provider: str,
    password: str,
    ip: str,
) -> SecretProviderOut:
    _spec(provider)
    username = user["username"]
    await _verify_reauth(
        session, redis, username=username, password=password, provider=provider, ip=ip
    )
    await _lock_provider(session, provider)
    if not await AsyncRuntimeSecretRepo(session).delete_platform(provider):
        raise HTTPException(status_code=404, detail="No override for this provider")
    await AsyncAuditLogRepo(session).write(
        username=username, action="secret_clear", target_id=provider, ip_address=ip
    )
    return await _provider_status(session, provider)


async def probe_provider(
    session: AsyncSession, *, user: AuthedUser, provider: str, ip: str
) -> SecretTestOut:
    """Probe konfigurasi EFEKTIF saat ini (`.env` + override yang tersimpan)."""
    _spec(provider)
    base, rows, snapshot = await _snapshot(session)
    effective = overlay.apply_overrides(base, snapshot.overrides)
    # Dibaca sebelum rollback: rollback meng-expire objek ORM, dan atributnya tidak bisa di-refresh
    # lazily di sesi async.
    has_row = any(r.provider == provider for r in rows)
    # Probe bisa berdetik-detik: jangan menahan transaksi (dan koneksi pool) terbuka selama itu.
    await session.rollback()
    result = await run_probe(provider, effective)
    # Hanya hasil yang BENAR-BENAR mewakili override tersimpan yang dicatat: baris yang tidak
    # terbaca tidak ikut diprobe (yang diprobe `.env`), SKIP tidak mengetes apa pun, dan NOTE
    # (kena batas pemakaian) bukan bukti key valid.
    if has_row and provider not in snapshot.errors and result.status in ("OK", "FAIL"):
        await AsyncRuntimeSecretRepo(session).record_test(
            provider, result.status == "OK", datetime.datetime.now(datetime.UTC)
        )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="secret_test",
        target_id=provider,
        detail={"status": result.status},
        ip_address=ip,
    )
    return SecretTestOut(status=result.status, detail=result.detail)  # type: ignore[arg-type]
