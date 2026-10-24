"""Salinan beku aturan kanonik + allowlist di migrasi 0.8.6 harus SAMA dengan kode aplikasi.

Kalau aturan aplikasi berubah tanpa menaikkan `CANONICAL_RULES_VERSION`, test ini gagal; kalau
versinya dinaikkan (aturan baru = migrasi baru), migrasi lama memang tidak boleh ikut berubah
dan test ini dilewati."""

from __future__ import annotations

import importlib.util
import itertools
import pathlib
from types import ModuleType

import pytest
from cti_core.ioc.allowlist import allowlist_match, load_seed
from cti_core.ioc.canonical import CANONICAL_RULES_VERSION, canonical

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("e7b2d4a9c6f1_*.py"))
    spec = importlib.util.spec_from_file_location("canonical_iocs_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

pytestmark = pytest.mark.skipif(
    CANONICAL_RULES_VERSION != migration.CANONICAL_RULES_VERSION,
    reason="aturan kanonik sudah versi baru; migrasi lama sengaja tidak ikut berubah",
)

_DOTS = [".", "[.]", "[.", "(.)", "{.}", "[dot]", "(dot)", "[DOT]", "(Dot)", " [.] ", "\\."]
_ATS = ["@", "[@]", "(@)", "[at]", "(at)", "[AT]", " (At) "]
_SCHEMES = ["http", "https", "hxxp", "hxxps", "HXXPS", "Http", "fxp", "ftp", "", "[:]"]
_TAILS = ["", "/", "/Payload.EXE", "/a/B?X=Y", "?q=1", "#Frag", "/p[.]php", "/x?u=hxxp://a[.]b"]


def _samples() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for dot in _DOTS:
        for host in (f"Evil{dot}COM", f"sub{dot}evil{dot}com", f"evil{dot}com."):
            out.append(("domain", host))
            out.append(("domain", f"  {host}  "))
        out.append(("ip", f"1{dot}2{dot}3{dot}4"))
        out.append(("ip", f" 10{dot}0{dot}0{dot}1 "))
        for at in _ATS:
            out.append(("email", f"Bob{at}Mail{dot}Example{dot}COM"))
    for scheme, dot, tail in itertools.product(_SCHEMES, _DOTS[:6], _TAILS):
        host = f"WWW{dot}Evil{dot}com"
        prefix = "" if scheme == "" else ("hxxp[:]" if scheme == "[:]" else f"{scheme}:")
        out.append(("url", f"{prefix}//{host}{tail}" if prefix else f"{host}{tail}"))
        out.append(("url", f"{scheme or 'https'}://user:Pw@{host}:8443{tail}"))
    for h in ("ABCDEF0123", " abcdef ", "AbC"):
        for t in ("sha256", "sha1", "md5"):
            out.append((t, h))
    out += [("unknown", "  Keep Case  "), ("url", "  HXXPS://Evil[.]com/Payload.EXE?A=B  ")]
    out += [
        ("domain", "evil[[.]]com"),
        ("ip", "1[[.]]2[[.]]3[[.]]4"),
        ("url", "hxxps://evil[[.]]com/P[[.]]x"),
        ("email", "bob[[@]]ex[[.]]com"),
    ]
    return out


@pytest.mark.parametrize(("ioc_type", "value"), _samples())
def test_frozen_canonical_matches_app(ioc_type: str, value: str) -> None:
    assert migration.canonical(ioc_type, value) == canonical(ioc_type, value)


@pytest.mark.parametrize(("ioc_type", "value"), _samples())
def test_frozen_canonical_is_idempotent(ioc_type: str, value: str) -> None:
    # Merge mengandalkan ini: nilai kanonik tidak pernah berubah lagi, jadi UPDATE ke nilai
    # kanonik tidak bisa bertabrakan dengan baris kelompok lain.
    once = migration.canonical(ioc_type, value)
    assert migration.canonical(ioc_type, once) == once


def test_frozen_seed_matches_seed_file() -> None:
    assert list(migration.SEED_URL_DOMAINS) == load_seed()


_ALLOWLIST = {
    "url_domains": {"gofile.io", "github.com"},
    "email_domains": {"gmail.com"},
    "ips": {"8.8.8.8"},
}
_MATCH_CASES = [
    ("domain", "store1.gofile.io"),
    ("domain", "gofile.io"),
    ("domain", "notgofile.io"),
    ("domain", "gofile.io.evil.net"),
    ("url", "https://cdn.gofile.io"),
    ("url", "https://cdn.gofile.io/"),
    ("url", "https://gofile.io/d/abc123"),
    ("url", "https://gofile.io?id=1"),
    ("url", "https://gofile.io/#f"),
    ("url", "https://evil.net/gofile.io"),
    ("url", "ftp://gofile.io"),
    ("url", "https://user@gofile.io/"),
    ("url", "github.com"),
    ("email", "bob@mail.gmail.com"),
    ("email", "bob@evilgmail.com"),
    ("email", "bob"),
    ("ip", "8.8.8.8"),
    ("ip", "8.8.8.80"),
    ("sha256", "abc"),
]


@pytest.mark.parametrize(("ioc_type", "value"), _MATCH_CASES)
def test_frozen_allowlist_match_matches_app(ioc_type: str, value: str) -> None:
    assert migration.allowlist_match(ioc_type, value, _ALLOWLIST) == allowlist_match(
        ioc_type, value, _ALLOWLIST
    )
