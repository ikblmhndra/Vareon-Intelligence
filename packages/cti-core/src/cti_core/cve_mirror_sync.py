"""Ingest mirror CVE dari CVE List V5 (ROADMAP #19, irisan 3; `docs/CVE_CATALOG_DESIGN.md` 5).

`sync_once` dipanggil tugas `cve.mirror_sync` tiap ~5 menit: baca `cves/delta.json` (jendela fetch
TERAKHIR CVE List V5: `fetchTime`, `new[]`, `updated[]`), unduh tiap berkas record, parse dengan
`cti_core.cve_record` (parser yang sama dengan `new_cve`), resolve produknya ke katalog, simpan ke
mirror (`CveMirrorRepo.upsert`). Jaringan DISUNTIK (`Fetcher`), jadi seluruh jalur dites tanpa
internet; implementasi httpx ada di tugas worker.

Yang dijaga di sini, semuanya pernah jadi lubang di rancangan awal:

- **Kursor di DB** (`job_state["cve_mirror.state"]`): `fetch_time` terakhir yang diproses +
  `polled_at` (kapan poll sukses terakhir). Hanya bergerak maju SETELAH batch selesai; sebelum itu
  mengulang tidak berbahaya karena upsert idempoten dan menolak record yang lebih lama.
- **Celah**: `delta.json` hanya menyimpan satu jendela, jadi worker yang mati melewatkan jendela
  yang sudah ditimpa. Dua pemicu catch-up lewat `deltaLog.json` (24 MB, 30 hari, jarang dibaca):
  poll sukses terakhir lebih tua dari `POLL_GAP` (kita sendiri yang tahu pernah telat), atau
  `fetchTime` baru terlalu jauh dari kursor (`FETCH_GAP`; selang fetch yang teramati maks 62 menit).
  Bila kursor lebih tua dari entri tertua log, laporan menandai `gap_unrecoverable`: yang tersisa
  hanya backfill (`tools/ops/backfill_cve_mirror.py`).
- **Kegagalan satu berkas tidak menghentikan batch**: CVE-nya masuk `pending` di state dan dicoba
  lagi siklus berikut (maks `MAX_ATTEMPTS`, lalu dibuang dengan log). Kelebihan di atas
  `max_files` juga masuk `pending` tanpa menambah percobaan, jadi kursor tetap boleh maju.
- **Hanya tautan CVE List V5** yang diunduh: isi `githubLink` datang dari jaringan, jadi host dan
  jalurnya divalidasi (bukan SSRF ke alamat sembarang).
- **Record yang tidak PUBLISHED** (REJECTED) dibuang dari mirror; record tanpa tanggal terbit, atau
  yang terbit sebelum batas retensi, tidak disimpan (akan langsung terpangkas).
- Tiap CVE diproses dalam savepoint: error DB satu record tidak menggugurkan batch (cache katalog
  dibuang sesudah rollback).

Sengaja BELUM ada di sini: promosi ke `cve_tracker` (irisan 4).
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from cti_core.catalog_resolve import resolve_all
from cti_core.cve_promotion import (
    EntryView,
    Mode,
    forget_shadow,
    load_entries,
    promote_record,
)
from cti_core.cve_record import (
    STATE_PUBLISHED,
    cna_summary,
    cve_state,
    mitre_datetime,
    parse_cve_record,
)
from cti_core.db.models.cve_mirror import CveRecord
from cti_core.db.repositories.catalog import (
    CatalogRepo,
    CveMirrorRepo,
    MirrorRecord,
    retention_cutoff,
)
from cti_core.db.repositories.report_state import JobStateRepo

log = structlog.get_logger()

BASE_URL = "https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves"
DELTA_URL = f"{BASE_URL}/delta.json"
DELTA_LOG_URL = f"{BASE_URL}/deltaLog.json"
RECORD_URL_PREFIX = "https://raw.githubusercontent.com/CVEProject/cvelistV5/"
NVD_LINK = "https://nvd.nist.gov/vuln/detail/{}"
STATE_KEY = "cve_mirror.state"

POLL_GAP = datetime.timedelta(minutes=12)
"""Poll sukses terakhir lebih tua dari ini = kita telat >= 2 tick (jadwal 5 menit): catch-up."""
FETCH_GAP = datetime.timedelta(minutes=90)
"""`fetchTime` baru melompat lebih jauh dari ini dari kursor = jendela di antaranya hilang."""
MAX_ATTEMPTS = 6
DEFAULT_MAX_FILES = 3000
COMMIT_EVERY = 200

LOCK_KEY = 7_203_104_511
"""Kunci advisory Postgres: satu `sync_once` sekaligus (tick beat yang menumpuk setelah worker
pulih, atau pemicu manual, tidak boleh berebut insert katalog/mirror)."""

_RE_CVE_ID = re.compile(r"^CVE-\d{4}-\d{4,}$")

Fetcher = Callable[[str], bytes]
"""`url -> isi`; melempar `FetchError` bila gagal."""


class FetchError(Exception):
    """Pengambilan satu URL gagal (jaringan, status non-200, isi rusak)."""


@dataclass(frozen=True)
class DeltaItem:
    cve_id: str
    link: str
    date_updated: datetime.datetime | None


@dataclass(frozen=True)
class DeltaEntry:
    fetch_time: datetime.datetime
    items: tuple[DeltaItem, ...]
    """`new[]` + `updated[]`, satu per CVE (yang `dateUpdated`-nya terbaru)."""


def _parse_items(raw: Any) -> Iterable[DeltaItem]:
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        cve_id, link = item.get("cveId"), item.get("githubLink")
        if isinstance(cve_id, str) and isinstance(link, str):
            updated = item.get("dateUpdated")
            yield DeltaItem(
                cve_id=cve_id,
                link=link,
                date_updated=mitre_datetime(updated if isinstance(updated, str) else None),
            )


def _dedupe(items: Iterable[DeltaItem]) -> tuple[DeltaItem, ...]:
    latest: dict[str, DeltaItem] = {}
    for item in items:
        kept = latest.get(item.cve_id)
        if kept is None or _ts(item) >= _ts(kept):
            latest[item.cve_id] = item
    return tuple(latest.values())


def _ts(item: DeltaItem) -> datetime.datetime:
    return item.date_updated or datetime.datetime.min.replace(tzinfo=datetime.UTC)


def parse_delta_entry(raw: Any) -> DeltaEntry:
    """Satu jendela fetch (bentuk `delta.json`, dan tiap elemen `deltaLog.json`)."""
    if not isinstance(raw, dict):
        raise FetchError("delta bukan objek JSON")
    fetch_time = mitre_datetime(
        raw.get("fetchTime") if isinstance(raw.get("fetchTime"), str) else None
    )
    if fetch_time is None:
        raise FetchError("delta tanpa fetchTime yang terbaca")
    items = [*_parse_items(raw.get("new")), *_parse_items(raw.get("updated"))]
    return DeltaEntry(fetch_time=fetch_time, items=_dedupe(items))


def parse_delta_log(raw: Any) -> list[DeltaEntry]:
    """`deltaLog.json` (array, terbaru dulu) -> entri terurut dari yang TERLAMA. Elemen rusak
    dilewati; log yang bukan array = `FetchError`."""
    if not isinstance(raw, list):
        raise FetchError("deltaLog bukan array JSON")
    entries: list[DeltaEntry] = []
    for element in raw:
        try:
            entries.append(parse_delta_entry(element))
        except FetchError:
            continue
    return sorted(entries, key=lambda e: e.fetch_time)


def _load_json(blob: bytes) -> Any:
    try:
        return json.loads(blob)
    except ValueError as e:
        raise FetchError(f"bukan JSON: {e}") from e


# ── state ─────────────────────────────────────────────────────────────────────────────────────


@dataclass
class PendingItem:
    cve_id: str
    link: str
    attempts: int = 0


@dataclass
class SyncState:
    fetch_time: datetime.datetime | None = None
    polled_at: datetime.datetime | None = None
    pending: list[PendingItem] = field(default_factory=list)

    def dump(self) -> dict[str, Any]:
        return {
            "fetch_time": self.fetch_time.isoformat() if self.fetch_time else None,
            "polled_at": self.polled_at.isoformat() if self.polled_at else None,
            "pending": [
                {"cve_id": p.cve_id, "link": p.link, "attempts": p.attempts} for p in self.pending
            ],
        }

    @classmethod
    def load(cls, raw: Any) -> SyncState:
        if not isinstance(raw, dict):
            return cls()

        def when(key: str) -> datetime.datetime | None:
            value = raw.get(key)
            if not isinstance(value, str):
                return None
            try:
                parsed = datetime.datetime.fromisoformat(value)
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)

        pending = [
            PendingItem(str(p["cve_id"]), str(p["link"]), int(p.get("attempts", 0)))
            for p in raw.get("pending", [])
            if isinstance(p, dict) and "cve_id" in p and "link" in p
        ]
        return cls(fetch_time=when("fetch_time"), polled_at=when("polled_at"), pending=pending)


def needs_catch_up(state: SyncState, fetch_time: datetime.datetime, now: datetime.datetime) -> bool:
    """Ada alasan percaya jendela di antara kursor dan `fetch_time` hilang? Tanpa kursor (run
    pertama) TIDAK: riwayat adalah urusan backfill, bukan `deltaLog`."""
    if state.fetch_time is None or fetch_time <= state.fetch_time:
        return False
    if state.polled_at is not None and now - state.polled_at > POLL_GAP:
        return True
    return fetch_time - state.fetch_time > FETCH_GAP


# ── satu record ───────────────────────────────────────────────────────────────────────────────

Outcome = Literal["created", "updated", "stale", "removed", "skipped"]


def valid_record_link(link: str) -> bool:
    return link.startswith(RECORD_URL_PREFIX) and link.endswith(".json") and ".." not in link


def apply_record(
    repo: CveMirrorRepo,
    data: Mapping[str, Any],
    *,
    cve_id: str,
    today: datetime.date,
    aliases: Mapping[str, str] | None = None,
) -> tuple[Outcome, str]:
    """Satu record CVE JSON 5.x -> mirror. Balikin (hasil, alasan-bila-dilewati)."""
    record: dict[str, Any] = dict(data)
    if cve_state(record) != STATE_PUBLISHED:
        existing = repo.get(cve_id)
        if existing is None:
            return "skipped", "bukan PUBLISHED"
        repo.session.execute(delete(CveRecord).where(CveRecord.cve_id == cve_id))
        repo.session.expire_all()
        return "removed", ""

    detail = parse_cve_record(
        record, cve_id=cve_id, link=NVD_LINK.format(cve_id), summary=cna_summary(record)
    )
    published = detail.fields["published"]
    if published is None:
        return "skipped", "tanpa tanggal terbit"
    if published < retention_cutoff(today):
        return "skipped", "di luar retensi"

    meta = record.get("cveMetadata", {})
    modified = mitre_datetime(meta.get("dateUpdated")) or detail.fields["published_at"]
    severity = detail.fields["cve_severity"]
    score = detail.fields["cve_score"]
    mirror = MirrorRecord(
        cve_id=cve_id,
        published_date=published,
        published_at=detail.fields["published_at"],
        modified_at=modified,
        summary=detail.fields["summary"],
        link=detail.fields["link"],
        solutions=detail.fields["solutions"],
        cvss_score=None if severity is None and not score else float(score),
        cvss_severity=severity,
        cvss_vector=detail.fields["cvss_vector"] or None,
        reference_urls=detail.fields["references"],
        affected_lines=detail.fields["affected"],
    )
    resolved = resolve_all(detail.affected_entries, aliases=aliases)
    result = repo.upsert(mirror, resolved)
    if result.skipped_stale:
        return "stale", ""
    return ("created" if result.created else "updated"), ""


# ── satu siklus ───────────────────────────────────────────────────────────────────────────────


@dataclass
class SyncReport:
    status: Literal["ok", "noop", "error", "locked"] = "ok"
    error: str = ""
    caught_up: bool = False
    gap_unrecoverable: bool = False
    fetch_time: datetime.datetime | None = None
    created: int = 0
    updated: int = 0
    stale: int = 0
    removed: int = 0
    skipped: int = 0
    failed: int = 0
    dropped: int = 0
    pending: int = 0
    promoted_new: int = 0
    """Baris `cve_tracker` BARU dari promosi `live`."""
    promoted_updated: int = 0
    shadow_rows: int = 0
    """Baris `cve_promotion_shadow` yang dievaluasi (mode `shadow`)."""

    def as_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k != "fetch_time"}
        out["fetch_time"] = self.fetch_time.isoformat() if self.fetch_time else None
        return out


def _entries_to_process(
    state: SyncState, latest: DeltaEntry, fetch: Fetcher, now: datetime.datetime, report: SyncReport
) -> list[DeltaEntry]:
    if not needs_catch_up(state, latest.fetch_time, now):
        return [latest]
    assert state.fetch_time is not None
    log_entries = parse_delta_log(_load_json(fetch(DELTA_LOG_URL)))
    report.caught_up = True
    if not log_entries or state.fetch_time < log_entries[0].fetch_time:
        report.gap_unrecoverable = True
        log.error(
            "cve_mirror_gap_unrecoverable",
            cursor=state.fetch_time.isoformat(),
            oldest_log=log_entries[0].fetch_time.isoformat() if log_entries else None,
        )
    newer = [e for e in log_entries if e.fetch_time > state.fetch_time]
    if all(e.fetch_time != latest.fetch_time for e in newer):
        newer.append(latest)  # log di CDN bisa tertinggal dari delta.json
    return sorted(newer, key=lambda e: e.fetch_time)


def sync_once(
    session: Session,
    fetch: Fetcher,
    now: datetime.datetime,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    promote: Mode = "off",
) -> SyncReport:
    """Satu siklus ingest. Tidak melempar untuk kegagalan jaringan: dilaporkan di `status="error"`
    dan state TIDAK berubah (siklus berikut mengulang). Siklus lain yang masih berjalan ->
    `status="locked"` (tidak melakukan apa pun)."""
    # Kunci tingkat SESI (bukan `_xact_`): `COMMIT_EVERY` meng-commit di tengah batch.
    if not session.scalar(select(func.pg_try_advisory_lock(LOCK_KEY))):
        return SyncReport(status="locked")
    try:
        return _sync_locked(session, fetch, now, max_files, promote)
    finally:
        try:
            session.execute(select(func.pg_advisory_unlock(LOCK_KEY)))
        except Exception:  # sesi sudah rusak: kunci lepas saat koneksinya ditutup
            log.warning("cve_mirror_unlock_failed")


def _sync_locked(
    session: Session, fetch: Fetcher, now: datetime.datetime, max_files: int, promote: Mode
) -> SyncReport:
    report = SyncReport()
    states = JobStateRepo(session)
    state = SyncState.load(states.get(STATE_KEY))
    try:
        latest = parse_delta_entry(_load_json(fetch(DELTA_URL)))
        entries = _entries_to_process(state, latest, fetch, now, report)
    except FetchError as e:
        report.status, report.error = "error", str(e)
        log.warning("cve_mirror_delta_failed", error=str(e))
        return report

    report.fetch_time = latest.fetch_time
    fresh = state.fetch_time is None or latest.fetch_time > state.fetch_time
    work: dict[str, PendingItem] = {p.cve_id: p for p in state.pending}
    if fresh:
        for entry in entries:
            for delta_item in entry.items:
                prior = work.get(delta_item.cve_id)
                work[delta_item.cve_id] = PendingItem(
                    delta_item.cve_id, delta_item.link, prior.attempts if prior else 0
                )
    else:
        report.status = "noop"

    catalog = CatalogRepo(session)
    repo = CveMirrorRepo(session, catalog)
    aliases = catalog.alias_map()
    today = now.date()
    tech_entries: list[EntryView] = load_entries(session) if promote != "off" else []
    queue = list(work.values())
    carry: list[PendingItem] = queue[max_files:]
    retry: list[PendingItem] = []

    for done, item in enumerate(queue[:max_files], start=1):
        try:
            _process(session, repo, fetch, item, today, aliases, report, promote, tech_entries)
        except Exception as e:  # FetchError, record janggal, error DB: batch jalan terus
            _record_failure(repo, item, e, retry, report)
        if done % COMMIT_EVERY == 0:
            session.commit()

    state.pending = [*retry, *carry]
    report.pending = len(state.pending)
    if fresh:
        state.fetch_time = latest.fetch_time
    state.polled_at = now
    states.set(STATE_KEY, state.dump())
    log.info("cve_mirror_synced", **report.as_dict())
    return report


def _process(
    session: Session,
    repo: CveMirrorRepo,
    fetch: Fetcher,
    item: PendingItem,
    today: datetime.date,
    aliases: Mapping[str, str],
    report: SyncReport,
    promote: Mode = "off",
    entries: Sequence[EntryView] = (),
) -> None:
    if not _RE_CVE_ID.match(item.cve_id) or not valid_record_link(item.link):
        report.skipped += 1
        log.warning("cve_mirror_bad_item", cve_id=item.cve_id, link=item.link[:120])
        return
    data = _load_json(fetch(item.link))
    if not isinstance(data, dict):
        raise FetchError("record bukan objek JSON")
    with session.begin_nested():
        outcome, reason = apply_record(repo, data, cve_id=item.cve_id, today=today, aliases=aliases)
        # Promosi di savepoint YANG SAMA: gagal = record ikut dicoba ulang, tak setengah jadi.
        if promote != "off":
            if outcome in ("created", "updated"):
                rec = repo.get(item.cve_id)
                if rec is not None:
                    done = promote_record(session, rec, entries, promote)
                    report.promoted_new += done.created
                    report.promoted_updated += done.updated
                    report.shadow_rows += done.shadow
            elif outcome == "removed":
                forget_shadow(session, item.cve_id)
    if outcome == "skipped":
        log.info("cve_mirror_record_skipped", cve_id=item.cve_id, reason=reason)
    setattr(report, outcome, getattr(report, outcome) + 1)


def _record_failure(
    repo: CveMirrorRepo,
    item: PendingItem,
    error: Exception,
    retry: list[PendingItem],
    report: SyncReport,
) -> None:
    repo.catalog.reset_cache()
    item.attempts += 1
    if item.attempts >= MAX_ATTEMPTS:
        report.dropped += 1
        log.error("cve_mirror_record_dropped", cve_id=item.cve_id, error=str(error)[:300])
        return
    report.failed += 1
    retry.append(item)
    log.warning(
        "cve_mirror_record_failed",
        cve_id=item.cve_id,
        attempts=item.attempts,
        error=str(error)[:300],
    )


def purge_expired(session: Session, today: datetime.date) -> int:
    """Retensi harian: buang CVE terbit sebelum batas tahun kalender (`retention_cutoff`)."""
    deleted = CveMirrorRepo(session).purge_expired(today)
    log.info("cve_mirror_purged", deleted=deleted, cutoff=retention_cutoff(today).isoformat())
    return deleted
