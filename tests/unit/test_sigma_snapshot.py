"""Snapshot SigmaHQ yang ikut di paket (P7e, spec 4.2): zip cocok dengan SOURCE dan lolos guard."""

from __future__ import annotations

import hashlib

from cti_core.hunt.sigma import MIN_RULES, SNAPSHOT_DIR, parse_sigma_zip, read_source


def test_committed_snapshot_matches_source() -> None:
    src = read_source()
    data = (SNAPSHOT_DIR / "sigma_all_rules.zip").read_bytes()
    assert hashlib.sha256(data).hexdigest() == src["sha256"]
    assert len(parse_sigma_zip(data).rules) >= MIN_RULES
    assert (SNAPSHOT_DIR / "LICENSE.Detection.Rules.md").is_file()
