"""`iocs` -> `indicators`: ganti nama tabel, kolom FK, sequence, constraint, dan index (P7a)

Murni rename, tanpa perubahan perilaku: id dan baris tetap sama (rename tabel tidak menyentuh data,
dan sequence ikut di-rename sehingga INSERT berikutnya melanjutkan id yang sama). Kolom FK
`ioc_id` di empat tabel anak menjadi `indicator_id`.

Nama lama tetap hidup sebagai VIEW kompatibilitas (`iocs`, `ioc_sources`, `ioc_tags`,
`ioc_threat_actors`, `ioc_feedback`) supaya konsumen luar yang membaca langsung dari DB (Splunk,
dasbor ad hoc) tidak patah saat deploy. View sederhana ini juga bisa ditulisi, tetapi statusnya
read-only secara kontrak dan akan dihapus di rilis berikutnya (lihat COMMENT pada tiap view).
Pembuatan view sengaja di blok terpisah di AKHIR `upgrade()` dan penghapusannya di AWAL
`downgrade()`: view bergantung pada tabel, jadi harus dibuat terakhir dan dibuang pertama (dan
kolom baru di migrasi yang sama harus ditambahkan SEBELUM blok view).

Revision ID: a9e4c7b1d3f6
Revises: d7a3e1b94c52
Create Date: 2026-10-29 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a9e4c7b1d3f6"
down_revision: str | Sequence[str] | None = "d7a3e1b94c52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (nama lama, nama baru) untuk tabel; sequence `<tabel>_id_seq` mengikuti.
_TABLES = (
    ("iocs", "indicators"),
    ("ioc_sources", "indicator_sources"),
    ("ioc_tags", "indicator_tags"),
    ("ioc_threat_actors", "indicator_threat_actors"),
    ("ioc_feedback", "indicator_feedback"),
)
# (tabel LAMA, nama lama, nama baru) untuk constraint; PK/unique sekaligus me-rename index-nya.
_CONSTRAINTS = (
    ("iocs", "pk_iocs", "pk_indicators"),
    ("iocs", "uq_iocs_type_value", "uq_indicators_type_value"),
    ("ioc_sources", "pk_ioc_sources", "pk_indicator_sources"),
    ("ioc_sources", "fk_ioc_sources_ioc_id_iocs", "fk_indicator_sources_indicator_id_indicators"),
    (
        "ioc_sources",
        "fk_ioc_sources_article_id_articles",
        "fk_indicator_sources_article_id_articles",
    ),
    ("ioc_tags", "pk_ioc_tags", "pk_indicator_tags"),
    ("ioc_tags", "uq_ioc_tag", "uq_indicator_tag"),
    ("ioc_tags", "fk_ioc_tags_ioc_id_iocs", "fk_indicator_tags_indicator_id_indicators"),
    ("ioc_threat_actors", "pk_ioc_threat_actors", "pk_indicator_threat_actors"),
    ("ioc_threat_actors", "uq_ioc_threat_actor", "uq_indicator_threat_actor"),
    (
        "ioc_threat_actors",
        "fk_ioc_threat_actors_ioc_id_iocs",
        "fk_indicator_threat_actors_indicator_id_indicators",
    ),
    ("ioc_feedback", "pk_ioc_feedback", "pk_indicator_feedback"),
    (
        "ioc_feedback",
        "fk_ioc_feedback_ioc_id_iocs",
        "fk_indicator_feedback_indicator_id_indicators",
    ),
)
# Index non-constraint.
_INDEXES = (
    ("ix_iocs_type", "ix_indicators_type"),
    ("ix_ioc_tags_tag", "ix_indicator_tags_tag"),
    ("ix_ioc_threat_actors_threat_actor", "ix_indicator_threat_actors_threat_actor"),
)
_CHILDREN = ("ioc_sources", "ioc_tags", "ioc_threat_actors", "ioc_feedback")
# Kolom view anak (selain `id` dan FK), urut seperti tabelnya.
_VIEW_COLUMNS = {
    "ioc_sources": "article_id, url, source_name, context, first_seen_at",
    "ioc_tags": "tag",
    "ioc_threat_actors": "threat_actor",
    "ioc_feedback": "verdict, submitted_by, note, submitted_at",
}
_VIEW_COMMENT = "deprecated since 0.8.11: read-only compatibility view, use indicator_*"


def _new_name(old: str) -> str:
    return dict(_TABLES)[old]


def upgrade() -> None:
    for old, new in _TABLES:
        op.rename_table(old, new)
        op.execute(f"ALTER SEQUENCE {old}_id_seq RENAME TO {new}_id_seq")
    for child in _CHILDREN:
        op.alter_column(_new_name(child), "ioc_id", new_column_name="indicator_id")
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {_new_name(table)} RENAME CONSTRAINT {old} TO {new}")
    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")

    # --- View kompatibilitas: SELALU terakhir (kolom baru ditambahkan sebelum blok ini) ---
    op.execute("CREATE VIEW iocs AS SELECT * FROM indicators")
    op.execute(f"COMMENT ON VIEW iocs IS '{_VIEW_COMMENT}'")
    for child in _CHILDREN:
        op.execute(
            f"CREATE VIEW {child} AS SELECT id, indicator_id AS ioc_id, {_VIEW_COLUMNS[child]} "
            f"FROM {_new_name(child)}"
        )
        op.execute(f"COMMENT ON VIEW {child} IS '{_VIEW_COMMENT}'")


def downgrade() -> None:
    # --- View dibuang PERTAMA: nama lamanya dibutuhkan lagi oleh tabel ---
    for child in _CHILDREN:
        op.execute(f"DROP VIEW {child}")
    op.execute("DROP VIEW iocs")

    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {_new_name(table)} RENAME CONSTRAINT {new} TO {old}")
    for child in _CHILDREN:
        op.alter_column(_new_name(child), "indicator_id", new_column_name="ioc_id")
    for old, new in _TABLES:
        op.execute(f"ALTER SEQUENCE {new}_id_seq RENAME TO {old}_id_seq")
        op.rename_table(new, old)
