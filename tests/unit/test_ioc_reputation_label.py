"""Label reputasi IOC dari kartu provider di `Indicator.enrichment` (pure, tanpa DB)."""

from __future__ import annotations

from cti_api.services.ioc_reputation import reputation_label


def _card(key: str, name: str, verdict: str) -> dict[str, object]:
    return {"key": key, "name": name, "verdict": verdict, "score": 0}


def test_reputation_label_worst_verdict() -> None:
    enrichment = {
        "providers": [
            _card("abuseipdb", "AbuseIPDB", "clean"),
            _card("otx", "AlienVault OTX", "suspicious"),
            _card("virustotal", "VirusTotal", "malicious"),
        ]
    }
    assert reputation_label(enrichment) == "malicious (VirusTotal)"
    assert (
        reputation_label({"providers": [_card("a", "A", "clean"), _card("b", "B", "suspicious")]})
        == "suspicious (B)"
    )
    assert reputation_label({"providers": [_card("a", "A", "clean")]}) == "clean (A)"


def test_reputation_label_none_when_unknown_or_empty() -> None:
    assert reputation_label({}) is None
    assert reputation_label({"providers": []}) is None
    assert reputation_label({"providers": [_card("a", "A", "unknown")]}) is None
    assert reputation_label({"providers": "rusak"}) is None
