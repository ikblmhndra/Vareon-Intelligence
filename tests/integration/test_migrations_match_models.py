"""Skema hasil `alembic upgrade head` harus sama dengan model SQLAlchemy.

Latar: migrasi Fase 10.E ditulis tangan (autogenerate butuh DB hidup). Tanpa
test ini, kolom/constraint yang lupa masuk migrasi baru ketahuan di produksi --
model bilang ada, tabelnya enggak. `compare_metadata` = mesin yang sama dengan
`alembic revision --autogenerate`; diff kosong = migrasi lengkap.

Diukur 2026-09-26: SELURUH skema (bukan cuma tabel baru) sudah nol drift, jadi
guard ini berlaku untuk semua tabel dan migrasi berikutnya.
"""

from __future__ import annotations

from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from cti_core.db.base import Base
from cti_core.db.engine import get_sync_engine


def _include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """P7c-1 (Ruling 2): kelas tautan lama sementara dipetakan ke VIEW kompatibilitas
    (`info={"compat_view": True}`), dan tabel aslinya kini `_legacy_*` tanpa model. Keduanya di
    luar perbandingan sampai Task 12 menghapus kelas lama (dan filter ini)."""
    table = obj if type_ == "table" else getattr(obj, "table", None)
    if table is not None and table.info.get("compat_view"):
        return False
    table_name = name if type_ == "table" else getattr(table, "name", "")
    return not (table_name or "").startswith("_legacy_")


@pytest.mark.usefixtures("_migrated_schema")
def test_migrations_produce_exactly_the_schema_the_models_declare() -> None:
    import cti_core.db.models  # noqa: F401  -- daftarkan semua model ke metadata

    with get_sync_engine().connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "include_object": _include_object}
        )
        drift = compare_metadata(ctx, Base.metadata)

    assert drift == []
