"""`tools/ops/pg_backup.py` -- backup/restore Postgres (Fase 10.G). Executor palsu, tanpa Docker.

Yang dikunci: berkas backup TIDAK pernah setengah jadi, retensi tidak menghabiskan backup,
restore tidak pernah menimpa DB live tanpa niat eksplisit, dan `verify` selalu membersihkan
DB scratch-nya.
"""

from __future__ import annotations

import datetime
import os
import stat
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.ops import pg_backup as pb

UTC = datetime.UTC
NOW = datetime.datetime(2026, 9, 27, 1, 0, 0, tzinfo=UTC)
PREFIX = ("docker", "compose", "exec", "-T", "postgres")
TARGET = pb.Target(pg_exec=PREFIX, user="cti", db="cti")
TOC = "; header\n1; 1259 16386 TABLE public articles cti\n2; 1259 16390 TABLE public iocs cti\n"


def tool_of(cmd: Sequence[str]) -> str:
    """Alat Postgres di perintah (awalan `exec` bisa apa saja)."""
    return next(t for t in cmd if t in ("pg_dump", "pg_restore", "psql"))


class FakeExecutor:
    """Skrip respons: `dump_rc`, `dump_bytes`, `toc_rc`, jawaban psql per potongan SQL."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.dump_rc, self.dump_bytes = 0, b"PGDMP-data"
        self.toc_rc, self.toc_out = 0, TOC
        self.restore_rc = 0
        self.databases: dict[str, int] = {"cti": 10, "postgres": 0}  # nama -> jumlah tabel
        self.counts: dict[tuple[str, str], int | None] = {}
        self.versions = {"cti": "rev-1", pb.SCRATCH_DB: "rev-1"}
        self.fail_count_query = False

    def run(self, cmd: Sequence[str], *, stdin: Path | None = None, stdout: Path | None = None):
        cmd = list(cmd)
        self.calls.append(cmd)
        tool = tool_of(cmd)
        if tool == "pg_dump":
            if stdout:
                stdout.write_bytes(self.dump_bytes)
            return self.dump_rc, "", "pg_dump: boom" if self.dump_rc else ""
        if tool == "pg_restore" and "--list" in cmd:
            return self.toc_rc, self.toc_out, "pg_restore: not a dump" if self.toc_rc else ""
        if tool == "pg_restore":
            if self.restore_rc == 0:
                self.databases[cmd[cmd.index("-d") + 1]] = 5
            return self.restore_rc, "", "pg_restore: error" if self.restore_rc else ""
        if tool == "psql":
            return self._psql(cmd[cmd.index("-d") + 1], cmd[-1])
        raise AssertionError(f"perintah tak dikenal: {cmd}")

    def _psql(self, db: str, sql: str):
        if "FROM pg_database" in sql:
            name = sql.split("datname = '")[1].rstrip("'")
            return 0, "1\n" if name in self.databases else "\n", ""
        if "information_schema.tables" in sql:
            return 0, f"{self.databases.get(db, 0)}\n", ""
        if sql.startswith("CREATE DATABASE"):
            self.databases[sql.split('"')[1]] = 0
            return 0, "", ""
        if sql.startswith("DROP DATABASE"):
            self.databases.pop(sql.split('"')[1], None)
            return 0, "", ""
        if "to_regclass" in sql:
            table = sql.split("public.")[1].split("'")[0]
            return 0, ("t\n" if self.counts.get((db, table), 0) is not None else "f\n"), ""
        if "count(*) FROM public." in sql:
            if self.fail_count_query:
                return 1, "", "psql: kaboom"
            return 0, f"{self.counts[(db, sql.split('public.')[1])]}\n", ""
        if "alembic_version" in sql:
            return 0, self.versions[db] + "\n", ""
        raise AssertionError(f"SQL tak dikenal: {sql}")

    def tools(self) -> list[str]:
        return [tool_of(c) for c in self.calls]


def pb_tool(cmd: Sequence[str]) -> str:
    return tool_of(cmd)


def stamp(days_ago: float) -> str:
    return pb.backup_name(NOW - datetime.timedelta(days=days_ago))


# --- nama & retensi -----------------------------------------------------------


def test_backup_name_is_utc_and_parses_back_to_the_same_instant() -> None:
    wib = datetime.timezone(datetime.timedelta(hours=7))
    name = pb.backup_name(datetime.datetime(2026, 9, 27, 8, 0, 5, tzinfo=wib))

    assert name == "cti-20260927T010005Z.dump"
    assert pb.parse_backup_time(name) == datetime.datetime(2026, 9, 27, 1, 0, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "name",
    [
        "cti-2026.dump",
        "notes.txt",
        "cti-20260927T010005Z.dump.sha256",
        "cti-20260927T010005Z.dump.partial",
        "x-20260927T010005Z.dump",
    ],
)
def test_only_exact_backup_names_are_recognised(name: str) -> None:
    assert pb.parse_backup_time(name) is None


def test_old_backups_are_pruned_but_the_newest_keep_min_are_always_safe() -> None:
    names = [stamp(d) for d in (0.5, 3, 20, 40, 90)]

    assert pb.select_prunable(names, NOW, keep_days=14, keep_min=3) == [stamp(40), stamp(90)]
    # semua sudah lewat umur -> tetap sisakan 3 terbaru (backup yang mandek tak menghabiskan stok)
    assert pb.select_prunable(names, NOW, keep_days=1, keep_min=3) == [stamp(40), stamp(90)]
    assert pb.select_prunable([stamp(40), stamp(90)], NOW, keep_days=1, keep_min=3) == []


def test_prune_age_boundary_and_unrelated_files_are_left_alone() -> None:
    exactly = stamp(14)  # tepat batas: BUKAN lebih tua dari cutoff -> aman
    older = pb.backup_name(NOW - datetime.timedelta(days=14, seconds=1))
    names = ["catatan.txt", "cti-latest.dump", exactly, older, stamp(0), stamp(1), stamp(2)]

    assert pb.select_prunable(names, NOW, keep_days=14, keep_min=3) == [older]


def test_prune_order_does_not_depend_on_input_order() -> None:
    names = [stamp(d) for d in (90, 0.5, 40, 3, 20)]

    assert sorted(pb.select_prunable(names, NOW, keep_days=14, keep_min=3)) == sorted(
        [stamp(40), stamp(90)]
    )


# --- backup -------------------------------------------------------------------


def test_backup_writes_a_private_verified_dump_with_checksum(tmp_path: Path) -> None:
    ex = FakeExecutor()

    final = pb.backup(ex, TARGET, tmp_path / "bk", now=NOW, keep_days=14, keep_min=3)

    assert final.name == "cti-20260927T010000Z.dump" and final.read_bytes() == b"PGDMP-data"
    assert stat.S_IMODE(final.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "bk").stat().st_mode) == 0o700
    checksum = final.with_name(final.name + ".sha256")
    assert checksum.read_text().split()[0] == pb.sha256_file(final)
    assert not list((tmp_path / "bk").glob("*.partial"))
    dump_cmd = ex.calls[0]
    assert dump_cmd[: len(PREFIX)] == list(PREFIX)
    assert dump_cmd[len(PREFIX) :] == ["pg_dump", "-U", "cti", "-d", "cti", "-Fc", "--no-owner"]
    assert ex.tools() == ["pg_dump", "pg_restore"]  # dump lalu verifikasi TOC


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda ex: setattr(ex, "dump_rc", 1), "pg_dump gagal"),
        (lambda ex: setattr(ex, "dump_bytes", b""), "berkas kosong"),
        (lambda ex: setattr(ex, "toc_rc", 1), "bukan dump valid"),
        (lambda ex: setattr(ex, "toc_out", "; hanya komentar\n"), "bukan dump valid"),
    ],
)
def test_a_failed_or_corrupt_dump_never_leaves_a_backup_file_behind(
    tmp_path: Path, setup, message: str
) -> None:
    ex = FakeExecutor()
    setup(ex)

    with pytest.raises(pb.BackupError, match=message):
        pb.backup(ex, TARGET, tmp_path, now=NOW, keep_days=14, keep_min=3)

    assert list(tmp_path.iterdir()) == []  # tak ada .dump, .partial, maupun .sha256


def test_a_successful_backup_prunes_old_ones_but_a_failed_one_does_not(tmp_path: Path) -> None:
    for d in (20, 30, 40, 50):
        (tmp_path / stamp(d)).write_bytes(b"x")
        (tmp_path / (stamp(d) + ".sha256")).write_text("x")
    failing = FakeExecutor()
    failing.dump_rc = 1
    with pytest.raises(pb.BackupError):
        pb.backup(failing, TARGET, tmp_path, now=NOW, keep_days=14, keep_min=3)
    assert len(list(tmp_path.glob("*.dump"))) == 4  # backup gagal -> stok lama utuh

    pb.backup(FakeExecutor(), TARGET, tmp_path, now=NOW, keep_days=14, keep_min=3)

    left = sorted(p.name for p in tmp_path.glob("*.dump"))
    assert left == sorted([pb.backup_name(NOW), stamp(20), stamp(30)])  # keep_min=3 terbaru
    assert not (tmp_path / (stamp(50) + ".sha256")).exists()  # checksum ikut dibuang


def test_a_stale_partial_file_from_a_crashed_run_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "cti-20260927T010000Z.dump.partial").write_bytes(b"sisa run yang crash")

    final = pb.backup(FakeExecutor(), TARGET, tmp_path, now=NOW, keep_days=14, keep_min=3)

    assert final.read_bytes() == b"PGDMP-data" and not list(tmp_path.glob("*.partial"))


# --- checksum -----------------------------------------------------------------


def test_checksum_detects_a_tampered_dump_and_is_optional(tmp_path: Path) -> None:
    dump = pb.backup(FakeExecutor(), TARGET, tmp_path, now=NOW, keep_days=14, keep_min=3)
    pb.check_checksum(dump)  # utuh -> lolos

    dump.write_bytes(b"rusak di jalan")
    with pytest.raises(pb.BackupError, match="checksum sha256 TIDAK cocok"):
        pb.check_checksum(dump)

    dump.with_name(dump.name + ".sha256").unlink()
    pb.check_checksum(dump)  # tanpa berkas checksum -> tidak diperiksa


# --- restore ------------------------------------------------------------------


def dump_file(tmp_path: Path) -> Path:
    path = tmp_path / stamp(0)
    path.write_bytes(b"PGDMP-data")
    return path


def test_restore_refuses_the_live_database_unless_explicitly_forced(tmp_path: Path) -> None:
    ex = FakeExecutor()

    with pytest.raises(pb.BackupError, match="MENOLAK restore ke DB live"):
        pb.restore(ex, TARGET, dump_file(tmp_path), "cti")

    assert ex.calls == []  # tidak menyentuh apa pun
    pb.restore(ex, TARGET, dump_file(tmp_path), "cti", force_live=True, replace=True)
    assert "pg_restore" in ex.tools()


def test_restore_creates_a_missing_database_and_restores_into_it(tmp_path: Path) -> None:
    ex = FakeExecutor()

    pb.restore(ex, TARGET, dump_file(tmp_path), "cti_test")

    assert "cti_test" in ex.databases
    restore_cmd = next(c for c in ex.calls if c[len(PREFIX)] == "pg_restore" and "--list" not in c)
    assert restore_cmd[len(PREFIX) :] == [
        "pg_restore",
        "-U",
        "cti",
        "-d",
        "cti_test",
        "--no-owner",
        "--exit-on-error",
    ]


def test_restore_refuses_a_database_that_already_has_tables_unless_replace(tmp_path: Path) -> None:
    ex = FakeExecutor()
    ex.databases["cti_test"] = 7

    with pytest.raises(pb.BackupError, match="sudah berisi"):
        pb.restore(ex, TARGET, dump_file(tmp_path), "cti_test")
    assert ex.databases["cti_test"] == 7 and "pg_restore" not in ex.tools()[3:]

    ex.calls.clear()
    pb.restore(ex, TARGET, dump_file(tmp_path), "cti_test", replace=True)

    ddl = [c[-1] for c in ex.calls if pb_tool(c) == "psql" and c[-1].startswith(("DROP", "CREATE"))]
    assert ddl == ['DROP DATABASE "cti_test" WITH (FORCE)', 'CREATE DATABASE "cti_test"']
    assert ex.databases["cti_test"] == 5  # dibuat ulang dan diisi hasil restore


def test_an_empty_existing_database_is_reused_without_replace(tmp_path: Path) -> None:
    ex = FakeExecutor()
    ex.databases["cti_test"] = 0

    pb.restore(ex, TARGET, dump_file(tmp_path), "cti_test")

    assert ex.databases["cti_test"] == 5


def test_restore_verifies_the_dump_before_touching_any_database(tmp_path: Path) -> None:
    ex = FakeExecutor()
    dump = pb.backup(ex, TARGET, tmp_path, now=NOW, keep_days=14, keep_min=3)
    dump.write_bytes(b"rusak")
    ex.calls.clear()

    with pytest.raises(pb.BackupError, match="checksum"):
        pb.restore(ex, TARGET, dump, "cti_test")

    assert ex.calls == []


def test_a_failing_pg_restore_is_reported(tmp_path: Path) -> None:
    ex = FakeExecutor()
    ex.restore_rc = 1

    with pytest.raises(pb.BackupError, match="pg_restore gagal"):
        pb.restore(ex, TARGET, dump_file(tmp_path), "cti_test")


def test_key_tables_include_indicators() -> None:
    assert "indicators" in pb.KEY_TABLES


# --- verify -------------------------------------------------------------------


def seed_counts(ex: FakeExecutor, live: int, restored: int) -> None:
    for table in pb.KEY_TABLES:
        ex.counts[("cti", table)] = live
        ex.counts[(pb.SCRATCH_DB, table)] = restored


def test_verify_compares_live_and_restored_then_drops_the_scratch_database(tmp_path: Path) -> None:
    ex = FakeExecutor()
    seed_counts(ex, live=120, restored=118)  # live sempat bertambah sesudah backup: wajar

    report = pb.verify(ex, TARGET, dump_file(tmp_path))

    assert report.problems() == []
    assert report.counts["articles"] == (120, 118)
    assert pb.SCRATCH_DB not in ex.databases


def test_verify_flags_an_empty_or_inflated_or_missing_restore() -> None:
    ok = pb.VerifyReport("r1", "r1", {"a": (10, 10), "b": (None, None)})
    assert ok.problems() == []

    bad = pb.VerifyReport("r2", "r1", {"empty": (10, 0), "inflated": (5, 9), "gone": (3, None)})
    text = " | ".join(bad.problems())
    assert "alembic_version beda" in text and "KOSONG" in text
    assert "LEBIH BANYAK" in text and "TIDAK ada di hasil restore" in text
    assert (
        pb.VerifyReport("r1", "r1", {"new": (None, 4)}).problems() == []
    )  # tabel baru di dump: tak masalah


def test_verify_drops_the_scratch_database_even_when_the_comparison_blows_up(
    tmp_path: Path,
) -> None:
    ex = FakeExecutor()
    seed_counts(ex, live=1, restored=1)
    ex.fail_count_query = True

    with pytest.raises(pb.BackupError, match="kaboom"):
        pb.verify(ex, TARGET, dump_file(tmp_path))

    assert pb.SCRATCH_DB not in ex.databases


def test_verify_replaces_a_scratch_database_left_over_from_a_previous_run(tmp_path: Path) -> None:
    ex = FakeExecutor()
    ex.databases[pb.SCRATCH_DB] = 9
    seed_counts(ex, live=1, restored=1)

    pb.verify(ex, TARGET, dump_file(tmp_path))

    assert pb.SCRATCH_DB not in ex.databases


# --- CLI ----------------------------------------------------------------------


def test_cli_backup_succeeds_and_passes_the_pg_exec_prefix_through(tmp_path: Path, capsys) -> None:
    ex = FakeExecutor()
    pg_exec = "docker compose -p x --env-file e.env exec -T postgres"
    rc = pb.main(
        ["--pg-exec", pg_exec, "--user", "u", "--db", "d", "backup", "--dir", str(tmp_path)],
        executor=ex,
    )
    # prefix di FakeExecutor tetap PREFIX untuk indeks alat -> cek langsung pemisahannya
    assert rc == 0 and "OK backup" in capsys.readouterr().out
    assert ex.calls[0][:9] == [
        "docker",
        "compose",
        "-p",
        "x",
        "--env-file",
        "e.env",
        "exec",
        "-T",
        "postgres",
    ]
    assert ex.calls[0][9:] == ["pg_dump", "-U", "u", "-d", "d", "-Fc", "--no-owner"]


def test_cli_failure_exits_1_and_runs_the_alarm_command_with_the_reason(tmp_path: Path) -> None:
    ex = FakeExecutor()
    ex.dump_rc = 1
    marker = tmp_path / "alarm.txt"

    rc = pb.main(
        [
            "backup",
            "--dir",
            str(tmp_path / "bk"),
            "--on-failure-cmd",
            f'echo "$BACKUP_ERROR" > {marker}',
        ],
        executor=ex,
    )

    assert rc == 1 and "pg_dump gagal" in marker.read_text()


def test_cli_verify_exits_1_when_the_restored_data_is_inconsistent(tmp_path: Path) -> None:
    ex = FakeExecutor()
    seed_counts(ex, live=10, restored=0)

    rc = pb.main(["verify", "--file", str(dump_file(tmp_path))], executor=ex)

    assert rc == 1


def test_cli_disk_errors_also_exit_1_and_trigger_the_alarm(tmp_path: Path) -> None:
    blocker = tmp_path / "bukan-direktori"
    blocker.write_text("x")  # `--dir` menunjuk ke berkas biasa -> mkdir gagal
    marker = tmp_path / "alarm.txt"

    rc = pb.main(
        ["backup", "--dir", str(blocker / "sub"), "--on-failure-cmd", f"echo gagal > {marker}"],
        executor=FakeExecutor(),
    )

    assert rc == 1 and marker.read_text().strip() == "gagal"


def test_cli_prune_only_removes_old_backups(tmp_path: Path, capsys) -> None:
    for d in (1, 2, 3, 40, 50):
        (tmp_path / stamp(d)).write_bytes(b"x")

    rc = pb.main(
        ["prune", "--dir", str(tmp_path), "--keep-days", "14", "--keep-min", "3"],
        executor=FakeExecutor(),
    )

    assert rc == 0 and "2 berkas dibuang" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([stamp(1), stamp(2), stamp(3)])


def test_pg_exec_can_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_EXEC", "ssh host docker exec -i pg")
    seen: list[pb.Target] = []
    monkeypatch.setattr(pb, "backup", lambda ex, target, *a, **k: seen.append(target) or Path("/x"))
    monkeypatch.setattr(Path, "stat", lambda self, **k: os.stat_result((0,) * 10))

    pb.main(["backup", "--dir", "/tmp/whatever"], executor=FakeExecutor())

    assert seen[0].pg_exec == ("ssh", "host", "docker", "exec", "-i", "pg")
