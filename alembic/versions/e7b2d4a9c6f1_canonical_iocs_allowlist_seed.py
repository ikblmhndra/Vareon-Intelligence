"""IOC lama ke bentuk kanonik (merge kembaran), kanonik `threat_feed_entries`, seed allowlist,
dan tandai IOC yang cocok allowlist (rilis 0.8.6, spec P2 cheap wins 3.3 dan 3.4)

1. `canonicalize_and_merge`: tiap baris `iocs` dihitung nilai kanoniknya; baris dengan
   `(type, nilai kanonik)` sama digabung ke `id` terkecil. `ioc_sources` dipindah semua,
   `ioc_tags`/`ioc_threat_actors` dipindah lewat `ON CONFLICT DO NOTHING` (pasangan yang sudah
   dimiliki penyintas dibuang), `ioc_feedback` (tanpa unique constraint) dipindah kecuali
   penyintas sudah punya feedback analis yang sama dengan verdict yang sama. `seen/tp/fp_count`
   dijumlah, `first_seen_at` minimum, `last_seen_at` maksimum, `enrichment` milik penyintas atau
   yang pertama tidak kosong, suppression penyintas (atau suppression kembaran pertama kalau
   penyintas belum tersuppress, supaya keputusan FP analis tidak hilang). Kolom lain (confidence,
   actionability) tetap milik penyintas. Baris kalah dihapus (sisa tautannya ikut cascade),
   BARU sesudah itu nilai penyintas diganti ke bentuk kanonik -- unique `(type, value)` tidak
   pernah dilanggar karena nilai kanonik idempoten.
2. `canonicalize_threat_feed`: nilai `threat_feed_entries` (dedup sink deepdarkCTI, yang kini
   menulis nilai kanonik) dikanonikkan dengan aturan yang sama; duplikat per `(feed, type,
   value)` dibuang, `id` terkecil bertahan.
3. `seed_and_flag_allowlist`: domain seed dimasukkan ke `ioc_allowlist_entries` sebagai
   `url_domain` dengan `added_by='seed'` (yang sudah ada dilewati), lalu IOC yang belum
   tersuppress dan cocok allowlist (seed + entri analis) ditandai `auto_suppressed` dengan alasan
   `allowlist:<tipe>:<entri> (infrastructure-abuse)`. Idempoten.

Aturan kanonik dan allowlist di sini SALINAN BEKU `cti_core.ioc.canonical`
(`CANONICAL_RULES_VERSION = 1`) dan `cti_core.ioc.allowlist`, begitu juga daftar seed
(`allowlist_seed.txt`): migrasi tidak boleh ikut berubah kalau kode aplikasi berubah.
`tests/unit/test_canonical_ioc_migration_frozen.py` menjaga keduanya tetap sama selama versinya
sama.

Merge TIDAK bisa dibalik: downgrade tidak melakukan apa-apa (deploy mengambil backup Postgres
dulu).

Revision ID: e7b2d4a9c6f1
Revises: d1a5c8e3f2b7
Create Date: 2026-10-25 12:00:00.000000

"""

import logging
import re
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b2d4a9c6f1"
down_revision: str | None = "d1a5c8e3f2b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_log = logging.getLogger("alembic.runtime.migration")

# --- salinan beku cti_core.ioc.canonical (CANONICAL_RULES_VERSION = 1) -------------------------

CANONICAL_RULES_VERSION = 1

_RE_DOT = re.compile(
    r"\s*(?:\[\.\]|\[\.|\.  \]|\(\.\)|\{\.\}|\[dot\]|\(dot\)|\\.)\s*", re.IGNORECASE
)
_RE_DEFANG_AT = re.compile(r"\s*(?:\[@\]|\(@\)|\[at\]|\(at\))\s*", re.IGNORECASE)
_RE_DEFANG_COLON = re.compile(r"\[:\]")
_RE_URL_PARTS = re.compile(r"^([^/?#]*?)(?:\[:\]|:)//([^/?#]*)(.*)$", re.DOTALL)
_RE_HOST_PREFIX = re.compile(r"^([^/?#]*)(.*)$", re.DOTALL)
_HASH_TYPES = frozenset({"sha256", "sha1", "md5"})
_SCHEME_FIX = {"hxxp": "http", "hxxps": "https", "fxp": "ftp"}


def _refang_host(authority: str) -> str:
    userinfo, sep, host = authority.rpartition("@")
    host = _RE_DEFANG_COLON.sub(":", _RE_DOT.sub(".", host)).lower()
    return f"{userinfo}{sep}{host}"


def _canonical_url(value: str) -> str:
    v = value.strip()
    m = _RE_URL_PARTS.match(v)
    if m:
        scheme, authority, rest = m.groups()
        scheme = scheme.lower()
        scheme = _SCHEME_FIX.get(scheme, scheme)
        return f"{scheme}://{_refang_host(authority)}{rest}"
    authority, rest = _RE_HOST_PREFIX.match(v).groups()  # type: ignore[union-attr]
    return f"{_refang_host(authority)}{rest}"


def _canonical_once(ioc_type: str, value: str) -> str:
    if ioc_type == "ip":
        return _RE_DOT.sub(".", value).strip()
    if ioc_type == "domain":
        return _RE_DOT.sub(".", value).strip().lower().rstrip(".")
    if ioc_type == "url":
        return _canonical_url(value)
    if ioc_type == "email":
        return _RE_DOT.sub(".", _RE_DEFANG_AT.sub("@", value)).strip().lower()
    if ioc_type in _HASH_TYPES:
        return value.strip().lower()
    return value.strip()


_MAX_PASSES = 5


def canonical(ioc_type: str, value: str) -> str:
    """Ulang sampai titik tetap (defang bersarang `[[.]]` terkupas satu lapis per putaran)."""
    for _ in range(_MAX_PASSES):
        nxt = _canonical_once(ioc_type, value)
        if nxt == value:
            break
        value = nxt
    return value


# --- salinan beku cti_core.ioc.allowlist (+ helper extractor yang dipakainya) ------------------

_RE_EXTRACT_DOMAIN = re.compile(r"^(?:https?://)?([^/:?\s]+)")
_REASON_SUFFIX = "(infrastructure-abuse)"


def _url_domain(url: str) -> str:
    m = _RE_EXTRACT_DOMAIN.match(url.lower())
    return m.group(1) if m else ""


def _email_domain(email: str) -> str:
    parts = re.split(r"[@\[\(]at[\)\]]", email.lower())
    if len(parts) == 2:
        return parts[1].strip().lstrip("[").rstrip("]").strip()
    if "@" in email:
        return email.split("@", 1)[1].lower()
    return ""


def _suffix_hit(host: str, entries: set[str]) -> str | None:
    host = host.strip().lower().rstrip(".")
    if not host:
        return None
    labels = host.split(".")
    for i in range(len(labels)):
        candidate = ".".join(labels[i:])
        if candidate in entries:
            return candidate
    return None


def _is_bare_host_url(url: str) -> bool:
    rest = url.split("://", 1)[-1]
    _, sep, tail = rest.partition("/")
    if not sep:
        return "?" not in rest and "#" not in rest
    return tail == ""


def allowlist_match(
    ioc_type: str, canonical_value: str, allowlist: dict[str, set[str]]
) -> str | None:
    url_domains = allowlist.get("url_domains", set())
    if ioc_type == "domain":
        entry = _suffix_hit(canonical_value, url_domains)
        kind = "url_domain"
    elif ioc_type == "url":
        if not _is_bare_host_url(canonical_value):
            return None
        entry = _suffix_hit(_url_domain(canonical_value), url_domains)
        kind = "url_domain"
    elif ioc_type == "email":
        entry = _suffix_hit(_email_domain(canonical_value), allowlist.get("email_domains", set()))
        kind = "email_domain"
    elif ioc_type == "ip":
        entry = canonical_value if canonical_value in allowlist.get("ips", set()) else None
        kind = "ip"
    else:
        return None
    if entry is None:
        return None
    return f"allowlist:{kind}:{entry} {_REASON_SUFFIX}"


# --- salinan beku allowlist_seed.txt -----------------------------------------------------------

SEED_URL_DOMAINS: tuple[str, ...] = (
    "gofile.io",
    "ably.io",
    "mega.nz",
    "mega.io",
    "dropbox.com",
    "wetransfer.com",
    "we.tl",
    "transfer.sh",
    "file.io",
    "catbox.moe",
    "pixeldrain.com",
    "sendspace.com",
    "mediafire.com",
    "4shared.com",
    "pastebin.com",
    "paste.ee",
    "ghostbin.com",
    "hastebin.com",
    "rentry.co",
    "controlc.com",
    "justpaste.it",
    "telegra.ph",
    "imgur.com",
    "postimg.cc",
    "prnt.sc",
    "google.com",
    "gstatic.com",
    "goo.gl",
    "youtube.com",
    "youtu.be",
    "microsoft.com",
    "live.com",
    "office.com",
    "office365.com",
    "outlook.com",
    "onedrive.com",
    "microsoftonline.com",
    "apple.com",
    "icloud.com",
    "discord.com",
    "discord.gg",
    "discordapp.com",
    "telegram.org",
    "t.me",
    "atlassian.com",
    "trello.com",
    "asana.com",
    "hubspot.com",
    "mailchimp.com",
    "twilio.com",
    "stripe.com",
    "paypal.com",
    "docusign.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "whatsapp.com",
    "reddit.com",
    "wikipedia.org",
    "archive.org",
    "cloudflare.com",
    "cloudflare-dns.com",
    "jsdelivr.net",
    "cdnjs.com",
    "unpkg.com",
    "bootstrapcdn.com",
    "jquery.com",
    "amazon.com",
    "aws.amazon.com",
    "digitalocean.com",
    "vultr.com",
    "ovh.com",
    "hetzner.com",
    "heroku.com",
    "alibabacloud.com",
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "npmjs.com",
    "pypi.org",
    "pythonhosted.org",
    "rubygems.org",
    "crates.io",
    "docker.com",
    "docker.io",
    "ghcr.io",
    "quay.io",
    "maven.org",
    "nuget.org",
    "stackoverflow.com",
    "virustotal.com",
    "abuseipdb.com",
    "alienvault.com",
    "shodan.io",
    "censys.io",
    "urlscan.io",
    "any.run",
    "hybrid-analysis.com",
    "joesandbox.com",
    "abuse.ch",
    "mitre.org",
    "nist.gov",
    "cisa.gov",
    "us-cert.gov",
    "first.org",
    "cve.org",
    "exploit-db.com",
    "securityweek.com",
    "bleepingcomputer.com",
    "thehackernews.com",
    "krebsonsecurity.com",
    "crowdstrike.com",
    "paloaltonetworks.com",
    "fortinet.com",
    "mandiant.com",
    "trendmicro.com",
    "kaspersky.com",
    "sophos.com",
    "eset.com",
    "symantec.com",
    "checkpoint.com",
    "sentinelone.com",
)
SEED_NOTE = "seed 0.8.6: infrastruktur sah yang sering disalahgunakan"

# --- merge IOC ---------------------------------------------------------------------------------

# Angka, enrichment, dan suppression dihitung selagi baris kalah masih ada. `ids` = penyintas +
# baris kalah; penyintas punya id terkecil, jadi `ORDER BY id` mendahulukan miliknya.
_MERGE_COUNTS_SQL = sa.text(
    """
UPDATE iocs s SET
    seen_count = a.seen_count,
    tp_count = a.tp_count,
    fp_count = a.fp_count,
    first_seen_at = a.first_seen_at,
    last_seen_at = a.last_seen_at,
    enrichment = COALESCE(
        (SELECT e.enrichment FROM iocs e
         WHERE e.id = ANY(:ids)
           AND e.enrichment <> CAST('{}' AS jsonb) AND e.enrichment <> CAST('null' AS jsonb)
         ORDER BY e.id LIMIT 1),
        s.enrichment
    ),
    suppression_reason = CASE WHEN s.auto_suppressed THEN s.suppression_reason ELSE
        (SELECT x.suppression_reason FROM iocs x
         WHERE x.id = ANY(:ids) AND x.auto_suppressed ORDER BY x.id LIMIT 1) END,
    auto_suppressed = s.auto_suppressed OR a.any_suppressed
FROM (
    SELECT sum(seen_count) AS seen_count, sum(tp_count) AS tp_count, sum(fp_count) AS fp_count,
           min(first_seen_at) AS first_seen_at, max(last_seen_at) AS last_seen_at,
           bool_or(auto_suppressed) AS any_suppressed
    FROM iocs WHERE id = ANY(:ids)
) a
WHERE s.id = :survivor
"""
)
_MOVE_SOURCES_SQL = sa.text("UPDATE ioc_sources SET ioc_id = :survivor WHERE ioc_id = ANY(:losers)")
_MOVE_TAGS_SQL = sa.text(
    "INSERT INTO ioc_tags (ioc_id, tag)"
    " SELECT :survivor, tag FROM ioc_tags WHERE ioc_id = ANY(:losers) ORDER BY id"
    " ON CONFLICT DO NOTHING"
)
_MOVE_ACTORS_SQL = sa.text(
    "INSERT INTO ioc_threat_actors (ioc_id, threat_actor)"
    " SELECT :survivor, threat_actor FROM ioc_threat_actors WHERE ioc_id = ANY(:losers)"
    " ORDER BY id ON CONFLICT DO NOTHING"
)
# Tanpa unique constraint: per baris kalah, feedback pindah kecuali penyintas sudah punya
# feedback analis yang sama dengan verdict yang sama (riwayat di dalam satu baris tetap utuh).
_MOVE_FEEDBACK_SQL = sa.text(
    """
UPDATE ioc_feedback f SET ioc_id = :survivor
WHERE f.ioc_id = :loser AND NOT EXISTS (
    SELECT 1 FROM ioc_feedback g
    WHERE g.ioc_id = :survivor AND g.verdict = f.verdict AND g.submitted_by = f.submitted_by
)
"""
)
_DELETE_IOCS_SQL = sa.text("DELETE FROM iocs WHERE id = ANY(:losers)")


def _merge_into(conn: Connection, survivor: int, losers: list[int]) -> None:
    conn.execute(_MERGE_COUNTS_SQL, {"survivor": survivor, "ids": [survivor, *losers]})
    params = {"survivor": survivor, "losers": losers}
    conn.execute(_MOVE_SOURCES_SQL, params)
    conn.execute(_MOVE_TAGS_SQL, params)
    conn.execute(_MOVE_ACTORS_SQL, params)
    for loser in losers:
        conn.execute(_MOVE_FEEDBACK_SQL, {"survivor": survivor, "loser": loser})
    conn.execute(_DELETE_IOCS_SQL, params)


def canonicalize_and_merge(conn: Connection) -> dict[str, int]:
    """`merged` = baris kalah yang dihapus; `rewritten` = baris yang nilainya diganti."""
    groups: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for ioc_id, ioc_type, value in conn.execute(
        sa.text("SELECT id, type, value FROM iocs ORDER BY id")
    ):
        groups.setdefault((ioc_type, canonical(ioc_type, value)), []).append((ioc_id, value))

    merged = 0
    renames: list[dict[str, object]] = []
    for (_, canon), members in groups.items():
        survivor, survivor_value = members[0]
        losers = [ioc_id for ioc_id, _ in members[1:]]
        if losers:
            _merge_into(conn, survivor, losers)
            merged += len(losers)
        if survivor_value != canon:
            renames.append({"id": survivor, "value": canon})
    # Sesudah SEMUA baris kalah terhapus: nilai kanonik tiap kelompok kini bebas.
    if renames:
        conn.execute(sa.text("UPDATE iocs SET value = :value WHERE id = :id"), renames)
    return {"merged": merged, "rewritten": len(renames)}


def canonicalize_threat_feed(conn: Connection) -> dict[str, int]:
    """Sama untuk `threat_feed_entries` (unique `(feed, type, value)`); tanpa tabel tautan."""
    groups: dict[tuple[str, str, str], list[tuple[int, str]]] = {}
    for entry_id, feed, entry_type, value in conn.execute(
        sa.text("SELECT id, feed, type, value FROM threat_feed_entries ORDER BY id")
    ):
        key = (feed, entry_type, canonical(entry_type, value))
        groups.setdefault(key, []).append((entry_id, value))

    losers: list[int] = []
    renames: list[dict[str, object]] = []
    for (_, _, canon), members in groups.items():
        survivor, survivor_value = members[0]
        losers.extend(entry_id for entry_id, _ in members[1:])
        if survivor_value != canon:
            renames.append({"id": survivor, "value": canon})
    if losers:
        conn.execute(
            sa.text("DELETE FROM threat_feed_entries WHERE id = ANY(:ids)"), {"ids": losers}
        )
    if renames:
        conn.execute(
            sa.text("UPDATE threat_feed_entries SET value = :value WHERE id = :id"), renames
        )
    return {"merged": len(losers), "rewritten": len(renames)}


# --- seed + tandai allowlist -------------------------------------------------------------------

_SEED_SQL = sa.text(
    "INSERT INTO ioc_allowlist_entries (type, value, note, added_by)"
    " SELECT 'url_domain', v, :note, 'seed' FROM unnest(CAST(:values AS text[])) AS v"
    " ON CONFLICT (type, value) DO NOTHING"
)
_ALLOWLIST_KEY = {"url_domain": "url_domains", "email_domain": "email_domains", "ip": "ips"}


def _load_allowlist(conn: Connection) -> dict[str, set[str]]:
    """Bentuk yang sama dengan `get_ioc_allowlist()`: domain huruf kecil, IP apa adanya."""
    result: dict[str, set[str]] = {"url_domains": set(), "email_domains": set(), "ips": set()}
    for entry_type, value in conn.execute(sa.text("SELECT type, value FROM ioc_allowlist_entries")):
        key = _ALLOWLIST_KEY.get(entry_type)
        if key:
            result[key].add(value if key == "ips" else value.lower())
    return result


def seed_and_flag_allowlist(conn: Connection) -> dict[str, int]:
    """`seeded` = entri seed baru; `flagged` = IOC yang baru ditandai. Alasan yang sudah ada
    (IOC yang sudah tersuppress) tidak ditimpa."""
    seeded = conn.execute(_SEED_SQL, {"note": SEED_NOTE, "values": list(SEED_URL_DOMAINS)})
    allowlist = _load_allowlist(conn)
    flags: list[dict[str, object]] = []
    for ioc_id, ioc_type, value in conn.execute(
        sa.text(
            "SELECT id, type, value FROM iocs"
            " WHERE NOT auto_suppressed AND type IN ('domain', 'url', 'email', 'ip')"
        )
    ):
        reason = allowlist_match(ioc_type, value, allowlist)
        if reason is not None:
            flags.append({"id": ioc_id, "reason": reason})
    if flags:
        conn.execute(
            sa.text(
                "UPDATE iocs SET auto_suppressed = true, suppression_reason = :reason"
                " WHERE id = :id"
            ),
            flags,
        )
    return {"seeded": seeded.rowcount, "flagged": len(flags)}


def upgrade() -> None:
    conn = op.get_bind()
    iocs = canonicalize_and_merge(conn)
    feed = canonicalize_threat_feed(conn)
    allowlist = seed_and_flag_allowlist(conn)
    _log.info("canonical IOC: iocs=%s threat_feed=%s allowlist=%s", iocs, feed, allowlist)


def downgrade() -> None:
    """Tidak ada yang dibalik: merge kembaran dan penggantian nilai tidak bisa dikembalikan
    (nilai asli tidak disimpan), dan migrasi ini tidak membuat struktur baru. Entri seed dan
    tanda allowlist dibiarkan; analis bisa menghapusnya seperti biasa. Pemulihan penuh = restore
    backup Postgres yang diambil `make deploy`."""
