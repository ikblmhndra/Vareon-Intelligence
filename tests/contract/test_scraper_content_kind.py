"""Kontrak `content_kind` / `default_relevance` per scraper (P2 cheap wins, spec 2.1).

`content_kind` menentukan grade default sumber; `default_relevance="always"` melewati classify
dan TTP, jadi HANYA boleh untuk sumber terstruktur (KEV, Exploit-DB, CIS).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from cti_scraper import registry


def _real_scrapers() -> dict[str, type]:
    """Hanya scraper paket `cti_scrapers` -- test lain mendaftarkan scraper palsu ke registry
    yang sama (mis. `unpatched`) dan itu bukan urusan kontrak ini."""
    return {
        sid: cls
        for sid, cls in registry.discover().items()
        if cls.__module__.startswith("cti_scrapers.")
    }


STRUCTURED_KINDS = {"advisory", "kev", "exploit"}
ALWAYS_EXPECTED = {"cisa_kev": "kev", "exploitdb": "exploit", "cis": "advisory"}


def test_always_only_for_structured_kinds() -> None:
    bad = {
        sid: (cls.meta.content_kind, cls.meta.default_relevance)
        for sid, cls in _real_scrapers().items()
        if cls.meta.default_relevance == "always" and cls.meta.content_kind not in STRUCTURED_KINDS
    }

    assert bad == {}


def test_always_set_exactly_on_structured_sources() -> None:
    always = {
        sid: cls.meta.content_kind
        for sid, cls in _real_scrapers().items()
        if cls.meta.default_relevance == "always"
    }

    assert always == ALWAYS_EXPECTED


def _meta_call_keywords(tree: ast.AST) -> list[set[str]]:
    """Kumpulan nama keyword dari tiap pemanggilan `ScraperMeta(...)` di satu modul."""
    found: list[set[str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ScraperMeta"
        ):
            found.append({kw.arg for kw in node.keywords if kw.arg})
    return found


def test_every_scraper_declares_content_kind() -> None:
    """Tiap modul scraper harus menulis `content_kind=` EKSPLISIT di `ScraperMeta(...)`,
    bukan mengandalkan default "news" (default itu cuma jaring pengaman)."""
    missing: list[str] = []
    for sid, cls in _real_scrapers().items():
        path = Path(inspect.getsourcefile(cls) or "")
        calls = _meta_call_keywords(ast.parse(path.read_text(encoding="utf-8")))
        if not calls or not all("content_kind" in kws for kws in calls):
            missing.append(sid)

    assert missing == []
