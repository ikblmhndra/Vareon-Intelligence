"""Seed data referensi buat cutover (Fase 10.C) dari dump Mongo produksi lama.

Beda dari `fase5_reference_data.py` (3 tabel referensi threat/IOC dari arsip
Fase 5): ini data yang DIKURASI manusia di web lama dan wajib ada sebelum
platform baru dipakai -- tanpa `techstack` pipeline CVE mati total, tanpa
`monitored_accounts` scraper X gak punya target.

    clients            -> clients + client_countries   (nama negara -> ISO alpha-2)
    roles              -> roles                        (cuma yang belum ada; lihat catatan)
    threatintel.techstack        -> techstack_entries
    news_db.monitored_accounts   -> monitored_accounts
    threatintel.ta_profiles      -> ta_profiles
    threatintel.ta_watchlist     -> ta_watchlist
    threatintel.whitelist        -> ta_whitelist
    threatintel.source_scores    -> source_reliability_entries
    news_db.pir_requirements     -> pir_requirements
    news_db.pir_notes            -> pir_notes            (pir_id ObjectId -> id baru)
    threatintel.groups           -> threat_actor_groups  (kamus regex TA, ~4000 nama)
    threatintel.apac-people      -> monitored_people
    news_db.ioc_allowlist        -> ioc_allowlist_entries

Tiga tabel terakhir dulu cuma ada di `fase5_reference_data.py` (dijalankan
sekali di DB dev, Fase 5) dan gak pernah masuk runbook cutover -- staging
yang dibangun dari nol jadinya gak punya `threat_actor_groups` sama sekali,
`stages/score.py` gak bisa nemu threat actor apa pun (QA 2026-10-01: 0 dari
325 artikel, dropdown TA kosong, PIR berbasis TA selalu 0 match). Sekarang
ikut di sini; artikel yang telanjur masuk dibetulkan
`python -m cti_enrich.backfill`.

TIDAK dimigrasi: `users`. Hash bcrypt lama sengaja gak dibawa -- user dibikin
ulang lewat UI dengan password baru (keputusan Fase 10). Script ini cuma
NGEPRINT daftar user lama (username/role/client) sebagai daftar kerja.

Idempoten: tiap tabel punya identitas alami (lihat fungsi `seed_*`), dijalankan
ulang gak bikin baris dobel dan gak nimpa perubahan yang sudah dibuat di UI
baru -- baris yang sudah ada dilewati, bukan di-update.

    uv run --with pymongo python tools/seed/fase10_reference_data.py --dry-run
    uv run --with pymongo python tools/seed/fase10_reference_data.py

`--dry-run` jalanin semuanya lalu rollback: buat ngecek dump + nama negara
sebelum nulis apa pun.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cti_core.db.engine import sync_session
from cti_core.db.models.auth import Client, ClientCountry, Role
from cti_core.db.models.entity import Entity, EntityProfile, EntityWatch
from cti_core.db.models.ioc_reference import IocAllowlistEntry
from cti_core.db.models.pir import _EMPTY_CRITERIA, PIRNote, PIRRequirement
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.models.techstack import TechStackEntry
from cti_core.db.models.threat_reference import MonitoredPerson, ThreatActorGroup
from cti_core.db.models.tweet import MonitoredAccount
from cti_core.entity.merge import set_suppressed
from cti_core.entity.resolve import resolve
from cti_enrich.countries import country_code
from sqlalchemy import func, select
from sqlalchemy.orm import Session

if __package__ in (None, ""):  # dijalankan sebagai skrip: `python tools/seed/...`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.seed._dump import DEFAULT_DUMP_DIR, DirDump, Dump, DumpError

DEFAULT_CLIENT = "default"
"""Dokumen lama tanpa `client_id` (era sebelum multi-tenant v3.8.0) milik client ini."""


class SeedError(RuntimeError):
    """Data dump gak bisa dipetakan dengan aman -- berhenti, jangan nebak."""


@dataclass
class Tally:
    inserted: int = 0
    existing: int = 0
    notes: list[str] = field(default_factory=list)


# --- parsing --------------------------------------------------------------------


def _dt(value: Any) -> datetime.datetime | None:
    """Timestamp dump (ISO string naif atau `datetime` BSON) -> aware UTC.
    Yang naif dianggap UTC, sama kayak app lama (`datetime.utcnow()`)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, datetime.date):
        parsed = datetime.datetime.combine(value, datetime.time())
    else:
        parsed = datetime.datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)


def _date(value: Any) -> datetime.date | None:
    parsed = _dt(value)
    return parsed.date() if parsed else None


def _to_country_code(name: str, *, where: str) -> str:
    name = name.strip()
    if len(name) == 2 and name.isalpha():
        return name.upper()  # sudah kode
    code = country_code(name)
    if code is None:
        raise SeedError(f"{where}: nama negara '{name}' gak dikenali -- betulkan di dump/alias")
    return code


def _country_codes(names: list[str], *, where: str) -> list[str]:
    return list(dict.fromkeys(_to_country_code(n, where=where) for n in names))


# --- seed per tabel -----------------------------------------------------------------


def seed_clients(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: `client_id`. Client yang sudah ada dilewati, TAPI negara yang
    belum tercatat ditambahkan (client `default` selalu ada duluan karena
    dibikin API pas start, tanpa negara)."""
    tally = Tally()
    for doc in docs:
        cid = doc["client_id"]
        codes = _country_codes(doc.get("countries") or [], where=f"client '{cid}'")
        client = session.get(Client, cid)
        if client is None:
            client = Client(client_id=cid, name=doc.get("name") or cid)
            if created := _dt(doc.get("created_at")):
                client.created_at = created
            session.add(client)
            session.flush()
            tally.inserted += 1
        else:
            tally.existing += 1
        have = {c.country_code for c in client.countries}
        for code in codes:
            if code not in have:
                session.add(ClientCountry(client_id=cid, country_code=code))
                tally.notes.append(f"client '{cid}': +negara {code}")
    session.flush()
    return tally


def _code_roles() -> dict[str, set[str]]:
    """Peran sistem versi KODE (`cti_api.services.roles`), buat deteksi drift.
    Best-effort: kalau `cti_api` gak terpasang, cek drift dilewati."""
    try:
        from cti_api.services.roles import SYSTEM_ROLES
    except ImportError:
        return {}
    return {name: set(spec["permissions"]) for name, spec in SYSTEM_ROLES.items()}  # type: ignore[call-overload]


def seed_roles(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: `name`. Role yang belum ada di-insert dari dump; yang sudah ada
    dilewati. Role SISTEM (superadmin/admin/analyst) sebenarnya dibikin API dari
    kode pas start dan menimpa isinya -- jadi yang penting di sini bukan
    insert-nya, tapi DRIFT: apakah izin di kode sama dengan izin di produksi
    lama? Beda = user lama diam-diam dapat hak akses yang berbeda."""
    tally = Tally()
    code_roles = _code_roles()
    if not code_roles:
        tally.notes.append("cek drift izin DILEWATI (paket cti_api tidak terpasang di sini)")
    for doc in docs:
        name = doc["name"]
        perms = list(doc.get("permissions") or [])
        row = session.get(Role, name)
        if row is None:
            row = Role(
                name=name,
                display_name=doc.get("display_name") or name,
                permissions=perms,
                is_system=bool(doc.get("is_system")),
                created_by=doc.get("created_by") or "system",
            )
            if created := _dt(doc.get("created_at")):
                row.created_at = created
            session.add(row)
            tally.inserted += 1
        else:
            tally.existing += 1
        code = code_roles.get(name)
        if code is not None and code != set(perms):
            added, removed = sorted(code - set(perms)), sorted(set(perms) - code)
            tally.notes.append(
                f"DRIFT role '{name}': kode +{added or '[]'} / produksi-lama +{removed or '[]'}"
            )
    session.flush()
    return tally


def _require_client(session: Session, client_id: str, *, where: str) -> None:
    if session.get(Client, client_id) is None:
        raise SeedError(f"{where}: client '{client_id}' belum ada (seed_clients harus duluan)")


def seed_techstack(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: (`name`, `client_id`) -- sama dengan unique constraint tabelnya."""
    tally = Tally()
    have = {
        (n, c) for n, c in session.execute(select(TechStackEntry.name, TechStackEntry.client_id))
    }
    for doc in docs:
        name = (doc.get("name") or "").strip()
        client_id = doc.get("client_id") or DEFAULT_CLIENT
        if not name:
            continue
        if (name, client_id) in have:
            tally.existing += 1
            continue
        _require_client(session, client_id, where=f"techstack '{name}'")
        session.add(
            TechStackEntry(
                name=name,
                client_id=client_id,
                exposure=doc.get("exposure"),
                hosting_type=doc.get("hosting_type"),
                source=doc.get("source"),
                added_date=_date(doc.get("added_date")),
            )
        )
        have.add((name, client_id))
        tally.inserted += 1
    session.flush()
    return tally


def seed_monitored_accounts(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: `username`."""
    tally = Tally()
    have = set(session.execute(select(MonitoredAccount.username)).scalars())
    for doc in docs:
        username = (doc.get("username") or "").strip()
        if not username:
            continue
        if username in have:
            tally.existing += 1
            continue
        row = MonitoredAccount(
            username=username,
            active=bool(doc.get("active", True)),
            display_name=doc.get("display_name") or "",
            notes=doc.get("notes") or "",
        )
        if added := _dt(doc.get("added_at")):
            row.created_at = added
        session.add(row)
        have.add(username)
        tally.inserted += 1
    session.flush()
    return tally


# Kunci meta buatan app lama yang BUKAN bagian JSON profil dari LLM.
_TA_PROFILE_META = {"_id", "_actor_name", "_generated_at"}


def _actor(session: Session, name: str) -> Entity:
    """Aktor lewat resolver (P7c): nama lama yang alias entitas lain menempel ke entitas itu."""
    return resolve(session, "intrusion-set", name, source="legacy")


def seed_ta_profiles(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: entitas aktor (`entity_profiles`, satu profil per entitas; P7c)."""
    tally = Tally()
    for doc in docs:
        name = (doc.get("_actor_name") or "").strip()
        if not name:
            continue
        entity = _actor(session, name)
        if session.scalar(select(EntityProfile.id).where(EntityProfile.entity_id == entity.id)):
            tally.existing += 1
            continue
        row = EntityProfile(
            entity_id=entity.id,
            profile={k: v for k, v in doc.items() if k not in _TA_PROFILE_META},
        )
        if generated := _dt(doc.get("_generated_at")):
            row.generated_at = generated
        session.add(row)
        session.flush()
        tally.inserted += 1
    return tally


def seed_ta_watchlist(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: (entitas aktor, `client_id`) di `entity_watches` (P7c)."""
    tally = Tally()
    for doc in docs:
        name = (doc.get("name") or "").strip()
        client_id = doc.get("client_id") or DEFAULT_CLIENT
        if not name:
            continue
        _require_client(session, client_id, where=f"ta_watchlist '{name}'")
        entity = _actor(session, name)
        if session.scalar(
            select(EntityWatch.id).where(
                EntityWatch.entity_id == entity.id, EntityWatch.client_id == client_id
            )
        ):
            tally.existing += 1
            continue
        row = EntityWatch(entity_id=entity.id, client_id=client_id)
        if added := _dt(doc.get("added_date")):
            row.created_at = added
        session.add(row)
        session.flush()
        tally.inserted += 1
    return tally


def seed_ta_whitelist(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Whitelist lama = entitas aktor `suppressed` (P7c): tidak pernah dicocokkan. `added_date`
    lama tidak punya kolom padanan (jejaknya baris audit `entity_suppress`)."""
    tally = Tally()
    for doc in docs:
        name = (doc.get("name") or "").strip()
        if not name:
            continue
        entity = _actor(session, name)
        if entity.suppressed:
            tally.existing += 1
            continue
        set_suppressed(session, entity.id, True, actor="system:seed")
        tally.inserted += 1
    return tally


def seed_source_scores(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: `source_name` case-insensitive (aturan repository-nya)."""
    tally = Tally()
    have = {
        n.lower() for n in session.execute(select(SourceReliabilityEntry.source_name)).scalars()
    }
    for doc in docs:
        name = (doc.get("source_name") or "").strip()
        if not name:
            continue
        if name.lower() in have:
            tally.existing += 1
            continue
        added = _date(doc.get("added_date")) or datetime.datetime.now(datetime.UTC).date()
        session.add(
            SourceReliabilityEntry(
                source_name=name,
                analyst_name=doc.get("analyst_name") or "",
                reliability_grade=doc["reliability_grade"],
                credibility_code=doc["credibility_code"],
                admiralty_code=doc.get("admiralty_code")
                or f"{doc['reliability_grade']}{doc['credibility_code']}",
                notes=doc.get("notes") or "",
                added_date=added,
                last_updated=_date(doc.get("last_updated")) or added,
            )
        )
        have.add(name.lower())
        tally.inserted += 1
    session.flush()
    return tally


def seed_threat_actor_groups(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: `name` case-insensitive (`AsyncTARepo.get_by_name_ci`; unique
    constraint DB cuma di `name` mentah). Nama disimpan apa adanya (dump sudah
    lowercase). `added_date` lama jadi `created_at` -- WAJIB: recap harian
    (`list_added_on`) baca `created_at::date` sebagai "TA baru hari ini";
    tanpa ini ~4000 grup muncul sebagai TA baru di hari seed."""
    tally = Tally()
    have = {n.lower() for n in session.execute(select(ThreatActorGroup.name)).scalars()}
    for doc in docs:
        name = (doc.get("name") or "").strip()
        if not name:
            continue
        if name.lower() in have:
            tally.existing += 1
            continue
        row = ThreatActorGroup(name=name, source=(doc.get("source") or "manual")[:50])
        if added := _dt(doc.get("added_date")):
            row.created_at = added
        session.add(row)
        have.add(name.lower())
        tally.inserted += 1
    session.flush()
    return tally


def seed_monitored_people(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: `name`. Isinya demonym (`Australian`, ...), bukan nama orang --
    lihat `fase5_reference_data.py`."""
    tally = Tally()
    have = set(session.execute(select(MonitoredPerson.name)).scalars())
    for doc in docs:
        name = (doc.get("name") or "").strip()
        if not name:
            continue
        if name in have:
            tally.existing += 1
            continue
        session.add(MonitoredPerson(name=name))
        have.add(name)
        tally.inserted += 1
    session.flush()
    return tally


def seed_ioc_allowlist(session: Session, docs: list[dict[str, Any]]) -> Tally:
    """Identitas: (`type`, `value`)."""
    tally = Tally()
    have = set(session.execute(select(IocAllowlistEntry.type, IocAllowlistEntry.value)).tuples())
    for doc in docs:
        type_ = (doc.get("type") or "").strip()
        value = (doc.get("value") or "").strip()
        if not type_ or not value:
            continue
        if (type_, value) in have:
            tally.existing += 1
            continue
        row = IocAllowlistEntry(type=type_, value=value, added_by=doc.get("added_by") or "system")
        if added := _dt(doc.get("added_at")):
            row.created_at = added
        session.add(row)
        have.add((type_, value))
        tally.inserted += 1
    session.flush()
    return tally


def _criteria(raw: dict[str, Any] | None, *, where: str) -> dict[str, list[str]]:
    """Kriteria PIR: semua kunci yang model minta selalu ada; `countries`
    disimpan sebagai KODE (artikel baru nyimpan negara sebagai ISO alpha-2)."""
    raw = raw or {}
    out = {key: list(raw.get(key) or []) for key in _EMPTY_CRITERIA}
    out["countries"] = _country_codes(out["countries"], where=where)
    return out


def seed_pir(
    session: Session, req_docs: list[dict[str, Any]], note_docs: list[dict[str, Any]]
) -> tuple[Tally, Tally]:
    """PIR: identitas (`title`, `created_at` asli) -- judul saja gak cukup,
    dump punya dua PIR berjudul sama. Catatan: (`pir_id` baru, `url`)."""
    reqs, notes = Tally(), Tally()
    have = {
        (title, created): pid
        for pid, title, created in session.execute(
            select(PIRRequirement.id, PIRRequirement.title, PIRRequirement.created_at)
        ).all()
    }
    new_id_by_mongo_id: dict[str, int] = {}
    for doc in req_docs:
        title = (doc.get("title") or "").strip()
        client_id = doc.get("client_id") or DEFAULT_CLIENT
        created = _dt(doc.get("created_at"))
        if not title:
            continue
        existing_id = have.get((title, created))
        if existing_id is not None:
            reqs.existing += 1
            new_id_by_mongo_id[str(doc["_id"])] = existing_id
            continue
        _require_client(session, client_id, where=f"pir '{title}'")
        row = PIRRequirement(
            title=title,
            description=doc.get("description") or "",
            priority=doc.get("priority") or "P2",
            owner=doc.get("owner") or "",
            status=doc.get("status") or "active",
            criteria=_criteria(doc.get("criteria"), where=f"pir '{title}'"),
            start_date=_date(doc.get("start_date")),
            end_date=_date(doc.get("end_date")),
            client_id=client_id,
        )
        if created:
            row.created_at = created
        if updated := _dt(doc.get("updated_at")):
            row.updated_at = updated
        session.add(row)
        session.flush()
        new_id_by_mongo_id[str(doc["_id"])] = row.id
        have[(title, created)] = row.id
        reqs.inserted += 1

    have_notes = {(pid, u) for pid, u in session.execute(select(PIRNote.pir_id, PIRNote.url))}
    for doc in note_docs:
        pir_id = new_id_by_mongo_id.get(str(doc.get("pir_id")))
        url = doc.get("url") or ""
        if pir_id is None:
            notes.notes.append(f"catatan dilewati: PIR {doc.get('pir_id')} gak ada di dump")
            continue
        if not url:
            continue
        if (pir_id, url) in have_notes:
            notes.existing += 1
            continue
        row_note = PIRNote(
            pir_id=pir_id, url=url, note=doc.get("note") or "", analyst=doc.get("analyst") or ""
        )
        if updated := _dt(doc.get("updated_at")):
            row_note.updated_at = updated
        session.add(row_note)
        have_notes.add((pir_id, url))
        notes.inserted += 1
    session.flush()
    return reqs, notes


# --- orkestrasi -------------------------------------------------------------------------


def seed_all(session: Session, dump: Dump) -> dict[str, Tally]:
    """Urutan penting: `clients` duluan (FK dari techstack/watchlist/PIR)."""
    results: dict[str, Tally] = {}
    results["clients"] = seed_clients(session, dump.docs("news_db/clients"))
    results["roles"] = seed_roles(session, dump.docs("news_db/roles"))
    results["techstack_entries"] = seed_techstack(session, dump.docs("threatintel/techstack"))
    results["monitored_accounts"] = seed_monitored_accounts(
        session, dump.docs("news_db/monitored_accounts")
    )
    results["ta_profiles"] = seed_ta_profiles(session, dump.docs("threatintel/ta_profiles"))
    results["ta_watchlist"] = seed_ta_watchlist(session, dump.docs("threatintel/ta_watchlist"))
    results["ta_whitelist"] = seed_ta_whitelist(session, dump.docs("threatintel/whitelist"))
    results["source_reliability_entries"] = seed_source_scores(
        session, dump.docs("threatintel/source_scores")
    )
    results["pir_requirements"], results["pir_notes"] = seed_pir(
        session, dump.docs("news_db/pir_requirements"), dump.docs("news_db/pir_notes")
    )
    results["threat_actor_groups"] = seed_threat_actor_groups(
        session, dump.docs("threatintel/groups")
    )
    results["monitored_people"] = seed_monitored_people(
        session, dump.docs("threatintel/apac-people")
    )
    results["ioc_allowlist_entries"] = seed_ioc_allowlist(
        session, dump.docs("news_db/ioc_allowlist")
    )
    return results


def legacy_users(dump: Dump) -> list[dict[str, Any]]:
    """User lama buat DIBIKIN ULANG lewat UI -- tanpa hash password."""
    return [
        {
            "username": d.get("username"),
            "role": d.get("role"),
            "clients": d.get("client_ids") or [DEFAULT_CLIENT],
            "last_sign_in": str(d.get("last_sign_in") or "-")[:10],
        }
        for d in dump.docs("news_db/users")
    ]


def row_counts(session: Session) -> dict[str, int]:
    models = {
        "clients": Client,
        "roles": Role,
        "techstack_entries": TechStackEntry,
        "monitored_accounts": MonitoredAccount,
        "ta_profiles": EntityProfile,  # label lama, tabel P7c
        "ta_watchlist": EntityWatch,
        "source_reliability_entries": SourceReliabilityEntry,
        "pir_requirements": PIRRequirement,
        "pir_notes": PIRNote,
        "threat_actor_groups": ThreatActorGroup,
        "monitored_people": MonitoredPerson,
        "ioc_allowlist_entries": IocAllowlistEntry,
    }
    counts = {
        name: session.scalar(select(func.count()).select_from(m)) or 0 for name, m in models.items()
    }
    counts["ta_whitelist"] = (
        session.scalar(
            select(func.count())
            .select_from(Entity)
            .where(
                Entity.type == "intrusion-set", Entity.suppressed, Entity.merged_into_id.is_(None)
            )
        )
        or 0
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--dump-dir", type=Path, default=DEFAULT_DUMP_DIR)
    ap.add_argument("--dry-run", action="store_true", help="jalankan semua lalu rollback")
    args = ap.parse_args(argv)

    dump = DirDump(args.dump_dir)
    try:
        with sync_session() as session:
            results = seed_all(session, dump)
            counts = row_counts(session)
            if args.dry_run:
                session.rollback()
    except (SeedError, DumpError) as e:
        print(f"GAGAL, tidak ada yang ditulis: {e}", file=sys.stderr)
        return 1

    mode = "DRY-RUN (di-rollback)" if args.dry_run else "DITULIS"
    print(f"== seed data referensi -- {mode} -- dump: {args.dump_dir}")
    print(f"{'tabel':30} {'baru':>6} {'sudah ada':>10} {'total di DB':>12}")
    for name, tally in results.items():
        print(f"{name:30} {tally.inserted:>6} {tally.existing:>10} {counts[name]:>12}")
    for name, tally in results.items():
        for note in tally.notes:
            print(f"  [{name}] {note}")

    try:
        users = legacy_users(dump)
    except DumpError as e:  # mis. `users.bson` sengaja gak diupload ke staging (isinya hash)
        print(f"\n(daftar user lama dilewati: {e})")
        return 0
    print(f"\n== {len(users)} user lama -- BUAT ULANG lewat UI (password baru, hash lama dibuang)")
    for u in users:
        clients, last = ",".join(u["clients"]), u["last_sign_in"]
        print(f"  {u['username']:22} role={u['role']:11} client={clients}  (login {last})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
