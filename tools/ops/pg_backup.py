#!/usr/bin/env python3
"""Backup + restore Postgres platform CTI (Fase 10.G). Cuma stdlib -- jalan di HOST
produksi tanpa `uv sync`; semua perintah Postgres dieksekusi DI DALAM container `postgres`
lewat `docker compose exec` (host tidak butuh klien Postgres).

    # dari direktori yang berisi docker-compose.yml + file env stack-nya:
    python3 tools/ops/pg_backup.py backup  --dir /var/backups/cti
    python3 tools/ops/pg_backup.py verify  --file /var/backups/cti/cti-20260927T010000Z.dump
    python3 tools/ops/pg_backup.py restore --file <dump> --to-db cti_restore_test
    python3 tools/ops/pg_backup.py prune   --dir /var/backups/cti

`--pg-exec` (atau env `PG_EXEC`) = awalan perintah yang menjalankan sesuatu DI container
postgres; default `docker compose exec -T postgres`. Staging (project `cti-stg`):
    --pg-exec "docker compose -p cti-stg --env-file stg.stack.env --profile app exec -T postgres"

  backup   `pg_dump -Fc` -> `<dir>/cti-<UTC>.dump` (+ `.sha256`, chmod 600). Ditulis ke
           `.partial` lalu di-rename SETELAH pg_dump sukses dan hasilnya lolos
           `pg_restore --list` -- tidak pernah ada berkas separuh jadi yang menyamar sebagai
           backup. Lalu retensi (`prune`). `--on-failure-cmd` dijalankan kalau gagal
           (mis. curl ke Telegram): backup yang gagal DIAM-DIAM itu kegagalan terburuk.
  verify   restore dump ke DB scratch, bandingkan `alembic_version` dan jumlah baris tabel
           kunci dengan DB live, lalu DROP scratch. Backup yang belum pernah dites restore
           itu belum backup.
  restore  restore ke DB target. MENOLAK DB live kecuali `--force-live`; DB target dibuat
           kalau belum ada, dan MENOLAK DB yang sudah berisi kecuali `--replace`.
  prune    retensi saja: berkas terbaru `--keep-min` SELALU dipertahankan; sisanya dibuang
           kalau lebih tua dari `--keep-days` (umur dari NAMA berkas, bukan mtime -- salinan
           dan rsync mengubah mtime).

Exit code 0 = sukses, 1 = gagal.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_UTC = datetime.timezone.utc  # noqa: UP017 -- jalan di python3 HOST (>= 3.9); `datetime.UTC` baru ada di 3.11

DEFAULT_PG_EXEC = "docker compose exec -T postgres"
NAME_RE = re.compile(r"^cti-(\d{8}T\d{6}Z)\.dump$")
SCRATCH_DB = "cti_restore_check"
KEY_TABLES = (
    "articles",
    "iocs",
    "indicators",
    "scraper_runs",
    "scraper_seen",
    "users",
    "monitored_accounts",
)
"""Dibandingkan live vs hasil restore di `verify`. Tabel yang tak ada di skema dilewati.
`iocs` (nama lama, kini view sejak 0.8.11) dan `indicators` (nama baru) sama-sama ada supaya
backup pra-rename tetap bisa diverifikasi."""


class BackupError(Exception):
    """Kegagalan yang harus membuat exit code 1 (dan `--on-failure-cmd` jalan)."""


# -- eksekusi (dipisah supaya logika bisa dites tanpa Docker) ------------------------------


class Executor(Protocol):
    def run(
        self,
        cmd: Sequence[str],
        *,
        stdin: Path | None = None,
        stdout: Path | None = None,
    ) -> tuple[int, str, str]:
        """Jalankan `cmd`; stdin/stdout opsional dari/ke berkas. -> (rc, stdout_text, stderr_text).
        `stdout_text` kosong kalau stdout dialihkan ke berkas."""


class SubprocessExecutor:
    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = cwd

    def run(
        self,
        cmd: Sequence[str],
        *,
        stdin: Path | None = None,
        stdout: Path | None = None,
    ) -> tuple[int, str, str]:
        fin = stdin.open("rb") if stdin else None
        fout = stdout.open("wb") if stdout else None
        try:
            proc = subprocess.run(
                list(cmd),
                stdin=fin,
                stdout=fout if fout else subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                check=False,
            )
        finally:
            if fin:
                fin.close()
            if fout:
                fout.close()
        out = "" if stdout else proc.stdout.decode(errors="replace")
        return proc.returncode, out, proc.stderr.decode(errors="replace")


@dataclass(frozen=True)
class Target:
    """Bagaimana menjangkau Postgres: awalan `exec`, user, dan DB live."""

    pg_exec: tuple[str, ...]
    user: str = "cti"
    db: str = "cti"

    def cmd(self, *args: str) -> list[str]:
        return [*self.pg_exec, *args]


# -- nama & retensi (murni) ---------------------------------------------------------------


def backup_name(now: datetime.datetime) -> str:
    return "cti-" + now.astimezone(_UTC).strftime("%Y%m%dT%H%M%SZ") + ".dump"


def parse_backup_time(name: str) -> datetime.datetime | None:
    m = NAME_RE.match(name)
    if not m:
        return None
    return datetime.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=_UTC)


def select_prunable(
    names: Sequence[str], now: datetime.datetime, *, keep_days: int, keep_min: int
) -> list[str]:
    """Nama berkas backup yang BOLEH dibuang. Yang bukan pola `cti-<UTC>.dump` tak pernah
    disentuh. `keep_min` terbaru selalu aman (jangan sampai retensi menghabiskan backup
    kalau backup-nya sendiri berhenti jalan berminggu-minggu)."""
    dated = sorted(((t, n) for n in names if (t := parse_backup_time(n)) is not None), reverse=True)
    cutoff = now - datetime.timedelta(days=keep_days)
    return [n for i, (t, n) in enumerate(dated) if i >= keep_min and t < cutoff]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -- operasi ---------------------------------------------------------------------------------


def toc_entries(ex: Executor, target: Target, dump: Path) -> int:
    """Jumlah entri `pg_restore --list` -- dump rusak/terpotong gagal di sini."""
    rc, out, err = ex.run(target.cmd("pg_restore", "--list"), stdin=dump)
    entries = [ln for ln in out.splitlines() if ln and not ln.startswith(";")]
    if rc != 0 or not entries:
        raise BackupError(f"{dump.name}: bukan dump valid ({err.strip()[:200] or 'kosong'})")
    return len(entries)


def backup(
    ex: Executor,
    target: Target,
    out_dir: Path,
    *,
    now: datetime.datetime,
    keep_days: int,
    keep_min: int,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    final = out_dir / backup_name(now)
    partial = final.with_suffix(".dump.partial")
    partial.unlink(missing_ok=True)

    rc, _, err = ex.run(
        target.cmd("pg_dump", "-U", target.user, "-d", target.db, "-Fc", "--no-owner"),
        stdout=partial,
    )
    try:
        if rc != 0:
            raise BackupError(f"pg_dump gagal (rc={rc}): {err.strip()[:300]}")
        if not partial.exists() or partial.stat().st_size == 0:
            raise BackupError("pg_dump menghasilkan berkas kosong")
        toc_entries(ex, target, partial)
    except BackupError:
        partial.unlink(missing_ok=True)
        raise

    os.chmod(partial, 0o600)
    partial.rename(final)
    digest = sha256_file(final)
    checksum = final.with_name(final.name + ".sha256")
    checksum.write_text(f"{digest}  {final.name}\n")
    os.chmod(checksum, 0o600)

    prune(out_dir, now=now, keep_days=keep_days, keep_min=keep_min)
    return final


def prune(out_dir: Path, *, now: datetime.datetime, keep_days: int, keep_min: int) -> list[str]:
    names = [p.name for p in out_dir.iterdir() if p.is_file()]
    doomed = select_prunable(names, now, keep_days=keep_days, keep_min=keep_min)
    for name in doomed:
        (out_dir / name).unlink()
        (out_dir / (name + ".sha256")).unlink(missing_ok=True)
    return doomed


def check_checksum(dump: Path) -> None:
    """Kalau ada `<dump>.sha256`, harus cocok (korupsi saat disalin/rsync ketahuan)."""
    checksum = dump.with_name(dump.name + ".sha256")
    if not checksum.exists():
        return
    expected = checksum.read_text().split()[0]
    if sha256_file(dump) != expected:
        raise BackupError(f"{dump.name}: checksum sha256 TIDAK cocok -- berkas rusak")


def _psql(ex: Executor, target: Target, db: str, sql: str) -> str:
    rc, out, err = ex.run(
        target.cmd("psql", "-U", target.user, "-d", db, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql)
    )
    if rc != 0:
        raise BackupError(f"psql ({db}) gagal: {err.strip()[:300]}")
    return out.strip()


def _db_exists(ex: Executor, target: Target, db: str) -> bool:
    return _psql(ex, target, "postgres", f"SELECT 1 FROM pg_database WHERE datname = '{db}'") == "1"


def _table_count(ex: Executor, target: Target, db: str) -> int:
    return int(
        _psql(
            ex,
            target,
            db,
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'",
        )
    )


def restore(
    ex: Executor,
    target: Target,
    dump: Path,
    to_db: str,
    *,
    force_live: bool = False,
    replace: bool = False,
) -> None:
    if to_db == target.db and not force_live:
        raise BackupError(
            f"MENOLAK restore ke DB live '{to_db}' -- pakai `--to-db` lain, atau `--force-live` "
            "kalau memang itu maksudnya (menimpa data live!)"
        )
    check_checksum(dump)
    toc_entries(ex, target, dump)

    if _db_exists(ex, target, to_db):
        if _table_count(ex, target, to_db) > 0 and not replace:
            raise BackupError(f"DB '{to_db}' sudah berisi -- pakai `--replace` untuk menimpanya")
        if replace:
            _psql(ex, target, "postgres", f'DROP DATABASE "{to_db}" WITH (FORCE)')
    if not _db_exists(ex, target, to_db):
        _psql(ex, target, "postgres", f'CREATE DATABASE "{to_db}"')

    rc, _, err = ex.run(
        target.cmd("pg_restore", "-U", target.user, "-d", to_db, "--no-owner", "--exit-on-error"),
        stdin=dump,
    )
    if rc != 0:
        raise BackupError(f"pg_restore gagal (rc={rc}): {err.strip()[:300]}")


@dataclass(frozen=True)
class VerifyReport:
    alembic_live: str
    alembic_restored: str
    counts: dict[str, tuple[int | None, int | None]]
    """tabel -> (live, hasil restore); `None` = tabel tidak ada di sisi itu."""

    def problems(self) -> list[str]:
        out: list[str] = []
        if self.alembic_live != self.alembic_restored:
            out.append(
                f"alembic_version beda: live={self.alembic_live} restore={self.alembic_restored} "
                "(normal kalau ada migrasi SESUDAH backup diambil)"
            )
        for table, (live, restored) in self.counts.items():
            if restored is None:
                if live is not None:
                    out.append(f"{table}: ada di live ({live}) tapi TIDAK ada di hasil restore")
            elif live is not None and restored > live:
                out.append(f"{table}: hasil restore ({restored}) LEBIH BANYAK dari live ({live})")
            elif live and restored == 0:
                out.append(f"{table}: live {live} baris tapi hasil restore KOSONG")
        return out


def verify(ex: Executor, target: Target, dump: Path) -> VerifyReport:
    """Restore ke DB scratch, bandingkan dengan live, DROP scratch (selalu)."""
    restore(ex, target, dump, SCRATCH_DB, replace=True)
    try:
        counts: dict[str, tuple[int | None, int | None]] = {}
        for table in KEY_TABLES:
            counts[table] = (
                _count(ex, target, target.db, table),
                _count(ex, target, SCRATCH_DB, table),
            )
        return VerifyReport(
            alembic_live=_version(ex, target, target.db),
            alembic_restored=_version(ex, target, SCRATCH_DB),
            counts=counts,
        )
    finally:
        _psql(ex, target, "postgres", f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')


def _count(ex: Executor, target: Target, db: str, table: str) -> int | None:
    if _psql(ex, target, db, f"SELECT to_regclass('public.{table}') IS NOT NULL") != "t":
        return None
    return int(_psql(ex, target, db, f"SELECT count(*) FROM public.{table}"))


def _version(ex: Executor, target: Target, db: str) -> str:
    return _psql(ex, target, db, "SELECT version_num FROM alembic_version") or "?"


# -- CLI ------------------------------------------------------------------------------------------


def _target(args: argparse.Namespace) -> Target:
    return Target(
        pg_exec=tuple(shlex.split(args.pg_exec)),
        user=args.user,
        db=args.db,
    )


def _fail(args: argparse.Namespace, message: str) -> int:
    print(f"GAGAL: {message}", file=sys.stderr)
    cmd = getattr(args, "on_failure_cmd", None)
    if cmd:
        subprocess.run(cmd, shell=True, check=False, env={**os.environ, "BACKUP_ERROR": message})
    return 1


def main(argv: Sequence[str] | None = None, *, executor: Executor | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--pg-exec", default=os.environ.get("PG_EXEC", DEFAULT_PG_EXEC))
    parser.add_argument("--user", default=os.environ.get("POSTGRES_USER", "cti"))
    parser.add_argument("--db", default=os.environ.get("POSTGRES_DB", "cti"))
    sub = parser.add_subparsers(dest="command", required=True)

    def retention(p: argparse.ArgumentParser) -> None:
        p.add_argument("--keep-days", type=int, default=14)
        p.add_argument("--keep-min", type=int, default=3)

    p = sub.add_parser("backup")
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--on-failure-cmd")
    retention(p)
    p = sub.add_parser("prune")
    p.add_argument("--dir", type=Path, required=True)
    retention(p)
    p = sub.add_parser("verify")
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--on-failure-cmd")
    p = sub.add_parser("restore")
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--to-db", required=True)
    p.add_argument("--force-live", action="store_true")
    p.add_argument("--replace", action="store_true")

    args = parser.parse_args(argv)
    ex = executor or SubprocessExecutor()
    target = _target(args)
    now = datetime.datetime.now(_UTC)

    try:
        if args.command == "backup":
            path = backup(
                ex, target, args.dir, now=now, keep_days=args.keep_days, keep_min=args.keep_min
            )
            print(f"OK backup: {path} ({path.stat().st_size / 1e6:.1f} MB)")
        elif args.command == "prune":
            doomed = prune(args.dir, now=now, keep_days=args.keep_days, keep_min=args.keep_min)
            print(
                f"OK prune: {len(doomed)} berkas dibuang"
                + (f" ({', '.join(doomed)})" if doomed else "")
            )
        elif args.command == "verify":
            check_checksum(args.file)
            report = verify(ex, target, args.file)
            print(f"alembic: live={report.alembic_live} restore={report.alembic_restored}")
            for table, (live, restored) in report.counts.items():
                print(f"  {table:20} live={live} restore={restored}")
            problems = report.problems()
            if problems:
                return _fail(args, "; ".join(problems))
            print("OK verify: hasil restore konsisten dengan DB live")
        elif args.command == "restore":
            restore(
                ex, target, args.file, args.to_db, force_live=args.force_live, replace=args.replace
            )
            print(f"OK restore: {args.file.name} -> DB '{args.to_db}'")
    except (BackupError, OSError) as e:  # OSError: disk penuh, izin, dst -- juga harus memicu alarm
        return _fail(args, str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
