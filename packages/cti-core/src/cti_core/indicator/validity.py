"""Validitas indikator: `valid_until = last_seen_at + TTL` per tipe (spec P7a 3.1).

Fungsi murni supaya jalur ingest sync/async dan task reconcile memakai satu aturan. Hash tidak
kedaluwarsa (`None`): sebuah hash tetap menunjuk berkas yang sama selamanya, sedangkan IP/domain
berpindah tangan."""

import datetime
import json

from cti_core.config import IndicatorSettings

HASH_TYPES = frozenset({"md5", "sha1", "sha256"})
# Semua tipe non-hash yang diterima `ttl_days` (sumber reconcile; termasuk url_with_path).
TTL_TYPES = ("ip", "domain", "url", "url_with_path", "email")


def ttl_days(ioc_type: str, cfg: IndicatorSettings) -> int | None:
    """TTL dalam hari; `None` untuk hash. Tipe tak dikenal (mis. `cve`) -> `ValueError`."""
    if ioc_type in HASH_TYPES:
        return None
    match ioc_type:
        case "ip":
            return cfg.ttl_ip_days
        case "domain":
            return cfg.ttl_domain_days
        case "url" | "url_with_path":
            return cfg.ttl_url_days
        case "email":
            return cfg.ttl_email_days
    raise ValueError(f"tipe indikator tidak punya TTL: {ioc_type!r}")


def extend(
    current: datetime.datetime | None,
    ioc_type: str,
    now: datetime.datetime,
    cfg: IndicatorSettings,
) -> datetime.datetime | None:
    """`max(current, now + TTL)`: perpanjang saat terlihat lagi, tidak pernah memendekkan."""
    days = ttl_days(ioc_type, cfg)
    if days is None:
        return None
    candidate = now + datetime.timedelta(days=days)
    return candidate if current is None else max(current, candidate)


def ttl_fingerprint(cfg: IndicatorSettings) -> str:
    """Sidik jari TTL; reconcile memakainya untuk tahu kapan TTL berubah dan perlu hitung ulang."""
    return json.dumps(cfg.model_dump(), sort_keys=True)
