"""Grade bawaan per `content_kind` (0.8.6, spec P2 5.1)."""

from __future__ import annotations

from cti_core.confidence import DEFAULT_GRADES


def test_default_grades_table() -> None:
    assert DEFAULT_GRADES == {
        "kev": ("A", "1"),
        "advisory": ("A", "2"),
        "exploit": ("B", "2"),
        "vendor_research": ("B", "2"),
        "news": ("C", "3"),
        "vendor_marketing": ("C", "4"),
        "social": ("D", "4"),
    }
