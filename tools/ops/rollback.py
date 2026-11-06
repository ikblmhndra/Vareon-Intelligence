#!/usr/bin/env python3
"""Rollback versi platform (Fase 10.G) -- SATU perintah yang aman, karena rollback naif
(`CTI_TAG=<lama> docker compose up -d`) terbukti MEMBAHAYAKAN di latihan staging:

  service `migrate` menjalankan `alembic upgrade head` di SETIAP `up`. Kalau DB sudah di revisi
  yang LEBIH BARU dari yang dikenal image lama -> "Can't locate revision" -> `migrate` gagal ->
  compose sudah terlanjur MENGHENTIKAN api/worker yang berjalan (mereka bergantung pada `migrate`)
  -> **outage**, tepat di saat orang sedang panik.

Alat ini memeriksa dulu (pre-flight), lalu mengurus urutan yang benar:

  1. revisi DB sekarang        <- `alembic current` di image SEKARANG
  2. revisi head image target  <- `alembic heads` di image TARGET
     (+ `alembic history` dari KEDUA image, digabung: image lama tak kenal revisi baru)
  3. kalau DB LEBIH BARU dari target: `alembic downgrade <head target>` dijalankan dengan image
     SEKARANG (hanya image itu yang kenal revisi barunya), sesudah konfirmasi `--yes` --
     downgrade bisa MENGHAPUS kolom/tabel (data hilang), ambil backup dulu
     (`tools/ops/pg_backup.py backup`)
  4. `CTI_TAG=<target> docker compose up -d <service>` lalu tunggu API `/healthz` + semua healthy.

    python3 tools/ops/rollback.py --current-tag stg --tag prev --yes \\
        --compose "docker compose -p cti-stg --env-file stg.stack.env --profile app" \\
        --env-file stg.env --network cti-stg_default --api-url http://127.0.0.1:18000/healthz

Menolak (exit 1, tidak menyentuh apa pun) kalau: riwayat migrasi tidak linear, revisi DB dan head
target bercabang (bukan leluhur satu sama lain), atau downgrade diperlukan tapi `--yes` tidak ada.
`--dry-run` mencetak rencana tanpa mengubah apa pun. Latihan staging: rollback + downgrade +
semua healthy = 21,9 detik.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass

DEFAULT_SERVICES = "api worker worker-browser worker-nlp worker-cve web"
REV_RE = re.compile(r"^([0-9a-f]{6,})\b")


class RollbackError(Exception):
    """Pre-flight menolak, atau langkah gagal -- exit 1."""


class Shell:
    """Batas ke dunia luar; diganti di test."""

    def run(self, cmd: Sequence[str], env: dict[str, str] | None = None) -> tuple[int, str]:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, **(env or {})},
        )
        return proc.returncode, proc.stdout + proc.stderr

    def http_ok(self, url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return bool(response.status == 200)
        except (urllib.error.URLError, OSError):
            return False

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class Config:
    current_tag: str
    tag: str
    compose: tuple[str, ...]
    env_file: str
    network: str
    services: tuple[str, ...]
    api_url: str
    api_image: str = "cti-api"
    wait_s: int = 300


# -- parsing keluaran alembic (murni) -------------------------------------------------------------


def parse_revision(output: str) -> str | None:
    """Revisi dari `alembic current`/`heads`: baris pertama yang diawali id heksa (baris INFO dan
    log lain dilewati). `None` = kosong (DB belum dimigrasi)."""
    for line in output.splitlines():
        m = REV_RE.match(line.strip())
        if m and not line.startswith(("INFO", "WARNI")):
            return m.group(1)
    return None


def parse_parents(history: str) -> dict[str, str | None]:
    """`{revisi: induk}` dari `alembic history`. Baris `parent -> rev (tag), pesan`. Riwayat
    bercabang/merge, atau baris yang tak terbaca, -> `RollbackError` (jangan menebak, dan jangan
    melewati baris diam-diam: peta yang bolong bisa menghasilkan keputusan downgrade yang salah)."""
    parents: dict[str, str | None] = {}
    for raw in history.splitlines():
        line = raw.strip()
        if " -> " not in line or line.startswith(("INFO", "WARNI")):
            continue
        parent, _, rest = line.partition(" -> ")
        rev_part = rest.split(", ", 1)[0]  # "<rev>" atau "<rev> (head)"
        rev, _, tags = rev_part.partition(" ")
        if "," in parent or "(" in parent or "branchpoint" in tags or "mergepoint" in tags:
            raise RollbackError("riwayat migrasi tidak linear (cabang/merge) -- rollback manual")
        if not REV_RE.match(rev) or not parent:
            raise RollbackError(f"baris riwayat migrasi tak terbaca: {line[:80]!r}")
        parents[rev] = None if parent == "<base>" else parent
    return parents


def ancestors(rev: str, parents: dict[str, str | None]) -> list[str]:
    """`rev` dan semua leluhurnya (terbaru dulu)."""
    chain = []
    cursor: str | None = rev
    while cursor is not None:
        chain.append(cursor)
        cursor = parents.get(cursor)
    return chain


@dataclass(frozen=True)
class Plan:
    db_rev: str | None
    target_head: str | None
    downgrade_to: str | None
    """Revisi tujuan downgrade; `None` = tidak perlu downgrade."""
    steps: tuple[str, ...] = ()
    """Revisi yang akan di-downgrade (terbaru dulu)."""


def merge_parents(*maps: dict[str, str | None]) -> dict[str, str | None]:
    """Gabungan peta induk dari beberapa image. Image LAMA tidak kenal revisi baru dan image BARU
    kenal semuanya, jadi hanya gabungan keduanya yang memuat DB dan target sekaligus. Revisi yang
    sama dengan induk berbeda antar image = riwayat berbeda -> `RollbackError`."""
    merged: dict[str, str | None] = {}
    for parents in maps:
        for rev, parent in parents.items():
            if rev in merged and merged[rev] != parent:
                raise RollbackError(
                    f"revisi {rev} punya induk berbeda antar image -- rollback manual"
                )
            merged[rev] = parent
    return merged


def decide(db_rev: str | None, target_head: str | None, parents: dict[str, str | None]) -> Plan:
    """Butuh downgrade atau tidak. `parents` = gabungan peta induk dari image sekarang + target."""
    if db_rev is None or target_head is None or db_rev == target_head:
        return Plan(db_rev, target_head, None)
    db_chain = ancestors(db_rev, parents)
    if target_head in db_chain:  # target LEBIH TUA dari DB -> downgrade ke target
        return Plan(
            db_rev, target_head, target_head, tuple(db_chain[: db_chain.index(target_head)])
        )
    if db_rev in ancestors(target_head, parents):  # target LEBIH BARU -> `migrate` yang naikkan
        return Plan(db_rev, target_head, None)
    raise RollbackError(
        f"revisi DB ({db_rev}) dan head image target ({target_head}) bercabang -- bukan leluhur "
        "satu sama lain; rollback manual"
    )


# -- eksekusi ------------------------------------------------------------


def alembic_cmd(cfg: Config, tag: str, *args: str) -> list[str]:
    return [
        "docker", "run", "--rm", "--network", cfg.network, "--env-file", cfg.env_file,
        "--entrypoint", "alembic", f"{cfg.api_image}:{tag}", *args,
    ]  # fmt: skip


def rollback(
    cfg: Config,
    sh: Shell,
    *,
    yes: bool = False,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> float:
    """Jalankan rollback; kembalikan detik yang dipakai."""
    started = sh.now()

    rc, out = sh.run(alembic_cmd(cfg, cfg.current_tag, "current"))
    if rc != 0:
        raise RollbackError(
            f"`alembic current` gagal di image {cfg.current_tag}: {out.strip()[-200:]}"
        )
    db_rev = parse_revision(out)

    rc, out = sh.run(alembic_cmd(cfg, cfg.tag, "heads"))
    if rc != 0:
        raise RollbackError(
            f"`alembic heads` gagal di image target {cfg.tag}: {out.strip()[-200:]}"
        )
    target_head = parse_revision(out)

    histories = []
    for tag in (cfg.current_tag, cfg.tag):
        rc, history = sh.run(alembic_cmd(cfg, tag, "history"))
        if rc != 0:
            raise RollbackError(f"`alembic history` gagal di image {tag}")
        histories.append(parse_parents(history))
    plan = decide(db_rev, target_head, merge_parents(*histories))

    log(f"pre-flight: revisi DB={db_rev}  head image target ({cfg.tag})={target_head}")
    if plan.downgrade_to:
        log(
            f"  -> DB LEBIH BARU dari target: downgrade {' -> '.join(plan.steps)} "
            f"ke {plan.downgrade_to}"
        )
        log("     (downgrade bisa MENGHAPUS kolom/tabel; pastikan sudah backup)")
        if not yes and not dry_run:
            raise RollbackError(
                "downgrade diperlukan tapi `--yes` tidak diberikan -- tidak ada yang diubah"
            )
    else:
        log("  -> tidak perlu downgrade")

    up = [*cfg.compose, "up", "-d", *cfg.services]
    if dry_run:
        if plan.downgrade_to:
            log(
                "[dry-run] "
                + shlex.join(alembic_cmd(cfg, cfg.current_tag, "downgrade", plan.downgrade_to))
            )
        log(f"[dry-run] CTI_TAG={cfg.tag} " + shlex.join(up))
        return sh.now() - started

    if plan.downgrade_to:
        rc, out = sh.run(alembic_cmd(cfg, cfg.current_tag, "downgrade", plan.downgrade_to))
        if rc != 0:  # JANGAN lanjut `up`: DB setengah jalan + image lain = lebih buruk
            raise RollbackError(f"downgrade GAGAL (tidak lanjut ke `up`): {out.strip()[-300:]}")
        log(f"downgrade selesai [+{sh.now() - started:.1f} dtk]")

    rc, out = sh.run(up, env={"CTI_TAG": cfg.tag})
    if rc != 0:
        raise RollbackError(f"`compose up` gagal: {out.strip()[-300:]}")
    log(f"compose up selesai [+{sh.now() - started:.1f} dtk]")

    deadline = sh.now() + cfg.wait_s
    while not sh.http_ok(cfg.api_url):
        if sh.now() > deadline:
            raise RollbackError(f"API tidak melayani {cfg.api_url} dalam {cfg.wait_s} dtk")
        sh.sleep(1)
    log(f"API melayani [+{sh.now() - started:.1f} dtk]")

    rc, out = sh.run(alembic_cmd(cfg, cfg.tag, "current"))
    final = parse_revision(out) if rc == 0 else None
    if target_head and final != target_head:
        raise RollbackError(f"revisi DB akhir ({final}) != head target ({target_head})")
    log(f"SELESAI: tag={cfg.tag} revisi DB={final} total {sh.now() - started:.1f} dtk")
    return sh.now() - started


def main(argv: Sequence[str] | None = None, *, shell: Shell | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--current-tag", required=True, help="tag image yang SEDANG berjalan")
    p.add_argument("--tag", required=True, help="tag image TUJUAN rollback")
    p.add_argument(
        "--compose",
        default="docker compose",
        help="awalan perintah compose (project/env-file/profile)",
    )
    p.add_argument(
        "--env-file", required=True, help="env aplikasi (DATABASE__SYNC_URL, dst) buat alembic"
    )
    p.add_argument(
        "--network", required=True, help="jaringan docker compose (mis. cti-stg_default)"
    )
    p.add_argument("--services", default=DEFAULT_SERVICES)
    p.add_argument("--api-url", default="http://127.0.0.1:8000/healthz")
    p.add_argument("--wait", type=int, default=300, help="detik menunggu API melayani")
    p.add_argument("--yes", action="store_true", help="setuju downgrade DB (bisa menghapus data)")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    cfg = Config(
        current_tag=a.current_tag, tag=a.tag, compose=tuple(shlex.split(a.compose)),
        env_file=a.env_file, network=a.network, services=tuple(a.services.split()),
        api_url=a.api_url, wait_s=a.wait,
    )  # fmt: skip
    try:
        rollback(cfg, shell or Shell(), yes=a.yes, dry_run=a.dry_run)
    except RollbackError as e:
        print(f"GAGAL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
