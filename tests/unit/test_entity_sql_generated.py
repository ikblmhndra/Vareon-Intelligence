"""Blok referensi di `backfill.sql` harus sama dengan hasil generator (konstanta entity)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "dev"))

import gen_entity_sql


def test_generated_sql_matches_constants() -> None:
    committed = gen_entity_sql.BACKFILL.read_text()
    assert gen_entity_sql.splice(committed) == committed, (
        "jalankan: uv run python tools/dev/gen_entity_sql.py"
    )
