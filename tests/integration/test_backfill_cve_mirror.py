"""`tools/ops/backfill_cve_mirror.py` di Postgres beneran: mode laporan TIDAK menulis, `--apply`
menulis dan idempoten, sumber clone maupun zip, record rusak/di luar retensi dihitung, dan skrip
menolak jalan bila `cve.mirror_sync` sedang memegang kunci."""

from __future__ import annotations

import datetime
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from cti_core.cve_mirror_sync import LOCK_KEY
from cti_core.db.models.catalog import CatalogVendor
from cti_core.db.models.cve_mirror import CveRecord
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tools.ops import backfill_cve_mirror as bf
from tools.ops.spike_cve_catalog import iter_raw

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "spike_cve"
TODAY = datetime.date(2026, 10, 7)
NAMES = ("CVE-2025-0282", "CVE-2025-1974")


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


def make_clone(root: Path) -> Path:
    """Tata letak CVE List V5: `cves/<tahun>/<Nxxx>/CVE-....json`."""
    for name in NAMES:
        d = root / "cves" / "2025" / "0xxx"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.json").write_bytes((FIXTURES / f"{name}.json").read_bytes())
    extra = root / "cves" / "2025" / "9xxx"
    extra.mkdir(parents=True)
    (extra / "CVE-2025-9001.json").write_text("{ bukan json")
    old = json.loads((FIXTURES / "CVE-2025-0282.json").read_text())
    old["cveMetadata"].update(cveId="CVE-2024-0001", datePublished="2024-06-01T00:00:00.000Z")
    d24 = root / "cves" / "2024" / "0xxx"
    d24.mkdir(parents=True)
    (d24 / "CVE-2024-0001.json").write_text(json.dumps(old))
    return root


def count(s: Session) -> int:
    return s.scalar(select(func.count()).select_from(CveRecord)) or 0


def test_report_mode_computes_everything_but_writes_nothing(
    session: Session, tmp_path: Path
) -> None:
    clone = make_clone(tmp_path)
    r = bf.run(session, iter_raw(clone, {2024, 2025}), today=TODAY, apply=False)
    assert (r.scanned, r.parse_errors, r.outcomes["created"]) == (4, 1, 2)
    assert r.outcomes["skipped"] == 1 and r.skip_reasons["di luar retensi"] == 1
    assert r.totals["cve_records"] == 2 and r.totals["catalog_vendors"] >= 2
    assert not r.applied
    assert count(session) == 0  # di-rollback


def test_apply_writes_and_is_idempotent(session: Session, tmp_path: Path) -> None:
    clone = make_clone(tmp_path)
    first = bf.run(session, iter_raw(clone, {2025}), today=TODAY, apply=True, commit_every=1)
    assert first.outcomes["created"] == 2 and count(session) == 2
    seen = dict(
        session.execute(select(CatalogVendor.key, CatalogVendor.cve_seen_total)).tuples().all()
    )
    again = bf.run(session, iter_raw(clone, {2025}), today=TODAY, apply=True)
    assert again.outcomes["updated"] == 2 and again.outcomes["created"] == 0
    assert count(session) == 2
    assert seen == dict(
        session.execute(select(CatalogVendor.key, CatalogVendor.cve_seen_total)).tuples().all()
    )


def test_zip_source_and_limit(session: Session, tmp_path: Path) -> None:
    clone = make_clone(tmp_path / "src")
    archive = tmp_path / "cvelistV5-main.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in clone.rglob("CVE-*.json"):
            zf.writestr(
                f"cvelistV5-main/cves/{path.relative_to(clone / 'cves')}", path.read_bytes()
            )
    r = bf.run(session, iter_raw(archive, {2025}), today=TODAY, apply=True, limit=1)
    assert r.scanned == 1 and count(session) == 1


def test_refuses_to_run_while_the_sync_lock_is_held(session: Session, tmp_path: Path) -> None:
    from cti_core.db.engine import get_sync_engine

    clone = make_clone(tmp_path)
    with get_sync_engine().connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            with pytest.raises(bf.Locked):
                bf.run(session, iter_raw(clone, {2025}), today=TODAY, apply=True)
        finally:
            other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
    assert count(session) == 0


def test_main_rejects_missing_source_and_bad_years(tmp_path: Path) -> None:
    assert bf.main(["--source", str(tmp_path / "nope")]) == 2
    assert bf.main(["--source", str(tmp_path), "--years", "abc"]) == 2


def test_empty_source_fails_loudly_with_a_diagnosis(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "salah-folder").mkdir()
    assert bf.main(["--source", str(tmp_path)]) == 4
    err = capsys.readouterr().err
    assert "TIDAK ADA berkas CVE" in err and "TIDAK ada" in err and "salah-folder" in err


def test_diagnosis_shows_which_years_the_source_does_have(tmp_path: Path) -> None:
    make_clone(tmp_path)
    text = bf.describe_source(tmp_path, {2030})
    assert "2024=1" in text and "2025=3" in text and "[2030]" in text
    assert "ada" in text


def test_progress_lines_show_rate_and_eta(
    session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clone = make_clone(tmp_path)
    total = bf.count_source(clone, {2024, 2025})
    assert total == 4
    bf.run(
        session,
        iter_raw(clone, {2024, 2025}),
        today=TODAY,
        apply=False,
        total=total,
        progress_every=2,
    )
    err = capsys.readouterr().err
    assert "[" in err and "2/4 berkas" in err and "sisa ~" in err and "4/4 berkas" in err
