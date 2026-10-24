from cti_core.ioc.allowlist import allowlist_match, load_seed
from cti_core.ioc.extractor import extract_iocs

AL = {
    "url_domains": {"gofile.io"},
    "email_domains": {"gmail.com"},
    "ips": {"8.8.8.8"},
}
REASON = "allowlist:url_domain:gofile.io (infrastructure-abuse)"


def test_domain_suffix_match() -> None:
    assert allowlist_match("domain", "store1.gofile.io", AL) == REASON
    assert allowlist_match("domain", "gofile.io", AL) == REASON


def test_domain_lookalikes_do_not_match() -> None:
    assert allowlist_match("domain", "notgofile.io", AL) is None
    assert allowlist_match("domain", "gofile.io.evil.net", AL) is None


def test_url_host_suffix_match() -> None:
    assert allowlist_match("url", "https://cdn.gofile.io", AL) == REASON
    assert allowlist_match("url", "https://cdn.gofile.io/", AL) == REASON
    assert allowlist_match("url", "https://evil.net/gofile.io", AL) is None


def test_url_with_path_or_query_is_never_flagged() -> None:
    assert allowlist_match("url", "https://gofile.io/d/abc123", AL) is None
    assert allowlist_match("url", "https://gofile.io/?id=1", AL) is None
    assert allowlist_match("url", "https://gofile.io?id=1", AL) is None
    assert allowlist_match("url", "https://gofile.io/#frag", AL) is None


def test_seed_has_no_tenant_namespaces() -> None:
    seed = set(load_seed())
    for bad in ("workers.dev", "trycloudflare.com", "amazonaws.com", "github.io", "anonfiles.com"):
        assert bad not in seed


def test_email_domain_suffix_match() -> None:
    assert (
        allowlist_match("email", "bob@mail.gmail.com", AL)
        == "allowlist:email_domain:gmail.com (infrastructure-abuse)"
    )
    assert allowlist_match("email", "bob@evilgmail.com", AL) is None


def test_ip_exact_only() -> None:
    assert allowlist_match("ip", "8.8.8.8", AL) == "allowlist:ip:8.8.8.8 (infrastructure-abuse)"
    assert allowlist_match("ip", "8.8.8.80", AL) is None


def test_other_types_never_match() -> None:
    assert allowlist_match("sha256", "a" * 64, AL) is None


def test_seed_shape() -> None:
    seed = load_seed()
    assert 120 <= len(seed) <= 200
    assert all(d == d.lower() and d.strip() == d for d in seed)
    assert len(seed) == len(set(seed))
    assert "gofile.io" in seed and "ably.io" in seed and "github.com" in seed


def test_extractor_keeps_allowlisted_but_drops_private_and_self() -> None:
    text = "See https://wiz.io/blog and 8.8.8.8 and 10.0.0.1 and https://src.example/a"
    result = extract_iocs(text, source_url="https://src.example/post")
    assert "https://wiz.io/blog" in result["urls"]
    assert result["ips"] == ["8.8.8.8"]
    assert not any("src.example" in u for u in result.get("urls", []))
