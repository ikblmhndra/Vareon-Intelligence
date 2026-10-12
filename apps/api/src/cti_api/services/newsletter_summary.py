"""Executive Summary newsletter dari recap MINGGUAN (ROADMAP #22, PR 8): SATU paragraf Indonesia
yang merangkum bulan sebuah edisi, disimpan di `newsletter_suggestions.summary_text`.

**Masukan hanya teks recap mingguan yang sudah tersimpan** (`kind='weekly'`, rentangnya beririsan
dengan jendela edisi): judul, narasi, story teratas, CVE/actor/kampanye penting, sinyal APAC. Tidak
pernah dari artikel mentah: recap sudah lolos grounding (PR 3), jadi paragraf ini tidak perlu
membaca ulang ribuan artikel, dan bulan tanpa recap menghasilkan teks KOSONG, bukan karangan.
Forecast sengaja tidak ikut: ringkasan ini tentang yang terjadi, dan newsletter tidak memuat
rekomendasi aksi maupun prediksi.

**Satu panggilan LLM per edisi.** Recap berbahasa Inggris (tetap, #21) dan paragrafnya Indonesia,
jadi sesuatu harus meringkas dan menerjemahkan sekaligus. Glosarium PR 6 (`newsletter_glossary`)
disuntik ke prompt dari konstanta yang sama dengan ringkasan artikel, supaya satu koreksi analis
berlaku di keduanya. Tanpa recap = TANPA panggilan.

**Grounding (modul bersama PR 3).** CVE id di paragraf yang tidak ada di teks recap yang dikirim ke
model diganti penanda `CVE_MARKER` dan dicatat di `summary_meta.dropped`. Penandanya Indonesia
(`[CVE tidak terverifikasi]`) karena paragrafnya Indonesia dan analis yang menyunting teks ini
harus langsung mengenalinya; recap sendiri tetap memakai `[unverified CVE]` bawaan modul itu.

**Ekor bulan.** Bulan yang tidak berakhir di hari Minggu punya hari-hari terakhir di pekan yang
BELUM selesai pada hari kerja pertama (November 2026 berakhir Senin 30 Nov, pekannya baru selesai
6 Des), dan recap pekan itu belum ada. Hari-hari itu tidak masuk paragraf (tetap masuk ranking
artikel), dan tidak dibuatkan recap harian untuk menambalnya. `summary_meta` mencatat pekan yang
dipakai, rentang yang dicakup, dan hari-hari jendela yang TIDAK dicakup (`uncovered`, juga untuk
pekan yang bolong di tengah), supaya composer bisa menampilkannya.

Bentuk `summary_meta` (selalu sama, juga saat tidak ada recap)::

    {
      "weeks": [{"week_start": "2026-09-28", "week_end": "2026-10-04"}, ...],  # yang dipakai
      "covered_start": "2026-09-28" | None,   # Senin pekan pertama yang dipakai
      "covered_end": "2026-11-01" | None,     # Minggu pekan terakhir yang dipakai
      "uncovered": [{"start": "2026-11-30", "end": "2026-11-30"}],  # hari jendela di luar pekan
      "model": "...",                          # "" kalau tanpa panggilan
      "token_usage": {...},                    # `usage_from` + `wall_ms` + `input_chars`;
                                               # {"skipped": true, "reason": "no_recaps"}
                                               # atau {"skipped": true, "reason": "llm_error"}
      "dropped": [{"field", "value", "reason"}],
      "parse_failed": false,                   # balasan model bukan JSON / tanpa `summary`
      "error": null                            # "<NamaException>: <pesan>" kalau panggilan gagal
    }

**Panggilan LLM yang gagal tidak membuang ranking.** Exception dari panggilan itu (gateway mati,
timeout, apa pun) ditangkap: teks kosong, `token_usage = {"skipped": true, "reason":
"llm_error"}`, `error` terisi (`NamaException: pesan`, pesannya dipotong `ERROR_CLIP` karakter),
dan log peringatan `newsletter_summary_failed`. Pemanggil tetap menyimpan barisnya dengan ranking,
dan hari kerja berikutnya di jendela kejar mengulang HANYA langkah ini
(`newsletter_suggestion.refresh_summary`). Hanya panggilan LLM-nya yang ditangkap: kesalahan DB
dan sejenisnya tetap naik. Pesan exception dicatat apa adanya (terpotong); pesan gateway yang
menolak kredensial kadang memuat potongan kunci yang sudah disamarkan oleh gateway-nya.

Rentang pekan yang dipakai boleh melewati batas bulan (pekan 28 Sep-4 Okt dipakai utuh untuk
edisi Oktober): `covered_*` adalah batas PEKAN, bukan batas bulan."""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Any

import structlog
from cti_core.db.models.recap import DailyRecap
from cti_core.db.repositories.recap import AsyncRecapRepo
from cti_core.llm.client import get_llm_client, parse_json_response, usage_from
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import grounding, newsletter_edition, newsletter_glossary

log = structlog.get_logger()

CVE_MARKER = "[CVE tidak terverifikasi]"
"""Pengganti CVE id karangan di paragraf (lihat docstring modul)."""

ERROR_CLIP = 200
"""Panjang maksimum pesan exception yang disimpan di `summary_meta.error`."""

_ONE_DAY = datetime.timedelta(days=1)

_SYSTEM_PROMPT_HEAD = "\n".join(
    [
        "You write the Executive Summary of a monthly cyber threat intelligence newsletter for a "
        "security leadership audience.",
        "",
        "The input is a set of weekly recaps (in English) that our analysts wrote for the weeks of "
        "one month. Condense them into ONE paragraph of about 100-130 words, written in "
        "Indonesian (Bahasa Indonesia).",
        "",
        "Rules:",
        "- One paragraph of plain prose: no bullet points, no headings, no line breaks, and no "
        "week-by-week or day-by-day walk-through. Lead with the biggest developments and the "
        "trend across the whole period.",
        "- Use ONLY what the recaps say. Never add facts, figures, dates, CVE IDs, threat actor "
        "names, product names or campaigns that are not in them. If the recaps say little, write "
        "a shorter paragraph instead of padding it.",
        "- Do not give recommendations or recommended actions, and do not make forecasts.",
        '- Leave out anything the recaps mark as "[unverified CVE]".',
        "- Weeks at the edge of the month may include a few days of the neighbouring month; "
        "treat them as part of the period.",
        "",
        'Output STRICT JSON (no markdown, no code fences): {"summary": "<the paragraph>"}',
    ]
)


def _language_rules() -> str:
    """Aturan bahasa dari konstanta glosarium PR 6 (bukan `language_instructions`, yang menyebut
    kunci `key_points` milik prompt ringkasan artikel; di sini kuncinya hanya `summary`)."""
    return "\n".join(
        [
            "Write the paragraph in a clear, professional register.",
            "Copy these exactly as they appear in the recaps; never translate or transliterate "
            "them: " + "; ".join(newsletter_glossary.KEEP_AS_WRITTEN) + ".",
            "Leave these terms in English: " + ", ".join(newsletter_glossary.KEEP_IN_ENGLISH) + ".",
            "Use these Indonesian renderings for recurring terms so the wording stays consistent "
            "between editions:",
            *(f"- {en}: {id_}" for en, id_ in newsletter_glossary.TRANSLATIONS),
        ]
    )


def system_prompt() -> str:
    return _SYSTEM_PROMPT_HEAD + "\n" + _language_rules()


def _texts(value: object) -> list[str]:
    """Hanya string tak kosong dari sebuah daftar: isi recap berasal dari LLM, jadi bentuknya
    tidak dipercaya (daftar yang berisi objek, angka, atau bukan daftar sama sekali)."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dicts(value: object) -> list[dict[str, Any]]:
    """Hanya objek dari sebuah daftar (`top_stories`, `active_campaigns`), alasannya sama."""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _week_of(row: DailyRecap) -> tuple[datetime.date, datetime.date]:
    day = datetime.date.fromisoformat(row.date)
    return row.period_start or day, row.period_end or day


def _recap_block(row: DailyRecap) -> str:
    """Teks satu recap untuk prompt; kosong kalau recap itu tidak punya apa-apa untuk diringkas
    (balasan model yang gagal di-parse disimpan dengan judul dan isi kosong): pekan itu lalu
    dianggap tidak ada, dan muncul di `uncovered`."""
    recap = row.yesterday if isinstance(row.yesterday, dict) else {}
    headline, narrative = _text(row.headline), _text(recap.get("summary"))
    if not headline and not narrative:
        return ""
    start, end = _week_of(row)
    lines = [f"=== Week {start.isoformat()} to {end.isoformat()} ==="]
    if headline:
        lines.append(f"Headline: {headline}")
    if narrative:
        lines.append(f"Summary: {narrative}")
    stories = [
        f"- {title}: {why}" if (why := _text(s.get("why_it_matters"))) else f"- {title}"
        for s in _dicts(recap.get("top_stories"))
        if (title := _text(s.get("title")))
    ]
    if stories:
        lines += ["Top stories:", *stories]
    actors = _texts(recap.get("active_threat_actors"))
    if actors:
        lines.append("Active threat actors: " + ", ".join(actors))
    campaigns = [t for c in _dicts(recap.get("active_campaigns")) if (t := _text(c.get("theme")))]
    if campaigns:
        lines.append("Active campaigns: " + "; ".join(campaigns))
    cves = _texts(recap.get("notable_cves"))
    if cves:
        lines.append("Notable CVEs: " + ", ".join(cves))
    apac = _texts(recap.get("apac_signals"))
    if apac:
        lines.append("APAC signals: " + "; ".join(apac))
    return "\n".join(lines)


def build_user_message(
    period_start: datetime.date, period_end: datetime.date, blocks: list[str]
) -> str:
    """Pesan user: edisi yang dirangkum, lalu blok tiap recap. Teks inilah yang menjadi `Known`
    grounding, jadi semua yang boleh muncul di paragraf harus ada di sini."""
    label = newsletter_edition.period_label(period_start, period_end)
    span = newsletter_edition.period_range(period_start, period_end)
    return "\n\n".join([f"Edition: {label} ({span})", f"Weekly recaps ({len(blocks)}):", *blocks])


def uncovered_days(
    period_start: datetime.date,
    period_end: datetime.date,
    weeks: list[tuple[datetime.date, datetime.date]],
) -> list[dict[str, str]]:
    """Rentang hari jendela (inklusif) yang tidak termasuk pekan mana pun di `weeks`: ekor bulan
    yang pekannya belum selesai, dan pekan bolong di tengah."""
    gaps: list[dict[str, str]] = []
    cursor = period_start
    for week_start, week_end in sorted(weeks):
        if week_start > cursor:
            last = min(week_start - _ONE_DAY, period_end)
            gaps.append({"start": cursor.isoformat(), "end": last.isoformat()})
        cursor = max(cursor, week_end + _ONE_DAY)
        if cursor > period_end:
            break
    if cursor <= period_end:
        gaps.append({"start": cursor.isoformat(), "end": period_end.isoformat()})
    return gaps


def _call_llm(user_message: str) -> tuple[str, str, dict[str, int]]:
    """`(isi balasan, nama model, pemakaian)`: `usage_from` (kosong kalau gateway tidak mengirim
    `usage`) plus `wall_ms` dan `input_chars`, supaya ukuran panggilan tetap terlihat walau gateway
    diam. Sinkron, dijalankan di thread (`asyncio.to_thread`)."""
    client, model_name = get_llm_client()
    started = time.monotonic()
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
        n=1,
    )
    wall_ms = int((time.monotonic() - started) * 1000)
    usage = {**usage_from(completion), "wall_ms": wall_ms, "input_chars": len(user_message)}
    return completion.choices[0].message.content or "", model_name, usage


def _paragraph(raw: str) -> str:
    """Nilai `summary` dari balasan model sebagai SATU paragraf (spasi dan baris baru dilebur);
    kosong kalau balasannya bukan JSON, tanpa `summary`, atau bukan string."""
    try:
        parsed = parse_json_response(raw)
    except Exception:
        return ""
    value = parsed.get("summary") if isinstance(parsed, dict) else None
    return " ".join(value.split()) if isinstance(value, str) else ""


def _describe(exc: Exception) -> str:
    """`NamaException: pesan` untuk `summary_meta.error`; pesannya dilebur jadi satu baris dan
    dipotong, supaya balasan error gateway yang panjang tidak membengkakkan baris saran."""
    message = " ".join(str(exc).split())[:ERROR_CLIP]
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


async def generate_executive_summary(
    session: AsyncSession, period_start: datetime.date, period_end: datetime.date
) -> tuple[str, dict[str, Any]]:
    """`(summary_text, summary_meta)` untuk jendela edisi. Tidak menulis apa pun ke DB: pemanggil
    (`newsletter_suggestion.build_suggestion`) menyimpannya di baris saran.

    Tanpa recap mingguan yang bisa dipakai: teks kosong dan TANPA panggilan LLM. Panggilan yang
    gagal (exception apa pun dari panggilan itu) menghasilkan teks kosong dan `error` terisi,
    bukan exception: saran tidak boleh kehilangan rankingnya karena gateway sedang mati (lihat
    docstring modul)."""
    rows = await AsyncRecapRepo(session).list_overlapping("weekly", period_start, period_end)
    used = [(row, block) for row in rows if (block := _recap_block(row))]
    weeks = sorted(_week_of(row) for row, _ in used)
    meta: dict[str, Any] = {
        "weeks": [{"week_start": s.isoformat(), "week_end": e.isoformat()} for s, e in weeks],
        "covered_start": weeks[0][0].isoformat() if weeks else None,
        "covered_end": max(e for _, e in weeks).isoformat() if weeks else None,
        "uncovered": uncovered_days(period_start, period_end, weeks),
        "model": "",
        "dropped": [],
        "parse_failed": False,
        "error": None,
    }
    if not used:
        return "", {**meta, "token_usage": {"skipped": True, "reason": "no_recaps"}}

    user_message = build_user_message(period_start, period_end, [block for _, block in used])
    try:
        raw, model_name, token_usage = await asyncio.to_thread(_call_llm, user_message)
    except Exception as exc:
        error = _describe(exc)
        log.warning("newsletter_summary_failed", error=error, weeks_used=len(weeks))
        return "", {**meta, "token_usage": {"skipped": True, "reason": "llm_error"}, "error": error}
    text = _paragraph(raw)
    grounder = grounding.Grounder(grounding.Known.build(text=user_message), cve_marker=CVE_MARKER)
    text = grounder.free_text("summary", text)
    if not text:
        log.warning("newsletter_summary_unparsed", raw=raw[:500])
    return text, {
        **meta,
        "model": model_name,
        "token_usage": token_usage,
        "dropped": grounder.report()["dropped"],
        "parse_failed": not text,
    }
