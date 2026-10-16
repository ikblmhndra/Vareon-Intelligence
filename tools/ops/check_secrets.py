#!/usr/bin/env python3
"""Cek apakah secret/API key yang dikonfigurasi BENERAN diterima provider-nya
(bukan cuma "terisi"): satu request BACA-DOANG per provider, tanpa efek samping,
tanpa nge-print secret.

Dipakai: verifikasi staging sebelum rehearsal (Fase 10.G), dan verifikasi
SESUDAH rotasi secret di produksi (Fase 10.F) -- key baru yang salah ketik
ketahuan sebelum go-live, bukan pas scraper pertama gagal jam 3 pagi.

    # dari root repo (baca .env), atau di dalam container (baca env-nya):
    uv run python tools/ops/check_secrets.py
    docker run --rm --env-file stg.env -v "$PWD/tools:/tools:ro" cti-worker:stg \\
        python /tools/ops/check_secrets.py

Yang dicek (read-only): LLM `GET /models` (tanpa generate, gak makan kuota),
Telegram `getMe` + `getChat` (TIDAK ngirim pesan), NVD `resultsPerPage=1`,
GitHub `/rate_limit`, twitterapi.io `user/info`, API resmi X `GET /2/usage/tweets` (bearer;
endpoint pemakaian, tidak membaca satu tweet pun -- terverifikasi HTTP 200, tanpa tagihan baca).
Microsoft Graph SENGAJA gak dites (cuma dilaporin terisi atau nggak) -- satu-satunya cara ngetes
adalah ngirim/bikin email beneran.

Exit code 1 kalau ada key yang TERISI tapi DITOLAK, atau LLM/Telegram gagal.
Key opsional yang kosong = SKIP (bukan gagal).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

# Probe-nya dipindah ke `cti_api.services.secret_probes`: halaman admin memakai kode yang sama dan
# image API tidak membawa `tools/`. Nama-nama ini tetap diekspor dari sini (tes, pemanggil lama).
from cti_api.services.secret_probes import (
    Result,
    check_github,
    check_llm,
    check_nvd,
    check_telegram,
    check_twitter,
    check_x,
    redact,
)

REQUIRED = {"llm", "telegram"}


def _secrets(settings: Any) -> list[str]:
    vals = [
        settings.llm.api_key,
        settings.telegram.bot_token,
        settings.nvd.api_key,
        settings.github.token,
        settings.twitter.api_key,
        settings.x.bearer_token,
        settings.graph.client_secret,
    ]
    return [v for v in vals if v and len(v) >= 6]


def check_telegram_threads(settings: Any, timeout: float) -> Result:
    """Offline: `thread_id` per topik. 0 = tanpa thread, pesan masuk chat utama; kalau SEMUA 0 (atau
    beberapa topik berbagi satu id) topik-topik itu menumpuk di satu tempat. Bukan kegagalan --
    cuma NOTE, karena menumpuk itu kadang memang disengaja (mis. chat tes biasa tanpa Topics)."""
    ids: dict[str, int] = dict(settings.telegram.thread_ids)
    if not ids:
        return Result("telegram_threads", "NOTE", "TELEGRAM__THREAD_IDS kosong")
    zero = sorted(t for t, i in ids.items() if not i)
    if len(zero) == len(ids):
        return Result(
            "telegram_threads",
            "NOTE",
            f"SEMUA {len(ids)} topik thread_id 0 -> semua alert masuk chat utama, satu tempat",
        )
    notes = []
    if zero:
        notes.append(f"{len(zero)} topik masih 0 (masuk chat utama): {', '.join(zero)}")
    by_id: dict[int, list[str]] = {}
    for topic, thread_id in sorted(ids.items()):
        if thread_id:
            by_id.setdefault(thread_id, []).append(topic)
    shared = {i: ts for i, ts in by_id.items() if len(ts) > 1}
    if shared:
        notes.append(
            "berbagi thread: " + "; ".join(f"{i}: {', '.join(ts)}" for i, ts in shared.items())
        )
    if notes:
        return Result("telegram_threads", "NOTE", " | ".join(notes))
    return Result("telegram_threads", "OK", f"{len(ids)} topik, thread_id berbeda-beda")


def check_graph(settings: Any, timeout: float) -> Result:
    g = settings.graph
    set_fields = [k for k in ("tenant_id", "client_id", "client_secret", "sender") if getattr(g, k)]
    if not set_fields:
        return Result("graph", "SKIP", "kosong")
    return Result(
        "graph",
        "NOTE",
        f"TERISI ({', '.join(set_fields)}) -- gak dites; "
        "di staging ini bisa bikin draft/email BENERAN",
    )


CHECKS = {
    "llm": check_llm,
    "telegram": check_telegram,
    "telegram_threads": check_telegram_threads,
    "nvd": check_nvd,
    "github": check_github,
    "twitter": check_twitter,
    "x": check_x,
    "graph": check_graph,
}


def run_checks(
    settings: Any, *, only: list[str] | None = None, timeout: float = 15.0
) -> list[Result]:
    secrets = _secrets(settings)
    results = []
    for name, fn in CHECKS.items():
        if only and name not in only:
            continue
        res = fn(settings, timeout)
        res.detail = redact(res.detail, secrets)
        results.append(res)
    return results


def exit_code(results: list[Result]) -> int:
    return 1 if any(r.status == "FAIL" for r in results) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", help=f"koma-pisah dari: {', '.join(CHECKS)}")
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args(argv)

    from cti_core.config import get_settings

    only = [x.strip() for x in args.only.split(",")] if args.only else None
    settings = get_settings()
    if settings.secrets_encryption_keys:
        print(
            "NOTE: this checks the .env values only. Keys changed from the admin page "
            "(Third-party Keys) are not checked here; use the Test button there.",
            file=sys.stderr,
        )
    results = run_checks(settings, only=only, timeout=args.timeout)
    for r in results:
        req = " (wajib)" if r.name in REQUIRED else ""
        print(f"{r.status:5} {r.name:16}{req:9} {r.detail}")
    code = exit_code(results)
    print(
        "\nSEMUA OK" if code == 0 else "\nADA YANG GAGAL", file=sys.stderr if code else sys.stdout
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
