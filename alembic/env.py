"""env.py Alembic -- URL DB dibaca dari cti_core.config, BUKAN dari
alembic.ini. Satu sumber config yang sama dipakai apps/api, apps/worker,
dan migrasi -- gak ada kredensial DB tersebar di file kedua.
"""

from __future__ import annotations

from logging.config import fileConfig

from cti_core.config import get_settings
from cti_core.db.base import Base

# Import semua model biar ke-daftar di Base.metadata sebelum autogenerate
# nge-diff -- kalau ini gak di-import, alembic ngira semua tabel model
# adalah "DROP TABLE" karena metadata-nya kosong.
from cti_core.db.models import (  # noqa: F401
    article,
    attack,
    auth,
    catalog,
    cve,
    cve_mirror,
    ioc,
    mindmap,
    newsletter,
    package,
    pir,
    ransomware,
    recap,
    rfi,
    scraper,
    source_reliability,
    ta,
    techstack,
    threat_reference,
    tweet,
)
from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database.sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql` -- generate SQL tanpa konek DB."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
