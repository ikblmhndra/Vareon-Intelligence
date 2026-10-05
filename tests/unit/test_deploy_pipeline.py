"""Pagar CD: workflow deploy tidak boleh terpicu PR/fork, skrip deploy harus utuh."""

from __future__ import annotations

import pathlib
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
SCRIPT = ROOT / "tools" / "ops" / "deploy.sh"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def test_deploy_hanya_dari_ci_main_atau_manual() -> None:
    wf = _workflow()
    triggers = wf.get("on") or wf[True]  # YAML 1.1: kunci `on` terbaca sebagai True
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}  # tidak ada pull_request/push
    assert triggers["workflow_run"]["workflows"] == ["CI"]
    assert triggers["workflow_run"]["branches"] == ["main"]
    assert triggers["workflow_run"]["types"] == ["completed"]


def test_job_deploy_menolak_pr_dan_fork() -> None:
    job = _workflow()["jobs"]["deploy"]
    cond = " ".join(str(job["if"]).split())
    assert "workflow_run.conclusion == 'success'" in cond
    assert "workflow_run.event == 'push'" in cond
    assert "head_repository.full_name == github.repository" in cond
    assert job["runs-on"] == ["self-hosted", "cti-prod"]
    assert job["environment"] == "production"


def test_deploy_tidak_membatalkan_deploy_yang_sedang_jalan() -> None:
    conc = _workflow()["concurrency"]
    assert conc["group"] == "deploy-production"
    assert conc["cancel-in-progress"] is False


def test_sha_lewat_env_bukan_interpolasi_ke_script() -> None:
    """`${{ ... }}` di dalam `run:` = command injection; nilai harus lewat `env:`."""
    for step in _workflow()["jobs"]["deploy"]["steps"]:
        assert "${{" not in step["run"], step["run"]


def test_deploy_sh_executable_sintaks_valid_dan_help_jalan() -> None:
    assert SCRIPT.stat().st_mode & 0o111, "deploy.sh harus executable"
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0
    out = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0 and "rollback" in out.stdout


def test_deploy_sh_tidak_pernah_downgrade_otomatis() -> None:
    code = [line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")]
    assert any("rollback.py" in line for line in code)
    assert not [line for line in code if "--yes" in line]  # downgrade DB selalu keputusan manusia
