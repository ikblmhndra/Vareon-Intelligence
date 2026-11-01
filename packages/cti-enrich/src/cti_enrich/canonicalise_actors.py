"""DIGANTIKAN (P7c, Ruling 22): dulu menulis ulang nama aktor historis dari bentuk alias ke nama
kanonik ATT&CK (0.8.8). Sejak migrasi `entity_model` semua bentuk alias sudah resolve ke satu
entitas (alias di `entity_aliases`), dan duplikat yang tersisa digabung `cti-entity merge-aliases`.

Modul tetap ada dan tetap bisa dijalankan (`python -m cti_enrich.canonicalise_actors [--apply]`)
karena runbook upgrade prod satu lompatan 0.8.2 -> 0.8.11 masih menyebutnya: perintah ini tidak
menulis apa pun, mencetak bahwa ia digantikan, dan keluar 0, dengan atau tanpa `--apply`.
"""

from __future__ import annotations

import argparse

SUPERSEDED = (
    "canonicalise_actors digantikan: migrasi entity_model sudah menyatukan bentuk alias aktor "
    "(entity_aliases); jalankan `cti-entity merge-aliases` untuk duplikat yang tersisa. "
    "Tidak ada yang ditulis."
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="diabaikan (perintah ini digantikan)")
    ap.parse_args(argv)
    print(SUPERSEDED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
