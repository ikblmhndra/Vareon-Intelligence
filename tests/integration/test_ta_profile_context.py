"""Blok konteks ATT&CK untuk prompt profil threat actor (spec 2026-10-24 bagian 6.1 butir 2),
Postgres asli (testcontainers): grup dicocokkan lewat nama/alias, software dan teknik lewat
`attack_relationships`."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import ta_profile
from cti_core.db.models.article import Article
from cti_core.db.models.attack import (
    AttackGroup,
    AttackRelationship,
    AttackSoftware,
    AttackTechnique,
)
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    session.add_all(
        [
            AttackGroup(
                stix_id="intrusion-set--g1",
                group_id="G0096",
                name="APT41",
                aliases=["Wicked Panda", "BARIUM"],
                domains=["enterprise-attack"],
            ),
            AttackSoftware(
                stix_id="malware--s1",
                software_id="S0154",
                name="Cobalt Strike",
                software_type="malware",
                domains=["enterprise-attack"],
            ),
            AttackTechnique(
                stix_id="attack-pattern--t1",
                attack_id="T1190",
                name="Exploit Public-Facing Application",
                tactics=["initial-access"],
                domains=["enterprise-attack"],
            ),
            AttackRelationship(
                stix_id="relationship--r1",
                relationship_type="uses",
                source_ref="intrusion-set--g1",
                source_type="intrusion-set",
                target_ref="malware--s1",
                target_type="malware",
                domain="enterprise-attack",
            ),
            AttackRelationship(
                stix_id="relationship--r2",
                relationship_type="uses",
                source_ref="intrusion-set--g1",
                source_type="intrusion-set",
                target_ref="attack-pattern--t1",
                target_type="attack-pattern",
                domain="enterprise-attack",
            ),
        ]
    )
    await session.flush()


async def test_ta_profile_context_from_attack(async_db_session: AsyncSession) -> None:
    await _seed(async_db_session)

    msg, mitre_id, article_count = await ta_profile.build_profile_input(
        async_db_session, "wicked panda"
    )

    assert mitre_id == "G0096"
    assert "G0096" in msg
    assert "Cobalt Strike" in msg
    assert "T1190" in msg
    assert "BARIUM" in msg
    assert article_count == 0


async def test_ta_profile_context_without_match(async_db_session: AsyncSession) -> None:
    await _seed(async_db_session)

    msg, mitre_id, article_count = await ta_profile.build_profile_input(
        async_db_session, "Unknown Crew"
    )

    assert mitre_id is None
    assert "Unknown Crew" in msg
    assert "No MITRE ATT&CK group matches" in msg
    assert "G0096" not in msg
    assert article_count == 0


@pytest.mark.parametrize(("seeded", "expected"), [(3, 3), (12, 10)])
async def test_ta_profile_article_count(
    async_db_session: AsyncSession, seeded: int, expected: int
) -> None:
    today = datetime.date.today()
    async_db_session.add_all(
        Article(
            title=f"Zorbax Crew campaign {i}",
            url=f"https://example.test/zorbax/{i}",
            url_hash=f"zorbax-{i}",
            source="Test Source",
            posted_on=today,
        )
        for i in range(seeded)
    )
    await async_db_session.flush()

    _msg, _mitre, article_count = await ta_profile.build_profile_input(
        async_db_session, "Zorbax Crew"
    )

    assert article_count == expected
