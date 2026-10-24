from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from cti_core.ioc.canonical import CANONICAL_RULES_VERSION, canonical

CASES = [
    ("ip", "1[.]2[.]3(.)4", "1.2.3.4"),
    ("ip", " 1{.}2[dot]3(dot)4 ", "1.2.3.4"),
    ("domain", "Evil[.]COM.", "evil.com"),
    ("domain", "a[dot]b[.]c", "a.b.c"),
    ("url", "HXXPS://Evil[.]com/Payload.EXE?A=B", "https://evil.com/Payload.EXE?A=B"),
    ("url", "hxxp://a[.]b/x", "http://a.b/x"),
    ("url", "fxp://h[.]x/a", "ftp://h.x/a"),
    ("url", "hxxp[:]//Evil[.]com:8080/A#Frag", "http://evil.com:8080/A#Frag"),
    ("url", "http://User:Pw@Evil.com/Path", "http://User:Pw@evil.com/Path"),
    ("email", "Bob[@]Ex[.]Com", "bob@ex.com"),
    ("email", "bob(@)ex(.)com", "bob@ex.com"),
    ("email", "bob[at]ex[.]com", "bob@ex.com"),
    ("email", "Bob(at)Ex.com", "bob@ex.com"),
    ("url", "http://a.com/p\\x?q=1", "http://a.com/p\\x?q=1"),
    ("url", "HTTP://A[.]com/P[.]q", "http://a.com/P[.]q"),
    ("url", "hxxp://Ex[DOT]com/Path", "http://ex.com/Path"),
    ("domain", "Ex[DOT]com", "ex.com"),
    ("domain", "Ex(DOT)com", "ex.com"),
    ("email", "a@b[DOT]com", "a@b.com"),
    ("email", "a[AT]b.com", "a@b.com"),
    ("ip", "1[DOT]2.3.4", "1.2.3.4"),
    ("sha256", "ABCDEF", "abcdef"),
    ("sha1", "ABCDEF", "abcdef"),
    ("md5", "ABCDEF", "abcdef"),
    ("cve", " CVE-2024-1 ", "CVE-2024-1"),
]


@pytest.mark.parametrize(("ioc_type", "value", "expected"), CASES)
def test_canonical_rules(ioc_type: str, value: str, expected: str) -> None:
    assert canonical(ioc_type, value) == expected


@pytest.mark.parametrize(("ioc_type", "value", "expected"), CASES)
def test_canonical_idempotent(ioc_type: str, value: str, expected: str) -> None:
    once = canonical(ioc_type, value)
    assert canonical(ioc_type, once) == once


def test_unknown_type_only_stripped() -> None:
    assert canonical("mystery", "  Foo[.]Bar ") == "Foo[.]Bar"


def test_rules_version() -> None:
    assert CANONICAL_RULES_VERSION == 1


def test_persist_stores_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_enrich.stages import persist as persist_mod

    ioc_repo = MagicMock()
    monkeypatch.setattr(persist_mod, "IOCRepo", lambda session: ioc_repo)
    monkeypatch.setattr(persist_mod, "ArticleRepo", lambda session: MagicMock())
    monkeypatch.setattr(persist_mod, "resolve_industries", lambda x: [])
    monkeypatch.setattr(persist_mod, "_country_roles", lambda *a, **k: [])
    monkeypatch.setattr(persist_mod, "_audit_fields", lambda c: {})

    persist_mod.persist(
        session=MagicMock(),
        url="https://x.example/a",
        title="t",
        source="s",
        scraper_id=None,
        posted_on=None,
        classify_result=MagicMock(confidence=0.5, incident_confidence=None),
        score_result=None,
        routing_result=MagicMock(threat_actors=[]),
        ttp_result=None,
        ioc_data={"domains": ["Evil[.]com"], "urls_with_path": ["hxxp://a[.]b/x"]},
        c2_indicator=False,
    )
    got = [(c.kwargs["type"], c.kwargs["value"]) for c in ioc_repo.upsert.call_args_list]
    assert got == [("domain", "evil.com"), ("url", "http://a.b/x")]


async def test_newsletter_writer_stores_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from cti_api.services import newsletter

    repo = MagicMock()
    repo.upsert = AsyncMock()
    monkeypatch.setattr(newsletter, "AsyncIOCRepo", lambda s: repo)
    monkeypatch.setattr(newsletter, "AsyncCveTrackerRepo", lambda s: MagicMock())
    monkeypatch.setattr(
        newsletter,
        "_get_allowlist_sets",
        AsyncMock(return_value={"url_domains": {"a.b"}, "email_domains": set(), "ips": set()}),
    )
    art: dict[str, Any] = {
        "id": 1,
        "iocs": {
            "domains": ["Evil[.]com", "Sub[.]A[.]b"],
            "urls_with_path": ["hxxp://a[.]b/x"],
        },
    }
    ctx = {"highlights": [art], "apac": [], "global_news": [], "indonesia": []}
    await newsletter.write_article_findings(MagicMock(), ctx)
    got = [(c.kwargs["type"], c.kwargs["value"]) for c in repo.upsert.call_args_list]
    assert got == [("domain", "evil.com"), ("domain", "sub.a.b"), ("url", "http://a.b/x")]
    reasons = [c.kwargs["suppression_reason"] for c in repo.upsert.call_args_list]
    assert reasons == [None, "allowlist:url_domain:a.b (infrastructure-abuse)", None]
