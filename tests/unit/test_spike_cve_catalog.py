"""`tools/ops/spike_cve_catalog.py` -- spike pengukuran katalog tech dari CVE List V5 (ROADMAP #19).

Skrip ini dijalankan di server dev oleh manusia dan hasilnya jadi dasar keputusan desain, jadi yang
dikunci di sini: ekstraksi dari bentuk record CVE JSON 5.x yang NYATA (bentuk dicek terhadap record
CVE-2025-0108/-1974/-24813 asli), klasifikasi sampah, vonis per tech, kedua jenis sumber (direktori
dan zip, termasuk zip bersarang), dan perbandingan dengan tracker."""

from __future__ import annotations

import datetime
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tools.ops import spike_cve_catalog as sp

SINCE = datetime.date(2025, 1, 1)


def cve(
    cve_id: str,
    *affected: dict[str, Any],
    published: str = "2025-03-10T12:00:00.000Z",
    state: str = "PUBLISHED",
    adp: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    containers: dict[str, Any] = {"cna": {"affected": list(affected)}}
    if adp is not None:
        containers["adp"] = [{"affected": adp}]
    return {
        "cveMetadata": {"cveId": cve_id, "state": state, "datePublished": published},
        "containers": containers,
    }


def prod(vendor: str, product: str, **extra: Any) -> dict[str, Any]:
    return {"vendor": vendor, "product": product, "versions": [{"version": "1"}], **extra}


def write_tree(root: Path, records: list[dict[str, Any]]) -> None:
    for rec in records:
        cid = rec["cveMetadata"]["cveId"]
        year, num = cid.split("-")[1], int(cid.split("-")[2])
        d = root / "cves" / year / f"{num // 1000}xxx"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{cid}.json").write_text(json.dumps(rec))


def corpus_of(*records: dict[str, Any]) -> sp.Corpus:
    raw = [(f"{r['cveMetadata']['cveId']}.json", json.dumps(r).encode()) for r in records]
    return sp.load_corpus(raw, SINCE)


# ── normalisasi dan pencocok ──────────────────────────────────────────────────────────────────


def test_normalize_compact_and_family() -> None:
    assert sp.normalize("Palo_Alto-Networks") == "palo alto networks"
    assert sp.compact("Palo Alto Networks") == sp.compact("paloaltonetworks")
    assert sp.family("windows 10 version 1507") == "windows"
    assert sp.family("windows server 2022") == "windows server"
    assert sp.family("windows 11 version 23h2") == "windows"
    assert sp.family("nginx") == "nginx"
    assert sp.family("log4j") == "log4j"


@pytest.mark.parametrize(
    ("tech", "text", "expected"),
    [
        ("graylog", "graylog2-server", True),
        ("nginx", "ingress-nginx", True),
        ("nginx", "nginxy", False),
        ("go", "google", False),
        ("c++", "c++ inc", False),  # istilah < 2 karakter tak pernah cocok (sama dengan tech_match)
    ],
)
def test_local_matcher_follows_the_shared_rules(tech: str, text: str, expected: bool) -> None:
    assert sp.mentions(tech, text) is expected


@pytest.mark.parametrize(
    ("product", "reason"),
    [
        ("n/a", "placeholder"),
        ("N/A", "placeholder"),
        ("Unspecified", "placeholder"),
        ("web application", "generik"),
        ("1.2.3", "mirip-versi"),
        ("v2.0.1-beta", "mirip-versi"),
        ("2024", "angka-saja"),
        ("https://github.com/x/y", "url"),
        ("github.com/x/y", "url"),
        # bentuk janggal tapi produk asli: BUKAN sampah (laporan 2026-10-07 salah menghitungnya)
        ("chatwoot/chatwoot", None),
        ("a" * 90, None),
        ("Giveaways and Contests by RafflePress", None),
        ("Social Media Share Buttons & Social Sharing Icons", None),
        ("PAN-OS", None),
        ("Windows Server 2022, 23H2 Edition (Server Core installation)", None),  # koma sah
        ("Zabbix", None),
    ],
)
def test_junk_reason(product: str, reason: str | None) -> None:
    assert sp.junk_reason(product) == reason


# ── ekstraksi ─────────────────────────────────────────────────────────────────────────────────


def test_parse_record_extracts_cna_products_cpes_and_date() -> None:
    rec = sp.parse_record(
        cve(
            "cve-2025-0108",
            prod("Palo Alto Networks", "PAN-OS", cpes=["cpe:2.3:o:paloaltonetworks:pan-os:*:*:*"]),
            prod("n/a", "n/a", packageName="pkg"),
        )
    )

    assert rec is not None
    assert rec.cve_id == "CVE-2025-0108" and rec.published == datetime.date(2025, 3, 10)
    assert [p.vendor for p in rec.cna] == ["Palo Alto Networks", "n/a"]
    assert rec.cna[0].identity_names() == ("paloaltonetworks", "pan-os")  # CPE lebih bersih
    assert rec.cna[1].identity_names() == ("n/a", "n/a")


def test_cpe_wildcards_fall_back_to_the_cna_fields() -> None:
    p = sp.Product("Acme", "Widget", "", ("cpe:2.3:a:*:*:*:*",), "cna")
    assert p.identity_names() == ("Acme", "Widget")


@pytest.mark.parametrize("bad", [None, [], {}, {"cveMetadata": {}}, {"cveMetadata": {"cveId": 5}}])
def test_parse_record_ignores_non_records(bad: Any) -> None:
    assert sp.parse_record(bad) is None


def test_corpus_filters_state_date_and_garbage() -> None:
    good = cve("CVE-2025-0001", prod("Acme", "Widget"))
    old = cve("CVE-2025-0002", prod("Acme", "Widget"), published="2024-12-31T00:00:00Z")
    rejected = cve("CVE-2025-0003", prod("Acme", "Widget"), state="REJECTED")
    undated = cve("CVE-2025-0004", prod("Acme", "Widget"), published="")
    raw = [
        (f"{i}.json", json.dumps(r).encode()) for i, r in enumerate([good, old, rejected, undated])
    ]
    raw += [("bad.json", b"{not json"), ("delta.json", b'{"new": []}')]

    c = sp.load_corpus(raw, SINCE)

    assert [r.cve_id for r in c.records] == ["CVE-2025-0001"]
    assert (c.parse_errors, c.not_published, c.before_since, c.no_date) == (1, 1, 1, 1)


# ── sumber: direktori dan zip ─────────────────────────────────────────────────────────────────


def test_directory_source_filters_by_id_year(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        [
            cve("CVE-2025-1111", prod("Acme", "Widget")),
            cve("CVE-2024-2222", prod("Acme", "Gadget")),  # tahun ID 2024, terbit 2025
            cve("CVE-2021-3333", prod("Acme", "Old")),
        ],
    )

    names = [n for n, _ in sp.iter_raw(tmp_path, {2024, 2025})]

    assert sorted(Path(n).name for n in names) == ["CVE-2024-2222.json", "CVE-2025-1111.json"]


def _zip_bytes(records: list[dict[str, Any]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for rec in records:
            cid = rec["cveMetadata"]["cveId"]
            zf.writestr(f"cves/{cid.split('-')[1]}/1xxx/{cid}.json", json.dumps(rec))
    return buf.getvalue()


def test_plain_and_nested_zip_sources(tmp_path: Path) -> None:
    records = [cve("CVE-2025-1001", prod("Acme", "Widget")), cve("CVE-2023-1002", prod("A", "B"))]
    plain = tmp_path / "plain.zip"
    plain.write_bytes(_zip_bytes(records))
    nested = tmp_path / "nested.zip.zip"
    with zipfile.ZipFile(nested, "w") as outer:
        outer.writestr("2025-10-07_all_CVEs_at_midnight.zip", _zip_bytes(records))

    for source in (plain, nested):
        got = [Path(n).name for n, _ in sp.iter_raw(source, {2025})]
        assert got == ["CVE-2025-1001.json"], source.name


# ── analisis ──────────────────────────────────────────────────────────────────────────────────


def test_coverage_junk_and_adp_rescue() -> None:
    c = corpus_of(
        cve("CVE-2025-0001", prod("Acme", "Widget")),
        cve("CVE-2025-0002", prod("n/a", "n/a")),  # hanya sampah
        cve("CVE-2025-0003"),  # tanpa affected
        cve("CVE-2025-0004", prod("n/a", "n/a"), adp=[prod("Beta", "Gizmo")]),  # diselamatkan ADP
    )

    r = sp.analyze(c, [], None, since=SINCE)

    assert (r.with_usable_cna, r.only_junk_cna, r.no_affected, r.rescued_by_adp) == (1, 2, 1, 1)
    assert r.junk["placeholder"] == 2
    assert {i.label for i in r.catalog} == {"acme | widget", "beta | gizmo"}


def test_spelling_variants_cluster_and_version_variants_fold_into_a_family() -> None:
    c = corpus_of(
        cve("CVE-2025-0001", prod("Palo Alto Networks", "PAN-OS")),
        cve("CVE-2025-0002", prod("paloaltonetworks", "pan_os")),
        cve("CVE-2025-0003", prod("Microsoft", "Windows 10 Version 1507")),
        cve("CVE-2025-0004", prod("Microsoft", "Windows 10 Version 1607")),
        cve("CVE-2025-0005", prod("Microsoft", "Windows 11 Version 22H2")),
    )

    r = sp.analyze(c, [], None, since=SINCE)

    assert r.normalized_ids == 5 and r.clustered_ids == 4  # PAN-OS dua ejaan jadi satu
    assert r.clusters and r.clusters[0][1] == 2
    assert r.families == 2  # palo alto|pan os + microsoft|windows
    assert r.top_families[0][0] == "microsoft|windows" and r.top_families[0][1] == 3


def test_long_tail_buckets() -> None:
    recs = [cve(f"CVE-2025-{n:04d}", prod("Acme", "Big")) for n in range(1, 6)]
    recs.append(cve("CVE-2025-0100", prod("Acme", "Tiny")))

    r = sp.analyze(corpus_of(*recs), [], None, since=SINCE)

    assert r.long_tail["5-19 CVE"] == 1 and r.long_tail["1 CVE"] == 1


def test_tech_verdicts_clean_one_vendor_many_products_ambiguous_and_none() -> None:
    c = corpus_of(
        cve("CVE-2025-0001", prod("F5", "NGINX")),
        cve("CVE-2025-0002", prod("F5", "NGINX Plus")),  # nginx: dua produk tapi satu vendor
        cve("CVE-2025-0003", prod("Palo Alto Networks", "PAN-OS")),
        cve("CVE-2025-0004", prod("Palo Alto Networks", "Prisma Access")),
        cve("CVE-2025-0005", prod("Palo Alto Networks", "Cortex XDR")),
        cve("CVE-2025-0006", prod("Okta", "Okta Verify")),  # bersih
        cve("CVE-2025-0007", prod("Acme", "jira helper")),
        cve("CVE-2025-0008", prod("Beta", "jira exporter")),  # jira: vendor tersebar
    )

    res = {
        t.tech: t
        for t in sp.analyze(
            c, ["nginx", "palo alto", "okta", "jira", "wazuh"], None, since=SINCE
        ).techs
    }

    assert res["okta"].verdict == "bersih"
    assert res["nginx"].verdict == "satu vendor, banyak produk"
    assert res["palo alto"].verdict == "satu vendor, banyak produk"
    assert res["jira"].verdict == "ambigu"
    assert res["wazuh"].verdict == "tidak ada" and not res["wazuh"].cves


def test_vendor_spellings_do_not_make_one_vendor_look_ambiguous() -> None:
    c = corpus_of(
        cve("CVE-2025-0001", prod("Palo Alto Networks", "PAN-OS")),
        cve("CVE-2025-0002", prod("paloaltonetworks", "PAN-OS")),
    )

    (res,) = sp.analyze(c, ["palo alto"], None, since=SINCE).techs[:1]

    assert res.vendor_share == 1.0 and res.verdict in ("bersih", "satu vendor, banyak produk")


def test_a_junk_product_is_a_hit_but_not_a_catalog_identity() -> None:
    c = corpus_of(cve("CVE-2025-0001", prod("Nginx Inc", "n/a")))

    (res,) = sp.analyze(c, ["nginx"], None, since=SINCE).techs[:1]

    assert res.cves == {"CVE-2025-0001"} and not res.identities and res.verdict == "tidak ada"


# ── tracker ───────────────────────────────────────────────────────────────────────────────────


def test_tracker_comparison_counts_both_only_tracker_only_catalog_and_outside_window() -> None:
    c = corpus_of(
        cve("CVE-2025-0001", prod("F5", "NGINX")),
        cve("CVE-2025-0002", prod("F5", "NGINX")),
        cve("CVE-2025-0003", prod("Zabbix", "Zabbix")),
    )
    tracker = [
        ("CVE-2025-0001", "nginx"),  # keduanya
        (
            "CVE-2025-0003",
            "nginx",
        ),  # hanya tracker (salah-cocok lama: Zabbix menyebut nginx di teks)
        ("CVE-2019-9999", "nginx"),  # di luar jendela
    ]

    r = sp.analyze(c, ["nginx"], tracker, since=SINCE)

    assert r.tracker is not None
    row = r.tracker[0]
    assert (row["tracker"], row["outside"], row["inside"], row["both"]) == (3, 1, 2, 1)
    assert row["only_tracker"] == ["CVE-2025-0003"] and row["only_catalog"] == ["CVE-2025-0002"]


def test_tracker_csv_requires_the_header(tmp_path: Path) -> None:
    ok = tmp_path / "ok.csv"
    ok.write_text("cve_id,tech\nCVE-2025-1,nginx\n,orphan\n")
    bad = tmp_path / "bad.csv"
    bad.write_text("id,name\n1,x\n")

    assert sp.read_tracker_csv(ok) == [("CVE-2025-1", "nginx")]
    with pytest.raises(SystemExit):
        sp.read_tracker_csv(bad)


# ── laporan dan CLI ───────────────────────────────────────────────────────────────────────────


def test_report_has_every_section_and_is_honest_about_limits() -> None:
    c = corpus_of(cve("CVE-2025-0001", prod("F5", "NGINX")))

    text = sp.render(sp.analyze(c, ["nginx"], None, since=SINCE), today=datetime.date(2026, 10, 7))

    for heading in (
        "## 1. Korpus",
        "## 2. Cakupan data produk",
        "## 3. Ukuran dan kebersihan katalog",
        "## 4. Duplikasi ejaan",
        "## 6. 34 tech produksi",
        "## 7. Recall terhadap tracker",
        "## 8. Batas pengukuran",
    ):
        assert heading in text
    assert "Tidak ada `--tracker-csv`" in text and "TIDAK ikut dihitung" in text


def test_cli_end_to_end_writes_report_and_catalog(tmp_path: Path) -> None:
    write_tree(
        tmp_path / "clone",
        [
            cve("CVE-2025-0001", prod("F5", "NGINX")),
            cve("CVE-2025-0002", prod("F5", "NGINX")),
        ],
    )
    tracker = tmp_path / "tracker.csv"
    tracker.write_text("cve_id,tech\nCVE-2025-0001,nginx\n")
    out, catalog = tmp_path / "report.md", tmp_path / "catalog.csv"

    code = sp.main(
        [
            "--source", str(tmp_path / "clone"), "--id-years", "2025", "--since", "2025-01-01",
            "--tracker-csv", str(tracker), "--out", str(out), "--catalog-csv", str(catalog),
        ]
    )  # fmt: skip

    assert code == 0
    report = out.read_text()
    assert "CVE dianalisis: 2" in report and "1/1 (100.0%)" in report
    rows = catalog.read_text().splitlines()
    assert rows[0].startswith("vendor,product,family") and "f5,nginx,nginx,2," in rows[1]


def test_cli_exits_non_zero_when_the_window_is_empty(tmp_path: Path) -> None:
    write_tree(
        tmp_path, [cve("CVE-2025-0001", prod("F5", "NGINX"), published="2020-01-01T00:00:00Z")]
    )

    assert sp.main(["--source", str(tmp_path), "--id-years", "2025"]) == 2


# ── record CVE asli (bentuk skema nyata, bukan buatan) ────────────────────────────────────────

REAL = Path(__file__).resolve().parents[1] / "fixtures" / "spike_cve"


def test_real_cve_json_records_parse_into_identities() -> None:
    """CVE-2025-0282 (Ivanti, 3 produk) dan CVE-2025-1974 (kubernetes ingress-nginx): data publik
    CVE List V5 apa adanya. Kalau CVE Program mengubah bentuk `affected`, test ini yang merah."""
    recs = {
        f.stem: sp.parse_record(json.loads(f.read_text())) for f in sorted(REAL.glob("CVE-*.json"))
    }

    ivanti, ingress = recs["CVE-2025-0282"], recs["CVE-2025-1974"]
    assert ivanti is not None and ingress is not None
    assert ivanti.published == datetime.date(2025, 1, 8)
    assert [p.identity_names() for p in ivanti.cna] == [
        ("Ivanti", "Connect Secure"),
        ("Ivanti", "Policy Secure"),
        ("Ivanti", "Neurons for ZTA gateways"),
    ]
    assert [p.identity_names() for p in ingress.cna] == [("kubernetes", "ingress-nginx")]


def test_real_ingress_nginx_shows_why_a_clean_verdict_is_not_a_correct_one() -> None:
    """`ingress-nginx` (kubernetes) bukan F5 nginx, tapi cocok kata utuh `nginx` (batasan leksikal,
    docs/CVE_TECH_MATCHING.md 6) dan vonisnya `bersih`. Vonis mengukur konsistensi nama, bukan
    benar-tidaknya produk; itu sebabnya laporan menyuruh tinjau manusia."""
    raw = [(f.name, f.read_bytes()) for f in sorted(REAL.glob("CVE-*.json"))]

    report = sp.analyze(sp.load_corpus(raw, SINCE), ["nginx", "ivanti"], None, since=SINCE)
    res = {t.tech: t for t in report.techs}

    assert res["nginx"].cves == {"CVE-2025-1974"} and res["nginx"].verdict == "bersih"
    assert res["ivanti"].verdict == "satu vendor, banyak produk" and len(res["ivanti"].cves) == 1


def test_non_latin_product_names_are_identities_not_placeholders() -> None:
    """Laporan pertama di data penuh menghitung nama produk CJK (plugin WordPress) sebagai
    "placeholder" karena normalisasi ASCII menghapusnya. Sekarang tetap identitas."""
    assert sp.normalize("워드프레스 결제 심플페이") == "워드프레스 결제 심플페이"
    assert sp.junk_reason("简数采集器") is None
    c = corpus_of(cve("CVE-2025-0001", prod("某公司", "简数采集器")))

    r = sp.analyze(c, [], None, since=SINCE)

    assert r.with_usable_cna == 1 and r.junk == {}
    assert sp.mentions("nginx", "nginx 서버") is True  # huruf non-Latin di sebelahnya = batas kata


def test_odd_shapes_are_noted_but_stay_identities() -> None:
    assert sp.shape_note("chatwoot/chatwoot") == "owner/repo"
    assert sp.shape_note("a" * 90) == "judul-panjang"
    assert sp.shape_note("Giveaways and Contests by RafflePress") == "memuat-and-atau-titik-koma"
    assert sp.shape_note("nginx") is None
    c = corpus_of(
        cve("CVE-2025-0001", prod("chatwoot", "chatwoot/chatwoot")),
        cve("CVE-2025-0002", prod("rafflepress", "Giveaways and Contests by RafflePress")),
    )

    r = sp.analyze(c, [], None, since=SINCE)

    assert r.with_usable_cna == 2 and r.junk == {}
    assert r.shapes == {"owner/repo": 1, "memuat-and-atau-titik-koma": 1}
