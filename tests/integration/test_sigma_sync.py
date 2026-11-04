"""`sync_sigma` pada Postgres nyata dengan fetcher palsu (tanpa jaringan)."""

from __future__ import annotations

import pytest
from cti_core.db.models import SigmaRule
from cti_core.db.models.entity import ReferenceSnapshot
from cti_core.hunt.sigma import load_sigma_zip
from sqlalchemy import delete, func, select

from tests.integration.test_sigma_load import _zip_n


@pytest.fixture(autouse=True)
def _empty_sigma_rules(db_session):
    # lifespan test lain bisa meng-commit snapshot bawaan; guard shrink butuh tabel kosong
    db_session.execute(delete(SigmaRule))


def sync_sigma(*a, **k):
    # import malas: modul task menyiapkan Celery app yang butuh Settings (belum ada saat collect)
    from cti_worker.tasks.sigma import sync_sigma as f

    return f(*a, **k)


ASSET_NAME = "sigma_all_rules.zip"


def _boom(url: str):
    raise AssertionError("tidak boleh mengunduh")


def test_sync_unchanged(db_session):
    load_sigma_zip(db_session, _zip_n(1200), release="r1", source_url="u")
    out = sync_sigma(db_session, lambda u: {"tag_name": "r1", "assets": []}, _boom)
    assert out == {"status": "unchanged", "release": "r1"}


def test_sync_loads_new_release(db_session):
    load_sigma_zip(db_session, _zip_n(1200), release="r1", source_url="u")
    rel = {"tag_name": "r2", "assets": [{"name": ASSET_NAME, "browser_download_url": "z"}]}
    out = sync_sigma(db_session, lambda u: rel, lambda u: _zip_n(1300))
    assert out == {"status": "loaded", "release": "r2", "rules": 1300}


def test_sync_failure_keeps_rows_and_records_error(db_session):
    load_sigma_zip(db_session, _zip_n(1200), release="r1", source_url="u")
    out = sync_sigma(db_session, lambda u: {"tag_name": "r2", "assets": []}, _boom)
    assert out["status"] == "failed"
    assert db_session.get(ReferenceSnapshot, "sigma").content["last_error"] == (
        f"ValueError: asset {ASSET_NAME} missing from release r2"
    )
    assert db_session.scalar(select(func.count()).select_from(SigmaRule)) == 1200


def test_sync_refused_zip_keeps_rows(db_session):
    load_sigma_zip(db_session, _zip_n(2000), release="r1", source_url="u")
    rel = {"tag_name": "r2", "assets": [{"name": ASSET_NAME, "browser_download_url": "z"}]}
    out = sync_sigma(db_session, lambda u: rel, lambda u: _zip_n(1500))
    assert out["status"] == "failed"
    assert db_session.scalar(select(func.count()).select_from(SigmaRule)) == 2000


def test_sync_unchanged_clears_stale_error(db_session):
    load_sigma_zip(db_session, _zip_n(1200), release="r1", source_url="u")
    sync_sigma(db_session, lambda u: {"tag_name": "r2", "assets": []}, _boom)
    assert db_session.get(ReferenceSnapshot, "sigma").content["last_error"]
    out = sync_sigma(db_session, lambda u: {"tag_name": "r1", "assets": []}, _boom)
    assert out == {"status": "unchanged", "release": "r1"}
    assert db_session.get(ReferenceSnapshot, "sigma").content["last_error"] is None


def test_sync_tolerates_malformed_snapshot(db_session):
    load_sigma_zip(db_session, _zip_n(1200), release="r1", source_url="u")
    db_session.get(ReferenceSnapshot, "sigma").content = ["x"]
    db_session.flush()
    rel = {"tag_name": "r2", "assets": [{"name": ASSET_NAME, "browser_download_url": "z"}]}
    out = sync_sigma(db_session, lambda u: rel, lambda u: _zip_n(1300))
    assert out == {"status": "loaded", "release": "r2", "rules": 1300}
