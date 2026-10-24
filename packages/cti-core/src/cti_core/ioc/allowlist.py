"""Pencocokan allowlist IOC -- dipakai persist enrich dan newsletter SESUDAH `canonical()`.

Sejak 0.8.6 IOC yang cocok allowlist TIDAK dibuang di extractor: barisnya disimpan dengan
`auto_suppressed=True` + alasan, supaya keputusan bisa diaudit dan dibatalkan (menghapus entri
allowlist membatalkan tanda IOC yang alasannya persis entri itu, `AsyncIocAllowlistRepo.delete`).
Domain ikut dicek (dulu hanya IP/URL/email). Entri `url_domain` menutup host URL DAN domain
polos, termasuk subdomainnya (`store1.gofile.io` kena `gofile.io`, `notgofile.io` tidak)."""

from __future__ import annotations

from importlib import resources

from cti_core.ioc.extractor import _email_domain, _url_domain

_REASON_SUFFIX = "(infrastructure-abuse)"


def _suffix_hit(host: str, entries: set[str]) -> str | None:
    """Entri terpanjang yang sama dengan `host` atau jadi induk domainnya; None kalau tak ada."""
    host = host.strip().lower().rstrip(".")
    if not host:
        return None
    labels = host.split(".")
    for i in range(len(labels)):
        candidate = ".".join(labels[i:])
        if candidate in entries:
            return candidate
    return None


def _is_bare_host_url(url: str) -> bool:
    rest = url.split("://", 1)[-1]
    _, sep, tail = rest.partition("/")
    if not sep:
        return "?" not in rest and "#" not in rest
    return tail == ""


def allowlist_match(
    ioc_type: str, canonical_value: str, allowlist: dict[str, set[str]]
) -> str | None:
    """Alasan `allowlist:<tipe entri>:<entri> (infrastructure-abuse)` atau None."""
    url_domains = allowlist.get("url_domains", set())
    if ioc_type == "domain":
        entry = _suffix_hit(canonical_value, url_domains)
        kind = "url_domain"
    elif ioc_type == "url":
        # URL dengan path/query bermakna adalah indikator payload (`gofile.io/d/abc123`): tidak
        # pernah ditandai. Hanya URL yang berhenti di host (path kosong atau "/", tanpa query).
        if not _is_bare_host_url(canonical_value):
            return None
        entry = _suffix_hit(_url_domain(canonical_value), url_domains)
        kind = "url_domain"
    elif ioc_type == "email":
        entry = _suffix_hit(_email_domain(canonical_value), allowlist.get("email_domains", set()))
        kind = "email_domain"
    elif ioc_type == "ip":
        entry = canonical_value if canonical_value in allowlist.get("ips", set()) else None
        kind = "ip"
    else:
        return None
    if entry is None:
        return None
    return allowlist_reason(kind, entry)


def allowlist_reason(entry_type: str, entry: str) -> str:
    """Alasan suppression untuk satu entri allowlist. Dipakai juga saat entri dihapus: hanya IOC
    dengan alasan PERSIS ini yang tandanya dibatalkan (alasan lain/keputusan analis tidak)."""
    return f"allowlist:{entry_type}:{entry} {_REASON_SUFFIX}"


def load_seed() -> list[str]:
    """Domain seed (huruf kecil) dari `allowlist_seed.txt`; baris kosong dan `#` diabaikan."""
    text = resources.files("cti_core.ioc").joinpath("allowlist_seed.txt").read_text("utf-8")
    out: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            out.append(line)
    return out
