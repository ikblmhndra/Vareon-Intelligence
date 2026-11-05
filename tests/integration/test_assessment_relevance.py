"""Integration test sinyal relevansi di `assessment` (P7f Task 2) -- Postgres REAL.

PIR aktif dan techstack aktif dimuat per batch oleh `apply_assessments*`; hasilnya masuk
`priority_score` dan `score_reasons` lewat `assess()`."""

from __future__ import annotations

import datetime
import hashlib
from typing import Any

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveFalsePositive, CveTracker
from cti_core.db.models.pir import PIRRequirement
from cti_core.db.models.techstack import TechStackEntry
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.article_cve import AsyncArticleCveRepo
from cti_core.db.repositories.assessment import apply_assessments, apply_assessments_async
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_TODAY = datetime.datetime.now(datetime.UTC).date()


async def _pir(s: AsyncSession, client: str = "default", **kw: Any) -> PIRRequirement:
    await AsyncClientRepo(s).ensure_default()
    if client != "default" and await AsyncClientRepo(s).get(client) is None:
        s.add(Client(client_id=client, name=client))
        await s.flush()
    status = kw.pop("status", "active")
    start, end = kw.pop("start_date", None), kw.pop("end_date", None)
    pir = await AsyncPIRRepo(s).create(
        {"title": kw.pop("title", "PIR uji"), "priority": kw.pop("priority", "P2"), **kw},
        client_id=client,
    )
    pir.status, pir.start_date, pir.end_date = status, start, end
    await s.flush()
    return pir


async def _art(s: AsyncSession, n: str, title: str = "Berita biasa", **kw: Any) -> Article:
    url = f"https://ex.com/rel-{n}"
    kw.setdefault("source", "src")
    art = Article(url=url, url_hash=hashlib.sha256(url.encode()).hexdigest(), title=title, **kw)
    s.add(art)
    await s.flush()
    return art


async def _tech(s: AsyncSession, name: str, client: str = "default", active: bool = True) -> None:
    await AsyncClientRepo(s).ensure_default()
    if client != "default" and await AsyncClientRepo(s).get(client) is None:
        s.add(Client(client_id=client, name=client))
    s.add(TechStackEntry(name=name, client_id=client, active=active, targets=[]))
    await s.flush()


async def _score(s: AsyncSession, art: Article) -> Any:
    return (await apply_assessments_async(s, [art.id]))[art.id]


def _codes(a: Any) -> dict[str, int]:
    return {p["code"]: p["points"] for p in a.reasons["priority"]}


@pytest.mark.asyncio
async def test_pir_actor_match_adds_points(async_db_session: AsyncSession) -> None:
    s = async_db_session
    pir = await _pir(s, criteria={"threat_actors": ["ShinyHunters"]})
    art = await _art(s, "actor")
    await AsyncArticleRepo(s).set_enrichment(art, threat_actors=["ShinyHunters"])

    a = await _score(s, art)

    assert _codes(a)["pir_match"] == 15
    assert a.reasons["pir"][0]["id"] == pir.id
    assert a.reasons["pir"][0]["client_id"] == "default"


_CRITERIA = [
    {"threat_actors": ["ShinyHunters"]},
    {"malware": ["Lumma Stealer"]},
    {"ttps": ["T1059"]},
    {"keywords": ["ransomware"]},
    {"countries": ["ID"]},
    {"industries": ["Finance"]},
    {"threat_actors": ["ShinyHunters"], "keywords": ["ransomware"]},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("criteria", _CRITERIA)
async def test_pir_hits_equal_pir_page(
    async_db_session: AsyncSession, criteria: dict[str, Any]
) -> None:
    s = async_db_session
    repo = AsyncArticleRepo(s)
    arts = [
        await _art(s, f"eq{i}", "ransomware wave" if i % 2 else "Berita biasa") for i in range(4)
    ]
    await repo.set_enrichment(
        arts[0],
        threat_actors=["ShinyHunters"],
        malware=[("Lumma Stealer", "malware")],
        ttps=[("T1059", "Command and Scripting")],
        countries=[("ID", "victim")],
        industries=["Finance"],
    )
    await repo.set_enrichment(arts[1], threat_actors=["ShinyHunters"], countries=[("ID", "victim")])
    await repo.set_enrichment(arts[2], malware=[("Lumma Stealer", "malware")])
    pir = await _pir(s, criteria=criteria)

    result = await apply_assessments_async(s, [a.id for a in arts])
    hit_ids = {i for i, a in result.items() if "pir" in a.reasons}
    page, _ = await AsyncPIRRepo(s).list_articles_for_pir(pir, repo, page_size=100)

    assert hit_ids == {a.id for a in page} & {a.id for a in arts}
    assert hit_ids  # kriteria memang cocok ke sesuatu, bukan himpunan kosong yang kebetulan sama


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kw",
    [
        {"status": "archived"},
        {"end_date": _TODAY - datetime.timedelta(days=1)},
        {"start_date": _TODAY + datetime.timedelta(days=1)},
        {"criteria": {}},
    ],
)
async def test_pir_inactive_outside_dates_or_empty_criteria_no_hit(
    async_db_session: AsyncSession, kw: dict[str, Any]
) -> None:
    s = async_db_session
    await _pir(s, **{"criteria": {"keywords": ["ransomware"]}, **kw})
    art = await _art(s, "inactive", "ransomware wave", posted_on=_TODAY)

    assert "pir" not in (await _score(s, art)).reasons


@pytest.mark.asyncio
async def test_pir_window_filters_posted_on(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await _pir(s, criteria={"keywords": ["ransomware"]}, start_date=datetime.date(2026, 11, 1))
    old = await _art(s, "old", "ransomware wave", posted_on=datetime.date(2026, 10, 20))
    new = await _art(s, "new", "ransomware wave", posted_on=datetime.date(2026, 11, 2))

    result = await apply_assessments_async(s, [old.id, new.id])

    assert "pir" not in result[old.id].reasons
    assert "pir" in result[new.id].reasons


@pytest.mark.asyncio
async def test_null_posted_on_matches_pir_without_dates(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await _pir(s, criteria={"keywords": ["ransomware"]})
    art = await _art(s, "nodate", "ransomware wave")

    assert "pir" in (await _score(s, art)).reasons


@pytest.mark.asyncio
async def test_malformed_criteria_ignored(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await _pir(s, criteria={"threat_actors": "x", "keywords": [1]})
    art = await _art(s, "malformed", "x 1 ransomware")

    assert "pir" not in (await _score(s, art)).reasons


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [["x"], "x", None])
async def test_non_dict_criteria_ignored(async_db_session: AsyncSession, bad: Any) -> None:
    s = async_db_session
    await _pir(s, criteria=bad)
    art = await _art(s, "nondict", "x ransomware")

    assert "pir" not in (await _score(s, art)).reasons


@pytest.mark.asyncio
async def test_mixed_valid_and_malformed_keys_still_match(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await _pir(s, criteria={"threat_actors": "x", "keywords": ["mixedkw"]})
    art = await _art(s, "mixed", "mixedkw campaign")

    assert "pir" in (await _score(s, art)).reasons


@pytest.mark.asyncio
async def test_unmatched_active_pir_keeps_p6_scores(async_db_session: AsyncSession) -> None:
    s = async_db_session
    art = await _art(s, "plain")
    before = await _score(s, art)
    await _pir(s, criteria={"threat_actors": ["Nobody"]})

    after = await _score(s, art)

    assert (after.priority_score, after.reasons) == (before.priority_score, before.reasons)


@pytest.mark.asyncio
async def test_title_tech_hit(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await _tech(s, "gitlab")
    art = await _art(s, "gl", "GitLab patches critical flaw")

    a = await _score(s, art)

    assert _codes(a)["own_asset"] == 15
    assert a.reasons["own_asset"] == [{"name": "gitlab", "client_id": "default"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "title"),
    [
        ("Oracle Java SE", "Oracle Java SE zero-day exploited"),
        ("n8n", "Critical n8n workflow RCE"),
        ("microsoft 365", "Microsoft 365 tenants phished"),
    ],
)
async def test_multiword_and_punctuated_names(
    async_db_session: AsyncSession, name: str, title: str
) -> None:
    s = async_db_session
    await _tech(s, name)
    art = await _art(s, "mw", title)

    assert (await _score(s, art)).reasons["own_asset"][0]["name"] == name


@pytest.mark.asyncio
async def test_inactive_techstack_no_hit(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await _tech(s, "gitlab", active=False)
    art = await _art(s, "gl-off", "GitLab patches critical flaw")

    assert "own_asset" not in (await _score(s, art)).reasons


async def _cve_art(s: AsyncSession, n: str, tech: str, *, fp: bool) -> Article:
    art = await _art(s, n, "Weekly vulnerability roundup")
    await AsyncArticleCveRepo(s).add_many(art.id, ["CVE-2026-7777"], "")
    s.add(CveTracker(cve_id="CVE-2026-7777", client_id="default", tech=tech))
    if fp:
        s.add(CveFalsePositive(cve_id="CVE-2026-7777", client_id="default"))
    await s.flush()
    return art


@pytest.mark.asyncio
@pytest.mark.parametrize("fp", [False, True])
async def test_cve_path_hit_and_fp_excluded(async_db_session: AsyncSession, fp: bool) -> None:
    s = async_db_session
    await _tech(s, "fortinet")
    art = await _cve_art(s, f"cve{fp}", "fortinet", fp=fp)

    reasons = (await _score(s, art)).reasons

    assert ("own_asset" in reasons) is (not fp)


@pytest.mark.asyncio
async def test_title_and_cve_hit_same_tech_one_entry(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await _tech(s, "fortinet")
    art = await _cve_art(s, "both", "fortinet", fp=False)
    art.title = "Fortinet patches FortiOS"
    await s.flush()

    a = await _score(s, art)

    assert a.reasons["own_asset"] == [{"name": "fortinet", "client_id": "default"}]
    assert _codes(a)["own_asset"] == 15


@pytest.mark.asyncio
async def test_two_clients_same_tech(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await _tech(s, "nginx")
    await _tech(s, "nginx", client="acme")
    art = await _art(s, "ng", "nginx request smuggling")

    a = await _score(s, art)

    assert {e["client_id"] for e in a.reasons["own_asset"]} == {"default", "acme"}
    assert _codes(a)["own_asset"] == 15


@pytest.mark.asyncio
async def test_sync_and_async_agree_with_relevance(
    db_session: Session, async_db_session: AsyncSession
) -> None:
    # Dua transaksi terbuka yang sama-sama membuat client "default" saling mengunci, jadi tiap
    # sesi memakai client sendiri; `client_id` dinormalkan sebelum dibandingkan.
    sync_s, s = db_session, async_db_session
    sync_s.add(Client(client_id="rel-sync", name="S"))
    sync_s.flush()
    sync_s.add_all(
        [
            PIRRequirement(
                title="PIR uji",
                priority="P1",
                client_id="rel-sync",
                criteria={"keywords": ["gitlab"]},
            ),
            TechStackEntry(name="gitlab", client_id="rel-sync", targets=[]),
        ]
    )
    art_s = Article(
        url="https://ex.com/sync-rel", url_hash="s" * 64, title="GitLab flaw", source="x"
    )
    sync_s.add(art_s)
    sync_s.flush()
    sync_result = apply_assessments(sync_s, [art_s.id])

    s.add(Client(client_id="rel-async", name="A"))
    await s.flush()
    await _pir(s, client="rel-async", priority="P1", criteria={"keywords": ["gitlab"]})
    await _tech(s, "gitlab", client="rel-async")
    art_a = await _art(s, "async-rel", "GitLab flaw", source="x")
    async_result = await apply_assessments_async(s, [art_a.id])

    def norm(a: Any) -> tuple[int, str]:
        pirs = [(p["priority"], p["title"]) for p in a.reasons["pir"]]
        assets = [e["name"] for e in a.reasons["own_asset"]]
        return a.priority_score, repr((pirs, assets, a.reasons["priority"]))

    assert norm(sync_result[art_s.id]) == norm(async_result[art_a.id])
    assert _codes(sync_result[art_s.id]) == {"pir_match": 20, "own_asset": 15}
