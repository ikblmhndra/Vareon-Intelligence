"""Pintasan ops di `Makefile` -- yang dikunci: perintah yang dirakit `make` untuk tool ops sekali
jalan menunjuk service dan file yang beneran ada, dan tanpa `ARGS` tool-nya hanya melapor (tidak
menulis).

`make -n` mencetak perintah tanpa menjalankannya, jadi test ini tidak butuh Docker."""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = "tools/ops/backfill_cve_published_at.py"

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="butuh make")


def make_n(*args: str) -> str:
    out = subprocess.run(
        ["make", "-n", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return " ".join(out.split())  # rapikan sambungan baris `\`


def test_backfill_runs_the_tool_inside_the_existing_worker_service() -> None:
    cmd = make_n("backfill-published-at")

    assert cmd.startswith("docker compose --env-file docker/stack.env --profile app run ")
    assert (
        "--rm --no-deps -T" in cmd
    )  # sekali jalan, tidak menyentuh postgres/redis/migrate, tanpa TTY
    assert "--entrypoint python worker" in cmd
    assert ":/tools:ro" in cmd  # `tools/` tidak ikut image, di-mount read-only
    assert "/tools/ops/backfill_cve_published_at.py" in cmd
    assert (ROOT / TOOL).is_file()


def test_backfill_without_args_only_reports() -> None:
    assert "--apply" not in make_n("backfill-published-at")


def test_backfill_passes_args_through() -> None:
    cmd = make_n("backfill-published-at", "ARGS=--apply --client acme")

    assert cmd.endswith("/tools/ops/backfill_cve_published_at.py --apply --client acme")


def test_help_lists_the_target() -> None:
    out = subprocess.run(
        ["make", "help"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout

    assert "make backfill-published-at" in out


def test_check_orphaned_tickets_runs_the_read_only_tool_in_the_worker_service() -> None:
    cmd = make_n("check-orphaned-tickets", "ARGS=--client acme")

    assert "--entrypoint python worker" in cmd and ":/tools:ro" in cmd
    assert cmd.endswith("/tools/ops/check_orphaned_tickets.py --client acme")
    assert (ROOT / "tools/ops/check_orphaned_tickets.py").is_file()
    assert "--apply" not in make_n("check-orphaned-tickets")  # tool ini memang tak punya --apply
