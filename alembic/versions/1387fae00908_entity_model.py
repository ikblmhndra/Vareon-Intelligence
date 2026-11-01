"""Model entitas (P7c-1): tabel `entities`, `entity_aliases`, `relationships`, `entity_mentions`,
`entity_watches`, `entity_profiles`, `reference_snapshots` dan jam feed `stories.feed_changed_at`.

File ini dibangun bertahap oleh beberapa task P7c-1; tiap task menambah seksi sendiri di
`upgrade()`/`downgrade()` (urutan downgrade kebalikan). Seksi 1 = DDL tabel.

`entity_aliases.entity_type` didenormalisasi dari `entities.type` oleh TRIGGER (nilai kiriman
ditimpa), supaya unik `(entity_type, alias_norm)` tak bisa dilewati SQL mentah. Jam feed memakai
`clock_timestamp()`, bukan `now()`, dengan alasan yang sama seperti migrasi `machine_api`.

Revision ID: 1387fae00908
Revises: c4f1a8d27b93
Create Date: 2026-10-30 09:00:00.000000

"""

import pathlib
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "1387fae00908"
down_revision: str | Sequence[str] | None = "c4f1a8d27b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TLP = "('clear', 'green', 'amber', 'amber+strict', 'red')"
_FEED_DEFAULT = sa.text("clock_timestamp()")


def _ts(name: str, *, default: sa.TextClause | None = None, null: bool = True) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=default, nullable=null and default is None
    )


def _create_tables() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("stix_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(50), nullable=True),
        sa.Column("identity_class", sa.String(20), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("suppressed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("merged_into_id", sa.BigInteger(), nullable=True),
        _ts("first_seen"),
        _ts("last_seen"),
        sa.Column("tlp", sa.String(12), server_default="clear", nullable=False),
        _ts("created_at", default=sa.text("now()")),
        _ts("updated_at", default=sa.text("now()")),
        _ts("feed_changed_at", default=_FEED_DEFAULT),
        sa.CheckConstraint(
            "type IN ('intrusion-set', 'malware', 'tool', 'attack-pattern', 'vulnerability',"
            " 'campaign', 'identity', 'location')",
            name=op.f("ck_entities_type"),
        ),
        sa.CheckConstraint(
            "source IN ('attack', 'galaxy', 'dictionary', 'analyst', 'cve', 'iso', 'sector',"
            " 'ransomware', 'legacy')",
            name=op.f("ck_entities_source"),
        ),
        sa.CheckConstraint(f"tlp IN {_TLP}", name=op.f("ck_entities_tlp")),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["entities.id"], name=op.f("fk_entities_merged_into_id_entities")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
        sa.UniqueConstraint("stix_id", name=op.f("uq_entities_stix_id")),
    )
    op.create_index(
        "uq_entities_type_lower_name",
        "entities",
        ["type", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("merged_into_id IS NULL AND type <> 'attack-pattern'"),
    )
    # identitas teknik = id teknik (nama ATT&CK tidak unik: sub-teknik, lintas domain)
    op.create_index(
        "uq_entities_type_external_id",
        "entities",
        ["type", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL AND merged_into_id IS NULL"),
    )
    op.create_index("ix_entities_feed_changed_at_id", "entities", ["feed_changed_at", "id"])

    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("alias", sa.String(300), nullable=False),
        sa.Column("alias_norm", sa.String(300), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        _ts("created_at", default=sa.text("now()")),
        sa.CheckConstraint(
            "source IN ('attack', 'galaxy', 'analyst', 'legacy', 'dictionary')",
            name=op.f("ck_entity_aliases_source"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_aliases_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_aliases")),
        sa.UniqueConstraint("entity_type", "alias_norm", name="uq_entity_aliases_type_norm"),
    )
    op.create_index("ix_entity_aliases_entity_id", "entity_aliases", ["entity_id"])
    op.execute(
        """
        CREATE FUNCTION entity_aliases_sync_type() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            SELECT type INTO NEW.entity_type FROM entities WHERE id = NEW.entity_id;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_entity_aliases_sync_type BEFORE INSERT OR UPDATE ON entity_aliases"
        " FOR EACH ROW EXECUTE FUNCTION entity_aliases_sync_type()"
    )
    # Sisi sebaliknya: tipe entitas berubah -> salinan tipe di alias ikut (aturan unik per tipe
    # tetap berlaku; bentrok alias di tipe baru gagal di sini, bukan diam-diam).
    op.execute(
        """
        CREATE FUNCTION entities_sync_alias_type() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE entity_aliases SET entity_type = NEW.type WHERE entity_id = NEW.id;
            RETURN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_entities_sync_alias_type AFTER UPDATE OF type ON entities"
        " FOR EACH ROW WHEN (OLD.type IS DISTINCT FROM NEW.type)"
        " EXECUTE FUNCTION entities_sync_alias_type()"
    )

    op.create_table(
        "relationships",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stix_id", sa.String(100), nullable=False),
        sa.Column("relationship_type", sa.String(30), nullable=False),
        sa.Column("source_entity_id", sa.BigInteger(), nullable=True),
        sa.Column("source_indicator_id", sa.BigInteger(), nullable=True),
        sa.Column("target_entity_id", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.SmallInteger(), nullable=True),
        _ts("first_seen"),
        _ts("last_seen"),
        sa.Column("provenance", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=True),
        _ts("revoked_at"),
        sa.Column("revoked_by", sa.String(200), nullable=True),
        sa.Column("tlp", sa.String(12), server_default="clear", nullable=False),
        _ts("created_at", default=sa.text("now()")),
        _ts("updated_at", default=sa.text("now()")),
        _ts("feed_changed_at", default=_FEED_DEFAULT),
        sa.CheckConstraint(
            "relationship_type IN ('uses', 'targets', 'attributed-to', 'exploits', 'indicates',"
            " 'variant-of', 'located-at', 'related-to', 'subtechnique-of')",
            name=op.f("ck_relationships_relationship_type"),
        ),
        sa.CheckConstraint(
            "provenance IN ('attack', 'analyst', 'ransomware')",
            name=op.f("ck_relationships_provenance"),
        ),
        sa.CheckConstraint(f"tlp IN {_TLP}", name=op.f("ck_relationships_tlp")),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100", name=op.f("ck_relationships_confidence")
        ),
        sa.CheckConstraint(
            "num_nonnulls(source_entity_id, source_indicator_id) = 1",
            name=op.f("ck_relationships_source"),
        ),
        sa.ForeignKeyConstraint(
            ["source_entity_id"],
            ["entities.id"],
            name=op.f("fk_relationships_source_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_indicator_id"],
            ["indicators.id"],
            name=op.f("fk_relationships_source_indicator_id_indicators"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"],
            ["entities.id"],
            name=op.f("fk_relationships_target_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relationships")),
        sa.UniqueConstraint("stix_id", name=op.f("uq_relationships_stix_id")),
    )
    op.create_index(
        "uq_relationships_edge",
        "relationships",
        [
            sa.text("coalesce(source_entity_id, 0)"),
            sa.text("coalesce(source_indicator_id, 0)"),
            "relationship_type",
            "target_entity_id",
        ],
        unique=True,
    )
    op.create_index("ix_relationships_source_entity_id", "relationships", ["source_entity_id"])
    op.create_index("ix_relationships_target_entity_id", "relationships", ["target_entity_id"])
    # FK ON DELETE CASCADE dari indicators: tanpa indeks, hapus indikator memindai relationships
    op.create_index(
        "ix_relationships_source_indicator_id", "relationships", ["source_indicator_id"]
    )
    op.create_index(
        "ix_relationships_feed_changed_at_id", "relationships", ["feed_changed_at", "id"]
    )

    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=True),
        sa.Column("indicator_id", sa.BigInteger(), nullable=True),
        sa.Column("cve_tracker_id", sa.BigInteger(), nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("method", sa.String(12), nullable=False),
        sa.Column("matched_alias", sa.String(300), nullable=False),
        sa.Column("role", sa.String(10), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("extracted", postgresql.JSONB(), nullable=True),
        _ts("created_at", default=sa.text("now()")),
        sa.CheckConstraint(
            "method IN ('dictionary', 'llm', 'keyword', 'explicit', 'analyst', 'legacy')",
            name=op.f("ck_entity_mentions_method"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(article_id, indicator_id, cve_tracker_id) = 1",
            name=op.f("ck_entity_mentions_subject"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_entity_mentions_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["indicator_id"],
            ["indicators.id"],
            name=op.f("fk_entity_mentions_indicator_id_indicators"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cve_tracker_id"],
            ["cve_tracker.id"],
            name=op.f("fk_entity_mentions_cve_tracker_id_cve_tracker"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], name=op.f("fk_entity_mentions_entity_id_entities")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_mentions")),
        sa.UniqueConstraint(
            "article_id",
            "indicator_id",
            "cve_tracker_id",
            "entity_id",
            "role",
            name="uq_entity_mentions_subject_entity_role",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_entity_mentions_entity_id_article_id", "entity_mentions", ["entity_id", "article_id"]
    )
    op.create_index("ix_entity_mentions_article_id", "entity_mentions", ["article_id"])
    op.create_index("ix_entity_mentions_indicator_id", "entity_mentions", ["indicator_id"])
    op.create_index("ix_entity_mentions_cve_tracker_id", "entity_mentions", ["cve_tracker_id"])

    op.create_table(
        "entity_watches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        _ts("created_at", default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.client_id"],
            name=op.f("fk_entity_watches_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_watches_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_watches")),
        sa.UniqueConstraint("client_id", "entity_id", name="uq_entity_watches_pair"),
    )

    op.create_table(
        "entity_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("profile", postgresql.JSONB(), nullable=True),
        _ts("generated_at", default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_profiles_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_profiles")),
        sa.UniqueConstraint("entity_id", name=op.f("uq_entity_profiles_entity_id")),
    )

    op.create_table(
        "reference_snapshots",
        sa.Column("name", sa.String(50), nullable=False),
        _ts("fetched_at", default=sa.text("now()")),
        sa.Column("sha256", postgresql.CHAR(64), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_reference_snapshots")),
    )

    # Dua kolom ber-default volatil dalam SATU ALTER TABLE: `stories` ditulis ulang sekali, bukan
    # dua kali. stix_id = id STIX report (Ruling 34), acak per story, terisi untuk baris lama oleh
    # default itu; lookup report per id jadi lookup berindeks.
    op.execute(
        "ALTER TABLE stories"
        " ADD COLUMN feed_changed_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,"
        " ADD COLUMN stix_id UUID DEFAULT gen_random_uuid() NOT NULL"
    )
    op.create_index("ix_stories_feed_changed_at_id", "stories", ["feed_changed_at", "id"])
    op.create_unique_constraint(op.f("uq_stories_stix_id"), "stories", ["stix_id"])


def _drop_tables() -> None:
    op.drop_constraint(op.f("uq_stories_stix_id"), "stories", type_="unique")
    op.drop_column("stories", "stix_id")
    op.drop_index("ix_stories_feed_changed_at_id", table_name="stories")
    op.drop_column("stories", "feed_changed_at")
    op.drop_table("reference_snapshots")
    op.drop_table("entity_profiles")
    op.drop_table("entity_watches")
    op.drop_table("entity_mentions")
    op.drop_table("relationships")
    op.execute("DROP TRIGGER trg_entities_sync_alias_type ON entities")
    op.execute("DROP FUNCTION entities_sync_alias_type()")
    op.execute("DROP TRIGGER trg_entity_aliases_sync_type ON entity_aliases")
    op.execute("DROP FUNCTION entity_aliases_sync_type()")
    op.drop_table("entity_aliases")
    op.drop_table("entities")


def _create_resolve() -> None:
    """Seksi 2: fungsi `entity_resolve` (kembaran SQL resolver Python)."""
    sql = pathlib.Path(__file__).parent / "entity_model_sql" / "resolve.sql"
    op.execute(sql.read_text())


def _backfill() -> None:
    """Seksi 3: isi entitas/alias/relasi/mention/watch/profil dari tabel lama (spec 3.2 langkah
    2-7). Tabel lama tidak diubah di sini; downgrade cukup membuang tabel baru (seksi 1)."""
    sql = pathlib.Path(__file__).parent / "entity_model_sql" / "backfill.sql"
    op.execute(sql.read_text())


# Tabel lama yang diganti view kompatibilitas (spec 3.6); urutan = urutan di compat_views.sql.
_COMPAT = (
    "article_threat_actors",
    "article_malware",
    "article_ttps",
    "article_cves",
    "article_countries",
    "article_industries",
    "indicator_threat_actors",
    "cve_threat_actors",
    "cve_ttps",
    "ta_watchlist",
    "ta_profiles",
    "ta_whitelist",
)
_COMPAT_HELPERS = (
    "entity_compat_extracted(text, text)",
    "entity_compat_repoint(bigint, bigint, text)",
    "entity_compat_mention(bigint, bigint, bigint, bigint, text, text, text, text, jsonb)",
    "entity_compat_country(text)",
    "entity_compat_sector(text)",
    "entity_compat_cve(text)",
    "entity_compat_technique(text, text)",
    "entity_compat_resolve(text, text)",
    "entity_compat_method(text, text)",
)
_IOC_VIEW_COMMENT = "deprecated since 0.8.11: read-only compatibility view, use indicator_*"


def _rename_compat(src: str, dst: str) -> None:
    """Rename tabel lama <-> `_legacy_*`; sekuens id ikut tabelnya (`article_cves` tanpa id)."""
    for t in _COMPAT:
        op.rename_table(src + t, dst + t)
        if t != "article_cves":
            op.execute(f"ALTER SEQUENCE {src}{t}_id_seq RENAME TO {dst}{t}_id_seq")


def _create_feed_triggers() -> None:
    """Jam feed entitas/relasi/story (spec 3.5); SESUDAH backfill supaya muatan massal tak bump."""
    sql = pathlib.Path(__file__).parent / "entity_model_sql" / "feed_triggers.sql"
    op.execute(sql.read_text())


_FEED_TRIGGERS = (
    ("entities", "entities_feed_propagate"),
    ("entity_mentions", "entity_mentions_feed_bump"),
    ("stories", "stories_feed_bump"),
    ("relationships", "relationships_feed_bump"),
    ("entity_aliases", "entity_aliases_feed_bump"),
    ("entities", "entities_feed_bump"),
)


def _drop_feed_triggers() -> None:
    # trigger level statement: satu per event (tabel transisi tak boleh multi-event)
    for event in ("ins", "del", "upd"):
        op.execute(f"DROP TRIGGER trg_indicator_sources_feed_bump_{event} ON indicator_sources")
    op.execute("DROP FUNCTION indicator_sources_feed_bump()")
    for table, fn in _FEED_TRIGGERS:
        op.execute(f"DROP TRIGGER trg_{fn} ON {table}")
        op.execute(f"DROP FUNCTION {fn}()")


def _create_compat_views() -> None:
    """Seksi 4: tabel lama -> `_legacy_<nama>` (disimpan sampai rilis sesudah 0.8.11 untuk audit
    dan undo manual), lalu view bernama lama + trigger INSTEAD OF supaya kode 0.8.2/0.8.10 yang
    di-rollback tetap jalan. View P7a `ioc_threat_actors` dipasang ulang di atas view baru."""
    op.execute("DROP VIEW ioc_threat_actors")
    _rename_compat("", "_legacy_")
    sql = pathlib.Path(__file__).parent / "entity_model_sql" / "compat_views.sql"
    op.execute(sql.read_text())


def _drop_compat_views() -> None:
    """Kebalikan seksi 4. Baris yang ditulis lewat view sesudah upgrade hilang (spec 3.2)."""
    op.execute("DROP VIEW ioc_threat_actors")
    for t in _COMPAT:
        op.execute(f"DROP VIEW {t}")
        op.execute(f"DROP FUNCTION {t}_compat()")
    for fn in _COMPAT_HELPERS:
        op.execute(f"DROP FUNCTION {fn}")
    _rename_compat("_legacy_", "")
    op.execute(
        "CREATE VIEW ioc_threat_actors AS SELECT id, indicator_id AS ioc_id, threat_actor"
        " FROM indicator_threat_actors"
    )
    op.execute(f"COMMENT ON VIEW ioc_threat_actors IS '{_IOC_VIEW_COMMENT}'")


# Tabel baru yang diisi backfill; ANALYZE di akhir upgrade supaya planner tidak menebak tabel
# kosong pada query pertama sesudah deploy (autovacuum baru menyusul belakangan).
_ANALYZE = (
    "entities",
    "entity_aliases",
    "relationships",
    "entity_mentions",
    "entity_watches",
    "entity_profiles",
    "stories",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    _create_tables()
    # Kunci EXCLUSIVE tabel lama SEBELUM backfill membacanya: kode 0.8.2 yang masih jalan selama
    # migrate tetap bisa membaca, tapi tulisannya menunggu sampai rename/view selesai, bukan masuk
    # ke tabel yang sudah selesai disalin (lalu hilang di `_legacy_*`). Sengaja SESUDAH
    # `_create_tables()`: FK `entity_mentions` mengunci articles/indicators/cve_tracker dulu, urutan
    # yang sama dengan worker lama (induk dulu, baru tabel link), jadi tidak ada siklus deadlock.
    # Bila lock_timeout habis (transaksi panjang di tabel itu), migrasi gagal utuh dan
    # `make deploy` cukup diulang.
    op.execute(f"LOCK TABLE {', '.join(_COMPAT)} IN EXCLUSIVE MODE")
    _create_resolve()
    _backfill()
    _create_compat_views()
    _create_feed_triggers()
    for table in _ANALYZE:
        op.execute(f"ANALYZE {table}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    _drop_feed_triggers()
    _drop_compat_views()
    op.execute("DROP FUNCTION entity_resolve_technique(text, text, text)")
    op.execute("DROP FUNCTION entity_resolve(text, text, text)")
    op.execute("DROP FUNCTION entity_resolve_lookup(text, text)")
    op.execute("DROP FUNCTION entity_alias_norm(text)")
    op.execute("DROP FUNCTION entity_collapse_ws(text)")
    _drop_tables()
