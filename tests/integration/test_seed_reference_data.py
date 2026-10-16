"""`tools/seed/fase10_reference_data.py` -- seed data referensi cutover (10.C).

Dump-nya PALSU (`MemoryDump`) tapi bentuknya disalin dari dokumen dump asli
(`legacy/dump`), supaya test jalan tanpa `pymongo` dan tanpa file BSON. Satu
test terakhir baca dump ASLI kalau ada -- itu yang ngunci angka di PROGRESS.md.

Fungsi seed cuma `flush()`, gak `commit()`, jadi `db_session` biasa cukup.
"""

from __future__ import annotations

import datetime
import pathlib

import pytest
from cti_core.db.models.auth import Client, ClientCountry, Role
from cti_core.db.models.ioc_reference import IocAllowlistEntry
from cti_core.db.models.pir import PIRNote, PIRRequirement
from cti_core.db.models.ta import TAProfile, TAWatchlistEntry, TAWhitelistEntry
from cti_core.db.models.techstack import TechStackEntry
from cti_core.db.models.threat_reference import MonitoredPerson, ThreatActorGroup
from cti_core.db.models.tweet import MonitoredAccount
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tools.seed import fase10_reference_data as seed
from tools.seed._dump import DirDump, MemoryDump

PIR_1 = "69ed6826daed4940a867c5f1"
PIR_2 = "69ed6826daed4940a867c5f2"


def dump_data() -> dict[str, list[dict]]:
    return {
        "news_db/clients": [
            {
                "client_id": "default",
                "name": "Default",
                "countries": ["Indonesia"],
                "created_at": "2026-05-14T18:35:15.228876+00:00",
            },
            {
                "client_id": "privy",
                "name": "Privy Identitas Digital",
                "countries": ["Australia", "Indonesia"],
            },
        ],
        "news_db/roles": [
            {
                "name": "custom-ops",
                "display_name": "Ops",
                "permissions": ["view_news"],
                "is_system": False,
                "created_by": "admin",
            },
        ],
        "threatintel/techstack": [
            {
                "name": "anydesk",
                "added_date": "2026-04-18",
                "source": "migration",
                "exposure": "internal",
            },  # tanpa client_id -> default
            {
                "name": "splunk",
                "client_id": "privy",
                "added_date": "2026-06-24",
                "source": "manual",
                "exposure": "internal",
                "hosting_type": "on_prem",
            },
        ],
        "news_db/monitored_accounts": [
            {
                "username": "virusbtn",
                "active": True,
                "display_name": "",
                "notes": "",
                "added_at": datetime.datetime(2026, 5, 12, 14, 16, 35),
            },
        ],
        "threatintel/ta_profiles": [
            {
                "_id": "x",
                "_actor_name": "apt36",
                "_generated_at": "2026-05-04T00:53:36+00:00",
                "identity": {"primary_name": "APT36"},
                "motivation": {"primary_motivation": "espionage"},
            },
        ],
        "threatintel/ta_watchlist": [
            {"name": "apt36", "added_date": "2026-04-27", "client_id": "default"},
        ],
        "threatintel/whitelist": [{"name": "TestActor", "added_date": "2026-04-26"}],
        "threatintel/source_scores": [
            {
                "source_name": "Cyfirma",
                "analyst_name": "Michael",
                "reliability_grade": "A",
                "credibility_code": "2",
                "admiralty_code": "A2",
                "notes": "TIP",
                "added_date": "2026-04-24",
                "last_updated": "2026-04-24",
            },
        ],
        "news_db/pir_requirements": [
            # Dua PIR BERJUDUL SAMA (ada di dump asli) -- beda created_at.
            {
                "_id": PIR_1,
                "title": "Monitor ShinyHunters",
                "priority": "P2",
                "owner": "",
                "status": "active",
                "criteria": {"threat_actors": ["Shinyhunters"]},
                "created_at": "2026-04-27T09:53:46.650771",
            },
            {
                "_id": PIR_2,
                "title": "Monitor ShinyHunters",
                "priority": "P1",
                "owner": "Michael",
                "status": "active",
                "criteria": {"threat_actors": ["Shinyhunters"]},
                "start_date": "2026-05-04",
                "end_date": "2026-05-04",
                "created_at": "2026-05-04T10:55:09.155845",
            },
        ],
        "news_db/pir_notes": [
            {
                "pir_id": PIR_2,
                "url": "https://x.example/a",
                "analyst": "michael",
                "note": "bagus",
                "updated_at": "2026-04-28T00:39:53.581246",
            },
        ],
        "threatintel/groups": [
            {"name": "shinyhunters", "added_date": "2024-03-25", "source": "malpedia"},
            {"name": "apt36", "added_date": "2024-03-25", "source": "malpedia"},
            {"name": "APT36", "source": "manual"},  # beda kapital -> dianggap sama
            {"name": "  "},
        ],
        "threatintel/apac-people": [{"name": "Australian"}, {"name": "Indonesian"}],
        "news_db/ioc_allowlist": [
            {"type": "ip", "value": "127.0.0.1", "added_by": "admin"},
            {"type": "url_domain", "value": "wiz.io", "added_by": "admin"},
        ],
        "news_db/users": [
            {
                "username": "jane",
                "role": "admin",
                "hashed_password": "$2b$12$SECRETHASH",
                "client_ids": ["default"],
                "last_sign_in": "2026-09-16T06:22:03",
            },
            {"username": "root", "role": "superadmin", "hashed_password": "$2b$12$OTHERHASH"},
        ],
    }


def dump() -> MemoryDump:
    return MemoryDump(dump_data())


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# --- pemetaan -----------------------------------------------------------------------


def test_seed_maps_every_table(db_session: Session) -> None:
    results = seed.seed_all(db_session, dump())

    assert {name: (t.inserted, t.existing) for name, t in results.items()} == {
        "clients": (2, 0),
        "roles": (1, 0),
        "techstack_entries": (2, 0),
        "monitored_accounts": (1, 0),
        "ta_profiles": (1, 0),
        "ta_watchlist": (1, 0),
        "ta_whitelist": (1, 0),
        "source_reliability_entries": (1, 0),
        "pir_requirements": (2, 0),
        "pir_notes": (1, 0),
        "threat_actor_groups": (2, 1),
        "monitored_people": (2, 0),
        "ioc_allowlist_entries": (2, 0),
    }

    groups = {g.name: g for g in db_session.scalars(select(ThreatActorGroup))}
    assert set(groups) == {"shinyhunters", "apt36"}
    assert groups["shinyhunters"].source == "malpedia"
    # added_date lama -> created_at: recap harian gak boleh nganggap ini "TA baru hari ini"
    assert groups["shinyhunters"].created_at == datetime.datetime(2024, 3, 25, tzinfo=datetime.UTC)
    assert count(db_session, MonitoredPerson) == 2
    assert (
        db_session.scalars(
            select(IocAllowlistEntry.added_by).where(IocAllowlistEntry.value == "wiz.io")
        ).one()
        == "admin"
    )

    countries = {
        cid: sorted(
            c
            for (c,) in db_session.execute(
                select(ClientCountry.country_code).where(ClientCountry.client_id == cid)
            ).all()
        )
        for cid in ("default", "privy")
    }
    assert countries == {"default": ["ID"], "privy": ["AU", "ID"]}  # nama -> ISO alpha-2

    # dokumen techstack lama tanpa client_id jatuh ke `default`
    ts = {(e.name, e.client_id) for e in db_session.scalars(select(TechStackEntry))}
    assert ts == {("anydesk", "default"), ("splunk", "privy")}

    profile = db_session.scalars(select(TAProfile)).one()
    assert profile.actor_name == "apt36"
    assert set(profile.profile) == {"identity", "motivation"}  # meta app lama gak ikut
    assert profile.generated_at == datetime.datetime(2026, 5, 4, 0, 53, 36, tzinfo=datetime.UTC)

    assert db_session.scalars(select(TAWhitelistEntry.name)).one() == "testactor"  # lowercase
    assert db_session.scalars(select(TAWatchlistEntry.client_id)).one() == "default"
    assert db_session.scalars(select(MonitoredAccount.created_at)).one() == datetime.datetime(
        2026, 5, 12, 14, 16, 35, tzinfo=datetime.UTC
    )
    assert db_session.get(Client, "default").created_at == datetime.datetime(
        2026, 5, 14, 18, 35, 15, 228876, tzinfo=datetime.UTC
    )


def test_pir_notes_attach_to_the_right_pir_even_when_titles_collide(db_session: Session) -> None:
    seed.seed_all(db_session, dump())

    pirs = {p.owner: p for p in db_session.scalars(select(PIRRequirement))}
    assert len(pirs) == 2  # dua PIR berjudul sama TIDAK saling menimpa
    note = db_session.scalars(select(PIRNote)).one()
    assert note.pir_id == pirs["Michael"].id  # catatan milik PIR kedua, bukan yang pertama
    assert pirs["Michael"].start_date == datetime.date(2026, 5, 4)
    assert set(pirs["Michael"].criteria) == {
        "threat_actors",
        "industries",
        "countries",
        "news_types",
        "keywords",
        "ttps",
    }


def test_pir_criteria_countries_are_stored_as_codes(db_session: Session) -> None:
    data = dump_data()
    data["news_db/pir_requirements"][0]["criteria"]["countries"] = ["Indonesia", "MY"]

    seed.seed_all(db_session, MemoryDump(data))

    first = db_session.scalars(select(PIRRequirement).order_by(PIRRequirement.created_at)).first()
    assert first is not None and first.criteria["countries"] == ["ID", "MY"]


# --- idempoten & gak nimpa ----------------------------------------------------------


def test_running_twice_creates_no_duplicates(db_session: Session) -> None:
    seed.seed_all(db_session, dump())
    before = {
        m.__name__: count(db_session, m)
        for m in (PIRRequirement, PIRNote, TechStackEntry, ClientCountry)
    }

    second = seed.seed_all(db_session, dump())

    assert all(t.inserted == 0 for t in second.values())
    assert second["clients"].existing == 2 and second["pir_requirements"].existing == 2
    assert second["pir_notes"].existing == 1
    assert before == {
        m.__name__: count(db_session, m)
        for m in (PIRRequirement, PIRNote, TechStackEntry, ClientCountry)
    }


def test_existing_rows_are_left_alone(db_session: Session) -> None:
    """Perubahan yang sudah dibikin di UI baru gak boleh ketimpa seed ulang."""
    db_session.add(Client(client_id="default", name="Nama Custom"))
    db_session.flush()
    db_session.add(TechStackEntry(name="anydesk", client_id="default", exposure="internet-facing"))
    db_session.flush()

    seed.seed_all(db_session, dump())

    assert db_session.get(Client, "default").name == "Nama Custom"
    kept = db_session.scalars(select(TechStackEntry).where(TechStackEntry.name == "anydesk")).one()
    assert kept.exposure == "internet-facing"


def test_default_client_made_by_api_bootstrap_still_gets_its_countries(db_session: Session) -> None:
    """API bikin `default` tanpa negara pas start -- seed harus tetap nambahin."""
    db_session.add(Client(client_id="default", name="Default"))
    db_session.flush()

    seed.seed_all(db_session, dump())

    db_session.expire_all()
    assert [c.country_code for c in db_session.get(Client, "default").countries] == ["ID"]


# --- gagal dengan jelas ------------------------------------------------------------------


def test_unknown_country_name_aborts_instead_of_guessing(db_session: Session) -> None:
    bad = MemoryDump(
        {"news_db/clients": [{"client_id": "x", "name": "X", "countries": ["Atlantis"]}]}
    )

    with pytest.raises(seed.SeedError, match="Atlantis"):
        seed.seed_all(db_session, bad)


def test_techstack_for_unknown_client_aborts(db_session: Session) -> None:
    bad = MemoryDump(
        {
            "news_db/clients": [{"client_id": "default", "name": "Default"}],
            "threatintel/techstack": [{"name": "nginx", "client_id": "ghost"}],
        }
    )

    with pytest.raises(seed.SeedError, match="ghost"):
        seed.seed_all(db_session, bad)


# --- role & user ---------------------------------------------------------------------------


def test_role_drift_between_code_and_old_production_is_reported(db_session: Session) -> None:
    from cti_api.services.roles import SYSTEM_ROLES

    same = list(SYSTEM_ROLES["analyst"]["permissions"])  # type: ignore[arg-type]
    diverged = [p for p in same if p != "manage_pir"] + ["manage_users"]
    ok = MemoryDump(
        {
            "news_db/roles": [
                {
                    "name": "analyst",
                    "display_name": "Analyst",
                    "permissions": same,
                    "is_system": True,
                }
            ]
        }
    )
    drift = MemoryDump(
        {
            "news_db/roles": [
                {
                    "name": "analyst",
                    "display_name": "Analyst",
                    "permissions": diverged,
                    "is_system": True,
                }
            ]
        }
    )

    assert seed.seed_roles(db_session, ok.docs("news_db/roles")).notes == []
    notes = seed.seed_roles(db_session, drift.docs("news_db/roles")).notes  # baris sudah ada
    assert (
        len(notes) == 1
        and "DRIFT" in notes[0]
        and "manage_pir" in notes[0]
        and "manage_users" in notes[0]
    )


def test_legacy_users_are_listed_without_password_hashes() -> None:
    users = seed.legacy_users(dump())

    assert [(u["username"], u["role"], u["clients"]) for u in users] == [
        ("jane", "admin", ["default"]),
        ("root", "superadmin", ["default"]),  # tanpa client_ids -> default
    ]
    assert "HASH" not in repr(users)


def test_roles_seed_inserts_missing_custom_role(db_session: Session) -> None:
    seed.seed_all(db_session, dump())

    role = db_session.get(Role, "custom-ops")
    assert role is not None and role.permissions == ["view_news"] and role.is_system is False


# --- dump ASLI (kalau ada) ---------------------------------------------------------------------

REAL_DUMP = pathlib.Path(__file__).resolve().parents[2] / "legacy" / "dump"


@pytest.mark.skipif(not REAL_DUMP.is_dir(), reason="legacy/dump tidak ada di checkout ini")
def test_real_dump_seeds_the_documented_counts(db_session: Session) -> None:
    pytest.importorskip("bson", reason="butuh `uv run --with pymongo`")

    results = seed.seed_all(db_session, DirDump(REAL_DUMP))

    assert {n: t.inserted for n, t in results.items()} == {
        "clients": 2,
        "roles": 3,
        "techstack_entries": 33,
        "monitored_accounts": 18,
        "ta_profiles": 2,
        "ta_watchlist": 2,
        "ta_whitelist": 2,
        "source_reliability_entries": 2,
        "pir_requirements": 3,
        "pir_notes": 3,
        "threat_actor_groups": 3991,
        "monitored_people": 30,
        "ioc_allowlist_entries": 9,
    }
    assert results["roles"].notes == []  # izin peran di kode == produksi lama
    assert count(db_session, ClientCountry) == 3  # default:ID + privy:AU,ID
