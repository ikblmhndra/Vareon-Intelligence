"""Bangkitkan blok tabel referensi (sektor, label industri, negara ISO) di
`alembic/versions/entity_model_sql/backfill.sql` dari konstanta `cti_core.entity`.

SQL inti tidak punya uuid5, jadi `stix_id` sektor/negara (nama yang sudah diketahui saat
generate) dihitung di sini dengan `entity_stix_id()` dan ditulis sebagai literal. Output urut
supaya deterministik; `tests/unit/test_entity_sql_generated.py` memastikan file ter-commit sama.

    uv run python tools/dev/gen_entity_sql.py
"""

from __future__ import annotations

import pathlib

from cti_core.entity import entity_stix_id
from cti_core.entity.countries import ISO_COUNTRY_NAMES
from cti_core.entity.sectors import _LABEL_TO_SECTOR, SECTORS

BACKFILL = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "entity_model_sql"
    / "backfill.sql"
)
BEGIN = "-- BEGIN GENERATED (tools/dev/gen_entity_sql.py)\n"
END = "-- END GENERATED\n"


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _values(rows: list[tuple[str, ...]]) -> str:
    return ",\n".join("    (" + ", ".join(_q(v) for v in row) + ")" for row in rows) + ";\n"


def render() -> str:
    sectors = [(k, v, entity_stix_id("identity", v)) for k, v in sorted(SECTORS.items())]
    labels = sorted((label, sec) for label, sec in _LABEL_TO_SECTOR.items() if sec is not None)
    countries = [
        (k, v, entity_stix_id("location", v)) for k, v in sorted(ISO_COUNTRY_NAMES.items())
    ]
    return (
        BEGIN
        + "CREATE TEMP TABLE _bf_sectors (external_id text, name text, stix_id text);\n"
        + "INSERT INTO _bf_sectors VALUES\n"
        + _values(sectors)
        + "CREATE TEMP TABLE _bf_sector_labels (label text, external_id text);\n"
        + "INSERT INTO _bf_sector_labels VALUES\n"
        + _values(labels)
        + "CREATE TEMP TABLE _bf_countries (code text, name text, stix_id text);\n"
        + "INSERT INTO _bf_countries VALUES\n"
        + _values(countries)
        + END
    )


def splice(text: str) -> str:
    """Ganti blok di antara penanda dengan hasil `render()`."""
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return head + render() + tail


if __name__ == "__main__":
    BACKFILL.write_text(splice(BACKFILL.read_text()))
