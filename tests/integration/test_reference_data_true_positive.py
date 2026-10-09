"""`reference_data._resolve_true_positive_cves` (daftar CVE untuk monitor PoC GitHub): FP dinilai
per baris client, bukan lewat himpunan FP dari client mana pun. Skenarionya: `cve_fp_scenario`."""

from __future__ import annotations

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
    db_session.add_all(CveTracker(cve_id=c, client_id=cl, tech="nginx") for c, cl in TRACKED)
    db_session.add_all(CveFalsePositive(cve_id=c, client_id=cl) for c, cl in MARKED_FP)
    db_session.flush()

    entries = _resolve_true_positive_cves(db_session)

    assert [e["cve_id"] for e in entries] == TRUE_POSITIVES
