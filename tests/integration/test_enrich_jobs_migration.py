"""Migrasi P7g memindahkan `rejected_articles` gagal-enrich ke `enrich_jobs`.

Skema test dipakai bersama satu package (`_migrated_schema`): test ini men-downgrade lalu WAJIB
upgrade balik ke head di `finally`, supaya test berikutnya tidak melihat skema yang mundur.
"""

from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

PREV = "1387fae00908"


def _cfg() -> Config:
    root = pathlib.Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def test_migration_moves_failed_rows(_migrated_schema: None, postgres_url: str) -> None:
    cfg = _cfg()
    engine = sa.create_engine(postgres_url)
    try:
        command.downgrade(cfg, PREV)
        kinds = ["transient", "config", "json", "permanent", None]
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM rejected_articles"))
            for i, kind in enumerate(kinds):
                conn.execute(
                    sa.text(
                        "INSERT INTO rejected_articles (url, url_hash, title, source, reason,"
                        " failure_kind, raw_enrichment) VALUES (:u, :h, 't', 's', :r, :k, '{}')"
                    ),
                    {"u": f"https://e.com/{i}", "h": f"h{i}", "r": f"reason-{kind}", "k": kind},
                )
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            jobs = conn.execute(
                sa.text(
                    "SELECT url_hash, kind, state, last_error, input_text FROM enrich_jobs"
                    " ORDER BY url_hash"
                )
            ).all()
            left = conn.execute(sa.text("SELECT url_hash FROM rejected_articles")).scalars().all()
        assert [(j.url_hash, j.kind, j.state) for j in jobs] == [
            ("h0", "classify", "pending"),
            ("h1", "classify", "pending"),
            ("h2", "classify", "pending"),
            ("h3", "classify", "failed"),
        ]
        assert jobs[3].last_error == "reason-permanent"
        assert all(j.input_text is None for j in jobs)
        assert left == ["h4"]
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM enrich_jobs"))
            conn.execute(sa.text("DELETE FROM rejected_articles"))
        engine.dispose()
