"""Perintah `cti-sigma` (argparse, gaya `cti-entity`).

`cti-sigma import ZIP --release TAG`: ganti isi `sigma_rules` dengan zip rilis SigmaHQ
(`sigma_all_rules.zip`). Guard `load_sigma_zip` (minimum aturan, batas penyusutan) tetap berlaku;
satu transaksi, commit di akhir.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cti_core.db.engine import sync_session
from cti_core.hunt.sigma import SigmaLoadError, load_sigma_zip

_RELEASE_URL = "https://github.com/SigmaHQ/sigma/releases/download/{tag}/sigma_all_rules.zip"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cti-sigma", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    i = sub.add_parser("import", help="muat zip rilis SigmaHQ ke sigma_rules")
    i.add_argument("zip", type=Path, help="path sigma_all_rules.zip")
    i.add_argument("--release", required=True, help="tag rilis, mis. r2026-07-01")
    args = ap.parse_args(argv)
    data = args.zip.read_bytes()
    try:
        with sync_session() as session:
            url = _RELEASE_URL.format(tag=args.release)
            result = load_sigma_zip(session, data, release=args.release, source_url=url)
    except SigmaLoadError as e:
        print(f"DITOLAK: {e}", file=sys.stderr)
        return 1
    print(
        f"== sigma {result.release}: {result.rules} aturan, {result.skipped} dilewati,"
        f" sha256 {result.sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
