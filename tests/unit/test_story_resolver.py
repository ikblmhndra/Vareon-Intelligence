"""Resolver story murni (P3, spec 3.2): aturan CVE, judul persis, judul mirip, veto, jendela."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cti_core.config import StorySettings
from cti_core.db.repositories.story import StoryCandidate, StoryMember
from cti_enrich.story.resolver import ArticleKeys, Match, key_cves, resolve

AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
CFG = StorySettings()
CHROME = (
    "2026-117: Multiple Vulnerabilities in Google Chrome Could Allow for Arbitrary Code Execution"
)
ADOBE = (
    "2026-114: Multiple Vulnerabilities in Adobe Products Could Allow for Arbitrary Code Execution"
)


def story(
    sid: int,
    cves: set[str] | None = None,
    members: list[tuple[str, str]] | None = None,
    last: timedelta = timedelta(hours=1),
    first: timedelta = timedelta(hours=2),
) -> StoryCandidate:
    return StoryCandidate(
        id=sid,
        cve_ids=frozenset(cves or ()),
        first_seen_at=AT - first,
        last_seen_at=AT - last,
        members=[StoryMember(t, s) for t, s in (members or [("zzz qqq", "Other")])],
        has_classify=False,
    )


def keys(title: str = "unrelated words here", source: str = "A", cves: set[str] | None = None):
    return ArticleKeys(title, source, frozenset(cves or ()), AT)


def test_cve_rule_majority_overlap():
    s = story(1, {"CVE-1", "CVE-3"})
    assert resolve(keys(cves={"CVE-1", "CVE-2"}), [s], CFG) == Match(1, "cve")
    assert resolve(keys(cves={"CVE-1", "CVE-2", "CVE-4"}), [story(1, {"CVE-1"})], CFG) is None


def test_cve_tie_break():
    one, two = story(1, {"CVE-1"}), story(2, {"CVE-1", "CVE-2"})
    k = keys(cves={"CVE-1", "CVE-2"})
    assert resolve(k, [one, two], CFG) == Match(2, "cve")
    small = story(3, {"CVE-1"}, members=[("a b", "X")])
    big = story(4, {"CVE-1"}, members=[("a b", "X"), ("c d", "Y")])
    assert resolve(keys(cves={"CVE-1"}), [small, big], CFG) == Match(4, "cve")
    tie_a, tie_b = story(9, {"CVE-1"}), story(5, {"CVE-1"})
    assert resolve(keys(cves={"CVE-1"}), [tie_a, tie_b], CFG) == Match(5, "cve")


def test_roundup_has_no_cve_key():
    ids = {f"CVE-2026-{n}" for n in range(6)}
    assert key_cves(ids, 5) == frozenset()
    assert key_cves({"cve-1"}, 5) == frozenset({"CVE-1"})
    assert resolve(keys(cves=ids), [story(1, ids)], CFG) is None


def test_exact_title_any_source():
    s = story(1, members=[("Patch Now: Foo Bar!", "A")])
    assert resolve(keys("patch now foo bar", "A"), [s], CFG) == Match(1, "title_exact")


def test_title_rule_requires_other_source():
    s = story(1, members=[(ADOBE, "Cis")])
    assert resolve(keys(CHROME, "Cis"), [s], CFG) is None
    near = story(1, members=[(ADOBE, "Other")])
    assert resolve(keys(CHROME, "Cis"), [near], CFG) == Match(1, "title")


def test_cve_veto_blocks_title():
    t = "Citrix confirms NetScaler zero-days exploited in attacks"
    s = story(1, {"CVE-2026-88771"}, members=[(t, "Other")])
    assert resolve(keys(t + " now", "A", {"CVE-2026-88779"}), [s], CFG) is None
    assert resolve(keys(t + " now", "A"), [s], CFG) == Match(1, "title")


def test_window_and_age():
    stale = story(1, {"CVE-1"}, last=timedelta(hours=73))
    assert resolve(keys(cves={"CVE-1"}), [stale], CFG) is None
    old = story(2, {"CVE-1"}, last=timedelta(hours=1), first=timedelta(days=8))
    assert resolve(keys(cves={"CVE-1"}), [old], CFG) is None


def test_title_tie_break_lowest_id():
    title = "Citrix confirms NetScaler zero-days exploited in attacks"
    members = [(title, "Other")]
    got = resolve(
        keys(title + " now", "A"), [story(7, members=members), story(3, members=members)], CFG
    )
    assert got == Match(3, "title")


def test_period_tokens_ignored():
    s = story(1, members=[("Ransomware 2026 Report September", "Threatmon")])
    assert resolve(keys("September 2026 Dark Web Issue Trend Report", "Asec"), [s], CFG) is None
