"""Tulis ulang nama threat actor historis dari bentuk alias ke nama kanonik ATT&CK (sekali jalan).

Sebelum P4 (0.8.8) nama aktor disimpan sebagai alias yang cocok, di-`capitalize()` ("Midnight
blizzard"); sejak P4 Tier 1 menyimpan nama kanonik ("Apt29"). Tanpa perintah ini satu aktor
tampil sebagai dua seri di dashboard/leaderboard/tren/profil TA/PIR dan filter `threat_actor`.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field

from cti_core.db.models.article import ArticleThreatActor
from cti_core.db.models.pir import PIRRequirement
from cti_core.db.models.ta import TAProfile, TAWatchlistEntry
from cti_core.db.repositories.threat_reference import load_entity_sources
from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_enrich.backfill_tier1 import canonical_actor_name
from cti_enrich.tier1.dictionary import EntityDictionary, build_dictionary


def _target(name: str, dictionary: EntityDictionary) -> str | None:
    """Nama kanonik bila `name` alias; None bila tidak ada perubahan. Beda huruf besar saja bukan
    alias: semua pencocokan nama aktor (filter, watchlist, profil, PIR) case-insensitive."""
    canonical = canonical_actor_name(name, dictionary)
    if canonical is None or canonical.lower() == name.lower():
        return None
    return canonical


def canonicalise_name_list(names: list[str], dictionary: EntityDictionary) -> list[str]:
    """Ganti alias di daftar nama (kriteria PIR), buang duplikat case-insensitive, urutan tetap."""
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        new = _target(name, dictionary) or name
        if new.lower() not in seen:
            seen.add(new.lower())
            out.append(new)
    return out


@dataclass
class Changes:
    renamed: Counter[tuple[str, str]] = field(default_factory=Counter)
    """(lama, baru) -> jumlah baris yang namanya diganti."""
    merged: Counter[tuple[str, str]] = field(default_factory=Counter)
    """(lama, baru) -> jumlah baris alias yang dibuang karena nama kanonik sudah ada."""


@dataclass
class CanonicaliseStats:
    articles: Changes = field(default_factory=Changes)
    watchlist: Changes = field(default_factory=Changes)
    profiles: Changes = field(default_factory=Changes)
    pir: Changes = field(default_factory=Changes)
    dropped_profiles: list[str] = field(default_factory=list)
    """`actor_name` profil yang dihapus karena kalah dari profil yang lebih baru."""


def _articles(session: Session, d: EntityDictionary, changes: Changes) -> None:
    rows = session.execute(
        select(ArticleThreatActor).order_by(ArticleThreatActor.article_id, ArticleThreatActor.id)
    ).scalars()
    present: dict[int, set[str]] = {}
    pending: list[tuple[ArticleThreatActor, str]] = []
    for row in rows:
        present.setdefault(row.article_id, set()).add(row.threat_actor.lower())
        new = _target(row.threat_actor, d)
        if new is not None:
            pending.append((row, new))
    # Dua lintasan: nama kanonik yang sudah ada di artikel harus diketahui dulu, apa pun urutan
    # barisnya. Tidak pernah rename ke nama yang sudah ada -> unique (article_id, threat_actor)
    # aman walau UPDATE di-flush sebelum DELETE.
    for row, new in pending:
        names = present[row.article_id]
        if new.lower() in names:
            session.delete(row)
            changes.merged[(row.threat_actor, new)] += 1
        else:
            names.add(new.lower())
            changes.renamed[(row.threat_actor, new)] += 1
            row.threat_actor = new


def _watchlist(session: Session, d: EntityDictionary, changes: Changes) -> None:
    rows = list(
        session.execute(
            select(TAWatchlistEntry).order_by(TAWatchlistEntry.client_id, TAWatchlistEntry.id)
        ).scalars()
    )
    present: dict[str, set[str]] = {}
    for row in rows:
        present.setdefault(row.client_id, set()).add(row.name.lower())
    for row in rows:
        new = _target(row.name, d)
        if new is None:
            continue
        names = present[row.client_id]
        if new.lower() in names:
            session.delete(row)
            changes.merged[(row.name, new)] += 1
        else:
            names.add(new.lower())
            changes.renamed[(row.name, new)] += 1
            row.name = new


def _profiles(session: Session, d: EntityDictionary, stats: CanonicaliseStats) -> None:
    """Profil dikelompokkan per nama kanonik (case-insensitive, seperti `get_profile`); kelompok
    yang berisi alias disisakan satu: `generated_at` terbaru menang, sisanya dihapus."""
    groups: dict[str, list[TAProfile]] = {}
    for p in session.execute(select(TAProfile).order_by(TAProfile.id)).scalars():
        groups.setdefault((_target(p.actor_name, d) or p.actor_name).lower(), []).append(p)
    renames: list[tuple[TAProfile, str]] = []
    for members in groups.values():
        if all(_target(p.actor_name, d) is None for p in members):
            continue
        winner = max(members, key=lambda p: (p.generated_at, p.id))
        for p in members:
            if p is not winner:
                stats.dropped_profiles.append(p.actor_name)
                session.delete(p)
        new = _target(winner.actor_name, d)
        if new is not None:
            renames.append((winner, new))
    # `actor_name` unique: profil yang kalah harus terhapus sebelum pemenang mengambil namanya.
    session.flush()
    for p, new in renames:
        stats.profiles.renamed[(p.actor_name, new)] += 1
        p.actor_name = new


def _pir(session: Session, d: EntityDictionary, changes: Changes) -> None:
    for pir in session.execute(select(PIRRequirement).order_by(PIRRequirement.id)).scalars():
        names = list(pir.criteria.get("threat_actors") or [])
        new_names = canonicalise_name_list(names, d)
        if new_names == names:
            continue
        lowered = {n.lower() for n in names}
        for name in names:
            new = _target(name, d)
            if new is None:
                continue
            if new.lower() in lowered:
                changes.merged[(name, new)] += 1
            else:
                lowered.add(new.lower())
                changes.renamed[(name, new)] += 1
        # Dict baru (bukan mutasi di tempat) supaya kolom JSONB terdeteksi berubah.
        pir.criteria = {**pir.criteria, "threat_actors": new_names}


def canonicalise_actors(session: Session, *, dry_run: bool) -> CanonicaliseStats:
    """Satu transaksi untuk semua tabel (datanya kecil: prod 2026-10-25 = 7 baris artikel):
    rollback bila `dry_run`, commit bila tidak. Kamus dibangun segar dari DB, bukan cache
    `get_dictionary`, supaya gagal baca DB = error, bukan kamus kosong yang diam-diam tidak
    mengubah apa pun."""
    d = build_dictionary(*load_entity_sources(session))
    stats = CanonicaliseStats()
    _articles(session, d, stats.articles)
    _watchlist(session, d, stats.watchlist)
    _profiles(session, d, stats)
    _pir(session, d, stats.pir)
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return stats


def _print_changes(label: str, changes: Changes) -> None:
    print(
        f"{label}: {sum(changes.renamed.values())} diganti, {sum(changes.merged.values())} digabung"
    )
    for (old, new), n in sorted(changes.renamed.items()):
        print(f"  rename  {old!r} -> {new!r}: {n}")
    for (old, new), n in sorted(changes.merged.items()):
        print(f"  gabung  {old!r} -> {new!r}: {n}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument(
        "--apply", action="store_true", help="tulis perubahan (default: dry-run, di-rollback)"
    )
    args = ap.parse_args(argv)

    from cti_core.db.engine import sync_session

    with sync_session() as session:
        stats = canonicalise_actors(session, dry_run=not args.apply)

    print(f"== kanonikalisasi nama aktor -- {'DITULIS' if args.apply else 'DRY-RUN (di-rollback)'}")
    _print_changes("article_threat_actors", stats.articles)
    _print_changes("ta_watchlist", stats.watchlist)
    _print_changes("ta_profiles", stats.profiles)
    for name in stats.dropped_profiles:
        print(f"  hapus profil {name!r} (kalah dari profil yang lebih baru)")
    _print_changes("pir_requirements", stats.pir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
