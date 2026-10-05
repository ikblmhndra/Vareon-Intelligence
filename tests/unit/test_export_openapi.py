"""Unit test `tools/export_openapi.py` -- Fase 7.7. `export_schema()`
murni introspeksi statis (gak nyentuh DB/Redis beneran, lihat docstring
modul), jadi ini test unit biasa -- gak butuh Postgres/testcontainers.
Lolosnya test ini DI CI (gak ada `.env` sama sekali di sana) juga yang
ngebuktiin `_ensure_placeholder_env()` beneran cukup buat `create_app()`
kebentuk tanpa secret asli."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

from export_openapi import export_schema


def test_export_schema_has_expected_shape() -> None:
    schema = export_schema()
    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "Vareon Intelligence API"
    assert "/healthz" in schema["paths"]
    assert len(schema["paths"]) > 100
    assert "schemas" in schema["components"]


def test_export_schema_is_json_serializable() -> None:
    schema = export_schema()
    json.dumps(schema)
