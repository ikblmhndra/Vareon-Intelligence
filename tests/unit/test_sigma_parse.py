"""Parser zip rilis SigmaHQ (P7e, spec 4.1): path, ruleset, teknik ATT&CK, aturan yang dilewati."""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from cti_core.hunt.sigma import SigmaLoadError, parse_sigma_zip, techniques_from_tags

U1, U2, U3 = (uuid.UUID(int=i) for i in (1, 2, 3))


def _rule(uid: uuid.UUID, tags: list[str], status: str = "test", level: str = "high") -> str:
    return (
        f"title: Rule {uid}\nid: {uid}\nstatus: {status}\nlevel: {level}\n"
        f"tags: {tags}\nlogsource:\n  product: windows\n  category: process_creation\n"
    )


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


def test_techniques_from_tags():
    assert techniques_from_tags(
        ["attack.execution", "attack.t1059.001", "attack.T1059", "attack.g0016", "cve.2021-1"]
    ) == ["T1059", "T1059.001"]


def test_parse_good_and_skipped():
    p = parse_sigma_zip(
        _zip(
            {
                "rules/windows/a.yml": _rule(U1, ["attack.t1059.001"]),
                "rules/windows/b.yml": "title: no id\nlogsource: {}\nlevel: high\nstatus: test\n",
                "deprecated/windows/c.yml": _rule(U2, []),
                "rules/windows/d.yml": _rule(U3, [], status="deprecated"),
            }
        )
    )
    assert [r.id for r in p.rules] == [U1]
    assert p.rules[0].ruleset == "core" and p.rules[0].techniques == ["T1059.001"]
    assert p.rules[0].author == ""
    assert set(p.skipped) == {"rules/windows/b.yml", "rules/windows/d.yml"}


def test_parse_strips_top_folder():
    p = parse_sigma_zip(
        _zip({"sigma_all_rules\\rules-emerging-threats\\2024\\x.yml": _rule(U1, ["attack.t1190"])})
    )
    assert p.rules[0].path == "rules-emerging-threats/2024/x.yml"
    assert p.rules[0].ruleset == "emerging-threats"


def test_parse_not_a_zip():
    with pytest.raises(SigmaLoadError):
        parse_sigma_zip(b"nope")


def test_parse_skips_unsupported_values_and_folders():
    p = parse_sigma_zip(
        _zip(
            {
                "rules/a/ok.yml": _rule(U1, []),
                "rules/a/s.yml": _rule(U2, [], status="weird"),
                "rules/a/l.yml": _rule(U3, [], level="x" * 40),
                "rules/windows/deprecated/x.yml": _rule(uuid.UUID(int=4), []),
                "rules/windows/unsupported/x.yml": _rule(uuid.UUID(int=5), []),
            }
        )
    )
    assert [r.id for r in p.rules] == [U1]
    assert set(p.skipped) == {
        "rules/a/s.yml",
        "rules/a/l.yml",
        "rules/windows/deprecated/x.yml",
        "rules/windows/unsupported/x.yml",
    }
