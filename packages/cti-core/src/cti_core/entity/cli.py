"""Perintah `cti-entity` (argparse, Ruling 18).

`cti-entity merge-aliases [--dry-run | --apply] [--csv PATH] [--snapshot-dir DIR]`: merge alias
entitas dari MISP Galaxy (spec 4.2). Default `--dry-run`: hanya membaca dan mencetak rencana
(merge, alias baru, skip) sebagai CSV; runbook meminta CSV itu ditinjau sebelum `--apply`.

`--apply` berjalan dalam SATU transaksi untuk seluruh run (commit di akhir). Merge yang ditolak
`EntityMergeError` dicatat sebagai skip `error` dan run lanjut (SAVEPOINT per merge; deadlock dicoba
ulang sekali); error DB lain menggagalkan dan me-rollback seluruh run, jadi tidak ada yang tertulis
dan runbook cukup meminta perintah dijalankan ulang.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TextIO

from cti_core.db.engine import sync_session
from cti_core.entity.galaxy import (
    CSV_COLUMNS,
    GalaxyPlan,
    PlannedSkip,
    apply_plan,
    galaxy_sources,
    load_galaxy,
    plan_merges,
)


def plan_rows(plan: GalaxyPlan, errors: Iterable[PlannedSkip] = ()) -> Iterator[list[str]]:
    """Baris CSV (`CSV_COLUMNS`): `merge`, `alias`, `skip`."""
    for m in plan.merges:
        yield ["merge", m.cluster, m.source_name, m.target_name, ";".join(m.aliases), ""]
    for a in plan.new_aliases:
        yield ["alias", a.cluster, "", a.target_name, a.alias, ""]
    for s in (*plan.skips, *errors):
        yield ["skip", s.cluster, s.entity_name, s.target_name, s.alias, s.reason]


def _write_csv(out: TextIO, plan: GalaxyPlan, errors: Iterable[PlannedSkip]) -> None:
    w = csv.writer(out, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    w.writerows(plan_rows(plan, errors))


def merge_aliases(apply: bool, csv_path: Path | None, snapshot_dir: Path | None) -> int:
    with sync_session() as session:
        sources = galaxy_sources(session, snapshot_dir)
        clusters = [c for name, content in sources.items() for c in load_galaxy(name, content)]
        plan = plan_merges(session, clusters)
        errors: list[PlannedSkip] = []
        if apply:
            result = apply_plan(session, plan)
            errors = result.errors
            summary = (
                f"DITULIS: {result.merged} merge, {result.aliases_added} alias baru,"
                f" {len(errors)} error"
            )
        else:
            summary = (
                f"DRY-RUN: {len(plan.merges)} merge, {len(plan.new_aliases)} alias baru,"
                f" {len(plan.skips)} skip direncanakan"
            )
    if csv_path is None:
        _write_csv(sys.stdout, plan, errors)
    else:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            _write_csv(f, plan, errors)
    print(f"== merge-aliases ({len(clusters)} cluster) -- {summary}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cti-entity", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    m = sub.add_parser("merge-aliases", help="merge alias entitas dari snapshot MISP Galaxy")
    mode = m.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="hanya rencana (default)")
    mode.add_argument(
        "--apply",
        action="store_true",
        help="jalankan merge dan tambah alias (satu transaksi; error DB lain = rollback, ulangi)",
    )
    m.add_argument("--csv", type=Path, help="tulis rencana ke file CSV (default: stdout)")
    m.add_argument(
        "--snapshot-dir",
        type=Path,
        help="folder snapshot Galaxy pengganti snapshot bawaan paket (kalau tak ada salinan di DB)",
    )
    args = ap.parse_args(argv)
    return merge_aliases(args.apply, args.csv, args.snapshot_dir)


if __name__ == "__main__":
    raise SystemExit(main())
