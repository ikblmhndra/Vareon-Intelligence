"""`reference_data._resolve_true_positive_cves` (daftar CVE untuk monitor PoC GitHub): FP dinilai
per baris client, bukan lewat himpunan FP dari client mana pun. Skenarionya: `cve_fp_scenario`."""

from __future__ import annotations

import datetime

from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveFalsePositive, CveTracker
from cti_scraper.reference_data import _resolve_true_positive_cves
from sqlalchemy.orm import Session

from tests.integration.cve_fp_scenario import MARKED_FP, TRACKED, TRUE_POSITIVES


def test_cves_some_client_still_needs_are_searched_for_pocs(db_session: Session) -> None:
    """Dulu CVE yang FP di satu client tak pernah dicari PoC-nya walau client lain masih
    men-track-nya sebagai valid."""
    db_session.add_all([Client(client_id=c, name=c.title()) for c in ("default", "acme")])
    db_session.flush()
    db_session.add_all(
        CveTracker(cve_id=c, client_id=cl, tech="nginx", published=datetime.date.today())
        for c, cl in TRACKED
    )
    db_session.add_all(CveFalsePositive(cve_id=c, client_id=cl) for c, cl in MARKED_FP)
    db_session.flush()

    entries = _resolve_true_positive_cves(db_session)

    assert [e["cve_id"] for e in entries] == TRUE_POSITIVES


def test_true_positive_cves_only_recent_or_kev(db_session: Session) -> None:
    """Hanya CVE terbit <= 90 hari atau di CISA KEV yang dicari PoC-nya (bukan semua 2.469)."""
    today = datetime.date.today()
    old = today - datetime.timedelta(days=100)
    recent = today - datetime.timedelta(days=10)
    db_session.add_all([Client(client_id=c, name=c.title()) for c in ("default", "acme")])
    db_session.flush()
    db_session.add_all(
        [
            CveTracker(cve_id="CVE-2020-0001", client_id="default", tech="x", published=old),
            CveTracker(
                cve_id="CVE-2020-0002", client_id="default", tech="x", published=old, cisa_kev=True
            ),
            CveTracker(cve_id="CVE-2026-0003", client_id="default", tech="x", published=recent),
            CveTracker(cve_id="CVE-2026-0004", client_id="default", tech="x", published=recent),
            CveTracker(cve_id="CVE-2026-0004", client_id="acme", tech="x", published=recent),
        ]
    )
    db_session.add(CveFalsePositive(cve_id="CVE-2026-0004", client_id="default"))
    db_session.flush()

    entries = _resolve_true_positive_cves(db_session)

    # 0004 tetap ada: FP hanya di client default, acme masih valid.
    assert [e["cve_id"] for e in entries] == ["CVE-2020-0002", "CVE-2026-0003", "CVE-2026-0004"]
