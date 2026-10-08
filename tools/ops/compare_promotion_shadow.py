#!/usr/bin/env python3
"""Bandingkan hasil promosi bayangan dengan `cve_tracker` hasil `new_cve` (ROADMAP #19 irisan 4,
`docs/CVE_CATALOG_DESIGN.md` 8.4). Hanya BACA.

Per (CVE, client) terbit sejak `--since`:
  - **sama**: ada di bayangan dan tracker dengan tech yang sama.
  - **tech beda**: keduanya ada, tech berbeda (bayangan = entri paling spesifik).
  - **hanya bayangan**: pipeline mirror akan membuatnya, `new_cve` tidak. Inilah yang kelewat
    keyword search, ATAU riwayat yang terbit sebelum tech/tracker itu ada (jalankan dengan
    `--since` = tanggal `new_cve` mulai berjalan untuk memisahkan keduanya).
  - **hanya tracker**: `new_cve` membuatnya, bayangan tidak, dengan SEBAB: tidak ada di mirror
    (di luar jendela), MIRROR BASI (terbit pada/setelah record mirror terbaru: ingest belum jalan
    atau clone backfill lebih tua dari CVE itu), entri nonaktif/hilang, entri bertarget yang tidak
    cocok CVE-nya (target salah atau kurang), atau entri teks yang gate-nya tak cocok di mirror.

False positive per client disembunyikan seperti tab CVEs (`--include-fp` menampilkannya).

Prasyarat: bayangan sudah terisi (`tools/ops/promote_cve_mirror.py --mode shadow --apply` untuk
riwayat; mode `shadow` di ingest untuk yang baru). Tanpa itu semuanya "hanya tracker".

    uv run python tools/ops/compare_promotion_shadow.py --since 2026-09-01 --csv /tmp/cmp.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from cti_core.cve_promotion import SPEC_LABELS, load_entries
from cti_core.db.engine import sync_session
from cti_core.db.models.cve import CveFalsePositive, CveTracker
from cti_core.db.models.cve_mirror import CvePromotionShadow, CveRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

Key = tuple[str, str]  # (cve_id, client_id)

REASON_NOT_IN_MIRROR = "tidak ada di mirror"
REASON_MIRROR_STALE = "terbit pada/setelah record mirror terbaru (mirror basi?)"
REASON_ENTRY_GONE = "entri nonaktif/hilang"
REASON_TARGET_MISS = "entri bertarget tidak cocok CVE"
REASON_TEXT_MISS = "gate teks tidak cocok di mirror"


@dataclass
class Comparison:
    same: list[Key] = field(default_factory=list)
    tech_differs: list[tuple[Key, str, str, str]] = field(default_factory=list)
    """(kunci, tech tracker, tech bayangan, kekhususan bayangan)"""
    only_shadow: list[tuple[Key, str, str]] = field(default_factory=list)
    """(kunci, tech bayangan, kekhususan)"""
    only_tracker: list[tuple[Key, str, str]] = field(default_factory=list)
    """(kunci, tech tracker, sebab)"""

    @property
    def total(self) -> int:
        return (
            len(self.same) + len(self.tech_differs) + len(self.only_shadow) + len(self.only_tracker)
        )


def compare(
    session: Session,
    *,
    since: datetime.date,
    client_id: str | None = None,
    include_fp: bool = False,
) -> Comparison:
    tracker_q = select(
        CveTracker.cve_id, CveTracker.client_id, CveTracker.tech, CveTracker.published
    ).where(CveTracker.published >= since)
    shadow_q = select(
        CvePromotionShadow.cve_id,
        CvePromotionShadow.client_id,
        CvePromotionShadow.tech,
        CvePromotionShadow.specificity,
    ).where(CvePromotionShadow.published_date >= since)
    if client_id is not None:
        tracker_q = tracker_q.where(CveTracker.client_id == client_id)
        shadow_q = shadow_q.where(CvePromotionShadow.client_id == client_id)

    fp: set[Key] = set()
    if not include_fp:
        fp = {
            (c, cl)
            for c, cl in session.execute(
                select(CveFalsePositive.cve_id, CveFalsePositive.client_id)
            )
        }
    published: dict[Key, datetime.date | None] = {}
    tracker: dict[Key, str] = {}
    for c, cl, t, pub in session.execute(tracker_q):
        if (c, cl) not in fp:
            tracker[(c, cl)] = t or ""
            published[(c, cl)] = pub
    mirror_latest = session.scalar(select(func.max(CveRecord.published_date)))
    shadow = {(c, cl): (t, s) for c, cl, t, s in session.execute(shadow_q) if (c, cl) not in fp}

    in_mirror = {c for (c,) in session.execute(select(CveRecord.cve_id))}
    entries = {(e.client_id, e.name.lower()): e for e in load_entries(session, client_id=client_id)}
    out = Comparison()
    for key in sorted(set(tracker) | set(shadow)):
        in_t, in_s = key in tracker, key in shadow
        if in_t and in_s:
            if tracker[key].lower() == shadow[key][0].lower():
                out.same.append(key)
            else:
                out.tech_differs.append((key, tracker[key], shadow[key][0], shadow[key][1]))
        elif in_s:
            out.only_shadow.append((key, shadow[key][0], shadow[key][1]))
        else:
            cve_id, cl = key
            entry = entries.get((cl, tracker[key].lower()))
            if cve_id not in in_mirror:
                pub = published[key]
                stale = pub is not None and (mirror_latest is None or pub >= mirror_latest)
                reason = REASON_MIRROR_STALE if stale else REASON_NOT_IN_MIRROR
            elif entry is None:  # `load_entries` hanya memuat entri aktif
                reason = REASON_ENTRY_GONE
            elif entry.has_targets:
                reason = REASON_TARGET_MISS
            else:
                reason = REASON_TEXT_MISS
            out.only_tracker.append((key, tracker[key], reason))
    return out


def render(c: Comparison, *, since: datetime.date, examples: int = 10) -> str:
    def pct(n: int) -> str:
        return f"{100 * n / c.total:.1f}%" if c.total else "-"

    o = [
        f"# Bayangan vs tracker (terbit >= {since})",
        "",
        f"(CVE, client) dibandingkan: {c.total}",
        f"- sama               : {len(c.same)} ({pct(len(c.same))})",
        f"- tech beda          : {len(c.tech_differs)} ({pct(len(c.tech_differs))})",
        f"- hanya bayangan     : {len(c.only_shadow)} ({pct(len(c.only_shadow))})",
        f"- hanya tracker      : {len(c.only_tracker)} ({pct(len(c.only_tracker))})",
    ]
    if c.only_tracker:
        o += ["", "## Hanya tracker, menurut sebab"]
        reasons = Counter(r for _, _, r in c.only_tracker)
        o += [f"- {r}: {n}" for r, n in reasons.most_common()]
        by_tech: dict[str, Counter[str]] = defaultdict(Counter)
        for _, tech, reason in c.only_tracker:
            by_tech[tech][reason] += 1
        o += ["", "Per tech (jumlah, sebab terbanyak):"]
        for tech, reasons_t in sorted(by_tech.items(), key=lambda kv: -sum(kv[1].values())):
            top, _ = reasons_t.most_common(1)[0]
            o.append(f"- {tech or '(kosong)'}: {sum(reasons_t.values())} ({top})")
        o += ["", f"Contoh (maks {examples}):"]
        o += [f"- {k[0]} / {k[1]}: {t} -- {r}" for k, t, r in c.only_tracker[:examples]]
    if c.only_shadow:
        o += ["", "## Hanya bayangan, per tech"]
        per = Counter(t for _, t, _ in c.only_shadow)
        o += [f"- {t}: {n}" for t, n in per.most_common()]
        spec = Counter(s for _, _, s in c.only_shadow)
        o.append("Kekhususan: " + ", ".join(f"{k}={v}" for k, v in sorted(spec.items())))
        o += ["", f"Contoh (maks {examples}):"]
        o += [f"- {k[0]} / {k[1]}: {t} ({s})" for k, t, s in c.only_shadow[:examples]]
    if c.tech_differs:
        o += ["", "## Tech beda"]
        pairs = Counter((a, b) for _, a, b, _ in c.tech_differs)
        o += [f"- tracker `{a}` -> bayangan `{b}`: {n}" for (a, b), n in pairs.most_common(15)]
    o += ["", f"Kekhususan yang dikenal: {', '.join(SPEC_LABELS.values())}."]
    return "\n".join(o)


def write_csv(c: Comparison, path: Path) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["kategori", "cve_id", "client_id", "tech_tracker", "tech_bayangan", "keterangan"]
        )
        for k in c.same:
            w.writerow(["sama", *k, "", "", ""])
        for k, t, s, spec in c.tech_differs:
            w.writerow(["tech_beda", *k, t, s, spec])
        for k, s, spec in c.only_shadow:
            w.writerow(["hanya_bayangan", *k, "", s, spec])
        for k, t, reason in c.only_tracker:
            w.writerow(["hanya_tracker", *k, t, "", reason])


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("--since", type=datetime.date.fromisoformat, required=True)
    ap.add_argument("--client", default=None)
    ap.add_argument("--include-fp", action="store_true")
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--examples", type=int, default=10)
    args = ap.parse_args(argv)
    with sync_session() as session:
        result = compare(
            session, since=args.since, client_id=args.client, include_fp=args.include_fp
        )
    if result.total == 0:
        print(
            "Tidak ada baris untuk dibandingkan (bayangan dan tracker kosong sejak tanggal itu). "
            "Isi bayangan dulu: promote_cve_mirror.py --mode shadow --apply.",
            file=sys.stderr,
        )
        return 4
    print(render(result, since=args.since, examples=args.examples))
    if args.csv:
        write_csv(result, args.csv)
        print(f"\nCSV: {args.csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
