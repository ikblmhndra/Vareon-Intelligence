"""`load_sigma_zip` pada Postgres nyata: ganti semua baris, guard minimum dan shrink 20 %."""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from cti_core.db.models import SigmaRule
from cti_core.db.models.entity import ReferenceSnapshot
from cti_core.hunt.sigma import SigmaLoadError, load_sigma_zip, record_sigma_error
from sqlalchemy import delete, func, select


def _zip_n(n: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(n):
            uid = uuid.UUID(int=i + 1)
            z.writestr(
                f"rules/windows/r{i}.yml",
                f"title: R{i}\nid: {uid}\nstatus: test\nlevel: high\n"
                "tags: [attack.t1059]\nlogsource:\n  product: windows\n",
            )
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _empty_sigma_rules(db_session):
    # lifespan/bootstrap test lain meng-commit snapshot bawaan; guard shrink butuh tabel kosong
    db_session.execute(delete(SigmaRule))


def _count(s) -> int:
    return s.scalar(select(func.count()).select_from(SigmaRule))


def test_load_replaces_rows(db_session):
    r = load_sigma_zip(db_session, _zip_n(1200), release="r1", source_url="u")
    assert r.rules == 1200
    assert _count(db_session) == 1200
    snap = db_session.get(ReferenceSnapshot, "sigma")
    assert snap.content["release"] == "r1" and snap.content["last_error"] is None


def test_load_refuses_below_minimum(db_session):
    with pytest.raises(SigmaLoadError):
        load_sigma_zip(db_session, _zip_n(999), release="r1", source_url="u")


def test_load_refuses_shrink_and_keeps_rows(db_session):
    load_sigma_zip(db_session, _zip_n(2000), release="r1", source_url="u")
    with pytest.raises(SigmaLoadError):
        load_sigma_zip(db_session, _zip_n(1500), release="r2", source_url="u")
    assert _count(db_session) == 2000


def test_record_error(db_session):
    load_sigma_zip(db_session, _zip_n(1200), release="r1", source_url="u")
    record_sigma_error(db_session, "HTTPError: 503")
    assert db_session.get(ReferenceSnapshot, "sigma").content["last_error"] == "HTTPError: 503"


def test_load_min_counts_unique_ids(db_session):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(1000):
            uid = uuid.UUID(int=i % 900 + 1)
            z.writestr(
                f"rules/w/r{i}.yml",
                f"title: R{i}\nid: {uid}\nstatus: test\nlevel: high\nlogsource:\n  product: w\n",
            )
    with pytest.raises(SigmaLoadError):
        load_sigma_zip(db_session, buf.getvalue(), release="r1", source_url="u")
