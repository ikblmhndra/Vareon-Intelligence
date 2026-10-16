"""`tools/ops/check_secrets.py` sesudah probe-nya pindah ke `cti_api.services.secret_probes`
(ROADMAP #23, PR 2).

CLI tetap dipakai operator (`make` target, runbook rotasi, verifikasi staging) dan tetap membaca
`.env`, jadi permukaannya TIDAK boleh berubah: daftar `CHECKS` (urutan dan kuncinya, TANPA
otx/abuseipdb/virustotal -- itu hanya untuk halaman admin) dan nama-nama yang di-export. Perilaku
probe-nya sendiri dijaga `tests/unit/test_check_secrets.py` (tidak diubah, jaring regresi) dan
`tests/unit/test_secret_probes.py`.
"""

from __future__ import annotations

from cti_api.services import secret_probes

from tools.ops import check_secrets


def test_the_cli_checks_are_unchanged_in_keys_and_order() -> None:
    assert list(check_secrets.CHECKS) == [
        "llm",
        "telegram",
        "telegram_threads",
        "nvd",
        "github",
        "twitter",
        "x",
        "graph",
    ]


def test_the_cli_checks_do_not_include_the_ioc_providers() -> None:
    assert {"otx", "abuseipdb", "virustotal"}.isdisjoint(check_secrets.CHECKS)


def test_the_cli_shares_the_result_type_with_the_api_probes() -> None:
    assert check_secrets.Result is secret_probes.Result


def test_the_cli_still_exports_its_public_surface() -> None:
    for name in ("run_checks", "CHECKS", "Result", "exit_code", "main", "check_telegram_threads"):
        assert hasattr(check_secrets, name), name
